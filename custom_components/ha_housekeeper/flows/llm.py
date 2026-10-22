"""Dialoge der Funktion LLM-Verbrauch."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SubentryFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .. import llm_providers
from ..const import (
    CONF_API_KEY,
    CONF_DAILY_LIMIT,
    CONF_FORECAST_WARNING,
    CONF_LLM_AMOUNT,
    CONF_LLM_BASELINE,
    CONF_LLM_CALIBRATE,
    CONF_LLM_MODE,
    CONF_LOW_BALANCE,
    CONF_MOBILE_TARGETS,
    CONF_MONTHLY_LIMIT,
    CONF_NAME,
    CONF_POLL_MINUTES,
    CONF_PROVIDER,
    CONF_TRACK_USAGE,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    DEFAULT_POLL_MINUTES,
    LLM_MODE_BALANCE,
    LLM_MODE_BUDGET,
    LLM_MODES,
    PROVIDERS,
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
    _select,
    _suggest,
    _validate_notify,
)

_LOGGER = logging.getLogger(__name__)

_CLEARABLE = (
    CONF_MOBILE_TARGETS,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    CONF_LOW_BALANCE,
    CONF_DAILY_LIMIT,
    CONF_MONTHLY_LIMIT,
)
_MAX_AMOUNT = 1_000_000
SECTION_LIMITS = "limits"


def _key_selector() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


def _amount() -> selector.NumberSelector:
    return _number(0, _MAX_AMOUNT, step=0.01)


def _limit_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Optionale Grenzen (leer = keine Warnung)."""
    return {
        vol.Optional(
            CONF_LOW_BALANCE, description=_suggest(CONF_LOW_BALANCE, defaults)
        ): _amount(),
        vol.Optional(
            CONF_DAILY_LIMIT, description=_suggest(CONF_DAILY_LIMIT, defaults)
        ): _amount(),
        vol.Optional(
            CONF_MONTHLY_LIMIT, description=_suggest(CONF_MONTHLY_LIMIT, defaults)
        ): _amount(),
        vol.Required(
            CONF_FORECAST_WARNING, default=defaults.get(CONF_FORECAST_WARNING, True)
        ): bool,
    }


def _poll_field(defaults: dict[str, Any]) -> dict[Any, Any]:
    return {
        vol.Required(
            CONF_POLL_MINUTES, default=defaults.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES)
        ): _number(5, 1440, "min"),
        vol.Required(
            CONF_TRACK_USAGE, default=defaults.get(CONF_TRACK_USAGE, False)
        ): bool,
    }


def _llm_sections(
    hass: HomeAssistant, general: dict[Any, Any], limits: dict[Any, Any], defaults: dict[str, Any]
) -> vol.Schema:
    """Seite in drei Abschnitte: Konto, Grenzen und Benachrichtigung (nur „Konto“ ist aufgeklappt)."""

    def _section(fields: dict[Any, Any], collapsed: bool = True) -> Any:
        return section(vol.Schema(fields), {"collapsed": collapsed})

    return vol.Schema(
        {
            vol.Required(SECTION_GENERAL): _section(general, collapsed=False),
            vol.Required(SECTION_LIMITS): _section(limits),
            vol.Required(SECTION_NOTIFICATIONS): _section(
                _notify_fields(hass, {**_POOL_NOTIFY_DEFAULTS, **defaults}, with_action=False)
            ),
        }
    )


def _llm_new_schema(hass: HomeAssistant, defaults: dict[str, Any]) -> vol.Schema:
    """Anlegen: Konto (Name, Anbieter, Key, Modus mit Betrag, Intervall), Grenzen und Benachrichtigung."""
    general: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
        vol.Required(
            CONF_PROVIDER, default=defaults.get(CONF_PROVIDER, PROVIDERS[0])
        ): _select(PROVIDERS, "llm_provider", mode=selector.SelectSelectorMode.LIST),
        vol.Required(CONF_API_KEY, description=_suggest(CONF_API_KEY, defaults)): _key_selector(),
        vol.Required(
            CONF_LLM_MODE, default=defaults.get(CONF_LLM_MODE, LLM_MODE_BALANCE)
        ): _select(LLM_MODES, "llm_mode", mode=selector.SelectSelectorMode.LIST),
        vol.Required(
            CONF_LLM_AMOUNT, description=_suggest(CONF_LLM_AMOUNT, defaults)
        ): _amount(),
    }
    general.update(_poll_field(defaults))
    return _llm_sections(hass, general, _limit_fields(defaults), defaults)


