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

test("committed project navigation keeps the old editor locked and needs no acknowledgement", async () => {
  const calls = [];
  const locks = [];
  const projects = [];
  let clipWrites = 0;
  const result = {
    command_id: "open",
    persisted: true,
    ui_applied: false,
    scope: "project",
    action: "project.open",
    project_id: 1,
    clip_id: null,
    navigation_required: true,
    canonical: { project: { id: 3, title: "Other" } },
  };
  const bridge = createControlBridge({
    sessionId: "editor",
    snapshot: () => ({ project_id: 1, clip_id: 2, ready: true, busy: false, playing: false }),
    whenIdle: async () => {},
    lockInput: (value) => locks.push(value),
    applyCanonical: () => {
      clipWrites += 1;
    },
    applyProject: (value) => {
      calls.push("navigate");
      projects.push(value);
    },
    request: async (action) => {
      calls.push(action);
      if (action === "poll") return { enabled: true, commands: [{ command_id: "open" }] };
      if (action === "execute") return result;
      return result;
    },
  });
  await bridge.tick();
  assert.deepEqual(calls, ["poll", "execute", "navigate"]);
  assert.equal(clipWrites, 0);
  assert.deepEqual(locks, [true]);
  assert.deepEqual(projects, [result]);
  await bridge.tick();
  assert.equal(calls.length, 3); // old editor remains stopped after navigation request
});

test("project rename applies title before acknowledgement without clip canonical", async () => {
  const calls = [];
  const result = {
    command_id: "rename",
    persisted: true,
    ui_applied: false,
    scope: "project",
    action: "project.rename",
    project_id: 1,
    clip_id: null,
    navigation_required: false,
    canonical: { project: { id: 1, title: "Renamed" } },
  };
  const bridge = createControlBridge({
    sessionId: "editor",
    snapshot: () => ({ project_id: 1, clip_id: null, ready: false, busy: false, playing: false }),
    whenIdle: async () => {},
    lockInput: () => {},
    applyCanonical: () => {
      throw new Error("clip writer called");
    },
    applyProject: () => calls.push("title"),
    request: async (action, body) => {
      calls.push(action);
      if (action === "poll") return { enabled: true, commands: [{ command_id: "rename" }] };
      if (action === "ack") assert.equal(body.preview_status, "unavailable");
      return result;
    },
  });
  await bridge.tick();
  assert.deepEqual(calls, ["poll", "execute", "title", "ack"]);
});

test("lost project execute response retains input lock until recovery navigation", async () => {
  const locks = [];
  const calls = [];
  let committed = false;
  let busy = false;
  const result = {
    command_id: "switch",
    scope: "project",
    persisted: true,
    ui_applied: false,
    navigation_required: true,
    project_id: 1,
    clip_id: null,
  };
  const bridge = createControlBridge({
    sessionId: "editor",
    whenIdle: async () => {},
    snapshot: () => ({ project_id: 1, clip_id: 2, busy, playing: busy, ready: true }),
    lockInput: (value) => locks.push(value),
    applyCanonical: () => {
      throw new Error("clip writer called");
    },
    applyProject: () => calls.push("navigate"),
    request: async (action) => {
      calls.push(action);
      if (action === "poll")
        return {
          enabled: true,
          commands: [
            committed ? result : { command_id: "switch", scope: "project", persisted: false },
          ],
        };
      if (action === "execute") {
        committed = true;
        busy = true;
        throw new Error("lost response");
      }
      if (action === "recover") return result;
      throw new Error("acknowledgement should not be needed");
    },
  });
  await bridge.tick();
  assert.deepEqual(locks, [true]);
  await bridge.tick();
  assert.deepEqual(calls, ["poll", "execute", "recover", "navigate"]);
  assert.deepEqual(locks, [true, true]);
});

