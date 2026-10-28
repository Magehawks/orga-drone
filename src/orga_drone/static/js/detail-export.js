/**
 * One-file export from the media detail page.
 * Photos are still images. Videos reuse the Studio MP4 job.
 * Share presets are local files. Nothing is uploaded.
 */
(function () {
  const root = document.getElementById("detail-export");
  const exportDialog = document.getElementById("detail-export-dialog");
  if (!root || !exportDialog) return;

  const mediaId = root.dataset.mediaId || "";
  const kind = root.dataset.kind || "";
  const msgFailed = root.dataset.exportFailed || "Export failed.";
  const msgCancelled = root.dataset.exportCancelled || "Export cancelled.";
  const msgCancelling = root.dataset.exportCancelling || "Cancelling export…";
  const msgRunning = root.dataset.exportRunning || "Exporting…";
  const msgDone = root.dataset.exportDone || "Export finished.";
  const msgPreparing = root.dataset.exportPreparing || "Preparing export…";
  const msgClip = root.dataset.exportClip || "Clip {current} of {total}";
  const msgRunningHint = root.dataset.exportRunningHint || "Export is running…";
  const msgElapsed = root.dataset.exportElapsed || "Elapsed {time}";
  const msgEta = root.dataset.exportEta || "About {time} left";
  const msgEstimating = root.dataset.exportEstimating || "Estimating…";
  const msgDoneIn = root.dataset.exportDoneIn || "Done in {time}";
  const msgSuccess = root.dataset.exportSuccess || "Exported {filename}.";
  const msgFileMissing = root.dataset.exportFileMissing || "The exported file is no longer available.";
  const msgOpenUnavailable = root.dataset.exportOpenUnavailable || "Opening the exported video is not available on this device.";
  const msgRevealUnavailable = root.dataset.exportRevealUnavailable || "Showing the file in its folder is not available on this device.";
  const msgUnavailable = root.dataset.exportUnavailable || "Export needs the desktop app for the save dialog.";
  const msgOpenVideo = root.dataset.openVideo || "Open video";
  const msgOpenImage = root.dataset.openImage || "Open image";
  const msgNoPreset = root.dataset.noPreset || "No exportable resolution for this file.";
  const presetNames = {
    best: root.dataset.presetBest || "Best quality",
    whatsapp: root.dataset.presetWhatsapp || "WhatsApp",
    instagram: root.dataset.presetInstagram || "Instagram",
    tiktok: root.dataset.presetTiktok || "TikTok",
  };

  const gradePreview = document.getElementById("detail-export-grade-preview");
  const pagePreview = document.querySelector(".photo-preview");
  const adjustInputs = ["exposure", "contrast", "saturation", "warmth"].map((key) => ({
    key,
    input: document.getElementById(`detail-adjust-${key}`),
    value: document.getElementById(`detail-adjust-${key}-value`),
  }));
  const imageAdjustModel = readImageAdjustModel();

  const presetSelect = document.getElementById("detail-export-preset");
  const exportFilename = document.getElementById("detail-export-filename");
  const exportStatus = document.getElementById("detail-export-status");
  const exportHint = document.getElementById("detail-export-hint");
  const exportRunBtn = document.getElementById("detail-export-run");
  const exportCancelBtn = document.getElementById("detail-export-cancel");
  const exportProgress = document.getElementById("detail-export-progress");
  const exportProgressBar = document.getElementById("detail-export-progress-bar");
  const exportProgressEl = document.getElementById("detail-export-progressbar");
  const exportProgressLabel = document.getElementById("detail-export-progress-label");
  const exportProgressMeta = document.getElementById("detail-export-progress-meta");

  let optionsCache = null;
  let filenameAuto = "";
  let pollTimer = null;
  let elapsedTimer = null;
  let startedAtMs = 0;
  let lastJob = null;
  let activeJobId = null;
  let cancelRequested = false;

  function readImageAdjustModel() {
    const fallback = {
      exposureEvAtFull: 1,
      contrastDeltaAtFull: 0.5,
      saturationDeltaAtFull: 1,
      warmthMiredAtFull: 60,
      neutralKelvin: 6500,
    };
    try {
      const parsed = JSON.parse(root.dataset.imageAdjustModel || "");
      if (!parsed || typeof parsed !== "object") return fallback;
      return Object.assign(fallback, parsed);
    } catch (_) {
      return fallback;
    }
  }

  function clampSlider(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(-100, Math.min(100, Math.round(number)));
  }

  function readAdjust() {
    const adjust = { exposure: 0, contrast: 0, saturation: 0, warmth: 0 };
    adjustInputs.forEach((row) => {
      adjust[row.key] = clampSlider(row.input ? row.input.value : 0);
    });
    return adjust;
  }

  function imageAdjustIsNeutral(adjust) {
    return !adjust.exposure && !adjust.contrast && !adjust.saturation && !adjust.warmth;
  }

  // Peak-normalized Tanner Helland blackbody. Keep in lockstep with
  // studio_image.blackbody_channel_gains and studio.js.
  function blackbodyGains(kelvin) {
    const temp = kelvin / 100;
    let red;
    let green;
    let blue;
    if (temp <= 66) {
      red = 255;
      green = 99.4708025861 * Math.log(temp) - 161.1195681661;
      blue = temp <= 19 ? 0 : 138.5177312231 * Math.log(temp - 10) - 305.0447927307;
    } else {
      red = 329.698727446 * (temp - 60) ** -0.1332047592;
      green = 288.1221695283 * (temp - 60) ** -0.0755148492;
      blue = 255;
    }
    const channels = [red, green, blue].map((channel) => Math.max(0, Math.min(255, channel)));
    const peak = Math.max(...channels) || 1;
    return channels.map((channel) => channel / peak);
  }

  function kelvinForWarmth(warmth) {
    const neutralMired = 1000000 / imageAdjustModel.neutralKelvin;
    const mired = neutralMired + (warmth / 100) * imageAdjustModel.warmthMiredAtFull;
    const kelvin = 1000000 / mired;
    return Math.round(Math.min(40000, Math.max(1000, kelvin)));
  }

  function cssFilterFor(adjust) {
    const parts = [];
    if (adjust.saturation) {
      const factor = 1 + (adjust.saturation / 100) * imageAdjustModel.saturationDeltaAtFull;
      parts.push(`saturate(${factor.toFixed(4)})`);
    }
    if (adjust.contrast) {
      const factor = 1 + (adjust.contrast / 100) * imageAdjustModel.contrastDeltaAtFull;
      parts.push(`contrast(${factor.toFixed(4)})`);
    }
    if (adjust.exposure) {
      const ev = (adjust.exposure / 100) * imageAdjustModel.exposureEvAtFull;
      parts.push(`brightness(${Math.pow(2, ev).toFixed(4)})`);
    }
    return parts.join(" ");
  }

  function applyGradePreview() {
    if (kind !== "photo") return;
    const adjust = readAdjust();
    adjustInputs.forEach((row) => {
      if (row.value) row.value.textContent = String(adjust[row.key]);
    });
    const targets = [gradePreview, pagePreview].filter(Boolean);
    if (imageAdjustIsNeutral(adjust)) {
      targets.forEach((el) => {
        el.style.filter = "";
      });
      return;
    }
    const css = cssFilterFor(adjust);
    if (adjust.warmth) {
      const matrix = document.getElementById("detail-export-grade-matrix");
      const [red, green, blue] = blackbodyGains(kelvinForWarmth(adjust.warmth));
      if (matrix) {
        matrix.setAttribute(
          "values",
          `${red.toFixed(6)} 0 0 0 0 0 ${green.toFixed(6)} 0 0 0 0 0 ${blue.toFixed(6)} 0 0 0 0 0 1 0`
        );
      }
      targets.forEach((el) => {
        el.style.filter = `${css} url(#detail-export-grade)`.trim();
      });
      return;
    }
    targets.forEach((el) => {
      el.style.filter = css;
    });
  }

  function presetById(id) {
    const presets = optionsCache && Array.isArray(optionsCache.presets) ? optionsCache.presets : [];
    return presets.find((row) => row.id === id) || null;
  }

  function selectedPreset() {
    const id = presetSelect ? presetSelect.value : "";
    return presetById(id);
  }

  function selectedStillFormat() {
    const select = document.getElementById("detail-export-format");
    const preset = selectedPreset();
    if (!select || kind !== "photo" || !preset || preset.id !== "best") return null;
    return select.value === "png" ? "png" : "jpeg";
  }

  function syncFormatVisibility() {
    const wrap = document.getElementById("detail-export-format-wrap");
    if (!wrap) return;
    const preset = selectedPreset();
    wrap.hidden = !(kind === "photo" && preset && preset.id === "best");
  }

  function suggestionFor(preset) {
    const base = preset && preset.suggested_filename
      ? String(preset.suggested_filename)
      : (kind === "video" ? "export.mp4" : "export.jpg");
    if (kind === "photo" && preset && preset.id === "best" && selectedStillFormat() === "png") {
      return base.replace(/\.[^.]+$/, ".png");
    }
    return base;
  }

  function fill(template, preset) {
    return String(template || "")
      .replace("{width}", preset && preset.width != null ? String(preset.width) : "")
      .replace("{height}", preset && preset.height != null ? String(preset.height) : "");
  }

  function presetDetail(preset) {
    if (!preset) return "";
    if (kind === "photo" && preset.id === "best") {
      if (selectedStillFormat() === "png") return root.dataset.gradePng || "";
      if (!imageAdjustIsNeutral(readAdjust())) return root.dataset.gradeReencode || "";
      return preset.copied ? root.dataset.photoBest || "" : root.dataset.photoBestJpeg || "";
    }
    if (kind === "photo" && preset.id === "whatsapp") return root.dataset.photoWhatsapp || "";
    if (kind === "photo" && preset.id === "instagram") return root.dataset.photoInstagram || "";
    if (kind === "photo" && preset.id === "tiktok") return root.dataset.photoTiktok || "";
    if (kind === "video" && preset.id === "best") return fill(root.dataset.videoBest, preset);
    if (kind === "video") return fill(root.dataset.videoFit, preset);
    return "";
  }

  function optionLabel(preset) {
    const name = presetNames[preset.id] || preset.id;
    if (preset.width != null && preset.height != null) {
      return `${name} — ${preset.width}×${preset.height}`;
    }
    return name;
  }

  function setStatus(message, { error = false } = {}) {
    if (!exportStatus) return;
    if (!message) {
      exportStatus.hidden = true;
      exportStatus.textContent = "";
      exportStatus.classList.remove("is-error");
      return;
    }
    exportStatus.hidden = false;
    exportStatus.textContent = message;
    exportStatus.classList.toggle("is-error", !!error);
  }

  function setProgressVisible(visible) {
    if (!exportProgress) return;
    exportProgress.hidden = !visible;
    if (!visible) exportProgress.classList.remove("is-working");
  }

  function formatDuration(totalSeconds) {
    const sec = Math.max(0, Math.round(Number(totalSeconds) || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function phaseLabel(job) {
    if (job.phase === "preparing") return msgPreparing;
    if (job.phase === "done" || job.state === "completed") return msgDone;
    if (job.phase === "rendering") {
      const current = Number(job.clip_index) || 0;
      const total = Number(job.clip_total) || 0;
      if (total > 1) {
        return msgClip.replace("{current}", String(current)).replace("{total}", String(total));
      }
    }
    return msgRunning;
  }

  function updateProgress(job, { localElapsedS = null } = {}) {
    lastJob = job;
    const percent = Math.max(0, Math.min(100, Number(job.percent) || 0));
    if (exportProgressBar) exportProgressBar.style.width = `${percent}%`;
    if (exportProgressEl) exportProgressEl.setAttribute("aria-valuenow", String(percent));
    if (exportProgress) {
      exportProgress.classList.toggle("is-working", job.state === "running" || job.state === "pending");
    }
    if (exportProgressLabel) exportProgressLabel.textContent = `${phaseLabel(job)} (${percent}%)`;
    const elapsed = localElapsedS != null ? localElapsedS : Number(job.elapsed_s) || 0;
    const elapsedText = msgElapsed.replace("{time}", formatDuration(elapsed));
    let etaText = msgEstimating;
    let etaS = job.eta_s;
    if (etaS == null && percent >= 5 && elapsed > 0 && percent < 100) {
      etaS = (elapsed / (percent / 100)) * (1 - percent / 100);
    }
    if (job.state === "completed") etaText = msgDoneIn.replace("{time}", formatDuration(elapsed));
    else if (etaS != null && Number.isFinite(Number(etaS))) etaText = msgEta.replace("{time}", formatDuration(etaS));
    if (exportProgressMeta) exportProgressMeta.textContent = `${elapsedText} · ${etaText}`;
  }

  function setRunningUi(running) {
    if (exportRunBtn) exportRunBtn.disabled = running;
    if (presetSelect) presetSelect.disabled = running;
    if (exportFilename) exportFilename.disabled = running;
    adjustInputs.forEach((row) => {
      if (row.input) row.input.disabled = running;
    });
    const formatSelect = document.getElementById("detail-export-format");
    const resetBtn = document.getElementById("detail-adjust-reset");
    if (formatSelect) formatSelect.disabled = running;
    if (resetBtn) resetBtn.disabled = running;
    if (exportCancelBtn && !cancelRequested) exportCancelBtn.disabled = false;
  }

  function refreshHint() {
    if (!exportHint || !optionsCache) return;
    const preset = selectedPreset();
    const name = (exportFilename && exportFilename.value.trim()) || suggestionFor(preset);
    const detail = presetDetail(preset);
    const dest = `${name} → ${optionsCache.default_directory || ""}`;
    exportHint.textContent = detail ? `${detail} ${dest}` : dest;
  }

  function syncFilename(preset, { reset = false } = {}) {
    const next = suggestionFor(preset);
    const current = exportFilename ? exportFilename.value.trim() : "";
    if (exportFilename && (reset || !current || current === filenameAuto)) {
      exportFilename.value = next;
      filenameAuto = next;
    }
    refreshHint();
  }

  function chosenFilename(preset) {
    const typed = exportFilename ? exportFilename.value.trim() : "";
    return typed || suggestionFor(preset);
  }

  function stopElapsed() {
    if (elapsedTimer) {
      window.clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
  }

  function startElapsed() {
    stopElapsed();
    startedAtMs = Date.now();
    elapsedTimer = window.setInterval(() => {
      if (!lastJob) return;
      updateProgress(lastJob, { localElapsedS: (Date.now() - startedAtMs) / 1000 });
    }, 1000);
  }

  function hideSuccess() {
    const banner = document.getElementById("detail-export-success");
    if (banner) banner.hidden = true;
  }

  function setSuccessError(message) {
    const errEl = document.getElementById("detail-export-success-error");
    if (!errEl) return;
    if (!message) {
      errEl.hidden = true;
      errEl.textContent = "";
      return;
    }
    errEl.hidden = false;
    errEl.textContent = message;
  }

  function showSuccess(job) {
    const banner = document.getElementById("detail-export-success");
    const titleEl = document.getElementById("detail-export-success-title");
    const pathEl = document.getElementById("detail-export-success-path");
    const openBtn = document.getElementById("detail-export-open-file");
    const revealBtn = document.getElementById("detail-export-reveal-file");
    if (!banner || !titleEl) return;
    const filename = job.filename || (job.output_path || "").split(/[/\\]/).pop() || "export";
    titleEl.textContent = msgSuccess.replace("{filename}", filename);
    if (pathEl) {
      if (job.output_path) {
        pathEl.hidden = false;
        pathEl.textContent = job.output_path;
        pathEl.title = job.output_path;
      } else {
        pathEl.hidden = true;
        pathEl.textContent = "";
      }
    }
    setSuccessError("");
    if (openBtn) {
      openBtn.hidden = job.open_available === false;
      openBtn.textContent = String(filename).toLowerCase().endsWith(".mp4") ? msgOpenVideo : msgOpenImage;
    }
    if (revealBtn) revealBtn.hidden = job.reveal_available === false;
    banner.hidden = false;
  }

  async function requestAction(action) {
    const unavailable = action === "open" ? msgOpenUnavailable : msgRevealUnavailable;
    try {
      const res = await fetch(`/api/studio/export/${action}`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => null);
      if (res.status === 503) {
        setSuccessError(unavailable);
        return;
      }
      if (!res.ok || !data || data.ok === false) {
        setSuccessError((data && data.detail) || msgFileMissing);
        return;
      }
      setSuccessError("");
    } catch (_) {
      setSuccessError(msgFileMissing);
    }
  }

  function stopPoll() {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
    stopElapsed();
  }

  function pollJob(jobId) {
    stopPoll();
    startElapsed();
    const tick = async () => {
      try {
        const res = await fetch(`/api/studio/export/jobs/${encodeURIComponent(jobId)}`, {
          headers: { Accept: "application/json" },
        });
        const data = await res.json().catch(() => null);
        if (res.status === 404) {
          stopElapsed();
          setStatus(msgFailed, { error: true });
          setRunningUi(false);
          setProgressVisible(false);
          return;
        }
        if (!res.ok || !data || !data.ok) {
          stopElapsed();
          setStatus((data && data.detail) || msgFailed, { error: true });
          setRunningUi(false);
          return;
        }
        setProgressVisible(true);
        updateProgress(data, { localElapsedS: (Date.now() - startedAtMs) / 1000 });
        if (data.state === "cancelled") {
          stopElapsed();
          activeJobId = null;
          cancelRequested = false;
          if (exportProgress) exportProgress.classList.remove("is-working");
          setProgressVisible(false);
          setStatus(msgCancelled);
          setRunningUi(false);
          return;
        }
        if (data.phase === "cancelling") {
          setStatus(msgCancelling);
          if (exportCancelBtn) exportCancelBtn.disabled = true;
          pollTimer = window.setTimeout(tick, 400);
          return;
        }
        if (data.state === "completed") {
          stopElapsed();
          activeJobId = null;
          cancelRequested = false;
          if (exportProgress) exportProgress.classList.remove("is-working");
          setRunningUi(false);
          if (typeof exportDialog.close === "function") exportDialog.close();
          showSuccess(data);
          if (optionsCache) {
            optionsCache.default_directory = data.directory || optionsCache.default_directory;
            optionsCache.last_export_directory = data.directory || null;
          }
          return;
        }
        if (data.state === "failed") {
          stopElapsed();
          activeJobId = null;
          cancelRequested = false;
          if (exportProgress) exportProgress.classList.remove("is-working");
          setStatus(data.error || msgFailed, { error: true });
          setRunningUi(false);
          return;
        }
        setStatus(msgRunningHint);
        pollTimer = window.setTimeout(tick, 400);
      } catch (_) {
        pollTimer = window.setTimeout(tick, 1000);
      }
    };
    tick();
  }

  async function openDialog() {
    hideSuccess();
    stopPoll();
    lastJob = null;
    activeJobId = null;
    cancelRequested = false;
    setStatus("");
    setProgressVisible(false);
    if (exportProgressBar) exportProgressBar.style.width = "0%";
    if (exportProgressLabel) exportProgressLabel.textContent = "";
    if (exportProgressMeta) exportProgressMeta.textContent = "";
    if (exportHint) exportHint.textContent = "";
    setRunningUi(false);
    if (exportRunBtn) exportRunBtn.disabled = true;
    if (presetSelect) presetSelect.innerHTML = "";
    filenameAuto = "";
    if (exportFilename) exportFilename.value = "";
    exportDialog.showModal();
    try {
      const res = await fetch(`/api/media/${encodeURIComponent(mediaId)}/export/options`, {
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        setStatus((data && data.detail) || msgFailed, { error: true });
        return;
      }
      optionsCache = data;
      const presets = Array.isArray(data.presets) ? data.presets : [];
      if (!presets.length) {
        setStatus(msgNoPreset, { error: true });
        if (exportHint) exportHint.textContent = msgNoPreset;
        return;
      }
      if (presetSelect) {
        presets.forEach((preset) => {
          const option = document.createElement("option");
          option.value = String(preset.id);
          option.textContent = optionLabel(preset);
          if (preset.id === data.default_preset) option.selected = true;
          presetSelect.appendChild(option);
        });
      }
      syncFilename(selectedPreset(), { reset: true });
      syncFormatVisibility();
      if (exportRunBtn) exportRunBtn.disabled = false;
    } catch (_) {
      setStatus(msgFailed, { error: true });
    }
  }

  async function runExport() {
    const preset = selectedPreset();
    if (!optionsCache || !preset || !exportRunBtn) return;
    setRunningUi(true);
    setStatus(msgRunningHint);
    setProgressVisible(false);
    let pickedPath = null;
    try {
      const pickRes = await fetch("/api/desktop/pick-save-file", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          directory: optionsCache.default_directory || "",
          filename: chosenFilename(preset),
        }),
      });
      const pickData = await pickRes.json().catch(() => null);
      if (pickRes.status === 503) {
        setStatus(msgUnavailable, { error: true });
        setRunningUi(false);
        return;
      }
      if (!pickData || pickData.status === "cancelled") {
        setStatus(msgCancelled);
        setRunningUi(false);
        return;
      }
      if (pickData.status !== "ok" || !pickData.path) {
        setStatus(msgFailed, { error: true });
        setRunningUi(false);
        return;
      }
      pickedPath = pickData.path;
    } catch (_) {
      setStatus(msgFailed, { error: true });
      setRunningUi(false);
      return;
    }

    try {
      const res = await fetch(`/api/media/${encodeURIComponent(mediaId)}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(exportBody(preset, pickedPath)),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok || !data.job_id) {
        setStatus((data && data.detail) || msgFailed, { error: true });
        setRunningUi(false);
        return;
      }
      setProgressVisible(true);
      updateProgress({
        phase: "preparing",
        percent: 0,
        clip_index: 0,
        clip_total: 1,
        state: "running",
        elapsed_s: 0,
        eta_s: null,
      });
      setStatus(msgRunningHint);
      activeJobId = data.job_id;
      cancelRequested = false;
      pollJob(data.job_id);
    } catch (_) {
      setStatus(msgFailed, { error: true });
      setRunningUi(false);
    }
  }

  async function requestCancel() {
    if (!activeJobId || cancelRequested) return;
    cancelRequested = true;
    if (exportCancelBtn) exportCancelBtn.disabled = true;
    setStatus(msgCancelling);
    try {
      const res = await fetch(
        `/api/studio/export/jobs/${encodeURIComponent(activeJobId)}/cancel`,
        { method: "POST", headers: { Accept: "application/json" } }
      );
      if (!res.ok) {
        cancelRequested = false;
        if (exportCancelBtn) exportCancelBtn.disabled = false;
      }
    } catch (_) {
      cancelRequested = false;
      if (exportCancelBtn) exportCancelBtn.disabled = false;
    }
  }

  document.getElementById("detail-export-open")?.addEventListener("click", () => {
    openDialog();
  });
  document.getElementById("detail-export-open-file")?.addEventListener("click", () => {
    requestAction("open");
  });
  document.getElementById("detail-export-reveal-file")?.addEventListener("click", () => {
    requestAction("reveal");
  });
  document.getElementById("detail-export-success-dismiss")?.addEventListener("click", () => {
    hideSuccess();
  });
  function exportBody(preset, pickedPath) {
    const body = { preset: preset.id, output_path: pickedPath };
    if (kind !== "photo") return body;
    Object.assign(body, readAdjust());
    const fmt = selectedStillFormat();
    if (fmt) body.still_format = fmt;
    return body;
  }

  function loadSavedAdjust() {
    if (kind !== "photo") return;
    let saved = null;
    try {
      saved = JSON.parse(root.dataset.imageAdjust || "");
    } catch (_) {
      saved = null;
    }
    if (!saved || typeof saved !== "object") return;
    adjustInputs.forEach((row) => {
      if (!row.input || saved[row.key] == null) return;
      row.input.value = String(clampSlider(saved[row.key]));
    });
  }

  async function saveAdjust() {
    if (kind !== "photo" || !mediaId) return;
    try {
      await fetch(`/api/media/${encodeURIComponent(mediaId)}/image-adjust`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(readAdjust()),
        keepalive: true,
      });
    } catch (_) {
      /* the next visit still has the last successful save */
    }
  }

  function resetAdjust() {
    adjustInputs.forEach((row) => {
      if (row.input) row.input.value = "0";
    });
    applyGradePreview();
    refreshHint();
    saveAdjust();
  }

  presetSelect?.addEventListener("change", () => {
    syncFormatVisibility();
    syncFilename(selectedPreset());
  });
  document.getElementById("detail-export-format")?.addEventListener("change", () => {
    syncFilename(selectedPreset());
    refreshHint();
  });
  document.getElementById("detail-adjust-reset")?.addEventListener("click", (event) => {
    event.preventDefault();
    resetAdjust();
  });
  adjustInputs.forEach((row) => {
    row.input?.addEventListener("input", () => {
      applyGradePreview();
      refreshHint();
    });
    row.input?.addEventListener("change", () => {
      saveAdjust();
    });
  });
  window.addEventListener("pagehide", () => {
    saveAdjust();
  });
  loadSavedAdjust();
  applyGradePreview();
  syncFormatVisibility();
  exportFilename?.addEventListener("input", () => {
    refreshHint();
  });
  exportRunBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    runExport();
  });
  exportCancelBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    if (activeJobId) {
      requestCancel();
      return;
    }
    stopPoll();
    if (typeof exportDialog.close === "function") exportDialog.close();
  });
  exportDialog.addEventListener("cancel", (event) => {
    if (!activeJobId) return;
    event.preventDefault();
    requestCancel();
  });
})();
