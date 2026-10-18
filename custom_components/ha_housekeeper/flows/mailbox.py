"""Dialoge der Funktion Benachrichtigung Briefkasten."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SubentryFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from ..const import (
    CONF_AUTO_RESET_HOURS,
    CONF_DEBOUNCE,
    CONF_MESSAGE,
    CONF_NAME,
    CONF_REPEAT_MESSAGE,
    CONF_SENSITIVITY_ENTITY,
    CONF_SENSITIVITY_VALUE,
    CONF_VIBRATION_SENSOR,
    DEFAULT_AUTO_RESET_HOURS,
    DEFAULT_DEBOUNCE,
    DEFAULT_MESSAGE,
    DEFAULT_REPEAT_MESSAGE,
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
    _suggest,
    _validate_notify,
    _with_cleared,
)


SECTION_SENSITIVITY = "sensitivity"


def _value_selector(hass: HomeAssistant, entity_id: str) -> Any:
    """Auswahl für den Empfindlichkeitswert, passend zur Entität (Zahl mit Grenzen oder deren Stufen)."""
    state = hass.states.get(entity_id)
    attrs = state.attributes if state else {}
    if entity_id.startswith("select."):
        options = [str(o) for o in attrs.get("options") or []]
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                custom_value=not options,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=float(attrs.get("min", -1000000)),
            max=float(attrs.get("max", 1000000)),
            step=attrs.get("step", "any"),
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _mailbox_schema(
    hass: HomeAssistant,
    defaults: dict[str, Any],
    with_name: bool,
    saved_entity: str | None = None,
) -> vol.Schema:
    """Die Seite: Allgemein (offen), Empfindlichkeit (nur in den Einstellungen) und Benachrichtigung.

    Der Wert der Empfindlichkeit erscheint erst, wenn eine Entität gespeichert ist (sein Typ hängt von ihr ab)."""
    general: dict[Any, Any] = {
        vol.Optional(CONF_NAME, description=_suggest(CONF_NAME, defaults)): str,
        vol.Required(
            CONF_VIBRATION_SENSOR, description=_suggest(CONF_VIBRATION_SENSOR, defaults)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
        vol.Required(
            CONF_DEBOUNCE, default=defaults.get(CONF_DEBOUNCE, DEFAULT_DEBOUNCE)
        ): _number(0, 3600, "s"),
        vol.Required(
            CONF_AUTO_RESET_HOURS,
            default=defaults.get(CONF_AUTO_RESET_HOURS, DEFAULT_AUTO_RESET_HOURS),
        ): _number(0, 168, "h"),
    }
    notifications: dict[Any, Any] = dict(_notify_fields(hass, defaults, with_action=True))
    notifications[
        vol.Required(CONF_MESSAGE, default=defaults.get(CONF_MESSAGE, DEFAULT_MESSAGE))
    ] = str
    notifications[
        vol.Required(
            CONF_REPEAT_MESSAGE,
            default=defaults.get(CONF_REPEAT_MESSAGE, DEFAULT_REPEAT_MESSAGE),
        )
    ] = str
    sections: dict[Any, Any] = {
        vol.Required(SECTION_GENERAL): section(vol.Schema(general), {"collapsed": False}),
    }
    if not with_name:
        # nur in den Einstellungen: Entität, an die die Empfindlichkeit auf Anforderung geht
        sensitivity: dict[Any, Any] = {
            vol.Optional(
                CONF_SENSITIVITY_ENTITY, description=_suggest(CONF_SENSITIVITY_ENTITY, defaults)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain=["number", "select"]))
        }
        if saved_entity:
            sensitivity[
                vol.Optional(CONF_SENSITIVITY_VALUE, description=_suggest(CONF_SENSITIVITY_VALUE, defaults))
            ] = _value_selector(hass, saved_entity)
        sections[vol.Required(SECTION_SENSITIVITY)] = section(
            vol.Schema(sensitivity), {"collapsed": True}
        )
    sections[vol.Required(SECTION_NOTIFICATIONS)] = section(
        vol.Schema(notifications), {"collapsed": False}
    )
    return vol.Schema(sections)


class MailboxOptions:
    """Konfigurationsseite des Briefkastens (kein Menü, der Name ist ein Feld)."""

    async def async_step_mailbox_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()
        saved_entity = self._current.get(CONF_SENSITIVITY_ENTITY)
        defaults = {**self._current, CONF_NAME: instance_name(subentry.title)}
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_notify(flat, require_method=True)
            if not errors:
                data = _with_cleared(flat)
                data.pop(CONF_NAME, None)
                # Der Wert gilt nur für die gespeicherte Entität: bei anderer oder leerer Entität wird er verworfen
                if flat.get(CONF_SENSITIVITY_ENTITY) != saved_entity:
                    data[CONF_SENSITIVITY_VALUE] = None
                elif flat.get(CONF_SENSITIVITY_VALUE) is None:
                    data[CONF_SENSITIVITY_VALUE] = None
                name = (flat.get(CONF_NAME) or "").strip()
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
            step_id="mailbox_settings",
            data_schema=_mailbox_schema(self.hass, defaults, with_name=False, saved_entity=saved_entity),
            errors=errors,
        )
