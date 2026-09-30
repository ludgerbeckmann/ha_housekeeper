"""Reine Trockenlauf-Logik (ohne Home-Assistant-Abhängigkeit, daher einzeln testbar)."""

from __future__ import annotations

from datetime import datetime, timedelta


def in_range(power: float | None, minimum: float, maximum: float) -> bool:
    """Liegt die Leistung im (inklusiven) Trockenlauf-Bereich? Unbekannt = nein."""
    return power is not None and minimum <= power <= maximum


class DryRunDetector:
    """Erkennt, dass die Leistung lange genug im Trockenlauf-Bereich liegt."""

    def __init__(self, minimum: float, maximum: float, duration: timedelta) -> None:
        self.minimum = minimum
        self.maximum = maximum
        self.duration = duration
        self.since: datetime | None = None

    def reset(self) -> None:
        self.since = None

    def update(self, now: datetime, pump_on: bool, power: float | None) -> bool:
        """Zustand aktualisieren; True, sobald die Dauer durchgehend erreicht ist.

        Der Timer läuft nur, solange die Pumpe an ist und die Leistung
        durchgehend im Bereich liegt. Verlässt sie den Bereich, geht die Pumpe
        aus oder ist der Sensor nicht verfügbar, startet er neu.
        """
        if not pump_on or not in_range(power, self.minimum, self.maximum):
            self.since = None
            return False
        if self.since is None:
            self.since = now
        return now - self.since >= self.duration
