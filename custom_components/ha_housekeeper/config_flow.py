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
    CONF_FUNCTION_TYPE,
    CONF_NAME,
    CONF_PROFILES,
    CONF_PUMP_ENTITY,
    CONF_SCHEDULES,
    CONF_TASKS,
    DOMAIN,
    FUNCTION_ALARM,
    FUNCTION_CONSUMPTION,
    FUNCTION_DOOR_GUARD,
    FUNCTION_DOORBELL,
    FUNCTION_ENERGY,
    FUNCTION_IR,
    FUNCTION_KNX_SONOS,
    FUNCTION_LLM,
    FUNCTION_MAILBOX,
    FUNCTION_MONITOR,
    FUNCTION_PLATFORMS,
    FUNCTION_POOL,
    FUNCTION_TASK_PLANNER,
    FUNCTION_UPDATER,
    CONF_HUB,
    clean_instance_name,
    hub_title,
    instance_name,
    instance_title,
)
from .flows.alarm import AlarmOptions, _alarm_settings_schema, _validate_alarm_settings
from .flows.common import OptionsBase, _flatten_sections, _validate_notify
from .flows.door_guard import (
    DoorGuardOptions,
    _dg_schema,
    _validate_dg,
    new_instance_data as new_dg_data,
)
from .flows.consumption import (
    ConsumptionGuardOptions,
    _cg_schema,
    _validate_cg,
    new_instance_data as new_cg_data,
)
from .flows.doorbell import DoorbellOptions, _bell_schema, _validate_bell
from .flows.ir import IrOptions, _ir_schema, _validate_ir, new_instance_data as new_ir_data
from .flows.energy import (
    EnergyMonitorOptions,
    _em_schema,
    _validate_em,
    em_data,
)
from .flows.knx import KnxSonosOptions, _knx_schema, _validate_knx, new_instance_data as new_knx_data
from .flows.llm import LlmOptions, _llm_new_schema, async_validate_new, new_instance_data
from .knx_project import async_project_addresses
from .flows.mailbox import MailboxOptions, _mailbox_schema
from .flows.monitor import MonitorOptions, _monitor_schema, _validate_monitor, monitor_data
from .flows.planner import TaskPlannerOptions, _planner_schema, _validate_planner
from .flows.pool import _PUMP_SELECTOR, PoolOptions
from .flows.updater import UpdaterOptions, _updater_schema


# --- Config-Flow ---------------------------------------------------------------



