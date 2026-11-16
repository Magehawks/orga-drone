/**
 * Collage cell framing dialog: full source + free orange crop viewport + Color panel.
 * Viewport can be moved and resized freely (width/height); crop is persisted on media.
 */

import { MIN_LEAF_ZOOM, MAX_LEAF_ZOOM, mediaSourceWindow, sourceWindow } from "./collage-layout.js";

const MIN_CROP_EDGE = 0.05;
const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

/**
 * @param {object} opts
 * @param {(msg: string) => void} [opts.showFlash]
 */
export function createCollageFrameModal(opts = {}) {
  const dialog = document.getElementById("studio-collage-frame-dialog");
  const stage = document.getElementById("studio-collage-frame-stage");
  const image = document.getElementById("studio-collage-frame-image");
  const viewport = document.getElementById("studio-collage-frame-viewport");
  const fitEl = document.getElementById("studio-collage-frame-fit");
  const zoomEl = document.getElementById("studio-collage-frame-zoom");
  const applyBtn = document.getElementById("studio-collage-frame-apply");
  const cancelBtn = document.getElementById("studio-collage-frame-cancel");
  const colorHost = document.getElementById("studio-collage-frame-color");

  /** @type {null | {
   *   media: any,
   *   crop: { x: number, y: number, w: number, h: number },
   *   cellW: number,
   *   cellH: number,
   *   studioId: string,
   *   leafId: string,
   *   sourceUrl: string,
   *   onApply: (media: any, meta?: { cropAspect: number }) => void,
   *   usingGradedStill: boolean,
   * }} */
  let session = null;
  /** @type {null | { mode: "move"|"resize", handle?: string, startX: number, startY: number, startCrop: any, box: any }} */
  let drag = null;
  /** @type {Comment | null} */
  let colorHome = null;
  let gradeSeq = 0;
  let handlesReady = false;

  function clampZoom(value) {
    const zoom = Number(value);
    if (!Number.isFinite(zoom)) return MIN_LEAF_ZOOM;
    return Math.max(MIN_LEAF_ZOOM, Math.min(MAX_LEAF_ZOOM, zoom));
  }

  function clampPan(value) {
    const pan = Number(value);
    if (!Number.isFinite(pan)) return 0.5;
    return Math.max(0, Math.min(1, pan));
  }

  function clampCrop(crop) {
    let x = Number(crop?.x);
    let y = Number(crop?.y);
    let w = Number(crop?.w);
    let h = Number(crop?.h);
    if (!Number.isFinite(x)) x = 0;
    if (!Number.isFinite(y)) y = 0;
    if (!(w > 0)) w = 1;
    if (!(h > 0)) h = 1;
    w = Math.max(MIN_CROP_EDGE, Math.min(1, w));
    h = Math.max(MIN_CROP_EDGE, Math.min(1, h));
    x = Math.max(0, Math.min(1 - w, x));
    y = Math.max(0, Math.min(1 - h, y));
    return { x, y, w, h };
  }

  function imageContentRect() {
    if (!stage || !image) return null;
    const nw = Math.max(1, image.naturalWidth || 0);
    const nh = Math.max(1, image.naturalHeight || 0);
    if (!nw || !nh) return null;
    const bw = Math.max(1, stage.clientWidth);
    const bh = Math.max(1, stage.clientHeight);
    const scale = Math.min(bw / nw, bh / nh);
    const width = nw * scale;
    const height = nh * scale;
    return {
      left: (bw - width) / 2,
      top: (bh - height) / 2,
      width,
      height,
      nw,
      nh,
    };
  }

  function ensureHandles() {
    if (!viewport || handlesReady) return;
    HANDLES.forEach((name) => {
      const handle = document.createElement("span");
      handle.className = `studio-collage-frame-handle is-${name}`;
      handle.dataset.handle = name;
      handle.setAttribute("aria-hidden", "true");
      viewport.appendChild(handle);
    });
    handlesReady = true;
  }

  function defaultCropFromCell() {
    if (!session) return { x: 0, y: 0, w: 1, h: 1 };
    const box = imageContentRect();
    const nw = box?.nw || 1;
    const nh = box?.nh || 1;
    const fit = String(session.media.fit || "fill").toLowerCase() === "fit" ? "fit" : "fill";
    return clampCrop(
      sourceWindow({
        sourceW: nw,
        sourceH: nh,
        cellW: session.cellW,
        cellH: session.cellH,
        fit,
        zoom: session.media.zoom,
        panX: session.media.pan_x,
        panY: session.media.pan_y,
      })
    );
  }

  function syncZoomFromCrop() {
    if (!session || !zoomEl) return;
    // Approximate zoom: how much smaller than a full-cover window.
    const box = imageContentRect();
    const cover = sourceWindow({
      sourceW: box?.nw || 1,
      sourceH: box?.nh || 1,
      cellW: session.cellW,
      cellH: session.cellH,
      fit: "fill",
      zoom: 1,
      panX: 0.5,
      panY: 0.5,
    });
    const areaRatio = (cover.w * cover.h) / Math.max(1e-6, session.crop.w * session.crop.h);
    const approx = Math.sqrt(Math.max(1, areaRatio));
    zoomEl.value = String(clampZoom(approx));
    session.media.zoom = clampZoom(approx);
  }

  function syncPanFromCrop() {
    if (!session) return;
    const { x, y, w, h } = session.crop;
    const maxX = Math.max(0, 1 - w);
    const maxY = Math.max(0, 1 - h);
    session.media.pan_x = clampPan(maxX > 1e-6 ? x / maxX : 0.5);
    session.media.pan_y = clampPan(maxY > 1e-6 ? y / maxY : 0.5);
  }

  function paintViewport() {
    if (!session || !viewport) return;
    ensureHandles();
    const box = imageContentRect();
    if (!box) {
      viewport.style.display = "none";
      return;
    }
    const crop = clampCrop(session.crop);
    session.crop = crop;
    viewport.style.display = "block";
    viewport.style.left = `${box.left + crop.x * box.width}px`;
    viewport.style.top = `${box.top + crop.y * box.height}px`;
    viewport.style.width = `${Math.max(2, crop.w * box.width)}px`;
    viewport.style.height = `${Math.max(2, crop.h * box.height)}px`;
  }

  function syncControls() {
    if (!session) return;
    if (fitEl) fitEl.value = session.media.fit === "fit" ? "fit" : "fill";
    syncZoomFromCrop();
  }

  function attachColorPanel() {
    if (!colorHost) return;
    const panel = document.getElementById("inspector-image-panel");
    if (!panel || panel.parentElement === colorHost) return;
    if (!colorHome) {
      colorHome = document.createComment("inspector-image-panel-home");
    }
    if (panel.parentNode) {
      panel.parentNode.insertBefore(colorHome, panel);
    }
    colorHost.appendChild(panel);
    panel.hidden = false;
    panel.classList.add("is-in-collage-frame");
  }

  function detachColorPanel() {
    const panel = document.getElementById("inspector-image-panel");
    if (!panel) return;
    panel.classList.remove("is-in-collage-frame");
    if (colorHome && colorHome.parentNode) {
      colorHome.parentNode.insertBefore(panel, colorHome);
      colorHome.remove();
    }
    colorHome = null;
  }

  function quickLookModel() {
    try {
      const root =
        document.getElementById("studio-root") ||
        document.querySelector("[data-quick-looks-model]");
      return JSON.parse(root?.dataset?.quickLooksModel || "{}");
    } catch {
      return {};
    }
  }

  function readInspectorAdjust() {
    const num = (id) => {
      const n = Number(document.getElementById(id)?.value);
      return Number.isFinite(n) ? n : 0;
    };
    return {
      exposure: num("inspector-image-exposure"),
      contrast: num("inspector-image-contrast"),
      saturation: num("inspector-image-saturation"),
      warmth: num("inspector-image-warmth"),
    };
  }

  function adjustFromLookId(lookId) {
    const key = String(lookId || "").trim().toLowerCase();
    if (!key) return null;
    const values = quickLookModel()?.values;
    if (!values || typeof values !== "object") return null;
    const row = values[key];
    if (!row || typeof row !== "object") return null;
    return {
      exposure: Number(row.exposure) || 0,
      contrast: Number(row.contrast) || 0,
      saturation: Number(row.saturation) || 0,
      warmth: Number(row.warmth) || 0,
    };
  }

  function applyCssGradePreview(adjust) {
    if (!image) return;
    if (session?.usingGradedStill) {
      image.style.filter = "";
      return;
    }
    const e = (Number(adjust?.exposure) || 0) / 100;
    const c = (Number(adjust?.contrast) || 0) / 100;
    const s = (Number(adjust?.saturation) || 0) / 100;
    const w = (Number(adjust?.warmth) || 0) / 100;
    const brightness = Math.max(0.2, 1 + e * 0.55);
    const contrast = Math.max(0.2, 1 + c * 0.9);
    const saturate = Math.max(0, 1 + s);
    const sepia = Math.max(0, w) * 0.42;
    const hue = w * 18;
    image.style.filter =
      `brightness(${brightness}) contrast(${contrast}) saturate(${saturate}) ` +
      `sepia(${sepia}) hue-rotate(${hue}deg)`;
  }

  function syncLiveGradeFromUi(event) {
    if (!session || !image) return;
    const target = event?.target;
    if (target && typeof target.closest === "function") {
      const chip = target.closest("[data-quick-look-chip]");
      if (chip) {
        const lookId = chip.getAttribute("data-quick-look-chip") || "";
        const fromLook = adjustFromLookId(lookId);
        if (fromLook) {
          applyCssGradePreview(fromLook);
          return;
        }
      }
      const select = target.closest("#inspector-quick-look");
      if (select && select.tagName === "SELECT") {
        const fromLook = adjustFromLookId(select.value);
        if (fromLook) {
          applyCssGradePreview(fromLook);
          return;
        }
      }
    }
    applyCssGradePreview(readInspectorAdjust());
  }

  function gradedPreviewUrl(studioId, leafId, bust) {
    const params = new URLSearchParams();
    params.set("t_s", "0");
    params.set("v", String(bust || Date.now()));
    return `/api/studio/${encodeURIComponent(String(studioId))}/collage/leaves/${encodeURIComponent(String(leafId))}/preview-frame?${params}`;
  }

  function setStageImage(url, { allowFallback = true, graded = false } = {}) {
    if (!image || !url || !session) return;
    const seq = ++gradeSeq;
    const onLoad = () => {
      if (seq !== gradeSeq || !session) return;
      session.usingGradedStill = Boolean(graded);
      if (graded) image.style.filter = "";
      else applyCssGradePreview(readInspectorAdjust());
      if (!session.crop || !(session.crop.w > 0)) {
        session.crop = defaultCropFromCell();
      }
      paintViewport();
    };
    const onError = () => {
      if (seq !== gradeSeq || !session) return;
      if (allowFallback && session.sourceUrl && !String(url).includes(session.sourceUrl.split("?")[0])) {
        setStageImage(session.sourceUrl, { allowFallback: false, graded: false });
        return;
      }
      session.usingGradedStill = false;
      applyCssGradePreview(readInspectorAdjust());
    };
    image.addEventListener("load", onLoad, { once: true });
    image.addEventListener("error", onError, { once: true });
    image.src = url;
    if (image.complete && image.naturalWidth) onLoad();
  }

  /**
   * @param {{ grade?: object|null }} [opts]
   */
  function refreshGradePreview(opts = {}) {
    if (!session) return;
    // Keep session media.grade in sync when Looks/HSL/LUT save while the dialog is open.
    if (opts && Object.prototype.hasOwnProperty.call(opts, "grade")) {
      if (opts.grade && typeof opts.grade === "object") {
        session.media = { ...session.media, grade: opts.grade };
      } else {
        const next = { ...session.media };
        delete next.grade;
        session.media = next;
      }
    }
    session.usingGradedStill = false;
    applyCssGradePreview(readInspectorAdjust());
    if (!session.studioId || !session.leafId) return;
    setStageImage(gradedPreviewUrl(session.studioId, session.leafId, Date.now()), {
      allowFallback: true,
      graded: true,
    });
  }

  function close() {
    drag = null;
    session = null;
    gradeSeq += 1;
    stage?.classList.remove("is-dragging");
    dialog?.classList.remove("is-open-frame");
    detachColorPanel();
    if (image) {
      image.style.filter = "";
      image.removeAttribute("src");
    }
    if (dialog?.open) dialog.close();
  }

  /**
   * @param {{
   *   sourceUrl: string,
   *   media: any,
   *   cellW: number,
   *   cellH: number,
   *   studioId?: string|number,
   *   leafId?: string,
   *   onApply: (media: any, meta?: { cropAspect: number }) => void,
   * }} args
   */
  function open(args) {
    if (!dialog || !image || !stage || !args?.sourceUrl || !args?.media) {
      opts.showFlash?.("Could not open framing.");
      return;
    }
    const media = {
      ...args.media,
      zoom: clampZoom(args.media.zoom),
      pan_x: clampPan(args.media.pan_x),
      pan_y: clampPan(args.media.pan_y),
      fit: args.media.fit === "fit" ? "fit" : "fill",
    };
    session = {
      media,
      crop: clampCrop(
        args.media.crop ||
          mediaSourceWindow(media, {
            sourceW: 1000,
            sourceH: 1000,
            cellW: Math.max(1, Number(args.cellW) || 1),
            cellH: Math.max(1, Number(args.cellH) || 1),
          })
      ),
      cellW: Math.max(1, Number(args.cellW) || 1),
      cellH: Math.max(1, Number(args.cellH) || 1),
      studioId: args.studioId != null ? String(args.studioId) : "",
      leafId: args.leafId != null ? String(args.leafId) : "",
      sourceUrl: String(args.sourceUrl),
      onApply: args.onApply,
      usingGradedStill: false,
    };
    syncControls();
    viewport && (viewport.style.display = "none");
    ensureHandles();
    const bust = args.sourceUrl.includes("?") ? "&" : "?";
    setStageImage(`${args.sourceUrl}${bust}frame=${Date.now()}`, {
      allowFallback: false,
      graded: false,
    });
    if (session.studioId && session.leafId) {
      setStageImage(gradedPreviewUrl(session.studioId, session.leafId, Date.now()), {
        allowFallback: true,
        graded: true,
      });
    }
    attachColorPanel();
    applyCssGradePreview(readInspectorAdjust());
    dialog.classList.add("is-open-frame");
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    requestAnimationFrame(() => {
      if (session && (!args.media.crop || !(args.media.crop.w > 0))) {
        session.crop = defaultCropFromCell();
      }
      paintViewport();
      applyCssGradePreview(readInspectorAdjust());
    });
  }

  function beginDrag(event, mode, handle) {
    if (!session || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const box = imageContentRect();
    if (!box) return;
    try {
      stage?.setPointerCapture(event.pointerId);
    } catch {
      /* ignore */
    }
    stage?.classList.add("is-dragging");
    drag = {
      mode,
      handle: handle || "",
      startX: event.clientX,
      startY: event.clientY,
      startCrop: { ...session.crop },
      box,
    };
  }

  function resizeCrop(start, handle, dxNorm, dyNorm) {
    let { x, y, w, h } = start;
    const right = x + w;
    const bottom = y + h;
    if (handle.includes("w")) {
      const nextX = Math.max(0, Math.min(right - MIN_CROP_EDGE, x + dxNorm));
      w = right - nextX;
      x = nextX;
    }
    if (handle.includes("e")) {
      w = Math.max(MIN_CROP_EDGE, Math.min(1 - x, w + dxNorm));
    }
    if (handle.includes("n")) {
      const nextY = Math.max(0, Math.min(bottom - MIN_CROP_EDGE, y + dyNorm));
      h = bottom - nextY;
      y = nextY;
    }
    if (handle.includes("s")) {
      h = Math.max(MIN_CROP_EDGE, Math.min(1 - y, h + dyNorm));
    }
    return clampCrop({ x, y, w, h });
  }

  colorHost?.addEventListener("input", syncLiveGradeFromUi);
  colorHost?.addEventListener("change", syncLiveGradeFromUi);
  colorHost?.addEventListener("click", (event) => {
    if (event.target?.closest?.("[data-quick-look-chip], #inspector-quick-look, #inspector-image-reset")) {
      window.setTimeout(() => syncLiveGradeFromUi(event), 0);
    }
  });

  viewport?.addEventListener("pointerdown", (event) => {
    if (!session) return;
    const handleEl = event.target?.closest?.("[data-handle]");
    if (handleEl) {
      beginDrag(event, "resize", handleEl.getAttribute("data-handle") || "");
      return;
    }
    beginDrag(event, "move", "");
  });

  stage?.addEventListener("pointerdown", (event) => {
    if (!session || event.button !== 0) return;
    if (event.target?.closest?.("#studio-collage-frame-viewport")) return;
    // Click outside viewport: start move using current crop (pan).
    beginDrag(event, "move", "");
  });

  stage?.addEventListener("pointermove", (event) => {
    if (!drag || !session) return;
    const dxNorm = (event.clientX - drag.startX) / Math.max(1, drag.box.width);
    const dyNorm = (event.clientY - drag.startY) / Math.max(1, drag.box.height);
    if (drag.mode === "resize") {
      session.crop = resizeCrop(drag.startCrop, drag.handle || "se", dxNorm, dyNorm);
    } else {
      session.crop = clampCrop({
        x: drag.startCrop.x + dxNorm,
        y: drag.startCrop.y + dyNorm,
        w: drag.startCrop.w,
        h: drag.startCrop.h,
      });
    }
    syncPanFromCrop();
    syncZoomFromCrop();
    paintViewport();
  });

  const endDrag = () => {
    drag = null;
    stage?.classList.remove("is-dragging");
  };
  stage?.addEventListener("pointerup", endDrag);
  stage?.addEventListener("pointercancel", endDrag);

  stage?.addEventListener(
    "wheel",
    (event) => {
      if (!session) return;
      event.preventDefault();
      const direction = event.deltaY < 0 ? 1 : -1;
      const factor = direction > 0 ? 0.92 : 1.08;
      const cx = session.crop.x + session.crop.w / 2;
      const cy = session.crop.y + session.crop.h / 2;
      const nextW = Math.max(MIN_CROP_EDGE, Math.min(1, session.crop.w * factor));
      const nextH = Math.max(MIN_CROP_EDGE, Math.min(1, session.crop.h * factor));
      session.crop = clampCrop({
        x: cx - nextW / 2,
        y: cy - nextH / 2,
        w: nextW,
        h: nextH,
      });
      syncPanFromCrop();
      syncZoomFromCrop();
      paintViewport();
    },
    { passive: false }
  );

  fitEl?.addEventListener("change", () => {
    if (!session) return;
    session.media.fit = fitEl.value === "fit" ? "fit" : "fill";
    // Reset to cell-locked window when switching fit mode, then user can free-resize again.
    session.crop = defaultCropFromCell();
    syncPanFromCrop();
    syncZoomFromCrop();
    paintViewport();
  });
  zoomEl?.addEventListener("input", () => {
    if (!session) return;
    const zoom = clampZoom(zoomEl.value);
    session.media.zoom = zoom;
    // Scale crop around center toward/away from cover size at this zoom.
    const box = imageContentRect();
    const cover = sourceWindow({
      sourceW: box?.nw || 1,
      sourceH: box?.nh || 1,
      cellW: session.cellW,
      cellH: session.cellH,
      fit: "fill",
      zoom,
      panX: session.media.pan_x,
      panY: session.media.pan_y,
    });
    // Keep free aspect: scale both edges by same factor relative to previous cover.
    const prev = sourceWindow({
      sourceW: box?.nw || 1,
      sourceH: box?.nh || 1,
      cellW: session.cellW,
      cellH: session.cellH,
      fit: "fill",
      zoom: 1,
      panX: 0.5,
      panY: 0.5,
    });
    const aspect = session.crop.w / Math.max(1e-6, session.crop.h);
    let nextW = cover.w;
    let nextH = cover.w / Math.max(1e-6, aspect);
    if (nextH > 1) {
      nextH = 1;
      nextW = aspect;
    }
    if (nextW > 1) {
      nextW = 1;
      nextH = 1 / Math.max(1e-6, aspect);
    }
    // Prefer cover-sized free aspect at this zoom level.
    void prev;
    const cx = session.crop.x + session.crop.w / 2;
    const cy = session.crop.y + session.crop.h / 2;
    session.crop = clampCrop({
      x: cx - nextW / 2,
      y: cy - nextH / 2,
      w: nextW,
      h: nextH,
    });
    syncPanFromCrop();
    paintViewport();
  });

  applyBtn?.addEventListener("click", () => {
    if (!session) return;
    const box = imageContentRect();
    const crop = clampCrop(session.crop);
    syncPanFromCrop();
    syncZoomFromCrop();
    const next = {
      ...session.media,
      crop,
      zoom: clampZoom(session.media.zoom),
      pan_x: clampPan(session.media.pan_x),
      pan_y: clampPan(session.media.pan_y),
    };
    const nw = box?.nw || 1;
    const nh = box?.nh || 1;
    const cropAspect = ((crop.w * nw) / Math.max(1e-6, crop.h * nh));
    const apply = session.onApply;
    close();
    apply?.(next, { cropAspect });
  });
  cancelBtn?.addEventListener("click", () => close());
  dialog?.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  window.addEventListener("resize", () => {
    if (session) paintViewport();
  });

  return {
    open,
    close,
    isOpen: () => Boolean(session),
    refreshGradePreview,
  };
}
