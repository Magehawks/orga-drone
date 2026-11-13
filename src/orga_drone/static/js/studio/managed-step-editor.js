/** Serial managed grade step list: enable / mix / reorder via grade commands (#361/#363). */

import { beginRequestToken, isCurrentRequestToken } from "./color-workspace.js";
import { postGradeCommand } from "./grade-api.js";

const STEP_LABELS = {
  "primaries-v1": "Primaries",
  "wheels-v1": "Wheels",
  "managed-hsl-v1": "Managed HSL",
  "rgb-curves-v1": "RGB curves",
  "luma-curve-v1": "Luma curve",
  "hue-vs-hue-v1": "Hue vs hue",
  "hue-vs-saturation-v1": "Hue vs sat",
  "hue-vs-luma-v1": "Hue vs luma",
  "luma-vs-saturation-v1": "Luma vs sat",
  "saturation-vs-saturation-v1": "Sat vs sat",
  "creative-lut-v1": "Creative LUT",
  "input-transform-v1": "Input transform",
  "output-transform-v1": "Output transform",
  "legacy-stack-v1": "Legacy stack",
};

export function stepTypeLabel(type, labels = {}) {
  const key = String(type || "");
  return labels[key] || STEP_LABELS[key] || key || "Step";
}

/**
 * Pure reorder helper used by the UI and unit tests.
 * @param {Array<{id: string}>} steps
 * @param {string} stepId
 * @param {"up"|"down"} direction
 * @returns {string[]|null} next id order, or null when no-op / unknown
 */
export function reorderStepIds(steps, stepId, direction) {
  const ids = (Array.isArray(steps) ? steps : []).map((step) => String(step?.id || ""));
  const index = ids.indexOf(String(stepId));
  if (index < 0) return null;
  const target = direction === "up" ? index - 1 : index + 1;
  if (target < 0 || target >= ids.length) return null;
  const next = ids.slice();
  const [moved] = next.splice(index, 1);
  next.splice(target, 0, moved);
  return next;
}

export function createManagedStepEditor({
  panel,
  getSelectedStudioId,
  getGrade,
  onChanged,
  messages = {},
  labels = {},
}) {
  if (!panel) {
    return { syncFromGrade() {}, reset() {} };
  }
  const list = panel.querySelector("[data-managed-step-list]");
  const status = panel.querySelector("[data-managed-step-status]");
  const tokens = new Map();
  let busy = false;

  function setStatus(text) {
    if (status) status.textContent = text || "";
  }

  function setBusy(next) {
    busy = Boolean(next);
    panel.querySelectorAll("button, input").forEach((el) => {
      if (el instanceof HTMLInputElement || el instanceof HTMLButtonElement) {
        el.disabled = busy || el.dataset.keepDisabled === "1";
      }
    });
  }

  async function runCommand(type, params) {
    const studioId = getSelectedStudioId?.();
    const gradeDoc = getGrade?.();
    if (!studioId || !gradeDoc || gradeDoc.evaluator !== "managed-sdr-v1") return;
    const expectedRevision = gradeDoc.revision;
    const token = beginRequestToken(tokens, studioId);
    setBusy(true);
    try {
      const payload = await postGradeCommand(studioId, {
        type,
        expectedRevision,
        params,
      });
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (String(getSelectedStudioId?.()) !== String(studioId)) return;
      onChanged?.(payload);
      setStatus(
        messages.saved?.replace("{rev}", String(payload.revision)) ||
          `steps · rev ${payload.revision}`
      );
    } catch (error) {
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      setStatus(String(error.message || error));
    } finally {
      setBusy(false);
      syncFromGrade(getGrade?.(), getSelectedStudioId?.());
    }
  }

  function renderRow(step, index, total) {
    const row = document.createElement("div");
    row.className = "studio-managed-step-row";
    row.dataset.stepId = String(step.id);
    const title = document.createElement("span");
    title.className = "studio-managed-step-title";
    title.textContent = stepTypeLabel(step.type, labels);

    const enabled = document.createElement("label");
    enabled.className = "studio-managed-step-enabled";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = step.enabled !== false;
    checkbox.setAttribute("aria-label", messages.enableAria || "Enable step");
    checkbox.addEventListener("change", () => {
      void runCommand("set_step_enabled", {
        step_id: String(step.id),
        enabled: Boolean(checkbox.checked),
      });
    });
    enabled.append(checkbox, document.createTextNode(messages.enable || "On"));

    const mixLabel = document.createElement("label");
    mixLabel.className = "studio-managed-step-mix";
    const mix = document.createElement("input");
    mix.type = "range";
    mix.min = "0";
    mix.max = "1";
    mix.step = "0.01";
    mix.value = String(Number.isFinite(Number(step.mix)) ? Number(step.mix) : 1);
    mix.setAttribute("aria-label", messages.mixAria || "Step mix");
    const mixValue = document.createElement("span");
    mixValue.textContent = Number(mix.value).toFixed(2);
    mix.addEventListener("input", () => {
      mixValue.textContent = Number(mix.value).toFixed(2);
    });
    mix.addEventListener("change", () => {
      void runCommand("set_step_mix", {
        step_id: String(step.id),
        mix: Number(mix.value),
      });
    });
    mixLabel.append(mix, mixValue);

    const up = document.createElement("button");
    up.type = "button";
    up.className = "button ghost";
    up.textContent = messages.moveUp || "Move up";
    up.disabled = index === 0;
    up.addEventListener("click", () => {
      const grade = getGrade?.()?.grade;
      const next = reorderStepIds(grade?.steps, step.id, "up");
      if (!next) return;
      void runCommand("reorder_steps", { ids: next });
    });

    const down = document.createElement("button");
    down.type = "button";
    down.className = "button ghost";
    down.textContent = messages.moveDown || "Move down";
    down.disabled = index >= total - 1;
    down.addEventListener("click", () => {
      const grade = getGrade?.()?.grade;
      const next = reorderStepIds(grade?.steps, step.id, "down");
      if (!next) return;
      void runCommand("reorder_steps", { ids: next });
    });

    const actions = document.createElement("div");
    actions.className = "studio-managed-step-actions";
    actions.append(up, down);

    row.append(title, enabled, mixLabel, actions);
    return row;
  }

  function syncFromGrade(gradeDoc, studioId) {
    if (!list) return;
    list.replaceChildren();
    if (!gradeDoc || gradeDoc.evaluator !== "managed-sdr-v1" || !gradeDoc.grade) {
      setStatus(messages.unavailable || "");
      return;
    }
    if (
      studioId !== null &&
      studioId !== undefined &&
      String(getSelectedStudioId?.()) !== String(studioId)
    ) {
      return;
    }
    const steps = Array.isArray(gradeDoc.grade.steps) ? gradeDoc.grade.steps : [];
    if (!steps.length) {
      setStatus(messages.empty || "No steps yet");
      return;
    }
    steps.forEach((step, index) => {
      if (!step?.id) return;
      list.append(renderRow(step, index, steps.length));
    });
    if (!busy) {
      setStatus(
        messages.ready?.replace("{count}", String(steps.length)) || `${steps.length} steps · serial`
      );
    }
  }

  function reset() {
    list?.replaceChildren();
    setStatus("");
  }

  return { syncFromGrade, reset };
}
