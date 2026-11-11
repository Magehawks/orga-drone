"""Verify the independent Color Workspace reference math against the vectors
published in docs/architecture/COLOR_WORKSPACE_REVIEW_EVIDENCE.md.

These are arithmetic contract checks (OpenCode evidence lane). They do not
measure any production pipeline and cannot pass L320 or the managed gate.
"""

from __future__ import annotations

import math

import pytest

from tests.color_workspace_reference import (
    CubeLut,
    combine_mask_leaves,
    decode_bt709,
    decode_srgb,
    elliptical_radius,
    encode_bt709,
    encode_srgb,
    hue_vs_hue,
    hue_vs_luma,
    hue_vs_saturation,
    intersection,
    luma_curve_v1,
    linear_mask_coverage,
    parse_cube_text,
    piecewise_linear,
    primaries_balance,
    primaries_contrast,
    primaries_exposure,
    primaries_saturation,
    q8,
    radial_mask_coverage,
    rgb_curves_v1,
    rgb_to_hsl,
    sample_creative_lut,
    sample_lut,
    shortest_hue_offset,
    signed_distance_to_line,
    smoothstep,
    step_blend,
    subtraction,
    union,
    wheels_v1,
)


# ---------------------------------------------------------------------------
# Published transfer reference vectors (tolerance 1e-9, codes exact)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "linear,expected_s,expected_b,code_s,code_b",
    [
        (0.0, 0.0, 0.0, 0, 0),
        (0.001, 0.012920000000, 0.004500000000, 3, 1),
        (0.010, 0.099852822734, 0.045000000000, 25, 11),
        (0.180, 0.461356129500, 0.409007728864, 118, 104),
        (0.500, 0.735356983052, 0.705515089922, 188, 180),
        (1.0, 1.0, 1.0, 255, 255),
    ],
)
def test_published_transfer_vectors(
    linear: float, expected_s: float, expected_b: float, code_s: int, code_b: int
) -> None:
    assert abs(encode_srgb(linear) - expected_s) <= 1e-9
    assert abs(encode_bt709(linear) - expected_b) <= 1e-9
    assert (q8(encode_srgb(linear)), q8(encode_bt709(linear))) == (code_s, code_b)
    assert abs(decode_srgb(encode_srgb(linear)) - linear) <= 1e-12
    assert abs(decode_bt709(encode_bt709(linear)) - linear) <= 1e-12
    assert q8(encode_srgb(decode_bt709(encode_bt709(linear)))) == code_s


def test_gray_negative_control_is_invalid_boundary() -> None:
    """Raw S(.18) vs B(.18) differs by ~13.348842 RGB8 levels: comparing
    mismatched presentation codes is INVALID_MANAGED_BOUNDARY, not color
    failure. After inverse transfer + common S encoding both are Q8 118."""
    raw_difference = 255 * (encode_srgb(0.18) - encode_bt709(0.18))
    assert math.isclose(raw_difference, 13.348842162254, abs_tol=1e-9)
    assert q8(encode_bt709(0.18)) == 104 and q8(encode_srgb(0.18)) == 118
    assert q8(encode_srgb(decode_bt709(encode_bt709(0.18)))) == 118


def test_readback_quantization_residual_is_retained() -> None:
    """Pre-quantized BT.709 104/255 normalizes to 117, not 118: the one-code
    quantization error must be retained, never hidden by ideal pixels."""
    assert q8(encode_srgb(decode_bt709(104 / 255))) == 117
    assert q8(encode_srgb(decode_srgb(118 / 255))) == 118


def test_toe_branch_discontinuities_are_literal() -> None:
    """Rounded standards constants have a small toe discontinuity; the
    contract forbids smoothing it."""
    assert abs(encode_bt709(0.018) - 0.08124794403514046) <= 1e-12
    assert abs(decode_bt709(0.081) - 0.01794502336674779) <= 1e-12
    assert abs(encode_srgb(0.0031308) - 0.040449936) <= 1e-12
    assert abs(decode_srgb(0.04045) - 0.0031308049535603713) <= 1e-12


# ---------------------------------------------------------------------------
# Published alpha reference vectors
# ---------------------------------------------------------------------------


