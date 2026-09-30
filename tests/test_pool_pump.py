from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.ha_housekeeper.const import DOMAIN

PUMP = "switch.pool_pump"
ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def _setup(hass, windows, pump_state=STATE_OFF):
    hass.states.async_set(PUMP, pump_state)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pool",
        data={"function_type": "pool_pump", "pump_entity": PUMP},
        options={"pump_entity": PUMP, "windows": windows},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _tick(hass, freezer, minutes):
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _calls(hass):
    on = async_mock_service(hass, "homeassistant", "turn_on")
    off = async_mock_service(hass, "homeassistant", "turn_off")
    return on, off


async def test_switches_at_window_boundaries(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 07:59:30+00:00")
    on, off = _calls(hass)
    await hass.config.async_set_time_zone("UTC")
    await _setup(hass, [{"start": "08:00:00", "end": "09:00:00", "days": ALL}])
    on.clear(); off.clear()

    await _tick(hass, freezer, 1)  # 08:00:30 -> Fensterbeginn
    assert len(on) == 1 and on[0].data["entity_id"] == PUMP
    hass.states.async_set(PUMP, STATE_ON)

    await _tick(hass, freezer, 30)  # innerhalb, keine weiteren Aufrufe
    assert len(on) == 1 and not off

    await _tick(hass, freezer, 30)  # 09:00:30 -> Ende
    assert len(off) == 1


async def test_startup_syncs_inside_window(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 08:30:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    on, off = _calls(hass)
    await _setup(hass, [{"start": "08:00:00", "end": "09:00:00", "days": ALL}])
    assert len(on) == 1


async def test_manual_intervention_not_overridden(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 08:30:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    on, off = _calls(hass)
    await _setup(hass, [{"start": "08:00:00", "end": "09:00:00", "days": ALL}], STATE_ON)
    on.clear(); off.clear()
    hass.states.async_set(PUMP, STATE_OFF)  # Nutzer schaltet manuell aus
    await _tick(hass, freezer, 5)
    assert not on and not off


async def test_unavailable_pump_retried(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 08:30:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    on, off = _calls(hass)
    await _setup(
        hass,
        [{"start": "08:00:00", "end": "09:00:00", "days": ALL}],
        STATE_UNAVAILABLE,
    )
    assert not on
    hass.states.async_set(PUMP, STATE_OFF)
    await hass.async_block_till_done()
    assert len(on) == 1


async def test_disabled_schedule_does_nothing(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 07:59:30+00:00")
    await hass.config.async_set_time_zone("UTC")
    on, off = _calls(hass)
    await _setup(hass, [{"start": "08:00:00", "end": "09:00:00", "days": ALL}])
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.pool_schedule_active"}, blocking=True
    )
    on.clear(); off.clear()
    await _tick(hass, freezer, 1)
    assert not on


async def test_run_pump_service_and_expiry(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    on, off = _calls(hass)
    await _setup(hass, [{"start": "08:00:00", "end": "09:00:00", "days": ALL}])
    on.clear(); off.clear()
    await hass.services.async_call(DOMAIN, "run_pump", {"duration": 10}, blocking=True)
    assert len(on) == 1
    hass.states.async_set(PUMP, STATE_ON)
    await _tick(hass, freezer, 11)
    assert len(off) == 1


async def test_runtime_and_entities(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    await _setup(hass, [{"start": "18:00:00", "end": "19:00:00", "days": ALL}])
    hass.states.async_set(PUMP, STATE_ON)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=15))
    hass.states.async_set(PUMP, STATE_OFF)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.pool_runtime_today")
    assert state is not None and float(state.state) == 15.0
    nxt = hass.states.get("sensor.pool_next_start")
    assert nxt.state.startswith("2026-09-28T18:00:00")
    assert hass.states.get("binary_sensor.pool_pump_should_run").state == STATE_OFF


async def test_enabled_state_survives_restart(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    _calls(hass)
    entry = await _setup(hass, [{"start": "18:00:00", "end": "19:00:00", "days": ALL}])
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.pool_schedule_active"}, blocking=True
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.pool_schedule_active").state == STATE_OFF


async def test_dry_run_alarm_uses_shared_notification(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    _calls(hass)
    create = async_mock_service(hass, "persistent_notification", "create")
    dismiss = async_mock_service(hass, "persistent_notification", "dismiss")
    push = async_mock_service(hass, "notify", "mobile_app_phone")
    hass.states.async_set(PUMP, STATE_ON)
    hass.states.async_set(POWER, "90", {"unit_of_measurement": "W"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pool",
        data={"function_type": "pool_pump", "pump_entity": PUMP},
        options={
            "pump_entity": PUMP, "windows": [], "power_entity": POWER,
            "dry_min_power": 75, "dry_max_power": 100, "dry_duration": 5,
            "persistent_enabled": True, "mobile_enabled": True,
            "mobile_targets": ["mobile_app_phone"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _tick(hass, freezer, 5)
    assert _dry_state(hass) == STATE_ON
    assert len(create) == 1 and len(push) == 1
    assert "Trockenlauf" in push[0].data["title"] or "dry" in push[0].data["title"]
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.pool_acknowledge_dry_run"}, blocking=True
    )
    assert len(dismiss) == 1
    assert push[-1].data["message"] == "clear_notification"


async def test_run_pump_unknown_entry_rejected(hass: HomeAssistant):
    import pytest
    from homeassistant.exceptions import ServiceValidationError

    await _setup(hass, [])
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "run_pump", {"duration": 5, "entry_id": "nope"}, blocking=True
        )


async def test_unload(hass: HomeAssistant):
    entry = await _setup(hass, [])
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


POWER = "sensor.pump_power"


async def _setup_dry(hass, auto_off=False, pump_state=STATE_ON, power="90", windows=None):
    hass.states.async_set(PUMP, pump_state)
    hass.states.async_set(POWER, power, {"unit_of_measurement": "W"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pool",
        data={"function_type": "pool_pump", "pump_entity": PUMP},
        options={
            "pump_entity": PUMP,
            "windows": windows or [],
            "power_entity": POWER,
            "dry_min_power": 75,
            "dry_max_power": 100,
            "dry_duration": 5,
            "dry_auto_off": auto_off,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _dry_state(hass):
    return hass.states.get("binary_sensor.pool_dry_run_detected").state


async def test_dry_run_detected_after_duration_and_latched(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    on, off = _calls(hass)
    await _setup_dry(hass)
    assert _dry_state(hass) == STATE_OFF
    await _tick(hass, freezer, 4)
    assert _dry_state(hass) == STATE_OFF
    await _tick(hass, freezer, 1)
    assert _dry_state(hass) == STATE_ON
    assert not off  # ohne Auto-Aus wird nicht geschaltet

    # Pumpe aus -> Alarm bleibt gehalten; Neustart der Pumpe nimmt ihn zurück
    hass.states.async_set(PUMP, STATE_OFF)
    await _tick(hass, freezer, 1)
    assert _dry_state(hass) == STATE_ON
    hass.states.async_set(PUMP, STATE_ON)
    await hass.async_block_till_done()
    assert _dry_state(hass) == STATE_OFF


async def test_normal_load_never_triggers(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    _calls(hass)
    await _setup_dry(hass, power="250")
    await _tick(hass, freezer, 30)
    assert _dry_state(hass) == STATE_OFF


async def test_unavailable_power_is_not_dry_run(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    _calls(hass)
    await _setup_dry(hass, power=STATE_UNAVAILABLE)
    await _tick(hass, freezer, 30)
    assert _dry_state(hass) == STATE_OFF


async def test_kw_sensor_is_converted(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    _calls(hass)
    await _setup_dry(hass, power="0.09")
    hass.states.async_set(POWER, "0.09", {"unit_of_measurement": "kW"})
    await hass.async_block_till_done()
    await _tick(hass, freezer, 5)
    assert _dry_state(hass) == STATE_ON


async def test_auto_off_pauses_schedule_until_acknowledged(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    on, off = _calls(hass)
    await _setup_dry(
        hass,
        auto_off=True,
        windows=[{"start": "11:00:00", "end": "23:00:00", "days": ALL}],
    )
    on.clear(); off.clear()
    await _tick(hass, freezer, 5)
    assert _dry_state(hass) == STATE_ON
    assert len(off) == 1 and off[0].data["entity_id"] == PUMP
    assert hass.states.get("switch.pool_schedule_active").state == STATE_OFF
    hass.states.async_set(PUMP, STATE_OFF)

    await _tick(hass, freezer, 5)  # Zeitplan ist pausiert: Pumpe bleibt aus
    assert not on

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.pool_acknowledge_dry_run"}, blocking=True
    )
    await hass.async_block_till_done()
    assert _dry_state(hass) == STATE_OFF
    assert hass.states.get("switch.pool_schedule_active").state == STATE_ON
    assert len(on) == 1  # Zeitplan gleicht die Pumpe wieder an (im Fenster)


async def test_dry_run_entities_removed_when_not_configured(hass: HomeAssistant):
    entry = await _setup_dry(hass)
    assert hass.states.get("button.pool_acknowledge_dry_run") is not None
    hass.config_entries.async_update_entry(
        entry, options={"pump_entity": PUMP, "windows": [], "power_entity": None}
    )
    await hass.async_block_till_done()
    assert hass.states.get("button.pool_acknowledge_dry_run") is None
    assert hass.states.get("binary_sensor.pool_dry_run_detected") is None


async def test_no_windows_leaves_pump_alone(hass: HomeAssistant, freezer):
    freezer.move_to("2026-09-28 12:00:00+00:00")
    await hass.config.async_set_time_zone("UTC")
    on, off = _calls(hass)
    await _setup(hass, [], STATE_ON)
    await _tick(hass, freezer, 5)
    assert not on and not off


# --- Config- und Options-Flow -----------------------------------------------------


async def test_user_flow_and_duplicate(hass):
    from homeassistant.data_entry_flow import FlowResultType

    hass.states.async_set("switch.pump", "off")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "pool_pump"}
    )
    assert result["step_id"] == "pool_pump"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Garten", "pump_entity": "switch.pump"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"function_type": "pool_pump", "pump_entity": "switch.pump"}
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"function_type": "pool_pump"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Zweiter", "pump_entity": "switch.pump"}
    )
    assert result["type"] is FlowResultType.ABORT


async def test_options_windows_add_edit_delete(hass):
    from homeassistant.data_entry_flow import FlowResultType

    entry = await _setup(hass, [])
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    assert result["step_id"] == "pool_menu"
    assert result["menu_options"] == ["pool_general", "add_window", "dry_run", "done"]

    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_window"})
    bad = await flow.async_configure(
        result["flow_id"], {"start": "08:00:00", "end": "08:00:00", "days": ["mon"]}
    )
    assert bad["errors"] == {"base": "start_equals_end"}
    none = await flow.async_configure(
        bad["flow_id"], {"start": "08:00:00", "end": "09:00:00", "days": []}
    )
    assert none["errors"] == {"base": "no_weekday"}
    result = await flow.async_configure(
        none["flow_id"], {"start": "08:00:00", "end": "10:00:00", "days": ["mon"]}
    )
    assert result["type"] is FlowResultType.MENU
    assert "edit_window" in result["menu_options"]
    (window,) = entry.options["windows"]
    assert window["start"] == "08:00:00" and window["days"] == ["mon"]

    result = await flow.async_configure(result["flow_id"], {"next_step_id": "edit_window"})
    result = await flow.async_configure(result["flow_id"], {"window": window["id"]})
    result = await flow.async_configure(
        result["flow_id"], {"start": "07:00:00", "end": "09:00:00", "days": ["mon", "tue"]}
    )
    (edited,) = entry.options["windows"]
    assert edited["id"] == window["id"] and edited["start"] == "07:00:00"

    result = await flow.async_configure(result["flow_id"], {"next_step_id": "delete_window"})
    result = await flow.async_configure(result["flow_id"], {"window": window["id"]})
    assert entry.options["windows"] == []
    done = await flow.async_configure(result["flow_id"], {"next_step_id": "done"})
    assert done["type"] is FlowResultType.CREATE_ENTRY


async def test_options_max_windows(hass):
    entry = await _setup(hass, [])
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "windows": [
                {"id": str(i), "start": "08:00:00", "end": "09:00:00", "days": ["mon"]}
                for i in range(8)
            ],
        },
    )
    await hass.async_block_till_done()
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_window"})
    result = await flow.async_configure(
        result["flow_id"], {"start": "10:00:00", "end": "11:00:00", "days": ["tue"]}
    )
    assert result["errors"] == {"base": "too_many_windows"}


async def test_options_dry_run_set_validate_and_clear(hass):
    from homeassistant.data_entry_flow import FlowResultType

    entry = await _setup(hass, [])
    flow = hass.config_entries.options

    async def open_dry():
        r = await flow.async_init(entry.entry_id)
        return await flow.async_configure(r["flow_id"], {"next_step_id": "dry_run"})

    base = {"dry_duration": 5, "dry_auto_off": True, "mobile_enabled": False,
            "tts_enabled": False, "persistent_enabled": True}
    r = await open_dry()
    bad = await flow.async_configure(
        r["flow_id"],
        {**base, "power_entity": "sensor.p", "dry_min_power": 100, "dry_max_power": 75},
    )
    assert bad["errors"] == {"base": "min_ge_max"}
    no_target = await flow.async_configure(
        bad["flow_id"],
        {**base, "power_entity": "sensor.p", "dry_min_power": 75, "dry_max_power": 100,
         "mobile_enabled": True},
    )
    assert no_target["errors"] == {"base": "no_targets"}
    ok = await flow.async_configure(
        no_target["flow_id"],
        {**base, "power_entity": "sensor.p", "dry_min_power": 75, "dry_max_power": 100},
    )
    assert ok["type"] is FlowResultType.MENU
    assert entry.options["power_entity"] == "sensor.p"
    assert entry.options["dry_auto_off"] is True
    assert entry.options["pump_entity"] == PUMP  # bleibt erhalten
    await hass.async_block_till_done()
    assert hass.states.get("button.pool_acknowledge_dry_run") is not None

    r = await open_dry()
    cleared = await flow.async_configure(
        r["flow_id"], {**base, "dry_min_power": 75, "dry_max_power": 100}
    )
    assert cleared["type"] is FlowResultType.MENU
    assert entry.options["power_entity"] is None
    await hass.async_block_till_done()
    assert hass.states.get("button.pool_acknowledge_dry_run") is None
