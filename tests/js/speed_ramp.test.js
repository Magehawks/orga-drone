import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  parseRamp,
  rampTime,
  rampSource,
  rampSourceAtTime,
  rampSpeed,
  rampPreset,
  rampMediaTime,
  edgeSourceAfterRampDrag,
  placeRampRegion,
  rampAfterRegionDrag,
  remapRampSpan,
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

test("edge drag uses absolute inverse on asymmetric trimmed ramps", () => {
  const ramp = parseRamp({
    v: 1,
    interp: "reciprocal_smoothstep",
    points: [
      { source_s: 0, speed: 0.5 },
      { source_s: 4, speed: 4 },
      { source_s: 8, speed: 0.5 },
    ],
  });
  const startIn = 5;
  const startOut = 8;
  const delta = 1.25;
  const expectedOut = rampSourceAtTime(ramp, rampTime(ramp, startOut) + delta, 0, 10);
  const moved = edgeSourceAfterRampDrag(ramp, {
    edge: "out",
    sourceIn: startIn,
    sourceOut: startOut,
    deltaStory: delta,
    repeats: 1,
    catalog: 10,
  });
  assert.equal(moved.inS, startIn);
  close(moved.outS, Number(expectedOut.toFixed(2)));
  assert.ok(Math.abs(rampTime(ramp, moved.outS) - rampTime(ramp, startOut) - delta) < 0.02);

  const left = edgeSourceAfterRampDrag(ramp, {
    edge: "in",
    sourceIn: startIn,
    sourceOut: startOut,
    deltaStory: -0.8,
    repeats: 2,
    catalog: 10,
  });
  const expectedIn = rampSourceAtTime(ramp, rampTime(ramp, startIn) - 0.8 / 2, 0, 10);
  assert.equal(left.outS, startOut);
  close(left.inS, Number(expectedIn.toFixed(2)));
  // Absolute primitive fed as relative story with start=0 coincides only because
  // rampTime(0) is 0; keep callers on rampSourceAtTime / edgeSourceAfterRampDrag.
  close(rampSource(ramp, rampTime(ramp, startOut) + delta, 0, 10), expectedOut);
});

test("edge remap localizes a sub-span with 1× joins and keeps curve character", () => {
  const ramp = rampPreset("slow_fast_slow", 0, 60);
  const localized = remapRampSpan(ramp, 10, 40, { playStart: 0, playEnd: 60 });
  assert.ok(localized);
  assert.equal(localized.points[0].source_s, 10);
  assert.equal(localized.points.at(-1).source_s, 40);
  assert.equal(localized.points[0].speed, 1);
  assert.equal(localized.points.at(-1).speed, 1);
  assert.equal(localized.points.length, 5);
  assert.equal(localized.points[2].speed, 4);
  assert.equal(rampSpeed(localized, 5), 1);
  assert.equal(rampSpeed(localized, 50), 1);
  assert.ok(Math.abs(rampSpeed(localized, 25) - 4) < 0.05);
  const full = remapRampSpan(ramp, 0, 60, { playStart: 0, playEnd: 60 });
  assert.ok(full);
  assert.equal(full.points[0].speed, 0.5);
  assert.equal(full.points.at(-1).speed, 0.5);
});

test("edge remap can translate a localized span without changing its length", () => {
  const ramp = remapRampSpan(rampPreset("slow_fast_slow", 0, 60), 10, 40, {
    playStart: 0,
    playEnd: 60,
  });
  const moved = remapRampSpan(ramp, 20, 50, { playStart: 0, playEnd: 60 });
  assert.ok(moved);
  assert.equal(moved.points[0].source_s, 20);
  assert.equal(moved.points.at(-1).source_s, 50);
  assert.equal(moved.points[0].speed, 1);
  assert.equal(moved.points.at(-1).speed, 1);
  assert.ok(moved.points.some((point) => point.speed === 4));
});

test("edge remap wraps two-point presets with 1× joins", () => {
  const ramp = rampPreset("acceleration", 0, 20);
  const localized = remapRampSpan(ramp, 4, 14, { playStart: 0, playEnd: 20 });
  assert.ok(localized);
  assert.equal(localized.points.length, 4);
  assert.equal(localized.points[0].speed, 1);
  assert.equal(localized.points.at(-1).speed, 1);
  assert.equal(localized.points[1].speed, 0.5);
  assert.equal(localized.points[2].speed, 4);
  assert.equal(remapRampSpan(ramp, 0, 0.01, { playStart: 0, playEnd: 0.02 }), null);
});

