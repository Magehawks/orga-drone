/**
 * Reference ScopeFrameV1 accumulation (ADR 0035).
 * Pure math only — no DOM, no render plan mutation.
 */

export const LUMA_COEFF = Object.freeze({ r: 0.2126, g: 0.7152, b: 0.0722 });
export const VECTORSCOPE_CB_SCALE = 1.8556;
export const VECTORSCOPE_CR_SCALE = 1.5748;

function clamp01(value) {
  if (value <= 0) return 0;
  if (value >= 1) return 1;
  return value;
}

/** Expand limited-range video codes to full [0,1] once. */
export function expandLegalRange(code) {
  return clamp01((code - 16 / 255) / ((235 - 16) / 255));
}

export function lumaY(r, g, b) {
  return LUMA_COEFF.r * r + LUMA_COEFF.g * g + LUMA_COEFF.b * b;
}

export function histogramBin(code) {
  return Math.min(255, Math.floor(256 * clamp01(code)));
}

export function vectorscopeCbCr(r, g, b) {
  const y = lumaY(r, g, b);
  return {
    cb: (b - y) / VECTORSCOPE_CB_SCALE,
    cr: (r - y) / VECTORSCOPE_CR_SCALE,
    y,
  };
}

function sampleStep(sampleFactor) {
  const step = Math.max(1, Math.round(Number(sampleFactor) || 1));
  return step;
}

function readPixel(frame, x, y) {
  const index = y * frame.stride + x * frame.channels;
  let r = frame.rgb[index];
  let g = frame.rgb[index + 1];
  let b = frame.rgb[index + 2];
  const a = frame.channels > 3 ? frame.rgb[index + 3] : 1;
  if (frame.legalRange) {
    r = expandLegalRange(r);
    g = expandLegalRange(g);
    b = expandLegalRange(b);
  }
  return { r: clamp01(r), g: clamp01(g), b: clamp01(b), a: clamp01(a) };
}

function forEachWeightedSample(frame, visit) {
  const { roi } = frame;
  const step = sampleStep(frame.sampleFactor);
  let visited = 0;
  for (let y = roi.y; y < roi.y + roi.height; y += step) {
    for (let x = roi.x; x < roi.x + roi.width; x += step) {
      const pixel = readPixel(frame, x, y);
      if (pixel.a <= 0) continue;
      visit(pixel, x, y, pixel.a);
      visited += 1;
    }
  }
  return { visited, step };
}

export function accumulateHistogram(frame) {
  const r = new Float64Array(256);
  const g = new Float64Array(256);
  const b = new Float64Array(256);
  const luma = new Float64Array(256);
  let weightSum = 0;
  const meta = forEachWeightedSample(frame, (pixel, _x, _y, weight) => {
    weightSum += weight;
    r[histogramBin(pixel.r)] += weight;
    g[histogramBin(pixel.g)] += weight;
    b[histogramBin(pixel.b)] += weight;
    luma[histogramBin(lumaY(pixel.r, pixel.g, pixel.b))] += weight;
  });
  const normalize = (bins) => {
    const out = new Float64Array(256);
    if (weightSum <= 0) return out;
    for (let i = 0; i < 256; i += 1) out[i] = bins[i] / weightSum;
    return out;
  };
  return Object.freeze({
    kind: "histogram",
    bins: 256,
    absolute: Object.freeze({ r, g, b, luma }),
    normalized: Object.freeze({
      r: normalize(r),
      g: normalize(g),
      b: normalize(b),
      luma: normalize(luma),
    }),
    weightSum,
    sampleFactor: meta.step,
    sampleCount: meta.visited,
  });
}

/**
 * Waveform: x = normalized source x in ROI, y = Y' (0 black … 1 white).
 * Density accumulates sample weight into a fixed grid for display/tests.
 */
