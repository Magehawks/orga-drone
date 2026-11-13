/** Managed-sdr GPU capability probe for the existing WebGL LUT adapter (#360). */

export const MANAGED_GPU_ADAPTER_VERSION = "managed-sdr-webgl-bake-v2-tetrahedral";

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

/**
 * Inspect a managed grade document and report WebGL coverage.
 * Spatial selections and unknown ops are never silently approximated.
 */
export function probeManagedGpuCapabilities(gradeDoc) {
  const grade = gradeDoc?.grade || gradeDoc;
  if (!grade || gradeDoc?.evaluator !== "managed-sdr-v1") {
    return {
      adapter: MANAGED_GPU_ADAPTER_VERSION,
      supported: false,
      mode: "none",
      reasons: ["not-managed-sdr"],
      unsupported: [],
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
    };
  }
  if (hasSpatial || unsupported.length) {
    return {
      adapter: MANAGED_GPU_ADAPTER_VERSION,
      supported: false,
      mode: "cpu-fallback",
      reasons: hasSpatial ? ["spatial-selection"] : ["unsupported-op"],
      unsupported: [...new Set(unsupported)],
    };
  }
  return {
    adapter: MANAGED_GPU_ADAPTER_VERSION,
    supported: true,
    // Preview samples tetrahedrally (#360) but RGBA8 3D textures still
    // quantize table values. Export/CPU float remain the exact reference.
    mode: "webgl-bake-tetrahedral",
    exact: false,
    interpolation: "tetrahedral",
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
