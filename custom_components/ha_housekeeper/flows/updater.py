"""Dialoge der Funktion Home Assistant Updater."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SubentryFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    CONF_CLEAR_RULES,
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    CONF_SCHEDULES,
    CONF_TIMEOUT_MINUTES,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_WINDOW_END,
    CONF_WINDOW_START,
    clean_instance_name,
    instance_name,
    instance_title,
    DEFAULT_TIMEOUT_MINUTES,
    TRIGGER_TIME,
    TRIGGERS,
    WEEKDAYS,
)
from ..updater import (
    GROUP_MODES,
    GROUP_NAMES,
    GROUP_OFF,
    GROUPS,
    NOTIFY_KEYS,
    SYSTEM_COMPONENTS,
    group_key,
)
from .common import (
    SECTION_GENERAL,
    _POOL_NOTIFY_DEFAULTS,
    _flatten_sections,
    _notify_fields,
    _number,
    _select,
    _suggest,
    _validate_notify,
)


def _updater_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    """Eintrag: Name (nur beim Anlegen) und Zeitlimit; Benachrichtigungen je Zeitplan."""
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults))] = str
    fields[
        vol.Required(
            CONF_TIMEOUT_MINUTES,
            default=defaults.get(CONF_TIMEOUT_MINUTES, DEFAULT_TIMEOUT_MINUTES),
        )
    ] = _number(1, 720, "min")
    return vol.Schema(fields)


SECTION_LEGACY = "legacy"
_NOTIFY_CLEARABLE = (CONF_MOBILE_TARGETS, CONF_TTS_ENTITY, CONF_TTS_PLAYER)


def notify_section(group: str) -> str:
    return f"{group}_notify"


def _prefixed(group: str, fields: dict[Any, Any]) -> dict[Any, Any]:
    """Felder der Benachrichtigungswege mit dem Gruppenpräfix versehen (z. B. `system_mobile_enabled`)."""
    return {
        type(marker)(
            group_key(group, marker.schema), default=marker.default, description=marker.description
        ): value
        for marker, value in fields.items()
    }


def _group_fields(group: str, defaults: dict[str, Any]) -> dict[Any, Any]:
    """Aktion, Auslöser und Sicherung einer Gruppe (System und Einzelne Updates mit eigener Auswahl)."""

    def key(field: str) -> str:
        return group_key(group, field)

    fields: dict[Any, Any] = {
        vol.Required(key("mode"), default=defaults.get(key("mode"), GROUP_OFF)): _select(
            GROUP_MODES, "update_group_mode", mode=selector.SelectSelectorMode.LIST
        ),
    }
    if group == "system":
        fields[
            vol.Required(key("components"), default=defaults.get(key("components"), SYSTEM_COMPONENTS))
        ] = _select(
            SYSTEM_COMPONENTS, "update_component", multiple=True, mode=selector.SelectSelectorMode.LIST
        )
    if group == "single":
        fields[vol.Optional(key("targets"), description=_suggest(key("targets"), defaults))] = (
            selector.EntitySelector(selector.EntitySelectorConfig(domain="update", multiple=True))
        )
    fields.update(
        {
            vol.Required(key("trigger"), default=defaults.get(key("trigger"), TRIGGER_TIME)): _select(
                TRIGGERS, "update_trigger", mode=selector.SelectSelectorMode.LIST
            ),
            vol.Optional(
                key("time"), description={"suggested_value": defaults.get(key("time"), "03:00:00")}
            ): selector.TimeSelector(),
            vol.Optional(key("weekdays"), default=defaults.get(key("weekdays"), WEEKDAYS)): _select(
                WEEKDAYS, "weekday", multiple=True, mode=selector.SelectSelectorMode.LIST
            ),
            vol.Required(key("backup"), default=bool(defaults.get(key("backup"), False))): bool,
        }
    )
    return fields


def _updater_settings_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_legacy: bool = False
) -> vol.Schema:
    """Die Seite: Allgemein (offen), je Gruppe ein Abschnitt mit Aktion und einer mit Meldewegen (eingeklappt)."""

    def _section(fields: dict[Any, Any], collapsed: bool = True) -> Any:
        return section(vol.Schema(fields), {"collapsed": collapsed})

    general: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
        vol.Required(
            CONF_TIMEOUT_MINUTES, default=defaults.get(CONF_TIMEOUT_MINUTES, DEFAULT_TIMEOUT_MINUTES)
        ): _number(1, 720, "min"),
        vol.Optional(CONF_WINDOW_START, description=_suggest(CONF_WINDOW_START, defaults)): selector.TimeSelector(),
        vol.Optional(CONF_WINDOW_END, description=_suggest(CONF_WINDOW_END, defaults)): selector.TimeSelector(),
    }
    sections: dict[Any, Any] = {vol.Required(SECTION_GENERAL): _section(general, collapsed=False)}
    for group in GROUPS:
        sections[vol.Required(group)] = _section(_group_fields(group, defaults))
        own = {key: defaults.get(group_key(group, key)) for key in NOTIFY_KEYS}
        notify_defaults = {**_POOL_NOTIFY_DEFAULTS, **{k: v for k, v in own.items() if v is not None}}
        sections[vol.Required(notify_section(group))] = _section(
            _prefixed(group, _notify_fields(hass, notify_defaults, with_action=False))
        )
    if with_legacy:
        sections[vol.Required(SECTION_LEGACY)] = _section({vol.Required(CONF_CLEAR_RULES, default=False): bool})
    return vol.Schema(sections)


def _validate_settings(flat: dict[str, Any], language: str) -> tuple[dict[str, str], dict[str, str]]:
    """Fehler und Platzhalter (Name der Gruppe) für die Einstellungsseite."""
    names = GROUP_NAMES["de" if language.startswith("de") else "en"]
    if bool(flat.get(CONF_WINDOW_START)) != bool(flat.get(CONF_WINDOW_END)) or (
        flat.get(CONF_WINDOW_START) and flat.get(CONF_WINDOW_START) == flat.get(CONF_WINDOW_END)
    ):
        return {"base": "invalid_window"}, {}
    for group in GROUPS:
        def get(field: str, default: Any = None, group: str = group) -> Any:
            return flat.get(group_key(group, field), default)

        if get("mode", GROUP_OFF) == GROUP_OFF:
            continue
        error: str | None = None
        if get("trigger", TRIGGER_TIME) == TRIGGER_TIME:
            if not get("time"):
                error = "group_no_time"
            elif not get("weekdays"):
                error = "group_no_weekday"
        if error is None and group == "system" and not get("components"):
            error = "group_no_update_selected"
        if error is None and group == "single" and not get("targets"):
            error = "group_no_update_selected"
        if error is None:
            own = {key: get(key) for key in NOTIFY_KEYS}
            if own.get(CONF_MOBILE_ENABLED) and not own.get(CONF_MOBILE_TARGETS):
                error = "group_no_targets"
            elif notify := _validate_notify(own, require_method=True):
                error = f"group_{notify['base']}"
        if error:
            return {"base": error}, {"group": names[group]}
    return {}, {}


def settings_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern; geleerte optionale Felder werden explizit auf None gesetzt.

    Die Benachrichtigungseinstellungen des Eintrags bleiben unangetastet (ältere Zeitpläne nutzen sie als Rückfall)."""
    cleared = {group_key(group, key): None for group in GROUPS for key in _NOTIFY_CLEARABLE}
    cleared.update({group_key("single", "targets"): None, CONF_WINDOW_START: None, CONF_WINDOW_END: None})
    data = {**cleared, **flat}
    data.pop(CONF_NAME, None)
    if data.pop(CONF_CLEAR_RULES, False):
        data[CONF_SCHEDULES] = None
    data[CONF_TIMEOUT_MINUTES] = int(data[CONF_TIMEOUT_MINUTES])
    return data


class UpdaterOptions:
    """Konfigurationsseite des Home Assistant Updaters (kein Menü, der Name ist ein Feld)."""

    async def async_step_upd_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors, placeholders = _validate_settings(flat, self.hass.config.language or "")
            if not errors:
                name = (flat.get(CONF_NAME) or "").strip()
                self.hass.config_entries.async_update_subentry(
                    self._get_entry(),
                    subentry,
                    title=instance_title(
                        self.hass, self.function_type, clean_instance_name(self.function_type, name)
                    ),
                    data={**subentry.data, **settings_data(flat)},
                )
                return self.async_abort(reason="reconfigure_successful")
            defaults = {**defaults, **flat}
        return self.async_show_form(
            step_id="upd_settings",
            data_schema=_updater_settings_schema(
                self.hass, defaults, with_legacy=bool(self._current.get(CONF_SCHEDULES))
            ),
            errors=errors,
            description_placeholders=placeholders or None,
        )
