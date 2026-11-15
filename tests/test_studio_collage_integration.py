"""Studio collage integration slice (ADR 0038 / #463).

Covers create → assign media → still preview/export → MP4 Story export.
WebView2 / packaged E2E: NOT_RUN.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.studio_collage import (
    assign_leaf_media,
    collage_spec_from_raw,
    iter_leaves,
)
from orga_drone.studio_collage_still import (
    export_collage_still,
    render_collage_preview_png,
)
from orga_drone.studio_export import run_studio_export


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_collage_still.settings", prefs)
    monkeypatch.setattr("orga_drone.app.settings", prefs)
    return prefs


def _rgb(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG", quality=90)


def _add_photo(db: Database, root: Path, name: str, path: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=root.name)
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": name,
            "path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": None,
            "mode": None,
            "drone_model": "Avata 2",
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )


def test_collage_create_still_and_mp4_story_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    a = root / "a.jpg"
    b = root / "b.jpg"
    _rgb(a, (640, 360), (200, 40, 40))
    _rgb(b, (640, 360), (40, 40, 200))
    a_id = _add_photo(db, root, "a.jpg", a)
    b_id = _add_photo(db, root, "b.jpg", b)

    project = db.ensure_default_studio_project()
    assert project is not None
    clip = db.add_studio_collage(project.id, preset="1+1", collage_duration_s=1.0)
    leaves = iter_leaves(collage_spec_from_raw(clip.collage_spec)["root"])
    spec = assign_leaf_media(
        collage_spec_from_raw(clip.collage_spec),
        leaves[0]["id"],
        {"source": "library", "media_id": a_id, "kind": "photo"},
    )
    spec = assign_leaf_media(
        spec,
        leaves[1]["id"],
        {"source": "library", "media_id": b_id, "kind": "photo"},
    )
    clip = db.update_studio_collage(clip.id, collage_spec=spec, collage_duration_s=1.0)
    assert clip.item_kind == "collage"

    png = render_collage_preview_png(
        db, collage_spec_from_raw(clip.collage_spec), long_edge=640, t_s=0.0
    )
    assert png.startswith(b"\x89PNG")

    still_out = prefs.data_dir / "exports" / "collage.png"
    still_out.parent.mkdir(parents=True, exist_ok=True)
    published_still = export_collage_still(
        db,
        collage_spec_from_raw(clip.collage_spec),
        still_out,
        fmt="png",
        long_edge=960,
        t_s=0.0,
    )
    assert published_still.is_file()
    assert published_still.stat().st_size > 500

    mp4_out = prefs.data_dir / "exports" / "story.mp4"
    published_mp4 = run_studio_export(
        db,
        height=720,
        output_path=mp4_out,
        project_id=project.id,
    )
    assert published_mp4.is_file()
    assert published_mp4.stat().st_size > 1000
    # Source media unchanged.
    assert a.is_file() and b.is_file()
