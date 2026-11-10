import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createSpeedRampEditor } from "../../src/orga_drone/static/js/studio/speed-ramp-editor.js";
import { parseRamp } from "../../src/orga_drone/static/js/studio/speed-ramp.js";

const fixture = JSON.parse(readFileSync(new URL("../fixtures/speed_ramp.json", import.meta.url)));
const tick = () => new Promise((resolve) => setImmediate(resolve));

function field(name, extras = {}) {
  return {
    name,
    value: "",
    disabled: false,
    hidden: false,
    listeners: {},
    getAttribute() {
      return name;
    },
    addEventListener(type, fn) {
      this.listeners[type] = fn;
    },
    dispatch(type) {
      this.listeners[type]?.({ preventDefault() {}, stopPropagation() {} });
    },
    replaceChildren() {},
    ...extras,
  };
}

function installDom() {
  globalThis.window = {
    addEventListener() {},
  };
  globalThis.document = {
    createElement(tag) {
      return {
        tagName: String(tag).toUpperCase(),
        value: "",
        textContent: "",
      };
    },
    createElementNS(_ns, tag) {
      const node = {
        tagName: tag,
        attrs: {},
        children: [],
        style: {},
        hidden: false,
        parentNode: null,
        setAttribute(key, value) {
          this.attrs[key] = String(value);
        },
        replaceChildren(...kids) {
          this.children = kids;
        },
        append(...kids) {
          for (const kid of kids) {
            kid.parentNode = this;
            this.children.push(kid);
          }
        },
        addEventListener() {},
        setPointerCapture() {},
        getBoundingClientRect() {
          return { width: 400, height: 64, left: 0, top: 0 };
        },
        remove() {
          if (!this.parentNode) return;
          this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
          this.parentNode = null;
        },
      };
      return node;
    },
    addEventListener() {},
  };
}

function fixtureEditor() {
  installDom();
  const controls = field("controls", { hidden: true });
  const remove = field("remove");
  const apply = field("apply");
  const preset = field("preset", { value: "acceleration" });
  const point = field("point");
  const time = field("time");
  const speed = field("speed");
  const add = field("add");
  const removePoint = field("remove-point");
  const fields = {
    controls,
    remove,
    apply,
    preset,
    point,
    time,
    speed,
    add,
    "remove-point": removePoint,
  };
  const panel = {
    hidden: false,
    querySelector(sel) {
      const key = String(sel)
        .replace(/^\[data-ramp-/, "")
        .replace(/\]$/, "");
      return fields[key] || null;
    },
    querySelectorAll() {
      return Object.values(fields);
    },
  };
  const lane = {
    children: [],
    style: { minHeight: "36px" },
    append(node) {
      node.parentNode = this;
      this.children.push(node);
    },
  };
  const clip = { dataset: { studioId: "1", speedRamp: "null" } };
  let ramp = null;
  const saves = [];
  const editor = createSpeedRampEditor({
    panel,
    getSelection: () => clip,
    readRamp: () => ramp,
    bounds: () => ({ start: 0, end: 5 }),
    pause() {},
    position: () => ({ left: 10, width: 200 }),
    onError() {},
    async save(c, value) {
      saves.push(value);
      ramp = value ? parseRamp(value) && value : null;
      c.dataset.speedRamp = value ? JSON.stringify(value) : "null";
    },
  });
  return {
    editor,
    controls,
    remove,
    lane,
    saves,
    setRamp(next) {
      ramp = next;
      clip.dataset.speedRamp = next ? JSON.stringify(next) : "null";
    },
  };
}

test("removing a ramp hides controls and detaches the curve", async () => {
  const f = fixtureEditor();
  f.setRamp(fixture.curve);
  f.editor.fill();
  f.editor.layout(f.lane);
  assert.equal(f.controls.hidden, false);
  assert.equal(f.lane.children.length, 1);
  assert.equal(f.lane.children[0].hidden, false);
  f.remove.dispatch("click");
  await tick();
  assert.deepEqual(f.saves, [null]);
  assert.equal(f.controls.hidden, true);
  assert.equal(f.lane.children.length, 0);
  f.editor.layout(f.lane);
  assert.equal(f.lane.children.length, 0);
});
