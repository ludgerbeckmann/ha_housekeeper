"""Schalter: Automatik des Türwächters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import FunctionEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([DoorAutomationSwitch(hass.data[DOMAIN][entry.entry_id])])


class DoorAutomationSwitch(FunctionEntity, SwitchEntity):
    """on = Regeln des Türwächters sind aktiv."""

    _attr_icon = "mdi:door-closed-lock"

    def __init__(self, controller) -> None:
        super().__init__(controller, "automation")

    @property
    def is_on(self) -> bool:
        return self._controller.automation_enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        until = self._controller.paused_until
        if until and until > dt_util.utcnow():
            return {"paused_until": until.isoformat()}
        return {"paused_until": None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)
