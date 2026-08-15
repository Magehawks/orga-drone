"""Encoder regression: chained Crossfade stitch + music (Issue #27 human test)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from orga_drone.config import Settings
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig, StudioExportMusic
from orga_drone.export.studio_encoder import FfmpegStudioEncoder
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_transition import AppliedTransition, story_length_s


def _ffmpeg() -> str:
    binary = find_ffmpeg()
    if binary is None:
        pytest.skip("ffmpeg not available")
    return binary


def _write_av_clip(
    ffmpeg: str, dest: Path, *, color: str, duration_s: float = 1.0
) -> Path:
    made = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=64x48:r=30:d={duration_s}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration_s}",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(dest),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert made.returncode == 0, made.stderr
    return dest


def _write_music(ffmpeg: str, dest: Path, *, duration_s: float = 2.0) -> Path:
    made = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=880:duration={duration_s}",
            str(dest),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert made.returncode == 0, made.stderr
    return dest


def _probe(ffmpeg: str, path: Path) -> tuple[float, bool]:
    probed = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    has_aac = "Audio: aac" in probed.stderr
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", probed.stderr)
    assert match is not None, probed.stderr
    hours, minutes, seconds = match.groups()
    duration_s = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return duration_s, has_aac


def _video_clip(
    source: Path,
    duration_s: float,
    *,
    transition_type: str = "cut",
    transition_s: float = 0.0,
    fade_in_s: float = 0.0,
    fade_out_s: float = 0.0,
) -> StudioExportClip:
    return StudioExportClip(
        source_path=source,
        kind="video",
        duration_s=duration_s,
        source_start_s=0.0,
        source_end_s=duration_s,
        transition_type=transition_type,
        transition_s=transition_s,
        fade_in_s=fade_in_s,
        fade_out_s=fade_out_s,
    )


def _music(path: Path, *, duration_s: float) -> StudioExportMusic:
    return StudioExportMusic(
        source_path=path,
        volume=0.5,
        fade_in_s=0.1,
        fade_out_s=0.1,
        loop=False,
        duration_s=duration_s,
    )


def _render(
    tmp_path: Path,
    clips: tuple[StudioExportClip, ...],
    *,
    music: StudioExportMusic | None = None,
    name: str = "out.mp4",
) -> Path:
    output = tmp_path / name
    config = StudioExportConfig(
        output_path=output,
        width=64,
        height=48,
        clips=clips,
        music=music,
    )
    assert FfmpegStudioEncoder().render(config) == output
    assert output.is_file()
    return output


def test_captured_failing_ffmpeg_command_is_archived() -> None:
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "studio-export-chained-xfade-timebase-fail.ffmpeg.txt"
    )
    text = fixture.read_text(encoding="utf-8")
    assert "[xv1][3:v]xfade=transition=fade:duration=0.5000:offset=7.3000[xv2]" in text
    assert "timebase (1/1000000)" in text
    assert "aost#0:1" in text
    assert "-map [xa2]" in text


def test_encoder_video_music_cut_exports(tmp_path: Path) -> None:
    ffmpeg = _ffmpeg()
    a = _write_av_clip(ffmpeg, tmp_path / "a.mp4", color="red")
    b = _write_av_clip(ffmpeg, tmp_path / "b.mp4", color="blue")
    music = _write_music(ffmpeg, tmp_path / "bed.wav")
    a_bytes, b_bytes, m_bytes = a.read_bytes(), b.read_bytes(), music.read_bytes()
    out = _render(
        tmp_path,
        (_video_clip(a, 1.0), _video_clip(b, 1.0)),
        music=_music(music, duration_s=2.0),
        name="cut.mp4",
    )
    duration_s, has_aac = _probe(ffmpeg, out)
    assert has_aac
    assert duration_s == pytest.approx(2.0, abs=0.25)
    assert a.read_bytes() == a_bytes
    assert b.read_bytes() == b_bytes
    assert music.read_bytes() == m_bytes


def test_encoder_video_music_one_crossfade_exports(tmp_path: Path) -> None:
    ffmpeg = _ffmpeg()
    a = _write_av_clip(ffmpeg, tmp_path / "a.mp4", color="red")
    b = _write_av_clip(ffmpeg, tmp_path / "b.mp4", color="blue")
    music = _write_music(ffmpeg, tmp_path / "bed.wav")
    out = _render(
        tmp_path,
        (
            _video_clip(a, 1.0, transition_type="crossfade", transition_s=0.4),
            _video_clip(b, 1.0),
        ),
        music=_music(music, duration_s=2.0),
        name="xfade.mp4",
    )
    duration_s, has_aac = _probe(ffmpeg, out)
    assert has_aac
    assert duration_s == pytest.approx(1.6, abs=0.25)


def test_encoder_video_music_fade_black_exports(tmp_path: Path) -> None:
    ffmpeg = _ffmpeg()
    a = _write_av_clip(ffmpeg, tmp_path / "a.mp4", color="red")
    b = _write_av_clip(ffmpeg, tmp_path / "b.mp4", color="blue")
    music = _write_music(ffmpeg, tmp_path / "bed.wav")
    out = _render(
        tmp_path,
        (
            _video_clip(
                a,
                1.0,
                transition_type="fade_black",
                transition_s=0.5,
                fade_out_s=0.25,
            ),
            _video_clip(b, 1.0, fade_in_s=0.25),
        ),
        music=_music(music, duration_s=2.0),
        name="fadeblack.mp4",
    )
    duration_s, has_aac = _probe(ffmpeg, out)
    assert has_aac
    assert duration_s == pytest.approx(2.0, abs=0.25)


def test_encoder_chained_crossfade_with_music_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Human-test topology: Crossfade → Cut → Crossfade + music (FFmpeg 7 timebase)."""
    ffmpeg = _ffmpeg()
    clips_src = [
        _write_av_clip(ffmpeg, tmp_path / f"c{i}.mp4", color=color)
        for i, color in enumerate(("red", "green", "blue", "yellow"))
    ]
    music = _write_music(ffmpeg, tmp_path / "bed.wav", duration_s=4.0)
    source_bytes = [path.read_bytes() for path in clips_src]
    music_bytes = music.read_bytes()

    from orga_drone.export import studio_encoder as encoder_module

    commands: list[list[str]] = []
    real_run = encoder_module._run_ffmpeg

    def recording_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        commands.append(cmd.copy())
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(encoder_module, "_run_ffmpeg", recording_run)

    clips = (
        _video_clip(clips_src[0], 1.0, transition_type="crossfade", transition_s=0.4),
        _video_clip(clips_src[1], 1.0),
        _video_clip(clips_src[2], 1.0, transition_type="crossfade", transition_s=0.2),
        _video_clip(clips_src[3], 1.0),
    )
    expected = story_length_s(
        [1.0, 1.0, 1.0, 1.0],
        (
            AppliedTransition(
                type="crossfade",
                duration_s=0.4,
                stored_type="crossfade",
                stored_duration_s=0.4,
                fallback_cut=False,
                clamped=False,
            ),
            AppliedTransition(
                type="cut",
                duration_s=0.0,
                stored_type="cut",
                stored_duration_s=0.0,
                fallback_cut=False,
                clamped=False,
            ),
            AppliedTransition(
                type="crossfade",
                duration_s=0.2,
                stored_type="crossfade",
                stored_duration_s=0.2,
                fallback_cut=False,
                clamped=False,
            ),
        ),
    )
    assert expected == pytest.approx(3.4)

    out = _render(
        tmp_path,
        clips,
        music=_music(music, duration_s=4.0),
        name="chained.mp4",
    )
    duration_s, has_aac = _probe(ffmpeg, out)
    assert has_aac
    assert duration_s == pytest.approx(expected, abs=0.3)
    for path, original in zip(clips_src, source_bytes, strict=True):
        assert path.read_bytes() == original
    assert music.read_bytes() == music_bytes

    stitch_graphs = [
        cmd[cmd.index("-filter_complex") + 1]
        for cmd in commands
        if "-filter_complex" in cmd and "xfade=" in cmd[cmd.index("-filter_complex") + 1]
    ]
    assert stitch_graphs
    assert "settb=1/30" in stitch_graphs[0]
    assert "[xv1][3:v]xfade" not in stitch_graphs[0]

    mix_graphs = [
        cmd[cmd.index("-filter_complex") + 1]
        for cmd in commands
        if "-filter_complex" in cmd and "amix=" in cmd[cmd.index("-filter_complex") + 1]
    ]
    assert mix_graphs
    graph = mix_graphs[-1]
    assert "volume=0.5" in graph
    assert "afade=" in graph
    assert "amix=inputs=2:duration=first" in graph
    mix_cmd = next(
        cmd
        for cmd in commands
        if "-filter_complex" in cmd
        and "amix=" in cmd[cmd.index("-filter_complex") + 1]
    )
    assert mix_cmd[mix_cmd.index("-c:v") + 1] == "copy"


