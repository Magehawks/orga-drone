"""Canonical timing, persistence and decoded source-frame regression coverage."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import FfmpegStudioEncoder
from orga_drone.export.studio_ramp_encoder import ramp_passes
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_color_animation import ColorAnimation, ColorKey
from orga_drone.studio_estimate import effective_seconds
from orga_drone.studio_speed_ramp import (
    Point,
    Region,
    SpeedRamp,
    edge_source_after_ramp_drag,
    parse_ramp,
    place_ramp_region,
    ramp_after_region_drag,
    ramp_from_settings,
)
from orga_drone.studio_frame import FrameTransform
from orga_drone.studio_map import MapPlacement
from orga_drone.studio_mask import Mask
from orga_drone.studio_overlay import Overlay
from orga_drone.studio_image import SaturationRamp
from tests.test_studio_speed import _add_item, _seed_media

FIXTURE = json.loads((Path(__file__).parent / "fixtures/speed_ramp.json").read_text())


def test_constant_speed_stories_keep_legacy_timing() -> None:
    from orga_drone.export.studio_frame_plan import plan_story_frames
    from orga_drone.studio_speed import output_duration_s

    clip = StudioExportClip(
        None,
        "video",
        4,
        source_end_s=2,
        playback_speed=0.5,
        transition_type="crossfade",
        transition_s=0.4,
    )
    plain = replace(clip, transition_type="cut", transition_s=0)
    assert plan_story_frames((clip, plain)) == ((clip, plain), (clip, plain))
    legacy = effective_seconds(
        kind="video",
        available=True,
        photo_duration_s=None,
        duration_s=4,
        source_in_s=0,
        source_out_s=2,
        playback_speed=0.5,
        effect_settings="{}",
    )
    assert legacy == pytest.approx(output_duration_s(2, 0.5))
    slow = {"slow_bar": {"start_s": 0, "end_s": 2, "speed": 0.5}}
    broken = {**slow, "speed_ramp": {"v": 1, "points": []}}
    kwargs = dict(
        kind="video",
        available=True,
        photo_duration_s=None,
        duration_s=4,
        source_in_s=0,
        source_out_s=2,
        playback_speed=0.5,
    )
    assert effective_seconds(
        **kwargs, effect_settings=json.dumps(slow)
    ) == effective_seconds(**kwargs, effect_settings=json.dumps(broken))


def test_shared_mapping_fixture_and_trim() -> None:
    ramp = parse_ramp(FIXTURE["curve"])
    for sample in FIXTURE["samples"]:
        assert ramp.time_at(sample["source"]) == pytest.approx(sample["story"])
        assert ramp.speed_at(sample["source"]) == pytest.approx(sample["speed"])
        assert ramp.source_at(sample["story"], 0, 5) == pytest.approx(
            sample["source"], abs=1e-9
        )
    raw = json.dumps({"speed_ramp": ramp.as_dict()})
    duration = effective_seconds(
        kind="video",
        available=True,
        photo_duration_s=None,
        duration_s=5,
        source_in_s=1,
        source_out_s=3,
        effect_settings=raw,
    )
    assert duration == pytest.approx(ramp.duration(1, 3))
    assert ramp.duration(1, 2) + ramp.duration(2, 3) == pytest.approx(duration)


@pytest.mark.parametrize(
    "speed", [0, -1, 0.249, 20.001, float("nan"), float("inf"), True, "1"]
)
def test_invalid_speeds(speed: object) -> None:
    value = json.loads(json.dumps(FIXTURE["curve"]))
    value["points"][0]["speed"] = speed
    with pytest.raises(ValueError):
        parse_ramp(value)


def test_roundtrip_history_cut_and_legacy_speed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    cid = _add_item(
        db,
        _seed_media(
            db,
            tmp_path / "lib",
            filename="ramp.mp4",
            content=b"synthetic",
            duration_s=5,
        ),
    )
    client = TestClient(app)
    route = f"/api/studio/{cid}/speed-ramp"
    assert client.patch(route, json={"speed_ramp": FIXTURE["curve"]}).status_code == 200
    extreme = json.loads(json.dumps(FIXTURE["curve"]))
    extreme["points"][0]["source_s"] = 10**1000
    assert client.patch(route, json={"speed_ramp": extreme}).status_code == 400
    assert ramp_from_settings(json.dumps({"speed_ramp": extreme})) is None
    saved = next(i for i in db.list_studio_items() if i.id == cid)
    assert ramp_from_settings(saved.effect_settings) == parse_ramp(FIXTURE["curve"])
    assert client.get("/studio").status_code == 200
    assert client.post("/api/studio/history/undo").status_code == 200
    assert ramp_from_settings(db.list_studio_items()[0].effect_settings) is None
    assert client.post("/api/studio/history/redo").status_code == 200
    reopened = Database(db.path)
    assert (
        ramp_from_settings(reopened.list_studio_items()[0].effect_settings) is not None
    )
    cut = client.post(f"/api/studio/{cid}/cut", json={"local_s": 2})
    assert cut.status_code == 200
    assert cut.json()["left"]["effective_duration_s"] == pytest.approx(6.59375)
    left, right = db.list_studio_items()
    assert ramp_from_settings(left.effect_settings) == ramp_from_settings(
        right.effect_settings
    )
    db.set_studio_playback_speed(left.id, 0.5)
    assert ramp_from_settings(db.list_studio_items()[0].effect_settings) is None
    photo = _add_item(
        db,
        _seed_media(
            db,
            tmp_path / "photos",
            filename="still.jpg",
            content=b"jpeg",
            kind="photo",
            duration_s=None,
        ),
    )
    refused = client.patch(
        f"/api/studio/{photo}/speed-ramp", json={"speed_ramp": FIXTURE["curve"]}
    )
    assert refused.status_code == 400
    assert "video" in refused.json()["detail"]


def test_remove_ramp_null_undo_redo_and_legacy_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    cid = _add_item(
        db,
        _seed_media(
            db,
            tmp_path / "lib",
            filename="remove-ramp.mp4",
            content=b"synthetic",
            duration_s=5,
        ),
    )
    client = TestClient(app)
    route = f"/api/studio/{cid}/speed-ramp"
    applied = client.patch(route, json={"speed_ramp": FIXTURE["curve"]})
    assert applied.status_code == 200
    assert applied.json()["speed_ramp"] is not None
    ramped = next(i for i in db.list_studio_items() if i.id == cid)
    assert ramp_from_settings(ramped.effect_settings) is not None
    ramped_seconds = effective_seconds(
        kind="video",
        available=True,
        photo_duration_s=None,
        duration_s=5,
        source_in_s=0,
        source_out_s=5,
        effect_settings=ramped.effect_settings,
    )
    removed = client.patch(route, json={"speed_ramp": None})
    assert removed.status_code == 200
    assert removed.json()["speed_ramp"] is None
    assert removed.json()["effective_duration_s"] == pytest.approx(5.0)
    cleared = next(i for i in db.list_studio_items() if i.id == cid)
    assert ramp_from_settings(cleared.effect_settings) is None
    assert cleared.playback_speed == pytest.approx(1.0)
    assert "speed_ramp" not in json.loads(cleared.effect_settings or "{}")
    legacy_seconds = effective_seconds(
        kind="video",
        available=True,
        photo_duration_s=None,
        duration_s=5,
        source_in_s=0,
        source_out_s=5,
        effect_settings=cleared.effect_settings,
    )
    assert legacy_seconds == pytest.approx(5.0)
    assert ramped_seconds != pytest.approx(legacy_seconds)
    assert client.post("/api/studio/history/undo").status_code == 200
    restored = next(i for i in db.list_studio_items() if i.id == cid)
    assert ramp_from_settings(restored.effect_settings) == parse_ramp(FIXTURE["curve"])
    assert client.post("/api/studio/history/redo").status_code == 200
    reopened = Database(db.path)
    gone = next(i for i in reopened.list_studio_items() if i.id == cid)
    assert ramp_from_settings(gone.effect_settings) is None


def test_edge_drag_absolute_inverse_on_trimmed_asymmetric_ramp() -> None:
    ramp = SpeedRamp((Point(0.0, 0.5), Point(4.0, 4.0), Point(8.0, 0.5)))
    start_in, start_out = 5.0, 8.0
    delta = 1.25
    new_in, new_out = edge_source_after_ramp_drag(
        ramp,
        edge="out",
        source_in_s=start_in,
        source_out_s=start_out,
        delta_story_s=delta,
        repeats=1,
        media_duration_s=10.0,
    )
    assert new_in == pytest.approx(start_in)
    assert ramp.time_at(new_out) - ramp.time_at(start_out) == pytest.approx(
        delta, abs=0.02
    )
    left_in, left_out = edge_source_after_ramp_drag(
        ramp,
        edge="in",
        source_in_s=start_in,
        source_out_s=start_out,
        delta_story_s=-0.8,
        repeats=2,
        media_duration_s=10.0,
    )
    assert left_out == pytest.approx(start_out)
    assert left_in == pytest.approx(
        round(ramp.source_at_time(ramp.time_at(start_in) - 0.4, 0.0, 10.0), 2)
    )


def test_cut_on_trimmed_ramp_uses_relative_local_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UI storyToSource is relative; cut expects that same relative local_s."""
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    cid = _add_item(
        db,
        _seed_media(
            db,
            tmp_path / "lib",
            filename="trim-cut.mp4",
            content=b"synthetic",
            duration_s=12,
        ),
    )
    client = TestClient(app)
    assert (
        client.patch(
            f"/api/studio/{cid}/section",
            json={"source_in_s": 5, "source_out_s": 9, "repeats": 1},
        ).status_code
        == 200
    )
    curve = {
        "v": 1,
        "interp": "reciprocal_smoothstep",
        "points": [
            {"source_s": 5.0, "speed": 0.5},
            {"source_s": 7.0, "speed": 4.0},
            {"source_s": 9.0, "speed": 0.5},
        ],
    }
    assert (
        client.patch(
            f"/api/studio/{cid}/speed-ramp", json={"speed_ramp": curve}
        ).status_code
        == 200
    )
    # Relative offset 2 from source_in 5 → absolute source 7.
    cut = client.post(f"/api/studio/{cid}/cut", json={"local_s": 2})
    assert cut.status_code == 200
    left, right = db.list_studio_items()
    assert left.source_start == pytest.approx(5.0)
    assert left.source_end == pytest.approx(7.0)
    assert right.source_start == pytest.approx(7.0)
    assert right.source_end == pytest.approx(9.0)
    assert ramp_from_settings(left.effect_settings) == parse_ramp(curve)
    assert ramp_from_settings(right.effect_settings) == parse_ramp(curve)


