"""Studio Collage layout model and persistence helpers (ADR 0038)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

ITEM_KIND_COLLAGE = "collage"
COLLAGE_KIND = "collage"

SPEC_VERSION = 1
DEFAULT_DURATION_S = 5.0
MIN_DURATION_S = 1.0
MAX_DURATION_S = 120.0
DURATION_STEP_S = 0.1

MAX_LEAVES = 16
MAX_SPLIT_DEPTH = 8
# Concurrent muted HTML video leaves during Story play (ADR 0038 / #461).
MAX_CONCURRENT_COLLAGE_VIDEOS = 4
MIN_RATIO = 0.05
MAX_RATIO = 0.95
DEFAULT_GAP_PX = 8
MAX_GAP_PX = 200
MAX_CORNER_RADIUS_PX = 64
MIN_ZOOM = 1.0
MAX_ZOOM = 3.0
MAX_START_OFFSET_S = 24 * 3600.0

ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
}
DEFAULT_ASPECT = "16:9"
DEFAULT_BACKGROUND = "#0a0c0e"
DEFAULT_FIT = "fill"

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_LEAF_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class SourceWindow:
    """Normalized source crop window in 0..1 of the oriented picture."""

    x: float
    y: float
    w: float
    h: float


class CollageSpecError(ValueError):
    """Invalid collage specification."""


def clamp_collage_duration(duration_s: float) -> float:
    raw = float(duration_s)
    stepped = round(raw / DURATION_STEP_S) * DURATION_STEP_S
    clamped = max(MIN_DURATION_S, min(MAX_DURATION_S, stepped))
    return round(clamped, 1)


def new_leaf_id() -> str:
    return f"leaf-{uuid.uuid4().hex[:10]}"


def stable_external_source_key(path: str) -> str:
    """Opaque handle for external media that survives public path scrubbing."""
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
    return f"src-{digest}"


def _leaf(media: dict[str, Any] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "leaf", "id": new_leaf_id()}
    if media is not None:
        node["media"] = media
    return node


def _split(direction: str, ratio: float, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "split",
        "id": f"split-{uuid.uuid4().hex[:10]}",
        "dir": direction,
        "ratio": float(ratio),
        "a": a,
        "b": b,
    }


def _blank_spec(*, aspect: str = DEFAULT_ASPECT, root: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "version": SPEC_VERSION,
        "aspect": aspect,
        "gap_px": DEFAULT_GAP_PX,
        "background": DEFAULT_BACKGROUND,
        "corner_radius_px": 0,
        "duration_s": DEFAULT_DURATION_S,
        "root": root if root is not None else _leaf(),
    }


def preset_names() -> tuple[str, ...]:
    return (
        "1+1",
        "2+1",
        "1+2",
        "2x2",
        "3x2",
        "1+2+1",
        "3|2",
        "3|1+2",
    )


def preset_spec(name: str) -> dict[str, Any]:
    """Build a normalized preset collage spec."""
    key = (name or "").strip()
    if key == "1+1":
        root = _split("h", 0.5, _leaf(), _leaf())
    elif key == "2+1":
        root = _split("h", 0.4, _split("v", 0.5, _leaf(), _leaf()), _leaf())
    elif key == "1+2":
        root = _split("h", 0.6, _leaf(), _split("v", 0.5, _leaf(), _leaf()))
    elif key == "2x2":
        root = _split(
            "v",
            0.5,
            _split("h", 0.5, _leaf(), _leaf()),
            _split("h", 0.5, _leaf(), _leaf()),
        )
    elif key == "3x2":
        def _row() -> dict[str, Any]:
            return _split("h", 1 / 3, _leaf(), _split("h", 0.5, _leaf(), _leaf()))

        root = _split("v", 0.5, _row(), _row())
    elif key == "1+2+1":
        root = _split(
            "v",
            1 / 3,
            _leaf(),
            _split("v", 0.5, _split("h", 0.5, _leaf(), _leaf()), _leaf()),
        )
    elif key in {"3|2", "3left2right"}:
        left = _split("v", 1 / 3, _leaf(), _split("v", 0.5, _leaf(), _leaf()))
        right = _split("v", 0.5, _leaf(), _leaf())
        root = _split("h", 0.5, left, right)
    elif key in {"3|1+2", "3left_video_2bottom"}:
        # Three stacked cells on the left, one tall cell on the right (video),
        # two cells across the bottom — a common photo+video magazine layout.
        left3 = _split("v", 1 / 3, _leaf(), _split("v", 0.5, _leaf(), _leaf()))
        top = _split("h", 0.42, left3, _leaf())
        bottom = _split("h", 0.5, _leaf(), _leaf())
        root = _split("v", 0.68, top, bottom)
    else:
        raise CollageSpecError(f"unknown collage preset: {name}")
    return normalize_spec(_blank_spec(root=root))


def transfer_leaf_media(
    source_spec: dict[str, Any], target_spec: dict[str, Any]
) -> dict[str, Any]:
    """Copy leaf media (and grades) onto ``target_spec`` in leaf order.

    Extra source leaves are dropped when the target has fewer cells. Extra
    target leaves stay empty. Framing and ``media.grade`` travel with the media.
    """
    source = normalize_spec(source_spec)
    target = normalize_spec(target_spec)
    source_media = [
        dict(leaf["media"])
        for leaf in iter_leaves(source["root"])
        if isinstance(leaf.get("media"), dict)
    ]
    next_spec = target
    for leaf, media in zip(iter_leaves(next_spec["root"]), source_media, strict=False):
        next_spec = assign_leaf_media(next_spec, str(leaf["id"]), media)
    return normalize_spec(next_spec)


def apply_preset_preserving_media(
    current_spec: dict[str, Any], preset_name: str
) -> dict[str, Any]:
    """Build a preset layout and keep assigned media in leaf order."""
    current = normalize_spec(current_spec)
    next_spec = preset_spec(preset_name)
    for key in (
        "aspect",
        "gap_px",
        "background",
        "corner_radius_px",
        "duration_s",
    ):
        if key in current:
            next_spec[key] = current[key]
    return transfer_leaf_media(current, next_spec)


def default_spec() -> dict[str, Any]:
    return preset_spec("1+1")


def dump_collage_spec(spec: dict[str, Any]) -> str:
    normalized = normalize_spec(spec)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def collage_spec_from_raw(raw: str | None) -> dict[str, Any]:
    if raw is None or not str(raw).strip():
        return default_spec()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CollageSpecError("collage_spec must be JSON") from exc
    if not isinstance(parsed, dict):
        raise CollageSpecError("collage_spec must be an object")
    return normalize_spec(parsed)


def iter_leaves(node: dict[str, Any]) -> list[dict[str, Any]]:
    kind = node.get("type")
    if kind == "leaf":
        return [node]
    if kind == "split":
        return iter_leaves(node["a"]) + iter_leaves(node["b"])
    raise CollageSpecError("invalid layout node")


def leaf_count(spec: dict[str, Any]) -> int:
    return len(iter_leaves(spec["root"]))


def normalize_spec(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CollageSpecError("spec must be an object")
    version = int(raw.get("version") or SPEC_VERSION)
    if version != SPEC_VERSION:
        raise CollageSpecError(f"unsupported collage_spec version: {version}")
    aspect = _normalize_aspect(raw.get("aspect", DEFAULT_ASPECT))
    gap = _normalize_int(raw.get("gap_px", DEFAULT_GAP_PX), 0, MAX_GAP_PX, "gap_px")
    background = _normalize_background(raw.get("background", DEFAULT_BACKGROUND))
    radius = _normalize_int(
        raw.get("corner_radius_px", 0), 0, MAX_CORNER_RADIUS_PX, "corner_radius_px"
    )
    duration = clamp_collage_duration(
        float(raw["duration_s"]) if raw.get("duration_s") is not None else DEFAULT_DURATION_S
    )
    root_raw = raw.get("root")
    if not isinstance(root_raw, dict):
        raise CollageSpecError("root layout is required")
    root = _normalize_node(root_raw, depth=0)
    leaves = iter_leaves(root)
    if len(leaves) > MAX_LEAVES:
        raise CollageSpecError(
            f"too many collage cells ({len(leaves)}); maximum is {MAX_LEAVES}"
        )
    ids = [str(leaf["id"]) for leaf in leaves]
    if len(ids) != len(set(ids)):
        raise CollageSpecError("duplicate leaf ids")
    return {
        "version": SPEC_VERSION,
        "aspect": aspect,
        "gap_px": gap,
        "background": background,
        "corner_radius_px": radius,
        "duration_s": duration,
        "root": root,
    }


def _normalize_node(raw: dict[str, Any], *, depth: int) -> dict[str, Any]:
    if depth > MAX_SPLIT_DEPTH:
        raise CollageSpecError(f"layout deeper than {MAX_SPLIT_DEPTH} splits")
    if not isinstance(raw, dict):
        raise CollageSpecError("layout node must be an object")
    kind = str(raw.get("type") or "").strip().lower()
    if kind == "leaf":
        leaf_id = str(raw.get("id") or new_leaf_id())
        if not _LEAF_ID_RE.match(leaf_id):
            raise CollageSpecError("invalid leaf id")
        node: dict[str, Any] = {"type": "leaf", "id": leaf_id}
        if "media" in raw and raw["media"] is not None:
            node["media"] = _normalize_media(raw["media"])
        return node
    if kind == "split":
        direction = str(raw.get("dir") or "").strip().lower()
        if direction not in {"h", "v"}:
            raise CollageSpecError("split dir must be h or v")
        ratio = float(raw.get("ratio", 0.5))
        if not (MIN_RATIO <= ratio <= MAX_RATIO):
            raise CollageSpecError(
                f"split ratio must be between {MIN_RATIO} and {MAX_RATIO}"
            )
        child_a = raw.get("a")
        child_b = raw.get("b")
        if not isinstance(child_a, dict) or not isinstance(child_b, dict):
            raise CollageSpecError("split requires a and b children")
        split_id = str(raw.get("id") or f"split-{uuid.uuid4().hex[:10]}")
        if not _LEAF_ID_RE.match(split_id):
            raise CollageSpecError("invalid split id")
        return {
            "type": "split",
            "id": split_id,
            "dir": direction,
            "ratio": round(ratio, 6),
            "a": _normalize_node(child_a, depth=depth + 1),
            "b": _normalize_node(child_b, depth=depth + 1),
        }
    raise CollageSpecError("layout node type must be leaf or split")


def _normalize_media(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CollageSpecError("leaf media must be an object")
    source = str(raw.get("source") or "").strip().lower()
    if source not in {"library", "external"}:
        raise CollageSpecError("media source must be library or external")
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in {"photo", "video"}:
        raise CollageSpecError("media kind must be photo or video")
    fit = str(raw.get("fit") or DEFAULT_FIT).strip().lower()
    if fit not in {"fit", "fill"}:
        raise CollageSpecError("media fit must be fit or fill")
    zoom = float(raw.get("zoom", 1.0))
    if not (MIN_ZOOM <= zoom <= MAX_ZOOM):
        raise CollageSpecError(f"zoom must be between {MIN_ZOOM} and {MAX_ZOOM}")
    pan_x = float(raw.get("pan_x", 0.5))
    pan_y = float(raw.get("pan_y", 0.5))
    if not (0.0 <= pan_x <= 1.0 and 0.0 <= pan_y <= 1.0):
        raise CollageSpecError("pan_x/pan_y must be between 0 and 1")
    start_offset = float(raw.get("start_offset_s", 0.0) or 0.0)
    if start_offset < 0 or start_offset > MAX_START_OFFSET_S:
        raise CollageSpecError("start_offset_s out of range")
    out: dict[str, Any] = {
        "source": source,
        "kind": kind,
        "fit": fit,
        "zoom": round(zoom, 4),
        "pan_x": round(pan_x, 6),
        "pan_y": round(pan_y, 6),
        "start_offset_s": round(start_offset, 3),
    }
    if source == "library":
        media_id = raw.get("media_id")
        if media_id is not None:
            # JSON clients may send whole numbers as int or digit strings.
            if isinstance(media_id, bool):
                raise CollageSpecError("media_id must be a positive integer")
            if isinstance(media_id, int):
                parsed_id = media_id
            elif isinstance(media_id, str) and media_id.strip().isdigit():
                parsed_id = int(media_id.strip())
            elif isinstance(media_id, float) and media_id.is_integer():
                parsed_id = int(media_id)
            else:
                raise CollageSpecError("media_id must be a positive integer")
            if parsed_id <= 0:
                raise CollageSpecError("media_id must be a positive integer")
            out["media_id"] = parsed_id
        identity = raw.get("identity_key")
        if identity is not None:
            text = str(identity).strip()
            if not text:
                raise CollageSpecError("identity_key must be non-empty")
            out["identity_key"] = text
        if "media_id" not in out and "identity_key" not in out:
            raise CollageSpecError("library media requires media_id or identity_key")
    else:
        path = str(raw.get("path") or "").strip()
        if not path:
            raise CollageSpecError("external media requires path")
        out["path"] = path
        source_key = str(raw.get("source_key") or "").strip()
        if not source_key:
            source_key = stable_external_source_key(path)
        if not _SOURCE_KEY_RE.match(source_key):
            raise CollageSpecError("invalid source_key")
        out["source_key"] = source_key
        display = str(raw.get("display_name") or "").strip()
        if display:
            out["display_name"] = display[:240]
    if "grade" in raw and raw["grade"] is not None:
        if not isinstance(raw["grade"], dict):
            raise CollageSpecError("grade must be an object")
        out["grade"] = raw["grade"]
    if "crop" in raw and raw["crop"] is not None:
        out["crop"] = _normalize_crop(raw["crop"])
    return out


def _normalize_crop(raw: Any) -> dict[str, float]:
    """Normalized source crop rectangle (free framing viewport)."""
    if not isinstance(raw, dict):
        raise CollageSpecError("crop must be an object")
    try:
        x = float(raw.get("x", 0.0))
        y = float(raw.get("y", 0.0))
        w = float(raw.get("w", 0.0))
        h = float(raw.get("h", 0.0))
    except (TypeError, ValueError) as exc:
        raise CollageSpecError("crop x/y/w/h must be numbers") from exc
    if not (w > 0.0 and h > 0.0):
        raise CollageSpecError("crop w/h must be positive")
    if x < 0.0 or y < 0.0 or x + w > 1.0 + 1e-6 or y + h > 1.0 + 1e-6:
        raise CollageSpecError("crop must stay inside the source (0..1)")
    # Snap into bounds for float noise.
    w = min(w, 1.0 - x)
    h = min(h, 1.0 - y)
    return {
        "x": round(max(0.0, x), 6),
        "y": round(max(0.0, y), 6),
        "w": round(max(1e-6, w), 6),
        "h": round(max(1e-6, h), 6),
    }


def _normalize_aspect(raw: Any) -> str | dict[str, int]:
    if isinstance(raw, str):
        key = raw.strip()
        if key in ASPECT_PRESETS:
            return key
        raise CollageSpecError("aspect must be 16:9, 9:16, 1:1, or custom {w,h}")
    if isinstance(raw, dict):
        w = int(raw.get("w") or 0)
        h = int(raw.get("h") or 0)
        if w < 1 or h < 1 or w > 7680 or h > 7680:
            raise CollageSpecError("custom aspect w/h out of range")
        return {"w": w, "h": h}
    raise CollageSpecError("invalid aspect")


def _normalize_background(raw: Any) -> str:
    if raw is None:
        return DEFAULT_BACKGROUND
    text = str(raw).strip()
    if text.lower() == "transparent":
        return "transparent"
    if _HEX_RE.match(text):
        return text.lower()
    raise CollageSpecError("background must be #RRGGBB, #RRGGBBAA, or transparent")


def _normalize_int(raw: Any, lo: int, hi: int, label: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise CollageSpecError(f"{label} must be an integer") from exc
    if value < lo or value > hi:
        raise CollageSpecError(f"{label} must be between {lo} and {hi}")
    return value


def aspect_size(aspect: str | dict[str, int], *, long_edge: int) -> tuple[int, int]:
    """Return (width, height) for a canvas with the given long edge."""
    edge = max(1, int(long_edge))
    if isinstance(aspect, str):
        aw, ah = ASPECT_PRESETS[aspect]
    else:
        aw, ah = int(aspect["w"]), int(aspect["h"])
    if aw >= ah:
        width = edge
        height = max(1, round(edge * ah / aw))
    else:
        height = edge
        width = max(1, round(edge * aw / ah))
    return width, height


def resolve_rects(spec: dict[str, Any], width: int, height: int) -> dict[str, Rect]:
    """Map leaf ids to integer pixel rects inside the canvas."""
    normalized = normalize_spec(spec)
    w = max(1, int(width))
    h = max(1, int(height))
    gap = int(normalized["gap_px"])
    out: dict[str, Rect] = {}
    _resolve_node(normalized["root"], 0, 0, w, h, gap, out)
    expected = leaf_count(normalized)
    if len(out) != expected:
        raise CollageSpecError(
            f"layout cannot place all cells ({len(out)}/{expected}); "
            "reduce gap or widen splits"
        )
    return out


def _resolve_node(
    node: dict[str, Any],
    x: int,
    y: int,
    w: int,
    h: int,
    gap: int,
    out: dict[str, Rect],
) -> None:
    if w <= 0 or h <= 0:
        raise CollageSpecError(
            "layout does not fit canvas; reduce gap or widen splits"
        )
    if node["type"] == "leaf":
        out[str(node["id"])] = Rect(x=x, y=y, w=w, h=h)
        return
    direction = node["dir"]
    ratio = float(node["ratio"])
    if direction == "h":
        usable = w - gap
        if usable < 2:
            raise CollageSpecError(
                "horizontal split does not fit; reduce gap or widen splits"
            )
        first = max(1, min(usable - 1, round(usable * ratio)))
        second = usable - first
        _resolve_node(node["a"], x, y, first, h, gap, out)
        _resolve_node(node["b"], x + first + gap, y, second, h, gap, out)
        return
    usable = h - gap
    if usable < 2:
        raise CollageSpecError(
            "vertical split does not fit; reduce gap or widen splits"
        )
    first = max(1, min(usable - 1, round(usable * ratio)))
    second = usable - first
    _resolve_node(node["a"], x, y, w, first, gap, out)
    _resolve_node(node["b"], x, y + first + gap, w, second, gap, out)


def set_split_ratio(spec: dict[str, Any], split_id: str, ratio: float) -> dict[str, Any]:
    normalized = normalize_spec(spec)
    found = _set_ratio(normalized["root"], split_id, float(ratio))
    if not found:
        raise CollageSpecError(f"split not found: {split_id}")
    return normalize_spec(normalized)


def _set_ratio(node: dict[str, Any], split_id: str, ratio: float) -> bool:
    if node["type"] == "leaf":
        return False
    if str(node["id"]) == split_id:
        node["ratio"] = max(MIN_RATIO, min(MAX_RATIO, ratio))
        return True
    return _set_ratio(node["a"], split_id, ratio) or _set_ratio(node["b"], split_id, ratio)


def split_leaf(
    spec: dict[str, Any],
    leaf_id: str,
    *,
    direction: str,
    ratio: float = 0.5,
) -> dict[str, Any]:
    normalized = normalize_spec(spec)
    if leaf_count(normalized) >= MAX_LEAVES:
        raise CollageSpecError(f"cannot split; maximum is {MAX_LEAVES} cells")
    direction = direction.strip().lower()
    if direction not in {"h", "v"}:
        raise CollageSpecError("direction must be h or v")

    def _factory(leaf: dict[str, Any]) -> dict[str, Any]:
        return _split(direction, ratio, {**leaf, "id": leaf["id"]}, _leaf())

    root = normalized["root"]
    if root["type"] == "leaf":
        if str(root["id"]) != str(leaf_id):
            raise CollageSpecError(f"leaf not found: {leaf_id}")
        normalized["root"] = _factory(root)
        return normalize_spec(normalized)
    replaced = _replace_leaf(root, leaf_id, _factory)
    if not replaced:
        raise CollageSpecError(f"leaf not found: {leaf_id}")
    return normalize_spec(normalized)


def _band_of_leaves(count: int, *, direction: str) -> dict[str, Any]:
    """Build ``count`` empty leaves in a balanced split tree along ``direction``."""
    n = max(1, int(count))
    nodes: list[dict[str, Any]] = [_leaf() for _ in range(n)]

    def _build(items: list[dict[str, Any]]) -> dict[str, Any]:
        if len(items) == 1:
            return items[0]
        mid = len(items) // 2
        left_items = items[:mid]
        right_items = items[mid:]
        ratio = len(left_items) / max(1, len(items))
        return _split(direction, ratio, _build(left_items), _build(right_items))

    return _build(nodes)


def add_band(
    spec: dict[str, Any],
    *,
    edge: str,
    cells: int = 1,
) -> dict[str, Any]:
    """Wrap the whole collage with a new row or column of empty cells.

    ``edge`` is ``bottom``, ``top``, ``right``, or ``left``. ``cells`` is how
    many empty tiles the new band contains (clamped to remaining leaf budget).
    """
    normalized = normalize_spec(spec)
    current = leaf_count(normalized)
    if current >= MAX_LEAVES:
        raise CollageSpecError(f"cannot add cells; maximum is {MAX_LEAVES}")
    edge_key = str(edge or "").strip().lower()
    if edge_key not in {"bottom", "top", "right", "left"}:
        raise CollageSpecError("edge must be bottom, top, right, or left")
    wanted = max(1, int(cells))
    room = MAX_LEAVES - current
    band_cells = min(wanted, room)
    if band_cells < 1:
        raise CollageSpecError(f"cannot add cells; maximum is {MAX_LEAVES}")

    # New horizontal band (row) chains left→right; vertical band (column) top→bottom.
    if edge_key in {"bottom", "top"}:
        band = _band_of_leaves(band_cells, direction="h")
        # Keep most of the existing layout; new band takes ~28%.
        ratio = 0.72 if edge_key == "bottom" else 0.28
        if edge_key == "bottom":
            normalized["root"] = _split("v", ratio, normalized["root"], band)
        else:
            normalized["root"] = _split("v", ratio, band, normalized["root"])
    else:
        band = _band_of_leaves(band_cells, direction="v")
        ratio = 0.72 if edge_key == "right" else 0.28
        if edge_key == "right":
            normalized["root"] = _split("h", ratio, normalized["root"], band)
        else:
            normalized["root"] = _split("h", ratio, band, normalized["root"])
    return normalize_spec(normalized)


def split_leaf_times(
    spec: dict[str, Any],
    leaf_id: str,
    *,
    direction: str,
    times: int = 1,
) -> dict[str, Any]:
    """Split one leaf repeatedly (e.g. 2 → three cells along that axis)."""
    next_spec = normalize_spec(spec)
    count = max(1, min(8, int(times)))
    target = str(leaf_id)
    for _ in range(count):
        next_spec = split_leaf(next_spec, target, direction=direction)
        # After a split, keep targeting the original leaf id (left/top child).
    return next_spec


def merge_public_media_paths(
    incoming: dict[str, Any], persisted: dict[str, Any]
) -> dict[str, Any]:
    """Restore server-only external paths when a public spec is patched back."""
    persisted_norm = normalize_spec(persisted)
    persisted_by_key: dict[str, dict[str, Any]] = {}
    persisted_by_id: dict[str, dict[str, Any]] = {}
    for leaf in iter_leaves(persisted_norm["root"]):
        media = leaf.get("media")
        if not isinstance(media, dict):
            continue
        persisted_by_id[str(leaf["id"])] = media
        key = str(media.get("source_key") or "").strip()
        if key and media.get("path"):
            persisted_by_key[key] = media

    def _restore(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "leaf":
            media = node.get("media")
            if not isinstance(media, dict) or media.get("source") != "external":
                return
            if media.get("path"):
                media.pop("has_path", None)
                return
            key = str(media.get("source_key") or "").strip()
            prior = persisted_by_key.get(key) if key else None
            if prior is None:
                prior = persisted_by_id.get(str(node.get("id")))
            if isinstance(prior, dict) and prior.get("path"):
                media["path"] = prior["path"]
                if prior.get("source_key") and not media.get("source_key"):
                    media["source_key"] = prior["source_key"]
                if prior.get("display_name") and not media.get("display_name"):
                    media["display_name"] = prior["display_name"]
            media.pop("has_path", None)
            return
        if node.get("type") == "split":
            _restore(node.get("a"))
            _restore(node.get("b"))

    draft = json.loads(json.dumps(incoming))
    if isinstance(draft, dict):
        _restore(draft.get("root"))
    return normalize_spec(draft)


def remove_leaf(spec: dict[str, Any], leaf_id: str) -> dict[str, Any]:
    normalized = normalize_spec(spec)
    if leaf_count(normalized) <= 1:
        raise CollageSpecError("cannot remove the last collage cell")
    new_root, removed = _remove_leaf(normalized["root"], leaf_id)
    if not removed or new_root is None:
        raise CollageSpecError(f"leaf not found: {leaf_id}")
    normalized["root"] = new_root
    return normalize_spec(normalized)


def _replace_leaf(
    node: dict[str, Any],
    leaf_id: str,
    factory,
) -> bool:
    if node["type"] == "leaf":
        return False
    for key in ("a", "b"):
        child = node[key]
        if child["type"] == "leaf" and str(child["id"]) == leaf_id:
            node[key] = factory(child)
            return True
        if _replace_leaf(child, leaf_id, factory):
            return True
    return False


def _remove_leaf(
    node: dict[str, Any], leaf_id: str
) -> tuple[dict[str, Any] | None, bool]:
    if node["type"] == "leaf":
        if str(node["id"]) == leaf_id:
            return None, True
        return node, False
    left, left_hit = _remove_leaf(node["a"], leaf_id)
    if left_hit:
        return (node["b"] if left is None else {**node, "a": left}), True
    right, right_hit = _remove_leaf(node["b"], leaf_id)
    if right_hit:
        return (node["a"] if right is None else {**node, "b": right}), True
    return node, False


def _same_leaf_source(prior: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """True when framing/look patches target the same underlying media."""
    if str(prior.get("source") or "") != str(incoming.get("source") or ""):
        return False
    if str(prior.get("kind") or "") != str(incoming.get("kind") or ""):
        return False
    source = str(incoming.get("source") or "").strip().lower()
    if source == "library":
        if prior.get("media_id") is not None and incoming.get("media_id") is not None:
            return int(prior["media_id"]) == int(incoming["media_id"])
        return str(prior.get("identity_key") or "") == str(
            incoming.get("identity_key") or ""
        ) and bool(prior.get("identity_key") or incoming.get("identity_key"))
    if source == "external":
        prior_key = str(prior.get("source_key") or "").strip()
        next_key = str(incoming.get("source_key") or "").strip()
        if prior_key and next_key:
            return prior_key == next_key
        return str(prior.get("path") or "") == str(incoming.get("path") or "") and bool(
            prior.get("path") or incoming.get("path")
        )
    return False


def _merge_leaf_media_preserve(
    prior: dict[str, Any] | None, incoming: dict[str, Any]
) -> dict[str, Any]:
    """Keep grade/crop across framing patches of the same source.

    ``grade: None`` or ``crop: None`` is an explicit clear. Omitting the key
    preserves the prior value. A different media source replaces everything.
    """
    out = dict(incoming)
    if not isinstance(prior, dict) or not _same_leaf_source(prior, out):
        if out.get("grade") is None:
            out.pop("grade", None)
        if out.get("crop") is None:
            out.pop("crop", None)
        return out
    if "grade" in out:
        if out["grade"] is None:
            out.pop("grade", None)
    elif "grade" in prior:
        out["grade"] = prior["grade"]
    if "crop" in out:
        if out["crop"] is None:
            out.pop("crop", None)
    elif "crop" in prior:
        out["crop"] = prior["crop"]
    return out


def assign_leaf_media(
    spec: dict[str, Any], leaf_id: str, media: dict[str, Any] | None
) -> dict[str, Any]:
    normalized = normalize_spec(spec)
    found = False

    def walk(node: dict[str, Any]) -> None:
        nonlocal found
        if node["type"] == "leaf":
            if str(node["id"]) == leaf_id:
                if media is None:
                    node.pop("media", None)
                else:
                    prior = node.get("media") if isinstance(node.get("media"), dict) else None
                    merged = _merge_leaf_media_preserve(prior, media)
                    node["media"] = _normalize_media(merged)
                found = True
            return
        walk(node["a"])
        walk(node["b"])

    walk(normalized["root"])
    if not found:
        raise CollageSpecError(f"leaf not found: {leaf_id}")
    return normalize_spec(normalized)


def duration_for_video_assign(
    current_duration_s: float | None,
    video_duration_s: float | None,
) -> float | None:
    """If a video is longer than the collage, extend duration to match.

    Returns the clamped duration to apply, or ``None`` when no change is needed.
    Keeps a longer manual collage duration untouched.
    """
    if video_duration_s is None:
        return None
    try:
        video_s = float(video_duration_s)
    except (TypeError, ValueError):
        return None
    if not (video_s > 0):
        return None
    current = (
        float(current_duration_s)
        if current_duration_s is not None
        else DEFAULT_DURATION_S
    )
    if current + 1e-6 >= video_s:
        return None
    return clamp_collage_duration(video_s)


def swap_leaf_media(spec: dict[str, Any], leaf_a: str, leaf_b: str) -> dict[str, Any]:
    normalized = normalize_spec(spec)
    leaves = {str(leaf["id"]): leaf for leaf in iter_leaves(normalized["root"])}
    if leaf_a not in leaves or leaf_b not in leaves:
        raise CollageSpecError("leaf not found for swap")
    media_a = leaves[leaf_a].get("media")
    media_b = leaves[leaf_b].get("media")
    if media_b is None:
        leaves[leaf_a].pop("media", None)
    else:
        leaves[leaf_a]["media"] = dict(media_b)
    if media_a is None:
        leaves[leaf_b].pop("media", None)
    else:
        leaves[leaf_b]["media"] = dict(media_a)
    return normalize_spec(normalized)


def source_window(
    *,
    source_w: int,
    source_h: int,
    cell_w: int,
    cell_h: int,
    fit: str = DEFAULT_FIT,
    zoom: float = 1.0,
    pan_x: float = 0.5,
    pan_y: float = 0.5,
) -> SourceWindow:
    """Compute the normalized source crop for Fit/Fill without distortion."""
    sw = max(1, int(source_w))
    sh = max(1, int(source_h))
    cw = max(1, int(cell_w))
    ch = max(1, int(cell_h))
    z = max(MIN_ZOOM, min(MAX_ZOOM, float(zoom)))
    px = max(0.0, min(1.0, float(pan_x)))
    py = max(0.0, min(1.0, float(pan_y)))
    src_aspect = sw / sh
    cell_aspect = cw / ch
    mode = (fit or DEFAULT_FIT).strip().lower()
    if mode == "fit":
        # Entire source visible; letterbox is outside this window (full frame).
        win_w = 1.0 / z
        win_h = 1.0 / z
    else:
        # Cover cell: window matches cell aspect inside source, then zoom.
        if src_aspect > cell_aspect:
            # source wider → crop horizontally
            base_h = 1.0
            base_w = cell_aspect / src_aspect
        else:
            base_w = 1.0
            base_h = src_aspect / cell_aspect
        win_w = min(1.0, base_w / z)
        win_h = min(1.0, base_h / z)
    win_w = min(1.0, max(1.0 / max(sw, sh), win_w))
    win_h = min(1.0, max(1.0 / max(sw, sh), win_h))
    max_x = max(0.0, 1.0 - win_w)
    max_y = max(0.0, 1.0 - win_h)
    return SourceWindow(x=px * max_x, y=py * max_y, w=win_w, h=win_h)


def media_source_window(
    media: dict[str, Any] | None,
    *,
    source_w: int,
    source_h: int,
    cell_w: int,
    cell_h: int,
) -> SourceWindow:
    """Prefer an explicit free ``crop`` rect; otherwise Fit/Fill zoom/pan."""
    if isinstance(media, dict):
        crop = media.get("crop")
        if isinstance(crop, dict):
            try:
                normalized = _normalize_crop(crop)
            except CollageSpecError:
                normalized = None
            if normalized is not None:
                return SourceWindow(
                    x=float(normalized["x"]),
                    y=float(normalized["y"]),
                    w=float(normalized["w"]),
                    h=float(normalized["h"]),
                )
        fit = str(media.get("fit") or DEFAULT_FIT)
        zoom_raw = media.get("zoom", 1.0)
        pan_x_raw = media.get("pan_x", 0.5)
        pan_y_raw = media.get("pan_y", 0.5)
        try:
            zoom = float(zoom_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            zoom = 1.0
        try:
            pan_x = float(pan_x_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pan_x = 0.5
        try:
            pan_y = float(pan_y_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pan_y = 0.5
        return source_window(
            source_w=source_w,
            source_h=source_h,
            cell_w=cell_w,
            cell_h=cell_h,
            fit=fit,
            zoom=zoom,
            pan_x=pan_x,
            pan_y=pan_y,
        )
    return source_window(
        source_w=source_w,
        source_h=source_h,
        cell_w=cell_w,
        cell_h=cell_h,
    )


def public_collage_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Client-safe spec: strip absolute external paths."""
    normalized = normalize_spec(spec)

    def scrub(node: dict[str, Any]) -> dict[str, Any]:
        if node["type"] == "leaf":
            out = {"type": "leaf", "id": node["id"]}
            media = node.get("media")
            if isinstance(media, dict):
                safe = {k: v for k, v in media.items() if k != "path"}
                if media.get("source") == "external":
                    from pathlib import Path

                    path = str(media.get("path") or "").strip()
                    safe["has_path"] = bool(path and Path(path).is_file())
                    if "display_name" not in safe:
                        safe["display_name"] = "External media"
                out["media"] = safe
            return out
        return {
            "type": "split",
            "id": node["id"],
            "dir": node["dir"],
            "ratio": node["ratio"],
            "a": scrub(node["a"]),
            "b": scrub(node["b"]),
        }

    return {
        "version": normalized["version"],
        "aspect": normalized["aspect"],
        "gap_px": normalized["gap_px"],
        "background": normalized["background"],
        "corner_radius_px": normalized["corner_radius_px"],
        "duration_s": normalized["duration_s"],
        "root": scrub(normalized["root"]),
        "leaf_count": leaf_count(normalized),
        "presets": list(preset_names()),
    }
