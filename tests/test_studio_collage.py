"""Studio Collage layout model and persistence (ADR 0038 / #457)."""

from __future__ import annotations

import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.studio_collage import (
    MAX_LEAVES,
    CollageSpecError,
    add_band,
    assign_leaf_media,
    clamp_collage_duration,
    collage_spec_from_raw,
    dump_collage_spec,
    duration_for_video_assign,
    iter_leaves,
    leaf_count,
    media_source_window,
    merge_public_media_paths,
    normalize_spec,
    preset_names,
    preset_spec,
    public_collage_spec,
    remove_leaf,
    resolve_rects,
    set_split_ratio,
    source_window,
    split_leaf,
    split_leaf_times,
    swap_leaf_media,
)
from orga_drone.studio_estimate import effective_seconds, summarize_studio_items
from orga_drone.studio_history import history_flags, undo_story


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _video_assignment_request(db: Database, source: Path) -> tuple[str, dict]:
    project = db.ensure_default_studio_project()
    assert project is not None
    clip = db.add_studio_collage(project.id, preset="1+1", collage_duration_s=5.0)
    leaf_id = iter_leaves(collage_spec_from_raw(clip.collage_spec)["root"])[0]["id"]
    source.write_bytes(b"synthetic video; ffprobe is simulated")
    return f"/api/studio/{clip.id}/collage", {
        "op": "assign_media",
        "leaf_id": leaf_id,
        "media": {"source": "external", "path": str(source), "kind": "video"},
    }


def test_slow_collage_probe_allows_reads_and_preserves_a_concurrent_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    url, payload = _video_assignment_request(db, tmp_path / "slow.mp4")
    entered = threading.Event()
    release = threading.Event()
    calls: list[float] = []

    def slow_probe(cmd: list[str], *, timeout: float, **kwargs: object):
        calls.append(timeout)
        entered.set()
        if not release.wait(timeout=20):
            raise subprocess.TimeoutExpired(cmd, timeout)
        return subprocess.CompletedProcess(cmd, 0, b'{"format":{"duration":"12.4"}}')

    monkeypatch.setattr("orga_drone.ffmpeg_bin.find_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr("subprocess.run", slow_probe)
    # The context-managed client shares one ASGI portal/event loop across threads.
    with client, ThreadPoolExecutor(max_workers=4) as pool:
        assignment = pool.submit(client.patch, url, json=payload)
        try:
            assert entered.wait(timeout=5)
            health = pool.submit(client.get, "/health")
            leaf = pool.submit(client.get, f"{url}/leaves/{payload['leaf_id']}/stream")
            assert health.result(timeout=5).json()["status"] == "ok"
            read = leaf.result(timeout=5)
            assert read.status_code == 404
            assert read.json()["detail"] == "Collage cell has no media"
            edit = pool.submit(client.patch, url, json={"gap_px": 12, "duration_s": 20.0})
            assert edit.result(timeout=5).status_code == 200
            assert not assignment.done()
        finally:
            release.set()
        response = assignment.result(timeout=5)

    assert calls == [8]
    assert response.status_code == 200
    assert response.json()["collage_spec"]["gap_px"] == 12
    assert response.json()["duration_s"] == 20.0
    media = iter_leaves(response.json()["collage_spec"]["root"])[0]["media"]
    assert media["has_path"] and media["kind"] == "video"


@pytest.mark.parametrize(
    ("outcome", "duration", "expected_calls"),
    [
        ("success", 12.4, [8]),
        ("timeout", 5.0, [8]),
        ("failure", 5.0, [8]),
        ("unavailable", 5.0, []),
    ],
)
def test_video_assignment_preserves_probe_results_and_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    duration: float,
    expected_calls: list[int],
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    url, payload = _video_assignment_request(db, tmp_path / "clip.mp4")
    calls: list[float] = []

    def probe(cmd: list[str], *, timeout: float, **kwargs: object):
        calls.append(timeout)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd, timeout)
        if outcome == "failure":
            return subprocess.CompletedProcess(cmd, 1, b"")
        return subprocess.CompletedProcess(cmd, 0, b'{"format":{"duration":"12.4"}}')

    monkeypatch.setattr(
        "orga_drone.ffmpeg_bin.find_ffprobe",
        lambda: None if outcome == "unavailable" else "ffprobe",
    )
    monkeypatch.setattr("subprocess.run", probe)
    response = client.patch(url, json=payload)

    assert calls == expected_calls
    assert response.status_code == 200
    assert response.json()["duration_s"] == duration
    media = iter_leaves(response.json()["collage_spec"]["root"])[0]["media"]
    assert media["has_path"] and "path" not in media and media["kind"] == "video"


