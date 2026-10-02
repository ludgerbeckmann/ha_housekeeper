"""Dialoge der Funktion Home Assistant Updater."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    FUNCTION_UPDATER,
    function_title,
    CONF_SCHEDULES,
    CONF_TIMEOUT_MINUTES,
    DEFAULT_TIMEOUT_MINUTES,
    U_BACKUP,
    U_COMPONENTS,
    U_ENABLED,
    U_ID,
    U_MODE,
    U_NAME,
    U_TARGETS,
    U_TIME,
    U_TRIGGER,
    U_WEEKDAYS,
    U_WINDOW_END,
    U_WINDOW_START,
    TRIGGER_TIME,
    TRIGGERS,
    UPDATE_MODE_NOTIFY,
    UPDATE_MODES,
    WEEKDAYS,
)
from ..const import COMPONENTS
from ..updater import NOTIFY_KEYS, has_own_notify, schedule_summary
from .common import (
    SECTION_NOTIFICATIONS,
    _POOL_NOTIFY_DEFAULTS,
    _flatten_sections,
    _notify_fields,
    _number,
    _select,
    _suggest,
    _validate_notify,
)


def _updater_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    """Eintrag: Name (nur beim Anlegen) und Zeitlimit; Benachrichtigungen je Zeitplan."""
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, function_title(hass, FUNCTION_UPDATER)))] = str
    fields[
        vol.Required(
            CONF_TIMEOUT_MINUTES,
            default=defaults.get(CONF_TIMEOUT_MINUTES, DEFAULT_TIMEOUT_MINUTES),
        )
    ] = _number(1, 720, "min")
    return vol.Schema(fields)


class UpdaterOptions:
    """Options-Flow-Schritte: Home Assistant Updater."""

    def _schedules(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_SCHEDULES) or [])

    async def async_step_upd_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["upd_general", "add_schedule"]
        if self._schedules():
            options += ["edit_schedule", "delete_schedule"]
        options.append("rename")
        return await self._menu("upd_menu", options, user_input)

    async def async_step_upd_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # bewusst ohne _with_cleared: die Benachrichtigungseinstellungen des Eintrags
            # dienen älteren Zeitplänen weiter als Rückfall
            self._save(user_input)
            return await self.async_step_upd_menu()
        return self.async_show_form(
            step_id="upd_general",
            data_schema=_updater_schema(self.hass, self._current, with_name=False),
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

    def _schedule_notify_defaults(self, d: dict[str, Any]) -> dict[str, Any]:
        """Vorbelegung der Benachrichtigung: eigene Werte, sonst die des Eintrags, sonst Standard."""
        defaults: dict[str, Any] = dict(_POOL_NOTIFY_DEFAULTS)
        defaults.update({k: self._current[k] for k in NOTIFY_KEYS if self._current.get(k) is not None})
        if has_own_notify(d):
            defaults.update({k: d[k] for k in NOTIFY_KEYS if d.get(k) is not None})
        return defaults

    async def async_step_schedule_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_notify(flat, require_method=True)
            if flat.get(CONF_MOBILE_ENABLED) and not flat.get(CONF_MOBILE_TARGETS):
                errors["base"] = "no_targets"
            trigger = flat.get(U_TRIGGER, TRIGGER_TIME)
            if not errors:
                if not (flat.get(U_TARGETS) or flat.get(U_COMPONENTS)):
                    errors["base"] = "no_update_selected"
                elif trigger == TRIGGER_TIME and not flat.get(U_WEEKDAYS):
                    errors["base"] = "no_weekday"
                elif bool(flat.get(U_WINDOW_START)) != bool(flat.get(U_WINDOW_END)) or (
                    flat.get(U_WINDOW_START) and flat.get(U_WINDOW_START) == flat.get(U_WINDOW_END)
                ):
                    errors["base"] = "invalid_window"
            if not errors:
                schedule = {
                    U_ID: self._edit_id or uuid.uuid4().hex[:8],
                    U_NAME: flat[U_NAME],
                    U_ENABLED: flat.get(U_ENABLED, True),
                    U_TRIGGER: trigger,
                    U_TIME: flat.get(U_TIME) or "03:00:00",
                    U_WEEKDAYS: flat.get(U_WEEKDAYS) or [],
                    U_WINDOW_START: flat.get(U_WINDOW_START) or None,
                    U_WINDOW_END: flat.get(U_WINDOW_END) or None,
                    U_MODE: flat[U_MODE],
                    U_COMPONENTS: flat.get(U_COMPONENTS) or [],
                    U_TARGETS: flat.get(U_TARGETS) or [],
                    U_BACKUP: flat[U_BACKUP],
                    **{k: flat.get(k) for k in NOTIFY_KEYS},
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
            d = flat
        timing: dict[Any, Any] = {
            vol.Required(U_NAME, description=_suggest(U_NAME, d)): str,
            vol.Required(U_ENABLED, default=d.get(U_ENABLED, True)): bool,
            vol.Required(U_TRIGGER, default=d.get(U_TRIGGER, TRIGGER_TIME)): _select(
                TRIGGERS, "update_trigger", mode=selector.SelectSelectorMode.LIST
            ),
            vol.Required(
                U_TIME, default=d.get(U_TIME) or "03:00:00"
            ): selector.TimeSelector(),
            vol.Optional(U_WEEKDAYS, default=d.get(U_WEEKDAYS) or ["sun"]): _select(
                WEEKDAYS,
                "weekday",
                multiple=True,
                mode=selector.SelectSelectorMode.LIST,
            ),
            vol.Optional(
                U_WINDOW_START, description=_suggest(U_WINDOW_START, d) if d.get(U_WINDOW_START) else {}
            ): selector.TimeSelector(),
            vol.Optional(
                U_WINDOW_END, description=_suggest(U_WINDOW_END, d) if d.get(U_WINDOW_END) else {}
            ): selector.TimeSelector(),
        }
        actions: dict[Any, Any] = {
            vol.Required(U_MODE, default=d.get(U_MODE, UPDATE_MODE_NOTIFY)): _select(
                UPDATE_MODES, "update_mode", mode=selector.SelectSelectorMode.LIST
            ),
            vol.Optional(U_COMPONENTS, default=d.get(U_COMPONENTS, [])): _select(
                COMPONENTS,
                "update_component",
                multiple=True,
                mode=selector.SelectSelectorMode.LIST,
            ),
            vol.Optional(
                U_TARGETS, description=_suggest(U_TARGETS, d)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="update", multiple=True)
            ),
            vol.Required(U_BACKUP, default=d.get(U_BACKUP, False)): bool,
        }
        notifications = _notify_fields(
            self.hass, self._schedule_notify_defaults(d), with_action=False
        )
        return self.async_show_form(
            step_id="schedule_edit",
            data_schema=vol.Schema(
                {
                    vol.Required("timing"): section(vol.Schema(timing), {"collapsed": False}),
                    vol.Required("actions"): section(vol.Schema(actions), {"collapsed": False}),
                    vol.Required(SECTION_NOTIFICATIONS): section(
                        vol.Schema(notifications), {"collapsed": False}
                    ),
                }
            ),
            errors=errors,
        )
