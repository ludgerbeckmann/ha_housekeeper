"""Logik der Funktion "Aufgabenplaner": Auslöser lösen frei definierte Aktionen aus."""

from __future__ import annotations

import asyncio
import calendar
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Context, Event, HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.script import Script
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_TASKS,
    DOMAIN,
    MONTH_FIRST,
    MONTH_LAST,
    TASK_ACTIONS,
    TASK_ENABLED,
    TASK_ID,
    TASK_NAME,
    TASK_NOTIFY_ERROR,
    TASK_NOTIFY_START,
    TASK_NOTIFY_SUCCESS,
    TASK_TRIGGERS,
    TR_ABOVE,
    TR_AT,
    TR_BELOW,
    TR_ENTITY,
    TR_FOR,
    TR_MINUTES,
    TR_MONTH_DAY,
    TR_MONTH_MODE,
    TR_TIME,
    TR_TO_STATE,
    TR_TYPE,
    TR_WEEKDAYS,
    TRIG_INTERVAL,
    TRIG_MONTHLY,
    TRIG_ONCE,
    TRIG_STATE,
    TRIG_THRESHOLD,
    TRIG_WEEKLY,
    WEEKDAYS,
    signal_update,
)
from .notify import Notifier, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
_UNKNOWN = (STATE_UNAVAILABLE, STATE_UNKNOWN)

_TEXT = {
    "de": {
        "start": "Aufgabe „{name}“ gestartet",
        "done": "Aufgabe „{name}“ abgeschlossen",
        "failed": "Aufgabe „{name}“ fehlgeschlagen: {error}",
        "month_first": "am 1. des Monats",
        "month_last": "am letzten Tag des Monats",
        "month_day": "am {day}. des Monats",
        "weekly": "{days} um {time}",
        "daily": "täglich",
        "monthly": "{rule} um {time}",
        "once": "einmalig am {at}",
        "interval": "alle {minutes} Minuten",
        "state": "{entity} wechselt zu „{state}“",
        "state_any": "{entity} ändert sich",
        "threshold": "{entity} {cond}",
        "above": "über {value}",
        "below": "unter {value}",
        "for": ", für {minutes} Minuten",
        "triggers": "Auslöser",
        "actions": "Aktionen",
        "off": "aus",
    },
    "en": {
        "start": "Task \"{name}\" started",
        "done": "Task \"{name}\" completed",
        "failed": "Task \"{name}\" failed: {error}",
        "month_first": "on the 1st of the month",
        "month_last": "on the last day of the month",
        "month_day": "on day {day} of the month",
        "weekly": "{days} at {time}",
        "daily": "daily",
        "monthly": "{rule} at {time}",
        "once": "once on {at}",
        "interval": "every {minutes} minutes",
        "state": "{entity} changes to \"{state}\"",
        "state_any": "{entity} changes",
        "threshold": "{entity} {cond}",
        "above": "above {value}",
        "below": "below {value}",
        "for": ", for {minutes} minutes",
        "triggers": "triggers",
        "actions": "actions",
        "off": "off",
    },
}


def _text(hass: HomeAssistant) -> dict[str, str]:
    return _TEXT["de" if (hass.config.language or "").startswith("de") else "en"]


# --- reine Logik: Kalender ---------------------------------------------------------


def month_day_matches(day: date, mode: str, month_day: int = 1) -> bool:
    """Trifft der Tag die Monatsregel? Ein zu großer Tag gilt als letzter Tag."""
    last = calendar.monthrange(day.year, day.month)[1]
    if mode == MONTH_FIRST:
        return day.day == 1
    if mode == MONTH_LAST:
        return day.day == last
    return day.day == min(max(int(month_day or 1), 1), last)


def day_matches(trigger: dict[str, Any], day: date) -> bool:
    """Tagesprüfung für Wochentags- und Monatsauslöser."""
    if trigger.get(TR_TYPE) == TRIG_MONTHLY:
        return month_day_matches(
            day, trigger.get(TR_MONTH_MODE, MONTH_FIRST), trigger.get(TR_MONTH_DAY, 1)
        )
    return WEEKDAYS[day.weekday()] in (trigger.get(TR_WEEKDAYS) or WEEKDAYS)