def test_all_presets_normalize_and_resolve() -> None:
    for name in preset_names():
        spec = preset_spec(name)
        assert leaf_count(spec) >= 2
        rects = resolve_rects(spec, 1920, 1080)
        assert len(rects) == leaf_count(spec)
        area = sum(r.w * r.h for r in rects.values())
        assert area > 0
        for rect in rects.values():
            assert rect.w >= 1 and rect.h >= 1
            assert rect.x >= 0 and rect.y >= 0
            assert rect.x + rect.w <= 1920
            assert rect.y + rect.h <= 1080


def test_add_band_and_split_times() -> None:
    spec = preset_spec("1+1")
    assert leaf_count(spec) == 2
    with_row = add_band(spec, edge="bottom", cells=2)
    assert leaf_count(with_row) == 4
    leaves = iter_leaves(with_row["root"])
    first = leaves[0]["id"]
    into_three = split_leaf_times(with_row, first, direction="h", times=2)
    assert leaf_count(into_three) == 6
    too_many = add_band(preset_spec("3x2"), edge="right", cells=20)
    assert leaf_count(too_many) <= 16


def test_custom_split_ratio_remove_and_swap() -> None:
    spec = preset_spec("1+1")
    leaves = iter_leaves(spec["root"])
    leaf_a = leaves[0]["id"]
    leaf_b = leaves[1]["id"]
    split_id = spec["root"]["id"]
    moved = set_split_ratio(spec, split_id, 0.25)
    assert moved["root"]["ratio"] == 0.25
    rects = resolve_rects(moved, 1000, 500)
    assert abs(rects[leaf_a].w - 248) <= 2  # (1000-8)*0.25

    with_media = assign_leaf_media(
        moved,
        leaf_a,
        {
            "source": "library",
            "media_id": 7,
            "kind": "photo",
            "fit": "fit",
            "zoom": 1.2,
            "pan_x": 0.2,
            "pan_y": 0.8,
        },
    )
    swapped = swap_leaf_media(with_media, leaf_a, leaf_b)
    leaves2 = {leaf["id"]: leaf for leaf in iter_leaves(swapped["root"])}
    assert "media" not in leaves2[leaf_a]
    assert leaves2[leaf_b]["media"]["media_id"] == 7

    split_more = split_leaf(swapped, leaf_b, direction="v", ratio=0.4)
    assert leaf_count(split_more) == 3
    trimmed = remove_leaf(split_more, iter_leaves(split_more["root"])[-1]["id"])
    assert leaf_count(trimmed) == 2


def test_library_media_id_accepts_digit_string() -> None:
    spec = preset_spec("1+1")
    leaf_id = iter_leaves(spec["root"])[0]["id"]
    assigned = assign_leaf_media(
        spec,
        leaf_id,
        {
            "source": "library",
            "media_id": "42",
            "kind": "photo",
            "fit": "fill",
            "zoom": 1.0,
            "pan_x": 0.5,
            "pan_y": 0.5,
        },
    )
    media = iter_leaves(assigned["root"])[0]["media"]
    assert media["media_id"] == 42
    with pytest.raises(CollageSpecError):
        assign_leaf_media(
            spec,
            leaf_id,
            {
                "source": "library",
                "media_id": "nope",
                "kind": "photo",
            },
        )


def test_resource_limit_and_fit_window() -> None:
    # Balanced growth avoids depth limit before leaf cap.
    current = preset_spec("2x2")
    while leaf_count(current) < MAX_LEAVES:
        # Split the leaf with the shallowest path by rotating through leaves.
        target = None
        for leaf in iter_leaves(current["root"]):
            target = leaf["id"]
            try:
                current = split_leaf(current, target, direction="h")
                break
            except ValueError:
                continue
        else:
            break
    assert leaf_count(current) == MAX_LEAVES
    with pytest.raises(ValueError):
        split_leaf(current, iter_leaves(current["root"])[0]["id"], direction="h")

    win_fit = source_window(
        source_w=4000, source_h=3000, cell_w=100, cell_h=100, fit="fit", zoom=1.0
    )
    assert win_fit.w == pytest.approx(1.0)
    assert win_fit.h == pytest.approx(1.0)
    win_fill = source_window(
        source_w=4000, source_h=3000, cell_w=100, cell_h=100, fit="fill", zoom=1.0
    )
    assert win_fill.w < 1.0 or win_fill.h < 1.0


