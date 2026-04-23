"""Pydantic response models shared by the parser, simulator, and editor."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .scripts import ScriptType


class InputView(BaseModel):
    index: int
    txid: str
    vout: int
    sequence: int
    script_type: ScriptType
    address: str | None = None
    script_pub_key_hex: str | None = None
    value_sats: int | None = Field(
        default=None,
        description="Prevout value in satoshis if known (witness_utxo or non_witness_utxo).",
    )
    value_source: str | None = Field(
        default=None,
        description="Where the value came from: witness_utxo | non_witness_utxo | unknown.",
    )
    vsize: float
    weight: int
    partial_sigs: int = 0
    final_scriptsig: bool = False
    final_scriptwitness: bool = False


class OutputView(BaseModel):
    index: int
    script_type: ScriptType
    address: str | None = None
    script_pub_key_hex: str
    value_sats: int
    size_bytes: int
    is_change_candidate: bool = False
    change_confidence: float = 0.0
    change_reasons: list[str] = Field(default_factory=list)


class FeeInfo(BaseModel):
    total_in_sats: int | None
    total_out_sats: int
    fee_sats: int | None
    vsize: float
    weight: int
    fee_rate_sat_vb: float | None
    unknown_inputs: int = 0


class MempoolFeeComparison(BaseModel):
    recommended: dict[str, int] | None = None
    effective_sat_vb: float | None = None
    bucket: str | None = Field(
        default=None,
        description="Closest bucket: below_min | min | hour | half_hour | fastest | over_fastest.",
    )
    percent_vs_half_hour: float | None = None
    note: str | None = None


class PSBTReport(BaseModel):
    psbt_version: int
    network: str
    inputs: list[InputView]
    outputs: list[OutputView]
    fees: FeeInfo
    fee_comparison: MempoolFeeComparison | None = None
    script_mix_note: str
    warnings: list[str] = Field(default_factory=list)
    psbt_base64: str = Field(description="Re-serialized PSBT so clients can round-trip edits.")


class AnalyzeRequest(BaseModel):
    """Accept a PSBT as base64, hex, or raw bytes (base64-encoded for JSON transport)."""

    psbt_base64: str | None = None
    psbt_hex: str | None = None


class UTXO(BaseModel):
    outpoint: str = Field(description="txid:vout identifier.")
    value_sats: int
    script_type: ScriptType
    address: str | None = None
    label: str | None = None
    index: int | None = Field(
        default=None,
        description="PSBT input index when known (e.g. coin-sim bootstrap).",
    )


class PaymentTarget(BaseModel):
    address: str | None = None
    script_type: ScriptType
    value_sats: int
    index: int | None = Field(
        default=None,
        description="PSBT output index when known (e.g. coin-sim bootstrap).",
    )


class CoinSimRequest(BaseModel):
    utxos: list[UTXO]
    targets: list[PaymentTarget]
    change_script_type: ScriptType = ScriptType.P2WPKH
    fee_rate_sat_vb: float = 1.0
    dust_threshold_sats: int = 546
    strategies: list[str] = Field(
        default_factory=lambda: ["largest_first", "smallest_first", "branch_and_bound"]
    )


class CoinSimResult(BaseModel):
    strategy: str
    ok: bool
    message: str | None = None
    selected_outpoints: list[str] = Field(default_factory=list)
    total_in_sats: int = 0
    total_out_sats: int = 0
    change_sats: int = 0
    fee_sats: int = 0
    vsize: float = 0.0
    fee_rate_sat_vb: float = 0.0
    num_inputs: int = 0
    num_outputs: int = 0


class CoinSimResponse(BaseModel):
    results: list[CoinSimResult]
    best_strategy: str | None = None


class EditOp(BaseModel):
    """One structured edit to apply to a PSBT."""

    op: str = Field(
        description=(
            "drop_input | add_input | set_input_value | "
            "set_output_value | drop_output | add_output"
        ),
    )
    input_index: int | None = None
    output_index: int | None = None
    value_sats: int | None = None
    address: str | None = None
    script_pub_key_hex: str | None = None
    txid: str | None = Field(
        default=None,
        description="Prev-tx hex id for add_input; synthesized if omitted.",
    )
    vout: int | None = Field(
        default=None,
        description="Prev-tx output index for add_input; defaults to 0.",
    )


class ApplyRequest(BaseModel):
    psbt_base64: str | None = None
    psbt_hex: str | None = None
    ops: list[EditOp]


class ApplyResponse(BaseModel):
    psbt_base64: str
    report: PSBTReport
    applied: list[EditOp]
    notes: list[str] = Field(default_factory=list)
