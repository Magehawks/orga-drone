/** ScopeFrameV1 contract (ADR 0035 / COLOR_WORKSPACE_CONTRACT). */

export const SCOPE_FRAME_VERSION = 1;

export const SCOPE_TAP_IDS = Object.freeze({
  CLIP_POST_GRADE: "clip-post-grade",
  PROJECT_COMPOSITE: "project-composite",
  FIXTURE: "fixture",
});

export const SCOPE_SOURCE_KINDS = Object.freeze({
  FIXTURE: "fixture",
  ENGINE_TAP: "engine-tap",
});

/** Declared BT.709 encoded working labels for the first managed SDR tap. */
export const SCOPE_PROFILES = Object.freeze(["bt709"]);
export const SCOPE_TRANSFERS = Object.freeze(["bt709"]);

const REQUIRED_KEYS = [
  "version",
  "width",
  "height",
  "stride",
  "rgb",
  "channels",
  "profile",
  "transfer",
  "straightAlpha",
  "ptsNum",
  "ptsDen",
  "frameIndex",
  "projectId",
  "clipId",
  "gradeRevision",
  "contextDigest",
  "tapId",
  "roi",
  "sampleFactor",
  "sourceKind",
];

const MAX_DIMENSION = 16384;
const MAX_FRAME_INDEX = Number.MAX_SAFE_INTEGER;

/**
 * Require a finite safe integer without bitwise truncation.
 * Rejects floats, NaN, Infinity and values outside Number.MAX_SAFE_INTEGER.
 */
export function requireSafeInt(value, name, { min = 0, max = MAX_FRAME_INDEX } = {}) {
  if (typeof value !== "number" || !Number.isInteger(value) || !Number.isSafeInteger(value)) {
    throw new RangeError(`ScopeFrameV1.${name} must be a safe integer`);
  }
  if (value < min || value > max) {
    throw new RangeError(`ScopeFrameV1.${name} out of range [${min}, ${max}]`);
  }
  return value;
}

function requireFiniteNumber(value, name) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new RangeError(`ScopeFrameV1.${name} must be a finite number`);
  }
  return value;
}

function freezeRoi(roi, width, height) {
  if (!roi || typeof roi !== "object") {
    throw new TypeError("ScopeFrameV1.roi must be an object");
  }
  const x = requireSafeInt(roi.x, "roi.x", { min: 0, max: width });
  const y = requireSafeInt(roi.y, "roi.y", { min: 0, max: height });
  const roiWidth = requireSafeInt(roi.width, "roi.width", { min: 1, max: width });
  const roiHeight = requireSafeInt(roi.height, "roi.height", { min: 1, max: height });
  if (x + roiWidth > width || y + roiHeight > height) {
    throw new RangeError("ScopeFrameV1.roi out of bounds");
  }
  return Object.freeze({ x, y, width: roiWidth, height: roiHeight });
}

/**
 * Build a ScopeFrameV1. Rejects incomplete or out-of-contract payloads.
 * RGB samples are BT.709 encoded channel values in [0, 1], interleaved RGBA.
 *
 * Buffer ownership: the frame keeps a defensive Float32Array copy. The frame
 * object is frozen, but TypedArray element slots cannot be Object.frozen in JS.
 * Callers must treat `rgb` as read-only; mutating it is unsupported.
 */
