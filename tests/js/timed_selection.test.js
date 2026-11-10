import assert from "node:assert/strict";
import test from "node:test";
import {
  createTimedSelection,
  isActiveTimedSelection,
  isEffectBarKind,
  isOverlayTimedKind,
  persistTimedSelectionRemoval,
  resolveDeleteAction,
  shouldIgnoreDeleteShortcut,
  timedEffectInspectorTab,
  timedSelectionMatches,
} from "../../src/orga_drone/static/js/studio/timed-selection.js";

test("createTimedSelection keeps ramp identity and rejects unknown kinds", () => {
  assert.deepEqual(createTimedSelection({ kind: "ramp", clipId: 12, id: "" }), {
    kind: "ramp",
    clipId: "12",
    id: "",
  });
  assert.equal(createTimedSelection({ kind: "lut", clipId: "1" }), null);
  assert.equal(createTimedSelection({ kind: "ramp", clipId: "" }), null);
});

test("timedSelectionMatches compares kind, clip and id", () => {
  const selection = createTimedSelection({ kind: "ramp", clipId: "7" });
  assert.equal(timedSelectionMatches(selection, "ramp", "7"), true);
  assert.equal(timedSelectionMatches(selection, "ramp", 7), true);
  assert.equal(timedSelectionMatches(selection, "zoom", "7"), false);
  assert.equal(timedSelectionMatches(null, "ramp", "7"), false);
  const mask = createTimedSelection({ kind: "mask", clipId: "3", id: "blur-1" });
  assert.equal(timedSelectionMatches(mask, "mask", "3", "blur-1"), true);
  assert.equal(timedSelectionMatches(mask, "mask", "3", "other"), false);
});

test("effect bar kinds map to existing inspector tabs", () => {
  assert.equal(isEffectBarKind("zoom"), true);
  assert.equal(isEffectBarKind("mask"), true);
  assert.equal(isEffectBarKind("slow"), true);
  assert.equal(isEffectBarKind("color"), true);
  assert.equal(isEffectBarKind("ramp"), false);
  assert.equal(isEffectBarKind("overlay"), false);
  assert.equal(isOverlayTimedKind("overlay"), true);
  assert.equal(isOverlayTimedKind("zoom"), false);
  assert.equal(timedEffectInspectorTab("zoom"), "image");
  assert.equal(timedEffectInspectorTab("mask"), "effects");
  assert.equal(timedEffectInspectorTab("color"), "effects");
  assert.equal(timedEffectInspectorTab("slow"), "clip");
  assert.equal(timedEffectInspectorTab("ramp"), "clip");
  assert.equal(timedEffectInspectorTab("overlay"), "overlays");
});

test("shouldIgnoreDeleteShortcut protects typing and dialogs", () => {
  assert.equal(shouldIgnoreDeleteShortcut({ tagName: "INPUT", type: "text" }), true);
  assert.equal(shouldIgnoreDeleteShortcut({ tagName: "INPUT", type: "range" }), false);
  assert.equal(shouldIgnoreDeleteShortcut({ tagName: "TEXTAREA" }), true);
  assert.equal(shouldIgnoreDeleteShortcut({ tagName: "DIV", isContentEditable: true }), true);
  assert.equal(shouldIgnoreDeleteShortcut({ tagName: "BUTTON" }, { dialogOpen: true }), true);
  assert.equal(shouldIgnoreDeleteShortcut({ tagName: "BUTTON" }, { reuseDraft: true }), true);
  assert.equal(shouldIgnoreDeleteShortcut({ tagName: "DIV" }), false);
});

test("resolveDeleteAction prefers timed effects over clip and allows Backspace", () => {
  const ramp = createTimedSelection({ kind: "ramp", clipId: "3" });
  const zoom = createTimedSelection({ kind: "zoom", clipId: "4" });
  const mask = createTimedSelection({ kind: "mask", clipId: "5", id: "m1" });
  assert.equal(
    resolveDeleteAction({
      key: "Delete",
      timedSelection: ramp,
      hasSelectedStoryClip: true,
      storyClipFocused: true,
    }),
    "ramp"
  );
  assert.equal(
    resolveDeleteAction({
      key: "Backspace",
      timedSelection: ramp,
      hasSelectedStoryClip: true,
      storyClipFocused: true,
    }),
    "ramp"
  );
  assert.equal(
    resolveDeleteAction({
      key: "Delete",
      timedSelection: zoom,
      hasSelectedStoryClip: true,
      storyClipFocused: true,
    }),
    "effect-bar"
  );
  assert.equal(
    resolveDeleteAction({
      key: "Backspace",
      timedSelection: mask,
      hasSelectedStoryClip: true,
      storyClipFocused: true,
    }),
    "effect-bar"
  );
  const overlay = createTimedSelection({ kind: "overlay", clipId: "8", id: "ovtext001" });
  assert.equal(
    resolveDeleteAction({
      key: "Delete",
      timedSelection: overlay,
      hasSelectedStoryClip: true,
      storyClipFocused: true,
    }),
    "overlay"
  );
  assert.equal(
    resolveDeleteAction({
      key: "Backspace",
      timedSelection: overlay,
      hasSelectedStoryClip: true,
      storyClipFocused: true,
    }),
    "overlay"
  );
  // Legacy selectedEffectBar alone must not delete after an ordinary clip switch.
  assert.equal(
    resolveDeleteAction({
      key: "Backspace",
      timedSelection: null,
      hasEffectBarSelection: true,
    }),
    null
  );
  assert.equal(
    resolveDeleteAction({
      key: "Delete",
      timedSelection: null,
      hasEffectBarSelection: true,
      hasSelectedStoryClip: true,
      storyClipFocused: true,
    }),
    "story-clip"
  );
  assert.equal(
    resolveDeleteAction({
      key: "Backspace",
      timedSelection: null,
      hasSelectedStoryClip: true,
      storyClipFocused: true,
    }),
    null
  );
  assert.equal(
    resolveDeleteAction({
      key: "Delete",
      timedSelection: null,
      hasSelectedStoryClip: true,
      storyClipFocused: true,
    }),
    "story-clip"
  );
  assert.equal(
    resolveDeleteAction({
      key: "Backspace",
      timedSelection: null,
      privacyMaskActive: true,
    }),
    "mask"
  );
});

test("isActiveTimedSelection blocks async handlers from overwriting a newer choice", () => {
  const pending = createTimedSelection({ kind: "zoom", clipId: "1" });
  const newer = createTimedSelection({ kind: "slow", clipId: "2" });
  assert.equal(isActiveTimedSelection(pending, pending), true);
  assert.equal(isActiveTimedSelection(null, pending), false);
  assert.equal(isActiveTimedSelection(newer, pending), false);
});

test("failed effect removal keeps selection so Delete/Backspace can retry", async () => {
  const selection = createTimedSelection({ kind: "zoom", clipId: "9" });
  let calls = 0;
  const save = async () => {
    calls += 1;
    if (calls === 1) throw new Error("patch failed");
  };

  const failed = await persistTimedSelectionRemoval(selection, save);
  assert.equal(failed.ok, false);
  assert.equal(failed.selection, selection);
  assert.equal(String(failed.error?.message || ""), "patch failed");
  assert.equal(
    timedSelectionMatches(failed.selection, "zoom", "9"),
    true,
    "selection remains after failed save"
  );

  const retried = await persistTimedSelectionRemoval(failed.selection, save);
  assert.equal(retried.ok, true);
  assert.equal(retried.selection, null);
  assert.equal(calls, 2);
});
