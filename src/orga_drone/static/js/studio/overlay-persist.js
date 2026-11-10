/**
 * Clip-scoped overlay mutation revisions for serialized Studio saves (#339).
 * Pure helpers only — fetch/DOM wiring stays in the entry.
 */

export function bumpOverlayRevision(revisions, clipId) {
  const key = String(clipId || "");
  const next = (Number(revisions.get(key)) || 0) + 1;
  revisions.set(key, next);
  return next;
}

export function overlayRevisionOf(revisions, clipId) {
  return Number(revisions.get(String(clipId || ""))) || 0;
}

/** True when a successful PATCH still owns the latest local overlay mutation. */
export function shouldApplyOverlayResponse(localRevision, savedRevision) {
  return Number(localRevision) === Number(savedRevision);
}

/** True when a failed save may restore the pre-mutation snapshot. */
export function shouldRollbackOverlayMutation(localRevision, mutationRevision) {
  return Number(localRevision) === Number(mutationRevision);
}

/**
 * Restore a full prior overlay array only when this mutation still owns the clip.
 * Returns null when a newer local edit must be kept.
 */
export function rollbackOverlaysIfCurrent({ localRevision, mutationRevision, previous } = {}) {
  if (!shouldRollbackOverlayMutation(localRevision, mutationRevision)) return null;
  return Array.isArray(previous) ? previous : null;
}

/**
 * After a failed removal where newer edits exist, re-insert only the removed
 * overlay so Delete/Backspace can retry without wiping those edits.
 */
export function restoreRemovedOverlay(current, previous, overlayId) {
  const id = String(overlayId || "");
  const list = Array.isArray(current) ? current.slice() : [];
  if (!id || list.some((item) => String(item.id) === id)) return list;
  const prior = Array.isArray(previous) ? previous : [];
  const entry = prior.find((item) => String(item.id) === id);
  if (!entry) return list;
  const index = prior.findIndex((item) => String(item.id) === id);
  list.splice(Math.min(Math.max(0, index), list.length), 0, entry);
  return list;
}
