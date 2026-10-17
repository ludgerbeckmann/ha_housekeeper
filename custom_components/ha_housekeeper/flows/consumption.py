"""Dialoge der Funktion Verbrauchswächter: eine Konfigurationsseite."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SubentryFlowResult
from homeassistant.helpers import selector

from ..const import (
    CONF_CG_FROM,
    CONF_CG_MINUTES,
    CONF_CG_REPEAT,
    CONF_CG_SENSOR,
    CONF_CG_THRESHOLD,
    CONF_CG_TO,
    CONF_MOBILE_TARGETS,
    CONF_NAME,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    DEFAULT_CG_MINUTES,
    clean_instance_name,
    instance_name,
    instance_title,
)
from .common import (
    _POOL_NOTIFY_DEFAULTS,
    _flatten_sections,
    _notify_fields,
    _number,
    _sections_schema,
    _suggest,
    _validate_notify,
)

_CLEARABLE = (
    CONF_CG_FROM,
    CONF_CG_TO,
    CONF_MOBILE_TARGETS,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
)


def _cg_schema(hass, defaults: dict[str, Any]) -> vol.Schema:
    """Die Seite: Überwachung (Sensor, Schwelle, Dauer, Zeitfenster) und Benachrichtigungen."""
    general: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
        vol.Required(
            CONF_CG_SENSOR, description=_suggest(CONF_CG_SENSOR, defaults)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
        vol.Required(
            CONF_CG_THRESHOLD, description=_suggest(CONF_CG_THRESHOLD, defaults)
        ): _number(0, 1_000_000, step=0.01),
        vol.Required(
            CONF_CG_MINUTES, default=defaults.get(CONF_CG_MINUTES, DEFAULT_CG_MINUTES)
        ): _number(1, 1440, "min"),
        vol.Required(
            CONF_CG_REPEAT, default=defaults.get(CONF_CG_REPEAT, 0)
        ): _number(0, 1440, "min"),
        vol.Optional(
            CONF_CG_FROM, description=_suggest(CONF_CG_FROM, defaults)
        ): selector.TimeSelector(),
        vol.Optional(
            CONF_CG_TO, description=_suggest(CONF_CG_TO, defaults)
        ): selector.TimeSelector(),
    }
    return _sections_schema(
        general,
        _notify_fields(hass, {**_POOL_NOTIFY_DEFAULTS, **defaults}, with_action=False),
    )


def _validate_cg(flat: dict[str, Any]) -> dict[str, str]:
    errors = _validate_notify(flat, require_method=True)
    if bool(flat.get(CONF_CG_FROM)) != bool(flat.get(CONF_CG_TO)):
        errors["base"] = "window_incomplete"
    return errors


def cg_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern; geleerte optionale Felder werden explizit auf None gesetzt."""
    data = {**{key: None for key in _CLEARABLE}, **flat}
    data.pop(CONF_NAME, None)
    data[CONF_CG_MINUTES] = int(data[CONF_CG_MINUTES])
    data[CONF_CG_REPEAT] = int(data[CONF_CG_REPEAT])
    return data


def new_instance_data(flat: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in cg_data(flat).items() if value is not None}


class ConsumptionGuardOptions:
    """Konfigurationsseite des Verbrauchswächters (kein Menü, der Name ist ein Feld)."""

    async def async_step_cg_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_cg(flat)
            if not errors:
                name = (flat.get(CONF_NAME) or "").strip()
                self.hass.config_entries.async_update_subentry(
                    self._get_entry(),
                    subentry,
                    title=instance_title(
                        self.hass, self.function_type, clean_instance_name(self.function_type, name)
                    ),
                    data={**subentry.data, **cg_data(flat)},
                )
                return self.async_abort(reason="reconfigure_successful")
            defaults = {**defaults, **flat}
        return self.async_show_form(
            step_id="cg_settings", data_schema=_cg_schema(self.hass, defaults), errors=errors
        )
