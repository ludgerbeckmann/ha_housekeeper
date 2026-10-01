"""Dialoge der Funktion Wecker."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from ..alarm_clock import alarm_summary
from ..const import (
    A_AUTO_STOP,
    A_ENABLED,
    A_ID,
    A_MEDIA,
    A_NAME,
    A_NOT_IF_ON,
    A_ONLY_IF_ON,
    A_PLAYERS,
    A_SNOOZE,
    A_TIME,
    A_VOLUME,
    A_WEEKDAYS,
    CONF_ALARMS,
    CONF_CRITICAL,
    CONF_WORKDAY_SENSORS,
    DEFAULT_ALARM_AUTO_STOP,
    DEFAULT_ALARM_MESSAGE,
    DEFAULT_ALARM_SNOOZE,
    DEFAULT_ALARM_VOLUME,
)
from ..const import (
    CONF_MESSAGE,
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    WEEKDAYS,
)
from .common import (
    _flatten_sections,
    _mobile_selector,
    _mobile_suggest,
    _number,
    _sections_schema,
    _select,
    _suggest,
    _with_cleared,
)


def _alarm_settings_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    """Eintrag: Name (nur beim Anlegen), Werktagssensoren und die Push-Meldung."""
    general: dict[Any, Any] = {}
    if with_name:
        general[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Wecker"))] = str
    general[
        vol.Optional(
            CONF_WORKDAY_SENSORS, description=_suggest(CONF_WORKDAY_SENSORS, defaults)
        )
    ] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
    )
    notifications: dict[Any, Any] = {
        vol.Required(
            CONF_MOBILE_ENABLED, default=defaults.get(CONF_MOBILE_ENABLED, True)
        ): bool,
        vol.Optional(
            CONF_MOBILE_TARGETS, description=_mobile_suggest(hass, defaults)
        ): _mobile_selector(),
        vol.Required(
            CONF_CRITICAL, default=defaults.get(CONF_CRITICAL, True)
        ): bool,
        vol.Required(
            CONF_MESSAGE, default=defaults.get(CONF_MESSAGE, DEFAULT_ALARM_MESSAGE)
        ): str,
    }
    return _sections_schema(general, notifications)


def _validate_alarm_settings(user_input: dict[str, Any]) -> dict[str, str]:
    if user_input.get(CONF_MOBILE_ENABLED) and not user_input.get(CONF_MOBILE_TARGETS):
        return {"base": "no_targets"}
    return {}


class AlarmOptions:
    """Options-Flow-Schritte: Wecker."""

    def _alarms(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_ALARMS) or [])

    async def async_step_alarm_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["alarm_general", "add_alarm"]
        if self._alarms():
            options += ["edit_alarm", "delete_alarm"]
        options.append("done")
        return await self._menu("alarm_menu", options, user_input)

    async def async_step_alarm_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            errors = _validate_alarm_settings(user_input)
            if not errors:
                self._save(_with_cleared(user_input))
                return await self.async_step_alarm_menu()
            defaults = user_input
        return self.async_show_form(
            step_id="alarm_general",
            data_schema=_alarm_settings_schema(self.hass, defaults, with_name=False),
            errors=errors,
        )

    def _alarm_picker_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("alarm"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=a[A_ID], label=alarm_summary(self.hass, a)
                            )
                            for a in self._alarms()
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    async def async_step_add_alarm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_alarm_edit()

    async def async_step_edit_alarm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            alarm = next(a for a in self._alarms() if a[A_ID] == user_input["alarm"])
            self._edit_id = alarm[A_ID]
            self._draft = dict(alarm)
            return await self.async_step_alarm_edit()
        return self.async_show_form(
            step_id="edit_alarm", data_schema=self._alarm_picker_schema()
        )

    async def async_step_delete_alarm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {CONF_ALARMS: [a for a in self._alarms() if a[A_ID] != user_input["alarm"]]}
            )
            return await self.async_step_alarm_menu()
        return self.async_show_form(
            step_id="delete_alarm", data_schema=self._alarm_picker_schema()
        )

    async def async_step_alarm_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            media = user_input.get(A_MEDIA) or {}
            if not user_input.get(A_PLAYERS):
                errors["base"] = "no_players"
            elif not media.get("media_content_id"):
                errors["base"] = "no_media"
            elif not user_input.get(A_WEEKDAYS):
                errors["base"] = "no_weekday"
            else:
                alarm = {
                    A_ID: self._edit_id or uuid.uuid4().hex[:8],
                    **{
                        k: user_input[k]
                        for k in (
                            A_NAME, A_ENABLED, A_TIME, A_WEEKDAYS, A_PLAYERS, A_MEDIA,
                            A_VOLUME, A_SNOOZE, A_AUTO_STOP,
                        )
                    },
                    # ohne globale Sensoren bleibt die Auswahl unverändert
                    **{
                        k: (user_input.get(k) or [])
                        if self._current.get(CONF_WORKDAY_SENSORS)
                        else list(d.get(k) or [])
                        for k in (A_ONLY_IF_ON, A_NOT_IF_ON)
                    },
                }
                alarms = self._alarms()
                if self._edit_id:
                    alarms = [alarm if a[A_ID] == self._edit_id else a for a in alarms]
                else:
                    alarms.append(alarm)
                self._save({CONF_ALARMS: alarms})
                return await self.async_step_alarm_menu()
            d = user_input
        return self.async_show_form(
            step_id="alarm_edit",
            data_schema=vol.Schema(
                {
                    vol.Required(A_NAME, description=_suggest(A_NAME, d)): str,
                    vol.Required(A_ENABLED, default=d.get(A_ENABLED, True)): bool,
                    vol.Required(
                        A_TIME, default=d.get(A_TIME, "07:00:00")
                    ): selector.TimeSelector(),
                    vol.Required(A_WEEKDAYS, default=d.get(A_WEEKDAYS, list(WEEKDAYS))): _select(
                        WEEKDAYS,
                        "weekday",
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    ),
                    vol.Required(
                        A_PLAYERS, description=_suggest(A_PLAYERS, d)
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="media_player", multiple=True)
                    ),
                    vol.Required(
                        A_MEDIA, description=_suggest(A_MEDIA, d)
                    ): selector.MediaSelector(
                        selector.MediaSelectorConfig(accept=["audio/*"])
                    ),
                    vol.Required(
                        A_VOLUME, default=d.get(A_VOLUME, DEFAULT_ALARM_VOLUME)
                    ): _number(0, 100, "%"),
                    vol.Required(
                        A_SNOOZE, default=d.get(A_SNOOZE, DEFAULT_ALARM_SNOOZE)
                    ): _number(1, 120, "min"),
                    vol.Required(
                        A_AUTO_STOP, default=d.get(A_AUTO_STOP, DEFAULT_ALARM_AUTO_STOP)
                    ): _number(0, 720, "min"),
                    **self._condition_fields(d),
                }
            ),
            errors=errors,
        )

    def _condition_fields(self, d: dict[str, Any]) -> dict[Any, Any]:
        """Werktags-/Feiertagsbedingungen: Auswahl aus den globalen Sensoren (nur wenn vorhanden)."""
        sensors = list(self._current.get(CONF_WORKDAY_SENSORS) or [])
        if not sensors:
            return {}
        options = [
            selector.SelectOptionDict(
                value=entity_id,
                label=(
                    str(state.attributes.get("friendly_name") or entity_id)
                    if (state := self.hass.states.get(entity_id))
                    else entity_id
                ),
            )
            for entity_id in sensors
        ]
        field = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options, multiple=True, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
        return {
            vol.Optional(
                A_ONLY_IF_ON, default=[s for s in d.get(A_ONLY_IF_ON) or [] if s in sensors]
            ): field,
            vol.Optional(
                A_NOT_IF_ON, default=[s for s in d.get(A_NOT_IF_ON) or [] if s in sensors]
            ): field,
        }
