import test from "node:test";
import assert from "node:assert/strict";
import { polygonLeaf, brushLeaf } from "../../src/orga_drone/static/js/studio/grade-api.js";

test("polygonLeaf builds closed UV polygon", () => {
  const leaf = polygonLeaf({
    points: [
      [0.2, 0.2],
      [0.8, 0.2],
      [0.5, 0.8],
    ],
    feather: 0.04,
    closed: true,
  });
  assert.equal(leaf.type, "polygon");
  assert.equal(leaf.closed, true);
  assert.equal(leaf.feather, 0.04);
  assert.equal(leaf.points.length, 3);
  assert.deepEqual(leaf.points[0], [0.2, 0.2]);
});

test("brushLeaf unchanged for regression", () => {
  const leaf = brushLeaf({ points: [[0.4, 0.5], [0.6, 0.5]], radius: 0.1 });
  assert.equal(leaf.type, "brush");
  assert.equal(leaf.strokes.length, 1);
});
