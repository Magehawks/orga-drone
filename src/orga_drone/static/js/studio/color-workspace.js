/** Pure helpers for Creative/Pro color workspace UI races and grade summary. */

import { formatTemplate } from "./format.js";

export function beginRequestToken(store, key) {
  const id = String(key);
  const next = (Number(store.get(id)) || 0) + 1;
  store.set(id, next);
  return next;
}

export function isCurrentRequestToken(store, key, token) {
  return store.get(String(key)) === token;
}

export function shouldRefreshColorInspector({ clipId, selectedId, requestCurrent }) {
  if (!requestCurrent) return false;
  if (clipId === null || clipId === undefined) return false;
  if (selectedId === null || selectedId === undefined || selectedId === "") return false;
  return String(clipId) === String(selectedId);
}

/**
 * @param {{
 *   lookId?: string,
 *   lookName?: string,
 *   basicActive?: boolean,
 *   conversionOn?: boolean,
 *   creativeLutOn?: boolean,
 *   hslActive?: boolean,
 *   wheelsActive?: boolean,
 *   tonalActive?: boolean,
 *   detailActive?: boolean,
 *   bwActive?: boolean,
 * }} state
 * @param {{
 *   look?: string,
 *   sliders?: string,
 *   conversion?: string,
 *   creativeLut?: string,
 *   hsl?: string,
 *   wheels?: string,
 *   tonal?: string,
 *   detail?: string,
 *   bw?: string,
 * }} labels
 */
export function buildColorGradeSummaryParts(state, labels = {}) {
  const parts = [];
  const lookId = String(state.lookId || "");
  if (lookId) {
    parts.push(
      formatTemplate(labels.look || "Look: {name}", {
        name: state.lookName || lookId,
      })
    );
  } else if (state.basicActive) {
    parts.push(labels.sliders || "Manual sliders");
  }
  if (state.conversionOn) parts.push(labels.conversion || "Camera conversion on");
  if (state.creativeLutOn) parts.push(labels.creativeLut || "Creative LUT on");
  if (state.hslActive) parts.push(labels.hsl || "HSL active");
  if (state.wheelsActive) parts.push(labels.wheels || "Color wheels active");
  if (state.tonalActive) parts.push(labels.tonal || "Fine-tune active");
  if (state.detailActive) parts.push(labels.detail || "Sharpen or denoise on");
  if (state.bwActive) parts.push(labels.bw || "Black-and-white ramp on");
  return parts;
}

export function formatColorGradeSummary(parts, neutralLabel) {
  return parts && parts.length ? parts.join(" · ") : neutralLabel || "No color changes yet";
}
