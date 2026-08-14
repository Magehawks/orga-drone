"""Studio Title Cards: domain, persistence, HTTP, estimate, export (Issue #26)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database, make_identity_key
from orga_drone.studio_estimate import effective_seconds, summarize_studio_items
from orga_drone.studio_title_card import (
    TITLE_CARD_PRESETS,
    clamp_card_duration,
    display_lines,
    normalize_background,
    normalize_subtitle,
    normalize_title,
    render_title_card_image,
    wrap_to_lines,
)


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Database]:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    return TestClient(app), app.state.db


def _seed_video(db: Database, root_path: Path) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    root_id = db.add_root(root_path, label="test")
    media_file = root_path / "DJI_0001.MP4"
    media_file.write_bytes(b"fake-video")
    path = str(media_file.resolve())
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "video",
            "filename": "DJI_0001.MP4",
            "path": path,
            "size_bytes": 10,
            "duration_s": 12.0,
            "recorded_at": "2024-01-02T10:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": "DJI",
            "camera_model": None,
            "source_type": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": False,
            "has_lrf": False,
            "track_json": None,
        }
    )


def test_display_lines_fallback_and_subtitle_only() -> None:
    assert display_lines("", "", "en") == ("Title card", "")
    assert display_lines("  ", None, "de") == ("Titelseite", "")
    assert display_lines("", "Volkach", "en") == ("", "Volkach")
    assert display_lines("Bali 2026", "Day 2", "de") == ("Bali 2026", "Day 2")


def test_clamp_and_normalize() -> None:
    assert clamp_card_duration(0.9) == 1.0
    assert clamp_card_duration(10.1) == 10.0
    assert clamp_card_duration(3.14) == 3.1
    assert normalize_title("  " + ("x" * 90)) == "x" * 80
    assert normalize_subtitle("  hi  ") == "hi"
    assert normalize_background("Accent") == "accent"
    with pytest.raises(ValueError):
        normalize_background("hex")


def test_wrap_to_lines_ellipsis() -> None:
    lines = wrap_to_lines(
        "one two three four five",
        max_width=9,
        max_lines=2,
        measure=len,
    )
    assert len(lines) <= 2
    assert lines
    assert all(len(line) <= 9 for line in lines)


def test_persist_reopen_and_isolation(tmp_path: Path) -> None:
    db_path = tmp_path / "t.sqlite3"
    db = Database(db_path)
    a = db.create_studio_project("Alps")
    b = db.create_studio_project("Lake")
    card = db.add_studio_title_card(a.id, title_text=a.title)
    assert card.item_kind == "title_card"
    assert card.media_path is None
    assert card.identity_key is None
    assert card.card_duration_s == 3.0
    assert card.background == "dark"
    assert card.title_text == "Alps"
    db.update_studio_title_card(
        card.id,
        title_text="Bali 2026",
        subtitle_text="Day 2",
        card_duration_s=4.5,
        background="light",
    )
    db.add_studio_title_card(b.id, title_text="Other")

    reopened = Database(db_path)
    cards_a = [c for c in reopened.list_studio_items(a.id) if c.item_kind == "title_card"]
    cards_b = [c for c in reopened.list_studio_items(b.id) if c.item_kind == "title_card"]
    assert len(cards_a) == 1 and len(cards_b) == 1
    stored = cards_a[0]
    assert stored.title_text == "Bali 2026"
    assert stored.subtitle_text == "Day 2"
    assert stored.card_duration_s == 4.5
    assert stored.background == "light"
    assert stored.available is True
    assert cards_b[0].title_text == "Other"


def test_http_add_patch_reorder_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Bali 2026")
    db.set_open_studio_project_id(project.id)
    added = client.post("/api/studio/title-cards")
    assert added.status_code == 200
    body = added.json()
    card_id = body["id"]
    assert body["title"] == "Bali 2026"
    assert body["duration_s"] == 3.0
    assert body["background"] == "dark"
    page = client.get(f"/studio?select={card_id}&focus=title")
    assert page.status_code == 200
    assert "studio-preview-titlecard" in page.text
    assert "Add title card" in page.text or "Titelseite hinzufügen" in page.text
    assert 'data-kind="title_card"' in page.text
    assert "titlecard://" not in page.text
    browser = page.text.split('id="studio-browser-story"', 1)[1].split("</ul>", 1)[0]
    assert 'class="badge unavailable"' not in browser
    assert f'data-select-clip="{card_id}"' in browser
    assert "Title card" in browser or "Titelseite" in browser
    assert "studio-titlecard-swatch" in browser

    patched = client.patch(
        f"/api/studio/{card_id}/title-card",
        json={
            "title": "Bali 2026",
            "subtitle": "Day 2",
            "duration_s": 0.9,
            "background": "accent",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["duration_s"] == 1.0
    assert patched.json()["background"] == "accent"
    second = client.post("/api/studio/title-cards")
    second_id = second.json()["id"]
    ordered = client.post(
        "/api/studio/reorder",
        json={"ordered_ids": [second_id, card_id]},
    )
    assert ordered.status_code == 200
    items = db.list_studio_items(project.id)
    assert [i.id for i in items] == [second_id, card_id]
    cut = client.post(f"/api/studio/{card_id}/cut", json={"local_s": 0.5})
    assert cut.status_code == 400
    dur = client.patch(
        f"/api/studio/{card_id}/photo-duration", json={"duration_s": 2}
    )
    assert dur.status_code == 400
    removed = client.post(f"/studio/{second_id}/remove")
    assert removed.status_code in {200, 303}
    left = db.list_studio_items(project.id)
    assert [i.id for i in left] == [card_id]


def test_title_card_survives_rescan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Story")
    db.set_open_studio_project_id(project.id)
    media_id = _seed_video(db, tmp_path / "media")
    media = db.get_media(media_id)
    assert media is not None
    db.add_studio_item(
        media.path,
        identity_key=make_identity_key(media.filename, media.size_bytes, media.recorded_at),
        filename=media.filename,
        recorded_at=media.recorded_at,
        kind="video",
        project_id=project.id,
        source_media_id=media.id,
    )
    card = db.add_studio_title_card(project.id, title_text="Chapter")
    before = Path(media.path).read_bytes()
    db.link_studio_item_for_path(
        media.path,
        filename=media.filename,
        size_bytes=media.size_bytes,
        recorded_at=media.recorded_at,
    )
    items = db.list_studio_items(project.id)
    kinds = [i.kind for i in items]
    assert "title_card" in kinds
    assert "video" in kinds
    stored = next(i for i in items if i.id == card.id)
    assert stored.available is True
    assert stored.media_path is None
    assert Path(media.path).read_bytes() == before
    assert db.is_in_studio(media.path, project.id) is True
    assert db.is_in_studio("C:/missing.mp4", project.id) is False
    assert client.get("/studio").status_code == 200


def test_export_options_generated_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    project = db.create_studio_project("Cards")
    db.set_open_studio_project_id(project.id)
    empty = client.get("/api/studio/export/options")
    assert empty.status_code == 200
    assert empty.json()["options"] == []
    db.add_studio_title_card(project.id, title_text="Intro")
    opts = client.get("/api/studio/export/options")
    heights = {o["height"] for o in opts.json()["options"]}
    assert heights == {720, 1080}
    assert opts.json()["default_height"] == 1080


def test_export_options_photo_only_without_cards_stay_empty(tmp_path: Path) -> None:
    from orga_drone.studio_export import build_export_options_payload

    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Photos")
    root_id = db.add_root(tmp_path / "m", label="m")
    photo = tmp_path / "m" / "DJI_0001.JPG"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"jpeg")
    media_id = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": "photo",
            "filename": "DJI_0001.JPG",
            "path": str(photo.resolve()),
            "size_bytes": 4,
            "duration_s": None,
            "recorded_at": "2024-01-02T10:00:00",
            "sequence": 1,
            "mode": None,
            "drone_model": None,
            "camera_model": None,
            "source_type": None,
            "latitude": None,
            "longitude": None,
            "abs_alt": None,
            "has_srt": False,
            "has_lrf": False,
            "track_json": None,
        }
    )
    media = db.get_media(media_id)
    assert media is not None
    db.add_studio_item(
        media.path,
        identity_key=make_identity_key(media.filename, media.size_bytes, media.recorded_at),
        filename=media.filename,
        recorded_at=media.recorded_at,
        kind="photo",
        project_id=project.id,
        source_media_id=media.id,
    )
    payload = build_export_options_payload(db, project.id)
    assert payload["options"] == []


def test_render_title_card_uses_locked_colors() -> None:
    try:
        img = render_title_card_image(
            width=320,
            height=180,
            title="Bali 2026",
            subtitle="Day 2",
            background="dark",
            locale="en",
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"title card font unavailable: {exc}")
    px = img.getpixel((2, 2))
    expected = TITLE_CARD_PRESETS["dark"].bg.lstrip("#")
    rgb = tuple(int(expected[i : i + 2], 16) for i in (0, 2, 4))
    assert px == rgb


def test_prepare_export_title_card_only(tmp_path: Path) -> None:
    from orga_drone.studio_export import prepare_studio_export

    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Solo")
    db.add_studio_title_card(project.id, title_text="Intro")
    dest = tmp_path / "out.mp4"
    cfg = prepare_studio_export(
        db, height=1080, output_path=dest, overwrite=True, project_id=project.id
    )
    assert len(cfg.clips) == 1
    assert cfg.clips[0].kind == "title_card"
    assert cfg.clips[0].source_path is None
    assert cfg.width == 1920
    assert cfg.height == 1080


def test_existing_studio_clips_without_item_kind_migrate(tmp_path: Path) -> None:
    """Opening a pre-#26 library must rebuild studio_clips, not fail on SCHEMA indexes."""
    db_path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE studio_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE studio_clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
            media_path TEXT NOT NULL,
            identity_key TEXT NOT NULL,
            source_media_id INTEGER,
            position INTEGER NOT NULL,
            filename_snapshot TEXT NOT NULL,
            recorded_at_snapshot TEXT,
            kind_snapshot TEXT NOT NULL DEFAULT 'photo',
            photo_duration_s REAL,
            source_start REAL,
            source_end REAL,
            playback_speed REAL NOT NULL DEFAULT 1.0,
            volume REAL NOT NULL DEFAULT 1.0,
            transition TEXT,
            effect_settings TEXT NOT NULL DEFAULT '{}',
            added_at TEXT NOT NULL
        );
        INSERT INTO studio_projects(id, title, created_at, updated_at)
        VALUES (1, 'Legacy story', '2026-01-01T00:00:00', '2026-01-01T00:00:00');
        INSERT INTO studio_clips(
            id, project_id, media_path, identity_key, source_media_id, position,
            filename_snapshot, recorded_at_snapshot, kind_snapshot,
            photo_duration_s, source_start, source_end,
            playback_speed, volume, transition, effect_settings, added_at
        ) VALUES (
            1, 1, '/tmp/DJI_0001.MP4', 'id-1', NULL, 0,
            'DJI_0001.MP4', '2024-01-02T10:00:00', 'video',
            NULL, NULL, NULL, 1.0, 1.0, NULL, '{}', '2026-01-01T00:00:00'
        );
        """
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    items = db.list_studio_items(1)
    assert len(items) == 1
    assert items[0].item_kind == "media"
    assert items[0].media_path == "/tmp/DJI_0001.MP4"
    db.add_studio_title_card(1, title_text="Intro")
    kinds = [i.item_kind for i in db.list_studio_items(1)]
    assert kinds == ["media", "title_card"]


def test_estimate_summary_counts_media_not_cards(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    project = db.create_studio_project("Mix")
    db.add_studio_title_card(project.id, title_text="Intro", card_duration_s=3.0)
    media_id = _seed_video(db, tmp_path / "media")
    media = db.get_media(media_id)
    assert media is not None
    db.add_studio_item(
        media.path,
        identity_key=make_identity_key(media.filename, media.size_bytes, media.recorded_at),
        filename=media.filename,
        recorded_at=media.recorded_at,
        kind="video",
        project_id=project.id,
        source_media_id=media.id,
    )
    items = db.list_studio_items(project.id)
    summary = summarize_studio_items(items)
    assert summary.video_count == 1
    assert summary.photo_count == 0
    assert summary.estimated_total_s >= 15.0
    card = next(i for i in items if i.kind == "title_card")
    assert (
        effective_seconds(
            kind="title_card",
            photo_duration_s=None,
            duration_s=None,
            available=True,
            card_duration_s=card.card_duration_s,
        )
        == 3.0
    )
