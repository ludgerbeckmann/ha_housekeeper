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


async def async_fetch_costs(
    session: aiohttp.ClientSession, provider: str, api_key: str, since: date
) -> tuple[str, dict[str, float]]:
    """Kosten je Tag (UTC) ab `since` bis heute: (Währung, {`YYYY-MM-DD`: Betrag})."""
    if provider == PROVIDER_ANTHROPIC:
        url, parse = ANTHROPIC_URL, parse_anthropic
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        params: dict[str, Any] = {
            "starting_at": f"{since.isoformat()}T00:00:00Z",
            "limit": PAGE_SIZE,
        }
    elif provider == PROVIDER_OPENAI:
        url, parse = OPENAI_URL, parse_openai
        headers = {"Authorization": f"Bearer {api_key}"}
        start = datetime(since.year, since.month, since.day, tzinfo=UTC)
        params = {"start_time": int(start.timestamp()), "bucket_width": "1d", "limit": PAGE_SIZE}
    else:
        raise ProviderError(f"unbekannter Anbieter: {provider}")

    days: dict[str, float] = {}
    currency = "USD"
    for _ in range(MAX_PAGES):
        page = await _get(session, url, headers, params)
        try:
            currency, found = parse(page)
        except (KeyError, TypeError, ValueError) as err:
            raise ProviderError(f"unerwartete Antwort: {err}") from err
        for day, amount in found.items():
            days[day] = days.get(day, 0.0) + amount
        if not page.get("has_more") or not page.get("next_page"):
            return currency, days
        params = {**params, "page": page["next_page"]}
    raise ProviderError("zu viele Seiten (der Abgleich liegt zu lange zurück)")
