import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

import {
  createCanonicalApplier,
  createControlBridge,
  hasActiveControlGesture,
} from "../../src/orga_drone/static/js/studio/control-bridge.js";

// Execute the existing IIFE functions without booting a real library or media.
const script = readFileSync(
  new URL("../../src/orga_drone/static/js/studio.js", import.meta.url),
  "utf8"
);
function sourceFunction(name) {
  const start = script.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, name);
  return script.slice(start, script.indexOf("\n  }", start) + 4);
}

function element(dataset = {}) {
  const classes = new Set();
  const attributes = new Map();
  const listeners = new Map();
  return {
    dataset,
    hidden: false,
    style: { opacity: "" },
    readyState: 1,
    duration: 100,
    currentTime: 0,
    paused: true,
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
    },
    setAttribute: (name, value) => attributes.set(name, value),
    getAttribute: (name) => attributes.get(name),
    removeAttribute: (name) => attributes.delete(name),
    querySelector: () => null,
    pause() {
      this.paused = true;
    },
    play() {
      this.paused = false;
      return Promise.resolve();
    },
    load() {},
    addEventListener(name, callback) {
      const list = listeners.get(name) || [];
      list.push(callback);
      listeners.set(name, list);
    },
    fire(name) {
      const callbacks = listeners.get(name) || [];
      listeners.delete(name);
      callbacks.forEach((callback) => callback());
    },
  };
}

