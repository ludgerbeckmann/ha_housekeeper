"""Config-/Options-Flow: Funktionstyp wählen, dann typspezifisch konfigurieren."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    ACTIONS,
    ACT_FAVORITE,
    ACT_MUTE_SET,
    ACT_VOLUME_DIM,
    ACT_VOLUME_SET,
    BLOCK_NOTIFY,
    BLOCK_RETRY,
    CONF_AUTO_RESET_HOURS,
    CONF_BLOCK_ACTION,
    CONF_CLEAR_HOURS,
    CONF_COMMANDS,
    CONF_CONTACT,
    CONF_DEBOUNCE,
    CONF_DRY_AUTO_OFF,
    CONF_DRY_DURATION,
    CONF_DRY_MAX_POWER,
    CONF_DRY_MIN_POWER,
    CONF_FUNCTION_TYPE,
    CONF_LOCK,
    CONF_MANUAL_OVERRIDE,
    CONF_MANUAL_PAUSE_MINUTES,
    CONF_MAX_VOLUME,
    CONF_MESSAGE,
    CONF_MOBILE_ACTION,
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    CONF_OPEN_ALERT_MINUTES,
    CONF_OPEN_ALERT_REPEAT,
    CONF_PERSISTENT_ENABLED,
    CONF_PLAYER,
    CONF_POWER_ENTITY,
    CONF_PROFILES,
    CONF_PUMP_ENTITY,
    CONF_REPEAT_MESSAGE,
    CONF_RETRY_MINUTES,
    CONF_RULES,
    CONF_SCHEDULES,
    CONF_STATUS,
    CONF_STOP_INSTEAD,
    CONF_TIMEOUT_MINUTES,
    CONF_TRIGGER_ENTITY,
    CONF_TTS_ENABLED,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_VERIFY_SECONDS,
    CONF_VIBRATION_SENSOR,
    CONF_VOLUME_STEP,
    CONF_WINDOWS,
    DEFAULT_AUTO_RESET_HOURS,
    DEFAULT_CLEAR_HOURS,
    DEFAULT_DEBOUNCE,
    DEFAULT_DRY_DURATION,
    DEFAULT_DRY_MAX_POWER,
    DEFAULT_DRY_MIN_POWER,
    DEFAULT_MANUAL_PAUSE_MINUTES,
    DEFAULT_MAX_VOLUME,
    DEFAULT_MESSAGE,
    DEFAULT_MOBILE_ACTION,
    DEFAULT_NAME,
    DEFAULT_OPEN_ALERT_MINUTES,
    DEFAULT_OPEN_ALERT_REPEAT,
    DEFAULT_REPEAT_MESSAGE,
    DEFAULT_RETRY_MINUTES,
    DEFAULT_RING_DEBOUNCE,
    DEFAULT_RING_MESSAGE,
    DEFAULT_TIMEOUT_MINUTES,
    DEFAULT_VERIFY_SECONDS,
    DEFAULT_VOLUME_STEP,
    DOMAIN,
    DPTS,
    DPT_DIMMING,
    DPT_PERCENT,
    DPT_SCENE,
    DPT_SWITCH,
    FUNCTION_DOORBELL,
    FUNCTION_DOOR_GUARD,
    FUNCTION_KNX_SONOS,
    FUNCTION_MAILBOX,
    FUNCTION_PLATFORMS,
    FUNCTION_POOL,
    FUNCTION_UPDATER,
    K_ACTION,
    K_ADDRESS,
    K_DPT,
    K_FAVORITE,
    K_ID,
    K_IDLE_TEXT,
    K_NAME,
    K_SCENE,
    K_SOURCE,
    K_VOLUME,
    K_WHEN,
    MANUAL_IGNORE,
    MANUAL_PAUSE,
    MAX_WINDOWS,
    MODE_KEYS,
    MODE_RINGTONE,
    MODE_TTS,
    OPTIONAL_KEYS,
    P_FROM,
    P_ID,
    P_MEDIA,
    P_MODE,
    P_NAME,
    P_PLAYERS,
    P_TEXT,
    P_TO,
    P_TTS_ENTITY,
    P_VOLUME,
    P_WEEKDAYS,
    RULE_LOCK,
    RULE_UNLOCK,
    R_ACTION,
    R_DELAY,
    R_ENTITY,
    R_FOR_MINUTES,
    R_ID,
    R_TIME,
    R_TO_STATE,
    R_TRIGGER,
    R_WEEKDAYS,
    SRC_PLAYING,
    STATUS_SOURCES,
    TEXT_SOURCES,
    TRIGGER_DOOR_CLOSED,
    TRIGGER_KEYS,
    TRIGGER_STATE,
    TRIGGER_TIME,
    UPDATE_MODES,
    UPDATE_MODE_NOTIFY,
    U_BACKUP,
    U_ID,
    U_MODE,
    U_NAME,
    U_TARGETS,
    U_TIME,
    U_WEEKDAYS,
    WEEKDAYS,
    WHENS,
    WHEN_ON,
    W_DAYS,
    W_END,
    W_ID,
    W_START,
)
from .door_guard import rule_summary
from .doorbell import profile_summary
from .knx_codec import is_valid_ga
from .knx_sonos import command_summary, status_summary
from .updater import schedule_summary
from .pool_schedule import describe_window, parse_time, parse_windows


def _mobile_services(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Push-Dienste der Companion-App, beschriftet mit dem Gerätenamen."""
    device_names = {
        f"mobile_app_{slugify(entry.data['device_name'])}": entry.data["device_name"]
        for entry in hass.config_entries.async_entries("mobile_app")
        if entry.data.get("device_name")
    }
    options = [
        selector.SelectOptionDict(
            value=service,
            label=f"{device_names[service]} ({service})"
            if service in device_names
            else service,
        )
        for service in hass.services.async_services_for_domain("notify")
        if service.startswith("mobile_app_")
    ]
    return sorted(options, key=lambda option: option["label"].lower())


