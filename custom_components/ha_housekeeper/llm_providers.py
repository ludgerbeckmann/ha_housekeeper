"""Abfrage der Kosten bei LLM-Anbietern (Anthropic, OpenAI) und Auswertung der Antworten.

Beide Anbieter liefern nur die **Kosten je Tag** (UTC), kein Guthaben. Das Restguthaben berechnet
die Funktion selbst (`llm_usage.py`). Abgefragt wird mit einem Admin-Key der Organisation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

import aiohttp

from .const import PROVIDER_ANTHROPIC, PROVIDER_OPENAI

TIMEOUT = aiohttp.ClientTimeout(total=30)
PAGE_SIZE = 31
MAX_PAGES = 24  # rund zwei Jahre; mehr bedeutet, dass der Abgleich viel zu lange zurückliegt

ANTHROPIC_URL = "https://api.anthropic.com/v1/organizations/cost_report"
OPENAI_URL = "https://api.openai.com/v1/organization/costs"
ANTHROPIC_USAGE_URL = "https://api.anthropic.com/v1/organizations/usage_report/messages"
OPENAI_USAGE_URL = "https://api.openai.com/v1/organization/usage/completions"


class ProviderError(Exception):
    """Die Abfrage ist fehlgeschlagen (Netzwerk, Serverfehler, unerwartete Antwort)."""


class ProviderAuthError(ProviderError):
    """Der API-Key wurde abgelehnt (401/403)."""


def parse_anthropic(page: dict[str, Any]) -> tuple[str, dict[str, float]]:
    """Kosten je Tag aus einer Seite des Anthropic-Kostenberichts.

    `amount` steht in der kleinsten Währungseinheit (Cent) als Dezimalstring."""
    days: dict[str, float] = {}
    currency = "USD"
    for bucket in page.get("data") or []:
        day = str(bucket["starting_at"])[:10]
        total = 0.0
        for result in bucket.get("results") or []:
            total += float(result["amount"]) / 100
            currency = str(result.get("currency") or currency).upper()
        days[day] = days.get(day, 0.0) + total
    return currency, days


def parse_openai(page: dict[str, Any]) -> tuple[str, dict[str, float]]:
    """Kosten je Tag aus einer Seite der OpenAI-Costs-API (`amount.value` in der Währung)."""
    days: dict[str, float] = {}
    currency = "USD"
    for bucket in page.get("data") or []:
        day = datetime.fromtimestamp(int(bucket["start_time"]), UTC).date().isoformat()
        total = 0.0
        for result in bucket.get("results") or []:
            amount = result.get("amount") or {}
            total += float(amount.get("value") or 0)
            currency = str(amount.get("currency") or currency).upper()
        days[day] = days.get(day, 0.0) + total
    return currency, days


def parse_anthropic_usage(page: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Tokens je Tag aus dem Anthropic-Nutzungsbericht (keine Anfragenzahl).

    Eingabe = nicht zwischengespeicherte + Cache-Schreib- + Cache-Lese-Tokens."""
    days: dict[str, dict[str, Any]] = {}
    for bucket in page.get("data") or []:
        day = str(bucket["starting_at"])[:10]
        total = {"input": 0, "output": 0, "cached": 0, "requests": None}
        for result in bucket.get("results") or []:
            creation = result.get("cache_creation") or {}
            cache_read = int(result.get("cache_read_input_tokens") or 0)
            total["input"] += (
                int(result.get("uncached_input_tokens") or 0)
                + int(creation.get("ephemeral_1h_input_tokens") or 0)
                + int(creation.get("ephemeral_5m_input_tokens") or 0)
                + cache_read
            )
            total["output"] += int(result.get("output_tokens") or 0)
            total["cached"] += cache_read
        days[day] = _add_usage(days.get(day), total)
    return "", days


