"""Tests for library scan progress, job store, and status API."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orga_drone.config import Settings
from orga_drone.db import Database
from orga_drone.scan import iter_media_files, scan_root
from orga_drone.scan.jobs import ScanJobStore
from orga_drone.scan.progress import ScanProgress, display_scan_path


def _write_jpg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (20, 40, 60)).save(path, format="JPEG")


def test_display_scan_path_is_relative_not_absolute(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    nested = root / "day1" / "shot.jpg"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"x")
    shown = display_scan_path(nested, root)
    assert shown == "day1/shot.jpg" or shown == "day1\\shot.jpg".replace("\\", "/")
    assert ":" not in shown or shown.startswith("day1")
    assert not Path(shown).is_absolute()
    assert str(root.resolve()) not in shown


def test_scan_root_without_callback_still_works(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    _write_jpg(lib / "a.jpg")
    db = Database(tmp_path / "t.sqlite3")
    root_id = db.add_root(lib, "t")
    counts = scan_root(db, root_id, lib)
    assert counts["photos"] == 1
    assert counts["assets"] >= 1


def test_progress_callback_phases_and_counters(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    _write_jpg(lib / "one.jpg")
    _write_jpg(lib / "sub" / "two.jpg")
    (lib / "notes.txt").write_text("ignore", encoding="utf-8")

    events: list[ScanProgress] = []
    db = Database(tmp_path / "t.sqlite3")
    root_id = db.add_root(lib, "t")
    counts = scan_root(db, root_id, lib, on_progress=events.append)

    assert counts["photos"] == 2
    phases = [e.phase for e in events]
    assert "discovering" in phases
    assert "indexing" in phases
    assert "grouping" in phases
    assert phases[-1] == "done"

    discovering = [e for e in events if e.phase == "discovering"]
    assert discovering
    assert max(e.discovered for e in discovering) == 2

    indexing = [e for e in events if e.phase == "indexing"]
    assert indexing
    assert indexing[-1].processed == 2
    assert indexing[-1].discovered == 2
    for e in indexing:
        if e.current_path:
            assert not Path(e.current_path).is_absolute()
            assert str(lib.resolve()) not in e.current_path

    grouping = [e for e in events if e.phase == "grouping"]
    assert grouping
    assert all(e.current_path is None for e in grouping)


def test_job_store_state_transitions_and_failure() -> None:
    store = ScanJobStore(max_finished=5, finished_ttl_s=60)
    job = store.try_create(root_id=1)
    assert job is not None
    assert job.state == "pending"
    assert store.try_create() is None

    store.mark_running(job.id)
    running = store.get(job.id)
    assert running is not None
    assert running.state == "running"

    store.apply_progress(
        job.id,
        ScanProgress(phase="indexing", discovered=3, processed=1, current_path="a.jpg"),
    )
    mid = store.get(job.id)
    assert mid is not None
    assert mid.phase == "indexing"
    assert mid.processed == 1
    assert mid.discovered == 3

    store.complete(job.id, {"photos": 2})
    done = store.get(job.id)
    assert done is not None
    assert done.state == "completed"
    assert done.phase == "done"
    assert done.counts == {"photos": 2}
    assert store.has_active() is False

    job2 = store.try_create()
    assert job2 is not None
    store.fail(job2.id, "boom")
    failed = store.get(job2.id)
    assert failed is not None
    assert failed.state == "failed"
    assert failed.error == "boom"


def test_stale_job_cleanup() -> None:
    store = ScanJobStore(max_finished=2, finished_ttl_s=0.05)
    a = store.try_create()
    assert a is not None
    store.complete(a.id, {})
    time.sleep(0.06)
    b = store.try_create()
    assert b is not None
    store.complete(b.id, {})
    c = store.try_create()
    assert c is not None
    store.complete(c.id, {})
    store.cleanup()
    # TTL removes old finished jobs; bounded max also trims.
    remaining = [store.get(a.id), store.get(b.id), store.get(c.id)]
    present = [j for j in remaining if j is not None]
    assert len(present) <= 2
    assert store.get(a.id) is None


def test_iter_media_files_discovery_callback(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    _write_jpg(lib / "x.jpg")
    events: list[ScanProgress] = []
    files = iter_media_files(lib, events.append)
    assert len(files) == 1
    assert events
    assert all(e.phase == "discovering" for e in events)
    assert events[-1].discovered == 1


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "orga_drone.app.settings",
        Settings(data_dir=tmp_path / "data"),
    )
    from orga_drone.app import create_app

    return create_app()


def _wait_job(client: TestClient, job_id: str, *, timeout_s: float = 10.0) -> dict:
    deadline = time.time() + timeout_s
    last: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/scan-jobs/{job_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["state"] in {"completed", "failed"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {last}")


def test_library_scan_api_completion_and_busy_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from orga_drone import scan as scan_mod

    release = threading.Event()
    entered = threading.Event()
    real_scan_root = scan_mod.scan_root

    def slow_scan_root(db, root_id, root_path, on_progress=None):
        entered.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test release not signaled")
        return real_scan_root(db, root_id, root_path, on_progress=on_progress)

    monkeypatch.setattr("orga_drone.app.scan_root", slow_scan_root)

    app = _app(tmp_path, monkeypatch)
    client = TestClient(app)
    lib = tmp_path / "lib"
    _write_jpg(lib / "photo.jpg")

    start = client.post(
        "/library/add",
        data={"path": str(lib), "label": "t"},
        follow_redirects=False,
    )
    assert start.status_code == 303
    loc = start.headers["location"]
    assert "scan_job=" in loc
    job_id = loc.split("scan_job=", 1)[1].split("&", 1)[0]

    assert entered.wait(timeout=5)

    busy = client.post(
        f"/library/{app.state.db.list_roots()[0]['id']}/scan",
        follow_redirects=False,
    )
    assert busy.status_code == 303
    assert "scan_error=busy" in busy.headers["location"]

    page = client.get("/library?scan_error=busy")
    assert page.status_code == 200
    assert "already running" in page.text.lower() or "läuft bereits" in page.text.lower()

    release.set()
    final = _wait_job(client, job_id)
    assert final["state"] == "completed"
    assert final["phase"] == "done"
    assert (final.get("discovered") or 0) >= 1

    status = client.get(f"/api/scan-jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["state"] == "completed"


def test_scan_job_worker_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, monkeypatch)
    store: ScanJobStore = app.state.scan_jobs
    job = store.try_create(root_id=1)
    assert job is not None

    def boom(_on_progress) -> None:
        raise RuntimeError("forced failure")

    # Mirror app worker path
    store.mark_running(job.id)
    try:
        boom(lambda _p: None)
        store.complete(job.id, {})
    except Exception as exc:
        store.fail(job.id, str(exc))

    failed = store.get(job.id)
    assert failed is not None
    assert failed.state == "failed"
    assert "forced failure" in (failed.error or "")
