"""Ein Hub je Funktion, Instanzen als Untereinträge mit eigenem Gerät."""

from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from .helpers import add_instance, is_menu, make_entry
from custom_components.ha_housekeeper.const import DOMAIN

BELL = {"function_type": "doorbell", "name": "Haustür", "trigger_entity": "binary_sensor.bell",
        "debounce_seconds": 0, "profiles": []}


def _hub_with_two_bells() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title="Türklingel", unique_id="hub:doorbell",
        data={"function_type": "doorbell", "hub": True},
        subentries_data=[
            ConfigSubentryData(subentry_type="doorbell", title="Haustür", unique_id=None,
                               data={"name": "Haustür", "trigger_entity": "binary_sensor.front",
                                     "debounce_seconds": 0, "profiles": []}),
            ConfigSubentryData(subentry_type="doorbell", title="Garten", unique_id=None,
                               data={"name": "Garten", "trigger_entity": "binary_sensor.garden",
                                     "debounce_seconds": 0, "profiles": []}),
        ],
    )


async def test_each_subentry_has_its_own_controller_device_and_entities(hass: HomeAssistant) -> None:
    for entity in ("binary_sensor.front", "binary_sensor.garden"):
        hass.states.async_set(entity, "off")
    hub = _hub_with_two_bells()
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()

    assert hub.state is ConfigEntryState.LOADED and len(hub.subentries) == 2
    assert all(sid in hass.data[DOMAIN] for sid in hub.subentries)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), hub.entry_id)
    assert sorted(d.name for d in devices) == ["Garten", "Haustür"]
    assert hass.states.get("switch.haustur_doorbell_active") is not None
    assert hass.states.get("switch.garten_doorbell_active") is not None
    # jedes Gerät gehört zu seinem Untereintrag
    registry = er.async_get(hass)
    by_subentry = {
        e.config_subentry_id for e in er.async_entries_for_config_entry(registry, hub.entry_id)
    }
    assert by_subentry == set(hub.subentries)


async def test_ringing_one_doorbell_does_not_ring_the_other(hass: HomeAssistant) -> None:
    for entity in ("binary_sensor.front", "binary_sensor.garden"):
        hass.states.async_set(entity, "off")
    hub = _hub_with_two_bells()
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()
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
    await hass.async_block_till_done()
    assert sorted(s.title for s in entry.hub.subentries.values()) == ["Garten", "Haustür"]
    assert len(hass.data[DOMAIN]) == 2                       # beide Controller laufen nach dem Neuladen
    assert hass.states.get("switch.garten_doorbell_active") is not None


async def test_reconfigure_opens_the_menu_of_that_instance(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.front", "off")
    hass.states.async_set("binary_sensor.garden", "off")
    hub = _hub_with_two_bells()
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()
    garden_id = next(s.subentry_id for s in hub.subentries.values() if s.title == "Garten")
    result = await hass.config_entries.subentries.async_init(
        (hub.entry_id, "doorbell"), context={"source": "reconfigure", "subentry_id": garden_id})
    assert is_menu(result) and result["step_id"] == "bell_menu"
    flow = hass.config_entries.subentries
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "bell_general"})
    await flow.async_configure(
        result["flow_id"], {"general": {"trigger_entity": "binary_sensor.front", "debounce_seconds": 99}})
    assert hub.subentries[garden_id].data["debounce_seconds"] == 99
    other = next(s for s in hub.subentries.values() if s.title == "Haustür")
    assert other.data["debounce_seconds"] == 0               # die andere Instanz bleibt unverändert


async def test_removing_a_subentry_cleans_up_issues(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.front", "off")
    hass.states.async_set("binary_sensor.garden", "off")
    hub = _hub_with_two_bells()
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()
    garden = next(s for s in hub.subentries.values() if s.title == "Garten")
    ir.async_create_issue(
        hass, DOMAIN, f"{garden.subentry_id}_entity_x", is_fixable=False,
        severity=ir.IssueSeverity.WARNING, translation_key="entity_missing",
        translation_placeholders={"entry": "Garten", "function": "x", "entity": "x"})
    hass.config_entries.async_remove_subentry(hub, garden.subentry_id)
    await hass.async_block_till_done()
    assert garden.subentry_id not in hass.data[DOMAIN] and len(hass.data[DOMAIN]) == 1
    assert not [i for (d, i) in ir.async_get(hass).issues if d == DOMAIN and garden.subentry_id in i]


async def test_legacy_entry_is_not_loaded_and_reported(hass: HomeAssistant) -> None:
    legacy = MockConfigEntry(domain=DOMAIN, title="Alte Klingel", data={**BELL})
    legacy.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(legacy.entry_id)
    assert legacy.state is ConfigEntryState.SETUP_ERROR
    assert (DOMAIN, f"legacy_{legacy.entry_id}") in ir.async_get(hass).issues


async def test_removing_the_hub_removes_stores_and_issues(hass: HomeAssistant, hass_storage) -> None:
    hass.states.async_set("binary_sensor.front", "off")
    hass.states.async_set("binary_sensor.garden", "off")
    hub = _hub_with_two_bells()
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()
    ids = list(hub.subentries)
    for sid in ids:
        hass_storage[f"{DOMAIN}.{sid}"] = {"version": 1, "key": f"{DOMAIN}.{sid}", "data": {}}
    await hass.config_entries.async_remove(hub.entry_id)
    await hass.async_block_till_done()
    assert not any(f"{DOMAIN}.{sid}" in hass_storage for sid in ids)


async def test_second_hub_of_the_same_type_is_refused(hass: HomeAssistant) -> None:
    hub = _hub_with_two_bells()
    hub.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "hub_doorbell"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    # andere Funktion: möglich
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "hub_updater"})
    assert result["step_id"] == "new_updater"


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
    hub = MockConfigEntry(
        domain=DOMAIN, title="Wecker", unique_id="hub:alarm_clock",
        data={"function_type": "alarm_clock", "hub": True},
        subentries_data=[
            ConfigSubentryData(subentry_type="alarm_clock", title="A", unique_id=None,
                               data={"name": "A", **base}),
            ConfigSubentryData(subentry_type="alarm_clock", title="B", unique_id=None,
                               data={"name": "B", **base}),
        ])
    hub.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()
    first_id, second_id = list(hub.subentries)
    first, second = hass.data[DOMAIN][first_id], hass.data[DOMAIN][second_id]
    await first.async_ring(alarm)
    assert first.busy
    hass.config_entries.async_update_subentry(
        hub, hub.subentries[second_id], data={**hub.subentries[second_id].data, "message": "neu"})
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][first_id] is first and hass.data[DOMAIN][second_id] is second  # nicht neu geladen
    await first.async_stop_alarm()
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][second_id] is not second                                       # jetzt nachgeholt


async def test_function_menu_lists_all_functions_and_defaults_to_function_names(
    hass: HomeAssistant,
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.MENU
    assert sorted(result["menu_options"]) == sorted([
        "hub_mailbox", "hub_door_guard", "hub_doorbell", "hub_pool_pump", "hub_knx_sonos",
        "hub_updater", "hub_task_planner", "hub_alarm_clock"])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "hub_updater"})
    assert result["step_id"] == "new_updater"
    name = next(k for k in result["data_schema"].schema if str(k) == "name")
    assert name.default() == "Home Assistant Updater"             # Vorgabe = Funktionsname
