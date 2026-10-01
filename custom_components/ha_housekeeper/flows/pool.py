"""Dialoge der Funktion Poolsteuerung."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from ..const import (
    CONF_DRY_AUTO_OFF,
    CONF_DRY_DURATION,
    CONF_DRY_MAX_POWER,
    CONF_DRY_MIN_POWER,
    CONF_HEATER_ENTITY,
    CONF_HEATER_OFF_BELOW,
    CONF_HEATER_ON_ABOVE,
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_POWER_ENTITY,
    CONF_PUMP_ENTITY,
    CONF_TEMP_ENTITY,
    CONF_WINDOWS,
    DEFAULT_DRY_DURATION,
    DEFAULT_DRY_MAX_POWER,
    DEFAULT_DRY_MIN_POWER,
    DEFAULT_HEATER_OFF_BELOW,
    DEFAULT_HEATER_ON_ABOVE,
    MAX_WINDOWS,
    W_DAYS,
    W_END,
    W_ID,
    W_START,
    WEEKDAYS,
)
from ..pool_schedule import describe_window, parse_time, parse_windows
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


_PUMP_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
)


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
    return _sections_schema(
        fields,
        _notify_fields(hass, {**_POOL_NOTIFY_DEFAULTS, **defaults}, with_action=False),
    )


def _validate_dry_run(user_input: dict[str, Any]) -> dict[str, str]:
    errors = _validate_notify(user_input, require_method=False)
    if user_input.get(CONF_MOBILE_ENABLED) and not user_input.get(CONF_MOBILE_TARGETS):
        errors["base"] = "no_targets"
    if user_input.get(CONF_POWER_ENTITY) and float(
        user_input[CONF_DRY_MIN_POWER]
    ) >= float(user_input[CONF_DRY_MAX_POWER]):
        errors["base"] = "min_ge_max"
    return errors


def _heater_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_HEATER_ENTITY, description=_suggest(CONF_HEATER_ENTITY, defaults)
            ): _PUMP_SELECTOR,
            vol.Optional(
                CONF_TEMP_ENTITY, description=_suggest(CONF_TEMP_ENTITY, defaults)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
            vol.Required(
                CONF_HEATER_ON_ABOVE,
                default=defaults.get(CONF_HEATER_ON_ABOVE, DEFAULT_HEATER_ON_ABOVE),
            ): _number(-50, 150, "°C", 0.5),
            vol.Required(
                CONF_HEATER_OFF_BELOW,
                default=defaults.get(CONF_HEATER_OFF_BELOW, DEFAULT_HEATER_OFF_BELOW),
            ): _number(-50, 150, "°C", 0.5),
        }
    )


def _validate_heater(user_input: dict[str, Any]) -> dict[str, str]:
    if not user_input.get(CONF_HEATER_ENTITY):
        return {}
    if not user_input.get(CONF_TEMP_ENTITY):
        return {"base": "no_temperature"}
    if float(user_input[CONF_HEATER_OFF_BELOW]) >= float(user_input[CONF_HEATER_ON_ABOVE]):
        return {"base": "off_ge_on"}
    return {}


class PoolOptions:
    """Options-Flow-Schritte: Poolsteuerung."""

    def _windows(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_WINDOWS) or [])

    async def async_step_pool_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["pool_general", "add_window"]
        if self._windows():
            options += ["edit_window", "delete_window"]
        options += ["dry_run", "heater"]
        return await self._menu("pool_menu", options, user_input)

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

    async def async_step_heater(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            errors = _validate_heater(user_input)
            if not errors:
                # nur die Heizungsfelder leeren (nicht Trockenlauf-/Benachrichtigungsfelder)
                self._save({CONF_HEATER_ENTITY: None, CONF_TEMP_ENTITY: None, **user_input})
                return await self.async_step_pool_menu()
            defaults = user_input
        return self.async_show_form(
            step_id="heater", data_schema=_heater_schema(defaults), errors=errors
        )

    async def async_step_dry_run(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            user_input = _flatten_sections(user_input)
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