def parse_openai_usage(page: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Tokens und Anfragen je Tag aus dem OpenAI-Nutzungsbericht (Completions); die Eingabe
    enthält die zwischengespeicherten Tokens bereits."""
    days: dict[str, dict[str, Any]] = {}
    for bucket in page.get("data") or []:
        day = datetime.fromtimestamp(int(bucket["start_time"]), UTC).date().isoformat()
        total = {"input": 0, "output": 0, "cached": 0, "requests": 0}
        for result in bucket.get("results") or []:
            total["input"] += int(result.get("input_tokens") or 0)
            total["output"] += int(result.get("output_tokens") or 0)
            total["cached"] += int(result.get("input_cached_tokens") or 0)
            total["requests"] += int(result.get("num_model_requests") or 0)
        days[day] = _add_usage(days.get(day), total)
    return "", days


async def _get(
    session: aiohttp.ClientSession, url: str, headers: dict[str, str], params: dict[str, Any]
) -> dict[str, Any]:
    try:
        async with session.get(url, headers=headers, params=params, timeout=TIMEOUT) as response:
            if response.status in (401, 403):
                raise ProviderAuthError(f"HTTP {response.status}")
            if response.status != 200:
                raise ProviderError(f"HTTP {response.status}")
            data = await response.json()
    except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError) as err:
        raise ProviderError(str(err) or type(err).__name__) from err
    if not isinstance(data, dict):
        raise ProviderError("unerwartete Antwort")
    return data


async def _collect(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    parse: Any,
    merge: Any,
) -> tuple[str, dict[str, Any]]:
    """Alle Seiten eines Berichts abrufen und je Tag zusammenfassen."""
    days: dict[str, Any] = {}
    currency = "USD"
    for _ in range(MAX_PAGES):
        page = await _get(session, url, headers, params)
        try:
            currency, found = parse(page)
        except (KeyError, TypeError, ValueError) as err:
            raise ProviderError(f"unerwartete Antwort: {err}") from err
        for day, value in found.items():
            days[day] = merge(days.get(day), value)
        if not page.get("has_more") or not page.get("next_page"):
            return currency, days
        params = {**params, "page": page["next_page"]}
    raise ProviderError("zu viele Seiten (der Abgleich liegt zu lange zurück)")


def _add(old: float | None, new: float) -> float:
    return (old or 0.0) + new


def _request(provider: str, api_key: str, since: date, kind: str) -> tuple[Any, ...]:
    """URL, Kopfzeilen, Parameter und Auswertung für `costs` bzw. `usage` eines Anbieters."""
    if provider == PROVIDER_ANTHROPIC:
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        params: dict[str, Any] = {
            "starting_at": f"{since.isoformat()}T00:00:00Z",
            "limit": PAGE_SIZE,
        }
        if kind == "costs":
            return ANTHROPIC_URL, headers, params, parse_anthropic
        return ANTHROPIC_USAGE_URL, headers, {**params, "bucket_width": "1d"}, parse_anthropic_usage
    if provider == PROVIDER_OPENAI:
        headers = {"Authorization": f"Bearer {api_key}"}
        start = datetime(since.year, since.month, since.day, tzinfo=UTC)
        params = {"start_time": int(start.timestamp()), "bucket_width": "1d", "limit": PAGE_SIZE}
        if kind == "costs":
            return OPENAI_URL, headers, params, parse_openai
        return OPENAI_USAGE_URL, headers, params, parse_openai_usage
    raise ProviderError(f"unbekannter Anbieter: {provider}")


async def async_fetch_costs(
    session: aiohttp.ClientSession, provider: str, api_key: str, since: date
) -> tuple[str, dict[str, float]]:
    """Kosten je Tag (UTC) ab `since` bis heute: (Währung, {`YYYY-MM-DD`: Betrag})."""
    url, headers, params, parse = _request(provider, api_key, since, "costs")
    return await _collect(session, url, headers, params, parse, _add)


def _add_usage(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    if old is None:
        return dict(new)
    merged = {key: old[key] + new[key] for key in ("input", "output", "cached")}
    requests = [v for v in (old["requests"], new["requests"]) if v is not None]
    merged["requests"] = sum(requests) if requests else None
    return merged


async def async_fetch_usage(
    session: aiohttp.ClientSession, provider: str, api_key: str, since: date
) -> dict[str, dict[str, Any]]:
    """Tokens (und Anfragen) je Tag (UTC) ab `since`: {`YYYY-MM-DD`: {input, output, cached, requests}}."""
    url, headers, params, parse = _request(provider, api_key, since, "usage")
    _, days = await _collect(session, url, headers, params, parse, _add_usage)
    return days
