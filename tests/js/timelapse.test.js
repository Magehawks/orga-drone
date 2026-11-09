import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_TIMELAPSE_SPEED,
  allowedTargetRange,
  clampPreviewPlaybackRate,
  draftFromSpeed,
  draftFromTarget,
  flatTimelapseRamp,
  timelapseConflict,
} from "../../src/orga_drone/static/js/studio/timelapse.js";
import { parseRamp, rampTime } from "../../src/orga_drone/static/js/studio/speed-ramp.js";

test("target duration and speed multiplier stay synchronized", () => {
  const eight = draftFromTarget(120, 15);
  assert.equal(eight.speed, 8);
  assert.equal(draftFromSpeed(120, 8).targetDurationS, 15);

  const twenty = draftFromTarget(300, 15);
  assert.equal(twenty.speed, 20);
  assert.equal(draftFromSpeed(300, 20).targetDurationS, 15);
  assert.equal(MAX_TIMELAPSE_SPEED, 20);
});

test("unsupported values and conflicts refuse mutation helpers", () => {
  assert.equal(draftFromTarget(120, 5), null);
  assert.equal(draftFromSpeed(10, 0.5), null);
  assert.equal(draftFromSpeed(10, 20.001), null);
  assert.equal(flatTimelapseRamp(0, 10, 1), null);
  assert.ok(timelapseConflict({ hasRamp: true, sectionRepeats: 1, forwardLoop: false }));
  assert.ok(timelapseConflict({ hasRamp: false, sectionRepeats: 2, forwardLoop: false }));
  assert.ok(timelapseConflict({ hasRamp: false, sectionRepeats: 1, forwardLoop: true }));
  assert.equal(timelapseConflict({ hasRamp: false, sectionRepeats: 1, forwardLoop: false }), null);
  const range = allowedTargetRange(120);
  assert.ok(range);
  assert.equal(range.min, 6);
  assert.equal(range.max, 120);
});

test("flat timelapse ramps reuse the shared ADR 0034 parser", () => {
  const ramp = flatTimelapseRamp(30, 90, 4);
  assert.ok(parseRamp(ramp));
  assert.equal(rampTime(ramp, 90) - rampTime(ramp, 30), 15);
  assert.ok(flatTimelapseRamp(0, 120, 8));
  assert.ok(flatTimelapseRamp(0, 300, 20));
  assert.equal(clampPreviewPlaybackRate(20), 16);
  assert.equal(clampPreviewPlaybackRate(8), 8);
});
