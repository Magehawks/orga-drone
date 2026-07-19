"""Tests for clip / complete-flight detail helpers."""

from __future__ import annotations

from types import SimpleNamespace

from orga_drone.flight_view import concat_clip_tracks, normalize_detail_tab


def _clip(**kwargs):
    defaults = {
        "kind": "video",
        "duration_s": 10.0,
        "track_json": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_normalize_detail_tab() -> None:
    assert normalize_detail_tab(None) == "clip"
    assert normalize_detail_tab("flight") == "flight"
    assert normalize_detail_tab("CLIP") == "clip"
    assert normalize_detail_tab("nope") == "clip"


def test_concat_timed_tracks_offsets() -> None:
    a = _clip(
        duration_s=10.0,
        track_json='[{"lat":1.0,"lon":2.0,"t":0},{"lat":1.1,"lon":2.1,"t":10}]',
    )
    b = _clip(
        duration_s=5.0,
        track_json='[{"lat":1.2,"lon":2.2,"t":0},{"lat":1.3,"lon":2.3,"t":5}]',
    )
    track, total = concat_clip_tracks([a, b])  # type: ignore[arg-type]
    assert total == 15.0
    assert len(track) == 4
    assert track[0]["t"] == 0
    assert track[1]["t"] == 10
    assert track[2]["t"] == 10
    assert track[3]["t"] == 15
    assert track[2]["lat"] == 1.2


def test_concat_skips_photos() -> None:
    video = _clip(
        duration_s=4.0,
        track_json='[{"lat":1.0,"lon":2.0,"t":0},{"lat":1.1,"lon":2.1,"t":4}]',
    )
    photo = _clip(kind="photo", duration_s=None, track_json=None)
    track, total = concat_clip_tracks([video, photo])  # type: ignore[arg-type]
    assert total == 4.0
    assert len(track) == 2
