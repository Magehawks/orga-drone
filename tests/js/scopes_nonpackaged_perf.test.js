import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { runScopesNonpackagedPerf } from "../../scripts/scopes_nonpackaged_perf.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");

test("non-packaged scopes harness returns ≥5 cold/warm samples and heap deltas", () => {
  const report = runScopesNonpackagedPerf({ samples: 5 });
  assert.equal(report.harness, "scopes_nonpackaged_perf");
  assert.equal(report.environment.packaged_webview2, false);
  assert.ok(report.cases.length >= 3);
  for (const entry of report.cases) {
    assert.equal(entry.cold.n, 5);
    assert.equal(entry.warm.n, 5);
    assert.ok(entry.cold.p50_ms >= 0);
    assert.ok(entry.warm.p95_ms >= entry.warm.min_ms);
    assert.ok(entry.buffer_bytes > 0);
    assert.ok(entry.effective_pixels > 0);
    assert.ok(entry.memory);
    assert.equal(entry.memory.input_buffer_bytes, entry.buffer_bytes);
    assert.equal(entry.memory.per_accumulate_heap_delta_bytes.n, 5);
  }
  assert.ok(report.limitations.some((line) => /packaged/i.test(line)));
  assert.ok(report.limitations.some((line) => /heapUsed/i.test(line)));
});

test("1080p synthetic buffer size and sampleFactor visits are disclosed", () => {
  const report = runScopesNonpackagedPerf({
    samples: 5,
    sizes: [{ label: "preview-1920x1080", width: 1920, height: 1080, sampleFactor: 4 }],
  });
  const only = report.cases[0];
  assert.equal(only.buffer_bytes, 1920 * 1080 * 4 * 4);
  assert.ok(only.buffer_mib > 30);
  assert.equal(only.sample_step, 4);
  // ceil(1920/4)*ceil(1080/4) with integer step loops from 0
  assert.equal(only.effective_pixels, 480 * 270);
});

test("committed evidence JSON matches harness schema and non-packaged flag", () => {
  const raw = readFileSync(join(root, "docs/planning/362-scopes-nonpackaged-perf.json"), "utf8");
  const evidence = JSON.parse(raw);
  assert.equal(evidence.harness, "scopes_nonpackaged_perf");
  assert.equal(evidence.environment.packaged_webview2, false);
  assert.ok(evidence.samples_per_phase >= 5);
  assert.ok(Array.isArray(evidence.cases) && evidence.cases.length >= 3);
  for (const entry of evidence.cases) {
    assert.ok(entry.cold?.n >= 5);
    assert.ok(entry.warm?.n >= 5);
    assert.ok(Number.isFinite(entry.effective_pixels));
    assert.ok(entry.memory?.per_accumulate_heap_delta_bytes?.n >= 5);
  }
  assert.ok(
    evidence.limitations.some((line) => /Packaged latency\/memory remain NOT_RUN/i.test(line))
  );
});
