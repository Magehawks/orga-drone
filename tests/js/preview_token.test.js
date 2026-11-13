import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  contextDigestFromParts,
  createPreviewTokenStore,
} from "../../src/orga_drone/static/js/studio/preview-token.js";

describe("preview-token (#363)", () => {
  it("builds stable context digests", () => {
    assert.equal(contextDigestFromParts(["a", 1, null]), "a|1|");
  });

  it("rejects stale generation after begin or invalidate", () => {
    const store = createPreviewTokenStore();
    const first = store.begin({ projectId: 1, clipId: 2, revision: 3, contextDigest: "x" });
    assert.equal(store.isCurrent(first), true);
    const second = store.begin({ projectId: 1, clipId: 2, revision: 3, contextDigest: "x" });
    assert.equal(store.isCurrent(first), false);
    assert.equal(store.isCurrent(second), true);
    store.invalidate();
    assert.equal(store.isCurrent(second), false);
  });

  it("rejects mismatched clip or revision", () => {
    const store = createPreviewTokenStore();
    const token = store.begin({ clipId: "9", revision: "4", contextDigest: "ctx" });
    assert.equal(store.isCurrent({ ...token, clipId: "8" }), false);
    assert.equal(store.isCurrent({ ...token, revision: "5" }), false);
    assert.equal(store.isCurrent(token), true);
  });
});
