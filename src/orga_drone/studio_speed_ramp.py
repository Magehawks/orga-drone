"""Source-anchored speed ramps. The absent ramp preserves legacy speed timing.

Version 1 stores one curve in ``points`` and an optional ``region``. Outside
that region playback is 1×. A ramp with no region keeps the ADR 0034 endpoint
hold so existing projects do not change. Older builds ignore ``region`` and
hold the endpoint speed outside the points.

Version 2 stores up to three non-overlapping ``regions``. Each region has a
stable id, absolute Source bounds, and its own 2–5 point curve. Playback
outside every region is 1×. Version 1 documents still parse and render as
before (ADR 0038).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re

KEY = "speed_ramp"
MIN_SPEED = 0.25
MAX_SPEED = 20.0
MAX_POINTS = 5
MAX_REGIONS = 3
MIN_REGION_S = 0.05
_REGION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_PRESETS: dict[str, tuple[float, ...]] = {
    "slow_fast_slow": (0.5, 4.0, 0.5),
    "fast_slow_fast": (4.0, 0.5, 4.0),
    "acceleration": (0.5, 4.0),
    "deceleration": (4.0, 0.5),
}


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("speed ramp values must be finite numbers")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError("speed ramp values must be finite numbers") from exc
    if not math.isfinite(number):
        raise ValueError("speed ramp values must be finite numbers")
    return number


@dataclass(frozen=True)
class Point:
    source_s: float
    speed: float

    def as_dict(self) -> dict[str, float]:
        return {"source_s": self.source_s, "speed": self.speed}


@dataclass(frozen=True)
class Region:
    """One Source span. Playback is 1× outside it and the curve inside it."""

    start_s: float
    end_s: float

    def as_dict(self) -> dict[str, float]:
        return {"start_s": self.start_s, "end_s": self.end_s}


@dataclass(frozen=True)
class CurveRegion:
    """One bounded curve. Source seconds are absolute file time."""

    id: str
    start_s: float
    end_s: float
    points: tuple[Point, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "points": [point.as_dict() for point in self.points],
        }


@dataclass(frozen=True)
class SpeedRamp:
    points: tuple[Point, ...]
    region: Region | None = None
    regions: tuple[CurveRegion, ...] = ()
    version: int = 1

    def as_dict(self) -> dict[str, object]:
        if self.version == 2:
            return {
                "v": 2,
                "interp": "reciprocal_smoothstep",
                "regions": [region.as_dict() for region in self.regions],
            }
        payload: dict[str, object] = {
            "v": 1,
            "interp": "reciprocal_smoothstep",
            "points": [p.as_dict() for p in self.points],
        }
        if self.region is not None:
            payload["region"] = self.region.as_dict()
        return payload

    def speed_at(self, source_s: float) -> float:
        if self.version == 2:
            for region in self.regions:
                if region.start_s <= source_s <= region.end_s:
                    return _points_speed(region.points, source_s)
            return 1.0
        if self.region is not None and (
            source_s < self.region.start_s or source_s > self.region.end_s
        ):
            return 1.0
        return self._curve_speed_at(source_s)

    def _curve_speed_at(self, source_s: float) -> float:
        return _points_speed(self.points, source_s)

    def time_at(self, source_s: float) -> float:
        """Primitive of 1/speed; subtract primitives to measure a trimmed span."""
        if self.version == 2:
            return _regions_time(self.regions, source_s)
        if self.region is None:
            return self._curve_time_at(source_s)
        start = self.region.start_s
        end = self.region.end_s
        if source_s <= start:
            return source_s
        capped = min(source_s, end)
        interior = self._curve_time_at(capped) - self._curve_time_at(start)
        if source_s <= end:
            return start + interior
        return start + interior + (source_s - end)

    def _curve_time_at(self, source_s: float) -> float:
        return _points_time(self.points, source_s)

    def duration(self, start: float, end: float) -> float:
        return max(0.0, self.time_at(end) - self.time_at(start))

    def source_at_time(self, absolute_story_s: float, lo: float, hi: float) -> float:
        """Invert ``time_at`` inside ``[lo, hi]`` against an absolute primitive."""
        low = float(lo)
        high = float(hi)
        if high < low:
            low, high = high, low
        target = float(absolute_story_s)
        if target <= self.time_at(low):
            return low
        if target >= self.time_at(high):
            return high
        left, right = low, high
        for _ in range(48):
            mid = (left + right) / 2
            if self.time_at(mid) < target:
                left = mid
            else:
                right = mid
        return (left + right) / 2

    def source_at(self, story_s: float, start: float, end: float) -> float:
        """Invert relative Story seconds measured from ``time_at(start)``."""
        return self.source_at_time(self.time_at(start) + max(0.0, float(story_s)), start, end)

    def ffmpeg_time(self, variable: str = "T") -> str:
        """An exact primitive in FFmpeg expression syntax, including endpoint holds."""
        if self.version == 2:
            return _regions_ffmpeg_time(self.regions, variable)
        curve = self._curve_ffmpeg_time(variable)
        if self.region is None:
            return curve
        start = self.region.start_s
        end = self.region.end_s
        curve_start = self._curve_time_at(start)
        interior = self._curve_time_at(end) - curve_start
        return (
            f"if(lte(({variable}),{start:.12g}),({variable}),"
            f"if(lte(({variable}),{end:.12g}),"
            f"{start:.12g}+(({curve})-({curve_start:.12g})),"
            f"{(start + interior):.12g}+(({variable})-{end:.12g})))"
        )

    def _curve_ffmpeg_time(self, variable: str) -> str:
        return _points_ffmpeg_time(self.points, variable)


def _points_speed(points: tuple[Point, ...], source_s: float) -> float:
    if source_s <= points[0].source_s:
        return points[0].speed
    for earlier, later in zip(points, points[1:]):
        if source_s <= later.source_s:
            span = later.source_s - earlier.source_s
            u = (source_s - earlier.source_s) / span
            return 1 / (
                1 / earlier.speed
                + (1 / later.speed - 1 / earlier.speed) * (3 * u * u - 2 * u * u * u)
            )
    return points[-1].speed


def _points_time(points: tuple[Point, ...], source_s: float) -> float:
    total = min(source_s, points[0].source_s) / points[0].speed
    if source_s <= points[0].source_s:
        return total
    for earlier, later in zip(points, points[1:]):
        length = later.source_s - earlier.source_s
        u = min(1.0, (source_s - earlier.source_s) / length)
        total += length * (
            u / earlier.speed
            + (1 / later.speed - 1 / earlier.speed) * (u**3 - 0.5 * u**4)
        )
        if source_s <= later.source_s:
            return total
    return total + (source_s - points[-1].source_s) / points[-1].speed


def _points_ffmpeg_time(points: tuple[Point, ...], variable: str) -> str:
    tail = (
        f"({_points_time(points, points[-1].source_s):.12g}+(({variable})-"
        f"{points[-1].source_s:.12g})/{points[-1].speed:.12g})"
    )
    for earlier, later in reversed(list(zip(points, points[1:]))):
        length = later.source_s - earlier.source_s
        u = f"((({variable})-{earlier.source_s:.12g})/{length:.12g})"
        span = (
            f"({_points_time(points, earlier.source_s):.12g}+{length:.12g}*"
            f"({u}/{earlier.speed:.12g}+({1 / later.speed - 1 / earlier.speed:.12g})*"
            f"({u}^3-0.5*{u}^4)))"
        )
        tail = f"if(lte(({variable}),{later.source_s:.12g}),{span},{tail})"
    return (
        f"if(lte(({variable}),{points[0].source_s:.12g}),"
        f"({variable})/{points[0].speed:.12g},{tail})"
    )


def _regions_time(regions: tuple[CurveRegion, ...], source_s: float) -> float:
    total = 0.0
    previous = 0.0
    for region in regions:
        if source_s <= region.start_s:
            return total + (source_s - previous)
        total += region.start_s - previous
        if source_s <= region.end_s:
            return total + (
                _points_time(region.points, source_s)
                - _points_time(region.points, region.start_s)
            )
        total += (
            _points_time(region.points, region.end_s)
            - _points_time(region.points, region.start_s)
        )
        previous = region.end_s
    return total + (source_s - previous)


def _regions_ffmpeg_time(regions: tuple[CurveRegion, ...], variable: str) -> str:
    last = regions[-1]
    expression = (
        f"({_regions_time(regions, last.end_s):.12g}+(({variable})-{last.end_s:.12g}))"
    )
    previous_ends = (0.0, *[region.end_s for region in regions[:-1]])
    for region, previous_end in zip(reversed(regions), reversed(previous_ends)):
        curve = _points_ffmpeg_time(region.points, variable)
        curve_start = _points_time(region.points, region.start_s)
        accumulated = _regions_time(regions, region.start_s)
        interior = f"{accumulated:.12g}+(({curve})-({curve_start:.12g}))"
        expression = (
            f"if(lte(({variable}),{region.end_s:.12g}),{interior},{expression})"
        )
        if region is regions[0]:
            gap = f"({variable})"
        else:
            gap = (
                f"({_regions_time(regions, previous_end):.12g}+"
                f"(({variable})-{previous_end:.12g}))"
            )
        expression = f"if(lte(({variable}),{region.start_s:.12g}),{gap},{expression})"
    return expression


def edge_source_after_ramp_drag(
    ramp: SpeedRamp,
    *,
    edge: str,
    source_in_s: float,
    source_out_s: float,
    delta_story_s: float,
    repeats: int = 1,
    media_duration_s: float,
    min_segment_s: float = 0.05,
) -> tuple[float, float]:
    """Move one trimmed edge by Story seconds along a source-anchored ramp."""
    if edge not in {"in", "out"}:
        raise ValueError("edge must be in or out")
    catalog = float(media_duration_s)
    floor = float(min_segment_s)
    if catalog <= floor:
        return 0.0, max(0.0, catalog)
    count = max(1, min(8, int(repeats)))
    start = float(source_in_s)
    end = float(source_out_s)
    source = start if edge == "in" else end
    mapped = ramp.source_at_time(
        ramp.time_at(source) + float(delta_story_s) / count,
        0.0,
        catalog,
    )
    if edge == "in":
        start = mapped
    else:
        end = mapped
    start = min(max(0.0, start), catalog)
    end = min(max(0.0, end), catalog)
    if end - start < floor:
        if edge == "in":
            start = end - floor
        else:
            end = start + floor
        start = min(max(0.0, start), catalog)
        end = min(max(0.0, end), catalog)
        if end - start < floor:
            if edge == "in":
                end = min(catalog, start + floor)
            else:
                start = max(0.0, end - floor)
    start = round(start, 2)
    end = round(end, 2)
    start = min(max(0.0, start), catalog)
    end = min(max(0.0, end), catalog)
    if end - start < floor:
        if edge == "in":
            start = max(0.0, round(end - floor, 2))
        else:
            end = min(catalog, round(start + floor, 2))
    return start, end


def parse_ramp(value: object, *, media_duration_s: float | None = None) -> SpeedRamp:
    if (
        not isinstance(value, dict)
        or type(value.get("v")) is not int
        or value.get("interp") != "reciprocal_smoothstep"
    ):
        raise ValueError("unsupported speed ramp")
    version = value.get("v")
    if version == 2:
        return _parse_regions(value, media_duration_s)
    if version != 1 or "regions" in value:
        raise ValueError("unsupported speed ramp")
    raw = value.get("points")
    if not isinstance(raw, list) or not 2 <= len(raw) <= MAX_POINTS:
        raise ValueError("speed ramp needs 2 to 5 points")
    points: list[Point] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("invalid speed ramp point")
        source, speed = (
            _finite_number(item.get("source_s")),
            _finite_number(item.get("speed")),
        )
        if source < 0 or (
            media_duration_s is not None and source > media_duration_s + 1e-6
        ):
            raise ValueError("speed ramp points must stay inside the source")
        if not MIN_SPEED <= speed <= MAX_SPEED:
            raise ValueError(f"speed ramp must stay between {MIN_SPEED:g} and {MAX_SPEED:g}")
        if points and source - points[-1].source_s < 0.05 - 1e-9:
            raise ValueError(
                "speed ramp points must be ordered and at least 0.05 seconds apart"
            )
        points.append(Point(source, speed))
    return SpeedRamp(tuple(points), _parse_region(value, points, media_duration_s))


def ramp_from_settings(raw: str | None) -> SpeedRamp | None:
    try:
        data = json.loads(raw or "{}")
        return parse_ramp(data[KEY]) if isinstance(data, dict) and KEY in data else None
    except (ValueError, KeyError, TypeError):
        return None


def ramp_client_state(raw: str | None) -> dict[str, object] | None:
    ramp = ramp_from_settings(raw)
    return ramp.as_dict() if ramp else None


def _parse_region(
    value: dict[str, object],
    points: list[Point],
    media_duration_s: float | None,
) -> Region | None:
    if "region" not in value or value.get("region") is None:
        return None
    raw = value.get("region")
    if not isinstance(raw, dict):
        raise ValueError("speed ramp region must be an object")
    start, end = _finite_number(raw.get("start_s")), _finite_number(raw.get("end_s"))
    if end - start < 0.05 - 1e-9:
        raise ValueError("speed ramp region must be at least 0.05 seconds")
    if start < -1e-9 or (media_duration_s is not None and end > media_duration_s + 1e-6):
        raise ValueError("speed ramp region must stay inside the source")
    for point in points:
        if point.source_s < start - 1e-6 or point.source_s > end + 1e-6:
            raise ValueError("speed ramp points must stay inside the region")
    return Region(start, end)


def _parse_regions(value: dict[str, object], media_duration_s: float | None) -> SpeedRamp:
    if "points" in value or "region" in value:
        raise ValueError("unsupported speed ramp")
    raw = value.get("regions")
    if not isinstance(raw, list) or not raw:
        raise ValueError("speed ramp needs at least one region")
    if len(raw) > MAX_REGIONS:
        raise ValueError("a clip can have at most 3 speed ramp regions")
    parsed: list[CurveRegion] = []
    seen: set[str] = set()
    for item in raw:
        parsed.append(_parse_curve_region(item, media_duration_s, seen))
    parsed.sort(key=lambda region: (region.start_s, region.id))
    for earlier, later in zip(parsed, parsed[1:]):
        if later.start_s < earlier.end_s - 1e-9:
            raise ValueError("speed ramp regions must not overlap")
    return SpeedRamp((), None, tuple(parsed), 2)


def _parse_curve_region(
    value: object,
    media_duration_s: float | None,
    seen: set[str],
) -> CurveRegion:
    if not isinstance(value, dict):
        raise ValueError("speed ramp region must be an object")
    region_id = value.get("id")
    if not isinstance(region_id, str) or _REGION_ID.fullmatch(region_id) is None:
        raise ValueError("invalid speed ramp region id")
    if region_id in seen:
        raise ValueError("speed ramp region ids must be unique")
    seen.add(region_id)
    start, end = _finite_number(value.get("start_s")), _finite_number(value.get("end_s"))
    if end - start < MIN_REGION_S - 1e-9:
        raise ValueError("speed ramp region must be at least 0.05 seconds")
    if start < -1e-9 or (media_duration_s is not None and end > media_duration_s + 1e-6):
        raise ValueError("speed ramp region must stay inside the source")
    points = _parse_points(value.get("points"), media_duration_s)
    for point in points:
        if point.source_s < start - 1e-6 or point.source_s > end + 1e-6:
            raise ValueError("speed ramp points must stay inside the region")
    return CurveRegion(region_id, start, end, tuple(points))


def _parse_points(raw: object, media_duration_s: float | None) -> list[Point]:
    if not isinstance(raw, list) or not 2 <= len(raw) <= MAX_POINTS:
        raise ValueError("speed ramp needs 2 to 5 points")
    points: list[Point] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("invalid speed ramp point")
        source, speed = (
            _finite_number(item.get("source_s")),
            _finite_number(item.get("speed")),
        )
        if source < 0 or (
            media_duration_s is not None and source > media_duration_s + 1e-6
        ):
            raise ValueError("speed ramp points must stay inside the source")
        if not MIN_SPEED <= speed <= MAX_SPEED:
            raise ValueError(f"speed ramp must stay between {MIN_SPEED:g} and {MAX_SPEED:g}")
        if points and source - points[-1].source_s < 0.05 - 1e-9:
            raise ValueError(
                "speed ramp points must be ordered and at least 0.05 seconds apart"
            )
        points.append(Point(source, speed))
    return points


def _new_region_id(taken: set[str]) -> str:
    for index in range(1, MAX_REGIONS + 1):
        candidate = f"r{index}"
        if candidate not in taken:
            return candidate
    raise ValueError("a clip can have at most 3 speed ramp regions")


def _bounded_curves(ramp: SpeedRamp) -> list[CurveRegion]:
    if ramp.version == 2:
        return list(ramp.regions)
    if ramp.region is None:
        raise ValueError("speed ramp region is not bounded")
    return [
        CurveRegion(
            _new_region_id(set()),
            ramp.region.start_s,
            ramp.region.end_s,
            ramp.points,
        )
    ]


def _region_index(ramp: SpeedRamp, region_id: str | None) -> int:
    if ramp.version != 2 or not ramp.regions:
        raise ValueError("unknown speed ramp region")
    if region_id is None:
        if len(ramp.regions) == 1:
            return 0
        raise ValueError("speed ramp region id is required")
    for index, region in enumerate(ramp.regions):
        if region.id == region_id:
            return index
    raise ValueError("unknown speed ramp region")


def _neighbor_limits(
    regions: tuple[CurveRegion, ...],
    index: int,
    play_start: float,
    play_end: float,
) -> tuple[float, float]:
    lo = float(play_start) if index == 0 else max(float(play_start), regions[index - 1].end_s)
    hi = (
        float(play_end)
        if index == len(regions) - 1
        else min(float(play_end), regions[index + 1].start_s)
    )
    if hi - lo < MIN_REGION_S - 1e-9:
        raise ValueError("speed ramp region does not fit")
    return lo, hi


def _free_gaps(
    regions: list[CurveRegion],
    play_start: float,
    play_end: float,
) -> list[tuple[float, float]]:
    gaps: list[tuple[float, float]] = []
    cursor = play_start
    for region in sorted(regions, key=lambda item: item.start_s):
        right = min(region.start_s, play_end)
        if right - cursor > 1e-9:
            gaps.append((cursor, right))
        cursor = max(cursor, region.end_s)
        if cursor >= play_end - 1e-9:
            return gaps
    if play_end - cursor > 1e-9:
        gaps.append((cursor, play_end))
    return gaps


def _placement_gap(
    regions: list[CurveRegion],
    play_start: float,
    play_end: float,
    need: float,
    span: float,
) -> tuple[float, float] | None:
    """Prefer the open tail after the last region, then the widest usable gap.

    A short hole before the first region must not trap the new region there:
    a later region cannot be dragged through an earlier one.
    """
    if (
        not math.isfinite(play_start)
        or not math.isfinite(play_end)
        or play_end - play_start < need - 1e-9
    ):
        return None
    gaps = [
        gap
        for gap in _free_gaps(regions, play_start, play_end)
        if gap[1] - gap[0] >= need - 1e-9
    ]
    if not gaps:
        return None
    last_end = max((region.end_s for region in regions), default=play_start)
    for gap in gaps:
        if abs(gap[0] - last_end) <= 1e-6 and gap[1] - gap[0] >= span - 1e-9:
            return gap
    wide = [gap for gap in gaps if gap[1] - gap[0] >= span - 1e-9]
    pool = wide or gaps
    return max(pool, key=lambda gap: (gap[1] - gap[0], -gap[0]))


def _round_up(value: float) -> float:
    return math.ceil(value * 100 - 1e-9) / 100


def _round_down(value: float) -> float:
    return math.floor(value * 100 + 1e-9) / 100


def _preset_points(start: float, end: float, speeds: tuple[float, ...]) -> tuple[Point, ...]:
    span = end - start
    count = len(speeds)
    placed = [
        Point(
            start if index == 0 else end if index == count - 1 else round(
                start + span * index / (count - 1), 2
            ),
            speed,
        )
        for index, speed in enumerate(speeds)
    ]
    for index in range(1, len(placed)):
        floor_s = round(placed[index - 1].source_s + MIN_REGION_S, 2)
        if placed[index].source_s < floor_s:
            placed[index] = Point(floor_s, placed[index].speed)
    if placed[-1].source_s > end:
        placed[-1] = Point(end, placed[-1].speed)
        for index in range(len(placed) - 2, -1, -1):
            ceiling = round(placed[index + 1].source_s - MIN_REGION_S, 2)
            if placed[index].source_s > ceiling:
                placed[index] = Point(ceiling, placed[index].speed)
        placed[0] = Point(start, placed[0].speed)
    return tuple(placed)


def region_bounds(ramp: SpeedRamp, region_id: str | None = None) -> tuple[float, float]:
    if ramp.version == 2:
        region = ramp.regions[_region_index(ramp, region_id)]
        return region.start_s, region.end_s
    if ramp.region is not None:
        return ramp.region.start_s, ramp.region.end_s
    return ramp.points[0].source_s, ramp.points[-1].source_s


def place_ramp_region(
    ramp: SpeedRamp,
    new_start: float,
    new_end: float,
    *,
    play_start: float,
    play_end: float,
    min_gap: float = 0.05,
    region_id: str | None = None,
) -> SpeedRamp:
    """Scale one region's curve into new Source bounds without changing speeds."""
    if ramp.version == 2:
        return _place_curve_region(
            ramp,
            new_start,
            new_end,
            play_start=play_start,
            play_end=play_end,
            min_gap=min_gap,
            region_id=region_id,
        )
    play_start = float(play_start)
    play_end = float(play_end)
    if not math.isfinite(play_start) or not math.isfinite(play_end):
        raise ValueError("speed ramp region does not fit")
    old_start, old_end = region_bounds(ramp)
    old_span = old_end - old_start
    if old_span <= 0:
        raise ValueError("speed ramp region is invalid")
    start = float(new_start)
    end = float(new_end)
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError("speed ramp region is invalid")
    if end < start:
        start, end = end, start
    start = min(max(play_start, start), play_end)
    end = min(max(play_start, end), play_end)
    floor = max(min_gap, (len(ramp.points) - 1) * min_gap)
    if end - start < floor:
        if end >= play_end - 1e-9:
            start = max(play_start, end - floor)
        else:
            end = min(play_end, start + floor)
    if end - start < floor - 1e-9:
        raise ValueError("speed ramp region does not fit")
    start = round(start, 2)
    end = round(end, 2)
    start = min(max(play_start, start), play_end)
    end = min(max(play_start, end), play_end)
    if end - start < floor - 1e-9:
        raise ValueError("speed ramp region does not fit")
    placed: list[Point] = []
    for point in ramp.points:
        fraction = (point.source_s - old_start) / old_span
        placed.append(Point(round(start + fraction * (end - start), 2), point.speed))
    placed[0] = Point(start, placed[0].speed)
    placed[-1] = Point(end, placed[-1].speed)
    for index in range(1, len(placed)):
        floor_s = round(placed[index - 1].source_s + min_gap, 2)
        if placed[index].source_s < floor_s:
            placed[index] = Point(floor_s, placed[index].speed)
    if placed[-1].source_s > end:
        placed[-1] = Point(end, placed[-1].speed)
        for index in range(len(placed) - 2, -1, -1):
            ceiling = round(placed[index + 1].source_s - min_gap, 2)
            if placed[index].source_s > ceiling:
                placed[index] = Point(ceiling, placed[index].speed)
        placed[0] = Point(start, placed[0].speed)
    return parse_ramp(SpeedRamp(tuple(placed), Region(start, end)).as_dict())


