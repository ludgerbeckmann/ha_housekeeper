"""Konstanten für Housekeeper."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ha_housekeeper"

CONF_FUNCTION_TYPE = "function_type"

# Funktionstypen. Neue Funktion: Konstante + Eintrag in FUNCTION_PLATFORMS
# ergänzen, Config-Flow-Schritt "async_step_<typ>" anlegen.
FUNCTION_MAILBOX = "mailbox"

FUNCTION_PLATFORMS: dict[str, list[Platform]] = {
    FUNCTION_MAILBOX: [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.BUTTON],
}

# --- Benachrichtigung Briefkasten ---
CONF_NAME = "name"
CONF_VIBRATION_SENSOR = "vibration_sensor"
CONF_MOBILE_ENABLED = "mobile_enabled"
CONF_MOBILE_TARGETS = "mobile_targets"
CONF_MOBILE_ACTION = "mobile_action"
CONF_TTS_ENABLED = "tts_enabled"
CONF_TTS_ENTITY = "tts_entity"
CONF_TTS_PLAYER = "tts_player"
CONF_PERSISTENT_ENABLED = "persistent_enabled"
CONF_MESSAGE = "message"
CONF_DEBOUNCE = "debounce_seconds"
CONF_AUTO_RESET_HOURS = "auto_reset_hours"

DEFAULT_NAME = "Briefkasten"
DEFAULT_MESSAGE = "Es ist Post im Briefkasten."
DEFAULT_TITLE = "Briefkasten"
DEFAULT_DEBOUNCE = 60
DEFAULT_AUTO_RESET_HOURS = 0
DEFAULT_MOBILE_ACTION = True

ACTION_TITLE = "Briefkasten geleert"
ACTION_PREFIX = "HOUSEKEEPER_MAILBOX_EMPTIED_"
MOBILE_ACTION_EVENT = "mobile_app_notification_action"


def signal_update(entry_id: str) -> str:
    """Dispatcher-Signal für Entitätsupdates eines Eintrags."""
    return f"{DOMAIN}_update_{entry_id}"
