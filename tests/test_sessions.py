"""Tests for flight session grouping heuristics."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from orga_drone.db import Database
from orga_drone.group import (
    SESSION_MAX_GAP_SECONDS,
    SESSION_SOFT_GAP_SECONDS,
    ClipForSession,
    altitude_edges_from_track,
    attach_photos_to_sessions,
    group_clips_into_sessions,
    should_continue_session,
)


def _clip(
    mid: int,
    *,
    minutes: float = 0,
    duration_s: float = 60,
    flow_id: int | None = None,
    start_rel: float | None = None,
    end_rel: float | None = None,
) -> ClipForSession:
    base = datetime(2024, 6, 1, 10, 0, 0)
    return ClipForSession(
        media_id=mid,
        recorded_at=base + timedelta(minutes=minutes),
        duration_s=duration_s,
        flow_id=flow_id,
        size_bytes=1000,
        start_rel_alt=start_rel,
        end_rel_alt=end_rel,
    )


def test_soft_gap_keeps_same_session() -> None:
    a = _clip(1, minutes=0, duration_s=120)
    # Idle gap ~2 min (< soft 3 min)
    b = _clip(2, minutes=4, duration_s=60)
    assert should_continue_session(a, b)
    assert group_clips_into_sessions([a, b]) == [[1, 2]]


def test_hard_gap_starts_new_session() -> None:
    a = _clip(1, minutes=0, duration_s=60)
    gap_min = (SESSION_MAX_GAP_SECONDS / 60) + 5
    b = _clip(2, minutes=1 + gap_min, duration_s=60)
    assert not should_continue_session(a, b)
    assert group_clips_into_sessions([a, b]) == [[1], [2]]


def test_landing_hint_splits_within_hard_gap() -> None:
    # Gap between soft and max, both near ground → new session
    a = _clip(1, minutes=0, duration_s=60, end_rel=1.0)
    gap_min = (SESSION_SOFT_GAP_SECONDS / 60) + 5  # ~8 min idle
    b = _clip(2, minutes=1 + gap_min, duration_s=60, start_rel=0.5)
    assert not should_continue_session(a, b)
    assert group_clips_into_sessions([a, b]) == [[1], [2]]


def test_airborne_continuation_within_hard_gap() -> None:
    a = _clip(1, minutes=0, duration_s=60, end_rel=40.0)
    gap_min = (SESSION_SOFT_GAP_SECONDS / 60) + 5
    b = _clip(2, minutes=1 + gap_min, duration_s=60, start_rel=35.0)
    assert should_continue_session(a, b)
    assert group_clips_into_sessions([a, b]) == [[1, 2]]


def test_same_flow_always_together() -> None:
    a = _clip(1, minutes=0, duration_s=60, flow_id=9)
    # Huge gap would normally split, but same flow_id wins
    b = _clip(2, minutes=120, duration_s=60, flow_id=9)
    assert should_continue_session(a, b)
    assert group_clips_into_sessions([a, b]) == [[1, 2]]


def test_flow_block_nests_inside_session() -> None:
    # Flow parts + later clip with soft gap
    a = _clip(1, minutes=0, duration_s=300, flow_id=3)
    b = _clip(2, minutes=5, duration_s=120, flow_id=3)
    c = _clip(3, minutes=8, duration_s=60, flow_id=None)  # ~1 min after b ends
    sessions = group_clips_into_sessions([a, b, c])
    assert sessions == [[1, 2, 3]]


def test_altitude_edges_from_track() -> None:
    track = [
        {"lat": 1.0, "lon": 2.0, "rel_alt": 1.0, "abs_alt": 100.0},
        {"lat": 1.01, "lon": 2.01, "rel_alt": 50.0, "abs_alt": 150.0},
        {"lat": 1.02, "lon": 2.02, "rel_alt": 2.0, "abs_alt": 102.0},
    ]
    start_rel, end_rel, *_ = altitude_edges_from_track(track)
    assert start_rel is not None and start_rel < 20
    assert end_rel is not None and end_rel < 20


def test_attach_photos_nearby() -> None:
    videos = [
        _clip(1, minutes=0, duration_s=120),
        _clip(2, minutes=3, duration_s=60),
    ]
    sessions = group_clips_into_sessions(videos)
    lookup = {c.media_id: c for c in videos}
    photo = _clip(99, minutes=1, duration_s=0)
    photo.flow_id = None
    enriched = attach_photos_to_sessions(sessions, lookup, [photo])
    assert 99 in enriched[0]


def test_replace_sessions_and_list_collapse(tmp_path: Path) -> None:
    db = Database(tmp_path / "s.sqlite3")
    root_id = db.add_root(tmp_path / "lib", label="t")
    (tmp_path / "lib").mkdir(parents=True, exist_ok=True)

    def seed(name: str, recorded: str, *, kind: str = "video") -> int:
        path = tmp_path / "lib" / name
        path.write_bytes(b"x")
        return db.upsert_media(
            {
                "root_id": root_id,
                "primary_asset_id": None,
                "kind": kind,
                "filename": name,
                "path": str(path.resolve()),
                "size_bytes": 10,
                "duration_s": 30.0,
                "recorded_at": recorded,
                "sequence": None,
                "mode": None,
                "drone_model": "Avata 2",
                "camera_model": None,
                "latitude": 48.1,
                "longitude": 11.5,
                "abs_alt": None,
                "has_srt": 0,
                "has_lrf": 0,
                "track_json": None,
            }
        )

    a = seed("a.MP4", "2024-06-01T10:00:00")
    b = seed("b.MP4", "2024-06-01T10:02:00")
    c = seed("c.MP4", "2024-06-01T12:00:00")  # far later → other session
    lookup = db.media_map_for_root(root_id, kind=None)
    db.replace_sessions_for_root(root_id, [[a, b], [c]], lookup)

    items = db.list_media(sessions_only=True)
    assert len(items) == 1
    assert items[0].id == a
    assert items[0].session_video_count == 2

    all_items = db.list_media()
    # Multi-session collapsed to 1 row + single session c = 2 rows
    ids = {i.id for i in all_items}
    assert a in ids and c in ids and b not in ids

    clips = db.session_clips(items[0].session_id)  # type: ignore[arg-type]
    assert [x.id for x in clips] == [a, b]

    stats = db.stats()
    assert stats["sessions"] == 1
