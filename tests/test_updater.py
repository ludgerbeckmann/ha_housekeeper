"""Tests für die Funktion Updater."""

import asyncio
from datetime import datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import sectioned
from custom_components.ha_housekeeper import updater as upd
from custom_components.ha_housekeeper.const import DOMAIN

ADDON = "update.esphome_update"
DEVICE = "update.sensor_firmware"
CORE = "update.home_assistant_core_update"
OS = "update.home_assistant_operating_system_update"
SUPERVISOR = "update.home_assistant_supervisor_update"
ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

BASE = {
    "function_type": "updater", "name": "Updater", "timeout_minutes": 30,
    "mobile_enabled": True, "mobile_targets": ["mobile_app_phone"],
    "tts_enabled": False, "persistent_enabled": False, "schedules": [],
}


def schedule(i="s1", targets=(ADDON,), mode="install", backup=False, days=ALL_DAYS, time="03:00:00"):
    return {"id": i, "name": f"Plan {i}", "time": time, "weekdays": list(days),
            "mode": mode, "targets": list(targets), "backup": backup}


def put(hass, entity_id, installed="1.0", latest="2.0", state="on", features=0):
    hass.states.async_set(entity_id, state, {
        "installed_version": installed, "latest_version": latest,
        "title": entity_id.split(".")[1], "supported_features": features})