def test_partial_loop_uses_inverse_mapping() -> None:
    ramp = parse_ramp(FIXTURE["curve"])
    clip = StudioExportClip(
        None,
        "video",
        duration_s=10,
        source_end_s=4,
        speed_ramp=ramp,
        forward_loop=True,
        forward_cycle_s=8.5,
    )
    passes = ramp_passes(clip)
    assert len(passes) == 2
    tail, start = passes[-1]
    assert start == pytest.approx(8.5)
    assert ramp.duration(0, tail.source_end_s) == pytest.approx(1.5)


@pytest.mark.parametrize("animated", [False, True])
@pytest.mark.parametrize(
    "mode", ["single", "trim", "repeat", "loop", "crossfade", "effects", "seam"]
)
def test_decoded_ramp_frames_have_no_accumulated_piece_drift(
    tmp_path: Path, animated: bool, mode: str
) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    frames = tmp_path / "frames"
    frames.mkdir()
    for n in range(120):
        image = Image.new("RGB", (64, 48))
        draw = ImageDraw.Draw(image)
        for bit in range(8):
            draw.rectangle(
                (bit * 8, 0, bit * 8 + 7, 47),
                fill="white" if n & (1 << bit) else "black",
            )
        image.save(frames / f"{n:03}.png")
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-framerate",
            "60",
            "-i",
            str(frames / "%03d.png"),
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=2",
            "-c:v",
            "libx264",
            "-crf",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        timeout=30,
        **subprocess_no_window_kwargs(),
    )
    original = source.read_bytes()
    ramp = SpeedRamp((Point(0, 0.5), Point(1, 4), Point(2, 0.5)))
    animation = (
        ColorAnimation(bar_end_s=2, keys=(ColorKey(0), ColorKey(2, warmth=10)))
        if animated
        else None
    )
    clip = StudioExportClip(
        source,
        "video",
        ramp.duration(0, 2),
        source_end_s=2,
        speed_ramp=ramp,
        color_animation=animation,
    )
    if mode == "trim":
        clip = replace(
            clip,
            source_start_s=0.25,
            source_end_s=1.75,
            duration_s=ramp.duration(0.25, 1.75),
        )
    elif mode == "repeat":
        clip = replace(clip, section_repeats=2, duration_s=4.5)
    elif mode == "loop":
        clip = replace(clip, forward_loop=True, forward_cycle_s=2.25, duration_s=3)
    elif mode == "crossfade":
        clip = replace(
            clip, section_repeats=2, duration_s=4.3, forward_transition_s=0.2
        )
    elif mode == "seam":
        clip = replace(
            clip,
            source_start_s=0.25,
            source_end_s=1.75,
            duration_s=ramp.duration(0.25, 1.75),
            speed_ramp_source_in_s=0,
            speed_ramp_source_out_s=2,
        )
    elif mode == "effects":
        clip = replace(
            clip,
            frame=FrameTransform(zoom_start=1.1, zoom_end=1.5),
            masks=(Mask("test", "blur", 50, 0.2, 0.2, 0.3, 0.3, 0.25, 1.25),),
            overlays=(
                Overlay(
                    "label",
                    "text",
                    0.2,
                    1.5,
                    0.1,
                    0.1,
                    0.5,
                    0.2,
                    text="Synthetic",
                    animation="fade_in",
                ),
            ),
            saturation_ramp=SaturationRamp(True, 0, 2),
            map_placement=MapPlacement(enabled=True),
            fade_in_s=0.2,
            fade_out_s=0.2,
        )
    output = tmp_path / "ramp.mp4"
    FfmpegStudioEncoder().render(StudioExportConfig(output, 64, 48, clips=(clip,)))
    decoded = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(output),
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
        timeout=30,
        **subprocess_no_window_kwargs(),
    ).stdout
    size = 64 * 48 * 3
    assert len(decoded) // size == int(clip.duration_s * 30 + 0.5)
    passes = ramp_passes(clip)
    for frame in range(len(decoded) // size):
        if mode == "effects":
            continue
        story = frame / 30
        if (
            any(start <= story <= start + 0.2 for _, start in passes[1:])
            and mode == "crossfade"
        ):
            continue  # Blended frames intentionally contain two source identities.
        current, pass_start = next(
            (p, start) for p, start in reversed(passes) if story >= start
        )
        pixels = decoded[frame * size : (frame + 1) * size]
        source_frame = sum(
            (1 << bit) for bit in range(8) if pixels[(24 * 64 + bit * 8 + 4) * 3] > 128
        )
        assert (
            abs(
                ramp.time_at(source_frame / 60)
                - ramp.time_at(clip.source_start_s)
                - (story - pass_start)
            )
            <= 1 / 30 + 0.001
        )
    assert source.read_bytes() == original
    audio = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(output),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-f",
            "s16le",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=30,
        **subprocess_no_window_kwargs(),
    ).stdout
    import array

    samples = array.array("h", audio)
    assert samples and max(abs(value) for value in samples) <= 1


