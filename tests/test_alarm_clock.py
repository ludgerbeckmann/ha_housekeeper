"""Tests für die Funktion Wecker."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.ha_housekeeper import alarm_clock as ac
from custom_components.ha_housekeeper.const import DOMAIN

from .helpers import is_menu, menu_options, sectioned

PLAYER = "media_player.bedroom"
MEDIA = {"media_content_id": "media-source://media_source/local/wecker.mp3",
         "media_content_type": "audio/mpeg"}
ACTION_STOP = "HOUSEKEEPER_ALARM_STOP_"
ACTION_SNOOZE = "HOUSEKEEPER_ALARM_SNOOZE_"


def alarm(i="a1", **over):
    return {"id": i, "name": "Aufstehen", "enabled": True, "time": "07:00:00",
            "weekdays": ["mon", "tue", "wed", "thu", "fri"], "players": [PLAYER],
            "media": MEDIA, "volume": 30, "snooze_minutes": 9, "auto_stop_minutes": 30, **over}


class Env:
    """Gemockte Dienste."""

    def __init__(self, hass):
        self.volume = async_mock_service(hass, "media_player", "volume_set")
        self.play = async_mock_service(hass, "media_player", "play_media")
        self.stop = async_mock_service(hass, "media_player", "media_stop")
        self.push = async_mock_service(hass, "notify", "mobile_app_phone")


async def _setup(hass, alarms, freezer=None, now="2026-01-05 06:59:58+01:00", **over):
    """Montag 2026-01-05, kurz vor 07:00."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.config.language = "en"
    if freezer is not None:
        freezer.move_to(now)
    hass.states.async_set(PLAYER, "idle", {"volume_level": 0.5})
    env = Env(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, title="Wecker",
        data={"function_type": "alarm_clock", "name": "Wecker", "mobile_enabled": True,
              "mobile_targets": ["mobile_app_phone"], "critical": True, "message": "Wecker",
              "alarms": alarms, **over},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id], env


async def _advance(hass, freezer, **delta):
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


# --- reine Logik ---------------------------------------------------------------------------


