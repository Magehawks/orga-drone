import assert from "node:assert/strict";
import test from "node:test";
import {
  accumulateHistogram,
  accumulateRgbParade,
  accumulateVectorscope,
  accumulateWaveform,
  histogramBin,
  lumaY,
  vectorscopeCbCr,
} from "../../src/orga_drone/static/js/studio/scopes/accumulate.js";
import {
  colorBarVectorscopeTargets,
  createScopeFixture,
} from "../../src/orga_drone/static/js/studio/scopes/fixtures.js";
import {
  createScopeFrameV1,
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
} from "../../src/orga_drone/static/js/studio/scopes/scope-frame.js";

test("histogram uses 256 bins and peaks at expected code for solid gray", () => {
  const frame = createScopeFixture("gray");
  const hist = accumulateHistogram(frame);
  assert.equal(hist.bins, 256);
  const grayBin = histogramBin(0.5);
  assert.equal(grayBin, 128);
  assert.ok(hist.absolute.r[grayBin] > 0);
  assert.equal(hist.absolute.r[0], 0);
  assert.equal(hist.absolute.r[255], 0);
  const sum = hist.absolute.luma.reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(sum - hist.weightSum) < 1e-9);
});

test("black fixture fills bin 0 only", () => {
  const hist = accumulateHistogram(createScopeFixture("black"));
  assert.equal(hist.absolute.luma[0], hist.weightSum);
  for (let i = 1; i < 256; i += 1) assert.equal(hist.absolute.luma[i], 0);
});

test("red fixture isolates the red channel", () => {
  const hist = accumulateHistogram(createScopeFixture("red"));
  assert.equal(hist.absolute.r[255], hist.weightSum);
  assert.equal(hist.absolute.g[0], hist.weightSum);
  assert.equal(hist.absolute.b[0], hist.weightSum);
});

test("waveform places solid mid gray on the mid luminance row", () => {
  const wave = accumulateWaveform(createScopeFixture("gray"), { columns: 32, rows: 32 });
  const row = Math.floor(0.5 * 32);
  let mass = 0;
  for (let c = 0; c < 32; c += 1) mass += wave.density[row * 32 + c];
  assert.ok(mass > 0);
  assert.equal(wave.axis.y, "Y_prime_bt709");
});

test("RGB parade separates channel planes", () => {
  const parade = accumulateRgbParade(createScopeFixture("green"), { columns: 16, rows: 16 });
  const gRow = 15; // value 1.0 → last row before clamp
  let gMass = 0;
  let rMass = 0;
  for (let c = 0; c < 16; c += 1) {
    gMass += parade.panels.g[gRow * 16 + c];
    rMass += parade.panels.r[0 * 16 + c];
  }
  assert.ok(gMass > 0);
  assert.ok(rMass > 0);
  assert.deepEqual(parade.axis.channels, ["R_prime", "G_prime", "B_prime"]);
});

test("vectorscope axes and color-bar targets match BT.709 Cb/Cr formulas", () => {
  const red = vectorscopeCbCr(1, 0, 0);
  assert.ok(Math.abs(red.cr - (1 - lumaY(1, 0, 0)) / 1.5748) < 1e-12);
  assert.ok(Math.abs(red.cb - (0 - lumaY(1, 0, 0)) / 1.8556) < 1e-12);
  const targets = colorBarVectorscopeTargets();
  assert.equal(targets.length, 7);
  const scope = accumulateVectorscope(createScopeFixture("color-bars"), { size: 64 });
  assert.equal(scope.axis.encoding, "bt709_encoded_opponent");
  assert.deepEqual(scope.axis.range, [-0.5, 0.5]);
  for (const target of targets) {
    const col = Math.min(63, Math.max(0, Math.floor((target.cb + 0.5) * 64)));
    const row = Math.min(63, Math.max(0, Math.floor((0.5 - target.cr) * 64)));
    assert.ok(scope.density[row * 64 + col] > 0, `missing density for ${target.rgb}`);
  }
});

test("alpha=0 samples are ignored", () => {
  const channels = 4;
  const width = 2;
  const height = 1;
  const stride = width * channels;
  const rgb = new Float32Array([1, 0, 0, 0, 0, 1, 0, 1]);
  const frame = createScopeFrameV1({
    version: 1,
    width,
    height,
    stride,
    rgb,
    channels,
    profile: "bt709",
    transfer: "bt709",
    straightAlpha: true,
    ptsNum: 0,
    ptsDen: 1,
    frameIndex: 0,
    projectId: "p",
    clipId: "c",
    gradeRevision: "1",
    contextDigest: "d",
    tapId: SCOPE_TAP_IDS.FIXTURE,
    roi: { x: 0, y: 0, width, height },
    sampleFactor: 1,
    sourceKind: SCOPE_SOURCE_KINDS.FIXTURE,
  });
  const hist = accumulateHistogram(frame);
  assert.equal(hist.weightSum, 1);
  assert.equal(hist.absolute.g[255], 1);
  assert.equal(hist.absolute.r[255], 0);
});
