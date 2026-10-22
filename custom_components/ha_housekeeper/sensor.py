"""Sensoren der Funktionen."""

from __future__ import annotations

from functools import partial

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .alarm_clock import AlarmClockController
from .consumption_guard import ConsumptionGuardController
from .door_guard import DoorGuardController
from .energy_cost import EnergyCostController
from .energy_monitor import EnergyMonitorController, share_a
from .doorbell import DoorbellController
from .subentry import hub_controllers
from .entity import FunctionEntity, remove_unconfigured
from .knx_sonos import KnxSonosController
from .pool_pump import PoolPumpController
from .integration_monitor import IntegrationMonitorController
from .ir_remote import IrRemoteController
from .llm_usage import LlmUsageController
from .task_planner import TaskPlannerController
from .updater import UpdaterController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Entitäten je Untereintrag (eigenes Gerät) des Hubs."""
    for controller in hub_controllers(hass, entry, Platform.SENSOR):
        _add_entities(
            hass,
            controller,
            partial(async_add_entities, config_subentry_id=controller.entry.entry_id),
        )


def _add_entities(hass: HomeAssistant, controller, async_add_entities) -> None:
    if isinstance(controller, DoorGuardController):
        async_add_entities([DoorLastActionSensor(controller)])
    elif isinstance(controller, DoorbellController):
        async_add_entities([DoorbellLastRingSensor(controller)])
    elif isinstance(controller, PoolPumpController):
        async_add_entities(
            [PoolNextStartSensor(controller), PoolRuntimeTodaySensor(controller)]
        )
    elif isinstance(controller, KnxSonosController):
        async_add_entities([KnxLastCommandSensor(controller)])
    elif isinstance(controller, UpdaterController):
        async_add_entities(
            [
                UpdaterLastRunSensor(controller),
                UpdaterNextRunSensor(controller),
                UpdatesAvailableSensor(controller),
            ]
        )
    elif isinstance(controller, AlarmClockController):
        async_add_entities([AlarmNextSensor(controller), AlarmLastSensor(controller)])
    elif isinstance(controller, TaskPlannerController):
        async_add_entities(
            [TaskLastRunSensor(controller), TaskNextRunSensor(controller)]
        )
    elif isinstance(controller, IntegrationMonitorController):
        async_add_entities(
            [MonitorFaultySensor(controller), MonitorDisabledSensor(controller)]
        )
    elif isinstance(controller, EnergyCostController):
        async_add_entities(
            [CostEnergySensor(controller)]
            + [CostSensor(controller, kind) for kind in ("today", "month", "year", "total")]
        )
    elif isinstance(controller, EnergyMonitorController):
        async_add_entities(
            [
                EnergyTotalSensor(controller, unit, kind)
                for unit in ("a", "b")
                for kind in ("grid", "pv")
            ]
            + [
                EnergyShareSensor(controller),
                EnergySettlementSensor(controller, "month"),
                EnergySettlementSensor(controller, "year"),
            ]
            + [
                cls(controller, kind, period)
                for kind in ("water", "gas")
                if controller.configured(kind)
                for cls in (EnergyUtilitySensor, EnergyUtilityCostSensor)
                for period in ("month", "year")
            ]
        )
        for kind in ("water", "gas"):               # nicht (mehr) gewählte Zähler: Sensoren entfernen
            if not controller.configured(kind):
                for period in ("month", "year"):
                    remove_unconfigured(hass, "sensor", controller, f"energy_{kind}_{period}")
                    remove_unconfigured(hass, "sensor", controller, f"energy_{kind}_cost_{period}")
    elif isinstance(controller, ConsumptionGuardController):
        async_add_entities([ConsumptionSinceSensor(controller)])
    elif isinstance(controller, IrRemoteController):
        async_add_entities([IrLastSentSensor(controller)])
    elif isinstance(controller, LlmUsageController):
        entities: list[FunctionEntity] = [
            LlmRemainingSensor(controller),
            LlmCostTodaySensor(controller),
            LlmCostMonthSensor(controller),
            LlmForecastSensor(controller),
            LlmDaysLeftSensor(controller),
        ]
        if controller.track_usage:
            entities += [LlmTokensTodaySensor(controller), LlmTokensMonthSensor(controller)]
            if controller.has_requests:
                entities += [LlmRequestsTodaySensor(controller), LlmRequestsMonthSensor(controller)]
        # nicht (mehr) gewünschte Sensoren aus der Registry entfernen
        wanted = {e._attr_translation_key for e in entities}  # noqa: SLF001
        for key in ("llm_tokens_today", "llm_tokens_month", "llm_requests_today", "llm_requests_month"):
            if key not in wanted:
                remove_unconfigured(hass, "sensor", controller, key)
        async_add_entities(entities)
    else:
        async_add_entities([MailboxLastDeliverySensor(controller)])


class MailboxLastDeliverySensor(FunctionEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:mailbox-up-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "last_delivery")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.last_delivery


class DoorLastActionSensor(FunctionEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:door-closed-lock"

    def __init__(self, controller) -> None:
        super().__init__(controller, "last_action")

    @property
    def native_value(self) -> datetime | None:
        last = self._controller.last_action
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._controller.last_action or {}
        return {k: last.get(k) for k in ("action", "reason", "result")}


class DoorbellLastRingSensor(FunctionEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:bell-ring"

    def __init__(self, controller) -> None:
        super().__init__(controller, "last_ring")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.last_ring


class PoolNextStartSensor(FunctionEntity, SensorEntity):
    """Nächster geplanter Pumpenstart."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(self, controller) -> None:
        super().__init__(controller, "next_start")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.next_start


