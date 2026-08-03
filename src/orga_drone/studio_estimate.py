"""Studio runtime estimate helpers (planning summary, not playback/export)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

DEFAULT_PHOTO_DURATION_S = 3.0
MIN_PHOTO_DURATION_S = 0.5
MAX_PHOTO_DURATION_S = 60.0


class StudioEstimateItem(Protocol):
    """Minimal fields needed to estimate Studio runtime.

    ``kind`` is the *effective* kind (live when available, else snapshot).
    """

    available: bool
    kind: str | None
    photo_duration_s: float | None
    duration_s: float | None


@dataclass(frozen=True)
class StudioSummary:
    photo_count: int
    video_count: int
    estimated_total_s: float
    estimated_total_label: str

    def as_dict(self) -> dict[str, int | float | str]:
        return {
            "photo_count": self.photo_count,
            "video_count": self.video_count,
            "estimated_total_s": self.estimated_total_s,
            "estimated_total_label": self.estimated_total_label,
        }


def clamp_photo_duration(duration_s: float) -> float:
    return max(MIN_PHOTO_DURATION_S, min(MAX_PHOTO_DURATION_S, float(duration_s)))


def format_studio_duration(seconds: float) -> str:
    """Always ``HH:MM:SS`` for Studio summary totals (not Browse ``m:ss``)."""
    total = int(round(max(0.0, float(seconds))))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def effective_kind(
    *,
    available: bool,
    live_kind: str | None,
    kind_snapshot: str | None,
) -> str:
    if available and live_kind in {"photo", "video"}:
        return live_kind
    if kind_snapshot in {"photo", "video"}:
        return kind_snapshot
    return "unknown"


def effective_seconds(
    *,
    kind: str,
    photo_duration_s: float | None,
    duration_s: float | None,
    available: bool,
) -> float | None:
    if kind == "photo":
        if photo_duration_s is not None:
            return float(photo_duration_s)
        return DEFAULT_PHOTO_DURATION_S
    if kind == "video":
        if available and duration_s is not None:
            return float(duration_s)
        return None
    return None


def summarize_studio_items(items: Iterable[StudioEstimateItem]) -> StudioSummary:
    photo_count = 0
    video_count = 0
    total = 0.0
    for item in items:
        kind = item.kind if item.kind in {"photo", "video"} else "unknown"
        if kind == "photo":
            photo_count += 1
        elif kind == "video":
            video_count += 1
        seconds = effective_seconds(
            kind=kind,
            photo_duration_s=item.photo_duration_s,
            duration_s=item.duration_s,
            available=item.available,
        )
        if seconds is not None:
            total += seconds
    return StudioSummary(
        photo_count=photo_count,
        video_count=video_count,
        estimated_total_s=total,
        estimated_total_label=format_studio_duration(total),
    )
