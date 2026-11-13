import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { sampleLutTetrahedral } from "../../src/orga_drone/static/js/studio/lut-tetrahedral.js";
import {
  expandLutToRgba32f,
  LUT_PRECISION_RGBA16F,
  LUT_PRECISION_RGBA32F,
  LUT_PRECISION_RGBA8,
  measureRgbParity,
  PARITY_PROBES,
  quantizeLutToRgba8,
} from "../../src/orga_drone/static/js/studio/lut-webgl-precision.js";
import { probeManagedGpuCapabilities } from "../../src/orga_drone/static/js/studio/managed-gpu-adapter.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const webglSource = fs.readFileSync(
  path.resolve(here, "../../src/orga_drone/static/js/studio-lut-webgl.js"),
  "utf8"
);

function identityRgb(size) {
  const data = [];
  for (let b = 0; b < size; b += 1) {
    for (let g = 0; g < size; g += 1) {
      for (let r = 0; r < size; r += 1) {
        data.push(r / (size - 1), g / (size - 1), b / (size - 1));
      }
    }
  }
  return { size, data: Float32Array.from(data) };
}

function contrastCube(size) {
  const data = [];
  for (let b = 0; b < size; b += 1) {
    for (let g = 0; g < size; g += 1) {
      for (let r = 0; r < size; r += 1) {
        const x = r / (size - 1);
        const y = g / (size - 1);
        const z = b / (size - 1);
        // High-contrast S-curve style remap (still within 0..1).
        data.push(x * x, Math.sqrt(y), Math.min(1, z * 1.4));
      }
    }
  }
  return { size, data: Float32Array.from(data) };
}

function sampleFromRgba8Table(size, rgba8, rgb) {
  const floatRgb = new Float32Array(size * size * size * 3);
  for (let i = 0; i < size * size * size; i += 1) {
    floatRgb[i * 3] = rgba8[i * 4] / 255;
    floatRgb[i * 3 + 1] = rgba8[i * 4 + 1] / 255;
    floatRgb[i * 3 + 2] = rgba8[i * 4 + 2] / 255;
  }
  return sampleLutTetrahedral({ size, data: floatRgb }, rgb);
}

test("WebGL path keeps float cube data and probes float formats (#360)", () => {
  assert.match(webglSource, /dataF32/);
  assert.match(webglSource, /RGBA32F/);
  assert.match(webglSource, /RGBA16F/);
  assert.match(webglSource, /probeLutPrecision/);
  assert.match(webglSource, /NEAREST/);
});

test("float tetrahedral identity stays within 1e-5 operator gate", () => {
  for (const size of [17, 33]) {
    const lut = identityRgb(size);
    const stats = measureRgbParity(
      PARITY_PROBES,
      (rgb) => rgb,
      (rgb) => sampleLutTetrahedral(lut, rgb)
    );
    assert.ok(stats.maxError <= 1e-5, `size ${size} max=${stats.maxError}`);
    assert.ok(stats.meanError <= 1e-5, `size ${size} mean=${stats.meanError}`);
  }
});

test("RGBA8 quantization error is measured and exceeds float gate on contrast LUTs", () => {
  const lut = contrastCube(33);
  const rgba8 = quantizeLutToRgba8(lut.data, lut.size, false);
  const stats = measureRgbParity(
    PARITY_PROBES,
    (rgb) => sampleLutTetrahedral(lut, rgb),
    (rgb) => sampleFromRgba8Table(lut.size, rgba8, rgb)
  );
  // Documented unavoidable difference: 8-bit table quantization before tet sample.
  assert.ok(stats.maxError > 1e-5, `expected visible rgba8 error, got ${stats.maxError}`);
  // Still far below encoded swatch gate (3.0/255 ≈ 0.012 in float unit for one code).
  assert.ok(stats.maxError < 3.0 / 255 + 1e-3, `max=${stats.maxError}`);
  assert.ok(Number.isFinite(stats.meanError));
});

test("expandLutToRgba32f preserves lattice values", () => {
  const lut = identityRgb(3);
  const rgba = expandLutToRgba32f(lut.data, 3, false);
  assert.equal(rgba.length, 3 * 3 * 3 * 4);
  assert.equal(rgba[0], 0);
  // size 3: lattice r=1 → 1/(3-1)=0.5
  assert.equal(rgba[4], 0.5);
  assert.equal(rgba[rgba.length - 4], 1);
});

test("probe exact:true only when float LUT precision is available", () => {
  const grade = {
    evaluator: "managed-sdr-v1",
    grade: {
      schema_version: 1,
      evaluator: "managed-sdr-v1",
      steps: [{ id: "p1", type: "primaries-v1", enabled: true, selection_id: null }],
      selections: [],
      animation: [],
    },
  };
  const rgba8 = probeManagedGpuCapabilities(grade, {
    lutPrecision: LUT_PRECISION_RGBA8,
  });
  assert.equal(rgba8.exact, false);
  assert.ok(rgba8.reasons.includes("rgba8-quantization"));

  const f32 = probeManagedGpuCapabilities(grade, {
    lutPrecision: LUT_PRECISION_RGBA32F,
  });
  assert.equal(f32.exact, true);
  assert.equal(f32.lutPrecision, LUT_PRECISION_RGBA32F);
  assert.deepEqual(f32.reasons, []);

  const f16 = probeManagedGpuCapabilities(grade, {
    lutPrecision: LUT_PRECISION_RGBA16F,
  });
  assert.equal(f16.exact, true);
});
