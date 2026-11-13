import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  reorderStepIds,
  stepTypeLabel,
} from "../../src/orga_drone/static/js/studio/managed-step-editor.js";

describe("managed-step-editor (#361/#363)", () => {
  it("labels known step types", () => {
    assert.equal(stepTypeLabel("primaries-v1"), "Primaries");
    assert.equal(stepTypeLabel("custom-op"), "custom-op");
  });

  it("reorders steps up and down without inventing ids", () => {
    const steps = [{ id: "a" }, { id: "b" }, { id: "c" }];
    assert.deepEqual(reorderStepIds(steps, "b", "up"), ["b", "a", "c"]);
    assert.deepEqual(reorderStepIds(steps, "b", "down"), ["a", "c", "b"]);
    assert.equal(reorderStepIds(steps, "a", "up"), null);
    assert.equal(reorderStepIds(steps, "c", "down"), null);
    assert.equal(reorderStepIds(steps, "missing", "up"), null);
  });
});
