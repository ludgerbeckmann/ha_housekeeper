"""Tests für die Funktion Stromkosten."""

from datetime import UTC, datetime, timedelta

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


def _state(hass, entity, state, **attrs):
    hass.states.async_set(entity, state, attrs)
    return hass.states.get(entity)


def test_fixed_power_kw(hass: HomeAssistant) -> None:
    on = _state(hass, "light.a", "on", brightness=128)
    assert ec.fixed_power_kw(on, 10) == pytest.approx(0.01)
    assert ec.fixed_power_kw(on, 10, scale=True) == pytest.approx(10 * 128 / 255 / 1000)
    assert ec.fixed_power_kw(_state(hass, "light.b", "on"), 10, scale=True) == pytest.approx(0.01)   # ohne Helligkeit
    assert ec.fixed_power_kw(_state(hass, "light.c", "off"), 10, standby_w=2) == pytest.approx(0.002)
    assert ec.fixed_power_kw(_state(hass, "media_player.x", "idle"), 50) == 0
    assert ec.fixed_power_kw(_state(hass, "media_player.x", "playing"), 50) == pytest.approx(0.05)
    assert ec.fixed_power_kw(_state(hass, "climate.k", "cool"), 800) == pytest.approx(0.8)
    assert ec.fixed_power_kw(_state(hass, "light.d", "unavailable"), 10) is None
    assert ec.fixed_power_kw(None, 10) is None


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
        fixed = {"standby_power": 0, "scale_brightness": False}
        price = {"price_unit": "eur"}
        for key, value in over.items():
            if value is None:
                source.pop(key, None)
                continue
            if key in ("name", "source_entity"):
                source[key] = value
            elif key in ("fixed_entity", "fixed_power", "standby_power", "scale_brightness"):
                fixed[key] = value
            elif key in ("history_from", "start_kwh", "start_cost"):
                continue
            else:
                price[key] = value
        history = {k: v for k, v in over.items() if k in ("history_from", "start_kwh", "start_cost") and v is not None}
        return {"source": source, "fixed": fixed, "price": price, "history": history}

    bad = await flow.async_configure(result["flow_id"], page())
    assert bad["errors"] == {"base": "no_price"}
    hass.states.async_set("sensor.temp", "5", {"unit_of_measurement": "°C"})
    bad = await flow.async_configure(bad["flow_id"], page(source_entity="sensor.temp", price_ct=30))
    assert bad["errors"] == {"base": "unsupported_unit"}
    bad = await flow.async_configure(bad["flow_id"], page(price_ct=30, fixed_entity="light.lampe"))
    assert bad["errors"] == {"base": "source_or_fixed"}
    bad = await flow.async_configure(bad["flow_id"], page(price_ct=30, source_entity=None))
    assert bad["errors"] == {"base": "source_or_fixed"}
    bad = await flow.async_configure(
        bad["flow_id"], page(price_ct=30, source_entity=None, fixed_entity="light.lampe"))
    assert bad["errors"] == {"base": "no_power"}
    bad = await flow.async_configure(bad["flow_id"], page(price_ct=30, history_from="2999-01-01"))
    assert bad["errors"] == {"base": "history_in_future"}
    bad = await flow.async_configure(
        bad["flow_id"], page(price_ct=30, source_entity=None, fixed_entity="light.lampe", fixed_power=5,
                             history_from="2026-01-01"))
    assert bad["errors"] == {"base": "history_needs_source"}
    ok = await flow.async_configure(bad["flow_id"], page(price_ct=30))
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["data"]["price_ct"] == 30 and "price_entity" not in ok["data"] and "name" not in ok["data"]

    entry, _ = await _setup(hass)
    result = await reconfigure(hass, entry)
    assert result["step_id"] == "ec_settings" and not is_menu(result)
    assert [str(k) for k in result["data_schema"].schema] == ["source", "fixed", "price", "history"]
    done = await flow.async_configure(
        result["flow_id"], page(name="Gesamt", price_ct=None, price_entity=PRICE, price_unit="ct"))
    assert done["reason"] == "reconfigure_successful"
    assert entry.options["price_entity"] == PRICE and entry.options["price_ct"] is None
    assert entry.title.endswith("Gesamt")


def test_references() -> None:
    entry = make_entry(domain=DOMAIN, title="G", data={**BASE, "price_entity": PRICE})
    entities, _ = collect_references(entry.sub)
    assert {SOURCE, PRICE} <= set(entities)


FIXED = {"function_type": "energy_cost", "name": "Lampe", "fixed_entity": "light.lampe",
         "fixed_power": 10.0, "standby_power": 1.0, "price_ct": 30.0}


