"""Binary Sensoren: Post vorhanden (Briefkasten), Tür zu lange offen (Türwächter)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .door_guard import DoorGuardController
from .entity import FunctionEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    if isinstance(controller, DoorGuardController):
        async_add_entities([DoorOpenTooLongSensor(controller)])
    else:
        async_add_entities([MailboxHasMailSensor(controller)])


class MailboxHasMailSensor(FunctionEntity, BinarySensorEntity):
    """on = Post im Briefkasten."""

    def __init__(self, controller) -> None:
        super().__init__(controller, "has_mail")

    @property
    def is_on(self) -> bool:
        return self._controller.has_mail

    @property
    def icon(self) -> str:
        return "mdi:mailbox-up" if self.is_on else "mdi:mailbox-outline"


class DoorOpenTooLongSensor(FunctionEntity, BinarySensorEntity):
    """on = Tür steht länger offen als eingestellt."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, controller) -> None:
        super().__init__(controller, "open_too_long")

    @property
    def is_on(self) -> bool:
        return self._controller.open_too_long

    @property
    def icon(self) -> str:
        return "mdi:door-open" if self.is_on else "mdi:door-closed"
