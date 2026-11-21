/** Managed mask/qualifier selection editor (#356/#357). */

import { beginRequestToken, isCurrentRequestToken } from "./color-workspace.js";
import {
  brushLeaf,
  emptySelection,
  findStep,
  neutralManagedHslParams,
  neutralPrimariesParams,
  neutralWheelsParams,
  polygonLeaf,
  postGradeCommand,
  qualifierFromSample,
  radialLeaf,
  linearLeaf,
  sampleEyedropper,
} from "./grade-api.js";
import {
  clearManagedSelectionOverlay,
  createManagedViewerTools,
  paintSelectionInspectionOverlay,
  paintSelectionRasterOverlay,
  resolveActivePreviewMedia,
} from "./managed-viewer-tools.js";

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
  messages = {},
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
  const polygonBtn = panel.querySelector("[data-managed-polygon-draw]");
  const brushRadius = panel.querySelector("[data-managed-brush-radius]");
  const brushHardness = panel.querySelector("[data-managed-brush-hardness]");
  const sampleSwatch = panel.querySelector("[data-managed-eyedropper-swatch]");
  const sampleMeta = panel.querySelector("[data-managed-eyedropper-meta]");
  const summaryEl = panel.querySelector("[data-managed-selection-summary]");
  const listHeading = panel.querySelector("[data-managed-mask-list-heading]");

  let current = null;
  let currentId = null;
  let pendingSample = null;
  let viewerMode = "none";
  let inspectedSelectionId = null;
  let tools = { rebind() {}, destroy() {} };
  const tokens = new Map();

  function setStatus(text) {
    if (status) status.textContent = text || "";
  }

  function stepLabel(stepType) {
    const option = bindSelect?.querySelector?.(`option[value="${stepType}"]`);
    return option?.textContent?.trim() || stepType || "";
  }

  function leafTypeLabel(selection) {
    const type = selection?.mask?.leaves?.[0]?.type || "none";
    const map = {
      polygon: messages.typePolygon || "Polygon",
      brush: messages.typeBrush || "Brush",
      radial: messages.typeRadial || "Radial",
      linear: messages.typeLinear || "Linear",
      none: messages.typeEmpty || "Empty",
    };
    return map[type] || type;
  }

  function displayName(selection) {
    const named = typeof selection?.name === "string" ? selection.name.trim() : "";
    if (named) return named;
    return (messages.untitledMask || "Mask {id}").replace("{id}", String(selection?.id || ""));
  }

  function overlayVisible(selection) {
    if (selection?.overlay && typeof selection.overlay.visible === "boolean") {
      return selection.overlay.visible;
    }
    return true;
  }

  let overlayToken = 0;

  async function refreshInspectionOverlay(gradeDoc) {
    const media = resolveActivePreviewMedia([getPreviewMediaEl?.()].flat().filter(Boolean));
    if (!media || !inspectedSelectionId) {
      clearManagedSelectionOverlay(media);
      return;
    }
    const selection = (gradeDoc?.grade?.selections || []).find(
      (entry) => entry.id === inspectedSelectionId
    );
    if (!selection || !overlayVisible(selection)) {
      clearManagedSelectionOverlay(media);
      return;
    }
    const studioId = getSelectedStudioId?.();
    const revision = gradeDoc?.revision;
    if (!studioId || revision === undefined || revision === null) {
      paintSelectionInspectionOverlay(media, selection, {
        invertedHint: Boolean(selection.invert),
      });
      return;
    }
    const token = ++overlayToken;
    try {
      const url =
        `/api/studio/${studioId}/grade/selection-overlay` +
        `?selection_id=${encodeURIComponent(String(inspectedSelectionId))}` +
        `&expected_revision=${encodeURIComponent(String(revision))}` +
        `&max_edge=640`;
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(`overlay ${res.status}`);
      const blob = await res.blob();
      if (token !== overlayToken) return;
      const bitmap = await createImageBitmap(blob);
      if (token !== overlayToken) {
        bitmap.close?.();
        return;
      }
      paintSelectionRasterOverlay(media, bitmap, selection);
      bitmap.close?.();
    } catch {
      if (token !== overlayToken) return;
      paintSelectionInspectionOverlay(media, selection, {
        invertedHint: Boolean(selection.invert),
      });
    }
  }

  function renderSelectionSummary(gradeDoc) {
    if (!summaryEl) return;
    const selections = gradeDoc?.grade?.selections || [];
    const steps = gradeDoc?.grade?.steps || [];
    summaryEl.replaceChildren();
    if (!selections.length) {
      summaryEl.hidden = true;
      if (listHeading) listHeading.hidden = true;
      inspectedSelectionId = null;
      refreshInspectionOverlay(null);
      return;
    }
    summaryEl.hidden = false;
    if (listHeading) listHeading.hidden = false;
    const bindType = bindSelect?.value || "primaries-v1";
    const activeStep = findStep(gradeDoc.grade, bindType);
    const boundSelectionId = activeStep?.selection_id || null;
    if (inspectedSelectionId && !selections.some((entry) => entry.id === inspectedSelectionId)) {
      inspectedSelectionId = null;
    }
    if (!inspectedSelectionId && boundSelectionId) {
      inspectedSelectionId = boundSelectionId;
    }
    for (const selection of selections) {
      const boundSteps = steps.filter((step) => step.selection_id === selection.id);
      const li = document.createElement("li");
      li.className = "studio-mask-list-item";
      li.tabIndex = 0;
      li.setAttribute("role", "option");
      li.dataset.selectionId = String(selection.id);
      const isInspected = inspectedSelectionId && selection.id === inspectedSelectionId;
      const isBound = boundSelectionId && selection.id === boundSelectionId;
      if (isInspected) li.classList.add("is-active");
      if (isBound) li.classList.add("is-bound");

      const title = document.createElement("button");
      title.type = "button";
      title.className = "studio-mask-list-select";
      const gradePart = boundSteps.length
        ? boundSteps.map((step) => stepLabel(step.type)).join(", ")
        : messages.bindingUnboundShort || "unbound";
      const invertPart = selection.invert ? ` · ${messages.invertShort || "invert"}` : "";
      title.textContent = `${displayName(selection)} · ${leafTypeLabel(selection)} · ${gradePart}${invertPart}`;
      title.title = String(selection.id);
      title.addEventListener("click", (event) => {
        event.preventDefault();
        inspectedSelectionId = selection.id;
        if (invertInput) invertInput.checked = Boolean(selection.invert);
        const leafType = selection?.mask?.leaves?.[0]?.type;
        if (leafType && shapeSelect) {
          shapeSelect.value = leafType;
        }
        // Enable polygon edit mode so add/remove/move work without re-arming Draw (#538).
        if (leafType === "polygon") {
          setViewerMode("polygon");
          tools.rebind?.();
        }
        renderSelectionSummary(gradeDoc);
        setStatus(
          (messages.maskSelected || "Selected mask · {name}")
            .replace("{name}", displayName(selection))
            .replace("{id}", String(selection.id))
        );
      });

      const actions = document.createElement("div");
      actions.className = "studio-mask-list-actions";

      const overlayBtn = document.createElement("button");
      overlayBtn.type = "button";
      overlayBtn.className = "button ghost studio-mask-list-action";
      const ovVisible = overlayVisible(selection);
      overlayBtn.textContent = ovVisible
        ? messages.hideOverlay || "Hide"
        : messages.showOverlay || "Show";
      overlayBtn.setAttribute(
        "aria-label",
        ovVisible
          ? messages.hideOverlayAria || "Hide selection overlay"
          : messages.showOverlayAria || "Show selection overlay"
      );
      overlayBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        void upsertSelectionMeta(selection.id, {
          overlay: { visible: !ovVisible },
        });
      });

      const renameBtn = document.createElement("button");
      renameBtn.type = "button";
      renameBtn.className = "button ghost studio-mask-list-action";
      renameBtn.textContent = messages.renameMask || "Rename";
      renameBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const next = window.prompt(
          messages.renamePrompt || "Mask name",
          typeof selection.name === "string" ? selection.name : displayName(selection)
        );
        if (next === null) return;
        const trimmed = String(next).trim().slice(0, 80);
        void upsertSelectionMeta(selection.id, { name: trimmed });
      });

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "button ghost studio-mask-list-action";
      deleteBtn.textContent = messages.deleteMask || "Delete";
      deleteBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (
          !window.confirm(
            (messages.deleteConfirm || "Delete mask “{name}”?").replace(
              "{name}",
              displayName(selection)
            )
          )
        ) {
          return;
        }
        void deleteSelection(selection.id);
      });

      actions.append(overlayBtn, renameBtn, deleteBtn);
      li.append(title, actions);
      summaryEl.appendChild(li);
    }
    refreshInspectionOverlay(gradeDoc);
  }

  async function upsertSelectionMeta(selectionId, patch) {
    const studioId = getSelectedStudioId?.();
    const gradeDoc = getGrade?.() || current;
    if (!studioId || !gradeDoc?.grade || gradeDoc.evaluator !== "managed-sdr-v1") return;
    const previous = (gradeDoc.grade.selections || []).find((entry) => entry.id === selectionId);
    if (!previous) return;
    const selection = structuredClone(previous);
    if (Object.prototype.hasOwnProperty.call(patch, "name")) selection.name = patch.name;
    if (Object.prototype.hasOwnProperty.call(patch, "overlay")) {
      selection.overlay = { ...(selection.overlay || {}), ...patch.overlay };
    }
    const token = beginRequestToken(tokens, studioId);
    try {
      const payload = await postGradeCommand(studioId, {
        type: "upsert_selection",
        expectedRevision: gradeDoc.revision,
        params: { selection },
        historyGroup: `selection-meta-${selectionId}`,
      });
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      current = payload;
      onChanged?.(payload);
    } catch (error) {
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      setStatus(String(error.message || error));
    }
  }

  async function deleteSelection(selectionId) {
    const studioId = getSelectedStudioId?.();
    const gradeDoc = getGrade?.() || current;
    if (!studioId || !gradeDoc?.grade || gradeDoc.evaluator !== "managed-sdr-v1") return;
    const token = beginRequestToken(tokens, studioId);
    try {
      const payload = await postGradeCommand(studioId, {
        type: "remove_selection",
        expectedRevision: gradeDoc.revision,
        params: { selection_id: selectionId },
        historyGroup: `selection-delete-${selectionId}`,
      });
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (inspectedSelectionId === selectionId) inspectedSelectionId = null;
      current = payload;
      setStatus(messages.maskDeleted || "Mask deleted");
      onChanged?.(payload);
    } catch (error) {
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      setStatus(String(error.message || error));
    }
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
      polygonBtn,
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
    if (polygonBtn) {
      polygonBtn.setAttribute("aria-pressed", viewerMode === "polygon" ? "true" : "false");
    }
    const provided = getPreviewMediaEl?.();
    const media = Array.isArray(provided) ? resolveActivePreviewMedia(provided) : provided || null;
    if (media && media.style) {
      media.style.cursor =
        viewerMode === "eyedropper" || viewerMode === "polygon"
          ? "crosshair"
          : viewerMode === "brush"
            ? "cell"
            : "";
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
      const template = messages.sampleMeta || "Sample · rev {rev} · {domain} · frame {frame}";
      sampleMeta.textContent = template
        .replace("{rev}", String(sample.revision))
        .replace("{domain}", String(sample.domain || ""))
        .replace("{frame}", String(sample.frame));
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
    if (stroke?.kind === "polygon" || (stroke?.points && stroke?.closed)) {
      return polygonLeaf({
        points: stroke.points,
        feather,
        closed: stroke.closed !== false,
      });
    }
    if (stroke) {
      return brushLeaf({
        points: stroke.points,
        radius: stroke.radius,
        hardness: stroke.hardness,
        pressure: stroke.pressure,
      });
    }
    if (shape === "linear") return linearLeaf({ feather });
    if (shape === "polygon") {
      return polygonLeaf({
        points: [
          [0.3, 0.3],
          [0.7, 0.3],
          [0.7, 0.7],
          [0.3, 0.7],
        ],
        feather,
        closed: true,
      });
    }
    if (shape === "brush") {
      return brushLeaf({
        radius: numberFromInput(brushRadius, 0.08),
        hardness: numberFromInput(brushHardness, 0.5),
      });
    }
    return radialLeaf({ feather });
  }

  async function saveSelection({ clear = false, stroke = null, acceptSample = false } = {}) {
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
    if (acceptSample) {
      if (!pendingSample) return;
      if (Number(pendingSample.revision) !== Number(gradeDoc.revision)) {
        showSample(null);
        setStatus(messages.sampleStale || "Sample is stale. Sample again.");
        return;
      }
    }
    const token = beginRequestToken(tokens, studioId);
    const expectedId = String(studioId);
    const bindType = bindSelect?.value || "primaries-v1";
    let expectedRevision = gradeDoc.revision;
    const historyGroup = `selection-${expectedId}-${Date.now().toString(36)}`;
    try {
      let payload = gradeDoc;
      let step = findStep(gradeDoc.grade, bindType);
      if (clear) {
        showSample(null);
        if (!step?.id) {
          setStatus(messages.selectionCleared || "Selection cleared");
          return;
        }
        payload = await postGradeCommand(studioId, {
          type: "bind_step_selection",
          expectedRevision,
          params: { step_id: step.id, selection_id: null },
          historyGroup,
        });
      } else {
        if (!step) {
          const neutrals =
            bindType === "wheels-v1"
              ? neutralWheelsParams()
              : bindType === "managed-hsl-v1"
                ? neutralManagedHslParams()
                : neutralPrimariesParams();
          payload = await postGradeCommand(studioId, {
            type: "upsert_step_params",
            expectedRevision,
            params: {
              step_id: `${bindType}-${Date.now().toString(36)}`,
              type: bindType,
              params: neutrals,
              enabled: true,
            },
            historyGroup,
          });
          expectedRevision = payload.revision;
          step = findStep(payload.grade, bindType);
        }
        if (!step?.id) throw new Error("step not found");
        const reuseId = step.selection_id || null;
        const previous = (payload.grade.selections || []).find((entry) => entry.id === reuseId);
        const selection = previous
          ? structuredClone(previous)
          : emptySelection(reuseId || undefined);
        if (!selection.mask || typeof selection.mask !== "object") {
          selection.mask = { combine: "union", leaves: [] };
        }
        if (!Array.isArray(selection.mask.leaves)) selection.mask.leaves = [];
        if (stroke) {
          const leaf = buildLeaf(stroke);
          if (leaf.type === "polygon") {
            selection.mask.leaves = [leaf];
            if (shapeSelect) shapeSelect.value = "polygon";
          } else {
            const brushIndex = selection.mask.leaves.findIndex((entry) => entry?.type === "brush");
            if (brushIndex >= 0) {
              const brush = selection.mask.leaves[brushIndex];
              const strokes = Array.isArray(brush.strokes) ? brush.strokes.slice() : [];
              strokes.push(...(leaf.strokes || []));
              selection.mask.leaves[brushIndex] = { ...brush, strokes };
            } else if (selection.mask.leaves.length === 0) {
              selection.mask.leaves = [leaf];
            } else {
              selection.mask.leaves.push(leaf);
            }
            if (shapeSelect) shapeSelect.value = "brush";
          }
        } else if (!acceptSample) {
          selection.mask = { combine: "union", leaves: [buildLeaf(null)] };
        }
        if (acceptSample || !stroke) {
          selection.qualifier = buildQualifier();
        } else if (!selection.qualifier || typeof selection.qualifier !== "object") {
          selection.qualifier = {};
        }
        selection.invert = Boolean(invertInput?.checked);
        payload = await postGradeCommand(studioId, {
          type: "upsert_selection",
          expectedRevision,
          params: { selection },
          historyGroup,
        });
        expectedRevision = payload.revision;
        payload = await postGradeCommand(studioId, {
          type: "bind_step_selection",
          expectedRevision,
          params: { step_id: step.id, selection_id: selection.id },
          historyGroup,
        });
      }
      if (!isCurrentRequestToken(tokens, studioId, token)) return;
      if (String(getSelectedStudioId?.()) !== expectedId) return;
      current = payload;
      currentId = expectedId;
      if (acceptSample) showSample(null);
      setStatus(
        clear
          ? `${messages.selectionCleared || "Selection cleared"} · rev ${payload.revision}`
          : `${messages.selectionSaved || "Selection saved"} · rev ${payload.revision}`
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
    setStatus(messages.sampling || "Sampling…");
    try {
      const data = await sampleEyedropper(studioId, {
        u: uv.u,
        v: uv.v,
        t_s: Number(getPreviewSourceTimeS?.() || 0),
        expectedRevision: gradeDoc.revision,
      });
      if (!isCurrentRequestToken(tokens, `eye-${studioId}`, token)) return;
      if (String(getSelectedStudioId?.()) !== String(studioId)) return;
      const live = getGrade?.() || current;
      if (!live || Number(live.revision) !== Number(data.sample.revision)) {
        showSample(null);
        setStatus(messages.sampleStale || "Sample is stale. Sample again.");
        return;
      }
      showSample(data.sample);
      if (qualifierSelect && qualifierSelect.value === "none") {
        qualifierSelect.value = "rgb";
      }
      setStatus(
        `${messages.sampledHint || "Sampled — accept to apply qualifier"} · rev ${data.sample.revision}`
      );
      setViewerMode("none");
    } catch (error) {
      if (!isCurrentRequestToken(tokens, `eye-${studioId}`, token)) return;
      showSample(null);
      setStatus(String(error.message || error));
    }
  }

  function syncFromGrade(payload, studioId) {
    const previousId = currentId;
    const previousRevision = current?.revision;
    current = payload || null;
    currentId = studioId ? String(studioId) : null;
    if (String(previousId || "") !== String(currentId || "")) {
      inspectedSelectionId = null;
      overlayToken += 1;
      clearManagedSelectionOverlay(
        resolveActivePreviewMedia([getPreviewMediaEl?.()].flat().filter(Boolean))
      );
    }
    if (
      String(previousId || "") !== String(currentId || "") ||
      Number(previousRevision) !== Number(payload?.revision)
    ) {
      showSample(null);
    }
    const managed = payload?.evaluator === "managed-sdr-v1";
    setEnabled(managed);
    tools.rebind?.();
    if (!managed) {
      setStatus("");
      showSample(null);
      setViewerMode("none");
      renderSelectionSummary(null);
      return;
    }
    const bindType = bindSelect?.value || "primaries-v1";
    const boundForBind = findStep(payload.grade, bindType);
    const bound = boundForBind?.selection_id
      ? boundForBind
      : (payload.grade?.steps || []).find((step) => step.selection_id) || boundForBind;
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
    renderSelectionSummary(payload);
    if (selection && bound) {
      setStatus(
        (
          messages.selectionBound ||
          messages.selectionStatus ||
          "Active · {id} on {step} · rev {rev}"
        )
          .replace("{id}", String(selection.id))
          .replace("{step}", stepLabel(bound.type))
          .replace("{rev}", String(payload.revision))
      );
    } else {
      setStatus(
        (messages.noSelectionStatus || "No selection · rev {rev}").replace(
          "{rev}",
          String(payload.revision)
        )
      );
    }
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
  bindSelect?.addEventListener("change", () => {
    const studioId = getSelectedStudioId?.();
    const payload = getGrade?.() || current;
    if (payload) syncFromGrade(payload, studioId);
  });
  eyedropperBtn?.addEventListener("click", () => {
    setViewerMode(viewerMode === "eyedropper" ? "none" : "eyedropper");
    setStatus(
      viewerMode === "eyedropper" ? messages.eyedropperHint || "Eyedropper: click the preview" : ""
    );
    tools.rebind?.();
  });
  brushBtn?.addEventListener("click", () => {
    if (shapeSelect) shapeSelect.value = "brush";
    setViewerMode(viewerMode === "brush" ? "none" : "brush");
    setStatus(viewerMode === "brush" ? messages.brushHint || "Brush: draw on the preview" : "");
    tools.rebind?.();
  });
  polygonBtn?.addEventListener("click", () => {
    if (shapeSelect) shapeSelect.value = "polygon";
    setViewerMode(viewerMode === "polygon" ? "none" : "polygon");
    setStatus(
      viewerMode === "polygon"
        ? messages.polygonHint ||
            "Polygon: click to place points, drag handles to refine, Enter or double-click to close"
        : ""
    );
    tools.rebind?.();
  });
  acceptBtn?.addEventListener("click", () => {
    if (!pendingSample) return;
    void saveSelection({ acceptSample: true });
  });

  function currentPolygonPoints() {
    const studioId = getSelectedStudioId?.();
    const payload = getGrade?.() || current;
    const grade = payload?.grade;
    if (!grade || !studioId) return null;
    const bindType = bindSelect?.value || "primaries-v1";
    const step = (grade.steps || []).find((entry) => entry?.type === bindType);
    const selectionId = inspectedSelectionId || step?.selection_id;
    if (!selectionId) return null;
    const selection = (grade.selections || []).find((entry) => entry?.id === selectionId);
    const leaf = selection?.mask?.leaves?.find((entry) => entry?.type === "polygon");
    if (!leaf || !Array.isArray(leaf.points) || leaf.points.length < 3) return null;
    return { points: leaf.points, closed: leaf.closed !== false };
  }

  tools = createManagedViewerTools({
    getMediaEl: () => {
      const provided = getPreviewMediaEl?.();
      if (Array.isArray(provided)) return resolveActivePreviewMedia(provided);
      return provided || null;
    },
    getMode: () => viewerMode,
    getBrushSettings: () => ({
      radius: numberFromInput(brushRadius, 0.08),
      hardness: numberFromInput(brushHardness, 0.5),
      pressure: 1,
    }),
    getEditablePolygon: () => currentPolygonPoints(),
    onEyedropperSample: (uv) => runEyedropper(uv),
    onBrushStrokeComplete: (stroke) => {
      void saveSelection({ stroke });
      setViewerMode("none");
    },
    onPolygonComplete: (poly) => {
      void saveSelection({
        stroke: { kind: "polygon", points: poly.points, closed: true },
      });
      setViewerMode("none");
    },
    onPolygonEdited: (poly) => {
      void saveSelection({
        stroke: { kind: "polygon", points: poly.points, closed: true },
      });
    },
    onStatus: setStatus,
    messages: {
      ...messages,
      brushDrawing: messages.brushDrawing,
      brushCancelled: messages.brushCancelled,
      polygonDrawing: messages.polygonDrawing,
      polygonCancelled: messages.polygonCancelled,
      polygonNeedPoints: messages.polygonNeedPoints,
      polygonDragging: messages.polygonDragging,
      polygonEdited: messages.polygonEdited,
      polygonVertexAdded: messages.polygonVertexAdded,
      polygonVertexRemoved: messages.polygonVertexRemoved,
      polygonMoving: messages.polygonMoving,
      polygonMoved: messages.polygonMoved,
    },
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