def trigger_next(
    trigger: dict[str, Any], now: datetime, anchor: datetime | None = None
) -> datetime | None:
    """Nächster Zeitpunkt eines Zeit-Auslösers nach `now` (lokale Zeit), sonst None."""
    kind = trigger.get(TR_TYPE)
    if kind in (TRIG_WEEKLY, TRIG_MONTHLY):
        at = dt_util.parse_time(str(trigger.get(TR_TIME, "")))
        if at is None:
            return None
        for offset in range(0, 400):
            day = now + timedelta(days=offset)
            if not day_matches(trigger, day.date()):
                continue
            candidate = day.replace(
                hour=at.hour, minute=at.minute, second=at.second, microsecond=0
            )
            if candidate > now:
                return candidate
        return None
    if kind == TRIG_ONCE:
        at = dt_util.parse_datetime(str(trigger.get(TR_AT, "")))
        if at is None:
            return None
        at = dt_util.as_local(at) if at.tzinfo else at.replace(tzinfo=dt_util.get_default_time_zone())
        return at if at > now else None
    if kind == TRIG_INTERVAL:
        minutes = float(trigger.get(TR_MINUTES) or 0)
        if minutes <= 0 or anchor is None:
            return None
        step = timedelta(minutes=minutes)
        if now < anchor:
            return anchor
        return anchor + step * (int((now - anchor) / step) + 1)
    return None


# --- reine Logik: Zustands- und Grenzwertauslöser ----------------------------------


def _number(value: str | None) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def state_condition(trigger: dict[str, Any], value: str | None) -> bool:
    """Gilt die Bedingung des Auslösers für den Zustandswert?"""
    if value is None or value in _UNKNOWN:
        return False
    if trigger.get(TR_TYPE) == TRIG_THRESHOLD:
        number = _number(value)
        if number is None:
            return False
        above, below = trigger.get(TR_ABOVE), trigger.get(TR_BELOW)
        if above is None and below is None:
            return False
        return (above is None or number > float(above)) and (
            below is None or number < float(below)
        )
    target = trigger.get(TR_TO_STATE)
    if target in (None, ""):
        return True
    return value.lower() == str(target).lower()


def state_fires(trigger: dict[str, Any], old: str | None, new: str | None) -> bool:
    """Löst der Zustandswechsel `old` -> `new` aus (nur bei Flanke)?"""
    if old == new or new is None:
        return False
    if trigger.get(TR_TYPE) == TRIG_STATE and trigger.get(TR_TO_STATE) in (None, ""):
        return new not in _UNKNOWN
    return state_condition(trigger, new) and not state_condition(trigger, old)


def trigger_summary(hass: HomeAssistant, trigger: dict[str, Any]) -> str:
    """Kurzbeschreibung eines Auslösers."""
    text = _text(hass)
    kind = trigger.get(TR_TYPE)
    if kind == TRIG_WEEKLY:
        days = trigger.get(TR_WEEKDAYS) or WEEKDAYS
        return text["weekly"].format(
            days=text["daily"] if len(days) == 7 else ", ".join(days),
            time=str(trigger.get(TR_TIME, ""))[:5],
        )
    if kind == TRIG_MONTHLY:
        mode = trigger.get(TR_MONTH_MODE, MONTH_FIRST)
        rule = text[f"month_{mode}"].format(day=trigger.get(TR_MONTH_DAY, 1))
        return text["monthly"].format(rule=rule, time=str(trigger.get(TR_TIME, ""))[:5])
    if kind == TRIG_ONCE:
        return text["once"].format(at=str(trigger.get(TR_AT, ""))[:16].replace("T", " "))
    if kind == TRIG_INTERVAL:
        return text["interval"].format(minutes=_fmt(trigger.get(TR_MINUTES)))
    extra = ""
    if float(trigger.get(TR_FOR) or 0) > 0:
        extra = text["for"].format(minutes=_fmt(trigger.get(TR_FOR)))
    entity = trigger.get(TR_ENTITY, "")
    if kind == TRIG_STATE:
        if trigger.get(TR_TO_STATE) in (None, ""):
            return text["state_any"].format(entity=entity)
        return text["state"].format(entity=entity, state=trigger.get(TR_TO_STATE)) + extra
    parts = []
    if trigger.get(TR_ABOVE) is not None:
        parts.append(text["above"].format(value=_fmt(trigger.get(TR_ABOVE))))
    if trigger.get(TR_BELOW) is not None:
        parts.append(text["below"].format(value=_fmt(trigger.get(TR_BELOW))))
    return text["threshold"].format(entity=entity, cond=" / ".join(parts)) + extra


