"""Reparaturformulare: „Störungen prüfen“ des Integrationsmonitors."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import DOMAIN
from .integration_monitor import IntegrationMonitorController

FIELD_KNOWN = "known"
FIELD_UNTIL = "known_until_recovery"


class MonitorReviewFlow(RepairsFlow):
    """Eine Seite: welche der gemeldeten Störungen sind normal?"""

    def __init__(self, controller: IntegrationMonitorController | None) -> None:
        self._controller = controller

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        controller = self._controller
        pending = controller.pending_review() if controller else []
        if not pending:
            return self.async_abort(reason="nothing_to_review")
        errors: dict[str, str] = {}
        if user_input is not None:
            known = list(user_input.get(FIELD_KNOWN) or [])
            until = list(user_input.get(FIELD_UNTIL) or [])
            if set(known) & set(until):
                errors["base"] = "chosen_twice"
            else:
                await controller.async_review(pending, known, until)
                return self.async_create_entry(data={})
        options = [
            selector.SelectOptionDict(value=eid, label=await controller.fault_label(eid))
            for eid in pending
        ]

        def _field() -> selector.SelectSelector:
            return selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options, multiple=True, mode=selector.SelectSelectorMode.LIST
                )
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(FIELD_KNOWN, default=list((user_input or {}).get(FIELD_KNOWN) or [])): _field(),
                    vol.Optional(FIELD_UNTIL, default=list((user_input or {}).get(FIELD_UNTIL) or [])): _field(),
                }
            ),
            errors=errors,
            description_placeholders={"count": str(len(pending))},
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Formular zu einem behebbaren Hinweis dieser Integration."""
    controller = hass.data.get(DOMAIN, {}).get((data or {}).get("entry_id"))
    return MonitorReviewFlow(
        controller if isinstance(controller, IntegrationMonitorController) else None
    )
