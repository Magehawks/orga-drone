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

export function createManagedViewerTools({
  getMediaEl,
  mediaEl,
  getMode,
  getBrushSettings,
  onEyedropperSample,
  onBrushStrokeComplete,
  onStatus,
  messages = {},
}) {
  let drawing = false;
  let points = [];
  let pointerId = null;
  let boundEl = null;

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
      setStatus(messages.brushDrawing || "Brush drawing…");
    }
  }

  function onPointerMove(event) {
    if (!drawing || (pointerId !== null && event.pointerId !== pointerId)) return;
    const uv = pointerToSourceUv(event, activeMedia());
    if (!uv) return;
    const last = points[points.length - 1];
    if (last && Math.hypot(uv.u - last[0], uv.v - last[1]) < 0.004) {
      return;
    }
    points.push([uv.u, uv.v]);
  }

  function onPointerUp(event) {
    if (!drawing) return;
    if (pointerId !== null && event.pointerId !== pointerId) return;
    finishStroke();
  }

  function onKeyDown(event) {
    if (event.key === "Escape" && drawing) {
      drawing = false;
      points = [];
      pointerId = null;
      setStatus(messages.brushCancelled || "Brush cancelled");
    }
  }

  function bind(el) {
    if (boundEl === el) return;
    if (boundEl) {
      boundEl.removeEventListener("pointerdown", onPointerDown);
      boundEl.removeEventListener("pointermove", onPointerMove);
      boundEl.removeEventListener("pointerup", onPointerUp);
      boundEl.removeEventListener("pointercancel", onPointerUp);
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
      bind(null);
      document.removeEventListener("keydown", onKeyDown);
    },
  };
}
