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

CHOICE_REPORT = "report"
CHOICE_KNOWN = "known"
CHOICE_UNTIL = "until_recovery"
CHOICES = [CHOICE_REPORT, CHOICE_KNOWN, CHOICE_UNTIL]


class MonitorReviewFlow(RepairsFlow):
    """Eine Seite: je gemeldeter Störung ein Dropdown (weiter melden / normal / normal bis zur Wiederkehr).

    Die Zeile einer Störung ist ihr Text; er dient zugleich als Feldname, denn Beschriftungen
    für wechselnde Zeilen lassen sich nicht übersetzen.
    """

    def __init__(self, controller: IntegrationMonitorController | None) -> None:
        self._controller = controller
        self._fields: dict[str, str] = {}  # Zeilentext -> ID des Eintrags

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Start: Home Assistant übergibt hier Startdaten (`issue_id`), das ist kein Formular."""
        return await self.async_step_review()

    async def async_step_review(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        controller = self._controller
        pending = controller.pending_review() if controller else []
        if not pending:
            return self.async_abort(reason="nothing_to_review")
        if user_input is not None and self._fields:
            known: list[str] = []
            until: list[str] = []
            for label, eid in self._fields.items():
                choice = user_input.get(label, CHOICE_REPORT)
                if choice == CHOICE_KNOWN:
                    known.append(eid)
                elif choice == CHOICE_UNTIL:
                    until.append(eid)
            await controller.async_review(list(self._fields.values()), known, until)
            return self.async_create_entry(data={})
        labels = {eid: await controller.fault_label(eid) for eid in pending}
        self._fields = {}
        for eid, label in sorted(labels.items(), key=lambda item: item[1].casefold()):
            unique, n = label, 2
            while unique in self._fields:
                unique, n = f"{label} ({n})", n + 1
            self._fields[unique] = eid
        choice = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=CHOICES,
                translation_key="monitor_review_choice",
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
        return self.async_show_form(
            step_id="review",
            data_schema=vol.Schema({vol.Optional(label, default=CHOICE_REPORT): choice for label in self._fields}),
            description_placeholders={
                "count": str(len(pending)),
                "faults": "\n".join(f"{i}. {label}" for i, label in enumerate(self._fields, 1)),
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Formular zu einem behebbaren Hinweis dieser Integration."""
    controller = hass.data.get(DOMAIN, {}).get((data or {}).get("entry_id"))
    return MonitorReviewFlow(
        controller if isinstance(controller, IntegrationMonitorController) else None
    )
