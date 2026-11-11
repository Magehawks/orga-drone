/**
 * Read-only ScopeFrameV1 engine-tap orchestration (#366).
 *
 * Live media publishing is gated on a tagged post-grade capture plane from the
 * #359 render adapters. Current preview blit / CSS / JPEG candidates are
 * refused so scopes never present divergent pixels as contract measurements.
 *
 * Provenance rule: buildScopeFrameFromTaggedRgb never invents profile, transfer,
 * tap, clock, identity, ROI, sampling or alpha. Missing tags are rejected.
 */

import {
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
  createScopeFrameV1,
  isScopeFrameCurrent,
  scopeViewKey,
} from "./scope-frame.js";

export const SCOPE_TAP_REASONS = Object.freeze({
  AWAITING_RENDER_ADAPTER: "awaiting-render-adapter-359",
  DISPLAY_BLIT_FRAMING: "display-blit-includes-framing-composite",
  CSS_FILTER_APPROXIMATION: "css-filter-is-approximate",
  UNTAGGED_CAPTURE: "capture-plane-untagged",
  PLAYBACK_WITHOUT_GRADED_PROXY: "playback-without-graded-proxy",
  JPEG_STILL_NOT_CONTINUOUS: "jpeg-still-not-continuous-tap",
  MISSING_BUFFER: "missing-tagged-rgb-buffer",
  MISSING_PROVENANCE: "missing-scope-frame-provenance",
  INVALID_PROVENANCE: "invalid-scope-frame-provenance",
  STALE_VIEW: "stale-view",
});

/**
 * Adapter-boundary capture stages (explicit until ADR grows matching fields).
 * Validated here; not silently inferred from tapId or builder name.
 */
export const SCOPE_CAPTURE_STAGES = Object.freeze({
  CLIP_POST_GRADE_PRE_FRAME: "clip-post-grade-pre-frame",
  PROJECT_COMPOSITE: "project-composite",
});

/** Declared capture-plane labels the producer must set. */
export const SCOPE_CAPTURE_PLANES = Object.freeze({
  BT709_ENCODED_RGBA: "bt709-encoded-rgba",
});

const REQUIRED_PROVENANCE_KEYS = Object.freeze([
  "width",
  "height",
  "stride",
  "rgb",
  "channels",
  "profile",
  "transfer",
  "captureStage",
  "capturePlane",
  "tapId",
  "straightAlpha",
  "legalRange",
  "ptsNum",
  "ptsDen",
  "frameIndex",
  "projectId",
  "clipId",
  "gradeRevision",
  "contextDigest",
  "roi",
  "sampleFactor",
]);

function missingProvenance(key) {
  const error = new TypeError(`${SCOPE_TAP_REASONS.MISSING_PROVENANCE}:${key}`);
  error.code = SCOPE_TAP_REASONS.MISSING_PROVENANCE;
  error.key = key;
  return error;
}

function invalidProvenance(detail) {
  const error = new TypeError(`${SCOPE_TAP_REASONS.INVALID_PROVENANCE}:${detail}`);
  error.code = SCOPE_TAP_REASONS.INVALID_PROVENANCE;
  error.detail = detail;
  return error;
}

function requireKey(descriptor, key) {
  if (!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, key)) {
    throw missingProvenance(key);
  }
  const value = descriptor[key];
  if (value === undefined || value === null) throw missingProvenance(key);
  return value;
}

function requireNonEmptyString(descriptor, key) {
  const value = requireKey(descriptor, key);
  if (typeof value !== "string" || !value.trim()) throw missingProvenance(key);
  return value;
}

/**
 * Classify today's Studio preview candidates. None are eligible for a contract
 * live tap until #359 provides a tagged post-grade/pre-frame plane.
 *
 * `renderAdapterReady` alone never makes capability available.
 */
export function probeScopeTapCapability(snapshot = {}) {
  const notes = [];
  if (snapshot.renderAdapterReady === true) {
    notes.push("render-adapter-flag-set; flag-alone-never-qualifies-buffer");
  } else {
    notes.push("render-adapter-359-not-ready");
  }

  const candidates = Array.isArray(snapshot.candidates) ? snapshot.candidates : [];
  for (const candidate of candidates) {
    const refusal = refusePreviewCandidate(candidate);
    if (refusal) notes.push(`${candidate.id || candidate.kind}:${refusal}`);
  }

  if (!candidates.length) {
    notes.push("no-preview-candidates-declared");
  }

  // Live publishing stays off until #359 supplies tagged frames through tryPublish.
  return Object.freeze({
    available: false,
    reason: SCOPE_TAP_REASONS.AWAITING_RENDER_ADAPTER,
    tapId: SCOPE_TAP_IDS.CLIP_POST_GRADE,
    notes: Object.freeze(notes.slice()),
  });
}

