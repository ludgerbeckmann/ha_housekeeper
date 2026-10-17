"""Dialoge der Funktion IR-Fernbedienung."""

from __future__ import annotations

import asyncio
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .. import ir_remote
from ..const import (
    CONF_IR_COMMANDS,
    CONF_IR_DELAY,
    CONF_IR_DEVICE,
    CONF_IR_OFF,
    CONF_IR_ON,
    CONF_IR_REPEATS,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    CONF_REMOTES,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    DEFAULT_IR_DELAY,
    DEFAULT_IR_REPEATS,
    DOMAIN,
    IC_CODE,
    IC_ENABLED,
    IC_ID,
    IC_NAME,
    IC_REMOTES,
    IC_TYPE,
    IR_TYPE_IR,
    IR_TYPES,
)
from .common import (
    _POOL_NOTIFY_DEFAULTS,
    _flatten_sections,
    _notify_fields,
    _number,
    _sections_schema,
    _select,
    _suggest,
    _validate_notify,
)

_CLEARABLE = (CONF_MOBILE_TARGETS, CONF_TTS_ENTITY, CONF_TTS_PLAYER)


def _remote_selector() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="remote", multiple=True)
    )


def _ir_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    """Anlegen (mit Name und Gerätename) und Einstellungen (ohne beides)."""
    general: dict[Any, Any] = {}
    if with_name:
        general[vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults))] = str
    general[vol.Required(CONF_REMOTES, description=_suggest(CONF_REMOTES, defaults))] = (
        _remote_selector()
    )
    if with_name:
        general[
            vol.Required(CONF_IR_DEVICE, description=_suggest(CONF_IR_DEVICE, defaults))
        ] = str
    general[
        vol.Required(CONF_IR_REPEATS, default=defaults.get(CONF_IR_REPEATS, DEFAULT_IR_REPEATS))
    ] = _number(1, 20)
    general[
        vol.Required(CONF_IR_DELAY, default=defaults.get(CONF_IR_DELAY, DEFAULT_IR_DELAY))
    ] = _number(0, 10, "s", step=0.1)
    return _sections_schema(
        general,
        _notify_fields(hass, {**_POOL_NOTIFY_DEFAULTS, **defaults}, with_action=False),
    )


def _validate_ir(user_input: dict[str, Any], with_device: bool) -> dict[str, str]:
    errors = _validate_notify(user_input, require_method=False)
    if not user_input.get(CONF_REMOTES):
        errors["base"] = "no_remotes"
    elif with_device and not (user_input.get(CONF_IR_DEVICE) or "").strip():
        errors["base"] = "no_device"
    return errors


