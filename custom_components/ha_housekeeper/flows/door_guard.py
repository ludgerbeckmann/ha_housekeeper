"""Dialoge der Funktion Türwächter."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from ..const import (
    BLOCK_NOTIFY,
    BLOCK_RETRY,
    CONF_BLOCK_ACTION,
    CONF_CONTACT,
    CONF_LOCK,
    CONF_MANUAL_OVERRIDE,
    CONF_MANUAL_PAUSE_MINUTES,
    CONF_NAME,
    CONF_OPEN_ALERT_MINUTES,
    CONF_OPEN_ALERT_REPEAT,
    CONF_RETRY_MINUTES,
    CONF_RULES,
    CONF_VERIFY_SECONDS,
    DEFAULT_MANUAL_PAUSE_MINUTES,
    DEFAULT_OPEN_ALERT_MINUTES,
    DEFAULT_OPEN_ALERT_REPEAT,
    DEFAULT_RETRY_MINUTES,
    DEFAULT_VERIFY_SECONDS,
    MANUAL_IGNORE,
    MANUAL_PAUSE,
    R_ACTION,
    R_DELAY,
    R_ENABLED,
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
    WEEKDAYS,
)
from ..door_guard import rule_summary
from .common import (
    _flatten_sections,
    _notify_fields,
    _number,
    _sections_schema,
    _select,
    _suggest,
    _validate_notify,
    _with_cleared,
)


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
    return _sections_schema(fields, _notify_fields(hass, defaults, with_action=False))


def _validate_door(user_input: dict[str, Any]) -> dict[str, str]:
    errors = _validate_notify(user_input, require_method=False)
    if float(user_input.get(CONF_OPEN_ALERT_MINUTES) or 0) > 0 and not user_input.get(
        CONF_CONTACT
    ):
        errors["base"] = "alert_needs_contact"
    return errors


class DoorGuardOptions:
    """Options-Flow-Schritte: Türwächter."""

    def _rules(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_RULES) or [])

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["general", "add_rule"]
        if self._rules():
            options += ["edit_rule", "delete_rule"]
        return await self._menu("menu", options, user_input)

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            user_input = _flatten_sections(user_input)
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
                    vol.Required(R_ENABLED, default=draft.get(R_ENABLED, True)): bool,
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
            R_ENABLED: self._draft.get(R_ENABLED, True),
            **{k: self._draft[k] for k in TRIGGER_KEYS[trigger] if k in self._draft},
        }
        rules = self._rules()
        if self._edit_id:
            rules = [rule if r[R_ID] == self._edit_id else r for r in rules]
        else:
            rules.append(rule)
        self._save({CONF_RULES: rules})
        return await self.async_step_menu()
