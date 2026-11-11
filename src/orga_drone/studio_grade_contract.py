"""Transport-neutral grade validation errors and immutable JSON snapshots (#350)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, NoReturn

MAX_BYTES = 4 * 1024 * 1024
MAX_STEPS = 32
MAX_SELECTIONS = 32
MAX_CURVE_POINTS = 4096
MAX_BRUSH_POINTS = 100000
MAX_SAFE_INTEGER = 2**53 - 1
LEGACY_KEYS = (
    "image",
    "color",
    "hsl",
    "color_wheels",
    "detail",
    "saturation_ramp",
    "color_animation",
)


@dataclass
class GradeError(ValueError):
    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} at {self.path}: {self.message}"

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


def fail(path: str, message: str, code: str = "INVALID_GRADE") -> NoReturn:
    raise GradeError(code, path, message)


def object_value(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(path, "Expected an object")
    return value


def array_value(value: Any, path: str, limit: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > limit:
        fail(path, f"Expected an array with at most {limit} entries")
    return value


def integer(value: Any, path: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_SAFE_INTEGER:
        fail(path, f"Expected an integer in [{minimum}, {MAX_SAFE_INTEGER}]")
    return value


def number(value: Any, path: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or not minimum <= value <= maximum:
        fail(path, f"Expected a finite number in [{minimum}, {maximum}]")
    return float(value)


def identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        fail(path, "Expected a nonempty identifier of at most 128 characters")
    return value


def json_tree(value: Any, path: str = "$", depth: int = 0) -> None:
    """Bound recursion and reject non-JSON values, including mapping key coercion."""
    if depth > 64:
        fail(path, "JSON nesting exceeds 64 levels")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            fail(path, "Nonfinite JSON number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            json_tree(item, f"{path}[{index}]", depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                fail(path, "JSON object keys must be strings")
            json_tree(item, f"{path}.{key}", depth + 1)
        return
    fail(path, "Not a JSON value")


def snapshot(value: Any) -> str:
    json_tree(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(key, "Duplicate JSON member")
        result[key] = value
    return result
