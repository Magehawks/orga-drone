import test from "node:test";
import assert from "node:assert/strict";
import { proposeObjectSelect } from "../../src/orga_drone/static/js/studio/grade-api.js";

test("proposeObjectSelect posts seeds and expand_passes", async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          ok: true,
          proposal: {
            points: [
              [0.2, 0.2],
              [0.8, 0.2],
              [0.5, 0.8],
            ],
            seeds_uv: [
              [0.5, 0.5],
              [0.55, 0.55],
            ],
            expand_passes: 2,
          },
        };
      },
    };
  };
  try {
    const data = await proposeObjectSelect(42, {
      u: 0.5,
      v: 0.5,
      seeds: [
        [0.55, 0.55],
        [0.45, 0.45],
      ],
      expandPasses: 2,
      expectedRevision: 7,
      tol: 16,
    });
    assert.equal(data.ok, true);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/api/studio/42/grade/object-select");
    const body = JSON.parse(calls[0].init.body);
    assert.equal(body.u, 0.5);
    assert.equal(body.v, 0.5);
    assert.equal(body.expected_revision, 7);
    assert.equal(body.tol, 16);
    assert.equal(body.expand_passes, 2);
    assert.deepEqual(body.seeds, [
      [0.55, 0.55],
      [0.45, 0.45],
    ]);
  } finally {
    globalThis.fetch = original;
  }
});
