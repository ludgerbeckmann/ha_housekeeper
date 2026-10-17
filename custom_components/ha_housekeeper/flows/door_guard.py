"""Dialoge der Funktion Türwächter: eine Konfigurationsseite mit den Grundeinstellungen."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SubentryFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    BLOCK_NOTIFY,
    BLOCK_RETRY,
    CONF_BLOCK_ACTION,
    CONF_CLEAR_RULES,
    CONF_CONTACT,
    CONF_LOCK,
    CONF_LOCK_AWAY,
    CONF_LOCK_AWAY_MINUTES,
    CONF_LOCK_CLOSED,
    CONF_LOCK_ONLY_IF,
    CONF_LOCK_SKIP_IF,
    CONF_LOCK_TIME,
    CONF_MANUAL_OVERRIDE,
    CONF_MANUAL_PAUSE_MINUTES,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    CONF_OPEN_ALERT_MINUTES,
    CONF_OPEN_ALERT_REPEAT,
    CONF_PRESENCE,
    CONF_RETRY_MINUTES,
    CONF_RULES,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_UNLOCK_ARRIVAL,
    CONF_UNLOCK_FREE,
    CONF_UNLOCK_HOME,
    CONF_UNLOCK_ONLY_IF,
    CONF_UNLOCK_SKIP_IF,
    CONF_UNLOCK_WORKDAY,
    CONF_VERIFY_SECONDS,
    CONF_WORKDAY,
    DEFAULT_MANUAL_PAUSE_MINUTES,
    DEFAULT_OPEN_ALERT_MINUTES,
    DEFAULT_OPEN_ALERT_REPEAT,
    DEFAULT_PRESENCE_MINUTES,
    DEFAULT_RETRY_MINUTES,
    DEFAULT_VERIFY_SECONDS,
    MANUAL_IGNORE,
    MANUAL_PAUSE,
    clean_instance_name,
    instance_name,
    instance_title,
)
from .common import (
    _flatten_sections,
    _notify_fields,
    _number,
    _select,
    _suggest,
    _validate_notify,
    _with_cleared,
)

SECTION_DOOR = "door"
SECTION_CHECKS = "checks"
SECTION_UNLOCK = "unlock"
SECTION_LOCK = "lock"
SECTION_NOTIFICATIONS = "notifications"
SECTION_LEGACY = "legacy"

_CONDITION_DOMAINS = [
    "binary_sensor",
    "input_boolean",
    "calendar",
    "schedule",
    "person",
    "device_tracker",
    "zone",
]

# Felder der Grundeinstellungen, die beim Leeren explizit auf None gesetzt werden müssen
_CLEARABLE = (
    CONF_WORKDAY,
    CONF_UNLOCK_WORKDAY,
    CONF_UNLOCK_FREE,
    CONF_UNLOCK_ONLY_IF,
    CONF_UNLOCK_SKIP_IF,
    CONF_LOCK_TIME,
    CONF_LOCK_ONLY_IF,
    CONF_LOCK_SKIP_IF,
    CONF_MOBILE_TARGETS,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
)


def _condition_selector() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=_CONDITION_DOMAINS, multiple=True)
    )


def _dg_schema(
    hass: HomeAssistant,
    defaults: dict[str, Any],
    with_name: bool,
    with_legacy: bool = False,
) -> vol.Schema:
    """Die Seite: Tür, Prüfungen, Aufschließen, Abschließen, Benachrichtigungen (nur „Tür“ ist offen)."""

    def _section(fields: dict[Any, Any], collapsed: bool = True) -> Any:
        return section(vol.Schema(fields), {"collapsed": collapsed})

    door: dict[Any, Any] = {}
    if with_name:
        door[vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults))] = str
    door[vol.Required(CONF_LOCK, description=_suggest(CONF_LOCK, defaults))] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="lock"))
    )
    door[vol.Optional(CONF_CONTACT, description=_suggest(CONF_CONTACT, defaults))] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor"))
    )
    door[vol.Optional(CONF_PRESENCE, description=_suggest(CONF_PRESENCE, defaults))] = (
        selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["person", "device_tracker"], multiple=True)
        )
    )
    door[vol.Optional(CONF_WORKDAY, description=_suggest(CONF_WORKDAY, defaults))] = (
        selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor"))
    )

    checks: dict[Any, Any] = {
        vol.Required(
            CONF_BLOCK_ACTION, default=defaults.get(CONF_BLOCK_ACTION, BLOCK_NOTIFY)
        ): _select([BLOCK_NOTIFY, BLOCK_RETRY], CONF_BLOCK_ACTION),
        vol.Required(
            CONF_RETRY_MINUTES, default=defaults.get(CONF_RETRY_MINUTES, DEFAULT_RETRY_MINUTES)
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
            CONF_VERIFY_SECONDS, default=defaults.get(CONF_VERIFY_SECONDS, DEFAULT_VERIFY_SECONDS)
        ): _number(0, 600, "s"),
        vol.Required(
            CONF_MANUAL_OVERRIDE, default=defaults.get(CONF_MANUAL_OVERRIDE, MANUAL_IGNORE)
        ): _select([MANUAL_IGNORE, MANUAL_PAUSE], CONF_MANUAL_OVERRIDE),
        vol.Required(
            CONF_MANUAL_PAUSE_MINUTES,
            default=defaults.get(CONF_MANUAL_PAUSE_MINUTES, DEFAULT_MANUAL_PAUSE_MINUTES),
        ): _number(1, 1440, "min"),
    }

    def _optional(key: str, kind: Any) -> tuple[Any, Any]:
        return vol.Optional(key, description=_suggest(key, defaults)), kind

    unlock = dict(
        [
            _optional(CONF_UNLOCK_WORKDAY, selector.TimeSelector()),
            _optional(CONF_UNLOCK_FREE, selector.TimeSelector()),
        ]
    )
    unlock[vol.Required(CONF_UNLOCK_HOME, default=bool(defaults.get(CONF_UNLOCK_HOME, False)))] = bool
    unlock[
        vol.Required(CONF_UNLOCK_ARRIVAL, default=bool(defaults.get(CONF_UNLOCK_ARRIVAL, False)))
    ] = bool
    unlock.update(
        dict(
            [
                _optional(CONF_UNLOCK_ONLY_IF, _condition_selector()),
                _optional(CONF_UNLOCK_SKIP_IF, _condition_selector()),
            ]
        )
    )

    lock = dict([_optional(CONF_LOCK_TIME, selector.TimeSelector())])
    lock[vol.Required(CONF_LOCK_AWAY, default=bool(defaults.get(CONF_LOCK_AWAY, False)))] = bool
    lock[
        vol.Required(
            CONF_LOCK_AWAY_MINUTES,
            default=defaults.get(CONF_LOCK_AWAY_MINUTES, DEFAULT_PRESENCE_MINUTES),
        )
    ] = _number(0, 1440, "min")
    lock[
        vol.Required(CONF_LOCK_CLOSED, default=defaults.get(CONF_LOCK_CLOSED, 0) or 0)
    ] = _number(0, 3600, "s")
    lock.update(
        dict(
            [
                _optional(CONF_LOCK_ONLY_IF, _condition_selector()),
                _optional(CONF_LOCK_SKIP_IF, _condition_selector()),
            ]
        )
    )

    sections: dict[Any, Any] = {
        vol.Required(SECTION_DOOR): _section(door, collapsed=False),
        vol.Required(SECTION_UNLOCK): _section(unlock),
        vol.Required(SECTION_LOCK): _section(lock),
        vol.Required(SECTION_CHECKS): _section(checks),
        vol.Required(SECTION_NOTIFICATIONS): _section(
            _notify_fields(hass, defaults, with_action=False)
        ),
    }
    if with_legacy:
        sections[vol.Required(SECTION_LEGACY)] = _section(
            {vol.Required(CONF_CLEAR_RULES, default=False): bool}
        )
    return vol.Schema(sections)


def _validate_dg(user_input: dict[str, Any]) -> dict[str, str]:
    """Prüfung der Seite (die Fehler stehen als Schlüssel in den Übersetzungen)."""
    errors = _validate_notify(user_input, require_method=False)
    if errors:
        return errors
    if float(user_input.get(CONF_OPEN_ALERT_MINUTES) or 0) > 0 and not user_input.get(CONF_CONTACT):
        return {"base": "alert_needs_contact"}
    if float(user_input.get(CONF_LOCK_CLOSED) or 0) > 0 and not user_input.get(CONF_CONTACT):
        return {"base": "no_contact"}
    needs_presence = (
        user_input.get(CONF_UNLOCK_HOME)
        or user_input.get(CONF_UNLOCK_ARRIVAL)
        or user_input.get(CONF_LOCK_AWAY)
    )
    if needs_presence and not user_input.get(CONF_PRESENCE):
        return {"base": "no_presence_entities"}
    if user_input.get(CONF_UNLOCK_FREE) and not user_input.get(CONF_WORKDAY):
        return {"base": "no_workday_sensor"}
    return {}


def dg_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern: geleerte optionale Felder auf None, ältere Regeln nur auf Wunsch löschen."""
    data = {**_with_cleared(flat), **{key: None for key in _CLEARABLE if key not in flat}}
    data.pop(CONF_NAME, None)
    for key in (CONF_LOCK_CLOSED,):
        data[key] = int(data.get(key) or 0)
    if data.pop(CONF_CLEAR_RULES, False):
        data[CONF_RULES] = None
    return data


def new_instance_data(flat: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dg_data(flat).items() if value is not None}


class DoorGuardOptions:
    """Konfigurationsseite des Türwächters (kein Menü, der Name ist ein Feld)."""

    def _legacy_rules(self) -> list[dict[str, Any]]:
        return list(self._current.get(CONF_RULES) or [])

    async def async_step_door_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_dg(flat)
            if not errors:
                name = (flat.get(CONF_NAME) or "").strip()
                self.hass.config_entries.async_update_subentry(
                    self._get_entry(),
                    subentry,
                    title=instance_title(
                        self.hass, self.function_type, clean_instance_name(self.function_type, name)
                    ),
                    data={**subentry.data, **dg_data(flat)},
                )
                return self.async_abort(reason="reconfigure_successful")
            defaults = {**defaults, **flat}
        legacy = self._legacy_rules()
        return self.async_show_form(
            step_id="door_settings",
            data_schema=_dg_schema(
                self.hass, defaults, with_name=True, with_legacy=bool(legacy)
            ),
            errors=errors,
            description_placeholders={"legacy": str(len(legacy))},
        )
