"""Collage export disk-safety and publication regressions (#487 / #489)."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.export.studio_encoder import ExportCancelled, StudioExportError
from orga_drone.ffmpeg_bin import find_ffmpeg, find_ffprobe, subprocess_no_window_kwargs
from orga_drone.studio_collage import (
    assign_leaf_media,
    collage_spec_from_raw,
    iter_leaves,
)
import orga_drone.studio_collage_export as collage
from orga_drone.studio_collage_export import (
    COLLAGE_STAGING_DISK_FULL_MESSAGE,
    COLLAGE_STAGING_FREE_SPACE_RESERVE_BYTES,
    estimate_composed_jpeg_bytes,
    ensure_staging_space,
    render_collage_mp4_segment,
)
from orga_drone.studio_export import run_studio_export, translate_export_error


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    prefs = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("orga_drone.app_prefs.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_export.settings", prefs)
    monkeypatch.setattr("orga_drone.config.settings", prefs)
    monkeypatch.setattr("orga_drone.studio_collage_still.settings", prefs)
    monkeypatch.setattr("orga_drone.app.settings", prefs)
    return prefs


def _rgb(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG", quality=90)


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


def _photo_collage(db: Database, tmp_path: Path, *, duration_s: float = 0.2):
    root = tmp_path / "media"
    left = root / "left.jpg"
    right = root / "right.jpg"
    _rgb(left, (160, 90), (220, 40, 40))
    _rgb(right, (160, 90), (40, 40, 220))
    left_id = _add_photo(db, root, "left.jpg", left)
    right_id = _add_photo(db, root, "right.jpg", right)
    project = db.ensure_default_studio_project()
    assert project is not None
    clip = db.add_studio_collage(project.id, preset="1+1", collage_duration_s=duration_s)
    spec = collage_spec_from_raw(clip.collage_spec)
    leaves = iter_leaves(spec["root"])
    spec = assign_leaf_media(
        spec,
        leaves[0]["id"],
        {"source": "library", "media_id": left_id, "kind": "photo"},
    )
    spec = assign_leaf_media(
        spec,
        leaves[1]["id"],
        {"source": "library", "media_id": right_id, "kind": "photo"},
    )
    clip = db.update_studio_collage(clip.id, collage_spec=spec, collage_duration_s=duration_s)
    return project, clip, spec


def _make_video(path: Path) -> None:
    ffmpeg = find_ffmpeg()
    assert ffmpeg
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x90:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        **subprocess_no_window_kwargs(),
    )


def test_estimate_composed_jpeg_bytes_scales_and_has_floor() -> None:
    tiny = estimate_composed_jpeg_bytes(16, 9)
    assert tiny == 64_000
    hd = estimate_composed_jpeg_bytes(1920, 1080)
    uhd = estimate_composed_jpeg_bytes(3840, 2160)
    assert hd > tiny
    assert uhd > hd


@pytest.mark.parametrize(
    ("free", "next_write", "staged", "reserve", "ok"),
    [
        (2 * 1024**3, 100, 0, 1 * 1024**3, True),
        (1 * 1024**3 + 50, 100, 0, 1 * 1024**3, False),
        (1 * 1024**3, 0, 0, 1 * 1024**3, True),
        (1 * 1024**3 - 1, 0, 0, 1 * 1024**3, False),
        (1 * 1024**3 + 200, 100, 150, 1 * 1024**3, False),
        (500, 10, 0, 0, True),
        (9, 10, 0, 0, False),
    ],
)
def test_ensure_staging_space_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    free: int,
    next_write: int,
    staged: int,
    reserve: int,
    ok: bool,
) -> None:
    monkeypatch.setattr(collage, "_staging_free_bytes_override", free)
    if ok:
        ensure_staging_space(
            tmp_path,
            next_write_bytes=next_write,
            staged_bytes=staged,
            reserve_bytes=reserve,
        )
    else:
        with pytest.raises(StudioExportError, match="Not enough temporary disk space"):
            ensure_staging_space(
                tmp_path,
                next_write_bytes=next_write,
                staged_bytes=staged,
                reserve_bytes=reserve,
            )


def test_low_space_before_render_preserves_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    project, _clip, _spec = _photo_collage(db, tmp_path, duration_s=0.2)
    dest = prefs.data_dir / "exports" / "story.mp4"
    dest.parent.mkdir(parents=True)
    original = b"existing export bytes"
    dest.write_bytes(original)
    monkeypatch.setattr(collage, "_staging_free_bytes_override", 1024)

    with pytest.raises(StudioExportError, match="Not enough temporary disk space"):
        run_studio_export(
            db, height=720, output_path=dest, project_id=project.id, overwrite=True
        )
    assert dest.read_bytes() == original
    assert list(dest.parent.iterdir()) == [dest]
    assert not list((prefs.data_dir / "tmp" / "collage-export").glob("*.mp4"))


def test_low_space_after_real_frames_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    project, clip, spec = _photo_collage(db, tmp_path, duration_s=1.0)
    video = tmp_path / "cell.mp4"
    _make_video(video)
    leaves = iter_leaves(spec["root"])
    spec = assign_leaf_media(
        spec,
        leaves[0]["id"],
        {"source": "external", "kind": "video", "path": str(video)},
    )
    db.update_studio_collage(clip.id, collage_spec=spec, collage_duration_s=1.0)
    dest = prefs.data_dir / "exports" / "story.mp4"
    dest.parent.mkdir(parents=True)
    original = b"keep me"
    dest.write_bytes(original)

    reserve = COLLAGE_STAGING_FREE_SPACE_RESERVE_BYTES
    checks = {"n": 0}

    def provider(path: Path) -> int:
        checks["n"] += 1
        if checks["n"] <= 3:
            return reserve + 8 * 1024**3
        return reserve // 2

    monkeypatch.setattr(collage, "_staging_free_bytes_provider", provider)

    with pytest.raises(StudioExportError, match="Not enough temporary disk space"):
        run_studio_export(
            db, height=720, output_path=dest, project_id=project.id, overwrite=True
        )
    assert checks["n"] >= 4
    assert dest.read_bytes() == original
    assert list(dest.parent.iterdir()) == [dest]
    assert not list((prefs.data_dir / "tmp" / "collage-export").glob("*.mp4"))


def test_env_budget_low_space_before_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    project, _clip, _spec = _photo_collage(db, tmp_path, duration_s=0.2)
    dest = prefs.data_dir / "exports" / "story.mp4"
    dest.parent.mkdir(parents=True)
    original = b"env-sentinel"
    dest.write_bytes(original)
    monkeypatch.setenv("ORGA_DRONE_E2E", "1")
    monkeypatch.setenv(collage.COLLAGE_STAGING_FREE_BYTES_ENV, "2048")

    with pytest.raises(StudioExportError, match="Not enough temporary disk space"):
        run_studio_export(
            db, height=720, output_path=dest, project_id=project.id, overwrite=True
        )
    assert dest.read_bytes() == original


def test_cancel_during_collage_render_cleans_and_preserves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    project, clip, spec = _photo_collage(db, tmp_path, duration_s=1.0)
    video = tmp_path / "cell.mp4"
    _make_video(video)
    leaves = iter_leaves(spec["root"])
    spec = assign_leaf_media(
        spec,
        leaves[0]["id"],
        {"source": "external", "kind": "video", "path": str(video)},
    )
    db.update_studio_collage(clip.id, collage_spec=spec, collage_duration_s=1.0)
    dest = prefs.data_dir / "exports" / "story.mp4"
    dest.parent.mkdir(parents=True)
    original = b"sentinel-cancel"
    dest.write_bytes(original)
    cancel = threading.Event()
    frames = {"n": 0}
    real_write = collage._write_composed_jpeg

    def write_then_cancel(canvas, dest_path, **kwargs):
        frames["n"] += 1
        size = real_write(canvas, dest_path, **kwargs)
        if frames["n"] >= 3:
            cancel.set()
        return size

    monkeypatch.setattr(collage, "_write_composed_jpeg", write_then_cancel)
    with pytest.raises(ExportCancelled):
        run_studio_export(
            db,
            height=720,
            output_path=dest,
            project_id=project.id,
            overwrite=True,
            cancel_event=cancel,
        )
    assert dest.read_bytes() == original
    assert not list((prefs.data_dir / "tmp" / "collage-export").glob("*.mp4"))


def test_encoder_failure_preserves_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    project, _clip, _spec = _photo_collage(db, tmp_path, duration_s=0.2)
    dest = prefs.data_dir / "exports" / "story.mp4"
    dest.parent.mkdir(parents=True)
    original = b"existing"
    dest.write_bytes(original)

    def fail_encode(cmd: list[str], **kwargs: object) -> None:
        Path(cmd[-1]).write_bytes(b"incomplete")
        raise StudioExportError("simulated encoder failure")

    monkeypatch.setattr(collage, "_run_ffmpeg", fail_encode)
    with pytest.raises(StudioExportError, match="simulated encoder failure"):
        run_studio_export(
            db, height=720, output_path=dest, project_id=project.id, overwrite=True
        )
    assert dest.read_bytes() == original
    assert not list((prefs.data_dir / "tmp" / "collage-export").glob("*.mp4"))


def test_successful_export_with_space_decodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    project, _clip, _spec = _photo_collage(db, tmp_path, duration_s=0.5)
    dest = prefs.data_dir / "exports" / "story.mp4"
    dest.parent.mkdir(parents=True)
    published = run_studio_export(
        db, height=720, output_path=dest, project_id=project.id
    )
    assert published.is_file()
    assert published.stat().st_size > 1000
    ffmpeg = find_ffmpeg()
    assert ffmpeg
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(published), "-f", "null", "-"],
        capture_output=True,
        text=True,
        **subprocess_no_window_kwargs(),
    )
    assert probe.returncode == 0
    # Duration/dimensions completeness for the photo-hold collage segment.
    import json

    ffprobe = find_ffprobe()
    if ffprobe:
        probe2 = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height:format=duration",
                "-of",
                "json",
                str(published),
            ],
            capture_output=True,
            text=True,
            **subprocess_no_window_kwargs(),
        )
        assert probe2.returncode == 0
        info = json.loads(probe2.stdout)
        stream = info["streams"][0]
        assert int(stream["width"]) == 1280
        assert int(stream["height"]) == 720
        assert float(info["format"]["duration"]) >= 0.4


def test_low_space_error_is_localized() -> None:
    exc = StudioExportError(
        COLLAGE_STAGING_DISK_FULL_MESSAGE, code="collage_staging_disk_full"
    )
    de = {
        COLLAGE_STAGING_DISK_FULL_MESSAGE: (
            "Nicht genug temporärer Speicherplatz. Gib Speicherplatz frei und versuche es erneut."
        )
    }
    assert translate_export_error(exc, de.__getitem__) == de[COLLAGE_STAGING_DISK_FULL_MESSAGE]


def test_removing_disk_guard_breaks_low_space_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression contract: without the guard, a simulated full volume proceeds."""
    _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    _project, _clip, spec = _photo_collage(db, tmp_path, duration_s=0.2)
    dest = tmp_path / "blocked.mp4"
    monkeypatch.setattr(collage, "_staging_free_bytes_override", 1)

    with pytest.raises(StudioExportError, match="Not enough temporary disk space"):
        render_collage_mp4_segment(
            db, spec, dest, width=1280, height=720, duration_s=0.2
        )

    monkeypatch.setattr(
        collage,
        "ensure_staging_space",
        lambda *args, **kwargs: None,
    )
    out = tmp_path / "unguarded.mp4"
    render_collage_mp4_segment(
        db, spec, out, width=1280, height=720, duration_s=0.2
    )
    assert out.is_file() and out.stat().st_size > 0
