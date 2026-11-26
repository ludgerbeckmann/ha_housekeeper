"""Tests für die Funktion Integrationsmonitor."""

from datetime import timedelta
from unittest.mock import AsyncMock


from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from .helpers import is_menu, make_entry, new_instance, reconfigure
from custom_components.ha_housekeeper import integration_monitor as mon
from custom_components.ha_housekeeper.const import DOMAIN

BASE = {
    "function_type": "integration_monitor", "name": "Monitor",
    "grace_minutes": 5, "min_entities": 2, "check_minutes": 1, "notify_errors": True,
    "notify_unavailable": True, "summary_minutes": 0,
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
    # Entwarnung: die Sammelmeldung verschwindet (Löschaufruf), es kommt keine neue Meldung
    assert ctrl.faults == {} and ctrl.summary["sent"] == []
    assert len(messages(push)) == 1 and push[-1].data["message"] == "clear_notification"


async def test_unavailable_entities_are_a_fault(hass: HomeAssistant) -> None:
    entry = foreign(hass)
    add_entities(hass, entry, ["unavailable", "unavailable"])
    _, ctrl, push = await _setup(hass)
    await check(ctrl)
    assert ctrl.faults[entry.entry_id]["kind"] == mon.KIND_UNAVAILABLE
    assert len(push) == 1


async def test_excluded_and_switches_off_are_silent(hass: HomeAssistant) -> None:
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
        hass, notify_errors=False, notify_unavailable=False, monitor_rules=[rule([broken.entry_id], action="reload")])
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
        hass, notify_errors=False, notify_unavailable=False, monitor_rules=[rule([chosen.entry_id], action="reload")])
    await check(ctrl)
    reload.assert_awaited_once_with(chosen.entry_id)
    assert other.entry_id in ctrl.faults and ctrl.faults[other.entry_id]["reported"] is False


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
    assert ctrl.summary["sent"] == []                          # wieder in Ordnung: Meldung entfernt
    assert any("deaktiviert" in m or "disabled" in m for m in messages(push))


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
                        "monitor_disabled", "monitor_check_now", "monitor_reenable",
                        "monitor_reset_known"}
    assert hass.states.get(ids["monitor_problem"]).state == "on"
    assert hass.states.get(ids["monitor_faulty"]).state == "1"
    assert hass.states.get(ids["monitor_faulty"]).attributes["integrations"] == ["Drucker"]
    assert hass.states.get(ids["monitor_disabled"]).state == "0"


# --- Einstellungsdialoge -------------------------------------------------------------------------


def mon_page(**over):
    """Eingaben der Seite: flache Felder auf die Abschnitte verteilen."""
    sections = {
        "general": {"name": "Integration monitor", "grace_minutes": 5, "min_entities": 2, "check_minutes": 1},
        "report": {"report_mode": "blacklist", "report_entries": []},
        "reload": {"reload_mode": "whitelist", "reload_entries": [], "reload_on_error": True,
                   "reload_on_unavailable": True},
        "disable": {"disable_mode": "whitelist", "disable_entries": [], "disable_on_error": True,
                    "disable_on_unavailable": True, "disable_reenable": False},
        "notifications": {"notify_errors": True, "notify_unavailable": False, "summary_minutes": 10,
                          "mobile_enabled": False, "persistent_enabled": True, "tts_enabled": False},
    }
    for key, value in over.items():
        if key == "disable_presence":
            sections["disable"][key] = value
            continue
        for fields in sections.values():
            if key in fields:
                fields[key] = value
                break
        else:
            sections.setdefault("legacy", {})[key] = value
    return sections


async def test_create_instance_flow(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "integration_monitor")
    assert result["step_id"] == "new_integration_monitor"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], mon_page())
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Integration monitor"
    assert result["data"]["notify_errors"] is True and result["data"]["report_mode"] == "blacklist"
    assert result["data"]["notify_unavailable"] is False and "notify_all" not in result["data"]


