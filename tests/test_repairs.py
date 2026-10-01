"""Reparaturhinweise für Entitäten und Geräte, die es nicht mehr gibt."""

import json
from datetime import timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.ha_housekeeper import issues
from custom_components.ha_housekeeper.const import DOMAIN

COMPONENT = Path(__file__).parent.parent / "custom_components" / "ha_housekeeper"
MAILBOX = {"function_type": "mailbox", "name": "Briefkasten", "vibration_sensor": "binary_sensor.v",
           "mobile_enabled": False, "persistent_enabled": True, "message": "x",
           "debounce_seconds": 0, "auto_reset_hours": 0}


def entry_of(data, title="Test", options=None):
    return MockConfigEntry(domain=DOMAIN, title=title, data=data, options=options or {})


async def setup(hass: HomeAssistant, data, title="Test", options=None):
    entry = entry_of(data, title, options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def open_issues(hass: HomeAssistant) -> dict[str, ir.IssueEntry]:
    return {i: v for (d, i), v in ir.async_get(hass).issues.items() if d == DOMAIN}


# --- Referenzen einsammeln ------------------------------------------------------------------------


def test_collect_references_per_function() -> None:
    def refs(data):
        return issues.collect_references(entry_of(data))

    assert refs({**MAILBOX, "sensitivity_entity": "number.s", "tts_entity": "tts.home",
                 "tts_player": "media_player.k", "mobile_targets": ["dev1", "dev2"]}) == (
        ["tts.home", "media_player.k", "binary_sensor.v", "number.s"], ["dev1", "dev2"])
    assert refs({"function_type": "door_guard", "lock": "lock.d", "contact": "binary_sensor.c",
                 "rules": [{"entity_id": "person.a"}, {"time": "22:00"}]})[0] == [
        "lock.d", "binary_sensor.c", "person.a"]
    assert refs({"function_type": "doorbell", "trigger_entity": "binary_sensor.b",
                 "profiles": [{"players": ["media_player.a"], "tts_entity": "tts.x"}]})[0] == [
        "binary_sensor.b", "media_player.a", "tts.x"]
    assert refs({"function_type": "pool_pump", "pump_entity": "switch.p", "power_entity": "sensor.w"})[0] == [
        "switch.p", "sensor.w"]
    assert refs({"function_type": "knx_sonos", "player": "media_player.l"})[0] == ["media_player.l"]
    assert refs({"function_type": "knx_sonos", "speakers": [
        {"player": "media_player.a"}, {"player": "media_player.b"}]})[0] == ["media_player.a", "media_player.b"]
    assert refs({"function_type": "updater", "schedules": [
        {"targets": ["update.a", "update.b"], "mobile_targets": ["devX"]}, {"targets": ["update.a"]}]}) == (
        ["update.a", "update.b"], ["devX"])
    assert refs({"function_type": "task_planner", "tasks": [
        {"triggers": [{"type": "state", "entity_id": "sensor.t"}, {"type": "weekly"}]}]})[0] == ["sensor.t"]
    assert refs({"function_type": "alarm_clock", "alarms": [{"players": ["media_player.a"]}],
                 "workday_sensors": ["binary_sensor.w"]})[0] == ["media_player.a", "binary_sensor.w"]
    # Optionen haben Vorrang; ein leeres Feld (None) überdeckt den Wert aus den Daten
    entry = entry_of({**MAILBOX, "sensitivity_entity": "number.s"}, options={"sensitivity_entity": None})
    assert "number.s" not in issues.collect_references(entry)[0]


# --- Hinweise anlegen und wieder entfernen -----------------------------------------------------------


async def test_missing_entity_creates_issue_and_resolves(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    entry = await setup(hass, MAILBOX, title="Briefkasten")
    assert await issues.async_check_entry(hass, entry) != []
    (issue,) = open_issues(hass).values()
    assert issue.translation_key == "entity_missing" and issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {
        "entry": "Briefkasten", "function": "Mailbox notification", "entity": "binary_sensor.v"}
    # Entität erscheint: der Hinweis verschwindet von selbst
    hass.states.async_set("binary_sensor.v", "off")
    assert await issues.async_check_entry(hass, entry) == []
    assert open_issues(hass) == {}


async def test_unavailable_and_disabled_are_not_missing(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.v", "unavailable")
    entry = await setup(hass, {**MAILBOX, "sensitivity_entity": "number.disabled"})
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "number", "test", "s1", suggested_object_id="disabled",
        disabled_by=er.RegistryEntryDisabler.USER)
    assert await issues.async_check_entry(hass, entry) == []
    assert open_issues(hass) == {}


async def test_each_missing_reference_has_its_own_issue(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.ok", "1")
    entry = await setup(hass, {
        "function_type": "pool_pump", "pump_entity": "switch.p", "power_entity": "sensor.w"})
    hass.states.async_set("switch.p", "off")
    assert len(await issues.async_check_entry(hass, entry)) == 1               # nur sensor.w fehlt
    hass.states.async_remove("switch.p")
    assert len(await issues.async_check_entry(hass, entry)) == 2
    hass.states.async_set("switch.p", "off")
    assert len(await issues.async_check_entry(hass, entry)) == 1
    assert [v.translation_placeholders["entity"] for v in open_issues(hass).values()] == ["sensor.w"]


async def _wait_for_event_check(hass: HomeAssistant, freezer) -> None:
    freezer.tick(timedelta(seconds=issues.EVENT_DELAY_SECONDS + 1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_device_issue_for_deleted_companion_device(hass: HomeAssistant, freezer) -> None:
    hass.config.language = "en"
    app = MockConfigEntry(domain="mobile_app", data={"device_name": "iPhone Ludger", "webhook_id": "a"})
    app.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=app.entry_id, identifiers={("mobile_app", "a")}, name="iPhone Ludger")
    hass.states.async_set("binary_sensor.v", "off")
    entry = await setup(hass, {**MAILBOX, "mobile_enabled": True, "mobile_targets": [device.id]})
    assert await issues.async_check_entry(hass, entry) == []
    dr.async_get(hass).async_remove_device(device.id)
    await _wait_for_event_check(hass, freezer)                               # Registry-Ereignis löst die Prüfung aus
    (issue,) = open_issues(hass).values()
    assert issue.translation_key == "device_missing" and issue.translation_placeholders["entity"] == device.id


async def test_legacy_service_name_missing_and_present(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.v", "off")
    entry = await setup(hass, {**MAILBOX, "mobile_enabled": True, "mobile_targets": ["mobile_app_altes"]})
    assert len(await issues.async_check_entry(hass, entry)) == 1
    async_mock_service(hass, "notify", "mobile_app_altes")
    assert await issues.async_check_entry(hass, entry) == []


# --- Auslöser der Prüfung ---------------------------------------------------------------------------------


async def test_entity_removed_or_renamed_triggers_check(hass: HomeAssistant, freezer) -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create("binary_sensor", "test", "v1", suggested_object_id="v")
    hass.states.async_set("binary_sensor.v", "off")
    await setup(hass, MAILBOX)
    assert open_issues(hass) == {}
    registry.async_update_entity("binary_sensor.v", new_entity_id="binary_sensor.v_neu")   # umbenannt
    hass.states.async_remove("binary_sensor.v")
    hass.states.async_set("binary_sensor.v_neu", "off")
    await hass.async_block_till_done()
    assert open_issues(hass) == {}                                           # erst nach kurzer Wartezeit
    await _wait_for_event_check(hass, freezer)
    assert len(open_issues(hass)) == 1                                       # die gespeicherte ID stimmt nicht mehr
    hass.states.async_set("binary_sensor.v", "off")                          # wieder da
    registry.async_get_or_create("binary_sensor", "test", "v2", suggested_object_id="v2")
    registry.async_remove("binary_sensor.v2")                                # irgendein Ereignis: neue Prüfung
    await _wait_for_event_check(hass, freezer)
    assert open_issues(hass) == {}


async def test_first_check_after_grace_period_and_hourly(hass: HomeAssistant, freezer) -> None:
    await setup(hass, MAILBOX)
    assert open_issues(hass) == {}                                           # Schonfrist nach dem Start
    freezer.tick(timedelta(seconds=issues.GRACE_SECONDS + 1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(open_issues(hass)) == 1
    hass.states.async_set("binary_sensor.v", "off")
    freezer.tick(timedelta(hours=1, minutes=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert open_issues(hass) == {}


async def test_issues_removed_with_the_entry(hass: HomeAssistant) -> None:
    entry = await setup(hass, MAILBOX)
    await issues.async_check_entry(hass, entry)
    assert len(open_issues(hass)) == 1
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(open_issues(hass)) == 1                                       # Entladen (Neuladen) behält den Hinweis
    assert await issues.async_check_entry(hass, entry) == []                 # entladener Eintrag wird nicht geprüft
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert open_issues(hass) == {}


async def test_issues_only_belong_to_their_entry(hass: HomeAssistant) -> None:
    first = await setup(hass, MAILBOX, title="Eins")
    second = await setup(hass, {**MAILBOX, "vibration_sensor": "binary_sensor.w"}, title="Zwei")
    await issues.async_check_entry(hass, first)
    await issues.async_check_entry(hass, second)
    assert len(open_issues(hass)) == 2
    hass.states.async_set("binary_sensor.v", "off")
    await issues.async_check_entry(hass, first)
    assert [v.translation_placeholders["entry"] for v in open_issues(hass).values()] == ["Zwei"]


# --- Übersetzungen -----------------------------------------------------------------------------------------------


def test_translations_for_issues() -> None:
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        data = json.loads((COMPONENT / name).read_text(encoding="utf-8"))
        for key in (issues.ENTITY_MISSING, issues.DEVICE_MISSING):
            text = data["issues"][key]
            for placeholder in ("{entry}", "{function}", "{entity}"):
                assert placeholder in text["description"], (name, key, placeholder)
            assert "{entity}" in text["title"], (name, key)
