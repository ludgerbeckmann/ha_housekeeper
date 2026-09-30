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
)


def sectioned(flat: dict) -> dict:
    """Flache Einstellungen in die Abschnitte des Formulars verteilen."""
    flat = {k: v for k, v in flat.items() if k != "function_type"}
    return {
        "general": {k: v for k, v in flat.items() if k not in NOTIFY_KEYS},
        "notifications": {k: v for k, v in flat.items() if k in NOTIFY_KEYS},
    }


def _action_options(result) -> list[str]:
    schema = result["data_schema"].schema
    key = next(k for k in schema if str(k) == "action")
    return [o if isinstance(o, str) else o["value"] for o in schema[key].config["options"]]


def is_menu(result) -> bool:
    """Das Menü ist ein Formular mit der Auswahl „action“ (Liste und „Weiter“)."""
    from homeassistant.data_entry_flow import FlowResultType

    schema = result.get("data_schema")
    return (
        result["type"] is FlowResultType.FORM
        and schema is not None
        and any(str(k) == "action" for k in schema.schema)
    )


def menu_options(result) -> list[str]:
    return _action_options(result)
