"""Reine Zeitplan-Logik (ohne Home-Assistant-Abhängigkeit, daher einzeln testbar)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_DAY_LABELS = {
    "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}


@dataclass(frozen=True)
class Window:
    """Ein Zeitfenster. `days` bezieht sich auf den Tag des Starts.

    Liegt `end` vor `start`, läuft das Fenster über Mitternacht.
    """

    start: time
    end: time
    days: tuple[int, ...]

    def bounds(self, day: datetime) -> tuple[datetime, datetime]:
        """Start und Ende des Fensters, das am Datum von `day` beginnt."""
        start = day.replace(
            hour=self.start.hour, minute=self.start.minute,
            second=self.start.second, microsecond=0,
        )
        end = day.replace(
            hour=self.end.hour, minute=self.end.minute,
            second=self.end.second, microsecond=0,
        )
        if self.end <= self.start:
            end += timedelta(days=1)
        return start, end


def parse_time(value: str) -> time:
    """'HH:MM' oder 'HH:MM:SS' in ein `time` umwandeln."""
    parts = [int(p) for p in str(value).split(":")]
    while len(parts) < 3:
        parts.append(0)
    return time(parts[0], parts[1], parts[2])


def parse_windows(raw: list[dict[str, Any]] | None) -> list[Window]:
    """Gespeicherte Fenster in `Window`-Objekte umwandeln (ungültige werden übersprungen)."""
    windows: list[Window] = []
    for item in raw or []:
        try:
            start = parse_time(item["start"])
            end = parse_time(item["end"])
            days = tuple(sorted(WEEKDAYS.index(d) for d in item["days"]))
        except (KeyError, ValueError, TypeError):
            continue
        if start == end or not days:
            continue
        windows.append(Window(start, end, days))
    return windows


def is_active(windows: list[Window], now: datetime) -> bool:
    """Liegt `now` in mindestens einem Fenster (inkl. Fenster von gestern über Mitternacht)?"""
    for window in windows:
        for offset in (0, 1):
            day = now - timedelta(days=offset)
            if day.weekday() not in window.days:
                continue
            start, end = window.bounds(day)
            if start <= now < end:
                return True
    return False


def next_start(windows: list[Window], now: datetime) -> datetime | None:
    """Nächster Fensterbeginn nach `now` (spätestens in 7 Tagen)."""
    best: datetime | None = None
    for window in windows:
        for offset in range(8):
            day = now + timedelta(days=offset)
            if day.weekday() not in window.days:
                continue
            start, _ = window.bounds(day)
            if start > now and (best is None or start < best):
                best = start
    return best


def describe_window(window: Window, language: str = "en") -> str:
    """Kurzbeschreibung, z. B. '08:00–10:00 (Mo, Di)'."""
    labels = _DAY_LABELS["de" if language.startswith("de") else "en"]
    days = ", ".join(labels[d] for d in window.days)
    return f"{window.start:%H:%M}–{window.end:%H:%M} ({days})"
