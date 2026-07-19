/**
 * Live SRT telemetry overlay synced to video playback (same index logic as map).
 */
(function () {
  const root = document.getElementById("telemetry-overlay");
  const player = document.getElementById("media-player");
  if (!root || !player || typeof OrgaTrack === "undefined") return;

  let track = [];
  try {
    track = JSON.parse(root.dataset.track || "[]");
  } catch (_) {
    track = [];
  }

  const points = OrgaTrack.normalizePoints(track);
  if (!points.length) {
    root.hidden = true;
    return;
  }

  const durationHint = parseFloat(root.dataset.duration || "");
  const elAbs = root.querySelector("[data-field='abs_alt']");
  const elRel = root.querySelector("[data-field='rel_alt']");
  const elSpeed = root.querySelector("[data-field='speed']");

  function formatAlt(m) {
    if (m === null || m === undefined || !Number.isFinite(m)) return "—";
    return m.toFixed(1) + " m";
  }

  function formatSpeed(ms) {
    if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return "—";
    const kmh = ms * 3.6;
    return kmh.toFixed(1) + " km/h";
  }

  function durationNow() {
    if (window.OrgaFlight && window.OrgaFlight.active) {
      const total = window.OrgaFlight.totalDuration();
      if (total > 0) return total;
    }
    return OrgaTrack.getDuration(player, durationHint, points);
  }

  function playbackTime() {
    if (window.OrgaFlight && window.OrgaFlight.active) {
      return window.OrgaFlight.globalTime();
    }
    return player.currentTime || 0;
  }

  function update() {
    const t = playbackTime();
    const duration = durationNow();
    const idx = OrgaTrack.indexForTime(t, points, duration);
    const sample = OrgaTrack.sampleAt(idx, points);
    if (elAbs) elAbs.textContent = formatAlt(sample ? sample.abs_alt : null);
    if (elRel) elRel.textContent = formatAlt(sample ? sample.rel_alt : null);
    if (elSpeed) elSpeed.textContent = formatSpeed(OrgaTrack.speedAt(idx, points, duration));
  }

  root.hidden = false;
  player.addEventListener("timeupdate", update);
  player.addEventListener("seeked", update);
  player.addEventListener("loadedmetadata", update);
  player.addEventListener("orgaflightchange", update);
  update();
})();
