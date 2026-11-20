import assert from "node:assert/strict";
import test from "node:test";

import {
  CONTEXT_PHOTO,
  CONTEXT_STORY,
  createEditingContextController,
  normalizeEditingContext,
  projectNeedsStoryTools,
  projectSuggestsPhotoContext,
  readStoredEditingContext,
  resolveInitialEditingContext,
  storageKeyForProject,
  writeStoredEditingContext,
} from "../../src/orga_drone/static/js/studio/editing-context.js";

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
    this.classList = new FakeClassList();
    this.dataset = {};
    this.hidden = false;
    this.attrs = {};
    this.listeners = {};
  }

  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }

  getAttribute(name) {
    return this.attrs[name];
  }

  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }

  click() {
    for (const fn of this.listeners.click || []) fn();
  }
}

function makeMemoryStorage() {
  const map = new Map();
  return {
    getItem(key) {
      return map.has(key) ? map.get(key) : null;
    },
    setItem(key, value) {
      map.set(String(key), String(value));
    },
    removeItem(key) {
      map.delete(key);
    },
  };
}

test("normalizeEditingContext defaults unknown values to story", () => {
  assert.equal(normalizeEditingContext("photo"), CONTEXT_PHOTO);
  assert.equal(normalizeEditingContext("PHOTO"), CONTEXT_PHOTO);
  assert.equal(normalizeEditingContext("story"), CONTEXT_STORY);
  assert.equal(normalizeEditingContext(""), CONTEXT_STORY);
  assert.equal(normalizeEditingContext("timeline"), CONTEXT_STORY);
});

test("projectSuggestsPhotoContext is true only for non-empty photo-only sets", () => {
  assert.equal(projectSuggestsPhotoContext([]), false);
  assert.equal(projectSuggestsPhotoContext([{ kind: "photo" }]), true);
  assert.equal(projectSuggestsPhotoContext([{ kind: "photo" }, { kind: "photo" }]), true);
  assert.equal(projectSuggestsPhotoContext([{ kind: "photo" }, { kind: "video" }]), false);
  assert.equal(projectSuggestsPhotoContext(["photo", "photo"]), true);
  assert.equal(projectSuggestsPhotoContext(["photo", "video"]), false);
});

test("resolveInitialEditingContext prefers stored preference over photo-only suggestion", () => {
  const storage = makeMemoryStorage();
  writeStoredEditingContext(7, CONTEXT_STORY, storage);
  assert.equal(
    resolveInitialEditingContext({
      projectId: 7,
      clips: [{ kind: "photo" }],
      storage,
    }),
    CONTEXT_STORY
  );
  writeStoredEditingContext(7, CONTEXT_PHOTO, storage);
  assert.equal(
    resolveInitialEditingContext({
      projectId: 7,
      clips: [{ kind: "photo" }, { kind: "video" }],
      storage,
    }),
    CONTEXT_PHOTO
  );
});

test("resolveInitialEditingContext suggests photo for photo-only projects without store", () => {
  const storage = makeMemoryStorage();
  assert.equal(
    resolveInitialEditingContext({
      projectId: 3,
      clips: [{ kind: "photo" }],
      storage,
    }),
    CONTEXT_PHOTO
  );
  assert.equal(
    resolveInitialEditingContext({
      projectId: 3,
      clips: [{ kind: "video" }],
      storage,
    }),
    CONTEXT_STORY
  );
});

test("projectNeedsStoryTools detects non-photo Story items", () => {
  assert.equal(projectNeedsStoryTools([{ kind: "photo" }]), false);
  assert.equal(projectNeedsStoryTools([{ kind: "photo" }, { kind: "video" }]), true);
  assert.equal(projectNeedsStoryTools([{ kind: "title" }]), true);
  assert.equal(projectNeedsStoryTools([]), false);
});

test("createEditingContextController toggles classes and never auto-switches on refresh", () => {
  const root = new FakeElement("studio-root");
  const photoBtn = new FakeElement("studio-context-photo");
  const storyBtn = new FakeElement("studio-context-story");
  const storyArea = new FakeElement("story-area");
  const continuityHint = new FakeElement("studio-context-continuity-hint");
  const modeBanner = new FakeElement("studio-context-mode-banner");
  const managedColor = new FakeElement("inspector-managed-color");
  managedColor.open = false;
  const stage = new FakeElement("studio-stage");
  stage.style = {
    props: {},
    setProperty(name, value) {
      this.props[name] = value;
    },
  };
  continuityHint.hidden = true;
  modeBanner.hidden = true;
  storyArea.classList.add("studio-story-area");
  const storage = makeMemoryStorage();
  const changes = [];
  let clips = [{ kind: "photo" }];

  const documentImpl = {
    getElementById(id) {
      if (id === "studio-context-photo") return photoBtn;
      if (id === "studio-context-story") return storyBtn;
      if (id === "studio-context-continuity-hint") return continuityHint;
      if (id === "studio-context-mode-banner") return modeBanner;
      if (id === "inspector-managed-color") return managedColor;
      return null;
    },
    querySelector(sel) {
      if (sel === ".studio-story-area") return storyArea;
      if (sel === ".studio-stage") return stage;
      return null;
    },
  };

  const controller = createEditingContextController({
    root,
    projectId: 12,
    getClips: () => clips,
    storage,
    documentImpl,
    onChange: (ctx) => changes.push(ctx),
  });

  assert.equal(controller.getContext(), CONTEXT_PHOTO);
  assert.equal(root.classList.contains("is-photo-context"), true);
  assert.equal(photoBtn.getAttribute("aria-pressed"), "true");
  assert.equal(storyBtn.getAttribute("aria-pressed"), "false");
  assert.equal(storyArea.getAttribute("aria-hidden"), "true");
  assert.equal(storyArea.hidden, true);
  assert.equal(modeBanner.hidden, false);
  assert.equal(managedColor.open, true);
  assert.equal(stage.style.props["--studio-story-height"], "0px");
  assert.equal(continuityHint.hidden, true);
  assert.deepEqual(changes, [CONTEXT_PHOTO]);

  controller.setContext(CONTEXT_STORY);
  assert.equal(controller.getContext(), CONTEXT_STORY);
  assert.equal(readStoredEditingContext(12, storage), CONTEXT_STORY);
  assert.equal(root.classList.contains("is-story-context"), true);
  assert.equal(storyArea.getAttribute("aria-hidden"), "false");
  assert.equal(storyArea.hidden, false);
  assert.equal(modeBanner.hidden, true);
  assert.equal(managedColor.open, true); // stays open; Story does not force-collapse
  assert.match(stage.style.props["--studio-story-height"], /px$/);

  // Continuity (#501): adding clips / refresh must not flip context.
  clips = [{ kind: "photo" }, { kind: "video" }];
  controller.refresh();
  assert.equal(controller.getContext(), CONTEXT_STORY);
  assert.equal(changes.at(-1), CONTEXT_STORY);
  assert.equal(continuityHint.hidden, true);

  photoBtn.click();
  assert.equal(controller.getContext(), CONTEXT_PHOTO);
  assert.equal(storage.getItem(storageKeyForProject(12)), CONTEXT_PHOTO);
  assert.equal(continuityHint.hidden, false);

  // Stored Photo focus survives mixed media on a fresh resolve (#501).
  assert.equal(
    resolveInitialEditingContext({
      projectId: 12,
      clips,
      storage,
    }),
    CONTEXT_PHOTO
  );
});
