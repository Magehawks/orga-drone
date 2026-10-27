"""Home hero, shared navigation, and settings cache safety."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.home_hero import pick_home_media_id
from orga_drone.local_cache import clear_regenerable_cache


class _Item:
    def __init__(self, media_id: int, path: Path) -> None:
        self.id = media_id
        self.path = path


def test_hero_uses_only_a_ready_cached_thumbnail(tmp_path: Path) -> None:
    ready = tmp_path / "ready.jpg"
    ready.write_bytes(b"jpg")
    missing = tmp_path / "gone.jpg"
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    (thumbs / "2_cached.jpg").write_bytes(b"thumb")
    (thumbs / "3_cached.jpg").write_bytes(b"thumb")
    chosen = pick_home_media_id(
        [_Item(1, ready), _Item(2, missing), _Item(3, ready)],
        tmp_path,
        file_ready=lambda item: item.path if item.path.is_file() else None,
    )
    assert chosen == 3


def test_clear_cache_leaves_database_and_originals(tmp_path: Path) -> None:
    data = tmp_path / "data"
    thumbs = data / "thumbs"
    tiles = data / "osm-tiles"
    thumbs.mkdir(parents=True)
    tiles.mkdir()
    (thumbs / "9_cached.jpg").write_bytes(b"thumb-bytes")
    (tiles / "tile.png").write_bytes(b"tile")
    db_file = data / "orga-drone.sqlite3"
    db_file.write_bytes(b"sqlite")
    original = tmp_path / "library" / "clip.MP4"
    original.parent.mkdir()
    original.write_bytes(b"original-video")
    overlays = data / "overlay-assets"
    overlays.mkdir()
    (overlays / "logo.png").write_bytes(b"user-overlay")

    removed = clear_regenerable_cache(data)

    assert removed >= len(b"thumb-bytes")
    assert not (thumbs / "9_cached.jpg").exists()
    assert not (tiles / "tile.png").exists()
    assert thumbs.is_dir()
    assert db_file.read_bytes() == b"sqlite"
    assert original.read_bytes() == b"original-video"
    assert (overlays / "logo.png").read_bytes() == b"user-overlay"


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    return TestClient(create_app())


def test_empty_home_shows_logo_and_shared_nav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    page = client.get("/")
    assert page.status_code == 200
    assert "orga-drone.png" in page.text
    assert "Welcome to orga-drone" in page.text or "Willkommen bei orga-drone" in page.text
    assert 'href="/library"' in page.text
    assert 'href="/browse"' in page.text
    assert 'href="/studio/projects"' in page.text
    assert 'href="/map"' in page.text
    assert 'href="/settings"' in page.text
    assert 'class="app-sidebar"' in page.text
    assert "/media/" not in page.text.split("home-hero", 1)[1].split("</section>", 1)[0]


def test_home_hero_falls_back_when_thumbnail_or_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    db: Database = client.app.state.db
    root = tmp_path / "library"
    root.mkdir()
    video = root / "clip.MP4"
    video.write_bytes(b"video")
    root_id = db.add_root(root, label="card")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": video.name,
            "path": str(video.resolve()),
            "size_bytes": video.stat().st_size,
            "duration_s": 3.0,
            "recorded_at": "2024-01-01T00:00:00",
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
    page = client.get("/")
    hero = page.text.split("home-hero", 1)[1].split("</section>", 1)[0]
    assert f"/media/{media_id}/cached-thumb" not in hero
    assert "orga-drone.png" in hero
    missing = client.get(f"/media/{media_id}/cached-thumb")
    assert missing.status_code == 404
    assert not (tmp_path / "data" / "thumbs").exists() or not any(
        (tmp_path / "data" / "thumbs").glob("*.jpg")
    )

    thumb = tmp_path / "data" / "thumbs"
    thumb.mkdir(parents=True, exist_ok=True)
    (thumb / f"{media_id}_ready.jpg").write_bytes(b"cached")
    shown = client.get("/")
    shown_hero = shown.text.split("home-hero", 1)[1].split("</section>", 1)[0]
    assert f"/media/{media_id}/cached-thumb" in shown_hero

    video.unlink()
    offline = client.get("/")
    offline_hero = offline.text.split("home-hero", 1)[1].split("</section>", 1)[0]
    assert f"/media/{media_id}/cached-thumb" not in offline_hero
    assert "orga-drone.png" in offline_hero


def test_continue_uses_the_stored_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    db: Database = client.app.state.db
    project = db.create_studio_project("Abendflug")
    db.set_open_studio_project_id(project.id)
    page = client.get("/", cookies={"lang": "en"})
    assert "Continue last project" in page.text
    assert "Abendflug" in page.text
    assert 'href="/studio"' in page.text


def test_settings_language_theme_and_cache_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    english = client.get("/settings", cookies={"lang": "en"})
    assert english.status_code == 200
    assert "Appearance" in english.text
    assert "Data and storage" in english.text
    assert "Clear cache" in english.text
    assert 'href="/theme/dark"' in english.text
    assert 'href="/theme/light"' in english.text
    assert 'href="/lang/de"' in english.text
    assert "System" not in english.text.split("Appearance", 1)[1].split("</section>", 1)[0]
    german = client.get("/settings", cookies={"lang": "de"})
    assert "Darstellung" in german.text
    assert "Daten und Speicher" in german.text
    assert 'class="nav-link sidebar-settings active"' in german.text or (
        "sidebar-settings" in german.text and "active" in german.text
    )

    switched = client.get(
        "/lang/en",
        headers={"referer": "http://testserver/settings"},
        follow_redirects=False,
    )
    assert switched.status_code == 303
    assert switched.headers["location"] == "/settings"

    themed = client.get("/theme/light", headers={"referer": "http://testserver/settings"})
    assert 'data-theme="light"' in themed.text

    data = tmp_path / "data"
    (data / "thumbs").mkdir(parents=True, exist_ok=True)
    (data / "thumbs" / "1_cached.jpg").write_bytes(b"thumb")
    original = tmp_path / "keep.MP4"
    original.write_bytes(b"keep")
    cleared = client.post("/settings/cache/clear", cookies={"lang": "en"})
    assert cleared.status_code == 200
    assert "Cache cleared." in cleared.text
    assert not (data / "thumbs" / "1_cached.jpg").exists()
    assert original.read_bytes() == b"keep"
    assert (data / "orga-drone.sqlite3").is_file()


def test_sidebar_stays_on_library_studio_and_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    for path in ("/browse", "/studio", "/map", "/settings"):
        page = client.get(path)
        assert page.status_code == 200
        assert 'class="app-sidebar"' in page.text
        assert 'href="/"' in page.text
        assert 'href="/settings"' in page.text
