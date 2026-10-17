"""Tests für die Funktion LLM-Verbrauch."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from .helpers import is_menu, make_entry, menu_options, new_instance, reconfigure, sectioned
from custom_components.ha_housekeeper import llm_providers as prov
from custom_components.ha_housekeeper import llm_usage as llm
from custom_components.ha_housekeeper.const import DOMAIN


def today() -> date:
    return dt_util.utcnow().date()


def iso(offset: int = 0) -> str:
    return (today() - timedelta(days=offset)).isoformat()


BASE = {
    "function_type": "llm_usage", "name": "Anthropic", "provider": "anthropic",
    "api_key": "sk-ant-admin-test", "mode": "balance", "amount": 50.0,
    "poll_minutes": 60, "low_balance": 10.0, "daily_limit": None, "monthly_limit": None,
    "mobile_enabled": True, "mobile_targets": ["mobile_app_phone"],
    "tts_enabled": False, "persistent_enabled": False,
}


def baseline_now() -> str:
    return dt_util.utcnow().isoformat()


def fake_costs(monkeypatch, days=None, currency="USD", error=None):
    """Abfrage der Anbieter ersetzen; liefert den AsyncMock zum Prüfen der Aufrufe."""
    mock = AsyncMock(side_effect=error, return_value=(currency, dict(days or {})))
    monkeypatch.setattr(prov, "async_fetch_costs", mock)
    return mock


async def _setup(hass, **over):
    push = async_mock_service(hass, "notify", "mobile_app_phone")
    data = {**BASE, "baseline_time": baseline_now(), **over}
    entry = make_entry(domain=DOMAIN, title="LLM-Verbrauch: Anthropic", data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.hub_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id], push


def messages(push):
    return [c.data["message"] for c in push if c.data["message"] != "clear_notification"]


# --- reine Funktionen ------------------------------------------------------------------------


def test_sums_and_averages() -> None:
    days = {iso(0): 1.0, iso(1): 2.0, iso(3): 4.0, iso(10): 100.0}
    assert llm.cost_today(days, today()) == 1.0
    assert llm.sum_days(days, today() - timedelta(days=3), today()) == 7.0
    # Durchschnitt der letzten 7 abgeschlossenen Tage (ohne heute): (2+4)/7
    assert llm.average_daily(days, today()) == pytest.approx(6 / 7)


def test_remaining_in_balance_mode() -> None:
    bday = today() - timedelta(days=2)
    days = {bday.isoformat(): 5.0, iso(1): 3.0, iso(0): 2.0}
    # 1 $ der 5 $ am Abgleichtag waren beim Abgleich schon abgezogen
    assert llm.remaining_balance("balance", 50, days, today(), bday, 4.0) == pytest.approx(50 - 1 - 3 - 2)
    assert llm.remaining_balance("balance", 50, days, today(), bday, None) is None
    assert llm.remaining_balance("balance", None, days, today(), bday, 4.0) is None


def test_remaining_in_budget_mode_uses_the_month() -> None:
    days = {today().isoformat(): 3.0, (today().replace(day=1) - timedelta(days=1)).isoformat(): 99.0}
    assert llm.remaining_balance("budget", 20, days, today(), None, None) == pytest.approx(17.0)


def test_days_left() -> None:
    assert llm.days_left(10.0, 2.0) == 5.0
    assert llm.days_left(-1.0, 2.0) == 0.0
    assert llm.days_left(10.0, 0.0) is None
    assert llm.days_left(None, 2.0) is None


# --- Anbieter ------------------------------------------------------------------------------------


def test_parse_anthropic_converts_cents() -> None:
    page = {"data": [
        {"starting_at": "2026-10-01T00:00:00Z", "results": [{"amount": "123.45", "currency": "USD"},
                                                              {"amount": "100", "currency": "USD"}]},
        {"starting_at": "2026-10-02T00:00:00Z", "results": []}]}
    currency, days = prov.parse_anthropic(page)
    assert currency == "USD"
    assert days == {"2026-10-01": pytest.approx(2.2345), "2026-10-02": 0.0}


def test_parse_openai_sums_line_items() -> None:
    start = int(datetime(2026, 10, 1, tzinfo=UTC).timestamp())
    page = {"data": [{"start_time": start, "end_time": start + 86400, "results": [
        {"amount": {"value": 0.06, "currency": "usd"}}, {"amount": {"value": 1.0, "currency": "usd"}}]}]}
    currency, days = prov.parse_openai(page)
    assert currency == "USD" and days == {"2026-10-01": pytest.approx(1.06)}


async def test_fetch_anthropic_with_paging(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    bucket = lambda day, cents: {"starting_at": f"{day}T00:00:00Z", "results": [{"amount": cents, "currency": "USD"}]}  # noqa: E731
    aioclient_mock.get(f"{prov.ANTHROPIC_URL}?page=p2", json={"data": [bucket("2026-10-02", "200")], "has_more": False})
    aioclient_mock.get(prov.ANTHROPIC_URL, json={
        "data": [bucket("2026-10-01", "100")], "has_more": True, "next_page": "p2"})
    currency, days = await prov.async_fetch_costs(
        async_get_clientsession(hass), "anthropic", "sk-ant-admin-x", date(2026, 10, 1))
    assert days == {"2026-10-01": pytest.approx(1.0), "2026-10-02": pytest.approx(2.0)}
    headers = aioclient_mock.mock_calls[0][3]
    assert headers["x-api-key"] == "sk-ant-admin-x" and headers["anthropic-version"]
    assert "starting_at=2026-10-01T00" in str(aioclient_mock.mock_calls[0][1])


async def test_fetch_openai(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    start = int(datetime(2026, 10, 1, tzinfo=UTC).timestamp())
    aioclient_mock.get(prov.OPENAI_URL, json={"data": [{"start_time": start, "results": [
        {"amount": {"value": 2.5, "currency": "usd"}}]}], "has_more": False})
    currency, days = await prov.async_fetch_costs(
        async_get_clientsession(hass), "openai", "sk-admin", date(2026, 10, 1))
    assert days == {"2026-10-01": 2.5}
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer sk-admin"
    assert f"start_time={start}" in str(aioclient_mock.mock_calls[0][1])


@pytest.mark.parametrize("status,error", [(401, prov.ProviderAuthError), (403, prov.ProviderAuthError),
                                          (500, prov.ProviderError)])
async def test_fetch_errors(hass: HomeAssistant, aioclient_mock, status, error) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    aioclient_mock.get(prov.ANTHROPIC_URL, status=status)
    with pytest.raises(error):
        await prov.async_fetch_costs(async_get_clientsession(hass), "anthropic", "k", today())


# --- Controller --------------------------------------------------------------------------------


async def test_refresh_computes_values(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(1): 4.0, iso(0): 2.0})
    _, ctrl, push = await _setup(hass)
    await ctrl.async_refresh()
    assert ctrl.cost_today == 2.0 and ctrl.cost_month >= 2.0
    # Abgleich war „jetzt“: der Stand von heute (2 $) ist im Guthaben schon abgezogen
    assert ctrl.remaining == pytest.approx(50.0)
    fake_costs(monkeypatch, {iso(1): 4.0, iso(0): 5.0})
    await ctrl.async_refresh()
    assert ctrl.remaining == pytest.approx(47.0)
    assert ctrl.days_left == pytest.approx(47.0 / (4.0 / 7))
    assert push == []


async def test_budget_mode(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 3.0})
    _, ctrl, _ = await _setup(hass, mode="budget", amount=20.0, baseline_time=None)
    await ctrl.async_refresh()
    assert ctrl.remaining == pytest.approx(17.0 - (ctrl.cost_month - 3.0))


async def test_second_refresh_only_loads_recent_days(hass: HomeAssistant, monkeypatch) -> None:
    mock = fake_costs(monkeypatch, {iso(0): 1.0})
    _, ctrl, _ = await _setup(hass)
    await ctrl.async_refresh()
    first = mock.await_args.args[3]
    await ctrl.async_refresh()
    second = mock.await_args.args[3]
    assert second > first                                  # nicht erneut die ganze Zeitspanne
    assert second == max(first, today() - timedelta(days=llm.RECHECK_DAYS))


async def test_low_balance_warns_once_and_clears(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 0.0})
    entry, ctrl, push = await _setup(hass)
    await ctrl.async_refresh()
    fake_costs(monkeypatch, {iso(0): 45.0})                # 50 - 45 = 5 < 10
    await ctrl.async_refresh()
    assert len(messages(push)) == 1 and "5.00" in messages(push)[0]
    assert ctrl.active_alerts == ["low"]
    await ctrl.async_refresh()
    assert len(messages(push)) == 1                        # nur einmal je Unterschreitung
    # Aufladen und abgleichen: wieder über der Grenze
    hass.config_entries.async_update_subentry(
        entry.hub, entry.subentry, data={**entry.subentry.data, "amount": 80.0,
                                         "baseline_time": baseline_now()})
    await hass.async_block_till_done()
    ctrl2 = hass.data[DOMAIN][entry.entry_id]
    await ctrl2.async_refresh()
    assert ctrl2.remaining == pytest.approx(80.0)
    assert ctrl2.active_alerts == []
    assert any("again" in m or "wieder" in m for m in messages(push)[1:]) or ctrl2.alerts["low"] is False


async def test_low_balance_recovery_message(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 0.0})
    _, ctrl, push = await _setup(hass)
    await ctrl.async_refresh()
    fake_costs(monkeypatch, {iso(0): 45.0})
    await ctrl.async_refresh()
    fake_costs(monkeypatch, {iso(0): 10.0})                # 40 über der Grenze
    await ctrl.async_refresh()
    assert ctrl.active_alerts == [] and len(messages(push)) == 2


async def test_daily_limit_warns_once_per_day(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 3.0})
    _, ctrl, push = await _setup(hass, low_balance=None, daily_limit=5.0)
    await ctrl.async_refresh()
    assert messages(push) == []
    fake_costs(monkeypatch, {iso(0): 6.0})
    await ctrl.async_refresh()
    await ctrl.async_refresh()
    assert len(messages(push)) == 1 and ctrl.active_alerts == ["daily"]
    ctrl.alerts["daily"] = iso(1)                          # gestern gewarnt: heute erneut
    await ctrl.async_refresh()
    assert len(messages(push)) == 2


async def test_monthly_limit(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 30.0})
    _, ctrl, push = await _setup(hass, low_balance=None, monthly_limit=25.0)
    await ctrl.async_refresh()
    await ctrl.async_refresh()
    assert len(messages(push)) == 1 and ctrl.active_alerts == ["monthly"]


async def test_failures_alert_after_three_then_recover(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, error=prov.ProviderError("HTTP 500"))
    _, ctrl, push = await _setup(hass)
    for _ in range(2):
        await ctrl.async_refresh()
    assert messages(push) == [] and ctrl.error == "HTTP 500"
    await ctrl.async_refresh()
    assert len(messages(push)) == 1 and ctrl.active_alerts == ["error"]
    await ctrl.async_refresh()
    assert len(messages(push)) == 1
    fake_costs(monkeypatch, {iso(0): 0.0})
    await ctrl.async_refresh()
    assert ctrl.active_alerts == [] and ctrl.error is None and len(messages(push)) == 2


async def test_invalid_key_alerts_immediately(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, error=prov.ProviderAuthError("HTTP 401"))
    _, ctrl, push = await _setup(hass)
    await ctrl.async_refresh()
    assert len(messages(push)) == 1 and "401" in messages(push)[0]


async def test_switch_off_pauses(hass: HomeAssistant, monkeypatch) -> None:
    mock = fake_costs(monkeypatch, {iso(0): 1.0})
    _, ctrl, _ = await _setup(hass)
    await ctrl.async_set_enabled(False)
    await ctrl.async_refresh()
    mock.assert_not_awaited()


async def test_state_survives_restart(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 0.0})
    entry, ctrl, push = await _setup(hass)
    await ctrl.async_refresh()
    fake_costs(monkeypatch, {iso(0): 45.0})
    await ctrl.async_refresh()
    await hass.config_entries.async_reload(entry.hub_id)
    await hass.async_block_till_done()
    ctrl2 = hass.data[DOMAIN][entry.entry_id]
    assert ctrl2.days == {iso(0): 45.0} and ctrl2.active_alerts == ["low"]


# --- Entitäten -------------------------------------------------------------------------------------


async def test_entities(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(1): 7.0, iso(0): 7.0})
    _, ctrl, _ = await _setup(hass)
    await ctrl.async_refresh()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    ids = {e.translation_key: e.entity_id for e in registry.entities.values() if e.platform == DOMAIN}
    assert set(ids) == {"llm_active", "llm_warning", "llm_remaining", "llm_cost_today",
                        "llm_cost_month", "llm_forecast", "llm_days_left", "llm_refresh"}
    assert float(hass.states.get(ids["llm_cost_today"]).state) == 7.0
    assert hass.states.get(ids["llm_cost_today"]).attributes["unit_of_measurement"] == "USD"
    assert hass.states.get(ids["llm_cost_today"]).attributes["state_class"] == "measurement"
    assert float(hass.states.get(ids["llm_remaining"]).state) == pytest.approx(50.0)
    assert hass.states.get(ids["llm_warning"]).state == "off"


async def test_refresh_button(hass: HomeAssistant, monkeypatch) -> None:
    mock = fake_costs(monkeypatch, {iso(0): 1.0})
    _, ctrl, _ = await _setup(hass)
    registry = er.async_get(hass)
    button = next(e.entity_id for e in registry.entities.values() if e.translation_key == "llm_refresh")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    mock.assert_awaited()


# --- Einstellungsdialoge -----------------------------------------------------------------------------


def new_form(**over):
    values = {"name": "", "provider": "anthropic", "api_key": "sk-ant-admin-x", "mode": "balance",
              "amount": 42.5, "poll_minutes": 60, "mobile_enabled": False,
              "persistent_enabled": True, "tts_enabled": False, **over}
    values = {k: v for k, v in values.items() if v not in ("", None)}
    return sectioned(values)


async def test_create_balance_instance(hass: HomeAssistant, monkeypatch) -> None:
    mock = fake_costs(monkeypatch, {})
    result = await new_instance(hass, "llm_usage")
    assert result["step_id"] == "new_llm_usage"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], new_form())
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "LLM usage"                        # leerer Name = Funktionsname
    data = result["data"]
    assert data["provider"] == "anthropic" and data["amount"] == 42.5
    assert data["mode"] == "balance" and dt_util.parse_datetime(data["baseline_time"])
    assert data["low_balance"] is None and "name" not in data
    mock.assert_awaited_once()                                   # Key wurde geprüft


async def test_create_budget_instance_has_no_baseline(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {})
    result = await new_instance(hass, "llm_usage")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], new_form(name="OpenAI", provider="openai", mode="budget", daily_limit=5))
    assert result["title"] == "LLM usage: OpenAI"
    assert "baseline_time" not in result["data"] and result["data"]["daily_limit"] == 5


@pytest.mark.parametrize("error,key", [(prov.ProviderAuthError("HTTP 401"), "invalid_auth"),
                                       (prov.ProviderError("HTTP 500"), "cannot_connect")])
async def test_create_checks_the_key(hass: HomeAssistant, monkeypatch, error, key) -> None:
    fake_costs(monkeypatch, error=error)
    result = await new_instance(hass, "llm_usage")
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], new_form())
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": key}


async def test_menu_depends_on_the_mode(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {})
    entry, _, _ = await _setup(hass)
    assert menu_options(await reconfigure(hass, entry)) == ["llm_general", "llm_calibrate", "rename"]


async def test_budget_mode_has_no_calibration(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {})
    entry, _, _ = await _setup(hass, mode="budget", baseline_time=None)
    assert menu_options(await reconfigure(hass, entry)) == ["llm_general", "rename"]


async def test_calibrate_sets_amount_and_time(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {})
    entry, _, _ = await _setup(hass, baseline_time="2026-01-01T00:00:00+00:00")
    menu = await reconfigure(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        menu["flow_id"], {"next_step_id": "llm_calibrate"})
    assert result["step_id"] == "llm_calibrate"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"amount": 99.5})
    assert is_menu(result)
    assert entry.options["amount"] == 99.5
    assert dt_util.parse_datetime(entry.options["baseline_time"]) > datetime(2026, 6, 1, tzinfo=UTC)


async def test_settings_keep_key_when_empty_and_clear_limits(hass: HomeAssistant, monkeypatch) -> None:
    mock = fake_costs(monkeypatch, {})
    entry, _, _ = await _setup(hass, daily_limit=5.0)
    menu = await reconfigure(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        menu["flow_id"], {"next_step_id": "llm_general"})
    assert result["step_id"] == "llm_general"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        sectioned({"poll_minutes": 30, "mobile_enabled": False, "persistent_enabled": True,
                   "tts_enabled": False}))
    assert is_menu(result)
    assert entry.options["api_key"] == "sk-ant-admin-test"          # unverändert
    assert entry.options["poll_minutes"] == 30
    assert entry.options["daily_limit"] is None and entry.options["low_balance"] is None
    mock.assert_not_awaited()


async def test_settings_new_key_is_checked(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, error=prov.ProviderAuthError("HTTP 401"))
    entry, _, _ = await _setup(hass)
    menu = await reconfigure(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        menu["flow_id"], {"next_step_id": "llm_general"})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        sectioned({"api_key": "bad", "poll_minutes": 60, "mobile_enabled": False,
                   "persistent_enabled": True, "tts_enabled": False}))
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.options["api_key"] == "sk-ant-admin-test"


async def test_diagnostics_redact_the_key() -> None:
    from custom_components.ha_housekeeper.diagnostics import TO_REDACT
    assert "api_key" in TO_REDACT


# --- Prognose ---------------------------------------------------------------------------------------


def test_forecast_month() -> None:
    day = date(2026, 10, 11)                                  # Oktober hat 31 Tage: 20 Tage nach heute
    days = {(day - timedelta(days=i)).isoformat(): 7.0 for i in range(1, 8)}   # 7 $/Tag, 7 Tage
    days[day.isoformat()] = 2.0
    days[date(2026, 10, 1).isoformat()] = 7.0
    month = llm.cost_month(days, day)
    # bisher + Rest von heute (7 - 2) + 20 Tage zu 7 $
    assert llm.forecast_month(days, day) == pytest.approx(month + 5.0 + 20 * 7.0)
    # heute schon über dem Durchschnitt: kein Abzug
    days[day.isoformat()] = 12.0
    assert llm.forecast_month(days, day) == pytest.approx(llm.cost_month(days, day) + 20 * 7.0)
    assert llm.forecast_month({}, day) == 0.0


async def test_forecast_warning_before_the_limit_is_hit(hass: HomeAssistant, monkeypatch) -> None:
    # 10 $/Tag in den letzten Tagen, heute noch nichts: Prognose über dem Limit, Kosten noch darunter
    days = {iso(i): 10.0 for i in range(1, 8)}
    days[iso(0)] = 0.0
    fake_costs(monkeypatch, days)
    limit = llm.cost_month(days, today()) + 5.0
    _, ctrl, push = await _setup(hass, low_balance=None, monthly_limit=limit)
    await ctrl.async_refresh()
    await ctrl.async_refresh()
    assert len(messages(push)) == 1
    assert "Prognose" in messages(push)[0] or "forecast" in messages(push)[0]
    assert ctrl.active_alerts == ["forecast"]


async def test_forecast_warning_can_be_switched_off(hass: HomeAssistant, monkeypatch) -> None:
    days = {iso(i): 10.0 for i in range(1, 8)}
    fake_costs(monkeypatch, days)
    _, ctrl, push = await _setup(hass, low_balance=None, monthly_limit=0.5 + 0.0,
                                 forecast_warning=False)
    await ctrl.async_refresh()
    assert not any("Prognose" in m or "forecast" in m for m in messages(push))
    assert "forecast" not in ctrl.active_alerts


async def test_forecast_uses_the_budget_in_budget_mode(hass: HomeAssistant, monkeypatch) -> None:
    days = {iso(i): 10.0 for i in range(1, 8)}
    days[iso(0)] = 0.0
    fake_costs(monkeypatch, days)
    _, ctrl, push = await _setup(
        hass, mode="budget", amount=ctrl_budget(days), baseline_time=None, low_balance=None)
    await ctrl.async_refresh()
    assert ctrl.active_alerts == ["forecast"] and len(messages(push)) == 1


def ctrl_budget(days) -> float:
    """Budget knapp über den bisherigen Monatskosten, aber unter der Prognose."""
    return llm.cost_month(days, today()) + 1.0


async def test_forecast_sensor(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 4.0})
    _, ctrl, _ = await _setup(hass)
    await ctrl.async_refresh()
    await hass.async_block_till_done()
    entity = next(e.entity_id for e in er.async_get(hass).entities.values()
                  if e.translation_key == "llm_forecast")
    assert float(hass.states.get(entity).state) == pytest.approx(ctrl.forecast, abs=1e-3)


# --- Tokens und Anfragen -----------------------------------------------------------------------------


def test_parse_anthropic_usage() -> None:
    page = {"data": [{"starting_at": "2026-10-01T00:00:00Z", "results": [{
        "uncached_input_tokens": 1500, "cache_read_input_tokens": 200, "output_tokens": 500,
        "cache_creation": {"ephemeral_1h_input_tokens": 100, "ephemeral_5m_input_tokens": 50}}]}]}
    _, days = prov.parse_anthropic_usage(page)
    assert days == {"2026-10-01": {"input": 1850, "output": 500, "cached": 200, "requests": None}}


def test_parse_openai_usage() -> None:
    start = int(datetime(2026, 10, 1, tzinfo=UTC).timestamp())
    page = {"data": [{"start_time": start, "results": [
        {"input_tokens": 1000, "output_tokens": 200, "input_cached_tokens": 300, "num_model_requests": 5},
        {"input_tokens": 10, "output_tokens": 20, "input_cached_tokens": 0, "num_model_requests": 1}]}]}
    _, days = prov.parse_openai_usage(page)
    assert days == {"2026-10-01": {"input": 1010, "output": 220, "cached": 300, "requests": 6}}


async def test_fetch_usage_anthropic(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    bucket = lambda day, out: {"starting_at": f"{day}T00:00:00Z", "results": [  # noqa: E731
        {"uncached_input_tokens": 10, "output_tokens": out}]}
    aioclient_mock.get(f"{prov.ANTHROPIC_USAGE_URL}?page=p2",
                       json={"data": [bucket("2026-10-02", 7)], "has_more": False})
    aioclient_mock.get(prov.ANTHROPIC_USAGE_URL, json={
        "data": [bucket("2026-10-01", 5)], "has_more": True, "next_page": "p2"})
    days = await prov.async_fetch_usage(
        async_get_clientsession(hass), "anthropic", "k", date(2026, 10, 1))
    assert days["2026-10-01"]["output"] == 5 and days["2026-10-02"]["output"] == 7
    assert "bucket_width=1d" in str(aioclient_mock.mock_calls[0][1])


async def test_fetch_usage_openai(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    start = int(datetime(2026, 10, 1, tzinfo=UTC).timestamp())
    aioclient_mock.get(prov.OPENAI_USAGE_URL, json={"data": [{"start_time": start, "results": [
        {"input_tokens": 9, "output_tokens": 1, "input_cached_tokens": 0, "num_model_requests": 2}]}],
        "has_more": False})
    days = await prov.async_fetch_usage(async_get_clientsession(hass), "openai", "k", date(2026, 10, 1))
    assert days == {"2026-10-01": {"input": 9, "output": 1, "cached": 0, "requests": 2}}


def fake_usage(monkeypatch, usage=None, error=None):
    mock = AsyncMock(side_effect=error, return_value=dict(usage or {}))
    monkeypatch.setattr(prov, "async_fetch_usage", mock)
    return mock


def usage_row(i=5, o=3, c=1, r=2):
    return {"input": i, "output": o, "cached": c, "requests": r}


async def test_usage_is_not_queried_by_default(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 1.0})
    usage = fake_usage(monkeypatch, {iso(0): usage_row()})
    _, ctrl, _ = await _setup(hass)
    await ctrl.async_refresh()
    usage.assert_not_awaited()
    ids = {e.translation_key for e in er.async_get(hass).entities.values() if e.platform == DOMAIN}
    assert not {"llm_tokens_today", "llm_tokens_month", "llm_requests_today"} & ids


async def test_usage_sensors_for_openai(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 1.0})
    month_first = today().replace(day=1).isoformat()
    fake_usage(monkeypatch, {iso(0): usage_row(10, 5, 2, 3), month_first: usage_row(100, 50, 20, 7)})
    _, ctrl, _ = await _setup(hass, provider="openai", track_usage=True)
    await ctrl.async_refresh()
    await hass.async_block_till_done()
    ids = {e.translation_key: e.entity_id for e in er.async_get(hass).entities.values()
           if e.platform == DOMAIN}
    for key in ("llm_tokens_today", "llm_tokens_month", "llm_requests_today", "llm_requests_month"):
        assert key in ids
    assert hass.states.get(ids["llm_tokens_today"]).state == "15"
    attrs = hass.states.get(ids["llm_tokens_today"]).attributes
    assert (attrs["input"], attrs["output"], attrs["cached_input"]) == (10, 5, 2)
    assert hass.states.get(ids["llm_requests_today"]).state == "3"
    if month_first != iso(0):
        assert hass.states.get(ids["llm_tokens_month"]).state == "165"
        assert hass.states.get(ids["llm_requests_month"]).state == "10"


async def test_anthropic_has_tokens_but_no_requests(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 1.0})
    fake_usage(monkeypatch, {iso(0): usage_row(4, 1, 0, None)})
    _, ctrl, _ = await _setup(hass, track_usage=True)
    await ctrl.async_refresh()
    ids = {e.translation_key for e in er.async_get(hass).entities.values() if e.platform == DOMAIN}
    assert {"llm_tokens_today", "llm_tokens_month"} <= ids
    assert not {"llm_requests_today", "llm_requests_month"} & ids


async def test_usage_error_does_not_break_the_costs(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 1.0})
    fake_usage(monkeypatch, error=prov.ProviderError("HTTP 500"))
    _, ctrl, push = await _setup(hass, track_usage=True)
    await ctrl.async_refresh()
    assert ctrl.cost_today == 1.0 and ctrl.error is None and ctrl.active_alerts == []
    assert ctrl.usage == {}


async def test_usage_entities_are_removed_when_switched_off(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {iso(0): 1.0})
    fake_usage(monkeypatch, {iso(0): usage_row()})
    entry, ctrl, _ = await _setup(hass, track_usage=True)
    await ctrl.async_refresh()
    registry = er.async_get(hass)
    assert any(e.translation_key == "llm_tokens_today" for e in registry.entities.values())
    hass.config_entries.async_update_subentry(
        entry.hub, entry.subentry, data={**entry.subentry.data, "track_usage": False})
    await hass.async_block_till_done()
    assert not any(e.translation_key == "llm_tokens_today" for e in registry.entities.values())


# --- Reparaturhinweis bei abgelehntem Key ------------------------------------------------------------


async def test_auth_failure_creates_a_repair_issue_that_clears(hass: HomeAssistant, monkeypatch) -> None:
    from homeassistant.helpers import issue_registry as ir
    from custom_components.ha_housekeeper.issues import async_check_entry
    fake_costs(monkeypatch, error=prov.ProviderAuthError("HTTP 401"))
    entry, ctrl, _ = await _setup(hass)
    await ctrl.async_refresh()
    issue_id = f"{entry.entry_id}_llm_auth"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_key == "llm_auth_failed"
    # die stündliche Prüfung der Referenzen darf den Hinweis nicht löschen
    await async_check_entry(hass, entry.sub)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    fake_costs(monkeypatch, {iso(0): 1.0})
    await ctrl.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_other_errors_create_no_issue(hass: HomeAssistant, monkeypatch) -> None:
    from homeassistant.helpers import issue_registry as ir
    fake_costs(monkeypatch, error=prov.ProviderError("HTTP 500"))
    entry, ctrl, _ = await _setup(hass)
    for _ in range(3):
        await ctrl.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}_llm_auth") is None


# --- Dialoge: neue Felder ----------------------------------------------------------------------------------


async def test_new_instance_stores_the_new_options(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, {})
    result = await new_instance(hass, "llm_usage")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], new_form(track_usage=True, forecast_warning=False, monthly_limit=30))
    assert result["data"]["track_usage"] is True and result["data"]["forecast_warning"] is False


# --- Fehlerdiagnose -------------------------------------------------------------------------------------


async def test_http_errors_carry_status_and_provider_message(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    aioclient_mock.get(prov.ANTHROPIC_URL, status=400, json={
        "type": "error", "error": {"type": "invalid_request_error", "message": "starting_at is bad"}})
    with pytest.raises(prov.ProviderError, match="HTTP 400: starting_at is bad") as err:
        await prov.async_fetch_costs(async_get_clientsession(hass), "anthropic", "k", today())
    assert not isinstance(err.value, prov.ProviderAuthError)


async def test_auth_errors_carry_the_provider_message(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    aioclient_mock.get(prov.ANTHROPIC_URL, status=401, json={
        "type": "error", "error": {"type": "authentication_error", "message": "API key is invalid."}})
    with pytest.raises(prov.ProviderAuthError, match="HTTP 401: API key is invalid."):
        await prov.async_fetch_costs(async_get_clientsession(hass), "anthropic", "k", today())


async def test_non_json_error_body_is_shortened(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    aioclient_mock.get(prov.OPENAI_URL, status=502, text="<html>" + "x" * 500 + "</html>")
    with pytest.raises(prov.ProviderError) as err:
        await prov.async_fetch_costs(async_get_clientsession(hass), "openai", "k", today())
    assert str(err.value).startswith("HTTP 502: <html>") and len(str(err.value)) < 230


async def test_connection_errors_name_the_cause(hass: HomeAssistant, aioclient_mock) -> None:
    import aiohttp
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    aioclient_mock.get(prov.ANTHROPIC_URL, exc=aiohttp.ClientConnectionError("Cannot connect to host"))
    with pytest.raises(prov.ProviderError, match="ClientConnectionError: Cannot connect to host"):
        await prov.async_fetch_costs(async_get_clientsession(hass), "anthropic", "k", today())


async def test_invalid_json_is_reported(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    aioclient_mock.get(prov.ANTHROPIC_URL, text="not json")
    with pytest.raises(prov.ProviderError, match="keine gültige JSON-Antwort"):
        await prov.async_fetch_costs(async_get_clientsession(hass), "anthropic", "k", today())


async def test_invalid_key_characters_are_explained() -> None:
    class Session:
        def get(self, *args, **kwargs):
            raise ValueError("Newline or carriage return character detected in HTTP status message or header")

    with pytest.raises(prov.ProviderError, match="ungültige Zeichen im Key"):
        await prov.async_fetch_costs(Session(), "anthropic", "k\nx", today())


async def test_create_shows_the_cause_and_strips_the_key(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, error=prov.ProviderError("HTTP 400: starting_at is bad"))
    result = await new_instance(hass, "llm_usage")
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], new_form())
    assert result["errors"] == {"base": "cannot_connect"}
    assert result["description_placeholders"] == {"detail": "HTTP 400: starting_at is bad"}

    mock = fake_costs(monkeypatch, {})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], new_form(api_key="  sk-ant-admin-x \n"))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["api_key"] == "sk-ant-admin-x"
    assert mock.await_args.args[2] == "sk-ant-admin-x"


async def test_auth_failure_shows_the_provider_message(hass: HomeAssistant, monkeypatch) -> None:
    fake_costs(monkeypatch, error=prov.ProviderAuthError("HTTP 403: not allowed"))
    result = await new_instance(hass, "llm_usage")
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], new_form())
    assert result["errors"] == {"base": "invalid_auth"}
    assert result["description_placeholders"] == {"detail": "HTTP 403: not allowed"}


async def test_stored_key_with_whitespace_is_stripped_for_queries(hass: HomeAssistant, monkeypatch) -> None:
    mock = fake_costs(monkeypatch, {iso(0): 1.0})
    _, ctrl, _ = await _setup(hass, api_key="  sk-ant-admin-test \n")
    await ctrl.async_refresh()
    assert mock.await_args.args[2] == "sk-ant-admin-test"
