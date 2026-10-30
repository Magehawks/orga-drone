(() => {
  const section = document.getElementById("settings-luts");
  if (!section) return;

  const listEl = document.getElementById("settings-lut-list");
  const statusEl = document.getElementById("settings-lut-status");
  const addBtn = document.getElementById("settings-lut-add");
  const openBtn = document.getElementById("settings-lut-open-folder");
  const fileInput = document.getElementById("settings-lut-file-input");

  let catalog = Array.isArray(window.__LUT_CATALOG__) ? window.__LUT_CATALOG__ : [];

  function t(key, fallback) {
    return section.dataset[key] || fallback;
  }

  function setStatus(message, { alert = false } = {}) {
    if (!statusEl) return;
    if (!message) {
      statusEl.hidden = true;
      statusEl.textContent = "";
      statusEl.removeAttribute("role");
      return;
    }
    statusEl.hidden = false;
    statusEl.textContent = message;
    statusEl.setAttribute("role", alert ? "alert" : "status");
  }

  async function readJson(res) {
    try {
      return await res.json();
    } catch (_) {
      return null;
    }
  }

  function formatUsage(entry) {
    const usage = entry.usage || {};
    const clips = Number(usage.clip_count) || 0;
    if (clips <= 0) return t("lutUnused", "Not used");
    return t("lutUsed", "Used in {n} clips").replace("{n}", String(clips));
  }

  function formatAdded(entry) {
    const raw = String(entry.imported_at || "");
    const date = raw.slice(0, 10) || raw;
    return t("lutAdded", "Added {date}").replace("{date}", date);
  }

  function render() {
    if (!listEl) return;
    listEl.innerHTML = "";
    if (!catalog.length) {
      const empty = document.createElement("li");
      empty.className = "hint";
      empty.textContent = t(
        "lutEmpty",
        "Color files you already have go here (for example from your drone maker). Orga Drone includes none. Your original file stays unchanged; the app keeps a copy."
      );
      listEl.appendChild(empty);
      return;
    }
    catalog.forEach((entry) => {
      const li = document.createElement("li");
      li.className = "settings-lut-row";
      li.dataset.assetName = entry.asset_name;

      const title = document.createElement("div");
      title.className = "settings-lut-title";
      title.textContent = entry.display_name || entry.asset_name;

      const meta = document.createElement("p");
      meta.className = "hint";
      meta.textContent = `${formatAdded(entry)} · ${formatUsage(entry)}`;

      li.appendChild(title);
      li.appendChild(meta);

      if (entry.file_present === false) {
        const missing = document.createElement("p");
        missing.className = "hint";
        missing.setAttribute("role", "alert");
        missing.textContent = `${t("lutFileMissing", "File missing")}. ${t(
          "lutFileMissingHelp",
          "Add the original .cube again to restore it, or stop using it in your clips first."
        )}`;
        li.appendChild(missing);
      }

      const actions = document.createElement("div");
      actions.className = "settings-lut-actions";

      const renameBtn = document.createElement("button");
      renameBtn.type = "button";
      renameBtn.className = "button ghost";
      renameBtn.textContent = t("lutRename", "Rename");
      renameBtn.addEventListener("click", () => beginRename(li, entry));

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "button ghost";
      removeBtn.textContent = t("lutRemove", "Remove from library");
      removeBtn.addEventListener("click", () => removeEntry(li, entry));

      actions.appendChild(renameBtn);
      actions.appendChild(removeBtn);
      li.appendChild(actions);

      const feedback = document.createElement("p");
      feedback.className = "hint settings-lut-feedback";
      feedback.hidden = true;
      li.appendChild(feedback);

      listEl.appendChild(li);
    });
  }

  function beginRename(row, entry) {
    const feedback = row.querySelector(".settings-lut-feedback");
    if (feedback) {
      feedback.hidden = true;
      feedback.textContent = "";
    }
    const title = row.querySelector(".settings-lut-title");
    if (!title) return;
    const input = document.createElement("input");
    input.type = "text";
    input.className = "settings-lut-rename";
    input.value = entry.display_name || "";
    input.maxLength = 80;
    input.setAttribute("aria-label", t("lutRename", "Rename"));
    title.replaceWith(input);
    input.focus();
    input.select();

    let finished = false;
    const finish = async (save) => {
      if (finished) return;
      finished = true;
      if (save) {
        const name = input.value.trim();
        try {
          const res = await fetch(`/api/luts/${encodeURIComponent(entry.asset_name)}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ display_name: name }),
          });
          const body = await readJson(res);
          if (!res.ok || !body || !body.ok) {
            throw new Error((body && body.detail) || t("lutRenameFailed", "Could not rename that color file."));
          }
          await reload();
          setStatus("");
          return;
        } catch (err) {
          finished = false;
          if (feedback) {
            feedback.hidden = false;
            feedback.setAttribute("role", "alert");
            feedback.textContent = (err && err.message) || t("lutRenameFailed", "Could not rename that color file.");
          }
          return;
        }
      }
      render();
    };

    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        finish(true);
      } else if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
    });
    input.addEventListener("blur", () => finish(true));
  }

  async function removeEntry(row, entry) {
    const feedback = row.querySelector(".settings-lut-feedback");
    const confirmMsg = t(
      "lutDeleteConfirm",
      "Remove {name} from the library? The copy inside Orga Drone is deleted. Your original .cube stays where it is."
    ).replace("{name}", entry.display_name || entry.asset_name);
    if (!window.confirm(confirmMsg)) return;
    try {
      const res = await fetch(`/api/luts/${encodeURIComponent(entry.asset_name)}`, {
        method: "DELETE",
        headers: { Accept: "application/json" },
      });
      const body = await readJson(res);
      if (res.status === 409 && body && body.in_use) {
        const names = (body.project_titles || []).join(", ");
        const msg = t(
          "lutInUse",
          "Cannot remove: used in {n} clips in {m} projects ({names}). Choose Don’t use there first."
        )
          .replace("{n}", String(body.clip_count || 0))
          .replace("{m}", String(body.project_count || 0))
          .replace("{names}", names || "—");
        if (feedback) {
          feedback.hidden = false;
          feedback.setAttribute("role", "alert");
          feedback.textContent = msg;
        }
        return;
      }
      if (!res.ok || !body || !body.ok) {
        throw new Error((body && body.detail) || t("lutDeleteFailed", "Could not remove that color file."));
      }
      await reload();
      setStatus("");
    } catch (err) {
      if (feedback) {
        feedback.hidden = false;
        feedback.setAttribute("role", "alert");
        feedback.textContent =
          (err && err.message) || t("lutDeleteFailed", "Could not remove that color file.");
      }
    }
  }

  async function reload() {
    const res = await fetch("/api/luts", { headers: { Accept: "application/json" } });
    const body = await readJson(res);
    if (res.ok && body && Array.isArray(body.luts)) {
      catalog = body.luts;
    }
    render();
  }

  async function importPath(path) {
    const res = await fetch("/api/luts", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ path }),
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || t("lutImportFailed", "Could not import that .cube LUT."));
    }
    return body;
  }

  async function importFile(file) {
    const form = new FormData();
    form.append("file", file, file.name || "look.cube");
    const res = await fetch("/api/luts", {
      method: "POST",
      headers: { Accept: "application/json" },
      body: form,
    });
    const body = await readJson(res);
    if (!res.ok || !body || !body.ok) {
      throw new Error((body && body.detail) || t("lutImportFailed", "Could not import that .cube LUT."));
    }
    return body;
  }

  async function pickAndImport() {
    try {
      const res = await fetch("/api/desktop/pick-open-file", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ file_types: ["3D LUT (*.cube)", "All files (*.*)"] }),
      });
      const body = await readJson(res);
      if (res.status !== 503 && body && body.path) {
        const imported = await importPath(body.path);
        await reload();
        afterImport(imported);
        return;
      }
    } catch (_) {
      /* fall through to file input */
    }
    if (!fileInput) return;
    fileInput.value = "";
    fileInput.click();
  }

  function afterImport(body) {
    const name = body.display_name || body.asset_name;
    if (body.already_present) {
      setStatus(t("lutAlready", 'This file is already in your library as "{name}".').replace("{name}", name));
    } else if (body.restored) {
      setStatus(
        t("lutRestored", 'The color file was restored in your library as "{name}".').replace("{name}", name)
      );
    } else {
      setStatus("");
    }
    const safe =
      window.CSS && typeof CSS.escape === "function"
        ? CSS.escape(body.asset_name)
        : String(body.asset_name).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    const row = listEl && listEl.querySelector(`[data-asset-name="${safe}"]`);
    if (row) {
      row.classList.add("is-highlight");
      row.scrollIntoView({ block: "nearest" });
      setTimeout(() => row.classList.remove("is-highlight"), 1600);
    }
  }

  addBtn?.addEventListener("click", () => {
    pickAndImport().catch((err) => {
      setStatus((err && err.message) || t("lutImportFailed", "Could not import that .cube LUT."), {
        alert: true,
      });
    });
  });

  fileInput?.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    importFile(file)
      .then(async (body) => {
        await reload();
        afterImport(body);
      })
      .catch((err) => {
        setStatus((err && err.message) || t("lutImportFailed", "Could not import that .cube LUT."), {
          alert: true,
        });
      });
  });

  openBtn?.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/luts/open-folder", {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const body = await readJson(res);
      if (!res.ok || !body || !body.ok) {
        setStatus((body && body.detail) || "Unavailable", { alert: true });
      }
    } catch (err) {
      setStatus((err && err.message) || "Unavailable", { alert: true });
    }
  });

  render();
})();
