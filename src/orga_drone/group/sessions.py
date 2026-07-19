"""Group clips into flight sessions (takeoff → landing), beyond FAT32 flows.

Sessions nest flows: split parts of one recording always share a session.
Heuristics use recording timestamps and optional SRT altitude samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# --- Tunable thresholds (documented for operators / future UI) ---

# Always keep clips in the same session when the idle gap is at most this long.
SESSION_SOFT_GAP_SECONDS = 3 * 60

# Hard upper bound: never join clips across a longer idle gap.
SESSION_MAX_GAP_SECONDS = 20 * 60

# Relative altitude (m) treated as "near ground" for takeoff/landing hints.
SESSION_LANDING_REL_ALT_M = 5.0

# Photos within this window of a session's time span may attach (nice-to-have).
SESSION_PHOTO_ATTACH_SECONDS = 5 * 60

# How many track samples at each end to average for altitude / GPS stability.
_TRACK_EDGE_SAMPLES = 5
_GPS_STABLE_DEG = 0.0003  # ~30 m; start/end cluster within this → "landed" hint


@dataclass
class ClipForSession:
    media_id: int
    recorded_at: datetime | None
    duration_s: float | None
    flow_id: int | None
    size_bytes: int
    start_rel_alt: float | None = None
    end_rel_alt: float | None = None
    start_lat: float | None = None
    start_lon: float | None = None
    end_lat: float | None = None
    end_lon: float | None = None


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def altitude_edges_from_track(
    track: list[dict[str, Any]] | None,
) -> tuple[float | None, float | None, float | None, float | None, float | None, float | None]:
    """Return (start_rel, end_rel, start_lat, start_lon, end_lat, end_lon) from SRT track."""
    if not track:
        return None, None, None, None, None, None

    start_slice = track[:_TRACK_EDGE_SAMPLES]
    end_slice = track[-_TRACK_EDGE_SAMPLES:]

    start_rels = [float(p["rel_alt"]) for p in start_slice if p.get("rel_alt") is not None]
    end_rels = [float(p["rel_alt"]) for p in end_slice if p.get("rel_alt") is not None]
    start_lats = [float(p["lat"]) for p in start_slice if p.get("lat") is not None]
    start_lons = [float(p["lon"]) for p in start_slice if p.get("lon") is not None]
    end_lats = [float(p["lat"]) for p in end_slice if p.get("lat") is not None]
    end_lons = [float(p["lon"]) for p in end_slice if p.get("lon") is not None]

    return (
        _avg(start_rels),
        _avg(end_rels),
        _avg(start_lats),
        _avg(start_lons),
        _avg(end_lats),
        _avg(end_lons),
    )


def _near_ground(rel_alt: float | None) -> bool:
    return rel_alt is not None and rel_alt <= SESSION_LANDING_REL_ALT_M


def _gps_stable(clip: ClipForSession) -> bool:
    if None in (clip.start_lat, clip.start_lon, clip.end_lat, clip.end_lon):
        return False
    return (
        abs(clip.start_lat - clip.end_lat) <= _GPS_STABLE_DEG
        and abs(clip.start_lon - clip.end_lon) <= _GPS_STABLE_DEG
        and _near_ground(clip.start_rel_alt)
        and _near_ground(clip.end_rel_alt)
    )


def _clip_end_time(clip: ClipForSession) -> datetime | None:
    if clip.recorded_at is None:
        return None
    if clip.duration_s is not None and clip.duration_s > 0:
        from datetime import timedelta

        return clip.recorded_at + timedelta(seconds=float(clip.duration_s))
    return clip.recorded_at


def _idle_gap_seconds(prev: ClipForSession, current: ClipForSession) -> float | None:
    if prev.recorded_at is None or current.recorded_at is None:
        return None
    end = _clip_end_time(prev)
    if end is None:
        return None
    gap = (current.recorded_at - end).total_seconds()
    # Overlap / same second (typical for split flows) → treat as continuous.
    return max(0.0, gap)


def should_continue_session(prev: ClipForSession, current: ClipForSession) -> bool:
    """Decide whether current belongs to the same flight session as prev."""
    # FAT32 flow members always stay together.
    if (
        prev.flow_id is not None
        and current.flow_id is not None
        and prev.flow_id == current.flow_id
    ):
        return True

    gap = _idle_gap_seconds(prev, current)
    if gap is None:
        return False
    if gap > SESSION_MAX_GAP_SECONDS:
        return False
    if gap <= SESSION_SOFT_GAP_SECONDS:
        return True

    # Soft < gap ≤ max: use SRT landing hints when available.
    prev_landed = _near_ground(prev.end_rel_alt) or _gps_stable(prev)
    current_on_ground = _near_ground(current.start_rel_alt)

    if prev_landed and current_on_ground:
        # Clear takeoff→landing break between recordings → new session.
        return False

    if prev.end_rel_alt is not None and not _near_ground(prev.end_rel_alt):
        # Still airborne at end of previous clip → same flight.
        return True

    if current.start_rel_alt is not None and not _near_ground(current.start_rel_alt):
        # Next clip starts already airborne → continuation.
        return True

    # No decisive altitude: join within the hard gap window.
    return True


def group_clips_into_sessions(clips: list[ClipForSession]) -> list[list[int]]:
    """Return ordered sessions; each session is an ordered list of media_ids."""
    ordered = sorted(
        clips,
        key=lambda c: (
            c.recorded_at or datetime.min,
            c.media_id,
        ),
    )
    if not ordered:
        return []

    # Ensure entire flows stay contiguous: expand so we never split a flow.
    by_flow: dict[int, list[ClipForSession]] = {}
    for clip in ordered:
        if clip.flow_id is not None:
            by_flow.setdefault(clip.flow_id, []).append(clip)

    # Rebuild order as flow-blocks + singles while preserving time order of first clip.
    seen_flows: set[int] = set()
    blocks: list[list[ClipForSession]] = []
    for clip in ordered:
        if clip.flow_id is not None and clip.flow_id in by_flow:
            if clip.flow_id in seen_flows:
                continue
            seen_flows.add(clip.flow_id)
            flow_clips = sorted(
                by_flow[clip.flow_id],
                key=lambda c: (c.recorded_at or datetime.min, c.media_id),
            )
            blocks.append(flow_clips)
        else:
            blocks.append([clip])

    if not blocks:
        return []

    sessions: list[list[ClipForSession]] = [list(blocks[0])]
    for block in blocks[1:]:
        prev = sessions[-1][-1]
        first = block[0]
        if should_continue_session(prev, first):
            sessions[-1].extend(block)
        else:
            sessions.append(list(block))

    return [[c.media_id for c in s] for s in sessions]


def attach_photos_to_sessions(
    sessions: list[list[int]],
    video_lookup: dict[int, ClipForSession],
    photos: list[ClipForSession],
) -> list[list[int]]:
    """Optionally append nearby photos into session media_id lists (by time)."""
    if not photos or not sessions:
        return sessions

    enriched: list[list[int]] = [list(ids) for ids in sessions]
    used: set[int] = set()

    for idx, ids in enumerate(sessions):
        clips = [video_lookup[mid] for mid in ids if mid in video_lookup]
        starts = [c.recorded_at for c in clips if c.recorded_at is not None]
        ends = [_clip_end_time(c) for c in clips]
        ends_ok = [e for e in ends if e is not None]
        if not starts or not ends_ok:
            continue
        window_start = min(starts)
        window_end = max(ends_ok)
        from datetime import timedelta

        lo = window_start - timedelta(seconds=SESSION_PHOTO_ATTACH_SECONDS)
        hi = window_end + timedelta(seconds=SESSION_PHOTO_ATTACH_SECONDS)
        for photo in photos:
            if photo.media_id in used or photo.recorded_at is None:
                continue
            if lo <= photo.recorded_at <= hi:
                enriched[idx].append(photo.media_id)
                used.add(photo.media_id)

    return enriched
