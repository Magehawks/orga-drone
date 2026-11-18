"""Studio collage MP4 segment export (ADR 0038 / #462)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.export.studio_encoder import StudioExportError
from orga_drone.studio_collage import (
    assign_leaf_media,
    collage_spec_from_raw,
    iter_leaves,
    preset_spec,
)
from orga_drone.studio_collage_export import (
    collage_has_video_leaf,
    render_collage_mp4_segment,
)
from orga_drone.studio_export import prepare_studio_export, run_studio_export


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


def test_collage_has_video_leaf_detects_kind() -> None:
    spec = preset_spec("1+1")
    assert collage_has_video_leaf(spec) is False
    leaves = iter_leaves(spec["root"])
    with_video = assign_leaf_media(
        spec,
        leaves[0]["id"],
        {"source": "library", "media_id": 1, "kind": "video"},
    )
    assert collage_has_video_leaf(with_video) is True


@pytest.mark.parametrize(("kind", "suffix"), [("photo", ".jpg"), ("video", ".mp4")])
def test_missing_assigned_source_blocks_story_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, suffix: str
) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    project = db.ensure_default_studio_project()
    assert project is not None
    spec = preset_spec("1+1")
    spec = assign_leaf_media(
        spec,
        iter_leaves(spec["root"])[0]["id"],
        {"source": "external", "path": str(tmp_path / f"missing{suffix}"), "kind": kind},
    )
    db.add_studio_collage(project.id, collage_spec=spec, collage_duration_s=1.0)
    dest = prefs.data_dir / "exports" / "story.mp4"
    dest.parent.mkdir(parents=True)
    original = b"existing export"
    dest.write_bytes(original)

    with pytest.raises(StudioExportError, match="source is unavailable"):
        run_studio_export(
            db, height=720, output_path=dest, project_id=project.id, overwrite=True
        )
    assert dest.read_bytes() == original
    assert list(dest.parent.iterdir()) == [dest]
    assert not list((prefs.data_dir / "tmp" / "collage-export").glob("*.mp4"))


def test_story_cleans_up_failed_segment_and_preserves_existing_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    project = db.ensure_default_studio_project()
    assert project is not None
    db.add_studio_collage(project.id, preset="1+1", collage_duration_s=1.0)
    dest = prefs.data_dir / "exports" / "story.mp4"
    dest.parent.mkdir(parents=True)
    original = b"existing export"
    dest.write_bytes(original)
    staging: list[Path] = []

    def fail_encode(cmd: list[str], **kwargs: object) -> None:
        Path(cmd[-1]).write_bytes(b"incomplete segment")
        staging.append(Path(cmd[cmd.index("-i") + 1]).parent)
        raise StudioExportError("simulated encoder failure")

    monkeypatch.setattr("orga_drone.studio_collage_export._run_ffmpeg", fail_encode)
    with pytest.raises(StudioExportError, match="simulated encoder failure"):
        run_studio_export(db, height=720, output_path=dest, project_id=project.id)
    assert dest.read_bytes() == original
    assert list(dest.parent.iterdir()) == [dest]
    assert staging and not staging[0].exists()
    assert not list((prefs.data_dir / "tmp" / "collage-export").glob("*.mp4"))


def test_photo_collage_mp4_segment_and_project_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs = _isolate(monkeypatch, tmp_path)
    db = Database(tmp_path / "lib.sqlite3")
    root = tmp_path / "media"
    left = root / "left.jpg"
    right = root / "right.jpg"
    _rgb(left, (320, 180), (220, 40, 40))
    _rgb(right, (320, 180), (40, 40, 220))
    left_id = _add_photo(db, root, "left.jpg", left)
    right_id = _add_photo(db, root, "right.jpg", right)
    project = db.ensure_default_studio_project()
    assert project is not None
    clip = db.add_studio_collage(project.id, preset="1+1", collage_duration_s=1.0)
    leaves = iter_leaves(collage_spec_from_raw(clip.collage_spec)["root"])
    spec = assign_leaf_media(
        collage_spec_from_raw(clip.collage_spec),
        leaves[0]["id"],
        {"source": "library", "media_id": left_id, "kind": "photo"},
    )
    spec = assign_leaf_media(
        spec,
        leaves[1]["id"],
        {"source": "library", "media_id": right_id, "kind": "photo"},
    )
    clip = db.update_studio_collage(clip.id, collage_spec=spec, collage_duration_s=1.0)

    segment = tmp_path / "segment.mp4"
    render_collage_mp4_segment(
        db,
        collage_spec_from_raw(clip.collage_spec),
        segment,
        width=1280,
        height=720,
        duration_s=1.0,
    )
    assert segment.is_file()
    assert segment.stat().st_size > 1000

    dest = prefs.data_dir / "exports" / "story.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    config = prepare_studio_export(
        db,
        height=720,
        output_path=dest,
        project_id=project.id,
    )
    assert any(c.kind == "collage" for c in config.clips)
    published = run_studio_export(
        db,
        height=720,
        output_path=dest,
        project_id=project.id,
    )
    assert published.is_file()
    assert published.stat().st_size > 1000
