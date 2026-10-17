"""Einstellungsdialoge mit den Abschnitten Allgemein und Benachrichtigungen."""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.ha_housekeeper.const import DOMAIN

from .helpers import is_menu, make_entry, reconfigure, new_instance

NOTIFY_FIELDS = {"mobile_enabled", "mobile_targets", "tts_enabled", "tts_entity",
                 "tts_player", "persistent_enabled"}


def _fields(section_obj) -> set[str]:
    return {str(k) for k in section_obj.schema.schema}


def _assert_sections(schema, general: set[str], notifications: set[str]) -> None:
    assert [str(k) for k in schema] == ["general", "notifications"]
    by_name = {str(k): v for k, v in schema.items()}
    for sect in by_name.values():
        assert sect.options["collapsed"] is False
    assert _fields(by_name["general"]) == general
    assert _fields(by_name["notifications"]) == notifications


@pytest.mark.parametrize(
    ("function", "general", "notifications"),
    [
        ("task_planner", {"name"}, NOTIFY_FIELDS),
    ],
)
async def test_config_forms_have_sections(hass: HomeAssistant, function, general, notifications) -> None:
    result = await new_instance(hass, function)
    assert result["step_id"] == f"new_{function}"
    _assert_sections(result["data_schema"].schema, general, notifications)


async def test_doorbell_config_form_has_only_general_section(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "doorbell")
    schema = result["data_schema"].schema
    assert [str(k) for k in schema] == ["general"]
    assert _fields(next(iter(schema.values()))) == {"name", "trigger_entity", "debounce_seconds"}


async def test_options_forms_have_sections(hass: HomeAssistant) -> None:
    hass.states.async_set("switch.pump", "off")
    cases = [
        ({"function_type": "doorbell", "name": "Klingel", "trigger_entity": "binary_sensor.k",
          "profiles": [], "mobile_enabled": False}, "bell_general", "bell_general"),
        ({"function_type": "pool_pump", "name": "Pool", "pump_entity": "switch.pump"},
         "dry_run", "dry_run"),
    ]
    for data, menu_item, step in cases:
        entry = make_entry(domain=DOMAIN, title=data["name"], data=data)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.hub_id)
        await hass.async_block_till_done()
        flow = hass.config_entries.subentries
        result = await reconfigure(hass, entry)
        result = await flow.async_configure(result["flow_id"], {"next_step_id": menu_item})
        assert result["step_id"] == step
        schema = result["data_schema"].schema
        # Türklingel: Push steckt in den Profilen, daher nur „Allgemein“
        assert [str(k) for k in schema] == (
            ["general"] if step == "bell_general" else ["general", "notifications"])
        assert "name" not in _fields(next(v for k, v in schema.items() if str(k) == "general"))


async def test_planner_options_only_notifications_section(hass: HomeAssistant) -> None:
    entry = make_entry(
        domain=DOMAIN, title="Planer",
        data={"function_type": "task_planner", "name": "Planer", "tasks": [],
              "mobile_enabled": False, "persistent_enabled": True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "tp_general"})
    assert [str(k) for k in result["data_schema"].schema] == ["notifications"]
    bad = await flow.async_configure(
        result["flow_id"],
        {"notifications": {"mobile_enabled": True, "tts_enabled": False, "persistent_enabled": False}},
    )
    assert bad["errors"] == {"base": "no_targets"}
    ok = await flow.async_configure(
        bad["flow_id"],
        {"notifications": {"mobile_enabled": False, "tts_enabled": False, "persistent_enabled": False}},
    )
    assert is_menu(ok)
    assert entry.options["persistent_enabled"] is False
