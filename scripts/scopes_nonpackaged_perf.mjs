#!/usr/bin/env node
/**
 * Non-packaged ScopeFrameV1 accumulate latency + Node heap delta harness (#362/#366).
 *
 * Measures cold/warm accumulateAllScopes on synthetic fixtures in Node, discloses
 * input buffer size, effective subsampled visit count, and heapUsed deltas.
 * Does NOT claim packaged WebView2 budgets — those remain NOT_RUN until EXE.
 *
 * Usage:
 *   node scripts/scopes_nonpackaged_perf.mjs
 *   node scripts/scopes_nonpackaged_perf.mjs --write docs/planning/362-scopes-nonpackaged-perf.json
 */

import { writeFileSync } from "node:fs";
import { performance } from "node:perf_hooks";
import { accumulateAllScopes } from "../src/orga_drone/static/js/studio/scopes/accumulate.js";
import { createScopeFixture } from "../src/orga_drone/static/js/studio/scopes/fixtures.js";
import {
  createScopeFrameV1,
  SCOPE_SOURCE_KINDS,
  SCOPE_TAP_IDS,
} from "../src/orga_drone/static/js/studio/scopes/scope-frame.js";

const DEFAULT_SAMPLES = 7;
const SIZES = [
  { label: "preview-960x540", width: 960, height: 540, sampleFactor: 2 },
  { label: "preview-1920x1080", width: 1920, height: 1080, sampleFactor: 4 },
  { label: "fixture-color-bars", fixture: "color-bars", width: 280, height: 160 },
];

function percentile(sorted, p) {
  if (!sorted.length) return null;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[idx];
}

function stats(samplesMs) {
  const sorted = samplesMs.slice().sort((a, b) => a - b);
  const sum = sorted.reduce((a, b) => a + b, 0);
  return {
    n: sorted.length,
    min_ms: sorted[0],
    max_ms: sorted[sorted.length - 1],
    mean_ms: sum / sorted.length,
    p50_ms: percentile(sorted, 50),
    p95_ms: percentile(sorted, 95),
  };
}

function effectiveVisitCount(width, height, sampleFactor) {
  const step = Math.max(1, Math.round(Number(sampleFactor) || 1));
  let visited = 0;
  for (let y = 0; y < height; y += step) {
    for (let x = 0; x < width; x += step) visited += 1;
  }
  return { step, visited };
}

function buildRectGrayFrame(spec) {
  if (spec.fixture === "color-bars") {
    return createScopeFixture("color-bars", { width: spec.width, height: spec.height });
  }
  const channels = 4;
  const stride = spec.width * channels;
  const rgb = new Float32Array(spec.height * stride);
  for (let i = 0; i < rgb.length; i += channels) {
    rgb[i] = 0.5;
    rgb[i + 1] = 0.5;
    rgb[i + 2] = 0.5;
    rgb[i + 3] = 1;
  }
  return createScopeFrameV1({
    version: 1,
    width: spec.width,
    height: spec.height,
    stride,
    channels,
    rgb,
    profile: "bt709",
    transfer: "bt709",
    straightAlpha: true,
    legalRange: false,
    ptsNum: 0,
    ptsDen: 1,
    frameIndex: 0,
    projectId: "perf-project",
    clipId: "perf-clip",
    gradeRevision: "0",
    contextDigest: `perf:${spec.label}`,
    tapId: SCOPE_TAP_IDS.FIXTURE,
    roi: { x: 0, y: 0, width: spec.width, height: spec.height },
    sampleFactor: spec.sampleFactor || 1,
    sourceKind: SCOPE_SOURCE_KINDS.FIXTURE,
    fixtureId: "gray",
  });
}

function heapSnapshot() {
  const usage = process.memoryUsage();
  return {
    heap_used_bytes: usage.heapUsed,
    heap_total_bytes: usage.heapTotal,
    rss_bytes: usage.rss,
    external_bytes: usage.external,
  };
}

