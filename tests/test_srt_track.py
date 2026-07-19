"""Tests for SRT track parsing used by map ↔ video sync."""

from __future__ import annotations

from pathlib import Path

from orga_drone.parse import parse_srt


def test_parse_srt_attaches_cue_timestamps(tmp_path: Path) -> None:
    srt = tmp_path / "clip.SRT"
    srt.write_text(
        """1
00:00:01,000 --> 00:00:01,033
[latitude: 47.1] [longitude: 8.2] [rel_alt: 10.0 abs_alt: 500.0]

2
00:00:02,500 --> 00:00:02,533
[latitude: 47.2] [longitude: 8.3] [rel_alt: 12.0 abs_alt: 502.0]

3
00:00:04,000 --> 00:00:04,033
[latitude: 47.3] [longitude: 8.4] [rel_alt: 14.0 abs_alt: 504.0]
""",
        encoding="utf-8",
    )
    start, track, duration = parse_srt(srt)
    assert start is not None
    assert start.lat == 47.1
    assert duration == 4.033
    assert len(track) == 3
    assert track[0].t == 1.0
    assert track[1].t == 2.5
    assert track[2].t == 4.0
    assert track[2].rel_alt == 14.0


def test_parse_srt_empty(tmp_path: Path) -> None:
    srt = tmp_path / "empty.SRT"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nno gps here\n", encoding="utf-8")
    start, track, duration = parse_srt(srt)
    assert start is None
    assert track == []
    assert duration == 1.0
