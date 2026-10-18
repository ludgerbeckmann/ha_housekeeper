"""Dialoge der Funktion Türklingel."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import SubentryFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    CONF_DEBOUNCE,
    CONF_NAME,
    CONF_PROFILES,
    CONF_TRIGGER_ENTITY,
    CONF_CLEAR_RULES,
    DEFAULT_CLEAR_HOURS,
    DEFAULT_RING_DEBOUNCE,
    DEFAULT_RING_MESSAGE,
    MODE_KEYS,
    MODE_RINGTONE,
    MODE_TTS,
    P_CLEAR_HOURS,
    P_ENABLED,
    P_FROM,
    P_ID,
    P_MEDIA,
    P_MESSAGE,
    P_MOBILE_ENABLED,
    P_MOBILE_TARGETS,
    P_MODE,
    P_NAME,
    P_PLAYERS,
    P_TEXT,
    P_TO,
    P_TTS_ENTITY,
    P_VOLUME,
    P_WEEKDAYS,
    WEEKDAYS,
    clean_instance_name,
    instance_name,
    instance_title,
)
from .common import (
    SECTION_GENERAL,
    _mobile_selector,
    _mobile_suggest,
    _number,
    _sections_schema,
    _select,
    _suggest,
)


def _bell_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults))] = str
    fields[
        vol.Required(CONF_TRIGGER_ENTITY, description=_suggest(CONF_TRIGGER_ENTITY, defaults))
    ] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["binary_sensor", "event"])
    )
    fields[
        vol.Required(
            CONF_DEBOUNCE, default=defaults.get(CONF_DEBOUNCE, DEFAULT_RING_DEBOUNCE)
        )
    ] = _number(0, 3600, "s")
    return _sections_schema(fields, {})


def _validate_bell(user_input: dict[str, Any]) -> dict[str, str]:
    """Der Eintrag selbst hat keine Pflichtprüfung mehr (Push steckt in den Profilen)."""
    return {}


PROFILE_SLOTS = 3          # feste Profilplätze der Einstellungsseite
SECTION_LEGACY = "legacy"
_PUSH_KEYS = (P_MOBILE_ENABLED, P_MOBILE_TARGETS, P_MESSAGE, P_CLEAR_HOURS)


def slot_key(number: int) -> str:
    return f"profile_{number}"


def _profile_defaults(profiles: list[dict[str, Any]], number: int, language: str) -> dict[str, Any]:
    """Vorbelegung eines Platzes: das Profil an dieser Stelle der Liste, sonst ein ausgeschalteter Platz."""
    if number <= len(profiles):
        return dict(profiles[number - 1])
    name = f"Profil {number}" if language.startswith("de") else f"Profile {number}"
    return {P_NAME: name, P_ENABLED: False}


def _slot_fields(hass: HomeAssistant, d: dict[str, Any]) -> dict[Any, Any]:
    """Alle Felder eines Profilplatzes: Zeitfenster, Ton und Push."""
    return {
        vol.Required(P_NAME, default=d.get(P_NAME, "")): str,
        vol.Required(P_ENABLED, default=d.get(P_ENABLED, True)): bool,
        vol.Required(P_FROM, default=d.get(P_FROM, "07:00:00")): selector.TimeSelector(),
        vol.Required(P_TO, default=d.get(P_TO, "22:00:00")): selector.TimeSelector(),
        vol.Required(P_WEEKDAYS, default=d.get(P_WEEKDAYS, WEEKDAYS)): _select(
            WEEKDAYS, "weekday", multiple=True, mode=selector.SelectSelectorMode.LIST
        ),
        vol.Optional(P_PLAYERS, description=_suggest(P_PLAYERS, d)): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="media_player", multiple=True)
        ),
        vol.Required(P_MODE, default=d.get(P_MODE, MODE_TTS)): _select(
            [MODE_TTS, MODE_RINGTONE], "profile_mode", mode=selector.SelectSelectorMode.LIST
        ),
        vol.Optional(P_TTS_ENTITY, description=_suggest(P_TTS_ENTITY, d)): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="tts")
        ),
        vol.Optional(P_TEXT, default=d.get(P_TEXT, DEFAULT_RING_MESSAGE)): str,
        vol.Optional(P_MEDIA, description=_suggest(P_MEDIA, d)): selector.MediaSelector(
            selector.MediaSelectorConfig(accept=["audio/*"])
        ),
        vol.Required(P_VOLUME, default=d.get(P_VOLUME, 0)): _number(0, 100, "%"),
        vol.Required(P_MOBILE_ENABLED, default=d.get(P_MOBILE_ENABLED, False)): bool,
        vol.Optional(P_MOBILE_TARGETS, description=_mobile_suggest(hass, d)): _mobile_selector(),
        vol.Required(P_MESSAGE, default=d.get(P_MESSAGE, DEFAULT_RING_MESSAGE)): str,
        vol.Required(P_CLEAR_HOURS, default=d.get(P_CLEAR_HOURS, DEFAULT_CLEAR_HOURS)): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=168, step=0.5, unit_of_measurement="h", mode=selector.NumberSelectorMode.BOX
            )
        ),
    }


def _bell_settings_schema(
    hass: HomeAssistant,
    defaults: dict[str, Any],
    profiles: list[dict[str, Any]],
    slot_values: dict[int, dict[str, Any]] | None = None,
) -> vol.Schema:
    """Die Seite: Allgemein (offen) und drei Profilplätze (eingeklappt); ältere Profile ab dem vierten nur als Hinweis."""
    language = hass.config.language or ""
    general: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
        vol.Required(
            CONF_TRIGGER_ENTITY, description=_suggest(CONF_TRIGGER_ENTITY, defaults)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain=["binary_sensor", "event"])),
        vol.Required(
            CONF_DEBOUNCE, default=defaults.get(CONF_DEBOUNCE, DEFAULT_RING_DEBOUNCE)
        ): _number(0, 3600, "s"),
    }
    sections: dict[Any, Any] = {
        vol.Required(SECTION_GENERAL): section(vol.Schema(general), {"collapsed": False})
    }
    for number in range(1, PROFILE_SLOTS + 1):
        d = (slot_values or {}).get(number) or _profile_defaults(profiles, number, language)
        sections[vol.Required(slot_key(number))] = section(
            vol.Schema(_slot_fields(hass, d)), {"collapsed": True}
        )
    if len(profiles) > PROFILE_SLOTS:
        sections[vol.Required(SECTION_LEGACY)] = section(
            vol.Schema({vol.Required(CONF_CLEAR_RULES, default=False): bool}), {"collapsed": True}
        )
    return vol.Schema(sections)


def _validate_slot(slot: dict[str, Any]) -> str | None:
    """Fehlerschlüssel eines eingeschalteten Profilplatzes (oder `None`)."""
    mode = slot.get(P_MODE, MODE_TTS)
    push = bool(slot.get(P_MOBILE_ENABLED))
    if not slot.get(P_WEEKDAYS):
        return "profile_no_weekday"
    if not slot.get(P_PLAYERS) and not push:
        return "profile_no_output"
    if push and not slot.get(P_MOBILE_TARGETS):
        return "profile_no_targets"
    if slot.get(P_PLAYERS) and mode == MODE_TTS and not (slot.get(P_TTS_ENTITY) and slot.get(P_TEXT)):
        return "profile_no_tts"
    if slot.get(P_PLAYERS) and mode == MODE_RINGTONE and not (slot.get(P_MEDIA) or {}).get("media_content_id"):
        return "profile_no_ringtone"
    return None


def _build_profile(slot: dict[str, Any], profile_id: str) -> dict[str, Any]:
    """Profil aus einem Platz bauen (Ton nur mit Media Player, Schlüssel passend zum Modus)."""
    profile: dict[str, Any] = {
        P_ID: profile_id,
        **{k: slot[k] for k in (P_NAME, P_ENABLED, P_FROM, P_TO, P_WEEKDAYS) if k in slot},
        P_PLAYERS: slot.get(P_PLAYERS) or [],
        P_MOBILE_ENABLED: bool(slot.get(P_MOBILE_ENABLED)),
        P_MOBILE_TARGETS: slot.get(P_MOBILE_TARGETS) or [],
        P_MESSAGE: slot.get(P_MESSAGE) or DEFAULT_RING_MESSAGE,
        P_CLEAR_HOURS: slot.get(P_CLEAR_HOURS, DEFAULT_CLEAR_HOURS),
    }
    if profile[P_PLAYERS]:
        mode = slot.get(P_MODE, MODE_TTS)
        profile[P_MODE] = mode
        profile[P_VOLUME] = slot.get(P_VOLUME, 0)
        profile.update({k: slot[k] for k in MODE_KEYS[mode] if k in slot})
    return profile


def slots_to_profiles(
    slots: dict[int, dict[str, Any]], existing: list[dict[str, Any]], drop_extra: bool
) -> list[dict[str, Any]]:
    """Profilliste aus den Plätzen: bis zum letzten benutzten Platz (Lücken als ausgeschaltete Plätze),
    ältere Profile ab dem vierten bleiben unverändert, außer sie werden gelöscht."""
    last = 0
    for number in range(1, PROFILE_SLOTS + 1):
        slot = slots[number]
        if slot.get(P_ENABLED) or slot.get(P_PLAYERS) or slot.get(P_MOBILE_ENABLED) or number <= len(existing):
            last = number
    profiles = []
    for number in range(1, last + 1):
        old = existing[number - 1] if number <= len(existing) else None
        profiles.append(_build_profile(slots[number], old[P_ID] if old else uuid.uuid4().hex[:8]))
    if not drop_extra:
        profiles += existing[PROFILE_SLOTS:]
    return profiles


class DoorbellOptions:
    """Konfigurationsseite der Türklingel (kein Menü, der Name ist ein Feld)."""

    async def async_step_bell_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()
        profiles = list(self._current.get(CONF_PROFILES) or [])
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        slot_values: dict[int, dict[str, Any]] | None = None
        if user_input is not None:
            slots = {n: dict(user_input.get(slot_key(n)) or {}) for n in range(1, PROFILE_SLOTS + 1)}
            for number, slot in slots.items():
                if slot.get(P_ENABLED) and (error := _validate_slot(slot)):
                    errors["base"] = error
                    placeholders["profile"] = str(slot.get(P_NAME) or number)
                    break
            if not errors:
                general = user_input.get(SECTION_GENERAL) or {}
                name = (general.get(CONF_NAME) or "").strip()
                legacy = user_input.get(SECTION_LEGACY) or {}
                data = {
                    CONF_TRIGGER_ENTITY: general[CONF_TRIGGER_ENTITY],
                    CONF_DEBOUNCE: general[CONF_DEBOUNCE],
                    CONF_PROFILES: slots_to_profiles(slots, profiles, bool(legacy.get(CONF_CLEAR_RULES))),
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
            defaults = {**defaults, **(user_input.get(SECTION_GENERAL) or {})}
            slot_values = slots
        return self.async_show_form(
            step_id="bell_settings",
            data_schema=_bell_settings_schema(self.hass, defaults, profiles, slot_values),
            errors=errors,
            description_placeholders=placeholders or None,
        )
