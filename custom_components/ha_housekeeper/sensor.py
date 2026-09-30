"""Sensor: Zeitpunkt des letzten Posteinwurfs."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import MailboxEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([MailboxLastDeliverySensor(hass.data[DOMAIN][entry.entry_id])])


class MailboxLastDeliverySensor(MailboxEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:mailbox-up-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "last_delivery")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.last_delivery
