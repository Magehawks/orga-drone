/** Shared grade HTTP helpers for Color Workspace (#361/#363). */

export async function fetchGrade(studioId) {
  const response = await fetch(`/api/studio/${studioId}/grade`, {
    headers: { Accept: "application/json" },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data?.detail?.message || data?.detail || "grade fetch failed");
    error.status = response.status;
    error.code = data?.detail?.code;
    throw error;
  }
  return data;
}

export async function wrapGrade(studioId) {
  const response = await fetch(`/api/studio/${studioId}/grade/wrap`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data?.detail?.message || data?.detail || "grade wrap failed");
    error.status = response.status;
    error.code = data?.detail?.code;
    throw error;
  }
  return data;
}

export async function convertManagedGrade(studioId, { acknowledge = true } = {}) {
  const response = await fetch(`/api/studio/${studioId}/grade/convert-managed`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ acknowledge_appearance_change: Boolean(acknowledge) }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data?.detail?.message || data?.detail || "managed convert failed");
    error.status = response.status;
    error.code = data?.detail?.code;
    throw error;
  }
  return data;
}

export async function putGrade(studioId, { grade, expectedRevision, extras = {} }) {
  const response = await fetch(`/api/studio/${studioId}/grade`, {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...extras,
      grade,
      expected_revision: expectedRevision,
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data?.detail?.message || data?.detail || "grade save failed");
    error.status = response.status;
    error.code = data?.detail?.code;
    throw error;
  }
  return data;
}

export function findStep(grade, type) {
  const steps = Array.isArray(grade?.steps) ? grade.steps : [];
  return steps.find((step) => step && step.type === type) || null;
}

export function upsertPrimariesStep(grade, params) {
  const next = structuredClone(grade || {});
  if (!Array.isArray(next.steps)) next.steps = [];
  let step = next.steps.find((entry) => entry.type === "primaries-v1");
  if (!step) {
    step = {
      id: `primaries-${Date.now().toString(36)}`,
      type: "primaries-v1",
      enabled: true,
      mix: 1,
      selection_id: null,
      params: {},
    };
    next.steps.push(step);
  }
  step.enabled = true;
  step.params = { ...step.params, ...params };
  return next;
}

export function neutralPrimariesParams() {
  return {
    exposure: 0,
    kelvin: 6500,
    tint: 0,
    contrast: 1,
    pivot: 0.18,
    saturation: 1,
    blacks: 0,
    shadows: 0,
    highlights: 0,
    whites: 0,
  };
}

export function neutralWheelsParams() {
  return { lift: 0, gamma: 1, gain: 1, offset: 0 };
}

export function neutralManagedHslParams() {
  return { hue: 0, saturation: 1, lightness: 0 };
}

export const IDENTITY_CURVE = [
  [0, 0],
  [1, 1],
];

export const IDENTITY_HUE_OFFSET_CURVE = [
  [0, 0],
  [360, 0],
];

export const IDENTITY_HUE_MULT_CURVE = [
  [0, 1],
  [360, 1],
];

export const CURVE_STEP_TYPES = [
  "rgb-curves-v1",
  "luma-curve-v1",
  "hue-vs-hue-v1",
  "hue-vs-saturation-v1",
  "hue-vs-luma-v1",
  "luma-vs-saturation-v1",
  "saturation-vs-saturation-v1",
];

export function neutralCurveParams(type) {
  if (type === "rgb-curves-v1") {
    return {
      domain: "linear-bt709",
      master: IDENTITY_CURVE.map((point) => [...point]),
      red: IDENTITY_CURVE.map((point) => [...point]),
      green: IDENTITY_CURVE.map((point) => [...point]),
      blue: IDENTITY_CURVE.map((point) => [...point]),
    };
  }
  if (type === "luma-curve-v1" || type === "saturation-vs-saturation-v1") {
    return { curve: IDENTITY_CURVE.map((point) => [...point]) };
  }
  if (type === "luma-vs-saturation-v1") {
    return {
      curve: [
        [0, 1],
        [1, 1],
      ],
    };
  }
  if (type === "hue-vs-saturation-v1") {
    return { curve: IDENTITY_HUE_MULT_CURVE.map((point) => [...point]) };
  }
  return { curve: IDENTITY_HUE_OFFSET_CURVE.map((point) => [...point]) };
}

