"""Neon Relic object-select coverage vs TARGET (#544/#550).

Requires local private fixtures via ORGA_NEON_RELIC_DIR or default worktree path.
Skipped in CI when fixtures are absent — never commits private media.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from orga_drone.studio_object_select import propose_object_polygon

_DEFAULT = Path(
    r"C:\Users\Niwes\Projects\orga-drone-wt\precision-mask-develop"
    r"\acceptance-evidence\neon-relic"
)


def _neon_paths() -> tuple[Path, Path] | None:
    root = Path(os.environ.get("ORGA_NEON_RELIC_DIR", str(_DEFAULT)))
    before = root / "00-before-original.jpg"
    target = root / "Magenta-Blatt-TARGET.jpg"
    if before.is_file() and target.is_file():
        return before, target
    return None


def _magenta_mask(path: Path, size: tuple[int, int]) -> list[bool]:
    im = Image.open(path).convert("RGB").resize(size, Image.Resampling.BILINEAR)
    out: list[bool] = []
    for r, g, b in im.getdata():
        out.append(
            r > 90 and b > 70 and g < r * 0.85 and ((r + b) / 2 - g) > 25
        )
    return out


def _poly_mask(points: list[list[float]], size: tuple[int, int]) -> list[bool]:
    w, h = size
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)
    xy = [(p[0] * (w - 1), p[1] * (h - 1)) for p in points]
    draw.polygon(xy, fill=255)
    return [v > 127 for v in img.getdata()]


@pytest.mark.skipif(_neon_paths() is None, reason="Neon Relic fixtures not available")
def test_neon_relic_object_select_covers_leaf_not_center_patch() -> None:
    before, target = _neon_paths()  # type: ignore[misc]
    assert before is not None and target is not None
    # Prefer a mid-leaf seed known to succeed; expand for mottled coverage.
    proposal = propose_object_polygon(
        before,
        0.55,
        0.75,
        seeds=[[0.45, 0.78], [0.52, 0.68]],
        max_edge=640,
        tol=16.0,
        expand_passes=2,
    )
    assert proposal.elapsed_s < 1.0
    assert len(proposal.points) >= 3

    with Image.open(before) as src:
        size = src.size
    prop_m = _poly_mask(proposal.points, size)
    tgt_m = _magenta_mask(target, size)
    both = sum(1 for a, b in zip(prop_m, tgt_m) if a and b)
    tgt_count = sum(1 for b in tgt_m if b) + 1e-9
    recall = both / tgt_count
    # Complete leaf coverage (not a center patch): recall must stay high.
    assert recall >= 0.90, f"leaf recall {recall:.3f} < 0.90 (center-patch risk)"
    assert 0.10 <= proposal.coverage <= 0.55
