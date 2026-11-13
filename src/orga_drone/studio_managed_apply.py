"""CPU reference applicator for managed-sdr-v1 grades (#359/#356/#357).

Applies serial pointwise operations using the published managed math modules.
Spatial selections require a source UV; creative LUT assets require a resolver.
Neither is silently omitted.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
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
    ManagedCube,
    ManagedLutError,
    decode_bt709,
    decode_srgb,
    encode_bt709,
    encode_srgb,
    make_lut_resolver,
    sample_creative_lut,
)
from orga_drone.studio_managed_masks import no_selection_coverage, step_blend
from orga_drone.studio_managed_primaries import apply_primaries
from orga_drone.studio_managed_selection import (
    ManagedSelectionError,
    evaluate_selection,
    selection_by_id,
)
from orga_drone.studio_managed_wheels import managed_hsl, wheels_v1

Rgb = tuple[float, float, float]
Curve = tuple[tuple[float, float], ...]
Uv = tuple[float, float]
LutResolver = Callable[[Mapping[str, Any]], ManagedCube]

ADAPTER_VERSION = "managed-sdr-cpu-v1"
BAKE_SIZE = 33
IDENTITY_HUE_OFFSET_CURVE: Curve = ((0.0, 0.0), (360.0, 0.0))
IDENTITY_HUE_MULT_CURVE: Curve = ((0.0, 1.0), (360.0, 1.0))


class ManagedApplyError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _param_float(params: Mapping[str, Any], key: str, default: float) -> float:
    """Read a float param. Explicit ``0`` stays ``0`` (never coerced via ``or``)."""
    if key not in params or params[key] is None:
        return float(default)
    value = float(params[key])
    if not math.isfinite(value):
        raise ManagedApplyError(f"{key} must be finite", code="RANGE")
    return value


def _param_float_any(
    params: Mapping[str, Any], keys: Sequence[str], default: float
) -> float:
    for key in keys:
        if key in params and params[key] is not None:
            return _param_float(params, key, default)
    return float(default)


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
    if name in {"linear-bt709", "srgb"}:
        return name
    if name in {"encoded-bt709", "bt709-sdr", "bt709"}:
        return "bt709-sdr"
    if name == "declared":
        return "linear-bt709"
    raise ManagedApplyError(f"unsupported domain: {name}", code="UNSUPPORTED_GRADE")


def apply_managed_step(
    rgb: Rgb,
    step: Mapping[str, Any],
    *,
    coverage: float = 1.0,
    lut_resolver: LutResolver | None = None,
) -> Rgb:
    """Apply one enabled managed step in its declared domain.

    ``coverage`` is the selection matte (1 = full). Mix and coverage both blend
    toward the step input: ``C + mix*coverage*(P-C)``.
    """
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
    if not 0.0 <= coverage <= 1.0:
        raise ManagedApplyError("coverage must be from 0 to 1", code="RANGE")
    raw_params = step.get("params")
    params: dict[str, Any] = dict(raw_params) if isinstance(raw_params, Mapping) else {}
    if "mix" not in step or step.get("mix") is None:
        mix = 1.0
    else:
        mix = float(step["mix"])
    if not 0.0 <= mix <= 1.0:
        raise ManagedApplyError("mix must be from 0 to 1", code="RANGE")

    processed: Rgb
    if kind == "primaries-v1":
        processed = apply_primaries(
            rgb,
            exposure=_param_float(params, "exposure", 0.0),
            kelvin=_param_float(params, "kelvin", 6500.0),
            tint=_param_float(params, "tint", 0.0),
            contrast=_param_float(params, "contrast", 1.0),
            pivot=_param_float(params, "pivot", 0.18),
            saturation=_param_float(params, "saturation", 1.0),
            blacks=_param_float(params, "blacks", 0.0),
            shadows=_param_float(params, "shadows", 0.0),
            highlights=_param_float(params, "highlights", 0.0),
            whites=_param_float(params, "whites", 0.0),
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
            lift=_param_float(params, "lift", 0.0),
            gamma=_param_float(params, "gamma", 1.0),
            gain=_param_float(params, "gain", 1.0),
            offset=_param_float(params, "offset", 0.0),
        )
    elif kind == "managed-hsl-v1":
        processed = managed_hsl(
            rgb,
            hue_offset_deg=_param_float_any(
                params, ("hue", "hue_offset_deg"), 0.0
            ),
            saturation_mult=_param_float_any(
                params, ("saturation", "saturation_mult"), 1.0
            ),
            lightness_offset=_param_float_any(
                params, ("lightness", "lightness_offset"), 0.0
            ),
        )
    elif kind == "creative-lut-v1":
        if lut_resolver is None:
            raise ManagedApplyError(
                "creative LUT assets require the managed LUT adapter",
                code="UNSUPPORTED_GRADE",
            )
        try:
            cube = lut_resolver(params)
            strength = _param_float(params, "strength", 1.0)
            processed = sample_creative_lut(cube, rgb, strength)
        except ManagedLutError as exc:
            raise ManagedApplyError(str(exc), code=exc.code) from exc
    elif kind == "legacy-stack-v1":
        raise ManagedApplyError(
            "legacy-stack must use the legacy builders",
            code="UNSUPPORTED_GRADE",
        )
    else:
        raise ManagedApplyError(f"unhandled step type: {kind}", code="UNSUPPORTED_GRADE")

    if mix >= 1.0 and coverage >= 1.0:
        return processed
    return step_blend(rgb, processed, mix, coverage)


def _encoded_bt709_sample(rgb: Rgb, *, domain: str) -> Rgb:
    """Qualifier contract samples the step input in bounded encoded BT.709."""
    if domain in {"encoded-bt709", "bt709-sdr", "bt709"}:
        return rgb
    if domain == "srgb":
        linear = _decode_profile("srgb", rgb)
        return _encode_profile("bt709-sdr", linear)
    if domain == "linear-bt709":
        return _encode_profile("bt709-sdr", rgb)
    raise ManagedApplyError(f"unsupported qualifier domain: {domain}", code="UNSUPPORTED_GRADE")


def apply_managed_grade_rgb(
    rgb: Rgb,
    grade: Mapping[str, Any] | GradeModel,
    *,
    lattice_domain: str = "encoded-bt709",
    uv: Uv | None = None,
    lut_resolver: LutResolver | None = None,
) -> Rgb:
    """Apply a managed grade to one RGB sample.

    ``lattice_domain`` is the encoding of the incoming sample (preview JPEG and
    FFmpeg RGB filters use encoded BT.709/sRGB code values). The applicator
    decodes to linear, converts into each step domain, then encodes to the grade
    output profile for presentation/export boundaries.

    Steps with ``selection_id`` require ``uv`` (normalized source coordinates).
    Creative LUT steps require ``lut_resolver``.
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

    raw_selections = document.get("selections")
    selections: list[Mapping[str, Any]] = [
        entry
        for entry in (list(raw_selections) if isinstance(raw_selections, list) else [])
        if isinstance(entry, Mapping)
    ]

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
        coverage = no_selection_coverage()
        selection_id = step.get("selection_id")
        if selection_id:
            if uv is None:
                raise ManagedApplyError(
                    "masked steps require a spatial adapter",
                    code="UNSUPPORTED_GRADE",
                )
            try:
                selection = selection_by_id(selections, str(selection_id))
                sample = _encoded_bt709_sample(working, domain=domain)
                coverage = evaluate_selection(selection, point=uv, rgb=sample)
            except ManagedSelectionError as exc:
                raise ManagedApplyError(
                    str(exc) or "masked steps require a spatial adapter",
                    code="UNSUPPORTED_GRADE",
                ) from exc

        working = apply_managed_step(
            working,
            step,
            coverage=coverage,
            lut_resolver=lut_resolver,
        )

    working = _to_domain(working, current=domain, target="linear-bt709")
    return _encode_profile(output_profile if output_profile != "bt709" else "bt709-sdr", working)


