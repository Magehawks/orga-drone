"""Browse pagination, page-size limits, and filter/sort regression."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.app import (
    BROWSE_PAGE_SIZE,
    browse_filter_query,
    browse_page_clamp,
    browse_pagination,
)
from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.i18n import clear_catalog_cache


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    clear_catalog_cache()
    from orga_drone.app import create_app

    return create_app()


def _seed_many(db: Database, root: Path, count: int) -> list[int]:
    root.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root, label="t")
    ids: list[int] = []
    for i in range(count):
        name = f"clip_{i:04d}.MP4"
        f = root / name
        f.write_bytes(b"x")
        mid = db.upsert_media(
            {
                "root_id": root_id,
                "primary_asset_id": None,
                "kind": "video",
                "filename": name,
                "path": str(f.resolve()),
                "size_bytes": 1000 + i,
                "duration_s": 1.0 + i,
                "recorded_at": f"2024-06-{(i % 28) + 1:02d}T12:00:00",
                "sequence": None,
                "mode": None,
                "drone_model": "Mini 4 Pro" if i % 2 == 0 else "Avata 2",
                "camera_model": None,
                "latitude": None,
                "longitude": None,
                "abs_alt": None,
                "has_srt": 0,
                "has_lrf": 0,
                "track_json": None,
            }
        )
        ids.append(mid)
    return ids


def test_browse_pagination_helpers() -> None:
    assert browse_page_clamp(0, total=100) == 1
    assert browse_page_clamp(99, total=100, page_size=48) == 3
    meta = browse_pagination(total=100, page=2, page_size=48)
    assert meta["page"] == 2
    assert meta["offset"] == 48
    assert meta["has_prev"] is True
    assert meta["has_next"] is True
    assert meta["showing_from"] == 49
    assert meta["showing_to"] == 96
    qs = browse_filter_query({"view": "grid", "kind": "video", "q": ""}, page=2)
    assert "view=grid" in qs
    assert "kind=video" in qs
    assert "page=2" in qs
    assert "q=" not in qs


def test_list_media_limit_offset_and_count(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    _seed_many(db, tmp_path / "lib", 10)
    assert db.count_media() == 10
    page1 = db.list_media(sort="filename", order="asc", limit=4, offset=0)
    page2 = db.list_media(sort="filename", order="asc", limit=4, offset=4)
    assert len(page1) == 4
    assert len(page2) == 4
    assert page1[0].filename == "clip_0000.MP4"
    assert page2[0].filename == "clip_0004.MP4"
    filtered = db.count_media(drone="Avata 2")
    assert filtered == 5
    limited = db.list_media(drone="Avata 2", limit=2, offset=0)
    assert len(limited) == 2
    assert all(i.drone_model == "Avata 2" for i in limited)


def test_browse_pages_limit_dom_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    total = BROWSE_PAGE_SIZE + 7
    _seed_many(db, tmp_path / "lib", total)

    client = TestClient(app)
    page1 = client.get("/browse")
    assert page1.status_code == 200
    assert page1.text.count('class="card"') == BROWSE_PAGE_SIZE
    assert "browse-pager" in page1.text
    assert f"/{(total + BROWSE_PAGE_SIZE - 1) // BROWSE_PAGE_SIZE}" in page1.text or (
        str((total + BROWSE_PAGE_SIZE - 1) // BROWSE_PAGE_SIZE) in page1.text
    )
    assert "page=2" in page1.text

    page2 = client.get("/browse?page=2")
    assert page2.status_code == 200
    assert page2.text.count('class="card"') == 7
    assert "page=1" in page2.text or "Previous" in page2.text or "Zurück" in page2.text

    filtered = client.get("/browse?kind=video&drone=Mini+4+Pro&page=1")
    assert filtered.status_code == 200
    # Even indices only → ceil(55/2) or floor depending on range(55)
    assert filtered.text.count('class="card"') == 28
    assert "Mini 4 Pro" in filtered.text
    assert "browse-pager" not in filtered.text

def test_browse_filter_and_sort_with_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    _seed_many(db, tmp_path / "lib", 20)

    client = TestClient(app)
    resp = client.get(
        "/browse",
        params={"sort": "filename", "order": "asc", "drone": "Avata 2", "kind": "video"},
    )
    assert resp.status_code == 200
    # Only Avata rows (every odd index) — 10 items, one page
    assert resp.text.count('class="card"') == 10
    assert "clip_0001.MP4" in resp.text
    assert "clip_0000.MP4" not in resp.text
    assert "browse-pager" not in resp.text

    listed = client.get(
        "/browse",
        params={"view": "list", "sort": "size", "order": "desc", "q": "clip_001"},
    )
    assert listed.status_code == 200
    assert "list-thumb" in listed.text
    assert "clip_0010.MP4" in listed.text or "clip_0011.MP4" in listed.text


def test_thumbs_js_unloads_offscreen_src(tmp_path: Path) -> None:
    """Static check: thumbs.js keeps observing and resets src off-viewport."""
    src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "orga_drone"
        / "static"
        / "js"
        / "thumbs.js"
    ).read_text(encoding="utf-8")
    assert "unload" in src
    assert "PLACEHOLDER" in src
    assert "io.unobserve" not in src
    assert "isIntersecting" in src
    assert "else unload" in src or "unload(entry.target)" in src
