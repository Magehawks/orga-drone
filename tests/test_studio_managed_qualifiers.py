"""Qualifier intervals, gray rejection and eyedropper metadata (#357)."""

from __future__ import annotations

import pytest

from orga_drone.studio_managed_qualifiers import (
    ManagedQualifierError,
    eyedropper_sample,
    hsl_qualifier,
    luma_qualifier,
    rgb_qualifier,
    selection_coverage,
    step_blend,
)


def test_rgb_hsl_luma_and_gray_gate() -> None:
    red = (1.0, 0.0, 0.0)
    # Intervals are (inner fully selected, outer zero). High red uses inner=1.
    assert rgb_qualifier(red, ((1.0, 0.8), (0.0, 0.2), (0.0, 0.2))) == 1.0
    assert rgb_qualifier(red, ((0.0, 0.2), (0.0, 0.2), (0.0, 0.2))) == 0.0
    assert hsl_qualifier(red, hue=(0.0, 40.0)) == 1.0
    assert hsl_qualifier((0.5, 0.5, 0.5), hue=(0.0, 60.0)) == 0.0
    assert luma_qualifier(red, 0.2126, 0.05) == 1.0
    assert selection_coverage(1.0, 0.5, invert=True) == pytest.approx(0.5)
    blended = step_blend(red, (0.0, 1.0, 0.0), mix=1.0, coverage=0.5)
    assert blended == pytest.approx((0.5, 0.5, 0.0))


def test_eyedropper_is_read_only_metadata() -> None:
    sample = eyedropper_sample(
        (0.2, 0.4, 0.6),
        frame=12,
        revision=3,
        domain="bt709",
        neighborhood=(0.1, 0.1, 0.2, 0.2),
    )
    assert sample["frame"] == 12
    assert sample["revision"] == 3
    assert sample["domain"] == "bt709"
    assert sample["rgb"] == (0.2, 0.4, 0.6)
    with pytest.raises(ManagedQualifierError):
        eyedropper_sample(
            (0.2, 0.4, 0.6),
            frame=1,
            revision=1,
            domain="hdr",
            neighborhood=(0.0, 0.0, 1.0, 1.0),
        )
