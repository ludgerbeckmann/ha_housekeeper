"""Sensoren: letzter Posteinwurf (Briefkasten), letzte Aktion (Türwächter)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .door_guard import DoorGuardController
from .doorbell import DoorbellController
from .entity import FunctionEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    if isinstance(controller, DoorGuardController):
        async_add_entities([DoorLastActionSensor(controller)])
    elif isinstance(controller, DoorbellController):
        async_add_entities([DoorbellLastRingSensor(controller)])
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