def ir_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern; geleerte optionale Felder werden explizit auf None gesetzt."""
    data = {**{key: None for key in _CLEARABLE}, **flat}
    data.pop(CONF_NAME, None)
    if CONF_IR_DEVICE in data:
        data[CONF_IR_DEVICE] = data[CONF_IR_DEVICE].strip()
    data[CONF_IR_REPEATS] = int(data[CONF_IR_REPEATS])
    return data


def new_instance_data(flat: dict[str, Any]) -> dict[str, Any]:
    return {CONF_IR_COMMANDS: [], **ir_data(flat)}


class IrOptions:
    """Options-Flow-Schritte: IR-Fernbedienung."""

    _learn: dict[str, Any] | None = None

    # --- Hilfen ------------------------------------------------------------

    def _ir_commands(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_IR_COMMANDS) or [])

    def _ir_remotes(self) -> list[str]:
        return list(self._current.get(CONF_REMOTES) or [])

    def _remote_name(self, remote: str) -> str:
        state = self.hass.states.get(remote)
        return state.name if state else remote

    def _remote_options(self) -> list[selector.SelectOptionDict]:
        return [
            selector.SelectOptionDict(value=r, label=self._remote_name(r))
            for r in self._ir_remotes()
        ]

    def _command_picker(self, *extra: Any) -> vol.Schema:
        fields: dict[Any, Any] = {
            vol.Required("command"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=c[IC_ID], label=c[IC_NAME])
                        for c in self._ir_commands()
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
        for item in extra:
            fields.update(item)
        return vol.Schema(fields)

    def _learn_on_field(self, default: list[str]) -> dict[Any, Any]:
        return {
            vol.Required("learn_on", default=default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=self._remote_options(),
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }

    def _ir_listing(self) -> str:
        total = len(self._ir_remotes())
        lines = []
        for command in self._ir_commands():
            known = [r for r in self._ir_remotes() if r in (command.get(IC_REMOTES) or [])]
            off = "" if command.get(IC_ENABLED, True) else " (aus)"
            lines.append(f"• {command[IC_NAME]}{off}: {len(known)}/{total}")
        return "\n".join(lines) or "–"

    def _save_command(self, command: dict[str, Any]) -> None:
        commands = self._ir_commands()
        if any(c[IC_ID] == command[IC_ID] for c in commands):
            commands = [command if c[IC_ID] == command[IC_ID] else c for c in commands]
        else:
            commands.append(command)
        self._save({CONF_IR_COMMANDS: commands})

    # --- Menü und Einstellungen ------------------------------------------------

    async def async_step_ir_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["ir_general", "add_ir_command", "import_ir_commands"]
        if self._ir_commands():
            options += [
                "learn_ir_command",
                "test_ir_command",
                "edit_ir_command",
                "delete_ir_command",
                "ir_switch",
            ]
        options.append("rename")
        return await self._menu(
            "ir_menu", options, user_input, {"commands": self._ir_listing()}
        )

    async def async_step_ir_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_ir(flat, with_device=False)
            if not errors:
                self._save(ir_data(flat))
                return await self.async_step_ir_menu()
            defaults = flat
        return self.async_show_form(
            step_id="ir_general",
            data_schema=_ir_schema(self.hass, defaults, with_name=False),
            errors=errors,
        )

    # --- Befehle anlegen und anlernen ---------------------------------------------

    async def async_step_add_ir_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            code = ir_remote.command_code(user_input[IC_NAME])
            if any(c[IC_CODE] == code for c in self._ir_commands()):
                errors["base"] = "command_exists"
                defaults = user_input
            else:
                command = {
                    IC_ID: uuid.uuid4().hex[:8],
                    IC_NAME: user_input[IC_NAME].strip(),
                    IC_CODE: code,
                    IC_TYPE: user_input[IC_TYPE],
                    IC_ENABLED: True,
                    IC_REMOTES: [],
                }
                return await self._start_learn(command, user_input["learn_on"], is_new=True)
        return self.async_show_form(
            step_id="add_ir_command",
            data_schema=vol.Schema(
                {
                    vol.Required(IC_NAME, description=_suggest(IC_NAME, defaults)): str,
                    vol.Required(IC_TYPE, default=defaults.get(IC_TYPE, IR_TYPE_IR)): _select(
                        IR_TYPES, "ir_type", mode=selector.SelectSelectorMode.LIST
                    ),
                    **self._learn_on_field(defaults.get("learn_on", self._ir_remotes())),
                }
            ),
            errors=errors,
        )

    async def async_step_learn_ir_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Befehl an weiteren Sendern anlernen oder dort neu anlernen."""
        if user_input is not None:
            command = next(c for c in self._ir_commands() if c[IC_ID] == user_input["command"])
            return await self._start_learn(command, user_input["learn_on"], is_new=False)
        return self.async_show_form(
            step_id="learn_ir_command",
            data_schema=self._command_picker(self._learn_on_field(self._ir_remotes())),
        )

    async def _start_learn(
        self, command: dict[str, Any], remotes: list[str], is_new: bool
    ) -> ConfigFlowResult:
        self._learn = {
            "command": command,
            "queue": [r for r in self._ir_remotes() if r in remotes],
            "done": [],
            "failed": {},
            "is_new": is_new,
            "task": None,
        }
        return await self.async_step_ir_learn()

    async def async_step_ir_learn(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Je Sender ein Fortschrittsdialog: Taste der Original-Fernbedienung drücken."""
        learn = self._learn
        if not learn["queue"]:
            return await self.async_step_ir_learn_done()
        remote = learn["queue"][0]
        command = learn["command"]
        if learn["task"] is None:
            learn["task"] = self.hass.async_create_task(
                ir_remote.async_learn(
                    self.hass,
                    remote,
                    self._current[CONF_IR_DEVICE],
                    command[IC_CODE],
                    command[IC_TYPE],
                )
            )
        task: asyncio.Task = learn["task"]
        if not task.done():
            return self.async_show_progress(
                step_id="ir_learn",
                progress_action="learn",
                progress_task=task,
                description_placeholders={
                    "command": command[IC_NAME],
                    "remote": self._remote_name(remote),
                },
            )
        learn["queue"].pop(0)
        learn["task"] = None
        try:
            task.result()
        except Exception as err:  # noqa: BLE001
            learn["failed"][remote] = str(err) or type(err).__name__
        else:
            learn["done"].append(remote)
        return self.async_show_progress_done(next_step_id="ir_learn")

    async def async_step_ir_learn_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ergebnis speichern; bei Fehlern zeigt ein Formular die Ursache."""
        learn = self._learn
        if user_input is not None:
            return await self.async_step_ir_menu()
        command = {**learn["command"]}
        if learn["done"]:
            known = set(command.get(IC_REMOTES) or []) | set(learn["done"])
            command[IC_REMOTES] = [r for r in self._ir_remotes() if r in known]
            self._save_command(command)
        if not learn["failed"]:
            return await self.async_step_ir_menu()
        detail = "; ".join(
            f"{self._remote_name(r)}: {err}" for r, err in learn["failed"].items()
        )
        return self.async_show_form(
            step_id="ir_learn_done",
            data_schema=vol.Schema({}),
            errors={"base": "learn_failed"},
            description_placeholders={"detail": detail, "command": command[IC_NAME]},
        )

    # --- Vorhandene Befehle übernehmen ----------------------------------------------

    async def async_step_import_ir_commands(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Befehle übernehmen, die beim Sender schon angelernt sind (z. B. aus alten Skripten)."""
        device = self._current[CONF_IR_DEVICE]
        found: dict[str, list[str]] = {}
        for remote in self._ir_remotes():
            for code in await ir_remote.async_stored_codes(self.hass, remote, device):
                found.setdefault(code, []).append(remote)
        existing = {c[IC_CODE] for c in self._ir_commands()}
        options = sorted(code for code in found if code not in existing)
        if user_input is not None:
            commands = self._ir_commands()
            for code in user_input.get("codes", []):
                code = ir_remote.command_code(code) if code not in found else code
                if code in existing:
                    continue
                existing.add(code)
                commands.append(
                    {
                        IC_ID: uuid.uuid4().hex[:8],
                        IC_NAME: ir_remote.command_label(code),
                        IC_CODE: code,
                        IC_TYPE: IR_TYPE_IR,
                        IC_ENABLED: True,
                        IC_REMOTES: found.get(code) or self._ir_remotes(),
                    }
                )
            self._save({CONF_IR_COMMANDS: commands})
            return await self.async_step_ir_menu()
        return self.async_show_form(
            step_id="import_ir_commands",
            data_schema=vol.Schema(
                {
                    vol.Optional("codes", default=options): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            description_placeholders={"device": device, "found": str(len(options))},
        )

    # --- Testen, bearbeiten, löschen, Schalter ----------------------------------------

    async def async_step_test_ir_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            command = next(c for c in self._ir_commands() if c[IC_ID] == user_input["command"])
            remotes = [r for r in self._ir_remotes() if r in (command.get(IC_REMOTES) or [])]
            controller = self.hass.data.get(DOMAIN, {}).get(self._get_reconfigure_subentry().subentry_id)
            if controller is not None:
                result = await controller.async_send(command[IC_ID])
                detail = ""
                failed = result != "ok"
            else:
                sent = await ir_remote.async_send(
                    self.hass,
                    remotes,
                    self._current[CONF_IR_DEVICE],
                    command[IC_CODE],
                    int(self._current.get(CONF_IR_REPEATS) or DEFAULT_IR_REPEATS),
                    float(self._current.get(CONF_IR_DELAY) or DEFAULT_IR_DELAY),
                )
                failed = ir_remote.outcome(sent) != "ok"
                detail = "; ".join(f"{r}: {e}" for r, e in sent.items() if e)
            if not failed:
                return await self.async_step_ir_menu()
            errors["base"] = "send_failed"
            if controller is not None and controller.last_sent:
                detail = "; ".join(
                    f"{r}: {e}" for r, e in (controller.last_sent.get("errors") or {}).items()
                ) or (controller.last_sent.get("result") or "")
        return self.async_show_form(
            step_id="test_ir_command",
            data_schema=self._command_picker(),
            errors=errors,
            description_placeholders={"detail": detail},
        )

    async def async_step_edit_ir_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            command = next(c for c in self._ir_commands() if c[IC_ID] == user_input["command"])
            self._edit_id = command[IC_ID]
            self._draft = command
            return await self.async_step_ir_command_edit()
        return self.async_show_form(
            step_id="edit_ir_command", data_schema=self._command_picker()
        )

    async def async_step_ir_command_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        d = self._draft
        if user_input is not None:
            self._save_command(
                {**d, IC_NAME: user_input[IC_NAME].strip(), IC_ENABLED: user_input[IC_ENABLED]}
            )
            return await self.async_step_ir_menu()
        return self.async_show_form(
            step_id="ir_command_edit",
            data_schema=vol.Schema(
                {
                    vol.Required(IC_NAME, description=_suggest(IC_NAME, d)): str,
                    vol.Required(IC_ENABLED, default=d.get(IC_ENABLED, True)): bool,
                }
            ),
            description_placeholders={"code": d[IC_CODE]},
        )

    async def async_step_delete_ir_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            command_id = user_input["command"]
            command = next(c for c in self._ir_commands() if c[IC_ID] == command_id)
            if command_id in (self._current.get(CONF_IR_ON), self._current.get(CONF_IR_OFF)):
                errors["base"] = "command_in_use"
            else:
                if user_input["delete_codes"]:
                    for remote in command.get(IC_REMOTES) or []:
                        await ir_remote.async_delete(
                            self.hass, remote, self._current[CONF_IR_DEVICE], command[IC_CODE]
                        )
                self._save(
                    {
                        CONF_IR_COMMANDS: [
                            c for c in self._ir_commands() if c[IC_ID] != command_id
                        ]
                    }
                )
                return await self.async_step_ir_menu()
        return self.async_show_form(
            step_id="delete_ir_command",
            data_schema=self._command_picker(
                {vol.Required("delete_codes", default=True): bool}
            ),
            errors=errors,
        )

    async def async_step_ir_switch(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            on, off = user_input.get(CONF_IR_ON), user_input.get(CONF_IR_OFF)
            if bool(on) != bool(off):
                errors["base"] = "switch_incomplete"
            elif on and on == off:
                errors["base"] = "switch_same"
            else:
                self._save({CONF_IR_ON: on, CONF_IR_OFF: off})
                return await self.async_step_ir_menu()
            defaults = user_input
        picker = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value=c[IC_ID], label=c[IC_NAME])
                    for c in self._ir_commands()
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
        return self.async_show_form(
            step_id="ir_switch",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_IR_ON, description=_suggest(CONF_IR_ON, defaults)): picker,
                    vol.Optional(CONF_IR_OFF, description=_suggest(CONF_IR_OFF, defaults)): picker,
                }
            ),
            errors=errors,
        )
