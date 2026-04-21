import pytest
from fastapi.testclient import TestClient

from psbt_tool.api.main import create_app
from psbt_tool.core import fees as fees_mod

from .fixtures import P2WPKH_2, segwit_two_output_psbt


@pytest.fixture
def client(monkeypatch):
    async def fake_fetch(*args, **kwargs):
        return {
            "fastestFee": 20,
            "halfHourFee": 15,
            "hourFee": 10,
            "economyFee": 3,
            "minimumFee": 1,
        }

    monkeypatch.setattr(fees_mod, "fetch_recommended_fees", fake_fetch)
    fees_mod.clear_cache()
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_analyze_json(client):
    b64 = segwit_two_output_psbt()
    res = client.post("/api/psbt/analyze", json={"psbt_base64": b64})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["psbt_version"] in (0, 2)
    assert data["fees"]["fee_sats"] == 2_068
    assert data["fee_comparison"]["bucket"] is not None


def test_analyze_invalid_psbt_400(client):
    res = client.post("/api/psbt/analyze", json={"psbt_base64": "not-a-psbt"})
    assert res.status_code == 400


def test_apply_drop_output_and_reanalyze(client):
    b64 = segwit_two_output_psbt()
    res = client.post(
        "/api/psbt/apply",
        json={
            "psbt_base64": b64,
            "ops": [{"op": "drop_output", "output_index": 0}],
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data["report"]["outputs"]) == 1
    assert data["psbt_base64"] != b64


def test_coin_sim_bootstrap(client):
    b64 = segwit_two_output_psbt()
    res = client.post("/api/coin-sim/bootstrap", json={"psbt_base64": b64})
    assert res.status_code == 200, res.text
    req = res.json()
    assert len(req["utxos"]) == 1
    assert len(req["targets"]) == 1


def test_coin_sim_run(client):
    body = {
        "utxos": [
            {"outpoint": "aa:0", "value_sats": 50_000, "script_type": "P2WPKH"},
            {"outpoint": "bb:0", "value_sats": 300_000, "script_type": "P2WPKH"},
        ],
        "targets": [
            {"address": P2WPKH_2, "script_type": "P2WPKH", "value_sats": 100_000}
        ],
        "change_script_type": "P2WPKH",
        "fee_rate_sat_vb": 2.0,
    }
    res = client.post("/api/coin-sim/run", json=body)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["best_strategy"] is not None
