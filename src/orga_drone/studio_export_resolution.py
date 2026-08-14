"""Studio export resolution levels and destination helpers (Issue #17).

Pure, codec-agnostic rules: no encoder details here.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# Supported export levels (height in pixels). Labels are UI-facing keys.
EXPORT_LEVELS: tuple[tuple[int, str], ...] = (
    (720, "720p"),
    (1080, "1080p"),
    (1440, "1440p"),
    (2160, "4K"),
)

RECOMMENDED_HEIGHT = 1080


@dataclass(frozen=True)
class ExportResolutionOption:
    height: int
    label: str
    width: int
    recommended: bool = False

    def as_dict(self) -> dict[str, int | str | bool]:
        return {
            "height": self.height,
            "label": self.label,
            "width": self.width,
            "recommended": self.recommended,
        }


def height_to_width(height: int) -> int:
    """16:9 frame width for a given export height."""
    return {720: 1280, 1080: 1920, 1440: 2560, 2160: 3840}.get(int(height), int(round(height * 16 / 9)))


def classify_source_height(height: int | None) -> int | None:
    """Map a source frame height to the highest supported export level it justifies.

    Uses a small tolerance so 2160-ish / 1080-ish sources still qualify.
    """
    if height is None:
        return None
    h = int(height)
    if h <= 0:
        return None
    if h >= 2100:
        return 2160
    if h >= 1400:
        return 1440
    if h >= 1000:
        return 1080
    if h >= 700:
        return 720
    return None


def max_project_export_height(source_heights: list[int | None]) -> int | None:
    """Highest meaningful export level justified by project video sources."""
    levels = [classify_source_height(h) for h in source_heights]
    usable = [h for h in levels if h is not None]
    return max(usable) if usable else None


def generated_only_export_resolutions() -> list[ExportResolutionOption]:
    """720 and 1080 when the project has Title Cards but no video heights."""
    return [
        ExportResolutionOption(
            height=720,
            label="720p",
            width=height_to_width(720),
            recommended=False,
        ),
        ExportResolutionOption(
            height=1080,
            label="1080p",
            width=height_to_width(1080),
            recommended=True,
        ),
    ]


def generated_only_default_height() -> int:
    return RECOMMENDED_HEIGHT


def available_export_resolutions(
    source_heights: list[int | None],
) -> list[ExportResolutionOption]:
    """Supported levels up to the project maximum (no artificial upscale options)."""
    ceiling = max_project_export_height(source_heights)
    if ceiling is None:
        return []
    default_h = default_export_height(source_heights)
    out: list[ExportResolutionOption] = []
    for height, label in EXPORT_LEVELS:
        if height > ceiling:
            continue
        out.append(
            ExportResolutionOption(
                height=height,
                label=label,
                width=height_to_width(height),
                recommended=(
                    height == RECOMMENDED_HEIGHT and default_h == RECOMMENDED_HEIGHT
                ),
            )
        )
    return out


def default_export_height(source_heights: list[int | None]) -> int | None:
    """1080p when the project supports it; else the highest available level."""
    ceiling = max_project_export_height(source_heights)
    if ceiling is None:
        return None
    if ceiling >= RECOMMENDED_HEIGHT:
        return RECOMMENDED_HEIGHT
    return ceiling


_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def suggested_export_filename(project_title: str) -> str:
    """Safe ``.mp4`` basename derived from the Studio project title."""
    raw = (project_title or "").strip() or "Your story"
    cleaned = _UNSAFE_FILENAME.sub(" ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "Your story"
    # Windows reserved device names
    if cleaned.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        cleaned = f"export-{cleaned}"
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip(" .")
    return f"{cleaned}.mp4"


def default_videos_directory() -> Path:
    """OS Videos folder when available, else the user home directory."""
    home = Path.home()
    if os.name == "nt":
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            videos = Path(userprofile) / "Videos"
            if videos.is_dir():
                return videos.resolve()
        known = home / "Videos"
        if known.is_dir():
            return known.resolve()
    else:
        xdg = os.environ.get("XDG_VIDEOS_DIR")
        if xdg:
            p = Path(xdg).expanduser()
            if p.is_dir():
                return p.resolve()
        videos = home / "Videos"
        if videos.is_dir():
            return videos.resolve()
        movies = home / "Movies"
        if movies.is_dir():
            return movies.resolve()
    return home.resolve()


def resolve_export_directory(last_successful: str | None) -> Path:
    """Prefer last successful export dir; else OS Videos (or home)."""
    if last_successful:
        candidate = Path(last_successful).expanduser()
        try:
            if candidate.is_dir():
                return candidate.resolve()
        except OSError:
            pass
    return default_videos_directory()
