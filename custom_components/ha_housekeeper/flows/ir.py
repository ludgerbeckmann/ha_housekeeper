"""Dialoge der Funktion IR-Fernbedienung."""

from __future__ import annotations

import asyncio
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult, SubentryFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .. import ir_remote
from ..const import (
    CONF_IR_ACTIVE,
    CONF_IR_GROUPS,
    CONF_IR_COMMANDS,
    CONF_IR_DELETE,
    CONF_IR_DELETE_CODES,
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
    IC_B64,
    IC_CODE,
    IC_ENABLED,
    IC_ID,
    IC_LEARNED,
    IC_NAME,
    IC_REMOTES,
    IC_TYPE,
    IG_COMMANDS,
    IG_ID,
    IG_NAME,
    IR_TYPE_IR,
    IR_TYPES,
    clean_instance_name,
    instance_name,
    instance_title,
)
from .common import (
    SECTION_GENERAL,
    SECTION_NOTIFICATIONS,
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
SECTION_COMMANDS = "commands"
SECTION_SWITCH = "switch"


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


def _ir_settings_schema(
    hass: HomeAssistant, defaults: dict[str, Any], commands: list[dict[str, Any]]
) -> vol.Schema:
    """Die Seite: Allgemein (Name, Sender, Wiederholungen), Befehle, Schalter und Benachrichtigung (nur „Allgemein“ offen)."""

    def _section(fields: dict[Any, Any], collapsed: bool = True) -> Any:
        return section(vol.Schema(fields), {"collapsed": collapsed})

    options = [selector.SelectOptionDict(value=c[IC_ID], label=c[IC_NAME]) for c in commands]

    def _picker(multiple: bool) -> selector.SelectSelector:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                multiple=multiple,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    general: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
        vol.Required(CONF_REMOTES, description=_suggest(CONF_REMOTES, defaults)): _remote_selector(),
        vol.Required(
            CONF_IR_REPEATS, default=defaults.get(CONF_IR_REPEATS, DEFAULT_IR_REPEATS)
        ): _number(1, 20),
        vol.Required(
            CONF_IR_DELAY, default=defaults.get(CONF_IR_DELAY, DEFAULT_IR_DELAY)
        ): _number(0, 10, "s", step=0.1),
    }
    active = defaults.get(CONF_IR_ACTIVE)
    if active is None:
        active = [c[IC_ID] for c in commands if c.get(IC_ENABLED, True)]
    command_fields: dict[Any, Any] = {
        vol.Optional(CONF_IR_ACTIVE, default=active): _picker(True),
        vol.Optional(CONF_IR_DELETE): _picker(True),
        vol.Required(CONF_IR_DELETE_CODES, default=True): bool,
    }
    switch_fields: dict[Any, Any] = {
        vol.Optional(CONF_IR_ON, description=_suggest(CONF_IR_ON, defaults)): _picker(False),
        vol.Optional(CONF_IR_OFF, description=_suggest(CONF_IR_OFF, defaults)): _picker(False),
    }
    return vol.Schema(
        {
            vol.Required(SECTION_GENERAL): _section(general, collapsed=False),
            vol.Required(SECTION_COMMANDS): _section(command_fields),
            vol.Required(SECTION_SWITCH): _section(switch_fields),
            vol.Required(SECTION_NOTIFICATIONS): _section(
                _notify_fields(hass, {**_POOL_NOTIFY_DEFAULTS, **defaults}, with_action=False)
            ),
        }
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
    _assign_remote: str = ""
    _group_edit: dict[str, Any] = {}

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

    def _ir_groups(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_IR_GROUPS) or [])

    def _picker(self, options: list[selector.SelectOptionDict], multiple: bool, **kwargs: Any) -> Any:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                multiple=multiple,
                mode=selector.SelectSelectorMode.DROPDOWN,
                **kwargs,
            )
        )

    def _command_options(self) -> list[selector.SelectOptionDict]:
        return [
            selector.SelectOptionDict(value=c[IC_ID], label=c[IC_NAME]) for c in self._ir_commands()
        ]

    async def _ensure_b64(self, command: dict[str, Any]) -> dict[str, Any] | None:
        """Befehl mit Base64-Code (aus den Daten oder dem Speicher eines Senders); `None`, wenn nicht lesbar."""
        if command.get(IC_B64):
            return command
        learned = command.get(IC_LEARNED)
        sources = list(command.get(IC_REMOTES) or []) if learned is None else list(learned)
        code = await ir_remote.async_stored_code(
            self.hass, sources, self._current[CONF_IR_DEVICE], command[IC_CODE]
        )
        return {**command, IC_B64: code} if code else None

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
        """Kleines Menü: Einstellungen (eine Seite) sowie Anlernen und Übernehmen von Befehlen."""
        options = ["ir_settings", "add_ir_command"]
        if self._ir_commands():
            options.append("learn_ir_command")
        options.append("import_ir_commands")
        if self._ir_commands():
            if len(self._ir_remotes()) > 1:
                options.append("ir_assign")
            options.append("ir_groups")
        return await self._menu(
            "ir_menu", options, user_input, {"commands": self._ir_listing()}
        )

    async def async_step_ir_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Alle Einstellungen auf einer Seite: Name, Sender, Wiederholungen, Befehle, Schalter, Meldungen."""
        errors: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        commands = self._ir_commands()
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_ir(flat, with_device=False)
            active = set(flat.pop(CONF_IR_ACTIVE, None) or [])
            delete = set(flat.pop(CONF_IR_DELETE, None) or [])
            delete_codes = bool(flat.pop(CONF_IR_DELETE_CODES, True))
            on, off = flat.get(CONF_IR_ON), flat.get(CONF_IR_OFF)
            if not errors:
                if bool(on) != bool(off):
                    errors["base"] = "switch_incomplete"
                elif on and on == off:
                    errors["base"] = "switch_same"
                elif {on, off} & delete:
                    errors["base"] = "command_in_use"
            if not errors:
                for command in commands:
                    if command[IC_ID] in delete and delete_codes:
                        learned = command.get(IC_LEARNED)
                        for remote in (command.get(IC_REMOTES) or []) if learned is None else learned:
                            await ir_remote.async_delete(
                                self.hass, remote, self._current[CONF_IR_DEVICE], command[IC_CODE]
                            )
                kept = [
                    {**c, IC_ENABLED: c[IC_ID] in active}
                    for c in commands
                    if c[IC_ID] not in delete
                ]
                name = (flat.pop(CONF_NAME, None) or "").strip()
                data = {**ir_data(flat), CONF_IR_COMMANDS: kept, CONF_IR_ON: on or None, CONF_IR_OFF: off or None}
                if delete:
                    data[CONF_IR_GROUPS] = [
                        {**g, IG_COMMANDS: [i for i in g[IG_COMMANDS] if i not in delete]}
                        for g in self._ir_groups()
                    ]
                self.hass.config_entries.async_update_subentry(
                    self._get_entry(),
                    subentry,
                    title=instance_title(
                        self.hass, self.function_type, clean_instance_name(self.function_type, name)
                    ),
                    data={**subentry.data, **data},
                )
                return self.async_abort(reason="reconfigure_successful")
            defaults = {**defaults, **flat, CONF_IR_ACTIVE: list(active), CONF_IR_ON: on, CONF_IR_OFF: off}
        return self.async_show_form(
            step_id="ir_settings",
            data_schema=_ir_settings_schema(self.hass, defaults, commands),
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
            learned = (
                set(command.get(IC_REMOTES) or [])
                if command.get(IC_LEARNED) is None and not learn["is_new"]
                else set(command.get(IC_LEARNED) or [])
            ) | set(learn["done"])
            command[IC_LEARNED] = [r for r in self._ir_remotes() if r in learned]
            if code := await ir_remote.async_stored_code(
                self.hass, learn["done"], self._current[CONF_IR_DEVICE], command[IC_CODE]
            ):
                command[IC_B64] = code
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
                        IC_LEARNED: found.get(code) or self._ir_remotes(),
                        **(
                            {IC_B64: b64}
                            if (
                                b64 := await ir_remote.async_stored_code(
                                    self.hass, found.get(code) or [], device, code
                                )
                            )
                            else {}
                        ),
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


    # --- Sender zuordnen -------------------------------------------------------------

    async def async_step_ir_assign(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sender wählen, dem Befehle (einzeln oder als Gruppe) zugeordnet werden."""
        if user_input is not None:
            self._assign_remote = user_input["remote"]
            return await self.async_step_ir_assign_edit()
        return self.async_show_form(
            step_id="ir_assign",
            data_schema=vol.Schema(
                {
                    vol.Required("remote"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=self._remote_options(),
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_ir_assign_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Befehle und Gruppen des gewählten Senders: nicht angekreuzte Befehle werden ihm entzogen."""
        remote = self._assign_remote
        commands = self._ir_commands()
        errors: dict[str, str] = {}
        placeholders = {"remote": self._remote_name(remote), "commands": ""}
        assigned = [c[IC_ID] for c in commands if remote in (c.get(IC_REMOTES) or [])]
        if user_input is not None:
            selected = set(user_input.get("commands") or [])
            for group in self._ir_groups():
                if group[IG_ID] in (user_input.get("groups") or []):
                    selected |= set(group[IG_COMMANDS])
            updated: list[dict[str, Any]] = []
            missing: list[str] = []
            for command in commands:
                known = list(command.get(IC_REMOTES) or [])
                if command[IC_ID] in selected and remote not in known:
                    resolved = await self._ensure_b64(command)
                    if resolved is None:
                        missing.append(command[IC_NAME])
                        updated.append(command)
                        continue
                    # ältere Befehle: bisherige Sender merken, bei denen der Code unter seinem Namen liegt
                    command = {**resolved, IC_LEARNED: command.get(IC_LEARNED, list(known))}
                    known.append(remote)
                elif command[IC_ID] not in selected and remote in known:
                    known.remove(remote)
                updated.append(
                    {**command, IC_REMOTES: [r for r in self._ir_remotes() if r in known]}
                )
            if missing:
                errors["base"] = "code_unavailable"
                placeholders["commands"] = ", ".join(missing)
                assigned = list(selected & {c[IC_ID] for c in commands})
            else:
                self._save({CONF_IR_COMMANDS: updated})
                return await self.async_step_ir_menu()
        fields: dict[Any, Any] = {
            vol.Optional("commands", default=assigned): self._picker(self._command_options(), True)
        }
        if self._ir_groups():
            fields[vol.Optional("groups")] = self._picker(
                [selector.SelectOptionDict(value=g[IG_ID], label=g[IG_NAME]) for g in self._ir_groups()],
                True,
            )
        return self.async_show_form(
            step_id="ir_assign_edit",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders=placeholders,
        )

    # --- Befehlsgruppen -----------------------------------------------------------------

    async def async_step_ir_groups(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Gruppe wählen oder durch Eintippen eines neuen Namens anlegen."""
        groups = self._ir_groups()
        if user_input is not None:
            value = (user_input["group"] or "").strip()
            known = next((g for g in groups if g[IG_ID] == value), None)
            if known is None and not value:
                return await self.async_step_ir_menu()
            self._group_edit = known or {IG_ID: uuid.uuid4().hex[:8], IG_NAME: value, IG_COMMANDS: []}
            return await self.async_step_ir_group_edit()
        return self.async_show_form(
            step_id="ir_groups",
            data_schema=vol.Schema(
                {
                    vol.Required("group"): self._picker(
                        [selector.SelectOptionDict(value=g[IG_ID], label=g[IG_NAME]) for g in groups],
                        False,
                        custom_value=True,
                    )
                }
            ),
        )

    async def async_step_ir_group_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Befehle der Gruppe festlegen oder die Gruppe löschen."""
        group = self._group_edit
        errors: dict[str, str] = {}
        if user_input is not None:
            others = [g for g in self._ir_groups() if g[IG_ID] != group[IG_ID]]
            if user_input.get("delete"):
                self._save({CONF_IR_GROUPS: others})
                return await self.async_step_ir_menu()
            if not user_input.get("commands"):
                errors["base"] = "group_empty"
            else:
                saved = {**group, IG_COMMANDS: list(user_input["commands"])}
                self._save({CONF_IR_GROUPS: [*others, saved]})
                return await self.async_step_ir_menu()
        return self.async_show_form(
            step_id="ir_group_edit",
            data_schema=vol.Schema(
                {
                    vol.Optional("commands", default=list(group[IG_COMMANDS])): self._picker(
                        self._command_options(), True
                    ),
                    vol.Optional("delete", default=False): bool,
                }
            ),
            errors=errors,
            description_placeholders={"group": group[IG_NAME]},
        )
