"""Regression tests for export overwrite and cross-project repath (Issue #134)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.export.studio_config import StudioExportClip, StudioExportConfig
from orga_drone.export.studio_encoder import (
    ExportCancelled,
    FfmpegStudioEncoder,
    StudioExportError,
)
from orga_drone.ffmpeg_bin import find_ffmpeg
from orga_drone.studio_overlay import Overlay, resolve_overlay_asset, store_overlay_asset
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


def _require_ffmpeg() -> str:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    return ffmpeg


def _color_mp4(ffmpeg: str, path: Path, color: str) -> None:
    generated = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x180:r=30:d=0.4",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr.decode("utf-8", errors="replace")


def _index_video(db: Database, root: Path, filename: str, ffmpeg: str, color: str) -> int:
    path = root / filename
    _color_mp4(ffmpeg, path, color)
    payload = path.read_bytes()
    if db.list_roots():
        root_id = int(db.list_roots()[0]["id"])
    else:
        root_id = db.add_root(root, label="lib")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": filename,
            "path": str(path.resolve()),
            "size_bytes": len(payload),
            "duration_s": 0.4,
            "width": 1280,
            "height": 720,
            "recorded_at": "2024-01-02T10:00:00",
            "sequence": 1,
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


def _mp4_signature(path: Path) -> None:
    header = path.read_bytes()[:64]
    assert b"ftyp" in header
    assert path.stat().st_size > 0


def test_rename_during_export_does_not_overwrite_indexed_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = _require_ffmpeg()
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    root.mkdir()
    source_id = _index_video(db, root, "CLIP.MP4", ffmpeg, "red")
    other_id = _index_video(db, root, "OTHER.MP4", ffmpeg, "blue")
    assert other_id != source_id
    _add_clip(db, source_id)
    source = root / "CLIP.MP4"
    other = root / "OTHER.MP4"
    source_hash = _sha256(source)
    other_bytes = other.read_bytes()
    other_hash = hashlib.sha256(other_bytes).hexdigest()
    dest = root / "Story.mp4"
    moved = {"done": False}

    def on_progress(payload: dict[str, object]) -> None:
        if moved["done"] or payload.get("phase") != "rendering":
            return
        os.replace(other, dest)
        moved["done"] = True

    with pytest.raises(StudioExportError):
        run_studio_export(
            db,
            height=720,
            output_path=dest,
            overwrite=True,
            on_progress=on_progress,
        )
    assert moved["done"] is True
    assert _sha256(source) == source_hash
    assert dest.is_file()
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == other_hash
    assert dest.read_bytes() == other_bytes
    assert not other.exists()


def test_rename_before_encoder_start_is_not_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A library file renamed onto the destination after the check is not a target.

    The move happens after prepare_studio_export and before the encoder starts.
    overwrite is false, so the encoder must not adopt the new file.
    """
    ffmpeg = _require_ffmpeg()
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    root.mkdir()
    source_id = _index_video(db, root, "CLIP.MP4", ffmpeg, "red")
    _index_video(db, root, "OTHER.MP4", ffmpeg, "blue")
    _add_clip(db, source_id)
    source = root / "CLIP.MP4"
    other = root / "OTHER.MP4"
    source_hash = _sha256(source)
    other_bytes = other.read_bytes()
    other_hash = hashlib.sha256(other_bytes).hexdigest()
    dest = root / "Story.mp4"
    moved = {"done": False}

    def on_progress(payload: dict[str, object]) -> None:
        if moved["done"] or payload.get("phase") != "preparing":
            return
        os.replace(other, dest)
        moved["done"] = True

    with pytest.raises(StudioExportError, match=_PROTECTED):
        run_studio_export(
            db,
            height=720,
            output_path=dest,
            overwrite=False,
            on_progress=on_progress,
        )
    assert moved["done"] is True
    assert _sha256(source) == source_hash
    assert dest.is_file()
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == other_hash
    assert dest.read_bytes() == other_bytes
    assert not other.exists()


