/**
 * Read-only ScopeFrameV1 engine-tap orchestration (#366).
 *
 * Live media publishing is gated on a tagged post-grade capture plane from the
 * #359 render adapters. Current preview blit / CSS / JPEG candidates are
 * refused so scopes never present divergent pixels as contract measurements.
 */

import {
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
  createScopeFrameV1,
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
});

/**
 * Classify today's Studio preview candidates. None are eligible for a contract
 * live tap until #359 provides a tagged post-grade/pre-frame plane.
 *
 * @param {{
 *   candidates?: Array<{
 *     id: string,
 *     kind: string,
 *     hasFraming?: boolean,
 *     hasComposite?: boolean,
 *     gradePath?: string,
 *     profileTagged?: boolean,
 *     transferTagged?: boolean,
 *     playing?: boolean,
 *     gradedProxyReady?: boolean,
 *   }>,
 *   renderAdapterReady?: boolean,
 * }} [snapshot]
 */
export function probeScopeTapCapability(snapshot = {}) {
  const notes = [];
  if (snapshot.renderAdapterReady === true) {
    // #359 will flip this once a tagged capture exists. Keep the probe honest:
    // readiness alone is not enough without an actual tagged buffer publish.
    notes.push("render-adapter-flag-set; waiting for tagged buffer publish");
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
  // Even a tagged-looking candidate is not live until the #359 adapter owns it.
  return SCOPE_TAP_REASONS.AWAITING_RENDER_ADAPTER;
}

/**
 * Build a ScopeFrameV1 from an already-tagged encoded RGB(A) buffer.
 * Callers (#359) must supply contract identity and bt709 profile/transfer.
 */
export function buildScopeFrameFromTaggedRgb(descriptor) {
  if (!descriptor || !descriptor.rgb) {
    throw new TypeError(SCOPE_TAP_REASONS.MISSING_BUFFER);
  }
  return createScopeFrameV1({
    version: 1,
    width: descriptor.width,
    height: descriptor.height,
    stride: descriptor.stride,
    rgb: descriptor.rgb,
    channels: descriptor.channels ?? 4,
    profile: descriptor.profile ?? "bt709",
    transfer: descriptor.transfer ?? "bt709",
    straightAlpha: descriptor.straightAlpha !== false,
    legalRange: Boolean(descriptor.legalRange),
    ptsNum: descriptor.ptsNum ?? 0,
    ptsDen: descriptor.ptsDen ?? 1,
    frameIndex: descriptor.frameIndex ?? 0,
    projectId: descriptor.projectId,
    clipId: descriptor.clipId,
    gradeRevision: descriptor.gradeRevision,
    contextDigest: descriptor.contextDigest,
    tapId: descriptor.tapId ?? SCOPE_TAP_IDS.CLIP_POST_GRADE,
    roi: descriptor.roi ?? {
      x: 0,
      y: 0,
      width: descriptor.width,
      height: descriptor.height,
    },
    sampleFactor: descriptor.sampleFactor ?? 1,
    sourceKind: SCOPE_SOURCE_KINDS.ENGINE_TAP,
    fixtureId: "",
  });
}

/**
 * Studio-facing controller. Never invents pixels; only forwards tagged frames
 * after capability checks and rate limiting.
 */
export function createScopeTapController({
  panel,
  getView,
  getCapability = probeScopeTapCapability,
  now = () => performance.now(),
  minIntervalMs = 100,
} = {}) {
  let lastPublishMs = 0;
  let dropped = 0;
  let attempted = 0;
  let lastStatus = getCapability();
  let lastViewKey = scopeViewKey(getView?.() || {});

  function sync() {
    const view = getView?.() || {};
    const key = scopeViewKey(view);
    if (key !== lastViewKey) {
      lastViewKey = key;
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
    const t = now();
    if (t - lastPublishMs < minIntervalMs) {
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
