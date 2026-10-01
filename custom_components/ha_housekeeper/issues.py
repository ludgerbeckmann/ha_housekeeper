"""Reparaturhinweise: verwendete Entitäten oder Geräte, die es nicht mehr gibt.

Home Assistant zeigt sie unter *Einstellungen → Reparaturen*. Geprüft wird nur, ob eine
Referenz **nicht mehr existiert** (gelöscht oder umbenannt); „nicht verfügbar“ ist oft
vorübergehend und löst keinen Hinweis aus. Ein Hinweis verschwindet von selbst, sobald die
Referenz wieder stimmt.
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.util import slugify

from .const import (
    CONF_ALARMS,
    CONF_CONTACT,
    CONF_FUNCTION_TYPE,
    CONF_LOCK,
    CONF_MOBILE_TARGETS,
    CONF_PLAYER,
    CONF_POWER_ENTITY,
    CONF_HEATER_ENTITY,
    CONF_PROFILES,
    CONF_PUMP_ENTITY,
    CONF_RULES,
    CONF_SCHEDULES,
    CONF_SENSITIVITY_ENTITY,
    CONF_TEMP_ENTITY,
    CONF_SPEAKERS,
    CONF_TASKS,
    CONF_TRIGGER_ENTITY,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_VIBRATION_SENSOR,
    CONF_WORKDAY_SENSORS,
    DOMAIN,
    FUNCTION_ALARM,
    FUNCTION_DOOR_GUARD,
    FUNCTION_DOORBELL,
    FUNCTION_KNX_SONOS,
    FUNCTION_MAILBOX,
    FUNCTION_POOL,
    FUNCTION_TASK_PLANNER,
    FUNCTION_UPDATER,
)
from .notify import entry_opt

_LOGGER = logging.getLogger(__name__)

ENTITY_MISSING = "entity_missing"
DEVICE_MISSING = "device_missing"
EVENT_DELAY_SECONDS = 10    # nach Registry-Ereignissen kurz warten und zusammenfassen
GRACE_SECONDS = 300          # nach dem Start Zeit lassen, bis alle Integrationen geladen sind
CHECK_INTERVAL = timedelta(hours=1)

FUNCTION_NAMES = {
    FUNCTION_MAILBOX: ("Benachrichtigung Briefkasten", "Mailbox notification"),
    FUNCTION_DOOR_GUARD: ("Türwächter", "Door guard"),
    FUNCTION_DOORBELL: ("Türklingel", "Doorbell"),
    FUNCTION_POOL: ("Poolsteuerung", "Pool control"),
    FUNCTION_KNX_SONOS: ("KNX/Sonos-Connector", "KNX/Sonos connector"),
    FUNCTION_UPDATER: ("Home Assistant Updater", "Home Assistant Updater"),
    FUNCTION_TASK_PLANNER: ("Aufgabenplaner", "Task planner"),
    FUNCTION_ALARM: ("Wecker", "Alarm clock"),
}


def _listed(items: Any, *keys: str) -> list[str]:
    """Werte aus verschachtelten Listen einsammeln (`items` = Liste von Dicts)."""
    found: list[str] = []
    for item in items or []:
        for key in keys:
            value = item.get(key)
            if isinstance(value, list):
                found.extend(str(v) for v in value if v)
            elif value:
                found.append(str(value))
    return found


def collect_references(entry: ConfigEntry) -> tuple[list[str], list[str]]:
    """Verwendete Entitäten und Geräte (Companion-App-Push-Ziele) eines Eintrags."""
    opt = entry_opt(entry)
    function = entry.data.get(CONF_FUNCTION_TYPE)
    entities: list[str] = [str(opt(CONF_TTS_ENTITY) or ""), str(opt(CONF_TTS_PLAYER) or "")]
    if function == FUNCTION_MAILBOX:
        entities += [opt(CONF_VIBRATION_SENSOR), opt(CONF_SENSITIVITY_ENTITY)]
    elif function == FUNCTION_DOOR_GUARD:
        entities += [opt(CONF_LOCK), opt(CONF_CONTACT)]
        entities += _listed(opt(CONF_RULES, []), "entity_id")
    elif function == FUNCTION_DOORBELL:
        entities.append(opt(CONF_TRIGGER_ENTITY))
        profiles = opt(CONF_PROFILES, [])
        entities += _listed(profiles, "players", "tts_entity")
    elif function == FUNCTION_POOL:
        entities += [
            opt(CONF_PUMP_ENTITY), opt(CONF_POWER_ENTITY),
            opt(CONF_HEATER_ENTITY), opt(CONF_TEMP_ENTITY),
        ]
    elif function == FUNCTION_KNX_SONOS:
        speakers = opt(CONF_SPEAKERS, [])
        entities += _listed(speakers, CONF_PLAYER) if speakers else [opt(CONF_PLAYER)]
    elif function == FUNCTION_UPDATER:
        entities += _listed(opt(CONF_SCHEDULES, []), "targets")
        # Zeitpläne mit eigenen TTS-Einstellungen
        entities += _listed(opt(CONF_SCHEDULES, []), CONF_TTS_ENTITY, CONF_TTS_PLAYER)
    elif function == FUNCTION_TASK_PLANNER:
        for task in opt(CONF_TASKS, []) or []:
            entities += _listed(task.get("triggers"), "entity_id")
    elif function == FUNCTION_ALARM:
        entities += _listed(opt(CONF_ALARMS, []), "players")
        entities += [str(v) for v in opt(CONF_WORKDAY_SENSORS, []) or []]
    devices = [str(t) for t in opt(CONF_MOBILE_TARGETS, []) or []]
    if function == FUNCTION_UPDATER:
        devices += _listed(opt(CONF_SCHEDULES, []), CONF_MOBILE_TARGETS)
    if function == FUNCTION_DOORBELL:
        devices += _listed(opt(CONF_PROFILES, []), CONF_MOBILE_TARGETS)
    entities = list(dict.fromkeys(e for e in entities if e and "." in e))
    return entities, list(dict.fromkeys(d for d in devices if d))


def _entity_exists(hass: HomeAssistant, entity_id: str) -> bool:
    """Gibt es die Entität? Auch eine deaktivierte Entität der Registry zählt als vorhanden."""
    return (
        hass.states.get(entity_id) is not None
        or er.async_get(hass).async_get(entity_id) is not None
    )


def _device_exists(hass: HomeAssistant, reference: str) -> bool:
    """Geräte-ID (Geräteauswahl) oder älterer Dienstname (`mobile_app_<gerät>`)."""
    if dr.async_get(hass).async_get(reference) is not None:
        return True
    if reference.removeprefix("notify.").startswith("mobile_app_"):
        return hass.services.has_service("notify", reference.removeprefix("notify."))
    return False


def _issue_id(entry: ConfigEntry, kind: str, reference: str) -> str:
    return f"{entry.entry_id}_{kind}_{slugify(reference)}"


def _function_name(hass: HomeAssistant, entry: ConfigEntry) -> str:
    german, english = FUNCTION_NAMES.get(entry.data.get(CONF_FUNCTION_TYPE), ("", ""))
    return (german if (hass.config.language or "").startswith("de") else english) or entry.title


async def async_check_entry(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Hinweise des Eintrags abgleichen; liefert die IDs der aktuell offenen Hinweise."""
    if entry.state is not ConfigEntryState.LOADED:
        return []
    entities, devices = collect_references(entry)
    wanted: dict[str, tuple[str, str]] = {}
    for entity_id in entities:
        if not _entity_exists(hass, entity_id):
            wanted[_issue_id(entry, "entity", entity_id)] = (ENTITY_MISSING, entity_id)
    for reference in devices:
        if not _device_exists(hass, reference):
            wanted[_issue_id(entry, "device", reference)] = (DEVICE_MISSING, reference)

    registry = ir.async_get(hass)
    prefix = f"{entry.entry_id}_"
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN and issue_id.startswith(prefix) and issue_id not in wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
    for issue_id, (key, reference) in wanted.items():
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders={
                "entry": entry.title,
                "function": _function_name(hass, entry),
                "entity": reference,
            },
        )
    return list(wanted)


