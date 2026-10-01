"""Dialoge der Funktion Aufgabenplaner."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    WEEKDAYS,
)
from ..const import (
    CONF_TASKS,
    MONTH_FIRST,
    MONTH_MODES,
    TASK_ACTIONS,
    TASK_ENABLED,
    TASK_ID,
    TASK_NAME,
    TASK_NOTIFY_ERROR,
    TASK_NOTIFY_START,
    TASK_NOTIFY_SUCCESS,
    TASK_TRIGGERS,
    TR_ABOVE,
    TR_AT,
    TR_BELOW,
    TR_ENTITY,
    TR_FOR,
    TR_MINUTES,
    TR_MONTH_DAY,
    TR_MONTH_MODE,
    TR_TIME,
    TR_TO_STATE,
    TR_TYPE,
    TR_WEEKDAYS,
    TRIG_INTERVAL,
    TRIG_MONTHLY,
    TRIG_ONCE,
    TRIG_STATE,
    TRIG_THRESHOLD,
    TRIG_WEEKLY,
    TRIGGER_TYPES,
)
from ..task_planner import task_summary, trigger_summary
from .common import (
    _POOL_NOTIFY_DEFAULTS,
    _flatten_sections,
    _notify_fields,
    _number,
    _sections_schema,
    _select,
    _suggest,
    _validate_notify,
    _with_cleared,
)


def _planner_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Aufgabenplaner"))
        ] = str
    return _sections_schema(
        fields,
        _notify_fields(hass, {**_POOL_NOTIFY_DEFAULTS, **defaults}, with_action=False),
    )


def _validate_planner(user_input: dict[str, Any]) -> dict[str, str]:
    errors = _validate_notify(user_input, require_method=False)
    if user_input.get(CONF_MOBILE_ENABLED) and not user_input.get(CONF_MOBILE_TARGETS):
        errors["base"] = "no_targets"
    return errors


class TaskPlannerOptions:
    """Options-Flow-Schritte: Aufgabenplaner."""

    def _tasks(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_TASKS) or [])

    async def async_step_tp_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["tp_general", "add_task"]
        if self._tasks():
            options += ["edit_task", "delete_task"]
        options.append("done")
        return await self._menu("tp_menu", options, user_input)

    async def async_step_tp_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            errors = _validate_planner(user_input)
            if not errors:
                self._save(_with_cleared(user_input))
                return await self.async_step_tp_menu()
            defaults = user_input
        return self.async_show_form(
            step_id="tp_general",
            data_schema=_planner_schema(self.hass, defaults, with_name=False),
            errors=errors,
        )

    def _task_picker_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("task"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=t[TASK_ID], label=task_summary(self.hass, t)
                            )
                            for t in self._tasks()
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    async def async_step_add_task(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {TASK_TRIGGERS: []}
        return await self.async_step_task_edit()

    async def async_step_edit_task(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            task = next(t for t in self._tasks() if t[TASK_ID] == user_input["task"])
            self._edit_id = task[TASK_ID]
            self._draft = {**task, TASK_TRIGGERS: list(task.get(TASK_TRIGGERS) or [])}
            return await self.async_step_task_edit()
        return self.async_show_form(
            step_id="edit_task", data_schema=self._task_picker_schema()
        )

    async def async_step_delete_task(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {CONF_TASKS: [t for t in self._tasks() if t[TASK_ID] != user_input["task"]]}
            )
            return await self.async_step_tp_menu()
        return self.async_show_form(
            step_id="delete_task", data_schema=self._task_picker_schema()
        )

    async def async_step_task_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            if not user_input.get(TASK_ACTIONS):
                errors["base"] = "no_actions"
            else:
                self._draft = {**d, **user_input}
                return await self.async_step_task_triggers()
            d = user_input
        return self.async_show_form(
            step_id="task_edit",
            data_schema=vol.Schema(
                {
                    vol.Required(TASK_NAME, description=_suggest(TASK_NAME, d)): str,
                    vol.Required(TASK_ENABLED, default=d.get(TASK_ENABLED, True)): bool,
                    vol.Required(
                        TASK_ACTIONS, description=_suggest(TASK_ACTIONS, d)
                    ): selector.ActionSelector(),
                    vol.Required(
                        TASK_NOTIFY_START, default=d.get(TASK_NOTIFY_START, False)
                    ): bool,
                    vol.Required(
                        TASK_NOTIFY_SUCCESS, default=d.get(TASK_NOTIFY_SUCCESS, False)
                    ): bool,
                    vol.Required(
                        TASK_NOTIFY_ERROR, default=d.get(TASK_NOTIFY_ERROR, True)
                    ): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_task_triggers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        triggers = self._draft.get(TASK_TRIGGERS) or []
        options = ["add_trigger"]
        if triggers:
            options.append("delete_trigger")
        options.append("task_save")
        listing = "\n".join(f"• {trigger_summary(self.hass, t)}" for t in triggers)
        return await self._menu(
            "task_triggers",
            options,
            user_input,
            {
                "task": str(self._draft.get(TASK_NAME, "")),
                "triggers": listing or "–",
            },
        )

    async def async_step_task_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        d = self._draft
        task = {
            TASK_ID: self._edit_id or uuid.uuid4().hex[:8],
            TASK_NAME: d[TASK_NAME],
            TASK_ENABLED: d[TASK_ENABLED],
            TASK_TRIGGERS: list(d.get(TASK_TRIGGERS) or []),
            TASK_ACTIONS: d[TASK_ACTIONS],
            TASK_NOTIFY_START: d[TASK_NOTIFY_START],
            TASK_NOTIFY_SUCCESS: d[TASK_NOTIFY_SUCCESS],
            TASK_NOTIFY_ERROR: d[TASK_NOTIFY_ERROR],
        }
        tasks = self._tasks()
        if self._edit_id:
            tasks = [task if t[TASK_ID] == self._edit_id else t for t in tasks]
        else:
            tasks.append(task)
        self._save({CONF_TASKS: tasks})
        return await self.async_step_tp_menu()

    async def async_step_add_trigger(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await getattr(self, f"async_step_trigger_{user_input[TR_TYPE]}")()
        return self.async_show_form(
            step_id="add_trigger",
            data_schema=vol.Schema(
                {
                    vol.Required(TR_TYPE, default=TRIG_WEEKLY): _select(
                        TRIGGER_TYPES, "trigger_type", mode=selector.SelectSelectorMode.LIST
                    )
                }
            ),
        )

    async def async_step_delete_trigger(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        triggers = list(self._draft.get(TASK_TRIGGERS) or [])
        if user_input is not None:
            del triggers[int(user_input["trigger"])]
            self._draft = {**self._draft, TASK_TRIGGERS: triggers}
            return await self.async_step_task_triggers()
        return self.async_show_form(
            step_id="delete_trigger",
            data_schema=vol.Schema(
                {
                    vol.Required("trigger"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=str(i), label=trigger_summary(self.hass, t)
                                )
                                for i, t in enumerate(triggers)
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def _async_add_trigger(
        self,
        step_id: str,
        kind: str,
        fields: dict[Any, Any],
        user_input: dict[str, Any] | None,
        validate=None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if validate is not None:
                errors = validate(user_input)
            if not errors:
                trigger = {
                    TR_TYPE: kind,
                    **{k: v for k, v in user_input.items() if v not in (None, "")},
                }
                self._draft = {
                    **self._draft,
                    TASK_TRIGGERS: [*(self._draft.get(TASK_TRIGGERS) or []), trigger],
                }
                return await self.async_step_task_triggers()
        return self.async_show_form(
            step_id=step_id, data_schema=vol.Schema(fields), errors=errors
        )

    async def async_step_trigger_weekly(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        def validate(data: dict[str, Any]) -> dict[str, str]:
            return {} if data.get(TR_WEEKDAYS) else {"base": "no_weekday"}

        return await self._async_add_trigger(
            "trigger_weekly",
            TRIG_WEEKLY,
            {
                vol.Required(TR_TIME, default="08:00:00"): selector.TimeSelector(),
                vol.Required(TR_WEEKDAYS, default=list(WEEKDAYS)): _select(
                    WEEKDAYS, "weekday", multiple=True, mode=selector.SelectSelectorMode.LIST
                ),
            },
            user_input,
            validate,
        )

    async def async_step_trigger_monthly(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_add_trigger(
            "trigger_monthly",
            TRIG_MONTHLY,
            {
                vol.Required(TR_MONTH_MODE, default=MONTH_FIRST): _select(
                    MONTH_MODES, "month_mode", mode=selector.SelectSelectorMode.LIST
                ),
                vol.Optional(TR_MONTH_DAY, default=1): _number(1, 31),
                vol.Required(TR_TIME, default="08:00:00"): selector.TimeSelector(),
            },
            user_input,
        )

    async def async_step_trigger_once(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        def validate(data: dict[str, Any]) -> dict[str, str]:
            at = dt_util.parse_datetime(str(data.get(TR_AT, "")))
            if at is None:
                return {"base": "invalid_datetime"}
            if at.tzinfo is None:
                at = at.replace(tzinfo=dt_util.get_default_time_zone())
            return {"base": "in_past"} if at <= dt_util.now() else {}

        return await self._async_add_trigger(
            "trigger_once",
            TRIG_ONCE,
            {vol.Required(TR_AT): selector.DateTimeSelector()},
            user_input,
            validate,
        )

    async def async_step_trigger_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_add_trigger(
            "trigger_interval",
            TRIG_INTERVAL,
            {vol.Required(TR_MINUTES, default=60): _number(1, 10080, "min")},
            user_input,
        )

    async def async_step_trigger_state(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        def validate(data: dict[str, Any]) -> dict[str, str]:
            if float(data.get(TR_FOR) or 0) > 0 and not data.get(TR_TO_STATE):
                return {"base": "for_needs_state"}
            return {}

        return await self._async_add_trigger(
            "trigger_state",
            TRIG_STATE,
            {
                vol.Required(TR_ENTITY): selector.EntitySelector(),
                vol.Optional(TR_TO_STATE): str,
                vol.Required(TR_FOR, default=0): _number(0, 1440, "min"),
            },
            user_input,
            validate,
        )

    async def async_step_trigger_threshold(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        def validate(data: dict[str, Any]) -> dict[str, str]:
            above, below = data.get(TR_ABOVE), data.get(TR_BELOW)
            if above is None and below is None:
                return {"base": "no_threshold"}
            if above is not None and below is not None and float(above) >= float(below):
                return {"base": "min_ge_max"}
            return {}

        return await self._async_add_trigger(
            "trigger_threshold",
            TRIG_THRESHOLD,
            {
                vol.Required(TR_ENTITY): selector.EntitySelector(),
                vol.Optional(TR_ABOVE): _number(-1000000, 1000000, step="any"),
                vol.Optional(TR_BELOW): _number(-1000000, 1000000, step="any"),
                vol.Required(TR_FOR, default=0): _number(0, 1440, "min"),
            },
            user_input,
            validate,
        )
