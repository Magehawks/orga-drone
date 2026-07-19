(function () {
  const el = document.getElementById("map");
  if (!el || typeof L === "undefined") return;

  const lat = parseFloat(el.dataset.lat);
  const lon = parseFloat(el.dataset.lon);
  if (Number.isNaN(lat) || Number.isNaN(lon)) return;

  let track = [];
  try {
    track = JSON.parse(el.dataset.track || "[]");
  } catch (_) {
    track = [];
  }

  const durationHint = parseFloat(el.dataset.duration || "");
  const points = (track || [])
    .filter((p) => p && typeof p.lat === "number" && typeof p.lon === "number")
    .map((p) => ({
      lat: p.lat,
      lon: p.lon,
      t: typeof p.t === "number" && Number.isFinite(p.t) ? p.t : null,
    }));
  const latlngs = points.map((p) => [p.lat, p.lon]);
  const hasTimedTrack = points.length > 1 && points.every((p) => p.t !== null);

  const map = L.map(el).setView([lat, lon], 15);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);

  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue("--accent").trim() || "#3db8a0";
  const accentDim = css.getPropertyValue("--accent-dim").trim() || accent;
  const onAccent = css.getPropertyValue("--on-accent").trim() || "#fff";

  const playMarker = L.circleMarker([lat, lon], {
    radius: 7,
    color: onAccent,
    weight: 2,
    fillColor: accent,
    fillOpacity: 1,
    interactive: false,
  }).addTo(map);

  let fullLine = null;
  let doneLine = null;

  function getDuration() {
    const player = document.getElementById("media-player");
    if (player && Number.isFinite(player.duration) && player.duration > 0) {
      return player.duration;
    }
    if (Number.isFinite(durationHint) && durationHint > 0) return durationHint;
    if (hasTimedTrack) {
      const last = points[points.length - 1].t;
      if (last > 0) return last;
    }
    return 0;
  }

  /** Fractional track index for a playback time (seconds). */
  function indexForTime(t) {
    const n = points.length;
    if (n <= 1) return 0;
    if (hasTimedTrack) {
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
    const duration = getDuration();
    if (duration <= 0) return 0;
    return Math.max(0, Math.min(1, t / duration)) * (n - 1);
  }

  function positionAt(indexF) {
    const n = points.length;
    if (n === 0) return [lat, lon];
    if (n === 1) return [points[0].lat, points[0].lon];
    const i0 = Math.max(0, Math.min(n - 1, Math.floor(indexF)));
    const i1 = Math.min(n - 1, i0 + 1);
    const f = indexF - i0;
    const a = points[i0];
    const b = points[i1];
    return [a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f];
  }

  function timeForIndex(index) {
    const n = points.length;
    if (n <= 1) return 0;
    const i = Math.max(0, Math.min(n - 1, index));
    if (hasTimedTrack) return points[i].t;
    const duration = getDuration();
    if (duration <= 0) return 0;
    return (i / (n - 1)) * duration;
  }

  function updateAtTime(t) {
    if (points.length < 2) return;
    const idx = indexForTime(t);
    const ll = positionAt(idx);
    playMarker.setLatLng(ll);

    if (doneLine) {
      const iEnd = Math.floor(idx);
      const done = latlngs.slice(0, iEnd + 1);
      if (idx > iEnd) done.push(ll);
      if (done.length < 2) {
        doneLine.setLatLngs([latlngs[0], ll]);
      } else {
        doneLine.setLatLngs(done);
      }
    }
  }

  function nearestIndex(latlng) {
    let best = 0;
    let bestD = Infinity;
    for (let i = 0; i < points.length; i++) {
      const d = map.distance(latlng, L.latLng(points[i].lat, points[i].lon));
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return { index: best, distanceM: bestD };
  }

  function seekFromLatLng(latlng) {
    if (points.length < 2) return;
    const { index, distanceM } = nearestIndex(latlng);
    // Ignore clicks far from the track (meters; hit-area polyline keeps this small).
    if (distanceM > 120) return;
    const player = document.getElementById("media-player");
    const time = timeForIndex(index);
    if (player && Number.isFinite(time)) {
      try {
        player.currentTime = time;
      } catch (_) {}
    }
    updateAtTime(time);
  }

  function onTrackClick(e) {
    L.DomEvent.stopPropagation(e);
    seekFromLatLng(e.latlng);
  }

  if (latlngs.length > 1) {
    fullLine = L.polyline(latlngs, {
      color: accentDim,
      weight: 3,
      opacity: 0.4,
      interactive: false,
    }).addTo(map);

    doneLine = L.polyline([latlngs[0], latlngs[0]], {
      color: accent,
      weight: 4,
      opacity: 1,
      interactive: false,
    }).addTo(map);

    // Wider invisible line for easier click-to-seek
    const hitLine = L.polyline(latlngs, {
      color: accent,
      weight: 18,
      opacity: 0,
      className: "track-hit",
    }).addTo(map);
    hitLine.on("click", onTrackClick);

    map.fitBounds(fullLine.getBounds(), { padding: [24, 24] });
    playMarker.setLatLng(latlngs[0]);
    playMarker.bringToFront();
  }

  const player = document.getElementById("media-player");
  if (player && points.length > 1) {
    const sync = () => updateAtTime(player.currentTime || 0);
    player.addEventListener("timeupdate", sync);
    player.addEventListener("seeked", sync);
    player.addEventListener("loadedmetadata", sync);
    // Quality switch (player.js) keeps the same <video> element — listeners stay valid.
    sync();
  }
})();
