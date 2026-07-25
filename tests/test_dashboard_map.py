"""Tests for dashboard, browse redirect, and geo map API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    return create_app()


def _seed(db: Database, root: Path, *, lat: float | None, lon: float | None, name: str) -> int:
    root.mkdir(parents=True, exist_ok=True)
    f = root / name
    f.write_bytes(b"x")
    return db.upsert_media(
        {
            "root_id": db.add_root(root, label="t") if not db.list_roots() else db.list_roots()[0]["id"],
            "primary_asset_id": None,
            "kind": "photo" if name.lower().endswith((".jpg", ".jpeg", ".png")) else "video",
            "filename": name,
            "path": str(f.resolve()),
            "size_bytes": 1,
            "duration_s": 1.0 if name.lower().endswith(".mp4") else None,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": None,
            "mode": None,
            "drone_model": "Mini 4 Pro",
            "camera_model": None,
            "latitude": lat,
            "longitude": lon,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )


def test_dashboard_is_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Welcome to orga-drone" in resp.text or "Willkommen bei orga-drone" in resp.text
    assert 'href="/browse"' in resp.text
    assert 'href="/map"' in resp.text
    # Empty roots: CTA to add folder, no forced redirect away from dashboard
    assert resp.history == [] or all(r.status_code != 303 for r in resp.history)


def test_browse_and_media_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    root = tmp_path / "lib"
    _seed(db, root, lat=47.0, lon=8.0, name="clip.MP4")

    client = TestClient(app)
    browse = client.get("/browse")
    assert browse.status_code == 200
    assert "clip.MP4" in browse.text

    alias = client.get("/media")
    assert alias.status_code == 200
    assert "clip.MP4" in alias.text

    dash = client.get("/dashboard", follow_redirects=False)
    assert dash.status_code == 303
    assert dash.headers["location"] == "/"


def test_map_page_and_geo_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    root = tmp_path / "lib"
    mid_gps = _seed(db, root, lat=47.1, lon=8.2, name="gps.MP4")
    mid_no = _seed(db, root, lat=None, lon=None, name="nogps.JPG")

    client = TestClient(app)
    page = client.get("/map")
    assert page.status_code == 200
    assert "world-map" in page.text
    assert "leaflet.markercluster" in page.text

    api = client.get("/api/geo/media?include_noloc=1")
    assert api.status_code == 200
    data = api.json()
    ids = {i["id"] for i in data["items"]}
    assert mid_gps in ids
    assert mid_no not in ids
    noloc_ids = {i["id"] for i in data["without_location"]}
    assert mid_no in noloc_ids

    boxed = client.get("/api/geo/media?north=48&south=46&east=9&west=7")
    assert boxed.status_code == 200
    assert any(i["id"] == mid_gps for i in boxed.json()["items"])

    outside = client.get("/api/geo/media?north=10&south=0&east=10&west=0")
    assert outside.status_code == 200
    assert outside.json()["items"] == []


def test_media_detail_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    mid = _seed(db, tmp_path / "lib", lat=1.0, lon=2.0, name="d.MP4")
    client = TestClient(app)
    resp = client.get(f"/media/{mid}")
    assert resp.status_code == 200
    assert "d.MP4" in resp.text
