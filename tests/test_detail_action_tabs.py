"""Detail page groups actions into Info, Location, Share, Image, and Export."""

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
    assert ">Info<" in text
    assert ">Share<" in text
    assert ">Image<" in text
    assert ">Export<" in text
    assert ">Location<" in text
    assert ">File<" not in text
    assert ">Organize<" not in text
    assert 'data-detail-tab-button="file"' not in text
    assert "/static/js/detail-actions.js" in text
    tab_order = [
        text.index('data-detail-tab-button="info"'),
        text.index('data-detail-tab-button="location"'),
        text.index('data-detail-tab-button="share"'),
        text.index('data-detail-tab-button="image"'),
        text.index('data-detail-tab-button="export"'),
    ]
    assert tab_order == sorted(tab_order)
    assert text.index("photo-preview") < text.index('id="detail-actions"')
    assert text.index('class="meta"') > text.index("photo-preview")
    assert text.count('class="meta"') == 1
    assert "view-tabs" not in text

    info_open = text.split('id="detail-panel-info"', 1)[1].split(">", 1)[0]
    share_open = text.split('id="detail-panel-share"', 1)[1].split(">", 1)[0]
    image_open = text.split('id="detail-panel-image"', 1)[1].split(">", 1)[0]
    export_open = text.split('id="detail-panel-export"', 1)[1].split(">", 1)[0]
    location_open = text.split('id="detail-panel-location"', 1)[1].split(">", 1)[0]
    assert "hidden" not in info_open
    assert "hidden" in share_open
    assert "hidden" in image_open
    assert "hidden" in export_open
    assert "hidden" in location_open

    info = _panel(text, "detail-panel-info", "detail-panel-share")
    share = _panel(text, "detail-panel-share", "detail-panel-image")
    image = _panel(text, "detail-panel-image", "detail-panel-export")
    export = _panel(text, "detail-panel-export", "detail-panel-location")
    location = _panel(text, "detail-panel-location", "detail-export-grade")
    assert 'class="meta"' in info
    assert ">Date<" in info
    assert ">Drone<" in info
    assert ">Camera<" in info
    assert ">Path<" in info
    assert "/meta" in info
    assert 'name="stars"' in info
    assert "/albums/add" in info
    assert "/rename" in info
    assert "/studio/add" in share
    assert 'id="detail-export"' not in share
    assert "detail-adjust-exposure" not in share
    assert 'id="detail-adjust-exposure"' in image
    assert 'id="detail-adjust-contrast"' in image
    assert 'id="detail-adjust-saturation"' in image
    assert 'id="detail-adjust-warmth"' in image
    assert 'id="detail-adjust-highlights"' in image
    assert 'id="detail-quick-look"' in image
    assert 'id="detail-look-compare"' in image
    assert 'id="detail-image-section-basic"' in image
    assert 'id="detail-image-section-advanced"' in image
    assert 'id="detail-adjust-reset"' in image
    assert "Look &amp; color" in image or "Look & color" in image
    assert "Fine-tune" in image
    assert 'id="detail-export-run"' not in image
    assert 'id="detail-export-format"' not in image
    assert 'id="detail-export-preset"' not in image
    assert 'id="detail-export"' in export
    assert 'id="detail-export-preset"' in export
    assert 'id="detail-export-format"' in export
    assert 'id="detail-export-run"' in export
    assert "detail-adjust-exposure" not in export
    assert "detail-adjust-reset" not in export
    assert 'id="map"' in location
    assert "Open in OpenStreetMap" in location
    assert "detail-adjust-exposure" not in location
    assert 'id="detail-export-run"' not in location
    assert "/merge" not in text
    assert "Auto-merge flow" not in text
    assert "detail-panel-file" not in text
    assert "detail-export-dialog" not in text

    german = client.get(f"/media/{mid}", cookies={"lang": "de"})
    assert ">Info<" in german.text
    assert ">Organisieren<" not in german.text
    assert ">Teilen<" in german.text
    assert ">Bild<" in german.text
    assert ">Exportieren<" in german.text
    assert ">Ort<" in german.text
    assert ">Datei<" not in german.text
    assert ">Umbenennen<" in german.text
    assert 'aria-label="Detailaktionen"' in german.text
    assert 'min="-100"' in text
    assert 'max="100"' in text
    assert ">Helligkeit<" in german.text


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
    assert text.index('class="view-tabs"') < text.index('id="media-player"')
    assert text.index('class="view-tabs"') < text.index('id="detail-actions"')
    assert text.index("Complete flight") < text.index('id="detail-actions"')
    assert text.index('id="media-player"') < text.index('id="detail-actions"')
    tab_order = [
        text.index('data-detail-tab-button="info"'),
        text.index('data-detail-tab-button="location"'),
        text.index('data-detail-tab-button="share"'),
        text.index('data-detail-tab-button="export"'),
    ]
    assert tab_order == sorted(tab_order)
    info = _panel(text, "detail-panel-info", "detail-panel-share")
    assert 'class="meta"' in info
    assert "/merge" in info
    assert "/rename" in info
    assert "detail-panel-file" not in text
    share = _panel(text, "detail-panel-share", "detail-panel-export")
    export = _panel(text, "detail-panel-export", "detail-panel-location")
    location = _panel(text, "detail-panel-location", "detail-actions.js")
    assert 'id="detail-export"' not in share
    assert "/studio/add" in share
    assert 'name="stars"' not in share
    assert 'id="detail-export"' in export
    assert 'id="detail-export-run"' in export
    assert 'id="detail-export-format"' not in export
    assert 'id="map"' in location
    assert "detail-adjust-exposure" not in location
    assert "detail-adjust-exposure" not in text
    assert 'data-detail-tab-button="image"' not in text
    assert 'id="detail-panel-image"' not in text

    script = client.get("/static/js/detail-actions.js")
    assert script.status_code == 200
    assert "orga-drone.detail.actionsTab" in script.text
    assert 'bubbles: true' in script.text
    assert 'select(initial || "info", false)' in script.text
    map_js = client.get("/static/js/map.js")
    assert map_js.status_code == 200
    assert "ResizeObserver" in map_js.text
    assert "invalidateSize" in map_js.text
    css = client.get("/static/css/app.css")
    assert ".detail-actions-panel[hidden]" in css.text
    assert "minmax(0, 1.15fr) minmax(17rem, 0.9fr)" in css.text
    assert "grid-column: 1" in css.text
    assert "grid-column: 2" in css.text
