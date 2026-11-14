"""Hardening: location metadata policy and JPEG/PNG format contract (#450 / PR #451)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image
from PIL.ExifTags import Base

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.export.still_export import (
    export_photo_file,
    inspect_photo_preset,
    still_may_contain_location,
)
from orga_drone.studio_export import build_media_export_options_payload, run_media_export
from orga_drone.studio_image import ImageAdjust


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)


def _add_photo(db: Database, root: Path, name: str, path: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=root.name)
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": name,
            "path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": None,
            "mode": None,
            "drone_model": "Avata 2",
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )


def _write_jpeg(path: Path, size: tuple[int, int] = (320, 240), *, color=(20, 40, 80)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG", quality=92)


def _write_png(path: Path, size: tuple[int, int] = (320, 240)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (30, 60, 90)).save(path, format="PNG")


def _jpeg_with_exif_gps(path: Path, size: tuple[int, int] = (640, 480)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[Base.GPSInfo] = {
        0: b"\x02\x02\x00\x00",
        1: "N",
        2: (1, 1, 1),
        3: "E",
        4: (1, 1, 1),
    }
    Image.new("RGB", size, (10, 20, 30)).save(path, format="JPEG", quality=90, exif=exif)


def _jpeg_with_xmp_gps(path: Path, size: tuple[int, int] = (400, 300)) -> None:
    """Insert an APP1 XMP packet with GPSLatitude after SOI."""
    buf = io.BytesIO()
    Image.new("RGB", size, (5, 6, 7)).save(buf, format="JPEG", quality=90)
    data = buf.getvalue()
    assert data[:2] == b"\xff\xd8"
    xmp = (
        b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        b'<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/gps/">'
        b"<exif:GPSLatitude>48,8.0N</exif:GPSLatitude>"
        b"<exif:GPSLongitude>11,34.0E</exif:GPSLongitude>"
        b"</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end=\"w\"?>"
    )
    payload = b"http://ns.adobe.com/xap/1.0/\x00" + xmp
    app1 = b"\xff\xe1" + len(payload).to_bytes(2, "big") + payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data[:2] + app1 + data[2:])


def _assert_jpeg(path: Path) -> Image.Image:
    assert path.read_bytes()[:3] == b"\xff\xd8\xff"
    img = Image.open(path)
    img.load()
    assert img.format == "JPEG"
    return img


def _assert_png(path: Path) -> Image.Image:
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(path)
    img.load()
    assert img.format == "PNG"
    return img


def test_location_free_jpeg_may_byte_copy(tmp_path: Path) -> None:
    src = tmp_path / "clean.jpg"
    _write_jpeg(src, (3840, 2160))
    assert still_may_contain_location(src) is False
    spec = inspect_photo_preset(src, "best", still_format="jpeg")
    assert spec.copied is True
    assert spec.width == 3840 and spec.height == 2160
    dest = tmp_path / "out.jpg"
    result = export_photo_file(src, dest, "best", still_format="jpeg")
    assert result.read_bytes() == src.read_bytes()
    _assert_jpeg(result)


def test_exif_gps_blocks_copy_and_reencode_has_no_gps(tmp_path: Path) -> None:
    src = tmp_path / "exif.jpg"
    _jpeg_with_exif_gps(src)
    assert still_may_contain_location(src) is True
    original = src.read_bytes()
    dest = tmp_path / "out.jpg"
    result = export_photo_file(src, dest, "best", still_format="jpeg")
    assert src.read_bytes() == original
    assert result.read_bytes() != original
    with _assert_jpeg(result) as img:
        assert img.size == (640, 480)
        exif = img.getexif()
        gps = None
        try:
            gps = exif.get_ifd(Base.GPSInfo) if exif else None
        except Exception:
            gps = exif.get(Base.GPSInfo) if exif else None
        assert not gps


def test_xmp_gps_blocks_copy(tmp_path: Path) -> None:
    src = tmp_path / "xmp.jpg"
    _jpeg_with_xmp_gps(src)
    assert still_may_contain_location(src) is True
    original = src.read_bytes()
    dest = tmp_path / "print.jpg"
    result = export_photo_file(src, dest, "best", still_format="jpeg")
    assert src.read_bytes() == original
    assert result.read_bytes() != original
    out = result.read_bytes()
    assert b"GPSLatitude" not in out
    _assert_jpeg(result)


def test_unreadable_location_detection_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orga_drone.export import still_export

    src = tmp_path / "opaque.jpg"
    _write_jpeg(src)

    monkeypatch.setattr(still_export, "_exif_has_gps", lambda _img: False)

    def _boom_bytes(_path: Path) -> bool:
        raise OSError("cannot scan")

    monkeypatch.setattr(still_export, "_file_bytes_suggest_location", _boom_bytes)
    assert still_may_contain_location(src) is True
    dest = tmp_path / "out.jpg"
    original = src.read_bytes()
    result = export_photo_file(src, dest, "best", still_format="jpeg")
    assert src.read_bytes() == original
    assert result.read_bytes() != original


def test_png_source_jpeg_choice_reencodes_as_jpeg(tmp_path: Path) -> None:
    src = tmp_path / "still.png"
    _write_png(src, (800, 600))
    original = src.read_bytes()
    dest = tmp_path / "out.jpg"
    result = export_photo_file(src, dest, "best", still_format="jpeg")
    assert src.read_bytes() == original
    assert result.read_bytes() != original
    with _assert_jpeg(result) as img:
        assert img.size == (800, 600)
    spec = inspect_photo_preset(src, "best", still_format="jpeg")
    assert spec.copied is False
    assert spec.suffix == ".jpg"


def test_png_source_png_choice_may_byte_copy(tmp_path: Path) -> None:
    src = tmp_path / "still.png"
    _write_png(src, (500, 400))
    assert still_may_contain_location(src) is False
    spec = inspect_photo_preset(src, "best", still_format="png")
    assert spec.copied is True
    assert spec.suffix == ".png"
    dest = tmp_path / "out.png"
    result = export_photo_file(src, dest, "best", still_format="png")
    assert result.read_bytes() == src.read_bytes()
    _assert_png(result)


def test_graded_print_png_keeps_full_resolution(tmp_path: Path) -> None:
    src = tmp_path / "grade.jpg"
    _write_jpeg(src, (3840, 2160))
    original = src.read_bytes()
    dest = tmp_path / "grade.png"
    result = export_photo_file(
        src,
        dest,
        "best",
        still_format="png",
        image=ImageAdjust(exposure=20, contrast=5),
    )
    assert src.read_bytes() == original
    with _assert_png(result) as img:
        assert img.size == (3840, 2160)
        assert img.mode == "RGB"


def test_hires_graded_print_jpeg(tmp_path: Path) -> None:
    src = tmp_path / "drone.jpg"
    _write_jpeg(src, (5472, 3648), color=(40, 80, 50))
    original = src.read_bytes()
    dest = tmp_path / "drone_out.jpg"
    result = export_photo_file(
        src, dest, "best", still_format="jpeg", image=ImageAdjust(saturation=10)
    )
    assert src.read_bytes() == original
    with _assert_jpeg(result) as img:
        assert img.size == (5472, 3648)


def test_custom_downscale_no_upscale(tmp_path: Path) -> None:
    src = tmp_path / "uhd.jpg"
    _write_jpeg(src, (3840, 2160))
    original = src.read_bytes()
    dest = tmp_path / "half.jpg"
    result = export_photo_file(
        src,
        dest,
        "custom",
        still_format="jpeg",
        width=1920,
        height=1080,
        jpeg_quality=90,
    )
    assert src.read_bytes() == original
    with _assert_jpeg(result) as img:
        assert img.size == (1920, 1080)
    # Upscale attempt clamps to source.
    dest2 = tmp_path / "up.jpg"
    up = export_photo_file(
        src, dest2, "custom", still_format="jpeg", width=8000, height=4000
    )
    with _assert_jpeg(up) as img:
        assert img.size == (3840, 2160)


def test_options_expose_format_specific_copy_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    jpeg = tmp_path / "lib" / "a.jpg"
    png = tmp_path / "lib2" / "b.png"
    _write_jpeg(jpeg, (640, 480))
    _write_png(png, (640, 480))
    mid_j = _add_photo(db, tmp_path / "lib", "a.jpg", jpeg)
    mid_p = _add_photo(db, tmp_path / "lib2", "b.png", png)
    opt_j = build_media_export_options_payload(db, mid_j)
    best_j = next(row for row in opt_j["presets"] if row["id"] == "best")
    assert best_j["copied_jpeg"] is True
    assert best_j["copied_png"] is False
    opt_p = build_media_export_options_payload(db, mid_p)
    best_p = next(row for row in opt_p["presets"] if row["id"] == "best")
    assert best_p["copied_jpeg"] is False
    assert best_p["copied_png"] is True


def test_matrix_via_run_media_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    out = tmp_path / "out"
    out.mkdir()

    # JPEG without GPS, neutral Original → JPEG byte-copy
    p1 = tmp_path / "m1" / "n.jpg"
    _write_jpeg(p1, (3840, 2160))
    mid1 = _add_photo(db, tmp_path / "m1", "n.jpg", p1)
    r1 = run_media_export(db, mid1, preset="best", output_path=out / "1.jpg", still_format="jpeg")
    assert r1.read_bytes() == p1.read_bytes()
    _assert_jpeg(r1).close()

    # JPEG EXIF GPS, neutral Original → JPEG re-encode
    p2 = tmp_path / "m2" / "g.jpg"
    _jpeg_with_exif_gps(p2, (800, 600))
    mid2 = _add_photo(db, tmp_path / "m2", "g.jpg", p2)
    orig2 = p2.read_bytes()
    r2 = run_media_export(db, mid2, preset="best", output_path=out / "2.jpg", still_format="jpeg")
    assert p2.read_bytes() == orig2
    assert r2.read_bytes() != orig2
    _assert_jpeg(r2).close()

    # JPEG XMP GPS, Print → JPEG re-encode
    p3 = tmp_path / "m3" / "x.jpg"
    _jpeg_with_xmp_gps(p3)
    mid3 = _add_photo(db, tmp_path / "m3", "x.jpg", p3)
    orig3 = p3.read_bytes()
    r3 = run_media_export(db, mid3, preset="best", output_path=out / "3.jpg", still_format="jpeg")
    assert p3.read_bytes() == orig3
    assert b"GPSLatitude" not in r3.read_bytes()
    _assert_jpeg(r3).close()

    # Graded Print PNG
    p4 = tmp_path / "m4" / "c.jpg"
    _write_jpeg(p4, (1280, 720))
    mid4 = _add_photo(db, tmp_path / "m4", "c.jpg", p4)
    orig4 = p4.read_bytes()
    r4 = run_media_export(
        db,
        mid4,
        preset="best",
        output_path=out / "4.png",
        still_format="png",
        image=ImageAdjust(exposure=15),
    )
    assert p4.read_bytes() == orig4
    with _assert_png(r4) as img:
        assert img.size == (1280, 720)

    # PNG → JPEG / PNG
    p5 = tmp_path / "m5" / "p.png"
    _write_png(p5, (640, 480))
    mid5 = _add_photo(db, tmp_path / "m5", "p.png", p5)
    orig5 = p5.read_bytes()
    r5j = run_media_export(
        db, mid5, preset="best", output_path=out / "5.jpg", still_format="jpeg"
    )
    r5p = run_media_export(
        db, mid5, preset="best", output_path=out / "5.png", still_format="png"
    )
    assert p5.read_bytes() == orig5
    _assert_jpeg(r5j).close()
    assert r5p.read_bytes() == orig5
    _assert_png(r5p).close()