@pytest.mark.parametrize("mode", ["ramps", "mixed", "transitions", "overlays"])
def test_project_frame_grid_does_not_accumulate_clip_rounding(
    tmp_path: Path, mode: str
) -> None:
    from orga_drone.export.studio_config import StudioExportMusic
    from orga_drone.export.studio_frame_plan import frame_index, plan_story_frames

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=64x48:r=60:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=30,
        **subprocess_no_window_kwargs(),
    )
    ramp = SpeedRamp((Point(0, 3.7), Point(1, 3.7)))
    base = StudioExportClip(source, "video", 1 / 3.7, source_end_s=1, speed_ramp=ramp)
    clips = []
    for index in range(20):
        if mode == "mixed" and index % 2:
            animation = ColorAnimation(
                bar_end_s=1.05, keys=(ColorKey(0), ColorKey(1.05, warmth=10))
            )
            clips.append(
                replace(
                    base,
                    speed_ramp=None,
                    duration_s=1.05,
                    source_end_s=1.05,
                    color_animation=animation,
                )
            )
        else:
            clips.append(
                replace(
                    base,
                    transition_type="crossfade"
                    if mode == "transitions" and index < 19
                    else "cut",
                    transition_s=0.1 if mode == "transitions" and index < 19 else 0,
                )
            )
            if mode == "overlays":
                clips[-1] = replace(clips[-1], overlays=(Overlay("counter", "text", .01, .25, .1, .1, .5, .2, text="Synthetic", animation="fade_in", animation_s=.1),),
                                    map_placement=MapPlacement(enabled=True), fade_in_s=.05, fade_out_s=.05)
    total = sum(c.duration_s for c in clips) - sum(c.transition_s for c in clips[:-1])
    render, stitch = plan_story_frames(tuple(clips))
    assert frame_index(
        sum(c.duration_s for c in stitch) - sum(c.transition_s for c in stitch[:-1])
    ) == frame_index(total)
    if mode == "ramps":
        assert sum(c.export_frame_count for c in render) == 162
    song = tmp_path / "music.wav"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=20",
            str(song),
        ],
        check=True,
        timeout=30,
        **subprocess_no_window_kwargs(),
    )
    output = tmp_path / "project.mp4"
    FfmpegStudioEncoder().render(
        StudioExportConfig(
            output,
            64,
            48,
            clips=tuple(clips),
            music_tracks=(StudioExportMusic(song, duration_s=20),),
        )
    )
    decoded = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(output),
            "-map",
            "0:v:0",
            "-fps_mode",
            "passthrough",
            "-f",
            "framemd5",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=30,
        text=True,
        **subprocess_no_window_kwargs(),
    ).stdout
    assert len(
        [line for line in decoded.splitlines() if line and not line.startswith("#")]
    ) == frame_index(total)
    audio = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(output),
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
        capture_output=True,
        check=True,
        timeout=30,
        **subprocess_no_window_kwargs(),
    ).stdout
    assert abs(len(audio) / 2 / 48000 - frame_index(total) / 30) < 0.05