async def test_create_needs_a_method_when_reporting_all(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "integration_monitor")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], mon_page(persistent_enabled=False))
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "no_method"}


async def test_settings_page_layout_and_validation(hass: HomeAssistant) -> None:
    printer = foreign(hass)
    entry, _, _ = await _setup(hass)
    page = await reconfigure(hass, entry)
    assert page["step_id"] == "mon_settings" and not is_menu(page)
    sections = {str(k): v for k, v in page["data_schema"].schema.items()}
    assert list(sections) == ["general", "report", "reload", "disable", "notifications"]
    assert [n for n, sec in sections.items() if not sec.options["collapsed"]] == ["general"]
    flow = hass.config_entries.subentries
    bad = await flow.async_configure(page["flow_id"], mon_page(disable_reenable=True))
    assert bad["errors"] == {"base": "no_presence"}
    done = await flow.async_configure(
        page["flow_id"],
        mon_page(name="Zentrale", reload_entries=[printer.entry_id], disable_mode="blacklist",
                 disable_presence="binary_sensor.da", disable_reenable=True, mobile_enabled=False))
    assert done["reason"] == "reconfigure_successful"
    assert entry.options["reload_entries"] == [printer.entry_id] and entry.title.endswith("Zentrale")
    assert entry.options["disable_presence"] == "binary_sensor.da" and entry.options["mobile_targets"] is None


async def test_old_exclusions_become_the_blacklist_and_legacy_can_be_cleared(
    hass: HomeAssistant
) -> None:
    printer = foreign(hass)
    entry, _, _ = await _setup(
        hass, excluded=[printer.entry_id], monitor_rules=[rule([printer.entry_id])])
    page = await reconfigure(hass, entry)
    sections = {str(k): v for k, v in page["data_schema"].schema.items()}
    assert "legacy" in sections                                  # nur mit älteren Regeln
    report = {str(k): k for k in sections["report"].schema.schema}
    assert report["report_entries"].default() == [printer.entry_id]
    done = await hass.config_entries.subentries.async_configure(
        page["flow_id"], mon_page(clear_legacy_rules=True))
    assert done["reason"] == "reconfigure_successful"
    assert entry.options["monitor_rules"] is None and entry.options["excluded"] is None


# --- feste Felder: Regeln, Listen und Bereich der Meldungen ---------------------------------------


def test_settings_rules_and_list_modes() -> None:
    assert mon.settings_rules(lambda key, default=None: default) == []     # nichts gewählt
    values = {"reload_entries": ["a"], "disable_mode": "blacklist", "disable_entries": ["b"],
              "disable_presence": "binary_sensor.da", "disable_reenable": True}
    rules = mon.settings_rules(lambda key, default=None: values.get(key, default))
    assert [r["id"] for r in rules] == ["basic:reload", "basic:disable"]
    assert mon.rule_matches(rules[0], "a", "error") and not mon.rule_matches(rules[0], "x", "error")
    assert mon.rule_matches(rules[1], "x", "error") and not mon.rule_matches(rules[1], "b", "error")
    assert rules[1]["reenable"] is True and rules[1]["presence_entity"] == "binary_sensor.da"


async def test_fields_reload_only_the_whitelist(hass: HomeAssistant, monkeypatch) -> None:
    printer = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    other = foreign(hass, "Lampe", ConfigEntryState.SETUP_RETRY, "lamp_x")
    reload = AsyncMock(return_value=True)
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)
    _, ctrl, _ = await _setup(hass, reload_mode="whitelist", reload_entries=[printer.entry_id])
    await check(ctrl)
    assert [c.args[0] for c in reload.call_args_list] == [printer.entry_id] and other


async def test_fields_disable_with_a_blacklist(hass: HomeAssistant) -> None:
    printer = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    lamp = foreign(hass, "Lampe", ConfigEntryState.SETUP_RETRY, "lamp_x")
    _, ctrl, _ = await _setup(hass, disable_mode="blacklist", disable_entries=[lamp.entry_id])
    await check(ctrl)
    assert printer.disabled_by is ConfigEntryDisabler.USER and lamp.disabled_by is None
    assert ctrl.disabled == {printer.entry_id: "basic:disable"}


