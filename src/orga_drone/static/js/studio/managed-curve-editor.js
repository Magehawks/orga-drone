/** Interactive managed curve families for Color Workspace (#354/#361). */

import { CURVE_STEP_TYPES, findStep, neutralCurveParams, postGradeCommand } from "./grade-api.js";
import {
  beginRequestToken,
  isCurrentRequestToken,
  shouldRefreshColorInspector,
} from "./color-workspace.js";

const FAMILY_META = {
  "rgb-curves-v1": {
    label: "RGB",
    channels: ["master", "red", "green", "blue"],
    xMax: 1,
    yMin: 0,
    yMax: 1,
  },
  "luma-curve-v1": {
    label: "Luma",
    channels: ["curve"],
    xMax: 1,
    yMin: 0,
    yMax: 1,
  },
  "hue-vs-hue-v1": {
    label: "Hue vs Hue",
    channels: ["curve"],
    xMax: 360,
    yMin: -180,
    yMax: 180,
  },
  "hue-vs-saturation-v1": {
    label: "Hue vs Sat",
    channels: ["curve"],
    xMax: 360,
    yMin: 0,
    yMax: 2,
  },
  "hue-vs-luma-v1": {
    label: "Hue vs Luma",
    channels: ["curve"],
    xMax: 360,
    yMin: -1,
    yMax: 1,
  },
  "luma-vs-saturation-v1": {
    label: "Luma vs Sat",
    channels: ["curve"],
    xMax: 1,
    yMin: 0,
    yMax: 2,
  },
  "saturation-vs-saturation-v1": {
    label: "Sat vs Sat",
    channels: ["curve"],
    xMax: 1,
    yMin: 0,
    yMax: 1,
  },
};

function clonePoints(points) {
  return (points || []).map((point) => [Number(point[0]), Number(point[1])]);
}

function sortPoints(points) {
  return clonePoints(points).sort((a, b) => a[0] - b[0]);
}

function validatePoints(points, meta) {
  const cleaned = sortPoints(points);
  if (cleaned.length < 2) return null;
  for (let index = 1; index < cleaned.length; index += 1) {
    if (cleaned[index][0] <= cleaned[index - 1][0]) return null;
  }
  for (const [x, y] of cleaned) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    if (x < 0 || x > meta.xMax) return null;
    if (y < meta.yMin || y > meta.yMax) return null;
  }
  if (meta.xMax === 360) {
    if (cleaned[0][0] !== 0 || cleaned[cleaned.length - 1][0] !== 360) return null;
    if (cleaned[0][1] !== cleaned[cleaned.length - 1][1]) return null;
  }
  return cleaned;
}

