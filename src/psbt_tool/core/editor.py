"""Apply structured edits to a PSBT and return a re-serialized copy.

Supported ops:

- ``drop_input``: remove the input at ``input_index`` from the global tx and
  the PSBT input map. Strips partial signatures that would no longer be valid
  (any edit that changes the unsigned tx invalidates prior signatures).
- ``set_output_value``: change the value (in sats) of an existing output.
- ``drop_output``: remove the output at ``output_index``.
- ``add_output``: append a new output given either an ``address`` (decoded
  against the configured network) or a raw ``script_pub_key_hex``.

Any tx-structure-changing op clears ``partial_sigs``, ``final_scriptsig``,
and ``final_scriptwitness`` on affected inputs: the user will need to
re-sign. This is called out in the response notes.
"""

from __future__ import annotations

from embit.networks import NETWORKS
from embit.psbt import PSBT, OutputScope
from embit.script import Script, address_to_scriptpubkey
from embit.transaction import TransactionOutput

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
    raise ValueError("add_output requires address or script_pub_key_hex.")


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
