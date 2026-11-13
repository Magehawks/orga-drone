import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createManagedGradePreviewCache } from "../../src/orga_drone/static/js/studio/managed-grade-preview-cache.js";

function makeClip(studioId, extras = {}) {
  return {
    dataset: {
      studioId: String(studioId),
      ...extras,
    },
  };
}

describe("managed grade preview cache", () => {
  it("caches managed grades and skips refetch", async () => {
    let calls = 0;
    const cache = createManagedGradePreviewCache({
      fetchGrade: async () => {
        calls += 1;
        return { evaluator: "managed-sdr-v1", revision: 3 };
      },
    });
    const clip = makeClip(11);
    const first = await cache.ensureCached(clip);
    const second = await cache.ensureCached(clip);
    assert.equal(first.revision, 3);
    assert.equal(second.revision, 3);
    assert.equal(calls, 1);
    assert.equal(cache.hasMiss(clip), false);
  });

  it("marks legacy/non-managed as miss and does not storm", async () => {
    let calls = 0;
    const cache = createManagedGradePreviewCache({
      fetchGrade: async () => {
        calls += 1;
        return { evaluator: "legacy-look", revision: 1 };
      },
    });
    const clip = makeClip(22);
    assert.equal(await cache.ensureCached(clip), null);
    assert.equal(await cache.ensureCached(clip), null);
    assert.equal(await cache.ensureCached(clip), null);
    assert.equal(calls, 1);
    assert.equal(cache.hasMiss(clip), true);
  });

  it("coalesces in-flight fetches for the same studio id", async () => {
    let calls = 0;
    let resolveFetch;
    const cache = createManagedGradePreviewCache({
      fetchGrade: () => {
        calls += 1;
        return new Promise((resolve) => {
          resolveFetch = resolve;
        });
      },
    });
    const clip = makeClip(33);
    const p1 = cache.ensureCached(clip);
    const p2 = cache.ensureCached(clip);
    assert.equal(calls, 1);
    resolveFetch({ evaluator: "managed-sdr-v1", revision: 9 });
    assert.equal((await p1).revision, 9);
    assert.equal((await p2).revision, 9);
  });

  it("rejects stale fill results after clip switch", () => {
    const cache = createManagedGradePreviewCache({
      fetchGrade: async () => null,
    });
    const clipA = makeClip(1);
    const ok = cache.cacheFillResult({
      clip: clipA,
      requestedStudioId: 1,
      editorStudioId: 2,
      grade: { evaluator: "managed-sdr-v1", revision: 1 },
    });
    assert.equal(ok, false);
    assert.equal(cache.readManagedGrade(clipA), null);
  });

  it("accepts fill when clip and editor still match", () => {
    const cache = createManagedGradePreviewCache({
      fetchGrade: async () => null,
    });
    const clip = makeClip(7);
    const ok = cache.cacheFillResult({
      clip,
      requestedStudioId: 7,
      editorStudioId: 7,
      grade: { evaluator: "managed-sdr-v1", revision: 4 },
    });
    assert.equal(ok, true);
    assert.equal(cache.readManagedGrade(clip).revision, 4);
  });

  it("drops stale ensure results when studio id changed on the element", async () => {
    const cache = createManagedGradePreviewCache({
      fetchGrade: async () => {
        await Promise.resolve();
        return { evaluator: "managed-sdr-v1", revision: 1 };
      },
    });
    const clip = makeClip(50);
    const pending = cache.ensureCached(clip);
    clip.dataset.studioId = "51";
    assert.equal(await pending, null);
    assert.equal(cache.readManagedGrade(clip), null);
  });
});
