"""Packaged Studio crossfade + LUT integration probe.

Synthetic 3 s tagged BT.709 palette clips, one 1 s crossfade, real package.
Runs with no LUT, one creative LUT on both clips, or two different LUTs.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio_clock_probe import OBSERVE, SNAPSHOT, seek, summarize  # noqa: E402
from studio_color_probe import (  # noqa: E402
    COLORS,
    compare,
    export,
    image_bytes,
)
from windows_e2e import (  # noqa: E402
    AppProcess,
    E2EError,
    expect_ok,
    fetch_json,
    navigate,
    sha256_file,
    wait_until,
)


def write_cube(path: Path, *, size: int, variant: str) -> None:
    slopes = {
        "red": (0.8, 0.5, 0.4),
        "blue": (0.4, 0.5, 0.8),
    }[variant]
    rows = [f'TITLE "Synthetic {variant}"', f"LUT_3D_SIZE {size}"]
    denom = size - 1
    for b in range(size):
        for g in range(size):
            for r in range(size):
                rows.append(
                    f"{0.1 + (r / denom) * slopes[0]:.8f} "
                    f"{0.1 + (g / denom) * slopes[1]:.8f} "
                    f"{0.1 + (b / denom) * slopes[2]:.8f}"
                )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def decode_at(binary: str, path: Path, t_s: float) -> Image.Image:
    result = subprocess.run(
        [
            binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ss",
            f"{t_s:.6f}",
            "-frames:v",
            "1",
            "-vf",
            "scale=640:360",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ],
        capture_output=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        raise E2EError(result.stderr.decode(errors="replace"))
    import io

    return Image.open(io.BytesIO(result.stdout)).convert("RGB")


def brightness(image: Image.Image) -> float:
    return round(sum(ImageStat.Stat(image).mean) / 3, 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lut-mode", choices=["none", "one", "two"], default="none")
    parser.add_argument("--lut-size", type=int, default=17)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Use a new/empty output directory")
    out.mkdir(parents=True, exist_ok=True)
    library, data = out / "library", out / "data"
    library.mkdir()
    data.mkdir()
    report: dict = {"status": "INCOMPLETE", "lut_mode": args.lut_mode, "errors": []}
    report_path = out / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    app = None
    try:
        report["exe_sha256"] = sha256_file(args.exe)
        report["studio_js_sha256"] = sha256_file(
            args.exe.resolve().parent / "_internal/orga_drone/static/js/studio.js"
        )
        report["studio_lut_webgl_sha256"] = sha256_file(
            args.exe.resolve().parent
            / "_internal/orga_drone/static/js/studio-lut-webgl.js"
        )
        palette = Image.new("RGB", (640, 360))
        draw = ImageDraw.Draw(palette)
        for i, color in enumerate(COLORS):
            x, y = i % 4 * 160, i // 4 * 180
            draw.rectangle((x, y, x + 159, y + 179), fill=color)
        palette.save(out / "palette.png")
        files = [library / "lut-a.mp4", library / "lut-b.mp4"]
        for i, path in enumerate(files):
            subprocess.run(
                [
                    args.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-loop",
                    "1",
                    "-framerate",
                    "30",
                    "-i",
                    str(out / "palette.png"),
                    "-t",
                    "3",
                    "-vf",
                    "drawbox=x='mod(t*120,600)':y=5:w=30:h=20:color=white@1:t=fill,"
                    "scale=1280:720:out_color_matrix=bt709:out_range=tv,format=yuv420p,"
                    "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-crf",
                    "10",
                    "-preset",
                    "ultrafast",
                    "-colorspace",
                    "bt709",
                    "-color_primaries",
                    "bt709",
                    "-color_trc",
                    "bt709",
                    "-color_range",
                    "tv",
                    str(path),
                ],
                check=True,
                timeout=120,
            )
            os.utime(path, (1700000000 + i * 86400,) * 2)
        sources = sorted(library.glob("*.mp4"))
        hashes = {p.name: sha256_file(p) for p in sources}
        app = AppProcess(args.exe.resolve(), data)
        app.start()
        cdp = app.require_cdp()
        report["browser"] = cdp.call("Browser.getVersion")
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1500, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
        )
        navigate(cdp, app.app_port, "/")
        expect_ok(
            fetch_json(
                cdp,
                "/library/add",
                method="POST",
                form_body={"path": str(library), "label": "Synthetic crossfade LUT"},
            ),
            "scan",
        )
        deadline = time.monotonic() + 90
        while True:
            found = expect_ok(
                fetch_json(cdp, "/api/search", method="POST", json_body={"q": ""}),
                "find",
            )
            ids = {it["filename"]: it["id"] for it in found["items"]}
            if all(p.name in ids for p in sources):
                break
            if time.monotonic() > deadline:
                raise E2EError("Synthetic scan incomplete")
            time.sleep(0.5)
        pid = expect_ok(
            fetch_json(
                cdp,
                "/api/studio/projects",
                method="POST",
                json_body={"title": "Crossfade LUT integration"},
            ),
            "create",
        )["id"]
        expect_ok(
            fetch_json(cdp, f"/api/studio/projects/{pid}/open", method="POST"), "open"
        )
        for path in files:
            expect_ok(
                fetch_json(
                    cdp,
                    f"/media/{ids[path.name]}/studio/add",
                    method="POST",
                    form_body={"return_to": "studio"},
                ),
                "add",
            )
        navigate(cdp, app.app_port, "/studio")
        wait_until(
            cdp,
            "document.querySelectorAll('.studio-clip').length===2",
            timeout_s=30,
            description="Story clips",
        )
        clip_ids = cdp.evaluate(
            "[...document.querySelectorAll('.studio-clip')].map(c=>c.dataset.studioId)"
        )
        expect_ok(
            fetch_json(
                cdp,
                f"/api/studio/{clip_ids[0]}/transition",
                method="PATCH",
                json_body={"type": "crossfade", "duration_s": 1},
            ),
            "crossfade",
        )
        assets: dict[str, str] = {}
        if args.lut_mode != "none":
            for variant in ("red", "blue") if args.lut_mode == "two" else ("red",):
                cube = out / f"{variant}.cube"
                write_cube(cube, size=args.lut_size, variant=variant)
                imported = expect_ok(
                    fetch_json(
                        cdp,
                        "/api/luts",
                        method="POST",
                        json_body={"path": str(cube)},
                    ),
                    f"import {variant}",
                )
                assets[variant] = imported["asset_name"]
            if args.lut_mode == "one":
                for clip_id in clip_ids:
                    expect_ok(
                        fetch_json(
                            cdp,
                            f"/api/studio/{clip_id}/color",
                            method="PATCH",
                            json_body={
                                "input_profile": "rec709",
                                "creative_lut": assets["red"],
                                "creative_strength": 100,
                            },
                        ),
                        "apply one LUT",
                    )
            else:
                for clip_id, variant in zip(clip_ids, ("red", "blue")):
                    expect_ok(
                        fetch_json(
                            cdp,
                            f"/api/studio/{clip_id}/color",
                            method="PATCH",
                            json_body={
                                "input_profile": "rec709",
                                "creative_lut": assets[variant],
                                "creative_strength": 100,
                            },
                        ),
                        f"apply {variant}",
                    )
        navigate(cdp, app.app_port, "/studio")
        wait_until(
            cdp,
            "document.getElementById('studio-preview-video')?.readyState>=2",
            timeout_s=30,
            description="preview",
        )
        cdp.evaluate(
            "document.getElementById('studio-preview-frame').style.cssText='width:640px;height:360px;max-width:none;border:0;padding:0;flex-shrink:0';document.querySelector('[data-timeline-zoom=fit]').click()"
        )
        if args.lut_mode != "none":
            wait_until(
                cdp,
                "document.getElementById('studio-preview-frame').dataset.lutWebgl==='1'",
                timeout_s=30,
                description="WebGL LUT",
            )
        cdp.evaluate(OBSERVE)
        seek(cdp, 2.5)
        paused_samples = []
        paused = None
        for delay in (0.05, 0.2, 0.5, 1.0):
            time.sleep(delay)
            image = image_bytes(
                cdp.evaluate(
                    "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
                )
            )
            paused_samples.append({
                "delay": delay,
                "brightness": brightness(image),
                "state": cdp.evaluate(SNAPSHOT),
            })
            if paused is None:
                paused = image
        report["paused_brightness_samples"] = paused_samples
        cdp.evaluate("document.getElementById('studio-preview-video-b').dispatchEvent(new Event('seeked'))")
        time.sleep(0.3)
        kicked = image_bytes(
            cdp.evaluate(
                "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
            )
        )
        report["paused_after_seeked_kick_brightness"] = brightness(kicked)
        kicked.save(out / "paused-after-kick.png")
        time.sleep(0.2)
        paused = image_bytes(
            cdp.evaluate(
                "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
            )
        )
        paused.save(out / "paused.png")
        cdp.evaluate(
            "(() => {const f=document.getElementById('studio-preview-frame');"
            "f.style.width='641px';requestAnimationFrame(()=>{f.style.width='640px';});})()"
        )
        time.sleep(0.4)
        paused_forced = image_bytes(
            cdp.evaluate(
                "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
            )
        )
        paused_forced.save(out / "paused-forced.png")
        report["paused_forced_brightness"] = brightness(paused_forced)
        for layer, layer_id in (("primary", "studio-preview-video"), ("outgoing", "studio-preview-video-b")):
            encoded = cdp.evaluate(
                f"""(() => {{const v=document.getElementById('{layer_id}');
                  const c=document.createElement('canvas');c.width=640;c.height=360;
                  const x=c.getContext('2d');x.drawImage(v,0,0,640,360);
                  return c.toDataURL().split(',')[1];}})()"""
            )
            (out / f"{layer}-alone.png").write_bytes(base64.b64decode(encoded))
        report["layer_state"] = cdp.evaluate(
            "(() => {const a=document.getElementById('studio-preview-video');"
            "const b=document.getElementById('studio-preview-video-b');"
            "return {primary:{className:a.className,width:a.videoWidth,height:a.videoHeight,hidden:a.hidden,opacity:a.style.opacity},"
            "outgoing:{className:b.className,width:b.videoWidth,height:b.videoHeight,hidden:b.hidden,opacity:b.style.opacity}};})()"
        )
        report["paused_state"] = cdp.evaluate(SNAPSHOT)
        report["webgl"] = cdp.evaluate(
            "({a:document.getElementById('studio-preview-frame').dataset.lutWebgl,"
            "b:!document.getElementById('studio-preview-lut-still').hidden})"
        )
        exported = out / "story-export.mp4"
        export(cdp, pid, exported)
        report["export_sha256"] = sha256_file(exported)
        reference = decode_at(args.ffmpeg, exported, 2.5)
        reference.save(out / "export-2.5.png")
        report["paused_vs_export"] = compare(paused, reference)
        report["paused_brightness"] = brightness(paused)
        seek(cdp, 1.4)
        cdp.evaluate(
            "document.querySelector('[data-transport=toggle]').click()",
            user_gesture=True,
        )
        samples = cdp.evaluate(
            """new Promise(resolve=>{const samples=[];const start=performance.now();
          const collect=()=>{samples.push("""
            + SNAPSHOT
            + """);
           if(performance.now()-start>2600){resolve(samples);return;}requestAnimationFrame(collect);};
           requestAnimationFrame(collect);})""",
            await_promise=True,
        )
        report["playback"] = samples
        report["playback_summary"] = summarize({"transition": "crossfade", "playback": samples})
        cdp.evaluate("document.querySelector('[data-transport=toggle]').click()")
        seek(cdp, 2.4)
        cdp.evaluate(
            "document.querySelector('[data-transport=toggle]').click()",
            user_gesture=True,
        )
        inside = cdp.evaluate(
            """new Promise(resolve=>{const samples=[];const start=performance.now();
          const collect=()=>{samples.push("""
            + SNAPSHOT
            + """);
           if(performance.now()-start>1000){resolve(samples);return;}requestAnimationFrame(collect);};
           requestAnimationFrame(collect);})""",
            await_promise=True,
        )
        cdp.evaluate("document.querySelector('[data-transport=toggle]').click()")
        report["inside_crossfade_summary"] = summarize(
            {"transition": "crossfade", "playback": inside}
        )
        seek(cdp, 1.5)
        cdp.evaluate(
            "document.querySelector('[data-transport=toggle]').click()",
            user_gesture=True,
        )
        time.sleep(0.2)
        seek(cdp, 0.5)
        time.sleep(0.3)
        report["preroll_cancel"] = cdp.evaluate(
            "(() => {const a=document.getElementById('studio-preview-video');"
            "const b=document.getElementById('studio-preview-video-b');"
            "return {primary:{paused:a.paused,seeking:a.seeking,currentTime:a.currentTime},"
            "outgoing:{hidden:b.hidden,paused:b.paused,seeking:b.seeking,currentTime:b.currentTime}};})()"
        )
        seek_images = []
        for index, t in enumerate([0, 1.5, 2.4, 2.6, 3.2, 1.5]):
            seek(cdp, t)
            image = image_bytes(
                cdp.evaluate(
                    "document.getElementById('studio-preview-blit').toDataURL().split(',')[1]"
                )
            )
            image.save(out / f"seek-{index}.png")
            seek_images.append(brightness(image))
        report["seek_brightness"] = seek_images
        report["source_unchanged"] = hashes == {
            p.name: sha256_file(p) for p in sources
        }
        report["status"] = "COMPLETE_INTEGRATION_DIAGNOSTIC"
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if app:
            try:
                app.stop()
            except Exception as exc:  # noqa: BLE001
                report["status"] = "INCOMPLETE"
                report["errors"].append(str(exc))
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "lut_mode": report["lut_mode"],
                "errors": report["errors"],
            }
        )
    )
    return 0 if report["status"] == "COMPLETE_INTEGRATION_DIAGNOSTIC" else 1


if __name__ == "__main__":
    raise SystemExit(main())
