/**
 * Creator Studio UI.
 * Persistence: reorder, photo duration, Title Cards, music, and transitions via APIs.
 * Playback: one project-time SoT; preview + playhead + active clip stay in sync.
 * Music is a persisted per-project soundtrack mixed into MP4 export.
 * The soundtrack lane is a read-only coverage span on the Story time canvas.
 * Visual transitions (Cut / Fade through black / Crossfade) persist in SQLite.
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
  const previewAnnotations = document.getElementById("studio-preview-annotations");
  const previewAnnotationsB = document.getElementById("studio-preview-annotations-b");
  const previewMasks = document.getElementById("studio-preview-masks");
  const previewMasksB = document.getElementById("studio-preview-masks-b");
  const previewMaskHandles = document.getElementById("studio-preview-mask-handles");
  const musicAudio = document.getElementById("studio-music-audio");
  const musicAudioNext = document.getElementById("studio-music-audio-next");
  const previewPlaceholder = document.getElementById("studio-preview-placeholder");
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
  const msgExportCancelled = root.dataset.exportCancelled || "Export cancelled.";
  const msgExportCancelling = root.dataset.exportCancelling || "Cancelling export…";
  const msgExportNoRes = root.dataset.exportNoResolution || "No exportable video resolution in this project.";
  const msgExportOverwrite = root.dataset.exportOverwrite || "A file with this name already exists. Overwrite it?";
  const msgExportRunning = root.dataset.exportRunning || "Exporting…";
  const msgExportDone = root.dataset.exportDone || "Export finished.";
  const msgExportPreparing = root.dataset.exportPreparing || "Preparing export…";
  const msgExportClip = root.dataset.exportClip || "Clip {current} of {total}";
  const msgExportCombining = root.dataset.exportCombining || "Combining clips…";
  const msgExportMixing = root.dataset.exportMixing || "Mixing music…";
  const msgExportUnavailable = root.dataset.exportUnavailable || "Export needs the desktop app for the save dialog.";
  const msgExportRunningHint = root.dataset.exportRunningHint || "Export is running…";
  const msgExportElapsed = root.dataset.exportElapsed || "Elapsed {time}";
  const msgExportEta = root.dataset.exportEta || "About {time} left";
  const msgExportEstimating = root.dataset.exportEstimating || "Estimating…";
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
  const msgStorySummary = root.dataset.storySummary || "{count} items · {duration}";
  const msgSourceIn = root.dataset.sourceIn || "Source in";
  const msgSourceOut = root.dataset.sourceOut || "Source out";
  const labelInspectorStory = root.dataset.inspectorStory || "Story";
  const labelInspectorMusic = root.dataset.inspectorMusic || "Music";
  const labelInStory = root.dataset.inStory || "In story";
  const msgCutHint = root.dataset.cutHint || "Cut splits this video at the playhead. Source files stay unchanged.";
  const msgImageFailed = root.dataset.imageFailed || "Could not save image adjustments.";
  const msgOverlayFailed = root.dataset.overlayFailed || "Could not save overlays.";
  const msgOverlayMissing = root.dataset.overlayMissing || "Overlay image is missing.";
  const msgOverlayClamped = root.dataset.overlayClamped || "Overlay timing was shortened to fit this clip.";
  const msgOverlayLimit = root.dataset.overlayLimit || "This clip already has 8 overlays.";
  const overlayModel = readOverlayModel();
  const msgMaskFailed = root.dataset.maskFailed || "Could not save privacy masks.";
  const msgMaskLimit = root.dataset.maskLimit || "A clip can have up to 8 privacy masks.";
  const labelMaskBlur = root.dataset.maskBlur || "Blur";
  const labelMaskPixelate = root.dataset.maskPixelate || "Pixelate";
  const imageAdjustModel = readImageAdjustModel();
  const maskModel = readMaskModel();

  const STORAGE_KEY = "orga-drone-studio-ui-v1";

  /** @type {{
   *  selected: {type: 'clip'|'transition'|'music'|null, id: string|null},
   *  projectTimeS: number,
   *  tracks: Array<{id: number, name: string, volume: number, fadeIn: number, fadeOut: number, loop: boolean, available: boolean, streamUrl: string|null, durationS: number}>,
   *  activeStudioId: string|null
   * }} */
  const state = {
    selected: { type: null, id: null },
    projectTimeS: 0,
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
    el.setAttribute("aria-label", type !== "cut" && dur > 0 ? `${label}, ${dur.toFixed(1)}s` : label);
    const chip = el.querySelector("[data-transition-label]");
    if (chip) chip.textContent = typeLabel;
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

  function sourceOutS(clip) {
    const raw = clip.dataset.sourceOut;
    if (raw !== "" && raw != null) {
      const n = Number(raw);
      if (Number.isFinite(n) && n > 0) return n;
    }
    const media = Number(clip.dataset.mediaDuration);
    if (Number.isFinite(media) && media > 0) return media;
    return sourceInS(clip) + clipDuration(clip);
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

  const TIMELINE_ZOOM_PX_S = [20, 40, 80, 160, 320];
  const TIMELINE_HIT_MIN_PX = 12;

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
      const left = Number.parseFloat(prev.style.left) || 0;
      const w = Number.parseFloat(prev.style.width) || 0;
      el.style.left = `${left + w}px`;
      el.style.display = dragCard ? "none" : "";
    });
    buildRuler();
    updatePlayheadChrome();
    updateZoomControls();
    layoutMusicSpans();
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

  function fitTimeline() {
    state.timelineMode = "fit";
    persistUiState();
    layoutTimeline();
    if (timelineScrollEl) timelineScrollEl.scrollLeft = 0;
  }

  function updateZoomControls() {
    const empty = clips().length === 0;
    const fitBtn = document.getElementById("studio-timeline-fit");
    const inBtn = document.getElementById("studio-timeline-zoom-in");
    const outBtn = document.getElementById("studio-timeline-zoom-out");
    const denser = nextZoomIndexAbove(timelineFitPxPerSecond());
    if (fitBtn) fitBtn.disabled = empty || state.timelineMode === "fit";
    if (outBtn) outBtn.disabled = empty || state.timelineMode === "fit";
    if (inBtn) {
      const atMaxZoom =
        state.timelineMode === "zoom" &&
        state.zoomIndex >= TIMELINE_ZOOM_PX_S.length - 1;
      inBtn.disabled = empty || atMaxZoom || (state.timelineMode === "fit" && denser < 0);
    }
  }

  function zoomTimeline(direction) {
    const fitPps = timelineFitPxPerSecond();
    if (direction > 0) {
      if (state.timelineMode === "fit") {
        const next = nextZoomIndexAbove(fitPps);
        if (next < 0) return;
        state.timelineMode = "zoom";
        state.zoomIndex = next;
      } else {
        state.zoomIndex = Math.min(TIMELINE_ZOOM_PX_S.length - 1, state.zoomIndex + 1);
      }
    } else if (state.timelineMode === "fit") {
      return;
    } else {
      const nextIndex = state.zoomIndex - 1;
      if (nextIndex < 0 || TIMELINE_ZOOM_PX_S[nextIndex] <= fitPps + 0.01) {
        state.timelineMode = "fit";
      } else {
        state.zoomIndex = nextIndex;
      }
    }
    persistUiState();
    layoutTimeline();
    centerPlayheadInView();
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

  function videoSrcFor(clip) {
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
    return { exposure: 0, contrast: 0, saturation: 0, warmth: 0 };
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
      };
    } catch (_) {
      return neutral;
    }
  }

  function writeImageAdjust(clip, adjust) {
    if (!clip) return;
    clip.dataset.imageAdjust = JSON.stringify({
      exposure: clampImageSlider(adjust.exposure),
      contrast: clampImageSlider(adjust.contrast),
      saturation: clampImageSlider(adjust.saturation),
      warmth: clampImageSlider(adjust.warmth),
    });
  }

  function imageAdjustIsNeutral(adjust) {
    return !adjust.exposure && !adjust.contrast && !adjust.saturation && !adjust.warmth;
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

  function cssFilterFor(adjust) {
    const model = imageAdjustModel;
    const parts = [];
    if (adjust.saturation) {
      const factor = 1 + (adjust.saturation / 100) * model.saturationDeltaAtFull;
      parts.push(`saturate(${factor.toFixed(4)})`);
    }
    if (adjust.contrast) {
      const factor = 1 + (adjust.contrast / 100) * model.contrastDeltaAtFull;
      parts.push(`contrast(${factor.toFixed(4)})`);
    }
    if (adjust.exposure) {
      const ev = (adjust.exposure / 100) * model.exposureEvAtFull;
      parts.push(`brightness(${Math.pow(2, ev).toFixed(4)})`);
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

  function gradePreviewElement(el, clip, filterId, matrixId) {
    if (!el) return;
    const kind = clip && clip.dataset.kind;
    const active = clip && (kind === "video" || kind === "photo") && !el.hidden;
    if (!active) {
      el.style.filter = "";
      return;
    }
    const adjust = readImageAdjust(clip);
    if (imageAdjustIsNeutral(adjust)) {
      el.style.filter = "";
      return;
    }
    const css = cssFilterFor(adjust);
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
    gradePreviewElement(
      previewVideo,
      primary,
      "studio-preview-grade",
      "studio-preview-grade-matrix"
    );
    gradePreviewElement(
      previewImage,
      primary,
      "studio-preview-grade",
      "studio-preview-grade-matrix"
    );
    gradePreviewElement(
      previewVideoB,
      overlap,
      "studio-preview-grade-b",
      "studio-preview-grade-matrix-b"
    );
    gradePreviewElement(
      previewImageB,
      overlap,
      "studio-preview-grade-b",
      "studio-preview-grade-matrix-b"
    );
  }

  const IMAGE_ADJUST_FIELDS = [
    ["exposure", "inspector-image-exposure", "inspector-image-exposure-value"],
    ["contrast", "inspector-image-contrast", "inspector-image-contrast-value"],
    ["saturation", "inspector-image-saturation", "inspector-image-saturation-value"],
    ["warmth", "inspector-image-warmth", "inspector-image-warmth-value"],
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
    writeImageAdjust(clip, body.image || adjust);
    if (
      state.selected &&
      state.selected.type === "clip" &&
      String(state.selected.id) === String(studioId)
    ) {
      fillImageAdjust(clip);
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
    return {
      id: String(mask.id || ""),
      effect: mask.effect === "pixelate" ? "pixelate" : "blur",
      strength: clampMaskStrength(mask.strength),
      x: Math.min(1 - width, Math.max(0, Number(mask.x) || 0)),
      y: Math.min(1 - height, Math.max(0, Number(mask.y) || 0)),
      w: width,
      h: height,
    };
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

  function paintPrivacyMask(ctx, media, mask, box, srcW, srcH) {
    const dx = mask.x * box.width;
    const dy = mask.y * box.height;
    const dw = Math.max(1, mask.w * box.width);
    const dh = Math.max(1, mask.h * box.height);
    const sx = mask.x * srcW;
    const sy = mask.y * srcH;
    const sw = Math.max(1, mask.w * srcW);
    const sh = Math.max(1, mask.h * srcH);
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
        scratch.drawImage(media, sx, sy, sw, sh, 0, 0, cols, rows);
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(maskScratch, 0, 0, cols, rows, dx, dy, dw, dh);
      } else {
        const radius = effectAmount(mask.strength, box.width, box.height, maskModel.blurFraction);
        const padX = (radius / box.width) * srcW;
        const padY = (radius / box.height) * srcH;
        ctx.filter = `blur(${radius}px)`;
        ctx.drawImage(
          media,
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
    const box = mediaContentBox(media);
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
    const selected =
      clip &&
      state.selected &&
      state.selected.type === "clip" &&
      String(state.selected.id) === String(clip.dataset.studioId);
    const masks = selected ? readMasks(clip) : [];
    if (!selected || !box || !masks.length) {
      layer.hidden = true;
      if (!maskDragging) layer.replaceChildren();
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
      boxEl.style.left = `${mask.x * 100}%`;
      boxEl.style.top = `${mask.y * 100}%`;
      boxEl.style.width = `${mask.w * 100}%`;
      boxEl.style.height = `${mask.h * 100}%`;
      boxEl.setAttribute("role", "button");
      boxEl.tabIndex = 0;
      boxEl.setAttribute("aria-label", maskEffectLabel(mask.effect));
      const handle = document.createElement("span");
      handle.className = "studio-mask-resize";
      handle.dataset.resize = "1";
      boxEl.appendChild(handle);
      boxEl.addEventListener("pointerdown", (event) => onMaskPointerDown(event, clip, mask.id));
      layer.appendChild(boxEl);
    });
  }

  function onMaskPointerDown(event, clip, maskId) {
    if (event.button != null && event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const layer = previewMaskHandles;
    if (!layer) return;
    selectedMaskId = maskId;
    fillMaskInspector(clip);
    const masks = readMasks(clip);
    const startMask = masks.find((item) => item.id === maskId);
    if (!startMask) return;
    const resizing = Boolean(event.target && event.target.dataset && event.target.dataset.resize);
    const bounds = layer.getBoundingClientRect();
    if (bounds.width < 2 || bounds.height < 2) return;
    maskDragging = true;
    const originX = event.clientX;
    const originY = event.clientY;
    const pointerId = event.pointerId;
    if (event.currentTarget.setPointerCapture) {
      try {
        event.currentTarget.setPointerCapture(pointerId);
      } catch (_) {
        /* ignore */
      }
    }
    const move = (ev) => {
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
      const el = layer.querySelector(`[data-mask-id="${CSS.escape(maskId)}"]`);
      if (el && current) {
        el.style.left = `${current.x * 100}%`;
        el.style.top = `${current.y * 100}%`;
        el.style.width = `${current.w * 100}%`;
        el.style.height = `${current.h * 100}%`;
      }
      drawPrivacyMasks();
    };
    const up = () => {
      maskDragging = false;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      queueMaskSave(clip);
      drawPrivacyMasks();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function drawPrivacyMasks() {
    const hit = resolveAt(state.projectTimeS);
    if (!hit || !hit.clip) {
      hidePrivacyMasks();
      return;
    }
    const primary = visiblePrimaryMedia();
    const primaryOpacity = primary ? primary.style.opacity : "1";
    drawMaskCanvas(previewMasks, primary, readMasks(hit.clip), primaryOpacity);
    const overlap = hit.overlapClip && hit.crossfadeProgress != null;
    const secondary = overlap ? visibleSecondaryMedia() : null;
    drawMaskCanvas(
      previewMasksB,
      secondary,
      overlap ? readMasks(hit.overlapClip) : [],
      secondary ? secondary.style.opacity : "1"
    );
    renderMaskHandles(hit.clip, primary ? mediaContentBox(primary) : null);
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
    masks.forEach((mask) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button ghost";
      button.textContent = maskEffectLabel(mask.effect);
      if (mask.id === selectedMaskId) button.setAttribute("aria-current", "true");
      button.addEventListener("click", () => {
        selectedMaskId = mask.id;
        fillMaskInspector(clip);
        drawPrivacyMasks();
      });
      item.appendChild(button);
      list.appendChild(item);
    });
    const current = masks.find((item) => item.id === selectedMaskId) || null;
    editor.hidden = !current;
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

  function showPlaceholder() {
    if (previewImage) previewImage.hidden = true;
    clearVideoElement();
    hideTitlecard();
    hideOverlayLayers();
    hideAnnotations();
    hidePrivacyMasks();
    if (previewPlaceholder) previewPlaceholder.hidden = false;
    applyPreviewGrades(null);
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
      return;
    }
    if (loadedImageSrc !== src) {
      loadedImageSrc = src;
      previewImage.src = src;
    }
  }

  function seekVideoLocal(localS, clip) {
    if (!previewVideo) return;
    const inS = clip ? sourceInS(clip) : 0;
    const outS = clip ? sourceOutS(clip) : null;
    const target = Math.max(inS, inS + Math.max(0, localS));
    const apply = () => {
      try {
        let max = Number.isFinite(previewVideo.duration) ? previewVideo.duration : target;
        if (outS != null && Number.isFinite(outS)) {
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
    const needLoad = !src || loadedVideoSrc !== src;
    if (needLoad) {
      loadedVideoSrc = src || "";
      suppressVideoClock = true;
      previewVideo.src = src || "";
      previewVideo.load();
      const token = ++syncToken;
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
      return;
    }
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
        const inS = sourceInS(clip);
        const target = inS + Math.max(0, localS);
        const apply = () => {
          try {
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

  function applyTransitionPreview(hit) {
    const overlap = hit && hit.overlapClip && hit.crossfadeProgress != null;
    if (!overlap) {
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
    } else {
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
  }

  function syncPreviewMedia({ seek = false } = {}) {
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
    const mediaTime = previewVideo.currentTime || 0;
    const local = Math.max(0, mediaTime - inS);
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
    if (musicLoopEnabled()) {
      const track = state.tracks[0];
      const mus = trackDurationS(track);
      if (!(mus > 0) || !track.available) return null;
      return { track, index: 0, offset: t % mus, startS: 0, spanS: story };
    }
    let cursor = 0;
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
    card.append(handle, body);
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
    let cursor = 0;
    cards.forEach((card, index) => {
      const track = state.tracks.find((item) => String(item.id) === String(card.dataset.musicId));
      if (!track) return;
      const nameEl = card.querySelector("strong");
      const meta = card.querySelector(".studio-music-meta");
      const badge = card.querySelector(".studio-music-badge");
      const fadeInEl = card.querySelector(".studio-music-fade-in");
      const fadeOutEl = card.querySelector(".studio-music-fade-out");
      const body = card.querySelector(".studio-music-clip-body");
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
        spanS = musicBedDuration(story, musDur, true);
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

  function applyTransitionsToDom() {
    grid.querySelectorAll(".studio-transition").forEach((el) => {
      const afterId = el.dataset.transitionAfter;
      const prev = clips().find((c) => String(c.dataset.studioId) === String(afterId));
      const type = (prev && prev.dataset.appliedType) || el.dataset.appliedType || "cut";
      el.dataset.transitionType = type;
      refreshTransitionChrome(el);
    });
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
    let step = 30;
    if (pps >= 80) step = 1;
    else if (pps >= 40) step = 5;
    else if (pps >= 20) step = 10;
    for (let s = 0; s <= total + 0.0001; s += step) {
      const mark = document.createElement("span");
      mark.className = "studio-ruler-mark";
      mark.style.left = `${timeToX(s)}px`;
      mark.textContent = formatTime(s).replace(/^00:/, "");
      rulerEl.appendChild(mark);
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
    state.selected = { type: "clip", id: String(id) };
    const clip = clips().find((c) => String(c.dataset.studioId) === String(id));
    if (!clip) return;
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
          const inEl = panel.querySelector('[data-field="source-in"]');
          const outEl = panel.querySelector('[data-field="source-out"]');
          const hintEl = panel.querySelector('[data-field="cut-hint"]');
          if (inEl) inEl.textContent = `${msgSourceIn}: ${sourceInS(clip).toFixed(1)} s`;
          if (outEl) outEl.textContent = `${msgSourceOut}: ${sourceOutS(clip).toFixed(1)} s`;
          if (hintEl) hintEl.textContent = msgCutHint;
        }
      }
      const imageWrap = document.getElementById("inspector-image-adjust");
      if (imageWrap) imageWrap.hidden = !(isPhoto || isVideo);
      if (isPhoto || isVideo) fillImageAdjust(clip);
      const overlayWrap = document.getElementById("inspector-overlays");
      if (overlayWrap) overlayWrap.hidden = !(isPhoto || isVideo);
      if (isPhoto || isVideo) fillOverlayInspector(clip);
      else selectedOverlayId = null;
      fillMaskInspector(clip);
      setClipRemoveAction(removeForm, clip.dataset.studioId);
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
  }

  function canCutAtHit(hit) {
    if (!hit || hit.atEnd) return false;
    if (!state.selected || state.selected.type !== "clip") return false;
    if (String(state.selected.id) !== String(hit.clip.dataset.studioId)) return false;
    if (hit.clip.dataset.kind !== "video") return false;
    if (hit.clip.dataset.canPlay !== "1") return false;
    if (hit.clip.dataset.available !== "1") return false;
    const local = hit.localS;
    const dur = hit.duration;
    return local > MIN_CUT_SEGMENT_S && local < dur - MIN_CUT_SEGMENT_S;
  }

  function updateCutEnabled() {
    if (!cutBtn) return;
    const hit = resolveAt(state.projectTimeS);
    const ok = canCutAtHit(hit);
    cutBtn.disabled = !ok;
  }

  async function cutSelectedAtPlayhead() {
    const hit = resolveAt(state.projectTimeS);
    if (!canCutAtHit(hit)) return;
    const studioId = hit.clip.dataset.studioId;
    const localS = hit.localS;
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
      } else {
        hint.hidden = true;
        hint.textContent = "";
      }
    }
    updateCutEnabled();
  }

  function musicErrorDetail(body) {
    const detail = body && body.detail;
    if (detail === "music_limit") return msgMusicLimit;
    if (typeof detail === "string" && detail) return detail;
    return msgMusicFailed;
  }

  function selectMusic(trackId) {
    const track = state.tracks.find((item) => String(item.id) === String(trackId));
    if (!track) return;
    state.selected = { type: "music", id: String(track.id) };
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
    const loopEl = document.getElementById("inspector-music-loop");
    const loopWrap = document.getElementById("inspector-music-loop-wrap");
    if (vol) vol.value = String(Math.round(track.volume * 100));
    if (fadeIn) fadeIn.value = String(track.fadeIn);
    if (fadeOut) fadeOut.value = String(track.fadeOut);
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
      state.selected = { type: null, id: null };
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
      rebuildTransitions();
      applyTransitionsToDom();
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
    rebuildTransitions();
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
      layoutTimeline();
      setProjectTime(state.projectTimeS);
      setSaveState(true);
      showFlash("");
    } catch (_) {
      clip.dataset.photoDuration = prev;
      showFlash(msgDurationFailed);
    }
  }

  function seekFromClientX(clientX, { resumeAfter = false } = {}) {
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

  root.addEventListener("click", (event) => {
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
    let etaText = msgExportEstimating;
    let etaS = job.eta_s;
    if (etaS == null && percent >= 5 && elapsed > 0 && percent < 100) {
      etaS = (elapsed / (percent / 100)) * (1 - percent / 100);
    }
    if (job.state === "completed") {
      etaText = msgExportDoneIn.replace("{time}", formatExportDuration(elapsed));
    } else if (etaS != null && Number.isFinite(Number(etaS))) {
      etaText = msgExportEta.replace("{time}", formatExportDuration(etaS));
    }
    if (exportProgressMeta) {
      exportProgressMeta.textContent = `${elapsedText} · ${etaText}`;
    }
  }

  function setExportRunningUi(running) {
    if (exportRunBtn) exportRunBtn.disabled = running;
    if (exportResolution) exportResolution.disabled = running;
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

    let overwrite = false;
    const tryStart = async () => {
      const res = await fetch("/api/studio/export", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          height,
          output_path: pickedPath,
          overwrite,
          project_id: projectId || exportOptionsCache.project_id || null,
        }),
      });
      const data = await res.json().catch(() => null);
      return { res, data };
    };

    try {
      let { res, data } = await tryStart();
      if (res.status === 409 && data && String(data.detail || "").toLowerCase().includes("already exists")) {
        const ok = window.confirm(msgExportOverwrite);
        if (!ok) {
          setExportStatus(msgExportCancelled);
          setExportRunningUi(false);
          return;
        }
        overwrite = true;
        ({ res, data } = await tryStart());
      }
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
    if (event.target.closest(".studio-drag-handle")) return;
    const card = event.target.closest(".studio-music-select");
    if (!card) return;
    event.stopPropagation();
    selectMusic(card.dataset.musicId);
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
      syncPreviewMedia();
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
      writeImageAdjust(clip, imageAdjustFromControls());
      applyPreviewGrades(resolveAt(state.projectTimeS));
      setSaveState(false);
    });
    input.addEventListener("change", () => {
      const clip = selectedAdjustableClip();
      if (!clip) return;
      writeImageAdjust(clip, imageAdjustFromControls());
      queueImageAdjustSave(clip);
    });
  });

  document.getElementById("mask-add-blur")?.addEventListener("click", () => addPrivacyMask("blur"));
  document.getElementById("mask-add-pixelate")?.addEventListener("click", () => {
    addPrivacyMask("pixelate");
  });
  document.getElementById("mask-remove")?.addEventListener("click", () => removeSelectedMask());
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
  window.addEventListener("resize", () => drawPrivacyMasks());
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
    const duration = clipDuration(clip);
    const visible = readOverlays(clip).filter((overlay) => overlayActive(overlay, localS, duration));
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
    visible.forEach((overlay) => layer.appendChild(buildAnnotation(overlay, layer, interactive, localS)));
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
    const duration = clipDuration(selectedOverlayClip() || { dataset: {} });
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
    const duration = Math.max(0.1, clipDuration(clip));
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
    previewImage.addEventListener("load", () => syncAnnotations(resolveAt(state.projectTimeS)));
  }
  if (previewVideo) {
    previewVideo.addEventListener("loadedmetadata", () => syncAnnotations(resolveAt(state.projectTimeS)));
  }

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
  document.getElementById("inspector-music-loop")?.addEventListener("change", (event) => {
    const track = selectedMusicTrack();
    if (!track) return;
    track.loop = !!event.target.checked;
    syncMusicAudio();
    layoutTimeline();
    patchMusicSettings();
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
      if (event.target.closest(".studio-clip, .studio-transition, .studio-playhead, .studio-ruler, #studio-music-track")) return;
      const wasPlaying = state.playing;
      pausePlayback();
      seekFromClientX(event.clientX, {
        resumeAfter: wasPlaying && state.projectTimeS < totalDuration() - 0.001,
      });
    });
  }

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
    event.preventDefault();
  });

  root.querySelectorAll("[data-timeline-zoom]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.getAttribute("data-timeline-zoom");
      if (action === "fit") fitTimeline();
      else if (action === "in") zoomTimeline(1);
      else if (action === "out") zoomTimeline(-1);
    });
  });
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
    selectClip(cutRestore.selectId, { movePlayhead: false });
    setProjectTime(Number(cutRestore.projectTimeS) || 0);
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
