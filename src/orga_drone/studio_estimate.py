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
    if kind_snapshot == "title_card":
        return "title_card"
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
    source_in_s: float | None = None,
    source_out_s: float | None = None,
    card_duration_s: float | None = None,
) -> float | None:
    if kind == "title_card":
        from orga_drone.studio_title_card import DEFAULT_DURATION_S, clamp_card_duration

        if card_duration_s is not None:
            return clamp_card_duration(float(card_duration_s))
        return DEFAULT_DURATION_S
    if kind == "photo":
        if photo_duration_s is not None:
            return float(photo_duration_s)
        return DEFAULT_PHOTO_DURATION_S
    if kind == "video":
        if not available:
            return None
        from orga_drone.studio_cut import resolve_source_range

        rang = resolve_source_range(
            source_in_s=source_in_s,
            source_out_s=source_out_s,
            media_duration_s=duration_s,
        )
        if rang is None:
            return None
        return rang.duration_s
    return None


def summarize_studio_items(items: Iterable[StudioEstimateItem]) -> StudioSummary:
    photo_count = 0
    video_count = 0
    total = 0.0
    for item in items:
        kind = item.kind if item.kind in {"photo", "video", "title_card"} else "unknown"
        if kind == "photo":
            photo_count += 1
        elif kind == "video":
            video_count += 1
        source_in = getattr(item, "source_in_s", None)
        source_out = getattr(item, "source_out_s", None)
        card_duration = getattr(item, "card_duration_s", None)
        seconds = effective_seconds(
            kind=kind,
            photo_duration_s=item.photo_duration_s,
            duration_s=item.duration_s,
            available=item.available,
            source_in_s=source_in,
            source_out_s=source_out,
            card_duration_s=card_duration,
        )
        if seconds is not None:
            total += seconds
    return StudioSummary(
        photo_count=photo_count,
        video_count=video_count,
        estimated_total_s=total,
        estimated_total_label=format_studio_duration(total),
    )


@dataclass(frozen=True)
class ProjectTimeHit:
    """Active Story clip for a global project time."""

    index: int
    start_s: float
    duration_s: float
    local_s: float
    at_end: bool


def resolve_project_time(
    durations_s: Iterable[float],
    project_time_s: float,
) -> ProjectTimeHit | None:
    """Map global Story time to clip index and local time within that clip.

    Clips with non-positive duration are skipped. At or past the total length,
    the last clip is returned with ``at_end=True`` and ``local_s`` clamped to
    the clip duration (or 0 for an empty story).
    """
    spans: list[tuple[int, float, float]] = []
    cursor = 0.0
    for index, raw in enumerate(durations_s):
        dur = float(raw)
        if dur <= 0:
            continue
        spans.append((index, cursor, dur))
        cursor += dur
    if not spans:
        return None
    total = cursor
    t = max(0.0, float(project_time_s))
    if t >= total:
        index, start, dur = spans[-1]
        return ProjectTimeHit(
            index=index,
            start_s=start,
            duration_s=dur,
            local_s=dur,
            at_end=True,
        )
    for index, start, dur in spans:
        if t < start + dur:
            return ProjectTimeHit(
                index=index,
                start_s=start,
                duration_s=dur,
                local_s=t - start,
                at_end=False,
            )
    index, start, dur = spans[-1]
    return ProjectTimeHit(
        index=index,
        start_s=start,
        duration_s=dur,
        local_s=dur,
        at_end=True,
    )
