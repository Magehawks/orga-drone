import assert from "node:assert/strict";
import test from "node:test";
import { runScopesNonpackagedPerf } from "../../scripts/scopes_nonpackaged_perf.mjs";

test("non-packaged scopes harness returns ≥5 cold/warm samples per case", () => {
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
  }
  assert.ok(report.limitations.some((line) => /packaged/i.test(line)));
});

test("1080p synthetic buffer size is disclosed in MiB", () => {
  const report = runScopesNonpackagedPerf({
    samples: 5,
    sizes: [{ label: "preview-1920x1080", width: 1920, height: 1080, sampleFactor: 4 }],
  });
  const only = report.cases[0];
  // float32 RGBA: 1920*1080*4*4 bytes
  assert.equal(only.buffer_bytes, 1920 * 1080 * 4 * 4);
  assert.ok(only.buffer_mib > 30);
});