test("malformed, extreme and nonfinite speeds are refused", () => {
  assert.equal(parseRamp({ ...fixture.curve, points: [null, null] }), null);
  for (const value of [null, {}, { ...fixture.curve, points: [] }])
    assert.equal(parseRamp(value), null);
  for (const speed of [0, -1, 0.249, 20.001, NaN, Infinity, true, "1"]) {
    const value = structuredClone(fixture.curve);
    value.points[0].speed = speed;
    assert.equal(parseRamp(value), null);
  }
  assert.ok(
    parseRamp({
      v: 1,
      interp: "reciprocal_smoothstep",
      points: [
        { source_s: 0, speed: 8 },
        { source_s: 120, speed: 8 },
      ],
    })
  );
  assert.ok(
    parseRamp({
      v: 1,
      interp: "reciprocal_smoothstep",
      points: [
        { source_s: 0, speed: 20 },
        { source_s: 300, speed: 20 },
      ],
    })
  );
});

test("a bounded region plays at 1× outside and keeps the curve inside", () => {
  const ramp = parseRamp({
    v: 1,
    interp: "reciprocal_smoothstep",
    region: { start_s: 2, end_s: 4 },
    points: [
      { source_s: 2, speed: 0.5 },
      { source_s: 4, speed: 0.5 },
    ],
  });
  assert.equal(rampSpeed(ramp, 1), 1);
  assert.equal(rampSpeed(ramp, 2), 0.5);
  assert.equal(rampSpeed(ramp, 4.2), 1);
  close(rampTime(ramp, 6) - rampTime(ramp, 0), 8);
  const legacy = {
    v: 1,
    interp: "reciprocal_smoothstep",
    points: ramp.points,
  };
  close(rampTime(ramp, 4) - rampTime(ramp, 2), rampTime(legacy, 4) - rampTime(legacy, 2));
  assert.equal(parseRamp({ ...ramp, region: { start_s: 3, end_s: 3.5 } }), null);
  assert.equal(parseRamp({ ...fixture.curve, region: { start_s: 1, end_s: 2 } }), null);
});

test("placing and dragging a region preserves curve speeds", () => {
  const ramp = rampPreset("slow_fast_slow", 0, 60);
  const placed = placeRampRegion(ramp, 10, 40, { playStart: 0, playEnd: 60 });
  assert.equal(placed.region.start_s, 10);
  assert.equal(placed.region.end_s, 40);
  assert.deepEqual(
    placed.points.map((point) => point.speed),
    [0.5, 4, 0.5]
  );
  assert.equal(rampSpeed(placed, 9), 1);
  assert.equal(rampSpeed(placed, 25), 4);
  assert.equal(rampSpeed(placed, 41), 1);
  const moved = rampAfterRegionDrag(placed, {
    mode: "move",
    deltaStory: 100,
    playStart: 0,
    playEnd: 60,
  });
  assert.equal(moved.region.start_s, 30);
  assert.equal(moved.region.end_s, 60);
  assert.deepEqual(
    moved.points.map((point) => point.speed),
    [0.5, 4, 0.5]
  );
  const before = rampTime(placed, 40) - rampTime(placed, 10);
  const resized = rampAfterRegionDrag(placed, {
    mode: "end",
    deltaStory: 3,
    playStart: 0,
    playEnd: 60,
  });
  assert.equal(resized.region.start_s, 10);
  assert.equal(resized.points[1].speed, 4);
  const after = rampTime(resized, resized.region.end_s) - rampTime(resized, 10);
  assert.ok(Math.abs(after - (before + 3)) < 0.02, `${after} != ${before + 3}`);
  const started = rampAfterRegionDrag(placed, {
    mode: "start",
    deltaStory: -2,
    playStart: 0,
    playEnd: 60,
  });
  assert.equal(started.region.start_s, 8);
  assert.equal(started.region.end_s, 40);
  assert.equal(started.points[0].speed, 0.5);
});
