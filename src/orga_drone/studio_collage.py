"""Studio Collage layout model and persistence helpers (ADR 0038)."""

from __future__ import annotations

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
    else:
        raise CollageSpecError(f"unknown collage preset: {name}")
    return normalize_spec(_blank_spec(root=root))


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
            if not isinstance(media_id, int) or isinstance(media_id, bool) or media_id <= 0:
                raise CollageSpecError("media_id must be a positive integer")
            out["media_id"] = int(media_id)
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
        display = str(raw.get("display_name") or "").strip()
        if display:
            out["display_name"] = display[:240]
    if "grade" in raw and raw["grade"] is not None:
        if not isinstance(raw["grade"], dict):
            raise CollageSpecError("grade must be an object")
        out["grade"] = raw["grade"]
    return out


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
        return
    if node["type"] == "leaf":
        out[str(node["id"])] = Rect(x=x, y=y, w=w, h=h)
        return
    direction = node["dir"]
    ratio = float(node["ratio"])
    if direction == "h":
        usable = w - gap
        if usable <= 1:
            _resolve_node(node["a"], x, y, w, h, gap, out)
            return
        first = max(1, min(usable - 1, round(usable * ratio)))
        second = usable - first
        _resolve_node(node["a"], x, y, first, h, gap, out)
        _resolve_node(node["b"], x + first + gap, y, second, h, gap, out)
        return
    usable = h - gap
    if usable <= 1:
        _resolve_node(node["a"], x, y, w, h, gap, out)
        return
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
    replaced = _replace_leaf(
        normalized["root"],
        leaf_id,
        lambda leaf: _split(direction, ratio, {**leaf, "id": leaf["id"]}, _leaf()),
    )
    if not replaced:
        raise CollageSpecError(f"leaf not found: {leaf_id}")
    return normalize_spec(normalized)


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
                    node["media"] = _normalize_media(media)
                found = True
            return
        walk(node["a"])
        walk(node["b"])

    walk(normalized["root"])
    if not found:
        raise CollageSpecError(f"leaf not found: {leaf_id}")
    return normalize_spec(normalized)


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
                    safe["has_path"] = True
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
