import assert from "node:assert/strict";
import test from "node:test";

import {
  createExportUi,
  exportPhaseLabel,
  formatExportDuration,
  suggestionForHeight,
} from "../../src/orga_drone/static/js/studio/export.js";

const ELEMENT_IDS = [
  "studio-export-dialog",
  "studio-export-open",
  "studio-export-open-file",
  "studio-export-reveal-file",
  "studio-export-success-dismiss",
  "studio-export-resolution",
  "studio-export-quality",
  "studio-export-filename",
  "studio-export-status",
  "studio-export-hint",
  "studio-export-run",
  "studio-export-cancel",
  "studio-export-progress",
  "studio-export-progress-bar",
  "studio-export-progressbar",
  "studio-export-progress-label",
  "studio-export-progress-meta",
  "studio-export-success",
  "studio-export-success-title",
  "studio-export-success-path",
  "studio-export-success-error",
];

const ROOT_MESSAGES = {
  exportFailed: "Export failed.",
  exportCancelled: "Export cancelled.",
  exportCancelling: "Cancelling export",
  exportNoResolution: "No resolution",
  exportRunning: "Running",
  exportDone: "Done",
  exportPreparing: "Preparing",
  exportClip: "Clip {current} of {total}",
  exportCombining: "Combining",
  exportMixing: "Mixing",
  exportUnavailable: "Unavailable",
  exportRunningHint: "Running",
  exportElapsed: "Elapsed {time}",
  exportDoneIn: "Done in {time}",
  exportSuccess: "Exported {filename}.",
  exportFileMissing: "Missing",
  exportOpenUnavailable: "Open unavailable",
  exportRevealUnavailable: "Reveal unavailable",
  recommendedLabel: "recommended",
};

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(value) {
    this.values.add(value);
  }

  remove(value) {
    this.values.delete(value);
  }

  toggle(value, force) {
    const shouldAdd = force === undefined ? !this.values.has(value) : Boolean(force);
    if (shouldAdd) this.values.add(value);
    else this.values.delete(value);
    return shouldAdd;
  }

  contains(value) {
    return this.values.has(value);
  }
}

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.hidden = false;
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.innerHTML = "";
    this.children = [];
    this.style = {};
    this.attributes = {};
    this.classList = new FakeClassList();
    this.listeners = new Map();
    this.title = "";
    this.open = false;
    this.closed = false;
    this.selected = false;
    this.dataset = {};
    this.parentNode = null;
  }

  addEventListener(event, handler) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event).add(handler);
  }

  removeEventListener(event, handler) {
    this.listeners.get(event)?.delete(handler);
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    if (child.selected) this.value = child.value;
    return child;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes[name];
  }

  showModal() {
    this.open = true;
  }

  close() {
    this.open = false;
    this.closed = true;
  }

  async emit(event, extra = {}) {
    if (this.disabled) return;
    for (const handler of [...(this.listeners.get(event) || [])]) {
      await handler({ preventDefault() {}, ...extra });
    }
  }

  get listenerCount() {
    let total = 0;
    for (const handlers of this.listeners.values()) total += handlers.size;
    return total;
  }
}

function jsonResponse(data, { status = 200, ok = true } = {}) {
  return { ok, status, json: async () => data };
}

function makeScheduler() {
  const timeouts = new Map();
  const intervals = new Map();
  let nextId = 1;
  return {
    setTimeout(fn, ms) {
      const id = nextId++;
      timeouts.set(id, { fn, ms });
      return id;
    },
    clearTimeout(id) {
      timeouts.delete(id);
    },
    setInterval(fn, ms) {
      const id = nextId++;
      intervals.set(id, { fn, ms });
      return id;
    },
    clearInterval(id) {
      intervals.delete(id);
    },
    async runTimeouts(ms) {
      const matches = [...timeouts.entries()].filter(([, item]) => item.ms === ms);
      for (const [id, item] of matches) {
        timeouts.delete(id);
        await item.fn();
      }
    },
    get timeoutCount() {
      return timeouts.size;
    },
    get intervalCount() {
      return intervals.size;
    },
  };
}

function makeHarness(handler) {
  const elements = {};
  for (const id of ELEMENT_IDS) elements[id] = new FakeElement(id);
  const root = new FakeElement("studio-root");
  root.dataset = { ...ROOT_MESSAGES };
  const documentImpl = {
    getElementById: (id) => elements[id] || null,
    createElement: (tag) => new FakeElement(tag),
  };
  const scheduler = makeScheduler();
  const calls = [];
  let clock = 1000;
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init });
    return handler(url, init);
  };
  const ui = createExportUi({
    projectId: 42,
    root,
    documentImpl,
    fetchImpl,
    now: () => clock,
    setTimeoutImpl: scheduler.setTimeout,
    clearTimeoutImpl: scheduler.clearTimeout,
    setIntervalImpl: scheduler.setInterval,
    clearIntervalImpl: scheduler.clearInterval,
  });
  return {
    ui,
    elements,
    scheduler,
    calls,
    setClock(value) {
      clock = value;
    },
  };
}