async def test_report_whitelist_limits_the_summary(hass: HomeAssistant) -> None:
    printer = foreign(hass, state=ConfigEntryState.SETUP_RETRY)
    lamp = foreign(hass, "Lampe", ConfigEntryState.SETUP_RETRY, "lamp_x")
    _, ctrl, push = await _setup(
        hass, report_mode="whitelist", report_entries=[printer.entry_id])
    await check(ctrl)
    text = " ".join(messages(push))
    assert "Drucker" in text and "Lampe" not in text and lamp


# --- Sammelmeldung ------------------------------------------------------------------------------------


async def test_one_summary_lists_all_faults_with_integration_names(hass: HomeAssistant) -> None:
    sun = foreign(hass, "Standort Haus", ConfigEntryState.LOADED, "sun")
    add_entities(hass, sun, ["unavailable"] * 3)
    foreign(hass, "Drucker", ConfigEntryState.SETUP_ERROR, "printer_x")
    _, ctrl, push = await _setup(hass)
    await check(ctrl)
    (message,) = messages(push)                               # eine Meldung für beide Störungen
    assert message.splitlines()[0] in ("Gestörte Integrationen (2):", "Faulty integrations (2):")
    assert "Sun: Standort Haus" in message                    # Integrationsname + Eintrag
    assert "3" in message and ("Entitäten" in message or "entities" in message)
    assert "Drucker" in message and "setup_error" in message
    assert "seit" in message or "since" in message


async def test_summary_updates_when_the_list_changes(hass: HomeAssistant) -> None:
    first = foreign(hass, "Erste", ConfigEntryState.SETUP_ERROR, "a_x")
    _, ctrl, push = await _setup(hass)
    await check(ctrl)
    foreign(hass, "Zweite", ConfigEntryState.SETUP_ERROR, "b_x")
    await check(ctrl)
    assert len(messages(push)) == 2 and "Zweite" in messages(push)[1] and "Erste" in messages(push)[1]
    first.mock_state(hass, ConfigEntryState.LOADED)
    await ctrl.async_check()
    assert len(messages(push)) == 3 and "Erste" not in messages(push)[2]


async def test_summary_is_bundled_by_the_delay(hass: HomeAssistant) -> None:
    foreign(hass, state=ConfigEntryState.SETUP_ERROR)
    _, ctrl, push = await _setup(hass, summary_minutes=10)
    await check(ctrl)
    assert messages(push) == [] and ctrl.summary["pending"]       # wartet auf die Bündelungszeit
    ctrl.summary["pending"] = (dt_util.utcnow() - timedelta(minutes=11)).isoformat()
    await ctrl.async_check()
    assert len(messages(push)) == 1 and ctrl.summary["pending"] is None


async def test_unavailable_is_not_reported_by_default_but_by_a_rule(hass: HomeAssistant) -> None:
    lamp = foreign(hass, "Lampe", ConfigEntryState.LOADED, "hue_x")
    add_entities(hass, lamp, ["unavailable", "unavailable"])
    hub = foreign(hass, "Zigbee2MQTT", ConfigEntryState.LOADED, "mqtt_x")
    add_entities(hass, hub, ["unavailable", "unavailable"])
    foreign(hass, "Kaputt", ConfigEntryState.SETUP_ERROR, "broken_x")
    _, ctrl, push = await _setup(
        hass, notify_unavailable=False, monitor_rules=[rule([hub.entry_id], action="none")])
    await check(ctrl)
    (message,) = messages(push)
    assert "Zigbee2MQTT" in message and "Kaputt" in message and "Lampe" not in message
    assert ctrl.faults[lamp.entry_id]["reported"] is False


