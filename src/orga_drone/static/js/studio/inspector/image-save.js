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
  leafIdFor = () => null,
  queuedPayloadFor = () => null,
  onResponse = noop,
  allowWithoutLeaf = () => true,
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

  function keyOf(studioId, leafId) {
    return `${String(studioId)}:${leafId || ""}`;
  }

  const saver = createSaver({
    url: (studioId) => `/api/studio/${studioId}/image`,
    method: "PATCH",
    payload: (studioId) => {
      const clip = getClipById(studioId);
      if (!clip) return null;
      const queued = queuedPayloadFor(studioId);
      const adjust = (queued && queued.adjust) || readAdjust(clip);
      if (!adjust) return null;
      const leafId =
        queued && Object.prototype.hasOwnProperty.call(queued, "leafId")
          ? queued.leafId
          : leafIdFor(studioId);
      if (!allowWithoutLeaf(studioId, leafId)) return null;
      pendingClips.set(keyOf(studioId, leafId), {
        clip,
        wrote: false,
        adjust,
        leafId,
      });
      if (leafId) return { ...adjust, leaf_id: leafId };
      return adjust;
    },
    apply: (studioId, body, requestBody) => {
      const leafId = requestBody && requestBody.leaf_id ? String(requestBody.leaf_id) : "";
      const pending = pendingClips.get(keyOf(studioId, leafId));
      if (!pending) return false;
      const sent = { ...(requestBody || {}) };
      delete sent.leaf_id;
      const currentLeaf = leafIdFor(studioId);
      const stillSameLeaf = !leafId || String(currentLeaf || "") === String(leafId);
      if (stillSameLeaf && JSON.stringify(readAdjust(pending.clip)) === JSON.stringify(sent)) {
        writeAdjust(pending.clip, body.image || sent, true);
        pending.wrote = true;
      }
      onResponse(pending.clip, body);
      return true;
    },
    refresh: (studioId) => {
      // Flush any pending keys for this studio id (with/without leaf).
      for (const [key, pending] of [...pendingClips.entries()]) {
        if (!key.startsWith(`${String(studioId)}:`)) continue;
        pendingClips.delete(key);
        if (isSelected(studioId)) fill(pending.clip);
        refreshPreview(pending.clip);
        if (pending.wrote) setSaved(true);
      }
    },
    errorMessage,
    onError: (err, studioId) => {
      for (const key of [...pendingClips.keys()]) {
        if (key.startsWith(`${String(studioId)}:`)) pendingClips.delete(key);
      }
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
