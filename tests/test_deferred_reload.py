"""Einstellungen speichern lädt den Eintrag neu, aber nicht mitten in einem Lauf."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.ha_housekeeper.const import DOMAIN

PLAYER = "media_player.bedroom"
PUMP = "switch.pool_pump"
ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ALARM = {"id": "a1", "name": "Wecker", "enabled": True, "time": "07:00:00", "weekdays": ALL,
         "players": [PLAYER], "media": {"media_content_id": "x", "media_content_type": "audio/mpeg"},
         "volume": 30, "snooze_minutes": 9, "auto_stop_minutes": 0}


async def _entry(hass: HomeAssistant, data: dict, title="Test", options=None):
    entry = MockConfigEntry(domain=DOMAIN, title=title, data=data, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


async def _save(hass: HomeAssistant, entry, **options) -> None:
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()


def _alarm_mocks(hass):
    hass.states.async_set(PLAYER, "idle", {"volume_level": 0.5})
    for service in ("volume_set", "play_media", "media_stop"):
        async_mock_service(hass, "media_player", service)


ALARM_DATA = {"function_type": "alarm_clock", "name": "Wecker", "mobile_enabled": False,
              "persistent_enabled": False, "alarms": [ALARM]}


async def test_idle_entry_reloads_immediately(hass: HomeAssistant) -> None:
    hass.states.async_set("binary_sensor.v", "off")
    entry, ctrl = await _entry(hass, {
        "function_type": "mailbox", "name": "Briefkasten", "vibration_sensor": "binary_sensor.v",
        "mobile_enabled": False, "persistent_enabled": True, "message": "x",
        "debounce_seconds": 0, "auto_reset_hours": 0})
    await _save(hass, entry, message="neu")
    assert hass.data[DOMAIN][entry.entry_id] is not ctrl                     # sofort neu geladen
    assert hass.data[DOMAIN][entry.entry_id]._opt("message") == "neu"        # noqa: SLF001


async def test_ringing_alarm_is_not_interrupted(hass: HomeAssistant) -> None:
    _alarm_mocks(hass)
    entry, ctrl = await _entry(hass, ALARM_DATA)
    await ctrl.async_ring(ALARM)
    assert ctrl.busy
    await _save(hass, entry, critical=False)
    assert hass.data[DOMAIN][entry.entry_id] is ctrl and ctrl.ringing and ctrl.reload_requested
    # Stoppen beendet den Vorgang: jetzt wird neu geladen und die Einstellung gilt
    await ctrl.async_stop_alarm()
    await hass.async_block_till_done()
    new = hass.data[DOMAIN][entry.entry_id]
    assert new is not ctrl and new._get("critical") is False and not new.reload_requested   # noqa: SLF001


async def test_snoozed_alarm_keeps_its_timer(hass: HomeAssistant) -> None:
    _alarm_mocks(hass)
    entry, ctrl = await _entry(hass, ALARM_DATA)
    await ctrl.async_ring(ALARM)
    await ctrl.async_snooze()
    assert ctrl.phase == "snoozed" and ctrl.busy
    await _save(hass, entry, message="x")
    assert hass.data[DOMAIN][entry.entry_id] is ctrl and ctrl.snooze_until is not None
    await ctrl.async_stop_alarm()
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id] is not ctrl


async def test_several_saves_cause_one_reload(hass: HomeAssistant) -> None:
    _alarm_mocks(hass)
    entry, ctrl = await _entry(hass, ALARM_DATA)
    await ctrl.async_ring(ALARM)
    original = hass.config_entries.async_reload
    with patch.object(hass.config_entries, "async_reload", side_effect=original) as reload:
        for text in ("a", "b", "c"):
            await _save(hass, entry, message=text)
        assert reload.call_count == 0
        await ctrl.async_stop_alarm()
        await hass.async_block_till_done()
        assert reload.call_count == 1
    assert hass.data[DOMAIN][entry.entry_id]._get("message") == "c"          # noqa: SLF001


async def test_removed_entry_while_pending_is_harmless(hass: HomeAssistant) -> None:
    _alarm_mocks(hass)
    entry, ctrl = await _entry(hass, ALARM_DATA)
    await ctrl.async_ring(ALARM)
    await _save(hass, entry, message="x")
    assert ctrl.reload_requested
    ctrl.reload_requested = True
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    ctrl.async_idle()                                                          # kein Fehler, kein Neuladen
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_updater_run_blocks_reload(hass: HomeAssistant) -> None:
    entry, ctrl = await _entry(hass, {
        "function_type": "updater", "name": "Updater", "schedules": [], "timeout_minutes": 30})
    assert not ctrl.busy
    ctrl._running = True                                                       # noqa: SLF001
    await _save(hass, entry, timeout_minutes=10)
    assert hass.data[DOMAIN][entry.entry_id] is ctrl
    ctrl._running = False                                                      # noqa: SLF001
    ctrl.async_idle()
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id] is not ctrl


async def test_updater_pending_report_blocks_reload(hass: HomeAssistant) -> None:
    entry, ctrl = await _entry(hass, {
        "function_type": "updater", "name": "Updater", "schedules": [], "timeout_minutes": 30})
    ctrl.pending = {"schedule": "x", "results": [], "current": {"entity": "update.core"}, "deferred": []}
    assert ctrl.busy
    await _save(hass, entry, timeout_minutes=10)
    assert hass.data[DOMAIN][entry.entry_id] is ctrl


async def test_running_task_blocks_reload(hass: HomeAssistant) -> None:
    entry, ctrl = await _entry(hass, {
        "function_type": "task_planner", "name": "Planer", "tasks": [], "mobile_enabled": False,
        "persistent_enabled": True})
    ctrl._running.add("t1")                                                    # noqa: SLF001
    assert ctrl.busy
    await _save(hass, entry, message="x")
    assert hass.data[DOMAIN][entry.entry_id] is ctrl
    ctrl._running.discard("t1")                                                # noqa: SLF001
    ctrl.async_idle()
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id] is not ctrl


async def test_manual_pool_run_blocks_reload_until_it_ends(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    async_mock_service(hass, "homeassistant", "turn_on")
    async_mock_service(hass, "homeassistant", "turn_off")
    hass.states.async_set(PUMP, "off")
    entry, ctrl = await _entry(
        hass, {"function_type": "pool_pump", "pump_entity": PUMP}, title="Pool",
        options={"pump_entity": PUMP, "windows": []})
    await hass.services.async_call(DOMAIN, "run_pump", {"duration": 10}, blocking=True)
    assert ctrl.busy
    await _save(hass, entry, windows=[{"start": "08:00:00", "end": "09:00:00", "days": ALL}])
    assert hass.data[DOMAIN][entry.entry_id] is ctrl                           # manueller Lauf bleibt erhalten
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id] is not ctrl
