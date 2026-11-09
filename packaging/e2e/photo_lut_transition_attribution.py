"""Analysis-only exact-alpha and standalone-video controls for synthetic probe data."""

from __future__ import annotations

import argparse
import io
import json
import sqlite3
import subprocess
import time
from pathlib import Path

from studio_clock_probe import seek
from orga_drone.export.studio_encoder import _segment_vf
from orga_drone.studio_lut import ColorLook, escape_ffmpeg_lut_path, ffmpeg_lut_chain
from PIL import Image

from studio_color_probe import compare, export, image_bytes
from studio_photo_lut_probe import capture, patch, reference
from windows_e2e import AppProcess, expect_ok, fetch_json, navigate, sha256_file


def run(args) -> None:
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    fixture = args.fixture_run.resolve()
    original = json.loads((fixture / "report.json").read_text(encoding="utf-8"))
    if not original["synthetic_only"] or not original["sources_unchanged"]:
        raise ValueError("Requires completed synthetic photo probe data")
    data = fixture / "data"
    with sqlite3.connect((data / "orga-drone.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        projects = dict(db.execute("select title,id from studio_projects"))
        video_id = db.execute("select id from media where filename='swatches.mp4'").fetchone()[0]
    app = AppProcess(args.exe.resolve(), data)
    report = {"synthetic_only": True, "analysis_only": True, "controls": [],
              "exe_sha256": sha256_file(args.exe), "ffmpeg_sha256": sha256_file(Path(args.ffmpeg))}
    try:
        app.start()
        cdp = app.require_cdp()
        cdp.call("Emulation.setDeviceMetricsOverride", dict(width=1500, height=1000, deviceScaleFactor=1, mobile=False))
        navigate(cdp, app.app_port, "/")

        def open_project(pid):
            expect_ok(fetch_json(cdp, f"/api/studio/projects/{pid}/open", method="POST"), "open")
            navigate(cdp, app.app_port, "/studio")
            cdp.evaluate("if(document.getElementById('studio-preview-frame')) document.getElementById('studio-preview-frame').style.cssText="
                         "'width:640px;height:360px;max-width:none;border:0;padding:0;flex-shrink:0';"
                         "document.querySelector('[data-timeline-zoom=fit]')?.click()")

        open_project(projects["Synthetic photo LUT photos-different"])
        photo_clips = cdp.evaluate("[...document.querySelectorAll('.studio-clip')].map(c=>c.dataset.studioId)")
        for point in (2.25, 2.5, 2.75):
            seek(cdp, point)
            time.sleep(0.8)
            before, state = capture(cdp)
            ref, index = reference(args.ffmpeg, fixture / "photos-different/export.mp4", state["time"])
            alpha = (index / 30) - 2
            cdp.evaluate("(()=>{const m=document.getElementById('studio-preview-image');m.style.opacity=" +
                         json.dumps(str(alpha)) + ";m.dispatchEvent(new Event('load'))})()")
            time.sleep(0.1)
            aligned, aligned_state = capture(cdp)
            reconstructed = image_bytes(cdp.evaluate("(async()=>{const ids=" + json.dumps(photo_clips) +
                ";const images=await Promise.all(ids.map(async id=>{const i=new Image();"
                "i.src=URL.createObjectURL(await (await fetch('/api/studio/'+id+'/preview-frame?t_s=0&detail=0')).blob());"
                "await i.decode();return i}));"
                "const c=document.createElement('canvas');c.width=640;c.height=360;const x=c.getContext('2d');"
                "x.fillStyle='#000';x.fillRect(0,0,640,360);x.imageSmoothingEnabled=true;"
                "x.imageSmoothingQuality='high';for(let n=0;n<images.length;n++){const i=images[n];"
                "x.globalAlpha=n===0?1:" + json.dumps(alpha) + ";const r=Math.min(640/i.width,360/i.height);"
                "const w=Math.min(640,Math.round(i.width*r)),h=Math.min(360,Math.round(i.height*r));"
                "x.drawImage(i,Math.floor((640-w)/2),Math.floor((360-h)/2),w,h)}"
                "window.photoParityControlImages=images;return c.toDataURL().split(',')[1]})()", await_promise=True))
            css_alpha = image_bytes(cdp.evaluate("(()=>{const c=document.createElement('canvas');"
                "c.width=640;c.height=360;const x=c.getContext('2d');x.fillStyle='#000';x.fillRect(0,0,640,360);"
                "x.imageSmoothingEnabled=true;x.imageSmoothingQuality='high';"
                "const alpha=Number(document.getElementById('studio-preview-image').style.opacity);"
                "window.photoParityControlImages.forEach((i,n)=>{x.globalAlpha=n===0?1:alpha;"
                "const r=Math.min(640/i.width,360/i.height),w=Math.round(i.width*r),h=Math.round(i.height*r);"
                "x.drawImage(i,Math.floor((640-w)/2),Math.floor((360-h)/2),w,h)});"
                "return c.toDataURL().split(',')[1]})()"))
            original_aspect = image_bytes(cdp.evaluate("(()=>{const c=document.createElement('canvas');"
                "c.width=640;c.height=360;const x=c.getContext('2d');x.fillStyle='#000';x.fillRect(0,0,640,360);"
                "x.imageSmoothingEnabled=true;x.imageSmoothingQuality='high';"
                "window.photoParityControlImages.forEach((i,n)=>{x.globalAlpha=n===0?1:" + json.dumps(alpha) +
                ";x.drawImage(i,0,0,640,360);URL.revokeObjectURL(i.src)});"
                "delete window.photoParityControlImages;return c.toDataURL().split(',')[1]})()"))
            # Fetch/decode controls can outlast a pending application paint.
            # Reassert the controlled alpha and wait two paints before comparing
            # decoded inputs, retaining both captures rather than hiding a race.
            cdp.evaluate("(async()=>{const m=document.getElementById('studio-preview-image');"
                "m.style.opacity=" + json.dumps(str(alpha)) + ";m.dispatchEvent(new Event('load'));"
                "await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))})()", await_promise=True)
            settled, settled_state = capture(cdp)
            report["controls"].append({"name": "photos-exact-alpha", "state": state,
                "export_frame": index, "controlled_alpha": alpha,
                "before": compare(before, ref), "aligned": compare(aligned, ref),
                "aligned_state": aligned_state, "settled_state": settled_state,
                "settled_versus_export": compare(settled, ref),
                "reconstructed_versus_settled": compare(reconstructed, settled),
                "css_alpha_reconstructed_versus_settled": compare(css_alpha, settled),
                "css_alpha_reconstructed_versus_export": compare(css_alpha, ref),
                "reconstructed_versus_preview": compare(reconstructed, aligned),
                "reconstructed_versus_export": compare(reconstructed, ref),
                "original_aspect_versus_export": compare(original_aspect, ref)})
            aligned.save(out / f"photos-aligned-{index}.png")
        open_project(projects["Synthetic photo LUT photo-video"])
        look = cdp.evaluate("JSON.parse(document.querySelectorAll('.studio-clip')[1].dataset.colorLook)")
        pid = expect_ok(fetch_json(cdp, "/api/studio/projects", method="POST",
                                   json_body={"title": "Synthetic standalone video attribution"}), "project")["id"]
        open_project(pid)
        expect_ok(fetch_json(cdp, f"/media/{video_id}/studio/add", method="POST", form_body={"return_to": "studio"}), "add")
        open_project(pid)
        clip = cdp.evaluate("document.querySelector('.studio-clip').dataset.studioId")
        patch(cdp, clip, "color", look)
        open_project(pid)
        output = out / "video-export.mp4"
        export(cdp, pid, output)
        for label, playing in (("paused", False), ("playing", True), ("after-pause", False)):
            if label == "paused":
                seek(cdp, 1)
            else:
                cdp.evaluate("document.querySelector('[data-transport=toggle]').click()", user_gesture=True)
            time.sleep(0.6)
            preview, state = capture(cdp)
            ref, index = reference(args.ffmpeg, output, state["time"])
            preview.save(out / f"video-{label}-preview.png")
            ref.save(out / f"video-{label}-export.png")
            report["controls"].append({"name": "video-" + label, "playing": playing,
                "state": state, "export_frame": index, "comparison": compare(preview, ref)})
            if label == "paused":
                raw = image_bytes(cdp.evaluate("(()=>{const c=document.createElement('canvas');"
                    "c.width=640;c.height=360;const x=c.getContext('2d');"
                    "x.imageSmoothingQuality='high';x.drawImage(document.getElementById('studio-preview-video'),"
                    "0,0,640,360);return c.toDataURL().split(',')[1]})()"))
                raw.save(out / "video-browser-source.png")
                lut = ffmpeg_lut_chain(ColorLook(**look), data_dir=data, work_dir=out / "luts")
                stages = {}
                for name, chain in {
                    "source": "",
                    "lut-rgb": lut,
                    "lut-float-rgb": "format=gbrpf32le," + lut,
                    "lut-yuv": lut + "," + _segment_vf(1280, 720),
                    "lut-float-yuv": "format=gbrpf32le," + lut + "," + _segment_vf(1280, 720),
                }.items():
                    tail = "scale=640:360,format=rgb24"
                    vf = chain + "," + tail if chain else tail
                    result = subprocess.run([args.ffmpeg, "-v", "verbose", "-i",
                        str(fixture / "synthetic-library/swatches.mp4"), "-vf", vf,
                        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                        capture_output=True, check=True, timeout=60)
                    picture = Image.open(io.BytesIO(result.stdout)).convert("RGB")
                    picture.save(out / ("video-cpu-" + name + ".png"))
                    portable_chain = vf.replace(escape_ffmpeg_lut_path(data), "<fixture-data>")
                    stages[name] = {"chain": portable_chain,
                        "format_negotiation": [line for line in result.stderr.decode(errors="replace").splitlines()
                                               if "fmt:" in line],
                        "versus_browser_source": compare(picture, raw),
                        "versus_webgl": compare(picture, preview), "versus_export": compare(picture, ref)}
                report["video_stages"] = stages
    finally:
        app.stop()
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--fixture-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
