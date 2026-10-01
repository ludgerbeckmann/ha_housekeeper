"""Logik der Funktion "Wecker": Ton auf Media Playern, kritische Push-Meldung, Stopp und Schlummern."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    A_AUTO_STOP,
    A_ENABLED,
    A_ID,
    A_MEDIA,
    A_NAME,
    A_PLAYERS,
    A_SNOOZE,
    A_TIME,
    A_VOLUME,
    A_WEEKDAYS,
    ALARM_ACTION_SNOOZE_PREFIX,
    ALARM_ACTION_STOP_PREFIX,
    CONF_ALARMS,
    CONF_CRITICAL,
    CONF_MESSAGE,
    DEFAULT_ALARM_AUTO_STOP,
    DEFAULT_ALARM_MESSAGE,
    DEFAULT_ALARM_SNOOZE,
    DOMAIN,
    MOBILE_ACTION_EVENT,
    WEEKDAYS,
    signal_update,
)
from .notify import Notifier, async_safe_call, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1

PHASE_RINGING = "ringing"
PHASE_SNOOZED = "snoozed"

_TEXT = {
    "de": {
        "stop": "Stoppen",
        "snooze": "Schlummern",
        "players": "Player",
        "off": "aus",
    },
    "en": {
        "stop": "Stop",
        "snooze": "Snooze",
        "players": "players",
        "off": "off",
    },
}


def _text(hass: HomeAssistant) -> dict[str, str]:
    return _TEXT["de" if (hass.config.language or "").startswith("de") else "en"]


def alarm_summary(hass: HomeAssistant, alarm: dict[str, Any]) -> str:
    """Kurzbeschreibung eines Weckers für Listen im Options-Flow."""
    text = _text(hass)
    days = alarm.get(A_WEEKDAYS) or WEEKDAYS
    day_text = "" if len(days) == 7 else f" ({', '.join(days)})"
    off = "" if alarm.get(A_ENABLED, True) else f", {text['off']}"
    return (
        f"{alarm.get(A_NAME)}: {str(alarm.get(A_TIME, ''))[:5]}{day_text}, "
        f"{len(alarm.get(A_PLAYERS) or [])} {text['players']}, "
        f"{int(alarm.get(A_VOLUME) or 0)} %{off}"
    )


def next_alarm(
    alarms: list[dict[str, Any]], now: datetime
) -> tuple[datetime, dict[str, Any]] | None:
    """Nächster Weckzeitpunkt aller aktiven Wecker nach `now` (lokale Zeit)."""
    best: tuple[datetime, dict[str, Any]] | None = None
    for alarm in alarms:
        if not alarm.get(A_ENABLED, True):
            continue
        at = dt_util.parse_time(str(alarm.get(A_TIME, "")))
        if at is None:
            continue
        days = alarm.get(A_WEEKDAYS) or WEEKDAYS
        for offset in range(8):
            day = now + timedelta(days=offset)
            if WEEKDAYS[day.weekday()] not in days:
                continue
            candidate = day.replace(
                hour=at.hour, minute=at.minute, second=at.second, microsecond=0
            )
            if candidate > now:
                if best is None or candidate < best[0]:
                    best = (candidate, alarm)
                break
    return best


def critical_data() -> dict[str, Any]:
    """Zusatzdaten der Push-Meldung für eine kritische Meldung (iOS und Android)."""
    return {
        # iOS: durchbricht „Nicht stören“ und die Stummschaltung
        "push": {
            "sound": {"name": "default", "critical": 1, "volume": 1.0},
            "interruption-level": "critical",
        },
        # Android: Alarm-Kanal mit hoher Priorität, bleibt stehen
        "channel": "alarm_stream",
        "importance": "high",
        "priority": "high",
        "ttl": 0,
        "sticky": "true",
    }


class AlarmClockController:
    """Löst die Wecker aus und bedient Stopp und Schlummern."""

    model = "Wecker"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.phase: str | None = None
        self.current: dict[str, Any] | None = None   # laufender Wecker
        self.snooze_until: datetime | None = None
        self.last_ring: datetime | None = None
        self.last_alarm: str | None = None
        self._restore: dict[str, float | None] = {}  # ursprüngliche Lautstärken
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._notifier = Notifier(
            hass, self._get, f"{DOMAIN}_{entry.entry_id}", lambda: entry.title
        )
        self._unsubs: list[CALLBACK_TYPE] = []
        self._auto_stop_unsub: CALLBACK_TYPE | None = None
        self._snooze_unsub: CALLBACK_TYPE | None = None

    # --- Hilfen ------------------------------------------------------------

    @property
    def alarms(self) -> list[dict[str, Any]]:
        return list(self._get(CONF_ALARMS, []) or [])

    @property
    def ringing(self) -> bool:
        return self.phase == PHASE_RINGING

    @property
    def active(self) -> bool:
        return self.phase is not None

    @property
    def next_alarm(self) -> tuple[datetime, dict[str, Any]] | None:
        return next_alarm(self.alarms, dt_util.now()) if self.enabled else None

    @property
    def stop_action_id(self) -> str:
        return f"{ALARM_ACTION_STOP_PREFIX}{self.entry.entry_id}"

    @property
    def snooze_action_id(self) -> str:
        return f"{ALARM_ACTION_SNOOZE_PREFIX}{self.entry.entry_id}"

    def alarm(self, alarm_id: str) -> dict[str, Any] | None:
        return next((a for a in self.alarms if a.get(A_ID) == alarm_id), None)

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "enabled": self.enabled,
                "last_ring": self.last_ring.isoformat() if self.last_ring else None,
                "last_alarm": self.last_alarm,
                "restore": self._restore,
            }
        )
        self._notify()

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.enabled = bool(stored.get("enabled", True))
        self.last_alarm = stored.get("last_alarm")
        if raw := stored.get("last_ring"):
            self.last_ring = dt_util.parse_datetime(raw)
        # Wurde Home Assistant während des Weckens neu gestartet, die Lautstärke zurücksetzen
        self._restore = dict(stored.get("restore") or {})
        if self._restore:
            await self._async_restore_volumes()
            self._restore = {}
            await self._async_save()

        for alarm in self.alarms:
            at = dt_util.parse_time(str(alarm.get(A_TIME, "")))
            if at is None:
                _LOGGER.warning("Wecker %s: ungültige Uhrzeit", alarm.get(A_NAME))
                continue

            @callback
            def _on_time(now: datetime, alarm=alarm) -> None:
                days = alarm.get(A_WEEKDAYS) or WEEKDAYS
                if (
                    self.enabled
                    and alarm.get(A_ENABLED, True)
                    and WEEKDAYS[dt_util.as_local(now).weekday()] in days
                ):
                    self.hass.async_create_task(self.async_ring(alarm))

            self._unsubs.append(
                async_track_time_change(
                    self.hass, _on_time, hour=at.hour, minute=at.minute, second=at.second
                )
            )
        self._unsubs.append(
            self.hass.bus.async_listen(MOBILE_ACTION_EVENT, self._on_mobile_action)
        )

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_timers()
        if self.active:
            await self._async_stop_sound()

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled and self.active:
            await self.async_stop_alarm()
            return
        await self._async_save()

    # --- Ton und Lautstärke -----------------------------------------------------

    def _players(self) -> list[str]:
        return list((self.current or {}).get(A_PLAYERS) or [])

    async def _async_start_sound(self) -> None:
        """Ursprüngliche Lautstärke merken, Lautstärke setzen, Datei abspielen."""
        alarm = self.current or {}
        players = self._players()
        self._restore = {}
        for player in players:
            state = self.hass.states.get(player)
            level = state.attributes.get("volume_level") if state else None
            self._restore[player] = float(level) if level is not None else None
        await self._async_save()

        volume = alarm.get(A_VOLUME)
        if volume is not None and players:
            await async_safe_call(
                self.hass, "media_player", "volume_set",
                {"entity_id": players, "volume_level": float(volume) / 100},
            )
        media = alarm.get(A_MEDIA) or {}
        if not media.get("media_content_id"):
            _LOGGER.warning("Wecker %s: keine Audiodatei gewählt", alarm.get(A_NAME))
            return
        await async_safe_call(
            self.hass, "media_player", "play_media",
            {
                "entity_id": players,
                "media_content_id": media["media_content_id"],
                "media_content_type": media.get("media_content_type", "music"),
            },
        )

    async def _async_stop_sound(self) -> None:
        """Wiedergabe beenden und die ursprüngliche Lautstärke wiederherstellen."""
        if players := self._players():
            await async_safe_call(
                self.hass, "media_player", "media_stop", {"entity_id": players}
            )
        await self._async_restore_volumes()
        self._restore = {}

    async def _async_restore_volumes(self) -> None:
        for player, level in self._restore.items():
            if level is None:
                continue
            await async_safe_call(
                self.hass, "media_player", "volume_set",
                {"entity_id": player, "volume_level": level},
            )

    # --- Ablauf --------------------------------------------------------------------

    def _cancel_timers(self) -> None:
        for name in ("_auto_stop_unsub", "_snooze_unsub"):
            if unsub := getattr(self, name):
                unsub()
                setattr(self, name, None)

    async def async_ring(self, alarm: dict[str, Any]) -> None:
        """Wecker auslösen; ein noch laufender Alarm wird vorher beendet."""
        if self.active:
            await self.async_stop_alarm()
        self.current = alarm
        self.last_ring = dt_util.utcnow()
        self.last_alarm = alarm.get(A_NAME)
        self.snooze_until = None
        await self._async_begin_ringing()

    async def _async_begin_ringing(self) -> None:
        alarm = self.current or {}
        self.phase = PHASE_RINGING
        self.snooze_until = None
        self._notify()
        await self._async_start_sound()
        await self._async_send_push()
        minutes = float(alarm.get(A_AUTO_STOP, DEFAULT_ALARM_AUTO_STOP) or 0)
        if minutes > 0:
            async def _auto_stop(_now: datetime) -> None:
                self._auto_stop_unsub = None
                await self.async_stop_alarm()

            self._auto_stop_unsub = async_call_later(self.hass, minutes * 60, _auto_stop)

    async def _async_send_push(self) -> None:
        text = _text(self.hass)
        alarm = self.current or {}
        message = self._get(CONF_MESSAGE) or DEFAULT_ALARM_MESSAGE
        if name := alarm.get(A_NAME):
            message = f"{message}: {name}" if message != name else message
        actions = [
            {"action": self.stop_action_id, "title": text["stop"]},
            {"action": self.snooze_action_id, "title": text["snooze"]},
        ]
        extra = critical_data() if self._get(CONF_CRITICAL, True) else None
        await self._notifier.async_send(message, actions=actions, extra=extra)

    async def async_stop_alarm(self) -> None:
        """Wecker stoppen: Ton aus, Lautstärke zurück, Meldung entfernen."""
        if not self.active:
            return
        self._cancel_timers()
        await self._async_stop_sound()
        self.phase = None
        self.snooze_until = None
        self.current = None
        await self._notifier.async_clear()
        await self._async_save()

    async def async_snooze(self) -> None:
        """Schlummern: Ton aus und Lautstärke zurück, nach der Schlummerzeit erneut wecken."""
        if self.phase != PHASE_RINGING:
            return
        alarm = self.current or {}
        self._cancel_timers()
        await self._async_stop_sound()
        minutes = float(alarm.get(A_SNOOZE, DEFAULT_ALARM_SNOOZE) or DEFAULT_ALARM_SNOOZE)
        self.phase = PHASE_SNOOZED
        self.snooze_until = dt_util.utcnow() + timedelta(minutes=minutes)
        await self._notifier.async_clear()
        await self._async_save()

        async def _resume(_now: datetime) -> None:
            self._snooze_unsub = None
            if self.phase == PHASE_SNOOZED:
                await self._async_begin_ringing()

        self._snooze_unsub = async_call_later(self.hass, minutes * 60, _resume)

    @callback
    def _on_mobile_action(self, event: Event) -> None:
        action = event.data.get("action")
        if action == self.stop_action_id:
            self.hass.async_create_task(self.async_stop_alarm())
        elif action == self.snooze_action_id:
            self.hass.async_create_task(self.async_snooze())
