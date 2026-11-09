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
    CONF_IR_AUTO,
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
    DEFAULT_IA_OFF_DELAY,
    DEFAULT_IR_DELAY,
    DEFAULT_IR_REPEATS,
    IA_LATEST_OFF,
    IA_LIGHTS,
    IA_OFF_DELAY,
    IA_OFFSET,
    IC_B64,
    IC_CODE,
    IC_ENABLED,
    IC_ID,
    IC_LEARNED,
    IC_NAME,
    IC_REMOTES,
    IC_TYPE,
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
SECTION_SENDER = "sender_"
SF_COMMANDS = "commands"       # Befehle eines Senders (im Abschnitt „Sender n“)
SF_ALL = "all_commands"        # alle Befehle diesem Sender zuordnen


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


SENDER_SLOTS = 4


def _ir_settings_schema(
    hass: HomeAssistant,
    defaults: dict[str, Any],
    commands: list[dict[str, Any]],
    remotes: list[str],
    sender_defaults: dict[str, dict[str, Any]],
) -> vol.Schema:
    """Die Seite: Allgemein (offen), Befehle, Schalter, je Sender ein Abschnitt (Befehle und Automatik), Benachrichtigung."""

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
    sections: dict[Any, Any] = {
        vol.Required(SECTION_GENERAL): _section(general, collapsed=False),
        vol.Required(SECTION_COMMANDS): _section(command_fields),
        vol.Required(SECTION_SWITCH): _section(switch_fields),
    }
    for index, remote in enumerate(remotes[:SENDER_SLOTS], start=1):
        mine = sender_defaults.get(remote, {})
        assigned = mine.get(SF_COMMANDS)
        if assigned is None:
            assigned = [c[IC_ID] for c in commands if remote in (c.get(IC_REMOTES) or [])]
        sections[vol.Required(f"{SECTION_SENDER}{index}")] = _section(
            {
                vol.Optional(SF_COMMANDS, default=assigned): _picker(True),
                vol.Required(SF_ALL, default=False): bool,
                vol.Optional(IA_LIGHTS, description=_suggest(IA_LIGHTS, mine)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["light", "switch"], multiple=True)
                ),
                vol.Required(IA_OFFSET, default=mine.get(IA_OFFSET, 0)): _number(-240, 240, "min"),
                vol.Required(
                    IA_OFF_DELAY, default=mine.get(IA_OFF_DELAY, DEFAULT_IA_OFF_DELAY)
                ): _number(0, 120, "min"),
                vol.Optional(IA_LATEST_OFF, description=_suggest(IA_LATEST_OFF, mine)): (
                    selector.TimeSelector()
                ),
            }
        )
    sections[vol.Required(SECTION_NOTIFICATIONS)] = _section(
        _notify_fields(hass, {**_POOL_NOTIFY_DEFAULTS, **defaults}, with_action=False)
    )
    return vol.Schema(sections)


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
        return await self._menu(
            "ir_menu",
            ["ir_settings", "add_ir_command", "import_ir_commands"],
            user_input,
            {"commands": self._ir_listing()},
        )

    def _senders_text(self) -> str:
        remotes = self._ir_remotes()[:SENDER_SLOTS]
        return "\n".join(f"Sender {i} = {self._remote_name(r)}" for i, r in enumerate(remotes, 1)) or "–"

    async def _apply_senders(
        self, commands: list[dict[str, Any]], sender_inputs: dict[str, dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
        """Befehle den Sendern zuordnen (Code wird gelesen) und die Automatik je Sender übernehmen."""
        remotes = self._ir_remotes()
        rules = dict(self._current.get(CONF_IR_AUTO) or {})
        missing: list[str] = []
        for index, remote in enumerate(remotes[:SENDER_SLOTS], start=1):
            form = sender_inputs.get(f"{SECTION_SENDER}{index}")
            if form is None:
                continue
            selected = (
                {c[IC_ID] for c in commands}
                if form.get(SF_ALL)
                else set(form.get(SF_COMMANDS) or [])
            )
            updated: list[dict[str, Any]] = []
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
                updated.append({**command, IC_REMOTES: [r for r in remotes if r in known]})
            commands = updated
            if lights := list(form.get(IA_LIGHTS) or []):
                rules[remote] = {
                    IA_LIGHTS: lights,
                    IA_OFFSET: int(form.get(IA_OFFSET) or 0),
                    IA_OFF_DELAY: int(form.get(IA_OFF_DELAY, DEFAULT_IA_OFF_DELAY) or 0),
                    IA_LATEST_OFF: form.get(IA_LATEST_OFF) or None,
                }
            else:
                rules.pop(remote, None)
        return commands, rules, missing

    async def async_step_ir_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Alle Einstellungen auf einer Seite: Name, Sender, Befehle, Schalter, je Sender Befehle und Automatik, Meldungen."""
        errors: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        commands = self._ir_commands()
        sender_defaults: dict[str, dict[str, Any]] = {
            remote: dict(rule) for remote, rule in (self._current.get(CONF_IR_AUTO) or {}).items()
        }
        placeholders = {"senders": self._senders_text(), "commands": ""}
        if user_input is not None:
            user_input = dict(user_input)
            sender_inputs = {
                key: user_input.pop(key) for key in list(user_input) if key.startswith(SECTION_SENDER)
            }
            flat = _flatten_sections(user_input)
            errors = _validate_ir(flat, with_device=False)
            active = set(flat.pop(CONF_IR_ACTIVE, None) or [])
            delete = set(flat.pop(CONF_IR_DELETE, None) or [])
            delete_codes = bool(flat.pop(CONF_IR_DELETE_CODES, True))
            on, off = flat.get(CONF_IR_ON), flat.get(CONF_IR_OFF)
            if not errors:
                if len(flat[CONF_REMOTES]) > SENDER_SLOTS:
                    errors["base"] = "too_many_remotes"
                elif bool(on) != bool(off):
                    errors["base"] = "switch_incomplete"
                elif on and on == off:
                    errors["base"] = "switch_same"
                elif {on, off} & delete:
                    errors["base"] = "command_in_use"
                elif not (on and off) and any(f.get(IA_LIGHTS) for f in sender_inputs.values()):
                    errors["base"] = "auto_needs_switch"
            kept: list[dict[str, Any]] = []
            rules: dict[str, Any] = {}
            if not errors:
                kept = [
                    {**c, IC_ENABLED: c[IC_ID] in active} for c in commands if c[IC_ID] not in delete
                ]
                kept, rules, missing = await self._apply_senders(kept, sender_inputs)
                if missing:
                    errors["base"] = "code_unavailable"
                    placeholders["commands"] = ", ".join(missing)
            if not errors:
                for command in commands:
                    if command[IC_ID] in delete and delete_codes:
                        learned = command.get(IC_LEARNED)
                        for remote in (command.get(IC_REMOTES) or []) if learned is None else learned:
                            await ir_remote.async_delete(
                                self.hass, remote, self._current[CONF_IR_DEVICE], command[IC_CODE]
                            )
                name = (flat.pop(CONF_NAME, None) or "").strip()
                data = {
                    **ir_data(flat),
                    CONF_IR_COMMANDS: kept,
                    CONF_IR_ON: on or None,
                    CONF_IR_OFF: off or None,
                    CONF_IR_AUTO: rules,
                    CONF_IR_GROUPS: None,         # frühere Befehlsgruppen gibt es nicht mehr
                }
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
            for index, remote in enumerate(self._ir_remotes()[:SENDER_SLOTS], start=1):
                if form := sender_inputs.get(f"{SECTION_SENDER}{index}"):
                    sender_defaults[remote] = dict(form)
        return self.async_show_form(
            step_id="ir_settings",
            data_schema=_ir_settings_schema(
                self.hass, defaults, commands, self._ir_remotes(), sender_defaults
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    # --- Befehle anlegen und anlernen ---------------------------------------------

    async def async_step_add_ir_command(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Befehl anlernen: vorhandenen wählen (neu anlernen, auch an weiteren Sendern) oder einen neuen Namen eintippen."""
        defaults: dict[str, Any] = {}
        if user_input is not None:
            value = (user_input["command"] or "").strip()
            commands = self._ir_commands()
            code = ir_remote.command_code(value)
            existing = next((c for c in commands if c[IC_ID] == value), None) or next(
                (c for c in commands if c[IC_CODE] == code), None
            )
            if existing is not None:
                return await self._start_learn(existing, user_input["learn_on"], is_new=False)
            command = {
                IC_ID: uuid.uuid4().hex[:8],
                IC_NAME: value,
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
                    vol.Required("command"): self._picker(
                        self._command_options(), False, custom_value=True
                    ),
                    vol.Required(IC_TYPE, default=defaults.get(IC_TYPE, IR_TYPE_IR)): _select(
                        IR_TYPES, "ir_type", mode=selector.SelectSelectorMode.LIST
                    ),
                    **self._learn_on_field(defaults.get("learn_on", self._ir_remotes())),
                }
            ),
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
