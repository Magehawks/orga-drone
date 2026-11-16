/** Pure collage layout helpers (ADR 0038). Mirror of studio_collage.py geometry. */

export const PRESET_NAMES = Object.freeze([
  "1+1",
  "2+1",
  "1+2",
  "2x2",
  "3x2",
  "1+2+1",
  "3|2",
  "3|1+2",
]);

export const MIN_RATIO = 0.05;
export const MAX_RATIO = 0.95;
export const MIN_LEAF_ZOOM = 1;
export const MAX_LEAF_ZOOM = 3;

/**
 * Normalized source crop window. Mirrors ``studio_collage.source_window``.
 * @param {{
 *   sourceW: number,
 *   sourceH: number,
 *   cellW: number,
 *   cellH: number,
 *   fit?: string,
 *   zoom?: number,
 *   panX?: number,
 *   panY?: number,
 * }} args
 * @returns {{ x: number, y: number, w: number, h: number }}
 */
export function sourceWindow({
  sourceW,
  sourceH,
  cellW,
  cellH,
  fit = "fill",
  zoom = 1,
  panX = 0.5,
  panY = 0.5,
}) {
  const sw = Math.max(1, Math.floor(Number(sourceW) || 1));
  const sh = Math.max(1, Math.floor(Number(sourceH) || 1));
  const cw = Math.max(1, Math.floor(Number(cellW) || 1));
  const ch = Math.max(1, Math.floor(Number(cellH) || 1));
  const zRaw = Number(zoom);
  const z = Math.max(MIN_LEAF_ZOOM, Math.min(MAX_LEAF_ZOOM, Number.isFinite(zRaw) ? zRaw : 1));
  const pxRaw = Number(panX);
  const pyRaw = Number(panY);
  const px = Math.max(0, Math.min(1, Number.isFinite(pxRaw) ? pxRaw : 0.5));
  const py = Math.max(0, Math.min(1, Number.isFinite(pyRaw) ? pyRaw : 0.5));
  const srcAspect = sw / sh;
  const cellAspect = cw / ch;
  const mode = String(fit || "fill")
    .trim()
    .toLowerCase();
  let winW;
  let winH;
  if (mode === "fit") {
    winW = 1 / z;
    winH = 1 / z;
  } else if (srcAspect > cellAspect) {
    const baseH = 1;
    const baseW = cellAspect / srcAspect;
    winW = Math.min(1, baseW / z);
    winH = Math.min(1, baseH / z);
  } else {
    const baseW = 1;
    const baseH = srcAspect / cellAspect;
    winW = Math.min(1, baseW / z);
    winH = Math.min(1, baseH / z);
  }
  const minEdge = 1 / Math.max(sw, sh);
  winW = Math.min(1, Math.max(minEdge, winW));
  winH = Math.min(1, Math.max(minEdge, winH));
  const maxX = Math.max(0, 1 - winW);
  const maxY = Math.max(0, 1 - winH);
  return { x: px * maxX, y: py * maxY, w: winW, h: winH };
}

/**
 * Prefer an explicit free ``crop`` rect on media; otherwise Fit/Fill zoom/pan.
 * @param {any} media
 * @param {{ sourceW: number, sourceH: number, cellW: number, cellH: number }} args
 */
export function mediaSourceWindow(media, { sourceW, sourceH, cellW, cellH }) {
  const crop = media && media.crop;
  if (crop && typeof crop === "object") {
    const x = Number(crop.x);
    const y = Number(crop.y);
    const w = Number(crop.w);
    const h = Number(crop.h);
    if (Number.isFinite(x) && Number.isFinite(y) && w > 0 && h > 0) {
      const nx = Math.max(0, Math.min(1, x));
      const ny = Math.max(0, Math.min(1, y));
      const nw = Math.max(1e-6, Math.min(1 - nx, w));
      const nh = Math.max(1e-6, Math.min(1 - ny, h));
      return { x: nx, y: ny, w: nw, h: nh };
    }
  }
  return sourceWindow({
    sourceW,
    sourceH,
    cellW,
    cellH,
    fit: media?.fit,
    zoom: media?.zoom,
    panX: media?.pan_x,
    panY: media?.pan_y,
  });
}

