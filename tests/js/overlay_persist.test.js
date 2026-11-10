import assert from "node:assert/strict";
import test from "node:test";
import {
  bumpOverlayRevision,
  overlayRevisionOf,
  recoverFailedOverlayRemoval,
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

test("failed removal restores A even when selection moved to edited B", () => {
  const previous = [
    { id: "a", text: "A" },
    { id: "b", text: "B-old" },
  ];
  const current = [{ id: "b", text: "B-new" }];
  const recovery = recoverFailedOverlayRemoval({
    localRevision: 5,
    mutationRevision: 4,
    previous,
    current,
    overlayId: "a",
  });
  assert.equal(recovery.mode, "partial");
  assert.deepEqual(recovery.overlays, [
    { id: "a", text: "A" },
    { id: "b", text: "B-new" },
  ]);
});

test("failed removal skips restore when a newer removal superseded it", () => {
  const previous = [
    { id: "a", text: "A" },
    { id: "b", text: "B" },
  ];
  const current = [{ id: "b", text: "B" }];
  const recovery = recoverFailedOverlayRemoval({
    localRevision: 8,
    mutationRevision: 4,
    previous,
    current,
    overlayId: "a",
    newerRemovalRevision: 7,
  });
  assert.equal(recovery.mode, "superseded");
  assert.equal(recovery.overlays, null);
});

test("failed removal full rollback when mutation still owns the clip", () => {
  const previous = [
    { id: "a", text: "A" },
    { id: "b", text: "B" },
  ];
  const recovery = recoverFailedOverlayRemoval({
    localRevision: 3,
    mutationRevision: 3,
    previous,
    current: [{ id: "b", text: "B" }],
    overlayId: "a",
  });
  assert.equal(recovery.mode, "full");
  assert.deepEqual(recovery.overlays, previous);
});
