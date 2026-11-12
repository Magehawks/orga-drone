"""Asynchronous hero-cache warming (issue #335).

Home paints from existing caches (logo/480 fallback first); the mid-res
hero JPEGs warm in a background pass so later visits render the hero
without an ffmpeg/Pillow pause. The warm pass must never block the request
or stack duplicate workers.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.home_hero import (
    cached_hero_thumbnail,
    warm_hero_cache,
    warm_hero_cache_async,
)


def _run(*args: str) -> None:
    subprocess.run(
        [find_ffmpeg() or "ffmpeg", "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )


def _seed(db: Database, root: Path, filename: str, kind: str = "video") -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=filename)
    media_file = root / filename
    if kind == "video":
        _run("-f", "lavfi", "-i", "color=c=orange:s=640x360:r=30:d=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(media_file))
    else:
        from PIL import Image

        Image.new("RGB", (640, 360), (200, 120, 40)).save(media_file, format="JPEG")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": 1.0 if kind == "video" else None,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": 1,
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


def _app_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database, Path]:
    data = tmp_path / "data"
    settings = Settings(data_dir=data)
    # thumbs.py binds `settings` at module import time (module-global), so
    # patch every consumer binding, not just the app module.
    monkeypatch.setattr("orga_drone.app.settings", settings)
    monkeypatch.setattr("orga_drone.config.settings", settings)
    monkeypatch.setattr("orga_drone.thumbs.settings", settings)
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db, data


def test_warm_creates_hero_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not find_ffmpeg():
        pytest.skip("ffmpeg unavailable")
    _client, db, data_dir = _app_db(tmp_path, monkeypatch)
    media_id = _seed(db, tmp_path / "videos", "HERO.MP4", "video")
    warmed = warm_hero_cache(db)
    assert warmed == 1
    assert cached_hero_thumbnail(data_dir, media_id) is not None


def test_warm_skips_already_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not find_ffmpeg():
        pytest.skip("ffmpeg unavailable")
    _client, db, _data_dir = _app_db(tmp_path, monkeypatch)
    _seed(db, tmp_path / "videos", "CACHED.MP4", "video")
    assert warm_hero_cache(db) == 1
    assert warm_hero_cache(db) == 0


def test_warm_skips_offline_media_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not find_ffmpeg():
        pytest.skip("ffmpeg unavailable")
    _client, db, data_dir = _app_db(tmp_path, monkeypatch)
    media_id = _seed(db, tmp_path / "videos", "GONE.MP4", "video")
    (tmp_path / "videos" / "GONE.MP4").unlink()
    assert warm_hero_cache(db) == 0
    assert cached_hero_thumbnail(data_dir, media_id) is None


def test_async_warm_runs_in_background_and_does_not_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not find_ffmpeg():
        pytest.skip("ffmpeg unavailable")
    _client, db, data_dir = _app_db(tmp_path, monkeypatch)
    media_id = _seed(db, tmp_path / "videos", "ASYNC.MP4", "video")
    assert warm_hero_cache_async(db) is True
    assert warm_hero_cache_async(db) is False  # one pass at a time
    deadline = time.time() + 30
    while time.time() < deadline:
        if cached_hero_thumbnail(data_dir, media_id) is not None:
            break
        time.sleep(0.2)
    assert cached_hero_thumbnail(data_dir, media_id) is not None


def test_dashboard_triggers_warming_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not find_ffmpeg():
        pytest.skip("ffmpeg unavailable")
    client, db, data_dir = _app_db(tmp_path, monkeypatch)
    media_id = _seed(db, tmp_path / "videos", "TRIGGER.MP4", "video")
    # The Home render itself must not wait for hero generation.
    started = time.monotonic()
    page = client.get("/")
    elapsed = time.monotonic() - started
    assert page.status_code == 200
    assert elapsed < 10.0
    deadline = time.time() + 30
    while time.time() < deadline:
        if cached_hero_thumbnail(data_dir, media_id) is not None:
            break
        time.sleep(0.2)
    assert cached_hero_thumbnail(data_dir, media_id) is not None
