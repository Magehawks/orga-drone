/**
 * One-file export from the media detail page.
 * Photos are still images. Videos reuse the Studio MP4 job.
 * Share presets are local files. Nothing is uploaded.
 */
(function () {
  const root = document.getElementById("detail-export");
  const exportDialog = document.getElementById("detail-export-dialog");
  if (!root) return;

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
    custom: root.dataset.profileCustom || "Custom",
  };
  const profileNames = {
    original: root.dataset.profileOriginal || "Original quality",
    print: root.dataset.profilePrint || "High quality / Print",
    social: root.dataset.profileSocial || "Social media",
    custom: root.dataset.profileCustom || "Custom",
  };
  const msgDimsLabel = root.dataset.dimsLabel || "Output size";
  const msgPpiLabel = root.dataset.ppiLabel || "About {ppi} PPI at this print size";
  const msgPpiAspect = root.dataset.ppiAspect || "";
  const msgPpiGuidance = root.dataset.ppiGuidance || "";
  const msgPhotoPrintHint = root.dataset.photoPrintHint || "";
  const msgPhotoBestGps = root.dataset.photoBestGps || "";
  const msgPhotoCustom = root.dataset.photoCustom || "";

  const gradePreview = document.getElementById("detail-export-grade-preview");
  const pagePreview = document.querySelector(".photo-preview");
  const adjustPanel = document.getElementById("detail-image-adjust");
  const adjustInputs = [
    "exposure",
    "contrast",
    "saturation",
    "warmth",
    "highlights",
    "shadows",
    "blacks",
  ].map((key) => ({
    key,
    input: document.getElementById(`detail-adjust-${key}`),
    value: document.getElementById(`detail-adjust-${key}-value`),
  }));
  const lookSelect = document.getElementById("detail-quick-look");
  const lookCompare = document.getElementById("detail-look-compare");
  const imageAdjustModel = readImageAdjustModel();
  const quickLooksModel = readQuickLooksModel();
  let activeLookId = "";
  let compareOriginal = false;

  const presetSelect = document.getElementById("detail-export-preset");
  const profileSelect = document.getElementById("detail-export-profile");
  const socialSelect = document.getElementById("detail-export-social");
  const formatSelect = document.getElementById("detail-export-format");
  const widthInput = document.getElementById("detail-export-width");
  const heightInput = document.getElementById("detail-export-height");
  const lockAspectInput = document.getElementById("detail-export-lock-aspect");
  const jpegQualityInput = document.getElementById("detail-export-jpeg-quality");
  const dimsEl = document.getElementById("detail-export-dims");
  const printWrap = document.getElementById("detail-export-print-wrap");
  const printSizeSelect = document.getElementById("detail-export-print-size");
  const ppiEl = document.getElementById("detail-export-ppi");
  const ppiAspectEl = document.getElementById("detail-export-ppi-aspect");
  const ppiGuidanceEl = document.getElementById("detail-export-ppi-guidance");
  const destinationEl = document.getElementById("detail-export-destination");
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
  let customSyncFrom = null;

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

  function readQuickLooksModel() {
    const fallback = { ids: [], values: {} };
    const raw =
      (adjustPanel && adjustPanel.dataset.quickLooksModel) ||
      root.dataset.quickLooksModel ||
      "";
    try {
      const parsed = JSON.parse(raw || "");
      if (!parsed || typeof parsed !== "object") return fallback;
      return {
        ids: Array.isArray(parsed.ids) ? parsed.ids : [],
        values: parsed.values && typeof parsed.values === "object" ? parsed.values : {},
      };
    } catch (_) {
      return fallback;
    }
  }

  function readAdjust() {
    const adjust = {
      exposure: 0,
      contrast: 0,
      saturation: 0,
      warmth: 0,
      highlights: 0,
      shadows: 0,
      blacks: 0,
    };
    adjustInputs.forEach((row) => {
      adjust[row.key] = clampSlider(row.input ? row.input.value : 0);
    });
    return adjust;
  }

  function writeAdjust(adjust, { lookId = "" } = {}) {
    adjustInputs.forEach((row) => {
      if (!row.input) return;
      const value = clampSlider(adjust && adjust[row.key] != null ? adjust[row.key] : 0);
      row.input.value = String(value);
    });
    activeLookId = lookId || "";
    if (lookSelect) lookSelect.value = activeLookId;
  }

  function imageAdjustIsNeutral(adjust) {
    return (
      !adjust.exposure &&
      !adjust.contrast &&
      !adjust.saturation &&
      !adjust.warmth &&
      !adjust.highlights &&
      !adjust.shadows &&
      !adjust.blacks
    );
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
    let contrast = 1 + (adjust.contrast / 100) * imageAdjustModel.contrastDeltaAtFull;
    contrast += ((adjust.highlights || 0) / 100) * 0.08;
    contrast -= ((adjust.shadows || 0) / 100) * 0.05;
    contrast -= ((adjust.blacks || 0) / 100) * 0.04;
    contrast = Math.min(1.6, Math.max(0.4, contrast));
    if (Math.abs(contrast - 1) > 0.0005) {
      parts.push(`contrast(${contrast.toFixed(4)})`);
    }
    let brightness = Math.pow(2, (adjust.exposure / 100) * imageAdjustModel.exposureEvAtFull);
    brightness += ((adjust.shadows || 0) / 100) * 0.06;
    brightness += ((adjust.blacks || 0) / 100) * 0.04;
    brightness -= ((adjust.highlights || 0) / 100) * 0.05;
    brightness = Math.min(2.2, Math.max(0.5, brightness));
    if (Math.abs(brightness - 1) > 0.0005) {
      parts.push(`brightness(${brightness.toFixed(4)})`);
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
    if (compareOriginal || imageAdjustIsNeutral(adjust)) {
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

  function selectedProfile() {
    if (kind !== "photo" || !profileSelect) return "";
    return profileSelect.value || "original";
  }

  function selectedWirePresetId() {
    if (kind !== "photo") {
      return presetSelect ? presetSelect.value : "";
    }
    const profile = selectedProfile();
    if (profile === "social") return socialSelect ? socialSelect.value || "whatsapp" : "whatsapp";
    if (profile === "custom") return "custom";
    return "best";
  }

  function selectedPreset() {
    return presetById(selectedWirePresetId());
  }

  function selectedStillFormat() {
    const preset = selectedPreset();
    if (!formatSelect || kind !== "photo" || !preset) return null;
    if (preset.id !== "best" && preset.id !== "custom") return null;
    return formatSelect.value === "png" ? "png" : "jpeg";
  }

  function sourceSize() {
    const w = Number(optionsCache && optionsCache.source_width);
    const h = Number(optionsCache && optionsCache.source_height);
    if (Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0) return { width: w, height: h };
    const best = presetById("best");
    if (best && best.width && best.height) return { width: Number(best.width), height: Number(best.height) };
    return { width: 0, height: 0 };
  }

  function resolveCustomPreviewSize() {
    const src = sourceSize();
    const lock = !(lockAspectInput && !lockAspectInput.checked);
    let reqW = widthInput && widthInput.value !== "" ? Number(widthInput.value) : null;
    let reqH = heightInput && heightInput.value !== "" ? Number(heightInput.value) : null;
    if (!Number.isFinite(reqW) || reqW <= 0) reqW = null;
    if (!Number.isFinite(reqH) || reqH <= 0) reqH = null;
    if (!src.width || !src.height) return { width: reqW || 0, height: reqH || 0 };
    if (reqW == null && reqH == null) return src;
    if (lock) {
      if (reqW != null && reqH != null) {
        const scale = Math.min(reqW / src.width, reqH / src.height, 1);
        return {
          width: Math.max(1, Math.min(src.width, Math.round(src.width * scale))),
          height: Math.max(1, Math.min(src.height, Math.round(src.height * scale))),
        };
      }
      if (reqW != null) {
        const outW = Math.min(reqW, src.width);
        return {
          width: outW,
          height: Math.max(1, Math.min(src.height, Math.round(src.height * (outW / src.width)))),
        };
      }
      const outH = Math.min(reqH, src.height);
      return {
        width: Math.max(1, Math.min(src.width, Math.round(src.width * (outH / src.height)))),
        height: outH,
      };
    }
    return {
      width: Math.max(1, Math.min(reqW != null ? reqW : src.width, src.width)),
      height: Math.max(1, Math.min(reqH != null ? reqH : src.height, src.height)),
    };
  }

  function currentOutputSize() {
    const preset = selectedPreset();
    if (kind === "photo" && selectedProfile() === "custom") return resolveCustomPreviewSize();
    if (preset && preset.width != null && preset.height != null) {
      return { width: Number(preset.width), height: Number(preset.height) };
    }
    return sourceSize();
  }

  function syncFormatVisibility() {
    const formatWrap = document.getElementById("detail-export-format-wrap");
    const socialWrap = document.getElementById("detail-export-social-wrap");
    const customWrap = document.getElementById("detail-export-custom-wrap");
    const lockWrap = document.getElementById("detail-export-lock-wrap");
    const qualityWrap = document.getElementById("detail-export-quality-wrap");
    if (kind !== "photo") {
      if (formatWrap) formatWrap.hidden = true;
      if (socialWrap) socialWrap.hidden = true;
      if (customWrap) customWrap.hidden = true;
      if (lockWrap) lockWrap.hidden = true;
      if (qualityWrap) qualityWrap.hidden = true;
      if (printWrap) printWrap.hidden = true;
      return;
    }
    const profile = selectedProfile();
    const fmt = selectedStillFormat();
    if (formatWrap) formatWrap.hidden = !(profile === "original" || profile === "print" || profile === "custom");
    if (socialWrap) socialWrap.hidden = profile !== "social";
    if (customWrap) customWrap.hidden = profile !== "custom";
    if (lockWrap) lockWrap.hidden = profile !== "custom";
    if (qualityWrap) qualityWrap.hidden = !(profile === "custom" && fmt !== "png");
    if (printWrap) printWrap.hidden = profile !== "print";
  }

  function refreshDimensions() {
    if (!dimsEl || kind !== "photo") return;
    const size = currentOutputSize();
    if (size.width > 0 && size.height > 0) {
      dimsEl.textContent = `${msgDimsLabel}: ${size.width}×${size.height}`;
      dimsEl.hidden = false;
    } else {
      dimsEl.textContent = "";
      dimsEl.hidden = true;
    }
    refreshPpi();
  }

  function effectivePpi(exportW, exportH, widthMm, heightMm) {
    const imageLandscape = exportW >= exportH;
    const paperLandscape = widthMm >= heightMm;
    let wMm = widthMm;
    let hMm = heightMm;
    if (imageLandscape !== paperLandscape) {
      wMm = heightMm;
      hMm = widthMm;
    }
    const widthIn = wMm / 25.4;
    const heightIn = hMm / 25.4;
    return Math.min(exportW / widthIn, exportH / heightIn);
  }

  function aspectMismatch(exportW, exportH, widthMm, heightMm) {
    const imageLandscape = exportW >= exportH;
    const paperLandscape = widthMm >= heightMm;
    let wMm = widthMm;
    let hMm = heightMm;
    if (imageLandscape !== paperLandscape) {
      wMm = heightMm;
      hMm = widthMm;
    }
    const imageAr = exportW / exportH;
    const paperAr = wMm / hMm;
    return Math.abs(imageAr - paperAr) / Math.max(imageAr, paperAr) > 0.02;
  }

  function refreshPpi() {
    if (!printWrap || printWrap.hidden || !printSizeSelect || !ppiEl) return;
    const chosen = printSizeSelect.value;
    const size = currentOutputSize();
    if (!chosen || !(size.width > 0 && size.height > 0)) {
      ppiEl.hidden = true;
      ppiEl.textContent = "";
      if (ppiAspectEl) {
        ppiAspectEl.hidden = true;
        ppiAspectEl.textContent = "";
      }
      if (ppiGuidanceEl) {
        ppiGuidanceEl.hidden = true;
        ppiGuidanceEl.textContent = "";
      }
      return;
    }
    const option = printSizeSelect.selectedOptions[0];
    const widthMm = Number(option && option.dataset.widthMm);
    const heightMm = Number(option && option.dataset.heightMm);
    if (!(widthMm > 0 && heightMm > 0)) return;
    const ppi = effectivePpi(size.width, size.height, widthMm, heightMm);
    ppiEl.hidden = false;
    ppiEl.textContent = msgPpiLabel.replace("{ppi}", String(Math.round(ppi)));
    if (ppiAspectEl) {
      const mismatch = aspectMismatch(size.width, size.height, widthMm, heightMm);
      ppiAspectEl.hidden = !mismatch;
      ppiAspectEl.textContent = mismatch ? msgPpiAspect : "";
    }
    if (ppiGuidanceEl) {
      ppiGuidanceEl.hidden = false;
      ppiGuidanceEl.textContent = msgPpiGuidance;
    }
  }

  function fillPrintSizes() {
    if (!printSizeSelect || !optionsCache) return;
    const sizes = Array.isArray(optionsCache.print_sizes) ? optionsCache.print_sizes : [];
    const previous = printSizeSelect.value;
    printSizeSelect.innerHTML = "";
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = root.dataset.printChoose || "Choose a print size";
    printSizeSelect.appendChild(empty);
    sizes.forEach((row) => {
      const option = document.createElement("option");
      option.value = String(row.id);
      option.dataset.widthMm = String(row.width_mm);
      option.dataset.heightMm = String(row.height_mm);
      const wCm = Math.round(Number(row.width_mm) / 10);
      const hCm = Math.round(Number(row.height_mm) / 10);
      option.textContent = `${wCm}×${hCm} cm`;
      printSizeSelect.appendChild(option);
    });
    if (previous && sizes.some((row) => String(row.id) === previous)) {
      printSizeSelect.value = previous;
    }
  }

  function suggestionFor(preset) {
    const base = preset && preset.suggested_filename
      ? String(preset.suggested_filename)
      : (kind === "video" ? "export.mp4" : "export.jpg");
    if (kind === "photo" && preset && (preset.id === "best" || preset.id === "custom") && selectedStillFormat() === "png") {
      return base.replace(/\.[^.]+$/, ".png");
    }
    if (kind === "photo" && preset && preset.id === "custom") {
      const size = resolveCustomPreviewSize();
      if (size.width > 0 && size.height > 0) {
        const stem = base.replace(/\.[^.]+$/, "");
        const cleaned = stem.replace(/_custom(?:_\d+x\d+)?$/i, "_custom");
        const ext = selectedStillFormat() === "png" ? ".png" : ".jpg";
        return `${cleaned}_${size.width}x${size.height}${ext}`;
      }
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
      if (preset.copied) return root.dataset.photoBest || "";
      return msgPhotoBestGps || root.dataset.photoBestJpeg || "";
    }
    if (kind === "photo" && preset.id === "custom") return msgPhotoCustom;
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

  function initCustomInputs() {
    const src = sourceSize();
    if (widthInput && src.width) widthInput.value = String(src.width);
    if (heightInput && src.height) heightInput.value = String(src.height);
    if (widthInput && src.width) widthInput.max = String(src.width);
    if (heightInput && src.height) heightInput.max = String(src.height);
    const custom = presetById("custom");
    if (jpegQualityInput) {
      const def = custom && custom.jpeg_quality_default != null ? custom.jpeg_quality_default : 95;
      jpegQualityInput.value = String(def);
      if (custom && custom.jpeg_quality_min != null) jpegQualityInput.min = String(custom.jpeg_quality_min);
      if (custom && custom.jpeg_quality_max != null) jpegQualityInput.max = String(custom.jpeg_quality_max);
    }
    if (lockAspectInput) lockAspectInput.checked = true;
  }

  function syncCustomAspect(changed) {
    if (!(lockAspectInput && lockAspectInput.checked)) return;
    const src = sourceSize();
    if (!(src.width > 0 && src.height > 0)) return;
    if (changed === "width" && widthInput && heightInput) {
      const w = Number(widthInput.value);
      if (!(w > 0)) return;
      heightInput.value = String(Math.max(1, Math.min(src.height, Math.round(src.height * (Math.min(w, src.width) / src.width)))));
    }
    if (changed === "height" && widthInput && heightInput) {
      const h = Number(heightInput.value);
      if (!(h > 0)) return;
      widthInput.value = String(Math.max(1, Math.min(src.width, Math.round(src.width * (Math.min(h, src.height) / src.height)))));
    }
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
    if (profileSelect) profileSelect.disabled = running;
    if (socialSelect) socialSelect.disabled = running;
    if (exportFilename) exportFilename.disabled = running;
    if (widthInput) widthInput.disabled = running;
    if (heightInput) heightInput.disabled = running;
    if (lockAspectInput) lockAspectInput.disabled = running;
    if (jpegQualityInput) jpegQualityInput.disabled = running;
    if (printSizeSelect) printSizeSelect.disabled = running;
    adjustInputs.forEach((row) => {
      if (row.input) row.input.disabled = running;
    });
    const resetBtn = document.getElementById("detail-adjust-reset");
    if (formatSelect) formatSelect.disabled = running;
    if (resetBtn) resetBtn.disabled = running;
    if (exportCancelBtn && !cancelRequested) exportCancelBtn.disabled = !running;
  }

  function refreshHint() {
    if (!exportHint || !optionsCache) return;
    const preset = selectedPreset();
    const name = (exportFilename && exportFilename.value.trim()) || suggestionFor(preset);
    let detail = presetDetail(preset);
    if (kind === "photo" && selectedProfile() === "print" && msgPhotoPrintHint) {
      detail = detail ? `${detail} ${msgPhotoPrintHint}` : msgPhotoPrintHint;
    }
    const destDir = optionsCache.default_directory || "";
    if (destinationEl) {
      destinationEl.hidden = !destDir;
      destinationEl.textContent = destDir ? destDir : "";
    }
    const dest = destDir ? `${name} → ${destDir}` : name;
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
          if (exportDialog && typeof exportDialog.close === "function") exportDialog.close();
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
    if (exportDialog && typeof exportDialog.showModal === "function") exportDialog.showModal();
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
      if (kind === "video" && presetSelect) {
        presets.forEach((preset) => {
          const option = document.createElement("option");
          option.value = String(preset.id);
          option.textContent = optionLabel(preset);
          if (preset.id === data.default_preset) option.selected = true;
          presetSelect.appendChild(option);
        });
      }
      if (kind === "photo") {
        if (profileSelect) {
          profileSelect.value = data.default_profile || "original";
        }
        if (socialSelect) socialSelect.value = "whatsapp";
        initCustomInputs();
        fillPrintSizes();
      }
      syncFormatVisibility();
      refreshDimensions();
      syncFilename(selectedPreset(), { reset: true });
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
    if (activeLookId) body.look_id = activeLookId;
    const fmt = selectedStillFormat();
    if (fmt) body.still_format = fmt;
    body.profile = selectedProfile() || "original";
    if (preset.id === "custom") {
      const size = resolveCustomPreviewSize();
      body.width = size.width;
      body.height = size.height;
      body.lock_aspect = !(lockAspectInput && !lockAspectInput.checked);
      if (fmt !== "png" && jpegQualityInput && jpegQualityInput.value !== "") {
        body.jpeg_quality = Number(jpegQualityInput.value);
      }
    }
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
    const lookId =
      (adjustPanel && adjustPanel.dataset.photoLook) || root.dataset.photoLook || "";
    if (!saved || typeof saved !== "object") {
      writeAdjust({}, { lookId: lookId || "" });
      return;
    }
    writeAdjust(saved, { lookId: lookId || "" });
  }

  async function saveAdjust({ keepLook = false } = {}) {
    if (kind !== "photo" || !mediaId) return;
    const body = readAdjust();
    if (keepLook && activeLookId) body.look_id = activeLookId;
    else body.look_id = "";
    if (!keepLook) activeLookId = "";
    if (lookSelect && !keepLook) lookSelect.value = "";
    try {
      const res = await fetch(`/api/media/${encodeURIComponent(mediaId)}/image-adjust`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
        keepalive: true,
      });
      const data = await res.json().catch(() => null);
      if (res.ok && data && data.look_id != null) {
        activeLookId = data.look_id || "";
        if (lookSelect) lookSelect.value = activeLookId;
      }
    } catch (_) {
      /* the next visit still has the last successful save */
    }
  }

  async function applyLook(lookId) {
    const values =
      (quickLooksModel.values && quickLooksModel.values[lookId]) ||
      (lookId === "natural" ? {} : null);
    if (!lookId) {
      activeLookId = "";
      await saveAdjust({ keepLook: false });
      applyGradePreview();
      refreshHint();
      return;
    }
    if (!values && lookId !== "natural") return;
    writeAdjust(values || {}, { lookId });
    applyGradePreview();
    refreshHint();
    await saveAdjust({ keepLook: true });
  }

  function resetAdjust() {
    writeAdjust({}, { lookId: "" });
    compareOriginal = false;
    if (lookCompare) lookCompare.checked = false;
    applyGradePreview();
    refreshHint();
    saveAdjust({ keepLook: false });
  }

  function onExportControlsChanged({ resetName = false } = {}) {
    syncFormatVisibility();
    refreshDimensions();
    syncFilename(selectedPreset(), { reset: resetName });
    refreshHint();
  }

  presetSelect?.addEventListener("change", () => onExportControlsChanged({ resetName: true }));
  profileSelect?.addEventListener("change", () => onExportControlsChanged({ resetName: true }));
  socialSelect?.addEventListener("change", () => onExportControlsChanged({ resetName: true }));
  formatSelect?.addEventListener("change", () => onExportControlsChanged({ resetName: true }));
  printSizeSelect?.addEventListener("change", () => refreshPpi());
  lockAspectInput?.addEventListener("change", () => {
    if (lockAspectInput.checked) syncCustomAspect("width");
    onExportControlsChanged({ resetName: true });
  });
  widthInput?.addEventListener("input", () => {
    syncCustomAspect("width");
    onExportControlsChanged({ resetName: true });
  });
  heightInput?.addEventListener("input", () => {
    syncCustomAspect("height");
    onExportControlsChanged({ resetName: true });
  });
  jpegQualityInput?.addEventListener("change", () => refreshHint());
  document.getElementById("detail-adjust-reset")?.addEventListener("click", (event) => {
    event.preventDefault();
    resetAdjust();
  });
  lookSelect?.addEventListener("change", () => {
    applyLook(lookSelect.value || "");
  });
  lookCompare?.addEventListener("change", () => {
    compareOriginal = Boolean(lookCompare.checked);
    applyGradePreview();
  });
  adjustInputs.forEach((row) => {
    row.input?.addEventListener("input", () => {
      if (activeLookId) {
        activeLookId = "";
        if (lookSelect) lookSelect.value = "";
      }
      applyGradePreview();
      refreshHint();
    });
    row.input?.addEventListener("change", () => {
      saveAdjust({ keepLook: false });
    });
  });
  window.addEventListener("pagehide", () => {
    saveAdjust({ keepLook: Boolean(activeLookId) });
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
    if (exportDialog && typeof exportDialog.close === "function") exportDialog.close();
  });
  exportDialog?.addEventListener("cancel", (event) => {
    if (!activeJobId) return;
    event.preventDefault();
    requestCancel();
  });
  openDialog();
})();
