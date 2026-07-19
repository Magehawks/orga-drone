"""Tests for local GeoJSON / .orga-spot.json spot export."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key, track_to_json
from orga_drone.export.spot import (
    COORD_DECIMALS,
    SPOT_VERSION,
    build_spot_geojson,
    downsample_track,
    round_coord,
    spot_download_filename,
)
from orga_drone.parse import GpsPoint


def _seed_gps_media(db: Database, root_path: Path, *, with_track: bool = True) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / "DJI_20240102_0001_D.MP4"
    media_file.write_bytes(b"fake")
    path = str(media_file.resolve())
    track_json = None
    if with_track:
        points = [
            GpsPoint(
                lat=47.12345678 + i * 0.0001,
                lon=8.23456789 + i * 0.0002,
                abs_alt=500.0,
                rel_alt=10.0 + i,
                t=float(i),
            )
            for i in range(50)
        ]
        track_json = track_to_json(points)
    mid = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": "DJI_20240102_0001_D.MP4",
            "path": path,
            "size_bytes": 4,
            "duration_s": 12.0,
            "recorded_at": "2024-01-02T10:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": "Avata 2",
            "camera_model": None,
            "latitude": 47.12345678,
            "longitude": 8.23456789,
            "abs_alt": 500.0,
            "has_srt": 1 if with_track else 0,
            "has_lrf": 0,
            "track_json": track_json,
        }
    )
    return mid


def test_round_coord_privacy() -> None:
    assert round_coord(47.12345678) == round(47.12345678, COORD_DECIMALS)
    assert COORD_DECIMALS == 4


def test_downsample_keeps_ends() -> None:
    pts = [{"lat": float(i), "lon": float(i)} for i in range(500)]
    out = downsample_track(pts, max_points=20)
    assert len(out) <= 20
    assert out[0] == pts[0]
    assert out[-1] == pts[-1]


def test_build_spot_geojson_point_and_meta(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    mid = _seed_gps_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    db.upsert_media_meta(
        item.path,
        stars=3,
        favorite=False,
        tags=["alps", "sunset"],
        notes="ridge line",
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
    )
    item = db.get_media(mid)
    assert item is not None

    from orga_drone.db import track_from_json

    geo = build_spot_geojson(item, track_from_json(item.track_json))
    assert geo["type"] == "FeatureCollection"
    assert geo["orga_drone_spot_version"] == SPOT_VERSION
    assert len(geo["features"]) == 2

    point = geo["features"][0]
    assert point["geometry"]["type"] == "Point"
    lon, lat = point["geometry"]["coordinates"]
    assert lon == round_coord(8.23456789)
    assert lat == round_coord(47.12345678)
    props = point["properties"]
    assert props["filename"] == "DJI_20240102_0001_D.MP4"
    assert props["title"] == "DJI_20240102_0001_D"
    assert props["drone_model"] == "Avata 2"
    assert props["notes"] == "ridge line"
    assert props["tags"] == ["alps", "sunset"]
    assert props["orga_drone_spot_version"] == 1

    line = geo["features"][1]
    assert line["geometry"]["type"] == "LineString"
    assert len(line["geometry"]["coordinates"]) >= 2


def test_build_spot_requires_gps(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    root_id = db.add_root(tmp_path / "lib", label="t")
    (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
    f = tmp_path / "lib" / "x.MP4"
    f.write_bytes(b"x")
    mid = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": "x.MP4",
            "path": str(f.resolve()),
            "size_bytes": 1,
            "duration_s": 1.0,
            "recorded_at": None,
            "sequence": None,
            "mode": None,
            "drone_model": None,
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    item = db.get_media(mid)
    assert item is not None
    with pytest.raises(ValueError):
        build_spot_geojson(item)


def test_spot_download_filename() -> None:
    assert spot_download_filename("DJI_2024.MP4") == "DJI_2024.orga-spot.json"


def test_http_export_spot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    mid = _seed_gps_media(db, tmp_path / "lib")
    item = db.get_media(mid)
    assert item is not None
    db.upsert_media_meta(item.path, stars=1, favorite=False, tags=["t"], notes="n")

    client = TestClient(app)
    resp = client.get(f"/media/{mid}/export/spot.geojson")
    assert resp.status_code == 200
    assert "application/geo+json" in resp.headers["content-type"]
    assert ".orga-spot.json" in resp.headers.get("content-disposition", "")
    data = resp.json()
    assert data["orga_drone_spot_version"] == 1
    assert data["features"][0]["properties"]["notes"] == "n"

    detail = client.get(f"/media/{mid}")
    assert detail.status_code == 200
    assert "/export/spot.geojson" in detail.text


def test_http_export_spot_without_gps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    root = tmp_path / "lib"
    root.mkdir()
    f = root / "nogps.MP4"
    f.write_bytes(b"x")
    mid = db.upsert_media(
        {
            "root_id": db.add_root(root, label="t"),
            "primary_asset_id": None,
            "kind": "video",
            "filename": "nogps.MP4",
            "path": str(f.resolve()),
            "size_bytes": 1,
            "duration_s": 1.0,
            "recorded_at": None,
            "sequence": None,
            "mode": None,
            "drone_model": None,
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    client = TestClient(app)
    resp = client.get(f"/media/{mid}/export/spot.geojson")
    assert resp.status_code == 404

    detail = client.get(f"/media/{mid}")
    assert detail.status_code == 200
    assert "Export spot" not in detail.text and "Spot exportieren" not in detail.text
