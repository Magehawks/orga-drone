"""Isolated #301 CSS/FFmpeg feasibility probe, never a product/admission test.

Run against a locally built onefolder EXE. Only synthetic images and an isolated
data directory are used. A successful process exit means evidence was collected,
not that transition parity passed. No production transition ids are enabled.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

from windows_e2e import AppProcess  # type: ignore[import-not-found]  # sibling script

TRANSITIONS = ("hblur", "smoothleft", "smoothright", "smoothup", "smoothdown")
WIDTH, HEIGHT = 640, 360


def run_ffmpeg(ffmpeg: str, args: list[str]) -> bytes:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout


def synthetic(path: Path, incoming: bool) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#225f99" if incoming else "#ae6628")
    draw = ImageDraw.Draw(image)
    # Sharp horizontal and vertical edges expose isotropic vs horizontal blur.
    for x in range(0, WIDTH, 80):
        draw.rectangle((x, 0, x + 20, HEIGHT), fill="#e4dc61")
    for y in range(40, HEIGHT, 80):
        draw.rectangle((0, y, WIDTH, y + 15), fill="#191919")
    draw.ellipse((180, 80, 420, 300), fill="white" if incoming else "#35d286")
    image.save(path)


def data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    data = output / "data"
    data.mkdir(exist_ok=True)
    report: dict[str, object] = {
        "status": "BLOCKED",
        "scope": "640x360 synthetic paused CSS feasibility, isolated packaged WebView2",
        "not_validated": [
            "production preview canvas integration", "moving playback", "1080p/4K",
            "LUT", "speed", "loops", "soundtrack", "save/reload", "undo/redo",
        ],
        "samples": [],
    }
    samples: list[dict[str, object]] = []
    report_path = output / "report.json"
    # Invalidate a previous run before any preflight or app startup can fail.
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    app: AppProcess | None = None
    try:
        report["exe_sha256"] = hashlib.sha256(args.exe.read_bytes()).hexdigest()
        report["ffmpeg_version"] = run_ffmpeg(args.ffmpeg, ["-version"]).decode().splitlines()[0]
        app = AppProcess(args.exe.resolve(), data)
        paths = []
        for index in range(2):
            original = output / f"source-{index}.png"
            graded = output / f"graded-{index}.png"
            synthetic(original, bool(index))
            grade = "eq=brightness=0.08:saturation=0.65" if index else "eq=contrast=1.15:saturation=1.3"
            run_ffmpeg(args.ffmpeg, ["-i", str(original), "-vf", grade, "-frames:v", "1", str(graded)])
            paths.append(graded)
        app.start()
        cdp = app.require_cdp()
        report["browser"] = cdp.call("Browser.getVersion")
        cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": WIDTH, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False,
        })
        # Isolate CSS compositor feasibility from the real Studio blit pipeline.
        cdp.evaluate("document.documentElement.innerHTML = '<head></head><body></body>'")
        for reverse in (False, True):
            left, right = paths[::-1] if reverse else paths
            for transition in TRANSITIONS:
                name = f"{transition}-{'ba' if reverse else 'ab'}"
                rendered = output / f"{name}.mp4"
                run_ffmpeg(args.ffmpeg, [
                    "-loop", "1", "-framerate", "30", "-t", "1.5", "-i", str(left),
                    "-loop", "1", "-framerate", "30", "-t", "1.5", "-i", str(right),
                    "-filter_complex", f"[0:v][1:v]xfade=transition={transition}:duration=1:offset=0.5[v]",
                    "-map", "[v]", "-an", "-c:v", "libx264", "-crf", "10", str(rendered),
                ])
                for progress in (0.0, 0.5, 1.0):
                    reference = output / f"{name}-{progress}-export.png"
                    run_ffmpeg(args.ffmpeg, [
                        "-i", str(rendered), "-vf", f"select=eq(n\\,{15 + round(30 * progress)})",
                        "-frames:v", "1", str(reference),
                    ])
                    # Candidate from discovery: blur + opacity, or linear soft mask.
                    # No tolerance is claimed; report raw error for review.
                    direction = {
                        "smoothleft": "to left", "smoothright": "to right",
                        "smoothup": "to top", "smoothdown": "to bottom",
                    }.get(transition)
                    blur = (WIDTH / 12) * (1 - abs(2 * progress - 1)) if not direction else 0
                    opacity = progress if not direction else 1
                    mask = "none"
                    if direction:
                        start = (2 * progress - 1) * 100
                        end = 2 * progress * 100
                        mask = f"linear-gradient({direction}, black {start}%, transparent {end}%)"
                    html = (
                        '<style>html,body{margin:0;background:black;overflow:hidden}'
                        f'img{{position:absolute;width:{WIDTH}px;height:{HEIGHT}px;left:0;top:0}}'
                        '</style>'
                        f'<img src="{data_url(left)}" style="filter:blur({blur}px)">'
                        f'<img src="{data_url(right)}" style="opacity:{opacity};filter:blur({blur}px);mask-image:{mask}">'
                    )
                    cdp.evaluate(f"document.body.innerHTML = {json.dumps(html)}")
                    cdp.evaluate(
                        "Promise.all([...document.images].map(i=>i.decode())).then(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))",
                        await_promise=True,
                    )
                    screenshot = cdp.call("Page.captureScreenshot", {"format": "png"})
                    preview = Image.open(io.BytesIO(base64.b64decode(screenshot["data"]))).convert("RGB")
                    preview_path = output / f"{name}-{progress}-preview.png"
                    preview.save(preview_path)
                    expected = Image.open(reference).convert("RGB")
                    difference = ImageChops.difference(preview, expected)
                    samples.append({
                        "transition": transition, "reverse": reverse, "progress": progress,
                        "mean_absolute_rgb_error_255": sum(ImageStat.Stat(difference).mean) / 3,
                        "export": reference.name, "preview": preview_path.name,
                    })
        report["status"] = "EVIDENCE_COLLECTED_NOT_APPROVED"
    except Exception as exc:  # noqa: BLE001 - preserve failed-spike evidence
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if app is not None:
            try:
                app.stop()
            except Exception as exc:  # noqa: BLE001 - retain evidence on teardown failure
                report["status"] = "BLOCKED"
                report["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        report["samples"] = samples
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "EVIDENCE_COLLECTED_NOT_APPROVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
