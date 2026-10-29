"""Local ``.cube`` LUT import and optional D-Log M conversion (Issue #174).

Technical conversion and creative looks are separate. SRT ``color_md`` is a
hint only — conversion never applies without an explicit user action and a
validated LUT file. Orga Drone does not redistribute camera-vendor LUTs;
users supply their own ``.cube`` files. Export uses FFmpeg ``lut3d`` after the
existing static grade and before the saturation ramp. Preview stays an
approximation of the grade sliders; LUT application is export-truth until a
shared still path exists.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

COLOR_KEY = "color"
INPUT_PROFILES = ("rec709", "dlog_m", "custom")
LUT_NAME_RE = re.compile(r"^[a-f0-9]{32}\.cube$")
MAX_LUT_BYTES = 32 * 1024 * 1024
MIN_LUT_SIZE = 2
MAX_LUT_SIZE = 65
TITLE_RE = re.compile(r'^TITLE\s+"([^"]*)"\s*$', re.IGNORECASE)
SIZE_RE = re.compile(r"^LUT_3D_SIZE\s+(\d+)\s*$", re.IGNORECASE)
DOMAIN_RE = re.compile(
    r"^DOMAIN_(?:MIN|MAX)\s+"
    r"([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*$",
    re.IGNORECASE,
)
TRIPLE_RE = re.compile(
    r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*$"
)


class LutMissingError(Exception):
    """A stored LUT reference no longer resolves on disk."""

    def __init__(self, asset_name: str) -> None:
        super().__init__(asset_name)
        self.asset_name = asset_name


class LutInvalidError(ValueError):
    """The file is not a usable 3D ``.cube`` LUT."""


@dataclass(frozen=True)
class ColorLook:
    """Per-clip color conversion and optional creative LUT."""

    input_profile: str = "rec709"
    conversion_lut: str = ""
    creative_lut: str = ""
    creative_strength: int = 100
    conversion_confirmed: bool = False

    @property
    def is_neutral(self) -> bool:
        return (
            self.input_profile == "rec709"
            and not self.conversion_lut
            and not self.creative_lut
            and self.creative_strength == 100
            and not self.conversion_confirmed
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "input_profile": self.input_profile,
            "conversion_lut": self.conversion_lut,
            "creative_lut": self.creative_lut,
            "creative_strength": self.creative_strength,
            "conversion_confirmed": self.conversion_confirmed,
        }


def color_look_preview_model() -> dict[str, object]:
    return {
        "inputProfiles": list(INPUT_PROFILES),
        "maxLutBytes": MAX_LUT_BYTES,
        "minLutSize": MIN_LUT_SIZE,
        "maxLutSize": MAX_LUT_SIZE,
    }


def lut_asset_dir(data_dir: Path) -> Path:
    path = data_dir / "luts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_lut_asset(data_dir: Path, asset_name: str) -> Path:
    if not isinstance(asset_name, str) or not LUT_NAME_RE.fullmatch(asset_name):
        raise ValueError("LUT reference is invalid")
    root = lut_asset_dir(data_dir).resolve()
    path = (root / asset_name).resolve()
    if path.parent != root:
        raise ValueError("LUT reference is invalid")
    return path


def require_lut_asset(data_dir: Path, asset_name: str) -> Path:
    path = resolve_lut_asset(data_dir, asset_name)
    if not path.is_file():
        raise LutMissingError(asset_name)
    return path


def parse_cube_text(text: str) -> tuple[int, list[tuple[float, float, float]]]:
    """Validate a ``.cube`` body. Returns size and RGB triples in file order."""
    if not isinstance(text, str) or not text.strip():
        raise LutInvalidError("LUT file is empty")
    size: int | None = None
    triples: list[tuple[float, float, float]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if TITLE_RE.match(line) or DOMAIN_RE.match(line):
            continue
        size_match = SIZE_RE.match(line)
        if size_match:
            if size is not None:
                raise LutInvalidError("LUT declares LUT_3D_SIZE more than once")
            size = int(size_match.group(1))
            if size < MIN_LUT_SIZE or size > MAX_LUT_SIZE:
                raise LutInvalidError(
                    f"LUT size must be between {MIN_LUT_SIZE} and {MAX_LUT_SIZE}"
                )
            continue
        triple_match = TRIPLE_RE.match(line)
        if triple_match:
            values = tuple(float(triple_match.group(i)) for i in (1, 2, 3))
            if any(not math.isfinite(v) for v in values):
                raise LutInvalidError("LUT contains a non-finite RGB value")
            triples.append((values[0], values[1], values[2]))
            continue
        raise LutInvalidError("LUT contains an unsupported line")
    if size is None:
        raise LutInvalidError("LUT is missing LUT_3D_SIZE")
    expected = size * size * size
    if len(triples) != expected:
        raise LutInvalidError(
            f"LUT expected {expected} RGB rows for size {size}, found {len(triples)}"
        )
    return size, triples


def validate_cube_bytes(data: bytes) -> tuple[int, list[tuple[float, float, float]]]:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise LutInvalidError("LUT file is empty")
    if len(data) > MAX_LUT_BYTES:
        raise LutInvalidError("LUT file is too large")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LutInvalidError("LUT file must be UTF-8 text") from exc
    return parse_cube_text(text)


def store_lut_asset(data_dir: Path, data: bytes) -> str:
    """Copy a validated ``.cube`` into the local data directory."""
    validate_cube_bytes(data)
    name = uuid.uuid4().hex + ".cube"
    dest = resolve_lut_asset(data_dir, name)
    dest.write_bytes(bytes(data))
    return name


def import_lut_from_path(data_dir: Path, source: Path) -> str:
    path = Path(source)
    if not path.is_file():
        raise LutInvalidError("LUT file was not found")
    if path.suffix.lower() != ".cube":
        raise LutInvalidError("LUT file must use the .cube extension")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LutInvalidError("LUT file could not be read") from exc
    return store_lut_asset(data_dir, data)


def _read_profile(value: object) -> str:
    if not isinstance(value, str):
        return "rec709"
    token = value.strip().lower().replace("-", "_")
    if token in INPUT_PROFILES:
        return token
    return "rec709"


def _read_lut_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    name = value.strip()
    if not name:
        return ""
    if not LUT_NAME_RE.fullmatch(name):
        return ""
    return name


def _read_strength(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 100
    number = float(value)
    if not math.isfinite(number):
        return 100
    return max(0, min(100, int(round(number))))


def color_look_from_effect_settings(raw: str | None) -> ColorLook:
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return ColorLook()
    if not isinstance(parsed, dict):
        return ColorLook()
    nested = parsed.get(COLOR_KEY)
    source = nested if isinstance(nested, dict) else {}
    return ColorLook(
        input_profile=_read_profile(source.get("input_profile")),
        conversion_lut=_read_lut_name(source.get("conversion_lut")),
        creative_lut=_read_lut_name(source.get("creative_lut")),
        creative_strength=_read_strength(source.get("creative_strength")),
        conversion_confirmed=bool(source.get("conversion_confirmed")),
    )


def parse_color_look_payload(payload: Mapping[str, object]) -> ColorLook:
    profile = payload.get("input_profile", "rec709")
    if not isinstance(profile, str) or profile.strip().lower().replace("-", "_") not in INPUT_PROFILES:
        raise ValueError("input_profile must be rec709, dlog_m, or custom")
    conversion = payload.get("conversion_lut", "")
    creative = payload.get("creative_lut", "")
    if conversion not in ("", None) and (
        not isinstance(conversion, str) or not LUT_NAME_RE.fullmatch(conversion)
    ):
        raise ValueError("conversion_lut reference is invalid")
    if creative not in ("", None) and (
        not isinstance(creative, str) or not LUT_NAME_RE.fullmatch(creative)
    ):
        raise ValueError("creative_lut reference is invalid")
    strength_raw = payload.get("creative_strength", 100)
    if isinstance(strength_raw, bool) or not isinstance(strength_raw, (int, float)):
        raise ValueError("creative_strength must be a number from 0 to 100")
    strength = float(strength_raw)
    if not math.isfinite(strength) or strength < 0 or strength > 100:
        raise ValueError("creative_strength must be a number from 0 to 100")
    confirmed = bool(payload.get("conversion_confirmed", False))
    conversion_name = conversion if isinstance(conversion, str) else ""
    creative_name = creative if isinstance(creative, str) else ""
    normalized = profile.strip().lower().replace("-", "_")
    if normalized == "dlog_m" and conversion_name and not confirmed:
        raise ValueError("D-Log M conversion requires an explicit confirmation")
    if normalized == "dlog_m" and confirmed and not conversion_name:
        raise ValueError("D-Log M conversion requires a .cube LUT")
    return ColorLook(
        input_profile=normalized,
        conversion_lut=conversion_name,
        creative_lut=creative_name,
        creative_strength=int(round(strength)),
        conversion_confirmed=confirmed,
    )


def dump_color_look(existing: str | None, look: ColorLook) -> str:
    try:
        parsed = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        parsed = {}
    data = parsed if isinstance(parsed, dict) else {}
    data[COLOR_KEY] = look.as_dict()
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def escape_ffmpeg_lut_path(path: Path) -> str:
    """Make a filesystem path safe inside an FFmpeg filter option value."""
    text = path.resolve().as_posix()
    return text.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def write_strength_blended_cube(
    source: Path,
    *,
    strength: int,
    destination: Path,
) -> Path:
    """Write a cube blended toward identity for creative strength below 100."""
    amount = max(0.0, min(1.0, float(strength) / 100.0))
    size, triples = parse_cube_text(source.read_text(encoding="utf-8"))
    if amount >= 1.0:
        shutil.copyfile(source, destination)
        return destination
    if amount <= 0.0:
        raise LutInvalidError("creative strength 0 skips the LUT")
    lines = [
        'TITLE "Orga Drone strength blend"',
        f"LUT_3D_SIZE {size}",
    ]
    denom = float(size - 1)
    index = 0
    for blue in range(size):
        for green in range(size):
            for red in range(size):
                lut_r, lut_g, lut_b = triples[index]
                identity = (red / denom, green / denom, blue / denom)
                blended = (
                    identity[0] * (1.0 - amount) + lut_r * amount,
                    identity[1] * (1.0 - amount) + lut_g * amount,
                    identity[2] * (1.0 - amount) + lut_b * amount,
                )
                lines.append(
                    f"{blended[0]:.8f} {blended[1]:.8f} {blended[2]:.8f}"
                )
                index += 1
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def ffmpeg_lut_chain(
    look: ColorLook,
    *,
    data_dir: Path,
    work_dir: Path | None = None,
) -> str:
    """Return ``lut3d`` filters after grade, or empty when nothing applies.

    Raises ``LutMissingError`` when a referenced asset is gone so export fails
    with an actionable error instead of silently skipping.
    """
    if look.is_neutral:
        return ""
    parts: list[str] = []
    if look.conversion_lut and look.conversion_confirmed:
        path = require_lut_asset(data_dir, look.conversion_lut)
        parts.append(
            f"lut3d=file={escape_ffmpeg_lut_path(path)}:interp=tetrahedral"
        )
    if look.creative_lut and look.creative_strength > 0:
        path = require_lut_asset(data_dir, look.creative_lut)
        if look.creative_strength < 100:
            if work_dir is None:
                raise LutInvalidError(
                    "creative strength below 100 needs a temporary work directory"
                )
            work_dir.mkdir(parents=True, exist_ok=True)
            blended = work_dir / f"creative_{look.creative_lut}"
            path = write_strength_blended_cube(
                path, strength=look.creative_strength, destination=blended
            )
        parts.append(
            f"lut3d=file={escape_ffmpeg_lut_path(path)}:interp=tetrahedral"
        )
    return ",".join(parts)


def write_identity_cube(path: Path, *, size: int = 2) -> Path:
    """Synthetic identity LUT for tests and packaging checks."""
    if size < MIN_LUT_SIZE or size > MAX_LUT_SIZE:
        raise LutInvalidError("invalid identity LUT size")
    lines = ['TITLE "Identity"', f"LUT_3D_SIZE {size}"]
    denom = float(size - 1)
    for blue in range(size):
        for green in range(size):
            for red in range(size):
                lines.append(
                    f"{red / denom:.8f} {green / denom:.8f} {blue / denom:.8f}"
                )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
