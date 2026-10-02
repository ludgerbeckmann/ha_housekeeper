"""Dialoge der Funktion Integrationsmonitor."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    CONF_CHECK_MINUTES,
    CONF_EXCLUDED,
    CONF_GRACE_MINUTES,
    CONF_MIN_ENTITIES,
    CONF_MOBILE_TARGETS,
    CONF_MONITOR_RULES,
    CONF_NAME,
    CONF_NOTIFY_ALL,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    DEFAULT_CHECK_MINUTES,
    DEFAULT_GRACE_MINUTES,
    DEFAULT_MIN_ENTITIES,
    DOMAIN,
    FUNCTION_MONITOR,
    M_ACTION,
    M_ENABLED,
    M_ENTRIES,
    M_ID,
    M_NAME,
    M_NOTIFY,
    M_ON_ERROR,
    M_ON_UNAVAILABLE,
    M_PRESENCE,
    M_REENABLE,
    MON_ACTION_DISABLE,
    MON_ACTION_NONE,
    MON_ACTIONS,
    function_title,
)
from .common import (
    SECTION_GENERAL,
    _flatten_sections,
    _notify_fields,
    _number,
    _select,
    _sections_schema,
    _suggest,
    _validate_notify,
)

_NOTIFY_CLEARABLE = (CONF_MOBILE_TARGETS, CONF_TTS_ENTITY, CONF_TTS_PLAYER)


def _entry_options(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Alle Integrationen (Config-Entries) außer dieser, sortiert nach Titel."""
    entries = sorted(
        (e for e in hass.config_entries.async_entries() if e.domain != DOMAIN),
        key=lambda e: (e.title.casefold(), e.domain),
    )
    return [
        selector.SelectOptionDict(value=e.entry_id, label=f"{e.title} ({e.domain})")
        for e in entries
    ]


def _entry_selector(hass: HomeAssistant) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=_entry_options(hass),
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _monitor_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    """Eintrag: Name (nur beim Anlegen), Prüfung, Ausschlüsse und Benachrichtigung."""
    general: dict[Any, Any] = {}
    if with_name:
        general[
            vol.Required(
                CONF_NAME,
                default=defaults.get(CONF_NAME, function_title(hass, FUNCTION_MONITOR)),
            )
        ] = str
    general.update(
        {
            vol.Required(
                CONF_GRACE_MINUTES,
                default=defaults.get(CONF_GRACE_MINUTES, DEFAULT_GRACE_MINUTES),
            ): _number(0, 1440, "min"),
            vol.Required(
                CONF_MIN_ENTITIES,
                default=defaults.get(CONF_MIN_ENTITIES, DEFAULT_MIN_ENTITIES),
            ): _number(1, 100),
            vol.Required(
                CONF_CHECK_MINUTES,
                default=defaults.get(CONF_CHECK_MINUTES, DEFAULT_CHECK_MINUTES),
            ): _number(1, 60, "min"),
            vol.Required(
                CONF_NOTIFY_ALL, default=defaults.get(CONF_NOTIFY_ALL, True)
            ): bool,
            vol.Optional(
                CONF_EXCLUDED, default=defaults.get(CONF_EXCLUDED) or []
            ): _entry_selector(hass),
        }
    )
    return _sections_schema(
        general, _notify_fields(hass, defaults, with_action=False)
    )


def _validate_monitor(flat: dict[str, Any]) -> dict[str, str]:
    return _validate_notify(flat, require_method=bool(flat.get(CONF_NOTIFY_ALL)))


