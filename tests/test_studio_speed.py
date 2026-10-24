"""Slow motion for a selected source range inside a Studio video clip."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import FfmpegStudioEncoder, _segment_chain
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_cut import SourceRange
from orga_drone.studio_estimate import effective_seconds, summarize_studio_items
from orga_drone.studio_speed import (
    ffmpeg_slow_stretch,
    normalize_playback_speed,
    output_duration_s,
    plan_speed_segments,
    source_offset_s,
    timeline_offset_s,
)


def _seed_media(
    db: Database,
    root_path: Path,
    *,
    filename: str,
    content: bytes,
    kind: str = "video",
    duration_s: float | None = 10.0,
) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / filename
    media_file.write_bytes(content)
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": str(media_file.resolve()),
            "size_bytes": len(content),
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


def _add_item(db: Database, media_id: int) -> int:
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


def test_speed_rejects_fast_forward_reverse_and_zero() -> None:
    for value in (2, 1.5, 0, -1, 4):
        with pytest.raises(ValueError, match="1, 0.5, or 0.25"):
            normalize_playback_speed(value)
    assert normalize_playback_speed(1) == 1.0
    assert normalize_playback_speed(0.5) == 0.5
    assert normalize_playback_speed(0.25) == 0.25
    with pytest.raises(ValueError):
        normalize_playback_speed(True)


def test_duration_follows_time_not_frame_count() -> None:
    # A 10 fps one-second source at 0.25× is 4 story seconds, not a new frame rate.
    assert output_duration_s(1.0, 0.25) == pytest.approx(4.0)
    assert output_duration_s(1.0 / 10.0, 0.5) == pytest.approx(0.2)
    assert output_duration_s(2.0, 0.5) == pytest.approx(4.0)
    assert timeline_offset_s(1.5, 0.5) == pytest.approx(3.0)
    assert source_offset_s(3.0, 0.5) == pytest.approx(1.5)


def test_plan_slows_only_the_selected_section() -> None:
    rang = SourceRange(0.0, 10.0)
    segments, selected = plan_speed_segments(
        rang, current_speed=1.0, range_in_s=2.0, range_out_s=4.0, speed=0.5
    )
    assert selected == 1
    assert [(s.source_in_s, s.source_out_s, s.speed) for s in segments] == [
        (0.0, 2.0, 1.0),
        (2.0, 4.0, 0.5),
        (4.0, 10.0, 1.0),
    ]
    assert sum(s.output_duration_s for s in segments) == pytest.approx(12.0)


def test_plan_on_an_existing_cut_uses_clip_local_time() -> None:
    rang = SourceRange(4.0, 10.0)
    segments, selected = plan_speed_segments(
        rang, current_speed=1.0, range_in_s=1.0, range_out_s=3.0, speed=0.25
    )
    assert selected == 1
    assert segments[0].source_in_s == pytest.approx(4.0)
    assert segments[1].source_in_s == pytest.approx(5.0)
    assert segments[1].source_out_s == pytest.approx(7.0)
    assert segments[1].speed == 0.25
    assert segments[1].output_duration_s == pytest.approx(8.0)
    assert segments[2].speed == 1.0
    assert sum(s.output_duration_s for s in segments) == pytest.approx(12.0)


def test_plan_keeps_neighbor_speed_and_rejects_edges() -> None:
    rang = SourceRange(0.0, 6.0)
    segments, selected = plan_speed_segments(
        rang, current_speed=0.5, range_in_s=1.0, range_out_s=3.0, speed=0.25
    )
    assert selected == 1
    assert [s.speed for s in segments] == [0.5, 0.25, 0.5]
    whole, index = plan_speed_segments(
        rang, current_speed=0.5, range_in_s=None, range_out_s=None, speed=1.0
    )
    assert index == 0
    assert len(whole) == 1
    assert whole[0].speed == 1.0
    with pytest.raises(ValueError, match="usable section"):
        plan_speed_segments(
            rang, current_speed=1.0, range_in_s=0.02, range_out_s=2.0, speed=0.5
        )
    with pytest.raises(ValueError, match="inside"):
        plan_speed_segments(
            rang, current_speed=1.0, range_in_s=0.0, range_out_s=9.0, speed=0.5
        )
    with pytest.raises(ValueError, match="1, 0.5, or 0.25"):
        plan_speed_segments(
            rang, current_speed=1.0, range_in_s=1.0, range_out_s=2.0, speed=2
        )


def test_stretch_filter_holds_frames_after_fps() -> None:
    assert ffmpeg_slow_stretch(0.5) == "setpts=2.0*PTS"
    assert ffmpeg_slow_stretch(0.25) == "setpts=4.0*PTS"
    half = StudioExportClip(
        source_path=Path("clip.mp4"),
        kind="video",
        duration_s=4.0,
        source_start_s=1.0,
        source_end_s=3.0,
        playback_speed=0.5,
    )
    chain = _segment_chain(64, 48, half)
    assert chain.startswith("trim=start=1.000000:end=3.000000,setpts=PTS-STARTPTS")
    assert "setpts=2.0*PTS" in chain
    assert chain.index("fps=") < chain.index("setpts=2.0*PTS")
    normal = StudioExportClip(
        source_path=Path("clip.mp4"),
        kind="video",
        duration_s=2.0,
        source_start_s=0.0,
        source_end_s=2.0,
        playback_speed=1.0,
    )
    assert "trim=" not in _segment_chain(64, 48, normal)


def test_speed_persists_and_updates_story_length(tmp_path: Path) -> None:
    db_path = tmp_path / "t.sqlite3"
    db = Database(db_path)
    media_id = _seed_media(db, tmp_path / "lib", filename="SLOW.MP4", content=b"slow")
    clip_id = _add_item(db, media_id)
    changed, selected = db.set_studio_playback_speed(clip_id, 0.5)
    assert selected == clip_id
    assert len(changed) == 1
    assert changed[0].playback_speed == pytest.approx(0.5)
    items = db.list_studio_items()
    assert summarize_studio_items(items).estimated_total_s == pytest.approx(20.0)
    assert (
        effective_seconds(
            kind="video",
            photo_duration_s=None,
            duration_s=changed[0].duration_s,
            available=True,
            source_in_s=changed[0].source_in_s,
            source_out_s=changed[0].source_out_s,
            playback_speed=changed[0].playback_speed,
        )
        == pytest.approx(20.0)
    )
    reopened = Database(db_path)
    again = reopened.list_studio_items()
    assert again[0].playback_speed == pytest.approx(0.5)
    reset, _selected = reopened.set_studio_playback_speed(clip_id, 1.0)
    assert reset[0].playback_speed == pytest.approx(1.0)
    assert summarize_studio_items(reopened.list_studio_items()).estimated_total_s == pytest.approx(
        10.0
    )


def test_partial_range_splits_and_shifts_the_next_clip(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    first_media = _seed_media(db, tmp_path / "a", filename="A.MP4", content=b"aaaa")
    second_media = _seed_media(db, tmp_path / "b", filename="B.MP4", content=b"bbbb")
    first = _add_item(db, first_media)
    second = _add_item(db, second_media)
    db.set_studio_transition(first, "crossfade", 0.5)
    pieces, selected = db.set_studio_playback_speed(first, 0.5, 2.0, 4.0)
    assert [p.playback_speed for p in pieces] == pytest.approx([1.0, 0.5, 1.0])
    assert pieces[1].id == selected
    assert pieces[0].transition == "cut"
    assert pieces[-1].transition == "crossfade"
    assert pieces[1].source_in_s == pytest.approx(2.0)
    assert pieces[1].source_out_s == pytest.approx(4.0)
    items = db.list_studio_items()
    assert [i.position for i in items] == [1, 2, 3, 4]
    assert items[-1].id == second
    assert items[-1].playback_speed == pytest.approx(1.0)
    # 2s + 4s slowed + 6s + the untouched 10s clip. Crossfade overlaps 0.5s.
    assert summarize_studio_items(items).estimated_total_s == pytest.approx(21.5)


def test_speed_on_a_cut_segment_does_not_change_the_other_half(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    media_id = _seed_media(db, tmp_path / "lib", filename="CUT.MP4", content=b"cut")
    clip_id = _add_item(db, media_id)
    left, right = db.cut_studio_video_item(clip_id, 4.0)
    pieces, selected = db.set_studio_playback_speed(right.id, 0.25, 1.0, 3.0)
    assert [p.source_in_s for p in pieces] == pytest.approx([4.0, 5.0, 7.0])
    assert pieces[1].id == selected
    assert pieces[1].playback_speed == pytest.approx(0.25)
    items = {item.id: item for item in db.list_studio_items()}
    assert items[left.id].source_out_s == pytest.approx(4.0)
    assert items[left.id].playback_speed == pytest.approx(1.0)
    total = summarize_studio_items(db.list_studio_items()).estimated_total_s
    assert total == pytest.approx(16.0)


def test_speed_rejects_photo_and_fast_forward(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    video_id = _add_item(
        db, _seed_media(db, tmp_path / "v", filename="V.MP4", content=b"v")
    )
    photo_id = _add_item(
        db,
        _seed_media(
            db,
            tmp_path / "p",
            filename="P.JPG",
            content=b"p",
            kind="photo",
            duration_s=None,
        ),
    )
    with pytest.raises(ValueError, match="only video"):
        db.set_studio_playback_speed(photo_id, 0.5)
    with pytest.raises(ValueError, match="1, 0.5, or 0.25"):
        db.set_studio_playback_speed(video_id, 2.0)
    with pytest.raises(ValueError, match="1, 0.5, or 0.25"):
        db.set_studio_playback_speed(video_id, -1)
    kept = next(item for item in db.list_studio_items() if item.id == video_id)
    assert kept.playback_speed == pytest.approx(1.0)


def test_http_speed_range_and_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    media_id = _seed_media(db, tmp_path / "lib", filename="HTTP.MP4", content=b"http")
    clip_id = _add_item(db, media_id)
    client = TestClient(app)

    page = client.get("/studio")
    assert page.status_code == 200
    assert 'id="inspector-speed"' in page.text
    assert "Von (s)" in page.text or "From (s)" in page.text

    rejected = client.post(f"/api/studio/{clip_id}/speed", json={"speed": 2})
    assert rejected.status_code == 400

    missing_end = client.post(
        f"/api/studio/{clip_id}/speed",
        json={"speed": 0.5, "range_in_s": 1.0},
    )
    assert missing_end.status_code == 400

    ok = client.post(
        f"/api/studio/{clip_id}/speed",
        json={"speed": 0.25, "range_in_s": 2.0, "range_out_s": 4.0},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert [clip["playback_speed"] for clip in body["clips"]] == pytest.approx(
        [1.0, 0.25, 1.0]
    )
    slowed = body["clips"][1]
    assert slowed["id"] == body["selected_id"]
    assert slowed["effective_duration_s"] == pytest.approx(8.0)
    assert body["summary"]["estimated_total_s"] == pytest.approx(16.0)


def test_slow_export_duration_on_low_fps_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")
    source = tmp_path / "ten-fps.mp4"
    generated = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x48:r=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0, generated.stderr
    source_bytes = source.read_bytes()

    from orga_drone.export import studio_encoder as encoder_module

    commands: list[list[str]] = []
    real_run = encoder_module._run_ffmpeg

    def recording_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        commands.append(cmd.copy())
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(encoder_module, "_run_ffmpeg", recording_run)
    output = tmp_path / "slow.mp4"
    config = StudioExportConfig(
        output_path=output,
        width=64,
        height=48,
        clips=(
            StudioExportClip(
                source_path=source,
                kind="video",
                duration_s=1.0,
                source_start_s=0.0,
                source_end_s=0.5,
                playback_speed=0.5,
            ),
        ),
    )
    assert FfmpegStudioEncoder().render(config) == output
    assert source.read_bytes() == source_bytes
    segment = next(cmd for cmd in commands if any("trim=start=0.000000:end=0.500000" in part for part in cmd))
    joined = " ".join(segment)
    assert "setpts=2.0*PTS" in joined
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in joined
    assert "-ss" not in segment
    assert "0:a:0" not in joined

    probed = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert "Audio: aac" in probed.stderr
    duration_match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", probed.stderr)
    assert duration_match is not None
    hours, minutes, seconds = duration_match.groups()
    duration_s = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    # 0.5s of a 10 fps source at 0.5× is 1.0s, not the whole 1s file and not 0.5s.
    assert duration_s == pytest.approx(1.0, abs=0.25)