def test_half_alpha_composite_vector() -> None:
    """50% coverage pre-composite taps composite to (0.09,0.25,0.5); the
    ideal final sRGB/Q8 output is (85,137,188); cross-stage alpha comparison
    (0.5 vs 1) is invalid, not an alpha failure."""
    rgb, alpha = (0.18, 0.5, 1.0), 0.5
    composited = tuple(alpha * channel for channel in rgb)
    assert composited == (0.09, 0.25, 0.5)
    export_encoded = tuple(encode_bt709(channel) for channel in composited)
    export_linear = tuple(decode_bt709(channel) for channel in export_encoded)
    expected_codes = tuple(q8(encode_srgb(channel)) for channel in export_linear)
    assert expected_codes == (85, 137, 188)
    assert q8(1.0) == 255
    assert abs(alpha - 1.0) > 1 / 255


def test_transparent_pixel_vector() -> None:
    """Fully transparent taps composite to black; hidden RGB at alpha=0 is
    canonicalized away."""
    composited = tuple(0.0 * channel for channel in (0.18, 0.5, 1.0))
    assert composited == (0.0, 0.0, 0.0)
    assert tuple(q8(encode_srgb(channel)) for channel in composited) == (0, 0, 0)


def test_observed_readback_quantization_vector() -> None:
    """sRGB RGBA8 (118,188,255,128) decodes + composites to RGB8
    (85,138,188): the one-code green residual versus ideal (85,137,188)."""
    observed = tuple(decode_srgb(channel / 255) for channel in (118, 188, 255))
    final = tuple((128 / 255) * channel for channel in observed)
    codes = tuple(q8(encode_srgb(channel)) for channel in final)
    assert codes == (85, 138, 188)
    assert q8(0.5) == 128
    assert abs(128 / 255 - 0.5) <= 1 / 255


# ---------------------------------------------------------------------------
# Contract operation semantics (contract-derived, oracle-consistent)
# ---------------------------------------------------------------------------


def test_primaries_v1_order_and_identities() -> None:
    rgb = (0.18, 0.5, 1.0)
    assert primaries_exposure(rgb, 0.0) == pytest.approx(rgb)
    assert primaries_balance(rgb, (1.0, 1.0, 1.0)) == pytest.approx(rgb)
    assert primaries_contrast(rgb, 1.0, 0.18) == pytest.approx(rgb)
    assert primaries_saturation(rgb, 1.0) == pytest.approx(rgb)
    # k=0 maps positive inputs to +p, negative to -p, zero to 0.
    assert primaries_contrast((0.4, 0.0, -0.4), 0.0, 0.25) == pytest.approx(
        (0.25, 0.0, -0.25)
    )
    # Exposure doubles linear values per stop.
    assert primaries_exposure((0.25, 0.25, 0.25), 1.0) == pytest.approx((0.5, 0.5, 0.5))
    # Saturation s=0 collapses to luma (equal channels); s=2 keeps gray.
    gray = (0.25, 0.25, 0.25)
    collapsed = primaries_saturation(rgb, 0.0)
    assert collapsed == pytest.approx((collapsed[0],) * 3)
    assert primaries_saturation(gray, 2.0) == pytest.approx(gray)


def test_primaries_v1_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        primaries_exposure((0.5, 0.5, 0.5), 10.5)
    with pytest.raises(ValueError):
        primaries_balance((0.5, 0.5, 0.5), (0.0, 1.0, 1.0))
    with pytest.raises(ValueError):
        primaries_contrast((0.5, 0.5, 0.5), 4.5, 0.18)
    with pytest.raises(ValueError):
        primaries_saturation((0.5, 0.5, 0.5), 4.5)


def test_balance_normalizes_luma_weighted_gain() -> None:
    """A green gain of 2 must be scaled so the luma-weighted sum is 1:
    effective gains = (2*0.2126, 2*0.7152, 2*0.0722)/1 = (.4252, 1.4304, .1444)
    normalized to sum (weighted) 1... the identity check is that gray stays
    exactly as bright in luma terms."""
    gray = (0.5, 0.5, 0.5)
    out = primaries_balance(gray, (1.0, 2.0, 1.0))
    expected_luma = 0.2126 * 0.5 + 0.7152 * 0.5 + 0.0722 * 0.5
    actual_luma = (
        0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
    )
    assert actual_luma == pytest.approx(expected_luma)
    # G channel rises, R and B fall below their originals.
    assert out[1] > gray[1] > out[0] and out[1] > gray[1] > out[2]


