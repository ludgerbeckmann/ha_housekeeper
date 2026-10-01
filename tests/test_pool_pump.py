from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from .helpers import is_menu, menu_options, sectioned, make_entry, reconfigure, update_entry
from custom_components.ha_housekeeper.const import DOMAIN

PUMP = "switch.pool_pump"
ALL = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def _setup(hass, windows, pump_state=STATE_OFF):
    hass.states.async_set(PUMP, pump_state)
    entry = make_entry(
        domain=DOMAIN,
        title="Pool",
        data={"function_type": "pool_pump", "pump_entity": PUMP},
        options={"pump_entity": PUMP, "windows": windows},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
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
    assert await hass.config_entries.async_unload(entry.hub_id)
    assert await hass.config_entries.async_setup(entry.hub_id)
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
    entry = make_entry(
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
    assert await hass.config_entries.async_setup(entry.hub_id)
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
    assert await hass.config_entries.async_unload(entry.hub_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


POWER = "sensor.pump_power"


async def _setup_dry(hass, auto_off=False, pump_state=STATE_ON, power="90", windows=None):
    hass.states.async_set(PUMP, pump_state)
    hass.states.async_set(POWER, power, {"unit_of_measurement": "W"})
    entry = make_entry(
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
    assert await hass.config_entries.async_setup(entry.hub_id)
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
    update_entry(hass, entry, {"pump_entity": PUMP, "windows": [], "power_entity": None}
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
        result["flow_id"], {"next_step_id": "hub_pool_pump"}
    )
    assert result["step_id"] == "new_pool_pump"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Garten", "pump_entity": "switch.pump"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Pool control"                      # Hub heißt wie die Funktion (Sprache von HA)
    assert result["data"] == {"function_type": "pool_pump", "hub": True}
    (first,) = result["subentries"]
    assert first["title"] == "Garten" and first["data"]["pump_entity"] == "switch.pump"
    await hass.async_block_till_done()
    (hub,) = hass.config_entries.async_entries(DOMAIN)
    assert next(iter(hub.subentries.values())).title == "Garten"

    # zweiter Hub desselben Typs: nicht möglich, weitere Pools kommen als Untereintrag
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "hub_pool_pump"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"

    # weiterer Pool als Untereintrag; dieselbe Pumpe wird abgelehnt
    sub = await hass.config_entries.subentries.async_init(
        (hub.entry_id, "pool_pump"), context={"source": "user"})
    assert sub["step_id"] == "new_pool_pump"
    sub = await hass.config_entries.subentries.async_configure(
        sub["flow_id"], {"name": "Zweiter", "pump_entity": "switch.pump"})
    assert sub["type"] is FlowResultType.ABORT and sub["reason"] == "pump_configured"
    hass.states.async_set("switch.pump2", "off")
    sub = await hass.config_entries.subentries.async_init(
        (hub.entry_id, "pool_pump"), context={"source": "user"})
    sub = await hass.config_entries.subentries.async_configure(
        sub["flow_id"], {"name": "Zweiter", "pump_entity": "switch.pump2"})
    assert sub["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert sorted(s.title for s in hub.subentries.values()) == ["Garten", "Zweiter"]
    assert hass.states.get("switch.garten_schedule_active") is not None
    assert hass.states.get("switch.zweiter_schedule_active") is not None


async def test_options_windows_add_edit_delete(hass):
    entry = await _setup(hass, [])
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    assert result["step_id"] == "pool_menu"
    assert menu_options(result) == ["pool_general", "add_window", "dry_run", "heater"]

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
    assert is_menu(result)
    assert "edit_window" in menu_options(result)
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


async def test_options_max_windows(hass):
    entry = await _setup(hass, [])
    update_entry(hass, entry, {
            **entry.options,
            "windows": [
                {"id": str(i), "start": "08:00:00", "end": "09:00:00", "days": ["mon"]}
                for i in range(8)
            ],
        },
    )
    await hass.async_block_till_done()
    flow = hass.config_entries.subentries
    result = await reconfigure(hass, entry)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_window"})
    result = await flow.async_configure(
        result["flow_id"], {"start": "10:00:00", "end": "11:00:00", "days": ["tue"]}
    )
    assert result["errors"] == {"base": "too_many_windows"}


async def test_options_dry_run_set_validate_and_clear(hass):
    entry = await _setup(hass, [])
    flow = hass.config_entries.subentries

    async def open_dry():
        r = await reconfigure(hass, entry)
        return await flow.async_configure(r["flow_id"], {"next_step_id": "dry_run"})

    base = {"dry_duration": 5, "dry_auto_off": True, "mobile_enabled": False,
            "tts_enabled": False, "persistent_enabled": True}
    r = await open_dry()
    bad = await flow.async_configure(
        r["flow_id"],
        sectioned({**base, "power_entity": "sensor.p", "dry_min_power": 100, "dry_max_power": 75}),
    )
    assert bad["errors"] == {"base": "min_ge_max"}
    no_target = await flow.async_configure(
        bad["flow_id"],
        sectioned({**base, "power_entity": "sensor.p", "dry_min_power": 75, "dry_max_power": 100,
                   "mobile_enabled": True}),
    )
    assert no_target["errors"] == {"base": "no_targets"}
    ok = await flow.async_configure(
        no_target["flow_id"],
        sectioned({**base, "power_entity": "sensor.p", "dry_min_power": 75, "dry_max_power": 100}),
    )
    assert is_menu(ok)
    assert entry.options["power_entity"] == "sensor.p"
    assert entry.options["dry_auto_off"] is True
    assert entry.options["pump_entity"] == PUMP  # bleibt erhalten
    await hass.async_block_till_done()
    assert hass.states.get("button.pool_acknowledge_dry_run") is not None

    r = await open_dry()
    cleared = await flow.async_configure(
        r["flow_id"], sectioned({**base, "dry_min_power": 75, "dry_max_power": 100})
    )
    assert is_menu(cleared)
    assert entry.options["power_entity"] is None
    await hass.async_block_till_done()
    assert hass.states.get("button.pool_acknowledge_dry_run") is None


# --- Poolheizung -----------------------------------------------------------------------------------

HEATER = "switch.pool_heater"
TEMP = "sensor.pool_temperature"


async def _setup_heater(hass, temp="20", heater_state=STATE_OFF, **over):
    hass.states.async_set(HEATER, heater_state)
    hass.states.async_set(TEMP, temp)
    options = {"pump_entity": PUMP, "windows": [], "heater_entity": HEATER,
               "temperature_entity": TEMP, "heater_on_above": 28, "heater_off_below": 26, **over}
    hass.states.async_set(PUMP, STATE_OFF)
    entry = make_entry(
        domain=DOMAIN, title="Pool",
        data={"function_type": "pool_pump", "pump_entity": PUMP}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry


async def test_heater_switches_on_above_and_off_below(hass: HomeAssistant):
    on, off = _calls(hass)
    await _setup_heater(hass, temp="20")
    assert not on and not off or all(c.data["entity_id"] != HEATER for c in on)
    on.clear(); off.clear()
    hass.states.async_set(TEMP, "27")             # zwischen den Schwellen: nichts
    await hass.async_block_till_done()
    assert not on and not off
    hass.states.async_set(TEMP, "28")             # ab der Einschaltschwelle
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in on] == [HEATER]
    hass.states.async_set(HEATER, STATE_ON)
    hass.states.async_set(TEMP, "26.5")           # Hysterese: bleibt an
    await hass.async_block_till_done()
    assert not off
    hass.states.async_set(TEMP, "26")             # bei der Ausschaltschwelle
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in off] == [HEATER]
    sensor = hass.states.get("binary_sensor.pool_heater_should_run")
    assert sensor.state == STATE_OFF and sensor.attributes["temperatur"] == 26.0


async def test_heater_switches_only_on_change(hass: HomeAssistant):
    on, off = _calls(hass)
    await _setup_heater(hass, temp="30")
    assert [c.data["entity_id"] for c in on] == [HEATER]
    hass.states.async_set(HEATER, STATE_ON)
    on.clear()
    hass.states.async_set(TEMP, "31")
    hass.states.async_set(TEMP, "32")
    await hass.async_block_till_done()
    assert not on
    hass.states.async_set(HEATER, STATE_OFF)      # manuell ausgeschaltet: bleibt aus
    await hass.async_block_till_done()
    assert not on


async def test_heater_ignores_invalid_temperature(hass: HomeAssistant):
    on, off = _calls(hass)
    await _setup_heater(hass, temp=STATE_UNAVAILABLE)
    hass.states.async_set(TEMP, "unknown")
    hass.states.async_set(TEMP, "abc")
    await hass.async_block_till_done()
    assert not on and not off


async def test_heater_unreachable_is_retried(hass: HomeAssistant):
    on, off = _calls(hass)
    await _setup_heater(hass, temp="30", heater_state=STATE_UNAVAILABLE)
    assert not on
    hass.states.async_set(HEATER, STATE_OFF)      # wieder erreichbar
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in on] == [HEATER]


async def test_heater_auto_switch_stops_and_reevaluates(hass: HomeAssistant):
    on, off = _calls(hass)
    await _setup_heater(hass, temp="30")
    on.clear()
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.pool_heater_automatic"}, blocking=True)
    hass.states.async_set(TEMP, "20")
    await hass.async_block_till_done()
    assert not off                                # Automatik aus: nie geschaltet
    assert hass.states.get("binary_sensor.pool_heater_should_run").state == STATE_OFF
    hass.states.async_set(TEMP, "31")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.pool_heater_automatic"}, blocking=True)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in on] == [HEATER]


async def test_heater_entities_only_when_configured(hass: HomeAssistant):
    await _setup(hass, [])
    assert hass.states.get("switch.pool_heater_automatic") is None
    assert hass.states.get("binary_sensor.pool_heater_should_run") is None


async def test_options_heater_set_validate_and_clear(hass: HomeAssistant):
    entry = await _setup(hass, [])
    flow = hass.config_entries.subentries

    async def start():
        r = await reconfigure(hass, entry)
        return await flow.async_configure(r["flow_id"], {"next_step_id": "heater"})

    result = await start()
    assert result["step_id"] == "heater"
    bad = await flow.async_configure(result["flow_id"], {
        "heater_entity": HEATER, "heater_on_above": 28, "heater_off_below": 26})
    assert bad["errors"] == {"base": "no_temperature"}
    bad = await flow.async_configure(bad["flow_id"], {
        "heater_entity": HEATER, "temperature_entity": TEMP,
        "heater_on_above": 26, "heater_off_below": 26})
    assert bad["errors"] == {"base": "off_ge_on"}
    ok = await flow.async_configure(bad["flow_id"], {
        "heater_entity": HEATER, "temperature_entity": TEMP,
        "heater_on_above": 29, "heater_off_below": 27})
    assert is_menu(ok)
    assert entry.options["heater_entity"] == HEATER and entry.options["heater_on_above"] == 29
    await hass.async_block_till_done()
    assert hass.states.get("switch.pool_heater_automatic") is not None

    result = await start()                        # Heizung entfernen
    ok = await flow.async_configure(result["flow_id"], {
        "heater_on_above": 29, "heater_off_below": 27})
    assert is_menu(ok) and entry.options["heater_entity"] is None
    await hass.async_block_till_done()
    assert hass.states.get("switch.pool_heater_automatic") is None
