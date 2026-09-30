"""Logik der Funktion "Benachrichtigung Briefkasten"."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_PREFIX,
    ACTION_TITLE,
    CONF_AUTO_RESET_HOURS,
    CONF_DEBOUNCE,
    CONF_MESSAGE,
    CONF_MOBILE_ACTION,
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_PERSISTENT_ENABLED,
    CONF_TTS_ENABLED,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_VIBRATION_SENSOR,
    DEFAULT_AUTO_RESET_HOURS,
    DEFAULT_DEBOUNCE,
    DEFAULT_MESSAGE,
    DEFAULT_MOBILE_ACTION,
    DEFAULT_TITLE,
    DOMAIN,
    MOBILE_ACTION_EVENT,
    signal_update,
)

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1


class MailboxController:
    """Wertet den Vibrationssensor aus und benachrichtigt."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.has_mail = False
        self.last_delivery: datetime | None = None
        self._last_trigger: float | None = None
        self._unsubs: list = []
        self._reset_unsub = None
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    @property
    def action_id(self) -> str:
        return f"{ACTION_PREFIX}{self.entry.entry_id}"

    def _opt(self, key: str, default: Any = None) -> Any:
        """Optionen haben Vorrang vor den Daten aus der Ersteinrichtung."""
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.has_mail = bool(stored.get("has_mail", False))
        if (raw := stored.get("last_delivery")) and (
            parsed := dt_util.parse_datetime(raw)
        ):
            self.last_delivery = parsed
        self._schedule_auto_reset()

        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self._opt(CONF_VIBRATION_SENSOR)], self._on_sensor_change
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(MOBILE_ACTION_EVENT, self._on_mobile_action)
        )

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_auto_reset()

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    # --- Zustand ---------------------------------------------------------

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "has_mail": self.has_mail,
                "last_delivery": self.last_delivery.isoformat()
                if self.last_delivery
                else None,
            }
        )
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def async_reset(self) -> None:
        """Briefkasten als geleert markieren."""
        was_full = self.has_mail
        self.has_mail = False
        self._cancel_auto_reset()
        await self._async_save()
        if was_full:
            await self._async_clear_notifications()

    def _cancel_auto_reset(self) -> None:
        if self._reset_unsub:
            self._reset_unsub()
            self._reset_unsub = None

    def _schedule_auto_reset(self) -> None:
        self._cancel_auto_reset()
        hours = float(self._opt(CONF_AUTO_RESET_HOURS, DEFAULT_AUTO_RESET_HOURS))
        if not self.has_mail or hours <= 0 or self.last_delivery is None:
            return
        remaining = self.last_delivery + timedelta(hours=hours) - dt_util.utcnow()

        async def _fire(_now: datetime) -> None:
            self._reset_unsub = None
            await self.async_reset()

        self._reset_unsub = async_call_later(
            self.hass, max(remaining.total_seconds(), 0), _fire
        )

    # --- Auslöser --------------------------------------------------------

    async def _on_sensor_change(self, event: Event) -> None:
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        if new is None or new.state != STATE_ON:
            return
        if old is None or old.state == STATE_ON:
            return
        await self.async_trigger()

    async def async_trigger(self) -> None:
        """Vibration erkannt: Post vermerken und benachrichtigen."""
        now = time.monotonic()
        debounce = float(self._opt(CONF_DEBOUNCE, DEFAULT_DEBOUNCE))
        if self._last_trigger is not None and now - self._last_trigger < debounce:
            return
        self._last_trigger = now
        if self.has_mail:
            return
        self.has_mail = True
        self.last_delivery = dt_util.utcnow()
        self._schedule_auto_reset()
        await self._async_save()
        await self._async_notify()

    @callback
    def _on_mobile_action(self, event: Event) -> None:
        if event.data.get("action") == self.action_id:
            self.hass.async_create_task(self.async_reset())

    # --- Benachrichtigung ------------------------------------------------

    @property
    def _tag(self) -> str:
        return f"{DOMAIN}_{self.entry.entry_id}"

    async def _async_call(self, domain: str, service: str, data: dict) -> None:
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except Exception:  # noqa: BLE001 - ein Kanal darf die anderen nicht stoppen
            _LOGGER.exception("Aufruf von %s.%s fehlgeschlagen", domain, service)

    async def _async_notify(self) -> None:
        message = self._opt(CONF_MESSAGE) or DEFAULT_MESSAGE
        title = self.entry.title or DEFAULT_TITLE

        if self._opt(CONF_MOBILE_ENABLED, False):
            data: dict[str, Any] = {"tag": self._tag}
            if self._opt(CONF_MOBILE_ACTION, DEFAULT_MOBILE_ACTION):
                data["actions"] = [{"action": self.action_id, "title": ACTION_TITLE}]
            for target in self._opt(CONF_MOBILE_TARGETS, []) or []:
                await self._async_call(
                    "notify",
                    target.removeprefix("notify."),
                    {"title": title, "message": message, "data": data},
                )

        if self._opt(CONF_TTS_ENABLED, False):
            tts_entity = self._opt(CONF_TTS_ENTITY)
            player = self._opt(CONF_TTS_PLAYER)
            if tts_entity and player:
                await self._async_call(
                    "tts",
                    "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": player,
                        "message": message,
                    },
                )

        if self._opt(CONF_PERSISTENT_ENABLED, False):
            await self._async_call(
                "persistent_notification",
                "create",
                {
                    "title": title,
                    "message": message,
                    "notification_id": self._tag,
                },
            )

    async def _async_clear_notifications(self) -> None:
        if self._opt(CONF_MOBILE_ENABLED, False):
            for target in self._opt(CONF_MOBILE_TARGETS, []) or []:
                await self._async_call(
                    "notify",
                    target.removeprefix("notify."),
                    {"message": "clear_notification", "data": {"tag": self._tag}},
                )
        if self._opt(CONF_PERSISTENT_ENABLED, False):
            await self._async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": self._tag},
            )