export function accumulateWaveform(frame, { columns = 256, rows = 256 } = {}) {
  const density = new Float64Array(columns * rows);
  let weightSum = 0;
  const meta = forEachWeightedSample(frame, (pixel, x, _y, weight) => {
    weightSum += weight;
    const xn = (x - frame.roi.x + 0.5) / frame.roi.width;
    const yn = lumaY(pixel.r, pixel.g, pixel.b);
    const col = Math.min(columns - 1, Math.max(0, Math.floor(xn * columns)));
    const row = Math.min(rows - 1, Math.max(0, Math.floor(yn * rows)));
    density[row * columns + col] += weight;
  });
  return Object.freeze({
    kind: "waveform",
    channel: "luma",
    columns,
    rows,
    density,
    weightSum,
    sampleFactor: meta.step,
    sampleCount: meta.visited,
    axis: Object.freeze({
      x: "normalized_source_x",
      y: "Y_prime_bt709",
      yRange: Object.freeze([0, 1]),
    }),
  });
}

/** RGB parade: three panels with the same x mapping and R'/G'/B' as vertical axes. */
export function accumulateRgbParade(frame, { columns = 256, rows = 256 } = {}) {
  const make = () => new Float64Array(columns * rows);
  const panels = Object.freeze({ r: make(), g: make(), b: make() });
  let weightSum = 0;
  const meta = forEachWeightedSample(frame, (pixel, x, _y, weight) => {
    weightSum += weight;
    const xn = (x - frame.roi.x + 0.5) / frame.roi.width;
    const col = Math.min(columns - 1, Math.max(0, Math.floor(xn * columns)));
    const add = (plane, value) => {
      const row = Math.min(rows - 1, Math.max(0, Math.floor(clamp01(value) * rows)));
      plane[row * columns + col] += weight;
    };
    add(panels.r, pixel.r);
    add(panels.g, pixel.g);
    add(panels.b, pixel.b);
  });
  return Object.freeze({
    kind: "rgb-parade",
    columns,
    rows,
    panels,
    weightSum,
    sampleFactor: meta.step,
    sampleCount: meta.visited,
    axis: Object.freeze({
      x: "normalized_source_x",
      y: "channel_code_bt709",
      yRange: Object.freeze([0, 1]),
      channels: Object.freeze(["R_prime", "G_prime", "B_prime"]),
    }),
  });
}

/**
 * Vectorscope: Cb right, Cr up, both in [-0.5, 0.5] from BT.709 encoded RGB.
 */
export function accumulateVectorscope(frame, { size = 256 } = {}) {
  const density = new Float64Array(size * size);
  let weightSum = 0;
  const meta = forEachWeightedSample(frame, (pixel, _x, _y, weight) => {
    weightSum += weight;
    const { cb, cr } = vectorscopeCbCr(pixel.r, pixel.g, pixel.b);
    const u = (cb + 0.5) * size;
    const v = (0.5 - cr) * size; // Cr up → smaller row index
    const col = Math.min(size - 1, Math.max(0, Math.floor(u)));
    const row = Math.min(size - 1, Math.max(0, Math.floor(v)));
    density[row * size + col] += weight;
  });
  return Object.freeze({
    kind: "vectorscope",
    size,
    density,
    weightSum,
    sampleFactor: meta.step,
    sampleCount: meta.visited,
    axis: Object.freeze({
      x: "Cb_bt709",
      y: "Cr_bt709",
      xIncreases: "right",
      yIncreases: "up",
      range: Object.freeze([-0.5, 0.5]),
      encoding: "bt709_encoded_opponent",
      formulas: Object.freeze({
        Y: "0.2126*R'+0.7152*G'+0.0722*B'",
        Cb: "(B'-Y')/1.8556",
        Cr: "(R'-Y')/1.5748",
      }),
    }),
  });
}

/** log1p density normalized to the peak count — display only. */
export function normalizeDensityLog1p(density) {
  let peak = 0;
  for (let i = 0; i < density.length; i += 1) {
    if (density[i] > peak) peak = density[i];
  }
  const out = new Float64Array(density.length);
  if (peak <= 0) return out;
  const denom = Math.log1p(peak);
  for (let i = 0; i < density.length; i += 1) {
    out[i] = Math.log1p(density[i]) / denom;
  }
  return out;
}

export function accumulateAllScopes(frame, options = {}) {
  return Object.freeze({
    histogram: accumulateHistogram(frame),
    waveform: accumulateWaveform(frame, options.waveform),
    parade: accumulateRgbParade(frame, options.parade),
    vectorscope: accumulateVectorscope(frame, options.vectorscope),
  });
}
