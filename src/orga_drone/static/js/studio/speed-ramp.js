// Pure counterpart of studio_speed_ramp.py. Absolute source seconds survive trims/cuts.
export const MIN_SPEED = 0.25;
export const MAX_SPEED = 20;
export const MAX_POINTS = 5;

export function parseRamp(value) {
  if (!value || value.v !== 1 || value.interp !== "reciprocal_smoothstep") return null;
  if (!Array.isArray(value.points) || value.points.length < 2 || value.points.length > MAX_POINTS)
    return null;
  let previous = -Infinity;
  for (const point of value.points) {
    if (!point || typeof point !== "object") return null;
    if (
      typeof point.source_s !== "number" ||
      !Number.isFinite(point.source_s) ||
      point.source_s < 0 ||
      point.source_s - previous < 0.05 - 1e-9 ||
      typeof point.speed !== "number" ||
      !Number.isFinite(point.speed) ||
      point.speed < MIN_SPEED ||
      point.speed > MAX_SPEED
    )
      return null;
    previous = point.source_s;
  }
  return value;
}

export function rampTime(ramp, source) {
  const points = ramp.points;
  let total = Math.min(source, points[0].source_s) / points[0].speed;
  if (source <= points[0].source_s) return total;
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1],
      b = points[i];
    const length = b.source_s - a.source_s;
    const u = Math.min(1, (source - a.source_s) / length);
    total += length * (u / a.speed + (1 / b.speed - 1 / a.speed) * (u ** 3 - 0.5 * u ** 4));
    if (source <= b.source_s) return total;
  }
  const last = points.at(-1);
  return total + (source - last.source_s) / last.speed;
}

export function rampSpeed(ramp, source) {
  const points = ramp.points;
  if (source <= points[0].source_s) return points[0].speed;
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1],
      b = points[i];
    if (source <= b.source_s) {
      const u = (source - a.source_s) / (b.source_s - a.source_s);
      return 1 / (1 / a.speed + (1 / b.speed - 1 / a.speed) * (3 * u * u - 2 * u * u * u));
    }
  }
  return points.at(-1).speed;
}

export function rampSourceAtTime(ramp, absoluteStory, lo, hi) {
  // Invert rampTime() against an absolute primitive inside [lo, hi].
  let low = lo,
    high = hi;
  if (high < low) {
    low = hi;
    high = lo;
  }
  const target = absoluteStory;
  if (target <= rampTime(ramp, low)) return low;
  if (target >= rampTime(ramp, high)) return high;
  let left = low,
    right = high;
  for (let i = 0; i < 48; i += 1) {
    const mid = (left + right) / 2;
    if (rampTime(ramp, mid) < target) left = mid;
    else right = mid;
  }
  return (left + right) / 2;
}

export function rampSource(ramp, story, start, end) {
  // story is relative to rampTime(start); do not pass an absolute primitive here.
  return rampSourceAtTime(ramp, rampTime(ramp, start) + Math.max(0, story), start, end);
}

export function edgeSourceAfterRampDrag(
  ramp,
  { edge, sourceIn, sourceOut, deltaStory, repeats = 1, catalog, minSegment = 0.05 }
) {
  if (!(catalog > minSegment)) return { inS: 0, outS: Math.max(0, catalog) };
  const count = Math.max(1, Math.min(8, Math.round(Number(repeats) || 1)));
  const source = edge === "in" ? sourceIn : sourceOut;
  const mapped = rampSourceAtTime(
    ramp,
    rampTime(ramp, source) + Number(deltaStory) / count,
    0,
    catalog
  );
  let start = edge === "in" ? mapped : sourceIn;
  let end = edge === "out" ? mapped : sourceOut;
  start = Math.min(Math.max(0, start), catalog);
  end = Math.min(Math.max(0, end), catalog);
  if (end - start < minSegment) {
    if (edge === "in") start = end - minSegment;
    else end = start + minSegment;
    start = Math.min(Math.max(0, start), catalog);
    end = Math.min(Math.max(0, end), catalog);
    if (end - start < minSegment) {
      if (edge === "in") end = Math.min(catalog, start + minSegment);
      else start = Math.max(0, end - minSegment);
    }
  }
  start = Number(start.toFixed(2));
  end = Number(end.toFixed(2));
  start = Math.min(Math.max(0, start), catalog);
  end = Math.min(Math.max(0, end), catalog);
  if (end - start < minSegment) {
    if (edge === "in") start = Math.max(0, Number((end - minSegment).toFixed(2)));
    else end = Math.min(catalog, Number((start + minSegment).toFixed(2)));
  }
  return { inS: start, outS: end };
}

export function rampPreset(id, start, end) {
  const speeds = {
    slow_fast_slow: [0.5, 4, 0.5],
    fast_slow_fast: [4, 0.5, 4],
    acceleration: [0.5, 4],
    deceleration: [4, 0.5],
  }[id];
  if (!speeds || end - start < 0.1) return null;
  return {
    v: 1,
    interp: "reciprocal_smoothstep",
    points: speeds.map((speed, i) => ({
      source_s: start + ((end - start) * i) / (speeds.length - 1),
      speed,
    })),
  };
}

export function rampMediaTime(ramp, story, start, end, mediaOrigin = 0) {
  return rampSource(ramp, story, start, end) - mediaOrigin;
}
