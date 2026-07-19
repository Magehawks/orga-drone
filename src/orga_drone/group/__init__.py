"""Group split DJI clips into flows (4GB FAT32 splits)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Avata 2 / DJI often splits near ~3.5–3.7 GB on FAT32
NEAR_LIMIT_BYTES = int(3.4 * 1024**3)
MAX_GAP_SECONDS = 5 * 60  # continuation window after a near-full file


@dataclass
class ClipForGrouping:
    media_id: int
    recorded_at: datetime | None
    sequence: int | None
    size_bytes: int
    duration_s: float | None


def should_continue(prev: ClipForGrouping, current: ClipForGrouping) -> bool:
    if prev.recorded_at is None or current.recorded_at is None:
        return False
    if prev.size_bytes < NEAR_LIMIT_BYTES:
        return False

    gap = (current.recorded_at - prev.recorded_at).total_seconds()
    if gap < 0 or gap > MAX_GAP_SECONDS:
        return False

    # Sequence should be consecutive when available
    if prev.sequence is not None and current.sequence is not None:
        if current.sequence != prev.sequence + 1:
            return False

    return True


def group_clips_into_flows(clips: list[ClipForGrouping]) -> list[list[int]]:
    """Return list of flows; each flow is an ordered list of media_ids."""
    ordered = sorted(
        clips,
        key=lambda c: (
            c.recorded_at or datetime.min,
            c.sequence if c.sequence is not None else 0,
            c.media_id,
        ),
    )
    if not ordered:
        return []

    flows: list[list[int]] = []
    current: list[ClipForGrouping] = [ordered[0]]

    for clip in ordered[1:]:
        if should_continue(current[-1], clip):
            current.append(clip)
        else:
            flows.append([c.media_id for c in current])
            current = [clip]
    flows.append([c.media_id for c in current])
    return flows
