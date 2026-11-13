import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildPreviewFrameUrl,
  quantizePreviewTime,
} from "../../src/orga_drone/static/js/studio/preview-frame-url.js";

describe("preview-frame-url (#358)", () => {
  it("quantizes to one decimal", () => {
    assert.equal(quantizePreviewTime(1.24), 1.2);
    assert.equal(quantizePreviewTime(1.25), 1.3);
    assert.equal(quantizePreviewTime("bad"), 0);
  });

  it("includes story_s beside t_s", () => {
    const url = buildPreviewFrameUrl(42, {
      t_s: 1.2,
      story_s: 10.5,
      detail: 0,
    });
    assert.match(url, /\/api\/studio\/42\/preview-frame\?/);
    assert.match(url, /t_s=1\.2/);
    assert.match(url, /story_s=10\.5/);
    assert.match(url, /detail=0/);
  });

  it("omits non-finite story_s", () => {
    const url = buildPreviewFrameUrl("7", { t_s: 0, story_s: Number.NaN, before: true });
    assert.match(url, /t_s=0/);
    assert.match(url, /before=1/);
    assert.doesNotMatch(url, /story_s=/);
  });
});
