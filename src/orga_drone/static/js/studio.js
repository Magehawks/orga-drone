/**
 * Creator Studio UI.
 * Persistence: reorder + photo duration via existing APIs.
 * Playback: one project-time SoT; preview + playhead + active clip stay in sync.
 * Music is a persisted per-project soundtrack mixed into MP4 export.
 * Transitions remain UI stubs.
 * Project browser/switcher (Issue #19) runs even when no Story grid is present.
 */
(function () {
  const root = document.getElementById("studio-root");
  if (!root) return;

  const studioMode = root.dataset.studioMode || "editor";
  const msgTitleFailed = root.dataset.titleFailed || "Could not save project title.";
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
  const projectsOpenBtn = document.getElementById("studio-projects-open");
  if (projectsOpenBtn && projectsDialog) {
    projectsOpenBtn.addEventListener("click", () => {
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
  const previewVideo = document.getElementById("studio-preview-video");
  const musicAudio = document.getElementById("studio-music-audio");
  const previewPlaceholder = document.getElementById("studio-preview-placeholder");
  const transportTime = document.getElementById("studio-transport-time");
  const playheadEl = document.getElementById("studio-playhead");
  const tracksEl = document.getElementById("studio-tracks");
  const rulerEl = document.getElementById("studio-ruler");
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
  const msgExportCancelled = root.dataset.exportCancelled || "Export cancelled.";
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
  const transitionLabels = {
    none: root.dataset.transitionNone || "None",
    fade: root.dataset.transitionFade || "Fade",
    crossfade: root.dataset.transitionCrossfade || "Cross fade",
    slide: root.dataset.transitionSlide || "Slide",
  };
  const kindLabels = {
    photo: root.dataset.kindPhoto || "Photo",
    video: root.dataset.kindVideo || "Video",
    unknown: root.dataset.kindUnknown || "Memory",
  };

  const STORAGE_KEY = "orga-drone-studio-ui-v1";

  /** @type {{
   *  selected: {type: 'clip'|'transition'|'music'|null, id: string|null},
   *  projectTimeS: number,
   *  playing: boolean,
   *  volume: number,
   *  title: string,
   *  music: null | {name: string, volume: number, fadeIn: number, fadeOut: number, loop: boolean, available: boolean, streamUrl: string|null},
   *  transitions: Record<string, string>,
   *  activeStudioId: string|null
   * }} */
  const state = {
    selected: { type: null, id: null },
    projectTimeS: 0,
    playing: false,
    volume: 0.8,
    title: titleInput ? titleInput.value : "Your story",
    music: null,
    transitions: {},
    activeStudioId: null,
  };

  let dragCard = null;
  let dragOrderBefore = null;
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
      return 0;
    }
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : 0;
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
    return clips().reduce((sum, clip) => sum + clipDuration(clip), 0);
  }

  function clipStartTime(clip) {
    let cursor = 0;
    for (const c of clips()) {
      if (c === clip) return cursor;
      cursor += clipDuration(c);
    }
    return 0;
  }

  /**
   * Map global project time to active clip + local time.
   * Skips zero-duration clips. At/past total → last clip, atEnd true.
   */
  function resolveAt(projectTimeS) {
    const list = clips();
    const spans = [];
    let cursor = 0;
    list.forEach((clip, index) => {
      const dur = clipDuration(clip);
      if (dur <= 0) return;
      spans.push({ clip, index, start: cursor, duration: dur });
      cursor += dur;
    });
    if (!spans.length) return null;
    const total = cursor;
    const t = Math.max(0, Number(projectTimeS) || 0);
    if (t >= total) {
      const last = spans[spans.length - 1];
      return {
        clip: last.clip,
        index: last.index,
        start: last.start,
        duration: last.duration,
        localS: last.duration,
        atEnd: true,
      };
    }
    for (const span of spans) {
      if (t < span.start + span.duration) {
        return {
          clip: span.clip,
          index: span.index,
          start: span.start,
          duration: span.duration,
          localS: t - span.start,
          atEnd: false,
        };
      }
    }
    const last = spans[spans.length - 1];
    return {
      clip: last.clip,
      index: last.index,
      start: last.start,
      duration: last.duration,
      localS: last.duration,
      atEnd: true,
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
    const pct = total > 0 ? (t / total) * 100 : 0;
    if (playheadEl) {
      playheadEl.style.left = `calc(4.25rem + (100% - 4.25rem) * ${pct / 100})`;
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

  function showPlaceholder() {
    if (previewImage) previewImage.hidden = true;
    clearVideoElement();
    if (previewPlaceholder) previewPlaceholder.hidden = false;
  }

  function showImage(src) {
    if (!previewImage) return;
    clearVideoElement();
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

  function syncPreviewMedia({ seek = false } = {}) {
    void seek;
    const hit = resolveAt(state.projectTimeS);
    if (!hit) {
      state.activeStudioId = null;
      clips().forEach((c) => c.classList.remove("is-active"));
      showPlaceholder();
      updateCutEnabled();
      return;
    }
    const { clip, localS, atEnd } = hit;
    state.activeStudioId = clip.dataset.studioId || null;
    clips().forEach((c) => c.classList.toggle("is-active", c === clip));

    const kind = clip.dataset.kind || "unknown";
    const canPlay = clip.dataset.canPlay === "1";

    // Photos first: never leave a video layer covering the image.
    if (kind === "photo") {
      const src = imageSrcFor(clip);
      if (src) {
        showImage(src);
        updateCutEnabled();
        return;
      }
      showPlaceholder();
      updateCutEnabled();
      return;
    }

    if (kind === "video" && canPlay) {
      const src = videoSrcFor(clip);
      if (!src) {
        const thumb = clip.dataset.thumb || "";
        if (thumb) showImage(thumb);
        else showPlaceholder();
        updateCutEnabled();
        return;
      }
      showVideo(src, localS, { play: state.playing && !atEnd, clip });
      updateCutEnabled();
      return;
    }

    // Unavailable / unknown: show thumb if any for duration window.
    const thumb = clip.dataset.thumb || "";
    if (thumb) showImage(thumb);
    else showPlaceholder();
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
        clips().forEach((c) => c.classList.toggle("is-active", c === hit.clip));
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
    const hit = resolveAt(state.projectTimeS);
    if (!hit || hit.clip.dataset.kind !== "video") return;
    if (String(hit.clip.dataset.studioId) !== String(state.activeStudioId)) return;
    const inS = sourceInS(hit.clip);
    const outS = sourceOutS(hit.clip);
    const mediaTime = previewVideo.currentTime || 0;
    const local = Math.max(0, mediaTime - inS);
    const next = hit.start + local;
    if (Math.abs(next - state.projectTimeS) < 0.01) {
      updatePlayheadChrome();
    } else {
      state.projectTimeS = next;
      updatePlayheadChrome();
    }
    updateCutEnabled();
    syncMusicAudio();
    // Clip boundary at source out (trimmed) or near local duration.
    if (outS != null && mediaTime >= outS - 0.05) {
      advanceToNextOrStop(hit);
      return;
    }
    if (hit.duration > 0 && local >= hit.duration - 0.05) {
      advanceToNextOrStop(hit);
    }
  }

  function onVideoEnded() {
    // Clearing/reloading the <video> when switching to a photo can fire "ended".
    // Never advance Story time unless we are actually playing a video clip.
    if (!state.playing || suppressVideoClock || !previewVideo) return;
    if (!previewVideo.getAttribute("src") && !previewVideo.currentSrc) return;
    const hit = resolveAt(state.projectTimeS);
    if (!hit || hit.clip.dataset.kind !== "video") return;
    if (String(hit.clip.dataset.studioId) !== String(state.activeStudioId)) return;
    advanceToNextOrStop(hit);
  }

  function loadUiState() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (data && typeof data === "object") {
        // Title is persisted in SQLite (studio_projects); do not restore from session.
        if (data.transitions && typeof data.transitions === "object") {
          state.transitions = data.transitions;
        }
        if (typeof data.volume === "number") {
          state.volume = Math.max(0, Math.min(1, data.volume));
          if (volumeInput) volumeInput.value = String(Math.round(state.volume * 100));
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
          transitions: state.transitions,
          volume: state.volume,
        })
      );
    } catch (_) {
      /* ignore */
    }
  }

  function musicFromPayload(payload) {
    if (!payload || !payload.present) return null;
    const volume = Number(payload.volume);
    const fadeIn = Number(payload.fade_in_s);
    const fadeOut = Number(payload.fade_out_s);
    return {
      name: payload.display_name || "Music",
      volume: Number.isFinite(volume) ? volume : 0.8,
      fadeIn: Number.isFinite(fadeIn) ? fadeIn : 0,
      fadeOut: Number.isFinite(fadeOut) ? fadeOut : 0,
      loop: !!payload.loop,
      available: payload.available !== false,
      streamUrl: payload.stream_url || null,
    };
  }

  function musicBedDuration(storyS, musicS, loop) {
    if (loop) return Math.max(0, storyS);
    if (!(musicS > 0)) return 0;
    return Math.min(musicS, Math.max(0, storyS));
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

  function pauseMusicAudio() {
    if (!musicAudio) return;
    try {
      musicAudio.pause();
    } catch (_) {
      /* ignore */
    }
  }

  function ensureMusicAudioSrc() {
    if (!musicAudio || !state.music || !state.music.available || !state.music.streamUrl) {
      if (musicAudio) {
        musicAudio.removeAttribute("src");
        try {
          musicAudio.load();
        } catch (_) {
          /* ignore */
        }
      }
      return false;
    }
    if (musicAudio.getAttribute("src") !== state.music.streamUrl) {
      try {
        musicAudio.pause();
      } catch (_) {
        /* ignore */
      }
      musicAudio.removeAttribute("src");
      musicAudio.src = state.music.streamUrl;
      musicAudio.load();
    }
    return true;
  }

  function syncMusicAudio() {
    if (!musicAudio || !state.music || !state.music.available) {
      pauseMusicAudio();
      return;
    }
    if (!ensureMusicAudioSrc()) {
      pauseMusicAudio();
      return;
    }
    const story = totalDuration();
    const t = state.projectTimeS;
    const musDur = Number.isFinite(musicAudio.duration) ? musicAudio.duration : 0;
    const bed = musicBedDuration(story, musDur, state.music.loop);
    let playPos = 0;
    let inBed = false;
    if (story > 0 && t < story && musDur > 0) {
      if (state.music.loop) {
        inBed = true;
        playPos = t % musDur;
      } else if (t < musDur) {
        inBed = true;
        playPos = t;
      }
    }
    const gain = inBed
      ? musicFadeGain(t, bed, state.music.fadeIn, state.music.fadeOut)
      : 0;
    musicAudio.volume = Math.max(0, Math.min(1, state.volume * state.music.volume * gain));
    if (!inBed || !state.playing) {
      pauseMusicAudio();
      if (inBed && Number.isFinite(playPos)) {
        try {
          if (Math.abs((musicAudio.currentTime || 0) - playPos) > 0.35) {
            musicAudio.currentTime = playPos;
          }
        } catch (_) {
          /* ignore */
        }
      }
      return;
    }
    try {
      if (Math.abs((musicAudio.currentTime || 0) - playPos) > 0.35) {
        musicAudio.currentTime = playPos;
      }
    } catch (_) {
      /* ignore */
    }
    const playPromise = musicAudio.play();
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

  function applyTransitionsToDom() {
    grid.querySelectorAll(".studio-transition").forEach((el) => {
      const afterId = el.dataset.transitionAfter;
      const type = state.transitions[afterId] || "none";
      el.dataset.transitionType = type;
      const label = el.querySelector("[data-transition-label]");
      if (label) label.textContent = transitionLabels[type] || type;
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
      li.dataset.transitionType = state.transitions[prev.dataset.studioId] || "none";
      li.tabIndex = 0;
      li.setAttribute("role", "button");
      li.setAttribute("aria-label", "Transition");
      const chip = document.createElement("span");
      chip.className = "studio-transition-chip";
      chip.dataset.transitionLabel = "";
      chip.textContent =
        transitionLabels[li.dataset.transitionType] || li.dataset.transitionType;
      li.appendChild(chip);
      grid.insertBefore(li, next);
    }
  }

  function buildRuler() {
    if (!rulerEl) return;
    const total = totalDuration();
    rulerEl.innerHTML = "";
    if (total <= 0) return;
    const step = total <= 30 ? 5 : total <= 120 ? 10 : 30;
    for (let s = 0; s <= total; s += step) {
      const mark = document.createElement("span");
      mark.className = "studio-ruler-mark";
      mark.style.left = `${(s / total) * 100}%`;
      mark.textContent = formatTime(s).replace(/^00:/, "");
      rulerEl.appendChild(mark);
    }
  }

  function showInspector(kind) {
    ["inspector-empty", "inspector-clip", "inspector-transition", "inspector-music"].forEach(
      (id) => {
        const el = document.getElementById(id);
        if (el) el.hidden = id !== kind;
      }
    );
  }

  function selectClip(id, { movePlayhead = true } = {}) {
    state.selected = { type: "clip", id: String(id) };
    const clip = clips().find((c) => String(c.dataset.studioId) === String(id));
    if (!clip) return;
    clips().forEach((c) => c.classList.toggle("is-selected", c === clip));
    grid.querySelectorAll(".studio-transition").forEach((el) => el.classList.remove("is-selected"));
    document.getElementById("studio-music-track")?.classList.remove("is-selected");

    showInspector("inspector-clip");
    const panel = document.getElementById("inspector-clip");
    if (!panel) return;
    panel.querySelector('[data-field="kind"]').textContent =
      kindLabels[clip.dataset.kind] || kindLabels.unknown;
    panel.querySelector('[data-field="filename"]').textContent = clip.dataset.filename || "";
    panel.querySelector('[data-field="recorded"]').textContent = clip.dataset.recordedAt || "—";
    const dur = clipDuration(clip);
    panel.querySelector('[data-field="duration-line"]').textContent =
      dur > 0 ? `${dur.toFixed(1)} s` : "—";

    const photoWrap = document.getElementById("inspector-photo-duration-wrap");
    const photoInput = document.getElementById("inspector-photo-duration");
    const photoReset = document.getElementById("inspector-photo-reset");
    const removeForm = document.getElementById("inspector-remove-form");
    const isPhoto = clip.dataset.kind === "photo";
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
    if (removeForm) removeForm.action = `/studio/${clip.dataset.studioId}/remove`;

    if (movePlayhead) {
      const wasPlaying = state.playing;
      if (wasPlaying) pausePlayback();
      setProjectTime(clipStartTime(clip));
      if (wasPlaying) startPlayback();
    } else {
      updateCutEnabled();
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
    clips().forEach((c) => c.classList.remove("is-selected"));
    grid.querySelectorAll(".studio-transition").forEach((t) => t.classList.toggle("is-selected", t === el));
    document.getElementById("studio-music-track")?.classList.remove("is-selected");
    showInspector("inspector-transition");
    const select = document.getElementById("inspector-transition-type");
    if (select) select.value = el.dataset.transitionType || "none";
    updateCutEnabled();
  }

  function selectMusic() {
    if (!state.music) return;
    state.selected = { type: "music", id: "music" };
    clips().forEach((c) => c.classList.remove("is-selected"));
    grid.querySelectorAll(".studio-transition").forEach((t) => t.classList.remove("is-selected"));
    document.getElementById("studio-music-track")?.classList.add("is-selected");
    showInspector("inspector-music");
    const panel = document.getElementById("inspector-music");
    if (!panel) return;
    panel.querySelector('[data-field="music-name"]').textContent = state.music.name;
    const vol = document.getElementById("inspector-music-volume");
    const fadeIn = document.getElementById("inspector-music-fade-in");
    const fadeOut = document.getElementById("inspector-music-fade-out");
    const loopEl = document.getElementById("inspector-music-loop");
    if (vol) vol.value = String(Math.round(state.music.volume * 100));
    if (fadeIn) fadeIn.value = String(state.music.fadeIn);
    if (fadeOut) fadeOut.value = String(state.music.fadeOut);
    if (loopEl) loopEl.checked = !!state.music.loop;
  }

  function renderMusic() {
    const empty = document.getElementById("studio-music-empty");
    const clip = document.getElementById("studio-music-clip");
    const name = document.getElementById("studio-music-name");
    const missing = document.getElementById("studio-music-missing");
    if (!empty || !clip) return;
    if (state.music) {
      empty.hidden = true;
      clip.hidden = false;
      if (name) name.textContent = state.music.name;
      if (missing) missing.hidden = !!state.music.available;
    } else {
      empty.hidden = false;
      clip.hidden = true;
      if (missing) missing.hidden = true;
      if (state.selected.type === "music") {
        state.selected = { type: null, id: null };
        showInspector("inspector-empty");
      }
    }
    syncMusicAudio();
  }

  async function pickAndSetMusic() {
    if (!projectId) return;
    try {
      const picked = await fetch("/api/desktop/pick-open-file", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({}),
      });
      const pickedBody = await picked.json().catch(() => null);
      if (picked.status === 503) {
        showFlash(msgMusicPickerUnavailable);
        return;
      }
      if (!picked.ok || !pickedBody || pickedBody.status === "cancelled") return;
      if (pickedBody.status !== "ok" || !pickedBody.path) {
        showFlash(msgMusicFailed);
        return;
      }
      setSaveState(false);
      const saved = await fetch(`/api/studio/projects/${projectId}/music`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ path: pickedBody.path }),
      });
      const savedBody = await saved.json().catch(() => null);
      if (!saved.ok || !savedBody || !savedBody.ok) {
        showFlash((savedBody && savedBody.detail) || msgMusicFailed);
        return;
      }
      state.music = musicFromPayload(savedBody);
      renderMusic();
      selectMusic();
      setSaveState(true);
      showFlash("");
    } catch (_) {
      showFlash(msgMusicFailed);
    }
  }

  async function patchMusicSettings() {
    if (!projectId || !state.music) return;
    setSaveState(false);
    try {
      const res = await fetch(`/api/studio/projects/${projectId}/music`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          volume: state.music.volume,
          fade_in_s: state.music.fadeIn,
          fade_out_s: state.music.fadeOut,
          loop: !!state.music.loop,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        showFlash((data && data.detail) || msgMusicFailed);
        return;
      }
      state.music = musicFromPayload(data);
      renderMusic();
      setSaveState(true);
    } catch (_) {
      showFlash(msgMusicFailed);
    }
  }

  async function clearMusic() {
    if (!projectId) {
      state.music = null;
      renderMusic();
      showInspector("inspector-empty");
      document.getElementById("studio-music-track")?.classList.remove("is-selected");
      return;
    }
    setSaveState(false);
    try {
      const res = await fetch(`/api/studio/projects/${projectId}/music`, {
        method: "DELETE",
        headers: { Accept: "application/json" },
      });
      if (!res.ok) throw new Error("delete music failed");
      state.music = null;
      renderMusic();
      showInspector("inspector-empty");
      document.getElementById("studio-music-track")?.classList.remove("is-selected");
      setSaveState(true);
      showFlash("");
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
      buildRuler();
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
      buildRuler();
      setProjectTime(state.projectTimeS);
      setSaveState(true);
      showFlash("");
    } catch (_) {
      clip.dataset.photoDuration = prev;
      showFlash(msgDurationFailed);
    }
  }

  function seekFromClientX(clientX, { resumeAfter = false } = {}) {
    if (!tracksEl) return;
    const rect = tracksEl.getBoundingClientRect();
    const style = window.getComputedStyle(document.documentElement);
    const rootFont = Number.parseFloat(style.fontSize) || 16;
    const labelPx = 4.25 * rootFont;
    const usable = rect.width - labelPx;
    if (usable <= 0) return;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left - labelPx) / usable));
    setProjectTime(ratio * totalDuration());
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
      selectClip(pick.getAttribute("data-select-clip"));
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
    if (exportCancelBtn) exportCancelBtn.disabled = running;
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
        if (data.state === "completed") {
          stopExportElapsedTimer();
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
    setExportStatus("");
    setExportProgressVisible(false);
    if (exportProgressBar) exportProgressBar.style.width = "0%";
    if (exportProgressLabel) exportProgressLabel.textContent = "";
    if (exportProgressMeta) exportProgressMeta.textContent = "";
    if (exportHint) exportHint.textContent = "";
    setExportRunningUi(false);
    if (exportRunBtn) exportRunBtn.disabled = true;
    if (exportResolution) exportResolution.innerHTML = "";
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
      if (exportHint) {
        exportHint.textContent = `${data.suggested_filename || "export.mp4"} → ${
          data.default_directory || ""
        }`;
      }
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
          filename: exportOptionsCache.suggested_filename || "export.mp4",
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
      pollExportJob(data.job_id);
    } catch (_) {
      setExportStatus(msgExportFailed, { error: true });
      setExportRunningUi(false);
    }
  }

  exportRunBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    runStudioExport();
  });

  document.getElementById("studio-music-add")?.addEventListener("click", () => {
    pickAndSetMusic();
  });
  document.getElementById("studio-music-replace")?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    pickAndSetMusic();
  });
  document.getElementById("studio-music-select")?.addEventListener("click", selectMusic);
  document.getElementById("studio-music-remove")?.addEventListener("click", clearMusic);
  document.getElementById("inspector-music-remove")?.addEventListener("click", clearMusic);

  document.getElementById("inspector-transition-type")?.addEventListener("change", (event) => {
    const value = event.target.value;
    if (state.selected.type !== "transition" || !state.selected.id) return;
    state.transitions[state.selected.id] = value;
    persistUiState();
    setSaveState(false);
    applyTransitionsToDom();
  });

  ["inspector-music-volume", "inspector-music-fade-in", "inspector-music-fade-out"].forEach(
    (id) => {
      document.getElementById(id)?.addEventListener("input", () => {
        if (!state.music) return;
        const vol = document.getElementById("inspector-music-volume");
        const fadeIn = document.getElementById("inspector-music-fade-in");
        const fadeOut = document.getElementById("inspector-music-fade-out");
        state.music.volume = Number(vol?.value || 80) / 100;
        state.music.fadeIn = Number(fadeIn?.value || 0);
        state.music.fadeOut = Number(fadeOut?.value || 0);
        syncMusicAudio();
      });
      document.getElementById(id)?.addEventListener("change", () => {
        patchMusicSettings();
      });
    }
  );
  document.getElementById("inspector-music-loop")?.addEventListener("change", (event) => {
    if (!state.music) return;
    state.music.loop = !!event.target.checked;
    syncMusicAudio();
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
    rulerEl?.addEventListener("click", (event) => {
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
    else dragOrderBefore = null;
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
    }
  });

  grid.addEventListener("drop", (event) => {
    event.preventDefault();
  });

  // Init
  loadUiState();
  try {
    const boot = root.dataset.musicPayload;
    if (boot) state.music = musicFromPayload(JSON.parse(boot));
  } catch (_) {
    state.music = null;
  }
  applyVolume();
  applyTransitionsToDom();
  renderMusic();
  buildRuler();
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
