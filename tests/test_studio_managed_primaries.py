"""Identity and range checks for primaries-v1. No Kelvin or tonal-slider mapping."""

from __future__ import annotations

import pytest

from orga_drone.studio_managed_primaries import (
    PrimariesError,
    apply_primaries,
    apply_tone_curve,
    linear_luma,
    primaries_balance,
    primaries_contrast,
    primaries_exposure,
    primaries_saturation,
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
