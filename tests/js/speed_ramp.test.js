import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  parseRamp,
  rampTime,
  rampSource,
  rampSpeed,
  rampPreset,
  rampMediaTime,
} from "../../src/orga_drone/static/js/studio/speed-ramp.js";

const fixture = JSON.parse(readFileSync(new URL("../fixtures/speed_ramp.json", import.meta.url)));
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`);
test("canonical shared speed, integral and inverse fixtures", () => {
  const ramp = parseRamp(fixture.curve);
  for (const sample of fixture.samples) {
    close(rampTime(ramp, sample.source), sample.story);
    close(rampSpeed(ramp, sample.source), sample.speed);
    close(rampSource(ramp, sample.story, 0, 5), sample.source);
  }
});
test("trim and split keep the original curve and duration", () => {
  const ramp = fixture.curve;
  const origin = rampTime(ramp, 1);
  for (let source = 1; source < 3; source += 0.013) {
    close(rampSource(ramp, rampTime(ramp, source) - origin, 1, 3), source);
  }
  close(
    rampTime(ramp, 2) - origin + (rampTime(ramp, 3) - rampTime(ramp, 2)),
    rampTime(ramp, 3) - origin
  );
});
test("presets remain editable bounded curves", () => {
  for (const id of ["slow_fast_slow", "fast_slow_fast", "acceleration", "deceleration"]) {
    const ramp = rampPreset(id, 3, 9);
    assert.ok(parseRamp(ramp));
    assert.equal(ramp.points[0].source_s, 3);
    assert.equal(ramp.points.at(-1).source_s, 9);
  }
  assert.equal(rampPreset("acceleration", 0, 0.09), null);
  assert.equal(rampPreset("unknown", 0, 4), null);
});

test("trimmed stream and clip-local proxy share source landmarks", () => {
  const ramp = {
    ...fixture.curve,
    points: fixture.curve.points.map((p) => ({ ...p, source_s: p.source_s + 5 })),
  };
  close(rampMediaTime(ramp, 6.59375, 5, 9), 7);
  close(rampMediaTime(ramp, 6.59375, 5, 9, 5), 2);
});
test("malformed, extreme and nonfinite speeds are refused", () => {
  assert.equal(parseRamp({ ...fixture.curve, points: [null, null] }), null);
  for (const value of [null, {}, { ...fixture.curve, points: [] }])
    assert.equal(parseRamp(value), null);
  for (const speed of [0, -1, 0.249, 4.001, NaN, Infinity, true, "1"]) {
    const value = structuredClone(fixture.curve);
    value.points[0].speed = speed;
    assert.equal(parseRamp(value), null);
  }
});
