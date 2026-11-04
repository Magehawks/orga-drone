"""Photo-only Studio export: resolution unlock + shared photo duration timeline."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_encoder import FfmpegStudioEncoder
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_estimate import DEFAULT_PHOTO_DURATION_S, effective_seconds
from orga_drone.studio_export import StudioExportError, prepare_studio_export
from orga_drone.studio_transition import story_length_s


def _write_jpeg(path: Path, *, size: tuple[int, int] = (320, 240)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (40, 80, 120)).save(path, format="JPEG")


def _ensure_root(db: Database, root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    return db.add_root(root, label=root.name)


def _add_photo(db: Database, root: Path, name: str) -> int:
    root_id = _ensure_root(db, root)
    photo = root / name
    _write_jpeg(photo)
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


def _add_video(db: Database, root: Path, name: str, *, duration_s: float) -> int:
    root_id = _ensure_root(db, root)
    video = root / name
    video.write_bytes(b"fake-mp4")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": name,
            "path": str(video.resolve()),
            "size_bytes": 8,
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
            "width": 1280,
            "height": 720,
        }
    )


def _studio_add(db: Database, media_id: int, project_id: int) -> int:
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _ = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(item.filename, item.size_bytes, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        project_id=project_id,
        source_media_id=item.id,
    )
    return clip_id


def test_single_photo_prepare_uses_default_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("One photo")
    mid = _add_photo(db, tmp_path / "lib", "a.jpg")
    _studio_add(db, mid, project.id)
    cfg = prepare_studio_export(
        db,
        height=1080,
        output_path=tmp_path / "out.mp4",
        overwrite=True,
        project_id=project.id,
    )
    assert len(cfg.clips) == 1
    assert cfg.clips[0].kind == "photo"
    assert cfg.clips[0].duration_s == DEFAULT_PHOTO_DURATION_S
    assert cfg.height == 1080
    assert cfg.width == 1920


def test_multiple_photos_preserve_order_and_total_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Slideshow")
    ids = [
        _add_photo(db, tmp_path / "lib", "a.jpg"),
        _add_photo(db, tmp_path / "lib", "b.jpg"),
        _add_photo(db, tmp_path / "lib", "c.jpg"),
    ]
    for mid in ids:
        _studio_add(db, mid, project.id)
    cfg = prepare_studio_export(
        db,
        height=720,
        output_path=tmp_path / "out.mp4",
        overwrite=True,
        project_id=project.id,
    )
    assert [c.source_path.name for c in cfg.clips] == ["a.jpg", "b.jpg", "c.jpg"]
    assert all(c.duration_s == DEFAULT_PHOTO_DURATION_S for c in cfg.clips)
    assert story_length_s([c.duration_s for c in cfg.clips], []) == pytest.approx(
        3 * DEFAULT_PHOTO_DURATION_S
    )


def test_mixed_video_photo_effective_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Mixed")
    v1 = _add_video(db, tmp_path / "lib", "v1.mp4", duration_s=5.0)
    p1 = _add_photo(db, tmp_path / "lib", "p1.jpg")
    v2 = _add_video(db, tmp_path / "lib", "v2.mp4", duration_s=4.0)
    for mid in (v1, p1, v2):
        _studio_add(db, mid, project.id)

    items = db.list_studio_items(project.id)
    seconds = [
        effective_seconds(
            kind=it.kind or "unknown",
            photo_duration_s=it.photo_duration_s,
            duration_s=it.duration_s,
            available=it.available,
            source_in_s=it.source_start,
            source_out_s=it.source_end,
        )
        for it in items
    ]
    assert seconds == [5.0, DEFAULT_PHOTO_DURATION_S, 4.0]

    cfg = prepare_studio_export(
        db,
        height=720,
        output_path=tmp_path / "out.mp4",
        overwrite=True,
        project_id=project.id,
    )
    assert [c.kind for c in cfg.clips] == ["video", "photo", "video"]
    assert [c.duration_s for c in cfg.clips] == [5.0, DEFAULT_PHOTO_DURATION_S, 4.0]


def test_empty_studio_export_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Empty")
    with pytest.raises(StudioExportError, match="Story is empty"):
        prepare_studio_export(
            db,
            height=1080,
            output_path=tmp_path / "out.mp4",
            overwrite=True,
            project_id=project.id,
        )


def test_missing_photo_file_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Missing")
    mid = _add_photo(db, tmp_path / "lib", "gone.jpg")
    item = db.get_media(mid)
    assert item is not None
    Path(item.path).unlink()
    _studio_add(db, mid, project.id)
    with pytest.raises(StudioExportError, match="Original source unavailable.*gone.jpg"):
        prepare_studio_export(
            db,
            height=1080,
            output_path=tmp_path / "out.mp4",
            overwrite=True,
            project_id=project.id,
        )


def test_photo_only_ffmpeg_export_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Photo export")
    for name in ("one.jpg", "two.jpg"):
        mid = _add_photo(db, tmp_path / "lib", name)
        _studio_add(db, mid, project.id)
    out = tmp_path / "slideshow.mp4"
    cfg = prepare_studio_export(
        db, height=720, output_path=out, overwrite=True, project_id=project.id
    )
    assert FfmpegStudioEncoder().render(cfg) == out
    assert out.is_file()
    assert out.stat().st_size > 0


@pytest.mark.parametrize("suffix", ["jpg", "png"])
def test_available_photo_readiness(tmp_path, monkeypatch, suffix):
    from orga_drone.studio_export import build_export_options_payload

    monkeypatch.setattr("orga_drone.app_prefs.settings", Settings(data_dir=tmp_path / "data"))
    db = Database(tmp_path / "db.sqlite3")
    project = db.create_studio_project("Photos")
    mid = _add_photo(db, tmp_path / "lib", f"one.{suffix}")
    if suffix == "png":
        Image.new("RGB", (320, 240), "red").save(tmp_path / "lib" / "one.png")
    _studio_add(db, mid, project.id)
    payload = build_export_options_payload(db, project.id)
    assert payload["readiness"] == "ready"
    assert [o["height"] for o in payload["options"]] == [720, 1080]
    cfg = prepare_studio_export(db, height=720, output_path=tmp_path / "out.mp4", project_id=project.id)
    if find_ffmpeg():
        assert FfmpegStudioEncoder().render(cfg).is_file()


@pytest.mark.parametrize("failure", ["missing", "orphan", "outside_root"])
@pytest.mark.parametrize("count", [1, 2])
def test_unavailable_source_blocks_complete_story(tmp_path, monkeypatch, failure, count):
    from orga_drone.studio_export import build_export_options_payload

    monkeypatch.setattr("orga_drone.app_prefs.settings", Settings(data_dir=tmp_path / "data"))
    db = Database(tmp_path / "db.sqlite3")
    project = db.create_studio_project("Integrity")
    for n in range(count):
        mid = _add_photo(db, tmp_path / "lib", f"photo{n}.jpg")
        _studio_add(db, mid, project.id)
    before = db.list_studio_items(project.id)
    assert build_export_options_payload(db, project.id)["readiness"] == "ready"
    path = tmp_path / "lib" / f"photo{count - 1}.jpg"
    if failure == "missing":
        path.unlink()
    elif failure == "orphan":
        with db.connect() as conn:
            conn.execute("DELETE FROM media WHERE id = ?", (mid,))
    else:
        with db.connect() as conn:
            conn.execute("UPDATE library_roots SET path = ?", (str(tmp_path / "elsewhere"),))
    payload = build_export_options_payload(db, project.id)
    assert payload["readiness"] == "unavailable_sources"
    assert payload["options"] == []
    assert payload["unavailable_sources"][-1]["filename"] == path.name
    with pytest.raises(StudioExportError, match="Original source unavailable"):
        prepare_studio_export(db, height=720, output_path=tmp_path / "out.mp4", project_id=project.id)
    after = db.list_studio_items(project.id)
    assert [(c.id, c.position, c.effect_settings, c.photo_duration_s) for c in after] == [
        (c.id, c.position, c.effect_settings, c.photo_duration_s) for c in before
    ]
    assert not (tmp_path / "out.mp4").exists()


def test_missing_after_preparation_fails_without_publication(tmp_path, monkeypatch):
    if not find_ffmpeg():
        pytest.skip("ffmpeg not available")
    monkeypatch.setattr("orga_drone.app_prefs.settings", Settings(data_dir=tmp_path / "data"))
    db = Database(tmp_path / "db.sqlite3")
    project = db.create_studio_project("Late loss")
    for name in ("one.jpg", "two.jpg"):
        _studio_add(db, _add_photo(db, tmp_path / "lib", name), project.id)
    out = tmp_path / "out.mp4"
    cfg = prepare_studio_export(db, height=720, output_path=out, project_id=project.id)
    (tmp_path / "lib" / "two.jpg").unlink()
    with pytest.raises(StudioExportError, match="Missing source file: two.jpg"):
        FfmpegStudioEncoder().render(cfg)
    assert not out.exists()
    assert not list(tmp_path.glob("*.partial"))


def test_empty_and_title_card_readiness(tmp_path, monkeypatch):
    from orga_drone.studio_export import build_export_options_payload

    monkeypatch.setattr("orga_drone.app_prefs.settings", Settings(data_dir=tmp_path / "data"))
    db = Database(tmp_path / "db.sqlite3")
    project = db.create_studio_project("Cards")
    assert build_export_options_payload(db, project.id)["readiness"] == "empty"
    db.add_studio_title_card(project.id, title_text="Hello")
    payload = build_export_options_payload(db, project.id)
    assert payload["readiness"] == "ready"
    assert [o["height"] for o in payload["options"]] == [720, 1080]
    assert len(prepare_studio_export(db, height=720, output_path=tmp_path / "out.mp4", project_id=project.id).clips) == 1


def test_video_readiness_preserves_resolution_limits(tmp_path, monkeypatch):
    from orga_drone.studio_export import build_export_options_payload

    monkeypatch.setattr("orga_drone.app_prefs.settings", Settings(data_dir=tmp_path / "data"))
    db = Database(tmp_path / "db.sqlite3")
    project = db.create_studio_project("Video")
    mid = _add_video(db, tmp_path / "lib", "one.mp4", duration_s=2)
    _studio_add(db, mid, project.id)
    assert [o["height"] for o in build_export_options_payload(db, project.id)["options"]] == [720]
    db.update_media_dimensions(mid, width=640, height=480)
    payload = build_export_options_payload(db, project.id)
    assert payload["readiness"] == "no_resolution"
    assert payload["options"] == []


def test_source_error_translates_filename_without_losing_unicode():
    from orga_drone.i18n import get_translator
    from orga_drone.studio_export import UnavailableStudioSource, translate_export_error

    error = UnavailableStudioSource("photo.jpg")
    message = translate_export_error(error, get_translator("de"))
    assert "photo.jpg" in message
    assert "Originaldatei" in message
    assert message != str(error)
