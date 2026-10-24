"""Discovery harness for GitHub issue #99.

Not a product feature. Builds synthetic fixtures, runs the shipping
``scan_root`` / ``scan_all_roots`` / browse / thumbnail paths, and writes
JSON measurements. It does not scan the user's library folders.

Fixture files are tiny JPEGs and short generated MP4 stubs unless a section
says otherwise. Those timings are not a 20k drone-archive result.

Usage (from the repository root):

    python docs/discovery/issue-99-cross-drive-benchmark.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_ROOT = REPO_ROOT / ".issue99-bench"
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["ORGA_DRONE_DATA_DIR"] = str(BENCH_ROOT / "appdata")
os.environ["ORGA_DRONE_GEOCODE"] = "offline"

from orga_drone.config import settings  # noqa: E402
from orga_drone.db import Database, make_identity_key  # noqa: E402
from orga_drone.ffmpeg_bin import find_ffmpeg, find_ffprobe  # noqa: E402
from orga_drone.parse import (  # noqa: E402
    parse_media_file,
    probe_video_streams,
    probe_video_with_ffprobe,
    scan_video_header,
)
from orga_drone.scan import iter_media_files, scan_all_roots, scan_root  # noqa: E402
from orga_drone.scan.progress import ScanProgress  # noqa: E402
from orga_drone.thumbs import ensure_thumbnail  # noqa: E402


def scrub(value: Any) -> Any:
    """Drop home-directory paths before anything is written to disk."""
    if isinstance(value, str):
        home = str(Path.home())
        text = value.replace(home, "%USERPROFILE%")
        text = text.replace(str(REPO_ROOT), "%REPO%")
        return text
    if isinstance(value, dict):
        return {str(k): scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def round_s(seconds: float) -> float:
    return round(seconds, 3)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def run_json_probe(argv_path: str, timeout_s: float) -> dict[str, Any]:
    code = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "p = Path(sys.argv[1])\n"
        "t0 = time.perf_counter()\n"
        "try:\n"
        "    exists = p.exists()\n"
        "    err = None\n"
        "except Exception as exc:\n"
        "    exists = None\n"
        "    err = f'{type(exc).__name__}: {exc}'[:300]\n"
        "print(json.dumps({'seconds': round(time.perf_counter()-t0, 3),"
        " 'exists': exists, 'error': err}))\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, argv_path],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "seconds": timeout_s,
            "exists": None,
            "error": "timeout",
            "timed_out": True,
            "stdout": scrub((exc.stdout or b"").decode("utf-8", "replace")[:200])
            if isinstance(exc.stdout, bytes)
            else scrub(str(exc.stdout or "")[:200]),
        }
    payload: dict[str, Any]
    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        payload = {"seconds": None, "exists": None, "error": "unparsed"}
    payload["timed_out"] = False
    payload["returncode"] = proc.returncode
    if proc.stderr.strip():
        payload["stderr"] = scrub(proc.stderr.strip()[:300])
    return payload


def working_set() -> dict[str, int] | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    ok = psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(),
        ctypes.byref(counters),
        counters.cb,
    )
    if not ok:
        return None
    return {
        "working_set_bytes": int(counters.WorkingSetSize),
        "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
    }


def log(message: str) -> None:
    print(message, flush=True)


def powershell_json(script: str) -> Any:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        return {"error": scrub(proc.stderr.strip()[:500]), "returncode": proc.returncode}
    raw = proc.stdout.strip()
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "unparsed", "stdout": scrub(raw[:500])}


def hardware() -> dict[str, Any]:
    logical = powershell_json(
        "Get-CimInstance Win32_LogicalDisk | "
        "Select-Object DeviceID, DriveType, FileSystem, Size, FreeSpace | "
        "ConvertTo-Json -Compress"
    )
    cpu = powershell_json(
        "Get-CimInstance Win32_Processor | "
        "Select-Object Name, NumberOfCores, NumberOfLogicalProcessors | "
        "ConvertTo-Json -Compress"
    )
    memory = powershell_json(
        "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"
    )
    disks = powershell_json(
        "Get-PhysicalDisk | "
        "Select-Object FriendlyName, MediaType, BusType, Size, HealthStatus | "
        "ConvertTo-Json -Compress"
    )
    partitions = powershell_json(
        "Get-Partition -ErrorAction SilentlyContinue | "
        "Where-Object DriveLetter | "
        "ForEach-Object { "
        "  $disk = Get-Disk -Number $_.DiskNumber; "
        "  $phys = Get-PhysicalDisk -DeviceNumber $_.DiskNumber "
        "    -ErrorAction SilentlyContinue; "
        "  [PSCustomObject]@{ "
        "    DriveLetter = [string]$_.DriveLetter; "
        "    BusType = [string]$disk.BusType; "
        "    MediaType = [string]$phys.MediaType; "
        "    FriendlyName = [string]$phys.FriendlyName "
        "  } "
        "} | ConvertTo-Json -Compress"
    )
    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "cpu": cpu,
        "total_physical_memory_bytes": memory,
        "logical_disks": logical,
        "physical_disks": disks,
        "partition_media": partitions,
        "process_memory_at_start": working_set(),
    }


def installed_catalog() -> dict[str, Any]:
    """Read-only counts from the app database. Paths are not recorded."""
    db_path = Path(os.environ.get("APPDATA", "")) / "orga-drone" / "orga-drone.sqlite3"
    if not db_path.is_file():
        return {"present": False}
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        return {"present": True, "error": scrub(str(exc))}
    try:
        def one(sql: str) -> int:
            row = conn.execute(sql).fetchone()
            return int(row[0] if row else 0)

        roots = [row[0] for row in conn.execute("SELECT path FROM library_roots")]
        existing = 0
        missing = 0
        for path in roots:
            probe = run_json_probe(str(path), 8)
            if probe.get("exists") is True:
                existing += 1
            else:
                missing += 1
        return {
            "present": True,
            "bytes": db_path.stat().st_size,
            "media": one("SELECT COUNT(*) FROM media"),
            "photos": one("SELECT COUNT(*) FROM media WHERE kind = 'photo'"),
            "videos": one("SELECT COUNT(*) FROM media WHERE kind = 'video'"),
            "roots": len(roots),
            "roots_existing": existing,
            "roots_missing": missing,
            "favorites": one("SELECT COUNT(*) FROM media_meta WHERE favorite = 1"),
            "studio_clips": one("SELECT COUNT(*) FROM studio_clips"),
            "note": "Counted only. This harness did not rescan those roots.",
        }
    except sqlite3.Error as exc:
        return {"present": True, "error": scrub(str(exc))}
    finally:
        conn.close()


def tiny_jpeg() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (8, 8), (20, 40, 60)).save(buf, format="JPEG", quality=40)
    return buf.getvalue()


def dji_name(index: int, kind: str) -> str:
    moment = datetime(2020, 1, 1) + timedelta(seconds=90 * index)
    ext = "JPG" if kind == "photo" else "MP4"
    return f"DJI_{moment:%Y%m%d%H%M%S}_{index % 10000:04d}_D.{ext}"


def write_tree(root: Path, start: int, count: int, payload: bytes, kind: str) -> float:
    started = time.perf_counter()
    current: Path | None = None
    for index in range(start, start + count):
        folder = root / f"batch_{(index // 100):04d}"
        if folder != current:
            folder.mkdir(parents=True, exist_ok=True)
            current = folder
        (folder / dji_name(index, kind)).write_bytes(payload)
    return time.perf_counter() - started


class PhaseTimer:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.events: list[dict[str, Any]] = []
        self._last: tuple[Any, ...] | None = None

    def __call__(self, progress: ScanProgress) -> None:
        key = (progress.root_id, progress.phase)
        if key == self._last:
            return
        self._last = key
        self.events.append(
            {
                "t_seconds": round_s(time.perf_counter() - self.started),
                "phase": progress.phase,
                "root_id": progress.root_id,
                "discovered": progress.discovered,
                "processed": progress.processed,
                "memory": working_set(),
            }
        )


def phase_durations(
    events: list[dict[str, Any]], end_seconds: float
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        end = events[index + 1]["t_seconds"] if index + 1 < len(events) else end_seconds
        duration = round(end - event["t_seconds"], 3)
        rows.append(
            {
                "phase": event["phase"],
                "root_id": event["root_id"],
                "start_seconds": event["t_seconds"],
                "duration_seconds": duration,
                "discovered": event["discovered"],
                "memory": event["memory"],
            }
        )
    return rows


def sql_count(db: Database, sql: str, params: tuple[Any, ...] = ()) -> int:
    with db.connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row[0] if row else 0)


def root_snapshot(db: Database, root_id: int) -> dict[str, int]:
    return {
        "media": sql_count(db, "SELECT COUNT(*) FROM media WHERE root_id = ?", (root_id,)),
        "assets": sql_count(db, "SELECT COUNT(*) FROM assets WHERE root_id = ?", (root_id,)),
    }


def pick_second_fixed_drive(logical: Any) -> str | None:
    """Choose a fixed disk other than C: with at least 5 GiB free."""
    rows = logical if isinstance(logical, list) else [logical] if isinstance(logical, dict) else []
    best: tuple[int, str] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if int(row.get("DriveType") or 0) != 3:
            continue
        device = str(row.get("DeviceID") or "")
        if device.upper().startswith("C:"):
            continue
        free = int(row.get("FreeSpace") or 0)
        if free < 5 * 1024**3:
            continue
        if best is None or free > best[0]:
            best = (free, device)
    return None if best is None else best[1]


def removable_drives(logical: Any) -> list[str]:
    rows = logical if isinstance(logical, list) else [logical] if isinstance(logical, dict) else []
    found: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if int(row.get("DriveType") or 0) != 2:
            continue
        device = str(row.get("DeviceID") or "")
        free = int(row.get("FreeSpace") or 0)
        if device and free > 100 * 1024**2:
            found.append(device)
    return found


def section_unavailable_roots(work: Path) -> dict[str, Any]:
    """Small local stand-in for a root that disappears or comes back empty."""
    blob = tiny_jpeg()
    base = work / "unavailable"
    keep = base / "keep"
    emptied = base / "emptied"
    direct = base / "direct"
    mid = base / "mid"
    for folder in (keep, emptied, direct, mid):
        folder.mkdir(parents=True, exist_ok=True)
    write_tree(keep, 0, 30, blob, "photo")
    write_tree(emptied, 100, 30, blob, "photo")
    write_tree(direct, 200, 20, blob, "photo")
    write_tree(mid, 300, 40, blob, "photo")

    db = Database(work / "unavailable.sqlite3")
    keep_id = db.add_root(keep, "keep")
    empty_id = db.add_root(emptied, "emptied")
    direct_id = db.add_root(direct, "direct")
    mid_id = db.add_root(mid, "mid")
    first = scan_all_roots(db)
    keep_item = db.list_media(limit=1)[0]
    # list_media is global; pick explicit rows by path prefix via SQL.
    with db.connect() as conn:
        keep_row = conn.execute(
            "SELECT path, filename, size_bytes, recorded_at FROM media WHERE root_id = ?",
            (keep_id,),
        ).fetchone()
        empty_row = conn.execute(
            "SELECT path, filename, size_bytes, recorded_at FROM media WHERE root_id = ?",
            (empty_id,),
        ).fetchone()
    assert keep_row is not None and empty_row is not None
    db.upsert_media_meta(
        str(keep_row["path"]),
        favorite=True,
        stars=5,
        tags=["bench-keep"],
        notes="keep",
        identity_key=make_identity_key(
            str(keep_row["filename"]),
            int(keep_row["size_bytes"]),
            keep_row["recorded_at"],
        ),
    )
    db.add_studio_item(
        str(keep_row["path"]),
        identity_key=make_identity_key(
            str(keep_row["filename"]),
            int(keep_row["size_bytes"]),
            keep_row["recorded_at"],
        ),
        filename=str(keep_row["filename"]),
        recorded_at=keep_row["recorded_at"],
        kind="photo",
    )
    db.upsert_media_meta(
        str(empty_row["path"]),
        favorite=True,
        stars=4,
        tags=["bench-empty"],
        notes="empty",
        identity_key=make_identity_key(
            str(empty_row["filename"]),
            int(empty_row["size_bytes"]),
            empty_row["recorded_at"],
        ),
    )
    db.add_studio_item(
        str(empty_row["path"]),
        identity_key=make_identity_key(
            str(empty_row["filename"]),
            int(empty_row["size_bytes"]),
            empty_row["recorded_at"],
        ),
        filename=str(empty_row["filename"]),
        recorded_at=empty_row["recorded_at"],
        kind="photo",
    )
    before = {
        "keep": root_snapshot(db, keep_id),
        "emptied": root_snapshot(db, empty_id),
        "direct": root_snapshot(db, direct_id),
        "favorites": sql_count(db, "SELECT COUNT(*) FROM media_meta WHERE favorite = 1"),
        "studio_clips": sql_count(db, "SELECT COUNT(*) FROM studio_clips"),
    }
    shutil.rmtree(keep)
    for child in emptied.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    missing_scan = scan_all_roots(db)
    after_missing = {
        "keep": root_snapshot(db, keep_id),
        "emptied": root_snapshot(db, empty_id),
        "direct": root_snapshot(db, direct_id),
        "favorites": sql_count(db, "SELECT COUNT(*) FROM media_meta WHERE favorite = 1"),
        "studio_clips": sql_count(db, "SELECT COUNT(*) FROM studio_clips"),
        "studio_available_flags": [
            item.available for item in db.list_studio_items()
        ],
        "scan_all_errors": [
            {"root_id": row.get("root_id"), "error": row.get("error")}
            for row in missing_scan
            if row.get("error")
        ],
    }
    restored_name = str(empty_row["filename"])
    (emptied / "batch_0001").mkdir(parents=True, exist_ok=True)
    # The original file lived in batch_{index//100}. Recreate every emptied file.
    write_tree(emptied, 100, 30, blob, "photo")
    restored = scan_all_roots(db)
    with db.connect() as conn:
        relinked = conn.execute(
            """SELECT mm.favorite, mm.notes
               FROM media_meta mm
               JOIN media m ON m.path = mm.media_path
               WHERE m.root_id = ? AND mm.favorite = 1""",
            (empty_id,),
        ).fetchone()
    after_restore = {
        "emptied": root_snapshot(db, empty_id),
        "favorite_relinked": relinked is not None,
        "studio_available_flags": [item.available for item in db.list_studio_items()],
        "restored_filename_present": (emptied / "batch_0001" / restored_name).exists()
        or any(emptied.rglob(restored_name)),
        "scan_errors": [row.get("error") for row in restored if row.get("error")],
    }

    shutil.rmtree(direct)
    direct_timer = PhaseTimer()
    direct_started = time.perf_counter()
    direct_error = None
    try:
        direct_counts = scan_root(db, direct_id, direct, on_progress=direct_timer)
    except Exception as exc:  # noqa: BLE001 — record the failure mode
        direct_counts = None
        direct_error = f"{type(exc).__name__}: {exc}"
    after_direct = {
        "seconds": round_s(time.perf_counter() - direct_started),
        "counts": direct_counts,
        "error": direct_error,
        "snapshot": root_snapshot(db, direct_id),
    }

    deleted_after = {"processed": 0}

    def drop_rest(progress: ScanProgress) -> None:
        if progress.phase == "indexing" and progress.processed == 10 and deleted_after["processed"] == 0:
            deleted_after["processed"] = 10
            for path in list(mid.rglob("*")):
                if path.is_file():
                    path.unlink()

    mid_started = time.perf_counter()
    mid_error = None
    try:
        mid_counts = scan_root(db, mid_id, mid, on_progress=drop_rest)
    except Exception as exc:  # noqa: BLE001
        mid_counts = None
        mid_error = f"{type(exc).__name__}: {exc}"
    files_left = sum(1 for path in mid.rglob("*") if path.is_file())
    return {
        "method": (
            "Local directories only. 'Missing' means the directory was removed. "
            "'Emptied' means the same path still exists with no media files. "
            "This is not a NAS unplug."
        ),
        "first_scan_result_count": len(first),
        "sample_list_media_id": keep_item.id,
        "before": before,
        "after_keep_removed_and_emptied_rescanned_via_scan_all_roots": after_missing,
        "after_emptied_files_restored": after_restore,
        "scan_root_after_directory_removed": after_direct,
        "mid_scan_files_deleted_at_processed_10": {
            "seconds": round_s(time.perf_counter() - mid_started),
            "counts": mid_counts,
            "error": mid_error,
            "files_left_on_disk": files_left,
            "snapshot": root_snapshot(db, mid_id),
        },
    }


def make_mp4(dest: Path, ffmpeg: str) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=160x90:d=0.5",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-frames:v",
        "8",
        str(dest),
    ]
    started = time.perf_counter()
    proc = subprocess.run(cmd, check=False, capture_output=True, timeout=60)
    return {
        "seconds": round_s(time.perf_counter() - started),
        "returncode": proc.returncode,
        "bytes": dest.stat().st_size if dest.exists() else 0,
        "stderr": scrub(proc.stderr.decode("utf-8", "replace")[:300]),
    }


def section_videos(work: Path, count: int) -> dict[str, Any]:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    root = work / "videos"
    root.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "ffmpeg": ffmpeg is not None,
        "ffprobe": ffprobe is not None,
        "count": count,
        "composition": "160x90 black H.264 about 0.5s, copied N times. Not drone footage.",
    }
    if not ffmpeg:
        result["error"] = "ffmpeg not found; video sample skipped"
        return result
    seed = root / "seed.mp4"
    generated = make_mp4(seed, ffmpeg)
    result["seed"] = generated
    if generated["returncode"] != 0 or not seed.exists():
        result["error"] = "ffmpeg could not write a stub mp4"
        return result
    payload = seed.read_bytes()
    seed.unlink()
    result["fixture_write_seconds"] = round_s(write_tree(root, 0, count, payload, "video"))
    sample = next(root.rglob("*.MP4"))
    per_file: dict[str, Any] = {"sample_bytes": sample.stat().st_size}
    for label, func in (
        ("scan_video_header", lambda path: scan_video_header(path)),
        ("probe_video_streams", lambda path: probe_video_streams(path)),
        ("probe_video_with_ffprobe", lambda path: probe_video_with_ffprobe(path)),
        ("parse_media_file", lambda path: parse_media_file(path)),
    ):
        started = time.perf_counter()
        repeats = 5
        for _ in range(repeats):
            func(sample)
        elapsed = time.perf_counter() - started
        per_file[label] = {
            "repeats": repeats,
            "seconds": round_s(elapsed),
            "seconds_per_call": round(elapsed / repeats, 4),
        }
    db = Database(work / "videos.sqlite3")
    root_id = db.add_root(root, "videos")
    timer = PhaseTimer()
    mem_before = working_set()
    counts = scan_root(db, root_id, root, on_progress=timer)
    elapsed = time.perf_counter() - timer.started
    result["scan"] = {
        "seconds": round_s(elapsed),
        "seconds_per_file": round(elapsed / count, 4) if count else None,
        "counts": counts,
        "phases": phase_durations(timer.events, round_s(elapsed)),
        "memory_before": mem_before,
        "memory_after": working_set(),
        "sqlite_bytes": (work / "videos.sqlite3").stat().st_size,
    }
    result["per_file_microbench"] = per_file
    result["projection_note"] = (
        "Per-file times are measurements. They are not multiplied into a 20k video total."
    )
    return result


def section_large_photos(work: Path) -> dict[str, Any]:
    from PIL import Image

    folder = work / "large-photos"
    folder.mkdir(parents=True, exist_ok=True)
    specs = [(1920, 1080, 6), (3840, 2160, 3)]
    files: list[dict[str, Any]] = []
    for width, height, count in specs:
        for index in range(count):
            path = folder / f"still_{width}x{height}_{index}.jpg"
            started = time.perf_counter()
            Image.new("RGB", (width, height), (30, 80, 120)).save(path, format="JPEG", quality=85)
            files.append(
                {
                    "width": width,
                    "height": height,
                    "bytes": path.stat().st_size,
                    "pillow_save_seconds": round_s(time.perf_counter() - started),
                    "path": path,
                }
            )
    parse_started = time.perf_counter()
    for item in files:
        parse_media_file(item["path"])
    parse_seconds = time.perf_counter() - parse_started
    thumb_started = time.perf_counter()
    for index, item in enumerate(files, start=1):
        ensure_thumbnail(
            media_id=10_000 + index,
            path=item["path"],
            kind="photo",
            filename=item["path"].name,
        )
    thumb_seconds = time.perf_counter() - thumb_started
    public_files = []
    for item in files:
        public_files.append(
            {
                "width": item["width"],
                "height": item["height"],
                "bytes": item["bytes"],
                "pillow_save_seconds": item["pillow_save_seconds"],
            }
        )
    return {
        "composition": "Synthetic solid-color JPEGs, no EXIF GPS. Not drone photos.",
        "files": public_files,
        "parse_media_file_seconds": round_s(parse_seconds),
        "parse_seconds_per_file": round(parse_seconds / len(files), 4),
        "ensure_thumbnail_seconds": round_s(thumb_seconds),
        "thumbnail_seconds_per_file": round(thumb_seconds / len(files), 4),
    }


def section_geocode(work: Path) -> dict[str, Any]:
    from orga_drone.geocode import resolve

    db = Database(work / "geocode.sqlite3")
    started = time.perf_counter()
    try:
        first = resolve(db, 47.3769, 8.5417, mode="offline")
    except Exception as exc:  # noqa: BLE001
        return {"error": scrub(f"{type(exc).__name__}: {exc}")}
    cold = time.perf_counter() - started
    warm_started = time.perf_counter()
    second = resolve(db, 47.3769, 8.5417, mode="offline")
    warm = time.perf_counter() - warm_started
    return {
        "coordinate": "47.3769, 8.5417 (public sample, not from a library file)",
        "cold_seconds": round_s(cold),
        "cached_seconds": round_s(warm),
        "cold_resolved": first is not None,
        "cached_resolved": second is not None,
        "note": (
            "The 20k photo fixture has no GPS, so scan did not call this. "
            "Cold time includes the first offline geocoder load in this process."
        ),
    }


def time_call(func: Any, repeats: int = 3) -> dict[str, Any]:
    samples: list[float] = []
    last_len = None
    for _ in range(repeats):
        started = time.perf_counter()
        value = func()
        samples.append(time.perf_counter() - started)
        if isinstance(value, list):
            last_len = len(value)
        elif isinstance(value, int):
            last_len = value
    return {
        "repeats": repeats,
        "min_seconds": round(min(samples), 4),
        "max_seconds": round(max(samples), 4),
        "last_result_len": last_len,
    }


def section_scale(
    work: Path,
    *,
    photo_count: int,
    second_drive: str | None,
) -> dict[str, Any]:
    log(f"synthetic scale: {photo_count} tiny jpegs")
    blob = tiny_jpeg()
    half = photo_count // 2
    rest = photo_count - half
    primary = work / "root-primary"
    if second_drive:
        secondary = Path(second_drive) / "orga-drone-issue-99-bench"
    else:
        secondary = work / "root-secondary-same-volume"
    if secondary.exists():
        shutil.rmtree(secondary)
    primary.mkdir(parents=True, exist_ok=True)
    secondary.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "photo_count": photo_count,
        "composition": (
            f"{photo_count} 8x8 JPEG files, DJI-style names, 100 files per folder, "
            "no EXIF GPS, split across two library roots. Not a drone archive."
        ),
        "primary_drive": str(primary.drive),
        "secondary_drive": str(secondary.drive),
        "same_volume": primary.drive.upper() == secondary.drive.upper(),
        "tiny_jpeg_bytes": len(blob),
        "secondary_root_kept_until_cleanup": str(secondary.drive) + "\\orga-drone-issue-99-bench",
    }
    try:
        result["fixture_write_seconds"] = {
            "primary": round_s(write_tree(primary, 0, half, blob, "photo")),
            "secondary": round_s(write_tree(secondary, half, rest, blob, "photo")),
        }
        db_path = Path(settings.db_path)
        if db_path.exists():
            db_path.unlink()
        db = Database(db_path)
        primary_id = db.add_root(primary, "primary")
        secondary_id = db.add_root(secondary, "secondary")
        discover_started = time.perf_counter()
        primary_found = iter_media_files(primary)
        secondary_found = iter_media_files(secondary)
        result["discover_only_seconds"] = round_s(time.perf_counter() - discover_started)
        result["discover_only_files"] = len(primary_found) + len(secondary_found)

        timer = PhaseTimer()
        mem_before = working_set()
        scanned = scan_all_roots(db, on_progress=timer)
        elapsed = time.perf_counter() - timer.started
        log(f"synthetic first scan done in {round_s(elapsed)}s")
        result["first_scan"] = {
            "seconds": round_s(elapsed),
            "seconds_per_file": round(elapsed / photo_count, 4) if photo_count else None,
            "roots": [
                {
                    "root_id": row.get("root_id"),
                    "error": row.get("error"),
                    "assets": row.get("assets"),
                    "photos": row.get("photos"),
                    "videos": row.get("videos"),
                }
                for row in scanned
            ],
            "phases": phase_durations(timer.events, round_s(elapsed)),
            "memory_before": mem_before,
            "memory_after": working_set(),
            "sqlite_bytes": db_path.stat().st_size,
            "media_rows": sql_count(db, "SELECT COUNT(*) FROM media"),
        }
        rescan_timer = PhaseTimer()
        scan_all_roots(db, on_progress=rescan_timer)
        rescan_elapsed = time.perf_counter() - rescan_timer.started
        log(f"synthetic rescan done in {round_s(rescan_elapsed)}s")
        result["second_full_rescan"] = {
            "seconds": round_s(rescan_elapsed),
            "seconds_per_file": round(rescan_elapsed / photo_count, 4) if photo_count else None,
            "phases": phase_durations(rescan_timer.events, round_s(rescan_elapsed)),
            "sqlite_bytes": db_path.stat().st_size,
            "memory_after": working_set(),
        }
        result["browse_queries"] = {
            "count_media": time_call(lambda: db.count_media()),
            "list_page_50": time_call(lambda: db.list_media(limit=50)),
            "list_page_100": time_call(lambda: db.list_media(limit=100)),
            "list_page_200": time_call(lambda: db.list_media(limit=200)),
            "list_deep_page_50": time_call(
                lambda: db.list_media(limit=50, offset=max(0, photo_count - 50))
            ),
            "list_unbounded": time_call(lambda: db.list_media(), repeats=1),
        }
        page = db.list_media(limit=50)
        ids = [item.id for item in page]
        unique_ids = len(set(ids))
        result["browse_queries"]["page_50_unique_ids"] = unique_ids
        result["browse_queries"]["page_50_row_count"] = len(page)
        thumb_paths = []
        for item in page:
            thumb_paths.append((item.id, Path(item.path), item.kind, item.filename))
        thumb_started = time.perf_counter()
        for media_id, path, kind, filename in thumb_paths:
            ensure_thumbnail(media_id=media_id, path=path, kind=kind, filename=filename)
        cold_thumbs = time.perf_counter() - thumb_started
        thumb_started = time.perf_counter()
        for media_id, path, kind, filename in thumb_paths:
            ensure_thumbnail(media_id=media_id, path=path, kind=kind, filename=filename)
        warm_thumbs = time.perf_counter() - thumb_started
        thumb_dir = settings.data_dir / "thumbs"
        thumb_bytes = 0
        thumb_files = 0
        if thumb_dir.exists():
            for path in thumb_dir.glob("*"):
                if path.is_file():
                    thumb_files += 1
                    thumb_bytes += path.stat().st_size
        result["thumbnails_first_50_tiny_jpegs"] = {
            "cold_seconds": round_s(cold_thumbs),
            "cached_seconds": round_s(warm_thumbs),
            "cache_files": thumb_files,
            "cache_bytes": thumb_bytes,
            "note": "Scan does not build thumbnails. These calls are ensure_thumbnail.",
        }
        result["http"] = section_http()
        result["root_ids"] = {"primary": primary_id, "secondary": secondary_id}
    finally:
        if secondary.exists() and secondary.name == "orga-drone-issue-99-bench":
            shutil.rmtree(secondary, ignore_errors=True)
    return result


def section_http() -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from orga_drone.app import create_app

    client = TestClient(create_app())
    paths = [
        "/browse?page_size=50",
        "/browse?page_size=200",
        "/browse?page=40&page_size=200",
        "/",
    ]
    pages: dict[str, Any] = {}
    for path in paths:
        started = time.perf_counter()
        response = client.get(path)
        pages[path] = {
            "status": response.status_code,
            "seconds": round_s(time.perf_counter() - started),
            "bytes": len(response.content),
        }
    browse = client.get("/browse?page_size=50")
    import re

    ids = re.findall(r"/media/(\d+)/thumb", browse.text)
    unique_ids = list(dict.fromkeys(ids))[:50]
    started = time.perf_counter()
    statuses: dict[str, int] = {}
    for media_id in unique_ids:
        thumb = client.get(f"/media/{media_id}/thumb")
        statuses[str(thumb.status_code)] = statuses.get(str(thumb.status_code), 0) + 1
    return {
        "pages": pages,
        "thumb_gets": {
            "count": len(unique_ids),
            "seconds": round_s(time.perf_counter() - started),
            "statuses": statuses,
        },
        "note": "In-process TestClient. No browser and no WebView2.",
    }


def section_network_and_drives(logical: Any) -> dict[str, Any]:
    probes = {
        "missing_local": run_json_probe(r"C:\orga-drone-issue-99-missing", 8),
        "unc_test_net": run_json_probe(r"\\192.0.2.1\orga-drone-issue99", 20),
        "unc_localhost_missing_share": run_json_probe(
            r"\\localhost\orga-drone-issue99-missing", 20
        ),
    }
    rows = logical if isinstance(logical, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        drive_type = int(row.get("DriveType") or 0)
        device = str(row.get("DeviceID") or "")
        if drive_type in {2, 4, 5} and device:
            probes[f"drive_{device[0].lower()}_type_{drive_type}"] = run_json_probe(
                device + "\\", 12
            )
    return {
        "method": (
            "Path.exists() in a child process. DriveType 2 is removable, 4 is network. "
            "No share was mounted and no drive was ejected."
        ),
        "probes": probes,
    }


def section_removable_folder(drives: list[str], work: Path) -> dict[str, Any]:
    if not drives:
        return {"attempted": False, "reason": "No removable drive with >100 MiB free."}
    device = drives[0]
    root = Path(device) / "orga-drone-issue-99-bench"
    blob = tiny_jpeg()
    try:
        if root.exists():
            shutil.rmtree(root)
        root.mkdir()
        write_seconds = write_tree(root, 0, 100, blob, "photo")
        db = Database(work / "removable.sqlite3")
        root_id = db.add_root(root, "removable")
        started = time.perf_counter()
        counts = scan_root(db, root_id, root)
        scan_seconds = time.perf_counter() - started
        shutil.rmtree(root)
        missing = scan_all_roots(db)
        return {
            "attempted": True,
            "drive": device,
            "files": 100,
            "fixture_write_seconds": round_s(write_seconds),
            "scan_seconds": round_s(scan_seconds),
            "counts": counts,
            "after_folder_removed": [
                {"root_id": row.get("root_id"), "error": row.get("error"), "photos": row.get("photos")}
                for row in missing
            ],
            "media_rows_after_missing_scan": root_snapshot(db, root_id),
            "note": "Folder deleted on a removable volume. The volume was not ejected.",
        }
    except OSError as exc:
        return {"attempted": True, "drive": device, "error": scrub(str(exc))}
    finally:
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)


def section_installed_library(work: Path) -> dict[str, Any]:
    """Rescan the machine's existing library roots into a throwaway database.

    The application database is opened read-only. Output keeps drive letters
    and counts, not paths or filenames.
    """
    db_path = Path(os.environ.get("APPDATA", "")) / "orga-drone" / "orga-drone.sqlite3"
    if not db_path.is_file():
        return {"attempted": False, "reason": "No installed catalog database."}
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        roots = [
            (int(row[0]), str(row[1]))
            for row in conn.execute("SELECT id, path FROM library_roots ORDER BY id")
        ]
    finally:
        conn.close()
    fresh = Database(work / "installed-library.sqlite3")
    log(f"installed library: {len(roots)} roots, throwaway rescan")
    scans: list[dict[str, Any]] = []
    for index, (_source_id, path_text) in enumerate(roots, start=1):
        path = Path(path_text)
        drive = path.drive or "?"
        probe = run_json_probe(path_text, 12)
        entry: dict[str, Any] = {
            "index": index,
            "drive": drive,
            "exists": probe.get("exists"),
            "exists_seconds": probe.get("seconds"),
            "exists_timed_out": probe.get("timed_out"),
        }
        if probe.get("exists") is not True:
            entry["error"] = "missing"
            scans.append(entry)
            continue
        root_id = fresh.add_root(path, f"installed-{index}")
        timer = PhaseTimer()
        try:
            counts = scan_root(fresh, root_id, path, on_progress=timer)
            elapsed = time.perf_counter() - timer.started
            entry.update(
                {
                    "seconds": round_s(elapsed),
                    "counts": counts,
                    "phases": phase_durations(timer.events, round_s(elapsed)),
                    "memory_after": working_set(),
                }
            )
            log(f"installed root {index} scanned in {entry['seconds']}s")
        except Exception as exc:  # noqa: BLE001 — do not record the path
            entry["error"] = type(exc).__name__
            entry["memory_after"] = working_set()
            log(f"installed root {index} failed: {type(exc).__name__}")
        scans.append(entry)
    db_file = work / "installed-library.sqlite3"
    photos = []
    videos = []
    with fresh.connect() as conn:
        photos = list(
            conn.execute(
                "SELECT id, path, filename FROM media WHERE kind = 'photo' LIMIT 10"
            )
        )
        videos = list(
            conn.execute(
                "SELECT id, path, filename FROM media WHERE kind = 'video' LIMIT 3"
            )
        )
    thumb_started = time.perf_counter()
    thumb_ok = 0
    thumb_fail = 0
    samples = [("photo", row) for row in photos] + [("video", row) for row in videos]
    for kind, row in samples:
        try:
            ensure_thumbnail(
                media_id=int(row["id"]),
                path=Path(str(row["path"])),
                kind=kind,
                filename=str(row["filename"]),
            )
            thumb_ok += 1
        except Exception:  # noqa: BLE001
            thumb_fail += 1
    thumb_seconds = time.perf_counter() - thumb_started
    return {
        "attempted": True,
        "method": (
            "Read-only look at the installed catalog, then a full rescan of those "
            "roots into a new SQLite file. Source files were not modified. "
            "Paths and filenames are omitted."
        ),
        "roots": scans,
        "media_rows": sql_count(fresh, "SELECT COUNT(*) FROM media"),
        "photo_rows": sql_count(fresh, "SELECT COUNT(*) FROM media WHERE kind = 'photo'"),
        "video_rows": sql_count(fresh, "SELECT COUNT(*) FROM media WHERE kind = 'video'"),
        "sqlite_bytes": db_file.stat().st_size if db_file.exists() else None,
        "browse_queries": {
            "count_media": time_call(lambda: fresh.count_media()),
            "list_page_50": time_call(lambda: fresh.list_media(limit=50)),
            "list_page_200": time_call(lambda: fresh.list_media(limit=200)),
            "list_unbounded": time_call(lambda: fresh.list_media(), repeats=1),
        },
        "thumbnails": {
            "photos": len(photos),
            "videos": len(videos),
            "ok": thumb_ok,
            "failed": thumb_fail,
            "seconds": round_s(thumb_seconds),
            "note": "First ensure_thumbnail call for this sample. Not the whole library.",
        },
        "memory_after": working_set(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo-count", type=int, default=20_000)
    parser.add_argument("--video-count", type=int, default=80)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "docs" / "discovery" / "issue-99-measurements.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.photo_count < 2:
        print("photo-count must be at least 2", file=sys.stderr)
        return 2
    if BENCH_ROOT.exists():
        shutil.rmtree(BENCH_ROOT)
    BENCH_ROOT.mkdir(parents=True)
    settings.ensure_dirs()
    report: dict[str, Any] = {
        "issue": 99,
        "measured_at": now_iso(),
        "git_head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "label": (
            "Synthetic fixture measurements. Not a recruited 20k photo/video archive "
            "and not a NAS."
        ),
    }
    try:
        log("hardware and catalog counts")
        report["hardware"] = hardware()
        report["installed_catalog_not_rescanned"] = installed_catalog()
        log("drive probes")
        report["network_and_other_drives"] = section_network_and_drives(
            report["hardware"].get("logical_disks")
        )
        report["removable_folder"] = section_removable_folder(
            removable_drives(report["hardware"].get("logical_disks")),
            BENCH_ROOT,
        )
        log("unavailable-root cases")
        report["unavailable_root_cases"] = section_unavailable_roots(BENCH_ROOT)
        log("video stubs")
        report["video_stubs"] = section_videos(BENCH_ROOT, args.video_count)
        log("large synthetic jpegs")
        report["large_synthetic_jpegs"] = section_large_photos(BENCH_ROOT)
        log("geocode sample")
        report["offline_geocode_one_coordinate"] = section_geocode(BENCH_ROOT)
        log("installed library rescan")
        report["installed_library_rescan"] = section_installed_library(BENCH_ROOT)
        log("synthetic scale")
        report["scale"] = section_scale(
            BENCH_ROOT,
            photo_count=args.photo_count,
            second_drive=pick_second_fixed_drive(report["hardware"].get("logical_disks")),
        )
        report["memory_at_end"] = working_set()
    except Exception as exc:  # noqa: BLE001
        report["fatal"] = {
            "error": scrub(f"{type(exc).__name__}: {exc}"),
            "traceback": scrub(traceback.format_exc()),
        }
    finally:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(scrub(report), indent=2),
            encoding="utf-8",
        )
        shutil.rmtree(BENCH_ROOT, ignore_errors=True)
        scale = report.get("scale") if isinstance(report.get("scale"), dict) else None
        if scale and scale.get("secondary_drive") and not scale.get("same_volume"):
            leftover_path = Path(str(scale["secondary_drive"]) + "\\") / "orga-drone-issue-99-bench"
            if leftover_path.exists():
                shutil.rmtree(leftover_path, ignore_errors=True)
    if report.get("fatal"):
        print(report["fatal"]["error"], file=sys.stderr)
        return 1
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