def grade_is_managed_sdr(
    effect_settings: str | Mapping[str, Any] | None,
) -> bool:
    """True when the clip authority is managed-sdr-v1."""
    model = read_grade(effect_settings)
    return model.evaluator == "managed-sdr-v1" and model.grade is not None


def grade_has_spatial_selections(
    effect_settings: str | Mapping[str, Any] | None,
) -> bool:
    """True when any enabled step binds a selection_id."""
    model = read_grade(effect_settings)
    if model.evaluator != "managed-sdr-v1" or model.grade is None:
        return False
    for step in model.grade.get("steps") or []:
        if step.get("enabled", True) and step.get("selection_id"):
            return True
    return False


def grade_needs_cpu_materialize(
    effect_settings: str | Mapping[str, Any] | None,
) -> bool:
    """True when preview/export must CPU-grade frames (spatial and/or animation)."""
    from orga_drone.studio_grade_animation import grade_has_animation

    model = read_grade(effect_settings)
    if model.evaluator != "managed-sdr-v1" or model.grade is None:
        return False
    if grade_has_animation(model.grade):
        return True
    return grade_has_spatial_selections(effect_settings)


def grade_is_managed_pointwise(effect_settings: str | Mapping[str, Any] | None) -> bool:
    """True when preview/export can bake a global 3D LUT (no spatial/LUT assets)."""
    from orga_drone.studio_grade_animation import grade_has_animation

    model = read_grade(effect_settings)
    if model.evaluator != "managed-sdr-v1" or model.grade is None:
        return False
    # Canonical animation is time-varying; a single bake LUT would flatten it.
    if grade_has_animation(model.grade):
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
            params = step.get("params") if isinstance(step.get("params"), Mapping) else {}
            asset = params.get("asset_id") or params.get("creative_lut")
            if not isinstance(asset, str) or not asset.strip():
                return False
    return True


