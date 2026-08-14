"""Studio per-project music persistence, isolation, and HTTP (Issue #25)."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.export.music_mix import (
    build_music_amix_filter,
    fade_gain,
    music_bed_duration_s,
    scaled_fades,
)


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _song(tmp_path: Path, name: str = "song.mp3") -> Path:
    path = tmp_path / "Music" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3fake-audio")
    return path.resolve()


def _boot_music_payload(html: str) -> dict | None:
    """Parse data-music-payload as a browser HTML attribute, then JSON."""

    class _Parser(HTMLParser):
        payload: str | None = None

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            data = dict(attrs)
            if tag == "section" and data.get("id") == "studio-root":
                self.payload = data.get("data-music-payload")

    parser = _Parser()
    parser.feed(html)
    raw = parser.payload
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def test_music_bed_and_fade_math() -> None:
    assert music_bed_duration_s(story_s=10, music_s=4, loop=True) == 10
    assert music_bed_duration_s(story_s=10, music_s=4, loop=False) == 4
    assert music_bed_duration_s(story_s=3, music_s=8, loop=False) == 3
    assert scaled_fades(6, 6, 4) == (2.0, 2.0)
    assert fade_gain(0, bed_s=10, fade_in_s=2, fade_out_s=0) == 0
    assert fade_gain(2, bed_s=10, fade_in_s=2, fade_out_s=0) == 1
    assert fade_gain(9, bed_s=10, fade_in_s=0, fade_out_s=2) == 0.5


def test_amix_filter_contains_volume_and_fades() -> None:
    graph = build_music_amix_filter(
        volume=0.8,
        fade_in_s=1.0,
        fade_out_s=2.0,
        story_s=10.0,
        music_s=4.0,
        loop=False,
    )
    assert "volume=0.8" in graph
    assert "afade=t=in" in graph
    assert "afade=t=out" in graph
    assert "amix=inputs=2:duration=first" in graph
    assert "normalize=0" in graph
    assert "volume=" in graph


def test_persist_reopen_and_isolation(tmp_path: Path) -> None:
    db_path = tmp_path / "t.sqlite3"
    db = Database(db_path)
    a = db.create_studio_project("Alps")
    b = db.create_studio_project("Lake")
    song_a = _song(tmp_path, "a.mp3")
    song_b = _song(tmp_path, "b.mp3")
    bytes_a = song_a.read_bytes()
    db.set_studio_music(a.id, str(song_a))
    db.patch_studio_music(a.id, volume=0.5, fade_in_s=1.0, fade_out_s=2.0, loop=True)
    db.set_studio_music(b.id, str(song_b))

    reopened = Database(db_path)
    music_a = reopened.get_studio_music(a.id)
    music_b = reopened.get_studio_music(b.id)
    assert music_a is not None and music_b is not None
    assert music_a.file_path == str(song_a)
    assert music_a.volume == 0.5
    assert music_a.fade_in_s == 1.0
    assert music_a.loop is True
    assert music_b.file_path == str(song_b)
    assert music_b.volume == 0.8
    assert music_b.loop is False
    assert song_a.read_bytes() == bytes_a


def test_music_survives_real_app_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_app → persist music → new create_app (desktop restart) must boot it."""
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    song = _song(tmp_path)
    song_bytes = song.read_bytes()

    app1 = create_app()
    with TestClient(app1) as client:
        project = app1.state.db.create_studio_project("Alps")
        project_id = project.id
        put = client.put(
            f"/api/studio/projects/{project_id}/music",
            json={"path": str(song)},
        )
        assert put.status_code == 200
        patched = client.patch(
            f"/api/studio/projects/{project_id}/music",
            json={
                "volume": 0.5,
                "fade_in_s": 1.0,
                "fade_out_s": 2.0,
                "loop": True,
            },
        )
        assert patched.status_code == 200
        opened = client.get(f"/studio?project_id={project_id}", follow_redirects=True)
        assert opened.status_code == 200
        before = app1.state.db.get_studio_music(project_id)
        assert before is not None

    app2 = create_app()
    with TestClient(app2) as client:
        with app2.state.db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM studio_audio_clips"
            ).fetchone()
            assert int(count["n"]) == 1
        stored = app2.state.db.get_studio_music(project_id)
        assert stored is not None
        assert stored.file_path == str(song)
        assert stored.volume == 0.5
        assert stored.fade_in_s == 1.0
        assert stored.fade_out_s == 2.0
        assert stored.loop is True
        restored = app2.state.db.resolve_studio_page_project()
        assert restored is not None
        assert restored.id == project_id
        page = client.get("/studio")
        assert page.status_code == 200
        boot = _boot_music_payload(page.text)
        assert boot is not None
        assert boot.get("present") is True
        assert boot.get("display_name") == "song.mp3"
        assert boot.get("volume") == 0.5
        assert boot.get("fade_in_s") == 1.0
        assert boot.get("fade_out_s") == 2.0
        assert boot.get("loop") is True
        assert "file_path" not in boot
        api = client.get(f"/api/studio/projects/{project_id}/music")
        assert api.status_code == 200
        body = api.json()
        assert body["present"] is True
        assert body["volume"] == 0.5
        assert body["loop"] is True
        assert song.read_bytes() == song_bytes