def test_tone_and_luma_curves_share_the_contract_math() -> None:
    rgb = (0.18, 0.5, 1.0)
    identity = ((0.0, 0.0), (1.0, 1.0))
    assert luma_curve_v1(rgb, identity) == pytest.approx(rgb)
    lifted = ((0.0, 0.1), (1.0, 1.0))
    y = 0.2126 * 0.18 + 0.7152 * 0.5 + 0.0722 * 1.0
    expected = tuple(channel + (0.1 + y * 0.9 - y) for channel in rgb)
    assert luma_curve_v1(rgb, lifted) == pytest.approx(expected)


def test_rgb_curves_extrapolate_endpoint_segments() -> None:
    curve = ((0.0, 0.0), (1.0, 1.0))
    # Above 1: endpoint extension continues the last segment slope (1.0).
    assert piecewise_linear(curve, 1.5) == pytest.approx(1.5)
    # Master applies before channel curves.
    darkened = ((0.0, 0.0), (1.0, 0.5))
    out = rgb_curves_v1((0.4, 0.4, 0.4), darkened, (curve, curve, curve))
    assert out == pytest.approx((0.2, 0.2, 0.2))


def test_rgb_curves_reject_non_increasing_x() -> None:
    with pytest.raises(ValueError):
        piecewise_linear(((0.0, 0.0), (0.5, 0.5), (0.5, 0.7), (1.0, 1.0)), 0.4)


def test_wheels_v1_lift_gamma_gain_offset() -> None:
    assert wheels_v1((0.25, 0.5, 0.75)) == pytest.approx((0.25, 0.5, 0.75))
    # gain=2 doubles z before gamma: out = (x*2)^(1/1) = 2x for neutral gamma.
    assert wheels_v1((0.25, 0.25, 0.25), gain=2.0) == pytest.approx((0.5, 0.5, 0.5))
    # gamma=2 on 0.25: sqrt(0.25)=0.5.
    assert wheels_v1((0.25, 0.25, 0.25), gamma=2.0) == pytest.approx((0.5, 0.5, 0.5))
    # lift shifts pre-gain: (0.25+0.25)*1 = 0.5.
    assert wheels_v1((0.25, 0.25, 0.25), lift=0.25) == pytest.approx((0.5, 0.5, 0.5))
    # offset adds post-gain.
    assert wheels_v1((0.25, 0.25, 0.25), offset=0.25) == pytest.approx((0.5, 0.5, 0.5))
    # Negative input stays signed: sign-preserving power.
    assert wheels_v1((-0.25, -0.25, -0.25), gamma=2.0) == pytest.approx((-0.5, -0.5, -0.5))
    with pytest.raises(ValueError):
        wheels_v1((0.5, 0.5, 0.5), gamma=0.0)
    with pytest.raises(ValueError):
        wheels_v1((0.5, 0.5, 0.5), gain=-1.0)


def test_hue_curves_wrap_and_gray_bypass() -> None:
    assert shortest_hue_offset(10.0) == pytest.approx(10.0)
    assert shortest_hue_offset(350.0) == pytest.approx(-10.0)
    assert shortest_hue_offset(-350.0) == pytest.approx(10.0)
    # Saturated red shifted +90 degrees becomes hue 90.
    red = (1.0, 0.0, 0.0)
    out = hue_vs_hue(red, ((0.0, 90.0), (360.0, 90.0)))
    hue, _, _ = rgb_to_hsl(out)
    assert hue % 360.0 == pytest.approx(90.0)
    # Gray pixels bypass hue-based operations exactly.
    gray = (0.5, 0.5, 0.5)
    for operation in (hue_vs_hue, hue_vs_saturation, hue_vs_luma):
        assert operation(gray, ((0.0, 90.0), (360.0, 90.0))) == gray


