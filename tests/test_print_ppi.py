"""Effective PPI helper for print-size guidance (issue #450)."""

from __future__ import annotations

import pytest

from orga_drone.export.print_ppi import (
    aspect_ratio_mismatch,
    effective_ppi,
    orient_print_size,
    print_size_presets_payload,
)


def test_effective_ppi_known_values() -> None:
    # 3840×2160 on a 40×30 cm landscape print → 30 cm = 11.811 in short side.
    ppi = effective_ppi(3840, 2160, 300, 400)
    assert ppi == pytest.approx(2160 / (300 / 25.4), rel=1e-6)


def test_orient_print_size_matches_image_long_side() -> None:
    assert orient_print_size(4000, 3000, 200, 300) == (300.0, 200.0)
    assert orient_print_size(3000, 4000, 200, 300) == (200.0, 300.0)


def test_aspect_mismatch_detects_different_ratio() -> None:
    assert aspect_ratio_mismatch(4000, 3000, 210, 297) is True
    assert aspect_ratio_mismatch(3000, 2000, 300, 200) is False


def test_print_size_presets_payload_stable_ids() -> None:
    rows = print_size_presets_payload()
    ids = [row["id"] for row in rows]
    assert "a4" in ids
    assert "20x30cm" in ids
    assert all(float(row["width_mm"]) > 0 and float(row["height_mm"]) > 0 for row in rows)


def test_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        effective_ppi(0, 1080, 100, 150)
