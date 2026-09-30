"""Buttons: Briefkasten geleert, Test-Klingeln, Trockenlauf quittieren."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .doorbell import DoorbellController
from .entity import FunctionEntity, remove_unconfigured
from .pool_pump import PoolPumpController
from .updater import UpdaterController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    if isinstance(controller, DoorbellController):
        async_add_entities([DoorbellTestButton(controller)])
    elif isinstance(controller, UpdaterController):
        async_add_entities([UpdaterCheckNowButton(controller)])
    elif isinstance(controller, PoolPumpController):
        if controller.dry_run_configured:
            async_add_entities([DryRunAcknowledgeButton(controller)])
        else:
            remove_unconfigured(hass, "button", controller, "dry_run_acknowledge")
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


class DryRunAcknowledgeButton(FunctionEntity, ButtonEntity):
    """Quittiert den Alarm und gibt einen pausierten Zeitplan wieder frei."""

    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "dry_run_acknowledge")

    async def async_press(self) -> None:
        await self._controller.async_acknowledge_dry_run()


class UpdaterCheckNowButton(FunctionEntity, ButtonEntity):
    """Prüft sofort auf Updates und meldet das Ergebnis (installiert nie)."""

    _attr_icon = "mdi:magnify"

    def __init__(self, controller) -> None:
        super().__init__(controller, "updater_check_now")

    async def async_press(self) -> None:
        await self._controller.async_check_now()
