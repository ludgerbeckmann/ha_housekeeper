"""Untereinträge: Adapter für die Controller und Hilfen für den Hub.

Ein **Hub** (Config-Entry) gehört zu genau einem Funktionstyp (z. B. „Türklingel“). Jede Instanz
(eine Klingel, ein Pool, ein Wecker …) ist ein **Untereintrag** mit eigenem Gerät. Die
Controller, die Entitäten, der Store und die Reparaturhinweise arbeiten weiter mit einem
„Eintrag“ (`entry_id`, `title`, `data`, `options`): Dafür gibt es `SubentryEntry`, der einen
Untereintrag wie einen Config-Entry aussehen lässt. Seine `entry_id` ist die ID des Untereintrags.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant

from .const import CONF_FUNCTION_TYPE, DOMAIN, FUNCTION_PLATFORMS, instance_name


class SubentryEntry:
    """Schmale Sicht auf einen Untereintrag mit der Schnittstelle eines Config-Entries."""

    domain = DOMAIN

    def __init__(self, hub: ConfigEntry, subentry: ConfigSubentry) -> None:
        self.hub = hub
        self._subentry = subentry

    @property
    def entry_id(self) -> str:
        return self._subentry.subentry_id

    @property
    def hub_entry_id(self) -> str:
        return self.hub.entry_id

    @property
    def title(self) -> str:
        """Gerätename: der Titel des Untereintrags ohne den Präfix „Funktion: “."""
        return instance_name(self._subentry.title)

    @property
    def data(self) -> dict[str, Any]:
        return {CONF_FUNCTION_TYPE: self._subentry.subentry_type, **self._subentry.data}

    @property
    def options(self) -> dict[str, Any]:
        """Es gibt keine getrennten Optionen: alles steht in den Daten des Untereintrags."""
        return {}

    @property
    def state(self) -> ConfigEntryState:
        return self.hub.state

    def async_on_unload(self, func: Callable[[], Any]) -> CALLBACK_TYPE:
        return self.hub.async_on_unload(func)


def hub_controllers(hass: HomeAssistant, hub: ConfigEntry, platform: Any = None) -> list[Any]:
    """Controller aller Untereinträge eines Hubs (soweit eingerichtet).

    Mit `platform` nur die Controller, deren Funktionstyp diese Plattform nutzt."""
    controllers = hass.data.get(DOMAIN, {})
    found = [controllers[sid] for sid in hub.subentries if sid in controllers]
    if platform is None:
        return found
    return [
        c for c in found
        if platform in FUNCTION_PLATFORMS[hub.subentries[c.entry.entry_id].subentry_type]
    ]


def any_busy(hass: HomeAssistant, hub: ConfigEntry) -> bool:
    """Hat ein Controller des Hubs gerade etwas Laufendes, das ein Neuladen nicht überstünde?"""
    return any(getattr(c, "busy", False) for c in hub_controllers(hass, hub))
