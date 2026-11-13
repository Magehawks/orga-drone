"""Read-only managed SDR transfers and 3D LUT sampling for issue #352.

Legacy ``studio_lut`` import, preview, and export stay unchanged. This module
does not persist a grade and is not called by the encoder.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ManagedLutError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def encode_srgb(linear: float) -> float:
    """sRGB OETF. The toe breakpoint is the published constant, not a smooth join."""
    if linear <= 0.0031308:
        return 12.92 * linear
    return 1.055 * linear ** (1 / 2.4) - 0.055


def encode_bt709(linear: float) -> float:
    """BT.709 OETF. The toe uses the published rounded constants."""
    if linear < 0.018:
        return 4.5 * linear
    return 1.099 * linear**0.45 - 0.099


def decode_srgb(encoded: float) -> float:
    if encoded <= 0.04045:
        return encoded / 12.92
    return ((encoded + 0.055) / 1.055) ** 2.4


def decode_bt709(encoded: float) -> float:
    if encoded < 0.081:
        return encoded / 4.5
    return ((encoded + 0.099) / 1.099) ** (1 / 0.45)


def quantize_rgb8(encoded: float) -> int:
    """Q8(x) = floor(255 * clamp(x, 0, 1) + 0.5). Ties round upward."""
    clamped = min(1.0, max(0.0, encoded))
    return math.floor(255 * clamped + 0.5)


def require_managed_profile(name: object) -> str:
    """Accept only tagged sRGB or BT.709. Untagged, HDR, and log names fail."""
    if not isinstance(name, str) or not name.strip():
        raise ManagedLutError(
            "untagged input is not assumed",
            code="UNSUPPORTED_INPUT_PROFILE",
        )
    key = "".join(character for character in name.strip().lower() if character.isalnum())
    if key == "srgb":
        return "srgb"
    if key in {"bt709", "rec709"}:
        return "bt709"
    if any(token in key for token in ("hdr", "pq", "hlg", "log", "slog", "dlog")):
        raise ManagedLutError(
            f"unsupported HDR or log profile: {name}",
            code="UNSUPPORTED_INPUT_PROFILE",
        )
    raise ManagedLutError(
        f"ambiguous or unsupported profile: {name}",
        code="UNSUPPORTED_INPUT_PROFILE",
    )


@dataclass(frozen=True)
class ManagedCube:
    size: int
    data: tuple[tuple[float, float, float], ...]
    domain_min: tuple[float, float, float]
    domain_max: tuple[float, float, float]
    input_profile: str
    output_profile: str
    digest: str


def lut_digest(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()


def parse_managed_cube(
    text: str,
    *,
    input_profile: str,
    output_profile: str,
) -> ManagedCube:
    """Parse one 3D cube. Red changes fastest. Domain lines are kept."""
    if not isinstance(text, str) or not text.strip():
        raise ManagedLutError("LUT file is empty", code="LUT_INVALID")
    profile_in = require_managed_profile(input_profile)
    profile_out = require_managed_profile(output_profile)
    size: int | None = None
    domain_min = [0.0, 0.0, 0.0]
    domain_max = [1.0, 1.0, 1.0]
    seen_size = False
    seen_min = False
    seen_max = False
    triples: list[tuple[float, float, float]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        upper = line.upper()
        if upper.startswith("TITLE"):
            continue
        if upper.startswith("LUT_3D_SIZE"):
            if seen_size:
                raise ManagedLutError("duplicate LUT_3D_SIZE header", code="LUT_INVALID")
            seen_size = True
            parts = upper.split()
            if len(parts) != 2 or not parts[1].isdigit():
                raise ManagedLutError("malformed LUT_3D_SIZE", code="LUT_INVALID")
            size = int(parts[1])
            if not 2 <= size <= 65:
                raise ManagedLutError(
                    "LUT_3D_SIZE must be from 2 to 65",
                    code="LUT_INVALID",
                )
            continue
        if upper.startswith("DOMAIN_MIN") or upper.startswith("DOMAIN_MAX"):
            is_min = upper.startswith("DOMAIN_MIN")
            if is_min and seen_min:
                raise ManagedLutError("duplicate DOMAIN_MIN header", code="LUT_INVALID")
            if not is_min and seen_max:
                raise ManagedLutError("duplicate DOMAIN_MAX header", code="LUT_INVALID")
            parts = line.split()
            if len(parts) != 4:
                raise ManagedLutError("malformed LUT domain", code="LUT_INVALID")
            try:
                values = [float(part) for part in parts[1:4]]
            except ValueError as exc:
                raise ManagedLutError("malformed LUT domain", code="LUT_INVALID") from exc
            target = domain_min if is_min else domain_max
            target[:] = values
            if is_min:
                seen_min = True
            else:
                seen_max = True
            if not all(math.isfinite(value) for value in values):
                raise ManagedLutError("non-finite LUT domain", code="LUT_INVALID")
            if any(domain_min[index] >= domain_max[index] for index in range(3)):
                raise ManagedLutError(
                    "LUT domain bounds are not increasing",
                    code="LUT_INVALID",
                )
            continue
        if upper.startswith(("LUT_1D_SIZE", "LUT_1D_INPUT_RANGE", "SHAPER_SIZE")):
            raise ManagedLutError(
                "1D and shaper LUTs are not part of this contract",
                code="LUT_UNSUPPORTED",
            )
        parts = line.split()
        if len(parts) != 3:
            raise ManagedLutError("malformed cube line", code="LUT_INVALID")
        try:
            triple = (float(parts[0]), float(parts[1]), float(parts[2]))
        except ValueError as exc:
            raise ManagedLutError("malformed cube line", code="LUT_INVALID") from exc
        if not all(math.isfinite(value) for value in triple):
            raise ManagedLutError("non-finite cube value", code="LUT_INVALID")
        triples.append(triple)
    if size is None:
        raise ManagedLutError("LUT is missing LUT_3D_SIZE", code="LUT_INVALID")
    expected = size * size * size
    if len(triples) != expected:
        raise ManagedLutError(
            f"LUT expected {expected} RGB rows, found {len(triples)}",
            code="LUT_INVALID",
        )
    encoded = text.encode("utf-8")
    return ManagedCube(
        size=size,
        data=tuple(triples),
        domain_min=(domain_min[0], domain_min[1], domain_min[2]),
        domain_max=(domain_max[0], domain_max[1], domain_max[2]),
        input_profile=profile_in,
        output_profile=profile_out,
        digest=lut_digest(encoded),
    )


def interpolation_order(fractions: tuple[float, float, float]) -> tuple[int, int, int]:
    """Descending fractional axes. Equal fractions resolve red, then green, then blue."""
    ordered = sorted(range(3), key=lambda axis: (-fractions[axis], axis))
    return (ordered[0], ordered[1], ordered[2])


def sample_lut(
    lut: ManagedCube, rgb: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Tetrahedral sample. Table values stay float; nothing is quantized to 8-bit."""
    size = lut.size
    coords: list[float] = []
    for index in range(3):
        span = lut.domain_max[index] - lut.domain_min[index]
        scaled = (rgb[index] - lut.domain_min[index]) / span
        coords.append(min(1.0, max(0.0, scaled)) * (size - 1))

    def vertex(red: int, green: int, blue: int) -> tuple[float, float, float]:
        return lut.data[red + green * size + blue * size * size]

    fractions = (coords[0] % 1.0, coords[1] % 1.0, coords[2] % 1.0)
    base = [int(coord) for coord in coords]
    first, second, third = interpolation_order(fractions)

    def at(offsets: tuple[int, int, int]) -> tuple[float, float, float]:
        return vertex(
            min(base[0] + offsets[0], size - 1),
            min(base[1] + offsets[1], size - 1),
            min(base[2] + offsets[2], size - 1),
        )

    def axis_offset(axis: int) -> tuple[int, int, int]:
        return (int(axis == 0), int(axis == 1), int(axis == 2))

    def both(left: int, right: int) -> tuple[int, int, int]:
        return (
            int(left == 0 or right == 0),
            int(left == 1 or right == 1),
            int(left == 2 or right == 2),
        )

    origin = at((0, 0, 0))
    along_first = at(axis_offset(first))
    along_two = at(both(first, second))
    far = at((1, 1, 1))
    weight_first = fractions[first]
    weight_second = fractions[second]
    weight_third = fractions[third]
    return (
        origin[0]
        + weight_first * (along_first[0] - origin[0])
        + weight_second * (along_two[0] - along_first[0])
        + weight_third * (far[0] - along_two[0]),
        origin[1]
        + weight_first * (along_first[1] - origin[1])
        + weight_second * (along_two[1] - along_first[1])
        + weight_third * (far[1] - along_two[1]),
        origin[2]
        + weight_first * (along_first[2] - origin[2])
        + weight_second * (along_two[2] - along_first[2])
        + weight_third * (far[2] - along_two[2]),
    )


