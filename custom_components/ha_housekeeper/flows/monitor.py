"""Dialoge der Funktion Integrationsmonitor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SubentryFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    CONF_CHECK_MINUTES,
    CONF_CLEAR_RULES,
    CONF_EXCLUDED,
    CONF_GRACE_MINUTES,
    CONF_MIN_ENTITIES,
    CONF_MOBILE_TARGETS,
    CONF_MON_DISABLE,
    CONF_MON_DISABLE_ERROR,
    CONF_MON_DISABLE_MODE,
    CONF_MON_DISABLE_PRESENCE,
    CONF_MON_DISABLE_REENABLE,
    CONF_MON_DISABLE_UNAVAILABLE,
    CONF_MON_RELOAD,
    CONF_MON_RELOAD_ERROR,
    CONF_MON_RELOAD_MODE,
    CONF_MON_RELOAD_UNAVAILABLE,
    CONF_MON_REPORT,
    CONF_MON_REPORT_MODE,
    CONF_MONITOR_RULES,
    CONF_NAME,
    CONF_NOTIFY_ALL,
    CONF_NOTIFY_ERRORS,
    CONF_NOTIFY_UNAVAILABLE,
    CONF_SUMMARY_MINUTES,
    CONF_TTS_ENTITY,
    CONF_TTS_PLAYER,
    DEFAULT_CHECK_MINUTES,
    DEFAULT_GRACE_MINUTES,
    DEFAULT_MIN_ENTITIES,
    DEFAULT_SUMMARY_MINUTES,
    DOMAIN,
    LIST_BLACKLIST,
    LIST_MODES,
    LIST_WHITELIST,
    clean_instance_name,
    instance_name,
    instance_title,
)
from .common import (
    SECTION_GENERAL,
    SECTION_NOTIFICATIONS,
    _flatten_sections,
    _notify_fields,
    _number,
    _select,
    _suggest,
    _validate_notify,
)

_NOTIFY_CLEARABLE = (CONF_MOBILE_TARGETS, CONF_TTS_ENTITY, CONF_TTS_PLAYER)


def _entry_options(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Alle Integrationen (Config-Entries) außer dieser, sortiert nach Titel."""
    entries = sorted(
        (e for e in hass.config_entries.async_entries() if e.domain != DOMAIN),
        key=lambda e: (e.title.casefold(), e.domain),
    )
    return [
        selector.SelectOptionDict(value=e.entry_id, label=f"{e.title} ({e.domain})")
        for e in entries
    ]


def _entry_selector(hass: HomeAssistant) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=_entry_options(hass),
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _list_mode(key: str, defaults: dict[str, Any], default: str) -> tuple[Any, Any]:
    return (
        vol.Required(key, default=defaults.get(key) or default),
        _select(LIST_MODES, "monitor_list_mode", mode=selector.SelectSelectorMode.LIST),
    )


