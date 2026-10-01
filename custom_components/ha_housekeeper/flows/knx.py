"""Dialoge der Funktion KNX/Sonos-Connector."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from ..const import (
    ACT_FAVORITE,
    ACT_MUTE_SET,
    ACT_VOLUME_DIM,
    ACT_VOLUME_SET,
    ACTIONS,
    CONF_COMMANDS,
    CONF_MAX_VOLUME,
    CONF_PLAYER,
    CONF_STATUS,
    CONF_STOP_INSTEAD,
    CONF_VOLUME_STEP,
    DEFAULT_MAX_VOLUME,
    DEFAULT_VOLUME_STEP,
    DPT_DIMMING,
    DPT_PERCENT,
    DPT_SCENE,
    DPT_SWITCH,
    DPTS,
    K_ACTION,
    K_ADDRESS,
    K_DPT,
    K_FAVORITE,
    K_ID,
    K_IDLE_TEXT,
    K_NAME,
    S_ENABLED,
    K_SCENE,
    K_SOURCE,
    K_VOLUME,
    K_WHEN,
    SRC_PLAYING,
    STATUS_SOURCES,
    TEXT_SOURCES,
    WHEN_ON,
    WHENS,
)
from ..const import CONF_SPEAKERS, K_PROFILE
from ..knx_codec import is_valid_ga
from ..knx_sonos import (
    command_summary,
    profile_for,
    speaker_profiles,
    status_summary,
)
from .common import _number, _select, _suggest


_SONOS_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="media_player", integration="sonos")
)


def _speaker_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Lautsprecher-Profil: Name, Lautsprecher und die zugehörigen Einstellungen."""
    return vol.Schema(
        {
            vol.Required(K_NAME, description=_suggest(K_NAME, defaults)): str,
            vol.Required(S_ENABLED, default=defaults.get(S_ENABLED, True)): bool,
            vol.Required(
                CONF_PLAYER, description=_suggest(CONF_PLAYER, defaults)
            ): _SONOS_SELECTOR,
            vol.Required(
                CONF_MAX_VOLUME, default=defaults.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME)
            ): _number(0, 100, "%"),
            vol.Required(
                CONF_VOLUME_STEP, default=defaults.get(CONF_VOLUME_STEP, DEFAULT_VOLUME_STEP)
            ): _number(1, 50, "%"),
            vol.Required(
                CONF_STOP_INSTEAD, default=defaults.get(CONF_STOP_INSTEAD, False)
            ): bool,
        }
    )


