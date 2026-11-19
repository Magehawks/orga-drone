import assert from "node:assert/strict";
import test from "node:test";
import {
  bindSliderNumberPair,
  clampSyncedNumber,
} from "../../src/orga_drone/static/js/studio/slider-number-sync.js";

function fakeInput(initial = "0") {
  return {
    value: String(initial),
    disabled: false,
    listeners: {},
    addEventListener(type, fn) {
      (this.listeners[type] ||= []).push(fn);
    },
    dispatchEvent(event) {
      for (const fn of this.listeners[event.type] || []) fn(event);
      return true;
    },
    blur() {},
  };
}

test("clampSyncedNumber respects min max step and fallback", () => {
  assert.equal(clampSyncedNumber(12.4, { min: -100, max: 100, step: 1 }), 12);
  assert.equal(clampSyncedNumber(150, { min: -100, max: 100, step: 1 }), 100);
  assert.equal(clampSyncedNumber(-150, { min: -100, max: 100, step: 1 }), -100);
  assert.equal(clampSyncedNumber("x", { min: -100, max: 100, step: 1, fallback: 0 }), 0);
  assert.equal(clampSyncedNumber(1.234, { min: 0, max: 2, step: 0.01 }), 1.23);
});

test("slider and number stay synchronized on input and Enter commit", () => {
  const slider = fakeInput("0");
  const numberInput = fakeInput("0");
  const inputs = [];
  const commits = [];
  const pair = bindSliderNumberPair({
    slider,
    numberInput,
    min: -100,
    max: 100,
    step: 1,
    onInput: (v) => inputs.push(v),
    onCommit: (v) => commits.push(v),
  });

  slider.value = "25";
  slider.dispatchEvent({ type: "input" });
  assert.equal(numberInput.value, "25");
  assert.deepEqual(inputs, [25]);

  numberInput.value = "40";
  numberInput.dispatchEvent({ type: "input" });
  assert.equal(slider.value, "40");
  assert.equal(pair.getValue(), 40);

  numberInput.value = "999";
  numberInput.dispatchEvent({ type: "keydown", key: "Enter", preventDefault() {} });
  assert.equal(pair.getValue(), 100);
  assert.equal(numberInput.value, "100");
  assert.equal(commits.at(-1), 100);
});

test("invalid number commit restores last valid value", () => {
  const slider = fakeInput("12");
  const numberInput = fakeInput("12");
  const commits = [];
  bindSliderNumberPair({
    slider,
    numberInput,
    min: -100,
    max: 100,
    step: 1,
    onCommit: (v) => commits.push(v),
  });
  numberInput.value = "abc";
  numberInput.dispatchEvent({ type: "change" });
  assert.equal(numberInput.value, "12");
  assert.equal(slider.value, "12");
  assert.deepEqual(commits, [12]);
});
