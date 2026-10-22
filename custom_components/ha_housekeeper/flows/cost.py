"""Dialoge der Funktion Stromkosten: eine Konfigurationsseite."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SubentryFlowResult
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_COST_FIXED_ENTITY,
    CONF_COST_HISTORY_FROM,
    CONF_COST_FIXED_POWER,
    CONF_COST_PRICE,
    CONF_COST_PRICE_ENTITY,
    CONF_COST_PRICE_UNIT,
    CONF_COST_SCALE,
    CONF_COST_SOURCE,
    CONF_COST_STANDBY,
    CONF_COST_START_COST,
    CONF_COST_START_KWH,
    CONF_NAME,
    COST_PRICE_UNITS,
    clean_instance_name,
    instance_name,
    instance_title,
)
from ..energy_cost import source_kind
from .common import _flatten_sections, _number, _suggest

SECTION_SOURCE = "source"
SECTION_FIXED = "fixed"
SECTION_PRICE = "price"
SECTION_HISTORY = "history"
_CLEARABLE = (
    CONF_COST_SOURCE, CONF_COST_PRICE, CONF_COST_PRICE_ENTITY, CONF_COST_FIXED_ENTITY,
    CONF_COST_START_KWH, CONF_COST_START_COST, CONF_COST_HISTORY_FROM,
)


def _cost_schema(hass, defaults: dict[str, Any]) -> vol.Schema:
    """Die Seite: Gerät (Quelle) und Preis."""
    source: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
        vol.Optional(
            CONF_COST_SOURCE, description=_suggest(CONF_COST_SOURCE, defaults)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
    }
    fixed: dict[Any, Any] = {
        vol.Optional(
            CONF_COST_FIXED_ENTITY, description=_suggest(CONF_COST_FIXED_ENTITY, defaults)
        ): selector.EntitySelector(),
        vol.Optional(CONF_COST_FIXED_POWER, description=_suggest(CONF_COST_FIXED_POWER, defaults)): _number(
            0, 100000, "W", step=0.1
        ),
        vol.Required(CONF_COST_STANDBY, default=defaults.get(CONF_COST_STANDBY) or 0): _number(
            0, 100000, "W", step=0.1
        ),
        vol.Required(CONF_COST_SCALE, default=bool(defaults.get(CONF_COST_SCALE, False))): bool,
    }
    price: dict[Any, Any] = {
        vol.Optional(CONF_COST_PRICE, description=_suggest(CONF_COST_PRICE, defaults)): _number(
            0, 1000, "ct/kWh", step=0.01
        ),
        vol.Optional(
            CONF_COST_PRICE_ENTITY, description=_suggest(CONF_COST_PRICE_ENTITY, defaults)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "input_number", "number"])),
        vol.Required(
            CONF_COST_PRICE_UNIT, default=defaults.get(CONF_COST_PRICE_UNIT) or "eur"
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=COST_PRICE_UNITS,
                translation_key=CONF_COST_PRICE_UNIT,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    }
    history: dict[Any, Any] = {
        vol.Optional(
            CONF_COST_HISTORY_FROM, description=_suggest(CONF_COST_HISTORY_FROM, defaults)
        ): selector.DateSelector(),
        vol.Optional(CONF_COST_START_KWH, description=_suggest(CONF_COST_START_KWH, defaults)): _number(
            0, 10_000_000, "kWh", step=0.001
        ),
        vol.Optional(CONF_COST_START_COST, description=_suggest(CONF_COST_START_COST, defaults)): _number(
            0, 10_000_000, step=0.01
        ),
    }
    return vol.Schema(
        {
            vol.Required(SECTION_SOURCE): section(vol.Schema(source), {"collapsed": False}),
            vol.Required(SECTION_FIXED): section(vol.Schema(fixed), {"collapsed": False}),
            vol.Required(SECTION_PRICE): section(vol.Schema(price), {"collapsed": False}),
            vol.Required(SECTION_HISTORY): section(vol.Schema(history), {"collapsed": True}),
        }
    )


def _validate_cost(hass, flat: dict[str, Any]) -> dict[str, str]:
    measured, fixed = bool(flat.get(CONF_COST_SOURCE)), bool(flat.get(CONF_COST_FIXED_ENTITY))
    if measured == fixed:                      # genau eines von beiden
        return {"base": "source_or_fixed"}
    if fixed and flat.get(CONF_COST_HISTORY_FROM):
        return {"base": "history_needs_source"}
    if flat.get(CONF_COST_HISTORY_FROM) and flat[CONF_COST_HISTORY_FROM] > dt_util.now().strftime("%Y-%m-%d"):
        return {"base": "history_in_future"}
    if fixed and float(flat.get(CONF_COST_FIXED_POWER) or 0) <= 0:
        return {"base": "no_power"}
    if flat.get(CONF_COST_PRICE) is None and not flat.get(CONF_COST_PRICE_ENTITY):
        return {"base": "no_price"}
    state = hass.states.get(flat.get(CONF_COST_SOURCE) or "")
    if state is not None and source_kind(state.attributes.get("unit_of_measurement")) is None:
        return {"base": "unsupported_unit"}
    return {}


def cost_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern; geleerte optionale Felder werden explizit auf None gesetzt."""
    data = {**{key: None for key in _CLEARABLE}, **flat}
    data.pop(CONF_NAME, None)
    return data


def new_instance_data(flat: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in cost_data(flat).items() if value is not None}


class EnergyCostOptions:
    """Konfigurationsseite der Stromkosten (kein Menü, der Name ist ein Feld)."""

    async def async_step_ec_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_cost(self.hass, flat)
            if not errors:
                name = (flat.get(CONF_NAME) or "").strip()
                self.hass.config_entries.async_update_subentry(
                    self._get_entry(),
                    subentry,
                    title=instance_title(
                        self.hass, self.function_type, clean_instance_name(self.function_type, name)
                    ),
                    data={**subentry.data, **cost_data(flat)},
                )
                return self.async_abort(reason="reconfigure_successful")
            defaults = {**defaults, **flat}
        return self.async_show_form(
            step_id="ec_settings", data_schema=_cost_schema(self.hass, defaults), errors=errors
        )
