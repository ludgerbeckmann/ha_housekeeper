"""Neuladen eines Eintrags aufschieben, solange sein Controller etwas Laufendes hat."""

from __future__ import annotations

import logging

from homeassistant.core import callback

from .subentry import any_busy, hub_controllers

_LOGGER = logging.getLogger(__name__)


class ReloadWhenIdle:
    """Mixin für Controller mit Zuständen, die ein Neuladen nicht überstehen.

    Das Speichern der Einstellungen lädt den Hub neu (`_async_reload` in `__init__.py`).
    Ist der Controller `busy` (z. B. ein klingelnder Wecker, ein laufender Update-Lauf), wird
    das Neuladen vorgemerkt und erst ausgeführt, wenn er wieder ruhig ist; mehrere Änderungen
    ergeben so nur ein Neuladen. Der Controller ruft dafür `async_idle()` auf, sobald etwas
    endet. Die Einstellungen selbst sind sofort gespeichert.
    """

    reload_requested: bool = False

    @property
    def busy(self) -> bool:
        """Läuft gerade etwas, das ein Neuladen nicht überstehen würde?"""
        return False

    @callback
    def async_idle(self) -> None:
        """Vorgemerktes Neuladen des Hubs ausführen, sobald kein Controller mehr beschäftigt ist."""
        if not self.reload_requested or self.busy:
            return
        hass = self.hass  # type: ignore[attr-defined]
        entry = self.entry  # type: ignore[attr-defined]
        hub = hass.config_entries.async_get_entry(entry.hub_entry_id)
        if hub is None or any_busy(hass, hub):
            return
        for controller in hub_controllers(hass, hub):
            controller.reload_requested = False
        _LOGGER.debug("%s: vorgemerktes Neuladen wird ausgeführt", hub.title)
        hass.async_create_task(hass.config_entries.async_reload(hub.entry_id))