def test_lut_parsing_and_tetrahedral_sampling() -> None:
    text = "\n".join(
        [
            'TITLE "oracle"',
            "DOMAIN_MIN 0.0 0.0 0.0",
            "DOMAIN_MAX 1.0 1.0 1.0",
            "LUT_3D_SIZE 2",
            "0 0 0",
            "1 0 0",
            "0 1 0",
            "1 1 0",
            "0 0 1",
            "1 0 1",
            "0 1 1",
            "1 1 1",
        ]
    )
    lut = parse_cube_text(text)
    assert lut.size == 2
    # Red-fastest: first triple is the red corner ramp.
    assert lut.data[1] == (1.0, 0.0, 0.0)
    # Midpoint of the unit cube in a 2x2x2 grid samples exactly halfway
    # between lattice corners via tetrahedral interpolation.
    assert sample_lut(lut, (0.5, 0.5, 0.5)) == pytest.approx((0.5, 0.5, 0.5))
    # Off-grid: (0.25,0.25,0.25) averages the cube between black and white.
    assert sample_lut(lut, (0.25, 0.25, 0.25)) == pytest.approx((0.25, 0.25, 0.25))
    # Domain clamp: outside values clamp into the declared domain.
    clamped = sample_lut(lut, (5.0, -5.0, 0.5))
    assert clamped == pytest.approx(sample_lut(lut, (1.0, 0.0, 0.5)))
    # Strength blend: 0 bypasses everything (identity, incl. domain clamp).
    assert sample_creative_lut(lut, (5.0, -5.0, 5.0), 0.0) == (5.0, -5.0, 5.0)
    assert sample_creative_lut(lut, (0.5, 0.5, 0.5), 1.0) == pytest.approx((0.5, 0.5, 0.5))
    with pytest.raises(ValueError):
        parse_cube_text(text.replace("LUT_3D_SIZE 2", "LUT_3D_SIZE 2\nLUT_3D_SIZE 2"))
    with pytest.raises(ValueError):
        parse_cube_text(text.replace("LUT_3D_SIZE 2", "LUT_1D_SIZE 2"))


def test_selection_mask_algebra_and_blend() -> None:
    point = (0.25, 0.5)
    # Hard linear mask: which side is "inside" follows the line orientation.
    # With the line running top->bottom at x=0.5, d<0 is the left side.
    inside = linear_mask_coverage(point, (0.5, 1.0), (0.5, 0.0), 0.0)
    outside = linear_mask_coverage((0.75, 0.5), (0.5, 1.0), (0.5, 0.0), 0.0)
    assert inside == 1.0 and outside == 0.0
    # Feathered coverage follows smoothstep(-f/2, f/2, d).
    feathered = linear_mask_coverage((0.5, 0.5), (0.5, 1.0), (0.5, 0.0), 0.4)
    distance = signed_distance_to_line((0.5, 0.5), (0.5, 1.0), (0.5, 0.0))
    assert feathered == pytest.approx(smoothstep(-0.2, 0.2, distance))
    # Radial hard/feathered coverage on elliptical radius.
    assert radial_mask_coverage((0.5, 0.5), (0.5, 0.5), (0.3, 0.3), 0.0) == 1.0
    assert radial_mask_coverage((1.5, 0.5), (0.5, 0.5), (0.3, 0.3), 0.0) == 0.0
    r = elliptical_radius((0.8, 0.5), (0.5, 0.5), (0.3, 0.3))
    assert radial_mask_coverage((0.8, 0.5), (0.5, 0.5), (0.3, 0.3), 0.2) == pytest.approx(
        1.0 - smoothstep(0.8, 1.2, r)
    )
    # Leaf algebra: union=max, intersection=min, subtraction=max(0,a-b).
    assert combine_mask_leaves([0.2, 0.7], union) == pytest.approx(0.7)
    assert combine_mask_leaves([0.2, 0.7], intersection) == pytest.approx(0.2)
    assert combine_mask_leaves([0.7, 0.2], subtraction) == pytest.approx(0.5)
    assert combine_mask_leaves([0.2, 0.7], subtraction) == 0.0
    # Step blend: C + m*q*(P-C).
    assert step_blend((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0.5, 0.5) == pytest.approx(
        (0.25, 0.25, 0.25)
    )
    assert step_blend((0.2, 0.2, 0.2), (0.8, 0.8, 0.8), 1.0, 0.0) == pytest.approx(
        (0.2, 0.2, 0.2)
    )


def test_cube_lut_dataclass_domain_defaults() -> None:
    lut = CubeLut(size=2, data=((0.0, 0.0, 0.0),) * 8)
    assert lut.domain_min == (0.0, 0.0, 0.0)
    assert lut.domain_max == (1.0, 1.0, 1.0)
