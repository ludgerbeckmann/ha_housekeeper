"""Ein Hub je Funktion, Instanzen als Untereinträge mit eigenem Gerät."""

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from .helpers import add_instance, is_menu, make_entry
from custom_components.ha_housekeeper.const import DOMAIN, clean_instance_name

BELL = {"function_type": "doorbell", "name": "Haustür", "trigger_entity": "binary_sensor.bell",
        "debounce_seconds": 0, "profiles": []}


def _hub(*subentries) -> MockConfigEntry:
    """Der eine Hub „Funktionen“ mit beliebigen Instanzen (Typ, Titel, Daten)."""
    return MockConfigEntry(
        domain=DOMAIN, title="Funktionen", unique_id="hub", data={"hub": True},
        subentries_data=[
            ConfigSubentryData(subentry_type=t, title=title, unique_id=None, data=data)
            for t, title, data in subentries
        ],
    )


def _bell(name, entity):
    return ("doorbell", name, {"name": name, "trigger_entity": entity,
                               "debounce_seconds": 0, "profiles": []})


def _hub_with_two_bells() -> MockConfigEntry:
    return _hub(_bell("Haustür", "binary_sensor.front"), _bell("Garten", "binary_sensor.garden"))


async def _setup(hass, hub):
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()


async def test_one_hub_holds_all_functions(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.front", "off")
    hass.states.async_set("binary_sensor.v", "off")
    hass.states.async_set("switch.p", "off")
    hub = _hub(
        _bell("Haustür", "binary_sensor.front"),
        ("mailbox", "Briefkasten", {"name": "Briefkasten", "vibration_sensor": "binary_sensor.v",
                                    "mobile_enabled": False, "persistent_enabled": True,
                                    "message": "x", "debounce_seconds": 0, "auto_reset_hours": 0}),
        ("pool_pump", "Garten", {"name": "Garten", "pump_entity": "switch.p"}),
    )
    await _setup(hass, hub)
    assert hub.state is ConfigEntryState.LOADED and len(hass.data[DOMAIN]) == 3
    # jede Funktion bekommt nur die Entitäten ihrer Plattformen, die Geräte heißen nur „Name“
    assert hass.states.get("switch.haustur_doorbell_active") is not None
    assert hass.states.get("binary_sensor.briefkasten_mail_present") is not None
    assert hass.states.get("switch.garten_schedule_active") is not None
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), hub.entry_id)
    assert sorted(d.name for d in devices) == ["Briefkasten", "Garten", "Haustür"]


async def test_titles_get_the_function_prefix(hass: HomeAssistant) -> None:
    for entity in ("binary_sensor.front", "binary_sensor.garden"):
        hass.states.async_set(entity, "off")
    hub = _hub(_bell("Haustür", "binary_sensor.front"),
               _bell("Doorbell", "binary_sensor.garden"),          # entspricht dem Funktionsnamen
               _bell("Doorbell: Garten", "binary_sensor.garden"))  # Präfix schon vorhanden
    await _setup(hass, hub)
    assert sorted(s.title for s in hub.subentries.values()) == [
        "Doorbell", "Doorbell: Garten", "Doorbell: Haustür"]


async def test_each_subentry_has_its_own_controller_device_and_entities(hass: HomeAssistant) -> None:
    for entity in ("binary_sensor.front", "binary_sensor.garden"):
        hass.states.async_set(entity, "off")
    hub = _hub_with_two_bells()
    await _setup(hass, hub)

    assert hub.state is ConfigEntryState.LOADED and len(hub.subentries) == 2
    assert all(sid in hass.data[DOMAIN] for sid in hub.subentries)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), hub.entry_id)
    assert sorted(d.name for d in devices) == ["Garten", "Haustür"]
    assert hass.states.get("switch.haustur_doorbell_active") is not None
    assert hass.states.get("switch.garten_doorbell_active") is not None
    registry = er.async_get(hass)
    by_subentry = {
        e.config_subentry_id for e in er.async_entries_for_config_entry(registry, hub.entry_id)
    }
    assert by_subentry == set(hub.subentries)


async def test_ringing_one_doorbell_does_not_ring_the_other(hass: HomeAssistant) -> None:
    for entity in ("binary_sensor.front", "binary_sensor.garden"):
        hass.states.async_set(entity, "off")
    hub = _hub_with_two_bells()
    await _setup(hass, hub)
    front, garden = (hass.data[DOMAIN][sid] for sid in hub.subentries)
    hass.states.async_set("binary_sensor.front", "on")
    await hass.async_block_till_done()
    assert front.last_ring is not None and garden.last_ring is None


