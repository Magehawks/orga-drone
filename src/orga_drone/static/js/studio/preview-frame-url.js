/** Build Studio preview-frame URLs with optional Story clock (#358). */

/**
 * Quantize source/story preview times to 0.1 s (matches server preview cache).
 * @param {unknown} value
 * @returns {number}
 */
export function quantizePreviewTime(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.round(n * 10) / 10;
}

/**
 * @param {string|number} studioId
 * @param {{
 *   t_s?: number|string|null,
 *   story_s?: number|string|null,
 *   detail?: number|string|null,
 *   before?: boolean,
 *   expectedRevision?: number|string|null,
 * }} [opts]
 * @returns {string}
 */
export function buildPreviewFrameUrl(studioId, opts = {}) {
  const params = new URLSearchParams();
  if (opts.t_s !== null && opts.t_s !== undefined && opts.t_s !== "") {
    const t = Number(opts.t_s);
    if (Number.isFinite(t)) params.set("t_s", String(t));
  }
  if (opts.story_s !== null && opts.story_s !== undefined && opts.story_s !== "") {
    const story = Number(opts.story_s);
    if (Number.isFinite(story)) params.set("story_s", String(story));
  }
  if (opts.detail !== null && opts.detail !== undefined && opts.detail !== "") {
    params.set("detail", String(opts.detail));
  }
  if (opts.before) params.set("before", "1");
  if (
    opts.expectedRevision !== null &&
    opts.expectedRevision !== undefined &&
    opts.expectedRevision !== ""
  ) {
    params.set("expected_revision", String(opts.expectedRevision));
  }
  return `/api/studio/${encodeURIComponent(String(studioId))}/preview-frame?${params.toString()}`;
}
