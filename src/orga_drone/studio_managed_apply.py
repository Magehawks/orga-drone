"""CPU reference applicator for managed-sdr-v1 grades (#359).

Applies serial pointwise operations using the published managed math modules.
Spatial selections and creative LUT assets are not silently omitted: they raise
``ManagedApplyError`` so preview/export can reject before publication.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from orga_drone.studio_grade_model import OPERATION_DESCRIPTORS, GradeModel, read_grade
from orga_drone.studio_managed_curves import (
    IDENTITY_CURVE,
    hue_vs_hue,
    hue_vs_luma,
    hue_vs_saturation,
    luma_curve_v1,
    luma_vs_saturation,
    rgb_curves_v1,
    saturation_vs_saturation,
)
from orga_drone.studio_managed_lut import (
    decode_bt709,
    decode_srgb,
    encode_bt709,
    encode_srgb,
)
from orga_drone.studio_managed_masks import no_selection_coverage, step_blend
from orga_drone.studio_managed_primaries import apply_primaries
from orga_drone.studio_managed_wheels import managed_hsl, wheels_v1

Rgb = tuple[float, float, float]
Curve = tuple[tuple[float, float], ...]

ADAPTER_VERSION = "managed-sdr-cpu-v1"
BAKE_SIZE = 33
IDENTITY_HUE_OFFSET_CURVE: Curve = ((0.0, 0.0), (360.0, 0.0))
IDENTITY_HUE_MULT_CURVE: Curve = ((0.0, 1.0), (360.0, 1.0))


class ManagedApplyError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _as_curve(value: Any, *, default: Curve = IDENTITY_CURVE) -> Curve:
    if value is None:
        return tuple((float(x), float(y)) for x, y in default)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ManagedApplyError("curve must be a list of points", code="CURVE")
    points: list[tuple[float, float]] = []
    for entry in value:
        if not isinstance(entry, Sequence) or len(entry) != 2:
            raise ManagedApplyError("each curve point needs x and y", code="CURVE")
        x_value, y_value = float(entry[0]), float(entry[1])
        if not math.isfinite(x_value) or not math.isfinite(y_value):
            raise ManagedApplyError("curve points must be finite", code="CURVE")
        points.append((x_value, y_value))
    if not points:
        return tuple((float(x), float(y)) for x, y in default)
    return tuple(points)


def _decode_profile(profile: str, rgb: Rgb) -> Rgb:
    if profile == "linear-bt709":
        return rgb
    if profile == "srgb":
        return (decode_srgb(rgb[0]), decode_srgb(rgb[1]), decode_srgb(rgb[2]))
    if profile in {"bt709-sdr", "bt709"}:
        return (decode_bt709(rgb[0]), decode_bt709(rgb[1]), decode_bt709(rgb[2]))
    raise ManagedApplyError(
        f"unsupported input profile: {profile}",
        code="UNSUPPORTED_INPUT_PROFILE",
    )


def _encode_profile(profile: str, rgb: Rgb) -> Rgb:
    clipped = (
        min(1.0, max(0.0, rgb[0])),
        min(1.0, max(0.0, rgb[1])),
        min(1.0, max(0.0, rgb[2])),
    )
    if profile == "linear-bt709":
        return clipped
    if profile == "srgb":
        return (encode_srgb(clipped[0]), encode_srgb(clipped[1]), encode_srgb(clipped[2]))
    if profile in {"bt709-sdr", "bt709"}:
        return (
            encode_bt709(clipped[0]),
            encode_bt709(clipped[1]),
            encode_bt709(clipped[2]),
        )
    raise ManagedApplyError(
        f"unsupported output profile: {profile}",
        code="UNSUPPORTED_GRADE",
    )


def _to_domain(rgb: Rgb, *, current: str, target: str) -> Rgb:
    if current == target:
        return rgb
    linear = rgb if current == "linear-bt709" else _decode_profile(current, rgb)
    if target == "linear-bt709":
        return linear
    if target in {"encoded-bt709", "bt709-sdr", "bt709"}:
        return _encode_profile("bt709-sdr", linear)
    if target == "srgb":
        return _encode_profile("srgb", linear)
    raise ManagedApplyError(
        f"unsupported domain transition {current} → {target}",
        code="UNSUPPORTED_GRADE",
    )


def _normalize_domain(name: str) -> str:
    if name in {"linear-bt709", "encoded-bt709", "srgb", "bt709-sdr", "bt709"}:
        return "bt709-sdr" if name in {"bt709", "bt709-sdr"} else name
    if name == "declared":
        return "linear-bt709"
    raise ManagedApplyError(f"unsupported domain: {name}", code="UNSUPPORTED_GRADE")


def apply_managed_step(rgb: Rgb, step: Mapping[str, Any]) -> Rgb:
    """Apply one enabled managed step in its declared domain."""
    kind = step.get("type")
    if not isinstance(kind, str):
        raise ManagedApplyError("step type is required", code="UNSUPPORTED_GRADE")
    if kind not in OPERATION_DESCRIPTORS:
        raise ManagedApplyError(f"unknown step type: {kind}", code="UNSUPPORTED_GRADE")
    descriptor = OPERATION_DESCRIPTORS[kind]
    if not descriptor.get("pointwise", False):
        raise ManagedApplyError(
            f"spatial step cannot run in the pointwise applicator: {kind}",
            code="UNSUPPORTED_GRADE",
        )
    if step.get("selection_id"):
        raise ManagedApplyError(
            "masked steps require a spatial adapter",
            code="UNSUPPORTED_GRADE",
        )
    raw_params = step.get("params")
    params: dict[str, Any] = dict(raw_params) if isinstance(raw_params, Mapping) else {}
    mix = float(step.get("mix", 1) or 0)
    if not 0.0 <= mix <= 1.0:
        raise ManagedApplyError("mix must be from 0 to 1", code="RANGE")

    processed: Rgb
    if kind == "primaries-v1":
        processed = apply_primaries(
            rgb,
            exposure=float(params.get("exposure", 0) or 0),
            kelvin=float(params.get("kelvin", 6500) or 6500),
            tint=float(params.get("tint", 0) or 0),
            contrast=float(params.get("contrast", 1) or 1),
            pivot=float(params.get("pivot", 0.18) or 0.18),
            saturation=float(params.get("saturation", 1) or 1),
            blacks=float(params.get("blacks", 0) or 0),
            shadows=float(params.get("shadows", 0) or 0),
            highlights=float(params.get("highlights", 0) or 0),
            whites=float(params.get("whites", 0) or 0),
        )
    elif kind == "rgb-curves-v1":
        processed = rgb_curves_v1(
            rgb,
            master=_as_curve(params.get("master")),
            channels=(
                _as_curve(params.get("red")),
                _as_curve(params.get("green")),
                _as_curve(params.get("blue")),
            ),
        )
    elif kind == "luma-curve-v1":
        processed = luma_curve_v1(rgb, _as_curve(params.get("curve")))
    elif kind == "hue-vs-hue-v1":
        processed = hue_vs_hue(
            rgb, _as_curve(params.get("curve"), default=IDENTITY_HUE_OFFSET_CURVE)
        )
    elif kind == "hue-vs-saturation-v1":
        processed = hue_vs_saturation(
            rgb, _as_curve(params.get("curve"), default=IDENTITY_HUE_MULT_CURVE)
        )
    elif kind == "hue-vs-luma-v1":
        processed = hue_vs_luma(
            rgb, _as_curve(params.get("curve"), default=IDENTITY_HUE_OFFSET_CURVE)
        )
    elif kind == "luma-vs-saturation-v1":
        processed = luma_vs_saturation(
            rgb, _as_curve(params.get("curve"), default=((0.0, 1.0), (1.0, 1.0)))
        )
    elif kind == "saturation-vs-saturation-v1":
        processed = saturation_vs_saturation(rgb, _as_curve(params.get("curve")))
    elif kind == "wheels-v1":
        processed = wheels_v1(
            rgb,
            lift=float(params.get("lift", 0) or 0),
            gamma=float(params.get("gamma", 1) or 1),
            gain=float(params.get("gain", 1) or 1),
            offset=float(params.get("offset", 0) or 0),
        )
    elif kind == "managed-hsl-v1":
        processed = managed_hsl(
            rgb,
            hue_offset_deg=float(params.get("hue", params.get("hue_offset_deg", 0)) or 0),
            saturation_mult=float(
                params.get("saturation", params.get("saturation_mult", 1)) or 1
            ),
            lightness_offset=float(
                params.get("lightness", params.get("lightness_offset", 0)) or 0
            ),
        )
    elif kind == "creative-lut-v1":
        raise ManagedApplyError(
            "creative LUT assets require the managed LUT adapter",
            code="UNSUPPORTED_GRADE",
        )
    elif kind == "legacy-stack-v1":
        raise ManagedApplyError(
            "legacy-stack must use the legacy builders",
            code="UNSUPPORTED_GRADE",
        )
    else:
        raise ManagedApplyError(f"unhandled step type: {kind}", code="UNSUPPORTED_GRADE")

    if mix >= 1.0:
        return processed
    return step_blend(rgb, processed, mix, no_selection_coverage())


def apply_managed_grade_rgb(
    rgb: Rgb,
    grade: Mapping[str, Any] | GradeModel,
    *,
    lattice_domain: str = "encoded-bt709",
) -> Rgb:
    """Apply a managed grade to one RGB sample.

    ``lattice_domain`` is the encoding of the incoming sample (preview JPEG and
    FFmpeg RGB filters use encoded BT.709/sRGB code values). The applicator
    decodes to linear, converts into each step domain, then encodes to the grade
    output profile for presentation/export boundaries.
    """
    if isinstance(grade, GradeModel):
        if grade.evaluator != "managed-sdr-v1" or grade.grade is None:
            raise ManagedApplyError(
                "managed applicator requires managed-sdr-v1",
                code="UNSUPPORTED_GRADE",
            )
        document: Mapping[str, Any] = grade.grade
    else:
        document = grade
        if document.get("evaluator") != "managed-sdr-v1":
            raise ManagedApplyError(
                "managed applicator requires managed-sdr-v1",
                code="UNSUPPORTED_GRADE",
            )

    raw_input = document.get("input")
    input_obj: Mapping[str, Any] = raw_input if isinstance(raw_input, Mapping) else {}
    raw_output = document.get("output")
    output_obj: Mapping[str, Any] = raw_output if isinstance(raw_output, Mapping) else {}
    input_profile = str(input_obj.get("profile") or "bt709-sdr")
    output_profile = str(output_obj.get("profile") or "bt709-sdr")
    current = _normalize_domain(lattice_domain)
    # Enter working linear space from the lattice encoding, respecting the
    # declared input profile when the lattice is already that profile.
    if current in {"encoded-bt709", "bt709-sdr", "bt709"}:
        linear = _decode_profile("bt709-sdr", rgb)
    elif current == "srgb":
        linear = _decode_profile("srgb", rgb)
    elif current == "linear-bt709":
        linear = rgb
    else:
        linear = _decode_profile(input_profile, rgb)
    working: Rgb = linear
    domain = "linear-bt709"

    raw_steps = document.get("steps")
    steps: list[Any] = list(raw_steps) if isinstance(raw_steps, list) else []
    for step in steps:
        if not isinstance(step, Mapping) or not step.get("enabled", True):
            continue
        kind = step.get("type")
        descriptor = OPERATION_DESCRIPTORS.get(str(kind))
        if descriptor is None:
            raise ManagedApplyError(
                f"unknown enabled step: {kind}",
                code="UNSUPPORTED_GRADE",
            )
        target = descriptor.get("domain", "linear-bt709")
        if target == "declared":
            step_params = step.get("params")
            params_map: Mapping[str, Any] = (
                step_params if isinstance(step_params, Mapping) else {}
            )
            target = str(params_map.get("domain") or "linear-bt709")
        target = _normalize_domain(str(target))
        working = _to_domain(working, current=domain, target=target)
        domain = target
        working = apply_managed_step(working, step)

    working = _to_domain(working, current=domain, target="linear-bt709")
    return _encode_profile(output_profile if output_profile != "bt709" else "bt709-sdr", working)


def grade_is_managed_pointwise(effect_settings: str | Mapping[str, Any] | None) -> bool:
    """True when preview/export should use the managed applicator instead of legacy."""
    model = read_grade(effect_settings)
    if model.evaluator != "managed-sdr-v1" or model.grade is None:
        return False
    for step in model.grade.get("steps") or []:
        if not step.get("enabled", True):
            continue
        if step.get("selection_id"):
            return False
        kind = step.get("type")
        descriptor = OPERATION_DESCRIPTORS.get(str(kind))
        if descriptor is None or not descriptor.get("lut_bakeable", False):
            return False
        if kind == "creative-lut-v1":
            return False
    return True


def bake_managed_grade_cube(
    grade: Mapping[str, Any] | GradeModel,
    path: Path,
    *,
    size: int = BAKE_SIZE,
    lattice_domain: str = "encoded-bt709",
) -> Path:
    """Write a red-fastest .cube that approximates the managed grade in lattice space."""
    if size < 2 or size > 65:
        raise ManagedApplyError("bake size must be from 2 to 65", code="RANGE")
    denom = float(size - 1)
    lines = [
        f'TITLE "Orga managed-sdr {ADAPTER_VERSION}"',
        f"LUT_3D_SIZE {size}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
    ]
    for blue in range(size):
        for green in range(size):
            for red in range(size):
                sample = (red / denom, green / denom, blue / denom)
                out = apply_managed_grade_rgb(
                    sample, grade, lattice_domain=lattice_domain
                )
                lines.append(f"{out[0]:.8f} {out[1]:.8f} {out[2]:.8f}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def managed_grade_digest(effect_settings: str | Mapping[str, Any] | None) -> str | None:
    """Stable content digest for cache keys, or None when not managed pointwise."""
    import hashlib
    import json

    model = read_grade(effect_settings)
    if not grade_is_managed_pointwise(effect_settings) or model.grade is None:
        return None
    payload = {
        "adapter": ADAPTER_VERSION,
        "evaluator": model.evaluator,
        "revision": model.revision,
        "grade": model.grade,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ffmpeg_managed_grade_chain(
    effect_settings: str | Mapping[str, Any] | None,
    *,
    work_dir: Path,
) -> str:
    """Bake a managed grade to ``lut3d`` for FFmpeg preview/export, or empty."""
    if not grade_is_managed_pointwise(effect_settings):
        return ""
    model = read_grade(effect_settings)
    assert model.grade is not None
    digest = managed_grade_digest(effect_settings)
    assert digest is not None
    work_dir.mkdir(parents=True, exist_ok=True)
    cube = work_dir / f"managed_{digest[:16]}.cube"
    if not cube.is_file():
        bake_managed_grade_cube(model.grade, cube)
    from orga_drone.studio_lut import escape_ffmpeg_lut_path

    return f"lut3d=file={escape_ffmpeg_lut_path(cube)}:interp=tetrahedral"
