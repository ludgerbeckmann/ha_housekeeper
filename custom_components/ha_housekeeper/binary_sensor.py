"""Binary Sensoren: Post vorhanden (Briefkasten), Tür zu lange offen (Türwächter)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .alarm_clock import AlarmClockController
from .const import DOMAIN
from .door_guard import DoorGuardController
from .entity import FunctionEntity, remove_unconfigured
from .pool_pump import PoolPumpController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    if isinstance(controller, DoorGuardController):
        async_add_entities([DoorOpenTooLongSensor(controller)])
    elif isinstance(controller, AlarmClockController):
        async_add_entities([AlarmRingingSensor(controller)])
    elif isinstance(controller, PoolPumpController):
        entities: list[FunctionEntity] = [PumpShouldRunSensor(controller)]
        if controller.dry_run_configured:
            entities.append(DryRunSensor(controller))
        else:
            remove_unconfigured(hass, "binary_sensor", controller, "dry_run_detected")
        async_add_entities(entities)
    else:
        async_add_entities([MailboxHasMailSensor(controller)])


class MailboxHasMailSensor(FunctionEntity, BinarySensorEntity):
    """on = Post im Briefkasten."""

    def __init__(self, controller) -> None:
        super().__init__(controller, "has_mail")

    @property
    def is_on(self) -> bool:
        return self._controller.has_mail

    @property
    def icon(self) -> str:
        return "mdi:mailbox-up" if self.is_on else "mdi:mailbox-outline"


class DoorOpenTooLongSensor(FunctionEntity, BinarySensorEntity):
    """on = Tür steht länger offen als eingestellt."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, controller) -> None:
        super().__init__(controller, "open_too_long")

    @property
    def is_on(self) -> bool:
        return self._controller.open_too_long

    @property
    def icon(self) -> str:
        return "mdi:door-open" if self.is_on else "mdi:door-closed"


class PumpShouldRunSensor(FunctionEntity, BinarySensorEntity):
    """on = die Pumpe soll laut Zeitplan bzw. manuellem Lauf laufen."""

    def __init__(self, controller) -> None:
        super().__init__(controller, "pump_should_run")

    @property
    def is_on(self) -> bool:
        return self._controller.should_run

    @property
    def icon(self) -> str:
        return "mdi:pump" if self.is_on else "mdi:pump-off"

    @property
    def extra_state_attributes(self) -> dict:
        ctrl = self._controller
        return {
            "zeitplan_aktiv": ctrl.enabled,
            "im_zeitfenster": ctrl.schedule_active,
            "manueller_lauf_bis": ctrl.manual_until.isoformat()
            if ctrl.manual_active
            else None,
            "pumpe": ctrl.pump_entity,
        }


class DryRunSensor(FunctionEntity, BinarySensorEntity):
    """on = Trockenlauf erkannt (gehalten, bis quittiert oder Pumpe neu gestartet)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, controller) -> None:
        super().__init__(controller, "dry_run_detected")

    @property
    def is_on(self) -> bool:
        return self._controller.dry_run_detected

    @property
    def icon(self) -> str:
        return "mdi:water-alert" if self.is_on else "mdi:water-check"

    @property
    def extra_state_attributes(self) -> dict:
        ctrl = self._controller
        since = ctrl.dry_run_since
        return {
            "leistung": ctrl.current_power(),
            "seit": since.isoformat() if since else None,
            "zeitplan_pausiert": ctrl.dry_run_paused_schedule,
            "automatisch_ausschalten": ctrl.dry_auto_off,
            "leistungssensor": ctrl.power_entity,
        }


class AlarmRingingSensor(FunctionEntity, BinarySensorEntity):
    """on = ein Wecker klingelt gerade (beim Schlummern off, Attribut snooze_until)."""

    _attr_icon = "mdi:alarm-light"

    def __init__(self, controller) -> None:
        super().__init__(controller, "alarm_ringing")

    @property
    def is_on(self) -> bool:
        return self._controller.ringing

    @property
    def extra_state_attributes(self) -> dict:
        ctrl = self._controller
        return {
            "alarm": (ctrl.current or {}).get("name"),
            "snoozed": ctrl.phase == "snoozed",
            "snooze_until": ctrl.snooze_until.isoformat() if ctrl.snooze_until else None,
        }
