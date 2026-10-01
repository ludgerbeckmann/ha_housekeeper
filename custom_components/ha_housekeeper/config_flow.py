"""Config-/Options-Flow: Funktionstyp wählen, dann typspezifisch konfigurieren."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ALARMS,
    CONF_COMMANDS,
    CONF_FUNCTION_TYPE,
    CONF_MAX_VOLUME,
    CONF_NAME,
    CONF_PLAYER,
    CONF_PROFILES,
    CONF_PUMP_ENTITY,
    CONF_RULES,
    CONF_SCHEDULES,
    CONF_STATUS,
    CONF_STOP_INSTEAD,
    CONF_TASKS,
    CONF_VOLUME_STEP,
    DEFAULT_MAX_VOLUME,
    DEFAULT_VOLUME_STEP,
    DOMAIN,
    FUNCTION_ALARM,
    FUNCTION_DOOR_GUARD,
    FUNCTION_DOORBELL,
    FUNCTION_KNX_SONOS,
    FUNCTION_MAILBOX,
    FUNCTION_PLATFORMS,
    FUNCTION_POOL,
    FUNCTION_TASK_PLANNER,
    FUNCTION_UPDATER,
)
from .flows.alarm import AlarmOptions, _alarm_settings_schema, _validate_alarm_settings
from .flows.common import OptionsBase, _flatten_sections, _validate_notify
from .flows.door_guard import DoorGuardOptions, _door_schema, _validate_door
from .flows.doorbell import DoorbellOptions, _bell_schema, _validate_bell
from .flows.knx import _SONOS_SELECTOR, KnxSonosOptions
from .flows.mailbox import MailboxOptions, _mailbox_schema
from .flows.planner import TaskPlannerOptions, _planner_schema, _validate_planner
from .flows.pool import _PUMP_SELECTOR, PoolOptions
from .flows.updater import UpdaterOptions, _updater_schema


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
            user_input = _flatten_sections(user_input)
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
            user_input = _flatten_sections(user_input)
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
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_FUNCTION_TYPE: FUNCTION_UPDATER,
                    CONF_SCHEDULES: [],
                    **user_input,
                },
            )
        return self.async_show_form(
            step_id="updater",
            data_schema=_updater_schema(self.hass, {}, with_name=True),
        )

    async def async_step_alarm_clock(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            errors = _validate_alarm_settings(user_input)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_FUNCTION_TYPE: FUNCTION_ALARM,
                        CONF_ALARMS: [],
                        **user_input,
                    },
                )
            defaults = user_input
        return self.async_show_form(
            step_id="alarm_clock",
            data_schema=_alarm_settings_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    async def async_step_task_planner(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            errors = _validate_planner(user_input)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_FUNCTION_TYPE: FUNCTION_TASK_PLANNER,
                        CONF_TASKS: [],
                        **user_input,
                    },
                )
            defaults = user_input
        return self.async_show_form(
            step_id="task_planner",
            data_schema=_planner_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return HousekeeperOptionsFlow()


# --- Options-Flow ---------------------------------------------------------------


class HousekeeperOptionsFlow(MailboxOptions, DoorGuardOptions, DoorbellOptions, PoolOptions, KnxSonosOptions, UpdaterOptions, TaskPlannerOptions, AlarmOptions, OptionsBase, OptionsFlow):
    """Einstellungen einer Funktion nachträglich ändern."""

    def __init__(self) -> None:
        self._draft: dict[str, Any] = {}
        self._edit_id: str | None = None

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
        if function_type == FUNCTION_TASK_PLANNER:
            return await self.async_step_tp_menu()
        if function_type == FUNCTION_ALARM:
            return await self.async_step_alarm_menu()
        return await self.async_step_mailbox_menu()
