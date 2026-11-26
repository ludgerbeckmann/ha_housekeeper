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
MAX_ROWS = 40  # so viele Zeilen („Störung 1…40“) hat die Übersetzung; der Rest kommt beim nächsten Öffnen


class MonitorReviewFlow(RepairsFlow):
    """Eine Seite: je gemeldeter Störung ein Dropdown (weiter melden / normal / normal bis zur Wiederkehr).

    Die Zeilen heißen „Störung 1 … n“ (Beschriftungen wechselnder Zeilen lassen sich nicht
    übersetzen, das Frontend zeigt auch keinen Feldnamen an); die Beschreibung listet sie
    nummeriert, und jede Antwort nennt die Integration („Powercalc: Lampe → Weiter melden“).
    """

    def __init__(self, controller: IntegrationMonitorController | None) -> None:
        self._controller = controller
        self._fields: dict[str, str] = {}  # Feld „fault_1“ -> ID des Eintrags

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
            for field, eid in self._fields.items():
                choice = user_input.get(field, CHOICE_REPORT)
                if choice == CHOICE_KNOWN:
                    known.append(eid)
                elif choice == CHOICE_UNTIL:
                    until.append(eid)
            await controller.async_review(list(self._fields.values()), known, until)
            return self.async_create_entry(data={})
        lines = {eid: await controller.fault_label(eid) for eid in pending}
        ordered = sorted(lines, key=lambda eid: lines[eid].casefold())[:MAX_ROWS]
        texts = controller.choice_texts()
        self._fields = {f"fault_{i}": eid for i, eid in enumerate(ordered, 1)}
        schema: dict[Any, Any] = {}
        for field, eid in self._fields.items():
            name = await controller.fault_name(eid)
            schema[vol.Optional(field, default=CHOICE_REPORT)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=choice, label=f"{name} → {texts[choice]}")
                        for choice in CHOICES
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        return self.async_show_form(
            step_id="review",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "count": str(len(pending)),
                "faults": "\n".join(f"{i}. {lines[eid]}" for i, eid in enumerate(ordered, 1)),
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
