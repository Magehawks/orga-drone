"""Managed SDR transfer and LUT sampling. Legacy import and export stay untouched."""

from __future__ import annotations

import pytest

from orga_drone.studio_lut import parse_cube_text
from orga_drone.studio_managed_lut import (
    ManagedLutError,
    confirm_technical_lut,
    decode_bt709,
    decode_srgb,
    encode_bt709,
    encode_srgb,
    interpolation_order,
    lut_digest,
    parse_managed_cube,
    quantize_rgb8,
    require_managed_profile,
    sample_creative_lut,
    sample_lut,
)

VECTORS = (
    (0.0, 0.0, 0.0, 0, 0),
    (0.001, 0.012920000000, 0.004500000000, 3, 1),
    (0.010, 0.099852822734, 0.045000000000, 25, 11),
    (0.180, 0.461356129500, 0.409007728864, 118, 104),
    (0.500, 0.735356983052, 0.705515089922, 188, 180),
    (1.0, 1.0, 1.0, 255, 255),
)


def _cube(size: int, rows: list[tuple[float, float, float]], domain: str = "") -> str:
    body = "\n".join(f"{row[0]} {row[1]} {row[2]}" for row in rows)
    return f'TITLE "synthetic"\n{domain}LUT_3D_SIZE {size}\n{body}\n'


def test_transfer_vectors_match_the_published_reference() -> None:
    for linear, expected_s, expected_b, code_s, code_b in VECTORS:
        assert encode_srgb(linear) == pytest.approx(expected_s, abs=1e-9)
        assert encode_bt709(linear) == pytest.approx(expected_b, abs=1e-9)
        assert (quantize_rgb8(encode_srgb(linear)), quantize_rgb8(encode_bt709(linear))) == (
            code_s,
            code_b,
        )
        assert decode_srgb(encode_srgb(linear)) == pytest.approx(linear, abs=1e-12)
        assert decode_bt709(encode_bt709(linear)) == pytest.approx(linear, abs=1e-12)
        assert quantize_rgb8(encode_srgb(decode_bt709(encode_bt709(linear)))) == code_s
    assert 255 * (encode_srgb(0.18) - encode_bt709(0.18)) == pytest.approx(
        13.348842162254, abs=1e-9
    )
    assert quantize_rgb8(encode_srgb(decode_srgb(118 / 255))) == 118
    assert quantize_rgb8(encode_srgb(decode_bt709(104 / 255))) == 117
    assert encode_bt709(0.018) == pytest.approx(0.08124794403514046, abs=1e-12)
    assert decode_bt709(0.081) == pytest.approx(0.01794502336674779, abs=1e-12)
    assert encode_srgb(0.0031308) == pytest.approx(0.040449936, abs=1e-12)
    assert decode_srgb(0.04045) == pytest.approx(0.0031308049535603713, abs=1e-12)


def test_profiles_reject_untagged_hdr_and_log() -> None:
    assert require_managed_profile("sRGB") == "srgb"
    assert require_managed_profile("BT.709") == "bt709"
    assert require_managed_profile("Rec.709") == "bt709"
    for name in ("", "   ", "PQ", "HLG", "D-Log M", "HDR10", "camera"):
        with pytest.raises(ManagedLutError) as raised:
            require_managed_profile(name)
        assert raised.value.code == "UNSUPPORTED_INPUT_PROFILE"


def test_cube_parser_keeps_domain_and_rejects_unsupported_files() -> None:
    rows = [(0.0, 0.0, 0.0)] * 7 + [(1.0, 0.0, 0.0)]
    text = _cube(2, rows, domain="DOMAIN_MIN 0 0 0\nDOMAIN_MAX 2 2 2\n")
    parsed = parse_managed_cube(text, input_profile="srgb", output_profile="srgb")
    assert parsed.domain_max == (2.0, 2.0, 2.0)
    assert parsed.digest == lut_digest(text.encode("utf-8"))
    assert lut_digest(b"other") != parsed.digest
    with pytest.raises(ManagedLutError) as size:
        parse_managed_cube(_cube(1, [(0.0, 0.0, 0.0)]), input_profile="srgb", output_profile="bt709")
    assert size.value.code == "LUT_INVALID"
    with pytest.raises(ManagedLutError) as oned:
        parse_managed_cube("LUT_1D_SIZE 2\n0 0 0\n1 1 1\n", input_profile="srgb", output_profile="srgb")
    assert oned.value.code == "LUT_UNSUPPORTED"
    with pytest.raises(ManagedLutError):
        parse_managed_cube(
            "LUT_3D_SIZE 2\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 0 1 1\n" + "0 0 0\n" * 8,
            input_profile="bt709",
            output_profile="bt709",
        )
    legacy_size, _triples = parse_cube_text(text)
    assert legacy_size == 2


def test_tetrahedral_sample_and_tie_order() -> None:
    assert interpolation_order((0.5, 0.5, 0.2)) == (0, 1, 2)
    assert interpolation_order((0.2, 0.5, 0.5)) == (1, 2, 0)
    assert interpolation_order((0.4, 0.2, 0.4)) == (0, 2, 1)
    rows = [(0.0, 0.0, 0.0)] * 8
    rows[1] = (1.0, 0.0, 0.0)
    lut = parse_managed_cube(_cube(2, rows), input_profile="bt709", output_profile="bt709")
    assert sample_lut(lut, (0.25, 0.0, 0.0)) == pytest.approx((0.25, 0.0, 0.0))
    wide = parse_managed_cube(
        _cube(2, rows, domain="DOMAIN_MIN 0 0 0\nDOMAIN_MAX 2 1 1\n"),
        input_profile="bt709",
        output_profile="bt709",
    )
    assert sample_lut(wide, (0.5, 0.0, 0.0)) == pytest.approx((0.25, 0.0, 0.0))


def test_creative_strength_and_technical_confirmation() -> None:
    rows = [(0.0, 0.0, 1.0)] * 8
    lut = parse_managed_cube(_cube(2, rows), input_profile="srgb", output_profile="srgb")
    original = (2.0, -1.0, 0.2)
    assert sample_creative_lut(lut, original, 0.0) == original
    assert sample_creative_lut(lut, (1.0, 0.0, 0.0), 0.5) == pytest.approx((0.5, 0.0, 0.5))
    mismatched = parse_managed_cube(_cube(2, rows), input_profile="srgb", output_profile="bt709")
    with pytest.raises(ManagedLutError) as domain:
        sample_creative_lut(mismatched, (0.2, 0.2, 0.2), 1.0)
    assert domain.value.code == "LUT_DOMAIN"
    confirm_technical_lut(confirmed=True, already_applied=False)
    with pytest.raises(ManagedLutError) as unconfirmed:
        confirm_technical_lut(confirmed=False, already_applied=False)
    assert unconfirmed.value.code == "TECHNICAL_LUT_UNCONFIRMED"
    with pytest.raises(ManagedLutError) as twice:
        confirm_technical_lut(confirmed=True, already_applied=True)
    assert twice.value.code == "TECHNICAL_LUT_ONCE"
