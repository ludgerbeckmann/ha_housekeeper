"""Tests für Config-Flow und Funktion Benachrichtigung Briefkasten."""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from .helpers import is_menu, make_entry, reconfigure, new_instance
from custom_components.ha_housekeeper.const import DEFAULT_REPEAT_MESSAGE, DOMAIN

SENSOR = "binary_sensor.briefkasten_vibration"
DATA = {
    "function_type": "mailbox",
    "name": "Briefkasten",
    "vibration_sensor": SENSOR,
    "mobile_enabled": True,
    "mobile_targets": ["mobile_app_iphone"],
    "mobile_action": True,
    "tts_enabled": False,
    "persistent_enabled": True,
    "message": "Post!",
    "debounce_seconds": 0,
    "auto_reset_hours": 0,
}


GENERAL_KEYS = ("name", "vibration_sensor", "delivery_contact", "empty_contact",
                "debounce_seconds", "auto_reset_hours")


def _sections(flat: dict) -> dict:
    """Flache Einstellungen in die zwei Formularabschnitte verteilen."""
    flat = {k: v for k, v in flat.items() if k != "function_type"}
    return {
        "general": {k: v for k, v in flat.items() if k in GENERAL_KEYS},
        "notifications": {k: v for k, v in flat.items() if k not in GENERAL_KEYS},
    }


async def _setup(hass: HomeAssistant, **over):
    entry = make_entry(domain=DOMAIN, title="Briefkasten", data={**DATA, **over})
    entry.add_to_hass(hass)
    hass.states.async_set(SENSOR, "off")
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "mailbox")
    assert result["step_id"] == "new_mailbox"
    bad = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        _sections({**DATA, "mobile_enabled": False, "persistent_enabled": False}),
    )
    assert bad["errors"] == {"base": "no_method"}
    ok = await hass.config_entries.subentries.async_configure(
        result["flow_id"], _sections(DATA)
    )
    assert ok["type"] is FlowResultType.CREATE_ENTRY

    # gespeichert wird flach, unabhängig von den Abschnitten des Formulars
    assert ok["data"]["vibration_sensor"] == SENSOR and ok["data"]["message"] == "Post!"
    assert "general" not in ok["data"] and "notifications" not in ok["data"]


async def test_form_has_two_expanded_sections(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "mailbox")
    schema = result["data_schema"].schema
    assert [str(key) for key in schema] == ["general", "notifications"]
    for sect in schema.values():
        assert sect.options["collapsed"] is False
    fields = {str(k) for k in schema[next(k for k in schema if str(k) == "general")].schema.schema}
    assert fields == {"name", "vibration_sensor", "delivery_contact", "empty_contact",
                      "debounce_seconds", "auto_reset_hours"}
    notify = {str(k) for k in schema[next(k for k in schema if str(k) == "notifications")].schema.schema}
    assert {"mobile_enabled", "mobile_targets", "mobile_action", "tts_enabled", "tts_entity",
            "tts_player", "persistent_enabled", "message", "repeat_message"} == notify


def _settings_sections(flat: dict) -> dict:
    """Eingaben der Einstellungsseite: wie die Abschnitte beim Anlegen, dazu „Empfindlichkeit“."""
    sensitivity_keys = ("sensitivity_entity", "sensitivity_value")
    sections = _sections({k: v for k, v in flat.items() if k not in sensitivity_keys})
    sections["sensitivity"] = {k: v for k, v in flat.items() if k in sensitivity_keys}
    return sections


