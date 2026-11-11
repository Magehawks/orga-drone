import assert from "node:assert/strict";
import test from "node:test";
import {
  SCOPE_CAPTURE_PLANES,
  SCOPE_CAPTURE_STAGES,
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
  SCOPE_TAP_REASONS,
  buildScopeFrameFromTaggedRgb,
  createScopeFixture,
  createScopeTapController,
  probeScopeTapCapability,
  refusePreviewCandidate,
} from "../../src/orga_drone/static/js/studio/scopes/index.js";

function taggedDescriptor(fixture, overrides = {}) {
  return {
    width: fixture.width,
    height: fixture.height,
    stride: fixture.stride,
    rgb: fixture.rgb,
    channels: fixture.channels,
    profile: "bt709",
    transfer: "bt709",
    captureStage: SCOPE_CAPTURE_STAGES.CLIP_POST_GRADE_PRE_FRAME,
    capturePlane: SCOPE_CAPTURE_PLANES.BT709_ENCODED_RGBA,
    tapId: SCOPE_TAP_IDS.CLIP_POST_GRADE,
    straightAlpha: true,
    legalRange: false,
    ptsNum: 1,
    ptsDen: 30,
    frameIndex: 3,
    projectId: "p1",
    clipId: "c1",
    gradeRevision: "9",
    contextDigest: "digest",
    roi: { x: 0, y: 0, width: fixture.width, height: fixture.height },
    sampleFactor: 2,
    ...overrides,
  };
}

test("probe refuses current preview candidates and stays unavailable", () => {
  const capability = probeScopeTapCapability({
    renderAdapterReady: false,
    candidates: [
      { id: "blit", kind: "display-blit", hasFraming: true },
      { id: "css", kind: "css-filter" },
      { id: "still", kind: "jpeg-still" },
      { id: "webgl", kind: "webgl-lut", profileTagged: false, transferTagged: false },
    ],
  });
  assert.equal(capability.available, false);
  assert.equal(capability.reason, SCOPE_TAP_REASONS.AWAITING_RENDER_ADAPTER);
  assert.ok(capability.notes.some((n) => n.includes("display-blit")));
  assert.ok(capability.notes.some((n) => n.includes("css-filter")));
});

test("renderAdapterReady alone never makes capability available", () => {
  const capability = probeScopeTapCapability({
    renderAdapterReady: true,
    candidates: [],
  });
  assert.equal(capability.available, false);
  assert.equal(capability.reason, SCOPE_TAP_REASONS.AWAITING_RENDER_ADAPTER);
  assert.ok(capability.notes.some((n) => n.includes("flag-alone-never-qualifies")));
});

test("refusePreviewCandidate covers framing, CSS, JPEG and untagged GPU paths", () => {
  assert.equal(
    refusePreviewCandidate({ kind: "display-blit" }),
    SCOPE_TAP_REASONS.DISPLAY_BLIT_FRAMING
  );
  assert.equal(
    refusePreviewCandidate({ kind: "css-filter" }),
    SCOPE_TAP_REASONS.CSS_FILTER_APPROXIMATION
  );
  assert.equal(
    refusePreviewCandidate({ kind: "jpeg-still" }),
    SCOPE_TAP_REASONS.JPEG_STILL_NOT_CONTINUOUS
  );
  assert.equal(
    refusePreviewCandidate({
      kind: "playback-proxy",
      profileTagged: true,
      transferTagged: true,
      playing: true,
      gradedProxyReady: false,
    }),
    SCOPE_TAP_REASONS.PLAYBACK_WITHOUT_GRADED_PROXY
  );
});

test("fully tagged buffer builds an engine-tap ScopeFrameV1", () => {
  const fixture = createScopeFixture("red");
  const frame = buildScopeFrameFromTaggedRgb(taggedDescriptor(fixture));
  assert.equal(frame.sourceKind, SCOPE_SOURCE_KINDS.ENGINE_TAP);
  assert.equal(frame.tapId, SCOPE_TAP_IDS.CLIP_POST_GRADE);
  assert.equal(frame.profile, "bt709");
  assert.equal(frame.transfer, "bt709");
  assert.equal(frame.sampleFactor, 2);
  assert.equal(frame.clipId, "c1");
  assert.equal(frame.frameIndex, 3);
  assert.equal(frame.ptsDen, 30);
  assert.equal(frame.straightAlpha, true);
});

test("missing or mislabeled provenance is rejected before engine-tap creation", () => {
  const fixture = createScopeFixture("gray");
  const base = taggedDescriptor(fixture);

  for (const key of [
    "profile",
    "transfer",
    "captureStage",
    "capturePlane",
    "tapId",
    "straightAlpha",
    "ptsNum",
    "ptsDen",
    "frameIndex",
    "projectId",
    "clipId",
    "gradeRevision",
    "contextDigest",
    "roi",
    "sampleFactor",
    "channels",
  ]) {
    const broken = { ...base };
    delete broken[key];
    assert.throws(() => buildScopeFrameFromTaggedRgb(broken), /missing-scope-frame-provenance/);
  }

  assert.throws(
    () => buildScopeFrameFromTaggedRgb(taggedDescriptor(fixture, { profile: "display-p3" })),
    /invalid-scope-frame-provenance:profile/
  );
  assert.throws(
    () => buildScopeFrameFromTaggedRgb(taggedDescriptor(fixture, { transfer: "pq" })),
    /invalid-scope-frame-provenance:transfer/
  );
  assert.throws(
    () =>
      buildScopeFrameFromTaggedRgb(
        taggedDescriptor(fixture, {
          captureStage: SCOPE_CAPTURE_STAGES.CLIP_POST_GRADE_PRE_FRAME,
          tapId: SCOPE_TAP_IDS.PROJECT_COMPOSITE,
        })
      ),
    /captureStage\/tapId-mismatch/
  );
  assert.throws(
    () => buildScopeFrameFromTaggedRgb(taggedDescriptor(fixture, { straightAlpha: "yes" })),
    /straightAlpha/
  );
  assert.throws(
    () => buildScopeFrameFromTaggedRgb({ rgb: fixture.rgb }),
    /missing-scope-frame-provenance/
  );
});

