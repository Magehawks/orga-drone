/**
 * Collage framing interaction prefs (local to this browser / desktop profile).
 * Shared by Studio collage editor and Settings.
 */

export const FRAMING_PREF_KEY = "orga-drone:collage-framing";
export const FRAMING_MODIFIERS = Object.freeze(["none", "alt", "ctrl", "shift"]);

/**
 * @returns {{ panModifier: string, zoomModifier: string }}
 */
export function readFramingPrefs() {
  const fallback = { panModifier: "none", zoomModifier: "none" };
  try {
    const raw = localStorage.getItem(FRAMING_PREF_KEY);
    if (!raw) return { ...fallback };
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return { ...fallback };
    const panModifier = FRAMING_MODIFIERS.includes(parsed.panModifier)
      ? parsed.panModifier
      : "none";
    const zoomModifier = FRAMING_MODIFIERS.includes(parsed.zoomModifier)
      ? parsed.zoomModifier
      : "none";
    return { panModifier, zoomModifier };
  } catch {
    return { ...fallback };
  }
}

/**
 * @param {{ panModifier?: string, zoomModifier?: string }} next
 */
export function writeFramingPrefs(next) {
  const current = readFramingPrefs();
  const panModifier = FRAMING_MODIFIERS.includes(next?.panModifier)
    ? next.panModifier
    : current.panModifier;
  const zoomModifier = FRAMING_MODIFIERS.includes(next?.zoomModifier)
    ? next.zoomModifier
    : current.zoomModifier;
  const payload = { panModifier, zoomModifier };
  try {
    localStorage.setItem(FRAMING_PREF_KEY, JSON.stringify(payload));
  } catch {
    /* private mode / quota */
  }
  return payload;
}

/**
 * @param {string} modifier
 * @param {KeyboardEvent | MouseEvent | WheelEvent | PointerEvent} event
 */
export function modifierMatches(modifier, event) {
  const key = String(modifier || "none");
  if (key === "none") {
    return !event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey;
  }
  if (key === "alt") return Boolean(event.altKey) && !event.ctrlKey && !event.metaKey;
  if (key === "ctrl") return Boolean(event.ctrlKey || event.metaKey) && !event.altKey;
  if (key === "shift")
    return Boolean(event.shiftKey) && !event.altKey && !event.ctrlKey && !event.metaKey;
  return false;
}
