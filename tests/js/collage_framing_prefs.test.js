import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

test("collage framing prefs round-trip and modifier matching", () => {
  const source = readFileSync("src/orga_drone/static/js/studio/collage-framing-prefs.js", "utf8");
  // Strip ESM export so the helpers can run in a plain VM context.
  const body = source
    .replace(/^export const /gm, "const ")
    .replace(/^export function /gm, "function ");
  const store = new Map();
  const context = {
    localStorage: {
      getItem: (key) => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => {
        store.set(key, String(value));
      },
    },
  };
  vm.createContext(context);
  vm.runInContext(
    `${body}\nglobalThis.__framing = { readFramingPrefs, writeFramingPrefs, modifierMatches };`,
    context
  );
  const api = context.__framing;
  const initial = api.readFramingPrefs();
  assert.equal(initial.panModifier, "none");
  assert.equal(initial.zoomModifier, "none");
  api.writeFramingPrefs({ panModifier: "alt", zoomModifier: "ctrl" });
  const saved = api.readFramingPrefs();
  assert.equal(saved.panModifier, "alt");
  assert.equal(saved.zoomModifier, "ctrl");
  assert.equal(
    api.modifierMatches("none", {
      altKey: false,
      ctrlKey: false,
      metaKey: false,
      shiftKey: false,
    }),
    true
  );
  assert.equal(
    api.modifierMatches("none", {
      altKey: true,
      ctrlKey: false,
      metaKey: false,
      shiftKey: false,
    }),
    false
  );
  assert.equal(
    api.modifierMatches("alt", {
      altKey: true,
      ctrlKey: false,
      metaKey: false,
      shiftKey: false,
    }),
    true
  );
  assert.equal(
    api.modifierMatches("ctrl", {
      altKey: false,
      ctrlKey: true,
      metaKey: false,
      shiftKey: false,
    }),
    true
  );
});
