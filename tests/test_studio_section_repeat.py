"""Video section repeat: in/out range played again, capped at 8 (Issue #112)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip
from orga_drone.export.studio_encoder import FfmpegStudioEncoder, section_repeat_slices
from orga_drone.studio_cut import (
    MAX_SECTION_REPEATS,
    parse_section_repeats,
    section_playback_point,
    section_repeats_from_effect_settings,
)
from orga_drone.studio_estimate import effective_seconds, summarize_studio_items
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_image import image_adjust_from_effect_settings


def test_repeat_count_caps_at_eight_and_rejects_fractions() -> None:
    assert parse_section_repeats(1) == 1
    assert parse_section_repeats(3) == 3
    assert parse_section_repeats(9) == MAX_SECTION_REPEATS
    assert parse_section_repeats(8.0) == 8
    with pytest.raises(ValueError):
        parse_section_repeats(0)
    with pytest.raises(ValueError):
        parse_section_repeats(1.5)
    with pytest.raises(ValueError):
        parse_section_repeats(True)
    with pytest.raises(ValueError):
        parse_section_repeats("2")


def test_playback_point_covers_short_ranges_and_boundaries() -> None:
    assert section_playback_point(0.0, 0.5, 3) == (0, 0.0)
    assert section_playback_point(0.2, 0.5, 3) == pytest.approx((0, 0.2))
    assert section_playback_point(0.5, 0.5, 3) == pytest.approx((1, 0.0))
    assert section_playback_point(1.25, 0.5, 3) == pytest.approx((2, 0.25))
    index, offset = section_playback_point(1.5, 0.5, 3)
    assert index == 2
    assert offset == pytest.approx(0.5)
    assert section_playback_point(4.0, 10.0, 1) == (0, 4.0)
    assert effective_seconds(
        kind="video",
        photo_duration_s=None,
        duration_s=10.0,
        available=True,
        source_in_s=1.0,
        source_out_s=1.2,
        section_repeats=1,
    ) == pytest.approx(0.2)


def _seed(db: Database, root: Path, filename: str, duration_s: float) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=filename)
    media_file = root / filename
    media_file.write_bytes(b"media")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": media_file.stat().st_size,
            "duration_s": duration_s,
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
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
    )
    return clip_id


def _seconds(clip: object) -> float:
    from orga_drone.studio_transition import item_effective_seconds

    seconds = item_effective_seconds(clip)
    assert seconds is not None
    return seconds


def test_section_grows_story_and_reopens(tmp_path: Path) -> None:
    db = Database(tmp_path / "library.sqlite")
    first = _seed(db, tmp_path / "a", "A.MP4", 10.0)
    second = _seed(db, tmp_path / "b", "B.MP4", 8.0)
    db.set_studio_image_adjust(first, {"exposure": 12})
    stored = db.set_studio_section(
        first, source_in_s=1.0, source_out_s=1.2, repeats=3
    )
    assert stored.source_start == pytest.approx(1.0)
    assert stored.source_end == pytest.approx(1.2)
    assert section_repeats_from_effect_settings(stored.effect_settings) == 3
    assert stored.playback_speed == pytest.approx(1.0)
    assert image_adjust_from_effect_settings(stored.effect_settings).exposure == 12
    assert _seconds(stored) == pytest.approx(0.6)

    other = db.set_studio_section(
        second, source_in_s=0.0, source_out_s=0.25, repeats=4
    )
    assert _seconds(other) == pytest.approx(1.0)
    summary = summarize_studio_items(db.list_studio_items())
    assert summary.estimated_total_s == pytest.approx(1.6)

    capped = db.set_studio_section(
        first, source_in_s=1.0, source_out_s=1.2, repeats=12
    )
    assert section_repeats_from_effect_settings(capped.effect_settings) == 8
    assert _seconds(capped) == pytest.approx(1.6)

    full = db.set_studio_section(second, source_in_s=0.0, source_out_s=8.0, repeats=2)
    assert full.source_start is None
    assert full.source_end is None
    assert _seconds(full) == pytest.approx(16.0)

    edge = db.set_studio_section(first, source_in_s=9.0, source_out_s=99.0, repeats=2)
    assert edge.source_start == pytest.approx(9.0)
    assert edge.source_end == pytest.approx(10.0)
    assert _seconds(edge) == pytest.approx(2.0)

    once = db.set_studio_section(first, source_in_s=9.0, source_out_s=10.0, repeats=1)
    assert section_repeats_from_effect_settings(once.effect_settings) == 1
    assert "section_repeats" not in once.effect_settings
    assert _seconds(once) == pytest.approx(1.0)

    reopened = Database(tmp_path / "library.sqlite")
    again = {item.id: item for item in reopened.list_studio_items()}
    assert section_repeats_from_effect_settings(again[second].effect_settings) == 2
    assert _seconds(again[second]) == pytest.approx(16.0)
    assert again[first].playback_speed == pytest.approx(1.0)

    with pytest.raises(ValueError):
        db.set_studio_section(second, source_in_s=3.0, source_out_s=3.0, repeats=2)
    with pytest.raises(ValueError):
        db.set_studio_section(second, source_in_s=4.0, source_out_s=1.0, repeats=2)


def test_repeat_slices_keep_speed_and_join_as_cuts() -> None:
    clip = StudioExportClip(
        source_path=Path("clip.mp4"),
        kind="video",
        duration_s=1.2,
        source_start_s=1.0,
        source_end_s=1.4,
        section_repeats=3,
        fade_in_s=0.2,
        fade_out_s=0.15,
    )
    slices = section_repeat_slices(clip)
    assert len(slices) == 3
    assert sum(item.duration_s for item in slices) == pytest.approx(1.2)
    assert slices[0].fade_in_s == pytest.approx(0.2)
    assert slices[0].fade_out_s == 0
    assert slices[1].fade_in_s == 0 and slices[1].fade_out_s == 0
    assert slices[2].fade_out_s == pytest.approx(0.15)
    for item in slices:
        assert item.source_start_s == pytest.approx(1.0)
        assert item.source_end_s == pytest.approx(1.4)
        assert item.duration_s == pytest.approx(0.4)
        assert item.section_repeats == 1
        assert item.exact_span is True
    plain = StudioExportClip(
        source_path=Path("clip.mp4"), kind="video", duration_s=4.0
    )
    assert section_repeat_slices(plain) == (plain,)


def test_export_encodes_each_play_without_changing_speed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> None:
        calls.append([str(part) for part in cmd])

    monkeypatch.setattr("orga_drone.export.studio_encoder._run_ffmpeg", fake_run)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"media")
    clip = StudioExportClip(
        source_path=src,
        kind="video",
        duration_s=0.6,
        source_start_s=2.0,
        source_end_s=2.2,
        section_repeats=3,
    )
    FfmpegStudioEncoder()._render_video(
        "ffmpeg",
        clip,
        tmp_path / "out.mp4",
        1280,
        720,
        on_progress=None,
        clip_index=1,
        clip_total=1,
    )
    trims = [cmd for cmd in calls if "-ss" in cmd]
    assert len(trims) == 3
    for cmd in trims:
        text = " ".join(cmd)
        assert "2.000" in text
        assert "0.200" in text
        assert "atempo" not in text
        assert "setpts" not in text
    assert len(calls) == 4


def test_http_section_persists_and_leaves_photos_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    video_id = _seed(db, tmp_path / "videos", "V.MP4", 6.0)
    root = tmp_path / "photos"
    root.mkdir()
    photo = root / "P.JPG"
    photo.write_bytes(b"photo")
    photo_id = db.upsert_media(
        {
            "root_id": db.add_root(root, label="photos"),
            "primary_asset_id": None,
            "kind": "photo",
            "filename": "P.JPG",
            "path": str(photo.resolve()),
            "size_bytes": photo.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": 1,
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
    photo_item = db.get_media(photo_id)
    assert photo_item is not None
    photo_clip, _created = db.add_studio_item(
        photo_item.path,
        identity_key=make_identity_key(
            photo_item.filename, photo_item.size_bytes, photo_item.recorded_at
        ),
        filename=photo_item.filename,
        recorded_at=photo_item.recorded_at,
        kind="photo",
    )
    client = TestClient(app)
    page = client.get("/studio")
    assert page.status_code == 200
    assert 'id="inspector-section-repeats"' in page.text
    assert 'max="8"' in page.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "function sectionPoint" in script
    assert "sectionRepeats(hit.clip) > 1" in script

    saved = client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 1.0, "source_out_s": 2.5, "repeats": 2},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["section_repeats"] == 2
    assert body["effective_duration_s"] == pytest.approx(3.0)
    stored = {item.id: item for item in db.list_studio_items()}[video_id]
    built = _clip_to_export_clip(db, stored)
    assert built is not None
    assert built.section_repeats == 2
    assert built.duration_s == pytest.approx(3.0)
    assert sum(item.duration_s for item in section_repeat_slices(built)) == pytest.approx(3.0)

    capped = client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 1.0, "source_out_s": 2.5, "repeats": 20},
    )
    assert capped.status_code == 200
    assert capped.json()["section_repeats"] == 8

    fraction = client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 1.0, "source_out_s": 2.5, "repeats": 2.5},
    )
    assert fraction.status_code == 400
    blocked = client.patch(
        f"/api/studio/{photo_clip}/section",
        json={"source_in_s": 0, "source_out_s": 1, "repeats": 2},
    )
    assert blocked.status_code == 400
    assert db.list_studio_items()[0].playback_speed == pytest.approx(1.0)


def test_section_api_duration_includes_playback_speed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    video_id = _seed(db, tmp_path / "videos", "SLOW.MP4", 8.0)
    db.set_studio_playback_speed(video_id, 0.25)
    client = TestClient(app)
    saved = client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 1.0, "source_out_s": 2.0, "repeats": 2},
    )
    assert saved.status_code == 200
    body = saved.json()
    expected = effective_seconds(
        kind="video",
        photo_duration_s=None,
        duration_s=8.0,
        available=True,
        source_in_s=1.0,
        source_out_s=2.0,
        playback_speed=0.25,
        section_repeats=2,
    )
    assert body["effective_duration_s"] == pytest.approx(8.0)
    assert body["effective_duration_s"] == pytest.approx(expected)
    stored = {item.id: item for item in db.list_studio_items()}[video_id]
    summary = summarize_studio_items(db.list_studio_items())
    assert summary.estimated_total_s == pytest.approx(8.0)
    built = _clip_to_export_clip(db, stored)
    assert built is not None
    assert built.duration_s == pytest.approx(8.0)
