import { formatExportDuration } from "./format.js";

export { formatExportDuration };

const DEFAULT_MESSAGES = {
  failed: "Export failed.",
  cancelled: "Export cancelled.",
  cancelling: "Cancelling export…",
  noResolution: "No exportable video resolution in this project.",
  running: "Exporting…",
  done: "Export finished.",
  preparing: "Preparing export…",
  clip: "Clip {current} of {total}",
  combining: "Combining clips…",
  mixing: "Mixing music…",
  unavailable: "Export needs the desktop app for the save dialog.",
  runningHint: "Export is running…",
  elapsed: "Elapsed {time}",
  doneIn: "Done in {time}",
  success: "Exported {filename}.",
  fileMissing: "The exported file is no longer available.",
  openUnavailable: "Opening the exported video is not available on this device.",
  revealUnavailable: "Showing the file in its folder is not available on this device.",
  recommended: "recommended",
};

const MESSAGE_DATASET_KEYS = {
  failed: "exportFailed",
  cancelled: "exportCancelled",
  cancelling: "exportCancelling",
  noResolution: "exportNoResolution",
  running: "exportRunning",
  done: "exportDone",
  preparing: "exportPreparing",
  clip: "exportClip",
  combining: "exportCombining",
  mixing: "exportMixing",
  unavailable: "exportUnavailable",
  runningHint: "exportRunningHint",
  elapsed: "exportElapsed",
  doneIn: "exportDoneIn",
  success: "exportSuccess",
  fileMissing: "exportFileMissing",
  openUnavailable: "exportOpenUnavailable",
  revealUnavailable: "exportRevealUnavailable",
  recommended: "recommendedLabel",
};

function messagesFromRoot(root) {
  const data = root && root.dataset ? root.dataset : null;
  if (!data) return { ...DEFAULT_MESSAGES };
  const messages = { ...DEFAULT_MESSAGES };
  for (const [key, datasetKey] of Object.entries(MESSAGE_DATASET_KEYS)) {
    if (typeof data[datasetKey] === "string" && data[datasetKey]) {
      messages[key] = data[datasetKey];
    }
  }
  return messages;
}

export function exportPhaseLabel(job, messages) {
  if (job.phase === "preparing") return messages.preparing;
  if (job.phase === "concat") return messages.combining;
  if (job.phase === "mixing") return messages.mixing;
  if (job.phase === "done" || job.state === "completed") return messages.done;
  if (job.phase === "rendering") {
    const current = Number(job.clip_index) || 0;
    const total = Number(job.clip_total) || 0;
    let label = messages.clip
      .replace("{current}", String(current))
      .replace("{total}", String(total));
    if (job.current_label) {
      label = `${label} · ${job.current_label}`;
    }
    return label;
  }
  return messages.running;
}

export function suggestionForHeight(optionsCache, height) {
  const options = optionsCache && Array.isArray(optionsCache.options) ? optionsCache.options : [];
  const match = options.find((opt) => Number(opt.height) === Number(height));
  if (match && match.suggested_filename) return String(match.suggested_filename);
  if (optionsCache && optionsCache.suggested_filename) {
    return String(optionsCache.suggested_filename);
  }
  return "export.mp4";
}

function queryElements(documentImpl) {
  if (!documentImpl) return {};
  return {
    dialog: documentImpl.getElementById("studio-export-dialog"),
    openButton: documentImpl.getElementById("studio-export-open"),
    openFileButton: documentImpl.getElementById("studio-export-open-file"),
    revealFileButton: documentImpl.getElementById("studio-export-reveal-file"),
    dismissButton: documentImpl.getElementById("studio-export-success-dismiss"),
    resolution: documentImpl.getElementById("studio-export-resolution"),
    quality: documentImpl.getElementById("studio-export-quality"),
    filename: documentImpl.getElementById("studio-export-filename"),
    status: documentImpl.getElementById("studio-export-status"),
    hint: documentImpl.getElementById("studio-export-hint"),
    runButton: documentImpl.getElementById("studio-export-run"),
    cancelButton: documentImpl.getElementById("studio-export-cancel"),
    progress: documentImpl.getElementById("studio-export-progress"),
    progressBar: documentImpl.getElementById("studio-export-progress-bar"),
    progressEl: documentImpl.getElementById("studio-export-progressbar"),
    progressLabel: documentImpl.getElementById("studio-export-progress-label"),
    progressMeta: documentImpl.getElementById("studio-export-progress-meta"),
    successBanner: documentImpl.getElementById("studio-export-success"),
    successTitle: documentImpl.getElementById("studio-export-success-title"),
    successPath: documentImpl.getElementById("studio-export-success-path"),
    successError: documentImpl.getElementById("studio-export-success-error"),
  };
}

