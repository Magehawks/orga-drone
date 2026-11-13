/** Managed Color Workspace primaries/wheels/HSL editor (#361/#355). */

import {
  beginRequestToken,
  isCurrentRequestToken,
  shouldRefreshColorInspector,
} from "./color-workspace.js";
import {
  convertManagedGrade,
  fetchGrade,
  findStep,
  neutralManagedHslParams,
  neutralPrimariesParams,
  neutralWheelsParams,
  putGrade,
  upsertManagedHslStep,
  upsertPrimariesStep,
  upsertWheelsStep,
  wrapGrade,
} from "./grade-api.js";
import { createManagedCurveEditor } from "./managed-curve-editor.js";
import { createManagedLutEditor } from "./managed-lut-editor.js";
import { createManagedSelectionEditor } from "./managed-selection-editor.js";

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

function paintGroup(fields, values) {
  Object.entries(fields).forEach(([key, input]) => {
    if (!input || !(key in values)) return;
    input.value = String(values[key]);
    input.dispatchEvent(new Event("input"));
  });
}

export function createManagedColorEditor({
  panel,
  getSelectedStudioId,
  getPreviewMediaEl,
  getPreviewSourceTimeS,
  onChanged,
  confirmConvert,
  listLuts,
  messages = {},
}) {
  if (!panel) {
    return { fill() {}, reset() {} };
  }
  const status = panel.querySelector("[data-managed-color-status]");
  const wrapBtn = panel.querySelector("[data-managed-color-wrap]");
  const convertBtn = panel.querySelector("[data-managed-color-convert]");
  const resetBtn = panel.querySelector("[data-managed-color-reset]");
  const wheelsResetBtn = panel.querySelector("[data-managed-wheels-reset]");
  const hslResetBtn = panel.querySelector("[data-managed-hsl-reset]");
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
  const wheelFields = {
    lift: panel.querySelector("[data-managed-lift]"),
    gamma: panel.querySelector("[data-managed-gamma]"),
    gain: panel.querySelector("[data-managed-gain]"),
    offset: panel.querySelector("[data-managed-offset]"),
  };
  const hslFields = {
    hue: panel.querySelector("[data-managed-hue]"),
    saturation: panel.querySelector("[data-managed-hsl-sat]"),
    lightness: panel.querySelector("[data-managed-hsl-light]"),
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
  const curveEditor = createManagedCurveEditor({
    panel: panel.querySelector("[data-managed-curve-panel]"),
    getSelectedStudioId,
    getGrade: () => current,
    onChanged: (payload) => {
      current = payload;
      onChanged?.(payload);
    },
  });
  let lutEditor = { syncFromGrade() {} };
  const selectionEditor = createManagedSelectionEditor({
    panel: panel.querySelector("[data-managed-selection-panel]"),
    getSelectedStudioId,
    getGrade: () => current,
    getPreviewMediaEl,
    getPreviewSourceTimeS,
    messages: {
      sampling: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgSampling,
      sampledHint: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgSampled,
      sampleStale: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgSampleStale,
      eyedropperHint: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgEyedropper,
      brushHint: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgBrush,
      brushDrawing: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgBrushDrawing,
      brushCancelled: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgBrushCancelled,
      selectionSaved: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgSaved,
      selectionCleared: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgCleared,
    },
    onChanged: (payload) => {
      current = payload;
      curveEditor.syncFromGrade(payload, getSelectedStudioId?.());
      lutEditor.syncFromGrade(payload, getSelectedStudioId?.());
      onChanged?.(payload);
    },
  });
  lutEditor = createManagedLutEditor({
    panel: panel.querySelector("[data-managed-lut-panel]"),
    getSelectedStudioId,
    getGrade: () => current,
    listLuts,
    onChanged: (payload) => {
      current = payload;
      curveEditor.syncFromGrade(payload, getSelectedStudioId?.());
      selectionEditor.syncFromGrade(payload, getSelectedStudioId?.());
      onChanged?.(payload);
    },
  });

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
  bindValueLabel(wheelFields.lift, panel.querySelector("[data-managed-lift-value]"), (v) =>
    v.toFixed(2)
  );
  bindValueLabel(wheelFields.gamma, panel.querySelector("[data-managed-gamma-value]"), (v) =>
    v.toFixed(2)
  );
  bindValueLabel(wheelFields.gain, panel.querySelector("[data-managed-gain-value]"), (v) =>
    v.toFixed(2)
  );
  bindValueLabel(wheelFields.offset, panel.querySelector("[data-managed-offset-value]"), (v) =>
    v.toFixed(2)
  );
  bindValueLabel(
    hslFields.hue,
    panel.querySelector("[data-managed-hue-value]"),
    (v) => `${Math.round(v)}°`
  );
  bindValueLabel(hslFields.saturation, panel.querySelector("[data-managed-hsl-sat-value]"), (v) =>
    v.toFixed(2)
  );
  bindValueLabel(hslFields.lightness, panel.querySelector("[data-managed-hsl-light-value]"), (v) =>
    v.toFixed(2)
  );

  function setStatus(message) {
    if (status) status.textContent = message || "";
  }

  function setEnabled(enabled) {
    [...Object.values(fields), ...Object.values(wheelFields), ...Object.values(hslFields)].forEach(
      (input) => {
        if (input) input.disabled = !enabled || busy;
      }
    );
    [resetBtn, wheelsResetBtn, hslResetBtn].forEach((button) => {
      if (button) button.disabled = !enabled || busy;
    });
  }

  function readPrimaries() {
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

  function readWheels() {
    return {
      lift: numberFromInput(wheelFields.lift, 0),
      gamma: numberFromInput(wheelFields.gamma, 1),
      gain: numberFromInput(wheelFields.gain, 1),
      offset: numberFromInput(wheelFields.offset, 0),
    };
  }

  function readHsl() {
    return {
      hue: numberFromInput(hslFields.hue, 0),
      saturation: numberFromInput(hslFields.saturation, 1),
      lightness: numberFromInput(hslFields.lightness, 0),
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
        paintGroup(fields, {
          ...neutralPrimariesParams(),
          ...(findStep(current.grade, "primaries-v1")?.params || {}),
        });
        paintGroup(wheelFields, {
          ...neutralWheelsParams(),
          ...(findStep(current.grade, "wheels-v1")?.params || {}),
        });
        paintGroup(hslFields, {
          ...neutralManagedHslParams(),
          ...(findStep(current.grade, "managed-hsl-v1")?.params || {}),
        });
        setStatus(
          messages.managedStatus?.replace("{rev}", String(current.revision)) ||
            `managed-sdr · rev ${current.revision} · preview/export bake`
        );
        curveEditor.syncFromGrade(current, studioId);
        selectionEditor.syncFromGrade(current, studioId);
        lutEditor.syncFromGrade(current, studioId);
      } else if (current.authority === "canonical") {
        setStatus(
          messages.wrappedStatus?.replace("{rev}", String(current.revision)) ||
            `legacy wrapper · rev ${current.revision} · Look & color locked`
        );
        curveEditor.syncFromGrade(null, null);
        selectionEditor.syncFromGrade(null, null);
        lutEditor.syncFromGrade(null, null);
      } else {
        setStatus(messages.legacyStatus || "legacy color");
        curveEditor.syncFromGrade(null, null);
        selectionEditor.syncFromGrade(null, null);
        lutEditor.syncFromGrade(null, null);
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

  async function saveManaged() {
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
    const primaries = readPrimaries();
    const wheels = readWheels();
    const hsl = readHsl();
    let grade = current.grade;
    const hasPrimaries = Boolean(findStep(grade, "primaries-v1"));
    const hasWheels = Boolean(findStep(grade, "wheels-v1"));
    const hasHsl = Boolean(findStep(grade, "managed-hsl-v1"));
    const primariesChanged = JSON.stringify(primaries) !== JSON.stringify(neutralPrimariesParams());
    const wheelsChanged = JSON.stringify(wheels) !== JSON.stringify(neutralWheelsParams());
    const hslChanged = JSON.stringify(hsl) !== JSON.stringify(neutralManagedHslParams());
    if (hasPrimaries || primariesChanged) {
      grade = upsertPrimariesStep(grade, primaries);
    }
    if (hasWheels || wheelsChanged) {
      grade = upsertWheelsStep(grade, wheels);
    }
    if (hasHsl || hslChanged) {
      grade = upsertManagedHslStep(grade, hsl);
    }
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
      curveEditor.syncFromGrade(current, expectedId);
      selectionEditor.syncFromGrade(current, expectedId);
      lutEditor.syncFromGrade(current, expectedId);
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
      void saveManaged();
    }, 180);
  }

  [...Object.values(fields), ...Object.values(wheelFields), ...Object.values(hslFields)].forEach(
    (input) => {
      input?.addEventListener("change", scheduleSave);
      input?.addEventListener("pointerup", scheduleSave);
    }
  );

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
    paintGroup(fields, neutralPrimariesParams());
    scheduleSave();
  });
  wheelsResetBtn?.addEventListener("click", () => {
    paintGroup(wheelFields, neutralWheelsParams());
    scheduleSave();
  });
  hslResetBtn?.addEventListener("click", () => {
    paintGroup(hslFields, neutralManagedHslParams());
    scheduleSave();
  });

  return {
    fill,
    reset() {
      paintGroup(fields, neutralPrimariesParams());
      paintGroup(wheelFields, neutralWheelsParams());
      paintGroup(hslFields, neutralManagedHslParams());
    },
  };
}