class PoolRuntimeTodaySensor(FunctionEntity, SensorEntity):
    """Bisherige Pumpenlaufzeit des heutigen Tages."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "runtime_today")

    @property
    def native_value(self) -> float:
        return self._controller.runtime_today_minutes()


class KnxLastCommandSensor(FunctionEntity, SensorEntity):
    """Zeitpunkt des letzten ausgeführten KNX-Befehls."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:knx"

    def __init__(self, controller) -> None:
        super().__init__(controller, "last_command")

    @property
    def native_value(self) -> datetime | None:
        last = self._controller.last_command
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._controller.last_command or {}
        return {k: last.get(k) for k in ("profile", "name", "address", "action", "value")}


class UpdaterLastRunSensor(FunctionEntity, SensorEntity):
    """Zeitpunkt des letzten Update-Laufs, mit Ergebnis als Attribute."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:update"

    def __init__(self, controller) -> None:
        super().__init__(controller, "updater_last_run")

    @property
    def native_value(self) -> datetime | None:
        last = self._controller.last_run
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._controller.last_run or {}
        attrs = {
            k: last.get(k)
            for k in ("schedule", "mode", "installed", "failed", "skipped", "summary")
        }
        attrs["running"] = self._controller.running
        return attrs


class UpdaterNextRunSensor(FunctionEntity, SensorEntity):
    """Nächster geplanter Lauf über alle Zeitpläne."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, controller) -> None:
        super().__init__(controller, "updater_next_run")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.next_run


class UpdatesAvailableSensor(FunctionEntity, SensorEntity):
    """Anzahl der verfügbaren Updates unter den gewählten Zielen."""

    _attr_icon = "mdi:package-up"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller) -> None:
        super().__init__(controller, "updates_available")

    @property
    def native_value(self) -> int:
        return len(self._controller.available_updates())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"updates": self._controller.available_updates()}


class TaskLastRunSensor(FunctionEntity, SensorEntity):
    """Zeitpunkt der zuletzt ausgeführten Aufgabe, mit Ergebnis als Attribute."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clipboard-check-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "task_last_run")

    @property
    def native_value(self) -> datetime | None:
        last = self._controller.last_run
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._controller.last_run or {}
        attrs = {k: last.get(k) for k in ("task", "trigger", "status", "error")}
        attrs["running"] = self._controller.running
        return attrs


class TaskNextRunSensor(FunctionEntity, SensorEntity):
    """Nächster Zeitpunkt einer zeitgesteuerten Aufgabe."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, controller) -> None:
        super().__init__(controller, "task_next_run")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.next_run