export function createExportUi(options = {}) {
  const documentImpl = options.documentImpl || globalThis.document;
  const root = options.root || documentImpl?.getElementById("studio-root") || null;
  const messages = options.messages || messagesFromRoot(root);
  const fetchImpl = options.fetchImpl || ((...args) => globalThis.fetch(...args));
  const now = options.now || (() => Date.now());
  const setTimeoutImpl = options.setTimeoutImpl || ((fn, ms) => globalThis.setTimeout(fn, ms));
  const clearTimeoutImpl = options.clearTimeoutImpl || ((id) => globalThis.clearTimeout(id));
  const setIntervalImpl = options.setIntervalImpl || ((fn, ms) => globalThis.setInterval(fn, ms));
  const clearIntervalImpl = options.clearIntervalImpl || ((id) => globalThis.clearInterval(id));
  const projectId = Number(options.projectId || 0) || 0;
  const elements = { ...queryElements(documentImpl), ...(options.elements || {}) };
  const listeners = [];
  const state = {
    optionsCache: null,
    pollTimer: null,
    elapsedTimer: null,
    startedAtMs: 0,
    lastJob: null,
    activeJobId: null,
    cancelRequested: false,
    filenameAuto: "",
  };

  function on(target, event, handler) {
    if (!target || typeof target.addEventListener !== "function") return;
    target.addEventListener(event, handler);
    listeners.push({ target, event, handler });
  }

  function setExportStatus(message, { error = false } = {}) {
    if (!elements.status) return;
    if (!message) {
      elements.status.hidden = true;
      elements.status.textContent = "";
      return;
    }
    elements.status.hidden = false;
    elements.status.textContent = message;
    elements.status.classList.toggle("is-error", !!error);
  }

  function setExportProgressVisible(visible) {
    if (!elements.progress) return;
    elements.progress.hidden = !visible;
    if (!visible) {
      elements.progress.classList.remove("is-working");
    }
  }

  function updateExportProgress(job, { localElapsedS = null } = {}) {
    state.lastJob = job;
    const percent = Math.max(0, Math.min(100, Number(job.percent) || 0));
    if (elements.progressBar) elements.progressBar.style.width = `${percent}%`;
    if (elements.progressEl) {
      elements.progressEl.setAttribute("aria-valuenow", String(percent));
    }
    if (elements.progress) {
      elements.progress.classList.toggle(
        "is-working",
        job.state === "running" || job.state === "pending"
      );
    }
    const primary = `${exportPhaseLabel(job, messages)} (${percent}%)`;
    if (elements.progressLabel) elements.progressLabel.textContent = primary;

    const elapsed =
      localElapsedS !== null && localElapsedS !== undefined
        ? localElapsedS
        : Number(job.elapsed_s) || 0;
    const elapsedText = messages.elapsed.replace("{time}", formatExportDuration(elapsed));
    if (elements.progressMeta) {
      elements.progressMeta.textContent =
        job.state === "completed"
          ? messages.doneIn.replace("{time}", formatExportDuration(elapsed))
          : elapsedText;
    }
  }

  function setExportRunningUi(running) {
    if (elements.runButton) elements.runButton.disabled = running;
    if (elements.resolution) elements.resolution.disabled = running;
    if (elements.quality) elements.quality.disabled = running;
    if (elements.filename) elements.filename.disabled = running;
    if (elements.cancelButton && !state.cancelRequested) {
      elements.cancelButton.disabled = false;
    }
  }

  function refreshExportHint() {
    if (!elements.hint || !state.optionsCache) return;
    const name =
      (elements.filename && elements.filename.value.trim()) ||
      suggestionForHeight(
        state.optionsCache,
        elements.resolution ? elements.resolution.value : null
      );
    elements.hint.textContent = `${name} → ${state.optionsCache.default_directory || ""}`;
  }

  function syncExportFilename(height, { reset = false } = {}) {
    const next = suggestionForHeight(state.optionsCache, height);
    const current = elements.filename ? elements.filename.value.trim() : "";
    if (elements.filename && (reset || !current || current === state.filenameAuto)) {
      elements.filename.value = next;
      state.filenameAuto = next;
    }
    refreshExportHint();
  }

  function chosenExportFilename(height) {
    const typed = elements.filename ? elements.filename.value.trim() : "";
    return typed || suggestionForHeight(state.optionsCache, height);
  }

  function stopExportElapsedTimer() {
    if (state.elapsedTimer) {
      clearIntervalImpl(state.elapsedTimer);
      state.elapsedTimer = null;
    }
  }

  function startExportElapsedTimer() {
    stopExportElapsedTimer();
    state.startedAtMs = now();
    state.elapsedTimer = setIntervalImpl(() => {
      if (!state.lastJob) return;
      const localElapsedS = (now() - state.startedAtMs) / 1000;
      updateExportProgress(state.lastJob, { localElapsedS });
    }, 1000);
  }

  function hideExportSuccess() {
    if (elements.successBanner) elements.successBanner.hidden = true;
  }

  function setExportSuccessError(message) {
    if (!elements.successError) return;
    if (!message) {
      elements.successError.hidden = true;
      elements.successError.textContent = "";
      return;
    }
    elements.successError.hidden = false;
    elements.successError.textContent = message;
  }

  function showExportSuccess(job) {
    if (!elements.successBanner || !elements.successTitle) return;
    const filename = job.filename || (job.output_path || "").split(/[/\\]/).pop() || "export.mp4";
    elements.successTitle.textContent = messages.success.replace("{filename}", filename);
    if (elements.successPath) {
      if (job.output_path) {
        elements.successPath.hidden = false;
        elements.successPath.textContent = job.output_path;
        elements.successPath.title = job.output_path;
      } else {
        elements.successPath.hidden = true;
        elements.successPath.textContent = "";
      }
    }
    setExportSuccessError("");
    if (elements.openFileButton) {
      elements.openFileButton.hidden = job.open_available === false;
    }
    if (elements.revealFileButton) {
      elements.revealFileButton.hidden = job.reveal_available === false;
    }
    elements.successBanner.hidden = false;
  }

  async function requestExportAction(action) {
    const unavailable = action === "open" ? messages.openUnavailable : messages.revealUnavailable;
    try {
      const res = await fetchImpl(`/api/studio/export/${action}`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => null);
      if (res.status === 503) {
        setExportSuccessError(unavailable);
        return;
      }
      if (!res.ok || !data || data.ok === false) {
        setExportSuccessError((data && data.detail) || messages.fileMissing);
        return;
      }
      setExportSuccessError("");
    } catch {
      setExportSuccessError(messages.fileMissing);
    }
  }

  function stopExportPoll() {
    if (state.pollTimer) {
      clearTimeoutImpl(state.pollTimer);
      state.pollTimer = null;
    }
    stopExportElapsedTimer();
  }

  function pollExportJob(jobId) {
    stopExportPoll();
    startExportElapsedTimer();
    const tick = async () => {
      try {
        const res = await fetchImpl(`/api/studio/export/jobs/${encodeURIComponent(jobId)}`, {
          headers: { Accept: "application/json" },
        });
        const data = await res.json().catch(() => null);
        if (res.status === 404) {
          stopExportElapsedTimer();
          setExportStatus(messages.failed, { error: true });
          setExportRunningUi(false);
          setExportProgressVisible(false);
          return;
        }
        if (!res.ok || !data || !data.ok) {
          stopExportElapsedTimer();
          setExportStatus((data && data.detail) || messages.failed, { error: true });
          setExportRunningUi(false);
          return;
        }
        setExportProgressVisible(true);
        const localElapsedS = (now() - state.startedAtMs) / 1000;
        updateExportProgress(data, { localElapsedS });
        if (data.state === "cancelled") {
          stopExportElapsedTimer();
          state.activeJobId = null;
          state.cancelRequested = false;
          if (elements.progress) elements.progress.classList.remove("is-working");
          setExportProgressVisible(false);
          setExportStatus(messages.cancelled);
          setExportRunningUi(false);
          return;
        }
        if (data.phase === "cancelling") {
          setExportStatus(messages.cancelling);
          if (elements.cancelButton) elements.cancelButton.disabled = true;
          state.pollTimer = setTimeoutImpl(tick, 400);
          return;
        }
        if (data.state === "completed") {
          stopExportElapsedTimer();
          state.activeJobId = null;
          state.cancelRequested = false;
          if (elements.progress) elements.progress.classList.remove("is-working");
          setExportRunningUi(false);
          if (elements.dialog && typeof elements.dialog.close === "function") {
            elements.dialog.close();
          }
          showExportSuccess(data);
          if (state.optionsCache) {
            state.optionsCache.default_directory =
              data.directory || state.optionsCache.default_directory;
            state.optionsCache.last_export_directory = data.directory || null;
          }
          return;
        }
        if (data.state === "failed") {
          stopExportElapsedTimer();
          state.activeJobId = null;
          state.cancelRequested = false;
          if (elements.progress) elements.progress.classList.remove("is-working");
          setExportStatus(data.error || messages.failed, { error: true });
          setExportRunningUi(false);
          return;
        }
        setExportStatus(messages.runningHint);
        state.pollTimer = setTimeoutImpl(tick, 400);
      } catch {
        state.pollTimer = setTimeoutImpl(tick, 1000);
      }
    };
    tick();
  }

  async function openExportDialog() {
    if (!elements.dialog) return;
    hideExportSuccess();
    stopExportPoll();
    state.lastJob = null;
    state.activeJobId = null;
    state.cancelRequested = false;
    setExportStatus("");
    setExportProgressVisible(false);
    if (elements.progressBar) elements.progressBar.style.width = "0%";
    if (elements.progressLabel) elements.progressLabel.textContent = "";
    if (elements.progressMeta) elements.progressMeta.textContent = "";
    if (elements.hint) elements.hint.textContent = "";
    setExportRunningUi(false);
    if (elements.runButton) elements.runButton.disabled = true;
    if (elements.resolution) elements.resolution.innerHTML = "";
    state.filenameAuto = "";
    if (elements.filename) elements.filename.value = "";
    elements.dialog.showModal();
    try {
      const qs = projectId ? `?project_id=${encodeURIComponent(String(projectId))}` : "";
      const res = await fetchImpl(`/api/studio/export/options${qs}`, {
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        setExportStatus((data && data.detail) || messages.failed, { error: true });
        return;
      }
      state.optionsCache = data;
      const optionRows = Array.isArray(data.options) ? data.options : [];
      if (!optionRows.length) {
        setExportStatus(messages.noResolution, { error: true });
        if (elements.hint) elements.hint.textContent = messages.noResolution;
        return;
      }
      if (elements.resolution) {
        optionRows.forEach((opt) => {
          const option = documentImpl.createElement("option");
          option.value = String(opt.height);
          const recommended =
            opt.recommended || Number(opt.height) === Number(data.default_height)
              ? ` (${messages.recommended})`
              : "";
          option.textContent = `${opt.label}${recommended}`;
          if (Number(opt.height) === Number(data.default_height)) {
            option.selected = true;
          }
          elements.resolution.appendChild(option);
        });
      }
      if (elements.quality && data.default_quality) {
        elements.quality.value = String(data.default_quality);
        if (elements.quality.value !== String(data.default_quality)) {
          elements.quality.value = "high";
        }
      }
      syncExportFilename(elements.resolution ? elements.resolution.value : data.default_height, {
        reset: true,
      });
      if (elements.runButton) elements.runButton.disabled = false;
    } catch {
      setExportStatus(messages.failed, { error: true });
    }
  }

  async function runStudioExport() {
    if (!state.optionsCache || !elements.resolution || !elements.runButton) return;
    const height = Number(elements.resolution.value);
    if (!Number.isFinite(height) || height <= 0) {
      setExportStatus(messages.noResolution, { error: true });
      return;
    }
    setExportRunningUi(true);
    setExportStatus(messages.runningHint);
    setExportProgressVisible(false);
    let pickedPath;
    try {
      const pickRes = await fetchImpl("/api/desktop/pick-save-file", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          directory: state.optionsCache.default_directory || "",
          filename: chosenExportFilename(height),
        }),
      });
      const pickData = await pickRes.json().catch(() => null);
      if (pickRes.status === 503) {
        setExportStatus(messages.unavailable, { error: true });
        setExportRunningUi(false);
        return;
      }
      if (!pickData || pickData.status === "cancelled") {
        setExportStatus(messages.cancelled);
        setExportRunningUi(false);
        return;
      }
      if (pickData.status !== "ok" || !pickData.path) {
        setExportStatus(messages.failed, { error: true });
        setExportRunningUi(false);
        return;
      }
      pickedPath = pickData.path;
    } catch {
      setExportStatus(messages.failed, { error: true });
      setExportRunningUi(false);
      return;
    }

    try {
      const res = await fetchImpl("/api/studio/export", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          height,
          quality: elements.quality ? elements.quality.value : "high",
          output_path: pickedPath,
          project_id: projectId || state.optionsCache.project_id || null,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok || !data.job_id) {
        setExportStatus((data && data.detail) || messages.failed, { error: true });
        setExportRunningUi(false);
        return;
      }
      setExportProgressVisible(true);
      updateExportProgress({
        phase: "preparing",
        percent: 0,
        clip_index: 0,
        clip_total: 0,
        state: "running",
        elapsed_s: 0,
        eta_s: null,
      });
      setExportStatus(messages.runningHint);
      state.activeJobId = data.job_id;
      state.cancelRequested = false;
      pollExportJob(data.job_id);
    } catch {
      setExportStatus(messages.failed, { error: true });
      setExportRunningUi(false);
    }
  }

  async function requestExportCancel() {
    if (!state.activeJobId || state.cancelRequested) return;
    state.cancelRequested = true;
    if (elements.cancelButton) elements.cancelButton.disabled = true;
    setExportStatus(messages.cancelling);
    try {
      const res = await fetchImpl(
        `/api/studio/export/jobs/${encodeURIComponent(state.activeJobId)}/cancel`,
        { method: "POST", headers: { Accept: "application/json" } }
      );
      if (!res.ok) {
        state.cancelRequested = false;
        if (elements.cancelButton) elements.cancelButton.disabled = false;
      }
    } catch {
      state.cancelRequested = false;
      if (elements.cancelButton) elements.cancelButton.disabled = false;
    }
  }

  function bind() {
    on(elements.openButton, "click", () => {
      void openExportDialog();
    });
    on(elements.openFileButton, "click", () => {
      void requestExportAction("open");
    });
    on(elements.revealFileButton, "click", () => {
      void requestExportAction("reveal");
    });
    on(elements.dismissButton, "click", hideExportSuccess);
    on(elements.resolution, "change", () => {
      syncExportFilename(elements.resolution.value);
    });
    on(elements.filename, "input", refreshExportHint);
    on(elements.runButton, "click", (event) => {
      event.preventDefault();
      void runStudioExport();
    });
    on(elements.cancelButton, "click", (event) => {
      event.preventDefault();
      if (state.activeJobId) {
        void requestExportCancel();
        return;
      }
      stopExportPoll();
      if (elements.dialog && typeof elements.dialog.close === "function") {
        elements.dialog.close();
      }
    });
    on(elements.dialog, "cancel", (event) => {
      if (!state.activeJobId) return;
      event.preventDefault();
      void requestExportCancel();
    });
  }

  function destroy() {
    stopExportPoll();
    for (const { target, event, handler } of listeners.splice(0)) {
      if (typeof target.removeEventListener === "function") {
        target.removeEventListener(event, handler);
      }
    }
  }

  bind();

  return {
    openExportDialog,
    runStudioExport,
    requestExportAction,
    requestExportCancel,
    hideExportSuccess,
    stopExportPoll,
    destroy,
  };
}
