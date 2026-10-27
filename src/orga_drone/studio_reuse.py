"""Add another source range from a Story clip's original file.

The new row references the same library media. The file is not copied, and
the clip the person started from keeps its trim and settings.
"""

from __future__ import annotations

from orga_drone.studio_cut import MIN_SEGMENT_S, resolve_source_range

REUSE_REASONS = {
    "not_found": "That Story clip is no longer there.",
    "not_video": "Another scene can only be chosen from a video.",
    "offline": "This recording is offline, so another scene cannot be chosen.",
    "duration_unknown": "The length of this recording is unknown, so a range cannot be chosen.",
    "too_short": "That range is too short.",
    "outside": "That range is outside the recording.",
}


class ReuseBlocked(Exception):
    """The requested range cannot be added. ``code`` is a ``REUSE_REASONS`` key."""

    def __init__(self, code: str) -> None:
        self.code = code if code in REUSE_REASONS else "outside"
        super().__init__(self.code)


def stored_source_range(
    source_in_s: object,
    source_out_s: object,
    media_duration_s: float,
) -> tuple[float | None, float | None]:
    """Clamp a requested range to the catalog duration.

    A range that covers the whole file is stored as NULL, NULL, matching Cut
    and the section editor. Overlap with the clip already in the Story is
    allowed. Raises ``ReuseBlocked`` when the span is unusable.
    """
    if isinstance(source_in_s, bool) or not isinstance(source_in_s, (int, float)):
        raise ReuseBlocked("outside")
    if isinstance(source_out_s, bool) or not isinstance(source_out_s, (int, float)):
        raise ReuseBlocked("outside")
    duration = float(media_duration_s)
    if duration <= 0:
        raise ReuseBlocked("duration_unknown")
    rang = resolve_source_range(
        source_in_s=float(source_in_s),
        source_out_s=float(source_out_s),
        media_duration_s=duration,
    )
    if rang is None:
        raise ReuseBlocked("outside")
    if rang.duration_s < MIN_SEGMENT_S:
        raise ReuseBlocked("too_short")
    if rang.source_in_s <= 1e-4 and rang.source_out_s >= duration - 1e-3:
        return None, None
    return rang.source_in_s, rang.source_out_s
