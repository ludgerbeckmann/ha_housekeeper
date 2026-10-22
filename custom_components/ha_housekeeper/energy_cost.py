"""Logik der Funktion "Stromkosten": Verbrauch und Kosten eines vorhandenen Geräts mitzählen."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COST_FIXED_ENTITY,
    CONF_COST_FIXED_POWER,
    CONF_COST_PRICE,
    CONF_COST_PRICE_ENTITY,
    CONF_COST_PRICE_UNIT,
    CONF_COST_SCALE,
    CONF_COST_SOURCE,
    CONF_COST_STANDBY,
    DOMAIN,
    signal_update,
)
from .notify import entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
CHECK_INTERVAL = timedelta(minutes=1)
MAX_GAP = timedelta(minutes=15)       # längere Lücken (z. B. Neustart) werden bei Leistungssensoren nicht aufgerechnet
KEEP_DAYS = 400
_UNKNOWN = (STATE_UNAVAILABLE, STATE_UNKNOWN)

# Faktoren auf kW bzw. kWh
POWER_UNITS = {"W": 0.001, "kW": 1.0, "MW": 1000.0}
ENERGY_UNITS = {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}


# --- reine Funktionen ------------------------------------------------------------------------


def source_kind(unit: str | None) -> str | None:
    """`power` bei W/kW/MW, `energy` bei Wh/kWh/MWh, sonst `None`."""
    if unit in POWER_UNITS:
        return "power"
    if unit in ENERGY_UNITS:
        return "energy"
    return None


OFF_STATES = ("off", "idle", "standby", "paused")


def fixed_power_kw(
    state: Any, power_w: float, standby_w: float = 0.0, scale: bool = False
) -> float | None:
    """Leistung eines Geräts ohne Messung in kW aus dem Zustand seiner Entität (`None` = unbekannt).

    An (alles außer `off`, `idle`, `standby`, `paused`): feste Leistung, bei Leuchten mit `scale` nach der Helligkeit
    (0 bis 255) skaliert; sonst die Standby-Leistung."""
    if state is None or state.state in _UNKNOWN:
        return None
    if state.state in OFF_STATES:
        return standby_w / 1000
    brightness = state.attributes.get("brightness")
    if scale and brightness is not None:
        return power_w * max(0.0, min(float(brightness), 255.0)) / 255 / 1000
    return power_w / 1000


def price_per_kwh(value: float, unit: str) -> float:
    """Preis in €/kWh aus einem Wert in €/kWh (`eur`) oder ct/kWh (`ct`)."""
    return value / 100 if unit == "ct" else value


def power_energy(prev_kw: float, cur_kw: float, hours: float) -> float:
    """Energie in kWh aus zwei Leistungswerten (Trapez), nie negativ."""
    return max((prev_kw + cur_kw) / 2 * hours, 0.0)


def add_day(days: dict[str, dict[str, float]], key: str, kwh: float, cost: float) -> None:
    day = days.setdefault(key, {"kwh": 0.0, "cost": 0.0})
    day["kwh"] += kwh
    day["cost"] += cost
    for old in sorted(days)[:-KEEP_DAYS]:
        days.pop(old)


def sum_days(days: dict[str, dict[str, float]], prefix: str) -> dict[str, float]:
    """Summe aller Tage, deren Schlüssel (`YYYY-MM-DD`) mit `prefix` beginnen (Tag, Monat oder Jahr)."""
    kwh = sum(v["kwh"] for k, v in days.items() if k.startswith(prefix))
    cost = sum(v["cost"] for k, v in days.items() if k.startswith(prefix))
    return {"kwh": kwh, "cost": cost}


def _number(state: Any) -> float | None:
    if state is None or state.state in _UNKNOWN:
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


# --- Controller --------------------------------------------------------------------------------


class EnergyCostController:
    """Zählt Energie und Kosten eines Geräts anhand eines Leistungs- oder Energiesensors."""

    model = "Stromkosten"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.total_kwh = 0.0
        self.total_cost = 0.0
        self.days: dict[str, dict[str, float]] = {}
        self.energy_baseline: float | None = None      # letzter Stand eines Energiezählers (kWh)
        self.price: float | None = None                # zuletzt gültiger Preis in €/kWh
        self._last_power: float | None = None          # kW beim letzten Aufruf
        self._last_time: datetime | None = None
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list[CALLBACK_TYPE] = []

    # --- Einstellungen -------------------------------------------------------

    @property
    def source(self) -> str:
        return self._get(CONF_COST_SOURCE, "") or ""

    @property
    def fixed_entity(self) -> str:
        return self._get(CONF_COST_FIXED_ENTITY, "") or ""

    @property
    def currency(self) -> str:
        return self.hass.config.currency

    def _current_price(self) -> float | None:
        """Aktueller Preis in €/kWh: Preis-Entität, bei Ausfall der letzte gültige Wert, sonst der feste Preis."""
        entity = self._get(CONF_COST_PRICE_ENTITY)
        if entity:
            value = _number(self.hass.states.get(entity))
            if value is not None:
                self.price = price_per_kwh(value, self._get(CONF_COST_PRICE_UNIT, "eur") or "eur")
                return self.price
            if self.price is not None:
                return self.price
        fixed = self._get(CONF_COST_PRICE)
        return None if fixed is None else float(fixed) / 100

    # --- Auswertung für die Entitäten -----------------------------------------

    @staticmethod
    def day_key(now: datetime | None = None) -> str:
        return (now or dt_util.now()).strftime("%Y-%m-%d")

    def period(self, kind: str) -> dict[str, float]:
        """`today`, `month` oder `year` (Energie und Kosten)."""
        key = self.day_key()
        prefix = {"today": key, "month": key[:7], "year": key[:4]}[kind]
        return sum_days(self.days, prefix)

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.total_kwh = float(stored.get("total_kwh", 0.0))
        self.total_cost = float(stored.get("total_cost", 0.0))
        self.days = stored.get("days") or {}
        self.energy_baseline = stored.get("energy_baseline")
        self.price = stored.get("price")
        watched = [
            e for e in (self.source, self.fixed_entity, self._get(CONF_COST_PRICE_ENTITY)) if e
        ]
        self._unsubs.append(async_track_state_change_event(self.hass, watched, self._on_change))
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, CHECK_INTERVAL))
        await self.async_update()

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def _on_tick(self, _now: datetime) -> None:
        await self.async_update()

    async def _on_change(self, event: Event[EventStateChangedData]) -> None:
        await self.async_update()

    def _data(self) -> dict[str, Any]:
        return {
            "total_kwh": self.total_kwh,
            "total_cost": self.total_cost,
            "days": self.days,
            "energy_baseline": self.energy_baseline,
            "price": self.price,
        }

    def _async_save(self) -> None:
        """Verzögert speichern (jede Minute ein Schreibzugriff wäre zu viel); beim Beenden von HA wird geschrieben."""
        self._store.async_delay_save(self._data, 30)

    # --- Berechnung --------------------------------------------------------------

    def _delta_kwh(self, now: datetime) -> float:
        """Energie seit dem letzten Aufruf in kWh (0, wenn nichts zu zählen ist)."""
        if self.fixed_entity:                       # Gerät ohne Messung: feste Leistung nach dem Zustand
            kw = fixed_power_kw(
                self.hass.states.get(self.fixed_entity),
                float(self._get(CONF_COST_FIXED_POWER, 0) or 0),
                float(self._get(CONF_COST_STANDBY, 0) or 0),
                bool(self._get(CONF_COST_SCALE, False)),
            )
            kwh = 0.0
            if kw is not None and self._last_power is not None and self._last_time is not None:
                gap = now - self._last_time
                if gap <= MAX_GAP:
                    kwh = self._last_power * gap.total_seconds() / 3600   # mit dem Zustand des vorigen Zeitpunkts
            self._last_power, self._last_time = kw, now
            return kwh
        state = self.hass.states.get(self.source)
        value = _number(state)
        unit = state.attributes.get("unit_of_measurement") if state else None
        kind = source_kind(unit)
        if value is None or kind is None:
            self._last_power = None
            return 0.0
        if kind == "power":
            kw = value * POWER_UNITS[unit]
            kwh = 0.0
            if self._last_power is not None and self._last_time is not None:
                gap = now - self._last_time
                if gap <= MAX_GAP:
                    kwh = power_energy(self._last_power, kw, gap.total_seconds() / 3600)
            self._last_power, self._last_time = kw, now
            return kwh
        total = value * ENERGY_UNITS[unit]
        if self.energy_baseline is None or total < self.energy_baseline:
            if self.energy_baseline is not None:
                _LOGGER.warning("%s: Zähler zurückgesetzt, der Zeitraum wird übersprungen", self.entry.title)
            self.energy_baseline = total
            return 0.0
        delta = total - self.energy_baseline
        self.energy_baseline = total
        return delta

    async def async_update(self) -> None:
        """Energie seit dem letzten Aufruf zählen und mit dem aktuellen Preis bewerten."""
        now = dt_util.utcnow()
        kwh = self._delta_kwh(now)
        price = self._current_price()
        changed = False
        if kwh > 0:
            cost = kwh * price if price is not None else 0.0
            self.total_kwh += kwh
            self.total_cost += cost
            add_day(self.days, self.day_key(), kwh, cost)
            changed = True
        elif self.energy_baseline is not None:
            changed = True                                  # Zählerstand mitschreiben
        if changed:
            self._async_save()
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))
