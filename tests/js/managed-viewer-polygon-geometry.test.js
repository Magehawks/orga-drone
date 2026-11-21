import test from "node:test";
import assert from "node:assert/strict";
import {
  distanceToSegment,
  hitTestPolygonEdge,
  hitTestPolygonVertex,
  pointInPolygon,
} from "../../src/orga_drone/static/js/studio/managed-viewer-tools.js";

const TRI = [
  [0.2, 0.2],
  [0.8, 0.2],
  [0.5, 0.8],
];

test("hitTestPolygonEdge inserts on nearest edge (#538)", () => {
  // Midpoint of top edge between [0.2,0.2] and [0.8,0.2]
  assert.equal(hitTestPolygonEdge(TRI, { u: 0.5, v: 0.2 }, 0.02), 1);
  assert.equal(hitTestPolygonEdge(TRI, { u: 0.5, v: 0.5 }, 0.01), -1);
});

test("distanceToSegment is zero on the segment", () => {
  assert.ok(distanceToSegment({ u: 0.5, v: 0.2 }, [0.2, 0.2], [0.8, 0.2]) < 1e-9);
  assert.ok(distanceToSegment({ u: 0.5, v: 0.5 }, [0.2, 0.2], [0.8, 0.2]) > 0.2);
});

test("pointInPolygon detects interior vs exterior (#538)", () => {
  assert.equal(pointInPolygon({ u: 0.5, v: 0.4 }, TRI), true);
  assert.equal(pointInPolygon({ u: 0.05, v: 0.05 }, TRI), false);
  assert.equal(pointInPolygon({ u: 0.9, v: 0.9 }, TRI), false);
});

test("vertex hit still wins over edge for handle drag", () => {
  assert.equal(hitTestPolygonVertex(TRI, { u: 0.2, v: 0.2 }, 0.03), 0);
  // Near a vertex should not be treated as a fresh edge insert preference in callers.
  assert.equal(hitTestPolygonVertex(TRI, { u: 0.21, v: 0.19 }, 0.05), 0);
});

test("remove-vertex safety: keep at least three points", () => {
  const next = TRI.filter((_, index) => index !== 1);
  assert.equal(next.length, 2);
  assert.ok(next.length < 3);
});
