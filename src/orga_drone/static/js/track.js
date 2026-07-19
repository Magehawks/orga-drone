/**
 * Shared SRT track ↔ playback helpers (map sync + telemetry overlay).
 */
(function (global) {
  function normalizePoints(raw) {
    return (raw || [])
      .filter((p) => p && typeof p.lat === "number" && typeof p.lon === "number")
      .map((p) => ({
        lat: p.lat,
        lon: p.lon,
        abs_alt:
          typeof p.abs_alt === "number" && Number.isFinite(p.abs_alt) ? p.abs_alt : null,
        rel_alt:
          typeof p.rel_alt === "number" && Number.isFinite(p.rel_alt) ? p.rel_alt : null,
        t: typeof p.t === "number" && Number.isFinite(p.t) ? p.t : null,
      }));
  }

  function hasTimedTrack(points) {
    return points.length > 1 && points.every((p) => p.t !== null);
  }

  function getDuration(player, durationHint, points) {
    if (player && Number.isFinite(player.duration) && player.duration > 0) {
      return player.duration;
    }
    if (Number.isFinite(durationHint) && durationHint > 0) return durationHint;
    if (hasTimedTrack(points)) {
      const last = points[points.length - 1].t;
      if (last > 0) return last;
    }
    return 0;
  }

  /** Fractional track index for a playback time (seconds). */
  function indexForTime(t, points, duration) {
    const n = points.length;
    if (n <= 1) return 0;
    if (hasTimedTrack(points)) {
      if (t <= points[0].t) return 0;
      if (t >= points[n - 1].t) return n - 1;
      let lo = 0;
      let hi = n - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (points[mid].t <= t) lo = mid;
        else hi = mid;
      }
      const t0 = points[lo].t;
      const t1 = points[hi].t;
      const f = t1 > t0 ? (t - t0) / (t1 - t0) : 0;
      return lo + f;
    }
    if (duration <= 0) return 0;
    return Math.max(0, Math.min(1, t / duration)) * (n - 1);
  }

  function positionAt(indexF, points, fallbackLatLon) {
    const n = points.length;
    if (n === 0) return fallbackLatLon;
    if (n === 1) return [points[0].lat, points[0].lon];
    const i0 = Math.max(0, Math.min(n - 1, Math.floor(indexF)));
    const i1 = Math.min(n - 1, i0 + 1);
    const f = indexF - i0;
    const a = points[i0];
    const b = points[i1];
    return [a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f];
  }

  function timeForIndex(index, points, duration) {
    const n = points.length;
    if (n <= 1) return 0;
    const i = Math.max(0, Math.min(n - 1, index));
    if (hasTimedTrack(points)) return points[i].t;
    if (duration <= 0) return 0;
    return (i / (n - 1)) * duration;
  }

  /** Nearest discrete sample for telemetry display. */
  function sampleAt(indexF, points) {
    if (!points.length) return null;
    const i = Math.max(0, Math.min(points.length - 1, Math.round(indexF)));
    return points[i];
  }

  function haversineM(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  function segmentDt(a, b, i0, i1, n, duration) {
    if (a.t !== null && b.t !== null) return b.t - a.t;
    if (duration > 0 && n > 1) return ((i1 - i0) / (n - 1)) * duration;
    return 0;
  }

  /** Ground speed (m/s) along the segment containing indexF, or null. */
  function speedAt(indexF, points, duration) {
    const n = points.length;
    if (n < 2) return null;
    const i0 = Math.max(0, Math.min(n - 2, Math.floor(indexF)));
    const i1 = i0 + 1;
    const a = points[i0];
    const b = points[i1];
    const dt = segmentDt(a, b, i0, i1, n, duration);
    if (dt <= 0) return null;
    const dist = haversineM(a.lat, a.lon, b.lat, b.lon);
    if (!Number.isFinite(dist)) return null;
    return dist / dt;
  }

  global.OrgaTrack = {
    normalizePoints,
    hasTimedTrack,
    getDuration,
    indexForTime,
    positionAt,
    timeForIndex,
    sampleAt,
    speedAt,
    haversineM,
  };
})(window);
