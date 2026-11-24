"""Multi-seed / expand object proposal (#550) and regression guards."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from orga_drone.studio_object_select import (
    MAX_OBJECT_SEEDS,
    ObjectSelectError,
    propose_object_polygon,
)
from orga_drone.studio_object_select_fast import fast_object_select_enabled


def _mottled_leaf(tmp_path: Path) -> Path:
    """Two green lobes separated by a darker vein — single seed often misses one lobe."""
    img = Image.new("RGB", (240, 180), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.ellipse((20, 40, 110, 140), fill=(50, 170, 70))
    draw.ellipse((130, 40, 220, 140), fill=(45, 160, 65))
    # Darker strip between lobes that breaks a single flood at low tol.
    draw.rectangle((110, 40, 130, 140), fill=(25, 40, 25))
    path = tmp_path / "mottled.jpg"
    img.save(path, quality=95)
    return path


def test_multiseed_covers_both_lobes(tmp_path: Path) -> None:
    path = _mottled_leaf(tmp_path)
    single = propose_object_polygon(
        path, 0.27, 0.5, max_edge=240, tol=14.0, max_points=48, expand_passes=0
    )
    multi = propose_object_polygon(
        path,
        0.27,
        0.5,
        seeds=[[0.73, 0.5]],
        max_edge=240,
        tol=14.0,
        max_points=48,
        expand_passes=0,
    )
    assert multi.coverage > single.coverage * 1.25
    assert len(multi.seeds_uv) == 2
    assert "multiseed" in multi.method
    xs = [p[0] for p in multi.points]
    assert min(xs) < 0.35 and max(xs) > 0.65


def test_expand_increases_coverage_on_gap(tmp_path: Path) -> None:
    path = _mottled_leaf(tmp_path)
    tight = propose_object_polygon(
        path, 0.27, 0.5, max_edge=240, tol=12.0, max_points=48, expand_passes=0
    )
    grown = propose_object_polygon(
        path, 0.27, 0.5, max_edge=240, tol=12.0, max_points=48, expand_passes=4
    )
    assert grown.coverage >= tight.coverage
    assert grown.expand_passes == 4


def test_rejects_too_many_seeds(tmp_path: Path) -> None:
    path = _mottled_leaf(tmp_path)
    seeds = [[0.1 + i * 0.05, 0.5] for i in range(MAX_OBJECT_SEEDS + 1)]
    with pytest.raises(ObjectSelectError):
        propose_object_polygon(path, 0.27, 0.5, seeds=seeds, max_edge=240)


def test_rejects_invalid_seed_coords(tmp_path: Path) -> None:
    path = _mottled_leaf(tmp_path)
    with pytest.raises(ObjectSelectError):
        propose_object_polygon(path, 0.27, 0.5, seeds=[[1.5, 0.5]], max_edge=240)


def test_proposal_under_one_second_on_2mp(tmp_path: Path) -> None:
    """#554: typical ~2 MP proposal should stay under 1 s on the fast path."""
    if not fast_object_select_enabled():
        pytest.skip("OpenCV/NumPy fast path unavailable")
    img = Image.new("RGB", (1600, 1200), (40, 40, 40))
    draw = ImageDraw.Draw(img)
    draw.ellipse((400, 300, 1200, 900), fill=(40, 180, 60))
    path = tmp_path / "two_mp.jpg"
    img.save(path, quality=92)
    proposal = propose_object_polygon(path, 0.5, 0.5, max_edge=640, tol=16.0)
    assert proposal.elapsed_s < 1.0
    assert proposal.method.endswith("+opencv") or "+opencv" in proposal.method
    assert 0.05 < proposal.coverage < 0.7


def test_out_of_range_primary_uv_rejected(tmp_path: Path) -> None:
    """Broken UV validation must fail — regression contract (#542)."""
    path = _mottled_leaf(tmp_path)
    with pytest.raises(ObjectSelectError):
        propose_object_polygon(path, -0.01, 0.5, max_edge=240)
    with pytest.raises(ObjectSelectError):
        propose_object_polygon(path, 0.5, 1.01, max_edge=240)
