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
FUNCTION_MONITOR = "integration_monitor"

CONF_HUB = "hub"  # Marker im Hub-Eintrag (neues Format: Hub + Untereinträge)

# Anzeigenamen der Funktionen (Hub-Titel, Reparaturhinweise): (deutsch, englisch)
FUNCTION_TITLES: dict[str, tuple[str, str]] = {
    FUNCTION_MAILBOX: ("Benachrichtigung Briefkasten", "Mailbox notification"),
    FUNCTION_DOOR_GUARD: ("Türwächter", "Door guard"),
    FUNCTION_DOORBELL: ("Türklingel", "Doorbell"),
    FUNCTION_POOL: ("Poolsteuerung", "Pool control"),
    FUNCTION_KNX_SONOS: ("KNX/Sonos-Connector", "KNX/Sonos connector"),
    FUNCTION_UPDATER: ("Home Assistant Updater", "Home Assistant Updater"),
    FUNCTION_TASK_PLANNER: ("Aufgabenplaner", "Task planner"),
    FUNCTION_ALARM: ("Wecker", "Alarm clock"),
    FUNCTION_MONITOR: ("Integrationsmonitor", "Integration monitor"),
}

HUB_TITLE = ("Funktionen", "Functions")


def hub_title(hass) -> str:
    """Titel des einen Hubs („Funktionen“)."""
    german, english = HUB_TITLE
    return german if (hass.config.language or "").startswith("de") else english


def instance_title(hass, function_type: str, name: str) -> str:
    """Titel eines Untereintrags (Zeile mit dem Zahnrad): „Funktion: Name“."""
    function = function_title(hass, function_type)
    # ohne Namen (oder mit dem Funktionsnamen) gibt es keinen doppelten Präfix
    return function if not name or name == function else f"{function}: {name}"


_NAME_SEPARATORS = " :-–—_"


def clean_instance_name(function_type: str, name: str | None) -> str:
    """Namen der Instanz ohne den Funktionsnamen am Anfang (vermeidet „Funktion: Funktion Name“).

    „Türwächter Garagentür“ wird zu „Garagentür“; „Türwächterei“ bleibt unverändert (nach dem
    Funktionsnamen muss ein Trenner folgen). Bleibt nichts übrig, ist das Ergebnis leer."""
    name = (name or "").strip()
    while True:
        for prefix in FUNCTION_TITLES[function_type]:
            if name.casefold().startswith(prefix.casefold()):
                rest = name[len(prefix) :]
                if not rest or rest[0] in _NAME_SEPARATORS:
                    name = rest.strip(_NAME_SEPARATORS)
                    break
        else:
            return name


def instance_name(title: str) -> str:
    """Name der Instanz (Gerätename): der Titel ohne den Präfix „Funktion: “."""
    for names in FUNCTION_TITLES.values():
        for prefix in names:
            if title.startswith(f"{prefix}: "):
                return title[len(prefix) + 2 :]
    return title


def function_title(hass, function_type: str) -> str:
    """Anzeigename der Funktion (Hub-Titel, Vorgabe für Instanznamen) in der Sprache von Home Assistant."""
    german, english = FUNCTION_TITLES[function_type]
    return german if (hass.config.language or "").startswith("de") else english


FUNCTION_PLATFORMS: dict[str, list[Platform]] = {
    FUNCTION_MAILBOX: [
        Platform.BINARY_SENSOR,
        Platform.SENSOR,
        Platform.BUTTON,
        Platform.SWITCH,
    ],
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
    FUNCTION_MONITOR: [
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
CONF_SENSITIVITY_ENTITY = "sensitivity_entity"
CONF_SENSITIVITY_VALUE = "sensitivity_value"

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
R_ENABLED = "enabled"

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
P_ENABLED = "enabled"
P_MOBILE_ENABLED = "mobile_enabled"
P_MOBILE_TARGETS = "mobile_targets"
P_MESSAGE = "message"
P_CLEAR_HOURS = "clear_after_hours"

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
CONF_HEATER_ENTITY = "heater_entity"
CONF_TEMP_ENTITY = "temperature_entity"
CONF_HEATER_ON_ABOVE = "heater_on_above"
CONF_HEATER_OFF_BELOW = "heater_off_below"
DEFAULT_HEATER_ON_ABOVE = 28
DEFAULT_HEATER_OFF_BELOW = 26

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
CONF_SPEAKERS = "speakers"

DEFAULT_MAX_VOLUME = 100
DEFAULT_SPEAKER_ID = "default"
DEFAULT_SPEAKER_NAME = "Standard"
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
K_PROFILE = "profile"
S_ENABLED = "enabled"  # Lautsprecher-Profil aktiv

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
U_ENABLED = "enabled"
U_TRIGGER = "trigger"
U_WINDOW_START = "window_start"
U_WINDOW_END = "window_end"
TRIGGER_TIME = "time"
TRIGGER_AVAILABLE = "on_available"
TRIGGERS = [TRIGGER_TIME, TRIGGER_AVAILABLE]

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
A_ONLY_IF_ON = "only_if_on"
A_NOT_IF_ON = "skip_if_on"

# --- Integrationsmonitor ---
CONF_MONITOR_RULES = "monitor_rules"
CONF_GRACE_MINUTES = "grace_minutes"
CONF_CHECK_MINUTES = "check_minutes"
CONF_MIN_ENTITIES = "min_entities"
CONF_EXCLUDED = "excluded"
CONF_NOTIFY_ALL = "notify_all"

DEFAULT_GRACE_MINUTES = 5
DEFAULT_CHECK_MINUTES = 1
DEFAULT_MIN_ENTITIES = 2

# Überwachungsregel (Aktion für ausgewählte Integrationen): Schlüssel und Werte
M_ID = "id"
M_NAME = "name"
M_ENABLED = "enabled"
M_ENTRIES = "entries"
M_ON_ERROR = "on_error"
M_ON_UNAVAILABLE = "on_unavailable"
M_ACTION = "action"
M_NOTIFY = "notify"
M_PRESENCE = "presence_entity"
M_REENABLE = "reenable"

MON_ACTION_NONE = "none"
MON_ACTION_RELOAD = "reload"
MON_ACTION_DISABLE = "disable"
MON_ACTIONS = [MON_ACTION_NONE, MON_ACTION_RELOAD, MON_ACTION_DISABLE]

# Felder, die im Formular geleert werden können
OPTIONAL_KEYS = [
    CONF_MOBILE_TARGETS,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_CONTACT,
    CONF_POWER_ENTITY,
    CONF_HEATER_ENTITY,
    CONF_TEMP_ENTITY,
    CONF_SENSITIVITY_ENTITY,
    CONF_SENSITIVITY_VALUE,
]


def signal_update(entry_id: str) -> str:
    """Dispatcher-Signal für Entitätsupdates eines Eintrags."""
    return f"{DOMAIN}_update_{entry_id}"
