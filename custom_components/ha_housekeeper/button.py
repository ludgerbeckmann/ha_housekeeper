"""Buttons: Briefkasten geleert, Test-Klingeln, Trockenlauf quittieren."""

from __future__ import annotations

from functools import partial

import voluptuous as vol

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers import entity_registry as er

from .alarm_clock import AlarmClockController
from .consumption_guard import ConsumptionGuardController
from .const import CONF_IR_REPEATS, IC_ID, IC_NAME, SERVICE_SEND_IR, TASK_ID, TASK_NAME
from .doorbell import DoorbellController
from .integration_monitor import IntegrationMonitorController
from .ir_remote import IrRemoteController
from .llm_usage import LlmUsageController
from .subentry import hub_controllers
from .entity import FunctionEntity, remove_unconfigured
from .pool_pump import PoolPumpController
from .task_planner import TaskPlannerController
from .updater import UpdaterController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Entitäten je Untereintrag (eigenes Gerät) des Hubs."""
    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_SEND_IR,
        {vol.Optional(CONF_IR_REPEATS): vol.All(vol.Coerce(int), vol.Range(min=1, max=20))},
        _async_send_ir,
    )
    for controller in hub_controllers(hass, entry, Platform.BUTTON):
        _add_entities(
            hass,
            controller,
            partial(async_add_entities, config_subentry_id=controller.entry.entry_id),
        )


async def _async_send_ir(entity, call) -> None:
    """Aktion `send_ir_command`: nur für die Befehls-Buttons der IR-Fernbedienung."""
    if not isinstance(entity, IrCommandButton):
        raise ServiceValidationError(f"{entity.entity_id} ist kein IR-Befehl")
    await entity.async_send_ir(call.data.get(CONF_IR_REPEATS))


def _add_entities(hass: HomeAssistant, controller, async_add_entities) -> None:
    if isinstance(controller, DoorbellController):
        async_add_entities([DoorbellTestButton(controller)])
    elif isinstance(controller, UpdaterController):
        async_add_entities([UpdaterCheckNowButton(controller)])
    elif isinstance(controller, LlmUsageController):
        async_add_entities([LlmRefreshButton(controller)])
    elif isinstance(controller, ConsumptionGuardController):
        async_add_entities([ConsumptionAcknowledgeButton(controller)])
    elif isinstance(controller, IrRemoteController):
        entry = controller.entry
        prefix = f"{entry.entry_id}_ir_"
        commands = controller.active_commands
        keep = {f"{prefix}{command[IC_ID]}" for command in commands}
        registry = er.async_get(hass)
        for entity in er.async_entries_for_config_entry(registry, entry.hub_entry_id):
            if entity.domain == "button" and entity.unique_id.startswith(prefix):
                if entity.unique_id not in keep:
                    registry.async_remove(entity.entity_id)
        async_add_entities([IrCommandButton(controller, command) for command in commands])
    elif isinstance(controller, IntegrationMonitorController):
        async_add_entities([MonitorCheckNowButton(controller), MonitorReenableButton(controller)])
    elif isinstance(controller, AlarmClockController):
        async_add_entities([AlarmStopButton(controller), AlarmSnoozeButton(controller)])
    elif isinstance(controller, TaskPlannerController):
        tasks = controller.tasks
        entry = controller.entry
        prefix = f"{entry.entry_id}_task_"
        keep = {f"{prefix}{task[TASK_ID]}" for task in tasks}
        registry = er.async_get(hass)
        for entity in er.async_entries_for_config_entry(registry, entry.hub_entry_id):
            if entity.domain == "button" and entity.unique_id.startswith(prefix):
                if entity.unique_id not in keep:
                    registry.async_remove(entity.entity_id)
        async_add_entities([TaskRunButton(controller, task) for task in tasks])
    elif isinstance(controller, PoolPumpController):
        if controller.dry_run_configured:
            async_add_entities([DryRunAcknowledgeButton(controller)])
        else:
            remove_unconfigured(hass, "button", controller, "dry_run_acknowledge")
    else:
        buttons: list[FunctionEntity] = [MailboxEmptiedButton(controller)]
        if controller.sensitivity_configured:
            buttons.append(MailboxSensitivityButton(controller))
        else:
            remove_unconfigured(hass, "button", controller, "send_sensitivity")
        async_add_entities(buttons)


class MailboxEmptiedButton(FunctionEntity, ButtonEntity):
    _attr_icon = "mdi:mailbox-open-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "emptied")

    async def async_press(self) -> None:
        await self._controller.async_reset()


class DoorbellTestButton(FunctionEntity, ButtonEntity):
    """Löst die Klingel testweise aus (umgeht Schalter und Sperrzeit)."""

    _attr_icon = "mdi:bell-badge"

    def __init__(self, controller) -> None:
        super().__init__(controller, "test_ring")

    async def async_press(self) -> None:
        await self._controller.async_ring(test=True)


class DryRunAcknowledgeButton(FunctionEntity, ButtonEntity):
    """Quittiert den Alarm und gibt einen pausierten Zeitplan wieder frei."""

    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "dry_run_acknowledge")

    async def async_press(self) -> None:
        await self._controller.async_acknowledge_dry_run()


class UpdaterCheckNowButton(FunctionEntity, ButtonEntity):
    """Prüft sofort auf Updates und meldet das Ergebnis (installiert nie)."""

    _attr_icon = "mdi:magnify"

    def __init__(self, controller) -> None:
        super().__init__(controller, "updater_check_now")

    async def async_press(self) -> None:
        await self._controller.async_check_now()


class TaskRunButton(FunctionEntity, ButtonEntity):
    """Führt eine Aufgabe sofort aus (unabhängig von Auslösern und Pause)."""

    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, controller, task: dict) -> None:
        super().__init__(controller, "task_run")
        self._task_id = task[TASK_ID]
        self._attr_translation_key = None
        self._attr_name = task[TASK_NAME]
        self._attr_unique_id = f"{controller.entry.entry_id}_task_{self._task_id}"

    async def async_press(self) -> None:
        await self._controller.async_run_task_id(self._task_id)


class AlarmStopButton(FunctionEntity, ButtonEntity):
    """Stoppt den klingelnden oder schlummernden Wecker."""

    _attr_icon = "mdi:alarm-off"

    def __init__(self, controller) -> None:
        super().__init__(controller, "alarm_stop")

    async def async_press(self) -> None:
        await self._controller.async_stop_alarm()


class AlarmSnoozeButton(FunctionEntity, ButtonEntity):
    """Schlummert den klingelnden Wecker."""

    _attr_icon = "mdi:alarm-snooze"

    def __init__(self, controller) -> None:
        super().__init__(controller, "alarm_snooze")

    async def async_press(self) -> None:
        await self._controller.async_snooze()


class MailboxSensitivityButton(FunctionEntity, ButtonEntity):
    """Sendet die eingestellte Empfindlichkeit an den Vibrationssensor (nur auf Knopfdruck)."""

    _attr_icon = "mdi:tune-vertical"

    def __init__(self, controller) -> None:
        super().__init__(controller, "send_sensitivity")

    async def async_press(self) -> None:
        await self._controller.async_send_sensitivity()


class MonitorCheckNowButton(FunctionEntity, ButtonEntity):
    """Prüft sofort alle Integrationen (die Wartezeit bis zur Bestätigung gilt weiter)."""

    _attr_icon = "mdi:magnify"

    def __init__(self, controller) -> None:
        super().__init__(controller, "monitor_check_now")

    async def async_press(self) -> None:
        await self._controller.async_check()


class MonitorReenableButton(FunctionEntity, ButtonEntity):
    """Aktiviert alle vom Monitor deaktivierten Integrationen wieder."""

    _attr_icon = "mdi:puzzle-plus-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "monitor_reenable")

    async def async_press(self) -> None:
        await self._controller.async_reenable_all()


class LlmRefreshButton(FunctionEntity, ButtonEntity):
    """Fragt die Kosten sofort ab."""

    _attr_icon = "mdi:refresh"

    def __init__(self, controller) -> None:
        super().__init__(controller, "llm_refresh")

    async def async_press(self) -> None:
        await self._controller.async_refresh()


class IrCommandButton(FunctionEntity, ButtonEntity):
    """Sendet einen angelernten IR-Befehl an alle Sender der Instanz."""

    _attr_icon = "mdi:remote"

    def __init__(self, controller, command: dict) -> None:
        super().__init__(controller, "ir_command")
        self._command_id = command[IC_ID]
        self._attr_translation_key = None
        self._attr_name = command[IC_NAME]
        self._attr_unique_id = f"{controller.entry.entry_id}_ir_{self._command_id}"

    async def async_press(self) -> None:
        await self.async_send_ir(None)

    async def async_send_ir(self, repeats: int | None) -> None:
        if await self._controller.async_send(self._command_id, repeats) == "failed":
            raise ServiceValidationError(f"{self._attr_name}: Senden fehlgeschlagen")


class ConsumptionAcknowledgeButton(FunctionEntity, ButtonEntity):
    """Quittiert die Warnung (keine Wiederholung, bis der Verbrauch wieder unter die Schwelle fällt)."""

    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "consumption_acknowledge")

    async def async_press(self) -> None:
        await self._controller.async_acknowledge()
