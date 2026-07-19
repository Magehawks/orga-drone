"""Merge split flow clips into one MP4 via ffmpeg (stream copy)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from orga_drone.db import Database, MediaRow
from orga_drone.media_files import is_under_root, resolve_media_file
from orga_drone.scan import scan_root


@dataclass
class MergeResult:
    output: Path
    clip_count: int
    ffmpeg: str


class MergeError(ValueError):
    pass


def find_ffmpeg() -> str | None:
    which = shutil.which("ffmpeg")
    if which:
        return which
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ffmpeg_available() -> bool:
    return find_ffmpeg() is not None


def default_merge_name(first: MediaRow) -> str:
    stem = Path(first.filename).stem
    return f"{stem}_MERGED.MP4"


def merge_flow(
    db: Database,
    *,
    flow_id: int,
    output_name: str | None = None,
) -> MergeResult:
    clips = db.flow_clips(flow_id)
    videos = [c for c in clips if c.kind == "video"]
    if len(videos) < 2:
        raise MergeError("need at least two video clips")

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise MergeError("ffmpeg missing")

    paths: list[Path] = []
    for clip in videos:
        path = resolve_media_file(db, clip)
        if path is None:
            raise MergeError(f"missing file: {clip.filename}")
        paths.append(path)

    roots = {int(r["id"]): Path(r["path"]) for r in db.list_roots()}
    root = roots.get(videos[0].root_id)
    if root is None:
        raise MergeError("library root missing")

    out_name = (output_name or default_merge_name(videos[0])).strip()
    if not out_name.lower().endswith((".mp4", ".mov", ".mkv")):
        out_name += ".MP4"
    if "/" in out_name or "\\" in out_name or ":" in out_name:
        raise MergeError("invalid output name")

    output = paths[0].parent / out_name
    if output.exists():
        raise MergeError(f"target exists: {output.name}")
    if not is_under_root(output, root):
        raise MergeError("target outside library")

    # ffmpeg concat demuxer list
    with tempfile.TemporaryDirectory(prefix="orga-merge-") as tmp:
        list_file = Path(tmp) / "concat.txt"
        lines = []
        for p in paths:
            # Escape single quotes for ffmpeg concat
            escaped = str(p.resolve()).replace("'", r"'\''")
            lines.append(f"file '{escaped}'")
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60 * 60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MergeError(str(exc)) from exc

        if proc.returncode != 0 or not output.exists():
            err = (proc.stderr or proc.stdout or "ffmpeg failed")[-800:]
            if output.exists():
                output.unlink(missing_ok=True)
            raise MergeError(err)

    # Refresh index for this library root so the merged file appears
    scan_root(db, videos[0].root_id, root)
    return MergeResult(output=output, clip_count=len(videos), ffmpeg=ffmpeg)
