"""Studio video cut: split a trimmed Story clip at a local playhead offset.

Source media files are never modified. Only Studio clip start/end offsets change.

A section repeat plays that same in/out range again (Issue #112). It is not
slow motion: each play uses the source timing as-is. The count is capped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

# Reject cuts that would leave a segment shorter than this (seconds).
MIN_SEGMENT_S = 0.05

# One play is 1. Extra plays stop at this cap so a story cannot grow without limit.
MAX_SECTION_REPEATS = 8
SECTION_REPEATS_KEY = "section_repeats"


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


def parse_section_repeats(value: object) -> int:
    """Whole-number repeat count from 1 to ``MAX_SECTION_REPEATS``.

    Counts above the cap become the cap. Bools, fractions, and values below 1
    are rejected. 1 means the in/out range plays once.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("repeat count must be a whole number from 1 to 8")
    number = float(value)
    try:
        count = int(number)
    except (OverflowError, ValueError) as exc:
        raise ValueError("repeat count must be a whole number from 1 to 8") from exc
    if number != count or count < 1:
        raise ValueError("repeat count must be a whole number from 1 to 8")
    return min(MAX_SECTION_REPEATS, count)


def section_repeats_from_effect_settings(raw: str | None) -> int:
    """Read ``section_repeats`` from effect JSON. Missing or bad values are 1."""
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return 1
    if not isinstance(parsed, dict) or SECTION_REPEATS_KEY not in parsed:
        return 1
    try:
        return parse_section_repeats(parsed[SECTION_REPEATS_KEY])
    except ValueError:
        return 1


def dump_section_repeats(existing: str | None, repeats: int) -> str:
    """Store the repeat count and keep unrelated effect_settings keys.

    A count of 1 omits the key so ordinary clips stay unchanged.
    """
    count = parse_section_repeats(repeats)
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    if count <= 1:
        data.pop(SECTION_REPEATS_KEY, None)
    else:
        data[SECTION_REPEATS_KEY] = count
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def repeated_duration_s(cycle_s: float, repeats: int) -> float:
    """Story length of one in/out range played ``repeats`` times."""
    count = max(1, min(MAX_SECTION_REPEATS, int(repeats)))
    return max(0.0, float(cycle_s)) * count


def section_playback_point(
    local_s: float,
    cycle_s: float,
    repeats: int,
) -> tuple[int, float]:
    """Map story-local time onto one play of the section.

    Returns ``(repeat_index, offset_s)``. The exact end of the repeated span
    stays on the last repeat at ``offset_s == cycle_s`` and does not wrap to 0.
    One repeat returns ``(0, local_s)``. Preview uses the same mapping.
    """
    count = max(1, min(MAX_SECTION_REPEATS, int(repeats)))
    cycle = float(cycle_s)
    local = max(0.0, float(local_s))
    if count <= 1 or cycle <= 0:
        return 0, local
    span = cycle * count
    if local >= span - 1e-6:
        return count - 1, cycle
    index = min(count - 1, int(local // cycle))
    return index, local - (index * cycle)
