"""Home Assistant Hausmeister - Integration für verschiedene Smart-Home-Anwendungsfälle."""

from __future__ import annotations

import inspect
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_DURATION,
    ATTR_ENTRY_ID,
    CONF_FUNCTION_TYPE,
    DOMAIN,
    FUNCTION_ALARM,
    FUNCTION_DOOR_GUARD,
    FUNCTION_DOORBELL,
    FUNCTION_KNX_SONOS,
    FUNCTION_MAILBOX,
    FUNCTION_POOL,
    FUNCTION_TASK_PLANNER,
    FUNCTION_UPDATER,
    FUNCTION_PLATFORMS,
    SERVICE_RUN_PUMP,
)
from .alarm_clock import AlarmClockController
from .issues import async_remove_entry_issues, async_setup_checks
from .door_guard import DoorGuardController
from .doorbell import DoorbellController
from .knx_sonos import KnxSonosController
from .mailbox import MailboxController
from .pool_pump import PoolPumpController
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Eintrag einrichten - je nach Funktionstyp."""
    function_type = entry.data[CONF_FUNCTION_TYPE]
    controller = CONTROLLERS[function_type](hass, entry)
    await controller.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller

    await hass.config_entries.async_forward_entry_setups(
        entry, FUNCTION_PLATFORMS[function_type]
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    async_setup_checks(hass, entry)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Eintrag nach einer Änderung neu laden, aber nicht mitten in einem Lauf."""
    controller = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if controller is not None and getattr(controller, "busy", False):
        controller.reload_requested = True
        _LOGGER.info(
            "%s: Änderungen werden übernommen, sobald der laufende Vorgang beendet ist",
            entry.title,
        )
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Eintrag entladen."""
    function_type = entry.data[CONF_FUNCTION_TYPE]
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, FUNCTION_PLATFORMS[function_type]
    )
    if unloaded:
        controller = hass.data[DOMAIN].pop(entry.entry_id, None)
        if controller:
            result = controller.async_stop()
            if inspect.isawaitable(result):
                await result
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Gespeicherten Zustand und Reparaturhinweise beim Löschen entfernen."""
    async_remove_entry_issues(hass, entry)
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
