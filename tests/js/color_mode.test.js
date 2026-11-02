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
  const standard = makeButton("standard");
  const expert = makeButton("expert");
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
      querySelectorAll: (selector) => (selector === "[data-image-mode]" ? [standard, expert] : []),
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, panel, standard, expert, storage };
}

test("color editing mode is a local UI preference only", () => {
  const { context, panel, standard, expert, storage } = modeContext("expert");
  assert.equal(context.readColorModePreference(), "expert");
  context.applyColorModePreference("standard", { persist: true });
  assert.equal(panel.dataset.imageMode, "standard");
  assert.equal(standard.attrs["aria-pressed"], "true");
  assert.equal(expert.attrs["aria-pressed"], "false");
  assert.equal(storage.get("orga-drone.studio.color-mode"), "standard");
  assert.equal(standard.classList.values.has("is-active"), true);
});

test("color editing mode defaults to standard without stored preference", () => {
  const { context } = modeContext(null);
  assert.equal(context.readColorModePreference(), "standard");
});

test("mode switch does not call preview or save paths", () => {
  assert.doesNotMatch(source, /applyPreviewGrades|scheduleLutProxyPrepare|fetch\(/);
});
