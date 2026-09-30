"""Hilfen für Tests der Einstellungsdialoge mit den Abschnitten Allgemein/Benachrichtigungen."""

NOTIFY_KEYS = (
    "mobile_enabled",
    "mobile_targets",
    "mobile_action",
    "tts_enabled",
    "tts_entity",
    "tts_player",
    "persistent_enabled",
    "message",
    "repeat_message",
    "clear_after_hours",
)


def sectioned(flat: dict) -> dict:
    """Flache Einstellungen in die Abschnitte des Formulars verteilen."""
    flat = {k: v for k, v in flat.items() if k != "function_type"}
    return {
        "general": {k: v for k, v in flat.items() if k not in NOTIFY_KEYS},
        "notifications": {k: v for k, v in flat.items() if k in NOTIFY_KEYS},
    }
