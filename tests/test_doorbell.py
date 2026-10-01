"""Tests für die Funktion Türklingel."""

from datetime import datetime, timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import is_menu, menu_options, make_entry, reconfigure
from custom_components.ha_housekeeper.const import DOMAIN
from custom_components.ha_housekeeper.doorbell import (
    assign_players,
    in_window,
    profile_summary,
)

TRIGGER = "binary_sensor.bell"
ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MEDIA = {"media_content_id": "media-source://media_source/local/bell.mp3",
         "media_content_type": "audio/mpeg"}
DAY_TTS = {"id": "p1", "name": "Tag", "from": "07:00:00", "to": "22:00:00",
           "weekdays": ALL_DAYS, "players": ["media_player.kitchen"], "mode": "tts",
           "tts_entity": "tts.home", "text": "Es klingelt", "volume": 0,
           "mobile_enabled": True, "mobile_targets": ["mobile_app_phone"],
           "message": "Ding", "clear_after_hours": 1}
PUSH_ALL = {"id": "p4", "name": "Push", "from": "00:00:00", "to": "00:00:00",
            "weekdays": ALL_DAYS, "players": [], "mobile_enabled": True,
            "mobile_targets": ["mobile_app_phone"], "message": "Nur Push", "clear_after_hours": 1}
NIGHT_RING = {"id": "p2", "name": "Nacht", "from": "22:00:00", "to": "06:00:00",
              "weekdays": ["fri"], "players": ["media_player.bedroom"], "mode": "ringtone",
              "media": MEDIA, "volume": 30}
ALL_DAY = {"id": "p3", "name": "Immer", "from": "00:00:00", "to": "00:00:00",
           "weekdays": ALL_DAYS, "players": ["media_player.kitchen", "media_player.hall"],
           "mode": "ringtone", "media": MEDIA, "volume": 0}
BASE = {
    "function_type": "doorbell", "name": "Bell", "trigger_entity": TRIGGER,
    "debounce_seconds": 10, "profiles": [DAY_TTS],
}


def _at(hour: int, minute: int = 0, weekday: int = 2) -> datetime:
    """Zeitpunkt an einem Wochentag (0 = Montag); 2024-01-01 war ein Montag."""
    return datetime(2024, 1, 1 + weekday, hour, minute, tzinfo=dt_util.DEFAULT_TIME_ZONE)


async def _setup(hass: HomeAssistant, **over):
    entry = make_entry(domain=DOMAIN, title="Bell", data={**BASE, **over})
    entry.add_to_hass(hass)
    hass.states.async_set(over.get("trigger_entity", TRIGGER), "off")
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry


def _mocks(hass: HomeAssistant):
    return {
        "push": async_mock_service(hass, "notify", "mobile_app_phone"),
        "tts": async_mock_service(hass, "tts", "speak"),
        "play": async_mock_service(hass, "media_player", "play_media"),
        "volume": async_mock_service(hass, "media_player", "volume_set"),
    }


async def _ring(hass: HomeAssistant, now: datetime, entity: str = TRIGGER) -> None:
    with patch("custom_components.ha_housekeeper.doorbell.dt_util.now", return_value=now):
        hass.states.async_set(entity, "on")
        await hass.async_block_till_done()


# --- reine Logik ------------------------------------------------------------------


def test_in_window_daytime() -> None:
    assert in_window(DAY_TTS, _at(12))
    assert in_window(DAY_TTS, _at(7))
    assert not in_window(DAY_TTS, _at(22))
    assert not in_window(DAY_TTS, _at(6, 59))


def test_in_window_over_midnight_belongs_to_start_day() -> None:
    friday, saturday, thursday = 4, 5, 3
    assert in_window(NIGHT_RING, _at(23, weekday=friday))
    assert in_window(NIGHT_RING, _at(5, weekday=saturday))      # gehört zu Freitag
    assert not in_window(NIGHT_RING, _at(5, weekday=friday))    # Donnerstag-Nacht
    assert not in_window(NIGHT_RING, _at(23, weekday=thursday))
    assert not in_window(NIGHT_RING, _at(12, weekday=friday))


def test_in_window_all_day_and_weekday() -> None:
    assert in_window(ALL_DAY, _at(3))
    assert not in_window({**ALL_DAY, "weekdays": ["mon"]}, _at(3, weekday=2))


def test_assign_players_dedupes_first_profile_wins() -> None:
    result = assign_players([DAY_TTS, ALL_DAY], _at(12))
    assert [(p["id"], players) for p, players in result] == [
        ("p1", ["media_player.kitchen"]),
        ("p3", ["media_player.hall"]),
    ]
    assert assign_players([DAY_TTS], _at(23)) == []


# --- Config-Flow ------------------------------------------------------------------


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "hub_doorbell"}
    )
    assert result["step_id"] == "new_doorbell"
    data = {k: v for k, v in BASE.items() if k not in ("function_type", "profiles")}
    ok = await hass.config_entries.flow.async_configure(result["flow_id"], {"general": data})
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["function_type"] == "doorbell" and ok["subentries"][0]["data"]["profiles"] == []


