import httpx
import pytest

from psbt_tool.core import fees as fees_mod


@pytest.fixture(autouse=True)
def _clear_cache():
    fees_mod.clear_cache()
    yield
    fees_mod.clear_cache()


def test_compare_below_min():
    cmp = fees_mod.compare_effective_fee(
        0.5, {"minimumFee": 1, "economyFee": 2, "hourFee": 5, "halfHourFee": 10, "fastestFee": 15}
    )
    assert cmp.bucket == "below_min"


def test_compare_over_fastest():
    cmp = fees_mod.compare_effective_fee(
        40.0, {"minimumFee": 1, "economyFee": 2, "hourFee": 5, "halfHourFee": 10, "fastestFee": 15}
    )
    assert cmp.bucket == "over_fastest"
    assert cmp.percent_vs_half_hour and cmp.percent_vs_half_hour > 0


def test_compare_half_hour_bucket():
    cmp = fees_mod.compare_effective_fee(
        12.0, {"minimumFee": 1, "economyFee": 2, "hourFee": 5, "halfHourFee": 10, "fastestFee": 15}
    )
    assert cmp.bucket == "half_hour"


async def test_fetch_recommended_fees_uses_cache(monkeypatch):
    calls = {"n": 0}
    payload = {
        "fastestFee": 20,
        "halfHourFee": 15,
        "hourFee": 10,
        "economyFee": 3,
        "minimumFee": 1,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.path.endswith("/v1/fees/recommended")
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        first = await fees_mod.fetch_recommended_fees(client=client, base_url="https://example.test/api")
        second = await fees_mod.fetch_recommended_fees(client=client, base_url="https://example.test/api")

    assert first == payload
    assert second == payload
    assert calls["n"] == 1  # cached on the second call