test("committed navigation proceeds even if fresh editor state becomes busy", async () => {
  let busy = false;
  let navigated = false;
  const locks = [];
  const result = {
    command_id: "switch",
    scope: "project",
    persisted: true,
    ui_applied: false,
    navigation_required: true,
  };
  const bridge = createControlBridge({
    sessionId: "editor",
    whenIdle: async () => {},
    snapshot: () => ({ project_id: 1, clip_id: 2, busy, playing: busy, ready: true }),
    lockInput: (value) => locks.push(value),
    applyCanonical: () => {
      throw new Error("clip writer called");
    },
    applyProject: () => {
      navigated = true;
    },
    request: async (action) => {
      if (action === "poll")
        return { enabled: true, commands: [{ command_id: "switch", scope: "project" }] };
      if (action === "execute") {
        busy = true;
        return result;
      }
      throw new Error("acknowledgement should not be needed");
    },
  });
  await bridge.tick();
  assert.equal(navigated, true);
  assert.deepEqual(locks, [true]);
});

test("recovery of a rejected project command unlocks without changing context", async () => {
  const calls = [];
  const locks = [];
  const bridge = createControlBridge({
    sessionId: "editor",
    whenIdle: async () => {},
    snapshot: () => ({ project_id: 1, clip_id: 2, ready: true, busy: false, playing: false }),
    lockInput: (value) => locks.push(value),
    applyCanonical: () => {
      throw new Error("clip writer called");
    },
    applyProject: () => {
      throw new Error("project application called");
    },
    request: async (action) => {
      calls.push(action);
      if (action === "poll")
        return {
          enabled: true,
          commands: [
            { command_id: "rejected", scope: "project", persisted: false, status: "queued" },
          ],
        };
      if (action === "execute") throw new Error("lost response");
      if (action === "recover")
        return {
          command_id: "rejected",
          scope: "project",
          persisted: false,
          status: "rejected",
          error_code: "STALE_STATE",
        };
      throw new Error("unexpected acknowledgement");
    },
  });
  await bridge.tick();
  assert.deepEqual(locks, [true]);
  await bridge.tick();
  assert.deepEqual(calls, ["poll", "execute", "recover"]);
  assert.deepEqual(locks, [true, true, false]);
});

function timelineHarness(executeResult, { resumeTicket = null, resumeSelection = () => {} } = {}) {
  const state = {
    project_id: 1,
    clip_id: 2,
    playhead_s: 0,
    playing: false,
    busy: false,
    ready: true,
  };
  const calls = [];
  const reloads = [];
  const statuses = [];
  const bridge = createControlBridge({
    sessionId: "old-editor",
    resumeTicket,
    resumeSelection,
    reloadTimeline: (result) => reloads.push(result),
    snapshot: () => state,
    whenIdle: async () => {},
    applyCanonical: () => "refresh_requested",
    lockInput: () => {},
    status: (value) => statuses.push(value),
    request: async (action, body) => {
      calls.push({ action, body });
      if (action === "poll")
        return {
          enabled: true,
          commands: [
            {
              command_id: "timeline-1",
              status: "queued",
              persisted: false,
              scope: "timeline",
            },
          ],
        };
      if (action === "execute") return executeResult;
      return {};
    },
  });
  return { bridge, calls, reloads, statuses, state };
}

test("timeline commit with reload ticket reloads instead of acknowledging", async () => {
  const h = timelineHarness({
    command_id: "timeline-1",
    persisted: true,
    ui_applied: false,
    scope: "timeline",
    reload_required: true,
    resume_ticket: "resume-ticket",
    canonical: {},
  });
  await h.bridge.tick();
  assert.deepEqual(
    h.calls.map((call) => call.action),
    ["poll", "execute"]
  );
  assert.equal(h.reloads.length, 1);
  assert.equal(h.reloads[0].resume_ticket, "resume-ticket");
});

