"""Local offline object-proposal via classical LAB-ish flood fill (#539/#540/#550).

No cloud, no ONNX, no required model download. Returns a closed UV polygon
suitable for managed selections; callers persist via upsert_selection.

Multi-seed union and optional connected expand improve coverage on mottled
subjects without a second mask engine.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageFilter

MAX_OBJECT_SEEDS = 16


class ObjectSelectError(ValueError):
    """Raised when an object proposal cannot be produced."""


@dataclass(frozen=True)
class ObjectProposal:
    points: list[list[float]]
    closed: bool
    coverage: float
    method: str
    elapsed_s: float
    proposal_size: tuple[int, int]
    seed_uv: tuple[float, float]
    seeds_uv: tuple[tuple[float, float], ...] = ()
    expand_passes: int = 0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _rgb_to_lab_approx(r: float, g: float, b: float) -> tuple[float, float, float]:
    """Fast perceptual-ish axes without a colorspace dependency.

    Uses luma + opponent chromatic channels scaled similarly to Lab a/b.
    """
    rr, gg, bb = r / 255.0, g / 255.0, b / 255.0
    L = 0.2126 * rr + 0.7152 * gg + 0.0722 * bb
    a = (rr - gg) * 128.0
    bch = (0.5 * (rr + gg) - bb) * 128.0
    return L * 100.0, a, bch


def _chromatic_dist(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> float:
    dL = 0.35 * (a[0] - b[0])
    da = a[1] - b[1]
    db = a[2] - b[2]
    return math.sqrt(dL * dL + da * da + db * db)


def _flood_mask(
    pixels: Sequence[tuple[int, int, int]],
    width: int,
    height: int,
    seed_xy: tuple[int, int],
    tol: float,
) -> list[bool]:
    sx, sy = seed_xy
    seed_lab = _rgb_to_lab_approx(*pixels[sy * width + sx])
    mask = [False] * (width * height)
    stack = [(sx, sy)]
    mask[sy * width + sx] = True
    while stack:
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            idx = ny * width + nx
            if mask[idx]:
                continue
            lab = _rgb_to_lab_approx(*pixels[idx])
            if _chromatic_dist(lab, seed_lab) <= tol:
                mask[idx] = True
                stack.append((nx, ny))
    return mask


def _largest_component(mask: list[bool], width: int, height: int) -> list[bool]:
    visited = [False] * len(mask)
    best: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            idx = y * width + x
            if not mask[idx] or visited[idx]:
                continue
            stack = [(x, y)]
            visited[idx] = True
            cells = [(x, y)]
            while stack:
                cx, cy = stack.pop()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    nidx = ny * width + nx
                    if visited[nidx] or not mask[nidx]:
                        continue
                    visited[nidx] = True
                    stack.append((nx, ny))
                    cells.append((nx, ny))
            if len(cells) > len(best):
                best = cells
    out = [False] * len(mask)
    for x, y in best:
        out[y * width + x] = True
    return out


def _mask_to_image(mask: list[bool], width: int, height: int) -> Image.Image:
    raw = bytes(255 if bit else 0 for bit in mask)
    return Image.frombytes("L", (width, height), raw)


def _image_to_mask(image: Image.Image) -> list[bool]:
    raw = image.tobytes()
    return [value > 127 for value in raw]


def _boundary_ring(mask: list[bool], width: int, height: int) -> list[tuple[float, float]]:
    """Collect boundary pixels in rough clockwise order from top-most seed."""
    boundary: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            if not mask[y * width + x]:
                continue
            edge = False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if nx < 0 or ny < 0 or nx >= width or ny >= height or not mask[ny * width + nx]:
                    edge = True
                    break
            if edge:
                boundary.append((x, y))
    if len(boundary) < 3:
        raise ObjectSelectError("Object proposal has no usable contour")

    # Start at top-most then left-most boundary pixel; walk nearest-neighbour.
    start = min(boundary, key=lambda p: (p[1], p[0]))
    remaining = set(boundary)
    remaining.remove(start)
    ordered = [start]
    current = start
    while remaining:
        cx, cy = current
        nxt = min(remaining, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        # Break long jumps that indicate a disconnected rim.
        if (nxt[0] - cx) ** 2 + (nxt[1] - cy) ** 2 > 25:
            break
        remaining.remove(nxt)
        ordered.append(nxt)
        current = nxt
    if len(ordered) < 3:
        raise ObjectSelectError("Object proposal contour tracing failed")
    return [(float(x), float(y)) for x, y in ordered]


def _perp_dist(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    x, y = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def _douglas_peucker(
    points: Sequence[tuple[float, float]], epsilon: float
) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return list(points)
    start, end = points[0], points[-1]
    idx = -1
    best = 0.0
    for i in range(1, len(points) - 1):
        dist = _perp_dist(points[i], start, end)
        if dist > best:
            best = dist
            idx = i
    if idx >= 0 and best > epsilon:
        left = _douglas_peucker(points[: idx + 1], epsilon)
        right = _douglas_peucker(points[idx:], epsilon)
        return left[:-1] + right
    return [start, end]


def _simplify_closed(
    points: Sequence[tuple[float, float]], max_points: int, width: int, height: int
) -> list[tuple[float, float]]:
    if len(points) <= max_points:
        return list(points)
    # Epsilon in pixel space; grow until under budget.
    epsilon = max(1.0, min(width, height) * 0.004)
    simplified = list(points)
    for _ in range(12):
        simplified = _douglas_peucker(points, epsilon)
        if len(simplified) <= max_points:
            break
        epsilon *= 1.45
    if len(simplified) > max_points:
        step = max(1, len(simplified) // max_points)
        simplified = simplified[::step][:max_points]
    if simplified[0] != simplified[-1]:
        # Ensure ring semantics for consumers that expect first≈last optionally.
        pass
    if len(simplified) < 3:
        raise ObjectSelectError("Simplified contour too small")
    return simplified


def _normalize_seeds(
    u: float,
    v: float,
    seeds: Sequence[Sequence[float]] | None,
) -> list[tuple[float, float]]:
    """Primary ``(u, v)`` plus optional extra seeds; capped and de-duplicated."""
    if not (0.0 <= float(u) <= 1.0 and 0.0 <= float(v) <= 1.0):
        raise ObjectSelectError("u and v must be in [0, 1]")
    out: list[tuple[float, float]] = [(_clamp01(u), _clamp01(v))]
    if seeds:
        if len(seeds) > MAX_OBJECT_SEEDS:
            raise ObjectSelectError(f"At most {MAX_OBJECT_SEEDS} seeds allowed")
        for entry in seeds:
            try:
                su = float(entry[0])
                sv = float(entry[1])
            except (TypeError, ValueError, IndexError) as exc:
                raise ObjectSelectError("Each seed must be [u, v]") from exc
            if not (0.0 <= su <= 1.0 and 0.0 <= sv <= 1.0):
                raise ObjectSelectError("All seeds must be in [0, 1]")
            point = (_clamp01(su), _clamp01(sv))
            if point not in out:
                out.append(point)
            if len(out) > MAX_OBJECT_SEEDS:
                raise ObjectSelectError(f"At most {MAX_OBJECT_SEEDS} seeds allowed")
    return out


def _union_flood_mask(
    pixels: Sequence[tuple[int, int, int]],
    width: int,
    height: int,
    seeds_xy: Sequence[tuple[int, int]],
    tol: float,
) -> list[bool]:
    mask = [False] * (width * height)
    for sx, sy in seeds_xy:
        part = _flood_mask(pixels, width, height, (sx, sy), tol)
        for i, bit in enumerate(part):
            if bit:
                mask[i] = True
    return mask


def _expand_mask_python(
    pixels: Sequence[tuple[int, int, int]],
    mask: list[bool],
    width: int,
    height: int,
    primary_xy: tuple[int, int],
    tol: float,
    passes: int,
) -> list[bool]:
    if passes <= 0:
        return mask
    px, py = primary_xy
    primary = _rgb_to_lab_approx(*pixels[py * width + px])
    out = list(mask)
    for step in range(max(0, int(passes))):
        grow_tol = float(tol) * (1.0 + 0.12 * (step + 1))
        added = False
        for y in range(height):
            for x in range(width):
                idx = y * width + x
                if out[idx]:
                    continue
                touches = False
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height and out[ny * width + nx]:
                        touches = True
                        break
                if not touches:
                    continue
                lab = _rgb_to_lab_approx(*pixels[idx])
                if _chromatic_dist(lab, primary) <= grow_tol:
                    out[idx] = True
                    added = True
        if not added:
            break
    return out


def propose_object_polygon(
    source_path: Path | str,
    u: float,
    v: float,
    *,
    seeds: Sequence[Sequence[float]] | None = None,
    max_edge: int = 640,
    tol: float = 16.0,
    max_points: int = 64,
    expand_passes: int = 2,
) -> ObjectProposal:
    """Propose a closed UV polygon for the connected object under ``(u, v)``.

    Optional ``seeds`` are unioned with the primary click. ``expand_passes``
    grows the seed-connected region into nearby similar colors (#550).
    """
    seed_list = _normalize_seeds(u, v, seeds)
    path = Path(source_path)
    if not path.is_file():
        raise ObjectSelectError("Source media file is missing")
    if expand_passes < 0 or expand_passes > 8:
        raise ObjectSelectError("expand_passes must be 0..8")
    t0 = time.perf_counter()
    with Image.open(path) as src:
        rgb = src.convert("RGB")
        sw, sh = rgb.size
        if sw < 2 or sh < 2:
            raise ObjectSelectError("Source image too small")
        scale = float(max_edge) / float(max(sw, sh))
        if scale < 1.0:
            nw = max(2, int(round(sw * scale)))
            nh = max(2, int(round(sh * scale)))
            work = rgb.resize((nw, nh), Image.Resampling.BILINEAR)
        else:
            work = rgb
            nw, nh = sw, sh
    seeds_xy = [
        (
            int(round(su * (nw - 1))),
            int(round(sv * (nh - 1))),
        )
        for su, sv in seed_list
    ]
    sx, sy = seeds_xy[0]
    method = "lab-flood+morph+lcc+polyline"
    points: list[list[float]]
    coverage: float
    used_expand = int(expand_passes)
    try:
        from orga_drone.studio_object_select_fast import (
            contour_points_uv,
            fast_object_select_enabled,
            propose_mask_fast,
        )

        if fast_object_select_enabled():
            mask_u8, coverage = propose_mask_fast(
                work,
                seed_xy=(sx, sy),
                seeds_xy=seeds_xy,
                tol=float(tol),
                expand_passes=used_expand,
            )
            if coverage < 0.001 or coverage > 0.98:
                raise ObjectSelectError("Object proposal coverage out of usable range")
            points = contour_points_uv(
                mask_u8, max_points=max(3, int(max_points))
            )
            method = "lab-flood+morph+lcc+polyline+opencv"
            if len(seed_list) > 1:
                method += "+multiseed"
            if used_expand > 0:
                method += "+expand"
        else:
            raise RuntimeError("fast path disabled")
    except ObjectSelectError:
        raise
    except Exception:
        raw = work.tobytes()
        pixels = [
            (raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)
        ]
        mask = _union_flood_mask(pixels, nw, nh, seeds_xy, float(tol))
        if used_expand > 0:
            mask = _expand_mask_python(
                pixels, mask, nw, nh, (sx, sy), float(tol), used_expand
            )
        # Light morphological close to bridge thin gaps (veins / noise).
        closed = (
            _mask_to_image(mask, nw, nh)
            .filter(ImageFilter.MaxFilter(5))
            .filter(ImageFilter.MinFilter(5))
        )
        mask = _largest_component(_image_to_mask(closed), nw, nh)
        coverage = sum(1 for bit in mask if bit) / float(nw * nh)
        if coverage < 0.001 or coverage > 0.98:
            raise ObjectSelectError("Object proposal coverage out of usable range")
        ring = _boundary_ring(mask, nw, nh)
        simplified = _simplify_closed(
            ring, max_points=max(3, int(max_points)), width=nw, height=nh
        )
        points = [
            [_clamp01(x / float(nw - 1)), _clamp01(y / float(nh - 1))]
            for x, y in simplified
        ]
        # Drop duplicate closing point if present.
        if len(points) >= 2 and points[0] == points[-1]:
            points = points[:-1]
        method = "lab-flood+morph+lcc+polyline"
        if len(seed_list) > 1:
            method += "+multiseed"
        if used_expand > 0:
            method += "+expand"
    if len(points) < 3:
        raise ObjectSelectError("Object proposal produced fewer than 3 points")
    elapsed = time.perf_counter() - t0
    return ObjectProposal(
        points=points,
        closed=True,
        coverage=float(coverage),
        method=method,
        elapsed_s=float(elapsed),
        proposal_size=(nw, nh),
        seed_uv=seed_list[0],
        seeds_uv=tuple(seed_list),
        expand_passes=used_expand,
    )


def proposal_to_selection(
    proposal: ObjectProposal,
    *,
    selection_id: str,
    name: str | None = None,
) -> dict:
    """Build a managed selection dict for upsert_selection."""
    selection: dict = {
        "id": selection_id,
        "invert": False,
        "overlay": {"visible": True},
        "mask": {
            "combine": "union",
            "leaves": [
                {
                    "type": "polygon",
                    "points": proposal.points,
                    "feather": 0.01,
                    "closed": True,
                }
            ],
        },
        "qualifier": {"type": "none"},
    }
    if name:
        selection["name"] = name
    return selection
