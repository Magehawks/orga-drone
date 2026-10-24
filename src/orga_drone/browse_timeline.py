"""Chronological Browse groups for indexed photos and videos.

This is the library rediscovery timeline (year / month / day). It does not
share code with the Studio story timeline.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

FocusKind = Literal["year", "month", "day", "unknown"]

MONTH_LABELS: tuple[str, ...] = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True)
class RecordingDay:
    year: str
    month: str
    day: str

    @property
    def iso(self) -> str:
        return f"{self.year}-{self.month}-{self.day}"


@dataclass(frozen=True)
class TimelineFocus:
    kind: FocusKind
    year: str = ""
    month: str = ""
    day: str = ""

    @property
    def token(self) -> str:
        if self.kind == "unknown":
            return "unknown"
        if self.kind == "year":
            return self.year
        if self.kind == "month":
            return f"{self.year}-{self.month}"
        return f"{self.year}-{self.month}-{self.day}"


@dataclass
class TimelineDayBlock:
    key: str
    known: bool
    year: str
    month: str
    day_num: str
    month_label: str
    href: str
    items: list[Any] = field(default_factory=list)


@dataclass
class TimelineMonthBlock:
    key: str
    known: bool
    year: str
    month_label: str
    href: str
    days: list[TimelineDayBlock] = field(default_factory=list)


@dataclass
class TimelineYearBlock:
    key: str
    known: bool
    year: str
    href: str
    months: list[TimelineMonthBlock] = field(default_factory=list)


@dataclass(frozen=True)
class TimelineNavLink:
    token: str
    label: str
    count: int
    href: str
    active: bool
    month_label: str = ""


@dataclass
class TimelineNavMonth:
    link: TimelineNavLink
    open: bool
    days: list[TimelineNavLink] = field(default_factory=list)


@dataclass
class TimelineNavYear:
    link: TimelineNavLink
    open: bool
    months: list[TimelineNavMonth] = field(default_factory=list)


@dataclass
class TimelineNav:
    all_href: str
    all_active: bool
    years: list[TimelineNavYear]
    unknown_count: int
    unknown_href: str
    unknown_active: bool


def month_label(month: str) -> str:
    try:
        index = int(month) - 1
    except ValueError:
        return month
    if 0 <= index < len(MONTH_LABELS):
        return MONTH_LABELS[index]
    return month


def parse_recording_day(value: str | None) -> RecordingDay | None:
    """Calendar day from a stored ``recorded_at``, or None when it is not one.

    Accepts an ISO ``YYYY-MM-DD`` prefix (the form the scanner stores). Blank,
    non-ISO, and impossible dates are unknown so Browse can show them apart
    from real recording days.
    """
    if value is None:
        return None
    text = value.strip()
    if len(text) < 10 or text[4] != "-" or text[7] != "-":
        return None
    year_s, month_s, day_s = text[0:4], text[5:7], text[8:10]
    if not (year_s.isdigit() and month_s.isdigit() and day_s.isdigit()):
        return None
    year, month, day = int(year_s), int(month_s), int(day_s)
    try:
        datetime(year, month, day)
    except ValueError:
        return None
    return RecordingDay(f"{year:04d}", f"{month:02d}", f"{day:02d}")


def parse_timeline_focus(raw: str | None) -> TimelineFocus | None:
    """Allowlisted Browse focus: ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD``, or ``unknown``."""
    text = (raw or "").strip()
    if not text:
        return None
    if text == "unknown":
        return TimelineFocus("unknown")
    if len(text) == 4 and text.isdigit():
        year = int(text)
        if 1 <= year <= 9999:
            return TimelineFocus("year", f"{year:04d}")
        return None
    if len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:7].isdigit():
        year = int(text[:4])
        month = int(text[5:7])
        if 1 <= year <= 9999 and 1 <= month <= 12:
            return TimelineFocus("month", f"{year:04d}", f"{month:02d}")
        return None
    if len(text) == 10:
        parsed = parse_recording_day(text)
        if parsed is not None and parsed.iso == text:
            return TimelineFocus("day", parsed.year, parsed.month, parsed.day)
    return None


# A stored value counts as a calendar day only when SQLite's date() agrees with
# the ISO prefix. That rejects NULL, junk, and dates SQLite would roll over
# (for example 2024-02-31) so Python grouping and SQL stay on the same day.
RECORDED_DAY_KNOWN_SQL = (
    "date(m.recorded_at) IS NOT NULL AND substr(m.recorded_at, 1, 10) = date(m.recorded_at)"
)


def timeline_order_sql(direction: str) -> str:
    """ORDER BY for the Browse timeline. Known days first; unknown dates last."""
    if direction not in {"ASC", "DESC"}:
        direction = "DESC"
    known = RECORDED_DAY_KNOWN_SQL
    return (
        f"CASE WHEN {known} THEN 0 ELSE 1 END ASC, "
        f"CASE WHEN {known} THEN date(m.recorded_at) END {direction}, "
        f"CASE WHEN {known} THEN m.recorded_at END {direction}, "
        "m.id DESC"
    )


def timeline_day_key_sql() -> str:
    """SELECT expression: ISO day, or NULL when the recording date is unknown."""
    return f"CASE WHEN {RECORDED_DAY_KNOWN_SQL} THEN date(m.recorded_at) ELSE NULL END"


def recorded_span_clause(span: str | None) -> tuple[str | None, list[str]]:
    """SQL predicate for a timeline focus. Invalid values add no clause."""
    focus = parse_timeline_focus(span)
    if focus is None:
        return None, []
    known = RECORDED_DAY_KNOWN_SQL
    if focus.kind == "unknown":
        return f"(NOT ({known}))", []
    if focus.kind == "year":
        return (
            f"({known} AND strftime('%Y', m.recorded_at) = ?)",
            [focus.year],
        )
    if focus.kind == "month":
        return (
            f"({known} AND strftime('%Y-%m', m.recorded_at) = ?)",
            [f"{focus.year}-{focus.month}"],
        )
    return (f"({known} AND date(m.recorded_at) = ?)", [focus.token])


def group_timeline_page(
    items: Sequence[Any],
    *,
    href_for: Callable[[str | None], str],
) -> list[TimelineYearBlock]:
    """Group a page that is already in chronological order.

    Consecutive equal days stay together. A day split by pagination still gets
    a heading on each page. Missing and non-calendar dates form one unknown
    group when they are contiguous (timeline queries sort them together).
    """
    years: list[TimelineYearBlock] = []
    for item in items:
        recorded = getattr(item, "recorded_at", None)
        parsed = parse_recording_day(recorded if isinstance(recorded, str) else None)
        if parsed is None:
            year_key = "unknown"
            month_key = "unknown"
            day_key = "unknown"
        else:
            year_key = parsed.year
            month_key = f"{parsed.year}-{parsed.month}"
            day_key = parsed.iso
        if not years or years[-1].key != year_key:
            years.append(
                TimelineYearBlock(
                    key=year_key,
                    known=parsed is not None,
                    year="" if parsed is None else parsed.year,
                    href=href_for("unknown" if parsed is None else year_key),
                )
            )
        year = years[-1]
        if not year.months or year.months[-1].key != month_key:
            year.months.append(
                TimelineMonthBlock(
                    key=month_key,
                    known=parsed is not None,
                    year="" if parsed is None else parsed.year,
                    month_label="" if parsed is None else month_label(parsed.month),
                    href=href_for("unknown" if parsed is None else month_key),
                )
            )
        month = year.months[-1]
        if not month.days or month.days[-1].key != day_key:
            month.days.append(
                TimelineDayBlock(
                    key=day_key,
                    known=parsed is not None,
                    year="" if parsed is None else parsed.year,
                    month="" if parsed is None else parsed.month,
                    day_num="" if parsed is None else str(int(parsed.day)),
                    month_label="" if parsed is None else month_label(parsed.month),
                    href=href_for("unknown" if parsed is None else day_key),
                )
            )
        month.days[-1].items.append(item)
    return years


def _desc(order: str) -> bool:
    return order.lower() != "asc"


def build_timeline_nav(
    day_counts: Sequence[tuple[str | None, int]],
    *,
    active: TimelineFocus | None,
    order: str,
    href_for: Callable[[str | None], str],
) -> TimelineNav:
    """Year / month / day navigator for the filtered library, newest first by default."""
    buckets: dict[str, dict[str, list[tuple[RecordingDay, int]]]] = {}
    unknown = 0
    for raw_day, count in day_counts:
        parsed = parse_recording_day(raw_day) if raw_day else None
        if parsed is None:
            unknown += int(count)
            continue
        buckets.setdefault(parsed.year, {}).setdefault(parsed.month, []).append(
            (parsed, int(count))
        )

    newest_first = _desc(order)
    year_keys = sorted(buckets, reverse=newest_first)
    years: list[TimelineNavYear] = []
    for index, year in enumerate(year_keys):
        months_in = buckets[year]
        month_keys = sorted(months_in, reverse=newest_first)
        year_count = sum(n for days in months_in.values() for _day, n in days)
        year_open = False
        if active is None:
            year_open = index == 0
        elif active.kind != "unknown":
            year_open = active.year == year
        months: list[TimelineNavMonth] = []
        for month in month_keys:
            day_rows = sorted(months_in[month], key=lambda pair: pair[0].iso, reverse=newest_first)
            month_count = sum(n for _day, n in day_rows)
            month_token = f"{year}-{month}"
            month_open = (
                active is not None
                and active.kind in {"month", "day"}
                and active.year == year
                and active.month == month
            )
            days = [
                TimelineNavLink(
                    token=day.iso,
                    label=str(int(day.day)),
                    count=n,
                    href=href_for(day.iso),
                    active=active is not None and active.kind == "day" and active.token == day.iso,
                    month_label=month_label(month),
                )
                for day, n in day_rows
            ]
            months.append(
                TimelineNavMonth(
                    link=TimelineNavLink(
                        token=month_token,
                        label=month_label(month),
                        count=month_count,
                        href=href_for(month_token),
                        active=active is not None
                        and active.kind == "month"
                        and active.token == month_token,
                        month_label=month_label(month),
                    ),
                    open=month_open,
                    days=days,
                )
            )
        years.append(
            TimelineNavYear(
                link=TimelineNavLink(
                    token=year,
                    label=year,
                    count=year_count,
                    href=href_for(year),
                    active=active is not None and active.kind == "year" and active.year == year,
                ),
                open=year_open,
                months=months,
            )
        )

    return TimelineNav(
        all_href=href_for(None),
        all_active=active is None,
        years=years,
        unknown_count=unknown,
        unknown_href=href_for("unknown"),
        unknown_active=active is not None and active.kind == "unknown",
    )
