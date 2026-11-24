"""Independent ScopeFrameV1 reference accumulation (#364 / #366).

Pure Python math mirroring ADR 0035 / COLOR_WORKSPACE_CONTRACT scope-tap
formulas. Kept separate from production JS so incorrect bin counts, stale
identity assumptions, or legal-range double-expansion fail CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

LUMA_R = 0.2126
LUMA_G = 0.7152
LUMA_B = 0.0722
VECTORSCOPE_CB_SCALE = 1.8556
VECTORSCOPE_CR_SCALE = 1.5748

COLOR_BAR_RGB: tuple[tuple[float, float, float], ...] = (
    (1.0, 1.0, 1.0),
    (1.0, 1.0, 0.0),
    (0.0, 1.0, 1.0),
    (0.0, 1.0, 0.0),
    (1.0, 0.0, 1.0),
    (1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0),
)


def clamp01(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return float(value)


def expand_legal_range(code: float) -> float:
    """Expand limited-range video codes to full [0,1] exactly once."""
    return clamp01((code - 16.0 / 255.0) / ((235.0 - 16.0) / 255.0))


def luma_y(r: float, g: float, b: float) -> float:
    return LUMA_R * r + LUMA_G * g + LUMA_B * b


def histogram_bin(code: float) -> int:
    return min(255, int(256 * clamp01(code)))


def vectorscope_cb_cr(r: float, g: float, b: float) -> tuple[float, float, float]:
    y = luma_y(r, g, b)
    return ((b - y) / VECTORSCOPE_CB_SCALE, (r - y) / VECTORSCOPE_CR_SCALE, y)


@dataclass(frozen=True)
class ScopePixel:
    r: float
    g: float
    b: float
    a: float
    x: int
    y: int


@dataclass(frozen=True)
class ScopeFrameRef:
    width: int
    height: int
    rgba: Sequence[float]
    sample_factor: int = 1
    legal_range: bool = False
    roi: tuple[int, int, int, int] | None = None  # x, y, w, h


def _roi(frame: ScopeFrameRef) -> tuple[int, int, int, int]:
    if frame.roi is None:
        return (0, 0, frame.width, frame.height)
    return frame.roi


def iter_weighted_samples(frame: ScopeFrameRef) -> Iterable[tuple[ScopePixel, float]]:
    x0, y0, rw, rh = _roi(frame)
    step = max(1, int(round(frame.sample_factor)))
    channels = 4
    for y in range(y0, y0 + rh, step):
        for x in range(x0, x0 + rw, step):
            i = (y * frame.width + x) * channels
            r = float(frame.rgba[i])
            g = float(frame.rgba[i + 1])
            b = float(frame.rgba[i + 2])
            a = float(frame.rgba[i + 3]) if len(frame.rgba) > i + 3 else 1.0
            if frame.legal_range:
                r = expand_legal_range(r)
                g = expand_legal_range(g)
                b = expand_legal_range(b)
            r, g, b, a = clamp01(r), clamp01(g), clamp01(b), clamp01(a)
            if a <= 0.0:
                continue
            yield ScopePixel(r, g, b, a, x, y), a


def accumulate_histogram(frame: ScopeFrameRef) -> dict:
    r = [0.0] * 256
    g = [0.0] * 256
    b = [0.0] * 256
    luma = [0.0] * 256
    weight_sum = 0.0
    samples = 0
    for pixel, weight in iter_weighted_samples(frame):
        weight_sum += weight
        samples += 1
        r[histogram_bin(pixel.r)] += weight
        g[histogram_bin(pixel.g)] += weight
        b[histogram_bin(pixel.b)] += weight
        luma[histogram_bin(luma_y(pixel.r, pixel.g, pixel.b))] += weight
    return {
        "bins": 256,
        "absolute": {"r": r, "g": g, "b": b, "luma": luma},
        "weight_sum": weight_sum,
        "sample_count": samples,
        "sample_factor": max(1, int(round(frame.sample_factor))),
    }


def accumulate_waveform(
    frame: ScopeFrameRef, *, columns: int = 32, rows: int = 32
) -> dict:
    density = [0.0] * (columns * rows)
    weight_sum = 0.0
    x0, _y0, rw, _rh = _roi(frame)
    for pixel, weight in iter_weighted_samples(frame):
        weight_sum += weight
        xn = (pixel.x - x0 + 0.5) / rw
        yn = luma_y(pixel.r, pixel.g, pixel.b)
        col = min(columns - 1, max(0, int(xn * columns)))
        row = min(rows - 1, max(0, int(yn * rows)))
        density[row * columns + col] += weight
    return {
        "columns": columns,
        "rows": rows,
        "density": density,
        "weight_sum": weight_sum,
        "axis": {"x": "normalized_source_x", "y": "Y_prime_bt709"},
    }


def accumulate_rgb_parade(
    frame: ScopeFrameRef, *, columns: int = 16, rows: int = 16
) -> dict:
    panels = {ch: [0.0] * (columns * rows) for ch in ("r", "g", "b")}
    weight_sum = 0.0
    x0, _y0, rw, _rh = _roi(frame)
    for pixel, weight in iter_weighted_samples(frame):
        weight_sum += weight
        xn = (pixel.x - x0 + 0.5) / rw
        col = min(columns - 1, max(0, int(xn * columns)))

        def add(plane: list[float], value: float) -> None:
            row = min(rows - 1, max(0, int(clamp01(value) * rows)))
            plane[row * columns + col] += weight

        add(panels["r"], pixel.r)
        add(panels["g"], pixel.g)
        add(panels["b"], pixel.b)
    return {
        "columns": columns,
        "rows": rows,
        "panels": panels,
        "weight_sum": weight_sum,
        "channels": ["R_prime", "G_prime", "B_prime"],
    }


def accumulate_vectorscope(frame: ScopeFrameRef, *, size: int = 64) -> dict:
    density = [0.0] * (size * size)
    weight_sum = 0.0
    for pixel, weight in iter_weighted_samples(frame):
        weight_sum += weight
        cb, cr, _y = vectorscope_cb_cr(pixel.r, pixel.g, pixel.b)
        col = min(size - 1, max(0, int((cb + 0.5) * size)))
        row = min(size - 1, max(0, int((0.5 - cr) * size)))
        density[row * size + col] += weight
    return {
        "size": size,
        "density": density,
        "weight_sum": weight_sum,
        "axis": {
            "encoding": "bt709_encoded_opponent",
            "range": [-0.5, 0.5],
            "x_increases": "right",
            "y_increases": "up",
        },
    }


def solid_frame(
    width: int,
    height: int,
    rgb: tuple[float, float, float],
    *,
    alpha: float = 1.0,
    sample_factor: int = 1,
    legal_range: bool = False,
) -> ScopeFrameRef:
    rgba: list[float] = []
    for _ in range(width * height):
        rgba.extend([rgb[0], rgb[1], rgb[2], alpha])
    return ScopeFrameRef(
        width=width,
        height=height,
        rgba=rgba,
        sample_factor=sample_factor,
        legal_range=legal_range,
    )


def color_bar_frame(width: int = 280, height: int = 160) -> ScopeFrameRef:
    bars = COLOR_BAR_RGB
    rgba: list[float] = []
    for _y in range(height):
        for x in range(width):
            bar = bars[min(len(bars) - 1, int(x * len(bars) / width))]
            rgba.extend([bar[0], bar[1], bar[2], 1.0])
    return ScopeFrameRef(width=width, height=height, rgba=rgba)


def color_bar_vectorscope_targets() -> list[dict]:
    out: list[dict] = []
    for rgb in COLOR_BAR_RGB:
        cb, cr, y = vectorscope_cb_cr(*rgb)
        out.append({"rgb": rgb, "cb": cb, "cr": cr, "y": y})
    return out
