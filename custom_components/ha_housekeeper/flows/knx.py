"""Dialoge der Funktion KNX/Sonos-Connector: eine Konfigurationsseite mit festen Feldern."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SubentryFlowResult
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    CONF_ADDR_MUTE,
    CONF_ADDR_NEXT_PREV,
    CONF_ADDR_PLAY_PAUSE,
    CONF_ADDR_SCENE,
    CONF_ADDR_STOP,
    CONF_ADDR_TOGGLE,
    CONF_ADDR_VOLUME,
    CONF_ADDR_VOLUME_DIM,
    CONF_ADDR_VOLUME_STEP,
    CONF_CLEAR_LEGACY,
    CONF_COMMANDS,
    CONF_IDLE_TEXT,
    CONF_MAX_VOLUME,
    CONF_NAME,
    CONF_PLAYER,
    CONF_SPEAKERS,
    CONF_STATUS,
    CONF_STATUS_ALBUM,
    CONF_STATUS_ARTIST,
    CONF_STATUS_MUTED,
    CONF_STATUS_PAUSED,
    CONF_STATUS_PLAYING,
    CONF_STATUS_SOURCE,
    CONF_STATUS_TITLE,
    CONF_STATUS_VOLUME,
    CONF_STOP_INSTEAD,
    CONF_VOLUME_STEP,
    DEFAULT_MAX_VOLUME,
    DEFAULT_VOLUME_STEP,
    OBSOLETE_SCENES,
    SCENE_COUNT,
    clean_instance_name,
    instance_name,
    instance_title,
    scene_key,
)
from ..knx_codec import is_valid_ga
from ..knx_project import address_label, async_project_addresses
from ..knx_sonos import speaker_profiles
from .common import _flatten_sections, _number, _suggest

_SONOS_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="media_player", integration="sonos")
)

# Abschnitte der Seite mit ihren Gruppenadressfeldern
SECTION_SPEAKER = "speaker"
SECTION_PLAYBACK = "playback"
SECTION_VOLUME = "volume"
SECTION_SCENES = "scenes"
SECTION_STATUS_PLAY = "status_play"
SECTION_STATUS_LEVEL = "status_level"
SECTION_STATUS_TEXT = "status_text"
SECTION_LEGACY = "legacy"

_PLAYBACK_FIELDS = [CONF_ADDR_PLAY_PAUSE, CONF_ADDR_NEXT_PREV, CONF_ADDR_STOP, CONF_ADDR_TOGGLE]
_VOLUME_FIELDS = [CONF_ADDR_VOLUME, CONF_ADDR_VOLUME_STEP, CONF_ADDR_VOLUME_DIM, CONF_ADDR_MUTE]
# Rückmeldungen in drei Abschnitten: Wiedergabe, Lautstärke, Text
_STATUS_PLAY_FIELDS = [CONF_STATUS_PLAYING, CONF_STATUS_PAUSED]
_STATUS_LEVEL_FIELDS = [CONF_STATUS_VOLUME, CONF_STATUS_MUTED]
_STATUS_TEXT_FIELDS = [CONF_STATUS_TITLE, CONF_STATUS_ARTIST, CONF_STATUS_ALBUM, CONF_STATUS_SOURCE]
_STATUS_FIELDS = [*_STATUS_PLAY_FIELDS, *_STATUS_LEVEL_FIELDS, *_STATUS_TEXT_FIELDS]
_SCENE_ADDRESSES = [scene_key(n, "address") for n in range(1, SCENE_COUNT + 1)]
# alle Felder mit einer Gruppenadresse (leer = nicht verwendet)
ADDRESS_FIELDS = [
    *_PLAYBACK_FIELDS,
    *_VOLUME_FIELDS,
    CONF_ADDR_SCENE,
    *_SCENE_ADDRESSES,
    *_STATUS_FIELDS,
]
_SCENE_FAVORITES = [scene_key(n, "favorite") for n in range(1, SCENE_COUNT + 1)]
_SCENE_VOLUMES = [scene_key(n, "volume") for n in range(1, SCENE_COUNT + 1)]
# Felder, die beim Leeren explizit auf None gesetzt werden müssen
_CLEARABLE = [*ADDRESS_FIELDS, *_SCENE_FAVORITES, *_SCENE_VOLUMES, CONF_IDLE_TEXT]
# frühere Szenen 6 bis 8 verfallen beim Speichern
_OBSOLETE = [
    scene_key(n, field)
    for n in OBSOLETE_SCENES
    for field in ("favorite", "volume", "address")
]


# Haupt-Datentyp je Adressfeld (für den Filter der Projektadressen)
_FIELD_DPT: dict[str, int] = {
    **{key: 1 for key in (*_PLAYBACK_FIELDS, CONF_ADDR_VOLUME_STEP, CONF_ADDR_MUTE, *_SCENE_ADDRESSES)},
    CONF_ADDR_VOLUME: 5,
    CONF_ADDR_VOLUME_DIM: 3,
    CONF_ADDR_SCENE: 17,
    CONF_STATUS_PLAYING: 1,
    CONF_STATUS_PAUSED: 1,
    CONF_STATUS_MUTED: 1,
    CONF_STATUS_VOLUME: 5,
    CONF_STATUS_TITLE: 16,
    CONF_STATUS_ARTIST: 16,
    CONF_STATUS_ALBUM: 16,
    CONF_STATUS_SOURCE: 16,
}


def _address(
    key: str, defaults: dict[str, Any], project: list[dict[str, Any]]
) -> tuple[Any, Any]:
    """Adressfeld: Dropdown mit den passenden Adressen des ETS-Projekts (frei beschreibbar),
    ohne Projekt ein Textfeld. Adressen ohne Datentyp im Projekt passen zu jedem Feld."""
    wanted = _FIELD_DPT.get(key)
    options = [
        selector.SelectOptionDict(value=item["address"], label=address_label(item))
        for item in project
        if item["main"] is None or item["main"] == wanted
    ]
    field = vol.Optional(key, description=_suggest(key, defaults))
    if not options:
        return field, str
    return field, selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _knx_schema(
    defaults: dict[str, Any],
    sources: list[str],
    with_legacy: bool,
    project: list[dict[str, Any]] | None = None,
) -> vol.Schema:
    """Die Seite: Abschnitte Lautsprecher, Wiedergabe, Lautstärke, Szenen, Rückmeldungen."""
    project = project or []

    def _section(fields: dict[Any, Any], collapsed: bool = True) -> Any:
        return section(vol.Schema(fields), {"collapsed": collapsed})

    speaker: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
        vol.Required(CONF_PLAYER, description=_suggest(CONF_PLAYER, defaults)): _SONOS_SELECTOR,
        vol.Required(
            CONF_MAX_VOLUME, default=defaults.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME)
        ): _number(0, 100, "%"),
        vol.Required(
            CONF_VOLUME_STEP, default=defaults.get(CONF_VOLUME_STEP, DEFAULT_VOLUME_STEP)
        ): _number(1, 50, "%"),
        vol.Required(
            CONF_STOP_INSTEAD, default=bool(defaults.get(CONF_STOP_INSTEAD, False))
        ): bool,
    }
    sections: dict[Any, Any] = {
        vol.Required(SECTION_SPEAKER): _section(speaker, collapsed=False),   # nur der erste Abschnitt ist offen
        vol.Required(SECTION_PLAYBACK): _section(
            dict(_address(key, defaults, project) for key in _PLAYBACK_FIELDS)
        ),
        vol.Required(SECTION_VOLUME): _section(
            dict(_address(key, defaults, project) for key in _VOLUME_FIELDS)
        ),
        vol.Required(SECTION_SCENES): _section(dict([_address(CONF_ADDR_SCENE, defaults, project)])),
    }
    favorite = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=sources, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )
    for number in range(1, SCENE_COUNT + 1):
        fav, vol_key, addr = (scene_key(number, f) for f in ("favorite", "volume", "address"))
        sections[vol.Required(f"scene_{number}")] = _section(
            {
                vol.Optional(fav, description=_suggest(fav, defaults)): favorite,
                vol.Optional(vol_key, description=_suggest(vol_key, defaults)): _number(
                    0, 100, "%"
                ),
                **dict([_address(addr, defaults, project)]),
            }
        )
    sections[vol.Required(SECTION_STATUS_PLAY)] = _section(
        dict(_address(key, defaults, project) for key in _STATUS_PLAY_FIELDS)
    )
    sections[vol.Required(SECTION_STATUS_LEVEL)] = _section(
        dict(_address(key, defaults, project) for key in _STATUS_LEVEL_FIELDS)
    )
    text: dict[Any, Any] = dict(_address(key, defaults, project) for key in _STATUS_TEXT_FIELDS)
    text[vol.Optional(CONF_IDLE_TEXT, description=_suggest(CONF_IDLE_TEXT, defaults))] = str
    sections[vol.Required(SECTION_STATUS_TEXT)] = _section(text)
    if with_legacy:
        sections[vol.Required(SECTION_LEGACY)] = _section(
            {vol.Required(CONF_CLEAR_LEGACY, default=False): bool}
        )
    return vol.Schema(sections)


def _label(language: str, key: str) -> str:
    """Kurzname eines Felds für Fehlermeldungen."""
    de = language.startswith("de")
    if key.startswith("scene_"):
        number = key.split("_")[1]
        return f"{'Szene' if de else 'Scene'} {number}"
    names = {
        CONF_ADDR_PLAY_PAUSE: "Play/Pause",
        CONF_ADDR_NEXT_PREV: "Vor/Zurück" if de else "Next/previous",
        CONF_ADDR_STOP: "Stopp" if de else "Stop",
        CONF_ADDR_TOGGLE: "Umschalten" if de else "Toggle",
        CONF_ADDR_VOLUME: "Lautstärke" if de else "Volume",
        CONF_ADDR_VOLUME_STEP: "Lautstärke ±" if de else "Volume ±",
        CONF_ADDR_VOLUME_DIM: "Dimmen" if de else "Dimming",
        CONF_ADDR_MUTE: "Stumm" if de else "Mute",
        CONF_ADDR_SCENE: "Szenenadresse" if de else "Scene address",
    }
    return names.get(key, ("Rückmeldung " if de else "Feedback ") + key.removeprefix("status_"))


def _validate_knx(language: str, flat: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Prüfung der Seite: (Fehler, Angabe zur Fehlerstelle)."""
    wrong = [
        key
        for key in ADDRESS_FIELDS
        if flat.get(key) and not is_valid_ga(flat[key])
    ]
    if wrong:
        return {"base": "invalid_address"}, ", ".join(_label(language, k) for k in wrong)
    lonely = [
        n
        for n in range(1, SCENE_COUNT + 1)
        if (flat.get(scene_key(n, "favorite")) or flat.get(scene_key(n, "volume")) is not None)
        and not flat.get(CONF_ADDR_SCENE)
        and not flat.get(scene_key(n, "address"))
    ]
    if lonely:
        return {"base": "scene_no_trigger"}, ", ".join(
            _label(language, scene_key(n, "address")) for n in lonely
        )
    return {}, ""


