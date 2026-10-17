"""KNX/Sonos-Connector: mehrere Lautsprecher über Profile."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.ha_housekeeper.const import DOMAIN
from custom_components.ha_housekeeper.knx_sonos import (
    command_summary,
    profile_for,
    speaker_profiles,
)

from .helpers import make_entry

LIVING = "media_player.living_room"
KITCHEN = "media_player.kitchen"
SERVICES = ("media_play", "media_pause", "media_stop", "volume_set", "volume_mute", "select_source")


def speaker(i, name, player, **over):
    return {"id": i, "name": name, "player": player, "max_volume": 100, "volume_step": 5,
            "stop_instead_of_pause": False, **over}


def cmd(i, address, dpt, action, profile=None, **extra):
    item = {"id": i, "name": f"Cmd {i}", "address": address, "dpt": dpt, "action": action, **extra}
    if profile:
        item["profile"] = profile
    return item


def status(i, address, source, profile=None):
    item = {"id": i, "name": f"S {i}", "source": source, "address": address}
    if profile:
        item["profile"] = profile
    return item


DATA = {"function_type": "knx_sonos", "commands": [], "status": []}


async def _setup(hass: HomeAssistant, **over):
    mocks = {n: async_mock_service(hass, "media_player", n) for n in SERVICES}
    mocks["register"] = async_mock_service(hass, "knx", "event_register")
    mocks["send"] = async_mock_service(hass, "knx", "send")
    hass.states.async_set(LIVING, "paused", {"volume_level": 0.3, "is_volume_muted": False,
                                              "source_list": ["Radio", "Jazz"]})
    hass.states.async_set(KITCHEN, "playing", {"volume_level": 0.6, "is_volume_muted": True,
                                                "source_list": ["Podcast"], "media_title": "Song"})
    entry = make_entry(domain=DOMAIN, title="Sonos", data={**DATA, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry, mocks


async def _telegram(hass, destination, data):
    hass.bus.async_fire("knx_event", {
        "data": data, "destination": destination, "direction": "Incoming",
        "telegramtype": "GroupValueWrite", "value": None, "source": "1.1.1"})
    await hass.async_block_till_done()


def two_speakers(**over):
    return {"speakers": [speaker("w", "Wohnzimmer", LIVING), speaker("k", "Küche", KITCHEN, **over)]}


# --- reine Funktionen -----------------------------------------------------------------------------


def test_legacy_entry_gets_default_profile() -> None:
    legacy = {"player": LIVING, "max_volume": 80, "volume_step": 7, "stop_instead_of_pause": True}
    (profile,) = speaker_profiles(lambda key, default=None: legacy.get(key, default))
    assert profile["id"] == "default" and profile["name"] == "Standard" and profile["player"] == LIVING
    assert profile["max_volume"] == 80 and profile["volume_step"] == 7
    assert profile["stop_instead_of_pause"] is True
    assert speaker_profiles(lambda key, default=None: default) == []


def test_configured_profiles_win_and_profile_lookup() -> None:
    profiles = [speaker("w", "Wohnzimmer", LIVING), speaker("k", "Küche", KITCHEN)]
    got = speaker_profiles(lambda key, default=None: {"speakers": profiles, "player": "x"}.get(key, default))
    assert got == profiles
    assert profile_for(profiles, {"profile": "k"})["id"] == "k"
    assert profile_for(profiles, {})["id"] == "w"                       # ohne Angabe: erstes Profil
    assert profile_for(profiles, {"profile": "gelöscht"})["id"] == "w"
    assert profile_for([], {}) is None


async def test_summary_shows_profile(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    item = cmd("1", "1/0/1", "switch", "play")
    assert command_summary(hass, item) == "Cmd 1: 1/0/1 → Play"
    assert command_summary(hass, item, "Küche") == "Cmd 1 [Küche]: 1/0/1 → Play"


# --- Steuerung mehrerer Lautsprecher ---------------------------------------------------------------


async def test_commands_go_to_their_speaker(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, **two_speakers(), commands=[
        cmd("1", "1/0/1", "switch", "play", "w"),
        cmd("2", "2/0/1", "switch", "play", "k"),
        cmd("3", "3/0/1", "switch", "play"),                     # ohne Profil: erstes Profil
    ])
    await _telegram(hass, "1/0/1", 1)
    assert [c.data["entity_id"] for c in m["media_play"]] == [LIVING]
    await _telegram(hass, "2/0/1", 1)
    assert [c.data["entity_id"] for c in m["media_play"]] == [LIVING, KITCHEN]
    await _telegram(hass, "3/0/1", 1)
    assert [c.data["entity_id"] for c in m["media_play"]][-1] == LIVING


async def test_settings_apply_per_speaker(hass: HomeAssistant) -> None:
    speakers = {"speakers": [speaker("w", "Wohnzimmer", LIVING, max_volume=40, volume_step=10),
                             speaker("k", "Küche", KITCHEN, max_volume=90, volume_step=20,
                                     stop_instead_of_pause=True)]}
    _, m = await _setup(hass, **speakers, commands=[
        cmd("1", "1/0/1", "percent", "volume_set", "w"), cmd("2", "2/0/1", "percent", "volume_set", "k"),
        cmd("3", "1/0/2", "switch", "volume_up", "w"), cmd("4", "2/0/2", "switch", "volume_up", "k"),
        cmd("5", "2/0/3", "switch", "pause", "k"), cmd("6", "1/0/3", "switch", "pause", "w"),
    ])
    await _telegram(hass, "1/0/1", (255,))                    # 100 % angefragt, Wohnzimmer maximal 40
    await _telegram(hass, "2/0/1", (255,))                    # Küche maximal 90
    levels = {c.data["entity_id"]: c.data["volume_level"] for c in m["volume_set"]}
    assert levels == {LIVING: 0.4, KITCHEN: 0.9}
    m["volume_set"].clear()
    await _telegram(hass, "1/0/2", 1)                         # 0.3 + 10 % Schritt
    await _telegram(hass, "2/0/2", 1)                         # 0.6 + 20 % Schritt
    levels = {c.data["entity_id"]: c.data["volume_level"] for c in m["volume_set"]}
    assert levels == {LIVING: 0.4, KITCHEN: 0.8}
    await _telegram(hass, "2/0/3", 1)
    await _telegram(hass, "1/0/3", 1)
    assert [c.data["entity_id"] for c in m["media_stop"]] == [KITCHEN]    # nur Küche: stoppen
    assert [c.data["entity_id"] for c in m["media_pause"]] == [LIVING]


async def test_unavailable_speaker_does_not_block_the_other(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, **two_speakers(), commands=[
        cmd("1", "1/0/1", "switch", "play", "w"), cmd("2", "2/0/1", "switch", "play", "k")])
    hass.states.async_set(LIVING, "unavailable")
    await _telegram(hass, "1/0/1", 1)
    await _telegram(hass, "2/0/1", 1)
    assert [c.data["entity_id"] for c in m["media_play"]] == [KITCHEN]


async def test_last_command_names_the_profile(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, **two_speakers(), commands=[cmd("2", "2/0/1", "switch", "play", "k")])
    await _telegram(hass, "2/0/1", 1)
    attrs = hass.states.get("sensor.sonos_last_command").attributes
    assert attrs["profile"] == "Küche" and attrs["name"] == "Cmd 2"


async def test_status_is_sent_per_speaker(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, **two_speakers(), status=[
        status("a", "5/0/1", "volume", "w"), status("b", "5/0/2", "volume", "k"),
        status("c", "5/0/3", "muted", "k")])
    sent = {c.data["address"]: c.data["payload"] for c in m["send"]}
    assert sent == {"5/0/1": 30, "5/0/2": 60, "5/0/3": True}
    m["send"].clear()
    # nur der Wert des Wohnzimmers ändert sich: nur dessen Adresse wird gesendet
    hass.states.async_set(LIVING, "paused", {"volume_level": 0.5, "is_volume_muted": False})
    await hass.async_block_till_done()
    assert [(c.data["address"], c.data["payload"]) for c in m["send"]] == [("5/0/1", 50)]


async def test_read_request_answered_from_the_right_speaker(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, **two_speakers(), status=[
        status("a", "5/0/1", "volume", "w"), status("b", "5/0/2", "volume", "k")])
    m["send"].clear()
    hass.bus.async_fire("knx_event", {"data": None, "destination": "5/0/2", "direction": "Incoming",
                                      "telegramtype": "GroupValueRead", "value": None, "source": "1.1.1"})
    await hass.async_block_till_done()
    assert [(c.data["address"], c.data["payload"], c.data.get("response")) for c in m["send"]] == [
        ("5/0/2", 60, True)]


async def test_registers_all_addresses_and_tracks_all_players(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, **two_speakers(), commands=[
        cmd("1", "1/0/1", "switch", "play", "w"), cmd("2", "2/0/1", "switch", "play", "k")],
        status=[status("a", "5/0/1", "volume", "k")])
    assert m["register"][0].data["address"] == ["1/0/1", "2/0/1", "5/0/1"]
    m["send"].clear()
    hass.states.async_set(KITCHEN, "playing", {"volume_level": 0.1, "is_volume_muted": True})
    await hass.async_block_till_done()
    assert [(c.data["address"], c.data["payload"]) for c in m["send"]] == [("5/0/1", 10)]


async def test_legacy_entry_runs_unchanged(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, player=LIVING, max_volume=100, volume_step=5,
                        stop_instead_of_pause=False,
                        commands=[cmd("1", "1/0/1", "switch", "play")])
    await _telegram(hass, "1/0/1", 1)
    assert [c.data["entity_id"] for c in m["media_play"]] == [LIVING]
