"""Detail photo preview: HEIC/HEIF must use JPEG /preview, not raw /stream."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.thumbs import browser_can_display_photo


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    monkeypatch.setattr(
        "orga_drone.thumbs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    return create_app()


def test_browser_can_display_photo() -> None:
    assert browser_can_display_photo(Path("a.JPG"))
    assert browser_can_display_photo(Path("a.png"))
    assert not browser_can_display_photo(Path("a.HEIC"))
    assert not browser_can_display_photo(Path("a.heif"))
    assert not browser_can_display_photo(Path("a.dng"))


def test_heic_detail_uses_jpeg_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_generic_media import _write_gps_image

    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    lib = tmp_path / "lib"
    lib.mkdir()
    photo = lib / "IMG_map.HEIC"
    _write_gps_image(photo, fmt="HEIC", lat=47.2, lon=8.3)

    root_id = db.add_root(lib, label="iphone")
    mid = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": photo.name,
            "path": str(photo.resolve()),
            "size_bytes": photo.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-06-15T12:30:00",
            "sequence": None,
            "mode": None,
            "drone_model": "Camera",
            "camera_model": "iPhone",
            "source_type": "phone",
            "latitude": 47.2,
            "longitude": 8.3,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )

    client = TestClient(app)
    detail = client.get(f"/media/{mid}")
    assert detail.status_code == 200
    assert f'/media/{mid}/preview' in detail.text
    assert f'/media/{mid}/stream' not in detail.text or "photo-preview" in detail.text
    # Prefer asserting the img src specifically:
    assert f'src="/media/{mid}/preview"' in detail.text

    preview = client.get(f"/media/{mid}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/jpeg")
    assert preview.content[:2] == b"\xff\xd8"  # JPEG SOI
    # Inline image responses must not force a download filename (WebView2).
    cd = preview.headers.get("content-disposition", "")
    assert "filename=" not in cd.lower()


def test_session_photo_detail_shows_photo_not_video_player(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """World-map photos attached to a multi-clip session must still show as photos.

    Regression: flight tab used a <video> player for photos, so the map thumb
    worked while the detail preview looked unavailable.
    """
    from tests.test_generic_media import _write_gps_image

    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    lib = tmp_path / "lib"
    lib.mkdir()
    photo = lib / "IMG_session.JPG"
    _write_gps_image(photo, fmt="JPEG", lat=46.9, lon=7.4)
    # Minimal stand-in videos (bytes only; not decoded in this test).
    v1 = lib / "clip_a.MP4"
    v2 = lib / "clip_b.MP4"
    v1.write_bytes(b"\x00\x00\x00\x14ftypisom" + b"\x00" * 64)
    v2.write_bytes(b"\x00\x00\x00\x14ftypisom" + b"\x00" * 64)

    root_id = db.add_root(lib, label="flight")
    photo_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": photo.name,
            "path": str(photo.resolve()),
            "size_bytes": photo.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-06-15T12:30:00",
            "sequence": None,
            "mode": None,
            "drone_model": "Camera",
            "camera_model": "iPhone",
            "source_type": "phone",
            "latitude": 46.9,
            "longitude": 7.4,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    ids = [photo_id]
    for name, path, ts in (
        ("clip_a.MP4", v1, "2024-06-15T12:00:00"),
        ("clip_b.MP4", v2, "2024-06-15T12:05:00"),
    ):
        ids.append(
            db.upsert_media(
                {
                    "root_id": root_id,
                    "primary_asset_id": None,
                    "kind": "video",
                    "filename": name,
                    "path": str(path.resolve()),
                    "size_bytes": path.stat().st_size,
                    "duration_s": 12.0,
                    "recorded_at": ts,
                    "sequence": None,
                    "mode": None,
                    "drone_model": "DJI Avata 2",
                    "camera_model": None,
                    "source_type": "drone",
                    "latitude": 46.9,
                    "longitude": 7.4,
                    "abs_alt": None,
                    "has_srt": 0,
                    "has_lrf": 0,
                    "track_json": None,
                }
            )
        )
    lookup = db.media_map_for_root(root_id, kind=None)
    # One session: two videos + photo (photo last, as attach_photos would).
    db.replace_sessions_for_root(root_id, [ids[1:] + [ids[0]]], lookup)

    client = TestClient(app)
    # Default open (as from world map) and explicit flight tab must both keep
    # a photo <img>, never a <video> for this media id.
    for url in (f"/media/{photo_id}", f"/media/{photo_id}?tab=flight"):
        detail = client.get(url)
        assert detail.status_code == 200, url
        assert 'class="photo-preview"' in detail.text, url
        assert f'src="/media/{photo_id}/stream"' in detail.text, url
        assert 'id="media-player"' not in detail.text, url

    stream = client.get(f"/media/{photo_id}/stream")
    assert stream.status_code == 200
    cd = stream.headers.get("content-disposition", "")
    assert "filename=" not in cd.lower()


def test_jpeg_detail_uses_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_generic_media import _write_gps_image

    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    lib = tmp_path / "lib"
    lib.mkdir()
    photo = lib / "shot.JPG"
    _write_gps_image(photo, fmt="JPEG")

    root_id = db.add_root(lib, label="cam")
    mid = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": photo.name,
            "path": str(photo.resolve()),
            "size_bytes": photo.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-06-15T12:30:00",
            "sequence": None,
            "mode": None,
            "drone_model": "Camera",
            "camera_model": None,
            "source_type": "phone",
            "latitude": 47.1,
            "longitude": 8.5,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )

    client = TestClient(app)
    detail = client.get(f"/media/{mid}")
    assert detail.status_code == 200
    assert f'src="/media/{mid}/stream"' in detail.text
    assert f'src="/media/{mid}/preview"' not in detail.text
