"""Change-output heuristics applied on top of a parsed :class:`PSBTReport`.

These are heuristics only: they label each output with a change-likelihood
score and the reasons that contributed. We never mark something as definitely
change; the UI should reflect that uncertainty.
"""

from __future__ import annotations

from .models import OutputView, PSBTReport
from .scripts import ScriptType


def _is_round(value: int) -> bool:
    """A value is 'round' (likely a human payment) if it ends in several zeros."""
    if value <= 0:
        return False
    for zeros in (100_000_000, 10_000_000, 1_000_000, 100_000, 10_000, 1_000):
        if value % zeros == 0:
            return True
    return False


def annotate_change(report: PSBTReport) -> PSBTReport:
    """Mutate ``report.outputs`` in place with heuristic change scoring and return it."""
    input_types = {i.script_type for i in report.inputs}
    input_types.discard(ScriptType.UNKNOWN)

    n_outputs = len(report.outputs)
    values = [o.value_sats for o in report.outputs]
    total_out = sum(values) or 1

    # Heuristic signal: only meaningful when there are at least 2 outputs.
    for out in report.outputs:
        reasons: list[str] = []
        score = 0.0

        if n_outputs < 2:
            out.is_change_candidate = False
            out.change_confidence = 0.0
            out.change_reasons = []
            continue

        # 1. Matches an input script type (same wallet is likely).
        if input_types and out.script_type in input_types:
            score += 0.35
            reasons.append("script type matches one of the inputs")

        # 2. Non-round amount (payments to humans tend to be round).
        if not _is_round(out.value_sats):
            score += 0.25
            reasons.append("non-round amount")
        else:
            reasons.append("round amount (less likely to be change)")

        # 3. Smaller fraction of total output value (change is often the leftover).
        fraction = out.value_sats / total_out
        if fraction < 0.5:
            score += 0.15 * (1 - fraction)
            reasons.append(f"smaller output ({fraction:.1%} of total)")

        # 4. Avoid OP_RETURN.
        if out.script_type is ScriptType.OP_RETURN:
            score = 0.0
            reasons = ["OP_RETURN cannot be change"]

        out.is_change_candidate = score >= 0.4
        out.change_confidence = round(min(score, 0.95), 2)
        out.change_reasons = reasons

    _pick_single_candidate(report.outputs)
    return report


def _pick_single_candidate(outputs: list[OutputView]) -> None:
    """If multiple outputs qualify, keep only the strongest as the single change candidate."""
    candidates = [o for o in outputs if o.is_change_candidate]
    if len(candidates) <= 1:
        return
    best = max(candidates, key=lambda o: (o.change_confidence, -o.value_sats))
    for o in candidates:
        if o is not best:
            o.is_change_candidate = False
            o.change_reasons = [*o.change_reasons, "another output had stronger signals"]
