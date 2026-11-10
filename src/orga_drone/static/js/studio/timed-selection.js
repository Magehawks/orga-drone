/**
 * Minimal timed-element selection helpers for timeline-first Studio UX (#334/#339).
 * Pure state helpers only — persistence and DOM wiring stay in the entry.
 */

export const TIMED_KINDS = Object.freeze([
  "ramp",
  "zoom",
  "mask",
  "slow",
  "color",
  "overlay",
  "audio",
  "music",
]);

/** Effect-lane bars that share the Phase-2 timeline-first contract. */
export const EFFECT_BAR_KINDS = Object.freeze(["zoom", "mask", "slow", "color"]);

/** Kinds that Delete/Backspace may remove without touching the story clip. */
export const TIMED_DELETE_KINDS = Object.freeze(["ramp", "overlay", ...EFFECT_BAR_KINDS]);

export function createTimedSelection(value = null) {
  if (!value || typeof value !== "object") return null;
  const kind = String(value.kind || "");
  if (!TIMED_KINDS.includes(kind)) return null;
  const clipId = value.clipId === null || value.clipId === undefined ? "" : String(value.clipId);
  const id = value.id === null || value.id === undefined ? "" : String(value.id);
  if (kind !== "music" && !clipId) return null;
  return { kind, clipId, id };
}

export function timedSelectionMatches(selection, kind, clipId, id = "") {
  if (!selection) return false;
  return (
    selection.kind === kind &&
    String(selection.clipId) === String(clipId || "") &&
    String(selection.id || "") === String(id || "")
  );
}

export function isEffectBarKind(kind) {
  return EFFECT_BAR_KINDS.includes(String(kind || ""));
}

export function isOverlayTimedKind(kind) {
  return String(kind || "") === "overlay";
}

/** Existing inspector tab for a timed effect kind. */
export function timedEffectInspectorTab(kind) {
  const value = String(kind || "");
  if (value === "zoom") return "image";
  if (value === "mask" || value === "color") return "effects";
  if (value === "overlay") return "overlays";
  return "clip";
}

/**
 * True when Delete/Backspace must edit text or stay inside a dialog / draft.
 */
export function shouldIgnoreDeleteShortcut(
  active,
  { dialogOpen = false, reuseDraft = false } = {}
) {
  if (reuseDraft) return true;
  if (dialogOpen) return true;
  if (!active) return false;
  if (active.isContentEditable === true) return true;
  if (typeof active.closest === "function" && active.closest("dialog")) return true;
  const tag = active.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag !== "INPUT") return false;
  const type = String(active.type || "text").toLowerCase();
  return (
    type !== "range" &&
    type !== "checkbox" &&
    type !== "radio" &&
    type !== "button" &&
    type !== "submit" &&
    type !== "file" &&
    type !== "color"
  );
}

/**
 * Decide which deletion path owns a Delete/Backspace press.
 * Story-clip removal stays Delete-only and requires story focus.
 * timedSelection is the sole authority for timed-effect deletion; legacy
 * selectedEffectBar must not delete after an ordinary clip switch.
 */
export function resolveDeleteAction({
  key,
  timedSelection,
  hasEffectBarSelection = false,
  privacyMaskActive = false,
  storyClipFocused = false,
  hasSelectedStoryClip = false,
} = {}) {
  void hasEffectBarSelection;
  if (key !== "Delete" && key !== "Backspace") return null;
  if (timedSelection && TIMED_DELETE_KINDS.includes(timedSelection.kind)) {
    if (timedSelection.kind === "ramp") return "ramp";
    if (timedSelection.kind === "overlay") return "overlay";
    return "effect-bar";
  }
  if (privacyMaskActive) return "mask";
  if (key === "Delete" && storyClipFocused && hasSelectedStoryClip) return "story-clip";
  return null;
}

/**
 * True when an in-flight timed removal still owns the live selection.
 * Prevents async success/failure handlers from overwriting a newer choice.
 */
export function isActiveTimedSelection(current, pending) {
  if (!pending) return false;
  return timedSelectionMatches(current, pending.kind, pending.clipId, pending.id);
}

/**
 * Persist a timed-selection removal without clearing selection first.
 * On save failure the prior selection is returned so Delete/Backspace can retry.
 */
export async function persistTimedSelectionRemoval(selection, save) {
  if (!selection) return { ok: false, selection: null };
  try {
    await save(selection);
    return { ok: true, selection: null };
  } catch (error) {
    return { ok: false, selection, error };
  }
}