async def test_options_flow_sections_and_clearing(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await reconfigure(hass, entry)
    assert not is_menu(result) and result["step_id"] == "mailbox_settings"
    schema = result["data_schema"].schema
    assert [str(k) for k in schema] == ["general", "sensitivity", "notifications"]
    assert [str(k) for k, sec in schema.items() if not sec.options["collapsed"]] == ["general", "notifications"]
    general = {str(k) for k in next(v for k, v in schema.items() if str(k) == "general").schema.schema}
    assert "name" in general                         # Name steht als Feld auf der Seite
    sensitivity = {str(k) for k in next(v for k, v in schema.items() if str(k) == "sensitivity").schema.schema}
    assert sensitivity == {"sensitivity_entity"}     # ohne gespeicherte Entität noch kein Wertfeld
    flat = {k: v for k, v in DATA.items() if k not in ("mobile_targets",)}
    flat.update(mobile_enabled=False, persistent_enabled=True, debounce_seconds=45)
    done = await hass.config_entries.subentries.async_configure(result["flow_id"], _settings_sections(flat))
    assert done["reason"] == "reconfigure_successful"
    assert entry.options["debounce_seconds"] == 45
    assert entry.options["mobile_targets"] is None    # geleertes Feld überdeckt die Daten


async def test_options_flow_sections_validation(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await reconfigure(hass, entry)
    flat = dict(DATA)
    flat.update(mobile_enabled=False, persistent_enabled=False)
    bad = await hass.config_entries.subentries.async_configure(
        result["flow_id"], _settings_sections(flat))
    assert bad["errors"] == {"base": "no_method"}


async def test_trigger_notify_and_reset(hass: HomeAssistant) -> None:
    notify = async_mock_service(hass, "notify", "mobile_app_iphone")
    persist = async_mock_service(hass, "persistent_notification", "create")
    dismiss = async_mock_service(hass, "persistent_notification", "dismiss")
    entry = await _setup(hass)
    assert hass.states.get("binary_sensor.briefkasten_mail_present").state == "off"

    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.briefkasten_mail_present").state == "on"
    assert len(notify) == 1 and len(persist) == 1
    actions = notify[0].data["data"]["actions"]
    assert actions[0]["title"] == "Briefkasten geleert"

    # Zweite Vibration: erneuter Hinweis mit Möglichkeit zu bestätigen
    hass.states.async_set(SENSOR, "off")
    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    assert len(notify) == 2 and len(persist) == 2
    assert notify[1].data["message"] == DEFAULT_REPEAT_MESSAGE
    assert notify[1].data["data"]["tag"] == notify[0].data["data"]["tag"]
    assert notify[1].data["data"]["actions"] == actions
    assert hass.states.get("binary_sensor.briefkasten_mail_present").state == "on"

    # iOS-Aktion "Briefkasten geleert"
    hass.bus.async_fire("mobile_app_notification_action", {"action": actions[0]["action"]})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.briefkasten_mail_present").state == "off"
    assert len(dismiss) == 1
    assert notify[-1].data["message"] == "clear_notification"

    # Button
    hass.states.async_set(SENSOR, "off")
    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.briefkasten_mailbox_emptied"}, blocking=True
    )
    assert hass.states.get("binary_sensor.briefkasten_mail_present").state == "off"

    assert await hass.config_entries.async_unload(entry.hub_id)


async def test_action_disabled(hass: HomeAssistant) -> None:
    notify = async_mock_service(hass, "notify", "mobile_app_iphone")
    await _setup(hass, mobile_action=False, persistent_enabled=False)
    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    assert "actions" not in notify[0].data["data"]


async def test_repeat_message_custom_and_debounce(hass: HomeAssistant) -> None:
    notify = async_mock_service(hass, "notify", "mobile_app_iphone")
    await _setup(hass, repeat_message="Nochmal!", debounce_seconds=60, persistent_enabled=False)
    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    hass.states.async_set(SENSOR, "off")
    hass.states.async_set(SENSOR, "on")       # innerhalb der Sperrzeit
    await hass.async_block_till_done()
    assert len(notify) == 1
    ctrl = hass.data[DOMAIN][next(iter(hass.data[DOMAIN]))]
    ctrl._last_trigger -= 120                 # Sperrzeit abgelaufen
    hass.states.async_set(SENSOR, "off")
    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    assert [n.data["message"] for n in notify] == ["Post!", "Nochmal!"]


async def test_push_targets_in_flow_schema(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain="mobile_app", data={"device_name": "iPhone Ludger", "webhook_id": "a"}
    ).add_to_hass(hass)
    async_mock_service(hass, "notify", "mobile_app_iphone_ludger")
    result = await new_instance(hass, "mailbox")
    assert result["step_id"] == "new_mailbox"
    ok = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        _sections({**DATA, "mobile_targets": ["mobile_app_iphone_ludger"]}),
    )
    assert ok["data"]["mobile_targets"] == ["mobile_app_iphone_ludger"]


