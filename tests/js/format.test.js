import assert from "node:assert/strict";
import test from "node:test";

import {
  formatExportDuration,
  formatLaneTime,
  formatTemplate,
  formatTime,
} from "../../src/orga_drone/static/js/studio/format.js";

test("formatTemplate replaces known placeholders and leaves unknown ones empty", () => {
  assert.equal(
    formatTemplate("Clip {current} of {total}", { current: 2, total: 5 }),
    "Clip 2 of 5"
  );
  assert.equal(formatTemplate("{missing}", {}), "");
  assert.equal(formatTemplate("{zero}", { zero: 0 }), "0");
  assert.equal(formatTemplate(null, { a: 1 }), "");
  assert.equal(formatTemplate("plain", { a: 1 }), "plain");
});

test("formatTime keeps the existing HH:MM:SS rounding behavior", () => {
  assert.equal(formatTime(0), "00:00:00");
  assert.equal(formatTime(-5), "00:00:00");
  assert.equal(formatTime(59.4), "00:00:59");
  assert.equal(formatTime(59.6), "00:01:00");
  assert.equal(formatTime(3599), "00:59:59");
  assert.equal(formatTime(3600), "01:00:00");
  assert.equal(formatTime(3661), "01:01:01");
  assert.equal(formatTime(86399), "23:59:59");
  assert.equal(formatTime(86400), "24:00:00");
  assert.equal(formatTime(Number.NaN), "00:00:00");
  assert.equal(formatTime("12.5"), "00:00:13");
});

test("formatLaneTime removes only the leading empty hour", () => {
  assert.equal(formatLaneTime(0), "00:00");
  assert.equal(formatLaneTime(59.6), "01:00");
  assert.equal(formatLaneTime(3599), "59:59");
  assert.equal(formatLaneTime(3600), "01:00:00");
  assert.equal(formatLaneTime(3661), "01:01:01");
});

test("formatExportDuration keeps its compact export clock semantics", () => {
  assert.equal(formatExportDuration(0), "0:00");
  assert.equal(formatExportDuration(-5), "0:00");
  assert.equal(formatExportDuration(59.6), "1:00");
  assert.equal(formatExportDuration(3599), "59:59");
  assert.equal(formatExportDuration(3600), "1:00:00");
  assert.equal(formatExportDuration(3661), "1:01:01");
  assert.equal(formatExportDuration(Number.NaN), "0:00");
});
