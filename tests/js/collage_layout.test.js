import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  PRESET_NAMES,
  collectDividers,
  iterLeaves,
  mediaSourceWindow,
  resolveRects,
  setSplitRatio,
  sourceWindow,
} from "../../src/orga_drone/static/js/studio/collage-layout.js";

function split(dir, ratio, a, b) {
  return { type: "split", id: `s-${dir}-${ratio}`, dir, ratio, a, b };
}

function leaf(id) {
  return { type: "leaf", id };
}

describe("collage-layout", () => {
  it("lists preset names", () => {
    assert.ok(PRESET_NAMES.length >= 7);
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

  it("mirrors Python source_window for fit and fill", () => {
    const fit = sourceWindow({
      sourceW: 4000,
      sourceH: 3000,
      cellW: 100,
      cellH: 100,
      fit: "fit",
      zoom: 1,
    });
    assert.equal(fit.w, 1);
    assert.equal(fit.h, 1);
    const fill = sourceWindow({
      sourceW: 4000,
      sourceH: 3000,
      cellW: 100,
      cellH: 100,
      fit: "fill",
      zoom: 1,
    });
    assert.ok(fill.w < 1 || fill.h < 1);
    const zoomed = sourceWindow({
      sourceW: 1000,
      sourceH: 1000,
      cellW: 100,
      cellH: 100,
      fit: "fill",
      zoom: 2,
      panX: 0,
      panY: 1,
    });
    assert.ok(Math.abs(zoomed.w - 0.5) < 0.001);
    assert.ok(Math.abs(zoomed.x - 0) < 0.001);
    assert.ok(Math.abs(zoomed.y - 0.5) < 0.001);
  });

  it("prefers free crop over fit/zoom window", () => {
    const win = mediaSourceWindow(
      {
        fit: "fill",
        zoom: 2,
        pan_x: 0.1,
        pan_y: 0.9,
        crop: { x: 0.1, y: 0.2, w: 0.4, h: 0.5 },
      },
      { sourceW: 1000, sourceH: 800, cellW: 400, cellH: 300 }
    );
    assert.equal(win.x, 0.1);
    assert.equal(win.y, 0.2);
    assert.equal(win.w, 0.4);
    assert.equal(win.h, 0.5);
  });
});
