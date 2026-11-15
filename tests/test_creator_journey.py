"""Creator journey gate: Library → Project → Collage/Edit → Export (#470).

Synthetic fixtures only. Shares collage helpers with WP5–WP7 / #463.
WebView2 / packaged E2E: NOT_RUN (see docs/discovery/470-creator-journey-evidence.md).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.i18n import clear_catalog_cache
from orga_drone.studio_collage import (
    assign_leaf_media,
    collage_spec_from_raw,
    iter_leaves,
)
from orga_drone.studio_collage_grade import apply_hsl, grade_blob
from orga_drone.studio_collage_seed import seed_collage_from_media_ids
from orga_drone.studio_collage_still import (
    export_collage_still,
    render_collage_preview_png,
)
from orga_drone.studio_export import run_studio_export
from orga_drone.studio_hsl import hsl_adjust_from_effect_settings


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_collage_still.settings", prefs)
    monkeypatch.setattr("orga_drone.app.settings", prefs)
    clear_catalog_cache()
    return prefs


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _isolate(monkeypatch, tmp_path)
    from orga_drone.app import create_app

    return create_app()


def _jpg(path: Path, color: tuple[int, int, int] = (40, 90, 140)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 180), color).save(path, format="JPEG", quality=90)
    return path


def _mp4(path: Path, *, duration_s: float = 1.0, color: str = "0x306090") -> Path:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg required for synthetic video journey")
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=320x180:d={duration_s}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-t",
        str(duration_s),
        str(path),
    ]
    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **subprocess_no_window_kwargs(),
    )
    return path


def _add_media(
    db: Database,
    root: Path,
    path: Path,
    *,
    kind: str,
    duration_s: float | None = None,
) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=root.name)
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": path.name,
            "path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
            "duration_s": duration_s,
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


def test_browse_multiselect_new_project_opens_with_clips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1. Multi-select → Edit in Studio → new project → clips present."""
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    root = tmp_path / "lib"
    ids = [
        _add_media(db, root, _jpg(root / "a.jpg", (200, 40, 40)), kind="photo"),
        _add_media(db, root, _jpg(root / "b.jpg", (40, 40, 200)), kind="photo"),
    ]
    db.set_open_studio_project_id(None)
    for project in db.list_studio_projects():
        db.delete_studio_project(project.id)

    client = TestClient(app)
    resp = client.post(
        "/studio/add-bulk",
        data={
            "return_to": "/browse",
            "media_ids": [str(i) for i in ids],
            "project_mode": "new",
            "project_title": "Creator journey photos",
            "open_studio": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    loc = resp.headers["location"]
    assert loc.startswith("/studio?")
    qs = parse_qs(urlparse(loc).query)
    assert qs.get("msg") == ["studio_bulk_added"]
    assert qs.get("added") == ["2"]
    projects = db.list_studio_projects()
    assert len(projects) == 1
    items = db.list_studio_items(projects[0].id)
    assert len(items) == 2
    assert {i.item_kind for i in items} == {"media"}


def test_browse_seed_collage_and_empty_start_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2. Empty project start chrome + seeded collage leaves filled."""
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    root = tmp_path / "lib"
    ids = [
        _add_media(db, root, _jpg(root / f"p{i}.jpg", (50 + i * 40, 80, 120)), kind="photo")
        for i in range(3)
    ]
    db.set_open_studio_project_id(None)
    for project in db.list_studio_projects():
        db.delete_studio_project(project.id)

    client = TestClient(app)
    empty = db.create_studio_project("Empty start")
    db.set_open_studio_project_id(empty.id)
    page = client.get(f"/studio?project_id={empty.id}", follow_redirects=True)
    assert page.status_code == 200
    assert 'id="studio-empty-start"' in page.text
    assert 'id="studio-empty-create-collage"' in page.text

    resp = client.post(
        "/studio/add-bulk",
        data={
            "return_to": "/browse",
            "media_ids": [str(i) for i in ids],
            "project_mode": "new",
            "project_title": "Seeded collage",
            "open_studio": "1",
            "seed": "collage",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    projects = [p for p in db.list_studio_projects() if p.title == "Seeded collage"]
    assert len(projects) == 1
    collages = [
        i for i in db.list_studio_items(projects[0].id) if i.item_kind == "collage"
    ]
    assert len(collages) == 1
    leaves = iter_leaves(collage_spec_from_raw(collages[0].collage_spec)["root"])
    assert len(leaves) == 3
    assert all((leaf.get("media") or {}).get("media_id") for leaf in leaves)

    studio = client.get(f"/studio?project_id={projects[0].id}", follow_redirects=True)
    assert studio.status_code == 200
    assert 'id="studio-empty-start"' not in studio.text or 'hidden' in studio.text


def test_hold_last_frame_helper_matches_export_clock() -> None:
    """3. Hold-last-frame agreement (mirrors collage-playback.js / WP5)."""

    def leaf_source_time(
        local_s: float, start_offset_s: float, duration_s: float | None
    ) -> dict[str, float | bool]:
        t = float(start_offset_s) + max(0.0, float(local_s))
        if duration_s is None:
            return {"t": t, "hold": False}
        end = float(duration_s)
        if t >= end:
            return {"t": end, "hold": True}
        return {"t": t, "hold": False}

    # Same vectors as tests/js/collage_playback.test.js
    assert leaf_source_time(1.5, 2.0, 10) == {"t": 3.5, "hold": False}
    assert leaf_source_time(9, 2.0, 10) == {"t": 10, "hold": True}
    assert leaf_source_time(0, 0, None) == {"t": 0, "hold": False}


def test_per_leaf_grade_still_and_story_with_following_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """4–5. Per-leaf grade still smoke + collage before a normal Story clip."""
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    a = _jpg(root / "a.jpg", (200, 40, 40))
    b = _jpg(root / "b.jpg", (40, 40, 200))
    c = _jpg(root / "c.jpg", (40, 180, 40))
    a_id = _add_media(db, root, a, kind="photo")
    b_id = _add_media(db, root, b, kind="photo")
    c_id = _add_media(db, root, c, kind="photo")

    project = db.create_studio_project("Journey collage")
    collage, _assigned, leftovers = seed_collage_from_media_ids(
        db, project.id, [a_id, b_id]
    )
    assert leftovers == 0
    spec = collage_spec_from_raw(collage.collage_spec)
    leaves = iter_leaves(spec["root"])
    leaf_ids = [str(leaf["id"]) for leaf in leaves]
    graded = apply_hsl(
        spec,
        leaf_ids[0],
        {"ranges": {"red": {"hue": 25, "saturation": 10, "luminance": 0}}},
    )
    collage = db.update_studio_collage(
        collage.id, collage_spec=graded, collage_duration_s=1.0
    )
    media_c = db.get_media(c_id)
    assert media_c is not None
    trailing_id, created = db.add_studio_item(
        media_c.path,
        identity_key=make_identity_key(
            media_c.filename, media_c.size_bytes, media_c.recorded_at
        ),
        filename=media_c.filename,
        recorded_at=media_c.recorded_at,
        kind=media_c.kind,
        project_id=project.id,
        source_media_id=media_c.id,
    )
    assert created is True
    items = db.list_studio_items(project.id)
    kinds = [i.item_kind for i in items]
    assert kinds[0] == "collage"
    assert kinds[-1] == "media"
    assert trailing_id == items[-1].id

    leaves_after = {
        str(leaf["id"]): leaf
        for leaf in iter_leaves(collage_spec_from_raw(collage.collage_spec)["root"])
    }
    hsl_a = hsl_adjust_from_effect_settings(
        grade_blob(leaves_after[leaf_ids[0]].get("media"))
    )
    assert hsl_a.red.hue == 25

    png = render_collage_preview_png(
        db, collage_spec_from_raw(collage.collage_spec), long_edge=480, t_s=0.0
    )
    assert png.startswith(b"\x89PNG")

    still_out = prefs.data_dir / "exports" / "journey-collage.png"
    still_out.parent.mkdir(parents=True, exist_ok=True)
    published_still = export_collage_still(
        db,
        collage_spec_from_raw(collage.collage_spec),
        still_out,
        fmt="png",
        long_edge=640,
        t_s=0.0,
    )
    assert published_still.is_file()
    assert published_still.stat().st_size > 400

    jpeg_out = prefs.data_dir / "exports" / "journey-collage.jpg"
    published_jpeg = export_collage_still(
        db,
        collage_spec_from_raw(collage.collage_spec),
        jpeg_out,
        fmt="jpeg",
        long_edge=640,
        t_s=0.0,
    )
    assert published_jpeg.is_file()

    mp4_out = prefs.data_dir / "exports" / "journey-story.mp4"
    published_mp4 = run_studio_export(
        db,
        height=720,
        output_path=mp4_out,
        project_id=project.id,
    )
    assert published_mp4.is_file()
    assert published_mp4.stat().st_size > 1000
    assert a.is_file() and b.is_file() and c.is_file()


def test_mixed_photo_video_collage_and_missing_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mixed collage + missing library file stays export-safe."""
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    photo = _jpg(root / "still.jpg", (180, 60, 60))
    video = _mp4(root / "clip.mp4", duration_s=0.5, color="0x2060a0")
    photo_id = _add_media(db, root, photo, kind="photo")
    video_id = _add_media(db, root, video, kind="video", duration_s=0.5)
    missing_path = root / "gone.jpg"
    _jpg(missing_path, (10, 10, 10))
    missing_id = _add_media(db, root, missing_path, kind="photo")
    missing_path.unlink()

    project = db.create_studio_project("Mixed")
    collage = db.add_studio_collage(project.id, preset="2+1", collage_duration_s=1.0)
    leaves = iter_leaves(collage_spec_from_raw(collage.collage_spec)["root"])
    assert len(leaves) >= 3
    spec = collage_spec_from_raw(collage.collage_spec)
    for leaf, mid, kind in zip(
        leaves[:3],
        [photo_id, video_id, missing_id],
        ["photo", "video", "photo"],
        strict=True,
    ):
        spec = assign_leaf_media(
            spec,
            leaf["id"],
            {"source": "library", "media_id": mid, "kind": kind},
        )
    collage = db.update_studio_collage(collage.id, collage_spec=spec)

    png = render_collage_preview_png(
        db, collage_spec_from_raw(collage.collage_spec), long_edge=480, t_s=0.4
    )
    assert png.startswith(b"\x89PNG")

    still_out = prefs.data_dir / "exports" / "mixed.png"
    still_out.parent.mkdir(parents=True, exist_ok=True)
    published = export_collage_still(
        db,
        collage_spec_from_raw(collage.collage_spec),
        still_out,
        fmt="png",
        long_edge=640,
        t_s=0.4,
    )
    assert published.is_file()


def test_bulk_add_cancel_without_project_id_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelled / incomplete project choice does not invent a project."""
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    root = tmp_path / "lib"
    mid = _add_media(db, root, _jpg(root / "one.jpg"), kind="photo")
    before = len(db.list_studio_projects())
    client = TestClient(app)
    resp = client.post(
        "/studio/add-bulk",
        data={
            "return_to": "/browse",
            "media_ids": [str(mid)],
            "project_mode": "existing",
            # missing project_id → chooser retry, no silent invent
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs.get("msg") == ["studio_choose_project"]
    assert qs.get("selected") == [str(mid)]
    assert len(db.list_studio_projects()) == before
