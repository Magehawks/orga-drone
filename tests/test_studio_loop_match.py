"""Local seam search for a repeated section. No cloud and no new renderer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_loop_match import (
    MATCH_HEIGHT,
    MATCH_WIDTH,
    analyze_loop_seam,
    choose_seam,
)


def _solid(red: int, green: int, blue: int) -> bytes:
    return bytes((red, green, blue)) * (MATCH_WIDTH * MATCH_HEIGHT)


def test_seam_sampling_hides_the_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"not a real video")
    seen: list[dict[str, object]] = []

    def fake_run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen.append(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=1, stdout=b"")

    monkeypatch.setattr("orga_drone.ffmpeg_bin.find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("orga_drone.studio_loop_match.subprocess.run", fake_run)
    warned = analyze_loop_seam(source, 0.0, 4.0)
    assert warned.confidence == "low"
    assert len(seen) == 2
    if sys.platform == "win32":
        flag = subprocess.CREATE_NO_WINDOW
        assert all(call.get("creationflags") == flag for call in seen)
        assert all(call.get("startupinfo") is not None for call in seen)


def test_seam_shifts_only_when_the_ends_actually_agree() -> None:
    blue = _solid(0, 0, 220)
    red = _solid(220, 20, 20)
    green = _solid(20, 200, 20)
    shifted = choose_seam(
        user_in_s=0.0,
        user_out_s=4.0,
        start_frames=[(0.0, blue), (1.0, red)],
        end_frames=[(3.0, red), (4.0, green)],
    )
    assert shifted.confidence == "ok"
    assert shifted.applied is True
    assert shifted.source_in_s == pytest.approx(1.0)
    assert shifted.source_out_s == pytest.approx(3.0)
    assert shifted.crossfade_s == 0

    mismatch = choose_seam(
        user_in_s=0.0,
        user_out_s=4.0,
        start_frames=[(0.0, blue), (1.0, blue)],
        end_frames=[(3.0, green), (4.0, green)],
    )
    assert mismatch.confidence == "low"
    assert mismatch.applied is False
    assert mismatch.source_in_s == pytest.approx(0.0)
    assert mismatch.source_out_s == pytest.approx(4.0)
    assert mismatch.crossfade_s == 0


def test_matching_file_reports_the_effective_range_and_a_mismatch_warns(tmp_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")

    def color_clip(path: Path, parts: list[tuple[str, float]]) -> None:
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        for color, duration in parts:
            cmd.extend(["-f", "lavfi", "-i", f"color=c={color}:s=64x48:r=30:d={duration}"])
        filters = []
        for index in range(len(parts)):
            filters.append(f"[{index}:v]format=yuv420p[v{index}]")
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
        generated = subprocess.run(cmd, check=False, capture_output=True, text=True)
        assert generated.returncode == 0, generated.stderr

    matched = tmp_path / "matched.mp4"
    color_clip(matched, [("blue", 1), ("red", 3)])
    seam = analyze_loop_seam(matched, 0.0, 4.0)
    assert seam.confidence == "ok"
    assert seam.source_in_s == pytest.approx(1.0, abs=0.3)
    assert seam.source_out_s == pytest.approx(4.0, abs=0.3)
    assert seam.source_out_s - seam.source_in_s >= 2.0

    mismatch = tmp_path / "mismatch.mp4"
    color_clip(mismatch, [("blue", 2), ("green", 2)])
    warned = analyze_loop_seam(mismatch, 0.0, 4.0)
    assert warned.confidence == "low"
    assert warned.applied is False
    assert warned.source_in_s == pytest.approx(0.0)
    assert warned.source_out_s == pytest.approx(4.0)
