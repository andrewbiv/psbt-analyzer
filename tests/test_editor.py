import base64

from embit.psbt import PSBT

from psbt_tool.core.editor import apply_ops
from psbt_tool.core.models import EditOp
from psbt_tool.core.parser import analyze_psbt, build_report
from psbt_tool.core.scripts import ScriptType

from .fixtures import P2WPKH_2, mixed_type_psbt, segwit_two_output_psbt


def _decode(b64: str) -> PSBT:
    return PSBT.parse(base64.b64decode(b64))


def test_drop_input_reserialized_and_reanalyzed():
    b64 = mixed_type_psbt()
    psbt = _decode(b64)
    psbt, notes = apply_ops(psbt, [EditOp(op="drop_input", input_index=1)])
    report = build_report(psbt, network="mainnet")
    assert len(report.inputs) == 1
    assert report.inputs[0].script_type is ScriptType.P2WPKH
    assert any("Dropped input" in n for n in notes)


def test_set_output_value_updates_totals():
    b64 = segwit_two_output_psbt(input_value=200_000, pay_value=50_000, change_value=147_932)
    psbt = _decode(b64)
    psbt, _ = apply_ops(psbt, [EditOp(op="set_output_value", output_index=1, value_sats=140_000)])
    report = build_report(psbt, network="mainnet")
    assert report.fees.total_out_sats == 50_000 + 140_000
    assert report.fees.fee_sats == 10_000  # 200k - 190k


def test_drop_output():
    b64 = segwit_two_output_psbt()
    psbt = _decode(b64)
    psbt, _ = apply_ops(psbt, [EditOp(op="drop_output", output_index=0)])
    report = build_report(psbt, network="mainnet")
    assert len(report.outputs) == 1


def test_add_output_by_address():
    b64 = segwit_two_output_psbt()
    psbt = _decode(b64)
    psbt, _ = apply_ops(
        psbt,
        [EditOp(op="add_output", address=P2WPKH_2, value_sats=25_000)],
    )
    report = build_report(psbt, network="mainnet")
    assert len(report.outputs) == 3
    assert any(o.value_sats == 25_000 and o.address == P2WPKH_2 for o in report.outputs)


def test_set_input_value_updates_totals():
    b64 = segwit_two_output_psbt(input_value=200_000, pay_value=50_000, change_value=147_932)
    psbt = _decode(b64)
    psbt, notes = apply_ops(
        psbt, [EditOp(op="set_input_value", input_index=0, value_sats=250_000)]
    )
    report = build_report(psbt, network="mainnet")
    assert report.inputs[0].value_sats == 250_000
    assert report.fees.total_in_sats == 250_000
    # Outputs unchanged; fee grew by the same amount.
    assert report.fees.total_out_sats == 50_000 + 147_932
    assert any("Set input 0 value" in n for n in notes)


def test_add_input_by_address_appears_in_report():
    b64 = segwit_two_output_psbt()
    psbt = _decode(b64)
    psbt, notes = apply_ops(
        psbt,
        [EditOp(op="add_input", address=P2WPKH_2, value_sats=75_000)],
    )
    report = build_report(psbt, network="mainnet")
    assert len(report.inputs) == 2
    new_in = report.inputs[-1]
    assert new_in.script_type is ScriptType.P2WPKH
    assert new_in.value_sats == 75_000
    assert new_in.address == P2WPKH_2
    assert any("Added input" in n for n in notes)


def test_structure_change_strips_signatures(monkeypatch):
    # Build a PSBT and plant a fake partial sig and finalization so we can
    # check the editor strips them on structure-changing ops.
    _, report = analyze_psbt(psbt_base64=segwit_two_output_psbt())
    psbt = _decode(report.psbt_base64)
    pseudo_key = bytes.fromhex("02" + "11" * 32)
    psbt.inputs[0].partial_sigs = {pseudo_key: b"\x30\x45\x02\x21\x00"}
    psbt.inputs[0].final_scriptsig = b"\x00"
    psbt, notes = apply_ops(
        psbt, [EditOp(op="set_output_value", output_index=0, value_sats=40_000)]
    )
    assert psbt.inputs[0].partial_sigs == {}
    assert psbt.inputs[0].final_scriptsig is None
    assert any("Stripped prior partial signatures" in n for n in notes)
