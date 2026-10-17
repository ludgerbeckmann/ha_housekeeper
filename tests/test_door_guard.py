"""Tests für die Funktion Türwächter."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import is_menu, menu_options, sectioned, make_entry, reconfigure, new_instance
from custom_components.ha_housekeeper.const import DOMAIN
from custom_components.ha_housekeeper.door_guard import (
    entity_on,
    evaluate_conditions,
    presence_met,
)

LOCK = "lock.front_door"
CONTACT = "binary_sensor.front_door_contact"
PERSON = "person.ludger"
BASE = {
    "function_type": "door_guard",
    "name": "Door",
    "lock": LOCK,
    "contact": CONTACT,
    "block_action": "notify",
    "retry_minutes": 10,
    "open_alert_minutes": 10,
    "open_alert_repeat_minutes": 0,
    "verify_seconds": 0,
    "manual_override": "ignore",
    "manual_pause_minutes": 60,
    "mobile_enabled": True,
    "mobile_targets": ["mobile_app_phone"],
    "tts_enabled": False,
    "persistent_enabled": False,
    "rules": [],
}
OPEN_TOO_LONG = "binary_sensor.door_door_open_too_long"


async def _setup(hass: HomeAssistant, lock_state="unlocked", contact_state="off", **over):
    entry = make_entry(domain=DOMAIN, title="Door", data={**BASE, **over})
    entry.add_to_hass(hass)
    hass.states.async_set(LOCK, lock_state)
    hass.states.async_set(CONTACT, contact_state)
    hass.states.async_set(PERSON, "not_home")
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry


async def _advance(hass: HomeAssistant, **delta) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(**delta))
    await hass.async_block_till_done()


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "door_guard")
    assert result["step_id"] == "new_door_guard"
    data = {k: v for k, v in BASE.items() if k not in ("function_type", "rules")}
    bad = await hass.config_entries.subentries.async_configure(
        result["flow_id"], sectioned({k: v for k, v in data.items() if k != "contact"})
    )
    assert bad["errors"] == {"base": "alert_needs_contact"}
    ok = await hass.config_entries.subentries.async_configure(result["flow_id"], sectioned(data))
    assert ok["type"] is FlowResultType.CREATE_ENTRY

    assert ok["data"]["rules"] == []


async def test_state_rule_unlocks(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "unlock")
    rule = {"id": "r1", "action": "unlock", "trigger": "state",
            "entity_id": PERSON, "to_state": "home", "for_minutes": 0}
    await _setup(hass, lock_state="locked", rules=[rule])
    hass.states.async_set(PERSON, "home")
    await hass.async_block_till_done()
    assert len(calls) == 1 and calls[0].data["entity_id"] == LOCK
    last = hass.states.get("sensor.door_last_action")
    assert last.attributes["action"] == "unlock" and last.attributes["result"] == "ok"


async def test_state_rule_for_minutes_cancelled(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    rule = {"id": "r1", "action": "lock", "trigger": "state",
            "entity_id": PERSON, "to_state": "not_home", "for_minutes": 5}
    await _setup(hass, rules=[rule])
    hass.states.async_set(PERSON, "home")
    hass.states.async_set(PERSON, "not_home")
    hass.states.async_set(PERSON, "home")   # Timer wird abgebrochen
    await hass.async_block_till_done()
    await _advance(hass, minutes=6)
    assert calls == []
    hass.states.async_set(PERSON, "not_home")
    await hass.async_block_till_done()
    await _advance(hass, minutes=6)
    assert len(calls) == 1


async def test_time_rule(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    rule = {"id": "r1", "action": "lock", "trigger": "time",
            "time": "22:00:00", "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}
    await _setup(hass, rules=[rule])
    fire = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
    async_fire_time_changed(hass, fire + timedelta(days=1))
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_lock_blocked_when_open(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    entry = await _setup(hass, contact_state="on")
    ctrl = hass.data[DOMAIN][entry.entry_id]
    await ctrl.async_run_action("lock", "test")
    assert calls == [] and len(notify) == 1
    assert hass.states.get("sensor.door_last_action").attributes["result"] == "blocked"


async def test_lock_blocked_contact_unavailable(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    entry = await _setup(hass, contact_state="unavailable")
    await hass.data[DOMAIN][entry.entry_id].async_run_action("lock", "test")
    assert calls == []


async def test_lock_retry_after_close(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    async_mock_service(hass, "notify", "mobile_app_phone")
    entry = await _setup(hass, contact_state="on", block_action="retry")
    await hass.data[DOMAIN][entry.entry_id].async_run_action("lock", "test")
    assert calls == []
    hass.states.async_set(CONTACT, "off")
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_door_closed_rule(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    rule = {"id": "r1", "action": "lock", "trigger": "door_closed", "delay_seconds": 30}
    await _setup(hass, contact_state="on", rules=[rule])
    hass.states.async_set(CONTACT, "off")
    await hass.async_block_till_done()
    assert calls == []
    await _advance(hass, seconds=31)
    assert len(calls) == 1


async def test_door_closed_rule_cancelled_on_reopen(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    rule = {"id": "r1", "action": "lock", "trigger": "door_closed", "delay_seconds": 30}
    await _setup(hass, contact_state="on", rules=[rule])
    hass.states.async_set(CONTACT, "off")
    hass.states.async_set(CONTACT, "on")
    await hass.async_block_till_done()
    await _advance(hass, seconds=31)
    assert calls == []


async def test_open_too_long(hass: HomeAssistant) -> None:
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    await _setup(hass)
    hass.states.async_set(CONTACT, "on")
    await hass.async_block_till_done()
    assert hass.states.get(OPEN_TOO_LONG).state == "off"
    await _advance(hass, minutes=11)
    assert hass.states.get(OPEN_TOO_LONG).state == "on"
    assert len(notify) == 1 and "10" in notify[0].data["message"]
    hass.states.async_set(CONTACT, "off")
    await hass.async_block_till_done()
    assert hass.states.get(OPEN_TOO_LONG).state == "off"
    assert notify[-1].data["message"] == "clear_notification"


async def test_manual_operation_pauses(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "unlock")
    entry = await _setup(hass, lock_state="unlocked", manual_override="pause")
    hass.states.async_set(LOCK, "locked")     # von außen bedient
    await hass.async_block_till_done()
    assert hass.states.get("switch.door_automation").attributes["paused_until"]
    ctrl = hass.data[DOMAIN][entry.entry_id]
    await ctrl.async_run_action("unlock", "test")
    assert calls == []                        # pausiert
    await _advance(hass, minutes=61)
    assert hass.states.get("switch.door_automation").attributes["paused_until"] is None
    await ctrl.async_run_action("unlock", "test")
    assert len(calls) == 1


async def test_manual_operation_ignored(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    entry = await _setup(hass, lock_state="unlocked")
    hass.states.async_set(LOCK, "locked")
    hass.states.async_set(LOCK, "unlocked")
    await hass.async_block_till_done()
    await hass.data[DOMAIN][entry.entry_id].async_run_action("lock", "test")
    assert len(calls) == 1


async def test_own_action_not_manual(hass: HomeAssistant) -> None:
    async_mock_service(hass, "lock", "lock")
    entry = await _setup(hass, manual_override="pause")
    await hass.data[DOMAIN][entry.entry_id].async_run_action("lock", "test")
    hass.states.async_set(LOCK, "locked")     # Folge unseres Befehls
    await hass.async_block_till_done()
    assert hass.states.get("switch.door_automation").attributes["paused_until"] is None


async def test_automation_switch_off(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    entry = await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.door_automation"}, blocking=True
    )
    await hass.data[DOMAIN][entry.entry_id].async_run_action("lock", "test")
    assert calls == []
    assert hass.states.get("switch.door_automation").state == "off"


async def test_verify_failure_notifies(hass: HomeAssistant) -> None:
    async_mock_service(hass, "lock", "lock")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    entry = await _setup(hass, verify_seconds=30)
    await hass.data[DOMAIN][entry.entry_id].async_run_action("lock", "test")
    await _advance(hass, seconds=31)      # Schloss bleibt "unlocked"
    assert len(notify) == 1 and "unlocked" in notify[0].data["message"]
    assert hass.states.get("sensor.door_last_action").attributes["result"] == "failed"


async def test_options_flow_rules(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await reconfigure(hass, entry)
    assert is_menu(result)
    assert "edit_rule" not in menu_options(result)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "add_rule"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"action": "unlock", "trigger": "state"}
    )
    assert result["step_id"] == "rule_state"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_id": PERSON, "to_state": "home", "for_minutes": 0}
    )
    assert result["step_id"] == "rule_conditions"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert is_menu(result)
    assert "edit_rule" in menu_options(result)
    assert len(entry.options["rules"]) == 1
    rule_id = entry.options["rules"][0]["id"]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "delete_rule"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"rule": rule_id}
    )
    assert entry.options["rules"] == []


async def test_options_flow_door_closed_needs_contact(hass: HomeAssistant) -> None:
    entry = await _setup(hass, contact=None)
    result = await reconfigure(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "add_rule"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"action": "lock", "trigger": "door_closed"}
    )
    assert result["errors"] == {"base": "no_contact"}


def _st(entity_id: str, state: str):
    from homeassistant.core import State

    return State(entity_id, state)


def test_entity_on() -> None:
    assert entity_on(None) is None
    assert entity_on(_st("binary_sensor.x", "unavailable")) is None
    assert entity_on(_st("binary_sensor.x", "on")) is True
    assert entity_on(_st("input_boolean.x", "off")) is False
    assert entity_on(_st("person.a", "home")) is True
    assert entity_on(_st("person.a", "not_home")) is False
    assert entity_on(_st("zone.home", "2")) is True
    assert entity_on(_st("zone.home", "0")) is False
    assert entity_on(_st("zone.home", "abc")) is None


def test_presence_met() -> None:
    assert presence_met("all_away", [False, False])
    assert not presence_met("all_away", [False, None])
    assert not presence_met("all_away", [False, True])
    assert not presence_met("all_away", [])
    assert presence_met("any_home", [False, True])
    assert not presence_met("any_home", [None, False])


def test_evaluate_conditions() -> None:
    assert evaluate_conditions({}, "unlock", [], {}) is None
    rule = {"presence": "someone_home"}
    assert evaluate_conditions(rule, "unlock", [True, False], {}) is None
    assert evaluate_conditions(rule, "unlock", [False, False], {}) == "presence:away"
    assert evaluate_conditions(rule, "unlock", [None, False], {}) == "presence:unclear"
    assert evaluate_conditions(rule, "unlock", [], {}) == "presence:none"
    away = {"presence": "all_away"}
    assert evaluate_conditions(away, "lock", [False, False], {}) is None
    assert evaluate_conditions(away, "lock", [False, True], {}) == "presence:home"
    assert evaluate_conditions(away, "lock", [False, None], {}) == "presence:unclear"
    only = {"only_if_on": ["binary_sensor.a", "binary_sensor.b"]}
    assert evaluate_conditions(only, "unlock", [], {"binary_sensor.a": True, "binary_sensor.b": True}) is None
    assert evaluate_conditions(only, "unlock", [], {"binary_sensor.a": True, "binary_sensor.b": False}) == "only_if:binary_sensor.b"
    assert evaluate_conditions(only, "unlock", [], {"binary_sensor.a": True, "binary_sensor.b": None}) == "only_if:binary_sensor.b"
    assert evaluate_conditions(only, "lock", [], {"binary_sensor.a": True, "binary_sensor.b": None}) is None
    skip = {"skip_if_on": ["binary_sensor.a"]}
    assert evaluate_conditions(skip, "unlock", [], {"binary_sensor.a": True}) == "skip_if:binary_sensor.a"
    assert evaluate_conditions(skip, "unlock", [], {"binary_sensor.a": None}) == "skip_if:binary_sensor.a"
    assert evaluate_conditions(skip, "lock", [], {"binary_sensor.a": None}) is None


async def test_time_rule_skipped_by_condition(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "unlock")
    rule = {"id": "r1", "action": "unlock", "trigger": "time", "time": "06:30:00",
            "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "presence": "someone_home", "only_if_on": [], "skip_if_on": ["binary_sensor.holiday"]}
    await _setup(hass, lock_state="locked", rules=[rule], presence_entities=[PERSON])
    hass.states.async_set("binary_sensor.holiday", "on")
    hass.states.async_set(PERSON, "home")
    fire = dt_util.now().replace(hour=6, minute=30, second=0, microsecond=0)
    async_fire_time_changed(hass, fire + timedelta(days=1))
    await hass.async_block_till_done()
    assert calls == []
    last = hass.states.get("sensor.door_last_action")
    assert last.attributes["result"] == "skipped"
    hass.states.async_set("binary_sensor.holiday", "off")
    async_fire_time_changed(hass, fire + timedelta(days=2))
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_presence_rule_all_away(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    p2 = "person.partner"
    rule = {"id": "r1", "action": "lock", "trigger": "presence",
            "presence_mode": "all_away", "for_minutes": 3}
    entry = make_entry(domain=DOMAIN, title="Door",
                       data={**BASE, "rules": [rule], "presence_entities": [PERSON, p2]})
    entry.add_to_hass(hass)
    hass.states.async_set(LOCK, "unlocked")
    hass.states.async_set(CONTACT, "off")
    hass.states.async_set(PERSON, "home")
    hass.states.async_set(p2, "home")
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()

    hass.states.async_set(PERSON, "not_home")
    await hass.async_block_till_done()
    await _advance(hass, minutes=4)
    assert calls == []                      # eine Person ist noch da
    hass.states.async_set(p2, "not_home")
    await hass.async_block_till_done()
    hass.states.async_set(p2, "home")       # kommt zurück: abgebrochen
    await hass.async_block_till_done()
    await _advance(hass, minutes=4)
    assert calls == []
    hass.states.async_set(p2, "not_home")
    await hass.async_block_till_done()
    await _advance(hass, minutes=4)
    assert len(calls) == 1


async def test_presence_rule_unclear_and_no_catch_up(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    rule = {"id": "r1", "action": "lock", "trigger": "presence",
            "presence_mode": "all_away", "for_minutes": 0}
    # Beim Start sind schon alle weg: kein Nachholen
    await _setup(hass, rules=[rule], presence_entities=[PERSON])
    await hass.async_block_till_done()
    assert calls == []
    hass.states.async_set(PERSON, "unavailable")
    await hass.async_block_till_done()
    assert calls == []


async def test_options_flow_presence_rule(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await reconfigure(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "add_rule"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"action": "lock", "trigger": "presence"}
    )
    assert result["errors"] == {"base": "no_presence_entities"}


async def test_condition_needs_presence_entities(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await reconfigure(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "add_rule"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"action": "unlock", "trigger": "state"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_id": PERSON, "to_state": "home", "for_minutes": 0}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"presence": "someone_home"}
    )
    assert result["errors"] == {"base": "no_presence_entities"}
