import assert from "node:assert/strict";
import test from "node:test";

import {
  mediaReachedPlayEnd,
  playEndMediaTime,
  proxyRelativeMediaTime,
} from "../../src/orga_drone/static/js/studio/proxy-loop-map.js";

test("proxy-relative media time is zero-based on the graded cycle", () => {
  assert.equal(proxyRelativeMediaTime(true, 12.5, 1.25), 1.25);
  assert.equal(proxyRelativeMediaTime(false, 12.5, 1.25), 13.75);
  assert.equal(proxyRelativeMediaTime(true, 12.5, -3), 0);
  assert.equal(proxyRelativeMediaTime(false, "bad", 2), 2);
});

test("play-end media time uses mapped length while a proxy is active", () => {
  assert.equal(playEndMediaTime(true, 10, 5), 5);
  assert.equal(playEndMediaTime(false, 10, 5), 15);
  assert.equal(playEndMediaTime(false, 0, 5), 5);
});

test("broken absolute seek on a proxy differs from proxy-local mapping", () => {
  const sourceIn = 12.5;
  const overlap = 1.0;
  const wrong = sourceIn + overlap;
  const right = proxyRelativeMediaTime(true, sourceIn, overlap);
  assert.notEqual(wrong, right);
  assert.equal(right, overlap);
});

test("mediaReachedPlayEnd respects the wrap epsilon", () => {
  assert.equal(mediaReachedPlayEnd(4.995, 5, 0.01), true);
  assert.equal(mediaReachedPlayEnd(4.98, 5, 0.01), false);
  assert.equal(mediaReachedPlayEnd(Number.NaN, 5), false);
});
