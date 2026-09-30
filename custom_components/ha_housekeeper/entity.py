"""Gemeinsame Basisklasse der Entitäten einer Funktion."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, signal_update


class FunctionEntity(Entity):
    """Entität, die den Zustand des Controllers spiegelt."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller, key: str) -> None:
        self._controller = controller
        self._attr_translation_key = key
        entry = controller.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Housekeeper",
            model=controller.model,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_update(self._controller.entry.entry_id),
                self.async_write_ha_state,
            )
        )
