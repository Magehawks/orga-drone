"""Source-anchored speed ramps. The absent ramp preserves legacy speed timing."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math

KEY = "speed_ramp"
MIN_SPEED = 0.25
MAX_SPEED = 4.0
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
class SpeedRamp:
    points: tuple[Point, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "v": 1,
            "interp": "reciprocal_smoothstep",
            "points": [p.as_dict() for p in self.points],
        }

    def speed_at(self, source_s: float) -> float:
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

    def source_at(self, story_s: float, start: float, end: float) -> float:
        if story_s <= 0:
            return start
        if story_s >= self.duration(start, end):
            return end
        target = self.time_at(start) + max(0.0, story_s)
        lo, hi = start, end
        for _ in range(48):
            mid = (lo + hi) / 2
            if self.time_at(mid) < target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def ffmpeg_time(self, variable: str = "T") -> str:
        """An exact primitive in FFmpeg expression syntax, including endpoint holds."""
        p = self.points
        tail = f"({self.time_at(p[-1].source_s):.12g}+(({variable})-{p[-1].source_s:.12g})/{p[-1].speed:.12g})"
        for a, b in reversed(list(zip(p, p[1:]))):
            length = b.source_s - a.source_s
            u = f"((({variable})-{a.source_s:.12g})/{length:.12g})"
            span = (
                f"({self.time_at(a.source_s):.12g}+{length:.12g}*"
                f"({u}/{a.speed:.12g}+({1 / b.speed - 1 / a.speed:.12g})*({u}^3-0.5*{u}^4)))"
            )
            tail = f"if(lte(({variable}),{b.source_s:.12g}),{span},{tail})"
        return f"if(lte(({variable}),{p[0].source_s:.12g}),({variable})/{p[0].speed:.12g},{tail})"


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
            raise ValueError("speed ramp must stay between 0.25 and 4")
        if points and source - points[-1].source_s < 0.05 - 1e-9:
            raise ValueError(
                "speed ramp points must be ordered and at least 0.05 seconds apart"
            )
        points.append(Point(source, speed))
    return SpeedRamp(tuple(points))


def ramp_from_settings(raw: str | None) -> SpeedRamp | None:
    try:
        data = json.loads(raw or "{}")
        return parse_ramp(data[KEY]) if isinstance(data, dict) and KEY in data else None
    except (ValueError, KeyError, TypeError):
        return None


def ramp_client_state(raw: str | None) -> dict[str, object] | None:
    ramp = ramp_from_settings(raw)
    return ramp.as_dict() if ramp else None