async def test_older_single_switch_still_applies(hass: HomeAssistant) -> None:
    foreign(hass, state=ConfigEntryState.SETUP_ERROR)
    _, ctrl, push = await _setup(hass, notify_errors=None, notify_unavailable=None, notify_all=False)
    await check(ctrl)
    assert messages(push) == []
    _, ctrl2, push2 = await _setup(hass, notify_errors=None, notify_unavailable=None, notify_all=True)
    await check(ctrl2)
    assert len(messages(push2)) == 1


async def test_tts_speaks_only_the_count(hass: HomeAssistant) -> None:
    speak = async_mock_service(hass, "tts", "speak")
    foreign(hass, "A", ConfigEntryState.SETUP_ERROR, "a_x")
    foreign(hass, "B", ConfigEntryState.SETUP_ERROR, "b_x")
    _, ctrl, _ = await _setup(
        hass, mobile_enabled=False, tts_enabled=True, tts_entity="tts.cloud",
        tts_player="media_player.kitchen")
    await check(ctrl)
    (call,) = speak
    assert call.data["message"] in ("2 Integrationen gestört.", "2 integrations faulty.")


async def test_old_single_notifications_are_cleared_after_the_update(
    hass: HomeAssistant, hass_storage
) -> None:
    from custom_components.ha_housekeeper.integration_monitor import STORE_VERSION
    async_mock_service(hass, "notify", "mobile_app_phone")
    dismiss = async_mock_service(hass, "persistent_notification", "dismiss")
    entry = make_entry(domain=DOMAIN, title="Monitor", data={**BASE, "persistent_enabled": True})
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": STORE_VERSION, "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"enabled": True, "disabled": {},
                 "faults": {"abc": {"kind": "error", "acted": True, "notified": True}}}}
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    ids = {c.data["notification_id"] for c in dismiss}
    assert any(i.endswith("_abc") for i in ids) and any(i.endswith("_abc_ok") for i in ids)
    ctrl = hass.data[DOMAIN][entry.entry_id]
    assert ctrl.faults["abc"]["reported"] is True            # `notified` zu `reported` übernommen


# --- Assistent „Störungen prüfen“ -----------------------------------------------------------------

from homeassistant.helpers import issue_registry as ir  # noqa: E402

from custom_components.ha_housekeeper.repairs import async_create_fix_flow  # noqa: E402


def review_issue(hass, ctrl):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{ctrl.entry.entry_id}_monitor_review")


class Review:
    """Das Reparaturformular, bedient über den echten Reparatur-Manager von Home Assistant."""

    def __init__(self, manager, form):
        self.manager = manager
        self.form = form

    async def submit(self, data):
        return await self.manager.async_configure(self.form["flow_id"], data)


async def open_review(hass, ctrl):
    """Das Formular des Reparaturhinweises öffnen, genau wie es die Reparaturen tun.

    Der Start übergibt Daten (`issue_id`); das ist kein abgesendetes Formular.
    """
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "repairs", {})
    issue = review_issue(hass, ctrl)
    manager = hass.data["repairs"]["flow_manager"]
    form = await manager.async_init(
        DOMAIN, context={"issue_id": issue.issue_id}, data={"issue_id": issue.issue_id}
    )
    return Review(manager, form), form


def pick(form, **choices):
    """Antworten für das Formular: je Integrationsname eine Wahl, alles andere „weiter melden“."""
    answers = {}
    for key in form["data_schema"].schema:
        answers[str(key)] = next(
            (value for name, value in choices.items() if name in str(key)), "report")
    return answers


async def two_faults(hass, **over):
    printer = foreign(hass, "Drucker", ConfigEntryState.SETUP_ERROR, "printer_x")
    lamp = foreign(hass, "Lampe", ConfigEntryState.SETUP_RETRY, "lamp_x")
    entry, ctrl, push = await _setup(hass, **over)
    await check(ctrl)
    return printer, lamp, ctrl, push


