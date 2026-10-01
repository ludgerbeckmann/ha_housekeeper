"""Sensoren der Funktionen."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .alarm_clock import AlarmClockController
from .const import DOMAIN
from .door_guard import DoorGuardController
from .doorbell import DoorbellController
from .entity import FunctionEntity
from .knx_sonos import KnxSonosController
from .pool_pump import PoolPumpController
from .task_planner import TaskPlannerController
from .updater import UpdaterController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    if isinstance(controller, DoorGuardController):
        async_add_entities([DoorLastActionSensor(controller)])
    elif isinstance(controller, DoorbellController):
        async_add_entities([DoorbellLastRingSensor(controller)])
    elif isinstance(controller, PoolPumpController):
        async_add_entities(
            [PoolNextStartSensor(controller), PoolRuntimeTodaySensor(controller)]
        )
    elif isinstance(controller, KnxSonosController):
        async_add_entities([KnxLastCommandSensor(controller)])
    elif isinstance(controller, UpdaterController):
        async_add_entities(
            [
                UpdaterLastRunSensor(controller),
                UpdaterNextRunSensor(controller),
                UpdatesAvailableSensor(controller),
            ]
        )
    elif isinstance(controller, AlarmClockController):
        async_add_entities([AlarmNextSensor(controller), AlarmLastSensor(controller)])
    elif isinstance(controller, TaskPlannerController):
        async_add_entities(
            [TaskLastRunSensor(controller), TaskNextRunSensor(controller)]
        )
    else:
        async_add_entities([MailboxLastDeliverySensor(controller)])


class MailboxLastDeliverySensor(FunctionEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:mailbox-up-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "last_delivery")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.last_delivery


class DoorLastActionSensor(FunctionEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:door-closed-lock"

    def __init__(self, controller) -> None:
        super().__init__(controller, "last_action")

    @property
    def native_value(self) -> datetime | None:
        last = self._controller.last_action
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._controller.last_action or {}
        return {k: last.get(k) for k in ("action", "reason", "result")}


class DoorbellLastRingSensor(FunctionEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:bell-ring"

    def __init__(self, controller) -> None:
        super().__init__(controller, "last_ring")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.last_ring


class PoolNextStartSensor(FunctionEntity, SensorEntity):
    """Nächster geplanter Pumpenstart."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(self, controller) -> None:
        super().__init__(controller, "next_start")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.next_start


class PoolRuntimeTodaySensor(FunctionEntity, SensorEntity):
    """Bisherige Pumpenlaufzeit des heutigen Tages."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "runtime_today")

    @property
    def native_value(self) -> float:
        return self._controller.runtime_today_minutes()


class KnxLastCommandSensor(FunctionEntity, SensorEntity):
    """Zeitpunkt des letzten ausgeführten KNX-Befehls."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:knx"

    def __init__(self, controller) -> None:
        super().__init__(controller, "last_command")

    @property
    def native_value(self) -> datetime | None:
        last = self._controller.last_command
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._controller.last_command or {}
        return {k: last.get(k) for k in ("profile", "name", "address", "action", "value")}


class UpdaterLastRunSensor(FunctionEntity, SensorEntity):
    """Zeitpunkt des letzten Update-Laufs, mit Ergebnis als Attribute."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:update"

    def __init__(self, controller) -> None:
        super().__init__(controller, "updater_last_run")

    @property
    def native_value(self) -> datetime | None:
        last = self._controller.last_run
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._controller.last_run or {}
        attrs = {
            k: last.get(k)
            for k in ("schedule", "mode", "installed", "failed", "skipped", "summary")
        }
        attrs["running"] = self._controller.running
        return attrs


class UpdaterNextRunSensor(FunctionEntity, SensorEntity):
    """Nächster geplanter Lauf über alle Zeitpläne."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, controller) -> None:
        super().__init__(controller, "updater_next_run")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.next_run


class UpdatesAvailableSensor(FunctionEntity, SensorEntity):
    """Anzahl der verfügbaren Updates unter den gewählten Zielen."""

    _attr_icon = "mdi:package-up"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller) -> None:
        super().__init__(controller, "updates_available")

    @property
    def native_value(self) -> int:
        return len(self._controller.available_updates())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"updates": self._controller.available_updates()}


class TaskLastRunSensor(FunctionEntity, SensorEntity):
    """Zeitpunkt der zuletzt ausgeführten Aufgabe, mit Ergebnis als Attribute."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clipboard-check-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "task_last_run")

    @property
    def native_value(self) -> datetime | None:
        last = self._controller.last_run
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._controller.last_run or {}
        attrs = {k: last.get(k) for k in ("task", "trigger", "status", "error")}
        attrs["running"] = self._controller.running
        return attrs


class TaskNextRunSensor(FunctionEntity, SensorEntity):
    """Nächster Zeitpunkt einer zeitgesteuerten Aufgabe."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, controller) -> None:
        super().__init__(controller, "task_next_run")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.next_run


class AlarmNextSensor(FunctionEntity, SensorEntity):
    """Nächster Weckzeitpunkt aller aktiven Wecker."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:alarm"

    def __init__(self, controller) -> None:
        super().__init__(controller, "alarm_next")

    @property
    def native_value(self) -> datetime | None:
        nxt = self._controller.next_alarm
        return nxt[0] if nxt else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nxt = self._controller.next_alarm
        return {"alarm": nxt[1].get("name") if nxt else None}


class AlarmLastSensor(FunctionEntity, SensorEntity):
    """Zeitpunkt des zuletzt ausgelösten Weckers."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:alarm-check"

    def __init__(self, controller) -> None:
        super().__init__(controller, "alarm_last")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.last_ring

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "alarm": self._controller.last_alarm,
            "skipped": self._controller.last_skipped,
        }
