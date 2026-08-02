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
    assert "/static/vendor/leaflet/leaflet.js" in page.text
    assert "/static/vendor/leaflet.markercluster/" in page.text
    assert "unpkg.com/leaflet" not in page.text

    vendor_js = client.get("/static/vendor/leaflet/leaflet.js")
    assert vendor_js.status_code == 200
    assert len(vendor_js.content) > 1000
    cluster_js = client.get(
        "/static/vendor/leaflet.markercluster/leaflet.markercluster.js"
    )
    assert cluster_js.status_code == 200
    worldmap_js = client.get("/static/js/worldmap.js")
    assert worldmap_js.status_code == 200

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
    assert "Back to map" not in resp.text
    assert "Zurück zur Karte" not in resp.text


def test_media_detail_back_to_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    mid = _seed(db, tmp_path / "lib", lat=47.1, lon=8.2, name="frommap.MP4")
    client = TestClient(app)
    resp = client.get(f"/media/{mid}?from=map&lat=47.050000&lon=8.300000&zoom=11.5")
    assert resp.status_code == 200
    assert "Zurück zur Karte" in resp.text or "Back to map" in resp.text
    assert 'href="/map?' in resp.text
    assert f"focus={mid}" in resp.text
    assert "lat=47.05" in resp.text
    assert "lon=8.3" in resp.text
    assert "zoom=11.5" in resp.text
    assert "detail-map-return" in resp.text

def test_browse_detail_links_carry_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    mid = _seed(db, tmp_path / "lib", lat=47.0, lon=8.0, name="filtered.MP4")
    client = TestClient(app)
    browse = client.get("/browse?kind=video&drone=Mini+4+Pro&q=filtered&view=grid")
    assert browse.status_code == 200
    assert f'href="/media/{mid}?from=browse' in browse.text
    assert "kind=video" in browse.text
    assert "drone=Mini+4+Pro" in browse.text or "drone=Mini%204%20Pro" in browse.text
    assert "q=filtered" in browse.text
    assert "/static/js/browse.js" in browse.text


def test_media_detail_back_to_browse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    mid = _seed(db, tmp_path / "lib", lat=1.0, lon=2.0, name="frombrowse.MP4")
    client = TestClient(app)
    qs = "from=browse&kind=video&drone=Mini+4+Pro&favorite=yes&q=hello&view=list"
    resp = client.get(f"/media/{mid}?{qs}")
    assert resp.status_code == 200
    assert "Zurück zu Medien" in resp.text or "Back to browse" in resp.text
    assert "detail-browse-return" in resp.text
    assert 'href="/browse?' in resp.text
    assert "kind=video" in resp.text
    assert "favorite=yes" in resp.text
    assert "q=hello" in resp.text
    assert "view=list" in resp.text
    # Breadcrumb and primary nav should keep the filtered browse URL
    assert resp.text.count('href="/browse?') >= 2
    assert "Back to map" not in resp.text
    assert "Zurück zur Karte" not in resp.text


def test_media_detail_without_browse_origin_has_plain_browse_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    mid = _seed(db, tmp_path / "lib", lat=1.0, lon=2.0, name="plain.MP4")
    client = TestClient(app)
    resp = client.get(f"/media/{mid}")
    assert resp.status_code == 200
    assert "detail-browse-return" not in resp.text
    assert "Back to browse" not in resp.text
    assert "Zurück zu Medien" not in resp.text
    assert 'href="/browse"' in resp.text
