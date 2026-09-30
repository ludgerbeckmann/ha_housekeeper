"""Buttons: Briefkasten geleert, Test-Klingeln."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .doorbell import DoorbellController
from .entity import FunctionEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    if isinstance(controller, DoorbellController):
        async_add_entities([DoorbellTestButton(controller)])
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
