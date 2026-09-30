"""Config-/Options-Flow: Funktionstyp wählen, dann typspezifisch konfigurieren."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_RESET_HOURS,
    CONF_DEBOUNCE,
    CONF_FUNCTION_TYPE,
    CONF_MESSAGE,
    CONF_MOBILE_ACTION,
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    CONF_PERSISTENT_ENABLED,
    CONF_TTS_ENABLED,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_VIBRATION_SENSOR,
    DEFAULT_AUTO_RESET_HOURS,
    DEFAULT_DEBOUNCE,
    DEFAULT_MESSAGE,
    DEFAULT_MOBILE_ACTION,
    DEFAULT_NAME,
    DOMAIN,
    FUNCTION_MAILBOX,
    FUNCTION_PLATFORMS,
)


def _mobile_services(hass: HomeAssistant) -> list[str]:
    services = hass.services.async_services_for_domain("notify")
    return sorted(s for s in services if s.startswith("mobile_app_"))


def _suggest(key: str, defaults: dict[str, Any]) -> dict[str, Any]:
    return {"suggested_value": defaults[key]} if key in defaults else {}


def _mailbox_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = str
    fields.update(
        {
            vol.Required(
                CONF_VIBRATION_SENSOR, description=_suggest(CONF_VIBRATION_SENSOR, defaults)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
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
                CONF_MOBILE_ACTION,
                default=defaults.get(CONF_MOBILE_ACTION, DEFAULT_MOBILE_ACTION),
            ): bool,
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
            vol.Required(
                CONF_MESSAGE, default=defaults.get(CONF_MESSAGE, DEFAULT_MESSAGE)
            ): str,
            vol.Required(
                CONF_DEBOUNCE, default=defaults.get(CONF_DEBOUNCE, DEFAULT_DEBOUNCE)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=3600,
                    step=1,
                    unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_AUTO_RESET_HOURS,
                default=defaults.get(CONF_AUTO_RESET_HOURS, DEFAULT_AUTO_RESET_HOURS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=168,
                    step=1,
                    unit_of_measurement="h",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )
    return vol.Schema(fields)


def _validate_mailbox(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    mobile = user_input.get(CONF_MOBILE_ENABLED) and user_input.get(CONF_MOBILE_TARGETS)
    tts = (
        user_input.get(CONF_TTS_ENABLED)
        and user_input.get(CONF_TTS_ENTITY)
        and user_input.get(CONF_TTS_PLAYER)
    )
    if not (mobile or tts or user_input.get(CONF_PERSISTENT_ENABLED)):
        errors["base"] = "no_method"
    if user_input.get(CONF_TTS_ENABLED) and not (
        user_input.get(CONF_TTS_ENTITY) and user_input.get(CONF_TTS_PLAYER)
    ):
        errors["base"] = "tts_incomplete"
    return errors


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
            errors = _validate_mailbox(user_input)
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return HousekeeperOptionsFlow()


class HousekeeperOptionsFlow(OptionsFlow):
    """Einstellungen einer Funktion nachträglich ändern."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            errors = _validate_mailbox(user_input)
            if not errors:
                return self.async_create_entry(data=user_input)
            defaults = user_input
        return self.async_show_form(
            step_id="init",
            data_schema=_mailbox_schema(self.hass, defaults, with_name=False),
            errors=errors,
        )
