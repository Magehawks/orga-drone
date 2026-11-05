import test from "node:test";
import assert from "node:assert/strict";
import {
  createControlBridge,
  createBridgeRequest,
  createCanonicalApplier,
  hasActiveControlGesture,
} from "../../src/orga_drone/static/js/studio/control-bridge.js";

function harness() {
  let state = {
    project_id: 1,
    clip_id: 2,
    playhead_s: 0,
    playing: false,
    busy: false,
    ready: true,
  };
  let queued = [{ command_id: "one", persisted: false }];
  const calls = [];
  const applied = [];
  const locks = [];
  const statuses = [];
  const bridge = createControlBridge({
    sessionId: "editor",
    snapshot: () => state,
    whenIdle: async () => {},
    applyCanonical: (result) => {
      applied.push(result);
      return "refresh_requested";
    },
    lockInput: (value) => locks.push(value),
    status: (value) => statuses.push(value),
    request: async (action, body) => {
      calls.push({ action, body });
      if (action === "poll") return { enabled: true, commands: queued };
      if (action === "execute")
        return { command_id: "one", persisted: true, ui_applied: false, canonical: {} };
      return { enabled: action !== "disable" };
    },
  });
  return {
    bridge,
    calls,
    applied,
    locks,
    statuses,
    setState: (next) => {
      state = { ...state, ...next };
    },
    setQueued: (next) => {
      queued = next;
    },
  };
}

test("canonical application refreshes once, acknowledges preview request, and does not save", async () => {
  const h = harness();
  await h.bridge.tick();
  assert.deepEqual(
    h.calls.map((c) => c.action),
    ["poll", "execute", "ack"]
  );
  assert.equal(h.applied.length, 1);
  assert.deepEqual(h.locks, [true, false]);
  assert.equal(h.calls[2].body.preview_status, "refresh_requested");
});

test("two-clip canonical Undo/Redo synchronizes only the original inspector and preview", () => {
  const clips = new Map([
    [1, { image: { contrast: 15 } }],
    [2, { image: { contrast: 0 } }],
  ]);
  let selected = 2;
  const inspector = [];
  const preview = [];
  const apply = createCanonicalApplier({
    snapshot: () => ({ project_id: 10, clip_id: selected }),
    getClip: (id) => clips.get(id),
    writeImage: (clip, image, persisted) => {
      assert.equal(persisted, true);
      clip.image = image;
    },
    writeColor: (clip, color) => {
      clip.color = color;
    },
    fillInspector: (clip) => inspector.push(clip.image.contrast),
    syncHistory: () => {},
    refreshPreview: () => preview.push(clips.get(selected).image.contrast),
    setSaved: () => {},
  });
  const undoA = {
    project_id: 10,
    clip_id: 1,
    undone_command_id: "edit-A",
    canonical: { image: { contrast: 0 }, color_look: {} },
  };
  assert.throws(() => apply(undoA), /target/);
  assert.equal(clips.get(1).image.contrast, 15);
  assert.deepEqual(inspector, []);
  assert.deepEqual(preview, []);
  selected = 1;
  assert.throws(() => apply({ ...undoA, project_id: 11 }), /target/);
  assert.equal(apply(undoA), "refresh_requested");
  apply({ ...undoA, canonical: { image: { contrast: 15 }, color_look: {} } });
  assert.deepEqual(inspector, [0, 15]);
  assert.deepEqual(preview, [0, 15]);
  assert.equal(clips.get(2).image.contrast, 0);
});

test("fresh state reports unsaved edits and A to B to A selection revision", async () => {
  const h = harness();
  h.bridge.noteLocalChange();
  h.setState({ clip_id: 3, busy: true });
  h.bridge.noteLocalChange();
  h.setState({ clip_id: 2 });
  await h.bridge.tick();
  const execution = h.calls.find((c) => c.action === "execute");
  assert.equal(execution.body.state.selection_revision, 2);
  assert.equal(execution.body.state.busy, true);
});

test("committed unconfirmed command resynchronizes without reexecuting", async () => {
  const h = harness();
  h.setQueued([{ command_id: "one", persisted: true, ui_applied: false, canonical: {} }]);
  await h.bridge.tick();
  assert.deepEqual(
    h.calls.map((c) => c.action),
    ["poll", "ack"]
  );
});

