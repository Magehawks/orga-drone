/**
 * Persist browse scroll position when opening a media detail link, and restore
 * it when returning to the same browse URL (filters included).
 * Also enables the current-page Studio bulk-add control.
 */
(function () {
  const KEY = "orga-drone:browse-scroll";
  const pathKey = () => window.location.pathname + window.location.search;

  function isDetailLink(href) {
    if (!href) return false;
    try {
      const url = new URL(href, window.location.origin);
      return /^\/media\/\d+$/.test(url.pathname);
    } catch (_) {
      return false;
    }
  }

  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) {
      const data = JSON.parse(raw);
      if (data && data.path === pathKey() && typeof data.y === "number" && data.y > 0) {
        sessionStorage.removeItem(KEY);
        const y = data.y;
        const restore = () => window.scrollTo(0, y);
        restore();
        window.requestAnimationFrame(restore);
        window.setTimeout(restore, 50);
      }
    }
  } catch (_) {
    /* ignore quota / private mode */
  }

  document.addEventListener("click", (event) => {
    const anchor = event.target && event.target.closest
      ? event.target.closest("a[href]")
      : null;
    if (!anchor || !isDetailLink(anchor.getAttribute("href"))) return;
    try {
      sessionStorage.setItem(
        KEY,
        JSON.stringify({
          path: pathKey(),
          y: window.scrollY || window.pageYOffset || 0,
        })
      );
    } catch (_) {
      /* ignore */
    }
  });

  const bulkForm = document.getElementById("browse-bulk-studio");
  const bulkSubmit = document.getElementById("browse-bulk-submit");
  const bulkCount = document.getElementById("browse-bulk-count");
  const projectDialog = document.getElementById("browse-studio-project-dialog");
  const projectList = document.getElementById("browse-studio-project-list");
  const projectEmpty = document.getElementById("browse-studio-project-empty");
  const projectMode = document.getElementById("browse-bulk-project-mode");
  const projectIdInput = document.getElementById("browse-bulk-project-id");
  const projectTitleInput = document.getElementById("browse-bulk-project-title");
  const openStudioInput = document.getElementById("browse-bulk-open-studio");
  const newTitleInput = document.getElementById("browse-studio-new-title");
  if (bulkForm && bulkSubmit) {
    let chooserReady = false;
    const syncBulk = () => {
      const selected = document.querySelectorAll(
        'input.browse-select-input[name="media_ids"][form="browse-bulk-studio"]:checked:not(:disabled)'
      );
      const n = selected.length;
      bulkSubmit.disabled = n === 0;
      if (bulkCount) {
        if (n > 0) {
          bulkCount.hidden = false;
          bulkCount.textContent = String(n);
        } else {
          bulkCount.hidden = true;
          bulkCount.textContent = "";
        }
      }
    };
    const resetChooserFields = () => {
      if (projectMode) projectMode.value = "";
      if (projectIdInput) projectIdInput.value = "";
      if (projectTitleInput) projectTitleInput.value = "";
      if (openStudioInput) openStudioInput.value = "";
      chooserReady = false;
    };
    const renderProjects = (projects) => {
      if (!projectList) return;
      projectList.replaceChildren();
      const rows = Array.isArray(projects) ? projects : [];
      if (projectEmpty) projectEmpty.hidden = rows.length > 0;
      for (const row of rows) {
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "button secondary browse-studio-project-pick";
        btn.textContent = row.title || `Project ${row.id}`;
        btn.dataset.projectId = String(row.id);
        btn.addEventListener("click", () => {
          if (projectMode) projectMode.value = "existing";
          if (projectIdInput) projectIdInput.value = String(row.id);
          if (openStudioInput) openStudioInput.value = "1";
          chooserReady = true;
          if (typeof projectDialog?.close === "function") projectDialog.close();
          bulkForm.requestSubmit();
        });
        li.appendChild(btn);
        projectList.appendChild(li);
      }
    };
    const openChooser = async () => {
      if (!projectDialog || typeof projectDialog.showModal !== "function") {
        return false;
      }
      try {
        const res = await fetch("/api/studio/projects", {
          headers: { Accept: "application/json" },
        });
        if (res.ok) {
          const data = await res.json();
          renderProjects(data.projects || []);
        } else {
          renderProjects([]);
        }
      } catch {
        renderProjects([]);
      }
      projectDialog.showModal();
      return true;
    };
    document.addEventListener("change", (event) => {
      const t = event.target;
      if (
        t &&
        t.classList &&
        t.classList.contains("browse-select-input") &&
        t.getAttribute("form") === "browse-bulk-studio"
      ) {
        syncBulk();
      }
    });
    bulkForm.addEventListener("submit", (event) => {
      const n = document.querySelectorAll(
        'input.browse-select-input[name="media_ids"][form="browse-bulk-studio"]:checked:not(:disabled)'
      ).length;
      if (n === 0) {
        event.preventDefault();
        syncBulk();
        return;
      }
      if (chooserReady) {
        return;
      }
      event.preventDefault();
      void openChooser();
    });
    document.getElementById("browse-studio-new")?.addEventListener("click", () => {
      if (projectMode) projectMode.value = "new";
      if (projectTitleInput) {
        projectTitleInput.value = (newTitleInput && newTitleInput.value.trim()) || "Your story";
      }
      if (openStudioInput) openStudioInput.value = "1";
      chooserReady = true;
      if (typeof projectDialog?.close === "function") projectDialog.close();
      bulkForm.requestSubmit();
    });
    document.getElementById("browse-studio-cancel")?.addEventListener("click", () => {
      resetChooserFields();
      if (typeof projectDialog?.close === "function") projectDialog.close();
    });
    projectDialog?.addEventListener("cancel", () => {
      resetChooserFields();
    });
    syncBulk();
    // After a missing/invalid project redirect, selection is restored via
    // checked checkboxes; reopen the chooser so the user can retry.
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get("msg") === "studio_choose_project") {
        const n = document.querySelectorAll(
          'input.browse-select-input[name="media_ids"][form="browse-bulk-studio"]:checked:not(:disabled)'
        ).length;
        if (n > 0) {
          void openChooser();
        }
      }
    } catch {
      /* ignore */
    }
  }

  const FILTER_KEY = "orga-drone:browse-filters";
  const FILTER_NAMES = ["drone", "kind", "source", "gps", "sessions", "flows", "favorite", "q", "date_from", "date_to", "ask", "tl"];
  try {
    if (window.location.pathname === "/browse" || window.location.pathname.startsWith("/media")) {
      const params = new URLSearchParams(window.location.search);
      const active = FILTER_NAMES.some((name) => params.get(name));
      if (active) sessionStorage.setItem(FILTER_KEY, window.location.pathname + window.location.search);
      else if (window.location.pathname === "/browse") sessionStorage.removeItem(FILTER_KEY);
    }
  } catch (_) {
    /* ignore quota / private mode */
  }
})();
