import test from "node:test";
import assert from "node:assert/strict";
import { pointerToSourceUv } from "../../src/orga_drone/static/js/studio/managed-viewer-tools.js";
import { qualifierFromSample } from "../../src/orga_drone/static/js/studio/grade-api.js";

test("pointerToSourceUv maps into media rect", () => {
  const mediaEl = {
    getBoundingClientRect: () => ({ left: 100, top: 50, width: 200, height: 100 }),
    naturalWidth: 200,
    naturalHeight: 100,
  };
  const uv = pointerToSourceUv({ clientX: 150, clientY: 100 }, mediaEl);
  assert.deepEqual(uv, { u: 0.25, v: 0.5 });
});

test("pointerToSourceUv accounts for contain letterboxing", () => {
  const mediaEl = {
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 200, height: 100 }),
    naturalWidth: 100,
    naturalHeight: 100,
  };
  // Picture is centered 100x100 inside 200x100.
  assert.equal(pointerToSourceUv({ clientX: 10, clientY: 50 }, mediaEl), null);
  const uv = pointerToSourceUv({ clientX: 100, clientY: 50 }, mediaEl);
  assert.ok(uv);
  assert.ok(Math.abs(uv.u - 0.5) < 1e-6);
  assert.ok(Math.abs(uv.v - 0.5) < 1e-6);
});

test("pointerToSourceUv rejects outside clicks", () => {
  const mediaEl = {
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 }),
  };
  assert.equal(pointerToSourceUv({ clientX: -1, clientY: 10 }, mediaEl), null);
});

test("qualifierFromSample reads suggested ranges", () => {
  const sample = {
    suggested: {
      rgb: {
        type: "rgb",
        channels: [
          [0.5, 0.1],
          [0.5, 0.1],
          [0.5, 0.1],
        ],
      },
    },
  };
  const q = qualifierFromSample(sample, "rgb");
  assert.equal(q.type, "rgb");
  assert.equal(q.channels.length, 3);
});
