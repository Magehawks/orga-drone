import assert from "node:assert/strict";
import test from "node:test";

import { createImageAdjustSaver } from "../../src/orga_drone/static/js/studio/inspector/image-save.js";

const NEUTRAL = {
  exposure: 0,
  contrast: 0,
  saturation: 0,
  warmth: 0,
  highlights: 0,
  shadows: 0,
  blacks: 0,
};

function adjust(overrides = {}) {
  return { ...NEUTRAL, ...overrides };
}

function makeClip(id, values = {}) {
  return { id, adjust: adjust(values), dirty: false };
}

function jsonResponse(body, { ok = true } = {}) {
  return {
    ok,
    json: async () => body,
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

function deferredFetch() {
  const pending = [];
  return {
    pending,
    fetchImpl: (url, options) => {
      const request = deferred();
      pending.push({ url, options, request });
      return request.promise;
    },
    resolve(index, body, ok = true) {
      pending[index].request.resolve(jsonResponse(body, { ok }));
    },
  };
}

function createTimers() {
  let nextId = 1;
  const pending = new Map();
  return {
    setTimeout(fn, ms) {
      const id = nextId;
      nextId += 1;
      pending.set(id, { fn, ms });
      return id;
    },
    clearTimeout(id) {
      pending.delete(id);
    },
    runAll() {
      const timers = [...pending.values()];
      pending.clear();
      timers.forEach((timer) => timer.fn());
    },
    get size() {
      return pending.size;
    },
  };
}

function createHarness(overrides = {}) {
  const clips = new Map();
  const events = [];
  const errors = [];
  const saved = [];
  const requests = [];
  const state = { shared: Promise.resolve() };
  let selectedId = null;

  function appendShared(run) {
    const next = state.shared.then(run);
    state.shared = next.catch(() => {});
    return next;
  }

  const saver = createImageAdjustSaver({
    getClipById: (studioId) => clips.get(String(studioId)) || null,
    readAdjust: (clip) => ({ ...clip.adjust }),
    writeAdjust: (clip, values, persisted) => {
      clip.adjust = { ...values };
      clip.dirty = !persisted;
      events.push(["write", clip.id, persisted, clip.adjust.exposure]);
    },
    isSelected: (studioId) => String(selectedId) === String(studioId),
    fill: (clip) => events.push(["fill", clip.id]),
    refreshPreview: (clip) => events.push(["preview", clip.id]),
    setSaved: (value) => {
      saved.push(value);
      events.push(["saved", value]);
    },
    showError: (message) => {
      errors.push(message);
      events.push(["error", message]);
    },
    serialize: appendShared,
    getSharedChain: () => state.shared,
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return jsonResponse({ ok: true, image: JSON.parse(options.body) });
    },
    ...overrides,
  });

  return {
    saver,
    clips,
    events,
    errors,
    saved,
    requests,
    state,
    appendShared,
    setSelected: (id) => {
      selectedId = id;
    },
  };
}

test("sends the image PATCH with the current adjustment payload", async () => {
  const harness = createHarness();
  const clip = makeClip("1", { exposure: 25 });
  harness.clips.set("1", clip);
  harness.setSelected("1");

  harness.saver.queue("1");
  await harness.saver.whenIdle();

  assert.equal(harness.requests.length, 1);
  const request = harness.requests[0];
  assert.equal(request.url, "/api/studio/1/image");
  assert.equal(request.options.method, "PATCH");
  assert.deepEqual(request.options.headers, {
    "Content-Type": "application/json",
    Accept: "application/json",
  });
  assert.deepEqual(JSON.parse(request.options.body), adjust({ exposure: 25 }));
  assert.deepEqual(harness.saved, [true]);
  assert.deepEqual(
    harness.events.filter((event) => event[0] === "write"),
    [["write", "1", true, 25]]
  );
  assert(harness.events.some((event) => event[0] === "fill" && event[1] === "1"));
  assert(harness.events.some((event) => event[0] === "preview" && event[1] === "1"));
});

test("serializes rapid saves and keeps newer input dirty over a stale response", async () => {
  const control = deferredFetch();
  const harness = createHarness({ fetchImpl: control.fetchImpl });
  const clip = makeClip("1", { exposure: 25 });
  harness.clips.set("1", clip);
  harness.setSelected("1");

  harness.saver.queue("1");
  await tick();
  assert.equal(control.pending.length, 1);
  assert.equal(JSON.parse(control.pending[0].options.body).exposure, 25);

  clip.adjust = adjust({ exposure: 35 });
  clip.dirty = true;
  control.resolve(0, { ok: true, image: adjust({ exposure: 25 }) });
  await harness.saver.whenIdle();
  assert.equal(clip.adjust.exposure, 35);
  assert.equal(clip.dirty, true);
  assert.deepEqual(harness.saved, []);
  assert.equal(
    harness.events.filter((event) => event[0] === "preview").length,
    1,
    "stale response still refreshes the preview"
  );

  harness.saver.queue("1");
  await tick();
  assert.equal(control.pending.length, 2);
  assert.equal(JSON.parse(control.pending[1].options.body).exposure, 35);
  control.resolve(1, { ok: true, image: adjust({ exposure: 35 }) });
  await harness.saver.whenIdle();
  assert.equal(clip.adjust.exposure, 35);
  assert.equal(clip.dirty, false);
  assert.deepEqual(harness.saved, [true]);
});

test("does not transfer an in-flight save to a replacement clip", async () => {
  const control = deferredFetch();
  const harness = createHarness({ fetchImpl: control.fetchImpl });
  const original = makeClip("1", { exposure: 10 });
  harness.clips.set("1", original);
  harness.setSelected("1");

  harness.saver.queue("1");
  await tick();
  const replacement = makeClip("1", { exposure: 99 });
  harness.clips.set("1", replacement);

  control.resolve(0, { ok: true, image: adjust({ exposure: 10 }) });
  await harness.saver.whenIdle();

  assert.equal(original.adjust.exposure, 10);
  assert.equal(original.dirty, false);
  assert.equal(replacement.adjust.exposure, 99);
  assert.equal(replacement.dirty, false);
  assert(harness.events.some((event) => event[0] === "write" && event[3] === 10));
});

test("reports a failed save and allows a retry", async () => {
  const control = deferredFetch();
  const harness = createHarness({ fetchImpl: control.fetchImpl });
  const clip = makeClip("1", { exposure: 20 });
  clip.dirty = true;
  harness.clips.set("1", clip);
  harness.setSelected("1");

  harness.saver.queue("1");
  await tick();
  control.resolve(0, { detail: "bad image" }, false);
  await harness.saver.whenIdle();

  assert.deepEqual(harness.errors, ["bad image"]);
  assert.deepEqual(harness.saved, []);
  assert.equal(clip.dirty, true);
  assert.equal(
    harness.events.some((event) => event[0] === "write"),
    false
  );

  harness.saver.queue("1");
  await tick();
  control.resolve(1, { ok: true, image: adjust({ exposure: 20 }) });
  await harness.saver.whenIdle();

  assert.deepEqual(harness.saved, [true]);
  assert.equal(clip.dirty, false);
  assert.equal(control.pending.length, 2);
});

test("skips the request when the clip is gone", async () => {
  const harness = createHarness();

  harness.saver.queue("missing");
  await harness.saver.whenIdle();

  assert.equal(harness.requests.length, 0);
  assert.deepEqual(harness.saved, []);
  assert.deepEqual(harness.errors, []);
});

test("coalesces rapid edits when debounce is configured", async () => {
  const timers = createTimers();
  const harness = createHarness({
    debounceMs: 25,
    setTimeoutImpl: timers.setTimeout,
    clearTimeoutImpl: timers.clearTimeout,
  });
  const clip = makeClip("1", { exposure: 10 });
  harness.clips.set("1", clip);

  harness.saver.queue("1");
  clip.adjust = adjust({ exposure: 20 });
  harness.saver.queue("1");

  assert.equal(timers.size, 1);
  timers.runAll();
  await harness.saver.whenIdle();

  assert.equal(harness.requests.length, 1);
  assert.equal(JSON.parse(harness.requests[0].options.body).exposure, 20);
});

test("keeps image and saturation-ramp saves in one ordered chain", async () => {
  const order = [];
  const imageRequests = [];
  const harness = createHarness({
    fetchImpl: (url, options) => {
      const index = imageRequests.length + 1;
      order.push(`image${index}:start`);
      const request = deferred();
      imageRequests.push({ options, request });
      return request.promise;
    },
  });
  const clip = makeClip("1", { exposure: 1 });
  harness.clips.set("1", clip);

  harness.saver.queue("1");
  await tick();
  assert.deepEqual(order, ["image1:start"]);

  const rampGate = deferred();
  harness.appendShared(async () => {
    order.push("ramp:start");
    await rampGate.promise;
    order.push("ramp:end");
  });

  harness.saver.queue("1");
  await tick();
  assert.deepEqual(order, ["image1:start"]);

  imageRequests[0].request.resolve(jsonResponse({ ok: true, image: adjust({ exposure: 1 }) }));
  await tick();
  assert.deepEqual(order, ["image1:start", "ramp:start"]);

  rampGate.resolve();
  await tick();
  assert.deepEqual(order, ["image1:start", "ramp:start", "ramp:end", "image2:start"]);

  imageRequests[1].request.resolve(jsonResponse({ ok: true, image: adjust({ exposure: 1 }) }));
  await harness.saver.whenIdle();
  assert.deepEqual(order, ["image1:start", "ramp:start", "ramp:end", "image2:start"]);
});
