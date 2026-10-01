"""Schalter der Funktionen (Türwächter, Türklingel, Poolpumpe, KNX/Sonos)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .alarm_clock import AlarmClockController
from .const import DOMAIN
from .doorbell import DoorbellController
from .entity import FunctionEntity
from .knx_sonos import KnxSonosController
from .mailbox import MailboxController
from .pool_pump import PoolPumpController
from .task_planner import TaskPlannerController
from .updater import UpdaterController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    if isinstance(controller, DoorbellController):
        async_add_entities([DoorbellActiveSwitch(controller)])
    elif isinstance(controller, PoolPumpController):
        async_add_entities([ScheduleEnabledSwitch(controller)])
    elif isinstance(controller, KnxSonosController):
        async_add_entities([KnxActiveSwitch(controller)])
    elif isinstance(controller, UpdaterController):
        async_add_entities([UpdaterActiveSwitch(controller)])
    elif isinstance(controller, AlarmClockController):
        async_add_entities([AlarmClockActiveSwitch(controller)])
    elif isinstance(controller, TaskPlannerController):
        async_add_entities([TaskPlannerActiveSwitch(controller)])
    elif isinstance(controller, MailboxController):
        async_add_entities([MailboxActiveSwitch(controller)])
    else:
        async_add_entities([DoorAutomationSwitch(controller)])


class DoorAutomationSwitch(FunctionEntity, SwitchEntity):
    """on = Regeln des Türwächters sind aktiv."""

    _attr_icon = "mdi:door-closed-lock"

    def __init__(self, controller) -> None:
        super().__init__(controller, "automation")

    @property
    def is_on(self) -> bool:
        return self._controller.automation_enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        until = self._controller.paused_until
        if until and until > dt_util.utcnow():
            return {"paused_until": until.isoformat()}
        return {"paused_until": None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)


class DoorbellActiveSwitch(FunctionEntity, SwitchEntity):
    """on = Klingel meldet (Audio und Push); off = komplett stumm."""

    _attr_icon = "mdi:bell"

    def __init__(self, controller) -> None:
        super().__init__(controller, "active")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)


class ScheduleEnabledSwitch(FunctionEntity, SwitchEntity):
    """Aktiviert bzw. deaktiviert die Zeitplan-Automatik der Pumpe."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, controller) -> None:
        super().__init__(controller, "schedule_enabled")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)


class KnxActiveSwitch(FunctionEntity, SwitchEntity):
    """on = Befehle und Rückmeldungen sind aktiv; off = Connector pausiert."""

    _attr_icon = "mdi:connection"

    def __init__(self, controller) -> None:
        super().__init__(controller, "connector_active")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)


class UpdaterActiveSwitch(FunctionEntity, SwitchEntity):
    """on = Zeitpläne des Updaters laufen; off = Updater pausiert."""

    _attr_icon = "mdi:update"

    def __init__(self, controller) -> None:
        super().__init__(controller, "updater_active")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)


class TaskPlannerActiveSwitch(FunctionEntity, SwitchEntity):
    """on = Auslöser lösen Aufgaben aus; off = Aufgabenplaner pausiert."""

    _attr_icon = "mdi:clipboard-clock-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "task_planner_active")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)


class AlarmClockActiveSwitch(FunctionEntity, SwitchEntity):
    """on = Wecker laufen; off = alle Wecker pausiert (ein laufender Alarm wird gestoppt)."""

    _attr_icon = "mdi:alarm"

    def __init__(self, controller) -> None:
        super().__init__(controller, "alarm_clock_active")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)


class MailboxActiveSwitch(FunctionEntity, SwitchEntity):
    """on = Vibrationen lösen Benachrichtigungen aus; off = Benachrichtigung pausiert."""

    _attr_icon = "mdi:mailbox-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "mailbox_active")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)