/**
 * Reset a leaf thumb to a clipped cover/contain fallback.
 * Never uses CSS scale — that diverges from server crop math and bleeds into neighbors.
 * @param {HTMLImageElement} img
 * @param {any} media
 */
export function resetLeafThumbFraming(img, media) {
  if (!img) return;
  const fit = String(media?.fit || "fill").toLowerCase() === "fit" ? "fit" : "fill";
  img.style.position = "absolute";
  img.style.inset = "0";
  img.style.left = "0";
  img.style.top = "0";
  img.style.right = "0";
  img.style.bottom = "0";
  img.style.width = "100%";
  img.style.height = "100%";
  img.style.objectFit = fit === "fit" ? "contain" : "cover";
  img.style.objectPosition = "50% 50%";
  img.style.transform = "";
  img.style.transformOrigin = "";
}

/**
 * CSS placement for a leaf thumb so the crop matches ``sourceWindow``.
 * Used only while framing live; idle view relies on the graded composed still.
 * @param {HTMLImageElement} img
 * @param {any} media
 * @param {number} cellW
 * @param {number} cellH
 */
export function applyLeafThumbFraming(img, media, cellW, cellH) {
  if (!img || !media) return;
  const nw = Math.max(1, Number(img.naturalWidth) || 0);
  const nh = Math.max(1, Number(img.naturalHeight) || 0);
  // Until the thumb has decoded, keep the simple visible fallback.
  if (!img.naturalWidth || !img.naturalHeight) {
    resetLeafThumbFraming(img, media);
    return;
  }
  const cw = Math.max(1, Number(cellW) || 1);
  const ch = Math.max(1, Number(cellH) || 1);
  const win = mediaSourceWindow(media, {
    sourceW: nw,
    sourceH: nh,
    cellW: cw,
    cellH: ch,
  });
  if (!(win.w > 0) || !(win.h > 0)) {
    resetLeafThumbFraming(img, media);
    return;
  }
  img.style.position = "absolute";
  img.style.inset = "auto";
  img.style.right = "auto";
  img.style.bottom = "auto";
  img.style.width = `${100 / win.w}%`;
  img.style.height = `${100 / win.h}%`;
  img.style.left = `${(-100 * win.x) / win.w}%`;
  img.style.top = `${(-100 * win.y) / win.h}%`;
  img.style.objectFit = "fill";
  img.style.objectPosition = "0 0";
  img.style.transform = "";
  img.style.transformOrigin = "";
}

/**
 * @typedef {{ x: number, y: number, w: number, h: number }} CollageRect
 */

/**
 * @param {any} node
 * @returns {any[]}
 */
export function iterLeaves(node) {
  if (!node || typeof node !== "object") return [];
  if (node.type === "leaf") return [node];
  if (node.type === "split") {
    return [...iterLeaves(node.a), ...iterLeaves(node.b)];
  }
  return [];
}

/**
 * @param {any} node
 * @param {number} x
 * @param {number} y
 * @param {number} w
 * @param {number} h
 * @param {number} gap
 * @param {Record<string, CollageRect>} out
 */
