"""Home Assistant Hausmeister - Integration für verschiedene Smart-Home-Anwendungsfälle."""

from __future__ import annotations

import inspect
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryError, ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_DURATION,
    ATTR_ENTRY_ID,
    CONF_FUNCTION_TYPE,
    CONF_HUB,
    DOMAIN,
    FUNCTION_ALARM,
    FUNCTION_DOOR_GUARD,
    FUNCTION_DOORBELL,
    FUNCTION_KNX_SONOS,
    FUNCTION_MAILBOX,
    FUNCTION_MONITOR,
    FUNCTION_POOL,
    FUNCTION_TASK_PLANNER,
    FUNCTION_UPDATER,
    FUNCTION_PLATFORMS,
    instance_name,
    instance_title,
    SERVICE_RUN_PUMP,
)
from .alarm_clock import AlarmClockController
from .issues import async_remove_issues_with_prefix, async_setup_checks
from .door_guard import DoorGuardController
from .doorbell import DoorbellController
from .integration_monitor import IntegrationMonitorController
from .knx_sonos import KnxSonosController
from .mailbox import MailboxController
from .pool_pump import PoolPumpController
from .subentry import SubentryEntry, any_busy, hub_controllers
from .task_planner import TaskPlannerController
from .updater import UpdaterController

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Registry: Funktionstyp -> Controller-Klasse
CONTROLLERS = {
    FUNCTION_MAILBOX: MailboxController,
    FUNCTION_DOOR_GUARD: DoorGuardController,
    FUNCTION_DOORBELL: DoorbellController,
    FUNCTION_POOL: PoolPumpController,
    FUNCTION_KNX_SONOS: KnxSonosController,
    FUNCTION_UPDATER: UpdaterController,
    FUNCTION_TASK_PLANNER: TaskPlannerController,
    FUNCTION_ALARM: AlarmClockController,
    FUNCTION_MONITOR: IntegrationMonitorController,
}

RUN_PUMP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DURATION): vol.All(vol.Coerce(float), vol.Range(min=1, max=1440)),
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Dienste registrieren."""
    hass.data.setdefault(DOMAIN, {})

    async def _run_pump(call: ServiceCall) -> None:
        controllers = hass.data[DOMAIN]
        pools = {
            entry_id: c
            for entry_id, c in controllers.items()
            if isinstance(c, PoolPumpController)
        }
        entry_id = call.data.get(ATTR_ENTRY_ID)
        if entry_id is not None:
            if entry_id not in pools:
                raise ServiceValidationError(f"Unbekannte Poolpumpe: {entry_id}")
            targets = [pools[entry_id]]
        else:
            targets = list(pools.values())
        for pool in targets:
            await pool.async_run_pump(call.data[ATTR_DURATION])

    hass.services.async_register(
        DOMAIN, SERVICE_RUN_PUMP, _run_pump, schema=RUN_PUMP_SCHEMA
    )
    return True


ALL_PLATFORMS = sorted({p for platforms in FUNCTION_PLATFORMS.values() for p in platforms})


def _is_hub(entry: ConfigEntry) -> bool:
    """Aktuelles Format: ein Hub („Funktionen“) mit allen Instanzen als Untereinträge.

    Ältere Einträge (eine Instanz je Eintrag, später ein Hub je Funktion mit `function_type`)
    werden nicht mehr geladen."""
    return bool(entry.data.get(CONF_HUB)) and CONF_FUNCTION_TYPE not in entry.data


def _normalize_titles(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Titel der Untereinträge auf „Funktion: Name“ bringen (z. B. nach einem Umbenennen)."""
    for subentry in list(entry.subentries.values()):
        expected = instance_title(
            hass, subentry.subentry_type, instance_name(subentry.title)
        )
        if subentry.title != expected:
            hass.config_entries.async_update_subentry(entry, subentry, title=expected)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Hub einrichten: je Untereintrag ein Controller, dazu die Plattformen."""
    if not _is_hub(entry):
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"legacy_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="legacy_entry",
            translation_placeholders={"entry": entry.title},
        )
        raise ConfigEntryError(
            f"{entry.title}: älteres Eintragsformat, bitte löschen und neu anlegen"
        )
    ir.async_delete_issue(hass, DOMAIN, f"legacy_{entry.entry_id}")

    _normalize_titles(hass, entry)
    controllers = hass.data.setdefault(DOMAIN, {})
    adapters: list[SubentryEntry] = []
    for subentry in entry.subentries.values():
        adapter = SubentryEntry(entry, subentry)
        controller = CONTROLLERS[subentry.subentry_type](hass, adapter)
        await controller.async_start()
        controllers[subentry.subentry_id] = controller
        adapters.append(adapter)

    await hass.config_entries.async_forward_entry_setups(entry, ALL_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    async_setup_checks(hass, entry, adapters)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Hub nach einer Änderung neu laden, aber nicht mitten in einem Lauf."""
    controllers = hub_controllers(hass, entry)
    if any_busy(hass, entry):
        for controller in controllers:
            controller.reload_requested = True
        _LOGGER.info(
            "%s: Änderungen werden übernommen, sobald der laufende Vorgang beendet ist",
            entry.title,
        )
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Hub entladen."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, ALL_PLATFORMS)
    if unloaded:
        # alle Controller dieses Hubs (auch die eines inzwischen entfernten Untereintrags)
        controllers = hass.data[DOMAIN]
        for subentry_id in [
            sid for sid, c in controllers.items() if c.entry.hub_entry_id == entry.entry_id
        ]:
            controller = controllers.pop(subentry_id)
            result = controller.async_stop()
            if inspect.isawaitable(result):
                await result
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Gespeicherten Zustand und Reparaturhinweise aller Untereinträge entfernen."""
    ir.async_delete_issue(hass, DOMAIN, f"legacy_{entry.entry_id}")
    for subentry_id in entry.subentries:
        async_remove_issues_with_prefix(hass, f"{subentry_id}_")
        await Store(hass, 1, f"{DOMAIN}.{subentry_id}").async_remove()

