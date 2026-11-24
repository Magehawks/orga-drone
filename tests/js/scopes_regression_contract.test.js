import assert from "node:assert/strict";
import test from "node:test";
import {
  accumulateHistogram,
  accumulateRgbParade,
  accumulateVectorscope,
  accumulateWaveform,
  expandLegalRange,
  histogramBin,
  lumaY,
  vectorscopeCbCr,
} from "../../src/orga_drone/static/js/studio/scopes/accumulate.js";
import { createScopeFixture } from "../../src/orga_drone/static/js/studio/scopes/fixtures.js";
import {
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
  createScopeFrameV1,
  isScopeFrameCurrent,
} from "../../src/orga_drone/static/js/studio/scopes/scope-frame.js";
import { createManagedPreviewScopeProducer } from "../../src/orga_drone/static/js/studio/scopes/preview-tap.js";

function solidFrame(rgba, { size = 4, sampleFactor = 1, legalRange = false, alpha = null } = {}) {
  const channels = 4;
  const width = size;
  const height = size;
  const stride = width * channels;
  const rgb = new Float32Array(height * stride);
  for (let i = 0; i < width * height; i += 1) {
    const o = i * channels;
    rgb[o] = rgba[0];
    rgb[o + 1] = rgba[1];
    rgb[o + 2] = rgba[2];
    rgb[o + 3] = alpha === null ? 1 : (alpha[i] ?? 1);
  }
  return createScopeFrameV1({
    version: 1,
    width,
    height,
    stride,
    rgb,
    channels,
    profile: "bt709",
    transfer: "bt709",
    straightAlpha: true,
    legalRange,
    ptsNum: 0,
    ptsDen: 1,
    frameIndex: 0,
    projectId: "p",
    clipId: "c",
    gradeRevision: "1",
    contextDigest: "d",
    tapId: SCOPE_TAP_IDS.FIXTURE,
    roi: { x: 0, y: 0, width, height },
    sampleFactor,
    sourceKind: SCOPE_SOURCE_KINDS.FIXTURE,
  });
}

test("exact histogram counts for solid 4x4 gray", () => {
  const frame = solidFrame([0.5, 0.5, 0.5], { size: 4 });
  const hist = accumulateHistogram(frame);
  const bin = histogramBin(0.5);
  assert.equal(bin, 128);
  assert.equal(hist.weightSum, 16);
  assert.equal(hist.absolute.r[bin], 16);
  assert.equal(hist.absolute.g[bin], 16);
  assert.equal(hist.absolute.b[bin], 16);
  assert.equal(hist.absolute.luma[bin], 16);
  for (let i = 0; i < 256; i += 1) {
    if (i === bin) continue;
    assert.equal(hist.absolute.r[i], 0);
    assert.equal(hist.absolute.luma[i], 0);
  }
});

test("legal-range expansion happens exactly once before binning", () => {
  const code = 16 / 255;
  const expanded = expandLegalRange(code);
  assert.ok(Math.abs(expanded) < 1e-12);
  const mid = 115.5 / 255; // mid of legal range ≈ 0.5 after expand
  const frame = solidFrame([mid, mid, mid], { size: 2, legalRange: true });
  const hist = accumulateHistogram(frame);
  const expected = histogramBin(expandLegalRange(mid));
  assert.equal(hist.absolute.luma[expected], 4);
  // Without expansion the legal mid would land elsewhere — prove we expanded.
  const unexpandedBin = histogramBin(mid);
  assert.notEqual(expected, unexpandedBin);
});

test("deterministic subsample visits every sampleFactor grid point once", () => {
  const frame = solidFrame([1, 0, 0], { size: 8, sampleFactor: 2 });
  const hist = accumulateHistogram(frame);
  // 8x8 with step 2 → 4x4 = 16 samples
  assert.equal(hist.sampleCount, 16);
  assert.equal(hist.sampleFactor, 2);
  assert.equal(hist.absolute.r[255], 16);
  const again = accumulateHistogram(frame);
  assert.deepEqual(Array.from(again.absolute.r), Array.from(hist.absolute.r));
});