/** Pure refusal rules for known preview surfaces. */
export function refusePreviewCandidate(candidate = {}) {
  const kind = String(candidate.kind || "");
  if (kind === "display-blit") {
    return SCOPE_TAP_REASONS.DISPLAY_BLIT_FRAMING;
  }
  if (kind === "css-filter") {
    return SCOPE_TAP_REASONS.CSS_FILTER_APPROXIMATION;
  }
  if (kind === "jpeg-still") {
    return SCOPE_TAP_REASONS.JPEG_STILL_NOT_CONTINUOUS;
  }
  if (kind === "playback-proxy" || kind === "webgl-lut") {
    if (!candidate.profileTagged || !candidate.transferTagged) {
      return SCOPE_TAP_REASONS.UNTAGGED_CAPTURE;
    }
    if (candidate.playing && !candidate.gradedProxyReady) {
      return SCOPE_TAP_REASONS.PLAYBACK_WITHOUT_GRADED_PROXY;
    }
  }
  if (candidate.hasFraming || candidate.hasComposite) {
    return SCOPE_TAP_REASONS.DISPLAY_BLIT_FRAMING;
  }
  if (!candidate.profileTagged || !candidate.transferTagged) {
    return SCOPE_TAP_REASONS.UNTAGGED_CAPTURE;
  }
  return SCOPE_TAP_REASONS.AWAITING_RENDER_ADAPTER;
}

/**
 * Validate adapter-boundary provenance before constructing ScopeFrameV1.
 * No silent defaults for profile/transfer/tap/clock/identity/ROI/sample/alpha.
 */
export function assertTaggedRgbProvenance(descriptor) {
  if (!descriptor || typeof descriptor !== "object") {
    throw missingProvenance("descriptor");
  }
  for (const key of REQUIRED_PROVENANCE_KEYS) {
    requireKey(descriptor, key);
  }
  if (!descriptor.rgb || typeof descriptor.rgb.length !== "number") {
    throw missingProvenance("rgb");
  }

  const profile = requireNonEmptyString(descriptor, "profile");
  const transfer = requireNonEmptyString(descriptor, "transfer");
  const captureStage = requireNonEmptyString(descriptor, "captureStage");
  const capturePlane = requireNonEmptyString(descriptor, "capturePlane");
  const tapId = requireNonEmptyString(descriptor, "tapId");

  if (profile !== "bt709") throw invalidProvenance("profile");
  if (transfer !== "bt709") throw invalidProvenance("transfer");
  if (!Object.values(SCOPE_CAPTURE_PLANES).includes(capturePlane)) {
    throw invalidProvenance("capturePlane");
  }
  if (!Object.values(SCOPE_CAPTURE_STAGES).includes(captureStage)) {
    throw invalidProvenance("captureStage");
  }
  if (!Object.values(SCOPE_TAP_IDS).includes(tapId)) {
    throw invalidProvenance("tapId");
  }
  if (
    captureStage === SCOPE_CAPTURE_STAGES.CLIP_POST_GRADE_PRE_FRAME &&
    tapId !== SCOPE_TAP_IDS.CLIP_POST_GRADE
  ) {
    throw invalidProvenance("captureStage/tapId-mismatch");
  }
  if (
    captureStage === SCOPE_CAPTURE_STAGES.PROJECT_COMPOSITE &&
    tapId !== SCOPE_TAP_IDS.PROJECT_COMPOSITE
  ) {
    throw invalidProvenance("captureStage/tapId-mismatch");
  }
  if (typeof descriptor.straightAlpha !== "boolean") {
    throw invalidProvenance("straightAlpha");
  }
  if (typeof descriptor.legalRange !== "boolean") {
    throw invalidProvenance("legalRange");
  }
  if (typeof descriptor.sampleFactor !== "number") {
    throw invalidProvenance("sampleFactor");
  }
  requireNonEmptyString(descriptor, "projectId");
  requireNonEmptyString(descriptor, "clipId");
  requireNonEmptyString(descriptor, "gradeRevision");
  requireNonEmptyString(descriptor, "contextDigest");
  if (!descriptor.roi || typeof descriptor.roi !== "object") {
    throw invalidProvenance("roi");
  }
  return Object.freeze({
    profile,
    transfer,
    captureStage,
    capturePlane,
    tapId,
  });
}