def sample_creative_lut(
    lut: ManagedCube,
    rgb: tuple[float, float, float],
    strength: float,
) -> tuple[float, float, float]:
    """Blend in the LUT domain. Strength 0 skips the sample and the domain clamp."""
    if lut.input_profile != lut.output_profile:
        raise ManagedLutError(
            "creative LUT output cannot be blended in its input domain",
            code="LUT_DOMAIN",
        )
    if strength < 0.0 or strength > 1.0:
        raise ManagedLutError("creative strength must be from 0 to 1", code="LUT_INVALID")
    if strength == 0.0:
        return rgb
    sampled = sample_lut(lut, rgb)
    return (
        (1.0 - strength) * rgb[0] + strength * sampled[0],
        (1.0 - strength) * rgb[1] + strength * sampled[1],
        (1.0 - strength) * rgb[2] + strength * sampled[2],
    )


def confirm_technical_lut(*, confirmed: bool, already_applied: bool) -> None:
    """A technical conversion is explicit and happens once, before grading."""
    if already_applied:
        raise ManagedLutError(
            "technical conversion already ran",
            code="TECHNICAL_LUT_ONCE",
        )
    if not confirmed:
        raise ManagedLutError(
            "technical conversion requires confirmation",
            code="TECHNICAL_LUT_UNCONFIRMED",
        )


