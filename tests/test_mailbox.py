"""Tests für Config-Flow und Funktion Benachrichtigung Briefkasten."""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

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


GENERAL_KEYS = ("name", "vibration_sensor", "debounce_seconds", "auto_reset_hours")


def _sections(flat: dict) -> dict:
    """Flache Einstellungen in die zwei Formularabschnitte verteilen."""
    flat = {k: v for k, v in flat.items() if k != "function_type"}
    return {
        "general": {k: v for k, v in flat.items() if k in GENERAL_KEYS},
        "notifications": {k: v for k, v in flat.items() if k not in GENERAL_KEYS},
    }


async def _setup(hass: HomeAssistant, **over):
    entry = MockConfigEntry(domain=DOMAIN, title="Briefkasten", data={**DATA, **over})
    entry.add_to_hass(hass)
    hass.states.async_set(SENSOR, "off")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "mailbox"}
    )
    assert result["step_id"] == "mailbox"
    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _sections({**DATA, "mobile_enabled": False, "persistent_enabled": False}),
    )
    assert bad["errors"] == {"base": "no_method"}
    ok = await hass.config_entries.flow.async_configure(
        result["flow_id"], _sections(DATA)
    )
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["function_type"] == "mailbox"
    # gespeichert wird flach, unabhängig von den Abschnitten des Formulars
    assert ok["data"]["vibration_sensor"] == SENSOR and ok["data"]["message"] == "Post!"
    assert "general" not in ok["data"] and "notifications" not in ok["data"]


async def test_form_has_two_expanded_sections(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "mailbox"}
    )
    schema = result["data_schema"].schema
    assert [str(key) for key in schema] == ["general", "notifications"]
    for sect in schema.values():
        assert sect.options["collapsed"] is False
    fields = {str(k) for k in schema[next(k for k in schema if str(k) == "general")].schema.schema}
    assert fields == {"name", "vibration_sensor", "debounce_seconds", "auto_reset_hours"}
    notify = {str(k) for k in schema[next(k for k in schema if str(k) == "notifications")].schema.schema}
    assert {"mobile_enabled", "mobile_targets", "mobile_action", "tts_enabled", "tts_entity",
            "tts_player", "persistent_enabled", "message", "repeat_message"} == notify


async def test_options_flow_sections_and_clearing(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "mailbox"
    assert {str(k) for k in result["data_schema"].schema} == {"general", "notifications"}
    general = {str(k) for k in next(
        v for k, v in result["data_schema"].schema.items() if str(k) == "general").schema.schema}
    assert "name" not in general                     # Name nur beim Hinzufügen
    flat = {k: v for k, v in DATA.items() if k not in ("name", "mobile_targets")}
    flat.update(mobile_enabled=False, persistent_enabled=True, debounce_seconds=45)
    done = await hass.config_entries.options.async_configure(result["flow_id"], _sections(flat))
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["debounce_seconds"] == 45
    assert entry.options["mobile_targets"] is None    # geleertes Feld überdeckt die Daten


async def test_options_flow_sections_validation(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flat = {k: v for k, v in DATA.items() if k != "name"}
    flat.update(mobile_enabled=False, persistent_enabled=False)
    bad = await hass.config_entries.options.async_configure(result["flow_id"], _sections(flat))
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

    assert await hass.config_entries.async_unload(entry.entry_id)


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


async def test_push_targets_show_device_names(hass: HomeAssistant) -> None:
    from custom_components.ha_housekeeper.config_flow import _mobile_services

    MockConfigEntry(
        domain="mobile_app", data={"device_name": "iPhone Ludger", "webhook_id": "a"}
    ).add_to_hass(hass)
    MockConfigEntry(
        domain="mobile_app", data={"device_name": "iPad von Britta", "webhook_id": "b"}
    ).add_to_hass(hass)
    for service in ("mobile_app_iphone_ludger", "mobile_app_ipad_von_britta", "mobile_app_ohne_geraet", "andere"):
        async_mock_service(hass, "notify", service)

    options = _mobile_services(hass)
    assert [(o["value"], o["label"]) for o in options] == [
        ("mobile_app_ipad_von_britta", "iPad von Britta (mobile_app_ipad_von_britta)"),
        ("mobile_app_iphone_ludger", "iPhone Ludger (mobile_app_iphone_ludger)"),
        ("mobile_app_ohne_geraet", "mobile_app_ohne_geraet"),
    ]


async def test_push_targets_in_flow_schema(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain="mobile_app", data={"device_name": "iPhone Ludger", "webhook_id": "a"}
    ).add_to_hass(hass)
    async_mock_service(hass, "notify", "mobile_app_iphone_ludger")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "mailbox"}
    )
    assert result["step_id"] == "mailbox"
    ok = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _sections({**DATA, "mobile_targets": ["mobile_app_iphone_ludger"]}),
    )
    assert ok["data"]["mobile_targets"] == ["mobile_app_iphone_ludger"]
