import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  contextDigestFromParts,
  createPreviewTokenStore,
  previewTokenKey,
} from "../../src/orga_drone/static/js/studio/preview-token.js";

describe("preview-token (#363)", () => {
  it("builds stable context digests and keys", () => {
    assert.equal(contextDigestFromParts(["a", 1, null]), "a|1|");
    assert.equal(previewTokenKey({ clipId: 9 }), "9");
    assert.equal(previewTokenKey({ key: "custom", clipId: 9 }), "custom");
  });

  it("rejects stale generation after begin or invalidate for one key", () => {
    const store = createPreviewTokenStore();
    const first = store.begin({ projectId: 1, clipId: 2, revision: 3, contextDigest: "x" });
    assert.equal(store.isCurrent(first), true);
    const second = store.begin({ projectId: 1, clipId: 2, revision: 3, contextDigest: "x" });
    assert.equal(store.isCurrent(first), false);
    assert.equal(store.isCurrent(second), true);
    store.invalidate("2");
    assert.equal(store.isCurrent(second), false);
  });

  it("keeps parallel clip tokens independent", () => {
    const store = createPreviewTokenStore();
    const a = store.begin({ clipId: "a", revision: "1", contextDigest: "ctx-a" });
    const b = store.begin({ clipId: "b", revision: "1", contextDigest: "ctx-b" });
    assert.equal(store.isCurrent(a), true);
    assert.equal(store.isCurrent(b), true);
    store.begin({ clipId: "b", revision: "2", contextDigest: "ctx-b" });
    assert.equal(store.isCurrent(a), true);
    assert.equal(store.isCurrent(b), false);
  });

  it("rejects mismatched clip or revision", () => {
    const store = createPreviewTokenStore();
    const token = store.begin({ clipId: "9", revision: "4", contextDigest: "ctx" });
    assert.equal(store.isCurrent({ ...token, clipId: "8" }), false);
    assert.equal(store.isCurrent({ ...token, revision: "5" }), false);
    assert.equal(store.isCurrent(token), true);
  });
});
