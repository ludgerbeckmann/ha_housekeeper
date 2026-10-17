"""Logik der Funktion "Verbrauchswächter": meldet, wenn ein Verbrauch zu lange am Stück anliegt."""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CG_FROM,
    CONF_CG_MINUTES,
    CONF_CG_REPEAT,
    CONF_CG_SENSOR,
    CONF_CG_THRESHOLD,
    CONF_CG_TO,
    DEFAULT_CG_MINUTES,
    DOMAIN,
    signal_update,
)
from .notify import Notifier, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
CHECK_INTERVAL = timedelta(minutes=1)
_UNKNOWN = (STATE_UNAVAILABLE, STATE_UNKNOWN)

_TEXT = {
    "de": "„{title}“: {sensor} liegt seit {minutes} Minuten über {threshold} {unit} (aktuell {value} {unit}).",
    "en": "\"{title}\": {sensor} has been above {threshold} {unit} for {minutes} minutes (now {value} {unit}).",
}


# --- reine Funktionen ------------------------------------------------------------------------


def is_running(state: Any, threshold: float) -> bool | None:
    """Liegt der Wert über der Schwelle? `None` = unklar (fehlt, nicht verfügbar, keine Zahl)."""
    if state is None or state.state in _UNKNOWN:
        return None
    try:
        return float(state.state) > threshold
    except ValueError:
        return None


def in_window(start: str | None, end: str | None, now: dtime) -> bool:
    """Liegt die Uhrzeit im Zeitfenster? Ohne Fenster oder bei Von = Bis immer; über Mitternacht möglich."""
    first = dt_util.parse_time(str(start)) if start else None
    last = dt_util.parse_time(str(end)) if end else None
    if first is None or last is None or first == last:
        return True
    if first < last:
        return first <= now < last
    return now >= first or now < last


# --- Controller --------------------------------------------------------------------------------


class ConsumptionGuardController:
    """Überwacht einen Durchfluss- oder Leistungssensor."""

    model = "Verbrauchswächter"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.since: datetime | None = None      # seit wann der Wert über der Schwelle liegt
        self.warning = False
        self._acknowledged = False
        self._last_alert: datetime | None = None
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._notifier = Notifier(
            hass, self._get, f"{DOMAIN}_{entry.entry_id}", lambda: entry.title
        )
        self._unsubs: list[CALLBACK_TYPE] = []

    # --- Hilfen ------------------------------------------------------------

    @property
    def sensor(self) -> str | None:
        return self._get(CONF_CG_SENSOR)

    @property
    def threshold(self) -> float:
        return float(self._get(CONF_CG_THRESHOLD, 0))

    @property
    def duration(self) -> timedelta:
        return timedelta(minutes=float(self._get(CONF_CG_MINUTES, DEFAULT_CG_MINUTES)))

    @property
    def repeat(self) -> timedelta | None:
        minutes = float(self._get(CONF_CG_REPEAT, 0) or 0)
        return timedelta(minutes=minutes) if minutes > 0 else None

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_save(self) -> None:
        await self._store.async_save({"enabled": self.enabled})

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.enabled = bool(stored.get("enabled", True))
        if self.sensor:
            self._unsubs.append(
                async_track_state_change_event(self.hass, [self.sensor], self._on_change)
            )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_tick, CHECK_INTERVAL)
        )
        await self._async_evaluate()

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self._async_save()
        await self._async_evaluate()

    async def async_acknowledge(self) -> None:
        """Warnung quittieren: keine Wiederholung, bis der Verbrauch einmal unter die Schwelle fällt."""
        if not self.warning:
            return
        self._acknowledged = True
        self.warning = False
        await self._notifier.async_clear("warning")
        self._notify()

    # --- Auswertung ------------------------------------------------------------

    @callback
    def _on_change(self, event: Event) -> None:
        self.hass.async_create_task(self._async_evaluate())

    async def _on_tick(self, _now: datetime) -> None:
        await self._async_evaluate()

    async def _async_reset(self, *, keep_warning: bool = False) -> None:
        changed = self.since is not None
        self.since = None
        if keep_warning:
            if changed:
                self._notify()
            return
        self._acknowledged = False
        had_warning = self.warning
        self.warning = False
        self._last_alert = None
        if had_warning:
            await self._notifier.async_clear("warning")
        if changed or had_warning:
            self._notify()

    async def _async_evaluate(self) -> None:
        if not self.sensor:
            return
        if not self.enabled:
            await self._async_reset()
            return
        now = dt_util.utcnow()
        state = self.hass.states.get(self.sensor)
        running = is_running(state, self.threshold)
        if not in_window(
            self._get(CONF_CG_FROM), self._get(CONF_CG_TO), dt_util.now().time()
        ) or running is False:
            await self._async_reset()
            return
        if running is None:
            # unklar: keine Fehlalarme, eine bestehende Warnung bleibt
            await self._async_reset(keep_warning=self.warning)
            return
        if self.since is None:
            self.since = now
            self._notify()
        if self._acknowledged:
            return
        if not self.warning:
            if now - self.since >= self.duration:
                await self._async_alert(state, now)
        elif (repeat := self.repeat) and self._last_alert and now - self._last_alert >= repeat:
            await self._async_alert(state, now)

    async def _async_alert(self, state, now: datetime) -> None:
        self.warning = True
        self._last_alert = now
        self._notify()
        language = "de" if (self.hass.config.language or "").startswith("de") else "en"
        minutes = int((now - (self.since or now)).total_seconds() // 60)
        unit = state.attributes.get("unit_of_measurement") or ""
        value = state.state
        await self._notifier.async_send(
            _TEXT[language].format(
                title=self.entry.title,
                sensor=state.name,
                minutes=minutes,
                threshold=f"{self.threshold:g}",
                unit=unit,
                value=value,
            ).replace("  ", " "),
            kind="warning",
        )