def monitor_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern; geleerte Benachrichtigungsfelder werden explizit auf None gesetzt."""
    return {**{key: None for key in _NOTIFY_CLEARABLE}, **flat}


def rule_summary(hass: HomeAssistant, rule: dict[str, Any]) -> str:
    """Kurzbeschreibung einer Regel für die Auswahllisten."""
    names = {o["value"]: o["label"] for o in _entry_options(hass)}
    entries = [names.get(e, e) for e in rule.get(M_ENTRIES) or []]
    off = "" if rule.get(M_ENABLED, True) else " (aus)"
    return f"{rule.get(M_NAME)}: {', '.join(entries)} → {rule.get(M_ACTION, MON_ACTION_NONE)}{off}"


class MonitorOptions:
    """Options-Flow-Schritte: Integrationsmonitor."""

    def _monitor_rules(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_MONITOR_RULES) or [])

    async def async_step_mon_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["mon_general", "add_monitor_rule"]
        if self._monitor_rules():
            options += ["edit_monitor_rule", "delete_monitor_rule"]
        options.append("rename")
        return await self._menu("mon_menu", options, user_input)

    async def async_step_mon_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_monitor(flat)
            if not errors:
                self._save(monitor_data(flat))
                return await self.async_step_mon_menu()
            defaults = flat
        return self.async_show_form(
            step_id="mon_general",
            data_schema=_monitor_schema(self.hass, defaults, with_name=False),
            errors=errors,
        )

    async def async_step_add_monitor_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._edit_id = None
        self._draft = {}
        return await self.async_step_monitor_rule_edit()

    async def async_step_edit_monitor_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            rule = next(r for r in self._monitor_rules() if r[M_ID] == user_input["rule"])
            self._edit_id = rule[M_ID]
            self._draft = dict(rule)
            return await self.async_step_monitor_rule_edit()
        return self.async_show_form(
            step_id="edit_monitor_rule", data_schema=self._monitor_rule_picker()
        )

    async def async_step_delete_monitor_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._save(
                {
                    CONF_MONITOR_RULES: [
                        r for r in self._monitor_rules() if r[M_ID] != user_input["rule"]
                    ]
                }
            )
            return await self.async_step_mon_menu()
        return self.async_show_form(
            step_id="delete_monitor_rule", data_schema=self._monitor_rule_picker()
        )

    def _monitor_rule_picker(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("rule"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=r[M_ID], label=rule_summary(self.hass, r)
                            )
                            for r in self._monitor_rules()
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    def _has_notify_method(self) -> bool:
        """Ist im Eintrag mindestens ein Meldeweg eingerichtet?"""
        return not _validate_notify(self._current, True)

    async def async_step_monitor_rule_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self._draft
        if user_input is not None:
            flat = _flatten_sections(user_input)
            if not flat.get(M_ENTRIES):
                errors["base"] = "no_integration"
            elif not (flat.get(M_ON_ERROR) or flat.get(M_ON_UNAVAILABLE)):
                errors["base"] = "no_condition"
            elif flat[M_ACTION] == MON_ACTION_NONE and not flat.get(M_NOTIFY):
                errors["base"] = "nothing_to_do"
            elif flat.get(M_REENABLE) and not flat.get(M_PRESENCE):
                errors["base"] = "no_presence"
            elif flat.get(M_REENABLE) and flat[M_ACTION] != MON_ACTION_DISABLE:
                errors["base"] = "reenable_needs_disable"
            elif flat.get(M_NOTIFY) and not self._has_notify_method():
                errors["base"] = "no_method"
            if not errors:
                rule = {
                    M_ID: self._edit_id or uuid.uuid4().hex[:8],
                    M_NAME: flat[M_NAME],
                    M_ENABLED: flat.get(M_ENABLED, True),
                    M_ENTRIES: flat[M_ENTRIES],
                    M_ON_ERROR: flat.get(M_ON_ERROR, True),
                    M_ON_UNAVAILABLE: flat.get(M_ON_UNAVAILABLE, True),
                    M_ACTION: flat[M_ACTION],
                    M_NOTIFY: flat.get(M_NOTIFY, False),
                    M_PRESENCE: flat.get(M_PRESENCE) or None,
                    M_REENABLE: flat.get(M_REENABLE, False),
                }
                rules = self._monitor_rules()
                if self._edit_id:
                    rules = [rule if r[M_ID] == self._edit_id else r for r in rules]
                else:
                    rules.append(rule)
                self._save({CONF_MONITOR_RULES: rules})
                return await self.async_step_mon_menu()
            d = flat
        general: dict[Any, Any] = {
            vol.Required(M_NAME, description=_suggest(M_NAME, d)): str,
            vol.Required(M_ENABLED, default=d.get(M_ENABLED, True)): bool,
        }
        condition: dict[Any, Any] = {
            vol.Required(
                M_ENTRIES, default=d.get(M_ENTRIES) or []
            ): _entry_selector(self.hass),
            vol.Required(M_ON_ERROR, default=d.get(M_ON_ERROR, True)): bool,
            vol.Required(M_ON_UNAVAILABLE, default=d.get(M_ON_UNAVAILABLE, True)): bool,
        }
        action: dict[Any, Any] = {
            vol.Required(M_ACTION, default=d.get(M_ACTION, MON_ACTION_NONE)): _select(
                MON_ACTIONS, "monitor_action", mode=selector.SelectSelectorMode.LIST
            ),
            vol.Required(M_NOTIFY, default=d.get(M_NOTIFY, True)): bool,
            vol.Optional(
                M_PRESENCE, description=_suggest(M_PRESENCE, d) if d.get(M_PRESENCE) else {}
            ): selector.EntitySelector(),
            vol.Required(M_REENABLE, default=d.get(M_REENABLE, False)): bool,
        }
        return self.async_show_form(
            step_id="monitor_rule_edit",
            data_schema=vol.Schema(
                {
                    vol.Required(SECTION_GENERAL): section(
                        vol.Schema(general), {"collapsed": False}
                    ),
                    vol.Required("condition"): section(
                        vol.Schema(condition), {"collapsed": False}
                    ),
                    vol.Required("action"): section(
                        vol.Schema(action), {"collapsed": False}
                    ),
                }
            ),
            errors=errors,
        )

