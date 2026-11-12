"""Source-anchored speed ramps. The absent ramp preserves legacy speed timing.

An optional ``region`` keeps one Source span where the curve applies. Outside
that span playback is 1×. A ramp with no region keeps the ADR 0034 endpoint
hold so existing projects do not change. Older builds ignore ``region`` and
hold the endpoint speed outside the points.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math

KEY = "speed_ramp"
MIN_SPEED = 0.25
MAX_SPEED = 20.0
MAX_POINTS = 5


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
class SpeedRamp:
    points: tuple[Point, ...]
    region: Region | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "v": 1,
            "interp": "reciprocal_smoothstep",
            "points": [p.as_dict() for p in self.points],
        }
        if self.region is not None:
            payload["region"] = self.region.as_dict()
        return payload

    def speed_at(self, source_s: float) -> float:
        if self.region is not None and (
            source_s < self.region.start_s or source_s > self.region.end_s
        ):
            return 1.0
        return self._curve_speed_at(source_s)

    def _curve_speed_at(self, source_s: float) -> float:
        p = self.points
        if source_s <= p[0].source_s:
            return p[0].speed
        for a, b in zip(p, p[1:]):
            if source_s <= b.source_s:
                u = (source_s - a.source_s) / (b.source_s - a.source_s)
                return 1 / (
                    1 / a.speed
                    + (1 / b.speed - 1 / a.speed) * (3 * u * u - 2 * u * u * u)
                )
        return p[-1].speed

    def time_at(self, source_s: float) -> float:
        """Primitive of 1/speed; subtract primitives to measure a trimmed span."""
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
        p = self.points
        total = min(source_s, p[0].source_s) / p[0].speed
        if source_s <= p[0].source_s:
            return total
        for a, b in zip(p, p[1:]):
            length = b.source_s - a.source_s
            u = min(1.0, (source_s - a.source_s) / length)
            total += length * (
                u / a.speed + (1 / b.speed - 1 / a.speed) * (u**3 - 0.5 * u**4)
            )
            if source_s <= b.source_s:
                return total
        return total + (source_s - p[-1].source_s) / p[-1].speed

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
        p = self.points
        tail = (
            f"({self._curve_time_at(p[-1].source_s):.12g}+(({variable})-"
            f"{p[-1].source_s:.12g})/{p[-1].speed:.12g})"
        )
        for a, b in reversed(list(zip(p, p[1:]))):
            length = b.source_s - a.source_s
            u = f"((({variable})-{a.source_s:.12g})/{length:.12g})"
            span = (
                f"({self._curve_time_at(a.source_s):.12g}+{length:.12g}*"
                f"({u}/{a.speed:.12g}+({1 / b.speed - 1 / a.speed:.12g})*({u}^3-0.5*{u}^4)))"
            )
            tail = f"if(lte(({variable}),{b.source_s:.12g}),{span},{tail})"
        return (
            f"if(lte(({variable}),{p[0].source_s:.12g}),"
            f"({variable})/{p[0].speed:.12g},{tail})"
        )


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
        or value.get("v") != 1
        or value.get("interp") != "reciprocal_smoothstep"
    ):
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


def region_bounds(ramp: SpeedRamp) -> tuple[float, float]:
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
) -> SpeedRamp:
    """Scale the curve into one Source region without changing its speeds."""
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
) -> SpeedRamp:
    """Move or resize the one region so the dragged edge follows Story time."""
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
