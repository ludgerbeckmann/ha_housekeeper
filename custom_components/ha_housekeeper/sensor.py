"""Sensoren der Funktionen (Briefkasten, Türwächter, Türklingel, Poolpumpe)."""

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

from .const import DOMAIN
from .door_guard import DoorGuardController
from .doorbell import DoorbellController
from .entity import FunctionEntity
from .pool_pump import PoolPumpController


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