async def test_add_instance_creates_subentry_and_reloads_hub(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.bell", "off")
    entry = make_entry(domain=DOMAIN, title="Haustür", data=BELL)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()

    result = await add_instance(hass, entry)
    assert result["step_id"] == "new_doorbell"
    hass.states.async_set("binary_sensor.garden", "off")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"general": {"name": "Garten", "trigger_entity": "binary_sensor.garden",
                     "debounce_seconds": 5}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Doorbell: Garten"
    await hass.async_block_till_done()
    assert len(hass.data[DOMAIN]) == 2                       # beide Controller laufen nach dem Neuladen
    assert hass.states.get("switch.garten_doorbell_active") is not None


async def test_reconfigure_opens_the_menu_of_that_instance(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.front", "off")
    hass.states.async_set("binary_sensor.garden", "off")
    hub = _hub_with_two_bells()
    await _setup(hass, hub)
    garden_id = next(s.subentry_id for s in hub.subentries.values() if "Garten" in s.title)
    result = await hass.config_entries.subentries.async_init(
        (hub.entry_id, "doorbell"), context={"source": "reconfigure", "subentry_id": garden_id})
    assert is_menu(result) and result["step_id"] == "bell_menu"
    assert "rename" in result["menu_options"]
    flow = hass.config_entries.subentries
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "bell_general"})
    await flow.async_configure(
        result["flow_id"], {"general": {"trigger_entity": "binary_sensor.front", "debounce_seconds": 99}})
    assert hub.subentries[garden_id].data["debounce_seconds"] == 99
    other = next(s for s in hub.subentries.values() if "Haustür" in s.title)
    assert other.data["debounce_seconds"] == 0               # die andere Instanz bleibt unverändert


async def test_rename_keeps_the_function_prefix(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.front", "off")
    hass.states.async_set("binary_sensor.garden", "off")
    hub = _hub_with_two_bells()
    await _setup(hass, hub)
    garden_id = next(s.subentry_id for s in hub.subentries.values() if "Garten" in s.title)
    flow = hass.config_entries.subentries
    result = await flow.async_init(
        (hub.entry_id, "doorbell"), context={"source": "reconfigure", "subentry_id": garden_id})
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "rename"})
    assert result["step_id"] == "rename"
    name = next(k for k in result["data_schema"].schema if str(k) == "name")
    assert name.default() == "Garten"
    result = await flow.async_configure(result["flow_id"], {"name": "Terrasse"})
    assert is_menu(result)
    assert hub.subentries[garden_id].title == "Doorbell: Terrasse"
    await hass.async_block_till_done()
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), hub.entry_id)
    assert "Terrasse" in {d.name for d in devices}           # Gerät: nur der Name


async def test_rename_removes_a_duplicated_function_name(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.front", "off")
    hass.states.async_set("binary_sensor.garden", "off")
    hub = _hub_with_two_bells()
    await _setup(hass, hub)
    garden_id = next(s.subentry_id for s in hub.subentries.values() if "Garten" in s.title)
    flow = hass.config_entries.subentries
    result = await flow.async_init(
        (hub.entry_id, "doorbell"), context={"source": "reconfigure", "subentry_id": garden_id})
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "rename"})
    await flow.async_configure(result["flow_id"], {"name": "Doorbell: Doorbell Terrasse"})
    assert hub.subentries[garden_id].title == "Doorbell: Terrasse"


async def test_native_rename_is_corrected_on_reload(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.front", "off")
    hass.states.async_set("binary_sensor.garden", "off")
    hub = _hub_with_two_bells()
    await _setup(hass, hub)
    garden = next(s for s in hub.subentries.values() if "Garten" in s.title)
    hass.config_entries.async_update_subentry(hub, garden, title="Hannahs Klingel")
    await hass.async_block_till_done()
    assert garden.title == "Doorbell: Hannahs Klingel"


async def test_removing_a_subentry_cleans_up_issues(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.front", "off")
    hass.states.async_set("binary_sensor.garden", "off")
    hub = _hub_with_two_bells()
    await _setup(hass, hub)
    garden = next(s for s in hub.subentries.values() if "Garten" in s.title)
    ir.async_create_issue(
        hass, DOMAIN, f"{garden.subentry_id}_entity_x", is_fixable=False,
        severity=ir.IssueSeverity.WARNING, translation_key="entity_missing",
        translation_placeholders={"entry": "Garten", "function": "x", "entity": "x"})
    hass.config_entries.async_remove_subentry(hub, garden.subentry_id)
    await hass.async_block_till_done()
    assert garden.subentry_id not in hass.data[DOMAIN] and len(hass.data[DOMAIN]) == 1
    assert not [i for (d, i) in ir.async_get(hass).issues if d == DOMAIN and garden.subentry_id in i]


async def test_legacy_entries_are_not_loaded_and_reported(hass: HomeAssistant) -> None:
    old = MockConfigEntry(domain=DOMAIN, title="Alte Klingel", data={**BELL})            # eine Instanz je Eintrag
    per_function = MockConfigEntry(domain=DOMAIN, title="Türklingel",
                                   data={"function_type": "doorbell", "hub": True})    # ein Hub je Funktion
    for legacy in (old, per_function):
        legacy.add_to_hass(hass)
        assert not await hass.config_entries.async_setup(legacy.entry_id)
        assert legacy.state is ConfigEntryState.SETUP_ERROR
        assert (DOMAIN, f"legacy_{legacy.entry_id}") in ir.async_get(hass).issues


async def test_removing_the_hub_removes_stores_and_issues(hass: HomeAssistant, hass_storage) -> None:
    hass.states.async_set("binary_sensor.front", "off")
    hass.states.async_set("binary_sensor.garden", "off")
    hub = _hub_with_two_bells()
    await _setup(hass, hub)
    ids = list(hub.subentries)
    for sid in ids:
        hass_storage[f"{DOMAIN}.{sid}"] = {"version": 1, "key": f"{DOMAIN}.{sid}", "data": {}}
    await hass.config_entries.async_remove(hub.entry_id)
    await hass.async_block_till_done()
    assert not any(f"{DOMAIN}.{sid}" in hass_storage for sid in ids)


async def test_all_functions_are_subentry_types(hass: HomeAssistant) -> None:
    hub = _hub()
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()
    assert set(hub.supported_subentry_types) == {
        "mailbox", "door_guard", "doorbell", "pool_pump", "knx_sonos",
        "updater", "task_planner", "alarm_clock", "integration_monitor"}


async def _new_updater(hass, data):
    hub = _hub()
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.subentries.async_init(
        (hub.entry_id, "updater"), context={"source": "user"})
    assert result["step_id"] == "new_updater"
    return result, await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"timeout_minutes": 30, **data})


