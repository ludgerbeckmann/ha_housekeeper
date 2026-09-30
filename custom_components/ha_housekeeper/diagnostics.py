"""Diagnose-Download."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
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
    return result
