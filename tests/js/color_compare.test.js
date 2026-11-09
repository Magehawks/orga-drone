import assert from "node:assert/strict";
import test from "node:test";
import { createColorCompare } from "../../src/orga_drone/static/js/studio/color-compare.js";

const tick = () => new Promise((resolve) => setImmediate(resolve));
function fixture() {
  class Element extends EventTarget {
    attrs = {};
    setAttribute(k, v) {
      this.attrs[k] = v;
    }
    focus() {}
    setPointerCapture() {}
  }
  const button = new Element();
  const status = {};
  const win = new Element();
  const doc = new Element();
  const requests = [],
    decodes = [],
    revoked = [];
  let target = { id: "1", key: "grade-A", url: "/preview-frame?before=1" };
  let changes = 0;
  const control = createColorCompare({
    button,
    status,
    windowImpl: win,
    documentImpl: doc,
    getTarget: () => target,
    whenIdle: () => Promise.resolve(),
    onChange: () => changes++,
    messages: { loading: "loading", before: "before", failed: "failed" },
    fetchImpl: (url, options) => new Promise((resolve) => requests.push({ url, options, resolve })),
    imageFactory: () => ({ decode: () => new Promise((resolve) => decodes.push(resolve)) }),
    urlImpl: { createObjectURL: (blob) => blob.id, revokeObjectURL: (url) => revoked.push(url) },
  });
  function event(name, props = {}, element = button) {
    const e = new Event(name, { cancelable: true });
    Object.assign(e, props);
    element.dispatchEvent(e);
    return e;
  }
  async function reply(index, id) {
    requests[index].resolve({ ok: true, blob: async () => ({ id }) });
    await tick();
  }
  return {
    button,
    status,
    win,
    doc,
    control,
    requests,
    decodes,
    revoked,
    event,
    reply,
    setTarget: (value) => {
      target = value;
    },
    changes: () => changes,
  };
}

test("pointer hold requests only a read-only before still and release restores the normal path", async () => {
  const f = fixture();
  f.event("pointerdown", { button: 0, pointerId: 1 });
  await tick();
  assert.equal(f.button.attrs["aria-pressed"], "true");
  assert.equal(f.status.textContent, "loading");
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].url, "/preview-frame?before=1");
  assert.equal(f.requests[0].options.method, undefined);
  assert.equal(f.requests[0].options.cache, "no-store");
  await f.reply(0, "before-A");
  f.decodes[0]();
  await tick();
  assert.equal(f.control.pictureFor({ dataset: { studioId: "1" } }).src, "before-A");
  assert.equal(f.control.pictureFor({ dataset: { studioId: "2" } }), null);
  for (let i = 0; i < 100; i++) f.control.refresh();
  assert.equal(f.requests.length, 1, "redraws never fetch comparison frames");
  f.event("pointerup");
  assert.equal(f.control.pictureFor({ dataset: { studioId: "1" } }), null);
  assert.equal(f.button.attrs["aria-pressed"], "false");
  assert.deepEqual(f.revoked, ["before-A"]);
});

test("release during fetch and rapid re-hold reject old responses", async () => {
  const f = fixture();
  f.event("keydown", { key: " " });
  await tick();
  f.event("keyup", { key: " " });
  assert.equal(f.requests[0].options.signal.aborted, true);
  f.event("keydown", { key: "Enter" });
  await tick();
  await f.reply(0, "old");
  assert.equal(f.decodes.length, 0);
  await f.reply(1, "current");
  f.decodes[0]();
  await tick();
  assert.equal(f.control.pictureFor({ dataset: { studioId: "1" } }).src, "current");
  f.event("keyup", { key: "Enter" });
});

test("selection, LUT edits/removal and play/seek changes reject in-flight decode", async () => {
  for (const target of [
    null,
    { id: "2", key: "clip-B" },
    { id: "1", key: "LUT-removed" },
    { id: "1", key: "seek" },
  ]) {
    const f = fixture();
    f.event("pointerdown", { button: 0, pointerId: 1 });
    await tick();
    await f.reply(0, "old-decode");
    f.setTarget(target);
    f.control.refresh();
    f.decodes[0]();
    await tick();
    assert.equal(f.control.pictureFor({ dataset: { studioId: "1" } }), null);
    assert.deepEqual(f.revoked, ["old-decode"]);
    assert.equal(f.button.attrs["aria-pressed"], "false");
  }
});

test("keyboard repeat, lost pointer, focus loss, hidden page and navigation cannot latch Before", async () => {
  for (const cancellation of [
    "blur",
    "pointercancel",
    "lostpointercapture",
    "pagehide",
    "visibilitychange",
  ]) {
    const f = fixture();
    f.event("pointerdown", { button: 0, pointerId: 1 });
    await tick();
    if (cancellation === "visibilitychange") f.doc.hidden = true;
    f.event(
      cancellation,
      {},
      cancellation === "pagehide" ? f.win : cancellation === "visibilitychange" ? f.doc : f.button
    );
    assert.equal(f.button.attrs["aria-pressed"], "false");
    assert.equal(f.requests[0].options.signal.aborted, true);
  }
  const f = fixture();
  f.event("keydown", { key: " ", repeat: true });
  await tick();
  assert.equal(f.requests.length, 0);
  f.setTarget(null);
  f.control.refresh();
  f.event("keydown", { key: "Enter" });
  await tick();
  assert.equal(f.requests.length, 0);
  f.control.destroy();
});

test("a failed comparison keeps the normal grade and reports failure until release", async () => {
  const f = fixture();
  f.event("keydown", { key: "Enter" });
  await tick();
  f.requests[0].resolve({ ok: false });
  await tick();
  assert.equal(f.status.textContent, "failed");
  assert.equal(f.control.pictureFor({ dataset: { studioId: "1" } }), null);
  f.event("keyup", { key: "Enter" });
  assert.equal(f.status.hidden, true);
});
