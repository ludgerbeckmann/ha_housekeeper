"""Logik der Funktion "Benachrichtigung Briefkasten"."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_PREFIX,
    ACTION_TITLE,
    CONF_AUTO_RESET_HOURS,
    CONF_DEBOUNCE,
    CONF_DELIVERY_CONTACT,
    CONF_EMPTY_CONTACT,
    CONF_MESSAGE,
    CONF_MOBILE_ACTION,
    CONF_REPEAT_MESSAGE,
    CONF_SENSITIVITY_ENTITY,
    CONF_SENSITIVITY_VALUE,
    CONF_VIBRATION_SENSOR,
    DEFAULT_AUTO_RESET_HOURS,
    DEFAULT_DEBOUNCE,
    DEFAULT_MESSAGE,
    DEFAULT_MOBILE_ACTION,
    DEFAULT_REPEAT_MESSAGE,
    DEFAULT_TITLE,
    DOMAIN,
    MOBILE_ACTION_EVENT,
    signal_update,
)
from .notify import Notifier, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1


class MailboxController:
    """Wertet Vibrationssensor oder Einwurf-/Entnahmekontakt aus und benachrichtigt."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.has_mail = False
        self.enabled = True
        self.last_delivery: datetime | None = None
        self.last_emptied: datetime | None = None
        self._last_trigger: float | None = None
        self._unsubs: list = []
        self._reset_unsub = None
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._get = entry_opt(entry)
        self._notifier = Notifier(
            hass,
            self._get,
            f"{DOMAIN}_{entry.entry_id}",
            lambda: entry.title or DEFAULT_TITLE,
        )

    model = "Benachrichtigung Briefkasten"

    @property
    def action_id(self) -> str:
        return f"{ACTION_PREFIX}{self.entry.entry_id}"

    def _opt(self, key: str, default: Any = None) -> Any:
        return self._get(key, default)

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.has_mail = bool(stored.get("has_mail", False))
        self.enabled = bool(stored.get("enabled", True))
        if (raw := stored.get("last_delivery")) and (
            parsed := dt_util.parse_datetime(raw)
        ):
            self.last_delivery = parsed
        if (raw := stored.get("last_emptied")) and (
            parsed := dt_util.parse_datetime(raw)
        ):
            self.last_emptied = parsed
        self._schedule_auto_reset()

        # entweder Vibrationssensor oder die beiden Türkontakte (Einwurf, Entnahme), nie beides
        if self._opt(CONF_VIBRATION_SENSOR):
            self._track(self._opt(CONF_VIBRATION_SENSOR), self.async_trigger)
        else:
            self._track(self._opt(CONF_DELIVERY_CONTACT), self.async_trigger)
            self._track(self._opt(CONF_EMPTY_CONTACT), self._async_contact_emptied)
        self._unsubs.append(
            self.hass.bus.async_listen(MOBILE_ACTION_EVENT, self._on_mobile_action)
        )

    def _track(self, entity_id: str | None, action) -> None:
        """Bei Wechsel von „aus“ auf „an“ die Aktion ausführen."""
        if not entity_id:
            return

        async def _changed(event: Event) -> None:
            new = event.data.get("new_state")
            old = event.data.get("old_state")
            if new is None or new.state != STATE_ON:
                return
            if old is None or old.state == STATE_ON:
                return
            await action()

        self._unsubs.append(async_track_state_change_event(self.hass, [entity_id], _changed))

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_auto_reset()

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    # --- Empfindlichkeit (nur auf Anforderung) ---------------------------

    @property
    def sensitivity_configured(self) -> bool:
        return bool(
            self._opt(CONF_SENSITIVITY_ENTITY)
            and self._opt(CONF_SENSITIVITY_VALUE) not in (None, "")
        )

    async def async_send_sensitivity(self) -> None:
        """Eingestellte Empfindlichkeit an den Sensor senden.

        Nur auf Anforderung (Button), nie automatisch: Batteriesensoren übernehmen
        solche Einstellungen meist nur, wenn sie am Gerät aufgeweckt wurden. Fehler
        werden nicht verschluckt, damit sie dem Bedienenden angezeigt werden.
        """
        if not self.sensitivity_configured:
            raise ServiceValidationError("Empfindlichkeit ist nicht eingestellt")
        entity_id = str(self._opt(CONF_SENSITIVITY_ENTITY))
        value = self._opt(CONF_SENSITIVITY_VALUE)
        if entity_id.startswith("select."):
            await self.hass.services.async_call(
                "select", "select_option",
                {"entity_id": entity_id, "option": str(value)}, blocking=True,
            )
        else:
            await self.hass.services.async_call(
                "number", "set_value",
                {"entity_id": entity_id, "value": float(value)}, blocking=True,
            )

    # --- Zustand ---------------------------------------------------------

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "enabled": self.enabled,
                "has_mail": self.has_mail,
                "last_delivery": self.last_delivery.isoformat()
                if self.last_delivery
                else None,
                "last_emptied": self.last_emptied.isoformat()
                if self.last_emptied
                else None,
            }
        )
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def async_set_enabled(self, enabled: bool) -> None:
        """Benachrichtigung ein- oder ausschalten (aus = Vibrationen werden ignoriert)."""
        self.enabled = enabled
        await self._async_save()

    async def async_reset(self) -> None:
        """Briefkasten als geleert markieren."""
        was_full = self.has_mail
        self.has_mail = False
        if was_full:
            self.last_emptied = dt_util.utcnow()
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

    async def _async_contact_emptied(self) -> None:
        """Entnahmetür geöffnet: nur zurücksetzen, wenn Post vermerkt ist (nicht innerhalb der Sperrzeit nach dem Einwurf)."""
        if not self.enabled or not self.has_mail:
            return
        debounce = float(self._opt(CONF_DEBOUNCE, DEFAULT_DEBOUNCE))
        if self._last_trigger is not None and time.monotonic() - self._last_trigger < debounce:
            return
        await self.async_reset()

    async def async_trigger(self) -> None:
        """Vibration erkannt: Post vermerken und benachrichtigen."""
        if not self.enabled:
            return
        now = time.monotonic()
        debounce = float(self._opt(CONF_DEBOUNCE, DEFAULT_DEBOUNCE))
        if self._last_trigger is not None and now - self._last_trigger < debounce:
            return
        self._last_trigger = now
        repeat = self.has_mail
        self.has_mail = True
        self.last_delivery = dt_util.utcnow()
        self._schedule_auto_reset()
        await self._async_save()
        await self._async_notify(repeat=repeat)

    @callback
    def _on_mobile_action(self, event: Event) -> None:
        if event.data.get("action") == self.action_id:
            self.hass.async_create_task(self.async_reset())

    # --- Benachrichtigung ------------------------------------------------

    async def _async_notify(self, repeat: bool = False) -> None:
        """Meldung senden; bei erneutem Auslösen mit eigenem Text (gleicher Tag)."""
        actions = None
        if self._opt(CONF_MOBILE_ACTION, DEFAULT_MOBILE_ACTION):
            actions = [{"action": self.action_id, "title": ACTION_TITLE}]
        if repeat:
            message = self._opt(CONF_REPEAT_MESSAGE) or DEFAULT_REPEAT_MESSAGE
        else:
            message = self._opt(CONF_MESSAGE) or DEFAULT_MESSAGE
        await self._notifier.async_send(message, actions=actions)

    async def _async_clear_notifications(self) -> None:
        await self._notifier.async_clear()