export function upsertTypedStep(grade, type, params, neutrals = {}) {
  const next = structuredClone(grade || {});
  if (!Array.isArray(next.steps)) next.steps = [];
  let step = next.steps.find((entry) => entry.type === type);
  if (!step) {
    step = {
      id: `${type}-${Date.now().toString(36)}`,
      type,
      enabled: true,
      mix: 1,
      selection_id: null,
      params: {},
    };
    next.steps.push(step);
  }
  step.enabled = true;
  step.params = { ...neutrals, ...step.params, ...params };
  return next;
}

export function upsertWheelsStep(grade, params) {
  return upsertTypedStep(grade, "wheels-v1", params, neutralWheelsParams());
}

export function upsertManagedHslStep(grade, params) {
  return upsertTypedStep(grade, "managed-hsl-v1", params, neutralManagedHslParams());
}

export function upsertCurveStep(grade, type, params) {
  if (!CURVE_STEP_TYPES.includes(type)) {
    throw new Error(`unsupported curve type: ${type}`);
  }
  return upsertTypedStep(grade, type, params, neutralCurveParams(type));
}

export function emptySelection(id) {
  return {
    id: id || `sel-${Date.now().toString(36)}`,
    mask: { combine: "union", leaves: [] },
    qualifier: null,
    invert: false,
  };
}

export function linearLeaf({ start = [0.5, 0], end = [0.5, 1], feather = 0.05 } = {}) {
  return { type: "linear", start, end, feather };
}

export function radialLeaf({ center = [0.5, 0.5], axes = [0.25, 0.25], feather = 0.05 } = {}) {
  return { type: "radial", center, axes, feather };
}

export function brushLeaf({
  points = [
    [0.4, 0.5],
    [0.6, 0.5],
  ],
  radius = 0.08,
  hardness = 0.5,
  pressure = 1,
} = {}) {
  return {
    type: "brush",
    combine: "union",
    strokes: [{ points, radius, hardness, pressure }],
  };
}

export function upsertSelection(grade, selection) {
  const next = structuredClone(grade || {});
  if (!Array.isArray(next.selections)) next.selections = [];
  const index = next.selections.findIndex((entry) => entry.id === selection.id);
  if (index >= 0) next.selections[index] = selection;
  else next.selections.push(selection);
  return next;
}

export function bindStepSelection(grade, stepType, selectionId) {
  const next = structuredClone(grade || {});
  if (!Array.isArray(next.steps)) next.steps = [];
  const step = next.steps.find((entry) => entry.type === stepType);
  if (!step) {
    throw new Error(`step not found: ${stepType}`);
  }
  step.selection_id = selectionId;
  return next;
}

export async function sampleEyedropper(
  studioId,
  { u, v, t_s = 0, expectedRevision, neighborhood = 0.01, domain = "srgb" } = {}
) {
  const response = await fetch(`/api/studio/${studioId}/grade/eyedropper`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      u,
      v,
      t_s,
      neighborhood,
      domain,
      expected_revision: expectedRevision,
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(
      data?.detail?.message || data?.detail || "eyedropper sample failed"
    );
    error.status = response.status;
    error.code = data?.detail?.code;
    throw error;
  }
  return data;
}

/** Pick a suggested qualifier object from an eyedropper sample payload. */
export function qualifierFromSample(sample, kind = "rgb") {
  const suggested = sample?.suggested?.[kind] || sample?.sample?.suggested?.[kind];
  if (!suggested) {
    throw new Error(`no suggested ${kind} qualifier on sample`);
  }
  return structuredClone(suggested);
}