class AlarmNextSensor(FunctionEntity, SensorEntity):
    """Nächster Weckzeitpunkt aller aktiven Wecker."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:alarm"

    def __init__(self, controller) -> None:
        super().__init__(controller, "alarm_next")

    @property
    def native_value(self) -> datetime | None:
        nxt = self._controller.next_alarm
        return nxt[0] if nxt else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nxt = self._controller.next_alarm
        return {"alarm": nxt[1].get("name") if nxt else None}


class AlarmLastSensor(FunctionEntity, SensorEntity):
    """Zeitpunkt des zuletzt ausgelösten Weckers."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:alarm-check"

    def __init__(self, controller) -> None:
        super().__init__(controller, "alarm_last")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.last_ring

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "alarm": self._controller.last_alarm,
            "skipped": self._controller.last_skipped,
        }


class MonitorFaultySensor(FunctionEntity, SensorEntity):
    """Anzahl der Integrationen mit bestätigter Störung (Namen als Attribut)."""

    _attr_icon = "mdi:puzzle-remove-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "monitor_faulty")

    @property
    def native_value(self) -> int:
        return len(self._controller.faulty_titles)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"integrations": self._controller.faulty_titles}


class MonitorDisabledSensor(FunctionEntity, SensorEntity):
    """Anzahl der vom Monitor deaktivierten Integrationen (Namen als Attribut)."""

    _attr_icon = "mdi:puzzle-minus-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, "monitor_disabled")

    @property
    def native_value(self) -> int:
        return len(self._controller.disabled_titles)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"integrations": self._controller.disabled_titles}


class _LlmSensor(FunctionEntity, SensorEntity):
    """Basis der LLM-Sensoren: Messwert mit Währung, der Verlauf kommt aus den Recorder-Statistiken."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._controller.currency

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._controller.last_update
        return {"last_update": last.isoformat() if last else None}


class LlmRemainingSensor(_LlmSensor):
    """Restguthaben (Guthaben-Modus) bzw. Restbudget (Monatsbudget)."""

    _attr_icon = "mdi:cash-clock"

    def __init__(self, controller) -> None:
        super().__init__(controller, "llm_remaining")

    @property
    def native_value(self) -> float | None:
        value = self._controller.remaining
        return None if value is None else round(value, 4)


class LlmCostTodaySensor(_LlmSensor):
    """Kosten heute (UTC-Tag des Anbieters)."""

    _attr_icon = "mdi:cash-fast"

    def __init__(self, controller) -> None:
        super().__init__(controller, "llm_cost_today")

    @property
    def native_value(self) -> float | None:
        return round(self._controller.cost_today, 4) if self._controller.last_update else None


class LlmCostMonthSensor(_LlmSensor):
    """Kosten im laufenden Monat (UTC)."""

    _attr_icon = "mdi:cash-multiple"

    def __init__(self, controller) -> None:
        super().__init__(controller, "llm_cost_month")

    @property
    def native_value(self) -> float | None:
        return round(self._controller.cost_month, 4) if self._controller.last_update else None


class LlmDaysLeftSensor(_LlmSensor):
    """Reichweite des Restguthabens in Tagen (bei den Durchschnittskosten der letzten 7 Tage)."""

    _attr_icon = "mdi:calendar-clock"
    _attr_suggested_display_precision = 1

    def __init__(self, controller) -> None:
        super().__init__(controller, "llm_days_left")

    @property
    def native_unit_of_measurement(self) -> str | None:
        return UnitOfTime.DAYS

    @property
    def native_value(self) -> float | None:
        value = self._controller.days_left
        return None if value is None else round(value, 1)


class LlmForecastSensor(_LlmSensor):
    """Erwartete Kosten bis Monatsende (bisherige Kosten plus Durchschnitt der letzten 7 Tage)."""

    _attr_icon = "mdi:chart-line"

    def __init__(self, controller) -> None:
        super().__init__(controller, "llm_forecast")

    @property
    def native_value(self) -> float | None:
        return round(self._controller.forecast, 4) if self._controller.last_update else None


class _LlmUsageSensor(FunctionEntity, SensorEntity):
    """Basis der Token- und Anfragen-Sensoren (Zählwerte ohne Einheit)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def _usage(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        usage = self._usage()
        return {"input": usage["input"], "output": usage["output"], "cached_input": usage["cached"]}

    @property
    def available(self) -> bool:
        return bool(self._controller.usage)


class LlmTokensTodaySensor(_LlmUsageSensor):
    """Tokens heute (Eingabe und Ausgabe, UTC-Tag)."""

    _attr_icon = "mdi:counter"

    def __init__(self, controller) -> None:
        super().__init__(controller, "llm_tokens_today")

    def _usage(self) -> dict[str, Any]:
        return self._controller.usage_today

    @property
    def native_value(self) -> int:
        usage = self._usage()
        return usage["input"] + usage["output"]


class LlmTokensMonthSensor(LlmTokensTodaySensor):
    """Tokens im laufenden Monat (UTC)."""

    def __init__(self, controller) -> None:
        _LlmUsageSensor.__init__(self, controller, "llm_tokens_month")

    def _usage(self) -> dict[str, Any]:
        return self._controller.usage_month


class LlmRequestsTodaySensor(_LlmUsageSensor):
    """Anfragen heute (nur OpenAI)."""

    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, controller) -> None:
        super().__init__(controller, "llm_requests_today")

    def _usage(self) -> dict[str, Any]:
        return self._controller.usage_today

    @property
    def native_value(self) -> int | None:
        return self._usage()["requests"]


