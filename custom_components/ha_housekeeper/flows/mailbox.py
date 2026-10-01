"""Dialoge der Funktion Benachrichtigung Briefkasten."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
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
    DEFAULT_NAME,
    DEFAULT_REPEAT_MESSAGE,
)
from .common import (
    _flatten_sections,
    _notify_fields,
    _number,
    _sections_schema,
    _suggest,
    _validate_notify,
    _with_cleared,
)


def _mailbox_schema(
    hass: HomeAssistant, defaults: dict[str, Any], with_name: bool
) -> vol.Schema:
    """Formular in zwei ausgeklappte Abschnitte: Allgemein und Benachrichtigungen."""
    general: dict[Any, Any] = {}
    if with_name:
        general[
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))
        ] = str
    general[
        vol.Required(
            CONF_VIBRATION_SENSOR, description=_suggest(CONF_VIBRATION_SENSOR, defaults)
        )
    ] = selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor"))
    general[
        vol.Required(
            CONF_DEBOUNCE, default=defaults.get(CONF_DEBOUNCE, DEFAULT_DEBOUNCE)
        )
    ] = _number(0, 3600, "s")
    general[
        vol.Required(
            CONF_AUTO_RESET_HOURS,
            default=defaults.get(CONF_AUTO_RESET_HOURS, DEFAULT_AUTO_RESET_HOURS),
        )
    ] = _number(0, 168, "h")
    if not with_name:
        # nur in den Einstellungen: Entität, an die die Empfindlichkeit auf Anforderung geht
        general[
            vol.Optional(
                CONF_SENSITIVITY_ENTITY,
                description=_suggest(CONF_SENSITIVITY_ENTITY, defaults),
            )
        ] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["number", "select"])
        )

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

    return _sections_schema(general, notifications)


class MailboxOptions:
    """Options-Flow-Schritte: Benachrichtigung Briefkasten."""

    async def async_step_mailbox_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["mailbox"]
        if self._current.get(CONF_SENSITIVITY_ENTITY):
            options.append("mailbox_sensitivity")
        options.append("done")
        return await self._menu("mailbox_menu", options, user_input)

    async def async_step_mailbox(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = self._current
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate_notify(flat, require_method=True)
            if not errors:
                data = _with_cleared(flat)
                # Die Entität wird nur hinterlegt; der Wert wird über den Menüpunkt „Empfindlichkeit
                # einstellen“ gesetzt. Er bleibt erhalten, solange die Entität dieselbe ist.
                if flat.get(CONF_SENSITIVITY_ENTITY) == self._current.get(CONF_SENSITIVITY_ENTITY):
                    data[CONF_SENSITIVITY_VALUE] = self._current.get(CONF_SENSITIVITY_VALUE)
                self._save(data)
                return await self.async_step_mailbox_menu()
            defaults = flat
        return self.async_show_form(
            step_id="mailbox",
            data_schema=_mailbox_schema(self.hass, defaults, with_name=False),
            errors=errors,
        )

    async def async_step_mailbox_sensitivity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wert der Empfindlichkeit, passend zur gewählten Entität (Zahl oder Stufe)."""
        entity_id = self._current.get(CONF_SENSITIVITY_ENTITY)
        if not entity_id:
            return await self.async_step_mailbox_menu()
        if user_input is not None:
            self._save({CONF_SENSITIVITY_VALUE: user_input[CONF_SENSITIVITY_VALUE]})
            return await self.async_step_mailbox_menu()
        state = self.hass.states.get(entity_id)
        attrs = state.attributes if state else {}
        if entity_id.startswith("select."):
            options = [str(o) for o in attrs.get("options") or []]
            value_selector: Any = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    custom_value=not options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            value_selector = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=float(attrs.get("min", -1000000)),
                    max=float(attrs.get("max", 1000000)),
                    step=attrs.get("step", "any"),
                    mode=selector.NumberSelectorMode.BOX,
                )
            )
        return self.async_show_form(
            step_id="mailbox_sensitivity",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SENSITIVITY_VALUE,
                        description=_suggest(CONF_SENSITIVITY_VALUE, self._current),
                    ): value_selector
                }
            ),
            description_placeholders={"entity": entity_id},
        )
