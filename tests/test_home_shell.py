"""Home hero, shared navigation, and settings cache safety."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.home_hero import pick_home_media_id
from orga_drone.local_cache import clear_regenerable_cache
from orga_drone.thumbs import (
    HERO_CACHE_PREFIX,
    HERO_SIZE,
    ensure_hero_thumbnail,
    ensure_thumbnail,
)


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


def test_hero_accepts_midres_hero_cache_without_grid_thumb(tmp_path: Path) -> None:
    ready = tmp_path / "ready.jpg"
    ready.write_bytes(b"jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    (thumbs / f"{HERO_CACHE_PREFIX}4_ready.jpg").write_bytes(b"hero")
    chosen = pick_home_media_id(
        [_Item(4, ready)],
        tmp_path,
        file_ready=lambda item: item.path if item.path.is_file() else None,
    )
    assert chosen == 4


def test_ensure_hero_thumbnail_writes_midres_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    monkeypatch.setattr("orga_drone.thumbs.settings", Settings(data_dir=tmp_path / "data"))
    photo = tmp_path / "shot.jpg"
    Image.new("RGB", (2000, 1200), (40, 80, 120)).save(photo, "JPEG")
    hero = ensure_hero_thumbnail(
        media_id=9, path=photo, kind="photo", filename=photo.name
    )
    assert hero.name.startswith(HERO_CACHE_PREFIX)
    assert hero.is_file()
    with Image.open(hero) as img:
        assert img.size == HERO_SIZE


def test_hero_thumb_falls_back_to_grid_without_caching_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    monkeypatch.setattr("orga_drone.thumbs.settings", Settings(data_dir=tmp_path / "data"))

    def _fail_hero(**_kwargs):
        raise OSError("hero unavailable")

    monkeypatch.setattr("orga_drone.thumbs.ensure_hero_thumbnail", _fail_hero)
    monkeypatch.setattr("orga_drone.app.ensure_hero_thumbnail", _fail_hero)
    from orga_drone.app import create_app

    client = TestClient(create_app())
    db: Database = client.app.state.db
    root = tmp_path / "library"
    root.mkdir()
    photo = root / "shot.jpg"
    Image.new("RGB", (640, 360), (20, 90, 140)).save(photo, "JPEG")
    root_id = db.add_root(root, label="card")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": photo.name,
            "path": str(photo.resolve()),
            "size_bytes": photo.stat().st_size,
            "duration_s": None,
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
    response = client.get(f"/media/{media_id}/hero-thumb")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    thumbs = tmp_path / "data" / "thumbs"
    assert thumbs.is_dir()
    assert not any(thumbs.glob(f"{HERO_CACHE_PREFIX}{media_id}_*.jpg"))
    assert any(thumbs.glob(f"{media_id}_*.jpg"))


def test_grid_thumbnail_path_never_triggers_hero_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    monkeypatch.setattr("orga_drone.thumbs.settings", Settings(data_dir=tmp_path / "data"))
    calls: list[dict[str, object]] = []

    def _track_hero(**kwargs):
        calls.append(kwargs)
        raise AssertionError("ensure_hero_thumbnail must not run on the grid path")

    monkeypatch.setattr("orga_drone.thumbs.ensure_hero_thumbnail", _track_hero)
    photo = tmp_path / "shot.jpg"
    Image.new("RGB", (800, 450), (30, 70, 110)).save(photo, "JPEG")

    first = ensure_thumbnail(media_id=11, path=photo, kind="photo", filename=photo.name)
    second = ensure_thumbnail(media_id=11, path=photo, kind="photo", filename=photo.name)
    assert first.is_file()
    assert second == first
    assert calls == []
    thumbs = tmp_path / "data" / "thumbs"
    assert any(thumbs.glob("11_*.jpg"))
    assert not any(thumbs.glob(f"{HERO_CACHE_PREFIX}11_*.jpg"))

    client_settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app.settings", client_settings)
    from orga_drone.app import create_app

    client = TestClient(create_app())
    db: Database = client.app.state.db
    root = tmp_path / "library"
    root.mkdir()
    library_photo = root / "grid.jpg"
    Image.new("RGB", (640, 360), (40, 80, 120)).save(library_photo, "JPEG")
    root_id = db.add_root(root, label="card")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": library_photo.name,
            "path": str(library_photo.resolve()),
            "size_bytes": library_photo.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-01-02T00:00:00",
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
    monkeypatch.setattr("orga_drone.app.ensure_hero_thumbnail", _track_hero)
    grid = client.get(f"/media/{media_id}/thumb")
    assert grid.status_code == 200
    assert calls == []
    assert not any(
        (tmp_path / "data" / "thumbs").glob(f"{HERO_CACHE_PREFIX}{media_id}_*.jpg")
    )


def test_hero_jpeg_covers_rendered_viewport_boxes() -> None:
    """1280x720 stays at or above 1x CSS box size for the Home hero clamps."""
    # Content width ≈ viewport - sidebar(15rem/0) - main padding.
    cases = (
        (900, 868, 288),  # sidebar hidden; max-height 18rem
        (1440, 1152, 317),  # clamp(16rem, 22vw, 24rem) → ~22vw
        (1920, 1632, 346),  # clamp(18rem, 18vw, 28rem) → ~18vw
    )
    for viewport, width_px, height_px in cases:
        scale = max(width_px / HERO_SIZE[0], height_px / HERO_SIZE[1])
        assert scale <= 1.28, (viewport, width_px, height_px, scale)


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


def _welcome_block(html: str) -> str:
    return html.split("home-welcome", 1)[1].split("home-actions", 1)[0]


def _hero_media_block(html: str) -> str:
    welcome = _welcome_block(html)
    return welcome.split("home-hero", 1)[1]


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
    welcome = _welcome_block(page.text)
    assert "home-hero-copy" in welcome
    assert "home-hero" in welcome
    # Welcome copy sits outside the media preview block.
    copy = welcome.split("home-hero-copy", 1)[1].split("home-hero ", 1)[0]
    assert "Welcome to orga-drone" in copy or "Willkommen bei orga-drone" in copy
    assert "/media/" not in _hero_media_block(page.text)
    css = client.get("/static/css/app.css")
    assert css.status_code == 200
    assert ".home-welcome" in css.text
    assert "aspect-ratio: 16 / 9" in css.text
    assert "@media (min-width: 1440px)" in css.text
    assert "@media (min-width: 1920px)" in css.text


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
    hero = _hero_media_block(page.text)
    assert f"/media/{media_id}/hero-thumb" not in hero
    assert f"/media/{media_id}/stream" not in page.text.split("home-welcome", 1)[1].split(
        "home-actions", 1
    )[0]
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
    shown_hero = _hero_media_block(shown.text)
    assert f"/media/{media_id}/hero-thumb" in shown_hero
    assert "home-hero-media" in shown_hero
    assert f"/media/{media_id}/stream" not in shown_hero
    assert f"/media/{media_id}/preview" not in shown_hero
    welcome = _welcome_block(shown.text)
    copy = welcome.split("home-hero-copy", 1)[1].split("home-hero ", 1)[0]
    assert "Welcome to orga-drone" in copy or "Willkommen bei orga-drone" in copy
    assert "home-hero-media" not in copy

    video.unlink()
    offline = client.get("/")
    offline_hero = _hero_media_block(offline.text)
    assert f"/media/{media_id}/hero-thumb" not in offline_hero
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


def test_sidebar_collapse_toggle_is_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    page = client.get("/", cookies={"lang": "en"})
    assert page.status_code == 200
    assert 'id="app-sidebar"' in page.text
    assert 'id="sidebar-collapse-toggle"' in page.text
    assert 'data-label-collapse="Collapse navigation"' in page.text
    assert 'data-label-expand="Expand navigation"' in page.text
    assert 'class="nav-link-icon"' in page.text
    assert 'class="nav-link-label"' in page.text
    js = client.get("/static/js/ui.js")
    assert js.status_code == 200
    assert "orga-drone:sidebar-collapsed" in js.text
    assert "initSidebarCollapse" in js.text or "sidebar-collapse-toggle" in js.text
    css = client.get("/static/css/app.css")
    assert css.status_code == 200
    assert ".app-sidebar.is-collapsed" in css.text
    german = client.get("/", cookies={"lang": "de"})
    assert 'data-label-collapse="Navigation einklappen"' in german.text
    assert 'data-label-expand="Navigation ausklappen"' in german.text
