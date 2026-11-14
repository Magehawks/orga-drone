// Pure counterpart of studio_speed_ramp.py. Absolute source seconds survive trims/cuts.
export const MIN_SPEED = 0.25;
export const MAX_SPEED = 20;
export const MAX_POINTS = 5;
export const MAX_REGIONS = 3;
const REGION_ID = /^[A-Za-z][A-Za-z0-9_-]{0,31}$/;
const PRESETS = {
  slow_fast_slow: [0.5, 4, 0.5],
  fast_slow_fast: [4, 0.5, 4],
  acceleration: [0.5, 4],
  deceleration: [4, 0.5],
};

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function sortedRegions(regions) {
  return [...regions].sort(
    (a, b) => a.start_s - b.start_s || String(a.id).localeCompare(String(b.id))
  );
}

function regionsTime(regions, source) {
  let total = 0;
  let previous = 0;
  for (const region of regions) {
    if (source <= region.start_s) return total + (source - previous);
    total += region.start_s - previous;
    if (source <= region.end_s) {
      return (
        total +
        (curveTime({ points: region.points }, source) -
          curveTime({ points: region.points }, region.start_s))
      );
    }
    total +=
      curveTime({ points: region.points }, region.end_s) -
      curveTime({ points: region.points }, region.start_s);
    previous = region.end_s;
  }
  return total + (source - previous);
}

function regionsSpeed(regions, source) {
  for (const region of regions) {
    if (source >= region.start_s && source <= region.end_s) {
      return curveSpeed({ points: region.points }, source);
    }
  }
  return 1;
}

function parseRegions(value) {
  if (!value || Object.prototype.hasOwnProperty.call(value, "points")) return false;
  if (Object.prototype.hasOwnProperty.call(value, "region")) return false;
  if (
    !Array.isArray(value.regions) ||
    value.regions.length < 1 ||
    value.regions.length > MAX_REGIONS
  ) {
    return false;
  }
  const seen = new Set();
  for (const region of value.regions) {
    if (!region || typeof region !== "object") return false;
    if (typeof region.id !== "string" || !REGION_ID.test(region.id) || seen.has(region.id))
      return false;
    seen.add(region.id);
    if (!finiteNumber(region.start_s) || !finiteNumber(region.end_s)) return false;
    if (region.start_s < 0 || region.end_s - region.start_s < 0.05 - 1e-9) return false;
    if (!validPoints(region.points)) return false;
    for (const point of region.points) {
      if (point.source_s < region.start_s - 1e-6 || point.source_s > region.end_s + 1e-6)
        return false;
    }
  }
  const ordered = sortedRegions(value.regions);
  for (let index = 1; index < ordered.length; index += 1) {
    if (ordered[index].start_s < ordered[index - 1].end_s - 1e-9) return false;
  }
  return true;
}

function validPoints(points) {
  if (!Array.isArray(points) || points.length < 2 || points.length > MAX_POINTS) return false;
  let previous = -Infinity;
  for (const point of points) {
    if (!point || typeof point !== "object") return false;
    if (
      !finiteNumber(point.source_s) ||
      point.source_s < 0 ||
      point.source_s - previous < 0.05 - 1e-9 ||
      !finiteNumber(point.speed) ||
      point.speed < MIN_SPEED ||
      point.speed > MAX_SPEED
    ) {
      return false;
    }
    previous = point.source_s;
  }
  return true;
}

export function parseRamp(value) {
  if (!value || value.interp !== "reciprocal_smoothstep" || (value.v !== 1 && value.v !== 2)) {
    return null;
  }
  if (value.v === 2) return parseRegions(value) ? value : null;
  if (Object.prototype.hasOwnProperty.call(value, "regions")) return null;
  if (!validPoints(value.points)) return null;
  if (Object.prototype.hasOwnProperty.call(value, "region") && value.region !== null) {
    const region = value.region;
    if (!region || typeof region !== "object") return null;
    const start = region.start_s;
    const end = region.end_s;
    if (
      typeof start !== "number" ||
      typeof end !== "number" ||
      !Number.isFinite(start) ||
      !Number.isFinite(end) ||
      start < 0 ||
      end - start < 0.05 - 1e-9
    )
      return null;
    for (const point of value.points) {
      if (point.source_s < start - 1e-6 || point.source_s > end + 1e-6) return null;
    }
  }
  return value;
}

