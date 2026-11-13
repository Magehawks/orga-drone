/**
 * Managed-grade preview-frame producer for ScopeFrameV1 (#362/#366).
 *
 * Reuses the #359 CPU preview-frame path (same grade as export stills).
 * Transport is JPEG; sampleFactor is applied once by accumulate (no second
 * physical shrink). Not a display-blit / CSS / untagged WebGL tap.
 */

import { SCOPE_TAP_IDS } from "./scope-frame.js";
import {
  SCOPE_CAPTURE_PLANES,
  SCOPE_CAPTURE_STAGES,
  buildScopeFrameFromTaggedRgb,
} from "./engine-tap.js";

export const MANAGED_PREVIEW_SCOPE_PRODUCER = "managed-preview-frame-v1";
export const PREVIEW_SCOPE_QUANTIZE_S = 0.1;

/** Build taggedCapturePlane snapshot for probeScopeTapCapability. */
export function managedPreviewTaggedCapturePlane(ready) {
  if (!ready) return null;
  return Object.freeze({
    producer: MANAGED_PREVIEW_SCOPE_PRODUCER,
    profile: "bt709",
    transfer: "bt709",
    captureStage: SCOPE_CAPTURE_STAGES.CLIP_POST_GRADE_PRE_FRAME,
    capturePlane: SCOPE_CAPTURE_PLANES.BT709_ENCODED_RGBA,
  });
}

/** Quantize source time to the same 0.1 s grid as preview-frame. */
export function quantizePreviewScopeTime(tS, step = PREVIEW_SCOPE_QUANTIZE_S) {
  const value = Number(tS);
  if (!Number.isFinite(value) || value < 0) return 0;
  if (!(step > 0)) return value;
  return Math.round(value / step) * step;
}

/**
 * sampleFactor for accumulate: step through the decoded buffer once so the
 * effective long edge stays near maxEdge. Does not resize the buffer.
 */
export function sampleFactorForMaxEdge(width, height, maxEdge = 320) {
  const longEdge = Math.max(1, width | 0, height | 0);
  return Math.max(1, Math.ceil(longEdge / Math.max(1, maxEdge)));
}

/** Convert 8-bit RGBA into a full-size float ScopeFrame buffer. */
export function rgba8ToFloatRgb(rgba, width, height) {
  const w = Math.max(1, width | 0);
  const h = Math.max(1, height | 0);
  const channels = 4;
  const stride = w * channels;
  const out = new Float32Array(h * stride);
  for (let i = 0; i < w * h; i += 1) {
    const si = i * 4;
    const di = i * channels;
    out[di] = (rgba[si] || 0) / 255;
    out[di + 1] = (rgba[si + 1] || 0) / 255;
    out[di + 2] = (rgba[si + 2] || 0) / 255;
    out[di + 3] = rgba.length > si + 3 ? (rgba[si + 3] || 0) / 255 : 1;
  }
  return { width: w, height: h, stride, channels, rgb: out };
}

export function buildManagedPreviewScopeDescriptor({
  rgba,
  width,
  height,
  maxEdge = 320,
  projectId,
  clipId,
  gradeRevision,
  contextDigest,
  sourceTimeS = 0,
  ptsDen = 10,
}) {
  const plane = rgba8ToFloatRgb(rgba, width, height);
  const sampleFactor = sampleFactorForMaxEdge(plane.width, plane.height, maxEdge);
  const t = quantizePreviewScopeTime(sourceTimeS);
  // ptsDen=10 matches 0.1 s preview quantize so frameIndex tracks seek grid.
  const den = Math.max(1, Math.round(Number(ptsDen) || 10));
  const frameIndex = Math.max(0, Math.round(t * den));
  return {
    width: plane.width,
    height: plane.height,
    stride: plane.stride,
    rgb: plane.rgb,
    channels: plane.channels,
    profile: "bt709",
    transfer: "bt709",
    captureStage: SCOPE_CAPTURE_STAGES.CLIP_POST_GRADE_PRE_FRAME,
    capturePlane: SCOPE_CAPTURE_PLANES.BT709_ENCODED_RGBA,
    tapId: SCOPE_TAP_IDS.CLIP_POST_GRADE,
    straightAlpha: true,
    legalRange: false,
    ptsNum: frameIndex,
    ptsDen: den,
    frameIndex,
    projectId: String(projectId || ""),
    clipId: String(clipId || ""),
    gradeRevision: String(gradeRevision || "0"),
    contextDigest: String(contextDigest || ""),
    roi: { x: 0, y: 0, width: plane.width, height: plane.height },
    sampleFactor,
  };
}

export function buildManagedPreviewScopeFrame(input) {
  return buildScopeFrameFromTaggedRgb(buildManagedPreviewScopeDescriptor(input));
}