def ramp_after_region_drag(
    ramp: SpeedRamp,
    *,
    mode: str,
    delta_story_s: float,
    play_start: float,
    play_end: float,
    region_id: str | None = None,
) -> SpeedRamp:
    """Move or resize one region so the dragged edge follows Story time."""
    if ramp.version == 2:
        return _drag_curve_region(
            ramp,
            mode=mode,
            delta_story_s=delta_story_s,
            play_start=play_start,
            play_end=play_end,
            region_id=region_id,
        )
    if mode not in {"move", "start", "end"}:
        raise ValueError("mode must be move, start, or end")
    start, end = region_bounds(ramp)
    span = end - start
    if span <= 0:
        raise ValueError("speed ramp region is invalid")
    origin_left = ramp.time_at(start) - ramp.time_at(play_start)
    story = ramp.duration(start, end)
    rate = story / span if span else 1.0
    min_span = max(0.05, (len(ramp.points) - 1) * 0.05)
    play_span = float(play_end) - float(play_start)
    if mode == "move":
        start = float(play_start) + origin_left + float(delta_story_s)
        end = start + span
        if span >= play_span:
            start, end = float(play_start), float(play_end)
        else:
            if start < play_start:
                start, end = float(play_start), float(play_start) + span
            if end > play_end:
                end, start = float(play_end), float(play_end) - span
    elif mode == "start":
        start = float(play_start) + origin_left + float(delta_story_s)
        end = region_bounds(ramp)[1]
        if start < play_start:
            start = float(play_start)
        if end - start < min_span:
            start = end - min_span
        if start < play_start:
            raise ValueError("speed ramp region does not fit")
    else:
        start = region_bounds(ramp)[0]
        end = start + span + float(delta_story_s) / max(rate, 1e-6)
        if end > play_end:
            end = float(play_end)
        if end - start < min_span:
            end = start + min_span
        if end > play_end:
            raise ValueError("speed ramp region does not fit")
    return place_ramp_region(
        ramp, start, end, play_start=play_start, play_end=play_end
    )


