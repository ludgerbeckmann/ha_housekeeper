"""Config-Flow (Hub anlegen) und Untereintrags-Flow (Instanzen anlegen und einstellen)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow

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
    CONF_HUB,
    function_title,
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



_MENU_STEPS = {
    FUNCTION_MAILBOX: "mailbox_menu",
    FUNCTION_DOOR_GUARD: "menu",
    FUNCTION_DOORBELL: "bell_menu",
    FUNCTION_POOL: "pool_menu",
    FUNCTION_KNX_SONOS: "knx_menu",
    FUNCTION_UPDATER: "upd_menu",
    FUNCTION_TASK_PLANNER: "tp_menu",
    FUNCTION_ALARM: "alarm_menu",
}


class NewInstanceSteps:
    """Formulare zum Anlegen einer Instanz (beim Hub-Anlegen und als weiterer Untereintrag).

    Die Schritte heißen `new_<typ>`, damit sie nicht mit den Einstellungsschritten der Typen
    (z. B. `mailbox`) zusammenfallen.
    """

    async def _finish_new(
        self, title: str, data: dict[str, Any], unique_id: str | None = None
    ) -> Any:
        raise NotImplementedError

    def _abort_if_pump_configured(self, unique_id: str) -> None:
        """Dieselbe Pumpe nicht zweimal einrichten (nur bei weiteren Untereinträgen relevant)."""

    async def async_step_new_mailbox(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_notify(flat, require_method=True)
            if not errors:
                return await self._finish_new(
                    flat[CONF_NAME],
                    {**flat},
                )
            defaults = flat
        return self.async_show_form(
            step_id="new_mailbox",
            data_schema=_mailbox_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    async def async_step_new_door_guard(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            errors = _validate_door(user_input)
            if not errors:
                return await self._finish_new(
                    user_input[CONF_NAME],
                    {
                        CONF_RULES: [],
                        **user_input,
                    },
                )
            defaults = user_input
        return self.async_show_form(
            step_id="new_door_guard",
            data_schema=_door_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    async def async_step_new_doorbell(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            errors = _validate_bell(user_input)
            if not errors:
                return await self._finish_new(
                    user_input[CONF_NAME],
                    {
                        CONF_PROFILES: [],
                        **user_input,
                    },
                )
            defaults = user_input
        return self.async_show_form(
            step_id="new_doorbell",
            data_schema=_bell_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    async def async_step_new_pool_pump(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            unique_id = f"{FUNCTION_POOL}:{user_input[CONF_PUMP_ENTITY]}"
            self._abort_if_pump_configured(unique_id)
            return await self._finish_new(
                user_input[CONF_NAME],
                {CONF_PUMP_ENTITY: user_input[CONF_PUMP_ENTITY]},
                unique_id,
            )
        return self.async_show_form(
            step_id="new_pool_pump",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=function_title(self.hass, FUNCTION_POOL)): str,
                    vol.Required(CONF_PUMP_ENTITY): _PUMP_SELECTOR,
                }
            ),
        )

    async def async_step_new_knx_sonos(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self.hass.services.has_service("knx", "event_register"):
            return self.async_abort(reason="knx_missing")
        if user_input is not None:
            return await self._finish_new(
                    user_input[CONF_NAME],
                    {
                    CONF_PLAYER: user_input[CONF_PLAYER],
                    CONF_MAX_VOLUME: DEFAULT_MAX_VOLUME,
                    CONF_VOLUME_STEP: DEFAULT_VOLUME_STEP,
                    CONF_STOP_INSTEAD: False,
                    CONF_COMMANDS: [],
                    CONF_STATUS: [],
                },
                )
        return self.async_show_form(
            step_id="new_knx_sonos",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=function_title(self.hass, FUNCTION_KNX_SONOS)): str,
                    vol.Required(CONF_PLAYER): _SONOS_SELECTOR,
                }
            ),
        )

    async def async_step_new_updater(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._finish_new(
                    user_input[CONF_NAME],
                    {
                    CONF_SCHEDULES: [],
                    **user_input,
                },
                )
        return self.async_show_form(
            step_id="new_updater",
            data_schema=_updater_schema(self.hass, {}, with_name=True),
        )

    async def async_step_new_alarm_clock(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            errors = _validate_alarm_settings(user_input)
            if not errors:
                return await self._finish_new(
                    user_input[CONF_NAME],
                    {
                        CONF_ALARMS: [],
                        **user_input,
                    },
                )
            defaults = user_input
        return self.async_show_form(
            step_id="new_alarm_clock",
            data_schema=_alarm_settings_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    async def async_step_new_task_planner(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            errors = _validate_planner(user_input)
            if not errors:
                return await self._finish_new(
                    user_input[CONF_NAME],
                    {
                        CONF_TASKS: [],
                        **user_input,
                    },
                )
            defaults = user_input
        return self.async_show_form(
            step_id="new_task_planner",
            data_schema=_planner_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )


# --- Config-Flow ---------------------------------------------------------------


class HousekeeperConfigFlow(NewInstanceSteps, ConfigFlow, domain=DOMAIN):
    """Hub einer Funktion anlegen (mit der ersten Instanz)."""

    VERSION = 1
    _function_type: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Funktion wählen: natives Menü, ein Klick öffnet das Anlege-Formular."""
        return self.async_show_menu(
            step_id="user", menu_options=[f"hub_{t}" for t in FUNCTION_PLATFORMS]
        )

    async def _start_hub(self, function_type: str) -> ConfigFlowResult:
        """Je Funktionstyp gibt es einen Hub; weitere Instanzen kommen über dessen Schaltfläche."""
        self._function_type = function_type
        await self.async_set_unique_id(f"{CONF_HUB}:{function_type}")
        self._abort_if_unique_id_configured()
        return await getattr(self, f"async_step_new_{function_type}")()

    async def _finish_new(
        self, title: str, data: dict[str, Any], unique_id: str | None = None
    ) -> ConfigFlowResult:
        function_type = self._function_type
        return self.async_create_entry(
            title=function_title(self.hass, function_type),
            data={CONF_FUNCTION_TYPE: function_type, CONF_HUB: True},
            subentries=[
                {
                    "subentry_type": function_type,
                    "title": title,
                    "data": data,
                    "unique_id": unique_id,
                }
            ],
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Weitere Instanzen werden als Untereintrag des Hubs angelegt."""
        function_type = config_entry.data.get(CONF_FUNCTION_TYPE)
        if not config_entry.data.get(CONF_HUB) or function_type not in FUNCTION_PLATFORMS:
            return {}
        return {function_type: HousekeeperSubentryFlow}


def _hub_step(function_type: str):
    async def step(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._start_hub(function_type)

    step.__name__ = f"async_step_hub_{function_type}"
    return step


for _function_type in FUNCTION_PLATFORMS:
    setattr(HousekeeperConfigFlow, f"async_step_hub_{_function_type}", _hub_step(_function_type))


# --- Untereintrags-Flow ---------------------------------------------------------


class HousekeeperSubentryFlow(
    MailboxOptions,
    DoorGuardOptions,
    DoorbellOptions,
    PoolOptions,
    KnxSonosOptions,
    UpdaterOptions,
    TaskPlannerOptions,
    AlarmOptions,
    NewInstanceSteps,
    OptionsBase,
    ConfigSubentryFlow,
):
    """Instanz hinzufügen und ihre Einstellungen ändern (Konfigurieren-Menü)."""

    def __init__(self) -> None:
        self._draft: dict[str, Any] = {}
        self._edit_id: str | None = None

    @property
    def function_type(self) -> str:
        return self.handler[1]

    @property
    def config_entry(self) -> ConfigEntry:
        return self._get_entry()

    @property
    def _current(self) -> dict[str, Any]:
        return dict(self._get_reconfigure_subentry().data)

    def _save(self, options: dict[str, Any]) -> None:
        subentry = self._get_reconfigure_subentry()
        self.hass.config_entries.async_update_subentry(
            self._get_entry(), subentry, data={**subentry.data, **options}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await getattr(self, f"async_step_new_{self.function_type}")()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await getattr(self, f"async_step_{_MENU_STEPS[self.function_type]}")()

    async def _finish_new(
        self, title: str, data: dict[str, Any], unique_id: str | None = None
    ) -> SubentryFlowResult:
        return self.async_create_entry(title=title, data=data, unique_id=unique_id)

    def _abort_if_pump_configured(self, unique_id: str) -> None:
        if any(s.unique_id == unique_id for s in self._get_entry().subentries.values()):
            raise AbortFlow("pump_configured")