def test_rename_during_approval_is_not_an_overwrite_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An original renamed onto dest inside the approval is not approved.

    The rename runs after the path check and before the destination identity
    is read. The catalog still has the old path, so only the captured file
    identity can recognize the original.
    """
    ffmpeg = _require_ffmpeg()
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    root.mkdir()
    source_id = _index_video(db, root, "CLIP.MP4", ffmpeg, "red")
    _index_video(db, root, "OTHER.MP4", ffmpeg, "blue")
    _add_clip(db, source_id)
    source = root / "CLIP.MP4"
    other = root / "OTHER.MP4"
    source_hash = _sha256(source)
    other_bytes = other.read_bytes()
    other_hash = hashlib.sha256(other_bytes).hexdigest()
    dest = root / "Story.mp4"
    dest.write_bytes(b"ordinary-export")
    moved = {"done": False}
    from orga_drone.export import studio_encoder

    real_reject = studio_encoder.reject_protected_export_destination

    def reject_then_rename(path: Path, protected: Iterable[Path | str]) -> None:
        real_reject(path, protected)
        if moved["done"] or path.name != dest.name:
            return
        os.replace(other, path)
        moved["done"] = True

    monkeypatch.setattr(
        studio_encoder,
        "reject_protected_export_destination",
        reject_then_rename,
    )
    with pytest.raises(StudioExportError, match=_PROTECTED):
        run_studio_export(
            db,
            height=720,
            output_path=dest,
            overwrite=True,
        )
    assert moved["done"] is True
    assert _sha256(source) == source_hash
    assert dest.is_file()
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == other_hash
    assert dest.read_bytes() == other_bytes
    assert not other.exists()


def test_rename_during_identity_capture_keeps_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An in-app rename started while identities are captured cannot replace the original.

    The capture pauses before the second indexed file is identified. rename_media
    then targets the export name. Either the rename or the export is rejected.
    """
    ffmpeg = _require_ffmpeg()
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    root.mkdir()
    source_id = _index_video(db, root, "CLIP.MP4", ffmpeg, "red")
    other_id = _index_video(db, root, "OTHER.MP4", ffmpeg, "blue")
    _add_clip(db, source_id)
    source = root / "CLIP.MP4"
    other = root / "OTHER.MP4"
    source_hash = _sha256(source)
    other_bytes = other.read_bytes()
    other_hash = hashlib.sha256(other_bytes).hexdigest()
    dest = root / "Story.MP4"
    from orga_drone import media_mutation
    from orga_drone.export import studio_encoder
    from orga_drone.ops.rename import rename_media

    paused = threading.Event()
    release = threading.Event()
    rename_waiting = threading.Event()
    gate = {"used": False, "export_ident": 0}
    outcome: dict[str, BaseException | None] = {"export": None, "rename": None}

    def before_identity(path: Path) -> None:
        if gate["used"]:
            return
        try:
            matches = path.resolve() == other.resolve()
        except OSError:
            matches = False
        if not matches:
            return
        gate["used"] = True
        gate["export_ident"] = threading.get_ident()

        def about_to_lock() -> None:
            if threading.get_ident() != gate["export_ident"]:
                rename_waiting.set()

        media_mutation.before_media_mutation_lock = about_to_lock
        paused.set()
        assert release.wait(30)

    def run_export() -> None:
        try:
            run_studio_export(
                db,
                height=720,
                output_path=dest,
                overwrite=False,
            )
        except Exception as exc:  # noqa: BLE001
            outcome["export"] = exc

    def run_rename() -> None:
        try:
            item = db.get_media(other_id)
            assert item is not None
            rename_media(db, item, "Story")
        except Exception as exc:  # noqa: BLE001
            outcome["rename"] = exc

    studio_encoder.before_protected_identity = before_identity
    export_thread = threading.Thread(target=run_export)
    rename_thread = threading.Thread(target=run_rename)
    try:
        export_thread.start()
        assert paused.wait(30)
        rename_thread.start()
        assert rename_waiting.wait(30)
        release.set()
        export_thread.join(60)
        rename_thread.join(30)
    finally:
        release.set()
        studio_encoder.before_protected_identity = None
        media_mutation.before_media_mutation_lock = None
        export_thread.join(5)
        rename_thread.join(5)
    assert gate["used"] is True
    assert not export_thread.is_alive()
    assert not rename_thread.is_alive()
    assert outcome["export"] is not None or outcome["rename"] is not None
    assert _sha256(source) == source_hash
    preserved = False
    if other.exists():
        assert other.read_bytes() == other_bytes
        assert _sha256(other) == other_hash
        preserved = True
    if dest.exists() and dest.read_bytes() == other_bytes:
        preserved = True
        assert outcome["export"] is not None
    assert preserved


