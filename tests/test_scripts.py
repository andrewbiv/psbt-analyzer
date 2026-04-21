from psbt_tool.core.scripts import (
    ScriptType,
    classify_script_pubkey,
    estimate_tx_vsize,
    input_vsize,
    output_size,
    refine_p2sh_wrapping,
)


def test_classify_p2wpkh():
    spk = bytes.fromhex("0014751e76e8199196d454941c45d1b3a323f1433bd6")
    assert classify_script_pubkey(spk) is ScriptType.P2WPKH


def test_classify_p2tr():
    spk = bytes.fromhex("5120a60869f0dbcf1dc659c9cecbaf8050135ea9e8cdc487053f1dc6880949dc684c")
    assert classify_script_pubkey(spk) is ScriptType.P2TR


def test_classify_p2pkh():
    spk = bytes.fromhex("76a91477bff20c60e522dfaa3350c39b030a5d004e839a88ac")
    assert classify_script_pubkey(spk) is ScriptType.P2PKH


def test_classify_p2sh_then_refine():
    p2sh_spk = bytes.fromhex("a914" + "11" * 20 + "87")
    assert classify_script_pubkey(p2sh_spk) is ScriptType.P2SH
    redeem_p2wpkh = bytes.fromhex("0014" + "22" * 20)
    assert refine_p2sh_wrapping(ScriptType.P2SH, redeem_p2wpkh) is ScriptType.P2SH_P2WPKH
    redeem_p2wsh = bytes.fromhex("0020" + "33" * 32)
    assert refine_p2sh_wrapping(ScriptType.P2SH, redeem_p2wsh) is ScriptType.P2SH_P2WSH


def test_op_return_classified():
    assert classify_script_pubkey(b"\x6a\x04abcd") is ScriptType.OP_RETURN


def test_unknown_for_garbage():
    assert classify_script_pubkey(b"") is ScriptType.UNKNOWN
    assert classify_script_pubkey(b"\x00\x05foo") is ScriptType.UNKNOWN


def test_tx_vsize_segwit_discount():
    # Legacy > any segwit variant at whole-tx level; input vsize alone ranks
    # P2PKH > P2WPKH > P2TR as expected from the witness discount.
    legacy = estimate_tx_vsize([ScriptType.P2PKH], [ScriptType.P2PKH])
    segwit = estimate_tx_vsize([ScriptType.P2WPKH], [ScriptType.P2WPKH])
    taproot = estimate_tx_vsize([ScriptType.P2TR], [ScriptType.P2TR])
    assert legacy > segwit
    assert legacy > taproot
    assert input_vsize(ScriptType.P2PKH) > input_vsize(ScriptType.P2WPKH)
    assert input_vsize(ScriptType.P2WPKH) > input_vsize(ScriptType.P2TR)


def test_input_and_output_sizes_table():
    assert input_vsize(ScriptType.P2WPKH) == 68.0
    assert input_vsize(ScriptType.P2TR) == 57.5
    assert output_size(ScriptType.P2WPKH) == 31
    assert output_size(ScriptType.P2TR) == 43