_MENU_STEPS = {
    FUNCTION_MAILBOX: "mailbox_settings",
    FUNCTION_DOOR_GUARD: "door_settings",
    FUNCTION_DOORBELL: "bell_menu",
    FUNCTION_POOL: "pool_menu",
    FUNCTION_KNX_SONOS: "knx_settings",
    FUNCTION_UPDATER: "upd_menu",
    FUNCTION_TASK_PLANNER: "tp_menu",
    FUNCTION_ALARM: "alarm_menu",
    FUNCTION_MONITOR: "mon_settings",
    FUNCTION_LLM: "llm_menu",
    FUNCTION_IR: "ir_menu",
    FUNCTION_CONSUMPTION: "cg_settings",
    FUNCTION_ENERGY: "em_settings",
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
                    flat.get(CONF_NAME),
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
            errors = _validate_dg(user_input)
            if not errors:
                return await self._finish_new(user_input.get(CONF_NAME), new_dg_data(user_input))
            defaults = user_input
        return self.async_show_form(
            step_id="new_door_guard",
            data_schema=_dg_schema(self.hass, defaults, with_name=True),
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
                    user_input.get(CONF_NAME),
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
                user_input.get(CONF_NAME),
                {CONF_PUMP_ENTITY: user_input[CONF_PUMP_ENTITY]},
                unique_id,
            )
        return self.async_show_form(
            step_id="new_pool_pump",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME): str,
                    vol.Required(CONF_PUMP_ENTITY): _PUMP_SELECTOR,
                }
            ),
        )

    async def async_step_new_knx_sonos(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self.hass.services.has_service("knx", "event_register"):
            return self.async_abort(reason="knx_missing")
        errors: dict[str, str] = {}
        detail = ""
        defaults: dict[str, Any] = {}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors, detail = _validate_knx(self.hass.config.language or "", flat)
            if not errors:
                return await self._finish_new(flat.get(CONF_NAME), new_knx_data(flat))
            defaults = flat
        return self.async_show_form(
            step_id="new_knx_sonos",
            data_schema=_knx_schema(
                defaults, [], with_legacy=False, project=await async_project_addresses(self.hass)
            ),
            errors=errors,
            description_placeholders={"detail": detail, "legacy": ""},
        )

    async def async_step_new_updater(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._finish_new(
                    user_input.get(CONF_NAME),
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
                    user_input.get(CONF_NAME),
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

    async def async_step_new_integration_monitor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_monitor(flat)
            if not errors:
                return await self._finish_new(
                    flat.get(CONF_NAME),
                    {key: value for key, value in monitor_data(flat).items() if value is not None},
                )
            defaults = flat
        return self.async_show_form(
            step_id="new_integration_monitor",
            data_schema=_monitor_schema(self.hass, defaults, new=True),
            errors=errors,
        )

    async def async_step_new_llm_usage(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        detail = ""
        defaults: dict[str, Any] = {}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors, detail = await async_validate_new(self.hass, flat)
            if not errors:
                return await self._finish_new(flat.get(CONF_NAME), new_instance_data(flat))
            defaults = flat
        return self.async_show_form(
            step_id="new_llm_usage",
            data_schema=_llm_new_schema(self.hass, defaults),
            errors=errors,
            description_placeholders={"detail": detail},
        )

    async def async_step_new_ir_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_ir(flat, with_device=True)
            if not errors:
                return await self._finish_new(flat.get(CONF_NAME), new_ir_data(flat))
            defaults = flat
        return self.async_show_form(
            step_id="new_ir_remote",
            data_schema=_ir_schema(self.hass, defaults, with_name=True),
            errors=errors,
        )

    async def async_step_new_consumption_guard(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_cg(flat)
            if not errors:
                return await self._finish_new(flat.get(CONF_NAME), new_cg_data(flat))
            defaults = flat
        return self.async_show_form(
            step_id="new_consumption_guard",
            data_schema=_cg_schema(self.hass, defaults),
            errors=errors,
        )

    async def async_step_new_energy_monitor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_em(flat)
            if not errors:
                return await self._finish_new(flat.get(CONF_NAME), em_data(flat))
            defaults = flat
        return self.async_show_form(
            step_id="new_energy_monitor",
            data_schema=_em_schema(self.hass.config.language or "", defaults),
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
                    user_input.get(CONF_NAME),
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


class HousekeeperConfigFlow(ConfigFlow, domain=DOMAIN):
    """Den einen Hub „Funktionen“ anlegen; die Instanzen kommen als Untereinträge dazu."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(CONF_HUB)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=hub_title(self.hass), data={CONF_HUB: True})

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Jede Funktion ist ein Untereintragstyp des Hubs."""
        if not config_entry.data.get(CONF_HUB) or CONF_FUNCTION_TYPE in config_entry.data:
            return {}
        return {function_type: HousekeeperSubentryFlow for function_type in FUNCTION_PLATFORMS}


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
    MonitorOptions,
    LlmOptions,
    IrOptions,
    ConsumptionGuardOptions,
    EnergyMonitorOptions,
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
        return self.async_create_entry(
            title=instance_title(
                self.hass, self.function_type, clean_instance_name(self.function_type, title)
            ),
            data=data,
            unique_id=unique_id,
        )

    def _abort_if_pump_configured(self, unique_id: str) -> None:
        if any(s.unique_id == unique_id for s in self._get_entry().subentries.values()):
            raise AbortFlow("pump_configured")

    async def async_step_rename(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Instanz umbenennen: Eingabe nur des Namens, der Titel erhält den Präfix „Funktion: “."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None and user_input[CONF_NAME].strip():
            self.hass.config_entries.async_update_subentry(
                self._get_entry(),
                subentry,
                title=instance_title(
                    self.hass,
                    self.function_type,
                    clean_instance_name(self.function_type, user_input[CONF_NAME]),
                ),
            )
            return await getattr(self, f"async_step_{_MENU_STEPS[self.function_type]}")()
        return self.async_show_form(
            step_id="rename",
            data_schema=vol.Schema(
                {vol.Required(CONF_NAME, default=instance_name(subentry.title)): str}
            ),
        )