test("sequential poll excludes overlap and always unlocks on acknowledgement loss", async () => {
  let resolve;
  let polls = 0;
  const locks = [];
  const bridge = createControlBridge({
    sessionId: "editor",
    snapshot: () => ({}),
    whenIdle: async () => {},
    applyCanonical: () => "refresh_requested",
    lockInput: (v) => locks.push(v),
    request: async (action) => {
      if (action === "poll") {
        polls += 1;
        await new Promise((r) => {
          resolve = r;
        });
        return { enabled: true, commands: [{ command_id: "x", persisted: true }] };
      }
      throw new Error("synthetic connection loss");
    },
  });
  const first = bridge.tick();
  await bridge.tick();
  assert.equal(polls, 1);
  resolve();
  await first;
  assert.deepEqual(locks, [true, false]);
});

test("transport sends key only in enable body and propagates stable error codes", async () => {
  const calls = [];
  const request = createBridgeRequest(async (url, options) => {
    calls.push({ url, options });
    return { ok: false, json: async () => ({ error: { code: "EDITOR_SESSION_CONFLICT" } }) };
  });
  await assert.rejects(request("enable", { pairing_key: "synthetic" }), {
    code: "EDITOR_SESSION_CONFLICT",
  });
  assert.equal(calls[0].url, "/api/studio/control/enable");
  assert.equal(JSON.parse(calls[0].options.body).pairing_key, "synthetic");
});

test("native drag remains busy after pointer cancellation until dragend", async () => {
  const gestures = {
    dragCard: {},
    musicDragCard: null,
    dragOriginalMediaId: null,
    edgeDrag: null,
    maskDragging: false,
    playheadDragging: false,
  };
  let pointerActive = true;
  const states = [];
  let applied = 0;
  const bridge = createControlBridge({
    sessionId: "editor",
    snapshot: () => ({ busy: pointerActive || hasActiveControlGesture(gestures) }),
    whenIdle: async () => {},
    applyCanonical: () => {
      applied += 1;
    },
    lockInput: () => {},
    request: async (action, body) => {
      if (action === "poll")
        return { enabled: true, commands: [{ command_id: "during-drag", persisted: false }] };
      if (action === "execute") {
        states.push(body.state);
        return { persisted: false, error_code: "EDITOR_BUSY" };
      }
    },
  });
  pointerActive = false; // Browser's pointercancel starts native HTML dragging.
  await bridge.tick();
  assert.equal(states[0].busy, true);
  assert.equal(applied, 0);
  gestures.dragCard = null; // dragend, independently of the pointer stream.
  assert.equal(hasActiveControlGesture(gestures), false);
  for (const key of Object.keys(gestures)) {
    gestures[key] = true;
    assert.equal(hasActiveControlGesture(gestures), true, key);
    gestures[key] = null;
  }
});

test("extended color/effect canonical values update only the selected clip", () => {
  const clips = new Map([[7, {}]]);
  const filled = [];
  const previews = [];
  const apply = createCanonicalApplier({
    snapshot: () => ({ project_id: 3, clip_id: 7 }),
    getClip: (id) => clips.get(id),
    writeImage: (clip, image) => {
      clip.image = image;
    },
    writeColor: (clip, color) => {
      clip.color = color;
    },
    writeHsl: (clip, hsl) => {
      clip.hsl = hsl;
    },
    writeWheels: (clip, wheels) => {
      clip.wheels = wheels;
    },
    writeDetail: (clip, detail) => {
      clip.detail = detail;
    },
    fillInspector: (clip) => filled.push(clip),
    syncHistory: () => {},
    refreshPreview: () => previews.push(7),
    setSaved: () => {},
  });
  const result = {
    project_id: 3,
    clip_id: 7,
    can_undo: true,
    can_redo: false,
    canonical: {
      image: { contrast: 15 },
      color_look: { creative_lut: "a".repeat(32) + ".cube" },
      hsl: { ranges: { blue: { hue: 20, saturation: 0, luminance: 0 } } },
      color_wheels: { wheels: { shadows: { x: 0.2, y: -0.1 } } },
      detail: { sharpen: 12, denoise: 4 },
    },
  };
  assert.equal(apply(result), "refresh_requested");
  assert.deepEqual(clips.get(7).hsl, result.canonical.hsl);
  assert.deepEqual(clips.get(7).wheels, result.canonical.color_wheels);
  assert.deepEqual(clips.get(7).detail, result.canonical.detail);
  assert.deepEqual(filled, [clips.get(7)]);
  assert.deepEqual(previews, [7]);
  assert.throws(() => apply({ ...result, clip_id: 8 }), /target/);
});
