"""Issue #487/#489 collage export benchmark with phase timing (synthetic only)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from PIL import __version__ as pillow_version

try:
    import psutil
except ImportError:
    psutil = None

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path)
parser.add_argument("--seconds-cap", type=int, default=900)
parser.add_argument("--disk-gib", type=float, default=4)
parser.add_argument("--scenarios", nargs="+", default=["pilot-1080", "pilot-2160", "A"])
args = parser.parse_args()
root = args.output.resolve()
root.mkdir(parents=True, exist_ok=False)
os.environ["ORGA_DRONE_DATA_DIR"] = str(root / "app")
os.environ["TEMP"] = os.environ["TMP"] = str(root / "scratch")
Path(os.environ["TEMP"]).mkdir()
tempfile.tempdir = os.environ["TEMP"]

from orga_drone.db import Database
from orga_drone.ffmpeg_bin import find_ffmpeg, subprocess_no_window_kwargs
from orga_drone.studio_collage import assign_leaf_media, iter_leaves, preset_spec
from orga_drone.studio_export import run_studio_export
import orga_drone.studio_collage_export as collage
import orga_drone.studio_collage_still as still
from orga_drone.export.studio_encoder import ExportCancelled, StudioExportError

ffmpeg = find_ffmpeg()
assert ffmpeg
gib = 1024 ** 3
reserve = 10 * gib
limit = args.disk_gib * gib
if shutil.disk_usage(root).free < reserve + limit + gib:
    raise SystemExit("Insufficient initial disk headroom")
process = psutil.Process() if psutil else None
scratch = root / "scratch"
app_temp = root / "app" / "tmp"
dest_dir = root / "outputs"
dest_dir.mkdir()
real_encode = collage._run_ffmpeg
real_save = collage._canvas_to_rgb_jpeg
real_prefetch = still.prefetch_export_video_sequence


def ff(*cmd, timeout=180):
    return subprocess.run(
        [ffmpeg, *cmd],
        check=True,
        capture_output=True,
        timeout=timeout,
        **subprocess_no_window_kwargs(),
    )


def emit(record):
    line = json.dumps(record)
    print(line, flush=True)
    with (root / "results.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def files_under(directory):
    for current, _, names in os.walk(directory):
        for name in names:
            path = Path(current) / name
            try:
                yield path, path.stat().st_size
            except FileNotFoundError:
                continue


def make_sources(height):
    folder = root / f"sources-{height}"
    folder.mkdir()
    width = height * 16 // 9
    sources = []
    for index in range(2):
        base = folder / f"seed-{index}.mp4"
        source = folder / f"video-{index}.mp4"
        filters = f"noise=alls=12:allf=u:all_seed={41 + index}"
        if index == 1:
            filters = "hflip,hue=h=75," + filters
        ff(
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x{height}:rate=30:duration=4",
            "-vf",
            filters,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-g",
            "30",
            "-keyint_min",
            "30",
            "-sc_threshold",
            "0",
            "-threads",
            "4",
            "-pix_fmt",
            "yuv420p",
            str(base),
        )
        ff("-y", "-v", "error", "-stream_loop", "-1", "-i", str(base), "-t", "121", "-c", "copy", str(source))
        base.unlink()
        sources.append(source)
    return folder, sources


def run(label, height, duration, folder, sources, fault=None):
    db = Database(root / f"{label}.sqlite3")
    project = db.ensure_default_studio_project()
    spec = preset_spec("1+1")
    for leaf, source in zip(iter_leaves(spec["root"]), sources, strict=True):
        spec = assign_leaf_media(
            spec,
            leaf["id"],
            {"source": "external", "kind": "video", "path": str(source)},
        )
    db.add_studio_collage(project.id, collage_spec=spec, collage_duration_s=duration)
    anchor = folder / "anchor.mp4"
    if not anchor.exists():
        ff("-y", "-v", "error", "-i", str(sources[0]), "-t", "1", "-c", "copy", str(anchor))
    root_id = db.add_root(folder, label="Synthetic")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "kind": "video",
            "filename": anchor.name,
            "path": str(anchor),
            "size_bytes": anchor.stat().st_size,
            "duration_s": 1.0,
            "width": height * 16 // 9,
            "height": height,
            "has_srt": 0,
            "has_lrf": 0,
        }
    )
    db.add_studio_item(
        str(anchor),
        identity_key=f"benchmark-{height}",
        filename=anchor.name,
        recorded_at=None,
        kind="video",
        project_id=project.id,
        source_media_id=media_id,
    )
    requested = dest_dir / f"{label}.mp4"
    sentinel = b"synthetic pre-existing output guard"
    requested.write_bytes(sentinel)
    cancel = threading.Event()
    stop = threading.Event()
    peak = {
        "temp_bytes": 0,
        "temp_files": 0,
        "tree_rss_bytes": 0,
        "python_rss_bytes": 0,
    }
    phase = {
        "prefetch_s": 0.0,
        "jpeg_write_s": 0.0,
        "encoding_s": None,
        "compose_loop_s": 0.0,
    }
    reason = []
    t0 = time.perf_counter()

    def abort(message):
        if not cancel.is_set():
            reason.append(message)
            cancel.set()

    def sample():
        paths = list(files_under(scratch)) + list(files_under(app_temp))
        paths += [(p, n) for p, n in files_under(dest_dir) if p.name.endswith(".partial")]
        peak["temp_bytes"] = max(peak["temp_bytes"], sum(n for _, n in paths))
        peak["temp_files"] = max(peak["temp_files"], len(paths))
        if process:
            rss = process.memory_info().rss
            total = rss
            for child in process.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            peak["python_rss_bytes"] = max(peak["python_rss_bytes"], rss)
            peak["tree_rss_bytes"] = max(peak["tree_rss_bytes"], total)
        if peak["temp_bytes"] >= limit or shutil.disk_usage(root).free < reserve:
            abort("disk safety limit")
        if time.perf_counter() - t0 > args.seconds_cap:
            abort("elapsed time limit")
        return paths

    def watch():
        while not stop.wait(0.5):
            sample()

    composed = 0

    def save(canvas, dest_path):
        nonlocal composed
        t1 = time.perf_counter()
        real_save(canvas, dest_path)
        phase["jpeg_write_s"] += time.perf_counter() - t1
        composed += 1
        if fault == "cancel" and composed == 3:
            abort("injected cancel after three real frames")
        if fault == "failure" and composed == 3:
            raise StudioExportError("injected failure after three real frames")

    def encode(cmd, **kwargs):
        if phase["encoding_s"] is None:
            phase["encoding_s"] = time.perf_counter() - t0
        return real_encode(cmd, **kwargs)

    def prefetch(*a, **k):
        t1 = time.perf_counter()
        out = real_prefetch(*a, **k)
        phase["prefetch_s"] += time.perf_counter() - t1
        return out

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    collage._run_ffmpeg = encode
    collage._canvas_to_rgb_jpeg = save
    still.prefetch_export_video_sequence = prefetch
    collage.prefetch_export_video_sequence = prefetch
    result = None
    status = "PASS"
    failure = None
    try:
        result = run_studio_export(
            db,
            height=height,
            output_path=requested,
            project_id=project.id,
            cancel_event=cancel,
        )
    except ExportCancelled:
        status = "PASS" if fault == "cancel" else "ABORTED"
    except Exception as exc:  # noqa: BLE001
        failure = f"{type(exc).__name__}: {exc}"
        status = "PASS" if fault == "failure" and "injected failure" in failure else "FAIL"
    finally:
        elapsed = time.perf_counter() - t0
        stop.set()
        watcher.join()
        collage._run_ffmpeg = real_encode
        collage._canvas_to_rgb_jpeg = real_save
        still.prefetch_export_video_sequence = real_prefetch
        collage.prefetch_export_video_sequence = real_prefetch
    remaining = list(files_under(scratch)) + list(files_under(app_temp))
    protected = requested.read_bytes() == sentinel
    mp4_bytes = result.stat().st_size if result else None
    verified = False
    if result:
        ff("-v", "error", "-i", str(result), "-map", "0:v:0", "-f", "null", "-")
        verified = True
        result.unlink()
    partials = [p for p in dest_dir.iterdir() if p != requested]
    requested.unlink(missing_ok=True)
    if remaining or not protected or partials or (fault and result):
        status = "FAIL"
    record = dict(
        label=label,
        status=status,
        height=height,
        duration_s=duration,
        elapsed_s=elapsed,
        mp4_bytes=mp4_bytes,
        mp4_decoded=verified,
        composed=composed,
        cleanup_files=len(remaining),
        unexpected_outputs=len(partials),
        protected=protected,
        failure=failure,
        stopped=reason,
        rss_available=process is not None,
        **peak,
        **phase,
    )
    emit(record)
    return record


emit(
    dict(
        event="environment",
        python=os.sys.version,
        pillow=pillow_version,
        ffmpeg=ff("-version").stdout.decode().splitlines()[0],
        platform=os.sys.platform,
        cores=os.cpu_count(),
        physical_cores=psutil.cpu_count(logical=False) if psutil else None,
        ram_bytes=psutil.virtual_memory().total if psutil else None,
        free_bytes=shutil.disk_usage(root).free,
        disk_cap_bytes=limit,
        reserve_bytes=reserve,
        seconds_cap=args.seconds_cap,
        implementation="sequential-source-prefetch",
    )
)

wanted = set(args.scenarios)
# Always generate sources for requested heights.
heights = []
if any(s.startswith("pilot-1080") or s in {"A", "B"} for s in wanted):
    heights.append(1080)
if any(s.startswith("pilot-2160") or s in {"C", "D"} for s in wanted):
    heights.append(2160)

folders = {}
for height in heights:
    folders[height] = make_sources(height)

if "pilot-1080" in wanted and 1080 in folders:
    folder, sources = folders[1080]
    run("pilot-1080", 1080, 3, folder, sources)
    if "failure" in wanted:
        run("failure", 1080, 3, folder, sources, fault="failure")
    if "cancel" in wanted:
        run("cancel", 1080, 3, folder, sources, fault="cancel")
if "pilot-2160" in wanted and 2160 in folders:
    folder, sources = folders[2160]
    run("pilot-2160", 2160, 3, folder, sources)
if "A" in wanted and 1080 in folders:
    folder, sources = folders[1080]
    run("A", 1080, 30, folder, sources)
if "C" in wanted and 2160 in folders:
    folder, sources = folders[2160]
    run("C", 2160, 30, folder, sources)
for label in ("B", "D"):
    if label in wanted:
        emit(dict(label=label, status="NOT_RUN", reason="explicit budget skip in this harness run"))