def test_late_nonkeyframe_seek_matches_full_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.export import studio_encoder as enc

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    source = tmp_path / "long-source.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=64x48:r=60:d=20",
            "-c:v",
            "libx264",
            "-g",
            "250",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=30,
        **subprocess_no_window_kwargs(),
    )
    ramp = SpeedRamp((Point(18.15, 0.5), Point(19.75, 4)))
    clip = StudioExportClip(
        source,
        "video",
        ramp.duration(18.15, 19.75),
        source_start_s=18.15,
        source_end_s=19.75,
        speed_ramp=ramp,
        color_animation=ColorAnimation(
            bar_end_s=1.6, keys=(ColorKey(0), ColorKey(1.6, warmth=10))
        ),
    )
    real = enc._run_ffmpeg
    commands = []
    reference = False

    def run(cmd, **kwargs):
        if "-copyts" in cmd:
            commands.append(cmd.copy())
            if reference:
                first_input = cmd.index("-i")
                head = cmd[:first_input]
                for option in ("-ss", "-t"):
                    at = head.index(option)
                    del head[at : at + 2]
                cmd = head + cmd[first_input:]
        return real(cmd, **kwargs)

    monkeypatch.setattr(enc, "_run_ffmpeg", run)
    bounded = tmp_path / "bounded.mp4"
    full = tmp_path / "reference.mp4"
    FfmpegStudioEncoder().render(StudioExportConfig(bounded, 64, 48, clips=(clip,)))
    reference = True
    FfmpegStudioEncoder().render(StudioExportConfig(full, 64, 48, clips=(clip,)))
    for cmd in commands:
        assert float(cmd[cmd.index("-ss") + 1]) >= 18
        assert float(cmd[cmd.index("-t") + 1]) <= 2

    def pixels(path):
        return subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "-",
            ],
            capture_output=True,
            check=True,
            timeout=30,
            **subprocess_no_window_kwargs(),
        ).stdout

    assert pixels(bounded) == pixels(full)


