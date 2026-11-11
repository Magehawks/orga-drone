import assert from "node:assert/strict";
import test from "node:test";
import {
  SCOPE_FRAME_VERSION,
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
  createScopeFrameV1,
  describeScopeSource,
  isScopeFrameCurrent,
  scopeFrameIdentity,
} from "../../src/orga_drone/static/js/studio/scopes/scope-frame.js";
import { createScopeFixture } from "../../src/orga_drone/static/js/studio/scopes/fixtures.js";
import { createColorScopesPanel } from "../../src/orga_drone/static/js/studio/scopes/panel.js";

function liveFrame(overrides = {}) {
  const base = createScopeFixture("gray");
  return createScopeFrameV1({
    ...base,
    rgb: base.rgb,
    sourceKind: SCOPE_SOURCE_KINDS.ENGINE_TAP,
    tapId: SCOPE_TAP_IDS.CLIP_POST_GRADE,
    projectId: "proj-1",
    clipId: "clip-9",
    gradeRevision: "3",
    contextDigest: "digest-a",
    fixtureId: "",
    ...overrides,
  });
}

test("ScopeFrameV1 is versioned and copies the RGB buffer", () => {
  const frame = createScopeFixture("black");
  assert.equal(frame.version, SCOPE_FRAME_VERSION);
  assert.equal(frame.sourceKind, SCOPE_SOURCE_KINDS.FIXTURE);
  frame.rgb[0] = 1;
  // Mutating the returned copy does not throw; immutability is structural freeze.
  assert.ok(Object.isFrozen(frame));
});

test("stale frames for another clip or revision are rejected", () => {
  const frame = liveFrame();
  assert.equal(
    isScopeFrameCurrent(frame, {
      projectId: "proj-1",
      clipId: "clip-9",
      gradeRevision: "3",
      contextDigest: "digest-a",
    }),
    true
  );
  assert.equal(
    isScopeFrameCurrent(frame, {
      projectId: "proj-1",
      clipId: "other",
      gradeRevision: "3",
      contextDigest: "digest-a",
    }),
    false
  );
  assert.equal(
    isScopeFrameCurrent(frame, {
      projectId: "proj-1",
      clipId: "clip-9",
      gradeRevision: "4",
      contextDigest: "digest-a",
    }),
    false
  );
});

test("panel drops stale and older frames; fixture mode never pretends to be live", () => {
  const paints = [];
  const canvas = {
    width: 64,
    height: 36,
    getContext() {
      return {
        fillStyle: "",
        fillRect() {},
        createImageData(w, h) {
          return { data: new Uint8ClampedArray(w * h * 4), width: w, height: h };
        },
        putImageData() {
          paints.push("density");
        },
        strokeStyle: "",
        beginPath() {},
        moveTo() {},
        lineTo() {},
        stroke() {},
        fillText() {},
        font: "",
      };
    },
  };
  const root = {
    dataset: {},
    querySelector(sel) {
      if (sel === "[data-scope-canvas]") return canvas;
      if (sel === "[data-scope-status]") return { textContent: "" };
      if (sel === "[data-scope-disclosure]") return { textContent: "", dataset: {} };
      if (sel === "[data-scope-dropped]") return { textContent: "" };
      if (sel === "[data-scope-kinds]") return null;
      if (sel === "[data-scope-fixture]") return null;
      if (sel === "[data-scope-fixture-enable]") return null;
      return null;
    },
  };
  const panel = createColorScopesPanel({
    root,
    getView: () => ({
      projectId: "proj-1",
      clipId: "clip-9",
      gradeRevision: "3",
      contextDigest: "digest-a",
    }),
  });

  const first = liveFrame({ frameIndex: 2 });
  assert.equal(panel.injectFrame(first).accepted, true);
  const older = liveFrame({ frameIndex: 1 });
  assert.equal(panel.injectFrame(older).accepted, false);
  assert.equal(panel.injectFrame(older).reason, "stale-frame");
  const wrongClip = liveFrame({ clipId: "clip-1", frameIndex: 5 });
  assert.equal(panel.injectFrame(wrongClip).accepted, false);

  panel.showFixture("red");
  assert.equal(panel.getState().fixtureMode, true);
  assert.equal(panel.getState().sourceKind, SCOPE_SOURCE_KINDS.FIXTURE);
  assert.match(describeScopeSource(createScopeFixture("red")), /not a media measurement/i);
  assert.ok(panel.getMetrics().droppedFrames >= 2);
  assert.ok(scopeFrameIdentity(first).includes("clip-9"));
  panel.destroy();
});

test("scope toggles expose no save API surface", async () => {
  const fs = await import("node:fs");
  const source = fs.readFileSync("src/orga_drone/static/js/studio/scopes/panel.js", "utf8");
  assert.equal(source.includes("fetch("), false);
  assert.equal(source.includes("/api/studio"), false);
  assert.equal(source.includes("PATCH"), false);
});
