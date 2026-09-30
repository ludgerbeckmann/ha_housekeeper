"""Konstanten für Housekeeper."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ha_housekeeper"

CONF_FUNCTION_TYPE = "function_type"

# Funktionstypen. Neue Funktion: Konstante + Eintrag in FUNCTION_PLATFORMS
# ergänzen, Config-Flow-Schritt "async_step_<typ>" anlegen.
FUNCTION_MAILBOX = "mailbox"
FUNCTION_DOOR_GUARD = "door_guard"

FUNCTION_PLATFORMS: dict[str, list[Platform]] = {
    FUNCTION_MAILBOX: [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.BUTTON],
    FUNCTION_DOOR_GUARD: [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH],
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
CONF_REPEAT_MESSAGE = "repeat_message"
CONF_DEBOUNCE = "debounce_seconds"
CONF_AUTO_RESET_HOURS = "auto_reset_hours"

DEFAULT_NAME = "Briefkasten"
DEFAULT_MESSAGE = "Es ist Post im Briefkasten."
DEFAULT_REPEAT_MESSAGE = "Der Briefkasten wurde erneut benutzt. Wurde er schon geleert?"
DEFAULT_TITLE = "Briefkasten"
DEFAULT_DEBOUNCE = 60
DEFAULT_AUTO_RESET_HOURS = 0
DEFAULT_MOBILE_ACTION = True

ACTION_TITLE = "Briefkasten geleert"
ACTION_PREFIX = "HOUSEKEEPER_MAILBOX_EMPTIED_"
MOBILE_ACTION_EVENT = "mobile_app_notification_action"

# --- Türwächter ---
CONF_LOCK = "lock"
CONF_CONTACT = "contact"
CONF_BLOCK_ACTION = "block_action"
CONF_RETRY_MINUTES = "retry_minutes"
CONF_OPEN_ALERT_MINUTES = "open_alert_minutes"
CONF_OPEN_ALERT_REPEAT = "open_alert_repeat_minutes"
CONF_VERIFY_SECONDS = "verify_seconds"
CONF_MANUAL_OVERRIDE = "manual_override"
CONF_MANUAL_PAUSE_MINUTES = "manual_pause_minutes"
CONF_RULES = "rules"

BLOCK_NOTIFY = "notify"
BLOCK_RETRY = "retry"
MANUAL_IGNORE = "ignore"
MANUAL_PAUSE = "pause"

DEFAULT_RETRY_MINUTES = 10
DEFAULT_OPEN_ALERT_MINUTES = 10
DEFAULT_OPEN_ALERT_REPEAT = 10
DEFAULT_VERIFY_SECONDS = 30
DEFAULT_MANUAL_PAUSE_MINUTES = 60

# Regel: Schlüssel und Werte
R_ID = "id"
R_ACTION = "action"
R_TRIGGER = "trigger"
R_ENTITY = "entity_id"
R_TO_STATE = "to_state"
R_FOR_MINUTES = "for_minutes"
R_TIME = "time"
R_WEEKDAYS = "weekdays"
R_DELAY = "delay_seconds"

RULE_LOCK = "lock"
RULE_UNLOCK = "unlock"
TRIGGER_STATE = "state"
TRIGGER_TIME = "time"
TRIGGER_DOOR_CLOSED = "door_closed"

# Pro Auslöser gültige Regel-Schlüssel
TRIGGER_KEYS: dict[str, list[str]] = {
    TRIGGER_STATE: [R_ENTITY, R_TO_STATE, R_FOR_MINUTES],
    TRIGGER_TIME: [R_TIME, R_WEEKDAYS],
    TRIGGER_DOOR_CLOSED: [R_DELAY],
}

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Felder, die im Formular geleert werden können
OPTIONAL_KEYS = [
    CONF_MOBILE_TARGETS,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_CONTACT,
]


def signal_update(entry_id: str) -> str:
    """Dispatcher-Signal für Entitätsupdates eines Eintrags."""
    return f"{DOMAIN}_update_{entry_id}"
