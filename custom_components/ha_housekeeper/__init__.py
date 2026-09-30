"""Housekeeper - Integration für verschiedene Smart-Home-Anwendungsfälle."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

from .const import CONF_FUNCTION_TYPE, DOMAIN, FUNCTION_MAILBOX, FUNCTION_PLATFORMS
from .mailbox import MailboxController

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Eintrag einrichten - je nach Funktionstyp."""
    function_type = entry.data[CONF_FUNCTION_TYPE]
    domain_data = hass.data.setdefault(DOMAIN, {})

    if function_type == FUNCTION_MAILBOX:
        controller = MailboxController(hass, entry)
        await controller.async_start()
        domain_data[entry.entry_id] = controller

    await hass.config_entries.async_forward_entry_setups(
        entry, FUNCTION_PLATFORMS[function_type]
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Eintrag entladen."""
    function_type = entry.data[CONF_FUNCTION_TYPE]
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, FUNCTION_PLATFORMS[function_type]
    )
    if unloaded:
        controller = hass.data[DOMAIN].pop(entry.entry_id, None)
        if controller:
            controller.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Gespeicherten Zustand beim Löschen entfernen."""
    if entry.data.get(CONF_FUNCTION_TYPE) == FUNCTION_MAILBOX:
        await MailboxController(hass, entry).async_remove_data()
