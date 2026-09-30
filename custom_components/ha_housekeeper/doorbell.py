"""Logik der Funktion "Türklingel"."""

from __future__ import annotations

import asyncio
from datetime import datetime, time as dtime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLEAR_HOURS,
    CONF_DEBOUNCE,
    CONF_MESSAGE,
    CONF_PROFILES,
    CONF_TRIGGER_ENTITY,
    DEFAULT_CLEAR_HOURS,
    DEFAULT_RING_DEBOUNCE,
    DEFAULT_RING_MESSAGE,
    DOMAIN,
    MODE_TTS,
    P_FROM,
    P_MEDIA,
    P_MODE,
    P_NAME,
    P_PLAYERS,
    P_TEXT,
    P_TO,
    P_TTS_ENTITY,
    P_VOLUME,
    P_WEEKDAYS,
    WEEKDAYS,
    signal_update,
)
from .notify import Notifier, async_safe_call, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
_IGNORED_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)

_WORDS = {
    "de": {"players": "Player", MODE_TTS: "Ansage", "ringtone": "Klingelton"},
    "en": {"players": "players", MODE_TTS: "announcement", "ringtone": "ringtone"},
}


def profile_summary(hass: HomeAssistant, profile: dict[str, Any]) -> str:
    """Kurzbeschreibung eines Profils für Listen im Options-Flow."""
    words = _WORDS["de" if (hass.config.language or "").startswith("de") else "en"]
    days = profile.get(P_WEEKDAYS) or WEEKDAYS
    day_text = "" if len(days) == 7 else f", {', '.join(days)}"
    return (
        f"{profile.get(P_NAME)}: {str(profile.get(P_FROM, ''))[:5]}–"
        f"{str(profile.get(P_TO, ''))[:5]}{day_text}, "
        f"{len(profile.get(P_PLAYERS) or [])} {words['players']}, "
        f"{words.get(profile.get(P_MODE), profile.get(P_MODE))}"
    )


def in_window(profile: dict[str, Any], now_local: datetime) -> bool:
    """Liegt der Zeitpunkt im Zeitfenster des Profils?

    Fenster über Mitternacht (z. B. 22:00 bis 06:00) gehören zum Wochentag,
    an dem sie beginnen. Von = Bis bedeutet ganztägig.
    """
    start = dt_util.parse_time(str(profile.get(P_FROM, "")))
    end = dt_util.parse_time(str(profile.get(P_TO, "")))
    if start is None or end is None:
        return False
    days = profile.get(P_WEEKDAYS) or WEEKDAYS
    today = WEEKDAYS[now_local.weekday()]
    yesterday = WEEKDAYS[(now_local.weekday() - 1) % 7]
    now_time: dtime = now_local.time()
    if start == end:
        return today in days
    if start < end:
        return today in days and start <= now_time < end
    if now_time >= start:
        return today in days
    if now_time < end:
        return yesterday in days
    return False


def assign_players(
    profiles: list[dict[str, Any]], now_local: datetime
) -> list[tuple[dict[str, Any], list[str]]]:
    """Passende Profile mit ihren Playern; jeder Player nur einmal (erstes Profil)."""
    claimed: set[str] = set()
    result: list[tuple[dict[str, Any], list[str]]] = []
    for profile in profiles:
        if not in_window(profile, now_local):
            continue
        players = [p for p in profile.get(P_PLAYERS) or [] if p not in claimed]
        claimed.update(players)
        if players:
            result.append((profile, players))
    return result