const flush = async () => {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
};

const OPTIONS = {
  ok: true,
  options: [
    {
      height: 1080,
      label: "1080p",
      recommended: true,
      suggested_filename: "story_1080p.mp4",
    },
    {
      height: 720,
      label: "720p",
      suggested_filename: "story_720p.mp4",
    },
  ],
  default_height: 1080,
  default_quality: "high",
  default_directory: "C:\\Videos",
};

function exportHandler({ jobResponses } = {}) {
  let jobIndex = 0;
  return async (url) => {
    if (url.startsWith("/api/studio/export/options")) return jsonResponse(OPTIONS);
    if (url === "/api/desktop/pick-save-file") {
      return jsonResponse({ status: "ok", path: "C:\\Out\\story.mp4" });
    }
    if (url === "/api/studio/export") {
      return jsonResponse({ ok: true, job_id: "job-1" });
    }
    if (url === "/api/studio/export/jobs/job-1/cancel") {
      return jsonResponse({ ok: false }, { status: 500, ok: false });
    }
    if (url === "/api/studio/export/jobs/job-1") {
      const response = jobResponses[Math.min(jobIndex, jobResponses.length - 1)];
      jobIndex += 1;
      return jsonResponse(response);
    }
    if (url === "/api/studio/export/open") {
      return jsonResponse({}, { status: 503, ok: false });
    }
    throw new Error(`Unexpected URL: ${url}`);
  };
}

test("formats export durations and phase labels", () => {
  assert.equal(formatExportDuration(0), "0:00");
  assert.equal(formatExportDuration(59.6), "1:00");
  assert.equal(formatExportDuration(3661), "1:01:01");
  const messages = {
    preparing: "Preparing",
    combining: "Combining",
    mixing: "Mixing",
    done: "Done",
    clip: "Clip {current} of {total}",
    running: "Running",
  };
  assert.equal(exportPhaseLabel({ phase: "preparing" }, messages), "Preparing");
  assert.equal(
    exportPhaseLabel(
      { phase: "rendering", clip_index: 1, clip_total: 3, current_label: "a.mp4" },
      messages
    ),
    "Clip 1 of 3 · a.mp4"
  );
  assert.equal(suggestionForHeight(OPTIONS, 720), "story_720p.mp4");
  assert.equal(suggestionForHeight(null, 720), "export.mp4");
});

test("binds and removes export listeners", () => {
  const { ui, elements } = makeHarness(exportHandler());
  assert.equal(elements["studio-export-open"].listenerCount, 1);
  assert.equal(elements["studio-export-open-file"].listenerCount, 1);
  assert.equal(elements["studio-export-reveal-file"].listenerCount, 1);
  assert.equal(elements["studio-export-success-dismiss"].listenerCount, 1);
  assert.equal(elements["studio-export-resolution"].listenerCount, 1);
  assert.equal(elements["studio-export-filename"].listenerCount, 1);
  assert.equal(elements["studio-export-run"].listenerCount, 1);
  assert.equal(elements["studio-export-cancel"].listenerCount, 1);
  assert.equal(elements["studio-export-dialog"].listenerCount, 1);
  ui.destroy();
  assert.equal(elements["studio-export-open"].listenerCount, 0);
  assert.equal(elements["studio-export-run"].listenerCount, 0);
  assert.equal(elements["studio-export-cancel"].listenerCount, 0);
  assert.equal(elements["studio-export-dialog"].listenerCount, 0);
});

test("opens the dialog, loads options and resets the filename", async () => {
  const { ui, elements, calls } = makeHarness(exportHandler());
  await ui.openExportDialog();
  await flush();

  assert.equal(calls[0].url, "/api/studio/export/options?project_id=42");
  assert.equal(elements["studio-export-dialog"].open, true);
  assert.equal(elements["studio-export-resolution"].children.length, 2);
  assert.equal(elements["studio-export-resolution"].children[0].value, "1080");
  assert.equal(elements["studio-export-resolution"].children[0].selected, true);
  assert.equal(elements["studio-export-resolution"].children[0].textContent, "1080p (recommended)");
  assert.equal(elements["studio-export-filename"].value, "story_1080p.mp4");
  assert.equal(elements["studio-export-run"].disabled, false);
  assert.equal(elements["studio-export-hint"].textContent, "story_1080p.mp4 → C:\\Videos");
  ui.destroy();
});

