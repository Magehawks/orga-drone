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

  const map = L.map(el).setView([lat, lon], 15);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);

  L.marker([lat, lon]).addTo(map);

  const latlngs = (track || [])
    .filter((p) => p && typeof p.lat === "number" && typeof p.lon === "number")
    .map((p) => [p.lat, p.lon]);

  if (latlngs.length > 1) {
    const line = L.polyline(latlngs, { color: "#3db8a0", weight: 3 }).addTo(map);
    map.fitBounds(line.getBounds(), { padding: [24, 24] });
  }
})();
