"""Repeat one video section forward until a known soundtrack ends.

This is the inverse of the single-song "loop to Story end" bed. The soundtrack
plays once. The selected section repeats forward, and the last play is trimmed
so the story matches that once-through duration. The original media file is
never modified.

Joins are hard cuts unless the clip asks for a forward crossfade or a longer
cinematic blend. That blend overlaps the end of one play with the start of the
next. Both plays keep moving forward. A smooth curve eases the incoming
picture in. It does not match frames, reverse, or fade through black. A long
blend can show the same object twice when the views differ.
The overlap shortens the story time each extra play adds. The soundtrack is
not blended and is not restarted at a join.

A remainder shorter than ``MIN_SEGMENT_S`` (0.05s, the shortest span a cut or
an exact encode keeps) is omitted. Other agreement is within
``FORWARD_LOOP_TOLERANCE_S`` (0.001s), the same epsilon the preview uses when
it wraps a repeated section. Export prints slice times to 3 decimal places.

The count is derived when the story is measured. It is not stored, and it is
not guessed when any soundtrack duration is missing. The manual 1–8 repeat
count is a separate control and stays capped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from orga_drone.studio_cut import MIN_SEGMENT_S

LOOP_TO_SOUNDTRACK_KEY = "loop_to_soundtrack"
LOOP_TRANSITION_KEY = "loop_transition"
LOOP_TRANSITION_S_KEY = "loop_transition_s"
LOOP_TRANSITION_CROSSFADE = "crossfade"
LOOP_TRANSITION_MATCH = "match"
LOOP_TRANSITION_CINEMATIC = "cinematic"
LOOP_TRANSITION_CURVE_KEY = "loop_transition_curve"
LOOP_CURVE_LINEAR = "linear"
LOOP_CURVE_SMOOTH = "smooth"
# Crossfade and smart matching stay on the short range. Cinematic blend may
# run longer. A short section still clamps either one.
LOOP_TRANSITION_MIN_S = 0.5
LOOP_TRANSITION_MAX_S = 2.0
LOOP_CINEMATIC_MAX_S = 5.0
LOOP_TRANSITION_DEFAULT_S = 1.0
# Preview wrap epsilon in studio.js (`local >= span - 0.001`).
FORWARD_LOOP_TOLERANCE_S = 0.001
# One encode per play. Past this, the action is refused instead of truncating
# the soundtrack to a guessed shorter story.
MAX_FORWARD_LOOP_PLAYS = 240


@dataclass(frozen=True)
class ForwardLoopPlan:
    """How one in/out range fills a target output duration."""

    cycle_s: float
    target_s: float
    full_plays: int
    partial_s: float
    total_s: float
    # Story time removed at each join. 0 is a hard cut. ``partial_s`` is the
    # last play's source length, which includes this overlap when it is the
    # incoming side of a crossfade.
    overlap_s: float = 0.0

    @property
    def play_count(self) -> int:
        return self.full_plays + (1 if self.partial_s > 0 else 0)

    def output_spans(self) -> tuple[float, ...]:
        spans = [self.cycle_s] * self.full_plays
        if self.partial_s > 0:
            spans.append(self.partial_s)
        return tuple(spans)


@dataclass(frozen=True)
class ForwardLoopResolution:
    """The one clip, if any, that is allowed to fill the soundtrack."""

    item_id: int | None
    requested: bool
    active: bool
    reason: str
    cycle_s: float | None = None
    total_s: float | None = None
    plan: ForwardLoopPlan | None = None

    @property
    def overrides(self) -> dict[int, float]:
        if self.active and self.item_id is not None and self.total_s is not None:
            return {int(self.item_id): float(self.total_s)}
        return {}


def loop_to_soundtrack_enabled(raw: str | None) -> bool:
    """True only for a JSON boolean. Missing or bad values stay off."""
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    return parsed.get(LOOP_TO_SOUNDTRACK_KEY) is True


def dump_loop_to_soundtrack(existing: str | None, enabled: bool) -> str:
    """Store the flag and keep unrelated effect_settings keys.

    Off omits the key so ordinary clips stay unchanged.
    """
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    if enabled:
        data[LOOP_TO_SOUNDTRACK_KEY] = True
    else:
        data.pop(LOOP_TO_SOUNDTRACK_KEY, None)
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _effect_dict(raw: str | None) -> dict[str, object]:
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def loop_transition_choice(raw: str | None) -> str:
    """``crossfade``, ``cinematic``, ``match``, or ``off``. Anything else stays off."""
    stored = _effect_dict(raw).get(LOOP_TRANSITION_KEY)
    if stored in {
        LOOP_TRANSITION_CROSSFADE,
        LOOP_TRANSITION_MATCH,
        LOOP_TRANSITION_CINEMATIC,
    }:
        return str(stored)
    return "off"


def loop_transition_maximum_s(choice: str) -> float:
    """Cinematic blend accepts up to 5 s. The short crossfade stays at 2 s."""
    if choice == LOOP_TRANSITION_CINEMATIC:
        return LOOP_CINEMATIC_MAX_S
    return LOOP_TRANSITION_MAX_S


def coerce_loop_transition_s(
    value: object, *, maximum: float = LOOP_TRANSITION_MAX_S
) -> float:
    """Store a duration inside 0.5 s and ``maximum``. Invalid values use 1.0 s."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return LOOP_TRANSITION_DEFAULT_S
    if number < LOOP_TRANSITION_MIN_S:
        return LOOP_TRANSITION_MIN_S
    if number > maximum:
        return maximum
    return number


