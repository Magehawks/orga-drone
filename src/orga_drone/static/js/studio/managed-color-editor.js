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
  postGradeCommand,
  wrapGrade,
} from "./grade-api.js";
import { createManagedCurveEditor } from "./managed-curve-editor.js";
import { createManagedLutEditor } from "./managed-lut-editor.js";
import { createManagedSelectionEditor } from "./managed-selection-editor.js";
import { createManagedStepEditor } from "./managed-step-editor.js";
import { createPreviewTokenStore, contextDigestFromParts } from "./preview-token.js";
import { bindSliderNumberPair } from "./slider-number-sync.js";

function numberFromInput(input, fallback) {
  const value = Number(input?.value);
  return Number.isFinite(value) ? value : fallback;
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
  const primaryNumberFields = {
    exposure: panel.querySelector("[data-managed-exposure-number]"),
    kelvin: panel.querySelector("[data-managed-kelvin-number]"),
    tint: panel.querySelector("[data-managed-tint-number]"),
    contrast: panel.querySelector("[data-managed-contrast-number]"),
    pivot: panel.querySelector("[data-managed-pivot-number]"),
    saturation: panel.querySelector("[data-managed-saturation-number]"),
    blacks: panel.querySelector("[data-managed-blacks-number]"),
    shadows: panel.querySelector("[data-managed-shadows-number]"),
    highlights: panel.querySelector("[data-managed-highlights-number]"),
    whites: panel.querySelector("[data-managed-whites-number]"),
  };
  const wheelFields = {
    lift: panel.querySelector("[data-managed-lift]"),
    gamma: panel.querySelector("[data-managed-gamma]"),
    gain: panel.querySelector("[data-managed-gain]"),
    offset: panel.querySelector("[data-managed-offset]"),
  };
  const wheelNumberFields = {
    lift: panel.querySelector("[data-managed-lift-number]"),
    gamma: panel.querySelector("[data-managed-gamma-number]"),
    gain: panel.querySelector("[data-managed-gain-number]"),
    offset: panel.querySelector("[data-managed-offset-number]"),
  };
  const hslFields = {
    hue: panel.querySelector("[data-managed-hue]"),
    saturation: panel.querySelector("[data-managed-hsl-sat]"),
    lightness: panel.querySelector("[data-managed-hsl-light]"),
  };
  const hslNumberFields = {
    hue: panel.querySelector("[data-managed-hue-number]"),
    saturation: panel.querySelector("[data-managed-hsl-sat-number]"),
    lightness: panel.querySelector("[data-managed-hsl-light-number]"),
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
  const previewTokens = createPreviewTokenStore();
  const curveEditor = createManagedCurveEditor({
    panel: panel.querySelector("[data-managed-curve-panel]"),
    getSelectedStudioId,
    getGrade: () => current,
    onChanged: (payload) => {
      current = payload;
      stepEditor.syncFromGrade(payload, getSelectedStudioId?.());
      onChanged?.(payload);
    },
  });
  let lutEditor = { syncFromGrade() {} };
  let stepEditor = { syncFromGrade() {}, reset() {} };
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
      sampleMeta: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgSampleMeta,
      eyedropperHint: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgEyedropper,
      objectSelectHint: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgObjectSelect,
      objectSelecting: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgObjectSelecting,
      objectSelectingSlow: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgObjectSelectingSlow,
      objectSelected: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgObjectSelected,
      objectAddSeedHint: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgObjectAddSeed,
      objectFinished: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgObjectFinished,
      objectFailed: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgObjectFailed,
      objectDefaultName: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgObjectDefaultName,
      brushHint: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgBrush,
      brushDrawing: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgBrushDrawing,
      brushCancelled: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgBrushCancelled,
      polygonHint: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgPolygon,
      polygonDrawing: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgPolygonDrawing,
      polygonCancelled: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgPolygonCancelled,
      polygonNeedPoints: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgPolygonNeedPoints,
      polygonDragging: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgPolygonDragging,
      polygonEdited: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgPolygonEdited,
      selectionSaved: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgSaved,
      selectionCleared: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgCleared,
      selectionStatus: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgSelection,
      selectionBound: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgSelectionBound,
      bindingLine: panel.querySelector("[data-managed-selection-panel]")?.dataset.msgBindingLine,
      bindingUnbound: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgBindingUnbound,
      noSelectionStatus: panel.querySelector("[data-managed-selection-panel]")?.dataset
        .msgNoSelection,
    },
    onChanged: (payload) => {
      current = payload;
      curveEditor.syncFromGrade(payload, getSelectedStudioId?.());
      lutEditor.syncFromGrade(payload, getSelectedStudioId?.());
      stepEditor.syncFromGrade(payload, getSelectedStudioId?.());
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
      stepEditor.syncFromGrade(payload, getSelectedStudioId?.());
      onChanged?.(payload);
    },
  });
  stepEditor = createManagedStepEditor({
    panel: panel.querySelector("[data-managed-step-panel]"),
    getSelectedStudioId,
    getGrade: () => current,
    messages: {
      enable: panel.querySelector("[data-managed-step-panel]")?.dataset.msgEnable,
      enableAria: panel.querySelector("[data-managed-step-panel]")?.dataset.msgEnableAria,
      mixAria: panel.querySelector("[data-managed-step-panel]")?.dataset.msgMixAria,
      moveUp: panel.querySelector("[data-managed-step-panel]")?.dataset.msgMoveUp,
      moveDown: panel.querySelector("[data-managed-step-panel]")?.dataset.msgMoveDown,
      empty: panel.querySelector("[data-managed-step-panel]")?.dataset.msgEmpty,
      ready: panel.querySelector("[data-managed-step-panel]")?.dataset.msgReady,
      saved: panel.querySelector("[data-managed-step-panel]")?.dataset.msgSaved,
      unavailable: panel.querySelector("[data-managed-step-panel]")?.dataset.msgUnavailable,
    },
    onChanged: (payload) => {
      current = payload;
      curveEditor.syncFromGrade(payload, getSelectedStudioId?.());
      selectionEditor.syncFromGrade(payload, getSelectedStudioId?.());
      lutEditor.syncFromGrade(payload, getSelectedStudioId?.());
      onChanged?.(payload);
    },
  });

  const liftValueLabel = panel.querySelector("[data-managed-lift-value]");
  const gammaValueLabel = panel.querySelector("[data-managed-gamma-value]");
  const gainValueLabel = panel.querySelector("[data-managed-gain-value]");
  const offsetValueLabel = panel.querySelector("[data-managed-offset-value]");
  const hueValueLabel = panel.querySelector("[data-managed-hue-value]");
  const satValueLabel = panel.querySelector("[data-managed-hsl-sat-value]");
  const lightValueLabel = panel.querySelector("[data-managed-hsl-light-value]");

  const primaryPairSpecs = {
    exposure: {
      min: -4,
      max: 4,
      step: 0.05,
      fallback: 0,
      format: (v) => v.toFixed(2),
      label: (v) => `${v.toFixed(2)} EV`,
    },
    kelvin: {
      min: 2000,
      max: 15000,
      step: 50,
      fallback: 6500,
      format: (v) => String(Math.round(v)),
      label: (v) => `${Math.round(v)} K`,
    },
    tint: {
      min: -100,
      max: 100,
      step: 1,
      fallback: 0,
      format: (v) => String(Math.round(v)),
      label: (v) => `${Math.round(v)}`,
    },
    contrast: {
      min: 0,
      max: 4,
      step: 0.01,
      fallback: 1,
      format: (v) => v.toFixed(2),
      label: (v) => v.toFixed(2),
    },
    pivot: {
      min: 0.001,
      max: 1,
      step: 0.001,
      fallback: 0.18,
      format: (v) => v.toFixed(3),
      label: (v) => v.toFixed(3),
    },
    saturation: {
      min: 0,
      max: 4,
      step: 0.01,
      fallback: 1,
      format: (v) => v.toFixed(2),
      label: (v) => v.toFixed(2),
    },
    blacks: {
      min: -100,
      max: 100,
      step: 1,
      fallback: 0,
      format: (v) => String(Math.round(v)),
      label: (v) => `${Math.round(v)}`,
    },
    shadows: {
      min: -100,
      max: 100,
      step: 1,
      fallback: 0,
      format: (v) => String(Math.round(v)),
      label: (v) => `${Math.round(v)}`,
    },
    highlights: {
      min: -100,
      max: 100,
      step: 1,
      fallback: 0,
      format: (v) => String(Math.round(v)),
      label: (v) => `${Math.round(v)}`,
    },
    whites: {
      min: -100,
      max: 100,
      step: 1,
      fallback: 0,
      format: (v) => String(Math.round(v)),
      label: (v) => `${Math.round(v)}`,
    },
  };
  const wheelPairSpecs = {
    lift: {
      min: -0.5,
      max: 0.5,
      step: 0.01,
      fallback: 0,
      format: (v) => v.toFixed(2),
      labelEl: liftValueLabel,
    },
    gamma: {
      min: 0.2,
      max: 3,
      step: 0.01,
      fallback: 1,
      format: (v) => v.toFixed(2),
      labelEl: gammaValueLabel,
    },
    gain: {
      min: 0,
      max: 4,
      step: 0.01,
      fallback: 1,
      format: (v) => v.toFixed(2),
      labelEl: gainValueLabel,
    },
    offset: {
      min: -0.5,
      max: 0.5,
      step: 0.01,
      fallback: 0,
      format: (v) => v.toFixed(2),
      labelEl: offsetValueLabel,
    },
  };

  const primaryPairs = Object.fromEntries(
    Object.entries(primaryPairSpecs).map(([key, spec]) => [
      key,
      bindSliderNumberPair({
        slider: fields[key],
        numberInput: primaryNumberFields[key],
        min: spec.min,
        max: spec.max,
        step: spec.step,
        fallback: spec.fallback,
        format: spec.format,
        onInput: (v) => {
          if (labels[key]) labels[key].textContent = spec.label(v);
        },
        onCommit: () => scheduleSave(),
      }),
    ])
  );
  const wheelPairs = Object.fromEntries(
    Object.entries(wheelPairSpecs).map(([key, spec]) => [
      key,
      bindSliderNumberPair({
        slider: wheelFields[key],
        numberInput: wheelNumberFields[key],
        min: spec.min,
        max: spec.max,
        step: spec.step,
        fallback: spec.fallback,
        format: spec.format,
        onInput: (v) => {
          if (spec.labelEl) spec.labelEl.textContent = spec.format(v);
        },
        onCommit: () => scheduleSave(),
      }),
    ])
  );
  const hslPairs = {
    hue: bindSliderNumberPair({
      slider: hslFields.hue,
      numberInput: hslNumberFields.hue,
      min: -180,
      max: 180,
      step: 1,
      fallback: 0,
      format: (v) => String(Math.round(v)),
      onInput: (v) => {
        if (hueValueLabel) hueValueLabel.textContent = `${Math.round(v)}°`;
      },
      onCommit: () => scheduleSave(),
    }),
    saturation: bindSliderNumberPair({
      slider: hslFields.saturation,
      numberInput: hslNumberFields.saturation,
      min: 0,
      max: 2,
      step: 0.01,
      fallback: 1,
      format: (v) => v.toFixed(2),
      onInput: (v) => {
        if (satValueLabel) satValueLabel.textContent = v.toFixed(2);
      },
      onCommit: () => scheduleSave(),
    }),
    lightness: bindSliderNumberPair({
      slider: hslFields.lightness,
      numberInput: hslNumberFields.lightness,
      min: -0.5,
      max: 0.5,
      step: 0.01,
      fallback: 0,
      format: (v) => v.toFixed(2),
      onInput: (v) => {
        if (lightValueLabel) lightValueLabel.textContent = v.toFixed(2);
      },
      onCommit: () => scheduleSave(),
    }),
  };

  function paintPairGroup(pairs, values) {
    Object.entries(pairs).forEach(([key, pair]) => {
      if (!(key in values) || !pair) return;
      pair.setValue(values[key], { emitInput: true });
    });
  }
  function paintHslGroup(values) {
    paintPairGroup(hslPairs, values);
  }
  function paintPrimariesGroup(values) {
    paintPairGroup(primaryPairs, values);
  }
  function paintWheelsGroup(values) {
    paintPairGroup(wheelPairs, values);
  }

  function setStatus(message) {
    if (status) status.textContent = message || "";
  }

  function setEnabled(enabled) {
    [...Object.values(fields), ...Object.values(wheelFields), ...Object.values(hslFields)].forEach(
      (input) => {
        if (input) input.disabled = !enabled || busy;
      }
    );
    [
      ...Object.values(primaryNumberFields),
      ...Object.values(wheelNumberFields),
      ...Object.values(hslNumberFields),
    ].forEach((input) => {
      if (input) input.disabled = !enabled || busy;
    });
    [
      ...Object.values(primaryPairs),
      ...Object.values(wheelPairs),
      ...Object.values(hslPairs),
    ].forEach((pair) => {
      pair?.setDisabled?.(!enabled || busy);
    });
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
      previewTokens.invalidate();
      setEnabled(false);
      setStatus("");
      stepEditor.reset();
      return;
    }
    const token = beginRequestToken(tokens, studioId);
    const previewToken = previewTokens.begin({
      key: String(studioId),
      clipId: studioId,
      revision: "",
      contextDigest: contextDigestFromParts(["managed-fill", studioId]),
    });
    try {
      const payload = await fetchGrade(studioId);
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (!previewTokens.isCurrent(previewToken)) return;
      if (!selectedStillCurrent(studioId)) return;
      // Re-bind revision after the fetch so later paints match this response.
      const paintToken = previewTokens.begin({
        key: String(studioId),
        clipId: studioId,
        revision: payload?.revision,
        contextDigest: contextDigestFromParts([
          "managed-fill",
          studioId,
          payload?.revision,
          payload?.evaluator,
        ]),
      });
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
      if (!previewTokens.isCurrent(paintToken) || !selectedStillCurrent(studioId)) return;
      if (managed) {
        paintPrimariesGroup({
          ...neutralPrimariesParams(),
          ...(findStep(current.grade, "primaries-v1")?.params || {}),
        });
        paintWheelsGroup({
          ...neutralWheelsParams(),
          ...(findStep(current.grade, "wheels-v1")?.params || {}),
        });
        paintHslGroup({
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
        stepEditor.syncFromGrade(current, studioId);
      } else if (current.authority === "canonical") {
        setStatus(
          messages.wrappedStatus?.replace("{rev}", String(current.revision)) ||
            `legacy wrapper · rev ${current.revision} · Look & color locked`
        );
        curveEditor.syncFromGrade(null, null);
        selectionEditor.syncFromGrade(null, null);
        lutEditor.syncFromGrade(null, null);
        stepEditor.syncFromGrade(null, null);
      } else {
        setStatus(messages.legacyStatus || "legacy color");
        curveEditor.syncFromGrade(null, null);
        selectionEditor.syncFromGrade(null, null);
        lutEditor.syncFromGrade(null, null);
        stepEditor.syncFromGrade(null, null);
      }
    } catch (error) {
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (!previewTokens.isCurrent(previewToken)) return;
      if (!selectedStillCurrent(studioId)) return;
      current = null;
      currentId = null;
      previewTokens.invalidate(String(studioId));
      setEnabled(false);
      setStatus(String(error.message || error));
      stepEditor.reset();
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
    let expectedRevision = current.revision;
    const primaries = readPrimaries();
    const wheels = readWheels();
    const hsl = readHsl();
    const grade = current.grade;
    const commands = [];
    function familyDirty(type, nextParams, neutrals) {
      const step = findStep(grade, type);
      const baseline = { ...neutrals, ...(step?.params || {}) };
      const candidate = { ...neutrals, ...nextParams };
      return JSON.stringify(baseline) !== JSON.stringify(candidate);
    }
    const primariesDirty = familyDirty("primaries-v1", primaries, neutralPrimariesParams());
    const wheelsDirty = familyDirty("wheels-v1", wheels, neutralWheelsParams());
    const hslDirty = familyDirty("managed-hsl-v1", hsl, neutralManagedHslParams());
    if (primariesDirty) {
      commands.push({
        type: "upsert_step_params",
        params: {
          step_id: findStep(grade, "primaries-v1")?.id || `primaries-${Date.now().toString(36)}`,
          type: "primaries-v1",
          params: primaries,
          enabled: true,
        },
      });
    }
    if (wheelsDirty) {
      commands.push({
        type: "upsert_step_params",
        params: {
          step_id: findStep(grade, "wheels-v1")?.id || `wheels-${Date.now().toString(36)}`,
          type: "wheels-v1",
          params: wheels,
          enabled: true,
        },
      });
    }
    if (hslDirty) {
      commands.push({
        type: "upsert_step_params",
        params: {
          step_id: findStep(grade, "managed-hsl-v1")?.id || `hsl-${Date.now().toString(36)}`,
          type: "managed-hsl-v1",
          params: hsl,
          enabled: true,
        },
      });
    }
    if (!commands.length) return;
    const historyGroup = `grade-save-${expectedId}-${Date.now().toString(36)}`;
    busy = true;
    setEnabled(true);
    try {
      let payload = current;
      for (const command of commands) {
        payload = await postGradeCommand(studioId, {
          type: command.type,
          expectedRevision,
          params: command.params,
          historyGroup,
        });
        expectedRevision = payload.revision;
      }
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (String(getSelectedStudioId?.()) !== expectedId) return;
      current = payload;
      currentId = expectedId;
      previewTokens.begin({
        clipId: expectedId,
        revision: current.revision,
        contextDigest: contextDigestFromParts(["managed-save", expectedId, current.revision]),
      });
      curveEditor.syncFromGrade(current, expectedId);
      selectionEditor.syncFromGrade(current, expectedId);
      lutEditor.syncFromGrade(current, expectedId);
      stepEditor.syncFromGrade(current, expectedId);
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
      setEnabled(current?.evaluator === "managed-sdr-v1");
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
      setEnabled(current?.evaluator === "managed-sdr-v1");
    }
  });

  resetBtn?.addEventListener("click", () => {
    paintPrimariesGroup(neutralPrimariesParams());
    scheduleSave();
  });
  wheelsResetBtn?.addEventListener("click", () => {
    paintWheelsGroup(neutralWheelsParams());
    scheduleSave();
  });
  hslResetBtn?.addEventListener("click", () => {
    paintHslGroup(neutralManagedHslParams());
    scheduleSave();
  });

  return {
    fill,
    currentGrade() {
      return current;
    },
    currentStudioId() {
      return currentId;
    },
    previewTokens,
    beginPreviewToken(identity) {
      return previewTokens.begin(identity || {});
    },
    isPreviewTokenCurrent(token) {
      return previewTokens.isCurrent(token);
    },
    reset() {
      paintPrimariesGroup(neutralPrimariesParams());
      paintWheelsGroup(neutralWheelsParams());
      paintHslGroup(neutralManagedHslParams());
      stepEditor.reset();
      previewTokens.invalidate();
    },
  };
}
