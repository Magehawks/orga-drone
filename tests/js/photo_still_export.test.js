import test from "node:test";
import assert from "node:assert/strict";
import {
  createPhotoStillExportUi,
  projectAllowsPhotoStillExport,
} from "../../src/orga_drone/static/js/studio/photo-still-export.js";

test("projectAllowsPhotoStillExport is true only for exactly one photo", () => {
  assert.equal(projectAllowsPhotoStillExport([]), false);
  assert.equal(projectAllowsPhotoStillExport([{ kind: "photo" }]), true);
  assert.equal(projectAllowsPhotoStillExport([{ dataset: { kind: "photo" } }]), true);
  assert.equal(
    projectAllowsPhotoStillExport([{ kind: "photo" }, { kind: "photo" }]),
    false
  );
  assert.equal(
    projectAllowsPhotoStillExport([{ kind: "photo" }, { kind: "video" }]),
    false
  );
  assert.equal(projectAllowsPhotoStillExport([{ kind: "video" }]), false);
  assert.equal(projectAllowsPhotoStillExport([{ kind: "title" }]), false);
});

class FakeEl {
  constructor({ id = "", hidden = false } = {}) {
    this.id = id;
    this.hidden = hidden;
    this.disabled = false;
    this.value = "jpeg";
    this.dataset = {};
    this.attrs = {};
    this.listeners = new Map();
    this.textContent = "";
    this.classList = {
      values: new Set(),
      toggle(name, on) {
        if (on) this.values.add(name);
        else this.values.delete(name);
      },
    };
  }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }
  getAttribute(name) {
    return this.attrs[name];
  }
  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(fn);
  }
  click() {
    for (const fn of this.listeners.get("click") || []) fn({ stopPropagation() {} });
  }
  contains(node) {
    return node === this;
  }
  focus() {}
}

test("createPhotoStillExportUi shows topbar for single photo and opens controls", () => {
  const panel = new FakeEl({ id: "studio-photo-still-export", hidden: true });
  const openBtn = new FakeEl({ id: "studio-photo-still-export-open", hidden: true });
  const popover = new FakeEl({ id: "studio-photo-still-export-popover", hidden: true });
  const formatEl = new FakeEl({ id: "inspector-photo-still-format" });
  const exportBtn = new FakeEl({ id: "inspector-photo-still-export-btn" });
  const statusEl = new FakeEl({ id: "inspector-photo-still-export-status", hidden: true });
  const byId = {
    "studio-photo-still-export": panel,
    "studio-photo-still-export-open": openBtn,
    "studio-photo-still-export-popover": popover,
    "inspector-photo-still-format": formatEl,
    "inspector-photo-still-export-btn": exportBtn,
    "inspector-photo-still-export-status": statusEl,
  };
  const documentImpl = {
    getElementById(id) {
      return byId[id] || null;
    },
    addEventListener() {},
  };
  let clips = [{ kind: "photo", dataset: { kind: "photo", studioId: "279" } }];
  const ui = createPhotoStillExportUi({
    getClips: () => clips,
    getSelectedClip: () => clips[0],
    documentImpl,
  });

  assert.equal(openBtn.hidden, false);
  assert.equal(panel.hidden, false);
  assert.equal(popover.hidden, true);

  openBtn.click();
  assert.equal(popover.hidden, false);
  assert.equal(openBtn.getAttribute("aria-expanded"), "true");

  clips = [
    { kind: "photo", dataset: { kind: "photo", studioId: "279" } },
    { kind: "video", dataset: { kind: "video", studioId: "280" } },
  ];
  ui.sync();
  assert.equal(openBtn.hidden, true);
  assert.equal(popover.hidden, true);

  clips = [{ kind: "photo", dataset: { kind: "photo", studioId: "279" } }];
  ui.sync();
  assert.equal(openBtn.hidden, false);
});
