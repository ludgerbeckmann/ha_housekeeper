"""Gruppenadressen des in der KNX-Integration importierten ETS-Projekts (nur zur Auswahl im Dialog)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

# Speicherdatei der KNX-Integration mit dem importierten ETS-Projekt (`.storage/knx/knx_project.json`)
STORAGE_KEY = "knx/knx_project.json"
STORAGE_VERSION = 1


async def async_project_addresses(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Gruppenadressen des ETS-Projekts: [{address, name, main, sub}], nach Adresse sortiert.

    `main`/`sub` sind der Haupt- und Untertyp des Datentyps (`None`, wenn im Projekt keiner
    hinterlegt ist). Ohne importiertes Projekt oder bei geändertem Format ist die Liste leer;
    die Felder bleiben dann freie Eingabe."""
    try:
        project = await Store(hass, STORAGE_VERSION, STORAGE_KEY).async_load()
        raw = project["group_addresses"].values() if isinstance(project, dict) else []
        found = []
        for item in raw:
            dpt = item.get("dpt") or {}
            found.append(
                {
                    "address": str(item["address"]),
                    "name": str(item.get("name") or ""),
                    "main": dpt.get("main"),
                    "sub": dpt.get("sub"),
                }
            )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Gruppenadressen des KNX-Projekts nicht lesbar", exc_info=True)
        return []
    return sorted(found, key=lambda item: _sort_key(item["address"]))


def _sort_key(address: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in address.split("/"))
    except ValueError:
        return (10**6,)


def address_label(item: dict[str, Any]) -> str:
    """„1/2/3 – Name (1.001)“ für das Dropdown."""
    label = f"{item['address']} – {item['name']}" if item["name"] else item["address"]
    if item["main"] is not None:
        sub = f".{int(item['sub']):03d}" if item["sub"] is not None else ""
        label += f" ({item['main']}{sub})"
    return label
