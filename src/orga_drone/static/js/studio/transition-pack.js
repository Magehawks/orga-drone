/** Drone-pack overlap transitions. Same occupancy as a crossfade. */

export const OVERLAP_TYPES = new Set([
  "crossfade",
  "blur_dissolve",
  "soft_wipe_left",
  "soft_wipe_right",
  "soft_wipe_up",
  "soft_wipe_down",
]);

export function isOverlapType(type) {
  return OVERLAP_TYPES.has(String(type || "cut"));
}

/** Blur peaks at the middle of the overlap and returns to sharp. */
export function blurRadiusPx(progress) {
  const amount = Math.max(0, Math.min(1, Number(progress) || 0));
  return Math.sin(amount * Math.PI) * 16;
}

/**
 * Soft wipe mask for the incoming layer.
 * Left/right/up/down name the direction the reveal travels.
 */
export function wipeMask(type, progress) {
  const amount = Math.max(0, Math.min(1, Number(progress) || 0));
  const hidden = (1 - amount) * 100;
  const start = Math.max(0, hidden - 14);
  const end = Math.min(100, hidden);
  const edge = `transparent ${start}%, #000 ${end}%`;
  if (type === "soft_wipe_left") return `linear-gradient(to right, ${edge})`;
  if (type === "soft_wipe_right") return `linear-gradient(to left, ${edge})`;
  if (type === "soft_wipe_up") return `linear-gradient(to bottom, ${edge})`;
  if (type === "soft_wipe_down") return `linear-gradient(to top, ${edge})`;
  return "";
}
