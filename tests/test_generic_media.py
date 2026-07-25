"""Tests for brand-agnostic photo/video indexing, EXIF GPS, and source filter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image
from PIL.ExifTags import Base

from orga_drone.db import Database
from orga_drone.parse import (
    NON_DJI_CAMERA_LABEL,
    PHOTO_EXTS,
    VIDEO_EXTS,
    _dms_to_decimal,
    _parse_iso6709,
    classify_ext,
    classify_source_type,
    ensure_heif_support,
    parse_exif,
    parse_media_file,
)
from orga_drone.scan import iter_media_files, scan_root


def _write_gps_image(
    path: Path,
    *,
    fmt: str = "JPEG",
    lat: float = 47.1,
    lon: float = 8.5,
    alt: float = 400.0,
    make: str = "Apple",
    model: str = "iPhone",
    when: str = "2024:06:15 12:30:00",
) -> None:
    """Create a small image with EXIF GPS + DateTimeOriginal (any brand)."""
    if fmt.upper() in {"HEIC", "HEIF"}:
        ensure_heif_support()
        fmt = "HEIF"
    img = Image.new("RGB", (64, 64), (10, 80, 120))
    exif = img.getexif()
    lat_ref = "N" if lat >= 0 else "S"
    lon_ref = "E" if lon >= 0 else "W"
    alat, alon = abs(lat), abs(lon)
    lat_d, lat_m = int(alat), (alat - int(alat)) * 60
    lat_s = (lat_m - int(lat_m)) * 60
    lon_d, lon_m = int(alon), (alon - int(alon)) * 60
    lon_s = (lon_m - int(lon_m)) * 60
    exif[Base.GPSInfo] = {
        1: lat_ref,
        2: (float(lat_d), float(int(lat_m)), float(lat_s)),
        3: lon_ref,
        4: (float(lon_d), float(int(lon_m)), float(lon_s)),
        6: float(alt),
    }
    exif[Base.Make] = make
    exif[Base.Model] = model
    exif[Base.DateTimeOriginal] = when
    exif[Base.DateTime] = when
    img.save(path, exif=exif, format=fmt)


def test_extensions_include_generic_types() -> None:
    assert ".webp" in PHOTO_EXTS
    assert ".heic" in PHOTO_EXTS
    assert ".heif" in PHOTO_EXTS
    assert ".m4v" in VIDEO_EXTS
    assert classify_ext(Path("holiday.WEBP")) == "photo"
    assert classify_ext(Path("IMG_0001.HEIC")) == "photo"
    assert classify_ext(Path("clip.M4V")) == "video"
    assert classify_ext(Path("random_name.MOV")) == "video"


def test_dms_to_decimal() -> None:
    assert abs(_dms_to_decimal((47, 6, 0), "N") - 47.1) < 1e-9
    assert abs(_dms_to_decimal((8, 30, 0), "W") + 8.5) < 1e-9


def test_parse_iso6709() -> None:
    pt = _parse_iso6709("location:+47.376900+008.541700/")
    assert pt is not None
    assert abs(pt.lat - 47.3769) < 1e-6
    assert abs(pt.lon - 8.5417) < 1e-6


def test_classify_source_type() -> None:
    assert (
        classify_source_type(filename="DJI_20240101120000_0001_D.MP4", mode="D")
        == "drone"
    )
    assert (
        classify_source_type(
            filename="clip.mp4", drone_model="DJI Avata 2", camera_model="FC8485"
        )
        == "drone"
    )
    assert (
        classify_source_type(
            filename="IMG_1.JPG", make="Apple", camera_model="iPhone 15"
        )
        == "phone"
    )
    assert (
        classify_source_type(
            filename="DSC_1.JPG", make="Canon", camera_model="EOS R50"
        )
        == "camera"
    )
    assert classify_source_type(filename="mystery.mp4") == "unknown"


@pytest.mark.parametrize(
    ("make", "model", "expected_source"),
    [
        ("Apple", "iPhone 15", "phone"),
        ("samsung", "SM-S911B", "phone"),
        ("Canon", "Canon EOS R50", "camera"),
        ("SONY", "ILCE-7M4", "camera"),
        ("NIKON CORPORATION", "NIKON Z 6", "camera"),
        ("GoPro", "HERO12 Black", "camera"),
    ],
)
def test_exif_gps_brand_agnostic(
    tmp_path: Path, make: str, model: str, expected_source: str
) -> None:
    photo = tmp_path / "vacation.jpg"
    _write_gps_image(photo, make=make, model=model)
    gps, drone, camera, recorded, exif_make = parse_exif(photo)
    assert gps is not None
    assert abs(gps.lat - 47.1) < 0.01
    assert abs(gps.lon - 8.5) < 0.01
    assert drone == NON_DJI_CAMERA_LABEL
    assert camera == model
    assert exif_make == make
    assert recorded == datetime(2024, 6, 15, 12, 30, 0)
    parsed = parse_media_file(photo)
    assert parsed.sequence is None
    assert parsed.mode is None
    assert parsed.drone_model == NON_DJI_CAMERA_LABEL
    assert parsed.source_type == expected_source


def test_dji_exif_still_maps_drone(tmp_path: Path) -> None:
    photo = tmp_path / "DJI_20240615123000_0001_D.JPG"
    _write_gps_image(photo, make="DJI", model="FC8485")
    parsed = parse_media_file(photo)
    assert parsed.drone_model == "DJI Avata 2"
    assert parsed.source_type == "drone"
    assert parsed.recorded_at == datetime(2024, 6, 15, 12, 30, 0)
    assert parsed.sequence == 1
    assert parsed.mode == "D"
    assert parsed.latitude is not None


@pytest.mark.skipif(not ensure_heif_support(), reason="pillow-heif not available")
def test_heic_exif_gps(tmp_path: Path) -> None:
    photo = tmp_path / "IMG_0001.HEIC"
    _write_gps_image(photo, fmt="HEIF", make="Apple", model="iPhone")
    gps, drone, camera, recorded, make = parse_exif(photo)
    assert gps is not None
    assert abs(gps.lat - 47.1) < 0.01
    assert abs(gps.lon - 8.5) < 0.01
    assert drone == NON_DJI_CAMERA_LABEL
    assert camera == "iPhone"
    assert make == "Apple"
    assert recorded == datetime(2024, 6, 15, 12, 30, 0)


def test_generic_video_indexed_without_srt(tmp_path: Path) -> None:
    video = tmp_path / "vacation_clip.mp4"
    payload = (
        b"\x00\x00\x00\x18ftypmp42"
        + b"creation_time\x00\x002024-07-01T18:45:00.000000Z"
        + b"location\x00+46.8000+009.1000/"
        + b"\x00" * 64
    )
    video.write_bytes(payload)

    parsed = parse_media_file(video)
    assert parsed.kind == "video"
    assert parsed.drone_model is None
    assert parsed.source_type == "unknown"
    assert parsed.recorded_at == datetime(2024, 7, 1, 18, 45, 0)
    assert parsed.latitude is not None
    assert abs(parsed.latitude - 46.8) < 1e-3
    assert abs(parsed.longitude - 9.1) < 1e-3
    assert parsed.track is None


def test_generic_video_mtime_fallback_without_gps(tmp_path: Path) -> None:
    video = tmp_path / "phone_movie.MOV"
    video.write_bytes(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 32)
    parsed = parse_media_file(video)
    assert parsed.kind == "video"
    assert parsed.latitude is None
    assert parsed.longitude is None
    assert parsed.recorded_at is not None
    assert parsed.source_type == "unknown"


def test_scan_and_source_filter(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_gps_image(lib / "beach.jpg", make="Google", model="Pixel 8")
    _write_gps_image(
        lib / "DJI_20240615123000_0001_D.JPG", make="DJI", model="FC8485"
    )
    (lib / "clip.mp4").write_bytes(b"\x00\x00\x00\x14ftypmp42" + b"\x00" * 32)

    db = Database(tmp_path / "t.sqlite3")
    root_id = db.add_root(lib, label="vacation")
    counts = scan_root(db, root_id, lib)
    assert counts["photos"] >= 2
    assert counts["videos"] >= 1

    all_items = db.list_media()
    by_name = {i.filename: i for i in all_items}
    assert by_name["beach.jpg"].source_type == "phone"
    assert by_name["beach.jpg"].latitude is not None
    assert by_name["DJI_20240615123000_0001_D.JPG"].source_type == "drone"
    assert by_name["clip.mp4"].source_type == "unknown"

    drones = db.list_media(source="drone")
    assert all(i.source_type == "drone" for i in drones)
    assert any(i.filename.startswith("DJI_") for i in drones)

    others = db.list_media(source="other")
    assert all((i.source_type or "unknown") != "drone" for i in others)
    assert any(i.filename == "beach.jpg" for i in others)


def test_iter_media_files_picks_common_exts(tmp_path: Path) -> None:
    (tmp_path / "a.webp").write_bytes(b"x")
    (tmp_path / "b.m4v").write_bytes(b"x")
    (tmp_path / "c.heic").write_bytes(b"x")
    (tmp_path / "d.txt").write_bytes(b"x")
    names = {p.name for p in iter_media_files(tmp_path)}
    assert "a.webp" in names
    assert "b.m4v" in names
    assert "c.heic" in names
    assert "d.txt" not in names


def test_live_photo_pair_detected(tmp_path: Path) -> None:
    from orga_drone.parse import live_photo_video_sidecars

    still = tmp_path / "IMG_0001.HEIC"
    mov = tmp_path / "IMG_0001.MOV"
    alone = tmp_path / "holiday.MOV"
    still.write_bytes(b"still")
    mov.write_bytes(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 32)
    alone.write_bytes(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 32)

    sidecars = live_photo_video_sidecars([still, mov, alone])
    assert mov.resolve() in sidecars
    assert alone.resolve() not in sidecars


def test_scan_skips_live_photo_mov_as_video(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    still = lib / "IMG_0042.JPG"
    mov = lib / "IMG_0042.MOV"
    real_video = lib / "clip.MOV"
    _write_gps_image(still, make="Apple", model="iPhone 15")
    mov.write_bytes(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 32)
    real_video.write_bytes(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 32)

    db = Database(tmp_path / "live.sqlite3")
    root_id = db.add_root(lib, label="iphone")
    counts = scan_root(db, root_id, lib)

    assert counts["photos"] >= 1
    assert counts["videos"] == 1
    assert counts.get("live_sidecars", 0) == 1

    by_name = {i.filename: i for i in db.list_media()}
    assert "IMG_0042.JPG" in by_name
    assert by_name["IMG_0042.JPG"].kind == "photo"
    assert "IMG_0042.MOV" not in by_name
    assert "clip.MOV" in by_name
    assert by_name["clip.MOV"].kind == "video"
