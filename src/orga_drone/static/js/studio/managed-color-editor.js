/** Managed Color Workspace primaries editor (#361). */

import {
  beginRequestToken,
  isCurrentRequestToken,
  shouldRefreshColorInspector,
} from "./color-workspace.js";
import {
  convertManagedGrade,
  fetchGrade,
  findStep,
  neutralPrimariesParams,
  putGrade,
  upsertPrimariesStep,
  wrapGrade,
} from "./grade-api.js";

function numberFromInput(input, fallback) {
  const value = Number(input?.value);
  return Number.isFinite(value) ? value : fallback;
}

function bindValueLabel(input, label, format) {
  if (!input || !label) return;
  const paint = () => {
    label.textContent = format(numberFromInput(input, 0));
  };
  input.addEventListener("input", paint);
  paint();
}

export function createManagedColorEditor({
  panel,
  getSelectedStudioId,
  onChanged,
  confirmConvert,
  messages = {},
}) {
  if (!panel) {
    return { fill() {}, reset() {} };
  }
  const status = panel.querySelector("[data-managed-color-status]");
  const wrapBtn = panel.querySelector("[data-managed-color-wrap]");
  const convertBtn = panel.querySelector("[data-managed-color-convert]");
  const resetBtn = panel.querySelector("[data-managed-color-reset]");
  const fields = {
    exposure: panel.querySelector("[data-managed-exposure]"),
    kelvin: panel.querySelector("[data-managed-kelvin]"),
    tint: panel.querySelector("[data-managed-tint]"),
    contrast: panel.querySelector("[data-managed-contrast]"),
    pivot: panel.querySelector("[data-managed-pivot]"),
    saturation: panel.querySelector("[data-managed-saturation]"),
    blacks: panel.querySelector("[data-managed-blacks]"),
    shadows: panel.querySelector("[data-managed-shadows]"),
    highlights: panel.querySelector("[data-managed-highlights]"),
    whites: panel.querySelector("[data-managed-whites]"),
  };
  const labels = {
    exposure: panel.querySelector("[data-managed-exposure-value]"),
    kelvin: panel.querySelector("[data-managed-kelvin-value]"),
    tint: panel.querySelector("[data-managed-tint-value]"),
    contrast: panel.querySelector("[data-managed-contrast-value]"),
    pivot: panel.querySelector("[data-managed-pivot-value]"),
    saturation: panel.querySelector("[data-managed-saturation-value]"),
    blacks: panel.querySelector("[data-managed-blacks-value]"),
    shadows: panel.querySelector("[data-managed-shadows-value]"),
    highlights: panel.querySelector("[data-managed-highlights-value]"),
    whites: panel.querySelector("[data-managed-whites-value]"),
  };

  let current = null;
  let currentId = null;
  let saveTimer = 0;
  let busy = false;
  const tokens = new Map();

  bindValueLabel(fields.exposure, labels.exposure, (v) => `${v.toFixed(2)} EV`);
  bindValueLabel(fields.kelvin, labels.kelvin, (v) => `${Math.round(v)} K`);
  bindValueLabel(fields.tint, labels.tint, (v) => `${Math.round(v)}`);
  bindValueLabel(fields.contrast, labels.contrast, (v) => v.toFixed(2));
  bindValueLabel(fields.pivot, labels.pivot, (v) => v.toFixed(3));
  bindValueLabel(fields.saturation, labels.saturation, (v) => v.toFixed(2));
  bindValueLabel(fields.blacks, labels.blacks, (v) => `${Math.round(v)}`);
  bindValueLabel(fields.shadows, labels.shadows, (v) => `${Math.round(v)}`);
  bindValueLabel(fields.highlights, labels.highlights, (v) => `${Math.round(v)}`);
  bindValueLabel(fields.whites, labels.whites, (v) => `${Math.round(v)}`);

  function setStatus(message) {
    if (status) status.textContent = message || "";
  }

  function setEnabled(enabled) {
    Object.values(fields).forEach((input) => {
      if (input) input.disabled = !enabled || busy;
    });
    if (resetBtn) resetBtn.disabled = !enabled || busy;
  }

  function paintParams(params) {
    const values = { ...neutralPrimariesParams(), ...params };
    Object.entries(fields).forEach(([key, input]) => {
      if (!input) return;
      input.value = String(values[key]);
      input.dispatchEvent(new Event("input"));
    });
  }

  function readParams() {
    return {
      exposure: numberFromInput(fields.exposure, 0),
      kelvin: numberFromInput(fields.kelvin, 6500),
      tint: numberFromInput(fields.tint, 0),
      contrast: numberFromInput(fields.contrast, 1),
      pivot: numberFromInput(fields.pivot, 0.18),
      saturation: numberFromInput(fields.saturation, 1),
      blacks: numberFromInput(fields.blacks, 0),
      shadows: numberFromInput(fields.shadows, 0),
      highlights: numberFromInput(fields.highlights, 0),
      whites: numberFromInput(fields.whites, 0),
    };
  }

  function selectedStillCurrent(studioId) {
    return shouldRefreshColorInspector({
      clipId: studioId,
      selectedId: getSelectedStudioId?.(),
      requestCurrent: true,
    });
  }

  async function fill() {
    clearTimeout(saveTimer);
    saveTimer = 0;
    const studioId = getSelectedStudioId?.();
    if (!studioId) {
      current = null;
      currentId = null;
      setEnabled(false);
      setStatus("");
      return;
    }
    const token = beginRequestToken(tokens, studioId);
    try {
      const payload = await fetchGrade(studioId);
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (!selectedStillCurrent(studioId)) return;
      current = payload;
      currentId = String(studioId);
      const managed = current.evaluator === "managed-sdr-v1";
      setEnabled(managed);
      if (wrapBtn) {
        wrapBtn.hidden = current.authority === "canonical";
        wrapBtn.disabled = busy;
      }
      if (convertBtn) {
        convertBtn.hidden = managed;
        convertBtn.disabled = busy;
      }
      if (managed) {
        const step = findStep(current.grade, "primaries-v1");
        paintParams(step?.params || neutralPrimariesParams());
        setStatus(
          messages.managedStatus?.replace("{rev}", String(current.revision)) ||
            `managed-sdr · rev ${current.revision} · preview/export bake`
        );
      } else if (current.authority === "canonical") {
        setStatus(
          messages.wrappedStatus?.replace("{rev}", String(current.revision)) ||
            `legacy wrapper · rev ${current.revision} · Look & color locked`
        );
      } else {
        setStatus(messages.legacyStatus || "legacy color");
      }
    } catch (error) {
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (!selectedStillCurrent(studioId)) return;
      current = null;
      currentId = null;
      setEnabled(false);
      setStatus(String(error.message || error));
    }
  }

  async function savePrimaries() {
    const studioId = getSelectedStudioId?.();
    if (
      !studioId ||
      !current?.grade ||
      current.evaluator !== "managed-sdr-v1" ||
      String(currentId) !== String(studioId)
    ) {
      return;
    }
    const token = beginRequestToken(tokens, studioId);
    const expectedId = String(studioId);
    const expectedRevision = current.revision;
    const grade = upsertPrimariesStep(current.grade, readParams());
    busy = true;
    setEnabled(true);
    try {
      const payload = await putGrade(studioId, {
        grade,
        expectedRevision,
      });
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (String(getSelectedStudioId?.()) !== expectedId) return;
      current = payload;
      currentId = expectedId;
      setStatus(
        messages.managedStatus?.replace("{rev}", String(current.revision)) ||
          `managed-sdr · rev ${current.revision} · preview/export bake`
      );
      onChanged?.(current);
    } catch (error) {
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (String(getSelectedStudioId?.()) !== expectedId) return;
      setStatus(String(error.message || error));
      await fill();
    } finally {
      busy = false;
      setEnabled(current?.evaluator === "managed-sdr-v1");
    }
  }

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      void savePrimaries();
    }, 180);
  }

  Object.values(fields).forEach((input) => {
    input?.addEventListener("change", scheduleSave);
    input?.addEventListener("pointerup", scheduleSave);
  });

  wrapBtn?.addEventListener("click", async () => {
    const studioId = getSelectedStudioId?.();
    if (!studioId) return;
    const token = beginRequestToken(tokens, studioId);
    busy = true;
    try {
      const payload = await wrapGrade(studioId);
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (!selectedStillCurrent(studioId)) return;
      current = payload;
      currentId = String(studioId);
      setStatus(
        messages.wrappedStatus?.replace("{rev}", String(current.revision)) ||
          `legacy wrapper · rev ${current.revision} · Look & color locked`
      );
      onChanged?.(current);
      await fill();
    } catch (error) {
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      setStatus(String(error.message || error));
    } finally {
      busy = false;
    }
  });

  convertBtn?.addEventListener("click", async () => {
    const studioId = getSelectedStudioId?.();
    if (!studioId) return;
    const confirmText =
      messages.convertConfirm ||
      "Convert to managed Color Workspace? Appearance can change. This cannot keep exact legacy math.";
    const ok = confirmConvert
      ? await confirmConvert()
      : (globalThis.confirm || (() => false))(confirmText);
    if (!ok) return;
    const token = beginRequestToken(tokens, studioId);
    busy = true;
    try {
      const payload = await convertManagedGrade(studioId, { acknowledge: true });
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (!selectedStillCurrent(studioId)) return;
      current = payload;
      currentId = String(studioId);
      onChanged?.(current);
      await fill();
    } catch (error) {
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      setStatus(String(error.message || error));
    } finally {
      busy = false;
    }
  });

  resetBtn?.addEventListener("click", () => {
    paintParams(neutralPrimariesParams());
    scheduleSave();
  });

  return {
    fill,
    reset() {
      paintParams(neutralPrimariesParams());
    },
  };
}
