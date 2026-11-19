/**
 * Adaptive Studio editing context (#500 / #501).
 *
 * Photo context focuses color tools and still export; Story context keeps the
 * full timeline. Preference is per-project and never auto-switches merely
 * because another clip was added (#501). Clip grades stay on each clip's
 * effect_settings — there is no second grade store.
 */

export const CONTEXT_PHOTO = "photo";
export const CONTEXT_STORY = "story";

const STORAGE_PREFIX = "orga-drone.studio.editing-context.";

function clipKindOf(clip) {
  if (typeof clip === "string") return String(clip).toLowerCase();
  const kind = clip?.kind || clip?.dataset?.kind || clip?.item_kind || "";
  return String(kind).toLowerCase();
}

export function normalizeEditingContext(raw) {
  const value = String(raw || "")
    .trim()
    .toLowerCase();
  return value === CONTEXT_PHOTO ? CONTEXT_PHOTO : CONTEXT_STORY;
}

/** True when every present clip is a photo (empty project → false). */
export function projectSuggestsPhotoContext(clips) {
  const list = Array.isArray(clips) ? clips.filter(Boolean) : [];
  if (!list.length) return false;
  return list.every((clip) => clipKindOf(clip) === "photo");
}

/**
 * True when the project has at least one non-photo Story item (video, title,
 * collage). Used only for continuity hints — never to force a context switch.
 */
export function projectNeedsStoryTools(clips) {
  const list = Array.isArray(clips) ? clips.filter(Boolean) : [];
  return list.some((clip) => clipKindOf(clip) !== "photo");
}

export function storageKeyForProject(projectId) {
  const id = String(projectId || "").trim();
  return id ? `${STORAGE_PREFIX}${id}` : `${STORAGE_PREFIX}none`;
}

export function readStoredEditingContext(projectId, storage = globalThis.localStorage) {
  try {
    return normalizeEditingContext(storage?.getItem?.(storageKeyForProject(projectId)));
  } catch {
    return CONTEXT_STORY;
  }
}

export function writeStoredEditingContext(projectId, context, storage = globalThis.localStorage) {
  const next = normalizeEditingContext(context);
  try {
    storage?.setItem?.(storageKeyForProject(projectId), next);
  } catch {
    /* ignore quota / private mode */
  }
  return next;
}

/**
 * Resolve initial context: explicit stored preference wins; otherwise photo-only
 * projects open in photo context. Mixed media never clears a stored Photo focus.
 */
export function resolveInitialEditingContext({
  projectId,
  clips,
  stored = undefined,
  storage = globalThis.localStorage,
} = {}) {
  if (stored !== undefined && stored !== null && String(stored).trim() !== "") {
    return normalizeEditingContext(stored);
  }
  let fromStore;
  try {
    fromStore = storage?.getItem?.(storageKeyForProject(projectId));
  } catch {
    fromStore = undefined;
  }
  if (fromStore !== undefined && fromStore !== null && String(fromStore).trim() !== "") {
    return normalizeEditingContext(fromStore);
  }
  return projectSuggestsPhotoContext(clips) ? CONTEXT_PHOTO : CONTEXT_STORY;
}

export function createEditingContextController({
  root,
  projectId,
  getClips,
  onChange,
  storage = globalThis.localStorage,
  documentImpl = document,
} = {}) {
  let context = resolveInitialEditingContext({
    projectId,
    clips: typeof getClips === "function" ? getClips() : [],
    storage,
  });

  const photoBtn = documentImpl.getElementById("studio-context-photo");
  const storyBtn = documentImpl.getElementById("studio-context-story");
  const storyArea = documentImpl.querySelector(".studio-story-area");
  const continuityHint = documentImpl.getElementById("studio-context-continuity-hint");

  function currentClips() {
    return typeof getClips === "function" ? getClips() : [];
  }

  function apply() {
    if (root) {
      root.classList.toggle("is-photo-context", context === CONTEXT_PHOTO);
      root.classList.toggle("is-story-context", context === CONTEXT_STORY);
      root.dataset.editingContext = context;
    }
    if (photoBtn) {
      photoBtn.setAttribute("aria-pressed", context === CONTEXT_PHOTO ? "true" : "false");
      photoBtn.classList.toggle("is-active", context === CONTEXT_PHOTO);
    }
    if (storyBtn) {
      storyBtn.setAttribute("aria-pressed", context === CONTEXT_STORY ? "true" : "false");
      storyBtn.classList.toggle("is-active", context === CONTEXT_STORY);
    }
    if (storyArea) {
      storyArea.hidden = false;
      storyArea.setAttribute("aria-hidden", context === CONTEXT_PHOTO ? "true" : "false");
    }
    if (continuityHint) {
      const showHint = context === CONTEXT_PHOTO && projectNeedsStoryTools(currentClips());
      continuityHint.hidden = !showHint;
    }
    if (typeof onChange === "function") onChange(context);
  }

  function setContext(next, { persist = true } = {}) {
    const normalized = normalizeEditingContext(next);
    if (normalized === context) {
      apply();
      return context;
    }
    context = normalized;
    if (persist) writeStoredEditingContext(projectId, context, storage);
    apply();
    return context;
  }

  photoBtn?.addEventListener("click", () => setContext(CONTEXT_PHOTO));
  storyBtn?.addEventListener("click", () => setContext(CONTEXT_STORY));

  apply();

  return {
    getContext: () => context,
    setContext,
    isPhoto: () => context === CONTEXT_PHOTO,
    isStory: () => context === CONTEXT_STORY,
    /** Re-apply DOM classes after layout / clip-list changes; never auto-switch. */
    refresh() {
      apply();
    },
  };
}
