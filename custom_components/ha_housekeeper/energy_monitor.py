"""Logik der Funktion "Energiemonitor": Netzbezug und PV-Eigenverbrauch auf zwei Einheiten aufteilen."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EM_BASE_FEE,
    CONF_EM_BASE_SHARE,
    CONF_EM_COMMON_KEY,
    CONF_EM_COMMON_METER,
    CONF_EM_COMMON_POWER,
    CONF_EM_AREA_A,
    CONF_EM_AREA_B,
    CONF_EM_FEED,
    CONF_EM_GAS,
    CONF_EM_GAS_FEE,
    CONF_EM_GAS_KEY,
    CONF_EM_GAS_PRICE,
    CONF_EM_GRID,
    CONF_EM_METER_A,
    CONF_EM_METER_B,
    CONF_EM_NAME_A,
    CONF_EM_NAME_B,
    CONF_EM_PERSONS_A,
    CONF_EM_PERSONS_B,
    CONF_EM_PRICE,
    CONF_EM_PV,
    CONF_EM_PV_PRICE,
    CONF_EM_WATER,
    CONF_EM_WATER_FEE,
    CONF_EM_WATER_PRICE,
    DEFAULT_EM_BASE_SHARE,
    DEFAULT_EM_NAME_A,
    DEFAULT_EM_NAME_B,
    DEFAULT_EM_PERSONS,
    DOMAIN,
    signal_update,
)
from .notify import entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
CHECK_INTERVAL = timedelta(minutes=1)
KEEP_MONTHS = 36
_UNKNOWN = (STATE_UNAVAILABLE, STATE_UNKNOWN)

# Summen je Zeitraum: Netzbezug und PV-Eigenverbrauch je Einheit, dazu der Verbrauch laut Zwischenzähler,
# außerdem der gemeinsame Verbrauch von Wasser und Gas (m³)
KEYS = ("grid_a", "grid_b", "pv_a", "pv_b", "cons_a", "cons_b", "water", "gas", "common", "common_b")
UTILITIES = {
    "water": (CONF_EM_WATER, CONF_EM_WATER_PRICE, CONF_EM_WATER_FEE),
    "gas": (CONF_EM_GAS, CONF_EM_GAS_PRICE, CONF_EM_GAS_FEE),
}
SOURCES = (CONF_EM_GRID, CONF_EM_FEED, CONF_EM_PV, CONF_EM_METER_A, CONF_EM_METER_B)


# --- reine Funktionen ------------------------------------------------------------------------


def split_interval(
    d_grid: float, d_feed: float, d_pv: float, d_a: float, d_b: float, shift: float = 0.0
) -> dict[str, float] | None:
    """Einen Zeitraum aufteilen (zeitgleich anteilig nach den Zwischenzählern).

    Der PV-Eigenverbrauch ist Erzeugung minus Einspeisung (nicht negativ); Netzbezug und
    Eigenverbrauch werden im Verhältnis des Verbrauchs der Zwischenzähler auf die Einheiten verteilt.
    Hat keine Einheit etwas verbraucht, gibt es nichts zu verteilen (`None`).

    `shift` ist der Teil des Allgemeinstroms (läuft über den Zähler von A), der Einheit B zugerechnet wird:
    er wandert von A nach B, bevor verteilt wird."""
    d_a, d_b = d_a - shift, d_b + shift
    total = d_a + d_b
    if total <= 0:
        return None
    share_a = d_a / total
    self_use = max(d_pv - d_feed, 0.0)
    return {
        "grid_a": d_grid * share_a,
        "grid_b": d_grid * (1 - share_a),
        "pv_a": self_use * share_a,
        "pv_b": self_use * (1 - share_a),
        "cons_a": d_a,
        "cons_b": d_b,
    }


def add_up(acc: dict[str, float] | None, part: dict[str, float]) -> dict[str, float]:
    return {key: (acc or {}).get(key, 0.0) + part.get(key, 0.0) for key in KEYS}


def common_part(
    d_a: float, meter_delta: float | None, power_w: float, hours: float, share_b: float
) -> tuple[float, float]:
    """Allgemeinstrom im Zeitraum (Zähler, sonst feste Leistung × Zeit, höchstens der Verbrauch von A) und
    der Anteil, der Einheit B zugerechnet wird."""
    common = meter_delta if meter_delta is not None else power_w / 1000 * hours
    common = max(0.0, min(common, d_a))
    return common, common * share_b


def settle(
    acc: dict[str, float],
    price_ct: float,
    pv_price_ct: float,
    base_fee: float,
    base_share_b: float,
    months: int,
) -> dict[str, float]:
    """Verrechnung: was Einheit B an Einheit A schuldet (negativ = A schuldet B).

    Netzstrom von B plus dessen Anteil am Grundpreis, abzüglich der PV-kWh von A zum Preis je PV-kWh
    (die Eigenverbrauchsvergütung bleibt beim Anlagenbetreiber)."""
    grid_cost_b = acc.get("grid_b", 0.0) * price_ct / 100
    pv_credit = acc.get("pv_a", 0.0) * pv_price_ct / 100
    fee_b = base_fee * base_share_b / 100 * months
    return {
        "owed": grid_cost_b + fee_b - pv_credit,
        "grid_cost_b": grid_cost_b,
        "pv_credit_a": pv_credit,
        "base_fee_b": fee_b,
    }


def persons_share_b(persons_a: float, persons_b: float) -> float:
    """Anteil von Einheit B nach Personenzahl oder Wohnfläche (0 bis 1; ohne Bezugsgröße 0)."""
    total = persons_a + persons_b
    return 0.0 if total <= 0 else persons_b / total


def utility_cost_b(
    volume: float, price: float, base_fee: float, share_b: float, months: int
) -> dict[str, float]:
    """Wasser oder Gas: Kosten insgesamt und der Anteil von Einheit B (Personenschlüssel)."""
    total = volume * price + base_fee * months
    return {"total": total, "cost_b": total * share_b}


def share_a(acc: dict[str, float]) -> float | None:
    """Anteil von Einheit A am Verbrauch in Prozent (`None` ohne Verbrauch)."""
    total = acc.get("cons_a", 0.0) + acc.get("cons_b", 0.0)
    return None if total <= 0 else acc["cons_a"] / total * 100


def _number(state: Any) -> float | None:
    if state is None or state.state in _UNKNOWN:
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


# --- Controller --------------------------------------------------------------------------------


class EnergyMonitorController:
    """Verteilt die Zählerstände von Netz, Einspeisung, PV und zwei Zwischenzählern."""

    model = "Energiemonitor"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.baseline: dict[str, float] | None = None
        self.util_baseline: dict[str, float] = {}
        self.baseline_time: datetime | None = None
        self.totals: dict[str, float] = {key: 0.0 for key in KEYS}
        self.months: dict[str, dict[str, float]] = {}
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list[CALLBACK_TYPE] = []
        self._last_month: str | None = None

    # --- Einstellungen -------------------------------------------------------

    @property
    def name_a(self) -> str:
        return self._get(CONF_EM_NAME_A, DEFAULT_EM_NAME_A) or DEFAULT_EM_NAME_A

    @property
    def name_b(self) -> str:
        return self._get(CONF_EM_NAME_B, DEFAULT_EM_NAME_B) or DEFAULT_EM_NAME_B

    @property
    def currency(self) -> str:
        return self.hass.config.currency

    def configured(self, kind: str) -> bool:
        """Ist für Wasser bzw. Gas ein Zähler gewählt?"""
        return bool(self._get(UTILITIES[kind][0]))

    def share_b(self, kind: str) -> float:
        """Anteil von Einheit B: Wasser nach Personen, Gas und Allgemeinstrom nach Wohnfläche (Standard),
        Personen oder (Allgemeinstrom) je zur Hälfte."""
        key_name = {"gas": CONF_EM_GAS_KEY, "common": CONF_EM_COMMON_KEY}.get(kind)
        key = self._get(key_name, "area") if key_name else "persons"
        if key == "half":
            return 0.5
        if key == "area":
            keys = (CONF_EM_AREA_A, CONF_EM_AREA_B)
        else:
            keys = (CONF_EM_PERSONS_A, CONF_EM_PERSONS_B)
        return persons_share_b(*(float(self._get(key, DEFAULT_EM_PERSONS) or 0) for key in keys))

    def utility(self, kind: str, acc: dict[str, float], months: int) -> dict[str, float]:
        """Verbrauch (m³), Gesamtkosten und Anteil von Einheit B; ohne Zähler alles 0."""
        if not self.configured(kind):
            return {"volume": 0.0, "total": 0.0, "cost_b": 0.0}
        _meter, price, fee = UTILITIES[kind]
        volume = acc.get(kind, 0.0)
        result = utility_cost_b(
            volume, float(self._get(price, 0) or 0), float(self._get(fee, 0) or 0), self.share_b(kind), months
        )
        return {"volume": volume, **result}

    def _settle(self, acc: dict[str, float], months: int) -> dict[str, float]:
        result = settle(
            acc,
            float(self._get(CONF_EM_PRICE, 0)),
            float(self._get(CONF_EM_PV_PRICE, 0)),
            float(self._get(CONF_EM_BASE_FEE, 0)),
            float(self._get(CONF_EM_BASE_SHARE, DEFAULT_EM_BASE_SHARE)),
            months,
        )
        for kind in UTILITIES:
            result[f"{kind}_cost_b"] = self.utility(kind, acc, months)["cost_b"]
            result["owed"] += result[f"{kind}_cost_b"]
        return result

    # --- Auswertung für die Entitäten -----------------------------------------

    @staticmethod
    def month_key(now: datetime | None = None) -> str:
        return (now or dt_util.now()).strftime("%Y-%m")

    def month(self, key: str | None = None) -> dict[str, float]:
        return self.months.get(key or self.month_key(), {k: 0.0 for k in KEYS})

    def year(self, year: str | None = None) -> tuple[dict[str, float], int]:
        """Summe der Monate eines Jahres und Zahl der Monate mit Werten."""
        prefix = year or self.month_key()[:4]
        acc: dict[str, float] = {k: 0.0 for k in KEYS}
        count = 0
        for key, values in self.months.items():
            if key.startswith(prefix):
                acc = add_up(acc, values)
                count += 1
        return acc, count

    def settlement_month(self) -> dict[str, float]:
        return self._settle(self.month(), 1)

    def settlement_year(self) -> dict[str, float]:
        acc, count = self.year()
        return self._settle(acc, count)

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.baseline = stored.get("baseline")
        self.util_baseline = stored.get("util_baseline") or {}
        self.baseline_time = dt_util.parse_datetime(stored.get("baseline_time") or "")
        self.totals = {**self.totals, **(stored.get("totals") or {})}
        self.months = stored.get("months") or {}
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, CHECK_INTERVAL))
        await self.async_update()

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def _on_tick(self, _now: datetime) -> None:
        await self.async_update()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "baseline": self.baseline,
                "util_baseline": self.util_baseline,
                "baseline_time": self.baseline_time.isoformat() if self.baseline_time else None,
                "totals": self.totals,
                "months": self.months,
            }
        )

    # --- Berechnung --------------------------------------------------------------

    def _read(self) -> dict[str, float] | None:
        values: dict[str, float] = {}
        for key in SOURCES:
            number = _number(self.hass.states.get(self._get(key) or ""))
            if number is None:
                return None
            values[key] = number
        if self._get(CONF_EM_COMMON_METER):         # optionaler Zähler: unklar = Zeitraum wächst weiter
            number = _number(self.hass.states.get(self._get(CONF_EM_COMMON_METER)))
            if number is None:
                return None
            values[CONF_EM_COMMON_METER] = number
        return values

    async def _async_update_utilities(self) -> None:
        """Wasser und Gas: der Verbrauch seit dem letzten Stand gehört zum laufenden Monat (kein Verteilen nötig)."""
        changed = False
        for kind in UTILITIES:
            if not self.configured(kind):
                if self.util_baseline.pop(kind, None) is not None:
                    changed = True
                continue
            number = _number(self.hass.states.get(self._get(UTILITIES[kind][0])))
            if number is None:
                continue                            # Zähler unklar: der Zeitraum wächst weiter
            last = self.util_baseline.get(kind)
            if last is None or number < last:       # erster Stand oder Zähler zurückgesetzt
                self.util_baseline[kind] = number
                changed = True
                continue
            if number == last:
                continue
            part = {kind: number - last}
            key = self.month_key()
            self.months[key] = add_up(self.months.get(key), part)
            self.totals = add_up(self.totals, part)
            self.util_baseline[kind] = number
            changed = True
        if changed:
            await self._async_save()
            async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def async_update(self) -> None:
        """Zählerstände einlesen und den Zeitraum seit dem letzten Stand verteilen."""
        month = self.month_key()
        if month != self._last_month:               # neuer Monat (oder Start): Entitäten aktualisieren
            self._last_month = month
            async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))
        await self._async_update_utilities()
        current = self._read()
        if current is None:
            return                                  # ein Zähler fehlt: der Zeitraum wächst weiter
        now = dt_util.utcnow()
        if self.baseline is None or any(
            value < self.baseline.get(key, value) for key, value in current.items()
        ):
            if self.baseline is not None:
                _LOGGER.warning("%s: Zähler zurückgesetzt, der Zeitraum wird übersprungen", self.entry.title)
            self.baseline = current
            self.baseline_time = now
            await self._async_save()
            return
        d_a = current[CONF_EM_METER_A] - self.baseline[CONF_EM_METER_A]
        meter_delta = (
            current[CONF_EM_COMMON_METER] - self.baseline.get(CONF_EM_COMMON_METER, current[CONF_EM_COMMON_METER])
            if CONF_EM_COMMON_METER in current
            else None
        )
        hours = (now - self.baseline_time).total_seconds() / 3600 if self.baseline_time else 0.0
        common, shift = common_part(
            d_a, meter_delta, float(self._get(CONF_EM_COMMON_POWER, 0) or 0), hours, self.share_b("common")
        )
        part = split_interval(
            current[CONF_EM_GRID] - self.baseline[CONF_EM_GRID],
            current[CONF_EM_FEED] - self.baseline[CONF_EM_FEED],
            current[CONF_EM_PV] - self.baseline[CONF_EM_PV],
            d_a,
            current[CONF_EM_METER_B] - self.baseline[CONF_EM_METER_B],
            shift,
        )
        if part is None:
            return                                  # nichts verbraucht: weiter sammeln
        part["common"], part["common_b"] = common, shift
        key = self.month_key()
        self.months[key] = add_up(self.months.get(key), part)
        for old in sorted(self.months)[:-KEEP_MONTHS]:
            self.months.pop(old)
        self.totals = add_up(self.totals, part)
        self.baseline = current
        self.baseline_time = now
        await self._async_save()
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))
