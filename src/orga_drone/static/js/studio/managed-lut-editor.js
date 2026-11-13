/** Managed creative LUT step editor (#352). */

import { beginRequestToken, isCurrentRequestToken } from "./color-workspace.js";
import { findStep, putGrade, upsertTypedStep } from "./grade-api.js";

export function upsertCreativeLutStep(grade, params) {
  return upsertTypedStep(grade, "creative-lut-v1", params, {
    asset_id: "",
    strength: 1,
    domain: "encoded-bt709",
    input_profile: "bt709",
    output_profile: "bt709",
    sha256: null,
    interpolation: "tetrahedral",
  });
}

export function createManagedLutEditor({
  panel,
  getSelectedStudioId,
  getGrade,
  onChanged,
  listLuts,
}) {
  if (!panel) {
    return { fill() {}, syncFromGrade() {} };
  }
  const status = panel.querySelector("[data-managed-lut-status]");
  const assetSelect = panel.querySelector("[data-managed-lut-asset]");
  const strengthInput = panel.querySelector("[data-managed-lut-strength]");
  const strengthLabel = panel.querySelector("[data-managed-lut-strength-value]");
  const enableInput = panel.querySelector("[data-managed-lut-enable]");
  const applyBtn = panel.querySelector("[data-managed-lut-apply]");
  const clearBtn = panel.querySelector("[data-managed-lut-clear]");

  let current = null;
  let currentId = null;
  const tokens = new Map();

  function setStatus(text) {
    if (status) status.textContent = text || "";
  }

  function setEnabled(enabled) {
    panel.hidden = !enabled;
    [assetSelect, strengthInput, enableInput, applyBtn, clearBtn].forEach((el) => {
      if (el) el.disabled = !enabled;
    });
  }

  function paintStrength() {
    if (!strengthLabel || !strengthInput) return;
    const value = Number(strengthInput.value);
    strengthLabel.textContent = Number.isFinite(value) ? value.toFixed(2) : "1.00";
  }

  async function refreshAssets(selected) {
    if (!assetSelect || !listLuts) return;
    const items = await listLuts();
    assetSelect.innerHTML = "";
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "—";
    assetSelect.appendChild(blank);
    (items || []).forEach((item) => {
      const name = item?.asset_name || item?.name || item;
      if (!name) return;
      const option = document.createElement("option");
      option.value = String(name);
      option.textContent = String(name);
      const digest = item?.content_sha256 || item?.sha256 || "";
      if (digest) option.dataset.sha256 = String(digest);
      if (item?.file_present === false) option.disabled = true;
      assetSelect.appendChild(option);
    });
    if (selected) assetSelect.value = selected;
  }

  async function save({ clear = false } = {}) {
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
    if (clear) {
      grade.steps = (grade.steps || []).filter((step) => step.type !== "creative-lut-v1");
    } else {
      const assetId = assetSelect?.value || "";
      if (!assetId) {
        setStatus("choose a .cube asset");
        return;
      }
      const strength = Number(strengthInput?.value);
      const selected = assetSelect?.selectedOptions?.[0];
      const sha256 = selected?.dataset?.sha256 || null;
      grade = upsertCreativeLutStep(grade, {
        asset_id: assetId,
        strength: Number.isFinite(strength) ? strength : 1,
        domain: "encoded-bt709",
        input_profile: "bt709",
        output_profile: "bt709",
        sha256,
      });
      const step = findStep(grade, "creative-lut-v1");
      if (step) step.enabled = enableInput ? Boolean(enableInput.checked) : true;
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
          ? `creative LUT cleared · rev ${payload.revision}`
          : `creative LUT saved · rev ${payload.revision}`
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
    const step = findStep(payload.grade, "creative-lut-v1");
    void refreshAssets(step?.params?.asset_id || "");
    if (strengthInput) strengthInput.value = String(step?.params?.strength ?? 1);
    if (enableInput) enableInput.checked = step ? step.enabled !== false : true;
    paintStrength();
    setStatus(
      step?.params?.asset_id
        ? `creative LUT · ${step.params.asset_id} · rev ${payload.revision}`
        : `no creative LUT · rev ${payload.revision}`
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

  strengthInput?.addEventListener("input", paintStrength);
  applyBtn?.addEventListener("click", () => {
    void save();
  });
  clearBtn?.addEventListener("click", () => {
    void save({ clear: true });
  });

  return { fill, syncFromGrade };
}
