"""Studio SFX lane persistence, history, mix filter, and HTTP (#184 / ADR 0036)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import STUDIO_SFX_MAX_CLIPS, Database
from orga_drone.export.music_mix import build_sfx_overlay_filter
from orga_drone.studio_history import clear_studio_history, history_flags, undo_story
from orga_drone.studio_sfx import (
    clamp_sfx_start_s,
    resolve_sfx_trim,
    sfx_audible_duration_s,
)


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    clear_studio_history()
    app = create_app()
    return TestClient(app), app.state.db


def _wav(tmp_path: Path, name: str = "fx.wav") -> Path:
    path = tmp_path / "Audio" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal RIFF header so the path validates as an audio suffix; duration
    # probing may fail — tests that need duration stub the probe.
    path.write_bytes(b"RIFFfake")
    return path.resolve()


def test_sfx_trim_and_placement_helpers() -> None:
    assert resolve_sfx_trim(duration_s=4.0, source_in_s=None, source_out_s=None) == (
        0.0,
        4.0,
    )
    assert resolve_sfx_trim(duration_s=4.0, source_in_s=1.0, source_out_s=3.0) == (
        1.0,
        3.0,
    )
    assert sfx_audible_duration_s(
        duration_s=4.0, source_in_s=1.0, source_out_s=3.5
    ) == pytest.approx(2.5)
    assert clamp_sfx_start_s(1.25) == 1.25
    with pytest.raises(ValueError):
        clamp_sfx_start_s(-0.1)
    with pytest.raises(ValueError):
        resolve_sfx_trim(duration_s=2.0, source_in_s=1.5, source_out_s=1.5)


def test_sfx_overlay_filter_places_independent_clips() -> None:
    graph = build_sfx_overlay_filter(
        story_s=10.0,
        clips=[
            {
                "start_s": 1.0,
                "source_in_s": 0.0,
                "source_out_s": 2.0,
                "volume": 0.5,
                "fade_in_s": 0.2,
                "fade_out_s": 0.0,
            },
            {
                "start_s": 4.0,
                "source_in_s": 0.5,
                "source_out_s": 1.5,
                "volume": 0.8,
                "fade_in_s": 0.0,
                "fade_out_s": 0.1,
            },
        ],
    )
    assert "adelay=1000:all=1" in graph
    assert "adelay=4000:all=1" in graph
    assert "amix=inputs=3" in graph
    assert "normalize=0" in graph


def test_sfx_db_roundtrip_independent_of_music(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.db.Database._probe_music_duration_s",
        lambda self, path: 3.0,
    )
    db = Database(tmp_path / "orga.sqlite3")
    project = db.ensure_default_studio_project()
    a = _wav(tmp_path, "wind.wav")
    b = _wav(tmp_path, "fire.wav")
    first = db.append_studio_sfx(project.id, str(a), start_s=2.0, volume=0.6)
    second = db.append_studio_sfx(
        project.id,
        str(b),
        start_s=0.5,
        source_in_s=0.2,
        source_out_s=1.8,
        fade_in_s=0.1,
    )
    music = db.append_studio_music(project.id, str(a))
    clips = db.list_studio_sfx(project.id)
    assert [c.id for c in clips] == [second.id, first.id]  # ordered by start_s
    assert clips[0].start_s == pytest.approx(0.5)
    assert clips[0].source_in_s == pytest.approx(0.2)
    assert clips[1].volume == pytest.approx(0.6)
    assert db.list_studio_music(project.id)[0].id == music.id
    patched = db.patch_studio_sfx_clip(project.id, first.id, start_s=5.0, volume=0.0)
    assert patched.start_s == pytest.approx(5.0)
    assert patched.volume == 0.0
    assert db.delete_studio_sfx_clip(project.id, second.id) is True
    assert [c.id for c in db.list_studio_sfx(project.id)] == [first.id]
    assert db.list_studio_music(project.id)  # music untouched


def test_sfx_limit_and_http_undo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.db.Database._probe_music_duration_s",
        lambda self, path: 2.0,
    )
    client, db = _client(tmp_path, monkeypatch)
    project = db.ensure_default_studio_project()
    path = _wav(tmp_path)
    created = []
    for index in range(2):
        response = client.post(
            f"/api/studio/projects/{project.id}/sfx",
            json={"path": str(path), "start_s": float(index), "volume": 0.7},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert len(body["clips"]) == index + 1
        created.append(body["clips"][-1]["id"])
    assert history_flags(project.id)["can_undo"] is True
    assert undo_story(db, project.id) is True
    assert len(db.list_studio_sfx(project.id)) == 1
    listed = client.get(f"/api/studio/projects/{project.id}/sfx").json()
    assert len(listed["clips"]) == 1
    patch = client.patch(
        f"/api/studio/projects/{project.id}/sfx/{listed['clips'][0]['id']}",
        json={"start_s": 3.5, "volume": 0.2},
    )
    assert patch.status_code == 200
    assert patch.json()["clips"][0]["start_s"] == pytest.approx(3.5)
    delete = client.delete(
        f"/api/studio/projects/{project.id}/sfx/{listed['clips'][0]['id']}"
    )
    assert delete.status_code == 200
    assert delete.json()["clips"] == []
    for index in range(STUDIO_SFX_MAX_CLIPS):
        assert (
            client.post(
                f"/api/studio/projects/{project.id}/sfx",
                json={"path": str(path), "start_s": float(index)},
            ).status_code
            == 200
        )
    limited = client.post(
        f"/api/studio/projects/{project.id}/sfx",
        json={"path": str(path), "start_s": 99.0},
    )
    assert limited.status_code == 409
    assert limited.json()["detail"] == "sfx_limit"