def test_public_spec_strips_external_path(tmp_path: Path) -> None:
    existing = tmp_path / "drone.mp4"
    existing.write_bytes(b"x")
    spec = preset_spec("1+1")
    leaf_id = iter_leaves(spec["root"])[0]["id"]
    with_ext = assign_leaf_media(
        spec,
        leaf_id,
        {
            "source": "external",
            "path": str(existing),
            "kind": "video",
            "display_name": "drone.mp4",
        },
    )
    public = public_collage_spec(with_ext)
    media = iter_leaves(public["root"])[0]["media"]
    assert "path" not in media
    assert media["has_path"] is True
    assert media["display_name"] == "drone.mp4"
    assert media["source_key"].startswith("src-")
    missing = assign_leaf_media(
        spec,
        leaf_id,
        {
            "source": "external",
            "path": str(tmp_path / "gone.mp4"),
            "kind": "video",
            "display_name": "gone.mp4",
        },
    )
    missing_public = public_collage_spec(missing)
    assert iter_leaves(missing_public["root"])[0]["media"]["has_path"] is False


def test_persist_reopen_migration_and_estimate(tmp_path: Path) -> None:
    db = Database(tmp_path / "c.sqlite3")
    project = db.ensure_default_studio_project()
    assert project is not None
    clip = db.add_studio_collage(project.id, preset="2x2", collage_duration_s=7.5)
    assert clip.item_kind == "collage"
    assert clip.kind == "collage"
    assert clip.collage_duration_s == 7.5
    assert clip.media_path is None
    assert leaf_count(collage_spec_from_raw(clip.collage_spec)) == 4

    reopened = Database(tmp_path / "c.sqlite3")
    items = reopened.list_studio_items(project.id)
    assert len(items) == 1
    assert items[0].kind == "collage"
    assert items[0].collage_duration_s == 7.5
    seconds = effective_seconds(
        kind="collage",
        photo_duration_s=None,
        duration_s=items[0].duration_s,
        available=True,
        card_duration_s=items[0].collage_duration_s,
    )
    assert seconds == 7.5
    summary = summarize_studio_items(items)
    assert summary.estimated_total_s == pytest.approx(7.5)

    updated = reopened.update_studio_collage(
        items[0].id, collage_duration_s=3.0, collage_spec=preset_spec("1+1")
    )
    assert updated.collage_duration_s == 3.0
    assert leaf_count(collage_spec_from_raw(updated.collage_spec)) == 2


def test_missing_library_media_keeps_collage(tmp_path: Path) -> None:
    db = Database(tmp_path / "m.sqlite3")
    project = db.ensure_default_studio_project()
    assert project is not None
    clip = db.add_studio_collage(project.id, preset="1+1")
    leaf_id = iter_leaves(collage_spec_from_raw(clip.collage_spec)["root"])[0]["id"]
    spec = assign_leaf_media(
        collage_spec_from_raw(clip.collage_spec),
        leaf_id,
        {"source": "library", "media_id": 999999, "kind": "photo"},
    )
    updated = db.update_studio_collage(clip.id, collage_spec=spec)
    assert updated.available is True
    assert updated.item_kind == "collage"
    assert "999999" in (updated.collage_spec or "")


def test_http_add_patch_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.ensure_default_studio_project()
    assert project is not None
    db.set_app_state("studio_last_project_id", str(project.id))

    created = client.post("/api/studio/collages", json={"preset": "3|2"})
    assert created.status_code == 200
    body = created.json()
    assert body["ok"] is True
    clip_id = int(body["id"])
    assert body["collage_spec"]["leaf_count"] == 5

    patched = client.patch(
        f"/api/studio/{clip_id}/collage",
        json={"duration_s": 9.0},
        headers={"X-Studio-History-Group": "collage-dur"},
    )
    assert patched.status_code == 200
    assert patched.json()["duration_s"] == 9.0

    flags = history_flags(project.id)
    assert flags["can_undo"] is True
    undo_story(db, project.id)
    items = db.list_studio_items(project.id)
    assert len(items) == 1
    assert items[0].item_kind == "collage"
    assert items[0].collage_duration_s == 5.0