test("starts one export, shows progress and completes", async () => {
  const handler = exportHandler({
    jobResponses: [
      {
        ok: true,
        state: "running",
        phase: "rendering",
        percent: 25,
        clip_index: 1,
        clip_total: 2,
        elapsed_s: 1,
      },
      {
        ok: true,
        state: "completed",
        percent: 100,
        filename: "story.mp4",
        output_path: "C:\\Out\\story.mp4",
        open_available: true,
        reveal_available: true,
      },
    ],
  });
  const { ui, elements, scheduler, calls } = makeHarness(handler);
  await ui.openExportDialog();
  await flush();

  await elements["studio-export-run"].emit("click");
  await elements["studio-export-run"].emit("click");
  await flush();

  const pickCalls = calls.filter((call) => call.url === "/api/desktop/pick-save-file");
  const startCalls = calls.filter((call) => call.url === "/api/studio/export");
  assert.equal(pickCalls.length, 1);
  assert.equal(startCalls.length, 1);
  const startedBody = JSON.parse(startCalls[0].init.body);
  assert.equal(startedBody.height, 1080);
  assert.equal(startedBody.quality, "high");
  assert.equal(startedBody.output_path, "C:\\Out\\story.mp4");
  assert.equal(startedBody.project_id, 42);

  assert.equal(elements["studio-export-progress"].hidden, false);
  assert.equal(elements["studio-export-progress-bar"].style.width, "25%");
  assert.equal(elements["studio-export-progress-label"].textContent, "Clip 1 of 2 (25%)");
  assert.equal(elements["studio-export-progress-meta"].textContent, "Elapsed 0:00");
  assert.equal(scheduler.timeoutCount, 1);
  assert.equal(scheduler.intervalCount, 1);

  await scheduler.runTimeouts(400);
  await flush();

  assert.equal(elements["studio-export-dialog"].closed, true);
  assert.equal(elements["studio-export-success"].hidden, false);
  assert.equal(elements["studio-export-success-title"].textContent, "Exported story.mp4.");
  assert.equal(elements["studio-export-success-path"].textContent, "C:\\Out\\story.mp4");
  assert.equal(scheduler.timeoutCount, 0);
  assert.equal(scheduler.intervalCount, 0);
  ui.destroy();
});

test("shows failed jobs and stops timers", async () => {
  const handler = exportHandler({
    jobResponses: [
      {
        ok: true,
        state: "failed",
        percent: 40,
        error: "encode failed",
      },
    ],
  });
  const { ui, elements, scheduler } = makeHarness(handler);
  await ui.openExportDialog();
  await flush();
  await elements["studio-export-run"].emit("click");
  await flush();

  assert.equal(elements["studio-export-status"].textContent, "encode failed");
  assert.equal(elements["studio-export-status"].classList.contains("is-error"), true);
  assert.equal(scheduler.timeoutCount, 0);
  assert.equal(scheduler.intervalCount, 0);
  ui.destroy();
});

test("reports open and reveal failures", async () => {
  const { ui, elements } = makeHarness(exportHandler());
  await ui.requestExportAction("open");
  assert.equal(elements["studio-export-success-error"].hidden, false);
  assert.equal(elements["studio-export-success-error"].textContent, "Open unavailable");
  ui.destroy();
});

test("can retry a failed cancel and cleans timers on destroy", async () => {
  const handler = exportHandler({
    jobResponses: [
      {
        ok: true,
        state: "running",
        phase: "rendering",
        percent: 10,
        clip_index: 1,
        clip_total: 2,
      },
      {
        ok: true,
        state: "running",
        phase: "rendering",
        percent: 20,
        clip_index: 1,
        clip_total: 2,
      },
    ],
  });
  const { ui, elements, scheduler, calls } = makeHarness(handler);
  await ui.openExportDialog();
  await flush();
  await elements["studio-export-run"].emit("click");
  await flush();

  await ui.requestExportCancel();
  await flush();
  assert.equal(elements["studio-export-cancel"].disabled, false);
  assert.equal(calls.filter((call) => call.url.endsWith("/cancel")).length, 1);

  await ui.requestExportCancel();
  await flush();
  assert.equal(calls.filter((call) => call.url.endsWith("/cancel")).length, 2);

  ui.destroy();
  assert.equal(scheduler.timeoutCount, 0);
  assert.equal(scheduler.intervalCount, 0);
});
