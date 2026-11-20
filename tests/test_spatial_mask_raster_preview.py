"""Spatial mask raster cache + preview edge clamp (#508 / #506)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from orga_drone.studio_image import ImageAdjust
from orga_drone.studio_lut import ColorLook
from orga_drone.studio_managed_apply import apply_managed_grade_image
from orga_drone.studio_managed_selection import (
    evaluate_selection,
    rasterize_selection_coverage,
)
from orga_drone.studio_preview_frame import (
    PREVIEW_MAX_EDGE,
    SPATIAL_PREVIEW_MAX_EDGE,
    PreviewFrameRequest,
    cache_key_for,
    render_preview_frame,
)


def _brush_grade() -> dict:
    strokes = [
        {
            "mode": "add",
            "radius": 0.08,
            "hardness": 0.7,
            "points": [[0.4, 0.4], [0.5, 0.5], [0.6, 0.55]],
        }
    ]
    return {
        "schema_version": 1,
        "evaluator": "managed-sdr-v1",
        "revision": 1,
        "input": {"profile": "bt709-sdr", "technical_lut": None},
        "working": "linear-bt709",
        "steps": [
            {
                "id": "p1",
                "type": "primaries-v1",
                "enabled": True,
                "mix": 1.0,
                "selection_id": "sel-a",
                "params": {
                    "exposure": 0.0,
                    "kelvin": 6500,
                    "tint": 0,
                    "contrast": 1.0,
                    "pivot": 0.18,
                    "saturation": 0.0,
                    "blacks": 0,
                    "shadows": 0,
                    "highlights": 0,
                    "whites": 0,
                },
            }
        ],
        "selections": [
            {
                "id": "sel-a",
                "invert": False,
                "mask": {
                    "combine": "union",
                    "leaves": [{"type": "brush", "feather": 0.02, "strokes": strokes}],
                },
                "qualifier": {"type": "none"},
            }
        ],
        "animation": [],
        "output": {"profile": "bt709-sdr", "gamut": "clip"},
        "extensions": {},
    }


def test_rasterize_selection_matches_evaluate_selection() -> None:
    from orga_drone.studio_managed_selection import BRUSH_STAMP_TOLERANCE

    selection = _brush_grade()["selections"][0]
    width, height = 48, 36
    raster = rasterize_selection_coverage(selection, width=width, height=height)
    for y in range(height):
        for x in range(width):
            uv = ((x + 0.5) / width, (y + 0.5) / height)
            expected = evaluate_selection(selection, point=uv, rgb=(0.5, 0.5, 0.5))
            # Stamp raster (#525) may diverge in the soft band within tolerance.
            assert abs(raster[y * width + x] - expected) <= BRUSH_STAMP_TOLERANCE + 1e-6


def test_apply_managed_grade_image_matches_per_pixel_path() -> None:
    from orga_drone.studio_managed_selection import BRUSH_STAMP_TOLERANCE

    grade = _brush_grade()
    width = height = 24
    pixels = [
        [((x / 23.0), (y / 23.0), 0.25) for x in range(width)] for y in range(height)
    ]
    out = apply_managed_grade_image(pixels, grade, lattice_domain="encoded-bt709")
    # Spot-check vs analytic evaluate path; stamp raster may differ within tolerance.
    from orga_drone.studio_managed_apply import apply_managed_grade_rgb

    for y, x in ((0, 0), (12, 12), (23, 23)):
        uv = ((x + 0.5) / width, (y + 0.5) / height)
        direct = apply_managed_grade_rgb(
            pixels[y][x], grade, lattice_domain="encoded-bt709", uv=uv
        )
        assert all(
            abs(a - b) <= BRUSH_STAMP_TOLERANCE + 1e-5
            for a, b in zip(out[y][x], direct, strict=True)
        )


def test_spatial_preview_clamps_max_edge(tmp_path: Path) -> None:
    import json
    from dataclasses import replace

    from orga_drone.studio_managed_apply import grade_needs_cpu_materialize

    photo = tmp_path / "leaf.jpg"
    Image.new("RGB", (900, 1600), (80, 60, 40)).save(photo, quality=90)
    grade = _brush_grade()
    effect_settings = json.dumps({"grade": grade})

    req = PreviewFrameRequest(
        media_path=photo,
        kind="photo",
        source_time_s=0.0,
        image=ImageAdjust(),
        look=ColorLook(),
        max_edge=PREVIEW_MAX_EDGE,
        effect_settings=effect_settings,
    )
    assert grade_needs_cpu_materialize(req.effect_settings)
    assert SPATIAL_PREVIEW_MAX_EDGE < PREVIEW_MAX_EDGE
    clamped = replace(req, max_edge=min(req.max_edge, SPATIAL_PREVIEW_MAX_EDGE))
    key_full = cache_key_for(req, media_mtime_ns=1, media_size=1, data_dir=tmp_path)
    key_clamped = cache_key_for(
        clamped, media_mtime_ns=1, media_size=1, data_dir=tmp_path
    )
    assert key_full != key_clamped

    # render_preview_frame itself clamps when max_edge is still 1080.
    out = render_preview_frame(req, data_dir=tmp_path, cache_dir=tmp_path / "prev")
    with Image.open(out) as img:
        assert max(img.size) <= SPATIAL_PREVIEW_MAX_EDGE + 1