def _validate_command_basic(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    dpt, action = user_input[K_DPT], user_input[K_ACTION]
    if not is_valid_ga(user_input[K_ADDRESS]):
        errors["base"] = "invalid_address"
    elif (dpt == DPT_DIMMING) != (action == ACT_VOLUME_DIM):
        errors["base"] = "dimming_mismatch"
    elif action == ACT_MUTE_SET and dpt != DPT_SWITCH:
        errors["base"] = "mute_set_needs_switch"
    return errors


def _command_needs_params(draft: dict[str, Any]) -> bool:
    return bool(
        (draft[K_DPT] == DPT_SWITCH and draft[K_ACTION] != ACT_MUTE_SET)
        or draft[K_DPT] == DPT_SCENE
        or (draft[K_ACTION] == ACT_VOLUME_SET and draft[K_DPT] != DPT_PERCENT)
        or draft[K_ACTION] == ACT_FAVORITE
    )


class KnxSonosOptions:
    """Options-Flow-Schritte: KNX/Sonos-Connector."""

    def _commands(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_COMMANDS) or [])

    def _status_list(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_STATUS) or [])

    def _speakers(self) -> list[dict[str, Any]]:
        """Lautsprecher-Profile; ältere Einträge liefern ein Profil „Standard“."""
        current = self._current
        return speaker_profiles(
            lambda key, default=None: default if current.get(key) is None else current[key]
        )

    def _profile_names(self) -> dict[str, str]:
        """Namen der Profile, nur wenn es mehrere gibt (sonst wird das Profil nicht angezeigt)."""
        speakers = self._speakers()
        return {p[K_ID]: p[K_NAME] for p in speakers} if len(speakers) > 1 else {}

    def _profile_field(self, d: dict[str, Any]) -> dict[Any, Any]:
        """Auswahl des Profils für Befehle und Rückmeldungen (nur bei mehreren Profilen)."""
        names = self._profile_names()
        if not names:
            return {}
        first = next(iter(names))
        return {
            vol.Required(K_PROFILE, default=d.get(K_PROFILE) if d.get(K_PROFILE) in names else first): (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=pid, label=name)
                            for pid, name in names.items()
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            )
        }

    def _default_profile_id(self, chosen: str | None = None) -> str | None:
        speakers = self._speakers()
        if chosen and any(p[K_ID] == chosen for p in speakers):
            return chosen
        return speakers[0][K_ID] if speakers else None

    async def async_step_knx_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["add_speaker", "edit_speaker"]
        if len(self._speakers()) > 1:
            options.append("delete_speaker")
        options.append("add_command")
        if self._commands():
            options += ["edit_command", "delete_command"]
        options.append("add_status")
        if self._status_list():
            options += ["edit_status", "delete_status"]
        options.append("done")
        return await self._menu("knx_menu", options, user_input)

    def _speaker_picker_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("item"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=p[K_ID],
                                label=f"{p[K_NAME]} ({p.get(CONF_PLAYER)})"
                                + ("" if p.get(S_ENABLED, True) else (" (aus)" if (self.hass.config.language or "").startswith("de") else " (off)")),
                            )
                            for p in self._speakers()
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    async def async_step_add_speaker(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_speaker_edit()

    async def async_step_edit_speaker(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            speaker = next(p for p in self._speakers() if p[K_ID] == user_input["item"])
            self._edit_id = speaker[K_ID]
            self._draft = dict(speaker)
            return await self.async_step_speaker_edit()
        return self.async_show_form(
            step_id="edit_speaker", data_schema=self._speaker_picker_schema()
        )

    async def async_step_delete_speaker(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            speakers = self._speakers()
            target = user_input["item"]
            first = speakers[0][K_ID] if speakers else None
            # Befehle und Rückmeldungen ohne Profilangabe gehören zum ersten Profil
            used = any(
                (item.get(K_PROFILE) or first) == target
                for item in (*self._commands(), *self._status_list())
            )
            if used:
                errors["base"] = "profile_in_use"
            elif len(speakers) <= 1:
                errors["base"] = "last_profile"
            else:
                self._save({CONF_SPEAKERS: [p for p in speakers if p[K_ID] != target]})
                return await self.async_step_knx_menu()
        return self.async_show_form(
            step_id="delete_speaker",
            data_schema=self._speaker_picker_schema(),
            errors=errors,
        )

    async def async_step_speaker_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        d = self._draft
        if user_input is not None:
            speaker = {
                K_ID: self._edit_id or uuid.uuid4().hex[:8],
                K_NAME: user_input[K_NAME],
                S_ENABLED: user_input.get(S_ENABLED, True),
                CONF_PLAYER: user_input[CONF_PLAYER],
                CONF_MAX_VOLUME: user_input[CONF_MAX_VOLUME],
                CONF_VOLUME_STEP: user_input[CONF_VOLUME_STEP],
                CONF_STOP_INSTEAD: user_input[CONF_STOP_INSTEAD],
            }
            speakers = self._speakers()
            if self._edit_id:
                speakers = [speaker if p[K_ID] == self._edit_id else p for p in speakers]
            else:
                speakers.append(speaker)
            self._save({CONF_SPEAKERS: speakers})
            return await self.async_step_knx_menu()
        return self.async_show_form(
            step_id="speaker_edit", data_schema=_speaker_schema(d)
        )

    def _item_picker_schema(self, items: list[dict[str, Any]], summary) -> vol.Schema:
        names = self._profile_names()
        first = next(iter(names), None)
        return vol.Schema(
            {
                vol.Required("item"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=i[K_ID],
                                label=summary(
                                    self.hass, i, names.get(i.get(K_PROFILE) or first)
                                ),
                            )
                            for i in items
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    async def async_step_add_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_command_basic()

    async def async_step_edit_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            command = next(c for c in self._commands() if c[K_ID] == user_input["item"])
            self._edit_id = command[K_ID]
            self._draft = dict(command)
            return await self.async_step_command_basic()
        return self.async_show_form(
            step_id="edit_command",
            data_schema=self._item_picker_schema(self._commands(), command_summary),
        )

    async def async_step_delete_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {
                    CONF_COMMANDS: [
                        c for c in self._commands() if c[K_ID] != user_input["item"]
                    ]
                }
            )
            return await self.async_step_knx_menu()
        return self.async_show_form(
            step_id="delete_command",
            data_schema=self._item_picker_schema(self._commands(), command_summary),
        )

    async def async_step_command_basic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            errors = _validate_command_basic(user_input)
            if not errors:
                self._draft = {
                    **user_input,
                    K_PROFILE: self._default_profile_id(user_input.get(K_PROFILE)),
                }
                if _command_needs_params(self._draft):
                    return await self.async_step_command_params()
                return await self._finish_command()
            d = user_input
        return self.async_show_form(
            step_id="command_basic",
            data_schema=vol.Schema(
                {
                    vol.Required(K_NAME, description=_suggest(K_NAME, d)): str,
                    vol.Required(K_ADDRESS, description=_suggest(K_ADDRESS, d)): str,
                    vol.Required(K_DPT, default=d.get(K_DPT, DPT_SWITCH)): _select(
                        DPTS, "knx_dpt", mode=selector.SelectSelectorMode.LIST
                    ),
                    vol.Required(K_ACTION, default=d.get(K_ACTION, "play")): _select(
                        ACTIONS, "knx_action"
                    ),
                    **self._profile_field(d),
                }
            ),
            errors=errors,
        )

    async def async_step_command_params(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        d = self._draft
        if user_input is not None:
            self._draft = {**d, **user_input}
            return await self._finish_command()
        fields: dict[Any, Any] = {}
        if d[K_DPT] == DPT_SWITCH and d[K_ACTION] != ACT_MUTE_SET:
            fields[vol.Required(K_WHEN, default=d.get(K_WHEN, WHEN_ON))] = _select(
                WHENS, "knx_when", mode=selector.SelectSelectorMode.LIST
            )
        if d[K_DPT] == DPT_SCENE:
            fields[vol.Required(K_SCENE, default=d.get(K_SCENE, 1))] = _number(1, 64)
        if d[K_ACTION] == ACT_VOLUME_SET and d[K_DPT] != DPT_PERCENT:
            fields[vol.Required(K_VOLUME, default=d.get(K_VOLUME, 20))] = _number(0, 100, "%")
        if d[K_ACTION] == ACT_FAVORITE:
            profile = profile_for(self._speakers(), d) or {}
            state = self.hass.states.get(profile.get(CONF_PLAYER, ""))
            sources = sorted((state.attributes.get("source_list") or []) if state else [])
            fields[vol.Required(K_FAVORITE, description=_suggest(K_FAVORITE, d))] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=sources,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            )
        return self.async_show_form(
            step_id="command_params", data_schema=vol.Schema(fields)
        )

    async def _finish_command(self) -> ConfigFlowResult:
        d = self._draft
        keep = [K_NAME, K_ADDRESS, K_DPT, K_ACTION, K_PROFILE]
        if d[K_DPT] == DPT_SWITCH and d[K_ACTION] != ACT_MUTE_SET:
            keep.append(K_WHEN)
        if d[K_DPT] == DPT_SCENE:
            keep.append(K_SCENE)
        if d[K_ACTION] == ACT_VOLUME_SET and d[K_DPT] != DPT_PERCENT:
            keep.append(K_VOLUME)
        if d[K_ACTION] == ACT_FAVORITE:
            keep.append(K_FAVORITE)
        command = {K_ID: self._edit_id or uuid.uuid4().hex[:8]}
        command.update({k: d[k] for k in keep if k in d})
        commands = self._commands()
        if self._edit_id:
            commands = [command if c[K_ID] == self._edit_id else c for c in commands]
        else:
            commands.append(command)
        self._save({CONF_COMMANDS: commands})
        return await self.async_step_knx_menu()

    async def async_step_add_status(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_status_edit()

    async def async_step_edit_status(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            status = next(s for s in self._status_list() if s[K_ID] == user_input["item"])
            self._edit_id = status[K_ID]
            self._draft = dict(status)
            return await self.async_step_status_edit()
        return self.async_show_form(
            step_id="edit_status",
            data_schema=self._item_picker_schema(self._status_list(), status_summary),
        )

    async def async_step_delete_status(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {
                    CONF_STATUS: [
                        s for s in self._status_list() if s[K_ID] != user_input["item"]
                    ]
                }
            )
            return await self.async_step_knx_menu()
        return self.async_show_form(
            step_id="delete_status",
            data_schema=self._item_picker_schema(self._status_list(), status_summary),
        )

    async def async_step_status_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            if not is_valid_ga(user_input[K_ADDRESS]):
                errors["base"] = "invalid_address"
            else:
                status = {
                    K_ID: self._edit_id or uuid.uuid4().hex[:8],
                    K_NAME: user_input[K_NAME],
                    K_SOURCE: user_input[K_SOURCE],
                    K_ADDRESS: user_input[K_ADDRESS],
                    K_PROFILE: self._default_profile_id(user_input.get(K_PROFILE)),
                }
                if user_input[K_SOURCE] in TEXT_SOURCES:
                    status[K_IDLE_TEXT] = user_input.get(K_IDLE_TEXT, "")
                items = self._status_list()
                if self._edit_id:
                    items = [status if s[K_ID] == self._edit_id else s for s in items]
                else:
                    items.append(status)
                self._save({CONF_STATUS: items})
                return await self.async_step_knx_menu()
            d = user_input
        return self.async_show_form(
            step_id="status_edit",
            data_schema=vol.Schema(
                {
                    vol.Required(K_NAME, description=_suggest(K_NAME, d)): str,
                    vol.Required(K_SOURCE, default=d.get(K_SOURCE, SRC_PLAYING)): _select(
                        STATUS_SOURCES, "knx_source"
                    ),
                    vol.Required(K_ADDRESS, description=_suggest(K_ADDRESS, d)): str,
                    vol.Optional(K_IDLE_TEXT, default=d.get(K_IDLE_TEXT, "")): str,
                    **self._profile_field(d),
                }
            ),
            errors=errors,
        )
