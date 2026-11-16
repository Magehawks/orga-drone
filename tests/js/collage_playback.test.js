import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MAX_CONCURRENT_COLLAGE_VIDEOS,
  countVideoLeaves,
  leafMediaUrl,
  leafNeedsDecodedStill,
  leafNeedsFramedStill,
  leafNeedsHonestStillPlay,
  leafSourceTime,
  shouldKeepComposedUnderlay,
  shouldUseStillFallback,
  specNeedsDecodedStill,
  specNeedsFramedStill,
  specNeedsHonestStillPlay,
} from "../../src/orga_drone/static/js/studio/collage-playback.js";

describe("collage-playback timing", () => {
  it("adds start offset and holds past the end", () => {
    assert.deepEqual(leafSourceTime(1.5, 2.0, 10), { t: 3.5, hold: false });
    assert.deepEqual(leafSourceTime(9, 2.0, 10), { t: 10, hold: true });
    assert.deepEqual(leafSourceTime(0, 0, null), { t: 0, hold: false });
  });

  it("caps concurrent videos at 4", () => {
    assert.equal(MAX_CONCURRENT_COLLAGE_VIDEOS, 4);
    assert.equal(shouldUseStillFallback(4), false);
    assert.equal(shouldUseStillFallback(5), true);
  });

  it("counts video leaves and builds media urls", () => {
    const spec = {
      root: {
        type: "split",
        a: { type: "leaf", id: "a", media: { source: "library", media_id: 3, kind: "video" } },
        b: {
          type: "split",
          a: { type: "leaf", id: "b", media: { source: "library", media_id: 4, kind: "photo" } },
          b: {
            type: "leaf",
            id: "c",
            media: { source: "external", kind: "video", has_path: true },
          },
        },
      },
    };
    assert.equal(countVideoLeaves(spec), 2);
    assert.equal(leafMediaUrl(9, spec.root.a), "/media/3/stream");
    assert.equal(leafMediaUrl(9, spec.root.b.b), "/api/studio/9/collage/leaves/c/stream");
    assert.equal(
      leafMediaUrl(9, {
        id: "d",
        media: { source: "library", identity_key: "abc", kind: "photo" },
      }),
      "/api/studio/9/collage/leaves/d/stream"
    );
  });

  it("detects non-default zoom/pan framing", () => {
    assert.equal(leafNeedsFramedStill({ zoom: 1, pan_x: 0.5, pan_y: 0.5 }), false);
    assert.equal(leafNeedsFramedStill({ zoom: 1.4, pan_x: 0.5, pan_y: 0.5 }), true);
    assert.equal(leafNeedsFramedStill({ zoom: 1, pan_x: 0.2, pan_y: 0.5 }), true);
    assert.equal(
      specNeedsFramedStill({
        root: {
          type: "leaf",
          id: "a",
          media: { source: "library", media_id: 1, kind: "photo", zoom: 1.2 },
        },
      }),
      true
    );
  });

  it("does not treat zoom/pan framing as a decoded-still playback gate", () => {
    assert.equal(
      specNeedsDecodedStill({
        root: {
          type: "leaf",
          id: "a",
          media: { source: "library", media_id: 1, kind: "photo", zoom: 1.2 },
        },
      }),
      false
    );
    assert.equal(
      specNeedsDecodedStill({
        root: {
          type: "leaf",
          id: "a",
          media: {
            source: "external",
            kind: "photo",
            display_name: "drone.HEIC",
            has_path: true,
          },
        },
      }),
      true
    );
  });

  it("forces decoded stills for HEIC and identity-only photos", () => {
    assert.equal(
      leafNeedsDecodedStill({
        source: "external",
        kind: "photo",
        display_name: "drone.HEIC",
        has_path: true,
      }),
      true
    );
    assert.equal(
      leafNeedsDecodedStill({
        source: "external",
        kind: "photo",
        display_name: "shot.jpg",
        has_path: true,
      }),
      false
    );
    assert.equal(
      leafNeedsDecodedStill({ source: "library", identity_key: "x", kind: "photo" }),
      true
    );
  });

  it("keeps graded compose underlay instead of killing live video", () => {
    assert.equal(
      leafNeedsHonestStillPlay({
        source: "library",
        media_id: 1,
        kind: "photo",
        grade: { look: "warm" },
      }),
      true
    );
    assert.equal(
      leafNeedsHonestStillPlay({
        source: "library",
        media_id: 1,
        kind: "photo",
        zoom: 1.3,
      }),
      true
    );
    assert.equal(
      leafNeedsHonestStillPlay({
        source: "library",
        media_id: 1,
        kind: "photo",
      }),
      false
    );
    const gradedVideo = {
      root: {
        type: "split",
        a: {
          type: "leaf",
          id: "a",
          media: {
            source: "library",
            media_id: 1,
            kind: "photo",
            grade: { look: "warm" },
          },
        },
        b: {
          type: "leaf",
          id: "b",
          media: { source: "library", media_id: 2, kind: "video" },
        },
      },
    };
    assert.equal(specNeedsHonestStillPlay(gradedVideo), true);
    assert.equal(shouldKeepComposedUnderlay(gradedVideo, true), true);
    assert.equal(shouldKeepComposedUnderlay(gradedVideo, false), false);
    assert.equal(
      shouldKeepComposedUnderlay(
        {
          root: {
            type: "leaf",
            id: "a",
            media: { source: "library", media_id: 2, kind: "video" },
          },
        },
        true
      ),
      false
    );
  });
});
