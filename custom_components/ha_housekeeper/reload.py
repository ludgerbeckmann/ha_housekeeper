"""Neuladen eines Eintrags aufschieben, solange sein Controller etwas Laufendes hat."""

from __future__ import annotations

import logging

from homeassistant.core import callback

_LOGGER = logging.getLogger(__name__)


class ReloadWhenIdle:
    """Mixin für Controller mit Zuständen, die ein Neuladen nicht überstehen.

    Das Speichern der Einstellungen lädt den Eintrag neu (`_async_reload` in `__init__.py`).
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
        """Vorgemerktes Neuladen ausführen, sobald der Controller nicht mehr beschäftigt ist."""
        if not self.reload_requested or self.busy:
            return
        self.reload_requested = False
        hass, entry_id = self.hass, self.entry.entry_id  # type: ignore[attr-defined]
        if hass.config_entries.async_get_entry(entry_id) is None:
            return
        _LOGGER.debug("%s: vorgemerktes Neuladen wird ausgeführt", self.entry.title)  # type: ignore[attr-defined]
        hass.async_create_task(hass.config_entries.async_reload(entry_id))
