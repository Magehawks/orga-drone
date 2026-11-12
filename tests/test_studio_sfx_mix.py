"""Measured music, source, and SFX mix from a real Studio MP4 (#184)."""

from __future__ import annotations

import array
import hashlib
import math
import subprocess
from pathlib import Path

import pytest

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.music_mix import fade_gain
from orga_drone.export.studio_encoder import FfmpegStudioEncoder
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_export import prepare_studio_export
from orga_drone.studio_history import (
    clear_studio_history,
    redo_story,
    story_edit,
    undo_story,
)


def test_preview_envelope_matches_export_fade_gain() -> None:
    assert fade_gain(0.2, bed_s=1, fade_in_s=0.4, fade_out_s=0) == pytest.approx(0.5)
    assert fade_gain(0.9, bed_s=1, fade_in_s=0, fade_out_s=0.4) == pytest.approx(0.25)
    assert fade_gain(0.25, bed_s=1, fade_in_s=0.8, fade_out_s=0.8) == pytest.approx(0.5)
    assert fade_gain(0.5, bed_s=1, fade_in_s=0, fade_out_s=0) == pytest.approx(1)


def test_exported_mp4_mixes_source_music_and_two_sfx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    clear_studio_history()

    video = tmp_path / "lib" / "CLIP.MP4"
    music = tmp_path / "audio" / "bed.wav"
    sfx_a = tmp_path / "audio" / "crack.wav"
    sfx_b = tmp_path / "audio" / "wind.wav"
    video.parent.mkdir()
    music.parent.mkdir()
    _ffmpeg(
        ffmpeg,
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1280x720:r=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=48000,volume=0.18",
            "-t",
            "4.5",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video),
        ],
    )
    _ffmpeg(
        ffmpeg,
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:sample_rate=48000:duration=5",
            str(music),
        ],
    )
    _ffmpeg(
        ffmpeg,
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1500:sample_rate=48000:duration=0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=2000:sample_rate=48000:duration=1.0",
            "-filter_complex",
            "[0:a][1:a]concat=n=2:v=0:a=1",
            str(sfx_a),
        ],
    )
    _ffmpeg(
        ffmpeg,
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1800:sample_rate=48000:duration=0.8",
            str(sfx_b),
        ],
    )
    originals = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (video, music, sfx_a, sfx_b)}

    db = Database(tmp_path / "mix.sqlite3")
    root_id = db.add_root(video.parent, label="lib")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": video.name,
            "path": str(video.resolve()),
            "size_bytes": video.stat().st_size,
            "duration_s": 4.0,
            "width": 1280,
            "height": 720,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": "Test",
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    project = db.ensure_default_studio_project(title="SFX mix")
    media = db.get_media(media_id)
    assert media is not None
    db.add_studio_item(
        media.path,
        identity_key=make_identity_key(media.filename, media.size_bytes, media.recorded_at),
        filename=media.filename,
        recorded_at=media.recorded_at,
        kind="video",
        project_id=project.id,
        source_media_id=media.id,
    )
    bed = db.append_studio_music(project.id, str(music.resolve()))
    db.patch_studio_music_clip(project.id, bed.id, volume=0.22, fade_in_s=0.5)
    first = db.append_studio_sfx(
        project.id,
        str(sfx_a.resolve()),
        start_s=1.0,
        source_in_s=0.5,
        source_out_s=1.5,
        volume=0.3,
        fade_in_s=0.4,
    )
    second = db.append_studio_sfx(
        project.id,
        str(sfx_b.resolve()),
        start_s=2.4,
        volume=0.22,
    )
    output = tmp_path / "story.mp4"
    config = prepare_studio_export(
        db,
        height=720,
        output_path=output,
        overwrite=True,
        project_id=project.id,
        quality="standard",
    )
    assert len(config.music_tracks) == 1
    assert config.music_tracks[0].volume == pytest.approx(0.22)
    assert config.music_tracks[0].fade_in_s == pytest.approx(0.5)
    placed = [
        (track.start_s, track.source_in_s, track.source_out_s) for track in config.sfx_tracks
    ]
    assert placed[0] == pytest.approx((1.0, 0.5, 1.5))
    assert placed[1][0] == pytest.approx(2.4)
    assert placed[1][1] == pytest.approx(0.0)
    assert placed[1][2] == pytest.approx(0.8, abs=0.05)
    rendered = FfmpegStudioEncoder().render(config)
    assert rendered == output
    assert output.stat().st_size > 0

    samples = _decode_mono(ffmpeg, output)
    rate = 8000
    duration = len(samples) / rate
    assert 3.6 < duration < 4.6
    peak = max(abs(sample) for sample in samples)
    assert 0.05 < peak < 0.98

    source_early = _tone(samples, rate, 0.4, 0.3, 220)
    source_late = _tone(samples, rate, 3.45, 0.3, 220)
    music_early = _tone(samples, rate, 0.08, 0.12, 660)
    music_late = _tone(samples, rate, 1.4, 0.3, 660)
    trimmed = _tone(samples, rate, 1.55, 0.3, 1500)
    crack_before = _tone(samples, rate, 0.35, 0.3, 2000)
    crack_fade = _tone(samples, rate, 1.05, 0.12, 2000)
    crack_body = _tone(samples, rate, 1.55, 0.3, 2000)
    crack_after = _tone(samples, rate, 2.6, 0.3, 2000)
    wind_during = _tone(samples, rate, 2.6, 0.3, 1800)
    wind_before = _tone(samples, rate, 1.55, 0.3, 1800)
    levels = {
        "source_early": source_early,
        "source_late": source_late,
        "music_early": music_early,
        "music_late": music_late,
        "trimmed": trimmed,
        "crack_before": crack_before,
        "crack_fade": crack_fade,
        "crack_body": crack_body,
        "crack_after": crack_after,
        "wind_during": wind_during,
        "wind_before": wind_before,
        "peak": peak,
        "duration": duration,
    }
    assert source_early > 0.02 and source_late > 0.02, levels
    assert music_late > music_early * 2 and music_late > 0.02, levels
    assert crack_body > crack_before * 4 and crack_body > 0.02, levels
    assert crack_fade < crack_body * 0.6 and crack_fade > crack_before * 1.5, levels
    assert trimmed < crack_body / 4, levels
    assert crack_after < crack_body / 4, levels
    assert wind_during > wind_before * 4 and wind_during > 0.02, levels
    assert music_late > 0.02 and crack_body > 0.02, levels

    with story_edit(db, project.id):
        db.patch_studio_sfx_clip(project.id, first.id, start_s=0.2)
    moved = db.get_studio_sfx_clip(project.id, first.id)
    assert moved is not None and moved.start_s == pytest.approx(0.2)
    assert undo_story(db, project.id) is True
    restored = db.get_studio_sfx_clip(project.id, first.id)
    assert restored is not None and restored.start_s == pytest.approx(1.0)
    assert redo_story(db, project.id) is True
    redone = db.get_studio_sfx_clip(project.id, first.id)
    assert redone is not None and redone.start_s == pytest.approx(0.2)
    assert undo_story(db, project.id) is True

    reopened = Database(db.path)
    clips = reopened.list_studio_sfx(project.id)
    assert clips[0].id == first.id
    assert clips[0].start_s == pytest.approx(1.0)
    assert clips[0].source_in_s == pytest.approx(0.5)
    assert clips[0].source_out_s == pytest.approx(1.5)
    assert clips[1].id == second.id
    assert clips[1].start_s == pytest.approx(2.4)
    assert clips[1].source_in_s == pytest.approx(0.0)
    assert clips[1].source_out_s == pytest.approx(0.8, abs=0.05)
    reopened_music = reopened.list_studio_music(project.id)
    assert reopened_music[0].volume == pytest.approx(0.22)
    assert reopened_music[0].fade_in_s == pytest.approx(0.5)
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in originals} == originals


def _ffmpeg(ffmpeg: str, args: list[str]) -> None:
    proc = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args],
        check=False,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]


def _decode_mono(ffmpeg: str, path: Path) -> array.array[float]:
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "f32le",
            "pipe:1",
        ],
        check=False,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    usable = len(proc.stdout) - (len(proc.stdout) % 4)
    samples: array.array[float] = array.array("f")
    samples.frombytes(proc.stdout[:usable])
    return samples


def _tone(
    samples: array.array[float],
    rate: int,
    start_s: float,
    duration_s: float,
    frequency: float,
) -> float:
    start = int(start_s * rate)
    end = int((start_s + duration_s) * rate)
    window = samples[start:end]
    count = len(window)
    if count < 8:
        return 0.0
    step = 2 * math.pi * frequency / rate
    real = 0.0
    imag = 0.0
    for index, sample in enumerate(window):
        real += sample * math.cos(step * index)
        imag += sample * math.sin(step * index)
    return 2 * math.hypot(real, imag) / count