/**
 * Build a ScopeFrameV1 only from a fully tagged producer descriptor.
 * Does not invent provenance; does not treat renderAdapterReady as authority.
 */
export function buildScopeFrameFromTaggedRgb(descriptor) {
  const provenance = assertTaggedRgbProvenance(descriptor);
  // captureStage/capturePlane stay adapter-boundary metadata until ADR extends
  // ScopeFrameV1; identity is enforced here before the immutable frame exists.
  void provenance;
  return createScopeFrameV1({
    version: 1,
    width: descriptor.width,
    height: descriptor.height,
    stride: descriptor.stride,
    rgb: descriptor.rgb,
    channels: descriptor.channels,
    profile: descriptor.profile,
    transfer: descriptor.transfer,
    straightAlpha: descriptor.straightAlpha,
    legalRange: descriptor.legalRange,
    ptsNum: descriptor.ptsNum,
    ptsDen: descriptor.ptsDen,
    frameIndex: descriptor.frameIndex,
    projectId: descriptor.projectId,
    clipId: descriptor.clipId,
    gradeRevision: descriptor.gradeRevision,
    contextDigest: descriptor.contextDigest,
    tapId: descriptor.tapId,
    roi: descriptor.roi,
    sampleFactor: descriptor.sampleFactor,
    sourceKind: SCOPE_SOURCE_KINDS.ENGINE_TAP,
    fixtureId: "",
  });
}

/**
 * Studio-facing controller. Never invents pixels; only forwards tagged frames
 * after capability checks, stale-view checks and rate limiting.
 */
export function createScopeTapController({
  panel,
  getView,
  getCapability = probeScopeTapCapability,
  now = () => performance.now(),
  minIntervalMs = 100,
} = {}) {
  // null sentinel: first eligible publish is never rate-limited by t=0 clocks.
  let lastPublishMs = null;
  let dropped = 0;
  let attempted = 0;
  let lastStatus = getCapability();
  let lastViewKey = scopeViewKey(getView?.() || {});

  function sync() {
    const view = getView?.() || {};
    const key = scopeViewKey(view);
    if (key !== lastViewKey) {
      lastViewKey = key;
      // Seek/clip/revision changes must not inherit the previous throttle window.
      lastPublishMs = null;
      panel?.syncView?.(view);
    } else {
      panel?.syncView?.(view);
    }
    lastStatus = getCapability();
    return lastStatus;
  }

  function tryPublish(frameOrNull) {
    attempted += 1;
    const capability = getCapability();
    lastStatus = capability;
    if (!capability.available) {
      dropped += 1;
      return { accepted: false, reason: capability.reason };
    }
    if (!frameOrNull) {
      dropped += 1;
      return { accepted: false, reason: SCOPE_TAP_REASONS.MISSING_BUFFER };
    }
    if (frameOrNull.sourceKind !== SCOPE_SOURCE_KINDS.ENGINE_TAP) {
      dropped += 1;
      return { accepted: false, reason: "non-engine-source" };
    }
    const view = getView?.() || {};
    const viewKey = scopeViewKey(view);
    if (viewKey !== lastViewKey) {
      lastViewKey = viewKey;
      lastPublishMs = null;
      panel?.syncView?.(view);
    }
    if (!isScopeFrameCurrent(frameOrNull, view)) {
      dropped += 1;
      return { accepted: false, reason: SCOPE_TAP_REASONS.STALE_VIEW };
    }
    const t = now();
    if (lastPublishMs !== null && t - lastPublishMs < minIntervalMs) {
      dropped += 1;
      return { accepted: false, reason: "rate-limited" };
    }
    if (!panel?.injectFrame) {
      dropped += 1;
      return { accepted: false, reason: "missing-panel" };
    }
    const result = panel.injectFrame(frameOrNull);
    if (result?.accepted) lastPublishMs = t;
    else dropped += 1;
    return result;
  }

  return {
    sync,
    tryPublish,
    probe: () => {
      lastStatus = getCapability();
      return lastStatus;
    },
    getStatus() {
      return {
        capability: lastStatus,
        attempted,
        dropped,
        lastPublishMs,
        viewKey: lastViewKey,
      };
    },
    destroy() {},
  };
}
