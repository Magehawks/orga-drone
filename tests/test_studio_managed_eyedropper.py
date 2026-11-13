"""Eyedropper sample + qualifier suggestion (#357)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from orga_drone.studio_managed_eyedropper import (
    ManagedEyedropperError,
    apply_sample_to_selection,
    build_eyedropper_payload,
    qualifier_ranges_from_sample,
    sample_preview_jpeg,
)


def _jpeg(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (40, 40)) -> Path:
    Image.new("RGB", size, color).save(path, format="JPEG", quality=95)
    return path


def test_sample_preview_jpeg_center(tmp_path: Path) -> None:
    path = _jpeg(tmp_path / "frame.jpg", (200, 40, 40))
    rgb, box, size = sample_preview_jpeg(path, u=0.5, v=0.5, neighborhood=0.0)
    assert size == (40, 40)
    assert abs(rgb[0] - 200 / 255) < 0.05
    assert box[0] <= 0.5 <= box[2]


def test_invalid_uv_rejected(tmp_path: Path) -> None:
    path = _jpeg(tmp_path / "frame.jpg", (10, 10, 10))
    with pytest.raises(ManagedEyedropperError) as exc:
        sample_preview_jpeg(path, u=1.5, v=0.2)
    assert exc.value.code == "RANGE"


def test_qualifier_ranges_and_payload() -> None:
    rgb = (0.8, 0.2, 0.1)
    suggested = qualifier_ranges_from_sample(rgb, domain="srgb", kind="rgb")
    assert suggested["type"] == "rgb"
    payload = build_eyedropper_payload(
        rgb=rgb,
        frame=12,
        revision=3,
        domain="srgb",
        neighborhood=(0.4, 0.4, 0.6, 0.6),
        source_time_s=1.25,
        size=(64, 48),
    )
    assert payload["revision"] == 3
    assert payload["suggested"]["hsl"]["type"] == "hsl"
    assert payload["source_time_s"] == 1.25


def test_apply_sample_does_not_require_mask_leaves() -> None:
    selection = apply_sample_to_selection(
        {"id": "sel-1"},
        {"type": "luma", "inner": 0.5, "outer": 0.1},
    )
    assert selection["id"] == "sel-1"
    assert selection["qualifier"]["type"] == "luma"
