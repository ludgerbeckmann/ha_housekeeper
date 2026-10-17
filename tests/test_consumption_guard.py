"""Tests für die Funktion Verbrauchswächter."""

from datetime import time, timedelta

from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import is_menu, make_entry, new_instance, reconfigure, sectioned
from custom_components.ha_housekeeper.const import DOMAIN
from custom_components.ha_housekeeper.consumption_guard import in_window, is_running
from custom_components.ha_housekeeper.issues import collect_references

SENSOR = "sensor.water_flow"
BASE = {
    "function_type": "consumption_guard", "name": "Wasser", "consumption_sensor": SENSOR,
    "threshold": 0.5, "duration_minutes": 15, "repeat_minutes": 0,
    "mobile_enabled": True, "mobile_targets": ["mobile_app_phone"],
    "tts_enabled": False, "persistent_enabled": False,
}
START = "2026-01-05 12:00:00+01:00"


async def _setup(hass: HomeAssistant, freezer, value="0", **over):
    freezer.move_to(START)
    push = async_mock_service(hass, "notify", "mobile_app_phone")
    hass.states.async_set(SENSOR, value, {"unit_of_measurement": "l/min", "friendly_name": "Wasserfluss"})
    entry = make_entry(domain=DOMAIN, title="Wasser", data={**BASE, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id], push


async def _advance(hass, freezer, **delta) -> None:
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _messages(push):
    return [c.data["message"] for c in push if c.data["message"] != "clear_notification"]


def _entity(hass, platform, key, entry):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")


def test_is_running() -> None:
    assert is_running(None, 1) is None
    assert is_running(State(SENSOR, "unavailable"), 1) is None
    assert is_running(State(SENSOR, "abc"), 1) is None
    assert is_running(State(SENSOR, "1.5"), 1) is True
    assert is_running(State(SENSOR, "1"), 1) is False         # genau die Schwelle zählt nicht


def test_in_window() -> None:
    assert in_window(None, None, time(3, 0)) and in_window("08:00:00", "08:00:00", time(3, 0))
    assert in_window("08:00:00", "18:00:00", time(8, 0)) and not in_window("08:00:00", "18:00:00", time(18, 0))
    assert in_window("22:00:00", "06:00:00", time(23, 0)) and in_window("22:00:00", "06:00:00", time(5, 0))
    assert not in_window("22:00:00", "06:00:00", time(12, 0))


async def test_warns_after_duration(hass: HomeAssistant, freezer) -> None:
    entry, controller, push = await _setup(hass, freezer)
    warning = _entity(hass, "binary_sensor", "consumption_warning", entry)
    hass.states.async_set(SENSOR, "2.0", {"unit_of_measurement": "l/min", "friendly_name": "Wasserfluss"})
    await hass.async_block_till_done()
    assert controller.since is not None and hass.states.get(warning).state == "off"
    await _advance(hass, freezer, minutes=14)
    assert hass.states.get(warning).state == "off" and not _messages(push)
    await _advance(hass, freezer, minutes=1)
    assert hass.states.get(warning).state == "on"
    (message,) = _messages(push)
    assert "Wasserfluss" in message and "0.5 l/min" in message and "15" in message
    await _advance(hass, freezer, minutes=30)
    assert len(_messages(push)) == 1                        # ohne Wiederholung nur eine Meldung
    # Verbrauch endet: Warnung geht weg, Push wird entfernt
    push.clear()
    hass.states.async_set(SENSOR, "0.2", {"unit_of_measurement": "l/min"})
    await hass.async_block_till_done()
    assert hass.states.get(warning).state == "off" and controller.since is None
    assert [c.data["message"] for c in push] == ["clear_notification"]
    since = hass.states.get(_entity(hass, "sensor", "consumption_since", entry))
    assert since.state == "unknown"


async def test_interruption_resets_the_duration(hass: HomeAssistant, freezer) -> None:
    entry, controller, push = await _setup(hass, freezer, value="2")
    await _advance(hass, freezer, minutes=10)
    hass.states.async_set(SENSOR, "0", {})
    await hass.async_block_till_done()
    hass.states.async_set(SENSOR, "2", {})
    await hass.async_block_till_done()
    await _advance(hass, freezer, minutes=10)
    assert not _messages(push)                              # neu gestartet, erst 10 Minuten
    await _advance(hass, freezer, minutes=5)
    assert len(_messages(push)) == 1


async def test_unavailable_sensor_resets_without_false_alarm(hass: HomeAssistant, freezer) -> None:
    entry, controller, push = await _setup(hass, freezer, value="2")
    await _advance(hass, freezer, minutes=10)
    hass.states.async_set(SENSOR, "unavailable")
    await hass.async_block_till_done()
    assert controller.since is None
    await _advance(hass, freezer, minutes=60)
    assert not _messages(push)
    # eine bestehende Warnung bleibt bei unklarem Sensor
    hass.states.async_set(SENSOR, "2")
    await hass.async_block_till_done()
    await _advance(hass, freezer, minutes=15)
    assert controller.warning
    hass.states.async_set(SENSOR, "unknown")
    await hass.async_block_till_done()
    assert controller.warning and controller.since is None


async def test_repeat_and_acknowledge(hass: HomeAssistant, freezer) -> None:
    entry, controller, push = await _setup(hass, freezer, value="2", repeat_minutes=10)
    await _advance(hass, freezer, minutes=15)
    assert len(_messages(push)) == 1
    await _advance(hass, freezer, minutes=10)
    assert len(_messages(push)) == 2                        # Wiederholung
    button = _entity(hass, "button", "consumption_acknowledge", entry)
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert not controller.warning
    await _advance(hass, freezer, minutes=60)
    assert len(_messages(push)) == 2 and not controller.warning   # quittiert: Ruhe, solange es läuft
    hass.states.async_set(SENSOR, "0")
    await hass.async_block_till_done()
    hass.states.async_set(SENSOR, "2")
    await hass.async_block_till_done()
    await _advance(hass, freezer, minutes=15)
    assert len(_messages(push)) == 3                        # nach einer Pause wieder aktiv


async def test_time_window(hass: HomeAssistant, freezer) -> None:
    # Fenster 22:00 bis 06:00, Start mittags: außerhalb zählt nichts
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry, controller, push = await _setup(
        hass, freezer, value="2", window_from="22:00:00", window_to="06:00:00")
    await _advance(hass, freezer, minutes=30)
    assert controller.since is None and not _messages(push)
    # im Fenster beginnt die Dauer neu
    freezer.move_to("2026-01-05 23:00:00+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert controller.since is not None
    await _advance(hass, freezer, minutes=15)
    assert len(_messages(push)) == 1
    # Fensterende beendet die Warnung
    freezer.move_to("2026-01-06 06:00:00+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert not controller.warning and controller.since is None


async def test_switch_off_pauses(hass: HomeAssistant, freezer) -> None:
    entry, controller, push = await _setup(hass, freezer, value="2")
    switch = _entity(hass, "switch", "consumption_active", entry)
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    await _advance(hass, freezer, minutes=30)
    assert controller.since is None and not _messages(push)
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert controller.since is not None                   # beim Einschalten beginnt die Dauer


async def test_config_flow_and_settings_page(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "consumption_guard")
    assert result["step_id"] == "new_consumption_guard"
    flow = hass.config_entries.subentries
    data = {"consumption_sensor": SENSOR, "threshold": 0.5, "duration_minutes": 15, "repeat_minutes": 0,
            "mobile_enabled": False, "tts_enabled": False, "persistent_enabled": True}
    bad = await flow.async_configure(result["flow_id"], sectioned({**data, "window_from": "22:00:00"}))
    assert bad["errors"] == {"base": "window_incomplete"}
    bad = await flow.async_configure(
        result["flow_id"], sectioned({**data, "persistent_enabled": False}))
    assert bad["errors"] == {"base": "no_method"}
    ok = await flow.async_configure(result["flow_id"], sectioned({**data, "name": "Wasser"}))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["threshold"] == 0.5 and "name" not in ok["data"]
    assert "window_from" not in ok["data"]


async def test_settings_page_saves_and_clears(hass: HomeAssistant, freezer) -> None:
    entry, controller, push = await _setup(hass, freezer, window_from="22:00:00", window_to="06:00:00")
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    assert result["step_id"] == "cg_settings" and not is_menu(result)
    data = {"name": "Dusche", "consumption_sensor": SENSOR, "threshold": 1, "duration_minutes": 20,
            "repeat_minutes": 5, "mobile_enabled": True, "mobile_targets": ["mobile_app_phone"],
            "tts_enabled": False, "persistent_enabled": False}
    done = await flow.async_configure(result["flow_id"], sectioned(data))
    assert done["type"] is FlowResultType.ABORT and done["reason"] == "reconfigure_successful"
    assert entry.options["window_from"] is None and entry.options["duration_minutes"] == 20
    assert entry.title.endswith("Dusche")


def test_references() -> None:
    entry = make_entry(domain=DOMAIN, title="Wasser", data=BASE)
    entities, _ = collect_references(entry.sub)
    assert SENSOR in entities
