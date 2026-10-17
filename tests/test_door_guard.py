"""Tests für die Funktion Türwächter."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import is_menu, make_entry, reconfigure, new_instance
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


def dg_page(**fields):
    """Eingaben der Konfigurationsseite: flache Felder auf die Abschnitte verteilen."""
    keys = {
        "door": ("name", "lock", "contact", "presence_entities", "workday_sensor"),
        "unlock": ("unlock_time_workday", "unlock_time_free", "unlock_only_when_home",
                   "unlock_on_arrival", "unlock_only_if_on", "unlock_skip_if_on"),
        "lock": ("lock_time", "lock_when_away", "lock_away_minutes", "lock_closed_seconds",
                 "lock_only_if_on", "lock_skip_if_on"),
        "checks": ("block_action", "retry_minutes", "open_alert_minutes", "open_alert_repeat_minutes",
                   "verify_seconds", "manual_override", "manual_pause_minutes"),
        "legacy": ("clear_legacy_rules",),
    }
    sections = {name: {} for name in ("door", "unlock", "lock", "checks", "notifications")}
    for key, value in fields.items():
        for name, names in keys.items():
            if key in names:
                sections.setdefault(name, {})[key] = value
                break
        else:
            sections["notifications"][key] = value
    return sections


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "door_guard")
    assert result["step_id"] == "new_door_guard"
    flow = hass.config_entries.subentries
    data = {k: v for k, v in BASE.items() if k not in ("function_type", "rules")}
    bad = await flow.async_configure(
        result["flow_id"], dg_page(**{k: v for k, v in data.items() if k != "contact"}))
    assert bad["errors"] == {"base": "alert_needs_contact"}
    bad = await flow.async_configure(
        result["flow_id"], dg_page(**{**data, "lock_when_away": True}))
    assert bad["errors"] == {"base": "no_presence_entities"}
    bad = await flow.async_configure(
        result["flow_id"], dg_page(**{**data, "lock_when_away": False, "unlock_time_free": "08:30:00"}))
    assert bad["errors"] == {"base": "no_workday_sensor"}
    no_contact = {k: v for k, v in data.items() if k != "contact"}
    bad = await flow.async_configure(
        result["flow_id"], dg_page(**{**no_contact, "open_alert_minutes": 0, "lock_when_away": False,
                                      "lock_closed_seconds": 20}))
    assert bad["errors"] == {"base": "no_contact"}
    ok = await flow.async_configure(result["flow_id"], dg_page(**data, lock_when_away=False))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert "rules" not in ok["data"] and ok["data"]["lock"] == LOCK


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


# --- Grundeinstellungen zum Auf- und Abschließen ------------------------------------------------------------


def test_settings_rules() -> None:
    from custom_components.ha_housekeeper.door_guard import settings_rules

    values = {"workday_sensor": "binary_sensor.workday", "unlock_time_workday": "06:30:00",
              "unlock_time_free": "08:30:00", "unlock_only_when_home": True, "unlock_on_arrival": True,
              "unlock_skip_if_on": ["input_boolean.vacation"], "lock_time": "22:30:00",
              "lock_when_away": True, "lock_away_minutes": 3, "lock_closed_seconds": 20,
              "lock_only_if_on": ["binary_sensor.guest"]}
    get = lambda key, default=None: values.get(key, default)  # noqa: E731
    rules = {r["id"]: r for r in settings_rules(get)}
    assert set(rules) == {"basic:unlock_workday", "basic:unlock_free", "basic:unlock_arrival",
                          "basic:lock_time", "basic:lock_away", "basic:lock_closed"}
    work = rules["basic:unlock_workday"]
    assert work["action"] == "unlock" and work["time"] == "06:30:00" and work["presence"] == "someone_home"
    assert work["only_if_on"] == ["binary_sensor.workday"] and work["skip_if_on"] == ["input_boolean.vacation"]
    free = rules["basic:unlock_free"]
    assert free["skip_if_on"] == ["binary_sensor.workday", "input_boolean.vacation"] and free["only_if_on"] == []
    arrival = rules["basic:unlock_arrival"]
    assert arrival["trigger"] == "presence" and arrival["presence_mode"] == "any_home"
    away = rules["basic:lock_away"]
    assert away["action"] == "lock" and away["presence_mode"] == "all_away" and away["for_minutes"] == 3
    assert rules["basic:lock_closed"]["delay_seconds"] == 20
    assert rules["basic:lock_time"]["only_if_on"] == ["binary_sensor.guest"]
    # ohne Arbeitstag-Sensor gilt die Uhrzeit für Arbeitstage jeden Tag, die für freie Tage entfällt
    values.update({"workday_sensor": None})
    rules = {r["id"]: r for r in settings_rules(get)}
    assert rules["basic:unlock_workday"]["only_if_on"] == [] and "basic:unlock_free" not in rules
    assert settings_rules(lambda key, default=None: default) == []


async def test_workday_and_free_day_unlock_times(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "unlock")
    await _setup(hass, lock_state="locked", workday_sensor="binary_sensor.workday",
                 unlock_time_workday="06:30:00", unlock_time_free="08:30:00",
                 unlock_only_when_home=True, presence_entities=[PERSON])
    hass.states.async_set(PERSON, "home")
    fire = lambda h, m, d: dt_util.now().replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=d)  # noqa: E731
    hass.states.async_set("binary_sensor.workday", "on")
    async_fire_time_changed(hass, fire(6, 30, 1))
    await hass.async_block_till_done()
    assert len(calls) == 1                                  # Arbeitstag: 06:30 gilt
    async_fire_time_changed(hass, fire(8, 30, 1))
    await hass.async_block_till_done()
    assert len(calls) == 1                                  # 08:30 gilt nur an freien Tagen
    assert hass.states.get("sensor.door_last_action").attributes["result"] == "skipped"
    hass.states.async_set("binary_sensor.workday", "off")
    async_fire_time_changed(hass, fire(8, 30, 2))
    await hass.async_block_till_done()
    assert len(calls) == 2                                  # freier Tag: 08:30 gilt
    async_fire_time_changed(hass, fire(6, 30, 2))
    await hass.async_block_till_done()
    assert len(calls) == 2
    # niemand zu Hause: nichts aufschließen
    hass.states.async_set(PERSON, "not_home")
    async_fire_time_changed(hass, fire(8, 30, 3))
    await hass.async_block_till_done()
    assert len(calls) == 2
    # Arbeitstag-Sensor nicht verfügbar: sichere Seite, nicht aufschließen
    hass.states.async_set(PERSON, "home")
    hass.states.async_set("binary_sensor.workday", "unavailable")
    async_fire_time_changed(hass, fire(8, 30, 4))
    await hass.async_block_till_done()
    assert len(calls) == 2


async def test_lock_when_everyone_is_away_from_settings(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    entry = make_entry(domain=DOMAIN, title="Door", data={
        **BASE, "presence_entities": [PERSON, "person.partner"], "lock_when_away": True,
        "lock_away_minutes": 3})
    entry.add_to_hass(hass)
    hass.states.async_set(LOCK, "unlocked")
    hass.states.async_set(CONTACT, "off")
    hass.states.async_set(PERSON, "home")
    hass.states.async_set("person.partner", "home")
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    hass.states.async_set(PERSON, "not_home")
    hass.states.async_set("person.partner", "not_home")
    await hass.async_block_till_done()
    await _advance(hass, minutes=4)
    assert len(calls) == 1


async def test_legacy_rules_run_next_to_the_fields(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "lock")
    rule = {"id": "r1", "action": "lock", "trigger": "time", "time": "22:00:00",
            "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}
    await _setup(hass, rules=[rule], lock_time="23:00:00")
    fire = dt_util.now().replace(hour=23, minute=30, second=0, microsecond=0)
    async_fire_time_changed(hass, fire + timedelta(days=1))   # beide Uhrzeiten sind überschritten
    await hass.async_block_till_done()
    assert len(calls) == 2                                      # die ältere Regel und das Feld laufen


async def test_settings_page(hass: HomeAssistant) -> None:
    entry = await _setup(hass, lock_time="22:30:00", rules=[{"id": "x", "action": "lock", "trigger": "time",
                                                              "time": "21:00:00", "weekdays": ["mon"]}])
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    assert result["step_id"] == "door_settings" and not is_menu(result)
    sections = {str(k): v for k, v in result["data_schema"].schema.items()}
    assert list(sections) == ["door", "unlock", "lock", "checks", "notifications", "legacy"]
    assert [name for name, sec in sections.items() if not sec.options["collapsed"]] == ["door"]
    assert result["description_placeholders"]["legacy"] == "1"
    data = {k: v for k, v in BASE.items() if k not in ("function_type", "rules", "name")}
    done = await flow.async_configure(result["flow_id"], dg_page(
        **data, name="Garage", unlock_time_workday="06:30:00", clear_legacy_rules=True))
    assert done["type"] is FlowResultType.ABORT and done["reason"] == "reconfigure_successful"
    assert entry.options["unlock_time_workday"] == "06:30:00" and entry.options["lock_time"] is None
    assert entry.options["rules"] is None and entry.title.endswith("Garage")
    again = await reconfigure(hass, entry)
    assert "legacy" not in {str(k) for k in again["data_schema"].schema}
