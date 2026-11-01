import assert from "node:assert/strict";
import test from "node:test";

import { createProjectBrowser } from "../../src/orga_drone/static/js/studio/project-browser.js";

function jsonResponse(data, { status = 200, ok = true } = {}) {
  return { ok, status, json: async () => data };
}

class FakeElement {
  constructor({ id = "", dataset = {}, attributes = {} } = {}) {
    this.id = id;
    this.dataset = dataset;
    this.attributes = { ...attributes };
    this.listeners = new Map();
    this.queryMap = {};
    this.queryAllMap = {};
    this.value = "";
    this.open = false;
    this.closed = false;
  }

  addEventListener(event, handler) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event).add(handler);
  }

  removeEventListener(event, handler) {
    this.listeners.get(event)?.delete(handler);
  }

  querySelector(selector) {
    return this.queryMap[selector] || null;
  }

  querySelectorAll(selector) {
    return this.queryAllMap[selector] || [];
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name)
      ? String(this.attributes[name])
      : null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  closest(selector) {
    if (!selector.startsWith("[") || !selector.endsWith("]")) return null;
    const name = selector.slice(1, -1);
    return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this : null;
  }

  showModal() {
    this.open = true;
  }

  close() {
    this.open = false;
    this.closed = true;
  }

  async emit(event, extra = {}) {
    const payload = {
      target: extra.target || this,
      defaultPrevented: false,
      preventDefault() {
        this.defaultPrevented = true;
      },
      ...extra,
    };
    for (const handler of [...(this.listeners.get(event) || [])]) {
      await handler(payload);
    }
    return payload;
  }

  get listenerCount() {
    let total = 0;
    for (const handlers of this.listeners.values()) total += handlers.size;
    return total;
  }
}

const flush = async () => {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
};

const ROOT_MESSAGES = {
  createFailed: "Create failed",
  openFailed: "Open failed",
  deleteFailed: "Delete failed",
  deleteConfirm: "Delete this project?",
  renamePrompt: "Rename project",
  titleFailed: "Title failed",
};

function makeHarness(handler) {
  const root = new FakeElement({ dataset: ROOT_MESSAGES });
  const dialog = new FakeElement({ id: "studio-projects-dialog" });
  const openButton = new FakeElement({ id: "studio-projects-open" });
  const closeButton = new FakeElement({ id: "studio-projects-close" });
  const form = new FakeElement({ id: "create-form" });
  const input = new FakeElement({ id: "title" });
  input.value = "New project";
  form.queryMap['input[name="title"]'] = input;
  root.queryAllMap["[data-studio-project-create]"] = [form];
  const elements = {
    "studio-root": root,
    "studio-projects-dialog": dialog,
    "studio-projects-open": openButton,
    "studio-projects-close": closeButton,
  };
  const calls = [];
  const navigations = [];
  const reloads = [];
  const errors = [];
  let beforeOpen = 0;
  const controls = {
    promptResult: "Renamed project",
    confirmResult: true,
  };
  const ui = createProjectBrowser({
    root,
    dialog,
    openButton,
    closeButton,
    documentImpl: { getElementById: (id) => elements[id] || null },
    defaultTitle: "Fallback title",
    fetchImpl: async (url, init = {}) => {
      calls.push({ url, init });
      return handler(url, init);
    },
    navigate: (url) => navigations.push(url),
    reload: () => reloads.push(true),
    prompt: () => controls.promptResult,
    confirm: () => controls.confirmResult,
    showError: (message) => errors.push(message),
    beforeOpen: () => {
      beforeOpen += 1;
    },
  });
  ui.init();
  return {
    ui,
    root,
    dialog,
    openButton,
    closeButton,
    form,
    input,
    calls,
    navigations,
    reloads,
    errors,
    controls,
    get beforeOpen() {
      return beforeOpen;
    },
  };
}

function actionTarget(attributes) {
  return new FakeElement({ attributes });
}

test("binds once, opens the dialog, and removes listeners on destroy", async () => {
  const h = makeHarness(async () => jsonResponse({ ok: true }));
  assert.equal(h.root.listenerCount, 1);
  assert.equal(h.dialog.listenerCount, 1);
  assert.equal(h.openButton.listenerCount, 1);
  assert.equal(h.closeButton.listenerCount, 1);
  assert.equal(h.form.listenerCount, 1);
  h.ui.init();
  assert.equal(h.root.listenerCount, 1);
  assert.equal(h.openButton.listenerCount, 1);

  await h.openButton.emit("click");
  assert.equal(h.beforeOpen, 1);
  assert.equal(h.dialog.open, true);

  await h.closeButton.emit("click");
  assert.equal(h.dialog.closed, true);

  h.ui.destroy();
  assert.equal(h.root.listenerCount, 0);
  assert.equal(h.dialog.listenerCount, 0);
  assert.equal(h.openButton.listenerCount, 0);
  assert.equal(h.closeButton.listenerCount, 0);
  assert.equal(h.form.listenerCount, 0);
});