class Installer:
    """Simulierter Dienst update.install."""

    def __init__(self, hass, fail=(), apply=True, delay=None):
        self.hass, self.fail, self.apply, self.delay = hass, set(fail), apply, delay
        self.calls: list[dict] = []
        hass.services.async_register("update", "install", self._handle)

    async def _handle(self, call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        self.calls.append(dict(call.data))
        if self.delay is not None:
            await self.delay.wait()
        if entity_id in self.fail:
            raise RuntimeError("Installer kaputt")
        if self.apply:
            state = self.hass.states.get(entity_id)
            self.hass.states.async_set(entity_id, "off", {
                **state.attributes, "installed_version": state.attributes["latest_version"]})


async def _setup(hass, schedules, **over):
    push = async_mock_service(hass, "notify", "mobile_app_phone")
    entry = MockConfigEntry(domain=DOMAIN, title="Updater",
                            data={**BASE, "schedules": schedules, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id], push


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr(upd, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(upd, "SETTLE_SECONDS", 0.05)


# --- reine Funktionen ------------------------------------------------------------------


def test_order_targets_puts_system_updates_last():
    assert upd.order_targets([OS, CORE, ADDON, SUPERVISOR, DEVICE]) == [
        ADDON, DEVICE, SUPERVISOR, CORE, OS]


def test_next_run():
    now = datetime(2024, 1, 3, 12, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)   # Mittwoch
    sched = [schedule("a", days=["wed"], time="15:00:00"), schedule("b", days=["mon"], time="03:00:00")]
    assert upd.next_run(sched, now) == now.replace(hour=15)
    assert upd.next_run([schedule("b", days=["mon"], time="03:00:00")], now) == datetime(
        2024, 1, 8, 3, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    assert upd.next_run([], now) is None
    # heute, aber die Uhrzeit ist schon vorbei: nächste Woche
    assert upd.next_run([schedule(days=["wed"], time="11:00:00")], now) == datetime(
        2024, 1, 10, 11, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)


# --- Benachrichtigen ---------------------------------------------------------------------


async def test_notify_mode_reports_only(hass: HomeAssistant) -> None:
    put(hass, ADDON)
    put(hass, DEVICE, state="off", installed="2.0", latest="2.0")
    inst = Installer(hass)
    _, ctrl, push = await _setup(hass, [schedule(targets=[ADDON, DEVICE], mode="notify")])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert inst.calls == []
    assert len(push) == 1
    assert "esphome_update" in push[0].data["message"] and "1.0 → 2.0" in push[0].data["message"]
    assert "sensor_firmware" not in push[0].data["message"]
    assert ctrl.last_run["mode"] == "notify"


async def test_no_updates_is_silent_but_check_now_answers(hass: HomeAssistant) -> None:
    put(hass, ADDON, state="off", installed="2.0", latest="2.0")
    Installer(hass)
    _, ctrl, push = await _setup(hass, [schedule(mode="notify")])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert push == [] and ctrl.last_run["installed"] == 0
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.updater_check_now"}, blocking=True)
    assert len(push) == 1 and "No updates" in push[0].data["message"]


async def test_check_now_never_installs(hass: HomeAssistant) -> None:
    put(hass, ADDON)
    inst = Installer(hass)
    _, ctrl, push = await _setup(hass, [schedule(mode="install")])
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.updater_check_now"}, blocking=True)
    assert inst.calls == [] and len(push) == 1


# --- Installieren ---------------------------------------------------------------------------


async def test_install_order_and_report(hass: HomeAssistant) -> None:
    for entity in (CORE, ADDON, DEVICE, SUPERVISOR):
        put(hass, entity)
    inst = Installer(hass)
    _, ctrl, push = await _setup(
        hass, [schedule(targets=[CORE, ADDON, DEVICE, SUPERVISOR])])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert [c["entity_id"] for c in inst.calls] == [ADDON, DEVICE, SUPERVISOR, CORE]
    assert len(push) == 2                       # Start und Ergebnis
    assert "started" in push[0].data["message"]
    assert push[1].data["message"].count("✔") == 4
    assert ctrl.last_run["installed"] == 4 and ctrl.last_run["failed"] == 0
    assert ctrl.pending is None
    assert hass.states.get("sensor.updater_available_updates").state == "0"


async def test_failure_skips_system_updates_but_continues_others(hass: HomeAssistant) -> None:
    for entity in (ADDON, DEVICE, CORE):
        put(hass, entity)
    inst = Installer(hass, fail=[ADDON])
    _, ctrl, push = await _setup(hass, [schedule(targets=[ADDON, DEVICE, CORE])])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert [c["entity_id"] for c in inst.calls] == [ADDON, DEVICE]   # Core ausgelassen
    message = push[1].data["message"]
    assert "✖" in message and "Installer kaputt" in message and "⏭" in message
    assert ctrl.last_run["installed"] == 1 and ctrl.last_run["failed"] == 1
    assert ctrl.last_run["skipped"] == 1


async def test_timeout_counts_as_failure(hass: HomeAssistant) -> None:
    put(hass, ADDON)
    gate = asyncio.Event()
    inst = Installer(hass, delay=gate)              # hängt, bis das Tor geöffnet wird
    _, ctrl, push = await _setup(hass, [schedule()], timeout_minutes=0.001)
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert "timed out" in push[1].data["message"]
    assert ctrl.last_run["failed"] == 1
    # die Installation selbst wurde nicht abgebrochen, sie läuft weiter
    assert len(inst.calls) == 1
    gate.set()
    await hass.async_block_till_done()
    assert hass.states.get(ADDON).state == "off"


async def test_version_not_applied_is_failure(hass: HomeAssistant) -> None:
    put(hass, ADDON)
    Installer(hass, apply=False)                    # Dienst "ok", Version bleibt
    _, ctrl, push = await _setup(hass, [schedule()])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert "not applied" in push[1].data["message"]


async def test_backup_only_where_supported(hass: HomeAssistant) -> None:
    put(hass, ADDON, features=1 | 8)
    put(hass, DEVICE, features=1)
    inst = Installer(hass)
    _, ctrl, _ = await _setup(hass, [schedule(targets=[ADDON, DEVICE], backup=True)])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    by_entity = {c["entity_id"]: c for c in inst.calls}
    assert by_entity[ADDON].get("backup") is True and "backup" not in by_entity[DEVICE]


async def test_no_backup_by_default(hass: HomeAssistant) -> None:
    put(hass, ADDON, features=1 | 8)
    inst = Installer(hass)
    _, ctrl, _ = await _setup(hass, [schedule()])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert "backup" not in inst.calls[0]


async def test_only_one_restart_per_run(hass: HomeAssistant) -> None:
    put(hass, CORE)
    put(hass, OS)
    inst = Installer(hass)
    _, ctrl, push = await _setup(hass, [schedule(targets=[OS, CORE])])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert [c["entity_id"] for c in inst.calls] == [CORE]
    assert "deferred" in push[1].data["message"]
    assert ctrl.last_run["skipped"] == 1 and ctrl.pending is None


async def test_no_parallel_runs(hass: HomeAssistant) -> None:
    put(hass, ADDON)
    gate = asyncio.Event()
    inst = Installer(hass, delay=gate)
    _, ctrl, _ = await _setup(hass, [schedule()])
    first = hass.async_create_task(ctrl.async_run_schedule(ctrl.schedules[0]))
    await asyncio.sleep(0.05)
    assert ctrl.running
    await ctrl.async_run_schedule(ctrl.schedules[0])       # wird übersprungen
    gate.set()
    await first
    assert len(inst.calls) == 1 and not ctrl.running


# --- Neustart durch Core-Update ----------------------------------------------------------------


def _pending(status_to="2.0"):
    return {"schedule": "Plan s1",
            "results": [{"entity": ADDON, "name": "esphome_update", "from": "1.0", "to": "2.0",
                         "status": "installed"}],
            "current": {"entity": CORE, "name": "core", "from": "1.0", "to": status_to},
            "deferred": [OS]}


async def _setup_with_pending(hass, hass_storage, installed, monkeypatch):
    monkeypatch.setattr(upd, "FINALIZE_DELAY", 0.01)
    put(hass, CORE, installed=installed, latest="2.0", state="off")
    entry = MockConfigEntry(domain=DOMAIN, title="Updater",
                            data={**BASE, "schedules": [schedule(targets=[CORE])]})
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1, "minor_version": 1, "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"enabled": True, "last_run": None, "pending": _pending()}}
    push = async_mock_service(hass, "notify", "mobile_app_phone")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id], push


async def test_report_after_restart_success(hass: HomeAssistant, hass_storage, monkeypatch) -> None:
    ctrl, push = await _setup_with_pending(hass, hass_storage, "2.0", monkeypatch)
    assert len(push) == 1
    message = push[0].data["message"]
    assert message.count("✔") == 2 and "deferred" in message
    assert ctrl.pending is None and ctrl.last_run["installed"] == 2


async def test_report_after_restart_failure(hass: HomeAssistant, hass_storage, monkeypatch) -> None:
    ctrl, push = await _setup_with_pending(hass, hass_storage, "1.0", monkeypatch)
    assert "✖" in push[0].data["message"] and ctrl.last_run["failed"] == 1


# --- Zeitplan, Schalter, Sensoren ---------------------------------------------------------------


def _at(weekday: int, hour: int = 3) -> datetime:
    """Kommender Wochentag (0 = Montag) zur angegebenen Uhrzeit."""
    now = dt_util.now()
    day = now + timedelta(days=(weekday - now.weekday()) % 7 + 7)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


async def test_time_trigger_respects_weekday_and_switch(hass: HomeAssistant) -> None:
    put(hass, ADDON)
    inst = Installer(hass)
    _, ctrl, _ = await _setup(hass, [schedule(days=["sun"])])
    async_fire_time_changed(hass, _at(0))                  # Montag: nichts
    await hass.async_block_till_done()
    assert inst.calls == []
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.updater_updater_active"}, blocking=True)
    async_fire_time_changed(hass, _at(6))                  # Sonntag, aber pausiert
    await hass.async_block_till_done()
    assert inst.calls == []
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.updater_updater_active"}, blocking=True)
    async_fire_time_changed(hass, _at(6) + timedelta(days=7))   # der nächste Sonntag
    await hass.async_block_till_done()
    assert [c["entity_id"] for c in inst.calls] == [ADDON]


async def test_schedules_have_their_own_targets(hass: HomeAssistant) -> None:
    put(hass, ADDON)
    put(hass, DEVICE)
    inst = Installer(hass)
    _, ctrl, _ = await _setup(hass, [
        schedule("a", targets=[ADDON], time="03:00:00"),
        schedule("b", targets=[DEVICE], time="05:00:00")])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert [c["entity_id"] for c in inst.calls] == [ADDON]
    await ctrl.async_run_schedule(ctrl.schedules[1])
    assert [c["entity_id"] for c in inst.calls] == [ADDON, DEVICE]


async def test_sensors(hass: HomeAssistant) -> None:
    put(hass, ADDON)
    put(hass, DEVICE, state="off", installed="2.0", latest="2.0")
    Installer(hass)
    _, ctrl, _ = await _setup(hass, [schedule(targets=[ADDON, DEVICE], mode="notify")])
    available = hass.states.get("sensor.updater_available_updates")
    assert available.state == "1" and available.attributes["updates"] == ["esphome_update"]
    assert hass.states.get("sensor.updater_next_update_run").state != "unknown"
    assert hass.states.get("sensor.updater_last_update_run").state == "unknown"
    put(hass, DEVICE)                                         # zweites Update erscheint
    await hass.async_block_till_done()
    assert hass.states.get("sensor.updater_available_updates").state == "2"


# --- Flows ---------------------------------------------------------------------------------------


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "updater"})
    assert result["step_id"] == "updater"
    data = {"name": "Updater", "timeout_minutes": 30, "mobile_enabled": False,
            "tts_enabled": False, "persistent_enabled": False}
    bad = await hass.config_entries.flow.async_configure(result["flow_id"], sectioned(data))
    assert bad["errors"] == {"base": "no_method"}
    no_target = await hass.config_entries.flow.async_configure(
        bad["flow_id"], sectioned({**data, "mobile_enabled": True}))
    assert no_target["errors"] == {"base": "no_targets"}
    ok = await hass.config_entries.flow.async_configure(
        no_target["flow_id"], sectioned({**data, "persistent_enabled": True}))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["function_type"] == "updater" and ok["data"]["schedules"] == []


async def test_options_flow_schedules(hass: HomeAssistant) -> None:
    entry, _, _ = await _setup(hass, [])
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    assert result["step_id"] == "upd_menu" and "edit_schedule" not in result["menu_options"]

    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_schedule"})
    form = {"name": "Sonntag", "time": "03:00:00", "weekdays": ["sun"], "mode": "notify",
            "targets": [ADDON, DEVICE], "backup": False}
    bad = await flow.async_configure(result["flow_id"], {**form, "targets": []})
    assert bad["errors"] == {"base": "no_update_selected"}
    none = await flow.async_configure(bad["flow_id"], {**form, "weekdays": []})
    assert none["errors"] == {"base": "no_weekday"}
    result = await flow.async_configure(none["flow_id"], form)
    assert result["type"] is FlowResultType.MENU
    (created,) = entry.options["schedules"]
    assert created["targets"] == [ADDON, DEVICE] and created["mode"] == "notify"
    assert created["backup"] is False

    result = await flow.async_configure(result["flow_id"], {"next_step_id": "edit_schedule"})
    result = await flow.async_configure(result["flow_id"], {"schedule": created["id"]})
    result = await flow.async_configure(
        result["flow_id"], {**form, "mode": "install", "backup": True, "targets": [CORE]})
    (edited,) = entry.options["schedules"]
    assert edited["id"] == created["id"] and edited["mode"] == "install"
    assert edited["targets"] == [CORE] and edited["backup"] is True

    result = await flow.async_configure(result["flow_id"], {"next_step_id": "upd_general"})
    bad = await flow.async_configure(
        result["flow_id"], sectioned({"timeout_minutes": 10, "mobile_enabled": False,
                                      "tts_enabled": False, "persistent_enabled": False}))
    assert bad["errors"] == {"base": "no_method"}
    result = await flow.async_configure(
        bad["flow_id"], sectioned({"timeout_minutes": 10, "mobile_enabled": True,
                                   "mobile_targets": ["mobile_app_phone"],
                                   "tts_enabled": False, "persistent_enabled": False}))
    assert entry.options["timeout_minutes"] == 10

    result = await flow.async_configure(result["flow_id"], {"next_step_id": "delete_schedule"})
    result = await flow.async_configure(result["flow_id"], {"schedule": created["id"]})
    assert entry.options["schedules"] == []
    done = await flow.async_configure(result["flow_id"], {"next_step_id": "done"})
    assert done["type"] is FlowResultType.CREATE_ENTRY


# --- Komponenten ------------------------------------------------------------------------------


def register(hass, platform, name, disabled=False):
    from homeassistant.helpers import entity_registry as er

    entry = er.async_get(hass).async_get_or_create(
        "update", platform, name, suggested_object_id=name,
        disabled_by=er.RegistryEntryDisabler.USER if disabled else None)
    return entry.entity_id


def components_schedule(components, targets=(), **kw):
    return {**schedule(targets=targets, **kw), "components": list(components)}


async def test_resolve_targets_by_component(hass: HomeAssistant) -> None:
    addon = register(hass, "hassio", "addon_mosquitto")
    device = register(hass, "esphome", "kitchen_firmware")
    card = register(hass, "hacs", "some_card")
    off = register(hass, "esphome", "disabled_firmware", disabled=True)
    for entity in (CORE, SUPERVISOR, OS, addon, device, card, off):
        put(hass, entity)
    resolve = lambda comps, targets=(): upd.resolve_targets(  # noqa: E731
        hass, components_schedule(comps, targets))
    assert resolve(["core"]) == [CORE]
    assert sorted(resolve(["supervisor", "os"])) == sorted([SUPERVISOR, OS])
    assert resolve(["addons"]) == [addon]
    assert resolve(["esphome"]) == [device]        # deaktivierte Entität zählt nicht
    assert resolve(["other"]) == [card]
    assert resolve([]) == []
    # Vereinigung mit Einzel-Entitäten, ohne Doppelte
    assert resolve(["addons"], [device, addon]) == [device, addon]
    assert upd.component_of(hass, "update.unbekannt") == "other"


async def test_install_only_selected_components(hass: HomeAssistant) -> None:
    addon = register(hass, "hassio", "addon_mosquitto")
    device = register(hass, "esphome", "kitchen_firmware")
    for entity in (CORE, addon, device):
        put(hass, entity)
    inst = Installer(hass)
    _, ctrl, push = await _setup(hass, [components_schedule(["addons", "esphome"])])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert sorted(c["entity_id"] for c in inst.calls) == sorted([addon, device])
    assert CORE not in [c["entity_id"] for c in inst.calls]
    assert ctrl.last_run["installed"] == 2


async def test_components_are_resolved_at_run_time(hass: HomeAssistant) -> None:
    inst = Installer(hass)
    _, ctrl, _ = await _setup(hass, [components_schedule(["addons"])])
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert inst.calls == []
    later = register(hass, "hassio", "addon_neu")          # erst nach dem Start vorhanden
    put(hass, later)
    await ctrl.async_run_schedule(ctrl.schedules[0])
    assert [c["entity_id"] for c in inst.calls] == [later]


async def test_available_updates_counts_components(hass: HomeAssistant) -> None:
    addon = register(hass, "hassio", "addon_mosquitto")
    put(hass, addon)
    put(hass, CORE)
    _, ctrl, _ = await _setup(hass, [components_schedule(["addons"])])
    assert ctrl.available_updates() == ["addon_mosquitto"]
    assert hass.states.get("sensor.updater_available_updates").state == "1"


async def test_schedule_summary_with_components(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    text = upd.schedule_summary(hass, components_schedule(["os", "core", "addons"], [ADDON], mode="notify"))
    assert text == "Plan s1: 03:00, Core, OS, Add-ons, 1 updates, notify"
    hass.config.language = "de"
    assert "Core, OS, Add-ons" in upd.schedule_summary(hass, components_schedule(["os", "core", "addons"]))
    # alte Zeitpläne ohne Komponenten unverändert
    hass.config.language = "en"
    assert upd.schedule_summary(hass, schedule()) == "Plan s1: 03:00, 1 updates, install"


async def test_options_flow_components_only(hass: HomeAssistant) -> None:
    entry, _, _ = await _setup(hass, [])
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_schedule"})
    form = {"name": "Nachts", "time": "03:00:00", "weekdays": ["sun"], "mode": "install",
            "backup": False}
    bad = await flow.async_configure(result["flow_id"], form)
    assert bad["errors"] == {"base": "no_update_selected"}
    ok = await flow.async_configure(bad["flow_id"], {**form, "components": ["addons", "esphome"]})
    assert ok["type"] is FlowResultType.MENU
    (created,) = entry.options["schedules"]
    assert created["components"] == ["addons", "esphome"] and created["targets"] == []