def _suggest(key: str, defaults: dict[str, Any]) -> dict[str, Any]:
    return {"suggested_value": defaults[key]} if key in defaults else {}


def _number(
    minimum: float, maximum: float, unit: str | None = None, step: float | str = 1
) -> selector.NumberSelector:
    config: dict[str, Any] = {
        "min": minimum,
        "max": maximum,
        "step": step,
        "mode": selector.NumberSelectorMode.BOX,
    }
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _select(options: list[str], key: str, **kwargs: Any) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            translation_key=key,
            mode=kwargs.pop("mode", selector.SelectSelectorMode.DROPDOWN),
            **kwargs,
        )
    )


def _notify_fields(
    hass: HomeAssistant, defaults: dict[str, Any], with_action: bool
) -> dict[Any, Any]:
    """Felder der gemeinsamen Benachrichtigungswege."""
    fields: dict[Any, Any] = {
        vol.Required(
            CONF_MOBILE_ENABLED, default=defaults.get(CONF_MOBILE_ENABLED, True)
        ): bool,
        vol.Optional(
            CONF_MOBILE_TARGETS, description=_suggest(CONF_MOBILE_TARGETS, defaults)
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=_mobile_services(hass),
                multiple=True,
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    }
    if with_action:
        fields[
            vol.Required(
                CONF_MOBILE_ACTION,
                default=defaults.get(CONF_MOBILE_ACTION, DEFAULT_MOBILE_ACTION),
            )
        ] = bool
    fields.update(
        {
            vol.Required(
                CONF_TTS_ENABLED, default=defaults.get(CONF_TTS_ENABLED, False)
            ): bool,
            vol.Optional(
                CONF_TTS_ENTITY, description=_suggest(CONF_TTS_ENTITY, defaults)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="tts")),
            vol.Optional(
                CONF_TTS_PLAYER, description=_suggest(CONF_TTS_PLAYER, defaults)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
            vol.Required(
                CONF_PERSISTENT_ENABLED,
                default=defaults.get(CONF_PERSISTENT_ENABLED, False),
            ): bool,
        }
    )
    return fields


def _validate_notify(user_input: dict[str, Any], require_method: bool) -> dict[str, str]:
    errors: dict[str, str] = {}
    tts_ready = bool(
        user_input.get(CONF_TTS_ENTITY) and user_input.get(CONF_TTS_PLAYER)
    )
    mobile = user_input.get(CONF_MOBILE_ENABLED) and user_input.get(CONF_MOBILE_TARGETS)
    tts = user_input.get(CONF_TTS_ENABLED) and tts_ready
    if require_method and not (
        mobile or tts or user_input.get(CONF_PERSISTENT_ENABLED)
    ):
        errors["base"] = "no_method"
    if user_input.get(CONF_TTS_ENABLED) and not tts_ready:
        errors["base"] = "tts_incomplete"
    return errors


def _with_cleared(user_input: dict[str, Any]) -> dict[str, Any]:
    """Geleerte optionale Felder explizit auf None setzen.

    Sonst würde beim Lesen der Wert aus der Ersteinrichtung wieder greifen.
    """
    return {**{key: None for key in OPTIONAL_KEYS}, **user_input}


# --- Briefkasten ---------------------------------------------------------------


SECTION_GENERAL = "general"
SECTION_NOTIFICATIONS = "notifications"


def _flatten_sections(user_input: dict[str, Any]) -> dict[str, Any]:
    """Abschnitte des Formulars zu den flachen Schlüsseln der Einstellungen auflösen."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def _mailbox_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    """Formular in zwei ausgeklappte Abschnitte: Allgemein und Benachrichtigungen."""
    general: dict[Any, Any] = {}
    if with_name:
        general[
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))
        ] = str
    general[
        vol.Required(
            CONF_VIBRATION_SENSOR, description=_suggest(CONF_VIBRATION_SENSOR, defaults)
        )
    ] = selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor"))
    general[
        vol.Required(
            CONF_DEBOUNCE, default=defaults.get(CONF_DEBOUNCE, DEFAULT_DEBOUNCE)
        )
    ] = _number(0, 3600, "s")
    general[
        vol.Required(
            CONF_AUTO_RESET_HOURS,
            default=defaults.get(CONF_AUTO_RESET_HOURS, DEFAULT_AUTO_RESET_HOURS),
        )
    ] = _number(0, 168, "h")

    notifications: dict[Any, Any] = dict(_notify_fields(hass, defaults, with_action=True))
    notifications[
        vol.Required(CONF_MESSAGE, default=defaults.get(CONF_MESSAGE, DEFAULT_MESSAGE))
    ] = str
    notifications[
        vol.Required(
            CONF_REPEAT_MESSAGE,
            default=defaults.get(CONF_REPEAT_MESSAGE, DEFAULT_REPEAT_MESSAGE),
        )
    ] = str

    return vol.Schema(
        {
            vol.Required(SECTION_GENERAL): section(
                vol.Schema(general), {"collapsed": False}
            ),
            vol.Required(SECTION_NOTIFICATIONS): section(
                vol.Schema(notifications), {"collapsed": False}
            ),
        }
    )


# --- Türwächter -----------------------------------------------------------------


def _door_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Haustür"))] = str
    fields[
        vol.Required(CONF_LOCK, description=_suggest(CONF_LOCK, defaults))
    ] = selector.EntitySelector(selector.EntitySelectorConfig(domain="lock"))
    fields[
        vol.Optional(CONF_CONTACT, description=_suggest(CONF_CONTACT, defaults))
    ] = selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor"))
    fields.update(
        {
            vol.Required(
                CONF_BLOCK_ACTION, default=defaults.get(CONF_BLOCK_ACTION, BLOCK_NOTIFY)
            ): _select([BLOCK_NOTIFY, BLOCK_RETRY], CONF_BLOCK_ACTION),
            vol.Required(
                CONF_RETRY_MINUTES,
                default=defaults.get(CONF_RETRY_MINUTES, DEFAULT_RETRY_MINUTES),
            ): _number(1, 240, "min"),
            vol.Required(
                CONF_OPEN_ALERT_MINUTES,
                default=defaults.get(CONF_OPEN_ALERT_MINUTES, DEFAULT_OPEN_ALERT_MINUTES),
            ): _number(0, 1440, "min"),
            vol.Required(
                CONF_OPEN_ALERT_REPEAT,
                default=defaults.get(CONF_OPEN_ALERT_REPEAT, DEFAULT_OPEN_ALERT_REPEAT),
            ): _number(0, 1440, "min"),
            vol.Required(
                CONF_VERIFY_SECONDS,
                default=defaults.get(CONF_VERIFY_SECONDS, DEFAULT_VERIFY_SECONDS),
            ): _number(0, 600, "s"),
            vol.Required(
                CONF_MANUAL_OVERRIDE,
                default=defaults.get(CONF_MANUAL_OVERRIDE, MANUAL_IGNORE),
            ): _select([MANUAL_IGNORE, MANUAL_PAUSE], CONF_MANUAL_OVERRIDE),
            vol.Required(
                CONF_MANUAL_PAUSE_MINUTES,
                default=defaults.get(
                    CONF_MANUAL_PAUSE_MINUTES, DEFAULT_MANUAL_PAUSE_MINUTES
                ),
            ): _number(1, 1440, "min"),
        }
    )
    fields.update(_notify_fields(hass, defaults, with_action=False))
    return vol.Schema(fields)


def _validate_door(user_input: dict[str, Any]) -> dict[str, str]:
    errors = _validate_notify(user_input, require_method=False)
    if float(user_input.get(CONF_OPEN_ALERT_MINUTES) or 0) > 0 and not user_input.get(
        CONF_CONTACT
    ):
        errors["base"] = "alert_needs_contact"
    return errors


# --- Türklingel -----------------------------------------------------------------


def _bell_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Türklingel"))] = str
    fields[
        vol.Required(CONF_TRIGGER_ENTITY, description=_suggest(CONF_TRIGGER_ENTITY, defaults))
    ] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["binary_sensor", "event"])
    )
    fields[
        vol.Required(
            CONF_DEBOUNCE, default=defaults.get(CONF_DEBOUNCE, DEFAULT_RING_DEBOUNCE)
        )
    ] = _number(0, 3600, "s")
    fields.update(
        {
            vol.Required(
                CONF_MOBILE_ENABLED, default=defaults.get(CONF_MOBILE_ENABLED, True)
            ): bool,
            vol.Optional(
                CONF_MOBILE_TARGETS, description=_suggest(CONF_MOBILE_TARGETS, defaults)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_mobile_services(hass),
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_MESSAGE, default=defaults.get(CONF_MESSAGE, DEFAULT_RING_MESSAGE)
            ): str,
            vol.Required(
                CONF_CLEAR_HOURS,
                default=defaults.get(CONF_CLEAR_HOURS, DEFAULT_CLEAR_HOURS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=168,
                    step=0.5,
                    unit_of_measurement="h",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )
    return vol.Schema(fields)


def _validate_bell(user_input: dict[str, Any]) -> dict[str, str]:
    if user_input.get(CONF_MOBILE_ENABLED) and not user_input.get(CONF_MOBILE_TARGETS):
        return {"base": "no_targets"}
    return {}


# --- Poolpumpe -------------------------------------------------------------------

_PUMP_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
)

# Standard der Benachrichtigung bei Trockenlauf: nur persistente Meldung
_POOL_NOTIFY_DEFAULTS = {CONF_MOBILE_ENABLED: False, CONF_PERSISTENT_ENABLED: True}


def _dry_run_schema(hass: HomeAssistant, defaults: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Optional(
            CONF_POWER_ENTITY, description=_suggest(CONF_POWER_ENTITY, defaults)
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="power")
        ),
        vol.Required(
            CONF_DRY_MIN_POWER,
            default=defaults.get(CONF_DRY_MIN_POWER, DEFAULT_DRY_MIN_POWER),
        ): _number(0, 100000, "W", "any"),
        vol.Required(
            CONF_DRY_MAX_POWER,
            default=defaults.get(CONF_DRY_MAX_POWER, DEFAULT_DRY_MAX_POWER),
        ): _number(0, 100000, "W", "any"),
        vol.Required(
            CONF_DRY_DURATION,
            default=defaults.get(CONF_DRY_DURATION, DEFAULT_DRY_DURATION),
        ): _number(1, 120, "min", "any"),
        vol.Required(
            CONF_DRY_AUTO_OFF, default=defaults.get(CONF_DRY_AUTO_OFF, False)
        ): bool,
    }
    fields.update(
        _notify_fields(hass, {**_POOL_NOTIFY_DEFAULTS, **defaults}, with_action=False)
    )
    return vol.Schema(fields)


def _validate_dry_run(user_input: dict[str, Any]) -> dict[str, str]:
    errors = _validate_notify(user_input, require_method=False)
    if user_input.get(CONF_MOBILE_ENABLED) and not user_input.get(CONF_MOBILE_TARGETS):
        errors["base"] = "no_targets"
    if user_input.get(CONF_POWER_ENTITY) and float(
        user_input[CONF_DRY_MIN_POWER]
    ) >= float(user_input[CONF_DRY_MAX_POWER]):
        errors["base"] = "min_ge_max"
    return errors


# --- KNX/Sonos-Connector ---------------------------------------------------------

_SONOS_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="media_player", integration="sonos")
)


def _knx_general_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PLAYER, default=defaults.get(CONF_PLAYER)): _SONOS_SELECTOR,
            vol.Required(
                CONF_MAX_VOLUME, default=defaults.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME)
            ): _number(0, 100, "%"),
            vol.Required(
                CONF_VOLUME_STEP, default=defaults.get(CONF_VOLUME_STEP, DEFAULT_VOLUME_STEP)
            ): _number(1, 50, "%"),
            vol.Required(
                CONF_STOP_INSTEAD, default=defaults.get(CONF_STOP_INSTEAD, False)
            ): bool,
        }
    )


def _validate_command_basic(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    dpt, action = user_input[K_DPT], user_input[K_ACTION]
    if not is_valid_ga(user_input[K_ADDRESS]):
        errors["base"] = "invalid_address"
    elif (dpt == DPT_DIMMING) != (action == ACT_VOLUME_DIM):
        errors["base"] = "dimming_mismatch"
    elif action == ACT_MUTE_SET and dpt != DPT_SWITCH:
        errors["base"] = "mute_set_needs_switch"
    return errors


# Ohne weitere Angaben (Bedingung, Szene, Lautstärke, Favorit) kann ein Befehl sofort gespeichert werden.
def _command_needs_params(draft: dict[str, Any]) -> bool:
    return bool(
        (draft[K_DPT] == DPT_SWITCH and draft[K_ACTION] != ACT_MUTE_SET)
        or draft[K_DPT] == DPT_SCENE
        or (draft[K_ACTION] == ACT_VOLUME_SET and draft[K_DPT] != DPT_PERCENT)
        or draft[K_ACTION] == ACT_FAVORITE
    )


# --- Updater ----------------------------------------------------------------------


def _updater_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Updater"))] = str
    fields[
        vol.Required(
            CONF_TIMEOUT_MINUTES,
            default=defaults.get(CONF_TIMEOUT_MINUTES, DEFAULT_TIMEOUT_MINUTES),
        )
    ] = _number(1, 720, "min")
    fields.update(
        _notify_fields(hass, {**_POOL_NOTIFY_DEFAULTS, **defaults}, with_action=False)
    )
    return vol.Schema(fields)


def _validate_updater(user_input: dict[str, Any]) -> dict[str, str]:
    errors = _validate_notify(user_input, require_method=True)
    if user_input.get(CONF_MOBILE_ENABLED) and not user_input.get(CONF_MOBILE_TARGETS):
        errors["base"] = "no_targets"
    return errors


# --- Config-Flow ---------------------------------------------------------------


class HousekeeperConfigFlow(ConfigFlow, domain=DOMAIN):
    """Funktion (Eintrag) hinzufügen."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await getattr(self, f"async_step_{user_input[CONF_FUNCTION_TYPE]}")()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FUNCTION_TYPE, default=FUNCTION_MAILBOX
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(FUNCTION_PLATFORMS),
                            translation_key=CONF_FUNCTION_TYPE,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_mailbox(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_notify(flat, require_method=True)
            if not errors:
                return self.async_create_entry(
                    title=flat[CONF_NAME],
                    data={CONF_FUNCTION_TYPE: FUNCTION_MAILBOX, **flat},
                )
            defaults = flat
        return self.async_show_form(
            step_id="mailbox",
            data_schema=_mailbox_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    async def async_step_door_guard(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            errors = _validate_door(user_input)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_FUNCTION_TYPE: FUNCTION_DOOR_GUARD,
                        CONF_RULES: [],
                        **user_input,
                    },
                )
            defaults = user_input
        return self.async_show_form(
            step_id="door_guard",
            data_schema=_door_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    async def async_step_doorbell(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            errors = _validate_bell(user_input)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_FUNCTION_TYPE: FUNCTION_DOORBELL,
                        CONF_PROFILES: [],
                        **user_input,
                    },
                )
            defaults = user_input
        return self.async_show_form(
            step_id="doorbell",
            data_schema=_bell_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    async def async_step_pool_pump(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(f"{FUNCTION_POOL}:{user_input[CONF_PUMP_ENTITY]}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_FUNCTION_TYPE: FUNCTION_POOL,
                    CONF_PUMP_ENTITY: user_input[CONF_PUMP_ENTITY],
                },
            )
        return self.async_show_form(
            step_id="pool_pump",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Pool"): str,
                    vol.Required(CONF_PUMP_ENTITY): _PUMP_SELECTOR,
                }
            ),
        )

    async def async_step_knx_sonos(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self.hass.services.has_service("knx", "event_register"):
            return self.async_abort(reason="knx_missing")
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_FUNCTION_TYPE: FUNCTION_KNX_SONOS,
                    CONF_PLAYER: user_input[CONF_PLAYER],
                    CONF_MAX_VOLUME: DEFAULT_MAX_VOLUME,
                    CONF_VOLUME_STEP: DEFAULT_VOLUME_STEP,
                    CONF_STOP_INSTEAD: False,
                    CONF_COMMANDS: [],
                    CONF_STATUS: [],
                },
            )
        return self.async_show_form(
            step_id="knx_sonos",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="KNX Sonos"): str,
                    vol.Required(CONF_PLAYER): _SONOS_SELECTOR,
                }
            ),
        )

    async def async_step_updater(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            errors = _validate_updater(user_input)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_FUNCTION_TYPE: FUNCTION_UPDATER,
                        CONF_SCHEDULES: [],
                        **user_input,
                    },
                )
            defaults = user_input
        return self.async_show_form(
            step_id="updater",
            data_schema=_updater_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return HousekeeperOptionsFlow()


# --- Options-Flow ---------------------------------------------------------------


class HousekeeperOptionsFlow(OptionsFlow):
    """Einstellungen einer Funktion nachträglich ändern."""

    def __init__(self) -> None:
        self._draft: dict[str, Any] = {}
        self._edit_id: str | None = None

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    def _rules(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_RULES) or [])

    def _save(self, options: dict[str, Any]) -> None:
        self.hass.config_entries.async_update_entry(
            self.config_entry, options={**self.config_entry.options, **options}
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        function_type = self.config_entry.data[CONF_FUNCTION_TYPE]
        if function_type == FUNCTION_DOOR_GUARD:
            return await self.async_step_menu()
        if function_type == FUNCTION_DOORBELL:
            return await self.async_step_bell_menu()
        if function_type == FUNCTION_POOL:
            return await self.async_step_pool_menu()
        if function_type == FUNCTION_KNX_SONOS:
            return await self.async_step_knx_menu()
        if function_type == FUNCTION_UPDATER:
            return await self.async_step_upd_menu()
        return await self.async_step_mailbox()

    # Briefkasten

    async def async_step_mailbox(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_notify(flat, require_method=True)
            if not errors:
                return self.async_create_entry(data=_with_cleared(flat))
            defaults = flat
        return self.async_show_form(
            step_id="mailbox",
            data_schema=_mailbox_schema(self.hass, defaults, with_name=False),
            errors=errors,
        )

    # Türwächter: Menü

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["general", "add_rule"]
        if self._rules():
            options += ["edit_rule", "delete_rule"]
        options.append("done")
        return self.async_show_menu(step_id="menu", menu_options=options)

    async def async_step_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(data=dict(self.config_entry.options))

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            errors = _validate_door(user_input)
            if not errors:
                self._save(_with_cleared(user_input))
                return await self.async_step_menu()
            defaults = user_input
        return self.async_show_form(
            step_id="general",
            data_schema=_door_schema(self.hass, defaults, with_name=False),
            errors=errors,
        )

    # Türwächter: Regeln

    async def async_step_add_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_rule_type()

    async def async_step_edit_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            rule = next(r for r in self._rules() if r[R_ID] == user_input["rule"])
            self._edit_id = rule[R_ID]
            self._draft = dict(rule)
            return await self.async_step_rule_type()
        return self.async_show_form(
            step_id="edit_rule", data_schema=self._rule_picker_schema()
        )

    async def async_step_delete_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {CONF_RULES: [r for r in self._rules() if r[R_ID] != user_input["rule"]]}
            )
            return await self.async_step_menu()
        return self.async_show_form(
            step_id="delete_rule", data_schema=self._rule_picker_schema()
        )

    def _rule_picker_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("rule"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=r[R_ID], label=rule_summary(self.hass, r)
                            )
                            for r in self._rules()
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    async def async_step_rule_type(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        draft = self._draft
        if user_input is not None:
            if user_input[R_TRIGGER] == TRIGGER_DOOR_CLOSED:
                if not self._current.get(CONF_CONTACT):
                    errors["base"] = "no_contact"
                elif user_input[R_ACTION] != RULE_LOCK:
                    errors["base"] = "door_closed_needs_lock"
            if not errors:
                self._draft.update(user_input)
                return await getattr(self, f"async_step_rule_{user_input[R_TRIGGER]}")()
            draft = user_input
        return self.async_show_form(
            step_id="rule_type",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        R_ACTION, default=draft.get(R_ACTION, RULE_LOCK)
                    ): _select([RULE_LOCK, RULE_UNLOCK], "rule_action"),
                    vol.Required(
                        R_TRIGGER, default=draft.get(R_TRIGGER, TRIGGER_STATE)
                    ): _select(
                        [TRIGGER_STATE, TRIGGER_TIME, TRIGGER_DOOR_CLOSED],
                        "rule_trigger",
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_rule_state(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._draft.update(user_input)
            return await self._finish_rule()
        d = self._draft
        return self.async_show_form(
            step_id="rule_state",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        R_ENTITY, description=_suggest(R_ENTITY, d)
                    ): selector.EntitySelector(),
                    vol.Required(R_TO_STATE, description=_suggest(R_TO_STATE, d)): str,
                    vol.Required(R_FOR_MINUTES, default=d.get(R_FOR_MINUTES, 0)): _number(
                        0, 1440, "min"
                    ),
                }
            ),
        )

    async def async_step_rule_time(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            if not user_input.get(R_WEEKDAYS):
                errors["base"] = "no_weekday"
            else:
                self._draft.update(user_input)
                return await self._finish_rule()
            d = user_input
        return self.async_show_form(
            step_id="rule_time",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        R_TIME, description=_suggest(R_TIME, d)
                    ): selector.TimeSelector(),
                    vol.Required(
                        R_WEEKDAYS, default=d.get(R_WEEKDAYS, WEEKDAYS)
                    ): _select(
                        WEEKDAYS,
                        "weekday",
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_rule_door_closed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._draft.update(user_input)
            return await self._finish_rule()
        return self.async_show_form(
            step_id="rule_door_closed",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        R_DELAY, default=self._draft.get(R_DELAY, 30)
                    ): _number(0, 3600, "s")
                }
            ),
        )

    async def _finish_rule(self) -> ConfigFlowResult:
        trigger = self._draft[R_TRIGGER]
        rule: dict[str, Any] = {
            R_ID: self._edit_id or uuid.uuid4().hex[:8],
            R_ACTION: self._draft[R_ACTION],
            R_TRIGGER: trigger,
            **{k: self._draft[k] for k in TRIGGER_KEYS[trigger] if k in self._draft},
        }
        rules = self._rules()
        if self._edit_id:
            rules = [rule if r[R_ID] == self._edit_id else r for r in rules]
        else:
            rules.append(rule)
        self._save({CONF_RULES: rules})
        return await self.async_step_menu()

    # Türklingel: Menü und Profile

    def _profiles(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_PROFILES) or [])

    async def async_step_bell_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["bell_general", "add_profile"]
        if self._profiles():
            options += ["edit_profile", "delete_profile"]
        options.append("done")
        return self.async_show_menu(step_id="bell_menu", menu_options=options)

    async def async_step_bell_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            errors = _validate_bell(user_input)
            if not errors:
                self._save(_with_cleared(user_input))
                return await self.async_step_bell_menu()
            defaults = user_input
        return self.async_show_form(
            step_id="bell_general",
            data_schema=_bell_schema(self.hass, defaults, with_name=False),
            errors=errors,
        )

    async def async_step_add_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_profile_basic()

    async def async_step_edit_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            profile = next(p for p in self._profiles() if p[P_ID] == user_input["profile"])
            self._edit_id = profile[P_ID]
            self._draft = dict(profile)
            return await self.async_step_profile_basic()
        return self.async_show_form(
            step_id="edit_profile", data_schema=self._profile_picker_schema()
        )

    async def async_step_delete_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {
                    CONF_PROFILES: [
                        p for p in self._profiles() if p[P_ID] != user_input["profile"]
                    ]
                }
            )
            return await self.async_step_bell_menu()
        return self.async_show_form(
            step_id="delete_profile", data_schema=self._profile_picker_schema()
        )

    def _profile_picker_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("profile"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=p[P_ID], label=profile_summary(self.hass, p)
                            )
                            for p in self._profiles()
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    async def async_step_profile_basic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            if not user_input.get(P_PLAYERS):
                errors["base"] = "no_players"
            elif not user_input.get(P_WEEKDAYS):
                errors["base"] = "no_weekday"
            else:
                self._draft.update(user_input)
                return await getattr(self, f"async_step_profile_{user_input[P_MODE]}")()
            d = user_input
        return self.async_show_form(
            step_id="profile_basic",
            data_schema=vol.Schema(
                {
                    vol.Required(P_NAME, description=_suggest(P_NAME, d)): str,
                    vol.Required(
                        P_FROM, default=d.get(P_FROM, "07:00:00")
                    ): selector.TimeSelector(),
                    vol.Required(
                        P_TO, default=d.get(P_TO, "22:00:00")
                    ): selector.TimeSelector(),
                    vol.Required(P_WEEKDAYS, default=d.get(P_WEEKDAYS, WEEKDAYS)): _select(
                        WEEKDAYS,
                        "weekday",
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    ),
                    vol.Required(
                        P_PLAYERS, description=_suggest(P_PLAYERS, d)
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="media_player", multiple=True)
                    ),
                    vol.Required(P_MODE, default=d.get(P_MODE, MODE_TTS)): _select(
                        [MODE_TTS, MODE_RINGTONE],
                        "profile_mode",
                        mode=selector.SelectSelectorMode.LIST,
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_profile_tts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._draft.update(user_input)
            return await self._finish_profile()
        d = self._draft
        return self.async_show_form(
            step_id="profile_tts",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        P_TTS_ENTITY, description=_suggest(P_TTS_ENTITY, d)
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="tts")),
                    vol.Required(P_TEXT, default=d.get(P_TEXT, DEFAULT_RING_MESSAGE)): str,
                    vol.Required(P_VOLUME, default=d.get(P_VOLUME, 0)): _number(0, 100, "%"),
                }
            ),
        )

    async def async_step_profile_ringtone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._draft.update(user_input)
            return await self._finish_profile()
        d = self._draft
        return self.async_show_form(
            step_id="profile_ringtone",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        P_MEDIA, description=_suggest(P_MEDIA, d)
                    ): selector.MediaSelector(
                        selector.MediaSelectorConfig(accept=["audio/*"])
                    ),
                    vol.Required(P_VOLUME, default=d.get(P_VOLUME, 0)): _number(0, 100, "%"),
                }
            ),
        )

    async def _finish_profile(self) -> ConfigFlowResult:
        mode = self._draft[P_MODE]
        profile: dict[str, Any] = {
            P_ID: self._edit_id or uuid.uuid4().hex[:8],
            **{
                k: self._draft[k]
                for k in (P_NAME, P_FROM, P_TO, P_WEEKDAYS, P_PLAYERS, P_MODE, P_VOLUME)
                if k in self._draft
            },
            **{k: self._draft[k] for k in MODE_KEYS[mode] if k in self._draft},
        }
        profiles = self._profiles()
        if self._edit_id:
            profiles = [profile if p[P_ID] == self._edit_id else p for p in profiles]
        else:
            profiles.append(profile)
        self._save({CONF_PROFILES: profiles})
        return await self.async_step_bell_menu()

    # Poolpumpe: Menü, Zeitfenster, Trockenlauf

    def _windows(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_WINDOWS) or [])

    async def async_step_pool_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["pool_general", "add_window"]
        if self._windows():
            options += ["edit_window", "delete_window"]
        options += ["dry_run", "done"]
        return self.async_show_menu(step_id="pool_menu", menu_options=options)

    async def async_step_pool_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save({CONF_PUMP_ENTITY: user_input[CONF_PUMP_ENTITY]})
            return await self.async_step_pool_menu()
        return self.async_show_form(
            step_id="pool_general",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PUMP_ENTITY, default=self._current[CONF_PUMP_ENTITY]
                    ): _PUMP_SELECTOR
                }
            ),
        )

    async def async_step_add_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_window_edit()

    async def async_step_edit_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            window = next(w for w in self._windows() if w[W_ID] == user_input["window"])
            self._edit_id = window[W_ID]
            self._draft = dict(window)
            return await self.async_step_window_edit()
        return self.async_show_form(
            step_id="edit_window", data_schema=self._window_picker_schema()
        )

    async def async_step_delete_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {
                    CONF_WINDOWS: [
                        w for w in self._windows() if w[W_ID] != user_input["window"]
                    ]
                }
            )
            return await self.async_step_pool_menu()
        return self.async_show_form(
            step_id="delete_window", data_schema=self._window_picker_schema()
        )

    def _window_picker_schema(self) -> vol.Schema:
        options = []
        for raw in self._windows():
            window = next(iter(parse_windows([raw])), None)
            label = (
                describe_window(window, self.hass.config.language)
                if window
                else str(raw)
            )
            options.append(selector.SelectOptionDict(value=raw[W_ID], label=label))
        return vol.Schema(
            {
                vol.Required("window"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, mode=selector.SelectSelectorMode.LIST
                    )
                )
            }
        )

    async def async_step_window_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            windows = self._windows()
            if self._edit_id is None and len(windows) >= MAX_WINDOWS:
                errors["base"] = "too_many_windows"
            elif parse_time(user_input[W_START]) == parse_time(user_input[W_END]):
                errors["base"] = "start_equals_end"
            elif not user_input[W_DAYS]:
                errors["base"] = "no_weekday"
            else:
                window = {
                    W_ID: self._edit_id or uuid.uuid4().hex[:8],
                    W_START: user_input[W_START],
                    W_END: user_input[W_END],
                    W_DAYS: user_input[W_DAYS],
                }
                if self._edit_id:
                    windows = [window if w[W_ID] == self._edit_id else w for w in windows]
                else:
                    windows.append(window)
                self._save({CONF_WINDOWS: windows})
                return await self.async_step_pool_menu()
            d = user_input
        return self.async_show_form(
            step_id="window_edit",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        W_START, default=d.get(W_START, "08:00:00")
                    ): selector.TimeSelector(),
                    vol.Required(
                        W_END, default=d.get(W_END, "10:00:00")
                    ): selector.TimeSelector(),
                    vol.Required(W_DAYS, default=d.get(W_DAYS, WEEKDAYS)): _select(
                        WEEKDAYS,
                        "weekday",
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_dry_run(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            errors = _validate_dry_run(user_input)
            if not errors:
                self._save(_with_cleared(user_input))
                return await self.async_step_pool_menu()
            defaults = user_input
        return self.async_show_form(
            step_id="dry_run",
            data_schema=_dry_run_schema(self.hass, defaults),
            errors=errors,
        )

    # KNX/Sonos-Connector: Menü, Befehle, Rückmeldungen

    def _commands(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_COMMANDS) or [])

    def _status_list(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_STATUS) or [])

    async def async_step_knx_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["knx_general", "add_command"]
        if self._commands():
            options += ["edit_command", "delete_command"]
        options.append("add_status")
        if self._status_list():
            options += ["edit_status", "delete_status"]
        options.append("done")
        return self.async_show_menu(step_id="knx_menu", menu_options=options)

    async def async_step_knx_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(user_input)
            return await self.async_step_knx_menu()
        return self.async_show_form(
            step_id="knx_general", data_schema=_knx_general_schema(self._current)
        )

    def _item_picker_schema(self, items: list[dict[str, Any]], summary) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("item"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=i[K_ID], label=summary(self.hass, i)
                            )
                            for i in items
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    # Befehle

    async def async_step_add_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_command_basic()

    async def async_step_edit_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            command = next(c for c in self._commands() if c[K_ID] == user_input["item"])
            self._edit_id = command[K_ID]
            self._draft = dict(command)
            return await self.async_step_command_basic()
        return self.async_show_form(
            step_id="edit_command",
            data_schema=self._item_picker_schema(self._commands(), command_summary),
        )

    async def async_step_delete_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {
                    CONF_COMMANDS: [
                        c for c in self._commands() if c[K_ID] != user_input["item"]
                    ]
                }
            )
            return await self.async_step_knx_menu()
        return self.async_show_form(
            step_id="delete_command",
            data_schema=self._item_picker_schema(self._commands(), command_summary),
        )

    async def async_step_command_basic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            errors = _validate_command_basic(user_input)
            if not errors:
                self._draft = {**user_input}
                if _command_needs_params(self._draft):
                    return await self.async_step_command_params()
                return await self._finish_command()
            d = user_input
        return self.async_show_form(
            step_id="command_basic",
            data_schema=vol.Schema(
                {
                    vol.Required(K_NAME, description=_suggest(K_NAME, d)): str,
                    vol.Required(K_ADDRESS, description=_suggest(K_ADDRESS, d)): str,
                    vol.Required(K_DPT, default=d.get(K_DPT, DPT_SWITCH)): _select(
                        DPTS, "knx_dpt", mode=selector.SelectSelectorMode.LIST
                    ),
                    vol.Required(K_ACTION, default=d.get(K_ACTION, "play")): _select(
                        ACTIONS, "knx_action"
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_command_params(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        d = self._draft
        if user_input is not None:
            self._draft = {**d, **user_input}
            return await self._finish_command()
        fields: dict[Any, Any] = {}
        if d[K_DPT] == DPT_SWITCH and d[K_ACTION] != ACT_MUTE_SET:
            fields[vol.Required(K_WHEN, default=d.get(K_WHEN, WHEN_ON))] = _select(
                WHENS, "knx_when", mode=selector.SelectSelectorMode.LIST
            )
        if d[K_DPT] == DPT_SCENE:
            fields[vol.Required(K_SCENE, default=d.get(K_SCENE, 1))] = _number(1, 64)
        if d[K_ACTION] == ACT_VOLUME_SET and d[K_DPT] != DPT_PERCENT:
            fields[vol.Required(K_VOLUME, default=d.get(K_VOLUME, 20))] = _number(0, 100, "%")
        if d[K_ACTION] == ACT_FAVORITE:
            state = self.hass.states.get(self._current.get(CONF_PLAYER, ""))
            sources = sorted((state.attributes.get("source_list") or []) if state else [])
            fields[vol.Required(K_FAVORITE, description=_suggest(K_FAVORITE, d))] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=sources,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            )
        return self.async_show_form(
            step_id="command_params", data_schema=vol.Schema(fields)
        )

    async def _finish_command(self) -> ConfigFlowResult:
        d = self._draft
        keep = [K_NAME, K_ADDRESS, K_DPT, K_ACTION]
        if d[K_DPT] == DPT_SWITCH and d[K_ACTION] != ACT_MUTE_SET:
            keep.append(K_WHEN)
        if d[K_DPT] == DPT_SCENE:
            keep.append(K_SCENE)
        if d[K_ACTION] == ACT_VOLUME_SET and d[K_DPT] != DPT_PERCENT:
            keep.append(K_VOLUME)
        if d[K_ACTION] == ACT_FAVORITE:
            keep.append(K_FAVORITE)
        command = {K_ID: self._edit_id or uuid.uuid4().hex[:8]}
        command.update({k: d[k] for k in keep if k in d})
        commands = self._commands()
        if self._edit_id:
            commands = [command if c[K_ID] == self._edit_id else c for c in commands]
        else:
            commands.append(command)
        self._save({CONF_COMMANDS: commands})
        return await self.async_step_knx_menu()

    # Rückmeldungen

    async def async_step_add_status(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_status_edit()

    async def async_step_edit_status(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            status = next(s for s in self._status_list() if s[K_ID] == user_input["item"])
            self._edit_id = status[K_ID]
            self._draft = dict(status)
            return await self.async_step_status_edit()
        return self.async_show_form(
            step_id="edit_status",
            data_schema=self._item_picker_schema(self._status_list(), status_summary),
        )

    async def async_step_delete_status(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {
                    CONF_STATUS: [
                        s for s in self._status_list() if s[K_ID] != user_input["item"]
                    ]
                }
            )
            return await self.async_step_knx_menu()
        return self.async_show_form(
            step_id="delete_status",
            data_schema=self._item_picker_schema(self._status_list(), status_summary),
        )

    async def async_step_status_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            if not is_valid_ga(user_input[K_ADDRESS]):
                errors["base"] = "invalid_address"
            else:
                status = {
                    K_ID: self._edit_id or uuid.uuid4().hex[:8],
                    K_NAME: user_input[K_NAME],
                    K_SOURCE: user_input[K_SOURCE],
                    K_ADDRESS: user_input[K_ADDRESS],
                }
                if user_input[K_SOURCE] in TEXT_SOURCES:
                    status[K_IDLE_TEXT] = user_input.get(K_IDLE_TEXT, "")
                items = self._status_list()
                if self._edit_id:
                    items = [status if s[K_ID] == self._edit_id else s for s in items]
                else:
                    items.append(status)
                self._save({CONF_STATUS: items})
                return await self.async_step_knx_menu()
            d = user_input
        return self.async_show_form(
            step_id="status_edit",
            data_schema=vol.Schema(
                {
                    vol.Required(K_NAME, description=_suggest(K_NAME, d)): str,
                    vol.Required(K_SOURCE, default=d.get(K_SOURCE, SRC_PLAYING)): _select(
                        STATUS_SOURCES, "knx_source"
                    ),
                    vol.Required(K_ADDRESS, description=_suggest(K_ADDRESS, d)): str,
                    vol.Optional(K_IDLE_TEXT, default=d.get(K_IDLE_TEXT, "")): str,
                }
            ),
            errors=errors,
        )

    # Updater: Menü und Zeitpläne

    def _schedules(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_SCHEDULES) or [])

    async def async_step_upd_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["upd_general", "add_schedule"]
        if self._schedules():
            options += ["edit_schedule", "delete_schedule"]
        options.append("done")
        return self.async_show_menu(step_id="upd_menu", menu_options=options)

    async def async_step_upd_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            errors = _validate_updater(user_input)
            if not errors:
                self._save(_with_cleared(user_input))
                return await self.async_step_upd_menu()
            defaults = user_input
        return self.async_show_form(
            step_id="upd_general",
            data_schema=_updater_schema(self.hass, defaults, with_name=False),
            errors=errors,
        )

    async def async_step_add_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_schedule_edit()

    async def async_step_edit_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            schedule = next(s for s in self._schedules() if s[U_ID] == user_input["schedule"])
            self._edit_id = schedule[U_ID]
            self._draft = dict(schedule)
            return await self.async_step_schedule_edit()
        return self.async_show_form(
            step_id="edit_schedule", data_schema=self._schedule_picker_schema()
        )

    async def async_step_delete_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {
                    CONF_SCHEDULES: [
                        s for s in self._schedules() if s[U_ID] != user_input["schedule"]
                    ]
                }
            )
            return await self.async_step_upd_menu()
        return self.async_show_form(
            step_id="delete_schedule", data_schema=self._schedule_picker_schema()
        )

    def _schedule_picker_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("schedule"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=s[U_ID], label=schedule_summary(self.hass, s)
                            )
                            for s in self._schedules()
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    async def async_step_schedule_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            if not user_input.get(U_TARGETS):
                errors["base"] = "no_update_selected"
            elif not user_input.get(U_WEEKDAYS):
                errors["base"] = "no_weekday"
            else:
                schedule = {
                    U_ID: self._edit_id or uuid.uuid4().hex[:8],
                    U_NAME: user_input[U_NAME],
                    U_TIME: user_input[U_TIME],
                    U_WEEKDAYS: user_input[U_WEEKDAYS],
                    U_MODE: user_input[U_MODE],
                    U_TARGETS: user_input[U_TARGETS],
                    U_BACKUP: user_input[U_BACKUP],
                }
                schedules = self._schedules()
                if self._edit_id:
                    schedules = [
                        schedule if s[U_ID] == self._edit_id else s for s in schedules
                    ]
                else:
                    schedules.append(schedule)
                self._save({CONF_SCHEDULES: schedules})
                return await self.async_step_upd_menu()
            d = user_input
        return self.async_show_form(
            step_id="schedule_edit",
            data_schema=vol.Schema(
                {
                    vol.Required(U_NAME, description=_suggest(U_NAME, d)): str,
                    vol.Required(
                        U_TIME, default=d.get(U_TIME, "03:00:00")
                    ): selector.TimeSelector(),
                    vol.Required(U_WEEKDAYS, default=d.get(U_WEEKDAYS, ["sun"])): _select(
                        WEEKDAYS,
                        "weekday",
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    ),
                    vol.Required(U_MODE, default=d.get(U_MODE, UPDATE_MODE_NOTIFY)): _select(
                        UPDATE_MODES, "update_mode", mode=selector.SelectSelectorMode.LIST
                    ),
                    vol.Required(
                        U_TARGETS, description=_suggest(U_TARGETS, d)
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="update", multiple=True)
                    ),
                    vol.Required(U_BACKUP, default=d.get(U_BACKUP, False)): bool,
                }
            ),
            errors=errors,
        )