test("creates and opens a project from the form", async () => {
  const h = makeHarness(async (url) => {
    if (url === "/api/studio/projects") return jsonResponse({ ok: true, id: 7 });
    if (url === "/api/studio/projects/7/open") return jsonResponse({ ok: true });
    throw new Error(`Unexpected URL ${url}`);
  });

  await h.form.emit("submit");
  await flush();

  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[0].url, "/api/studio/projects");
  assert.deepEqual(JSON.parse(h.calls[0].init.body), { title: "New project" });
  assert.equal(h.calls[1].url, "/api/studio/projects/7/open");
  assert.deepEqual(h.navigations, ["/studio"]);
  assert.deepEqual(h.errors, []);
});

test("uses the fallback title for an empty create form and reports failures", async () => {
  const h = makeHarness(async (url) => {
    if (url === "/api/studio/projects") {
      return jsonResponse({ detail: "create exploded" }, { status: 500, ok: false });
    }
    throw new Error(`Unexpected URL ${url}`);
  });
  h.input.value = "   ";

  await h.form.emit("submit");
  await flush();

  assert.deepEqual(JSON.parse(h.calls[0].init.body), { title: "Fallback title" });
  assert.deepEqual(h.errors, ["create exploded"]);
  assert.deepEqual(h.navigations, []);
});

test("opens, renames, and deletes a project", async () => {
  const h = makeHarness(async (url, init) => {
    if (url === "/api/studio/projects/7/open") return jsonResponse({ ok: true });
    if (url === "/api/studio/projects/7" && init.method === "PATCH") {
      return jsonResponse({ ok: true });
    }
    if (url === "/api/studio/projects/7" && init.method === "DELETE") {
      return jsonResponse({ ok: true });
    }
    throw new Error(`Unexpected URL ${url}`);
  });

  await h.root.emit("click", {
    target: actionTarget({ "data-project-open": "7" }),
  });
  await flush();
  assert.equal(h.calls[0].url, "/api/studio/projects/7/open");
  assert.deepEqual(h.navigations, ["/studio"]);

  h.calls.length = 0;
  h.controls.promptResult = "Renamed project";
  await h.root.emit("click", {
    target: actionTarget({
      "data-project-rename": "7",
      "data-project-title": "Old project",
    }),
  });
  await flush();
  assert.equal(h.calls[0].init.method, "PATCH");
  assert.deepEqual(JSON.parse(h.calls[0].init.body), { title: "Renamed project" });
  assert.equal(h.reloads.length, 1);

  h.calls.length = 0;
  h.controls.confirmResult = true;
  await h.root.emit("click", {
    target: actionTarget({ "data-project-delete": "7" }),
  });
  await flush();
  assert.equal(h.calls[0].init.method, "DELETE");
  assert.deepEqual(h.navigations, ["/studio", "/studio"]);
});

test("does not send rename or delete requests when cancelled", async () => {
  const h = makeHarness(async () => jsonResponse({ ok: true }));

  h.controls.promptResult = null;
  await h.root.emit("click", {
    target: actionTarget({
      "data-project-rename": "7",
      "data-project-title": "Old project",
    }),
  });
  await flush();
  assert.equal(h.calls.length, 0);

  h.controls.confirmResult = false;
  await h.root.emit("click", {
    target: actionTarget({ "data-project-delete": "7" }),
  });
  await flush();
  assert.equal(h.calls.length, 0);
});

test("reports open, rename, and delete API errors", async () => {
  const h = makeHarness(async (url, init) => {
    if (url === "/api/studio/projects/7/open") {
      return jsonResponse({ detail: "open exploded" }, { status: 500, ok: false });
    }
    if (url === "/api/studio/projects/7" && init.method === "PATCH") {
      return jsonResponse({ detail: "rename exploded" }, { status: 500, ok: false });
    }
    if (url === "/api/studio/projects/7" && init.method === "DELETE") {
      return jsonResponse({ detail: "delete exploded" }, { status: 500, ok: false });
    }
    throw new Error(`Unexpected URL ${url}`);
  });

  await h.root.emit("click", {
    target: actionTarget({ "data-project-open": "7" }),
  });
  await flush();
  await h.root.emit("click", {
    target: actionTarget({
      "data-project-rename": "7",
      "data-project-title": "Old project",
    }),
  });
  await flush();
  await h.root.emit("click", {
    target: actionTarget({ "data-project-delete": "7" }),
  });
  await flush();

  assert.deepEqual(h.errors, ["open exploded", "rename exploded", "delete exploded"]);
  assert.deepEqual(h.navigations, []);
  assert.equal(h.reloads.length, 0);
});

test("waits for asynchronous project responses before navigating", async () => {
  let resolveOpen;
  const openPromise = new Promise((resolve) => {
    resolveOpen = resolve;
  });
  const h = makeHarness(async (url) => {
    if (url === "/api/studio/projects/7/open") {
      await openPromise;
      return jsonResponse({ ok: true });
    }
    throw new Error(`Unexpected URL ${url}`);
  });

  await h.root.emit("click", {
    target: actionTarget({ "data-project-open": "7" }),
  });
  assert.deepEqual(h.navigations, []);
  resolveOpen();
  await flush();
  assert.deepEqual(h.navigations, ["/studio"]);
});
