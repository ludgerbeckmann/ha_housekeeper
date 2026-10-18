"""Briefkasten: Empfindlichkeit des Vibrationssensors, nur auf Anforderung."""

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    async_mock_service,
)

from .helpers import make_entry, reconfigure, new_instance
from custom_components.ha_housekeeper.const import DOMAIN

from .helpers import sectioned

SENSOR = "binary_sensor.briefkasten_vibration"
NUMBER = "number.vibrationssensor_sensitivity"
SELECT = "select.vibrationssensor_sensitivity"
BUTTON = "button.briefkasten_send_sensitivity"

DATA = {
    "function_type": "mailbox", "name": "Briefkasten", "vibration_sensor": SENSOR,
    "mobile_enabled": False, "tts_enabled": False, "persistent_enabled": True,
    "message": "Post!", "debounce_seconds": 0, "auto_reset_hours": 0,
}


async def _setup(hass: HomeAssistant, **over):
    hass.states.async_set(SENSOR, "off")
    entry = make_entry(domain=DOMAIN, title="Briefkasten", data={**DATA, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry


SENSITIVITY_KEYS = ("sensitivity_entity", "sensitivity_value")


def _flat(**over):
    """Eingaben der Einstellungsseite (der Name steht im Abschnitt „Allgemein“)."""
    flat = {k: v for k, v in DATA.items() if k != "function_type"}
    sections = sectioned({k: v for k, v in {**flat, **over}.items() if k not in SENSITIVITY_KEYS})
    sections["sensitivity"] = {k: v for k, v in over.items() if k in SENSITIVITY_KEYS and v is not None}
    return sections


async def _open_settings(hass, entry):
    flow = hass.config_entries.subentries
    return flow, await reconfigure(hass, entry)


def _sensitivity_fields(result) -> dict:
    section = next(v for k, v in result["data_schema"].schema.items() if str(k) == "sensitivity")
    return {str(k): v for k, v in section.schema.schema.items()}


async def test_field_only_in_settings(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "mailbox")
    assert "sensitivity" not in {str(k) for k in result["data_schema"].schema}

    entry = await _setup(hass)
    _, result = await _open_settings(hass, entry)
    assert set(_sensitivity_fields(result)) == {"sensitivity_entity"}       # Wertfeld erst mit gespeicherter Entität


async def test_without_entity_nothing_changes(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    flow, result = await _open_settings(hass, entry)
    done = await flow.async_configure(result["flow_id"], _flat())
    assert done["reason"] == "reconfigure_successful"
    assert entry.options["sensitivity_entity"] is None and entry.options["sensitivity_value"] is None
    await hass.async_block_till_done()
    assert hass.states.get(BUTTON) is None


async def test_entity_is_stored_and_value_is_asked_on_the_next_visit(hass: HomeAssistant) -> None:
    hass.states.async_set(NUMBER, "5", {"min": 1, "max": 21, "step": 1})
    entry = await _setup(hass)
    flow, result = await _open_settings(hass, entry)
    done = await flow.async_configure(result["flow_id"], _flat(sensitivity_entity=NUMBER))
    assert done["reason"] == "reconfigure_successful"
    assert entry.options["sensitivity_entity"] == NUMBER and entry.options["sensitivity_value"] is None
    await hass.async_block_till_done()
    assert hass.states.get(BUTTON) is None               # ohne Wert kein Button
    # beim nächsten Öffnen gibt es das Wertfeld, passend zur Entität (Zahl mit Grenzen)
    _, result = await _open_settings(hass, entry)
    fields = _sensitivity_fields(result)
    assert set(fields) == {"sensitivity_entity", "sensitivity_value"}
    value = fields["sensitivity_value"]
    assert value.config["min"] == 1 and value.config["max"] == 21
    done = await flow.async_configure(
        result["flow_id"], _flat(sensitivity_entity=NUMBER, sensitivity_value=12))
    assert done["reason"] == "reconfigure_successful" and entry.options["sensitivity_value"] == 12
    await hass.async_block_till_done()
    assert hass.states.get(BUTTON) is not None


async def test_select_value_offers_the_entitys_options(hass: HomeAssistant) -> None:
    hass.states.async_set(SELECT, "medium", {"options": ["low", "medium", "high"]})
    entry = await _setup(hass, sensitivity_entity=SELECT)
    flow, result = await _open_settings(hass, entry)
    value = _sensitivity_fields(result)["sensitivity_value"]
    assert [o["value"] if isinstance(o, dict) else o for o in value.config["options"]] == [
        "low", "medium", "high"]
    await flow.async_configure(
        result["flow_id"], _flat(sensitivity_entity=SELECT, sensitivity_value="high"))
    assert entry.options["sensitivity_value"] == "high"


async def test_value_kept_when_unchanged_and_dropped_on_entity_change(
    hass: HomeAssistant,
) -> None:
    hass.states.async_set(NUMBER, "5", {"min": 1, "max": 21})
    hass.states.async_set(SELECT, "medium", {"options": ["low", "medium"]})
    entry = await _setup(hass, sensitivity_entity=NUMBER, sensitivity_value=12)
    flow, result = await _open_settings(hass, entry)
    await flow.async_configure(
        result["flow_id"], _flat(sensitivity_entity=NUMBER, sensitivity_value=12))
    assert entry.options["sensitivity_value"] == 12      # gleiche Entität: Wert bleibt
    flow, result = await _open_settings(hass, entry)
    await flow.async_configure(
        result["flow_id"], _flat(sensitivity_entity=SELECT, sensitivity_value=12))
    assert entry.options["sensitivity_entity"] == SELECT
    assert entry.options["sensitivity_value"] is None    # andere Entität: alter Wert verworfen


async def test_nothing_is_sent_automatically(hass: HomeAssistant) -> None:
    hass.states.async_set(NUMBER, "5", {"min": 1, "max": 21})
    calls = async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass, sensitivity_entity=NUMBER, sensitivity_value=12)
    assert calls == []                                   # nicht beim Start
    assert await hass.config_entries.async_reload(entry.hub_id)
    hass.states.async_set(SENSOR, "unavailable")
    hass.states.async_set(SENSOR, "off")                 # Sensor wird wieder erreichbar
    await hass.async_block_till_done()
    assert calls == []                                   # weder beim Neuladen noch bei Erreichbarkeit


async def test_button_sends_number_value(hass: HomeAssistant) -> None:
    hass.states.async_set(NUMBER, "5", {"min": 1, "max": 21})
    calls = async_mock_service(hass, "number", "set_value")
    await _setup(hass, sensitivity_entity=NUMBER, sensitivity_value=12)
    await hass.services.async_call("button", "press", {"entity_id": BUTTON}, blocking=True)
    assert [c.data for c in calls] == [{"entity_id": NUMBER, "value": 12.0}]


async def test_button_sends_select_option(hass: HomeAssistant) -> None:
    hass.states.async_set(SELECT, "medium", {"options": ["low", "medium", "high"]})
    calls = async_mock_service(hass, "select", "select_option")
    await _setup(hass, sensitivity_entity=SELECT, sensitivity_value="high")
    await hass.services.async_call("button", "press", {"entity_id": BUTTON}, blocking=True)
    assert [c.data for c in calls] == [{"entity_id": SELECT, "option": "high"}]


async def test_failure_is_reported_not_swallowed(hass: HomeAssistant) -> None:
    hass.states.async_set(NUMBER, "5")

    async def failing(call: ServiceCall) -> None:
        raise HomeAssistantError("Sensor schläft")

    hass.services.async_register("number", "set_value", failing)
    await _setup(hass, sensitivity_entity=NUMBER, sensitivity_value=12)
    with pytest.raises(HomeAssistantError, match="Sensor schläft"):
        await hass.services.async_call("button", "press", {"entity_id": BUTTON}, blocking=True)


async def test_clearing_entity_removes_value_and_button(hass: HomeAssistant) -> None:
    hass.states.async_set(NUMBER, "5", {"min": 1, "max": 21})
    entry = await _setup(hass, sensitivity_entity=NUMBER, sensitivity_value=12)
    assert hass.states.get(BUTTON) is not None
    flow, result = await _open_settings(hass, entry)
    done = await flow.async_configure(result["flow_id"], _flat())     # Feld leer
    assert done["reason"] == "reconfigure_successful"
    assert entry.options["sensitivity_entity"] is None and entry.options["sensitivity_value"] is None
    await hass.async_block_till_done()
    assert hass.states.get(BUTTON) is None
