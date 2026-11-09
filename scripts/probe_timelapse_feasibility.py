#!/usr/bin/env python3
"""Issue #325 feasibility probe: flat 8×/20× ramps via existing ADR 0034 adapter.

Bypasses parse_ramp MAX_SPEED by constructing SpeedRamp directly. Does not
change production limits when run against an older checkout. Exit 0 only when
every probe passes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orga_drone.export.studio_config import (  # noqa: E402
    StudioExportClip,
    StudioExportConfig,
)
from orga_drone.export.studio_encoder import FfmpegStudioEncoder  # noqa: E402
from orga_drone.export.studio_frame_plan import (  # noqa: E402
    frame_index,
    plan_story_frames,
)
from orga_drone.ffmpeg_bin import (  # noqa: E402
    find_ffmpeg,
    subprocess_no_window_kwargs,
)
from orga_drone.studio_speed_ramp import Point, SpeedRamp  # noqa: E402


def make_source(
    ffmpeg: str,
    path: Path,
    *,
    seconds: float,
    fps: int,
    width: int,
    height: int,
) -> None:
    frames = int(round(seconds * fps))
    frame_dir = path.parent / f"{path.stem}_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for n in range(frames):
        image = Image.new("RGB", (width, height), (n % 256, (n * 3) % 256, (n * 7) % 256))
        draw = ImageDraw.Draw(image)
        for bit in range(16):
            on = bool(n & (1 << bit))
            draw.rectangle((bit * 4, 0, bit * 4 + 3, 7), fill="white" if on else "black")
        image.save(frame_dir / f"{n:05d}.png")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frame_dir / "%05d.png"),
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        timeout=180,
        **subprocess_no_window_kwargs(),
    )


def flat_ramp(start: float, end: float, speed: float) -> SpeedRamp:
    return SpeedRamp((Point(start, speed), Point(end, speed)))


def decode_raw_len(ffmpeg: str, video: Path) -> int:
    return len(
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(video),
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
            timeout=300,
            **subprocess_no_window_kwargs(),
        ).stdout
    )


def export_flat(
    *,
    ffmpeg: str,
    source: Path,
    out: Path,
    speed: float,
    source_in: float,
    source_out: float,
    width: int,
    height: int,
) -> dict[str, object]:
    ramp = flat_ramp(source_in, source_out, speed)
    duration = ramp.duration(source_in, source_out)
    clip = StudioExportClip(
        source,
        "video",
        duration,
        source_start_s=source_in,
        source_end_s=source_out,
        speed_ramp=ramp,
        speed_ramp_source_in_s=source_in,
        speed_ramp_source_out_s=source_out,
    )
    config = StudioExportConfig(out, width, height, clips=(clip,))
    render_clips, _stitch = plan_story_frames(config.clips)
    expected = render_clips[0].export_frame_count or (
        frame_index(duration) - frame_index(0.0)
    )
    started = time.perf_counter()
    FfmpegStudioEncoder().render(config)
    elapsed = time.perf_counter() - started
    actual = decode_raw_len(ffmpeg, out) // (width * height * 3)
    return {
        "speed": speed,
        "source_in": source_in,
        "source_out": source_out,
        "duration_s": duration,
        "expected_frames": expected,
        "actual_frames": actual,
        "elapsed_s": round(elapsed, 3),
        "width": width,
        "height": height,
        "frame_error": actual - expected,
        "source_bytes": source.stat().st_size,
        "out_bytes": out.stat().st_size,
        "ok": actual == expected
        and abs(duration - (source_out - source_in) / speed) < 1e-9,
    }


def py_js_parity_checks() -> list[dict[str, object]]:
    results = []
    for speed, span in ((8.0, 120.0), (20.0, 300.0), (8.0, 60.0), (20.0, 60.0)):
        start, end = 30.0, 30.0 + span
        ramp = flat_ramp(start, end, speed)
        duration = ramp.duration(start, end)
        expected = span / speed
        mid_story = expected / 2
        source = ramp.source_at(mid_story, start, end)
        results.append(
            {
                "speed": speed,
                "span": span,
                "duration": duration,
                "expected": expected,
                "mid_source": source,
                "mid_expected": start + mid_story * speed,
                "ok": abs(duration - expected) < 1e-9
                and abs(source - (start + mid_story * speed)) < 1e-6,
            }
        )
    return results


def main() -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print(json.dumps({"ok": False, "error": "ffmpeg missing"}))
        return 2
    report: dict[str, object] = {"ffmpeg": ffmpeg, "parity": py_js_parity_checks()}
    failures: list[str] = []
    for item in report["parity"]:  # type: ignore[index]
        if not item["ok"]:
            failures.append(f"parity speed={item['speed']} span={item['span']}")

    with tempfile.TemporaryDirectory(prefix="timelapse325_") as tmp:
        tmp_path = Path(tmp)
        short = tmp_path / "src_8s_720.mp4"
        make_source(ffmpeg, short, seconds=8.0, fps=60, width=1280, height=720)
        longish = tmp_path / "src_20s_1080.mp4"
        make_source(ffmpeg, longish, seconds=20.0, fps=30, width=1920, height=1080)
        uhd = tmp_path / "src_10s_4k.mp4"
        make_source(ffmpeg, uhd, seconds=10.0, fps=30, width=3840, height=2160)

        cases = [
            dict(
                source=short,
                speed=8.0,
                source_in=0.0,
                source_out=8.0,
                width=1280,
                height=720,
                label="8x_full_720",
            ),
            dict(
                source=short,
                speed=8.0,
                source_in=2.0,
                source_out=8.0,
                width=1280,
                height=720,
                label="8x_trim_720",
            ),
            dict(
                source=longish,
                speed=20.0,
                source_in=0.0,
                source_out=20.0,
                width=1920,
                height=1080,
                label="20x_full_1080",
            ),
            dict(
                source=longish,
                speed=20.0,
                source_in=5.0,
                source_out=15.0,
                width=1920,
                height=1080,
                label="20x_trim_1080",
            ),
            dict(
                source=uhd,
                speed=8.0,
                source_in=0.0,
                source_out=10.0,
                width=3840,
                height=2160,
                label="8x_full_4k",
            ),
            dict(
                source=uhd,
                speed=20.0,
                source_in=0.0,
                source_out=10.0,
                width=3840,
                height=2160,
                label="20x_full_4k",
            ),
        ]

        exports: list[dict[str, object]] = []
        for case in cases:
            out = tmp_path / f"{case['label']}.mp4"
            original = case["source"].read_bytes()
            try:
                result = export_flat(
                    ffmpeg=ffmpeg,
                    source=case["source"],
                    out=out,
                    speed=case["speed"],
                    source_in=case["source_in"],
                    source_out=case["source_out"],
                    width=case["width"],
                    height=case["height"],
                )
                result["label"] = case["label"]
                result["source_intact"] = case["source"].read_bytes() == original
                if (
                    not result["ok"]
                    or not result["source_intact"]
                    or result["frame_error"] != 0
                ):
                    failures.append(case["label"])
                exports.append(result)
                status = (
                    "PASS"
                    if result["ok"] and result["source_intact"]
                    else "FAIL"
                )
                print(
                    f"{status} {case['label']}: frames={result['actual_frames']} "
                    f"dur={result['duration_s']:.4f}s elapsed={result['elapsed_s']}s"
                )
            except Exception as exc:  # noqa: BLE001 — probe must capture evidence
                failures.append(case["label"])
                exports.append(
                    {
                        "label": case["label"],
                        "ok": False,
                        "error": str(exc),
                        "trace": traceback.format_exc(),
                    }
                )
                print(f"FAIL {case['label']}: {exc}")

        ramp = flat_ramp(0.0, 8.0, 8.0)
        clips = (
            StudioExportClip(short, "video", 1.0, source_end_s=1.0),
            StudioExportClip(
                short,
                "video",
                ramp.duration(0.0, 8.0),
                source_end_s=8.0,
                speed_ramp=ramp,
            ),
            StudioExportClip(short, "video", 0.5, source_start_s=1.0, source_end_s=1.5),
        )
        mixed_out = tmp_path / "mixed_8x.mp4"
        render_clips, _stitch = plan_story_frames(clips)
        mixed_cfg = StudioExportConfig(mixed_out, 1280, 720, clips=clips)
        try:
            started = time.perf_counter()
            FfmpegStudioEncoder().render(mixed_cfg)
            elapsed = time.perf_counter() - started
            expected = sum(c.export_frame_count or 0 for c in render_clips)
            actual = decode_raw_len(ffmpeg, mixed_out) // (1280 * 720 * 3)
            mixed = {
                "label": "mixed_story_8x",
                "expected_frames": expected,
                "actual_frames": actual,
                "elapsed_s": round(elapsed, 3),
                "ok": actual == expected,
            }
            if not mixed["ok"]:
                failures.append("mixed_story_8x")
            exports.append(mixed)
            print(f"{'PASS' if mixed['ok'] else 'FAIL'} mixed_story_8x: {mixed}")
        except Exception as exc:  # noqa: BLE001
            failures.append("mixed_story_8x")
            exports.append({"label": "mixed_story_8x", "ok": False, "error": str(exc)})
            print(f"FAIL mixed_story_8x: {exc}")

        report["exports"] = exports

    report["ok"] = not failures
    report["failures"] = failures
    report["max_validated_speed"] = (
        20.0
        if not failures
        else (8.0 if all("20x" not in f for f in failures) else None)
    )
    out_path = ROOT / "docs" / "discovery" / "325-timelapse-feasibility.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "failures": failures, "written": str(out_path)}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
