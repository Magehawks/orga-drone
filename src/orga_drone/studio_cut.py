"""Studio video cut: split a trimmed Story clip at a local playhead offset.

Source media files are never modified. Only Studio clip start/end offsets change.
"""

from __future__ import annotations

from dataclasses import dataclass

# Reject cuts that would leave a segment shorter than this (seconds).
MIN_SEGMENT_S = 0.05


@dataclass(frozen=True)
class SourceRange:
    """Inclusive-start / exclusive-end range in the source media timeline."""

    source_in_s: float
    source_out_s: float

    @property
    def duration_s(self) -> float:
        return max(0.0, float(self.source_out_s) - float(self.source_in_s))


def resolve_source_range(
    *,
    source_in_s: float | None,
    source_out_s: float | None,
    media_duration_s: float | None,
) -> SourceRange | None:
    """Resolve stored offsets against the source media duration.

    ``None`` in/out means full media (0 .. duration). Returns ``None`` when the
    media duration is unknown and both ends are not fully specified as a valid
    positive span.
    """
    if media_duration_s is not None:
        media_dur = float(media_duration_s)
        if media_dur <= 0:
            return None
        start = 0.0 if source_in_s is None else float(source_in_s)
        end = media_dur if source_out_s is None else float(source_out_s)
    else:
        if source_in_s is None or source_out_s is None:
            return None
        start = float(source_in_s)
        end = float(source_out_s)
    start = max(0.0, start)
    if end <= start:
        return None
    if media_duration_s is not None:
        end = min(end, float(media_duration_s))
        if end <= start:
            return None
    return SourceRange(source_in_s=start, source_out_s=end)


def split_source_range(
    rang: SourceRange,
    local_cut_s: float,
    *,
    min_segment_s: float = MIN_SEGMENT_S,
) -> tuple[SourceRange, SourceRange]:
    """Split ``rang`` at ``local_cut_s`` seconds from the range start.

    Raises ``ValueError`` when the cut is at/near either end or outside the range.
    The two results always satisfy ``left.duration + right.duration == rang.duration``.
    """
    local = float(local_cut_s)
    dur = rang.duration_s
    if local <= min_segment_s or local >= dur - min_segment_s:
        raise ValueError("cut position must be inside the clip, not at the ends")
    cut_abs = rang.source_in_s + local
    left = SourceRange(source_in_s=rang.source_in_s, source_out_s=cut_abs)
    right = SourceRange(source_in_s=cut_abs, source_out_s=rang.source_out_s)
    if abs((left.duration_s + right.duration_s) - dur) > 1e-9:
        raise ValueError("split duration mismatch")
    return left, right
