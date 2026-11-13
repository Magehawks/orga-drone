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
