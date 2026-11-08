"""Reproducible synthetic precision experiment: latency, cache hits and memory.

Analysis only. Each worker has isolated output/cache state. Sources are generated
once and shared read-only by baseline/candidate runs. Requires psutil in the
analysis environment; this does not add an application dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(args) -> None:
    from PIL import Image, ImageDraw
    from studio_crossfade_lut_probe import write_cube

    root = args.fixtures.resolve()
    root.mkdir(parents=True, exist_ok=False)
    write_cube(root / "synthetic.cube", size=17, variant="red")
    for height in (1080, 2160):
        width = height * 16 // 9
        picture = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(picture)
        for x in range(width):
            draw.line((x, 0, x, height - 1), fill=(x % 256, (x * 3) % 256, (x * 7) % 256))
        for y in range(0, height, 16):
            draw.line((0, y, width - 1, y), fill=(200, 120, 70), width=2)
        picture.save(root / f"source-{height}.png")
        picture.save(root / f"source-{height}.jpg", quality=98, subsampling=0)
        subprocess.run([args.ffmpeg, "-v", "error", "-loop", "1", "-i",
            str(root / f"source-{height}.png"), "-t", "2", "-r", "30", "-vf",
            "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
            "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
            str(root / f"source-{height}.mp4")], check=True, capture_output=True, timeout=120)
    (root / "hashes.json").write_text(json.dumps(
        {p.name: digest(p) for p in root.iterdir() if p.is_file()}, indent=2), encoding="utf-8")


def worker(job: dict) -> dict:
    from orga_drone.config import Settings
    import orga_drone.config as config
    from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
    from orga_drone.export.studio_encoder import FfmpegStudioEncoder
    from orga_drone.studio_image import ImageAdjust
    from orga_drone.studio_lut import ColorLook, import_lut_from_path
    from orga_drone.studio_playback_proxy import PlaybackProxyRequest, render_playback_proxy
    from orga_drone.studio_preview_frame import PreviewFrameRequest, render_preview_frame

    source, out, cube = (Path(job[key]) for key in ("source", "output", "cube"))
    out.mkdir(parents=True, exist_ok=False)
    config.settings = Settings(data_dir=out / "data")
    asset = import_lut_from_path(config.settings.data_dir, cube)
    look = ColorLook(creative_lut=asset, creative_strength=100)
    operation = job["operation"]
    if operation == "still":
        req = PreviewFrameRequest(source, "photo", 0, ImageAdjust(), look)
        def call():
            return render_preview_frame(req, data_dir=config.settings.data_dir)
    elif operation == "proxy":
        proxy_req = PlaybackProxyRequest(source, source_end_s=2, look=look)
        def call():
            return render_playback_proxy(proxy_req, data_dir=config.settings.data_dir)
    else:
        cfg = StudioExportConfig(output_path=out / "export.mp4", width=job["height"] * 16 // 9,
            height=job["height"], quality="high",
            clips=(StudioExportClip(source, "video", 2, source_end_s=2, color_look=look),))
        def call():
            return FfmpegStudioEncoder().render(cfg)
    started = time.perf_counter()
    output = call()
    elapsed = time.perf_counter() - started
    hit_s = None
    same = None
    if operation != "export":
        before = output.stat().st_mtime_ns
        started = time.perf_counter()
        cached = call()
        hit_s = time.perf_counter() - started
        same = cached == output and cached.stat().st_mtime_ns == before
    return {"elapsed_s": elapsed, "cache_hit_s": hit_s, "cache_hit_reused": same,
            "output_bytes": output.stat().st_size, "output_sha256": digest(output)}


def run(args) -> None:
    import psutil

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    fixtures = args.fixtures.resolve()
    hashes = json.loads((fixtures / "hashes.json").read_text(encoding="utf-8"))
    assert hashes == {name: digest(fixtures / name) for name in hashes}
    env = os.environ.copy()
    env["PYTHONPATH"] = str(args.source_root.resolve())
    env["PATH"] = str(Path(args.ffmpeg).resolve().parent) + os.pathsep + env.get("PATH", "")
    report = {"synthetic_only": True, "label": args.label, "repetitions": args.repeats,
        "duration_s": 2, "export_quality": "high", "ffmpeg_sha256": digest(Path(args.ffmpeg)),
        "memory_metric": "sampled summed process-tree RSS; maximum child peak working set; 10ms polling",
        "rows": [], "status": "INCOMPLETE"}
    try:
        for repeat in range(args.repeats):
            for height in (1080, 2160):
                for operation, suffix in (("still", "jpg"), ("still", "png"), ("proxy", "mp4"), ("export", "mp4")):
                    name = f"{repeat}-{height}-{operation}-{suffix}"
                    job = {"operation": operation, "height": height,
                        "source": str(fixtures / f"source-{height}.{suffix}"),
                        "cube": str(fixtures / "synthetic.cube"), "output": str(out / name)}
                    job_file = out / (name + ".json")
                    job_file.write_text(json.dumps(job), encoding="utf-8")
                    with (out / (name + ".log")).open("wb") as log:
                        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker",
                            str(job_file)], env=env, stdout=subprocess.PIPE, stderr=log)
                        peak_tree = peak_child = 0
                        while process.poll() is None:
                            try:
                                parent = psutil.Process(process.pid)
                                total = 0
                                for member in [parent, *parent.children(recursive=True)]:
                                    try:
                                        info = member.memory_info()
                                        total += info.rss
                                        if member.pid != parent.pid:
                                            peak_child = max(peak_child, getattr(info, "peak_wset", info.rss))
                                    except psutil.Error:
                                        pass
                                peak_tree = max(peak_tree, total)
                            except psutil.Error:
                                pass
                            time.sleep(0.01)
                        stdout, _ = process.communicate()
                    if process.returncode:
                        raise RuntimeError(f"Benchmark worker failed: {name}; inspect its log")
                    result = json.loads(stdout)
                    result.update(operation=operation, source_format=suffix, height=height, repeat=repeat,
                        sampled_peak_tree_rss_bytes=peak_tree, max_child_peak_working_set_bytes=peak_child)
                    report["rows"].append(result)
                    print(name, round(result["elapsed_s"], 3), round(peak_tree / 2**20, 1), flush=True)
                    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["status"] = "COMPLETE"
    finally:
        report["sources_unchanged"] = hashes == {name: digest(fixtures / name) for name in hashes}
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.loads(args.worker.read_text(encoding="utf-8")))))
    elif args.prepare:
        prepare(args)
    else:
        run(args)
