import assert from "node:assert/strict";
import test from "node:test";
import {
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
  SCOPE_TAP_REASONS,
  accumulateHistogram,
  buildManagedPreviewScopeFrame,
  createManagedPreviewScopeProducer,
  createScopeTapController,
  managedPreviewTaggedCapturePlane,
  probeScopeTapCapability,
  quantizePreviewScopeTime,
  sampleFactorForMaxEdge,
} from "../../src/orga_drone/static/js/studio/scopes/index.js";

test("tagged managed preview plane enables capability without trusting blit", () => {
  const capability = probeScopeTapCapability({
    renderAdapterReady: true,
    taggedCapturePlane: managedPreviewTaggedCapturePlane(true),
    candidates: [
      { id: "preview-blit", kind: "display-blit", hasFraming: true },
      { id: "lut-still", kind: "jpeg-still" },
    ],
  });
  assert.equal(capability.available, true);
  assert.equal(capability.reason, "");
  assert.equal(capability.tapId, SCOPE_TAP_IDS.CLIP_POST_GRADE);
  assert.ok(capability.notes.some((n) => n.includes("managed-preview-frame-v1")));
  assert.ok(capability.notes.some((n) => n.includes("display-blit")));
});

test("incomplete tagged plane stays unavailable", () => {
  const capability = probeScopeTapCapability({
    renderAdapterReady: true,
    taggedCapturePlane: {
      producer: "managed-preview-frame-v1",
      profile: "bt709",
      transfer: "srgb",
      captureStage: "clip-post-grade-pre-frame",
      capturePlane: "bt709-encoded-rgba",
    },
  });
  assert.equal(capability.available, false);
  assert.equal(capability.reason, SCOPE_TAP_REASONS.AWAITING_RENDER_ADAPTER);
});

test("sampleFactor is applied once by accumulate on full-size buffer", () => {
  const width = 40;
  const height = 20;
  const rgba = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < rgba.length; i += 4) {
    rgba[i] = 255;
    rgba[i + 3] = 255;
  }
  const factor = sampleFactorForMaxEdge(width, height, 10);
  assert.equal(factor, 4);
  const frame = buildManagedPreviewScopeFrame({
    rgba,
    width,
    height,
    maxEdge: 10,
    projectId: "p",
    clipId: "c",
    gradeRevision: "1",
    contextDigest: "d",
  });
  assert.equal(frame.width, 40);
  assert.equal(frame.height, 20);
  assert.equal(frame.sampleFactor, 4);
  const hist = accumulateHistogram(frame);
  assert.equal(hist.sampleFactor, 4);
  assert.equal(hist.sampleCount, Math.ceil(40 / 4) * Math.ceil(20 / 4));
});

test("managed preview descriptor builds engine-tap frame from quantized time", () => {
  const rgba = new Uint8ClampedArray([10, 20, 30, 255, 40, 50, 60, 255]);
  const frame = buildManagedPreviewScopeFrame({
    rgba,
    width: 2,
    height: 1,
    maxEdge: 2,
    projectId: "p",
    clipId: "c",
    gradeRevision: "7",
    contextDigest: "d",
    sourceTimeS: 1.04,
    ptsDen: 10,
  });
  assert.equal(frame.sourceKind, SCOPE_SOURCE_KINDS.ENGINE_TAP);
  assert.equal(frame.gradeRevision, "7");
  assert.equal(quantizePreviewScopeTime(1.04), 1.0);
  assert.equal(frame.frameIndex, 10);
  assert.equal(frame.profile, "bt709");
});

test("producer rejects stale generation after invalidate", async () => {
  let publishes = 0;
  const producer = createManagedPreviewScopeProducer({
    getView: () => ({
      projectId: "p",
      clipId: "11",
      gradeRevision: "1",
      contextDigest: "x",
    }),
    getSourceTimeS: () => 0,
    isPlaying: () => false,
    pauseIntervalMs: 0,
    fetchPreviewJpeg: async () => ({
      bytes: new ArrayBuffer(8),
      gradeRevision: "1",
      sourceTimeS: 0,
    }),
    decodeJpegToRgba: async () => ({
      width: 2,
      height: 1,
      rgba: new Uint8ClampedArray([255, 0, 0, 255, 0, 255, 0, 255]),
    }),
    tryPublish: () => {
      publishes += 1;
      return { accepted: true };
    },
  });
  const pending = producer.refresh("first");
  producer.invalidate();
  const result = await pending;
  assert.equal(result.accepted, false);
  assert.equal(result.reason, "stale-generation");
  assert.equal(publishes, 0);
});

test("producer rejects response when grade revision drifts", async () => {
  const producer = createManagedPreviewScopeProducer({
    getView: () => ({
      projectId: "p",
      clipId: "11",
      gradeRevision: "1",
      contextDigest: "x",
    }),
    getSourceTimeS: () => 0,
    isPlaying: () => false,
    pauseIntervalMs: 0,
    fetchPreviewJpeg: async () => ({
      bytes: new ArrayBuffer(8),
      gradeRevision: "9",
      sourceTimeS: 0,
    }),
    decodeJpegToRgba: async () => ({
      width: 1,
      height: 1,
      rgba: new Uint8ClampedArray([1, 2, 3, 255]),
    }),
    tryPublish: () => ({ accepted: true }),
  });
  const result = await producer.refresh("rev");
  assert.equal(result.accepted, false);
  assert.equal(result.reason, "stale-revision");
});

test("controller accepts managed preview frames when capability is open", () => {
  const injected = [];
  const controller = createScopeTapController({
    panel: {
      syncView() {},
      injectFrame(frame) {
        injected.push(frame);
        return { accepted: true };
      },
    },
    getView: () => ({
      projectId: "p",
      clipId: "c",
      gradeRevision: "3",
      contextDigest: "d",
      tapId: SCOPE_TAP_IDS.CLIP_POST_GRADE,
    }),
    getCapability: () =>
      probeScopeTapCapability({
        taggedCapturePlane: managedPreviewTaggedCapturePlane(true),
      }),
    minIntervalMs: 0,
  });
  const rgba = new Uint8ClampedArray(4).fill(128);
  rgba[3] = 255;
  const frame = buildManagedPreviewScopeFrame({
    rgba,
    width: 1,
    height: 1,
    projectId: "p",
    clipId: "c",
    gradeRevision: "3",
    contextDigest: "d",
  });
  const result = controller.tryPublish(frame);
  assert.equal(result.accepted, true);
  assert.equal(injected.length, 1);
});