class DoorbellController:
    """Reagiert auf den Klingel-Auslöser mit Audio und Push."""

    model = "Türklingel"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.last_ring: datetime | None = None
        self._clear_at: datetime | None = None
        self._last_trigger: float | None = None
        self._clear_unsub = None
        self._unsub = None
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._notifier = Notifier(
            hass, self._get, f"{DOMAIN}_{entry.entry_id}", lambda: entry.title
        )

    def _opt(self, key: str, default: Any = None) -> Any:
        return self._get(key, default)

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.enabled = bool(stored.get("enabled", True))
        if raw := stored.get("last_ring"):
            self.last_ring = dt_util.parse_datetime(raw)
        if raw := stored.get("clear_at"):
            self._clear_at = dt_util.parse_datetime(raw)
        self._schedule_clear()
        self._unsub = async_track_state_change_event(
            self.hass, [self._opt(CONF_TRIGGER_ENTITY)], self._on_trigger
        )

    def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._cancel_clear()

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "enabled": self.enabled,
                "last_ring": self.last_ring.isoformat() if self.last_ring else None,
                "clear_at": self._clear_at.isoformat() if self._clear_at else None,
            }
        )
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self._async_save()

    # --- Auslöser ------------------------------------------------------------

    async def _on_trigger(self, event: Event) -> None:
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        if new is None or old is None:
            return
        if new.state in _IGNORED_STATES or old.state in _IGNORED_STATES:
            return
        if str(self._opt(CONF_TRIGGER_ENTITY)).startswith("event."):
            # Ereignis-Entität: jedes neue Ereignis ändert den Zustand (Zeitstempel)
            if new.state == old.state:
                return
        elif new.state != STATE_ON or old.state == STATE_ON:
            return
        await self.async_ring()

    async def async_ring(self, test: bool = False) -> None:
        """Klingeln: Audio und Push. Der Test umgeht Schalter und Sperrzeit."""
        if not test:
            if not self.enabled:
                return
            now = time.monotonic()
            debounce = float(self._opt(CONF_DEBOUNCE, DEFAULT_RING_DEBOUNCE))
            if self._last_trigger is not None and now - self._last_trigger < debounce:
                return
            self._last_trigger = now
            self.last_ring = dt_util.utcnow()
            await self._async_save()

        assignments = assign_players(
            list(self._opt(CONF_PROFILES, []) or []), dt_util.now()
        )
        results = await asyncio.gather(
            *(self._play(profile, players) for profile, players in assignments),
            self._push(),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                _LOGGER.error("Klingeln: Ausgabe fehlgeschlagen", exc_info=result)

    # --- Audio ---------------------------------------------------------------

    async def _play(self, profile: dict[str, Any], players: list[str]) -> None:
        if volume := int(profile.get(P_VOLUME) or 0):
            await async_safe_call(
                self.hass,
                "media_player",
                "volume_set",
                {"entity_id": players, "volume_level": volume / 100},
            )
        if profile.get(P_MODE) == MODE_TTS:
            if not (profile.get(P_TTS_ENTITY) and profile.get(P_TEXT)):
                _LOGGER.warning("Profil %s: TTS-Dienst oder Text fehlt", profile.get(P_NAME))
                return
            await async_safe_call(
                self.hass,
                "tts",
                "speak",
                {
                    "entity_id": profile[P_TTS_ENTITY],
                    "media_player_entity_id": players,
                    "message": profile[P_TEXT],
                },
            )
            return
        media = profile.get(P_MEDIA) or {}
        if not media.get("media_content_id"):
            _LOGGER.warning("Profil %s: kein Klingelton gewählt", profile.get(P_NAME))
            return
        await async_safe_call(
            self.hass,
            "media_player",
            "play_media",
            {
                "entity_id": players,
                "media_content_id": media["media_content_id"],
                "media_content_type": media.get("media_content_type", "music"),
            },
        )

    # --- Push ----------------------------------------------------------------

    async def _push(self) -> None:
        if not self._notifier._targets():  # noqa: SLF001
            return
        await self._notifier.async_send(self._opt(CONF_MESSAGE) or DEFAULT_RING_MESSAGE)
        hours = float(self._opt(CONF_CLEAR_HOURS, DEFAULT_CLEAR_HOURS))
        if hours > 0:
            self._clear_at = dt_util.utcnow() + timedelta(hours=hours)
            self._schedule_clear()
            await self._async_save()

    def _cancel_clear(self) -> None:
        if self._clear_unsub:
            self._clear_unsub()
            self._clear_unsub = None

    def _schedule_clear(self) -> None:
        self._cancel_clear()
        if self._clear_at is None:
            return
        remaining = (self._clear_at - dt_util.utcnow()).total_seconds()

        async def _clear(_now: datetime) -> None:
            self._clear_unsub = None
            self._clear_at = None
            await self._notifier.async_clear()
            await self._async_save()

        self._clear_unsub = async_call_later(self.hass, max(remaining, 0), _clear)
