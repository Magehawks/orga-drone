import test from "node:test";
import assert from "node:assert/strict";
import { hitTestPolygonVertex } from "../../src/orga_drone/static/js/studio/managed-viewer-tools.js";

test("hitTestPolygonVertex finds nearest handle within threshold", () => {
  const points = [
    [0.2, 0.2],
    [0.8, 0.2],
    [0.5, 0.8],
  ];
  assert.equal(hitTestPolygonVertex(points, { u: 0.21, v: 0.19 }, 0.05), 0);
  assert.equal(hitTestPolygonVertex(points, { u: 0.79, v: 0.21 }, 0.05), 1);
  assert.equal(hitTestPolygonVertex(points, { u: 0.5, v: 0.5 }, 0.05), -1);
});
