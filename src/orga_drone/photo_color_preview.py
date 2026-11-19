"""Server JPEG preview for library-photo color (#491).

Reuses ``render_preview_frame`` builders at a capped edge so Detail can show
HSL/LUT/wheels/managed without CSS approximation.
"""

from __future__ import annotations

from pathlib import Path

from orga_drone.photo_color import photo_color_parts
from orga_drone.studio_preview_frame import (
    PREVIEW_MAX_EDGE,
    PreviewFrameError,
    PreviewFrameRequest,
    render_preview_frame,
)

PHOTO_COLOR_PREVIEW_MAX_EDGE = PREVIEW_MAX_EDGE


def render_photo_color_preview(
    source: Path,
    color_raw: str | None,
    *,
    data_dir: Path,
    max_edge: int = PHOTO_COLOR_PREVIEW_MAX_EDGE,
    cache_dir: Path | None = None,
) -> Path:
    """Return a cached JPEG path for the graded photo still."""
    parts = photo_color_parts(color_raw)
    req = PreviewFrameRequest(
        media_path=source,
        kind="photo",
        source_time_s=0.0,
        image=parts.image,
        look=parts.color_look,
        hsl=parts.hsl,
        color_wheels=parts.color_wheels,
        max_edge=max(64, int(max_edge)),
        effect_settings=parts.effect_settings if parts.managed else None,
        exact_time=True,
    )
    try:
        return render_preview_frame(req, data_dir=data_dir, cache_dir=cache_dir)
    except PreviewFrameError:
        raise
