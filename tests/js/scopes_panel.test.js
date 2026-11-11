import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import {
  createColorScopesPanel,
  SCOPE_KINDS,
} from "../../src/orga_drone/static/js/studio/scopes/index.js";

test("template exposes four scope controls and Pro-only hooks", () => {
  const html = fs.readFileSync("src/orga_drone/templates/studio.html", "utf8");
  assert.match(html, /id="inspector-image-section-scopes"/);
  for (const kind of SCOPE_KINDS) {
    assert.match(html, new RegExp(`data-scope-kind="${kind}"`));
  }
  assert.match(html, /Show test pattern/);
  assert.match(html, /not a measurement of your media/i);
  const css = fs.readFileSync("src/orga_drone/static/css/app.css", "utf8");
  assert.match(css, /creative"] #inspector-image-section-scopes/);
});

test("entry mounts scopes without embedding accumulate math", () => {
  const entry = fs.readFileSync("src/orga_drone/static/js/studio.js", "utf8");
  assert.match(entry, /createColorScopesPanel/);
  assert.equal(entry.includes("histogramBin"), false);
  assert.equal(entry.includes("VECTORSCOPE_CB_SCALE"), false);
});

test("fixture demo paints without claiming engine tap", () => {
  let status = "";
  let disclosure = "";
  const disclosureDataset = {};
  const canvas = {
    width: 80,
    height: 45,
    getContext() {
      return {
        fillStyle: "",
        strokeStyle: "",
        font: "",
        fillRect() {},
        beginPath() {},
        moveTo() {},
        lineTo() {},
        stroke() {},
        fillText() {},
        createImageData(w, h) {
          return { data: new Uint8ClampedArray(w * h * 4), width: w, height: h };
        },
        putImageData() {},
      };
    },
  };
  const root = {
    dataset: {},
    querySelector(sel) {
      if (sel === "[data-scope-canvas]") return canvas;
      if (sel === "[data-scope-status]") {
        return {
          set textContent(v) {
            status = v;
          },
          get textContent() {
            return status;
          },
        };
      }
      if (sel === "[data-scope-disclosure]") {
        return {
          dataset: disclosureDataset,
          set textContent(v) {
            disclosure = v;
          },
          get textContent() {
            return disclosure;
          },
        };
      }
      if (sel === "[data-scope-dropped]") return { textContent: "" };
      return null;
    },
  };
  const panel = createColorScopesPanel({ root });
  panel.showFixture("color-bars");
  panel.setKind("vectorscope");
  assert.equal(panel.getState().fixtureMode, true);
  assert.match(disclosure, /Test patterns only|not a measurement/i);
  assert.equal(disclosureDataset.scopeSource, "fixture");
  assert.match(status, /not a media measurement/i);
  assert.ok(panel.getMeasurements().histogram.bins === 256);
  panel.destroy();
});
