"""Gemeinsame Benachrichtigungswege: App-Push, Sprachausgabe, persistente Meldung."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_PERSISTENT_ENABLED,
    CONF_TTS_ENABLED,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
)

_LOGGER = logging.getLogger(__name__)


async def async_safe_call(
    hass: HomeAssistant, domain: str, service: str, data: dict[str, Any]
) -> None:
    """Dienst aufrufen; ein Fehler darf andere Kanäle nicht stoppen."""
    try:
        await hass.services.async_call(domain, service, data, blocking=True)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Aufruf von %s.%s fehlgeschlagen", domain, service)


def entry_opt(entry: ConfigEntry) -> Callable[..., Any]:
    """Wert lesen: Optionen haben Vorrang vor den Daten der Ersteinrichtung.

    Ein in den Optionen explizit auf None gesetzter Wert (Feld geleert)
    überdeckt den Wert aus den Daten und liefert den Standardwert.
    """

    def opt(key: str, default: Any = None) -> Any:
        value = entry.options[key] if key in entry.options else entry.data.get(key)
        return default if value is None else value

    return opt


class Notifier:
    """Sendet Meldungen über die im Eintrag aktivierten Wege."""

    def __init__(
        self,
        hass: HomeAssistant,
        opt: Callable[..., Any],
        tag_base: str,
        title: Callable[[], str],
    ) -> None:
        self._hass = hass
        self._opt = opt
        self._tag_base = tag_base
        self._title = title

    def tag(self, kind: str = "") -> str:
        return f"{self._tag_base}_{kind}" if kind else self._tag_base

    async def _call(self, domain: str, service: str, data: dict) -> None:
        await async_safe_call(self._hass, domain, service, data)

    def _targets(self) -> list[str]:
        if not self._opt(CONF_MOBILE_ENABLED, False):
            return []
        return [
            t.removeprefix("notify.") for t in self._opt(CONF_MOBILE_TARGETS, []) or []
        ]

    async def async_send(
        self,
        message: str,
        *,
        kind: str = "",
        actions: list[dict[str, str]] | None = None,
    ) -> None:
        title = self._title()

        data: dict[str, Any] = {"tag": self.tag(kind)}
        if actions:
            data["actions"] = actions
        for target in self._targets():
            await self._call(
                "notify", target, {"title": title, "message": message, "data": data}
            )

        if self._opt(CONF_TTS_ENABLED, False):
            tts_entity = self._opt(CONF_TTS_ENTITY)
            player = self._opt(CONF_TTS_PLAYER)
            if tts_entity and player:
                await self._call(
                    "tts",
                    "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": player,
                        "message": message,
                    },
                )

        if self._opt(CONF_PERSISTENT_ENABLED, False):
            await self._call(
                "persistent_notification",
                "create",
                {
                    "title": title,
                    "message": message,
                    "notification_id": self.tag(kind),
                },
            )

    async def async_clear(self, kind: str = "") -> None:
        for target in self._targets():
            await self._call(
                "notify",
                target,
                {"message": "clear_notification", "data": {"tag": self.tag(kind)}},
            )
        if self._opt(CONF_PERSISTENT_ENABLED, False):
            await self._call(
                "persistent_notification",
                "dismiss",
                {"notification_id": self.tag(kind)},
            )