def _eval_ffmpeg_time(expression: str, source: float) -> float:
    """Evaluate the ramp's FFmpeg primitive at one source time."""
    text = expression.replace("T", f"({source:.12g})")
    index = 0

    def peek() -> str:
        return text[index:]

    def expr() -> float:
        value = term()
        while index < len(text) and text[index] in "+-":
            op = text[index]
            advance(1)
            right = term()
            value = value + right if op == "+" else value - right
        return value

    def term() -> float:
        value = power()
        while index < len(text) and text[index] in "*/":
            op = text[index]
            advance(1)
            right = power()
            value = value * right if op == "*" else value / right
        return value

    def power() -> float:
        value = unary()
        if index < len(text) and text[index] == "^":
            advance(1)
            return value ** power()
        return value

    def unary() -> float:
        nonlocal index
        if text[index] == "+":
            advance(1)
            return unary()
        if text[index] == "-":
            advance(1)
            return -unary()
        return primary()

    def primary() -> float:
        nonlocal index
        if text.startswith("if", index) and not text[index + 2 : index + 3].isalnum():
            advance(2)
            expect("(")
            cond = expr()
            expect(",")
            yes = expr()
            expect(",")
            no = expr()
            expect(")")
            return yes if cond else no
        if text.startswith("lte", index):
            advance(3)
            expect("(")
            left = expr()
            expect(",")
            right = expr()
            expect(")")
            return 1.0 if left <= right else 0.0
        if text[index] == "(":
            advance(1)
            value = expr()
            expect(")")
            return value
        token = ""
        while index < len(text) and (text[index].isdigit() or text[index] == "."):
            token += text[index]
            index += 1
        if index < len(text) and text[index] in "eE":
            token += text[index]
            index += 1
            if index < len(text) and text[index] in "+-":
                token += text[index]
                index += 1
            while index < len(text) and text[index].isdigit():
                token += text[index]
                index += 1
        if not token:
            raise ValueError(text[index : index + 24])
        return float(token)

    def advance(count: int) -> None:
        nonlocal index
        index += count

    def expect(char: str) -> None:
        nonlocal index
        if text[index] != char:
            raise ValueError(text[index : index + 24])
        index += 1

    value = expr()
    if index != len(text):
        raise ValueError(text[index : index + 24])
    return value


