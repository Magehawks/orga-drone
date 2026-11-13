import test from "node:test";
import assert from "node:assert/strict";
import {
  isManagedWebglBakeMode,
  managedBakeUrl,
  probeManagedGpuCapabilities,
} from "../../src/orga_drone/static/js/studio/managed-gpu-adapter.js";

function grade(steps) {
  return {
    evaluator: "managed-sdr-v1",
    revision: 2,
    grade: {
      schema_version: 1,
      evaluator: "managed-sdr-v1",
      steps,
      selections: [],
      animation: [],
    },
  };
}

test("pointwise primaries are webgl-bake-tetrahedral supported", () => {
  const probe = probeManagedGpuCapabilities(
    grade([{ id: "p1", type: "primaries-v1", enabled: true, selection_id: null }])
  );
  assert.equal(probe.supported, true);
  assert.equal(probe.mode, "webgl-bake-tetrahedral");
  assert.equal(probe.interpolation, "tetrahedral");
  assert.equal(probe.exact, false);
  assert.ok(probe.reasons.includes("rgba8-quantization"));
});

test("spatial selection forces cpu fallback", () => {
  const probe = probeManagedGpuCapabilities(
    grade([
      {
        id: "p1",
        type: "primaries-v1",
        enabled: true,
        selection_id: "sel-1",
      },
    ])
  );
  assert.equal(probe.supported, false);
  assert.equal(probe.mode, "cpu-fallback");
  assert.ok(probe.unsupported.some((item) => item.startsWith("spatial:")));
});

test("managedBakeUrl includes revision", () => {
  assert.equal(managedBakeUrl(12, 4), "/api/studio/12/grade/bake.cube?rev=4");
});

test("isManagedWebglBakeMode accepts tetrahedral and legacy bake modes", () => {
  assert.equal(isManagedWebglBakeMode("webgl-bake-tetrahedral"), true);
  assert.equal(isManagedWebglBakeMode("webgl-bake-approx"), true);
  assert.equal(isManagedWebglBakeMode("webgl-bake"), true);
  assert.equal(isManagedWebglBakeMode("cpu-fallback"), false);
});
