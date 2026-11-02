/**
 * Read-only and narrow write access to Studio clip `data-*` fields.
 *
 * The DOM dataset remains the source of truth in this step. These helpers do
 * not cache clip state, start requests, or persist anything.
 *
 * @typedef {HTMLElement & {dataset: DOMStringMap}} StudioClipElement
 */

const WRITABLE_FIELDS = new Set([
  "photoDuration",
  "effectiveDuration",
  "title",
  "subtitle",
  "background",
  "displayTitle",
  "displaySubtitle",
]);

function isNullish(value) {
  return value === null || value === undefined;
}

function readString(clip, field) {
  if (!clip || !clip.dataset) return "";
  return clip.dataset[field] || "";
}

function readPositiveNumber(clip, field) {
  if (!clip || !clip.dataset) return null;
  const raw = clip.dataset[field];
  if (raw === "" || isNullish(raw)) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/**
 * @param {ParentNode | null | undefined} scope
 * @returns {StudioClipElement[]}
 */
export function listClipElements(scope) {
  if (!scope || typeof scope.querySelectorAll !== "function") return [];
  return Array.from(scope.querySelectorAll(".studio-clip"));
}

/**
 * @param {ParentNode | null | undefined} scope
 * @param {string | number | null | undefined} id
 * @returns {StudioClipElement | null}
 */
export function findClip(scope, id) {
  const target = String(isNullish(id) ? "" : id);
  return listClipElements(scope).find((clip) => clipId(clip) === target) || null;
}

/** @returns {string} */
export function clipId(clip) {
  return readString(clip, "studioId");
}

/** @returns {string} */
export function clipKind(clip) {
  return readString(clip, "kind") || "unknown";
}

/** @returns {boolean} */
export function clipIsAvailable(clip) {
  return readString(clip, "available") === "1";
}

/** @returns {boolean} */
export function clipCanPlay(clip) {
  return readString(clip, "canPlay") === "1";
}

/** @returns {boolean} */
export function clipHasProxy(clip) {
  return readString(clip, "hasProxy") === "1";
}

/** @returns {number | null} */
export function clipMediaId(clip) {
  return readPositiveNumber(clip, "mediaId");
}

/** @returns {string} */
export function clipFilename(clip) {
  return readString(clip, "filename");
}

/** @returns {string} */
export function clipDisplayTitle(clip) {
  return readString(clip, "displayTitle");
}

/** @returns {string} */
export function clipDisplaySubtitle(clip) {
  return readString(clip, "displaySubtitle");
}

/** @returns {number | null} */
export function clipEffectiveDuration(clip) {
  return readPositiveNumber(clip, "effectiveDuration");
}

/** @returns {number} */
export function clipSourceIn(clip) {
  if (!clip || !clip.dataset) return 0;
  const raw = clip.dataset.sourceIn;
  if (raw === "" || isNullish(raw)) return 0;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

/** @returns {number | null} */
export function clipSourceOut(clip) {
  return readPositiveNumber(clip, "sourceOut");
}

/** @returns {number | null} */
export function clipMediaDuration(clip) {
  return readPositiveNumber(clip, "mediaDuration");
}

/** @returns {0.5 | 0.25 | 1} */
export function clipPlaybackSpeed(clip) {
  const value = Number(clip && clip.dataset && clip.dataset.playbackSpeed);
  if (value === 0.5 || value === 0.25) return value;
  return 1;
}

/** @returns {number | null} */
export function clipPhotoDuration(clip) {
  return readPositiveNumber(clip, "photoDuration");
}

/** @returns {string} */
export function clipStreamUrl(clip) {
  return readString(clip, "streamUrl");
}

/** @returns {string} */
export function clipProxyUrl(clip) {
  return readString(clip, "proxyUrl");
}

/** @returns {string} */
export function clipPreviewUrl(clip) {
  return readString(clip, "previewUrl");
}

/** @returns {string} */
export function clipThumbUrl(clip) {
  return readString(clip, "thumb");
}

/**
 * Story duration fallback used by the current Timeline and Inspector code.
 *
 * @param {StudioClipElement | null | undefined} clip
 * @param {number} defaultPhotoDuration
 * @returns {number}
 */
export function clipDuration(clip, defaultPhotoDuration) {
  if (!clip || !clip.dataset) return 0;
  const raw = clip.dataset.effectiveDuration;
  if (raw === "" || isNullish(raw)) {
    const kind = clipKind(clip);
    if (kind === "photo") return defaultPhotoDuration;
    if (kind === "title_card") return 3;
    return 0;
  }
  const value = Number(raw);
  if (Number.isFinite(value) && value > 0) return value;
  return clipKind(clip) === "title_card" ? 3 : 0;
}

/**
 * Write one supported dataset field without persistence or layout side effects.
 *
 * @param {StudioClipElement | null | undefined} clip
 * @param {string} field
 * @param {unknown} value
 * @returns {boolean}
 */
export function setClipField(clip, field, value) {
  if (!clip || !clip.dataset || !WRITABLE_FIELDS.has(field)) return false;
  clip.dataset[field] = isNullish(value) ? "" : String(value);
  return true;
}
