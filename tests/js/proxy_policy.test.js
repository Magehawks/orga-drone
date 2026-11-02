import assert from "node:assert/strict";
import test from "node:test";

import {
  evaluateLutProxyEligibility,
  evaluateLutWebglHandling,
  lutProxyPrepareKey,
} from "../../src/orga_drone/static/js/studio/proxy-policy.js";

test("eligibility keeps the existing video and fallback rules", () => {
  assert.equal(evaluateLutProxyEligibility({ kind: "photo", hasLut: true }), false);
  assert.equal(evaluateLutProxyEligibility({ kind: "video", hasClipAudio: true }), false);
  assert.equal(evaluateLutProxyEligibility({ kind: "video", playbackSpeed: 0.5 }), false);
  assert.equal(evaluateLutProxyEligibility({ kind: "video", hasSlowBar: true }), false);
  assert.equal(evaluateLutProxyEligibility({ kind: "video", sectionRepeats: 2 }), false);
  assert.equal(evaluateLutProxyEligibility({ kind: "video", forwardLoopActive: true }), false);
  assert.equal(evaluateLutProxyEligibility({ kind: "video", colorAnimationKeys: 2 }), false);
  assert.equal(evaluateLutProxyEligibility({ kind: "video", saturationRampEnabled: true }), false);
});

test("eligibility accepts LUT, HSL, and colour wheel color work", () => {
  assert.equal(evaluateLutProxyEligibility({ kind: "video", hasLut: true }), true);
  assert.equal(evaluateLutProxyEligibility({ kind: "video", hslActive: true }), true);
  assert.equal(evaluateLutProxyEligibility({ kind: "video", colorWheelsActive: true }), true);
  assert.equal(evaluateLutProxyEligibility({ kind: "video" }), false);
  assert.equal(
    evaluateLutProxyEligibility({ kind: "video", playbackSpeed: "1", sectionRepeats: "1" }),
    false
  );
});

test("WebGL handling falls back for generated color stages", () => {
  assert.equal(evaluateLutWebglHandling({ kind: "photo", hasLut: true }), false);
  assert.equal(evaluateLutWebglHandling({ kind: "video", webglSupported: false }), false);
  assert.equal(
    evaluateLutWebglHandling({ kind: "video", webglSupported: true, colorAnimationKeys: 2 }),
    false
  );
  assert.equal(
    evaluateLutWebglHandling({ kind: "video", webglSupported: true, hslActive: true }),
    false
  );
  assert.equal(
    evaluateLutWebglHandling({ kind: "video", webglSupported: true, colorWheelsActive: true }),
    false
  );
  assert.equal(evaluateLutWebglHandling({ kind: "video", webglSupported: true }), false);
  assert.equal(
    evaluateLutWebglHandling({ kind: "video", webglSupported: true, hasLut: true }),
    true
  );
});

test("proxy prepare key keeps the persisted color and timing fields in order", () => {
  const dataset = {
    colorLook: "look",
    imageAdjust: "image",
    hsl: "hsl",
    colorWheels: "wheels",
    sourceIn: "1",
    sourceOut: "2",
    saturationRamp: "ramp",
    playbackSpeed: "1",
    unrelated: "ignored",
  };

  assert.equal(
    lutProxyPrepareKey(dataset),
    JSON.stringify(["look", "image", "hsl", "wheels", "1", "2", "ramp", "1"])
  );
  assert.notEqual(lutProxyPrepareKey(dataset), lutProxyPrepareKey({ ...dataset, hsl: "changed" }));
  assert.equal(lutProxyPrepareKey(), JSON.stringify(Array(8).fill(undefined)));
});
