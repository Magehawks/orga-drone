/**
 * Studio collage inspector + preview shell (ADR 0038 / #458).
 * Persistence goes through /api/studio/{id}/collage; media fill is WP3.
 */

import {
  PRESET_NAMES,
  aspectCss,
  applyLeafThumbFraming,
  collectDividers,
  iterLeaves,
  resetLeafThumbFraming,
  resolveRects,
  sourceWindow,
} from "./collage-layout.js";
import {
  createCollagePlayback,
  shouldKeepComposedUnderlay,
} from "./collage-playback.js?v=collage-looks-keep-1";
import { createCollageFrameModal } from "./collage-frame-modal.js?v=collage-looks-keep-1";

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
  const presetButtons = Array.from(
    document.querySelectorAll("#inspector-collage-presets [data-collage-preset]")
  );
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
  const sourceDialog = document.getElementById("studio-collage-source-dialog");
  const composedImg = document.getElementById("studio-preview-collage-composed");
  const exportFormatEl = document.getElementById("inspector-collage-export-format");
  const exportBtn = document.getElementById("inspector-collage-export");
  const exportStatus = document.getElementById("inspector-collage-export-status");

  const MEDIA_FILE_TYPES = [
    "Media (*.jpg;*.jpeg;*.png;*.webp;*.heic;*.mp4;*.mov;*.m4v;*.webm)",
    "Images (*.jpg;*.jpeg;*.png;*.webp;*.heic)",
    "Videos (*.mp4;*.mov;*.m4v;*.webm)",
    "All files (*.*)",
  ];

  let composedTimer = null;
  let composedSeq = 0;
  let composedObjectUrl = null;
  let exportBusy = false;
  let exportPollTimer = null;

  let selectedLeafId = null;
  let selectedLeafOwnerId = null;
  let drag = null;
  let framingDrag = null;
  let framingLiveTimer = 0;
  let framingCommitTimer = 0;
  let framingQuiet = false;
  let framingLiveSafetyTimer = 0;
  let saveChain = Promise.resolve();
  let libraryItems = [];
  let librarySelected = {};
  let hostResizeTimer = 0;
  let lastHostKey = "";
  let previewClip = null;
  const playback = createCollagePlayback({ stage });
  const frameModal = createCollageFrameModal({
    showFlash: (text) => opts.showFlash?.(text),
  });
  const MIN_LEAF_ZOOM = 1;
  const MAX_LEAF_ZOOM = 3;
  const ZOOM_WHEEL_STEP = 0.08;

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
    return { width, height, css, aw, ah };
  }

  function measureCollageHost() {
    // Prefer the visible preview frame — collage host can still be 0×0 on first show.
    const frame = document.getElementById("studio-preview-frame");
    const frameRect = frame?.getBoundingClientRect?.();
    const hostRect = preview?.getBoundingClientRect?.();
    let hostW = Math.round(hostRect?.width || preview?.clientWidth || 0);
    let hostH = Math.round(hostRect?.height || preview?.clientHeight || 0);
    if (hostW < 48 || hostH < 48) {
      hostW = Math.round(frameRect?.width || frame?.clientWidth || 0);
      hostH = Math.round(frameRect?.height || frame?.clientHeight || 0);
    }
    const reliable = hostW >= 48 && hostH >= 48;
    if (!reliable) {
      hostW = Math.max(hostW, 960);
      hostH = Math.max(hostH, 540);
    }
    return { hostW, hostH, reliable };
  }

  function scheduleHostRelayout(clip, specCss) {
    const run = () => {
      if (previewClip !== clip) return;
      if (!isCollage(clip)) return;
      if (framingDrag || framingQuiet) return;
      // Force style flush after unhide / studio chrome layout.
      void preview?.offsetWidth;
      void document.getElementById("studio-preview-frame")?.offsetWidth;
      const again = measureCollageHost();
      const key = `${again.hostW}x${again.hostH}:${specCss}`;
      // Compare against the aspect-fit box — NOT raw host size (portrait stages
      // are intentionally narrower than a 16:9 frame and looked "too small").
      const expected = aspectBox(parseSpec(clip) || { aspect: "16:9" }, again.hostW, again.hostH);
      const stageW = Math.round(stage?.clientWidth || 0);
      const stageH = Math.round(stage?.clientHeight || 0);
      const tooSmall =
        expected.width >= 64 &&
        expected.height >= 64 &&
        (stageW < expected.width * 0.85 || stageH < expected.height * 0.85);
      if (key !== lastHostKey || tooSmall) {
        renderPreview(clip);
      }
    };
    requestAnimationFrame(() => {
      requestAnimationFrame(run);
    });
    window.setTimeout(run, 120);
    window.setTimeout(run, 350);
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

  function clearComposedPreview() {
    if (composedTimer) {
      clearTimeout(composedTimer);
      composedTimer = null;
    }
    composedSeq += 1;
    if (composedObjectUrl) {
      URL.revokeObjectURL(composedObjectUrl);
      composedObjectUrl = null;
    }
    if (composedImg) {
      composedImg.hidden = true;
      composedImg.removeAttribute("src");
    }
    setHasComposedStill(false);
    setFramingLive(false);
  }

  function hideThumbsUnderComposed() {
    stage?.querySelectorAll(".studio-collage-cell img").forEach((img) => {
      img.style.opacity = "0";
    });
  }

  function showComposedUrl(nextUrl, seq) {
    if (!composedImg) {
      URL.revokeObjectURL(nextUrl);
      return;
    }
    if (seq !== composedSeq) {
      URL.revokeObjectURL(nextUrl);
      return;
    }
    if (composedObjectUrl) URL.revokeObjectURL(composedObjectUrl);
    composedObjectUrl = nextUrl;
    // Ensure the composed still is still mounted after stage.replaceChildren().
    if (composedImg.parentElement !== stage) {
      stage?.insertBefore(composedImg, stage.firstChild);
    }
    composedImg.src = nextUrl;
    composedImg.hidden = false;
    // Under cell chrome (labels/selection), above stage background.
    composedImg.style.zIndex = "0";
    composedImg.style.pointerEvents = "none";
    composedImg.style.opacity = "1";
    composedImg.style.visibility = "visible";
    setFramingLive(false);
    setHasComposedStill(true);
    hideThumbsUnderComposed();
  }

  function scheduleComposedPreview(clip, tS = null, { keepLiveUntilLoad = false } = {}) {
    if (!composedImg || !isCollage(clip)) return;
    const studioId = String(clip.dataset.studioId || "");
    if (!studioId) return;
    /* While playing, collage-playback owns the live still; editor still refreshes
       the graded composed preview when paused so leaf Looks/HSL/LUTs show. */
    if (composedTimer) clearTimeout(composedTimer);
    const requestTs = tS == null ? Number(opts.getCollageLocalS?.() || 0) : Number(tS) || 0;
    composedTimer = setTimeout(async () => {
      composedTimer = null;
      if (framingDrag) return;
      const seq = ++composedSeq;
      try {
        const res = await fetchImpl(`/api/studio/${encodeURIComponent(studioId)}/collage/preview`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ t_s: requestTs }),
        });
        if (seq !== composedSeq) return;
        // Newer preview cancelled this one — keep current still; never stay in live-hide.
        if (res.status === 409) {
          if (keepLiveUntilLoad) setFramingLive(false);
          return;
        }
        if (!res.ok) {
          setFramingLive(false);
          if (!composedObjectUrl) clearComposedPreview();
          return;
        }
        const blob = await res.blob();
        if (seq !== composedSeq) return;
        const nextUrl = URL.createObjectURL(blob);
        if (keepLiveUntilLoad) {
          const swap = new Image();
          swap.onload = () => showComposedUrl(nextUrl, seq);
          swap.onerror = () => {
            // Still assign — better a flash than a blank stage.
            showComposedUrl(nextUrl, seq);
          };
          swap.src = nextUrl;
          return;
        }
        showComposedUrl(nextUrl, seq);
      } catch {
        if (seq === composedSeq) {
          setFramingLive(false);
          if (!composedObjectUrl) clearComposedPreview();
        }
      }
    }, keepLiveUntilLoad ? 280 : 220);
  }

  function renderPreview(clip) {
    if (!preview || !stage) return;
    const spec = parseSpec(clip);
    if (!isCollage(clip) || !spec) {
      previewClip = null;
      lastHostKey = "";
      preview.hidden = true;
      clearComposedPreview();
      stage.replaceChildren();
      if (composedImg) stage.appendChild(composedImg);
      return;
    }
    previewClip = clip;
    // Fresh paint: keep cell thumbs visible until composed arrives.
    setFramingLive(false);
    setHasComposedStill(false);
    preview.hidden = false;
    // Flush after unhide so frame/host rects are real (first open was measuring 0).
    void preview.offsetWidth;
    void document.getElementById("studio-preview-frame")?.offsetWidth;
    const bg = spec.background === "transparent" ? "#0a0c0e" : spec.background || "#0a0c0e";
    stage.style.background = bg;
    const measured = measureCollageHost();
    const box = aspectBox(spec, measured.hostW, measured.hostH);
    lastHostKey = `${measured.hostW}x${measured.hostH}:${box.css}`;
    // Explicit px size — % height inside the flex collage host collapses on first paint.
    stage.style.aspectRatio = box.css;
    stage.style.width = `${box.width}px`;
    stage.style.height = `${box.height}px`;
    stage.style.maxWidth = "100%";
    stage.style.maxHeight = "100%";
    const width = box.width;
    const height = box.height;
    const rects = resolveRects(spec, width, height);
    const leaves = iterLeaves(spec.root);
    const emptyLabel = msg("collageEmptyCell", "Empty cell");
    const missingLabel = msg("collageMissingMedia", "Missing media");
    stage.replaceChildren();
    if (composedImg) {
      stage.appendChild(composedImg);
    }
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
      if (media) {
        cell.classList.add("has-media");
        const thumb = cell.querySelector("img");
        if (thumb) {
          // Idle: simple visible fallback. Precise crop only while framing live.
          resetLeafThumbFraming(thumb, media);
        }
      }
      cell.addEventListener("click", () => {
        const leafId = String(leaf.id);
        // Always read current media from the clip dataset — closure media goes stale after Apply.
        const current = leafMedia(clip, leafId) || media || null;
        selectLeaf(clip, leaf, current);
        stage
          ?.querySelectorAll(".studio-collage-cell.is-selected")
          .forEach((el) => el.classList.remove("is-selected"));
        cell.classList.add("is-selected");
        fillLeafFraming(clip);
        notifyLeafSelection(clip);
        if (!current) {
          openSourceChooser();
          return;
        }
        openFrameModalForLeaf(clip, leaf, current, cell);
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
    const playing = Boolean(opts.isPlaying?.());
    const keepUnderlay = shouldKeepComposedUnderlay(spec, playing);
    // Paused editing: force composed stills only — no raw leaf media under/over thumbs.
    playback.mount({
      spec,
      studioId: clip.dataset.studioId,
      rects,
      width,
      height,
      forceStill: !playing,
    });
    preview?.classList.toggle("has-play-media", true);
    preview?.classList.toggle("is-paused", !playing);
    // Playing without Looks: hide graded still so live layers own the picture.
    // With Looks/framing (or photo-only): keep graded compose under live video.
    if (playing && composedImg) {
      if (keepUnderlay) {
        composedImg.hidden = false;
        composedImg.style.visibility = "visible";
        composedImg.style.opacity = "1";
        setHasComposedStill(true);
        if (!composedImg.getAttribute("src")) scheduleComposedPreview(clip);
      } else {
        composedImg.hidden = true;
        composedImg.style.visibility = "hidden";
        setHasComposedStill(false);
      }
    }
    playback.sync({
      localS: Number(opts.getCollageLocalS?.() || 0),
      playing,
      seek: true,
      spec,
    });
    if (!playing) scheduleComposedPreview(clip);
    // Always re-check after layout — clicking the track later was the only reliable resize.
    scheduleHostRelayout(clip, box.css);
  }

  function setExportStatus(text, { error = false } = {}) {
    if (!exportStatus) return;
    if (!text) {
      exportStatus.hidden = true;
      exportStatus.textContent = "";
      return;
    }
    exportStatus.hidden = false;
    exportStatus.textContent = text;
    exportStatus.classList.toggle("is-error", Boolean(error));
  }

  async function pickStillSavePath(filename) {
    const isJpeg =
      String(filename).toLowerCase().endsWith(".jpg") ||
      String(filename).toLowerCase().endsWith(".jpeg");
    const fileTypes = isJpeg
      ? ["JPEG Images (*.jpg;*.jpeg)", "PNG Images (*.png)"]
      : ["PNG Images (*.png)", "JPEG Images (*.jpg;*.jpeg)"];
    const res = await fetchImpl("/api/desktop/pick-save-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, file_types: fileTypes }),
    });
    if (res.status === 503) {
      throw new Error(msg("collageDesktopRequired", "Native file picker needs the desktop app."));
    }
    const data = await res.json().catch(() => null);
    if (!data || data.status === "cancelled" || data.cancelled) return null;
    if (!data.path) {
      throw new Error(msg("collageDesktopRequired", "Native file picker needs the desktop app."));
    }
    return data.path;
  }

  function stopExportPoll() {
    if (exportPollTimer) {
      clearInterval(exportPollTimer);
      exportPollTimer = null;
    }
  }

  async function pollExportJob(jobId) {
    try {
      const res = await fetchImpl(`/api/studio/export/jobs/${encodeURIComponent(jobId)}`);
      const data = await res.json().catch(() => null);
      if (!data) return;
      if (data.state === "completed") {
        stopExportPoll();
        exportBusy = false;
        if (exportBtn) exportBtn.disabled = false;
        setExportStatus(data.output_path || data.filename || "OK");
        return;
      }
      if (data.state === "failed" || data.state === "cancelled") {
        stopExportPoll();
        exportBusy = false;
        if (exportBtn) exportBtn.disabled = false;
        setExportStatus(
          data.state === "cancelled"
            ? msg("collageExportCancelled", "Collage export cancelled.")
            : data.error || msg("collageExportFailed", "Could not export collage."),
          { error: true }
        );
      }
    } catch {
      /* keep polling briefly */
    }
  }

  async function exportStill() {
    if (exportBusy) return;
    const clip = opts.getSelectedClip?.();
    if (!isCollage(clip)) return;
    const studioId = String(clip.dataset.studioId || "");
    if (!studioId) return;
    const fmt = exportFormatEl?.value === "jpeg" ? "jpeg" : "png";
    const base = msg("collageExportDefault", "collage");
    const filename = `${base}${fmt === "png" ? ".png" : ".jpg"}`;
    let outputPath;
    try {
      outputPath = await pickStillSavePath(filename);
    } catch (err) {
      setExportStatus(
        err && err.message ? err.message : msg("collageExportFailed", "Could not export collage."),
        {
          error: true,
        }
      );
      return;
    }
    if (!outputPath) return;
    exportBusy = true;
    if (exportBtn) exportBtn.disabled = true;
    setExportStatus("…");
    try {
      const res = await fetchImpl(`/api/studio/${encodeURIComponent(studioId)}/collage/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format: fmt, output_path: outputPath, t_s: 0 }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.job_id) {
        exportBusy = false;
        if (exportBtn) exportBtn.disabled = false;
        setExportStatus(
          (data && data.detail) || msg("collageExportFailed", "Could not export collage."),
          { error: true }
        );
        return;
      }
      stopExportPoll();
      exportPollTimer = setInterval(() => pollExportJob(data.job_id), 400);
      pollExportJob(data.job_id);
    } catch {
      exportBusy = false;
      if (exportBtn) exportBtn.disabled = false;
      setExportStatus(msg("collageExportFailed", "Could not export collage."), { error: true });
    }
  }

  function fillInspector(clip) {
    if (!isCollage(clip)) return;
    const ownerId = String(clip.dataset.studioId || "");
    if (selectedLeafOwnerId && selectedLeafOwnerId !== ownerId) {
      selectedLeafId = null;
      selectedLeafOwnerId = null;
    }
    const spec = parseSpec(clip) || {};
    // Auto-select a cell so HSL / Looks / LUTs are available without an extra click.
    if (!selectedLeafId || selectedLeafOwnerId !== ownerId) {
      const leaves = spec.root ? iterLeaves(spec.root) : [];
      const withMedia = leaves.find((leaf) => leaf && leaf.media);
      const pick = withMedia || leaves[0] || null;
      if (pick) {
        selectedLeafId = String(pick.id);
        selectedLeafOwnerId = ownerId;
      }
    }
    if (selectedLeafId && selectedLeafOwnerId === ownerId) {
      // Keep Color Workspace usable alongside collage layout controls.
      opts.showInspector("inspector-collage", { also: ["inspector-clip"] });
    } else {
      opts.showInspector("inspector-collage");
    }
    if (durationEl) {
      durationEl.value = String(clip.dataset.collageDuration || spec.duration_s || "5");
    }
    if (presetEl) {
      const names = Array.isArray(spec.presets) ? spec.presets : PRESET_NAMES;
      // Prefer matching the current tree shape; fall back to the control value.
      const current = String(presetEl.value || "1+1");
      const next = names.includes(current) ? current : "1+1";
      presetEl.value = next;
      syncPresetButtons(next);
    }
    if (aspectEl) {
      if (typeof spec.aspect === "string") {
        aspectEl.value = spec.aspect;
      } else if (spec.aspect && typeof spec.aspect === "object") {
        // Free crop may set a custom {w,h} aspect — keep select stable.
        const custom = `custom:${spec.aspect.w}x${spec.aspect.h}`;
        let opt = Array.from(aspectEl.options).find((o) => o.value === custom);
        if (!opt) {
          opt = document.createElement("option");
          opt.value = custom;
          opt.textContent = `${spec.aspect.w}×${spec.aspect.h}`;
          aspectEl.appendChild(opt);
        }
        aspectEl.value = custom;
      } else {
        aspectEl.value = "16:9";
      }
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
    if (selectedLeafId && selectedLeafOwnerId === ownerId) {
      notifyLeafSelection(clip);
    }
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

  function notifyLeafSelection(clip) {
    if (!clip || !selectedLeafId || selectedLeafOwnerId !== String(clip.dataset.studioId || "")) {
      return;
    }
    const spec = parseSpec(clip);
    const leaf = spec
      ? iterLeaves(spec.root).find((item) => String(item.id) === String(selectedLeafId))
      : null;
    opts.onLeafSelected?.(clip, leaf || { id: selectedLeafId }, leaf?.media || null);
  }

  async function assignMediaList(clip, mediaList) {
    if (!isCollage(clip) || !mediaList.length) return false;
    const targets = mediaTargets(clip, mediaList.length);
    if (!targets.length) {
      opts.showFlash(msg("collageFailed", "Could not save collage."));
      return false;
    }
    const group = gestureGroup("collage-assign");
    try {
      for (let i = 0; i < targets.length; i += 1) {
        const leafId = targets[i];
        const media = mediaList[i];
        // Await the real patch (not the swallowed queueSave catch) so a failed
        // assign cannot look like success with empty cells.
        await (saveChain = saveChain
          .catch(() => {})
          .then(() => patchCollage(clip, { op: "assign_media", leaf_id: leafId, media }, group)));
      }
    } catch (err) {
      opts.showFlash(err?.message || msg("collageFailed", "Could not save collage."));
      return false;
    }
    // Dialog close / click-through can clear selection; always refresh this clip.
    const studioId = String(clip.dataset.studioId || "");
    if (studioId) opts.onSelectClip?.(studioId);
    fillInspector(clip);
    notifyLeafSelection(clip);
    renderPreview(clip);
    return true;
  }

  function syncPresetButtons(presetName) {
    const selected = String(presetName || "");
    presetButtons.forEach((btn) => {
      const active = String(btn.getAttribute("data-collage-preset") || "") === selected;
      btn.setAttribute("aria-checked", active ? "true" : "false");
      btn.classList.toggle("is-selected", active);
    });
  }

  function applyPresetChoice(presetName) {
    const clip = opts.getSelectedClip();
    const name = String(presetName || "").trim();
    if (!isCollage(clip) || !name) return;
    if (presetEl) presetEl.value = name;
    syncPresetButtons(name);
    selectedLeafId = null;
    queueSave(clip, { preset: name }, gestureGroup("collage-preset")).then(() => {
      if (isStillSelected(clip)) fillInspector(clip);
    });
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
    if (libraryEmpty) {
      if (!libraryItems.length) {
        libraryEmpty.textContent = msg(
          "collageLibraryEmpty",
          "No photos or videos in the library yet."
        );
        libraryEmpty.hidden = false;
      } else if (!visible.length) {
        libraryEmpty.textContent = msg(
          "collageLibraryNoMatch",
          "No matching photos or videos."
        );
        libraryEmpty.hidden = false;
      } else {
        libraryEmpty.hidden = true;
      }
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
      // Double-click commits immediately so selection is not lost without the confirm button.
      btn.addEventListener("dblclick", (event) => {
        event.preventDefault();
        librarySelected[id] = item;
        btn.classList.add("is-selected");
        btn.setAttribute("aria-selected", "true");
        syncLibraryAddButton();
        void commitLibrarySelection();
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

  function openSourceChooser() {
    if (!sourceDialog) {
      openLibraryPicker();
      return;
    }
    if (typeof sourceDialog.showModal === "function") sourceDialog.showModal();
    else sourceDialog.setAttribute("open", "");
  }

  function closeSourceChooser() {
    if (!sourceDialog) return;
    if (typeof sourceDialog.close === "function") sourceDialog.close();
    else sourceDialog.removeAttribute("open");
  }

  async function openLibraryPicker() {
    const clip = clipForLeafAction();
    if (!isCollage(clip) || !libraryDialog) return;
    closeSourceChooser();
    if (frameModal.isOpen?.()) frameModal.close();
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
    const clip = clipForLeafAction();
    if (!isCollage(clip)) {
      opts.showFlash(msg("collageFailed", "Could not save collage."));
      return;
    }
    const selected = Object.keys(librarySelected).map((key) => librarySelected[key]);
    if (!selected.length) {
      opts.showFlash(msg("collageSelectLibrary", "Select at least one photo or video."));
      return;
    }
    const mediaList = selected.map((item) => {
      const mediaId = Number(item.id);
      return {
        source: "library",
        media_id: mediaId,
        kind: item.kind === "video" ? "video" : "photo",
        fit: "fill",
        zoom: 1,
        pan_x: 0.5,
        pan_y: 0.5,
      };
    });
    if (mediaList.some((entry) => !Number.isInteger(entry.media_id) || entry.media_id <= 0)) {
      opts.showFlash(msg("collageFailed", "Could not save collage."));
      return;
    }
    // Close only after a successful assign so a failed save keeps the picker open.
    const ok = await assignMediaList(clip, mediaList);
    if (ok) closeLibraryPicker();
  }

  async function pickComputerFiles() {
    const clip = clipForLeafAction();
    if (!isCollage(clip)) {
      opts.showFlash(msg("collageFailed", "Could not save collage."));
      return;
    }
    closeSourceChooser();
    if (frameModal.isOpen?.()) frameModal.close();
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

  function clampLeafZoom(value) {
    const zoom = Number(value);
    if (!Number.isFinite(zoom)) return MIN_LEAF_ZOOM;
    return Math.max(MIN_LEAF_ZOOM, Math.min(MAX_LEAF_ZOOM, zoom));
  }

  function clampPan(value) {
    const pan = Number(value);
    if (!Number.isFinite(pan)) return 0.5;
    return Math.max(0, Math.min(1, pan));
  }

  /**
   * Best-effort layout adapt after free crop: single-cell → collage aspect;
   * multi-cell → nudge the parent split toward the crop aspect.
   * @param {HTMLElement} clip
   * @param {string} leafId
   * @param {number} cropAspect
   */
  function adaptCollageToCropAspect(clip, leafId, cropAspect) {
    if (!clip || !(cropAspect > 0.05) || !(cropAspect < 40)) return;
    const spec = parseSpec(clip);
    if (!spec?.root) return;
    const leaves = iterLeaves(spec.root);
    if (leaves.length === 1) {
      const long = 1000;
      const aspect =
        cropAspect >= 1
          ? { w: long, h: Math.max(1, Math.round(long / cropAspect)) }
          : { w: Math.max(1, Math.round(long * cropAspect)), h: long };
      queueSave(clip, { aspect }, gestureGroup("collage-frame-aspect")).then(() => {
        if (isStillSelected(clip)) {
          fillInspector(clip);
          renderPreview(clip);
        }
      });
      return;
    }
    const stageW = Math.max(1, stage?.clientWidth || 1);
    const stageH = Math.max(1, stage?.clientHeight || 1);
    const parent = findLeafParentSplit(spec.root, String(leafId), null, stageW, stageH);
    if (!parent?.split || !parent.side) return;
    const rects = resolveRects(spec, stageW, stageH);
    const cell = rects[String(leafId)];
    if (!cell || !(cell.w > 0) || !(cell.h > 0)) return;
    const gap = Number(spec.gap_px) || 0;
    let nextRatio = Number(parent.split.ratio) || 0.5;
    if (parent.split.dir === "h") {
      // Side-by-side: change width share for this leaf.
      const usable = Math.max(1, (parent.boundW || cell.w * 2) - gap);
      const desiredW = Math.max(1, Math.min(usable - 1, cell.h * cropAspect));
      nextRatio = parent.side === "a" ? desiredW / usable : 1 - desiredW / usable;
    } else {
      // Stacked: change height share.
      const usable = Math.max(1, (parent.boundH || cell.h * 2) - gap);
      const desiredH = Math.max(1, Math.min(usable - 1, cell.w / cropAspect));
      nextRatio = parent.side === "a" ? desiredH / usable : 1 - desiredH / usable;
    }
    nextRatio = Math.max(0.08, Math.min(0.92, nextRatio));
    if (Math.abs(nextRatio - (Number(parent.split.ratio) || 0.5)) < 0.01) return;
    queueSave(
      clip,
      { op: "set_ratio", split_id: parent.split.id, ratio: nextRatio },
      gestureGroup("collage-frame-ratio")
    ).then(() => {
      if (isStillSelected(clip)) renderPreview(clip);
    });
  }

  /**
   * @param {any} node
   * @param {string} leafId
   * @param {{ split: any, side: "a"|"b", boundW: number, boundH: number } | null} [acc]
   * @param {number} [boundW]
   * @param {number} [boundH]
   */
  function findLeafParentSplit(node, leafId, acc = null, boundW = 0, boundH = 0) {
    if (!node) return acc;
    if (node.type === "leaf") {
      return String(node.id) === String(leafId) ? acc : null;
    }
    if (node.type !== "split") return null;
    const gap = 0;
    const ratio = Math.max(0.05, Math.min(0.95, Number(node.ratio) || 0.5));
    if (node.dir === "h") {
      const usable = Math.max(1, boundW - gap);
      const first = Math.max(1, Math.round(usable * ratio));
      const foundA = findLeafParentSplit(
        node.a,
        leafId,
        { split: node, side: "a", boundW, boundH },
        first,
        boundH
      );
      if (foundA) return foundA;
      return findLeafParentSplit(
        node.b,
        leafId,
        { split: node, side: "b", boundW, boundH },
        Math.max(1, usable - first),
        boundH
      );
    }
    const usable = Math.max(1, boundH - gap);
    const first = Math.max(1, Math.round(usable * ratio));
    const foundA = findLeafParentSplit(
      node.a,
      leafId,
      { split: node, side: "a", boundW, boundH },
      boundW,
      first
    );
    if (foundA) return foundA;
    return findLeafParentSplit(
      node.b,
      leafId,
      { split: node, side: "b", boundW, boundH },
      boundW,
      Math.max(1, usable - first)
    );
  }

  function openFrameModalForLeaf(clip, leaf, media, cell) {
    if (!clip || !leaf) return;
    const leafId = String(leaf.id);
    const current = leafMedia(clip, leafId) || media;
    if (!current) return;
    const sourceUrl = framingSourceUrl(clip, leaf, current);
    if (!sourceUrl) {
      opts.showFlash(msg("collageFrameUnavailable", "This cell has no previewable photo for framing."));
      return;
    }
    // Use layout rect aspect (same as export), not the on-screen button box.
    const spec = parseSpec(clip);
    const stageW = Math.max(1, stage?.clientWidth || 1);
    const stageH = Math.max(1, stage?.clientHeight || 1);
    const layoutRects = spec ? resolveRects(spec, stageW, stageH) : {};
    const layout = layoutRects[leafId];
    const screen = cell?.getBoundingClientRect?.();
    const cellW = Math.max(1, Math.round(layout?.w || screen?.width || 1));
    const cellH = Math.max(1, Math.round(layout?.h || screen?.height || 1));
    frameModal.open({
      sourceUrl,
      media: current,
      cellW,
      cellH,
      studioId: clip.dataset.studioId,
      leafId,
      onApply: (nextMedia, meta) => {
        selectedLeafId = leafId;
        selectedLeafOwnerId = String(clip.dataset.studioId || "");
        // Framing must not wipe Looks/HSL/LUT applied while the dialog was open
        // (session.media can be stale relative to clip.dataset.collageSpec).
        const latest = leafMedia(clip, leafId) || current || {};
        const merged = {
          ...latest,
          fit: nextMedia?.fit === "fit" ? "fit" : "fill",
          zoom: nextMedia?.zoom,
          pan_x: nextMedia?.pan_x,
          pan_y: nextMedia?.pan_y,
        };
        if (nextMedia && Object.prototype.hasOwnProperty.call(nextMedia, "crop")) {
          if (nextMedia.crop) merged.crop = nextMedia.crop;
          else delete merged.crop;
        }
        if (latest.grade) merged.grade = latest.grade;
        else delete merged.grade;
        applyLeafFramingLocal(clip, leafId, merged);
        commitLeafFraming(clip, leafId, merged, "collage-frame-modal");
        if (meta?.cropAspect) adaptCollageToCropAspect(clip, leafId, Number(meta.cropAspect));
        notifyLeafSelection(clip);
      },
    });
  }

  function refreshFrameModalGrade() {
    if (!frameModal.isOpen?.()) return;
    const clip = opts.getSelectedClip?.();
    const leafId = selectedLeafId;
    const media = clip && leafId ? leafMedia(clip, leafId) : null;
    const grade = media && media.grade && typeof media.grade === "object" ? media.grade : null;
    frameModal.refreshGradePreview?.({ grade });
  }

  function framingSourceUrl(clip, leaf, media) {
    if (!media) return null;
    const kind = String(media.kind || "").toLowerCase();
    if (media.source === "library" && media.media_id) {
      // Photos: full stream keeps source aspect. Videos stay on thumb (can't img-decode).
      if (kind === "video") return `/media/${media.media_id}/thumb`;
      return `/media/${media.media_id}/stream`;
    }
    if (media.source === "external" && media.has_path && clip?.dataset?.studioId && leaf?.id) {
      if (kind === "video") return null;
      return `/api/studio/${encodeURIComponent(String(clip.dataset.studioId))}/collage/leaves/${encodeURIComponent(String(leaf.id))}/stream`;
    }
    return null;
  }

  function ensureFramingSource(thumb, clip, leaf, media) {
    if (!thumb || !media) return Promise.resolve(false);
    const next = framingSourceUrl(clip, leaf, media);
    if (!next) return Promise.resolve(Boolean(thumb.naturalWidth));
    if (!thumb.dataset.idleSrc) {
      thumb.dataset.idleSrc = thumb.getAttribute("src") || "";
    }
    if (thumb.getAttribute("src") === next && thumb.naturalWidth) {
      return Promise.resolve(true);
    }
    return new Promise((resolve) => {
      const done = () => resolve(Boolean(thumb.naturalWidth));
      thumb.addEventListener("load", done, { once: true });
      thumb.addEventListener("error", () => resolve(false), { once: true });
      thumb.src = next;
      if (thumb.complete && thumb.naturalWidth) done();
    });
  }

  function restoreIdleThumbSources() {
    stage?.querySelectorAll(".studio-collage-cell img[data-idle-src]").forEach((img) => {
      const idle = img.dataset.idleSrc || "";
      if (idle && img.getAttribute("src") !== idle) {
        img.src = idle;
      }
      delete img.dataset.idleSrc;
      img.style.opacity = "";
    });
  }

  function setFramingLive(active) {
    const on = Boolean(active);
    preview?.classList.toggle("is-framing-live", on);
    window.clearTimeout(framingLiveSafetyTimer);
    framingLiveSafetyTimer = 0;
    if (on) {
      // Never leave the graded still hidden if a preview request 409s/fails.
      framingLiveSafetyTimer = window.setTimeout(() => {
        framingLiveSafetyTimer = 0;
        if (!framingDrag) setFramingLive(false);
      }, 2500);
    } else {
      restoreIdleThumbSources();
    }
  }

  function setHasComposedStill(active) {
    preview?.classList.toggle("has-composed-still", Boolean(active));
  }

  function isFramingQuiet() {
    return Boolean(framingQuiet || framingDrag || preview?.classList.contains("is-framing-live"));
  }

  function applyLeafFramingLocal(clip, leafId, nextMedia) {
    const spec = parseSpec(clip);
    if (!spec || !spec.root) return;
    const leaf = iterLeaves(spec.root).find((item) => String(item.id) === String(leafId));
    if (!leaf) return;
    leaf.media = nextMedia;
    try {
      clip.dataset.collageSpec = JSON.stringify(spec);
    } catch {
      /* ignore */
    }
    if (zoomEl) zoomEl.value = String(nextMedia.zoom ?? 1);
    if (panXEl) panXEl.value = String(nextMedia.pan_x ?? 0.5);
    if (panYEl) panYEl.value = String(nextMedia.pan_y ?? 0.5);
    if (fitEl) fitEl.value = nextMedia.fit === "fit" ? "fit" : "fill";
    const cell = stage?.querySelector(
      `.studio-collage-cell[data-leaf-id="${CSS.escape(String(leafId))}"]`
    );
    const thumb = cell?.querySelector("img");
    if (thumb && cell) {
      // Live feedback: source_window crop, clipped to this cell only.
      const box = cell.getBoundingClientRect();
      applyLeafThumbFraming(thumb, nextMedia, Math.max(1, box.width), Math.max(1, box.height));
      // Hide sibling thumbs during live framing so scaled/wrong crops can't stack.
      stage?.querySelectorAll(".studio-collage-cell img").forEach((img) => {
        img.style.opacity = img === thumb ? "1" : "0";
      });
    }
  }

  function commitLeafFraming(clip, leafId, nextMedia, groupPrefix = "collage-frame") {
    if (!clip || !leafId || !nextMedia) return;
    const group = gestureGroup(groupPrefix);
    framingQuiet = true;
    setFramingLive(true);
    saveChain = saveChain
      .catch(() => {})
      .then(() =>
        patchCollage(clip, { op: "assign_media", leaf_id: leafId, media: nextMedia }, group)
      )
      .catch((err) => {
        opts.showFlash(err?.message || msg("collageFailed", "Could not save collage."));
      });
    saveChain.then(() => {
      framingQuiet = false;
      if (!isStillSelected(clip)) {
        setFramingLive(false);
        return;
      }
      fillLeafFraming(clip);
      // Keep live thumbs until the new graded still is decoded → no full-stage flicker.
      scheduleComposedPreview(clip, null, { keepLiveUntilLoad: true });
    });
  }

  function patchSelectedLeafMedia(
    mutator,
    { refreshPreview = true, groupPrefix = "collage-frame", live = false } = {}
  ) {
    const clip = clipForLeafAction();
    if (!isCollage(clip) || !selectedLeafId) return;
    const leafId = selectedLeafId;
    const media = leafMedia(clip, leafId);
    if (!media) return;
    const nextMedia = mutator({ ...media });
    if (live) setFramingLive(true);
    applyLeafFramingLocal(clip, leafId, nextMedia);
    if (live) {
      window.clearTimeout(framingCommitTimer);
      framingCommitTimer = window.setTimeout(() => {
        framingCommitTimer = 0;
        commitLeafFraming(clip, leafId, nextMedia, groupPrefix);
      }, 140);
      return;
    }
    commitLeafFraming(clip, leafId, nextMedia, groupPrefix);
    if (!refreshPreview) {
      /* commitLeafFraming already refreshes composed still after save */
    }
  }

  function endFramingLiveSoon() {
    window.clearTimeout(framingLiveTimer);
    framingLiveTimer = window.setTimeout(() => {
      framingLiveTimer = 0;
      if (!framingDrag) setFramingLive(false);
    }, 160);
  }

  function selectLeaf(clip, leaf, media) {
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
    const current = leafMedia(clip, leaf.id) || media || null;
    opts.onLeafSelected?.(clip, leaf, current);
  }

  function hidePreview() {
    playback.teardown();
    preview?.classList.remove("has-play-media");
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
    if (!presetEl) return;
    applyPresetChoice(presetEl.value);
  });
  presetButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      applyPresetChoice(btn.getAttribute("data-collage-preset") || "");
    });
  });
  document.getElementById("inspector-collage-aspect")?.addEventListener("change", () => {
    const clip = opts.getSelectedClip();
    if (!isCollage(clip) || !aspectEl) return;
    const raw = String(aspectEl.value || "");
    if (raw.startsWith("custom:")) return;
    queueSave(clip, { aspect: raw }, gestureGroup("collage-aspect")).then(() => {
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
  function activeCollageClip() {
    return (
      opts.getSelectedClip?.() ||
      previewClip ||
      clipForLeafAction() ||
      null
    );
  }

  function splitSelectedCell(dir, times = 1) {
    const clip = activeCollageClip();
    if (!isCollage(clip)) {
      opts.showFlash(msg("collageFailed", "Select a collage first."));
      return;
    }
    if (!selectedLeafId) {
      opts.showFlash(
        msg("collageSelectCellFirst", "Select a cell in the collage first.")
      );
      return;
    }
    const payload = { op: "split", leaf_id: selectedLeafId, dir };
    if (times > 1) payload.times = times;
    queueSave(clip, payload, gestureGroup("collage-split")).then(() => {
      fillInspector(clip);
      renderPreview(clip);
    });
  }

  function addCollageBand(edge, cells = 1) {
    const clip = activeCollageClip();
    if (!isCollage(clip)) {
      opts.showFlash(msg("collageFailed", "Select a collage first."));
      return;
    }
    queueSave(
      clip,
      { op: "add_band", edge, cells },
      gestureGroup("collage-add-band")
    ).then(() => {
      fillInspector(clip);
      renderPreview(clip);
    });
  }

  // Event delegation: survives WebView cache quirks and late inspector show.
  document.getElementById("inspector-collage")?.addEventListener("click", (event) => {
    const btn = event.target?.closest?.("button[id]");
    if (!btn) return;
    switch (btn.id) {
      case "inspector-collage-add-row":
        event.preventDefault();
        addCollageBand("bottom", 1);
        break;
      case "inspector-collage-add-column":
        event.preventDefault();
        addCollageBand("right", 1);
        break;
      case "inspector-collage-split-h":
        event.preventDefault();
        splitSelectedCell("h", 1);
        break;
      case "inspector-collage-split-v":
        event.preventDefault();
        splitSelectedCell("v", 1);
        break;
      case "inspector-collage-split-h3":
        event.preventDefault();
        splitSelectedCell("h", 2);
        break;
      case "inspector-collage-split-v3":
        event.preventDefault();
        splitSelectedCell("v", 2);
        break;
      default:
        break;
    }
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
  exportBtn?.addEventListener("click", () => {
    void exportStill();
  });

  window.addEventListener("pointermove", (event) => {
    if (framingDrag) {
      const dx = (event.clientX - framingDrag.startX) / framingDrag.width;
      const dy = (event.clientY - framingDrag.startY) / framingDrag.height;
      if (Math.abs(dx) > 0.008 || Math.abs(dy) > 0.008) framingDrag.moved = true;
      const media = leafMedia(framingDrag.clip, framingDrag.leafId);
      if (!media) return;
      // Map finger travel 1:1 onto the visible crop (depends on zoom / aspect).
      const cell = stage?.querySelector(
        `.studio-collage-cell[data-leaf-id="${CSS.escape(String(framingDrag.leafId))}"]`
      );
      const thumb = cell?.querySelector("img");
      const sw = Math.max(1, Number(thumb?.naturalWidth) || framingDrag.width);
      const sh = Math.max(1, Number(thumb?.naturalHeight) || framingDrag.height);
      const fit = String(media.fit || "fill").toLowerCase() === "fit" ? "fit" : "fill";
      const win = sourceWindow({
        sourceW: sw,
        sourceH: sh,
        cellW: framingDrag.width,
        cellH: framingDrag.height,
        fit,
        zoom: media.zoom,
        panX: 0.5,
        panY: 0.5,
      });
      const maxX = Math.max(0, 1 - win.w);
      const maxY = Math.max(0, 1 - win.h);
      const dxPan = maxX > 1e-6 ? (dx * win.w) / maxX : 0;
      const dyPan = maxY > 1e-6 ? (dy * win.h) / maxY : 0;
      // Dragging the picture right → pan decreases (window moves left in source).
      const nextMedia = {
        ...media,
        pan_x: clampPan(framingDrag.startPanX - dxPan),
        pan_y: clampPan(framingDrag.startPanY - dyPan),
      };
      setFramingLive(true);
      applyLeafFramingLocal(framingDrag.clip, framingDrag.leafId, nextMedia);
      framingDrag.pendingMedia = nextMedia;
      return;
    }
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
  window.addEventListener("pointerup", (event) => {
    if (framingDrag) {
      const active = framingDrag;
      framingDrag = null;
      stage
        ?.querySelectorAll(".studio-collage-cell.is-framing")
        .forEach((el) => el.classList.remove("is-framing"));
      if (!active.moved || !active.pendingMedia) {
        endFramingLiveSoon();
        notifyLeafSelection(active.clip);
        return;
      }
      selectedLeafId = active.leafId;
      selectedLeafOwnerId = String(active.clip.dataset.studioId || "");
      commitLeafFraming(
        active.clip,
        active.leafId,
        active.pendingMedia,
        "collage-frame-drag"
      );
      notifyLeafSelection(active.clip);
      return;
    }
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

  window.addEventListener("keydown", (event) => {
    if (event.defaultPrevented) return;
    const target = event.target;
    if (
      target &&
      (target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable)
    ) {
      return;
    }
    const clip = clipForLeafAction();
    if (!isCollage(clip) || !selectedLeafId) return;
    const media = leafMedia(clip, selectedLeafId);
    if (!media) return;
    const key = event.key;
    if (key === "ArrowLeft" || key === "ArrowRight" || key === "ArrowUp" || key === "ArrowDown") {
      event.preventDefault();
      const step = event.shiftKey ? 0.02 : 0.05;
      patchSelectedLeafMedia(
        (entry) => {
          if (key === "ArrowLeft") entry.pan_x = clampPan((Number(entry.pan_x) || 0.5) - step);
          if (key === "ArrowRight") entry.pan_x = clampPan((Number(entry.pan_x) || 0.5) + step);
          if (key === "ArrowUp") entry.pan_y = clampPan((Number(entry.pan_y) || 0.5) - step);
          if (key === "ArrowDown") entry.pan_y = clampPan((Number(entry.pan_y) || 0.5) + step);
          return entry;
        },
        { live: true, groupPrefix: "collage-frame-keys" }
      );
      return;
    }
    if (key === "+" || key === "=" || key === "-" || key === "_") {
      event.preventDefault();
      const direction = key === "-" || key === "_" ? -1 : 1;
      patchSelectedLeafMedia(
        (entry) => {
          entry.zoom = clampLeafZoom((Number(entry.zoom) || 1) + direction * ZOOM_WHEEL_STEP);
          return entry;
        },
        { live: true, groupPrefix: "collage-frame-keys" }
      );
    }
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
  document.getElementById("studio-empty-create-collage")?.addEventListener("click", addCollage);

  const emptyRoot = document.getElementById("studio-empty-root");
  const emptyStart = document.getElementById("studio-empty-start");
  const emptyHints = document.getElementById("studio-empty-hints");
  if (emptyRoot && emptyStart && emptyHints) {
    const projectId = document.getElementById("studio-root")?.getAttribute("data-project-id") || "";
    const dismissKey = `orga-drone:studio-empty-start:${projectId}`;
    const showHints = () => {
      emptyStart.hidden = true;
      emptyHints.hidden = false;
      try {
        if (projectId) sessionStorage.setItem(dismissKey, "1");
      } catch {
        /* ignore quota / private mode */
      }
    };
    try {
      if (projectId && sessionStorage.getItem(dismissKey) === "1") {
        showHints();
      }
    } catch {
      /* ignore */
    }
    document.getElementById("studio-empty-edit-normal")?.addEventListener("click", showHints);
    document.getElementById("studio-empty-skip")?.addEventListener("click", showHints);
  }
  document.getElementById("inspector-collage-from-library")?.addEventListener("click", () => {
    openLibraryPicker();
  });
  document.getElementById("inspector-collage-from-computer")?.addEventListener("click", () => {
    pickComputerFiles();
  });
  document.getElementById("studio-collage-frame-from-library")?.addEventListener("click", () => {
    openLibraryPicker();
  });
  document.getElementById("studio-collage-frame-from-computer")?.addEventListener("click", () => {
    pickComputerFiles();
  });
  document.getElementById("studio-collage-source-library")?.addEventListener("click", () => {
    openLibraryPicker();
  });
  document.getElementById("studio-collage-source-computer")?.addEventListener("click", () => {
    pickComputerFiles();
  });
  document.getElementById("studio-collage-source-cancel")?.addEventListener("click", () => {
    closeSourceChooser();
  });
  sourceDialog?.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeSourceChooser();
  });
  document.getElementById("inspector-collage-clear-cell")?.addEventListener("click", () => {
    const clip = clipForLeafAction();
    if (!isCollage(clip) || !selectedLeafId) return;
    voidSave(
      clip,
      { op: "assign_media", leaf_id: selectedLeafId, media: null },
      gestureGroup("collage-clear")
    ).then(() => {
      if (isStillSelected(clip)) {
        fillInspector(clip);
        notifyLeafSelection(clip);
      }
    });
  });
  document.getElementById("inspector-collage-open-frame")?.addEventListener("click", () => {
    const clip = clipForLeafAction();
    if (!isCollage(clip) || !selectedLeafId) return;
    const media = leafMedia(clip, selectedLeafId);
    if (!media) return;
    const leaf = { id: selectedLeafId };
    const cell = stage?.querySelector(
      `.studio-collage-cell[data-leaf-id="${CSS.escape(String(selectedLeafId))}"]`
    );
    openFrameModalForLeaf(clip, leaf, media, cell);
  });
  fitEl?.addEventListener("change", () => {
    patchSelectedLeafMedia((media) => {
      media.fit = fitEl.value === "fit" ? "fit" : "fill";
      return media;
    });
  });
  zoomEl?.addEventListener("input", () => {
    patchSelectedLeafMedia(
      (media) => {
        const zoom = Number(zoomEl.value);
        media.zoom = Number.isFinite(zoom) ? zoom : 1;
        return media;
      },
      { live: true, groupPrefix: "collage-frame-slider" }
    );
  });
  panXEl?.addEventListener("input", () => {
    patchSelectedLeafMedia(
      (media) => {
        const pan = Number(panXEl.value);
        media.pan_x = Number.isFinite(pan) ? pan : 0.5;
        return media;
      },
      { live: true, groupPrefix: "collage-frame-slider" }
    );
  });
  panYEl?.addEventListener("input", () => {
    patchSelectedLeafMedia(
      (media) => {
        const pan = Number(panYEl.value);
        media.pan_y = Number.isFinite(pan) ? pan : 0.5;
        return media;
      },
      { live: true, groupPrefix: "collage-frame-slider" }
    );
  });
  document.getElementById("studio-collage-library-cancel")?.addEventListener("click", () => {
    closeLibraryPicker();
  });
  document.getElementById("studio-collage-library-add")?.addEventListener("click", (event) => {
    event.preventDefault();
    void commitLibrarySelection();
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

  const frameEl = document.getElementById("studio-preview-frame");
  const resizeTargets = [preview, preview?.parentElement, frameEl].filter(Boolean);
  if (typeof ResizeObserver === "function" && resizeTargets.length) {
    const ro = new ResizeObserver(() => {
      window.clearTimeout(hostResizeTimer);
      hostResizeTimer = window.setTimeout(() => {
        const clip = previewClip || opts.getSelectedClip?.();
        if (!clip || !isCollage(clip) || preview?.hidden) return;
        if (framingDrag || framingQuiet) return;
        const spec = parseSpec(clip);
        scheduleHostRelayout(clip, aspectCss(spec));
      }, 60);
    });
    resizeTargets.forEach((el) => {
      try {
        ro.observe(el);
      } catch {
        /* ignore */
      }
    });
  }

  return {
    isCollage,
    fillInspector,
    hidePreview,
    renderPreview,
    refreshFrameModalGrade,
    isFramingQuiet,
    getSelectedLeafId: () => selectedLeafId,
    getSelectedLeafOwnerId: () => selectedLeafOwnerId,
    selectedLeafMedia,
    syncPlayback: (args) => {
      const playing = Boolean(args?.playing);
      preview?.classList.toggle("is-paused", !playing);
      const clip = opts.getSelectedClip?.();
      const spec = clip && isCollage(clip) ? parseSpec(clip) : null;
      const keepUnderlay = shouldKeepComposedUnderlay(spec, playing);
      if (playing && composedImg) {
        if (keepUnderlay) {
          composedImg.hidden = false;
          composedImg.style.visibility = "visible";
          composedImg.style.opacity = "1";
          setHasComposedStill(true);
          if (clip && !composedImg.getAttribute("src")) scheduleComposedPreview(clip);
        } else {
          composedImg.hidden = true;
          composedImg.style.visibility = "hidden";
          setHasComposedStill(false);
        }
      }
      playback.sync(args);
      if (!playing) {
        if (clip && isCollage(clip)) scheduleComposedPreview(clip);
      }
    },
    pausePlayback: () => {
      playback.pause();
      const clip = opts.getSelectedClip?.();
      const spec = clip && isCollage(clip) ? parseSpec(clip) : null;
      playback.sync({
        localS: Number(opts.getCollageLocalS?.() || 0),
        playing: false,
        seek: true,
        spec,
      });
      preview?.classList.toggle("is-paused", true);
      if (clip && isCollage(clip)) scheduleComposedPreview(clip);
    },
    teardownPlayback: () => playback.teardown(),
    isPlaybackFallback: () => playback.isFallback(),
    parseSpec,
  };
}
