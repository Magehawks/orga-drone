"""Tests for duplicate fingerprint matching across library roots."""

from __future__ import annotations

from pathlib import Path

from orga_drone.dupes import (
    DURATION_TOLERANCE_S,
    RECORDED_AT_TOLERANCE_S,
    MediaFingerprintInput,
    attributes_match,
    duration_within_tolerance,
    find_duplicate_groups,
    normalize_dji_stem,
    recorded_within_tolerance,
)


def _item(
    mid: int,
    *,
    filename: str = "DJI_20240601100000_0001_D.MP4",
    path: str | None = None,
    root_id: int = 1,
    size: int = 1_000_000,
    duration_s: float | None = 60.0,
    recorded_at: str | None = "2024-06-01T10:00:00",
    kind: str = "video",
    root_label: str | None = None,
) -> MediaFingerprintInput:
    return MediaFingerprintInput(
        id=mid,
        root_id=root_id,
        filename=filename,
        path=path or f"/root{root_id}/{filename}",
        size_bytes=size,
        duration_s=duration_s,
        recorded_at=recorded_at,
        kind=kind,
        root_label=root_label or f"root-{root_id}",
        root_path=f"/root{root_id}",
    )


def test_normalize_dji_stem() -> None:
    assert normalize_dji_stem("DJI_20240601100000_0001_D.MP4") == "DJI_20240601100000_0001_D"
    assert normalize_dji_stem("dji_20240601100000_0001_d.mp4") == "DJI_20240601100000_0001_D"
    assert normalize_dji_stem("holiday.mp4") is None
    assert normalize_dji_stem("DJI_bad_name.MP4") is None


def test_recorded_tolerance_thresholds() -> None:
    assert RECORDED_AT_TOLERANCE_S == 2.0
    assert recorded_within_tolerance("2024-06-01T10:00:00", "2024-06-01T10:00:02")
    assert not recorded_within_tolerance("2024-06-01T10:00:00", "2024-06-01T10:00:03")
    assert recorded_within_tolerance(None, None)
    assert recorded_within_tolerance("2024-06-01T10:00:00", None)


def test_duration_tolerance_thresholds() -> None:
    assert DURATION_TOLERANCE_S == 1.0
    assert duration_within_tolerance(60.0, 60.9)
    assert not duration_within_tolerance(60.0, 61.1)
    assert duration_within_tolerance(None, 60.0)


def test_dji_stem_matches_across_roots() -> None:
    a = _item(1, root_id=1, root_label="SD")
    b = _item(2, root_id=2, root_label="Backup")
    groups = find_duplicate_groups([a, b])
    assert len(groups) == 1
    assert groups[0].size == 2
    assert "dji_stem" in groups[0].match_reasons
    labels = {m.root_label for m in groups[0].members}
    assert labels == {"SD", "Backup"}


def test_dji_stem_case_insensitive() -> None:
    a = _item(1, filename="DJI_20240601100000_0001_D.MP4", root_id=1)
    b = _item(2, filename="dji_20240601100000_0001_d.mp4", root_id=2)
    groups = find_duplicate_groups([a, b])
    assert len(groups) == 1
    assert "dji_stem" in groups[0].match_reasons


def test_attribute_match_within_tolerances() -> None:
    a = _item(
        1,
        filename="clip.mp4",
        root_id=1,
        recorded_at="2024-06-01T10:00:00",
        duration_s=60.0,
    )
    b = _item(
        2,
        filename="CLIP.MP4",
        root_id=2,
        recorded_at="2024-06-01T10:00:01",
        duration_s=60.5,
    )
    assert attributes_match(a, b)
    groups = find_duplicate_groups([a, b])
    assert len(groups) == 1
    assert "attributes" in groups[0].match_reasons


def test_attribute_rejects_size_mismatch() -> None:
    a = _item(1, filename="clip.mp4", size=100, root_id=1)
    b = _item(2, filename="clip.mp4", size=101, root_id=2)
    assert not attributes_match(a, b)
    assert find_duplicate_groups([a, b]) == []


def test_attribute_rejects_duration_outside_tolerance() -> None:
    a = _item(1, filename="clip.mp4", duration_s=60.0, root_id=1)
    b = _item(2, filename="clip.mp4", duration_s=62.0, root_id=2)
    assert not attributes_match(a, b)
    assert find_duplicate_groups([a, b]) == []


def test_same_path_not_duplicate() -> None:
    a = _item(1, path="/same/file.MP4", root_id=1)
    b = _item(2, path="/same/file.MP4", root_id=1)
    assert find_duplicate_groups([a, b]) == []


def test_singleton_not_reported() -> None:
    a = _item(1, root_id=1)
    b = _item(2, filename="DJI_20240601100000_0002_D.MP4", root_id=2)
    assert find_duplicate_groups([a, b]) == []


def test_three_way_group() -> None:
    a = _item(1, root_id=1)
    b = _item(2, root_id=2)
    c = _item(3, root_id=3)
    groups = find_duplicate_groups([a, b, c])
    assert len(groups) == 1
    assert groups[0].size == 3


def test_db_list_and_page(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from orga_drone.config import Settings

    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db = app.state.db
    r1 = tmp_path / "sd"
    r2 = tmp_path / "backup"
    r1.mkdir()
    r2.mkdir()
    id1 = db.add_root(r1, "SD")
    id2 = db.add_root(r2, "Backup")
    f1 = r1 / "DJI_20240601100000_0001_D.MP4"
    f2 = r2 / "DJI_20240601100000_0001_D.MP4"
    f1.write_bytes(b"x" * 100)
    f2.write_bytes(b"x" * 100)
    for root_id, path in ((id1, f1), (id2, f2)):
        db.upsert_media(
            {
                "root_id": root_id,
                "primary_asset_id": None,
                "kind": "video",
                "filename": path.name,
                "path": str(path.resolve()),
                "size_bytes": 100,
                "duration_s": 12.0,
                "recorded_at": "2024-06-01T10:00:00",
                "sequence": 1,
                "mode": "D",
                "drone_model": "DJI Avata 2",
                "camera_model": None,
                "latitude": None,
                "longitude": None,
                "abs_alt": None,
                "has_srt": 0,
                "has_lrf": 0,
                "track_json": None,
            }
        )

    client = TestClient(app)
    page = client.get("/duplicates")
    assert page.status_code == 200
    assert b"DJI_20240601100000_0001_D.MP4" in page.content
    assert b"SD" in page.content
    assert b"Backup" in page.content

    scan = client.post("/duplicates/scan", follow_redirects=False)
    assert scan.status_code == 303
    assert "/duplicates" in scan.headers["location"]
