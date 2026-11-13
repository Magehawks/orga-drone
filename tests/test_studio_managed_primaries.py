"""Identity, range, and published Kelvin/tint + tone-control mapping checks."""

from __future__ import annotations

import pytest

from orga_drone.studio_managed_primaries import (
    KELVIN_TINT_MAPPING,
    TONE_CONTROLS_MAPPING,
    PrimariesError,
    apply_primaries,
    apply_tone_curve,
    kelvin_tint_to_gains,
    linear_luma,
    primaries_balance,
    primaries_contrast,
    primaries_exposure,
    primaries_saturation,
    tone_controls_to_curve,
)

KELVIN_TINT_VECTORS = (
    (6500.0, 0.0, (1.0, 1.0, 1.0)),
    (5000.0, 0.0, (1.0, 0.897298118, 0.82358362)),
    (8000.0, 0.0, (0.867508429, 0.904289926, 1.019829043)),
    (6500.0, 50.0, (0.875, 1.25, 0.875)),
    (6500.0, -50.0, (1.125, 0.75, 1.125)),
)


def test_identities_and_known_values() -> None:
    rgb = (0.18, 0.5, 1.0)
    assert primaries_exposure(rgb, 0.0) == pytest.approx(rgb)
    assert primaries_balance(rgb, (1.0, 1.0, 1.0)) == pytest.approx(rgb)
    assert primaries_contrast(rgb, 1.0, 0.18) == pytest.approx(rgb)
    assert primaries_saturation(rgb, 1.0) == pytest.approx(rgb)
    assert primaries_contrast((0.4, 0.0, -0.4), 0.0, 0.25) == pytest.approx((0.25, 0.0, -0.25))
    assert primaries_exposure((0.25, 0.25, 0.25), 1.0) == pytest.approx((0.5, 0.5, 0.5))
    collapsed = primaries_saturation(rgb, 0.0)
    assert collapsed == pytest.approx((collapsed[0], collapsed[0], collapsed[0]))
    assert primaries_saturation((0.25, 0.25, 0.25), 2.0) == pytest.approx((0.25, 0.25, 0.25))


def test_ranges_and_balance_keep_luma() -> None:
    with pytest.raises(PrimariesError):
        primaries_exposure((0.5, 0.5, 0.5), 10.5)
    with pytest.raises(PrimariesError):
        primaries_balance((0.5, 0.5, 0.5), (0.0, 1.0, 1.0))
    with pytest.raises(PrimariesError):
        primaries_contrast((0.5, 0.5, 0.5), 4.5, 0.18)
    with pytest.raises(PrimariesError):
        primaries_saturation((0.5, 0.5, 0.5), 4.5)
    gray = (0.5, 0.5, 0.5)
    balanced = primaries_balance(gray, (1.0, 2.0, 1.0))
    assert linear_luma(balanced) == pytest.approx(linear_luma(gray))
    assert balanced[1] > gray[1] > balanced[0]
    assert balanced[1] > gray[1] > balanced[2]


def test_tone_curve_and_serial_order() -> None:
    gray = (0.2, 0.2, 0.2)
    assert apply_tone_curve(gray, ((0.0, 0.0), (1.0, 0.5))) == pytest.approx((0.1, 0.1, 0.1))
    with pytest.raises(PrimariesError) as raised:
        apply_tone_curve(gray, ((0.0, 0.0), (0.4, 0.8), (1.0, 0.2)))
    assert raised.value.code == "CURVE"
    doubled = apply_primaries((0.25, 0.25, 0.25), exposure=1.0)
    assert doubled == pytest.approx((0.5, 0.5, 0.5))
    identity = apply_primaries((0.18, 0.5, 1.0))
    assert identity == pytest.approx((0.18, 0.5, 1.0))


def test_kelvin_tint_mapping_vectors() -> None:
    assert KELVIN_TINT_MAPPING == "kelvin-tint-v1"
    for kelvin, tint, expected in KELVIN_TINT_VECTORS:
        assert kelvin_tint_to_gains(kelvin, tint) == pytest.approx(expected, abs=1e-9)
    gray = (0.5, 0.5, 0.5)
    warmed = apply_primaries(gray, kelvin=5000.0)
    assert linear_luma(warmed) == pytest.approx(linear_luma(gray))
    with pytest.raises(PrimariesError):
        kelvin_tint_to_gains(1000.0, 0.0)
    with pytest.raises(PrimariesError):
        kelvin_tint_to_gains(6500.0, 120.0)


def test_tone_controls_mapping_vectors() -> None:
    assert TONE_CONTROLS_MAPPING == "tone-controls-v1"
    assert tone_controls_to_curve() == ((0.0, 0.0), (1.0, 1.0))
    curve = tone_controls_to_curve(blacks=40, shadows=20, highlights=-10, whites=15)
    expected = ((0.0, 0.1), (0.25, 0.29), (0.5, 0.505), (0.75, 0.73), (1.0, 1.0375))
    assert len(curve) == len(expected)
    for actual_point, expected_point in zip(curve, expected, strict=True):
        assert actual_point == pytest.approx(expected_point)
    lifted = apply_primaries((0.1, 0.1, 0.1), blacks=40)
    assert lifted[0] > 0.1
    with pytest.raises(PrimariesError):
        tone_controls_to_curve(blacks=101)