def test_windows_export_handle_blocks_rename(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows share mode excludes delete")
    from orga_drone.export.studio_encoder import _open_export_target

    dest = tmp_path / "story.mp4"
    dest.write_bytes(b"ordinary-export")
    other = tmp_path / "other.mp4"
    other.write_bytes(b"original-bytes")
    fd = _open_export_target(dest)
    try:
        with pytest.raises(OSError):
            os.replace(other, dest)
        assert other.read_bytes() == b"original-bytes"
        assert dest.read_bytes() == b"ordinary-export"
    finally:
        os.close(fd)


def test_rename_onto_approved_overwrite_keeps_indexed_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Overwrite was confirmed for an ordinary export, then a library file took that name."""
    ffmpeg = _require_ffmpeg()
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    root.mkdir()
    source_id = _index_video(db, root, "CLIP.MP4", ffmpeg, "red")
    _index_video(db, root, "OTHER.MP4", ffmpeg, "blue")
    _add_clip(db, source_id)
    source = root / "CLIP.MP4"
    other = root / "OTHER.MP4"
    source_hash = _sha256(source)
    other_bytes = other.read_bytes()
    other_hash = hashlib.sha256(other_bytes).hexdigest()
    dest = root / "Story.mp4"
    dest.write_bytes(b"ordinary-export")
    moved = {"done": False, "replaced": False}

    def on_progress(payload: dict[str, object]) -> None:
        if moved["done"] or payload.get("phase") != "rendering":
            return
        moved["done"] = True
        try:
            os.replace(other, dest)
        except OSError:
            return
        moved["replaced"] = True

    export_error: StudioExportError | None = None
    try:
        run_studio_export(
            db,
            height=720,
            output_path=dest,
            overwrite=True,
            on_progress=on_progress,
        )
    except StudioExportError as exc:
        export_error = exc
    assert moved["done"] is True
    assert _sha256(source) == source_hash
    if moved["replaced"]:
        assert export_error is not None
        assert hashlib.sha256(dest.read_bytes()).hexdigest() == other_hash
    else:
        assert hashlib.sha256(other.read_bytes()).hexdigest() == other_hash
        assert other.read_bytes() == other_bytes


def test_real_encoder_success_overwrite_and_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = _require_ffmpeg()
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    root.mkdir()
    source_id = _index_video(db, root, "CLIP.MP4", ffmpeg, "green")
    _add_clip(db, source_id)
    source = root / "CLIP.MP4"
    source_hash = _sha256(source)
    dest = tmp_path / "exports" / "story.mp4"
    dest.parent.mkdir()
    dest.write_bytes(b"ordinary-export")

    run_studio_export(
        db,
        height=720,
        output_path=dest,
        overwrite=True,
    )
    assert _sha256(source) == source_hash
    assert dest.read_bytes() != b"ordinary-export"
    _mp4_signature(dest)

    kept = b"ordinary-export-cancel"
    dest.write_bytes(kept)
    event = threading.Event()

    def on_progress(payload: dict[str, object]) -> None:
        if payload.get("phase") == "rendering":
            event.set()

    with pytest.raises(ExportCancelled):
        run_studio_export(
            db,
            height=720,
            output_path=dest,
            overwrite=True,
            on_progress=on_progress,
            cancel_event=event,
        )
    assert dest.read_bytes() == kept
    assert _sha256(source) == source_hash
    released = dest.with_name("released-after-cancel.bin")
    released.write_bytes(b"released-after-cancel")
    os.replace(released, dest)
    assert dest.read_bytes() == b"released-after-cancel"


def test_external_replace_before_identity_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An external rename before identity capture must not become an overwrite.

    The second original is moved onto the existing export name immediately
    before that path is identified. Real FFmpeg is the encoder. The export is
    refused and the original bytes stay intact.
    """
    ffmpeg = _require_ffmpeg()
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    root.mkdir()
    source_id = _index_video(db, root, "CLIP.MP4", ffmpeg, "red")
    other_id = _index_video(db, root, "OTHER.MP4", ffmpeg, "blue")
    assert other_id != source_id
    _add_clip(db, source_id)
    source = root / "CLIP.MP4"
    other = root / "OTHER.MP4"
    source_hash = _sha256(source)
    other_bytes = other.read_bytes()
    other_hash = hashlib.sha256(other_bytes).hexdigest()
    dest = tmp_path / "exports" / "story.mp4"
    dest.parent.mkdir()
    dest.write_bytes(b"ordinary-export")
    from orga_drone.export import studio_encoder

    def before_identity(path: Path) -> None:
        try:
            matches = path.resolve() == other.resolve()
        except OSError:
            matches = False
        if matches and other.is_file():
            os.replace(other, dest)

    studio_encoder.before_protected_identity = before_identity
    try:
        with pytest.raises(StudioExportError, match="library source is missing"):
            run_studio_export(
                db,
                height=720,
                output_path=dest,
                overwrite=True,
            )
    finally:
        studio_encoder.before_protected_identity = None
    assert _sha256(source) == source_hash
    assert not other.exists()
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == other_hash
    assert dest.read_bytes() == other_bytes
    released = dest.with_name("released-after-refusal.bin")
    released.write_bytes(b"released-after-refusal")
    os.replace(released, dest)
    assert dest.read_bytes() == b"released-after-refusal"


def test_offline_source_refuses_overwrite_and_allows_free_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = _require_ffmpeg()
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    root.mkdir()
    source_id = _index_video(db, root, "CLIP.MP4", ffmpeg, "green")
    other_id = _index_video(db, root, "OTHER.MP4", ffmpeg, "blue")
    assert other_id != source_id
    _add_clip(db, source_id)
    source = root / "CLIP.MP4"
    other = root / "OTHER.MP4"
    source_hash = _sha256(source)
    other.unlink()
    dest = tmp_path / "exports" / "story.mp4"
    dest.parent.mkdir()
    ordinary = b"ordinary-export"
    dest.write_bytes(ordinary)

    with pytest.raises(StudioExportError, match="library source is missing"):
        run_studio_export(
            db,
            height=720,
            output_path=dest,
            overwrite=True,
        )
    assert dest.read_bytes() == ordinary
    assert _sha256(source) == source_hash
    assert not other.exists()

    free = dest.with_name("story-free.mp4")
    run_studio_export(
        db,
        height=720,
        output_path=free,
        overwrite=False,
    )
    assert _sha256(source) == source_hash
    assert dest.read_bytes() == ordinary
    assert not other.exists()
    _mp4_signature(free)


def test_export_error_releases_destination_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prefs(monkeypatch, tmp_path)
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    source_id = _seed_media(db, root, height=720, width=1280, content=b"source-bytes")
    _add_clip(db, source_id)
    source = root / "CLIP.MP4"
    source_hash = _sha256(source)
    dest = tmp_path / "exports" / "story.mp4"
    dest.parent.mkdir()
    ordinary = b"ordinary-export"
    dest.write_bytes(ordinary)

    class _Encoder:
        def render(self, config: StudioExportConfig, **_kwargs: object) -> Path:
            assert config.approved_file is not None
            raise StudioExportError("encode failed")

    with pytest.raises(StudioExportError, match="encode failed"):
        run_studio_export(
            db,
            height=720,
            output_path=dest,
            overwrite=True,
            encoder=_Encoder(),
        )
    assert dest.read_bytes() == ordinary
    assert _sha256(source) == source_hash
    released = dest.with_name("released-after-error.bin")
    released.write_bytes(b"released-after-error")
    os.replace(released, dest)
    assert dest.read_bytes() == b"released-after-error"


def test_encoder_keeps_overlay_png_even_as_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = _require_ffmpeg()
    data = tmp_path / "data"
    monkeypatch.setattr("orga_drone.config.settings", Settings(data_dir=data))
    source = tmp_path / "clip.mp4"
    _color_mp4(ffmpeg, source, "red")
    buffer = BytesIO()
    Image.new("RGB", (32, 32), (220, 20, 20)).save(buffer, "PNG")
    asset_name = store_overlay_asset(data, buffer.getvalue())
    asset = resolve_overlay_asset(data, asset_name)
    overlay_hash = _sha256(asset)
    source_hash = _sha256(source)
    clip = StudioExportClip(
        source_path=source,
        kind="video",
        duration_s=0.4,
        overlays=(
            Overlay(
                id="ovimage001",
                kind="image",
                start_s=0.0,
                end_s=0.4,
                x=0.1,
                y=0.1,
                w=0.4,
                h=0.4,
                asset_name=asset_name,
            ),
        ),
    )
    exported = tmp_path / "story.mp4"
    FfmpegStudioEncoder().render(
        StudioExportConfig(
            output_path=exported,
            width=320,
            height=180,
            clips=(clip,),
        )
    )
    _mp4_signature(exported)
    assert _sha256(asset) == overlay_hash
    assert _sha256(source) == source_hash

    with pytest.raises(StudioExportError, match=_PROTECTED):
        FfmpegStudioEncoder().render(
            StudioExportConfig(
                output_path=asset,
                width=320,
                height=180,
                clips=(clip,),
            )
        )
    assert _sha256(asset) == overlay_hash

    alias = tmp_path / "overlay-alias.png"
    try:
        os.link(asset, alias)
    except OSError:
        alias = None
    if alias is not None:
        with pytest.raises(StudioExportError, match=_PROTECTED):
            FfmpegStudioEncoder().render(
                StudioExportConfig(
                    output_path=alias,
                    width=320,
                    height=180,
                    clips=(clip,),
                )
            )
        assert _sha256(asset) == overlay_hash
        assert _sha256(alias) == overlay_hash