class LlmRequestsMonthSensor(LlmRequestsTodaySensor):
    """Anfragen im laufenden Monat (nur OpenAI)."""

    def __init__(self, controller) -> None:
        _LlmUsageSensor.__init__(self, controller, "llm_requests_month")

    def _usage(self) -> dict[str, Any]:
        return self._controller.usage_month


class IrLastSentSensor(FunctionEntity, SensorEntity):
    """Zeitpunkt des letzten gesendeten IR-Befehls, mit Befehl, Ergebnis und Fehlern je Sender."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:remote"

    def __init__(self, controller) -> None:
        super().__init__(controller, "ir_last_sent")

    @property
    def native_value(self) -> datetime | None:
        last = self._controller.last_sent
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._controller.last_sent or {}
        return {k: last.get(k) for k in ("command", "result", "errors")}


class ConsumptionSinceSensor(FunctionEntity, SensorEntity):
    """Seit wann der Wert über der Schwelle liegt (leer, wenn nicht)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:water-alert"

    def __init__(self, controller) -> None:
        super().__init__(controller, "consumption_since")

    @property
    def native_value(self) -> datetime | None:
        return self._controller.since


class CostEnergySensor(FunctionEntity, SensorEntity):
    """Gezählte Energie des Geräts (kWh, steigend; im Energie-Dashboard als einzelnes Gerät nutzbar)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 3

    def __init__(self, controller) -> None:
        super().__init__(controller, "cost_energy")

    @property
    def native_value(self) -> float:
        return round(self._controller.total_kwh, 4)


class CostSensor(FunctionEntity, SensorEntity):
    """Kosten des Geräts: heute, im Monat, im Jahr oder gesamt (Währung von Home Assistant)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    def __init__(self, controller, kind: str) -> None:
        super().__init__(controller, f"cost_{kind}")
        self._kind = kind
        if kind == "total":
            self._attr_state_class = SensorStateClass.TOTAL

    @property
    def native_unit_of_measurement(self) -> str:
        return self._controller.currency

    @property
    def native_value(self) -> float:
        if self._kind == "total":
            return round(self._controller.total_cost, 4)
        return round(self._controller.period(self._kind)["cost"], 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._kind == "total":
            return {"kwh": round(self._controller.total_kwh, 4)}
        return {"kwh": round(self._controller.period(self._kind)["kwh"], 4)}


class EnergyTotalSensor(FunctionEntity, SensorEntity):
    """Netzbezug oder PV-Anteil einer Einheit (kWh seit dem Einrichten, steigend)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2

    def __init__(self, controller, unit: str, kind: str) -> None:
        super().__init__(controller, f"energy_{kind}_{unit}")
        self._attr_translation_key = f"energy_{kind}"
        self._attr_translation_placeholders = {
            "unit": controller.name_a if unit == "a" else controller.name_b
        }
        self._key = f"{kind}_{unit}"

    @property
    def native_value(self) -> float:
        return round(self._controller.totals.get(self._key, 0.0), 3)


class EnergyShareSensor(FunctionEntity, SensorEntity):
    """Anteil von Einheit A am Verbrauch im laufenden Monat (laut Zwischenzählern)."""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:percent"

    def __init__(self, controller) -> None:
        super().__init__(controller, "energy_share")
        self._attr_translation_placeholders = {"unit": controller.name_a}

    @property
    def native_value(self) -> float | None:
        value = share_a(self._controller.month())
        return None if value is None else round(value, 2)


class EnergyUtilitySensor(FunctionEntity, SensorEntity):
    """Verbrauch von Wasser oder Gas im Monat oder Jahr (m³, beide Einheiten zusammen)."""

    _attr_native_unit_of_measurement = "m³"
    _attr_suggested_display_precision = 2

    def __init__(self, controller, kind: str, period: str) -> None:
        super().__init__(controller, f"energy_{kind}_{period}")
        self._kind = kind
        self._period = period
        self._attr_device_class = (
            SensorDeviceClass.WATER if kind == "water" else SensorDeviceClass.GAS
        )

    @property
    def native_value(self) -> float:
        controller = self._controller
        acc = controller.month() if self._period == "month" else controller.year()[0]
        return round(acc.get(self._kind, 0.0), 3)


class EnergyUtilityCostSensor(FunctionEntity, SensorEntity):
    """Anteil von Einheit B an den Kosten für Wasser oder Gas im Monat oder Jahr (Personen bzw. Wohnfläche)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    def __init__(self, controller, kind: str, period: str) -> None:
        super().__init__(controller, f"energy_{kind}_cost_{period}")
        self._kind = kind
        self._period = period
        self._attr_translation_placeholders = {"unit": controller.name_b}

    @property
    def native_unit_of_measurement(self) -> str:
        return self._controller.currency

    def _result(self) -> dict[str, float]:
        controller = self._controller
        if self._period == "month":
            acc, months = controller.month(), 1
        else:
            acc, months = controller.year()
        return controller.utility(self._kind, acc, months)

    @property
    def native_value(self) -> float:
        return round(self._result()["cost_b"], 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._result()
        return {
            "volume_m3": round(result["volume"], 3),
            "total_cost": round(result["total"], 2),
            "share_b": round(self._controller.share_b(self._kind) * 100, 2),
        }


class EnergySettlementSensor(FunctionEntity, SensorEntity):
    """Verrechnung im Monat oder Jahr: was Einheit B an Einheit A schuldet (negativ = A schuldet B)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    def __init__(self, controller, period: str) -> None:
        super().__init__(controller, f"energy_settlement_{period}")
        self._period = period
        self._attr_translation_placeholders = {"unit": controller.name_b}

    @property
    def native_unit_of_measurement(self) -> str:
        return self._controller.currency

    def _values(self) -> tuple[dict[str, float], dict[str, float], int]:
        controller = self._controller
        if self._period == "month":
            acc, months = controller.month(), 1
        else:
            acc, months = controller.year()
        return acc, controller._settle(acc, months), months  # noqa: SLF001

    @property
    def native_value(self) -> float:
        return round(self._values()[1]["owed"], 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        acc, result, months = self._values()
        controller = self._controller
        return {
            "unit_a": controller.name_a,
            "unit_b": controller.name_b,
            "direction": "b_owes_a" if result["owed"] >= 0 else "a_owes_b",
            "months": months,
            "grid_kwh_a": round(acc["grid_a"], 3),
            "grid_kwh_b": round(acc["grid_b"], 3),
            "pv_kwh_a": round(acc["pv_a"], 3),
            "pv_kwh_b": round(acc["pv_b"], 3),
            "grid_cost_b": round(result["grid_cost_b"], 2),
            "pv_credit_a": round(result["pv_credit_a"], 2),
            "base_fee_b": round(result["base_fee_b"], 2),
            "common_kwh": round(acc.get("common", 0.0), 3),
            "common_kwh_b": round(acc.get("common_b", 0.0), 3),
            "water_m3": round(acc.get("water", 0.0), 3),
            "gas_m3": round(acc.get("gas", 0.0), 3),
            "water_cost_b": round(result["water_cost_b"], 2),
            "gas_cost_b": round(result["gas_cost_b"], 2),
        }