test("controller never publishes while capability is unavailable", () => {
  const injected = [];
  const synced = [];
  const panel = {
    injectFrame(frame) {
      injected.push(frame);
      return { accepted: true };
    },
    syncView(view) {
      synced.push(view);
    },
  };
  let view = { projectId: "p", clipId: "a", gradeRevision: "1", contextDigest: "x" };
  const controller = createScopeTapController({
    panel,
    getView: () => view,
    getCapability: () =>
      probeScopeTapCapability({
        candidates: [{ id: "blit", kind: "display-blit", hasFraming: true }],
      }),
    minIntervalMs: 0,
  });

  const fixture = createScopeFixture("gray");
  const fakeLive = buildScopeFrameFromTaggedRgb(
    taggedDescriptor(fixture, {
      projectId: "p",
      clipId: "a",
      gradeRevision: "1",
      contextDigest: "x",
      sampleFactor: 1,
      frameIndex: 1,
      ptsNum: 0,
      ptsDen: 1,
    })
  );

  const denied = controller.tryPublish(fakeLive);
  assert.equal(denied.accepted, false);
  assert.equal(denied.reason, SCOPE_TAP_REASONS.AWAITING_RENDER_ADAPTER);
  assert.equal(injected.length, 0);

  view = { projectId: "p", clipId: "b", gradeRevision: "1", contextDigest: "y" };
  controller.sync();
  assert.equal(synced.at(-1).clipId, "b");

  const status = controller.getStatus();
  assert.equal(status.capability.available, false);
  assert.ok(status.dropped >= 1);
  controller.destroy();
});

test("first eligible frame is not rate-limited; view change resets throttle and rejects stale", () => {
  const injected = [];
  let available = true;
  let t = 0;
  let view = { projectId: "p", clipId: "a", gradeRevision: "1", contextDigest: "x" };
  const panel = {
    injectFrame(frame) {
      injected.push(frame);
      return { accepted: true };
    },
    syncView() {},
  };
  const controller = createScopeTapController({
    panel,
    getView: () => view,
    getCapability: () => ({
      available,
      reason: available ? "" : SCOPE_TAP_REASONS.AWAITING_RENDER_ADAPTER,
      tapId: SCOPE_TAP_IDS.CLIP_POST_GRADE,
      notes: [],
    }),
    now: () => t,
    minIntervalMs: 50,
  });
  const fixture = createScopeFixture("blue");
  const frameA = buildScopeFrameFromTaggedRgb(
    taggedDescriptor(fixture, {
      projectId: "p",
      clipId: "a",
      gradeRevision: "1",
      contextDigest: "x",
      frameIndex: 1,
      ptsNum: 0,
      ptsDen: 1,
      sampleFactor: 1,
    })
  );

  // Fake clock at 0 must still accept the first frame (sentinel, not lastPublishMs=0).
  t = 0;
  assert.equal(controller.tryPublish(frameA).accepted, true);
  assert.equal(injected.length, 1);

  t = 20;
  assert.equal(controller.tryPublish(frameA).accepted, false);
  assert.equal(controller.tryPublish(frameA).reason, "rate-limited");

  // Clip/seek/revision change clears throttle and rejects the previous clip frame.
  view = { projectId: "p", clipId: "b", gradeRevision: "1", contextDigest: "y" };
  controller.sync();
  t = 25;
  assert.equal(controller.tryPublish(frameA).accepted, false);
  assert.equal(controller.tryPublish(frameA).reason, SCOPE_TAP_REASONS.STALE_VIEW);

  const frameB = buildScopeFrameFromTaggedRgb(
    taggedDescriptor(fixture, {
      projectId: "p",
      clipId: "b",
      gradeRevision: "1",
      contextDigest: "y",
      frameIndex: 2,
      ptsNum: 1,
      ptsDen: 30,
      sampleFactor: 1,
    })
  );
  assert.equal(controller.tryPublish(frameB).accepted, true);
  assert.equal(injected.length, 2);

  // Revision change: old revision is stale even if clip id matches.
  view = { projectId: "p", clipId: "b", gradeRevision: "2", contextDigest: "y2" };
  controller.sync();
  assert.equal(controller.tryPublish(frameB).reason, SCOPE_TAP_REASONS.STALE_VIEW);
  controller.destroy();
});

test("studio entry wires probe and refuses blit as live source", async () => {
  const fs = await import("node:fs");
  const entry = fs.readFileSync("src/orga_drone/static/js/studio.js", "utf8");
  assert.match(entry, /createScopeTapController/);
  assert.match(entry, /probeScopeTapCapability/);
  assert.match(entry, /display-blit/);
  assert.match(entry, /awaiting-render-adapter|renderAdapterReady:\s*false/);
  assert.equal(entry.includes("getImageData("), false);
});
