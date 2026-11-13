/** Viewer eyedropper + brush stroke capture for managed selections (#356/#357). */

/**
 * Map a pointer event on the preview media box to normalized source UV [0,1].
 * Returns null when the point is outside the painted media rect.
 */
export function pointerToSourceUv(event, mediaEl) {
  if (!mediaEl || !event) return null;
  const rect = mediaEl.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  const x = (event.clientX - rect.left) / rect.width;
  const y = (event.clientY - rect.top) / rect.height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return { u: x, v: y };
}

export function createManagedViewerTools({
  mediaEl,
  getMode,
  getBrushSettings,
  onEyedropperSample,
  onBrushStrokeComplete,
  onStatus,
}) {
  let drawing = false;
  let points = [];
  let pointerId = null;

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
      strokePoints.push([
        Math.min(1, strokePoints[0][0] + 0.001),
        strokePoints[0][1],
      ]);
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
    const uv = pointerToSourceUv(event, mediaEl);
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
        mediaEl.setPointerCapture?.(event.pointerId);
      } catch {
        /* ignore */
      }
      setStatus("brush drawing…");
    }
  }

  function onPointerMove(event) {
    if (!drawing || (pointerId !== null && event.pointerId !== pointerId)) return;
    const uv = pointerToSourceUv(event, mediaEl);
    if (!uv) return;
    const last = points[points.length - 1];
    if (
      last &&
      Math.hypot(uv.u - last[0], uv.v - last[1]) < 0.004
    ) {
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
      setStatus("brush cancelled");
    }
  }

  mediaEl?.addEventListener("pointerdown", onPointerDown);
  mediaEl?.addEventListener("pointermove", onPointerMove);
  mediaEl?.addEventListener("pointerup", onPointerUp);
  mediaEl?.addEventListener("pointercancel", onPointerUp);
  document.addEventListener("keydown", onKeyDown);

  return {
    destroy() {
      mediaEl?.removeEventListener("pointerdown", onPointerDown);
      mediaEl?.removeEventListener("pointermove", onPointerMove);
      mediaEl?.removeEventListener("pointerup", onPointerUp);
      mediaEl?.removeEventListener("pointercancel", onPointerUp);
      document.removeEventListener("keydown", onKeyDown);
    },
  };
}
