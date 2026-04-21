"""Mempool fee client and fee reasonableness comparison."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import get_settings
from .models import MempoolFeeComparison


@dataclass
class _CacheEntry:
    expires_at: float
    value: dict[str, int]


_CACHE: dict[str, _CacheEntry] = {}


async def fetch_recommended_fees(
    client: httpx.AsyncClient | None = None,
    base_url: str | None = None,
) -> dict[str, int]:
    """Fetch mempool.space recommended fees. Cached for ``MEMPOOL_CACHE_TTL`` seconds."""
    settings = get_settings()
    url_base = (base_url or settings.mempool_base_url).rstrip("/")
    cache_key = url_base

    now = time.monotonic()
    entry = _CACHE.get(cache_key)
    if entry and entry.expires_at > now:
        return entry.value

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=10.0)

    try:
        resp = await client.get(f"{url_base}/v1/fees/recommended")
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    finally:
        if owns_client:
            await client.aclose()

    fees = {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}
    _CACHE[cache_key] = _CacheEntry(
        expires_at=now + max(settings.mempool_cache_ttl, 1),
        value=fees,
    )
    return fees


def clear_cache() -> None:
    _CACHE.clear()


def compare_effective_fee(
    effective_sat_vb: float | None, recommended: dict[str, int] | None
) -> MempoolFeeComparison:
    """Bucket the effective fee rate against mempool.space recommendations."""
    if effective_sat_vb is None or recommended is None:
        return MempoolFeeComparison(
            recommended=recommended,
            effective_sat_vb=effective_sat_vb,
            note="Fee rate not available; cannot compare.",
        )

    minimum = recommended.get("minimumFee", 1)
    economy = recommended.get("economyFee", minimum)
    hour = recommended.get("hourFee", economy)
    half_hour = recommended.get("halfHourFee", hour)
    fastest = recommended.get("fastestFee", half_hour)

    rate = effective_sat_vb
    if rate < minimum:
        bucket = "below_min"
        note = (
            f"Below mempool minimum ({minimum} sat/vB). This tx may not relay."
        )
    elif rate < economy:
        bucket = "min"
        note = "Between minimum and economy: likely very slow confirmation."
    elif rate < hour:
        bucket = "economy"
        note = "Economy range: hours to a day is typical."
    elif rate < half_hour:
        bucket = "hour"
        note = "About-an-hour target."
    elif rate < fastest:
        bucket = "half_hour"
        note = "About half-an-hour target."
    elif rate <= fastest * 1.25:
        bucket = "fastest"
        note = "Top-of-mempool: next-block target."
    else:
        bucket = "over_fastest"
        note = (
            f"{(rate / fastest - 1) * 100:.0f}% above next-block rate; you may be overpaying."
        )

    percent = None
    if half_hour:
        percent = round((rate / half_hour - 1) * 100, 2)

    return MempoolFeeComparison(
        recommended=recommended,
        effective_sat_vb=round(rate, 3),
        bucket=bucket,
        percent_vs_half_hour=percent,
        note=note,
    )
