"""Analytic fixtures for linear, radial and brush mattes (#356)."""

from __future__ import annotations

import pytest

from orga_drone.studio_managed_masks import (
    ManagedMaskError,
    brush_stroke_coverage,
    combine_coverages,
    invert_coverage,
    linear_coverage,
    no_selection_coverage,
    radial_coverage,
    step_blend,
)


def test_linear_and_radial_hard_and_feathered() -> None:
    # Upward y-axis: positive-x samples land on the negative side of the line.
    assert linear_coverage((0.2, 0.5), (0.0, 0.0), (0.0, 1.0), 0.0) == 1.0
    assert linear_coverage((-0.2, 0.5), (0.0, 0.0), (0.0, 1.0), 0.0) == 0.0
    assert linear_coverage((0.0, 0.5), (0.0, 0.0), (0.0, 1.0), 0.2) == pytest.approx(0.5)
    assert radial_coverage((0.5, 0.5), (0.5, 0.5), (0.25, 0.25), 0.0) == 1.0
    assert radial_coverage((0.75, 0.5), (0.5, 0.5), (0.25, 0.25), 0.0) == 1.0
    assert radial_coverage((1.0, 0.5), (0.5, 0.5), (0.25, 0.25), 0.0) == 0.0
    edge = radial_coverage((0.8125, 0.5), (0.5, 0.5), (0.25, 0.25), 0.5)
    assert 0.0 < edge < 1.0


def test_brush_combine_invert_and_blend() -> None:
    assert brush_stroke_coverage((0.1, 0.1), ((0.1, 0.1),), radius=0.2, hardness=1.0) == 1.0
    assert brush_stroke_coverage((0.5, 0.1), ((0.1, 0.1),), radius=0.2, hardness=0.5) == 0.0
    soft = brush_stroke_coverage(
        (0.25, 0.1),
        ((0.1, 0.1), (0.4, 0.1)),
        radius=0.2,
        hardness=0.0,
        pressure=0.5,
    )
    assert soft == pytest.approx(0.5)
    assert combine_coverages([], "union") == 0.0
    assert combine_coverages([0.8, 0.3], "union") == 0.8
    assert combine_coverages([0.8, 0.3], "intersection") == 0.3
    assert combine_coverages([0.8, 0.3], "subtraction") == pytest.approx(0.5)
    assert invert_coverage(0.25) == pytest.approx(0.75)
    assert no_selection_coverage() == 1.0
    blended = step_blend((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), mix=0.5, coverage=0.5)
    assert blended == pytest.approx((0.25, 0.0, 0.0))
    with pytest.raises(ManagedMaskError):
        combine_coverages([0.5], "xor")