function resolveNode(node, x, y, w, h, gap, out) {
  if (!node || w <= 0 || h <= 0) return;
  if (node.type === "leaf") {
    out[String(node.id)] = { x, y, w, h };
    return;
  }
  const ratio = Math.max(MIN_RATIO, Math.min(MAX_RATIO, Number(node.ratio) || 0.5));
  if (node.dir === "h") {
    const usable = w - gap;
    if (usable <= 1) {
      resolveNode(node.a, x, y, w, h, gap, out);
      return;
    }
    const first = Math.max(1, Math.min(usable - 1, Math.round(usable * ratio)));
    const second = usable - first;
    resolveNode(node.a, x, y, first, h, gap, out);
    resolveNode(node.b, x + first + gap, y, second, h, gap, out);
    return;
  }
  const usable = h - gap;
  if (usable <= 1) {
    resolveNode(node.a, x, y, w, h, gap, out);
    return;
  }
  const first = Math.max(1, Math.min(usable - 1, Math.round(usable * ratio)));
  const second = usable - first;
  resolveNode(node.a, x, y, w, first, gap, out);
  resolveNode(node.b, x, y + first + gap, w, second, gap, out);
}

/**
 * @param {any} spec
 * @param {number} width
 * @param {number} height
 * @returns {Record<string, CollageRect>}
 */
export function resolveRects(spec, width, height) {
  const out = {};
  if (!spec || !spec.root) return out;
  const gap = Math.max(0, Number(spec.gap_px) || 0);
  resolveNode(spec.root, 0, 0, Math.max(1, width | 0), Math.max(1, height | 0), gap, out);
  return out;
}

/**
 * @param {any} node
 * @param {string} splitId
 * @param {number} ratio
 * @returns {boolean}
 */
function setRatioNode(node, splitId, ratio) {
  if (!node || node.type !== "split") return false;
  if (String(node.id) === String(splitId)) {
    node.ratio = Math.max(MIN_RATIO, Math.min(MAX_RATIO, ratio));
    return true;
  }
  return setRatioNode(node.a, splitId, ratio) || setRatioNode(node.b, splitId, ratio);
}

/**
 * @param {any} spec
 * @param {string} splitId
 * @param {number} ratio
 * @returns {any}
 */
export function setSplitRatio(spec, splitId, ratio) {
  const next = structuredClone(spec);
  if (!setRatioNode(next.root, splitId, ratio)) {
    throw new Error("split not found");
  }
  return next;
}

/**
 * Collect divider hit targets for pointer editing.
 * @param {any} node
 * @param {number} x
 * @param {number} y
 * @param {number} w
 * @param {number} h
 * @param {number} gap
 * @param {Array<object>} out
 */
export function collectDividers(node, x, y, w, h, gap, out = []) {
  if (!node || node.type !== "split") return out;
  const ratio = Math.max(MIN_RATIO, Math.min(MAX_RATIO, Number(node.ratio) || 0.5));
  if (node.dir === "h") {
    const usable = w - gap;
    if (usable > 1) {
      const first = Math.max(1, Math.min(usable - 1, Math.round(usable * ratio)));
      out.push({
        id: String(node.id),
        dir: "h",
        x: x + first,
        y,
        w: Math.max(gap, 6),
        h,
        ratio,
        span: usable,
        origin: x,
      });
      collectDividers(node.a, x, y, first, h, gap, out);
      collectDividers(node.b, x + first + gap, y, usable - first, h, gap, out);
    }
  } else {
    const usable = h - gap;
    if (usable > 1) {
      const first = Math.max(1, Math.min(usable - 1, Math.round(usable * ratio)));
      out.push({
        id: String(node.id),
        dir: "v",
        x,
        y: y + first,
        w,
        h: Math.max(gap, 6),
        ratio,
        span: usable,
        origin: y,
      });
      collectDividers(node.a, x, y, w, first, gap, out);
      collectDividers(node.b, x, y + first + gap, w, usable - first, gap, out);
    }
  }
  return out;
}

/**
 * @param {any} spec
 * @returns {string}
 */
export function aspectCss(spec) {
  const aspect = spec?.aspect;
  if (aspect && typeof aspect === "object" && aspect.w && aspect.h) {
    return `${aspect.w} / ${aspect.h}`;
  }
  if (aspect === "9:16") return "9 / 16";
  if (aspect === "1:1") return "1 / 1";
  return "16 / 9";
}