DELIVERY = "binary_sensor.briefkasten_klappe"
EMPTY = "binary_sensor.briefkasten_tuer"
CONTACTS = {"vibration_sensor": None, "delivery_contact": DELIVERY, "empty_contact": EMPTY}


async def test_sensor_either_or_validation(hass: HomeAssistant) -> None:
    flow = hass.config_entries.subentries
    cases = {
        "sensor_either_or": {"vibration_sensor": SENSOR, "delivery_contact": DELIVERY, "empty_contact": EMPTY},
        "no_sensor": {"vibration_sensor": None},
        "contacts_incomplete": {"vibration_sensor": None, "delivery_contact": DELIVERY},
    }
    for error, over in cases.items():
        result = await new_instance(hass, "mailbox")
        data = {k: v for k, v in {**DATA, **over}.items() if v is not None}
        bad = await flow.async_configure(result["flow_id"], _sections(data))
        assert bad["errors"] == {"base": error}, error
    result = await new_instance(hass, "mailbox")
    data = {k: v for k, v in {**DATA, **CONTACTS}.items() if v is not None}
    ok = await flow.async_configure(result["flow_id"], _sections(data))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["delivery_contact"] == DELIVERY and "vibration_sensor" not in ok["data"]


async def test_settings_switch_to_contacts_clears_vibration(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await reconfigure(hass, entry)
    flat = {k: v for k, v in {**DATA, **CONTACTS}.items() if v is not None}
    flat.update(mobile_enabled=False, persistent_enabled=True)
    done = await hass.config_entries.subentries.async_configure(result["flow_id"], _settings_sections(flat))
    assert done["reason"] == "reconfigure_successful"
    assert entry.options["vibration_sensor"] is None and entry.options["empty_contact"] == EMPTY


async def test_contacts_delivery_and_emptied(hass: HomeAssistant) -> None:
    notify = async_mock_service(hass, "notify", "mobile_app_iphone")
    async_mock_service(hass, "persistent_notification", "create")
    async_mock_service(hass, "persistent_notification", "dismiss")
    hass.states.async_set(DELIVERY, "off")
    hass.states.async_set(EMPTY, "off")
    entry = await _setup(hass, **CONTACTS)
    mail = "binary_sensor.briefkasten_mail_present"
    last = er_entity(hass, "sensor", "last_emptied", entry)

    hass.states.async_set(EMPTY, "on")            # Tür auf ohne Post: nichts
    await hass.async_block_till_done()
    assert hass.states.get(mail).state == "off" and hass.states.get(last).state == "unknown"
    hass.states.async_set(EMPTY, "off")

    hass.states.async_set(DELIVERY, "on")         # Einwurf
    await hass.async_block_till_done()
    assert hass.states.get(mail).state == "on" and len(notify) == 1
    hass.states.async_set(DELIVERY, "off")

    hass.states.async_set(EMPTY, "on")            # Entnahme
    await hass.async_block_till_done()
    assert hass.states.get(mail).state == "off"
    assert hass.states.get(last).state not in ("unknown", "unavailable")


async def test_empty_contact_ignored_within_debounce(hass: HomeAssistant) -> None:
    async_mock_service(hass, "notify", "mobile_app_iphone")
    async_mock_service(hass, "persistent_notification", "create")
    hass.states.async_set(DELIVERY, "off")
    hass.states.async_set(EMPTY, "off")
    await _setup(hass, **CONTACTS, debounce_seconds=60)
    hass.states.async_set(DELIVERY, "on")
    await hass.async_block_till_done()
    hass.states.async_set(EMPTY, "on")            # kurz nach dem Einwurf: ignoriert
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.briefkasten_mail_present").state == "on"


def er_entity(hass, platform, key, entry):
    from homeassistant.helpers import entity_registry as er

    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
