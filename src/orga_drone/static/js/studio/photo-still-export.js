/** Photo-clip still export UI (#499 / Adaptive Studio PR1 / #505 topbar). */

function clipKindOf(clip) {
  if (!clip) return "";
  if (typeof clip === "string") return String(clip).toLowerCase();
  const kind = clip.kind || clip.dataset?.kind || clip.item_kind || "";
  return String(kind).toLowerCase();
}

/**
 * JPG/PNG topbar export is available only for single-photo projects.
 * Focus (Photo/Story) must not affect this rule.
 */
export function projectAllowsPhotoStillExport(clips) {
  const list = Array.isArray(clips) ? clips.filter(Boolean) : [];
  if (list.length !== 1) return false;
  return clipKindOf(list[0]) === "photo";
}

export function createPhotoStillExportUi({
  getSelectedClip,
  getClips,
  fetchImpl = fetch,
  documentImpl = document,
} = {}) {
  const panel = documentImpl.getElementById("studio-photo-still-export");
  const openBtn = documentImpl.getElementById("studio-photo-still-export-open");
  const popover = documentImpl.getElementById("studio-photo-still-export-popover");
  const formatEl = documentImpl.getElementById("inspector-photo-still-format");
  const exportBtn = documentImpl.getElementById("inspector-photo-still-export-btn");
  const statusEl = documentImpl.getElementById("inspector-photo-still-export-status");
  if (!panel || !exportBtn || !openBtn) {
    return { sync() {}, close() {} };
  }

  let busy = false;
  let pollTimer = null;
  let open = false;

  function msg(key, fallback) {
    const value = panel.dataset[key];
    return value && String(value).trim() ? String(value) : fallback;
  }

  function setStatus(text, { error = false } = {}) {
    if (!statusEl) return;
    const value = text == null ? "" : String(text);
    statusEl.hidden = !value;
    statusEl.textContent = value;
    statusEl.classList.toggle("is-error", Boolean(error) && Boolean(value));
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function setOpen(next) {
    open = Boolean(next);
    if (popover) popover.hidden = !open;
    openBtn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open && formatEl) {
      try {
        formatEl.focus({ preventScroll: true });
      } catch {
        /* ignore */
      }
    }
  }

  function closePopover() {
    setOpen(false);
  }

  function resolveExportClip() {
    const selected = getSelectedClip?.();
    if (selected && clipKindOf(selected) === "photo") return selected;
    const clips = getClips?.() || [];
    if (projectAllowsPhotoStillExport(clips)) return clips[0];
    return null;
  }

  async function pickSavePath(filename) {
    const res = await fetchImpl("/api/desktop/pick-save-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, filters: [["Images", "*.jpg;*.jpeg;*.png"]] }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = data && data.detail;
      throw new Error(
        typeof detail === "string"
          ? detail
          : msg("photoStillUnavailable", "Export needs the desktop app for the save dialog.")
      );
    }
    return data && data.path ? String(data.path) : "";
  }

  async function pollJob(jobId) {
    try {
      const res = await fetchImpl(`/api/studio/export/jobs/${encodeURIComponent(jobId)}`);
      const data = await res.json().catch(() => null);
      if (!res.ok || !data) return;
      const state = data.state || data.status;
      if (state === "running" || state === "queued" || state === "pending") {
        const percent = Number(data.percent);
        setStatus(
          Number.isFinite(percent) ? `… ${Math.max(0, Math.min(100, Math.round(percent)))}%` : "…"
        );
        return;
      }
      stopPoll();
      busy = false;
      exportBtn.disabled = false;
      if (state === "done" || state === "completed") {
        setStatus(data.filename || data.output_path || "OK");
        return;
      }
      if (state === "cancelled") {
        setStatus(msg("photoStillCancelled", "Photo export cancelled."), { error: true });
        return;
      }
      setStatus(
        data.error || data.detail || msg("photoStillFailed", "Could not export this photo."),
        { error: true }
      );
    } catch {
      /* keep polling briefly */
    }
  }

  async function exportStill() {
    if (busy) return;
    const clip = resolveExportClip();
    if (!clip || clipKindOf(clip) !== "photo") return;
    const studioId = String(clip.dataset?.studioId || clip.studio_id || clip.id || "");
    if (!studioId) return;
    const fmt = formatEl?.value === "png" ? "png" : "jpeg";
    const base = msg("photoStillDefault", "photo");
    const filename = `${base}${fmt === "png" ? ".png" : ".jpg"}`;
    let outputPath;
    try {
      outputPath = await pickSavePath(filename);
    } catch (err) {
      setStatus(
        err && err.message ? err.message : msg("photoStillFailed", "Could not export this photo."),
        { error: true }
      );
      return;
    }
    if (!outputPath) return;
    busy = true;
    exportBtn.disabled = true;
    setStatus("…");
    try {
      const res = await fetchImpl(`/api/studio/${encodeURIComponent(studioId)}/still/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          format: fmt,
          preset: "best",
          output_path: outputPath,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.job_id) {
        busy = false;
        exportBtn.disabled = false;
        setStatus(
          (data && data.detail) || msg("photoStillFailed", "Could not export this photo."),
          { error: true }
        );
        return;
      }
      stopPoll();
      pollTimer = setInterval(() => pollJob(data.job_id), 400);
      pollJob(data.job_id);
    } catch {
      busy = false;
      exportBtn.disabled = false;
      setStatus(msg("photoStillFailed", "Could not export this photo."), { error: true });
    }
  }

  function sync() {
    const clips = getClips?.() || [];
    const allow = projectAllowsPhotoStillExport(clips);
    openBtn.hidden = !allow;
    openBtn.disabled = !allow;
    panel.hidden = !allow;
    if (!allow) {
      closePopover();
      setStatus("");
    }
  }

  openBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    if (openBtn.hidden || openBtn.disabled) return;
    setOpen(!open);
  });

  exportBtn.addEventListener("click", () => {
    void exportStill();
  });

  documentImpl.addEventListener?.("keydown", (event) => {
    if (event.key === "Escape" && open) {
      closePopover();
    }
  });

  documentImpl.addEventListener?.("click", (event) => {
    if (!open) return;
    const target = event.target;
    if (panel.contains?.(target)) return;
    closePopover();
  });

  sync();

  return { sync, close: closePopover };
}