async def test_pending_faults_create_a_fixable_issue_and_a_hint(hass: HomeAssistant) -> None:
    printer, lamp, ctrl, push = await two_faults(hass)
    issue = review_issue(hass, ctrl)
    assert issue.is_fixable and issue.translation_placeholders["count"] == "2"
    assert len(ctrl.pending_review()) == 2
    (message,) = messages(push)
    assert "2 faults are waiting for your review" in message
    assert push[0].data["data"]["url"] == "/config/repairs"


async def test_review_marks_known_and_reports_the_rest(hass: HomeAssistant) -> None:
    printer, lamp, ctrl, push = await two_faults(hass)
    flow, form = await open_review(hass, ctrl)
    assert form["type"] is FlowResultType.FORM and form["step_id"] == "review"
    assert form["description_placeholders"]["count"] == "2"
    assert "Drucker" in form["description_placeholders"]["faults"]
    assert "Lampe" in form["description_placeholders"]["faults"]
    assert len(form["data_schema"].schema) == 2
    done = await flow.submit(pick(form, Drucker="known"))
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert ctrl.known == {printer.entry_id: {"kind": "error", "until_recovery": False}}
    assert ctrl.known_titles == ["Drucker"]
    assert review_issue(hass, ctrl) is None                 # alles eingeschätzt, nichts wird mehr gefragt
    last = messages(push)[-1]
    assert "Lampe" in last and "Drucker" not in last and "+ 1 marked as normal" in last
    assert "waiting for your review" not in last
    assert len(ctrl.faults) == 2                             # die Störung besteht weiter, wird nur nicht gemeldet


async def test_known_faults_are_silent_and_the_list_clears_when_all_are_known(hass: HomeAssistant) -> None:
    printer, lamp, ctrl, push = await two_faults(hass)
    flow, form = await open_review(hass, ctrl)
    await flow.submit(pick(form, Drucker="known", Lampe="until_recovery"))
    assert push[-1].data["message"] == "clear_notification"  # nichts mehr zu melden
    count = len(push)
    await ctrl.async_check()
    assert len(push) == count and ctrl.summary["sent"] == []


async def test_form_has_one_dropdown_per_fault_with_the_fault_as_label(hass: HomeAssistant) -> None:
    printer, lamp, ctrl, push = await two_faults(hass)
    flow, form = await open_review(hass, ctrl)
    keys = [str(k) for k in form["data_schema"].schema]
    assert len(keys) == 2 and "Lampe" in keys[0] and "Drucker" in keys[1]     # sortiert, je Störung eine Zeile
    assert "setup_retry" in keys[0] and "setup_error" in keys[1]
    assert all(k.default() == "report" for k in form["data_schema"].schema)    # vorbelegt: weiter melden
    desc = form["description_placeholders"]["faults"]
    assert desc.startswith("1. ") and "Drucker" in desc and "Lampe" in desc
    # eine Antwort je Störung, es gibt keinen Konflikt mehr
    done = await flow.submit({keys[1]: "known", keys[0]: "until_recovery"})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert ctrl.known[printer.entry_id]["until_recovery"] is False
    assert ctrl.known[lamp.entry_id]["until_recovery"] is True


async def test_identical_rows_get_distinct_field_names(hass: HomeAssistant) -> None:
    from custom_components.ha_housekeeper.repairs import MonitorReviewFlow

    foreign(hass, "Drucker", ConfigEntryState.SETUP_ERROR, "printer_x")
    foreign(hass, "Drucker", ConfigEntryState.SETUP_ERROR, "printer_x")
    _, ctrl, _ = await _setup(hass)
    await check(ctrl)
    flow = MonitorReviewFlow(ctrl)
    flow.hass = hass
    form = await flow.async_step_init({"issue_id": "x"})
    keys = [str(k) for k in form["data_schema"].schema]
    assert len(keys) == 2 and len(set(keys)) == 2 and keys[1].endswith("(2)")
    await flow.async_step_review(pick(form, **{"(2)": "known"}))
    assert len(ctrl.known) == 1                                   # nur die zweite Zeile war „normal“


