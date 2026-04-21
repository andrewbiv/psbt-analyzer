"""Script type detection and size/weight helpers.

Detection is done directly from ``scriptPubKey`` bytes so it does not depend
on any specific library version. The size estimates are the standard wallet
figures used for fee estimation (BIP 141 weight units / vbytes, with segwit
and taproot discounts folded in).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ScriptType(StrEnum):
    P2PK = "P2PK"
    P2PKH = "P2PKH"
    P2SH = "P2SH"
    P2SH_P2WPKH = "P2SH-P2WPKH"
    P2SH_P2WSH = "P2SH-P2WSH"
    P2WPKH = "P2WPKH"
    P2WSH = "P2WSH"
    P2TR = "P2TR"
    OP_RETURN = "OP_RETURN"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SizeEstimate:
    """Witness-aware size estimates for a single input or output, in vbytes.

    ``witness_discount`` is True when the type benefits from segwit's
    witness discount (witness data counts as 1 WU per byte instead of 4).
    """

    vbytes: float
    witness_discount: bool


# Output sizes in bytes. Outputs have no witness, so vbytes == bytes.
# Each is 8-byte value + 1-byte script length + scriptPubKey bytes.
_OUTPUT_SIZES: dict[ScriptType, int] = {
    ScriptType.P2PKH: 34,
    ScriptType.P2SH: 32,
    ScriptType.P2SH_P2WPKH: 32,
    ScriptType.P2SH_P2WSH: 32,
    ScriptType.P2WPKH: 31,
    ScriptType.P2WSH: 43,
    ScriptType.P2TR: 43,
    ScriptType.P2PK: 44,
    ScriptType.OP_RETURN: 11,  # minimal placeholder; real size depends on payload
    ScriptType.UNKNOWN: 34,
}

# Typical single-signer spend sizes in vbytes. These are the commonly cited
# wallet estimates and are accurate enough for fee guidance.
_INPUT_VSIZES: dict[ScriptType, float] = {
    ScriptType.P2PKH: 148.0,
    ScriptType.P2SH: 297.0,  # pessimistic; depends on redeem script
    ScriptType.P2SH_P2WPKH: 91.0,
    ScriptType.P2SH_P2WSH: 140.0,
    ScriptType.P2WPKH: 68.0,
    ScriptType.P2WSH: 104.5,  # 2-of-3 multisig baseline
    ScriptType.P2TR: 57.5,  # key-path spend
    ScriptType.P2PK: 113.0,
    ScriptType.UNKNOWN: 110.0,
}

_WITNESS_TYPES = {
    ScriptType.P2WPKH,
    ScriptType.P2WSH,
    ScriptType.P2TR,
    ScriptType.P2SH_P2WPKH,
    ScriptType.P2SH_P2WSH,
}


def classify_script_pubkey(script: bytes | None) -> ScriptType:
    """Classify a raw scriptPubKey."""
    if not script:
        return ScriptType.UNKNOWN
    b = bytes(script)
    n = len(b)

    # OP_RETURN
    if n >= 1 and b[0] == 0x6A:
        return ScriptType.OP_RETURN

    # P2PKH: 25 bytes, OP_DUP OP_HASH160 0x14 <20> OP_EQUALVERIFY OP_CHECKSIG
    if (
        n == 25
        and b[0] == 0x76
        and b[1] == 0xA9
        and b[2] == 0x14
        and b[23] == 0x88
        and b[24] == 0xAC
    ):
        return ScriptType.P2PKH

    # P2SH: 23 bytes, OP_HASH160 0x14 <20> OP_EQUAL
    if n == 23 and b[0] == 0xA9 and b[1] == 0x14 and b[22] == 0x87:
        return ScriptType.P2SH

    # P2WPKH: 22 bytes, OP_0 0x14 <20>
    if n == 22 and b[0] == 0x00 and b[1] == 0x14:
        return ScriptType.P2WPKH

    # P2WSH: 34 bytes, OP_0 0x20 <32>
    if n == 34 and b[0] == 0x00 and b[1] == 0x20:
        return ScriptType.P2WSH

    # P2TR: 34 bytes, OP_1 0x20 <32>
    if n == 34 and b[0] == 0x51 and b[1] == 0x20:
        return ScriptType.P2TR

    # P2PK: <pubkey> OP_CHECKSIG; 35 or 67 bytes
    if (n == 35 and b[0] == 0x21 and b[34] == 0xAC) or (n == 67 and b[0] == 0x41 and b[66] == 0xAC):
        return ScriptType.P2PK

    return ScriptType.UNKNOWN


def refine_p2sh_wrapping(outer: ScriptType, redeem_script: bytes | None) -> ScriptType:
    """Refine a bare P2SH type using the redeem script when known (PSBT input)."""
    if outer is not ScriptType.P2SH or not redeem_script:
        return outer
    inner = classify_script_pubkey(redeem_script)
    if inner is ScriptType.P2WPKH:
        return ScriptType.P2SH_P2WPKH
    if inner is ScriptType.P2WSH:
        return ScriptType.P2SH_P2WSH
    return outer


def output_size(script_type: ScriptType, script: bytes | None = None) -> int:
    """Size of an output in bytes (== vbytes)."""
    if script_type is ScriptType.OP_RETURN and script is not None:
        return 9 + len(script)  # 8 value + 1 length + script
    return _OUTPUT_SIZES.get(script_type, _OUTPUT_SIZES[ScriptType.UNKNOWN])


def input_vsize(script_type: ScriptType) -> float:
    """Estimated spend-input vsize for a single signer."""
    return _INPUT_VSIZES.get(script_type, _INPUT_VSIZES[ScriptType.UNKNOWN])


def uses_witness_discount(script_type: ScriptType) -> bool:
    return script_type in _WITNESS_TYPES


def estimate_tx_vsize(input_types: list[ScriptType], output_types: list[ScriptType]) -> float:
    """Estimate the full transaction vsize given input and output types.

    Overhead: 10.5 vbytes for a segwit transaction (version 4 + marker/flag 0.5
    + locktime 4 + input/output counts 2); 10 vbytes for a legacy one.
    """
    has_witness = any(uses_witness_discount(t) for t in input_types)
    overhead = 10.5 if has_witness else 10.0
    ins = sum(input_vsize(t) for t in input_types)
    outs = sum(output_size(t) for t in output_types)
    return overhead + ins + outs


def weight_contribution(vbytes: float) -> int:
    """Convert vbytes to weight units (WU)."""
    return int(round(vbytes * 4))
