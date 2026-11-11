import assert from "node:assert/strict";
import test from "node:test";
import {
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
  SCOPE_TAP_REASONS,
  buildScopeFrameFromTaggedRgb,
  createScopeFixture,
  createScopeTapController,
  probeScopeTapCapability,
  refusePreviewCandidate,
} from "../../src/orga_drone/static/js/studio/scopes/index.js";

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

test("buildScopeFrameFromTaggedRgb produces engine-tap frames for fixtures buffers", () => {
  const fixture = createScopeFixture("red");
  const frame = buildScopeFrameFromTaggedRgb({
    width: fixture.width,
    height: fixture.height,
    stride: fixture.stride,
    rgb: fixture.rgb,
    channels: fixture.channels,
    projectId: "p1",
    clipId: "c1",
    gradeRevision: "9",
    contextDigest: "digest",
    frameIndex: 3,
    ptsNum: 1,
    ptsDen: 30,
    sampleFactor: 2,
  });
  assert.equal(frame.sourceKind, SCOPE_SOURCE_KINDS.ENGINE_TAP);
  assert.equal(frame.tapId, SCOPE_TAP_IDS.CLIP_POST_GRADE);
  assert.equal(frame.profile, "bt709");
  assert.equal(frame.transfer, "bt709");
  assert.equal(frame.sampleFactor, 2);
  assert.equal(frame.clipId, "c1");
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
  const fakeLive = buildScopeFrameFromTaggedRgb({
    width: fixture.width,
    height: fixture.height,
    stride: fixture.stride,
    rgb: fixture.rgb,
    channels: fixture.channels,
    projectId: "p",
    clipId: "a",
    gradeRevision: "1",
    contextDigest: "x",
  });

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

test("controller publishes only when capability is available and rate allows", () => {
  const injected = [];
  let available = false;
  let t = 0;
  const panel = {
    injectFrame(frame) {
      injected.push(frame);
      return { accepted: true };
    },
    syncView() {},
  };
  const controller = createScopeTapController({
    panel,
    getView: () => ({
      projectId: "p",
      clipId: "a",
      gradeRevision: "1",
      contextDigest: "x",
    }),
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
  const frame = buildScopeFrameFromTaggedRgb({
    width: fixture.width,
    height: fixture.height,
    stride: fixture.stride,
    rgb: fixture.rgb,
    channels: fixture.channels,
    projectId: "p",
    clipId: "a",
    gradeRevision: "1",
    contextDigest: "x",
    frameIndex: 1,
  });

  assert.equal(controller.tryPublish(frame).accepted, false);
  available = true;
  t = 100;
  assert.equal(controller.tryPublish(frame).accepted, true);
  assert.equal(injected.length, 1);
  t = 120;
  assert.equal(controller.tryPublish(frame).accepted, false);
  assert.equal(controller.tryPublish(frame).reason, "rate-limited");
  t = 160;
  assert.equal(controller.tryPublish(frame).accepted, true);
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
