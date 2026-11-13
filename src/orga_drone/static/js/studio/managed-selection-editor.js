/** Managed mask/qualifier selection editor (#356/#357). */

import { beginRequestToken, isCurrentRequestToken } from "./color-workspace.js";
import {
  bindStepSelection,
  brushLeaf,
  emptySelection,
  linearLeaf,
  putGrade,
  radialLeaf,
  upsertSelection,
} from "./grade-api.js";

function numberFromInput(input, fallback) {
  const value = Number(input?.value);
  return Number.isFinite(value) ? value : fallback;
}

export function createManagedSelectionEditor({ panel, getSelectedStudioId, getGrade, onChanged }) {
  if (!panel) {
    return { fill() {}, syncFromGrade() {} };
  }
  const status = panel.querySelector("[data-managed-selection-status]");
  const shapeSelect = panel.querySelector("[data-managed-mask-shape]");
  const featherInput = panel.querySelector("[data-managed-mask-feather]");
  const invertInput = panel.querySelector("[data-managed-selection-invert]");
  const qualifierSelect = panel.querySelector("[data-managed-qualifier-type]");
  const applyBtn = panel.querySelector("[data-managed-selection-apply]");
  const clearBtn = panel.querySelector("[data-managed-selection-clear]");
  const bindSelect = panel.querySelector("[data-managed-selection-bind]");

  let current = null;
  let currentId = null;
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
    ].forEach((el) => {
      if (el) el.disabled = !enabled;
    });
  }

  function buildQualifier() {
    const type = qualifierSelect?.value || "none";
    if (type === "none") return null;
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

  function buildLeaf() {
    const shape = shapeSelect?.value || "radial";
    const feather = numberFromInput(featherInput, 0.05);
    if (shape === "linear") return linearLeaf({ feather });
    if (shape === "brush") return brushLeaf({ radius: 0.1 + feather });
    return radialLeaf({ feather });
  }

  async function saveSelection({ clear = false } = {}) {
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
    } else {
      const existing = (grade.steps || []).find((entry) => entry.type === bindType);
      const reuseId = existing?.selection_id || null;
      const selection = emptySelection(reuseId || undefined);
      selection.mask = { combine: "union", leaves: [buildLeaf()] };
      selection.qualifier = buildQualifier();
      selection.invert = Boolean(invertInput?.checked);
      grade = upsertSelection(grade, selection);
      grade = bindStepSelection(grade, bindType, selection.id);
      // Drop unused selection resources so the 32-cap stays tidy.
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

  function syncFromGrade(payload, studioId) {
    current = payload || null;
    currentId = studioId ? String(studioId) : null;
    const managed = payload?.evaluator === "managed-sdr-v1";
    setEnabled(managed);
    if (!managed) {
      setStatus("");
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

  return { fill, syncFromGrade };
}
