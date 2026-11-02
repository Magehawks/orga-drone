import assert from "node:assert/strict";
import test from "node:test";

import {
  clipCanPlay,
  clipDisplaySubtitle,
  clipDisplayTitle,
  clipDuration,
  clipEffectiveDuration,
  clipFilename,
  clipHasProxy,
  clipId,
  clipIsAvailable,
  clipKind,
  clipMediaDuration,
  clipMediaId,
  clipPlaybackSpeed,
  clipPhotoDuration,
  clipPreviewUrl,
  clipProxyUrl,
  clipSourceIn,
  clipSourceOut,
  clipStreamUrl,
  clipThumbUrl,
  findClip,
  listClipElements,
  setClipField,
} from "../../src/orga_drone/static/js/studio/clip-model.js";

function clip(dataset = {}) {
  return { dataset: { ...dataset } };
}

test("lists and finds clip elements without touching the DOM", () => {
  const first = clip({ studioId: "1" });
  const second = clip({ studioId: "2" });
  const scope = {
    querySelectorAll: (selector) => (selector === ".studio-clip" ? [first, second] : []),
  };

  assert.deepEqual(listClipElements(scope), [first, second]);
  assert.equal(findClip(scope, 2), second);
  assert.equal(findClip(scope, "missing"), null);
  assert.deepEqual(listClipElements(null), []);
  assert.deepEqual(listClipElements({}), []);
});

test("reads clip identity, type, availability, and media identity", () => {
  const video = clip({
    studioId: "7",
    kind: "video",
    available: "1",
    canPlay: "1",
    hasProxy: "1",
    mediaId: "42",
  });
  assert.equal(clipId(video), "7");
  assert.equal(clipKind(video), "video");
  assert.equal(clipIsAvailable(video), true);
  assert.equal(clipCanPlay(video), true);
  assert.equal(clipHasProxy(video), true);
  assert.equal(clipMediaId(video), 42);

  const missing = clip();
  assert.equal(clipId(missing), "");
  assert.equal(clipKind(missing), "unknown");
  assert.equal(clipIsAvailable(missing), false);
  assert.equal(clipCanPlay(missing), false);
  assert.equal(clipHasProxy(missing), false);
  assert.equal(clipMediaId(missing), null);

  assert.equal(clipMediaId(clip({ mediaId: "" })), null);
  assert.equal(clipMediaId(clip({ mediaId: "0" })), null);
  assert.equal(clipMediaId(clip({ mediaId: "-4" })), null);
  assert.equal(clipMediaId(clip({ mediaId: "nope" })), null);
});

test("reads filenames, display text, and media URLs", () => {
  const video = clip({
    filename: "clip.mp4",
    displayTitle: "Title",
    displaySubtitle: "Subtitle",
    streamUrl: "/stream",
    proxyUrl: "/proxy",
    previewUrl: "/preview",
    thumb: "/thumb",
  });
  assert.equal(clipFilename(video), "clip.mp4");
  assert.equal(clipDisplayTitle(video), "Title");
  assert.equal(clipDisplaySubtitle(video), "Subtitle");
  assert.equal(clipStreamUrl(video), "/stream");
  assert.equal(clipProxyUrl(video), "/proxy");
  assert.equal(clipPreviewUrl(video), "/preview");
  assert.equal(clipThumbUrl(video), "/thumb");

  const missing = clip();
  assert.equal(clipFilename(missing), "");
  assert.equal(clipDisplayTitle(missing), "");
  assert.equal(clipDisplaySubtitle(missing), "");
  assert.equal(clipStreamUrl(missing), "");
  assert.equal(clipProxyUrl(missing), "");
  assert.equal(clipPreviewUrl(missing), "");
  assert.equal(clipThumbUrl(missing), "");
});

test("converts durations and source ranges with the existing fallbacks", () => {
  assert.equal(clipEffectiveDuration(clip({ effectiveDuration: "12.5" })), 12.5);
  assert.equal(clipEffectiveDuration(clip({ effectiveDuration: "0" })), null);
  assert.equal(clipEffectiveDuration(clip({ effectiveDuration: "-2" })), null);
  assert.equal(clipEffectiveDuration(clip({ effectiveDuration: "nope" })), null);
  assert.equal(clipEffectiveDuration(clip({ effectiveDuration: "" })), null);

  assert.equal(clipSourceIn(clip({ sourceIn: "2.25" })), 2.25);
  assert.equal(clipSourceIn(clip({ sourceIn: "" })), 0);
  assert.equal(clipSourceIn(clip({ sourceIn: "-1" })), 0);
  assert.equal(clipSourceIn(clip({ sourceIn: "nope" })), 0);
  assert.equal(clipSourceIn(null), 0);

  assert.equal(clipSourceOut(clip({ sourceOut: "8.5" })), 8.5);
  assert.equal(clipSourceOut(clip({ sourceOut: "0" })), null);
  assert.equal(clipSourceOut(clip({ sourceOut: "-1" })), null);
  assert.equal(clipSourceOut(clip({ sourceOut: "" })), null);

  assert.equal(clipMediaDuration(clip({ mediaDuration: "9.5" })), 9.5);
  assert.equal(clipMediaDuration(clip({ mediaDuration: "nope" })), null);

  assert.equal(clipPhotoDuration(clip({ photoDuration: "4.5" })), 4.5);
  assert.equal(clipPhotoDuration(clip({ photoDuration: "0" })), null);
  assert.equal(clipPhotoDuration(clip({})), null);
});