function harness() {
  const noop = () => {};
  const list = [244, 245].map((id) =>
    element({ studioId: String(id), kind: "video", available: "1", canPlay: "1" })
  );
  list[0].classList.add("is-selected");
  list[0].setAttribute("aria-selected", "true");
  const transitions = [element({ transitionAfter: "244" })];
  const panel = { querySelector: () => ({ textContent: "" }) };
  const calls = { preview: [], polls: [], inspectors: [], timers: [] };
  const state = {
    selected: { type: "clip", id: "244" },
    projectTimeS: 7.5,
    playing: false,
    activeStudioId: "244",
    tracks: [],
    volume: 0.8,
  };
  const context = vm.createContext({
    state,
    rampEditor: null,
    reuseDraft: null,
    syncToken: 0,
    loadedVideoSrc: "",
    suppressVideoClock: false,
    projectId: 46,
    controlPendingWrites: 0,
    controlWriteFailed: false,
    historyGesture: null,
    titleSaveTimer: 0,
    hslSaveTimer: 0,
    colorWheelsSaveTimer: 0,
    saveStateEl: null,
    dragCard: null,
    musicDragCard: null,
    dragOriginalMediaId: null,
    edgeDrag: null,
    maskDragging: false,
    playheadDragging: false,
    hasActiveControlGesture,
    grid: { querySelectorAll: () => transitions },
    clips: () => list,
    findClip: (_grid, id) => list.find((clip) => clip.dataset.studioId === String(id)),
    clipKind: (clip) => clip?.dataset.kind,
    clipId: (clip) => clip?.dataset.studioId,
    clipFilename: () => "synthetic.mp4",
    clipDuration: () => 20,
    sourceInS: () => 0,
    sourceOutS: () => 20,
    catalogDurationS: () => 100,
    defaultReuseRange: () => ({ inS: 20, outS: 100, whole: false }),
    videoSrcFor: () => "synthetic-story",
    lutProxySrcFor: () => "",
    speedRampOf: () => null,
    rampNeedsSeekPreview: () => false,
    allowHtmlVideoAutoplay: ({ playing, seekSample }) => !!playing && !seekSample,
    storyToSource: (_clip, time) => time,
    playSourceOffset: (_clip, time) => time,
    secondaryVideoTarget: (_clip, time) => time,
    lutProxyActiveFor: () => false,
    loopPlayInS: () => 0,
    loopPlayOutS: () => 20,
    playbackSpeed: () => 1,
    slowBarOf: () => null,
    clipMediaTarget: (_clip, mapped, start) => mapped + start,
    sectionPoint: (_clip, localS) => ({ index: 0, offset: localS }),
    readColorAnimation: () => null,
    readSaturationRamp: () => null,
    previewVideo: element(),
    previewVideoB: element(),
    previewImage: element(),
    previewImageB: element(),
    previewTitlecard: element(),
    previewTitlecardB: element(),
    previewPlaceholder: element(),
    previewFadeBlack: element(),
    document: { getElementById: (id) => (id === "inspector-clip" ? panel : null) },
    window: { setTimeout: (callback) => calls.timers.push(callback) },
    kindLabels: { video: "Video" },
    labelInStory: "In Story",
    showInspector: (id) => calls.inspectors.push(id),
    readFrame: () => ({}),
    frameMotionOn: () => false,
    forwardLoopActive: () => false,
    sectionRepeats: () => 1,
    playheadTouchesClip: () => true,
    pausePlayback: () => {
      state.playing = false;
    },
    setProjectTime: (time) => {
      state.projectTimeS = time;
      calls.preview.push(time);
    },
    syncPreviewMedia: () => calls.preview.push(state.projectTimeS),
  });
  context.timedSelection = null;
  for (const name of [
    "layoutMusicSpans",
    "markActiveClips",
    "updateRemoveEnabled",
    "hideTitlecard",
    "clearLutPreviewStill",
    "paintReuseDraft",
    "showReuseChrome",
    "hideClipMenu",
    "revealPreviewMedia",
    "holdPreviewMedia",
    "applyVolume",
    "applyClipPlayback",
    "schedulePreviewBlit",
    "setInspectorHeading",
    "fillSpeedInspector",
    "fillImageAdjust",
    "fillImageInspectorSections",
    "fillSaturationRamp",
    "fillOverlayInspector",
    "fillMaskInspector",
    "fillFrame",
    "fillMapInspector",
    "fillHud",
    "setClipRemoveAction",
    "setInspectorTab",
    "refreshInspectorTabMarks",
    "scheduleLutProxyPrepare",
    "clearTimedSelection",
    "layoutEffectBars",
    "layoutClipAudio",
  ])
    context[name] = noop;
  for (const name of [
    "hideOverlayLayers",
    "beginReuseDraft",
    "openOriginalDraft",
    "openReuseDraft",
    "reusePreviewSrc",
    "seekCatalog",
    "cancelReuseDraft",
    "selectClip",
    "selectedAdjustableClip",
    "controlSnapshot",
    "seekVideoLocal",
    "showVideo",
  ])
    vm.runInContext(sourceFunction(name), context);
  context.revealPreviewMedia = (media) => media.classList.remove("is-pending");
  context.holdPreviewMedia = (media) => media.classList.add("is-pending");
  context.controlBridge = createControlBridge({
    sessionId: "synthetic-editor",
    snapshot: context.controlSnapshot,
    whenIdle: async () => {},
    applyCanonical: noop,
    lockInput: noop,
    request: async (_action, body) => {
      calls.polls.push(body.state);
      return { enabled: true, commands: [] };
    },
  });
  const original = (id = "1") => ({
    dataset: {
      canPlay: "1",
      mediaDuration: "100",
      originalMediaId: id,
      streamUrl: `original-${id}`,
    },
  });
  return { context, state, list, calls, original, transitions };
}

test("Original and reuse previews clear selection and publish no editable target", async () => {
  for (const mode of ["original", "reuse"]) {
    const { context: c, state, list, original, calls } = harness();
    assert.equal(c.controlSnapshot().clip_id, 244);
    assert.equal(c.controlSnapshot().ready, true);
    if (mode === "original") c.openOriginalDraft(original());
    else c.openReuseDraft("245");
    assert.equal(state.selected.type, null);
    assert.equal(state.selected.id, null);
    assert.equal(state.activeStudioId, null);
    assert.ok(list.every((clip) => !clip.classList.contains("is-selected")));
    assert.ok(list.every((clip) => clip.getAttribute("aria-selected") === undefined));
    await c.controlBridge.tick();
    assert.equal(calls.polls[0].clip_id, null);
    assert.equal(calls.polls[0].ready, false);
    assert.ok(calls.polls[0].selection_revision > 0);
    // Defence in depth: a retained selection must still not target a draft.
    state.selected = { type: "clip", id: "244" };
    assert.equal(c.controlSnapshot().clip_id, null);
    assert.equal(c.controlSnapshot().ready, false);
    const apply = createCanonicalApplier({ snapshot: c.controlSnapshot });
    assert.throws(() => apply({ project_id: 46, clip_id: 244 }), /no longer selected/);
  }
});

