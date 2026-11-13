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

test("pointwise primaries default to rgba8 exact:false", () => {
  const probe = probeManagedGpuCapabilities(
    grade([{ id: "p1", type: "primaries-v1", enabled: true, selection_id: null }])
  );
  assert.equal(probe.supported, true);
  assert.equal(probe.mode, "webgl-bake-tetrahedral");
  assert.equal(probe.interpolation, "tetrahedral");
  assert.equal(probe.exact, false);
  assert.ok(probe.reasons.includes("rgba8-quantization"));
  assert.match(probe.adapter, /v3-precision-gated/);
});

test("RGBA32F enables exact:true; RGBA16F stays labeled approx", () => {
  const f32 = probeManagedGpuCapabilities(
    grade([{ id: "p1", type: "primaries-v1", enabled: true, selection_id: null }]),
    { lutPrecision: "rgba32f" }
  );
  assert.equal(f32.exact, true);
  assert.equal(f32.lutPrecision, "rgba32f");
  assert.deepEqual(f32.reasons, []);

  const f16 = probeManagedGpuCapabilities(
    grade([{ id: "p1", type: "primaries-v1", enabled: true, selection_id: null }]),
    { lutPrecision: "rgba16f" }
  );
  assert.equal(f16.exact, false);
  assert.ok(f16.reasons.includes("rgba16f-quantization"));
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