async def test_fixed_power_follows_the_entity_state(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set("light.lampe", "on")
    entry = make_entry(domain=DOMAIN, title="Lampe", data=FIXED)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    ctrl = hass.data[DOMAIN][entry.entry_id]
    await _advance(hass, freezer, 60)                       # 1 Stunde an: 10 W = 0,01 kWh
    assert ctrl.total_kwh == pytest.approx(0.01, abs=0.0003)
    hass.states.async_set("light.lampe", "off")             # danach Standby: 1 W
    await _advance(hass, freezer, 60)
    assert ctrl.total_kwh == pytest.approx(0.011, abs=0.0004)
    assert ctrl.total_cost == pytest.approx(0.011 * 0.30, abs=0.0002)
    hass.states.async_set("light.lampe", "unavailable")     # unbekannt: nichts zählen
    before = ctrl.total_kwh
    await _advance(hass, freezer, 10)
    assert ctrl.total_kwh == before


async def test_fixed_power_scales_with_brightness(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set("light.lampe", "on", {"brightness": 128})
    entry = make_entry(domain=DOMAIN, title="Lampe", data={**FIXED, "scale_brightness": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    ctrl = hass.data[DOMAIN][entry.entry_id]
    await _advance(hass, freezer, 60)
    assert ctrl.total_kwh == pytest.approx(0.01 * 128 / 255, abs=0.0003)


def test_fixed_entity_is_a_reference() -> None:
    entry = make_entry(domain=DOMAIN, title="Lampe", data=FIXED)
    entities, _ = collect_references(entry.sub)
    assert "light.lampe" in set(entities)


def _row(start, **values):
    return {"start": start, **values}


def test_build_history_groups_by_local_day_and_carries_prices() -> None:
    day1 = datetime(2026, 10, 1, 10, tzinfo=UTC).timestamp()
    day1b = datetime(2026, 10, 1, 11, tzinfo=UTC).timestamp()
    day2 = datetime(2026, 10, 2, 10, tzinfo=UTC).timestamp()
    days = ec.build_history(
        [(day1, 1.0), (day1b, 2.0), (day2, 4.0), (day2 + 3600, 0.0)],
        {day1: 0.30, day2: 0.40}, default_price=0.20)
    assert days["2026-10-01"]["kwh"] == 3.0 and days["2026-10-01"]["cost"] == pytest.approx(0.3 + 0.6)   # Preis wird weitergetragen
    assert days["2026-10-02"] == {"kwh": 4.0, "cost": pytest.approx(1.6)}
    assert ec.build_history([(day1, 1.0)], {}, None)["2026-10-01"]["cost"] == 0       # ohne Preis keine Kosten


async def test_start_values_are_added_to_the_totals(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set(SOURCE, "0", {"unit_of_measurement": "kWh"})
    entry, ctrl = await _setup(hass, start_kwh=100.0, start_cost=25.0)
    hass.states.async_set(SOURCE, "1", {"unit_of_measurement": "kWh"})
    await _advance(hass, freezer, 1)
    assert ctrl.total_kwh == pytest.approx(101) and ctrl.total_cost == pytest.approx(25.3)
    assert float(hass.states.get(_entity(hass, "cost_energy", entry)).state) == pytest.approx(101)
    assert float(hass.states.get(_entity(hass, "cost_total", entry)).state) == pytest.approx(25.3)
    assert ctrl.period("today")["kwh"] == pytest.approx(1)                # Tag, Monat, Jahr ohne Startwert


async def test_backfill_from_statistics(hass: HomeAssistant, freezer, monkeypatch) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-10 12:00:00+00:00")
    calls = []

    async def fake(hass_, start, end, statistic_id, types):
        calls.append((statistic_id, sorted(types), start, end))
        if statistic_id == PRICE:
            return [_row(datetime(2026, 10, 1, 0, tzinfo=UTC).timestamp(), mean=0.20)]
        return [_row(datetime(2026, 10, 1, h, tzinfo=UTC).timestamp(), mean=2.0) for h in range(2)] + [
            _row(datetime(2026, 10, 2, 0, tzinfo=UTC).timestamp(), mean=1.0)]

    monkeypatch.setattr(ec, "async_fetch_statistics", fake)
    hass.states.async_set(PRICE, "0.20")
    _power(hass, 1000)
    entry, ctrl = await _setup(hass, history_from="2026-10-01", price_entity=PRICE, price_unit="eur")
    await hass.async_block_till_done()
    assert [c[0] for c in calls] == [SOURCE, PRICE] and calls[0][1] == ["mean"]
    assert calls[0][3] == datetime(2026, 10, 10, 12, tzinfo=UTC)         # bis zum Beginn der Zählung (volle Stunde)
    assert ctrl.history["2026-10-01"] == {"kwh": 4.0, "cost": pytest.approx(0.8)}
    assert ctrl.total_kwh == pytest.approx(5.0) and ctrl.total_cost == pytest.approx(1.0)
    assert ctrl.period("year")["kwh"] == pytest.approx(5.0)               # fließt in Monat und Jahr ein
    assert ctrl.history_done == "2026-10-01"
    # dasselbe Datum rechnet nicht erneut, ein anderes ersetzt die Rückrechnung
    await ctrl.async_backfill()
    assert len(calls) == 2


async def test_backfill_energy_meter_uses_change(hass: HomeAssistant, freezer, monkeypatch) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-10 12:00:00+00:00")

    async def fake(hass_, start, end, statistic_id, types):
        assert types == {"change"}
        return [_row(datetime(2026, 10, 3, 8, tzinfo=UTC).timestamp(), change=1.5, mean=None)]

    monkeypatch.setattr(ec, "async_fetch_statistics", fake)
    hass.states.async_set(SOURCE, "10", {"unit_of_measurement": "kWh"})
    _, ctrl = await _setup(hass, history_from="2026-10-01")
    await hass.async_block_till_done()
    assert ctrl.history["2026-10-03"] == {"kwh": 1.5, "cost": pytest.approx(0.45)}      # fester Preis 30 ct


async def test_backfill_failure_is_logged_not_raised(hass: HomeAssistant, freezer, monkeypatch) -> None:
    async def broken(*args, **kwargs):
        raise RuntimeError("keine Statistik")

    monkeypatch.setattr(ec, "async_fetch_statistics", broken)
    _power(hass, 1000)
    _, ctrl = await _setup(hass, history_from="2026-10-01")
    await hass.async_block_till_done()
    assert ctrl.history == {} and ctrl.history_done is None
