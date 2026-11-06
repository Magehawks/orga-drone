// Diagnostic regression for the existing canonical clock and paint scheduler.
// Explicit CLI (not an automatically passing test): baseline is expected to fail.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const script = fs.readFileSync(path.resolve(__dirname, "../../src/orga_drone/static/js/studio.js"), "utf8");
function body(name) {
  const start = script.indexOf(`  function ${name}(`);
  if (start < 0) return null;
  return script.slice(start, script.indexOf("\n  }", start) + 4);
}
function scenario(options = {}) {
  const clip = { dataset: { studioId: "1", kind: "video" } };
  const state = { playing: true, activeStudioId: "1", projectTimeS: 0 };
  const video = { currentTime: 3.5, paused: false, hidden: false, seeking: false, readyState: 4,
    ended: false, currentSrc: "source", getAttribute: () => "source", ...options.video };
  const queue = [];
  const painted = [];
  const context = vm.createContext({
    state, previewVideo: video, previewVideoB: null, previewBlitRaf: 0,
    reuseDraft: options.reuseDraft || null, suppressVideoClock: !!options.suppressed,
    wallClockRaf: options.wallClock ? 5 : 0,
    videoLoopIndex: 0, loopSeeking: false, loadedVideoSrc: "source",
    clips: () => [clip], sourceInS: () => 1.5, sourceOutS: () => 100,
    playbackSpeed: () => 2, sectionRepeats: () => 1, sectionCycleS: () => 20,
    lutProxyActiveFor: () => !!options.proxy,
    applyClipPlayback() {}, slowBarOf: () => null,
    forwardLoopOverlapS: () => 0, forwardLoopSpans: () => [],
    clipStartTime: () => 4, clipDuration: () => 20,
    updatePlayheadChrome() {}, resolveAt: () => ({ clip }),
    applyTransitionPreview() {}, updateCutEnabled() {}, syncMusicAudio() {},
    syncPreviewMedia() {}, beginClockForActiveClip() {}, advanceToNextOrStop() {},
    pausePlayback() {}, sourceToStory: (_, t) => t,
    paintPreviewBlit: () => painted.push(state.projectTimeS),
    requestAnimationFrame: (callback) => { queue.push(callback); return queue.length; },
  });
  vm.runInContext(["clipOffsetFromMediaTime", "videoStoryPosition", "syncStoryClockFromVideo", "onVideoTimeUpdate", "schedulePreviewBlit"].map(body).filter(Boolean).join("\n"), context);
  context.schedulePreviewBlit();
  queue.shift()(1000);
  return { state, painted };
}
assert.equal(scenario().painted[0], 5, "paint must sample canonical source-in/speed mapping between native timeupdate events");
assert.equal(scenario({ proxy: true }).painted[0], 5.75, "clip-local LUT proxy mapping must be retained");
for (const options of [
  { video: { paused: true } }, { video: { seeking: true } }, { video: { hidden: true } },
  { video: { readyState: 1 } }, { suppressed: true }, { wallClock: true },
  { reuseDraft: { mode: "original" } },
]) {
  assert.equal(scenario(options).painted[0], 0, "excluded clocks must not advance Story during paint");
}
console.log("CANONICAL_CLOCK_TICK_PROBE_PASSED");
