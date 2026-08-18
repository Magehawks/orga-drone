"""Functional smoke checks for a running packaged orga-drone.exe via its HTTP API.

Used by ``packaging/windows_motw_smoke.ps1`` after MOTW extract + launch.
Requires indexed library media (at least one video) for the 1080p export step.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TAG = "MOTW-SMOKE"
OUT = Path(os.environ.get("TEMP", ".")) / "orga-drone-motw-smoke-export"
WORK = Path(os.environ.get("TEMP", ".")) / "orga-drone-motw-smoke-work"
MUSIC = WORK / "track.mp3"
DB = Path(os.environ["APPDATA"]) / "orga-drone" / "orga-drone.sqlite3"


def call(
    base: str,
    method: str,
    path: str,
    data: dict | None = None,
    form: dict | None = None,
    timeout: int = 600,
) -> tuple[int, dict]:
    url = base + path
    body: bytes | None = None
    headers: dict[str, str] = {}
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300]
        print(f"HTTP {exc.code} {method} {path}: {detail!r}")
        return exc.code, {}
    try:
        return 200, json.loads(raw)
    except ValueError:
        return 200, {}


def query(sql: str, args: tuple = ()) -> tuple | None:
    if not DB.is_file():
        return None
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return con.execute(sql, args).fetchone()
    finally:
        con.close()


def find_ffmpeg(extract_root: Path | None) -> str | None:
    if extract_root is not None:
        matches = sorted(
            extract_root.rglob("ffmpeg-win*.exe"),
            key=lambda p: len(str(p)),
        )
        if matches:
            return str(matches[0])
    for name in ("ffmpeg", "ffmpeg.exe"):
        try:
            subprocess.run(  # noqa: S603
                [name, "-version"],
                check=True,
                capture_output=True,
                timeout=10,
            )
            return name
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    return None


def ensure_music(ffmpeg: str) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    if MUSIC.is_file():
        return
    subprocess.run(  # noqa: S603
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:a",
            "libmp3lame",
            str(MUSIC),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )


def run_export(base: str, ffmpeg: str) -> int:
    ensure_music(ffmpeg)
    _, project = call(base, "POST", "/api/studio/projects", {"title": TAG})
    pid = project.get("id")
    if pid is None:
        print("EXPORT=FAIL no project id")
        return 3
    call(base, "POST", f"/api/studio/projects/{pid}/open")
    call(base, "POST", "/api/studio/title-cards")
    row = query(
        "SELECT id FROM media WHERE kind='video' AND duration_s > 10 "
        "AND height >= 1080 ORDER BY duration_s ASC LIMIT 1"
    )
    if row is None:
        row = query(
            "SELECT id FROM media WHERE kind='video' AND height IS NOT NULL "
            "ORDER BY duration_s ASC LIMIT 1"
        )
    if row is None:
        print("EXPORT=SKIP no indexed video media in library")
        return 2
    media_id = int(row[0])
    call(base, "POST", f"/media/{media_id}/studio/add", form={"return_to": "studio"})
    clip = query(
        "SELECT id FROM studio_clips WHERE project_id=? ORDER BY id DESC LIMIT 1",
        (pid,),
    )
    if clip:
        _, cut = call(base, "POST", f"/api/studio/{clip[0]}/cut", {"local_s": 2.0})
        if cut.get("right_id"):
            call(base, "POST", f"/studio/{cut['right_id']}/remove")
    _, music = call(base, "POST", f"/api/studio/projects/{pid}/music", {"path": str(MUSIC)})
    tracks = music.get("tracks") or music.get("clips") or []
    print(f"MUSIC_TRACKS={len(tracks)}")
    _, options = call(base, "GET", f"/api/studio/export/options?project_id={pid}")
    heights = [int(o["height"]) for o in options.get("options", [])]
    height = 1080 if 1080 in heights else (heights[0] if heights else None)
    if height is None:
        print("EXPORT=FAIL no export height options")
        return 3
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "motw-smoke-1080p.mp4"
    if target.exists():
        target.unlink()
    _, job = call(
        base,
        "POST",
        "/api/studio/export",
        {
            "height": height,
            "output_path": str(target),
            "overwrite": True,
            "project_id": pid,
        },
    )
    job_id = job.get("job_id") or job.get("id")
    print(f"EXPORT_JOB={job_id}")
    payload: dict = {}
    deadline = time.time() + 420
    while job_id and time.time() < deadline:
        _, payload = call(base, "GET", f"/api/studio/export/jobs/{job_id}")
        state = str(payload.get("state") or payload.get("status") or "")
        if state in {"done", "success", "finished", "error", "failed", "cancelled"}:
            break
        time.sleep(2)
    ok = target.is_file() and target.stat().st_size > 10_000
    size = target.stat().st_size if target.is_file() else 0
    print(f"EXPORT_STATE={payload.get('state') or payload.get('status')}")
    print(f"EXPORT_FILE={target} SIZE={size}")
    marker = WORK / "persist-marker.json"
    marker.write_text(
        json.dumps({"project_id": pid, "title": TAG, "music": str(MUSIC)}),
        encoding="utf-8",
    )
    print(f"PERSIST_MARKER={marker}")
    print(f"EXPORT={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 4


def verify_restart(base: str) -> int:
    marker_path = WORK / "persist-marker.json"
    if not marker_path.is_file():
        print("RESTART=SKIP no persist marker from export step")
        return 0
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    _, projects = call(base, "GET", "/api/studio/projects")
    found = any(
        p.get("id") == marker["project_id"] and p.get("title") == marker["title"]
        for p in projects.get("projects", [])
    )
    _, music = call(base, "GET", f"/api/studio/projects/{marker['project_id']}/music")
    track_count = len(music.get("tracks") or music.get("clips") or [])
    print(f"RESTART_PROJECT={'PASS' if found else 'FAIL'} id={marker['project_id']}")
    print(f"RESTART_MUSIC={'PASS' if track_count >= 1 else 'FAIL'} tracks={track_count}")
    return 0 if found and track_count >= 1 else 5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--extract-root",
        type=Path,
        default=None,
        help="Extracted orga-drone folder (used to locate bundled ffmpeg)",
    )
    parser.add_argument("--ffmpeg", default="", help="Explicit ffmpeg executable path")
    parser.add_argument(
        "--restart-only",
        action="store_true",
        help="Only verify project/music persistence after relaunch",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    if args.restart_only:
        return verify_restart(base)

    ffmpeg = args.ffmpeg.strip() or find_ffmpeg(args.extract_root)
    if ffmpeg is None:
        print("EXPORT=SKIP no ffmpeg found for test soundtrack")
        return 2
    return run_export(base, ffmpeg)


if __name__ == "__main__":
    raise SystemExit(main())
