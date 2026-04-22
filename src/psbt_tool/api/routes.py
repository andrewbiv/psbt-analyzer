"""API routes: analyze, apply edits, coin-sim, fees."""

from __future__ import annotations

import base64

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import get_settings
from ..core import fees as fees_mod
from ..core import heuristics
from ..core.coin_sim import bootstrap_from_report, run_simulation
from ..core.editor import apply_ops
from ..core.models import (
    AnalyzeRequest,
    ApplyRequest,
    ApplyResponse,
    CoinSimRequest,
    CoinSimResponse,
    PSBTReport,
)
from ..core.parser import analyze_psbt, build_report, normalize_psbt_base64_paste, split_psbt_paste

router = APIRouter(tags=["psbt"])


def _guard_size(psbt_b64: str | None, psbt_hex: str | None, raw: bytes | None = None) -> None:
    settings = get_settings()
    size = 0
    if psbt_b64:
        size = max(size, len(psbt_b64) * 3 // 4)
    if psbt_hex:
        size = max(size, len(psbt_hex) // 2)
    if raw is not None:
        size = max(size, len(raw))
    if size > settings.max_psbt_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"PSBT exceeds MAX_PSBT_BYTES ({settings.max_psbt_bytes} bytes).",
        )


async def _attach_fee_comparison(report: PSBTReport) -> None:
    """Best-effort enrichment: add mempool fee comparison; swallow network errors."""
    try:
        recommended = await fees_mod.fetch_recommended_fees()
    except Exception as exc:  # pragma: no cover - network-dependent
        report.fee_comparison = fees_mod.compare_effective_fee(
            report.fees.fee_rate_sat_vb, None
        )
        report.warnings.append(f"Could not fetch mempool fees: {exc}")
        return
    report.fee_comparison = fees_mod.compare_effective_fee(
        report.fees.fee_rate_sat_vb, recommended
    )


@router.post("/psbt/analyze", response_model=PSBTReport)
async def analyze_json(req: AnalyzeRequest) -> PSBTReport:
    settings = get_settings()
    _guard_size(req.psbt_base64, req.psbt_hex)
    try:
        _, report = analyze_psbt(req.psbt_base64, req.psbt_hex, settings.network)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    heuristics.annotate_change(report)
    await _attach_fee_comparison(report)
    return report


_UPLOAD = File(...)
_PSBT_FORM = Form(...)


@router.post("/psbt/analyze/upload", response_model=PSBTReport)
async def analyze_upload(file: UploadFile = _UPLOAD) -> PSBTReport:
    settings = get_settings()
    raw = await file.read()
    _guard_size(None, None, raw)
    try:
        # File may be raw PSBT bytes or base64 text. Try base64 first.
        text = raw.strip().decode("ascii", errors="ignore")
        if text.startswith("cHNidP") or text.startswith("cHNid"):
            psbt_b64 = normalize_psbt_base64_paste(text)
        else:
            psbt_b64 = base64.b64encode(raw).decode("ascii")
        _, report = analyze_psbt(psbt_b64, None, settings.network)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    heuristics.annotate_change(report)
    await _attach_fee_comparison(report)
    return report


@router.post("/psbt/analyze/text", response_model=PSBTReport)
async def analyze_text(psbt: str = _PSBT_FORM) -> PSBTReport:
    settings = get_settings()
    b64, hx = split_psbt_paste(psbt)
    _guard_size(b64, hx)
    try:
        _, report = analyze_psbt(b64, hx, settings.network)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    heuristics.annotate_change(report)
    await _attach_fee_comparison(report)
    return report


@router.post("/psbt/apply", response_model=ApplyResponse)
async def apply_edits(req: ApplyRequest) -> ApplyResponse:
    settings = get_settings()
    _guard_size(req.psbt_base64, req.psbt_hex)
    try:
        psbt, _ = analyze_psbt(req.psbt_base64, req.psbt_hex, settings.network)
        psbt, notes = apply_ops(psbt, req.ops, settings.network)
        report = build_report(psbt, settings.network)
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Edit failed: {exc}") from exc
    heuristics.annotate_change(report)
    await _attach_fee_comparison(report)
    return ApplyResponse(
        psbt_base64=report.psbt_base64,
        report=report,
        applied=req.ops,
        notes=notes,
    )


@router.post("/coin-sim/run", response_model=CoinSimResponse)
async def run_coin_sim(req: CoinSimRequest) -> CoinSimResponse:
    return run_simulation(req)


@router.post("/coin-sim/bootstrap", response_model=CoinSimRequest)
async def bootstrap_coin_sim(req: AnalyzeRequest) -> CoinSimRequest:
    """Parse a PSBT and return a pre-filled coin-sim request."""
    settings = get_settings()
    _guard_size(req.psbt_base64, req.psbt_hex)
    try:
        _, report = analyze_psbt(req.psbt_base64, req.psbt_hex, settings.network)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    heuristics.annotate_change(report)
    return bootstrap_from_report(report.inputs, report.outputs)


@router.get("/fees/recommended")
async def get_recommended_fees() -> dict[str, int | str]:
    try:
        data = await fees_mod.fetch_recommended_fees()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mempool fees unavailable: {exc}") from exc
    return data