function measureCase(spec, sampleCount) {
  const frame = buildRectGrayFrame(spec);
  const bufferBytes = frame.rgb.byteLength;
  const sampleFactor = spec.sampleFactor || 1;
  const visits = effectiveVisitCount(spec.width, spec.height, sampleFactor);
  const cold = [];
  const warm = [];
  const heapDeltas = [];
  const options = {
    waveform: { columns: 256, rows: 256 },
    parade: { columns: 256, rows: 256 },
    vectorscope: { size: 256 },
  };

  if (typeof globalThis.gc === "function") globalThis.gc();
  const heapBeforeCase = heapSnapshot();

  for (let i = 0; i < sampleCount; i += 1) {
    const before = process.memoryUsage().heapUsed;
    const t0 = performance.now();
    const result = accumulateAllScopes(frame, options);
    const t1 = performance.now();
    const after = process.memoryUsage().heapUsed;
    cold.push(t1 - t0);
    heapDeltas.push(after - before);
    if (!result.histogram) throw new Error("missing histogram");
  }

  for (let i = 0; i < sampleCount; i += 1) {
    const t0 = performance.now();
    accumulateAllScopes(frame, options);
    const t1 = performance.now();
    warm.push(t1 - t0);
  }

  const heapAfterCase = heapSnapshot();
  const sortedDeltas = heapDeltas.slice().sort((a, b) => a - b);

  return {
    label: spec.label,
    width: spec.width,
    height: spec.height,
    sampleFactor,
    effective_pixels: visits.visited,
    sample_step: visits.step,
    buffer_bytes: bufferBytes,
    buffer_mib: Number((bufferBytes / (1024 * 1024)).toFixed(3)),
    cold: stats(cold),
    warm: stats(warm),
    memory: {
      input_buffer_bytes: bufferBytes,
      heap_before_bytes: heapBeforeCase.heap_used_bytes,
      heap_after_bytes: heapAfterCase.heap_used_bytes,
      heap_delta_bytes: heapAfterCase.heap_used_bytes - heapBeforeCase.heap_used_bytes,
      rss_after_bytes: heapAfterCase.rss_bytes,
      per_accumulate_heap_delta_bytes: {
        n: sortedDeltas.length,
        min: sortedDeltas[0],
        max: sortedDeltas[sortedDeltas.length - 1],
        p50: percentile(sortedDeltas, 50),
        p95: percentile(sortedDeltas, 95),
      },
    },
  };
}

export function runScopesNonpackagedPerf({ samples = DEFAULT_SAMPLES, sizes = SIZES } = {}) {
  const cases = sizes.map((spec) => measureCase(spec, samples));
  return {
    harness: "scopes_nonpackaged_perf",
    issues: ["#362", "#366"],
    environment: {
      runtime: "node",
      node: process.version,
      platform: process.platform,
      arch: process.arch,
      packaged_webview2: false,
    },
    samples_per_phase: samples,
    measured_at: new Date().toISOString(),
    cases,
    limitations: [
      "Node synthetic ScopeFrameV1 only — not packaged WebView2 / Chromium GPU path",
      "Does not include JPEG decode, preview-frame fetch, or panel canvas paint",
      "Memory = process.memoryUsage() heapUsed/RSS deltas around accumulate; not WebView2 process budgets",
      "sampleFactor steps x/y once — preview-960x540@2 and preview-1920x1080@4 visit ~same effective pixels",
      "Cold/warm are sequential halves of the same loop (not isolated JIT/GC warmup); warm p95 may exceed cold",
      "Packaged latency/memory remain NOT_RUN until EXE verification phase",
    ],
  };
}

function parseArgs(argv) {
  const out = { write: null, samples: DEFAULT_SAMPLES };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--write") out.write = argv[++i];
    if (argv[i] === "--samples") out.samples = Number(argv[++i]) || DEFAULT_SAMPLES;
  }
  return out;
}

const isMain =
  process.argv[1] && process.argv[1].replace(/\\/g, "/").endsWith("scopes_nonpackaged_perf.mjs");
if (isMain) {
  const args = parseArgs(process.argv.slice(2));
  const report = runScopesNonpackagedPerf({ samples: args.samples });
  const text = `${JSON.stringify(report, null, 2)}\n`;
  if (args.write) {
    writeFileSync(args.write, text, "utf8");
    console.error(`wrote ${args.write}`);
  }
  process.stdout.write(text);
}
