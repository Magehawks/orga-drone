"""Tests for date filters, NL search parser, and /api/search."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.search import parse_natural_query


def _seed(
    db: Database,
    root_path: Path,
    *,
    filename: str,
    kind: str,
    recorded_at: str,
    tags: list[str] | None = None,
    notes: str = "",
) -> int:
    root_path.mkdir(parents=True, exist_ok=True)
    roots = db.list_roots()
    if roots:
        root_id = int(roots[0]["id"])
    else:
        root_id = db.add_root(root_path, label="test")
    media_file = root_path / filename
    media_file.write_bytes(b"fake")
    path = str(media_file.resolve())
    mid = db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": filename,
            "path": path,
            "size_bytes": 4,
            "duration_s": 12.0 if kind == "video" else None,
            "recorded_at": recorded_at,
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
    if tags or notes:
        db.upsert_media_meta(path, stars=0, favorite=False, tags=tags or [], notes=notes)
    return mid


def test_parse_natural_query_examples() -> None:
    malta = parse_natural_query("zeig mir die videos vom malta urlaub")
    assert malta.kind == "video"
    assert malta.place == "malta"
    assert "urlaub" in malta.tags
    assert malta.effective_q() is not None
    assert "malta" in malta.effective_q()

    nov = parse_natural_query("alle bilder von 2025 november")
    assert nov.kind == "photo"
    assert nov.date_from == "2025-11-01"
    assert nov.date_to == "2025-11-30"

    en = parse_natural_query("photos November 2025")
    assert en.kind == "photo"
    assert en.date_from == "2025-11-01"
    assert en.date_to == "2025-11-30"

    year = parse_natural_query("videos 2024")
    assert year.kind == "video"
    assert year.date_from == "2024-01-01"
    assert year.date_to == "2024-12-31"


def test_list_media_date_range_and_token_and(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    lib = tmp_path / "lib"
    _seed(db, lib, filename="a.MP4", kind="video", recorded_at="2025-11-05T10:00:00", tags=["malta"])
    _seed(db, lib, filename="b.JPG", kind="photo", recorded_at="2025-11-10T10:00:00", tags=["malta", "urlaub"])
    _seed(db, lib, filename="c.JPG", kind="photo", recorded_at="2025-10-01T10:00:00", tags=["malta"])

    nov_photos = db.list_media(
        kind="photo",
        date_from="2025-11-01",
        date_to="2025-11-30",
    )
    assert [i.filename for i in nov_photos] == ["b.JPG"]

    malta_urlaub = db.list_media(q="malta urlaub")
    assert [i.filename for i in malta_urlaub] == ["b.JPG"]


def test_browse_ask_and_api_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    app = create_app()
    db: Database = app.state.db
    lib = tmp_path / "lib"
    _seed(db, lib, filename="nov.JPG", kind="photo", recorded_at="2025-11-12T09:00:00")
    _seed(
        db,
        lib,
        filename="malta.MP4",
        kind="video",
        recorded_at="2024-06-01T12:00:00",
        tags=["malta", "urlaub"],
    )

    client = TestClient(app)
    browse = client.get("/browse", params={"ask": "alle bilder von 2025 november"})
    assert browse.status_code == 200
    assert "nov.JPG" in browse.text
    assert "malta.MP4" not in browse.text
    assert "Interpreted as" in browse.text or "Interpretiert als" in browse.text

    api = client.post(
        "/api/search",
        json={"ask": "zeig mir die videos vom malta urlaub"},
    )
    assert api.status_code == 200
    body = api.json()
    assert body["filters"]["kind"] == "video"
    assert body["count"] == 1
    assert body["items"][0]["filename"] == "malta.MP4"

    ranged = client.post(
        "/api/search",
        json={"kind": "photo", "date_from": "2025-11-01", "date_to": "2025-11-30"},
    )
    assert ranged.json()["count"] == 1
    assert ranged.json()["items"][0]["filename"] == "nov.JPG"