def loop_transition_requested_s(raw: str | None) -> float:
    """The stored request, or 1.0 s when the clip has not chosen one."""
    data = _effect_dict(raw)
    maximum = loop_transition_maximum_s(loop_transition_choice(raw))
    if LOOP_TRANSITION_S_KEY not in data:
        return LOOP_TRANSITION_DEFAULT_S
    return coerce_loop_transition_s(data.get(LOOP_TRANSITION_S_KEY), maximum=maximum)


def loop_transition_curve(raw: str | None) -> str:
    """``smooth`` only for a cinematic blend that asked for it. Otherwise linear."""
    if loop_transition_choice(raw) != LOOP_TRANSITION_CINEMATIC:
        return LOOP_CURVE_LINEAR
    stored = _effect_dict(raw).get(LOOP_TRANSITION_CURVE_KEY)
    if stored == LOOP_CURVE_LINEAR:
        return LOOP_CURVE_LINEAR
    return LOOP_CURVE_SMOOTH


def applied_loop_overlap_s(
    cycle_s: float,
    requested_s: float,
    *,
    maximum: float = LOOP_TRANSITION_MAX_S,
) -> float:
    """Overlap that still leaves a unique slice of the section.

    Returns 0 when the section cannot hold a blend. The result may be
    below 0.5 s so a short section is clamped instead of guessed longer.
    """
    cycle = float(cycle_s)
    if cycle < MIN_SEGMENT_S * 2:
        return 0.0
    cap = cycle - MIN_SEGMENT_S
    applied = min(coerce_loop_transition_s(requested_s, maximum=maximum), cap)
    if applied < MIN_SEGMENT_S:
        return 0.0
    return applied