def test_encoder_chained_crossfade_without_music_exports(tmp_path: Path) -> None:
    ffmpeg = _ffmpeg()
    clips_src = [
        _write_av_clip(ffmpeg, tmp_path / f"c{i}.mp4", color=color)
        for i, color in enumerate(("red", "green", "blue", "yellow"))
    ]
    out = _render(
        tmp_path,
        (
            _video_clip(clips_src[0], 1.0, transition_type="crossfade", transition_s=0.4),
            _video_clip(clips_src[1], 1.0),
            _video_clip(clips_src[2], 1.0, transition_type="crossfade", transition_s=0.2),
            _video_clip(clips_src[3], 1.0),
        ),
        name="nomusic.mp4",
    )
    duration_s, has_aac = _probe(ffmpeg, out)
    assert has_aac
    assert duration_s == pytest.approx(3.4, abs=0.3)


def test_encoder_title_card_music_crossfade_exports(tmp_path: Path) -> None:
    ffmpeg = _ffmpeg()
    video = _write_av_clip(ffmpeg, tmp_path / "v.mp4", color="blue")
    music = _write_music(ffmpeg, tmp_path / "bed.wav")
    video_bytes = video.read_bytes()
    out = _render(
        tmp_path,
        (
            StudioExportClip(
                source_path=None,
                kind="title_card",
                duration_s=1.0,
                title_text="Intro",
                transition_type="crossfade",
                transition_s=0.3,
            ),
            _video_clip(video, 1.0),
        ),
        music=_music(music, duration_s=2.0),
        name="title.mp4",
    )
    duration_s, has_aac = _probe(ffmpeg, out)
    assert has_aac
    assert duration_s == pytest.approx(1.7, abs=0.3)
    assert video.read_bytes() == video_bytes


def test_persist_ffmpeg_failure_writes_full_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.export.studio_encoder import _persist_ffmpeg_failure

    monkeypatch.setattr(
        "orga_drone.config.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    cmd = ["ffmpeg", "-y", "-filter_complex", "[xv1][3:v]xfade=transition=fade", "out.mp4"]
    _persist_ffmpeg_failure(cmd, "timebase (1/1000000) do not match\nConversion failed!\n")
    log = (tmp_path / "data" / "logs" / "studio-export-ffmpeg.log").read_text(encoding="utf-8")
    assert "CMD " in log
    assert "[xv1][3:v]xfade=transition=fade" in log
    assert "timebase (1/1000000)" in log
    assert "Conversion failed!" in log
