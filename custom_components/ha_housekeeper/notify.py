"""Gemeinsame Benachrichtigungswege: App-Push, Sprachausgabe, persistente Meldung."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import slugify

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


MOBILE_APP = "mobile_app"


def _mobile_entry_ids(hass: HomeAssistant) -> dict[str, str]:
    """Dienstname (`mobile_app_<gerät>`) -> Config-Entry-ID je Companion-App-Gerät."""
    return {
        f"mobile_app_{slugify(entry.data['device_name'])}": entry.entry_id
        for entry in hass.config_entries.async_entries(MOBILE_APP)
        if entry.data.get("device_name")
    }


def mobile_service_for_device(hass: HomeAssistant, device_id: str) -> str | None:
    """Push-Dienst (ohne `notify.`) eines Companion-App-Geräts der Geräteverwaltung."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == MOBILE_APP and entry.data.get("device_name"):
            return f"mobile_app_{slugify(entry.data['device_name'])}"
    return None


def device_id_for_service(hass: HomeAssistant, service: str) -> str | None:
    """Gerät der Geräteverwaltung zu einem Push-Dienst `mobile_app_<gerät>` (sonst None)."""
    entry_id = _mobile_entry_ids(hass).get(service.removeprefix("notify."))
    if entry_id is None:
        return None
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry_id)
    return devices[0].id if devices else None


def resolve_mobile_services(hass: HomeAssistant, targets: list[str] | None) -> list[str]:
    """Gespeicherte Push-Ziele in Dienstnamen auflösen, ohne Doppelte.

    Neue Einträge speichern Geräte der Geräteverwaltung (Geräteauswahl), ältere direkt den
    Dienstnamen; beides wird unterstützt. Ein Gerät ohne Companion-App-Dienst wird übersprungen.
    """
    services: dict[str, None] = {}
    for target in targets or []:
        target = str(target)
        if dr.async_get(hass).async_get(target) is not None:
            service = mobile_service_for_device(hass, target)
            if service is None:
                _LOGGER.warning("Gerät %s hat keinen Push-Dienst der Companion-App", target)
                continue
        else:
            service = target.removeprefix("notify.")
        services.setdefault(service, None)
    return list(services)


def targets_for_form(hass: HomeAssistant, targets: list[str] | None) -> list[str]:
    """Gespeicherte Ziele für die Geräteauswahl: ältere Dienstnamen werden zu Geräten.

    Nicht zuordenbare Einträge bleiben unverändert stehen, damit nichts verloren geht.
    """
    return [
        device_id_for_service(hass, str(target)) or str(target) for target in targets or []
    ]


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
        return resolve_mobile_services(self._hass, self._opt(CONF_MOBILE_TARGETS, []))

    async def async_send(
        self,
        message: str,
        *,
        kind: str = "",
        actions: list[dict[str, str]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        title = self._title()

        data: dict[str, Any] = {"tag": self.tag(kind)}
        if actions:
            data["actions"] = actions
        if extra:
            data.update(extra)
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
