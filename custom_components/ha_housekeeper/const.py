"""Konstanten für Housekeeper."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ha_housekeeper"

CONF_FUNCTION_TYPE = "function_type"

# Funktionstypen. Neue Funktion: Konstante + Eintrag in FUNCTION_PLATFORMS
# ergänzen, Config-Flow-Schritt "async_step_<typ>" anlegen.
FUNCTION_MAILBOX = "mailbox"
FUNCTION_DOOR_GUARD = "door_guard"
FUNCTION_DOORBELL = "doorbell"
FUNCTION_POOL = "pool_pump"
FUNCTION_KNX_SONOS = "knx_sonos"
FUNCTION_UPDATER = "updater"
FUNCTION_TASK_PLANNER = "task_planner"
FUNCTION_ALARM = "alarm_clock"

FUNCTION_PLATFORMS: dict[str, list[Platform]] = {
    FUNCTION_MAILBOX: [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.BUTTON],
    FUNCTION_DOOR_GUARD: [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH],
    FUNCTION_DOORBELL: [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON],
    FUNCTION_KNX_SONOS: [Platform.SENSOR, Platform.SWITCH],
    FUNCTION_UPDATER: [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON],
    FUNCTION_TASK_PLANNER: [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON],
    FUNCTION_ALARM: [
        Platform.BINARY_SENSOR,
        Platform.SENSOR,
        Platform.SWITCH,
        Platform.BUTTON,
    ],
    FUNCTION_POOL: [
        Platform.BINARY_SENSOR,
        Platform.BUTTON,
        Platform.SENSOR,
        Platform.SWITCH,
    ],
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


# --- Türklingel ---
CONF_TRIGGER_ENTITY = "trigger_entity"
CONF_CLEAR_HOURS = "clear_after_hours"
CONF_PROFILES = "profiles"

DEFAULT_RING_MESSAGE = "Es hat geklingelt."
DEFAULT_RING_DEBOUNCE = 10
DEFAULT_CLEAR_HOURS = 1

# Zeitfenster-Profil: Schlüssel und Werte
P_ID = "id"
P_NAME = "name"
P_FROM = "from"
P_TO = "to"
P_WEEKDAYS = "weekdays"
P_PLAYERS = "players"
P_MODE = "mode"
P_TTS_ENTITY = "tts_entity"
P_TEXT = "text"
P_MEDIA = "media"
P_VOLUME = "volume"

MODE_TTS = "tts"
MODE_RINGTONE = "ringtone"

# Pro Modus gültige Profil-Schlüssel (zusätzlich zu den Basisfeldern und P_VOLUME)
MODE_KEYS: dict[str, list[str]] = {
    MODE_TTS: [P_TTS_ENTITY, P_TEXT],
    MODE_RINGTONE: [P_MEDIA],
}

# --- Poolpumpe ---
CONF_PUMP_ENTITY = "pump_entity"
CONF_WINDOWS = "windows"
CONF_POWER_ENTITY = "power_entity"
CONF_DRY_MIN_POWER = "dry_min_power"
CONF_DRY_MAX_POWER = "dry_max_power"
CONF_DRY_DURATION = "dry_duration"
CONF_DRY_AUTO_OFF = "dry_auto_off"

DEFAULT_DRY_MIN_POWER = 75
DEFAULT_DRY_MAX_POWER = 100
DEFAULT_DRY_DURATION = 5

# Zeitfenster der Pumpe: Schlüssel (id ist neu und dient dem Bearbeiten/Löschen)
W_ID = "id"
W_START = "start"
W_END = "end"
W_DAYS = "days"
MAX_WINDOWS = 8

SERVICE_RUN_PUMP = "run_pump"
ATTR_DURATION = "duration"
ATTR_ENTRY_ID = "entry_id"

# --- KNX/Sonos-Connector ---
CONF_PLAYER = "player"
CONF_MAX_VOLUME = "max_volume"
CONF_VOLUME_STEP = "volume_step"
CONF_STOP_INSTEAD = "stop_instead_of_pause"
CONF_COMMANDS = "commands"
CONF_STATUS = "status"

DEFAULT_MAX_VOLUME = 100
DEFAULT_VOLUME_STEP = 5

# Befehl (KNX -> Sonos) und Rückmeldung (Sonos -> KNX): Schlüssel
K_ID = "id"
K_NAME = "name"
K_ADDRESS = "address"
K_DPT = "dpt"
K_ACTION = "action"
K_WHEN = "when"
K_SCENE = "scene"
K_VOLUME = "volume"
K_FAVORITE = "favorite"
K_SOURCE = "source"
K_IDLE_TEXT = "idle_text"

# Datentypen der Befehle
DPT_SWITCH = "switch"  # 1.001
DPT_PERCENT = "percent"  # 5.001
DPT_SCENE = "scene"  # 17.001
DPT_DIMMING = "dimming"  # 3.007
DPTS = [DPT_SWITCH, DPT_PERCENT, DPT_SCENE, DPT_DIMMING]

# Bedingung bei Schalten (1 Bit)
WHEN_ON = "on"
WHEN_OFF = "off"
WHEN_ANY = "any"
WHENS = [WHEN_ON, WHEN_OFF, WHEN_ANY]

# Aktionen der Befehle
ACT_PLAY = "play"
ACT_PAUSE = "pause"
ACT_PLAY_PAUSE = "play_pause"
ACT_STOP = "stop"
ACT_NEXT = "next"
ACT_PREVIOUS = "previous"
ACT_VOLUME_SET = "volume_set"
ACT_VOLUME_UP = "volume_up"
ACT_VOLUME_DOWN = "volume_down"
ACT_VOLUME_DIM = "volume_dim"
ACT_MUTE = "mute"
ACT_UNMUTE = "unmute"
ACT_MUTE_TOGGLE = "mute_toggle"
ACT_MUTE_SET = "mute_set"
ACT_FAVORITE = "favorite"
ACTIONS = [
    ACT_PLAY,
    ACT_PAUSE,
    ACT_PLAY_PAUSE,
    ACT_STOP,
    ACT_NEXT,
    ACT_PREVIOUS,
    ACT_VOLUME_SET,
    ACT_VOLUME_UP,
    ACT_VOLUME_DOWN,
    ACT_VOLUME_DIM,
    ACT_MUTE,
    ACT_UNMUTE,
    ACT_MUTE_TOGGLE,
    ACT_MUTE_SET,
    ACT_FAVORITE,
]

# Quellen der Rückmeldungen
SRC_PLAYING = "playing"
SRC_PAUSED = "paused"
SRC_VOLUME = "volume"
SRC_MUTED = "muted"
SRC_TITLE = "title"
SRC_ARTIST = "artist"
SRC_ALBUM = "album"
SRC_SOURCE = "source"
STATUS_SOURCES = [
    SRC_PLAYING,
    SRC_PAUSED,
    SRC_VOLUME,
    SRC_MUTED,
    SRC_TITLE,
    SRC_ARTIST,
    SRC_ALBUM,
    SRC_SOURCE,
]
TEXT_SOURCES = [SRC_TITLE, SRC_ARTIST, SRC_ALBUM, SRC_SOURCE]

# --- Updater ---
CONF_SCHEDULES = "schedules"
CONF_TIMEOUT_MINUTES = "timeout_minutes"
DEFAULT_TIMEOUT_MINUTES = 30

# Zeitplan: Schlüssel und Werte
U_ID = "id"
U_NAME = "name"
U_TIME = "time"
U_WEEKDAYS = "weekdays"
U_MODE = "mode"
U_TARGETS = "targets"
U_BACKUP = "backup"
U_COMPONENTS = "components"

# Komponenten, die ein Zeitplan als Ganzes auswählen kann
COMP_CORE = "core"
COMP_SUPERVISOR = "supervisor"
COMP_OS = "os"
COMP_ADDONS = "addons"
COMP_ESPHOME = "esphome"
COMP_OTHER = "other"
COMPONENTS = [COMP_CORE, COMP_SUPERVISOR, COMP_OS, COMP_ADDONS, COMP_ESPHOME, COMP_OTHER]

UPDATE_MODE_NOTIFY = "notify"
UPDATE_MODE_INSTALL = "install"
UPDATE_MODES = [UPDATE_MODE_NOTIFY, UPDATE_MODE_INSTALL]

# --- Aufgabenplaner ---
CONF_TASKS = "tasks"

# Aufgabe: Schlüssel
TASK_ID = "id"
TASK_NAME = "name"
TASK_ENABLED = "enabled"
TASK_TRIGGERS = "triggers"
TASK_ACTIONS = "actions"
TASK_NOTIFY_START = "notify_start"
TASK_NOTIFY_SUCCESS = "notify_success"
TASK_NOTIFY_ERROR = "notify_error"

# Auslöser einer Aufgabe: Schlüssel
TR_TYPE = "type"
TR_TIME = "time"
TR_WEEKDAYS = "weekdays"
TR_MONTH_MODE = "month_mode"
TR_MONTH_DAY = "month_day"
TR_AT = "at"
TR_MINUTES = "minutes"
TR_ENTITY = "entity_id"
TR_TO_STATE = "to_state"
TR_FOR = "for_minutes"
TR_ABOVE = "above"
TR_BELOW = "below"

TRIG_WEEKLY = "weekly"
TRIG_MONTHLY = "monthly"
TRIG_ONCE = "once"
TRIG_INTERVAL = "interval"
TRIG_STATE = "state"
TRIG_THRESHOLD = "threshold"
TRIGGER_TYPES = [
    TRIG_WEEKLY,
    TRIG_MONTHLY,
    TRIG_ONCE,
    TRIG_INTERVAL,
    TRIG_STATE,
    TRIG_THRESHOLD,
]

MONTH_FIRST = "first"
MONTH_LAST = "last"
MONTH_DAY = "day"
MONTH_MODES = [MONTH_FIRST, MONTH_LAST, MONTH_DAY]

# --- Wecker ---
CONF_ALARMS = "alarms"
CONF_CRITICAL = "critical"

DEFAULT_ALARM_MESSAGE = "Wecker"
DEFAULT_ALARM_VOLUME = 30
DEFAULT_ALARM_SNOOZE = 9
DEFAULT_ALARM_AUTO_STOP = 30

ALARM_ACTION_STOP_PREFIX = "HOUSEKEEPER_ALARM_STOP_"
ALARM_ACTION_SNOOZE_PREFIX = "HOUSEKEEPER_ALARM_SNOOZE_"

# Wecker: Schlüssel
A_ID = "id"
A_NAME = "name"
A_ENABLED = "enabled"
A_TIME = "time"
A_WEEKDAYS = "weekdays"
A_PLAYERS = "players"
A_MEDIA = "media"
A_VOLUME = "volume"
A_SNOOZE = "snooze_minutes"
A_AUTO_STOP = "auto_stop_minutes"

# Felder, die im Formular geleert werden können
OPTIONAL_KEYS = [
    CONF_MOBILE_TARGETS,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_CONTACT,
    CONF_POWER_ENTITY,
]


def signal_update(entry_id: str) -> str:
    """Dispatcher-Signal für Entitätsupdates eines Eintrags."""
    return f"{DOMAIN}_update_{entry_id}"
