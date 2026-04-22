"""Parse a PSBT into a normalized :class:`PSBTReport`."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from embit.networks import NETWORKS
from embit.psbt import PSBT
from embit.script import Script

from .models import FeeInfo, InputView, OutputView, PSBTReport
from .scripts import (
    ScriptType,
    classify_script_pubkey,
    estimate_tx_vsize,
    input_vsize,
    output_size,
    refine_p2sh_wrapping,
    weight_contribution,
)

_NETWORK_KEYS = {
    "mainnet": "main",
    "main": "main",
    "testnet": "test",
    "test": "test",
    "signet": "signet",
    "regtest": "regtest",
}


def _network(network: str) -> dict[str, Any]:
    key = _NETWORK_KEYS.get(network.lower(), "main")
    return NETWORKS[key]


def normalize_psbt_base64_paste(text: str) -> str:
    """Undo ``application/x-www-form-urlencoded`` turning ``+`` into space.

    Strips other whitespace (line breaks) from pasted base64. PSBT wire bytes
    never contain unencoded ASCII spaces.
    """
    s = text.strip().replace(" ", "+")
    return "".join(s.split())


def split_psbt_paste(text: str) -> tuple[str | None, str | None]:
    """Return ``(psbt_base64, psbt_hex)`` for :func:`_decode_psbt` — exactly one is set.

    Distinguishes hex (optional internal whitespace) from base64; normalizes
    base64 that was broken by form encoding or newlines in paste.
    """
    s = text.strip()
    hex_compact = re.sub(r"\s+", "", s)
    is_hex = (
        len(hex_compact) > 0
        and len(hex_compact) % 2 == 0
        and all(c in "0123456789abcdefABCDEF" for c in hex_compact)
    )
    if is_hex:
        return None, hex_compact
    return normalize_psbt_base64_paste(s), None


def _decode_psbt(psbt_base64: str | None, psbt_hex: str | None) -> PSBT:
    """Decode either base64 or hex-encoded PSBT bytes into a PSBT object."""
    if psbt_base64:
        data = psbt_base64.strip()
        try:
            raw = base64.b64decode(data, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Invalid base64 PSBT: {exc}") from exc
        return PSBT.parse(raw)
    if psbt_hex:
        try:
            raw = bytes.fromhex(psbt_hex.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid hex PSBT: {exc}") from exc
        return PSBT.parse(raw)
    raise ValueError("No PSBT provided: expected psbt_base64 or psbt_hex.")


def _script_to_address(script: bytes | None, network_key: str) -> str | None:
    if not script:
        return None
    try:
        return Script(bytes(script)).address(_network(network_key))
    except Exception:
        return None


def _txid_display(raw: bytes) -> str:
    """Return the display (big-endian) txid hex.

    embit stores ``TransactionInput.txid`` in display order already (it reverses
    the raw bytes on read and write), so we just hex-encode here.
    """
    if not raw:
        return ""
    return bytes(raw).hex()


def _input_value(psbt_input: Any, vin_vout: int) -> tuple[int | None, bytes | None, str]:
    """Return (value_sats, script_pub_key, source) for a PSBT input."""
    wu = getattr(psbt_input, "witness_utxo", None)
    if wu is not None:
        return int(wu.value), bytes(wu.script_pubkey.data), "witness_utxo"
    nwu = getattr(psbt_input, "non_witness_utxo", None)
    if nwu is not None and 0 <= vin_vout < len(nwu.vout):
        txout = nwu.vout[vin_vout]
        return int(txout.value), bytes(txout.script_pubkey.data), "non_witness_utxo"
    return None, None, "unknown"


def _psbt_version(psbt: PSBT) -> int:
    ver = getattr(psbt, "version", None)
    if isinstance(ver, int):
        return ver
    return 0


def _to_base64(psbt: PSBT) -> str:
    data = psbt.serialize()
    return base64.b64encode(data).decode("ascii")


def _script_mix_note(
    input_types: list[ScriptType], output_types: list[ScriptType]
) -> str:
    def _summary(items: list[ScriptType]) -> str:
        if not items:
            return "none"
        counts: dict[str, int] = {}
        for it in items:
            counts[it.value] = counts.get(it.value, 0) + 1
        return ", ".join(f"{k} x{v}" for k, v in sorted(counts.items()))

    return f"inputs: {_summary(input_types)}; outputs: {_summary(output_types)}"


def build_report(psbt: PSBT, network: str) -> PSBTReport:
    """Construct a :class:`PSBTReport` from a parsed embit PSBT."""
    warnings: list[str] = []
    tx = psbt.tx

    inputs: list[InputView] = []
    input_types: list[ScriptType] = []
    total_in: int = 0
    unknown_inputs = 0

    for i, vin in enumerate(tx.vin):
        psbt_in = psbt.inputs[i]
        value, spk, source = _input_value(psbt_in, vin.vout)
        outer = classify_script_pubkey(spk) if spk is not None else ScriptType.UNKNOWN
        redeem = getattr(psbt_in, "redeem_script", None)
        redeem_bytes = bytes(redeem.data) if redeem is not None else None
        stype = refine_p2sh_wrapping(outer, redeem_bytes)
        vsize = input_vsize(stype)
        weight = weight_contribution(vsize)
        input_types.append(stype)

        if value is None:
            unknown_inputs += 1
            warnings.append(f"Input {i}: missing prevout value (no witness/non-witness utxo).")
        else:
            total_in += value

        partial_sigs = getattr(psbt_in, "partial_sigs", None) or {}
        final_ss = bool(getattr(psbt_in, "final_scriptsig", None))
        final_sw = bool(getattr(psbt_in, "final_scriptwitness", None))

        inputs.append(
            InputView(
                index=i,
                txid=_txid_display(vin.txid),
                vout=int(vin.vout),
                sequence=int(vin.sequence),
                script_type=stype,
                address=_script_to_address(spk, network),
                script_pub_key_hex=spk.hex() if spk else None,
                value_sats=value,
                value_source=source,
                vsize=vsize,
                weight=weight,
                partial_sigs=len(partial_sigs),
                final_scriptsig=final_ss,
                final_scriptwitness=final_sw,
            )
        )

    outputs: list[OutputView] = []
    output_types: list[ScriptType] = []
    total_out: int = 0

    for j, vout in enumerate(tx.vout):
        spk_bytes = bytes(vout.script_pubkey.data)
        stype = classify_script_pubkey(spk_bytes)
        size = output_size(stype, spk_bytes if stype is ScriptType.OP_RETURN else None)
        total_out += int(vout.value)
        output_types.append(stype)
        outputs.append(
            OutputView(
                index=j,
                script_type=stype,
                address=_script_to_address(spk_bytes, network),
                script_pub_key_hex=spk_bytes.hex(),
                value_sats=int(vout.value),
                size_bytes=size,
            )
        )

    vsize = estimate_tx_vsize(input_types, output_types)
    weight = weight_contribution(vsize)
    fee: int | None = None
    fee_rate: float | None = None
    if unknown_inputs == 0:
        fee = total_in - total_out
        fee_rate = (fee / vsize) if vsize > 0 else None
        if fee < 0:
            warnings.append(
                "Computed fee is negative; outputs exceed known inputs (likely malformed PSBT)."
            )

    fees = FeeInfo(
        total_in_sats=None if unknown_inputs > 0 else total_in,
        total_out_sats=total_out,
        fee_sats=fee,
        vsize=vsize,
        weight=weight,
        fee_rate_sat_vb=fee_rate,
        unknown_inputs=unknown_inputs,
    )

    return PSBTReport(
        psbt_version=_psbt_version(psbt),
        network=network,
        inputs=inputs,
        outputs=outputs,
        fees=fees,
        script_mix_note=_script_mix_note(input_types, output_types),
        warnings=warnings,
        psbt_base64=_to_base64(psbt),
    )


def analyze_psbt(
    psbt_base64: str | None = None,
    psbt_hex: str | None = None,
    network: str = "mainnet",
) -> tuple[PSBT, PSBTReport]:
    """Decode and analyze a PSBT. Returns the parsed PSBT and the report."""
    psbt = _decode_psbt(psbt_base64, psbt_hex)
    return psbt, build_report(psbt, network)
