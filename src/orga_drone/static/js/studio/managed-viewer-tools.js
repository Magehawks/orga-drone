/** Viewer eyedropper + brush stroke capture for managed selections (#356/#357/#561). */

/**
 * Client-space rectangle of the painted picture inside a media element.
 *
 * Studio preview media uses ``object-fit: contain``. The element's
 * ``getBoundingClientRect()`` includes letterbox gutters; mask UV and overlays
 * must use the content rect instead (#561).
 *
 * @returns {{ left: number, top: number, width: number, height: number } | null}
 */
export function mediaContentClientRect(mediaEl) {
  if (!mediaEl?.getBoundingClientRect) return null;
  const rect = mediaEl.getBoundingClientRect();
  if (!(rect.width > 0) || !(rect.height > 0)) return null;
  const intrinsicW = Number(mediaEl.videoWidth || mediaEl.naturalWidth || mediaEl.width || 0) || 0;
  const intrinsicH =
    Number(mediaEl.videoHeight || mediaEl.naturalHeight || mediaEl.height || 0) || 0;
  if (!(intrinsicW > 0) || !(intrinsicH > 0)) {
    return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
  }
  const scale = Math.min(rect.width / intrinsicW, rect.height / intrinsicH);
  const width = intrinsicW * scale;
  const height = intrinsicH * scale;
  return {
    left: rect.left + (rect.width - width) / 2,
    top: rect.top + (rect.height - height) / 2,
    width,
    height,
  };
}

/**
 * Map a pointer event on the preview media box to normalized source UV [0,1].
 * Accounts for ``object-fit: contain`` letterboxing when intrinsic size is known.
 * Returns null when the point is outside the painted picture.
 */
export function pointerToSourceUv(event, mediaEl) {
  if (!mediaEl || !event) return null;
  const content = mediaContentClientRect(mediaEl);
  if (!content || !(content.width > 0) || !(content.height > 0)) return null;
  const x = (event.clientX - content.left) / content.width;
  const y = (event.clientY - content.top) / content.height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return { u: x, v: y };
}

/** Map source UV back to client pixels using the same content rect as pointers. */
export function sourceUvToClient(uv, mediaEl) {
  const content = mediaContentClientRect(mediaEl);
  if (!content || !uv) return null;
  const u = Number(uv.u);
  const v = Number(uv.v);
  if (!Number.isFinite(u) || !Number.isFinite(v)) return null;
  return {
    clientX: content.left + u * content.width,
    clientY: content.top + v * content.height,
  };
}

/** Host-relative overlay box matching the painted picture (#561). */
export function overlayLayoutForMedia(mediaEl, hostEl) {
  const content = mediaContentClientRect(mediaEl);
  if (!content || !hostEl?.getBoundingClientRect) return null;
  const hostRect = hostEl.getBoundingClientRect();
  return {
    left: Math.round(content.left - hostRect.left),
    top: Math.round(content.top - hostRect.top),
    width: Math.max(1, Math.round(content.width)),
    height: Math.max(1, Math.round(content.height)),
  };
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
  const layout = overlayLayoutForMedia(mediaEl, host);
  if (!layout) return null;
  let canvas = host.querySelector?.("[data-managed-brush-overlay]");
  if (!canvas) {
    canvas = document.createElement("canvas");
    canvas.className = "studio-managed-brush-overlay";
    canvas.dataset.managedBrushOverlay = "1";
    canvas.setAttribute("aria-hidden", "true");
    host.appendChild(canvas);
  }
  // Align overlay to the painted picture, not the letterboxed media box (#561).
  if (canvas.width !== layout.width) canvas.width = layout.width;
  if (canvas.height !== layout.height) canvas.height = layout.height;
  canvas.style.left = `${layout.left}px`;
  canvas.style.top = `${layout.top}px`;
  canvas.style.width = `${layout.width}px`;
  canvas.style.height = `${layout.height}px`;
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

export function paintPolygonOverlay(
  mediaEl,
  points,
  { closed = false, squareHandles = false } = {}
) {
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
    const x = pt[0] * canvas.width;
    const y = pt[1] * canvas.height;
    ctx.fillStyle = "rgba(64, 200, 255, 0.95)";
    if (squareHandles) {
      const s = 7;
      ctx.fillRect(x - s / 2, y - s / 2, s, s);
      ctx.strokeStyle = "rgba(20, 20, 20, 0.85)";
      ctx.lineWidth = 1;
      ctx.strokeRect(x - s / 2, y - s / 2, s, s);
      ctx.strokeStyle = "rgba(64, 200, 255, 0.95)";
      ctx.lineWidth = 2;
    } else {
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
    }
  });
}

