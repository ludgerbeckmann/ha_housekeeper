"""Tests für den KNX/Sonos-Connector."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import is_menu, make_entry, reconfigure, new_instance
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
    entry = make_entry(domain=DOMAIN, title="Sonos", data={**BASE, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry, mocks


async def _telegram(hass, destination, data, *, direction="Incoming", telegramtype="GroupValueWrite"):
    hass.bus.async_fire("knx_event", {
        "data": data, "destination": destination, "direction": direction,
        "telegramtype": telegramtype, "value": None, "source": "1.1.1"})
    await hass.async_block_till_done()


# --- Config-Flow --------------------------------------------------------------------


async def test_config_flow_needs_knx(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "knx_sonos")
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "knx_missing"


def page(**fields):
    """Eingaben der Konfigurationsseite: flache Felder auf die Abschnitte verteilen."""
    sections = {name: {} for name in
                ("speaker", "playback", "volume", "scenes", *(f"scene_{n}" for n in range(1, 9)), "status")}
    for key, value in fields.items():
        if key in ("name", "player", "max_volume", "volume_step", "stop_instead_of_pause"):
            sections["speaker"][key] = value
        elif key.startswith("scene_"):
            sections[f"scene_{key.split('_')[1]}"][key] = value
        elif key in ("addr_play_pause", "addr_next_prev", "addr_stop", "addr_toggle"):
            sections["playback"][key] = value
        elif key in ("addr_volume", "addr_volume_step", "addr_volume_dim", "addr_mute"):
            sections["volume"][key] = value
        elif key == "addr_scene":
            sections["scenes"][key] = value
        elif key == "clear_legacy":
            sections.setdefault("legacy", {})[key] = value
        else:
            sections["status"][key] = value
    sections["speaker"].setdefault("max_volume", 100)
    sections["speaker"].setdefault("volume_step", 5)
    sections["speaker"].setdefault("stop_instead_of_pause", False)
    sections["speaker"].setdefault("player", PLAYER)
    return sections


async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    async_mock_service(hass, "knx", "event_register")
    result = await new_instance(hass, "knx_sonos")
    assert result["step_id"] == "new_knx_sonos"
    flow = hass.config_entries.subentries
    bad = await flow.async_configure(
        result["flow_id"], page(name="Wohnzimmer", addr_play_pause="x/y", scene_2_address="bad"))
    assert bad["errors"] == {"base": "invalid_address"}
    assert "Play/Pause" in bad["description_placeholders"]["detail"]
    assert "Scene 2" in bad["description_placeholders"]["detail"]
    lonely = await flow.async_configure(result["flow_id"], page(scene_3_favorite="Jazz"))
    assert lonely["errors"] == {"base": "scene_no_trigger"}
    ok = await flow.async_configure(
        result["flow_id"], page(name="Wohnzimmer", addr_play_pause="1/0/1", addr_scene="1/0/9",
                                scene_3_favorite="Jazz", scene_3_volume=30, status_title="5/0/4",
                                idle_text="Pause"))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    data = ok["data"]
    assert data["player"] == PLAYER and data["max_volume"] == 100 and data["addr_play_pause"] == "1/0/1"
    assert data["scene_3_favorite"] == "Jazz" and data["scene_3_volume"] == 30
    assert "addr_stop" not in data and "name" not in data


# --- Konfigurationsseite: Befehle und Rückmeldungen aus festen Feldern ------------------------------------------


def test_settings_commands_and_status() -> None:
    from custom_components.ha_housekeeper.knx_sonos import settings_commands, settings_status

    values = {"addr_play_pause": "1/0/1", "addr_volume_dim": "1/0/2", "addr_scene": "2/0/1",
              "scene_2_favorite": "Radio", "scene_2_volume": 20, "scene_2_address": "2/1/2",
              "status_title": "5/0/4", "status_playing": "5/0/1", "idle_text": "Pause"}
    get = lambda key, default=None: values.get(key, default)  # noqa: E731
    commands = settings_commands(get)
    by = {(c["address"], c["action"], c.get("when"), c.get("scene")) for c in commands}
    assert ("1/0/1", "play", "on", None) in by and ("1/0/1", "pause", "off", None) in by
    assert ("1/0/2", "volume_dim", None, None) in by
    assert ("2/0/1", "favorite", None, 2) in by and ("2/0/1", "volume_set", None, 2) in by
    assert ("2/1/2", "favorite", "on", None) in by and ("2/1/2", "pause", "off", None) in by
    statuses = {s["address"]: s for s in settings_status(get)}
    assert statuses["5/0/4"]["idle_text"] == "Pause" and "idle_text" not in statuses["5/0/1"]
    assert settings_commands(lambda key, default=None: default) == []


async def test_fields_drive_the_player(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, addr_play_pause="1/0/1", addr_next_prev="1/0/2", addr_volume="1/0/3",
        addr_volume_step="1/0/4", addr_mute="1/0/5", addr_scene="2/0/1", scene_1_favorite="Jazz",
        scene_1_volume=25, scene_2_address="2/1/2", scene_2_favorite="Radio")
    await _telegram(hass, "1/0/1", 1)
    await _telegram(hass, "1/0/1", 0)
    assert len(m["media_play"]) == 1 and len(m["media_pause"]) == 1
    await _telegram(hass, "1/0/2", 1)
    await _telegram(hass, "1/0/2", 0)
    assert len(m["media_next_track"]) == len(m["media_previous_track"]) == 1
    await _telegram(hass, "1/0/3", (128,))
    assert m["volume_set"][-1].data["volume_level"] == 0.5
    await _telegram(hass, "1/0/4", 1)       # 30 % + 5 %
    assert m["volume_set"][-1].data["volume_level"] == 0.35
    await _telegram(hass, "1/0/5", 1)
    assert m["volume_mute"][-1].data["is_volume_muted"] is True
    await _telegram(hass, "2/0/1", (0,))    # Szene 1: Favorit, dann Lautstärke
    assert [c.data["source"] for c in m["select_source"]] == ["Jazz"]
    assert m["volume_set"][-1].data["volume_level"] == 0.25
    await _telegram(hass, "2/1/2", 1)       # Szene 2 über die 1-Bit-Adresse
    assert [c.data["source"] for c in m["select_source"]] == ["Jazz", "Radio"]
    pauses = len(m["media_pause"])
    await _telegram(hass, "2/1/2", 0)       # 0 = Pause
    assert len(m["media_pause"]) == pauses + 1


async def test_fields_send_status(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, status_playing="5/0/1", status_title="5/0/4", idle_text="Pause")
    assert _sent(m) == {"5/0/1": (False, "1.001", False), "5/0/4": ("Pause", "16.001", False)}


async def test_settings_page_saves_and_renames(hass: HomeAssistant) -> None:
    entry, _ = await _setup(hass, addr_play_pause="1/0/1", addr_stop="1/0/2")
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    assert result["step_id"] == "knx_settings" and not is_menu(result)
    assert "legacy" not in {str(k) for k in result["data_schema"].schema}     # keine alten Listen
    # Bestehende Adressen sind vorbelegt; Stopp wird geleert, Name gesetzt
    done = await flow.async_configure(
        result["flow_id"], page(name="Küche", addr_play_pause="1/0/1", max_volume=70))
    assert done["type"] is FlowResultType.ABORT and done["reason"] == "reconfigure_successful"
    assert entry.options["addr_stop"] is None and entry.options["addr_play_pause"] == "1/0/1"
    assert entry.options["max_volume"] == 70
    assert entry.title.endswith("Küche")


async def test_settings_page_legacy_entries(hass: HomeAssistant) -> None:
    legacy_cmd = cmd("1", "1/0/1", "switch", "play")
    entry, _ = await _setup(
        hass, commands=[legacy_cmd],
        speakers=[{"id": "a", "name": "A", "player": PLAYER, "max_volume": 80, "volume_step": 7,
                   "stop_instead_of_pause": True},
                  {"id": "b", "name": "B", "player": "media_player.b"}])
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    schema = {str(k): v for k, v in result["data_schema"].schema.items()}
    assert "legacy" in schema                                    # Schalter zum Löschen der alten Listen
    assert "weitere" in result["description_placeholders"]["legacy"] or "more" in result["description_placeholders"]["legacy"]
    await flow.async_configure(result["flow_id"], page(max_volume=80, volume_step=7,
                                                       stop_instead_of_pause=True, clear_legacy=True))
    assert entry.options["speakers"] is None and entry.options["commands"] is None
    assert entry.options["volume_step"] == 7 and entry.options["stop_instead_of_pause"] is True


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
    entry = make_entry(
        domain=DOMAIN, title="Sonos",
        data={**BASE, "commands": [cmd("a", "1/2/3", "switch", "play")]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
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
    entry = make_entry(domain=DOMAIN, title="Sonos", data={
        **BASE, "status": [{"id": "b", "name": "B", "source": "volume", "address": "5/0/2"}]})
    entry.add_to_hass(hass)
    send = async_mock_service(hass, "knx", "send")
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    assert send == []                           # KNX ist (noch) nicht bereit