def resolve_creative_lut_cube(
    data_dir: Path,
    params: Mapping[str, Any],
) -> ManagedCube:
    """Load and validate a creative .cube from confined LUT assets.

    Params use ``asset_id`` (filename under data_dir/luts) plus optional
    ``sha256``, ``input_profile``, and ``output_profile``. Missing or
    mismatched digests fail closed.
    """
    from orga_drone.studio_lut import LutMissingError, require_lut_asset

    asset_id = params.get("asset_id") or params.get("creative_lut")
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise ManagedLutError("creative LUT asset_id is required", code="LUT_MISSING")
    try:
        path = require_lut_asset(data_dir, asset_id.strip())
    except (LutMissingError, ValueError) as exc:
        raise ManagedLutError(str(exc) or "creative LUT missing", code="LUT_MISSING") from exc
    text = path.read_text(encoding="utf-8")
    input_profile = str(params.get("input_profile") or "bt709")
    output_profile = str(params.get("output_profile") or input_profile)
    cube = parse_managed_cube(
        text, input_profile=input_profile, output_profile=output_profile
    )
    expected = params.get("sha256")
    if expected is not None and str(expected) and str(expected) != cube.digest:
        raise ManagedLutError(
            "creative LUT content does not match sha256",
            code="LUT_DIGEST",
        )
    return cube


def make_lut_resolver(data_dir: Path):
    """Return a callable suitable for ``apply_managed_step(..., lut_resolver=)``."""

    def resolve(params: Mapping[str, Any]) -> ManagedCube:
        return resolve_creative_lut_cube(data_dir, params)

    return resolve
