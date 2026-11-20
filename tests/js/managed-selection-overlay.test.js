import test from "node:test";
import assert from "node:assert/strict";
import {
  hitTestPolygonVertex,
  paintSelectionInspectionOverlay,
  clearManagedSelectionOverlay,
} from "../../src/orga_drone/static/js/studio/managed-viewer-tools.js";

test("hitTestPolygonVertex finds nearest point within threshold", () => {
  const points = [
    [0.2, 0.2],
    [0.8, 0.2],
    [0.5, 0.8],
  ];
  assert.equal(hitTestPolygonVertex(points, { u: 0.21, v: 0.19 }), 0);
  assert.equal(hitTestPolygonVertex(points, { u: 0.5, v: 0.5 }), -1);
});

test("paintSelectionInspectionOverlay tolerates missing media", () => {
  assert.doesNotThrow(() => {
    paintSelectionInspectionOverlay(null, {
      mask: { leaves: [{ type: "polygon", points: [[0, 0], [1, 0], [1, 1]], closed: true }] },
    });
    clearManagedSelectionOverlay(null);
  });
});
