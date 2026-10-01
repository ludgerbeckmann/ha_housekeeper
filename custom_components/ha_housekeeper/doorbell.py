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
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_DEBOUNCE,
    CONF_PROFILES,
    CONF_TRIGGER_ENTITY,
    DEFAULT_CLEAR_HOURS,
    DEFAULT_RING_DEBOUNCE,
    DEFAULT_RING_MESSAGE,
    DOMAIN,
    MODE_TTS,
    P_CLEAR_HOURS,
    P_ENABLED,
    P_ID,
    P_MESSAGE,
    P_MOBILE_ENABLED,
    P_MOBILE_TARGETS,
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
    "de": {"players": "Player", MODE_TTS: "Ansage", "ringtone": "Klingelton", "off": "aus", "push": "Push"},
    "en": {"players": "players", MODE_TTS: "announcement", "ringtone": "ringtone", "off": "off", "push": "push"},
}


def profile_summary(hass: HomeAssistant, profile: dict[str, Any]) -> str:
    """Kurzbeschreibung eines Profils für Listen im Options-Flow."""
    words = _WORDS["de" if (hass.config.language or "").startswith("de") else "en"]
    days = profile.get(P_WEEKDAYS) or WEEKDAYS
    day_text = "" if len(days) == 7 else f", {', '.join(days)}"
    off = "" if profile.get(P_ENABLED, True) else f", {words['off']}"
    parts = []
    if players := len(profile.get(P_PLAYERS) or []):
        parts.append(f"{players} {words['players']}")
        parts.append(words.get(profile.get(P_MODE), profile.get(P_MODE)))
    if profile.get(P_MOBILE_ENABLED):
        parts.append(words["push"])
    return (
        f"{profile.get(P_NAME)}: {str(profile.get(P_FROM, ''))[:5]}–"
        f"{str(profile.get(P_TO, ''))[:5]}{day_text}, {', '.join(parts)}{off}"
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
        if not profile.get(P_ENABLED, True) or not in_window(profile, now_local):
            continue
        players = [p for p in profile.get(P_PLAYERS) or [] if p not in claimed]
        claimed.update(players)
        if players:
            result.append((profile, players))
    return result


def assign_push(
    profiles: list[dict[str, Any]], now_local: datetime
) -> list[tuple[dict[str, Any], list[str]]]:
    """Passende Profile mit App-Push; alle gelten gleichberechtigt, jedes Ziel nur einmal."""
    claimed: set[str] = set()
    result: list[tuple[dict[str, Any], list[str]]] = []
    for profile in profiles:
        if (
            not profile.get(P_ENABLED, True)
            or not profile.get(P_MOBILE_ENABLED)
            or not in_window(profile, now_local)
        ):
            continue
        targets = [t for t in profile.get(P_MOBILE_TARGETS) or [] if t not in claimed]
        claimed.update(targets)
        if targets:
            result.append((profile, targets))
    return result


class DoorbellController:
    """Reagiert auf den Klingel-Auslöser mit Audio und Push."""

    model = "Türklingel"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.last_ring: datetime | None = None
        self._clear_at: dict[str, datetime] = {}
        self._last_trigger: float | None = None
        self._clear_unsubs: dict[str, Any] = {}
        self._unsub = None
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    def _notifier_for(self, targets: list[str]) -> Notifier:
        """Notifier nur für die App-Push-Ziele eines Profils."""
        values = {CONF_MOBILE_ENABLED: True, CONF_MOBILE_TARGETS: targets}
        return Notifier(
            self.hass,
            lambda key, default=None: values.get(key, default),
            f"{DOMAIN}_{self.entry.entry_id}",
            lambda: self.entry.title,
        )

    def _profiles(self) -> list[dict[str, Any]]:
        return list(self._opt(CONF_PROFILES, []) or [])

    def _opt(self, key: str, default: Any = None) -> Any:
        return self._get(key, default)

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.enabled = bool(stored.get("enabled", True))
        if raw := stored.get("last_ring"):
            self.last_ring = dt_util.parse_datetime(raw)
        for key, raw in (stored.get("clears") or {}).items():
            if (parsed := dt_util.parse_datetime(raw)) is not None:
                self._clear_at[key] = parsed
        if raw := stored.get("clear_at"):  # älteres Format: ein Zeitpunkt für alle Ziele
            if (parsed := dt_util.parse_datetime(raw)) is not None:
                self._clear_at.setdefault("*", parsed)
        for key in list(self._clear_at):
            self._schedule_clear(key)
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
                "clears": {k: v.isoformat() for k, v in self._clear_at.items()},
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

        now = dt_util.now()
        profiles = self._profiles()
        results = await asyncio.gather(
            *(self._play(profile, players) for profile, players in assign_players(profiles, now)),
            *(self._push(profile, targets) for profile, targets in assign_push(profiles, now)),
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

    async def _push(self, profile: dict[str, Any], targets: list[str]) -> None:
        await self._notifier_for(targets).async_send(
            profile.get(P_MESSAGE) or DEFAULT_RING_MESSAGE
        )
        hours = float(
            DEFAULT_CLEAR_HOURS
            if profile.get(P_CLEAR_HOURS) is None
            else profile[P_CLEAR_HOURS]
        )
        if hours > 0:
            key = str(profile.get(P_ID))
            self._clear_at[key] = dt_util.utcnow() + timedelta(hours=hours)
            self._schedule_clear(key)
            await self._async_save()

    def _cancel_clear(self, key: str | None = None) -> None:
        for k in [key] if key is not None else list(self._clear_unsubs):
            if unsub := self._clear_unsubs.pop(k, None):
                unsub()

    def _clear_targets(self, key: str) -> list[str]:
        """Push-Ziele, die beim Löschen angesprochen werden (Profil, sonst alle Profile)."""
        profiles = self._profiles()
        if match := next((p for p in profiles if str(p.get(P_ID)) == key), None):
            return list(match.get(P_MOBILE_TARGETS) or [])
        return [t for p in profiles for t in p.get(P_MOBILE_TARGETS) or []]

    def _schedule_clear(self, key: str) -> None:
        self._cancel_clear(key)
        if (clear_at := self._clear_at.get(key)) is None:
            return
        remaining = (clear_at - dt_util.utcnow()).total_seconds()

        async def _clear(_now: datetime) -> None:
            self._clear_unsubs.pop(key, None)
            self._clear_at.pop(key, None)
            await self._notifier_for(self._clear_targets(key)).async_clear()
            await self._async_save()

        self._clear_unsubs[key] = async_call_later(self.hass, max(remaining, 0), _clear)
