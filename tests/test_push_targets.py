"""Push-Ziele: native Geräteauswahl der Companion-App, intern der Dienst notify.mobile_app_<gerät>."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.ha_housekeeper.flows.common import _mobile_selector, _mobile_suggest
from custom_components.ha_housekeeper.const import DOMAIN
from custom_components.ha_housekeeper.notify import (
    Notifier,
    device_id_for_service,
    mobile_service_for_device,
    resolve_mobile_services,
    targets_for_form,
)


def add_device(hass: HomeAssistant, name: str, domain: str = "mobile_app") -> str:
    """Companion-App-Gerät (Config-Entry und Gerät) anlegen; liefert die Geräte-ID."""
    entry = MockConfigEntry(domain=domain, data={"device_name": name, "webhook_id": name})
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(domain, name)}, name=name)
    return device.id


def test_selector_is_native_device_picker_for_companion_app() -> None:
    config = _mobile_selector().config
    assert config["integration"] == "mobile_app" and config["multiple"] is True


async def test_device_resolves_to_push_service(hass: HomeAssistant) -> None:
    ludger = add_device(hass, "iPhone Ludger")
    britta = add_device(hass, "iPhone Britta")
    assert mobile_service_for_device(hass, ludger) == "mobile_app_iphone_ludger"
    assert mobile_service_for_device(hass, "gibt-es-nicht") is None
    assert resolve_mobile_services(hass, [ludger, britta]) == [
        "mobile_app_iphone_ludger", "mobile_app_iphone_britta"]


async def test_legacy_service_names_still_work_and_duplicates_are_removed(hass: HomeAssistant) -> None:
    ludger = add_device(hass, "iPhone Ludger")
    assert resolve_mobile_services(
        hass, ["mobile_app_iphone_ludger", "notify.mobile_app_andere", ludger, "mobile_app_andere"]
    ) == ["mobile_app_iphone_ludger", "mobile_app_andere"]
    assert resolve_mobile_services(hass, None) == [] and resolve_mobile_services(hass, []) == []


async def test_device_without_companion_app_is_skipped(hass: HomeAssistant) -> None:
    other = add_device(hass, "Lampe", domain="hue")
    ludger = add_device(hass, "iPhone Ludger")
    assert resolve_mobile_services(hass, [other, ludger]) == ["mobile_app_iphone_ludger"]


async def test_legacy_names_are_mapped_to_devices_for_the_form(hass: HomeAssistant) -> None:
    ludger = add_device(hass, "iPhone Ludger")
    assert device_id_for_service(hass, "mobile_app_iphone_ludger") == ludger
    assert device_id_for_service(hass, "notify.mobile_app_iphone_ludger") == ludger
    assert device_id_for_service(hass, "mobile_app_unbekannt") is None
    # nicht zuordenbare Einträge bleiben stehen (nichts geht verloren), Geräte bleiben Geräte
    assert targets_for_form(hass, ["mobile_app_iphone_ludger", "eigene_gruppe", ludger]) == [
        ludger, "eigene_gruppe", ludger]
    assert targets_for_form(hass, None) == []
    assert _mobile_suggest(hass, {}) == {}
    assert _mobile_suggest(hass, {"mobile_targets": ["mobile_app_iphone_ludger"]}) == {
        "suggested_value": [ludger]}
    assert _mobile_suggest(hass, {"mobile_targets": None}) == {"suggested_value": []}


async def test_notifier_sends_once_per_device_and_keeps_actions(hass: HomeAssistant) -> None:
    ludger = add_device(hass, "iPhone Ludger")
    britta = add_device(hass, "iPhone Britta")
    ludger_calls = async_mock_service(hass, "notify", "mobile_app_iphone_ludger")
    britta_calls = async_mock_service(hass, "notify", "mobile_app_iphone_britta")
    options = {"mobile_enabled": True, "mobile_targets": [ludger, "mobile_app_iphone_ludger", britta]}
    notifier = Notifier(
        hass, lambda key, default=None: options.get(key, default), "tag", lambda: "Titel")
    await notifier.async_send(
        "Hallo", kind="x", actions=[{"action": "A", "title": "Ja"}], extra={"push": {"x": 1}})
    assert len(ludger_calls) == 1 and len(britta_calls) == 1
    data = ludger_calls[0].data["data"]
    assert data["actions"] == [{"action": "A", "title": "Ja"}] and data["push"] == {"x": 1}
    await notifier.async_clear("x")
    assert ludger_calls[-1].data["message"] == "clear_notification" and len(ludger_calls) == 2


async def test_form_prefills_legacy_targets_as_devices(hass: HomeAssistant) -> None:
    ludger = add_device(hass, "iPhone Ludger")
    hass.states.async_set("binary_sensor.briefkasten_vibration", "off")
    entry = MockConfigEntry(
        domain=DOMAIN, title="Briefkasten",
        data={"function_type": "mailbox", "name": "Briefkasten",
              "vibration_sensor": "binary_sensor.briefkasten_vibration", "mobile_enabled": True,
              "mobile_targets": ["mobile_app_iphone_ludger"], "persistent_enabled": False,
              "message": "Post!", "debounce_seconds": 0, "auto_reset_hours": 0})
    entry.add_to_hass(hass)
    async_mock_service(hass, "notify", "mobile_app_iphone_ludger")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "mailbox"})
    notifications = next(v for k, v in result["data_schema"].schema.items() if str(k) == "notifications")
    key = next(k for k in notifications.schema.schema if str(k) == "mobile_targets")
    assert key.description == {"suggested_value": [ludger]}
    # Der Eintrag selbst sendet weiter an den bisherigen Dienst
    calls = async_mock_service(hass, "notify", "mobile_app_iphone_ludger")
    hass.states.async_set("binary_sensor.briefkasten_vibration", "on")
    await hass.async_block_till_done()
    assert len(calls) == 1
