"""Regression tests for export overwrite and cross-project repath (Issue #134)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import (
    ExportCancelled,
    FfmpegStudioEncoder,
    StudioExportError,
)
from orga_drone.studio_cut import section_repeats_from_effect_settings
from orga_drone.studio_export import prepare_studio_export, run_studio_export
from orga_drone.studio_mask import masks_from_effect_settings
from tests.test_studio_export import _seed_media

_PROTECTED = "library source or project asset"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _add_clip(db: Database, media_id: int, *, project_id: int | None = None) -> int:
    item = db.get_media(media_id)
    assert item is not None
    clip_id, _created = db.add_studio_item(
        item.path,
        identity_key=make_identity_key(
            item.filename, item.size_bytes, item.recorded_at
        ),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind=item.kind,
        project_id=project_id,
        source_media_id=media_id,
    )
    return clip_id


def _prefs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "orga_drone.app_prefs.settings",
        Settings(data_dir=tmp_path / "data"),
    )


def test_export_refuses_source_path_even_with_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    mid = _seed_media(db, root, height=720, width=1280, content=b"source-bytes")
    _add_clip(db, mid)
    source = root / "CLIP.MP4"
    digest = _sha256(source)
    called = {"n": 0}

    class _Encoder:
        def render(self, config: StudioExportConfig, **_kwargs: object) -> Path:
            called["n"] += 1
            config.output_path.write_bytes(b"overwritten")
            return config.output_path

    with pytest.raises(StudioExportError, match=_PROTECTED):
        run_studio_export(
            db,
            height=720,
            output_path=source,
            overwrite=True,
            encoder=_Encoder(),
        )
    assert called["n"] == 0
    assert _sha256(source) == digest
    assert source.read_bytes() == b"source-bytes"


def test_export_refuses_case_and_link_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    mid = _seed_media(db, root, height=720, width=1280, content=b"source-bytes")
    _add_clip(db, mid)
    source = root / "CLIP.MP4"
    digest = _sha256(source)

    aliases: list[Path] = []
    folded = source.with_name(source.name.swapcase())
    if folded.exists() and os.path.samefile(folded, source):
        aliases.append(folded)
    hard = root / "CLIP-HARD.MP4"
    try:
        os.link(source, hard)
    except OSError:
        hard = None  # type: ignore[assignment]
    else:
        aliases.append(hard)
    link = root / "CLIP-LINK.MP4"
    try:
        link.symlink_to(source)
    except OSError:
        link = None  # type: ignore[assignment]
    else:
        aliases.append(link)
    assert aliases, "need at least one path alias to the source file"

    for alias in aliases:
        with pytest.raises(StudioExportError, match=_PROTECTED):
            prepare_studio_export(
                db,
                height=720,
                output_path=alias,
                overwrite=True,
            )
        assert _sha256(source) == digest


def test_export_refuses_indexed_asset_and_soundtrack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    mid = _seed_media(db, root, height=720, width=1280, content=b"source-bytes")
    clip_id = _add_clip(db, mid)
    item = db.get_media(mid)
    assert item is not None
    project_id = db.list_studio_items()[0].project_id

    asset = root / "SIDECAR.MP4"
    asset.write_bytes(b"asset-bytes")
    db.upsert_asset(
        root_id=item.root_id,
        path=asset,
        kind="video",
        size_bytes=len(b"asset-bytes"),
        mtime=None,
        stem_base="SIDECAR",
    )
    song = root / "SONG.MP4"
    song.write_bytes(b"song-bytes")
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO studio_audio_clips(
                 project_id, lane, position, file_path, display_name, added_at
               ) VALUES (?, 'music', 0, ?, 'SONG.MP4', '2024-01-01T00:00:00')""",
            (project_id, str(song.resolve())),
        )

    for protected in (asset, song):
        digest = _sha256(protected)
        with pytest.raises(StudioExportError, match=_PROTECTED):
            prepare_studio_export(
                db,
                height=720,
                output_path=protected,
                overwrite=True,
                project_id=project_id,
            )
        assert _sha256(protected) == digest
    assert db.list_studio_items(project_id)[0].id == clip_id
    assert (root / "CLIP.MP4").read_bytes() == b"source-bytes"


