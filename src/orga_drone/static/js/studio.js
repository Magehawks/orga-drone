/**
 * Creator Studio UI (#14).
 * Persistence: reorder + photo duration via existing APIs.
 * Playback / transitions / music / export: local UI state only (no render pipeline).
 */
(function () {
  const root = document.getElementById("studio-root");
  const grid = document.getElementById("studio-grid");
  if (!root || !grid) return;

  const flashEl = document.getElementById("studio-flash");
  const saveStateEl = document.getElementById("studio-save-state");
  const titleInput = document.getElementById("studio-project-title");
  const previewImage = document.getElementById("studio-preview-image");
  const previewPlaceholder = document.getElementById("studio-preview-placeholder");
  const transportTime = document.getElementById("studio-transport-time");
  const playheadEl = document.getElementById("studio-playhead");
  const tracksEl = document.getElementById("studio-tracks");
  const rulerEl = document.getElementById("studio-ruler");
  const volumeInput = document.getElementById("studio-volume");
  const exportDialog = document.getElementById("studio-export-dialog");
  const previewFrame = document.getElementById("studio-preview-frame");

  const defaultPhotoDuration = Number(root.dataset.defaultPhotoDuration || "3") || 3;
  const msgReorderFailed = root.dataset.reorderFailed || "Could not save Studio order.";
  const msgDurationFailed = root.dataset.durationFailed || "Could not save photo duration.";
  const labelSaved = root.dataset.savedLabel || "Saved";
  const labelUnsaved = root.dataset.unsavedLabel || "Unsaved changes";
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
   *  playheadS: number,
   *  playing: boolean,
   *  volume: number,
   *  title: string,
   *  music: null | {name: string, volume: number, fadeIn: number, fadeOut: number},
   *  transitions: Record<string, string>
   * }} */
  const state = {
    selected: { type: null, id: null },
    playheadS: 0,
    playing: false,
    volume: 0.8,
    title: titleInput ? titleInput.value : "Your story",
    music: null,
    transitions: {},
  };

  let dragCard = null;
  let dragOrderBefore = null;
  let autoScrollRaf = 0;
  let pointerDrag = null;
  let playTimer = 0;
  let playheadDragging = false;

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
    saveStateEl.textContent = saved ? labelSaved : labelUnsaved;
  }

  function formatTime(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function clipDuration(clip) {
    const raw = clip.dataset.effectiveDuration;
    if (raw === "" || raw == null) {
      if (clip.dataset.kind === "photo") return defaultPhotoDuration;
      return 0;
    }
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }

  function totalDuration() {
    return clips().reduce((sum, clip) => sum + clipDuration(clip), 0);
  }

  function loadUiState() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (data && typeof data === "object") {
        if (typeof data.title === "string" && titleInput) {
          state.title = data.title;
          titleInput.value = data.title;
        }
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
          title: state.title,
          music: state.music,
          transitions: state.transitions,
          volume: state.volume,
        })
      );
    } catch (_) {
      /* ignore */
    }
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

  function clipAtTime(t) {
    let cursor = 0;
    for (const clip of clips()) {
      const dur = clipDuration(clip);
      if (t < cursor + dur || clip === clips()[clips().length - 1]) {
        return { clip, start: cursor, duration: dur };
      }
      cursor += dur;
    }
    return null;
  }

  function updatePreview() {
    const hit = clipAtTime(state.playheadS);
    if (!hit || !previewImage) return;
    const clip = hit.clip;
    const thumb = clip.dataset.thumb || "";
    clips().forEach((c) => c.classList.toggle("is-active", c === clip));
    if (thumb) {
      previewImage.src = thumb;
      previewImage.hidden = false;
      if (previewPlaceholder) previewPlaceholder.hidden = true;
    } else {
      previewImage.hidden = true;
      if (previewPlaceholder) previewPlaceholder.hidden = false;
    }
    if (
      state.selected.type === "clip" &&
      state.selected.id &&
      String(clip.dataset.studioId) === String(state.selected.id)
    ) {
      /* keep */
    }
  }

  function updatePlayheadUi() {
    const total = totalDuration();
    const t = Math.max(0, Math.min(total, state.playheadS));
    state.playheadS = t;
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
    updatePreview();
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

  function selectClip(id) {
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

    // Seek playhead to clip start for context.
    let cursor = 0;
    for (const c of clips()) {
      if (c === clip) {
        state.playheadS = cursor;
        break;
      }
      cursor += clipDuration(c);
    }
    updatePlayheadUi();
  }

  function selectTransition(el) {
    state.selected = { type: "transition", id: el.dataset.transitionAfter || "" };
    clips().forEach((c) => c.classList.remove("is-selected"));
    grid.querySelectorAll(".studio-transition").forEach((t) => t.classList.toggle("is-selected", t === el));
    document.getElementById("studio-music-track")?.classList.remove("is-selected");
    showInspector("inspector-transition");
    const select = document.getElementById("inspector-transition-type");
    if (select) select.value = el.dataset.transitionType || "none";
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
      updatePlayheadUi();
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
    // Remove transitions while restoring clip order.
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
      clip.style.setProperty("--clip-flex", String(flex));
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
      updatePlayheadUi();
      setSaveState(true);
      showFlash("");
    } catch (_) {
      clip.dataset.photoDuration = prev;
      showFlash(msgDurationFailed);
    }
  }

  function stopPlayback() {
    state.playing = false;
    if (playTimer) {
      clearInterval(playTimer);
      playTimer = 0;
    }
    const btn = root.querySelector('[data-transport="toggle"]');
    if (btn) btn.textContent = "Play";
  }

  function startPlayback() {
    if (totalDuration() <= 0) return;
    state.playing = true;
    const btn = root.querySelector('[data-transport="toggle"]');
    if (btn) btn.textContent = "Pause";
    if (playTimer) clearInterval(playTimer);
    playTimer = window.setInterval(() => {
      state.playheadS += 0.1;
      if (state.playheadS >= totalDuration()) {
        state.playheadS = totalDuration();
        updatePlayheadUi();
        stopPlayback();
        return;
      }
      updatePlayheadUi();
    }, 100);
  }

  function seekFromClientX(clientX) {
    if (!tracksEl) return;
    const rect = tracksEl.getBoundingClientRect();
    const style = window.getComputedStyle(document.documentElement);
    const rootFont = Number.parseFloat(style.fontSize) || 16;
    const labelPx = 4.25 * rootFont;
    const usable = rect.width - labelPx;
    if (usable <= 0) return;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left - labelPx) / usable));
    state.playheadS = ratio * totalDuration();
    updatePlayheadUi();
  }

  // ——— Events ———

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
      const list = clips();
      if (action === "start") state.playheadS = 0;
      else if (action === "end") state.playheadS = totalDuration();
      else if (action === "prev") {
        const hit = clipAtTime(state.playheadS);
        if (!hit) return;
        const idx = list.indexOf(hit.clip);
        if (state.playheadS > hit.start + 0.2) state.playheadS = hit.start;
        else if (idx > 0) {
          let cursor = 0;
          for (let i = 0; i < idx - 1; i += 1) cursor += clipDuration(list[i]);
          state.playheadS = cursor;
        } else state.playheadS = 0;
      } else if (action === "next") {
        const hit = clipAtTime(state.playheadS);
        if (!hit) return;
        const idx = list.indexOf(hit.clip);
        if (idx < list.length - 1) {
          let cursor = 0;
          for (let i = 0; i <= idx; i += 1) cursor += clipDuration(list[i]);
          state.playheadS = cursor;
        } else state.playheadS = totalDuration();
      } else if (action === "toggle") {
        if (state.playing) stopPlayback();
        else startPlayback();
        return;
      } else if (action === "fullscreen" && previewFrame) {
        if (!document.fullscreenElement) {
          previewFrame.requestFullscreen?.().catch(() => {});
        } else {
          document.exitFullscreen?.().catch(() => {});
        }
        return;
      }
      stopPlayback();
      updatePlayheadUi();
    }
  });

  if (titleInput) {
    titleInput.addEventListener("input", () => {
      state.title = titleInput.value;
      persistUiState();
      setSaveState(false);
    });
    titleInput.addEventListener("change", () => setSaveState(true));
  }

  if (volumeInput) {
    volumeInput.addEventListener("input", () => {
      state.volume = Number(volumeInput.value) / 100;
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

  // Playhead drag
  if (playheadEl && tracksEl) {
    const onMove = (event) => {
      if (!playheadDragging) return;
      seekFromClientX(event.clientX);
    };
    const onUp = () => {
      playheadDragging = false;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    playheadEl.addEventListener("pointerdown", (event) => {
      playheadDragging = true;
      stopPlayback();
      playheadEl.setPointerCapture?.(event.pointerId);
      seekFromClientX(event.clientX);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
    rulerEl?.addEventListener("click", (event) => {
      stopPlayback();
      seekFromClientX(event.clientX);
    });
  }

  // DnD reorder (clip handles only)
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
      // Keep transitions out of the way while dragging; rebuild on persist.
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
  applyTransitionsToDom();
  renderMusic();
  buildRuler();
  updatePlayheadUi();
  if (clips().length) {
    selectClip(clips()[0].dataset.studioId);
  } else {
    showInspector("inspector-empty");
  }
  setSaveState(true);
})();