test("keeps the playback speed fallback unchanged", () => {
  assert.equal(clipPlaybackSpeed(clip({ playbackSpeed: "0.5" })), 0.5);
  assert.equal(clipPlaybackSpeed(clip({ playbackSpeed: "0.25" })), 0.25);
  assert.equal(clipPlaybackSpeed(clip({ playbackSpeed: "1" })), 1);
  assert.equal(clipPlaybackSpeed(clip({ playbackSpeed: "0.75" })), 1);
  assert.equal(clipPlaybackSpeed(clip({ playbackSpeed: "" })), 1);
  assert.equal(clipPlaybackSpeed(null), 1);
});

test("clipDuration preserves the photo, title-card, and invalid-value rules", () => {
  assert.equal(clipDuration(clip({ effectiveDuration: "7.5", kind: "video" }), 3), 7.5);
  assert.equal(clipDuration(clip({ kind: "photo" }), 4), 4);
  assert.equal(clipDuration(clip({ kind: "title_card" }), 4), 3);
  assert.equal(clipDuration(clip({ kind: "unknown" }), 4), 0);
  assert.equal(clipDuration(clip({ kind: "video", effectiveDuration: "" }), 4), 0);
  assert.equal(clipDuration(clip({ kind: "title_card", effectiveDuration: "0" }), 4), 3);
  assert.equal(clipDuration(clip({ kind: "video", effectiveDuration: "-1" }), 4), 0);
  assert.equal(clipDuration(null, 4), 0);
});

test("writes only supported fields and never persists", () => {
  const video = clip({ studioId: "7", kind: "video" });
  assert.equal(setClipField(video, "displayTitle", "New title"), true);
  assert.equal(video.dataset.displayTitle, "New title");
  assert.equal(setClipField(video, "effectiveDuration", 12.5), true);
  assert.equal(video.dataset.effectiveDuration, "12.5");
  assert.equal(setClipField(video, "photoDuration", null), true);
  assert.equal(video.dataset.photoDuration, "");
  assert.equal(setClipField(video, "unknownField", "x"), false);
  assert.equal(video.dataset.unknownField, undefined);
  assert.equal(setClipField(null, "displayTitle", "x"), false);
});

test("pure readers do not mutate the clip dataset", () => {
  const video = clip({
    studioId: "7",
    kind: "video",
    available: "1",
    canPlay: "1",
    hasProxy: "1",
    mediaId: "42",
    filename: "clip.mp4",
    effectiveDuration: "12.5",
    sourceIn: "2",
    sourceOut: "9",
    mediaDuration: "10",
    playbackSpeed: "0.5",
    photoDuration: "4",
    streamUrl: "/stream",
    proxyUrl: "/proxy",
    previewUrl: "/preview",
    thumb: "/thumb",
    displayTitle: "Title",
    displaySubtitle: "Subtitle",
  });
  const before = { ...video.dataset };
  clipId(video);
  clipKind(video);
  clipIsAvailable(video);
  clipCanPlay(video);
  clipHasProxy(video);
  clipMediaId(video);
  clipFilename(video);
  clipDisplayTitle(video);
  clipDisplaySubtitle(video);
  clipEffectiveDuration(video);
  clipSourceIn(video);
  clipSourceOut(video);
  clipMediaDuration(video);
  clipPlaybackSpeed(video);
  clipPhotoDuration(video);
  clipStreamUrl(video);
  clipProxyUrl(video);
  clipPreviewUrl(video);
  clipThumbUrl(video);
  clipDuration(video, 3);
  assert.deepEqual(video.dataset, before);
});

test("never starts API requests or installs a global Studio object", () => {
  const hadFetch = Object.prototype.hasOwnProperty.call(globalThis, "fetch");
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.fetch = () => {
    fetchCalls += 1;
    throw new Error("clip model must not fetch");
  };
  try {
    const video = clip({
      studioId: "7",
      kind: "video",
      available: "1",
      canPlay: "1",
      hasProxy: "1",
      mediaId: "42",
      filename: "clip.mp4",
      effectiveDuration: "12.5",
      sourceIn: "2",
      sourceOut: "9",
      mediaDuration: "10",
      playbackSpeed: "0.5",
      photoDuration: "4",
      streamUrl: "/stream",
      proxyUrl: "/proxy",
      previewUrl: "/preview",
      thumb: "/thumb",
      displayTitle: "Title",
      displaySubtitle: "Subtitle",
    });
    const scope = {
      querySelectorAll: (selector) => (selector === ".studio-clip" ? [video] : []),
    };
    clipId(video);
    clipKind(video);
    clipIsAvailable(video);
    clipCanPlay(video);
    clipHasProxy(video);
    clipMediaId(video);
    clipFilename(video);
    clipDisplayTitle(video);
    clipDisplaySubtitle(video);
    clipEffectiveDuration(video);
    clipSourceIn(video);
    clipSourceOut(video);
    clipMediaDuration(video);
    clipPlaybackSpeed(video);
    clipPhotoDuration(video);
    clipStreamUrl(video);
    clipProxyUrl(video);
    clipPreviewUrl(video);
    clipThumbUrl(video);
    clipDuration(video, 3);
    listClipElements(scope);
    findClip(scope, "7");
    setClipField(video, "displayTitle", "Changed");
  } finally {
    if (hadFetch) globalThis.fetch = originalFetch;
    else delete globalThis.fetch;
  }
  assert.equal(fetchCalls, 0);
  assert.equal(globalThis.OrgaStudioClipModel, undefined);
});
