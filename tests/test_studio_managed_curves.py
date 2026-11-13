"""Identity, order, gray-gate and rejection tests for managed curves (#354)."""

from __future__ import annotations

import math

import pytest

from orga_drone.studio_managed_curves import (
    IDENTITY_CURVE,
    MAX_CURVE_POINTS,
    ManagedCurveError,
    hue_vs_hue,
    hue_vs_luma,
    hue_vs_saturation,
    luma_curve_v1,
    luma_vs_saturation,
    piecewise_linear,
    rgb_curves_v1,
    rgb_to_hsl,
    saturation_vs_saturation,
)


def test_rgb_and_luma_identities_and_order() -> None:
    rgb = (0.18, 0.5, 1.0)
    assert rgb_curves_v1(rgb) == pytest.approx(rgb)
    assert luma_curve_v1(rgb) == pytest.approx(rgb)
    master = ((0.0, 0.0), (1.0, 0.5))
    channel = ((0.0, 0.0), (1.0, 0.25))
    # Master first: 0.4 -> 0.2, then channel: 0.2 -> 0.05.
    assert rgb_curves_v1((0.4, 0.4, 0.4), master, (channel, channel, channel)) == pytest.approx(
        (0.05, 0.05, 0.05)
    )
    lifted = ((0.0, 0.1), (1.0, 1.1))
    expected = tuple(channel + 0.1 for channel in rgb)
    assert luma_curve_v1(rgb, lifted) == pytest.approx(expected)
    assert piecewise_linear(((0.0, 0.0), (1.0, 1.0)), -0.5) == pytest.approx(-0.5)
    assert piecewise_linear(((0.0, 0.0), (1.0, 1.0)), 1.5) == pytest.approx(1.5)


def test_hue_curves_wrap_and_gray_bypass() -> None:
    red = (1.0, 0.0, 0.0)
    rotated = hue_vs_hue(red, ((0.0, 90.0), (360.0, 90.0)))
    hue, _saturation, _lightness = rgb_to_hsl(rotated)
    assert hue == pytest.approx(90.0, abs=1e-6)
    gray = (0.5, 0.5, 0.5)
    for operation in (hue_vs_hue, hue_vs_saturation, hue_vs_luma):
        assert operation(gray, ((0.0, 90.0), (360.0, 90.0))) == gray
    boosted = hue_vs_saturation(red, ((0.0, 0.5), (360.0, 0.5)))
    assert rgb_to_hsl(boosted)[1] == pytest.approx(0.5)
    raised = hue_vs_luma(red, ((0.0, 0.1), (360.0, 0.1)))
    assert rgb_to_hsl(raised)[2] == pytest.approx(0.6)


def test_saturation_curves_and_rejections() -> None:
    red = (1.0, 0.0, 0.0)
    cut = saturation_vs_saturation(red, ((0.0, 0.0), (1.0, 0.25)))
    assert rgb_to_hsl(cut)[1] == pytest.approx(0.25)
    # Neutral multiplier is y=1, not the RGB identity [(0,0),(1,1)].
    muted = luma_vs_saturation(red, ((0.0, 1.0), (1.0, 1.0)))
    assert muted == pytest.approx(red)
    with pytest.raises(ManagedCurveError) as duplicate:
        piecewise_linear(((0.0, 0.0), (0.0, 1.0)), 0.5)
    assert duplicate.value.code == "CURVE"
    with pytest.raises(ManagedCurveError):
        piecewise_linear(((0.0, math.nan), (1.0, 1.0)), 0.5)
    with pytest.raises(ManagedCurveError):
        rgb_curves_v1(
            red,
            tuple((float(index), float(index)) for index in range(MAX_CURVE_POINTS + 1)),
        )
    with pytest.raises(ManagedCurveError):
        hue_vs_hue(red, ((0.0, 10.0), (180.0, 20.0), (360.0, 30.0)))
