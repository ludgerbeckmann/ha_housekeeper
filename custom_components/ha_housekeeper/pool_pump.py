"""Logik der Funktion "Poolpumpe": Zeitplan, manueller Lauf, Trockenlauf-Erkennung.

Portiert aus `ludgerbeckmann/ha_pool_manager`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DRY_AUTO_OFF,
    CONF_DRY_DURATION,
    CONF_DRY_MAX_POWER,
    CONF_DRY_MIN_POWER,
    CONF_HEATER_ENTITY,
    CONF_HEATER_OFF_BELOW,
    CONF_HEATER_ON_ABOVE,
    CONF_POWER_ENTITY,
    CONF_PUMP_ENTITY,
    CONF_TEMP_ENTITY,
    CONF_WINDOWS,
    DEFAULT_DRY_DURATION,
    DEFAULT_DRY_MAX_POWER,
    DEFAULT_DRY_MIN_POWER,
    DEFAULT_HEATER_OFF_BELOW,
    DEFAULT_HEATER_ON_ABOVE,
    DOMAIN,
    signal_update,
)
from .notify import Notifier, entry_opt
from .pool_dry_run import DryRunDetector
from .pool_schedule import is_active, next_start, parse_windows
from .reload import ReloadWhenIdle

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
DRY_RUN_KIND = "dry_run"


class PoolPumpController(ReloadWhenIdle):
    """Verwaltet Zeitplan, manuellen Lauf und Laufzeitzähler einer Poolpumpe."""

    model = "Poolsteuerung"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._get = entry_opt(entry)
        self.pump_entity: str = self._get(CONF_PUMP_ENTITY)
        self.windows = parse_windows(self._get(CONF_WINDOWS, []))
        self.enabled = True
        self.manual_until: datetime | None = None

        self.power_entity: str | None = self._get(CONF_POWER_ENTITY) or None
        self.dry_auto_off: bool = bool(self._get(CONF_DRY_AUTO_OFF, False))
        self._detector = DryRunDetector(
            float(self._get(CONF_DRY_MIN_POWER, DEFAULT_DRY_MIN_POWER)),
            float(self._get(CONF_DRY_MAX_POWER, DEFAULT_DRY_MAX_POWER)),
            timedelta(minutes=float(self._get(CONF_DRY_DURATION, DEFAULT_DRY_DURATION))),
        )
        # Trockenlauf-Alarm bleibt gehalten, bis quittiert oder die Pumpe neu startet
        self.dry_run_detected = False
        self.dry_run_since: datetime | None = None
        self._paused_by_dry_run = False

        # Poolheizung: Schalter plus Temperatursensor mit zwei Schwellen (Hysterese)
        self.heater_entity: str | None = self._get(CONF_HEATER_ENTITY) or None
        self.temp_entity: str | None = self._get(CONF_TEMP_ENTITY) or None
        self.heater_on_above = float(self._get(CONF_HEATER_ON_ABOVE, DEFAULT_HEATER_ON_ABOVE))
        self.heater_off_below = float(self._get(CONF_HEATER_OFF_BELOW, DEFAULT_HEATER_OFF_BELOW))
        self.heater_auto = True
        self._heater_desired: bool | None = None
        self._heater_pending: bool | None = None

        self._last_desired: bool | None = None
        self._pending: bool | None = None
        self._manual_on = False
        self._unsubs: list[CALLBACK_TYPE] = []
        self._manual_unsub: CALLBACK_TYPE | None = None

        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._runtime_date = dt_util.now().date()
        self._runtime_seconds = 0.0
        self._on_since: datetime | None = None
        self._notifier = Notifier(
            hass, self._get, f"{DOMAIN}_{entry.entry_id}", self._alarm_title
        )

    # ------------------------------------------------------------------ Lebenszyklus

    async def async_start(self) -> None:
        """Zustand laden, Listener registrieren, erste Bewertung durchführen."""
        stored = await self._store.async_load() or {}
        now = dt_util.now()
        self.enabled = bool(stored.get("enabled", True))
        self.heater_auto = bool(stored.get("heater_auto", True))
        if stored.get("date") == now.date().isoformat():
            self._runtime_seconds = float(stored.get("seconds", 0))
        state = self.hass.states.get(self.pump_entity)
        if state is not None and state.state == STATE_ON:
            self._on_since = now

        self._unsubs.append(async_track_time_change(self.hass, self._tick, second=0))
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self.pump_entity], self._pump_changed
            )
        )
        if self.power_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.power_entity], self._power_changed
                )
            )
        if self.heater_configured:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.temp_entity], self._heater_input_changed
                )
            )
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.heater_entity], self._heater_input_changed
                )
            )
        await self._async_evaluate(now)

    async def async_stop(self) -> None:
        """Listener entfernen und Zustand sichern."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._manual_unsub:
            self._manual_unsub()
            self._manual_unsub = None
        await self._async_save()

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    async def _async_save(self) -> None:
        await self._store.async_save(self._store_data(dt_util.now()))

    # ------------------------------------------------------------------ Zustand

    @property
    def schedule_active(self) -> bool:
        return is_active(self.windows, dt_util.now())

    @property
    def busy(self) -> bool:
        """Manueller Lauf aktiv (wird nicht gespeichert und ginge beim Neuladen verloren)."""
        return self.manual_active

    @property
    def manual_active(self) -> bool:
        return self.manual_until is not None and dt_util.now() < self.manual_until

    @property
    def should_run(self) -> bool:
        """Soll die Pumpe laut Zeitplan bzw. manuellem Lauf gerade laufen?"""
        return self.manual_active or (self.enabled and self.schedule_active)

    @property
    def next_start(self) -> datetime | None:
        return next_start(self.windows, dt_util.now())

    def runtime_today_minutes(self) -> float:
        now = dt_util.now()
        seconds = self._runtime_seconds
        if self._on_since is not None:
            seconds += max((now - self._on_since).total_seconds(), 0)
        return round(seconds / 60, 1)

    # ------------------------------------------------------------------ Steuerung

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if enabled:
            # Bewusst wieder eingeschaltet: keine ausstehende Trockenlauf-Pause mehr
            self._paused_by_dry_run = False
        await self._async_save()
        await self._async_evaluate(dt_util.now())

    async def async_run_pump(self, minutes: float) -> None:
        """Pumpe unabhängig vom Zeitplan für `minutes` Minuten laufen lassen."""
        now = dt_util.now()
        self.manual_until = now + timedelta(minutes=minutes)
        if self._manual_unsub:
            self._manual_unsub()
        self._manual_unsub = async_track_point_in_time(
            self.hass, self._manual_expired, self.manual_until
        )
        await self._async_evaluate(now)

    # ------------------------------------------------------------------ Poolheizung

    @property
    def heater_configured(self) -> bool:
        return self.heater_entity is not None and self.temp_entity is not None

    @property
    def heater_should_run(self) -> bool:
        """Soll die Heizung laut Temperaturschwellen gerade laufen?"""
        return self.heater_auto and self._heater_desired is True

    def current_temperature(self) -> float | None:
        state = self.hass.states.get(self.temp_entity) if self.temp_entity else None
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    async def async_set_heater_auto(self, enabled: bool) -> None:
        """Heizungsautomatik ein- oder ausschalten (aus = die Heizung wird nie geschaltet)."""
        self.heater_auto = enabled
        self._heater_desired = None  # beim Einschalten neu bewerten
        self._heater_pending = None
        await self._async_save()
        await self._async_evaluate_heater()
        self._notify()

    async def _async_evaluate_heater(self) -> None:
        """Soll-Zustand der Heizung bestimmen; geschaltet wird nur beim Wechsel.

        Ab der Einschaltschwelle (oder darüber) ein, bei der Ausschaltschwelle (oder darunter)
        aus; dazwischen bleibt der Zustand, wie er ist. Ohne gültige Temperatur geschieht nichts,
        eine nicht erreichbare Heizung bleibt vorgemerkt.
        """
        if not self.heater_configured or not self.heater_auto:
            return
        temperature = self.current_temperature()
        desired: bool | None = None
        if temperature is not None:
            if temperature >= self.heater_on_above:
                desired = True
            elif temperature <= self.heater_off_below:
                desired = False
        if desired is not None and desired != self._heater_desired:
            self._heater_desired = desired
            self._heater_pending = desired
        if self._heater_pending is not None:
            await self._async_apply_heater(self._heater_pending)

    async def _async_apply_heater(self, desired: bool) -> None:
        state = self.hass.states.get(self.heater_entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.debug("Heizung %s nicht verfügbar, versuche es erneut", self.heater_entity)
            return
        if state.state == (STATE_ON if desired else STATE_OFF):
            self._heater_pending = None
            return
        try:
            await self.hass.services.async_call(
                "homeassistant",
                "turn_on" if desired else "turn_off",
                {ATTR_ENTITY_ID: self.heater_entity},
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - beim nächsten Durchlauf erneut versuchen
            _LOGGER.exception("Schalten der Heizung %s fehlgeschlagen", self.heater_entity)
            return
        self._heater_pending = None

    @callback
    def _heater_input_changed(self, event: Event) -> None:
        self.hass.async_create_task(self._async_heater_and_notify())

    async def _async_heater_and_notify(self) -> None:
        await self._async_evaluate_heater()
        self._notify()

    # ------------------------------------------------------------------ Trockenlauf

    @property
    def dry_run_configured(self) -> bool:
        return self.power_entity is not None

    @property
    def dry_run_paused_schedule(self) -> bool:
        return self._paused_by_dry_run

    def current_power(self) -> float | None:
        """Aktuelle Leistung in Watt (None, wenn nicht verfügbar)."""
        if not self.power_entity:
            return None
        state = self.hass.states.get(self.power_entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        if str(state.attributes.get("unit_of_measurement", "")).lower() == "kw":
            value *= 1000
        return value

    async def async_acknowledge_dry_run(self) -> None:
        """Alarm quittieren; ein durch den Trockenlauf pausierter Zeitplan läuft weiter."""
        self.dry_run_detected = False
        self.dry_run_since = None
        self._detector.reset()
        await self._notifier.async_clear(DRY_RUN_KIND)
        if self._paused_by_dry_run:
            self._paused_by_dry_run = False
            self.enabled = True
            self._last_desired = None  # Pumpe wieder an den Zeitplan angleichen
            await self._async_save()
        await self._async_evaluate(dt_util.now())

    async def _async_check_dry_run(self, now: datetime) -> None:
        if not self.power_entity:
            return
        pump = self.hass.states.get(self.pump_entity)
        pump_on = pump is not None and pump.state == STATE_ON
        due = self._detector.update(now, pump_on, self.current_power())
        if not due or self.dry_run_detected:
            return

        self.dry_run_detected = True
        self.dry_run_since = self._detector.since
        _LOGGER.warning("Trockenlauf erkannt an %s", self.pump_entity)
        if self.dry_auto_off:
            # Zeitplan pausieren, manuellen Lauf beenden, Pumpe ausschalten
            self.enabled = False
            self._paused_by_dry_run = True
            self.manual_until = None
            self._manual_on = False
            self._pending = None
            if self._manual_unsub:
                self._manual_unsub()
                self._manual_unsub = None
            await self._async_save()
            try:
                await self.hass.services.async_call(
                    "homeassistant",
                    "turn_off",
                    {ATTR_ENTITY_ID: self.pump_entity},
                    blocking=True,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Abschalten der Pumpe %s fehlgeschlagen", self.pump_entity)
        await self._notifier.async_send(self._alarm_message(), kind=DRY_RUN_KIND)

    def _german(self) -> bool:
        return (self.hass.config.language or "").startswith("de")

    def _alarm_title(self) -> str:
        if self._german():
            return f"Pool: Pumpe läuft trocken ({self.entry.title})"
        return f"Pool: pump running dry ({self.entry.title})"

    def _alarm_message(self) -> str:
        power = self.current_power()
        watt = f"{power:.0f} W" if power is not None else "?"
        minutes = self._detector.duration.total_seconds() / 60
        low, high = self._detector.minimum, self._detector.maximum
        if self._german():
            message = (
                f"Die Leistung von {self.pump_entity} lag {minutes:g} Minuten lang "
                f"im Trockenlauf-Bereich ({low:g}–{high:g} W, zuletzt {watt})."
            )
            if self.dry_auto_off:
                message += " Die Pumpe wurde ausgeschaltet und der Zeitplan pausiert."
        else:
            message = (
                f"The power of {self.pump_entity} stayed in the dry-run range for "
                f"{minutes:g} minutes ({low:g}-{high:g} W, last {watt})."
            )
            if self.dry_auto_off:
                message += " The pump was switched off and the schedule paused."
        return message

    # ------------------------------------------------------------------ intern

    async def _manual_expired(self, _now: datetime) -> None:
        self._manual_unsub = None
        await self._async_evaluate(dt_util.now())
        self.async_idle()

    async def _tick(self, now: datetime) -> None:
        await self._async_evaluate(dt_util.as_local(now))
        self.async_idle()

    def _roll_day(self, now: datetime) -> None:
        """Tageszähler bei Datumswechsel zurücksetzen."""
        if now.date() == self._runtime_date:
            return
        self._runtime_date = now.date()
        self._runtime_seconds = 0.0
        if self._on_since is not None:
            self._on_since = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def _store_data(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or dt_util.now()
        seconds = self._runtime_seconds
        if self._on_since is not None:
            seconds += max((now - self._on_since).total_seconds(), 0)
        return {
            "date": self._runtime_date.isoformat(),
            "seconds": seconds,
            "enabled": self.enabled,
            "heater_auto": self.heater_auto,
        }

    async def _async_evaluate(self, now: datetime) -> None:
        """Soll-Zustand bestimmen und bei Wechsel auf die Pumpe anwenden.

        Es wird nur bei einem *Wechsel* des Soll-Zustands geschaltet - manuelle
        Eingriffe an der Pumpe bleiben daher bis zum nächsten Fensterwechsel
        bestehen. Ist die Pumpe gerade `unavailable`, bleibt der Wechsel
        vorgemerkt und wird beim nächsten Durchlauf erneut versucht.
        """
        self._roll_day(now)
        await self._async_check_dry_run(now)
        if self.manual_until is not None and now >= self.manual_until:
            self.manual_until = None

        scheduled = is_active(self.windows, now)
        desired: bool | None
        if self.manual_until is not None:
            desired = True
            self._manual_on = True
        elif self._manual_on:
            # Manueller Lauf ist gerade zu Ende gegangen
            desired = scheduled if self.enabled else False
            self._manual_on = False
        elif self.enabled and self.windows:
            desired = scheduled
        else:
            desired = None

        if desired is not None and desired != self._last_desired:
            self._last_desired = desired
            self._pending = desired

        if self._pending is not None:
            await self._async_apply(self._pending)

        await self._async_evaluate_heater()
        self._notify()

    async def _async_apply(self, desired: bool) -> None:
        state = self.hass.states.get(self.pump_entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.debug("Pumpe %s nicht verfügbar, versuche es erneut", self.pump_entity)
            return
        if state.state == (STATE_ON if desired else STATE_OFF):
            self._pending = None
            return
        try:
            await self.hass.services.async_call(
                "homeassistant",
                "turn_on" if desired else "turn_off",
                {ATTR_ENTITY_ID: self.pump_entity},
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - beim nächsten Durchlauf erneut versuchen
            _LOGGER.exception("Schalten der Pumpe %s fehlgeschlagen", self.pump_entity)
            return
        self._pending = None

    @callback
    def _pump_changed(self, event: Event) -> None:
        """Laufzeit mitführen, wenn sich der Pumpenzustand ändert."""
        now = dt_util.now()
        self._roll_day(now)
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        is_on = new is not None and new.state == STATE_ON
        if is_on and (old is None or old.state != STATE_ON) and self.dry_run_detected:
            # Pumpe wurde neu gestartet: Alarm zurücknehmen, die Erkennung beginnt neu
            self.dry_run_detected = False
            self.dry_run_since = None
            self._detector.reset()
        if is_on and self._on_since is None:
            self._on_since = now
        elif not is_on and self._on_since is not None:
            self._runtime_seconds += max((now - self._on_since).total_seconds(), 0)
            self._on_since = None
            self._store.async_delay_save(self._store_data, 60)
        if new is not None and new.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            if self._pending is not None:
                self.hass.async_create_task(self._async_apply(self._pending))
        self._notify()

    @callback
    def _power_changed(self, event: Event) -> None:
        self.hass.async_create_task(self._async_dry_run_and_notify())

    async def _async_dry_run_and_notify(self) -> None:
        await self._async_check_dry_run(dt_util.now())
        self._notify()

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))
