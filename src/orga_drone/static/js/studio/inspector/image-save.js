import { createSaver } from "../settings.js";

const DEFAULT_ERROR = "Could not save image adjustments.";

function noop() {}

export function createImageAdjustSaver({
  getClipById = () => null,
  readAdjust = () => null,
  writeAdjust = noop,
  isSelected = () => false,
  fill = noop,
  refreshPreview = noop,
  setSaved = noop,
  showError = noop,
  errorMessage = DEFAULT_ERROR,
  headers,
  fetchImpl,
  readJson,
  debounceMs = 0,
  setTimeoutImpl,
  clearTimeoutImpl,
  serialize,
  getSharedChain,
} = {}) {
  const pendingClips = new Map();

  function keyOf(studioId) {
    return String(studioId);
  }

  const saver = createSaver({
    url: (studioId) => `/api/studio/${studioId}/image`,
    method: "PATCH",
    payload: (studioId) => {
      const clip = getClipById(studioId);
      if (!clip) return null;
      pendingClips.set(keyOf(studioId), { clip, wrote: false });
      return readAdjust(clip);
    },
    apply: (studioId, body, requestBody) => {
      const pending = pendingClips.get(keyOf(studioId));
      if (!pending) return false;
      if (JSON.stringify(readAdjust(pending.clip)) === JSON.stringify(requestBody)) {
        writeAdjust(pending.clip, body.image || requestBody, true);
        pending.wrote = true;
      }
      return true;
    },
    refresh: (studioId) => {
      const key = keyOf(studioId);
      const pending = pendingClips.get(key);
      if (!pending) return;
      pendingClips.delete(key);
      if (isSelected(studioId)) fill(pending.clip);
      refreshPreview(pending.clip);
      if (pending.wrote) setSaved(true);
    },
    errorMessage,
    onError: (err, studioId) => {
      pendingClips.delete(keyOf(studioId));
      showError((err && err.message) || errorMessage);
    },
    headers,
    fetchImpl,
    readJson,
    debounceMs,
    setTimeoutImpl,
    clearTimeoutImpl,
    serialize,
    getChain: getSharedChain,
  });

  return {
    queue: (studioId) => saver.queue(studioId),
    flush: saver.flush,
    whenIdle: saver.whenIdle,
  };
}