export function createManagedCurveEditor({ panel, getSelectedStudioId, getGrade, onChanged }) {
  if (!panel) {
    return { fill() {}, syncFromGrade() {} };
  }
  const familySelect = panel.querySelector("[data-managed-curve-family]");
  const channelSelect = panel.querySelector("[data-managed-curve-channel]");
  const svg = panel.querySelector("[data-managed-curve-svg]");
  const pathEl = panel.querySelector("[data-managed-curve-path]");
  const pointsLayer = panel.querySelector("[data-managed-curve-points]");
  const resetBtn = panel.querySelector("[data-managed-curve-reset]");
  const status = panel.querySelector("[data-managed-curve-status]");
  const width = 220;
  const height = 160;
  const pad = 8;

  let current = null;
  let currentId = null;
  let family = "rgb-curves-v1";
  let channel = "master";
  let draft = neutralCurveParams(family);
  let saveTimer = 0;
  let dragIndex = -1;
  const tokens = new Map();

  function setStatus(message) {
    if (status) status.textContent = message || "";
  }

  function meta() {
    return FAMILY_META[family];
  }

  function activePoints() {
    if (family === "rgb-curves-v1") return clonePoints(draft[channel] || IDENTITY());
    return clonePoints(draft.curve || IDENTITY());
  }

  function IDENTITY() {
    return neutralCurveParams(family)[family === "rgb-curves-v1" ? channel : "curve"];
  }

  function toSvg(point) {
    const info = meta();
    const xNorm = point[0] / info.xMax;
    const yNorm = (point[1] - info.yMin) / (info.yMax - info.yMin);
    return [pad + xNorm * (width - pad * 2), pad + (1 - yNorm) * (height - pad * 2)];
  }

  function fromSvg(clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    const localX = ((clientX - rect.left) / rect.width) * width;
    const localY = ((clientY - rect.top) / rect.height) * height;
    const info = meta();
    const xNorm = Math.min(1, Math.max(0, (localX - pad) / (width - pad * 2)));
    const yNorm = Math.min(1, Math.max(0, 1 - (localY - pad) / (height - pad * 2)));
    return [
      Number((xNorm * info.xMax).toFixed(4)),
      Number((info.yMin + yNorm * (info.yMax - info.yMin)).toFixed(4)),
    ];
  }

  function writeActivePoints(points) {
    const validated = validatePoints(points, meta());
    if (!validated) {
      setStatus("invalid curve");
      return false;
    }
    if (family === "rgb-curves-v1") draft[channel] = validated;
    else draft.curve = validated;
    return true;
  }

  function paint() {
    const points = activePoints();
    const coords = points.map(toSvg);
    if (pathEl) {
      pathEl.setAttribute(
        "d",
        coords.map((point, index) => `${index === 0 ? "M" : "L"}${point[0]},${point[1]}`).join(" ")
      );
    }
    if (pointsLayer) {
      pointsLayer.replaceChildren();
      coords.forEach((point, index) => {
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", String(point[0]));
        circle.setAttribute("cy", String(point[1]));
        circle.setAttribute("r", "5");
        circle.setAttribute("data-index", String(index));
        circle.classList.add("studio-managed-curve-handle");
        pointsLayer.appendChild(circle);
      });
    }
    if (familySelect) familySelect.value = family;
    if (channelSelect) {
      const channels = meta().channels;
      channelSelect.replaceChildren();
      channels.forEach((name) => {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        channelSelect.appendChild(option);
      });
      channelSelect.value = channel;
      channelSelect.hidden = channels.length < 2;
    }
  }

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      void save();
    }, 180);
  }

  async function save() {
    const studioId = getSelectedStudioId?.();
    // Prefer the parent grade snapshot so primaries/wheels saves cannot leave a
    // stale expected_revision on this editor.
    const gradeDoc = getGrade?.() || current;
    if (
      !studioId ||
      !gradeDoc?.grade ||
      gradeDoc.evaluator !== "managed-sdr-v1" ||
      String(currentId) !== String(studioId)
    ) {
      return;
    }
    const token = beginRequestToken(tokens, studioId);
    const expectedId = String(studioId);
    try {
      const existing = findStep(gradeDoc.grade, family);
      const payload = await postGradeCommand(studioId, {
        type: "upsert_step_params",
        expectedRevision: gradeDoc.revision,
        params: {
          step_id: existing?.id || `${family}-${Date.now().toString(36)}`,
          type: family,
          params: { ...neutralCurveParams(family), ...draft },
          enabled: true,
        },
      });
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (String(getSelectedStudioId?.()) !== expectedId) return;
      current = payload;
      currentId = expectedId;
      const step = findStep(payload.grade, family);
      draft = { ...neutralCurveParams(family), ...(step?.params || {}) };
      paint();
      setStatus(`curve saved · rev ${payload.revision}`);
      onChanged?.(payload);
    } catch (error) {
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      setStatus(String(error.message || error));
      const fresh = getGrade?.();
      if (fresh) syncFromGrade(fresh, studioId);
    }
  }

  function syncFromGrade(payload, studioId) {
    clearTimeout(saveTimer);
    current = payload || null;
    currentId = studioId ? String(studioId) : null;
    const managed = payload?.evaluator === "managed-sdr-v1";
    panel.hidden = !managed;
    if (!managed) {
      setStatus("");
      return;
    }
    const step = findStep(payload.grade, family);
    draft = { ...neutralCurveParams(family), ...(step?.params || {}) };
    if (!meta().channels.includes(channel)) channel = meta().channels[0];
    paint();
    setStatus(`curves · rev ${payload.revision}`);
  }

  function fill() {
    const studioId = getSelectedStudioId?.();
    const payload = getGrade?.();
    if (!studioId || !payload) {
      syncFromGrade(null, null);
      return;
    }
    if (
      !shouldRefreshColorInspector({
        clipId: studioId,
        selectedId: studioId,
        requestCurrent: true,
      })
    ) {
      return;
    }
    syncFromGrade(payload, studioId);
  }

  familySelect?.addEventListener("change", () => {
    family = familySelect.value;
    if (!CURVE_STEP_TYPES.includes(family)) family = "rgb-curves-v1";
    channel = meta().channels[0];
    const step = findStep(current?.grade, family);
    draft = { ...neutralCurveParams(family), ...(step?.params || {}) };
    paint();
  });

  channelSelect?.addEventListener("change", () => {
    channel = channelSelect.value;
    paint();
  });

  resetBtn?.addEventListener("click", () => {
    draft = neutralCurveParams(family);
    paint();
    scheduleSave();
  });

  pointsLayer?.addEventListener("pointerdown", (event) => {
    const handle = event.target?.closest?.("[data-index]");
    if (!handle) return;
    dragIndex = Number(handle.dataset.index);
    handle.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  });

  svg?.addEventListener("pointermove", (event) => {
    if (dragIndex < 0) return;
    const points = activePoints();
    const next = fromSvg(event.clientX, event.clientY);
    const info = meta();
    if (info.xMax === 360 && (dragIndex === 0 || dragIndex === points.length - 1)) {
      next[0] = dragIndex === 0 ? 0 : 360;
    }
    points[dragIndex] = next;
    if (info.xMax === 360 && points.length > 1) {
      points[0][1] = points[points.length - 1][1] = next[1];
    }
    if (writeActivePoints(points)) {
      paint();
    }
  });

  const endDrag = () => {
    if (dragIndex < 0) return;
    dragIndex = -1;
    scheduleSave();
  };
  svg?.addEventListener("pointerup", endDrag);
  svg?.addEventListener("pointercancel", endDrag);

  svg?.addEventListener("dblclick", (event) => {
    const points = activePoints();
    const next = fromSvg(event.clientX, event.clientY);
    points.push(next);
    if (writeActivePoints(points)) {
      paint();
      scheduleSave();
    }
  });

  paint();
  return { fill, syncFromGrade };
}
