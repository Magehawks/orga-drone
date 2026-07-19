"""Helpers for clip vs complete-flight detail views."""

from __future__ import annotations

from typing import Any

from orga_drone.db import MediaRow, track_from_json
from orga_drone.media_files import resolve_media_file, resolve_proxy_file


def normalize_detail_tab(tab: str | None) -> str:
    value = (tab or "clip").strip().lower()
    return value if value in {"clip", "flight"} else "clip"


def concat_clip_tracks(clips: list[MediaRow]) -> tuple[list[dict[str, Any]], float]:
    """Concatenate per-clip SRT tracks with cumulative time offsets.

    Returns (combined_track, total_duration_s). Only video clips contribute.
    """
    combined: list[dict[str, Any]] = []
    offset = 0.0
    for clip in clips:
        if clip.kind != "video":
            continue
        raw = track_from_json(clip.track_json)
        dur = float(clip.duration_s) if clip.duration_s is not None else None
        local_span = 0.0
        if raw:
            ts = [p.get("t") for p in raw]
            has_t = all(isinstance(t, (int, float)) for t in ts)
            if has_t:
                local_span = max((float(t) for t in ts), default=0.0)
                for p in raw:
                    point = dict(p)
                    point["t"] = float(p["t"]) + offset
                    combined.append(point)
            else:
                local_span = dur or 0.0
                n = len(raw)
                for i, p in enumerate(raw):
                    point = dict(p)
                    if n > 1 and local_span > 0:
                        point["t"] = offset + local_span * i / (n - 1)
                    else:
                        point["t"] = offset
                    combined.append(point)
        clip_len = dur if dur is not None and dur > 0 else local_span
        offset += clip_len
    return combined, offset


def build_flight_playlist(db: Any, clips: list[MediaRow]) -> list[dict[str, Any]]:
    """Ordered playlist entries for sequential flight playback (videos only)."""
    entries: list[dict[str, Any]] = []
    for clip in clips:
        if clip.kind != "video":
            continue
        can_play = resolve_media_file(db, clip) is not None
        has_proxy = resolve_proxy_file(db, clip) is not None if can_play else False
        entries.append(
            {
                "id": clip.id,
                "filename": clip.filename,
                "duration_s": float(clip.duration_s) if clip.duration_s is not None else None,
                "size_bytes": clip.size_bytes,
                "can_play": can_play,
                "has_proxy": has_proxy,
                "proxy_url": f"/media/{clip.id}/proxy",
                "stream_url": f"/media/{clip.id}/stream",
                "thumb_url": f"/media/{clip.id}/thumb",
                "detail_url": f"/media/{clip.id}",
            }
        )
    return entries


def flight_map_center(
    item: MediaRow,
    flight_items: list[MediaRow],
    flight_track: list[dict[str, Any]],
) -> tuple[float | None, float | None]:
    """Prefer current item GPS, else first track point, else any clip GPS."""
    if item.latitude is not None and item.longitude is not None:
        return item.latitude, item.longitude
    if flight_track:
        first = flight_track[0]
        lat, lon = first.get("lat"), first.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon)
    for clip in flight_items:
        if clip.latitude is not None and clip.longitude is not None:
            return clip.latitude, clip.longitude
    return None, None
