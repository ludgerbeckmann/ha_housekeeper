"""Tests für den KNX/Sonos-Connector."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import is_menu, menu_options
from custom_components.ha_housekeeper.const import DOMAIN

PLAYER = "media_player.living_room"
SERVICES = ("media_play", "media_pause", "media_stop", "media_next_track",
            "media_previous_track", "volume_set", "volume_mute", "select_source")


def cmd(i, address, dpt, action, **extra):
    return {"id": i, "name": f"Cmd {i}", "address": address, "dpt": dpt, "action": action, **extra}


BASE = {
    "function_type": "knx_sonos", "player": PLAYER, "max_volume": 100,
    "volume_step": 5, "stop_instead_of_pause": False, "commands": [], "status": [],
}


async def _setup(hass: HomeAssistant, state="paused", attrs=None, **over):
    mocks = {n: async_mock_service(hass, "media_player", n) for n in SERVICES}
    mocks["register"] = async_mock_service(hass, "knx", "event_register")
    mocks["send"] = async_mock_service(hass, "knx", "send")
    hass.states.async_set(
        PLAYER, state,
        {"volume_level": 0.3, "is_volume_muted": False, "source_list": ["Radio", "Jazz"],
         "media_title": "Song", "media_artist": "Artist", "media_album_name": "Album",
         **(attrs or {})},
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Sonos", data={**BASE, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, mocks


async def _telegram(hass, destination, data, *, direction="Incoming", telegramtype="GroupValueWrite"):
    hass.bus.async_fire("knx_event", {
        "data": data, "destination": destination, "direction": direction,
        "telegramtype": telegramtype, "value": None, "source": "1.1.1"})
    await hass.async_block_till_done()


# --- Config-Flow --------------------------------------------------------------------


async def test_config_flow_needs_knx(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "knx_sonos"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "knx_missing"


async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    async_mock_service(hass, "knx", "event_register")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "knx_sonos"}
    )
    assert result["step_id"] == "knx_sonos"
    ok = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Wohnzimmer", "player": PLAYER}
    )
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["commands"] == [] and ok["data"]["status"] == []
    assert ok["data"]["max_volume"] == 100


# --- Anmeldung bei der KNX-Integration ----------------------------------------------------


async def test_registers_addresses_normalized_and_unique(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass,
        commands=[cmd("a", "1/2/3", "switch", "play"), cmd("b", "1/515", "switch", "pause")],
        status=[{"id": "s", "name": "S", "source": "playing", "address": "2/0/1"}],
    )
    assert len(m["register"]) == 1
    assert m["register"][0].data["address"] == ["1/2/3", "2/0/1"]


async def test_reregisters_on_reload_event_and_interval(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, commands=[cmd("a", "1/2/3", "switch", "play")])
    assert len(m["register"]) == 1
    hass.bus.async_fire("event_knx_reloaded")
    await hass.async_block_till_done()
    assert len(m["register"]) == 2
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert len(m["register"]) == 3


async def test_waits_for_knx_service(hass: HomeAssistant) -> None:
    hass.states.async_set(PLAYER, "paused", {"volume_level": 0.3})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Sonos",
        data={**BASE, "commands": [cmd("a", "1/2/3", "switch", "play")]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    register = async_mock_service(hass, "knx", "event_register")   # KNX kommt später
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert len(register) == 1


# --- Befehle ---------------------------------------------------------------------------


async def test_simple_actions(hass: HomeAssistant) -> None:
    cmds = [cmd("1", "1/0/1", "switch", "play"), cmd("2", "1/0/2", "switch", "pause"),
            cmd("3", "1/0/3", "switch", "stop"), cmd("4", "1/0/4", "switch", "next"),
            cmd("5", "1/0/5", "switch", "previous")]
    _, m = await _setup(hass, commands=cmds)
    for ga in ("1/0/1", "1/0/2", "1/0/3", "1/0/4", "1/0/5"):
        await _telegram(hass, ga, 1)
    assert len(m["media_play"]) == len(m["media_pause"]) == len(m["media_stop"]) == 1
    assert len(m["media_next_track"]) == len(m["media_previous_track"]) == 1
    assert m["media_play"][0].data["entity_id"] == PLAYER


async def test_switch_conditions(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, commands=[
        cmd("on", "1/0/1", "switch", "play", when="on"),
        cmd("off", "1/0/1", "switch", "pause", when="off"),
        cmd("any", "1/0/2", "switch", "next", when="any")])
    await _telegram(hass, "1/0/1", 1)
    assert len(m["media_play"]) == 1 and m["media_pause"] == []
    await _telegram(hass, "1/0/1", 0)
    assert len(m["media_pause"]) == 1
    await _telegram(hass, "1/0/2", 1)
    await _telegram(hass, "1/0/2", 0)
    assert len(m["media_next_track"]) == 2


async def test_play_pause_toggle_and_stop_instead(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, state="playing", stop_instead_of_pause=True,
                        commands=[cmd("t", "1/0/1", "switch", "play_pause", when="any"),
                                  cmd("p", "1/0/2", "switch", "pause", when="any")])
    await _telegram(hass, "1/0/1", 1)          # läuft -> "Pause" = Stopp
    assert len(m["media_stop"]) == 1 and m["media_pause"] == []
    hass.states.async_set(PLAYER, "paused", {"volume_level": 0.3})
    await hass.async_block_till_done()
    await _telegram(hass, "1/0/1", 1)          # pausiert -> Wiedergabe
    assert len(m["media_play"]) == 1
    await _telegram(hass, "1/0/2", 1)
    assert len(m["media_stop"]) == 2


async def test_scene_matching(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, commands=[
        cmd("s1", "2/0/1", "scene", "favorite", scene=3, favorite="Jazz"),
        cmd("s2", "2/0/1", "scene", "favorite", scene=4, favorite="Radio")])
    await _telegram(hass, "2/0/1", (2,))      # Wert 2 = Szene 3
    assert [c.data["source"] for c in m["select_source"]] == ["Jazz"]
    await _telegram(hass, "2/0/1", (3,))      # Szene 4
    assert [c.data["source"] for c in m["select_source"]] == ["Jazz", "Radio"]
    await _telegram(hass, "2/0/1", (9,))      # keine Szene
    assert len(m["select_source"]) == 2


async def test_volume_set_from_percent_and_clamped(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, max_volume=60,
                        commands=[cmd("v", "3/0/1", "percent", "volume_set")])
    await _telegram(hass, "3/0/1", (128,))    # 50 %
    assert m["volume_set"][0].data["volume_level"] == 0.5
    await _telegram(hass, "3/0/1", (255,))    # 100 % -> begrenzt auf 60 %
    assert m["volume_set"][1].data["volume_level"] == 0.6


async def test_volume_set_fixed(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, commands=[cmd("v", "3/0/2", "switch", "volume_set", when="on", volume=20)])
    await _telegram(hass, "3/0/2", 1)
    assert m["volume_set"][0].data["volume_level"] == 0.2


async def test_volume_up_down_step_and_limits(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, max_volume=32, volume_step=5, commands=[
        cmd("u", "3/1/1", "switch", "volume_up", when="on"),
        cmd("d", "3/1/2", "switch", "volume_down", when="on")])
    await _telegram(hass, "3/1/1", 1)         # 30 + 5 -> 32 (Maximum)
    assert m["volume_set"][0].data["volume_level"] == 0.32
    await _telegram(hass, "3/1/2", 1)         # 30 - 5
    assert m["volume_set"][1].data["volume_level"] == 0.25
    hass.states.async_set(PLAYER, "paused", {"volume_level": 0.02})
    await hass.async_block_till_done()
    await _telegram(hass, "3/1/2", 1)         # nicht unter 0
    assert m["volume_set"][2].data["volume_level"] == 0.0


async def test_dimming_direction_and_stop(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, commands=[cmd("dim", "3/2/1", "dimming", "volume_dim")])
    await _telegram(hass, "3/2/1", 0b1011)    # lauter
    await _telegram(hass, "3/2/1", 0b0011)    # leiser
    await _telegram(hass, "3/2/1", 0b1000)    # Stopp, wird ignoriert
    assert [c.data["volume_level"] for c in m["volume_set"]] == [0.35, 0.25]


async def test_mute_actions(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, commands=[
        cmd("m", "4/0/1", "switch", "mute", when="on"),
        cmd("u", "4/0/2", "switch", "unmute", when="on"),
        cmd("t", "4/0/3", "switch", "mute_toggle", when="on"),
        cmd("v", "4/0/4", "switch", "mute_set")])
    await _telegram(hass, "4/0/1", 1)
    await _telegram(hass, "4/0/2", 1)
    await _telegram(hass, "4/0/3", 1)         # war nicht stumm -> stumm
    await _telegram(hass, "4/0/4", 0)
    await _telegram(hass, "4/0/4", 1)
    assert [c.data["is_volume_muted"] for c in m["volume_mute"]] == [True, False, True, False, True]


async def test_telegram_filters(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, commands=[cmd("p", "1/0/1", "switch", "play")])
    await _telegram(hass, "1/0/1", 1, direction="Outgoing")
    await _telegram(hass, "1/0/1", 1, telegramtype="GroupValueResponse")
    await _telegram(hass, "9/9/9", 1)
    await _telegram(hass, "1/0/1", 5)         # ungültiger Wert für 1 Bit
    assert m["media_play"] == []
    await _telegram(hass, "1/0/1", 1)
    assert len(m["media_play"]) == 1


async def test_switch_off_pauses_commands_and_status(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, commands=[cmd("p", "1/0/1", "switch", "play")],
                        status=[{"id": "s", "name": "S", "source": "volume", "address": "5/0/1"}])
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.sonos_connector_active"}, blocking=True
    )
    m["send"].clear()
    await _telegram(hass, "1/0/1", 1)
    hass.states.async_set(PLAYER, "paused", {"volume_level": 0.8})
    await hass.async_block_till_done()
    assert m["media_play"] == [] and m["send"] == []
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.sonos_connector_active"}, blocking=True
    )
    assert len(m["send"]) == 1 and m["send"][0].data["payload"] == 80   # erneuter Abgleich


async def test_unavailable_player_is_skipped(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, commands=[cmd("p", "1/0/1", "switch", "play")])
    hass.states.async_set(PLAYER, "unavailable")
    await hass.async_block_till_done()
    await _telegram(hass, "1/0/1", 1)
    assert m["media_play"] == []


async def test_last_command_sensor(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, commands=[cmd("p", "1/0/1", "switch", "play")])
    assert hass.states.get("sensor.sonos_last_command").state == "unknown"
    await _telegram(hass, "1/0/1", 1)
    state = hass.states.get("sensor.sonos_last_command")
    assert state.state != "unknown"
    assert state.attributes["address"] == "1/0/1" and state.attributes["action"] == "play"


# --- Rückmeldungen -------------------------------------------------------------------------


def _sent(m):
    return {c.data["address"]: (c.data["payload"], c.data["type"], c.data.get("response", False))
            for c in m["send"]}


async def test_initial_status_sync_and_changes(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, status=[
        {"id": "a", "name": "A", "source": "playing", "address": "5/0/1"},
        {"id": "b", "name": "B", "source": "volume", "address": "5/0/2"},
        {"id": "c", "name": "C", "source": "muted", "address": "5/0/3"},
        {"id": "d", "name": "D", "source": "title", "address": "5/0/4", "idle_text": "Pause"},
    ])
    assert _sent(m) == {
        "5/0/1": (False, "1.001", False), "5/0/2": (30, "5.001", False),
        "5/0/3": (False, "1.001", False), "5/0/4": ("Pause", "16.001", False)}
    m["send"].clear()
    hass.states.async_set(PLAYER, "playing", {"volume_level": 0.3, "is_volume_muted": False,
                                              "media_title": "Ein sehr langer Titel"})
    await hass.async_block_till_done()
    # nur geänderte Werte: Wiedergabe und Titel (auf 14 Zeichen gekürzt)
    sent = _sent(m)
    assert sent["5/0/1"] == (True, "1.001", False)
    assert set(sent) == {"5/0/1", "5/0/4"}
    assert sent["5/0/4"][0] == "Ein sehr lange" and len(sent["5/0/4"][0]) == 14


async def test_paused_source_and_idle_default(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, status=[
        {"id": "p", "name": "P", "source": "paused", "address": "5/1/1"},
        {"id": "t", "name": "T", "source": "artist", "address": "5/1/2"}])
    assert _sent(m) == {"5/1/1": (True, "1.001", False), "5/1/2": ("", "16.001", False)}


async def test_read_request_is_answered(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, status=[{"id": "b", "name": "B", "source": "volume", "address": "5/0/2"}])
    m["send"].clear()
    await _telegram(hass, "5/0/2", None, telegramtype="GroupValueRead")
    assert _sent(m) == {"5/0/2": (30, "5.001", True)}
    m["send"].clear()
    await _telegram(hass, "5/0/2", None, direction="Outgoing", telegramtype="GroupValueRead")
    assert m["send"] == []                      # eigene/ausgehende Telegramme ignorieren


async def test_status_not_sent_without_knx_service(hass: HomeAssistant) -> None:
    hass.states.async_set(PLAYER, "paused", {"volume_level": 0.3})
    entry = MockConfigEntry(domain=DOMAIN, title="Sonos", data={
        **BASE, "status": [{"id": "b", "name": "B", "source": "volume", "address": "5/0/2"}]})
    entry.add_to_hass(hass)
    send = async_mock_service(hass, "knx", "send")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert send == []                           # KNX ist (noch) nicht bereit


# --- Options-Flow ----------------------------------------------------------------------------


async def test_options_flow_commands_and_status(hass: HomeAssistant) -> None:
    entry, _ = await _setup(hass)
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    assert result["step_id"] == "knx_menu"
    assert "edit_command" not in menu_options(result) and "edit_status" not in menu_options(result)

    # Lautsprecher-Profil bearbeiten (ältere Einträge: Profil „Standard“ aus dem Eintrag)
    assert "delete_speaker" not in menu_options(result)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "edit_speaker"})
    result = await flow.async_configure(result["flow_id"], {"item": "default"})
    assert result["step_id"] == "speaker_edit"
    result = await flow.async_configure(
        result["flow_id"],
        {"name": "Wohnzimmer", "player": PLAYER, "max_volume": 70, "volume_step": 10,
         "stop_instead_of_pause": True})
    (speaker,) = entry.options["speakers"]
    assert speaker["id"] == "default" and speaker["name"] == "Wohnzimmer"
    assert speaker["max_volume"] == 70 and speaker["stop_instead_of_pause"] is True

    # Befehl mit Favorit (zwei Schritte)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_command"})
    bad = await flow.async_configure(
        result["flow_id"], {"name": "Jazz", "address": "x/y", "dpt": "switch", "action": "favorite"})
    assert bad["errors"] == {"base": "invalid_address"}
    mismatch = await flow.async_configure(
        bad["flow_id"], {"name": "Jazz", "address": "1/0/1", "dpt": "dimming", "action": "play"})
    assert mismatch["errors"] == {"base": "dimming_mismatch"}
    mute = await flow.async_configure(
        mismatch["flow_id"], {"name": "Jazz", "address": "1/0/1", "dpt": "percent", "action": "mute_set"})
    assert mute["errors"] == {"base": "mute_set_needs_switch"}
    result = await flow.async_configure(
        mute["flow_id"], {"name": "Jazz", "address": "1/0/1", "dpt": "switch", "action": "favorite"})
    assert result["step_id"] == "command_params"
    result = await flow.async_configure(result["flow_id"], {"when": "on", "favorite": "Jazz"})
    assert is_menu(result)
    (command,) = entry.options["commands"]
    assert command["favorite"] == "Jazz" and command["when"] == "on" and "scene" not in command

    # Befehl ohne Zusatzangaben wird sofort gespeichert (Dimmen)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_command"})
    result = await flow.async_configure(
        result["flow_id"], {"name": "Dim", "address": "1/0/2", "dpt": "dimming", "action": "volume_dim"})
    assert is_menu(result) and len(entry.options["commands"]) == 2

    # Bearbeiten: auf Szene umstellen, alte Schlüssel verschwinden
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "edit_command"})
    result = await flow.async_configure(result["flow_id"], {"item": command["id"]})
    result = await flow.async_configure(
        result["flow_id"], {"name": "Jazz", "address": "1/0/1", "dpt": "scene", "action": "favorite"})
    result = await flow.async_configure(result["flow_id"], {"scene": 5, "favorite": "Radio"})
    edited = next(c for c in entry.options["commands"] if c["id"] == command["id"])
    assert edited["scene"] == 5 and edited["favorite"] == "Radio" and "when" not in edited

    # Löschen
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "delete_command"})
    result = await flow.async_configure(result["flow_id"], {"item": command["id"]})
    assert [c["name"] for c in entry.options["commands"]] == ["Dim"]

    # Rückmeldung: hinzufügen, bearbeiten, löschen
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_status"})
    bad = await flow.async_configure(
        result["flow_id"], {"name": "Titel", "source": "title", "address": "nope", "idle_text": ""})
    assert bad["errors"] == {"base": "invalid_address"}
    result = await flow.async_configure(
        bad["flow_id"], {"name": "Titel", "source": "title", "address": "5/0/4", "idle_text": "Pause"})
    (status,) = entry.options["status"]
    assert status["idle_text"] == "Pause"
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "edit_status"})
    result = await flow.async_configure(result["flow_id"], {"item": status["id"]})
    result = await flow.async_configure(
        result["flow_id"], {"name": "Laut", "source": "volume", "address": "5/0/5", "idle_text": "x"})
    (edited_status,) = entry.options["status"]
    assert edited_status["source"] == "volume" and "idle_text" not in edited_status
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "delete_status"})
    result = await flow.async_configure(result["flow_id"], {"item": status["id"]})
    assert entry.options["status"] == []