async def test_until_recovery_is_asked_again_after_it_worked(hass: HomeAssistant) -> None:
    printer, lamp, ctrl, push = await two_faults(hass)
    flow, form = await open_review(hass, ctrl)
    await flow.submit(pick(form, Drucker="until_recovery", Lampe="until_recovery"))
    assert ctrl.known[printer.entry_id]["until_recovery"] is True
    printer.mock_state(hass, ConfigEntryState.LOADED)       # läuft wieder
    await ctrl.async_check()
    assert printer.entry_id not in ctrl.known and lamp.entry_id in ctrl.known
    printer.mock_state(hass, ConfigEntryState.SETUP_ERROR)  # fällt erneut aus
    await check(ctrl)
    assert "Drucker" in messages(push)[-1]
    assert review_issue(hass, ctrl) is not None


async def test_permanent_mark_survives_a_recovery(hass: HomeAssistant) -> None:
    printer, lamp, ctrl, push = await two_faults(hass)
    flow, form = await open_review(hass, ctrl)
    await flow.submit(pick(form, Drucker="known"))
    printer.mock_state(hass, ConfigEntryState.LOADED)
    await ctrl.async_check()
    printer.mock_state(hass, ConfigEntryState.SETUP_ERROR)
    await check(ctrl)
    assert printer.entry_id in ctrl.known and "Drucker" not in messages(push)[-1]


async def test_a_different_kind_of_fault_is_new(hass: HomeAssistant) -> None:
    printer, lamp, ctrl, push = await two_faults(hass)
    flow, form = await open_review(hass, ctrl)
    await flow.submit(pick(form, Drucker="known"))
    printer.mock_state(hass, ConfigEntryState.LOADED)       # kein Fehler mehr, aber alle Entitäten weg
    add_entities(hass, printer, ["unavailable", "unavailable"])
    await check(ctrl)
    assert printer.entry_id not in ctrl.known              # andere Art: gilt als neu
    assert ctrl.faults[printer.entry_id]["kind"] == mon.KIND_UNAVAILABLE
    assert printer.entry_id in ctrl.pending_review()


async def test_reset_button_clears_the_ratings(hass: HomeAssistant) -> None:
    printer, lamp, ctrl, push = await two_faults(hass)
    flow, form = await open_review(hass, ctrl)
    await flow.submit(pick(form, Drucker="known"))
    registry = er.async_get(hass)
    button = next(e.entity_id for e in registry.entities.values()
                  if e.platform == DOMAIN and e.translation_key == "monitor_reset_known")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert ctrl.known == {} and len(ctrl.pending_review()) == 2
    assert review_issue(hass, ctrl) is not None
    assert "Drucker" in messages(push)[-1]


async def test_known_survives_a_restart_and_shows_in_the_sensor(hass: HomeAssistant) -> None:
    printer, lamp, ctrl, push = await two_faults(hass)
    flow, form = await open_review(hass, ctrl)
    await flow.submit(pick(form, Drucker="known"))
    await hass.async_block_till_done()
    sensor = next(e.entity_id for e in er.async_get(hass).entities.values()
                  if e.platform == DOMAIN and e.translation_key == "monitor_faulty")
    assert hass.states.get(sensor).attributes["known"] == ["Drucker"]
    await hass.config_entries.async_reload(ctrl.entry.hub_entry_id)
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][ctrl.entry.entry_id].known == ctrl.known


async def test_opening_the_form_does_not_answer_it(hass: HomeAssistant) -> None:
    """Regression: der Start des Reparaturablaufs übergibt Daten und darf nichts markieren."""
    printer, lamp, ctrl, push = await two_faults(hass)
    review, form = await open_review(hass, ctrl)
    assert form["type"] is FlowResultType.FORM
    assert len(ctrl.pending_review()) == 2 and ctrl.known == {}
    assert review_issue(hass, ctrl) is not None
    assert [f.get("reviewed") for f in ctrl.faults.values()] == [None, None]
    assert len(form["data_schema"].schema) == 2