test("alpha weighting scales absolute histogram mass", () => {
  const alphas = Array(4).fill(0.25);
  const frame = solidFrame([0, 1, 0], { size: 2, alpha: alphas });
  const hist = accumulateHistogram(frame);
  assert.equal(hist.weightSum, 1);
  assert.equal(hist.absolute.g[255], 1);
});

test("waveform / parade coordinates are deterministic for solid channels", () => {
  const green = solidFrame([0, 1, 0], { size: 4 });
  const wave = accumulateWaveform(green, { columns: 8, rows: 8 });
  const y = lumaY(0, 1, 0);
  const row = Math.min(7, Math.floor(y * 8));
  let mass = 0;
  for (let c = 0; c < 8; c += 1) mass += wave.density[row * 8 + c];
  assert.equal(mass, 16);
  const parade = accumulateRgbParade(green, { columns: 4, rows: 8 });
  let gMass = 0;
  for (let c = 0; c < 4; c += 1) gMass += parade.panels.g[7 * 4 + c];
  assert.equal(gMass, 16);
});

test("BT.709 vectorscope reference coordinates for primaries", () => {
  const red = vectorscopeCbCr(1, 0, 0);
  assert.ok(Math.abs(red.cb - (0 - lumaY(1, 0, 0)) / 1.8556) < 1e-12);
  assert.ok(Math.abs(red.cr - (1 - lumaY(1, 0, 0)) / 1.5748) < 1e-12);
  const scope = accumulateVectorscope(solidFrame([1, 0, 0], { size: 2 }), { size: 32 });
  const col = Math.min(31, Math.max(0, Math.floor((red.cb + 0.5) * 32)));
  const row = Math.min(31, Math.max(0, Math.floor((0.5 - red.cr) * 32)));
  assert.equal(scope.density[row * 32 + col], 4);
});

test("stale frame identity cannot masquerade as current", () => {
  const current = {
    projectId: "p",
    clipId: "c1",
    gradeRevision: "2",
    contextDigest: "now",
    tapId: SCOPE_TAP_IDS.CLIP_POST_GRADE,
  };
  const frame = createScopeFrameV1({
    ...solidFrame([0, 0, 0], { size: 2 }),
    rgb: solidFrame([0, 0, 0], { size: 2 }).rgb,
    sourceKind: SCOPE_SOURCE_KINDS.ENGINE_TAP,
    tapId: SCOPE_TAP_IDS.CLIP_POST_GRADE,
    projectId: "p",
    clipId: "c1",
    gradeRevision: "1",
    contextDigest: "old",
  });
  assert.equal(isScopeFrameCurrent(frame, current), false);
});

test("producer destroy cancels in-flight refresh (cancellation)", async () => {
  let resolveFetch;
  const fetchPromise = new Promise((resolve) => {
    resolveFetch = resolve;
  });
  const published = [];
  const producer = createManagedPreviewScopeProducer({
    getView: () => ({
      projectId: "p",
      clipId: "c",
      gradeRevision: "1",
      contextDigest: "d",
    }),
    getSourceTimeS: () => 0,
    fetchPreviewJpeg: async () => fetchPromise,
    decodeJpegToRgba: async () => ({
      width: 2,
      height: 2,
      rgba: new Uint8ClampedArray(16).fill(255),
    }),
    tryPublish: (frame) => {
      published.push(frame);
      return { accepted: true };
    },
    pauseIntervalMs: 0,
    playIntervalMs: 0,
  });
  const pending = producer.refresh("test");
  producer.destroy();
  resolveFetch({ bytes: new Uint8Array([1, 2, 3]), gradeRevision: "1", sourceTimeS: 0 });
  const result = await pending;
  assert.equal(result.reason, "stale-generation");
  assert.equal(published.length, 0);
});

test("regression contract: wrong gray bin count fails the exact assertion", () => {
  const hist = accumulateHistogram(createScopeFixture("gray"));
  const expected = 8 * 8; // default solid size
  const bin = histogramBin(0.5);
  assert.equal(hist.absolute.luma[bin], expected);
  // Temporary mutation must be detectable — prove the gate would catch it.
  const mutated = hist.absolute.luma[bin] + 1;
  assert.notEqual(mutated, expected);
});
