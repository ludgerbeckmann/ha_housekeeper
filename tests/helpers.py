"""Hilfen für Tests der Einstellungsdialoge mit den Abschnitten Allgemein/Benachrichtigungen."""

NOTIFY_KEYS = (
    "mobile_enabled",
    "mobile_targets",
    "mobile_action",
    "tts_enabled",
    "tts_entity",
    "tts_player",
    "persistent_enabled",
    "message",
    "repeat_message",
    "clear_after_hours",
    "critical",
)


def sectioned(flat: dict) -> dict:
    """Flache Einstellungen in die Abschnitte des Formulars verteilen."""
    flat = {k: v for k, v in flat.items() if k != "function_type"}
    return {
        "general": {k: v for k, v in flat.items() if k not in NOTIFY_KEYS},
        "notifications": {k: v for k, v in flat.items() if k in NOTIFY_KEYS},
    }


def is_menu(result) -> bool:
    """Das Konfigurationsmenü ist ein natives Home-Assistant-Menü."""
    from homeassistant.data_entry_flow import FlowResultType

    return result["type"] is FlowResultType.MENU


def menu_options(result) -> list[str]:
    return list(result["menu_options"])


# --- Hub und Untereintrag --------------------------------------------------------------------------------

from homeassistant.config_entries import ConfigSubentryDataWithId  # noqa: E402
from homeassistant.util import ulid as ulid_util  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.ha_housekeeper.const import DOMAIN, FUNCTION_TITLES  # noqa: E402


class FunctionEntry:
    """Test-Sicht auf einen Hub mit genau einem Untereintrag (so wie früher ein Eintrag).

    `entry_id` ist die ID des Untereintrags (Controller, Entitäten, Store), `hub_id` die des Hubs
    (setup/reload). `options` und `data` liefern die Daten des Untereintrags.
    """

    def __init__(self, hub: MockConfigEntry, subentry_id: str) -> None:
        self.hub = hub
        self.entry_id = subentry_id
        self.hub_id = hub.entry_id

    @property
    def sub(self):
        """Der Untereintrag als „Eintrag“ für Controller und Reparaturhinweise."""
        from custom_components.ha_housekeeper.subentry import SubentryEntry

        return SubentryEntry(self.hub, self.subentry)

    @property
    def subentry(self):
        return self.hub.subentries[self.entry_id]

    @property
    def options(self) -> dict:
        return dict(self.subentry.data)

    data = options

    @property
    def title(self) -> str:
        return self.subentry.title

    @property
    def state(self):
        return self.hub.state

    def add_to_hass(self, hass) -> None:
        self.hub.add_to_hass(hass)


def make_entry(domain=DOMAIN, title="Mock", data=None, options=None, unique_id=None, **_) -> FunctionEntry:
    """Hub (Funktionstyp aus `data`) mit einem Untereintrag anlegen."""
    data = dict(data or {})
    function_type = data.pop("function_type")
    merged = {**data, **(options or {})}
    subentry_id = ulid_util.ulid_now()
    hub = MockConfigEntry(
        domain=DOMAIN,
        title=FUNCTION_TITLES[function_type][0],
        data={"function_type": function_type, "hub": True},
        unique_id=f"hub:{function_type}",
        subentries_data=[
            ConfigSubentryDataWithId(
                data=merged, subentry_type=function_type, title=title,
                unique_id=unique_id, subentry_id=subentry_id)
        ],
    )
    return FunctionEntry(hub, subentry_id)


async def reconfigure(hass, entry: FunctionEntry):
    """Konfigurieren-Menü einer Instanz öffnen."""
    return await hass.config_entries.subentries.async_init(
        (entry.hub_id, entry.hub.data["function_type"]),
        context={"source": "reconfigure", "subentry_id": entry.entry_id},
    )


async def add_instance(hass, entry: FunctionEntry):
    """Formular „Instanz hinzufügen“ eines Hubs öffnen."""
    return await hass.config_entries.subentries.async_init(
        (entry.hub_id, entry.hub.data["function_type"]), context={"source": "user"}
    )


def update_entry(hass, entry: FunctionEntry, options: dict) -> None:
    """Einstellungen einer Instanz ändern (wie das Speichern im Konfigurieren-Dialog)."""
    hass.config_entries.async_update_subentry(
        entry.hub, entry.subentry, data={**entry.subentry.data, **options}
    )
