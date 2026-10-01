"""Tests für die Funktion Türwächter."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import is_menu, menu_options, sectioned
from custom_components.ha_housekeeper.const import DOMAIN

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
    entry = MockConfigEntry(domain=DOMAIN, title="Door", data={**BASE, **over})
    entry.add_to_hass(hass)
    hass.states.async_set(LOCK, lock_state)
    hass.states.async_set(CONTACT, contact_state)
    hass.states.async_set(PERSON, "not_home")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _advance(hass: HomeAssistant, **delta) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(**delta))
    await hass.async_block_till_done()


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "door_guard"}
    )
    assert result["step_id"] == "door_guard"
    data = {k: v for k, v in BASE.items() if k not in ("function_type", "rules")}
    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"], sectioned({k: v for k, v in data.items() if k != "contact"})
    )
    assert bad["errors"] == {"base": "alert_needs_contact"}
    ok = await hass.config_entries.flow.async_configure(result["flow_id"], sectioned(data))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["function_type"] == "door_guard"
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
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert is_menu(result)
    assert "edit_rule" not in menu_options(result)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_rule"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"action": "unlock", "trigger": "state"}
    )
    assert result["step_id"] == "rule_state"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entity_id": PERSON, "to_state": "home", "for_minutes": 0}
    )
    assert is_menu(result)
    assert "edit_rule" in menu_options(result)
    assert len(entry.options["rules"]) == 1
    rule_id = entry.options["rules"][0]["id"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "delete_rule"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"rule": rule_id}
    )
    assert entry.options["rules"] == []


async def test_options_flow_door_closed_needs_contact(hass: HomeAssistant) -> None:
    entry = await _setup(hass, contact=None)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_rule"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"action": "lock", "trigger": "door_closed"}
    )
    assert result["errors"] == {"base": "no_contact"}
