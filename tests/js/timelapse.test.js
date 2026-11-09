import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_TIMELAPSE_SPEED,
  SEEK_SAMPLE_MIN_INTERVAL_MS,
  allowHtmlVideoAutoplay,
  allowedTargetRange,
  captureValidatedDraft,
  clampPreviewPlaybackRate,
  draftFromSpeed,
  draftFromTarget,
  flatTimelapseRamp,
  rampNeedsSeekPreview,
  shouldReconcileSeekSample,
  timelapseConflict,
  validatedDraftMatches,
} from "../../src/orga_drone/static/js/studio/timelapse.js";
import {
  parseRamp,
  rampSource,
  rampTime,
} from "../../src/orga_drone/static/js/studio/speed-ramp.js";

test("target duration and speed multiplier stay synchronized", () => {
  const eight = draftFromTarget(120, 15);
  assert.equal(eight.speed, 8);
  assert.equal(draftFromSpeed(120, 8).targetDurationS, 15);

  const twenty = draftFromTarget(300, 15);
  assert.equal(twenty.speed, 20);
  assert.equal(draftFromSpeed(300, 20).targetDurationS, 15);
  assert.equal(MAX_TIMELAPSE_SPEED, 20);
  assert.equal(eight.framesApproximate, true);
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

test("validated draft ownership rejects stale bounds and empty capture", () => {
  const draft = draftFromTarget(120, 15);
  const captured = captureValidatedDraft({
    clipId: "7",
    start: 0,
    end: 120,
    field: "target",
    draft,
  });
  assert.ok(validatedDraftMatches(captured, { clipId: "7", start: 0, end: 120 }));
  assert.equal(validatedDraftMatches(captured, { clipId: "7", start: 10, end: 120 }), false);
  assert.equal(validatedDraftMatches(captured, { clipId: "8", start: 0, end: 120 }), false);
  assert.equal(
    captureValidatedDraft({ clipId: "7", start: 0, end: 120, field: "target", draft: null }),
    null
  );
});

test("flat timelapse ramps reuse the shared ADR 0034 parser", () => {
  const ramp = flatTimelapseRamp(30, 90, 4);
  assert.ok(parseRamp(ramp));
  assert.equal(rampTime(ramp, 90) - rampTime(ramp, 30), 15);
  assert.ok(flatTimelapseRamp(0, 120, 8));
  assert.ok(flatTimelapseRamp(0, 300, 20));
  assert.equal(clampPreviewPlaybackRate(20), 16);
  assert.equal(clampPreviewPlaybackRate(8), 8);
  assert.equal(rampNeedsSeekPreview(flatTimelapseRamp(0, 120, 8)), false);
  assert.equal(rampNeedsSeekPreview(flatTimelapseRamp(0, 300, 20)), true);
  assert.ok(
    parseRamp({
      v: 1,
      interp: "reciprocal_smoothstep",
      points: [
        { source_s: 0, speed: 0.5 },
        { source_s: 5, speed: 20 },
        { source_s: 10, speed: 1 },
      ],
    })
  );
});

test("seek-sampled 20× preview advances source with Story time and blocks HTML autoplay", () => {
  const ramp = flatTimelapseRamp(30, 330, 20);
  assert.ok(rampNeedsSeekPreview(ramp));
  // Wall-clock Story +0.5 s at 20× must land +10 s into the source span.
  assert.ok(Math.abs(rampSource(ramp, 0.5, 30, 330) - 40) < 1e-9);
  assert.ok(Math.abs(rampTime(ramp, 40) - rampTime(ramp, 30) - 0.5) < 1e-9);
  assert.equal(allowHtmlVideoAutoplay({ playing: true, seekSample: true }), false);
  assert.equal(allowHtmlVideoAutoplay({ playing: true, seekSample: false }), true);
  assert.equal(shouldReconcileSeekSample(0, 10), true);
  assert.equal(shouldReconcileSeekSample(100, 100 + SEEK_SAMPLE_MIN_INTERVAL_MS - 1), false);
  assert.equal(shouldReconcileSeekSample(100, 100 + SEEK_SAMPLE_MIN_INTERVAL_MS), true);
});