/** Draw a server-rasterized selection coverage PNG (#537). Preview only. */
export function paintSelectionRasterOverlay(mediaEl, imageBitmap, selection = null) {
  const canvas = ensureBrushOverlay(mediaEl);
  if (!canvas || !imageBitmap) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(imageBitmap, 0, 0, canvas.width, canvas.height);
  const poly = selection?.mask?.leaves?.find(
    (leaf) => leaf?.type === "polygon" && Array.isArray(leaf.points) && leaf.points.length >= 3
  );
  if (poly) {
    ctx.strokeStyle = "rgba(64, 200, 255, 0.95)";
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.beginPath();
    poly.points.forEach((pt, index) => {
      const x = Number(pt[0]) * canvas.width;
      const y = Number(pt[1]) * canvas.height;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.stroke();
    poly.points.forEach((pt) => {
      const x = Number(pt[0]) * canvas.width;
      const y = Number(pt[1]) * canvas.height;
      const s = 7;
      ctx.fillStyle = "rgba(64, 200, 255, 0.95)";
      ctx.fillRect(x - s / 2, y - s / 2, s, s);
      ctx.strokeStyle = "rgba(20, 20, 20, 0.85)";
      ctx.lineWidth = 1;
      ctx.strokeRect(x - s / 2, y - s / 2, s, s);
    });
  }
}

/** Fallback local outline when raster overlay is unavailable. */
export function paintSelectionInspectionOverlay(mediaEl, selection, { invertedHint = false } = {}) {
  if (!mediaEl || !selection) {
    clearBrushOverlay(mediaEl);
    return;
  }
  const leaves = selection?.mask?.leaves;
  if (!Array.isArray(leaves) || !leaves.length) {
    clearBrushOverlay(mediaEl);
    return;
  }
  const poly = leaves.find((leaf) => leaf?.type === "polygon" && Array.isArray(leaf.points));
  if (poly && poly.points.length >= 3) {
    paintPolygonOverlay(mediaEl, poly.points, {
      closed: Boolean(poly.closed !== false),
      squareHandles: true,
    });
    return;
  }
  const brush = leaves.find((leaf) => leaf?.type === "brush");
  if (brush && Array.isArray(brush.strokes) && brush.strokes.length) {
    const pts = [];
    for (const stroke of brush.strokes) {
      if (Array.isArray(stroke?.points)) pts.push(...stroke.points);
    }
    if (pts.length) {
      paintBrushOverlay(mediaEl, pts, brush.strokes[0]?.radius || 0.08);
      return;
    }
  }
  const radial = leaves.find((leaf) => leaf?.type === "radial");
  if (radial?.center && radial?.axes) {
    const canvas = ensureBrushOverlay(mediaEl);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const cx = Number(radial.center[0]) * canvas.width;
    const cy = Number(radial.center[1]) * canvas.height;
    const rx = Math.max(2, Number(radial.axes[0]) * canvas.width);
    const ry = Math.max(2, Number(radial.axes[1]) * canvas.height);
    ctx.fillStyle = invertedHint ? "rgba(255, 180, 64, 0.14)" : "rgba(64, 200, 255, 0.18)";
    ctx.strokeStyle = invertedHint ? "rgba(255, 180, 64, 0.95)" : "rgba(64, 200, 255, 0.95)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    return;
  }
  const linear = leaves.find((leaf) => leaf?.type === "linear");
  if (linear?.start && linear?.end) {
    const canvas = ensureBrushOverlay(mediaEl);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "rgba(64, 200, 255, 0.95)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(Number(linear.start[0]) * canvas.width, Number(linear.start[1]) * canvas.height);
    ctx.lineTo(Number(linear.end[0]) * canvas.width, Number(linear.end[1]) * canvas.height);
    ctx.stroke();
    return;
  }
  clearBrushOverlay(mediaEl);
}

export function clearManagedSelectionOverlay(mediaEl) {
  clearBrushOverlay(mediaEl);
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

/** Distance from point to segment; used for edge insert (#538). */
export function distanceToSegment(uv, a, b) {
  const ax = Number(a[0]);
  const ay = Number(a[1]);
  const bx = Number(b[0]);
  const by = Number(b[1]);
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 <= 1e-12) return Math.hypot(uv.u - ax, uv.v - ay);
  let t = ((uv.u - ax) * dx + (uv.v - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(uv.u - (ax + t * dx), uv.v - (ay + t * dy));
}

/** Hit-test polygon edge; returns insert index after vertex i, or -1. */
export function hitTestPolygonEdge(points, uv, thresholdUv = 0.022) {
  if (!uv || !Array.isArray(points) || points.length < 2) return -1;
  let best = -1;
  let bestDist = thresholdUv;
  for (let i = 0; i < points.length; i += 1) {
    const a = points[i];
    const b = points[(i + 1) % points.length];
    const dist = distanceToSegment(uv, a, b);
    if (dist <= bestDist) {
      bestDist = dist;
      best = i + 1;
    }
  }
  return best;
}

/** Even-odd point-in-polygon for whole-mask move (#538). */
export function pointInPolygon(uv, points) {
  if (!uv || !Array.isArray(points) || points.length < 3) return false;
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
    const xi = Number(points[i][0]);
    const yi = Number(points[i][1]);
    const xj = Number(points[j][0]);
    const yj = Number(points[j][1]);
    const intersect =
      yi > uv.v !== yj > uv.v && uv.u < ((xj - xi) * (uv.v - yi)) / (yj - yi + 1e-12) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export function createManagedViewerTools({
  getMediaEl,
  mediaEl,
  getMode,
  getBrushSettings,
  getEditablePolygon,
  onEyedropperSample,
  onObjectSelect,
  onBrushStrokeComplete,
  onPolygonComplete,
  onPolygonEdited,
  onStatus,
  messages = {},
}) {
  let drawing = false;
  let polygonActive = false;
  let polygonDragging = false;
  let polygonMoving = false;
  let dragIndex = -1;
  let moveOrigin = null;
  let moveBase = null;
  let points = [];
  let pointerId = null;
  let boundEl = null;
  let lastClickAt = 0;
  const MIN_POLYGON_POINTS = 3;
  const MAX_POLYGON_POINTS = 4096;

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
    if (mode === "object-select") {
      void onObjectSelect?.(uv, {
        shiftKey: Boolean(event.shiftKey),
        altKey: Boolean(event.altKey),
        metaKey: Boolean(event.metaKey),
      });
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
      // Edit existing closed polygon (#533/#538) before starting a new draw.
      if (!polygonActive) {
        const editable = getEditablePolygon?.();
        const editPoints = Array.isArray(editable?.points) ? editable.points : null;
        if (editPoints && editPoints.length >= 3) {
          const hit = hitTestPolygonVertex(editPoints, uv);
          // Alt/Option+click removes a vertex (keep ≥3).
          if (hit >= 0 && (event.altKey || event.metaKey)) {
            if (editPoints.length <= MIN_POLYGON_POINTS) {
              setStatus(messages.polygonNeedPoints || "Polygon needs at least 3 points");
              return;
            }
            const next = editPoints
              .map((pt) => [Number(pt[0]), Number(pt[1])])
              .filter((_, index) => index !== hit);
            paintPolygonOverlay(el, next, { closed: true, squareHandles: true });
            onPolygonEdited?.({ points: next, closed: true });
            setStatus(messages.polygonVertexRemoved || "Polygon vertex removed");
            return;
          }
          if (hit >= 0) {
            polygonDragging = true;
            polygonMoving = false;
            dragIndex = hit;
            pointerId = event.pointerId;
            points = editPoints.map((pt) => [Number(pt[0]), Number(pt[1])]);
            try {
              el?.setPointerCapture?.(event.pointerId);
            } catch {
              /* ignore */
            }
            paintPolygonOverlay(el, points, { closed: true, squareHandles: true });
            setStatus(messages.polygonDragging || "Polygon: drag vertex to refine");
            return;
          }
          const edgeInsert = hitTestPolygonEdge(editPoints, uv);
          if (edgeInsert >= 0 && editPoints.length < MAX_POLYGON_POINTS) {
            const next = editPoints.map((pt) => [Number(pt[0]), Number(pt[1])]);
            next.splice(edgeInsert, 0, [uv.u, uv.v]);
            polygonDragging = true;
            polygonMoving = false;
            dragIndex = edgeInsert;
            pointerId = event.pointerId;
            points = next;
            try {
              el?.setPointerCapture?.(event.pointerId);
            } catch {
              /* ignore */
            }
            paintPolygonOverlay(el, points, { closed: true, squareHandles: true });
            setStatus(messages.polygonVertexAdded || "Polygon: vertex added — drag to place");
            return;
          }
          if (pointInPolygon(uv, editPoints)) {
            polygonMoving = true;
            polygonDragging = false;
            dragIndex = -1;
            pointerId = event.pointerId;
            moveOrigin = { u: uv.u, v: uv.v };
            moveBase = editPoints.map((pt) => [Number(pt[0]), Number(pt[1])]);
            points = moveBase.map((pt) => [pt[0], pt[1]]);
            try {
              el?.setPointerCapture?.(event.pointerId);
            } catch {
              /* ignore */
            }
            paintPolygonOverlay(el, points, { closed: true, squareHandles: true });
            setStatus(messages.polygonMoving || "Polygon: move selection");
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
    if (polygonMoving) {
      if (pointerId !== null && event.pointerId !== pointerId) return;
      const el = activeMedia();
      const uv = pointerToSourceUv(event, el);
      if (!uv || !moveOrigin || !moveBase) return;
      const du = uv.u - moveOrigin.u;
      const dv = uv.v - moveOrigin.v;
      points = moveBase.map((pt) => [
        Math.max(0, Math.min(1, pt[0] + du)),
        Math.max(0, Math.min(1, pt[1] + dv)),
      ]);
      paintPolygonOverlay(el, points, { closed: true, squareHandles: true });
      return;
    }
    if (polygonDragging) {
      if (pointerId !== null && event.pointerId !== pointerId) return;
      const el = activeMedia();
      const uv = pointerToSourceUv(event, el);
      if (!uv || dragIndex < 0 || !points[dragIndex]) return;
      points[dragIndex] = [uv.u, uv.v];
      paintPolygonOverlay(el, points, { closed: true, squareHandles: true });
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
    if (polygonMoving) {
      if (pointerId !== null && event.pointerId !== pointerId) return;
      polygonMoving = false;
      pointerId = null;
      moveOrigin = null;
      moveBase = null;
      const edited = points.map((pt) => [pt[0], pt[1]]);
      paintPolygonOverlay(activeMedia(), edited, { closed: true, squareHandles: true });
      onPolygonEdited?.({ points: edited, closed: true });
      setStatus(messages.polygonMoved || "Polygon selection moved");
      return;
    }
    if (polygonDragging) {
      if (pointerId !== null && event.pointerId !== pointerId) return;
      polygonDragging = false;
      pointerId = null;
      const edited = points.map((pt) => [pt[0], pt[1]]);
      dragIndex = -1;
      paintPolygonOverlay(activeMedia(), edited, { closed: true, squareHandles: true });
      onPolygonEdited?.({ points: edited, closed: true });
      setStatus(messages.polygonEdited || "Polygon vertex updated");
      return;
    }
    if (!drawing) return;
    if (pointerId !== null && event.pointerId !== pointerId) return;
    finishStroke();
  }

  function onKeyDown(event) {
    if (event.key === "Escape" && (drawing || polygonActive || polygonDragging || polygonMoving)) {
      const wasBrush = drawing;
      drawing = false;
      polygonActive = false;
      polygonDragging = false;
      polygonMoving = false;
      dragIndex = -1;
      moveOrigin = null;
      moveBase = null;
      points = [];
      pointerId = null;
      clearBrushOverlay(activeMedia());
      // Re-paint current editable polygon after cancel so inspection stays visible.
      const editable = getEditablePolygon?.();
      if (editable?.points?.length >= 3) {
        paintPolygonOverlay(activeMedia(), editable.points, {
          closed: editable.closed !== false,
          squareHandles: true,
        });
      }
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
