"""Schalter der Funktionen (Türwächter, Türklingel, Poolpumpe, KNX/Sonos)."""

from __future__ import annotations

from functools import partial
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util, slugify

from .alarm_clock import AlarmClockController
from .consumption_guard import ConsumptionGuardController
from .doorbell import DoorbellController
from .subentry import hub_controllers
from .entity import FunctionEntity, remove_unconfigured
from .integration_monitor import IntegrationMonitorController
from .ir_remote import IrRemoteController
from .llm_usage import LlmUsageController
from .knx_sonos import KnxSonosController
from .mailbox import MailboxController
from .pool_pump import PoolPumpController
from .task_planner import TaskPlannerController
from .updater import UpdaterController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Entitäten je Untereintrag (eigenes Gerät) des Hubs."""
    for controller in hub_controllers(hass, entry, Platform.SWITCH):
        _add_entities(
            hass,
            controller,
            partial(async_add_entities, config_subentry_id=controller.entry.entry_id),
        )


def _add_entities(hass: HomeAssistant, controller, async_add_entities) -> None:
    if isinstance(controller, DoorbellController):
        async_add_entities([DoorbellActiveSwitch(controller)])
    elif isinstance(controller, PoolPumpController):
        entities: list[FunctionEntity] = [ScheduleEnabledSwitch(controller)]
        if controller.heater_configured:
            entities.append(HeaterAutoSwitch(controller))
        else:
            remove_unconfigured(hass, "switch", controller, "heater_auto")
        async_add_entities(entities)
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
    elif isinstance(controller, IntegrationMonitorController):
        async_add_entities([MonitorActiveSwitch(controller)])
    elif isinstance(controller, LlmUsageController):
        async_add_entities([LlmActiveSwitch(controller)])
    elif isinstance(controller, ConsumptionGuardController):
        async_add_entities([ConsumptionActiveSwitch(controller)])
    elif isinstance(controller, IrRemoteController):
        switches: list[IrPowerSwitch] = []
        if controller.power_configured:
            switches.append(IrPowerSwitch(controller))
            if len(controller.remotes) > 1:     # bei mehreren Sendern zusätzlich ein Schalter je Sender
                switches += [IrPowerSwitch(controller, remote) for remote in controller.remotes]
        keep = {switch.unique_id for switch in switches}
        registry = er.async_get(hass)
        prefix = f"{controller.entry.entry_id}_ir_power"
        for entity in er.async_entries_for_config_entry(registry, controller.entry.hub_entry_id):
            if entity.domain == "switch" and entity.unique_id.startswith(prefix) and entity.unique_id not in keep:
                registry.async_remove(entity.entity_id)
        async_add_entities(switches)
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


class HeaterAutoSwitch(FunctionEntity, SwitchEntity):
    """on = die Heizung wird nach den Temperaturschwellen automatisch geschaltet."""

    _attr_icon = "mdi:radiator"

    def __init__(self, controller) -> None:
        super().__init__(controller, "heater_auto")

    @property
    def is_on(self) -> bool:
        return self._controller.heater_auto

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_heater_auto(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_heater_auto(False)


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


class MonitorActiveSwitch(FunctionEntity, SwitchEntity):
    """on = Integrationen werden überwacht; off = Monitor pausiert (keine Meldungen, keine Aktionen)."""

    _attr_icon = "mdi:puzzle-check-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "monitor_active")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)


class LlmActiveSwitch(FunctionEntity, SwitchEntity):
    """on = Kosten werden abgefragt und überwacht; off = pausiert (keine Abfrage, keine Warnungen)."""

    _attr_icon = "mdi:robot-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "llm_active")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)
        await self._controller.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)


class IrPowerSwitch(FunctionEntity, SwitchEntity):
    """Schalter aus den Befehlen „an“ und „aus“; der Zustand ist nur angenommen (keine Rückmeldung)."""

    _attr_icon = "mdi:power"
    _attr_assumed_state = True

    def __init__(self, controller, remote: str | None = None) -> None:
        super().__init__(controller, "ir_power")
        self._remote = remote
        if remote:
            self._attr_translation_key = "ir_power_sender"
            self._attr_translation_placeholders = {"sender": controller.remote_name(remote)}
            self._attr_unique_id = f"{controller.entry.entry_id}_ir_power_{slugify(remote)}"

    @property
    def is_on(self) -> bool | None:
        if self._remote:
            return self._controller.assumed_remote.get(self._remote)
        return self._controller.assumed_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_power(True, self._remote)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_power(False, self._remote)


class ConsumptionActiveSwitch(FunctionEntity, SwitchEntity):
    """on = der Verbrauch wird überwacht; off = Wächter pausiert."""

    _attr_icon = "mdi:water-check"

    def __init__(self, controller) -> None:
        super().__init__(controller, "consumption_active")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)