async def test_next_alarm_and_summary(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    now = dt_util.now().replace(year=2026, month=1, day=5, hour=12, minute=0, second=0, microsecond=0)  # Montag
    weekdays = alarm(time="07:00:00")
    sat = alarm("a2", time="09:30:00", weekdays=["sat"])
    when, found = ac.next_alarm([weekdays, sat], now)
    assert found["id"] == "a1" and when.day == 6 and when.hour == 7        # Dienstag
    when, found = ac.next_alarm([sat, alarm("a3", enabled=False)], now)
    assert found["id"] == "a2" and when.weekday() == 5
    assert ac.next_alarm([alarm(enabled=False)], now) is None
    # heute, aber die Uhrzeit ist schon vorbei: nächster passender Tag
    assert ac.next_alarm([alarm(weekdays=["mon"], time="11:00:00")], now)[0].day == 12
    hass.config.language = "en"
    assert ac.alarm_summary(hass, weekdays) == "Aufstehen: 07:00 (mon, tue, wed, thu, fri), 1 players, 30 %"
    hass.config.language = "de"
    assert "Player" in ac.alarm_summary(hass, alarm(weekdays=list(ac.WEEKDAYS), enabled=False))


def test_critical_data() -> None:
    data = ac.critical_data()
    assert data["push"]["interruption-level"] == "critical"
    assert data["push"]["sound"]["critical"] == 1
    assert data["channel"] == "alarm_stream" and data["ttl"] == 0 and data["priority"] == "high"


# --- Ablauf ---------------------------------------------------------------------------------------


async def test_ring_sets_volume_plays_and_sends_critical_push(hass: HomeAssistant, freezer) -> None:
    entry, ctrl, env = await _setup(hass, [alarm()], freezer)
    assert hass.states.get("binary_sensor.wecker_alarm_ringing").state == "off"
    assert hass.states.get("sensor.wecker_next_alarm") is not None
    await _advance(hass, freezer, seconds=3)
    assert ctrl.ringing and hass.states.get("binary_sensor.wecker_alarm_ringing").state == "on"
    assert [c.data for c in env.volume] == [{"entity_id": [PLAYER], "volume_level": 0.3}]
    assert [c.data for c in env.play] == [{
        "entity_id": [PLAYER], "media_content_id": MEDIA["media_content_id"],
        "media_content_type": "audio/mpeg"}]
    (push,) = env.push
    assert push.data["message"] == "Wecker: Aufstehen"
    data = push.data["data"]
    assert [a["action"] for a in data["actions"]] == [ACTION_STOP + entry.entry_id, ACTION_SNOOZE + entry.entry_id]
    assert [a["title"] for a in data["actions"]] == ["Stop", "Snooze"]
    assert data["push"]["interruption-level"] == "critical" and data["channel"] == "alarm_stream"
    assert data["tag"].startswith("ha_housekeeper_")
    assert hass.states.get("sensor.wecker_last_alarm").attributes["alarm"] == "Aufstehen"


async def test_not_critical_when_disabled(hass: HomeAssistant, freezer) -> None:
    _, _, env = await _setup(hass, [alarm()], freezer, critical=False)
    await _advance(hass, freezer, seconds=3)
    assert "push" not in env.push[0].data["data"] and "channel" not in env.push[0].data["data"]
    assert "actions" in env.push[0].data["data"]


async def test_stop_restores_original_volume(hass: HomeAssistant, freezer) -> None:
    entry, ctrl, env = await _setup(hass, [alarm()], freezer)
    await _advance(hass, freezer, seconds=3)
    hass.bus.async_fire("mobile_app_notification_action", {"action": ACTION_STOP + entry.entry_id})
    await hass.async_block_till_done()
    assert not ctrl.active and hass.states.get("binary_sensor.wecker_alarm_ringing").state == "off"
    assert [c.data for c in env.stop] == [{"entity_id": [PLAYER]}]
    assert env.volume[-1].data == {"entity_id": PLAYER, "volume_level": 0.5}      # ursprüngliche Lautstärke
    assert env.push[-1].data["message"] == "clear_notification"
    # Button bei nichts Laufendem ändert nichts
    await hass.services.async_call("button", "press", {"entity_id": "button.wecker_stop_alarm"}, blocking=True)
    assert len(env.stop) == 1


async def test_snooze_restores_volume_and_rings_again(hass: HomeAssistant, freezer) -> None:
    entry, ctrl, env = await _setup(hass, [alarm()], freezer)
    await _advance(hass, freezer, seconds=3)
    hass.bus.async_fire("mobile_app_notification_action", {"action": ACTION_SNOOZE + entry.entry_id})
    await hass.async_block_till_done()
    assert ctrl.phase == "snoozed" and not ctrl.ringing
    assert hass.states.get("binary_sensor.wecker_alarm_ringing").state == "off"
    assert hass.states.get("binary_sensor.wecker_alarm_ringing").attributes["snoozed"] is True
    assert len(env.stop) == 1 and env.volume[-1].data["volume_level"] == 0.5
    assert env.push[-1].data["message"] == "clear_notification"
    # Der Player hat zwischendurch eine andere Lautstärke: sie wird beim nächsten Klingeln neu gemerkt
    hass.states.async_set(PLAYER, "idle", {"volume_level": 0.2})
    await _advance(hass, freezer, minutes=8)
    assert ctrl.phase == "snoozed" and len(env.play) == 1
    await _advance(hass, freezer, minutes=2)
    assert ctrl.ringing and len(env.play) == 2
    assert env.volume[-1].data == {"entity_id": [PLAYER], "volume_level": 0.3}
    assert env.push[-1].data["message"] == "Wecker: Aufstehen" and "actions" in env.push[-1].data["data"]
    await hass.services.async_call("button", "press", {"entity_id": "button.wecker_stop_alarm"}, blocking=True)
    assert env.volume[-1].data == {"entity_id": PLAYER, "volume_level": 0.2}


async def test_snooze_button_and_stop_while_snoozed(hass: HomeAssistant, freezer) -> None:
    _, ctrl, env = await _setup(hass, [alarm()], freezer)
    await _advance(hass, freezer, seconds=3)
    await hass.services.async_call("button", "press", {"entity_id": "button.wecker_snooze_alarm"}, blocking=True)
    assert ctrl.phase == "snoozed" and ctrl.snooze_until is not None
    await hass.services.async_call("button", "press", {"entity_id": "button.wecker_stop_alarm"}, blocking=True)
    assert not ctrl.active
    await _advance(hass, freezer, minutes=20)          # kein erneutes Klingeln nach dem Stoppen
    assert len(env.play) == 1


async def test_auto_stop(hass: HomeAssistant, freezer) -> None:
    _, ctrl, env = await _setup(hass, [alarm(auto_stop_minutes=5)], freezer)
    await _advance(hass, freezer, seconds=3)
    assert ctrl.ringing
    await _advance(hass, freezer, minutes=6)
    assert not ctrl.active and env.volume[-1].data["volume_level"] == 0.5
    assert len(env.stop) == 1


async def test_no_auto_stop_when_zero(hass: HomeAssistant, freezer) -> None:
    _, ctrl, _ = await _setup(hass, [alarm(auto_stop_minutes=0)], freezer)
    await _advance(hass, freezer, seconds=3)
    await _advance(hass, freezer, hours=3)
    assert ctrl.ringing


async def test_weekday_enabled_and_pause(hass: HomeAssistant, freezer) -> None:
    # Samstag: der Wecker gilt nur Montag bis Freitag
    _, ctrl, env = await _setup(hass, [alarm()], freezer, now="2026-01-10 06:59:58+01:00")
    await _advance(hass, freezer, seconds=3)
    assert not ctrl.active and env.play == []

    # Wecker einzeln deaktiviert
    _, _, env2 = await _setup(hass, [alarm("b1", enabled=False)], freezer, now="2026-01-05 06:59:58+01:00")
    await _advance(hass, freezer, seconds=3)
    assert env2.play == []


async def test_switch_off_pauses_and_stops_ringing(hass: HomeAssistant, freezer) -> None:
    entry, ctrl, env = await _setup(hass, [alarm()], freezer)
    await _advance(hass, freezer, seconds=3)
    assert ctrl.ringing
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.wecker_alarm_clock_active"}, blocking=True)
    assert not ctrl.active and env.volume[-1].data["volume_level"] == 0.5
    assert hass.states.get("sensor.wecker_next_alarm").state == "unknown"
    # Pause bleibt nach dem Neuladen erhalten
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert hass.states.get("switch.wecker_alarm_clock_active").state == "off"


async def test_new_alarm_replaces_running_one(hass: HomeAssistant, freezer) -> None:
    second = alarm("a2", name="Zweiter", time="07:01:00", volume=50)
    _, ctrl, env = await _setup(hass, [alarm(), second], freezer)
    await _advance(hass, freezer, seconds=3)
    assert ctrl.current["id"] == "a1"
    await _advance(hass, freezer, minutes=1)
    assert ctrl.current["id"] == "a2" and ctrl.ringing
    # Lautstärke: erst zurückgesetzt, dann neu gemerkt und gesetzt
    assert [c.data["volume_level"] for c in env.volume] == [0.3, 0.5, 0.5]


async def test_volume_restored_after_restart_while_ringing(hass: HomeAssistant, freezer) -> None:
    entry, ctrl, env = await _setup(hass, [alarm()], freezer)
    await _advance(hass, freezer, seconds=3)
    store = {"enabled": True, "last_ring": None, "last_alarm": "Aufstehen", "restore": {PLAYER: 0.5}}
    assert ctrl._restore == {PLAYER: 0.5}                                          # noqa: SLF001
    # Neustart simulieren: Zustand mit offener Wiederherstellung
    await hass.config_entries.async_unload(entry.entry_id)
    env.volume.clear()
    from homeassistant.helpers.storage import Store
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_save(store)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert env.volume and env.volume[0].data == {"entity_id": PLAYER, "volume_level": 0.5}
    assert hass.data[DOMAIN][entry.entry_id]._restore == {}                        # noqa: SLF001


async def test_unknown_original_volume_is_not_reset(hass: HomeAssistant, freezer) -> None:
    _, ctrl, env = await _setup(hass, [alarm()], freezer)
    hass.states.async_set(PLAYER, "idle", {})               # Player meldet keine Lautstärke
    await _advance(hass, freezer, seconds=3)
    await ctrl.async_stop_alarm()
    assert [c.data["volume_level"] for c in env.volume] == [0.3]     # nur das Setzen, kein Zurücksetzen


# --- Config- und Options-Flow -----------------------------------------------------------------------


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "alarm_clock"})
    assert result["step_id"] == "alarm_clock"
    schema = result["data_schema"].schema
    assert [str(k) for k in schema] == ["general", "notifications"]
    base = {"name": "Wecker", "mobile_enabled": True, "critical": True, "message": "Wecker"}
    bad = await hass.config_entries.flow.async_configure(result["flow_id"], sectioned(base))
    assert bad["errors"] == {"base": "no_targets"}
    ok = await hass.config_entries.flow.async_configure(
        result["flow_id"], sectioned({**base, "mobile_targets": ["mobile_app_phone"]}))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["function_type"] == "alarm_clock" and ok["data"]["alarms"] == []
    assert ok["data"]["critical"] is True


