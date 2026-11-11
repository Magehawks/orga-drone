import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import {
  SCOPE_FRAME_VERSION,
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
  createScopeFrameV1,
  describeScopeSource,
  isScopeFrameCurrent,
  requireSafeInt,
  scopeFrameIdentity,
  scopeViewKey,
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

function mockPanelDom({ withFixtureToggle = false } = {}) {
  let status = "";
  let disclosure = "";
  const disclosureDataset = {};
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
        putImageData() {},
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
  const enable = withFixtureToggle
    ? Object.assign(new EventEmitter(), {
        checked: false,
        addEventListener(type, handler) {
          this.on(type, handler);
        },
        removeEventListener(type, handler) {
          this.off(type, handler);
        },
      })
    : null;
  const root = {
    dataset: {},
    querySelector(sel) {
      if (sel === "[data-scope-canvas]") return canvas;
      if (sel === "[data-scope-status]") {
        return {
          set textContent(v) {
            status = v;
          },
          get textContent() {
            return status;
          },
        };
      }
      if (sel === "[data-scope-disclosure]") {
        return {
          dataset: disclosureDataset,
          set textContent(v) {
            disclosure = v;
          },
          get textContent() {
            return disclosure;
          },
        };
      }
      if (sel === "[data-scope-dropped]") return { textContent: "" };
      if (sel === "[data-scope-fixture-enable]") return enable;
      return null;
    },
  };
  return {
    root,
    enable,
    get status() {
      return status;
    },
    get disclosure() {
      return disclosure;
    },
    disclosureDataset,
  };
}

test("ScopeFrameV1 is versioned and copies the RGB buffer", () => {
  const source = createScopeFixture("black");
  const input = Float32Array.from(source.rgb);
  input[0] = 0.25;
  const frame = createScopeFrameV1({ ...source, rgb: input });
  assert.equal(frame.version, SCOPE_FRAME_VERSION);
  assert.equal(frame.sourceKind, SCOPE_SOURCE_KINDS.FIXTURE);
  assert.equal(frame.rgb[0], 0.25);
  input[0] = 0.9;
  assert.equal(frame.rgb[0], 0.25, "defensive copy isolates caller mutations");
  assert.ok(Object.isFrozen(frame));
  assert.ok(Object.isFrozen(frame.roi));
});

test("requireSafeInt rejects overflow-prone and non-integer values", () => {
  assert.equal(requireSafeInt(3, "n"), 3);
  // Values that bitwise |0 would wrap must not be silently accepted as dimensions.
  assert.throws(() => requireSafeInt(2 ** 31, "width", { min: 1, max: 16384 }), /out of range/i);
  assert.throws(() => requireSafeInt(Number.MAX_SAFE_INTEGER + 1, "frameIndex"), /safe integer/);
  assert.throws(() => requireSafeInt(1.5, "width"), /safe integer/);
  assert.throws(() => requireSafeInt(NaN, "width"), /safe integer/);
  assert.throws(() => requireSafeInt(-1, "frameIndex"), /out of range/i);
});

test("createScopeFrameV1 rejects invalid dimensions, pts, profile and transfer", () => {
  const base = createScopeFixture("gray");
  assert.throws(
    () => createScopeFrameV1({ ...base, rgb: base.rgb, width: 2 ** 31 }),
    /out of range|safe integer/i
  );
  assert.throws(
    () => createScopeFrameV1({ ...base, rgb: base.rgb, frameIndex: Number.MAX_SAFE_INTEGER + 1 }),
    /safe integer/i
  );
  assert.throws(() => createScopeFrameV1({ ...base, rgb: base.rgb, ptsDen: 0 }), /ptsDen/);
  assert.throws(
    () => createScopeFrameV1({ ...base, rgb: base.rgb, ptsDen: NaN }),
    /ptsDen|safe integer/
  );
  assert.throws(
    () => createScopeFrameV1({ ...base, rgb: base.rgb, profile: "display-p3" }),
    /profile/
  );
  assert.throws(() => createScopeFrameV1({ ...base, rgb: base.rgb, transfer: "pq" }), /transfer/);
  assert.throws(
    () =>
      createScopeFrameV1({
        ...base,
        rgb: base.rgb,
        roi: { x: 0, y: 0, width: base.width + 1, height: 1 },
      }),
    /roi/
  );
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
  assert.notEqual(
    scopeViewKey({ projectId: "p", clipId: "a", gradeRevision: "1", contextDigest: "x" }),
    scopeViewKey({ projectId: "p", clipId: "b", gradeRevision: "1", contextDigest: "x" })
  );
});

test("panel drops stale and older frames; fixture mode never pretends to be live", () => {
  const dom = mockPanelDom();
  const panel = createColorScopesPanel({
    root: dom.root,
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

test("syncView clears live measurement on clip A→B and revision change", () => {
  const dom = mockPanelDom();
  let view = {
    projectId: "proj-1",
    clipId: "clip-a",
    gradeRevision: "1",
    contextDigest: "ctx-a",
  };
  const panel = createColorScopesPanel({
    root: dom.root,
    getView: () => view,
  });

  assert.equal(
    panel.injectFrame(
      liveFrame({
        clipId: "clip-a",
        gradeRevision: "1",
        contextDigest: "ctx-a",
        frameIndex: 1,
      })
    ).accepted,
    true
  );
  assert.equal(panel.getState().hasMeasurements, true);
  assert.equal(dom.disclosureDataset.scopeSource, "engine-tap");

  view = {
    projectId: "proj-1",
    clipId: "clip-b",
    gradeRevision: "1",
    contextDigest: "ctx-b",
  };
  const switched = panel.syncView();
  assert.equal(switched.changed, true);
  assert.equal(switched.cleared, true);
  assert.equal(panel.getState().hasMeasurements, false);
  assert.equal(panel.getState().sourceKind, null);
  assert.equal(dom.disclosureDataset.scopeSource, "unavailable");
  assert.match(dom.status, /No live scope tap yet/i);

  assert.equal(
    panel.injectFrame(
      liveFrame({
        clipId: "clip-b",
        gradeRevision: "1",
        contextDigest: "ctx-b",
        frameIndex: 2,
      })
    ).accepted,
    true
  );
  view = {
    projectId: "proj-1",
    clipId: "clip-b",
    gradeRevision: "2",
    contextDigest: "ctx-b-rev",
  };
  const revised = panel.syncView();
  assert.equal(revised.cleared, true);
  assert.equal(panel.getState().hasMeasurements, false);
  assert.equal(dom.disclosureDataset.scopeSource, "unavailable");
  panel.destroy();
});

test("fixture toggle discloses patterns and clearing fixture removes them", () => {
  const dom = mockPanelDom({ withFixtureToggle: true });
  const panel = createColorScopesPanel({
    root: dom.root,
    getView: () => ({
      projectId: "proj-1",
      clipId: "clip-a",
      gradeRevision: "1",
      contextDigest: "ctx",
    }),
  });

  panel.showFixture("color-bars");
  assert.equal(panel.getState().fixtureMode, true);
  assert.equal(dom.disclosureDataset.scopeSource, "fixture");
  assert.match(dom.disclosure, /Test patterns only|not a measurement/i);
  assert.equal(panel.getState().hasMeasurements, true);

  // Clip switch while fixtures are on keeps the disclosed test pattern.
  const keepFixture = panel.syncView({
    projectId: "proj-1",
    clipId: "clip-b",
    gradeRevision: "1",
    contextDigest: "ctx-b",
  });
  assert.equal(keepFixture.cleared, false);
  assert.equal(dom.disclosureDataset.scopeSource, "fixture");

  dom.enable.checked = false;
  dom.enable.emit("change");
  assert.equal(panel.getState().fixtureMode, false);
  assert.equal(panel.getState().hasMeasurements, false);
  assert.equal(dom.disclosureDataset.scopeSource, "unavailable");
  assert.match(dom.status, /No live scope tap yet/i);
  panel.destroy();
});

test("scope toggles expose no save API surface", async () => {
  const fs = await import("node:fs");
  const source = fs.readFileSync("src/orga_drone/static/js/studio/scopes/panel.js", "utf8");
  assert.equal(source.includes("fetch("), false);
  assert.equal(source.includes("/api/studio"), false);
  assert.equal(source.includes("PATCH"), false);
});
