"""Tests for automatic scan tags (time, place, search, user-tag isolation)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from orga_drone.auto_tags import (
    apply_auto_tags_to_media,
    compute_auto_tags,
    place_tags_from_result,
    time_tags_from_recorded_at,
)
from orga_drone.db import Database
from orga_drone.geocode import PlaceResult, round_coord


def test_time_tags_from_recorded_at() -> None:
    assert time_tags_from_recorded_at("2025-11-05T10:00:00") == ["2025", "2025-11"]
    assert time_tags_from_recorded_at(None) == []
    assert time_tags_from_recorded_at("not-a-date") == []


def test_place_tags_from_result_dedupes() -> None:
    place = PlaceResult(
        country="Germany",
        region="Berlin",
        city="Berlin",
        district="Berlin",
        country_code="DE",
    )
    tags = place_tags_from_result(place)
    assert tags == ["Berlin", "Germany"]


def test_geocode_cache_hit(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    place = PlaceResult(
        country="Malta",
        region="Malta",
        city="Valletta",
        district=None,
        country_code="MT",
    )
    lat, lon = 35.8989, 14.5146
    lat_key = round_coord(lat)
    lon_key = round_coord(lon)
    db.upsert_geocode_cache(lat_key, lon_key, place)

    with patch("orga_drone.geocode._lookup_offline") as lookup:
        from orga_drone.geocode import resolve

        hit = resolve(db, lat, lon, mode="offline")
        lookup.assert_not_called()

    assert hit is not None
    assert hit.city == "Valletta"
    assert hit.country == "Malta"


def test_apply_auto_tags_user_tags_untouched(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    root_id = db.add_root(tmp_path / "lib", label="test")
    path = str((tmp_path / "lib" / "clip.MP4").resolve())
    (tmp_path / "lib").mkdir(parents=True)
    (tmp_path / "lib" / "clip.MP4").write_bytes(b"x")
    mid = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": "clip.MP4",
            "path": path,
            "size_bytes": 1,
            "duration_s": 1.0,
            "recorded_at": "2025-11-01T08:00:00",
            "sequence": None,
            "mode": None,
            "drone_model": None,
            "camera_model": None,
            "source_type": None,
            "latitude": 52.52,
            "longitude": 13.405,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    db.upsert_media_meta(path, stars=0, favorite=False, tags=["user-only"], notes="keep")

    mock_place = PlaceResult(
        country="Germany",
        region="Berlin",
        city="Berlin",
        district=None,
        country_code="DE",
    )
    with patch("orga_drone.auto_tags.resolve", return_value=mock_place):
        apply_auto_tags_to_media(
            db,
            mid,
            recorded_at="2025-11-01T08:00:00",
            latitude=52.52,
            longitude=13.405,
        )

    item = db.get_media(mid)
    assert item is not None
    assert item.tags == ["user-only"]
    assert item.notes == "keep"
    assert "2025" in item.auto_tags
    assert "2025-11" in item.auto_tags
    assert "Berlin" in item.auto_tags
    assert "Germany" in item.auto_tags
    assert item.place is not None
    assert item.place.get("city") == "Berlin"


def test_list_media_search_auto_tags_and_place(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    root_id = db.add_root(tmp_path / "lib", label="test")
    path = str((tmp_path / "lib" / "gps.JPG").resolve())
    (tmp_path / "lib").mkdir(parents=True)
    (tmp_path / "lib" / "gps.JPG").write_bytes(b"x")
    mid = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": "gps.JPG",
            "path": path,
            "size_bytes": 1,
            "duration_s": None,
            "recorded_at": "2025-11-12T09:00:00",
            "sequence": None,
            "mode": None,
            "drone_model": None,
            "camera_model": None,
            "source_type": None,
            "latitude": 35.9,
            "longitude": 14.5,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    apply_auto_tags_to_media(
        db,
        mid,
        recorded_at="2025-11-12T09:00:00",
        latitude=35.9,
        longitude=14.5,
        geocode_mode="off",
    )
    db.update_media_auto_tags(
        mid,
        auto_tags_json='["2025", "2025-11", "Valletta", "Malta"]',
        place_json='{"country":"Malta","region":"Malta","city":"Valletta","district":null,"country_code":"MT","source":"test"}',
    )

    by_month = db.list_media(q="2025-11")
    assert [i.filename for i in by_month] == ["gps.JPG"]

    by_place = db.list_media(q="Valletta")
    assert [i.filename for i in by_place] == ["gps.JPG"]


def test_compute_auto_tags_off_skips_geocode(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    with patch("orga_drone.auto_tags.resolve") as resolve:
        tags, place = compute_auto_tags(
            db,
            recorded_at="2024-06-15T12:00:00",
            latitude=48.0,
            longitude=11.0,
            geocode_mode="off",
        )
        resolve.assert_not_called()
    assert tags == ["2024", "2024-06"]
    assert place is None