/**
 * Orchestrates fetch → decode → tag → tryPublish with generation stale rejection.
 * fetchPreviewJpeg may return { bytes, gradeRevision, sourceTimeS }.
 */
export function createManagedPreviewScopeProducer({
  getView,
  getSourceTimeS,
  fetchPreviewJpeg,
  decodeJpegToRgba,
  tryPublish,
  maxEdge = 320,
  ptsDen = 10,
  isPlaying = () => false,
  pauseIntervalMs = 100,
  playIntervalMs = 500,
  now = () => performance.now(),
} = {}) {
  let generation = 0;
  let lastAttemptMs = null;
  let lastIdentityKey = "";
  let lastPausedSeek = "";
  let destroyed = false;

  function bump() {
    generation += 1;
    return generation;
  }

  function identityKey(view) {
    return [
      String(view?.projectId || ""),
      String(view?.clipId || ""),
      String(view?.gradeRevision || ""),
      String(view?.contextDigest || ""),
    ].join("\u001f");
  }

  async function refresh(reason = "manual") {
    if (destroyed) return { accepted: false, reason: "destroyed" };
    const view = getView?.() || {};
    if (!view.clipId) return { accepted: false, reason: "no-clip" };
    const sourceTimeS = Number(getSourceTimeS?.() || 0);
    const playing = Boolean(isPlaying?.());
    const idKey = identityKey(view);
    const pausedSeek = quantizePreviewScopeTime(sourceTimeS);
    if (idKey !== lastIdentityKey) {
      lastIdentityKey = idKey;
      lastPausedSeek = String(pausedSeek);
      bump();
      lastAttemptMs = null;
    } else if (!playing && String(pausedSeek) !== lastPausedSeek) {
      // Explicit scrub while paused: drop in-flight frames and reset throttle.
      lastPausedSeek = String(pausedSeek);
      bump();
      lastAttemptMs = null;
    }
    const minInterval = playing ? playIntervalMs : pauseIntervalMs;
    const t = now();
    if (lastAttemptMs !== null && t - lastAttemptMs < minInterval) {
      return { accepted: false, reason: "rate-limited", detail: reason };
    }
    lastAttemptMs = t;
    const gen = generation;
    let payload;
    try {
      payload = await fetchPreviewJpeg(String(view.clipId), sourceTimeS, {
        gradeRevision: view.gradeRevision,
        generation: gen,
      });
    } catch (err) {
      return { accepted: false, reason: "fetch-failed", error: err };
    }
    if (destroyed || gen !== generation) {
      return { accepted: false, reason: "stale-generation" };
    }
    const bytes = payload?.bytes ?? payload;
    const responseRevision =
      payload?.gradeRevision != null
        ? String(payload.gradeRevision)
        : String(view.gradeRevision || "");
    const responseTime =
      payload?.sourceTimeS != null
        ? Number(payload.sourceTimeS)
        : quantizePreviewScopeTime(sourceTimeS);
    if (String(responseRevision) !== String(view.gradeRevision || "")) {
      return { accepted: false, reason: "stale-revision" };
    }
    const decoded = await decodeJpegToRgba(bytes);
    if (destroyed || gen !== generation) {
      return { accepted: false, reason: "stale-generation" };
    }
    const latest = getView?.() || {};
    if (identityKey(latest) !== idKey) {
      return { accepted: false, reason: "stale-view" };
    }
    if (!playing) {
      const latestSeek = quantizePreviewScopeTime(getSourceTimeS?.() || 0);
      if (String(latestSeek) !== String(pausedSeek)) {
        return { accepted: false, reason: "stale-seek" };
      }
    }
    const frame = buildManagedPreviewScopeFrame({
      rgba: decoded.rgba,
      width: decoded.width,
      height: decoded.height,
      maxEdge,
      projectId: latest.projectId,
      clipId: latest.clipId,
      gradeRevision: responseRevision,
      contextDigest: latest.contextDigest,
      sourceTimeS: responseTime,
      ptsDen,
    });
    return tryPublish?.(frame) || { accepted: false, reason: "missing-publish" };
  }

  return {
    refresh,
    invalidate: bump,
    destroy() {
      destroyed = true;
      bump();
    },
  };
}

/** Browser helper: decode JPEG bytes to RGBA via createImageBitmap. */
export async function decodeJpegBytesToRgba(bytes, createBitmap = createImageBitmap) {
  const blob = bytes instanceof Blob ? bytes : new Blob([bytes], { type: "image/jpeg" });
  const bitmap = await createBitmap(blob);
  try {
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) throw new Error("2d-context-unavailable");
    ctx.drawImage(bitmap, 0, 0);
    const image = ctx.getImageData(0, 0, bitmap.width, bitmap.height);
    return {
      width: image.width,
      height: image.height,
      rgba: image.data,
    };
  } finally {
    bitmap.close?.();
  }
}