def _fmt(value: Any) -> str:
    number = _number(value)
    if number is None:
        return str(value)
    return str(int(number)) if number == int(number) else str(number)


def task_summary(hass: HomeAssistant, task: dict[str, Any]) -> str:
    """Kurzbeschreibung einer Aufgabe für Listen im Options-Flow."""
    text = _text(hass)
    off = "" if task.get(TASK_ENABLED, True) else f" ({text['off']})"
    return (
        f"{task.get(TASK_NAME)}{off}: {len(task.get(TASK_TRIGGERS) or [])} "
        f"{text['triggers']}, {len(task.get(TASK_ACTIONS) or [])} {text['actions']}"
    )


def next_run(
    tasks: list[dict[str, Any]], now: datetime, anchor: datetime | None = None
) -> datetime | None:
    """Nächster Zeitpunkt aller aktiven Aufgaben mit Zeit-Auslöser."""
    best: datetime | None = None
    for task in tasks:
        if not task.get(TASK_ENABLED, True):
            continue
        for trigger in task.get(TASK_TRIGGERS) or []:
            candidate = trigger_next(trigger, now, anchor)
            if candidate is not None and (best is None or candidate < best):
                best = candidate
    return best


# --- Controller -------------------------------------------------------------------


class TaskPlannerController:
    """Überwacht die Auslöser der Aufgaben und führt deren Aktionen aus."""

    model = "Task planner"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.last_run: dict[str, Any] | None = None
        self._running: set[str] = set()
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._notifier = Notifier(
            hass, self._get, f"{DOMAIN}_{entry.entry_id}", lambda: entry.title
        )
        self._unsubs: list[CALLBACK_TYPE] = []
        self._timers: dict[tuple[str, int], CALLBACK_TYPE] = {}
        self._anchor = dt_util.now()

    # --- Hilfen ------------------------------------------------------------

    @property
    def tasks(self) -> list[dict[str, Any]]:
        return list(self._get(CONF_TASKS, []) or [])

    @property
    def running(self) -> bool:
        return bool(self._running)

    @property
    def next_run(self) -> datetime | None:
        return next_run(self.tasks, dt_util.now(), self._anchor)

    def task(self, task_id: str) -> dict[str, Any] | None:
        return next((t for t in self.tasks if t.get(TASK_ID) == task_id), None)

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"enabled": self.enabled, "last_run": self.last_run}
        )
        self._notify()

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.enabled = bool(stored.get("enabled", True))
        self.last_run = stored.get("last_run")
        self._anchor = dt_util.now()
        for task in self.tasks:
            if not task.get(TASK_ENABLED, True):
                continue
            for index, trigger in enumerate(task.get(TASK_TRIGGERS) or []):
                try:
                    self._register(task, index, trigger)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception(
                        "%s: Auslöser %s der Aufgabe „%s“ ungültig",
                        self.entry.title, index + 1, task.get(TASK_NAME),
                    )

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self._async_save()

    # --- Auslöser ------------------------------------------------------------------

    def _fire(self, task: dict[str, Any], trigger: dict[str, Any], **extra: Any) -> None:
        if not self.enabled:
            return
        info = {"type": trigger.get(TR_TYPE), **extra}
        self.hass.async_create_task(self.async_run_task(task, info))

    def _register(self, task: dict[str, Any], index: int, trigger: dict[str, Any]) -> None:
        kind = trigger.get(TR_TYPE)
        if kind in (TRIG_WEEKLY, TRIG_MONTHLY):
            at = dt_util.parse_time(str(trigger.get(TR_TIME, "")))
            if at is None:
                raise ValueError("ungültige Uhrzeit")

            @callback
            def _on_time(now: datetime, task=task, trigger=trigger) -> None:
                if day_matches(trigger, dt_util.as_local(now).date()):
                    self._fire(task, trigger)

            self._unsubs.append(
                async_track_time_change(
                    self.hass, _on_time, hour=at.hour, minute=at.minute, second=at.second
                )
            )
        elif kind == TRIG_ONCE:
            when = trigger_next(trigger, dt_util.now())
            if when is None:
                return  # liegt in der Vergangenheit

            @callback
            def _on_once(now: datetime, task=task, trigger=trigger) -> None:
                self._fire(task, trigger)

            self._unsubs.append(async_track_point_in_time(self.hass, _on_once, when))
        elif kind == TRIG_INTERVAL:
            minutes = float(trigger.get(TR_MINUTES) or 0)
            if minutes <= 0:
                raise ValueError("ungültiges Intervall")

            @callback
            def _on_interval(now: datetime, task=task, trigger=trigger) -> None:
                self._fire(task, trigger)

            self._unsubs.append(
                async_track_time_interval(
                    self.hass, _on_interval, timedelta(minutes=minutes)
                )
            )
        elif kind in (TRIG_STATE, TRIG_THRESHOLD):
            entity_id = trigger[TR_ENTITY]

            @callback
            def _on_state(event: Event, task=task, trigger=trigger, index=index) -> None:
                self._on_state(task, index, trigger, event)

            self._unsubs.append(
                async_track_state_change_event(self.hass, [entity_id], _on_state)
            )
        else:
            raise ValueError(f"unbekannter Auslösertyp {kind}")

    @callback
    def _on_state(
        self, task: dict[str, Any], index: int, trigger: dict[str, Any], event: Event
    ) -> None:
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        old_value = old.state if old else None
        new_value = new.state if new else None
        key = (task[TASK_ID], index)
        wait = float(trigger.get(TR_FOR) or 0)
        extra = {
            "entity_id": trigger.get(TR_ENTITY),
            "from_state": old_value,
            "to_state": new_value,
        }

        if wait > 0 and trigger.get(TR_TYPE) in (TRIG_STATE, TRIG_THRESHOLD):
            if not state_condition(trigger, new_value):
                if timer := self._timers.pop(key, None):
                    timer()
                return
            if key in self._timers or state_condition(trigger, old_value):
                return

            @callback
            def _elapsed(_now: datetime) -> None:
                self._timers.pop(key, None)
                state = self.hass.states.get(trigger[TR_ENTITY])
                if state is not None and state_condition(trigger, state.state):
                    self._fire(task, trigger, **extra)

            self._timers[key] = async_call_later(self.hass, wait * 60, _elapsed)
            return

        if state_fires(trigger, old_value, new_value):
            self._fire(task, trigger, **extra)

    # --- Ausführung ------------------------------------------------------------------

    async def async_run_task_id(self, task_id: str) -> None:
        """Aufgabe von Hand starten (auch wenn die Automatik pausiert oder die Aufgabe aus ist)."""
        if (task := self.task(task_id)) is not None:
            await self.async_run_task(task, {"type": "manual"})

    async def async_run_task(self, task: dict[str, Any], info: dict[str, Any]) -> None:
        task_id = task[TASK_ID]
        name = task.get(TASK_NAME)
        if task_id in self._running:
            _LOGGER.warning("%s: Aufgabe „%s“ läuft bereits, übersprungen", self.entry.title, name)
            return
        self._running.add(task_id)
        self._notify()
        text = _text(self.hass)
        record: dict[str, Any] = {
            "time": dt_util.utcnow().isoformat(),
            "task": name,
            "trigger": info.get("type"),
            "status": "ok",
            "error": None,
        }
        try:
            if task.get(TASK_NOTIFY_START):
                await self._notifier.async_send(
                    text["start"].format(name=name), kind=f"task_{task_id}"
                )
            try:
                script = Script(
                    self.hass,
                    cv.SCRIPT_SCHEMA(task.get(TASK_ACTIONS) or []),
                    f"{self.entry.title}: {name}",
                    DOMAIN,
                )
                await script.async_run(
                    {"trigger": {"platform": DOMAIN, **info}, "task": name},
                    Context(),
                )
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("%s: Aufgabe „%s“ fehlgeschlagen: %s", self.entry.title, name, err)
                record.update(status="error", error=str(err) or type(err).__name__)
            if record["status"] == "ok":
                if task.get(TASK_NOTIFY_SUCCESS):
                    await self._notifier.async_send(
                        text["done"].format(name=name), kind=f"task_{task_id}"
                    )
            elif task.get(TASK_NOTIFY_ERROR, True):
                await self._notifier.async_send(
                    text["failed"].format(name=name, error=record["error"]),
                    kind=f"task_{task_id}",
                )
            self.last_run = record
            await self._async_save()
        finally:
            self._running.discard(task_id)
            self._notify()