def grade_is_managed_cpu_executable(
    effect_settings: str | Mapping[str, Any] | None,
    *,
    has_lut_resolver: bool = False,
) -> bool:
    """True when the CPU applicator can execute every enabled step.

    Spatial selections are supported. Creative LUT requires ``has_lut_resolver``.
    """
    model = read_grade(effect_settings)
    if model.evaluator != "managed-sdr-v1" or model.grade is None:
        return False
    for step in model.grade.get("steps") or []:
        if not step.get("enabled", True):
            continue
        kind = step.get("type")
        descriptor = OPERATION_DESCRIPTORS.get(str(kind))
        if descriptor is None or not descriptor.get("pointwise", False):
            return False
        if kind == "creative-lut-v1" and not has_lut_resolver:
            return False
    return True


def require_managed_pointwise(
    effect_settings: str | Mapping[str, Any] | None,
) -> None:
    """Reject managed grades that cannot be executed by the lut3d bake adapter."""
    if not grade_is_managed_sdr(effect_settings):
        return
    if grade_is_managed_pointwise(effect_settings):
        return
    raise ManagedApplyError(
        "This managed grade needs masks, a creative LUT, or another adapter before preview/export",
        code="UNSUPPORTED_GRADE",
    )


def require_managed_executable(
    effect_settings: str | Mapping[str, Any] | None,
    *,
    has_lut_resolver: bool = False,
) -> None:
    """Reject managed grades the CPU applicator cannot execute."""
    if not grade_is_managed_sdr(effect_settings):
        return
    if grade_is_managed_pointwise(effect_settings):
        return
    if grade_is_managed_cpu_executable(
        effect_settings, has_lut_resolver=has_lut_resolver
    ):
        return
    raise ManagedApplyError(
        "This managed grade needs a creative LUT resolver or another adapter before preview/export",
        code="UNSUPPORTED_GRADE",
    )


def apply_managed_grade_image(
    pixels: Sequence[Sequence[Rgb]],
    grade: Mapping[str, Any] | GradeModel,
    *,
    lattice_domain: str = "encoded-bt709",
    lut_resolver: LutResolver | None = None,
) -> list[list[Rgb]]:
    """Apply a managed grade to a row-major RGB image using pixel-center UVs."""
    if not pixels:
        return []
    height = len(pixels)
    width = len(pixels[0]) if height else 0
    if width <= 0:
        return [list(row) for row in pixels]
    out: list[list[Rgb]] = []
    for y, row in enumerate(pixels):
        if len(row) != width:
            raise ManagedApplyError("image rows must share a width", code="RANGE")
        out_row: list[Rgb] = []
        for x, sample in enumerate(row):
            uv = ((x + 0.5) / width, (y + 0.5) / height)
            out_row.append(
                apply_managed_grade_rgb(
                    sample,
                    grade,
                    lattice_domain=lattice_domain,
                    uv=uv,
                    lut_resolver=lut_resolver,
                )
            )
        out.append(out_row)
    return out


