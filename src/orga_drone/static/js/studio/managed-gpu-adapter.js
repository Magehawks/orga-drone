/** Managed-sdr GPU capability probe for the existing WebGL LUT adapter (#360). */

import {
  LUT_PRECISION_RGBA16F,
  LUT_PRECISION_RGBA32F,
  LUT_PRECISION_RGBA8,
} from "./lut-webgl-precision.js";

export const MANAGED_GPU_ADAPTER_VERSION = "managed-sdr-webgl-bake-v3-precision-gated";

const LUT_BAKEABLE = new Set([
  "primaries-v1",
  "rgb-curves-v1",
  "luma-curve-v1",
  "hue-vs-hue-v1",
  "hue-vs-saturation-v1",
  "hue-vs-luma-v1",
  "luma-vs-saturation-v1",
  "saturation-vs-saturation-v1",
  "wheels-v1",
  "managed-hsl-v1",
  "creative-lut-v1",
]);

/** Only RGBA32F meets the float operator gate (≤1e-5). RGBA16F is higher
 * precision than RGBA8 but half-float lattice error exceeds that gate. */
const EXACT_FLOAT_PRECISIONS = new Set([LUT_PRECISION_RGBA32F]);

/**
 * Inspect a managed grade document and report WebGL coverage.
 * Spatial selections and unknown ops are never silently approximated.
 *
 * @param {object} gradeDoc
 * @param {{ lutPrecision?: string }=} [options]
 *   Runtime WebGL LUT storage precision from the renderer probe. When omitted,
 *   assume RGBA8 (conservative exact:false). Float precision is required before
 *   claiming operator-exact GPU parity (≤1e-5 vs CPU tetrahedral).
 */
export function probeManagedGpuCapabilities(gradeDoc, options = {}) {
  const lutPrecision = String(options.lutPrecision || LUT_PRECISION_RGBA8);
  const grade = gradeDoc?.grade || gradeDoc;
  if (!grade || gradeDoc?.evaluator !== "managed-sdr-v1") {
    return {
      adapter: MANAGED_GPU_ADAPTER_VERSION,
      supported: false,
      mode: "none",
      reasons: ["not-managed-sdr"],
      unsupported: [],
      lutPrecision,
    };
  }
  const unsupported = [];
  const steps = Array.isArray(grade.steps) ? grade.steps : [];
  let hasSpatial = false;
  let hasEnabled = false;
  for (const step of steps) {
    if (!step || step.enabled === false) continue;
    hasEnabled = true;
    const type = String(step.type || "");
    if (step.selection_id) {
      hasSpatial = true;
      unsupported.push(`spatial:${type || step.id || "step"}`);
    }
    if (!LUT_BAKEABLE.has(type)) {
      unsupported.push(`op:${type || "unknown"}`);
    }
    if (Array.isArray(grade.animation) && grade.animation.length) {
      unsupported.push("animation");
    }
  }
  if (!hasEnabled) {
    return {
      adapter: MANAGED_GPU_ADAPTER_VERSION,
      supported: true,
      mode: "identity",
      reasons: [],
      unsupported: [],
      lutPrecision,
      exact: true,
    };
  }
  if (hasSpatial || unsupported.length) {
    return {
      adapter: MANAGED_GPU_ADAPTER_VERSION,
      supported: false,
      mode: "cpu-fallback",
      reasons: hasSpatial ? ["spatial-selection"] : ["unsupported-op"],
      unsupported: [...new Set(unsupported)],
      lutPrecision,
      exact: true,
    };
  }
  if (EXACT_FLOAT_PRECISIONS.has(lutPrecision)) {
    return {
      adapter: MANAGED_GPU_ADAPTER_VERSION,
      supported: true,
      mode: "webgl-bake-tetrahedral",
      exact: true,
      interpolation: "tetrahedral",
      lutPrecision: LUT_PRECISION_RGBA32F,
      reasons: [],
      unsupported: [],
    };
  }
  if (lutPrecision === LUT_PRECISION_RGBA16F) {
    return {
      adapter: MANAGED_GPU_ADAPTER_VERSION,
      supported: true,
      mode: "webgl-bake-tetrahedral",
      exact: false,
      interpolation: "tetrahedral",
      lutPrecision: LUT_PRECISION_RGBA16F,
      reasons: ["rgba16f-quantization"],
      unsupported: [],
    };
  }
  return {
    adapter: MANAGED_GPU_ADAPTER_VERSION,
    supported: true,
    // Tetrahedral sampling is exact; RGBA8 table storage is not. Export/CPU
    // float remain the reference when the runtime cannot upload float LUTs.
    mode: "webgl-bake-tetrahedral",
    exact: false,
    interpolation: "tetrahedral",
    lutPrecision: LUT_PRECISION_RGBA8,
    reasons: ["rgba8-quantization"],
    unsupported: [],
  };
}

/** Modes that may drive the existing WebGL LUT bake preview path. */
export function isManagedWebglBakeMode(mode) {
  return mode === "webgl-bake" || mode === "webgl-bake-approx" || mode === "webgl-bake-tetrahedral";
}

export function managedBakeUrl(studioId, revision) {
  if (!studioId) return "";
  const rev =
    revision === null || revision === undefined
      ? ""
      : `?rev=${encodeURIComponent(String(revision))}`;
  return `/api/studio/${encodeURIComponent(String(studioId))}/grade/bake.cube${rev}`;
}
