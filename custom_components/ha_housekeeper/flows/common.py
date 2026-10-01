"""Gemeinsame Hilfen der Einstellungsdialoge."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    CONF_MOBILE_ACTION,
    CONF_MOBILE_ENABLED,
    CONF_MOBILE_TARGETS,
    CONF_PERSISTENT_ENABLED,
    CONF_TTS_ENABLED,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    DEFAULT_MOBILE_ACTION,
    OPTIONAL_KEYS,
)
from ..notify import targets_for_form


def _mobile_selector() -> selector.DeviceSelector:
    """Mehrfachauswahl der Companion-App-Geräte (native Geräteauswahl mit Name und Bereich).

    Gespeichert werden Geräte der Geräteverwaltung; beim Senden wird daraus der Push-Dienst
    `notify.mobile_app_<gerät>` (nur darüber gehen Aktionen und kritische Meldungen).
    """
    return selector.DeviceSelector(
        selector.DeviceSelectorConfig(integration="mobile_app", multiple=True)
    )


def _mobile_suggest(hass: HomeAssistant, defaults: dict[str, Any]) -> dict[str, Any]:
    """Vorbelegung der Push-Ziele; ältere Dienstnamen werden den Geräten zugeordnet."""
    if CONF_MOBILE_TARGETS not in defaults:
        return {}
    return {"suggested_value": targets_for_form(hass, defaults[CONF_MOBILE_TARGETS])}


def _sections_schema(
    general: dict[Any, Any], notifications: dict[Any, Any]
) -> vol.Schema:
    """Formular in zwei ausgeklappte Abschnitte: Allgemein und Benachrichtigungen.

    Ein Abschnitt ohne Felder (z. B. „Allgemein“ des Aufgabenplaners in den
    Einstellungen, wo der Name entfällt) wird weggelassen.
    """
    sections: dict[Any, Any] = {}
    for key, fields in ((SECTION_GENERAL, general), (SECTION_NOTIFICATIONS, notifications)):
        if fields:
            sections[vol.Required(key)] = section(vol.Schema(fields), {"collapsed": False})
    return vol.Schema(sections)


def _suggest(key: str, defaults: dict[str, Any]) -> dict[str, Any]:
    return {"suggested_value": defaults[key]} if key in defaults else {}


def _number(
    minimum: float, maximum: float, unit: str | None = None, step: float | str = 1
) -> selector.NumberSelector:
    config: dict[str, Any] = {
        "min": minimum,
        "max": maximum,
        "step": step,
        "mode": selector.NumberSelectorMode.BOX,
    }
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _select(options: list[str], key: str, **kwargs: Any) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            translation_key=key,
            mode=kwargs.pop("mode", selector.SelectSelectorMode.DROPDOWN),
            **kwargs,
        )
    )


def _notify_fields(
    hass: HomeAssistant, defaults: dict[str, Any], with_action: bool
) -> dict[Any, Any]:
    """Felder der gemeinsamen Benachrichtigungswege."""
    fields: dict[Any, Any] = {
        vol.Required(
            CONF_MOBILE_ENABLED, default=defaults.get(CONF_MOBILE_ENABLED, True)
        ): bool,
        vol.Optional(
            CONF_MOBILE_TARGETS, description=_mobile_suggest(hass, defaults)
        ): _mobile_selector(),
    }
    if with_action:
        fields[
            vol.Required(
                CONF_MOBILE_ACTION,
                default=defaults.get(CONF_MOBILE_ACTION, DEFAULT_MOBILE_ACTION),
            )
        ] = bool
    fields.update(
        {
            vol.Required(
                CONF_TTS_ENABLED, default=defaults.get(CONF_TTS_ENABLED, False)
            ): bool,
            vol.Optional(
                CONF_TTS_ENTITY, description=_suggest(CONF_TTS_ENTITY, defaults)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="tts")),
            vol.Optional(
                CONF_TTS_PLAYER, description=_suggest(CONF_TTS_PLAYER, defaults)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
            vol.Required(
                CONF_PERSISTENT_ENABLED,
                default=defaults.get(CONF_PERSISTENT_ENABLED, False),
            ): bool,
        }
    )
    return fields


def _validate_notify(user_input: dict[str, Any], require_method: bool) -> dict[str, str]:
    errors: dict[str, str] = {}
    tts_ready = bool(
        user_input.get(CONF_TTS_ENTITY) and user_input.get(CONF_TTS_PLAYER)
    )
    mobile = user_input.get(CONF_MOBILE_ENABLED) and user_input.get(CONF_MOBILE_TARGETS)
    tts = user_input.get(CONF_TTS_ENABLED) and tts_ready
    if require_method and not (
        mobile or tts or user_input.get(CONF_PERSISTENT_ENABLED)
    ):
        errors["base"] = "no_method"
    if user_input.get(CONF_TTS_ENABLED) and not tts_ready:
        errors["base"] = "tts_incomplete"
    return errors


def _with_cleared(user_input: dict[str, Any]) -> dict[str, Any]:
    """Geleerte optionale Felder explizit auf None setzen.

    Sonst würde beim Lesen der Wert aus der Ersteinrichtung wieder greifen.
    """
    return {**{key: None for key in OPTIONAL_KEYS}, **user_input}


SECTION_GENERAL = "general"


SECTION_NOTIFICATIONS = "notifications"


def _flatten_sections(user_input: dict[str, Any]) -> dict[str, Any]:
    """Abschnitte des Formulars zu den flachen Schlüsseln der Einstellungen auflösen."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


_POOL_NOTIFY_DEFAULTS = {CONF_MOBILE_ENABLED: False, CONF_PERSISTENT_ENABLED: True}


class OptionsBase:
    """Gemeinsame Hilfen der Options-Flows (Menü, Speichern, Beenden)."""

    # `hass` und `config_entry` stellt OptionsFlow bereit

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def _menu(
        self,
        step_id: str,
        options: list[str],
        user_input: dict[str, Any] | None,
        placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Menü als Formular: Auswahlliste mit „Weiter“ unten rechts statt Menüpunkten.

        Die gewählte Aktion ist der Name eines Schritts (`async_step_<aktion>`).
        """
        if user_input is not None and user_input.get("action") in options:
            return await getattr(self, f"async_step_{user_input['action']}")()
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required("action"): _select(
                        options, "menu_action", mode=selector.SelectSelectorMode.LIST
                    )
                }
            ),
            description_placeholders=placeholders,
        )

    def _save(self, options: dict[str, Any]) -> None:
        self.hass.config_entries.async_update_entry(
            self.config_entry, options={**self.config_entry.options, **options}
        )

    async def async_step_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(data=dict(self.config_entry.options))