test("draft entry clears all transition media layers and primary opacity", () => {
  const { context: c, original, transitions } = harness();
  c.previewVideo.style.opacity = "0.4";
  c.previewVideo.classList.add("is-pending");
  c.previewImage.style.opacity = "0.4";
  c.previewVideoB.paused = false;
  transitions[0].classList.add("is-selected");
  c.openOriginalDraft(original());
  c.previewVideo.fire("loadedmetadata");
  for (const media of [c.previewVideoB, c.previewImageB, c.previewTitlecardB, c.previewFadeBlack]) {
    assert.equal(media.hidden, true);
  }
  assert.equal(c.previewVideoB.paused, true);
  assert.equal(c.previewVideo.style.opacity, "");
  assert.equal(c.previewImage.style.opacity, "");
  assert.equal(c.previewVideo.classList.contains("is-pending"), false);
  assert.equal(transitions[0].classList.contains("is-selected"), false);
});

test("switching drafts preserves cancellation selection and Story time", () => {
  const { context: c, state, list, original, calls } = harness();
  c.openOriginalDraft(original());
  c.openReuseDraft("245");
  c.openOriginalDraft(original("2"));
  assert.equal(c.reuseDraft.previousSelection.id, "244");
  c.cancelReuseDraft();
  assert.equal(c.reuseDraft, null);
  assert.equal(state.selected.id, "244");
  assert.equal(list[0].classList.contains("is-selected"), true);
  assert.equal(c.controlSnapshot().clip_id, 244);
  assert.equal(c.controlSnapshot().ready, true);
  assert.equal(calls.preview.at(-1), 7.5);
});

test("invalid Original entry and missing cancellation targets stay coherent", () => {
  const { context: c, state, list, original, calls } = harness();
  const invalid = original();
  invalid.dataset.mediaDuration = "NaN";
  c.openOriginalDraft(invalid);
  assert.equal(c.reuseDraft, null);
  assert.equal(state.selected.id, "244");
  assert.equal(list[0].classList.contains("is-selected"), true);
  c.openOriginalDraft(original());
  list.shift();
  c.cancelReuseDraft();
  assert.equal(state.selected.id, null);
  assert.equal(c.controlSnapshot().clip_id, null);
  assert.equal(calls.inspectors.at(-1), "inspector-empty");
});

test("cancellation restores transition/music selections and tolerates no prior selection", () => {
  for (const type of ["transition", "music", null]) {
    const { context: c, state, original, calls, transitions } = harness();
    state.selected = { type, id: type === "transition" ? "244" : type === "music" ? "23" : null };
    state.tracks = [{ id: 23 }];
    c.selectTransition = (transition) => {
      state.selected = { type: "transition", id: transition.dataset.transitionAfter };
    };
    c.selectMusic = (id) => {
      state.selected = { type: "music", id };
    };
    c.openOriginalDraft(original());
    c.cancelReuseDraft();
    assert.equal(state.selected.type, type);
    assert.equal(c.controlSnapshot().clip_id, null);
    assert.equal(c.controlSnapshot().ready, false);
    if (type === null) assert.equal(calls.inspectors.at(-1), "inspector-empty");
    if (type === "transition") {
      c.openOriginalDraft(original());
      transitions.length = 0;
      c.cancelReuseDraft();
      assert.equal(state.selected.type, null);
      assert.equal(calls.inspectors.at(-1), "inspector-empty");
    }
  }
});

test("selecting any actual Story clip exits reuse preview and publishes its ID", async () => {
  for (const id of ["244", "245"]) {
    const { context: c, state, calls } = harness();
    c.openReuseDraft(id);
    c.selectClip(id);
    assert.equal(c.reuseDraft, null);
    assert.equal(state.selected.id, id);
    await c.controlBridge.tick();
    assert.equal(calls.polls[0].clip_id, Number(id));
    assert.equal(calls.polls[0].ready, true);
  }
});

