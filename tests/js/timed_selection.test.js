import assert from "node:assert/strict";
import test from "node:test";
import {
  createTimedSelection,
  persistTimedSelectionRemoval,
  resolveDeleteAction,
  shouldIgnoreDeleteShortcut,
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

test("resolveDeleteAction prefers ramp over clip and keeps Backspace off story clips", () => {
  const ramp = createTimedSelection({ kind: "ramp", clipId: "3" });
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
      key: "Delete",
      timedSelection: null,
      hasEffectBarSelection: true,
      privacyMaskActive: true,
    }),
    "effect-bar"
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

test("failed ramp removal keeps selection so Delete/Backspace can retry", async () => {
  const selection = createTimedSelection({ kind: "ramp", clipId: "9" });
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
    timedSelectionMatches(failed.selection, "ramp", "9"),
    true,
    "selection remains after failed save"
  );

  const retried = await persistTimedSelectionRemoval(failed.selection, save);
  assert.equal(retried.ok, true);
  assert.equal(retried.selection, null);
  assert.equal(calls, 2);
});
