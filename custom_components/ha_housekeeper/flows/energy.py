"""Dialoge der Funktion Energiemonitor: eine Konfigurationsseite."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SubentryFlowResult
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    CONF_EM_BASE_FEE,
    CONF_EM_BASE_SHARE,
    CONF_EM_AREA_A,
    CONF_EM_AREA_B,
    CONF_EM_FEED,
    CONF_EM_GAS,
    CONF_EM_GAS_FEE,
    CONF_EM_GAS_KEY,
    CONF_EM_GAS_PRICE,
    CONF_EM_GRID,
    CONF_EM_METER_A,
    CONF_EM_METER_B,
    CONF_EM_NAME_A,
    CONF_EM_NAME_B,
    CONF_EM_PERSONS_A,
    CONF_EM_PERSONS_B,
    CONF_EM_PRICE,
    CONF_EM_PV,
    CONF_EM_PV_PRICE,
    CONF_EM_WATER,
    CONF_EM_WATER_FEE,
    CONF_EM_WATER_PRICE,
    CONF_NAME,
    DEFAULT_EM_BASE_SHARE,
    DEFAULT_EM_NAME_A,
    DEFAULT_EM_NAME_B,
    DEFAULT_EM_PERSONS,
    EM_GAS_KEYS,
    EM_PV_PRICES,
    clean_instance_name,
    instance_name,
    instance_title,
)
from .common import _flatten_sections, _number, _suggest

SECTION_METERS = "meters"
SECTION_UNITS = "units"
SECTION_PRICES = "prices"
SECTION_WATER = "water"
SECTION_GAS = "gas"

_SOURCES = (CONF_EM_GRID, CONF_EM_FEED, CONF_EM_PV, CONF_EM_METER_A, CONF_EM_METER_B)

_OPTIONAL = (  # Zähler und Preise von Wasser und Gas
    CONF_EM_WATER, CONF_EM_WATER_PRICE, CONF_EM_WATER_FEE,
    CONF_EM_GAS, CONF_EM_GAS_PRICE, CONF_EM_GAS_FEE,
)

_PV_PRICE_LABELS = {
    "de": {
        "0": "0 ct – kostenlos",
        "8.17": "8,17 ct – Eigenverbrauchsvergütung",
        "16.26": "16,26 ct – entgangener Erlös (Einspeisung abzüglich Eigenverbrauchsvergütung)",
        "24.43": "24,43 ct – volle Einspeisevergütung",
    },
    "en": {
        "0": "0 ct – free",
        "8.17": "8.17 ct – self-consumption tariff",
        "16.26": "16.26 ct – lost revenue (feed-in minus self-consumption tariff)",
        "24.43": "24.43 ct – full feed-in tariff",
    },
}


def pv_price_value(raw: Any) -> float | None:
    """Preis je PV-kWh aus Auswahl oder Eingabe („16,26“ oder „16.26“); `None`, wenn ungültig."""
    try:
        value = float(str(raw).strip().replace(",", "."))
    except ValueError:
        return None
    return value if value >= 0 else None


def _em_schema(language: str, defaults: dict[str, Any]) -> vol.Schema:
    """Die Seite: Zähler, Einheiten und Preise (nur „Zähler“ ist aufgeklappt)."""

    def _section(fields: dict[Any, Any], collapsed: bool = True) -> Any:
        return section(vol.Schema(fields), {"collapsed": collapsed})

    sensor = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    meters: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
    }
    for key in _SOURCES:
        meters[vol.Required(key, description=_suggest(key, defaults))] = sensor
    units = {
        vol.Required(CONF_EM_NAME_A, default=defaults.get(CONF_EM_NAME_A, DEFAULT_EM_NAME_A)): str,
        vol.Required(CONF_EM_NAME_B, default=defaults.get(CONF_EM_NAME_B, DEFAULT_EM_NAME_B)): str,
        vol.Required(
            CONF_EM_PERSONS_A, default=defaults.get(CONF_EM_PERSONS_A, DEFAULT_EM_PERSONS)
        ): _number(0, 20),
        vol.Required(
            CONF_EM_PERSONS_B, default=defaults.get(CONF_EM_PERSONS_B, DEFAULT_EM_PERSONS)
        ): _number(0, 20),
        vol.Required(CONF_EM_AREA_A, default=defaults.get(CONF_EM_AREA_A) or 0): _number(0, 1000, "m²"),
        vol.Required(CONF_EM_AREA_B, default=defaults.get(CONF_EM_AREA_B) or 0): _number(0, 1000, "m²"),
    }

    def _utility(meter: str, price: str, fee: str) -> dict[Any, Any]:
        return {
            vol.Optional(meter, description=_suggest(meter, defaults)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(price, default=defaults.get(price) or 0): _number(0, 100, "€/m³", step=0.001),
            vol.Required(fee, default=defaults.get(fee) or 0): _number(0, 1000, "€", step=0.01),
        }

    labels = _PV_PRICE_LABELS["de" if language.startswith("de") else "en"]
    pv_default = defaults.get(CONF_EM_PV_PRICE)
    pv_value = pv_price_value(pv_default)
    pv_text = "0" if pv_default is None else (f"{pv_value:g}" if pv_value is not None else str(pv_default))
    prices = {
        vol.Required(CONF_EM_PRICE, description=_suggest(CONF_EM_PRICE, defaults)): _number(
            0, 200, "ct/kWh", step=0.01
        ),
        vol.Required(
            CONF_EM_PV_PRICE, default=pv_text
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value=value, label=labels[value])
                    for value in EM_PV_PRICES
                ],
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(CONF_EM_BASE_FEE, default=defaults.get(CONF_EM_BASE_FEE, 0)): _number(
            0, 1000, "€", step=0.01
        ),
        vol.Required(
            CONF_EM_BASE_SHARE, default=defaults.get(CONF_EM_BASE_SHARE, DEFAULT_EM_BASE_SHARE)
        ): _number(0, 100, "%"),
    }
    gas = _utility(CONF_EM_GAS, CONF_EM_GAS_PRICE, CONF_EM_GAS_FEE)
    gas[vol.Required(CONF_EM_GAS_KEY, default=defaults.get(CONF_EM_GAS_KEY, "area"))] = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=EM_GAS_KEYS,
            translation_key=CONF_EM_GAS_KEY,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )
    return vol.Schema(
        {
            vol.Required(SECTION_METERS): _section(meters, collapsed=False),
            vol.Required(SECTION_UNITS): _section(units),
            vol.Required(SECTION_PRICES): _section(prices),
            vol.Required(SECTION_WATER): _section(_utility(CONF_EM_WATER, CONF_EM_WATER_PRICE, CONF_EM_WATER_FEE)),
            vol.Required(SECTION_GAS): _section(gas),
        }
    )


def _validate_em(flat: dict[str, Any]) -> dict[str, str]:
    chosen = [flat.get(key) for key in (*_SOURCES, CONF_EM_WATER, CONF_EM_GAS) if flat.get(key)]
    if len(set(chosen)) < len(chosen):
        return {"base": "duplicate_meter"}
    def _basis(a: str, b: str) -> float:
        return float(flat.get(a) or 0) + float(flat.get(b) or 0)

    if flat.get(CONF_EM_WATER) and _basis(CONF_EM_PERSONS_A, CONF_EM_PERSONS_B) <= 0:
        return {"base": "no_persons"}
    if flat.get(CONF_EM_GAS):
        by_area = flat.get(CONF_EM_GAS_KEY, "area") == "area"
        if _basis(*((CONF_EM_AREA_A, CONF_EM_AREA_B) if by_area else (CONF_EM_PERSONS_A, CONF_EM_PERSONS_B))) <= 0:
            return {"base": "no_area" if by_area else "no_persons"}
    if pv_price_value(flat.get(CONF_EM_PV_PRICE)) is None:
        return {"base": "invalid_price"}
    return {}


def em_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern: Preis je PV-kWh als Zahl, Namen bereinigt."""
    data = {**flat}
    data.pop(CONF_NAME, None)
    data[CONF_EM_PV_PRICE] = pv_price_value(flat[CONF_EM_PV_PRICE])
    data[CONF_EM_BASE_SHARE] = float(data[CONF_EM_BASE_SHARE])
    for key in (CONF_EM_PERSONS_A, CONF_EM_PERSONS_B, CONF_EM_AREA_A, CONF_EM_AREA_B):
        data[key] = float(data[key])
    for key in _OPTIONAL:                           # geleerte Felder überdecken frühere Werte
        data.setdefault(key, None)
    for key in (CONF_EM_NAME_A, CONF_EM_NAME_B):
        data[key] = (data.get(key) or "").strip()
    return data


class EnergyMonitorOptions:
    """Konfigurationsseite des Energiemonitors (kein Menü, der Name ist ein Feld)."""

    async def async_step_em_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_em(flat)
            if not errors:
                name = (flat.get(CONF_NAME) or "").strip()
                self.hass.config_entries.async_update_subentry(
                    self._get_entry(),
                    subentry,
                    title=instance_title(
                        self.hass, self.function_type, clean_instance_name(self.function_type, name)
                    ),
                    data={**subentry.data, **em_data(flat)},
                )
                return self.async_abort(reason="reconfigure_successful")
            defaults = {**defaults, **flat}
        return self.async_show_form(
            step_id="em_settings",
            data_schema=_em_schema(self.hass.config.language or "", defaults),
            errors=errors,
        )
