"""Coin-selection simulator that compares a few didactic strategies.

This is not a wallet. It exists to help users reason about how different
strategies change the resulting fee, change, and number of inputs for a
given UTXO pool and target set. We share script-type and vsize helpers
with the parser so results line up with the analyzed PSBT.
"""

from __future__ import annotations

from .models import UTXO, CoinSimRequest, CoinSimResponse, CoinSimResult, PaymentTarget
from .scripts import (
    ScriptType,
    estimate_tx_vsize,
    input_vsize,
    output_size,
)


def _targets_total(targets: list[PaymentTarget]) -> int:
    return sum(t.value_sats for t in targets)


def _tx_vsize(
    in_types: list[ScriptType],
    out_types: list[ScriptType],
    has_change: bool,
    change_type: ScriptType,
) -> float:
    outs = list(out_types)
    if has_change:
        outs.append(change_type)
    return estimate_tx_vsize(in_types, outs)


def _attempt_build(
    selected: list[UTXO],
    targets: list[PaymentTarget],
    fee_rate: float,
    change_type: ScriptType,
    dust: int,
) -> dict | None:
    """Given a candidate UTXO set, compute fee + change (or signal failure)."""
    in_sats = sum(u.value_sats for u in selected)
    out_sats = _targets_total(targets)
    in_types = [u.script_type for u in selected]
    out_types = [t.script_type for t in targets]

    vsize_no_change = _tx_vsize(in_types, out_types, False, change_type)
    fee_no_change = vsize_no_change * fee_rate
    leftover = in_sats - out_sats - fee_no_change
    if leftover < 0:
        return None

    vsize_with_change = _tx_vsize(in_types, out_types, True, change_type)
    fee_with_change = vsize_with_change * fee_rate
    change = in_sats - out_sats - fee_with_change

    if change <= dust:
        # Drop change into fees: no change output.
        return {
            "has_change": False,
            "vsize": vsize_no_change,
            "fee": round(fee_no_change + max(leftover, 0)),
            "change": 0,
            "in_sats": in_sats,
            "out_sats": out_sats,
        }
    return {
        "has_change": True,
        "vsize": vsize_with_change,
        "fee": round(fee_with_change),
        "change": int(change),
        "in_sats": in_sats,
        "out_sats": out_sats,
    }


def _largest_first(
    utxos: list[UTXO],
    targets: list[PaymentTarget],
    fee_rate: float,
    change_type: ScriptType,
    dust: int,
) -> tuple[list[UTXO], dict | None]:
    pool = sorted(utxos, key=lambda u: -u.value_sats)
    return _greedy(pool, targets, fee_rate, change_type, dust)


def _smallest_first(
    utxos: list[UTXO],
    targets: list[PaymentTarget],
    fee_rate: float,
    change_type: ScriptType,
    dust: int,
) -> tuple[list[UTXO], dict | None]:
    pool = sorted(utxos, key=lambda u: u.value_sats)
    return _greedy(pool, targets, fee_rate, change_type, dust)


def _greedy(
    pool: list[UTXO],
    targets: list[PaymentTarget],
    fee_rate: float,
    change_type: ScriptType,
    dust: int,
) -> tuple[list[UTXO], dict | None]:
    selected: list[UTXO] = []
    for u in pool:
        selected.append(u)
        outcome = _attempt_build(selected, targets, fee_rate, change_type, dust)
        if outcome is not None:
            return selected, outcome
    return selected, None


