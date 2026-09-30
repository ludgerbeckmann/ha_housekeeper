"""Diagnose-Download."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .door_guard import DoorGuardController
from .doorbell import DoorbellController
from .mailbox import MailboxController

TO_REDACT: set[str] = set()


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
    }
    controller = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(controller, MailboxController):
        sensor = hass.states.get(controller._opt("vibration_sensor"))  # noqa: SLF001
        result["state"] = {
            "has_mail": controller.has_mail,
            "last_delivery": controller.last_delivery.isoformat()
            if controller.last_delivery
            else None,
            "vibration_sensor_state": sensor.state if sensor else None,
        }
    if isinstance(controller, DoorGuardController):
        contact = controller._opt("contact")  # noqa: SLF001
        lock = hass.states.get(controller._opt("lock"))  # noqa: SLF001
        contact_state = hass.states.get(contact) if contact else None
        result["state"] = {
            "automation_enabled": controller.automation_enabled,
            "paused_until": controller.paused_until.isoformat()
            if controller.paused_until
            else None,
            "open_too_long": controller.open_too_long,
            "last_action": controller.last_action,
            "lock_state": lock.state if lock else None,
            "contact_state": contact_state.state if contact_state else None,
        }
    if isinstance(controller, DoorbellController):
        result["state"] = {
            "enabled": controller.enabled,
            "last_ring": controller.last_ring.isoformat()
            if controller.last_ring
            else None,
        }
    return result
