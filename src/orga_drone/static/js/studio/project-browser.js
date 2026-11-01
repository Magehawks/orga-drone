const DEFAULT_MESSAGES = {
  createFailed: "Could not create Studio project.",
  openFailed: "Could not open Studio project.",
  deleteFailed: "Could not delete Studio project.",
  deleteConfirm:
    "Delete this Studio project? Clips in this project are removed. Your media files are not deleted.",
  renamePrompt: "New project title",
  titleFailed: "Could not save project title.",
};

const MESSAGE_DATASET_KEYS = {
  createFailed: "createFailed",
  openFailed: "openFailed",
  deleteFailed: "deleteFailed",
  deleteConfirm: "deleteConfirm",
  renamePrompt: "renamePrompt",
  titleFailed: "titleFailed",
};

function messagesFromRoot(root) {
  const data = root && root.dataset ? root.dataset : null;
  if (!data) return { ...DEFAULT_MESSAGES };
  const messages = { ...DEFAULT_MESSAGES };
  for (const [key, datasetKey] of Object.entries(MESSAGE_DATASET_KEYS)) {
    if (typeof data[datasetKey] === "string" && data[datasetKey]) {
      messages[key] = data[datasetKey];
    }
  }
  return messages;
}

async function defaultReadJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export function createProjectBrowser(options = {}) {
  const documentImpl = options.documentImpl || globalThis.document;
  const root = options.root || documentImpl?.getElementById("studio-root") || null;
  const dialog = options.dialog || documentImpl?.getElementById("studio-projects-dialog") || null;
  const openButton =
    options.openButton || documentImpl?.getElementById("studio-projects-open") || null;
  const closeButton =
    options.closeButton || documentImpl?.getElementById("studio-projects-close") || null;
  const messages = {
    ...messagesFromRoot(root),
    ...(options.messages || {}),
  };
  const defaultTitle =
    options.defaultTitle || (root && root.dataset && root.dataset.defaultTitle) || "Your story";
  const fetchImpl = options.fetchImpl || ((...args) => globalThis.fetch(...args));
  const readJson = options.readJson || defaultReadJson;
  const navigate = options.navigate || ((url) => globalThis.location.assign(url));
  const reload = options.reload || (() => globalThis.location.reload());
  const promptImpl = options.prompt || ((message, value) => globalThis.prompt(message, value));
  const confirmImpl = options.confirm || ((message) => globalThis.confirm(message));
  const showError =
    options.showError ||
    ((message) => {
      if (globalThis.alert) globalThis.alert(message);
    });
  const beforeOpen = options.beforeOpen || (() => {});
  const listeners = [];
  let initialized = false;

  function on(target, event, handler) {
    if (!target || typeof target.addEventListener !== "function") return;
    target.addEventListener(event, handler);
    listeners.push({ target, event, handler });
  }

  function cleanTitle(value) {
    const text = String(value || "").trim();
    return text || defaultTitle;
  }

  async function createAndOpenProject(title) {
    const clean = cleanTitle(title);
    const created = await fetchImpl("/api/studio/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ title: clean }),
    });
    const createdBody = await readJson(created);
    if (!created.ok || !createdBody || !createdBody.id) {
      throw new Error((createdBody && createdBody.detail) || messages.createFailed);
    }
    const opened = await fetchImpl(`/api/studio/projects/${createdBody.id}/open`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const openedBody = await readJson(opened);
    if (!opened.ok) {
      throw new Error((openedBody && openedBody.detail) || messages.openFailed);
    }
    navigate("/studio");
  }

  async function openProject(projectId) {
    const res = await fetchImpl(`/api/studio/projects/${projectId}/open`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const body = await readJson(res);
    if (!res.ok) {
      throw new Error((body && body.detail) || messages.openFailed);
    }
    navigate("/studio");
  }

  async function renameProject(projectId, currentTitle) {
    const next = promptImpl(messages.renamePrompt, currentTitle || defaultTitle);
    if (next === null) return;
    const clean = String(next).trim();
    if (!clean) return;
    const res = await fetchImpl(`/api/studio/projects/${projectId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ title: clean }),
    });
    const body = await readJson(res);
    if (!res.ok) {
      throw new Error((body && body.detail) || messages.titleFailed);
    }
    reload();
  }

  async function deleteProject(projectId) {
    if (!confirmImpl(messages.deleteConfirm)) return;
    const res = await fetchImpl(`/api/studio/projects/${projectId}`, {
      method: "DELETE",
      headers: { Accept: "application/json" },
    });
    const body = await readJson(res);
    if (!res.ok) {
      throw new Error((body && body.detail) || messages.deleteFailed);
    }
    navigate("/studio");
  }

  function bindProjectUi(scope) {
    if (!scope || typeof scope.querySelectorAll !== "function") return;
    scope.querySelectorAll("[data-studio-project-create]").forEach((form) => {
      on(form, "submit", (event) => {
        event.preventDefault();
        const input = form.querySelector?.('input[name="title"]');
        const title = input && "value" in input ? String(input.value) : defaultTitle;
        createAndOpenProject(title).catch((err) => showError(err.message || messages.createFailed));
      });
    });
  }

  function handleProjectActionClick(event) {
    const target = event && event.target;
    if (!target || typeof target.closest !== "function") return;
    const openBtn = target.closest("[data-project-open]");
    if (openBtn) {
      event.preventDefault();
      const id = Number(openBtn.getAttribute("data-project-open") || "0");
      if (id) {
        openProject(id).catch((err) => showError(err.message || messages.openFailed));
      }
      return;
    }
    const renameBtn = target.closest("[data-project-rename]");
    if (renameBtn) {
      event.preventDefault();
      const id = Number(renameBtn.getAttribute("data-project-rename") || "0");
      const current = renameBtn.getAttribute("data-project-title") || "";
      if (id) {
        renameProject(id, current).catch((err) => showError(err.message || messages.titleFailed));
      }
      return;
    }
    const deleteBtn = target.closest("[data-project-delete]");
    if (deleteBtn) {
      event.preventDefault();
      const id = Number(deleteBtn.getAttribute("data-project-delete") || "0");
      if (id) {
        deleteProject(id).catch((err) => showError(err.message || messages.deleteFailed));
      }
    }
  }

  function init() {
    if (initialized) return api;
    initialized = true;
    on(root, "click", handleProjectActionClick);
    bindProjectUi(root);
    if (dialog) {
      bindProjectUi(dialog);
      on(dialog, "click", handleProjectActionClick);
    }
    if (openButton && dialog) {
      on(openButton, "click", () => {
        beforeOpen();
        if (typeof dialog.showModal === "function") dialog.showModal();
      });
    }
    if (closeButton && dialog) {
      on(closeButton, "click", () => dialog.close());
    }
    return api;
  }

  function destroy() {
    for (const { target, event, handler } of listeners.splice(0)) {
      if (typeof target.removeEventListener === "function") {
        target.removeEventListener(event, handler);
      }
    }
    initialized = false;
  }

  const api = { init, destroy };

  return api;
}
