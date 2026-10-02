"""Tests für die Funktion Aufgabenplaner."""

from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import is_menu, menu_options, sectioned, make_entry, reconfigure, update_entry, new_instance
from custom_components.ha_housekeeper.const import DOMAIN
from custom_components.ha_housekeeper.task_planner import (
    month_day_matches,
    next_run,
    state_fires,
    trigger_next,
    trigger_summary,
)

SENSOR = "sensor.temperatur"
DOOR = "binary_sensor.tuer"


def _task(triggers, actions=None, **over):
    return {
        "id": "t1",
        "name": "Test",
        "enabled": True,
        "triggers": triggers,
        "actions": actions or [{"action": "test.run", "data": {"x": 1}}],
        "notify_start": False,
        "notify_success": False,
        "notify_error": True,
        **over,
    }


async def _setup(hass: HomeAssistant, tasks, **over):
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.config.language = "en"
    entry = make_entry(
        domain=DOMAIN,
        title="Planer",
        data={
            "function_type": "task_planner",
            "name": "Planer",
            "mobile_enabled": False,
            "persistent_enabled": True,
            "tasks": tasks,
            **over,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


# --- reine Logik ---------------------------------------------------------------


def test_month_day_matches() -> None:
    assert month_day_matches(date(2026, 3, 1), "first")
    assert not month_day_matches(date(2026, 3, 2), "first")
    assert month_day_matches(date(2026, 2, 28), "last")
    assert month_day_matches(date(2024, 2, 29), "last")
    assert not month_day_matches(date(2024, 2, 28), "last")
    assert month_day_matches(date(2026, 3, 15), "day", 15)
    # zu großer Tag gilt als letzter Tag des Monats
    assert month_day_matches(date(2026, 4, 30), "day", 31)
    assert not month_day_matches(date(2026, 4, 29), "day", 31)


async def test_trigger_next(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    now = dt_util.now().replace(year=2026, month=1, day=31, hour=12, minute=0, second=0, microsecond=0)
    weekly = {"type": "weekly", "time": "08:00:00", "weekdays": ["mon"]}
    nxt = trigger_next(weekly, now)
    assert nxt.weekday() == 0 and nxt.hour == 8 and nxt > now
    monthly = {"type": "monthly", "month_mode": "last", "time": "23:30:00"}
    assert trigger_next(monthly, now).date() == date(2026, 1, 31)
    monthly_first = {"type": "monthly", "month_mode": "first", "time": "06:00:00"}
    assert trigger_next(monthly_first, now) == now.replace(month=2, day=1, hour=6)
    once = {"type": "once", "at": "2026-02-01T10:00:00"}
    assert trigger_next(once, now).day == 1
    assert trigger_next({"type": "once", "at": "2025-01-01T10:00:00"}, now) is None
    anchor = now - timedelta(minutes=25)
    assert trigger_next({"type": "interval", "minutes": 10}, now, anchor) == anchor + timedelta(minutes=30)
    assert trigger_next({"type": "state"}, now) is None
    tasks = [_task([weekly, monthly]), _task([once], enabled=False)]
    assert next_run(tasks, now) == min(trigger_next(weekly, now), trigger_next(monthly, now))


def test_state_fires() -> None:
    state = {"type": "state", "to_state": "on"}
    assert state_fires(state, "off", "on")
    assert not state_fires(state, "on", "on")
    assert not state_fires(state, "on", "off")
    assert state_fires({"type": "state"}, "a", "b")
    assert not state_fires({"type": "state"}, "a", "unavailable")
    above = {"type": "threshold", "above": 25}
    assert state_fires(above, "20", "26")
    assert not state_fires(above, "26", "27")      # nur die Flanke löst aus
    assert state_fires(above, None, "30")
    assert not state_fires(above, "20", "abc")
    rng = {"type": "threshold", "above": 10, "below": 20}
    assert state_fires(rng, "5", "15") and not state_fires(rng, "15", "25")
    assert not state_fires({"type": "threshold"}, "1", "2")


async def test_trigger_summary(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    assert trigger_summary(hass, {"type": "weekly", "time": "08:00:00", "weekdays": ["mon"]}) == "mon at 08:00"
    assert "last day" in trigger_summary(hass, {"type": "monthly", "month_mode": "last", "time": "09:00:00"})
    assert trigger_summary(hass, {"type": "interval", "minutes": 15}) == "every 15 minutes"
    assert "for 5 minutes" in trigger_summary(
        hass, {"type": "state", "entity_id": DOOR, "to_state": "on", "for_minutes": 5}
    )
    assert "above 25" in trigger_summary(hass, {"type": "threshold", "entity_id": SENSOR, "above": 25.0})
    hass.config.language = "de"
    assert "täglich" in trigger_summary(
        hass, {"type": "weekly", "time": "08:00:00", "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}
    )


# --- Controller ---------------------------------------------------------------


async def test_state_trigger_runs_actions(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "test", "run")
    hass.states.async_set(DOOR, "off")
    await _setup(hass, [_task([{"type": "state", "entity_id": DOOR, "to_state": "on"}])])
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert len(calls) == 1 and calls[0].data == {"x": 1}
    hass.states.async_set(DOOR, "off")
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert hass.states.get("sensor.planer_last_task_run").attributes["status"] == "ok"


async def test_threshold_trigger_and_for_minutes(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "test", "run")
    hass.states.async_set(SENSOR, "20")
    await _setup(
        hass,
        [_task([{"type": "threshold", "entity_id": SENSOR, "above": 25, "for_minutes": 5}])],
    )
    hass.states.async_set(SENSOR, "26")
    await hass.async_block_till_done()
    assert not calls
    hass.states.async_set(SENSOR, "20")           # Bedingung endet: Timer abgebrochen
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert not calls
    hass.states.async_set(SENSOR, "27")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_time_trigger_weekday_and_monthly(hass: HomeAssistant, freezer) -> None:
    calls = async_mock_service(hass, "test", "run")
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-01-30 23:59:58+01:00")      # Freitag
    tasks = [
        _task([{"type": "monthly", "month_mode": "last", "time": "00:00:00"}], id="m", name="Monat"),
        _task([{"type": "weekly", "time": "00:00:00", "weekdays": ["sat"]}], id="w", name="Woche"),
        _task([{"type": "weekly", "time": "00:00:00", "weekdays": ["mon"]}], id="x", name="Montag"),
    ]
    await _setup(hass, tasks)
    # 31.01.2026 ist Samstag und der letzte Tag des Monats
    freezer.move_to("2026-01-31 00:00:00+01:00")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert len(calls) == 2            # Monat + Woche, nicht Montag


async def test_failure_notifies_and_records(hass: HomeAssistant) -> None:
    persist = async_mock_service(hass, "persistent_notification", "create")
    hass.states.async_set(DOOR, "off")
    entry, ctrl = await _setup(
        hass,
        [_task([{"type": "state", "entity_id": DOOR, "to_state": "on"}],
               actions=[{"action": "gibt.es_nicht"}])],
    )
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert len(persist) == 1 and "failed" in persist[0].data["message"]
    assert ctrl.last_run["status"] == "error"
    attrs = hass.states.get("sensor.planer_last_task_run").attributes
    assert attrs["task"] == "Test" and attrs["status"] == "error"


async def test_notify_start_success_and_default_error_only(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "test", "run")
    persist = async_mock_service(hass, "persistent_notification", "create")
    hass.states.async_set(DOOR, "off")
    await _setup(
        hass,
        [_task([{"type": "state", "entity_id": DOOR, "to_state": "on"}],
               notify_start=True, notify_success=True)],
    )
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert [p.data["message"] for p in persist] == ['Task "Test" started', 'Task "Test" completed']


async def test_no_notification_on_success_by_default(hass: HomeAssistant) -> None:
    async_mock_service(hass, "test", "run")
    persist = async_mock_service(hass, "persistent_notification", "create")
    hass.states.async_set(DOOR, "off")
    await _setup(hass, [_task([{"type": "state", "entity_id": DOOR, "to_state": "on"}])])
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert not persist


async def test_switch_pauses_and_button_runs(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "test", "run")
    hass.states.async_set(DOOR, "off")
    entry, ctrl = await _setup(hass, [_task([{"type": "state", "entity_id": DOOR, "to_state": "on"}])])
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.planer_task_planner_active"}, blocking=True
    )
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert not calls
    # Button läuft auch bei Pause
    await hass.services.async_call("button", "press", {"entity_id": "button.planer_test"}, blocking=True)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert ctrl.last_run["trigger"] == "manual"
    # Pause bleibt nach dem Neuladen erhalten
    assert await hass.config_entries.async_reload(entry.hub_id)
    assert hass.states.get("switch.planer_task_planner_active").state == "off"


async def test_disabled_task_and_removed_button(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "test", "run")
    hass.states.async_set(DOOR, "off")
    entry, _ = await _setup(
        hass, [_task([{"type": "state", "entity_id": DOOR, "to_state": "on"}], enabled=False)]
    )
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert not calls
    assert hass.states.get("button.planer_test") is not None
    update_entry(hass, entry, {"tasks": []})
    await hass.async_block_till_done()
    assert hass.states.get("button.planer_test") is None


async def test_variables_available_in_actions(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "test", "run")
    hass.states.async_set(DOOR, "off")
    await _setup(
        hass,
        [_task([{"type": "state", "entity_id": DOOR, "to_state": "on"}],
               actions=[{"action": "test.run", "data": {"who": "{{ trigger.entity_id }}", "t": "{{ task }}"}}])],
    )
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert calls[0].data == {"who": DOOR, "t": "Test"}


# --- Config- und Options-Flow -----------------------------------------------------


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "task_planner")
    assert result["step_id"] == "new_task_planner"
    bad = await hass.config_entries.subentries.async_configure(
        result["flow_id"], sectioned({"name": "Planer", "mobile_enabled": True, "tts_enabled": False, "persistent_enabled": False})
    )
    assert bad["errors"] == {"base": "no_targets"}
    ok = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        sectioned({"name": "Planer", "mobile_enabled": False, "tts_enabled": False, "persistent_enabled": True}),
    )
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["tasks"] == []


async def test_options_flow_add_edit_delete_task(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    entry, _ = await _setup(hass, [])
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    assert is_menu(result) and result["step_id"] == "tp_menu"
    assert "edit_task" not in menu_options(result)

    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_task"})
    assert result["step_id"] == "task_edit"
    bad = await flow.async_configure(
        result["flow_id"],
        {"name": "Müll", "enabled": True, "actions": [], "notify_start": False,
         "notify_success": False, "notify_error": True},
    )
    assert bad["errors"] == {"base": "no_actions"}
    result = await flow.async_configure(
        result["flow_id"],
        {"name": "Müll", "enabled": True, "actions": [{"action": "test.run"}],
         "notify_start": False, "notify_success": True, "notify_error": True},
    )
    assert result["step_id"] == "task_triggers"
    assert "delete_trigger" not in menu_options(result)

    # Wochentag
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_trigger"})
    result = await flow.async_configure(result["flow_id"], {"type": "weekly"})
    assert result["step_id"] == "trigger_weekly"
    bad = await flow.async_configure(result["flow_id"], {"time": "07:00:00", "weekdays": []})
    assert bad["errors"] == {"base": "no_weekday"}
    result = await flow.async_configure(result["flow_id"], {"time": "07:00:00", "weekdays": ["mon", "thu"]})
    assert result["step_id"] == "task_triggers"
    assert "weekly" not in result["description_placeholders"]["triggers"]
    assert "mon, thu at 07:00" in result["description_placeholders"]["triggers"]

    # Monat
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_trigger"})
    result = await flow.async_configure(result["flow_id"], {"type": "monthly"})
    result = await flow.async_configure(
        result["flow_id"], {"month_mode": "last", "month_day": 1, "time": "18:00:00"}
    )
    # Zustand: Mindestdauer ohne Zielzustand
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_trigger"})
    result = await flow.async_configure(result["flow_id"], {"type": "state"})
    bad = await flow.async_configure(result["flow_id"], {"entity_id": DOOR, "for_minutes": 5})
    assert bad["errors"] == {"base": "for_needs_state"}
    result = await flow.async_configure(
        result["flow_id"], {"entity_id": DOOR, "to_state": "on", "for_minutes": 5}
    )
    # Grenzwert
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_trigger"})
    result = await flow.async_configure(result["flow_id"], {"type": "threshold"})
    bad = await flow.async_configure(result["flow_id"], {"entity_id": SENSOR, "for_minutes": 0})
    assert bad["errors"] == {"base": "no_threshold"}
    bad = await flow.async_configure(
        result["flow_id"], {"entity_id": SENSOR, "above": 30, "below": 20, "for_minutes": 0}
    )
    assert bad["errors"] == {"base": "min_ge_max"}
    result = await flow.async_configure(
        result["flow_id"], {"entity_id": SENSOR, "above": 30, "for_minutes": 0}
    )
    # einmalig + Intervall
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_trigger"})
    result = await flow.async_configure(result["flow_id"], {"type": "once"})
    bad = await flow.async_configure(result["flow_id"], {"at": "2020-01-01 10:00:00"})
    assert bad["errors"] == {"base": "in_past"}
    future = (dt_util.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    result = await flow.async_configure(result["flow_id"], {"at": future})
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_trigger"})
    result = await flow.async_configure(result["flow_id"], {"type": "interval"})
    result = await flow.async_configure(result["flow_id"], {"minutes": 90})

    # Einen Auslöser wieder entfernen (den Intervall-Auslöser)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "delete_trigger"})
    result = await flow.async_configure(result["flow_id"], {"trigger": "5"})
    assert result["step_id"] == "task_triggers"
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "task_save"})
    assert result["step_id"] == "tp_menu"

    tasks = entry.options["tasks"]
    assert len(tasks) == 1 and tasks[0]["name"] == "Müll"
    assert [t["type"] for t in tasks[0]["triggers"]] == ["weekly", "monthly", "state", "threshold", "once"]
    assert tasks[0]["triggers"][3] == {"type": "threshold", "entity_id": SENSOR, "above": 30, "for_minutes": 0}
    assert tasks[0]["triggers"][2]["for_minutes"] == 5
    assert tasks[0]["notify_success"] is True
    await hass.async_block_till_done()

    # Bearbeiten: Name ändern, Auslöser bleiben erhalten
    task_id = tasks[0]["id"]
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "edit_task"})
    result = await flow.async_configure(result["flow_id"], {"task": task_id})
    assert result["step_id"] == "task_edit"
    result = await flow.async_configure(
        result["flow_id"],
        {"name": "Müll raus", "enabled": True, "actions": [{"action": "test.run"}],
         "notify_start": False, "notify_success": False, "notify_error": True},
    )
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "task_save"})
    tasks = entry.options["tasks"]
    assert len(tasks) == 1 and tasks[0]["name"] == "Müll raus" and tasks[0]["id"] == task_id
    assert len(tasks[0]["triggers"]) == 5

    # Löschen
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "delete_task"})
    result = await flow.async_configure(result["flow_id"], {"task": task_id})
    assert entry.options["tasks"] == []
