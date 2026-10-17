"""Logik der Funktion "LLM-Verbrauch": Kosten und Restguthaben eines LLM-API-Kontos überwachen."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import llm_providers
from .const import (
    CONF_API_KEY,
    CONF_DAILY_LIMIT,
    CONF_FORECAST_WARNING,
    CONF_LLM_AMOUNT,
    CONF_LLM_BASELINE,
    CONF_LLM_MODE,
    CONF_LOW_BALANCE,
    CONF_MONTHLY_LIMIT,
    CONF_POLL_MINUTES,
    CONF_PROVIDER,
    CONF_TRACK_USAGE,
    DEFAULT_POLL_MINUTES,
    DOMAIN,
    LLM_MODE_BALANCE,
    LLM_MODE_BUDGET,
    signal_update,
)
from .llm_providers import ProviderAuthError, ProviderError
from .notify import Notifier, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
START_DELAY = 5            # Sekunden nach dem Start bis zur ersten Abfrage
FAILURES_BEFORE_ALERT = 3  # Fehlschläge in Folge bis zur Meldung (Key-Fehler sofort)
RECHECK_DAYS = 2           # so viele Tage vor dem letzten bekannten Tag werden neu geladen
KEEP_DAYS = 400
AVERAGE_DAYS = 7

_TEXT = {
    "de": {
        "low": "Guthaben von „{title}“ niedrig: noch {value} {currency} (Grenze {limit} {currency}).",
        "low_ok": "Guthaben von „{title}“ liegt wieder über der Grenze: {value} {currency}.",
        "daily": "„{title}“: Tageslimit überschritten, heute {value} {currency} (Limit {limit} {currency}).",
        "monthly": "„{title}“: Monatslimit überschritten, {value} {currency} in diesem Monat (Limit {limit} {currency}).",
        "error": "„{title}“: Abfrage fehlgeschlagen ({error}).",
        "error_ok": "„{title}“: Die Abfrage funktioniert wieder.",
        "forecast": "„{title}“: Prognose {value} {currency} bis Monatsende, über dem Limit von {limit} {currency}.",
    },
    "en": {
        "low": "Balance of \"{title}\" is low: {value} {currency} left (threshold {limit} {currency}).",
        "low_ok": "Balance of \"{title}\" is above the threshold again: {value} {currency}.",
        "daily": "\"{title}\": daily limit exceeded, {value} {currency} today (limit {limit} {currency}).",
        "monthly": "\"{title}\": monthly limit exceeded, {value} {currency} this month (limit {limit} {currency}).",
        "error": "\"{title}\": query failed ({error}).",
        "error_ok": "\"{title}\": the query works again.",
        "forecast": "\"{title}\": forecast {value} {currency} by the end of the month, above the limit of {limit} {currency}.",
    },
}


# --- reine Funktionen ------------------------------------------------------------------------


def sum_days(days: dict[str, float], start: date, end: date) -> float:
    """Summe der Tageskosten von `start` bis `end` (beide eingeschlossen)."""
    total = 0.0
    day = start
    while day <= end:
        total += days.get(day.isoformat(), 0.0)
        day += timedelta(days=1)
    return total


def month_start(day: date) -> date:
    return day.replace(day=1)


def cost_today(days: dict[str, float], today: date) -> float:
    return days.get(today.isoformat(), 0.0)


def cost_month(days: dict[str, float], today: date) -> float:
    return sum_days(days, month_start(today), today)


def average_daily(days: dict[str, float], today: date) -> float:
    """Durchschnittliche Tageskosten der letzten 7 abgeschlossenen Tage (ohne heute)."""
    return sum_days(days, today - timedelta(days=AVERAGE_DAYS), today - timedelta(days=1)) / AVERAGE_DAYS


def forecast_month(days: dict[str, float], today: date) -> float:
    """Erwartete Kosten bis Monatsende: bisherige Kosten, der Rest von heute und die übrigen Tage
    des Monats, jeweils mit dem Durchschnitt der letzten abgeschlossenen Tage."""
    average = average_daily(days, today)
    days_after_today = calendar.monthrange(today.year, today.month)[1] - today.day
    rest_today = max(average - cost_today(days, today), 0.0)
    return cost_month(days, today) + rest_today + average * days_after_today


def sum_usage(usage: dict[str, dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    """Tokens (und Anfragen) von `start` bis `end` (beide eingeschlossen)."""
    total: dict[str, Any] = {"input": 0, "output": 0, "cached": 0, "requests": None}
    day = start
    while day <= end:
        item = usage.get(day.isoformat())
        if item:
            for key in ("input", "output", "cached"):
                total[key] += item.get(key) or 0
            if item.get("requests") is not None:
                total["requests"] = (total["requests"] or 0) + item["requests"]
        day += timedelta(days=1)
    return total


def remaining_balance(
    mode: str,
    amount: float | None,
    days: dict[str, float],
    today: date,
    baseline_day: date | None,
    snapshot: float | None,
) -> float | None:
    """Restguthaben bzw. Restbudget; `None`, solange es nicht berechenbar ist.

    Guthaben-Modus: Betrag beim Abgleich minus die Kosten seit dem Abgleich (die Kosten des
    Abgleichtags zählen nur, soweit sie über den beim ersten Abruf gemerkten Stand hinausgehen).
    Budget-Modus: Betrag minus die Kosten des laufenden Monats."""
    if amount is None:
        return None
    if mode == LLM_MODE_BALANCE:
        if baseline_day is None or snapshot is None:
            return None
        spent = days.get(baseline_day.isoformat(), 0.0) - snapshot
        spent += sum_days(days, baseline_day + timedelta(days=1), today)
        return amount - spent
    return amount - cost_month(days, today)


def days_left(remaining: float | None, average: float) -> float | None:
    """Reichweite des Restguthabens in Tagen bei den durchschnittlichen Tageskosten."""
    if remaining is None or average <= 0:
        return None
    return max(remaining, 0.0) / average


class LlmUsageController:
    """Fragt die Kosten eines LLM-Kontos ab, berechnet das Restguthaben und warnt."""

    model = "LLM-Verbrauch"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.currency = "USD"
        self.days: dict[str, float] = {}
        self.days_from: str | None = None
        self.usage: dict[str, dict[str, Any]] = {}
        self.snapshot: dict[str, Any] | None = None
        self.alerts: dict[str, Any] = {}
        self.failures = 0
        self.error: str | None = None
        self.last_update: datetime | None = None
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list[CALLBACK_TYPE] = []
        self._refreshing = False

    # --- Einstellungen und Werte ------------------------------------------------------------

    def _opt(self, key: str, default: Any = None) -> Any:
        return self._get(key, default)

    def _text(self) -> dict[str, str]:
        return _TEXT["de" if (self.hass.config.language or "").startswith("de") else "en"]

    def _notifier(self) -> Notifier:
        return Notifier(
            self.hass, self._get, f"{DOMAIN}_{self.entry.entry_id}", lambda: self.entry.title
        )

    @property
    def track_usage(self) -> bool:
        return bool(self._opt(CONF_TRACK_USAGE, False))

    @property
    def has_requests(self) -> bool:
        """Nur OpenAI liefert die Anzahl der Anfragen."""
        return self._opt(CONF_PROVIDER) == "openai"

    @property
    def usage_today(self) -> dict[str, Any]:
        return sum_usage(self.usage, self._today, self._today)

    @property
    def usage_month(self) -> dict[str, Any]:
        return sum_usage(self.usage, month_start(self._today), self._today)

    @property
    def forecast(self) -> float:
        return forecast_month(self.days, self._today)

    @property
    def mode(self) -> str:
        return self._opt(CONF_LLM_MODE, LLM_MODE_BALANCE)

    @property
    def amount(self) -> float | None:
        value = self._opt(CONF_LLM_AMOUNT)
        return None if value is None else float(value)

    @property
    def _baseline(self) -> datetime | None:
        value = self._opt(CONF_LLM_BASELINE)
        parsed = dt_util.parse_datetime(str(value)) if value else None
        return dt_util.as_utc(parsed) if parsed else None

    @property
    def _today(self) -> date:
        return dt_util.utcnow().date()

    @property
    def cost_today(self) -> float:
        return cost_today(self.days, self._today)

    @property
    def cost_month(self) -> float:
        return cost_month(self.days, self._today)

    @property
    def remaining(self) -> float | None:
        baseline = self._baseline
        snapshot = (
            self.snapshot["day_cost"]
            if self.snapshot and baseline and self.snapshot.get("time") == baseline.isoformat()
            else None
        )
        return remaining_balance(
            self.mode,
            self.amount,
            self.days,
            self._today,
            baseline.date() if baseline else None,
            snapshot,
        )

    @property
    def days_left(self) -> float | None:
        return days_left(self.remaining, average_daily(self.days, self._today))

    @property
    def active_alerts(self) -> list[str]:
        """Aktuell bestehende Warnungen (`low`, `daily`, `monthly`, `error`)."""
        today = self._today
        found = []
        if self.alerts.get("low"):
            found.append("low")
        if self.alerts.get("daily") == today.isoformat():
            found.append("daily")
        if self.alerts.get("monthly") == today.strftime("%Y-%m"):
            found.append("monthly")
        if self.alerts.get("forecast") == today.strftime("%Y-%m"):
            found.append("forecast")
        if self.alerts.get("error"):
            found.append("error")
        return found

    # --- Lebenszyklus --------------------------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.enabled = bool(stored.get("enabled", True))
        self.currency = stored.get("currency", "USD")
        self.days = dict(stored.get("days") or {})
        self.days_from = stored.get("days_from")
        self.usage = dict(stored.get("usage") or {})
        self.snapshot = stored.get("snapshot")
        self.alerts = dict(stored.get("alerts") or {})
        self.failures = int(stored.get("failures", 0))
        self.error = stored.get("error")
        if stored.get("last_update"):
            self.last_update = dt_util.parse_datetime(stored["last_update"])

        async def _tick(_now: datetime) -> None:
            await self.async_refresh()

        interval = float(self._opt(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES))
        self._unsubs.append(
            async_track_time_interval(self.hass, _tick, timedelta(minutes=interval))
        )
        self._unsubs.append(async_call_later(self.hass, START_DELAY, _tick))

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "enabled": self.enabled,
                "currency": self.currency,
                "days": self.days,
                "days_from": self.days_from,
                "usage": self.usage,
                "snapshot": self.snapshot,
                "alerts": self.alerts,
                "failures": self.failures,
                "error": self.error,
                "last_update": self.last_update.isoformat() if self.last_update else None,
            }
        )
        self._notify()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self._async_save()

    # --- Abfrage -------------------------------------------------------------------------------

    def _needed_from(self, today: date) -> date:
        """Ältester Tag, dessen Kosten für die Werte gebraucht werden."""
        needed = min(month_start(today), today - timedelta(days=AVERAGE_DAYS))
        baseline = self._baseline
        if self.mode == LLM_MODE_BALANCE and baseline:
            needed = min(needed, baseline.date())
        return needed

    async def async_refresh(self) -> None:
        """Kosten abfragen, Werte berechnen und Warnungen prüfen."""
        if not self.enabled or self._refreshing:
            return
        self._refreshing = True
        try:
            await self._async_refresh()
        finally:
            self._refreshing = False

    async def _async_refresh(self) -> None:
        today = self._today
        needed = self._needed_from(today)
        fetch_from = needed
        if self.days and self.days_from and date.fromisoformat(self.days_from) <= needed:
            newest = max(date.fromisoformat(d) for d in self.days)
            fetch_from = max(needed, newest - timedelta(days=RECHECK_DAYS))
        try:
            currency, fetched = await llm_providers.async_fetch_costs(
                async_get_clientsession(self.hass),
                self._opt(CONF_PROVIDER),
                str(self._opt(CONF_API_KEY, "")).strip(),
                fetch_from,
            )
        except ProviderAuthError as err:
            await self._async_failed(str(err), immediate=True)
            return
        except ProviderError as err:
            await self._async_failed(str(err))
            return

        self.currency = currency
        self.days.update(fetched)
        earliest = fetch_from.isoformat()  # die Anbieter liefern jeden Tag, auch ohne Kosten
        self.days_from = min(self.days_from or earliest, earliest)
        cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
        self.days = {d: v for d, v in self.days.items() if d >= cutoff}
        self.last_update = dt_util.utcnow()
        baseline = self._baseline
        if self.mode == LLM_MODE_BALANCE and baseline:
            if not self.snapshot or self.snapshot.get("time") != baseline.isoformat():
                self.snapshot = {
                    "time": baseline.isoformat(),
                    "day_cost": self.days.get(baseline.date().isoformat(), 0.0),
                }
        if self.track_usage:
            await self._async_refresh_usage(today)
        else:
            self.usage = {}
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
        was_failing = bool(self.alerts.get("error"))
        self.failures = 0
        self.error = None
        self.alerts["error"] = False
        if was_failing:
            await self._notifier().async_send(
                self._text()["error_ok"].format(title=self.entry.title), kind="error"
            )
        await self._async_check_alerts(today)
        await self._async_save()

    async def _async_refresh_usage(self, today: date) -> None:
        """Tokens und Anfragen des Monats abfragen; ein Fehler hier stört die Kosten nicht."""
        try:
            fetched = await llm_providers.async_fetch_usage(
                async_get_clientsession(self.hass),
                self._opt(CONF_PROVIDER),
                str(self._opt(CONF_API_KEY, "")).strip(),
                month_start(today),
            )
        except ProviderError as err:
            _LOGGER.warning("%s: Abfrage der Tokens fehlgeschlagen: %s", self.entry.title, err)
            return
        self.usage.update(fetched)
        cutoff = month_start(today).isoformat()
        self.usage = {d: v for d, v in self.usage.items() if d >= cutoff}

    @property
    def _issue_id(self) -> str:
        return f"{self.entry.entry_id}_llm_auth"

    async def _async_failed(self, error: str, immediate: bool = False) -> None:
        self.failures += 1
        self.error = error
        _LOGGER.warning("%s: Abfrage fehlgeschlagen: %s", self.entry.title, error)
        if immediate:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="llm_auth_failed",
                translation_placeholders={"entry": self.entry.title},
            )
        if (immediate or self.failures >= FAILURES_BEFORE_ALERT) and not self.alerts.get("error"):
            self.alerts["error"] = True
            await self._notifier().async_send(
                self._text()["error"].format(title=self.entry.title, error=error), kind="error"
            )
        await self._async_save()

    # --- Warnungen ----------------------------------------------------------------------------

    async def _async_check_alerts(self, today: date) -> None:
        """Warnungen auslösen (einmal je Überschreitung) und die Entwarnung des Guthabens melden."""
        text = self._text()
        notifier = self._notifier()
        cur = self.currency
        title = self.entry.title

        low = self._opt(CONF_LOW_BALANCE)
        remaining = self.remaining
        if low is not None and remaining is not None:
            if remaining < float(low) and not self.alerts.get("low"):
                self.alerts["low"] = True
                await notifier.async_send(
                    text["low"].format(
                        title=title, value=f"{remaining:.2f}", limit=f"{float(low):.2f}", currency=cur
                    ),
                    kind="low",
                )
            elif remaining >= float(low) and self.alerts.get("low"):
                self.alerts["low"] = False
                await notifier.async_clear("low")
                await notifier.async_send(
                    text["low_ok"].format(title=title, value=f"{remaining:.2f}", currency=cur),
                    kind="low_ok",
                )
        elif low is None:
            self.alerts["low"] = False

        daily = self._opt(CONF_DAILY_LIMIT)
        if daily is not None and self.cost_today > float(daily):
            if self.alerts.get("daily") != today.isoformat():
                self.alerts["daily"] = today.isoformat()
                await notifier.async_send(
                    text["daily"].format(
                        title=title,
                        value=f"{self.cost_today:.2f}",
                        limit=f"{float(daily):.2f}",
                        currency=cur,
                    ),
                    kind="daily",
                )

        monthly = self._opt(CONF_MONTHLY_LIMIT)
        month = today.strftime("%Y-%m")
        # Prognose: gegen das Monatslimit, im Modus Monatsbudget sonst gegen das Budget
        forecast_limit = monthly
        if forecast_limit is None and self.mode == LLM_MODE_BUDGET:
            forecast_limit = self.amount
        if (
            self._opt(CONF_FORECAST_WARNING, True)
            and forecast_limit is not None
            and self.alerts.get("forecast") != month
            and self.cost_month <= float(forecast_limit)  # schon überschritten: Monatslimit meldet
            and self.forecast > float(forecast_limit)
        ):
            self.alerts["forecast"] = month
            await notifier.async_send(
                text["forecast"].format(
                    title=title,
                    value=f"{self.forecast:.2f}",
                    limit=f"{float(forecast_limit):.2f}",
                    currency=cur,
                ),
                kind="forecast",
            )
        if monthly is not None and self.cost_month > float(monthly):
            if self.alerts.get("monthly") != month:
                self.alerts["monthly"] = month
                await notifier.async_send(
                    text["monthly"].format(
                        title=title,
                        value=f"{self.cost_month:.2f}",
                        limit=f"{float(monthly):.2f}",
                        currency=cur,
                    ),
                    kind="monthly",
                )
