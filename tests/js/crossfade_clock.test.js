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
  const clip = {
    dataset: {
      kind: "video",
      canPlay: "1",
      thumb: "",
    },
  };
  const state = { playing: options.playing ?? true };
  const events = [];
  let pendingFrame = null;
  const video = {
    src: "source",
    hidden: true,
    muted: false,
    paused: options.paused ?? true,
    readyState: 4,
    playbackRate: 1,
    style: { opacity: "" },
    getAttribute: () => "source",
    load: () => events.push("load"),
    play: () => {
      video.paused = false;
      events.push("play");
      return Promise.resolve();
    },
    pause: () => {
      video.paused = true;
      events.push("pause");
    },
    addEventListener: (name) => events.push(`on:${name}`),
    requestVideoFrameCallback: (callback) => {
      events.push("requestFrame");
      pendingFrame = callback;
      return 1;
    },
  };
  let currentTime = options.currentTime ?? 2.5;
  Object.defineProperty(video, "currentTime", {
    get: () => currentTime,
    set: (value) => {
      currentTime = value;
      events.push("seek");
    },
  });
  const context = vm.createContext({
    state,
    clip,
    previewVideoB: video,
    previewImageB: null,
    previewTitlecardB: null,
    previewVideo: { hidden: false },
    videoSrcFor: () => "source",
    imageSrcFor: () => "",
    loopPlayInS: () => 1.5,
    sectionSampleS: (_, localS) => localS,
    playbackSpeed: () => 2,
    playSourceOffset: (_, time) => time * 2,
    secondaryVideoTarget: (_, time) => 1.5 + time * 2,
    speedRampOf: () => null,
    rampNeedsSeekPreview: () => false,
    allowHtmlVideoAutoplay: ({ playing, seekSample }) => !!playing && !seekSample,
    applyClipPlayback: () => {
      video.playbackRate = 2;
      events.push("applyClipPlayback");
    },
    schedulePreviewBlit: () => events.push("scheduleBlit"),
    fillTitlecardEl() {},
  });
  const body = functionBody("showOutgoingLayer");
  assert.ok(body, "showOutgoingLayer must exist");
  vm.runInContext(body, context);
  context.showOutgoingLayer(clip, options.localS ?? 0.5);
  return { video, events, state, pendingFrame };
}

test("playing crossfade starts the outgoing video without an unnecessary seek", () => {
  const result = scenario();
  assert.equal(result.video.paused, false);
  assert.equal(result.video.playbackRate, 2);
  assert.equal(result.video.hidden, false);
  assert.equal(result.video.muted, true);
  assert.ok(result.events.includes("play"));
  assert.ok(!result.events.includes("seek"), "matching target must not seek");
});

test("paused crossfade keeps the outgoing video paused and seeks it", () => {
  const result = scenario({ playing: false, paused: true, currentTime: 2.49 });
  assert.equal(result.video.paused, true);
  assert.equal(result.video.currentTime, 2.5);
  assert.ok(!result.events.includes("pause"));
  assert.ok(!result.events.includes("play"));
});

test("drifted outgoing video is corrected", () => {
  const result = scenario({ currentTime: 0 });
  assert.equal(result.video.currentTime, 2.5);
});

test("paused crossfade requests a repaint after the outgoing frame is presented", () => {
  const result = scenario({ playing: false, paused: true, currentTime: 0 });
  assert.ok(result.events.includes("requestFrame"));
  const before = result.events.filter((event) => event === "scheduleBlit").length;
  assert.equal(typeof result.pendingFrame, "function");
  result.pendingFrame();
  const after = result.events.filter((event) => event === "scheduleBlit").length;
  assert.equal(after, before + 1);
});

