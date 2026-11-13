/**
 * Managed-grade preview-frame producer for ScopeFrameV1 (#362/#366).
 *
 * Reuses the #359 CPU preview-frame path (same grade as export stills).
 * Transport is JPEG; sampleFactor and notes disclose downsample + quantization.
 * Not a display-blit / CSS / untagged WebGL tap.
 */

import { SCOPE_TAP_IDS } from "./scope-frame.js";
import {
  SCOPE_CAPTURE_PLANES,
  SCOPE_CAPTURE_STAGES,
  buildScopeFrameFromTaggedRgb,
} from "./engine-tap.js";

export const MANAGED_PREVIEW_SCOPE_PRODUCER = "managed-preview-frame-v1";

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

/**
 * Deterministic box downsample. sampleFactor is max(1, ceil(srcLong/maxEdge)).
 */
export function downsampleRgba(rgba, width, height, maxEdge = 320) {
  const w = Math.max(1, width | 0);
  const h = Math.max(1, height | 0);
  const longEdge = Math.max(w, h);
  const sampleFactor = Math.max(1, Math.ceil(longEdge / Math.max(1, maxEdge)));
  const outW = Math.max(1, Math.floor(w / sampleFactor));
  const outH = Math.max(1, Math.floor(h / sampleFactor));
  const channels = 4;
  const stride = outW * channels;
  const out = new Float32Array(outH * stride);
  for (let y = 0; y < outH; y += 1) {
    const sy = Math.min(h - 1, y * sampleFactor);
    for (let x = 0; x < outW; x += 1) {
      const sx = Math.min(w - 1, x * sampleFactor);
      const si = (sy * w + sx) * 4;
      const di = y * stride + x * channels;
      out[di] = (rgba[si] || 0) / 255;
      out[di + 1] = (rgba[si + 1] || 0) / 255;
      out[di + 2] = (rgba[si + 2] || 0) / 255;
      out[di + 3] = rgba.length > si + 3 ? (rgba[si + 3] || 0) / 255 : 1;
    }
  }
  return { width: outW, height: outH, stride, channels, rgb: out, sampleFactor };
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
  ptsDen = 30,
}) {
  const plane = downsampleRgba(rgba, width, height, maxEdge);
  const t = Number(sourceTimeS);
  const safeT = Number.isFinite(t) && t >= 0 ? t : 0;
  const frameIndex = Math.max(0, Math.round(safeT * ptsDen));
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
    ptsDen,
    frameIndex,
    projectId: String(projectId || ""),
    clipId: String(clipId || ""),
    gradeRevision: String(gradeRevision || "0"),
    contextDigest: String(contextDigest || ""),
    roi: { x: 0, y: 0, width: plane.width, height: plane.height },
    sampleFactor: plane.sampleFactor,
  };
}

export function buildManagedPreviewScopeFrame(input) {
  return buildScopeFrameFromTaggedRgb(buildManagedPreviewScopeDescriptor(input));
}

/**
 * Orchestrates fetch → decode → tag → tryPublish with generation stale rejection.
 */
export function createManagedPreviewScopeProducer({
  getView,
  getSourceTimeS,
  fetchPreviewJpeg,
  decodeJpegToRgba,
  tryPublish,
  maxEdge = 320,
  ptsDen = 30,
  isPlaying = () => false,
  pauseIntervalMs = 100,
  playIntervalMs = 500,
  now = () => performance.now(),
} = {}) {
  let generation = 0;
  let lastAttemptMs = null;
  let destroyed = false;

  function bump() {
    generation += 1;
    return generation;
  }

  async function refresh(reason = "manual") {
    if (destroyed) return { accepted: false, reason: "destroyed" };
    const view = getView?.() || {};
    if (!view.clipId) return { accepted: false, reason: "no-clip" };
    const playing = Boolean(isPlaying?.());
    const minInterval = playing ? playIntervalMs : pauseIntervalMs;
    const t = now();
    if (lastAttemptMs !== null && t - lastAttemptMs < minInterval) {
      return { accepted: false, reason: "rate-limited", detail: reason };
    }
    lastAttemptMs = t;
    const gen = bump();
    const sourceTimeS = Number(getSourceTimeS?.() || 0);
    let jpeg;
    try {
      jpeg = await fetchPreviewJpeg(String(view.clipId), sourceTimeS, {
        gradeRevision: view.gradeRevision,
        generation: gen,
      });
    } catch (err) {
      return { accepted: false, reason: "fetch-failed", error: err };
    }
    if (destroyed || gen !== generation) {
      return { accepted: false, reason: "stale-generation" };
    }
    const decoded = await decodeJpegToRgba(jpeg);
    if (destroyed || gen !== generation) {
      return { accepted: false, reason: "stale-generation" };
    }
    const latest = getView?.() || {};
    if (
      String(latest.clipId) !== String(view.clipId) ||
      String(latest.gradeRevision) !== String(view.gradeRevision) ||
      String(latest.contextDigest) !== String(view.contextDigest)
    ) {
      return { accepted: false, reason: "stale-view" };
    }
    const frame = buildManagedPreviewScopeFrame({
      rgba: decoded.rgba,
      width: decoded.width,
      height: decoded.height,
      maxEdge,
      projectId: latest.projectId,
      clipId: latest.clipId,
      gradeRevision: latest.gradeRevision,
      contextDigest: latest.contextDigest,
      sourceTimeS,
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