# --- Klingeln -----------------------------------------------------------------------


async def test_ring_tts_and_push_in_window(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass)
    await _ring(hass, _at(12))
    assert len(m["tts"]) == 1
    data = m["tts"][0].data
    assert data["entity_id"] == "tts.home" and data["message"] == "Es klingelt"
    assert data["media_player_entity_id"] == ["media_player.kitchen"]
    assert len(m["push"]) == 1 and m["push"][0].data["message"] == "Ding"
    assert m["play"] == [] and m["volume"] == []
    assert hass.states.get("sensor.bell_last_ring").state != "unknown"


async def test_ring_outside_window_only_push(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass, profiles=[DAY_TTS, PUSH_ALL])
    await _ring(hass, _at(23))
    assert m["tts"] == [] and m["play"] == []
    assert len(m["push"]) == 1 and m["push"][0].data["message"] == "Nur Push"


async def test_ringtone_with_volume(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass, profiles=[NIGHT_RING])
    await _ring(hass, _at(23, weekday=4))
    assert len(m["volume"]) == 1
    assert m["volume"][0].data["volume_level"] == 0.3
    assert m["volume"][0].data["entity_id"] == ["media_player.bedroom"]
    assert len(m["play"]) == 1
    assert m["play"][0].data["media_content_id"] == MEDIA["media_content_id"]
    assert m["play"][0].data["media_content_type"] == "audio/mpeg"


async def test_dedupe_between_matching_profiles(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass, profiles=[DAY_TTS, ALL_DAY])
    await _ring(hass, _at(12))
    assert m["tts"][0].data["media_player_entity_id"] == ["media_player.kitchen"]
    assert m["play"][0].data["entity_id"] == ["media_player.hall"]


async def test_debounce(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass)
    await _ring(hass, _at(12))
    hass.states.async_set(TRIGGER, "off")
    await _ring(hass, _at(12))
    assert len(m["push"]) == 1


async def test_event_entity_trigger(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass, trigger_entity="event.bell")
    hass.states.async_set("event.bell", "unknown")          # Start: ignorieren
    hass.states.async_set("event.bell", "2024-01-03T12:00:00+00:00")
    await hass.async_block_till_done()
    assert m["push"] == []
    with patch("custom_components.ha_housekeeper.doorbell.dt_util.now", return_value=_at(12)):
        hass.states.async_set("event.bell", "2024-01-03T12:00:30+00:00")
        await hass.async_block_till_done()
    assert len(m["push"]) == 1 and len(m["tts"]) == 1


async def test_switch_off_is_silent(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.bell_doorbell_active"}, blocking=True
    )
    await _ring(hass, _at(12))
    assert m["push"] == [] and m["tts"] == []
    assert hass.states.get("switch.bell_doorbell_active").state == "off"


async def test_push_cleared_after_hours(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass)
    await _ring(hass, _at(12))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=59))
    await hass.async_block_till_done()
    assert len(m["push"]) == 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1, minutes=1))
    await hass.async_block_till_done()
    assert len(m["push"]) == 2
    assert m["push"][1].data["message"] == "clear_notification"
    assert m["push"][1].data["data"]["tag"] == m["push"][0].data["data"]["tag"]


async def test_no_clear_when_zero_hours(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass, profiles=[{**DAY_TTS, "clear_after_hours": 0}])
    await _ring(hass, _at(12))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=30))
    await hass.async_block_till_done()
    assert len(m["push"]) == 1


async def test_push_disabled_audio_only(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass, profiles=[{**DAY_TTS, "mobile_enabled": False}])
    await _ring(hass, _at(12))
    assert m["push"] == [] and len(m["tts"]) == 1


async def test_test_button_bypasses_switch_and_debounce(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.bell_doorbell_active"}, blocking=True
    )
    with patch("custom_components.ha_housekeeper.doorbell.dt_util.now", return_value=_at(12)):
        for _ in range(2):
            await hass.services.async_call(
                "button", "press", {"entity_id": "button.bell_test_ring"}, blocking=True
            )
    assert len(m["push"]) == 2 and len(m["tts"]) == 2
    assert hass.states.get("sensor.bell_last_ring").state == "unknown"


# --- Options-Flow ------------------------------------------------------------------


