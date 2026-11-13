"""Neutral, extreme and serial composition tests for wheels/HSL (#355)."""

from __future__ import annotations

import pytest

from orga_drone.studio_managed_wheels import (
    ManagedWheelsError,
    compose_serial,
    managed_hsl,
    rgb_to_hsl,
    wheels_v1,
)


def test_wheels_neutral_and_extremes() -> None:
    rgb = (0.18, 0.5, 1.0)
    assert wheels_v1(rgb) == pytest.approx(rgb)
    assert wheels_v1((0.25, 0.25, 0.25), gain=2.0) == pytest.approx((0.5, 0.5, 0.5))
    assert wheels_v1((-0.5, 0.0, 0.5), gamma=2.0) == pytest.approx(
        (-(0.5**0.5), 0.0, 0.5**0.5)
    )
    lifted = wheels_v1(rgb, lift=0.1, offset=-0.05)
    assert lifted == pytest.approx((0.23, 0.55, 1.05))
    with pytest.raises(ManagedWheelsError):
        wheels_v1(rgb, gamma=0.0)
    with pytest.raises(ManagedWheelsError):
        wheels_v1(rgb, gain=-0.1)


def test_managed_hsl_and_serial_composition() -> None:
    red = (1.0, 0.0, 0.0)
    assert managed_hsl(red) == pytest.approx(red)
    shifted = managed_hsl(red, hue_offset_deg=120.0)
    assert rgb_to_hsl(shifted)[0] == pytest.approx(120.0, abs=1e-6)
    desat = managed_hsl(red, saturation_mult=0.0)
    assert desat == pytest.approx((0.5, 0.5, 0.5))
    composed = compose_serial(
        (0.25, 0.25, 0.25),
        (
            ("wheels-v1", {"gain": 2.0}),
            ("managed-hsl-v1", {"lightness_offset": -0.1}),
        ),
    )
    assert composed == pytest.approx((0.4, 0.4, 0.4))
    with pytest.raises(ManagedWheelsError) as raised:
        compose_serial(red, (("unknown-v1", {}),))
    assert raised.value.code == "UNSUPPORTED"
