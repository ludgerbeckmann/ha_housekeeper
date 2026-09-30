"""Menüs der Einstellungen als Formular mit Auswahlliste und „Weiter“."""

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
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
async def test_menu_is_form_ending_with_save_and_close(hass: HomeAssistant, function) -> None:
    _, result = await _open(hass, ENTRIES[function])
    assert is_menu(result)
    options = menu_options(result)
    assert options[-1] == "done"
    assert not any(o.startswith("edit_") or o.startswith("delete_") for o in options)


async def test_menu_selection_dispatches_and_done_closes(hass: HomeAssistant) -> None:
    entry, result = await _open(hass, ENTRIES["updater"])
    flow = hass.config_entries.options
    result = await flow.async_configure(result["flow_id"], {"action": "add_schedule"})
    assert result["step_id"] == "schedule_edit" and not is_menu(result)
    # ungültige Auswahl wird von der Oberfläche abgelehnt
    _, menu = await _open(
        hass, {**ENTRIES["task_planner"], "name": "Planer 2"}
    )
    with pytest.raises(Exception):  # noqa: B017
        await flow.async_configure(menu["flow_id"], {"action": "gibt_es_nicht"})
    done = await flow.async_configure(menu["flow_id"], {"action": "done"})
    assert done["type"] is FlowResultType.CREATE_ENTRY


def test_translations_cover_all_menu_options() -> None:
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        data = json.loads((COMPONENT / name).read_text(encoding="utf-8"))
        labels = data["selector"]["menu_action"]["options"]
        steps = data["options"]["step"]
        assert not any("menu_options" in step for step in steps.values()), name
        for step_id in ("menu", "bell_menu", "pool_menu", "knx_menu", "upd_menu", "tp_menu",
                        "task_triggers"):
            assert list(steps[step_id]["data"]) == ["action"], (name, step_id)
        assert labels["done"] in ("Save & close", "Speichern & schließen")
        # jeder Eintrag, den ein Menü anbieten kann, hat eine Beschriftung
        source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
        for option in ("general", "add_rule", "edit_rule", "delete_rule", "bell_general", "add_profile",
                       "pool_general", "add_window", "dry_run", "knx_general", "add_command",
                       "add_status", "upd_general", "add_schedule", "tp_general", "add_task",
                       "add_trigger", "delete_trigger", "task_save", "done"):
            assert option in labels and f'"{option}"' in source, (name, option)
