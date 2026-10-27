"""Forward repeat of one video section until a known soundtrack ends.

Joins are hard cuts unless the clip asks for a forward crossfade. The
soundtrack is one continuous pass, not restarted or blended at each video
boundary. A remainder under 0.05s is omitted. 0.001s is the agreement epsilon
shared with preview.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig, StudioExportMusic
from orga_drone.export.studio_encoder import (
    ExportCancelled,
    FfmpegStudioEncoder,
    XFADE_SMOOTH_EXPR,
    build_stitch_filters,
    section_repeat_slices,
)
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_image import ImageAdjust, ffmpeg_grade_chain
from orga_drone.studio_cut import section_repeats_from_effect_settings
from orga_drone.studio_estimate import summarize_studio_items
from orga_drone.studio_export import _clip_to_export_clip
from orga_drone.studio_forward_loop import (
    FORWARD_LOOP_TOLERANCE_S,
    MAX_FORWARD_LOOP_PLAYS,
    applied_loop_overlap_s,
    dump_loop_transition,
    loop_to_soundtrack_enabled,
    loop_transition_curve,
    loop_transition_requested_s,
    plan_forward_loop,
    resolve_forward_loop,
    soundtrack_once_s,
)


def test_plan_trims_the_last_play_and_drops_dust() -> None:
    exact = plan_forward_loop(2.0, 5.0)
    assert exact is not None
    assert exact.full_plays == 2
    assert exact.partial_s == pytest.approx(1.0)
    assert exact.total_s == pytest.approx(5.0)
    assert exact.output_spans() == pytest.approx((2.0, 2.0, 1.0))

    whole = plan_forward_loop(2.0, 4.0)
    assert whole is not None
    assert whole.partial_s == 0
    assert whole.total_s == pytest.approx(4.0)

    dust = plan_forward_loop(2.0, 4.04)
    assert dust is not None
    assert dust.partial_s == 0
    assert dust.total_s == pytest.approx(4.0)
    assert 4.04 - dust.total_s < 0.05

    absorbed = plan_forward_loop(2.0, 4.0 + (FORWARD_LOOP_TOLERANCE_S / 2))
    assert absorbed is not None
    assert absorbed.total_s == pytest.approx(4.0)

    short = plan_forward_loop(3.0, 2.5)
    assert short is not None
    assert short.full_plays == 0
    assert short.partial_s == pytest.approx(2.5)
    assert plan_forward_loop(2.0, 0.01) is None


def test_slices_repeat_forward_and_trim_the_last_span() -> None:
    clip = StudioExportClip(
        source_path=Path("clip.mp4"),
        kind="video",
        duration_s=5.0,
        source_start_s=1.0,
        source_end_s=3.0,
        forward_loop=True,
        forward_cycle_s=2.0,
        fade_in_s=0.2,
        fade_out_s=0.15,
    )
    slices = section_repeat_slices(clip)
    assert [item.duration_s for item in slices] == pytest.approx([2.0, 2.0, 1.0])
    assert slices[0].source_start_s == pytest.approx(1.0)
    assert slices[0].source_end_s == pytest.approx(3.0)
    assert slices[1].source_end_s == pytest.approx(3.0)
    assert slices[2].source_start_s == pytest.approx(1.0)
    assert slices[2].source_end_s == pytest.approx(2.0)
    assert slices[0].fade_in_s == pytest.approx(0.2)
    assert slices[0].fade_out_s == 0
    assert slices[-1].fade_out_s == pytest.approx(0.15)
    assert all(item.forward_loop is False and item.section_repeats == 1 for item in slices)
    assert sum(item.duration_s for item in slices) == pytest.approx(5.0)


def test_slow_motion_partial_uses_source_time() -> None:
    clip = StudioExportClip(
        source_path=Path("clip.mp4"),
        kind="video",
        duration_s=5.0,
        source_start_s=0.0,
        source_end_s=1.0,
        playback_speed=0.5,
        forward_loop=True,
        forward_cycle_s=2.0,
    )
    slices = section_repeat_slices(clip)
    assert [item.duration_s for item in slices] == pytest.approx([2.0, 2.0, 1.0])
    assert slices[0].source_end_s == pytest.approx(1.0)
    assert slices[-1].source_end_s == pytest.approx(0.5)
    assert slices[-1].playback_speed == pytest.approx(0.5)


def test_export_encodes_each_play_and_trims_the_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> None:
        calls.append([str(part) for part in cmd])

    monkeypatch.setattr("orga_drone.export.studio_encoder._run_ffmpeg", fake_run)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"media-bytes")
    clip = StudioExportClip(
        source_path=src,
        kind="video",
        duration_s=5.0,
        source_start_s=1.0,
        source_end_s=3.0,
        forward_loop=True,
        forward_cycle_s=2.0,
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
    texts = [" ".join(cmd) for cmd in trims]
    assert texts[0].count("1.000") >= 1 and "2.000" in texts[0]
    assert "2.000" in texts[1]
    assert "1.000" in texts[2]
    assert "-t" in texts[2]
    for text in texts:
        assert "atempo" not in text
        assert "setpts" not in text
        assert "song.mp3" not in text
        assert "xfade" not in text
    assert src.read_bytes() == b"media-bytes"


def test_mix_plays_the_soundtrack_once_across_video_joins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "orga_drone.export.music_mix.require_readable_music",
        lambda _path: 5.0,
    )
    monkeypatch.setattr(
        "orga_drone.export.studio_encoder._run_ffmpeg",
        lambda cmd, **_kwargs: calls.append([str(part) for part in cmd]),
    )
    music = tmp_path / "song.mp3"
    music.write_bytes(b"audio")
    concat = tmp_path / "concat.mp4"
    concat.write_bytes(b"picture")
    clip = StudioExportClip(
        source_path=tmp_path / "clip.mp4",
        kind="video",
        duration_s=5.0,
        source_start_s=0.0,
        source_end_s=2.0,
        forward_loop=True,
        forward_cycle_s=2.0,
        forward_transition_s=1.0,
    )
    config = StudioExportConfig(
        output_path=tmp_path / "out.mp4",
        width=1280,
        height=720,
        clips=(clip,),
        music_tracks=(
            StudioExportMusic(source_path=music, duration_s=5.0, loop=True),
        ),
    )
    FfmpegStudioEncoder()._mix_music("ffmpeg", concat, tmp_path / "mixed.mp4", config)
    text = " ".join(calls[0])
    assert "-stream_loop" not in text
    assert text.count(str(music)) == 1
    assert "atrim=0:5" in text
    assert text.count(" -i ") == 2

    plain = StudioExportConfig(
        output_path=tmp_path / "plain.mp4",
        width=1280,
        height=720,
        clips=(
            StudioExportClip(
                source_path=tmp_path / "clip.mp4",
                kind="video",
                duration_s=8.0,
            ),
        ),
        music_tracks=(
            StudioExportMusic(source_path=music, duration_s=5.0, loop=True),
        ),
    )
    FfmpegStudioEncoder()._mix_music("ffmpeg", concat, tmp_path / "looped.mp4", plain)
    looped = " ".join(calls[1])
    assert "-stream_loop" in looped


def test_cancel_stops_before_the_next_play(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.export.studio_encoder.find_ffmpeg", lambda: "ffmpeg"
    )
    event = threading.Event()
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> None:
        calls.append(cmd)
        event.set()

    monkeypatch.setattr("orga_drone.export.studio_encoder._run_ffmpeg", fake_run)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"keep-source")
    dest = tmp_path / "out" / "story.mp4"
    dest.parent.mkdir()
    dest.write_bytes(b"keep-dest")
    clip = StudioExportClip(
        source_path=src,
        kind="video",
        duration_s=5.0,
        source_start_s=1.0,
        source_end_s=3.0,
        forward_loop=True,
        forward_cycle_s=2.0,
    )
    config = StudioExportConfig(
        output_path=dest,
        width=320,
        height=180,
        clips=(clip,),
    )
    with pytest.raises(ExportCancelled):
        FfmpegStudioEncoder().render(config, cancel_event=event)
    assert len(calls) == 1
    assert src.read_bytes() == b"keep-source"
    assert dest.read_bytes() == b"keep-dest"


def _seed(db: Database, root: Path, filename: str, duration_s: float) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=filename)
    media_file = root / filename
    media_file.write_bytes(b"media-bytes")
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


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _song(db: Database, folder: Path, name: str, duration_s: float | None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"ID3fake")
    project = db.ensure_default_studio_project()

    def probe(file_path: str) -> float | None:
        return duration_s

    original = db._probe_music_duration_s
    db._probe_music_duration_s = probe  # type: ignore[method-assign]
    try:
        db.append_studio_music(project.id, str(path.resolve()))
    finally:
        db._probe_music_duration_s = original  # type: ignore[method-assign]


def test_unknown_soundtrack_does_not_guess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video_id = _seed(db, tmp_path / "videos", "SHORT.MP4", 8.0)
    _song(db, tmp_path / "music", "unknown.mp3", None)
    page = client.get("/studio", cookies={"lang": "en"})
    assert page.status_code == 200
    assert 'id="inspector-forward-loop"' in page.text
    assert "Soundtrack duration is unknown" in page.text
    assert 'data-forward-loop="0"' in page.text
    saved = client.patch(
        f"/api/studio/{video_id}/forward-loop",
        json={"enabled": True},
    )
    assert saved.status_code == 400
    assert saved.json()["detail"] == "unknown_duration"
    stored = {item.id: item for item in db.list_studio_items()}[video_id]
    assert loop_to_soundtrack_enabled(stored.effect_settings) is False
    assert (tmp_path / "videos" / "SHORT.MP4").read_bytes() == b"media-bytes"


def test_story_matches_soundtrack_and_keeps_manual_repeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video_id = _seed(db, tmp_path / "videos", "SHORT.MP4", 8.0)
    source = tmp_path / "videos" / "SHORT.MP4"
    before = source.read_bytes()
    client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 1.0, "source_out_s": 3.0, "repeats": 4},
    )
    _song(db, tmp_path / "music", "bed.mp3", 5.0)
    enabled = client.patch(
        f"/api/studio/{video_id}/forward-loop",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    body = enabled.json()
    assert body["active"] is True
    assert body["section_repeats"] == 4
    assert body["effective_duration_s"] == pytest.approx(5.0)
    assert body["summary"]["estimated_total_s"] == pytest.approx(5.0)
    stored = {item.id: item for item in db.list_studio_items()}[video_id]
    assert loop_to_soundtrack_enabled(stored.effect_settings) is True
    assert section_repeats_from_effect_settings(stored.effect_settings) == 4
    built = _clip_to_export_clip(
        db,
        stored,
        forward=resolve_forward_loop(
            db.list_studio_items(),
            soundtrack_once_s(db.list_studio_music(stored.project_id)),
        ),
    )
    assert built is not None
    assert built.forward_loop is True
    assert built.duration_s == pytest.approx(5.0)
    slices = section_repeat_slices(built)
    assert sum(item.duration_s for item in slices) == pytest.approx(built.duration_s)
    assert slices[-1].duration_s == pytest.approx(1.0)
    assert source.read_bytes() == before

    page = client.get("/studio")
    assert 'data-forward-loop-active="1"' in page.text
    disabled = client.patch(
        f"/api/studio/{video_id}/forward-loop",
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["active"] is False
    assert disabled.json()["effective_duration_s"] == pytest.approx(8.0)
    assert disabled.json()["section_repeats"] == 4


def test_partial_play_fills_gap_beside_another_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video_id = _seed(db, tmp_path / "videos", "SHORT.MP4", 8.0)
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
    db.add_studio_item(
        photo_item.path,
        identity_key=make_identity_key(
            photo_item.filename, photo_item.size_bytes, photo_item.recorded_at
        ),
        filename=photo_item.filename,
        recorded_at=photo_item.recorded_at,
        kind="photo",
    )
    client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 0.0, "source_out_s": 2.0, "repeats": 1},
    )
    _song(db, tmp_path / "music", "a.mp3", 4.0)
    _song(db, tmp_path / "music", "b.mp3", 6.0)
    enabled = client.patch(
        f"/api/studio/{video_id}/forward-loop",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    body = enabled.json()
    # Photo default is 3s, so the video fills 10 - 3 = 7s: three full 2s plays
    # and a 1s partial. The playlist is the sum of the two known songs.
    assert body["effective_duration_s"] == pytest.approx(7.0)
    assert body["summary"]["estimated_total_s"] == pytest.approx(10.0)
    once = soundtrack_once_s(db.list_studio_music(db.ensure_default_studio_project().id))
    assert once == pytest.approx(10.0)
    summary = summarize_studio_items(db.list_studio_items(), soundtrack_once_s=once)
    assert summary.estimated_total_s == pytest.approx(10.0)


def test_refuses_when_the_section_would_need_too_many_plays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video_id = _seed(db, tmp_path / "videos", "TINY.MP4", 8.0)
    client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 0.0, "source_out_s": 0.05, "repeats": 1},
    )
    _song(db, tmp_path / "music", "long.mp3", 20.0)
    saved = client.patch(
        f"/api/studio/{video_id}/forward-loop",
        json={"enabled": True},
    )
    assert saved.status_code == 400
    assert saved.json()["detail"] == "too_many_plays"
    plays = plan_forward_loop(0.05, 20.0)
    assert plays is not None
    assert plays.play_count > MAX_FORWARD_LOOP_PLAYS


def test_second_clip_cannot_take_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    first = _seed(db, tmp_path / "a", "A.MP4", 8.0)
    second = _seed(db, tmp_path / "b", "B.MP4", 8.0)
    client.patch(
        f"/api/studio/{first}/section",
        json={"source_in_s": 0.0, "source_out_s": 2.0, "repeats": 1},
    )
    _song(db, tmp_path / "music", "bed.mp3", 12.0)
    assert client.patch(
        f"/api/studio/{first}/forward-loop", json={"enabled": True}
    ).status_code == 200
    blocked = client.patch(
        f"/api/studio/{second}/forward-loop", json={"enabled": True}
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "forward_loop_other_clip"


def _story_seconds(spans: list[float], overlap: float) -> float:
    if not spans:
        return 0.0
    return sum(spans) - overlap * (len(spans) - 1)


def test_crossfade_overlap_shortens_each_cycle_and_trims_the_tail() -> None:
    blended = plan_forward_loop(2.0, 5.0, 1.0)
    assert blended is not None
    assert blended.overlap_s == pytest.approx(1.0)
    assert blended.play_count == 4
    assert blended.partial_s == 0
    assert blended.output_spans() == pytest.approx((2.0, 2.0, 2.0, 2.0))
    assert blended.total_s == pytest.approx(5.0)
    assert _story_seconds(list(blended.output_spans()), 1.0) == pytest.approx(5.0)

    partial = plan_forward_loop(2.0, 4.5, 1.0)
    assert partial is not None
    assert partial.output_spans() == pytest.approx((2.0, 2.0, 2.0, 1.5))
    assert partial.partial_s == pytest.approx(1.5)
    assert partial.total_s == pytest.approx(4.5)
    assert _story_seconds(list(partial.output_spans()), 1.0) == pytest.approx(4.5)

    dust = plan_forward_loop(2.0, 4.02, 1.0)
    assert dust is not None
    assert dust.partial_s == 0
    assert dust.total_s == pytest.approx(4.0)
    assert 4.02 - dust.total_s < 0.05

    assert applied_loop_overlap_s(1.2, 2.0) == pytest.approx(1.15)
    assert applied_loop_overlap_s(0.08, 1.0) == 0
    short = plan_forward_loop(0.08, 5.0, applied_loop_overlap_s(0.08, 1.0))
    assert short is not None
    assert short.overlap_s == 0
    assert 0 <= 5.0 - short.total_s < 0.05


def test_crossfade_slices_overlap_and_keep_the_story_length() -> None:
    clip = StudioExportClip(
        source_path=Path("clip.mp4"),
        kind="video",
        duration_s=4.5,
        source_start_s=1.0,
        source_end_s=3.0,
        forward_loop=True,
        forward_cycle_s=2.0,
        forward_transition_s=1.0,
        transition_type="fade_black",
        transition_s=0.4,
    )
    slices = section_repeat_slices(clip)
    assert [item.duration_s for item in slices] == pytest.approx([2.0, 2.0, 2.0, 1.5])
    assert _story_seconds([item.duration_s for item in slices], 1.0) == pytest.approx(4.5)
    assert slices[0].source_start_s == pytest.approx(1.0)
    assert slices[-1].source_end_s == pytest.approx(2.5)
    assert [item.transition_type for item in slices] == ["crossfade", "crossfade", "crossfade", "cut"]
    assert slices[0].transition_s == pytest.approx(1.0)
    assert slices[-1].transition_s == 0
    graph = ";".join(build_stitch_filters(tuple(slices)))
    assert graph.count("xfade=transition=fade:") == 3
    assert "duration=1.0000" in graph
    assert "acrossfade" not in graph
    assert "color=black" not in graph
    assert "fade=t=" not in graph
    assert slices[-1].source_start_s == pytest.approx(1.0)


def test_crossfade_export_blends_forward_without_black_or_music(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> None:
        calls.append([str(part) for part in cmd])

    monkeypatch.setattr("orga_drone.export.studio_encoder._run_ffmpeg", fake_run)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"media-bytes")
    clip = StudioExportClip(
        source_path=src,
        kind="video",
        duration_s=5.0,
        source_start_s=1.0,
        source_end_s=3.0,
        forward_loop=True,
        forward_cycle_s=2.0,
        forward_transition_s=1.0,
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
    texts = [" ".join(cmd) for cmd in calls]
    stitch = texts[-1]
    assert stitch.count("xfade=transition=fade:") == 3
    assert "duration=1.0000" in stitch
    assert "acrossfade" not in stitch
    assert "color=black" not in stitch
    assert "fade=t=" not in stitch
    assert "song" not in stitch
    assert len([text for text in texts if "-ss" in text]) == 4
    assert src.read_bytes() == b"media-bytes"


def test_crossfade_cancel_stops_before_the_stitch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.export.studio_encoder.find_ffmpeg", lambda: "ffmpeg"
    )
    event = threading.Event()
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> None:
        calls.append(cmd)
        event.set()

    monkeypatch.setattr("orga_drone.export.studio_encoder._run_ffmpeg", fake_run)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"keep-source")
    dest = tmp_path / "out" / "story.mp4"
    dest.parent.mkdir()
    dest.write_bytes(b"keep-dest")
    clip = StudioExportClip(
        source_path=src,
        kind="video",
        duration_s=5.0,
        source_start_s=1.0,
        source_end_s=3.0,
        forward_loop=True,
        forward_cycle_s=2.0,
        forward_transition_s=1.0,
    )
    config = StudioExportConfig(
        output_path=dest,
        width=320,
        height=180,
        clips=(clip,),
    )
    with pytest.raises(ExportCancelled):
        FfmpegStudioEncoder().render(config, cancel_event=event)
    assert len(calls) == 1
    assert "xfade" not in " ".join(str(part) for part in calls[0])
    assert src.read_bytes() == b"keep-source"
    assert dest.read_bytes() == b"keep-dest"


def test_crossfade_story_matches_soundtrack_and_off_stays_a_hard_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video_id = _seed(db, tmp_path / "videos", "SHORT.MP4", 8.0)
    source = tmp_path / "videos" / "SHORT.MP4"
    before = source.read_bytes()
    client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 0.0, "source_out_s": 2.0, "repeats": 1},
    )
    _song(db, tmp_path / "music", "bed.mp3", 4.5)
    enabled = client.patch(
        f"/api/studio/{video_id}/forward-loop",
        json={"enabled": True, "transition": "crossfade", "duration_s": 1.0},
    )
    assert enabled.status_code == 200
    body = enabled.json()
    assert body["active"] is True
    assert body["transition"] == "crossfade"
    assert body["overlap_s"] == pytest.approx(1.0)
    assert body["plays"] == 4
    assert body["partial_s"] == pytest.approx(1.5)
    assert body["effective_duration_s"] == pytest.approx(4.5)
    assert body["summary"]["estimated_total_s"] == pytest.approx(4.5)
    stored = {item.id: item for item in db.list_studio_items()}[video_id]
    built = _clip_to_export_clip(
        db,
        stored,
        forward=resolve_forward_loop(
            db.list_studio_items(),
            soundtrack_once_s(db.list_studio_music(stored.project_id)),
        ),
    )
    assert built is not None
    assert built.forward_transition_s == pytest.approx(1.0)
    slices = section_repeat_slices(built)
    assert _story_seconds([item.duration_s for item in slices], 1.0) == pytest.approx(
        built.duration_s
    )
    assert source.read_bytes() == before

    page = client.get("/studio", cookies={"lang": "en"})
    assert 'id="inspector-loop-transition"' in page.text
    assert "Loop effect" in page.text
    assert "data-forward-loop-transition=\"crossfade\"" in page.text

    hard = client.patch(
        f"/api/studio/{video_id}/forward-loop",
        json={"enabled": True, "transition": "off", "duration_s": 1.0},
    )
    assert hard.status_code == 200
    assert hard.json()["transition"] == "off"
    assert hard.json()["overlap_s"] == 0
    assert hard.json()["effective_duration_s"] == pytest.approx(4.5)
    assert hard.json()["plays"] == 3
    assert hard.json()["partial_s"] == pytest.approx(0.5)


def test_crossfade_refuses_when_the_overlap_needs_too_many_plays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video_id = _seed(db, tmp_path / "videos", "SHORT.MP4", 30.0)
    client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 0.0, "source_out_s": 2.0, "repeats": 1},
    )
    _song(db, tmp_path / "music", "long.mp3", 20.0)
    saved = client.patch(
        f"/api/studio/{video_id}/forward-loop",
        json={"enabled": True, "transition": "crossfade", "duration_s": 2.0},
    )
    assert saved.status_code == 400
    assert saved.json()["detail"] == "too_many_plays"
    stored = {item.id: item for item in db.list_studio_items()}[video_id]
    assert loop_to_soundtrack_enabled(stored.effect_settings) is False


def test_loop_crossfade_preview_grades_the_incoming_copy() -> None:
    """The second preview layer is the same clip, not an ungraded source frame.

    A story-neighbor grade left the incoming loop picture on the original
    color and then called the story-overlap helper with no neighbor.
    """
    root = Path(__file__).resolve().parents[1]
    script = (root / "src" / "orga_drone" / "static" / "js" / "studio.js").read_text(
        encoding="utf-8"
    )
    grades = script[script.index("function applyPreviewGrades") : script.index("const IMAGE_ADJUST_FIELDS")]
    assert "const incomingClip = loopBlend ? primary : overlap;" in grades
    preview = script[
        script.index("function applyTransitionPreview") : script.index("function syncPreviewMedia")
    ]
    story_branch = preview.index("} else if (overlap)")
    assert story_branch < preview.index("showOutgoingLayer(hit.overlapClip", story_branch)
    hint = (root / "src" / "orga_drone" / "templates" / "studio.html").read_text(encoding="utf-8")
    assert "keep the clip color settings" in hint
    assert "a double image can remain" in hint
    assert "function cinematicBlendProgress" in script
    assert "return t * t * (3 - 2 * t);" in script
    assert "not an invisible loop" in hint


def _mean_rgb_frames(ffmpeg: str, path: Path, width: int, height: int) -> list[tuple[float, float, float]]:
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=False,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")[-400:]
    frame_bytes = width * height * 3
    assert len(proc.stdout) >= frame_bytes
    means: list[tuple[float, float, float]] = []
    pixels = width * height
    for offset in range(0, len(proc.stdout) - frame_bytes + 1, frame_bytes):
        chunk = proc.stdout[offset : offset + frame_bytes]
        red = sum(chunk[index] for index in range(0, frame_bytes, 3)) / pixels
        green = sum(chunk[index] for index in range(1, frame_bytes, 3)) / pixels
        blue = sum(chunk[index] for index in range(2, frame_bytes, 3)) / pixels
        means.append((red, green, blue))
    return means


def _color_distance(
    left: tuple[float, float, float], right: tuple[float, float, float]
) -> float:
    return sum(abs(a - b) for a, b in zip(left, right, strict=True)) / 3


def _filter_text(cmd: list[str]) -> str:
    if "-vf" in cmd:
        return cmd[cmd.index("-vf") + 1]
    if "-filter_script:v" in cmd:
        return Path(cmd[cmd.index("-filter_script:v") + 1]).read_text(encoding="utf-8")
    if "-filter_complex" in cmd:
        return cmd[cmd.index("-filter_complex") + 1]
    if "-filter_complex_script" in cmd:
        return Path(cmd[cmd.index("-filter_complex_script") + 1]).read_text(encoding="utf-8")
    return ""


def test_forward_crossfade_keeps_grade_on_every_repeated_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A flat clip stays on the grade through every loop join.

    Differing start and end pictures can still ghost. That is not a reason to
    blend longer. An ungraded frame would fall back toward the source gray.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")
    source = tmp_path / "flat.mp4"
    generated = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x808080:s=64x48:r=30:d=2.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2.2",
            "-shortest",
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
    original = source.read_bytes()
    grade = ImageAdjust(exposure=40, contrast=60, saturation=70, warmth=50)
    chain = ffmpeg_grade_chain(grade)
    assert "exposure=" in chain
    assert "contrast=" in chain
    assert "saturation=" in chain
    assert "colortemperature=" in chain

    from orga_drone.export import studio_encoder as encoder_module

    captured: list[tuple[list[str], str]] = []
    real_run = encoder_module._run_ffmpeg

    def recording_run(cmd: list[str], **kwargs: object) -> None:
        copied = cmd.copy()
        captured.append((copied, _filter_text(copied)))
        real_run(cmd, **kwargs)

    monkeypatch.setattr(encoder_module, "_run_ffmpeg", recording_run)
    reference = tmp_path / "graded.mp4"
    looped = tmp_path / "looped.mp4"
    hard = tmp_path / "hard.mp4"
    encoder = FfmpegStudioEncoder()

    def clip(*, story: float, overlap: float) -> StudioExportClip:
        return StudioExportClip(
            source_path=source,
            kind="video",
            duration_s=story,
            source_start_s=0.0,
            source_end_s=2.0,
            forward_loop=True,
            forward_cycle_s=2.0,
            forward_transition_s=overlap,
            image=grade,
        )

    encoder.render(
        StudioExportConfig(
            output_path=reference,
            width=64,
            height=48,
            quality="standard",
            clips=(clip(story=2.0, overlap=0.0),),
        )
    )
    encoder.render(
        StudioExportConfig(
            output_path=looped,
            width=64,
            height=48,
            quality="standard",
            clips=(clip(story=5.0, overlap=1.0),),
        )
    )
    encoder.render(
        StudioExportConfig(
            output_path=hard,
            width=64,
            height=48,
            quality="standard",
            clips=(clip(story=5.0, overlap=0.0),),
        )
    )
    assert source.read_bytes() == original

    segment_texts = [text for cmd, text in captured if "-ss" in cmd]
    assert len(segment_texts) >= 4
    assert all(chain in text for text in segment_texts)
    stitch_texts = [text for _cmd, text in captured if "xfade=transition=fade:" in text]
    assert len(stitch_texts) == 1
    assert "colortemperature=" not in stitch_texts[0]
    assert "eq=" not in stitch_texts[0]

    raw = _mean_rgb_frames(ffmpeg, source, 64, 48)[8]
    graded_frames = _mean_rgb_frames(ffmpeg, reference, 64, 48)
    graded = graded_frames[len(graded_frames) // 2]
    assert _color_distance(graded, raw) > 20

    def assert_graded(path: Path, *, story_s: float) -> list[tuple[float, float, float]]:
        frames = _mean_rgb_frames(ffmpeg, path, 64, 48)
        assert story_s - 0.12 < len(frames) / 30 < story_s + 0.12
        for index, frame in enumerate(frames):
            assert _color_distance(frame, graded) < 8, index
            assert _color_distance(frame, raw) > 20, index
        return frames

    loop_frames = assert_graded(looped, story_s=5.0)
    # Before the first join, inside a 1s overlap, and after the last join.
    for index in (7, 45, 132):
        assert _color_distance(loop_frames[index], graded) < 8
    assert_graded(hard, story_s=5.0)


def test_manual_repeats_crossfade_without_a_soundtrack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video_id = _seed(db, tmp_path / "videos", "SHORT.MP4", 8.0)
    section = client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 0.0, "source_out_s": 2.0, "repeats": 3},
    )
    assert section.status_code == 200
    assert section.json()["effective_duration_s"] == pytest.approx(6.0)
    saved = client.patch(
        f"/api/studio/{video_id}/loop-effect",
        json={"transition": "crossfade", "duration_s": 1.0},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["transition"] == "crossfade"
    assert body["overlap_s"] == pytest.approx(1.0)
    assert body["effective_duration_s"] == pytest.approx(4.0)
    page = client.get("/studio", cookies={"lang": "en"})
    assert 'data-section-repeats="3"' in page.text
    assert 'data-forward-loop-transition="crossfade"' in page.text
    assert "Loop effect" in page.text
    assert "Repeat this section more than once" in page.text
    off = client.patch(
        f"/api/studio/{video_id}/loop-effect",
        json={"transition": "off", "duration_s": 1.0},
    )
    assert off.status_code == 200
    assert off.json()["overlap_s"] == 0
    assert off.json()["effective_duration_s"] == pytest.approx(6.0)
    stored = {item.id: item for item in db.list_studio_items()}[video_id]
    assert loop_to_soundtrack_enabled(stored.effect_settings) is False


def test_manual_crossfade_slices_keep_the_grade_and_skip_black(
    tmp_path: Path,
) -> None:
    clip = StudioExportClip(
        source_path=tmp_path / "clip.mp4",
        kind="video",
        duration_s=4.0,
        source_start_s=0.0,
        source_end_s=2.0,
        section_repeats=3,
        forward_transition_s=1.0,
        image=ImageAdjust(exposure=40, contrast=60, saturation=70, warmth=50),
        transition_type="fade_black",
        transition_s=0.4,
    )
    slices = section_repeat_slices(clip)
    assert [item.transition_type for item in slices] == ["crossfade", "crossfade", "cut"]
    assert slices[0].transition_s == pytest.approx(1.0)
    chain = ffmpeg_grade_chain(slices[0].image)
    assert chain
    assert all(item.image == clip.image for item in slices)
    graph = ";".join(build_stitch_filters(tuple(slices)))
    assert graph.count("xfade=transition=fade:") == 2
    assert "color=black" not in graph
    assert "fade=t=" not in graph


def test_cinematic_blend_duration_curve_and_overlap() -> None:
    stored = dump_loop_transition("{}", "cinematic", 2.5, "smooth")
    assert loop_transition_requested_s(stored) == pytest.approx(2.5)
    assert loop_transition_curve(stored) == "smooth"
    longest = dump_loop_transition(stored, "cinematic", 6.0, "linear")
    assert loop_transition_requested_s(longest) == pytest.approx(5.0)
    assert loop_transition_curve(longest) == "linear"
    short = dump_loop_transition("{}", "cinematic", 0.5, "smooth")
    assert loop_transition_requested_s(short) == pytest.approx(0.5)
    cross = dump_loop_transition(longest, "crossfade", 5.0, "smooth")
    assert loop_transition_requested_s(cross) == pytest.approx(2.0)
    assert "loop_transition_curve" not in cross
    assert applied_loop_overlap_s(8.0, 5.0, maximum=5.0) == pytest.approx(5.0)
    assert applied_loop_overlap_s(4.0, 2.5, maximum=5.0) == pytest.approx(2.5)
    assert applied_loop_overlap_s(3.0, 5.0, maximum=5.0) == pytest.approx(2.95)
    assert applied_loop_overlap_s(2.0, 0.5) == pytest.approx(0.5)
    plan = plan_forward_loop(6.0, 12.0, 2.5)
    assert plan is not None
    assert plan.total_s == pytest.approx(12.0)
    assert plan.overlap_s == pytest.approx(2.5)
    assert plan.play_count >= 2


def test_cinematic_stitch_uses_smoothstep_and_leaves_story_crossfades_linear() -> None:
    clip = StudioExportClip(
        source_path=Path("clip.mp4"),
        kind="video",
        duration_s=13.0,
        source_start_s=0.0,
        source_end_s=6.0,
        section_repeats=3,
        forward_transition_s=2.5,
        forward_transition_curve="smooth",
        image=ImageAdjust(exposure=40, contrast=60, saturation=70, warmth=50),
        transition_type="crossfade",
        transition_s=0.4,
    )
    slices = section_repeat_slices(clip)
    assert [item.transition_curve for item in slices] == ["smooth", "smooth", "linear"]
    assert all(item.image == clip.image for item in slices)
    graph = ";".join(build_stitch_filters(tuple(slices)))
    assert graph.count(f"expr={XFADE_SMOOTH_EXPR}") == 2
    assert "duration=2.5000" in graph
    assert "acrossfade" not in graph
    assert "color=black" not in graph
    assert "fade=t=" not in graph
    half = section_repeat_slices(
        replace(clip, forward_transition_s=0.5, forward_transition_curve="linear", duration_s=17.0)
    )
    half_graph = ";".join(build_stitch_filters(tuple(half)))
    assert "duration=0.5000" in half_graph
    assert "transition=fade:" in half_graph
    assert "transition=custom" not in half_graph
    wide = section_repeat_slices(
        replace(
            clip,
            source_end_s=8.0,
            duration_s=11.0,
            section_repeats=2,
            forward_transition_s=5.0,
        )
    )
    wide_graph = ";".join(build_stitch_filters(tuple(wide)))
    assert "duration=5.0000" in wide_graph
    story = build_stitch_filters(
        (
            StudioExportClip(
                source_path=Path("a.mp4"),
                kind="video",
                duration_s=2.0,
                transition_type="crossfade",
                transition_s=0.4,
            ),
            StudioExportClip(source_path=Path("b.mp4"), kind="video", duration_s=2.0),
        )
    )
    story_graph = ";".join(story)
    assert "transition=fade:" in story_graph
    assert "transition=custom" not in story_graph


def test_cinematic_blend_persists_for_manual_repeats_and_soundtrack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    video_id = _seed(db, tmp_path / "videos", "LONG.MP4", 20.0)
    client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 0.0, "source_out_s": 8.0, "repeats": 2},
    )
    saved = client.patch(
        f"/api/studio/{video_id}/loop-effect",
        json={"transition": "cinematic", "duration_s": 5.0, "curve": "smooth"},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["transition"] == "cinematic"
    assert body["transition_s"] == pytest.approx(5.0)
    assert body["overlap_s"] == pytest.approx(5.0)
    assert body["curve"] == "smooth"
    assert body["effective_duration_s"] == pytest.approx(11.0)
    page = client.get("/studio", cookies={"lang": "en"})
    assert 'data-forward-loop-transition="cinematic"' in page.text
    assert 'data-loop-transition-curve="smooth"' in page.text
    assert "Cinematic blend" in page.text
    assert "not an invisible loop" in page.text
    linear = client.patch(
        f"/api/studio/{video_id}/loop-effect",
        json={"transition": "cinematic", "duration_s": 2.5, "curve": "linear"},
    )
    assert linear.status_code == 200
    assert linear.json()["curve"] == "linear"
    assert linear.json()["overlap_s"] == pytest.approx(2.5)
    assert linear.json()["effective_duration_s"] == pytest.approx(13.5)
    client.patch(
        f"/api/studio/{video_id}/section",
        json={"source_in_s": 0.0, "source_out_s": 6.0, "repeats": 1},
    )
    _song(db, tmp_path / "music", "bed.mp3", 12.0)
    client.patch(f"/api/studio/{video_id}/forward-loop", json={"enabled": True})
    looped = client.patch(
        f"/api/studio/{video_id}/loop-effect",
        json={"transition": "cinematic", "duration_s": 2.5, "curve": "smooth"},
    )
    assert looped.status_code == 200
    loop_body = looped.json()
    plan = plan_forward_loop(6.0, 12.0, 2.5)
    assert plan is not None
    assert loop_body["overlap_s"] == pytest.approx(plan.overlap_s)
    assert loop_body["effective_duration_s"] == pytest.approx(plan.total_s)
    assert loop_body["plays"] == plan.play_count
    assert loop_to_soundtrack_enabled(
        {item.id: item for item in db.list_studio_items()}[video_id].effect_settings
    )


def _color_clip(ffmpeg: str, path: Path, parts: list[tuple[str, float]]) -> None:
    from orga_drone.ffmpeg_bin import subprocess_no_window_kwargs

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for color, duration in parts:
        cmd.extend(["-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=30:d={duration}"])
    filters = [f"[{index}:v]format=yuv420p[v{index}]" for index in range(len(parts))]
    inputs = "".join(f"[v{index}]" for index in range(len(parts)))
    filters.append(f"{inputs}concat=n={len(parts)}:v=1:a=0[v]")
    cmd.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(path),
        ]
    )
    generated = subprocess.run(
        cmd, check=False, capture_output=True, text=True, **subprocess_no_window_kwargs()
    )
    assert generated.returncode == 0, generated.stderr


def _render_repeat(
    ffmpeg: str,
    source: Path,
    dest: Path,
    *,
    cycle_s: float,
    repeats: int,
    overlap_s: float,
    curve: str,
) -> None:
    story = cycle_s * repeats - overlap_s * (repeats - 1)
    clip = StudioExportClip(
        source_path=source,
        kind="video",
        duration_s=story,
        source_start_s=0.0,
        source_end_s=cycle_s,
        section_repeats=repeats,
        forward_transition_s=overlap_s,
        forward_transition_curve=curve,
    )
    FfmpegStudioEncoder()._render_video(
        ffmpeg,
        clip,
        dest,
        64,
        48,
        on_progress=None,
        clip_index=1,
        clip_total=1,
    )


def test_cinematic_export_honors_linear_and_smooth_curves(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")
    source = tmp_path / "split.mp4"
    _color_clip(ffmpeg, source, [("red", 1.0), ("blue", 1.0)])
    before = source.read_bytes()
    smooth = tmp_path / "smooth.mp4"
    linear = tmp_path / "linear.mp4"
    _render_repeat(
        ffmpeg, source, smooth, cycle_s=2.0, repeats=2, overlap_s=1.0, curve="smooth"
    )
    _render_repeat(
        ffmpeg, source, linear, cycle_s=2.0, repeats=2, overlap_s=1.0, curve="linear"
    )
    smooth_frames = _mean_rgb_frames(ffmpeg, smooth, 64, 48)
    linear_frames = _mean_rgb_frames(ffmpeg, linear, 64, 48)
    assert 3.0 - 0.12 < len(smooth_frames) / 30 < 3.0 + 0.12
    assert 3.0 - 0.12 < len(linear_frames) / 30 < 3.0 + 0.12
    index = 38
    progress = index / 30 - 1.0
    eased = progress * progress * (3 - 2 * progress)
    red = smooth_frames[2]
    blue = smooth_frames[-2]

    def expect(weight: float) -> tuple[float, float, float]:
        return tuple(red[channel] * weight + blue[channel] * (1 - weight) for channel in range(3))

    smooth_rgb = smooth_frames[index]
    linear_rgb = linear_frames[index]
    assert _color_distance(smooth_rgb, expect(eased)) < 18
    assert _color_distance(linear_rgb, expect(progress)) < 18
    assert linear_rgb[0] > smooth_rgb[0] + 8
    for frame in (*smooth_frames, *linear_frames):
        assert frame[0] + frame[2] > 160
    half = tmp_path / "half.mp4"
    _render_repeat(
        ffmpeg, source, half, cycle_s=2.0, repeats=3, overlap_s=0.5, curve="linear"
    )
    half_frames = _mean_rgb_frames(ffmpeg, half, 64, 48)
    assert 5.0 - 0.15 < len(half_frames) / 30 < 5.0 + 0.15
    long_source = tmp_path / "long.mp4"
    _color_clip(ffmpeg, long_source, [("red", 4.0), ("blue", 4.0)])
    two_five = tmp_path / "two-five.mp4"
    five = tmp_path / "five.mp4"
    _render_repeat(
        ffmpeg,
        long_source,
        two_five,
        cycle_s=6.0,
        repeats=2,
        overlap_s=2.5,
        curve="smooth",
    )
    _render_repeat(
        ffmpeg, long_source, five, cycle_s=8.0, repeats=2, overlap_s=5.0, curve="smooth"
    )
    assert 9.5 - 0.2 < len(_mean_rgb_frames(ffmpeg, two_five, 64, 48)) / 30 < 9.5 + 0.2
    five_frames = _mean_rgb_frames(ffmpeg, five, 64, 48)
    assert 11.0 - 0.2 < len(five_frames) / 30 < 11.0 + 0.2
    midpoint = five_frames[len(five_frames) // 2]
    assert midpoint[0] + midpoint[2] > 160
    assert source.read_bytes() == before
