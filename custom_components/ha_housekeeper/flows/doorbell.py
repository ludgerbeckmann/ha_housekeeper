"""Dialoge der Funktion Türklingel."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    CONF_DEBOUNCE,
    CONF_NAME,
    CONF_PROFILES,
    CONF_TRIGGER_ENTITY,
    DEFAULT_CLEAR_HOURS,
    DEFAULT_RING_DEBOUNCE,
    DEFAULT_RING_MESSAGE,
    MODE_KEYS,
    MODE_RINGTONE,
    MODE_TTS,
    P_CLEAR_HOURS,
    P_ENABLED,
    P_FROM,
    P_ID,
    P_MEDIA,
    P_MESSAGE,
    P_MOBILE_ENABLED,
    P_MOBILE_TARGETS,
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
    SECTION_NOTIFICATIONS,
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
    return _sections_schema(fields, {})


def _validate_bell(user_input: dict[str, Any]) -> dict[str, str]:
    """Der Eintrag selbst hat keine Pflichtprüfung mehr (Push steckt in den Profilen)."""
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
        """Alle Angaben eines Profils in einem Formular: Zeitfenster, Ton, Benachrichtigung."""
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            flat = _flatten_sections(user_input)
            mode = flat.get(P_MODE, MODE_TTS)
            push = bool(flat.get(P_MOBILE_ENABLED))
            if not flat.get(P_WEEKDAYS):
                errors["base"] = "no_weekday"
            elif not flat.get(P_PLAYERS) and not push:
                errors["base"] = "no_output"
            elif push and not flat.get(P_MOBILE_TARGETS):
                errors["base"] = "no_targets"
            elif flat.get(P_PLAYERS) and mode == MODE_TTS and not (
                flat.get(P_TTS_ENTITY) and flat.get(P_TEXT)
            ):
                errors["base"] = "no_tts"
            elif flat.get(P_PLAYERS) and mode == MODE_RINGTONE and not (
                flat.get(P_MEDIA) or {}
            ).get("media_content_id"):
                errors["base"] = "no_ringtone"
            else:
                self._draft = flat
                return await self._finish_profile()
            d = flat
        timing: dict[Any, Any] = {
            vol.Required(P_NAME, description=_suggest(P_NAME, d)): str,
            vol.Required(P_ENABLED, default=d.get(P_ENABLED, True)): bool,
            vol.Required(P_FROM, default=d.get(P_FROM, "07:00:00")): selector.TimeSelector(),
            vol.Required(P_TO, default=d.get(P_TO, "22:00:00")): selector.TimeSelector(),
            vol.Required(P_WEEKDAYS, default=d.get(P_WEEKDAYS, WEEKDAYS)): _select(
                WEEKDAYS, "weekday", multiple=True, mode=selector.SelectSelectorMode.LIST
            ),
        }
        sound: dict[Any, Any] = {
            vol.Optional(
                P_PLAYERS, description=_suggest(P_PLAYERS, d)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=True)
            ),
            vol.Required(P_MODE, default=d.get(P_MODE, MODE_TTS)): _select(
                [MODE_TTS, MODE_RINGTONE], "profile_mode", mode=selector.SelectSelectorMode.LIST
            ),
            vol.Optional(
                P_TTS_ENTITY, description=_suggest(P_TTS_ENTITY, d)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="tts")),
            vol.Optional(P_TEXT, default=d.get(P_TEXT, DEFAULT_RING_MESSAGE)): str,
            vol.Optional(P_MEDIA, description=_suggest(P_MEDIA, d)): selector.MediaSelector(
                selector.MediaSelectorConfig(accept=["audio/*"])
            ),
            vol.Required(P_VOLUME, default=d.get(P_VOLUME, 0)): _number(0, 100, "%"),
        }
        notifications: dict[Any, Any] = {
            vol.Required(
                P_MOBILE_ENABLED, default=d.get(P_MOBILE_ENABLED, False)
            ): bool,
            vol.Optional(P_MOBILE_TARGETS, description=_mobile_suggest(self.hass, d)): _mobile_selector(),
            vol.Required(P_MESSAGE, default=d.get(P_MESSAGE, DEFAULT_RING_MESSAGE)): str,
            vol.Required(
                P_CLEAR_HOURS, default=d.get(P_CLEAR_HOURS, DEFAULT_CLEAR_HOURS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=168, step=0.5, unit_of_measurement="h",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
        return self.async_show_form(
            step_id="profile_basic",
            data_schema=vol.Schema(
                {
                    vol.Required("timing"): section(vol.Schema(timing), {"collapsed": False}),
                    vol.Required("sound"): section(vol.Schema(sound), {"collapsed": False}),
                    vol.Required(SECTION_NOTIFICATIONS): section(
                        vol.Schema(notifications), {"collapsed": False}
                    ),
                }
            ),
            errors=errors,
        )

    async def _finish_profile(self) -> ConfigFlowResult:
        d = self._draft
        has_sound = bool(d.get(P_PLAYERS))
        keys = [P_NAME, P_ENABLED, P_FROM, P_TO, P_WEEKDAYS, P_PLAYERS]
        profile: dict[str, Any] = {
            P_ID: self._edit_id or uuid.uuid4().hex[:8],
            **{k: d[k] for k in keys if k in d},
            P_MOBILE_ENABLED: bool(d.get(P_MOBILE_ENABLED)),
            P_MOBILE_TARGETS: d.get(P_MOBILE_TARGETS) or [],
            P_MESSAGE: d.get(P_MESSAGE) or DEFAULT_RING_MESSAGE,
            P_CLEAR_HOURS: d.get(P_CLEAR_HOURS, DEFAULT_CLEAR_HOURS),
            P_PLAYERS: d.get(P_PLAYERS) or [],
        }
        if has_sound:
            mode = d.get(P_MODE, MODE_TTS)
            profile[P_MODE] = mode
            profile[P_VOLUME] = d.get(P_VOLUME, 0)
            profile.update({k: d[k] for k in MODE_KEYS[mode] if k in d})
        profiles = self._profiles()
        if self._edit_id:
            profiles = [profile if p[P_ID] == self._edit_id else p for p in profiles]
        else:
            profiles.append(profile)
        self._save({CONF_PROFILES: profiles})
        return await self.async_step_bell_menu()