def test_clamp_and_dump_roundtrip() -> None:
    assert clamp_collage_duration(0.2) == 1.0
    assert clamp_collage_duration(200) == 120.0
    raw = dump_collage_spec(preset_spec("1+2+1"))
    again = collage_spec_from_raw(raw)
    assert normalize_spec(again)["duration_s"] == again["duration_s"]
    assert leaf_count(again) == 4


def test_remove_to_one_then_split_root_leaf() -> None:
    spec = preset_spec("1+1")
    leaves = iter_leaves(spec["root"])
    one = remove_leaf(spec, leaves[1]["id"])
    assert leaf_count(one) == 1
    assert one["root"]["type"] == "leaf"
    again = split_leaf(one, one["root"]["id"], direction="v")
    assert leaf_count(again) == 2


def test_public_patch_preserves_external_path(tmp_path: Path) -> None:
    from orga_drone.studio_collage import merge_public_media_paths, public_collage_spec

    db = Database(tmp_path / "ext.sqlite3")
    project = db.ensure_default_studio_project()
    assert project is not None
    clip = db.add_studio_collage(project.id, preset="1+1")
    leaf_id = iter_leaves(collage_spec_from_raw(clip.collage_spec)["root"])[0]["id"]
    with_path = assign_leaf_media(
        collage_spec_from_raw(clip.collage_spec),
        leaf_id,
        {
            "source": "external",
            "path": str(tmp_path / "clip.mp4"),
            "kind": "video",
            "display_name": "clip.mp4",
        },
    )
    saved = db.update_studio_collage(clip.id, collage_spec=with_path)
    public = public_collage_spec(collage_spec_from_raw(saved.collage_spec))
    public["gap_px"] = 12
    merged = merge_public_media_paths(public, collage_spec_from_raw(saved.collage_spec))
    media = iter_leaves(merged["root"])[0]["media"]
    assert media["path"] == str(tmp_path / "clip.mp4")
    updated = db.update_studio_collage(clip.id, collage_spec=public)
    media2 = iter_leaves(collage_spec_from_raw(updated.collage_spec)["root"])[0]["media"]
    assert media2["path"] == str(tmp_path / "clip.mp4")
    assert updated.collage_spec and '"gap_px":12' in updated.collage_spec


def test_http_assign_clear_and_frame_leaf_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.ensure_default_studio_project()
    assert project is not None
    db.set_app_state("studio_last_project_id", str(project.id))
    created = client.post("/api/studio/collages", json={"preset": "1+1"})
    clip_id = int(created.json()["id"])
    leaf_ids = [
        leaf["id"] for leaf in iter_leaves(created.json()["collage_spec"]["root"])
    ]
    leaf_a, leaf_b = leaf_ids[0], leaf_ids[1]
    assigned = client.patch(
        f"/api/studio/{clip_id}/collage",
        json={
            "op": "assign_media",
            "leaf_id": leaf_a,
            "media": {
                "source": "library",
                "media_id": 42,
                "kind": "photo",
                "fit": "fill",
                "zoom": 1.0,
                "pan_x": 0.5,
                "pan_y": 0.5,
            },
        },
    )
    assert assigned.status_code == 200
    framed = client.patch(
        f"/api/studio/{clip_id}/collage",
        json={
            "op": "assign_media",
            "leaf_id": leaf_a,
            "media": {
                "source": "library",
                "media_id": 42,
                "kind": "photo",
                "fit": "fit",
                "zoom": 1.5,
                "pan_x": 0.2,
                "pan_y": 0.8,
            },
        },
    )
    assert framed.status_code == 200
    media = next(
        leaf["media"]
        for leaf in iter_leaves(framed.json()["collage_spec"]["root"])
        if leaf["id"] == leaf_a
    )
    assert media["fit"] == "fit"
    assert media["zoom"] == 1.5
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(b"x")
    ext = client.patch(
        f"/api/studio/{clip_id}/collage",
        json={
            "op": "assign_media",
            "leaf_id": leaf_b,
            "media": {
                "source": "external",
                "path": str(clip_path),
                "kind": "video",
                "display_name": "clip.mp4",
            },
        },
    )
    assert ext.status_code == 200
    public_b = next(
        leaf["media"]
        for leaf in iter_leaves(ext.json()["collage_spec"]["root"])
        if leaf["id"] == leaf_b
    )
    assert "path" not in public_b
    assert public_b["has_path"] is True
    cleared = client.patch(
        f"/api/studio/{clip_id}/collage",
        json={"op": "assign_media", "leaf_id": leaf_a, "media": None},
    )
    assert cleared.status_code == 200
    leaves = {
        leaf["id"]: leaf
        for leaf in iter_leaves(cleared.json()["collage_spec"]["root"])
    }
    assert "media" not in leaves[leaf_a]
    assert "media" in leaves[leaf_b]