def _branch_and_bound(
    utxos: list[UTXO],
    targets: list[PaymentTarget],
    fee_rate: float,
    change_type: ScriptType,
    dust: int,
) -> tuple[list[UTXO], dict | None]:
    """Simplified BnB: look for a subset whose value covers target+fee with
    minimal wasted change (within dust of exact). Falls back to largest-first."""
    target_value = _targets_total(targets)
    pool = sorted(utxos, key=lambda u: -u.value_sats)
    best: tuple[list[UTXO], dict] | None = None
    best_waste = float("inf")
    # Effective-value bound: input value minus its marginal fee at current rate.
    tried = 0
    MAX_TRIES = 100_000

    def _recurse(idx: int, chosen: list[UTXO]) -> None:
        nonlocal best, best_waste, tried
        tried += 1
        if tried > MAX_TRIES:
            return
        outcome = _attempt_build(chosen, targets, fee_rate, change_type, dust) if chosen else None
        if outcome is not None:
            waste = outcome["change"] if outcome["has_change"] else 0
            if waste < best_waste:
                best_waste = waste
                best = (list(chosen), outcome)
                if waste == 0:
                    return
        if idx >= len(pool):
            return
        remaining_sum = sum(u.value_sats for u in pool[idx:])
        current_sum = sum(u.value_sats for u in chosen)
        if current_sum + remaining_sum < target_value:
            return
        # Include
        chosen.append(pool[idx])
        _recurse(idx + 1, chosen)
        chosen.pop()
        # Skip
        _recurse(idx + 1, chosen)

    _recurse(0, [])
    if best is None:
        return _largest_first(utxos, targets, fee_rate, change_type, dust)
    return best


_STRATEGIES = {
    "largest_first": _largest_first,
    "smallest_first": _smallest_first,
    "branch_and_bound": _branch_and_bound,
}


def run_simulation(req: CoinSimRequest) -> CoinSimResponse:
    results: list[CoinSimResult] = []
    for name in req.strategies:
        fn = _STRATEGIES.get(name)
        if fn is None:
            results.append(
                CoinSimResult(strategy=name, ok=False, message=f"Unknown strategy: {name}")
            )
            continue
        selected, outcome = fn(
            req.utxos,
            req.targets,
            req.fee_rate_sat_vb,
            req.change_script_type,
            req.dust_threshold_sats,
        )
        if outcome is None:
            results.append(
                CoinSimResult(
                    strategy=name,
                    ok=False,
                    message="Insufficient funds for target + fee.",
                    selected_outpoints=[u.outpoint for u in selected],
                )
            )
            continue
        vsize = outcome["vsize"]
        fee = outcome["fee"]
        results.append(
            CoinSimResult(
                strategy=name,
                ok=True,
                selected_outpoints=[u.outpoint for u in selected],
                total_in_sats=outcome["in_sats"],
                total_out_sats=outcome["out_sats"],
                change_sats=outcome["change"],
                fee_sats=fee,
                vsize=vsize,
                fee_rate_sat_vb=round(fee / vsize, 3) if vsize else 0.0,
                num_inputs=len(selected),
                num_outputs=len(req.targets) + (1 if outcome["has_change"] else 0),
            )
        )

    ok_results = [r for r in results if r.ok]
    best = None
    if ok_results:
        # Prefer lowest fee, then fewest inputs.
        best_res = min(ok_results, key=lambda r: (r.fee_sats, r.num_inputs))
        best = best_res.strategy
    return CoinSimResponse(results=results, best_strategy=best)


def bootstrap_from_report(inputs: list, outputs: list) -> CoinSimRequest:
    """Build a pre-filled coin-sim request from a parsed PSBT report.

    Inputs become the starting UTXO pool (user may add more). Outputs become
    payment targets. If change is flagged we exclude it from the targets.
    """
    utxos: list[UTXO] = []
    for i in inputs:
        if i.value_sats is None:
            continue
        utxos.append(
            UTXO(
                outpoint=f"{i.txid}:{i.vout}",
                value_sats=i.value_sats,
                script_type=i.script_type,
                address=i.address,
            )
        )
    targets: list[PaymentTarget] = []
    for o in outputs:
        if getattr(o, "is_change_candidate", False):
            continue
        if o.script_type is ScriptType.OP_RETURN:
            continue
        targets.append(
            PaymentTarget(
                address=o.address,
                script_type=o.script_type,
                value_sats=o.value_sats,
            )
        )
    return CoinSimRequest(utxos=utxos, targets=targets)


__all__ = [
    "estimate_tx_vsize",
    "input_vsize",
    "output_size",
    "run_simulation",
    "bootstrap_from_report",
]
