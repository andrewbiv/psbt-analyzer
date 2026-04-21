"""Helpers to build fixture PSBTs programmatically with embit.

Using constructed fixtures (rather than hard-coded vectors) means the tests
stay in sync with whatever PSBT version and serialization embit produces.
"""

from __future__ import annotations

from embit.psbt import PSBT
from embit.script import address_to_scriptpubkey
from embit.transaction import Transaction, TransactionInput, TransactionOutput

# Well-known mainnet addresses used for deterministic tests.
P2WPKH_1 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
P2WPKH_2 = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
P2PKH = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
P2TR = "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"


def _tx_input(prev_txid_hex: str = "aa" * 32, vout: int = 0) -> TransactionInput:
    return TransactionInput(bytes.fromhex(prev_txid_hex), vout)


def segwit_two_output_psbt(
    input_value: int = 200_000,
    pay_value: int = 50_000,
    change_value: int = 147_932,
) -> str:
    """One P2WPKH input, one P2WPKH payment, one P2WPKH change. Fee = in - out.

    ``pay_value`` defaults to a round-looking human payment and ``change_value``
    to a non-round leftover so the change heuristic has a clean signal to pick
    up on.
    """
    prev_spk = address_to_scriptpubkey(P2WPKH_1)
    pay_spk = address_to_scriptpubkey(P2WPKH_2)
    tx = Transaction(
        version=2,
        vin=[_tx_input()],
        vout=[TransactionOutput(pay_value, pay_spk), TransactionOutput(change_value, prev_spk)],
        locktime=0,
    )
    psbt = PSBT(tx)
    psbt.inputs[0].witness_utxo = TransactionOutput(input_value, prev_spk)
    return psbt.to_base64()


def taproot_psbt(input_value: int = 100_000, pay_value: int = 90_000) -> str:
    prev_spk = address_to_scriptpubkey(P2TR)
    pay_spk = address_to_scriptpubkey(P2WPKH_1)
    tx = Transaction(
        version=2,
        vin=[_tx_input()],
        vout=[TransactionOutput(pay_value, pay_spk)],
        locktime=0,
    )
    psbt = PSBT(tx)
    psbt.inputs[0].witness_utxo = TransactionOutput(input_value, prev_spk)
    return psbt.to_base64()


def legacy_psbt(input_value: int = 100_000, pay_value: int = 90_000) -> str:
    """P2PKH input + P2PKH output. Requires a non_witness_utxo (full prev tx)."""
    prev_spk = address_to_scriptpubkey(P2PKH)
    pay_spk = address_to_scriptpubkey(P2PKH)
    # Build a synthetic prev tx so the PSBT has a valid non_witness_utxo.
    prev_tx = Transaction(
        version=2,
        vin=[_tx_input("bb" * 32, 0)],
        vout=[TransactionOutput(input_value, prev_spk)],
        locktime=0,
    )
    tx = Transaction(
        version=2,
        vin=[TransactionInput(bytes.fromhex(prev_tx.txid().hex()), 0)],
        vout=[TransactionOutput(pay_value, pay_spk)],
        locktime=0,
    )
    psbt = PSBT(tx)
    psbt.inputs[0].non_witness_utxo = prev_tx
    return psbt.to_base64()


def unknown_input_value_psbt() -> str:
    """Intentionally omits witness_utxo / non_witness_utxo on the input."""
    pay_spk = address_to_scriptpubkey(P2WPKH_2)
    tx = Transaction(
        version=2,
        vin=[_tx_input()],
        vout=[TransactionOutput(50_000, pay_spk)],
        locktime=0,
    )
    psbt = PSBT(tx)
    return psbt.to_base64()


def mixed_type_psbt() -> str:
    """Two inputs (P2WPKH + P2TR), one payment, one change."""
    wpkh_spk = address_to_scriptpubkey(P2WPKH_1)
    tr_spk = address_to_scriptpubkey(P2TR)
    pay_spk = address_to_scriptpubkey(P2PKH)

    tx = Transaction(
        version=2,
        vin=[_tx_input("aa" * 32, 0), _tx_input("bb" * 32, 1)],
        vout=[
            TransactionOutput(120_000, pay_spk),
            TransactionOutput(80_000, wpkh_spk),
        ],
        locktime=0,
    )
    psbt = PSBT(tx)
    psbt.inputs[0].witness_utxo = TransactionOutput(150_000, wpkh_spk)
    psbt.inputs[1].witness_utxo = TransactionOutput(60_000, tr_spk)
    return psbt.to_base64()


__all__ = [
    "P2PKH",
    "P2TR",
    "P2WPKH_1",
    "P2WPKH_2",
    "legacy_psbt",
    "mixed_type_psbt",
    "segwit_two_output_psbt",
    "taproot_psbt",
    "unknown_input_value_psbt",
]
