"""Studio Collage layout model and persistence (ADR 0038 / #457)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.studio_collage import (
    MAX_LEAVES,
    CollageSpecError,
    assign_leaf_media,
    clamp_collage_duration,
    collage_spec_from_raw,
    dump_collage_spec,
    iter_leaves,
    leaf_count,
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


def test_public_spec_strips_external_path() -> None:
    spec = preset_spec("1+1")
    leaf_id = iter_leaves(spec["root"])[0]["id"]
    with_ext = assign_leaf_media(
        spec,
        leaf_id,
        {
            "source": "external",
            "path": "C:/secret/drone.mp4",
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
