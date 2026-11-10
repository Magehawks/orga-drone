import assert from "node:assert/strict";
import test from "node:test";
import {
  bumpOverlayRevision,
  overlayRevisionOf,
  restoreRemovedOverlay,
  rollbackOverlaysIfCurrent,
  shouldApplyOverlayResponse,
  shouldRollbackOverlayMutation,
} from "../../src/orga_drone/static/js/studio/overlay-persist.js";

test("clip-scoped revisions bump independently", () => {
  const revisions = new Map();
  assert.equal(bumpOverlayRevision(revisions, "1"), 1);
  assert.equal(bumpOverlayRevision(revisions, "1"), 2);
  assert.equal(bumpOverlayRevision(revisions, "2"), 1);
  assert.equal(overlayRevisionOf(revisions, "1"), 2);
  assert.equal(overlayRevisionOf(revisions, "2"), 1);
  assert.equal(overlayRevisionOf(revisions, "missing"), 0);
});

test("stale successful responses must not apply over newer local edits", () => {
  assert.equal(shouldApplyOverlayResponse(2, 2), true);
  assert.equal(shouldApplyOverlayResponse(3, 2), false);
  assert.equal(shouldApplyOverlayResponse(1, 2), false);
});

test("failed-save rollback only when the mutation still owns the clip", () => {
  const previous = [{ id: "a" }, { id: "b" }];
  assert.deepEqual(
    rollbackOverlaysIfCurrent({
      localRevision: 4,
      mutationRevision: 4,
      previous,
    }),
    previous
  );
  assert.equal(
    rollbackOverlaysIfCurrent({
      localRevision: 5,
      mutationRevision: 4,
      previous,
    }),
    null
  );
  assert.equal(shouldRollbackOverlayMutation(5, 4), false);
});

test("failed removal can restore only the removed overlay when newer edits exist", () => {
  const previous = [
    { id: "a", text: "A" },
    { id: "b", text: "B-old" },
  ];
  const current = [{ id: "b", text: "B-new" }];
  assert.deepEqual(restoreRemovedOverlay(current, previous, "a"), [
    { id: "a", text: "A" },
    { id: "b", text: "B-new" },
  ]);
  assert.deepEqual(restoreRemovedOverlay(current, previous, "b"), current);
  assert.deepEqual(restoreRemovedOverlay(current, previous, "missing"), current);
});
