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
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHECK_MINUTES,
    CONF_EXCLUDED,
    CONF_GRACE_MINUTES,
    CONF_MIN_ENTITIES,
    CONF_MONITOR_RULES,
    CONF_NOTIFY_ALL,
    DEFAULT_CHECK_MINUTES,
    DEFAULT_GRACE_MINUTES,
    DEFAULT_MIN_ENTITIES,
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

_TEXT = {
    "de": {
        KIND_ERROR: "meldet einen Fehler (Status: {state})",
        KIND_UNAVAILABLE: "alle Entitäten sind nicht verfügbar",
        "fault": "Integration „{title}“: {kind}.",
        MON_ACTION_RELOAD: "Sie wurde neu geladen.",
        MON_ACTION_DISABLE: "Sie wurde deaktiviert.",
        "failed": "Die Aktion ist fehlgeschlagen.",
        "recovered": "Integration „{title}“ läuft wieder.",
        "reenabled": "Integration „{title}“ wurde wieder aktiviert.",
    },
    "en": {
        KIND_ERROR: "reports an error (state: {state})",
        KIND_UNAVAILABLE: "all entities are unavailable",
        "fault": "Integration \"{title}\": {kind}.",
        MON_ACTION_RELOAD: "It was reloaded.",
        MON_ACTION_DISABLE: "It was disabled.",
        "failed": "The action failed.",
        "recovered": "Integration \"{title}\" is working again.",
        "reenabled": "Integration \"{title}\" was enabled again.",
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
        # bestätigte Störungen: Integration -> {"kind", "acted", "notified"}
        self.faults: dict[str, dict[str, Any]] = {}
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
            {"enabled": self.enabled, "faults": self.faults, "disabled": self.disabled}
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
                fault = {"kind": kind, "acted": False, "notified": False}
                self.faults[eid] = fault
                changed = True
            if not fault["acted"]:
                await self._async_handle_fault(eid, entries[eid], fault)
                changed = True

        for eid in list(self.faults):
            if status.get(eid) == STATUS_OK and eid not in self.disabled:
                fault = self.faults.pop(eid)
                changed = True
                if fault.get("notified"):
                    await self._async_notify_recovered(eid)

        changed |= await self._async_reenable_present(save=False)
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
        failed = False
        if action == MON_ACTION_DISABLE:
            failed = not await self._async_set_disabled(eid, True, rule[M_ID])
        elif action == MON_ACTION_RELOAD:
            failed = not await self._async_reload(eid)

        notify = (self._opt(CONF_NOTIFY_ALL, True) and eid not in self.excluded) or any(
            r.get(M_NOTIFY) for r in matching
        )
        if not notify:
            return
        text = self._text()
        message = text["fault"].format(
            title=entry.title, kind=text[kind].format(state=entry.state.value)
        )
        if action:
            message += f" {text['failed'] if failed else text[action]}"
        fault["notified"] = True
        await self._notifier().async_send(message, kind=eid)

    async def _async_notify_recovered(self, eid: str) -> None:
        notifier = self._notifier()
        await notifier.async_clear(eid)
        await notifier.async_send(
            self._text()["recovered"].format(title=self._title(eid)), kind=f"{eid}_ok"
        )

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
            await self._async_save()
        return changed

    async def _async_reenable(self, eid: str) -> bool:
        """Eine vom Monitor deaktivierte Integration wieder aktivieren."""
        rule_id = self.disabled.get(eid)
        if rule_id is None:
            return False
        if not await self._async_set_disabled(eid, False, None):
            return False
        self.disabled.pop(eid, None)
        self.faults.pop(eid, None)
        self._since.pop(eid, None)
        rule = next((r for r in self.rules if r.get(M_ID) == rule_id), None)
        if (self._opt(CONF_NOTIFY_ALL, True) and eid not in self.excluded) or (
            rule and rule.get(M_NOTIFY)
        ):
            await self._notifier().async_clear(eid)
            await self._notifier().async_send(
                self._text()["reenabled"].format(title=self._title(eid)), kind=f"{eid}_ok"
            )
        return True

    async def async_reenable_all(self) -> None:
        """Alle vom Monitor deaktivierten Integrationen wieder aktivieren (Button)."""
        for eid in list(self.disabled):
            await self._async_reenable(eid)
        await self._async_save()
