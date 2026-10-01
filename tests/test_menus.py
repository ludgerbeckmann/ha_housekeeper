"""Menüs der Einstellungen: native Menüs, direkt anklickbar, ohne Abschlusseintrag."""

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_housekeeper.const import DOMAIN

from .helpers import is_menu, menu_options

COMPONENT = Path(__file__).parent.parent / "custom_components" / "ha_housekeeper"

ENTRIES = {
    "door_guard": {"function_type": "door_guard", "name": "Tür", "lock": "lock.t", "rules": []},
    "doorbell": {"function_type": "doorbell", "name": "Klingel", "trigger_entity": "binary_sensor.k",
                 "profiles": [], "mobile_enabled": False},
    "pool_pump": {"function_type": "pool_pump", "name": "Pool", "pump_entity": "switch.p"},
    "knx_sonos": {"function_type": "knx_sonos", "name": "KNX", "player": "media_player.s",
                  "commands": [], "status": []},
    "updater": {"function_type": "updater", "name": "Updater", "schedules": [],
                "persistent_enabled": True},
    "alarm_clock": {"function_type": "alarm_clock", "name": "Wecker", "alarms": [],
                    "mobile_enabled": False},
    "task_planner": {"function_type": "task_planner", "name": "Planer", "tasks": [],
                     "persistent_enabled": True},
}


async def _open(hass: HomeAssistant, data: dict):
    entry = MockConfigEntry(domain=DOMAIN, title=data["name"], data=data)
    entry.add_to_hass(hass)
    hass.states.async_set("switch.p", "off")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, await hass.config_entries.options.async_init(entry.entry_id)


@pytest.mark.parametrize("function", list(ENTRIES))
async def test_menu_is_native_without_done_entry(hass: HomeAssistant, function) -> None:
    _, result = await _open(hass, ENTRIES[function])
    assert is_menu(result)
    options = menu_options(result)
    assert "done" not in options
    assert not any(
        (o.startswith("edit_") and o != "edit_speaker") or o.startswith("delete_") for o in options
    )


async def test_menu_selection_dispatches(hass: HomeAssistant) -> None:
    entry, result = await _open(hass, ENTRIES["updater"])
    flow = hass.config_entries.options
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_schedule"})
    assert result["step_id"] == "schedule_edit" and not is_menu(result)
    # ungültige Auswahl wird abgelehnt
    _, menu = await _open(
        hass, {**ENTRIES["task_planner"], "name": "Planer 2"}
    )
    with pytest.raises(Exception):  # noqa: B017
        await flow.async_configure(menu["flow_id"], {"next_step_id": "gibt_es_nicht"})


def test_translations_cover_all_menu_options() -> None:
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        data = json.loads((COMPONENT / name).read_text(encoding="utf-8"))
        steps = data["options"]["step"]
        assert "menu_action" not in data.get("selector", {}), name
        menus = {step_id: step["menu_options"] for step_id, step in steps.items() if "menu_options" in step}
        assert set(menus) == {"menu", "bell_menu", "pool_menu", "knx_menu", "upd_menu", "tp_menu",
                              "task_triggers", "alarm_menu", "mailbox_menu"}, name
        assert not any("done" in labels for labels in menus.values()), name
        # jeder Eintrag, den ein Menü anbieten kann, hat in seinem Menü eine Beschriftung
        labels = {option for options in menus.values() for option in options}
        source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8") + "".join(
            path.read_text(encoding="utf-8") for path in (COMPONENT / "flows").glob("*.py")
        )
        for option in ("general", "add_rule", "edit_rule", "delete_rule", "bell_general", "add_profile",
                       "pool_general", "add_window", "dry_run", "heater", "add_speaker", "edit_speaker",
                       "delete_speaker", "add_command", "add_status", "upd_general", "add_schedule",
                       "tp_general", "add_task", "add_trigger", "delete_trigger", "task_save",
                       "alarm_general", "add_alarm", "edit_alarm", "delete_alarm", "mailbox",
                       "mailbox_sensitivity"):
            assert option in labels and f'"{option}"' in source, (name, option)