function curveTime(ramp, source) {
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

export function rampTime(ramp, source) {
  if (ramp && ramp.v === 2 && Array.isArray(ramp.regions)) {
    return regionsTime(sortedRegions(ramp.regions), source);
  }
  const region = ramp && ramp.region;
  if (!region) return curveTime(ramp, source);
  if (source <= region.start_s) return source;
  const capped = Math.min(source, region.end_s);
  const interior = curveTime(ramp, capped) - curveTime(ramp, region.start_s);
  if (source <= region.end_s) return region.start_s + interior;
  return region.start_s + interior + (source - region.end_s);
}

function curveSpeed(ramp, source) {
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

export function rampSpeed(ramp, source) {
  if (ramp && ramp.v === 2 && Array.isArray(ramp.regions)) {
    return regionsSpeed(sortedRegions(ramp.regions), source);
  }
  const region = ramp && ramp.region;
  if (region && (source < region.start_s || source > region.end_s)) return 1;
  return curveSpeed(ramp, source);
}

export function rampRegions(ramp) {
  if (!ramp) return [];
  if (ramp.v === 2 && Array.isArray(ramp.regions)) {
    return sortedRegions(ramp.regions).map((region) => ({
      id: region.id,
      start: region.start_s,
      end: region.end_s,
      points: region.points,
    }));
  }
  if (ramp.region && Number.isFinite(ramp.region.start_s) && Number.isFinite(ramp.region.end_s)) {
    return [
      {
        id: "",
        start: ramp.region.start_s,
        end: ramp.region.end_s,
        points: ramp.points,
      },
    ];
  }
  if (Array.isArray(ramp.points) && ramp.points.length >= 2) {
    return [
      {
        id: "",
        start: ramp.points[0].source_s,
        end: ramp.points.at(-1).source_s,
        points: ramp.points,
      },
    ];
  }
  return [];
}

export function rampRegion(ramp) {
  if (
    ramp &&
    ramp.region &&
    Number.isFinite(ramp.region.start_s) &&
    Number.isFinite(ramp.region.end_s)
  ) {
    return { start: ramp.region.start_s, end: ramp.region.end_s };
  }
  return { start: ramp.points[0].source_s, end: ramp.points.at(-1).source_s };
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

/**
 * Move a ramp onto [newStart, newEnd] inside the playable source window.
 * When the span no longer covers the full play range, pin endpoint speeds to 1×
 * so outside the bar plays at normal speed (Slow-bar mental model).
 */
export function remapRampSpan(ramp, newStart, newEnd, { playStart, playEnd, minSpan = 0.05 } = {}) {
  if (!ramp || !Array.isArray(ramp.points) || ramp.points.length < 2) return null;
  if (!Number.isFinite(playStart) || !Number.isFinite(playEnd) || playEnd - playStart < minSpan) {
    return null;
  }
  const oldStart = ramp.points[0].source_s;
  const oldEnd = ramp.points.at(-1).source_s;
  const oldSpan = oldEnd - oldStart;
  if (!(oldSpan > 0) || !Number.isFinite(oldSpan)) return null;

  let start = Number(newStart);
  let end = Number(newEnd);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  start = Math.min(Math.max(playStart, start), playEnd);
  end = Math.min(Math.max(playStart, end), playEnd);
  if (end < start) {
    const swap = start;
    start = end;
    end = swap;
  }
  if (end - start < minSpan) {
    if (end >= playEnd - 1e-9) start = Math.max(playStart, end - minSpan);
    else end = Math.min(playEnd, start + minSpan);
  }
  if (end - start < minSpan) return null;
  start = Number(start.toFixed(2));
  end = Number(end.toFixed(2));
  if (end - start < minSpan) return null;

  const coversFull = start <= playStart + 1e-6 && end >= playEnd - 1e-6;
  let points = ramp.points.map((point) => {
    const u = (point.source_s - oldStart) / oldSpan;
    return {
      source_s: Number((start + u * (end - start)).toFixed(2)),
      speed: point.speed,
    };
  });
  points[0].source_s = start;
  points[points.length - 1].source_s = end;

  if (!coversFull) {
    // Keep the original curve character inside the bar and join to 1× outside.
    // With ≤3 source points we can wrap 1× anchors (max 5). More points: pin ends.
    const innerStart = Number((start + minSpan).toFixed(2));
    const innerEnd = Number((end - minSpan).toFixed(2));
    if (ramp.points.length <= 3 && innerEnd - innerStart >= minSpan) {
      const inner = ramp.points.map((point) => {
        const u = (point.source_s - oldStart) / oldSpan;
        return {
          source_s: Number((innerStart + u * (innerEnd - innerStart)).toFixed(2)),
          speed: point.speed,
        };
      });
      inner[0].source_s = innerStart;
      inner[inner.length - 1].source_s = innerEnd;
      points = [{ source_s: start, speed: 1 }, ...inner, { source_s: end, speed: 1 }];
    } else {
      points[0].speed = 1;
      points[points.length - 1].speed = 1;
    }
  }

  // Keep minimum separation after rounding.
  for (let i = 1; i < points.length; i += 1) {
    const floor = points[i - 1].source_s + minSpan;
    if (points[i].source_s < floor) points[i].source_s = Number(floor.toFixed(2));
  }
  if (points[points.length - 1].source_s > end) {
    points[points.length - 1].source_s = end;
    for (let i = points.length - 2; i >= 0; i -= 1) {
      const ceiling = points[i + 1].source_s - minSpan;
      if (points[i].source_s > ceiling) points[i].source_s = Number(ceiling.toFixed(2));
    }
    points[0].source_s = start;
  }

  const next = { v: 1, interp: "reciprocal_smoothstep", points };
  return parseRamp(next) ? next : null;
}

export function rampMediaTime(ramp, story, start, end, mediaOrigin = 0) {
  return rampSource(ramp, story, start, end) - mediaOrigin;
}

function roundSource(value) {
  return Number(Number(value).toFixed(2));
}

export function placeRampRegion(
  ramp,
  newStart,
  newEnd,
  { playStart, playEnd, minGap = 0.05, regionId = null } = {}
) {
  if (ramp && ramp.v === 2) {
    return placeCurveRegion(ramp, newStart, newEnd, { playStart, playEnd, minGap, regionId });
  }
  if (!ramp || !Array.isArray(ramp.points) || ramp.points.length < 2) return null;
  if (!Number.isFinite(playStart) || !Number.isFinite(playEnd) || !(playEnd > playStart))
    return null;
  const old = rampRegion(ramp);
  const oldSpan = old.end - old.start;
  if (!(oldSpan > 0)) return null;
  let start = Number(newStart);
  let end = Number(newEnd);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  if (end < start) {
    const swap = start;
    start = end;
    end = swap;
  }
  start = Math.min(Math.max(playStart, start), playEnd);
  end = Math.min(Math.max(playStart, end), playEnd);
  const floor = Math.max(minGap, (ramp.points.length - 1) * minGap);
  if (end - start < floor) {
    if (end >= playEnd - 1e-9) start = Math.max(playStart, end - floor);
    else end = Math.min(playEnd, start + floor);
  }
  if (end - start < floor - 1e-9) return null;
  start = roundSource(start);
  end = roundSource(end);
  start = Math.min(Math.max(playStart, start), playEnd);
  end = Math.min(Math.max(playStart, end), playEnd);
  if (end - start < floor - 1e-9) return null;
  const points = ramp.points.map((point) => {
    const fraction = (point.source_s - old.start) / oldSpan;
    return { source_s: roundSource(start + fraction * (end - start)), speed: point.speed };
  });
  points[0].source_s = start;
  points[points.length - 1].source_s = end;
  for (let i = 1; i < points.length; i += 1) {
    const next = roundSource(points[i - 1].source_s + minGap);
    if (points[i].source_s < next) points[i].source_s = next;
  }
  if (points[points.length - 1].source_s > end) {
    points[points.length - 1].source_s = end;
    for (let i = points.length - 2; i >= 0; i -= 1) {
      const ceiling = roundSource(points[i + 1].source_s - minGap);
      if (points[i].source_s > ceiling) points[i].source_s = ceiling;
    }
    points[0].source_s = start;
  }
  const next = {
    v: 1,
    interp: "reciprocal_smoothstep",
    points,
    region: { start_s: start, end_s: end },
  };
  return parseRamp(next) ? next : null;
}

export function rampAfterRegionDrag(
  ramp,
  { mode, deltaStory, playStart, playEnd, regionId = null }
) {
  if (ramp && ramp.v === 2) {
    return dragCurveRegion(ramp, { mode, deltaStory, playStart, playEnd, regionId });
  }
  if (!ramp || (mode !== "move" && mode !== "start" && mode !== "end")) return null;
  const region = rampRegion(ramp);
  const span = region.end - region.start;
  if (!(span > 0)) return null;
  const originLeft = rampTime(ramp, region.start) - rampTime(ramp, playStart);
  const story = rampTime(ramp, region.end) - rampTime(ramp, region.start);
  const rate = story / span;
  const minSpan = Math.max(0.05, (ramp.points.length - 1) * 0.05);
  const playSpan = playEnd - playStart;
  let start;
  let end;
  if (mode === "move") {
    start = playStart + originLeft + Number(deltaStory);
    end = start + span;
    if (span >= playSpan) {
      start = playStart;
      end = playEnd;
    } else {
      if (start < playStart) {
        start = playStart;
        end = playStart + span;
      }
      if (end > playEnd) {
        end = playEnd;
        start = playEnd - span;
      }
    }
  } else if (mode === "start") {
    start = playStart + originLeft + Number(deltaStory);
    end = region.end;
    if (start < playStart) start = playStart;
    if (end - start < minSpan) start = end - minSpan;
    if (start < playStart) return null;
  } else {
    start = region.start;
    end = start + span + Number(deltaStory) / Math.max(rate, 1e-6);
    if (end > playEnd) end = playEnd;
    if (end - start < minSpan) end = start + minSpan;
    if (end > playEnd) return null;
  }
  return placeRampRegion(ramp, start, end, { playStart, playEnd });
}

function cloneRegion(region) {
  return {
    id: region.id,
    start_s: region.start_s,
    end_s: region.end_s,
    points: region.points.map((point) => ({ source_s: point.source_s, speed: point.speed })),
  };
}

function projectRegion(region) {
  return {
    v: 1,
    interp: "reciprocal_smoothstep",
    points: region.points.map((point) => ({ source_s: point.source_s, speed: point.speed })),
    region: { start_s: region.start_s, end_s: region.end_s },
  };
}

function regionSlot(ramp, regionId) {
  const regions = sortedRegions(ramp.regions).map(cloneRegion);
  const index =
    regionId === null || regionId === undefined
      ? regions.length === 1
        ? 0
        : -1
      : regions.findIndex((region) => region.id === regionId);
  return { regions, index };
}

function neighborLimits(regions, index, playStart, playEnd) {
  const lo = index === 0 ? playStart : Math.max(playStart, regions[index - 1].end_s);
  const hi = index === regions.length - 1 ? playEnd : Math.min(playEnd, regions[index + 1].start_s);
  return { lo, hi };
}

function placeCurveRegion(ramp, newStart, newEnd, { playStart, playEnd, minGap, regionId }) {
  const { regions, index } = regionSlot(ramp, regionId);
  if (index < 0) return null;
  const { lo, hi } = neighborLimits(regions, index, playStart, playEnd);
  if (!(hi - lo >= 0.05 - 1e-9)) return null;
  const placed = placeRampRegion(projectRegion(regions[index]), newStart, newEnd, {
    playStart: lo,
    playEnd: hi,
    minGap,
  });
  if (!placed || !placed.region) return null;
  regions[index] = {
    id: regions[index].id,
    start_s: placed.region.start_s,
    end_s: placed.region.end_s,
    points: placed.points,
  };
  const next = { v: 2, interp: "reciprocal_smoothstep", regions };
  return parseRamp(next) ? next : null;
}

function dragCurveRegion(ramp, { mode, deltaStory, playStart, playEnd, regionId }) {
  if (mode !== "move" && mode !== "start" && mode !== "end") return null;
  const { regions, index } = regionSlot(ramp, regionId);
  if (index < 0) return null;
  const region = regions[index];
  const span = region.end_s - region.start_s;
  if (!(span > 0)) return null;
  const { lo, hi } = neighborLimits(regions, index, playStart, playEnd);
  const story = regionsTime(regions, region.end_s) - regionsTime(regions, region.start_s);
  const rate = story / span;
  const minSpan = Math.max(0.05, (region.points.length - 1) * 0.05);
  const delta = Number(deltaStory);
  let start;
  let end;
  if (mode === "move") {
    start = region.start_s + delta;
    end = start + span;
    if (span >= hi - lo - 1e-9) {
      start = lo;
      end = hi;
    } else {
      if (start < lo) {
        start = lo;
        end = lo + span;
      }
      if (end > hi) {
        end = hi;
        start = hi - span;
      }
    }
  } else if (mode === "start") {
    start = region.start_s + delta;
    end = region.end_s;
    if (start < lo) start = lo;
    if (end - start < minSpan) start = end - minSpan;
    if (start < lo) return null;
  } else {
    start = region.start_s;
    end = start + span + delta / Math.max(rate, 1e-6);
    if (end > hi) end = hi;
    if (end - start < minSpan) end = start + minSpan;
    if (end > hi) return null;
  }
  return placeCurveRegion({ v: 2, interp: "reciprocal_smoothstep", regions }, start, end, {
    playStart,
    playEnd,
    minGap: 0.05,
    regionId: region.id,
  });
}

function firstGap(regions, playStart, playEnd, need) {
  if (
    !Number.isFinite(playStart) ||
    !Number.isFinite(playEnd) ||
    playEnd - playStart < need - 1e-9
  ) {
    return null;
  }
  let cursor = playStart;
  for (const region of [...regions].sort((a, b) => a.start_s - b.start_s)) {
    const right = Math.min(region.start_s, playEnd);
    if (right - cursor >= need - 1e-9) return { start: cursor, end: right };
    cursor = Math.max(cursor, region.end_s);
  }
  if (playEnd - cursor >= need - 1e-9) return { start: cursor, end: playEnd };
  return null;
}

function roundUp(value) {
  return Math.ceil(value * 100 - 1e-9) / 100;
}

function roundDown(value) {
  return Math.floor(value * 100 + 1e-9) / 100;
}

function presetPoints(start, end, speeds) {
  const span = end - start;
  const points = speeds.map((speed, index) => ({
    source_s:
      index === 0
        ? start
        : index === speeds.length - 1
          ? end
          : roundSource(start + (span * index) / (speeds.length - 1)),
    speed,
  }));
  for (let index = 1; index < points.length; index += 1) {
    const floor = roundSource(points[index - 1].source_s + 0.05);
    if (points[index].source_s < floor) points[index].source_s = floor;
  }
  if (points[points.length - 1].source_s > end) {
    points[points.length - 1].source_s = end;
    for (let index = points.length - 2; index >= 0; index -= 1) {
      const ceiling = roundSource(points[index + 1].source_s - 0.05);
      if (points[index].source_s > ceiling) points[index].source_s = ceiling;
    }
    points[0].source_s = start;
  }
  return points;
}

function newRegionId(taken) {
  for (let index = 1; index <= MAX_REGIONS; index += 1) {
    const candidate = `r${index}`;
    if (!taken.has(candidate)) return candidate;
  }
  return null;
}

function boundedCurves(ramp) {
  if (ramp.v === 2) return sortedRegions(ramp.regions).map(cloneRegion);
  if (!ramp.region) return null;
  return [
    {
      id: newRegionId(new Set()),
      start_s: ramp.region.start_s,
      end_s: ramp.region.end_s,
      points: ramp.points.map((point) => ({ source_s: point.source_s, speed: point.speed })),
    },
  ];
}

export function addRampRegion(
  ramp,
  { playStart, playEnd, preset = "slow_fast_slow", regionId = null, span = 4 } = {}
) {
  if (!parseRamp(ramp)) return null;
  const speeds = PRESETS[preset];
  if (!speeds) return null;
  const existing = boundedCurves(ramp);
  if (!existing || existing.length >= MAX_REGIONS) return null;
  const need = Math.max(0.1, (speeds.length - 1) * 0.05);
  const gap = firstGap(existing, Number(playStart), Number(playEnd), need);
  if (!gap) return null;
  const length = Math.min(Number(span), gap.end - gap.start);
  let start = roundUp(gap.start);
  let end = roundDown(Math.min(gap.end, start + length));
  if (end - start < need - 1e-9) {
    end = roundDown(gap.end);
    start = roundUp(Math.max(gap.start, end - length));
  }
  if (end - start < need - 1e-9 || start < gap.start - 1e-9 || end > gap.end + 1e-9) return null;
  const taken = new Set(existing.map((region) => region.id));
  const id = regionId === null || regionId === undefined ? newRegionId(taken) : regionId;
  if (!id || taken.has(id) || !REGION_ID.test(id)) return null;
  existing.push({ id, start_s: start, end_s: end, points: presetPoints(start, end, speeds) });
  existing.sort((a, b) => a.start_s - b.start_s || String(a.id).localeCompare(String(b.id)));
  const next = { v: 2, interp: "reciprocal_smoothstep", regions: existing };
  return parseRamp(next) ? next : null;
}

// `null` clears the ramp. `undefined` means the requested region was not removed.
export function removeRampRegion(ramp, regionId) {
  if (!parseRamp(ramp)) return undefined;
  if (ramp.v !== 2) {
    if (!ramp.region || regionId !== "") return undefined;
    return null;
  }
  const kept = sortedRegions(ramp.regions).filter((region) => region.id !== regionId);
  if (kept.length === ramp.regions.length) return undefined;
  if (!kept.length) return null;
  const next = { v: 2, interp: "reciprocal_smoothstep", regions: kept.map(cloneRegion) };
  return parseRamp(next) ? next : undefined;
}