async def test_form_without_pending_faults_aborts(hass: HomeAssistant) -> None:
    from custom_components.ha_housekeeper.repairs import MonitorReviewFlow

    printer, lamp, ctrl, push = await two_faults(hass)
    flow, form = await open_review(hass, ctrl)
    await flow.submit(pick(form, Drucker="known", Lampe="known"))
    late = MonitorReviewFlow(ctrl)
    late.hass = hass
    again = await late.async_step_init({"issue_id": "x"})
    assert again["type"] is FlowResultType.ABORT and again["reason"] == "nothing_to_review"
    orphan = await async_create_fix_flow(hass, "x", {"entry_id": "gibt-es-nicht"})
    orphan.hass = hass
    assert (await orphan.async_step_init())["type"] is FlowResultType.ABORT


async def test_wrong_review_marks_from_the_old_bug_are_reset_once(hass: HomeAssistant) -> None:
    printer, lamp, ctrl, push = await two_faults(hass)
    for fault in ctrl.faults.values():          # so sah der Speicher nach dem Fehler aus
        fault["reviewed"] = True
    await ctrl._store.async_save(
        {"enabled": True, "faults": ctrl.faults, "known": {}, "disabled": {}, "summary": ctrl.summary}
    )
    await hass.config_entries.async_reload(ctrl.entry.hub_entry_id)
    await hass.async_block_till_done()
    ctrl2 = hass.data[DOMAIN][ctrl.entry.entry_id]
    assert len(ctrl2.pending_review()) == 2     # werden wieder gefragt
    await ctrl2.async_check()
    assert review_issue(hass, ctrl2) is not None
    # eine echte Antwort bleibt danach erhalten
    flow, form = await open_review(hass, ctrl2)
    await flow.submit(pick(form))
    await hass.config_entries.async_reload(ctrl.entry.hub_entry_id)
    await hass.async_block_till_done()
    ctrl3 = hass.data[DOMAIN][ctrl.entry.entry_id]
    assert ctrl3.pending_review() == []


async def test_old_faults_without_details_are_refreshed(hass: HomeAssistant) -> None:
    printer = foreign(hass, "Drucker", ConfigEntryState.LOADED, "printer_x")
    add_entities(hass, printer, ["unavailable", "unavailable"])
    _, ctrl, push = await _setup(hass)
    ctrl.faults[printer.entry_id] = {"kind": "unavailable", "acted": True, "reported": True}
    await check(ctrl)
    fault = ctrl.faults[printer.entry_id]
    assert fault["entities"] == 2 and fault["since"] and fault["state"] == "loaded"
    line = await ctrl._fault_line(printer.entry_id, fault)
    assert "all 2 entities" in line and "?" not in line


async def test_older_faults_show_the_date(hass: HomeAssistant) -> None:
    printer = foreign(hass, "Drucker", ConfigEntryState.SETUP_ERROR, "printer_x")
    _, ctrl, push = await _setup(hass)
    old = (dt_util.utcnow() - timedelta(days=2)).isoformat()
    fault = {"kind": "error", "state": "setup_error", "since": old}
    assert "/" in await ctrl._fault_line(printer.entry_id, fault)      # englisch: MM/TT hh:mm
    today = {**fault, "since": dt_util.utcnow().isoformat()}
    assert "/" not in await ctrl._fault_line(printer.entry_id, today)


def test_fixable_issue_has_a_fix_flow_and_no_description() -> None:
    """Hassfest erlaubt bei behebbaren Hinweisen nur `fix_flow`, keine `description`."""
    import json
    from pathlib import Path

    base = Path(__file__).parent.parent / "custom_components" / "ha_housekeeper"
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        issue = json.loads((base / name).read_text(encoding="utf-8"))["issues"]["monitor_review"]
        assert "fix_flow" in issue and "description" not in issue, name
        assert {"title", "description"} <= set(issue["fix_flow"]["step"]["review"])
        assert "init" not in issue["fix_flow"]["step"], name
        assert {"nothing_to_review"} <= set(issue["fix_flow"]["abort"])