def test_bounded_region_is_one_outside_and_matches_export_primitive() -> None:
    ramp = parse_ramp(
        {
            "v": 1,
            "interp": "reciprocal_smoothstep",
            "region": {"start_s": 2, "end_s": 4},
            "points": [
                {"source_s": 2, "speed": 0.5},
                {"source_s": 4, "speed": 0.5},
            ],
        }
    )
    assert ramp.speed_at(1) == 1
    assert ramp.speed_at(2) == pytest.approx(0.5)
    assert ramp.speed_at(4.2) == 1
    assert ramp.duration(0, 6) == pytest.approx(8)
    legacy = SpeedRamp(ramp.points)
    assert ramp.duration(2, 4) == pytest.approx(legacy.duration(2, 4))
    legacy_expr = parse_ramp(FIXTURE["curve"]).ffmpeg_time()
    for sample in FIXTURE["samples"]:
        assert _eval_ffmpeg_time(legacy_expr, sample["source"]) == pytest.approx(sample["story"])
    for source in (0, 1, 2, 3, 4, 5, 6):
        assert _eval_ffmpeg_time(ramp.ffmpeg_time(), source) == pytest.approx(ramp.time_at(source))
    with pytest.raises(ValueError):
        parse_ramp({**ramp.as_dict(), "region": {"start_s": 3, "end_s": 3.5}})


