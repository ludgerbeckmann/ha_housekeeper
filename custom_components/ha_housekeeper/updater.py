"""Logik der Funktion "Updater": Updates zeitgesteuert melden oder installieren."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SCHEDULES,
    CONF_TIMEOUT_MINUTES,
    DEFAULT_TIMEOUT_MINUTES,
    DOMAIN,
    U_BACKUP,
    U_ID,
    U_MODE,
    U_NAME,
    U_TARGETS,
    U_TIME,
    U_WEEKDAYS,
    UPDATE_MODE_INSTALL,
    WEEKDAYS,
    signal_update,
)
from .notify import Notifier, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
_UNKNOWN = (STATE_UNAVAILABLE, STATE_UNKNOWN)

# Home Assistant OS: Update-Entitäten des Systems. Supervisor, Core und OS stehen
# immer am Ende; Core und OS starten Home Assistant bzw. den Host neu.
SUPERVISOR_ID = "update.home_assistant_supervisor_update"
CORE_ID = "update.home_assistant_core_update"
OS_ID = "update.home_assistant_operating_system_update"
CRITICAL_ORDER = (SUPERVISOR_ID, CORE_ID, OS_ID)
RESTARTING = (CORE_ID, OS_ID)

FEATURE_BACKUP = 8  # UpdateEntityFeature.BACKUP

POLL_SECONDS = 2.0        # Abfrage, ob eine Version übernommen wurde
SETTLE_SECONDS = 120.0    # so lange auf die neue Version warten
FINALIZE_DELAY = 60       # Sekunden nach dem Start bis zur Nachmeldung
FINALIZE_ATTEMPTS = 10

ST_INSTALLED = "installed"
ST_FAILED = "failed"
ST_SKIPPED = "skipped"
ST_DEFERRED = "deferred"

_TEXT = {
    "de": {
        "available": "Updates verfügbar",
        "none": "Keine Updates verfügbar.",
        "start": "Update-Lauf „{name}“ gestartet",
        "done": "Update-Lauf „{name}“ beendet",
        "installed": "installiert",
        "failed": "fehlgeschlagen",
        "skipped": "übersprungen (vorheriger Fehler)",
        "deferred": "verschoben auf den nächsten Lauf (nur ein Neustart pro Lauf)",
        "timeout": "Zeitüberschreitung",
        "not_applied": "Version nicht übernommen",
        "unknown_after_restart": "Ergebnis unbekannt (Entität nicht verfügbar)",
        "now": "aktuell",
    },
    "en": {
        "available": "Updates available",
        "none": "No updates available.",
        "start": "Update run \"{name}\" started",
        "done": "Update run \"{name}\" finished",
        "installed": "installed",
        "failed": "failed",
        "skipped": "skipped (earlier failure)",
        "deferred": "deferred to the next run (only one restart per run)",
        "timeout": "timed out",
        "not_applied": "version not applied",
        "unknown_after_restart": "result unknown (entity unavailable)",
        "now": "currently",
    },
}


def _log_task_result(task: asyncio.Future) -> None:
    """Ergebnis einer nach Zeitüberschreitung weiterlaufenden Installation protokollieren."""
    if not task.cancelled() and (err := task.exception()) is not None:
        _LOGGER.warning("Weiterlaufende Installation fehlgeschlagen: %s", err)


def order_targets(entity_ids: list[str]) -> list[str]:
    """Reihenfolge wie gewählt; Supervisor, Core und OS (in dieser Reihenfolge) zuletzt."""
    normal = [e for e in entity_ids if e not in CRITICAL_ORDER]
    critical = [e for e in CRITICAL_ORDER if e in entity_ids]
    return normal + critical


def next_run(schedules: list[dict[str, Any]], now: datetime) -> datetime | None:
    """Nächster Startzeitpunkt aller Zeitpläne nach `now` (lokale Zeit)."""
    best: datetime | None = None
    for schedule in schedules:
        at = dt_util.parse_time(str(schedule.get(U_TIME, "")))
        if at is None:
            continue
        days = schedule.get(U_WEEKDAYS) or WEEKDAYS
        for offset in range(8):
            day = now + timedelta(days=offset)
            if WEEKDAYS[day.weekday()] not in days:
                continue
            candidate = day.replace(
                hour=at.hour, minute=at.minute, second=at.second, microsecond=0
            )
            if candidate > now and (best is None or candidate < best):
                best = candidate
    return best


def schedule_summary(hass: HomeAssistant, schedule: dict[str, Any]) -> str:
    """Kurzbeschreibung eines Zeitplans für Listen im Options-Flow."""
    german = (hass.config.language or "").startswith("de")
    days = schedule.get(U_WEEKDAYS) or WEEKDAYS
    day_text = "" if len(days) == 7 else f" ({', '.join(days)})"
    mode = schedule.get(U_MODE)
    if german:
        mode_text = "installieren" if mode == UPDATE_MODE_INSTALL else "melden"
        unit = "Updates"
    else:
        mode_text = "install" if mode == UPDATE_MODE_INSTALL else "notify"
        unit = "updates"
    return (
        f"{schedule.get(U_NAME)}: {str(schedule.get(U_TIME, ''))[:5]}{day_text}, "
        f"{len(schedule.get(U_TARGETS) or [])} {unit}, {mode_text}"
    )


class UpdaterController:
    """Führt die Update-Zeitpläne aus."""

    model = "Updater"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.last_run: dict[str, Any] | None = None
        self.pending: dict[str, Any] | None = None
        self._running = False
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._notifier = Notifier(
            hass, self._get, f"{DOMAIN}_{entry.entry_id}", lambda: entry.title
        )
        self._unsubs: list[CALLBACK_TYPE] = []
        self._finalize_unsub: CALLBACK_TYPE | None = None

    # --- Hilfen ------------------------------------------------------------

    def _opt(self, key: str, default: Any = None) -> Any:
        return self._get(key, default)

    def _text(self) -> dict[str, str]:
        return _TEXT["de" if (self.hass.config.language or "").startswith("de") else "en"]

    @property
    def schedules(self) -> list[dict[str, Any]]:
        return list(self._opt(CONF_SCHEDULES, []) or [])

    @property
    def running(self) -> bool:
        return self._running

    @property
    def next_run(self) -> datetime | None:
        return next_run(self.schedules, dt_util.now())

    def _target_ids(self) -> list[str]:
        seen: dict[str, None] = {}
        for schedule in self.schedules:
            for entity_id in schedule.get(U_TARGETS) or []:
                seen.setdefault(entity_id, None)
        return list(seen)

    def available_updates(self) -> list[str]:
        """Namen aller Ziel-Entitäten, für die gerade ein Update bereitsteht."""
        return [
            self._name(state)
            for entity_id in self._target_ids()
            if (state := self.hass.states.get(entity_id)) and state.state == STATE_ON
        ]

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "enabled": self.enabled,
                "last_run": self.last_run,
                "pending": self.pending,
            }
        )
        self._notify()

    @staticmethod
    def _name(state) -> str:
        attrs = state.attributes
        return str(attrs.get("title") or attrs.get("friendly_name") or state.entity_id)

    @staticmethod
    def _version_text(state) -> str:
        attrs = state.attributes
        old = attrs.get("installed_version")
        new = attrs.get("latest_version")
        return f"{old} → {new}" if old and new else ""

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.enabled = bool(stored.get("enabled", True))
        self.last_run = stored.get("last_run")
        self.pending = stored.get("pending")

        for schedule in self.schedules:
            at = dt_util.parse_time(str(schedule.get(U_TIME, "")))
            if at is None:
                _LOGGER.warning("Zeitplan %s: ungültige Uhrzeit", schedule.get(U_NAME))
                continue

            async def _trigger(now: datetime, schedule=schedule) -> None:
                days = schedule.get(U_WEEKDAYS) or WEEKDAYS
                if not self.enabled:
                    return
                if WEEKDAYS[dt_util.as_local(now).weekday()] in days:
                    self.hass.async_create_task(self.async_run_schedule(schedule))

            self._unsubs.append(
                async_track_time_change(
                    self.hass, _trigger, hour=at.hour, minute=at.minute, second=at.second
                )
            )
        if targets := self._target_ids():
            self._unsubs.append(
                async_track_state_change_event(self.hass, targets, self._on_target_change)
            )
        if self.pending:
            self._schedule_finalize(FINALIZE_DELAY, 0)

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._finalize_unsub:
            self._finalize_unsub()
            self._finalize_unsub = None

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self._async_save()

    @callback
    def _on_target_change(self, event: Event) -> None:
        self._notify()

    # --- Ausführung ------------------------------------------------------------

    async def async_check_now(self) -> None:
        """Alle Zeitpläne zusammen prüfen und das Ergebnis melden (nie installieren)."""
        union = {
            U_ID: "check",
            U_NAME: self.entry.title,
            U_TARGETS: self._target_ids(),
            U_MODE: "notify",
        }
        await self.async_run_schedule(union, force_notify=True)

    async def async_run_schedule(
        self, schedule: dict[str, Any], *, force_notify: bool = False
    ) -> None:
        if self._running:
            _LOGGER.warning("%s: Lauf „%s“ übersprungen, es läuft bereits einer",
                            self.entry.title, schedule.get(U_NAME))
            return
        self._running = True
        self._notify()
        try:
            await self._async_run(schedule, force_notify)
        finally:
            self._running = False
            self._notify()

    async def _async_run(self, schedule: dict[str, Any], force_notify: bool) -> None:
        text = self._text()
        candidates: list[str] = []
        for entity_id in schedule.get(U_TARGETS) or []:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state == STATE_ON:
                candidates.append(entity_id)

        mode = "notify" if force_notify else schedule.get(U_MODE)
        record: dict[str, Any] = {
            "time": dt_util.utcnow().isoformat(),
            "schedule": schedule.get(U_NAME),
            "mode": mode,
            "installed": 0,
            "failed": 0,
            "skipped": 0,
            "summary": "",
        }
        if not candidates:
            record["summary"] = text["none"]
            if force_notify:
                await self._notifier.async_send(text["none"], kind="run")
            self.last_run = record
            await self._async_save()
            return

        lines = [self._line(entity_id) for entity_id in candidates]
        if mode != UPDATE_MODE_INSTALL:
            message = f"{text['available']}:\n" + "\n".join(lines)
            record["summary"] = message
            await self._notifier.async_send(message, kind="run")
            self.last_run = record
            await self._async_save()
            return

        await self._notifier.async_send(
            f"{text['start'].format(name=schedule.get(U_NAME))}:\n" + "\n".join(lines),
            kind="run",
        )
        results = await self._async_install_all(
            schedule, order_targets(candidates), []
        )
        await self._async_finish(record, schedule.get(U_NAME), results)

    def _line(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        if state is None:
            return f"• {entity_id}"
        version = self._version_text(state)
        return f"• {self._name(state)}" + (f": {version}" if version else "")

    async def _async_install_all(
        self,
        schedule: dict[str, Any],
        ordered: list[str],
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        failed = any(r["status"] == ST_FAILED for r in results)
        restarted = False
        for entity_id in ordered:
            critical = entity_id in CRITICAL_ORDER
            state = self.hass.states.get(entity_id)
            base = {
                "entity": entity_id,
                "name": self._name(state) if state else entity_id,
                "from": state.attributes.get("installed_version") if state else None,
                "to": state.attributes.get("latest_version") if state else None,
            }
            if critical and failed:
                results.append({**base, "status": ST_SKIPPED})
                continue
            if entity_id in RESTARTING and restarted:
                results.append({**base, "status": ST_DEFERRED})
                continue
            result = await self._async_install(entity_id, base, schedule, results, ordered)
            results.append(result)
            failed = failed or result["status"] == ST_FAILED
            restarted = restarted or entity_id in RESTARTING
        return results

    async def _async_install(
        self,
        entity_id: str,
        base: dict[str, Any],
        schedule: dict[str, Any],
        results: list[dict[str, Any]],
        ordered: list[str],
    ) -> dict[str, Any]:
        if entity_id in RESTARTING:
            # Der Neustart beendet diesen Lauf: Zustand sichern, damit nach dem
            # Start das Ergebnis gemeldet werden kann.
            self.pending = {
                "schedule": schedule.get(U_NAME),
                "results": list(results),
                "current": base,
                "deferred": [e for e in ordered if e in RESTARTING and e != entity_id],
            }
            await self._async_save()

        state = self.hass.states.get(entity_id)
        data: dict[str, Any] = {"entity_id": entity_id}
        if (
            schedule.get(U_BACKUP)
            and state is not None
            and int(state.attributes.get("supported_features", 0)) & FEATURE_BACKUP
        ):
            data["backup"] = True

        timeout = float(self._opt(CONF_TIMEOUT_MINUTES, DEFAULT_TIMEOUT_MINUTES)) * 60
        text = self._text()
        error: str | None = None
        # Die Installation läuft als eigene Aufgabe und wird bei Zeitüberschreitung
        # nie abgebrochen (z. B. ein laufendes Flashen), der Lauf geht nur weiter.
        task = self.hass.async_create_task(
            self.hass.services.async_call("update", "install", data, blocking=True)
        )
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout)
        except TimeoutError:
            error = text["timeout"]
            task.add_done_callback(_log_task_result)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("%s: Installation von %s fehlgeschlagen", self.entry.title, entity_id)
            error = str(err) or type(err).__name__

        if error is None and not await self._async_wait_applied(entity_id, base["to"]):
            error = text["not_applied"]

        if entity_id in RESTARTING:
            self.pending = None
            await self._async_save()
        if error is not None:
            return {**base, "status": ST_FAILED, "error": error}
        return {**base, "status": ST_INSTALLED}

    async def _async_wait_applied(self, entity_id: str, expected: Any) -> bool:
        """Warten, bis die Entität die neue Version als installiert meldet."""
        waited = 0.0
        while True:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state not in _UNKNOWN:
                installed = state.attributes.get("installed_version")
                if expected is None or installed == expected or state.state != STATE_ON:
                    return True
            if waited >= SETTLE_SECONDS:
                return False
            await asyncio.sleep(POLL_SECONDS)
            waited += POLL_SECONDS

    # --- Bericht ----------------------------------------------------------------

    def _result_line(self, result: dict[str, Any]) -> str:
        text = self._text()
        status = result["status"]
        versions = (
            f": {result['from']} → {result['to']}"
            if result.get("from") and result.get("to")
            else ""
        )
        if status == ST_INSTALLED:
            return f"✔ {result['name']}{versions} ({text['installed']})"
        if status == ST_FAILED:
            return f"✖ {result['name']}{versions} ({text['failed']}: {result.get('error', '')})"
        return f"⏭ {result['name']} ({text[status]})"

    async def _async_finish(
        self, record: dict[str, Any], name: str | None, results: list[dict[str, Any]]
    ) -> None:
        text = self._text()
        record["installed"] = sum(r["status"] == ST_INSTALLED for r in results)
        record["failed"] = sum(r["status"] == ST_FAILED for r in results)
        record["skipped"] = sum(r["status"] in (ST_SKIPPED, ST_DEFERRED) for r in results)
        message = f"{text['done'].format(name=name)}:\n" + "\n".join(
            self._result_line(r) for r in results
        )
        record["summary"] = message
        self.last_run = record
        await self._async_save()
        await self._notifier.async_send(message, kind="run")

    # --- Nachmeldung nach einem Neustart --------------------------------------

    def _schedule_finalize(self, delay: float, attempt: int) -> None:
        async def _fire(_now: datetime) -> None:
            self._finalize_unsub = None
            await self._async_finalize_pending(attempt)

        self._finalize_unsub = async_call_later(self.hass, delay, _fire)

    async def _async_finalize_pending(self, attempt: int) -> None:
        pending = self.pending
        if not pending:
            return
        current = dict(pending["current"])
        state = self.hass.states.get(current["entity"])
        if (state is None or state.state in _UNKNOWN) and attempt < FINALIZE_ATTEMPTS:
            self._schedule_finalize(FINALIZE_DELAY, attempt + 1)
            return
        text = self._text()
        if state is None or state.state in _UNKNOWN:
            current.update(status=ST_FAILED, error=text["unknown_after_restart"])
        else:
            installed = state.attributes.get("installed_version")
            if current.get("to") is None or installed == current["to"]:
                current["status"] = ST_INSTALLED
            else:
                current.update(
                    status=ST_FAILED,
                    error=f"{text['not_applied']} ({text['now']} {installed})",
                )
        results = list(pending["results"]) + [current]
        for entity_id in pending.get("deferred", []):
            deferred_state = self.hass.states.get(entity_id)
            results.append(
                {
                    "entity": entity_id,
                    "name": self._name(deferred_state) if deferred_state else entity_id,
                    "from": None,
                    "to": None,
                    "status": ST_DEFERRED,
                }
            )
        record = {
            "time": dt_util.utcnow().isoformat(),
            "schedule": pending.get("schedule"),
            "mode": UPDATE_MODE_INSTALL,
            "installed": 0,
            "failed": 0,
            "skipped": 0,
            "summary": "",
        }
        self.pending = None
        await self._async_finish(record, pending.get("schedule"), results)