def _monitor_schema(
    hass: HomeAssistant, defaults: dict[str, Any], new: bool, with_legacy: bool = False
) -> vol.Schema:
    """Die Seite: Allgemein, Nur melden, Neu laden, Deaktivieren, Benachrichtigung (nur „Allgemein“ offen)."""

    def _section(fields: dict[Any, Any], collapsed: bool = True) -> Any:
        return section(vol.Schema(fields), {"collapsed": collapsed})

    general: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
        vol.Required(
            CONF_GRACE_MINUTES,
            default=defaults.get(CONF_GRACE_MINUTES, DEFAULT_GRACE_MINUTES),
        ): _number(0, 1440, "min"),
        vol.Required(
            CONF_MIN_ENTITIES,
            default=defaults.get(CONF_MIN_ENTITIES, DEFAULT_MIN_ENTITIES),
        ): _number(1, 100),
        vol.Required(
            CONF_CHECK_MINUTES,
            default=defaults.get(CONF_CHECK_MINUTES, DEFAULT_CHECK_MINUTES),
        ): _number(1, 60, "min"),
    }
    # „Nur melden“: eine ältere Ausnahmenliste wird zur Blacklist
    report_entries = defaults.get(CONF_MON_REPORT)
    if report_entries is None:
        report_entries = defaults.get(CONF_EXCLUDED) or []
    report = dict(
        [
            _list_mode(CONF_MON_REPORT_MODE, defaults, LIST_BLACKLIST),
            (vol.Optional(CONF_MON_REPORT, default=report_entries), _entry_selector(hass)),
        ]
    )
    reload = dict(
        [
            _list_mode(CONF_MON_RELOAD_MODE, defaults, LIST_WHITELIST),
            (
                vol.Optional(CONF_MON_RELOAD, default=defaults.get(CONF_MON_RELOAD) or []),
                _entry_selector(hass),
            ),
            (vol.Required(CONF_MON_RELOAD_ERROR, default=defaults.get(CONF_MON_RELOAD_ERROR, True)), bool),
            (
                vol.Required(
                    CONF_MON_RELOAD_UNAVAILABLE, default=defaults.get(CONF_MON_RELOAD_UNAVAILABLE, True)
                ),
                bool,
            ),
        ]
    )
    disable = dict(
        [
            _list_mode(CONF_MON_DISABLE_MODE, defaults, LIST_WHITELIST),
            (
                vol.Optional(CONF_MON_DISABLE, default=defaults.get(CONF_MON_DISABLE) or []),
                _entry_selector(hass),
            ),
            (vol.Required(CONF_MON_DISABLE_ERROR, default=defaults.get(CONF_MON_DISABLE_ERROR, True)), bool),
            (
                vol.Required(
                    CONF_MON_DISABLE_UNAVAILABLE,
                    default=defaults.get(CONF_MON_DISABLE_UNAVAILABLE, True),
                ),
                bool,
            ),
            (
                vol.Optional(
                    CONF_MON_DISABLE_PRESENCE, description=_suggest(CONF_MON_DISABLE_PRESENCE, defaults)
                ),
                selector.EntitySelector(),
            ),
            (
                vol.Required(
                    CONF_MON_DISABLE_REENABLE, default=bool(defaults.get(CONF_MON_DISABLE_REENABLE))
                ),
                bool,
            ),
        ]
    )
    notifications: dict[Any, Any] = {
        vol.Required(
            CONF_NOTIFY_ERRORS,
            default=defaults.get(CONF_NOTIFY_ERRORS, defaults.get(CONF_NOTIFY_ALL, True)),
        ): bool,
        vol.Required(
            CONF_NOTIFY_UNAVAILABLE,
            # neue Instanz: aus (Einzelgeräte sind oft aus); ältere Einstellung: wie bisher
            default=defaults.get(CONF_NOTIFY_UNAVAILABLE, defaults.get(CONF_NOTIFY_ALL, not new)),
        ): bool,
        vol.Required(
            CONF_SUMMARY_MINUTES,
            default=defaults.get(CONF_SUMMARY_MINUTES, DEFAULT_SUMMARY_MINUTES),
        ): _number(0, 240, "min"),
        **_notify_fields(hass, defaults, with_action=False),
    }
    sections: dict[Any, Any] = {
        vol.Required(SECTION_GENERAL): _section(general, collapsed=False),
        vol.Required("report"): _section(report),
        vol.Required("reload"): _section(reload),
        vol.Required("disable"): _section(disable),
        vol.Required(SECTION_NOTIFICATIONS): _section(notifications),
    }
    if with_legacy:
        sections[vol.Required("legacy")] = _section({vol.Required(CONF_CLEAR_RULES, default=False): bool})
    return vol.Schema(sections)


def _validate_monitor(flat: dict[str, Any]) -> dict[str, str]:
    reporting = (
        flat.get(CONF_NOTIFY_ERRORS)
        or flat.get(CONF_NOTIFY_UNAVAILABLE)
        or flat.get(CONF_MON_REPORT)
    )
    errors = _validate_notify(flat, require_method=bool(reporting))
    if errors:
        return errors
    if flat.get(CONF_MON_DISABLE_REENABLE) and not flat.get(CONF_MON_DISABLE_PRESENCE):
        return {"base": "no_presence"}
    return {}


def monitor_data(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern; geleerte Felder werden explizit auf None gesetzt.

    Der ältere Schalter „Alle Störungen melden“ und die ältere Ausnahmenliste entfallen (die neuen
    Felder ersetzen sie), ältere Regeln nur mit dem Schalter."""
    data = {
        **{key: None for key in (*_NOTIFY_CLEARABLE, CONF_NOTIFY_ALL, CONF_EXCLUDED, CONF_MON_DISABLE_PRESENCE)},
        **flat,
    }
    data.pop(CONF_NAME, None)
    if data.pop(CONF_CLEAR_RULES, False):
        data[CONF_MONITOR_RULES] = None
    return data


class MonitorOptions:
    """Konfigurationsseite des Integrationsmonitors (kein Menü, der Name ist ein Feld)."""

    async def async_step_mon_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_monitor(flat)
            if not errors:
                name = (flat.get(CONF_NAME) or "").strip()
                self.hass.config_entries.async_update_subentry(
                    self._get_entry(),
                    subentry,
                    title=instance_title(
                        self.hass, self.function_type, clean_instance_name(self.function_type, name)
                    ),
                    data={**subentry.data, **monitor_data(flat)},
                )
                return self.async_abort(reason="reconfigure_successful")
            defaults = {**defaults, **flat}
        return self.async_show_form(
            step_id="mon_settings",
            data_schema=_monitor_schema(
                self.hass, defaults, new=False, with_legacy=bool(self._current.get(CONF_MONITOR_RULES))
            ),
            errors=errors,
        )