test("no-op timeline commit acknowledges without reloading or applying clip canonical", async () => {
  let applied = 0;
  const calls = [];
  const bridge = createControlBridge({
    sessionId: "editor",
    snapshot: () => ({
      project_id: 1,
      clip_id: 2,
      playhead_s: 0,
      playing: false,
      busy: false,
      ready: true,
    }),
    whenIdle: async () => {},
    applyCanonical: () => {
      applied += 1;
      return "refresh_requested";
    },
    reloadTimeline: () => {
      throw new Error("no reload expected");
    },
    lockInput: () => {},
    status: () => {},
    request: async (action) => {
      calls.push(action);
      if (action === "poll")
        return {
          enabled: true,
          commands: [
            {
              command_id: "timeline-1",
              status: "queued",
              persisted: false,
              scope: "timeline",
            },
          ],
        };
      if (action === "execute")
        return {
          command_id: "timeline-1",
          persisted: true,
          ui_applied: false,
          scope: "timeline",
          reload_required: false,
          selection_clip_id: 2,
          canonical: {},
        };
      return {};
    },
  });
  await bridge.tick();
  assert.equal(applied, 0);
  assert.equal(calls.includes("ack"), true);
  assert.equal(calls.includes("resume"), false);
});

test("resume ticket restores session and selection before acknowledging timeline commit", async () => {
  const calls = [];
  const resumed = [];
  const bridge = createControlBridge({
    sessionId: "fresh-editor",
    resumeTicket: "resume-ticket",
    resumeSelection: (id) => resumed.push(id),
    snapshot: () => ({
      project_id: 1,
      clip_id: 2,
      playhead_s: 0,
      playing: false,
      busy: false,
      ready: true,
    }),
    whenIdle: async () => {},
    applyCanonical: () => "refresh_requested",
    reloadTimeline: () => {
      throw new Error("no reload expected");
    },
    lockInput: () => {},
    status: () => {},
    request: async (action, body) => {
      calls.push({ action, body });
      if (action === "resume")
        return {
          session_id: "restored-editor",
          selection_revision: 5,
          selection_clip_id: 2,
          command_id: "timeline-1",
        };
      if (action === "poll") return { enabled: true, commands: [] };
      return {};
    },
  });
  await bridge.tick();
  assert.deepEqual(calls.map((call) => call.action).slice(0, 4), ["resume", "poll", "ack", "poll"]);
  assert.deepEqual(resumed, [2]);
  assert.equal(calls[1].body.session_id, "restored-editor");
  assert.equal(calls[2].body.command_id, "timeline-1");
  assert.equal(
    calls.some((call) => call.action === "execute"),
    false
  );
});

test("transient resume failure keeps the ticket for retry and a rejection clears it", async () => {
  let attempts = 0;
  let resumed = false;
  const resumedIds = [];
  const bridge = createControlBridge({
    sessionId: "fresh-editor",
    resumeTicket: "resume-ticket",
    resumeSelection: (id) => resumedIds.push(id),
    snapshot: () => ({
      project_id: 1,
      clip_id: 2,
      playhead_s: 0,
      playing: false,
      busy: false,
      ready: true,
    }),
    whenIdle: async () => {},
    applyCanonical: () => "refresh_requested",
    lockInput: () => {},
    status: () => {},
    request: async (action) => {
      if (action === "resume") {
        attempts += 1;
        if (attempts === 1) throw new Error("network down");
        resumed = true;
        return {
          session_id: "restored-editor",
          selection_revision: 1,
          selection_clip_id: 2,
          command_id: "timeline-1",
        };
      }
      if (action === "poll") return { enabled: true, commands: [] };
      return {};
    },
  });
  await bridge.tick();
  assert.equal(resumed, false);
  await bridge.tick();
  assert.equal(attempts, 2);
  assert.equal(resumed, true);
  assert.deepEqual(resumedIds, [2]);

  let rejectedAttempts = 0;
  const rejected = createControlBridge({
    sessionId: "fresh-editor",
    resumeTicket: "dead-ticket",
    snapshot: () => ({
      project_id: 1,
      clip_id: 2,
      playhead_s: 0,
      playing: false,
      busy: false,
      ready: true,
    }),
    whenIdle: async () => {},
    applyCanonical: () => "refresh_requested",
    lockInput: () => {},
    status: () => {},
    request: async (action) => {
      if (action === "resume") {
        rejectedAttempts += 1;
        const error = new Error("expired");
        error.code = "INVALID_RESUME_TICKET";
        throw error;
      }
      return { enabled: true, commands: [] };
    },
  });
  await rejected.tick();
  await rejected.tick();
  assert.equal(rejectedAttempts, 1);
});
