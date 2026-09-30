"""Reine KNX-Hilfsfunktionen (ohne Home-Assistant-Abhängigkeit, daher einzeln testbar).

Die Telegramm-Rohdaten kommen aus dem Ereignis `knx_event` der KNX-Integration:
ein Integer für 1-Bit-/kleine Werte (DPTBinary), ein Tupel von Bytes für Werte
mit mindestens einem Byte (DPTArray).
"""

from __future__ import annotations

import re
from typing import Any

_GA_3 = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{1,3})$")
_GA_2 = re.compile(r"^(\d{1,2})/(\d{1,4})$")
_GA_FREE = re.compile(r"^\d{1,5}$")

TEXT_LENGTH = 14  # DPT 16.001


def _ga_to_int(value: Any) -> int | None:
    text = str(value).strip()
    if match := _GA_3.match(text):
        main, middle, sub = (int(g) for g in match.groups())
        if main > 31 or middle > 7 or sub > 255:
            return None
        return (main << 11) | (middle << 8) | sub
    if match := _GA_2.match(text):
        main, sub = (int(g) for g in match.groups())
        if main > 31 or sub > 2047:
            return None
        return (main << 11) | sub
    if _GA_FREE.match(text):
        number = int(text)
        return number if number <= 0xFFFF else None
    return None


def normalize_ga(value: Any) -> str | None:
    """Gruppenadresse in die kanonische 3-Ebenen-Schreibweise bringen (None = ungültig)."""
    number = _ga_to_int(value)
    if number is None:
        return None
    return f"{number >> 11}/{(number >> 8) & 7}/{number & 255}"


def is_valid_ga(value: Any) -> bool:
    return _ga_to_int(value) is not None


def decode_switch(data: Any) -> bool | None:
    """DPT 1.001: Integer 0/1."""
    if isinstance(data, bool) or not isinstance(data, int) or data not in (0, 1):
        return None
    return bool(data)


def _single_byte(data: Any) -> int | None:
    if isinstance(data, (tuple, list)) and len(data) == 1 and isinstance(data[0], int):
        return data[0] if 0 <= data[0] <= 255 else None
    return None


def decode_percent(data: Any) -> int | None:
    """DPT 5.001: ein Byte 0..255 entspricht 0..100 %."""
    byte = _single_byte(data)
    return None if byte is None else round(byte * 100 / 255)


def decode_scene(data: Any) -> int | None:
    """DPT 17.001: Wert 0..63 entspricht Szene 1..64."""
    byte = _single_byte(data)
    if byte is None or byte > 63:
        return None
    return byte + 1


def decode_dimming(data: Any) -> tuple[bool, int] | None:
    """DPT 3.007: (heller/lauter?, Schrittcode). Schrittcode 0 = Stopp."""
    if isinstance(data, bool) or not isinstance(data, int) or not 0 <= data <= 15:
        return None
    return bool(data & 0x8), data & 0x7


def truncate_text(text: Any, length: int = TEXT_LENGTH) -> str:
    """Text für DPT 16.001 (ISO 8859-1, 14 Zeichen) vorbereiten."""
    if text is None:
        return ""
    cleaned = str(text).encode("latin-1", errors="replace").decode("latin-1")
    return cleaned[:length]
