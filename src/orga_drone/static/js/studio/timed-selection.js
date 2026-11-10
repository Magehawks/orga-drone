/**
 * Minimal timed-element selection helpers for timeline-first Studio UX (#334).
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

export function createTimedSelection(value = null) {
  if (!value || typeof value !== "object") return null;
  const kind = String(value.kind || "");
  if (!TIMED_KINDS.includes(kind)) return null;
  const clipId = value.clipId == null ? "" : String(value.clipId);
  const id = value.id == null ? "" : String(value.id);
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
 */
export function resolveDeleteAction({
  key,
  timedSelection,
  hasEffectBarSelection = false,
  privacyMaskActive = false,
  storyClipFocused = false,
  hasSelectedStoryClip = false,
} = {}) {
  if (key !== "Delete" && key !== "Backspace") return null;
  if (timedSelection && timedSelection.kind === "ramp") return "ramp";
  if (key === "Delete" && hasEffectBarSelection) return "effect-bar";
  if (privacyMaskActive) return "mask";
  if (key === "Delete" && storyClipFocused && hasSelectedStoryClip) return "story-clip";
  return null;
}
