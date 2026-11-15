/**
 * Photo Workspace Image Composer (#453).
 * Compact dialog: ordered list, search-add, preview, PNG/JPEG export via shared job store.
 */
(function () {
  "use strict";

  const dialog = document.getElementById("detail-photo-combine-dialog");
  const openBtn = document.getElementById("detail-photo-combine-open");
  if (!dialog || !openBtn) return;

  const listEl = document.getElementById("detail-photo-combine-list");
  const searchInput = document.getElementById("detail-photo-combine-search");
  const searchResults = document.getElementById("detail-photo-combine-search-results");
  const layoutEl = document.getElementById("detail-photo-combine-layout");
  const spacingEl = document.getElementById("detail-photo-combine-spacing");
  const backgroundEl = document.getElementById("detail-photo-combine-background");
  const formatEl = document.getElementById("detail-photo-combine-format");
  const dimsEl = document.getElementById("detail-photo-combine-dims");
  const errorEl = document.getElementById("detail-photo-combine-error");
  const previewImg = document.getElementById("detail-photo-combine-preview");
  const previewHint = document.getElementById("detail-photo-combine-preview-hint");
  const exportBtn = document.getElementById("detail-photo-combine-export");
  const cancelBtn = document.getElementById("detail-photo-combine-cancel");
  const progressWrap = document.getElementById("detail-photo-combine-progress");
  const progressBar = document.getElementById("detail-photo-combine-progress-bar");
  const progressLabel = document.getElementById("detail-photo-combine-progress-label");
  const successRoot = document.getElementById("detail-export-success");
  const successTitle = document.getElementById("detail-export-success-title");
  const successPath = document.getElementById("detail-export-success-path");

  const ds = dialog.dataset;
  const msg = {
    needMore: ds.msgNeedMore || "Add at least one more image.",
    running: ds.msgRunning || "Combining images…",
    failed: ds.msgFailed || "Could not combine these images.",
    cancelled: ds.msgCancelled || "Combine cancelled.",
    done: ds.msgDone || "Combined image saved.",
    preparing: ds.msgPreparing || "Preparing combine…",
    desktop: ds.msgDesktop || "Desktop save dialog is unavailable.",
    searchEmpty: ds.msgSearchEmpty || "No matching photos.",
    transparentJpeg: ds.msgTransparentJpeg || "JPEG cannot use a transparent background. White was selected.",
    remove: ds.msgRemove || "Remove",
    moveEarlier: ds.msgMoveEarlier || "Move earlier",
    moveLater: ds.msgMoveLater || "Move later",
    position: ds.msgPosition || "Position {n}",
    defaultFilename: ds.defaultFilename || "combined",
  };

  let entries = [];
  let entrySeq = 1;
  let revision = 1;
  let previewUrl = null;
  let previewTimer = null;
  let previewAbort = null;
  let inspectTimer = null;
  let jobId = null;
  let pollTimer = null;
  let busy = false;
  let dragEntryId = null;

  function nextEntryId() {
    entrySeq += 1;
    return "e" + entrySeq;
  }

  function seedEntries() {
    const mediaId = Number(ds.seedMediaId || 0);
    const filename = ds.seedFilename || ("photo-" + mediaId);
    entries = mediaId > 0
      ? [{ entryId: nextEntryId(), mediaId: mediaId, filename: filename }]
      : [];
  }

  function specPayload() {
    const spacing = Math.max(0, Math.floor(Number(spacingEl.value) || 0));
    return {
      entries: entries.map(function (e) {
        return { entry_id: e.entryId, media_id: e.mediaId };
      }),
      layout: layoutEl.value === "vertical" ? "vertical" : "horizontal",
      spacing: spacing,
      background: backgroundEl.value,
      format: formatEl.value === "jpeg" ? "jpeg" : "png",
      revision: revision,
    };
  }

  function setError(text) {
    if (!errorEl) return;
    if (!text) {
      errorEl.hidden = true;
      errorEl.textContent = "";
      return;
    }
    errorEl.hidden = false;
    errorEl.textContent = text;
  }

  function setBusy(on) {
    busy = !!on;
    openBtn.disabled = busy;
    exportBtn.disabled = busy || entries.length < 2;
    cancelBtn.disabled = false;
    layoutEl.disabled = busy;
    spacingEl.disabled = busy;
    backgroundEl.disabled = busy;
    formatEl.disabled = busy;
    searchInput.disabled = busy;
  }

  function revokePreview() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }
    if (previewImg) {
      previewImg.removeAttribute("src");
      previewImg.hidden = true;
    }
    if (previewHint) previewHint.hidden = false;
  }

  function renderList() {
    listEl.innerHTML = "";
    entries.forEach(function (entry, index) {
      const li = document.createElement("li");
      li.className = "photo-combine-item";
      li.draggable = !busy;
      li.dataset.entryId = entry.entryId;
      li.setAttribute("aria-grabbed", "false");

      const thumb = document.createElement("img");
      thumb.className = "photo-combine-thumb";
      thumb.alt = "";
      thumb.loading = "lazy";
      thumb.src = "/media/" + entry.mediaId + "/thumb";

      const meta = document.createElement("div");
      meta.className = "photo-combine-item-meta";
      const pos = document.createElement("span");
      pos.className = "photo-combine-item-pos";
      pos.textContent = String(index + 1);
      const name = document.createElement("span");
      name.className = "photo-combine-item-name";
      name.textContent = entry.filename;
      name.title = entry.filename;
      meta.appendChild(pos);
      meta.appendChild(name);

      const actions = document.createElement("div");
      actions.className = "photo-combine-item-actions";

      const earlier = document.createElement("button");
      earlier.type = "button";
      earlier.className = "button ghost photo-combine-move";
      earlier.textContent = "↑";
      earlier.title = msg.moveEarlier;
      earlier.setAttribute("aria-label", msg.moveEarlier);
      earlier.disabled = busy || index === 0;
      earlier.addEventListener("click", function () {
        moveEntry(entry.entryId, -1);
      });

      const later = document.createElement("button");
      later.type = "button";
      later.className = "button ghost photo-combine-move";
      later.textContent = "↓";
      later.title = msg.moveLater;
      later.setAttribute("aria-label", msg.moveLater);
      later.disabled = busy || index === entries.length - 1;
      later.addEventListener("click", function () {
        moveEntry(entry.entryId, 1);
      });

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button ghost";
      remove.textContent = msg.remove;
      remove.disabled = busy;
      remove.addEventListener("click", function () {
        removeEntry(entry.entryId);
      });

      actions.appendChild(earlier);
      actions.appendChild(later);
      actions.appendChild(remove);

      li.appendChild(thumb);
      li.appendChild(meta);
      li.appendChild(actions);

      li.addEventListener("dragstart", function (ev) {
        if (busy) {
          ev.preventDefault();
          return;
        }
        dragEntryId = entry.entryId;
        li.setAttribute("aria-grabbed", "true");
        ev.dataTransfer.effectAllowed = "move";
        try {
          ev.dataTransfer.setData("text/plain", entry.entryId);
        } catch (_e) { /* ignore */ }
      });
      li.addEventListener("dragend", function () {
        dragEntryId = null;
        li.setAttribute("aria-grabbed", "false");
        listEl.querySelectorAll(".photo-combine-item").forEach(function (node) {
          node.classList.remove("photo-combine-drop-target");
        });
      });
      li.addEventListener("dragover", function (ev) {
        if (!dragEntryId || dragEntryId === entry.entryId) return;
        ev.preventDefault();
        li.classList.add("photo-combine-drop-target");
      });
      li.addEventListener("dragleave", function () {
        li.classList.remove("photo-combine-drop-target");
      });
      li.addEventListener("drop", function (ev) {
        ev.preventDefault();
        li.classList.remove("photo-combine-drop-target");
        const fromId = dragEntryId || (ev.dataTransfer && ev.dataTransfer.getData("text/plain"));
        if (!fromId || fromId === entry.entryId) return;
        reorderEntry(fromId, entry.entryId);
      });

      listEl.appendChild(li);
    });
    exportBtn.disabled = busy || entries.length < 2;
    scheduleInspectAndPreview();
  }

  function indexOfEntry(entryId) {
    return entries.findIndex(function (e) { return e.entryId === entryId; });
  }

  function moveEntry(entryId, delta) {
    const i = indexOfEntry(entryId);
    if (i < 0) return;
    const j = i + delta;
    if (j < 0 || j >= entries.length) return;
    const copy = entries.slice();
    const tmp = copy[i];
    copy[i] = copy[j];
    copy[j] = tmp;
    entries = copy;
    revision += 1;
    renderList();
  }

  function reorderEntry(fromId, beforeId) {
    const from = indexOfEntry(fromId);
    let to = indexOfEntry(beforeId);
    if (from < 0 || to < 0 || from === to) return;
    const copy = entries.slice();
    const [item] = copy.splice(from, 1);
    if (from < to) to -= 1;
    copy.splice(to, 0, item);
    entries = copy;
    revision += 1;
    renderList();
  }

  function removeEntry(entryId) {
    entries = entries.filter(function (e) { return e.entryId !== entryId; });
    revision += 1;
    renderList();
  }

  function addEntry(mediaId, filename) {
    entries.push({
      entryId: nextEntryId(),
      mediaId: Number(mediaId),
      filename: filename || ("photo-" + mediaId),
    });
    revision += 1;
    renderList();
  }

  function syncFormatBackground() {
    if (formatEl.value === "jpeg" && backgroundEl.value === "transparent") {
      backgroundEl.value = "white";
      setError(msg.transparentJpeg);
    }
  }

  function scheduleInspectAndPreview() {
    if (inspectTimer) clearTimeout(inspectTimer);
    if (previewTimer) clearTimeout(previewTimer);
    inspectTimer = setTimeout(runInspect, 120);
    previewTimer = setTimeout(runPreview, 280);
  }

  async function runInspect() {
    if (entries.length < 2) {
      if (dimsEl) dimsEl.textContent = msg.needMore;
      setError("");
      exportBtn.disabled = true;
      revokePreview();
      return;
    }
    try {
      const res = await fetch("/api/photo-combine/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(specPayload()),
      });
      const data = await res.json().catch(function () { return null; });
      if (!res.ok || !data) {
        setError((data && data.detail) || msg.failed);
        exportBtn.disabled = true;
        return;
      }
      if (data.revision != null && Number(data.revision) !== revision) return;
      if (dimsEl) {
        dimsEl.textContent = data.width && data.height
          ? (data.width + " × " + data.height + " · " + data.count)
          : "";
      }
      if (!data.ok) {
        setError(data.error || msg.failed);
        exportBtn.disabled = true;
      } else {
        setError("");
        exportBtn.disabled = busy;
      }
    } catch (_err) {
      setError(msg.failed);
      exportBtn.disabled = true;
    }
  }

  async function runPreview() {
    if (entries.length < 2) {
      if (previewAbort) {
        previewAbort.abort();
        previewAbort = null;
      }
      revokePreview();
      return;
    }
    const expectedRevision = revision;
    if (previewAbort) previewAbort.abort();
    previewAbort = typeof AbortController !== "undefined" ? new AbortController() : null;
    try {
      const res = await fetch("/api/photo-combine/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(specPayload()),
        signal: previewAbort ? previewAbort.signal : undefined,
      });
      if (res.status === 409) return;
      if (!res.ok) {
        const data = await res.json().catch(function () { return null; });
        setError((data && data.detail) || msg.failed);
        revokePreview();
        return;
      }
      if (expectedRevision !== revision) return;
      const blob = await res.blob();
      if (expectedRevision !== revision) return;
      revokePreview();
      previewUrl = URL.createObjectURL(blob);
      previewImg.src = previewUrl;
      previewImg.hidden = false;
      if (previewHint) previewHint.hidden = true;
    } catch (err) {
      if (err && err.name === "AbortError") return;
      revokePreview();
    }
  }

  let searchTimer = null;
  async function runSearch(q) {
    const query = String(q || "").trim();
    if (!query) {
      searchResults.hidden = true;
      searchResults.innerHTML = "";
      return;
    }
    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "photo", q: query, limit: 24 }),
      });
      const data = await res.json().catch(function () { return null; });
      const items = (data && data.items) || [];
      searchResults.innerHTML = "";
      if (!items.length) {
        const li = document.createElement("li");
        li.className = "photo-combine-search-empty";
        li.textContent = msg.searchEmpty;
        searchResults.appendChild(li);
        searchResults.hidden = false;
        return;
      }
      items.forEach(function (item) {
        if (!item || item.kind !== "photo") return;
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "photo-combine-search-hit";
        btn.innerHTML =
          '<img src="/media/' + item.id + '/thumb" alt="" loading="lazy">' +
          '<span></span>';
        btn.querySelector("span").textContent = item.filename || ("#" + item.id);
        btn.addEventListener("click", function () {
          addEntry(item.id, item.filename);
          searchInput.value = "";
          searchResults.hidden = true;
          searchResults.innerHTML = "";
        });
        li.appendChild(btn);
        searchResults.appendChild(li);
      });
      searchResults.hidden = false;
    } catch (_err) {
      searchResults.hidden = true;
    }
  }

  function showSuccess(path) {
    if (!successRoot || !successTitle) return;
    successTitle.textContent = msg.done;
    if (successPath) {
      successPath.textContent = path || "";
      successPath.hidden = !path;
    }
    successRoot.hidden = false;
  }

  async function pickSavePath(filename) {
    const res = await fetch("/api/desktop/pick-save-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: filename }),
    });
    if (res.status === 503) {
      throw new Error(msg.desktop);
    }
    const data = await res.json().catch(function () { return null; });
    if (!data || data.cancelled) return null;
    if (!data.path) throw new Error(msg.desktop);
    return data.path;
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function pollJob() {
    if (!jobId) return;
    try {
      const res = await fetch("/api/studio/export/jobs/" + encodeURIComponent(jobId));
      const data = await res.json().catch(function () { return null; });
      if (!data) return;
      const pct = Math.max(0, Math.min(100, Number(data.percent) || 0));
      if (progressBar) progressBar.style.width = pct + "%";
      if (progressLabel) {
        progressLabel.textContent = data.state === "running" || data.state === "pending"
          ? (msg.running + " " + pct + "%")
          : (data.error || msg.failed);
      }
      if (data.state === "completed") {
        stopPoll();
        setBusy(false);
        if (progressWrap) progressWrap.hidden = true;
        showSuccess(data.output_path || data.filename || "");
        dialog.close();
        return;
      }
      if (data.state === "failed" || data.state === "cancelled") {
        stopPoll();
        setBusy(false);
        if (progressWrap) progressWrap.hidden = true;
        setError(data.state === "cancelled" ? msg.cancelled : (data.error || msg.failed));
        jobId = null;
      }
    } catch (_err) {
      /* keep polling briefly */
    }
  }

  async function startExport() {
    if (busy || entries.length < 2) return;
    syncFormatBackground();
    setError("");
    const fmt = formatEl.value === "jpeg" ? "jpeg" : "png";
    const filename = msg.defaultFilename + (fmt === "png" ? ".png" : ".jpg");
    let outputPath;
    try {
      outputPath = await pickSavePath(filename);
    } catch (err) {
      setError(err && err.message ? err.message : msg.desktop);
      return;
    }
    if (!outputPath) return;

    setBusy(true);
    if (progressWrap) progressWrap.hidden = false;
    if (progressBar) progressBar.style.width = "0%";
    if (progressLabel) progressLabel.textContent = msg.preparing;

    try {
      const body = Object.assign(specPayload(), { output_path: outputPath });
      const res = await fetch("/api/photo-combine/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(function () { return null; });
      if (!res.ok || !data || !data.job_id) {
        setBusy(false);
        if (progressWrap) progressWrap.hidden = true;
        setError((data && data.detail) || msg.failed);
        return;
      }
      jobId = data.job_id;
      stopPoll();
      pollTimer = setInterval(pollJob, 400);
      pollJob();
    } catch (_err) {
      setBusy(false);
      if (progressWrap) progressWrap.hidden = true;
      setError(msg.failed);
    }
  }

  async function cancelExportOrClose() {
    if (jobId && busy) {
      try {
        await fetch("/api/studio/export/jobs/" + encodeURIComponent(jobId) + "/cancel", {
          method: "POST",
        });
      } catch (_err) { /* ignore */ }
      return;
    }
    dialog.close();
  }

  openBtn.addEventListener("click", function () {
    seedEntries();
    revision = 1;
    spacingEl.value = "0";
    layoutEl.value = "horizontal";
    backgroundEl.value = "white";
    formatEl.value = "png";
    setError("");
    if (progressWrap) progressWrap.hidden = true;
    searchResults.hidden = true;
    searchResults.innerHTML = "";
    searchInput.value = "";
    renderList();
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  });

  cancelBtn.addEventListener("click", function (ev) {
    ev.preventDefault();
    cancelExportOrClose();
  });

  dialog.addEventListener("cancel", function (ev) {
    if (busy) {
      ev.preventDefault();
      cancelExportOrClose();
    }
  });

  dialog.addEventListener("close", function () {
    stopPoll();
    revokePreview();
    setBusy(false);
    jobId = null;
  });

  exportBtn.addEventListener("click", function (ev) {
    ev.preventDefault();
    startExport();
  });

  [layoutEl, spacingEl, backgroundEl, formatEl].forEach(function (el) {
    el.addEventListener("change", function () {
      syncFormatBackground();
      revision += 1;
      scheduleInspectAndPreview();
    });
  });
  spacingEl.addEventListener("input", function () {
    revision += 1;
    scheduleInspectAndPreview();
  });

  searchInput.addEventListener("input", function () {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      runSearch(searchInput.value);
    }, 220);
  });
})();
