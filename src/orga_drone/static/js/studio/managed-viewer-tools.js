/** Viewer eyedropper + brush stroke capture for managed selections (#356/#357). */

/**
 * Map a pointer event on the preview media box to normalized source UV [0,1].
 * Accounts for ``object-fit: contain`` letterboxing when intrinsic size is known.
 * Returns null when the point is outside the painted picture.
 */
export function pointerToSourceUv(event, mediaEl) {
  if (!mediaEl || !event) return null;
  const rect = mediaEl.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  const intrinsicW = Number(mediaEl.videoWidth || mediaEl.naturalWidth || mediaEl.width || 0) || 0;
  const intrinsicH =
    Number(mediaEl.videoHeight || mediaEl.naturalHeight || mediaEl.height || 0) || 0;
  let left = rect.left;
  let top = rect.top;
  let width = rect.width;
  let height = rect.height;
  if (intrinsicW > 0 && intrinsicH > 0) {
    const scale = Math.min(rect.width / intrinsicW, rect.height / intrinsicH);
    width = intrinsicW * scale;
    height = intrinsicH * scale;
    left = rect.left + (rect.width - width) / 2;
    top = rect.top + (rect.height - height) / 2;
  }
  const x = (event.clientX - left) / width;
  const y = (event.clientY - top) / height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return { u: x, v: y };
}

/** Prefer the visible primary preview media element. */
export function resolveActivePreviewMedia(candidates = []) {
  for (const el of candidates) {
    if (el && !el.hidden && el.getClientRects?.().length) return el;
  }
  return candidates.find((el) => el) || null;
}

function ensureBrushOverlay(mediaEl) {
  const host = mediaEl?.parentElement;
  if (!host) return null;
  let canvas = host.querySelector?.("[data-managed-brush-overlay]");
  if (!canvas) {
    canvas = document.createElement("canvas");
    canvas.className = "studio-managed-brush-overlay";
    canvas.dataset.managedBrushOverlay = "1";
    canvas.setAttribute("aria-hidden", "true");
    host.appendChild(canvas);
  }
  const rect = mediaEl.getBoundingClientRect();
  const hostRect = host.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  canvas.style.left = `${Math.round(rect.left - hostRect.left)}px`;
  canvas.style.top = `${Math.round(rect.top - hostRect.top)}px`;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  canvas.hidden = false;
  return canvas;
}

function clearBrushOverlay(mediaEl) {
  const host = mediaEl?.parentElement;
  const canvas = host?.querySelector?.("[data-managed-brush-overlay]");
  if (!canvas) return;
  const ctx = canvas.getContext?.("2d");
  if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  canvas.hidden = true;
}

