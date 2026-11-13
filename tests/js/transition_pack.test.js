import test from "node:test";
import assert from "node:assert/strict";
import {
  blurRadiusPx,
  isOverlapType,
  wipeMask,
} from "../../src/orga_drone/static/js/studio/transition-pack.js";

test("drone pack shares crossfade occupancy and rejects other ids", () => {
  assert.equal(isOverlapType("crossfade"), true);
  assert.equal(isOverlapType("blur_dissolve"), true);
  assert.equal(isOverlapType("soft_wipe_down"), true);
  assert.equal(isOverlapType("fade_black"), false);
  assert.equal(isOverlapType("cut"), false);
});

test("blur peaks in the middle and wipes reveal in the named direction", () => {
  assert.ok(blurRadiusPx(0) < 0.01);
  assert.ok(blurRadiusPx(0.5) > blurRadiusPx(0.1));
  assert.ok(blurRadiusPx(1) < 0.01);
  assert.match(wipeMask("soft_wipe_left", 0.5), /to right/);
  assert.match(wipeMask("soft_wipe_right", 0.5), /to left/);
  assert.match(wipeMask("soft_wipe_up", 0.5), /to bottom/);
  assert.match(wipeMask("soft_wipe_down", 0.5), /to top/);
  assert.equal(wipeMask("crossfade", 0.5), "");
});
