/** Immutable ScopeFrameV1 contract (ADR 0035 / COLOR_WORKSPACE_CONTRACT). */

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

function isFiniteInt(value) {
  return Number.isInteger(value) && Number.isFinite(value);
}

function freezeRoi(roi) {
  return Object.freeze({
    x: roi.x | 0,
    y: roi.y | 0,
    width: roi.width | 0,
    height: roi.height | 0,
  });
}

/**
 * Build an immutable ScopeFrameV1. Rejects mutable or incomplete payloads.
 * RGB samples are BT.709 encoded channel values in [0, 1], interleaved RGBA.
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
  const width = input.width | 0;
  const height = input.height | 0;
  const stride = input.stride | 0;
  const channels = input.channels | 0;
  if (width < 1 || height < 1 || stride < width * channels || channels < 3 || channels > 4) {
    throw new RangeError("ScopeFrameV1 dimensions/channels invalid");
  }
  if (!input.rgb || typeof input.rgb.length !== "number") {
    throw new TypeError("ScopeFrameV1.rgb must be a typed array or array-like");
  }
  const expected = height * stride;
  if (input.rgb.length < expected) {
    throw new RangeError("ScopeFrameV1.rgb shorter than height*stride");
  }
  const roi = freezeRoi(input.roi || { x: 0, y: 0, width, height });
  if (
    roi.x < 0 ||
    roi.y < 0 ||
    roi.width < 1 ||
    roi.height < 1 ||
    roi.x + roi.width > width ||
    roi.y + roi.height > height
  ) {
    throw new RangeError("ScopeFrameV1.roi out of bounds");
  }
  const sampleFactor = Number(input.sampleFactor);
  if (!(sampleFactor >= 1) || !Number.isFinite(sampleFactor)) {
    throw new RangeError("ScopeFrameV1.sampleFactor must be >= 1");
  }
  if (!Object.values(SCOPE_TAP_IDS).includes(input.tapId)) {
    throw new TypeError(`Unknown ScopeFrameV1.tapId: ${input.tapId}`);
  }
  if (!Object.values(SCOPE_SOURCE_KINDS).includes(input.sourceKind)) {
    throw new TypeError(`Unknown ScopeFrameV1.sourceKind: ${input.sourceKind}`);
  }
  if (!isFiniteInt(input.frameIndex) || input.frameIndex < 0) {
    throw new RangeError("ScopeFrameV1.frameIndex must be a non-negative integer");
  }
  // Copy so callers cannot mutate the live frame through the input buffer.
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
    profile: String(input.profile),
    transfer: String(input.transfer),
    straightAlpha: Boolean(input.straightAlpha),
    legalRange: Boolean(input.legalRange),
    ptsNum: Number(input.ptsNum) || 0,
    ptsDen: Number(input.ptsDen) || 1,
    frameIndex: input.frameIndex | 0,
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

/**
 * A frame is current only when project/clip/revision/context match the view
 * and the frame index/PTS is not older than the latest accepted identity.
 */
export function isScopeFrameCurrent(frame, view, latestIdentity = "") {
  if (!frame || !view) return false;
  if (String(frame.projectId) !== String(view.projectId)) return false;
  if (String(frame.clipId) !== String(view.clipId)) return false;
  if (String(frame.gradeRevision) !== String(view.gradeRevision)) return false;
  if (String(frame.contextDigest) !== String(view.contextDigest)) return false;
  if (view.tapId && String(frame.tapId) !== String(view.tapId)) return false;
  const identity = scopeFrameIdentity(frame);
  if (latestIdentity && identity !== latestIdentity) {
    // Allow only frames that match the latest accepted identity token.
    return false;
  }
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
