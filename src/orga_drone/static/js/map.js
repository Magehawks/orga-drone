(function () {
  const el = document.getElementById("map");
  if (!el || typeof L === "undefined" || typeof OrgaTrack === "undefined") return;

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
  const points = OrgaTrack.normalizePoints(track);
  const latlngs = points.map((p) => [p.lat, p.lon]);

  const map = L.map(el).setView([lat, lon], 15);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);

  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue("--accent").trim() || "#ff9f0a";
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

  function durationNow() {
    if (window.OrgaFlight && window.OrgaFlight.active) {
      const total = window.OrgaFlight.totalDuration();
      if (total > 0) return total;
    }
    return OrgaTrack.getDuration(
      document.getElementById("media-player"),
      durationHint,
      points
    );
  }

  function playbackTime() {
    if (window.OrgaFlight && window.OrgaFlight.active) {
      return window.OrgaFlight.globalTime();
    }
    const media = document.getElementById("media-player");
    return media ? media.currentTime || 0 : 0;
  }

  function updateAtTime(t) {
    if (points.length < 2) return;
    const idx = OrgaTrack.indexForTime(t, points, durationNow());
    const ll = OrgaTrack.positionAt(idx, points, [lat, lon]);
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
    const time = OrgaTrack.timeForIndex(index, points, durationNow());
    if (!Number.isFinite(time)) return;
    if (window.OrgaFlight && window.OrgaFlight.active) {
      window.OrgaFlight.seekGlobal(time);
    } else {
      const media = document.getElementById("media-player");
      if (media) {
        try {
          media.currentTime = time;
        } catch (_) {}
      }
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
    const sync = () => updateAtTime(playbackTime());
    player.addEventListener("timeupdate", sync);
    player.addEventListener("seeked", sync);
    player.addEventListener("loadedmetadata", sync);
    player.addEventListener("orgaflightchange", sync);
    // Quality switch (player.js) keeps the same <video> element — listeners stay valid.
    sync();
  }
})();