def test_http_preset_preserves_aspect_gap_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.ensure_default_studio_project()
    assert project is not None
    db.set_app_state("studio_last_project_id", str(project.id))
    created = client.post("/api/studio/collages", json={"preset": "1+1"})
    clip_id = int(created.json()["id"])
    client.patch(
        f"/api/studio/{clip_id}/collage",
        json={"aspect": "9:16", "gap_px": 24, "background": "#112233"},
    )
    preset = client.patch(
        f"/api/studio/{clip_id}/collage",
        json={"preset": "2x2"},
    )
    assert preset.status_code == 200
    spec = preset.json()["collage_spec"]
    assert spec["leaf_count"] == 4
    assert spec["aspect"] == "9:16"
    assert spec["gap_px"] == 24
    assert spec["background"] == "#112233"


def test_http_preset_preserves_leaf_media_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.ensure_default_studio_project()
    assert project is not None
    db.set_app_state("studio_last_project_id", str(project.id))
    root = tmp_path / "media"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    media_ids: list[int] = []
    for name in ("a.jpg", "b.jpg"):
        path = root / name
        path.write_bytes(b"fake")
        media_ids.append(
            db.upsert_media(
                {
                    "root_id": root_id,
                    "primary_asset_id": None,
                    "kind": "photo",
                    "filename": name,
                    "path": str(path.resolve()),
                    "size_bytes": 4,
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
        )
    created = client.post("/api/studio/collages", json={"preset": "1+1"})
    clip_id = int(created.json()["id"])
    leaf_ids = [
        str(leaf["id"])
        for leaf in iter_leaves(created.json()["collage_spec"]["root"])
    ]
    for leaf_id, mid in zip(leaf_ids, media_ids, strict=True):
        assigned = client.patch(
            f"/api/studio/{clip_id}/collage",
            json={
                "op": "assign_media",
                "leaf_id": leaf_id,
                "media": {
                    "source": "library",
                    "media_id": mid,
                    "kind": "photo",
                    "fit": "fill",
                    "zoom": 1.2,
                    "pan_x": 0.4,
                    "pan_y": 0.6,
                },
            },
        )
        assert assigned.status_code == 200
    preset = client.patch(f"/api/studio/{clip_id}/collage", json={"preset": "2x2"})
    assert preset.status_code == 200
    leaves = iter_leaves(preset.json()["collage_spec"]["root"])
    assert len(leaves) == 4
    assert leaves[0]["media"]["media_id"] == media_ids[0]
    assert leaves[0]["media"]["zoom"] == 1.2
    assert leaves[1]["media"]["media_id"] == media_ids[1]
    assert "media" not in leaves[2]
    assert "media" not in leaves[3]


def test_public_external_swap_preserves_source_identity(tmp_path: Path) -> None:
    path_one = str(tmp_path / "one.mp4")
    path_two = str(tmp_path / "two.mp4")
    spec = preset_spec("1+1")
    leaves = iter_leaves(spec["root"])
    leaf_a = leaves[0]["id"]
    leaf_b = leaves[1]["id"]
    with_one = assign_leaf_media(
        spec,
        leaf_a,
        {
            "source": "external",
            "path": path_one,
            "kind": "video",
            "display_name": "one.mp4",
            "zoom": 1.1,
        },
    )
    with_both = assign_leaf_media(
        with_one,
        leaf_b,
        {
            "source": "external",
            "path": path_two,
            "kind": "video",
            "display_name": "two.mp4",
            "zoom": 1.5,
        },
    )
    public = public_collage_spec(with_both)
    pub_leaves = {leaf["id"]: leaf for leaf in iter_leaves(public["root"])}
    # Swap media objects (as a client would after drag-swap), keeping source_key.
    media_a = dict(pub_leaves[leaf_a]["media"])
    media_b = dict(pub_leaves[leaf_b]["media"])
    pub_leaves[leaf_a]["media"] = media_b
    pub_leaves[leaf_b]["media"] = media_a
    merged = merge_public_media_paths(public, with_both)
    by_id = {leaf["id"]: leaf["media"] for leaf in iter_leaves(merged["root"])}
    assert by_id[leaf_a]["path"] == path_two
    assert by_id[leaf_a]["display_name"] == "two.mp4"
    assert by_id[leaf_a]["zoom"] == 1.5
    assert by_id[leaf_b]["path"] == path_one
    assert by_id[leaf_b]["display_name"] == "one.mp4"
    assert by_id[leaf_b]["zoom"] == 1.1


def test_resolve_rects_rejects_undersized_nested_splits() -> None:
    spec = preset_spec("1+1")
    split_id = spec["root"]["id"]
    tight = set_split_ratio(spec, split_id, 0.05)
    first_leaf = iter_leaves(tight["root"])[0]["id"]
    nested = split_leaf(tight, first_leaf, direction="h", ratio=0.05)
    deep_leaf = iter_leaves(nested["root"])[0]["id"]
    deeper = split_leaf(nested, deep_leaf, direction="h", ratio=0.05)
    assert leaf_count(deeper) == 4
    with pytest.raises(CollageSpecError, match="does not fit|cannot place"):
        resolve_rects(deeper, 1920, 1080)


def test_interrupted_collage_migration_is_restartable(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "mig.sqlite3"
    # Build a pre-collage DB via an older-shaped table, then reopen.
    first = Database(db_path)
    project = first.ensure_default_studio_project()
    assert project is not None
    first.add_studio_title_card(project.id, title_text="Hello")
    with sqlite3.connect(db_path) as conn:
        # Simulate leftover staging from a crashed migration.
        conn.execute("DROP TABLE IF EXISTS studio_clips__collage_mig")
        conn.execute(
            "CREATE TABLE studio_clips__collage_mig (id INTEGER PRIMARY KEY)"
        )
        conn.commit()
    reopened = Database(db_path)
    items = reopened.list_studio_items(project.id)
    assert len(items) == 1
    assert items[0].kind == "title_card"
def test_http_collage_leaf_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image

    client, db = _client(tmp_path, monkeypatch)
    project = db.ensure_default_studio_project()
    assert project is not None
    root = tmp_path / "lib"
    root.mkdir()
    photo = root / "leaf.png"
    Image.new("RGB", (32, 24), (10, 20, 30)).save(photo)
    root_id = db.add_root(root, label="lib")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": "leaf.png",
            "path": str(photo.resolve()),
            "size_bytes": photo.stat().st_size,
            "duration_s": None,
            "recorded_at": "2024-06-01T12:00:00",
            "sequence": None,
            "mode": None,
            "drone_model": None,
            "camera_model": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
        }
    )
    clip = db.add_studio_collage(project.id, preset="1+1")
    leaf_id = iter_leaves(collage_spec_from_raw(clip.collage_spec)["root"])[0]["id"]
    external = tmp_path / "ext.jpg"
    Image.new("RGB", (16, 16), (1, 2, 3)).save(external)
    with_media = assign_leaf_media(
        collage_spec_from_raw(clip.collage_spec),
        leaf_id,
        {
            "source": "external",
            "path": str(external.resolve()),
            "kind": "photo",
            "display_name": "ext.jpg",
        },
    )
    db.update_studio_collage(clip.id, collage_spec=with_media)
    ok = client.get(f"/api/studio/{clip.id}/collage/leaves/{leaf_id}/stream")
    assert ok.status_code == 200
    assert ok.content[:8]  # bytes present
    assert "ext.jpg" not in (ok.headers.get("content-disposition") or "")
    missing = client.get(f"/api/studio/{clip.id}/collage/leaves/no-such/stream")
    assert missing.status_code == 404
    # Library path also works after reassignment
    lib_spec = assign_leaf_media(
        collage_spec_from_raw(db.list_studio_items(project.id)[0].collage_spec),
        leaf_id,
        {"source": "library", "media_id": media_id, "kind": "photo"},
    )
    db.update_studio_collage(clip.id, collage_spec=lib_spec)
    lib = client.get(f"/api/studio/{clip.id}/collage/leaves/{leaf_id}/stream")
    assert lib.status_code == 200


def test_http_collage_leaf_preview_frame_shows_grade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Framing dialog loads a graded full-source JPEG for the selected leaf."""
    from PIL import Image

    client, db = _client(tmp_path, monkeypatch)
    project = db.ensure_default_studio_project()
    assert project is not None
    photo = tmp_path / "grade-leaf.jpg"
    Image.new("RGB", (48, 32), (40, 80, 120)).save(photo)
    clip = db.add_studio_collage(project.id, preset="1+1")
    leaf_id = iter_leaves(collage_spec_from_raw(clip.collage_spec)["root"])[0]["id"]
    graded = assign_leaf_media(
        collage_spec_from_raw(clip.collage_spec),
        leaf_id,
        {
            "source": "external",
            "path": str(photo.resolve()),
            "kind": "photo",
            "display_name": "grade-leaf.jpg",
            "grade": {
                "image": {
                    "exposure": 20,
                    "contrast": 0,
                    "saturation": 0,
                    "warmth": 0,
                    "highlights": 0,
                    "shadows": 0,
                    "blacks": 0,
                }
            },
        },
    )
    db.update_studio_collage(clip.id, collage_spec=graded)
    res = client.get(f"/api/studio/{clip.id}/collage/leaves/{leaf_id}/preview-frame?t_s=0")
    assert res.status_code == 200
    assert res.headers.get("content-type", "").startswith("image/jpeg")
    assert res.content[:2] == b"\xff\xd8"
    missing = client.get(f"/api/studio/{clip.id}/collage/leaves/no-such/preview-frame")
    assert missing.status_code in {404, 409}


def test_collage_library_dialog_keeps_confirm_actions() -> None:
    """Library picker must use the shared picker grid + visible confirm actions."""
    page = Path("src/orga_drone/templates/studio.html").read_text(encoding="utf-8")
    assert 'id="studio-collage-library-dialog"' in page
    assert 'id="studio-collage-library-add"' in page
    assert "photo-combine-picker-grid" in page
    assert "studio-collage-library-actions" in page
    assert "method=\"dialog\"" not in page.split('id="studio-collage-library-dialog"', 1)[1].split(
        "</dialog>", 1
    )[0]
    editor = Path("src/orga_drone/static/js/studio/collage-editor.js").read_text(
        encoding="utf-8"
    )
    assert "All files (*.*)" in editor
    assert "dblclick" in editor
    assert "commitLibrarySelection" in editor


def test_collage_framing_prefs_and_settings_surface() -> None:
    prefs_js = Path(
        "src/orga_drone/static/js/studio/collage-framing-prefs.js"
    ).read_text(encoding="utf-8")
    assert "orga-drone:collage-framing" in prefs_js
    assert "modifierMatches" in prefs_js
    editor = Path("src/orga_drone/static/js/studio/collage-editor.js").read_text(
        encoding="utf-8"
    )
    assert "framingDrag" in editor
    frame_modal = Path(
        "src/orga_drone/static/js/studio/collage-frame-modal.js"
    ).read_text(encoding="utf-8")
    assert "wheel" in frame_modal
    assert "collage-framing-prefs" in editor or "modifierMatches" in prefs_js
    settings = Path("src/orga_drone/templates/settings.html").read_text(encoding="utf-8")
    assert 'id="settings-collage-framing"' in settings
    assert "settings-collage-framing.js" in settings
    studio = Path("src/orga_drone/templates/studio.html").read_text(encoding="utf-8")
    assert "Adjust framing" in studio
    assert "orange frame" in studio.lower() or "handles to set width" in studio


def test_collage_layout_presets_use_visual_cards() -> None:
    page = Path("src/orga_drone/templates/studio.html").read_text(encoding="utf-8")
    assert 'id="inspector-collage-presets"' in page
    assert 'data-collage-preset="2+1"' in page
    assert "More on the left" in page
    assert "More on the right" in page
    assert "Two cells side by side" in page
    assert "Split into 2 side by side" in page
    editor = Path("src/orga_drone/static/js/studio/collage-editor.js").read_text(
        encoding="utf-8"
    )
    assert "applyPresetChoice" in editor
    assert "syncPresetButtons" in editor
    css = Path("src/orga_drone/static/css/app.css").read_text(encoding="utf-8")
    assert ".studio-collage-presets" in css


def test_collage_quick_looks_are_not_blocked_in_ui() -> None:
    """Leaf Quick Looks must reach /look with leaf_id (not an early UI return)."""
    studio_js = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert "Quick Looks are not available for collage cells yet" not in studio_js
    assert "lookPayload.leaf_id = leafId" in studio_js
    # Switching cells must restore that leaf's look id into the inspector.
    assert "clip.dataset.quickLook = lookId" in studio_js
    assert "grade.look" in studio_js
    editor = Path("src/orga_drone/static/js/studio/collage-editor.js").read_text(
        encoding="utf-8"
    )
    # Graded composed preview must refresh while paused after a leaf look.
    assert "if (!opts.isPlaying?.()) return;" not in editor.split(
        "function scheduleComposedPreview", 1
    )[1].split("function renderPreview", 1)[0]


def test_duration_for_video_assign_extends_short_collage() -> None:
    assert duration_for_video_assign(5.0, 12.4) == 12.4
    assert duration_for_video_assign(5.0, 5.0) is None
    assert duration_for_video_assign(20.0, 12.0) is None
    assert duration_for_video_assign(None, 8.0) == 8.0
    assert duration_for_video_assign(5.0, None) is None
    assert duration_for_video_assign(5.0, 0) is None
    # Clamped to collage max.
    assert duration_for_video_assign(5.0, 999.0) == clamp_collage_duration(999.0)


def test_assign_media_preserves_grade_when_omitted() -> None:
    spec = preset_spec("1+1")
    leaf_id = iter_leaves(spec["root"])[0]["id"]
    graded = assign_leaf_media(
        spec,
        leaf_id,
        {
            "source": "library",
            "media_id": 3,
            "kind": "photo",
            "fit": "fill",
            "zoom": 1.0,
            "pan_x": 0.5,
            "pan_y": 0.5,
            "grade": {"look": {"id": "vibrant"}, "image": {"saturation": 38}},
        },
    )
    framed = assign_leaf_media(
        graded,
        leaf_id,
        {
            "source": "library",
            "media_id": 3,
            "kind": "photo",
            "fit": "fill",
            "zoom": 1.4,
            "pan_x": 0.2,
            "pan_y": 0.7,
            "crop": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
        },
    )
    media = iter_leaves(framed["root"])[0]["media"]
    assert media["zoom"] == 1.4
    assert media["crop"]["w"] == 0.5
    assert media["grade"]["look"]["id"] == "vibrant"
    # Replacing with a different media id drops the old grade.
    replaced = assign_leaf_media(
        framed,
        leaf_id,
        {
            "source": "library",
            "media_id": 9,
            "kind": "photo",
            "fit": "fill",
            "zoom": 1.0,
            "pan_x": 0.5,
            "pan_y": 0.5,
        },
    )
    assert "grade" not in iter_leaves(replaced["root"])[0]["media"]


def test_free_crop_overrides_fit_zoom_window() -> None:
    media = {
        "source": "library",
        "media_id": 1,
        "kind": "photo",
        "fit": "fill",
        "zoom": 2.0,
        "pan_x": 0.2,
        "pan_y": 0.8,
        "crop": {"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.5},
    }
    spec = preset_spec("1+1")
    leaf_id = iter_leaves(spec["root"])[0]["id"]
    assigned = assign_leaf_media(spec, leaf_id, media)
    leaf = iter_leaves(assigned["root"])[0]
    assert leaf["media"]["crop"] == {"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.5}
    win = media_source_window(
        leaf["media"],
        source_w=1000,
        source_h=800,
        cell_w=400,
        cell_h=300,
    )
    assert win.x == pytest.approx(0.1)
    assert win.y == pytest.approx(0.2)
    assert win.w == pytest.approx(0.4)
    assert win.h == pytest.approx(0.5)
