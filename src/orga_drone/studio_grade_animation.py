"""Canonical grade animation clocks (#358).

Validates and evaluates ``grade.animation`` against registered operation
descriptors. Does not own playback clocks: callers supply ``RenderContext``
with source-local / Story-local times from existing timeline owners.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Mapping

from orga_drone.studio_grade_contract import (
    MAX_STEPS,
    array_value,
    fail,
    identifier,
    integer,
    number,
    object_value,
)

MAX_ANIMATION_KEYS = 8
MIN_KEY_GAP = Fraction(1, 100)  # 10 ms floor; matches legacy 0.1s intent at store precision
CLOCKS = ("source-local", "story-local")
INTERPOLATIONS = ("linear",)
OUTSIDE_POLICIES = ("hold", "base")

# Scalar managed targets. Complex params (gains, curves, tone objects) reject.
ANIMATABLE_PARAMETERS: dict[str, dict[str, dict[str, Any]]] = {
    "primaries-v1": {
        "exposure": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": -10.0,
            "max": 10.0,
        },
        "kelvin": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": 2000.0,
            "max": 15000.0,
        },
        "tint": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": -100.0,
            "max": 100.0,
        },
        "contrast": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": 0.0,
            "max": 4.0,
        },
        "pivot": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": 0.0,
            "max": 1.0,
        },
        "blacks": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": -100.0,
            "max": 100.0,
        },
        "shadows": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": -100.0,
            "max": 100.0,
        },
        "highlights": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": -100.0,
            "max": 100.0,
        },
        "whites": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": -100.0,
            "max": 100.0,
        },
        "saturation": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": 0.0,
            "max": 4.0,
        },
    },
    "creative-lut-v1": {
        "strength": {
            "interpolation": "linear",
            "outside": OUTSIDE_POLICIES,
            "min": 0.0,
            "max": 1.0,
        },
    },
}


def animation_policy(op_type: str, parameter: str) -> dict[str, Any] | None:
    """Return the advertised policy for a supported (op, parameter), else None."""
    return ANIMATABLE_PARAMETERS.get(op_type, {}).get(parameter)


def _rational(value: Any, path: str) -> Fraction:
    if isinstance(value, list) and len(value) == 2:
        num = integer(value[0], path + ".numerator")
        den = integer(value[1], path + ".denominator", 1)
        if den == 0:
            fail(path, "Denominator must be positive")
        result = Fraction(num, den)
        if result < 0:
            fail(path, "Expected a nonnegative rational time")
        return result
    if type(value) in (int, float) and float(value) == value and value >= 0:
        # Accept JSON numbers for authoring convenience; store as exact Fraction.
        return Fraction(value).limit_denominator(1_000_000)
    fail(path, "Expected [numerator, denominator] or a nonnegative number")


def validate_animation_entry(
    anim: Mapping[str, Any],
    path: str,
    *,
    step_lookup: Mapping[str, Mapping[str, Any]],
) -> None:
    """Validate one canonical animation entry. Rejects unsupported targets."""
    object_value(dict(anim), path)
    step_id = identifier(anim.get("step_id"), path + ".step_id")
    step = step_lookup.get(step_id)
    if step is None:
        fail(path + ".step_id", "Dangling step reference")
    clock = anim.get("clock")
    if clock not in CLOCKS:
        fail(path + ".clock", "Explicit animation clock required")
    parameter = identifier(anim.get("parameter"), path + ".parameter")
    op_type = str(step.get("type") or "")
    if op_type == "legacy-stack-v1":
        fail(
            path,
            "Canonical animation cannot target legacy-stack-v1; use color_animation",
            "UNSUPPORTED_GRADE",
        )
    if step.get("selection_id") is not None:
        fail(
            path,
            "Spatial steps cannot be animated; reject rather than flatten",
            "UNSUPPORTED_GRADE",
        )
    policy = animation_policy(op_type, parameter)
    if policy is None:
        fail(
            path + ".parameter",
            f"Parameter {parameter!r} on {op_type} is not animatable",
            "UNSUPPORTED_GRADE",
        )
    interpolation = anim.get("interpolation", "linear")
    if interpolation not in INTERPOLATIONS or interpolation != policy["interpolation"]:
        fail(
            path + ".interpolation",
            "Only linear interpolation is supported",
            "UNSUPPORTED_GRADE",
        )
    outside = anim.get("outside", "hold")
    if outside not in policy["outside"]:
        fail(
            path + ".outside",
            "outside must be hold or base",
            "UNSUPPORTED_GRADE",
        )
    keys = array_value(anim.get("keys"), path + ".keys", MAX_ANIMATION_KEYS)
    if len(keys) < 2:
        fail(path + ".keys", "At least two keys are required")
    previous: Fraction | None = None
    lo = float(policy["min"])
    hi = float(policy["max"])
    for index, key in enumerate(keys):
        key_path = f"{path}.keys[{index}]"
        entry = object_value(key, key_path)
        if set(entry) - {"t", "value"}:
            fail(key_path, "Expected t and value only")
        instant = _rational(entry.get("t"), key_path + ".t")
        number(entry.get("value"), key_path + ".value", lo, hi)
        if previous is not None and instant - previous < MIN_KEY_GAP:
            fail(key_path + ".t", "Keys must increase by at least 0.01s")
        previous = instant


def validate_grade_animations(
    animations: list[Any],
    steps: list[Any],
    *,
    path_prefix: str = "grade.animation",
) -> None:
    """Validate the full animation array against steps."""
    step_lookup = {
        identifier(step.get("id"), f"grade.steps[{index}].id"): step
        for index, step in enumerate(steps)
        if isinstance(step, Mapping)
    }
    seen_targets: set[tuple[str, str]] = set()
    for index, anim in enumerate(animations):
        path = f"{path_prefix}[{index}]"
        if not isinstance(anim, Mapping):
            fail(path, "Expected an object")
        validate_animation_entry(anim, path, step_lookup=step_lookup)
        target = (
            identifier(anim.get("step_id"), path + ".step_id"),
            identifier(anim.get("parameter"), path + ".parameter"),
        )
        if target in seen_targets:
            fail(path, "Duplicate animation target for the same step parameter")
        seen_targets.add(target)
    if len(animations) > MAX_STEPS:
        fail(path_prefix, f"Expected an array with at most {MAX_STEPS} entries")


def clock_time(context: Mapping[str, Any] | Any, clock: str) -> Fraction:
    """Select source-local or Story-local time from a RenderContext or dict."""
    if clock == "source-local":
        value = getattr(context, "source_local", None)
        if value is None and isinstance(context, Mapping):
            raw = context.get("source_local")
            if isinstance(raw, list) and len(raw) == 2:
                return Fraction(int(raw[0]), int(raw[1]))
            if isinstance(raw, (int, float, Fraction)):
                return Fraction(raw)
        if isinstance(value, Fraction):
            return value
        fail("context.source_local", "Missing source-local clock")
    if clock == "story-local":
        value = getattr(context, "story_time", None)
        if value is None and isinstance(context, Mapping):
            raw = context.get("story_time")
            if isinstance(raw, list) and len(raw) == 2:
                return Fraction(int(raw[0]), int(raw[1]))
            if isinstance(raw, (int, float, Fraction)):
                return Fraction(raw)
        if isinstance(value, Fraction):
            return value
        fail("context.story_time", "Missing story-local clock")
    fail("clock", "Unknown animation clock", "UNSUPPORTED_GRADE")


def _lerp(a: float, b: float, u: Fraction) -> float:
    return float(a) + (float(b) - float(a)) * float(u)


def sample_animation_value(
    anim: Mapping[str, Any],
    instant: Fraction,
    *,
    base: float,
) -> float:
    """Deterministic linear sample with explicit outside-range policy."""
    keys = list(anim.get("keys") or [])
    times = [_rational(key.get("t"), "keys.t") for key in keys]
    values = [float(key.get("value")) for key in keys]
    outside = anim.get("outside", "hold")
    if instant < times[0]:
        return values[0] if outside == "hold" else float(base)
    if instant > times[-1]:
        return values[-1] if outside == "hold" else float(base)
    for index in range(len(times) - 1):
        left, right = times[index], times[index + 1]
        if left <= instant <= right:
            if right == left:
                return values[index]
            u = (instant - left) / (right - left)
            return _lerp(values[index], values[index + 1], u)
    return values[-1]


def evaluated_overrides(
    grade: Mapping[str, Any],
    context: Mapping[str, Any] | Any,
) -> dict[str, dict[str, float]]:
    """Map step_id → {parameter: value} for the supplied clock context."""
    animations = grade.get("animation") or []
    steps = {
        str(step.get("id")): step
        for step in (grade.get("steps") or [])
        if isinstance(step, Mapping)
    }
    result: dict[str, dict[str, float]] = {}
    for anim in animations:
        if not isinstance(anim, Mapping):
            continue
        step_id = str(anim.get("step_id"))
        step = steps.get(step_id)
        if step is None or not step.get("enabled", True):
            continue
        parameter = str(anim.get("parameter"))
        raw_params = step.get("params")
        params: Mapping[str, Any] = (
            raw_params if isinstance(raw_params, Mapping) else {}
        )
        base = params.get(parameter)
        if type(base) is int or type(base) is float:
            base_value = float(base)
        else:
            policy = animation_policy(str(step.get("type")), parameter) or {}
            # Neutral defaults for missing scalars match managed applicator defaults.
            defaults = {
                "exposure": 0.0,
                "kelvin": 6500.0,
                "tint": 0.0,
                "contrast": 1.0,
                "pivot": 0.18,
                "blacks": 0.0,
                "shadows": 0.0,
                "highlights": 0.0,
                "whites": 0.0,
                "saturation": 1.0,
                "strength": 1.0,
            }
            fallback = defaults.get(parameter, policy.get("min", 0.0))
            base_value = float(fallback if fallback is not None else 0.0)
        instant = clock_time(context, str(anim.get("clock")))
        value = sample_animation_value(anim, instant, base=base_value)
        result.setdefault(step_id, {})[parameter] = value
    return result


def materialize_grade_at(
    grade: Mapping[str, Any],
    context: Mapping[str, Any] | Any,
) -> dict[str, Any]:
    """Return a detached grade document with animated scalars resolved.

    Disabled steps stay untouched. Animation array is preserved for identity,
    but params already reflect the evaluated clock sample.
    """
    import copy

    document = copy.deepcopy(dict(grade))
    overrides = evaluated_overrides(document, context)
    for step in document.get("steps") or []:
        if not isinstance(step, dict):
            continue
        step_overrides = overrides.get(str(step.get("id")))
        if not step_overrides:
            continue
        params = step.get("params")
        if not isinstance(params, dict):
            params = {}
            step["params"] = params
        params.update(step_overrides)
    return document


def grade_has_animation(grade: Mapping[str, Any] | None) -> bool:
    if not isinstance(grade, Mapping):
        return False
    animations = grade.get("animation")
    return isinstance(animations, list) and len(animations) > 0
