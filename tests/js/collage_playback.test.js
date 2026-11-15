import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MAX_CONCURRENT_COLLAGE_VIDEOS,
  countVideoLeaves,
  leafMediaUrl,
  leafSourceTime,
  shouldUseStillFallback,
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
  });
});
