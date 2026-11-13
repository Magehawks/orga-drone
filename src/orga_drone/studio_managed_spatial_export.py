"""Materialize spatial managed grades for preview/export (#356/#357).

Pointwise grades stay on the lut3d bake path. Spatial selections cannot fold
into a global cube, so this module writes a temporary graded copy. Source
media is never overwritten.

Video spatial export is fail-closed until a timing/audio-accurate adapter
exists; photo export is supported.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from orga_drone.studio_managed_apply import (
    ManagedApplyError,
    apply_managed_grade_image,
)


def source_identity(path: Path) -> str:
    """Stable cache fragment from path + size + mtime."""
    try:
        st = path.stat()
    except OSError as exc:
        raise ManagedApplyError("source media is missing", code="MEDIA_MISSING") from exc
    payload = f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def spatial_work_dir(base: Path, *, grade_digest: str, source: Path) -> Path:
    """Work directory that cannot collide across different source files."""
    return base / f"spatial_{grade_digest[:16]}_{source_identity(source)}"


def _grade_rgb_image(path: Path, grade: Mapping[str, Any], dest: Path) -> Path:
    from PIL import Image

    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        raw = list(rgb.getdata())
        rows = [
            [
                (
                    raw[y * width + x][0] / 255.0,
                    raw[y * width + x][1] / 255.0,
                    raw[y * width + x][2] / 255.0,
                )
                for x in range(width)
            ]
            for y in range(height)
        ]
        graded = apply_managed_grade_image(rows, grade, lattice_domain="srgb")
        out = Image.new("RGB", (width, height))
        out.putdata(
            [
                (
                    int(min(255, max(0, round(sample[0] * 255)))),
                    int(min(255, max(0, round(sample[1] * 255)))),
                    int(min(255, max(0, round(sample[2] * 255)))),
                )
                for row in graded
                for sample in row
            ]
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.save(dest, format="PNG")
    return dest


def materialize_spatial_managed_media(
    source: Path,
    grade: Mapping[str, Any],
    work_dir: Path,
    *,
    kind: str,
    grade_digest: str | None = None,
) -> Path:
    """Return a temporary graded media path under ``work_dir``.

    ``work_dir`` should already incorporate source identity (see
    ``spatial_work_dir``). Video is rejected until a timing-accurate adapter
    ships.
    """
    if not source.is_file():
        raise ManagedApplyError("source media is missing", code="MEDIA_MISSING")
    if kind == "video":
        raise ManagedApplyError(
            "Spatial managed grades on video need a timing-accurate adapter before export",
            code="UNSUPPORTED_GRADE",
        )
    if kind != "photo":
        raise ManagedApplyError(f"unsupported spatial kind: {kind}", code="UNSUPPORTED_GRADE")

    # Prefer an isolated work dir when the caller passes a shared base + digest.
    if grade_digest:
        work_dir = spatial_work_dir(work_dir, grade_digest=grade_digest, source=source)
    work_dir.mkdir(parents=True, exist_ok=True)
    dest = work_dir / "graded.png"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    from orga_drone.export.studio_encoder import _materialize_photo_still

    still = work_dir / "source.jpg"
    _materialize_photo_still(source, still)
    return _grade_rgb_image(still, grade, dest)
