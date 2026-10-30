"""Detail-page export: one photo as a still, one video as a Studio MP4 plan."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.export.studio_encoder import StudioExportError
from orga_drone.studio_export import (
    build_media_export_options_payload,
    prepare_media_export,
    run_media_export,
)
from orga_drone.db import make_identity_key
from orga_drone.studio_image import ImageAdjust, image_adjust_from_export_payload


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)


def _jpeg(path: Path, size: tuple[int, int] = (800, 200)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (20, 40, 80)).save(path, format="JPEG", quality=90)


def _add_photo(db: Database, root: Path, name: str, *, size: tuple[int, int]) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=root.name)
    photo = root / name
    _jpeg(photo, size)
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": name,
            "path": str(photo.resolve()),
            "size_bytes": photo.stat().st_size,
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


def _add_video(db: Database, root: Path, name: str, *, height: int, duration_s: float) -> int:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label=root.name)
    video = root / name
    video.write_bytes(b"fake-mp4")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": name,
            "path": str(video.resolve()),
            "size_bytes": video.stat().st_size,
            "duration_s": duration_s,
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
            "width": 3840 if height >= 2160 else 1920,
            "height": height,
        }
    )


class _EncoderBoom:
    def render(self, *_args, **_kwargs):
        raise AssertionError("a photo export must not use the video encoder")


def test_best_quality_jpeg_keeps_original_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_photo(db, tmp_path / "lib", "coast.jpg", size=(640, 480))
    source = Path(db.get_media(mid).path)
    original = source.read_bytes()
    (tmp_path / "out").mkdir()
    result = run_media_export(
        db,
        mid,
        preset="best",
        output_path=tmp_path / "out" / "coast_best.jpg",
        encoder=_EncoderBoom(),
    )
    assert result.read_bytes() == original
    assert result.suffix.lower() == ".jpg"
    assert result.name == "coast_best.jpg"
    assert db.list_studio_projects() == []


def test_taken_filename_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_photo(db, tmp_path / "lib", "shot.jpg", size=(640, 480))
    source = Path(db.get_media(mid).path)
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    taken = dest_dir / "shot_best.jpg"
    taken.write_bytes(b"leave-this-file")
    result = run_media_export(
        db,
        mid,
        preset="best",
        output_path=taken,
        overwrite=True,
    )
    assert result.name == "shot_best_1.jpg"
    assert taken.read_bytes() == b"leave-this-file"
    assert result.read_bytes() == source.read_bytes()
    assert result != taken


def test_instagram_and_tiktok_photo_pixel_sizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_photo(db, tmp_path / "lib", "wide.jpg", size=(800, 200))
    out = tmp_path / "out"
    out.mkdir()
    instagram = run_media_export(
        db,
        mid,
        preset="instagram",
        output_path=out / "wide_instagram.jpg",
    )
    tiktok = run_media_export(
        db,
        mid,
        preset="tiktok",
        output_path=out / "wide_tiktok.jpg",
    )
    with Image.open(instagram) as img:
        assert img.size == (1080, 1350)
        assert img.format == "JPEG"
    with Image.open(tiktok) as img:
        assert img.size == (1080, 1920)
        assert img.format == "JPEG"


def test_whatsapp_fits_longest_side_without_upscaling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    big = _add_photo(db, tmp_path / "lib", "big.jpg", size=(2000, 1000))
    small = _add_photo(db, tmp_path / "lib2", "small.jpg", size=(100, 80))
    out = tmp_path / "out"
    out.mkdir()
    large = run_media_export(db, big, preset="whatsapp", output_path=out / "big.jpg")
    tiny = run_media_export(db, small, preset="whatsapp", output_path=out / "small.jpg")
    with Image.open(large) as img:
        assert img.size == (1600, 800)
    with Image.open(tiny) as img:
        assert img.size == (100, 80)


def test_missing_photo_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_photo(db, tmp_path / "lib", "gone.jpg", size=(320, 240))
    Path(db.get_media(mid).path).unlink()
    with pytest.raises(StudioExportError, match="not available"):
        run_media_export(
            db,
            mid,
            preset="best",
            output_path=tmp_path / "out" / "gone_best.jpg",
        )


def test_neutral_adjustment_keeps_best_quality_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_photo(db, tmp_path / "lib", "flat.jpg", size=(320, 200))
    source = Path(db.get_media(mid).path)
    original = source.read_bytes()
    out = tmp_path / "out"
    out.mkdir()
    result = run_media_export(
        db,
        mid,
        preset="best",
        output_path=out / "flat_best.jpg",
        image=ImageAdjust(),
    )
    assert result.read_bytes() == original
    assert source.read_bytes() == original


def test_brightness_grades_the_export_and_leaves_the_library_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_photo(db, tmp_path / "lib", "gray.jpg", size=(160, 120))
    source = Path(db.get_media(mid).path)
    original = source.read_bytes()
    out = tmp_path / "out"
    out.mkdir()
    result = run_media_export(
        db,
        mid,
        preset="best",
        output_path=out / "gray_best.jpg",
        image=ImageAdjust(exposure=100),
    )
    assert source.read_bytes() == original
    assert result.read_bytes() != original
    with Image.open(source) as src, Image.open(result) as graded:
        assert graded.size == src.size
        assert graded.format == "JPEG"
        src_px = src.convert("RGB").getpixel((8, 8))
        out_px = graded.convert("RGB").getpixel((8, 8))
    assert isinstance(src_px, tuple) and isinstance(out_px, tuple)
    assert sum(out_px[:3]) > sum(src_px[:3]) + 40


def test_graded_whatsapp_keeps_the_preset_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_photo(db, tmp_path / "lib", "wide.jpg", size=(2000, 1000))
    source = Path(db.get_media(mid).path)
    original = source.read_bytes()
    out = tmp_path / "out"
    out.mkdir()
    result = run_media_export(
        db,
        mid,
        preset="whatsapp",
        output_path=out / "wide_whatsapp.jpg",
        image=ImageAdjust(saturation=-100),
    )
    assert source.read_bytes() == original
    with Image.open(result) as img:
        assert img.size == (1600, 800)
        assert img.format == "JPEG"


def test_video_export_ignores_photo_adjustments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_video(db, tmp_path / "lib", "clip.mp4", height=1080, duration_s=2.0)
    out = tmp_path / "out"
    out.mkdir()
    plan = prepare_media_export(
        db,
        mid,
        preset="best",
        output_path=out / "clip_best.mp4",
        image=ImageAdjust(exposure=80, warmth=40),
    )
    assert plan.config is not None
    assert plan.config.clips[0].image.is_neutral
    assert plan.config.clips[0].kind == "video"


def test_export_payload_sliders_default_neutral_and_reject_out_of_range() -> None:
    assert image_adjust_from_export_payload(None).is_neutral
    assert image_adjust_from_export_payload({"preset": "best"}).is_neutral
    adjust = image_adjust_from_export_payload({"warmth": 25, "exposure": 0})
    assert adjust.warmth == 25
    assert adjust.exposure == 0
    with pytest.raises(ValueError):
        image_adjust_from_export_payload({"contrast": 140})


def test_saved_grade_survives_reopen_reset_and_identity_relink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db_path = tmp_path / "t.sqlite3"
    db = Database(db_path)
    mid = _add_photo(db, tmp_path / "lib", "gray.jpg", size=(80, 60))
    row = db.get_media(mid)
    assert row is not None
    source = Path(row.path)
    original = source.read_bytes()
    db.upsert_media_meta(row.path, stars=4, notes="keep", identity_key="old")
    identity = make_identity_key(row.filename, row.size_bytes, row.recorded_at)
    db.set_image_adjust(row.path, ImageAdjust(exposure=35, warmth=-10), identity_key=identity)
    again = Database(db_path)
    kept = again.get_media(mid)
    assert kept is not None
    assert kept.stars == 4
    assert kept.notes == "keep"
    assert again.get_image_adjust(row.path) == ImageAdjust(exposure=35, warmth=-10)
    assert source.read_bytes() == original

    again.set_image_adjust(row.path, ImageAdjust(), identity_key=identity)
    assert again.get_image_adjust(row.path).is_neutral
    assert again.get_media(mid).stars == 4

    again.set_image_adjust(row.path, ImageAdjust(contrast=20), identity_key=identity)
    with again.connect() as conn:
        conn.execute("DELETE FROM media WHERE id = ?", (mid,))
    moved = tmp_path / "relink" / "gray.jpg"
    moved.parent.mkdir()
    moved.write_bytes(original)
    new_id = again.upsert_media(
        {
            "root_id": row.root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": "gray.jpg",
            "path": str(moved.resolve()),
            "size_bytes": moved.stat().st_size,
            "duration_s": None,
            "recorded_at": row.recorded_at,
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
    again.link_media_meta_for_path(
        str(moved.resolve()),
        filename="gray.jpg",
        size_bytes=moved.stat().st_size,
        recorded_at=row.recorded_at,
    )
    assert again.get_image_adjust(str(moved.resolve())).contrast == 20
    assert again.get_media(new_id).stars == 4
    assert source.read_bytes() == original


def test_saved_grade_exports_without_repeating_the_sliders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_photo(db, tmp_path / "lib", "gray.jpg", size=(160, 120))
    source = Path(db.get_media(mid).path)
    original = source.read_bytes()
    db.set_image_adjust(str(source), ImageAdjust(exposure=100))
    out = tmp_path / "out"
    out.mkdir()
    result = run_media_export(db, mid, preset="best", output_path=out / "gray_best.jpg")
    assert source.read_bytes() == original
    assert result.read_bytes() != original
    with Image.open(source) as src, Image.open(result) as graded:
        src_px = src.convert("RGB").getpixel((4, 4))
        out_px = graded.convert("RGB").getpixel((4, 4))
    assert sum(out_px[:3]) > sum(src_px[:3]) + 40


def test_neutral_png_is_a_still_and_jpeg_best_stays_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_photo(db, tmp_path / "lib", "flat.jpg", size=(120, 80))
    source = Path(db.get_media(mid).path)
    original = source.read_bytes()
    out = tmp_path / "out"
    out.mkdir()
    png = run_media_export(
        db,
        mid,
        preset="best",
        output_path=out / "flat_best.jpg",
        still_format="png",
    )
    jpeg = run_media_export(
        db,
        mid,
        preset="best",
        output_path=out / "flat_best.jpg",
        image=ImageAdjust(),
    )
    assert png.suffix.lower() == ".png"
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    with Image.open(png) as img:
        assert img.format == "PNG"
        assert img.size == (120, 80)
    assert jpeg.read_bytes() == original
    assert source.read_bytes() == original
    assert not png.read_bytes().startswith(b"\x00\x00\x00")


def test_detail_page_reloads_the_saved_grade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from orga_drone.app import create_app
    from orga_drone.config import Settings
    from orga_drone.i18n import clear_catalog_cache

    clear_catalog_cache()
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    app = create_app()
    db = app.state.db
    mid = _add_photo(db, tmp_path / "lib", "page.jpg", size=(40, 30))
    client = TestClient(app)
    saved = client.post(
        f"/api/media/{mid}/image-adjust",
        json={"exposure": 12, "contrast": 0, "saturation": 0, "warmth": -4},
    )
    assert saved.status_code == 200
    page = client.get(f"/media/{mid}", cookies={"lang": "en"})
    assert page.status_code == 200
    assert '"exposure": 12' in page.text
    assert '"warmth": -4' in page.text
    assert "Reset adjustments" in page.text
    assert 'id="detail-export-format"' in page.text
    assert 'id="detail-quick-look"' in page.text
    video = _add_video(db, tmp_path / "vid", "clip.mp4", height=1080, duration_s=1.0)
    denied = client.post(
        f"/api/media/{video}/image-adjust",
        json={"exposure": 10, "contrast": 0, "saturation": 0, "warmth": 0},
    )
    assert denied.status_code == 400
    video_page = client.get(f"/media/{video}", cookies={"lang": "en"})
    assert "detail-adjust-exposure" not in video_page.text


def test_photo_quick_look_persists_and_exports_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from orga_drone.app import create_app
    from orga_drone.config import Settings
    from orga_drone.i18n import clear_catalog_cache
    from orga_drone.studio_looks import look_image_adjust

    clear_catalog_cache()
    monkeypatch.setattr("orga_drone.app.settings", Settings(data_dir=tmp_path / "data"))
    _isolate(monkeypatch, tmp_path)
    app = create_app()
    db = app.state.db
    mid = _add_photo(db, tmp_path / "lib", "look.jpg", size=(120, 80))
    # Soft teal so a vibrant look measurably boosts chroma.
    path = Path(db.get_media(mid).path)
    Image.new("RGB", (120, 80), (60, 140, 150)).save(path, format="JPEG", quality=95)
    client = TestClient(app)
    applied = client.post(
        f"/api/media/{mid}/image-adjust",
        json={"look_id": "vibrant"},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["look_id"] == "vibrant"
    assert body["image"]["saturation"] == look_image_adjust("vibrant").saturation
    page = client.get(f"/media/{mid}", cookies={"lang": "en"})
    assert 'data-photo-look="vibrant"' in page.text
    assert db.get_photo_look_id(path) == "vibrant"
    out = tmp_path / "out"
    out.mkdir()
    graded = run_media_export(
        db,
        mid,
        preset="best",
        output_path=out / "look_best.jpg",
        image=db.get_image_adjust(path),
    )
    neutral = run_media_export(
        db,
        mid,
        preset="best",
        output_path=out / "look_neutral.jpg",
        image=ImageAdjust(),
    )
    assert graded.read_bytes() != neutral.read_bytes()
    with Image.open(graded) as gimg, Image.open(neutral) as nimg:
        g = gimg.convert("RGB").getpixel((60, 40))
        n = nimg.convert("RGB").getpixel((60, 40))
    assert isinstance(g, tuple) and isinstance(n, tuple)
    # Vibrant raises saturation — channels should diverge from neutral gray.
    assert max(g) - min(g) > max(n) - min(n)
    # Slider edit clears the named look.
    custom = client.post(
        f"/api/media/{mid}/image-adjust",
        json={"exposure": 5, "contrast": 0, "saturation": 10, "warmth": 0, "look_id": ""},
    )
    assert custom.status_code == 200
    assert custom.json()["look_id"] == ""
    assert db.get_photo_look_id(path) == ""


def test_video_presets_use_encoder_frame_without_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    mid = _add_video(db, tmp_path / "lib", "clip.mp4", height=2160, duration_s=4.0)
    out = tmp_path / "out"
    out.mkdir()
    best = prepare_media_export(
        db, mid, preset="best", output_path=out / "clip_best.mp4"
    )
    tiktok = prepare_media_export(
        db, mid, preset="tiktok", output_path=out / "clip_tiktok.mp4"
    )
    assert best.config is not None
    assert best.config.width == 3840
    assert best.config.height == 2160
    assert best.config.music_tracks == ()
    assert len(best.config.clips) == 1
    assert tiktok.config is not None
    assert (tiktok.config.width, tiktok.config.height) == (1080, 1920)
    assert tiktok.config.clips[0].kind == "video"
    options = build_media_export_options_payload(db, mid)
    by_id = {row["id"]: row for row in options["presets"]}
    assert by_id["best"]["height"] == 2160
    assert by_id["instagram"]["width"] == 1080
    assert by_id["instagram"]["height"] == 1920
    assert "1080x1920" in str(by_id["whatsapp"]["suggested_filename"])
    assert db.list_studio_projects() == []