function preloadScenario(options = {}) {
  const events = [];
  const clip = {
    dataset: {
      studioId: "1",
      kind: "video",
      canPlay: "1",
      appliedType: options.transition ?? "crossfade",
      appliedDuration: "1",
    },
  };
  const next = { dataset: { studioId: "2", kind: "video" } };
  let currentTime = 0;
  const video = {
    src: "source",
    hidden: false,
    muted: false,
    paused: true,
    readyState: 4,
    playbackRate: 1,
    style: { opacity: "" },
    getAttribute: () => "source",
    load: () => events.push("load"),
    play: () => {
      video.paused = false;
      events.push("play");
      return Promise.resolve();
    },
    pause: () => {
      video.paused = true;
      events.push("pause");
    },
    addEventListener: (name) => events.push(`on:${name}`),
  };
  Object.defineProperty(video, "currentTime", {
    get: () => currentTime,
    set: (value) => {
      currentTime = value;
      events.push("seek");
    },
  });
  const state = { playing: options.playing ?? true };
  const context = vm.createContext({
    state,
    previewVideoB: video,
    crossfadePreloadId: null,
    clips: () => [clip, next],
    clipDuration: () => 3,
    loopOverlapS: () => options.loopOverlap ?? 0,
    videoSrcFor: () => "source",
    loopPlayInS: () => 0,
    sectionSampleS: (_, localS) => localS,
    playbackSpeed: () => options.speed ?? 1,
    playSourceOffset: (_, time) => time * (options.speed ?? 1),
    secondaryVideoTarget: (_, time) => time * (options.speed ?? 1),
    speedRampOf: () => options.ramp ?? null,
    rampNeedsSeekPreview: (ramp) => !!(options.seekSample || ramp),
    allowHtmlVideoAutoplay: ({ playing, seekSample }) => !!playing && !seekSample,
    applyClipPlayback: () => events.push("applyClipPlayback"),
  });
  const names = ["clearCrossfadePreload", "prepareOutgoingCrossfade"];
  const bodies = names.map(functionBody).filter(Boolean);
  vm.runInContext(["let crossfadePreloadId = null;", ...bodies].join("\n"), context);
  const hit = {
    clip,
    index: 0,
    localS: options.localS ?? 1.6,
    overlapClip: options.overlapClip ?? null,
  };
  const prepared = context.prepareOutgoingCrossfade(hit);
  return { prepared, video, events, context };
}

test("outgoing crossfade is preloaded and playing before the overlap", () => {
  const result = preloadScenario();
  assert.equal(result.prepared, true);
  assert.equal(result.video.hidden, true);
  assert.equal(result.video.paused, false);
  assert.equal(result.video.currentTime, 1.6);
  assert.ok(result.events.includes("play"));
});

test("outgoing crossfade is not preloaded too early or when paused", () => {
  assert.equal(preloadScenario({ localS: 0.5 }).prepared, false);
  assert.equal(preloadScenario({ playing: false }).prepared, false);
});

test("outgoing crossfade is not preloaded for cut, fade-black or loop blends", () => {
  assert.equal(preloadScenario({ transition: "cut" }).prepared, false);
  assert.equal(preloadScenario({ transition: "fade_black" }).prepared, false);
  assert.equal(preloadScenario({ loopOverlap: 0.2 }).prepared, false);
});

test("outgoing preload does not run inside an active overlap", () => {
  const result = preloadScenario({ overlapClip: { dataset: { studioId: "1" } } });
  assert.equal(result.prepared, false);
});

test("outgoing preload keeps the clip speed mapping", () => {
  const result = preloadScenario({ speed: 2, localS: 1.6 });
  assert.equal(result.prepared, true);
  assert.equal(result.video.currentTime, 3.2);
});

test("outgoing preload stays paused for seek-sampled >16× ramps", () => {
  const result = preloadScenario({
    seekSample: true,
    ramp: { points: [{ speed: 20 }, { speed: 20 }] },
  });
  assert.equal(result.prepared, true);
  assert.equal(result.video.paused, true);
  assert.ok(!result.events.includes("play"));
});
