"""Controlled synthetic PNG zero-strength scaling/encoding attribution.

Analysis only: writes alternative intermediates, never changes the application
or its acceptance threshold. Reference must be an application-exported MP4.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

from orga_drone.export.studio_encoder import _materialize_photo_still, _segment_vf, _x264_color_args
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_preview_frame import JPEG_COLOR_CHAIN
from orga_drone.studio_preview_frame import PreviewFrameRequest, render_preview_frame
from orga_drone.studio_image import ImageAdjust
from orga_drone.studio_lut import ColorLook
from studio_color_probe import compare, image_bytes
from studio_photo_lut_probe import reference
from windows_e2e import AppProcess, navigate, sha256_file


def detail_control(args) -> None:
    """Reject swatch-only improvements that lose native neutral-photo detail.

    Analysis-only recreation of the existing blit at CSS 640x360 / DPR 3.
    This metric is not the strict interior-swatch color gate.
    """
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    data = out / "data"
    data.mkdir()
    source = out / "synthetic-detail.png"
    picture = Image.new("RGB", (1920, 1080))
    draw = ImageDraw.Draw(picture)
    for x in range(1920):
        draw.line((x, 0, x, 539), fill="white" if x % 4 < 2 else "black")
    for y in range(540, 1080):
        draw.line((0, y, 1919, y), fill="white" if y % 4 < 2 else "black")
    picture.save(source)
    original_hash = sha256_file(source)
    previous_path = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = str(Path(args.ffmpeg).resolve().parent) + os.pathsep + previous_path
        selected_ffmpeg = find_ffmpeg()
        if not selected_ffmpeg or not Path(selected_ffmpeg).samefile(args.ffmpeg):
            raise ValueError("Detail control must use the supplied FFmpeg executable")
        still = render_preview_frame(PreviewFrameRequest(
            source, "photo", 0, ImageAdjust(), ColorLook(),
        ), data_dir=data)
    finally:
        os.environ["PATH"] = previous_path
    report = {"synthetic_only": True, "analysis_only": True,
              "exe_sha256": sha256_file(args.exe),
              "css_size": [640, 360], "dpr": 3, "backing_size": [1920, 1080],
              "source_sha256": original_hash, "strict_color_gate": "not measured by this detail control"}
    report["ffmpeg_sha256"] = sha256_file(Path(args.ffmpeg))
    app = AppProcess(args.exe.resolve(), data)
    try:
        app.start()
        cdp = app.require_cdp()
        navigate(cdp, app.app_port, "/")
        rendered = {}
        for name, path in (("original", source), ("neutral_720_prototype", still)):
            mime = "png" if path.suffix == ".png" else "jpeg"
            url = f"data:image/{mime};base64," + base64.b64encode(path.read_bytes()).decode()
            encoded = cdp.evaluate("(async()=>{const i=new Image();i.src=" + json.dumps(url) +
                ";await i.decode();const c=document.createElement('canvas');c.width=1920;c.height=1080;"
                "const x=c.getContext('2d');x.setTransform(3,0,0,3,0,0);"
                "x.imageSmoothingEnabled=true;x.imageSmoothingQuality='high';x.fillStyle='#000';"
                "x.fillRect(0,0,640,360);const r=Math.min(640/i.width,360/i.height);"
                "const w=Math.round(i.width*r),h=Math.round(i.height*r);"
                "x.drawImage(i,Math.floor((640-w)/2),Math.floor((360-h)/2),w,h);"
                "return c.toDataURL().split(',')[1]})()", await_promise=True)
            rendered[name] = image_bytes(encoded)
            rendered[name].save(out / (name + ".png"))
        difference = ImageStat.Stat(ImageChops.difference(rendered["original"], rendered["neutral_720_prototype"]))
        report.update(full_frame_mean_rgb_error=sum(difference.mean) / 3,
            original_stddev=ImageStat.Stat(rendered["original"]).stddev,
            prototype_stddev=ImageStat.Stat(rendered["neutral_720_prototype"]).stddev,
            browser=cdp.call("Browser.getVersion"))
    finally:
        app.stop()
        report["sources_unchanged"] = sha256_file(source) == original_hash
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def run(args) -> None:
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    data = out / "data"
    data.mkdir()
    report = {"synthetic_only": True, "analysis_only": True,
              "exe_sha256": sha256_file(args.exe), "ffmpeg_sha256": sha256_file(Path(args.ffmpeg)),
              "source_sha256": sha256_file(args.source),
              "export_sha256": sha256_file(args.reference), "variants": {}}
    ref, _ = reference(args.ffmpeg, args.reference, 0.5)
    ref.save(out / "export.png")
    materialized = out / "export-materialized.jpg"
    _materialize_photo_still(args.source, materialized)
    report["materialized_export"] = compare(Image.open(materialized).convert("RGB"), ref)
    report["codec_controls"] = {}
    for crf in (0, 17):
        previous = materialized
        for stage in (1, 2):
            encoded = out / f"export-control-crf{crf}-stage{stage}.mp4"
            inputs = ["-loop", "1", "-framerate", "30"] if stage == 1 else []
            chain = _segment_vf(1280, 720) if stage == 1 else "fps=30,format=yuv420p"
            subprocess.run([args.ffmpeg, "-v", "error", *inputs, "-i", str(previous),
                            "-t", "1", "-vf", chain, "-c:v", "libx264", "-preset", "slow",
                            "-crf", str(crf), *_x264_color_args(), str(encoded)],
                           check=True, capture_output=True, timeout=60)
            decoded, _ = reference(args.ffmpeg, encoded, 0.5)
            decoded.save(encoded.with_suffix(".png"))
            report["codec_controls"][f"crf{crf}-stage{stage}"] = compare(decoded, ref)
            previous = encoded
    app = AppProcess(args.exe.resolve(), data)
    try:
        app.start()
        cdp = app.require_cdp()
        navigate(cdp, app.app_port, "/")
        report["browser"] = cdp.call("Browser.getVersion")
        for size in ("720:405", "720:406", "704:396", "640:360", "1280:720"):
            limited = (f"scale={size}:out_color_matrix=bt709:out_range=tv,format=yuv420p,"
                       "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv")
            variants = {
                "rgb-png": (f"scale={size},format=rgb24", ".png", []),
                "709-png": (limited + ",scale=in_color_matrix=bt709:in_range=tv,format=rgb24", ".png", []),
                "jpeg-q5": (limited + "," + JPEG_COLOR_CHAIN, ".jpg", ["-q:v", "5"]),
                "jpeg-q1": (limited + "," + JPEG_COLOR_CHAIN, ".jpg", ["-q:v", "1"]),
                "export-source-jpeg-q5": (limited + "," + JPEG_COLOR_CHAIN, ".jpg", ["-q:v", "5"]),
            }
            for name, (chain, suffix, options) in variants.items():
                key = size.replace(":", "x") + "-" + name
                # The known odd-height JPEG encoder crash is not useful evidence
                # to repeat; the lossless odd-height controls remain included.
                if size == "720:405" and suffix == ".jpg":
                    continue
                target = out / (key + suffix)
                source = materialized if name.startswith("export-source") else args.source
                subprocess.run([args.ffmpeg, "-v", "error", "-i", str(source),
                                "-vf", chain, "-frames:v", "1", *options, str(target)],
                               check=True, capture_output=True, timeout=60)
                if suffix == ".png":
                    # Isolate decoded RGB values from FFmpeg PNG transfer tags.
                    # Browser/Pillow must receive the same untagged RGB control.
                    with Image.open(target) as picture:
                        pixels = picture.convert("RGB")
                    pixels.save(target)
                mime = "image/png" if suffix == ".png" else "image/jpeg"
                url = "data:" + mime + ";base64," + base64.b64encode(target.read_bytes()).decode()
                encoded = cdp.evaluate("(async()=>{const i=new Image();i.src=" + json.dumps(url) +
                    ";await i.decode();const c=document.createElement('canvas');c.width=640;c.height=360;"
                    "const x=c.getContext('2d');x.fillStyle='#000';x.fillRect(0,0,640,360);"
                    "x.imageSmoothingEnabled=true;x.imageSmoothingQuality='high';"
                    "const r=Math.min(640/i.naturalWidth,360/i.naturalHeight);"
                    "x.drawImage(i,(640-i.naturalWidth*r)/2,(360-i.naturalHeight*r)/2,"
                    "i.naturalWidth*r,i.naturalHeight*r);return c.toDataURL().split(',')[1]})()",
                    await_promise=True)
                browser = image_bytes(encoded)
                browser.save(out / (key + "-browser.png"))
                report["variants"][key] = {
                    "chain": chain, "browser_export": compare(browser, ref),
                    "pillow_export": compare(Image.open(target).convert("RGB"), ref),
                    "browser_pillow": compare(browser, Image.open(target).convert("RGB")),
                }
    finally:
        app.stop()
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--source", type=Path, help="Synthetic swatches PNG only")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--detail-control", action="store_true", help="Generate a synthetic native-detail control")
    args = parser.parse_args()
    if args.detail_control:
        detail_control(args)
    else:
        if args.source is None or args.reference is None:
            parser.error("--source and --reference are required for color attribution")
        run(args)