async def test_name_is_empty_and_optional(hass: HomeAssistant) -> None:
    form, result = await _new_updater(hass, {})
    name = next(k for k in form["data_schema"].schema if str(k) == "name")
    assert name.default is vol.UNDEFINED and not name.description    # keine Vorgabe
    assert result["title"] == "Home Assistant Updater"               # leer = Funktionsname


async def test_name_gets_the_function_prefix(hass: HomeAssistant) -> None:
    _, result = await _new_updater(hass, {"name": "Keller"})
    assert result["title"] == "Home Assistant Updater: Keller"


@pytest.mark.parametrize("typed,expected", [
    ("Home Assistant Updater Keller", "Home Assistant Updater: Keller"),
    ("home assistant updater - Keller", "Home Assistant Updater: Keller"),
    ("Home Assistant Updater", "Home Assistant Updater"),
    ("Home Assistant Updaterei", "Home Assistant Updater: Home Assistant Updaterei"),
])
async def test_duplicated_function_name_is_removed(hass: HomeAssistant, typed, expected) -> None:
    _, result = await _new_updater(hass, {"name": typed})
    assert result["title"] == expected


def test_clean_instance_name() -> None:
    assert clean_instance_name("door_guard", "Türwächter Garagentür") == "Garagentür"
    assert clean_instance_name("door_guard", "Türwächter: Haustür") == "Haustür"
    assert clean_instance_name("door_guard", "Door guard Haustür") == "Haustür"
    assert clean_instance_name("door_guard", "Türwächterei") == "Türwächterei"
    assert clean_instance_name("door_guard", "Türwächter") == ""
    assert clean_instance_name("door_guard", "  Garage ") == "Garage"
    assert clean_instance_name("door_guard", None) == ""
    assert clean_instance_name("knx_sonos", "KNX/Sonos-Connector Büro") == "Büro"


async def test_busy_sibling_defers_the_reload_of_the_whole_hub(hass: HomeAssistant) -> None:
    """Ein klingelnder Wecker eines Hubs verhindert das Neuladen, auch wenn ein anderer geändert wird."""
    player = "media_player.bedroom"
    hass.states.async_set(player, "idle", {"volume_level": 0.5})
    for service in ("volume_set", "play_media", "media_stop"):
        async_mock_service(hass, "media_player", service)
    alarm = {"id": "a1", "name": "Wecker", "enabled": True, "time": "07:00:00",
             "weekdays": ["mon"], "players": [player],
             "media": {"media_content_id": "x", "media_content_type": "audio/mpeg"},
             "volume": 30, "snooze_minutes": 9, "auto_stop_minutes": 0}
    base = {"mobile_enabled": False, "persistent_enabled": False, "alarms": [alarm]}
    hass.states.async_set("binary_sensor.front", "off")
    hub = _hub(("alarm_clock", "A", {"name": "A", **base}),
               ("alarm_clock", "B", {"name": "B", **base}),
               _bell("Haustür", "binary_sensor.front"))
    await _setup(hass, hub)
    first_id, second_id, bell_id = list(hub.subentries)
    first, second = hass.data[DOMAIN][first_id], hass.data[DOMAIN][second_id]
    bell = hass.data[DOMAIN][bell_id]
    await first.async_ring(alarm)
    assert first.busy
    # eine Änderung an einer ganz anderen Funktion wartet ebenfalls
    hass.config_entries.async_update_subentry(
        hub, hub.subentries[bell_id], data={**hub.subentries[bell_id].data, "debounce_seconds": 7})
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][first_id] is first and hass.data[DOMAIN][bell_id] is bell
    await first.async_stop_alarm()
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][bell_id] is not bell and hass.data[DOMAIN][second_id] is not second
