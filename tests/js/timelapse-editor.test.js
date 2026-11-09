import assert from "node:assert/strict";
import test from "node:test";
import { createTimelapseEditor } from "../../src/orga_drone/static/js/studio/timelapse-editor.js";
import { flatTimelapseRamp } from "../../src/orga_drone/static/js/studio/timelapse.js";

const tick = () => new Promise((resolve) => setImmediate(resolve));

function field(name) {
  return {
    name,
    value: "",
    disabled: false,
    listeners: {},
    addEventListener(type, fn) {
      this.listeners[type] = fn;
    },
    dispatch(type) {
      this.listeners[type]?.();
    },
  };
}

function fixture(overrides = {}) {
  const target = field("target");
  const speed = field("speed");
  const apply = field("apply");
  apply.disabled = true;
  const status = { textContent: "", hidden: true, classList: { toggle() {} }, setAttribute() {} };
  const calc = { textContent: "" };
  const hint = { textContent: "" };
  const controls = [target, speed, apply];
  const panel = {
    hidden: false,
    querySelector(sel) {
      if (sel.includes("target")) return target;
      if (sel.includes("speed")) return speed;
      if (sel.includes("apply")) return apply;
      if (sel.includes("status")) return status;
      if (sel.includes("calc")) return calc;
      if (sel.includes("hint")) return hint;
      return null;
    },
    querySelectorAll() {
      return controls;
    },
  };
  let clip = {
    dataset: {
      studioId: "7",
      available: "1",
      speedRamp: "null",
      sectionRepeats: "1",
      forwardLoop: "0",
    },
  };
  let bounds = { start: 0, end: 120 };
  let ramp = null;
  const saves = [];
  let saveImpl = async (c, payload) => {
    saves.push({ clip: c, payload });
    ramp = payload;
    c.dataset.speedRamp = payload ? JSON.stringify(payload) : "null";
  };
  const pauses = [];
  const errors = [];
  const editor = createTimelapseEditor({
    panel,
    getSelection: () => clip,
    readRamp: () => ramp,
    bounds: () => bounds,
    sectionRepeats: (c) => Number(c.dataset.sectionRepeats || 1),
    forwardLoop: (c) => c.dataset.forwardLoop === "1",
    pause: () => pauses.push(1),
    onError: (error) => errors.push(error || true),
    messages: {
      invalid: "invalid",
      stale: "stale",
      applied: "applied",
      removeRamp: "remove-ramp",
      removeRepeat: "remove-repeat",
      removeLoop: "remove-loop",
      calc: "About {frames} frames (~{duration} s)",
      rangeHint: "{min}-{max}/{maxSpeed}",
      previewApprox: "seek-sample",
    },
    save: (...args) => saveImpl(...args),
    ...overrides,
  });
  return {
    panel,
    target,
    speed,
    apply,
    status,
    calc,
    editor,
    saves,
    pauses,
    errors,
    setClip(next) {
      clip = next;
    },
    setBounds(next) {
      bounds = next;
    },
    setRamp(next) {
      ramp = next;
      if (clip) clip.dataset.speedRamp = next ? JSON.stringify(next) : "null";
    },
    setSave(fn) {
      saveImpl = fn;
    },
    getClip: () => clip,
  };
}

test("editor Apply commits the validated draft once and blocks repeats until cleared", async () => {
  const f = fixture();
  f.editor.fill();
  f.target.value = "15";
  f.target.dispatch("input");
  assert.equal(f.speed.value, "8");
  assert.equal(f.apply.disabled, false);
  f.apply.dispatch("click");
  await tick();
  assert.equal(f.saves.length, 1);
  assert.deepEqual(f.saves[0].payload, flatTimelapseRamp(0, 120, 8));
  assert.equal(f.pauses.length, 1);
  assert.match(f.status.textContent, /remove-ramp|applied/);
  // Active ramp blocks another Apply without an explicit remove.
  f.apply.dispatch("click");
  await tick();
  assert.equal(f.saves.length, 1);
});

test("editor rejects stale trim after a validated draft without mutating", async () => {
  const f = fixture();
  f.editor.fill();
  f.target.value = "15";
  f.target.dispatch("input");
  assert.equal(f.apply.disabled, false);
  f.setBounds({ start: 10, end: 120 });
  f.editor.fill();
  assert.equal(f.status.textContent, "stale");
  assert.equal(f.apply.disabled, true);
  f.apply.dispatch("click");
  await tick();
  assert.equal(f.saves.length, 0);
});

test("editor keeps prior validated values visible after a failed PATCH", async () => {
  const f = fixture();
  f.setSave(async () => {
    throw new Error("network");
  });
  f.editor.fill();
  f.speed.value = "20";
  f.speed.dispatch("input");
  assert.equal(f.target.value, "6");
  f.apply.dispatch("click");
  await tick();
  assert.equal(f.saves.length, 0);
  assert.equal(f.errors.length, 1);
  assert.equal(f.getClip().dataset.speedRamp, "null");
  // Values remain so the user can retry without silent success.
  assert.equal(f.speed.value, "20");
  assert.equal(f.target.value, "6");
});

test("invalid primary input clears the secondary field so Apply cannot revive it", () => {
  const f = fixture();
  f.editor.fill();
  f.target.value = "15";
  f.target.dispatch("input");
  assert.equal(f.speed.value, "8");
  f.target.value = "0";
  f.target.dispatch("input");
  assert.equal(f.speed.value, "");
  assert.equal(f.apply.disabled, true);
  f.apply.dispatch("click");
  assert.equal(f.saves.length, 0);
});