def async_remove_entry_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Alle Hinweise eines gelöschten Eintrags entfernen."""
    prefix = f"{entry.entry_id}_"
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN and issue_id.startswith(prefix):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def _entity_event_filter(data: Any) -> bool:
    """Entität entfernt oder umbenannt (die gespeicherte ID stimmt dann nicht mehr)."""
    return data["action"] == "remove" or (
        data["action"] == "update" and "entity_id" in (data.get("changes") or {})
    )


@callback
def _device_event_filter(data: Any) -> bool:
    return data["action"] == "remove"


@callback
def async_setup_checks(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Prüfungen einrichten: nach dem Start, stündlich und bei Entfernen/Umbenennen."""

    @callback
    def _run(*_args: Any) -> None:
        hass.async_create_task(async_check_entry(hass, entry))

    pending: list[CALLBACK_TYPE] = []

    @callback
    def _cancel_pending() -> None:
        while pending:
            pending.pop()()

    @callback
    def _run_soon(*_args: Any) -> None:
        """Nach Registry-Ereignissen kurz warten (der alte Zustand wird erst danach entfernt)
        und mehrere Ereignisse zu einer Prüfung zusammenfassen."""
        _cancel_pending()
        pending.append(async_call_later(hass, EVENT_DELAY_SECONDS, _run))

    entry.async_on_unload(_cancel_pending)
    entry.async_on_unload(async_track_time_interval(hass, _run, CHECK_INTERVAL))
    entry.async_on_unload(
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, _run_soon, event_filter=_entity_event_filter
        )
    )
    entry.async_on_unload(
        hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED, _run_soon, event_filter=_device_event_filter
        )
    )

    @callback
    def _first_check(_hass: HomeAssistant) -> None:
        # nach dem Start eine Schonfrist, bis alle Integrationen ihre Entitäten geladen haben
        entry.async_on_unload(async_call_later(hass, GRACE_SECONDS, _run))

    async_at_started(hass, _first_check)
