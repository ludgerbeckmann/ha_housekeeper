"""Buttons: Briefkasten geleert, Test-Klingeln, Trockenlauf quittieren."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers import entity_registry as er

from .alarm_clock import AlarmClockController
from .const import DOMAIN, TASK_ID, TASK_NAME
from .doorbell import DoorbellController
from .entity import FunctionEntity, remove_unconfigured
from .pool_pump import PoolPumpController
from .task_planner import TaskPlannerController
from .updater import UpdaterController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    if isinstance(controller, DoorbellController):
        async_add_entities([DoorbellTestButton(controller)])
    elif isinstance(controller, UpdaterController):
        async_add_entities([UpdaterCheckNowButton(controller)])
    elif isinstance(controller, AlarmClockController):
        async_add_entities([AlarmStopButton(controller), AlarmSnoozeButton(controller)])
    elif isinstance(controller, TaskPlannerController):
        tasks = controller.tasks
        prefix = f"{entry.entry_id}_task_"
        keep = {f"{prefix}{task[TASK_ID]}" for task in tasks}
        registry = er.async_get(hass)
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
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
        async_add_entities([MailboxEmptiedButton(controller)])


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