def bake_managed_grade_cube(
    grade: Mapping[str, Any] | GradeModel,
    path: Path,
    *,
    size: int = BAKE_SIZE,
    lattice_domain: str = "encoded-bt709",
    lut_resolver: LutResolver | None = None,
    data_dir: Path | None = None,
) -> Path:
    """Write a red-fastest .cube that approximates the managed grade in lattice space."""
    if size < 2 or size > 65:
        raise ManagedApplyError("bake size must be from 2 to 65", code="RANGE")
    resolver = lut_resolver
    if resolver is None and data_dir is not None:
        resolver = make_lut_resolver(data_dir)
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
                    sample,
                    grade,
                    lattice_domain=lattice_domain,
                    lut_resolver=resolver,
                )
                lines.append(f"{out[0]:.8f} {out[1]:.8f} {out[2]:.8f}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _creative_lut_asset_digests(
    grade: Mapping[str, Any],
    *,
    data_dir: Path | None,
) -> list[str]:
    """Resolve creative LUT file digests for cache identity. Fail closed if missing."""
    digests: list[str] = []
    for step in grade.get("steps") or []:
        if not isinstance(step, Mapping) or not step.get("enabled", True):
            continue
        if step.get("type") != "creative-lut-v1":
            continue
        params = step.get("params") if isinstance(step.get("params"), Mapping) else {}
        if data_dir is None:
            raise ManagedApplyError(
                "creative LUT bake requires data_dir for asset identity",
                code="UNSUPPORTED_GRADE",
            )
        try:
            cube = make_lut_resolver(data_dir)(params)
        except ManagedLutError as exc:
            raise ManagedApplyError(str(exc), code=exc.code) from exc
        digests.append(cube.digest)
    return digests


def managed_grade_digest(
    effect_settings: str | Mapping[str, Any] | None,
    *,
    data_dir: Path | None = None,
) -> str | None:
    """Stable content digest for cache keys, or None when not managed-sdr.

    When creative LUT steps are present, ``data_dir`` is required so asset
    bytes enter the digest (missing/replaced cubes fail closed).
    """
    import hashlib
    import json

    model = read_grade(effect_settings)
    if model.evaluator != "managed-sdr-v1" or model.grade is None:
        return None
    asset_digests = _creative_lut_asset_digests(model.grade, data_dir=data_dir)
    payload = {
        "adapter": ADAPTER_VERSION,
        "evaluator": model.evaluator,
        "revision": model.revision,
        "grade": model.grade,
        "assets": asset_digests,
        "mode": (
            "lut-bake"
            if grade_is_managed_pointwise(effect_settings)
            else "cpu-spatial"
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ffmpeg_managed_grade_chain(
    effect_settings: str | Mapping[str, Any] | None,
    *,
    work_dir: Path,
    data_dir: Path | None = None,
) -> str:
    """Bake a managed grade to ``lut3d`` for FFmpeg preview/export, or empty."""
    if not grade_is_managed_pointwise(effect_settings):
        return ""
    model = read_grade(effect_settings)
    assert model.grade is not None
    digest = managed_grade_digest(effect_settings, data_dir=data_dir)
    assert digest is not None
    work_dir.mkdir(parents=True, exist_ok=True)
    cube = work_dir / f"managed_{digest[:16]}.cube"
    # Always re-validate creative assets before reusing a bake.
    _creative_lut_asset_digests(model.grade, data_dir=data_dir)
    if not cube.is_file():
        bake_managed_grade_cube(model.grade, cube, data_dir=data_dir)
    from orga_drone.studio_lut import escape_ffmpeg_lut_path

    return f"lut3d=file={escape_ffmpeg_lut_path(cube)}:interp=tetrahedral"
