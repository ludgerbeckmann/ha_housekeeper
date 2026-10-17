"""Dialoge der Funktion LLM-Verbrauch."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
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


def _llm_new_schema(hass: HomeAssistant, defaults: dict[str, Any]) -> vol.Schema:
    """Anlegen: Name, Anbieter, Key, Modus mit Betrag, Grenzen und Benachrichtigung."""
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
    general.update(_limit_fields(defaults))
    return _sections_schema(
        general,
        _notify_fields(hass, {**_POOL_NOTIFY_DEFAULTS, **defaults}, with_action=False),
    )


def _llm_settings_schema(
    hass: HomeAssistant, defaults: dict[str, Any], mode: str
) -> vol.Schema:
    """Einstellungen: Key (leer = unverändert), Intervall, Budget (nur Monatsbudget), Grenzen."""
    general: dict[Any, Any] = {vol.Optional(CONF_API_KEY): _key_selector()}
    if mode == LLM_MODE_BUDGET:
        general[
            vol.Required(CONF_LLM_AMOUNT, default=defaults.get(CONF_LLM_AMOUNT, 0))
        ] = _amount()
    general.update(_poll_field(defaults))
    general.update(_limit_fields(defaults))
    return _sections_schema(general, _notify_fields(hass, defaults, with_action=False))


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
    """Options-Flow-Schritte: LLM-Verbrauch."""

    async def async_step_llm_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["llm_general"]
        if self._current.get(CONF_LLM_MODE, LLM_MODE_BALANCE) == LLM_MODE_BALANCE:
            options.append("llm_calibrate")
        options.append("rename")
        return await self._menu("llm_menu", options, user_input)

    async def async_step_llm_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        detail = ""
        defaults = self._current
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
                self._save(llm_data(flat))
                return await self.async_step_llm_menu()
            defaults = {**defaults, **flat}
        return self.async_show_form(
            step_id="llm_general",
            data_schema=_llm_settings_schema(self.hass, defaults, mode),
            errors=errors,
            description_placeholders={"detail": detail},
        )

    async def async_step_llm_calibrate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Guthaben abgleichen: den in der Konsole des Anbieters gezeigten Betrag eintragen."""
        if user_input is not None:
            self._save(
                {
                    CONF_LLM_AMOUNT: user_input[CONF_LLM_AMOUNT],
                    CONF_LLM_BASELINE: dt_util.utcnow().isoformat(),
                }
            )
            return await self.async_step_llm_menu()
        return self.async_show_form(
            step_id="llm_calibrate",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LLM_AMOUNT,
                        description=_suggest(CONF_LLM_AMOUNT, self._current),
                    ): _amount()
                }
            ),
        )