def test_place_and_drag_keep_curve_speeds() -> None:
    base = SpeedRamp((Point(0, 0.5), Point(30, 4), Point(60, 0.5)))
    placed = place_ramp_region(base, 10, 40, play_start=0, play_end=60)
    assert placed.region == Region(10, 40)
    assert [point.speed for point in placed.points] == [0.5, 4, 0.5]
    assert placed.speed_at(9) == 1
    assert placed.speed_at(25) == pytest.approx(4)
    assert placed.speed_at(41) == 1
    moved = ramp_after_region_drag(
        placed, mode="move", delta_story_s=100, play_start=0, play_end=60
    )
    assert moved.region == Region(30, 60)
    assert [point.speed for point in moved.points] == [0.5, 4, 0.5]
    before = placed.duration(10, 40)
    resized = ramp_after_region_drag(
        placed, mode="end", delta_story_s=3, play_start=0, play_end=60
    )
    assert resized.region is not None and resized.region.start_s == 10
    assert resized.points[1].speed == 4
    assert resized.duration(resized.region.start_s, resized.region.end_s) == pytest.approx(
        before + 3, abs=0.02
    )
    started = ramp_after_region_drag(
        placed, mode="start", delta_story_s=-2, play_start=0, play_end=60
    )
    assert started.region == Region(8, 40)
    assert started.points[0].speed == 0.5


def test_bounded_region_reopens_and_shares_preview_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    from orga_drone.app import create_app
    from orga_drone.studio_cut import resolve_source_range

    app = create_app()
    db: Database = app.state.db
    cid = _add_item(
        db,
        _seed_media(
            db,
            tmp_path / "lib",
            filename="bounded.mp4",
            content=b"synthetic",
            duration_s=6,
        ),
    )
    payload = {
        "v": 1,
        "interp": "reciprocal_smoothstep",
        "region": {"start_s": 2, "end_s": 4},
        "points": [
            {"source_s": 2, "speed": 0.5},
            {"source_s": 3, "speed": 4},
            {"source_s": 4, "speed": 0.5},
        ],
    }
    client = TestClient(app)
    route = f"/api/studio/{cid}/speed-ramp"
    applied = client.patch(route, json={"speed_ramp": payload})
    assert applied.status_code == 200
    saved = next(item for item in db.list_studio_items() if item.id == cid)
    ramp = ramp_from_settings(saved.effect_settings)
    assert ramp is not None and ramp.region == Region(2, 4)
    assert [point.speed for point in ramp.points] == [0.5, 4, 0.5]
    seconds = effective_seconds(
        kind="video",
        available=True,
        photo_duration_s=None,
        duration_s=6,
        source_in_s=0,
        source_out_s=6,
        effect_settings=saved.effect_settings,
    )
    assert seconds == pytest.approx(ramp.duration(0, 6))
    assert applied.json()["effective_duration_s"] == pytest.approx(seconds)
    assert client.post("/api/studio/history/undo").status_code == 200
    assert ramp_from_settings(db.list_studio_items()[0].effect_settings) is None
    assert client.post("/api/studio/history/redo").status_code == 200
    reopened = Database(db.path)
    again = next(item for item in reopened.list_studio_items() if item.id == cid)
    assert ramp_from_settings(again.effect_settings) == ramp
    cut = client.post(f"/api/studio/{cid}/cut", json={"local_s": 2})
    assert cut.status_code == 200
    for clip in db.list_studio_items():
        kept = ramp_from_settings(clip.effect_settings)
        assert kept is not None and kept.region == Region(2, 4)
        rang = resolve_source_range(
            source_in_s=clip.source_start,
            source_out_s=clip.source_end,
            media_duration_s=clip.duration_s,
        )
        assert rang is not None
        assert effective_seconds(
            kind="video",
            available=True,
            photo_duration_s=None,
            duration_s=clip.duration_s,
            source_in_s=clip.source_start,
            source_out_s=clip.source_end,
            effect_settings=clip.effect_settings,
        ) == pytest.approx(kept.duration(rang.source_in_s, rang.source_out_s))
