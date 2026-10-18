"""Tests für die Funktion Energiemonitor."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .helpers import is_menu, make_entry, new_instance, reconfigure
from custom_components.ha_housekeeper.const import DOMAIN
from custom_components.ha_housekeeper.energy_monitor import (
    common_part, persons_share_b, settle, share_a, split_interval, utility_cost_b,
)
from custom_components.ha_housekeeper.flows.energy import pv_price_value
from custom_components.ha_housekeeper.issues import collect_references

GRID, FEED, PV, A, B = (f"sensor.{n}" for n in ("grid", "feed", "pv", "meter_a", "meter_b"))
BASE = {
    "function_type": "energy_monitor", "name": "Haus", "grid_energy": GRID, "feed_in_energy": FEED,
    "pv_energy": PV, "meter_a_energy": A, "meter_b_energy": B, "unit_a_name": "Altbau",
    "unit_b_name": "Neubau", "grid_price": 34.0, "pv_price": 16.26, "base_fee_monthly": 20.0,
    "base_fee_share_b": 50.0,
}


def _set(hass, grid=0.0, feed=0.0, pv=0.0, a=0.0, b=0.0) -> None:
    for entity, value in ((GRID, grid), (FEED, feed), (PV, pv), (A, a), (B, b)):
        hass.states.async_set(entity, str(value))


async def _setup(hass: HomeAssistant, **over):
    _set(hass)
    entry = make_entry(domain=DOMAIN, title="Haus", data={**BASE, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


async def _tick(hass: HomeAssistant, freezer) -> None:
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _entity(hass, key, entry):
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")


def test_split_interval() -> None:
    part = split_interval(d_grid=10, d_feed=30, d_pv=50, d_a=3, d_b=1)
    assert part["grid_a"] == pytest.approx(7.5) and part["grid_b"] == pytest.approx(2.5)
    assert part["pv_a"] == pytest.approx(15) and part["pv_b"] == pytest.approx(5)     # Eigenverbrauch 20 kWh
    assert part["grid_a"] + part["grid_b"] == pytest.approx(10)
    assert split_interval(5, 0, 0, 0, 0) is None                   # nichts verbraucht: nichts zu verteilen
    assert split_interval(1, 9, 5, 1, 1)["pv_a"] == 0               # Einspeisung > Erzeugung: kein Eigenverbrauch


def test_settle_and_share() -> None:
    acc = {"grid_a": 4053, "grid_b": 1170, "pv_a": 3951, "pv_b": 1140, "cons_a": 3544, "cons_b": 1023}
    result = settle(acc, 34, 16.26, 0, 50, 1)
    assert result["grid_cost_b"] == pytest.approx(397.8)
    assert result["pv_credit_a"] == pytest.approx(642.4, abs=0.1)
    assert result["owed"] == pytest.approx(-244.6, abs=0.2)            # Familie schuldet dem Vater
    assert settle(acc, 34, 0, 0, 50, 1)["owed"] == pytest.approx(397.8)  # PV kostenlos
    assert settle(acc, 34, 0, 20, 25, 3)["base_fee_b"] == pytest.approx(15)
    assert share_a(acc) == pytest.approx(77.6, abs=0.1) and share_a({}) is None


def test_pv_price_value() -> None:
    assert pv_price_value("16,26") == 16.26 and pv_price_value(" 8.17 ") == 8.17
    assert pv_price_value("0") == 0 and pv_price_value("abc") is None and pv_price_value("-1") is None


async def test_allocation_over_time(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-10-05 12:00:00+02:00")
    entry, controller = await _setup(hass)
    assert controller.baseline is not None
    # Zeitraum 1: A verbraucht 3, B 1; Netz 10, Einspeisung 30, PV 50 (Eigenverbrauch 20)
    _set(hass, grid=10, feed=30, pv=50, a=3, b=1)
    await _tick(hass, freezer)
    assert controller.totals["grid_a"] == pytest.approx(7.5) and controller.totals["pv_b"] == pytest.approx(5)
    # Zeitraum 2: nur B verbraucht
    _set(hass, grid=14, feed=30, pv=54, a=3, b=5)
    await _tick(hass, freezer)
    assert controller.totals["grid_b"] == pytest.approx(2.5 + 4) and controller.totals["grid_a"] == pytest.approx(7.5)
    # Sensoren
    grid_a = hass.states.get(_entity(hass, "energy_grid_a", entry))
    assert float(grid_a.state) == pytest.approx(7.5) and grid_a.attributes["unit_of_measurement"] == "kWh"
    assert grid_a.name.endswith("Altbau") or "Altbau" in grid_a.name
    month = hass.states.get(_entity(hass, "energy_settlement_month", entry))
    # B: Netzstrom 6,5 kWh * 0,34 + Grundpreis 10 - PV_A 15 kWh * 0,1626
    assert float(month.state) == pytest.approx(6.5 * 0.34 + 10 - 15 * 0.1626, abs=0.01)
    assert month.attributes["direction"] == "b_owes_a" and month.attributes["pv_kwh_a"] == pytest.approx(15)
    assert float(hass.states.get(_entity(hass, "energy_share", entry)).state) == pytest.approx(37.5)


async def test_unavailable_reset_and_idle(hass: HomeAssistant, freezer) -> None:
    entry, controller = await _setup(hass)
    _set(hass, grid=5, feed=0, pv=0, a=0, b=0)                         # nur Netzbezug, kein Verbrauch an den Zählern
    await _tick(hass, freezer)
    assert controller.totals["grid_a"] == 0                              # weiter sammeln
    hass.states.async_set(PV, "unavailable")
    await _tick(hass, freezer)
    assert controller.totals["grid_a"] == 0
    _set(hass, grid=9, feed=0, pv=0, a=2, b=2)                          # der gesammelte Zeitraum wird jetzt verteilt
    await _tick(hass, freezer)
    assert controller.totals["grid_a"] == pytest.approx(4.5) and controller.totals["grid_b"] == pytest.approx(4.5)
    before = dict(controller.totals)
    _set(hass, grid=1, feed=0, pv=0, a=0, b=0)                          # Zähler zurückgesetzt: Zeitraum überspringen
    await _tick(hass, freezer)
    assert controller.totals == before and controller.baseline["grid_energy"] == 1


async def test_months_year_and_restore(hass: HomeAssistant, freezer, hass_storage) -> None:
    freezer.move_to("2026-10-31 12:00:00+01:00")
    entry, controller = await _setup(hass)
    _set(hass, grid=4, pv=0, a=1, b=1)
    await _tick(hass, freezer)
    freezer.move_to("2026-11-02 12:00:00+01:00")
    _set(hass, grid=10, pv=0, a=3, b=3)
    await _tick(hass, freezer)
    assert set(controller.months) == {"2026-10", "2026-11"}
    assert controller.month()["grid_b"] == pytest.approx(3) and controller.month("2026-10")["grid_b"] == pytest.approx(2)
    year = hass.states.get(_entity(hass, "energy_settlement_year", entry))
    assert year.attributes["months"] == 2 and year.attributes["base_fee_b"] == pytest.approx(20)   # 2 Monate * 10
    # nach einem Neustart bleiben Summen und Stand erhalten
    assert await hass.config_entries.async_reload(entry.hub_id)
    await hass.async_block_till_done()
    restored = hass.data[DOMAIN][entry.entry_id]
    assert restored.totals["grid_b"] == pytest.approx(5) and restored.baseline["grid_energy"] == 10


async def test_config_flow_and_settings_page(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "energy_monitor")
    assert result["step_id"] == "new_energy_monitor"
    flow = hass.config_entries.subentries

    def page(**over):
        meters = {"name": "Haus", "grid_energy": GRID, "feed_in_energy": FEED, "pv_energy": PV,
                  "meter_a_energy": A, "meter_b_energy": B}
        prices = {"grid_price": 34, "pv_price": "16.26", "base_fee_monthly": 0, "base_fee_share_b": 50}
        meters.update({k: v for k, v in over.items() if k in meters})
        prices.update({k: v for k, v in over.items() if k in prices})
        units = {"unit_a_name": "Altbau", "unit_b_name": "Neubau", "persons_a": 2, "persons_b": 2,
                 "area_a": 100, "area_b": 50}
        water = {"water_price": 0, "water_base_fee": 0}
        gas = {"gas_price": 0, "gas_base_fee": 0, "gas_key": "area"}
        water.update({k: v for k, v in over.items() if k == "water_meter"})
        gas.update({k: v for k, v in over.items() if k == "gas_meter"})
        for group in (units, water, gas):
            group.update({k: v for k, v in over.items() if k in group})
        common = {"common_power": 0, "common_key": "area"}
        common.update({k: v for k, v in over.items() if k in common or k == "common_meter"})
        return {"meters": meters, "units": units, "prices": prices, "water": water, "gas": gas,
                "common": common}

    bad = await flow.async_configure(result["flow_id"], page(meter_b_energy=A))
    assert bad["errors"] == {"base": "duplicate_meter"}
    bad = await flow.async_configure(result["flow_id"], page(water_meter=WATER, persons_a=0, persons_b=0))
    assert bad["errors"] == {"base": "no_persons"}
    bad = await flow.async_configure(result["flow_id"], page(gas_meter=GAS, area_a=0, area_b=0))
    assert bad["errors"] == {"base": "no_area"}
    bad = await flow.async_configure(result["flow_id"], page(common_power=40, area_a=0, area_b=0))
    assert bad["errors"] == {"base": "no_area"}
    bad = await flow.async_configure(
        result["flow_id"], page(common_power=40, common_key="persons", persons_a=0, persons_b=0))
    assert bad["errors"] == {"base": "no_persons"}
    bad = await flow.async_configure(result["flow_id"], page(pv_price="viel"))
    assert bad["errors"] == {"base": "invalid_price"}
    ok = await flow.async_configure(result["flow_id"], page(pv_price="12,5"))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["pv_price"] == 12.5 and "name" not in ok["data"]
    assert ok["data"]["water_meter"] is None and ok["data"]["gas_key"] == "area"

    entry, _ = await _setup(hass)
    page_result = await reconfigure(hass, entry)
    assert page_result["step_id"] == "em_settings" and not is_menu(page_result)
    sections = {str(k): v for k, v in page_result["data_schema"].schema.items()}
    assert list(sections) == ["meters", "units", "prices", "water", "gas", "common"]
    assert [name for name, sec in sections.items() if not sec.options["collapsed"]] == ["meters"]
    done = await flow.async_configure(page_result["flow_id"], page(pv_price="0", grid_price=30, name="Gesamt"))
    assert done["reason"] == "reconfigure_successful"
    assert entry.options["pv_price"] == 0 and entry.options["grid_price"] == 30 and entry.title.endswith("Gesamt")


def test_references() -> None:
    entry = make_entry(domain=DOMAIN, title="Haus", data=BASE)
    entities, _ = collect_references(entry.sub)
    assert {GRID, FEED, PV, A, B} <= set(entities)


WATER, GAS = "sensor.water", "sensor.gas"
UTIL = {
    "water_meter": WATER, "water_price": 4.0, "water_base_fee": 10.0,
    "gas_meter": GAS, "gas_price": 1.0, "gas_base_fee": 20.0,
    "persons_a": 2.0, "persons_b": 2.0, "area_a": 100.0, "area_b": 50.0,
}


def test_utility_shares() -> None:
    assert persons_share_b(3, 1) == pytest.approx(0.25) and persons_share_b(0, 0) == 0
    result = utility_cost_b(volume=10, price=4, base_fee=10, share_b=0.25, months=2)
    assert result["total"] == pytest.approx(60) and result["cost_b"] == pytest.approx(15)


async def test_water_and_gas(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set(WATER, "100")
    hass.states.async_set(GAS, "500")
    entry, controller = await _setup(hass, **UTIL)
    assert controller.util_baseline == {"water": 100.0, "gas": 500.0}
    hass.states.async_set(WATER, "110")
    hass.states.async_set(GAS, "530")
    await _tick(hass, freezer)
    assert controller.month()["water"] == pytest.approx(10) and controller.month()["gas"] == pytest.approx(30)
    water = hass.states.get(_entity(hass, "energy_water_cost_month", entry))
    gas = hass.states.get(_entity(hass, "energy_gas_cost_month", entry))
    assert float(water.state) == pytest.approx((10 * 4 + 10) * 0.5)          # Personen 2:2
    assert float(gas.state) == pytest.approx((30 * 1 + 20) / 3, abs=0.01)            # Wohnfläche 100:50
    assert gas.attributes["share_b"] == pytest.approx(33.33)
    month = hass.states.get(_entity(hass, "energy_settlement_month", entry))
    assert month.attributes["water_cost_b"] == pytest.approx(25) and month.attributes["gas_m3"] == pytest.approx(30)
    assert float(month.state) == pytest.approx(10 + 25 + 50 / 3, abs=0.01)             # Grundpreis Strom B + Wasser + Gas
    hass.states.async_set(WATER, "5")                                        # Zähler zurückgesetzt: überspringen
    await _tick(hass, freezer)
    assert controller.month()["water"] == pytest.approx(10) and controller.util_baseline["water"] == 5
    assert controller.share_b("water") == pytest.approx(0.5)


async def test_gas_by_persons_and_no_meter(hass: HomeAssistant) -> None:
    entry, controller = await _setup(hass, **{**UTIL, "gas_key": "persons", "persons_b": 6.0})
    assert controller.share_b("gas") == pytest.approx(0.75)
    plain, other = await _setup(hass)
    assert not other.configured("water") and _entity(hass, "energy_water_month", plain) is None


def test_common_electricity_is_moved_from_a_to_b() -> None:
    # A zählt 6 kWh (davon 2 Allgemeinstrom), B 2 kWh; B trägt 1/3 des Allgemeinstroms
    common, shift = common_part(d_a=6, meter_delta=2, power_w=0, hours=0, share_b=1 / 3)
    assert common == 2 and shift == pytest.approx(2 / 3)
    part = split_interval(d_grid=8, d_feed=0, d_pv=0, d_a=6, d_b=2, shift=shift)
    assert part["cons_a"] == pytest.approx(6 - 2 / 3) and part["cons_b"] == pytest.approx(2 + 2 / 3)
    assert part["grid_a"] + part["grid_b"] == pytest.approx(8)
    # ohne Zähler: feste Leistung × Zeit, begrenzt durch den Verbrauch von A
    assert common_part(6, None, 200, 5, 0.5) == (1.0, 0.5)
    assert common_part(0.4, None, 200, 5, 0.5) == (0.4, 0.2)
    assert common_part(6, None, 0, 5, 0.5) == (0.0, 0.0)


async def test_constant_power_shifts_consumption(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-10-10 12:00:00+00:00")
    entry, controller = await _setup(
        hass, common_power=1000.0, common_key="half", area_a=100.0, area_b=50.0)
    freezer.move_to("2026-10-10 13:59:00+00:00")              # nach dem Tick (+1 Minute) sind es 2 Stunden: 2 kWh
    _set(hass, grid=8, a=6, b=2)
    await _tick(hass, freezer)
    assert controller.month()["common"] == pytest.approx(2) and controller.month()["common_b"] == pytest.approx(1)
    assert controller.totals["cons_a"] == pytest.approx(5) and controller.totals["cons_b"] == pytest.approx(3)
    month = hass.states.get(_entity(hass, "energy_settlement_month", entry))
    assert month.attributes["common_kwh"] == pytest.approx(2) and month.attributes["common_kwh_b"] == pytest.approx(1)


async def test_common_meter_wins_over_power_and_key_by_area(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set("sensor.common", "10")
    entry, controller = await _setup(
        hass, common_meter="sensor.common", common_power=5000.0, common_key="area",
        area_a=100.0, area_b=50.0)
    freezer.tick(timedelta(hours=1))
    hass.states.async_set("sensor.common", "12")                # 2 kWh laut Zähler
    _set(hass, grid=8, a=6, b=2)
    await _tick(hass, freezer)
    assert controller.month()["common"] == pytest.approx(2)
    assert controller.month()["common_b"] == pytest.approx(2 * 50 / 150)
    hass.states.async_set("sensor.common", "unavailable")      # Zähler unklar: Zeitraum wächst weiter
    _set(hass, grid=16, a=12, b=4)
    before = dict(controller.totals)
    await _tick(hass, freezer)
    assert controller.totals == before


def test_common_references() -> None:
    entry = make_entry(domain=DOMAIN, title="Haus", data={**BASE, "common_meter": "sensor.common"})
    entities, _ = collect_references(entry.sub)
    assert "sensor.common" in set(entities)
