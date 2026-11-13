// Regression coverage for the canonical Story clock sampled by the preview paint
// loop. The legacy monolith is loaded as text so this test does not need a DOM.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(
  path.resolve(here, "../../src/orga_drone/static/js/studio.js"),
  "utf8"
);

function functionBody(name) {
  const start = source.indexOf(`  function ${name}(`);
  if (start < 0) return null;
  return source.slice(start, source.indexOf("\n  }", start) + 4);
}

function scenario(options = {}) {
  const clip = { dataset: { studioId: "1", kind: "video" } };
  const state = { playing: true, activeStudioId: "1", projectTimeS: 0 };
  const video = {
    currentTime: 3.5,
    paused: false,
    hidden: false,
    seeking: false,
    readyState: 4,
    ended: false,
    currentSrc: "source",
    getAttribute: () => "source",
    ...options.video,
  };
  const queue = [];
  const painted = [];
  const transitionCalls = [];
  const context = vm.createContext({
    state,
    colorComparison: null,
    previewVideo: video,
    previewVideoB: null,
    previewBlitRaf: 0,
    reuseDraft: options.reuseDraft || null,
    suppressVideoClock: !!options.suppressed,
    wallClockRaf: options.wallClock ? 5 : 0,
    videoLoopIndex: 0,
    loopSeeking: false,
    loadedVideoSrc: "source",
    clips: () => [clip],
    sourceInS: () => 1.5,
    sourceOutS: () => 100,
    playbackSpeed: () => 2,
    sectionRepeats: () => 1,
    sectionCycleS: () => 20,
    lutProxyActiveFor: () => !!options.proxy,
    applyClipPlayback() {},
    slowBarOf: () => null,
    speedRampOf: () => null,
    clipForPreviewMedia: () => null,
    loopOverlapS: () => 0,
    forwardLoopOverlapS: () => 0,
    forwardLoopSpans: () => [],
    clipStartTime: () => 4,
    clipDuration: () => 20,
    updatePlayheadChrome() {},
    resolveAt: () => ({ clip }),
    applyTransitionPreview: () => transitionCalls.push(state.projectTimeS),
    updateCutEnabled() {},
    syncMusicAudio() {},
    syncPreviewMedia() {},
    beginClockForActiveClip() {},
    advanceToNextOrStop() {},
    pausePlayback() {},
    sourceToStory: (_, t) => t,
    paintPreviewBlit: () => painted.push(state.projectTimeS),
    refreshColorScopesTap() {},
    requestAnimationFrame: (callback) => {
      queue.push(callback);
      return queue.length;
    },
  });
  const names = [
    "clipOffsetFromMediaTime",
    "videoStoryPosition",
    "syncStoryClockFromVideo",
    "onVideoTimeUpdate",
    "schedulePreviewBlit",
  ];
  const bodies = names.map(functionBody).filter(Boolean);
  vm.runInContext(bodies.join("\n"), context);
  if (options.nativeTimeUpdate) context.onVideoTimeUpdate();
  else context.schedulePreviewBlit();
  if (queue.length) queue.shift()(1000);
  return { state, painted, transitionCalls };
}

test("preview paint samples the canonical source-in and speed mapping", () => {
  const result = scenario();
  assert.equal(result.painted[0], 5);
  assert.equal(result.transitionCalls.length, 0);
});

test("preview paint keeps the clip-local LUT proxy mapping", () => {
  assert.equal(scenario({ proxy: true }).painted[0], 5.75);
});

test("native timeupdate still runs transition and music sync", () => {
  const result = scenario({ nativeTimeUpdate: true });
  assert.equal(result.state.projectTimeS, 5);
  assert.equal(result.transitionCalls.length, 1);
});

test("excluded clocks never advance Story time during paint", () => {
  const excluded = [
    { video: { paused: true } },
    { video: { seeking: true } },
    { video: { hidden: true } },
    { video: { readyState: 1 } },
    { suppressed: true },
    { wallClock: true },
    { reuseDraft: { mode: "original" } },
  ];
  for (const options of excluded) {
    const result = scenario(options);
    assert.equal(result.painted[0], 0, JSON.stringify(options));
    assert.equal(result.transitionCalls.length, 0, JSON.stringify(options));
  }
});
