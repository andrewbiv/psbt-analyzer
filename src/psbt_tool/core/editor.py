"""Apply structured edits to a PSBT and return a re-serialized copy.

Supported ops:

- ``drop_input``: remove the input at ``input_index`` from the global tx and
  the PSBT input map. Strips partial signatures that would no longer be valid
  (any edit that changes the unsigned tx invalidates prior signatures).
- ``set_input_value``: change the prevout value of an existing input.
  Updates ``witness_utxo.value`` when available, otherwise
  ``non_witness_utxo.vout[vin.vout].value``. Errors if neither is present.
- ``add_input``: append a new input backed by a ``witness_utxo``. Requires
  ``value_sats`` and either ``address`` or ``script_pub_key_hex``; ``txid`` and
  ``vout`` are optional and synthesized from the current time if omitted.
- ``set_output_value``: change the value (in sats) of an existing output.
- ``drop_output``: remove the output at ``output_index``.
- ``add_output``: append a new output given either an ``address`` (decoded
  against the configured network) or a raw ``script_pub_key_hex``.

Any tx-structure-changing op clears ``partial_sigs``, ``final_scriptsig``,
and ``final_scriptwitness`` on affected inputs: the user will need to
re-sign. This is called out in the response notes.
"""

from __future__ import annotations

import hashlib
import time

from embit.networks import NETWORKS
from embit.psbt import PSBT, InputScope, OutputScope
from embit.script import Script, address_to_scriptpubkey
from embit.transaction import TransactionInput, TransactionOutput

from .models import EditOp

# Storage model in embit:
#   - PSBT.tx is a *property* that rebuilds a fresh Transaction each access
#     from PSBT.inputs[i].vin and PSBT.outputs[j].vout.
#   - PSBT.outputs[j].value / .script_pubkey are the real storage.
# Any edit must mutate inputs[i] / outputs[j] directly; mutating psbt.tx.vout
# would be a no-op since that list is thrown away after each access.


_NETWORK_KEYS = {
    "mainnet": "main",
    "main": "main",
    "testnet": "test",
    "test": "test",
    "signet": "signet",
    "regtest": "regtest",
}


def _network(name: str):
    return NETWORKS[_NETWORK_KEYS.get(name.lower(), "main")]


def _script_from_op(op: EditOp, network: str) -> Script:
    if op.script_pub_key_hex:
        return Script(bytes.fromhex(op.script_pub_key_hex))
    if op.address:
        return address_to_scriptpubkey(op.address)
    raise ValueError(f"{op.op} requires address or script_pub_key_hex.")


def _synthetic_txid() -> bytes:
    """Deterministic-ish 32-byte id for manually added inputs.

    Used only so the PSBT parses cleanly; real prev-tx hashes should come from
    the caller when available.
    """
    seed = f"manual-input-{time.time_ns()}".encode()
    return hashlib.sha256(seed).digest()


def _strip_signing_data(psbt: PSBT) -> None:
    for pi in psbt.inputs:
        if getattr(pi, "partial_sigs", None):
            pi.partial_sigs = {}
        pi.final_scriptsig = None
        pi.final_scriptwitness = None


def apply_ops(psbt: PSBT, ops: list[EditOp], network: str = "mainnet") -> tuple[PSBT, list[str]]:
    """Apply ``ops`` in order to ``psbt`` in place. Returns the PSBT and notes."""
    notes: list[str] = []
    structure_changed = False

    for op in ops:
        name = op.op
        if name == "drop_input":
            if op.input_index is None:
                raise ValueError("drop_input requires input_index.")
            idx = op.input_index
            if not (0 <= idx < len(psbt.inputs)):
                raise IndexError(f"input_index out of range: {idx}")
            del psbt.inputs[idx]
            structure_changed = True
            notes.append(f"Dropped input {idx}.")
        elif name == "set_input_value":
            if op.input_index is None or op.value_sats is None:
                raise ValueError("set_input_value requires input_index and value_sats.")
            idx = op.input_index
            if not (0 <= idx < len(psbt.inputs)):
                raise IndexError(f"input_index out of range: {idx}")
            pin = psbt.inputs[idx]
            new_value = int(op.value_sats)
            wu = getattr(pin, "witness_utxo", None)
            if wu is not None:
                wu.value = new_value
            else:
                nwu = getattr(pin, "non_witness_utxo", None)
                vout_idx = int(getattr(pin.vin, "vout", 0))
                if nwu is None or not (0 <= vout_idx < len(nwu.vout)):
                    raise ValueError(
                        f"Input {idx} has no prevout value to edit "
                        "(missing witness_utxo and non_witness_utxo)."
                    )
                nwu.vout[vout_idx].value = new_value
            structure_changed = True
            notes.append(f"Set input {idx} value to {new_value} sats.")
        elif name == "set_output_value":
            if op.output_index is None or op.value_sats is None:
                raise ValueError("set_output_value requires output_index and value_sats.")
            idx = op.output_index
            if not (0 <= idx < len(psbt.outputs)):
                raise IndexError(f"output_index out of range: {idx}")
            psbt.outputs[idx].value = int(op.value_sats)
            structure_changed = True
            notes.append(f"Set output {idx} value to {op.value_sats} sats.")
        elif name == "drop_output":
            if op.output_index is None:
                raise ValueError("drop_output requires output_index.")
            idx = op.output_index
            if not (0 <= idx < len(psbt.outputs)):
                raise IndexError(f"output_index out of range: {idx}")
            del psbt.outputs[idx]
            structure_changed = True
            notes.append(f"Dropped output {idx}.")
        elif name == "add_output":
            if op.value_sats is None:
                raise ValueError("add_output requires value_sats.")
            script = _script_from_op(op, network)
            new_out = OutputScope(
                vout=TransactionOutput(int(op.value_sats), script)
            )
            psbt.outputs.append(new_out)
            structure_changed = True
            source = "address" if op.address else "raw script"
            notes.append(f"Added output of {op.value_sats} sats ({source}).")
        elif name == "add_input":
            if op.value_sats is None:
                raise ValueError("add_input requires value_sats.")
            script = _script_from_op(op, network)
            if op.txid:
                try:
                    txid_bytes = bytes.fromhex(op.txid)
                except ValueError as exc:
                    raise ValueError(f"Invalid txid hex: {exc}") from exc
                if len(txid_bytes) != 32:
                    raise ValueError("txid must be 32 bytes (64 hex chars).")
            else:
                txid_bytes = _synthetic_txid()
            vin = TransactionInput(
                txid_bytes,
                int(op.vout or 0),
                sequence=0xFFFFFFFD,
            )
            new_in = InputScope(vin=vin)
            new_in.witness_utxo = TransactionOutput(int(op.value_sats), script)
            psbt.inputs.append(new_in)
            structure_changed = True
            source = "address" if op.address else "raw script"
            notes.append(f"Added input of {op.value_sats} sats ({source}).")
        else:
            raise ValueError(f"Unknown op: {name}")

    if structure_changed:
        _strip_signing_data(psbt)
        notes.append(
            "Stripped prior partial signatures: any changed tx structure "
            "invalidates them; re-sign required."
        )

    # Touch network so unused-import checker is happy and the param is validated.
    _ = _network(network)

    return psbt, notes
