"""Logik der Funktion "Türwächter"."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BLOCK_RETRY,
    CONF_BLOCK_ACTION,
    CONF_CONTACT,
    CONF_LOCK,
    CONF_MANUAL_OVERRIDE,
    CONF_MANUAL_PAUSE_MINUTES,
    CONF_OPEN_ALERT_MINUTES,
    CONF_OPEN_ALERT_REPEAT,
    CONF_RETRY_MINUTES,
    CONF_RULES,
    CONF_VERIFY_SECONDS,
    DEFAULT_MANUAL_PAUSE_MINUTES,
    DEFAULT_OPEN_ALERT_MINUTES,
    DEFAULT_OPEN_ALERT_REPEAT,
    DEFAULT_RETRY_MINUTES,
    DEFAULT_VERIFY_SECONDS,
    DOMAIN,
    MANUAL_PAUSE,
    R_ACTION,
    R_DELAY,
    R_ENTITY,
    R_FOR_MINUTES,
    R_ID,
    R_TIME,
    R_TO_STATE,
    R_TRIGGER,
    R_WEEKDAYS,
    RULE_LOCK,
    RULE_UNLOCK,
    TRIGGER_DOOR_CLOSED,
    TRIGGER_STATE,
    TRIGGER_TIME,
    WEEKDAYS,
    signal_update,
)
from .notify import Notifier, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
LOCKED = "locked"
UNLOCKED = "unlocked"
OWN_ACTION_WINDOW = 120  # Sekunden, in denen eine Zustandsänderung als eigene gilt
_IGNORED_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)

MESSAGES: dict[str, dict[str, str]] = {
    "de": {
        "blocked": "{name} ist offen und wurde nicht abgeschlossen.",
        "blocked_retry": "{name} ist offen und wird nach dem Schließen abgeschlossen.",
        "contact_unavailable": "Der Türkontakt von {name} ist nicht verfügbar, es wurde nicht abgeschlossen.",
        "open_too_long": "{name} steht seit {minutes} Minuten offen.",
        "failed": "Das Schloss von {name} ist nicht {target} (Zustand: {state}).",
        "error": "Das Schloss von {name} konnte nicht bedient werden.",
        LOCKED: "abgeschlossen",
        UNLOCKED: "aufgeschlossen",
        RULE_LOCK: "Abschließen",
        RULE_UNLOCK: "Aufschließen",
        "for": "für",
        "min": "min",
        "door_closed": "Tür geschlossen seit",
    },
    "en": {
        "blocked": "{name} is open and was not locked.",
        "blocked_retry": "{name} is open and will be locked once it is closed.",
        "contact_unavailable": "The door contact of {name} is unavailable, the door was not locked.",
        "open_too_long": "{name} has been open for {minutes} minutes.",
        "failed": "The lock of {name} is not {target} (state: {state}).",
        "error": "The lock of {name} could not be operated.",
        LOCKED: "locked",
        UNLOCKED: "unlocked",
        RULE_LOCK: "Lock",
        RULE_UNLOCK: "Unlock",
        "for": "for",
        "min": "min",
        "door_closed": "Door closed for",
    },
}


def _lang(hass: HomeAssistant) -> dict[str, str]:
    return MESSAGES["de" if (hass.config.language or "").startswith("de") else "en"]


def _fmt(text: str, **values: Any) -> str:
    return text.format(**values)


def rule_summary(hass: HomeAssistant, rule: dict[str, Any]) -> str:
    """Kurzbeschreibung einer Regel für Listen im Options-Flow."""
    lang = _lang(hass)
    head = lang.get(rule[R_ACTION], rule[R_ACTION])
    trigger = rule[R_TRIGGER]
    if trigger == TRIGGER_STATE:
        text = f"{rule.get(R_ENTITY)} → {rule.get(R_TO_STATE)}"
        if (minutes := int(rule.get(R_FOR_MINUTES) or 0)) > 0:
            text += f" {lang['for']} {minutes} {lang['min']}"
    elif trigger == TRIGGER_TIME:
        text = str(rule.get(R_TIME, ""))[:5]
        days = rule.get(R_WEEKDAYS) or WEEKDAYS
        if len(days) < 7:
            text += " (" + ", ".join(days) + ")"
    else:
        text = f"{lang['door_closed']} {int(rule.get(R_DELAY) or 0)} s"
    return f"{head}: {text}"


class DoorGuardController:
    """Führt Regeln aus und überwacht Schloss und Türkontakt."""

    model = "Türwächter"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.automation_enabled = True
        self.paused_until: datetime | None = None
        self.last_action: dict[str, Any] | None = None
        self.open_too_long = False
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._notifier = Notifier(
            hass, self._get, f"{DOMAIN}_{entry.entry_id}", lambda: entry.title
        )
        self._unsubs: list = []
        self._timers: dict[str, Any] = {}
        self._pending_lock: datetime | None = None
        self._blocked_active = False
        self._own_target: str | None = None
        self._own_until = 0.0

    # --- Hilfen ------------------------------------------------------------

    def _opt(self, key: str, default: Any = None) -> Any:
        return self._get(key, default)

    @property
    def _name(self) -> str:
        return self.entry.title

    def _rules(self) -> list[dict[str, Any]]:
        return list(self._opt(CONF_RULES, []) or [])

    def _contact_state(self) -> str | None:
        contact = self._opt(CONF_CONTACT)
        if not contact:
            return None
        state = self.hass.states.get(contact)
        return state.state if state else STATE_UNAVAILABLE

    def _notify_dispatch(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    def _set_timer(self, key: str, delay: float, action) -> None:
        self._cancel_timer(key)

        async def _fire(_now: datetime) -> None:
            self._timers.pop(key, None)
            await action()

        self._timers[key] = async_call_later(self.hass, max(delay, 0), _fire)

    def _cancel_timer(self, key: str) -> None:
        if unsub := self._timers.pop(key, None):
            unsub()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "enabled": self.automation_enabled,
                "paused_until": self.paused_until.isoformat()
                if self.paused_until
                else None,
                "last_action": self.last_action,
            }
        )
        self._notify_dispatch()

    async def _record(self, action: str, reason: str, result: str) -> None:
        self.last_action = {
            "time": dt_util.utcnow().isoformat(),
            "action": action,
            "reason": reason,
            "result": result,
        }
        await self._async_save()

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.automation_enabled = bool(stored.get("enabled", True))
        if raw := stored.get("paused_until"):
            self.paused_until = dt_util.parse_datetime(raw)
        self.last_action = stored.get("last_action")
        self._schedule_pause_end()

        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self._opt(CONF_LOCK)], self._on_lock_change
            )
        )
        if contact := self._opt(CONF_CONTACT):
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [contact], self._on_contact_change
                )
            )
            self._start_open_timer_from_current_state()
        for rule in self._rules():
            self._setup_rule(rule)

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for key in list(self._timers):
            self._cancel_timer(key)

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.automation_enabled = enabled
        if not enabled:
            self._pending_lock = None
        await self._async_save()

    # --- Regeln --------------------------------------------------------------

    def _setup_rule(self, rule: dict[str, Any]) -> None:
        trigger = rule.get(R_TRIGGER)
        rule_id = rule.get(R_ID, "")
        if trigger == TRIGGER_STATE and rule.get(R_ENTITY):

            async def _on_state(event: Event, rule=rule, rule_id=rule_id) -> None:
                await self._on_rule_state(rule, rule_id, event)

            self._unsubs.append(
                async_track_state_change_event(self.hass, [rule[R_ENTITY]], _on_state)
            )
        elif trigger == TRIGGER_TIME:
            at = dt_util.parse_time(str(rule.get(R_TIME, "")))
            if at is None:
                _LOGGER.warning("Regel %s: ungültige Uhrzeit", rule_id)
                return

            async def _on_time(now: datetime, rule=rule) -> None:
                days = rule.get(R_WEEKDAYS) or WEEKDAYS
                if WEEKDAYS[dt_util.as_local(now).weekday()] in days:
                    await self.async_run_action(rule[R_ACTION], f"time:{rule[R_TIME]}")

            self._unsubs.append(
                async_track_time_change(
                    self.hass, _on_time, hour=at.hour, minute=at.minute, second=at.second
                )
            )

    async def _on_rule_state(
        self, rule: dict[str, Any], rule_id: str, event: Event
    ) -> None:
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        key = f"state_{rule_id}"
        if new is None:
            return
        if new.state != rule.get(R_TO_STATE):
            self._cancel_timer(key)
            return
        if old is None or old.state == new.state or old.state in _IGNORED_STATES:
            return
        reason = f"state:{rule[R_ENTITY]}={new.state}"
        minutes = float(rule.get(R_FOR_MINUTES) or 0)
        if minutes > 0:

            async def _later() -> None:
                await self.async_run_action(rule[R_ACTION], reason)

            self._set_timer(key, minutes * 60, _later)
        else:
            await self.async_run_action(rule[R_ACTION], reason)

    # --- Ausführung ------------------------------------------------------------

    async def async_run_action(self, action: str, reason: str) -> None:
        """Regelaktion ausführen, sofern Automatik aktiv und nicht pausiert."""
        if not self.automation_enabled:
            _LOGGER.debug("%s: Automatik aus, Aktion %s übersprungen", self._name, action)
            return
        now = dt_util.utcnow()
        if self.paused_until:
            if now < self.paused_until:
                _LOGGER.debug("%s: pausiert, Aktion %s übersprungen", self._name, action)
                return
            self.paused_until = None

        if action == RULE_LOCK:
            contact_state = self._contact_state()
            if contact_state is not None and contact_state != STATE_OFF:
                await self._async_blocked(
                    reason,
                    "open" if contact_state == STATE_ON else "contact_unavailable",
                )
                return
            target, service = LOCKED, "lock"
        else:
            self._pending_lock = None
            target, service = UNLOCKED, "unlock"

        lock_state = self.hass.states.get(self._opt(CONF_LOCK))
        if lock_state is not None and lock_state.state == target:
            await self._record(action, reason, "already")
            return

        self._own_target = target
        self._own_until = time.monotonic() + OWN_ACTION_WINDOW
        try:
            await self.hass.services.async_call(
                "lock", service, {"entity_id": self._opt(CONF_LOCK)}, blocking=True
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("%s: Schloss konnte nicht bedient werden", self._name)
            self._own_target = None
            await self._record(action, reason, "error")
            await self._notifier.async_send(
                _fmt(_lang(self.hass)["error"], name=self._name), kind="failed"
            )
            return

        if action == RULE_LOCK:
            self._pending_lock = None
            if self._blocked_active:
                self._blocked_active = False
                await self._notifier.async_clear("blocked")
        await self._record(action, reason, "ok")

        if (seconds := float(self._opt(CONF_VERIFY_SECONDS, DEFAULT_VERIFY_SECONDS))) > 0:

            async def _verify() -> None:
                await self._async_verify(action, target)

            self._set_timer("verify", seconds, _verify)

    async def _async_blocked(self, reason: str, why: str) -> None:
        lang = _lang(self.hass)
        retry = self._opt(CONF_BLOCK_ACTION) == BLOCK_RETRY and why == "open"
        if retry:
            minutes = float(self._opt(CONF_RETRY_MINUTES, DEFAULT_RETRY_MINUTES))
            self._pending_lock = dt_util.utcnow() + timedelta(minutes=minutes)
        key = "contact_unavailable" if why != "open" else (
            "blocked_retry" if retry else "blocked"
        )
        self._blocked_active = True
        await self._record(RULE_LOCK, reason, "blocked")
        await self._notifier.async_send(
            _fmt(lang[key], name=self._name), kind="blocked"
        )

    async def _async_verify(self, action: str, target: str) -> None:
        state = self.hass.states.get(self._opt(CONF_LOCK))
        current = state.state if state else STATE_UNAVAILABLE
        if current == target:
            return
        lang = _lang(self.hass)
        if self.last_action:
            self.last_action = {**self.last_action, "result": "failed"}
            await self._async_save()
        await self._notifier.async_send(
            _fmt(lang["failed"], name=self._name, target=lang[target], state=current),
            kind="failed",
        )

    # --- Schloss: manuelle Bedienung -----------------------------------------

    async def _on_lock_change(self, event: Event) -> None:
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        if new is None or old is None or new.state == old.state:
            return
        if new.state not in (LOCKED, UNLOCKED) or old.state in _IGNORED_STATES:
            return
        if self._own_target == new.state and time.monotonic() < self._own_until:
            self._own_target = None
            return
        if new.state == LOCKED:
            self._pending_lock = None
        if self._opt(CONF_MANUAL_OVERRIDE) == MANUAL_PAUSE:
            minutes = float(
                self._opt(CONF_MANUAL_PAUSE_MINUTES, DEFAULT_MANUAL_PAUSE_MINUTES)
            )
            self.paused_until = dt_util.utcnow() + timedelta(minutes=minutes)
            self._schedule_pause_end()
            await self._record(
                RULE_LOCK if new.state == LOCKED else RULE_UNLOCK,
                "manual",
                "manual_pause",
            )

    def _schedule_pause_end(self) -> None:
        self._cancel_timer("pause_end")
        if not self.paused_until:
            return
        remaining = (self.paused_until - dt_util.utcnow()).total_seconds()

        async def _end() -> None:
            self.paused_until = None
            await self._async_save()

        self._set_timer("pause_end", remaining, _end)

    # --- Türkontakt ----------------------------------------------------------------

    def _start_open_timer_from_current_state(self) -> None:
        contact = self.hass.states.get(self._opt(CONF_CONTACT))
        if contact is None or contact.state != STATE_ON:
            return
        alert = float(self._opt(CONF_OPEN_ALERT_MINUTES, DEFAULT_OPEN_ALERT_MINUTES))
        if alert <= 0:
            return
        elapsed = (dt_util.utcnow() - contact.last_changed).total_seconds()
        self._set_timer("open", alert * 60 - elapsed, self._async_open_alert)

    async def _async_open_alert(self) -> None:
        if self._contact_state() != STATE_ON:
            return
        contact = self.hass.states.get(self._opt(CONF_CONTACT))
        alert = int(float(self._opt(CONF_OPEN_ALERT_MINUTES, DEFAULT_OPEN_ALERT_MINUTES)))
        minutes = alert
        if contact is not None:
            minutes = max(
                alert,
                int((dt_util.utcnow() - contact.last_changed).total_seconds() // 60),
            )
        self.open_too_long = True
        self._notify_dispatch()
        await self._notifier.async_send(
            _fmt(_lang(self.hass)["open_too_long"], name=self._name, minutes=minutes),
            kind="open",
        )
        repeat = float(self._opt(CONF_OPEN_ALERT_REPEAT, DEFAULT_OPEN_ALERT_REPEAT))
        if repeat > 0:
            self._set_timer("open", repeat * 60, self._async_open_alert)

    async def _on_contact_change(self, event: Event) -> None:
        new = event.data.get("new_state")
        if new is None:
            return
        if new.state == STATE_ON:
            for rule in self._rules():
                if rule.get(R_TRIGGER) == TRIGGER_DOOR_CLOSED:
                    self._cancel_timer(f"closed_{rule.get(R_ID)}")
            alert = float(self._opt(CONF_OPEN_ALERT_MINUTES, DEFAULT_OPEN_ALERT_MINUTES))
            if alert > 0:
                self._set_timer("open", alert * 60, self._async_open_alert)
        elif new.state == STATE_OFF:
            self._cancel_timer("open")
            if self.open_too_long:
                self.open_too_long = False
                self._notify_dispatch()
                await self._notifier.async_clear("open")
            for rule in self._rules():
                if rule.get(R_TRIGGER) == TRIGGER_DOOR_CLOSED:
                    self._schedule_door_closed(rule)
            if self._pending_lock and dt_util.utcnow() < self._pending_lock:
                self._pending_lock = None
                await self.async_run_action(RULE_LOCK, "retry")

    def _schedule_door_closed(self, rule: dict[str, Any]) -> None:
        async def _later() -> None:
            await self.async_run_action(rule[R_ACTION], "door_closed")

        self._set_timer(
            f"closed_{rule.get(R_ID)}", float(rule.get(R_DELAY) or 0), _later
        )
