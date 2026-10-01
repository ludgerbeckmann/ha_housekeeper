"""Einzelschalter „aktiv“ bei Zeitplänen, Profilen und Regeln; Schalter beim Briefkasten."""

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.ha_housekeeper import updater as upd
from custom_components.ha_housekeeper.const import DOMAIN
from custom_components.ha_housekeeper.doorbell import assign_players, profile_summary
from custom_components.ha_housekeeper.door_guard import rule_summary

from .helpers import is_menu, make_entry, reconfigure, update_entry

ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# --- Updater-Zeitpläne --------------------------------------------------------------------------


def schedule(i, enabled=None, time="03:00:00", targets=("update.a",), **over):
    item = {"id": i, "name": f"Plan {i}", "time": time, "weekdays": ALL, "mode": "notify",
            "targets": list(targets), "backup": False, **over}
    if enabled is not None:
        item["enabled"] = enabled
    return item


def test_next_run_ignores_disabled_schedules() -> None:
    now = datetime(2024, 1, 3, 12, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    early = schedule("e", enabled=False, time="13:00:00")
    late = schedule("l", time="18:00:00")
    assert upd.next_run([early, late], now) == now.replace(hour=18)
    assert upd.next_run([early], now) is None
    assert upd.next_run([schedule("x")], now) is not None                    # ohne Angabe: aktiv


async def test_disabled_schedule_summary_and_effects(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    assert upd.schedule_summary(hass, schedule("a", targets=("update.a",))).endswith("1 updates, notify")
    assert upd.schedule_summary(hass, schedule("a", enabled=False)).endswith("notify, off")
    hass.config.language = "de"
    assert upd.schedule_summary(hass, schedule("a", enabled=False)).endswith("melden, aus")

    hass.config.language = "en"              # Entity-IDs entstehen aus den englischen Namen
    hass.states.async_set("update.a", "on", {"installed_version": "1", "latest_version": "2", "title": "A"})
    hass.states.async_set("update.b", "on", {"installed_version": "1", "latest_version": "2", "title": "B"})
    push = async_mock_service(hass, "notify", "mobile_app_phone")
    persist = async_mock_service(hass, "persistent_notification", "create")
    entry = make_entry(domain=DOMAIN, title="Updater", data={
        "function_type": "updater", "name": "Updater", "timeout_minutes": 30,
        "schedules": [
            schedule("on", targets=("update.a",), mobile_enabled=True, mobile_targets=["mobile_app_phone"],
                     tts_enabled=False, persistent_enabled=False),
            schedule("off", enabled=False, targets=("update.b",), mobile_enabled=False,
                     tts_enabled=False, persistent_enabled=True),
        ]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    ctrl = hass.data[DOMAIN][entry.entry_id]
    assert [s["id"] for s in ctrl.schedules] == ["on"] and len(ctrl.all_schedules) == 2
    assert ctrl.available_updates() == ["A"]                                  # B gehört nur dem ausgeschalteten Plan
    await hass.services.async_call("button", "press", {"entity_id": "button.updater_check_now"}, blocking=True)
    assert len(push) == 1 and persist == []                                   # Wege des ausgeschalteten Plans zählen nicht


# --- Türklingel-Profile ------------------------------------------------------------------------------


def test_doorbell_disabled_profile_is_skipped() -> None:
    day = {"id": "a", "name": "Tag", "from": "07:00:00", "to": "22:00:00", "weekdays": ALL,
           "players": ["media_player.a"], "mode": "tts"}
    off = {**day, "id": "b", "name": "Aus", "enabled": False, "players": ["media_player.b"]}
    now = datetime(2024, 1, 3, 12, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    assert [(p["id"], pl) for p, pl in assign_players([off, day], now)] == [("a", ["media_player.a"])]
    # ein ausgeschaltetes Profil beansprucht seine Player nicht
    both = {**day, "id": "c", "players": ["media_player.b"]}
    assert [p["id"] for p, _ in assign_players([off, both], now)] == ["c"]


async def test_doorbell_summary_marks_disabled(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    profile = {"id": "a", "name": "Tag", "from": "07:00:00", "to": "22:00:00", "weekdays": ALL,
               "players": ["x"], "mode": "tts"}
    assert profile_summary(hass, profile).endswith("announcement")
    assert profile_summary(hass, {**profile, "enabled": False}).endswith("announcement, off")


# --- Türwächter-Regeln -----------------------------------------------------------------------------------


async def test_door_guard_disabled_rule_is_ignored(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "lock", "unlock")
    hass.states.async_set("lock.front_door", "locked")
    hass.states.async_set("binary_sensor.contact", "off")
    hass.states.async_set("person.ludger", "not_home")
    hass.states.async_set("person.britta", "not_home")
    rules = [
        {"id": "r1", "action": "unlock", "trigger": "state", "entity_id": "person.ludger",
         "to_state": "home", "for_minutes": 0, "enabled": False},
        {"id": "r2", "action": "unlock", "trigger": "state", "entity_id": "person.britta",
         "to_state": "home", "for_minutes": 0},
    ]
    entry = make_entry(domain=DOMAIN, title="Door", data={
        "function_type": "door_guard", "name": "Door", "lock": "lock.front_door",
        "contact": "binary_sensor.contact", "block_action": "notify", "retry_minutes": 10,
        "open_alert_minutes": 0, "open_alert_repeat_minutes": 0, "verify_seconds": 0,
        "manual_override": "ignore", "manual_pause_minutes": 60, "mobile_enabled": False,
        "tts_enabled": False, "persistent_enabled": True, "rules": rules})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    hass.states.async_set("person.ludger", "home")                    # ausgeschaltete Regel
    await hass.async_block_till_done()
    assert calls == []
    hass.states.async_set("person.britta", "home")                    # aktive Regel
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_door_guard_rule_summary_and_flow(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    rule = {"id": "r1", "action": "lock", "trigger": "time", "time": "22:00:00", "weekdays": ALL}
    assert rule_summary(hass, rule) == "Lock: 22:00"
    assert rule_summary(hass, {**rule, "enabled": False}) == "Lock: 22:00 (off)"

    hass.states.async_set("lock.front_door", "locked")
    entry = make_entry(domain=DOMAIN, title="Door", data={
        "function_type": "door_guard", "name": "Door", "lock": "lock.front_door", "rules": [],
        "persistent_enabled": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_rule"})
    assert "enabled" in {str(k) for k in result["data_schema"].schema}
    result = await flow.async_configure(
        result["flow_id"], {"action": "lock", "trigger": "time", "enabled": False})
    result = await flow.async_configure(
        result["flow_id"], {"time": "22:00:00", "weekdays": ["mon"]})
    assert is_menu(result)
    (saved,) = entry.options["rules"]
    assert saved["enabled"] is False
    # Standard: aktiv
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_rule"})
    result = await flow.async_configure(result["flow_id"], {"action": "lock", "trigger": "time"})
    await flow.async_configure(result["flow_id"], {"time": "23:00:00", "weekdays": ["tue"]})
    assert entry.options["rules"][1]["enabled"] is True


async def test_doorbell_profile_flow_stores_enabled(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.bell", "off")
    entry = make_entry(domain=DOMAIN, title="Klingel", data={
        "function_type": "doorbell", "name": "Klingel", "trigger_entity": "binary_sensor.bell",
        "debounce_seconds": 0, "mobile_enabled": False, "message": "x", "clear_after_hours": 0,
        "profiles": []})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_profile"})
    sections = result["data_schema"].schema
    timing = next(v for k, v in sections.items() if str(k) == "timing")
    assert "enabled" in {str(k) for k in timing.schema.schema}
    result = await flow.async_configure(result["flow_id"], {
        "timing": {"name": "Nacht", "enabled": False, "from": "22:00:00", "to": "06:00:00",
                   "weekdays": ALL},
        "sound": {"players": ["media_player.a"], "mode": "ringtone", "volume": 10,
                  "media": {"media_content_id": "x", "media_content_type": "audio/mpeg"}},
        "notifications": {"mobile_enabled": False, "message": "x", "clear_after_hours": 0}})
    assert is_menu(result) and entry.options["profiles"][0]["enabled"] is False


# --- KNX/Sonos-Profile -------------------------------------------------------------------------------------


def speaker(i, player, **over):
    return {"id": i, "name": f"S {i}", "player": player, "max_volume": 100, "volume_step": 5,
            "stop_instead_of_pause": False, **over}


async def test_knx_disabled_profile_is_inert(hass: HomeAssistant) -> None:
    play = async_mock_service(hass, "media_player", "media_play")
    send = async_mock_service(hass, "knx", "send")
    async_mock_service(hass, "knx", "event_register")
    for player in ("media_player.a", "media_player.b"):
        hass.states.async_set(player, "paused", {"volume_level": 0.3})
    entry = make_entry(domain=DOMAIN, title="Sonos", data={
        "function_type": "knx_sonos",
        "speakers": [speaker("a", "media_player.a"), speaker("b", "media_player.b", enabled=False)],
        "commands": [
            {"id": "1", "name": "A", "address": "1/0/1", "dpt": "switch", "action": "play", "profile": "a"},
            {"id": "2", "name": "B", "address": "2/0/1", "dpt": "switch", "action": "play", "profile": "b"}],
        "status": [{"id": "s", "name": "S", "source": "volume", "address": "5/0/1", "profile": "b"}]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    ctrl = hass.data[DOMAIN][entry.entry_id]
    assert ctrl.players == ["media_player.a"]
    for destination in ("1/0/1", "2/0/1"):
        hass.bus.async_fire("knx_event", {"data": 1, "destination": destination, "direction": "Incoming",
                                          "telegramtype": "GroupValueWrite", "value": None, "source": "1.1.1"})
        await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in play] == ["media_player.a"]         # nur das aktive Profil
    assert send == []                                                        # Rückmeldung des ausgeschalteten Profils ruht
    # Wieder einschalten (Neuladen mit geänderten Optionen)
    update_entry(hass, entry, {
        "speakers": [speaker("a", "media_player.a"), speaker("b", "media_player.b")]})
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id].players == ["media_player.a", "media_player.b"]
    assert [(c.data["address"], c.data["payload"]) for c in send] == [("5/0/1", 30)]


async def test_knx_speaker_flow_stores_enabled_and_marks_picker(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    async_mock_service(hass, "knx", "event_register")
    hass.states.async_set("media_player.a", "paused", {})
    entry = make_entry(domain=DOMAIN, title="Sonos", data={
        "function_type": "knx_sonos", "player": "media_player.a", "max_volume": 100,
        "volume_step": 5, "stop_instead_of_pause": False, "commands": [], "status": []})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "edit_speaker"})
    result = await flow.async_configure(result["flow_id"], {"item": "default"})
    assert "enabled" in {str(k) for k in result["data_schema"].schema}
    result = await flow.async_configure(result["flow_id"], {
        "name": "Standard", "enabled": False, "player": "media_player.a", "max_volume": 100,
        "volume_step": 5, "stop_instead_of_pause": False})
    assert entry.options["speakers"][0]["enabled"] is False
    await hass.async_block_till_done()
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "edit_speaker"})
    labels = [o["label"] for o in next(iter(result["data_schema"].schema.values())).config["options"]]
    assert labels == ["Standard (media_player.a) (off)"]


# --- Briefkasten ------------------------------------------------------------------------------------------------


MAILBOX = {"function_type": "mailbox", "name": "Briefkasten", "vibration_sensor": "binary_sensor.v",
           "mobile_enabled": False, "persistent_enabled": True, "message": "Post!",
           "debounce_seconds": 0, "auto_reset_hours": 0}


async def _mailbox(hass):
    hass.states.async_set("binary_sensor.v", "off")
    entry = make_entry(domain=DOMAIN, title="Briefkasten", data=MAILBOX)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry


async def test_mailbox_switch_pauses_notification(hass: HomeAssistant) -> None:
    persist = async_mock_service(hass, "persistent_notification", "create")
    entry = await _mailbox(hass)
    switch = "switch.briefkasten_mailbox_notification_active"
    assert hass.states.get(switch).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    hass.states.async_set("binary_sensor.v", "on")
    await hass.async_block_till_done()
    assert persist == [] and hass.states.get("binary_sensor.briefkasten_mail_present").state == "off"
    # Pause bleibt nach dem Neuladen erhalten
    assert await hass.config_entries.async_reload(entry.hub_id)
    assert hass.states.get(switch).state == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    hass.states.async_set("binary_sensor.v", "off")
    hass.states.async_set("binary_sensor.v", "on")
    await hass.async_block_till_done()
    assert len(persist) == 1 and hass.states.get("binary_sensor.briefkasten_mail_present").state == "on"


async def test_mailbox_can_still_be_emptied_while_paused(hass: HomeAssistant) -> None:
    async_mock_service(hass, "persistent_notification", "create")
    async_mock_service(hass, "persistent_notification", "dismiss")
    await _mailbox(hass)
    hass.states.async_set("binary_sensor.v", "on")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.briefkasten_mail_present").state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.briefkasten_mailbox_notification_active"}, blocking=True)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.briefkasten_mailbox_emptied"}, blocking=True)
    assert hass.states.get("binary_sensor.briefkasten_mail_present").state == "off"
