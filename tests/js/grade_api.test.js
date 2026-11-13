import assert from "node:assert/strict";
import test from "node:test";
import {
  findStep,
  neutralCurveParams,
  neutralPrimariesParams,
  upsertCurveStep,
  upsertManagedHslStep,
  upsertPrimariesStep,
  upsertWheelsStep,
} from "../../src/orga_drone/static/js/studio/grade-api.js";

test("neutral primaries match managed defaults", () => {
  assert.deepEqual(neutralPrimariesParams(), {
    exposure: 0,
    kelvin: 6500,
    tint: 0,
    contrast: 1,
    pivot: 0.18,
    saturation: 1,
    blacks: 0,
    shadows: 0,
    highlights: 0,
    whites: 0,
  });
});

test("findStep locates primaries without inventing missing types", () => {
  const grade = {
    steps: [
      { type: "input-transform-v1", id: "in" },
      { type: "primaries-v1", id: "p1", params: { exposure: 0.5 } },
    ],
  };
  assert.equal(findStep(grade, "primaries-v1")?.id, "p1");
  assert.equal(findStep(grade, "curves-v1"), null);
  assert.equal(findStep(null, "primaries-v1"), null);
});

test("upsertPrimariesStep inserts or updates without dropping other steps", () => {
  const grade = {
    steps: [{ type: "input-transform-v1", id: "in", enabled: true }],
  };
  const first = upsertPrimariesStep(grade, { exposure: 0.25, kelvin: 5600 });
  assert.equal(first.steps.length, 2);
  assert.equal(first.steps[0].type, "input-transform-v1");
  assert.equal(findStep(first, "primaries-v1").params.exposure, 0.25);
  assert.equal(findStep(first, "primaries-v1").params.kelvin, 5600);

  const second = upsertPrimariesStep(first, { exposure: -0.5, tint: 12 });
  assert.equal(second.steps.length, 2);
  const step = findStep(second, "primaries-v1");
  assert.equal(step.params.exposure, -0.5);
  assert.equal(step.params.kelvin, 5600);
  assert.equal(step.params.tint, 12);
  assert.equal(step.enabled, true);
});

test("upsertWheelsStep and upsertManagedHslStep share the grade steps array", () => {
  let grade = { steps: [] };
  grade = upsertWheelsStep(grade, { lift: 0.1, gamma: 1.1 });
  grade = upsertManagedHslStep(grade, { hue: 12, saturation: 1.2 });
  assert.equal(findStep(grade, "wheels-v1").params.lift, 0.1);
  assert.equal(findStep(grade, "managed-hsl-v1").params.hue, 12);
  assert.equal(grade.steps.length, 2);
});

test("upsertCurveStep inserts rgb and hue curve families", () => {
  const grade = { steps: [] };
  const rgb = upsertCurveStep(grade, "rgb-curves-v1", {
    master: [
      [0, 0],
      [0.5, 0.6],
      [1, 1],
    ],
  });
  assert.equal(findStep(rgb, "rgb-curves-v1").params.master[1][1], 0.6);
  const hue = upsertCurveStep(rgb, "hue-vs-hue-v1", neutralCurveParams("hue-vs-hue-v1"));
  assert.equal(hue.steps.length, 2);
  assert.deepEqual(findStep(hue, "hue-vs-hue-v1").params.curve[0], [0, 0]);
});
