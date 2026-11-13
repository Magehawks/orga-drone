/** Managed mask/qualifier selection editor (#356/#357). */

import { beginRequestToken, isCurrentRequestToken } from "./color-workspace.js";
import {
  bindStepSelection,
  brushLeaf,
  emptySelection,
  putGrade,
  qualifierFromSample,
  radialLeaf,
  linearLeaf,
  sampleEyedropper,
  upsertSelection,
} from "./grade-api.js";
import { createManagedViewerTools } from "./managed-viewer-tools.js";

function numberFromInput(input, fallback) {
  const value = Number(input?.value);
  return Number.isFinite(value) ? value : fallback;
}

export function createManagedSelectionEditor({
  panel,
  getSelectedStudioId,
  getGrade,
  onChanged,
  getPreviewMediaEl,
  getPreviewSourceTimeS,
}) {
  if (!panel) {
    return { fill() {}, syncFromGrade() {}, setViewerMode() {} };
  }
  const status = panel.querySelector("[data-managed-selection-status]");
  const shapeSelect = panel.querySelector("[data-managed-mask-shape]");
  const featherInput = panel.querySelector("[data-managed-mask-feather]");
  const invertInput = panel.querySelector("[data-managed-selection-invert]");
  const qualifierSelect = panel.querySelector("[data-managed-qualifier-type]");
  const applyBtn = panel.querySelector("[data-managed-selection-apply]");
  const clearBtn = panel.querySelector("[data-managed-selection-clear]");
  const bindSelect = panel.querySelector("[data-managed-selection-bind]");
  const eyedropperBtn = panel.querySelector("[data-managed-eyedropper]");
  const acceptBtn = panel.querySelector("[data-managed-eyedropper-accept]");
  const brushBtn = panel.querySelector("[data-managed-brush-draw]");
  const brushRadius = panel.querySelector("[data-managed-brush-radius]");
  const brushHardness = panel.querySelector("[data-managed-brush-hardness]");
  const sampleSwatch = panel.querySelector("[data-managed-eyedropper-swatch]");
  const sampleMeta = panel.querySelector("[data-managed-eyedropper-meta]");

  let current = null;
  let currentId = null;
  let pendingSample = null;
  let viewerMode = "none";
  const tokens = new Map();

  function setStatus(text) {
    if (status) status.textContent = text || "";
  }

  function setEnabled(enabled) {
    panel.hidden = !enabled;
    [
      shapeSelect,
      featherInput,
      invertInput,
      qualifierSelect,
      applyBtn,
      clearBtn,
      bindSelect,
      eyedropperBtn,
      acceptBtn,
      brushBtn,
      brushRadius,
      brushHardness,
    ].forEach((el) => {
      if (el) el.disabled = !enabled;
    });
    if (acceptBtn) acceptBtn.disabled = !enabled || !pendingSample;
  }

  function setViewerMode(mode) {
    viewerMode = mode || "none";
    panel.dataset.viewerMode = viewerMode;
    if (eyedropperBtn) {
      eyedropperBtn.setAttribute("aria-pressed", viewerMode === "eyedropper" ? "true" : "false");
    }
    if (brushBtn) {
      brushBtn.setAttribute("aria-pressed", viewerMode === "brush" ? "true" : "false");
    }
    const media = getPreviewMediaEl?.();
    if (media) {
      media.style.cursor =
        viewerMode === "eyedropper" ? "crosshair" : viewerMode === "brush" ? "cell" : "";
    }
  }

  function showSample(sample) {
    pendingSample = sample || null;
    if (acceptBtn) acceptBtn.disabled = !pendingSample || panel.hidden;
    if (!sample) {
      if (sampleSwatch) sampleSwatch.style.background = "transparent";
      if (sampleMeta) sampleMeta.textContent = "";
      return;
    }
    const rgb = sample.rgb || [0, 0, 0];
    const r = Math.round(Math.min(255, Math.max(0, rgb[0] * 255)));
    const g = Math.round(Math.min(255, Math.max(0, rgb[1] * 255)));
    const b = Math.round(Math.min(255, Math.max(0, rgb[2] * 255)));
    if (sampleSwatch) sampleSwatch.style.background = `rgb(${r}, ${g}, ${b})`;
    if (sampleMeta) {
      sampleMeta.textContent = `sample · rev ${sample.revision} · ${sample.domain} · frame ${sample.frame}`;
    }
  }

  function buildQualifier() {
    const type = qualifierSelect?.value || "none";
    if (type === "none") return null;
    if (pendingSample) {
      try {
        return qualifierFromSample(pendingSample, type === "none" ? "rgb" : type);
      } catch {
        /* fall through to presets */
      }
    }
    if (type === "rgb") {
      return {
        type: "rgb",
        channels: [
          [0.7, 0.2],
          [0.7, 0.2],
          [0.7, 0.2],
        ],
      };
    }
    if (type === "hsl") {
      return { type: "hsl", hue: [20, 50], saturation: [0.4, 0.05], lightness: [0.55, 0.1] };
    }
    return { type: "luma", inner: 0.65, outer: 0.15 };
  }

  function buildLeaf(stroke) {
    const shape = shapeSelect?.value || "radial";
    const feather = numberFromInput(featherInput, 0.05);
    if (stroke) {
      return brushLeaf({
        points: stroke.points,
        radius: stroke.radius,
        hardness: stroke.hardness,
        pressure: stroke.pressure,
      });
    }
    if (shape === "linear") return linearLeaf({ feather });
    if (shape === "brush") {
      return brushLeaf({
        radius: numberFromInput(brushRadius, 0.08),
        hardness: numberFromInput(brushHardness, 0.5),
      });
    }
    return radialLeaf({ feather });
  }

  async function saveSelection({ clear = false, stroke = null } = {}) {
    const studioId = getSelectedStudioId?.();
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
    let grade = structuredClone(gradeDoc.grade);
    const bindType = bindSelect?.value || "primaries-v1";
    if (clear) {
      const step = (grade.steps || []).find((entry) => entry.type === bindType);
      if (step) step.selection_id = null;
      grade.selections = (grade.selections || []).filter((entry) => {
        const used = (grade.steps || []).some((s) => s.selection_id === entry.id);
        return used;
      });
      showSample(null);
    } else {
      const existing = (grade.steps || []).find((entry) => entry.type === bindType);
      const reuseId = existing?.selection_id || null;
      const selection = emptySelection(reuseId || undefined);
      selection.mask = { combine: "union", leaves: [buildLeaf(stroke)] };
      selection.qualifier = buildQualifier();
      selection.invert = Boolean(invertInput?.checked);
      grade = upsertSelection(grade, selection);
      grade = bindStepSelection(grade, bindType, selection.id);
      const used = new Set((grade.steps || []).map((step) => step.selection_id).filter(Boolean));
      grade.selections = (grade.selections || []).filter((entry) => used.has(entry.id));
    }
    try {
      const payload = await putGrade(studioId, {
        grade,
        expectedRevision: gradeDoc.revision,
      });
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (String(getSelectedStudioId?.()) !== expectedId) return;
      current = payload;
      currentId = expectedId;
      setStatus(
        clear
          ? `selection cleared · rev ${payload.revision}`
          : `selection saved · rev ${payload.revision}`
      );
      onChanged?.(payload);
    } catch (error) {
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      setStatus(String(error.message || error));
      const fresh = getGrade?.();
      if (fresh) syncFromGrade(fresh, studioId);
    }
  }

  async function runEyedropper(uv) {
    const studioId = getSelectedStudioId?.();
    const gradeDoc = getGrade?.() || current;
    if (!studioId || !gradeDoc || gradeDoc.evaluator !== "managed-sdr-v1") return;
    const token = beginRequestToken(tokens, `eye-${studioId}`);
    setStatus("sampling…");
    try {
      const data = await sampleEyedropper(studioId, {
        u: uv.u,
        v: uv.v,
        t_s: Number(getPreviewSourceTimeS?.() || 0),
        expectedRevision: gradeDoc.revision,
      });
      if (!isCurrentRequestToken(tokens, `eye-${studioId}`, token)) return;
      showSample(data.sample);
      if (qualifierSelect && qualifierSelect.value === "none") {
        qualifierSelect.value = "rgb";
      }
      setStatus(`sampled · accept to apply qualifier · rev ${data.sample.revision}`);
      setViewerMode("none");
    } catch (error) {
      if (!isCurrentRequestToken(tokens, `eye-${studioId}`, token)) return;
      showSample(null);
      setStatus(String(error.message || error));
    }
  }

  function syncFromGrade(payload, studioId) {
    current = payload || null;
    currentId = studioId ? String(studioId) : null;
    const managed = payload?.evaluator === "managed-sdr-v1";
    setEnabled(managed);
    if (!managed) {
      setStatus("");
      showSample(null);
      setViewerMode("none");
      return;
    }
    const bound = (payload.grade?.steps || []).find((step) => step.selection_id);
    const selection = (payload.grade?.selections || []).find(
      (entry) => entry.id === bound?.selection_id
    );
    if (invertInput) invertInput.checked = Boolean(selection?.invert);
    if (selection?.mask?.leaves?.[0]?.type && shapeSelect) {
      shapeSelect.value = selection.mask.leaves[0].type;
    }
    if (selection?.qualifier?.type && qualifierSelect) {
      qualifierSelect.value = selection.qualifier.type;
    } else if (qualifierSelect) {
      qualifierSelect.value = "none";
    }
    setStatus(
      selection
        ? `selection · ${selection.id} · rev ${payload.revision}`
        : `no selection · rev ${payload.revision}`
    );
  }

  function fill() {
    const studioId = getSelectedStudioId?.();
    const payload = getGrade?.();
    if (!studioId || !payload) {
      syncFromGrade(null, null);
      return;
    }
    syncFromGrade(payload, studioId);
  }

  applyBtn?.addEventListener("click", () => {
    void saveSelection();
  });
  clearBtn?.addEventListener("click", () => {
    void saveSelection({ clear: true });
  });
  eyedropperBtn?.addEventListener("click", () => {
    setViewerMode(viewerMode === "eyedropper" ? "none" : "eyedropper");
    setStatus(viewerMode === "eyedropper" ? "eyedropper: click the preview" : "");
  });
  brushBtn?.addEventListener("click", () => {
    if (shapeSelect) shapeSelect.value = "brush";
    setViewerMode(viewerMode === "brush" ? "none" : "brush");
    setStatus(viewerMode === "brush" ? "brush: draw on the preview" : "");
  });
  acceptBtn?.addEventListener("click", () => {
    if (!pendingSample) return;
    void saveSelection();
  });

  const media = getPreviewMediaEl?.();
  const tools = createManagedViewerTools({
    mediaEl: media,
    getMode: () => viewerMode,
    getBrushSettings: () => ({
      radius: numberFromInput(brushRadius, 0.08),
      hardness: numberFromInput(brushHardness, 0.5),
      pressure: 1,
    }),
    onEyedropperSample: (uv) => runEyedropper(uv),
    onBrushStrokeComplete: (stroke) => {
      void saveSelection({ stroke });
      setViewerMode("none");
    },
    onStatus: setStatus,
  });

  return {
    fill,
    syncFromGrade,
    setViewerMode,
    destroy() {
      tools.destroy();
    },
  };
}
