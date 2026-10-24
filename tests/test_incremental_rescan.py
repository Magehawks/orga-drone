"""Rescan skips metadata extraction when size and mtime are unchanged.

Issue #96 does not name a content fingerprint. The skip signal is file size
plus filesystem mtime (see ADR 0019). These tests are the benchmark: a second
scan must not call ``parse_media_file`` for unchanged media.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from orga_drone.db import Database, make_identity_key
from orga_drone.scan import scan_all_roots, scan_root

_MP4 = b"\x00\x00\x00\x14ftypmp42" + b"\x00" * 32


def _video(path: Path, payload: bytes = _MP4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _by_filename(db: Database, root_id: int) -> dict[str, tuple[int, dict]]:
    """All indexed media, including clips hidden by the browse flow collapse."""
    media = db.media_map_for_root(root_id, kind=None)
    return {str(row["filename"]): (mid, row) for mid, row in media.items()}


def _parse_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import orga_drone.scan as scan_mod

    calls: list[str] = []
    real = scan_mod.parse_media_file

    def wrapped(path: Path):
        calls.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(scan_mod, "parse_media_file", wrapped)
    return calls


def test_noop_rescan_skips_extraction_and_keeps_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = tmp_path / "lib"
    keep = lib / "keep.mp4"
    other = lib / "other.mp4"
    _video(keep)
    _video(other, _MP4 + b"\x01")
    keep_bytes = keep.read_bytes()

    db = Database(tmp_path / "lib.sqlite3")
    root_id = db.add_root(lib, "archive")
    calls = _parse_calls(monkeypatch)
    first = scan_root(db, root_id, lib)
    assert first["videos"] == 2
    assert first["unchanged"] == 0
    assert sorted(calls) == ["keep.mp4", "other.mp4"]

    by_name = _by_filename(db, root_id)
    keep_id, keep_row = by_name["keep.mp4"]
    other_id, _other_row = by_name["other.mp4"]
    db.upsert_media_meta(
        str(keep_row["path"]),
        stars=4,
        favorite=True,
        tags=["coast"],
        notes="keep me",
    )
    project = db.create_studio_project("Trip")
    clip_id, _created = db.add_studio_item(
        str(keep_row["path"]),
        identity_key=make_identity_key(
            str(keep_row["filename"]),
            int(keep_row["size_bytes"]),
            keep_row["recorded_at"],
        ),
        filename=str(keep_row["filename"]),
        recorded_at=keep_row["recorded_at"],
        kind="video",
        project_id=project.id,
        source_media_id=keep_id,
    )

    calls.clear()
    started = time.perf_counter()
    second = scan_root(db, root_id, lib)
    elapsed = time.perf_counter() - started
    assert calls == []
    assert second["unchanged"] == 2
    assert second["videos"] == 2
    assert second["removed"] == 0
    assert second["unavailable"] == 0
    assert elapsed < 2.0

    again_keep = db.get_media(keep_id)
    again_other = db.get_media(other_id)
    assert again_keep is not None and again_other is not None
    assert again_keep.id == keep_id
    assert again_other.id == other_id
    assert again_keep.favorite is True
    assert again_keep.stars == 4
    assert again_keep.tags == ["coast"]
    assert again_keep.notes == "keep me"
    assert keep.read_bytes() == keep_bytes

    with db.connect() as conn:
        stored = conn.execute(
            "SELECT source_media_id FROM studio_clips WHERE id = ?",
            (clip_id,),
        ).fetchone()
    assert stored is not None
    assert int(stored["source_media_id"]) == keep_id
    studio = db.list_studio_items(project.id)
    assert studio[0].available is True
    assert studio[0].source_media_id == keep_id


def test_changed_and_new_files_are_parsed_deleted_files_leave_user_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = tmp_path / "lib"
    sized = lib / "sized.mp4"
    touched = lib / "touched.mp4"
    gone = lib / "gone.mp4"
    _video(sized)
    _video(touched)
    _video(gone)

    db = Database(tmp_path / "chg.sqlite3")
    root_id = db.add_root(lib, "archive")
    scan_root(db, root_id, lib)
    rows = _by_filename(db, root_id)
    gone_id, gone_row = rows["gone.mp4"]
    sized_id, _sized_row = rows["sized.mp4"]
    touched_id, _touched_row = rows["touched.mp4"]
    db.upsert_media_meta(
        str(gone_row["path"]),
        favorite=True,
        tags=["gone-tag"],
        notes="still here",
        stars=2,
    )
    project = db.create_studio_project("Story")
    gone_clip, _created = db.add_studio_item(
        str(gone_row["path"]),
        identity_key=make_identity_key(
            str(gone_row["filename"]),
            int(gone_row["size_bytes"]),
            gone_row["recorded_at"],
        ),
        filename=str(gone_row["filename"]),
        recorded_at=gone_row["recorded_at"],
        kind="video",
        project_id=project.id,
        source_media_id=gone_id,
    )

    sized_stat = sized.stat()
    sized.write_bytes(sized.read_bytes() + b"\x02")
    os.utime(sized, ns=(sized_stat.st_atime_ns, sized_stat.st_mtime_ns))
    touched_stat = touched.stat()
    os.utime(
        touched,
        ns=(touched_stat.st_atime_ns, touched_stat.st_mtime_ns + 2_000_000_000),
    )
    gone_path = str(gone_row["path"])
    gone.unlink()
    added = lib / "added.mp4"
    _video(added, _MP4 + b"\x03")
    kept_bytes = touched.read_bytes()

    calls = _parse_calls(monkeypatch)
    counts = scan_root(db, root_id, lib)

    assert "touched.mp4" in calls
    assert "sized.mp4" in calls
    assert "added.mp4" in calls
    assert "gone.mp4" not in calls
    assert counts["removed"] == 1
    assert counts["videos"] == 3
    assert counts["unchanged"] == 0
    assert db.get_media(gone_id) is None
    assert db.get_media(sized_id) is not None
    assert db.get_media(touched_id) is not None
    sized_again = db.get_media(sized_id)
    assert sized_again is not None
    assert sized_again.size_bytes == sized.stat().st_size
    names = set(_by_filename(db, root_id))
    assert names == {"sized.mp4", "touched.mp4", "added.mp4"}
    assert touched.read_bytes() == kept_bytes
    assert not gone.exists()

    with db.connect() as conn:
        meta = conn.execute(
            "SELECT favorite, tags_json, notes FROM media_meta WHERE media_path = ?",
            (gone_path,),
        ).fetchone()
        studio_row = conn.execute(
            "SELECT id, media_path FROM studio_clips WHERE id = ?",
            (gone_clip,),
        ).fetchone()
    assert meta is not None
    assert int(meta["favorite"]) == 1
    assert "gone-tag" in str(meta["tags_json"])
    assert meta["notes"] == "still here"
    assert studio_row is not None
    assert str(studio_row["media_path"]) == gone_path
    listed = db.list_studio_items(project.id)
    assert len(listed) == 1
    assert listed[0].available is False


def test_sidecar_flag_and_live_photo_do_not_reparse_unchanged_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = tmp_path / "lib"
    video = lib / "clip.mp4"
    mov = lib / "IMG_0007.MOV"
    _video(video)
    _video(mov)
    db = Database(tmp_path / "side.sqlite3")
    root_id = db.add_root(lib, "phone")
    scan_root(db, root_id, lib)
    assert set(_by_filename(db, root_id)) == {"clip.mp4", "IMG_0007.MOV"}

    (lib / "clip.SRT").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
        encoding="utf-8",
    )
    from PIL import Image

    still = lib / "IMG_0007.JPG"
    Image.new("RGB", (8, 8), (4, 5, 6)).save(still, format="JPEG")

    calls = _parse_calls(monkeypatch)
    counts = scan_root(db, root_id, lib)
    assert "clip.mp4" not in calls
    assert "IMG_0007.MOV" not in calls
    assert "clip.SRT" in calls
    assert "IMG_0007.JPG" in calls
    by_name = _by_filename(db, root_id)
    clip_id, _clip_row = by_name["clip.mp4"]
    clip = db.get_media(clip_id)
    assert clip is not None and clip.has_srt is True
    assert "IMG_0007.MOV" not in by_name
    _jpg_id, jpg_row = by_name["IMG_0007.JPG"]
    assert jpg_row["kind"] == "photo"
    assert counts["live_sidecars"] == 1
    assert counts["unchanged"] >= 1


def test_unavailable_root_keeps_index_and_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = tmp_path / "lib"
    video = lib / "stay.mp4"
    _video(video)
    payload = video.read_bytes()
    db = Database(tmp_path / "miss.sqlite3")
    root_id = db.add_root(lib, "nas")
    scan_root(db, root_id, lib)
    media_id = db.list_media()[0].id
    stored_path = db.get_media(media_id)
    assert stored_path is not None
    db.upsert_media_meta(stored_path.path, favorite=True, tags=["nas"], notes="n")

    moved = tmp_path / "disconnected"
    lib.rename(moved)
    calls = _parse_calls(monkeypatch)
    counts = scan_root(db, root_id, lib)
    assert counts["unavailable"] == 1
    assert calls == []
    kept = db.get_media(media_id)
    assert kept is not None
    assert kept.favorite is True
    assert kept.tags == ["nas"]
    assert (moved / "stay.mp4").read_bytes() == payload

    results = scan_all_roots(db)
    assert results[0]["error"] == "missing"
    assert db.get_media(media_id) is not None
    assert calls == []


def test_slow_extract_is_skipped_on_noop_rescan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Controlled stand-in for an archive benchmark.

    Each parse sleeps. The second scan must not pay that cost. A 1k/10k NAS
    timing run was discovery work (issue #94) and is not repeated here.
    """
    import orga_drone.scan as scan_mod

    lib = tmp_path / "lib"
    for index in range(6):
        _video(lib / f"clip_{index}.mp4", _MP4 + bytes([index]))
    db = Database(tmp_path / "bench.sqlite3")
    root_id = db.add_root(lib, "bench")
    real = scan_mod.parse_media_file
    calls: list[str] = []

    def slow(path: Path):
        calls.append(Path(path).name)
        time.sleep(0.03)
        return real(path)

    monkeypatch.setattr(scan_mod, "parse_media_file", slow)
    started = time.perf_counter()
    scan_root(db, root_id, lib)
    first_elapsed = time.perf_counter() - started
    assert len(calls) == 6

    calls.clear()

    def fail_if_called(path: Path):
        calls.append(Path(path).name)
        raise AssertionError(f"unchanged file was parsed: {path}")

    monkeypatch.setattr(scan_mod, "parse_media_file", fail_if_called)
    started = time.perf_counter()
    second = scan_root(db, root_id, lib)
    second_elapsed = time.perf_counter() - started
    assert calls == []
    assert second["unchanged"] == 6
    assert second_elapsed < first_elapsed
