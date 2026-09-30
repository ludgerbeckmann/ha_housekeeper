"""Logik der Funktion "KNX/Sonos-Connector".

Setzt auf der offiziellen KNX-Integration auf (Dienste `knx.event_register`,
`knx.send`, Ereignis `knx_event`); es wird keine eigene Busverbindung aufgebaut.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_PLAYING, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ACT_FAVORITE,
    ACT_MUTE,
    ACT_MUTE_SET,
    ACT_MUTE_TOGGLE,
    ACT_NEXT,
    ACT_PAUSE,
    ACT_PLAY,
    ACT_PLAY_PAUSE,
    ACT_PREVIOUS,
    ACT_STOP,
    ACT_UNMUTE,
    ACT_VOLUME_DIM,
    ACT_VOLUME_DOWN,
    ACT_VOLUME_SET,
    ACT_VOLUME_UP,
    CONF_COMMANDS,
    CONF_MAX_VOLUME,
    CONF_PLAYER,
    CONF_STATUS,
    CONF_STOP_INSTEAD,
    CONF_VOLUME_STEP,
    DEFAULT_MAX_VOLUME,
    DEFAULT_VOLUME_STEP,
    DOMAIN,
    DPT_DIMMING,
    DPT_PERCENT,
    DPT_SCENE,
    DPT_SWITCH,
    K_ACTION,
    K_ADDRESS,
    K_DPT,
    K_FAVORITE,
    K_ID,
    K_IDLE_TEXT,
    K_NAME,
    K_SCENE,
    K_SOURCE,
    K_VOLUME,
    K_WHEN,
    SRC_ALBUM,
    SRC_ARTIST,
    SRC_MUTED,
    SRC_PAUSED,
    SRC_PLAYING,
    SRC_SOURCE,
    SRC_TITLE,
    SRC_VOLUME,
    TEXT_SOURCES,
    WHEN_ANY,
    WHEN_OFF,
    WHEN_ON,
    signal_update,
)
from .knx_codec import (
    decode_dimming,
    decode_percent,
    decode_scene,
    decode_switch,
    normalize_ga,
    truncate_text,
)
from .notify import async_safe_call, entry_opt

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
KNX_DOMAIN = "knx"
KNX_EVENT = "knx_event"
KNX_RELOADED_EVENT = "event_knx_reloaded"
REREGISTER_INTERVAL = timedelta(minutes=5)
_UNKNOWN = (STATE_UNAVAILABLE, STATE_UNKNOWN)

# KNX-Datentyp der Rückmeldung je Quelle (Kennung für `knx.send`)
_STATUS_DPT = {
    SRC_PLAYING: "1.001",
    SRC_PAUSED: "1.001",
    SRC_MUTED: "1.001",
    SRC_VOLUME: "5.001",
    SRC_TITLE: "16.001",
    SRC_ARTIST: "16.001",
    SRC_ALBUM: "16.001",
    SRC_SOURCE: "16.001",
}

_WORDS = {
    "de": {
        ACT_PLAY: "Wiedergabe",
        ACT_PAUSE: "Pause",
        ACT_PLAY_PAUSE: "Wiedergabe/Pause umschalten",
        ACT_STOP: "Stopp",
        ACT_NEXT: "Nächster Titel",
        ACT_PREVIOUS: "Vorheriger Titel",
        ACT_VOLUME_SET: "Lautstärke setzen",
        ACT_VOLUME_UP: "Lauter",
        ACT_VOLUME_DOWN: "Leiser",
        ACT_VOLUME_DIM: "Lautstärke dimmen",
        ACT_MUTE: "Stumm",
        ACT_UNMUTE: "Stumm aus",
        ACT_MUTE_TOGGLE: "Stumm umschalten",
        ACT_MUTE_SET: "Stumm (Wert)",
        ACT_FAVORITE: "Favorit",
        SRC_PLAYING: "Wiedergabe",
        SRC_PAUSED: "Pause",
        SRC_VOLUME: "Lautstärke",
        SRC_MUTED: "Stumm",
        SRC_TITLE: "Titel",
        SRC_ARTIST: "Interpret",
        SRC_ALBUM: "Album",
        SRC_SOURCE: "Quelle",
    },
    "en": {
        ACT_PLAY: "Play",
        ACT_PAUSE: "Pause",
        ACT_PLAY_PAUSE: "Toggle play/pause",
        ACT_STOP: "Stop",
        ACT_NEXT: "Next track",
        ACT_PREVIOUS: "Previous track",
        ACT_VOLUME_SET: "Set volume",
        ACT_VOLUME_UP: "Volume up",
        ACT_VOLUME_DOWN: "Volume down",
        ACT_VOLUME_DIM: "Dim volume",
        ACT_MUTE: "Mute",
        ACT_UNMUTE: "Unmute",
        ACT_MUTE_TOGGLE: "Toggle mute",
        ACT_MUTE_SET: "Mute (value)",
        ACT_FAVORITE: "Favorite",
        SRC_PLAYING: "Playing",
        SRC_PAUSED: "Paused",
        SRC_VOLUME: "Volume",
        SRC_MUTED: "Muted",
        SRC_TITLE: "Title",
        SRC_ARTIST: "Artist",
        SRC_ALBUM: "Album",
        SRC_SOURCE: "Source",
    },
}


def _words(hass: HomeAssistant) -> dict[str, str]:
    return _WORDS["de" if (hass.config.language or "").startswith("de") else "en"]


def command_summary(hass: HomeAssistant, command: dict[str, Any]) -> str:
    """Kurzbeschreibung eines Befehls für Listen im Options-Flow."""
    words = _words(hass)
    return (
        f"{command.get(K_NAME)}: {command.get(K_ADDRESS)} → "
        f"{words.get(command.get(K_ACTION), command.get(K_ACTION))}"
    )


def status_summary(hass: HomeAssistant, status: dict[str, Any]) -> str:
    """Kurzbeschreibung einer Rückmeldung für Listen im Options-Flow."""
    words = _words(hass)
    return (
        f"{status.get(K_NAME)}: "
        f"{words.get(status.get(K_SOURCE), status.get(K_SOURCE))} → {status.get(K_ADDRESS)}"
    )


class KnxSonosController:
    """Verbindet KNX-Gruppenadressen mit einem Sonos-Lautsprecher."""

    model = "KNX/Sonos-Connector"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.last_command: dict[str, Any] | None = None
        self._get = entry_opt(entry)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list[CALLBACK_TYPE] = []
        self._commands_by_ga: dict[str, list[dict[str, Any]]] = {}
        self._status_by_ga: dict[str, list[dict[str, Any]]] = {}
        self._last_sent: dict[str, Any] = {}
        self._knx_available = False

    # --- Hilfen ------------------------------------------------------------

    def _opt(self, key: str, default: Any = None) -> Any:
        return self._get(key, default)

    @property
    def player(self) -> str:
        return self._opt(CONF_PLAYER)

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"enabled": self.enabled, "last_command": self.last_command}
        )
        self._notify()

    def _player_state(self):
        state = self.hass.states.get(self.player)
        if state is None or state.state in _UNKNOWN:
            return None
        return state

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.enabled = bool(stored.get("enabled", True))
        self.last_command = stored.get("last_command")

        for command in self._opt(CONF_COMMANDS, []) or []:
            if ga := normalize_ga(command.get(K_ADDRESS)):
                self._commands_by_ga.setdefault(ga, []).append(command)
        for status in self._opt(CONF_STATUS, []) or []:
            if ga := normalize_ga(status.get(K_ADDRESS)):
                self._status_by_ga.setdefault(ga, []).append(status)

        self._unsubs.append(self.hass.bus.async_listen(KNX_EVENT, self._on_knx_event))
        self._unsubs.append(
            self.hass.bus.async_listen(KNX_RELOADED_EVENT, self._on_knx_reloaded)
        )
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self.player], self._on_player_change
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._on_reregister_interval, REREGISTER_INTERVAL
            )
        )
        await self._async_register()

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self._async_save()
        if enabled:
            await self._async_send_status(force=True)

    # --- KNX-Anbindung ---------------------------------------------------------

    async def _async_register(self) -> None:
        """Gruppenadressen bei der KNX-Integration anmelden (idempotent).

        Die Anmeldung gilt nur zur Laufzeit und geht beim Neuladen der
        KNX-Integration verloren, daher wird sie regelmäßig wiederholt.
        """
        if not self.hass.services.has_service(KNX_DOMAIN, "event_register"):
            self._knx_available = False
            return
        addresses = sorted({*self._commands_by_ga, *self._status_by_ga})
        if addresses:
            await async_safe_call(
                self.hass, KNX_DOMAIN, "event_register", {"address": addresses}
            )
        if not self._knx_available:
            self._knx_available = True
            await self._async_send_status(force=True)

    async def _on_knx_reloaded(self, event: Event) -> None:
        self._knx_available = False
        await self._async_register()

    async def _on_reregister_interval(self, _now: datetime) -> None:
        await self._async_register()

    async def _async_knx_send(
        self, address: str, payload: Any, dpt: str, *, response: bool = False
    ) -> None:
        if not self.hass.services.has_service(KNX_DOMAIN, "send"):
            return
        data: dict[str, Any] = {"address": address, "payload": payload, "type": dpt}
        if response:
            data["response"] = True
        await async_safe_call(self.hass, KNX_DOMAIN, "send", data)

    # --- Befehle (KNX -> Sonos) -----------------------------------------------

    async def _on_knx_event(self, event: Event) -> None:
        data = event.data
        # Ausgehende Telegramme (auch unsere eigenen Rückmeldungen) nie auswerten
        if data.get("direction") != "Incoming":
            return
        ga = normalize_ga(data.get("destination"))
        if ga is None:
            return
        telegram_type = data.get("telegramtype")
        if telegram_type == "GroupValueRead":
            await self._async_answer_read(ga)
            return
        if telegram_type != "GroupValueWrite" or not self.enabled:
            return
        for command in self._commands_by_ga.get(ga, []):
            await self._async_run_command(command, data.get("data"))

    def _decode(self, command: dict[str, Any], raw: Any) -> tuple[Any, bool] | None:
        """Rohdaten dekodieren und Bedingung prüfen: (Wert, erfüllt) oder None."""
        dpt = command.get(K_DPT)
        if dpt == DPT_SWITCH:
            value = decode_switch(raw)
            if value is None:
                return None
            # "Stumm (Wert)" folgt dem Telegrammwert, hat also keine Bedingung
            when = (
                WHEN_ANY
                if command.get(K_ACTION) == ACT_MUTE_SET
                else command.get(K_WHEN, WHEN_ON)
            )
            ok = (
                when == WHEN_ANY
                or (when == WHEN_ON and value)
                or (when == WHEN_OFF and not value)
            )
            return value, bool(ok)
        if dpt == DPT_PERCENT:
            value = decode_percent(raw)
            return (None, False) if value is None else (value, True)
        if dpt == DPT_SCENE:
            value = decode_scene(raw)
            if value is None:
                return None
            return value, value == int(command.get(K_SCENE, 0))
        if dpt == DPT_DIMMING:
            dim = decode_dimming(raw)
            if dim is None:
                return None
            increase, step = dim
            return increase, step != 0  # Schrittcode 0 = Stopp
        return None

    async def _async_run_command(self, command: dict[str, Any], raw: Any) -> None:
        decoded = self._decode(command, raw)
        if decoded is None or not decoded[1]:
            return
        value = decoded[0]
        state = self._player_state()
        if state is None:
            _LOGGER.debug("%s: Lautsprecher %s nicht verfügbar", self.entry.title, self.player)
            return
        await self._async_do(command.get(K_ACTION), command, value, state)
        self.last_command = {
            "time": dt_util.utcnow().isoformat(),
            "name": command.get(K_NAME),
            "address": command.get(K_ADDRESS),
            "action": command.get(K_ACTION),
            "value": value if isinstance(value, (bool, int, float, str)) else None,
        }
        await self._async_save()

    def _clamp(self, percent: float) -> float:
        maximum = float(self._opt(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME))
        return max(0.0, min(float(percent), maximum))

    async def _async_player_call(self, service: str, **data: Any) -> None:
        await async_safe_call(
            self.hass, "media_player", service, {"entity_id": self.player, **data}
        )

    async def _async_set_volume(self, percent: float) -> None:
        await self._async_player_call(
            "volume_set", volume_level=round(self._clamp(percent) / 100, 2)
        )

    def _current_volume_percent(self, state) -> float | None:
        level = state.attributes.get("volume_level")
        return None if level is None else float(level) * 100

    async def _async_pause(self) -> None:
        stop = bool(self._opt(CONF_STOP_INSTEAD, False))
        await self._async_player_call("media_stop" if stop else "media_pause")

    async def _async_do(self, action: str, command: dict[str, Any], value: Any, state) -> None:
        step = float(self._opt(CONF_VOLUME_STEP, DEFAULT_VOLUME_STEP))
        if action == ACT_PLAY:
            await self._async_player_call("media_play")
        elif action == ACT_PAUSE:
            await self._async_pause()
        elif action == ACT_PLAY_PAUSE:
            if state.state == STATE_PLAYING:
                await self._async_pause()
            else:
                await self._async_player_call("media_play")
        elif action == ACT_STOP:
            await self._async_player_call("media_stop")
        elif action == ACT_NEXT:
            await self._async_player_call("media_next_track")
        elif action == ACT_PREVIOUS:
            await self._async_player_call("media_previous_track")
        elif action == ACT_VOLUME_SET:
            if command.get(K_DPT) == DPT_PERCENT:
                await self._async_set_volume(value)
            elif command.get(K_VOLUME) is not None:
                await self._async_set_volume(float(command[K_VOLUME]))
        elif action in (ACT_VOLUME_UP, ACT_VOLUME_DOWN, ACT_VOLUME_DIM):
            current = self._current_volume_percent(state)
            if current is None:
                return
            up = action == ACT_VOLUME_UP or (action == ACT_VOLUME_DIM and value)
            await self._async_set_volume(current + step if up else current - step)
        elif action == ACT_MUTE:
            await self._async_player_call("volume_mute", is_volume_muted=True)
        elif action == ACT_UNMUTE:
            await self._async_player_call("volume_mute", is_volume_muted=False)
        elif action == ACT_MUTE_TOGGLE:
            muted = bool(state.attributes.get("is_volume_muted"))
            await self._async_player_call("volume_mute", is_volume_muted=not muted)
        elif action == ACT_MUTE_SET:
            await self._async_player_call("volume_mute", is_volume_muted=bool(value))
        elif action == ACT_FAVORITE and command.get(K_FAVORITE):
            await self._async_player_call("select_source", source=command[K_FAVORITE])

    # --- Rückmeldungen (Sonos -> KNX) -------------------------------------------

    def _status_value(self, status: dict[str, Any]) -> Any:
        """Aktuellen Wert der Quelle bestimmen (None = nicht senden)."""
        state = self._player_state()
        if state is None:
            return None
        source = status.get(K_SOURCE)
        attrs = state.attributes
        if source == SRC_PLAYING:
            return state.state == STATE_PLAYING
        if source == SRC_PAUSED:
            return state.state == "paused"
        if source == SRC_MUTED:
            return bool(attrs.get("is_volume_muted"))
        if source == SRC_VOLUME:
            level = attrs.get("volume_level")
            return None if level is None else round(float(level) * 100)
        if source in TEXT_SOURCES:
            if state.state != STATE_PLAYING:
                return truncate_text(status.get(K_IDLE_TEXT, ""))
            attribute = {
                SRC_TITLE: "media_title",
                SRC_ARTIST: "media_artist",
                SRC_ALBUM: "media_album_name",
                SRC_SOURCE: "source",
            }[source]
            return truncate_text(attrs.get(attribute))
        return None

    async def _async_send_status(self, force: bool = False) -> None:
        if not self.enabled or not self._knx_available:
            return
        for statuses in self._status_by_ga.values():
            for status in statuses:
                value = self._status_value(status)
                if value is None:
                    continue
                key = status.get(K_ID) or status.get(K_NAME)
                if not force and self._last_sent.get(key) == value:
                    continue
                self._last_sent[key] = value
                await self._async_knx_send(
                    status[K_ADDRESS], value, _STATUS_DPT[status[K_SOURCE]]
                )

    async def _async_answer_read(self, ga: str) -> None:
        if not self.enabled:
            return
        for status in self._status_by_ga.get(ga, []):
            value = self._status_value(status)
            if value is None:
                continue
            await self._async_knx_send(
                status[K_ADDRESS], value, _STATUS_DPT[status[K_SOURCE]], response=True
            )

    @callback
    def _on_player_change(self, event: Event) -> None:
        self.hass.async_create_task(self._async_send_status())
