/**
 * Creator Studio UI.
 * Persistence: reorder + photo duration via existing APIs.
 * Playback: one project-time SoT; preview + playhead + active clip stay in sync.
 * Music / transitions / export remain UI stubs (no render pipeline).
 */
(function () {
  const root = document.getElementById("studio-root");
  const grid = document.getElementById("studio-grid");
  if (!root || !grid) return;

  const flashEl = document.getElementById("studio-flash");
  const saveStateEl = document.getElementById("studio-save-state");
  const titleInput = document.getElementById("studio-project-title");
  const previewImage = document.getElementById("studio-preview-image");
  const previewVideo = document.getElementById("studio-preview-video");
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
  const msgTitleFailed = root.dataset.titleFailed || "Could not save project title.";
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
   *  music: null | {name: string, volume: number, fadeIn: number, fadeOut: number},
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
      return;
    }
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
        if (data.music && typeof data.music.name === "string") {
          state.music = {
            name: data.music.name,
            volume: Number(data.music.volume) || 0.8,
            fadeIn: Number(data.music.fadeIn) || 0,
            fadeOut: Number(data.music.fadeOut) || 0,
          };
        }
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
          music: state.music,
          transitions: state.transitions,
          volume: state.volume,
        })
      );
    } catch (_) {
      /* ignore */
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
    if (vol) vol.value = String(Math.round(state.music.volume * 100));
    if (fadeIn) fadeIn.value = String(state.music.fadeIn);
    if (fadeOut) fadeOut.value = String(state.music.fadeOut);
  }

  function renderMusic() {
    const empty = document.getElementById("studio-music-empty");
    const clip = document.getElementById("studio-music-clip");
    const name = document.getElementById("studio-music-name");
    if (!empty || !clip) return;
    if (state.music) {
      empty.hidden = true;
      clip.hidden = false;
      if (name) name.textContent = state.music.name;
    } else {
      empty.hidden = false;
      clip.hidden = true;
      if (state.selected.type === "music") {
        state.selected = { type: null, id: null };
        showInspector("inspector-empty");
      }
    }
  }

  function clearMusic() {
    state.music = null;
    persistUiState();
    setSaveState(false);
    renderMusic();
    showInspector("inspector-empty");
    document.getElementById("studio-music-track")?.classList.remove("is-selected");
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
    exportDialog?.showModal();
  });

  document.getElementById("studio-music-file")?.addEventListener("change", (event) => {
    const input = event.target;
    const file = input.files && input.files[0];
    if (!file) return;
    state.music = {
      name: file.name,
      volume: 0.8,
      fadeIn: 0,
      fadeOut: 0,
    };
    persistUiState();
    setSaveState(false);
    renderMusic();
    selectMusic();
    input.value = "";
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
        persistUiState();
        setSaveState(false);
      });
    }
  );

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
