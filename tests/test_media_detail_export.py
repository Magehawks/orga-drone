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
