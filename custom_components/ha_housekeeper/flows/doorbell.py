"""Dialoge der Funktion Türklingel."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from ..const import (
    CONF_CLEAR_HOURS,
    CONF_DEBOUNCE,
    CONF_MESSAGE,
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    CONF_PROFILES,
    CONF_TRIGGER_ENTITY,
    DEFAULT_CLEAR_HOURS,
    DEFAULT_RING_DEBOUNCE,
    DEFAULT_RING_MESSAGE,
    MODE_KEYS,
    MODE_RINGTONE,
    MODE_TTS,
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
    WEEKDAYS,
)
from ..doorbell import profile_summary
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
    notifications: dict[Any, Any] = {
        vol.Required(
            CONF_MOBILE_ENABLED, default=defaults.get(CONF_MOBILE_ENABLED, True)
        ): bool,
        vol.Optional(
            CONF_MOBILE_TARGETS, description=_mobile_suggest(hass, defaults)
        ): _mobile_selector(),
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
    return _sections_schema(fields, notifications)


def _validate_bell(user_input: dict[str, Any]) -> dict[str, str]:
    if user_input.get(CONF_MOBILE_ENABLED) and not user_input.get(CONF_MOBILE_TARGETS):
        return {"base": "no_targets"}
    return {}


class DoorbellOptions:
    """Options-Flow-Schritte: Türklingel."""

    def _profiles(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_PROFILES) or [])

    async def async_step_bell_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["bell_general", "add_profile"]
        if self._profiles():
            options += ["edit_profile", "delete_profile"]
        options.append("done")
        return await self._menu("bell_menu", options, user_input)

    async def async_step_bell_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            user_input = _flatten_sections(user_input)
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