def test_replace_remove_do_not_touch_file(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Story")
    first = _song(tmp_path, "first.mp3")
    second = _song(tmp_path, "second.mp3")
    before = first.read_bytes()
    db.set_studio_music(project.id, str(first))
    db.set_studio_music(project.id, str(second))
    assert first.read_bytes() == before
    assert db.get_studio_music(project.id) is not None
    assert db.get_studio_music(project.id).display_name == "second.mp3"
    db.delete_studio_music(project.id)
    assert db.get_studio_music(project.id) is None
    assert first.is_file()
    assert second.is_file()


def test_delete_project_drops_reference_only(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Story")
    song = _song(tmp_path)
    db.set_studio_music(project.id, str(song))
    assert db.delete_studio_project(project.id) is True
    assert db.get_studio_music(project.id) is None
    assert song.is_file()


def test_http_music_crud_hides_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Story")
    song = _song(tmp_path)
    before = song.read_bytes()
    before_updated = db.get_studio_project(project.id)
    assert before_updated is not None
    stamped = before_updated.updated_at

    put = client.put(
        f"/api/studio/projects/{project.id}/music",
        json={"path": str(song)},
    )
    assert put.status_code == 200
    body = put.json()
    assert body["ok"] is True
    assert body["present"] is True
    assert body["available"] is True
    assert body["display_name"] == "song.mp3"
    assert "file_path" not in body
    assert "file_path" not in json.dumps(body)
    assert body["stream_url"].startswith(
        f"/api/studio/projects/{project.id}/music/stream"
    )
    assert "v=" in body["stream_url"]

    got = client.get(f"/api/studio/projects/{project.id}/music")
    assert got.status_code == 200
    assert "file_path" not in json.dumps(got.json())

    patched = client.patch(
        f"/api/studio/projects/{project.id}/music",
        json={"volume": 0, "fade_in_s": 0.5, "loop": True},
    )
    assert patched.status_code == 200
    assert patched.json()["volume"] == 0
    assert patched.json()["loop"] is True
    stored = db.get_studio_music(project.id)
    assert stored is not None
    assert stored.volume == 0.0
    got_muted = client.get(f"/api/studio/projects/{project.id}/music")
    assert got_muted.json()["volume"] == 0

    after = db.get_studio_project(project.id)
    assert after is not None
    assert after.updated_at >= stamped
    assert song.read_bytes() == before

    other = _song(tmp_path, "other.mp3")
    replaced = client.put(
        f"/api/studio/projects/{project.id}/music",
        json={"path": str(other)},
    )
    assert replaced.status_code == 200
    assert replaced.json()["stream_url"] != body["stream_url"]
    assert replaced.json()["display_name"] == "other.mp3"

    stream = client.get(f"/api/studio/projects/{project.id}/music/stream")
    assert stream.status_code == 200
    assert stream.content == other.read_bytes()
    assert stream.headers.get("cache-control", "").lower() == "no-store"

    deleted = client.delete(f"/api/studio/projects/{project.id}/music")
    assert deleted.status_code == 200
    assert deleted.json()["present"] is False
    assert db.get_studio_music(project.id) is None
    assert song.is_file()
    assert other.is_file()


def test_http_music_outside_library_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Story")
    song = _song(tmp_path)
    res = client.put(
        f"/api/studio/projects/{project.id}/music",
        json={"path": str(song)},
    )
    assert res.status_code == 200
    stored = db.get_studio_music(project.id)
    assert stored is not None
    assert Path(stored.file_path) == song


def test_http_missing_music_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Story")
    song = _song(tmp_path)
    db.set_studio_music(project.id, str(song))
    song.unlink()
    got = client.get(f"/api/studio/projects/{project.id}/music")
    assert got.status_code == 200
    body = got.json()
    assert body["present"] is True
    assert body["available"] is False
    stream = client.get(f"/api/studio/projects/{project.id}/music/stream")
    assert stream.status_code == 404


def test_pick_open_file_503_without_desktop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _db = _client(tmp_path, monkeypatch)
    res = client.post("/api/desktop/pick-open-file", json={})
    assert res.status_code == 503
    assert res.json()["error"] == "open_picker_unavailable"
