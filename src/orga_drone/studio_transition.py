"""Studio visual transitions (Issue #27 / ADR 0010).

Shared apply/clamp/story-length rules for estimate, preview, export, and music
trim. Persist canonical type ids and a duration number — never ffmpeg strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

TYPE_CUT = "cut"
TYPE_FADE_BLACK = "fade_black"
TYPE_CROSSFADE = "crossfade"
CANONICAL_TYPES = frozenset({TYPE_CUT, TYPE_FADE_BLACK, TYPE_CROSSFADE})
# Stub / legacy values stored by the unrendered client UI or unused TEXT column.
LEGACY_CUT_TYPES = frozenset({"", "none", "fade", "slide"})

DEFAULT_DURATION_S = 0.5
MIN_DURATION_S = 0.1
MAX_DURATION_S = 2.0
DURATION_STEP_S = 0.1
MIN_OUTSIDE_S = 0.1


def normalize_type(raw: str | None) -> str:
    """Map stored/legacy values to a canonical id. Unknown → cut."""
    if raw is None:
        return TYPE_CUT
    value = str(raw).strip().lower()
    if value in CANONICAL_TYPES:
        return value
    return TYPE_CUT


def clamp_user_duration(duration_s: float) -> float:
    """Clamp to 0.1–2.0 s and snap to 0.1 s steps."""
    stepped = round(float(duration_s) / DURATION_STEP_S) * DURATION_STEP_S
    stepped = round(stepped, 1)
    return max(MIN_DURATION_S, min(MAX_DURATION_S, stepped))


def occupancy_s(applied_type: str, applied_d: float) -> float:
    """How much of a clip this boundary occupies on one side."""
    if applied_type == TYPE_FADE_BLACK:
        return max(0.0, float(applied_d) / 2.0)
    if applied_type == TYPE_CROSSFADE:
        return max(0.0, float(applied_d))
    return 0.0


@dataclass(frozen=True)
class AppliedTransition:
    """One outgoing boundary after clamp / fallback."""

    type: str
    duration_s: float
    stored_type: str
    stored_duration_s: float | None
    fallback_cut: bool
    clamped: bool

    @property
    def is_crossfade(self) -> bool:
        return self.type == TYPE_CROSSFADE and self.duration_s > 0

    @property
    def is_fade_black(self) -> bool:
        return self.type == TYPE_FADE_BLACK and self.duration_s > 0


def _cut_applied(
    stored_type: str,
    stored_duration_s: float | None,
    *,
    fallback_cut: bool,
    clamped: bool,
) -> AppliedTransition:
    return AppliedTransition(
        type=TYPE_CUT,
        duration_s=0.0,
        stored_type=stored_type,
        stored_duration_s=stored_duration_s,
        fallback_cut=fallback_cut,
        clamped=clamped,
    )


def apply_one_boundary(
    stored_type: str | None,
    stored_duration_s: float | None,
    duration_a: float,
    duration_b: float,
) -> AppliedTransition:
    """Apply one outgoing boundary without two-sided occupancy."""
    stored = normalize_type(stored_type)
    remembered = (
        None
        if stored_duration_s is None
        else clamp_user_duration(float(stored_duration_s))
    )
    if stored == TYPE_CUT:
        return _cut_applied(stored, remembered, fallback_cut=False, clamped=False)
    user_d = DEFAULT_DURATION_S if remembered is None else remembered
    max_d = min(float(duration_a), float(duration_b)) - MIN_OUTSIDE_S
    if max_d < MIN_DURATION_S:
        return _cut_applied(
            stored, remembered if remembered is not None else user_d, fallback_cut=True, clamped=False
        )
    applied_d = min(user_d, max_d)
    applied_d = round(applied_d, 4)
    clamped = applied_d + 1e-9 < user_d
    return AppliedTransition(
        type=stored,
        duration_s=applied_d,
        stored_type=stored,
        stored_duration_s=remembered if remembered is not None else user_d,
        fallback_cut=False,
        clamped=clamped,
    )


def apply_boundaries(
    durations_s: Sequence[float],
    stored_types: Sequence[str | None],
    stored_durations_s: Sequence[float | None],
) -> list[AppliedTransition]:
    """Apply outgoing transitions for clips 0..n-2.

    Last clip stored values are ignored. Empty/unknown types become Cut.
    Two-sided occupancy: if in+out occupy more than ``duration - 0.1``, fall
    back the outgoing boundary to Cut, then the incoming if still over.
    """
    n = len(durations_s)
    if n <= 1:
        return []
    if len(stored_types) < n or len(stored_durations_s) < n:
        raise ValueError("stored transition lists must cover every clip")
    applied: list[AppliedTransition] = []
    for i in range(n - 1):
        applied.append(
            apply_one_boundary(
                stored_types[i],
                stored_durations_s[i],
                float(durations_s[i]),
                float(durations_s[i + 1]),
            )
        )

    def _incoming(i: int) -> AppliedTransition | None:
        return applied[i - 1] if i > 0 else None

    def _outgoing(i: int) -> AppliedTransition | None:
        return applied[i] if i < n - 1 else None

    for i in range(n):
        d_i = float(durations_s[i])
        incoming = _incoming(i)
        outgoing = _outgoing(i)
        occ_in = occupancy_s(incoming.type, incoming.duration_s) if incoming else 0.0
        occ_out = occupancy_s(outgoing.type, outgoing.duration_s) if outgoing else 0.0
        budget = d_i - MIN_OUTSIDE_S
        if occ_in + occ_out <= budget + 1e-9:
            continue
        if outgoing is not None and outgoing.type != TYPE_CUT:
            applied[i] = _cut_applied(
                outgoing.stored_type,
                outgoing.stored_duration_s,
                fallback_cut=True,
                clamped=outgoing.clamped,
            )
            occ_out = 0.0
        if occ_in + occ_out <= budget + 1e-9:
            continue
        if incoming is not None and incoming.type != TYPE_CUT:
            applied[i - 1] = _cut_applied(
                incoming.stored_type,
                incoming.stored_duration_s,
                fallback_cut=True,
                clamped=incoming.clamped,
            )
    return applied


def story_length_s(
    durations_s: Sequence[float],
    applied: Sequence[AppliedTransition],
) -> float:
    """Cut/fade-black: sum(items). Crossfade subtracts each applied overlap D."""
    total = sum(max(0.0, float(d)) for d in durations_s)
    for boundary in applied:
        if boundary.is_crossfade:
            total -= boundary.duration_s
    return max(0.0, total)


def story_starts_s(
    durations_s: Sequence[float],
    applied: Sequence[AppliedTransition],
) -> list[float]:
    """Story-time start of each clip (next clip starts D early on crossfade)."""
    n = len(durations_s)
    starts = [0.0] * n
    cursor = 0.0
    for i, raw in enumerate(durations_s):
        starts[i] = cursor
        cursor += max(0.0, float(raw))
        if i < len(applied) and applied[i].is_crossfade:
            cursor -= applied[i].duration_s
    return starts


def clip_flex_s(duration_s: float, outgoing: AppliedTransition | None) -> float:
    """Story-track tile width: shrink by outgoing crossfade overlap only."""
    d = max(0.0, float(duration_s))
    if outgoing is not None and outgoing.is_crossfade:
        return max(0.0, d - outgoing.duration_s)
    return d


def fade_in_s(incoming: AppliedTransition | None) -> float:
    if incoming is not None and incoming.is_fade_black:
        return incoming.duration_s / 2.0
    return 0.0


def fade_out_s(outgoing: AppliedTransition | None) -> float:
    if outgoing is not None and outgoing.is_fade_black:
        return outgoing.duration_s / 2.0
    return 0.0


@dataclass(frozen=True)
class StoryTimeHit:
    """Active Story clip(s) for a global story time (preview/export playhead)."""

    index: int
    start_s: float
    duration_s: float
    local_s: float
    at_end: bool
    overlap_index: int | None = None
    overlap_local_s: float | None = None
    overlap_start_s: float | None = None
    crossfade_progress: float | None = None
    fade_black_opacity: float = 0.0


def resolve_story_time(
    durations_s: Sequence[float],
    applied: Sequence[AppliedTransition],
    story_time_s: float,
) -> StoryTimeHit | None:
    """Map story time to primary clip, optional crossfade partner, fade overlay."""
    n = len(durations_s)
    if n == 0:
        return None
    starts = story_starts_s(durations_s, applied)
    total = story_length_s(durations_s, applied)
    t = max(0.0, float(story_time_s))
    if total <= 0:
        return None

    def _hit(
        index: int,
        *,
        at_end: bool,
        local: float | None = None,
        overlap_index: int | None = None,
        overlap_local: float | None = None,
        overlap_start: float | None = None,
        crossfade_progress: float | None = None,
        fade_black_opacity: float = 0.0,
    ) -> StoryTimeHit:
        start = starts[index]
        dur = float(durations_s[index])
        local_s = dur if local is None else max(0.0, min(dur, local))
        return StoryTimeHit(
            index=index,
            start_s=start,
            duration_s=dur,
            local_s=local_s,
            at_end=at_end,
            overlap_index=overlap_index,
            overlap_local_s=overlap_local,
            overlap_start_s=overlap_start,
            crossfade_progress=crossfade_progress,
            fade_black_opacity=fade_black_opacity,
        )

    if t >= total:
        last = n - 1
        return _hit(last, at_end=True, local=float(durations_s[last]))

    primary: int | None = None
    for i in range(n):
        start = starts[i]
        end = start + float(durations_s[i])
        if start <= t < end - 1e-9:
            primary = i
        elif abs(t - start) < 1e-9:
            primary = i
    if primary is None:
        # Between clips (should not happen) or exactly on a non-overlap edge.
        for i in range(n - 1, -1, -1):
            if starts[i] <= t:
                primary = i
                break
    if primary is None:
        primary = 0

    start = starts[primary]
    dur = float(durations_s[primary])
    local = t - start
    incoming = applied[primary - 1] if primary > 0 else None
    outgoing = applied[primary] if primary < n - 1 else None

    fade_opacity = 0.0
    if outgoing is not None and outgoing.is_fade_black:
        half = outgoing.duration_s / 2.0
        fade_start = dur - half
        if local >= fade_start:
            fade_opacity = 0.0 if half <= 0 else min(1.0, (local - fade_start) / half)
    if incoming is not None and incoming.is_fade_black:
        half = incoming.duration_s / 2.0
        if local <= half:
            fade_opacity = 1.0 if half <= 0 else max(fade_opacity, 1.0 - (local / half))

    overlap_index = None
    overlap_local = None
    overlap_start = None
    progress = None
    if incoming is not None and incoming.is_crossfade:
        d = incoming.duration_s
        into = t - start
        if d > 0 and into <= d + 1e-9:
            overlap_index = primary - 1
            overlap_start = starts[overlap_index]
            overlap_local = t - overlap_start
            progress = min(1.0, max(0.0, into / d))
    elif outgoing is not None and outgoing.is_crossfade:
        next_start = starts[primary + 1]
        if t >= next_start:
            overlap_index = primary + 1
            overlap_start = next_start
            overlap_local = t - next_start
            d = outgoing.duration_s
            progress = 0.0 if d <= 0 else min(1.0, max(0.0, (t - next_start) / d))
            # Incoming is visually on top; treat it as primary for the playhead.
            return _hit(
                primary + 1,
                at_end=False,
                local=overlap_local,
                overlap_index=primary,
                overlap_local=local,
                overlap_start=start,
                crossfade_progress=progress,
                fade_black_opacity=0.0,
            )

    return _hit(
        primary,
        at_end=False,
        local=local,
        overlap_index=overlap_index,
        overlap_local=overlap_local,
        overlap_start=overlap_start,
        crossfade_progress=progress,
        fade_black_opacity=fade_opacity,
    )


def item_effective_seconds(item: object) -> float | None:
    """Duration used on estimate/preview surfaces (skip unavailable video)."""
    from orga_drone.studio_estimate import effective_seconds

    kind = getattr(item, "kind", None) or "unknown"
    return effective_seconds(
        kind=kind,
        photo_duration_s=getattr(item, "photo_duration_s", None),
        duration_s=getattr(item, "duration_s", None),
        available=bool(getattr(item, "available", False)),
        source_in_s=getattr(item, "source_in_s", None),
        source_out_s=getattr(item, "source_out_s", None),
        card_duration_s=getattr(item, "card_duration_s", None),
    )


def apply_for_items(items: Iterable[object]) -> tuple[list[float], list[AppliedTransition], list[int]]:
    """Apply transitions to items with a positive effective duration.

    Returns ``(durations, applied, source_indexes)`` where ``source_indexes``
    maps sequence positions back to the original item list.
    """
    durations: list[float] = []
    types: list[str | None] = []
    durs: list[float | None] = []
    indexes: list[int] = []
    for idx, item in enumerate(items):
        seconds = item_effective_seconds(item)
        if seconds is None or seconds <= 0:
            continue
        durations.append(float(seconds))
        types.append(getattr(item, "transition", None))
        raw_d = getattr(item, "transition_duration_s", None)
        durs.append(float(raw_d) if raw_d is not None else None)
        indexes.append(idx)
    applied = apply_boundaries(durations, types, durs)
    return durations, applied, indexes
