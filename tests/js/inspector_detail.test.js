import assert from "node:assert/strict";
import test from "node:test";

import {
  clampDetailSlider,
  createDetailControls,
  neutralDetail,
  readDetail,
  writeDetail,
} from "../../src/orga_drone/static/js/studio/inspector/detail.js";

function element(id) {
  const listeners = new Map();
  return {
    id,
    value: "",
    textContent: "",
    dataset: {},
    addEventListener(event, handler) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(handler);
    },
    removeEventListener(event, handler) {
      listeners.get(event)?.delete(handler);
    },
    dispatch(event) {
      listeners.get(event)?.forEach((handler) => handler());
    },
    listenerCount(event) {
      return listeners.get(event)?.size ?? 0;
    },
  };
}

function setup(overrides = {}) {
  const elements = {
    "inspector-detail-sharpen": element("inspector-detail-sharpen"),
    "inspector-detail-denoise": element("inspector-detail-denoise"),
    "inspector-detail-sharpen-value": element("inspector-detail-sharpen-value"),
    "inspector-detail-denoise-value": element("inspector-detail-denoise-value"),
    "inspector-detail-reset": element("inspector-detail-reset"),
  };
  const documentImpl = {
    getElementById(id) {
      return elements[id] ?? null;
    },
  };
  const clip = {
    kind: "video",
    dataset: { studioId: "clip-1", detail: JSON.stringify({ sharpen: 35, denoise: 20 }) },
  };
  const selected = { current: clip };
  const saved = [];
  const errors = [];
  const refreshes = [];
  const requests = [];
  const controls = createDetailControls({
    documentImpl,
    getSelectedClip: () => selected.current,
    getClipById: (id) => (id === "clip-1" ? clip : null),
    setSaved: (value) => saved.push(value),
    showError: (message) => errors.push(message),
    refresh: (value) => refreshes.push(value),
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return {
        ok: true,
        json: async () => ({ ok: true, detail: JSON.parse(options.body) }),
      };
    },
    ...overrides,
  });
  return { controls, elements, clip, selected, saved, errors, refreshes, requests };
}

async function flushSaves() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("clamps, neutralizes, reads, and writes detail settings", () => {
  assert.equal(clampDetailSlider(-5), 0);
  assert.equal(clampDetailSlider(150), 100);
  assert.equal(clampDetailSlider("42.4"), 42);
  assert.equal(clampDetailSlider("nope"), 0);
  assert.deepEqual(neutralDetail(), { sharpen: 0, denoise: 0 });

  const clip = { dataset: { detail: '{"sharpen":12,"denoise":120}' } };
  assert.deepEqual(readDetail(clip), { sharpen: 12, denoise: 100 });
  assert.deepEqual(readDetail({ dataset: { detail: "bad json" } }), { sharpen: 0, denoise: 0 });

  writeDetail(clip, { sharpen: 4, denoise: 8 });
  assert.deepEqual(readDetail(clip), { sharpen: 4, denoise: 8 });
});

test("fills the panel from the selected clip", () => {
  const { controls, elements, clip } = setup();

  controls.fill(clip);

  assert.equal(elements["inspector-detail-sharpen"].value, "35");
  assert.equal(elements["inspector-detail-denoise"].value, "20");
  assert.equal(elements["inspector-detail-sharpen-value"].textContent, "35");
  assert.equal(elements["inspector-detail-denoise-value"].textContent, "20");
});

test("writes local input immediately and saves on change", async () => {
  const { controls, elements, clip, saved, refreshes, requests } = setup();
  controls.bind();
  elements["inspector-detail-sharpen"].value = "80";
  elements["inspector-detail-denoise"].value = "40";

  elements["inspector-detail-sharpen"].dispatch("input");

  assert.deepEqual(readDetail(clip), { sharpen: 80, denoise: 40 });
  assert.equal(elements["inspector-detail-sharpen-value"].textContent, "80");
  assert.deepEqual(saved, [false]);
  assert.deepEqual(refreshes, [clip]);

  elements["inspector-detail-sharpen"].dispatch("change");
  await flushSaves();

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/studio/clip-1/detail");
  assert.deepEqual(JSON.parse(requests[0].options.body), { sharpen: 80, denoise: 40 });
  assert.deepEqual(saved, [false, true]);
});

test("resets to neutral and saves", async () => {
  const { controls, elements, clip, saved, requests, refreshes } = setup();
  controls.bind();

  elements["inspector-detail-reset"].dispatch("click");
  await flushSaves();

  assert.deepEqual(readDetail(clip), { sharpen: 0, denoise: 0 });
  assert.equal(elements["inspector-detail-sharpen"].value, "0");
  assert.equal(elements["inspector-detail-denoise"].value, "0");
  assert.deepEqual(refreshes, [clip]);
  assert.deepEqual(saved, [false, true]);
  assert.equal(requests.length, 1);
});

test("reports save failures", async () => {
  const { controls, elements, errors } = setup({
    fetchImpl: async () => ({ ok: false, status: 500, json: async () => ({}) }),
  });
  controls.bind();

  elements["inspector-detail-sharpen"].dispatch("change");
  await flushSaves();

  assert.deepEqual(errors, ["Could not save sharpen or denoise."]);
});

test("binds and removes listeners once", () => {
  const { controls, elements } = setup();
  controls.bind();
  controls.bind();
  assert.equal(elements["inspector-detail-sharpen"].listenerCount("input"), 1);
  assert.equal(elements["inspector-detail-reset"].listenerCount("click"), 1);

  controls.destroy();
  assert.equal(elements["inspector-detail-sharpen"].listenerCount("input"), 0);
  assert.equal(elements["inspector-detail-reset"].listenerCount("click"), 0);
});