def _place_curve_region(
    ramp: SpeedRamp,
    new_start: float,
    new_end: float,
    *,
    play_start: float,
    play_end: float,
    min_gap: float,
    region_id: str | None,
) -> SpeedRamp:
    index = _region_index(ramp, region_id)
    region = ramp.regions[index]
    lo, hi = _neighbor_limits(ramp.regions, index, play_start, play_end)
    placed = place_ramp_region(
        SpeedRamp(region.points, Region(region.start_s, region.end_s)),
        new_start,
        new_end,
        play_start=lo,
        play_end=hi,
        min_gap=min_gap,
    )
    if placed.region is None:
        raise ValueError("speed ramp region does not fit")
    updated = CurveRegion(
        region.id, placed.region.start_s, placed.region.end_s, placed.points
    )
    regions = list(ramp.regions)
    regions[index] = updated
    return parse_ramp(SpeedRamp((), None, tuple(regions), 2).as_dict())


def _drag_curve_region(
    ramp: SpeedRamp,
    *,
    mode: str,
    delta_story_s: float,
    play_start: float,
    play_end: float,
    region_id: str | None,
) -> SpeedRamp:
    if mode not in {"move", "start", "end"}:
        raise ValueError("mode must be move, start, or end")
    index = _region_index(ramp, region_id)
    region = ramp.regions[index]
    span = region.end_s - region.start_s
    if span <= 0:
        raise ValueError("speed ramp region is invalid")
    lo, hi = _neighbor_limits(ramp.regions, index, play_start, play_end)
    story = _regions_time(ramp.regions, region.end_s) - _regions_time(
        ramp.regions, region.start_s
    )
    rate = story / span if span else 1.0
    min_span = max(MIN_REGION_S, (len(region.points) - 1) * MIN_REGION_S)
    delta = float(delta_story_s)
    start = region.start_s
    end = region.end_s
    if mode == "move":
        start = region.start_s + delta
        end = start + span
        if span >= (hi - lo) - 1e-9:
            start, end = lo, hi
        else:
            if start < lo:
                start, end = lo, lo + span
            if end > hi:
                end, start = hi, hi - span
    elif mode == "start":
        start = region.start_s + delta
        end = region.end_s
        if start < lo:
            start = lo
        if end - start < min_span:
            start = end - min_span
        if start < lo:
            raise ValueError("speed ramp region does not fit")
    else:
        start = region.start_s
        end = start + span + delta / max(rate, 1e-6)
        if end > hi:
            end = hi
        if end - start < min_span:
            end = start + min_span
        if end > hi:
            raise ValueError("speed ramp region does not fit")
    return _place_curve_region(
        ramp,
        start,
        end,
        play_start=play_start,
        play_end=play_end,
        min_gap=MIN_REGION_S,
        region_id=region.id,
    )