test("late Story metadata cannot seek or reveal over an Original", () => {
  const { context: c, list, original } = harness();
  c.previewVideo.readyState = 0;
  c.showVideo("synthetic-story", 8, { play: false, clip: list[0] });
  c.seekVideoLocal(9, list[0]);
  c.openOriginalDraft(original());
  c.previewVideo.fire("loadedmetadata");
  c.previewVideo.fire("loadeddata");
  assert.equal(c.previewVideo.currentTime, 0);
  assert.equal(c.previewVideo.classList.contains("is-pending"), false);
  assert.equal(c.suppressVideoClock, true);
});

test("obsolete draft seeks cannot overwrite another draft or cancelled Story", () => {
  const { context: c, original } = harness();
  c.previewVideo.readyState = 0;
  c.openOriginalDraft(original());
  c.seekCatalog(12);
  c.openOriginalDraft(original("2"));
  c.seekCatalog(27);
  c.previewVideo.fire("loadedmetadata");
  assert.equal(c.previewVideo.currentTime, 27);
  c.seekCatalog(42);
  c.cancelReuseDraft();
  c.previewVideo.currentTime = 7.5;
  c.previewVideo.fire("loadedmetadata");
  assert.equal(c.previewVideo.currentTime, 7.5);
});

test("delayed Story clock release cannot take over Original preview", () => {
  const { context: c, list, calls, original } = harness();
  c.loadedVideoSrc = "synthetic-story";
  c.showVideo("synthetic-story", 8, { play: false, clip: list[0] });
  c.openOriginalDraft(original());
  calls.timers.forEach((callback) => callback());
  assert.equal(c.suppressVideoClock, true);
});

test("Story crossfades and cinematic loops retain two layers only during blends", () => {
  const { context: c, list } = harness();
  for (const name of [
    "applyPreviewGrades",
    "syncAnnotations",
    "drawPrivacyMasks",
    "drawFlightMap",
    "applyFramePreview",
    "syncHud",
    "syncFullscreenControl",
    "schedulePreviewBlit",
  ])
    c[name] = () => {};
  c.clipDuration = () => 13;
  c.clipMediaTarget = (_clip, offset) => offset;
  c.prepareOutgoingCrossfade = () => false;
  c.clearCrossfadePreload = () => {};
  for (const name of [
    "forwardLoopActive",
    "loopPlayInS",
    "loopPlayOutS",
    "onePlayS",
    "loopOverlapS",
    "forwardLoopOverlapS",
    "forwardLoopSpans",
    "forwardLoopStarts",
    "sectionPoint",
    "cinematicBlendProgress",
    "showLoopIncoming",
    "applyTransitionPreview",
  ]) {
    vm.runInContext(sourceFunction(name), c);
  }
  list[0].dataset.forwardLoopTransition = "cinematic";
  list[0].dataset.loopTransitionCurve = "smooth";
  Object.assign(list[0].dataset, {
    sourceIn: "0",
    sourceOut: "5",
    forwardLoopActive: "1",
    forwardLoopOverlap: "1",
    forwardLoopPlays: "3",
    forwardLoopPartial: "0",
  });
  c.applyTransitionPreview({ clip: list[0], localS: 4.5 });
  assert.equal(c.previewVideoB.hidden, false);
  assert.equal(c.previewVideo.style.opacity, "0.5");
  c.applyTransitionPreview({ clip: list[0], localS: 2 });
  assert.equal(c.previewVideoB.hidden, true);
  assert.equal(c.previewVideo.style.opacity, "");
  c.showOutgoingLayer = () => {
    c.previewVideoB.hidden = false;
  };
  c.applyTransitionPreview({ clip: list[1], overlapClip: list[0], crossfadeProgress: 0.3 });
  assert.equal(c.previewVideoB.hidden, false);
  assert.equal(c.previewVideo.style.opacity, "0.3");
});
