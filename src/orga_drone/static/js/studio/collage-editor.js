/**
 * Studio collage inspector + preview shell (ADR 0038 / #458).
 * Persistence goes through /api/studio/{id}/collage; media fill is WP3.
 */

import {
  PRESET_NAMES,
  aspectCss,
  collectDividers,
  iterLeaves,
  resolveRects,
} from "./collage-layout.js";
import { createCollagePlayback } from "./collage-playback.js";

/**
 * @param {object} opts
 * @param {HTMLElement | null} opts.root
 * @param {() => HTMLElement | null} opts.getSelectedClip
 * @param {(id: string) => void} opts.showInspector
 * @param {(msg: string) => void} opts.showFlash
 * @param {(clip: HTMLElement, data: any) => void} [opts.onSpecApplied]
 * @param {typeof fetch} [opts.fetchImpl]
 */
export function createCollageEditor(opts) {
  const root = opts.root;
  const fetchImpl = opts.fetchImpl || fetch;
  const preview = document.getElementById("studio-preview-collage");
  const stage = document.getElementById("studio-preview-collage-stage");
  const durationEl = document.getElementById("inspector-collage-duration");
  const presetEl = document.getElementById("inspector-collage-preset");
  const aspectEl = document.getElementById("inspector-collage-aspect");
  const gapEl = document.getElementById("inspector-collage-gap");
  const bgEl = document.getElementById("inspector-collage-background");
  const cellActions = document.getElementById("inspector-collage-cell-actions");
  const removeForm = document.getElementById("inspector-collage-remove-form");
  const fitEl = document.getElementById("inspector-collage-fit");
  const zoomEl = document.getElementById("inspector-collage-zoom");
  const panXEl = document.getElementById("inspector-collage-pan-x");
  const panYEl = document.getElementById("inspector-collage-pan-y");
  const libraryDialog = document.getElementById("studio-collage-library-dialog");
  const libraryGrid = document.getElementById("studio-collage-library-grid");
  const libraryFilter = document.getElementById("studio-collage-library-filter");
  const libraryEmpty = document.getElementById("studio-collage-library-empty");
  const libraryAdd = document.getElementById("studio-collage-library-add");

  const MEDIA_FILE_TYPES = [
    "Media (*.jpg;*.jpeg;*.png;*.webp;*.heic;*.mp4;*.mov;*.m4v;*.webm)",
    "Images (*.jpg;*.jpeg;*.png;*.webp;*.heic)",
    "Videos (*.mp4;*.mov;*.m4v;*.webm)",
  ];

  let selectedLeafId = null;
  let selectedLeafOwnerId = null;
  let drag = null;
  let saveChain = Promise.resolve();
  let libraryItems = [];
  let librarySelected = {};
  const playback = createCollagePlayback({ stage });

  function clipForLeafAction() {
    const selected = opts.getSelectedClip?.();
    if (
      selectedLeafOwnerId &&
      selected &&
      String(selected.dataset?.studioId || "") === String(selectedLeafOwnerId)
    ) {
      return selected;
    }
    if (selectedLeafOwnerId) {
      const owner = document.querySelector(
        `.studio-clip[data-studio-id="${CSS.escape(String(selectedLeafOwnerId))}"]`
      );
      if (owner) return owner;
    }
    return selected;
  }

  function msg(key, fallback) {
    const value = root?.dataset?.[key];
    return value && String(value).trim() ? String(value) : fallback;
  }

  function gestureGroup(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function isStillSelected(clip) {
    const selected = opts.getSelectedClip?.();
    return !!(
      selected &&
      clip &&
      String(selected.dataset?.studioId || "") === String(clip.dataset?.studioId || "")
    );
  }

  function aspectBox(spec, hostW, hostH) {
    const css = aspectCss(spec);
    const parts = String(css)
      .split("/")
      .map((part) => Number(String(part).trim()));
    const aw = parts[0] > 0 ? parts[0] : 16;
    const ah = parts[1] > 0 ? parts[1] : 9;
    const fit = Math.min(hostW / aw, hostH / ah);
    const width = Math.max(1, Math.floor(aw * fit));
    const height = Math.max(1, Math.floor(ah * fit));
    return { width, height, css };
  }

  function parseSpec(clip) {
    if (!clip) return null;
    const raw = clip.dataset.collageSpec;
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  function isCollage(clip) {
    return clip?.dataset?.kind === "collage";
  }

  async function patchCollage(clip, body, group) {
    const id = clip?.dataset?.studioId;
    if (!id) return null;
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };
    if (group) headers["X-Studio-History-Group"] = group;
    const res = await fetchImpl(`/api/studio/${id}/collage`, {
      method: "PATCH",
      headers,
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      throw new Error(data.detail || msg("collageFailed", "Could not save collage."));
    }
    if (data.collage_spec) {
      clip.dataset.collageSpec = JSON.stringify(data.collage_spec);
    }
    if (data.duration_s !== null && data.duration_s !== undefined) {
      clip.dataset.collageDuration = String(data.duration_s);
      clip.dataset.effectiveDuration = String(data.duration_s);
      const durLabel = clip.querySelector("[data-clip-duration]");
      if (durLabel) durLabel.textContent = `${Number(data.duration_s).toFixed(1)}s`;
    }
    opts.onSpecApplied?.(clip, data);
    return data;
  }

  function queueSave(clip, body, group) {
    saveChain = saveChain
      .catch(() => {})
      .then(() => patchCollage(clip, body, group))
      .catch((err) => {
        opts.showFlash(err?.message || msg("collageFailed", "Could not save collage."));
      });
    return saveChain;
  }

  function renderPreview(clip) {
    if (!preview || !stage) return;
    const spec = parseSpec(clip);
    if (!isCollage(clip) || !spec) {
      preview.hidden = true;
      stage.replaceChildren();
      return;
    }
    preview.hidden = false;
    const bg = spec.background === "transparent" ? "#0a0c0e" : spec.background || "#0a0c0e";
    stage.style.background = bg;
    const host = preview.getBoundingClientRect();
    const hostW = Math.max(1, Math.round(host.width || preview.clientWidth || 640));
    const hostH = Math.max(1, Math.round(host.height || preview.clientHeight || (hostW * 9) / 16));
    const box = aspectBox(spec, hostW, hostH);
    stage.style.aspectRatio = box.css;
    stage.style.width = `${box.width}px`;
    stage.style.height = `${box.height}px`;
    const width = box.width;
    const height = box.height;
    const rects = resolveRects(spec, width, height);
    const leaves = iterLeaves(spec.root);
    const emptyLabel = msg("collageEmptyCell", "Empty cell");
    const missingLabel = msg("collageMissingMedia", "Missing media");
    stage.replaceChildren();
    for (const leaf of leaves) {
      const rect = rects[String(leaf.id)];
      if (!rect) continue;
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "studio-collage-cell";
      if (selectedLeafId && String(selectedLeafId) === String(leaf.id)) {
        cell.classList.add("is-selected");
      }
      cell.dataset.leafId = String(leaf.id);
      cell.style.left = `${(rect.x / width) * 100}%`;
      cell.style.top = `${(rect.y / height) * 100}%`;
      cell.style.width = `${(rect.w / width) * 100}%`;
      cell.style.height = `${(rect.h / height) * 100}%`;
      const label = document.createElement("span");
      const media = leaf.media;
      if (!media) {
        label.textContent = emptyLabel;
      } else if (media.source === "library" && media.media_id) {
        const thumb = document.createElement("img");
        thumb.alt = "";
        thumb.loading = "lazy";
        thumb.src = `/media/${media.media_id}/thumb`;
        thumb.addEventListener("error", () => {
          thumb.remove();
          label.textContent = missingLabel;
          cell.classList.add("is-missing");
        });
        cell.appendChild(thumb);
        label.textContent = media.display_name || media.kind || "Media";
      } else if (media.source === "external" && media.has_path) {
        label.textContent = media.display_name || media.kind || "Media";
      } else {
        label.textContent = missingLabel;
        cell.classList.add("is-missing");
      }
      cell.appendChild(label);
      cell.addEventListener("click", () => {
        selectedLeafId = String(leaf.id);
        selectedLeafOwnerId = String(clip.dataset.studioId || "");
        if (cellActions) cellActions.hidden = false;
        fillLeafFraming(clip);
        const selected = opts.getSelectedClip?.();
        if (
          selectedLeafOwnerId &&
          selected &&
          String(selected.dataset?.studioId || "") !== selectedLeafOwnerId
        ) {
          opts.onSelectClip?.(selectedLeafOwnerId);
        }
        renderPreview(clip);
      });
      stage.appendChild(cell);
    }
    const dividers = collectDividers(spec.root, 0, 0, width, height, Number(spec.gap_px) || 0);
    for (const div of dividers) {
      const handle = document.createElement("div");
      handle.className = `studio-collage-divider is-${div.dir}`;
      handle.dataset.splitId = div.id;
      handle.style.left = `${(div.x / width) * 100}%`;
      handle.style.top = `${(div.y / height) * 100}%`;
      handle.style.width = `${(div.w / width) * 100}%`;
      handle.style.height = `${(div.h / height) * 100}%`;
      handle.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        handle.setPointerCapture(event.pointerId);
        drag = {
          clip,
          splitId: div.id,
          dir: div.dir,
          origin: div.origin,
          span: div.span,
          startRatio: div.ratio,
        };
      });
      stage.appendChild(handle);
    }
    playback.mount({
      spec,
      studioId: clip.dataset.studioId,
      rects,
      width,
      height,
      forceStill: false,
    });
    playback.sync({
      localS: Number(opts.getCollageLocalS?.() || 0),
      playing: Boolean(opts.isPlaying?.()),
      seek: true,
      spec,
    });
  }

  function fillInspector(clip) {
    if (!isCollage(clip)) return;
    const ownerId = String(clip.dataset.studioId || "");
    if (selectedLeafOwnerId && selectedLeafOwnerId !== ownerId) {
      selectedLeafId = null;
      selectedLeafOwnerId = null;
    }
    opts.showInspector("inspector-collage");
    const spec = parseSpec(clip) || {};
    if (durationEl) {
      durationEl.value = String(clip.dataset.collageDuration || spec.duration_s || "5");
    }
    if (presetEl) {
      const names = Array.isArray(spec.presets) ? spec.presets : PRESET_NAMES;
      // Keep selected blank; presets replace the tree.
      presetEl.value = names.includes(presetEl.value) ? presetEl.value : "1+1";
    }
    if (aspectEl) {
      const aspect = typeof spec.aspect === "string" ? spec.aspect : "16:9";
      aspectEl.value = aspect;
    }
    if (gapEl) gapEl.value = String(spec.gap_px ?? 8);
    if (bgEl && typeof spec.background === "string" && spec.background.startsWith("#")) {
      bgEl.value = spec.background.slice(0, 7);
    }
    if (removeForm) {
      const id = clip.dataset.studioId;
      removeForm.action = `/studio/${id}/remove`;
      const btn = removeForm.querySelector("button[type='submit']");
      if (btn) btn.setAttribute("formaction", `/studio/${id}/remove`);
    }
    if (cellActions) cellActions.hidden = !selectedLeafId;
    fillLeafFraming(clip);
    renderPreview(clip);
  }

  function leafMedia(clip, leafId) {
    const spec = parseSpec(clip);
    if (!spec || !leafId) return null;
    const leaf = iterLeaves(spec.root).find((item) => String(item.id) === String(leafId));
    return leaf?.media || null;
  }

  function selectedLeafMedia(clip) {
    return leafMedia(clip, selectedLeafId);
  }

  function fillLeafFraming(clip) {
    const media = selectedLeafMedia(clip);
    const has = !!media;
    if (fitEl) {
      fitEl.disabled = !has;
      fitEl.value = media?.fit === "fit" ? "fit" : "fill";
    }
    if (zoomEl) {
      zoomEl.disabled = !has;
      zoomEl.value = String(media?.zoom ?? 1);
    }
    if (panXEl) {
      panXEl.disabled = !has;
      panXEl.value = String(media?.pan_x ?? 0.5);
    }
    if (panYEl) {
      panYEl.disabled = !has;
      panYEl.value = String(media?.pan_y ?? 0.5);
    }
  }

  function basename(path) {
    const text = String(path || "").replace(/\\/g, "/");
    const parts = text.split("/");
    return parts[parts.length - 1] || text;
  }

  function kindFromPath(path) {
    const lower = String(path || "").toLowerCase();
    if (/\.(mp4|mov|m4v|webm)$/.test(lower)) return "video";
    return "photo";
  }

  function mediaTargets(clip, count) {
    const spec = parseSpec(clip);
    if (!spec || count <= 0) return [];
    const leaves = iterLeaves(spec.root);
    const targets = [];
    if (selectedLeafId) {
      const selected = leaves.find((leaf) => String(leaf.id) === String(selectedLeafId));
      if (selected) targets.push(String(selected.id));
    }
    for (const leaf of leaves) {
      if (targets.length >= count) break;
      const id = String(leaf.id);
      if (targets.includes(id)) continue;
      if (!leaf.media) targets.push(id);
    }
    for (const leaf of leaves) {
      if (targets.length >= count) break;
      const id = String(leaf.id);
      if (!targets.includes(id)) targets.push(id);
    }
    return targets.slice(0, count);
  }

  async function assignMediaList(clip, mediaList) {
    if (!isCollage(clip) || !mediaList.length) return;
    const targets = mediaTargets(clip, mediaList.length);
    for (let i = 0; i < targets.length; i += 1) {
      const leafId = targets[i];
      const media = mediaList[i];
      await queueSave(
        clip,
        { op: "assign_media", leaf_id: leafId, media },
        gestureGroup("collage-assign")
      );
    }
    if (isStillSelected(clip)) {
      fillInspector(clip);
    }
  }

  function syncLibraryAddButton() {
    if (!libraryAdd) return;
    libraryAdd.disabled = Object.keys(librarySelected).length === 0;
  }

  function renderLibraryGrid(query) {
    if (!libraryGrid) return;
    const q = String(query || "")
      .trim()
      .toLowerCase();
    libraryGrid.replaceChildren();
    const visible = libraryItems.filter((item) => {
      if (!item) return false;
      if (!q) return true;
      return String(item.filename || "")
        .toLowerCase()
        .includes(q);
    });
    if (libraryEmpty) libraryEmpty.hidden = visible.length > 0 || libraryItems.length === 0;
    if (!libraryItems.length && libraryEmpty) {
      libraryEmpty.hidden = false;
    }
    visible.forEach((item) => {
      const id = String(item.id);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "photo-combine-picker-card";
      btn.setAttribute("role", "option");
      btn.setAttribute("aria-selected", librarySelected[id] ? "true" : "false");
      if (librarySelected[id]) btn.classList.add("is-selected");
      const img = document.createElement("img");
      img.src = `/media/${item.id}/thumb`;
      img.alt = "";
      img.loading = "lazy";
      const span = document.createElement("span");
      span.textContent = `${item.filename || `#${item.id}`} (${item.kind || "?"})`;
      btn.appendChild(img);
      btn.appendChild(span);
      btn.addEventListener("click", () => {
        if (librarySelected[id]) delete librarySelected[id];
        else librarySelected[id] = item;
        btn.classList.toggle("is-selected", !!librarySelected[id]);
        btn.setAttribute("aria-selected", librarySelected[id] ? "true" : "false");
        syncLibraryAddButton();
      });
      libraryGrid.appendChild(btn);
    });
    syncLibraryAddButton();
  }

  async function loadLibraryMedia(query) {
    const res = await fetchImpl("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        q: String(query || "").trim(),
        limit: 120,
        sort: "recorded_at",
        order: "desc",
      }),
    });
    const data = await res.json().catch(() => null);
    libraryItems = ((data && data.items) || []).filter(
      (item) => item && (item.kind === "photo" || item.kind === "video")
    );
    renderLibraryGrid(libraryFilter ? libraryFilter.value : "");
  }

  async function openLibraryPicker() {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !libraryDialog) return;
    librarySelected = {};
    if (libraryFilter) libraryFilter.value = "";
    syncLibraryAddButton();
    try {
      await loadLibraryMedia("");
    } catch {
      libraryItems = [];
      renderLibraryGrid("");
      opts.showFlash(msg("collageFailed", "Could not save collage."));
      return;
    }
    if (typeof libraryDialog.showModal === "function") libraryDialog.showModal();
    else libraryDialog.setAttribute("open", "");
  }

  function closeLibraryPicker() {
    if (!libraryDialog) return;
    if (typeof libraryDialog.close === "function") libraryDialog.close();
    else libraryDialog.removeAttribute("open");
  }

  async function commitLibrarySelection() {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip)) return;
    const selected = Object.keys(librarySelected).map((key) => librarySelected[key]);
    if (!selected.length) {
      opts.showFlash(msg("collageSelectLibrary", "Select at least one photo or video."));
      return;
    }
    closeLibraryPicker();
    await assignMediaList(
      clip,
      selected.map((item) => ({
        source: "library",
        media_id: Number(item.id),
        kind: item.kind === "video" ? "video" : "photo",
        fit: "fill",
        zoom: 1,
        pan_x: 0.5,
        pan_y: 0.5,
      }))
    );
  }

  async function pickComputerFiles() {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip)) return;
    try {
      const res = await fetchImpl("/api/desktop/pick-open-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          allow_multiple: true,
          file_types: MEDIA_FILE_TYPES,
        }),
      });
      if (res.status === 503) {
        opts.showFlash(
          msg("collagePickerUnavailable", "Native file picker needs the desktop app.")
        );
        return;
      }
      const data = await res.json().catch(() => null);
      if (!data || data.status === "cancelled") return;
      if (data.status !== "ok") {
        opts.showFlash(
          msg("collagePickerUnavailable", "Native file picker needs the desktop app.")
        );
        return;
      }
      const paths = Array.isArray(data.paths) ? data.paths : data.path ? [data.path] : [];
      if (!paths.length) return;
      await assignMediaList(
        clip,
        paths.map((path) => ({
          source: "external",
          path,
          kind: kindFromPath(path),
          fit: "fill",
          zoom: 1,
          pan_x: 0.5,
          pan_y: 0.5,
          display_name: basename(path),
        }))
      );
    } catch {
      opts.showFlash(msg("collageFailed", "Could not save collage."));
    }
  }

  function patchSelectedLeafMedia(mutator) {
    const clip = clipForLeafAction();
    if (!isCollage(clip) || !selectedLeafId) return;
    const leafId = selectedLeafId;
    const group = gestureGroup("collage-frame");
    saveChain = saveChain
      .catch(() => {})
      .then(() => {
        const media = leafMedia(clip, leafId);
        if (!media) return null;
        return patchCollage(
          clip,
          { op: "assign_media", leaf_id: leafId, media: mutator({ ...media }) },
          group
        );
      })
      .catch((err) => {
        opts.showFlash(err?.message || msg("collageFailed", "Could not save collage."));
      });
    saveChain.then(() => {
      if (isStillSelected(clip)) renderPreview(clip);
    });
  }

  function hidePreview() {
    if (preview) preview.hidden = true;
    if (stage) stage.replaceChildren();
    selectedLeafId = null;
  }

  document.getElementById("inspector-collage-duration")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !durationEl) return;
    queueSave(clip, { duration_s: Number(durationEl.value) }, gestureGroup("collage-duration"));
  });
  document.getElementById("inspector-collage-preset")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !presetEl) return;
    selectedLeafId = null;
    queueSave(clip, { preset: presetEl.value }, gestureGroup("collage-preset")).then(() => {
      if (isStillSelected(clip)) fillInspector(clip);
    });
  });
  document.getElementById("inspector-collage-aspect")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !aspectEl) return;
    queueSave(clip, { aspect: aspectEl.value }, gestureGroup("collage-aspect")).then(() => {
      if (isStillSelected(clip)) renderPreview(clip);
    });
  });
  document.getElementById("inspector-collage-gap")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !gapEl) return;
    queueSave(clip, { gap_px: Number(gapEl.value) }, gestureGroup("collage-gap")).then(() => {
      if (isStillSelected(clip)) renderPreview(clip);
    });
  });
  document.getElementById("inspector-collage-background")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !bgEl) return;
    queueSave(clip, { background: bgEl.value }, gestureGroup("collage-bg")).then(() => {
      if (isStillSelected(clip)) renderPreview(clip);
    });
  });
  document.getElementById("inspector-collage-split-h")?.addEventListener("click", () => {
    const clip = clipForLeafAction();
    if (!isCollage(clip) || !selectedLeafId) return;
    queueSave(
      clip,
      { op: "split", leaf_id: selectedLeafId, dir: "h" },
      gestureGroup("collage-split")
    ).then(() => {
      if (isStillSelected(clip)) fillInspector(clip);
    });
  });
  document.getElementById("inspector-collage-split-v")?.addEventListener("click", () => {
    const clip = clipForLeafAction();
    if (!isCollage(clip) || !selectedLeafId) return;
    queueSave(
      clip,
      { op: "split", leaf_id: selectedLeafId, dir: "v" },
      gestureGroup("collage-split")
    ).then(() => {
      if (isStillSelected(clip)) fillInspector(clip);
    });
  });
  document.getElementById("inspector-collage-remove-cell")?.addEventListener("click", () => {
    const clip = clipForLeafAction();
    if (!isCollage(clip) || !selectedLeafId) return;
    const leafId = selectedLeafId;
    selectedLeafId = null;
    queueSave(
      clip,
      { op: "remove_leaf", leaf_id: leafId },
      gestureGroup("collage-remove-cell")
    ).then(() => {
      if (isStillSelected(clip)) fillInspector(clip);
    });
  });

  window.addEventListener("pointermove", (event) => {
    if (!drag || !stage) return;
    const rect = stage.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const pos =
      drag.dir === "h"
        ? ((event.clientX - rect.left) / rect.width) * (stage.clientWidth || rect.width)
        : ((event.clientY - rect.top) / rect.height) * (stage.clientHeight || rect.height);
    const ratio = Math.max(0.05, Math.min(0.95, (pos - drag.origin) / Math.max(1, drag.span)));
    drag.pendingRatio = ratio;
    // Live visual only via re-render with local mutation would need a draft;
    // keep pointer feedback light until pointerup persists.
  });
  window.addEventListener("pointerup", () => {
    if (!drag) return;
    const { clip, splitId, pendingRatio, startRatio } = drag;
    drag = null;
    if (
      pendingRatio === null ||
      pendingRatio === undefined ||
      Math.abs(pendingRatio - startRatio) < 0.001
    )
      return;
    queueSave(
      clip,
      { op: "set_ratio", split_id: splitId, ratio: pendingRatio },
      gestureGroup("collage-divider")
    ).then(() => {
      if (isStillSelected(clip)) renderPreview(clip);
    });
  });

  async function addCollage() {
    try {
      const res = await fetchImpl("/api/studio/collages", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ preset: "1+1" }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        throw new Error(data.detail || msg("collageFailed", "Could not save collage."));
      }
      const id = data.id;
      window.location.href = `/studio?select=${encodeURIComponent(String(id))}`;
    } catch (err) {
      opts.showFlash(err?.message || msg("collageFailed", "Could not save collage."));
    }
  }

  document.getElementById("studio-add-collage")?.addEventListener("click", addCollage);
  document.getElementById("studio-add-collage-empty")?.addEventListener("click", addCollage);
  document.getElementById("inspector-collage-from-library")?.addEventListener("click", () => {
    openLibraryPicker();
  });
  document.getElementById("inspector-collage-from-computer")?.addEventListener("click", () => {
    pickComputerFiles();
  });
  document.getElementById("inspector-collage-clear-cell")?.addEventListener("click", () => {
    const clip = clipForLeafAction();
    if (!isCollage(clip) || !selectedLeafId) return;
    queueSave(
      clip,
      { op: "assign_media", leaf_id: selectedLeafId, media: null },
      gestureGroup("collage-clear")
    ).then(() => {
      if (isStillSelected(clip)) fillInspector(clip);
    });
  });
  fitEl?.addEventListener("change", () => {
    patchSelectedLeafMedia((media) => {
      media.fit = fitEl.value === "fit" ? "fit" : "fill";
      return media;
    });
  });
  zoomEl?.addEventListener("change", () => {
    patchSelectedLeafMedia((media) => {
      const zoom = Number(zoomEl.value);
      media.zoom = Number.isFinite(zoom) ? zoom : 1;
      return media;
    });
  });
  panXEl?.addEventListener("change", () => {
    patchSelectedLeafMedia((media) => {
      const pan = Number(panXEl.value);
      media.pan_x = Number.isFinite(pan) ? pan : 0.5;
      return media;
    });
  });
  panYEl?.addEventListener("change", () => {
    patchSelectedLeafMedia((media) => {
      const pan = Number(panYEl.value);
      media.pan_y = Number.isFinite(pan) ? pan : 0.5;
      return media;
    });
  });
  document.getElementById("studio-collage-library-cancel")?.addEventListener("click", () => {
    closeLibraryPicker();
  });
  document.getElementById("studio-collage-library-add")?.addEventListener("click", () => {
    commitLibrarySelection();
  });
  let libraryFilterTimer = 0;
  libraryFilter?.addEventListener("input", () => {
    window.clearTimeout(libraryFilterTimer);
    libraryFilterTimer = window.setTimeout(() => {
      loadLibraryMedia(libraryFilter.value).catch(() => {
        renderLibraryGrid(libraryFilter.value);
      });
    }, 180);
  });

  return {
    isCollage,
    fillInspector,
    hidePreview,
    renderPreview,
    syncPlayback: (args) => playback.sync(args),
    pausePlayback: () => playback.pause(),
    teardownPlayback: () => playback.teardown(),
    isPlaybackFallback: () => playback.isFallback(),
    parseSpec,
  };
}
