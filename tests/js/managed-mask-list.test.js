import test from "node:test";
import assert from "node:assert/strict";
import {
  clearManagedSelectionOverlay,
  paintSelectionInspectionOverlay,
  paintSelectionRasterOverlay,
} from "../../src/orga_drone/static/js/studio/managed-viewer-tools.js";

function displayName(selection, messages = {}) {
  const named = typeof selection?.name === "string" ? selection.name.trim() : "";
  if (named) return named;
  return (messages.untitledMask || "Mask {id}").replace("{id}", String(selection?.id || ""));
}

function overlayVisible(selection) {
  if (selection?.overlay && typeof selection.overlay.visible === "boolean") {
    return selection.overlay.visible;
  }
  return true;
}

test("displayName prefers human name over id", () => {
  assert.equal(displayName({ id: "s1", name: "Blatt" }), "Blatt");
  assert.equal(displayName({ id: "s1", name: "  " }), "Mask s1");
  assert.equal(displayName({ id: "abc" }), "Mask abc");
});

test("overlayVisible defaults true and respects explicit false", () => {
  assert.equal(overlayVisible({}), true);
  assert.equal(overlayVisible({ overlay: { visible: false } }), false);
  assert.equal(overlayVisible({ overlay: { visible: true } }), true);
});

test("inspection overlay helpers tolerate null media", () => {
  const selection = {
    invert: true,
    mask: {
      leaves: [
        {
          type: "polygon",
          points: [
            [0.1, 0.1],
            [0.9, 0.1],
            [0.5, 0.9],
          ],
          closed: true,
        },
      ],
    },
  };
  assert.doesNotThrow(() => {
    paintSelectionInspectionOverlay(null, selection, { invertedHint: true });
    paintSelectionRasterOverlay(null, null, selection);
    clearManagedSelectionOverlay(null);
  });
});
