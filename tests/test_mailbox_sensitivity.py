"""Briefkasten: Empfindlichkeit des Vibrationssensors, nur auf Anforderung."""

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from .helpers import is_menu, menu_options
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
    entry = MockConfigEntry(domain=DOMAIN, title="Briefkasten", data={**DATA, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _flat(**over):
    flat = {k: v for k, v in DATA.items() if k not in ("name", "function_type")}
    return sectioned({**flat, **over})


async def test_field_only_in_settings(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "mailbox"})
    general = next(v for k, v in result["data_schema"].schema.items() if str(k) == "general")
    assert "sensitivity_entity" not in {str(k) for k in general.schema.schema}

    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"action": "mailbox"})
    general = next(v for k, v in result["data_schema"].schema.items() if str(k) == "general")
    assert "sensitivity_entity" in {str(k) for k in general.schema.schema}


async def test_without_entity_nothing_changes(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"action": "mailbox"})
    done = await hass.config_entries.options.async_configure(result["flow_id"], _flat())
    assert is_menu(done) and "mailbox_sensitivity" not in menu_options(done)
    assert entry.options["sensitivity_entity"] is None and entry.options["sensitivity_value"] is None
    await hass.async_block_till_done()
    assert hass.states.get(BUTTON) is None


async def _open_settings(hass, entry):
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    return flow, await flow.async_configure(result["flow_id"], {"action": "mailbox"})


async def test_entity_is_stored_without_asking_for_a_value(hass: HomeAssistant) -> None:
    hass.states.async_set(NUMBER, "5", {"min": 1, "max": 21, "step": 1})
    entry = await _setup(hass)
    flow, result = await _open_settings(hass, entry)
    result = await flow.async_configure(result["flow_id"], _flat(sensitivity_entity=NUMBER))
    # kein Wertedialog direkt danach: zurück ins Menü, Punkt „Empfindlichkeit einstellen“ ist da
    assert is_menu(result) and menu_options(result) == ["mailbox", "mailbox_sensitivity", "done"]
    assert entry.options["sensitivity_entity"] == NUMBER
    assert entry.options["sensitivity_value"] is None
    await hass.async_block_till_done()
    assert hass.states.get(BUTTON) is None               # ohne Wert kein Button


async def test_number_value_set_later_from_the_menu(hass: HomeAssistant) -> None:
    hass.states.async_set(NUMBER, "5", {"min": 1, "max": 21, "step": 1})
    entry = await _setup(hass, sensitivity_entity=NUMBER)
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    assert menu_options(result) == ["mailbox", "mailbox_sensitivity", "done"]
    result = await flow.async_configure(result["flow_id"], {"action": "mailbox_sensitivity"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "mailbox_sensitivity"
    assert result["description_placeholders"] == {"entity": NUMBER}
    selector = next(iter(result["data_schema"].schema.values()))
    assert selector.config["min"] == 1 and selector.config["max"] == 21
    result = await flow.async_configure(result["flow_id"], {"sensitivity_value": 12})
    assert is_menu(result)
    assert entry.data["sensitivity_entity"] == NUMBER and entry.options["sensitivity_value"] == 12
    await hass.async_block_till_done()
    assert hass.states.get(BUTTON) is not None


async def test_select_flow_offers_the_entitys_options(hass: HomeAssistant) -> None:
    hass.states.async_set(SELECT, "medium", {"options": ["low", "medium", "high"]})
    entry = await _setup(hass, sensitivity_entity=SELECT)
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(result["flow_id"], {"action": "mailbox_sensitivity"})
    selector = next(iter(result["data_schema"].schema.values()))
    assert list(selector.config["options"]) == ["low", "medium", "high"] or [
        o["value"] for o in selector.config["options"]] == ["low", "medium", "high"]
    result = await flow.async_configure(result["flow_id"], {"sensitivity_value": "high"})
    assert entry.options["sensitivity_value"] == "high" and is_menu(result)


async def test_value_kept_when_saving_settings_and_dropped_on_entity_change(
    hass: HomeAssistant,
) -> None:
    hass.states.async_set(NUMBER, "5", {"min": 1, "max": 21})
    hass.states.async_set(SELECT, "medium", {"options": ["low", "medium"]})
    entry = await _setup(hass, sensitivity_entity=NUMBER, sensitivity_value=12)
    flow, result = await _open_settings(hass, entry)
    result = await flow.async_configure(result["flow_id"], _flat(sensitivity_entity=NUMBER))
    assert entry.options["sensitivity_value"] == 12      # gleiche Entität: Wert bleibt
    result = await flow.async_configure(result["flow_id"], {"action": "mailbox"})
    result = await flow.async_configure(result["flow_id"], _flat(sensitivity_entity=SELECT))
    assert entry.options["sensitivity_entity"] == SELECT
    assert entry.options["sensitivity_value"] is None    # andere Entität: alter Wert verworfen


async def test_nothing_is_sent_automatically(hass: HomeAssistant) -> None:
    hass.states.async_set(NUMBER, "5", {"min": 1, "max": 21})
    calls = async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass, sensitivity_entity=NUMBER, sensitivity_value=12)
    assert calls == []                                   # nicht beim Start
    assert await hass.config_entries.async_reload(entry.entry_id)
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
    assert is_menu(done) and "mailbox_sensitivity" not in menu_options(done)
    assert entry.options["sensitivity_entity"] is None and entry.options["sensitivity_value"] is None
    await hass.async_block_till_done()
    assert hass.states.get(BUTTON) is None
