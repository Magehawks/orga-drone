"""Studio per-project music persistence, isolation, and HTTP (Issue #25)."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import STUDIO_MUSIC_MAX_TRACKS, Database
from orga_drone.export.music_mix import (
    build_music_amix_filter,
    build_playlist_amix_filter,
    fade_gain,
    music_bed_duration_s,
    playlist_span_durations,
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
    assert playlist_span_durations(
        story_s=10, music_durations=[4, 3], loop=False
    ) == [4, 3]
    assert playlist_span_durations(
        story_s=10, music_durations=[4, 8], loop=False
    ) == [4, 6]
    assert playlist_span_durations(
        story_s=10, music_durations=[4], loop=True
    ) == [10]
    assert playlist_span_durations(
        story_s=10, music_durations=[4, 3], loop=True
    ) == [4, 3]


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


def test_playlist_amix_concatenates_segments() -> None:
    graph = build_playlist_amix_filter(
        story_s=10.0,
        tracks=[
            {"volume": 0.5, "fade_in_s": 1.0, "fade_out_s": 0.0, "music_s": 4.0},
            {"volume": 0.8, "fade_in_s": 0.0, "fade_out_s": 2.0, "music_s": 8.0},
        ],
    )
    assert "[1:a]" in graph
    assert "[2:a]" in graph
    assert "concat=n=2:v=0:a=1" in graph
    assert "atrim=0:10" in graph
    assert "volume=0.5" in graph
    assert "volume=0.8" in graph
    assert "amix=inputs=2:duration=first" in graph
    assert "normalize=0" in graph


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
        posted = client.post(
            f"/api/studio/projects/{project_id}/music",
            json={"path": str(song)},
        )
        assert posted.status_code == 200
        clip_id = posted.json()["tracks"][0]["id"]
        patched = client.patch(
            f"/api/studio/projects/{project_id}/music/{clip_id}",
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
        tracks = boot.get("tracks")
        assert isinstance(tracks, list) and len(tracks) == 1
        assert tracks[0]["display_name"] == "song.mp3"
        assert tracks[0]["volume"] == 0.5
        assert tracks[0]["fade_in_s"] == 1.0
        assert tracks[0]["fade_out_s"] == 2.0
        assert tracks[0]["loop"] is True
        assert "file_path" not in boot
        assert "file_path" not in tracks[0]
        api = client.get(f"/api/studio/projects/{project_id}/music")
        assert api.status_code == 200
        body = api.json()
        assert body["tracks"][0]["volume"] == 0.5
        assert body["tracks"][0]["loop"] is True
        assert song.read_bytes() == song_bytes


def test_replace_remove_do_not_touch_file(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Story")
    first = _song(tmp_path, "first.mp3")
    second = _song(tmp_path, "second.mp3")
    before = first.read_bytes()
    db.set_studio_music(project.id, str(first))
    first_clip = db.get_studio_music(project.id)
    assert first_clip is not None
    db.set_studio_music(project.id, str(second))
    names = [clip.display_name for clip in db.list_studio_music(project.id)]
    assert names == ["first.mp3", "second.mp3"]
    db.patch_studio_music_clip(project.id, first_clip.id, file_path=str(second))
    replaced = db.get_studio_music_clip(project.id, first_clip.id)
    assert replaced is not None
    assert replaced.display_name == "second.mp3"
    db.delete_studio_music(project.id)
    assert db.get_studio_music(project.id) is None
    assert first.read_bytes() == before
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

    posted = client.post(
        f"/api/studio/projects/{project.id}/music",
        json={"path": str(song)},
    )
    assert posted.status_code == 200
    body = posted.json()
    assert body["ok"] is True
    tracks = body["tracks"]
    assert len(tracks) == 1
    clip_id = tracks[0]["id"]
    assert tracks[0]["available"] is True
    assert tracks[0]["display_name"] == "song.mp3"
    assert "file_path" not in body
    assert "file_path" not in json.dumps(body)
    assert tracks[0]["stream_url"].startswith(
        f"/api/studio/projects/{project.id}/music/{clip_id}/stream"
    )
    assert "v=" in tracks[0]["stream_url"]

    got = client.get(f"/api/studio/projects/{project.id}/music")
    assert got.status_code == 200
    assert "file_path" not in json.dumps(got.json())

    patched = client.patch(
        f"/api/studio/projects/{project.id}/music/{clip_id}",
        json={"volume": 0, "fade_in_s": 0.5, "loop": True},
    )
    assert patched.status_code == 200
    muted = patched.json()["tracks"][0]
    assert muted["volume"] == 0
    assert muted["loop"] is True
    stored = db.get_studio_music(project.id)
    assert stored is not None
    assert stored.volume == 0.0

    after = db.get_studio_project(project.id)
    assert after is not None
    assert after.updated_at >= stamped
    assert song.read_bytes() == before

    other = _song(tmp_path, "other.mp3")
    replaced = client.patch(
        f"/api/studio/projects/{project.id}/music/{clip_id}",
        json={"path": str(other)},
    )
    assert replaced.status_code == 200
    replaced_track = replaced.json()["tracks"][0]
    assert replaced_track["stream_url"] != tracks[0]["stream_url"]
    assert replaced_track["display_name"] == "other.mp3"

    stream = client.get(
        f"/api/studio/projects/{project.id}/music/{clip_id}/stream"
    )
    assert stream.status_code == 200
    assert stream.content == other.read_bytes()
    assert stream.headers.get("cache-control", "").lower() == "no-store"

    deleted = client.delete(
        f"/api/studio/projects/{project.id}/music/{clip_id}"
    )
    assert deleted.status_code == 200
    assert deleted.json()["tracks"] == []
    assert db.get_studio_music(project.id) is None
    assert song.is_file()
    assert other.is_file()


def test_http_music_playlist_reorder_cap_and_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Story")
    first = client.post(
        f"/api/studio/projects/{project.id}/music",
        json={"path": str(_song(tmp_path, "a.mp3"))},
    )
    second = client.post(
        f"/api/studio/projects/{project.id}/music",
        json={"path": str(_song(tmp_path, "b.mp3"))},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    tracks = second.json()["tracks"]
    assert [t["display_name"] for t in tracks] == ["a.mp3", "b.mp3"]
    id_a, id_b = tracks[0]["id"], tracks[1]["id"]

    patched = client.patch(
        f"/api/studio/projects/{project.id}/music/{id_a}",
        json={"volume": 0.2},
    )
    assert patched.status_code == 200
    by_id = {t["id"]: t for t in patched.json()["tracks"]}
    assert by_id[id_a]["volume"] == 0.2
    assert by_id[id_b]["volume"] == 0.8

    looped = client.patch(
        f"/api/studio/projects/{project.id}/music/{id_a}",
        json={"loop": True},
    )
    assert looped.status_code == 400
    assert looped.json()["detail"] == "loop_single_only"

    reordered = client.put(
        f"/api/studio/projects/{project.id}/music/reorder",
        json={"ids": [id_b, id_a]},
    )
    assert reordered.status_code == 200
    names = [t["display_name"] for t in reordered.json()["tracks"]]
    assert names == ["b.mp3", "a.mp3"]
    assert [clip.position for clip in db.list_studio_music(project.id)] == [0, 1]

    removed = client.delete(f"/api/studio/projects/{project.id}/music/{id_b}")
    assert removed.status_code == 200
    left = removed.json()["tracks"]
    assert [t["display_name"] for t in left] == ["a.mp3"]
    assert left[0]["position"] == 0
    loop_ok = client.patch(
        f"/api/studio/projects/{project.id}/music/{id_a}",
        json={"loop": True},
    )
    assert loop_ok.status_code == 200
    assert loop_ok.json()["tracks"][0]["loop"] is True


def test_http_music_cap_eight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Story")
    for index in range(STUDIO_MUSIC_MAX_TRACKS):
        res = client.post(
            f"/api/studio/projects/{project.id}/music",
            json={"path": str(_song(tmp_path, f"s{index}.mp3"))},
        )
        assert res.status_code == 200
    ninth = client.post(
        f"/api/studio/projects/{project.id}/music",
        json={"path": str(_song(tmp_path, "overflow.mp3"))},
    )
    assert ninth.status_code == 409
    assert ninth.json()["detail"] == "music_limit"
    assert len(db.list_studio_music(project.id)) == STUDIO_MUSIC_MAX_TRACKS


def test_music_playlist_drops_unique_index(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Story")
    db.set_studio_music(project.id, str(_song(tmp_path, "a.mp3")))
    db.set_studio_music(project.id, str(_song(tmp_path, "b.mp3")))
    assert len(db.list_studio_music(project.id)) == 2
    with db.connect() as conn:
        names = {
            str(row["name"])
            for row in conn.execute("PRAGMA index_list(studio_audio_clips)")
        }
    assert "idx_studio_audio_clips_one_music" not in names


def test_http_music_outside_library_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Story")
    song = _song(tmp_path)
    res = client.post(
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
    clip = db.set_studio_music(project.id, str(song))
    song.unlink()
    got = client.get(f"/api/studio/projects/{project.id}/music")
    assert got.status_code == 200
    body = got.json()
    assert len(body["tracks"]) == 1
    assert body["tracks"][0]["available"] is False
    stream = client.get(
        f"/api/studio/projects/{project.id}/music/{clip.id}/stream"
    )
    assert stream.status_code == 404


def test_pick_open_file_503_without_desktop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _db = _client(tmp_path, monkeypatch)
    res = client.post("/api/desktop/pick-open-file", json={})
    assert res.status_code == 503
    assert res.json()["error"] == "open_picker_unavailable"
