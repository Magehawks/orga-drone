import test from "node:test";
import assert from "node:assert/strict";
import {
  mediaContentClientRect,
  overlayLayoutForMedia,
  pointerToSourceUv,
  sourceUvToClient,
} from "../../src/orga_drone/static/js/studio/managed-viewer-tools.js";
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

test("mediaContentClientRect exposes nonzero letterbox offsets (#561)", () => {
  const mediaEl = {
    getBoundingClientRect: () => ({ left: 40, top: 10, width: 400, height: 200 }),
    naturalWidth: 100,
    naturalHeight: 200,
  };
  // Portrait 1:2 in a 2:1 frame → content 100x200 centered horizontally.
  const content = mediaContentClientRect(mediaEl);
  assert.ok(content);
  assert.ok(Math.abs(content.width - 100) < 1e-6);
  assert.ok(Math.abs(content.height - 200) < 1e-6);
  assert.ok(Math.abs(content.left - 190) < 1e-6); // 40 + (400-100)/2
  assert.ok(Math.abs(content.top - 10) < 1e-6);
});

test("pointer and overlay share letterbox UV round-trip (#561)", () => {
  const mediaEl = {
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 300, height: 200 }),
    naturalWidth: 100,
    naturalHeight: 200,
  };
  // Content is 100x200 centered: left=100.
  const samples = [
    { clientX: 100, clientY: 0 }, // top-left of picture
    { clientX: 150, clientY: 100 }, // center
    { clientX: 199.9, clientY: 199.9 }, // near bottom-right
  ];
  for (const sample of samples) {
    const uv = pointerToSourceUv(sample, mediaEl);
    assert.ok(uv, `expected UV for ${JSON.stringify(sample)}`);
    const back = sourceUvToClient(uv, mediaEl);
    assert.ok(back);
    assert.ok(Math.abs(back.clientX - sample.clientX) < 0.05);
    assert.ok(Math.abs(back.clientY - sample.clientY) < 0.05);
  }
  // Full-box UV mapping would wrongly place u=0.5 at clientX=150 of the
  // element; content mapping places picture-center at clientX=150 still, but
  // picture-left (u=0) at 100 — not at element left 0.
  const leftEdge = sourceUvToClient({ u: 0, v: 0.5 }, mediaEl);
  assert.ok(Math.abs(leftEdge.clientX - 100) < 1e-6);
  assert.equal(pointerToSourceUv({ clientX: 10, clientY: 100 }, mediaEl), null);
});

test("pointerToSourceUv rejects outside clicks", () => {
  const mediaEl = {
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 }),
  };
  assert.equal(pointerToSourceUv({ clientX: -1, clientY: 10 }, mediaEl), null);
});

test("overlay layout matches letterboxed content, not full media box (#561)", () => {
  const mediaEl = {
    getBoundingClientRect: () => ({ left: 20, top: 40, width: 400, height: 200 }),
    naturalWidth: 1125,
    naturalHeight: 1984,
  };
  const hostEl = {
    getBoundingClientRect: () => ({ left: 10, top: 30, width: 420, height: 220 }),
  };
  const content = mediaContentClientRect(mediaEl);
  const layout = overlayLayoutForMedia(mediaEl, hostEl);
  assert.ok(content && layout);
  // Must be narrower than the media element (side letterboxes).
  assert.ok(layout.width < 400);
  assert.ok(Math.abs(layout.width - Math.round(content.width)) < 1);
  assert.ok(Math.abs(layout.height - Math.round(content.height)) < 1);
  assert.equal(layout.left, Math.round(content.left - 10));
  assert.equal(layout.top, Math.round(content.top - 30));
  // Regression: old code used full media box → left ≈ 10, width 400.
  assert.notEqual(layout.width, 400);
  assert.ok(layout.left > 10);
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
