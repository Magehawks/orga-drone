"""Browse recording-date timeline: groups, filters, unknown dates, pagination."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orga_drone.app import BROWSE_PAGE_SIZE
from orga_drone.browse_timeline import (
    build_timeline_nav,
    group_timeline_page,
    parse_recording_day,
    parse_timeline_focus,
    recorded_span_clause,
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


def _add(
    db: Database,
    root_id: int,
    root: Path,
    name: str,
    *,
    kind: str = "video",
    recorded_at: str | None = "2024-06-02T12:00:00",
    drone: str = "Mini 4 Pro",
    place: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> int:
    path = root / name
    path.write_bytes(b"x")
    return db.upsert_media(
        {
            "root_id": root_id,
            "primary_asset_id": None,
            "kind": kind,
            "filename": name,
            "path": str(path.resolve()),
            "size_bytes": 1000,
            "duration_s": 2.0,
            "recorded_at": recorded_at,
            "sequence": None,
            "mode": None,
            "drone_model": drone,
            "camera_model": None,
            "latitude": latitude,
            "longitude": longitude,
            "abs_alt": None,
            "has_srt": 0,
            "has_lrf": 0,
            "track_json": None,
            "place_json": json.dumps({"city": place}) if place else None,
        }
    )


class _Item:
    def __init__(self, name: str, recorded_at: str | None) -> None:
        self.filename = name
        self.recorded_at = recorded_at


def test_parse_recording_day_and_focus() -> None:
    day = parse_recording_day("2024-06-02T18:30:00")
    assert day is not None
    assert day.iso == "2024-06-02"
    assert parse_recording_day(None) is None
    assert parse_recording_day("") is None
    assert parse_recording_day("not-a-date") is None
    assert parse_recording_day("2024-02-31T00:00:00") is None
    assert parse_recording_day("2024-6-2") is None

    assert parse_timeline_focus(None) is None
    assert parse_timeline_focus("nope") is None
    assert parse_timeline_focus("2024-02-31") is None
    assert parse_timeline_focus("2024-06-02T12:00:00") is None
    unknown = parse_timeline_focus("unknown")
    assert unknown is not None and unknown.token == "unknown"
    year = parse_timeline_focus("2024")
    assert year is not None and year.kind == "year" and year.token == "2024"
    month = parse_timeline_focus("2024-06")
    assert month is not None and month.token == "2024-06"
    exact = parse_timeline_focus("2024-06-02")
    assert exact is not None and exact.kind == "day"
    sql, params = recorded_span_clause("unknown")
    assert sql is not None and "NOT" in sql and params == []
    sql, params = recorded_span_clause("2024-06")
    assert params == ["2024-06"]
    assert recorded_span_clause("nope") == (None, [])


def test_group_order_keeps_input_and_unknown_bucket() -> None:
    items = [
        _Item("evening", "2024-06-02T18:00:00"),
        _Item("morning-later-id", "2024-06-02T08:00:00"),
        _Item("older-year", "2023-01-15T09:00:00"),
        _Item("blank", None),
        _Item("garbage", "not-a-date"),
    ]

    def href(token: str | None) -> str:
        return token or "all"

    groups = group_timeline_page(items, href_for=href)
    assert [year.key for year in groups] == ["2024", "2023", "unknown"]
    june = groups[0].months[0]
    assert june.month_label == "June"
    assert [item.filename for item in june.days[0].items] == [
        "evening",
        "morning-later-id",
    ]
    assert june.days[0].href == "2024-06-02"
    unknown_items = groups[-1].months[0].days[0].items
    assert [item.filename for item in unknown_items] == ["blank", "garbage"]
    assert groups[-1].known is False


def test_nav_opens_year_then_month_then_day() -> None:
    counts = [("2024-06-02", 2), ("2024-05-01", 1), ("2023-01-15", 4), (None, 3)]

    def href(token: str | None) -> str:
        return f"/{token}" if token else "/all"

    newest = build_timeline_nav(counts, active=None, order="desc", href_for=href)
    assert newest.all_active is True
    assert [year.link.label for year in newest.years] == ["2024", "2023"]
    assert newest.years[0].open is True
    assert newest.years[1].open is False
    assert [month.link.month_label for month in newest.years[0].months] == ["June", "May"]
    assert all(not month.open for month in newest.years[0].months)
    assert newest.unknown_count == 3

    month = parse_timeline_focus("2024-05")
    opened = build_timeline_nav(counts, active=month, order="desc", href_for=href)
    may = next(item for item in opened.years[0].months if item.link.token == "2024-05")
    assert opened.years[0].open is True
    assert opened.years[0].link.active is False
    assert may.open is True and may.link.active is True
    assert may.days[0].label == "1"
    assert may.days[0].active is False

    day = parse_timeline_focus("2024-06-02")
    on_day = build_timeline_nav(counts, active=day, order="asc", href_for=href)
    assert [year.link.label for year in on_day.years] == ["2023", "2024"]
    june = next(item for item in on_day.years[1].months if item.link.token == "2024-06")
    assert june.open is True
    assert june.days[0].active is True


def test_list_media_date_order_is_stable(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.sqlite3")
    root = tmp_path / "lib"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    _add(db, root_id, root, "b.MP4", recorded_at="2024-06-02T08:00:00")
    _add(db, root_id, root, "c.MP4", recorded_at="2024-06-02T18:00:00")
    _add(db, root_id, root, "d.MP4", recorded_at="2024-06-02T08:00:00")
    _add(db, root_id, root, "a.MP4", recorded_at="2023-01-15T09:00:00")
    _add(db, root_id, root, "e.MP4", recorded_at=None)
    _add(db, root_id, root, "f.JPG", kind="photo", recorded_at="not-a-date")
    _add(db, root_id, root, "g.MP4", recorded_at="2024-02-31T00:00:00")

    desc = [item.filename for item in db.list_media(date_order="desc")]
    assert desc[:4] == ["c.MP4", "d.MP4", "b.MP4", "a.MP4"]
    assert desc[-3:] == ["g.MP4", "f.JPG", "e.MP4"]
    asc = [item.filename for item in db.list_media(date_order="asc")]
    assert asc[0] == "a.MP4"
    assert asc[-3:] and set(asc[-3:]) == {"g.MP4", "f.JPG", "e.MP4"}
    counts = dict(db.timeline_day_counts())
    assert counts["2024-06-02"] == 3
    assert counts["2023-01-15"] == 1
    assert counts[None] == 3
    only_june = db.list_media(recorded_span="2024-06", date_order="desc")
    assert {item.filename for item in only_june} == {"b.MP4", "c.MP4", "d.MP4"}
    unknown = db.list_media(recorded_span="unknown", date_order="desc")
    assert {item.filename for item in unknown} == {"e.MP4", "f.JPG", "g.MP4"}


def test_browse_timeline_navigation_filters_and_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    root = tmp_path / "lib"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    _add(db, root_id, root, "malta.MP4", recorded_at="2024-06-02T18:00:00", place="Malta", latitude=35.9, longitude=14.4)
    _add(
        db,
        root_id,
        root,
        "malta-photo.JPG",
        kind="photo",
        recorded_at="2024-06-02T08:00:00",
        drone="Avata 2",
        place="Malta",
    )
    _add(db, root_id, root, "older.MP4", recorded_at="2023-01-15T09:00:00", drone="Avata 2")
    _add(db, root_id, root, "nodate.MP4", recorded_at=None)
    for i in range(BROWSE_PAGE_SIZE):
        _add(
            db,
            root_id,
            root,
            f"bulk_{i:03d}.MP4",
            recorded_at=f"2025-03-{(i % 28) + 1:02d}T12:00:00",
            drone="Mini 4 Pro",
        )

    client = TestClient(app)
    page = client.get("/browse", params={"view": "timeline"}, cookies={"lang": "en"})
    assert page.status_code == 200
    text = page.text
    assert "timeline-nav" in text
    assert "media-timeline" in text
    assert "All dates" in text
    assert "2025" in text
    assert "March" in text
    assert 'class="card"' in text
    assert text.count('class="card"') == BROWSE_PAGE_SIZE
    assert "browse-pager" in text
    assert "view=timeline" in text
    assert "Timeline follows the recording date." in text
    assert "studio-timeline" not in text
    assert text.index("2025") < text.index("2024")
    assert "malta.MP4" not in text

    page2 = client.get("/browse", params={"view": "timeline", "page": 2}, cookies={"lang": "en"})
    assert page2.status_code == 200
    body = page2.text
    assert body.index("malta.MP4") < body.index("malta-photo.JPG")
    assert body.index("malta-photo.JPG") < body.index("older.MP4")
    assert body.index("older.MP4") < body.index("nodate.MP4")
    assert "Date unknown" in body

    year = client.get("/browse", params={"view": "timeline", "tl": "2024"}, cookies={"lang": "en"})
    assert year.status_code == 200
    assert "malta.MP4" in year.text
    assert "malta-photo.JPG" in year.text
    assert "older.MP4" not in year.text
    assert "June" in year.text
    assert "nodate.MP4" not in year.text
    assert 'aria-current="page"' in year.text

    month = client.get(
        "/browse", params={"view": "timeline", "tl": "2024-06"}, cookies={"lang": "en"}
    )
    assert "malta.MP4" in month.text
    assert "older.MP4" not in month.text
    assert "2 June 2024" in month.text

    day = client.get(
        "/browse",
        params={"view": "timeline", "tl": "2024-06-02", "order": "asc"},
        cookies={"lang": "en"},
    )
    assert day.text.index("malta-photo.JPG") < day.text.index("malta.MP4")

    unknown = client.get(
        "/browse", params={"view": "timeline", "tl": "unknown"}, cookies={"lang": "en"}
    )
    assert "Date unknown" in unknown.text
    assert "nodate.MP4" in unknown.text
    assert "malta.MP4" not in unknown.text
    assert "missing or not a calendar day" in unknown.text

    ignored = client.get(
        "/browse", params={"view": "timeline", "tl": "not-a-focus"}, cookies={"lang": "en"}
    )
    assert ignored.text.count('class="card"') == BROWSE_PAGE_SIZE
    assert "2025" in ignored.text and "2023" in ignored.text
    ignored_page = client.get(
        "/browse",
        params={"view": "timeline", "tl": "not-a-focus", "page": 2},
        cookies={"lang": "en"},
    )
    assert "malta.MP4" in ignored_page.text
    assert "older.MP4" in ignored_page.text

    filtered = client.get(
        "/browse",
        params={
            "view": "timeline",
            "drone": "Avata 2",
            "kind": "photo",
            "q": "Malta",
            "date_from": "2024-06-01",
            "date_to": "2024-06-30",
        },
        cookies={"lang": "en"},
    )
    assert filtered.status_code == 200
    assert "malta-photo.JPG" in filtered.text
    assert "malta.MP4" not in filtered.text
    assert "older.MP4" not in filtered.text
    assert "2023" not in filtered.text

    grid = client.get("/browse", params={"view": "grid"}, cookies={"lang": "en"})
    assert "timeline-nav" not in grid.text
    assert grid.text.count('class="card"') == BROWSE_PAGE_SIZE

    german = client.get("/browse", params={"view": "timeline", "tl": "2024-06"}, cookies={"lang": "de"})
    assert "Zeitleiste" in german.text
    assert "Alle Daten" in german.text
    assert "Juni" in german.text

    studio = client.get("/studio", cookies={"lang": "en"})
    assert studio.status_code == 200
    assert "studio.js" in studio.text
    assert "timeline-nav" not in studio.text
    assert "media-timeline" not in studio.text


def test_timeline_detail_return_keeps_focus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    db: Database = app.state.db
    root = tmp_path / "lib"
    root.mkdir()
    root_id = db.add_root(root, label="t")
    media_id = _add(db, root_id, root, "malta.MP4", place="Valletta")
    client = TestClient(app)
    browse = client.get(
        "/browse",
        params={"view": "timeline", "tl": "2024-06", "q": "Valletta", "page_size": 50},
        cookies={"lang": "en"},
    )
    assert f"/media/{media_id}?" in browse.text
    assert "tl=2024-06" in browse.text
    detail = client.get(
        f"/media/{media_id}",
        params={"from": "browse", "view": "timeline", "tl": "2024-06", "q": "Valletta"},
        cookies={"lang": "en"},
    )
    assert detail.status_code == 200
    assert "view=timeline" in detail.text
    assert "tl=2024-06" in detail.text
    assert "Valletta" in detail.text or "q=Valletta" in detail.text
