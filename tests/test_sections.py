"""Einstellungsdialoge mit den Abschnitten Allgemein und Benachrichtigungen."""

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_housekeeper.const import DOMAIN

from .helpers import is_menu, sectioned

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
        ("door_guard",
         {"name", "lock", "contact", "block_action", "retry_minutes", "open_alert_minutes",
          "open_alert_repeat_minutes", "verify_seconds", "manual_override", "manual_pause_minutes"},
         NOTIFY_FIELDS),
        ("doorbell",
         {"name", "trigger_entity", "debounce_seconds"},
         {"mobile_enabled", "mobile_targets", "message", "clear_after_hours"}),
        ("task_planner", {"name"}, NOTIFY_FIELDS),
    ],
)
async def test_config_forms_have_sections(hass: HomeAssistant, function, general, notifications) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": function}
    )
    assert result["step_id"] == function
    _assert_sections(result["data_schema"].schema, general, notifications)


async def test_options_forms_have_sections(hass: HomeAssistant) -> None:
    hass.states.async_set("switch.pump", "off")
    cases = [
        ({"function_type": "door_guard", "name": "Tür", "lock": "lock.tuer", "rules": [],
          "persistent_enabled": True}, "general", "general"),
        ({"function_type": "doorbell", "name": "Klingel", "trigger_entity": "binary_sensor.k",
          "profiles": [], "mobile_enabled": False}, "bell_general", "bell_general"),
        ({"function_type": "pool_pump", "name": "Pool", "pump_entity": "switch.pump"},
         "dry_run", "dry_run"),
    ]
    for data, menu_item, step in cases:
        entry = MockConfigEntry(domain=DOMAIN, title=data["name"], data=data)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        flow = hass.config_entries.options
        result = await flow.async_init(entry.entry_id)
        result = await flow.async_configure(result["flow_id"], {"action": menu_item})
        assert result["step_id"] == step
        schema = result["data_schema"].schema
        assert [str(k) for k in schema] == ["general", "notifications"]
        assert "name" not in _fields(next(v for k, v in schema.items() if str(k) == "general"))


async def test_door_options_save_flat(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Tür",
        data={"function_type": "door_guard", "name": "Tür", "lock": "lock.tuer", "rules": [],
              "persistent_enabled": True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(result["flow_id"], {"action": "general"})
    flat = {"lock": "lock.tuer", "block_action": "notify", "retry_minutes": 10,
            "open_alert_minutes": 15, "open_alert_repeat_minutes": 10, "verify_seconds": 30,
            "manual_override": "ignore", "manual_pause_minutes": 60, "mobile_enabled": False,
            "tts_enabled": False, "persistent_enabled": True}
    bad = await flow.async_configure(result["flow_id"], sectioned(flat))
    assert bad["errors"] == {"base": "alert_needs_contact"}
    flat["contact"] = "binary_sensor.tuer"
    ok = await flow.async_configure(bad["flow_id"], sectioned(flat))
    assert is_menu(ok)
    assert entry.options["open_alert_minutes"] == 15
    assert entry.options["contact"] == "binary_sensor.tuer"
    assert "general" not in entry.options and "notifications" not in entry.options


async def test_planner_options_only_notifications_section(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Planer",
        data={"function_type": "task_planner", "name": "Planer", "tasks": [],
              "mobile_enabled": False, "persistent_enabled": True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(result["flow_id"], {"action": "tp_general"})
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
