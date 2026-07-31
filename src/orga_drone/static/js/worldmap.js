(function () {
  const root = document.getElementById("worldmap");
  const mapEl = document.getElementById("world-map");
  const listEl = document.getElementById("map-list");
  const summaryEl = document.getElementById("list-summary");
  const countEl = document.getElementById("map-count");
  const nolocToggle = document.getElementById("show-noloc");
  if (!root || !mapEl) return;

  const t = (key, fallback) => root.dataset[key] || fallback || "";

  if (typeof L === "undefined") {
    if (listEl) {
      listEl.innerHTML = `<p class="hint">${t("i18nEmpty", "Map library failed to load")}</p>`;
    }
    return;
  }

  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue("--accent").trim() || "#ff9f0a";
  const onAccent = css.getPropertyValue("--on-accent").trim() || "#fff";

  let allPoints = [];
  let withoutLoc = [];
  let markersById = new Map();
  let selectedId = null;
  let clusterGroup = null;
  let moveTimer = null;
  let resizeTimer = null;

  const map = L.map(mapEl, { worldCopyJump: true }).setView([20, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);

  function parseReturnView() {
    const sp = new URLSearchParams(window.location.search);
    const lat = parseFloat(sp.get("lat"));
    const lon = parseFloat(sp.get("lon"));
    const zoom = parseFloat(sp.get("zoom"));
    const focusRaw = sp.get("focus") || sp.get("media") || "";
    const focus = parseInt(focusRaw, 10);
    return {
      hasView: Number.isFinite(lat) && Number.isFinite(lon),
      lat,
      lon,
      zoom: Number.isFinite(zoom) ? Math.max(1, Math.min(19, zoom)) : 12,
      focus: Number.isFinite(focus) ? focus : null,
    };
  }

  function mediaDetailUrl(item) {
    const c = map.getCenter();
    const z = map.getZoom();
    const params = new URLSearchParams({
      from: "map",
      lat: c.lat.toFixed(6),
      lon: c.lng.toFixed(6),
      zoom: String(Math.round(z * 100) / 100),
    });
    return `/media/${item.id}?${params}`;
  }

  function markerIcon() {
    return L.divIcon({
      className: "wm-marker",
      html: `<span class="wm-marker-dot" style="background:${accent};border-color:${onAccent}"></span>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
  }

  function inBounds(item, bounds) {
    if (item.lat == null || item.lon == null) return false;
    return bounds.contains(L.latLng(item.lat, item.lon));
  }

  function dayKey(recordedAt) {
    if (!recordedAt) return "—";
    return String(recordedAt).slice(0, 10);
  }

  function placeKey(item, zoom) {
    const lat = Number(item.lat);
    const lon = Number(item.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return "—";
    // Coarser grid when zoomed out → fewer place groups.
    let decimals = 1;
    if (zoom >= 12) decimals = 3;
    else if (zoom >= 9) decimals = 2;
    else if (zoom >= 6) decimals = 1;
    else decimals = 0;
    return `${lat.toFixed(decimals)}, ${lon.toFixed(decimals)}`;
  }

  function groupItems(items, zoom) {
    const byDay = zoom >= 10;
    const groups = new Map();
    for (const item of items) {
      const key = byDay ? dayKey(item.recorded_at) : placeKey(item, zoom);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    const sorted = [...groups.entries()].sort((a, b) => {
      if (byDay) return a[0] < b[0] ? 1 : a[0] > b[0] ? -1 : 0;
      return b[1].length - a[1].length || a[0].localeCompare(b[0]);
    });
    return { mode: byDay ? "day" : "place", groups: sorted };
  }

  function formatMeta(item) {
    const parts = [];
    if (item.recorded_at) parts.push(String(item.recorded_at).replace("T", " ").slice(0, 16));
    if (item.drone_model) parts.push(item.drone_model);
    parts.push(item.kind);
    return parts.join(" · ");
  }

  function renderList() {
    const bounds = map.getBounds();
    const zoom = map.getZoom();
    const visible = allPoints.filter((p) => inBounds(p, bounds));
    const showNoloc = !nolocToggle || nolocToggle.checked;

    if (countEl) {
      countEl.textContent = `${visible.length} / ${allPoints.length} GPS`;
    }
    if (summaryEl) {
      const modeLabel =
        zoom >= 10 ? t("i18nGroupDay", "By day") : t("i18nGroupPlace", "By place");
      summaryEl.textContent = `${t("i18nVisible", "Visible in map")}: ${visible.length} · ${modeLabel}`;
    }

    const frag = document.createDocumentFragment();

    if (!visible.length && !(showNoloc && withoutLoc.length)) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = t("i18nEmpty", "No GPS media in this area");
      frag.appendChild(empty);
    } else {
      const { groups } = groupItems(visible, zoom);
      for (const [label, items] of groups) {
        const section = document.createElement("section");
        section.className = "wm-group";
        const h = document.createElement("h2");
        h.textContent = `${label} (${items.length})`;
        section.appendChild(h);
        const ul = document.createElement("ul");
        ul.className = "wm-items";
        for (const item of items) {
          ul.appendChild(listItem(item, item.id === selectedId));
        }
        section.appendChild(ul);
        frag.appendChild(section);
      }
    }

    if (showNoloc && withoutLoc.length) {
      const section = document.createElement("section");
      section.className = "wm-group wm-group-noloc";
      const h = document.createElement("h2");
      h.textContent = `${t("i18nNoloc", "Without location")} (${withoutLoc.length})`;
      section.appendChild(h);
      const ul = document.createElement("ul");
      ul.className = "wm-items";
      for (const item of withoutLoc) {
        ul.appendChild(listItem(item, false));
      }
      section.appendChild(ul);
      frag.appendChild(section);
    }

    listEl.replaceChildren(frag);
  }

  function listItem(item, active) {
    const li = document.createElement("li");
    li.className = "wm-item" + (active ? " is-active" : "");
    li.dataset.id = String(item.id);

    const a = document.createElement("a");
    a.href = mediaDetailUrl(item);
    a.className = "wm-item-link";

    const thumb = document.createElement("img");
    thumb.src = `/media/${item.id}/thumb`;
    thumb.alt = "";
    thumb.loading = "lazy";
    thumb.decoding = "async";

    const body = document.createElement("div");
    body.className = "wm-item-body";
    const title = document.createElement("strong");
    title.textContent = item.filename;
    const meta = document.createElement("span");
    meta.className = "wm-item-meta";
    meta.textContent = formatMeta(item);
    body.appendChild(title);
    body.appendChild(meta);

    a.appendChild(thumb);
    a.appendChild(body);
    li.appendChild(a);

    if (item.lat != null && item.lon != null) {
      li.addEventListener("mouseenter", () => highlightMarker(item.id, false));
      a.addEventListener("click", (e) => {
        // Allow middle-click / modifier; left-click still navigates.
        if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
          selectedId = item.id;
          highlightMarker(item.id, true);
        }
      });
    }
    return li;
  }

  function highlightMarker(id, pan) {
    selectedId = id;
    const marker = markersById.get(id);
    if (marker && pan) {
      const latlng = marker.getLatLng();
      map.panTo(latlng, { animate: true });
      if (clusterGroup && clusterGroup.zoomToShowLayer) {
        clusterGroup.zoomToShowLayer(marker, () => {
          marker.openPopup();
        });
      } else {
        marker.openPopup();
      }
    }
    listEl.querySelectorAll(".wm-item.is-active").forEach((el) => el.classList.remove("is-active"));
    const row = listEl.querySelector(`.wm-item[data-id="${id}"]`);
    if (row) {
      row.classList.add("is-active");
      row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  function buildMarkers(opts) {
    const skipFit = Boolean(opts && opts.skipFit);
    markersById = new Map();
    if (clusterGroup) {
      map.removeLayer(clusterGroup);
    }
    if (typeof L.markerClusterGroup === "function") {
      clusterGroup = L.markerClusterGroup({
        showCoverageOnHover: false,
        maxClusterRadius: (zoom) => {
          if (zoom <= 4) return 80;
          if (zoom <= 8) return 55;
          if (zoom <= 12) return 40;
          return 28;
        },
        spiderfyOnMaxZoom: true,
        disableClusteringAtZoom: 18,
      });
    } else {
      clusterGroup = L.layerGroup();
    }

    const bounds = [];
    for (const item of allPoints) {
      if (item.lat == null || item.lon == null) continue;
      const m = L.marker([item.lat, item.lon], { icon: markerIcon(), title: item.filename });
      m.bindPopup(
        `<strong>${escapeHtml(item.filename)}</strong><br>` +
          `<a href="${mediaDetailUrl(item)}">${escapeHtml(t("i18nOpen", "Open"))}</a>`
      );
      m.on("click", () => {
        selectedId = item.id;
        renderList();
        highlightMarker(item.id, false);
      });
      // Refresh popup link with current viewport when opened (center may have moved).
      m.on("popupopen", () => {
        const el = m.getPopup() && m.getPopup().getElement();
        if (!el) return;
        const link = el.querySelector("a");
        if (link) link.href = mediaDetailUrl(item);
      });
      clusterGroup.addLayer(m);
      markersById.set(item.id, m);
      bounds.push([item.lat, item.lon]);
    }
    map.addLayer(clusterGroup);
    if (!skipFit) {
      if (bounds.length === 1) {
        map.setView(bounds[0], 12);
      } else if (bounds.length > 1) {
        map.fitBounds(bounds, { padding: [36, 36], maxZoom: 12 });
      }
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function scheduleRender() {
    clearTimeout(moveTimer);
    moveTimer = setTimeout(renderList, 120);
  }

  map.on("moveend", scheduleRender);
  map.on("zoomend", scheduleRender);
  if (nolocToggle) {
    nolocToggle.addEventListener("change", renderList);
  }

  async function load() {
    const returnView = parseReturnView();
    listEl.innerHTML = `<p class="hint">${escapeHtml(t("i18nLoading", "Loading…"))}</p>`;
    try {
      const resp = await fetch("/api/geo/media?include_noloc=1");
      if (!resp.ok) throw new Error("geo fetch failed");
      const data = await resp.json();
      allPoints = Array.isArray(data.items) ? data.items : [];
      withoutLoc = Array.isArray(data.without_location) ? data.without_location : [];
      const restore =
        returnView.hasView || returnView.focus != null;
      buildMarkers({ skipFit: restore });
      if (returnView.hasView) {
        map.setView([returnView.lat, returnView.lon], returnView.zoom, { animate: false });
      } else if (returnView.focus != null) {
        const marker = markersById.get(returnView.focus);
        if (marker) {
          map.setView(marker.getLatLng(), 14, { animate: false });
        }
      }
      if (returnView.focus != null) {
        selectedId = returnView.focus;
        const marker = markersById.get(returnView.focus);
        if (marker && clusterGroup && clusterGroup.zoomToShowLayer) {
          clusterGroup.zoomToShowLayer(marker, () => {
            marker.openPopup();
          });
        } else if (marker) {
          marker.openPopup();
        }
      }
      renderList();
      // Invalidate size after layout (desktop split / mobile stack).
      requestAnimationFrame(() => {
        map.invalidateSize();
        setTimeout(() => map.invalidateSize(), 120);
      });
    } catch (err) {
      listEl.innerHTML = `<p class="hint">${escapeHtml(String(err.message || err))}</p>`;
    }
  }

  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      map.invalidateSize();
      renderList();
    }, 150);
  });

  load();
})();
