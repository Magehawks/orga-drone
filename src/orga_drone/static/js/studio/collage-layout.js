/** Pure collage layout helpers (ADR 0038). Mirror of studio_collage.py geometry. */

export const PRESET_NAMES = Object.freeze([
  "1+1",
  "2+1",
  "1+2",
  "2x2",
  "3x2",
  "1+2+1",
  "3|2",
]);

export const MIN_RATIO = 0.05;
export const MAX_RATIO = 0.95;

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
