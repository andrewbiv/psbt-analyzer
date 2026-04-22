#!/usr/bin/env python3
"""Build a synthetic unsigned PSBT (P2WPKH inputs/outputs) for testing.

Fee is ``ceil(fee_rate_sat_vb * estimated_vsize)`` using the same vsize model
as PSBT Analyzer. Amounts satisfy sum(inputs) = sum(outputs) + fee. Keys and
txids are deterministic and not from the live chain — use only on regtest
or for tools like PSBT Analyzer.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
from pathlib import Path

from embit.ec import ECError, PrivateKey
from embit.psbt import PSBT
from embit.script import p2wpkh
from embit.transaction import Transaction, TransactionInput, TransactionOutput

from psbt_tool.core.scripts import ScriptType, estimate_tx_vsize

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PSBT_DIR = _REPO_ROOT / "generated_psbts"


def _fee_tag(fee_rate: float) -> str:
    s = f"{fee_rate:.10g}".rstrip("0").rstrip(".")
    return s.replace(".", "p") if s else "0"


def _nth_valid_secret(n: int) -> bytes:
    """Derive a valid secp256k1 secret from index n (deterministic)."""
    x = max(0, n)
    for _ in range(100_000):
        digest = hashlib.sha256(x.to_bytes(8, "big", signed=False)).digest()
        try:
            PrivateKey(digest)
            return digest
        except ECError:
            x += 1
    raise RuntimeError("could not derive a valid private key; try a different n")


def _split_total(total: int, parts: int) -> list[int]:
    if parts <= 0:
        raise ValueError("parts must be positive")
    base, rem = divmod(total, parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]


def _fake_txid(idx: int) -> bytes:
    return hashlib.sha256(f"synthetic-input-{idx}".encode()).digest()


def build_psbt(
    num_inputs: int,
    num_outputs: int,
    fee_rate_sat_vb: float,
    per_output_sats: int,
) -> tuple[PSBT, float, int]:
    if num_inputs < 1 or num_outputs < 1:
        raise ValueError("inputs and outputs must be at least 1")
    if fee_rate_sat_vb < 0:
        raise ValueError("fee rate must be non-negative")
    if per_output_sats < 546:
        raise ValueError("per-output amount must be at least 546 sats (dust limit)")

    vsize_est = estimate_tx_vsize(
        [ScriptType.P2WPKH] * num_inputs,
        [ScriptType.P2WPKH] * num_outputs,
    )
    fee_sats = max(0, math.ceil(fee_rate_sat_vb * vsize_est))

    total_out = per_output_sats * num_outputs
    total_in = total_out + fee_sats
    input_values = _split_total(total_in, num_inputs)

    input_keys = [PrivateKey(_nth_valid_secret(i)) for i in range(num_inputs)]
    output_keys = [
        PrivateKey(_nth_valid_secret(num_inputs + j)) for j in range(num_outputs)
    ]

    vins: list[TransactionInput] = []
    for i in range(num_inputs):
        vins.append(
            TransactionInput(
                _fake_txid(i),
                0,
                sequence=0xFFFFFFFD,  # RBF-enabled, common in wallets
            )
        )

    vouts = [
        TransactionOutput(per_output_sats, p2wpkh(output_keys[j].get_public_key()))
        for j in range(num_outputs)
    ]

    tx = Transaction(version=2, vin=vins, vout=vouts, locktime=0)
    psbt = PSBT(tx)

    for i in range(num_inputs):
        spk = p2wpkh(input_keys[i].get_public_key())
        psbt.inputs[i].witness_utxo = TransactionOutput(input_values[i], spk)

    return psbt, vsize_est, fee_sats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Generate a synthetic .psbt with N inputs, M outputs, "
            "and fee from fee rate (sat/vB) × estimated vsize."
        )
    )
    p.add_argument(
        "--inputs",
        "-i",
        type=int,
        required=True,
        metavar="N",
        help="number of inputs (UTXOs)",
    )
    p.add_argument(
        "--outputs",
        "-o",
        type=int,
        required=True,
        metavar="M",
        help="number of outputs (payments)",
    )
    p.add_argument(
        "--fee-rate",
        "-f",
        type=float,
        required=True,
        metavar="SAT_VB",
        help="fee rate in satoshis per virtual byte (vsize × rate, rounded up)",
    )
    p.add_argument(
        "--per-output",
        type=int,
        default=100_000,
        metavar="SATS",
        help="value of each output in sats (default: 100000)",
    )
    p.add_argument(
        "--out",
        "-O",
        type=Path,
        default=DEFAULT_PSBT_DIR,
        help=f"output directory for .psbt files (default: {DEFAULT_PSBT_DIR})",
    )
    p.add_argument(
        "--name",
        type=str,
        default=None,
        metavar="STEM",
        help="output filename without .psbt; default: iN_oM_fRATE_poSATS from parameters",
    )
    args = p.parse_args(argv)

    try:
        psbt, vsize_est, fee_sats = build_psbt(
            args.inputs, args.outputs, args.fee_rate, args.per_output
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.name:
        stem = args.name
    else:
        stem = (
            f"i{args.inputs}_o{args.outputs}_f{_fee_tag(args.fee_rate)}_po{args.per_output}"
        )
    out_path = out_dir / f"{stem}.psbt"
    raw = psbt.serialize()
    out_path.write_bytes(raw)
    total_in = sum(psbt.utxo(i).value for i in range(len(psbt.inputs)))
    total_out = sum(o.value for o in psbt.tx.vout)
    print(f"Wrote {out_path} ({len(raw)} bytes)")
    print(
        f"  inputs: {args.inputs}, outputs: {args.outputs}, "
        f"fee rate: {args.fee_rate} sat/vB, est. vsize: {vsize_est:.1f} vB"
    )
    print(f"  fee (rounded): {fee_sats} sats")
    print(
        f"  total in {total_in} sats, total out {total_out} sats, "
        f"implicit fee {total_in - total_out} sats"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