def knx_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern: geleerte Felder auf None, Leerraum entfernen, alte Listen auf Wunsch löschen."""
    data: dict[str, Any] = {key: None for key in (*_CLEARABLE, *_OBSOLETE)}
    for key, value in flat.items():
        if isinstance(value, str):
            value = value.strip()
        if value in ("", None) and key in _CLEARABLE:
            continue
        data[key] = value
    # Lautsprecher-Profile gibt es nicht mehr: ein Eintrag gehört zu einem Lautsprecher
    data[CONF_SPEAKERS] = None
    for key in (CONF_MAX_VOLUME, CONF_VOLUME_STEP):
        data[key] = int(data[key])
    if data.pop(CONF_CLEAR_LEGACY, False):
        data[CONF_COMMANDS] = None
        data[CONF_STATUS] = None
    data.pop(CONF_NAME, None)
    return data


def new_instance_data(flat: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in knx_data(flat).items() if value is not None}


class KnxSonosOptions:
    """Konfigurationsseite des KNX/Sonos-Connectors (ersetzt das frühere Menü)."""

    def _knx_defaults(self) -> dict[str, Any]:
        """Aktuelle Werte; ältere Einträge mit Profilen zeigen die Werte des ersten Profils."""
        current = self._current
        defaults = dict(current)
        profiles = speaker_profiles(
            lambda key, default=None: default if current.get(key) is None else current[key]
        )
        if profiles:
            first = profiles[0]
            for key in (CONF_PLAYER, CONF_MAX_VOLUME, CONF_VOLUME_STEP, CONF_STOP_INSTEAD):
                if key in first:
                    defaults[key] = first[key]
        defaults[CONF_NAME] = instance_name(self._get_reconfigure_subentry().title)
        return defaults

    def _legacy_note(self) -> str:
        """Hinweis auf ältere Listen und Profile, die weiter laufen."""
        current = self._current
        commands = len(current.get(CONF_COMMANDS) or [])
        statuses = len(current.get(CONF_STATUS) or [])
        extra = max(len(current.get(CONF_SPEAKERS) or []) - 1, 0)
        german = (self.hass.config.language or "").startswith("de")
        parts = []
        if commands or statuses:
            parts.append(
                f"{commands} ältere Befehle und {statuses} ältere Rückmeldungen laufen weiter (Abschnitt „Ältere Einträge“)."
                if german
                else f"{commands} older commands and {statuses} older feedbacks keep running (section “Older entries”)."
            )
        if extra:
            parts.append(
                f"Dieser Eintrag hatte {extra} weitere Lautsprecher-Profile. Sie werden beim Speichern verworfen; lege sie als eigene Einträge an."
                if german
                else f"This entry had {extra} more speaker profiles. They are dropped when saving; add them as separate entries."
            )
        return " ".join(parts)

    def _knx_sources(self, player: str | None) -> list[str]:
        state = self.hass.states.get(player or "")
        return sorted((state.attributes.get("source_list") or []) if state else [])

    async def async_step_knx_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        detail = ""
        defaults = self._knx_defaults()
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors, detail = _validate_knx(self.hass.config.language or "", flat)
            if not errors:
                subentry = self._get_reconfigure_subentry()
                name = (flat.get(CONF_NAME) or "").strip()
                self.hass.config_entries.async_update_subentry(
                    self._get_entry(),
                    subentry,
                    title=instance_title(
                        self.hass, self.function_type, clean_instance_name(self.function_type, name)
                    ),
                    data={**subentry.data, **knx_data(flat)},
                )
                return self.async_abort(reason="reconfigure_successful")
            defaults = {**defaults, **flat}
        legacy = self._legacy_note()
        return self.async_show_form(
            step_id="knx_settings",
            data_schema=_knx_schema(
                defaults,
                self._knx_sources(defaults.get(CONF_PLAYER)),
                with_legacy=bool(
                    self._current.get(CONF_COMMANDS) or self._current.get(CONF_STATUS)
                ),
                project=await async_project_addresses(self.hass),
            ),
            errors=errors,
            description_placeholders={"detail": detail, "legacy": legacy},
        )
