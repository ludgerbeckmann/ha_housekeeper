"""Binary Sensor: Post vorhanden."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import MailboxEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([MailboxHasMailSensor(hass.data[DOMAIN][entry.entry_id])])


class MailboxHasMailSensor(MailboxEntity, BinarySensorEntity):
    """on = Post im Briefkasten."""

    def __init__(self, controller) -> None:
        super().__init__(controller, "has_mail")

    @property
    def is_on(self) -> bool:
        return self._controller.has_mail

    @property
    def icon(self) -> str:
        return "mdi:mailbox-up" if self.is_on else "mdi:mailbox-outline"
