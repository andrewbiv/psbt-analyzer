from psbt_tool.core.coin_sim import bootstrap_from_report, run_simulation
from psbt_tool.core.models import UTXO, CoinSimRequest, PaymentTarget
from psbt_tool.core.parser import analyze_psbt
from psbt_tool.core.scripts import ScriptType

from .fixtures import P2WPKH_2, segwit_two_output_psbt


def _pool() -> list[UTXO]:
    return [
        UTXO(outpoint=f"aa{i:02x}:0", value_sats=v, script_type=ScriptType.P2WPKH)
        for i, v in enumerate([20_000, 50_000, 70_000, 200_000])
    ]


def _target(value: int) -> PaymentTarget:
    return PaymentTarget(address=P2WPKH_2, script_type=ScriptType.P2WPKH, value_sats=value)


def test_largest_first_covers_target():
    req = CoinSimRequest(utxos=_pool(), targets=[_target(100_000)], fee_rate_sat_vb=2.0)
    res = run_simulation(req)
    names = {r.strategy for r in res.results if r.ok}
    assert "largest_first" in names
    lf = next(r for r in res.results if r.strategy == "largest_first")
    assert lf.num_inputs == 1
    assert lf.total_in_sats == 200_000
    assert lf.change_sats > 0


def test_smallest_first_uses_more_inputs():
    req = CoinSimRequest(utxos=_pool(), targets=[_target(100_000)], fee_rate_sat_vb=2.0)
    res = run_simulation(req)
    sf = next(r for r in res.results if r.strategy == "smallest_first")
    lf = next(r for r in res.results if r.strategy == "largest_first")
    assert sf.num_inputs >= lf.num_inputs


def test_insufficient_funds_reported():
    req = CoinSimRequest(
        utxos=[UTXO(outpoint="aa:0", value_sats=1_000, script_type=ScriptType.P2WPKH)],
        targets=[_target(100_000)],
        fee_rate_sat_vb=1.0,
        strategies=["largest_first"],
    )
    res = run_simulation(req)
    assert all(r.ok is False for r in res.results)


def test_bootstrap_from_psbt_report():
    from psbt_tool.core.heuristics import annotate_change

    _, report = analyze_psbt(psbt_base64=segwit_two_output_psbt())
    annotate_change(report)
    req = bootstrap_from_report(report.inputs, report.outputs)
    # One known input becomes a UTXO in the pool.
    assert len(req.utxos) == 1
    # Non-change payment output becomes a target. Change is excluded.
    assert len(req.targets) == 1
    assert req.targets[0].value_sats == 50_000
