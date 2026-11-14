// Pure Timelapse draft helpers aligned with studio_timelapse.py / ADR 0034.
import { MAX_SPEED, MIN_SPEED, parseRamp } from "./speed-ramp.js";

export const EXPORT_FPS = 30;
export const MIN_TIMELAPSE_SPEED = 1;
export const MAX_TIMELAPSE_SPEED = MAX_SPEED;
export const MIN_OUTPUT_FRAMES = 1;
export const MIN_SOURCE_SPAN_S = 0.05;
export const MAX_HTML_PLAYBACK_RATE = 16;

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

export function allowedTargetRange(sourceSpan) {
  if (!finite(sourceSpan) || sourceSpan < MIN_SOURCE_SPAN_S) return null;
  const minTarget = Math.max(sourceSpan / MAX_TIMELAPSE_SPEED, MIN_OUTPUT_FRAMES / EXPORT_FPS);
  const maxTarget = sourceSpan / MIN_TIMELAPSE_SPEED;
  if (minTarget > maxTarget) return null;
  return { min: minTarget, max: maxTarget };
}

export function draftFromTarget(sourceSpan, targetDuration) {
  if (!finite(sourceSpan) || !finite(targetDuration) || targetDuration <= 0) return null;
  const range = allowedTargetRange(sourceSpan);
  if (!range || targetDuration + 1e-9 < range.min || targetDuration - 1e-9 > range.max) return null;
  const speed = sourceSpan / targetDuration;
  // Approximate only: export snaps absolute Story boundaries on the shared 30 fps grid.
  const outputFrames = Math.max(
    MIN_OUTPUT_FRAMES,
    Math.trunc(targetDuration * EXPORT_FPS + 0.5 + 1e-8)
  );
  return {
    sourceSpanS: sourceSpan,
    speed,
    targetDurationS: targetDuration,
    outputFrames,
    outputDurationS: outputFrames / EXPORT_FPS,
    framesApproximate: true,
  };
}

export function draftFromSpeed(sourceSpan, speed) {
  if (
    !finite(sourceSpan) ||
    !finite(speed) ||
    speed < MIN_TIMELAPSE_SPEED ||
    speed > MAX_TIMELAPSE_SPEED ||
    sourceSpan < MIN_SOURCE_SPAN_S
  ) {
    return null;
  }
  const targetDuration = sourceSpan / speed;
  if (targetDuration * EXPORT_FPS + 1e-9 < MIN_OUTPUT_FRAMES) return null;
  const outputFrames = Math.max(
    MIN_OUTPUT_FRAMES,
    Math.trunc(targetDuration * EXPORT_FPS + 0.5 + 1e-8)
  );
  return {
    sourceSpanS: sourceSpan,
    speed,
    targetDurationS: targetDuration,
    outputFrames,
    outputDurationS: outputFrames / EXPORT_FPS,
    framesApproximate: true,
  };
}

export function flatTimelapseRamp(sourceIn, sourceOut, speed) {
  if (
    !finite(sourceIn) ||
    !finite(sourceOut) ||
    !finite(speed) ||
    sourceOut - sourceIn < MIN_SOURCE_SPAN_S ||
    speed < MIN_SPEED ||
    speed > MAX_SPEED ||
    Math.abs(speed - 1) <= 1e-9
  ) {
    return null;
  }
  const ramp = {
    v: 1,
    interp: "reciprocal_smoothstep",
    points: [
      { source_s: sourceIn, speed },
      { source_s: sourceOut, speed },
    ],
  };
  return parseRamp(ramp) ? ramp : null;
}

/** Soft gate: Apply may proceed only after an explicit UI confirmation (#333 A). */
export const CONFIRM_REPLACE_RAMP = "confirm_replace_ramp";

export function timelapseConflict({
  hasRamp,
  sectionRepeats,
  forwardLoop,
  replaceConfirmed = false,
}) {
  if (Number(sectionRepeats) > 1) {
    return "Turn off section repeat before applying Timelapse.";
  }
  if (forwardLoop) {
    return "Turn off Repeat to soundtrack before applying Timelapse.";
  }
  if (hasRamp && !replaceConfirmed) return CONFIRM_REPLACE_RAMP;
  return null;
}

export function isHardTimelapseConflict(code) {
  return !!code && code !== CONFIRM_REPLACE_RAMP;
}

export function clampPreviewPlaybackRate(speed) {
  if (!finite(speed)) return 1;
  return Math.min(Math.max(speed, MIN_SPEED), MAX_HTML_PLAYBACK_RATE);
}

export function rampNeedsSeekPreview(ramp) {
  if (!ramp) return false;
  const groups = [];
  if (Array.isArray(ramp.points)) groups.push(ramp.points);
  if (Array.isArray(ramp.regions)) {
    for (const region of ramp.regions) {
      if (region && Array.isArray(region.points)) groups.push(region.points);
    }
  }
  return groups.some((points) =>
    points.some((point) => finite(point.speed) && point.speed > MAX_HTML_PLAYBACK_RATE + 1e-9)
  );
}

/** Bound continuous seek sampling near 30 Hz to avoid decode overload. */
export const SEEK_SAMPLE_MIN_INTERVAL_MS = 33;

export function shouldReconcileSeekSample(
  lastMs,
  nowMs,
  minIntervalMs = SEEK_SAMPLE_MIN_INTERVAL_MS
) {
  if (!finite(nowMs)) return false;
  if (!finite(lastMs) || lastMs <= 0) return true;
  return nowMs - lastMs >= minIntervalMs;
}

export function allowHtmlVideoAutoplay({ playing, seekSample }) {
  return !!playing && !seekSample;
}

export function captureValidatedDraft({ clipId, start, end, field, draft }) {
  if (!draft || clipId === null || clipId === undefined || !finite(start) || !finite(end))
    return null;
  return {
    clipId: String(clipId),
    start,
    end,
    span: end - start,
    field,
    speed: draft.speed,
    targetDurationS: draft.targetDurationS,
    outputFrames: draft.outputFrames,
    outputDurationS: draft.outputDurationS,
    key: `${clipId}:${start}:${end}`,
  };
}

export function validatedDraftMatches(captured, { clipId, start, end }) {
  if (!captured) return false;
  return (
    captured.clipId === String(clipId) &&
    captured.start === start &&
    captured.end === end &&
    captured.key === `${clipId}:${start}:${end}` &&
    finite(captured.speed) &&
    finite(captured.targetDurationS)
  );
}
