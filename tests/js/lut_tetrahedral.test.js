import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  interpolationOrder,
  sampleLutTetrahedral,
} from "../../src/orga_drone/static/js/studio/lut-tetrahedral.js";

function identityCube(size = 3) {
  const data = [];
  for (let b = 0; b < size; b += 1) {
    for (let g = 0; g < size; g += 1) {
      for (let r = 0; r < size; r += 1) {
        data.push(r / (size - 1), g / (size - 1), b / (size - 1));
      }
    }
  }
  return { size, data };
}

describe("lut-tetrahedral (#360)", () => {
  it("orders fractional axes with R/G/B ties", () => {
    assert.deepEqual(interpolationOrder([0.2, 0.5, 0.1]), [1, 0, 2]);
    assert.deepEqual(interpolationOrder([0.4, 0.4, 0.1]), [0, 1, 2]);
    assert.deepEqual(interpolationOrder([0.3, 0.3, 0.3]), [0, 1, 2]);
  });

  it("samples identity LUT at lattice and off-grid points", () => {
    const lut = identityCube(5);
    for (const rgb of [
      [0, 0, 0],
      [1, 1, 1],
      [0.5, 0.25, 0.75],
      [0.1, 0.2, 0.3],
    ]) {
      const out = sampleLutTetrahedral(lut, rgb);
      assert.ok(Math.abs(out[0] - rgb[0]) < 1e-9);
      assert.ok(Math.abs(out[1] - rgb[1]) < 1e-9);
      assert.ok(Math.abs(out[2] - rgb[2]) < 1e-9);
    }
  });

  it("matches a non-identity corner blend", () => {
    const size = 2;
    // Red-fastest: index = r + g*2 + b*4
    const data = new Array(size * size * size * 3).fill(0);
    // Set far corner (1,1,1) to cyan-ish
    const far = (1 + 1 * 2 + 1 * 4) * 3;
    data[far] = 0.2;
    data[far + 1] = 0.8;
    data[far + 2] = 0.6;
    const out = sampleLutTetrahedral({ size, data }, [0.5, 0.5, 0.5]);
    assert.ok(out[0] > 0 && out[0] < 0.2);
    assert.ok(out[1] > 0 && out[1] < 0.8);
    assert.ok(out[2] > 0 && out[2] < 0.6);
  });
});