def dump_loop_transition(
    existing: str | None,
    choice: str,
    duration_s: float,
    curve: str | None = None,
) -> str:
    """Store the loop join. Off omits the type. The default duration is omitted.

    The soundtrack flag is left untouched. Manual repeats and the soundtrack
    loop share this setting. The curve is stored only for a cinematic blend.
    """
    data = _effect_dict(existing)
    maximum = loop_transition_maximum_s(choice)
    coerced = round(coerce_loop_transition_s(duration_s, maximum=maximum), 3)
    if choice in {
        LOOP_TRANSITION_CROSSFADE,
        LOOP_TRANSITION_MATCH,
        LOOP_TRANSITION_CINEMATIC,
    }:
        data[LOOP_TRANSITION_KEY] = choice
        data[LOOP_TRANSITION_S_KEY] = coerced
        if choice == LOOP_TRANSITION_CINEMATIC:
            data[LOOP_TRANSITION_CURVE_KEY] = (
                LOOP_CURVE_LINEAR if curve == LOOP_CURVE_LINEAR else LOOP_CURVE_SMOOTH
            )
        else:
            data.pop(LOOP_TRANSITION_CURVE_KEY, None)
    else:
        data.pop(LOOP_TRANSITION_KEY, None)
        data.pop(LOOP_TRANSITION_CURVE_KEY, None)
        if abs(coerced - LOOP_TRANSITION_DEFAULT_S) < 1e-6:
            data.pop(LOOP_TRANSITION_S_KEY, None)
        else:
            data[LOOP_TRANSITION_S_KEY] = coerced
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def applied_join_s(raw: str | None, cycle_s: float, *, path: Path | None = None, source_in_s: float | None = None, source_out_s: float | None = None) -> float:
    """Overlap used between plays. Off and a weak match stay hard cuts."""
    choice = loop_transition_choice(raw)
    if choice == "off":
        return 0.0
    requested = loop_transition_requested_s(raw)
    if choice == LOOP_TRANSITION_MATCH:
        from orga_drone.studio_loop_match import match_is_applied, match_record

        if not match_is_applied(
            raw, source_in_s=source_in_s, source_out_s=source_out_s, path=path
        ):
            return 0.0
        record = match_record(raw) or {}
        fade_raw = record.get("crossfade_s")
        fade = float(fade_raw) if isinstance(fade_raw, int | float) else 0.0
        if fade <= 0:
            return 0.0
        requested = min(requested, fade)
    return applied_loop_overlap_s(
        cycle_s,
        requested,
        maximum=loop_transition_maximum_s(choice),
    )


