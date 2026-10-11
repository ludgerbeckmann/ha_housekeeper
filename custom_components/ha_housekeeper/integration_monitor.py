"""Logik der Funktion "Integrationsmonitor": Störungen von Integrationen melden und behandeln."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryDisabler, ConfigEntryState
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHECK_MINUTES,
    CONF_EXCLUDED,
    CONF_GRACE_MINUTES,
    CONF_MIN_ENTITIES,
    CONF_MONITOR_RULES,
    CONF_NOTIFY_ALL,
    CONF_NOTIFY_ERRORS,
    CONF_NOTIFY_UNAVAILABLE,
    CONF_SUMMARY_MINUTES,
    DEFAULT_CHECK_MINUTES,
    DEFAULT_GRACE_MINUTES,
    DEFAULT_MIN_ENTITIES,
    DEFAULT_SUMMARY_MINUTES,
    DOMAIN,
    M_ACTION,
    M_ENABLED,
    M_ENTRIES,
    M_ID,
    M_NOTIFY,
    M_ON_ERROR,
    M_ON_UNAVAILABLE,
    M_PRESENCE,
    M_REENABLE,
    MON_ACTION_DISABLE,
    MON_ACTION_RELOAD,
    signal_update,
)
from .notify import Notifier, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
START_DELAY = 120  # Sekunden nach dem Start, bis alle Integrationen geladen sind

KIND_ERROR = "error"
KIND_UNAVAILABLE = "unavailable"
STATUS_OK = "ok"

# Zustände eines Config-Entries, die einen Fehler der Integration bedeuten
ERROR_STATES = (
    ConfigEntryState.SETUP_ERROR,
    ConfigEntryState.SETUP_RETRY,
    ConfigEntryState.MIGRATION_ERROR,
    ConfigEntryState.FAILED_UNLOAD,
)
# Zustände einer Anwesenheitsentität, bei denen das Gerät als wieder da gilt
PRESENT_STATES = (STATE_ON, "home")

SUMMARY_KIND = "summary"

_TEXT = {
    "de": {
        KIND_ERROR: "Fehler ({state})",
        KIND_UNAVAILABLE: "alle {count} Entitäten nicht verfügbar",
        "header": "Gestörte Integrationen ({count}):",
        "line": "• {name} – {kind} (seit {since})",
        MON_ACTION_RELOAD: "neu geladen",
        MON_ACTION_DISABLE: "deaktiviert",
        "failed": "Aktion fehlgeschlagen",
        "spoken": "{count} Integrationen gestört.",
    },
    "en": {
        KIND_ERROR: "error ({state})",
        KIND_UNAVAILABLE: "all {count} entities unavailable",
        "header": "Faulty integrations ({count}):",
        "line": "• {name} – {kind} (since {since})",
        MON_ACTION_RELOAD: "reloaded",
        MON_ACTION_DISABLE: "disabled",
        "failed": "action failed",
        "spoken": "{count} integrations faulty.",
    },
}


def entry_status(hass: HomeAssistant, entry: ConfigEntry, min_entities: int) -> str | None:
    """Zustand einer Integration: Fehlerart, `ok` oder `None` (noch nicht beurteilbar).

    Deaktivierte Einträge und solche, die gerade laden oder entladen, sind nicht beurteilbar.
    „Nicht verfügbar“ gilt nur, wenn mindestens `min_entities` aktive Entitäten mit Zustand
    existieren und alle nicht verfügbar sind.
    """
    if entry.disabled_by is not None:
        return None
    if entry.state in ERROR_STATES:
        return KIND_ERROR
    if entry.state is not ConfigEntryState.LOADED:
        return None
    states = [
        state
        for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if entity.disabled_by is None and (state := hass.states.get(entity.entity_id)) is not None
    ]
    if len(states) >= max(1, min_entities) and all(s.state == STATE_UNAVAILABLE for s in states):
        return KIND_UNAVAILABLE
    return STATUS_OK


def count_entities(hass: HomeAssistant, entry: ConfigEntry) -> int:
    """Anzahl der aktiven Entitäten der Integration, die einen Zustand haben."""
    return sum(
        1
        for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if entity.disabled_by is None and hass.states.get(entity.entity_id) is not None
    )


def rule_matches(rule: dict[str, Any], entry_id: str, kind: str) -> bool:
    """Gilt die (aktive) Regel für diese Integration und Fehlerart?"""
    if not rule.get(M_ENABLED, True) or entry_id not in (rule.get(M_ENTRIES) or []):
        return False
    key = M_ON_ERROR if kind == KIND_ERROR else M_ON_UNAVAILABLE
    return bool(rule.get(key, True))


class IntegrationMonitorController:
    """Überwacht alle Integrationen und führt die Regeln für ausgewählte aus."""

    model = "Integrationsmonitor"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        # bestätigte Störungen: Integration -> {"kind", "acted", "reported", "since", "entities",
        # "state", "result"}; `reported` = steht in der Sammelmeldung
        self.faults: dict[str, dict[str, Any]] = {}
        # Sammelmeldung: zuletzt gesendeter Inhalt und seit wann eine Änderung wartet
        self.summary: dict[str, Any] = {"sent": [], "pending": None}
        self._names: dict[str, str] = {}
        # vom Monitor deaktivierte Integrationen: Integration -> ID der Regel
        self.disabled: dict[str, str] = {}
        self._since: dict[str, tuple[str, datetime]] = {}
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list[CALLBACK_TYPE] = []
        self._checking = False

    # --- Einstellungen -------------------------------------------------------

    def _opt(self, key: str, default: Any = None) -> Any:
        return self._get(key, default)

    @property
    def rules(self) -> list[dict[str, Any]]:
        return list(self._opt(CONF_MONITOR_RULES, []) or [])

    @property
    def grace(self) -> timedelta:
        return timedelta(minutes=float(self._opt(CONF_GRACE_MINUTES, DEFAULT_GRACE_MINUTES)))

    @property
    def min_entities(self) -> int:
        return int(self._opt(CONF_MIN_ENTITIES, DEFAULT_MIN_ENTITIES))

    @property
    def excluded(self) -> list[str]:
        return list(self._opt(CONF_EXCLUDED, []) or [])

    def _text(self) -> dict[str, str]:
        return _TEXT["de" if (self.hass.config.language or "").startswith("de") else "en"]

    def _title(self, entry_id: str) -> str:
        entry = self.hass.config_entries.async_get_entry(entry_id)
        return entry.title if entry else entry_id

    def _notifier(self) -> Notifier:
        return Notifier(
            self.hass, self._get, f"{DOMAIN}_{self.entry.entry_id}", lambda: self.entry.title
        )

    @property
    def summary_delay(self) -> timedelta:
        return timedelta(minutes=float(self._opt(CONF_SUMMARY_MINUTES, DEFAULT_SUMMARY_MINUTES)))

    def _wants_report(self, kind: str, eid: str, matching: list[dict[str, Any]]) -> bool:
        """Soll diese Störung in die Sammelmeldung? Globaler Schalter je Art oder Regel mit „Melden“."""
        key = CONF_NOTIFY_ERRORS if kind == KIND_ERROR else CONF_NOTIFY_UNAVAILABLE
        value = self._opt(key)
        if value is None:  # ältere Einstellung: ein Schalter für beide Arten
            value = self._opt(CONF_NOTIFY_ALL, True)
        return bool((value and eid not in self.excluded) or any(r.get(M_NOTIFY) for r in matching))

    @property
    def faulty_titles(self) -> list[str]:
        """Integrationen mit bestätigter Störung (ohne die vom Monitor deaktivierten)."""
        return [self._title(i) for i in self.faults if i not in self.disabled]

    @property
    def disabled_titles(self) -> list[str]:
        return [self._title(i) for i in self.disabled]

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.enabled = bool(stored.get("enabled", True))
        self.faults = dict(stored.get("faults") or {})
        self.disabled = dict(stored.get("disabled") or {})
        self.summary = dict(stored.get("summary") or self.summary)
        for fault in self.faults.values():  # ältere Einträge: `notified` hieß später `reported`
            fault.setdefault("reported", fault.get("notified", False))
        if "summary" not in stored and self.faults:
            # Update von Einzelmeldungen: die alten Meldungen je Integration entfernen
            self.hass.async_create_task(self._async_clear_legacy(list(self.faults)))

        async def _tick(_now: datetime) -> None:
            await self.async_check()

        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                _tick,
                timedelta(minutes=float(self._opt(CONF_CHECK_MINUTES, DEFAULT_CHECK_MINUTES))),
            )
        )
        self._unsubs.append(async_call_later(self.hass, START_DELAY, _tick))
        presence = list(
            dict.fromkeys(
                r[M_PRESENCE] for r in self.rules if r.get(M_PRESENCE) and r.get(M_REENABLE)
            )
        )
        if presence:
            self._unsubs.append(
                async_track_state_change_event(self.hass, presence, self._on_presence)
            )

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "enabled": self.enabled,
                "faults": self.faults,
                "disabled": self.disabled,
                "summary": self.summary,
            }
        )
        self._notify()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self._async_save()

    # --- Prüfung -------------------------------------------------------------

    @callback
    def _on_presence(self, event: Event) -> None:
        self.hass.async_create_task(self._async_reenable_present())

    async def async_check(self) -> None:
        """Alle Integrationen prüfen, Störungen bestätigen/behandeln, Rückkehr melden."""
        if not self.enabled or self._checking:
            return
        self._checking = True
        try:
            await self._async_check()
        finally:
            self._checking = False

    async def _async_check(self) -> None:
        now = dt_util.utcnow()
        entries = {
            e.entry_id: e for e in self.hass.config_entries.async_entries() if e.domain != DOMAIN
        }
        status = {
            eid: entry_status(self.hass, e, self.min_entities) for eid, e in entries.items()
        }
        current = {eid: s for eid, s in status.items() if s in (KIND_ERROR, KIND_UNAVAILABLE)}

        for eid in list(self._since):
            if current.get(eid) != self._since[eid][0]:
                del self._since[eid]
        for eid, kind in current.items():
            self._since.setdefault(eid, (kind, now))

        changed = False
        # Aufräumen: gelöschte Einträge und von Hand wieder aktivierte Integrationen
        for eid in list(self.disabled):
            entry = entries.get(eid) or self.hass.config_entries.async_get_entry(eid)
            if entry is None or entry.disabled_by is None:
                del self.disabled[eid]
                self.faults.pop(eid, None)
                changed = True
        for eid in list(self.faults):
            if eid not in entries and eid not in self.disabled:
                del self.faults[eid]
                changed = True

        for eid, kind in current.items():
            if now - self._since[eid][1] < self.grace:
                continue
            fault = self.faults.get(eid)
            if fault is None or fault["kind"] != kind:
                entry = entries[eid]
                fault = {
                    "kind": kind,
                    "acted": False,
                    "reported": False,
                    "since": self._since[eid][1].isoformat(),
                    "entities": count_entities(self.hass, entry),
                    "state": entry.state.value,
                    "result": None,
                }
                self.faults[eid] = fault
                changed = True
            if not fault["acted"]:
                await self._async_handle_fault(eid, entries[eid], fault)
                changed = True

        for eid in list(self.faults):
            if status.get(eid) == STATUS_OK and eid not in self.disabled:
                del self.faults[eid]
                changed = True

        changed |= await self._async_reenable_present(save=False)
        changed |= await self._async_flush_summary(now)
        if changed:
            await self._async_save()
        else:
            self._notify()

    async def _async_handle_fault(
        self, eid: str, entry: ConfigEntry, fault: dict[str, Any]
    ) -> None:
        """Neue Störung: passende Regeln ausführen und melden."""
        kind = fault["kind"]
        matching = [r for r in self.rules if rule_matches(r, eid, kind)]
        action = None
        rule = None
        for candidate in matching:
            value = candidate.get(M_ACTION)
            if value == MON_ACTION_DISABLE or (value == MON_ACTION_RELOAD and action is None):
                action, rule = value, candidate
        fault["acted"] = True
        if action == MON_ACTION_DISABLE:
            ok = await self._async_set_disabled(eid, True, rule[M_ID])
        elif action == MON_ACTION_RELOAD:
            ok = await self._async_reload(eid)
        fault["result"] = None if action is None else (action if ok else "failed")
        fault["reported"] = self._wants_report(kind, eid, matching)

    async def _async_clear_legacy(self, entry_ids: list[str]) -> None:
        notifier = self._notifier()
        for eid in entry_ids:
            await notifier.async_clear(eid)
            await notifier.async_clear(f"{eid}_ok")

    async def _integration_name(self, domain: str) -> str:
        """Anzeigename der Integration („Shelly“), sonst die Domain."""
        if domain not in self._names:
            try:
                self._names[domain] = (await async_get_integration(self.hass, domain)).name
            except Exception:  # noqa: BLE001
                self._names[domain] = domain
        return self._names[domain]

    async def _fault_line(self, eid: str, fault: dict[str, Any]) -> str:
        text = self._text()
        entry = self.hass.config_entries.async_get_entry(eid)
        name = await self._integration_name(entry.domain) if entry else eid
        if entry and entry.title and entry.title.casefold() != name.casefold():
            name = f"{name}: {entry.title}"
        kind = text[fault["kind"]].format(
            state=fault.get("state", ""), count=fault.get("entities", 0)
        )
        since = dt_util.parse_datetime(fault.get("since") or "")
        line = text["line"].format(
            name=name,
            kind=kind,
            since=dt_util.as_local(since).strftime("%H:%M") if since else "?",
        )
        result = fault.get("result")
        return f"{line}; {text[result]}" if result else line

    async def _async_flush_summary(self, now: datetime) -> bool:
        """Sammelmeldung senden, wenn sich die Liste geändert hat und die Bündelungszeit um ist.

        Wird die Liste leer, verschwindet die Meldung sofort. Gibt zurück, ob sich Zustand
        geändert hat (zum Speichern)."""
        reported = {eid: f for eid, f in self.faults.items() if f.get("reported")}
        key = sorted(f"{eid}|{f['kind']}|{f.get('result') or ''}" for eid, f in reported.items())
        notifier = self._notifier()
        if key == self.summary.get("sent"):
            changed = self.summary.get("pending") is not None
            self.summary["pending"] = None
            return changed
        if not key:
            await notifier.async_clear(SUMMARY_KIND)
            self.summary = {"sent": [], "pending": None}
            return True
        pending = dt_util.parse_datetime(self.summary.get("pending") or "")
        if pending is None:
            pending = now
            self.summary["pending"] = now.isoformat()
        if now - pending < self.summary_delay:
            return True
        lines = [await self._fault_line(eid, f) for eid, f in reported.items()]
        lines.sort(key=str.casefold)
        text = self._text()
        message = "\n".join([text["header"].format(count=len(lines)), *lines])
        await notifier.async_send(
            message,
            kind=SUMMARY_KIND,
            spoken=text["spoken"].format(count=len(lines)),
        )
        self.summary = {"sent": key, "pending": None}
        return True

    async def _async_reload(self, eid: str) -> bool:
        try:
            await self.hass.config_entries.async_reload(eid)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Neuladen von %s fehlgeschlagen", self._title(eid))
            return False
        return True

    async def _async_set_disabled(self, eid: str, disable: bool, rule_id: str | None) -> bool:
        if disable:
            # nur ausdrücklich in einer Regel gewählte Integrationen werden deaktiviert
            self.disabled[eid] = rule_id or ""
        try:
            await self.hass.config_entries.async_set_disabled_by(
                eid, ConfigEntryDisabler.USER if disable else None
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Ändern des Aktivierungszustands von %s fehlgeschlagen", eid)
            if disable:
                self.disabled.pop(eid, None)
            return False
        return True

    # --- Wieder aktivieren -----------------------------------------------------

    def _present_ids(self) -> list[str]:
        """Vom Monitor deaktivierte Integrationen, deren Anwesenheitsentität „da“ meldet."""
        rules = {r.get(M_ID): r for r in self.rules}
        found = []
        for eid, rule_id in self.disabled.items():
            rule = rules.get(rule_id)
            if not rule or not rule.get(M_ENABLED, True) or not rule.get(M_REENABLE):
                continue
            presence = self.hass.states.get(rule.get(M_PRESENCE) or "")
            if presence is not None and presence.state in PRESENT_STATES:
                found.append(eid)
        return found

    async def _async_reenable_present(self, save: bool = True) -> bool:
        if not self.enabled:
            return False
        changed = False
        for eid in self._present_ids():
            changed |= await self._async_reenable(eid)
        if changed and save:
            await self._async_flush_summary(dt_util.utcnow())
            await self._async_save()
        return changed

    async def _async_reenable(self, eid: str) -> bool:
        """Eine vom Monitor deaktivierte Integration wieder aktivieren."""
        if eid not in self.disabled:
            return False
        if not await self._async_set_disabled(eid, False, None):
            return False
        self.disabled.pop(eid, None)
        self.faults.pop(eid, None)
        self._since.pop(eid, None)
        return True

    async def async_reenable_all(self) -> None:
        """Alle vom Monitor deaktivierten Integrationen wieder aktivieren (Button)."""
        for eid in list(self.disabled):
            await self._async_reenable(eid)
        await self._async_save()
