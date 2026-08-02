(function () {
  // Loading overlay + button state on scan / long-running form submits
  function isLongRunningForm(form) {
    const action = (form.getAttribute("action") || "").toLowerCase();
    return (
      action.includes("/library/add") ||
      action.includes("/scan") ||
      action.includes("scan-all") ||
      action.includes("/duplicates/scan")
    );
  }

  function ensureBusyOverlay() {
    let overlay = document.getElementById("busy-overlay");
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.id = "busy-overlay";
    overlay.className = "busy-overlay";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    overlay.setAttribute("aria-busy", "true");
    overlay.innerHTML =
      '<div class="busy-overlay-card">' +
      '<span class="busy-spinner" aria-hidden="true"></span>' +
      '<p class="busy-overlay-text"></p>' +
      '<div class="busy-progress is-indeterminate" hidden>' +
      '<div class="busy-progress-bar"></div>' +
      "</div>" +
      '<p class="busy-overlay-detail" hidden></p>' +
      '<p class="busy-overlay-path mono" hidden></p>' +
      "</div>";
    document.body.appendChild(overlay);
    return overlay;
  }

  function showBusyOverlay(message) {
    const overlay = ensureBusyOverlay();
    const text = overlay.querySelector(".busy-overlay-text");
    if (text) text.textContent = message || "Loading…";
    const detail = overlay.querySelector(".busy-overlay-detail");
    const pathEl = overlay.querySelector(".busy-overlay-path");
    const progress = overlay.querySelector(".busy-progress");
    if (detail) {
      detail.hidden = true;
      detail.textContent = "";
    }
    if (pathEl) {
      pathEl.hidden = true;
      pathEl.textContent = "";
    }
    if (progress) {
      progress.hidden = true;
      progress.classList.add("is-indeterminate");
      progress.classList.remove("is-determinate");
      const bar = progress.querySelector(".busy-progress-bar");
      if (bar) bar.style.width = "";
    }
    document.body.classList.add("is-busy");
  }

  function hideBusyOverlay() {
    document.body.classList.remove("is-busy");
    const overlay = document.getElementById("busy-overlay");
    if (overlay) overlay.setAttribute("aria-busy", "false");
  }

  function formatTemplate(template, values) {
    return String(template || "").replace(/\{(\w+)\}/g, (_, key) =>
      values[key] != null ? String(values[key]) : ""
    );
  }

  function updateScanOverlay(job, i18n) {
    const overlay = ensureBusyOverlay();
    const text = overlay.querySelector(".busy-overlay-text");
    const detail = overlay.querySelector(".busy-overlay-detail");
    const pathEl = overlay.querySelector(".busy-overlay-path");
    const progress = overlay.querySelector(".busy-progress");
    const bar = progress && progress.querySelector(".busy-progress-bar");
    const phase = job.phase || "";
    const state = job.state || "";

    let title = i18n.scanning;
    if (state === "completed") title = i18n.completed;
    else if (state === "failed") title = i18n.failed;
    else if (phase === "discovering") title = i18n.discovering;
    else if (phase === "indexing") title = i18n.indexing;
    else if (phase === "grouping") title = i18n.grouping;
    if (text) text.textContent = title;

    const discovered = Number(job.discovered) || 0;
    const processed = Number(job.processed) || 0;
    if (detail) {
      if (phase === "indexing" && state === "running") {
        detail.hidden = false;
        detail.textContent = formatTemplate(i18n.progress, {
          processed: processed,
          discovered: discovered,
        });
      } else if (state === "failed" && job.error) {
        detail.hidden = false;
        detail.textContent = job.error;
      } else {
        detail.hidden = true;
        detail.textContent = "";
      }
    }

    if (pathEl) {
      if (job.current_path && state === "running") {
        pathEl.hidden = false;
        pathEl.textContent = formatTemplate(i18n.current, { path: job.current_path });
      } else {
        pathEl.hidden = true;
        pathEl.textContent = "";
      }
    }

    if (progress && bar) {
      const determinate =
        phase === "indexing" && discovered > 0 && state === "running";
      if (state === "completed") {
        progress.hidden = false;
        progress.classList.remove("is-indeterminate");
        progress.classList.add("is-determinate");
        bar.style.width = "100%";
      } else if (determinate) {
        progress.hidden = false;
        progress.classList.remove("is-indeterminate");
        progress.classList.add("is-determinate");
        const pct = Math.max(0, Math.min(100, (processed / discovered) * 100));
        bar.style.width = pct.toFixed(1) + "%";
      } else if (state === "running" || state === "pending") {
        progress.hidden = false;
        progress.classList.add("is-indeterminate");
        progress.classList.remove("is-determinate");
        bar.style.width = "";
      } else {
        progress.hidden = true;
      }
    }

    document.body.classList.add("is-busy");
    overlay.setAttribute("aria-busy", state === "running" || state === "pending" ? "true" : "false");
  }

  function pollScanJob(jobId, i18n) {
    let finished = false;
    const poll = () => {
      if (finished) return;
      fetch("/api/scan-jobs/" + encodeURIComponent(jobId), {
        headers: { Accept: "application/json" },
      })
        .then((resp) => {
          if (resp.status === 404) {
            finished = true;
            hideBusyOverlay();
            return null;
          }
          if (!resp.ok) throw new Error("status " + resp.status);
          return resp.json();
        })
        .then((job) => {
          if (!job) return;
          updateScanOverlay(job, i18n);
          if (job.state === "completed") {
            finished = true;
            window.setTimeout(() => {
              const url = new URL(window.location.href);
              url.searchParams.delete("scan_job");
              url.searchParams.delete("scan_error");
              window.location.replace(url.pathname + (url.search || ""));
            }, 700);
            return;
          }
          if (job.state === "failed") {
            finished = true;
            window.setTimeout(() => {
              hideBusyOverlay();
              const url = new URL(window.location.href);
              url.searchParams.delete("scan_job");
              history.replaceState({}, "", url.pathname + (url.search || ""));
            }, 2500);
            return;
          }
          window.setTimeout(poll, 500);
        })
        .catch(() => {
          if (!finished) window.setTimeout(poll, 1000);
        });
    };
    showBusyOverlay(i18n.scanning);
    poll();
  }

  document.querySelectorAll("form").forEach((form) => {
    if (!isLongRunningForm(form)) return;
    form.addEventListener("submit", () => {
      const btn = form.querySelector('button[type="submit"], button:not([type])');
      if (btn && !btn.disabled) {
        btn.classList.add("is-loading");
        btn.setAttribute("aria-busy", "true");
        btn.disabled = true;
      }
      const label =
        (btn && btn.getAttribute("data-loading-label")) ||
        form.getAttribute("data-loading-label") ||
        "Scanning…";
      showBusyOverlay(label);
    });
  });

  const libraryPanel = document.getElementById("library-panel");
  if (libraryPanel) {
    const jobId = libraryPanel.getAttribute("data-scan-job") || "";
    if (jobId) {
      pollScanJob(jobId, {
        scanning: libraryPanel.getAttribute("data-i18n-scanning") || "Scanning…",
        discovering:
          libraryPanel.getAttribute("data-i18n-discovering") || "Discovering media…",
        indexing: libraryPanel.getAttribute("data-i18n-indexing") || "Indexing media…",
        grouping:
          libraryPanel.getAttribute("data-i18n-grouping") ||
          "Grouping flows and sessions…",
        completed: libraryPanel.getAttribute("data-i18n-completed") || "Scan completed",
        failed: libraryPanel.getAttribute("data-i18n-failed") || "Scan failed",
        progress:
          libraryPanel.getAttribute("data-i18n-progress") ||
          "Processed {processed} of {discovered}",
        current: libraryPanel.getAttribute("data-i18n-current") || "Current: {path}",
      });
    }
  }

  // Native folder picker for library roots (pywebview desktop shell)
  const browseFolderBtn = document.getElementById("browse-folder");
  const folderPathInput = document.getElementById("folder-path");
  if (browseFolderBtn && folderPathInput) {
    browseFolderBtn.addEventListener("click", () => {
      const unavailableMsg =
        browseFolderBtn.getAttribute("data-i18n-unavailable") ||
        "Native folder picker is not available. Enter the path manually or start orga-drone as a desktop app.";
      browseFolderBtn.disabled = true;
      fetch("/api/desktop/pick-folder", {
        method: "POST",
        headers: { Accept: "application/json" },
      })
        .then(async (resp) => {
          let data = null;
          try {
            data = await resp.json();
          } catch (_) {
            data = null;
          }
          if (resp.status === 503 || (data && data.status === "unavailable")) {
            window.alert(unavailableMsg);
            return;
          }
          if (!resp.ok) {
            window.alert(unavailableMsg);
            return;
          }
          if (!data || data.status === "cancelled") {
            // Leave the current path unchanged.
            return;
          }
          if (data.status === "ok" && data.path) {
            folderPathInput.value = data.path;
            folderPathInput.dispatchEvent(new Event("input", { bubbles: true }));
          }
        })
        .catch(() => {
          window.alert(unavailableMsg);
        })
        .finally(() => {
          browseFolderBtn.disabled = false;
        });
    });
  }

  // Flash / toast polish: dismiss + auto-hide
  document.querySelectorAll(".flash").forEach((el) => {
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "flash-dismiss";
    dismiss.setAttribute("aria-label", "Dismiss");
    dismiss.textContent = "×";
    dismiss.addEventListener("click", () => hideFlash(el));
    el.appendChild(dismiss);
    window.setTimeout(() => hideFlash(el), 6000);
  });

  function hideFlash(el) {
    if (!el || el.classList.contains("is-hiding")) return;
    el.classList.add("is-hiding");
    window.setTimeout(() => el.remove(), 320);
  }

  // Thumbnail loading skeletons
  document.querySelectorAll(".thumb").forEach((thumb) => {
    const media = thumb.querySelector("img, video");
    if (!media) {
      thumb.classList.add("is-loaded");
      return;
    }
    const mark = () => thumb.classList.add("is-loaded");
    if (media.tagName === "IMG") {
      if (media.complete && media.naturalWidth > 0) mark();
      else {
        media.addEventListener("load", mark, { once: true });
        media.addEventListener("error", mark, { once: true });
      }
    } else {
      media.addEventListener("loadeddata", mark, { once: true });
      media.addEventListener("error", mark, { once: true });
      if (media.readyState >= 2) mark();
    }
  });
})();