function paintBrushOverlay(mediaEl, points, radiusUv) {
  const canvas = ensureBrushOverlay(mediaEl);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!points.length) return;
  const radiusPx = Math.max(2, (Number(radiusUv) || 0.08) * Math.min(canvas.width, canvas.height));
  ctx.strokeStyle = "rgba(255, 64, 180, 0.95)";
  ctx.fillStyle = "rgba(255, 64, 180, 0.28)";
  ctx.lineWidth = Math.max(2, radiusPx * 0.35);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  points.forEach((pt, index) => {
    const x = pt[0] * canvas.width;
    const y = pt[1] * canvas.height;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  const last = points[points.length - 1];
  ctx.beginPath();
  ctx.arc(last[0] * canvas.width, last[1] * canvas.height, radiusPx, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}

function paintPolygonOverlay(mediaEl, points, { closed = false } = {}) {
  const canvas = ensureBrushOverlay(mediaEl);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!points.length) return;
  ctx.strokeStyle = "rgba(64, 200, 255, 0.95)";
  ctx.fillStyle = "rgba(64, 200, 255, 0.18)";
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.beginPath();
  points.forEach((pt, index) => {
    const x = pt[0] * canvas.width;
    const y = pt[1] * canvas.height;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  if (closed && points.length >= 3) {
    ctx.closePath();
    ctx.fill();
  }
  ctx.stroke();
  points.forEach((pt) => {
    ctx.beginPath();
    ctx.arc(pt[0] * canvas.width, pt[1] * canvas.height, 4, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(64, 200, 255, 0.95)";
    ctx.fill();
  });
}

/** Hit-test a polygon vertex in UV space; returns index or -1. */
export function hitTestPolygonVertex(points, uv, thresholdUv = 0.02) {
  if (!uv || !Array.isArray(points) || !points.length) return -1;
  let best = -1;
  let bestDist = thresholdUv;
  points.forEach((pt, index) => {
    if (!pt || pt.length < 2) return;
    const dist = Math.hypot(Number(pt[0]) - uv.u, Number(pt[1]) - uv.v);
    if (dist <= bestDist) {
      bestDist = dist;
      best = index;
    }
  });
  return best;
}

export function createManagedViewerTools({
  getMediaEl,
  mediaEl,
  getMode,
  getBrushSettings,
  getEditablePolygon,
  onEyedropperSample,
  onBrushStrokeComplete,
  onPolygonComplete,
  onPolygonEdited,
  onStatus,
  messages = {},
}) {
  let drawing = false;
  let polygonActive = false;
  let polygonDragging = false;
  let dragIndex = -1;
  let points = [];
  let pointerId = null;
  let boundEl = null;
  let lastClickAt = 0;

  function activeMedia() {
    return getMediaEl?.() || mediaEl || null;
  }

  function setStatus(text) {
    onStatus?.(text || "");
  }

  function finishStroke() {
    if (!drawing) return;
    drawing = false;
    pointerId = null;
    const strokePoints = points.slice();
    points = [];
    clearBrushOverlay(activeMedia());
    if (strokePoints.length < 1) return;
    if (strokePoints.length === 1) {
      strokePoints.push([Math.min(1, strokePoints[0][0] + 0.001), strokePoints[0][1]]);
    }
    const settings = getBrushSettings?.() || {};
    onBrushStrokeComplete?.({
      points: strokePoints,
      radius: Number(settings.radius) || 0.08,
      hardness: Number(settings.hardness) || 0.5,
      pressure: Number(settings.pressure) || 1,
    });
  }

  function finishPolygon() {
    if (!polygonActive) return;
    const polyPoints = points.slice();
    polygonActive = false;
    points = [];
    clearBrushOverlay(activeMedia());
    if (polyPoints.length < 3) {
      setStatus(messages.polygonNeedPoints || "Polygon needs at least 3 points");
      return;
    }
    paintPolygonOverlay(activeMedia(), polyPoints, { closed: true });
    onPolygonComplete?.({ points: polyPoints, closed: true });
  }

  function onPointerDown(event) {
    const mode = getMode?.() || "none";
    if (mode === "none") return;
    if (event.button !== undefined && event.button !== null && event.button !== 0) return;
    const el = activeMedia();
    const uv = pointerToSourceUv(event, el);
    if (!uv) return;
    event.preventDefault();
    event.stopPropagation();
    if (mode === "eyedropper") {
      void onEyedropperSample?.(uv);
      return;
    }
    if (mode === "brush") {
      drawing = true;
      pointerId = event.pointerId;
      points = [[uv.u, uv.v]];
      try {
        el?.setPointerCapture?.(event.pointerId);
      } catch {
        /* ignore */
      }
      const settings = getBrushSettings?.() || {};
      paintBrushOverlay(el, points, settings.radius);
      setStatus(messages.brushDrawing || "Brush drawing…");
      return;
    }
    if (mode === "polygon") {
      // Drag an existing closed polygon vertex (#533) before starting a new draw.
      if (!polygonActive) {
        const editable = getEditablePolygon?.();
        const editPoints = Array.isArray(editable?.points) ? editable.points : null;
        if (editPoints && editPoints.length >= 3) {
          const hit = hitTestPolygonVertex(editPoints, uv);
          if (hit >= 0) {
            polygonDragging = true;
            dragIndex = hit;
            pointerId = event.pointerId;
            points = editPoints.map((pt) => [Number(pt[0]), Number(pt[1])]);
            try {
              el?.setPointerCapture?.(event.pointerId);
            } catch {
              /* ignore */
            }
            paintPolygonOverlay(el, points, { closed: true });
            setStatus(messages.polygonDragging || "Polygon: drag vertex to refine");
            return;
          }
        }
      }
      const now = Date.now();
      const isDouble = now - lastClickAt < 350 && points.length >= 2;
      lastClickAt = now;
      if (!polygonActive) {
        polygonActive = true;
        points = [];
      }
      if (isDouble) {
        finishPolygon();
        return;
      }
      points.push([uv.u, uv.v]);
      paintPolygonOverlay(el, points, { closed: false });
      const template =
        messages.polygonDrawing ||
        "Polygon: {count} points — Enter/double-click to close, Esc to cancel";
      setStatus(template.replace("{count}", String(points.length)));
    }
  }

  function onPointerMove(event) {
    if (polygonDragging) {
      if (pointerId !== null && event.pointerId !== pointerId) return;
      const el = activeMedia();
      const uv = pointerToSourceUv(event, el);
      if (!uv || dragIndex < 0 || !points[dragIndex]) return;
      points[dragIndex] = [uv.u, uv.v];
      paintPolygonOverlay(el, points, { closed: true });
      return;
    }
    if (!drawing || (pointerId !== null && event.pointerId !== pointerId)) return;
    const el = activeMedia();
    const uv = pointerToSourceUv(event, el);
    if (!uv) return;
    const last = points[points.length - 1];
    if (last && Math.hypot(uv.u - last[0], uv.v - last[1]) < 0.004) {
      return;
    }
    points.push([uv.u, uv.v]);
    const settings = getBrushSettings?.() || {};
    paintBrushOverlay(el, points, settings.radius);
  }

  function onPointerUp(event) {
    if (polygonDragging) {
      if (pointerId !== null && event.pointerId !== pointerId) return;
      polygonDragging = false;
      pointerId = null;
      const edited = points.map((pt) => [pt[0], pt[1]]);
      dragIndex = -1;
      paintPolygonOverlay(activeMedia(), edited, { closed: true });
      onPolygonEdited?.({ points: edited, closed: true });
      setStatus(messages.polygonEdited || "Polygon vertex updated");
      return;
    }
    if (!drawing) return;
    if (pointerId !== null && event.pointerId !== pointerId) return;
    finishStroke();
  }

  function onKeyDown(event) {
    if (event.key === "Escape" && (drawing || polygonActive || polygonDragging)) {
      const wasBrush = drawing;
      drawing = false;
      polygonActive = false;
      polygonDragging = false;
      dragIndex = -1;
      points = [];
      pointerId = null;
      clearBrushOverlay(activeMedia());
      setStatus(
        wasBrush
          ? messages.brushCancelled || "Brush cancelled"
          : messages.polygonCancelled || "Polygon cancelled"
      );
      return;
    }
    if ((event.key === "Enter" || event.key === " ") && polygonActive) {
      event.preventDefault();
      finishPolygon();
    }
  }

  function bind(el) {
    if (boundEl === el) return;
    if (boundEl) {
      boundEl.removeEventListener("pointerdown", onPointerDown);
      boundEl.removeEventListener("pointermove", onPointerMove);
      boundEl.removeEventListener("pointerup", onPointerUp);
      boundEl.removeEventListener("pointercancel", onPointerUp);
      clearBrushOverlay(boundEl);
    }
    boundEl = el || null;
    if (!boundEl) return;
    boundEl.addEventListener("pointerdown", onPointerDown);
    boundEl.addEventListener("pointermove", onPointerMove);
    boundEl.addEventListener("pointerup", onPointerUp);
    boundEl.addEventListener("pointercancel", onPointerUp);
  }

  bind(activeMedia());
  document.addEventListener("keydown", onKeyDown);

  return {
    rebind() {
      bind(activeMedia());
    },
    destroy() {
      clearBrushOverlay(boundEl);
      bind(null);
      document.removeEventListener("keydown", onKeyDown);
    },
  };
}
