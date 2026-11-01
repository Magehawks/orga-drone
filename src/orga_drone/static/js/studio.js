/**
 * Creator Studio UI.
 * Persistence: reorder, photo duration, Title Cards, music, and transitions via APIs.
 * Playback: one project-time SoT; preview + playhead + active clip stay in sync.
 * Music is a persisted per-project soundtrack mixed into MP4 export.
 * The sequential soundtrack bed can be moved later on the Story time canvas.
 * Visual transitions (Cut / Fade through black / Crossfade) persist in SQLite.
 * A video clip's left and right edges drag Source in and Source out.
 * Photo and video image adjustments persist per clip and approximate the export grade.
 * Project browser/switcher (Issue #19) runs even when no Story grid is present.
 */
(function () {
  const root = document.getElementById("studio-root");
  if (!root) return;

  const studioMode = root.dataset.studioMode || "editor";
  const msgTitleCardFailed = root.dataset.titleCardFailed || "Could not save title card.";
  const msgCreateFailed = root.dataset.createFailed || "Could not create Studio project.";
  const msgOpenFailed = root.dataset.openFailed || "Could not open Studio project.";
  const msgDeleteFailed = root.dataset.deleteFailed || "Could not delete Studio project.";
  const msgDeleteConfirm =
    root.dataset.deleteConfirm ||
    "Delete this Studio project? Clips in this project are removed. Your media files are not deleted.";
  const msgRenamePrompt = root.dataset.renamePrompt || "New project title";
  const defaultProjectTitle = root.dataset.defaultTitle || "Your story";
  let historyGesture = "";
  const nativeFetch = window.fetch.bind(window);

  function syncHistoryButtons(undoEnabled, redoEnabled) {
    const undo = document.getElementById("studio-undo");
    const redo = document.getElementById("studio-redo");
    if (undo) undo.disabled = !undoEnabled;
    if (redo) redo.disabled = !redoEnabled;
  }

  window.fetch = function (input, init) {
    const method = String((init && init.method) || "GET").toUpperCase();
    if (historyGesture && method !== "GET" && method !== "HEAD") {
      const headers = new Headers((init && init.headers) || {});
      if (!headers.has("X-Studio-History-Group")) {
        headers.set("X-Studio-History-Group", historyGesture);
      }
      init = Object.assign({}, init || {}, { headers: headers });
    }
    const response = nativeFetch(input, init);
    if (method !== "GET" && method !== "HEAD") {
      response.then((res) => {
        const canUndo = res.headers.get("X-Studio-Can-Undo");
        if (canUndo == null) return;
        syncHistoryButtons(canUndo === "1", res.headers.get("X-Studio-Can-Redo") === "1");
      }, () => {});
    }
    return response;
  };

  function beginHistoryGesture(event) {
    const target = event.target;
    if (!target || !target.matches || !target.matches("input[type='range']")) return;
    const id = target.id || "";
    if (id === "studio-volume" || id.indexOf("music") !== -1) return;
    historyGesture = "g" + String(event.pointerId || Date.now());
  }

  function endHistoryGesture() {
    historyGesture = "";
  }

  document.addEventListener("pointerdown", beginHistoryGesture, true);
  document.addEventListener("pointerup", endHistoryGesture, true);
  document.addEventListener("pointercancel", endHistoryGesture, true);

  function isTextEditingTarget(node) {
    if (!node) return false;
    const tag = node.tagName;
    if (tag === "TEXTAREA" || tag === "SELECT" || node.isContentEditable === true) return true;
    if (tag !== "INPUT") return false;
    const type = String(node.type || "text").toLowerCase();
    return (
      type !== "range" &&
      type !== "checkbox" &&
      type !== "radio" &&
      type !== "button" &&
      type !== "submit" &&
      type !== "file" &&
      type !== "color"
    );
  }

  async function applyStudioHistory(direction) {
    const button = document.getElementById(
      direction === "undo" ? "studio-undo" : "studio-redo"
    );
    if (!button || button.disabled) return;
    const res = await nativeFetch("/api/studio/history/" + direction, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) return;
    window.location.reload();
  }

  function showRootFlash(message) {
    const el = document.getElementById("studio-flash");
    if (!el) {
      window.alert(message);
      return;
    }
    el.hidden = false;
    el.textContent = message;
  }

  async function readJson(res) {
    try {
      return await res.json();
    } catch (_err) {
      return null;
    }
  }

  async function createAndOpenProject(title) {
    const clean = (title || "").trim() || defaultProjectTitle;
    const created = await fetch("/api/studio/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ title: clean }),
    });
    const createdBody = await readJson(created);
    if (!created.ok || !createdBody || !createdBody.id) {
      throw new Error((createdBody && createdBody.detail) || msgCreateFailed);
    }
    const opened = await fetch(`/api/studio/projects/${createdBody.id}/open`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const openedBody = await readJson(opened);
    if (!opened.ok) {
      throw new Error((openedBody && openedBody.detail) || msgOpenFailed);
    }
    window.location.assign("/studio");
  }

  async function openProject(projectId) {
    const res = await fetch(`/api/studio/projects/${projectId}/open`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const body = await readJson(res);
    if (!res.ok) {
      throw new Error((body && body.detail) || msgOpenFailed);
    }
    window.location.assign("/studio");
  }

  async function renameProject(projectId, currentTitle) {
    const next = window.prompt(msgRenamePrompt, currentTitle || defaultProjectTitle);
    if (next === null) return;
    const clean = next.trim();
    if (!clean) return;
    const res = await fetch(`/api/studio/projects/${projectId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ title: clean }),
    });
    const body = await readJson(res);
    if (!res.ok) {
      throw new Error((body && body.detail) || msgTitleFailed);
    }
    window.location.reload();
  }

  async function deleteProject(projectId) {
    if (!window.confirm(msgDeleteConfirm)) return;
    const res = await fetch(`/api/studio/projects/${projectId}`, {
      method: "DELETE",
      headers: { Accept: "application/json" },
    });
    const body = await readJson(res);
    if (!res.ok) {
      throw new Error((body && body.detail) || msgDeleteFailed);
    }
    window.location.assign("/studio");
  }

  function bindProjectUi(scope) {
    if (!scope) return;
    scope.querySelectorAll("[data-studio-project-create]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const input = form.querySelector('input[name="title"]');
        const title = input && "value" in input ? String(input.value) : defaultProjectTitle;
        createAndOpenProject(title).catch((err) => showRootFlash(err.message || msgCreateFailed));
      });
    });
  }

  function handleProjectActionClick(event) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const openBtn = target.closest("[data-project-open]");
    if (openBtn) {
      event.preventDefault();
      const id = Number(openBtn.getAttribute("data-project-open") || "0");
      if (id) openProject(id).catch((err) => showRootFlash(err.message || msgOpenFailed));
      return;
    }
    const renameBtn = target.closest("[data-project-rename]");
    if (renameBtn) {
      event.preventDefault();
      const id = Number(renameBtn.getAttribute("data-project-rename") || "0");
      const current = renameBtn.getAttribute("data-project-title") || "";
      if (id) renameProject(id, current).catch((err) => showRootFlash(err.message || msgTitleFailed));
      return;
    }
    const deleteBtn = target.closest("[data-project-delete]");
    if (deleteBtn) {
      event.preventDefault();
      const id = Number(deleteBtn.getAttribute("data-project-delete") || "0");
      if (id) deleteProject(id).catch((err) => showRootFlash(err.message || msgDeleteFailed));
    }
  }

  root.addEventListener("click", handleProjectActionClick);
  bindProjectUi(root);
  const projectsDialog = document.getElementById("studio-projects-dialog");
  bindProjectUi(projectsDialog);
  if (projectsDialog) {
    projectsDialog.addEventListener("click", handleProjectActionClick);
  }
  let flushPendingTitleSave = () => {};
  const projectsOpenBtn = document.getElementById("studio-projects-open");
  if (projectsOpenBtn && projectsDialog) {
    projectsOpenBtn.addEventListener("click", () => {
      flushPendingTitleSave();
      if (typeof projectsDialog.showModal === "function") projectsDialog.showModal();
    });
  }
  const projectsCloseBtn = document.getElementById("studio-projects-close");
  if (projectsCloseBtn && projectsDialog) {
    projectsCloseBtn.addEventListener("click", () => projectsDialog.close());
  }

  const grid = document.getElementById("studio-grid");
  if (studioMode !== "editor" || !grid) return;

  const flashEl = document.getElementById("studio-flash");
  const saveStateEl = document.getElementById("studio-save-state");
  const titleInput = document.getElementById("studio-project-title");
  const previewImage = document.getElementById("studio-preview-image");
  const previewImageB = document.getElementById("studio-preview-image-b");
  const previewVideo = document.getElementById("studio-preview-video");
  const previewVideoB = document.getElementById("studio-preview-video-b");
  const previewTitlecard = document.getElementById("studio-preview-titlecard");
  const previewTitlecardB = document.getElementById("studio-preview-titlecard-b");
  const previewTitlecardTitle = document.getElementById("studio-preview-titlecard-title");
  const previewTitlecardSubtitle = document.getElementById("studio-preview-titlecard-subtitle");
  const previewTitlecardBTitle = document.getElementById("studio-preview-titlecard-b-title");
  const previewTitlecardBSubtitle = document.getElementById("studio-preview-titlecard-b-subtitle");
  const previewFadeBlack = document.getElementById("studio-preview-fade-black");
  const previewHud = document.getElementById("studio-preview-hud");
  const previewHudB = document.getElementById("studio-preview-hud-b");
  const previewAnnotations = document.getElementById("studio-preview-annotations");
  const previewAnnotationsB = document.getElementById("studio-preview-annotations-b");
  const previewMasks = document.getElementById("studio-preview-masks");
  const previewMasksB = document.getElementById("studio-preview-masks-b");
  const previewMaskHandles = document.getElementById("studio-preview-mask-handles");
  const previewMap = document.getElementById("studio-preview-map");
  const previewMapB = document.getElementById("studio-preview-map-b");
  const musicAudio = document.getElementById("studio-music-audio");
  const musicAudioNext = document.getElementById("studio-music-audio-next");
  const previewPlaceholder = document.getElementById("studio-preview-placeholder");
  const previewLoading = document.getElementById("studio-preview-loading");
  const transportTime = document.getElementById("studio-transport-time");
  const playheadEl = document.getElementById("studio-playhead");
  const tracksEl = document.getElementById("studio-tracks");
  const rulerEl = document.getElementById("studio-ruler");
  const timelineScrollEl = document.getElementById("studio-timeline-scroll");
  const timelineCanvasEl = document.getElementById("studio-timeline-canvas");
  const volumeInput = document.getElementById("studio-volume");
  const exportDialog = document.getElementById("studio-export-dialog");
  const previewFrame = document.getElementById("studio-preview-frame");
  const toggleBtn = root.querySelector('[data-transport="toggle"]');

  const defaultPhotoDuration = Number(root.dataset.defaultPhotoDuration || "3") || 3;
  const projectId = Number(root.dataset.projectId || "0") || 0;
  const msgReorderFailed = root.dataset.reorderFailed || "Could not save Studio order.";
  const msgDurationFailed = root.dataset.durationFailed || "Could not save photo duration.";
  const msgExportFailed = root.dataset.exportFailed || "Export failed.";
  const msgMusicFailed = root.dataset.musicFailed || "Could not save music settings.";
  const msgMusicPickerUnavailable = root.dataset.musicPickerUnavailable || "Choosing music needs the desktop app.";
  const msgMusicMissing = root.dataset.musicMissing || "The selected music file is no longer available.";
  const msgMusicLimit = root.dataset.musicLimit || "This story already has 8 soundtrack songs.";
  const msgMusicSongOf = root.dataset.musicSongOf || "Song {current} of {total}";
  const msgDragReorder = root.dataset.dragReorder || "Drag to reorder";
  const msgDragMusicStart =
    root.dataset.dragMusicStart || "Drag to set when the soundtrack starts";
  const msgExportCancelled = root.dataset.exportCancelled || "Export cancelled.";
  const msgExportCancelling = root.dataset.exportCancelling || "Cancelling export…";
  const msgExportNoRes = root.dataset.exportNoResolution || "No exportable video resolution in this project.";
  const msgExportRunning = root.dataset.exportRunning || "Exporting…";
  const msgExportDone = root.dataset.exportDone || "Export finished.";
  const msgExportPreparing = root.dataset.exportPreparing || "Preparing export…";
  const msgExportClip = root.dataset.exportClip || "Clip {current} of {total}";
  const msgExportCombining = root.dataset.exportCombining || "Combining clips…";
  const msgExportMixing = root.dataset.exportMixing || "Mixing music…";
  const msgExportUnavailable = root.dataset.exportUnavailable || "Export needs the desktop app for the save dialog.";
  const msgExportRunningHint = root.dataset.exportRunningHint || "Export is running…";
  const msgExportElapsed = root.dataset.exportElapsed || "Elapsed {time}";
  const msgExportDoneIn = root.dataset.exportDoneIn || "Done in {time}";
  const msgExportSuccess = root.dataset.exportSuccess || "Exported {filename}.";
  const msgExportFileMissing = root.dataset.exportFileMissing || "The exported file is no longer available.";
  const msgExportOpenUnavailable = root.dataset.exportOpenUnavailable || "Opening the exported video is not available on this device.";
  const msgExportRevealUnavailable = root.dataset.exportRevealUnavailable || "Showing the file in its folder is not available on this device.";
  const recommendedLabel = root.dataset.recommendedLabel || "recommended";
  const labelSaved = root.dataset.savedLabel || "Saved";
  const labelUnsaved = root.dataset.unsavedLabel || "Unsaved changes";
  const labelPlay = root.dataset.labelPlay || "Play";
  const labelPause = root.dataset.labelPause || "Pause";
  const msgTransitionFailed = root.dataset.transitionFailed || "Could not save the transition.";
  const msgTransitionFallback = root.dataset.transitionFallback || "";
  const msgTransitionClamped = root.dataset.transitionClamped || "";
  const transitionLabels = {
    cut: root.dataset.transitionChipCut || root.dataset.transitionCut || "Cut",
    fade_black: root.dataset.transitionChipFadeBlack || "Fade",
    crossfade: root.dataset.transitionChipCrossfade || "Crossfade",
  };
  const kindLabels = {
    photo: root.dataset.kindPhoto || "Photo",
    video: root.dataset.kindVideo || "Video",
    title_card: root.dataset.kindTitleCard || "Title card",
    unknown: root.dataset.kindUnknown || "Memory",
  };
  const msgBetween = root.dataset.transitionBetween || "Between {a} and {b}";
  const msgTransitionAria = root.dataset.transitionAria || "{type} between {a} and {b}";
  const msgTransitionNoRoom =
    root.dataset.transitionNoRoom || "Not enough clip length for this transition";
  const msgTransitionLimit =
    root.dataset.transitionLimit || "Up to {max}s with these clips";
  const msgStorySummary = root.dataset.storySummary || "{count} items · {duration}";
  const msgSectionFailed = root.dataset.sectionFailed || "Could not save the section.";
  const msgForwardLoopHint =
    root.dataset.forwardLoopHint ||
    "Repeats this section forward until the soundtrack ends. The soundtrack plays once and is not restarted at each join. Joins use the loop effect.";
  const msgLoopEffectIdle =
    root.dataset.loopEffectIdle || "Repeat this section more than once to use a loop effect.";
  const msgLoopMatchLow =
    root.dataset.loopMatchLow ||
    "No reliable seam was found. The original range stays, with a hard cut.";
  const msgLoopMatchOk =
    root.dataset.loopMatchOk ||
    "Effective loop: {start}–{end} s. This is not a guaranteed seamless join.";
  const msgLoopMatchStale =
    root.dataset.loopMatchStale ||
    "The section changed. Run smart frame matching again to update the seam.";
  const msgLoopMatchFade =
    root.dataset.loopMatchFade ||
    "A short crossfade was added at the seam. Both pictures keep moving forward.";
  const msgForwardLoopUnknown =
    root.dataset.forwardLoopUnknown ||
    "Soundtrack duration is unknown, so this section is not repeated to it.";
  const msgForwardLoopFilled =
    root.dataset.forwardLoopFilled ||
    "The rest of the story is already as long as the soundtrack, so this section is not extended.";
  const msgForwardLoopShort =
    root.dataset.forwardLoopShort ||
    "This section is too short to repeat through the soundtrack.";
  const msgForwardLoopOther =
    root.dataset.forwardLoopOther || "Another clip already repeats to the soundtrack.";
  const msgForwardLoopFailed =
    root.dataset.forwardLoopFailed || "Could not save the soundtrack loop.";
  const msgLoopCrossfade =
    root.dataset.loopCrossfadeHint ||
    "Blends the end of each repetition into the start of the next. Both keep moving forward. Where the start and end frames differ, a double image can remain. This does not match those frames automatically. The soundtrack plays once and is not blended.";
  const msgLoopCinematic =
    root.dataset.loopCinematicHint ||
    "Eases the end of each repetition into the start of the next. Both keep moving forward and keep the clip color settings. Roads, trees and other objects can appear doubled when the views differ. This is not an invisible loop. The soundtrack plays once and is not blended.";
  const msgLoopBlendClamped =
    root.dataset.loopBlendClamped ||
    "Blend is shortened to {seconds} s so it fits this section.";
  const msgLoopTransitionShort =
    root.dataset.loopTransitionShort ||
    "This section is too short for a crossfade, so the joins stay hard cuts.";
  const msgLoopTransitionClamped =
    root.dataset.loopTransitionClamped ||
    "Crossfade is shortened to {seconds} s so it fits this section.";
  const msgLoopTransitionOnce =
    root.dataset.loopTransitionOnce ||
    "The soundtrack ends before a second repetition, so there is no join to blend.";
  const MAX_SECTION_REPEATS = 8;
  const labelInspectorStory = root.dataset.inspectorStory || "Story";
  const labelInspectorMusic = root.dataset.inspectorMusic || "Music";
  const labelInStory = root.dataset.inStory || "In story";
  const msgCutHint = root.dataset.cutHint || "Cut splits this video at the playhead. Source files stay unchanged.";
  const msgSpeedFailed = root.dataset.speedFailed || "Could not change speed.";
  const msgImageFailed = root.dataset.imageFailed || "Could not save image adjustments.";
  const msgHslFailed = root.dataset.hslFailed || "Could not save HSL color settings.";
  const msgColorWheelsFailed = root.dataset.colorWheelsFailed || "Could not save color grading.";
  const msgColorFailed = root.dataset.colorFailed || "Could not save the color look.";
  const msgColorLutFailed = root.dataset.colorLutFailed || "Could not import that .cube LUT.";
  const msgColorLutMissing = root.dataset.colorLutMissing || "A LUT file is missing. Choose the .cube again, or clear the look.";
  const msgColorLutAlready = root.dataset.colorLutAlready || 'This file is already in your library as "{name}".';
  const msgColorLutRestored = root.dataset.colorLutRestored || 'The color file was restored in your library as "{name}".';
  const msgColorLutMissingOption = root.dataset.colorLutMissingOption || "Unknown color file (missing)";
  const msgColorFileMissingSuffix = root.dataset.colorFileMissingSuffix || "(file missing)";
  let lutCatalog = [];
  try {
    lutCatalog = JSON.parse(root.dataset.lutCatalog || "[]") || [];
  } catch (_) {
    lutCatalog = [];
  }
  if (!Array.isArray(lutCatalog)) lutCatalog = [];
  const msgColorDlogConfirm =
    root.dataset.colorDlogConfirm ||
    "Apply D-Log M conversion with your .cube LUT? Scrub or pause to see a rendered still with the file; playback approximates without it. Export applies it. Source files stay unchanged.";
  const labelColorLut = root.dataset.colorLutLabel || "LUT file";
  const msgLookFailed = root.dataset.lookFailed || "Could not apply that look.";
  const msgDetailFailed = root.dataset.detailFailed || "Could not save sharpen or denoise.";
  const msgBwFailed = root.dataset.bwFailed || "Could not save the color change.";
  let compareBeforeAfter = false;
  const msgOverlayFailed = root.dataset.overlayFailed || "Could not save overlays.";
  const msgOverlayMissing = root.dataset.overlayMissing || "Overlay image is missing.";
  const msgOverlayClamped = root.dataset.overlayClamped || "Overlay timing was shortened to fit this clip.";
  const msgOverlayLimit = root.dataset.overlayLimit || "This clip already has 8 overlays.";
  const msgMapFailed = root.dataset.mapFailed || "Could not save the flight map.";
  const msgMapEmpty = root.dataset.mapEmpty || "No GPS for this clip.";
  const msgMapLabel = root.dataset.mapLabel || "Flight map";
  const overlayModel = readOverlayModel();
  const msgMaskFailed = root.dataset.maskFailed || "Could not save privacy masks.";
  const msgMaskLimit = root.dataset.maskLimit || "A clip can have up to 8 privacy masks.";
  const labelMaskBlur = root.dataset.maskBlur || "Blur";
  const labelMaskPixelate = root.dataset.maskPixelate || "Pixelate";
  const msgMaskRemove =
    root.dataset.maskRemoveLabel || root.dataset.maskRemove || "Delete privacy mask";
  const msgFrameFailed = root.dataset.frameFailed || "Could not save framing.";
  const msgHudFailed = root.dataset.hudFailed || "Could not save the telemetry HUD.";
  const msgHudReady = root.dataset.hudReady || "Telemetry is available for this clip.";
  const msgHudMissing = root.dataset.hudMissing || "No telemetry for this clip.";
  const labelHudAvailable = root.dataset.hudAvailable || "Available";
  const labelHudUnavailable = root.dataset.hudUnavailable || "Unavailable";
  const imageAdjustModel = readImageAdjustModel();
  const maskModel = readMaskModel();
  const mapModel = readMapModel();
  let mapSaveChain = Promise.resolve();

  const STORAGE_KEY = "orga-drone-studio-ui-v1";

  /** @type {{
   *  selected: {type: 'clip'|'transition'|'music'|null, id: string|null},
   *  projectTimeS: number,
   *  musicStartS: number,
   *  tracks: Array<{id: number, name: string, volume: number, fadeIn: number, fadeOut: number, loop: boolean, available: boolean, streamUrl: string|null, durationS: number}>,
   *  activeStudioId: string|null
   * }} */
  const state = {
    selected: { type: null, id: null },
    projectTimeS: 0,
    musicStartS: Math.max(0, Number(root.dataset.musicStartS) || 0),
    playing: false,
    volume: 0.8,
    title: titleInput ? titleInput.value : "Your story",
    tracks: [],
    activeStudioId: null,
    timelineMode: "fit",
    zoomIndex: 1,
  };
  let selectedOverlayId = null;
  let overlaySaveChain = Promise.resolve();

  let dragCard = null;
  let dragOrderBefore = null;
  let musicDragCard = null;
  let musicDragOrderBefore = null;
  let playheadDragging = false;
  let playheadWasPlaying = false;
  let wallClockRaf = 0;
  let wallClockLastMs = 0;
  let suppressVideoClock = false;
  let videoLoopIndex = 0;
  let loopSeeking = false;
  let loadedVideoSrc = "";
  let loadedImageSrc = "";
  let syncToken = 0;

  function clips() {
    return Array.from(grid.querySelectorAll(".studio-clip"));
  }

  function orderedIds() {
    return clips().map((el) => Number(el.dataset.studioId));
  }

  function formatTemplate(tmpl, vars) {
    return String(tmpl || "").replace(/\{(\w+)\}/g, (_, key) =>
      vars[key] != null ? String(vars[key]) : ""
    );
  }

  function clipDisplayName(clip) {
    if (!clip) return "—";
    if (clip.dataset.kind === "title_card") {
      const title = (clip.dataset.displayTitle || "").trim();
      return title || kindLabels.title_card;
    }
    const name = (clip.dataset.filename || "").trim();
    return name || kindLabels.unknown;
  }

  function playheadTouchesClip(clip) {
    if (!clip) return false;
    const hit = resolveAt(state.projectTimeS);
    if (!hit) return false;
    const id = String(clip.dataset.studioId);
    if (String(hit.clip.dataset.studioId) === id) return true;
    return !!(hit.overlapClip && String(hit.overlapClip.dataset.studioId) === id);
  }

  function markActiveClips(primary, overlap) {
    clips().forEach((c) => {
      const on = c === primary || c === overlap;
      c.classList.toggle("is-active", on);
      const playing = c.querySelector(".studio-clip-playing-label");
      if (c === primary) {
        c.setAttribute("aria-current", "true");
        if (playing) playing.hidden = false;
      } else {
        c.removeAttribute("aria-current");
        if (playing) playing.hidden = true;
      }
    });
  }

  function setInspectorHeading(text) {
    const el = document.getElementById("studio-inspector-heading");
    if (el) el.textContent = text;
  }

  function fillEmptyInspector() {
    setInspectorHeading(labelInspectorStory);
    const titleEl = document.getElementById("inspector-empty-title");
    const summaryEl = document.getElementById("inspector-empty-summary");
    if (titleEl) titleEl.textContent = state.title || defaultProjectTitle;
    if (summaryEl) {
      summaryEl.textContent = formatTemplate(msgStorySummary, {
        count: String(clips().length),
        duration: formatTime(totalDuration()),
      });
    }
  }

  function transitionNeighbors(el) {
    const after = clips().find(
      (c) => String(c.dataset.studioId) === String(el.dataset.transitionAfter)
    );
    const before = clips().find(
      (c) => String(c.dataset.studioId) === String(el.dataset.transitionBefore)
    );
    return { after, before };
  }

  function refreshTransitionChrome(el) {
    const type = el.dataset.transitionType || "cut";
    const typeLabel = transitionLabels[type] || type;
    const { after, before } = transitionNeighbors(el);
    const a = clipDisplayName(after);
    const b = clipDisplayName(before);
    const label = formatTemplate(msgTransitionAria, { type: typeLabel, a, b });
    const dur = Number(el.dataset.appliedDuration) || 0;
    const maxHint = (() => {
      if (!after || !before || type === "cut") return "";
      const maxD = Math.min(clipDuration(after), clipDuration(before)) - 0.1;
      if (!Number.isFinite(maxD) || maxD < 0.1) {
        return msgTransitionNoRoom || "Not enough clip length for this transition";
      }
      return formatTemplate(msgTransitionLimit || "Up to {max}s with these clips", {
        max: Math.max(0.1, Math.min(2, maxD)).toFixed(1),
      });
    })();
    el.setAttribute(
      "aria-label",
      type !== "cut" && dur > 0
        ? `${label}, ${dur.toFixed(1)}s${maxHint ? `. ${maxHint}` : ""}`
        : label
    );
    el.title = maxHint || label;
    const chip = el.querySelector("[data-transition-label]");
    if (chip) chip.textContent = typeLabel;
    const span = el.querySelector("[data-transition-span]");
    if (span) {
      span.hidden = type === "cut" || dur <= 0;
      if (!span.hidden) span.textContent = `${dur.toFixed(1)}s`;
    }
  }

  function showFlash(message) {
    if (!flashEl) return;
    flashEl.textContent = message;
    flashEl.hidden = !message;
  }

  function setSaveState(saved) {
    if (!saveStateEl) return;
    saveStateEl.dataset.state = saved ? "saved" : "dirty";
    const label = saved ? labelSaved : labelUnsaved;
    const text = saveStateEl.querySelector(".studio-save-state-text");
    if (text) text.textContent = label;
    saveStateEl.setAttribute("title", label);
  }

  function formatTime(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  const MIN_CUT_SEGMENT_S = 0.05;
  const CUT_RESTORE_KEY = "orga-drone-studio-cut-restore";
  let reuseDraft = null;
  let dragOriginalMediaId = null;
  const cutBtn = root.querySelector('[data-transport="cut"]');
  const cutFailedMsg = root.dataset.cutFailed || "Could not cut clip.";

  function clipDuration(clip) {
    const raw = clip.dataset.effectiveDuration;
    if (raw === "" || raw == null) {
      if (clip.dataset.kind === "photo") return defaultPhotoDuration;
      if (clip.dataset.kind === "title_card") return 3;
      return 0;
    }
    const n = Number(raw);
    if (Number.isFinite(n) && n > 0) return n;
    if (clip.dataset.kind === "title_card") return 3;
    return 0;
  }

  function sourceInS(clip) {
    const raw = clip.dataset.sourceIn;
    if (raw === "" || raw == null) return 0;
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }

  function playbackSpeed(clip) {
    const n = Number(clip && clip.dataset.playbackSpeed);
    if (n === 0.5 || n === 0.25) return n;
    return 1;
  }

  function sourceOutS(clip) {
    const raw = clip.dataset.sourceOut;
    if (raw !== "" && raw != null) {
      const n = Number(raw);
      if (Number.isFinite(n) && n > 0) return n;
    }
    const media = Number(clip.dataset.mediaDuration);
    if (Number.isFinite(media) && media > 0) return media;
    const reps = sectionRepeats(clip);
    const speed = playbackSpeed(clip);
    const dur = clipDuration(clip);
    const cycle = reps > 0 && dur > 0 ? dur / reps : dur;
    return sourceInS(clip) + cycle * speed;
  }

  function sourceDurationS(clip) {
    return Math.max(0, sourceOutS(clip) - sourceInS(clip));
  }

  function readStoredBar(clip, key) {
    if (!clip) return null;
    try {
      const parsed = JSON.parse(clip.dataset[key] || "null");
      if (!parsed || typeof parsed !== "object") return null;
      const start = Number(parsed.start_s);
      const end = Number(parsed.end_s);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end - start < 0.05) return null;
      return { start, end, speed: Number(parsed.speed) };
    } catch (_) {
      return null;
    }
  }

  function zoomBarOf(clip) {
    if (!clip || clip.dataset.kind !== "video") return null;
    const frame = readFrame(clip);
    const zoom = Math.max(frame.zoom_start, frame.zoom_end);
    if (zoom <= 1.001) return null;
    const dur = Math.max(0.05, sourceDurationS(clip));
    const stored = readStoredBar(clip, "zoomBar");
    return stored ? { start: stored.start, end: Math.min(dur, stored.end), zoom } : { start: 0, end: dur, zoom };
  }

  function slowBarOf(clip) {
    if (!clip || clip.dataset.kind !== "video") return null;
    const dur = sourceDurationS(clip);
    const stored = readStoredBar(clip, "slowBar");
    if (stored && (stored.speed === 0.5 || stored.speed === 0.25)) {
      return { start: stored.start, end: stored.end, speed: stored.speed };
    }
    const speed = playbackSpeed(clip);
    if (speed >= 0.999 || dur < 0.05) return null;
    return { start: 0, end: dur, speed };
  }

  function speedAtSource(clip, offset) {
    const bar = slowBarOf(clip);
    if (!bar) return playbackSpeed(clip);
    if (offset >= bar.start - 0.001 && offset <= bar.end + 0.001) return bar.speed;
    return 1;
  }

  function sourceToStory(clip, offset) {
    const bar = slowBarOf(clip);
    const off = Math.max(0, offset);
    if (!bar || playbackSpeed(clip) < 0.999) return off / playbackSpeed(clip);
    if (off <= bar.start) return off;
    if (off <= bar.end) return bar.start + (off - bar.start) / bar.speed;
    return bar.start + (bar.end - bar.start) / bar.speed + (off - bar.end);
  }

  function storyToSource(clip, localS) {
    const bar = slowBarOf(clip);
    const local = Math.max(0, localS);
    if (!bar || playbackSpeed(clip) < 0.999) return local * playbackSpeed(clip);
    if (local <= bar.start) return local;
    const slowed = (bar.end - bar.start) / bar.speed;
    if (local <= bar.start + slowed) return bar.start + (local - bar.start) * bar.speed;
    return bar.end + (local - (bar.start + slowed));
  }

  let clipAudio = null;
  function clipAudioEl() {
    if (clipAudio) return clipAudio;
    clipAudio = document.createElement("audio");
    clipAudio.preload = "auto";
    clipAudio.hidden = true;
    document.body.appendChild(clipAudio);
    return clipAudio;
  }

  function syncClipAudio(video, clip) {
    const audio = clipAudioEl();
    if (!video || video !== previewVideo || !clip || clip.dataset.kind !== "video") {
      audio.pause();
      return;
    }
    const offset = clipOffsetFromMediaTime(clip, video.currentTime || 0, sourceInS(clip));
    const slow = speedAtSource(clip, offset) < 0.999;
    const stream = clip.dataset.streamUrl || "";
    const proxy = clip.dataset.hasProxy === "1";
    const range = audioPlacement(clip);
    if (slow) {
      audio.pause();
      video.muted = true;
      return;
    }
    if (lutProxyActiveFor(clip) && !range.custom) {
      audio.pause();
      video.muted = false;
      video.volume = state.volume;
      return;
    }
    if (range.custom) {
      video.muted = true;
      const speed = playbackSpeed(clip) || 1;
      const story = slowBarOf(clip) && playbackSpeed(clip) >= 0.999
        ? sourceToStory(clip, offset)
        : offset / speed;
      const into = story - range.place;
      if (!stream || into < -0.03 || into > range.story + 0.03) {
        audio.pause();
        return;
      }
      if (audio.dataset.src !== stream) {
        audio.src = stream;
        audio.dataset.src = stream;
      }
      const target = range.sourceIn + Math.max(0, into) * speed;
      if (Math.abs((audio.currentTime || 0) - target) > 0.35) {
        try { audio.currentTime = target; } catch (_) { /* seek while loading */ }
      }
      audio.volume = state.volume;
      if (video.paused) audio.pause();
      else audio.play().catch(() => {});
      return;
    }
    if (!stream) {
      audio.pause();
      video.muted = false;
      video.volume = state.volume;
      return;
    }
    if (proxy) {
      video.muted = true;
      if (audio.dataset.src !== stream) {
        audio.src = stream;
        audio.dataset.src = stream;
      }
      const target = sourceInS(clip) + offset;
      if (Math.abs((audio.currentTime || 0) - target) > 0.35) {
        try { audio.currentTime = target; } catch (_) { /* seek while loading */ }
      }
      audio.volume = state.volume;
      if (video.paused) audio.pause();
      else audio.play().catch(() => {});
      return;
    }
    audio.pause();
    video.muted = false;
    video.volume = state.volume;
  }

  function applyClipPlayback(video, clip) {
    if (!video) return;
    let speed = clip ? playbackSpeed(clip) : 1;
    if (clip && video === previewVideo && clip.dataset.kind === "video") {
      const offset = Math.max(0, (video.currentTime || 0) - sourceInS(clip));
      if (slowBarOf(clip) && playbackSpeed(clip) >= 0.999) speed = speedAtSource(clip, offset);
    }
    try {
      if (video.playbackRate !== speed) video.playbackRate = speed;
    } catch (_) {
      /* ignore unsupported rates */
    }
    if (video === previewVideo) syncClipAudio(video, clip);
  }

  function forwardLoopActive(clip) {
    return !!(clip && clip.dataset.forwardLoopActive === "1");
  }

  function loopPlayInS(clip) {
    if (clip && clip.dataset.loopMatchState === "ok") {
      const n = Number(clip.dataset.loopMatchIn);
      if (Number.isFinite(n) && n >= 0) return n;
    }
    return sourceInS(clip);
  }

  function loopPlayOutS(clip) {
    if (clip && clip.dataset.loopMatchState === "ok") {
      const n = Number(clip.dataset.loopMatchOut);
      if (Number.isFinite(n) && n > 0) return n;
    }
    const rawOut = clip && clip.dataset.sourceOut;
    if (rawOut !== "" && rawOut != null) {
      const n = Number(rawOut);
      if (Number.isFinite(n) && n > 0) return n;
    }
    const media = Number(clip && clip.dataset.mediaDuration);
    if (Number.isFinite(media) && media > 0) return media;
    return loopPlayInS(clip);
  }

  function onePlayS(clip) {
    if (!clip) return 0;
    const source = Math.max(0, loopPlayOutS(clip) - loopPlayInS(clip));
    const speed = playbackSpeed(clip);
    return speed > 0 ? source / speed : source;
  }

  function loopOverlapS(clip) {
    const n = Number(clip && clip.dataset.forwardLoopOverlap);
    if (!(Number.isFinite(n) && n > 0.001)) return 0;
    if (forwardLoopActive(clip)) return n;
    const reps = Number(clip && clip.dataset.sectionRepeats);
    if (Number.isFinite(reps) && Math.round(reps) > 1) return n;
    return 0;
  }

  function forwardLoopOverlapS(clip) {
    if (!forwardLoopActive(clip)) return 0;
    return loopOverlapS(clip);
  }

  function manualRepeatSpans(clip) {
    const cycle = onePlayS(clip);
    const reps = sectionRepeats(clip);
    if (!(cycle > 0.001) || reps < 2) return [];
    const spans = [];
    for (let i = 0; i < reps; i += 1) spans.push(cycle);
    return spans;
  }

  function forwardLoopSpans(clip) {
    const cycle = onePlayS(clip);
    const plays = Number(clip.dataset.forwardLoopPlays);
    const partial = Number(clip.dataset.forwardLoopPartial) || 0;
    if (!(plays > 0) || !(cycle > 0.001)) return [];
    const spans = [];
    const full = partial > 0.001 ? plays - 1 : plays;
    for (let i = 0; i < full; i += 1) spans.push(cycle);
    if (partial > 0.001) spans.push(partial);
    return spans;
  }

  function forwardLoopStarts(spans, overlap) {
    const starts = [];
    let cursor = 0;
    spans.forEach((span, index) => {
      starts.push(cursor);
      cursor += span;
      if (index < spans.length - 1) cursor -= overlap;
    });
    return starts;
  }

  function sectionRepeats(clip) {
    if (!clip) return 1;
    if (forwardLoopActive(clip)) {
      if (forwardLoopOverlapS(clip) > 0) {
        const plays = Number(clip.dataset.forwardLoopPlays);
        if (plays > 0) return plays;
      }
      const cycle = onePlayS(clip);
      const dur = clipDuration(clip);
      if (!(cycle > 0.001) || !(dur > 0)) return 1;
      // 0.001 matches FORWARD_LOOP_TOLERANCE_S and the preview wrap epsilon.
      return Math.max(1, Math.ceil((dur - 0.001) / cycle));
    }
    const n = Number(clip.dataset.sectionRepeats);
    if (!Number.isFinite(n)) return 1;
    const rounded = Math.round(n);
    if (rounded < 1) return 1;
    return Math.min(MAX_SECTION_REPEATS, rounded);
  }

  function sectionCycleS(clip) {
    if (forwardLoopActive(clip) || (clip && clip.dataset.loopMatchState === "ok")) {
      const story = onePlayS(clip);
      if (story > 0.001) return story;
    }
    const source = sourceOutS(clip) - sourceInS(clip);
    const speed = playbackSpeed(clip);
    const story = speed > 0 ? source / speed : source;
    if (story > 0.001) return story;
    const reps = sectionRepeats(clip);
    const dur = clipDuration(clip);
    return reps > 0 ? dur / reps : dur;
  }

  // Same mapping as section_playback_point in studio_cut.py.
  function sectionPoint(clip, localS) {
    const overlapNow = forwardLoopActive(clip) ? forwardLoopOverlapS(clip) : loopOverlapS(clip);
    if (overlapNow > 0 && (forwardLoopActive(clip) || sectionRepeats(clip) > 1)) {
      const spans = forwardLoopActive(clip) ? forwardLoopSpans(clip) : manualRepeatSpans(clip);
      const overlap = overlapNow;
      const story = clipDuration(clip);
      const local = Math.max(0, Number(localS) || 0);
      if (!spans.length || !(story > 0)) {
        return { index: 0, offset: local, atEnd: false, blending: false, progress: 0, incomingOffset: 0 };
      }
      const starts = forwardLoopStarts(spans, overlap);
      if (local >= story - 0.001) {
        const index = spans.length - 1;
        return {
          index,
          offset: spans[index],
          atEnd: true,
          blending: false,
          progress: 0,
          incomingOffset: 0,
        };
      }
      let clock = spans.length - 1;
      for (let i = 0; i < spans.length; i += 1) {
        if (local < starts[i] + spans[i] - 0.0005) {
          clock = i;
          break;
        }
      }
      const offset = Math.max(0, local - starts[clock]);
      const span = spans[clock];
      const hasNext = clock + 1 < spans.length;
      const blendStart = span - overlap;
      const blending = hasNext && offset >= blendStart - 0.0005 && offset < span;
      const progress = blending ? Math.max(0, Math.min(1, (offset - blendStart) / overlap)) : 0;
      return {
        index: clock,
        offset,
        atEnd: false,
        blending,
        progress,
        incomingOffset: blending ? Math.max(0, offset - blendStart) : 0,
      };
    }
    if (forwardLoopActive(clip)) {
      const cycle = sectionCycleS(clip);
      const dur = clipDuration(clip);
      const local = Math.max(0, Number(localS) || 0);
      if (!(cycle > 0) || !(dur > 0)) {
        return { index: 0, offset: local, atEnd: false };
      }
      const reps = sectionRepeats(clip);
      if (local >= dur - 0.001) {
        const index = Math.max(0, reps - 1);
        return { index, offset: Math.max(0, dur - index * cycle), atEnd: true };
      }
      const index = Math.min(reps - 1, Math.floor(local / cycle));
      return { index, offset: local - index * cycle, atEnd: false };
    }
    const reps = sectionRepeats(clip);
    const cycle = sectionCycleS(clip);
    const local = Math.max(0, Number(localS) || 0);
    if (reps <= 1 || !(cycle > 0)) {
      return { index: 0, offset: local, atEnd: false };
    }
    const span = cycle * reps;
    if (local >= span - 0.001) {
      return { index: reps - 1, offset: cycle, atEnd: true };
    }
    const index = Math.min(reps - 1, Math.floor(local / cycle));
    return { index, offset: local - index * cycle, atEnd: false };
  }

  function sectionSampleS(clip, localS) {
    return sectionPoint(clip, localS).offset;
  }

  function totalDuration() {
    const list = clips();
    let total = 0;
    list.forEach((clip, index) => {
      total += clipDuration(clip);
      if (index < list.length - 1 && (clip.dataset.appliedType || "cut") === "crossfade") {
        total -= Number(clip.dataset.appliedDuration) || 0;
      }
    });
    return Math.max(0, total);
  }

  const TIMELINE_ZOOM_PX_S = [20, 40, 80, 160, 320, 640, 1280];
  const TIMELINE_HIT_MIN_PX = 12;
  const TIMELINE_EXPORT_FPS = 30;

  function clipOccupancyS(clip, index, listLength) {
    // Same last-clip rule as totalDuration(): only a non-last Crossfade shrinks occupancy.
    let duration = clipDuration(clip);
    if (
      index < listLength - 1 &&
      (clip.dataset.appliedType || "cut") === "crossfade"
    ) {
      duration -= Number(clip.dataset.appliedDuration) || 0;
    }
    return Math.max(0, duration);
  }

  function timelineViewportPx() {
    return timelineScrollEl ? timelineScrollEl.clientWidth : 0;
  }

  function timelineFitPxPerSecond() {
    const total = totalDuration();
    const view = timelineViewportPx();
    if (total <= 0 || view <= 0) return TIMELINE_ZOOM_PX_S[1];
    return view / total;
  }

  function nextZoomIndexAbove(fitPps) {
    for (let i = 0; i < TIMELINE_ZOOM_PX_S.length; i += 1) {
      if (TIMELINE_ZOOM_PX_S[i] > fitPps + 0.5) return i;
    }
    return -1;
  }

  function timelinePxPerSecond() {
    const total = totalDuration();
    const view = timelineViewportPx();
    if (total <= 0) return TIMELINE_ZOOM_PX_S[1];
    if (state.timelineMode === "fit") {
      return view > 0 ? view / total : TIMELINE_ZOOM_PX_S[1];
    }
    const idx = Math.max(0, Math.min(TIMELINE_ZOOM_PX_S.length - 1, state.zoomIndex));
    return TIMELINE_ZOOM_PX_S[idx];
  }

  function timeToX(timeS) {
    return Math.max(0, Number(timeS) || 0) * timelinePxPerSecond();
  }

  function xToTime(xPx) {
    const pps = timelinePxPerSecond();
    if (pps <= 0) return 0;
    return Math.max(0, xPx) / pps;
  }

  let selectedEffectBar = null;

  function effectLabel(kind) {
    const lane = document.getElementById("studio-effect-lane");
    if (!lane) return kind;
    if (kind === "zoom") return lane.dataset.labelZoom || "Zoom";
    if (kind === "color") return lane.dataset.labelColor || "Color";
    if (kind === "blur") return lane.dataset.labelBlur || "Blur";
    if (kind === "pixelate") return lane.dataset.labelPixelate || "Pixelate";
    return lane.dataset.labelSlow || "Slow motion";
  }

  function layoutEffectBars() {
    const lane = document.getElementById("studio-effect-lane");
    const label = document.getElementById("studio-effect-label");
    if (!lane) return;
    const videos = clips().filter((clip) => clip.dataset.kind === "video");
    const show = videos.length > 0;
    lane.hidden = !show;
    if (label) {
      label.hidden = !show;
      if (!show) label.style.minHeight = "";
    }
    if (!show) {
      lane.replaceChildren();
      lane.style.minHeight = "";
      return;
    }
    const pps = timelinePxPerSecond();
    const effectBarPx = 32;
    const effectBarGapPx = 4;
    lane.replaceChildren();
    let stack = 1;
    videos.forEach((clip) => {
      const left = Number.parseFloat(clip.style.left) || 0;
      const bars = [];
      const zoom = zoomBarOf(clip);
      if (zoom) bars.push({ kind: "zoom", id: "", start: zoom.start, end: zoom.end, label: `${effectLabel("zoom")} ${zoom.zoom.toFixed(2).replace(/0$/, "").replace(/\.0$/, "")}×` });
      readMasks(clip).forEach((mask) => {
        const dur = Math.max(0.05, sourceDurationS(clip));
        const start = mask.start_s == null ? 0 : Number(mask.start_s);
        const end = mask.end_s == null ? dur : Number(mask.end_s);
        bars.push({ kind: mask.effect, id: mask.id, start, end, label: effectLabel(mask.effect) });
      });
      const slow = slowBarOf(clip);
      if (slow) bars.push({ kind: "slow", id: "", start: slow.start, end: slow.end, speed: slow.speed, label: `${effectLabel("slow")} ${slow.speed}×` });
      const colorAnim = readColorAnimation(clip);
      if (colorAnim && colorAnim.keys && colorAnim.keys.length >= 2) {
        const start = Number(colorAnim.bar && colorAnim.bar.start_s);
        const end = Number(colorAnim.bar && colorAnim.bar.end_s);
        if (Number.isFinite(start) && Number.isFinite(end) && end - start >= 0.05) {
          const presetName = colorAnim.preset_id
            ? colorAnimPresetLabel(colorAnim.preset_id)
            : (root.dataset.colorAnimCustom || "Custom points");
          bars.push({
            kind: "color",
            id: "",
            start,
            end,
            label: `${effectLabel("color")} · ${presetName}`,
          });
        }
      }
      bars.forEach((bar, index) => {
        const storyStart = sourceToStory(clip, bar.start);
        const storyEnd = sourceToStory(clip, bar.end);
        const el = document.createElement("button");
        el.type = "button";
        el.className = "studio-effect-bar";
        const step = effectBarPx + effectBarGapPx;
        el.style.left = `${left + storyStart * pps}px`;
        el.style.width = `${Math.max(12, (storyEnd - storyStart) * pps)}px`;
        el.style.top = `${effectBarGapPx + index * step}px`;
        el.style.height = `${effectBarPx}px`;
        el.dataset.kind = bar.kind === "blur" || bar.kind === "pixelate" ? "mask" : bar.kind;
        el.dataset.effect = bar.kind;
        el.dataset.maskId = bar.id;
        el.dataset.studioId = clip.dataset.studioId || "";
        el.dataset.speed = bar.speed ? String(bar.speed) : "";
        el.textContent = bar.label;
        const edgeIn = document.createElement("span");
        edgeIn.className = "studio-effect-edge studio-effect-edge-in";
        const edgeOut = document.createElement("span");
        edgeOut.className = "studio-effect-edge studio-effect-edge-out";
        el.append(edgeIn, edgeOut);
        if (selectedEffectBar && selectedEffectBar.studioId === el.dataset.studioId && selectedEffectBar.kind === el.dataset.kind && selectedEffectBar.id === el.dataset.maskId) {
          el.classList.add("is-selected");
        }
        el.addEventListener("pointerdown", (event) => onEffectPointerDown(event, el, clip));
        lane.appendChild(el);
        stack = Math.max(stack, index + 1);
      });
    });
    const step = effectBarPx + effectBarGapPx;
    lane.style.minHeight = `${effectBarGapPx + stack * step}px`;
    if (label) label.style.minHeight = lane.style.minHeight;
  }

  let suppressTimelineClick = false;

  function readClipAudio(clip) {
    if (!clip) return null;
    try {
      const parsed = JSON.parse(clip.dataset.clipAudio || "null");
      if (!parsed || parsed.active !== true) return null;
      const sourceIn = Number(parsed.source_in_s);
      const sourceOut = Number(parsed.source_out_s);
      const place = Number(parsed.place_s);
      if (!Number.isFinite(sourceIn) || !Number.isFinite(sourceOut) || sourceOut - sourceIn < 0.05) return null;
      return { sourceIn, sourceOut, place: Number.isFinite(place) ? place : 0 };
    } catch (_) {
      return null;
    }
  }

  function audioPlacement(clip) {
    const speed = playbackSpeed(clip) || 1;
    const stored = readClipAudio(clip);
    if (!stored) {
      const sourceIn = sourceInS(clip);
      const sourceOut = Math.max(sourceIn + 0.05, sourceOutS(clip));
      return {
        sourceIn,
        sourceOut,
        place: 0,
        custom: false,
        story: Math.max(0.05, (sourceOut - sourceIn) / speed),
      };
    }
    return {
      sourceIn: stored.sourceIn,
      sourceOut: stored.sourceOut,
      place: stored.place,
      custom: true,
      story: Math.max(0.05, (stored.sourceOut - stored.sourceIn) / speed),
    };
  }

  function makeAudioBar(clip, left, width) {
    const bar = document.createElement("button");
    bar.type = "button";
    bar.className = "studio-clip-audio-bar";
    bar.style.left = `${left}px`;
    bar.style.width = `${Math.max(8, width)}px`;
    bar.dataset.studioId = clip.dataset.studioId || "";
    bar.setAttribute("aria-label", clip.dataset.filename || "Audio");
    bar.textContent = clip.dataset.filename || "";
    const edgeIn = document.createElement("span");
    edgeIn.className = "studio-clip-audio-edge studio-clip-audio-edge-in";
    const edgeOut = document.createElement("span");
    edgeOut.className = "studio-clip-audio-edge studio-clip-audio-edge-out";
    bar.append(edgeIn, edgeOut);
    bar.addEventListener("pointerdown", (event) => onAudioPointerDown(event, bar, clip));
    bar.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    return bar;
  }

  function layoutClipAudio() {
    const host = document.getElementById("studio-clip-audio");
    const lane = document.getElementById("studio-clip-audio-lane");
    const label = document.getElementById("studio-audio-label");
    if (!host) return;
    host.replaceChildren();
    const videos = clips().filter((clip) => clip.dataset.kind === "video");
    const show = videos.length > 0;
    if (lane) lane.hidden = !show;
    if (label) label.hidden = !show;
    if (!show) return;
    const pps = timelinePxPerSecond() || 1;
    videos.forEach((clip) => {
      const clipLeft = Number.parseFloat(clip.style.left) || 0;
      const clipWidth = Number.parseFloat(clip.style.width) || 0;
      const range = audioPlacement(clip);
      if (!range.custom) {
        if (clipWidth < 4) return;
        host.appendChild(makeAudioBar(clip, clipLeft, clipWidth));
        return;
      }
      const reps = Math.max(1, sectionRepeats(clip));
      const cycle = sectionCycleS(clip);
      const width = Math.max(8, range.story * pps);
      if (reps > 1 && cycle > 0.05) {
        for (let i = 0; i < reps; i += 1) {
          host.appendChild(makeAudioBar(clip, clipLeft + (i * cycle + range.place) * pps, width));
        }
        return;
      }
      host.appendChild(makeAudioBar(clip, clipLeft + range.place * pps, width));
    });
  }

  function onAudioPointerDown(event, el, clip) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    suppressTimelineClick = true;
    const edge = event.target.closest ? event.target.closest(".studio-clip-audio-edge") : null;
    const mode = edge && edge.classList.contains("studio-clip-audio-edge-in")
      ? "start"
      : edge && edge.classList.contains("studio-clip-audio-edge-out")
        ? "end"
        : "move";
    const origin = audioPlacement(clip);
    const originLeft = Number.parseFloat(el.style.left) || 0;
    const startX = event.clientX;
    const pps = timelinePxPerSecond() || 1;
    const speed = playbackSpeed(clip) || 1;
    const group = "audio" + String(event.pointerId || Date.now());
    pausePlayback();
    selectClip(clip.dataset.studioId, { movePlayhead: false });
    const move = (ev) => {
      const deltaStory = (ev.clientX - startX) / pps;
      let sourceIn = origin.sourceIn;
      let sourceOut = origin.sourceOut;
      let place = origin.place;
      if (mode === "move") {
        const span = origin.story;
        const limit = Math.max(span, sectionCycleS(clip) || clipDuration(clip) || span);
        place = origin.place + deltaStory;
        place = Math.max(Math.min(0, 0.05 - span), Math.min(Math.max(0, limit - 0.05), place));
      } else if (mode === "start") {
        const next = Math.max(origin.sourceIn, Math.min(origin.sourceOut - 0.05, origin.sourceIn + deltaStory * speed));
        place = origin.place + (next - origin.sourceIn) / speed;
        sourceIn = next;
      } else {
        sourceOut = Math.max(origin.sourceIn + 0.05, Math.min(origin.sourceOut, origin.sourceOut + deltaStory * speed));
      }
      const story = Math.max(0.05, (sourceOut - sourceIn) / speed);
      el.style.left = `${originLeft + (place - origin.place) * pps}px`;
      el.style.width = `${Math.max(8, story * pps)}px`;
      el.dataset.draftIn = String(sourceIn);
      el.dataset.draftOut = String(sourceOut);
      el.dataset.draftPlace = String(place);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      window.setTimeout(() => {
        suppressTimelineClick = false;
      }, 0);
      const sourceIn = Number(el.dataset.draftIn);
      const sourceOut = Number(el.dataset.draftOut);
      const place = Number(el.dataset.draftPlace);
      if (!Number.isFinite(sourceIn) || !Number.isFinite(sourceOut) || !Number.isFinite(place)) return;
      if (
        Math.abs(sourceIn - origin.sourceIn) < 0.001 &&
        Math.abs(sourceOut - origin.sourceOut) < 0.001 &&
        Math.abs(place - origin.place) < 0.001
      ) {
        return;
      }
      historyGesture = group;
      void saveClipAudio(clip, {
        source_in_s: sourceIn,
        source_out_s: sourceOut,
        place_s: place,
      });
      historyGesture = "";
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  }

  async function saveClipAudio(clip, body) {
    let res;
    try {
      res = await fetch(`/api/studio/${clip.dataset.studioId}/clip-audio`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
      });
    } catch (_) {
      showFlash("Could not update the audio.");
      layoutClipAudio();
      return;
    }
    const data = await res.json().catch(() => null);
    if (!res.ok || !data || !data.ok) {
      showFlash((data && data.detail) || "Could not update the audio.");
      layoutClipAudio();
      return;
    }
    clip.dataset.clipAudio = JSON.stringify(data.audio || {});
    layoutClipAudio();
    applyClipPlayback(previewVideo, clip);
  }

  function onEffectPointerDown(event, el, clip) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    if (el.dataset.kind === "mask" && el.dataset.maskId) {
      selectedMaskId = el.dataset.maskId;
      const already =
        state.selected &&
        state.selected.type === "clip" &&
        String(state.selected.id) === String(clip.dataset.studioId);
      if (!already) selectClip(clip.dataset.studioId, { movePlayhead: false });
      else {
        try {
          fillMaskInspector(clip);
        } catch (_) {
          /* The preview frame still follows the selected mask. */
        }
        drawPrivacyMasks();
      }
    }
    selectedEffectBar = {
      studioId: el.dataset.studioId,
      kind: el.dataset.kind,
      id: el.dataset.maskId || "",
    };
    document.querySelectorAll(".studio-effect-bar.is-selected").forEach((node) => node.classList.remove("is-selected"));
    el.classList.add("is-selected");
    const edge = event.target.closest ? event.target.closest(".studio-effect-edge") : null;
    const mode = edge && edge.classList.contains("studio-effect-edge-in")
      ? "start"
      : edge && edge.classList.contains("studio-effect-edge-out")
        ? "end"
        : "move";
    const dur = Math.max(0.05, sourceDurationS(clip));
    const origin = sourceRangeForBar(clip, el);
    const startX = event.clientX;
    const pps = timelinePxPerSecond() || 1;
    const move = (ev) => {
      const deltaStory = (ev.clientX - startX) / pps;
      const delta = playbackSpeed(clip) < 0.999 ? deltaStory * playbackSpeed(clip) : deltaStory;
      let start = origin.start;
      let end = origin.end;
      if (mode === "move") {
        const span = end - start;
        start = Math.max(0, Math.min(dur - span, origin.start + delta));
        end = start + span;
      } else if (mode === "start") {
        start = Math.max(0, Math.min(end - 0.05, origin.start + delta));
      } else {
        end = Math.max(start + 0.05, Math.min(dur, origin.end + delta));
      }
      const left = Number.parseFloat(clip.style.left) || 0;
      el.style.left = `${left + sourceToStory(clip, start) * pps}px`;
      el.style.width = `${Math.max(12, (sourceToStory(clip, end) - sourceToStory(clip, start)) * pps)}px`;
      el.dataset.draftStart = String(start);
      el.dataset.draftEnd = String(end);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const start = Number(el.dataset.draftStart);
      const end = Number(el.dataset.draftEnd);
      if (!Number.isFinite(start) || !Number.isFinite(end)) return;
      saveEffectBar(clip, {
        kind: el.dataset.kind,
        op: "update",
        id: el.dataset.maskId || "",
        start_s: start,
        end_s: end,
        speed: el.dataset.effect === "slow" ? Number(el.dataset.speed) || slowBarOf(clip)?.speed || 0.5 : undefined,
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function sourceRangeForBar(clip, el) {
    const dur = Math.max(0.05, sourceDurationS(clip));
    if (el.dataset.kind === "zoom") {
      const bar = zoomBarOf(clip);
      return bar || { start: 0, end: dur };
    }
    if (el.dataset.kind === "slow") {
      const bar = slowBarOf(clip);
      return bar || { start: 0, end: dur };
    }
    if (el.dataset.kind === "color") {
      const anim = readColorAnimation(clip);
      if (anim && anim.bar) {
        return { start: Number(anim.bar.start_s) || 0, end: Number(anim.bar.end_s) || dur };
      }
      return { start: 0, end: dur };
    }
    const mask = readMasks(clip).find((item) => item.id === el.dataset.maskId);
    if (mask && mask.start_s != null) return { start: Number(mask.start_s), end: Number(mask.end_s) };
    return { start: 0, end: dur };
  }

  async function saveEffectBar(clip, body) {
    const res = await fetch(`/api/studio/${clip.dataset.studioId}/effect-lane`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || !data || !data.ok) {
      showFlash((data && data.detail) || "Could not update the effect.");
      layoutEffectBars();
      return;
    }
    clip.dataset.frame = JSON.stringify(data.frame || {});
    clip.dataset.masks = JSON.stringify(data.masks || []);
    clip.dataset.zoomBar = JSON.stringify(data.zoom_bar);
    clip.dataset.slowBar = JSON.stringify(data.slow_bar);
    if (data.effect_lane && Object.prototype.hasOwnProperty.call(data.effect_lane, "color_animation")) {
      writeColorAnimation(clip, data.effect_lane.color_animation || null);
    }
    if (data.playback_speed != null) clip.dataset.playbackSpeed = String(data.playback_speed);
    if (data.effective_duration_s != null) clip.dataset.effectiveDuration = String(data.effective_duration_s);
    layoutTimeline();
    applyFramePreview(resolveAt(state.projectTimeS));
    drawPrivacyMasks();
    applyClipPlayback(previewVideo, clip);
    fillColorAnimationInspector(clip);
  }

  function deleteSelectedEffectBar() {
    if (!selectedEffectBar) return false;
    const clip = clips().find((item) => String(item.dataset.studioId) === String(selectedEffectBar.studioId));
    if (!clip) return false;
    const body = {
      kind: selectedEffectBar.kind,
      op: "delete",
      id: selectedEffectBar.id,
    };
    if (selectedEffectBar.kind === "slow") {
      const bar = slowBarOf(clip);
      body.speed = bar ? bar.speed : 0.5;
    }
    selectedEffectBar = null;
    saveEffectBar(clip, body);
    return true;
  }

  function layoutTimeline() {
    if (!timelineCanvasEl || !grid) return;
    const total = totalDuration();
    const pps = timelinePxPerSecond();
    const view = timelineViewportPx();
    const width =
      state.timelineMode === "fit" || total <= 0
        ? Math.max(view, 1)
        : Math.max(view, total * pps);
    timelineCanvasEl.style.width = `${width}px`;
    if (timelineScrollEl) {
      timelineScrollEl.classList.toggle(
        "is-fit",
        state.timelineMode === "fit" || total <= 0
      );
    }
    let x = 0;
    const list = clips();
    list.forEach((clip, index) => {
      const occ = clipOccupancyS(clip, index, list.length);
      const w = occ * pps;
      clip.dataset.occupancyS = occ.toFixed(4);
      clip.style.left = `${x}px`;
      clip.style.width = `${w}px`;
      clip.style.setProperty("--clip-width-px", `${w}px`);
      clip.classList.toggle("is-narrow", w > 0 && w < TIMELINE_HIT_MIN_PX);
      x += w;
    });
    grid.querySelectorAll(".studio-transition").forEach((el) => {
      const afterId = el.dataset.transitionAfter;
      const prev = clips().find((c) => String(c.dataset.studioId) === String(afterId));
      if (!prev) return;
      const boundary = (Number.parseFloat(prev.style.left) || 0) + (Number.parseFloat(prev.style.width) || 0);
      const type = el.dataset.appliedType || el.dataset.transitionType || "cut";
      const dur = Number(el.dataset.appliedDuration) || 0;
      const regionW =
        type === "cut" || dur <= 0
          ? Math.max(14, TIMELINE_HIT_MIN_PX)
          : Math.max(24, dur * pps);
      el.style.width = `${regionW}px`;
      el.style.left = `${Math.max(0, boundary - regionW / 2)}px`;
      el.classList.toggle("is-cut", type === "cut" || dur <= 0);
      el.classList.toggle("is-fade", type === "fade_black");
      el.classList.toggle("is-crossfade", type === "crossfade");
      el.style.display = dragCard ? "none" : "";
      const span = el.querySelector("[data-transition-span]");
      if (span) {
        span.hidden = type === "cut" || dur <= 0;
        if (!span.hidden) span.textContent = `${dur.toFixed(1)}s`;
      }
    });
    buildRuler();
    updatePlayheadChrome();
    updateZoomControls();
    layoutMusicSpans();
    layoutEffectBars();
    layoutClipAudio();
  }

  function centerPlayheadInView() {
    if (!timelineScrollEl || state.timelineMode === "fit") {
      if (timelineScrollEl) timelineScrollEl.scrollLeft = 0;
      return;
    }
    const x = timeToX(state.projectTimeS);
    const view = timelineViewportPx();
    timelineScrollEl.scrollLeft = Math.max(0, x - view / 2);
  }

  function keepTimeUnderClientX(timeS, clientX) {
    if (!timelineScrollEl || state.timelineMode === "fit") {
      if (timelineScrollEl) timelineScrollEl.scrollLeft = 0;
      return;
    }
    const rect = timelineScrollEl.getBoundingClientRect();
    const offset = clientX - rect.left;
    timelineScrollEl.scrollLeft = Math.max(0, timeToX(timeS) - offset);
  }

  function fitTimeline() {
    state.timelineMode = "fit";
    persistUiState();
    layoutTimeline();
    if (timelineScrollEl) timelineScrollEl.scrollLeft = 0;
  }

  function zoomIndexForPxPerSecond(targetPps) {
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < TIMELINE_ZOOM_PX_S.length; i += 1) {
      const dist = Math.abs(TIMELINE_ZOOM_PX_S[i] - targetPps);
      if (dist < bestDist) {
        best = i;
        bestDist = dist;
      }
    }
    return best;
  }

  function zoomToWindowSeconds(windowS) {
    const view = timelineViewportPx();
    const total = totalDuration();
    if (view <= 0 || windowS <= 0 || total <= 0) return;
    const targetPps = view / windowS;
    const fitPps = timelineFitPxPerSecond();
    if (targetPps <= fitPps + 0.5) {
      fitTimeline();
      return;
    }
    state.timelineMode = "zoom";
    state.zoomIndex = zoomIndexForPxPerSecond(targetPps);
    persistUiState();
    layoutTimeline();
    centerPlayheadInView();
  }

  function updateZoomControls() {
    const empty = clips().length === 0;
    const fitBtn = document.getElementById("studio-timeline-fit");
    const inBtn = document.getElementById("studio-timeline-zoom-in");
    const outBtn = document.getElementById("studio-timeline-zoom-out");
    const win10 = document.getElementById("studio-timeline-window-10");
    const win1 = document.getElementById("studio-timeline-window-1");
    const denser = nextZoomIndexAbove(timelineFitPxPerSecond());
    if (fitBtn) fitBtn.disabled = empty || state.timelineMode === "fit";
    if (outBtn) outBtn.disabled = empty || state.timelineMode === "fit";
    if (win10) win10.disabled = empty;
    if (win1) win1.disabled = empty;
    if (inBtn) {
      const atMaxZoom =
        state.timelineMode === "zoom" &&
        state.zoomIndex >= TIMELINE_ZOOM_PX_S.length - 1;
      inBtn.disabled = empty || atMaxZoom || (state.timelineMode === "fit" && denser < 0);
    }
  }

  function applyZoomStep(direction) {
    const fitPps = timelineFitPxPerSecond();
    if (direction > 0) {
      if (state.timelineMode === "fit") {
        const next = nextZoomIndexAbove(fitPps);
        if (next < 0) return false;
        state.timelineMode = "zoom";
        state.zoomIndex = next;
      } else {
        if (state.zoomIndex >= TIMELINE_ZOOM_PX_S.length - 1) return false;
        state.zoomIndex = Math.min(TIMELINE_ZOOM_PX_S.length - 1, state.zoomIndex + 1);
      }
    } else if (state.timelineMode === "fit") {
      return false;
    } else {
      const nextIndex = state.zoomIndex - 1;
      if (nextIndex < 0 || TIMELINE_ZOOM_PX_S[nextIndex] <= fitPps + 0.01) {
        state.timelineMode = "fit";
      } else {
        state.zoomIndex = nextIndex;
      }
    }
    return true;
  }

  function zoomTimeline(direction, anchorClientX) {
    const beforeScroll = timelineScrollEl ? timelineScrollEl.scrollLeft : 0;
    let anchorTime = state.projectTimeS;
    if (typeof anchorClientX === "number" && timelineScrollEl) {
      const rect = timelineScrollEl.getBoundingClientRect();
      anchorTime = xToTime(beforeScroll + (anchorClientX - rect.left));
    }
    if (!applyZoomStep(direction)) return;
    persistUiState();
    layoutTimeline();
    if (typeof anchorClientX === "number") {
      keepTimeUnderClientX(anchorTime, anchorClientX);
    } else {
      centerPlayheadInView();
    }
  }

  function clipStartTime(clip) {
    let cursor = 0;
    const list = clips();
    for (let i = 0; i < list.length; i += 1) {
      const c = list[i];
      if (c === clip) return cursor;
      cursor += clipDuration(c);
      if (i < list.length - 1 && (c.dataset.appliedType || "cut") === "crossfade") {
        cursor -= Number(c.dataset.appliedDuration) || 0;
      }
    }
    return 0;
  }

  /**
   * Map global project time to active clip + local time.
   * During a crossfade both items are returned so preview can stack them.
   */
  function resolveAt(projectTimeS) {
    const list = clips().filter((c) => clipDuration(c) > 0);
    if (!list.length) return null;
    const starts = [];
    let cursor = 0;
    list.forEach((clip, index) => {
      starts.push(cursor);
      cursor += clipDuration(clip);
      if (index < list.length - 1 && (clip.dataset.appliedType || "cut") === "crossfade") {
        cursor -= Number(clip.dataset.appliedDuration) || 0;
      }
    });
    const total = cursor;
    const t = Math.max(0, Number(projectTimeS) || 0);
    const last = list[list.length - 1];
    if (t >= total) {
      return {
        clip: last,
        index: list.length - 1,
        start: starts[starts.length - 1],
        duration: clipDuration(last),
        localS: clipDuration(last),
        atEnd: true,
        overlapClip: null,
        overlapLocalS: 0,
        crossfadeProgress: null,
        fadeBlackOpacity: 0,
      };
    }
    let primary = 0;
    for (let i = 0; i < list.length; i += 1) {
      const start = starts[i];
      const end = start + clipDuration(list[i]);
      if (t >= start && t < end) primary = i;
    }
    const clip = list[primary];
    const start = starts[primary];
    const dur = clipDuration(clip);
    const localS = t - start;
    let fadeBlackOpacity = 0;
    const incoming = primary > 0 ? list[primary - 1] : null;
    const outgoingType = clip.dataset.appliedType || "cut";
    const outgoingD = Number(clip.dataset.appliedDuration) || 0;
    if (outgoingType === "fade_black" && outgoingD > 0) {
      const half = outgoingD / 2;
      const fadeStart = dur - half;
      if (localS >= fadeStart) fadeBlackOpacity = half <= 0 ? 0 : Math.min(1, (localS - fadeStart) / half);
    }
    if (incoming && (incoming.dataset.appliedType || "cut") === "fade_black") {
      const half = (Number(incoming.dataset.appliedDuration) || 0) / 2;
      if (half > 0 && localS <= half) {
        fadeBlackOpacity = Math.max(fadeBlackOpacity, 1 - localS / half);
      }
    }
    if (incoming && (incoming.dataset.appliedType || "cut") === "crossfade") {
      const d = Number(incoming.dataset.appliedDuration) || 0;
      const intoIncoming = t - start;
      if (d > 0 && intoIncoming <= d) {
        const progress = Math.max(0, Math.min(1, intoIncoming / d));
        return {
          clip,
          index: primary,
          start,
          duration: dur,
          localS,
          atEnd: false,
          overlapClip: incoming,
          overlapLocalS: t - starts[primary - 1],
          crossfadeProgress: progress,
          fadeBlackOpacity: 0,
        };
      }
    }
    if (outgoingType === "crossfade" && outgoingD > 0 && primary < list.length - 1) {
      const nextStart = starts[primary + 1];
      if (t >= nextStart) {
        const next = list[primary + 1];
        const progress = Math.max(0, Math.min(1, (t - nextStart) / outgoingD));
        return {
          clip: next,
          index: primary + 1,
          start: nextStart,
          duration: clipDuration(next),
          localS: t - nextStart,
          atEnd: false,
          overlapClip: clip,
          overlapLocalS: localS,
          crossfadeProgress: progress,
          fadeBlackOpacity: 0,
        };
      }
    }
    return {
      clip,
      index: primary,
      start,
      duration: dur,
      localS,
      atEnd: false,
      overlapClip: null,
      overlapLocalS: 0,
      crossfadeProgress: null,
      fadeBlackOpacity,
    };
  }

  function lutProxyEligible(clip) {
    if (!clip || clip.dataset.kind !== "video") return false;
    // Custom clip-audio trim/mute/offset uses the source audio element; keep
    // that path on ordinary playback where those rules are already proven.
    if (readClipAudio(clip)) return false;
    if (playbackSpeed(clip) < 0.999 || slowBarOf(clip)) return false;
    if (sectionRepeats(clip) > 1 || forwardLoopActive(clip)) return false;
    const anim = readColorAnimation(clip);
    if (anim && Array.isArray(anim.keys) && anim.keys.length >= 2) return false;
    const ramp = readSaturationRamp(clip);
    if (ramp && ramp.enabled) return false;
    const look = readColorLook(clip);
    if ((look.conversion_lut && look.conversion_confirmed) || look.creative_lut) {
      return true;
    }
    // The WebGL LUT renderer does not sample the generated HSL/wheel cubes, so
    // these stages need the rendered proxy too (with or without a LUT).
    return !hslIsNeutral(readHsl(clip)) || !colorWheelsIsNeutral(readColorWheels(clip));
  }

  function lutProxySrcFor(clip) {
    if (!lutProxyEligible(clip)) return "";
    if (lutWebglCanHandle(clip)) return "";
    const clipId = String(clip.dataset.studioId);
    const selected = state.selected;
    const selectedMatch = !!(selected && selected.type === "clip" &&
      String(selected.id) === clipId);
    const activeMatch = state.activeStudioId != null &&
      String(state.activeStudioId) === clipId;
    if (!selectedMatch && !activeMatch) return "";
    return clip.dataset.lutProxyUrl || "";
  }

  let lutRendererA = null;
  let lutRendererB = null;

  function lookHasLut(look) {
    return !!look && !!(
      (look.conversion_lut && look.conversion_confirmed) || look.creative_lut
    );
  }

  function lutWebglCanHandle(clip) {
    if (!clip || clip.dataset.kind !== "video") return false;
    if (!window.OrgaLutPreview || !window.OrgaLutPreview.supported) return false;
    const anim = readColorAnimation(clip);
    if (anim && Array.isArray(anim.keys) && anim.keys.length >= 2) return false;
    // The WebGL preview renders grade + user LUT. HSL and colour wheels are
    // generated LUT stages that the current shader does not sample, so use the
    // still/proxy path until the renderer supports them.
    if (!hslIsNeutral(readHsl(clip))) return false;
    if (!colorWheelsIsNeutral(readColorWheels(clip))) return false;
    return lookHasLut(readColorLook(clip));
  }

  function lutRendererFor(media) {
    if (media === previewVideo) {
      if (!lutRendererA) {
        lutRendererA = window.OrgaLutPreview?.createRenderer?.() || null;
        if (lutRendererA) {
          lutRendererA.onReady = () => {
            clearLutPreviewStill();
            schedulePreviewBlit();
          };
        }
      }
      return lutRendererA;
    }
    if (media === previewVideoB) {
      if (!lutRendererB) {
        lutRendererB = window.OrgaLutPreview?.createRenderer?.() || null;
        if (lutRendererB) {
          lutRendererB.onReady = () => {
            clearLutPreviewStill();
            schedulePreviewBlit();
          };
        }
      }
      return lutRendererB;
    }
    return null;
  }

  function lutWebglReadyFor(clip) {
    if (!lutWebglCanHandle(clip)) return false;
    const media = clipForPreviewMedia(previewVideo) === clip
      ? previewVideo
      : (clipForPreviewMedia(previewVideoB) === clip ? previewVideoB : null);
    if (!media) return false;
    const renderer = lutRendererFor(media);
    return !!renderer && renderer.isReady(readColorLook(clip));
  }

  function previewLutFrameFor(media, frameW, frameH) {
    const clip = clipForPreviewMedia(media);
    if (!lutWebglCanHandle(clip)) return null;
    const renderer = lutRendererFor(media);
    if (!renderer) return null;
    const look = readColorLook(clip);
    const hit = resolveAt(state.projectTimeS);
    const localS = hit && hit.overlapClip === clip
      ? hit.overlapLocalS
      : (hit && hit.clip === clip ? hit.localS : 0);
    const adjust = compareBeforeAfter ? neutralImageAdjust() : readImageAdjustAt(clip, localS);
    const ramp = compareBeforeAfter
      ? 1
      : saturationRampMultiplier(readSaturationRamp(clip), localS);
    return renderer.render(media, {
      grade: gradeFactors(adjust, ramp),
      look,
      frameW,
      frameH,
      dpr: window.devicePixelRatio || 1,
    });
  }

  function lutWebglCanvasFor(media) {
    const clip = clipForPreviewMedia(media);
    if (!lutWebglCanHandle(clip)) return null;
    const renderer = lutRendererFor(media);
    if (!renderer || !renderer.isReady(readColorLook(clip))) return null;
    return renderer.canvas;
  }

  function lutProxyActiveFor(clip) {
    const src = lutProxySrcFor(clip);
    return !!src && loadedVideoSrc === src;
  }

  function clipMediaTarget(clip, mapped, inS) {
    return lutProxyActiveFor(clip)
      ? Math.max(0, mapped)
      : Math.max(inS, inS + mapped);
  }

  function clipOffsetFromMediaTime(clip, mediaTime, inS) {
    return lutProxyActiveFor(clip)
      ? Math.max(0, mediaTime)
      : Math.max(0, mediaTime - inS);
  }

  function videoSrcFor(clip) {
    const lutProxy = lutProxySrcFor(clip);
    if (lutProxy) return lutProxy;
    if (clip.dataset.hasProxy === "1" && clip.dataset.proxyUrl) {
      return clip.dataset.proxyUrl;
    }
    return clip.dataset.streamUrl || "";
  }

  function imageSrcFor(clip) {
    return (
      clip.dataset.previewUrl ||
      clip.dataset.streamUrl ||
      clip.dataset.thumb ||
      ""
    );
  }

  function clearVideoElement() {
    if (!previewVideo) return;
    suppressVideoClock = true;
    try {
      previewVideo.pause();
    } catch (_) {
      /* ignore */
    }
    if (loadedVideoSrc || previewVideo.getAttribute("src")) {
      loadedVideoSrc = "";
      previewVideo.removeAttribute("src");
      try {
        previewVideo.load();
      } catch (_) {
        /* ignore */
      }
    }
    previewVideo.hidden = true;
    previewVideo.classList.remove("is-pending");
  }

  let imageLoadToken = 0;

  function setPreviewLoading(on) {
    if (previewLoading) previewLoading.hidden = !on;
  }

  function revealPreviewMedia(el) {
    if (el) el.classList.remove("is-pending");
    setPreviewLoading(false);
    schedulePreviewBlit();
  }

  function holdPreviewMedia(el) {
    if (el) el.classList.add("is-pending");
    setPreviewLoading(true);
  }

  function hideOverlayLayers() {
    if (previewImageB) {
      previewImageB.hidden = true;
      previewImageB.style.opacity = "";
    }
    if (previewVideoB) {
      try {
        previewVideoB.pause();
      } catch (_) {
        /* ignore */
      }
      previewVideoB.hidden = true;
      previewVideoB.style.opacity = "";
    }
    if (previewTitlecardB) {
      previewTitlecardB.hidden = true;
      previewTitlecardB.style.opacity = "";
    }
    if (previewImage) previewImage.style.opacity = "";
    if (previewVideo) previewVideo.style.opacity = "";
    if (previewTitlecard) previewTitlecard.style.opacity = "";
    if (previewFadeBlack) {
      previewFadeBlack.hidden = true;
      previewFadeBlack.style.opacity = "0";
    }
  }

  function applyVolume() {
    if (previewVideo) previewVideo.volume = state.volume;
    syncMusicAudio();
  }

  function setToggleLabel() {
    if (!toggleBtn) return;
    const playIcon = toggleBtn.querySelector("[data-play-icon]");
    const pauseIcon = toggleBtn.querySelector("[data-pause-icon]");
    if (playIcon) playIcon.hidden = state.playing;
    if (pauseIcon) pauseIcon.hidden = !state.playing;
    toggleBtn.setAttribute("aria-label", state.playing ? labelPause : labelPlay);
    toggleBtn.setAttribute("title", state.playing ? labelPause : labelPlay);
  }

  function stopWallClock() {
    if (wallClockRaf) {
      cancelAnimationFrame(wallClockRaf);
      wallClockRaf = 0;
    }
    wallClockLastMs = 0;
  }

  function pausePlayback() {
    state.playing = false;
    stopWallClock();
    if (previewVideo) {
      try {
        previewVideo.pause();
      } catch (_) {
        /* ignore */
      }
    }
    pauseMusicAudio();
    if (clipAudio) clipAudio.pause();
    setToggleLabel();
  }

  function updatePlayheadChrome() {
    const total = totalDuration();
    let t = state.projectTimeS;
    if (total <= 0) t = 0;
    else if (t > total) t = total;
    else if (t < 0) t = 0;
    state.projectTimeS = t;
    if (playheadEl) {
      playheadEl.style.left = `${timeToX(t)}px`;
      playheadEl.setAttribute("aria-valuemax", String(total.toFixed(1)));
      playheadEl.setAttribute("aria-valuenow", String(t.toFixed(1)));
    }
    if (transportTime) {
      transportTime.textContent = `${formatTime(t)} / ${formatTime(total)}`;
    }
    root.dataset.totalS = String(total);
    root.dataset.totalLabel = formatTime(total);
    updateCutEnabled();
  }

  function hideTitlecard() {
    if (previewTitlecard) previewTitlecard.hidden = true;
  }

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

  function clampImageSlider(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(-100, Math.min(100, Math.round(number)));
  }

  function neutralImageAdjust() {
    return {
      exposure: 0,
      contrast: 0,
      saturation: 0,
      warmth: 0,
      highlights: 0,
      shadows: 0,
      blacks: 0,
    };
  }

  function readImageAdjust(clip) {
    const neutral = neutralImageAdjust();
    if (!clip) return neutral;
    try {
      const parsed = JSON.parse(clip.dataset.imageAdjust || "");
      if (!parsed || typeof parsed !== "object") return neutral;
      return {
        exposure: clampImageSlider(parsed.exposure),
        contrast: clampImageSlider(parsed.contrast),
        saturation: clampImageSlider(parsed.saturation),
        warmth: clampImageSlider(parsed.warmth),
        highlights: clampImageSlider(parsed.highlights),
        shadows: clampImageSlider(parsed.shadows),
        blacks: clampImageSlider(parsed.blacks),
      };
    } catch (_) {
      return neutral;
    }
  }

  function writeImageAdjust(clip, adjust, persisted = false) {
    if (!clip) return;
    clip.dataset.imageAdjust = JSON.stringify({
      exposure: clampImageSlider(adjust.exposure),
      contrast: clampImageSlider(adjust.contrast),
      saturation: clampImageSlider(adjust.saturation),
      warmth: clampImageSlider(adjust.warmth),
      highlights: clampImageSlider(adjust.highlights),
      shadows: clampImageSlider(adjust.shadows),
      blacks: clampImageSlider(adjust.blacks),
    });
    clip.dataset.imagePreviewDirty = persisted ? "0" : "1";
    clearLutPreviewStill();
    if (persisted && clip.dataset.kind === "video") scheduleLutProxyPrepare(clip);
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

  const HSL_RANGE_IDS = ["red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"];
  const HSL_FIELDS = [
    ["hue", "inspector-hsl-hue", "inspector-hsl-hue-value"],
    ["saturation", "inspector-hsl-saturation", "inspector-hsl-saturation-value"],
    ["luminance", "inspector-hsl-luminance", "inspector-hsl-luminance-value"],
  ];
  let selectedHslRange = "red";

  function clampHslSlider(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(-100, Math.min(100, Math.round(number)));
  }

  function neutralHslRange() {
    return { hue: 0, saturation: 0, luminance: 0 };
  }

  function neutralHslAdjust() {
    const ranges = {};
    HSL_RANGE_IDS.forEach((rangeId) => {
      ranges[rangeId] = neutralHslRange();
    });
    return { ranges };
  }

  function readHsl(clip) {
    const neutral = neutralHslAdjust();
    if (!clip) return neutral;
    try {
      const parsed = JSON.parse(clip.dataset.hsl || "");
      const ranges = parsed && parsed.ranges;
      if (!ranges || typeof ranges !== "object") return neutral;
      HSL_RANGE_IDS.forEach((rangeId) => {
        const value = ranges[rangeId];
        if (!value || typeof value !== "object") return;
        neutral.ranges[rangeId] = {
          hue: clampHslSlider(value.hue),
          saturation: clampHslSlider(value.saturation),
          luminance: clampHslSlider(value.luminance),
        };
      });
      return neutral;
    } catch (_) {
      return neutral;
    }
  }

  function hslIsNeutral(hsl) {
    if (!hsl || !hsl.ranges) return true;
    return HSL_RANGE_IDS.every((rangeId) => {
      const value = hsl.ranges[rangeId] || {};
      return !value.hue && !value.saturation && !value.luminance;
    });
  }

  function writeHsl(clip, hsl, persisted = false) {
    if (!clip) return;
    clip.dataset.hsl = JSON.stringify(hsl || neutralHslAdjust());
    clip.dataset.hslPreviewDirty = persisted ? "0" : "1";
    clearLutPreviewStill();
    if (!hslIsNeutral(hsl)) setLutPreviewChip(msgLutChipUpdating);
    if (persisted && clip.dataset.kind === "video") scheduleLutProxyPrepare(clip);
  }

  const COLOR_WHEEL_IDS = ["shadows", "midtones", "highlights"];

  function neutralColorWheelPoint() {
    return { x: 0, y: 0 };
  }

  function neutralColorWheels() {
    const wheels = {};
    COLOR_WHEEL_IDS.forEach((wheelId) => {
      wheels[wheelId] = neutralColorWheelPoint();
    });
    return { wheels };
  }

  function clampWheelCoordinate(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(-1, Math.min(1, Math.round(number * 10000) / 10000));
  }

  function normalizeColorWheelPoint(point) {
    const x = clampWheelCoordinate(point && point.x);
    const y = clampWheelCoordinate(point && point.y);
    const radius = Math.hypot(x, y);
    if (radius > 1) {
      return { x: Math.round((x / radius) * 10000) / 10000, y: Math.round((y / radius) * 10000) / 10000 };
    }
    return { x, y };
  }

  function readColorWheels(clip) {
    const neutral = neutralColorWheels();
    if (!clip) return neutral;
    try {
      const parsed = JSON.parse(clip.dataset.colorWheels || "");
      const wheels = parsed && parsed.wheels;
      if (!wheels || typeof wheels !== "object") return neutral;
      COLOR_WHEEL_IDS.forEach((wheelId) => {
        neutral.wheels[wheelId] = normalizeColorWheelPoint(wheels[wheelId]);
      });
      return neutral;
    } catch (_) {
      return neutral;
    }
  }

  function colorWheelsIsNeutral(colorWheels) {
    if (!colorWheels || !colorWheels.wheels) return true;
    return COLOR_WHEEL_IDS.every((wheelId) => {
      const point = colorWheels.wheels[wheelId] || {};
      return !point.x && !point.y;
    });
  }

  function colorWheelPointFromRect(clientX, clientY, rect) {
    const radius = Math.max(1, Math.min(rect.width, rect.height) / 2);
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    return normalizeColorWheelPoint({
      x: (Number(clientX) - centerX) / radius,
      y: (Number(clientY) - centerY) / radius,
    });
  }

  function colorWheelStatusText(point) {
    if (!point || (!point.x && !point.y)) return msgWheelNeutral;
    const hue = Math.round((Math.atan2(point.y, point.x) * 180) / Math.PI + 360) % 360;
    const strength = Math.round(Math.min(1, Math.hypot(point.x, point.y)) * 100);
    return `${hue}° · ${strength}%`;
  }

  function writeColorWheels(clip, colorWheels, persisted = false) {
    if (!clip) return;
    clip.dataset.colorWheels = JSON.stringify(colorWheels || neutralColorWheels());
    clip.dataset.colorWheelsPreviewDirty = persisted ? "0" : "1";
    clearLutPreviewStill();
    if (!colorWheelsIsNeutral(colorWheels)) setLutPreviewChip(msgLutChipUpdating);
    if (persisted && clip.dataset.kind === "video") scheduleLutProxyPrepare(clip);
  }

  // Peak-normalized Tanner Helland blackbody. Keep in lockstep with
  // studio_image.blackbody_channel_gains. ffmpeg 7.1 colortemperature on
  // rgb(127, 95, 63) at 4800 K is (127, 83, 49).
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
    const model = imageAdjustModel;
    const neutralMired = 1000000 / model.neutralKelvin;
    const mired = neutralMired + (warmth / 100) * model.warmthMiredAtFull;
    const kelvin = 1000000 / mired;
    return Math.round(Math.min(40000, Math.max(1000, kelvin)));
  }

  function gradeFactors(adjust, rampMultiplier) {
    const model = imageAdjustModel;
    let saturation = 1 + ((adjust.saturation || 0) / 100) * model.saturationDeltaAtFull;
    let contrast = 1 + ((adjust.contrast || 0) / 100) * model.contrastDeltaAtFull;
    contrast += ((adjust.highlights || 0) / 100) * 0.08;
    contrast -= ((adjust.shadows || 0) / 100) * 0.05;
    contrast -= ((adjust.blacks || 0) / 100) * 0.04;
    contrast = Math.max(0.4, Math.min(1.6, contrast));
    let brightness = Math.pow(2, ((adjust.exposure || 0) / 100) * model.exposureEvAtFull);
    brightness += ((adjust.shadows || 0) / 100) * 0.06;
    brightness += ((adjust.blacks || 0) / 100) * 0.04;
    brightness -= ((adjust.highlights || 0) / 100) * 0.05;
    brightness = Math.max(0.5, Math.min(2.2, brightness));
    const ramp = Number.isFinite(rampMultiplier) ? rampMultiplier : 1;
    const warmthGains = adjust.warmth
      ? blackbodyGains(kelvinForWarmth(adjust.warmth))
      : [1, 1, 1];
    return { saturation, contrast, brightness, ramp, warmthGains };
  }

  function cssFilterFor(adjust, rampMultiplier) {
    const factors = gradeFactors(adjust, rampMultiplier);
    const parts = [];
    if (adjust.saturation) {
      parts.push(`saturate(${factors.saturation.toFixed(4)})`);
    }
    if (Math.abs(factors.contrast - 1) > 0.0005) {
      parts.push(`contrast(${factors.contrast.toFixed(4)})`);
    }
    if (Math.abs(factors.brightness - 1) > 0.0005) {
      parts.push(`brightness(${factors.brightness.toFixed(4)})`);
    }
    if (factors.ramp < 0.9995) {
      parts.push(`saturate(${Math.max(0, factors.ramp).toFixed(4)})`);
    }
    return parts.join(" ");
  }

  function setGradeMatrix(matrixId, kelvin) {
    const matrix = document.getElementById(matrixId);
    if (!matrix) return;
    const [red, green, blue] = blackbodyGains(kelvin);
    matrix.setAttribute(
      "values",
      `${red.toFixed(6)} 0 0 0 0 0 ${green.toFixed(6)} 0 0 0 0 0 ${blue.toFixed(6)} 0 0 0 0 0 1 0`
    );
  }

  function neutralSaturationRamp() {
    return { enabled: false, start_s: 0, end_s: 0, start_saturation: 100, end_saturation: 0 };
  }

  function clampRampTime(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(-86400, Math.min(86400, Math.round(number * 10000) / 10000));
  }

  function clampRampPercent(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(0, Math.min(100, Math.round(number)));
  }

  function readSaturationRamp(clip) {
    const neutral = neutralSaturationRamp();
    if (!clip || clip.dataset.kind !== "video") return neutral;
    try {
      const parsed = JSON.parse(clip.dataset.saturationRamp || "");
      if (!parsed || typeof parsed !== "object") return neutral;
      return {
        enabled: parsed.enabled === true,
        start_s: clampRampTime(parsed.start_s),
        end_s: clampRampTime(parsed.end_s),
        start_saturation: clampRampPercent(
          parsed.start_saturation == null ? 100 : parsed.start_saturation
        ),
        end_saturation: clampRampPercent(parsed.end_saturation),
      };
    } catch (_) {
      return neutral;
    }
  }

  function writeSaturationRamp(clip, ramp, persisted = false) {
    if (!clip) return;
    clip.dataset.saturationRamp = JSON.stringify({
      enabled: ramp.enabled === true,
      start_s: clampRampTime(ramp.start_s),
      end_s: clampRampTime(ramp.end_s),
      start_saturation: clampRampPercent(ramp.start_saturation),
      end_saturation: clampRampPercent(ramp.end_saturation),
    });
    clip.dataset.rampPreviewDirty = persisted ? "0" : "1";
    clearLutPreviewStill();
  }

  function saturationRampMultiplier(ramp, localS) {
    if (!ramp || ramp.enabled !== true) return 1;
    const span = ramp.end_s - ramp.start_s;
    if (!(span > 0.001)) return 1;
    const startM = ramp.start_saturation / 100;
    const endM = ramp.end_saturation / 100;
    if (ramp.start_saturation === ramp.end_saturation) return startM;
    const local = Number(localS);
    const t = Number.isFinite(local) ? local : 0;
    if (t <= ramp.start_s) return startM;
    if (t >= ramp.end_s) return endM;
    return startM + (endM - startM) * ((t - ramp.start_s) / span);
  }

  function gradePreviewElement(el, clip, filterId, matrixId, localS) {
    if (!el) return;
    const kind = clip && clip.dataset.kind;
    const active = clip && (kind === "video" || kind === "photo") && !el.hidden;
    if (!active) {
      el.style.filter = "";
      return;
    }
    const adjust = compareBeforeAfter
      ? neutralImageAdjust()
      : readImageAdjustAt(clip, localS);
    const mult = compareBeforeAfter
      ? 1
      : saturationRampMultiplier(readSaturationRamp(clip), localS);
    if (imageAdjustIsNeutral(adjust) && mult >= 0.9995) {
      el.style.filter = "";
      return;
    }
    const css = cssFilterFor(adjust, mult);
    if (adjust.warmth) {
      setGradeMatrix(matrixId, kelvinForWarmth(adjust.warmth));
      el.style.filter = `${css} url(#${filterId})`.trim();
      return;
    }
    el.style.filter = css;
  }

  function applyPreviewGrades(hit) {
    const primary = hit && hit.clip ? hit.clip : null;
    const overlap = hit && hit.overlapClip ? hit.overlapClip : null;
    const localS = hit && Number.isFinite(hit.localS) ? hit.localS : 0;
    const overlapLocal = hit && Number.isFinite(hit.overlapLocalS) ? hit.overlapLocalS : 0;
    // A forward loop restarts each play at the in-point, matching the export
    // slices. Story time would walk the saturation ramp off the section.
    const loopPoint =
      primary && !overlap && (forwardLoopActive(primary) || sectionRepeats(primary) > 1)
        ? sectionPoint(primary, localS)
        : null;
    const primaryLocal =
      loopPoint && Number.isFinite(loopPoint.offset) ? loopPoint.offset : localS;
    const loopBlend = Boolean(loopPoint && loopPoint.blending && loopOverlapS(primary) > 0);
    // The incoming loop copy is the same clip. Grading only the story neighbor
    // left that layer on the original color while the outgoing layer stayed graded.
    const incomingClip = loopBlend ? primary : overlap;
    const incomingLocal = loopBlend
      ? (Number.isFinite(loopPoint.incomingOffset) ? loopPoint.incomingOffset : 0)
      : overlapLocal;
    gradePreviewElement(
      previewVideo,
      primary,
      "studio-preview-grade",
      "studio-preview-grade-matrix",
      primaryLocal
    );
    gradePreviewElement(
      previewImage,
      primary,
      "studio-preview-grade",
      "studio-preview-grade-matrix",
      primaryLocal
    );
    gradePreviewElement(
      previewVideoB,
      incomingClip,
      "studio-preview-grade-b",
      "studio-preview-grade-matrix-b",
      incomingLocal
    );
    gradePreviewElement(
      previewImageB,
      incomingClip,
      "studio-preview-grade-b",
      "studio-preview-grade-matrix-b",
      incomingLocal
    );
    scheduleLutPreviewStill(primary, primaryLocal);
    schedulePreviewBlit();
  }

  const previewLutStill = document.getElementById("studio-preview-lut-still");
  const previewLutChip = document.getElementById("studio-preview-lut-chip");
  const msgLutChipUpdating = root.dataset.lutChipUpdating || "Updating picture…";
  const msgLutChipStill = root.dataset.lutChipStill || "Still frame with color file";
  const msgLutChipProxyPreparing = root.dataset.lutChipProxyPreparing || "LUT video is being prepared...";
  const msgLutChipPlaying = root.dataset.lutChipPlaying || "Playing without color file";
  const msgLutChipMissing = root.dataset.lutChipMissing || "Color file missing";
  const msgLutChipFailed = root.dataset.lutChipFailed || "Color preview unavailable; try pausing or seeking again";
  const msgLutChipComposite = root.dataset.lutChipComposite || "Color still; transition colors approximate";
  const msgHslChipPlaying = root.dataset.hslChipPlaying || "Playing without HSL preview; pause or seek to see it";
  const msgColorWheelsChipPlaying = root.dataset.colorWheelsChipPlaying || "Playing without color grading preview; pause or seek to see it";
  const msgWheelNeutral = root.dataset.wheelNeutral || "Neutral";
  let lutStillAbort = null;
  let lutStillTimer = 0;
  let lutStillToken = 0;
  let lutStillObjectUrl = "";
  let lutStillKey = "";

  function colorLookNeedsStill(look, clip) {
    if (!look) return false;
    // Keep 0% on the same output color path as 50/100%, even though the LUT
    // filter itself is skipped. Browser decoding may interpret untagged video
    // differently from export's BT.709 output.
    if (look.conversion_lut && look.conversion_confirmed) return true;
    if (look.creative_lut) return true;
    return false;
  }

  function lutStillSourceOffset(clip, localS) {
    if (!clip || clip.dataset.kind !== "video") return 0;
    const offset = Math.max(0, Number(localS) || 0);
    const speed = playbackSpeed(clip);
    if (slowBarOf(clip) && speed >= 0.999) return storyToSource(clip, offset);
    return offset * speed;
  }

  function setLutPreviewChip(text) {
    if (!previewLutChip) return;
    if (!text) {
      previewLutChip.hidden = true;
      previewLutChip.textContent = "";
      return;
    }
    previewLutChip.textContent = text;
    previewLutChip.hidden = false;
  }

  function clearLutPreviewStill() {
    lutStillKey = "";
    if (lutStillTimer) {
      window.clearTimeout(lutStillTimer);
      lutStillTimer = 0;
    }
    if (lutStillAbort) {
      try {
        lutStillAbort.abort();
      } catch (_) {
        /* ignore */
      }
      lutStillAbort = null;
    }
    lutStillToken += 1;
    if (previewLutStill) {
      previewLutStill.hidden = true;
      previewLutStill.removeAttribute("src");
    }
    if (lutStillObjectUrl) {
      try {
        URL.revokeObjectURL(lutStillObjectUrl);
      } catch (_) {
        /* ignore */
      }
      lutStillObjectUrl = "";
    }
    setLutPreviewChip("");
    schedulePreviewBlit();
  }

  function scheduleLutPreviewStill(clip, localS) {
    if (!previewLutStill) return;
    if (reuseDraft || compareBeforeAfter || !clip || (clip.dataset.kind !== "video" && clip.dataset.kind !== "photo")) {
      clearLutPreviewStill();
      return;
    }
    const look = readColorLook(clip);
    const hsl = readHsl(clip);
    const colorWheels = readColorWheels(clip);
    const hslActive = !hslIsNeutral(hsl);
    const wheelsActive = !colorWheelsIsNeutral(colorWheels);
    const lookActive = colorLookNeedsStill(look, clip);
    if (!lookActive && !hslActive && !wheelsActive) {
      clearLutPreviewStill();
      return;
    }
    // The proxy already contains grade + LUT + HSL + wheels at video
    // resolution. Keep its frame for pause/seek/selection instead of
    // overpainting a soft 720-edge JPEG.
    if (lutWebglReadyFor(clip)) {
      clearLutPreviewStill();
      return;
    }
    if (lutProxySrcFor(clip)) {
      clearLutPreviewStill();
      return;
    }
    if (clip.dataset.imagePreviewDirty === "1" || clip.dataset.rampPreviewDirty === "1" ||
        clip.dataset.hslPreviewDirty === "1" || clip.dataset.colorWheelsPreviewDirty === "1") {
      clearLutPreviewStill();
      setLutPreviewChip(msgLutChipUpdating);
      return;
    }
    if (state.playing) {
      clearLutPreviewStill();
      if (lutProxySrcFor(clip)) {
        setLutPreviewChip("");
      } else if (lutProxyPreparingFor(clip)) {
        setLutPreviewChip(msgLutChipProxyPreparing);
      } else if (!lookActive && !hslActive && wheelsActive) {
        setLutPreviewChip(msgColorWheelsChipPlaying);
      } else if (!lookActive && hslActive) {
        setLutPreviewChip(msgHslChipPlaying);
      } else {
        setLutPreviewChip(msgLutChipPlaying);
      }
      return;
    }
    const studioId = clip.dataset.studioId;
    if (!studioId) {
      clearLutPreviewStill();
      return;
    }
    // t_s is source offset from the clip in-point (same mapping as seekVideoLocal).
    const sourceOff = lutStillSourceOffset(clip, localS);
    const quant = Math.round(sourceOff * 10) / 10;
    const key = JSON.stringify([studioId, quant, clip.dataset.sourceIn,
      clip.dataset.sourceOut, look, readImageAdjust(clip), hsl, colorWheels,
      clip.dataset.saturationRamp]);
    if (key === lutStillKey) return;
    // Reject old responses now, including during the debounce and image decode.
    clearLutPreviewStill();
    lutStillKey = key;
    const token = lutStillToken;
    setLutPreviewChip(msgLutChipUpdating);
    lutStillTimer = window.setTimeout(async () => {
      lutStillTimer = 0;
      // The endpoint reads persisted settings. Do not race an in-flight edit.
      await Promise.all([colorSaveChain, imageSaveChain, hslSaveChain, colorWheelsSaveChain]);
      if (token !== lutStillToken) return;
      const controller = new AbortController();
      lutStillAbort = controller;
      const url = `/api/studio/${studioId}/preview-frame?t_s=${encodeURIComponent(String(quant))}&detail=0`;
      fetch(url, { cache: "no-store", headers: { Accept: "image/jpeg" }, signal: controller.signal })
        .then(async (res) => {
          if (token !== lutStillToken) return null;
          if (res.status === 409) {
            lutStillKey = "";
            setLutPreviewChip(msgLutChipMissing);
            previewLutStill.hidden = true;
            return null;
          }
          if (!res.ok) {
            lutStillKey = "";
            setLutPreviewChip(msgLutChipFailed);
            previewLutStill.hidden = true;
            return null;
          }
          return res.blob();
        })
        .then(async (blob) => {
          if (!blob || token !== lutStillToken) return;
          const objectUrl = URL.createObjectURL(blob);
          const decoded = new Image();
          decoded.src = objectUrl;
          try {
            await decoded.decode();
          } catch (err) {
            URL.revokeObjectURL(objectUrl);
            throw err;
          }
          if (token !== lutStillToken) {
            URL.revokeObjectURL(objectUrl);
            return;
          }
          lutStillObjectUrl = objectUrl;
          previewLutStill.src = objectUrl;
          previewLutStill.hidden = false;
          const hit = resolveAt(state.projectTimeS);
          const composite = hit && (hit.overlapClip ||
            (loopOverlapS(clip) > 0 && sectionPoint(clip, hit.localS).blending));
          const stillLabel = composite ? msgLutChipComposite : msgLutChipStill;
          setLutPreviewChip(
            lutProxyPreparingFor(clip) ? `${stillLabel} · ${msgLutChipProxyPreparing}` : stillLabel
          );
          drawPrivacyMasks();
          schedulePreviewBlit();
        })
        .catch((err) => {
          if (err && err.name === "AbortError") return;
          if (token !== lutStillToken) return;
          lutStillKey = "";
          setLutPreviewChip(msgLutChipFailed);
          previewLutStill.hidden = true;
        });
    }, 120);
  }

  const lutProxyPrepare = new Map();

  function lutProxyPrepareKey(clip) {
    return JSON.stringify([
      clip.dataset.colorLook, clip.dataset.imageAdjust, clip.dataset.hsl,
      clip.dataset.colorWheels, clip.dataset.sourceIn, clip.dataset.sourceOut,
      clip.dataset.saturationRamp, clip.dataset.playbackSpeed,
    ]);
  }

  function lutProxyPreparingFor(clip) {
    if (!clip || !clip.dataset.studioId) return false;
    const stateForClip = lutProxyPrepare.get(String(clip.dataset.studioId));
    return !!(stateForClip && stateForClip.pending);
  }

  function isActiveClip(clip) {
    if (!clip || state.activeStudioId == null) return false;
    return String(state.activeStudioId) === String(clip.dataset.studioId);
  }

  function dropLutProxyPrepare(id) {
    const stale = lutProxyPrepare.get(id);
    if (stale && stale.timer) window.clearTimeout(stale.timer);
    lutProxyPrepare.delete(id);
  }

  function scheduleLutProxyPrepare(clip, delay = 300) {
    if (!clip || !clip.dataset.studioId) return;
    const id = String(clip.dataset.studioId);
    if (lutWebglCanHandle(clip)) {
      clip.dataset.lutProxyUrl = "";
      dropLutProxyPrepare(id);
      return;
    }
    if (!lutProxyEligible(clip)) {
      clip.dataset.lutProxyUrl = "";
      dropLutProxyPrepare(id);
      return;
    }
    const key = lutProxyPrepareKey(clip);
    let stateForClip = lutProxyPrepare.get(id);
    if (!stateForClip) {
      stateForClip = {
        token: 0,
        key,
        pending: false,
        failed: false,
        timer: 0,
        inFlight: false,
        queuedKey: "",
      };
      lutProxyPrepare.set(id, stateForClip);
    }
    // Keep the pending timer: a second selection/grade call with the same key
    // must not clear it and then return without scheduling a new one.
    if (stateForClip.key === key && stateForClip.pending) return;
    if (
      !stateForClip.inFlight &&
      !stateForClip.timer &&
      stateForClip.key === key &&
      clip.dataset.lutProxyUrl
    ) {
      return;
    }
    stateForClip.key = key;
    if (stateForClip.timer) {
      window.clearTimeout(stateForClip.timer);
      stateForClip.timer = 0;
    }
    // Any proxy for older settings must not stand in for the new grade.
    clip.dataset.lutProxyUrl = "";
    if (stateForClip.inFlight) {
      // One full render at a time. Keep only the newest pending settings so a
      // burst of slider releases never starts several FFmpeg jobs at once.
      stateForClip.queuedKey = key;
      stateForClip.pending = true;
      stateForClip.failed = false;
      stateForClip.token += 1;
      return;
    }
    startLutProxyBuild(clip, id, stateForClip, key, delay);
  }

  function startLutProxyBuild(clip, id, stateForClip, key, delay) {
    stateForClip.key = key;
    stateForClip.queuedKey = "";
    stateForClip.pending = true;
    stateForClip.failed = false;
    stateForClip.token += 1;
    const token = stateForClip.token;
    stateForClip.timer = window.setTimeout(async () => {
      stateForClip.timer = 0;
      stateForClip.inFlight = true;
      try {
        const res = await fetch(`/api/studio/${id}/playback-proxy`, {
          method: "POST",
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (lutProxyPrepare.get(id) !== stateForClip || stateForClip.token !== token) return;
        if (!res.ok) {
          stateForClip.pending = false;
          stateForClip.failed = true;
          if (isActiveClip(clip)) setLutPreviewChip(msgLutChipFailed);
          return;
        }
        const data = await res.json();
        if (lutProxyPrepare.get(id) !== stateForClip || stateForClip.token !== token) return;
        if (lutProxyPrepareKey(clip) !== key) {
          // The user kept editing while this render was running. The next
          // persisted save schedules one build for the final settings.
          stateForClip.pending = false;
          stateForClip.key = "";
          return;
        }
        const url = data && data.url ? String(data.url) : "";
        if (!url) {
          stateForClip.pending = false;
          stateForClip.failed = true;
          if (isActiveClip(clip)) setLutPreviewChip(msgLutChipFailed);
          return;
        }
        clip.dataset.lutProxyUrl = url;
        stateForClip.pending = false;
        stateForClip.failed = false;
        // Never reload the active picture for a merely selected, non-active
        // clip, and do not interrupt an in-progress playhead drag. The new
        // source is picked up by the next sync/seek.
        if (isActiveClip(clip) && !playheadDragging) {
          setLutPreviewChip("");
          syncPreviewMedia({ seek: true });
        }
      } catch (_) {
        if (lutProxyPrepare.get(id) === stateForClip && stateForClip.token === token) {
          stateForClip.pending = false;
          stateForClip.failed = true;
          if (isActiveClip(clip)) setLutPreviewChip(msgLutChipFailed);
        }
      } finally {
        stateForClip.inFlight = false;
        if (lutProxyPrepare.get(id) === stateForClip && stateForClip.queuedKey) {
          const latestKey = stateForClip.queuedKey;
          stateForClip.queuedKey = "";
          startLutProxyBuild(clip, id, stateForClip, latestKey, 0);
        }
      }
    }, delay);
  }

  function canvasFilterFrom(styleFilter) {
    const text = String(styleFilter || "none").replace(/url\([^)]*\)/g, " ").replace(/\s+/g, " ").trim();
    return text || "none";
  }

  const IMAGE_ADJUST_FIELDS = [
    ["exposure", "inspector-image-exposure", "inspector-image-exposure-value"],
    ["contrast", "inspector-image-contrast", "inspector-image-contrast-value"],
    ["saturation", "inspector-image-saturation", "inspector-image-saturation-value"],
    ["warmth", "inspector-image-warmth", "inspector-image-warmth-value"],
    ["highlights", "inspector-image-highlights", "inspector-image-highlights-value"],
    ["shadows", "inspector-image-shadows", "inspector-image-shadows-value"],
    ["blacks", "inspector-image-blacks", "inspector-image-blacks-value"],
  ];

  function selectedAdjustableClip() {
    if (!state.selected || state.selected.type !== "clip") return null;
    const clip = clips().find((item) => String(item.dataset.studioId) === String(state.selected.id));
    if (!clip || (clip.dataset.kind !== "video" && clip.dataset.kind !== "photo")) return null;
    return clip;
  }

  function fillImageAdjust(clip) {
    const adjust = readImageAdjust(clip);
    IMAGE_ADJUST_FIELDS.forEach(([key, inputId, valueId]) => {
      const input = document.getElementById(inputId);
      const valueEl = document.getElementById(valueId);
      const shown = adjust[key];
      if (input) input.value = String(shown);
      if (valueEl) valueEl.textContent = String(shown);
    });
    const lookSelect = document.getElementById("inspector-quick-look");
    if (lookSelect) lookSelect.value = clip.dataset.quickLook || "";
    const compare = document.getElementById("inspector-look-compare");
    if (compare) compare.checked = compareBeforeAfter;
    fillHsl(clip);
    fillColorWheels(clip);
    fillColorAnimationInspector(clip);
  }

  function hslRangeFromControls(clip) {
    const base = readHsl(clip);
    const value = { ...(base.ranges[selectedHslRange] || neutralHslRange()) };
    HSL_FIELDS.forEach(([key, inputId, valueId]) => {
      const input = document.getElementById(inputId);
      const valueEl = document.getElementById(valueId);
      const shown = clampHslSlider(input ? input.value : value[key]);
      value[key] = shown;
      if (valueEl) valueEl.textContent = String(shown);
    });
    base.ranges[selectedHslRange] = value;
    return base;
  }

  function fillHsl(clip) {
    const hsl = readHsl(clip);
    const value = hsl.ranges[selectedHslRange] || neutralHslRange();
    HSL_FIELDS.forEach(([key, inputId, valueId]) => {
      const input = document.getElementById(inputId);
      const valueEl = document.getElementById(valueId);
      if (input) input.value = String(value[key]);
      if (valueEl) valueEl.textContent = String(value[key]);
    });
    document.querySelectorAll("[data-hsl-range]").forEach((button) => {
      const active = button.dataset.hslRange === selectedHslRange;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  function fillColorWheels(clip) {
    const colorWheels = readColorWheels(clip);
    COLOR_WHEEL_IDS.forEach((wheelId) => {
      const point = colorWheels.wheels[wheelId] || neutralColorWheelPoint();
      const marker = document.getElementById(`color-wheel-point-${wheelId}`);
      if (marker) {
        marker.style.left = `${50 + point.x * 50}%`;
        marker.style.top = `${50 + point.y * 50}%`;
      }
      const status = document.getElementById(`color-wheel-status-${wheelId}`);
      if (status) status.textContent = colorWheelStatusText(point);
      const wheel = document.getElementById(`color-wheel-${wheelId}`);
      if (wheel) {
        wheel.setAttribute("aria-valuenow", String(Math.min(1, Math.hypot(point.x, point.y))));
        wheel.setAttribute("aria-valuetext", colorWheelStatusText(point));
      }
    });
  }

  function updateColorWheelFromPointer(clip, wheelId, element, clientX, clientY) {
    if (!clip || !element) return;
    const rect = element.getBoundingClientRect();
    const point = colorWheelPointFromRect(clientX, clientY, rect);
    const colorWheels = readColorWheels(clip);
    colorWheels.wheels[wheelId] = point;
    writeColorWheels(clip, colorWheels);
    fillColorWheels(clip);
    setSaveState(false);
  }

  async function applyQuickLook(clip, lookId) {
    const studioId = clip.dataset.studioId;
    const res = await fetch(`/api/studio/${studioId}/look`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ id: lookId || "" }),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgLookFailed);
    }
    if (body.image) writeImageAdjust(clip, body.image, true);
    clip.dataset.quickLook = body.quick_look || "";
    fillImageAdjust(clip);
    applyPreviewGrades(resolveAt(state.projectTimeS));
    scheduleLutProxyPrepare(clip);
    setSaveState(true);
  }

  function clearQuickLookLabel(clip) {
    if (!clip) return;
    if (!clip.dataset.quickLook) return;
    clip.dataset.quickLook = "";
    const lookSelect = document.getElementById("inspector-quick-look");
    if (lookSelect) lookSelect.value = "";
    fetch(`/api/studio/${clip.dataset.studioId}/look`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ id: "" }),
    }).catch(() => {});
  }

  function colorProfileDisplayLabel(token) {
    const raw = String(token || "").trim();
    if (!raw) return "";
    const key = raw.toLowerCase().replace(/-/g, "_");
    if (key === "dlog_m") return root.dataset.colorProfileDlogM || "D-Log M";
    return raw;
  }

  function neutralColorLook() {
    return {
      input_profile: "rec709",
      conversion_lut: "",
      creative_lut: "",
      creative_strength: 100,
      conversion_confirmed: false,
    };
  }

  function readColorLook(clip) {
    const neutral = neutralColorLook();
    if (!clip) return neutral;
    try {
      const parsed = JSON.parse(clip.dataset.colorLook || "");
      if (!parsed || typeof parsed !== "object") return neutral;
      return {
        input_profile: String(parsed.input_profile || "rec709"),
        conversion_lut: String(parsed.conversion_lut || ""),
        creative_lut: String(parsed.creative_lut || ""),
        creative_strength: Math.max(
          0,
          Math.min(100, Math.round(Number.isFinite(Number(parsed.creative_strength)) &&
            parsed.creative_strength != null ? Number(parsed.creative_strength) : 100))
        ),
        conversion_confirmed: Boolean(parsed.conversion_confirmed),
      };
    } catch (_) {
      return neutral;
    }
  }

  function writeColorLook(clip, look) {
    if (!clip) return;
    clip.dataset.colorLook = JSON.stringify(look || neutralColorLook());
    clearLutPreviewStill();
    scheduleLutProxyPrepare(clip);
    if (colorLookNeedsStill(look, clip)) setLutPreviewChip(msgLutChipUpdating);
  }

  let colorAnimationModel = { maxKeys: 8, minKeyGapS: 0.1, presets: [] };
  try {
    colorAnimationModel = JSON.parse(root.dataset.colorAnimationModel || "{}") || colorAnimationModel;
  } catch (_) {
    /* keep defaults */
  }
  const msgColorAnimFailed = root.dataset.colorAnimFailed || "Could not save the color change.";

  function readColorAnimation(clip) {
    if (!clip) return null;
    try {
      const parsed = JSON.parse(clip.dataset.colorAnimation || "null");
      if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.keys)) return null;
      return parsed;
    } catch (_) {
      return null;
    }
  }

  function writeColorAnimation(clip, anim) {
    if (!clip) return;
    clip.dataset.colorAnimation = anim ? JSON.stringify(anim) : "null";
  }

  function colorAnimPresetLabel(id) {
    const list = (colorAnimationModel && colorAnimationModel.presets) || [];
    const hit = list.find((item) => item && item.id === id);
    if (!hit) return id;
    const lang = (document.documentElement.lang || "en").toLowerCase();
    return lang.startsWith("de") ? (hit.label_de || hit.label_en || id) : (hit.label_en || id);
  }

  function keyedColorAt(anim, localS, staticLutStrength) {
    if (!anim || !Array.isArray(anim.keys) || anim.keys.length < 2) return null;
    const start = Number(anim.bar && anim.bar.start_s);
    const end = Number(anim.bar && anim.bar.end_s);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end - start < 0.05) return null;
    const t = Number(localS) || 0;
    if (t < start - 0.001 || t > end + 0.001) return null;
    const staticStrength = Number.isFinite(staticLutStrength) ? staticLutStrength : 100;
    const keys = anim.keys
      .map((key) => ({
        t: Number(key.t),
        exposure: Number(key.exposure) || 0,
        contrast: Number(key.contrast) || 0,
        saturation: Number(key.saturation) || 0,
        warmth: Number(key.warmth) || 0,
        lut_strength:
          key.lut_strength == null || key.lut_strength === ""
            ? null
            : Math.max(0, Math.min(100, Math.round(Number(key.lut_strength)))),
      }))
      .filter((key) => Number.isFinite(key.t))
      .sort((a, b) => a.t - b.t);
    if (!keys.length) return null;
    const resolveStrength = (left, right, u) => {
      if (left == null && right == null) return null;
      const a = left == null ? staticStrength : left;
      const b = right == null ? staticStrength : right;
      return Math.round(a + (b - a) * u);
    };
    if (t <= keys[0].t) return keys[0];
    if (t >= keys[keys.length - 1].t) return keys[keys.length - 1];
    for (let i = 0; i < keys.length - 1; i += 1) {
      const left = keys[i];
      const right = keys[i + 1];
      if (t < left.t || t > right.t) continue;
      const span = right.t - left.t;
      const u = span > 1e-9 ? (t - left.t) / span : 1;
      const lerp = (a, b) => a + (b - a) * u;
      return {
        t,
        exposure: Math.round(lerp(left.exposure, right.exposure)),
        contrast: Math.round(lerp(left.contrast, right.contrast)),
        saturation: Math.round(lerp(left.saturation, right.saturation)),
        warmth: Math.round(lerp(left.warmth, right.warmth)),
        lut_strength: resolveStrength(left.lut_strength, right.lut_strength, u),
      };
    }
    return keys[keys.length - 1];
  }

  function readImageAdjustAt(clip, localS) {
    const base = readImageAdjust(clip);
    const keyed = keyedColorAt(readColorAnimation(clip), localS);
    if (!keyed) return base;
    return {
      ...base,
      exposure: keyed.exposure,
      contrast: keyed.contrast,
      saturation: keyed.saturation,
      warmth: keyed.warmth,
    };
  }

  async function saveColorAnimation(clip, payload) {
    const studioId = clip && clip.dataset.studioId;
    if (!studioId) return;
    const res = await fetch(`/api/studio/${studioId}/color-animation`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgColorAnimFailed);
    }
    writeColorAnimation(clip, body.color_animation || null);
    layoutEffectBars();
    applyPreviewGrades(resolveAt(state.projectTimeS));
    setSaveState(true);
    fillColorAnimationInspector(clip);
  }

  let selectedColorPointIndex = -1;

  function fillColorAnimationInspector(clip) {
    const section = document.getElementById("inspector-color-animation");
    if (!section) return;
    const video = clip && clip.dataset.kind === "video";
    section.hidden = !video;
    if (!video) return;
    const select = document.getElementById("color-anim-preset");
    if (select && !select.dataset.filled) {
      ((colorAnimationModel && colorAnimationModel.presets) || []).forEach((preset) => {
        const opt = document.createElement("option");
        opt.value = preset.id;
        opt.textContent = colorAnimPresetLabel(preset.id);
        select.appendChild(opt);
      });
      select.dataset.filled = "1";
    }
    const anim = readColorAnimation(clip);
    const removeBtn = document.getElementById("color-anim-remove");
    if (removeBtn) removeBtn.hidden = !anim;
    if (select) select.value = (anim && anim.preset_id) || "";
    const applyBtn = document.getElementById("color-anim-apply-preset");
    if (applyBtn) applyBtn.disabled = !select || !select.value;
    const count = document.getElementById("color-anim-points-count");
    const keys = anim && Array.isArray(anim.keys) ? anim.keys : [];
    if (count) count.textContent = keys.length ? `${keys.length}/8` : "";
    const mode = anim && anim.mode === "manual" ? "manual" : "preset";
    const modePreset = document.getElementById("color-anim-mode-presets");
    const modeManual = document.getElementById("color-anim-mode-manual");
    const presetsPanel = document.getElementById("color-anim-presets-panel");
    const manualPanel = document.getElementById("color-anim-manual-panel");
    if (modePreset) modePreset.classList.toggle("is-active", mode === "preset");
    if (modeManual) modeManual.classList.toggle("is-active", mode === "manual");
    if (presetsPanel) presetsPanel.hidden = mode !== "preset";
    if (manualPanel) manualPanel.hidden = mode !== "manual";
    const list = document.getElementById("color-anim-point-list");
    if (list) {
      list.replaceChildren();
      keys.forEach((key, index) => {
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "button ghost";
        if (index === selectedColorPointIndex) btn.classList.add("is-active");
        btn.textContent = `${Number(key.t).toFixed(1)}s · W ${key.warmth || 0}`;
        btn.addEventListener("click", () => {
          selectedColorPointIndex = index;
          fillColorAnimationInspector(clip);
        });
        li.appendChild(btn);
        list.appendChild(li);
      });
    }
    const editor = document.getElementById("color-anim-point-editor");
    const key = keys[selectedColorPointIndex];
    if (editor) editor.hidden = !key;
    if (key) {
      const setPair = (inputId, valueId, value) => {
        const input = document.getElementById(inputId);
        const valueEl = document.getElementById(valueId);
        if (input) input.value = String(value);
        if (valueEl) valueEl.textContent = String(value);
      };
      setPair("color-anim-point-time", null, Number(key.t));
      setPair("color-anim-exposure", "color-anim-exposure-value", key.exposure || 0);
      setPair("color-anim-contrast", "color-anim-contrast-value", key.contrast || 0);
      setPair("color-anim-saturation", "color-anim-saturation-value", key.saturation || 0);
      setPair("color-anim-warmth", "color-anim-warmth-value", key.warmth || 0);
      const look = readColorLook(clip);
      const hasLut = !!(look && look.creative_lut);
      const lutWrap = document.getElementById("color-anim-lut-strength-wrap");
      if (lutWrap) lutWrap.hidden = !hasLut;
      if (hasLut) {
        const strength =
          key.lut_strength == null
            ? Math.max(0, Math.min(100, Math.round(Number(look.creative_strength) || 100)))
            : Math.max(0, Math.min(100, Math.round(Number(key.lut_strength) || 0)));
        setPair("color-anim-lut-strength", "color-anim-lut-strength-value", strength);
      }
    }
  }

  async function persistSelectedColorPoint(clip) {
    const anim = readColorAnimation(clip);
    if (!anim || !Array.isArray(anim.keys) || selectedColorPointIndex < 0) return;
    const keys = anim.keys.map((key) => ({ ...key }));
    const current = keys[selectedColorPointIndex];
    if (!current) return;
    const timeEl = document.getElementById("color-anim-point-time");
    const readSlider = (id) => {
      const el = document.getElementById(id);
      return el ? Number(el.value) || 0 : 0;
    };
    current.t = timeEl ? Number(timeEl.value) || 0 : current.t;
    current.exposure = readSlider("color-anim-exposure");
    current.contrast = readSlider("color-anim-contrast");
    current.saturation = readSlider("color-anim-saturation");
    current.warmth = readSlider("color-anim-warmth");
    const look = readColorLook(clip);
    const lutWrap = document.getElementById("color-anim-lut-strength-wrap");
    if (look && look.creative_lut && lutWrap && !lutWrap.hidden) {
      current.lut_strength = Math.max(0, Math.min(100, readSlider("color-anim-lut-strength")));
    }
    keys.sort((a, b) => Number(a.t) - Number(b.t));
    selectedColorPointIndex = keys.findIndex((key) => key === current);
    await saveColorAnimation(clip, {
      mode: "manual",
      bar: anim.bar,
      keys,
    });
  }

  function initColorAnimationUi() {
    const select = document.getElementById("color-anim-preset");
    const applyBtn = document.getElementById("color-anim-apply-preset");
    const removeBtn = document.getElementById("color-anim-remove");
    const modePreset = document.getElementById("color-anim-mode-presets");
    const modeManual = document.getElementById("color-anim-mode-manual");
    const presetsPanel = document.getElementById("color-anim-presets-panel");
    const manualPanel = document.getElementById("color-anim-manual-panel");
    if (select) {
      select.addEventListener("change", () => {
        if (applyBtn) applyBtn.disabled = !select.value;
      });
    }
    if (applyBtn) {
      applyBtn.addEventListener("click", async () => {
        const clip = selectedAdjustableClip();
        if (!clip || clip.dataset.kind !== "video" || !select || !select.value) return;
        const dur = Math.max(0.05, sourceDurationS(clip));
        const hit = resolveAt(state.projectTimeS);
        const local = hit && hit.clip === clip ? hit.localS : 0;
        const start = Math.max(0, Math.min(dur - 0.05, local));
        try {
          await saveColorAnimation(clip, {
            preset_id: select.value,
            bar: { start_s: start, end_s: dur },
          });
        } catch (err) {
          showFlash(err.message || msgColorAnimFailed);
        }
      });
    }
    if (removeBtn) {
      removeBtn.addEventListener("click", async () => {
        const clip = selectedAdjustableClip();
        if (!clip) return;
        try {
          await saveColorAnimation(clip, { clear: true });
        } catch (err) {
          showFlash(err.message || msgColorAnimFailed);
        }
      });
    }
    function setMode(mode) {
      if (modePreset) modePreset.classList.toggle("is-active", mode === "preset");
      if (modeManual) modeManual.classList.toggle("is-active", mode === "manual");
      if (presetsPanel) presetsPanel.hidden = mode !== "preset";
      if (manualPanel) manualPanel.hidden = mode !== "manual";
    }
    if (modePreset) modePreset.addEventListener("click", () => setMode("preset"));
    if (modeManual) {
      modeManual.addEventListener("click", async () => {
        setMode("manual");
        const clip = selectedAdjustableClip();
        const anim = clip && readColorAnimation(clip);
        if (!clip || !anim || anim.mode === "manual") return;
        try {
          await saveColorAnimation(clip, {
            mode: "manual",
            bar: anim.bar,
            keys: anim.keys,
          });
        } catch (err) {
          showFlash(err.message || msgColorAnimFailed);
        }
      });
    }
    [
      "color-anim-exposure",
      "color-anim-contrast",
      "color-anim-saturation",
      "color-anim-warmth",
      "color-anim-lut-strength",
    ].forEach((id) => {
      const input = document.getElementById(id);
      if (!input) return;
      input.addEventListener("input", () => {
        const valueEl = document.getElementById(`${id}-value`);
        if (valueEl) valueEl.textContent = input.value;
      });
      input.addEventListener("change", async () => {
        const clip = selectedAdjustableClip();
        if (!clip) return;
        try {
          await persistSelectedColorPoint(clip);
        } catch (err) {
          showFlash(err.message || msgColorAnimFailed);
        }
      });
    });
    const timeInput = document.getElementById("color-anim-point-time");
    if (timeInput) {
      timeInput.addEventListener("change", async () => {
        const clip = selectedAdjustableClip();
        if (!clip) return;
        try {
          await persistSelectedColorPoint(clip);
        } catch (err) {
          showFlash(err.message || msgColorAnimFailed);
        }
      });
    }
    const deletePointBtn = document.getElementById("color-anim-delete-point");
    if (deletePointBtn) {
      deletePointBtn.addEventListener("click", async () => {
        const clip = selectedAdjustableClip();
        const anim = clip && readColorAnimation(clip);
        if (!clip || !anim || !Array.isArray(anim.keys) || selectedColorPointIndex < 0) return;
        if (anim.keys.length <= 2) {
          showFlash(root.dataset.colorAnimMinPoints || "Keep at least two points.");
          return;
        }
        const keys = anim.keys.filter((_, index) => index !== selectedColorPointIndex);
        selectedColorPointIndex = Math.min(selectedColorPointIndex, keys.length - 1);
        try {
          await saveColorAnimation(clip, { mode: "manual", bar: anim.bar, keys });
        } catch (err) {
          showFlash(err.message || msgColorAnimFailed);
        }
      });
    }
    const addPointBtn = document.getElementById("color-anim-add-point");
    if (addPointBtn) {
      addPointBtn.addEventListener("click", async () => {
        const clip = selectedAdjustableClip();
        if (!clip || clip.dataset.kind !== "video") return;
        const anim = readColorAnimation(clip);
        const dur = Math.max(0.05, sourceDurationS(clip));
        const hit = resolveAt(state.projectTimeS);
        const local = hit && hit.clip === clip ? Math.max(0, hit.localS) : 0;
        const barStart = anim && anim.bar ? Number(anim.bar.start_s) : local;
        const barEnd = anim && anim.bar ? Number(anim.bar.end_s) : dur;
        if (!(local >= barStart - 0.001 && local <= barEnd + 0.001)) {
          showFlash(root.dataset.colorAnimPlayhead || "Set the playhead inside the color bar.");
          return;
        }
        const keys = anim && Array.isArray(anim.keys) ? anim.keys.map((key) => ({ ...key })) : [
          { t: barStart, exposure: 0, contrast: 0, saturation: 0, warmth: 0 },
          { t: barEnd, exposure: 0, contrast: 0, saturation: 0, warmth: 0 },
        ];
        if (keys.length >= 8) {
          showFlash(root.dataset.colorAnimMax || "At most 8 points.");
          return;
        }
        if (keys.some((key) => Math.abs(Number(key.t) - local) < 0.1)) {
          return;
        }
        const look = readColorLook(clip);
        const staticStrength = look ? Math.max(0, Math.min(100, Math.round(Number(look.creative_strength) || 100))) : 100;
        const keyed = keyedColorAt(
          { bar: { start_s: barStart, end_s: barEnd }, keys },
          local,
          staticStrength
        ) || {
          exposure: 0, contrast: 0, saturation: 0, warmth: 0, lut_strength: null,
        };
        const point = {
          t: Math.round(local * 10) / 10,
          exposure: keyed.exposure,
          contrast: keyed.contrast,
          saturation: keyed.saturation,
          warmth: keyed.warmth,
        };
        if (keyed.lut_strength != null || (look && look.creative_lut)) {
          point.lut_strength =
            keyed.lut_strength != null ? keyed.lut_strength : staticStrength;
        }
        keys.push(point);
        keys.sort((a, b) => Number(a.t) - Number(b.t));
        try {
          await saveColorAnimation(clip, {
            mode: "manual",
            bar: { start_s: barStart, end_s: barEnd },
            keys,
          });
        } catch (err) {
          showFlash(err.message || msgColorAnimFailed);
        }
      });
    }
  }
  initColorAnimationUi();

  function lutDisplayName(assetName) {
    const name = String(assetName || "");
    if (!name) return root.dataset.noneLabel || "None";
    const hit = lutCatalog.find((item) => item && item.asset_name === name);
    if (hit && hit.display_name) return String(hit.display_name);
    return msgColorLutMissingOption;
  }

  function fillLutSelect(selectEl, selectedAsset, { includeNone, includePleaseChoose }) {
    if (!selectEl) return;
    const previous = selectedAsset || selectEl.value || "";
    selectEl.innerHTML = "";
    if (includePleaseChoose) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = root.dataset.pleaseChoose || "Please choose";
      selectEl.appendChild(opt);
    } else if (includeNone) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = root.dataset.noneLabel || "None";
      selectEl.appendChild(opt);
    }
    const seen = new Set();
    lutCatalog.forEach((item) => {
      if (!item || !item.asset_name) return;
      seen.add(item.asset_name);
      const opt = document.createElement("option");
      opt.value = item.asset_name;
      let label = String(item.display_name || item.asset_name);
      if (item.file_present === false) label = `${label} ${msgColorFileMissingSuffix}`;
      opt.textContent = label;
      selectEl.appendChild(opt);
    });
    if (previous && !seen.has(previous)) {
      const opt = document.createElement("option");
      opt.value = previous;
      opt.textContent = msgColorLutMissingOption;
      selectEl.appendChild(opt);
    }
    selectEl.value = previous;
  }

  function syncConversionApplyEnabled() {
    const apply = document.getElementById("inspector-color-dlog-apply");
    const select = document.getElementById("inspector-color-conversion-select");
    const confirm = document.getElementById("inspector-color-conversion-confirm");
    if (!apply) return;
    apply.disabled = !(select && select.value && confirm && confirm.checked);
  }

  function fillColorLook(clip) {
    const look = readColorLook(clip);
    const token = (clip && clip.dataset.colorProfile) || "";
    const profileValue = document.getElementById("inspector-color-profile-value");
    const suggest = document.getElementById("inspector-color-dlog-suggest");
    const conversionStatus = document.getElementById("inspector-color-conversion-status");
    const conversionClear = document.getElementById("inspector-color-conversion-clear");
    const conversionChange = document.getElementById("inspector-color-conversion-change");
    const conversionSelect = document.getElementById("inspector-color-conversion-select");
    const creativeSelect = document.getElementById("inspector-color-creative-select");
    const creativeMissing = document.getElementById("inspector-color-creative-missing");
    const strengthField = document.getElementById("inspector-color-strength-field");
    const strengthInput = document.getElementById("inspector-color-strength");
    const strengthValue = document.getElementById("inspector-color-strength-value");
    const hintKey = String(token || "").trim().toLowerCase().replace(/-/g, "_");
    const isDlogHint = hintKey === "dlog_m";
    const conversionOn = Boolean(look.conversion_lut && look.conversion_confirmed);
    if (profileValue) {
      if (token.trim()) {
        profileValue.hidden = false;
        profileValue.textContent = colorProfileDisplayLabel(token);
      } else {
        profileValue.hidden = true;
        profileValue.textContent = "";
      }
    }
    if (suggest) suggest.hidden = !(isDlogHint && !conversionOn);
    fillLutSelect(conversionSelect, conversionOn ? "" : look.conversion_lut, {
      includeNone: false,
      includePleaseChoose: true,
    });
    fillLutSelect(creativeSelect, look.creative_lut, {
      includeNone: true,
      includePleaseChoose: false,
    });
    if (conversionStatus) {
      conversionStatus.hidden = !conversionOn;
      conversionStatus.textContent = conversionOn
        ? `${root.dataset.colorProfileDlogM || "D-Log M"} → Rec.709 · ${lutDisplayName(look.conversion_lut)}`
        : "";
    }
    if (conversionClear) conversionClear.hidden = !conversionOn;
    if (conversionChange) conversionChange.hidden = !conversionOn;
    const creativeHit = lutCatalog.find((item) => item && item.asset_name === look.creative_lut);
    const creativeMissingFile = Boolean(
      look.creative_lut && (!creativeHit || creativeHit.file_present === false)
    );
    if (creativeMissing) {
      creativeMissing.hidden = !creativeMissingFile;
      creativeMissing.textContent = creativeMissingFile
        ? msgColorLutMissing
        : "";
    }
    if (strengthField) strengthField.hidden = !look.creative_lut;
    if (strengthInput) strengthInput.value = String(look.creative_strength);
    if (strengthValue) strengthValue.textContent = String(look.creative_strength);
    syncConversionApplyEnabled();
  }

  async function refreshLutCatalog() {
    try {
      const res = await fetch("/api/luts", { headers: { Accept: "application/json" } });
      const body = await readJson(res);
      if (res.ok && body && Array.isArray(body.luts)) {
        lutCatalog = body.luts;
      }
    } catch (_) {
      /* keep seed catalog */
    }
  }

  function neutralDetail() {
    return { sharpen: 0, denoise: 0 };
  }

  function clampDetailSlider(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(0, Math.min(100, Math.round(number)));
  }

  function readDetail(clip) {
    const neutral = neutralDetail();
    if (!clip) return neutral;
    try {
      const parsed = JSON.parse(clip.dataset.detail || "");
      if (!parsed || typeof parsed !== "object") return neutral;
      return {
        sharpen: clampDetailSlider(parsed.sharpen),
        denoise: clampDetailSlider(parsed.denoise),
      };
    } catch (_) {
      return neutral;
    }
  }

  function writeDetail(clip, detail) {
    if (!clip) return;
    clip.dataset.detail = JSON.stringify(detail || neutralDetail());
  }

  function fillDetail(clip) {
    const detail = readDetail(clip);
    const sharpen = document.getElementById("inspector-detail-sharpen");
    const denoise = document.getElementById("inspector-detail-denoise");
    const sharpenValue = document.getElementById("inspector-detail-sharpen-value");
    const denoiseValue = document.getElementById("inspector-detail-denoise-value");
    if (sharpen) sharpen.value = String(detail.sharpen);
    if (denoise) denoise.value = String(detail.denoise);
    if (sharpenValue) sharpenValue.textContent = String(detail.sharpen);
    if (denoiseValue) denoiseValue.textContent = String(detail.denoise);
  }

  let detailSaveChain = Promise.resolve();

  function queueDetailSave(clip) {
    const studioId = clip.dataset.studioId;
    detailSaveChain = detailSaveChain
      .then(() => saveDetail(studioId))
      .catch((err) => {
        showFlash((err && err.message) || msgDetailFailed);
      });
  }

  async function saveDetail(studioId) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip) return;
    const detail = readDetail(clip);
    const res = await fetch(`/api/studio/${studioId}/detail`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(detail),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgDetailFailed);
    }
    writeDetail(clip, body.detail || detail);
    if (
      state.selected &&
      state.selected.type === "clip" &&
      String(state.selected.id) === String(studioId)
    ) {
      fillDetail(clip);
    }
    setSaveState(true);
  }

  function fillImageInspectorSections(clip, isVideo) {
    // Accordion open/closed is owned by the HTML defaults and the user.
    // Do not write section.open or section.hidden here.
    fillColorLook(clip);
    fillDetail(clip);
    const bwRamp = document.getElementById("inspector-saturation-ramp");
    if (bwRamp) bwRamp.hidden = !isVideo;
  }

  let colorSaveChain = Promise.resolve();

  function queueColorLookSave(clip) {
    const studioId = clip.dataset.studioId;
    colorSaveChain = colorSaveChain
      .then(() => saveColorLook(studioId))
      .catch((err) => {
        showFlash((err && err.message) || msgColorFailed);
      });
  }

  async function saveColorLook(studioId) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip) return;
    const look = readColorLook(clip);
    const res = await fetch(`/api/studio/${studioId}/color`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(look),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      const detail = body && body.detail;
      if (detail && String(detail).toLowerCase().includes("missing")) {
        throw new Error(msgColorLutMissing);
      }
      throw new Error(detail || msgColorFailed);
    }
    // A response for an older slider value must not overwrite a newer edit.
    if (JSON.stringify(readColorLook(clip)) === JSON.stringify(look)) {
      writeColorLook(clip, body.color_look || look);
    }
    applyPreviewGrades(resolveAt(state.projectTimeS));
    if (
      state.selected &&
      state.selected.type === "clip" &&
      String(state.selected.id) === String(studioId)
    ) {
      fillColorLook(clip);
    }
    setSaveState(true);
  }

  async function importCubeLut(fileOrPath) {
    let body;
    if (typeof fileOrPath === "string") {
      const res = await fetch("/api/luts", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ path: fileOrPath }),
      });
      body = await readJson(res);
      if (!res.ok || !body || !body.ok || !body.asset_name) {
        throw new Error((body && body.detail) || msgColorLutFailed);
      }
    } else {
      const form = new FormData();
      form.append("file", fileOrPath, fileOrPath.name || "look.cube");
      const res = await fetch("/api/luts", {
        method: "POST",
        headers: { Accept: "application/json" },
        body: form,
      });
      body = await readJson(res);
      if (!res.ok || !body || !body.ok || !body.asset_name) {
        throw new Error((body && body.detail) || msgColorLutFailed);
      }
    }
    await refreshLutCatalog();
    if (body.already_present) {
      showFlash(msgColorLutAlready.replace("{name}", body.display_name || body.asset_name));
    } else if (body.restored) {
      showFlash(msgColorLutRestored.replace("{name}", body.display_name || body.asset_name));
    }
    return body.asset_name;
  }

  async function pickCubePath() {
    const res = await fetch("/api/desktop/pick-open-file", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        file_types: ["3D LUT (*.cube)", "All files (*.*)"],
      }),
    });
    const body = await readJson(res);
    if (res.status === 503 || (body && body.status === "unavailable")) {
      return null;
    }
    if (!res.ok || !body || body.status === "cancelled" || !body.path) {
      return null;
    }
    return body.path;
  }

  async function chooseCubeAsset() {
    const path = await pickCubePath();
    if (path) return importCubeLut(path);
    const input = document.getElementById("inspector-color-file-input");
    if (!input) throw new Error(msgColorLutFailed);
    return new Promise((resolve, reject) => {
      const onChange = async () => {
        input.removeEventListener("change", onChange);
        const file = input.files && input.files[0];
        input.value = "";
        if (!file) {
          reject(new Error("cancelled"));
          return;
        }
        try {
          resolve(await importCubeLut(file));
        } catch (err) {
          reject(err);
        }
      };
      input.addEventListener("change", onChange);
      input.click();
    });
  }

  function imageAdjustFromControls() {
    const adjust = neutralImageAdjust();
    IMAGE_ADJUST_FIELDS.forEach(([key, inputId, valueId]) => {
      const input = document.getElementById(inputId);
      const valueEl = document.getElementById(valueId);
      const shown = clampImageSlider(input ? input.value : 0);
      adjust[key] = shown;
      if (valueEl) valueEl.textContent = String(shown);
    });
    return adjust;
  }

  let imageSaveChain = Promise.resolve();

  function queueImageAdjustSave(clip) {
    const studioId = clip.dataset.studioId;
    imageSaveChain = imageSaveChain
      .then(() => saveImageAdjust(studioId))
      .catch((err) => {
        showFlash((err && err.message) || msgImageFailed);
      });
  }

  async function saveImageAdjust(studioId) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip) return;
    const adjust = readImageAdjust(clip);
    const res = await fetch(`/api/studio/${studioId}/image`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(adjust),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgImageFailed);
    }
    if (JSON.stringify(readImageAdjust(clip)) === JSON.stringify(adjust)) {
      writeImageAdjust(clip, body.image || adjust, true);
    }
    if (
      state.selected &&
      state.selected.type === "clip" &&
      String(state.selected.id) === String(studioId)
    ) {
      fillImageAdjust(clip);
    }
    applyPreviewGrades(resolveAt(state.projectTimeS));
    applyFramePreview(resolveAt(state.projectTimeS));
    setSaveState(true);
  }

  let hslSaveChain = Promise.resolve();
  let hslSaveTimer = 0;
  const hslPendingStudioIds = new Set();

  function queueHslSave(clip) {
    const studioId = clip && clip.dataset.studioId;
    if (!studioId) return;
    hslPendingStudioIds.add(String(studioId));
    if (hslSaveTimer) window.clearTimeout(hslSaveTimer);
    // Rapid slider releases coalesce into the latest per-clip settings.
    hslSaveTimer = window.setTimeout(() => {
      hslSaveTimer = 0;
      const pendingIds = [...hslPendingStudioIds];
      hslPendingStudioIds.clear();
      pendingIds.forEach((pendingId) => {
        hslSaveChain = hslSaveChain
          .then(() => saveHsl(pendingId))
          .catch((err) => {
            showFlash((err && err.message) || msgHslFailed);
          });
      });
    }, 150);
  }

  async function saveHsl(studioId) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip) return;
    const hsl = readHsl(clip);
    const res = await fetch(`/api/studio/${studioId}/hsl`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ ranges: hsl.ranges }),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgHslFailed);
    }
    if (JSON.stringify(readHsl(clip)) === JSON.stringify(hsl)) {
      writeHsl(clip, body.hsl || hsl, true);
    }
    if (
      state.selected &&
      state.selected.type === "clip" &&
      String(state.selected.id) === String(studioId)
    ) {
      fillHsl(clip);
    }
    applyPreviewGrades(resolveAt(state.projectTimeS));
    setSaveState(true);
  }

  let colorWheelsSaveChain = Promise.resolve();
  let colorWheelsSaveTimer = 0;
  const colorWheelsPendingStudioIds = new Set();

  function queueColorWheelsSave(clip) {
    const studioId = clip && clip.dataset.studioId;
    if (!studioId) return;
    colorWheelsPendingStudioIds.add(String(studioId));
    if (colorWheelsSaveTimer) window.clearTimeout(colorWheelsSaveTimer);
    colorWheelsSaveTimer = window.setTimeout(() => {
      colorWheelsSaveTimer = 0;
      const pendingIds = [...colorWheelsPendingStudioIds];
      colorWheelsPendingStudioIds.clear();
      pendingIds.forEach((pendingId) => {
        colorWheelsSaveChain = colorWheelsSaveChain
          .then(() => saveColorWheels(pendingId))
          .catch((err) => {
            showFlash((err && err.message) || msgColorWheelsFailed);
          });
      });
    }, 150);
  }

  async function saveColorWheels(studioId) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip) return;
    const colorWheels = readColorWheels(clip);
    const res = await fetch(`/api/studio/${studioId}/color-wheels`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ wheels: colorWheels.wheels }),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgColorWheelsFailed);
    }
    if (JSON.stringify(readColorWheels(clip)) === JSON.stringify(colorWheels)) {
      writeColorWheels(clip, body.color_wheels || colorWheels, true);
    }
    if (
      state.selected &&
      state.selected.type === "clip" &&
      String(state.selected.id) === String(studioId)
    ) {
      fillColorWheels(clip);
    }
    applyPreviewGrades(resolveAt(state.projectTimeS));
    setSaveState(true);
  }

  let selectedMaskId = null;
  let maskDragging = false;
  const maskScratch = document.createElement("canvas");

  function readMaskModel() {
    const fallback = {
      maxMasks: 8,
      minBox: 0.04,
      strengthMin: 1,
      strengthMax: 100,
      defaultStrength: 50,
      blurFraction: 0.05,
      pixelFraction: 0.06,
    };
    try {
      const parsed = JSON.parse(root.dataset.maskModel || "");
      return Object.assign(fallback, parsed);
    } catch (_) {
      return fallback;
    }
  }

  function clampMaskStrength(value) {
    const number = Number(value);
    const min = Number(maskModel.strengthMin) || 1;
    const max = Number(maskModel.strengthMax) || 100;
    if (!Number.isFinite(number)) return Number(maskModel.defaultStrength) || 50;
    return Math.max(min, Math.min(max, Math.round(number)));
  }

  function clampMaskBox(mask) {
    const minBox = Number(maskModel.minBox) || 0.04;
    const width = Math.min(1, Math.max(minBox, Number(mask.w) || minBox));
    const height = Math.min(1, Math.max(minBox, Number(mask.h) || minBox));
    const box = {
      id: String(mask.id || ""),
      effect: mask.effect === "pixelate" ? "pixelate" : "blur",
      strength: clampMaskStrength(mask.strength),
      x: Math.min(1 - width, Math.max(0, Number(mask.x) || 0)),
      y: Math.min(1 - height, Math.max(0, Number(mask.y) || 0)),
      w: width,
      h: height,
    };
    const start = Number(mask.start_s);
    const end = Number(mask.end_s);
    if (Number.isFinite(start) && Number.isFinite(end) && end - start >= 0.05) {
      box.start_s = start;
      box.end_s = end;
    }
    return box;
  }

  function masksAt(clip, localS) {
    const offset = storyToSource(clip, Number(localS) || 0);
    return readMasks(clip).filter((mask) => {
      if (mask.start_s == null || mask.end_s == null) return true;
      return offset >= Number(mask.start_s) - 0.001 && offset <= Number(mask.end_s) + 0.001;
    });
  }

  function readMasks(clip) {
    if (!clip) return [];
    try {
      const parsed = JSON.parse(clip.dataset.masks || "[]");
      if (!Array.isArray(parsed)) return [];
      return parsed.map((item) => clampMaskBox(item));
    } catch (_) {
      return [];
    }
  }

  function writeMasks(clip, masks) {
    clip.dataset.masks = JSON.stringify(masks.map((item) => clampMaskBox(item)));
    if (!maskDragging) layoutEffectBars();
  }

  function maskEffectLabel(effect) {
    return effect === "pixelate" ? labelMaskPixelate : labelMaskBlur;
  }

  function newMaskId() {
    const bytes = new Uint8Array(5);
    if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(bytes);
    else bytes.forEach((_, index) => { bytes[index] = Math.floor(Math.random() * 256); });
    const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
    return `m${hex}`;
  }

  function mediaContentBox(media) {
    if (!media || media.hidden) return null;
    const frame = media.parentElement;
    if (!frame) return null;
    const frameRect = frame.getBoundingClientRect();
    const mediaRect = media.getBoundingClientRect();
    const srcW = media.videoWidth || media.naturalWidth || 0;
    const srcH = media.videoHeight || media.naturalHeight || 0;
    if (!srcW || !srcH || mediaRect.width < 2 || mediaRect.height < 2) return null;
    const scale = Math.min(mediaRect.width / srcW, mediaRect.height / srcH);
    const width = srcW * scale;
    const height = srcH * scale;
    return {
      left: mediaRect.left - frameRect.left + (mediaRect.width - width) / 2,
      top: mediaRect.top - frameRect.top + (mediaRect.height - height) / 2,
      width,
      height,
    };
  }

  function effectAmount(strength, contentW, contentH, fraction) {
    const span = Math.min(contentW, contentH);
    const amount = (clampMaskStrength(strength) / 100) * span * Number(fraction || 0);
    return Math.max(1, amount);
  }

  function visibleContentBox(media) {
    if (!media || media.hidden) return null;
    const srcW = media.videoWidth || media.naturalWidth || 0;
    const srcH = media.videoHeight || media.naturalHeight || 0;
    const frameW = previewFrame ? previewFrame.clientWidth : 0;
    const frameH = previewFrame ? previewFrame.clientHeight : 0;
    if (!srcW || !srcH || frameW < 2 || frameH < 2) return null;
    const fit = contentRect(frameW, frameH, srcW, srcH);
    if (!fit || fit.w < 2 || fit.h < 2) return null;
    return { left: fit.x, top: fit.y, width: fit.w, height: fit.h };
  }

  function boxMatchingCanvas(canvas, media) {
    const fitted = media ? visibleContentBox(media) : null;
    if (!canvas || canvas.hidden || !previewFrame || !fitted) return fitted;
    const painted = canvas.getBoundingClientRect();
    const frame = previewFrame.getBoundingClientRect();
    if (painted.width < 2 || painted.height < 2) return fitted;
    return {
      left: painted.left - frame.left - previewFrame.clientLeft,
      top: painted.top - frame.top - previewFrame.clientTop,
      width: painted.width,
      height: painted.height,
    };
  }

  function sourceWindowForMask(media, srcW, srcH) {
    const laidOut = media.getBoundingClientRect();
    const frameW = previewFrame && previewFrame.clientWidth > 2 ? previewFrame.clientWidth : laidOut.width;
    const frameH = previewFrame && previewFrame.clientHeight > 2 ? previewFrame.clientHeight : laidOut.height;
    const clip = clipForPreviewMedia(media);
    const frame = clip ? readFrame(clip) : { zoom_start: 1, zoom_end: 1, x_start: 0.5, y_start: 0.5, x_end: 0.5, y_end: 0.5 };
    const hit = resolveAt(state.projectTimeS);
    const localS =
      clip && hit && hit.overlapClip === clip
        ? hit.overlapLocalS
        : hit && hit.clip === clip
          ? hit.localS
          : 0;
    // Match applyFrameToElement: outside a video zoom bar, framing is off.
    if (clip && clip.dataset.kind === "video") {
      const bar = zoomBarOf(clip);
      if (bar) {
        const offset = storyToSource(clip, localS);
        if (offset < bar.start - 0.001 || offset > bar.end + 0.001) {
          return { x: 0, y: 0, w: srcW, h: srcH };
        }
      }
    }
    const sample = sampleFrame(frame, clip ? framePreviewProgress(clip, localS) : 0);
    if (sample.zoom <= 1.001) {
      return { x: 0, y: 0, w: srcW, h: srcH };
    }
    const win = windowFor(sample.zoom, sample.x, sample.y, frameW, frameH, srcW, srcH);
    const scale = srcW / win.content.w;
    return {
      x: (win.x - win.content.x) * scale,
      y: (win.y - win.content.y) * scale,
      w: win.w * scale,
      h: win.h * scale,
    };
  }

  function clipForPreviewMedia(media) {
    if (media === previewVideo || media === previewImage) {
      const hit = resolveAt(state.projectTimeS);
      return hit && hit.clip ? hit.clip : null;
    }
    if (media === previewVideoB || media === previewImageB) {
      const hit = resolveAt(state.projectTimeS);
      return hit && hit.overlapClip ? hit.overlapClip : null;
    }
    return null;
  }

  function paintPrivacyMask(ctx, media, mask, box, srcW, srcH) {
    const rendered = !reuseDraft && !state.playing && (media === previewVideo || media === previewImage) &&
      previewLayerReady(previewLutStill) ? previewLutStill : null;
    const webgl = lutWebglCanvasFor(media);
    const picture = webgl || rendered || media;
    if (webgl) {
      srcW = webgl.width;
      srcH = webgl.height;
    } else if (rendered) {
      srcW = rendered.naturalWidth;
      srcH = rendered.naturalHeight;
    }
    const dx = mask.x * box.width;
    const dy = mask.y * box.height;
    const dw = Math.max(1, mask.w * box.width);
    const dh = Math.max(1, mask.h * box.height);
    const view = sourceWindowForMask(media, srcW, srcH);
    const sx = view.x + mask.x * view.w;
    const sy = view.y + mask.y * view.h;
    const sw = Math.max(1, mask.w * view.w);
    const sh = Math.max(1, mask.h * view.h);
    ctx.save();
    ctx.beginPath();
    ctx.rect(dx, dy, dw, dh);
    ctx.clip();
    try {
      if (mask.effect === "pixelate") {
        const block = Math.max(
          2,
          effectAmount(mask.strength, box.width, box.height, maskModel.pixelFraction)
        );
        const cols = Math.max(1, Math.round(dw / block));
        const rows = Math.max(1, Math.round(dh / block));
        maskScratch.width = cols;
        maskScratch.height = rows;
        const scratch = maskScratch.getContext("2d");
        if (!scratch) {
          ctx.restore();
          return;
        }
        scratch.imageSmoothingEnabled = false;
        scratch.clearRect(0, 0, cols, rows);
        scratch.drawImage(picture, sx, sy, sw, sh, 0, 0, cols, rows);
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(maskScratch, 0, 0, cols, rows, dx, dy, dw, dh);
      } else {
        const radius = effectAmount(mask.strength, box.width, box.height, maskModel.blurFraction);
        const padX = (radius / box.width) * view.w;
        const padY = (radius / box.height) * view.h;
        ctx.filter = `blur(${radius}px)`;
        ctx.drawImage(
          picture,
          sx - padX,
          sy - padY,
          sw + padX * 2,
          sh + padY * 2,
          dx - radius,
          dy - radius,
          dw + radius * 2,
          dh + radius * 2
        );
        ctx.filter = "none";
      }
    } catch (_) {
      /* Media may not be ready to draw yet. */
    }
    ctx.restore();
  }

  function drawMaskCanvas(canvas, media, masks, opacity) {
    if (!canvas) return;
    if (!media || media.hidden || !masks.length) {
      canvas.hidden = true;
      return;
    }
    const box = visibleContentBox(media);
    const srcW = media.videoWidth || media.naturalWidth || 0;
    const srcH = media.videoHeight || media.naturalHeight || 0;
    if (!box || !srcW || !srcH) {
      canvas.hidden = true;
      return;
    }
    const dpr = window.devicePixelRatio || 1;
    const pixelW = Math.max(1, Math.round(box.width * dpr));
    const pixelH = Math.max(1, Math.round(box.height * dpr));
    if (canvas.width !== pixelW || canvas.height !== pixelH) {
      canvas.width = pixelW;
      canvas.height = pixelH;
    }
    canvas.style.left = `${box.left}px`;
    canvas.style.top = `${box.top}px`;
    canvas.style.width = `${box.width}px`;
    canvas.style.height = `${box.height}px`;
    canvas.style.opacity = opacity == null || opacity === "" ? "1" : String(opacity);
    canvas.hidden = false;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, box.width, box.height);
    masks.forEach((mask) => paintPrivacyMask(ctx, media, mask, box, srcW, srcH));
  }

  function visiblePrimaryMedia() {
    if (previewVideo && !previewVideo.hidden) return previewVideo;
    if (previewImage && !previewImage.hidden) return previewImage;
    return null;
  }

  function visibleSecondaryMedia() {
    if (previewVideoB && !previewVideoB.hidden) return previewVideoB;
    if (previewImageB && !previewImageB.hidden) return previewImageB;
    return null;
  }

  function hidePrivacyMasks() {
    if (previewMasks) previewMasks.hidden = true;
    if (previewMasksB) previewMasksB.hidden = true;
    if (previewMaskHandles) previewMaskHandles.hidden = true;
  }

  function renderMaskHandles(clip, box) {
    const layer = previewMaskHandles;
    if (!layer) return;
    if (maskDragging) return;
    const hit = resolveAt(state.projectTimeS);
    const onPlayhead =
      clip &&
      hit &&
      hit.clip &&
      String(hit.clip.dataset.studioId) === String(clip.dataset.studioId);
    const masks = onPlayhead ? masksAt(clip, hit.localS) : [];
    if (!onPlayhead || !box || !masks.length) {
      if (maskDragging) return;
      layer.hidden = true;
      layer.replaceChildren();
      return;
    }
    layer.hidden = false;
    layer.style.left = `${box.left}px`;
    layer.style.top = `${box.top}px`;
    layer.style.width = `${box.width}px`;
    layer.style.height = `${box.height}px`;
    if (maskDragging) return;
    layer.replaceChildren();
    masks.forEach((mask) => {
      const boxEl = document.createElement("div");
      boxEl.className = "studio-mask-box";
      if (mask.id === selectedMaskId) boxEl.classList.add("is-selected");
      boxEl.dataset.maskId = mask.id;
      boxEl.dataset.studioId = clip.dataset.studioId || "";
      boxEl.style.left = `${mask.x * 100}%`;
      boxEl.style.top = `${mask.y * 100}%`;
      boxEl.style.width = `${mask.w * 100}%`;
      boxEl.style.height = `${mask.h * 100}%`;
      boxEl.setAttribute("role", "button");
      boxEl.tabIndex = 0;
      boxEl.setAttribute("aria-label", maskEffectLabel(mask.effect));
      const hitPad = document.createElement("span");
      hitPad.className = "studio-mask-hit";
      hitPad.setAttribute("aria-hidden", "true");
      boxEl.appendChild(hitPad);
      const handle = document.createElement("span");
      handle.className = "studio-mask-resize";
      handle.dataset.resize = "1";
      boxEl.appendChild(handle);
      if (mask.id === selectedMaskId) {
        const close = document.createElement("button");
        close.type = "button";
        close.className = "studio-mask-remove";
        close.dataset.maskRemove = "1";
        close.textContent = "×";
        close.setAttribute("aria-label", msgMaskRemove);
        close.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          event.stopPropagation();
        });
        close.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          selectedMaskId = mask.id;
          removeSelectedMask();
        });
        boxEl.appendChild(close);
      }
      boxEl.addEventListener("pointerdown", (event) => {
        if (maskDragging) return;
        beginMaskDrag(event, boxEl);
      });
      layer.appendChild(boxEl);
    });
  }

  function maskBoxAtPoint(clientX, clientY) {
    const layer = previewMaskHandles;
    if (!layer || layer.hidden) return null;
    const nodes = layer.querySelectorAll(".studio-mask-box, .studio-mask-resize");
    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i];
      const rect = node.getBoundingClientRect();
      if (
        clientX >= rect.left &&
        clientX <= rect.right &&
        clientY >= rect.top &&
        clientY <= rect.bottom
      ) {
        return node.closest(".studio-mask-box");
      }
    }
    return null;
  }

  function maskCanvasHit(clientX, clientY) {
    const hit = resolveAt(state.projectTimeS);
    if (!hit || !hit.clip) return null;
    const layers = [{ canvas: previewMasks, clip: hit.clip, localS: hit.localS }];
    if (hit.overlapClip && hit.crossfadeProgress != null) {
      layers.unshift({
        canvas: previewMasksB,
        clip: hit.overlapClip,
        localS: hit.overlapLocalS,
      });
    }
    let found = null;
    for (let layerIndex = 0; layerIndex < layers.length; layerIndex += 1) {
      const layer = layers[layerIndex];
      const canvas = layer.canvas;
      if (!canvas || canvas.hidden || !layer.clip) continue;
      const rect = canvas.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) continue;
      const masks = masksAt(layer.clip, layer.localS);
      for (let i = 0; i < masks.length; i += 1) {
        const mask = masks[i];
        const left = rect.left + mask.x * rect.width;
        const top = rect.top + mask.y * rect.height;
        const right = left + Math.max(1, mask.w * rect.width);
        const bottom = top + Math.max(1, mask.h * rect.height);
        const onResize =
          clientX >= right - 18 &&
          clientX <= right + 12 &&
          clientY >= bottom - 18 &&
          clientY <= bottom + 12;
        const inside =
          clientX >= left && clientX <= right && clientY >= top && clientY <= bottom;
        if (onResize || inside) {
          found = { mask, clip: layer.clip, resizing: onResize, rect };
        }
      }
    }
    return found;
  }

  function maskBoxForId(maskId) {
    const layer = previewMaskHandles;
    if (!layer) return null;
    const nodes = layer.querySelectorAll(".studio-mask-box");
    for (let i = 0; i < nodes.length; i += 1) {
      if (nodes[i].dataset.maskId === maskId) return nodes[i];
    }
    return null;
  }

  function maskDragBounds(layer, box, startMask, geomRect) {
    if (geomRect && geomRect.width >= 2 && geomRect.height >= 2) return geomRect;
    if (layer) {
      const layerRect = layer.getBoundingClientRect();
      if (layerRect.width >= 2 && layerRect.height >= 2) return layerRect;
    }
    if (!box) {
      return {
        width: Math.max(2, geomRect ? geomRect.width : 2),
        height: Math.max(2, geomRect ? geomRect.height : 2),
      };
    }
    const boxRect = box.getBoundingClientRect();
    const w = Math.max(0.04, Number(startMask.w) || 0.04);
    const h = Math.max(0.04, Number(startMask.h) || 0.04);
    return {
      width: Math.max(2, boxRect.width / w),
      height: Math.max(2, boxRect.height / h),
    };
  }

  function beginMaskDrag(event, box, geom) {
    if (maskDragging) return false;
    if (event.button != null && event.button !== 0) return false;
    // Only the on-preview × control — not #studio-root[data-mask-remove-label].
    if (event.target && event.target.closest && event.target.closest(".studio-mask-remove")) {
      return false;
    }
    const layer = previewMaskHandles;
    if (!layer) return false;
    const maskId = (box && box.dataset.maskId) || (geom && geom.mask && geom.mask.id) || "";
    const studioId =
      (box && box.dataset.studioId) ||
      (geom && geom.clip && geom.clip.dataset.studioId) ||
      "";
    const clip =
      (geom && geom.clip) ||
      clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip || !maskId) return false;
    const startMask = readMasks(clip).find((item) => item.id === maskId);
    if (!startMask) return false;
    let resizing = Boolean(geom && geom.resizing);
    if (
      event.target &&
      event.target.closest &&
      event.target.closest(".studio-mask-box [data-resize]")
    ) {
      resizing = true;
    }
    event.preventDefault();
    event.stopPropagation();
    selectedMaskId = maskId;
    // Flag before any redraw so renderMaskHandles does not rebuild under the pointer.
    // Do not call selectClip / fillMaskInspector here — WebView2 often cancels the
    // pointer when the inspector DOM is replaced mid-gesture (Issue #179).
    maskDragging = true;
    historyGesture = "g" + String(event.pointerId || Date.now());
    const needsSelect =
      !state.selected ||
      state.selected.type !== "clip" ||
      String(state.selected.id) !== String(clip.dataset.studioId);
    if (!box || !box.isConnected) box = maskBoxForId(maskId);
    if (box) box.classList.add("is-dragging", "is-selected");
    const pointerId = event.pointerId;
    const captureEl = previewFrame || box;
    try {
      if (captureEl && pointerId != null) captureEl.setPointerCapture(pointerId);
    } catch (_) {
      /* Window listeners still follow the pointer. */
    }
    const bounds = maskDragBounds(layer, box, startMask, geom && geom.rect);
    const originX = event.clientX;
    const originY = event.clientY;
    let ended = false;
    let moved = false;
    let earlyCancelTimer = 0;
    const finish = (save) => {
      if (ended) return;
      ended = true;
      if (earlyCancelTimer) {
        window.clearTimeout(earlyCancelTimer);
        earlyCancelTimer = 0;
      }
      maskDragging = false;
      if (box) box.classList.remove("is-dragging");
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      window.removeEventListener("pointercancel", up, true);
      if (captureEl) {
        captureEl.removeEventListener("lostpointercapture", onLostCapture);
        try {
          if (pointerId != null) captureEl.releasePointerCapture(pointerId);
        } catch (_) {
          /* already released */
        }
      }
      if (needsSelect) {
        try {
          selectClip(clip.dataset.studioId, { movePlayhead: false });
        } catch (_) {
          /* selection can wait until after the gesture */
        }
      }
      layoutEffectBars();
      if (save) queueMaskSave(clip);
      drawPrivacyMasks();
      historyGesture = "";
      try {
        fillMaskInspector(clip);
      } catch (_) {
        /* ignore */
      }
    };
    const move = (ev) => {
      if (ended) return;
      if (ev.pointerId != null && pointerId != null && ev.pointerId !== pointerId) return;
      moved = true;
      if (earlyCancelTimer) {
        window.clearTimeout(earlyCancelTimer);
        earlyCancelTimer = 0;
      }
      ev.preventDefault();
      ev.stopPropagation();
      const dx = (ev.clientX - originX) / bounds.width;
      const dy = (ev.clientY - originY) / bounds.height;
      const next = readMasks(clip).map((item) => {
        if (item.id !== maskId) return item;
        if (resizing) {
          return clampMaskBox({ ...startMask, w: startMask.w + dx, h: startMask.h + dy });
        }
        return clampMaskBox({ ...startMask, x: startMask.x + dx, y: startMask.y + dy });
      });
      writeMasks(clip, next);
      const current = next.find((item) => item.id === maskId);
      if (current && box && box.isConnected) {
        box.style.left = `${current.x * 100}%`;
        box.style.top = `${current.y * 100}%`;
        box.style.width = `${current.w * 100}%`;
        box.style.height = `${current.h * 100}%`;
      }
      drawPrivacyMasks();
    };
    const up = (ev) => {
      if (ended) return;
      if (ev && ev.pointerId != null && pointerId != null && ev.pointerId !== pointerId) return;
      // WebView2 may fire a spurious pointercancel immediately after pointerdown.
      // Abort cleanly after a short delay if no move/up follows, so maskDragging
      // never stays stuck true.
      if (ev && ev.type === "pointercancel" && !moved) {
        if (!earlyCancelTimer) {
          earlyCancelTimer = window.setTimeout(() => {
            earlyCancelTimer = 0;
            finish(false);
          }, 80);
        }
        return;
      }
      finish(true);
    };
    const onLostCapture = (ev) => {
      if (ended) return;
      if (ev && ev.pointerId != null && pointerId != null && ev.pointerId !== pointerId) return;
      finish(moved);
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", up, true);
    if (captureEl) captureEl.addEventListener("lostpointercapture", onLostCapture);
    return true;
  }

  function onDocumentMaskPointerDown(event) {
    if (event.button != null && event.button !== 0) return;
    if (event.target && event.target.closest && event.target.closest(".studio-mask-remove")) return;
    const geom = maskCanvasHit(event.clientX, event.clientY);
    const direct = event.target && event.target.closest && event.target.closest(".studio-mask-box");
    const box = direct || maskBoxAtPoint(event.clientX, event.clientY);
    if (!box && !geom) return;
    if (box && previewFrame && !previewFrame.contains(box) && !geom) return;
    if (beginMaskDrag(event, box, geom)) event.stopPropagation();
  }

  document.addEventListener("pointerdown", onDocumentMaskPointerDown, true);

  function drawPrivacyMasks() {
    const hit = resolveAt(state.projectTimeS);
    if (!hit || !hit.clip) {
      hidePrivacyMasks();
      return;
    }
    const primary = visiblePrimaryMedia();
    const primaryOpacity = primary ? primary.style.opacity : "1";
    drawMaskCanvas(previewMasks, primary, masksAt(hit.clip, hit.localS), primaryOpacity);
    const overlap = hit.overlapClip && hit.crossfadeProgress != null;
    const secondary = overlap ? visibleSecondaryMedia() : null;
    drawMaskCanvas(
      previewMasksB,
      secondary,
      overlap ? masksAt(hit.overlapClip, hit.overlapLocalS) : [],
      secondary ? secondary.style.opacity : "1"
    );
    renderMaskHandles(hit.clip, primary ? boxMatchingCanvas(previewMasks, primary) : null);
  }

  function fillMaskInspector(clip) {
    const wrap = document.getElementById("inspector-masks");
    const list = document.getElementById("mask-list");
    const editor = document.getElementById("mask-editor");
    const effect = document.getElementById("mask-effect");
    const strength = document.getElementById("mask-strength");
    const strengthValue = document.getElementById("mask-strength-value");
    if (!wrap || !list || !editor) return;
    const show = clip && (clip.dataset.kind === "photo" || clip.dataset.kind === "video");
    wrap.hidden = !show;
    if (!show) return;
    const masks = readMasks(clip);
    if (!masks.some((item) => item.id === selectedMaskId)) {
      selectedMaskId = masks.length ? masks[0].id : null;
    }
    list.replaceChildren();
    masks.forEach((mask, index) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button ghost";
      button.textContent = `${maskEffectLabel(mask.effect)} ${index + 1}`;
      if (mask.id === selectedMaskId) button.setAttribute("aria-current", "true");
      button.addEventListener("click", () => {
        selectedMaskId = mask.id;
        fillMaskInspector(clip);
        drawPrivacyMasks();
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button ghost studio-mask-list-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", msgMaskRemove);
      remove.addEventListener("click", () => {
        selectedMaskId = mask.id;
        removeSelectedMask();
      });
      item.appendChild(button);
      item.appendChild(remove);
      list.appendChild(item);
    });
    const current = masks.find((item) => item.id === selectedMaskId) || null;
    editor.hidden = !current;
    refreshInspectorTabMarks(clip);
    if (!current || !effect || !strength) return;
    if (document.activeElement !== effect) effect.value = current.effect;
    if (document.activeElement !== strength) strength.value = String(current.strength);
    if (strengthValue) strengthValue.textContent = String(current.strength);
  }

  function replaceSelectedMask(patch) {
    const clip = selectedAdjustableClip();
    if (!clip || !selectedMaskId) return;
    const masks = readMasks(clip).map((item) =>
      item.id === selectedMaskId ? clampMaskBox({ ...item, ...patch }) : item
    );
    writeMasks(clip, masks);
    fillMaskInspector(clip);
    drawPrivacyMasks();
    queueMaskSave(clip);
  }

  function addPrivacyMask(effectName) {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    const masks = readMasks(clip);
    if (masks.length >= Number(maskModel.maxMasks || 8)) {
      showFlash(msgMaskLimit);
      return;
    }
    const shift = (masks.length % 4) * 0.06;
    const mask = clampMaskBox({
      id: newMaskId(),
      effect: effectName,
      strength: maskModel.defaultStrength,
      x: 0.2 + shift,
      y: 0.2 + shift,
      w: 0.28,
      h: 0.22,
    });
    masks.push(mask);
    selectedMaskId = mask.id;
    writeMasks(clip, masks);
    fillMaskInspector(clip);
    drawPrivacyMasks();
    queueMaskSave(clip);
  }

  const inspectorTabs = ["clip", "image", "effects", "overlays"];

  function setInspectorTab(name) {
    const tab = inspectorTabs.includes(name) ? name : "clip";
    const panel = document.getElementById("inspector-clip");
    if (panel) panel.dataset.tab = tab;
    document.querySelectorAll("[data-inspector-tab-button]").forEach((button) => {
      const on = button.dataset.inspectorTabButton === tab;
      button.classList.toggle("is-active", on);
      button.setAttribute("aria-selected", on ? "true" : "false");
    });
    try {
      sessionStorage.setItem("orga-drone.studio.inspectorTab", tab);
    } catch (_) {
      /* ignore */
    }
  }

  function refreshInspectorTabMarks(clip) {
    const image = document.getElementById("inspector-tab-image");
    const effects = document.getElementById("inspector-tab-effects");
    const overlays = document.getElementById("inspector-tab-overlays");
    if (!clip || !image || !effects || !overlays) return;
    const adjust = readImageAdjust(clip);
    const ramp = readSaturationRamp(clip);
    const frame = readFrame(clip);
    const frameActive =
      frame.zoom_start > 1.001 ||
      frame.zoom_end > 1.001 ||
      Math.abs(frame.x_start - 0.5) > 0.001 ||
      Math.abs(frame.y_start - 0.5) > 0.001 ||
      Math.abs(frame.x_end - 0.5) > 0.001 ||
      Math.abs(frame.y_end - 0.5) > 0.001;
    image.classList.toggle(
      "has-settings",
      !imageAdjustIsNeutral(adjust) || ramp.enabled === true || frameActive ||
        !hslIsNeutral(readHsl(clip)) || !colorWheelsIsNeutral(readColorWheels(clip))
    );
    const hud = readHud(clip);
    effects.classList.toggle("has-settings", readMasks(clip).length > 0 || hud.enabled === true);
    const map = readMap(clip);
    overlays.classList.toggle(
      "has-settings",
      readOverlays(clip).length > 0 || map.enabled === true
    );
  }

  function readStoredSize(key, min, max) {
    try {
      const raw = localStorage.getItem(key);
      if (raw == null || raw === "") return null;
      const value = Number(raw);
      if (!Number.isFinite(value)) return null;
      return Math.round(Math.max(min, Math.min(max, value)));
    } catch (_) {
      return null;
    }
  }

  function bindInspectorChrome() {
    const workspace = document.querySelector(".studio-workspace");
    const handle = document.getElementById("studio-inspector-resize");
    const inspector = document.getElementById("studio-inspector");
    if (workspace) {
      const saved = readStoredSize("orga-drone.studio.inspectorWidth", 240, 520);
      if (saved != null) workspace.style.setProperty("--studio-inspector-width", `${saved}px`);
    }
    if (handle && workspace && inspector) {
      handle.addEventListener("pointerdown", (event) => {
        if (window.matchMedia("(max-width: 1100px)").matches) return;
        if (event.button != null && event.button !== 0) return;
        event.preventDefault();
        handle.classList.add("is-dragging");
        const move = (ev) => {
          const rect = workspace.getBoundingClientRect();
          const max = Math.min(520, Math.max(280, rect.width * 0.46));
          const width = Math.round(Math.min(max, Math.max(240, rect.right - ev.clientX)));
          workspace.style.setProperty("--studio-inspector-width", `${width}px`);
        };
        const up = () => {
          handle.classList.remove("is-dragging");
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
          const raw = workspace.style.getPropertyValue("--studio-inspector-width");
          const width = Number.parseFloat(raw);
          if (Number.isFinite(width)) {
            try {
              localStorage.setItem("orga-drone.studio.inspectorWidth", String(Math.round(width)));
            } catch (_) {
              /* ignore */
            }
          }
          drawPrivacyMasks();
          drawFlightMap(resolveAt(state.projectTimeS));
          if (typeof layoutTimeline === "function") layoutTimeline();
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
        move(event);
      });
    }
    const browser = document.querySelector(".studio-browser");
    const browserHandle = document.getElementById("studio-browser-resize");
    const stage = document.querySelector(".studio-stage");
    const story = document.querySelector(".studio-story-area");
    const storyHandle = document.getElementById("studio-story-resize");
    if (workspace) {
      const savedBrowser = readStoredSize("orga-drone.studio.browserWidth", 200, 420);
      if (savedBrowser != null) workspace.style.setProperty("--studio-browser-width", `${savedBrowser}px`);
    }
    if (stage) {
      const savedStory = readStoredSize("orga-drone.studio.storyHeight", 128, 480);
      if (savedStory != null) stage.style.setProperty("--studio-story-height", `${savedStory}px`);
    }
    if (browserHandle && workspace && browser) {
      browserHandle.addEventListener("pointerdown", (event) => {
        if (window.matchMedia("(max-width: 800px)").matches) return;
        if (event.button != null && event.button !== 0) return;
        event.preventDefault();
        browserHandle.classList.add("is-dragging");
        const originX = event.clientX;
        const originW = browser.getBoundingClientRect().width;
        const move = (ev) => {
          const rect = workspace.getBoundingClientRect();
          const max = Math.min(420, Math.max(240, rect.width * 0.36));
          const width = Math.round(Math.min(max, Math.max(200, originW + (ev.clientX - originX))));
          workspace.style.setProperty("--studio-browser-width", `${width}px`);
        };
        const up = () => {
          browserHandle.classList.remove("is-dragging");
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
          const width = Number.parseFloat(workspace.style.getPropertyValue("--studio-browser-width"));
          if (Number.isFinite(width)) {
            try {
              localStorage.setItem("orga-drone.studio.browserWidth", String(Math.round(width)));
            } catch (_) {
              /* ignore */
            }
          }
          drawPrivacyMasks();
          drawFlightMap(resolveAt(state.projectTimeS));
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
        move(event);
      });
    }
    if (storyHandle && stage && story) {
      storyHandle.addEventListener("pointerdown", (event) => {
        if (window.matchMedia("(max-width: 800px)").matches) return;
        if (event.button != null && event.button !== 0) return;
        event.preventDefault();
        storyHandle.classList.add("is-dragging");
        const originY = event.clientY;
        const originH = story.getBoundingClientRect().height;
        const move = (ev) => {
          const rect = stage.getBoundingClientRect();
          const max = Math.min(480, Math.max(180, rect.height * 0.55));
          const height = Math.round(Math.min(max, Math.max(128, originH + (originY - ev.clientY))));
          stage.style.setProperty("--studio-story-height", `${height}px`);
        };
        const up = () => {
          storyHandle.classList.remove("is-dragging");
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
          const height = Number.parseFloat(stage.style.getPropertyValue("--studio-story-height"));
          if (Number.isFinite(height)) {
            try {
              localStorage.setItem("orga-drone.studio.storyHeight", String(Math.round(height)));
            } catch (_) {
              /* ignore */
            }
          }
          drawPrivacyMasks();
          drawFlightMap(resolveAt(state.projectTimeS));
          layoutTimeline();
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
        move(event);
      });
    }
    document.querySelectorAll("[data-inspector-tab-button]").forEach((button) => {
      button.addEventListener("click", () => setInspectorTab(button.dataset.inspectorTabButton));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Delete" && event.key !== "Backspace") return;
      const active = document.activeElement;
      const tag = active && active.tagName;
      if (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        (active && active.isContentEditable)
      ) {
        return;
      }
      if (selectedEffectBar) return;
      if (!privacyMaskDeleteActive()) return;
      event.preventDefault();
      removeSelectedMask();
    });
  }

  function privacyMaskDeleteActive() {
    if (!selectedMaskId) return false;
    const clipPanel = document.getElementById("inspector-clip");
    const masksPanel = document.getElementById("inspector-masks");
    if (!clipPanel || clipPanel.hidden || !masksPanel || masksPanel.hidden) return false;
    const active = document.activeElement;
    const inMaskUi = Boolean(
      active &&
        active.closest &&
        (active.closest("#studio-preview-mask-handles") ||
          active.closest("#inspector-masks") ||
          active.closest("#mask-list"))
    );
    return clipPanel.dataset.tab === "effects" || inMaskUi;
  }

  function removeSelectedMask() {
    const clip = selectedAdjustableClip();
    if (!clip || !selectedMaskId) return;
    const masks = readMasks(clip).filter((item) => item.id !== selectedMaskId);
    selectedMaskId = masks.length ? masks[0].id : null;
    writeMasks(clip, masks);
    fillMaskInspector(clip);
    drawPrivacyMasks();
    queueMaskSave(clip);
  }

  let maskSaveChain = Promise.resolve();

  function queueMaskSave(clip) {
    const studioId = clip.dataset.studioId;
    const snapshot = clip.dataset.masks || "[]";
    maskSaveChain = maskSaveChain
      .then(() => saveMasks(studioId, snapshot))
      .catch((err) => {
        showFlash((err && err.message) || msgMaskFailed);
      });
  }

  async function saveMasks(studioId, snapshot) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip) return;
    const res = await fetch(`/api/studio/${studioId}/masks`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ masks: JSON.parse(snapshot || "[]") }),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgMaskFailed);
    }
    if ((clip.dataset.masks || "[]") === snapshot) {
      writeMasks(clip, body.masks || []);
      if (
        state.selected &&
        state.selected.type === "clip" &&
        String(state.selected.id) === String(studioId)
      ) {
        fillMaskInspector(clip);
      }
      drawPrivacyMasks();
    }
    setSaveState(true);
  }

  function neutralFrame() {
    return {
      zoom_start: 1,
      zoom_end: 1,
      x_start: 0.5,
      y_start: 0.5,
      x_end: 0.5,
      y_end: 0.5,
    };
  }

  function clampZoom(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 1;
    const stepped = Math.round(number * 20) / 20;
    return Math.max(1, Math.min(3, stepped));
  }

  function clampFocal(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0.5;
    return Math.max(0, Math.min(1, number));
  }

  function readFrame(clip) {
    const neutral = neutralFrame();
    if (!clip) return neutral;
    try {
      const parsed = JSON.parse(clip.dataset.frame || "");
      if (!parsed || typeof parsed !== "object") return neutral;
      const zoomStart = clampZoom(parsed.zoom_start);
      return {
        zoom_start: zoomStart,
        zoom_end: clampZoom(parsed.zoom_end == null ? zoomStart : parsed.zoom_end),
        x_start: clampFocal(parsed.x_start),
        y_start: clampFocal(parsed.y_start),
        x_end: clampFocal(parsed.x_end == null ? parsed.x_start : parsed.x_end),
        y_end: clampFocal(parsed.y_end == null ? parsed.y_start : parsed.y_end),
      };
    } catch (_) {
      return neutral;
    }
  }

  function writeFrame(clip, frame) {
    if (!clip) return;
    clip.dataset.frame = JSON.stringify({
      zoom_start: clampZoom(frame.zoom_start),
      zoom_end: clampZoom(frame.zoom_end),
      x_start: Number(clampFocal(frame.x_start).toFixed(4)),
      y_start: Number(clampFocal(frame.y_start).toFixed(4)),
      x_end: Number(clampFocal(frame.x_end).toFixed(4)),
      y_end: Number(clampFocal(frame.y_end).toFixed(4)),
    });
    layoutEffectBars();
  }

  function frameMotionChecked() {
    return Boolean(document.getElementById("inspector-frame-motion")?.checked);
  }

  function frameMotionOn(frame) {
    return (
      Math.abs(frame.zoom_start - frame.zoom_end) > 0.001 ||
      Math.abs(frame.x_start - frame.x_end) > 0.001 ||
      Math.abs(frame.y_start - frame.y_end) > 0.001
    );
  }

  function formatZoom(value) {
    return `${clampZoom(value).toFixed(2)}×`;
  }

  function contentRect(frameW, frameH, sourceW, sourceH) {
    if (!(sourceW > 0) || !(sourceH > 0) || !(frameW > 0) || !(frameH > 0)) {
      return { x: 0, y: 0, w: frameW, h: frameH };
    }
    const scale = Math.min(frameW / sourceW, frameH / sourceH);
    const w = Math.max(1, Math.min(frameW, Math.round(sourceW * scale)));
    const h = Math.max(1, Math.min(frameH, Math.round(sourceH * scale)));
    return {
      x: Math.floor((frameW - w) / 2),
      y: Math.floor((frameH - h) / 2),
      w,
      h,
    };
  }

  function windowFor(zoom, focalX, focalY, frameW, frameH, sourceW, sourceH) {
    const content = contentRect(frameW, frameH, sourceW, sourceH);
    const viewW = Math.max(1, Math.min(content.w, Math.round(content.w / clampZoom(zoom))));
    const viewH = Math.max(1, Math.min(content.h, Math.round(content.h / clampZoom(zoom))));
    const centerX = content.x + clampFocal(focalX) * content.w;
    const centerY = content.y + clampFocal(focalY) * content.h;
    let left = Math.round(centerX - viewW / 2);
    let top = Math.round(centerY - viewH / 2);
    left = Math.max(content.x, Math.min(content.x + content.w - viewW, left));
    top = Math.max(content.y, Math.min(content.y + content.h - viewH, top));
    return { x: left, y: top, w: viewW, h: viewH, content };
  }

  function sampleFrame(frame, progress) {
    const span = Math.max(0, Math.min(1, Number(progress) || 0));
    return {
      zoom: frame.zoom_start + (frame.zoom_end - frame.zoom_start) * span,
      x: frame.x_start + (frame.x_end - frame.x_start) * span,
      y: frame.y_start + (frame.y_end - frame.y_start) * span,
    };
  }

  function sourceSize(el) {
    if (!el) return { w: 0, h: 0 };
    if (el.tagName === "VIDEO") {
      return { w: el.videoWidth || 0, h: el.videoHeight || 0 };
    }
    return { w: el.naturalWidth || 0, h: el.naturalHeight || 0 };
  }

  function clearFrameTransform(el) {
    if (!el) return;
    el.style.transform = "";
    el.style.transformOrigin = "";
  }

  function framePreviewProgress(clip, localS, sampleOverride) {
    if (sampleOverride != null && Number.isFinite(sampleOverride)) {
      const duration = sectionRepeats(clip) > 1 ? sectionCycleS(clip) : clipDuration(clip);
      if (!(duration > 0)) return 0;
      return Math.max(0, Math.min(1, sampleOverride / duration));
    }
    const selected = selectedAdjustableClip();
    const editing =
      !state.playing &&
      frameMotionChecked() &&
      selected &&
      clip &&
      String(selected.dataset.studioId) === String(clip.dataset.studioId);
    if (editing) return frameEditTarget === "end" ? 1 : 0;
    const repeated = sectionRepeats(clip) > 1;
    const duration = repeated ? sectionCycleS(clip) : clipDuration(clip);
    const sample = repeated ? sectionSampleS(clip, localS) : localS;
    if (!(duration > 0)) return 0;
    return Math.max(0, Math.min(1, sample / duration));
  }

  function applyFrameToElement(el, clip, localS, sampleOverride) {
    if (!el) return;
    const kind = clip && clip.dataset.kind;
    if (!clip || el.hidden || (kind !== "photo" && kind !== "video")) {
      clearFrameTransform(el);
      return;
    }
    const frame = readFrame(clip);
    if (clip.dataset.kind === "video") {
      const bar = zoomBarOf(clip);
      if (bar) {
        const offset = storyToSource(clip, localS);
        if (offset < bar.start - 0.001 || offset > bar.end + 0.001) {
          clearFrameTransform(el);
          return;
        }
      }
    }
    const sample = sampleFrame(frame, framePreviewProgress(clip, localS, sampleOverride));
    if (sample.zoom <= 1.001) {
      clearFrameTransform(el);
      return;
    }
    const bounds = el.getBoundingClientRect();
    const source = sourceSize(el);
    if (!(bounds.width > 0) || !(bounds.height > 0) || !(source.w > 0) || !(source.h > 0)) {
      clearFrameTransform(el);
      return;
    }
    const win = windowFor(
      sample.zoom,
      sample.x,
      sample.y,
      bounds.width,
      bounds.height,
      source.w,
      source.h
    );
    const scale = win.content.w / win.w;
    const tx = win.content.x - win.x * scale;
    const ty = win.content.y - win.y * scale;
    el.style.transformOrigin = "0 0";
    el.style.transform = `translate(${tx.toFixed(3)}px, ${ty.toFixed(3)}px) scale(${scale.toFixed(6)})`;
  }

  function applyFramePreview(hit) {
    const primary = hit && hit.clip ? hit.clip : null;
    const localS = hit && Number.isFinite(hit.localS) ? hit.localS : 0;
    applyFrameToElement(previewImage, primary, localS);
    applyFrameToElement(previewVideo, primary, localS);
    const loopPoint =
      primary && !hit.overlapClip && loopOverlapS(primary) > 0
        ? sectionPoint(primary, localS)
        : null;
    if (loopPoint && loopPoint.blending) {
      applyFrameToElement(previewVideoB, primary, localS, loopPoint.incomingOffset);
      applyFrameToElement(previewImageB, null, 0);
    } else {
      const overlap = hit && hit.overlapClip ? hit.overlapClip : null;
      const overlapLocal = hit && Number.isFinite(hit.overlapLocalS) ? hit.overlapLocalS : 0;
      applyFrameToElement(previewImageB, overlap, overlapLocal);
      applyFrameToElement(previewVideoB, overlap, overlapLocal);
    }
    const active = selectedAdjustableClip();
    const framing = active ? readFrame(active) : null;
    const zooming = Boolean(
      framing && (framing.zoom_start > 1.001 || framing.zoom_end > 1.001)
    );
    if (previewFrame) previewFrame.classList.toggle("is-framing", zooming);
  }

  let frameEditTarget = "start";
  let frameMotionArmed = false;

  function fillFrame(clip) {
    const frame = readFrame(clip);
    const motion = document.getElementById("inspector-frame-motion");
    const fields = document.getElementById("inspector-frame-motion-fields");
    const zoom = document.getElementById("inspector-frame-zoom");
    const zoomValue = document.getElementById("inspector-frame-zoom-value");
    const zoomEnd = document.getElementById("inspector-frame-zoom-end");
    const zoomEndValue = document.getElementById("inspector-frame-zoom-end-value");
    const moving = frameMotionArmed || frameMotionOn(frame);
    if (motion) motion.checked = moving;
    if (fields) fields.hidden = !moving;
    if (!moving) frameEditTarget = "start";
    if (zoom) zoom.value = String(frame.zoom_start);
    if (zoomValue) zoomValue.textContent = formatZoom(frame.zoom_start);
    if (zoomEnd) zoomEnd.value = String(frame.zoom_end);
    if (zoomEndValue) zoomEndValue.textContent = formatZoom(frame.zoom_end);
    document
      .getElementById("inspector-frame-target-start")
      ?.classList.toggle("is-active", frameEditTarget !== "end");
    document
      .getElementById("inspector-frame-target-end")
      ?.classList.toggle("is-active", frameEditTarget === "end");
  }

  function commitFrame(clip, frame) {
    writeFrame(clip, frame);
    fillFrame(clip);
    applyFramePreview(resolveAt(state.projectTimeS));
  }

  let frameSaveChain = Promise.resolve();

  function queueFrameSave(clip) {
    const studioId = clip.dataset.studioId;
    frameSaveChain = frameSaveChain
      .then(() => saveFrame(studioId))
      .catch((err) => {
        showFlash((err && err.message) || msgFrameFailed);
      });
  }

  async function saveFrame(studioId) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip) return;
    const frame = readFrame(clip);
    const res = await fetch(`/api/studio/${studioId}/frame`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ frame }),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgFrameFailed);
    }
    writeFrame(clip, body.frame || frame);
    if (
      state.selected &&
      state.selected.type === "clip" &&
      String(state.selected.id) === String(studioId)
    ) {
      fillFrame(clip);
    }
    applyFramePreview(resolveAt(state.projectTimeS));
    setSaveState(true);
  }

  function panFrame(clip, dx, dy) {
    const el = previewImage && !previewImage.hidden ? previewImage : previewVideo;
    if (!el) return;
    const bounds = el.getBoundingClientRect();
    const source = sourceSize(el);
    if (!(bounds.width > 0) || !(bounds.height > 0) || !(source.w > 0) || !(source.h > 0)) {
      return;
    }
    const frame = readFrame(clip);
    const moving = frameMotionChecked();
    const editingEnd = moving && frameEditTarget === "end";
    const zoom = editingEnd ? frame.zoom_end : frame.zoom_start;
    const focalX = editingEnd ? frame.x_end : frame.x_start;
    const focalY = editingEnd ? frame.y_end : frame.y_start;
    if (zoom <= 1.001) return;
    const win = windowFor(zoom, focalX, focalY, bounds.width, bounds.height, source.w, source.h);
    const scale = win.content.w / win.w;
    const left = win.x - dx / scale;
    const top = win.y - dy / scale;
    const nextX = clampFocal((left + win.w / 2 - win.content.x) / win.content.w);
    const nextY = clampFocal((top + win.h / 2 - win.content.y) / win.content.h);
    if (editingEnd) {
      frame.x_end = nextX;
      frame.y_end = nextY;
    } else if (moving) {
      frame.x_start = nextX;
      frame.y_start = nextY;
    } else {
      frame.x_start = nextX;
      frame.y_start = nextY;
      frame.x_end = nextX;
      frame.y_end = nextY;
      frame.zoom_end = frame.zoom_start;
    }
    commitFrame(clip, frame);
  }

  function showPlaceholder() {
    if (previewImage) previewImage.hidden = true;
    clearVideoElement();
    hideTitlecard();
    hideOverlayLayers();
    hideAnnotations();
    hidePrivacyMasks();
    paintHud(previewHud, null, 0, null);
    paintHud(previewHudB, null, 0, null);
    if (previewPlaceholder) previewPlaceholder.hidden = false;
    applyPreviewGrades(null);
    clearFrameTransform(previewImage);
    clearFrameTransform(previewVideo);
    clearFrameTransform(previewImageB);
    clearFrameTransform(previewVideoB);
    if (previewFrame) previewFrame.classList.remove("is-framing", "is-panning");
    if (previewImage) previewImage.classList.remove("is-pending");
    setPreviewLoading(false);
    paintPreviewBlit();
  }

  function showImage(src) {
    if (!previewImage) return;
    clearVideoElement();
    hideTitlecard();
    if (previewPlaceholder) previewPlaceholder.hidden = true;
    previewImage.hidden = false;
    if (!src) {
      loadedImageSrc = "";
      previewImage.removeAttribute("src");
      revealPreviewMedia(previewImage);
      return;
    }
    if (loadedImageSrc === src && previewImage.complete && previewImage.naturalWidth > 0) {
      revealPreviewMedia(previewImage);
      return;
    }
    loadedImageSrc = src;
    holdPreviewMedia(previewImage);
    const token = ++imageLoadToken;
    const finish = () => {
      if (token !== imageLoadToken) return;
      revealPreviewMedia(previewImage);
    };
    previewImage.addEventListener("load", finish, { once: true });
    previewImage.addEventListener("error", finish, { once: true });
    previewImage.src = src;
  }

  function seekVideoLocal(localS, clip) {
    if (!previewVideo) return;
    const inS = clip ? loopPlayInS(clip) : 0;
    const outS = clip ? loopPlayOutS(clip) : null;
    const lutProxy = lutProxyActiveFor(clip);
    const point = clip
      ? sectionPoint(clip, localS)
      : { index: 0, offset: Math.max(0, localS), atEnd: false };
    videoLoopIndex = point.index;
    const speed = clip ? playbackSpeed(clip) : 1;
    const mapped = clip && slowBarOf(clip) && speed >= 0.999
      ? storyToSource(clip, point.offset)
      : Math.max(0, point.offset) * speed;
    const target = clipMediaTarget(clip, mapped, inS);
    const apply = () => {
      try {
        applyClipPlayback(previewVideo, clip);
        let max = Number.isFinite(previewVideo.duration) ? previewVideo.duration : target;
        if (!lutProxy && outS != null && Number.isFinite(outS)) {
          max = Math.min(max > 0 ? max : outS, outS);
        }
        previewVideo.currentTime = Math.min(target, max > 0 ? max : target);
      } catch (_) {
        /* ignore seek errors while loading */
      }
    };
    if (previewVideo.readyState >= 1) apply();
    else {
      previewVideo.addEventListener("loadedmetadata", apply, { once: true });
    }
  }

  function showVideo(src, localS, { play, clip } = { play: false }) {
    if (!previewVideo) return;
    if (previewImage) previewImage.hidden = true;
    hideTitlecard();
    if (previewPlaceholder) previewPlaceholder.hidden = true;
    previewVideo.hidden = false;
    applyVolume();
    const lutSrc = clip ? lutProxySrcFor(clip) : "";
    if (lutSrc && src === lutSrc) {
      previewVideo.addEventListener("error", () => {
        if (!clip || loadedVideoSrc !== lutSrc) return;
        delete clip.dataset.lutProxyUrl;
        loadedVideoSrc = "";
        showVideo(videoSrcFor(clip), localS, { play: state.playing, clip });
      }, { once: true });
    }
    applyClipPlayback(previewVideo, clip);
    const needLoad = !src || loadedVideoSrc !== src;
    if (needLoad) {
      loadedVideoSrc = src || "";
      suppressVideoClock = true;
      holdPreviewMedia(previewVideo);
      previewVideo.src = src || "";
      previewVideo.load();
      const token = ++syncToken;
      const reveal = () => {
        if (token !== syncToken) return;
        revealPreviewMedia(previewVideo);
      };
      previewVideo.addEventListener("loadeddata", reveal, { once: true });
      previewVideo.addEventListener("error", reveal, { once: true });
      previewVideo.addEventListener(
        "loadedmetadata",
        () => {
          if (token !== syncToken) return;
          seekVideoLocal(localS, clip);
          suppressVideoClock = false;
          if (play && state.playing) {
            previewVideo.play().catch(() => {
              pausePlayback();
            });
          }
        },
        { once: true }
      );
      if (previewVideo.readyState >= 2) reveal();
      return;
    }
    revealPreviewMedia(previewVideo);
    suppressVideoClock = true;
    seekVideoLocal(localS, clip);
    // Allow clock after seek settles.
    window.setTimeout(() => {
      suppressVideoClock = false;
    }, 50);
    if (play && state.playing) {
      previewVideo.play().catch(() => {
        pausePlayback();
      });
    }
  }

  function showTitlecard(clip) {
    if (!previewTitlecard) return;
    if (previewImage) previewImage.hidden = true;
    clearVideoElement();
    if (previewPlaceholder) previewPlaceholder.hidden = true;
    setPreviewLoading(false);
    const bg = clip.dataset.background || "dark";
    previewTitlecard.hidden = false;
    previewTitlecard.setAttribute("data-bg", bg);
    if (previewTitlecardTitle) {
      previewTitlecardTitle.textContent = clip.dataset.displayTitle || clip.dataset.title || "";
    }
    if (previewTitlecardSubtitle) {
      const sub = clip.dataset.displaySubtitle || clip.dataset.subtitle || "";
      previewTitlecardSubtitle.textContent = sub;
      previewTitlecardSubtitle.hidden = !sub;
    }
  }

  function fillTitlecardEl(el, titleEl, subEl, clip) {
    if (!el) return;
    const bg = clip.dataset.background || "dark";
    el.hidden = false;
    el.setAttribute("data-bg", bg);
    if (titleEl) titleEl.textContent = clip.dataset.displayTitle || clip.dataset.title || "";
    if (subEl) {
      const sub = clip.dataset.displaySubtitle || clip.dataset.subtitle || "";
      subEl.textContent = sub;
      subEl.hidden = !sub;
    }
  }

  function showOutgoingLayer(clip, localS) {
    const kind = clip.dataset.kind || "unknown";
    if (kind === "title_card") {
      fillTitlecardEl(previewTitlecardB, previewTitlecardBTitle, previewTitlecardBSubtitle, clip);
      if (previewTitlecardB) previewTitlecardB.style.opacity = "1";
      return;
    }
    if (kind === "photo" || kind === "unknown") {
      const src = imageSrcFor(clip) || clip.dataset.thumb || "";
      if (previewImageB && src) {
        previewImageB.hidden = false;
        previewImageB.src = src;
        previewImageB.style.opacity = "1";
      }
      return;
    }
    if (kind === "video") {
      const thumb = clip.dataset.thumb || "";
      const src = videoSrcFor(clip);
      if (previewVideoB && src && clip.dataset.canPlay === "1") {
        previewVideoB.hidden = false;
        previewVideoB.muted = true;
        previewVideoB.style.opacity = "1";
        if (previewVideoB.getAttribute("src") !== src) {
          previewVideoB.src = src;
          previewVideoB.load();
        }
        const inS = loopPlayInS(clip);
        const target = inS + Math.max(0, sectionSampleS(clip, localS)) * playbackSpeed(clip);
        const apply = () => {
          try {
            applyClipPlayback(previewVideoB, clip);
            previewVideoB.currentTime = target;
          } catch (_) {
            /* ignore */
          }
        };
        if (previewVideoB.readyState >= 1) apply();
        else previewVideoB.addEventListener("loadedmetadata", apply, { once: true });
        return;
      }
      if (previewImageB && thumb) {
        previewImageB.hidden = false;
        previewImageB.src = thumb;
        previewImageB.style.opacity = "1";
      }
    }
  }

  function cinematicBlendProgress(clip, linear) {
    const t = Math.max(0, Math.min(1, Number(linear) || 0));
    if (
      clip &&
      clip.dataset.forwardLoopTransition === "cinematic" &&
      clip.dataset.loopTransitionCurve === "smooth"
    ) {
      return t * t * (3 - 2 * t);
    }
    return t;
  }

  function showLoopIncoming(clip, point) {
    if (!previewVideoB || !clip || !point || !point.blending) return false;
    const src = videoSrcFor(clip);
    if (!src || clip.dataset.canPlay !== "1") return false;
    previewVideoB.hidden = false;
    previewVideoB.muted = true;
    previewVideoB.style.opacity = "1";
    if (previewVideo && !previewVideo.hidden) {
      const eased = cinematicBlendProgress(clip, point.progress);
      previewVideo.style.opacity = String(Math.max(0, 1 - eased));
    }
    const inS = loopPlayInS(clip);
    const speed = playbackSpeed(clip);
    const target = inS + Math.max(0, point.incomingOffset) * speed;
    if (previewVideoB.getAttribute("src") !== src) {
      previewVideoB.src = src;
      previewVideoB.load();
    }
    const seek = () => {
      try {
        if (previewVideoB.playbackRate !== speed) previewVideoB.playbackRate = speed;
        const drift = Math.abs((previewVideoB.currentTime || 0) - target);
        if (drift > 0.12) previewVideoB.currentTime = target;
      } catch (_) {
        /* ignore */
      }
    };
    if (previewVideoB.readyState >= 1) seek();
    else previewVideoB.addEventListener("loadedmetadata", seek, { once: true });
    if (state.playing && previewVideoB.paused) {
      previewVideoB.play().catch(() => {
        /* the outgoing picture still advances */
      });
    }
    if (!state.playing && !previewVideoB.paused) {
      try {
        previewVideoB.pause();
      } catch (_) {
        /* ignore */
      }
    }
    return true;
  }

  function applyTransitionPreview(hit) {
    const loopPoint =
      hit && hit.clip && !hit.overlapClip && loopOverlapS(hit.clip) > 0
        ? sectionPoint(hit.clip, hit.localS)
        : null;
    const loopBlend = !!(loopPoint && loopPoint.blending && showLoopIncoming(hit.clip, loopPoint));
    const overlap = !loopBlend && hit && hit.overlapClip && hit.crossfadeProgress != null;
    if (!overlap && !loopBlend) {
      if (previewImageB) {
        previewImageB.hidden = true;
        previewImageB.style.opacity = "";
      }
      if (previewVideoB) {
        try {
          previewVideoB.pause();
        } catch (_) {
          /* ignore */
        }
        previewVideoB.hidden = true;
        previewVideoB.style.opacity = "";
      }
      if (previewTitlecardB) {
        previewTitlecardB.hidden = true;
        previewTitlecardB.style.opacity = "";
      }
      if (previewImage) previewImage.style.opacity = "";
      if (previewVideo) previewVideo.style.opacity = "";
      if (previewTitlecard) previewTitlecard.style.opacity = "";
    } else if (overlap) {
      showOutgoingLayer(hit.overlapClip, hit.overlapLocalS || 0);
      const progress = hit.crossfadeProgress;
      if (previewImage && !previewImage.hidden) previewImage.style.opacity = String(progress);
      if (previewVideo && !previewVideo.hidden) previewVideo.style.opacity = String(progress);
      if (previewTitlecard && !previewTitlecard.hidden) previewTitlecard.style.opacity = String(progress);
    }
    if (hit && hit.fadeBlackOpacity > 0.001 && previewFadeBlack) {
      previewFadeBlack.hidden = false;
      previewFadeBlack.style.opacity = String(hit.fadeBlackOpacity);
    } else if (previewFadeBlack) {
      previewFadeBlack.hidden = true;
      previewFadeBlack.style.opacity = "0";
    }
    applyPreviewGrades(hit);
    syncAnnotations(hit);
    drawPrivacyMasks();
    drawFlightMap(hit);
    applyFramePreview(hit);
    syncHud(hit);
    schedulePreviewBlit();
  }

  // A CSS-sized video is rasterized in CSS pixels. Grade filters, zoom scale,
  // and a large high-DPI pane then stretch that bitmap, so the live picture
  // looks grainy while export still scales the source frame. Blit the visible
  // picture at device pixels with smoothing. Privacy pixelate keeps its own
  // unsmoothed scratch canvas.
  let previewBlitCanvas = null;
  let previewBlitRaf = 0;

  function previewBackingRatio(cssW, cssH) {
    let dpr = Number(window.devicePixelRatio);
    if (!Number.isFinite(dpr) || dpr < 1) dpr = 1;
    dpr = Math.min(dpr, 3);
    const longEdge = Math.max(Number(cssW) || 0, Number(cssH) || 0);
    if (longEdge > 0 && longEdge * dpr > 4096) dpr = Math.max(1, 4096 / longEdge);
    return dpr;
  }

  function readPreviewTransform(el) {
    const text = (el && el.style && el.style.transform) || "";
    const match = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)\s*scale\(([-\d.]+)\)/.exec(text);
    if (!match) return { tx: 0, ty: 0, scale: 1 };
    const scale = Number(match[3]);
    return {
      tx: Number(match[1]) || 0,
      ty: Number(match[2]) || 0,
      scale: scale > 0 ? scale : 1,
    };
  }

  function previewLayerReady(media) {
    if (!media || media.hidden || media.classList.contains("is-pending")) return false;
    const srcW = media.videoWidth || media.naturalWidth || 0;
    const srcH = media.videoHeight || media.naturalHeight || 0;
    return srcW > 0 && srcH > 0;
  }

  let previewGradeScratch = null;

  function previewGradeSource(media, filter) {
    if (!filter || filter === "none") return media;
    const srcW = media.videoWidth || media.naturalWidth || 0;
    const srcH = media.videoHeight || media.naturalHeight || 0;
    if (!srcW || !srcH) return media;
    if (!previewGradeScratch) previewGradeScratch = document.createElement("canvas");
    if (previewGradeScratch.width !== srcW || previewGradeScratch.height !== srcH) {
      previewGradeScratch.width = srcW;
      previewGradeScratch.height = srcH;
    }
    const scratch = previewGradeScratch.getContext("2d");
    if (!scratch) return media;
    scratch.filter = "none";
    scratch.clearRect(0, 0, srcW, srcH);
    scratch.drawImage(media, 0, 0, srcW, srcH);
    return previewGradeScratch;
  }

  function drawPreviewLayer(ctx, media, frameW, frameH, rendered = null) {
    if (!previewLayerReady(media)) return false;
    const webgl = previewLutFrameFor(media, frameW, frameH);
    if (webgl && previewFrame) {
      previewFrame.dataset.lutWebgl = "1";
      previewFrame.dataset.lutWebglWidth = String(webgl.width);
      previewFrame.dataset.lutWebglHeight = String(webgl.height);
    }
    const picture = webgl || rendered || media;
    const srcW = picture.videoWidth || picture.naturalWidth || picture.width || 0;
    const srcH = picture.videoHeight || picture.naturalHeight || picture.height || 0;
    if (!srcW || !srcH) return false;
    const fit = contentRect(frameW, frameH, srcW, srcH);
    const xform = readPreviewTransform(media);
    const parsed = media.style.opacity === "" ? 1 : Number(media.style.opacity);
    const alpha = Number.isFinite(parsed) ? Math.max(0, Math.min(1, parsed)) : 1;
    if (alpha <= 0.001) return true;
    // WebGL output, server stills and LUT proxies already contain grade + LUT.
    const proxyRendered = (media === previewVideo || media === previewVideoB) &&
      lutProxyActiveFor(clipForPreviewMedia(media));
    const filter = webgl || rendered || proxyRendered
      ? "none"
      : canvasFilterFrom(media.style.filter);
    ctx.save();
    try {
      ctx.globalAlpha = alpha;
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.translate(xform.tx, xform.ty);
      ctx.scale(xform.scale, xform.scale);
      const source = previewGradeSource(picture, filter);
      ctx.filter = filter || "none";
      ctx.drawImage(source, fit.x, fit.y, fit.w, fit.h);
      return true;
    } catch (_) {
      try {
        ctx.filter = "none";
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = "high";
        ctx.drawImage(picture, fit.x, fit.y, fit.w, fit.h);
        return true;
      } catch (_) {
        return false;
      }
    } finally {
      ctx.restore();
    }
  }

  function ensurePreviewBlit() {
    if (previewBlitCanvas || !previewFrame) return previewBlitCanvas;
    const canvas = document.createElement("canvas");
    canvas.id = "studio-preview-blit";
    canvas.className = "studio-preview-blit";
    canvas.hidden = true;
    canvas.setAttribute("aria-hidden", "true");
    const before = previewMasksB || previewMasks || null;
    if (before && before.parentNode === previewFrame) previewFrame.insertBefore(canvas, before);
    else previewFrame.appendChild(canvas);
    previewBlitCanvas = canvas;
    [previewVideo, previewVideoB, previewImage, previewImageB, previewLutStill].forEach((media) => {
      if (!media) return;
      const kick = () => schedulePreviewBlit();
      media.addEventListener("loadeddata", kick);
      media.addEventListener("seeked", kick);
      media.addEventListener("play", kick);
      media.addEventListener("load", kick);
    });
    if (typeof ResizeObserver === "function") {
      const observer = new ResizeObserver(() => schedulePreviewBlit());
      observer.observe(previewFrame);
    }
    return canvas;
  }

  function paintPreviewBlit() {
    const canvas = ensurePreviewBlit();
    if (!canvas || !previewFrame) return;
    const cssW = previewFrame.clientWidth;
    const cssH = previewFrame.clientHeight;
    if (cssW < 2 || cssH < 2) {
      canvas.hidden = true;
      return;
    }
    const dpr = previewBackingRatio(cssW, cssH);
    const pixelW = Math.max(1, Math.round(cssW * dpr));
    const pixelH = Math.max(1, Math.round(cssH * dpr));
    if (canvas.width !== pixelW || canvas.height !== pixelH) {
      canvas.width = pixelW;
      canvas.height = pixelH;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      canvas.hidden = true;
      return;
    }
    const secondary = visibleSecondaryMedia();
    const primary = visiblePrimaryMedia();
    if (!previewLayerReady(secondary) && !previewLayerReady(primary)) {
      canvas.hidden = true;
      return;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, cssW, cssH);
    const drewSecondary = drawPreviewLayer(ctx, secondary, cssW, cssH);
    const rendered = !reuseDraft && !state.playing && previewLayerReady(previewLutStill) ? previewLutStill : null;
    const drewPrimary = drawPreviewLayer(ctx, primary, cssW, cssH, rendered);
    canvas.hidden = !(drewSecondary || drewPrimary);
  }

  function schedulePreviewBlit() {
    if (previewBlitRaf) return;
    previewBlitRaf = requestAnimationFrame(() => {
      previewBlitRaf = 0;
      paintPreviewBlit();
      const playing = [previewVideo, previewVideoB].some(
        (video) => video && !video.hidden && !video.paused && !video.ended
      );
      if (playing) schedulePreviewBlit();
    });
  }

  function syncPreviewMedia({ seek = false } = {}) {
    if (reuseDraft) return;
    void seek;
    const hit = resolveAt(state.projectTimeS);
    if (!hit) {
      state.activeStudioId = null;
      markActiveClips(null, null);
      showPlaceholder();
      updateCutEnabled();
      return;
    }
    const { clip, localS, atEnd } = hit;
    state.activeStudioId = clip.dataset.studioId || null;
    markActiveClips(clip, hit.overlapClip);

    const kind = clip.dataset.kind || "unknown";
    const canPlay = clip.dataset.canPlay === "1";

    if (kind === "title_card") {
      showTitlecard(clip);
      applyTransitionPreview(hit);
      updateCutEnabled();
      return;
    }

    if (kind === "photo") {
      const src = imageSrcFor(clip);
      if (src) showImage(src);
      else showPlaceholder();
      applyTransitionPreview(hit);
      updateCutEnabled();
      return;
    }

    if (kind === "video" && canPlay) {
      const src = videoSrcFor(clip);
      if (!src) {
        const thumb = clip.dataset.thumb || "";
        if (thumb) showImage(thumb);
        else showPlaceholder();
        applyTransitionPreview(hit);
        updateCutEnabled();
        return;
      }
      showVideo(src, localS, { play: state.playing && !atEnd, clip });
      applyTransitionPreview(hit);
      updateCutEnabled();
      return;
    }

    const thumb = clip.dataset.thumb || "";
    if (thumb) showImage(thumb);
    else showPlaceholder();
    applyTransitionPreview(hit);
    updateCutEnabled();
  }

  function setProjectTime(t, { resume = false, fromVideo = false } = {}) {
    if (reuseDraft) return;
    const total = totalDuration();
    let next = Math.max(0, Number(t) || 0);
    if (total > 0 && next > total) next = total;
    state.projectTimeS = next;
    updatePlayheadChrome();

    if (!fromVideo) {
      syncPreviewMedia({ seek: true });
    } else {
      const hit = resolveAt(state.projectTimeS);
      if (hit) {
        state.activeStudioId = hit.clip.dataset.studioId || null;
        markActiveClips(hit.clip, hit.overlapClip);
        applyTransitionPreview(hit);
      }
      updateCutEnabled();
    }

    if (total > 0 && state.projectTimeS >= total - 0.001) {
      state.projectTimeS = total;
      updatePlayheadChrome();
      if (state.playing) pausePlayback();
      return;
    }

    if (resume && !state.playing) {
      startPlayback();
    } else if (state.playing && !fromVideo) {
      // After seek while playing, ensure the correct clock driver runs.
      beginClockForActiveClip();
    }
    syncMusicAudio();
  }

  function advanceToNextOrStop(hit) {
    const list = clips().filter((c) => clipDuration(c) > 0);
    if (!hit || !list.length) {
      pausePlayback();
      return;
    }
    const idx = list.indexOf(hit.clip);
    if (idx >= 0 && idx < list.length - 1) {
      const next = list[idx + 1];
      setProjectTime(clipStartTime(next));
      if (state.playing) beginClockForActiveClip();
      return;
    }
    setProjectTime(totalDuration());
    pausePlayback();
  }

  function wallClockTick(nowMs) {
    if (!state.playing) {
      stopWallClock();
      return;
    }
    if (!wallClockLastMs) wallClockLastMs = nowMs;
    const dt = Math.max(0, (nowMs - wallClockLastMs) / 1000);
    wallClockLastMs = nowMs;
    const total = totalDuration();
    const next = state.projectTimeS + dt;
    if (next >= total) {
      setProjectTime(total);
      pausePlayback();
      return;
    }
    const before = resolveAt(state.projectTimeS);
    state.projectTimeS = next;
    updatePlayheadChrome();
    const after = resolveAt(state.projectTimeS);
    if (!after) {
      pausePlayback();
      return;
    }
    if (!before || before.clip !== after.clip) {
      syncPreviewMedia({ seek: true });
      beginClockForActiveClip();
      syncMusicAudio();
      return;
    }
    applyTransitionPreview(after);
    syncMusicAudio();
    wallClockRaf = requestAnimationFrame(wallClockTick);
  }

  function startWallClock() {
    stopWallClock();
    wallClockLastMs = 0;
    wallClockRaf = requestAnimationFrame(wallClockTick);
  }

  function beginClockForActiveClip() {
    if (!state.playing) return;
    const hit = resolveAt(state.projectTimeS);
    if (!hit || hit.atEnd) {
      pausePlayback();
      return;
    }
    const kind = hit.clip.dataset.kind || "unknown";
    const canPlay = hit.clip.dataset.canPlay === "1";
    if (kind === "video" && canPlay && videoSrcFor(hit.clip)) {
      stopWallClock();
      syncPreviewMedia({ seek: true });
      if (previewVideo) {
        previewVideo.play().catch(() => {
          // Autoplay blocked or decode error → fall back to wall clock stills.
          startWallClock();
        });
      }
      return;
    }
    if (previewVideo) {
      try {
        previewVideo.pause();
      } catch (_) {
        /* ignore */
      }
    }
    syncPreviewMedia({ seek: true });
    startWallClock();
  }

  function startPlayback() {
    if (reuseDraft) return;
    const total = totalDuration();
    if (total <= 0) return;
    if (state.projectTimeS >= total - 0.001) {
      state.projectTimeS = 0;
    }
    state.playing = true;
    setToggleLabel();
    beginClockForActiveClip();
    syncMusicAudio();
  }

  function onVideoTimeUpdate() {
    if (reuseDraft && previewVideo) {
      if (previewVideo.currentTime >= reuseDraft.outS - 0.02) previewVideo.pause();
      return;
    }
    if (!state.playing || suppressVideoClock || !previewVideo) return;
    if (!previewVideo.getAttribute("src") && !previewVideo.currentSrc) return;
    const playing = clips().find(
      (c) => String(c.dataset.studioId) === String(state.activeStudioId)
    );
    if (!playing || playing.dataset.kind !== "video") {
      applyTransitionPreview(resolveAt(state.projectTimeS));
      return;
    }
    const inS = sourceInS(playing);
    const outS = sourceOutS(playing);
    const speed = playbackSpeed(playing);
    const reps = sectionRepeats(playing);
    const cycle = sectionCycleS(playing);
    const mediaTime = previewVideo.currentTime || 0;
    applyClipPlayback(previewVideo, playing);
    const offset = clipOffsetFromMediaTime(playing, mediaTime, inS);
    const within = slowBarOf(playing) && speed >= 0.999
      ? sourceToStory(playing, offset)
      : offset / speed;
    const loopOverlap = forwardLoopOverlapS(playing);
    const loopSpans = loopOverlap > 0 ? forwardLoopSpans(playing) : [];
    let local = reps > 1 ? videoLoopIndex * cycle + within : within;
    if (loopOverlap > 0 && loopSpans.length) {
      const starts = forwardLoopStarts(loopSpans, loopOverlap);
      const index = Math.max(0, Math.min(loopSpans.length - 1, videoLoopIndex));
      local = (starts[index] || 0) + within;
    }
    const next = clipStartTime(playing) + local;
    if (Math.abs(next - state.projectTimeS) >= 0.01) {
      state.projectTimeS = next;
    }
    updatePlayheadChrome();
    const after = resolveAt(state.projectTimeS);
    applyTransitionPreview(after);
    updateCutEnabled();
    syncMusicAudio();
    if (!after) {
      pausePlayback();
      return;
    }
    if (after.clip !== playing) {
      syncPreviewMedia({ seek: true });
      beginClockForActiveClip();
      return;
    }
    // A forward crossfade keeps the outgoing picture on this element and the
    // incoming picture on the second element. At the end of the outgoing play
    // the clock continues from the overlap already shown, still moving forward.
    // Soundtrack time follows projectTimeS and is not restarted here.
    if (loopOverlap > 0 && loopSpans.length) {
      const index = Math.max(0, Math.min(loopSpans.length - 1, videoLoopIndex));
      const span = loopSpans[index] || 0;
      const endMedia = inS + span * speed;
      if (index + 1 < loopSpans.length && mediaTime >= endMedia - 0.02) {
        if (loopSeeking) return;
        loopSeeking = true;
        videoLoopIndex = index + 1;
        suppressVideoClock = true;
        const starts = forwardLoopStarts(loopSpans, loopOverlap);
        state.projectTimeS = clipStartTime(playing) + (starts[index + 1] || 0) + loopOverlap;
        updatePlayheadChrome();
        applyTransitionPreview(resolveAt(state.projectTimeS));
        let settled = false;
        const settle = () => {
          if (settled) return;
          settled = true;
          loopSeeking = false;
          suppressVideoClock = false;
        };
        previewVideo.addEventListener("seeked", settle, { once: true });
        window.setTimeout(settle, 200);
        try {
          previewVideo.currentTime = inS + loopOverlap * speed;
        } catch (_) {
          settle();
        }
        if (state.playing) {
          previewVideo.play().catch(() => {
            pausePlayback();
          });
        }
        return;
      }
      if (mediaTime >= endMedia - 0.05) {
        advanceToNextOrStop(after);
      }
      return;
    }
    // Section repeat and a hard-cut soundtrack loop seek the picture back to
    // source in. Soundtrack time follows projectTimeS and is not restarted here.
    if (reps > 1 && outS != null && mediaTime >= outS - 0.01 && videoLoopIndex + 1 < reps) {
      if (loopSeeking) return;
      loopSeeking = true;
      videoLoopIndex += 1;
      suppressVideoClock = true;
      state.projectTimeS = clipStartTime(playing) + videoLoopIndex * cycle;
      updatePlayheadChrome();
      applyTransitionPreview(resolveAt(state.projectTimeS));
      let settled = false;
      const settle = () => {
        if (settled) return;
        settled = true;
        loopSeeking = false;
        suppressVideoClock = false;
      };
      previewVideo.addEventListener("seeked", settle, { once: true });
      window.setTimeout(settle, 200);
      try {
        previewVideo.currentTime = inS;
      } catch (_) {
        settle();
      }
      if (state.playing) {
        previewVideo.play().catch(() => {
          pausePlayback();
        });
      }
      return;
    }
    if (outS != null && mediaTime >= outS - 0.05) {
      advanceToNextOrStop(after);
      return;
    }
    if (clipDuration(playing) > 0 && local >= clipDuration(playing) - 0.05) {
      advanceToNextOrStop(after);
    }
  }

  function onVideoEnded() {
    if (!state.playing || suppressVideoClock || !previewVideo) return;
    if (!previewVideo.getAttribute("src") && !previewVideo.currentSrc) return;
    const hit = resolveAt(state.projectTimeS);
    if (!hit) {
      pausePlayback();
      return;
    }
    if (hit.clip.dataset.kind !== "video") {
      syncPreviewMedia({ seek: true });
      beginClockForActiveClip();
      return;
    }
    const reps = sectionRepeats(hit.clip);
    const endedOverlap = loopOverlapS(hit.clip);
    if (endedOverlap > 0 && videoLoopIndex + 1 < reps) {
      const inS = loopPlayInS(hit.clip);
      const speed = playbackSpeed(hit.clip);
      videoLoopIndex += 1;
      const spans = forwardLoopActive(hit.clip)
        ? forwardLoopSpans(hit.clip)
        : manualRepeatSpans(hit.clip);
      const starts = forwardLoopStarts(spans, endedOverlap);
      state.projectTimeS = clipStartTime(hit.clip) + (starts[videoLoopIndex] || 0) + endedOverlap;
      updatePlayheadChrome();
      try {
        previewVideo.currentTime = inS + endedOverlap * speed;
      } catch (_) {
        /* ignore */
      }
      if (state.playing) {
        previewVideo.play().catch(() => {
          pausePlayback();
        });
      }
      return;
    }
    if (reps > 1 && videoLoopIndex + 1 < reps) {
      videoLoopIndex += 1;
      const inS = sourceInS(hit.clip);
      state.projectTimeS = clipStartTime(hit.clip) + videoLoopIndex * sectionCycleS(hit.clip);
      updatePlayheadChrome();
      try {
        previewVideo.currentTime = inS;
      } catch (_) {
        /* ignore */
      }
      if (state.playing) {
        previewVideo.play().catch(() => {
          pausePlayback();
        });
      }
      return;
    }
    advanceToNextOrStop(hit);
  }

  function loadUiState() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (data && typeof data === "object") {
        // Title and transitions are persisted in SQLite; do not restore from session.
        if (typeof data.volume === "number") {
          state.volume = Math.max(0, Math.min(1, data.volume));
          if (volumeInput) volumeInput.value = String(Math.round(state.volume * 100));
        }
        const timeline = data.timeline;
        if (
          timeline &&
          typeof timeline === "object" &&
          Number(timeline.projectId) === projectId
        ) {
          if (timeline.mode === "fit" || timeline.mode === "zoom") {
            state.timelineMode = timeline.mode;
          }
          if (typeof timeline.zoomIndex === "number") {
            state.zoomIndex = Math.max(
              0,
              Math.min(TIMELINE_ZOOM_PX_S.length - 1, Math.round(timeline.zoomIndex))
            );
          }
        }
      }
    } catch (_) {
      /* ignore */
    }
  }

  function persistUiState() {
    try {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          volume: state.volume,
          timeline: {
            projectId,
            mode: state.timelineMode,
            zoomIndex: state.zoomIndex,
          },
        })
      );
    } catch (_) {
      /* ignore */
    }
  }

  const MUSIC_MAX_TRACKS = 8;

  function musicFromPayload(payload) {
    if (!payload) return null;
    const volume = Number(payload.volume);
    const fadeIn = Number(payload.fade_in_s);
    const fadeOut = Number(payload.fade_out_s);
    const durationS = Number(payload.duration_s);
    const id = Number(payload.id);
    return {
      id: Number.isFinite(id) ? id : 0,
      name: payload.display_name || "Music",
      volume: Number.isFinite(volume) ? volume : 0.8,
      fadeIn: Number.isFinite(fadeIn) ? fadeIn : 0,
      fadeOut: Number.isFinite(fadeOut) ? fadeOut : 0,
      loop: !!payload.loop,
      available: payload.available !== false,
      streamUrl: payload.stream_url || null,
      durationS: Number.isFinite(durationS) && durationS > 0 ? durationS : 0,
    };
  }

  function applyTracksPayload(payload) {
    const list = payload && Array.isArray(payload.tracks) ? payload.tracks : [];
    const startS = Number(payload && payload.music_start_s);
    if (Number.isFinite(startS)) state.musicStartS = Math.max(0, startS);
    state.tracks = list.map(musicFromPayload).filter(Boolean);
  }

  function selectedMusicTrack() {
    if (state.selected.type !== "music") return null;
    return state.tracks.find((t) => String(t.id) === String(state.selected.id)) || null;
  }

  function musicLoopEnabled() {
    return state.tracks.length === 1 && !!state.tracks[0].loop;
  }

  function musicBedDuration(storyS, musicS, loop) {
    if (loop) return Math.max(0, storyS);
    if (!(musicS > 0)) return 0;
    return Math.min(musicS, Math.max(0, storyS));
  }

  function formatLaneTime(seconds) {
    return formatTime(seconds).replace(/^00:/, "");
  }

  function trackDurationS(track) {
    if (!track || !track.available) return 0;
    if (track.durationS > 0) return track.durationS;
    for (const el of [musicAudio, musicAudioNext]) {
      if (
        el &&
        el.getAttribute("src") === track.streamUrl &&
        Number.isFinite(el.duration) &&
        el.duration > 0
      ) {
        track.durationS = el.duration;
        return el.duration;
      }
    }
    return 0;
  }

  function updateMusicAddEnabled() {
    const btn = document.getElementById("studio-music-add");
    if (!btn) return;
    btn.disabled = state.tracks.length >= MUSIC_MAX_TRACKS;
  }

  function playlistHit(t) {
    const story = totalDuration();
    if (!(story > 0) || t < 0 || t >= story || !state.tracks.length) return null;
    const musicStartS = Math.max(0, Math.min(story, state.musicStartS));
    if (t < musicStartS) return null;
    if (musicLoopEnabled()) {
      const track = state.tracks[0];
      const mus = trackDurationS(track);
      if (!(mus > 0) || !track.available) return null;
      return {
        track,
        index: 0,
        offset: (t - musicStartS) % mus,
        startS: musicStartS,
        spanS: story - musicStartS,
      };
    }
    let cursor = musicStartS;
    for (let i = 0; i < state.tracks.length; i += 1) {
      const track = state.tracks[i];
      const mus = trackDurationS(track);
      const remaining = Math.max(0, story - cursor);
      const span = track.available ? Math.min(Math.max(0, mus), remaining) : 0;
      if (span > 0 && t >= cursor && t < cursor + span) {
        return { track, index: i, offset: t - cursor, startS: cursor, spanS: span };
      }
      cursor += span;
      if (cursor >= story) break;
    }
    return null;
  }

  function musicClipEls() {
    const clipsEl = document.getElementById("studio-music-clips");
    if (!clipsEl) return [];
    return Array.from(clipsEl.querySelectorAll(":scope > .studio-music-select"));
  }

  function syncTracksFromMusicDom() {
    const byId = new Map(state.tracks.map((track) => [String(track.id), track]));
    const next = [];
    musicClipEls().forEach((el) => {
      const track = byId.get(String(el.dataset.musicId));
      if (track) next.push(track);
    });
    if (next.length === state.tracks.length) state.tracks = next;
  }

  function createMusicClipEl(track) {
    const card = document.createElement("div");
    card.className = "studio-music-select";
    card.dataset.musicId = String(track.id);
    const startHandle = document.createElement("button");
    startHandle.type = "button";
    startHandle.className = "studio-music-start-handle";
    startHandle.setAttribute("aria-label", msgDragMusicStart);
    startHandle.title = msgDragMusicStart;
    startHandle.setAttribute("aria-hidden", "true");
    const handle = document.createElement("button");
    handle.type = "button";
    handle.className = "studio-drag-handle";
    handle.draggable = true;
    handle.setAttribute("aria-label", msgDragReorder);
    handle.title = msgDragReorder;
    const handleMark = document.createElement("span");
    handleMark.setAttribute("aria-hidden", "true");
    handleMark.textContent = "≡";
    handle.appendChild(handleMark);
    const body = document.createElement("button");
    body.type = "button";
    body.className = "studio-music-clip-body";
    const nameEl = document.createElement("strong");
    const meta = document.createElement("span");
    meta.className = "studio-music-meta";
    const badge = document.createElement("span");
    badge.className = "studio-music-badge";
    badge.hidden = true;
    const fadeInEl = document.createElement("span");
    fadeInEl.className = "studio-music-fade studio-music-fade-in";
    fadeInEl.hidden = true;
    fadeInEl.setAttribute("aria-hidden", "true");
    const fadeOutEl = document.createElement("span");
    fadeOutEl.className = "studio-music-fade studio-music-fade-out";
    fadeOutEl.hidden = true;
    fadeOutEl.setAttribute("aria-hidden", "true");
    body.append(nameEl, meta, badge, fadeInEl, fadeOutEl);
    card.append(startHandle, handle, body);
    return card;
  }

  function layoutMusicSpans() {
    const clipsEl = document.getElementById("studio-music-clips");
    const empty = document.getElementById("studio-music-empty");
    const trackEl = document.getElementById("studio-music-track");
    if (!clipsEl) return;
    if (empty) empty.hidden = state.tracks.length > 0;
    if (trackEl) {
      trackEl.classList.toggle("is-selected", state.selected.type === "music");
    }
    updateMusicAddEnabled();
    if (!musicDragCard) {
      const ids = state.tracks.map((track) => String(track.id));
      const existing = musicClipEls().map((el) => String(el.dataset.musicId));
      if (existing.join(",") !== ids.join(",")) {
        clipsEl.replaceChildren();
        state.tracks.forEach((track) => clipsEl.appendChild(createMusicClipEl(track)));
      }
    }
    if (!state.tracks.length) return;

    const story = totalDuration();
    const loop = musicLoopEnabled();
    const msgLoop = root.dataset.musicLoopBadge || "Loop · repeats to Story end";
    const msgSilence = root.dataset.musicSilenceBadge || "then silence";
    const msgPending = root.dataset.musicPending || "Duration unknown";
    const msgCoverage = root.dataset.musicCoverage || "{music} of {story}";
    const cards = musicClipEls();
    let cursor = Math.max(0, Math.min(story, state.musicStartS));
    cards.forEach((card, index) => {
      const track = state.tracks.find((item) => String(item.id) === String(card.dataset.musicId));
      if (!track) return;
      const nameEl = card.querySelector("strong");
      const meta = card.querySelector(".studio-music-meta");
      const badge = card.querySelector(".studio-music-badge");
      const fadeInEl = card.querySelector(".studio-music-fade-in");
      const fadeOutEl = card.querySelector(".studio-music-fade-out");
      const body = card.querySelector(".studio-music-clip-body");
      const startHandle = card.querySelector(".studio-music-start-handle");
      if (startHandle) {
        startHandle.hidden = index !== 0;
        startHandle.setAttribute("aria-hidden", index === 0 ? "false" : "true");
      }
      card.classList.remove("is-pending", "is-missing", "is-selected");
      if (nameEl) nameEl.textContent = track.name;
      if (body) body.setAttribute("aria-label", track.name);
      if (meta) meta.textContent = "";
      if (badge) {
        badge.hidden = true;
        badge.textContent = "";
      }
      if (fadeInEl) {
        fadeInEl.hidden = true;
        fadeInEl.style.width = "";
      }
      if (fadeOutEl) {
        fadeOutEl.hidden = true;
        fadeOutEl.style.width = "";
      }
      if (String(state.selected.id) === String(track.id) && state.selected.type === "music") {
        card.classList.add("is-selected");
      }
      const musDur = trackDurationS(track);
      const known = musDur > 0;
      const remaining = Math.max(0, story - cursor);
      let spanS = 0;
      if (!track.available) {
        card.classList.add("is-missing");
        if (badge) {
          badge.hidden = false;
          badge.textContent = msgMusicMissing;
        }
      } else if (!known && !loop) {
        card.classList.add("is-pending");
        if (badge) {
          badge.hidden = false;
          badge.textContent = msgPending;
        }
      }
      if (loop) {
        spanS = musicBedDuration(remaining, musDur, true);
      } else if (musDur > 0 && remaining > 0) {
        spanS = Math.min(musDur, remaining);
      }
      const leftPx = timeToX(cursor);
      const widthPx = spanS > 0 ? Math.max(0, timeToX(cursor + spanS) - timeToX(cursor)) : 0;
      card.style.left = `${leftPx}px`;
      card.style.width = `${widthPx}px`;
      card.classList.toggle("is-narrow", widthPx < TIMELINE_HIT_MIN_PX);
      if (spanS > 0) cursor += spanS;
      if (known && story > 0 && meta) {
        meta.textContent = msgCoverage
          .replace("{music}", formatLaneTime(musDur))
          .replace("{story}", formatLaneTime(story));
      }
      if (loop && badge && track.available) {
        badge.hidden = false;
        badge.textContent = msgLoop;
      } else if (
        index === cards.length - 1 &&
        known &&
        cursor < story &&
        badge &&
        !card.classList.contains("is-missing")
      ) {
        badge.hidden = false;
        badge.textContent = msgSilence;
      }
      const scaled = scaledMusicFades(track.fadeIn, track.fadeOut, spanS || xToTime(widthPx));
      const fiPx = timeToX(scaled.fadeIn);
      const foPx = timeToX(scaled.fadeOut);
      if (fadeInEl && scaled.fadeIn > 0 && fiPx >= TIMELINE_HIT_MIN_PX) {
        fadeInEl.hidden = false;
        fadeInEl.style.width = `${fiPx}px`;
      }
      if (fadeOutEl && scaled.fadeOut > 0 && foPx >= TIMELINE_HIT_MIN_PX) {
        fadeOutEl.hidden = false;
        fadeOutEl.style.width = `${foPx}px`;
      }
    });
  }

  function scaledMusicFades(fadeIn, fadeOut, bedS) {
    let fi = Math.max(0, fadeIn);
    let fo = Math.max(0, fadeOut);
    const bed = Math.max(0, bedS);
    const total = fi + fo;
    if (bed <= 0 || total <= 0) return { fadeIn: 0, fadeOut: 0 };
    if (total > bed) {
      const scale = bed / total;
      return { fadeIn: fi * scale, fadeOut: fo * scale };
    }
    return { fadeIn: fi, fadeOut: fo };
  }

  function musicFadeGain(t, bedS, fadeIn, fadeOut) {
    if (t < 0 || t >= bedS) return 0;
    const scaled = scaledMusicFades(fadeIn, fadeOut, bedS);
    let gain = 1;
    if (scaled.fadeIn > 0 && t < scaled.fadeIn) gain = t / scaled.fadeIn;
    const foStart = Math.max(0, bedS - scaled.fadeOut);
    if (scaled.fadeOut > 0 && t > foStart) {
      gain = Math.min(gain, Math.max(0, (bedS - t) / scaled.fadeOut));
    }
    return Math.max(0, Math.min(1, gain));
  }

  function pauseMusicElement(el) {
    if (!el) return;
    try {
      el.pause();
    } catch (_) {
      /* ignore */
    }
  }

  function pauseMusicAudio() {
    pauseMusicElement(musicAudio);
    pauseMusicElement(musicAudioNext);
  }

  function ensureMusicSrc(el, url) {
    if (!el || !url) return false;
    if (el.getAttribute("src") !== url) {
      pauseMusicElement(el);
      el.removeAttribute("src");
      el.src = url;
      el.load();
    }
    return true;
  }

  function syncMusicAudio() {
    const hit = playlistHit(state.projectTimeS);
    if (!hit || !hit.track.streamUrl) {
      pauseMusicAudio();
      return;
    }
    const active = hit.index % 2 === 0 ? musicAudio : musicAudioNext;
    const idle = hit.index % 2 === 0 ? musicAudioNext : musicAudio;
    if (!active) {
      pauseMusicAudio();
      return;
    }
    ensureMusicSrc(active, hit.track.streamUrl);
    const nextTrack = !musicLoopEnabled() ? state.tracks[hit.index + 1] : null;
    if (idle && nextTrack && nextTrack.available && nextTrack.streamUrl) {
      ensureMusicSrc(idle, nextTrack.streamUrl);
    }
    const localT = state.projectTimeS - hit.startS;
    const gain = musicFadeGain(localT, hit.spanS, hit.track.fadeIn, hit.track.fadeOut);
    active.volume = Math.max(0, Math.min(1, state.volume * hit.track.volume * gain));
    const playPos = hit.offset;
    pauseMusicElement(idle);
    const seekIfNeeded = (el) => {
      if (!el || !Number.isFinite(playPos)) return;
      try {
        if (Math.abs((el.currentTime || 0) - playPos) > 0.35) {
          el.currentTime = playPos;
        }
      } catch (_) {
        /* ignore */
      }
    };
    if (!state.playing) {
      pauseMusicElement(active);
      seekIfNeeded(active);
      return;
    }
    seekIfNeeded(active);
    const playPromise = active.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch(() => {
        /* autoplay / decode */
      });
    }
  }

  let titleSaveTimer = 0;
  async function persistProjectTitle() {
    if (!projectId || !titleInput) return;
    const title = titleInput.value.trim();
    if (!title) {
      showFlash(msgTitleFailed);
      return;
    }
    try {
      const res = await fetch(`/api/studio/projects/${projectId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ title }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        showFlash((data && data.detail) || msgTitleFailed);
        setSaveState(false);
        return;
      }
      state.title = data.title;
      titleInput.value = data.title;
      setSaveState(true);
    } catch (_) {
      showFlash(msgTitleFailed);
      setSaveState(false);
    }
  }

  function scheduleTitleSave() {
    if (titleSaveTimer) window.clearTimeout(titleSaveTimer);
    setSaveState(false);
    titleSaveTimer = window.setTimeout(() => {
      titleSaveTimer = 0;
      persistProjectTitle();
    }, 400);
  }

  flushPendingTitleSave = () => {
    if (!titleSaveTimer) return;
    window.clearTimeout(titleSaveTimer);
    titleSaveTimer = 0;
    persistProjectTitle();
  };
  document.addEventListener("click", (event) => {
    const raw = event.target;
    const link = raw && raw.closest ? raw.closest("a[href]") : null;
    if (!link || !titleSaveTimer) return;
    let path = "";
    try {
      path = new URL(link.href, window.location.href).pathname;
    } catch (_) {
      return;
    }
    if (path !== "/studio/projects") return;
    event.preventDefault();
    const href = link.href;
    window.clearTimeout(titleSaveTimer);
    titleSaveTimer = 0;
    Promise.resolve(persistProjectTitle()).finally(() => {
      window.location.assign(href);
    });
  });

  function applyTransitionsToDom() {
    grid.querySelectorAll(".studio-transition").forEach((el) => {
      const afterId = el.dataset.transitionAfter;
      const prev = clips().find((c) => String(c.dataset.studioId) === String(afterId));
      const type = (prev && prev.dataset.appliedType) || el.dataset.appliedType || "cut";
      el.dataset.transitionType = type;
      refreshTransitionChrome(el);
    });
  }

  function transitionOccupancyS(type, duration) {
    const seconds = Number(duration) || 0;
    if (type === "fade_black") return Math.max(0, seconds / 2);
    if (type === "crossfade") return Math.max(0, seconds);
    return 0;
  }

  function refreshAppliedTransitions() {
    const list = clips().filter((c) => clipDuration(c) > 0);
    for (let i = 0; i < list.length - 1; i += 1) {
      const prev = list[i];
      const next = list[i + 1];
      const stored = prev.dataset.transitionType || "cut";
      let applied = stored;
      let duration = Number(prev.dataset.transitionDuration) || 0.5;
      const maxD = Math.min(clipDuration(prev), clipDuration(next)) - 0.1;
      if (stored !== "cut" && maxD < 0.1) {
        applied = "cut";
        duration = 0;
      } else if (stored !== "cut") {
        duration = Math.max(0.1, Math.min(2, duration));
        if (duration > maxD) duration = maxD;
      } else {
        duration = 0;
      }
      prev.dataset.appliedType = applied;
      prev.dataset.appliedDuration = String(applied === "cut" ? 0 : duration);
    }
    for (let i = 0; i < list.length; i += 1) {
      const incoming = i > 0 ? list[i - 1] : null;
      const outgoing = i < list.length - 1 ? list[i] : null;
      const occIn = incoming
        ? transitionOccupancyS(incoming.dataset.appliedType, incoming.dataset.appliedDuration)
        : 0;
      let occOut = outgoing
        ? transitionOccupancyS(outgoing.dataset.appliedType, outgoing.dataset.appliedDuration)
        : 0;
      const budget = clipDuration(list[i]) - 0.1;
      if (occIn + occOut <= budget + 1e-9) continue;
      if (outgoing && (outgoing.dataset.appliedType || "cut") !== "cut") {
        outgoing.dataset.appliedType = "cut";
        outgoing.dataset.appliedDuration = "0";
        occOut = 0;
      }
      if (occIn + occOut <= budget + 1e-9) continue;
      if (incoming && (incoming.dataset.appliedType || "cut") !== "cut") {
        incoming.dataset.appliedType = "cut";
        incoming.dataset.appliedDuration = "0";
      }
    }
    rebuildTransitions();
    applyTransitionsToDom();
  }

  function rebuildTransitions() {
    const list = clips();
    grid.querySelectorAll(".studio-transition").forEach((el) => el.remove());
    for (let i = 1; i < list.length; i += 1) {
      const prev = list[i - 1];
      const next = list[i];
      const li = document.createElement("li");
      li.className = "studio-transition";
      li.dataset.transitionAfter = prev.dataset.studioId || "";
      li.dataset.transitionBefore = next.dataset.studioId || "";
      const type = prev.dataset.appliedType || prev.dataset.transitionType || "cut";
      li.dataset.transitionType = type;
      li.dataset.storedType = prev.dataset.transitionType || "cut";
      li.dataset.storedDuration = prev.dataset.transitionDuration || "";
      li.dataset.appliedType = type;
      li.dataset.appliedDuration = prev.dataset.appliedDuration || "0";
      li.dataset.fallbackCut = prev.dataset.fallbackCut || "0";
      li.tabIndex = 0;
      li.setAttribute("role", "button");
      const chip = document.createElement("span");
      chip.className = "studio-transition-chip";
      chip.dataset.transitionLabel = "";
      li.appendChild(chip);
      const span = document.createElement("span");
      span.className = "studio-transition-span";
      span.dataset.transitionSpan = "";
      span.hidden = true;
      li.appendChild(span);
      refreshTransitionChrome(li);
      grid.insertBefore(li, next);
    }
  }

  function buildRuler() {
    if (!rulerEl) return;
    const total = totalDuration();
    rulerEl.innerHTML = "";
    if (total <= 0) return;
    const pps = timelinePxPerSecond();
    let major = 30;
    let minor = 0;
    if (pps >= 640) {
      major = 1;
      minor = 1 / TIMELINE_EXPORT_FPS;
    } else if (pps >= 320) {
      major = 1;
      minor = 0.2;
    } else if (pps >= 80) {
      major = 1;
    } else if (pps >= 40) {
      major = 5;
    } else if (pps >= 20) {
      major = 10;
    }
    const pushMark = (s, kind, label) => {
      const mark = document.createElement("span");
      mark.className =
        kind === "minor" ? "studio-ruler-mark is-minor" : "studio-ruler-mark";
      mark.style.left = `${timeToX(s)}px`;
      if (label) mark.textContent = label;
      rulerEl.appendChild(mark);
    };
    for (let s = 0; s <= total + 0.0001; s += major) {
      pushMark(s, "major", formatTime(s).replace(/^00:/, ""));
      if (minor > 0) {
        for (let m = s + minor; m < s + major - minor / 2 && m <= total + 0.0001; m += minor) {
          const nearMajor = Math.abs(m - Math.round(m / major) * major) < minor / 2;
          if (nearMajor) continue;
          pushMark(m, "minor", "");
        }
      }
    }
  }

  function showInspector(kind) {
    ["inspector-empty", "inspector-clip", "inspector-transition", "inspector-music", "inspector-titlecard"].forEach(
      (id) => {
        const el = document.getElementById(id);
        if (el) el.hidden = id !== kind;
      }
    );
    if (kind === "inspector-empty") fillEmptyInspector();
  }

  function setClipRemoveAction(form, studioId) {
    if (!form || studioId == null || studioId === "") return;
    const url = `/studio/${studioId}/remove`;
    form.setAttribute("action", url);
    form.querySelectorAll('button[type="submit"]').forEach((btn) => {
      btn.setAttribute("formaction", url);
    });
  }

  function fillTitlecardInspector(clip) {
    const titleEl = document.getElementById("inspector-titlecard-title");
    const subEl = document.getElementById("inspector-titlecard-subtitle");
    const durEl = document.getElementById("inspector-titlecard-duration");
    const removeForm = document.getElementById("inspector-titlecard-remove-form");
    if (titleEl) titleEl.value = clip.dataset.title || "";
    if (subEl) subEl.value = clip.dataset.subtitle || "";
    if (durEl) durEl.value = String(clipDuration(clip).toFixed(1));
    const bg = clip.dataset.background || "dark";
    document.querySelectorAll('input[name="inspector-titlecard-bg"]').forEach((el) => {
      el.checked = el.value === bg;
    });
    setClipRemoveAction(removeForm, clip.dataset.studioId);
  }

  function selectClip(id, { movePlayhead = true, seekTimeS = null } = {}) {
    if (reuseDraft) {
      const draftClipId = reuseDraft.clip && reuseDraft.clip.dataset.studioId;
      if (draftClipId == null || String(draftClipId) !== String(id)) cancelReuseDraft();
      else return;
    }
    state.selected = { type: "clip", id: String(id) };
    const clip = clips().find((c) => String(c.dataset.studioId) === String(id));
    if (!clip) {
      updateRemoveEnabled();
      return;
    }
    clips().forEach((c) => {
      c.classList.toggle("is-selected", c === clip);
      if (c === clip) c.setAttribute("aria-selected", "true");
      else c.removeAttribute("aria-selected");
    });
    grid.querySelectorAll(".studio-transition").forEach((el) => el.classList.remove("is-selected"));
    layoutMusicSpans();

    if (clip.dataset.kind === "title_card") {
      showInspector("inspector-titlecard");
      setInspectorHeading(kindLabels.title_card);
      fillTitlecardInspector(clip);
    } else {
      showInspector("inspector-clip");
      setInspectorHeading(kindLabels[clip.dataset.kind] || kindLabels.unknown);
      const panel = document.getElementById("inspector-clip");
      if (!panel) return;
      panel.querySelector('[data-field="kind"]').textContent =
        kindLabels[clip.dataset.kind] || kindLabels.unknown;
      panel.querySelector('[data-field="filename"]').textContent = clip.dataset.filename || "";
      panel.querySelector('[data-field="recorded"]').textContent = clip.dataset.recordedAt || "—";
      const dur = clipDuration(clip);
      const durationLine = panel.querySelector('[data-field="duration-line"]');
      if (durationLine) {
        durationLine.textContent =
          dur > 0 ? `${labelInStory}: ${dur.toFixed(1)} s` : "—";
      }

      const photoWrap = document.getElementById("inspector-photo-duration-wrap");
      const photoInput = document.getElementById("inspector-photo-duration");
      const photoReset = document.getElementById("inspector-photo-reset");
      const videoTiming = document.getElementById("inspector-video-timing");
      const removeForm = document.getElementById("inspector-remove-form");
      const isPhoto = clip.dataset.kind === "photo";
      const isVideo = clip.dataset.kind === "video";
      if (photoWrap) photoWrap.hidden = !isPhoto;
      if (photoReset) {
        photoReset.hidden = !isPhoto;
        photoReset.disabled = clip.dataset.photoDuration === "";
      }
      if (photoInput && isPhoto) {
        const shown =
          clip.dataset.photoDuration === ""
            ? defaultPhotoDuration
            : Number(clip.dataset.photoDuration);
        photoInput.value = Number(shown).toFixed(1);
      }
      if (videoTiming) {
        videoTiming.hidden = !isVideo;
        if (isVideo) {
          const inEl = document.getElementById("inspector-source-in");
          const outEl = document.getElementById("inspector-source-out");
          const repeatEl = document.getElementById("inspector-section-repeats");
          const hintEl = panel.querySelector('[data-field="cut-hint"]');
          if (inEl && document.activeElement !== inEl) inEl.value = sourceInS(clip).toFixed(2);
          if (outEl && document.activeElement !== outEl) outEl.value = sourceOutS(clip).toFixed(2);
          if (repeatEl && document.activeElement !== repeatEl) {
            repeatEl.value = String(
              forwardLoopActive(clip) ? Number(clip.dataset.sectionRepeats) || 1 : sectionRepeats(clip)
            );
          }
          fillForwardLoop(clip);
          if (hintEl) hintEl.textContent = msgCutHint;
        }
      }
      fillSpeedInspector(clip, isVideo);
      const canImage = isPhoto || isVideo;
      const imagePanel = document.getElementById("inspector-image-panel");
      if (imagePanel) imagePanel.hidden = !canImage;
      if (canImage) {
        fillImageAdjust(clip);
        fillImageInspectorSections(clip, isVideo);
      }
      if (isVideo) fillSaturationRamp(clip);
      const overlayWrap = document.getElementById("inspector-overlays");
      if (overlayWrap) overlayWrap.hidden = !(isPhoto || isVideo);
      if (isPhoto || isVideo) fillOverlayInspector(clip);
      else selectedOverlayId = null;
      fillMaskInspector(clip);
      const frameWrap = document.getElementById("inspector-frame");
      if (frameWrap) frameWrap.hidden = !canImage;
      if (canImage) {
        frameMotionArmed = frameMotionOn(readFrame(clip));
        frameEditTarget = "start";
        fillFrame(clip);
      }
      const mapWrap = document.getElementById("inspector-map");
      if (mapWrap) mapWrap.hidden = !(isPhoto || isVideo);
      if (isPhoto || isVideo) fillMapInspector(clip);
      const hudWrap = document.getElementById("inspector-hud");
      if (hudWrap) hudWrap.hidden = !isVideo;
      if (isVideo) fillHud(clip);
      setClipRemoveAction(removeForm, clip.dataset.studioId);
      let storedTab = "clip";
      try {
        storedTab = sessionStorage.getItem("orga-drone.studio.inspectorTab") || "clip";
      } catch (_) {
        storedTab = "clip";
      }
      setInspectorTab(storedTab);
      refreshInspectorTabMarks(clip);
    }

    if (movePlayhead && !playheadTouchesClip(clip)) {
      const start = clipStartTime(clip);
      const end = start + clipDuration(clip);
      let t = seekTimeS != null && Number.isFinite(seekTimeS) ? seekTimeS : start;
      if (end > start) t = Math.max(start, Math.min(end - 0.001, t));
      else t = start;
      const wasPlaying = state.playing;
      if (wasPlaying) pausePlayback();
      setProjectTime(t);
      if (wasPlaying) startPlayback();
    } else {
      // Keep selection from stealing the playhead, but still sync preview/active chrome.
      syncPreviewMedia({ seek: true });
    }
    scheduleLutProxyPrepare(clip);
    updateRemoveEnabled();
  }

  function fillSpeedInspector(clip, isVideo) {
    const wrap = document.getElementById("inspector-speed");
    if (wrap) wrap.hidden = !isVideo;
    if (!isVideo || !clip) return;
    const speed = playbackSpeed(clip);
    wrap.querySelectorAll("[data-speed]").forEach((btn) => {
      btn.classList.toggle("is-active", Number(btn.dataset.speed) === speed);
      btn.disabled = clip.dataset.available !== "1";
    });
    const inEl = document.getElementById("inspector-speed-in");
    const outEl = document.getElementById("inspector-speed-out");
    const sourceDur = sourceDurationS(clip);
    const shownOut = Math.floor(sourceDur * 1000) / 1000;
    if (inEl) {
      inEl.value = "0";
      inEl.disabled = clip.dataset.available !== "1";
    }
    if (outEl) {
      outEl.value = String(shownOut);
      outEl.disabled = clip.dataset.available !== "1";
    }
  }

  let speedApplyPending = false;

  async function applyClipSpeed(speed) {
    if (reuseDraft) return;
    if (speedApplyPending) return;
    const selected = clips().find(
      (c) => state.selected && String(c.dataset.studioId) === String(state.selected.id)
    );
    if (!selected || selected.dataset.kind !== "video") return;
    if (speed === playbackSpeed(selected)) return;
    const inEl = document.getElementById("inspector-speed-in");
    const outEl = document.getElementById("inspector-speed-out");
    const rangeIn = inEl ? Number(inEl.value) : 0;
    const rangeOut = outEl ? Number(outEl.value) : sourceDurationS(selected);
    if (!Number.isFinite(rangeIn) || !Number.isFinite(rangeOut)) {
      showFlash(msgSpeedFailed);
      return;
    }
    speedApplyPending = true;
    if (state.playing) pausePlayback();
    try {
      const res = await fetch(`/api/studio/${selected.dataset.studioId}/speed`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          speed,
          range_in_s: rangeIn,
          range_out_s: rangeOut,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        showFlash((data && data.detail) || msgSpeedFailed);
        speedApplyPending = false;
        return;
      }
      try {
        sessionStorage.setItem(
          CUT_RESTORE_KEY,
          JSON.stringify({
            selectId: String(data.selected_id),
            atClipStart: true,
          })
        );
      } catch (_) {
        /* ignore */
      }
      window.location.reload();
    } catch (_) {
      showFlash(msgSpeedFailed);
      speedApplyPending = false;
    }
  }

  function canCutAtHit(hit) {
    if (!hit || hit.atEnd) return false;
    if (!state.selected || state.selected.type !== "clip") return false;
    if (String(state.selected.id) !== String(hit.clip.dataset.studioId)) return false;
    if (hit.clip.dataset.kind !== "video") return false;
    if (sectionRepeats(hit.clip) > 1) return false;
    if (hit.clip.dataset.canPlay !== "1") return false;
    if (hit.clip.dataset.available !== "1") return false;
    const sourceLocal = hit.localS * playbackSpeed(hit.clip);
    const sourceDur = sourceDurationS(hit.clip);
    return sourceLocal > MIN_CUT_SEGMENT_S && sourceLocal < sourceDur - MIN_CUT_SEGMENT_S;
  }

  function updateCutEnabled() {
    if (!cutBtn) return;
    const hit = resolveAt(state.projectTimeS);
    const ok = canCutAtHit(hit);
    cutBtn.disabled = !ok;
  }

  const removeBtn = document.getElementById("studio-remove");

  function selectedStoryClip() {
    if (!state.selected || state.selected.type !== "clip") return null;
    return (
      clips().find((item) => String(item.dataset.studioId) === String(state.selected.id)) || null
    );
  }

  function updateRemoveEnabled() {
    if (!removeBtn) return;
    removeBtn.disabled = !selectedStoryClip();
  }

  let clipMenuReturnFocus = null;

  function hideClipMenu() {
    const menu = document.getElementById("studio-clip-menu");
    const restore = clipMenuReturnFocus;
    clipMenuReturnFocus = null;
    if (!menu || menu.hidden) return;
    const focusInside = Boolean(menu.contains(document.activeElement));
    menu.hidden = true;
    if (focusInside && restore && restore.isConnected && typeof restore.focus === "function") {
      restore.focus();
    }
  }

  function showClipMenu(x, y, returnTarget) {
    const menu = document.getElementById("studio-clip-menu");
    if (!menu) return;
    const active = document.activeElement;
    if (!active || !menu.contains(active)) {
      if (
        active &&
        active !== document.body &&
        active !== document.documentElement &&
        typeof active.focus === "function"
      ) {
        clipMenuReturnFocus = active;
      } else if (returnTarget && typeof returnTarget.focus === "function") {
        clipMenuReturnFocus = returnTarget;
      } else {
        clipMenuReturnFocus = null;
      }
    }
    menu.hidden = false;
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    const rect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
    const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
    const item = visibleClipMenuItems(menu)[0];
    if (item) item.focus();
  }

  function visibleClipMenuItems(menu) {
    return Array.from(menu.querySelectorAll("[role='menuitem']")).filter((entry) => !entry.hidden);
  }

  function setClipMenuReason(text) {
    const reason = document.getElementById("studio-clip-menu-reason");
    if (!reason) return;
    const show = Boolean(text);
    reason.hidden = !show;
    reason.textContent = text || "";
  }

  function mergeItemBlocked(button) {
    return !button || button.getAttribute("aria-disabled") === "true";
  }

  async function refreshMergeItem(button, studioId) {
    if (!button) return;
    button.setAttribute("aria-disabled", "true");
    button.removeAttribute("title");
    setClipMenuReason("");
    if (!studioId) return;
    try {
      const res = await fetch(`/api/studio/${studioId}/merge-previous`, {
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => null);
      const menu = document.getElementById("studio-clip-menu");
      if (!menu || menu.hidden || button.dataset.studioId !== String(studioId)) return;
      const ok = Boolean(data && data.ok);
      button.setAttribute("aria-disabled", ok ? "false" : "true");
      const reason = (data && data.reason) || "";
      if (!ok) {
        const text =
          reason ||
          root.dataset.mergeCheckFailed ||
          "Could not check whether these clips can be joined.";
        button.title = text;
        setClipMenuReason(text);
      }
      reuseReasonWins();
    } catch (_) {
      const menu = document.getElementById("studio-clip-menu");
      if (!menu || menu.hidden) return;
      const fallback =
        root.dataset.mergeCheckFailed || "Could not check whether these clips can be joined.";
      button.setAttribute("aria-disabled", "true");
      button.title = fallback;
      setClipMenuReason(fallback);
      reuseReasonWins();
    }
  }

  async function mergeWithPrevious(studioId) {
    if (!studioId) return;
    hideClipMenu();
    if (state.playing) pausePlayback();
    try {
      const res = await fetch(`/api/studio/${studioId}/merge-previous`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        showFlash((data && data.detail) || root.dataset.mergeFailed || "Could not remove the cut.");
        return;
      }
      window.location.reload();
    } catch (_) {
      showFlash(root.dataset.mergeFailed || "Could not remove the cut.");
    }
  }

  function storyClipDeleteContext(node) {
    if (document.querySelector("dialog[open]")) return false;
    if (!node || typeof node.closest !== "function") return false;
    if (node.closest("dialog")) return false;
    return Boolean(node.closest("#studio-grid, #studio-playhead"));
  }

  function removeSelectedStoryClip() {
    if (reuseDraft) return;
    const clip = selectedStoryClip();
    if (!clip) return;
    hideClipMenu();
    const form = document.getElementById("inspector-remove-form");
    if (!form) return;
    setClipRemoveAction(form, clip.dataset.studioId);
    if (state.playing) pausePlayback();
    form.requestSubmit();
  }

  async function cutSelectedAtPlayhead() {
    if (reuseDraft) return;
    const hit = resolveAt(state.projectTimeS);
    if (!canCutAtHit(hit)) return;
    const studioId = hit.clip.dataset.studioId;
    const localS = hit.localS * playbackSpeed(hit.clip);
    const playhead = state.projectTimeS;
    if (state.playing) pausePlayback();
    cutBtn.disabled = true;
    try {
      const res = await fetch(`/api/studio/${studioId}/cut`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ local_s: localS }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        showFlash((data && data.detail) || cutFailedMsg);
        updateCutEnabled();
        return;
      }
      try {
        sessionStorage.setItem(
          CUT_RESTORE_KEY,
          JSON.stringify({
            projectTimeS: playhead,
            selectId: String(data.right_id),
          })
        );
      } catch (_) {
        /* ignore */
      }
      window.location.reload();
    } catch (_) {
      showFlash(cutFailedMsg);
      updateCutEnabled();
    }
  }

  function selectTransition(el) {
    if (reuseDraft) cancelReuseDraft();
    state.selected = { type: "transition", id: el.dataset.transitionAfter || "" };
    clips().forEach((c) => {
      c.classList.remove("is-selected");
      c.removeAttribute("aria-selected");
    });
    grid.querySelectorAll(".studio-transition").forEach((t) => t.classList.toggle("is-selected", t === el));
    layoutMusicSpans();
    showInspector("inspector-transition");
    const headingType = transitionLabels[el.dataset.transitionType || "cut"] || "Transition";
    setInspectorHeading(headingType);
    const betweenEl = document.getElementById("inspector-transition-between");
    if (betweenEl) {
      const { after, before } = transitionNeighbors(el);
      betweenEl.textContent = formatTemplate(msgBetween, {
        a: clipDisplayName(after),
        b: clipDisplayName(before),
      });
    }
    const select = document.getElementById("inspector-transition-type");
    const stored = el.dataset.storedType || el.dataset.transitionType || "cut";
    if (select) select.value = stored === "cut" || stored === "fade_black" || stored === "crossfade" ? stored : "cut";
    const durWrap = document.getElementById("inspector-transition-duration-wrap");
    const durInput = document.getElementById("inspector-transition-duration");
    const isCut = (select ? select.value : stored) === "cut";
    if (durWrap) durWrap.hidden = isCut;
    if (durInput) {
      const raw = el.dataset.storedDuration;
      durInput.value = raw ? Number(raw).toFixed(1) : "0.5";
    }
    const hint = document.getElementById("inspector-transition-hint");
    if (hint) {
      if (el.dataset.fallbackCut === "1") {
        hint.hidden = false;
        hint.textContent = msgTransitionFallback;
      } else if (el.dataset.clamped === "1") {
        hint.hidden = false;
        hint.textContent = msgTransitionClamped;
      } else if (!isCut) {
        const { after, before } = transitionNeighbors(el);
        const maxD =
          after && before
            ? Math.min(clipDuration(after), clipDuration(before)) - 0.1
            : 0;
        if (!Number.isFinite(maxD) || maxD < 0.1) {
          hint.hidden = false;
          hint.textContent = msgTransitionNoRoom;
        } else {
          hint.hidden = false;
          hint.textContent = formatTemplate(msgTransitionLimit, {
            max: Math.max(0.1, Math.min(2, maxD)).toFixed(1),
          });
        }
        if (durInput) {
          durInput.max = String(Math.max(0.1, Math.min(2, maxD)));
        }
      } else {
        hint.hidden = true;
        hint.textContent = "";
      }
    }
    updateCutEnabled();
    updateRemoveEnabled();
  }

  function musicErrorDetail(body) {
    const detail = body && body.detail;
    if (detail === "music_limit") return msgMusicLimit;
    if (typeof detail === "string" && detail) return detail;
    return msgMusicFailed;
  }

  function selectMusic(trackId) {
    if (reuseDraft) cancelReuseDraft();
    const track = state.tracks.find((item) => String(item.id) === String(trackId));
    if (!track) return;
    state.selected = { type: "music", id: String(track.id) };
    updateRemoveEnabled();
    clips().forEach((c) => {
      c.classList.remove("is-selected");
      c.removeAttribute("aria-selected");
    });
    grid.querySelectorAll(".studio-transition").forEach((t) => t.classList.remove("is-selected"));
    showInspector("inspector-music");
    setInspectorHeading(labelInspectorMusic);
    layoutMusicSpans();
    const panel = document.getElementById("inspector-music");
    if (!panel) return;
    const nameEl = panel.querySelector('[data-field="music-name"]');
    if (nameEl) nameEl.textContent = track.name;
    const indexEl = document.getElementById("inspector-music-index");
    const index = state.tracks.findIndex((item) => item.id === track.id);
    if (indexEl) {
      indexEl.hidden = false;
      indexEl.textContent = msgMusicSongOf
        .replace("{current}", String(index + 1))
        .replace("{total}", String(state.tracks.length));
    }
    const vol = document.getElementById("inspector-music-volume");
    const fadeIn = document.getElementById("inspector-music-fade-in");
    const fadeOut = document.getElementById("inspector-music-fade-out");
    const start = document.getElementById("inspector-music-start");
    const loopEl = document.getElementById("inspector-music-loop");
    const loopWrap = document.getElementById("inspector-music-loop-wrap");
    if (vol) vol.value = String(Math.round(track.volume * 100));
    if (fadeIn) fadeIn.value = String(track.fadeIn);
    if (fadeOut) fadeOut.value = String(track.fadeOut);
    if (start) {
      const storyS = Math.max(0, totalDuration());
      start.value = String(Number(Math.min(storyS, state.musicStartS).toFixed(3)));
      start.max = String(storyS);
    }
    if (loopWrap) loopWrap.hidden = state.tracks.length !== 1;
    if (loopEl) loopEl.checked = !!track.loop && state.tracks.length === 1;
    const upBtn = document.getElementById("inspector-music-move-up");
    const downBtn = document.getElementById("inspector-music-move-down");
    if (upBtn) upBtn.disabled = index <= 0;
    if (downBtn) downBtn.disabled = index < 0 || index >= state.tracks.length - 1;
  }

  function renderMusic() {
    if (state.selected.type === "music" && !selectedMusicTrack()) {
      state.selected = { type: null, id: null };
      updateRemoveEnabled();
      showInspector("inspector-empty");
      document.getElementById("studio-music-track")?.classList.remove("is-selected");
    }
    syncMusicAudio();
    layoutTimeline();
    if (state.selected.type === "music") selectMusic(state.selected.id);
  }

  async function pickMusicPath() {
    const picked = await fetch("/api/desktop/pick-open-file", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({}),
    });
    const pickedBody = await picked.json().catch(() => null);
    if (picked.status === 503) {
      showFlash(msgMusicPickerUnavailable);
      return null;
    }
    if (!picked.ok || !pickedBody || pickedBody.status === "cancelled") return null;
    if (pickedBody.status !== "ok" || !pickedBody.path) {
      showFlash(msgMusicFailed);
      return null;
    }
    return pickedBody.path;
  }

  async function addMusicTrack() {
    if (!projectId) return;
    if (state.tracks.length >= MUSIC_MAX_TRACKS) {
      showFlash(msgMusicLimit);
      return;
    }
    try {
      const path = await pickMusicPath();
      if (!path) return;
      setSaveState(false);
      const saved = await fetch(`/api/studio/projects/${projectId}/music`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ path }),
      });
      const savedBody = await saved.json().catch(() => null);
      if (!saved.ok || !savedBody || !savedBody.ok) {
        showFlash(musicErrorDetail(savedBody));
        return;
      }
      applyTracksPayload(savedBody);
      if (reloadIfForwardLoop()) return;
      const last = state.tracks[state.tracks.length - 1];
      renderMusic();
      if (last) selectMusic(last.id);
      setSaveState(true);
      showFlash("");
    } catch (_) {
      showFlash(msgMusicFailed);
    }
  }

  async function replaceSelectedMusic() {
    if (!projectId) return;
    const track = selectedMusicTrack();
    if (!track) return;
    try {
      const path = await pickMusicPath();
      if (!path) return;
      setSaveState(false);
      const saved = await fetch(
        `/api/studio/projects/${projectId}/music/${track.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ path }),
        }
      );
      const savedBody = await saved.json().catch(() => null);
      if (!saved.ok || !savedBody || !savedBody.ok) {
        showFlash(musicErrorDetail(savedBody));
        return;
      }
      applyTracksPayload(savedBody);
      if (reloadIfForwardLoop()) return;
      renderMusic();
      selectMusic(track.id);
      setSaveState(true);
      showFlash("");
    } catch (_) {
      showFlash(msgMusicFailed);
    }
  }

  async function patchMusicSettings() {
    const track = selectedMusicTrack();
    if (!projectId || !track) return;
    setSaveState(false);
    const payload = {
      volume: track.volume,
      fade_in_s: track.fadeIn,
      fade_out_s: track.fadeOut,
    };
    if (state.tracks.length === 1) payload.loop = !!track.loop;
    try {
      const res = await fetch(`/api/studio/projects/${projectId}/music/${track.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        showFlash(musicErrorDetail(data));
        return;
      }
      applyTracksPayload(data);
      renderMusic();
      selectMusic(track.id);
      setSaveState(true);
    } catch (_) {
      showFlash(msgMusicFailed);
    }
  }

  async function persistMusicStart(previousStartS) {
    if (!projectId) return;
    const requested = Math.max(0, Math.min(totalDuration(), state.musicStartS));
    state.musicStartS = requested;
    setSaveState(false);
    try {
      const res = await fetch(`/api/studio/projects/${projectId}/music-start`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ start_s: requested }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        state.musicStartS = previousStartS;
        layoutTimeline();
        showFlash(musicErrorDetail(data));
        return;
      }
      state.musicStartS = Math.max(0, Number(data.music_start_s) || 0);
      renderMusic();
      setSaveState(true);
      showFlash("");
    } catch (_) {
      state.musicStartS = previousStartS;
      layoutTimeline();
      showFlash(msgMusicFailed);
    }
  }

  function beginMusicStartDrag(event, handle) {
    if (event.button != null && event.button !== 0) return;
    const first = musicClipEls()[0];
    if (!first || !first.contains(handle)) return;
    event.preventDefault();
    event.stopPropagation();
    const pointerId = event.pointerId;
    const originX = event.clientX;
    const storedStartS = state.musicStartS;
    const originStartS = Math.max(0, Math.min(totalDuration(), storedStartS));
    state.musicStartS = originStartS;
    const pps = timelinePxPerSecond() || 1;
    handle.setPointerCapture?.(pointerId);
    handle.classList.add("is-dragging");
    const move = (ev) => {
      if (ev.pointerId !== pointerId) return;
      const next = originStartS + (ev.clientX - originX) / pps;
      state.musicStartS = Math.max(0, Math.min(totalDuration(), next));
      layoutMusicSpans();
      syncMusicAudio();
      const input = document.getElementById("inspector-music-start");
      if (input) input.value = String(Number(state.musicStartS.toFixed(2)));
    };
    const finish = (commit) => {
      handle.classList.remove("is-dragging");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", cancel);
      if (commit && Math.abs(state.musicStartS - originStartS) >= 0.001) {
        persistMusicStart(storedStartS);
      } else {
        state.musicStartS = storedStartS;
        layoutMusicSpans();
      }
    };
    const up = (ev) => {
      if (ev.pointerId === pointerId) finish(true);
    };
    const cancel = (ev) => {
      if (ev.pointerId === pointerId) finish(false);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", cancel);
  }

  async function clearMusic() {
    const track = selectedMusicTrack();
    if (!projectId) {
      state.tracks = [];
      renderMusic();
      showInspector("inspector-empty");
      document.getElementById("studio-music-track")?.classList.remove("is-selected");
      return;
    }
    if (!track) return;
    setSaveState(false);
    try {
      const res = await fetch(`/api/studio/projects/${projectId}/music/${track.id}`, {
        method: "DELETE",
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        showFlash(musicErrorDetail(data));
        return;
      }
      applyTracksPayload(data);
      if (reloadIfForwardLoop()) return;
      state.selected = { type: null, id: null };
      updateRemoveEnabled();
      renderMusic();
      showInspector("inspector-empty");
      document.getElementById("studio-music-track")?.classList.remove("is-selected");
      setSaveState(true);
      showFlash("");
    } catch (_) {
      showFlash(msgMusicFailed);
    }
  }

  async function moveSelectedMusic(delta) {
    const track = selectedMusicTrack();
    if (!projectId || !track) return;
    const ids = state.tracks.map((item) => item.id);
    const index = ids.indexOf(track.id);
    const next = index + delta;
    if (index < 0 || next < 0 || next >= ids.length) return;
    const swapped = ids.slice();
    const tmp = swapped[index];
    swapped[index] = swapped[next];
    swapped[next] = tmp;
    setSaveState(false);
    try {
      const res = await fetch(`/api/studio/projects/${projectId}/music/reorder`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ ids: swapped }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        showFlash(musicErrorDetail(data));
        return;
      }
      applyTracksPayload(data);
      renderMusic();
      selectMusic(track.id);
      setSaveState(true);
    } catch (_) {
      showFlash(msgMusicFailed);
    }
  }

  async function persistMusicOrder() {
    if (!projectId) return;
    const ids = musicClipEls().map((el) => Number(el.dataset.musicId));
    const previous = musicDragOrderBefore;
    musicDragOrderBefore = null;
    if (!previous || previous.join(",") === ids.join(",")) {
      layoutTimeline();
      return;
    }
    setSaveState(false);
    try {
      const res = await fetch(`/api/studio/projects/${projectId}/music/reorder`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ ids }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        if (previous) {
          const byId = new Map(state.tracks.map((track) => [track.id, track]));
          state.tracks = previous.map((id) => byId.get(id)).filter(Boolean);
        }
        showFlash(musicErrorDetail(data));
        layoutTimeline();
        return;
      }
      applyTracksPayload(data);
      renderMusic();
      setSaveState(true);
    } catch (_) {
      showFlash(msgMusicFailed);
    }
  }

  async function persistOrder() {
    const ids = orderedIds();
    const previous = dragOrderBefore;
    setSaveState(false);
    try {
      const res = await fetch("/api/studio/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ ordered_ids: ids }),
      });
      if (!res.ok) throw new Error("reorder failed");
      await res.json();
      if (reloadIfForwardLoop()) return;
      refreshAppliedTransitions();
      layoutTimeline();
      setProjectTime(state.projectTimeS);
      setSaveState(true);
      showFlash("");
      dragOrderBefore = null;
    } catch (_) {
      if (previous) restoreOrder(previous);
      showFlash(msgReorderFailed);
    }
  }

  function restoreOrder(ids) {
    const byId = new Map(clips().map((c) => [Number(c.dataset.studioId), c]));
    grid.querySelectorAll(".studio-transition").forEach((el) => el.remove());
    ids.forEach((id) => {
      const el = byId.get(id);
      if (el) grid.appendChild(el);
    });
    refreshAppliedTransitions();
    layoutTimeline();
  }

  async function patchPhotoDuration(clip, durationS) {
    const id = clip.dataset.studioId;
    const prev = clip.dataset.photoDuration;
    setSaveState(false);
    try {
      const res = await fetch(`/api/studio/${id}/photo-duration`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ duration_s: durationS }),
      });
      if (!res.ok) throw new Error("duration failed");
      const data = await res.json();
      clip.dataset.photoDuration =
        data.photo_duration_s == null ? "" : String(data.photo_duration_s);
      clip.dataset.effectiveDuration =
        data.effective_duration_s == null ? "" : String(data.effective_duration_s);
      const flex =
        data.effective_duration_s == null ? defaultPhotoDuration : data.effective_duration_s;
      clip.style.setProperty("--clip-flex", String(Number(flex).toFixed(4)));
      const label = clip.querySelector("[data-clip-duration]");
      if (label) {
        label.textContent =
          data.effective_duration_s == null
            ? "—"
            : `${Number(data.effective_duration_s).toFixed(1)}s`;
      }
      const resetBtn = document.getElementById("inspector-photo-reset");
      if (resetBtn) resetBtn.disabled = data.photo_duration_s == null;
      const input = document.getElementById("inspector-photo-duration");
      if (input) {
        const shown =
          data.photo_duration_s == null ? defaultPhotoDuration : data.photo_duration_s;
        input.value = Number(shown).toFixed(1);
      }
      if (reloadIfForwardLoop()) return;
      refreshAppliedTransitions();
      layoutTimeline();
      setProjectTime(state.projectTimeS);
      setSaveState(true);
      showFlash("");
    } catch (_) {
      clip.dataset.photoDuration = prev;
      showFlash(msgDurationFailed);
    }
  }

  function soundtrackOnceS() {
    if (!state.tracks.length) return null;
    let total = 0;
    for (const track of state.tracks) {
      if (!track.available || !(track.durationS > 0)) return null;
      total += track.durationS;
    }
    return total;
  }

  function loopTransitionChoice(clip) {
    const value = clip && clip.dataset.forwardLoopTransition;
    if (value === "crossfade" || value === "cinematic" || value === "match") return value;
    return "off";
  }

  function loopEffectReady(clip) {
    return !!(
      clip &&
      clip.dataset.kind === "video" &&
      (forwardLoopActive(clip) || sectionRepeats(clip) > 1)
    );
  }

  function loopEffectNote(clip, ready) {
    if (!ready || !clip) return "";
    const choice = loopTransitionChoice(clip);
    if (choice === "off") return "";
    if (choice === "match") {
      const state = clip.dataset.loopMatchState || "low";
      if (state === "stale") return msgLoopMatchStale;
      if (state !== "ok") return msgLoopMatchLow;
      const start = Number(clip.dataset.loopMatchIn);
      const end = Number(clip.dataset.loopMatchOut);
      let note = msgLoopMatchOk
        .replace("{start}", (Number.isFinite(start) ? start : 0).toFixed(2))
        .replace("{end}", (Number.isFinite(end) ? end : 0).toFixed(2));
      if (loopOverlapS(clip) > 0) note = `${note} ${msgLoopMatchFade}`;
      return note;
    }
    const overlap = loopOverlapS(clip);
    if (forwardLoopActive(clip) && (Number(clip.dataset.forwardLoopPlays) || 0) < 2) {
      return msgLoopTransitionOnce;
    }
    if (!(overlap > 0)) return msgLoopTransitionShort;
    const requested = Number(clip.dataset.forwardLoopTransitionS);
    if (Number.isFinite(requested) && requested - overlap > 0.05) {
      const template = choice === "cinematic" ? msgLoopBlendClamped : msgLoopTransitionClamped;
      return template.replace("{seconds}", overlap.toFixed(1));
    }
    return choice === "cinematic" ? msgLoopCinematic : msgLoopCrossfade;
  }

  function forwardLoopHint(reason, clip) {
    if (reason === "unknown_duration" || reason === "unavailable") return msgForwardLoopUnknown;
    if (reason === "story_filled") return msgForwardLoopFilled;
    if (reason === "too_many_plays" || reason === "section_short") return msgForwardLoopShort;
    if (reason === "other_clip" || reason === "forward_loop_other_clip") return msgForwardLoopOther;
    return msgForwardLoopHint;
  }

  function loopTransitionNote(clip, reason) {
    if (!clip || reason !== "active" || loopTransitionChoice(clip) !== "crossfade") return "";
    const overlap = forwardLoopOverlapS(clip);
    const requested = Number(clip.dataset.forwardLoopTransitionS);
    if (overlap > 0 && Number.isFinite(requested) && requested - overlap > 0.05) {
      return msgLoopTransitionClamped.replace("{seconds}", overlap.toFixed(1));
    }
    return "";
  }

  function forwardLoopError(detail) {
    const known = forwardLoopHint(detail);
    if (known !== msgForwardLoopHint || detail === "active" || detail === "ready" || detail === "off") {
      if (
        detail === "unknown_duration" ||
        detail === "unavailable" ||
        detail === "story_filled" ||
        detail === "too_many_plays" ||
        detail === "section_short" ||
        detail === "other_clip" ||
        detail === "forward_loop_other_clip"
      ) {
        return known;
      }
    }
    return msgForwardLoopFailed;
  }

  function fillForwardLoop(clip) {
    const box = document.getElementById("inspector-forward-loop");
    const hint = document.getElementById("inspector-forward-loop-hint");
    const repeatEl = document.getElementById("inspector-section-repeats");
    if (!box || !hint || !clip) return;
    const requested = clip.dataset.forwardLoop === "1";
    const active = clip.dataset.forwardLoopActive === "1";
    let reason = clip.dataset.forwardLoopReason || "off";
    const other = clips().some(
      (otherClip) => otherClip !== clip && otherClip.dataset.forwardLoop === "1"
    );
    if (!requested && other) reason = "other_clip";
    else if (!requested) reason = soundtrackOnceS() == null ? "unknown_duration" : "ready";
    else if (!active && (reason === "active" || reason === "ready" || reason === "off")) {
      reason = "unknown_duration";
    }
    box.checked = requested;
    box.disabled = !requested && (reason === "unknown_duration" || reason === "other_clip");
    if (repeatEl) repeatEl.disabled = active;
    hint.textContent = forwardLoopHint(reason, clip);
    fillLoopEffect(clip);
  }

  function fillLoopEffect(clip) {
    const idle = document.getElementById("inspector-loop-effect-idle");
    const controls = document.getElementById("inspector-loop-effect-controls");
    const transitionEl = document.getElementById("inspector-loop-transition");
    const durationWrap = document.getElementById("inspector-loop-transition-duration-wrap");
    const durationEl = document.getElementById("inspector-loop-transition-duration");
    const transitionHint = document.getElementById("inspector-loop-transition-hint");
    const curveWrap = document.getElementById("inspector-loop-transition-curve-wrap");
    const curveEl = document.getElementById("inspector-loop-transition-curve");
    const ready = loopEffectReady(clip);
    if (idle) idle.hidden = ready;
    if (controls) controls.hidden = !ready;
    const choice = loopTransitionChoice(clip);
    if (transitionEl && document.activeElement !== transitionEl) transitionEl.value = choice;
    if (durationEl && document.activeElement !== durationEl) {
      const stored = Number(clip && clip.dataset.forwardLoopTransitionS);
      durationEl.value = (Number.isFinite(stored) && stored > 0 ? stored : 1).toFixed(1);
    }
    if (transitionEl) transitionEl.disabled = !ready;
    if (durationEl) {
      durationEl.disabled = !ready;
      durationEl.max = choice === "cinematic" ? "5" : "2";
    }
    if (durationWrap) durationWrap.hidden = !ready || choice === "off";
    if (curveWrap) curveWrap.hidden = !ready || choice !== "cinematic";
    if (curveEl && document.activeElement !== curveEl) {
      curveEl.value = clip && clip.dataset.loopTransitionCurve === "linear" ? "linear" : "smooth";
    }
    if (transitionHint) {
      const note = loopEffectNote(clip, ready);
      transitionHint.hidden = !note;
      transitionHint.textContent = note;
    }
  }

  function reloadIfForwardLoop() {
    if (clips().some((clip) => clip.dataset.forwardLoop === "1")) {
      window.location.reload();
      return true;
    }
    return false;
  }

  function applyForwardLoopClip(clip, data) {
    if (!clip || !data) return;
    clip.dataset.forwardLoop = data.enabled ? "1" : "0";
    clip.dataset.forwardLoopActive = data.active ? "1" : "0";
    clip.dataset.forwardLoopReason = data.reason || (data.active ? "active" : "off");
    if (data.transition) clip.dataset.forwardLoopTransition = data.transition;
    if (data.transition_s != null) clip.dataset.forwardLoopTransitionS = String(data.transition_s);
    if (data.overlap_s != null) clip.dataset.forwardLoopOverlap = String(data.overlap_s);
    if (data.plays != null) clip.dataset.forwardLoopPlays = String(data.plays);
    if (data.partial_s != null) clip.dataset.forwardLoopPartial = String(data.partial_s);
    if (data.match_state) clip.dataset.loopMatchState = data.match_state;
    if (data.match_in_s != null) clip.dataset.loopMatchIn = String(data.match_in_s);
    if (data.match_out_s != null) clip.dataset.loopMatchOut = String(data.match_out_s);
    if (data.curve) clip.dataset.loopTransitionCurve = data.curve;
    if (data.section_repeats != null) {
      clip.dataset.sectionRepeats = String(data.section_repeats);
    }
    if (data.effective_duration_s != null) {
      clip.dataset.effectiveDuration = String(data.effective_duration_s);
      const flex = Number(data.effective_duration_s);
      if (Number.isFinite(flex)) clip.style.setProperty("--clip-flex", flex.toFixed(4));
      const label = clip.querySelector("[data-clip-duration]");
      if (label) label.textContent = Number.isFinite(flex) ? `${flex.toFixed(1)}s` : "—";
    }
    if (data.summary && data.summary.estimated_total_s != null) {
      root.dataset.totalS = String(data.summary.estimated_total_s);
      root.dataset.totalLabel =
        data.summary.estimated_total_label || formatTime(data.summary.estimated_total_s);
    }
    const durationLine = document.querySelector("#inspector-clip [data-field='duration-line']");
    const dur = clipDuration(clip);
    if (durationLine) {
      durationLine.textContent = dur > 0 ? `${labelInStory}: ${dur.toFixed(1)} s` : "—";
    }
    fillForwardLoop(clip);
  }

  function loopEffectBody() {
    const choiceEl = document.getElementById("inspector-loop-transition");
    const durationEl = document.getElementById("inspector-loop-transition-duration");
    const choice = choiceEl && choiceEl.value;
    const cinematic = choice === "cinematic";
    let duration = Number(durationEl && durationEl.value);
    if (!Number.isFinite(duration)) duration = 1;
    duration = Math.max(0.5, Math.min(cinematic ? 5 : 2, duration));
    const curveEl = document.getElementById("inspector-loop-transition-curve");
    const body = {
      transition: choice === "crossfade" || choice === "match" || cinematic ? choice : "off",
      duration_s: Math.round(duration * 10) / 10,
    };
    if (cinematic) body.curve = curveEl && curveEl.value === "linear" ? "linear" : "smooth";
    return body;
  }

  async function persistForwardLoop(clip, enabled) {
    if (reuseDraft) return;
    const box = document.getElementById("inspector-forward-loop");
    const prevLoop = clip.dataset.forwardLoop;
    const prevActive = clip.dataset.forwardLoopActive;
    const prevReason = clip.dataset.forwardLoopReason;
    const prevDuration = clip.dataset.effectiveDuration;
    const prevTransition = clip.dataset.forwardLoopTransition;
    const prevTransitionS = clip.dataset.forwardLoopTransitionS;
    const prevOverlap = clip.dataset.forwardLoopOverlap;
    const prevPlays = clip.dataset.forwardLoopPlays;
    const prevPartial = clip.dataset.forwardLoopPartial;
    setSaveState(false);
    try {
      const res = await fetch(`/api/studio/${clip.dataset.studioId}/forward-loop`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ enabled: !!enabled }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        throw new Error((data && data.detail) || msgForwardLoopFailed);
      }
      applyForwardLoopClip(clip, data);
      refreshAppliedTransitions();
      layoutTimeline();
      setProjectTime(state.projectTimeS);
      setSaveState(true);
      showFlash("");
    } catch (err) {
      clip.dataset.forwardLoop = prevLoop;
      clip.dataset.forwardLoopActive = prevActive;
      clip.dataset.forwardLoopReason = prevReason;
      clip.dataset.effectiveDuration = prevDuration;
      clip.dataset.forwardLoopTransition = prevTransition;
      clip.dataset.forwardLoopTransitionS = prevTransitionS;
      clip.dataset.forwardLoopOverlap = prevOverlap;
      clip.dataset.forwardLoopPlays = prevPlays;
      clip.dataset.forwardLoopPartial = prevPartial;
      if (box) box.checked = prevLoop === "1";
      fillForwardLoop(clip);
      showFlash(forwardLoopError(err && err.message));
    }
  }

  async function persistSection(clip, preset) {
    if (reuseDraft) return;
    const inEl = document.getElementById("inspector-source-in");
    const outEl = document.getElementById("inspector-source-out");
    const repeatEl = document.getElementById("inspector-section-repeats");
    if (!inEl || !outEl || !repeatEl) return;
    const sourceIn = preset ? Number(preset.sourceIn) : Number(inEl.value);
    const sourceOut = preset ? Number(preset.sourceOut) : Number(outEl.value);
    let repeats = Math.round(Number(repeatEl.value));
    if (!Number.isFinite(repeats)) repeats = 1;
    repeats = Math.max(1, Math.min(MAX_SECTION_REPEATS, repeats));
    repeatEl.value = String(repeats);
    if (!Number.isFinite(sourceIn) || !Number.isFinite(sourceOut) || sourceOut <= sourceIn) {
      showFlash(msgSectionFailed);
      return;
    }
    if (preset) {
      inEl.value = sourceIn.toFixed(2);
      outEl.value = sourceOut.toFixed(2);
    }
    const prevIn = preset ? preset.prevIn : clip.dataset.sourceIn;
    const prevOut = preset ? preset.prevOut : clip.dataset.sourceOut;
    const prevRepeats = clip.dataset.sectionRepeats;
    const prevDuration = preset ? preset.prevDuration : clip.dataset.effectiveDuration;
    setSaveState(false);
    try {
      const res = await fetch(`/api/studio/${clip.dataset.studioId}/section`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          source_in_s: sourceIn,
          source_out_s: sourceOut,
          repeats,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        throw new Error((data && data.detail) || msgSectionFailed);
      }
      clip.dataset.sourceIn = data.source_in_s == null ? "" : String(data.source_in_s);
      clip.dataset.sourceOut = data.source_out_s == null ? "" : String(data.source_out_s);
      clip.dataset.sectionRepeats = String(data.section_repeats || 1);
      clip.dataset.effectiveDuration =
        data.effective_duration_s == null ? "" : String(data.effective_duration_s);
      const flex = Number(data.effective_duration_s);
      if (Number.isFinite(flex)) {
        clip.style.setProperty("--clip-flex", flex.toFixed(4));
      }
      const label = clip.querySelector("[data-clip-duration]");
      if (label) {
        label.textContent = Number.isFinite(flex) ? `${flex.toFixed(1)}s` : "—";
      }
      if (data.summary && data.summary.estimated_total_s != null) {
        root.dataset.totalS = String(data.summary.estimated_total_s);
        root.dataset.totalLabel =
          data.summary.estimated_total_label || formatTime(data.summary.estimated_total_s);
      }
      if (document.activeElement !== inEl) inEl.value = sourceInS(clip).toFixed(2);
      if (document.activeElement !== outEl) outEl.value = sourceOutS(clip).toFixed(2);
      if (document.activeElement !== repeatEl) repeatEl.value = String(sectionRepeats(clip));
      const durationLine = document.querySelector(
        "#inspector-clip [data-field='duration-line']"
      );
      const dur = clipDuration(clip);
      if (durationLine) {
        durationLine.textContent = dur > 0 ? `${labelInStory}: ${dur.toFixed(1)} s` : "—";
      }
      refreshAppliedTransitions();
      layoutTimeline();
      setProjectTime(state.projectTimeS);
      ensureOriginalRow(clip);
      setSaveState(true);
      showFlash("");
    } catch (err) {
      clip.dataset.sourceIn = prevIn;
      clip.dataset.sourceOut = prevOut;
      clip.dataset.sectionRepeats = prevRepeats;
      clip.dataset.effectiveDuration = prevDuration;
      if (document.activeElement !== inEl) inEl.value = sourceInS(clip).toFixed(2);
      if (document.activeElement !== outEl) outEl.value = sourceOutS(clip).toFixed(2);
      layoutTimeline();
      showFlash((err && err.message) || msgSectionFailed);
    }
  }

  // Same steps as edge_source_after_drag in studio_cut.py, then 0.01 s so the
  // inspector fields and the drag cannot disagree. No snap.
  function edgeSourceAfterDrag(edge, sourceIn, sourceOut, deltaStory, speed, repeats, catalog) {
    const limit = Number(catalog);
    if (!(limit > MIN_CUT_SEGMENT_S)) {
      return { inS: 0, outS: Math.max(0, limit) };
    }
    const rate = speed === 0.5 || speed === 0.25 ? speed : 1;
    const count = Math.max(1, Math.min(MAX_SECTION_REPEATS, Math.round(Number(repeats) || 1)));
    const delta = deltaStory * (rate / count);
    let start = Number(sourceIn);
    let end = Number(sourceOut);
    if (edge === "in") start += delta;
    else end += delta;
    start = Math.min(Math.max(0, start), limit);
    end = Math.min(Math.max(0, end), limit);
    if (end - start < MIN_CUT_SEGMENT_S) {
      if (edge === "in") start = end - MIN_CUT_SEGMENT_S;
      else end = start + MIN_CUT_SEGMENT_S;
      start = Math.min(Math.max(0, start), limit);
      end = Math.min(Math.max(0, end), limit);
      if (end - start < MIN_CUT_SEGMENT_S) {
        if (edge === "in") end = Math.min(limit, start + MIN_CUT_SEGMENT_S);
        else start = Math.max(0, end - MIN_CUT_SEGMENT_S);
      }
    }
    start = Number(start.toFixed(2));
    end = Number(end.toFixed(2));
    start = Math.min(Math.max(0, start), limit);
    end = Math.min(Math.max(0, end), limit);
    if (end - start < MIN_CUT_SEGMENT_S) {
      if (edge === "in") start = Math.max(0, Number((end - MIN_CUT_SEGMENT_S).toFixed(2)));
      else end = Math.min(limit, Number((start + MIN_CUT_SEGMENT_S).toFixed(2)));
    }
    return { inS: start, outS: end };
  }

  function storedSectionRepeats(clip) {
    const n = Number(clip && clip.dataset.sectionRepeats);
    if (!Number.isFinite(n)) return 1;
    return Math.max(1, Math.min(MAX_SECTION_REPEATS, Math.round(n)));
  }

  function previewEdgeDuration(clip, inS, outS) {
    const speed = playbackSpeed(clip);
    const span = Math.max(0, outS - inS);
    const cycle = speed > 0 ? span / speed : span;
    const reps = storedSectionRepeats(clip);
    let duration = cycle * reps;
    const overlap = loopOverlapS(clip);
    if (overlap > 0 && reps > 1) duration -= overlap * (reps - 1);
    return Math.max(MIN_CUT_SEGMENT_S, duration);
  }

  let edgeDrag = null;
  const edgeReadout = document.createElement("div");
  edgeReadout.className = "studio-edge-readout";
  edgeReadout.hidden = true;
  document.body.appendChild(edgeReadout);

  function paintEdgePreview(clip, inS, outS) {
    clip.dataset.sourceIn = String(inS);
    clip.dataset.sourceOut = String(outS);
    if (!forwardLoopActive(clip)) {
      const dur = previewEdgeDuration(clip, inS, outS);
      clip.dataset.effectiveDuration = String(dur);
      clip.style.setProperty("--clip-flex", dur.toFixed(4));
      const label = clip.querySelector("[data-clip-duration]");
      if (label) label.textContent = Number.isFinite(dur) ? `${dur.toFixed(1)}s` : "—";
    }
    if (
      state.selected.type === "clip" &&
      String(state.selected.id) === String(clip.dataset.studioId)
    ) {
      const inEl = document.getElementById("inspector-source-in");
      const outEl = document.getElementById("inspector-source-out");
      if (inEl && document.activeElement !== inEl) inEl.value = inS.toFixed(2);
      if (outEl && document.activeElement !== outEl) outEl.value = outS.toFixed(2);
      const durationLine = document.querySelector("#inspector-clip [data-field='duration-line']");
      const dur = clipDuration(clip);
      if (durationLine) {
        durationLine.textContent = dur > 0 ? `${labelInStory}: ${dur.toFixed(1)} s` : "—";
      }
    }
    layoutTimeline();
    setProjectTime(Math.min(state.projectTimeS, totalDuration()));
  }

  function restoreEdgeSnapshot(drag) {
    const clip = drag.clip;
    clip.dataset.sourceIn = drag.prevIn;
    clip.dataset.sourceOut = drag.prevOut;
    clip.dataset.effectiveDuration = drag.prevDuration;
    if (drag.prevFlex) clip.style.setProperty("--clip-flex", drag.prevFlex);
    else clip.style.removeProperty("--clip-flex");
    const label = clip.querySelector("[data-clip-duration]");
    if (label) label.textContent = drag.prevLabel;
    if (
      state.selected.type === "clip" &&
      String(state.selected.id) === String(clip.dataset.studioId)
    ) {
      const inEl = document.getElementById("inspector-source-in");
      const outEl = document.getElementById("inspector-source-out");
      if (inEl) inEl.value = sourceInS(clip).toFixed(2);
      if (outEl) outEl.value = sourceOutS(clip).toFixed(2);
    }
    layoutTimeline();
    setProjectTime(Math.min(state.projectTimeS, totalDuration()));
  }

  function showEdgeReadout(edge, value, clientX, clientY) {
    const name =
      edge === "in"
        ? root.dataset.sourceIn || "Source in"
        : root.dataset.sourceOut || "Source out";
    edgeReadout.textContent = `${name} ${Number(value).toFixed(2)} s`;
    edgeReadout.hidden = false;
    edgeReadout.style.left = `${clientX + 12}px`;
    edgeReadout.style.top = `${clientY + 16}px`;
  }

  function onEdgePointerMove(event) {
    if (!edgeDrag || event.pointerId !== edgeDrag.pointerId) return;
    const deltaStory = (event.clientX - edgeDrag.originX) / edgeDrag.pps;
    const next = edgeSourceAfterDrag(
      edgeDrag.edge,
      edgeDrag.startIn,
      edgeDrag.startOut,
      deltaStory,
      edgeDrag.speed,
      edgeDrag.repeats,
      edgeDrag.catalog
    );
    edgeDrag.currentIn = next.inS;
    edgeDrag.currentOut = next.outS;
    paintEdgePreview(edgeDrag.clip, next.inS, next.outS);
    const shown = edgeDrag.edge === "in" ? next.inS : next.outS;
    showEdgeReadout(edgeDrag.edge, shown, event.clientX, event.clientY);
  }

  function finishEdgeDrag(commit) {
    const drag = edgeDrag;
    if (!drag) return;
    edgeDrag = null;
    window.removeEventListener("pointermove", onEdgePointerMove);
    window.removeEventListener("pointerup", onEdgePointerUp);
    window.removeEventListener("pointercancel", onEdgePointerCancel);
    document.removeEventListener("keydown", onEdgeKeyDown, true);
    document.documentElement.classList.remove("is-edge-drag");
    edgeReadout.hidden = true;
    drag.clip.classList.remove("is-edge-target");
    const changed =
      Math.abs(drag.currentIn - drag.startIn) > 0.0005 ||
      Math.abs(drag.currentOut - drag.startOut) > 0.0005;
    if (!commit || !changed || reuseDraft) {
      restoreEdgeSnapshot(drag);
      return;
    }
    persistSection(drag.clip, {
      sourceIn: drag.currentIn,
      sourceOut: drag.currentOut,
      prevIn: drag.prevIn,
      prevOut: drag.prevOut,
      prevDuration: drag.prevDuration,
    });
  }

  function onEdgePointerUp(event) {
    if (!edgeDrag || event.pointerId !== edgeDrag.pointerId) return;
    finishEdgeDrag(true);
  }

  function onEdgePointerCancel(event) {
    if (!edgeDrag || event.pointerId !== edgeDrag.pointerId) return;
    finishEdgeDrag(false);
  }

  function onEdgeKeyDown(event) {
    if (!edgeDrag) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      finishEdgeDrag(false);
      return;
    }
    if ((event.ctrlKey || event.metaKey) && (event.key === "z" || event.key === "y")) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function beginEdgeDrag(handle, event) {
    if (reuseDraft || event.button !== 0) return;
    const clip = handle.closest && handle.closest(".studio-clip");
    if (!clip || clip.dataset.kind !== "video") return;
    const catalog = catalogDurationS(clip);
    if (catalog == null) return;
    const pps = timelinePxPerSecond();
    if (!(pps > 0)) return;
    event.preventDefault();
    event.stopPropagation();
    pausePlayback();
    selectClip(clip.dataset.studioId, { movePlayhead: false });
    const startIn = sourceInS(clip);
    const startOut = sourceOutS(clip);
    edgeDrag = {
      pointerId: event.pointerId,
      edge: handle.getAttribute("data-edge") === "in" ? "in" : "out",
      clip,
      originX: event.clientX,
      pps,
      catalog,
      speed: playbackSpeed(clip),
      repeats: storedSectionRepeats(clip),
      startIn,
      startOut,
      currentIn: startIn,
      currentOut: startOut,
      prevIn: clip.dataset.sourceIn,
      prevOut: clip.dataset.sourceOut,
      prevDuration: clip.dataset.effectiveDuration,
      prevFlex: clip.style.getPropertyValue("--clip-flex"),
      prevLabel: (clip.querySelector("[data-clip-duration]") || {}).textContent || "",
    };
    clip.classList.add("is-edge-target");
    document.documentElement.classList.add("is-edge-drag");
    handle.setPointerCapture?.(event.pointerId);
    window.addEventListener("pointermove", onEdgePointerMove);
    window.addEventListener("pointerup", onEdgePointerUp);
    window.addEventListener("pointercancel", onEdgePointerCancel);
    document.addEventListener("keydown", onEdgeKeyDown, true);
    showEdgeReadout(
      edgeDrag.edge,
      edgeDrag.edge === "in" ? startIn : startOut,
      event.clientX,
      event.clientY
    );
  }

  function seekFromClientX(clientX, { resumeAfter = false } = {}) {
    if (reuseDraft) return;
    const originEl = timelineCanvasEl || tracksEl;
    if (!originEl) return;
    const rect = originEl.getBoundingClientRect();
    const t = xToTime(clientX - rect.left);
    setProjectTime(Math.max(0, Math.min(totalDuration(), t)));
    if (resumeAfter) startPlayback();
  }

  // ——— Events ———

  if (previewVideo) {
    previewVideo.addEventListener("timeupdate", onVideoTimeUpdate);
    previewVideo.addEventListener("ended", onVideoEnded);
  }

  root.querySelectorAll("[data-browser-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.getAttribute("data-browser-tab");
      root.querySelectorAll("[data-browser-tab]").forEach((t) => {
        const on = t === tab;
        t.classList.toggle("is-active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      root.querySelectorAll("[data-browser-panel]").forEach((panel) => {
        const on = panel.getAttribute("data-browser-panel") === name;
        panel.classList.toggle("is-active", on);
        panel.hidden = !on;
      });
    });
  });

  document.getElementById("studio-undo")?.addEventListener("click", () => {
    if (reuseDraft) return;
    applyStudioHistory("undo");
  });
  document.getElementById("studio-redo")?.addEventListener("click", () => {
    if (reuseDraft) return;
    applyStudioHistory("redo");
  });
  function reuseReasonWins() {
    const reuseItem = document.getElementById("studio-clip-menu-reuse");
    if (!reuseItem || reuseItem.hidden) return;
    const text = reuseItem.dataset.reason || "";
    if (reuseItem.getAttribute("aria-disabled") === "true" && text) setClipMenuReason(text);
  }
  function catalogDurationS(clip) {
    const n = Number(clip && clip.dataset.mediaDuration);
    return Number.isFinite(n) && n > 0 ? n : null;
  }
  function reuseMenuState(clip) {
    if (!clip || clip.dataset.kind !== "video") return { show: false, reason: "" };
    if (clip.dataset.available !== "1" || clip.dataset.canPlay !== "1") {
      return {
        show: true,
        reason:
          root.dataset.reuseOffline ||
          "This recording is offline, so another scene cannot be chosen.",
      };
    }
    if (catalogDurationS(clip) == null) {
      return {
        show: true,
        reason:
          root.dataset.reuseUnknown ||
          "The length of this recording is unknown, so a range cannot be chosen.",
      };
    }
    return { show: true, reason: "" };
  }
  function defaultReuseRange(clip, catalog) {
    const inn = sourceInS(clip);
    const out = sourceOutS(clip);
    if (catalog - out >= MIN_CUT_SEGMENT_S) return { inS: out, outS: catalog, whole: false };
    if (inn >= MIN_CUT_SEGMENT_S) return { inS: 0, outS: inn, whole: false };
    return { inS: 0, outS: catalog, whole: true };
  }
  function fillReuseTemplate(template, token, value) {
    return String(template || "").replace(token, value);
  }
  function setReusePieceHidden(id, hidden) {
    const el = document.getElementById(id);
    if (!el) return;
    const label = el.closest("label");
    if (label) label.hidden = hidden;
    else el.hidden = hidden;
  }
  function showReuseChrome(on) {
    const draft = document.getElementById("inspector-reuse-draft");
    const actions = document.getElementById("inspector-reuse-actions");
    if (draft) draft.hidden = !on;
    if (actions) actions.hidden = !on;
    document.querySelectorAll("[data-inspector-tab-button]").forEach((btn) => {
      if (btn.getAttribute("data-inspector-tab-button") === "clip") return;
      btn.hidden = on;
    });
    setReusePieceHidden("inspector-section-repeats", on);
    const repeats = document.getElementById("inspector-section-repeats");
    const repeatsHint = repeats && repeats.closest("label") && repeats.closest("label").nextElementSibling;
    if (repeatsHint && repeatsHint.classList.contains("hint")) repeatsHint.hidden = on;
    setReusePieceHidden("inspector-forward-loop", on);
    const loopHint = document.getElementById("inspector-forward-loop-hint");
    if (loopHint) loopHint.hidden = on;
    const loopEffect = document.getElementById("inspector-loop-effect");
    if (loopEffect) loopEffect.hidden = on;
    const cutHint = document.querySelector("#inspector-video-timing [data-field='cut-hint']");
    if (cutHint) cutHint.hidden = on;
    const speed = document.getElementById("inspector-speed");
    if (on && speed) speed.hidden = true;
  }
  function reuseDraftName() {
    if (!reuseDraft) return "";
    if (reuseDraft.filename) return reuseDraft.filename;
    return (reuseDraft.clip && reuseDraft.clip.dataset.filename) || "";
  }
  function reusePreviewSrc() {
    if (!reuseDraft) return "";
    if (reuseDraft.hasProxy && reuseDraft.proxyUrl) return reuseDraft.proxyUrl;
    if (reuseDraft.streamUrl) return reuseDraft.streamUrl;
    if (reuseDraft.clip) return videoSrcFor(reuseDraft.clip);
    return "";
  }
  function paintReuseDraft() {
    if (!reuseDraft) return;
    const inEl = document.getElementById("inspector-source-in");
    const outEl = document.getElementById("inspector-source-out");
    if (inEl) inEl.value = reuseDraft.inS.toFixed(2);
    if (outEl) outEl.value = reuseDraft.outS.toFixed(2);
    const timing = document.getElementById("inspector-video-timing");
    if (timing) timing.hidden = false;
    showInspector("inspector-clip");
    const mode = document.getElementById("studio-view-mode");
    if (mode) {
      mode.hidden = false;
      mode.textContent = root.dataset.viewOriginal || "Original";
    }
    const play = document.querySelector('[data-transport="toggle"]');
    if (play) play.disabled = false;
    const note = document.getElementById("inspector-reuse-note");
    if (note) {
      note.textContent = reuseDraft.clip
        ? root.dataset.reuseNote || "The clip already in the Story is not changed."
        : root.dataset.originalKeep || "The scenes already in the Story stay as they are.";
    }
    const meta = document.getElementById("inspector-reuse-meta");
    if (meta) {
      const original = fillReuseTemplate(
        root.dataset.reuseOriginal || "Original {length}",
        "{length}",
        `${reuseDraft.catalog.toFixed(1)} s`
      );
      const scene = fillReuseTemplate(
        root.dataset.reuseScene || "New scene {length}",
        "{length}",
        `${Math.max(0, reuseDraft.outS - reuseDraft.inS).toFixed(1)} s`
      );
      meta.textContent = `${original} · ${scene}`;
    }
    const whole = document.getElementById("inspector-reuse-whole");
    if (whole) {
      whole.hidden = !reuseDraft.whole;
      whole.textContent =
        root.dataset.reuseWhole ||
        "Add will use the whole recording unless the range is narrowed.";
    }
    const add = document.getElementById("inspector-reuse-add");
    if (add) add.disabled = reuseDraft.outS - reuseDraft.inS < MIN_CUT_SEGMENT_S;
    showReuseChrome(true);
    setInspectorTab("clip");
    setInspectorHeading(
      fillReuseTemplate(
        root.dataset.reuseHeading || "Another scene from {name}",
        "{name}",
        reuseDraftName()
      )
    );
    if (inEl) inEl.focus();
  }
  function readReuseFields(seekEdge) {
    if (!reuseDraft) return;
    const inEl = document.getElementById("inspector-source-in");
    const outEl = document.getElementById("inspector-source-out");
    const catalog = reuseDraft.catalog;
    let inn = Number(inEl && inEl.value);
    let out = Number(outEl && outEl.value);
    if (!Number.isFinite(inn)) inn = 0;
    if (!Number.isFinite(out)) out = catalog;
    inn = Math.max(0, Math.min(catalog, inn));
    out = Math.max(0, Math.min(catalog, out));
    reuseDraft.inS = inn;
    reuseDraft.outS = out;
    reuseDraft.whole = inn <= 1e-4 && out >= catalog - 1e-3;
    const add = document.getElementById("inspector-reuse-add");
    if (add) add.disabled = out - inn < MIN_CUT_SEGMENT_S;
    const meta = document.getElementById("inspector-reuse-meta");
    if (meta) {
      const original = fillReuseTemplate(
        root.dataset.reuseOriginal || "Original {length}",
        "{length}",
        `${catalog.toFixed(1)} s`
      );
      const scene = fillReuseTemplate(
        root.dataset.reuseScene || "New scene {length}",
        "{length}",
        `${Math.max(0, out - inn).toFixed(1)} s`
      );
      meta.textContent = `${original} · ${scene}`;
    }
    const whole = document.getElementById("inspector-reuse-whole");
    if (whole) whole.hidden = !reuseDraft.whole;
    seekCatalog(seekEdge === "out" ? out : inn);
  }
  function seekCatalog(seconds) {
    if (!previewVideo || !reuseDraft) return;
    const src = reusePreviewSrc();
    if (!src) return;
    const catalog = reuseDraft.catalog;
    const apply = () => {
      if (!reuseDraft) return;
      let max = catalog;
      const known = Number(previewVideo.duration);
      if (Number.isFinite(known) && known > 0) max = Math.min(max, known);
      const target = Math.max(0, Math.min(Number(seconds) || 0, max));
      try {
        previewVideo.hidden = false;
        if (previewImage) previewImage.hidden = true;
        if (previewPlaceholder) previewPlaceholder.hidden = true;
        previewVideo.playbackRate = 1;
        previewVideo.muted = false;
        previewVideo.volume = state.volume;
        previewVideo.currentTime = target;
      } catch (_) {
        /* ignore seek errors while loading */
      }
      schedulePreviewBlit();
    };
    suppressVideoClock = true;
    if (loadedVideoSrc !== src) {
      loadedVideoSrc = src;
      previewVideo.src = src;
      previewVideo.load();
      previewVideo.addEventListener("loadedmetadata", apply, { once: true });
      return;
    }
    if (previewVideo.readyState >= 1) apply();
    else previewVideo.addEventListener("loadedmetadata", apply, { once: true });
  }
  function toggleReusePreview() {
    if (!previewVideo || !reuseDraft) return;
    if (!previewVideo.paused) {
      previewVideo.pause();
      return;
    }
    if (previewVideo.currentTime >= reuseDraft.outS - 0.05) seekCatalog(reuseDraft.inS);
    suppressVideoClock = true;
    previewVideo.play().catch(() => {});
  }
  function cancelReuseDraft() {
    if (!reuseDraft) return;
    const clip = reuseDraft.clip;
    const time = state.projectTimeS;
    reuseDraft = null;
    suppressVideoClock = false;
    if (previewVideo) {
      try {
        previewVideo.pause();
      } catch (_) {}
    }
    showReuseChrome(false);
    const mode = document.getElementById("studio-view-mode");
    if (mode) mode.hidden = true;
    if (!clips().length) {
      const play = document.querySelector('[data-transport="toggle"]');
      if (play) play.disabled = true;
      showInspector("inspector-empty");
      const timing = document.getElementById("inspector-video-timing");
      if (timing) timing.hidden = true;
      if (previewPlaceholder) previewPlaceholder.hidden = false;
    }
    if (clip && clip.isConnected) selectClip(clip.dataset.studioId, { movePlayhead: false });
    setProjectTime(time);
  }
  function ensureOriginalRow(clip) {
    if (!clip || clip.dataset.kind !== "video") return;
    if (!clip.dataset.sourceIn && !clip.dataset.sourceOut) return;
    const mediaId = clip.dataset.mediaId;
    if (!mediaId) return;
    if (document.querySelector(`[data-original-media-id="${CSS.escape(mediaId)}"]`)) return;
    const panel = document.querySelector('[data-browser-panel="story"]');
    if (!panel) return;
    let box = document.getElementById("studio-originals");
    if (!box) {
      box = document.createElement("div");
      box.id = "studio-originals";
      box.className = "studio-originals";
      const label = document.createElement("p");
      label.className = "studio-originals-label";
      label.textContent = root.dataset.originalLabel || "Original";
      const list = document.createElement("ul");
      list.className = "studio-browser-list";
      const hint = document.createElement("p");
      hint.className = "hint studio-originals-hint";
      hint.textContent = root.dataset.originalHint || "";
      box.append(label, list, hint);
      const empty = panel.querySelector(".studio-browser-empty");
      if (empty) empty.hidden = true;
      panel.insertBefore(box, panel.firstChild);
    }
    const li = document.createElement("li");
    li.className = "studio-browser-item studio-original-item";
    li.draggable = clip.dataset.canPlay === "1";
    li.dataset.originalMediaId = mediaId;
    li.dataset.filename = clip.dataset.filename || "";
    li.dataset.mediaDuration = clip.dataset.mediaDuration || "";
    li.dataset.streamUrl = clip.dataset.streamUrl || "";
    li.dataset.proxyUrl = clip.dataset.proxyUrl || "";
    li.dataset.hasProxy = clip.dataset.hasProxy || "0";
    li.dataset.canPlay = clip.dataset.canPlay || "0";
    li.dataset.available = clip.dataset.available || "0";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "studio-browser-pick";
    button.dataset.openOriginal = mediaId;
    const thumb = document.createElement("span");
    thumb.className = "studio-browser-thumb";
    if (clip.dataset.thumb) {
      const img = document.createElement("img");
      img.alt = "";
      img.src = clip.dataset.thumb;
      thumb.appendChild(img);
    }
    const meta = document.createElement("span");
    meta.className = "studio-browser-meta";
    const strong = document.createElement("strong");
    strong.textContent = clip.dataset.filename || "";
    const kind = document.createElement("span");
    kind.textContent = root.dataset.originalFull || "Full recording";
    meta.append(strong, kind);
    button.append(thumb, meta);
    li.appendChild(button);
    box.querySelector("ul").appendChild(li);
  }
  function openOriginalDraft(row) {
    if (!row || row.dataset.canPlay !== "1") return;
    clips().forEach((c) => {
      c.classList.remove("is-selected");
      c.removeAttribute("aria-selected");
    });
    const catalog = Number(row.dataset.mediaDuration);
    if (!Number.isFinite(catalog) || catalog <= 0) return;
    pausePlayback();
    clearLutPreviewStill();
    reuseDraft = {
      clip: null,
      mediaId: row.dataset.originalMediaId || "",
      filename: row.dataset.filename || "",
      streamUrl: row.dataset.streamUrl || "",
      proxyUrl: row.dataset.proxyUrl || "",
      hasProxy: row.dataset.hasProxy === "1",
      catalog,
      inS: 0,
      outS: catalog,
      whole: true,
      beforeId: null,
    };
    suppressVideoClock = true;
    paintReuseDraft();
    seekCatalog(0);
  }
  function openReuseDraft(studioId) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    const catalog = catalogDurationS(clip);
    if (!clip || catalog == null) return;
    if (clip.dataset.kind !== "video") return;
    if (clip.dataset.available !== "1" || clip.dataset.canPlay !== "1") return;
    hideClipMenu();
    pausePlayback();
    clearLutPreviewStill();
    const range = defaultReuseRange(clip, catalog);
    reuseDraft = {
      clip,
      mediaId: clip.dataset.mediaId || "",
      filename: clip.dataset.filename || "",
      streamUrl: clip.dataset.streamUrl || "",
      proxyUrl: clip.dataset.proxyUrl || "",
      hasProxy: clip.dataset.hasProxy === "1",
      catalog,
      inS: range.inS,
      outS: range.outS,
      whole: range.whole,
    };
    suppressVideoClock = true;
    paintReuseDraft();
    seekCatalog(range.inS);
  }
  async function addReuseScene() {
    if (!reuseDraft) return;
    const span = reuseDraft.outS - reuseDraft.inS;
    if (span < MIN_CUT_SEGMENT_S) return;
    const sourceIn = reuseDraft.inS;
    const sourceOut = reuseDraft.outS;
    const body = { source_in_s: sourceIn, source_out_s: sourceOut };
    let url = "";
    if (reuseDraft.clip) {
      url = `/api/studio/${reuseDraft.clip.dataset.studioId}/reuse-source`;
    } else if (reuseDraft.mediaId) {
      url = `/api/studio/media/${reuseDraft.mediaId}/reuse-source`;
      if (reuseDraft.beforeId) body.before_id = Number(reuseDraft.beforeId);
    }
    if (!url) return;
    if (previewVideo) previewVideo.pause();
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok || data.id == null) {
        showFlash((data && data.detail) || root.dataset.reuseFailed || "Could not add the scene.");
        return;
      }
      try {
        sessionStorage.setItem(
          CUT_RESTORE_KEY,
          JSON.stringify({ selectId: String(data.id), atClipStart: true })
        );
      } catch (_) {
        /* ignore */
      }
      window.location.reload();
    } catch (_) {
      showFlash(root.dataset.reuseFailed || "Could not add the scene.");
    }
  }
  function showStoryContextMenu(event, anchor, mode, mergeId) {
    const removeItem = document.getElementById("studio-clip-menu-remove");
    const mergeItem = document.getElementById("studio-clip-menu-merge");
    const uncutItem = document.getElementById("studio-clip-menu-uncut");
    const reuseItem = document.getElementById("studio-clip-menu-reuse");
    const clipEl =
      mode === "clip"
        ? (anchor.closest && anchor.closest(".studio-clip")) || anchor
        : null;
    const reuse = mode === "clip" ? reuseMenuState(clipEl) : { show: false, reason: "" };
    if (removeItem) removeItem.hidden = mode !== "clip";
    if (reuseItem) {
      reuseItem.hidden = !reuse.show;
      reuseItem.setAttribute("aria-disabled", reuse.reason ? "true" : "false");
      reuseItem.dataset.studioId = (clipEl && clipEl.dataset.studioId) || "";
      reuseItem.dataset.reason = reuse.reason || "";
    }
    if (mergeItem) {
      mergeItem.hidden = mode !== "clip" || !mergeId;
      mergeItem.setAttribute("aria-disabled", "true");
      mergeItem.dataset.studioId = mergeId || "";
    }
    if (uncutItem) {
      uncutItem.hidden = mode !== "boundary";
      uncutItem.setAttribute("aria-disabled", "true");
      uncutItem.dataset.studioId = mergeId || "";
    }
    setClipMenuReason(reuse.reason || "");
    const opener =
      (anchor.querySelector && anchor.querySelector("[data-select-clip]")) || anchor;
    showClipMenu(event.clientX, event.clientY, opener);
    const action = mode === "boundary" ? uncutItem : mergeItem;
    if (action && !action.hidden && mergeId) refreshMergeItem(action, mergeId);
  }
  grid.addEventListener("contextmenu", (event) => {
    const clip = event.target.closest && event.target.closest(".studio-clip");
    if (clip && clip.dataset.studioId) {
      event.preventDefault();
      selectClip(clip.dataset.studioId, { movePlayhead: false });
      const previous = clip.previousElementSibling;
      const hasPrevious = Boolean(
        previous &&
          (previous.classList.contains("studio-clip") ||
            previous.classList.contains("studio-transition"))
      );
      showStoryContextMenu(
        event,
        clip,
        "clip",
        hasPrevious ? clip.dataset.studioId : ""
      );
      return;
    }
    const transition = event.target.closest && event.target.closest(".studio-transition");
    if (!transition || !transition.dataset.transitionBefore) return;
    event.preventDefault();
    selectTransition(transition);
    showStoryContextMenu(event, transition, "boundary", transition.dataset.transitionBefore);
  });
  document.getElementById("studio-clip-menu-remove")?.addEventListener("click", () => {
    removeSelectedStoryClip();
  });
  document.getElementById("studio-clip-menu-merge")?.addEventListener("click", () => {
    const button = document.getElementById("studio-clip-menu-merge");
    if (mergeItemBlocked(button)) return;
    mergeWithPrevious(button.dataset.studioId);
  });
  document.getElementById("studio-clip-menu-uncut")?.addEventListener("click", () => {
    const button = document.getElementById("studio-clip-menu-uncut");
    if (mergeItemBlocked(button)) return;
    mergeWithPrevious(button.dataset.studioId);
  });
  document.getElementById("studio-clip-menu-reuse")?.addEventListener("click", () => {
    const button = document.getElementById("studio-clip-menu-reuse");
    if (mergeItemBlocked(button)) return;
    openReuseDraft(button.dataset.studioId);
  });
  document.getElementById("inspector-reuse-add")?.addEventListener("click", () => {
    addReuseScene();
  });
  document.querySelector(".studio-clear-form")?.addEventListener(
    "submit",
    (event) => {
      if (!reuseDraft) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    },
    true
  );
  ["inspector-source-in", "inspector-source-out"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", () => {
      if (!reuseDraft) return;
      const edge = id === "inspector-source-out" ? "out" : "in";
      readReuseFields(edge);
    });
    document.getElementById(id)?.addEventListener("keydown", (event) => {
      if (!reuseDraft || event.key !== "Enter") return;
      event.preventDefault();
    });
  });
  document.getElementById("studio-clip-menu")?.addEventListener("keydown", (event) => {
    if (event.key === "Escape" || event.key === "Tab") {
      event.preventDefault();
      hideClipMenu();
      return;
    }
    if (
      event.key !== "ArrowDown" &&
      event.key !== "ArrowUp" &&
      event.key !== "Home" &&
      event.key !== "End"
    ) {
      return;
    }
    const menu = document.getElementById("studio-clip-menu");
    const items = menu ? visibleClipMenuItems(menu) : [];
    if (!items.length) return;
    event.preventDefault();
    const current = items.indexOf(document.activeElement);
    let next = 0;
    if (event.key === "End") next = items.length - 1;
    else if (event.key === "ArrowDown") next = current < 0 ? 0 : (current + 1) % items.length;
    else if (event.key === "Home") next = 0;
    else next = current < 0 ? items.length - 1 : (current - 1 + items.length) % items.length;
    items[next].focus();
  });
  document.addEventListener("click", (event) => {
    const menu = document.getElementById("studio-clip-menu");
    if (menu && menu.contains(event.target)) return;
    hideClipMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideClipMenu();
    if (event.key === "Escape" && reuseDraft) cancelReuseDraft();
    if (event.key !== "Delete") return;
    if (reuseDraft) return;
    if (event.ctrlKey || event.altKey || event.metaKey) return;
    if (isTextEditingTarget(document.activeElement)) return;
    if (deleteSelectedEffectBar()) {
      event.preventDefault();
      return;
    }
    if (privacyMaskDeleteActive()) return;
    if (!storyClipDeleteContext(document.activeElement)) return;
    if (!selectedStoryClip()) return;
    event.preventDefault();
    removeSelectedStoryClip();
  });
  window.addEventListener("scroll", hideClipMenu, true);

  document.addEventListener("keydown", (event) => {
    if (!event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return;
    const key = event.key.toLowerCase();
    if (key !== "z" && key !== "y") return;
    if (isTextEditingTarget(document.activeElement)) return;
    if (reuseDraft) {
      event.preventDefault();
      return;
    }
    event.preventDefault();
    if (key === "z") applyStudioHistory("undo");
    else applyStudioHistory("redo");
  });

  root.addEventListener("click", (event) => {
    const opener = event.target.closest && event.target.closest("[data-open-original]");
    if (opener) {
      const row = opener.closest(".studio-original-item");
      if (row) openOriginalDraft(row);
      return;
    }
    const pick = event.target.closest && event.target.closest("[data-select-clip]");
    if (pick) {
      let seekTimeS = null;
      if (timelineCanvasEl) {
        seekTimeS = xToTime(event.clientX - timelineCanvasEl.getBoundingClientRect().left);
      }
      selectClip(pick.getAttribute("data-select-clip"), { seekTimeS });
      return;
    }
    const transition = event.target.closest && event.target.closest(".studio-transition");
    if (transition) {
      selectTransition(transition);
      return;
    }
    const transport = event.target.closest && event.target.closest("[data-transport]");
    if (transport) {
      const action = transport.getAttribute("data-transport");
      const list = clips().filter((c) => clipDuration(c) > 0);
      if (action === "toggle") {
        if (reuseDraft) {
          toggleReusePreview();
          return;
        }
        if (state.playing) pausePlayback();
        else startPlayback();
        return;
      }
      if (action === "fullscreen" && previewFrame) {
        if (!document.fullscreenElement) {
          previewFrame.requestFullscreen?.().catch(() => {});
        } else {
          document.exitFullscreen?.().catch(() => {});
        }
        return;
      }
      if (reuseDraft) return;
      const wasPlaying = state.playing;
      if (wasPlaying) pausePlayback();
      if (action === "start") setProjectTime(0);
      else if (action === "end") setProjectTime(totalDuration());
      else if (action === "prev") {
        const hit = resolveAt(state.projectTimeS);
        if (!hit) return;
        if (state.projectTimeS > hit.start + 0.2) setProjectTime(hit.start);
        else {
          const idx = list.indexOf(hit.clip);
          if (idx > 0) setProjectTime(clipStartTime(list[idx - 1]));
          else setProjectTime(0);
        }
      } else if (action === "next") {
        const hit = resolveAt(state.projectTimeS);
        if (!hit) return;
        const idx = list.indexOf(hit.clip);
        if (idx >= 0 && idx < list.length - 1) setProjectTime(clipStartTime(list[idx + 1]));
        else setProjectTime(totalDuration());
      } else if (action === "cut") {
        cutSelectedAtPlayhead();
        return;
      } else if (action === "remove") {
        removeSelectedStoryClip();
        return;
      }
      if (wasPlaying && state.projectTimeS < totalDuration() - 0.001) startPlayback();
    }
  });

  if (titleInput) {
    titleInput.addEventListener("input", () => {
      state.title = titleInput.value;
      scheduleTitleSave();
    });
    titleInput.addEventListener("change", () => {
      if (titleSaveTimer) {
        window.clearTimeout(titleSaveTimer);
        titleSaveTimer = 0;
      }
      persistProjectTitle();
    });
  }

  if (volumeInput) {
    volumeInput.addEventListener("input", () => {
      state.volume = Number(volumeInput.value) / 100;
      applyVolume();
      persistUiState();
    });
  }

  document.getElementById("studio-export-open")?.addEventListener("click", () => {
    openExportDialog();
  });
  document.getElementById("studio-export-open-file")?.addEventListener("click", () => {
    requestExportAction("open");
  });
  document.getElementById("studio-export-reveal-file")?.addEventListener("click", () => {
    requestExportAction("reveal");
  });
  document.getElementById("studio-export-success-dismiss")?.addEventListener("click", () => {
    hideExportSuccess();
  });

  const exportResolution = document.getElementById("studio-export-resolution");
  const exportQuality = document.getElementById("studio-export-quality");
  const exportFilename = document.getElementById("studio-export-filename");
  let exportFilenameAuto = "";
  const exportStatus = document.getElementById("studio-export-status");
  const exportHint = document.getElementById("studio-export-hint");
  const exportRunBtn = document.getElementById("studio-export-run");
  const exportCancelBtn = document.getElementById("studio-export-cancel");
  const exportProgress = document.getElementById("studio-export-progress");
  const exportProgressBar = document.getElementById("studio-export-progress-bar");
  const exportProgressEl = document.getElementById("studio-export-progressbar");
  const exportProgressLabel = document.getElementById("studio-export-progress-label");
  const exportProgressMeta = document.getElementById("studio-export-progress-meta");
  let exportOptionsCache = null;
  let exportPollTimer = null;
  let exportElapsedTimer = null;
  let exportStartedAtMs = 0;
  let exportLastJob = null;
  let exportActiveJobId = null;
  let exportCancelRequested = false;

  function setExportStatus(message, { error = false } = {}) {
    if (!exportStatus) return;
    if (!message) {
      exportStatus.hidden = true;
      exportStatus.textContent = "";
      return;
    }
    exportStatus.hidden = false;
    exportStatus.textContent = message;
    exportStatus.classList.toggle("is-error", !!error);
  }

  function setExportProgressVisible(visible) {
    if (!exportProgress) return;
    exportProgress.hidden = !visible;
    if (!visible) {
      exportProgress.classList.remove("is-working");
    }
  }

  function formatExportDuration(totalSeconds) {
    const sec = Math.max(0, Math.round(Number(totalSeconds) || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) {
      return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    }
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function exportPhaseLabel(job) {
    if (job.phase === "preparing") return msgExportPreparing;
    if (job.phase === "concat") return msgExportCombining;
    if (job.phase === "mixing") return msgExportMixing;
    if (job.phase === "done" || job.state === "completed") return msgExportDone;
    if (job.phase === "rendering") {
      const current = Number(job.clip_index) || 0;
      const total = Number(job.clip_total) || 0;
      let label = msgExportClip
        .replace("{current}", String(current))
        .replace("{total}", String(total));
      if (job.current_label) {
        label = `${label} · ${job.current_label}`;
      }
      return label;
    }
    return msgExportRunning;
  }

  function updateExportProgress(job, { localElapsedS = null } = {}) {
    exportLastJob = job;
    const percent = Math.max(0, Math.min(100, Number(job.percent) || 0));
    if (exportProgressBar) exportProgressBar.style.width = `${percent}%`;
    if (exportProgressEl) exportProgressEl.setAttribute("aria-valuenow", String(percent));
    if (exportProgress) {
      exportProgress.classList.toggle(
        "is-working",
        job.state === "running" || job.state === "pending"
      );
    }
    const primary = `${exportPhaseLabel(job)} (${percent}%)`;
    if (exportProgressLabel) exportProgressLabel.textContent = primary;

    const elapsed =
      localElapsedS != null
        ? localElapsedS
        : Number(job.elapsed_s) || 0;
    const elapsedText = msgExportElapsed.replace(
      "{time}",
      formatExportDuration(elapsed)
    );
    if (exportProgressMeta) {
      // One time only. Elapsed while encoding; total time once the job is done.
      exportProgressMeta.textContent =
        job.state === "completed"
          ? msgExportDoneIn.replace("{time}", formatExportDuration(elapsed))
          : elapsedText;
    }
  }

  function setExportRunningUi(running) {
    if (exportRunBtn) exportRunBtn.disabled = running;
    if (exportResolution) exportResolution.disabled = running;
    if (exportQuality) exportQuality.disabled = running;
    if (exportFilename) exportFilename.disabled = running;
    if (exportCancelBtn && !exportCancelRequested) exportCancelBtn.disabled = false;
  }

  function suggestionForHeight(height) {
    const options =
      exportOptionsCache && Array.isArray(exportOptionsCache.options)
        ? exportOptionsCache.options
        : [];
    const match = options.find((opt) => Number(opt.height) === Number(height));
    if (match && match.suggested_filename) return String(match.suggested_filename);
    if (exportOptionsCache && exportOptionsCache.suggested_filename) {
      return String(exportOptionsCache.suggested_filename);
    }
    return "export.mp4";
  }

  function refreshExportHint() {
    if (!exportHint || !exportOptionsCache) return;
    const name =
      (exportFilename && exportFilename.value.trim()) ||
      suggestionForHeight(exportResolution ? exportResolution.value : null);
    exportHint.textContent = `${name} → ${exportOptionsCache.default_directory || ""}`;
  }

  function syncExportFilename(height, { reset = false } = {}) {
    const next = suggestionForHeight(height);
    const current = exportFilename ? exportFilename.value.trim() : "";
    if (exportFilename && (reset || !current || current === exportFilenameAuto)) {
      exportFilename.value = next;
      exportFilenameAuto = next;
    }
    refreshExportHint();
  }

  function chosenExportFilename(height) {
    const typed = exportFilename ? exportFilename.value.trim() : "";
    return typed || suggestionForHeight(height);
  }

  function stopExportElapsedTimer() {
    if (exportElapsedTimer) {
      window.clearInterval(exportElapsedTimer);
      exportElapsedTimer = null;
    }
  }

  function startExportElapsedTimer() {
    stopExportElapsedTimer();
    exportStartedAtMs = Date.now();
    exportElapsedTimer = window.setInterval(() => {
      if (!exportLastJob) return;
      const localElapsedS = (Date.now() - exportStartedAtMs) / 1000;
      updateExportProgress(exportLastJob, { localElapsedS });
    }, 1000);
  }

  function hideExportSuccess() {
    const banner = document.getElementById("studio-export-success");
    if (banner) banner.hidden = true;
  }

  function setExportSuccessError(message) {
    const errEl = document.getElementById("studio-export-success-error");
    if (!errEl) return;
    if (!message) {
      errEl.hidden = true;
      errEl.textContent = "";
      return;
    }
    errEl.hidden = false;
    errEl.textContent = message;
  }

  function showExportSuccess(job) {
    const banner = document.getElementById("studio-export-success");
    const titleEl = document.getElementById("studio-export-success-title");
    const pathEl = document.getElementById("studio-export-success-path");
    const openBtn = document.getElementById("studio-export-open-file");
    const revealBtn = document.getElementById("studio-export-reveal-file");
    if (!banner || !titleEl) return;
    const filename = job.filename || (job.output_path || "").split(/[/\\]/).pop() || "export.mp4";
    titleEl.textContent = msgExportSuccess.replace("{filename}", filename);
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
    setExportSuccessError("");
    if (openBtn) openBtn.hidden = job.open_available === false;
    if (revealBtn) revealBtn.hidden = job.reveal_available === false;
    banner.hidden = false;
  }

  async function requestExportAction(action) {
    const unavailable =
      action === "open" ? msgExportOpenUnavailable : msgExportRevealUnavailable;
    try {
      const res = await fetch(`/api/studio/export/${action}`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => null);
      if (res.status === 503) {
        setExportSuccessError(unavailable);
        return;
      }
      if (!res.ok || !data || data.ok === false) {
        setExportSuccessError(
          (data && data.detail) || msgExportFileMissing
        );
        return;
      }
      setExportSuccessError("");
    } catch (_) {
      setExportSuccessError(msgExportFileMissing);
    }
  }

  function stopExportPoll() {
    if (exportPollTimer) {
      window.clearTimeout(exportPollTimer);
      exportPollTimer = null;
    }
    stopExportElapsedTimer();
  }

  function pollExportJob(jobId) {
    stopExportPoll();
    startExportElapsedTimer();
    const tick = async () => {
      try {
        const res = await fetch(`/api/studio/export/jobs/${encodeURIComponent(jobId)}`, {
          headers: { Accept: "application/json" },
        });
        const data = await res.json().catch(() => null);
        if (res.status === 404) {
          stopExportElapsedTimer();
          setExportStatus(msgExportFailed, { error: true });
          setExportRunningUi(false);
          setExportProgressVisible(false);
          return;
        }
        if (!res.ok || !data || !data.ok) {
          stopExportElapsedTimer();
          setExportStatus((data && data.detail) || msgExportFailed, { error: true });
          setExportRunningUi(false);
          return;
        }
        setExportProgressVisible(true);
        const localElapsedS = (Date.now() - exportStartedAtMs) / 1000;
        updateExportProgress(data, { localElapsedS });
        if (data.state === "cancelled") {
          stopExportElapsedTimer();
          exportActiveJobId = null;
          exportCancelRequested = false;
          if (exportProgress) exportProgress.classList.remove("is-working");
          setExportProgressVisible(false);
          setExportStatus(msgExportCancelled);
          setExportRunningUi(false);
          return;
        }
        if (data.phase === "cancelling") {
          setExportStatus(msgExportCancelling);
          if (exportCancelBtn) exportCancelBtn.disabled = true;
          exportPollTimer = window.setTimeout(tick, 400);
          return;
        }
        if (data.state === "completed") {
          stopExportElapsedTimer();
          exportActiveJobId = null;
          exportCancelRequested = false;
          if (exportProgress) exportProgress.classList.remove("is-working");
          setExportRunningUi(false);
          if (exportDialog && typeof exportDialog.close === "function") {
            exportDialog.close();
          }
          showExportSuccess(data);
          if (exportOptionsCache) {
            exportOptionsCache.default_directory =
              data.directory || exportOptionsCache.default_directory;
            exportOptionsCache.last_export_directory = data.directory || null;
          }
          return;
        }
        if (data.state === "failed") {
          stopExportElapsedTimer();
          exportActiveJobId = null;
          exportCancelRequested = false;
          if (exportProgress) exportProgress.classList.remove("is-working");
          setExportStatus(data.error || msgExportFailed, { error: true });
          setExportRunningUi(false);
          return;
        }
        setExportStatus(msgExportRunningHint);
        exportPollTimer = window.setTimeout(tick, 400);
      } catch (_) {
        exportPollTimer = window.setTimeout(tick, 1000);
      }
    };
    tick();
  }

  async function openExportDialog() {
    if (!exportDialog) return;
    hideExportSuccess();
    stopExportPoll();
    exportLastJob = null;
    exportActiveJobId = null;
    exportCancelRequested = false;
    setExportStatus("");
    setExportProgressVisible(false);
    if (exportProgressBar) exportProgressBar.style.width = "0%";
    if (exportProgressLabel) exportProgressLabel.textContent = "";
    if (exportProgressMeta) exportProgressMeta.textContent = "";
    if (exportHint) exportHint.textContent = "";
    setExportRunningUi(false);
    if (exportRunBtn) exportRunBtn.disabled = true;
    if (exportResolution) exportResolution.innerHTML = "";
    exportFilenameAuto = "";
    if (exportFilename) exportFilename.value = "";
    exportDialog.showModal();
    try {
      const qs = projectId ? `?project_id=${encodeURIComponent(String(projectId))}` : "";
      const res = await fetch(`/api/studio/export/options${qs}`, {
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        setExportStatus((data && data.detail) || msgExportFailed, { error: true });
        return;
      }
      exportOptionsCache = data;
      const options = Array.isArray(data.options) ? data.options : [];
      if (!options.length) {
        setExportStatus(msgExportNoRes, { error: true });
        if (exportHint) {
          exportHint.textContent = msgExportNoRes;
        }
        return;
      }
      if (exportResolution) {
        options.forEach((opt) => {
          const option = document.createElement("option");
          option.value = String(opt.height);
          const rec =
            opt.recommended || Number(opt.height) === Number(data.default_height)
              ? ` (${recommendedLabel})`
              : "";
          option.textContent = `${opt.label}${rec}`;
          if (Number(opt.height) === Number(data.default_height)) option.selected = true;
          exportResolution.appendChild(option);
        });
      }
      if (exportQuality && data.default_quality) {
        exportQuality.value = String(data.default_quality);
        if (exportQuality.value !== String(data.default_quality)) {
          exportQuality.value = "high";
        }
      }
      syncExportFilename(
        exportResolution ? exportResolution.value : data.default_height,
        { reset: true }
      );
      if (exportRunBtn) exportRunBtn.disabled = false;
    } catch (_) {
      setExportStatus(msgExportFailed, { error: true });
    }
  }

  async function runStudioExport() {
    if (!exportOptionsCache || !exportResolution || !exportRunBtn) return;
    const height = Number(exportResolution.value);
    if (!Number.isFinite(height) || height <= 0) {
      setExportStatus(msgExportNoRes, { error: true });
      return;
    }
    setExportRunningUi(true);
    setExportStatus(msgExportRunningHint);
    setExportProgressVisible(false);
    let pickedPath = null;
    try {
      const pickRes = await fetch("/api/desktop/pick-save-file", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          directory: exportOptionsCache.default_directory || "",
          filename: chosenExportFilename(height),
        }),
      });
      const pickData = await pickRes.json().catch(() => null);
      if (pickRes.status === 503) {
        setExportStatus(msgExportUnavailable, { error: true });
        setExportRunningUi(false);
        return;
      }
      if (!pickData || pickData.status === "cancelled") {
        setExportStatus(msgExportCancelled);
        setExportRunningUi(false);
        return;
      }
      if (pickData.status !== "ok" || !pickData.path) {
        setExportStatus(msgExportFailed, { error: true });
        setExportRunningUi(false);
        return;
      }
      pickedPath = pickData.path;
    } catch (_) {
      setExportStatus(msgExportFailed, { error: true });
      setExportRunningUi(false);
      return;
    }

    const tryStart = async () => {
      const res = await fetch("/api/studio/export", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          height,
          quality: exportQuality ? exportQuality.value : "high",
          output_path: pickedPath,
          project_id: projectId || exportOptionsCache.project_id || null,
        }),
      });
      const data = await res.json().catch(() => null);
      return { res, data };
    };

    try {
      const { res, data } = await tryStart();
      if (!res.ok || !data || !data.ok || !data.job_id) {
        setExportStatus((data && data.detail) || msgExportFailed, { error: true });
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
      setExportStatus(msgExportRunningHint);
      exportActiveJobId = data.job_id;
      exportCancelRequested = false;
      pollExportJob(data.job_id);
    } catch (_) {
      setExportStatus(msgExportFailed, { error: true });
      setExportRunningUi(false);
    }
  }

  exportResolution?.addEventListener("change", () => {
    syncExportFilename(exportResolution.value);
  });
  exportFilename?.addEventListener("input", () => {
    refreshExportHint();
  });

  exportRunBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    runStudioExport();
  });

  async function requestExportCancel() {
    if (!exportActiveJobId || exportCancelRequested) return;
    exportCancelRequested = true;
    if (exportCancelBtn) exportCancelBtn.disabled = true;
    setExportStatus(msgExportCancelling);
    try {
      const res = await fetch(
        `/api/studio/export/jobs/${encodeURIComponent(exportActiveJobId)}/cancel`,
        { method: "POST", headers: { Accept: "application/json" } }
      );
      if (!res.ok) {
        exportCancelRequested = false;
        if (exportCancelBtn) exportCancelBtn.disabled = false;
      }
    } catch (_) {
      exportCancelRequested = false;
      if (exportCancelBtn) exportCancelBtn.disabled = false;
    }
  }

  exportCancelBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    if (exportActiveJobId) {
      requestExportCancel();
      return;
    }
    stopExportPoll();
    if (exportDialog && typeof exportDialog.close === "function") exportDialog.close();
  });
  exportDialog?.addEventListener("cancel", (event) => {
    if (!exportActiveJobId) return;
    event.preventDefault();
    requestExportCancel();
  });

  document.getElementById("studio-music-add")?.addEventListener("click", (event) => {
    event.stopPropagation();
    addMusicTrack();
  });
  const musicClipsEl = document.getElementById("studio-music-clips");
  musicClipsEl?.addEventListener("click", (event) => {
    if (event.target.closest(".studio-drag-handle, .studio-music-start-handle")) return;
    const card = event.target.closest(".studio-music-select");
    if (!card) return;
    event.stopPropagation();
    selectMusic(card.dataset.musicId);
  });
  musicClipsEl?.addEventListener("pointerdown", (event) => {
    const handle =
      event.target.closest && event.target.closest(".studio-music-start-handle");
    if (handle) beginMusicStartDrag(event, handle);
  });
  musicClipsEl?.addEventListener("dragstart", (event) => {
    const handle = event.target.closest && event.target.closest(".studio-drag-handle");
    if (!handle) {
      event.preventDefault();
      return;
    }
    const card = handle.closest(".studio-music-select");
    if (!card) return;
    musicDragCard = card;
    musicDragOrderBefore = musicClipEls().map((el) => Number(el.dataset.musicId));
    card.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    try {
      event.dataTransfer.setData("text/plain", card.dataset.musicId || "");
    } catch (_) {
      /* older WebViews */
    }
  });
  musicClipsEl?.addEventListener("dragend", () => {
    if (musicDragCard) musicDragCard.classList.remove("is-dragging");
    musicDragCard = null;
    syncTracksFromMusicDom();
    persistMusicOrder();
  });
  musicClipsEl?.addEventListener("dragover", (event) => {
    if (!musicDragCard || !musicClipsEl) return;
    event.preventDefault();
    const target = event.target.closest && event.target.closest(".studio-music-select");
    if (target && target !== musicDragCard) {
      const rect = target.getBoundingClientRect();
      if (event.clientX < rect.left + rect.width / 2) {
        musicClipsEl.insertBefore(musicDragCard, target);
      } else {
        musicClipsEl.insertBefore(musicDragCard, target.nextSibling);
      }
      syncTracksFromMusicDom();
      layoutMusicSpans();
    }
  });
  musicClipsEl?.addEventListener("drop", (event) => {
    event.preventDefault();
  });
  document.getElementById("inspector-music-replace")?.addEventListener("click", (event) => {
    event.preventDefault();
    replaceSelectedMusic();
  });
  document.getElementById("inspector-music-remove")?.addEventListener("click", clearMusic);
  document.getElementById("inspector-music-move-up")?.addEventListener("click", (event) => {
    event.preventDefault();
    moveSelectedMusic(-1);
  });
  document.getElementById("inspector-music-move-down")?.addEventListener("click", (event) => {
    event.preventDefault();
    moveSelectedMusic(1);
  });
  const onMusicDuration = (event) => {
    const el = event.target;
    if (!el || !(Number.isFinite(el.duration) && el.duration > 0)) return;
    const src = el.getAttribute("src");
    state.tracks.forEach((track) => {
      if (track.streamUrl && track.streamUrl === src) track.durationS = el.duration;
    });
    layoutTimeline();
  };
  [musicAudio, musicAudioNext].forEach((el) => {
    if (!el) return;
    el.addEventListener("loadedmetadata", onMusicDuration);
    el.addEventListener("durationchange", onMusicDuration);
  });

  async function addTitleCard() {
    try {
      const res = await fetch("/api/studio/title-cards", {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const body = await readJson(res);
      if (!res.ok || !body || !body.id) {
        throw new Error((body && body.detail) || msgTitleCardFailed);
      }
      window.location.assign(`/studio?select=${body.id}&focus=title`);
    } catch (err) {
      showRootFlash(err.message || msgTitleCardFailed);
    }
  }

  document.getElementById("studio-add-title-card")?.addEventListener("click", addTitleCard);
  document.getElementById("studio-add-title-card-empty")?.addEventListener("click", addTitleCard);

  async function persistTitlecard() {
    const clip = clips().find(
      (c) => state.selected.type === "clip" && String(c.dataset.studioId) === String(state.selected.id)
    );
    if (!clip || clip.dataset.kind !== "title_card") return;
    const titleEl = document.getElementById("inspector-titlecard-title");
    const subEl = document.getElementById("inspector-titlecard-subtitle");
    const durEl = document.getElementById("inspector-titlecard-duration");
    const bgEl = document.querySelector('input[name="inspector-titlecard-bg"]:checked');
    const payload = {
      title: titleEl ? titleEl.value : "",
      subtitle: subEl ? subEl.value : "",
      duration_s: durEl ? Number(durEl.value) : 3,
      background: bgEl ? bgEl.value : "dark",
    };
    try {
      const res = await fetch(`/api/studio/${clip.dataset.studioId}/title-card`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await readJson(res);
      if (!res.ok) throw new Error((body && body.detail) || msgTitleCardFailed);
      clip.dataset.title = payload.title;
      clip.dataset.subtitle = payload.subtitle;
      clip.dataset.background = payload.background;
      const durationS =
        body.duration_s != null ? Number(body.duration_s) : Number(payload.duration_s);
      clip.dataset.effectiveDuration = String(durationS);
      clip.style.setProperty("--clip-flex", durationS.toFixed(4));
      clip.dataset.displayTitle = body.display_title || payload.title;
      clip.dataset.displaySubtitle = body.display_subtitle || payload.subtitle;
      const caption = clip.querySelector(".studio-clip-caption strong");
      if (caption) caption.textContent = clip.dataset.displayTitle || "";
      const swatch = clip.querySelector(".studio-titlecard-swatch");
      if (swatch) swatch.setAttribute("data-bg", payload.background);
      const durLabel = clip.querySelector("[data-clip-duration]");
      if (durLabel && Number.isFinite(durationS)) {
        durLabel.textContent = `${durationS.toFixed(1)}s`;
      }
      const browserRow = document.querySelector(
        `#studio-browser-story [data-studio-id="${clip.dataset.studioId}"]`
      );
      if (browserRow) {
        const browserCaption = browserRow.querySelector(".studio-browser-meta strong");
        if (browserCaption) browserCaption.textContent = clip.dataset.displayTitle || "";
        const browserSwatch = browserRow.querySelector(".studio-titlecard-swatch");
        if (browserSwatch) browserSwatch.setAttribute("data-bg", payload.background);
      }
      if (body.summary && body.summary.estimated_total_s != null) {
        root.dataset.totalS = String(body.summary.estimated_total_s);
        root.dataset.totalLabel = body.summary.estimated_total_label || formatTime(body.summary.estimated_total_s);
      }
      if (reloadIfForwardLoop()) return;
      syncPreviewMedia();
      refreshAppliedTransitions();
      layoutTimeline();
      setSaveState(true);
    } catch (err) {
      showRootFlash(err.message || msgTitleCardFailed);
    }
  }

  ["inspector-titlecard-title", "inspector-titlecard-subtitle"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", persistTitlecard);
  });
  document.getElementById("inspector-titlecard-duration")?.addEventListener("change", persistTitlecard);
  document.querySelectorAll('input[name="inspector-titlecard-bg"]').forEach((el) => {
    el.addEventListener("change", persistTitlecard);
  });

  document.getElementById("inspector-transition-type")?.addEventListener("change", (event) => {
    const value = event.target.value;
    if (state.selected.type !== "transition" || !state.selected.id) return;
    const durWrap = document.getElementById("inspector-transition-duration-wrap");
    if (durWrap) durWrap.hidden = value === "cut";
    persistTransition();
  });
  document.getElementById("inspector-transition-duration")?.addEventListener("change", () => {
    persistTransition();
  });

  async function persistTransition() {
    if (state.selected.type !== "transition" || !state.selected.id) return;
    const select = document.getElementById("inspector-transition-type");
    const durInput = document.getElementById("inspector-transition-duration");
    const payload = {
      type: select ? select.value : "cut",
      duration_s: durInput ? Number(durInput.value) : 0.5,
    };
    try {
      const res = await fetch(`/api/studio/${state.selected.id}/transition`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await readJson(res);
      if (!res.ok) throw new Error((body && body.detail) || msgTransitionFailed);
      const clip = clips().find((c) => String(c.dataset.studioId) === String(state.selected.id));
      if (clip) {
        clip.dataset.transitionType = body.type || payload.type;
        clip.dataset.transitionDuration =
          body.duration_s == null ? "" : String(body.duration_s);
        clip.dataset.appliedType = body.applied_type || "cut";
        clip.dataset.appliedDuration = String(body.applied_duration_s || 0);
        clip.dataset.fallbackCut = body.fallback_cut ? "1" : "0";
        const flex =
          clipDuration(clip) -
          ((body.applied_type === "crossfade" ? Number(body.applied_duration_s) : 0) || 0);
        clip.style.setProperty("--clip-flex", String(Math.max(0, flex).toFixed(4)));
      }
      const chip = grid.querySelector(
        `.studio-transition[data-transition-after="${state.selected.id}"]`
      );
      if (chip) {
        chip.dataset.storedType = body.type || payload.type;
        chip.dataset.storedDuration =
          body.duration_s == null ? "" : String(body.duration_s);
        chip.dataset.appliedType = body.applied_type || "cut";
        chip.dataset.appliedDuration = String(body.applied_duration_s || 0);
        chip.dataset.fallbackCut = body.fallback_cut ? "1" : "0";
        chip.dataset.clamped = body.clamped ? "1" : "0";
        chip.dataset.transitionType = body.applied_type || "cut";
        refreshTransitionChrome(chip);
        selectTransition(chip);
      }
      if (body.summary && body.summary.estimated_total_s != null) {
        root.dataset.totalS = String(body.summary.estimated_total_s);
        root.dataset.totalLabel = body.summary.estimated_total_label || formatTime(body.summary.estimated_total_s);
      }
      if (reloadIfForwardLoop()) return;
      layoutTimeline();
      syncPreviewMedia();
      setSaveState(true);
    } catch (err) {
      showRootFlash(err.message || msgTransitionFailed);
    }
  }

  IMAGE_ADJUST_FIELDS.forEach(([, inputId]) => {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener("input", () => {
      const clip = selectedAdjustableClip();
      if (!clip) return;
      clearQuickLookLabel(clip);
      writeImageAdjust(clip, imageAdjustFromControls());
      applyPreviewGrades(resolveAt(state.projectTimeS));
      setSaveState(false);
    });
    input.addEventListener("change", () => {
      const clip = selectedAdjustableClip();
      if (!clip) return;
      clearQuickLookLabel(clip);
      writeImageAdjust(clip, imageAdjustFromControls());
      queueImageAdjustSave(clip);
    });
  });

  document.getElementById("inspector-quick-look")?.addEventListener("change", async (event) => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    try {
      await applyQuickLook(clip, event.target.value || "");
    } catch (err) {
      showFlash((err && err.message) || msgLookFailed);
      fillImageAdjust(clip);
    }
  });

  document.getElementById("inspector-look-compare")?.addEventListener("change", (event) => {
    compareBeforeAfter = Boolean(event.target.checked);
    applyPreviewGrades(resolveAt(state.projectTimeS));
  });

  ["inspector-detail-sharpen", "inspector-detail-denoise"].forEach((inputId) => {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener("input", () => {
      const clip = selectedAdjustableClip();
      if (!clip) return;
      const sharpen = document.getElementById("inspector-detail-sharpen");
      const denoise = document.getElementById("inspector-detail-denoise");
      const detail = {
        sharpen: clampDetailSlider(sharpen && sharpen.value),
        denoise: clampDetailSlider(denoise && denoise.value),
      };
      writeDetail(clip, detail);
      fillDetail(clip);
      setSaveState(false);
    });
    input.addEventListener("change", () => {
      const clip = selectedAdjustableClip();
      if (!clip) return;
      queueDetailSave(clip);
    });
  });

  document.getElementById("inspector-detail-reset")?.addEventListener("click", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    writeDetail(clip, neutralDetail());
    fillDetail(clip);
    setSaveState(false);
    queueDetailSave(clip);
  });

  document.getElementById("mask-add-blur")?.addEventListener("click", () => addPrivacyMask("blur"));
  document.getElementById("mask-add-pixelate")?.addEventListener("click", () => {
    addPrivacyMask("pixelate");
  });
  document.getElementById("mask-remove")?.addEventListener("click", () => removeSelectedMask());
  bindInspectorChrome();
  document.getElementById("mask-effect")?.addEventListener("change", (event) => {
    replaceSelectedMask({ effect: event.target.value });
  });
  document.getElementById("mask-strength")?.addEventListener("input", (event) => {
    const clip = selectedAdjustableClip();
    if (!clip || !selectedMaskId) return;
    const strength = clampMaskStrength(event.target.value);
    const valueEl = document.getElementById("mask-strength-value");
    if (valueEl) valueEl.textContent = String(strength);
    const masks = readMasks(clip).map((item) =>
      item.id === selectedMaskId ? clampMaskBox({ ...item, strength }) : item
    );
    writeMasks(clip, masks);
    drawPrivacyMasks();
  });
  document.getElementById("mask-strength")?.addEventListener("change", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    queueMaskSave(clip);
  });
  window.addEventListener("resize", () => {
    drawPrivacyMasks();
    drawFlightMap(resolveAt(state.projectTimeS));
  });
  previewImage?.addEventListener("load", () => drawPrivacyMasks());
  previewVideo?.addEventListener("seeked", () => drawPrivacyMasks());
  previewVideo?.addEventListener("loadeddata", () => drawPrivacyMasks());
  document.getElementById("inspector-image-reset")?.addEventListener("click", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    writeImageAdjust(clip, neutralImageAdjust());
    fillImageAdjust(clip);
    applyPreviewGrades(resolveAt(state.projectTimeS));
    setSaveState(false);
    queueImageAdjustSave(clip);
  });

  HSL_FIELDS.forEach(([, inputId]) => {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener("input", () => {
      const clip = selectedAdjustableClip();
      if (!clip) return;
      writeHsl(clip, hslRangeFromControls(clip));
      applyPreviewGrades(resolveAt(state.projectTimeS));
      setSaveState(false);
    });
    input.addEventListener("change", () => {
      const clip = selectedAdjustableClip();
      if (!clip) return;
      writeHsl(clip, hslRangeFromControls(clip));
      queueHslSave(clip);
    });
  });

  document.querySelectorAll("[data-hsl-range]").forEach((button) => {
    button.addEventListener("click", () => {
      const clip = selectedAdjustableClip();
      if (!clip) return;
      if (clip.dataset.hslPreviewDirty === "1") queueHslSave(clip);
      selectedHslRange = button.dataset.hslRange || "red";
      fillHsl(clip);
    });
  });

  document.getElementById("inspector-hsl-reset")?.addEventListener("click", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    const hsl = readHsl(clip);
    hsl.ranges[selectedHslRange] = neutralHslRange();
    writeHsl(clip, hsl);
    fillHsl(clip);
    applyPreviewGrades(resolveAt(state.projectTimeS));
    setSaveState(false);
    queueHslSave(clip);
  });

  document.getElementById("inspector-hsl-reset-all")?.addEventListener("click", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    writeHsl(clip, neutralHslAdjust());
    fillHsl(clip);
    applyPreviewGrades(resolveAt(state.projectTimeS));
    setSaveState(false);
    queueHslSave(clip);
  });

  document.querySelectorAll("[data-color-wheel]").forEach((wheelElement) => {
    const wheelId = wheelElement.dataset.colorWheel;
    let dragging = false;

    wheelElement.addEventListener("pointerdown", (event) => {
      if (event.button !== undefined && event.button !== 0) return;
      const clip = selectedAdjustableClip();
      if (!clip) return;
      dragging = true;
      wheelElement.classList.add("is-dragging");
      try {
        wheelElement.setPointerCapture(event.pointerId);
      } catch (_) {
        /* ignore */
      }
      updateColorWheelFromPointer(clip, wheelId, wheelElement, event.clientX, event.clientY);
      event.preventDefault();
    });

    wheelElement.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      const clip = selectedAdjustableClip();
      if (!clip) return;
      updateColorWheelFromPointer(clip, wheelId, wheelElement, event.clientX, event.clientY);
      event.preventDefault();
    });

    const finishDrag = (event) => {
      if (!dragging) return;
      dragging = false;
      wheelElement.classList.remove("is-dragging");
      try {
        wheelElement.releasePointerCapture(event.pointerId);
      } catch (_) {
        /* ignore */
      }
      const clip = selectedAdjustableClip();
      if (!clip) return;
      applyPreviewGrades(resolveAt(state.projectTimeS));
      queueColorWheelsSave(clip);
    };
    wheelElement.addEventListener("pointerup", finishDrag);
    wheelElement.addEventListener("pointercancel", finishDrag);

    wheelElement.addEventListener("keydown", (event) => {
      const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"];
      if (!keys.includes(event.key)) return;
      const clip = selectedAdjustableClip();
      if (!clip) return;
      event.preventDefault();
      const colorWheels = readColorWheels(clip);
      const point = { ...(colorWheels.wheels[wheelId] || neutralColorWheelPoint()) };
      const step = event.shiftKey ? 0.002 : 0.02;
      if (event.key === "ArrowLeft") point.x -= step;
      if (event.key === "ArrowRight") point.x += step;
      if (event.key === "ArrowUp") point.y -= step;
      if (event.key === "ArrowDown") point.y += step;
      colorWheels.wheels[wheelId] = normalizeColorWheelPoint(point);
      writeColorWheels(clip, colorWheels);
      fillColorWheels(clip);
      setSaveState(false);
      queueColorWheelsSave(clip);
    });
  });

  COLOR_WHEEL_IDS.forEach((wheelId) => {
    document.getElementById(`color-wheel-reset-${wheelId}`)?.addEventListener("click", () => {
      const clip = selectedAdjustableClip();
      if (!clip) return;
      const colorWheels = readColorWheels(clip);
      colorWheels.wheels[wheelId] = neutralColorWheelPoint();
      writeColorWheels(clip, colorWheels);
      fillColorWheels(clip);
      applyPreviewGrades(resolveAt(state.projectTimeS));
      setSaveState(false);
      queueColorWheelsSave(clip);
    });
  });

  document.getElementById("inspector-color-dlog-apply")?.addEventListener("click", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    const select = document.getElementById("inspector-color-conversion-select");
    const confirm = document.getElementById("inspector-color-conversion-confirm");
    const asset = select && select.value;
    if (!asset || !(confirm && confirm.checked)) return;
    const look = readColorLook(clip);
    look.input_profile = "dlog_m";
    look.conversion_lut = asset;
    look.conversion_confirmed = true;
    writeColorLook(clip, look);
    fillColorLook(clip);
    setSaveState(false);
    queueColorLookSave(clip);
  });

  document.getElementById("inspector-color-conversion-select")?.addEventListener("change", () => {
    syncConversionApplyEnabled();
  });
  document.getElementById("inspector-color-conversion-confirm")?.addEventListener("change", () => {
    syncConversionApplyEnabled();
  });

  document.getElementById("inspector-color-conversion-add")?.addEventListener("click", async () => {
    try {
      const asset = await chooseCubeAsset();
      const select = document.getElementById("inspector-color-conversion-select");
      if (select) select.value = asset;
      syncConversionApplyEnabled();
      const clip = selectedAdjustableClip();
      if (clip) fillColorLook(clip);
    } catch (err) {
      if (err && err.message === "cancelled") return;
      showFlash((err && err.message) || msgColorLutFailed);
    }
  });

  document.getElementById("inspector-color-conversion-change")?.addEventListener("click", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    const look = readColorLook(clip);
    look.conversion_confirmed = false;
    writeColorLook(clip, look);
    fillColorLook(clip);
    const select = document.getElementById("inspector-color-conversion-select");
    if (select && look.conversion_lut) select.value = look.conversion_lut;
    syncConversionApplyEnabled();
  });

  document.getElementById("inspector-color-conversion-clear")?.addEventListener("click", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    const look = readColorLook(clip);
    look.input_profile = "rec709";
    look.conversion_lut = "";
    look.conversion_confirmed = false;
    writeColorLook(clip, look);
    fillColorLook(clip);
    setSaveState(false);
    queueColorLookSave(clip);
  });

  document.getElementById("inspector-color-creative-pick")?.addEventListener("click", async () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    try {
      const asset = await chooseCubeAsset();
      const look = readColorLook(clip);
      look.creative_lut = asset;
      if (!look.creative_strength) look.creative_strength = 100;
      writeColorLook(clip, look);
      fillColorLook(clip);
      setSaveState(false);
      queueColorLookSave(clip);
    } catch (err) {
      if (err && err.message === "cancelled") return;
      showFlash((err && err.message) || msgColorLutFailed);
    }
  });

  document.getElementById("inspector-color-creative-select")?.addEventListener("change", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    const select = document.getElementById("inspector-color-creative-select");
    const look = readColorLook(clip);
    look.creative_lut = (select && select.value) || "";
    if (!look.creative_lut) look.creative_strength = 100;
    else if (!look.creative_strength) look.creative_strength = 100;
    writeColorLook(clip, look);
    fillColorLook(clip);
    setSaveState(false);
    queueColorLookSave(clip);
  });

  document.getElementById("inspector-color-strength")?.addEventListener("input", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    const input = document.getElementById("inspector-color-strength");
    const valueEl = document.getElementById("inspector-color-strength-value");
    const look = readColorLook(clip);
    look.creative_strength = Math.max(0, Math.min(100, Math.round(Number(input && input.value) || 0)));
    if (valueEl) valueEl.textContent = String(look.creative_strength);
    writeColorLook(clip, look);
    setSaveState(false);
  });

  document.getElementById("inspector-color-strength")?.addEventListener("change", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    queueColorLookSave(clip);
  });

  function selectedVideoClip() {
    const clip = selectedAdjustableClip();
    if (!clip || clip.dataset.kind !== "video") return null;
    return clip;
  }

  function bwPartial(ramp, clip) {
    const duration = Math.max(0.1, clipDuration(clip));
    return ramp.start_s > 0.05 || ramp.end_s < duration - 0.05;
  }

  function syncBwPanels(clip) {
    const ramp = clip ? readSaturationRamp(clip) : neutralSaturationRamp();
    const on = Boolean(ramp.enabled);
    const off = document.getElementById("inspector-bw-off");
    const panel = document.getElementById("inspector-bw-on");
    const partial = document.getElementById("inspector-bw-partial");
    const fields = document.getElementById("inspector-bw-partial-fields");
    if (off) off.hidden = on;
    if (panel) panel.hidden = !on;
    const isPartial = clip ? bwPartial(ramp, clip) : false;
    if (partial) partial.checked = isPartial;
    if (fields) fields.hidden = !on || !isPartial;
  }

  function fillSaturationRamp(clip) {
    const ramp = readSaturationRamp(clip);
    const enabled = document.getElementById("inspector-bw-enabled");
    if (enabled) enabled.checked = ramp.enabled;
    const strength = document.getElementById("inspector-bw-strength");
    if (strength) strength.value = String(Math.round(100 - Number(ramp.end_saturation)));
    const start = document.getElementById("inspector-bw-start");
    const end = document.getElementById("inspector-bw-end");
    if (start) start.value = String(ramp.start_s);
    if (end) end.value = String(ramp.end_s);
    syncBwPanels(clip);
  }

  function bwStrengthLevel() {
    const strength = document.getElementById("inspector-bw-strength");
    return clampRampPercent(100 - Number(strength ? strength.value : 100));
  }

  function saturationRampFromControls(clip) {
    const stored = clip ? readSaturationRamp(clip) : neutralSaturationRamp();
    const enabled = document.getElementById("inspector-bw-enabled");
    const partial = document.getElementById("inspector-bw-partial");
    const partialOn = Boolean(partial && partial.checked);
    const level = bwStrengthLevel();
    const ramp = Object.assign({}, stored);
    ramp.enabled = Boolean(enabled && enabled.checked);
    ramp.end_saturation = level;
    ramp.start_saturation = partialOn ? 100 : level;
    if (!partialOn) {
      ramp.start_s = 0;
      ramp.end_s = Math.max(0.1, Math.round(clipDuration(clip) * 10000) / 10000);
    } else {
      const start = document.getElementById("inspector-bw-start");
      const end = document.getElementById("inspector-bw-end");
      ramp.start_s = clampRampTime(start ? start.value : stored.start_s);
      ramp.end_s = clampRampTime(end ? end.value : stored.end_s);
    }
    return ramp;
  }

  function queueSaturationRampSave(clip) {
    const studioId = clip.dataset.studioId;
    imageSaveChain = imageSaveChain
      .then(() => saveSaturationRamp(studioId))
      .catch((err) => {
        showFlash((err && err.message) || msgBwFailed);
      });
  }

  async function saveSaturationRamp(studioId) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip) return;
    const ramp = readSaturationRamp(clip);
    const res = await fetch(`/api/studio/${studioId}/saturation-ramp`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ saturation_ramp: ramp }),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgBwFailed);
    }
    if (JSON.stringify(readSaturationRamp(clip)) === JSON.stringify(ramp)) {
      writeSaturationRamp(clip, body.saturation_ramp || ramp, true);
    }
    if (
      state.selected &&
      state.selected.type === "clip" &&
      String(state.selected.id) === String(studioId)
    ) {
      fillSaturationRamp(clip);
    }
    applyPreviewGrades(resolveAt(state.projectTimeS));
    setSaveState(true);
  }

  function commitSaturationRamp(clip, ramp) {
    writeSaturationRamp(clip, ramp);
    fillSaturationRamp(clip);
    applyPreviewGrades(resolveAt(state.projectTimeS));
    setSaveState(false);
    queueSaturationRampSave(clip);
  }

  document.getElementById("inspector-bw-enabled")?.addEventListener("change", () => {
    const clip = selectedVideoClip();
    if (!clip) return;
    const turningOn = document.getElementById("inspector-bw-enabled")?.checked;
    if (!turningOn) {
      const ramp = readSaturationRamp(clip);
      ramp.enabled = false;
      commitSaturationRamp(clip, ramp);
      return;
    }
    const ramp = saturationRampFromControls(clip);
    ramp.enabled = true;
    commitSaturationRamp(clip, ramp);
  });
  document.getElementById("inspector-bw-strength")?.addEventListener("input", () => {
    const clip = selectedVideoClip();
    if (!clip) return;
    writeSaturationRamp(clip, saturationRampFromControls(clip));
    applyPreviewGrades(resolveAt(state.projectTimeS));
    setSaveState(false);
  });
  document.getElementById("inspector-bw-strength")?.addEventListener("change", () => {
    const clip = selectedVideoClip();
    if (!clip) return;
    commitSaturationRamp(clip, saturationRampFromControls(clip));
  });
  document.getElementById("inspector-bw-partial")?.addEventListener("change", () => {
    const clip = selectedVideoClip();
    if (!clip) return;
    const partial = document.getElementById("inspector-bw-partial");
    if (partial && partial.checked) {
      const duration = Math.max(0.1, clipDuration(clip));
      const start = document.getElementById("inspector-bw-start");
      const end = document.getElementById("inspector-bw-end");
      const startS = clampRampTime(start ? start.value : 0);
      const endS = clampRampTime(end ? end.value : duration);
      if (!(startS > 0.05 || endS < duration - 0.05) && end) {
        end.value = String(Math.max(0.5, Math.round(duration * 0.5 * 10000) / 10000));
      }
    }
    commitSaturationRamp(clip, saturationRampFromControls(clip));
  });
  ["inspector-bw-start", "inspector-bw-end"].forEach((inputId) => {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener("input", () => {
      const clip = selectedVideoClip();
      if (!clip) return;
      writeSaturationRamp(clip, saturationRampFromControls(clip));
      applyPreviewGrades(resolveAt(state.projectTimeS));
      setSaveState(false);
    });
    input.addEventListener("change", () => {
      const clip = selectedVideoClip();
      if (!clip) return;
      commitSaturationRamp(clip, saturationRampFromControls(clip));
    });
  });

  function readOverlayModel() {
    try {
      const parsed = JSON.parse(root.dataset.overlayModel || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function readOverlays(clip) {
    if (!clip) return [];
    try {
      const parsed = JSON.parse(clip.dataset.overlays || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (_) {
      return [];
    }
  }

  function writeOverlays(clip, overlays) {
    clip.dataset.overlays = JSON.stringify(overlays);
  }

  function overlayActive(overlay, localS, duration) {
    const start = Number(overlay.start_s);
    const end = Math.min(Number(overlay.end_s), Number(duration) || 0);
    return start <= localS && localS <= end && end - start >= 0.05;
  }

  function hideAnnotations() {
    [previewAnnotations, previewAnnotationsB].forEach((layer) => {
      if (!layer) return;
      layer.hidden = true;
      layer.replaceChildren();
      layer.style.opacity = "";
    });
  }

  function contentBoxFor(mediaEl) {
    const frameW = previewFrame ? previewFrame.clientWidth : 0;
    const frameH = previewFrame ? previewFrame.clientHeight : 0;
    const sourceW = mediaEl ? mediaEl.videoWidth || mediaEl.naturalWidth || 0 : 0;
    const sourceH = mediaEl ? mediaEl.videoHeight || mediaEl.naturalHeight || 0 : 0;
    if (!frameW || !frameH || !sourceW || !sourceH) {
      return { left: 0, top: 0, width: frameW, height: frameH };
    }
    const scale = Math.min(frameW / sourceW, frameH / sourceH);
    const width = sourceW * scale;
    const height = sourceH * scale;
    return {
      left: (frameW - width) / 2,
      top: (frameH - height) / 2,
      width,
      height,
    };
  }

  function mediaForAnnotation(clip, layerB) {
    if (!clip) return null;
    if (clip.dataset.kind === "photo") return layerB ? previewImageB : previewImage;
    if (clip.dataset.kind === "video") return layerB ? previewVideoB : previewVideo;
    return null;
  }

  function safeColor(value, fallback) {
    const text = String(value || "");
    return /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(text) ? text : fallback;
  }

  function annotationSvg(overlay) {
    const stroke = safeColor(overlay.stroke, "#ffffff");
    const fill = safeColor(overlay.fill, "none");
    if (overlay.kind === "arrow") {
      return (
        '<svg viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">' +
        '<line x1="2" y1="20" x2="72" y2="20" stroke="' + stroke + '" stroke-width="6" stroke-linecap="round"></line>' +
        '<polygon points="68,6 98,20 68,34" fill="' + stroke + '"></polygon></svg>'
      );
    }
    if (overlay.kind === "circle") {
      return (
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">' +
        '<ellipse cx="50" cy="50" rx="46" ry="46" fill="' + fill + '" stroke="' + stroke + '" stroke-width="4"></ellipse></svg>'
      );
    }
    if (overlay.kind === "rectangle") {
      return (
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">' +
        '<rect x="3" y="3" width="94" height="94" fill="' + fill + '" stroke="' + stroke + '" stroke-width="4"></rect></svg>'
      );
    }
    return "";
  }

  function animationSpan(overlay) {
    const start = Number(overlay.start_s) || 0;
    const end = Number(overlay.end_s) || 0;
    const limit = Math.max(0.1, end - start);
    const requested = Number(overlay.animation_s);
    const duration = Number.isFinite(requested) ? requested : 0.4;
    return Math.min(limit, Math.max(0.1, duration));
  }

  function animationOpacity(overlay, localS) {
    const kind = overlay.animation || "none";
    if (kind !== "fade_in" && kind !== "fade_out") return 1;
    const start = Number(overlay.start_s) || 0;
    const end = Number(overlay.end_s) || 0;
    const duration = animationSpan(overlay);
    if (kind === "fade_in") return Math.max(0, Math.min(1, (localS - start) / duration));
    const outStart = end - duration;
    if (localS <= outStart) return 1;
    return Math.max(0, Math.min(1, 1 - (localS - outStart) / duration));
  }

  function animationTransform(overlay, localS, layer) {
    const rotation = "rotate(" + Number(overlay.rotation || 0) + "deg)";
    if ((overlay.animation || "none") !== "slide_in") return rotation;
    const start = Number(overlay.start_s) || 0;
    const duration = animationSpan(overlay);
    const remain = 1 - Math.max(0, Math.min(1, (localS - start) / duration));
    const from = overlay.slide_from || "left";
    let shift = "";
    if (from === "right") {
      shift = "translateX(calc(" + remain + " * (100% + " + (1 - overlay.x - overlay.w) * 100 + "%)))";
    } else if (from === "up") {
      shift = "translateY(calc(" + -remain + " * (100% + " + overlay.y * 100 + "%)))";
    } else if (from === "down") {
      shift = "translateY(calc(" + remain + " * (100% + " + (1 - overlay.y - overlay.h) * 100 + "%)))";
    } else {
      shift = "translateX(calc(" + -remain + " * (100% + " + overlay.x * 100 + "%)))";
    }
    return shift + " " + rotation;
  }

  function buildAnnotation(overlay, layer, interactive, localS) {
    const el = document.createElement("div");
    el.className = "studio-annotation";
    if (interactive && selectedOverlayId === overlay.id) el.classList.add("is-selected");
    el.dataset.overlayId = overlay.id;
    el.style.left = Number(overlay.x) * 100 + "%";
    el.style.top = Number(overlay.y) * 100 + "%";
    el.style.width = Number(overlay.w) * 100 + "%";
    el.style.height = Number(overlay.h) * 100 + "%";
    el.style.transform = animationTransform(overlay, localS, layer);
    el.style.opacity = String(animationOpacity(overlay, localS));
    if (overlay.kind === "text") {
      el.textContent = overlay.text || "";
      el.style.color = safeColor(overlay.color, "#ffffff").slice(0, 7);
      const px = Math.max(8, Number(overlay.font_size || 0.06) * layer.clientHeight);
      el.style.fontSize = px + "px";
      if (overlay.fill && !String(overlay.fill).endsWith("00")) {
        el.style.background = overlay.fill;
      }
    } else if (overlay.kind === "image") {
      const img = document.createElement("img");
      img.alt = "";
      img.src = "/studio/overlay-assets/" + encodeURIComponent(overlay.asset_name || "");
      img.addEventListener("error", () => {
        el.classList.add("is-missing");
        el.textContent = msgOverlayMissing;
      });
      el.appendChild(img);
    } else {
      el.innerHTML = annotationSvg(overlay);
    }
    if (interactive) {
      el.addEventListener("pointerdown", (event) => startAnnotationDrag(event, overlay.id));
    }
    return el;
  }

  function renderAnnotationLayer(layer, clip, localS, interactive) {
    if (!layer) return;
    layer.replaceChildren();
    if (!clip || (clip.dataset.kind !== "photo" && clip.dataset.kind !== "video")) {
      layer.hidden = true;
      return;
    }
    const repeated = sectionRepeats(clip) > 1;
    const duration = repeated ? sectionCycleS(clip) : clipDuration(clip);
    const sample = repeated ? sectionSampleS(clip, localS) : localS;
    const visible = readOverlays(clip).filter((overlay) => overlayActive(overlay, sample, duration));
    if (!visible.length) {
      layer.hidden = true;
      return;
    }
    const media = mediaForAnnotation(clip, layer === previewAnnotationsB);
    const box = contentBoxFor(media);
    layer.hidden = false;
    layer.style.left = box.left + "px";
    layer.style.top = box.top + "px";
    layer.style.width = Math.max(1, box.width) + "px";
    layer.style.height = Math.max(1, box.height) + "px";
    visible.forEach((overlay) => layer.appendChild(buildAnnotation(overlay, layer, interactive, sample)));
  }

  function syncAnnotations(hit) {
    if (!hit || !hit.clip) {
      hideAnnotations();
      return;
    }
    const overlap = hit.overlapClip && hit.crossfadeProgress != null;
    renderAnnotationLayer(previewAnnotations, hit.clip, hit.localS || 0, true);
    if (previewAnnotations) {
      previewAnnotations.style.opacity = overlap ? String(hit.crossfadeProgress) : "";
    }
    if (overlap) {
      renderAnnotationLayer(previewAnnotationsB, hit.overlapClip, hit.overlapLocalS || 0, false);
    } else if (previewAnnotationsB) {
      previewAnnotationsB.hidden = true;
      previewAnnotationsB.replaceChildren();
    }
  }

  function selectedOverlayClip() {
    if (!state.selected || state.selected.type !== "clip") return null;
    const clip = clips().find((item) => String(item.dataset.studioId) === String(state.selected.id));
    if (!clip || (clip.dataset.kind !== "photo" && clip.dataset.kind !== "video")) return null;
    return clip;
  }

  function overlayLabel(overlay) {
    if (overlay.kind === "text" && overlay.text) return overlay.text;
    const button = document.getElementById("overlay-add-" + overlay.kind);
    if (button && button.textContent.trim()) return button.textContent.trim();
    return overlay.kind;
  }

  function fillOverlayInspector(clip) {
    const list = document.getElementById("inspector-overlay-list");
    const editor = document.getElementById("inspector-overlay-editor");
    if (!list || !editor) return;
    const overlays = readOverlays(clip);
    if (!overlays.some((overlay) => overlay.id === selectedOverlayId)) {
      selectedOverlayId = overlays.length ? overlays[overlays.length - 1].id : null;
    }
    list.replaceChildren();
    overlays.forEach((overlay) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button ghost";
      button.textContent = overlayLabel(overlay);
      if (overlay.id === selectedOverlayId) button.classList.add("is-selected");
      button.addEventListener("click", () => {
        selectedOverlayId = overlay.id;
        fillOverlayInspector(clip);
        syncAnnotations(resolveAt(state.projectTimeS));
      });
      item.appendChild(button);
      list.appendChild(item);
    });
    const current = overlays.find((overlay) => overlay.id === selectedOverlayId);
    editor.hidden = !current;
    if (!current) return;
    const kind = current.kind;
    editor.querySelectorAll("[data-overlay-field]").forEach((field) => {
      const key = field.getAttribute("data-overlay-field");
      const show =
        (key === "text" && kind === "text") ||
        (key === "font" && kind === "text") ||
        (key === "color" && kind === "text") ||
        (key === "stroke" && kind !== "text" && kind !== "image") ||
        (key === "fill" && (kind === "circle" || kind === "rectangle")) ||
        (key === "slide" && (current.animation || "none") === "slide_in");
      field.hidden = !show;
    });
    setNumber("overlay-start", current.start_s);
    setNumber("overlay-end", current.end_s);
    setNumber("overlay-x", Math.round(current.x * 100));
    setNumber("overlay-y", Math.round(current.y * 100));
    setNumber("overlay-w", Math.round(current.w * 100));
    setNumber("overlay-h", Math.round(current.h * 100));
    setNumber("overlay-rotation", current.rotation || 0);
    setNumber("overlay-font", Math.round(Number(current.font_size || 0.06) * 100));
    const text = document.getElementById("overlay-text");
    if (text && document.activeElement !== text) text.value = current.text || "";
    setColor("overlay-color", current.color);
    setColor("overlay-stroke", current.stroke);
    setColor("overlay-fill", current.fill);
    const animation = document.getElementById("overlay-animation");
    if (animation && document.activeElement !== animation) animation.value = current.animation || "none";
    setNumber("overlay-animation-s", current.animation_s == null ? 0.4 : current.animation_s);
    const slide = document.getElementById("overlay-slide-from");
    if (slide && document.activeElement !== slide) slide.value = current.slide_from || "left";
  }

  function setNumber(id, value) {
    const input = document.getElementById(id);
    if (!input || document.activeElement === input) return;
    input.value = String(value);
  }

  function setColor(id, value) {
    const input = document.getElementById(id);
    if (!input || document.activeElement === input) return;
    const hex = String(value || "#ffffff");
    input.value = hex.slice(0, 7);
  }

  function editorOverlayPatch(overlay) {
    const next = Object.assign({}, overlay);
    const overlayClip = selectedOverlayClip();
    const duration =
      overlayClip && sectionRepeats(overlayClip) > 1
        ? sectionCycleS(overlayClip)
        : clipDuration(overlayClip || { dataset: {} });
    next.start_s = numberOr(document.getElementById("overlay-start"), next.start_s);
    next.end_s = numberOr(document.getElementById("overlay-end"), next.end_s);
    next.x = numberOr(document.getElementById("overlay-x"), next.x * 100) / 100;
    next.y = numberOr(document.getElementById("overlay-y"), next.y * 100) / 100;
    next.w = numberOr(document.getElementById("overlay-w"), next.w * 100) / 100;
    next.h = numberOr(document.getElementById("overlay-h"), next.h * 100) / 100;
    next.rotation = numberOr(document.getElementById("overlay-rotation"), next.rotation || 0);
    next.font_size = numberOr(document.getElementById("overlay-font"), (next.font_size || 0.06) * 100) / 100;
    const text = document.getElementById("overlay-text");
    if (text && next.kind === "text") next.text = text.value;
    const color = document.getElementById("overlay-color");
    if (color && next.kind === "text") next.color = color.value;
    const stroke = document.getElementById("overlay-stroke");
    if (stroke && next.kind !== "text" && next.kind !== "image") next.stroke = stroke.value;
    const fill = document.getElementById("overlay-fill");
    if (fill && (next.kind === "circle" || next.kind === "rectangle")) next.fill = fill.value + "66";
    const animation = document.getElementById("overlay-animation");
    if (animation) next.animation = animation.value || "none";
    next.animation_s = numberOr(document.getElementById("overlay-animation-s"), next.animation_s || 0.4);
    const slide = document.getElementById("overlay-slide-from");
    if (slide) next.slide_from = slide.value || "left";
    if (duration > 0 && next.end_s > duration) next.end_s = duration;
    return next;
  }

  function numberOr(input, fallback) {
    if (!input) return Number(fallback) || 0;
    const value = Number(input.value);
    return Number.isFinite(value) ? value : Number(fallback) || 0;
  }

  function replaceSelectedOverlay(mutator, { save = true } = {}) {
    const clip = selectedOverlayClip();
    if (!clip || !selectedOverlayId) return;
    const overlays = readOverlays(clip).map((overlay) =>
      overlay.id === selectedOverlayId ? mutator(overlay) : overlay
    );
    writeOverlays(clip, overlays);
    if (selectedOverlayClip() === clip) fillOverlayInspector(clip);
    syncAnnotations(resolveAt(state.projectTimeS));
    if (save) queueOverlaySave(clip);
  }

  async function saveOverlays(studioId) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip) return;
    const res = await fetch("/api/studio/" + studioId + "/overlays", {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ overlays: readOverlays(clip) }),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgOverlayFailed);
    }
    writeOverlays(clip, body.overlays || []);
    if (body.clamped) showRootFlash(msgOverlayClamped);
    if (selectedOverlayClip() === clip) fillOverlayInspector(clip);
    syncAnnotations(resolveAt(state.projectTimeS));
    setSaveState(true);
  }

  function queueOverlaySave(clip) {
    const studioId = clip.dataset.studioId;
    setSaveState(false);
    overlaySaveChain = overlaySaveChain
      .then(() => saveOverlays(studioId))
      .catch((err) => {
        showRootFlash((err && err.message) || msgOverlayFailed);
      });
  }

  function addOverlay(kind, assetName) {
    const clip = selectedOverlayClip();
    if (!clip) return;
    const maxCount = Number(overlayModel.max_overlays || 8);
    const existing = readOverlays(clip);
    if (existing.length >= maxCount) {
      showRootFlash(msgOverlayLimit);
      return;
    }
    const duration = Math.max(
      0.1,
      sectionRepeats(clip) > 1 ? sectionCycleS(clip) : clipDuration(clip)
    );
    const shift = (existing.length % 4) * 0.06;
    const overlay = {
      id: "ov" + Math.random().toString(16).slice(2, 12),
      kind,
      start_s: 0,
      end_s: Math.max(0.1, Math.min(duration, 3)),
      x: Math.min(0.72, 0.08 + shift),
      y: Math.min(0.72, 0.08 + shift),
      w: kind === "text" ? 0.46 : kind === "arrow" ? 0.3 : 0.24,
      h: kind === "text" ? 0.16 : kind === "arrow" ? 0.12 : 0.24,
      rotation: 0,
      text: kind === "text" ? "Text" : "",
      font_size: 0.06,
      color: "#ffffff",
      fill: kind === "circle" || kind === "rectangle" ? "#00000066" : "#00000000",
      stroke: "#ffffff",
      stroke_width: 0.012,
      asset_name: assetName || "",
      animation: "none",
      animation_s: 0.4,
      slide_from: "left",
    };
    selectedOverlayId = overlay.id;
    writeOverlays(clip, existing.concat([overlay]));
    fillOverlayInspector(clip);
    syncAnnotations(resolveAt(state.projectTimeS));
    queueOverlaySave(clip);
  }

  function startAnnotationDrag(event, overlayId) {
    if (event.button != null && event.button !== 0) return;
    if (maskDragging) return;
    if (event.target && event.target.closest && event.target.closest(".studio-mask-box, .studio-mask-resize")) return;
    if (maskBoxAtPoint(event.clientX, event.clientY)) return;
    if (maskCanvasHit(event.clientX, event.clientY)) return;
    const clip = clips().find((item) => String(item.dataset.studioId) === String(state.activeStudioId));
    if (!clip) return;
    event.preventDefault();
    event.stopPropagation();
    selectedOverlayId = overlayId;
    if (!state.selected || String(state.selected.id) !== String(clip.dataset.studioId)) {
      selectClip(clip.dataset.studioId, { movePlayhead: false });
    } else {
      fillOverlayInspector(clip);
    }
    const layer = previewAnnotations;
    if (!layer) return;
    const origin = readOverlays(clip).find((item) => item.id === overlayId);
    if (!origin) return;
    const startX = event.clientX;
    const startY = event.clientY;
    const width = layer.clientWidth || 1;
    const height = layer.clientHeight || 1;
    function move(ev) {
      const dx = (ev.clientX - startX) / width;
      const dy = (ev.clientY - startY) / height;
      const maxX = Math.max(0, 1 - Number(origin.w));
      const maxY = Math.max(0, 1 - Number(origin.h));
      const next = Object.assign({}, origin, {
        x: Math.min(maxX, Math.max(0, Number(origin.x) + dx)),
        y: Math.min(maxY, Math.max(0, Number(origin.y) + dy)),
      });
      writeOverlays(
        clip,
        readOverlays(clip).map((item) => (item.id === overlayId ? next : item))
      );
      syncAnnotations(resolveAt(state.projectTimeS));
    }
    function up() {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      fillOverlayInspector(clip);
      queueOverlaySave(clip);
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  ["overlay-add-text", "overlay-add-arrow", "overlay-add-circle", "overlay-add-rectangle"].forEach(
    (id) => {
      const button = document.getElementById(id);
      if (!button) return;
      const kind = id.replace("overlay-add-", "");
      button.addEventListener("click", () => addOverlay(kind, ""));
    }
  );
  const overlayImageButton = document.getElementById("overlay-add-image");
  const overlayImageFile = document.getElementById("overlay-image-file");
  if (overlayImageButton && overlayImageFile) {
    overlayImageButton.addEventListener("click", () => overlayImageFile.click());
    overlayImageFile.addEventListener("change", async () => {
      const file = overlayImageFile.files && overlayImageFile.files[0];
      overlayImageFile.value = "";
      if (!file) return;
      try {
        const body = new FormData();
        body.append("file", file);
        const res = await fetch("/api/studio/overlay-assets", { method: "POST", body });
        const payload = await readJson(res);
        if (!res.ok || !payload || !payload.asset_name) {
          throw new Error((payload && payload.detail) || msgOverlayFailed);
        }
        addOverlay("image", payload.asset_name);
      } catch (err) {
        showRootFlash((err && err.message) || msgOverlayFailed);
      }
    });
  }
  ["overlay-text", "overlay-start", "overlay-end", "overlay-x", "overlay-y", "overlay-w", "overlay-h", "overlay-rotation", "overlay-font", "overlay-color", "overlay-stroke", "overlay-fill", "overlay-animation", "overlay-animation-s", "overlay-slide-from"].forEach(
    (id) => {
      const input = document.getElementById(id);
      if (!input) return;
      input.addEventListener("change", () => {
        replaceSelectedOverlay((overlay) => editorOverlayPatch(overlay));
      });
    }
  );
  document.getElementById("overlay-remove")?.addEventListener("click", () => {
    const clip = selectedOverlayClip();
    if (!clip || !selectedOverlayId) return;
    const overlays = readOverlays(clip).filter((overlay) => overlay.id !== selectedOverlayId);
    selectedOverlayId = overlays.length ? overlays[overlays.length - 1].id : null;
    writeOverlays(clip, overlays);
    fillOverlayInspector(clip);
    syncAnnotations(resolveAt(state.projectTimeS));
    queueOverlaySave(clip);
  });
  if (previewImage) {
    previewImage.addEventListener("load", () => {
      const hit = resolveAt(state.projectTimeS);
      syncAnnotations(hit);
      drawFlightMap(hit);
    });
  }
  if (previewVideo) {
    previewVideo.addEventListener("loadedmetadata", () => {
      const hit = resolveAt(state.projectTimeS);
      syncAnnotations(hit);
      drawFlightMap(hit);
    });
  }
  document.querySelectorAll("#inspector-speed [data-speed]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const speed = Number(btn.dataset.speed);
      if (speed === 1 || speed === 0.5 || speed === 0.25) applyClipSpeed(speed);
    });
  });

  document.getElementById("inspector-frame-zoom")?.addEventListener("input", () => {
    const clip = selectedAdjustableClip();
    const input = document.getElementById("inspector-frame-zoom");
    if (!clip || !input) return;
    const frame = readFrame(clip);
    frame.zoom_start = clampZoom(input.value);
    if (!frameMotionChecked()) {
      frame.zoom_end = frame.zoom_start;
      frame.x_end = frame.x_start;
      frame.y_end = frame.y_start;
    }
    commitFrame(clip, frame);
    setSaveState(false);
  });
  document.getElementById("inspector-frame-zoom")?.addEventListener("change", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    queueFrameSave(clip);
  });
  document.getElementById("inspector-frame-zoom-end")?.addEventListener("input", () => {
    const clip = selectedAdjustableClip();
    const input = document.getElementById("inspector-frame-zoom-end");
    if (!clip || !input) return;
    const frame = readFrame(clip);
    frame.zoom_end = clampZoom(input.value);
    frameMotionArmed = true;
    commitFrame(clip, frame);
    setSaveState(false);
  });
  document.getElementById("inspector-frame-zoom-end")?.addEventListener("change", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    queueFrameSave(clip);
  });
  document.getElementById("inspector-frame-motion")?.addEventListener("change", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    const frame = readFrame(clip);
    frameMotionArmed = frameMotionChecked();
    if (!frameMotionArmed) {
      frame.zoom_end = frame.zoom_start;
      frame.x_end = frame.x_start;
      frame.y_end = frame.y_start;
      frameEditTarget = "start";
    }
    commitFrame(clip, frame);
    setSaveState(false);
    queueFrameSave(clip);
  });
  document.getElementById("inspector-frame-target-start")?.addEventListener("click", () => {
    frameEditTarget = "start";
    const clip = selectedAdjustableClip();
    if (clip) fillFrame(clip);
    applyFramePreview(resolveAt(state.projectTimeS));
  });
  document.getElementById("inspector-frame-target-end")?.addEventListener("click", () => {
    frameEditTarget = "end";
    frameMotionArmed = true;
    const clip = selectedAdjustableClip();
    if (clip) fillFrame(clip);
    applyFramePreview(resolveAt(state.projectTimeS));
  });
  function readHud(clip) {
    if (!clip) return {};
    try {
      const parsed = JSON.parse(clip.dataset.hud || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function writeHud(clip, hud) {
    clip.dataset.hud = JSON.stringify(hud);
  }

  function formatHudElapsed(sourceS) {
    const total = Math.max(0, Math.floor(Number(sourceS) + 1e-6));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    const pad = (value) => String(value).padStart(2, "0");
    return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds);
  }

  function hudAltitudeText(hud, sourceS) {
    const rows = Array.isArray(hud.intervals) ? hud.intervals : [];
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index];
      const start = Number(row.start);
      const end = Number(row.end);
      const last = index === rows.length - 1;
      const beforeEnd = sourceS < end - 1e-9 || (last && sourceS <= end + 1e-3);
      if (sourceS >= start - 1e-9 && beforeEnd && row.alt != null && Number.isFinite(Number(row.alt))) {
        return Number(row.alt).toFixed(1) + " m";
      }
    }
    return "";
  }

  function paintHud(el, clip, localS, opacity) {
    if (!el) return;
    const hud = clip ? readHud(clip) : null;
    if (!clip || clip.dataset.kind !== "video" || !hud || !hud.enabled || !hud.available) {
      el.hidden = true;
      el.textContent = "";
      el.style.opacity = "";
      return;
    }
    const sourceS = sourceClock(clip, localS);
    const lines = [formatHudElapsed(sourceS)];
    const altitude = hudAltitudeText(hud, sourceS);
    if (altitude) lines.push(altitude);
    el.hidden = false;
    el.textContent = lines.join("\n");
    el.style.opacity = opacity == null ? "" : String(opacity);
  }

  function syncHud(hit) {
    if (!hit || !hit.clip) {
      paintHud(previewHud, null, 0, null);
      paintHud(previewHudB, null, 0, null);
      return;
    }
    const overlap = Boolean(hit.overlapClip && hit.crossfadeProgress != null);
    paintHud(
      previewHud,
      hit.clip,
      hit.localS || 0,
      overlap ? hit.crossfadeProgress : null
    );
    if (overlap) paintHud(previewHudB, hit.overlapClip, hit.overlapLocalS || 0, 1);
    else paintHud(previewHudB, null, 0, null);
  }

  function selectedVideoClip() {
    const clip = selectedAdjustableClip();
    if (!clip || clip.dataset.kind !== "video") return null;
    return clip;
  }

  function fillHud(clip) {
    const hud = readHud(clip);
    const status = document.getElementById("inspector-hud-status");
    const box = document.getElementById("inspector-hud-enabled");
    if (status) status.textContent = hud.available ? msgHudReady : msgHudMissing;
    ["elapsed", "altitude", "speed", "home_distance"].forEach((field) => {
      const node = document.querySelector('[data-hud-field="' + field + '"]');
      if (!node) return;
      const ready = hud[field] === "available";
      node.textContent = ready ? labelHudAvailable : labelHudUnavailable;
      node.classList.toggle("is-unavailable", !ready);
    });
    if (box) {
      box.disabled = !hud.available;
      box.checked = Boolean(hud.available && hud.enabled);
    }
  }

  async function saveHud(studioId, enabled) {
    const res = await fetch(`/api/studio/${studioId}/hud`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ enabled: Boolean(enabled) }),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgHudFailed);
    }
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (clip) {
      const hud = readHud(clip);
      hud.enabled = Boolean(body.enabled);
      writeHud(clip, hud);
      if (
        state.selected &&
        state.selected.type === "clip" &&
        String(state.selected.id) === String(studioId)
      ) {
        fillHud(clip);
      }
      syncHud(resolveAt(state.projectTimeS));
    }
    setSaveState(true);
  }

  document.getElementById("inspector-hud-enabled")?.addEventListener("change", () => {
    const clip = selectedVideoClip();
    const box = document.getElementById("inspector-hud-enabled");
    if (!clip || !box || box.disabled) return;
    const enabled = Boolean(box.checked);
    const hud = readHud(clip);
    hud.enabled = enabled;
    writeHud(clip, hud);
    syncHud(resolveAt(state.projectTimeS));
    setSaveState(false);
    saveHud(clip.dataset.studioId, enabled).catch((err) => {
      hud.enabled = !enabled;
      writeHud(clip, hud);
      box.checked = !enabled;
      syncHud(resolveAt(state.projectTimeS));
      showFlash((err && err.message) || msgHudFailed);
    });
  });
  document.getElementById("inspector-frame-reset")?.addEventListener("click", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    frameMotionArmed = false;
    frameEditTarget = "start";
    commitFrame(clip, neutralFrame());
    setSaveState(false);
    queueFrameSave(clip);
  });
  if (previewFrame) {
    previewFrame.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      if (maskDragging) return;
      if (
        event.target &&
        event.target.closest &&
        event.target.closest(".studio-mask-box, .studio-mask-hit, .studio-mask-resize, .studio-mask-remove, #studio-preview-mask-handles")
      ) {
        return;
      }
      if (maskBoxAtPoint(event.clientX, event.clientY)) return;
      if (maskCanvasHit(event.clientX, event.clientY)) return;
      const clip = selectedAdjustableClip();
      if (!clip) return;
      const frame = readFrame(clip);
      const editingEnd = frameMotionChecked() && frameEditTarget === "end";
      const zoom = editingEnd ? frame.zoom_end : frame.zoom_start;
      if (zoom <= 1.001) return;
      event.preventDefault();
      previewFrame.classList.add("is-panning");
      const pointerId = event.pointerId;
      previewFrame.setPointerCapture?.(pointerId);
      let lastX = event.clientX;
      let lastY = event.clientY;
      const move = (ev) => {
        panFrame(clip, ev.clientX - lastX, ev.clientY - lastY);
        lastX = ev.clientX;
        lastY = ev.clientY;
      };
      const up = () => {
        previewFrame.classList.remove("is-panning");
        previewFrame.removeEventListener("pointermove", move);
        previewFrame.removeEventListener("pointerup", up);
        previewFrame.removeEventListener("pointercancel", up);
        setSaveState(false);
        queueFrameSave(clip);
      };
      previewFrame.addEventListener("pointermove", move);
      previewFrame.addEventListener("pointerup", up);
      previewFrame.addEventListener("pointercancel", up);
    });
  }
  const reapplyFrame = () => applyFramePreview(resolveAt(state.projectTimeS));
  previewImage?.addEventListener("load", reapplyFrame);
  previewImageB?.addEventListener("load", reapplyFrame);
  previewVideo?.addEventListener("loadedmetadata", reapplyFrame);
  previewVideoB?.addEventListener("loadedmetadata", reapplyFrame);
  window.addEventListener("resize", reapplyFrame);

  ["inspector-music-volume", "inspector-music-fade-in", "inspector-music-fade-out"].forEach(
    (id) => {
      document.getElementById(id)?.addEventListener("input", () => {
        const track = selectedMusicTrack();
        if (!track) return;
        const vol = document.getElementById("inspector-music-volume");
        const fadeIn = document.getElementById("inspector-music-fade-in");
        const fadeOut = document.getElementById("inspector-music-fade-out");
        track.volume = Number(vol?.value || 80) / 100;
        track.fadeIn = Number(fadeIn?.value || 0);
        track.fadeOut = Number(fadeOut?.value || 0);
        syncMusicAudio();
        layoutMusicSpans();
      });
      document.getElementById(id)?.addEventListener("change", () => {
        patchMusicSettings();
      });
    }
  );
  document.getElementById("inspector-music-start")?.addEventListener("change", (event) => {
    const previous = state.musicStartS;
    const raw = Number(event.target.value);
    state.musicStartS = Number.isFinite(raw)
      ? Math.max(0, Math.min(totalDuration(), raw))
      : previous;
    layoutMusicSpans();
    syncMusicAudio();
    persistMusicStart(previous);
  });
  document.getElementById("inspector-music-loop")?.addEventListener("change", (event) => {
    const track = selectedMusicTrack();
    if (!track) return;
    track.loop = !!event.target.checked;
    syncMusicAudio();
    layoutTimeline();
    patchMusicSettings();
  });

  document.getElementById("inspector-forward-loop")?.addEventListener("change", (event) => {
    if (state.selected.type !== "clip") return;
    const clip = clips().find((c) => String(c.dataset.studioId) === String(state.selected.id));
    if (!clip || clip.dataset.kind !== "video") return;
    persistForwardLoop(clip, !!event.target.checked);
  });

  async function persistSelectedLoopTransition() {
    if (state.selected.type !== "clip") return;
    const clip = clips().find((c) => String(c.dataset.studioId) === String(state.selected.id));
    if (!clip || clip.dataset.kind !== "video" || !loopEffectReady(clip)) return;
    const durationWrap = document.getElementById("inspector-loop-transition-duration-wrap");
    const choice = document.getElementById("inspector-loop-transition");
    if (durationWrap && choice) durationWrap.hidden = choice.value === "off";
    const curveWrap = document.getElementById("inspector-loop-transition-curve-wrap");
    if (curveWrap && choice) curveWrap.hidden = choice.value !== "cinematic";
    if (choice && choice.value === "cinematic") {
      const durationEl = document.getElementById("inspector-loop-transition-duration");
      if (durationEl) durationEl.max = "5";
    }
    const prevTransition = clip.dataset.forwardLoopTransition;
    const prevTransitionS = clip.dataset.forwardLoopTransitionS;
    const prevOverlap = clip.dataset.forwardLoopOverlap;
    const prevMatch = clip.dataset.loopMatchState;
    const prevDuration = clip.dataset.effectiveDuration;
    setSaveState(false);
    try {
      const res = await fetch(`/api/studio/${clip.dataset.studioId}/loop-effect`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(loopEffectBody()),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        throw new Error((data && data.detail) || msgForwardLoopFailed);
      }
      if (data.transition) clip.dataset.forwardLoopTransition = data.transition;
      if (data.transition_s != null) clip.dataset.forwardLoopTransitionS = String(data.transition_s);
      if (data.overlap_s != null) clip.dataset.forwardLoopOverlap = String(data.overlap_s);
      if (data.effective_duration_s != null) {
        clip.dataset.effectiveDuration = String(data.effective_duration_s);
      }
      if (data.match_state) clip.dataset.loopMatchState = data.match_state;
      if (data.match_in_s != null) clip.dataset.loopMatchIn = String(data.match_in_s);
      if (data.match_out_s != null) clip.dataset.loopMatchOut = String(data.match_out_s);
      if (data.plays != null && clip.dataset.forwardLoopActive === "1") {
        clip.dataset.forwardLoopPlays = String(data.plays);
      }
      if (data.partial_s != null && clip.dataset.forwardLoopActive === "1") {
        clip.dataset.forwardLoopPartial = String(data.partial_s);
      }
      applyForwardLoopClip(clip, {
        enabled: clip.dataset.forwardLoop === "1",
        active: clip.dataset.forwardLoopActive === "1",
        reason: clip.dataset.forwardLoopReason,
        ...data,
      });
      refreshAppliedTransitions();
      layoutTimeline();
      setProjectTime(state.projectTimeS);
      setSaveState(true);
      showFlash("");
    } catch (err) {
      clip.dataset.forwardLoopTransition = prevTransition;
      clip.dataset.forwardLoopTransitionS = prevTransitionS;
      clip.dataset.forwardLoopOverlap = prevOverlap;
      clip.dataset.loopMatchState = prevMatch;
      clip.dataset.effectiveDuration = prevDuration;
      fillLoopEffect(clip);
      showFlash(err && err.message ? err.message : msgForwardLoopFailed);
    }
  }

  document.getElementById("inspector-loop-transition")?.addEventListener("change", () => {
    persistSelectedLoopTransition();
  });
  document.getElementById("inspector-loop-transition-duration")?.addEventListener("change", () => {
    persistSelectedLoopTransition();
  });
  document.getElementById("inspector-loop-transition-curve")?.addEventListener("change", () => {
    persistSelectedLoopTransition();
  });

  ["inspector-source-in", "inspector-source-out", "inspector-section-repeats"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => {
      if (reuseDraft) {
        readReuseFields(id === "inspector-source-out" ? "out" : "in");
        return;
      }
      if (state.selected.type !== "clip") return;
      const clip = clips().find((c) => String(c.dataset.studioId) === String(state.selected.id));
      if (!clip || clip.dataset.kind !== "video") return;
      persistSection(clip);
    });
  });

  document.getElementById("inspector-photo-duration")?.addEventListener("change", (event) => {
    if (state.selected.type !== "clip") return;
    const clip = clips().find((c) => String(c.dataset.studioId) === String(state.selected.id));
    if (!clip) return;
    let value = Number(event.target.value);
    if (!Number.isFinite(value)) value = defaultPhotoDuration;
    value = Math.max(0.5, Math.min(60, value));
    event.target.value = value.toFixed(1);
    patchPhotoDuration(clip, value);
  });

  document.getElementById("inspector-photo-reset")?.addEventListener("click", () => {
    if (state.selected.type !== "clip") return;
    const clip = clips().find((c) => String(c.dataset.studioId) === String(state.selected.id));
    if (!clip) return;
    patchPhotoDuration(clip, null);
  });

  if (playheadEl && tracksEl) {
    const onMove = (event) => {
      if (!playheadDragging) return;
      seekFromClientX(event.clientX);
    };
    const onUp = () => {
      if (!playheadDragging) return;
      playheadDragging = false;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      if (playheadWasPlaying && state.projectTimeS < totalDuration() - 0.001) {
        startPlayback();
      }
      playheadWasPlaying = false;
    };
    playheadEl.addEventListener("pointerdown", (event) => {
      playheadDragging = true;
      playheadWasPlaying = state.playing;
      pausePlayback();
      playheadEl.setPointerCapture?.(event.pointerId);
      seekFromClientX(event.clientX);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
    playheadEl.addEventListener("keydown", (event) => {
      const total = totalDuration();
      if (total <= 0) return;
      const step = event.shiftKey ? 5 : 1;
      let next = state.projectTimeS;
      if (event.key === "ArrowLeft") next -= step;
      else if (event.key === "ArrowRight") next += step;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = total;
      else return;
      event.preventDefault();
      setProjectTime(Math.max(0, Math.min(total, next)));
    });
    rulerEl?.addEventListener("click", (event) => {
      const wasPlaying = state.playing;
      pausePlayback();
      seekFromClientX(event.clientX, {
        resumeAfter: wasPlaying && state.projectTimeS < totalDuration() - 0.001,
      });
    });
    timelineCanvasEl?.addEventListener("click", (event) => {
      if (suppressTimelineClick) return;
      if (event.target.closest(".studio-clip, .studio-transition, .studio-playhead, .studio-ruler, #studio-music-track, .studio-clip-audio-bar")) return;
      const wasPlaying = state.playing;
      pausePlayback();
      seekFromClientX(event.clientX, {
        resumeAfter: wasPlaying && state.projectTimeS < totalDuration() - 0.001,
      });
    });
  }

  function clearOriginalDropMark() {
    grid.querySelectorAll(".is-drop-before").forEach((el) => el.classList.remove("is-drop-before"));
  }
  function originalDropBeforeId(event) {
    const clip = event.target.closest && event.target.closest(".studio-clip");
    if (!clip) return null;
    const rect = clip.getBoundingClientRect();
    if (event.clientX < rect.left + rect.width / 2) return clip.dataset.studioId || null;
    let next = clip.nextElementSibling;
    while (next && !next.classList.contains("studio-clip")) next = next.nextElementSibling;
    return next && next.dataset.studioId ? next.dataset.studioId : null;
  }
  root.addEventListener("dragstart", (event) => {
    const item = event.target.closest && event.target.closest(".studio-original-item");
    if (!item || item.dataset.canPlay !== "1") return;
    dragOriginalMediaId = item.dataset.originalMediaId || "";
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "copy";
      try {
        event.dataTransfer.setData("text/plain", `original:${dragOriginalMediaId}`);
      } catch (_) {
        /* older WebViews */
      }
    }
  });
  root.addEventListener("dragend", () => {
    dragOriginalMediaId = null;
    clearOriginalDropMark();
  });

  grid.addEventListener("pointerdown", (event) => {
    const handle = event.target.closest && event.target.closest("[data-edge]");
    if (!handle || !grid.contains(handle)) return;
    beginEdgeDrag(handle, event);
  });
  grid.addEventListener("dragstart", (event) => {
    const handle = event.target.closest && event.target.closest(".studio-drag-handle");
    if (!handle) {
      event.preventDefault();
      return;
    }
    const card = handle.closest(".studio-clip");
    if (!card) return;
    dragCard = card;
    dragOrderBefore = orderedIds();
    card.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    try {
      event.dataTransfer.setData("text/plain", card.dataset.studioId || "");
    } catch (_) {
      /* older WebViews */
    }
  });

  grid.addEventListener("dragend", () => {
    if (dragCard) dragCard.classList.remove("is-dragging");
    const changed =
      dragOrderBefore && dragOrderBefore.join(",") !== orderedIds().join(",");
    dragCard = null;
    if (changed) persistOrder();
    else {
      dragOrderBefore = null;
      layoutTimeline();
    }
  });

  grid.addEventListener("dragover", (event) => {
    if (dragOriginalMediaId) {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      clearOriginalDropMark();
      const clip = event.target.closest && event.target.closest(".studio-clip");
      if (clip) {
        const rect = clip.getBoundingClientRect();
        const mark = event.clientX < rect.left + rect.width / 2 ? clip : clip.nextElementSibling;
        const target = mark && mark.classList && mark.classList.contains("studio-clip")
          ? mark
          : null;
        if (target) target.classList.add("is-drop-before");
      }
      return;
    }
    if (!dragCard) return;
    event.preventDefault();
    const target = event.target.closest && event.target.closest(".studio-clip");
    if (target && target !== dragCard) {
      const rect = target.getBoundingClientRect();
      if (event.clientX < rect.left + rect.width / 2) {
        grid.insertBefore(dragCard, target);
      } else {
        grid.insertBefore(dragCard, target.nextSibling);
      }
      grid.querySelectorAll(".studio-transition").forEach((el) => {
        if (el !== dragCard) el.style.display = "none";
      });
      layoutTimeline();
    }
  });

  grid.addEventListener("drop", (event) => {
    if (dragOriginalMediaId) {
      event.preventDefault();
      const mediaId = dragOriginalMediaId;
      const beforeId = originalDropBeforeId(event);
      clearOriginalDropMark();
      dragOriginalMediaId = null;
      const row = document.querySelector(
        `[data-original-media-id="${CSS.escape(mediaId)}"]`
      );
      if (!row || row.dataset.canPlay !== "1") return;
      if (!reuseDraft || String(reuseDraft.mediaId) !== String(mediaId) || reuseDraft.clip) {
        openOriginalDraft(row);
      }
      if (!reuseDraft) return;
      reuseDraft.beforeId = beforeId;
      addReuseScene();
      return;
    }
    event.preventDefault();
  });

  root.querySelectorAll("[data-timeline-zoom]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.getAttribute("data-timeline-zoom");
      if (action === "fit") fitTimeline();
      else if (action === "in") zoomTimeline(1);
      else if (action === "out") zoomTimeline(-1);
      else if (action === "window-10") zoomToWindowSeconds(10);
      else if (action === "window-1") zoomToWindowSeconds(1);
    });
  });
  if (timelineScrollEl) {
    timelineScrollEl.addEventListener(
      "wheel",
      (event) => {
        if (!event.ctrlKey && !event.metaKey) return;
        if (clips().length === 0) return;
        event.preventDefault();
        const direction = event.deltaY < 0 ? 1 : -1;
        zoomTimeline(direction, event.clientX);
      },
      { passive: false }
    );
  }
  (function bindCompactTracks() {
    const stage = document.querySelector(".studio-stage");
    const btn = document.getElementById("studio-tracks-compact");
    if (!stage || !btn) return;
    const key = "orga-drone.studio.compactTracks";
    function applyCompact(on) {
      stage.classList.toggle("is-compact-tracks", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.classList.toggle("is-active", on);
    }
    applyCompact(localStorage.getItem(key) === "1");
    btn.addEventListener("click", () => {
      const on = !stage.classList.contains("is-compact-tracks");
      applyCompact(on);
      try {
        localStorage.setItem(key, on ? "1" : "0");
      } catch (_err) {
        /* ignore quota / private mode */
      }
    });
  })();
  if (timelineScrollEl && typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => {
      if (state.timelineMode === "fit") layoutTimeline();
    });
    ro.observe(timelineScrollEl);
  } else {
    window.addEventListener("resize", () => {
      if (state.timelineMode === "fit") layoutTimeline();
    });
  }

  function readMapModel() {
    const fallback = {
      minBox: 0.12,
      maxBox: 0.72,
      gapS: 2,
      pad: 0.08,
      defaultX: 0.8362,
      defaultY: 0.74,
      defaultW: 0.1237,
      defaultH: 0.22,
      shortSide: 0.22,
      margin: 0.04,
      defaultOpacity: 1,
      legacyX: 0.68,
      legacyY: 0.68,
      legacyW: 0.28,
      legacyH: 0.28,
      bg: "#14181d",
      route: "#7eb6ff",
      marker: "#ff9f0a",
      border: "#c5d0dc",
    };
    try {
      const parsed = JSON.parse(root.dataset.mapModel || "");
      return Object.assign(fallback, parsed && typeof parsed === "object" ? parsed : {});
    } catch (_) {
      return fallback;
    }
  }

  function round4(value) {
    return Math.round(value * 10000) / 10000;
  }

  function clampOpacity(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 1;
    return Math.round(Math.min(1, Math.max(0, number)) * 100) / 100;
  }

  function clampMapBox(map) {
    const minBox = Number(mapModel.minBox) || 0.12;
    const maxBox = Number(mapModel.maxBox) || 0.72;
    const width = round4(Math.min(maxBox, Math.max(minBox, Number(map.w) || minBox)));
    const height = round4(Math.min(maxBox, Math.max(minBox, Number(map.h) || minBox)));
    return {
      enabled: map.enabled === true,
      w: width,
      h: height,
      x: round4(Math.min(1 - width, Math.max(0, Number(map.x) || 0))),
      y: round4(Math.min(1 - height, Math.max(0, Number(map.y) || 0))),
      opacity: clampOpacity(map.opacity),
    };
  }

  function defaultMapBox(contentW, contentH) {
    let widthPx = Number(contentW);
    let heightPx = Number(contentH);
    if (!Number.isFinite(widthPx) || !Number.isFinite(heightPx) || widthPx <= 0 || heightPx <= 0) {
      widthPx = 16;
      heightPx = 9;
    }
    const shortSide = Number(mapModel.shortSide) || 0.22;
    const margin = Number(mapModel.margin);
    const pad = Number.isFinite(margin) ? margin : 0.04;
    const minBox = Number(mapModel.minBox) || 0.12;
    const maxBox = Number(mapModel.maxBox) || 0.72;
    let side = shortSide * Math.min(widthPx, heightPx);
    const minSide = minBox * Math.max(widthPx, heightPx);
    const maxSide = maxBox * Math.min(widthPx, heightPx);
    side = Math.min(Math.max(side, minSide), Math.max(minSide, maxSide));
    side = Math.min(side, (1 - pad) * widthPx, (1 - pad) * heightPx);
    const w = side / widthPx;
    const h = side / heightPx;
    return clampMapBox({
      enabled: false,
      x: 1 - w - pad,
      y: 1 - h - pad,
      w: w,
      h: h,
      opacity: 1,
    });
  }

  function defaultMap() {
    const box = defaultMapBox(16, 9);
    box.enabled = false;
    box.opacity = 1;
    return box;
  }

  function sameMapBox(map, other) {
    return ["x", "y", "w", "h"].every(
      (key) => Math.abs(Number(map[key]) - Number(other[key])) < 0.0015
    );
  }

  function isUntouchedMapBox(map) {
    const legacy = {
      x: Number(mapModel.legacyX),
      y: Number(mapModel.legacyY),
      w: Number(mapModel.legacyW),
      h: Number(mapModel.legacyH),
    };
    if (![legacy.x, legacy.y, legacy.w, legacy.h].every((value) => Number.isFinite(value))) {
      legacy.x = 0.68;
      legacy.y = 0.68;
      legacy.w = 0.28;
      legacy.h = 0.28;
    }
    return sameMapBox(map, legacy) || sameMapBox(map, defaultMapBox(16, 9));
  }

  function sourceSizeForMap(clip) {
    const media = mediaForAnnotation(clip, false);
    const width = media ? media.videoWidth || media.naturalWidth || 0 : 0;
    const height = media ? media.videoHeight || media.naturalHeight || 0 : 0;
    if (width > 0 && height > 0) return { width: width, height: height };
    return null;
  }

  function mapContentPixels(clip) {
    const media = mediaForAnnotation(clip, false);
    const box = contentBoxFor(media);
    if (box.width > 0 && box.height > 0 && sourceSizeForMap(clip)) return box;
    const size = sourceSizeForMap(clip);
    if (size) return size;
    return { width: 16, height: 9 };
  }

  function placeSquare(start, side, content) {
    const width = content.width;
    const height = content.height;
    if (!width || !height) return clampMapBox(start);
    const minBox = Number(mapModel.minBox) || 0.12;
    const maxBox = Number(mapModel.maxBox) || 0.72;
    const minSide = minBox * Math.max(width, height);
    const maxSide = maxBox * Math.min(width, height);
    const fitted = Math.min(Math.max(side, minSide), Math.max(minSide, maxSide));
    return clampMapBox(
      Object.assign({}, start, {
        w: fitted / width,
        h: fitted / height,
      })
    );
  }

  function adoptSquareMap(clip) {
    if (!clip) return;
    const placement = readMap(clip);
    if (!placement.enabled || !isUntouchedMapBox(placement)) return;
    const size = sourceSizeForMap(clip);
    if (!size) return;
    const box = defaultMapBox(size.width, size.height);
    if (sameMapBox(placement, box)) return;
    writeMap(
      clip,
      Object.assign({}, placement, {
        x: box.x,
        y: box.y,
        w: box.w,
        h: box.h,
        enabled: true,
      })
    );
    if (selectedAdjustableClip() === clip) fillMapInspector(clip);
    queueMapSave(clip);
  }

  function readMap(clip) {
    if (!clip) return defaultMap();
    try {
      const parsed = JSON.parse(clip.dataset.map || "");
      if (!parsed || typeof parsed !== "object") return defaultMap();
      return clampMapBox(parsed);
    } catch (_) {
      return defaultMap();
    }
  }

  function writeMap(clip, map) {
    clip.dataset.map = JSON.stringify(clampMapBox(map));
  }

  function readGps(clip) {
    const empty = { line: [], marker: [], tiles: [] };
    if (!clip) return empty;
    try {
      const parsed = JSON.parse(clip.dataset.gps || "");
      if (!parsed || typeof parsed !== "object") return empty;
      const line = Array.isArray(parsed.line) ? parsed.line : [];
      const marker = Array.isArray(parsed.marker) ? parsed.marker : line;
      const tiles = Array.isArray(parsed.tiles) ? parsed.tiles : [];
      return { line, marker, tiles };
    } catch (_) {
      return empty;
    }
  }

  function sourceClock(clip, localS) {
    const sample = sectionSampleS(clip, Math.max(0, Number(localS) || 0));
    return loopPlayInS(clip) + sample * playbackSpeed(clip);
  }

  function mapClock(clip, localS) {
    if (clip && clip.dataset.kind === "video") return sourceClock(clip, localS);
    return Number(localS) || 0;
  }

  function markerAt(points, timeS) {
    if (!points.length) return null;
    const gap = Number(mapModel.gapS) || 2;
    const first = points[0];
    if (points.length === 1 || timeS <= Number(first.t)) return first;
    const last = points[points.length - 1];
    if (timeS >= Number(last.t)) return last;
    for (let index = 0; index < points.length - 1; index += 1) {
      const left = points[index];
      const right = points[index + 1];
      if (timeS >= Number(right.t)) continue;
      const span = Number(right.t) - Number(left.t);
      if (span <= 0 || span > gap) return left;
      const mix = (timeS - Number(left.t)) / span;
      return {
        x: Number(left.x) + (Number(right.x) - Number(left.x)) * mix,
        y: Number(left.y) + (Number(right.y) - Number(left.y)) * mix,
        t: timeS,
      };
    }
    return last;
  }

  function finitePoint(point) {
    const x = Number(point && point.x);
    const y = Number(point && point.y);
    const t = Number(point && point.t);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(t)) return null;
    return { x, y, t };
  }

  function paintMapSvg(svg, gps, timeS) {
    if (!svg) return false;
    const pad = (Number(mapModel.pad) || 0.08) * 100;
    const span = 100 - pad * 2;
    const sx = (value) => pad + value * span;
    const sy = (value) => pad + value * span;
    const bg = safeColor(mapModel.bg, "#14181d");
    const route = safeColor(mapModel.route, "#7eb6ff");
    const marker = safeColor(mapModel.marker, "#ff9f0a");
    const border = safeColor(mapModel.border, "#c5d0dc");
    const line = (gps.line || []).map(finitePoint).filter(Boolean);
    const samples = (gps.marker || []).map(finitePoint).filter(Boolean);
    const tiles = Array.isArray(gps.tiles) ? gps.tiles : [];
    const parts = [
      '<rect x="0" y="0" width="100" height="100" fill="' + bg + '"></rect>',
    ];
    tiles.forEach((tile) => {
      const z = Number(tile.z);
      const x = Number(tile.x);
      const y = Number(tile.y);
      const left = Number(tile.left);
      const top = Number(tile.top);
      const width = Number(tile.width);
      const height = Number(tile.height);
      if (![z, x, y, left, top, width, height].every((value) => Number.isFinite(value))) return;
      const origin = (value) => (pad + (value / 100) * span).toFixed(2);
      const size = (value) => ((value / 100) * span).toFixed(2);
      parts.push(
        '<image href="/map-tiles/' +
          z +
          "/" +
          x +
          "/" +
          y +
          '.png" x="' +
          origin(left) +
          '" y="' +
          origin(top) +
          '" width="' +
          size(width) +
          '" height="' +
          size(height) +
          '" preserveAspectRatio="none"></image>'
      );
    });
    parts.push(
      '<rect x="0" y="0" width="100" height="100" fill="none" stroke="' +
        border +
        '" stroke-width="1"></rect>'
    );
    if (tiles.length) {
      parts.push(
        '<text x="2" y="97" fill="#ffffff" font-size="4" font-family="sans-serif">© OpenStreetMap</text>'
      );
    }
    if (line.length >= 2) {
      const d = line
        .map((point, index) => (index ? "L" : "M") + sx(point.x).toFixed(2) + " " + sy(point.y).toFixed(2))
        .join(" ");
      parts.push(
        '<path d="' +
          d +
          '" fill="none" stroke="' +
          route +
          '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></path>'
      );
    }
    const dot = markerAt(samples, timeS);
    if (dot) {
      parts.push(
        '<circle cx="' +
          sx(Number(dot.x)).toFixed(2) +
          '" cy="' +
          sy(Number(dot.y)).toFixed(2) +
          '" r="3.2" fill="' +
          marker +
          '" stroke="#1a1206" stroke-width="0.6"></circle>'
      );
    }
    svg.innerHTML = parts.join("");
    return line.length > 0 || Boolean(dot);
  }

  function placeMapElement(el, clip, localS, interactive) {
    if (!el) return;
    const placement = readMap(clip);
    const show = placement.enabled && clip && (clip.dataset.kind === "photo" || clip.dataset.kind === "video");
    if (!show) {
      el.hidden = true;
      return;
    }
    const media = mediaForAnnotation(clip, el === previewMapB);
    const content = contentBoxFor(media);
    el.hidden = false;
    el.style.left = content.left + placement.x * content.width + "px";
    el.style.top = content.top + placement.y * content.height + "px";
    el.style.width = Math.max(1, placement.w * content.width) + "px";
    el.style.height = Math.max(1, placement.h * content.height) + "px";
    const alpha = String(clampOpacity(placement.opacity));
    const svg = el.querySelector("svg");
    const emptyLabel = el.querySelector(".studio-preview-map-empty");
    if (svg) svg.style.opacity = alpha;
    if (emptyLabel) emptyLabel.style.opacity = alpha;
    el.setAttribute("aria-label", msgMapLabel);
    const selected =
      interactive &&
      state.selected &&
      state.selected.type === "clip" &&
      String(state.selected.id) === String(clip.dataset.studioId);
    el.classList.toggle("is-locked", !selected);
    const handle = el.querySelector("[data-resize]");
    if (handle) handle.hidden = !selected;
    const gps = readGps(clip);
    const hasRoute = paintMapSvg(el.querySelector("svg"), gps, mapClock(clip, localS));
    const empty = el.querySelector(".studio-preview-map-empty");
    if (empty) {
      empty.textContent = msgMapEmpty;
      empty.hidden = hasRoute;
    }
  }

  function drawFlightMap(hit) {
    if (!hit || !hit.clip) {
      if (previewMap) previewMap.hidden = true;
      if (previewMapB) previewMapB.hidden = true;
      return;
    }
    const overlap = hit.overlapClip && hit.crossfadeProgress != null;
    adoptSquareMap(hit.clip);
    if (overlap) adoptSquareMap(hit.overlapClip);
    placeMapElement(previewMap, hit.clip, hit.localS || 0, true);
    if (previewMap) previewMap.style.opacity = overlap ? String(hit.crossfadeProgress) : "";
    if (overlap) {
      placeMapElement(previewMapB, hit.overlapClip, hit.overlapLocalS || 0, false);
    } else if (previewMapB) {
      previewMapB.hidden = true;
    }
  }

  function fillMapInspector(clip) {
    const wrap = document.getElementById("inspector-map");
    const enabled = document.getElementById("inspector-map-enabled");
    const fields = document.getElementById("inspector-map-fields");
    const empty = document.getElementById("inspector-map-empty");
    if (!wrap || !enabled || !fields) return;
    const placement = readMap(clip);
    if (document.activeElement !== enabled) enabled.checked = placement.enabled;
    fields.hidden = !placement.enabled;
    const gps = readGps(clip);
    if (empty) empty.hidden = !(placement.enabled && !(gps.line && gps.line.length));
    setNumber("map-x", Math.round(placement.x * 100));
    setNumber("map-y", Math.round(placement.y * 100));
    setNumber("map-w", Math.round(placement.w * 100));
    setNumber("map-h", Math.round(placement.h * 100));
    const opacity = document.getElementById("map-opacity");
    const opacityValue = document.getElementById("map-opacity-value");
    if (opacity && document.activeElement !== opacity) {
      const percent = Math.round(clampOpacity(placement.opacity) * 100);
      opacity.value = String(percent);
      if (opacityValue) opacityValue.textContent = String(percent);
    }
  }

  async function saveMap(studioId) {
    const clip = clips().find((item) => String(item.dataset.studioId) === String(studioId));
    if (!clip) return;
    const res = await fetch("/api/studio/" + studioId + "/map", {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(readMap(clip)),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || msgMapFailed);
    }
    writeMap(clip, body.map || readMap(clip));
    if (selectedAdjustableClip() === clip) fillMapInspector(clip);
    drawFlightMap(resolveAt(state.projectTimeS));
    setSaveState(true);
  }

  function queueMapSave(clip) {
    const studioId = clip.dataset.studioId;
    setSaveState(false);
    mapSaveChain = mapSaveChain
      .then(() => saveMap(studioId))
      .catch((err) => {
        showRootFlash((err && err.message) || msgMapFailed);
      });
  }

  function onMapPointerDown(event) {
    if (event.button != null && event.button !== 0) return;
    if (maskDragging) return;
    if (event.target && event.target.closest && event.target.closest(".studio-mask-box")) return;
    if (maskBoxAtPoint(event.clientX, event.clientY)) return;
    if (maskCanvasHit(event.clientX, event.clientY)) return;
    const hit = resolveAt(state.projectTimeS);
    const clip = hit && hit.clip;
    if (!clip || !previewMap || previewMap.classList.contains("is-locked")) return;
    event.preventDefault();
    event.stopPropagation();
    const resizing = Boolean(event.target && event.target.dataset && event.target.dataset.resize);
    const start = readMap(clip);
    const content = contentBoxFor(mediaForAnnotation(clip, false));
    if (!content.width || !content.height) return;
    const originX = event.clientX;
    const originY = event.clientY;
    const move = (ev) => {
      const dx = (ev.clientX - originX) / content.width;
      const dy = (ev.clientY - originY) / content.height;
      const next = resizing
        ? placeSquare(
            start,
            Math.abs(dy * content.height) > Math.abs(dx * content.width)
              ? start.h * content.height + dy * content.height
              : start.w * content.width + dx * content.width,
            content
          )
        : clampMapBox(Object.assign({}, start, { x: start.x + dx, y: start.y + dy }));
      writeMap(clip, next);
      placeMapElement(previewMap, clip, hit.localS || 0, true);
      fillMapInspector(clip);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      queueMapSave(clip);
      drawFlightMap(resolveAt(state.projectTimeS));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  previewMap?.addEventListener("pointerdown", onMapPointerDown);
  document.getElementById("inspector-map-enabled")?.addEventListener("change", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    const next = readMap(clip);
    const enabled = document.getElementById("inspector-map-enabled");
    next.enabled = Boolean(enabled && enabled.checked);
    if (next.enabled && isUntouchedMapBox(next)) {
      const size = sourceSizeForMap(clip) || { width: 16, height: 9 };
      const box = defaultMapBox(size.width, size.height);
      next.x = box.x;
      next.y = box.y;
      next.w = box.w;
      next.h = box.h;
    }
    writeMap(clip, next);
    fillMapInspector(clip);
    drawFlightMap(resolveAt(state.projectTimeS));
    queueMapSave(clip);
  });
  ["map-x", "map-y", "map-w", "map-h"].forEach((id) => {
    const input = document.getElementById(id);
    if (!input) return;
    input.addEventListener("change", () => {
      const clip = selectedAdjustableClip();
      if (!clip) return;
      const current = readMap(clip);
      const value = numberOr(input, 0) / 100;
      if (id === "map-w" || id === "map-h") {
        const content = mapContentPixels(clip);
        const side = id === "map-w" ? value * content.width : value * content.height;
        writeMap(clip, placeSquare(current, side, content));
      } else {
        const next = Object.assign({}, current);
        if (id === "map-x") next.x = value;
        if (id === "map-y") next.y = value;
        writeMap(clip, clampMapBox(next));
      }
      fillMapInspector(clip);
      drawFlightMap(resolveAt(state.projectTimeS));
      queueMapSave(clip);
    });
  });
  document.getElementById("map-opacity")?.addEventListener("input", (event) => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    const next = readMap(clip);
    next.opacity = clampOpacity(Number(event.target.value) / 100);
    const valueEl = document.getElementById("map-opacity-value");
    if (valueEl) valueEl.textContent = String(Math.round(next.opacity * 100));
    writeMap(clip, next);
    drawFlightMap(resolveAt(state.projectTimeS));
  });
  document.getElementById("map-opacity")?.addEventListener("change", () => {
    const clip = selectedAdjustableClip();
    if (!clip) return;
    queueMapSave(clip);
  });

  // Init
  loadUiState();
  try {
    const boot = root.dataset.musicPayload;
    if (boot) applyTracksPayload(JSON.parse(boot));
  } catch (_) {
    state.tracks = [];
  }
  applyVolume();
  applyTransitionsToDom();
  renderMusic();
  layoutTimeline();
  ensurePreviewBlit();
  setToggleLabel();
  let cutRestore = null;
  try {
    const raw = sessionStorage.getItem(CUT_RESTORE_KEY);
    if (raw) {
      cutRestore = JSON.parse(raw);
      sessionStorage.removeItem(CUT_RESTORE_KEY);
    }
  } catch (_) {
    cutRestore = null;
  }
  if (
    cutRestore &&
    cutRestore.selectId &&
    clips().some((c) => String(c.dataset.studioId) === String(cutRestore.selectId))
  ) {
    if (cutRestore.atClipStart) {
      selectClip(cutRestore.selectId);
    } else {
      selectClip(cutRestore.selectId, { movePlayhead: false });
      setProjectTime(Number(cutRestore.projectTimeS) || 0);
    }
  } else if (root.dataset.selectId && clips().some((c) => String(c.dataset.studioId) === String(root.dataset.selectId))) {
    selectClip(root.dataset.selectId);
    if (root.dataset.focusField === "title") {
      const titleEl = document.getElementById("inspector-titlecard-title");
      if (titleEl) {
        titleEl.focus();
        titleEl.select();
      }
    }
  } else if (clips().length) {
    selectClip(clips()[0].dataset.studioId);
  } else {
    updatePlayheadChrome();
    showPlaceholder();
    showInspector("inspector-empty");
    updateCutEnabled();
  }
  setSaveState(true);
})();