def without_loop_to_soundtrack(existing: str | None) -> str:
    """Drop the soundtrack flag. The loop effect stays with the clip."""
    data = _effect_dict(existing)
    if data.get(LOOP_TO_SOUNDTRACK_KEY) is not True:
        return existing if existing else "{}"
    data.pop(LOOP_TO_SOUNDTRACK_KEY, None)
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def plan_forward_loop(
    cycle_s: float,
    target_s: float,
    overlap_s: float = 0.0,
) -> ForwardLoopPlan | None:
    """Full plays plus one trimmed last play.

    Returns ``None`` when the cycle or the target is below ``MIN_SEGMENT_S``.
    A leftover shorter than that minimum is dropped. A leftover within
    ``FORWARD_LOOP_TOLERANCE_S`` of 0 or of a full cycle is absorbed so the
    story does not gain a dust slice.

    ``overlap_s`` is the applied crossfade. Each extra play then adds
    ``cycle - overlap`` story seconds. ``total_s`` is that story length.
    ``partial_s`` stays the last play's source length. Zero overlap keeps
    the hard-cut plan.
    """
    cycle = float(cycle_s)
    target = float(target_s)
    if cycle < MIN_SEGMENT_S or target < MIN_SEGMENT_S:
        return None
    overlap = float(overlap_s or 0.0)
    if overlap > 0:
        overlap = min(overlap, cycle - MIN_SEGMENT_S)
    if overlap < MIN_SEGMENT_S:
        overlap = 0.0
    if overlap > 0:
        return _plan_forward_crossfade(cycle, target, overlap)
    if target <= cycle + FORWARD_LOOP_TOLERANCE_S:
        if target + FORWARD_LOOP_TOLERANCE_S >= cycle:
            return ForwardLoopPlan(
                cycle_s=cycle,
                target_s=target,
                full_plays=1,
                partial_s=0.0,
                total_s=cycle,
            )
        return ForwardLoopPlan(
            cycle_s=cycle,
            target_s=target,
            full_plays=0,
            partial_s=target,
            total_s=target,
        )
    full = int(target // cycle)
    remainder = target - (full * cycle)
    if remainder <= FORWARD_LOOP_TOLERANCE_S or cycle - remainder <= FORWARD_LOOP_TOLERANCE_S:
        plays = full if remainder <= FORWARD_LOOP_TOLERANCE_S else full + 1
        if plays < 1:
            return None
        return ForwardLoopPlan(
            cycle_s=cycle,
            target_s=target,
            full_plays=plays,
            partial_s=0.0,
            total_s=plays * cycle,
        )
    if remainder < MIN_SEGMENT_S:
        if full < 1:
            return None
        return ForwardLoopPlan(
            cycle_s=cycle,
            target_s=target,
            full_plays=full,
            partial_s=0.0,
            total_s=full * cycle,
        )
    return ForwardLoopPlan(
        cycle_s=cycle,
        target_s=target,
        full_plays=full,
        partial_s=remainder,
        total_s=(full * cycle) + remainder,
    )


def _plan_forward_crossfade(
    cycle: float,
    target: float,
    overlap: float,
) -> ForwardLoopPlan | None:
    """Fill ``target`` story seconds. Each join removes ``overlap`` seconds."""
    if target <= cycle + FORWARD_LOOP_TOLERANCE_S:
        if target + FORWARD_LOOP_TOLERANCE_S >= cycle:
            return ForwardLoopPlan(
                cycle_s=cycle,
                target_s=target,
                full_plays=1,
                partial_s=0.0,
                total_s=cycle,
                overlap_s=overlap,
            )
        return ForwardLoopPlan(
            cycle_s=cycle,
            target_s=target,
            full_plays=0,
            partial_s=target,
            total_s=target,
            overlap_s=0.0,
        )
    step = cycle - overlap
    remaining = target - cycle
    if remaining <= FORWARD_LOOP_TOLERANCE_S:
        return ForwardLoopPlan(
            cycle_s=cycle,
            target_s=target,
            full_plays=1,
            partial_s=0.0,
            total_s=cycle,
            overlap_s=overlap,
        )
    extra = int(remaining // step)
    leftover = remaining - (extra * step)
    if leftover < 0:
        extra = max(0, extra - 1)
        leftover = remaining - (extra * step)
    if abs(leftover) <= FORWARD_LOOP_TOLERANCE_S:
        leftover = 0.0
    if leftover <= FORWARD_LOOP_TOLERANCE_S or step - leftover <= FORWARD_LOOP_TOLERANCE_S:
        if step - leftover <= FORWARD_LOOP_TOLERANCE_S and leftover > FORWARD_LOOP_TOLERANCE_S:
            extra += 1
        total = cycle + (extra * step)
        return ForwardLoopPlan(
            cycle_s=cycle,
            target_s=target,
            full_plays=1 + extra,
            partial_s=0.0,
            total_s=total,
            overlap_s=overlap,
        )
    if leftover < MIN_SEGMENT_S:
        total = cycle + (extra * step)
        return ForwardLoopPlan(
            cycle_s=cycle,
            target_s=target,
            full_plays=1 + extra,
            partial_s=0.0,
            total_s=total,
            overlap_s=overlap,
        )
    partial = leftover + overlap
    if partial >= cycle - FORWARD_LOOP_TOLERANCE_S:
        total = cycle + ((extra + 1) * step)
        return ForwardLoopPlan(
            cycle_s=cycle,
            target_s=target,
            full_plays=2 + extra,
            partial_s=0.0,
            total_s=total,
            overlap_s=overlap,
        )
    return ForwardLoopPlan(
        cycle_s=cycle,
        target_s=target,
        full_plays=1 + extra,
        partial_s=partial,
        total_s=cycle + (extra * step) + leftover,
        overlap_s=overlap,
    )


def soundtrack_once_s(tracks: Sequence[object]) -> float | None:
    """Once-through playlist length.

    Every song must exist on disk and have a stored duration above zero.
    The sum is that length. A missing file or an unknown duration makes the
    whole soundtrack unknown. This is not the single-song loop that stretches
    one file to the Story end.
    """
    if not tracks:
        return None
    total = 0.0
    for track in tracks:
        duration = getattr(track, "duration_s", None)
        path_raw = getattr(track, "file_path", None)
        try:
            duration_s = float(duration) if duration is not None else 0.0
        except (TypeError, ValueError):
            return None
        if duration_s <= 0 or not path_raw:
            return None
        path = Path(str(path_raw))
        if not path.is_file():
            return None
        total += duration_s
    return total if total > 0 else None


def _playback_bounds(item: object) -> tuple[float | None, float | None, Path | None]:
    """Source range used for plays. A confident seam can narrow it."""
    from orga_drone.studio_loop_match import effective_source_bounds

    raw = getattr(item, "effect_settings", None)
    settings = raw if isinstance(raw, str) else None
    start = getattr(item, "source_in_s", None)
    if start is None:
        start = getattr(item, "source_start", None)
    end = getattr(item, "source_out_s", None)
    if end is None:
        end = getattr(item, "source_end", None)
    path_raw = getattr(item, "path", None) or getattr(item, "media_path", None)
    path = Path(str(path_raw)) if path_raw else None
    bounded_in, bounded_out = effective_source_bounds(
        settings,
        source_in_s=float(start) if start is not None else None,
        source_out_s=float(end) if end is not None else None,
        path=path if path is not None and path.is_file() else None,
    )
    return bounded_in, bounded_out, path if path is not None and path.is_file() else None


def _cycle_s(item: object) -> float | None:
    from orga_drone.studio_estimate import effective_seconds

    if (getattr(item, "kind", None) or "") != "video":
        return None
    if not bool(getattr(item, "available", False)):
        return None
    start, end, _path = _playback_bounds(item)
    return effective_seconds(
        kind="video",
        photo_duration_s=getattr(item, "photo_duration_s", None),
        duration_s=getattr(item, "duration_s", None),
        available=True,
        source_in_s=start,
        source_out_s=end,
        playback_speed=getattr(item, "playback_speed", None),
        section_repeats=1,
    )


def _story_target_s(
    items: Sequence[object],
    holder_id: int,
    soundtrack_s: float,
    cycle_s: float,
) -> float | None:
    """Output length the flagged clip needs so the story matches the soundtrack.

    Other clips keep their ordinary durations, including a 1–8 repeat.
    Crossfades are solved with the flagged clip treated as long, so the
    overlap depends on the neighbor and the stored transition, then the
    clip length is the value that brings the story back to the soundtrack.
    """
    from orga_drone.studio_transition import (
        apply_boundaries,
        item_effective_seconds,
        story_length_s,
    )

    if cycle_s < MIN_SEGMENT_S:
        return None
    placeholder = max(float(soundtrack_s), MIN_SEGMENT_S) + 1000.0
    durations: list[float] = []
    types: list[str | None] = []
    stored: list[float | None] = []
    found = False
    for item in items:
        item_id = getattr(item, "id", None)
        if item_id == holder_id:
            found = True
            durations.append(placeholder)
        else:
            seconds = item_effective_seconds(item)
            if seconds is None or seconds <= 0:
                continue
            durations.append(float(seconds))
        types.append(getattr(item, "transition", None))
        raw = getattr(item, "transition_duration_s", None)
        stored.append(float(raw) if raw is not None else None)
    if not found:
        return None
    applied = apply_boundaries(durations, types, stored)
    story = story_length_s(durations, applied)
    return placeholder + (float(soundtrack_s) - story)


def _item_settings(
    item: object,
    settings_override: tuple[int, str] | None,
) -> str | None:
    item_id = getattr(item, "id", None)
    if settings_override is not None and item_id == settings_override[0]:
        return settings_override[1]
    raw = getattr(item, "effect_settings", None)
    return raw if isinstance(raw, str) else None


def resolve_forward_loop(
    items: Iterable[object],
    soundtrack_once: float | None,
    *,
    assume_item_id: int | None = None,
    settings_override: tuple[int, str] | None = None,
) -> ForwardLoopResolution:
    """Derive the forward loop. Does not persist a duration.

    ``assume_item_id`` treats that clip as flagged so a save can refuse an
    inactive plan before anything is stored. The first flagged video in story
    order is the only one that can be active.
    """
    rows = list(items)
    flagged: list[int] = []
    for item in rows:
        item_id = getattr(item, "id", None)
        if not isinstance(item_id, int):
            continue
        kind = getattr(item, "kind", None) or ""
        requested = loop_to_soundtrack_enabled(_item_settings(item, settings_override))
        if item_id == assume_item_id or requested:
            if kind != "video" and item_id == assume_item_id and not requested:
                return ForwardLoopResolution(
                    item_id=item_id,
                    requested=False,
                    active=False,
                    reason="forward_loop_video_only",
                )
            if kind == "video" or requested:
                flagged.append(item_id)
    if not flagged:
        return ForwardLoopResolution(
            item_id=None, requested=False, active=False, reason="off"
        )
    holder_id = flagged[0]
    holder = next((item for item in rows if getattr(item, "id", None) == holder_id), None)
    if holder is None or (getattr(holder, "kind", None) or "") != "video":
        return ForwardLoopResolution(
            item_id=holder_id,
            requested=True,
            active=False,
            reason="forward_loop_video_only",
        )
    cycle = _cycle_s(holder)
    if cycle is None:
        return ForwardLoopResolution(
            item_id=holder_id,
            requested=True,
            active=False,
            reason="unavailable",
            cycle_s=None,
        )
    if cycle < MIN_SEGMENT_S:
        return ForwardLoopResolution(
            item_id=holder_id,
            requested=True,
            active=False,
            reason="section_short",
            cycle_s=cycle,
        )
    if soundtrack_once is None or soundtrack_once <= 0:
        return ForwardLoopResolution(
            item_id=holder_id,
            requested=True,
            active=False,
            reason="unknown_duration",
            cycle_s=cycle,
        )
    target = _story_target_s(rows, holder_id, float(soundtrack_once), cycle)
    if target is None or target < MIN_SEGMENT_S:
        return ForwardLoopResolution(
            item_id=holder_id,
            requested=True,
            active=False,
            reason="story_filled",
            cycle_s=cycle,
        )
    holder_settings = _item_settings(holder, settings_override)
    _start, _end, media_path = _playback_bounds(holder)
    overlap = applied_join_s(
        holder_settings,
        cycle,
        path=media_path,
        source_in_s=getattr(holder, "source_in_s", None)
        if getattr(holder, "source_in_s", None) is not None
        else getattr(holder, "source_start", None),
        source_out_s=getattr(holder, "source_out_s", None)
        if getattr(holder, "source_out_s", None) is not None
        else getattr(holder, "source_end", None),
    )
    plan = plan_forward_loop(cycle, target, overlap)
    if plan is None:
        return ForwardLoopResolution(
            item_id=holder_id,
            requested=True,
            active=False,
            reason="section_short",
            cycle_s=cycle,
        )
    if plan.play_count > MAX_FORWARD_LOOP_PLAYS:
        return ForwardLoopResolution(
            item_id=holder_id,
            requested=True,
            active=False,
            reason="too_many_plays",
            cycle_s=cycle,
            plan=plan,
        )
    return ForwardLoopResolution(
        item_id=holder_id,
        requested=True,
        active=True,
        reason="active",
        cycle_s=cycle,
        total_s=plan.total_s,
        plan=plan,
    )


def rejection_reason(
    items: Iterable[object],
    soundtrack_once: float | None,
    item_id: int,
    *,
    settings_override: tuple[int, str] | None = None,
) -> str | None:
    """Why enabling the flag on ``item_id`` must be refused, or ``None``."""
    rows = list(items)
    for item in rows:
        if getattr(item, "id", None) == item_id:
            continue
        raw = getattr(item, "effect_settings", None)
        if loop_to_soundtrack_enabled(raw if isinstance(raw, str) else None):
            return "forward_loop_other_clip"
    resolution = resolve_forward_loop(
        rows,
        soundtrack_once,
        assume_item_id=item_id,
        settings_override=settings_override,
    )
    if resolution.item_id != item_id:
        return "forward_loop_other_clip"
    if not resolution.active:
        return resolution.reason
    return None


def _user_bounds(item: object) -> tuple[float | None, float | None, Path | None]:
    start = getattr(item, "source_in_s", None)
    if start is None:
        start = getattr(item, "source_start", None)
    end = getattr(item, "source_out_s", None)
    if end is None:
        end = getattr(item, "source_end", None)
    path_raw = getattr(item, "path", None) or getattr(item, "media_path", None)
    path = Path(str(path_raw)) if path_raw else None
    if path is not None and not path.is_file():
        path = None
    return (
        float(start) if start is not None else None,
        float(end) if end is not None else None,
        path,
    )


def _manual_overlap_s(item: object, settings: str | None) -> float:
    """Overlap between manual 1–8 plays. One play has no join."""
    from orga_drone.studio_cut import section_repeats_from_effect_settings

    repeats = section_repeats_from_effect_settings(settings)
    if repeats < 2:
        return 0.0
    cycle = _cycle_s(item)
    if cycle is None or cycle <= 0:
        return 0.0
    start, end, path = _user_bounds(item)
    return applied_join_s(
        settings, cycle, path=path, source_in_s=start, source_out_s=end
    )


def _loop_transition_view(
    item: object,
    resolution: ForwardLoopResolution,
) -> dict[str, object]:
    """Stored join plus the overlap the current repeats actually use."""
    from orga_drone.studio_loop_match import loop_match_key, match_is_applied, match_record

    raw = getattr(item, "effect_settings", None)
    settings = raw if isinstance(raw, str) else None
    choice = loop_transition_choice(settings)
    requested_s = loop_transition_requested_s(settings)
    item_id = getattr(item, "id", None)
    plan = resolution.plan if resolution.item_id == item_id else None
    active = bool(resolution.active and resolution.item_id == item_id and plan is not None)
    if active and plan is not None:
        overlap = float(plan.overlap_s)
        plays = int(plan.play_count)
        partial = float(plan.partial_s)
    else:
        overlap = _manual_overlap_s(item, settings)
        plays = 0
        partial = 0.0
    repeated = plays >= 2 or _manual_overlap_s(item, settings) > 0 or (
        not active and choice != "off"
    )
    clamped = bool(
        choice
        in {LOOP_TRANSITION_CROSSFADE, LOOP_TRANSITION_MATCH, LOOP_TRANSITION_CINEMATIC}
        and (plays >= 2 or overlap > 0)
        and overlap + FORWARD_LOOP_TOLERANCE_S < requested_s
        and overlap > 0
    )
    start, end, path = _user_bounds(item)
    record = match_record(settings)
    match_state = "off"
    match_in = start if start is not None else 0.0
    match_out = end if end is not None else 0.0
    if choice == LOOP_TRANSITION_MATCH:
        if match_is_applied(settings, source_in_s=start, source_out_s=end, path=path):
            match_state = "ok"
            if record is not None:
                in_raw = record.get("source_in_s")
                out_raw = record.get("source_out_s")
                if isinstance(in_raw, int | float):
                    match_in = float(in_raw)
                if isinstance(out_raw, int | float):
                    match_out = float(out_raw)
        elif record is not None and path is not None and start is not None and end is not None:
            key = loop_match_key(path, start, end)
            match_state = "stale" if record.get("key") not in {None, key} else "low"
        else:
            match_state = "low"
    return {
        "transition": choice,
        "transition_s": requested_s,
        "overlap_s": overlap,
        "plays": plays,
        "partial_s": partial,
        "clamped": clamped,
        "repeated": repeated,
        "match_state": match_state,
        "match_in_s": match_in,
        "match_out_s": match_out,
        "curve": loop_transition_curve(settings),
    }


def clip_forward_loop_view(
    item: object,
    resolution: ForwardLoopResolution,
    soundtrack_once: float | None,
) -> dict[str, object]:
    """Inspector state for one clip. Does not invent a duration."""
    kind = getattr(item, "kind", None) or ""
    item_id = getattr(item, "id", None)
    controls = _loop_transition_view(item, resolution)
    requested = kind == "video" and loop_to_soundtrack_enabled(
        getattr(item, "effect_settings", None)
        if isinstance(getattr(item, "effect_settings", None), str)
        else None
    )
    if kind != "video":
        return {"requested": False, "active": False, "reason": "off", **controls}
    if requested and resolution.item_id == item_id:
        return {
            "requested": True,
            "active": resolution.active,
            "reason": "active" if resolution.active else resolution.reason,
            **controls,
        }
    if resolution.item_id is not None and resolution.item_id != item_id:
        return {"requested": requested, "active": False, "reason": "other_clip", **controls}
    if soundtrack_once is None:
        return {
            "requested": False,
            "active": False,
            "reason": "unknown_duration",
            **controls,
        }
    return {"requested": False, "active": False, "reason": "ready", **controls}


def effective_item_seconds(
    item: object,
    items: Iterable[object],
    soundtrack_once: float | None,
) -> float | None:
    """Story seconds for one clip, including an active forward loop."""
    from orga_drone.studio_transition import item_effective_seconds

    rows = list(items)
    resolution = resolve_forward_loop(rows, soundtrack_once)
    if (
        resolution.active
        and resolution.item_id == getattr(item, "id", None)
        and resolution.total_s is not None
    ):
        return float(resolution.total_s)
    return item_effective_seconds(item)
