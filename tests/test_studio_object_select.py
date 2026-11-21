"""Classical local object proposal (#539/#540)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from orga_drone.studio_object_select import (
    ObjectSelectError,
    propose_object_polygon,
    proposal_to_selection,
)


def _fixture(tmp_path: Path) -> Path:
    img = Image.new("RGB", (200, 200), (40, 40, 40))
    draw = ImageDraw.Draw(img)
    draw.ellipse((50, 50, 150, 150), fill=(40, 180, 60))
    path = tmp_path / "blob.jpg"
    img.save(path, quality=95)
    return path


def test_propose_object_polygon_on_green_blob(tmp_path: Path) -> None:
    path = _fixture(tmp_path)
    proposal = propose_object_polygon(path, 0.5, 0.5, max_edge=200, tol=18.0, max_points=32)
    assert proposal.closed is True
    assert len(proposal.points) >= 3
    assert 0.05 < proposal.coverage < 0.6
    assert proposal.method.startswith("lab-flood")
    # Contour should stay near the blob (not whole frame).
    xs = [p[0] for p in proposal.points]
    ys = [p[1] for p in proposal.points]
    assert min(xs) > 0.15 and max(xs) < 0.85
    assert min(ys) > 0.15 and max(ys) < 0.85
    selection = proposal_to_selection(proposal, selection_id="sel-obj", name="Object")
    assert selection["name"] == "Object"
    assert selection["mask"]["leaves"][0]["type"] == "polygon"


def test_propose_object_rejects_out_of_range_uv(tmp_path: Path) -> None:
    path = _fixture(tmp_path)
    with pytest.raises(ObjectSelectError):
        propose_object_polygon(path, -0.1, 0.5)


def test_propose_object_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ObjectSelectError):
        propose_object_polygon(tmp_path / "missing.jpg", 0.5, 0.5)
