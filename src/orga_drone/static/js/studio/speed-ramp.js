// Pure counterpart of studio_speed_ramp.py. Absolute source seconds survive trims/cuts.
export function parseRamp(value) {
  if (!value || value.v !== 1 || value.interp !== "reciprocal_smoothstep") return null;
  if (!Array.isArray(value.points) || value.points.length < 2 || value.points.length > 5)
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
      point.speed < 0.25 ||
      point.speed > 4
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

export function rampSource(ramp, story, start, end) {
  if (story <= 0) return start;
  if (story >= rampTime(ramp, end) - rampTime(ramp, start)) return end;
  const target = rampTime(ramp, start) + Math.max(0, story);
  let lo = start,
    hi = end;
  for (let i = 0; i < 48; i += 1) {
    const mid = (lo + hi) / 2;
    if (rampTime(ramp, mid) < target) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
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
