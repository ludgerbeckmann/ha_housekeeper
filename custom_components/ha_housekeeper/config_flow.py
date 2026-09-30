"""Config-/Options-Flow: Funktionstyp wählen, dann typspezifisch konfigurieren."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    BLOCK_NOTIFY,
    BLOCK_RETRY,
    CONF_AUTO_RESET_HOURS,
    CONF_BLOCK_ACTION,
    CONF_CLEAR_HOURS,
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
    CONF_MESSAGE,
    CONF_MOBILE_ACTION,
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    CONF_OPEN_ALERT_MINUTES,
    CONF_OPEN_ALERT_REPEAT,
    CONF_POWER_ENTITY,
    CONF_PROFILES,
    CONF_PUMP_ENTITY,
    CONF_PERSISTENT_ENABLED,
    CONF_REPEAT_MESSAGE,
    CONF_RETRY_MINUTES,
    CONF_RULES,
    CONF_TTS_ENABLED,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_TRIGGER_ENTITY,
    CONF_VERIFY_SECONDS,
    CONF_VIBRATION_SENSOR,
    CONF_WINDOWS,
    DEFAULT_AUTO_RESET_HOURS,
    DEFAULT_CLEAR_HOURS,
    DEFAULT_DEBOUNCE,
    DEFAULT_DRY_DURATION,
    DEFAULT_DRY_MAX_POWER,
    DEFAULT_DRY_MIN_POWER,
    DEFAULT_MANUAL_PAUSE_MINUTES,
    DEFAULT_MESSAGE,
    DEFAULT_MOBILE_ACTION,
    DEFAULT_NAME,
    DEFAULT_OPEN_ALERT_MINUTES,
    DEFAULT_OPEN_ALERT_REPEAT,
    DEFAULT_REPEAT_MESSAGE,
    DEFAULT_RETRY_MINUTES,
    DEFAULT_RING_DEBOUNCE,
    DEFAULT_RING_MESSAGE,
    DEFAULT_VERIFY_SECONDS,
    DOMAIN,
    FUNCTION_DOOR_GUARD,
    FUNCTION_DOORBELL,
    FUNCTION_MAILBOX,
    FUNCTION_POOL,
    FUNCTION_PLATFORMS,
    MANUAL_IGNORE,
    MAX_WINDOWS,
    MANUAL_PAUSE,
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
    R_ACTION,
    R_DELAY,
    R_ENTITY,
    R_FOR_MINUTES,
    R_ID,
    R_TIME,
    R_TO_STATE,
    R_TRIGGER,
    R_WEEKDAYS,
    RULE_LOCK,
    RULE_UNLOCK,
    TRIGGER_DOOR_CLOSED,
    TRIGGER_KEYS,
    TRIGGER_STATE,
    TRIGGER_TIME,
    W_DAYS,
    W_END,
    W_ID,
    W_START,
    WEEKDAYS,
)
from .door_guard import rule_summary
from .doorbell import profile_summary
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
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


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


def _mailbox_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = str
    fields[
        vol.Required(
            CONF_VIBRATION_SENSOR, description=_suggest(CONF_VIBRATION_SENSOR, defaults)
        )
    ] = selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor"))
    fields.update(_notify_fields(hass, defaults, with_action=True))
    fields.update(
        {
            vol.Required(
                CONF_MESSAGE, default=defaults.get(CONF_MESSAGE, DEFAULT_MESSAGE)
            ): str,
            vol.Required(
                CONF_REPEAT_MESSAGE,
                default=defaults.get(CONF_REPEAT_MESSAGE, DEFAULT_REPEAT_MESSAGE),
            ): str,
            vol.Required(
                CONF_DEBOUNCE, default=defaults.get(CONF_DEBOUNCE, DEFAULT_DEBOUNCE)
            ): _number(0, 3600, "s"),
            vol.Required(
                CONF_AUTO_RESET_HOURS,
                default=defaults.get(CONF_AUTO_RESET_HOURS, DEFAULT_AUTO_RESET_HOURS),
            ): _number(0, 168, "h"),
        }
    )
    return vol.Schema(fields)


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
            errors = _validate_notify(user_input, require_method=True)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_FUNCTION_TYPE: FUNCTION_MAILBOX, **user_input},
                )
            defaults = user_input
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
        return await self.async_step_mailbox()

    # Briefkasten

    async def async_step_mailbox(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            errors = _validate_notify(user_input, require_method=True)
            if not errors:
                return self.async_create_entry(data=_with_cleared(user_input))
            defaults = user_input
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
