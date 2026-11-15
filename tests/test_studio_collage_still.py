"""Studio collage still preview / PNG-JPEG export (ADR 0038 / #460)."""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.export.studio_encoder import StudioExportError
from orga_drone.studio_collage import (
    assign_leaf_media,
    iter_leaves,
    preset_spec,
    resolve_rects,
)
from orga_drone.studio_collage_still import (
    EXPORT_LONG_EDGE,
    PREVIEW_LONG_EDGE,
    compose_collage_rgba,
    export_collage_still,
    inspect_collage_still,
    render_collage_preview_png,
)


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_collage_still.settings", prefs)
    monkeypatch.setattr("orga_drone.app.settings", prefs)
    return prefs


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


def _rgb(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    _isolate(monkeypatch, tmp_path)
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _filled_1plus1(db: Database, root: Path, tmp_path: Path) -> tuple[dict, list[Path]]:
    del tmp_path  # root hosts the library files
    a = root / "a.png"
    b = root / "b.png"
    _rgb(a, (200, 100), (220, 40, 40))
    _rgb(b, (200, 100), (40, 80, 220))
    id_a = _add_photo(db, root, "a.png", a)
    id_b = _add_photo(db, root, "b.png", b)
    spec = preset_spec("1+1")
    leaves = iter_leaves(spec["root"])
    spec = assign_leaf_media(
        spec,
        leaves[0]["id"],
        {"source": "library", "media_id": id_a, "kind": "photo", "fit": "fill"},
    )
    spec = assign_leaf_media(
        spec,
        leaves[1]["id"],
        {"source": "library", "media_id": id_b, "kind": "photo", "fit": "fill"},
    )
    return spec, [a, b]


def test_compose_rects_match_solver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    spec, _paths = _filled_1plus1(db, root, tmp_path)
    canvas = compose_collage_rgba(db, spec, long_edge=640)
    try:
        assert max(canvas.size) == 640
        rects = resolve_rects(spec, canvas.size[0], canvas.size[1])
        leaves = iter_leaves(spec["root"])
        left = rects[leaves[0]["id"]]
        right = rects[leaves[1]["id"]]
        # Sample centers of each cell — should keep distinct leaf colors.
        lx = left.x + left.w // 2
        ly = left.y + left.h // 2
        rx = right.x + right.w // 2
        ry = right.y + right.h // 2
        left_px = canvas.getpixel((lx, ly))
        right_px = canvas.getpixel((rx, ry))
        assert left_px[0] > right_px[0]
        assert right_px[2] > left_px[2]
    finally:
        canvas.close()


def test_preview_long_edge_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    spec, _ = _filled_1plus1(db, root, tmp_path)
    png = render_collage_preview_png(db, spec, long_edge=PREVIEW_LONG_EDGE)
    img = Image.open(io.BytesIO(png))
    assert max(img.size) <= PREVIEW_LONG_EDGE
    assert img.format == "PNG"


def test_jpeg_rejects_transparent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    spec, paths = _filled_1plus1(db, root, tmp_path)
    spec = dict(spec)
    spec["background"] = "transparent"
    before = {p: p.read_bytes() for p in paths}
    with pytest.raises(StudioExportError, match="transparent"):
        export_collage_still(
            db,
            spec,
            tmp_path / "out.jpg",
            fmt="jpeg",
            long_edge=320,
        )
    for path, original in before.items():
        assert path.read_bytes() == original


def test_png_export_and_missing_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    spec, paths = _filled_1plus1(db, root, tmp_path)
    # Clear second leaf → placeholder, collage still exports.
    leaves = iter_leaves(spec["root"])
    spec = assign_leaf_media(spec, leaves[1]["id"], None)
    before = {p: p.read_bytes() for p in paths}
    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    out = export_collage_still(
        db,
        spec,
        export_dir / "collage.png",
        fmt="png",
        long_edge=480,
    )
    assert out.is_file()
    assert out.suffix.lower() == ".png"
    img = Image.open(out)
    assert max(img.size) == 480
    for path, original in before.items():
        assert path.read_bytes() == original


def test_inspect_and_http_preview_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    root = tmp_path / "media"
    spec, paths = _filled_1plus1(db, root, tmp_path)
    before = {p: p.read_bytes() for p in paths}

    project = db.create_studio_project("Still collage")
    clip = db.add_studio_collage(
        project.id,
        collage_spec=spec,
        collage_duration_s=5.0,
    )
    inspect = inspect_collage_still(db, spec, long_edge=EXPORT_LONG_EDGE, fmt="png")
    assert inspect["ok"] is True
    assert inspect["leaf_count"] == 2

    preview = client.post(f"/api/studio/{clip.id}/collage/preview", json={"t_s": 0})
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")
    assert len(preview.content) > 100

    export_dir = tmp_path / "out"
    export_dir.mkdir()
    dest = export_dir / "collage.jpg"
    started = client.post(
        f"/api/studio/{clip.id}/collage/export",
        json={"format": "jpeg", "output_path": str(dest), "t_s": 0},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    path = None
    for _ in range(50):
        status = client.get(f"/api/studio/export/jobs/{job_id}")
        assert status.status_code == 200
        body = status.json()
        if body["state"] == "completed":
            path = Path(body["output_path"])
            break
        if body["state"] in {"failed", "cancelled"}:
            pytest.fail(body.get("error") or body["state"])
        time.sleep(0.05)
    assert path is not None and path.is_file()
    assert path.suffix.lower() in {".jpg", ".jpeg"}
    for src, original in before.items():
        assert src.read_bytes() == original


def test_http_rejects_non_collage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("No collage")
    # Title card is not a collage.
    card = db.add_studio_title_card(project.id, title_text="Hi", card_duration_s=3.0)
    res = client.post(f"/api/studio/{card.id}/collage/preview", json={})
    assert res.status_code == 400


def test_fit_mode_letterboxes_without_stretch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    # Wide source into a square-ish 1:1 collage leaf via 1+1 with tall canvas.
    wide = root / "wide.png"
    _rgb(wide, (400, 100), (240, 20, 20))
    mid = _add_photo(db, root, "wide.png", wide)
    spec = preset_spec("1+1")
    leaves = iter_leaves(spec["root"])
    spec = assign_leaf_media(
        spec,
        leaves[0]["id"],
        {"source": "library", "media_id": mid, "kind": "photo", "fit": "fit"},
    )
    spec = dict(spec)
    spec["aspect"] = "1:1"
    spec["background"] = "#102030"
    canvas = compose_collage_rgba(db, spec, long_edge=200)
    try:
        # Center of left cell should be red; a corner of that cell should show bg.
        rects = resolve_rects(spec, canvas.size[0], canvas.size[1])
        left = rects[leaves[0]["id"]]
        center = canvas.getpixel((left.x + left.w // 2, left.y + left.h // 2))
        corner = canvas.getpixel((left.x + 2, left.y + 2))
        assert center[0] > 200
        assert corner[2] > corner[0]  # bluish background, not stretched red
    finally:
        canvas.close()
