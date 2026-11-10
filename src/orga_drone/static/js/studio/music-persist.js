/**
 * Playlist-scoped soundtrack mutation revisions (#339 Phase 4 re-review).
 * Pure helpers only — fetch/DOM wiring stays in the entry.
 */

/** Bump the single project playlist revision; returns the new value. */
export function bumpMusicPlaylistRevision(box) {
  const next = (Number(box?.value) || 0) + 1;
  if (box && typeof box === "object") box.value = next;
  return next;
}

export function musicPlaylistRevisionOf(box) {
  return Number(box?.value) || 0;
}

/** True when a successful playlist response still owns the latest local mutation. */
export function shouldApplyMusicPlaylistResponse(localRevision, mutationRevision) {
  return Number(localRevision) === Number(mutationRevision);
}

/** Drop one soundtrack id from a local playlist without touching other fields. */
export function applyDeletedMusicTrack(tracks, trackId) {
  const id = String(trackId || "");
  const list = Array.isArray(tracks) ? tracks.slice() : [];
  if (!id) return list;
  return list.filter((track) => String(track?.id) !== id);
}

/**
 * After a successful DELETE, either take the server playlist (current mutation)
 * or remove only the deleted id so newer local edits stay intact.
 */
export function resolveMusicDeleteSuccess({
  localRevision,
  mutationRevision,
  currentTracks,
  responseTracks,
  trackId,
} = {}) {
  if (shouldApplyMusicPlaylistResponse(localRevision, mutationRevision)) {
    return {
      tracks: Array.isArray(responseTracks) ? responseTracks.slice() : [],
      mode: "full",
    };
  }
  return {
    tracks: applyDeletedMusicTrack(currentTracks, trackId),
    mode: "local-remove",
  };
}

/**
 * Filter a server playlist so ids removed by a newer successful DELETE cannot
 * be resurrected by a stale add/patch/reorder payload.
 */
export function filterResurrectedMusicTracks(tracks, removedIds) {
  const list = Array.isArray(tracks) ? tracks : [];
  if (!removedIds || typeof removedIds.has !== "function" || removedIds.size === 0) {
    return list.slice();
  }
  return list.filter((track) => !removedIds.has(String(track?.id)));
}
