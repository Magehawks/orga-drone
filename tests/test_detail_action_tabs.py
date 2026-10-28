"""Detail page groups existing actions into Organize, Share, and File tabs."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.i18n import clear_catalog_cache


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    return create_app()


def _seed(db: Database, root: Path, name: str, *, kind: str, lat: float | None = 47.1) -> int:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(b"x")
    root_id = db.list_roots()[0]["id"] if db.list_roots() else db.add_root(root, label="t")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": name,
            "path": str(path.resolve()),
            "size_bytes": 1,
            "duration_s": 2.0 if kind == "video" else None,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": None,
            "mode": None,
            "drone_model": "Mini 4 Pro",
            "camera_model": None,
            "latitude": lat,
            "longitude": 8.2 if lat is not None else None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )


def _panel(html: str, panel_id: str, next_id: str | None) -> str:
    chunk = html.split(f'id="{panel_id}"', 1)[1]
    if next_id:
        chunk = chunk.split(f'id="{next_id}"', 1)[0]
    return chunk


def test_photo_detail_tabs_keep_preview_outside_and_hide_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_catalog_cache()
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    mid = _seed(db, tmp_path / "lib", "still.JPG", kind="photo")
    client = TestClient(app)

    page = client.get(f"/media/{mid}", cookies={"lang": "en"})
    assert page.status_code == 200
    text = page.text
    assert 'id="detail-actions"' in text
    assert 'role="tablist"' in text
    assert ">Organize<" in text
    assert ">Share<" in text
    assert ">File<" in text
    assert "/static/js/detail-actions.js" in text
    assert text.index('class="meta"') < text.index("photo-preview")
    assert text.index("photo-preview") < text.index('id="detail-actions"')
    assert text.index(">Location<") < text.index('id="detail-actions"')
    assert "view-tabs" not in text

    organize_open = text.split('id="detail-panel-organize"', 1)[1].split(">", 1)[0]
    share_open = text.split('id="detail-panel-share"', 1)[1].split(">", 1)[0]
    file_open = text.split('id="detail-panel-file"', 1)[1].split(">", 1)[0]
    assert "hidden" not in organize_open
    assert "hidden" in share_open
    assert "hidden" in file_open

    organize = _panel(text, "detail-panel-organize", "detail-panel-share")
    share = _panel(text, "detail-panel-share", "detail-panel-file")
    file_panel = _panel(text, "detail-panel-file", "detail-export-dialog")
    assert "/meta" in organize
    assert 'name="stars"' in organize
    assert "/albums/add" in organize
    assert "/studio/add" in share
    assert 'id="detail-export"' in share
    assert "/rename" in file_panel
    assert "/merge" not in text
    assert "Auto-merge flow" not in text

    german = client.get(f"/media/{mid}", cookies={"lang": "de"})
    assert ">Organisieren<" in german.text
    assert ">Teilen<" in german.text
    assert ">Datei<" in german.text
    assert 'aria-label="Detailaktionen"' in german.text


def test_flow_video_keeps_flight_switch_outside_tabs_and_merge_in_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_catalog_cache()
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    root = tmp_path / "lib"
    first = _seed(db, root, "part1.MP4", kind="video")
    second = _seed(db, root, "part2.MP4", kind="video")
    root_id = db.list_roots()[0]["id"]
    db.replace_flows_for_root(
        root_id,
        [[first, second]],
        {
            first: {
                "filename": "part1.MP4",
                "size_bytes": 1,
                "duration_s": 2.0,
                "recorded_at": "2024-06-01T12:00:00",
                "latitude": 47.1,
                "longitude": 8.2,
                "drone_model": "Mini 4 Pro",
            },
            second: {
                "filename": "part2.MP4",
                "size_bytes": 1,
                "duration_s": 2.0,
                "recorded_at": "2024-06-01T12:00:02",
                "latitude": 47.1,
                "longitude": 8.2,
                "drone_model": "Mini 4 Pro",
            },
        },
    )
    client = TestClient(app)
    page = client.get(f"/media/{first}", cookies={"lang": "en"})
    assert page.status_code == 200
    text = page.text
    assert text.index('class="view-tabs"') < text.index('id="detail-actions"')
    assert text.index("Complete flight") < text.index('id="detail-actions"')
    assert text.index('id="media-player"') < text.index('id="detail-actions"')
    file_panel = _panel(text, "detail-panel-file", "detail-export-dialog")
    assert "/merge" in file_panel
    assert "/rename" in file_panel
    share = _panel(text, "detail-panel-share", "detail-panel-file")
    assert 'id="detail-export"' in share
    assert 'name="stars"' not in share

    script = client.get("/static/js/detail-actions.js")
    assert script.status_code == 200
    assert "orga-drone.detail.actionsTab" in script.text
    css = client.get("/static/css/app.css")
    assert ".detail-actions-panel[hidden]" in css.text