def test_source_sha256_unchanged_on_success_failure_and_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    mid = _seed_media(db, root, height=720, width=1280, content=b"source-bytes")
    _add_clip(db, mid)
    source = root / "CLIP.MP4"
    digest = _sha256(source)

    class _Ok:
        def render(self, config: StudioExportConfig, **_kwargs: object) -> Path:
            config.output_path.write_bytes(b"mp4-bytes")
            return config.output_path

    class _Fail:
        def render(self, config: StudioExportConfig, **_kwargs: object) -> Path:
            raise StudioExportError("encoder failed")

    class _Cancel:
        def render(self, config: StudioExportConfig, **_kwargs: object) -> Path:
            raise ExportCancelled()

    ok_dest = tmp_path / "out" / "story.mp4"
    ok_dest.parent.mkdir()
    run_studio_export(
        db, height=720, output_path=ok_dest, overwrite=True, encoder=_Ok()
    )
    assert _sha256(source) == digest
    assert ok_dest.read_bytes() == b"mp4-bytes"

    with pytest.raises(StudioExportError, match="encoder failed"):
        run_studio_export(
            db,
            height=720,
            output_path=tmp_path / "out" / "fail.mp4",
            overwrite=True,
            encoder=_Fail(),
        )
    assert _sha256(source) == digest

    with pytest.raises(ExportCancelled):
        run_studio_export(
            db,
            height=720,
            output_path=tmp_path / "out" / "cancel.mp4",
            overwrite=True,
            encoder=_Cancel(),
        )
    assert _sha256(source) == digest
    assert source.read_bytes() == b"source-bytes"


def test_encoder_refuses_to_replace_source_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "CLIP.MP4"
    source.write_bytes(b"original-source-bytes")
    digest = _sha256(source)
    invoked = {"n": 0}

    def _popen(*_args: object, **_kwargs: object) -> None:
        invoked["n"] += 1
        raise AssertionError("ffmpeg must not run when the destination is a source")

    monkeypatch.setattr(
        "orga_drone.export.studio_encoder.find_ffmpeg", lambda: "ffmpeg"
    )
    monkeypatch.setattr("orga_drone.export.studio_encoder.subprocess.Popen", _popen)
    clip = StudioExportClip(source_path=source, kind="video", duration_s=1.0)
    config = StudioExportConfig(
        output_path=source, width=1280, height=720, clips=(clip,)
    )
    with pytest.raises(StudioExportError, match=_PROTECTED):
        FfmpegStudioEncoder().render(config)
    assert invoked["n"] == 0
    assert _sha256(source) == digest


def test_repath_preserves_cross_project_clip_edits(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    mid = _seed_media(db, root, filename="OLD.MP4", content=b"old-bytes")
    item = db.get_media(mid)
    assert item is not None
    project_a = db.create_studio_project("Trip A")
    project_b = db.create_studio_project("Trip B")
    clip_a = _add_clip(db, mid, project_id=project_a.id)
    db.set_studio_section(clip_a, source_in_s=1.0, source_out_s=3.0, repeats=2)
    _clips, speed_id = db.set_studio_playback_speed(clip_a, 0.5)
    assert speed_id == clip_a
    db.set_studio_masks(
        clip_a,
        {"masks": [{"id": "mask-a", "effect": "pixelate", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.2}]},
    )

    new_file = root / "NEW.MP4"
    new_file.write_bytes(b"new-bytes")
    new_path = str(new_file.resolve())
    clip_b, _created = db.add_studio_item(
        new_path,
        identity_key="other-identity",
        filename="NEW.MP4",
        recorded_at=None,
        kind="video",
        project_id=project_b.id,
    )
    db.set_studio_masks(
        clip_b,
        {"masks": [{"id": "mask-b", "effect": "blur", "x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}]},
    )
    before_b = {c.id: c for c in db.list_studio_items(project_b.id)}[clip_b]

    db.repath_file(item.path, new_path, new_stem="NEW")

    after_a = {c.id: c for c in db.list_studio_items(project_a.id)}
    after_b = {c.id: c for c in db.list_studio_items(project_b.id)}
    assert clip_a in after_a
    assert clip_b in after_b
    kept = after_a[clip_a]
    other = after_b[clip_b]
    assert kept.media_path == new_path
    assert kept.position == 1
    assert kept.source_start == pytest.approx(1.0)
    assert kept.source_end == pytest.approx(3.0)
    assert kept.playback_speed == pytest.approx(0.5)
    assert section_repeats_from_effect_settings(kept.effect_settings) == 2
    masks_a = masks_from_effect_settings(kept.effect_settings)
    assert [mask.id for mask in masks_a] == ["mask-a"]
    assert masks_a[0].effect == "pixelate"
    assert other.id == before_b.id
    assert other.position == before_b.position
    assert other.media_path == new_path
    masks_b = masks_from_effect_settings(other.effect_settings)
    assert [mask.id for mask in masks_b] == ["mask-b"]
    assert (root / "OLD.MP4").read_bytes() == b"old-bytes"
    assert new_file.read_bytes() == b"new-bytes"
