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
from .pool_pump import PoolPumpController

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
    if isinstance(controller, PoolPumpController):
        pump = hass.states.get(controller.pump_entity)
        next_start = controller.next_start
        result["state"] = {
            "enabled": controller.enabled,
            "schedule_active": controller.schedule_active,
            "should_run": controller.should_run,
            "manual_until": controller.manual_until.isoformat()
            if controller.manual_until
            else None,
            "next_start": next_start.isoformat() if next_start else None,
            "runtime_today_minutes": controller.runtime_today_minutes(),
            "pump_state": pump.state if pump else None,
            "dry_run": {
                "configured": controller.dry_run_configured,
                "detected": controller.dry_run_detected,
                "schedule_paused": controller.dry_run_paused_schedule,
                "power": controller.current_power(),
            },
        }
    return result
