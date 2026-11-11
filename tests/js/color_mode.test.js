import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const script = fs.readFileSync("src/orga_drone/static/js/studio.js", "utf8");
const start = script.indexOf("const COLOR_MODE_KEY");
const end = script.indexOf("applyColorModePreference(readColorModePreference());", start);
assert.ok(start >= 0 && end > start);
const source = script.slice(start, end);

function makeButton(mode) {
  return {
    dataset: { imageMode: mode },
    classList: {
      values: new Set(),
      toggle(name, active) {
        if (active) this.values.add(name);
        else this.values.delete(name);
      },
    },
    attrs: {},
    setAttribute(name, value) {
      this.attrs[name] = value;
    },
  };
}

function modeContext(stored) {
  const panel = { dataset: {} };
  const creative = makeButton("creative");
  const pro = makeButton("pro");
  const storage = new Map();
  if (stored) storage.set("orga-drone.studio.color-mode", stored);
  const context = {
    window: {
      localStorage: {
        getItem: (key) => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value),
      },
    },
    document: {
      getElementById: (id) => (id === "inspector-image-panel" ? panel : null),
      querySelectorAll: (selector) => (selector === "[data-image-mode]" ? [creative, pro] : []),
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, panel, creative, pro, storage };
}

test("color editing mode is a local UI preference only", () => {
  const { context, panel, creative, pro, storage } = modeContext("pro");
  assert.equal(context.readColorModePreference(), "pro");
  context.applyColorModePreference("creative", { persist: true });
  assert.equal(panel.dataset.imageMode, "creative");
  assert.equal(creative.attrs["aria-pressed"], "true");
  assert.equal(pro.attrs["aria-pressed"], "false");
  assert.equal(storage.get("orga-drone.studio.color-mode"), "creative");
  assert.equal(creative.classList.values.has("is-active"), true);
});

test("color editing mode defaults to creative without stored preference", () => {
  const { context } = modeContext(null);
  assert.equal(context.readColorModePreference(), "creative");
});

test("legacy standard and expert preferences map to creative and pro", () => {
  const standard = modeContext("standard");
  assert.equal(standard.context.readColorModePreference(), "creative");
  const expert = modeContext("expert");
  assert.equal(expert.context.readColorModePreference(), "pro");
  expert.context.applyColorModePreference("expert", { persist: true });
  assert.equal(expert.panel.dataset.imageMode, "pro");
  assert.equal(expert.storage.get("orga-drone.studio.color-mode"), "pro");
});

test("mode switch does not call preview or save paths", () => {
  assert.doesNotMatch(source, /applyPreviewGrades|scheduleLutProxyPrepare|fetch\(/);
});

test("template exposes Creative and Pro mode controls", () => {
  const html = fs.readFileSync("src/orga_drone/templates/studio.html", "utf8");
  assert.match(html, /data-image-mode="creative"/);
  assert.match(html, /data-image-mode="pro"/);
  assert.match(html, /data-quick-look-chip="cinematic"/);
  assert.match(html, /id="studio-color-grade-summary"/);
  assert.doesNotMatch(html, /data-image-mode="standard"/);
  assert.doesNotMatch(html, /data-image-mode="expert"/);
});

test("creative mode CSS hides pro-only color sections", () => {
  const css = fs.readFileSync("src/orga_drone/static/css/app.css", "utf8");
  assert.match(css, /\[data-image-mode="creative"\] #inspector-image-section-hsl/);
  assert.match(css, /\[data-image-mode="creative"\] #inspector-image-section-color-wheels/);
  assert.match(css, /\[data-image-mode="creative"\] #inspector-image-section-advanced/);
});
