"""Tests für die Funktion Integrationsmonitor."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from .helpers import is_menu, make_entry, menu_options, new_instance, reconfigure, sectioned
from custom_components.ha_housekeeper import integration_monitor as mon
from custom_components.ha_housekeeper.const import DOMAIN

BASE = {
    "function_type": "integration_monitor", "name": "Monitor",
    "grace_minutes": 5, "min_entities": 2, "check_minutes": 1, "notify_all": True,
    "excluded": [], "mobile_enabled": True, "mobile_targets": ["mobile_app_phone"],
    "tts_enabled": False, "persistent_enabled": False, "monitor_rules": [],
}


def foreign(hass, title="Drucker", state=ConfigEntryState.LOADED, domain="printer_x"):
    entry = MockConfigEntry(domain=domain, title=title)
    entry.add_to_hass(hass)
    entry.mock_state(hass, state)
    return entry


def add_entities(hass, entry, states):
    """Entitäten der Integration anlegen, `states` = Zustände."""
    registry = er.async_get(hass)
    for i, state in enumerate(states):
        entity = registry.async_get_or_create(
            "sensor", entry.domain, f"{entry.entry_id}_{i}", config_entry=entry)
        hass.states.async_set(entity.entity_id, state)


def rule(entries, i="r1", action="none", notify=True, error=True, unavailable=True,
         presence=None, reenable=False, enabled=True):
    return {"id": i, "name": f"Regel {i}", "enabled": enabled, "entries": list(entries),
            "on_error": error, "on_unavailable": unavailable, "action": action,
            "notify": notify, "presence_entity": presence, "reenable": reenable}


async def _setup(hass, **over):
    push = async_mock_service(hass, "notify", "mobile_app_phone")
    entry = make_entry(domain=DOMAIN, title="Monitor", data={**BASE, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id], push


def messages(push):
    """Gesendete Meldungen ohne die Löschaufrufe (`clear_notification`)."""
    return [c.data["message"] for c in push if c.data["message"] != "clear_notification"]


def age(ctrl, minutes=10):
    """Störungen so behandeln, als bestünden sie schon länger als die Wartezeit."""
    now = dt_util.utcnow()
    for eid, (kind, _) in list(ctrl._since.items()):
        ctrl._since[eid] = (kind, now - timedelta(minutes=minutes))


async def check(ctrl, minutes=10):
    """Zweimal prüfen: erst Störung merken, dann (nach der Wartezeit) bestätigen."""
    await ctrl.async_check()
    age(ctrl, minutes)
    await ctrl.async_check()


# --- reine Funktionen ------------------------------------------------------------------


async def test_entry_status(hass: HomeAssistant) -> None:
    entry = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    assert mon.entry_status(hass, entry, 2) == mon.KIND_ERROR
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    assert mon.entry_status(hass, entry, 2) is None
    entry.mock_state(hass, ConfigEntryState.LOADED)
    assert mon.entry_status(hass, entry, 2) == mon.STATUS_OK          # keine Entitäten
    add_entities(hass, entry, ["unavailable", "unavailable"])
    assert mon.entry_status(hass, entry, 2) == mon.KIND_UNAVAILABLE
    assert mon.entry_status(hass, entry, 3) == mon.STATUS_OK          # zu wenige Entitäten
    add_entities(hass, entry, ["unavailable", "unavailable", "on"])
    assert mon.entry_status(hass, entry, 2) == mon.STATUS_OK          # eine Entität läuft


def test_rule_matches() -> None:
    r = rule(["a"], unavailable=False)
    assert mon.rule_matches(r, "a", mon.KIND_ERROR)
    assert not mon.rule_matches(r, "a", mon.KIND_UNAVAILABLE)
    assert not mon.rule_matches(r, "b", mon.KIND_ERROR)
    assert not mon.rule_matches(rule(["a"], enabled=False), "a", mon.KIND_ERROR)


# --- Überwachung und Meldung ---------------------------------------------------------------


async def test_waits_for_grace_time_then_reports_once(hass: HomeAssistant) -> None:
    broken = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    _, ctrl, push = await _setup(hass)
    await ctrl.async_check()
    assert push == [] and ctrl.faults == {}              # Wartezeit läuft noch
    age(ctrl)
    await ctrl.async_check()
    assert len(messages(push)) == 1 and "Drucker" in messages(push)[0]
    assert ctrl.faulty_titles == ["Drucker"]
    await ctrl.async_check()
    assert len(messages(push)) == 1                       # nur einmal je Störung
    broken.mock_state(hass, ConfigEntryState.LOADED)
    await ctrl.async_check()
    assert ctrl.faults == {} and len(messages(push)) == 2   # Entwarnung
    assert "working again" in messages(push)[1] or "läuft wieder" in messages(push)[1]


async def test_unavailable_entities_are_a_fault(hass: HomeAssistant) -> None:
    entry = foreign(hass)
    add_entities(hass, entry, ["unavailable", "unavailable"])
    _, ctrl, push = await _setup(hass)
    await check(ctrl)
    assert ctrl.faults[entry.entry_id]["kind"] == mon.KIND_UNAVAILABLE
    assert len(push) == 1


async def test_excluded_and_notify_all_off_are_silent(hass: HomeAssistant) -> None:
    broken = foreign(hass, state=ConfigEntryState.SETUP_ERROR)
    _, ctrl, push = await _setup(hass, excluded=[broken.entry_id])
    await check(ctrl)
    assert push == [] and ctrl.faults                     # erkannt, aber nicht gemeldet


async def test_own_integration_is_not_monitored(hass: HomeAssistant) -> None:
    _, ctrl, push = await _setup(hass)
    hub_entries = hass.config_entries.async_entries(DOMAIN)
    assert hub_entries
    await check(ctrl)
    assert ctrl.faults == {}


async def test_switch_off_pauses_everything(hass: HomeAssistant) -> None:
    foreign(hass, state=ConfigEntryState.SETUP_ERROR)
    _, ctrl, push = await _setup(hass)
    await ctrl.async_set_enabled(False)
    await check(ctrl)
    assert push == [] and ctrl.faults == {}


# --- Regeln: Aktionen --------------------------------------------------------------------------


async def test_rule_reloads_the_integration(hass: HomeAssistant, monkeypatch) -> None:
    broken = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    reload = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)
    _, ctrl, push = await _setup(
        hass, notify_all=False, monitor_rules=[rule([broken.entry_id], action="reload")])
    await check(ctrl)
    reload.assert_awaited_once_with(broken.entry_id)
    assert len(push) == 1                                 # die Regel meldet selbst
    await ctrl.async_check()
    reload.assert_awaited_once()                          # nur einmal je Störung


async def test_rule_only_applies_to_selected_integrations(hass: HomeAssistant, monkeypatch) -> None:
    chosen = foreign(hass, "Drucker", ConfigEntryState.SETUP_RETRY, "printer_x")
    other = foreign(hass, "Klima", ConfigEntryState.SETUP_RETRY, "ac_x")
    reload = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)
    _, ctrl, push = await _setup(
        hass, notify_all=False, monitor_rules=[rule([chosen.entry_id], action="reload")])
    await check(ctrl)
    reload.assert_awaited_once_with(chosen.entry_id)
    assert other.entry_id in ctrl.faults and ctrl.faults[other.entry_id]["notified"] is False


async def test_rule_condition_must_match(hass: HomeAssistant, monkeypatch) -> None:
    broken = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    reload = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)
    _, ctrl, _ = await _setup(
        hass, monitor_rules=[rule([broken.entry_id], action="reload", error=False)])
    await check(ctrl)
    reload.assert_not_awaited()


async def test_disabled_rule_does_nothing(hass: HomeAssistant, monkeypatch) -> None:
    broken = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    reload = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)
    _, ctrl, _ = await _setup(
        hass, monitor_rules=[rule([broken.entry_id], action="reload", enabled=False)])
    await check(ctrl)
    reload.assert_not_awaited()


async def test_failed_action_is_reported(hass: HomeAssistant, monkeypatch) -> None:
    broken = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    monkeypatch.setattr(
        hass.config_entries, "async_reload", AsyncMock(side_effect=RuntimeError("kaputt")))
    _, ctrl, push = await _setup(
        hass, monitor_rules=[rule([broken.entry_id], action="reload")])
    await check(ctrl)
    assert len(messages(push)) == 1
    assert "fehlgeschlagen" in messages(push)[0] or "failed" in messages(push)[0]


# --- Deaktivieren und wieder aktivieren ---------------------------------------------------------


async def test_rule_disables_and_presence_reenables(hass: HomeAssistant) -> None:
    printer = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    hass.states.async_set("binary_sensor.drucker_da", "off")
    _, ctrl, push = await _setup(
        hass, monitor_rules=[rule([printer.entry_id], action="disable",
                                  presence="binary_sensor.drucker_da", reenable=True)])
    await check(ctrl)
    assert printer.disabled_by is ConfigEntryDisabler.USER
    assert ctrl.disabled == {printer.entry_id: "r1"}
    assert ctrl.disabled_titles == ["Drucker"] and ctrl.faulty_titles == []
    await ctrl.async_check()
    assert printer.disabled_by is ConfigEntryDisabler.USER   # Gerät noch nicht da
    hass.states.async_set("binary_sensor.drucker_da", "on")
    await hass.async_block_till_done()
    assert printer.disabled_by is None
    assert ctrl.disabled == {} and ctrl.faults == {}
    assert any("aktiviert" in m or "enabled" in m for m in messages(push))


async def test_without_reenable_stays_disabled(hass: HomeAssistant) -> None:
    printer = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    hass.states.async_set("binary_sensor.drucker_da", "on")
    _, ctrl, _ = await _setup(
        hass, monitor_rules=[rule([printer.entry_id], action="disable",
                                  presence="binary_sensor.drucker_da", reenable=False)])
    await check(ctrl)
    await ctrl.async_check()
    assert printer.disabled_by is ConfigEntryDisabler.USER


async def test_reenable_button_enables_all(hass: HomeAssistant) -> None:
    printer = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    _, ctrl, _ = await _setup(
        hass, monitor_rules=[rule([printer.entry_id], action="disable")])
    await check(ctrl)
    assert ctrl.disabled
    await ctrl.async_reenable_all()
    assert printer.disabled_by is None and ctrl.disabled == {}


async def test_manually_enabled_integration_is_forgotten(hass: HomeAssistant) -> None:
    printer = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    _, ctrl, _ = await _setup(
        hass, monitor_rules=[rule([printer.entry_id], action="disable")])
    await check(ctrl)
    await hass.config_entries.async_set_disabled_by(printer.entry_id, None)
    printer.mock_state(hass, ConfigEntryState.LOADED)
    await ctrl.async_check()
    assert ctrl.disabled == {} and ctrl.faults == {}


async def test_user_disabled_integration_is_never_touched(hass: HomeAssistant) -> None:
    printer = foreign(hass, state=ConfigEntryState.NOT_LOADED)
    await hass.config_entries.async_set_disabled_by(printer.entry_id, ConfigEntryDisabler.USER)
    _, ctrl, push = await _setup(
        hass, monitor_rules=[rule([printer.entry_id], action="disable")])
    await check(ctrl)
    assert push == [] and ctrl.faults == {} and ctrl.disabled == {}
    await ctrl.async_reenable_all()
    assert printer.disabled_by is ConfigEntryDisabler.USER


async def test_state_survives_restart(hass: HomeAssistant) -> None:
    printer = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    entry, ctrl, push = await _setup(
        hass, monitor_rules=[rule([printer.entry_id], action="disable")])
    await check(ctrl)
    await hass.config_entries.async_reload(entry.hub_id)
    await hass.async_block_till_done()
    ctrl2 = hass.data[DOMAIN][entry.entry_id]
    assert ctrl2.disabled == {printer.entry_id: "r1"}


# --- Entitäten -------------------------------------------------------------------------------


async def test_entities(hass: HomeAssistant) -> None:
    foreign(hass, state=ConfigEntryState.SETUP_ERROR)
    _, ctrl, _ = await _setup(hass)
    await check(ctrl)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    ids = {e.translation_key: e.entity_id for e in registry.entities.values()
           if e.platform == DOMAIN}
    assert set(ids) == {"monitor_active", "monitor_problem", "monitor_faulty",
                        "monitor_disabled", "monitor_check_now", "monitor_reenable"}
    assert hass.states.get(ids["monitor_problem"]).state == "on"
    assert hass.states.get(ids["monitor_faulty"]).state == "1"
    assert hass.states.get(ids["monitor_faulty"]).attributes["integrations"] == ["Drucker"]
    assert hass.states.get(ids["monitor_disabled"]).state == "0"


# --- Einstellungsdialoge -------------------------------------------------------------------------


async def test_create_instance_flow(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "integration_monitor")
    assert result["step_id"] == "new_integration_monitor"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        sectioned({"name": "Integration monitor", "grace_minutes": 5, "min_entities": 2,
                   "check_minutes": 1, "notify_all": True, "excluded": [],
                   "mobile_enabled": False, "persistent_enabled": True,
                   "tts_enabled": False}))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Integration monitor"
    assert result["data"]["monitor_rules"] == [] and result["data"]["notify_all"] is True


async def test_create_needs_a_method_when_reporting_all(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "integration_monitor")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        sectioned({"name": "M", "grace_minutes": 5, "min_entities": 2, "check_minutes": 1,
                   "notify_all": True, "excluded": [], "mobile_enabled": False,
                   "persistent_enabled": False, "tts_enabled": False}))
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "no_method"}


async def _rule_form(hass, entry):
    menu = await reconfigure(hass, entry)
    assert is_menu(menu) and menu["step_id"] == "mon_menu"
    assert menu_options(menu) == ["mon_general", "add_monitor_rule", "rename"]
    result = await hass.config_entries.subentries.async_configure(
        menu["flow_id"], {"next_step_id": "add_monitor_rule"})
    assert result["step_id"] == "monitor_rule_edit"
    return result


def rule_input(entry_ids, **over):
    values = {"name": "Drucker", "enabled": True, "entries": list(entry_ids), "on_error": True,
              "on_unavailable": True, "action": "disable", "notify": True,
              "presence_entity": "binary_sensor.drucker_da", "reenable": True}
    values.update(over)
    return {"general": {k: values[k] for k in ("name", "enabled")},
            "condition": {k: values[k] for k in ("entries", "on_error", "on_unavailable")},
            "action": {k: values[k] for k in ("action", "notify", "presence_entity", "reenable")}}


async def test_add_rule_flow(hass: HomeAssistant) -> None:
    printer = foreign(hass)
    entry, _, _ = await _setup(hass)
    result = await _rule_form(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], rule_input([printer.entry_id]))
    assert is_menu(result)
    saved = entry.options["monitor_rules"]
    assert len(saved) == 1 and saved[0]["entries"] == [printer.entry_id]
    assert saved[0]["action"] == "disable" and saved[0]["reenable"] is True


@pytest.mark.parametrize("over,error", [
    ({"entries": []}, "no_integration"),
    ({"on_error": False, "on_unavailable": False}, "no_condition"),
    ({"action": "none", "notify": False, "reenable": False}, "nothing_to_do"),
    ({"presence_entity": None}, "no_presence"),
    ({"action": "reload"}, "reenable_needs_disable"),
])
async def test_rule_validation(hass: HomeAssistant, over, error) -> None:
    printer = foreign(hass)
    entry, _, _ = await _setup(hass)
    result = await _rule_form(hass, entry)
    data = rule_input([printer.entry_id], **over)
    if over.get("presence_entity", 1) is None:
        del data["action"]["presence_entity"]
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], data)
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": error}


async def test_rule_notify_needs_a_method(hass: HomeAssistant) -> None:
    printer = foreign(hass)
    entry, _, _ = await _setup(
        hass, notify_all=False, mobile_enabled=False, persistent_enabled=False)
    result = await _rule_form(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], rule_input([printer.entry_id]))
    assert result["errors"] == {"base": "no_method"}


async def test_edit_and_delete_rule(hass: HomeAssistant) -> None:
    printer = foreign(hass)
    entry, _, _ = await _setup(hass, monitor_rules=[rule([printer.entry_id])])
    menu = await reconfigure(hass, entry)
    assert menu_options(menu) == [
        "mon_general", "add_monitor_rule", "edit_monitor_rule", "delete_monitor_rule", "rename"]
    result = await hass.config_entries.subentries.async_configure(
        menu["flow_id"], {"next_step_id": "delete_monitor_rule"})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"rule": "r1"})
    assert is_menu(result) and entry.options["monitor_rules"] == []


async def test_general_settings_clear_optional_fields(hass: HomeAssistant) -> None:
    entry, _, _ = await _setup(hass)
    menu = await reconfigure(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        menu["flow_id"], {"next_step_id": "mon_general"})
    assert result["step_id"] == "mon_general"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        sectioned({"grace_minutes": 10, "min_entities": 1, "check_minutes": 2,
                   "notify_all": True, "excluded": [], "mobile_enabled": False,
                   "persistent_enabled": True, "tts_enabled": False}))
    assert is_menu(result)
    assert entry.options["grace_minutes"] == 10 and entry.options["mobile_targets"] is None
