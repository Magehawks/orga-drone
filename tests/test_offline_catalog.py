"""Catalog rows stay when a library root cannot be listed."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.scan import scan_all_roots, scan_root


def _write_jpg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), (12, 40, 80)).save(path, format="JPEG")


def _index(tmp_path: Path) -> tuple[Database, int, Path]:
    lib = tmp_path / "sd"
    _write_jpg(lib / "coast.jpg")
    db = Database(tmp_path / "t.sqlite3")
    root_id = db.add_root(lib, "SD card")
    counts = scan_root(db, root_id, lib)
    assert counts["photos"] == 1
    item = db.list_media()[0]
    db.upsert_media_meta(
        item.path,
        stars=4,
        favorite=True,
        tags=["coast"],
        notes="keep me",
    )
    return db, root_id, lib


def _meta_count(db: Database) -> int:
    with db.connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM media_meta").fetchone()
    assert row is not None
    return int(row["c"])


def test_missing_root_scan_preserves_catalog_and_user_meta(tmp_path: Path) -> None:
    db, root_id, lib = _index(tmp_path)
    away = tmp_path / "sd-away"
    lib.rename(away)

    one = scan_root(db, root_id, lib)
    assert one["offline"] == 1
    assert one["preserved"] == 1
    all_roots = scan_all_roots(db)
    assert all_roots[0]["error"] == "missing"
    assert all_roots[0]["preserved"] == 1

    rows = db.list_media()
    assert len(rows) == 1
    assert rows[0].filename == "coast.jpg"
    assert rows[0].favorite is True
    assert rows[0].stars == 4
    assert rows[0].notes == "keep me"
    assert _meta_count(db) == 1


def test_interrupted_discovery_does_not_clear_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, root_id, lib = _index(tmp_path)

    def disconnected(root: Path, on_found=None, *, root_id: int | None = None):
        shutil.rmtree(root)
        raise OSError("drive removed during discovery")

    monkeypatch.setattr("orga_drone.scan.iter_media_files", disconnected)
    result = scan_root(db, root_id, lib)
    assert result["preserved"] == 1
    assert len(db.list_media()) == 1
    assert db.list_media()[0].notes == "keep me"


def test_listing_error_on_a_present_root_does_not_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, root_id, lib = _index(tmp_path)

    def broken(root: Path, on_found=None, *, root_id: int | None = None):
        raise OSError("could not read a subdirectory")

    monkeypatch.setattr("orga_drone.scan.iter_media_files", broken)
    with pytest.raises(OSError, match="subdirectory"):
        scan_root(db, root_id, lib)
    assert len(db.list_media()) == 1
    assert _meta_count(db) == 1


def test_interrupted_read_after_listing_preserves_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, root_id, lib = _index(tmp_path)
    # A size/mtime match skips parsing. Bump mtime so this rescan still reads
    # the file, which is where a disappearing source must not clear the catalog.
    (lib / "coast.jpg").touch()
    import orga_drone.scan as scan_mod

    real_parse = scan_mod.parse_media_file

    def drop_source(path: Path):
        parent = path.parent
        if parent.exists():
            shutil.rmtree(parent)
        return real_parse(path)

    monkeypatch.setattr("orga_drone.scan.parse_media_file", drop_source)
    result = scan_root(db, root_id, lib)
    assert result["preserved"] == 1
    assert len(db.list_media()) == 1
    assert db.list_media()[0].favorite is True


def test_files_removed_from_a_listable_folder_are_dropped(tmp_path: Path) -> None:
    db, root_id, lib = _index(tmp_path)
    (lib / "coast.jpg").unlink()
    result = scan_root(db, root_id, lib)
    assert result.get("offline") != 1
    assert db.list_media() == []


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    return create_app()


def _wait_job(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 10
    last: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/scan-jobs/{job_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["state"] in {"completed", "failed"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"job did not finish: {last}")


def test_reconnect_restores_open_without_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    client = TestClient(app)
    db: Database = app.state.db
    lib = tmp_path / "sd"
    _write_jpg(lib / "coast.jpg")
    root_id = db.add_root(lib, "SD card")
    scan_root(db, root_id, lib)
    item = db.list_media()[0]
    db.upsert_media_meta(item.path, stars=5, favorite=True, tags=["trip"], notes="keep me")
    media_id = item.id

    away = tmp_path / "sd-away"
    lib.rename(away)

    start = client.post(f"/library/{root_id}/scan", follow_redirects=False)
    assert start.status_code == 303
    job_id = start.headers["location"].split("scan_job=", 1)[1].split("&", 1)[0]
    job = _wait_job(client, job_id)
    assert job["state"] == "completed"
    assert len(db.list_media()) == 1

    cookies = {"lang": "en"}
    library = client.get("/library", cookies=cookies)
    assert library.status_code == 200
    assert "Offline" in library.text
    assert "Source offline. Catalog entries stay until this folder is connected again." in library.text

    browse = client.get("/browse", cookies=cookies)
    assert "badge unavailable" in browse.text
    assert "thumb-placeholder" in browse.text
    assert f"/media/{media_id}/thumb" not in browse.text

    listed = client.get("/browse?view=list", cookies=cookies)
    assert "badge unavailable" in listed.text
    assert f"/media/{media_id}/thumb" not in listed.text

    detail = client.get(f"/media/{media_id}", cookies=cookies)
    assert "Source offline. This catalog entry is kept. Connect the drive to open it again." in detail.text
    assert client.get(f"/media/{media_id}/stream").status_code == 404

    geo = client.get("/api/geo/media?include_noloc=1")
    assert geo.status_code == 200
    without = geo.json()["without_location"]
    assert len(without) == 1
    assert without[0]["source_offline"] is True

    dash = client.get("/", cookies=cookies)
    assert "dash-rail-thumb" in dash.text
    assert f"/media/{media_id}/thumb" not in dash.text

    away.rename(lib)
    online = client.get("/browse", cookies=cookies)
    assert "Source offline" not in online.text
    assert "thumb-placeholder" not in online.text
    assert client.get(f"/media/{media_id}/stream").status_code == 200
    detail_online = client.get(f"/media/{media_id}", cookies=cookies)
    assert "Source offline" not in detail_online.text

    again = scan_root(db, root_id, lib)
    assert again.get("offline") != 1
    assert again["photos"] == 1
    rows = db.list_media()
    assert len(rows) == 1
    assert len({row.path for row in rows}) == 1
    assert rows[0].favorite is True
    assert rows[0].stars == 5
    assert rows[0].notes == "keep me"
    assert client.get(f"/media/{rows[0].id}/stream").status_code == 200
    geo_online = client.get("/api/geo/media?include_noloc=1")
    assert geo_online.json()["without_location"][0]["source_offline"] is False
