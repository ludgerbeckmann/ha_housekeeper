"""Button: Briefkasten geleert."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import MailboxEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([MailboxEmptiedButton(hass.data[DOMAIN][entry.entry_id])])


class MailboxEmptiedButton(MailboxEntity, ButtonEntity):
    _attr_icon = "mdi:mailbox-open-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "emptied")

    async def async_press(self) -> None:
        await self._controller.async_reset()