def add_ramp_region(
    ramp: SpeedRamp,
    *,
    play_start: float,
    play_end: float,
    preset: str = "slow_fast_slow",
    region_id: str | None = None,
    span_s: float = 4.0,
) -> SpeedRamp:
    """Append one bounded region after the last region when that tail can hold it."""
    speeds = _PRESETS.get(preset)
    if speeds is None:
        raise ValueError("unknown speed ramp preset")
    existing = _bounded_curves(ramp)
    if len(existing) >= MAX_REGIONS:
        raise ValueError("a clip can have at most 3 speed ramp regions")
    need = max(0.1, (len(speeds) - 1) * MIN_REGION_S)
    requested = max(need, float(span_s))
    gap = _placement_gap(
        existing, float(play_start), float(play_end), need, requested
    )
    if gap is None:
        raise ValueError("speed ramp region does not fit")
    length = min(float(span_s), gap[1] - gap[0])
    start = _round_up(gap[0])
    end = _round_down(min(gap[1], start + length))
    if end - start < need - 1e-9:
        end = _round_down(gap[1])
        start = _round_up(max(gap[0], end - length))
    if end - start < need - 1e-9 or start < gap[0] - 1e-9 or end > gap[1] + 1e-9:
        raise ValueError("speed ramp region does not fit")
    taken = {region.id for region in existing}
    new_id = region_id if region_id is not None else _new_region_id(taken)
    if new_id in taken or _REGION_ID.fullmatch(new_id) is None:
        raise ValueError("invalid speed ramp region id")
    existing.append(CurveRegion(new_id, start, end, _preset_points(start, end, speeds)))
    existing.sort(key=lambda region: (region.start_s, region.id))
    return parse_ramp(SpeedRamp((), None, tuple(existing), 2).as_dict())


def remove_ramp_region(ramp: SpeedRamp, region_id: str) -> SpeedRamp | None:
    """Drop one region. Other regions keep their ids, bounds, and points."""
    if ramp.version != 2:
        if ramp.region is None or region_id != "":
            raise ValueError("unknown speed ramp region")
        return None
    kept = [region for region in ramp.regions if region.id != region_id]
    if len(kept) == len(ramp.regions):
        raise ValueError("unknown speed ramp region")
    if not kept:
        return None
    return SpeedRamp((), None, tuple(kept), 2)
