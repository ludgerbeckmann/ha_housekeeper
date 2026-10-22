"""Tests für die Funktion Stromkosten."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .helpers import is_menu, make_entry, new_instance, reconfigure
from custom_components.ha_housekeeper import energy_cost as ec
from custom_components.ha_housekeeper.const import DOMAIN
from custom_components.ha_housekeeper.issues import collect_references

SOURCE = "sensor.steckdose_power"
PRICE = "sensor.strompreis"
BASE = {"function_type": "energy_cost", "name": "Gefrierschrank", "source_entity": SOURCE, "price_ct": 30.0}


def _power(hass, value, unit="W"):
    hass.states.async_set(SOURCE, str(value), {"unit_of_measurement": unit})


async def _setup(hass: HomeAssistant, **over):
    entry = make_entry(domain=DOMAIN, title="Gefrierschrank", data={**BASE, **over})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


async def _jump(hass, freezer, minutes):
    """Eine Zeitspanne auf einmal überspringen (ein einziger Takt)."""
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _advance(hass, freezer, minutes):
    """Minute für Minute vorrücken wie im Betrieb."""
    for _ in range(minutes):
        await _jump(hass, freezer, 1)


def _entity(hass, key, entry):
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")


def test_pure_helpers() -> None:
    assert ec.source_kind("W") == "power" and ec.source_kind("kWh") == "energy" and ec.source_kind("°C") is None
    assert ec.price_per_kwh(34, "ct") == pytest.approx(0.34) and ec.price_per_kwh(0.34, "eur") == 0.34
    assert ec.power_energy(1.0, 3.0, 0.5) == 1.0 and ec.power_energy(-1.0, -1.0, 1) == 0.0
    days: dict = {}
    ec.add_day(days, "2026-10-31", 1.0, 0.3)
    ec.add_day(days, "2026-11-01", 2.0, 0.6)
    ec.add_day(days, "2026-11-01", 1.0, 0.3)
    assert ec.sum_days(days, "2026-11-01") == {"kwh": 3.0, "cost": pytest.approx(0.9)}
    assert ec.sum_days(days, "2026-11")["kwh"] == 3.0 and ec.sum_days(days, "2026")["kwh"] == 4.0


async def test_power_sensor_is_integrated(hass: HomeAssistant, freezer) -> None:
    _power(hass, 1000)
    entry, ctrl = await _setup(hass)
    await _advance(hass, freezer, 30)                       # 1 kW über 30 Minuten
    assert ctrl.total_kwh == pytest.approx(0.5, abs=0.01)
    assert ctrl.total_cost == pytest.approx(0.15, abs=0.005)    # 30 ct/kWh
    assert float(hass.states.get(_entity(hass, "cost_energy", entry)).state) == pytest.approx(0.5, abs=0.01)
    today = hass.states.get(_entity(hass, "cost_today", entry))
    assert float(today.state) == pytest.approx(0.15, abs=0.005) and today.attributes["kwh"] == pytest.approx(0.5, abs=0.01)
    _power(hass, 2, "kW")                                   # kW wird umgerechnet
    await _advance(hass, freezer, 30)
    assert ctrl.total_kwh == pytest.approx(0.5 + 2 * 0.5, abs=0.03)             # danach 2 kW über 30 Minuten


async def test_gaps_and_unavailable_are_not_counted(hass: HomeAssistant, freezer) -> None:
    _power(hass, 1000)
    _, ctrl = await _setup(hass)
    hass.states.async_set(SOURCE, "unavailable", {"unit_of_measurement": "W"})
    await _advance(hass, freezer, 10)
    assert ctrl.total_kwh == 0
    _power(hass, 1000)
    await _advance(hass, freezer, 1)
    before = ctrl.total_kwh
    await _jump(hass, freezer, 60)                          # länger als MAX_GAP: nicht aufgerechnet
    assert ctrl.total_kwh == before
    hass.states.async_set(SOURCE, "5", {"unit_of_measurement": "°C"})
    before = ctrl.total_kwh
    await _advance(hass, freezer, 5)
    assert ctrl.total_kwh == before                         # falsche Einheit zählt nicht


async def test_energy_meter_difference_and_reset(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set(SOURCE, "100", {"unit_of_measurement": "kWh"})
    _, ctrl = await _setup(hass)
    hass.states.async_set(SOURCE, "102500", {"unit_of_measurement": "Wh"})     # 102,5 kWh: +2,5 kWh
    await _advance(hass, freezer, 1)
    assert ctrl.total_kwh == pytest.approx(2.5) and ctrl.total_cost == pytest.approx(0.75)
    hass.states.async_set(SOURCE, "3", {"unit_of_measurement": "kWh"})         # Zähler zurückgesetzt
    await _advance(hass, freezer, 1)
    assert ctrl.total_kwh == pytest.approx(2.5)
    hass.states.async_set(SOURCE, "4", {"unit_of_measurement": "kWh"})
    await _advance(hass, freezer, 1)
    assert ctrl.total_kwh == pytest.approx(3.5)


async def test_price_entity_replaces_fixed_price_and_keeps_last_value(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set(PRICE, "0.20")
    hass.states.async_set(SOURCE, "0", {"unit_of_measurement": "kWh"})
    _, ctrl = await _setup(hass, price_entity=PRICE, price_unit="eur")
    hass.states.async_set(SOURCE, "1", {"unit_of_measurement": "kWh"})
    await _advance(hass, freezer, 1)
    assert ctrl.total_cost == pytest.approx(0.20)
    hass.states.async_set(PRICE, "unavailable")              # letzter gültiger Preis gilt weiter
    hass.states.async_set(SOURCE, "2", {"unit_of_measurement": "kWh"})
    await _advance(hass, freezer, 1)
    assert ctrl.total_cost == pytest.approx(0.40)
    hass.states.async_set(PRICE, "40")                       # ct/kWh nach Umstellen der Einheit
    ctrl._get = lambda key, default=None: {**BASE, "price_entity": PRICE, "price_unit": "ct"}.get(key, default)
    hass.states.async_set(SOURCE, "3", {"unit_of_measurement": "kWh"})
    await _advance(hass, freezer, 1)
    assert ctrl.total_cost == pytest.approx(0.80)


async def test_no_price_still_counts_energy(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set(SOURCE, "0", {"unit_of_measurement": "kWh"})
    _, ctrl = await _setup(hass, price_ct=None)
    hass.states.async_set(SOURCE, "1", {"unit_of_measurement": "kWh"})
    await _advance(hass, freezer, 1)
    assert ctrl.total_kwh == 1 and ctrl.total_cost == 0


async def test_periods_and_restore(hass: HomeAssistant, freezer, hass_storage) -> None:
    freezer.move_to("2026-10-31 12:00:00+00:00")
    hass.states.async_set(SOURCE, "0", {"unit_of_measurement": "kWh"})
    entry, ctrl = await _setup(hass)
    hass.states.async_set(SOURCE, "2", {"unit_of_measurement": "kWh"})
    await _advance(hass, freezer, 1)
    freezer.move_to("2026-11-02 12:00:00+00:00")
    hass.states.async_set(SOURCE, "5", {"unit_of_measurement": "kWh"})
    await _advance(hass, freezer, 1)
    assert ctrl.period("today")["kwh"] == pytest.approx(3) and ctrl.period("month")["kwh"] == pytest.approx(3)
    assert ctrl.period("year")["kwh"] == pytest.approx(5)
    await ctrl._store.async_save(ctrl._data())              # wie beim Beenden geschrieben
    assert await hass.config_entries.async_reload(entry.hub_id)
    await hass.async_block_till_done()
    restored = hass.data[DOMAIN][entry.entry_id]
    assert restored.total_kwh == pytest.approx(5) and restored.energy_baseline == pytest.approx(5)


async def test_config_flow_and_settings_page(hass: HomeAssistant) -> None:
    result = await new_instance(hass, "energy_cost")
    assert result["step_id"] == "new_energy_cost"
    flow = hass.config_entries.subentries
    hass.states.async_set(SOURCE, "5", {"unit_of_measurement": "W"})

    def page(**over):
        source = {"name": "Kühlschrank", "source_entity": SOURCE}
        price = {"price_unit": "eur"}
        for key, value in over.items():
            if value is not None:
                (source if key in ("name", "source_entity") else price)[key] = value
        return {"source": source, "price": price}

    bad = await flow.async_configure(result["flow_id"], page())
    assert bad["errors"] == {"base": "no_price"}
    hass.states.async_set("sensor.temp", "5", {"unit_of_measurement": "°C"})
    bad = await flow.async_configure(bad["flow_id"], page(source_entity="sensor.temp", price_ct=30))
    assert bad["errors"] == {"base": "unsupported_unit"}
    ok = await flow.async_configure(bad["flow_id"], page(price_ct=30))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["price_ct"] == 30 and "price_entity" not in ok["data"] and "name" not in ok["data"]

    entry, _ = await _setup(hass)
    result = await reconfigure(hass, entry)
    assert result["step_id"] == "ec_settings" and not is_menu(result)
    assert [str(k) for k in result["data_schema"].schema] == ["source", "price"]
    done = await flow.async_configure(
        result["flow_id"], page(name="Gesamt", price_ct=None, price_entity=PRICE, price_unit="ct"))
    assert done["reason"] == "reconfigure_successful"
    assert entry.options["price_entity"] == PRICE and entry.options["price_ct"] is None
    assert entry.title.endswith("Gesamt")


def test_references() -> None:
    entry = make_entry(domain=DOMAIN, title="G", data={**BASE, "price_entity": PRICE})
    entities, _ = collect_references(entry.sub)
    assert {SOURCE, PRICE} <= set(entities)