export function createScopeFrameV1(input) {
  if (!input || typeof input !== "object") {
    throw new TypeError("ScopeFrameV1 requires an object");
  }
  for (const key of REQUIRED_KEYS) {
    if (!(key in input)) throw new TypeError(`ScopeFrameV1 missing ${key}`);
  }
  if (input.version !== SCOPE_FRAME_VERSION) {
    throw new TypeError(`Unsupported ScopeFrameV1 version: ${input.version}`);
  }

  const width = requireSafeInt(input.width, "width", { min: 1, max: MAX_DIMENSION });
  const height = requireSafeInt(input.height, "height", { min: 1, max: MAX_DIMENSION });
  const channels = requireSafeInt(input.channels, "channels", { min: 3, max: 4 });
  const stride = requireSafeInt(input.stride, "stride", {
    min: width * channels,
    max: MAX_DIMENSION * channels,
  });
  if (stride < width * channels) {
    throw new RangeError("ScopeFrameV1.stride shorter than width*channels");
  }

  if (!input.rgb || typeof input.rgb.length !== "number") {
    throw new TypeError("ScopeFrameV1.rgb must be a typed array or array-like");
  }
  const expected = height * stride;
  if (!Number.isSafeInteger(expected) || expected < 1) {
    throw new RangeError("ScopeFrameV1 buffer size is not a safe integer");
  }
  if (input.rgb.length < expected) {
    throw new RangeError("ScopeFrameV1.rgb shorter than height*stride");
  }

  const roi = freezeRoi(input.roi ?? { x: 0, y: 0, width, height }, width, height);

  const sampleFactor = requireFiniteNumber(Number(input.sampleFactor), "sampleFactor");
  if (!(sampleFactor >= 1)) {
    throw new RangeError("ScopeFrameV1.sampleFactor must be >= 1");
  }

  if (!Object.values(SCOPE_TAP_IDS).includes(input.tapId)) {
    throw new TypeError(`Unknown ScopeFrameV1.tapId: ${input.tapId}`);
  }
  if (!Object.values(SCOPE_SOURCE_KINDS).includes(input.sourceKind)) {
    throw new TypeError(`Unknown ScopeFrameV1.sourceKind: ${input.sourceKind}`);
  }

  const profile = String(input.profile);
  const transfer = String(input.transfer);
  if (!SCOPE_PROFILES.includes(profile)) {
    throw new TypeError(`Unsupported ScopeFrameV1.profile: ${profile}`);
  }
  if (!SCOPE_TRANSFERS.includes(transfer)) {
    throw new TypeError(`Unsupported ScopeFrameV1.transfer: ${transfer}`);
  }

  const frameIndex = requireSafeInt(input.frameIndex, "frameIndex", {
    min: 0,
    max: MAX_FRAME_INDEX,
  });
  const ptsNum = requireSafeInt(input.ptsNum, "ptsNum", {
    min: Number.MIN_SAFE_INTEGER,
    max: Number.MAX_SAFE_INTEGER,
  });
  const ptsDen = requireSafeInt(input.ptsDen, "ptsDen", { min: 1, max: MAX_FRAME_INDEX });

  // Defensive copy so mutating the caller's buffer cannot alter the frame.
  const rgb =
    input.rgb instanceof Float32Array
      ? input.rgb.slice(0, expected)
      : Float32Array.from(Array.prototype.slice.call(input.rgb, 0, expected));

  return Object.freeze({
    version: SCOPE_FRAME_VERSION,
    width,
    height,
    stride,
    rgb,
    channels,
    profile,
    transfer,
    straightAlpha: Boolean(input.straightAlpha),
    legalRange: Boolean(input.legalRange),
    ptsNum,
    ptsDen,
    frameIndex,
    projectId: String(input.projectId),
    clipId: String(input.clipId),
    gradeRevision: String(input.gradeRevision),
    contextDigest: String(input.contextDigest),
    tapId: input.tapId,
    roi,
    sampleFactor,
    sourceKind: input.sourceKind,
    fixtureId: input.fixtureId ? String(input.fixtureId) : "",
  });
}

/** Identity used to reject stale frames for the active selection/revision. */
export function scopeFrameIdentity(frame) {
  if (!frame) return "";
  return [
    frame.projectId,
    frame.clipId,
    frame.gradeRevision,
    frame.contextDigest,
    frame.tapId,
    frame.frameIndex,
    frame.ptsNum,
    frame.ptsDen,
  ].join("\u001f");
}

/** Stable key for the inspector's current project/clip/grade context. */
export function scopeViewKey(view) {
  if (!view) return "";
  return [
    String(view.projectId ?? ""),
    String(view.clipId ?? ""),
    String(view.gradeRevision ?? ""),
    String(view.contextDigest ?? ""),
    String(view.tapId ?? ""),
  ].join("\u001f");
}

/**
 * A frame is current only when project/clip/revision/context match the view.
 * Optional latestIdentity pins the accepted frame token after display.
 */
export function isScopeFrameCurrent(frame, view, latestIdentity = "") {
  if (!frame || !view) return false;
  if (String(frame.projectId) !== String(view.projectId)) return false;
  if (String(frame.clipId) !== String(view.clipId)) return false;
  if (String(frame.gradeRevision) !== String(view.gradeRevision)) return false;
  if (String(frame.contextDigest) !== String(view.contextDigest)) return false;
  if (view.tapId && String(frame.tapId) !== String(view.tapId)) return false;
  const identity = scopeFrameIdentity(frame);
  if (latestIdentity && identity !== latestIdentity) return false;
  return true;
}

export function describeScopeSource(frame, labels = {}) {
  if (!frame) return labels.unavailable || "Scopes unavailable";
  if (frame.sourceKind === SCOPE_SOURCE_KINDS.FIXTURE) {
    return labels.fixture || "Test pattern — not a media measurement";
  }
  if (frame.tapId === SCOPE_TAP_IDS.PROJECT_COMPOSITE) {
    return labels.composite || "Project composite tap";
  }
  if (frame.sampleFactor > 1) {
    return labels.downsampled || "Downsampled measurement";
  }
  return labels.live || "Engine tap measurement";
}