async def test_options_flow_add_edit_delete_alarm(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    entry, _, _ = await _setup(hass, [])
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    assert is_menu(result) and "edit_alarm" not in menu_options(result)
    result = await flow.async_configure(result["flow_id"], {"action": "add_alarm"})
    assert result["step_id"] == "alarm_edit"
    form = {"name": "Früh", "enabled": True, "time": "06:30:00", "weekdays": ["mon", "tue"],
            "players": [PLAYER], "media": MEDIA, "volume": 25, "snooze_minutes": 5,
            "auto_stop_minutes": 20}
    for field, value, error in (("players", [], "no_players"), ("weekdays", [], "no_weekday"),
                                ("media", {"media_content_id": "", "media_content_type": "audio/mpeg"}, "no_media")):
        bad = await flow.async_configure(result["flow_id"], {**form, field: value})
        assert bad["errors"] == {"base": error}
    result = await flow.async_configure(bad["flow_id"], form)
    assert is_menu(result)
    (created,) = entry.options["alarms"]
    assert created["name"] == "Früh" and created["volume"] == 25 and created["media"] == MEDIA
    assert created["players"] == [PLAYER] and created["snooze_minutes"] == 5
    await hass.async_block_till_done()

    result = await flow.async_configure(result["flow_id"], {"action": "edit_alarm"})
    result = await flow.async_configure(result["flow_id"], {"alarm": created["id"]})
    result = await flow.async_configure(result["flow_id"], {**form, "volume": 40})
    (edited,) = entry.options["alarms"]
    assert edited["id"] == created["id"] and edited["volume"] == 40

    result = await flow.async_configure(result["flow_id"], {"action": "delete_alarm"})
    result = await flow.async_configure(result["flow_id"], {"alarm": created["id"]})
    assert entry.options["alarms"] == []
    done = await flow.async_configure(result["flow_id"], {"action": "done"})
    assert done["type"] is FlowResultType.CREATE_ENTRY


async def test_options_general_only_notifications(hass: HomeAssistant) -> None:
    entry, _, _ = await _setup(hass, [])
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(result["flow_id"], {"action": "alarm_general"})
    assert [str(k) for k in result["data_schema"].schema] == ["notifications"]
    ok = await flow.async_configure(
        result["flow_id"],
        {"notifications": {"mobile_enabled": True, "mobile_targets": ["mobile_app_phone"],
                           "critical": False, "message": "Aufwachen"}},
    )
    assert is_menu(ok)
    assert entry.options["critical"] is False and entry.options["message"] == "Aufwachen"
