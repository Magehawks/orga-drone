"""Compare packaged photo LUT playback/compositing with real application exports.

Only generated swatches and an isolated data directory are used. Run against
both baseline and candidate EXEs; a completed run is evidence, not human approval.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw

from orga_drone.db import Database
from studio_clock_probe import seek  # type: ignore[import-not-found]
from studio_color_probe import COLORS, compare, export, image_bytes  # type: ignore[import-not-found]
from studio_crossfade_lut_probe import write_cube  # type: ignore[import-not-found]
from windows_e2e import (  # type: ignore[import-not-found]
    AppProcess,
    expect_ok,
    fetch_json,
    navigate,
    sha256_file,
    wait_until,
)


def patch(cdp, clip: str, field: str, value: dict) -> None:
    expect_ok(fetch_json(cdp, f"/api/studio/{clip}/{field}", method="PATCH", json_body=value), field)


def capture(cdp, *, screen: bool = False) -> tuple[Image.Image, dict]:
    # Pixel capture and Story timestamp are read in the same JS task.
    value = cdp.evaluate("""(()=>({
      png:document.getElementById('studio-preview-blit').toDataURL().split(',')[1],
      time:parseFloat(document.getElementById('studio-playhead').style.left)/
        document.getElementById('studio-timeline-scroll').clientWidth*Number(document.getElementById('studio-root').dataset.totalS),
      roundedTime:Number(document.getElementById('studio-playhead').getAttribute('aria-valuenow')),
      requests:performance.getEntriesByType('resource').filter(e=>e.name.includes('/preview-frame?')).length,
      primaryStill:!document.getElementById('studio-preview-lut-still').hidden,
      stillSize:[document.getElementById('studio-preview-lut-still').naturalWidth,document.getElementById('studio-preview-lut-still').naturalHeight],
      layers:['studio-preview-image','studio-preview-image-b','studio-preview-video','studio-preview-video-b'].map(id=>{
        const m=document.getElementById(id);
        return {id,hidden:m.hidden,pending:m.classList.contains('is-pending'),opacity:m.style.opacity,
          filter:m.style.filter,currentTime:m.currentTime??null,readyState:m.readyState??null,
          size:[m.videoWidth||m.naturalWidth||0,m.videoHeight||m.naturalHeight||0]};
      }),
      webgl:document.getElementById('studio-preview-frame').dataset.lutWebgl,
      failedChip:[document.getElementById('studio-root').dataset.lutChipFailed,document.getElementById('studio-root').dataset.lutChipMissing].includes(document.getElementById('studio-preview-lut-chip').textContent),
      chip:document.getElementById('studio-preview-lut-chip').textContent
    }))()""")
    pixels = image_bytes(value.pop("png"))
    if screen:
        rect = cdp.evaluate("(()=>{const r=document.getElementById('studio-preview-frame').getBoundingClientRect();"
                            "return {x:r.x,y:r.y,width:r.width,height:r.height,scale:1}})()")
        pixels = image_bytes(cdp.call("Page.captureScreenshot", dict(format="png", clip=rect,
                                                                   captureBeyondViewport=True))["data"])
    return pixels, value


def reference(binary: str, path: Path, story_time: float) -> tuple[Image.Image, int]:
    index = max(0, round(story_time * 30))
    data = subprocess.run(
        [binary, "-v", "error", "-i", str(path), "-vf",
         f"select=eq(n\\,{index}),scale=640:360", "-frames:v", "1",
         "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, check=True, timeout=60,
    ).stdout
    return Image.open(io.BytesIO(data)).convert("RGB"), index


def run(args) -> dict:
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    library = out / "synthetic-library"
    library.mkdir()
    data = out / "data"
    data.mkdir()
    image = Image.new("RGB", (1280, 720))
    draw = ImageDraw.Draw(image)
    for i, color in enumerate(COLORS):
        x, y = i % 4 * 320, i // 4 * 360
        draw.rectangle((x, y, x + 319, y + 359), fill=color)
    image.save(library / "swatches.png")
    image.save(library / "swatches.jpg", quality=98, subsampling=0)
    subprocess.run(
        [args.ffmpeg, "-v", "error", "-loop", "1", "-i", str(library / "swatches.png"),
         "-t", "3", "-vf", "scale=1280:720:out_color_matrix=bt709:out_range=tv,"
         "format=yuv420p,setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv",
         "-r", "30", "-c:v", "libx264", "-crf", "10", str(library / "swatches.mp4")],
        check=True, timeout=60,
    )
    db = Database(data / "orga-drone.sqlite3")
    root = db.add_root(library)
    ids = {}
    for path in sorted(library.iterdir()):
        kind = "video" if path.suffix == ".mp4" else "photo"
        stat = path.stat()
        asset = db.upsert_asset(root_id=root, path=path, kind=kind, size_bytes=stat.st_size,
                                mtime=stat.st_mtime, stem_base=path.stem)
        ids[path.suffix[1:]] = db.upsert_media(dict(
            root_id=root, primary_asset_id=asset, kind=kind, filename=path.name, path=str(path),
            size_bytes=stat.st_size, duration_s=3 if kind == "video" else None,
            width=1280, height=720, has_srt=0, has_lrf=0,
        ))
    hashes = {p.name: sha256_file(p) for p in library.iterdir()}
    resources = args.exe.resolve().parent / "_internal" / "orga_drone" / "static" / "js"
    report = {"exe_sha256": sha256_file(args.exe),
              "studio_js_sha256": sha256_file(resources / "studio.js"),
              "lut_webgl_sha256": sha256_file(resources / "studio-lut-webgl.js"),
              "ffmpeg_version": subprocess.check_output([args.ffmpeg, "-version"], text=True).splitlines()[0],
              "synthetic_only": True,
              "source_hashes": hashes, "cases": [], "status": "INCOMPLETE"}
    app = AppProcess(args.exe.resolve(), data)
    try:
        app.start()
        cdp = app.require_cdp()
        report["browser"] = cdp.call("Browser.getVersion")
        cdp.call("Emulation.setDeviceMetricsOverride", dict(width=1500, height=1000,
                                                           deviceScaleFactor=1, mobile=False))
        navigate(cdp, app.app_port, "/")
        assets = {}
        for variant in ("red", "blue"):
            cube = out / f"synthetic-{variant}.cube"
            write_cube(cube, size=17, variant=variant)
            assets[variant] = expect_ok(fetch_json(cdp, "/api/luts", method="POST",
                                                  json_body={"path": str(cube)}), "lut")["asset_name"]
        cases = [(f"{fmt}-{look}", [fmt], look) for fmt in ("jpg", "png")
                 for look in ("neutral", "creative0", "creative50", "creative100", "conversion")]
        cases += [("photos-different", ["jpg", "png"], "different"),
                  ("photo-video", ["jpg", "mp4"], "creative100"),
                  ("video-photo", ["mp4", "png"], "creative100")]
        if args.decorated:
            cases = [("jpg-neutral", ["jpg"], "neutral"), ("jpg-creative100", ["jpg"], "creative100")]
        report["decorated_screen_capture"] = args.decorated
        for name, formats, setting in cases:
            case_dir = out / name
            case_dir.mkdir()
            pid = expect_ok(fetch_json(cdp, "/api/studio/projects", method="POST",
                                      json_body={"title": "Synthetic photo LUT " + name}), "project")["id"]
            expect_ok(fetch_json(cdp, f"/api/studio/projects/{pid}/open", method="POST"), "open")
            for fmt in formats:
                expect_ok(fetch_json(cdp, f"/media/{ids[fmt]}/studio/add", method="POST",
                                     form_body={"return_to": "studio"}), "add")
            navigate(cdp, app.app_port, "/studio")
            clips = cdp.evaluate("[...document.querySelectorAll('.studio-clip')].map(c=>c.dataset.studioId)")
            for i, (clip, fmt) in enumerate(zip(clips, formats, strict=True)):
                if fmt != "mp4":
                    patch(cdp, clip, "photo-duration", {"duration_s": 3})
                look = {"input_profile": "rec709", "creative_strength": 100}
                if setting.startswith("creative") or setting == "different":
                    look.update(creative_lut=assets["blue" if setting == "different" and i else "red"],
                                creative_strength=int(setting[8:]) if setting.startswith("creative") else 100)
                if setting == "conversion":
                    look.update(input_profile="custom", conversion_lut=assets["red"], conversion_confirmed=True)
                patch(cdp, clip, "color", look)
            if args.decorated:
                patch(cdp, clips[0], "image", {"exposure": 8, "contrast": 5, "saturation": 12})
                patch(cdp, clips[0], "frame", {"zoom_start": 1.15, "zoom_end": 1.15,
                                               "x_start": 0.55, "x_end": 0.55,
                                               "y_start": 0.45, "y_end": 0.45})
                patch(cdp, clips[0], "masks", {"masks": [{"effect": "blur", "strength": 55,
                      "x": 0.2, "y": 0.15, "w": 0.2, "h": 0.3}]})
            if len(clips) == 2:
                patch(cdp, clips[0], "transition", {"type": "crossfade", "duration_s": 1})
            navigate(cdp, app.app_port, "/studio")
            wait_until(cdp, "document.getElementById('studio-preview-blit')?.width>0",
                       timeout_s=30, description="preview canvas")
            cdp.evaluate("document.getElementById('studio-preview-frame').style.cssText="
                         "'width:640px;height:360px;max-width:none;border:0;padding:0;flex-shrink:0';"
                         "document.querySelector('[data-timeline-zoom=fit]').click()")
            if args.decorated:
                # Compare picture layers, excluding editor handles and status UI.
                cdp.evaluate("(()=>{const s=document.createElement('style');s.textContent="
                             "'#studio-preview-mask-handles,#studio-preview-lut-chip{visibility:hidden!important}';"
                             "document.head.append(s)})()")
            if setting != "neutral":
                wait_until(cdp, "!document.getElementById('studio-preview-lut-still').hidden||"
                           "document.getElementById('studio-preview-frame').dataset.lutWebgl==='1'||"
                           "document.getElementById('studio-preview-lut-chip').textContent==="
                           "document.getElementById('studio-root').dataset.lutChipFailed",
                           timeout_s=30, description="initial graded frame decoded")
            output = case_dir / "export.mp4"
            export(cdp, pid, output)
            row = {"name": name, "formats": formats, "frames": [], "export_sha256": sha256_file(output)}

            def record(label: str) -> None:
                preview, state = capture(cdp, screen=args.decorated)
                ref, index = reference(args.ffmpeg, output, state["time"])
                preview.save(case_dir / f"{label}-preview.png")
                ref.save(case_dir / f"{label}-export.png")
                metrics = compare(preview, ref)
                row["frames"].append(dict(label=label, state=state, export_frame=index,
                                          export_time=index / 30, comparison=metrics,
                                          strict_pass=metrics["max_swatch_mean_rgb_error"] <= 3))

            points = [2.25, 2.5, 2.75] if len(clips) == 2 else [0.5]
            for point in points:
                seek(cdp, point)
                time.sleep(0.8)
                record(f"paused-{point}")
            for label, point in (("continuous", 1.7 if len(clips) == 2 else 0.1),
                                 ("inside", 2.25 if len(clips) == 2 else 0.5)):
                seek(cdp, point)
                time.sleep(0.8)
                _, before = capture(cdp)
                cdp.evaluate("document.querySelector('[data-transport=toggle]').click()", user_gesture=True)
                time.sleep(0.65)
                record(label + "-playing")
                cdp.evaluate("document.querySelector('[data-transport=toggle]').click()", user_gesture=True)
                time.sleep(0.4)
                record(label + "-after-pause")
                row.setdefault("request_deltas", []).append(capture(cdp)[1]["requests"] - before["requests"])
            report["cases"].append(row)
            (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(name, max(f["comparison"]["max_swatch_mean_rgb_error"] for f in row["frames"]), flush=True)
        frames = [frame for case in report["cases"] for frame in case["frames"]]
        report["strict_all_pass"] = all(frame["strict_pass"] for frame in frames)
        neutral = {case["formats"][0]: max(frame["comparison"]["max_swatch_mean_rgb_error"]
                    for frame in case["frames"]) for case in report["cases"] if case["name"].endswith("neutral")}
        photo_cases = [case for case in report["cases"] if "mp4" not in case["formats"]]
        for case in photo_cases:
            bound = max(neutral[fmt] for fmt in case["formats"]) + 1.5
            for frame in case["frames"]:
                frame["bounded_threshold"] = bound
                frame["bounded_pass"] = frame["comparison"]["max_swatch_mean_rgb_error"] <= bound
        report["bounded_photo_pass"] = all(frame["bounded_pass"] for case in photo_cases for frame in case["frames"])
        report["photo_fix_pass"] = all(frame["strict_pass"] and not frame["state"]["failedChip"] and
                                       (len(case["formats"]) != 1 or frame["state"]["primaryStill"]) for case in photo_cases
                                       if not case["name"].endswith("neutral") for frame in case["frames"])
        report["status"] = "COMPLETE"
    finally:
        app.stop()
        report["sources_unchanged"] = hashes == {p.name: sha256_file(p) for p in library.iterdir()}
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-photo-fix", action="store_true",
                        help="Fail if colored photo-only preview frames exceed the unchanged strict gate")
    parser.add_argument("--decorated", action="store_true",
                        help="Additional grade/framing/blur-mask smoke using actual preview-screen captures")
    args = parser.parse_args()
    result = run(args)
    if args.expect_photo_fix and not result["photo_fix_pass"]:
        raise SystemExit("Photo lifecycle/color gate failed; inspect report.json")