def _llm_settings_schema(
    hass: HomeAssistant, defaults: dict[str, Any], mode: str
) -> vol.Schema:
    """Einstellungen: Name, Key (leer = unverändert), Budget bzw. Abgleich, Intervall, Grenzen, Benachrichtigung."""
    general: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
        vol.Optional(CONF_API_KEY): _key_selector(),
    }
    if mode == LLM_MODE_BUDGET:
        general[
            vol.Required(CONF_LLM_AMOUNT, default=defaults.get(CONF_LLM_AMOUNT, 0))
        ] = _amount()
    else:
        general[vol.Optional(CONF_LLM_CALIBRATE)] = _amount()
    general.update(_poll_field(defaults))
    return _llm_sections(hass, general, _limit_fields(defaults), defaults)


def llm_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern; geleerte optionale Felder werden explizit auf None gesetzt."""
    return {**{key: None for key in _CLEARABLE}, **flat}


async def async_check_key(
    hass: HomeAssistant, provider: str, api_key: str
) -> tuple[str | None, str]:
    """Key mit einer Abfrage prüfen: (`None`, "") = in Ordnung, sonst (Fehlerschlüssel, Ursache)."""
    yesterday = dt_util.utcnow().date() - timedelta(days=1)
    try:
        await llm_providers.async_fetch_costs(
            async_get_clientsession(hass), provider, api_key, yesterday
        )
    except llm_providers.ProviderAuthError as err:
        _LOGGER.warning("LLM-Verbrauch: Key abgelehnt (%s): %s", provider, err)
        return "invalid_auth", str(err)
    except llm_providers.ProviderError as err:
        _LOGGER.warning("LLM-Verbrauch: Prüfung des Keys fehlgeschlagen (%s): %s", provider, err)
        return "cannot_connect", str(err)
    return None, ""


async def async_validate_new(
    hass: HomeAssistant, flat: dict[str, Any]
) -> tuple[dict[str, str], str]:
    """Eingaben prüfen: (Fehler, Ursache des Key-Fehlers); der Key wird dabei bereinigt."""
    errors = _validate_notify(flat, require_method=False)
    detail = ""
    if not errors:
        flat[CONF_API_KEY] = flat[CONF_API_KEY].strip()
        error, detail = await async_check_key(hass, flat[CONF_PROVIDER], flat[CONF_API_KEY])
        if error:
            errors["base"] = error
    return errors, detail


def new_instance_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Daten einer neuen Instanz (im Guthaben-Modus mit dem Zeitpunkt des Abgleichs)."""
    data = llm_data(flat)
    data.pop(CONF_NAME, None)
    if data[CONF_LLM_MODE] == LLM_MODE_BALANCE:
        data[CONF_LLM_BASELINE] = dt_util.utcnow().isoformat()
    return data


class LlmOptions:
    """Konfigurationsseite des LLM-Verbrauchs (kein Menü, der Name ist ein Feld)."""

    async def async_step_llm_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        detail = ""
        subentry = self._get_reconfigure_subentry()
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        mode = defaults.get(CONF_LLM_MODE, LLM_MODE_BALANCE)
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_notify(flat, require_method=False)
            if not errors:
                key = (flat.pop(CONF_API_KEY, None) or "").strip()
                if key:
                    error, detail = await async_check_key(self.hass, defaults[CONF_PROVIDER], key)
                    if error:
                        errors["base"] = error
                    else:
                        flat[CONF_API_KEY] = key
            if not errors:
                data = llm_data(flat)
                name = (data.pop(CONF_NAME, None) or "").strip()
                calibrate = data.pop(CONF_LLM_CALIBRATE, None)
                if calibrate is not None:               # Guthaben abgleichen: Betrag und Zeitpunkt
                    data[CONF_LLM_AMOUNT] = calibrate
                    data[CONF_LLM_BASELINE] = dt_util.utcnow().isoformat()
                self.hass.config_entries.async_update_subentry(
                    self._get_entry(),
                    subentry,
                    title=instance_title(
                        self.hass, self.function_type, clean_instance_name(self.function_type, name)
                    ),
                    data={**subentry.data, **data},
                )
                return self.async_abort(reason="reconfigure_successful")
            defaults = {**defaults, **flat}
        return self.async_show_form(
            step_id="llm_settings",
            data_schema=_llm_settings_schema(self.hass, defaults, mode),
            errors=errors,
            description_placeholders={"detail": detail},
        )
