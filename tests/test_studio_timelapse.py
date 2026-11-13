"""Timelapse draft helpers and flat-ramp export evidence for issue #325."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from orga_drone.export.studio_config import (
    StudioExportClip,
    StudioExportConfig,
    StudioExportMusic,
)
from orga_drone.export.studio_encoder import FfmpegStudioEncoder
from orga_drone.export.studio_frame_plan import frame_index, plan_story_frames
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_speed_ramp import MAX_SPEED, Point, SpeedRamp, parse_ramp
from orga_drone.studio_timelapse import (
    CONFIRM_REPLACE_RAMP,
    draft_from_speed,
    draft_from_target,
    flat_timelapse_payload,
    is_hard_timelapse_conflict,
    timelapse_conflict,
)


def test_target_and_speed_stay_synchronized() -> None:
    eight = draft_from_target(120.0, 15.0)
    assert eight.speed == pytest.approx(8.0)
    assert draft_from_speed(120.0, 8.0).target_duration_s == pytest.approx(15.0)

    twenty = draft_from_target(300.0, 15.0)
    assert twenty.speed == pytest.approx(20.0)
    assert draft_from_speed(300.0, 20.0).target_duration_s == pytest.approx(15.0)

    trimmed = draft_from_target(60.0, 15.0)
    assert trimmed.speed == pytest.approx(4.0)


def test_unsupported_ratios_and_conflicts_do_not_mutate() -> None:
    with pytest.raises(ValueError):
        draft_from_target(120.0, 5.0)  # 24× beyond validated cap
    with pytest.raises(ValueError):
        draft_from_speed(10.0, 0.5)
    with pytest.raises(ValueError):
        draft_from_speed(10.0, 20.001)
    with pytest.raises(ValueError):
        flat_timelapse_payload(0.0, 10.0, 1.0)
    soft = timelapse_conflict(has_ramp=True, section_repeats=1, forward_loop=False)
    assert soft == CONFIRM_REPLACE_RAMP
    assert not is_hard_timelapse_conflict(soft)
    assert (
        timelapse_conflict(
            has_ramp=True, section_repeats=1, forward_loop=False, replace_confirmed=True
        )
        is None
    )
    assert is_hard_timelapse_conflict(
        timelapse_conflict(has_ramp=False, section_repeats=2, forward_loop=False)
    )
    assert is_hard_timelapse_conflict(
        timelapse_conflict(has_ramp=False, section_repeats=1, forward_loop=True)
    )
    # Hard blocks win over a pending ramp replace confirm.
    assert is_hard_timelapse_conflict(
        timelapse_conflict(has_ramp=True, section_repeats=2, forward_loop=False)
    )
    assert timelapse_conflict(has_ramp=False, section_repeats=1, forward_loop=False) is None


def test_flat_timelapse_payload_parses_at_validated_speeds() -> None:
    for speed, span in ((8.0, 120.0), (20.0, 300.0)):
        payload = flat_timelapse_payload(0.0, span, speed)
        ramp = parse_ramp(payload, media_duration_s=span)
        assert ramp.duration(0.0, span) == pytest.approx(span / speed)
        assert MAX_SPEED >= speed


def _synthetic_source(tmp_path: Path, ffmpeg: str, *, seconds: float, width: int, height: int) -> Path:
    frames = tmp_path / "frames"
    frames.mkdir()
    count = int(round(seconds * 30))
    for n in range(count):
        image = Image.new("RGB", (width, height), (n % 256, 40, 80))
        draw = ImageDraw.Draw(image)
        for bit in range(12):
            draw.rectangle(
                (bit * 4, 0, bit * 4 + 3, 7),
                fill="white" if n & (1 << bit) else "black",
            )
        image.save(frames / f"{n:04d}.png")
    source = tmp_path / f"src_{width}x{height}.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-framerate",
            "30",
            "-i",
            str(frames / "%04d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=120,
        **subprocess_no_window_kwargs(),
    )
    return source


@pytest.mark.parametrize(
    ("speed", "width", "height", "source_in", "source_out"),
    [
        (8.0, 1920, 1080, 0.0, 8.0),
        (20.0, 1920, 1080, 2.0, 12.0),
        (8.0, 3840, 2160, 0.0, 6.0),
        (20.0, 3840, 2160, 0.0, 10.0),
    ],
)
def test_decoded_flat_timelapse_exports_match_frame_grid(
    tmp_path: Path,
    speed: float,
    width: int,
    height: int,
    source_in: float,
    source_out: float,
) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    source = _synthetic_source(
        tmp_path, ffmpeg, seconds=max(source_out, 10.0), width=width, height=height
    )
    original = source.read_bytes()
    ramp = SpeedRamp((Point(source_in, speed), Point(source_out, speed)))
    duration = ramp.duration(source_in, source_out)
    clip = StudioExportClip(
        source,
        "video",
        duration,
        source_start_s=source_in,
        source_end_s=source_out,
        speed_ramp=ramp,
    )
    out = tmp_path / "out.mp4"
    render_clips, _ = plan_story_frames((clip,))
    expected = render_clips[0].export_frame_count
    assert expected == frame_index(duration) - frame_index(0.0)
    FfmpegStudioEncoder().render(StudioExportConfig(out, width, height, clips=(clip,)))
    raw = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(out),
            "-map",
            "0:v:0",
            "-fps_mode",
            "passthrough",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=180,
        **subprocess_no_window_kwargs(),
    ).stdout
    assert len(raw) // (width * height * 3) == expected
    assert source.read_bytes() == original


def test_non_grid_story_start_changes_exported_frame_count() -> None:
    """Inspector target*30 is approximate; absolute Story snaps own the count."""
    from orga_drone.export.studio_frame_plan import frame_index, plan_story_frames

    ramp = SpeedRamp((Point(0.0, 8.0), Point(15.1, 8.0)))
    duration = ramp.duration(0.0, 15.1)
    naive = int(duration * 30 + 0.5 + 1e-8)
    assert naive == 57
    lead = StudioExportClip(Path("lead.mp4"), "video", 0.02, source_end_s=0.02)
    timed = StudioExportClip(
        Path("timed.mp4"),
        "video",
        duration,
        source_end_s=15.1,
        speed_ramp=ramp,
    )
    render, _ = plan_story_frames((lead, timed))
    assert len(render) == 2
    origin = render[1].export_frame_origin_s or 0.0
    assert origin == pytest.approx(0.02)
    assert render[1].export_frame_count == frame_index(0.02 + duration) - frame_index(0.02)
    assert render[1].export_frame_count == 56
    assert render[1].export_frame_count != naive


def test_mixed_story_with_flat_timelapse_keeps_shared_grid(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    source = _synthetic_source(tmp_path, ffmpeg, seconds=8.0, width=320, height=180)
    ramp = SpeedRamp((Point(0.0, 8.0), Point(8.0, 8.0)))
    clips = (
        StudioExportClip(source, "video", 1.0, source_end_s=1.0),
        StudioExportClip(
            source,
            "video",
            ramp.duration(0.0, 8.0),
            source_end_s=8.0,
            speed_ramp=ramp,
        ),
        StudioExportClip(source, "video", 0.5, source_start_s=1.0, source_end_s=1.5),
    )
    render_clips, _stitch = plan_story_frames(clips)
    expected = sum(c.export_frame_count or 0 for c in render_clips)
    out = tmp_path / "mixed.mp4"
    FfmpegStudioEncoder().render(StudioExportConfig(out, 320, 180, clips=clips))
    raw = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(out),
            "-map",
            "0:v:0",
            "-fps_mode",
            "passthrough",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=60,
        **subprocess_no_window_kwargs(),
    ).stdout
    assert len(raw) // (320 * 180 * 3) == expected


def _video_frame_count(ffmpeg: str, path: Path, width: int, height: int) -> int:
    raw = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-fps_mode",
            "passthrough",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=180,
        **subprocess_no_window_kwargs(),
    ).stdout
    return len(raw) // (width * height * 3)


def _audio_seconds(ffmpeg: str, path: Path) -> float:
    raw = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "s16le",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=60,
        **subprocess_no_window_kwargs(),
    ).stdout
    return (len(raw) // 2) / 48000


def test_target_duration_export_keeps_draft_frames_and_music(tmp_path: Path) -> None:
    """A trimmed target duration uses the existing flat ramp and story mix."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    source_in, source_out = 0.5, 2.5
    draft = draft_from_target(source_out - source_in, 0.5)
    assert draft.speed == pytest.approx(4.0)
    source = _synthetic_source(tmp_path, ffmpeg, seconds=3.0, width=320, height=180)
    original = source.read_bytes()
    ramp = parse_ramp(
        flat_timelapse_payload(source_in, source_out, draft.speed),
        media_duration_s=3.0,
    )
    duration = ramp.duration(source_in, source_out)
    clip = StudioExportClip(
        source,
        "video",
        duration,
        source_start_s=source_in,
        source_end_s=source_out,
        speed_ramp=ramp,
    )
    song = tmp_path / "music.wav"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            str(song),
        ],
        check=True,
        timeout=30,
        **subprocess_no_window_kwargs(),
    )
    out = tmp_path / "target.mp4"
    FfmpegStudioEncoder().render(
        StudioExportConfig(
            out,
            320,
            180,
            clips=(clip,),
            music_tracks=(StudioExportMusic(song, duration_s=3.0),),
        )
    )
    assert _video_frame_count(ffmpeg, out, 320, 180) == draft.output_frames
    assert _audio_seconds(ffmpeg, out) == pytest.approx(draft.output_duration_s, abs=1 / 30)
    assert source.read_bytes() == original


def test_target_duration_exports_1080p(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    span, target = 2.0, 0.5
    draft = draft_from_target(span, target)
    source = _synthetic_source(tmp_path, ffmpeg, seconds=span, width=1920, height=1080)
    original = source.read_bytes()
    ramp = parse_ramp(
        flat_timelapse_payload(0.0, span, draft.speed),
        media_duration_s=span,
    )
    clip = StudioExportClip(
        source,
        "video",
        ramp.duration(0.0, span),
        source_end_s=span,
        speed_ramp=ramp,
    )
    out = tmp_path / "hd.mp4"
    FfmpegStudioEncoder().render(StudioExportConfig(out, 1920, 1080, clips=(clip,)))
    assert _video_frame_count(ffmpeg, out, 1920, 1080) == draft.output_frames
    assert source.read_bytes() == original