async def test_options_flow_profiles(hass: HomeAssistant) -> None:
    _mocks(hass)
    entry = await _setup(hass, profiles=[])
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    assert is_menu(result) and result["step_id"] == "bell_menu"
    assert "edit_profile" not in menu_options(result)

    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_profile"})
    schema = result["data_schema"].schema
    assert [str(k) for k in schema] == ["timing", "sound", "notifications"]

    def form(timing=None, sound=None, notifications=None):
        return {
            "timing": {"name": "Tag", "enabled": True, "from": "07:00:00", "to": "22:00:00",
                       "weekdays": ALL_DAYS, **(timing or {})},
            "sound": {"mode": "tts", "volume": 0, **(sound or {})},
            "notifications": {"mobile_enabled": False, "message": "Ding",
                              "clear_after_hours": 1, **(notifications or {})},
        }

    bad = await flow.async_configure(result["flow_id"], form())
    assert bad["errors"] == {"base": "no_output"}
    bad = await flow.async_configure(
        bad["flow_id"], form(notifications={"mobile_enabled": True}))
    assert bad["errors"] == {"base": "no_targets"}
    bad = await flow.async_configure(
        bad["flow_id"], form(sound={"players": ["media_player.kitchen"]}))
    assert bad["errors"] == {"base": "no_tts"}
    bad = await flow.async_configure(
        bad["flow_id"], form(sound={"players": ["media_player.kitchen"], "mode": "ringtone"}))
    assert bad["errors"] == {"base": "no_ringtone"}
    result = await flow.async_configure(
        bad["flow_id"],
        form(sound={"players": ["media_player.kitchen"], "tts_entity": "tts.home",
                    "text": "Hallo", "volume": 20},
             notifications={"mobile_enabled": True, "mobile_targets": ["mobile_app_phone"]}))
    assert is_menu(result)
    assert len(entry.options["profiles"]) == 1
    tts_profile = entry.options["profiles"][0]
    assert tts_profile["text"] == "Hallo" and tts_profile["mode"] == "tts"
    assert tts_profile["mobile_enabled"] is True
    assert tts_profile["mobile_targets"] == ["mobile_app_phone"]
    assert tts_profile["message"] == "Ding" and tts_profile["clear_after_hours"] == 1

    # Profil auf Klingelton umstellen: alte TTS-Schlüssel verschwinden
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "edit_profile"})
    result = await flow.async_configure(result["flow_id"], {"profile": tts_profile["id"]})
    result = await flow.async_configure(
        result["flow_id"],
        form(sound={"players": ["media_player.kitchen"], "mode": "ringtone", "media": MEDIA}))
    profile = entry.options["profiles"][0]
    assert profile["id"] == tts_profile["id"] and profile["mode"] == "ringtone"
    assert "text" not in profile and "tts_entity" not in profile
    assert profile["media"]["media_content_id"] == MEDIA["media_content_id"]
    assert "Tag" in profile_summary(hass, profile)

    # Profil nur mit Push: kein Ton, keine Player
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_profile"})
    result = await flow.async_configure(
        result["flow_id"],
        form(timing={"name": "Nur Push"},
             notifications={"mobile_enabled": True, "mobile_targets": ["mobile_app_phone"]}))
    push_only = entry.options["profiles"][1]
    assert push_only["players"] == [] and "mode" not in push_only
    assert "Push" in profile_summary(hass, push_only)

    result = await flow.async_configure(result["flow_id"], {"next_step_id": "delete_profile"})
    result = await flow.async_configure(result["flow_id"], {"profile": profile["id"]})
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "delete_profile"})
    result = await flow.async_configure(result["flow_id"], {"profile": push_only["id"]})
    assert entry.options["profiles"] == []


# --- Push je Profil ------------------------------------------------------------------


async def test_all_matching_profiles_push_equally(hass: HomeAssistant) -> None:
    other = async_mock_service(hass, "notify", "mobile_app_tablet")
    m = _mocks(hass)
    second = {**PUSH_ALL, "mobile_targets": ["mobile_app_phone", "mobile_app_tablet"],
              "message": "Zweites"}
    await _setup(hass, profiles=[DAY_TTS, second])
    await _ring(hass, _at(12))
    assert [c.data["message"] for c in m["push"]] == ["Ding"]      # Handy: erstes Profil
    assert [c.data["message"] for c in other] == ["Zweites"]       # Tablet: zweites Profil


async def test_profile_without_push_sends_nothing(hass: HomeAssistant) -> None:
    m = _mocks(hass)
    await _setup(hass, profiles=[{**DAY_TTS, "mobile_enabled": False}, PUSH_ALL])
    await _ring(hass, _at(12))
    assert len(m["tts"]) == 1 and [c.data["message"] for c in m["push"]] == ["Nur Push"]


async def test_each_profile_clears_with_its_own_hours(hass: HomeAssistant) -> None:
    other = async_mock_service(hass, "notify", "mobile_app_tablet")
    m = _mocks(hass)
    second = {**PUSH_ALL, "mobile_targets": ["mobile_app_tablet"], "clear_after_hours": 3}
    await _setup(hass, profiles=[DAY_TTS, second])
    await _ring(hass, _at(12))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1, minutes=1))
    await hass.async_block_till_done()
    assert m["push"][-1].data["message"] == "clear_notification" and len(other) == 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=3, minutes=1))
    await hass.async_block_till_done()
    assert other[-1].data["message"] == "clear_notification"
