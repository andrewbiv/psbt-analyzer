from psbt_tool.core.heuristics import annotate_change
from psbt_tool.core.parser import analyze_psbt
from psbt_tool.core.scripts import ScriptType

from .fixtures import (
    P2PKH,
    P2WPKH_1,
    legacy_psbt,
    mixed_type_psbt,
    segwit_two_output_psbt,
    taproot_psbt,
    unknown_input_value_psbt,
)


def test_segwit_psbt_basic_fields():
    psbt_b64 = segwit_two_output_psbt(input_value=200_000, pay_value=50_000, change_value=147_932)
    _, report = analyze_psbt(psbt_base64=psbt_b64)
    assert report.fees.total_in_sats == 200_000
    assert report.fees.total_out_sats == 197_932
    assert report.fees.fee_sats == 2_068
    assert report.fees.unknown_inputs == 0
    assert report.fees.fee_rate_sat_vb and report.fees.fee_rate_sat_vb > 0
    assert len(report.inputs) == 1
    assert report.inputs[0].script_type is ScriptType.P2WPKH
    assert report.inputs[0].address == P2WPKH_1
    assert report.outputs[0].script_type is ScriptType.P2WPKH


def test_taproot_psbt():
    _, report = analyze_psbt(psbt_base64=taproot_psbt())
    assert report.inputs[0].script_type is ScriptType.P2TR
    # Taproot key-path spend must be lighter than segwit in vsize.
    assert report.inputs[0].vsize < 70


def test_legacy_psbt_uses_non_witness_utxo():
    _, report = analyze_psbt(psbt_base64=legacy_psbt(input_value=100_000, pay_value=90_000))
    assert report.inputs[0].script_type is ScriptType.P2PKH
    assert report.inputs[0].address == P2PKH
    assert report.inputs[0].value_source == "non_witness_utxo"
    assert report.fees.fee_sats == 10_000


def test_unknown_input_value_is_reported():
    _, report = analyze_psbt(psbt_base64=unknown_input_value_psbt())
    assert report.fees.unknown_inputs == 1
    assert report.fees.total_in_sats is None
    assert report.fees.fee_sats is None
    assert any("missing prevout value" in w for w in report.warnings)


def test_mixed_input_types_summary():
    _, report = analyze_psbt(psbt_base64=mixed_type_psbt())
    types = [i.script_type for i in report.inputs]
    assert ScriptType.P2WPKH in types and ScriptType.P2TR in types
    assert "P2WPKH" in report.script_mix_note
    assert "P2TR" in report.script_mix_note


def test_change_heuristic_prefers_same_type_non_round():
    _, report = analyze_psbt(psbt_base64=segwit_two_output_psbt())
    annotate_change(report)
    change = [o for o in report.outputs if o.is_change_candidate]
    assert len(change) == 1
    # Payment is round (50_000) and change is non-round (147_932); the heuristic
    # should select the non-round, same-type output as change.
    assert change[0].value_sats == 147_932


def test_psbt_base64_round_trip():
    b64 = segwit_two_output_psbt()
    _, report = analyze_psbt(psbt_base64=b64)
    # Re-serialize via the report
    _, report2 = analyze_psbt(psbt_base64=report.psbt_base64)
    assert report2.fees.fee_sats == report.fees.fee_sats
