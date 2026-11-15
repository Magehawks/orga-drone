import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  PRESET_NAMES,
  collectDividers,
  iterLeaves,
  resolveRects,
  setSplitRatio,
} from "../../src/orga_drone/static/js/studio/collage-layout.js";

function split(dir, ratio, a, b) {
  return { type: "split", id: `s-${dir}-${ratio}`, dir, ratio, a, b };
}

function leaf(id) {
  return { type: "leaf", id };
}

describe("collage-layout", () => {
  it("lists preset names", () => {
    assert.equal(PRESET_NAMES.length, 7);
    assert.ok(PRESET_NAMES.includes("3|2"));
  });

  it("resolves a horizontal split with gap", () => {
    const spec = {
      gap_px: 10,
      root: split("h", 0.5, leaf("a"), leaf("b")),
    };
    const rects = resolveRects(spec, 210, 100);
    assert.equal(rects.a.w + rects.b.w + 10, 210);
    assert.equal(rects.a.h, 100);
    assert.equal(rects.b.x, rects.a.w + 10);
  });

  it("updates split ratios and collects dividers", () => {
    const spec = {
      gap_px: 8,
      root: split("v", 0.4, leaf("a"), leaf("b")),
    };
    const next = setSplitRatio(spec, spec.root.id, 0.7);
    assert.equal(next.root.ratio, 0.7);
    const dividers = collectDividers(next.root, 0, 0, 100, 200, 8);
    assert.equal(dividers.length, 1);
    assert.equal(dividers[0].dir, "v");
    assert.equal(iterLeaves(next.root).length, 2);
  });
});
