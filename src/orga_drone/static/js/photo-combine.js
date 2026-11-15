/**
 * Photo Workspace Image Composer (#453 / picker UX).
 * Library multi-select + desktop multi-file pick, ordered list, preview, export.
 */
(function () {
  "use strict";

  const dialog = document.getElementById("detail-photo-combine-dialog");
  const openBtn = document.getElementById("detail-photo-combine-open");
  if (!dialog || !openBtn) return;

  const listEl = document.getElementById("detail-photo-combine-list");
  const fromLibraryBtn = document.getElementById("detail-photo-combine-from-library");
  const fromComputerBtn = document.getElementById("detail-photo-combine-from-computer");
  const libraryDialog = document.getElementById("detail-photo-combine-library-dialog");
  const libraryGrid = document.getElementById("detail-photo-combine-library-grid");
  const libraryFilter = document.getElementById("detail-photo-combine-library-filter");
  const libraryEmpty = document.getElementById("detail-photo-combine-library-empty");
  const libraryCancel = document.getElementById("detail-photo-combine-library-cancel");
  const libraryAdd = document.getElementById("detail-photo-combine-library-add");
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

  const IMAGE_FILE_TYPES = [
    "Images (*.png;*.jpg;*.jpeg;*.webp;*.heic;*.heif;*.dng)",
    "All files (*.*)",
  ];

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
    pickerUnavailable: ds.msgPickerUnavailable || "Desktop file picker is unavailable. Start Orga Drone as a desktop app.",
    unreadable: ds.msgUnreadable || "One selected file could not be read. Choose another photo.",
    libraryEmpty: ds.msgLibraryEmpty || "No photos in the library yet.",
    selectLibrary: ds.msgSelectLibrary || "Select at least one photo.",
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
  let libraryItems = [];
  let librarySelected = {};
  let libraryFilterTimer = null;

  function nextEntryId() {
    entrySeq += 1;
    return "e" + entrySeq;
  }

  function seedEntries() {
    const mediaId = Number(ds.seedMediaId || 0);
    const filename = ds.seedFilename || ("photo-" + mediaId);
    entries = mediaId > 0
      ? [{ entryId: nextEntryId(), mediaId: mediaId, sourcePath: null, filename: filename }]
      : [];
  }

  function filenameFromPath(path) {
    const text = String(path || "").replace(/\\/g, "/");
    const parts = text.split("/");
    return parts[parts.length - 1] || text || "photo";
  }

  function specPayload() {
    const spacing = Math.max(0, Math.floor(Number(spacingEl.value) || 0));
    return {
      entries: entries.map(function (e) {
        if (e.sourcePath) {
          return { entry_id: e.entryId, source_path: e.sourcePath };
        }
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
    if (fromLibraryBtn) fromLibraryBtn.disabled = busy;
    if (fromComputerBtn) fromComputerBtn.disabled = busy;
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

      let thumb;
      if (entry.mediaId) {
        thumb = document.createElement("img");
        thumb.className = "photo-combine-thumb";
        thumb.alt = "";
        thumb.loading = "lazy";
        thumb.src = "/media/" + entry.mediaId + "/thumb";
      } else {
        thumb = document.createElement("span");
        thumb.className = "photo-combine-thumb photo-combine-thumb-external";
        thumb.setAttribute("aria-hidden", "true");
      }

      const meta = document.createElement("div");
      meta.className = "photo-combine-item-meta";
      const pos = document.createElement("span");
      pos.className = "photo-combine-item-pos";
      pos.textContent = String(index + 1);
      const name = document.createElement("span");
      name.className = "photo-combine-item-name";
      name.textContent = entry.filename;
      name.title = entry.sourcePath || entry.filename;
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

  function addLibraryEntry(mediaId, filename) {
    entries.push({
      entryId: nextEntryId(),
      mediaId: Number(mediaId),
      sourcePath: null,
      filename: filename || ("photo-" + mediaId),
    });
  }

  function addExternalEntry(path) {
    entries.push({
      entryId: nextEntryId(),
      mediaId: null,
      sourcePath: String(path),
      filename: filenameFromPath(path),
    });
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

  function selectedLibraryCount() {
    return Object.keys(librarySelected).length;
  }

  function syncLibraryAddButton() {
    if (libraryAdd) libraryAdd.disabled = busy || selectedLibraryCount() < 1;
  }

  function renderLibraryGrid(filterText) {
    if (!libraryGrid) return;
    const needle = String(filterText || "").trim().toLowerCase();
    libraryGrid.innerHTML = "";
    const visible = libraryItems.filter(function (item) {
      if (!item || item.kind !== "photo") return false;
      if (!needle) return true;
      return String(item.filename || "").toLowerCase().indexOf(needle) !== -1;
    });
    if (libraryEmpty) {
      if (!libraryItems.length) {
        libraryEmpty.textContent = msg.libraryEmpty;
        libraryEmpty.hidden = false;
      } else if (!visible.length) {
        libraryEmpty.textContent = msg.searchEmpty;
        libraryEmpty.hidden = false;
      } else {
        libraryEmpty.hidden = true;
        libraryEmpty.textContent = "";
      }
    }
    visible.forEach(function (item) {
      const id = String(item.id);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "photo-combine-picker-card";
      btn.setAttribute("role", "option");
      btn.setAttribute("aria-selected", librarySelected[id] ? "true" : "false");
      if (librarySelected[id]) btn.classList.add("is-selected");
      btn.innerHTML =
        '<img src="/media/' + item.id + '/thumb" alt="" loading="lazy">' +
        '<span></span>';
      btn.querySelector("span").textContent = item.filename || ("#" + item.id);
      btn.addEventListener("click", function () {
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

  async function loadLibraryPhotos(query) {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: "photo",
        q: String(query || "").trim(),
        limit: 120,
        sort: "recorded_at",
        order: "desc",
      }),
    });
    const data = await res.json().catch(function () { return null; });
    libraryItems = ((data && data.items) || []).filter(function (item) {
      return item && item.kind === "photo";
    });
    renderLibraryGrid(libraryFilter ? libraryFilter.value : "");
  }

  async function openLibraryPicker() {
    if (!libraryDialog || busy) return;
    librarySelected = {};
    if (libraryFilter) libraryFilter.value = "";
    syncLibraryAddButton();
    try {
      await loadLibraryPhotos("");
    } catch (_err) {
      libraryItems = [];
      renderLibraryGrid("");
      setError(msg.failed);
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

  function commitLibrarySelection() {
    const selected = Object.keys(librarySelected).map(function (key) {
      return librarySelected[key];
    });
    if (!selected.length) {
      setError(msg.selectLibrary);
      return;
    }
    selected.forEach(function (item) {
      addLibraryEntry(item.id, item.filename);
    });
    revision += 1;
    closeLibraryPicker();
    setError("");
    renderList();
  }

  async function pickComputerFiles() {
    if (busy) return;
    try {
      const res = await fetch("/api/desktop/pick-open-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          allow_multiple: true,
          file_types: IMAGE_FILE_TYPES,
        }),
      });
      if (res.status === 503) {
        setError(msg.pickerUnavailable);
        return;
      }
      const data = await res.json().catch(function () { return null; });
      if (!data || data.status === "cancelled") return;
      if (data.status !== "ok") {
        setError(msg.pickerUnavailable);
        return;
      }
      const paths = Array.isArray(data.paths)
        ? data.paths
        : (data.path ? [data.path] : []);
      if (!paths.length) return;
      paths.forEach(function (path) {
        if (path) addExternalEntry(path);
      });
      revision += 1;
      setError("");
      renderList();
    } catch (_err) {
      setError(msg.unreadable);
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
    if (!data || data.status === "cancelled" || data.cancelled) return null;
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
    renderList();
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  });

  if (fromLibraryBtn) {
    fromLibraryBtn.addEventListener("click", function (ev) {
      ev.preventDefault();
      openLibraryPicker();
    });
  }
  if (fromComputerBtn) {
    fromComputerBtn.addEventListener("click", function (ev) {
      ev.preventDefault();
      pickComputerFiles();
    });
  }
  if (libraryCancel) {
    libraryCancel.addEventListener("click", function (ev) {
      ev.preventDefault();
      closeLibraryPicker();
    });
  }
  if (libraryAdd) {
    libraryAdd.addEventListener("click", function (ev) {
      ev.preventDefault();
      commitLibrarySelection();
    });
  }
  if (libraryFilter) {
    libraryFilter.addEventListener("input", function () {
      if (libraryFilterTimer) clearTimeout(libraryFilterTimer);
      libraryFilterTimer = setTimeout(function () {
        loadLibraryPhotos(libraryFilter.value).catch(function () {
          libraryItems = [];
          renderLibraryGrid(libraryFilter.value);
        });
      }, 220);
    });
  }

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
    closeLibraryPicker();
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
})();
