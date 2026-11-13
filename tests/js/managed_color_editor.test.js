import assert from "node:assert/strict";
import test from "node:test";
import { createManagedColorEditor } from "../../src/orga_drone/static/js/studio/managed-color-editor.js";

function range(attrs = {}) {
  const el = {
    value: String(attrs.value ?? 0),
    disabled: Boolean(attrs.disabled),
    listeners: {},
    addEventListener(type, fn) {
      this.listeners[type] = fn;
    },
    dispatchEvent(event) {
      this.listeners[event.type]?.();
      return true;
    },
  };
  return el;
}

function label() {
  return { textContent: "" };
}

function button(hidden = false) {
  return {
    hidden,
    disabled: false,
    listeners: {},
    addEventListener(type, fn) {
      this.listeners[type] = fn;
    },
    click() {
      this.listeners.click?.();
    },
  };
}

function buildPanel() {
  const fields = {
    exposure: range({ value: 0, disabled: true }),
    kelvin: range({ value: 6500, disabled: true }),
    tint: range({ value: 0, disabled: true }),
    contrast: range({ value: 1, disabled: true }),
    pivot: range({ value: 0.18, disabled: true }),
    saturation: range({ value: 1, disabled: true }),
    blacks: range({ value: 0, disabled: true }),
    shadows: range({ value: 0, disabled: true }),
    highlights: range({ value: 0, disabled: true }),
    whites: range({ value: 0, disabled: true }),
  };
  const labels = Object.fromEntries(Object.keys(fields).map((key) => [key, label()]));
  const status = { textContent: "" };
  const wrapBtn = button(false);
  const convertBtn = button(false);
  const resetBtn = button(false);
  const map = {
    "[data-managed-color-status]": status,
    "[data-managed-color-wrap]": wrapBtn,
    "[data-managed-color-convert]": convertBtn,
    "[data-managed-color-reset]": resetBtn,
    "[data-managed-exposure]": fields.exposure,
    "[data-managed-kelvin]": fields.kelvin,
    "[data-managed-tint]": fields.tint,
    "[data-managed-contrast]": fields.contrast,
    "[data-managed-pivot]": fields.pivot,
    "[data-managed-saturation]": fields.saturation,
    "[data-managed-blacks]": fields.blacks,
    "[data-managed-shadows]": fields.shadows,
    "[data-managed-highlights]": fields.highlights,
    "[data-managed-whites]": fields.whites,
    "[data-managed-exposure-value]": labels.exposure,
    "[data-managed-kelvin-value]": labels.kelvin,
    "[data-managed-tint-value]": labels.tint,
    "[data-managed-contrast-value]": labels.contrast,
    "[data-managed-pivot-value]": labels.pivot,
    "[data-managed-saturation-value]": labels.saturation,
    "[data-managed-blacks-value]": labels.blacks,
    "[data-managed-shadows-value]": labels.shadows,
    "[data-managed-highlights-value]": labels.highlights,
    "[data-managed-whites-value]": labels.whites,
  };
  return {
    panel: {
      hidden: false,
      querySelector(sel) {
        return map[sel] || null;
      },
    },
    fields,
    status,
    wrapBtn,
    convertBtn,
    resetBtn,
  };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("managed editor enables primaries only for managed-sdr grades", async () => {
  const fixture = buildPanel();
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(["GET", url]);
    return {
      ok: true,
      async json() {
        return {
          evaluator: "legacy-v1",
          authority: "legacy",
          revision: 3,
          grade: { steps: [] },
        };
      },
    };
  };
  const editor = createManagedColorEditor({
    panel: fixture.panel,
    getSelectedStudioId: () => "42",
  });
  await editor.fill();
  assert.equal(fixture.fields.exposure.disabled, true);
  assert.equal(fixture.convertBtn.hidden, false);
  assert.match(fixture.status.textContent, /legacy/);
  assert.deepEqual(calls, [["GET", "/api/studio/42/grade"]]);
});

test("stale fill after clip switch does not paint the previous clip", async () => {
  const fixture = buildPanel();
  let resolveFirst;
  const firstBody = new Promise((resolve) => {
    resolveFirst = resolve;
  });
  let selected = "1";
  let call = 0;
  globalThis.fetch = async () => {
    call += 1;
    if (call === 1) {
      return {
        ok: true,
        async json() {
          return firstBody;
        },
      };
    }
    return {
      ok: true,
      async json() {
        return {
          evaluator: "managed-sdr-v1",
          authority: "canonical",
          revision: 2,
          grade: {
            steps: [
              {
                type: "primaries-v1",
                id: "p2",
                enabled: true,
                params: { exposure: -0.5, kelvin: 6500 },
              },
            ],
          },
        };
      },
    };
  };
  const editor = createManagedColorEditor({
    panel: fixture.panel,
    getSelectedStudioId: () => selected,
  });
  const first = editor.fill();
  selected = "2";
  await editor.fill();
  resolveFirst({
    evaluator: "managed-sdr-v1",
    authority: "canonical",
    revision: 1,
    grade: {
      steps: [
        {
          type: "primaries-v1",
          id: "p1",
          enabled: true,
          params: { exposure: 1.5, kelvin: 4000 },
        },
      ],
    },
  });
  await first;
  assert.equal(fixture.fields.exposure.value, "-0.5");
  assert.equal(fixture.fields.kelvin.value, "6500");
});

test("managed editor paints primaries and command-saves after reset", async () => {
  const fixture = buildPanel();
  const commands = [];
  let revision = 7;
  let gradeSteps = [
    {
      type: "primaries-v1",
      id: "p1",
      enabled: true,
      mix: 1,
      selection_id: null,
      params: { exposure: 0.4, kelvin: 5200 },
    },
  ];
  globalThis.fetch = async (url, init = {}) => {
    if (!init.method || init.method === "GET") {
      return {
        ok: true,
        async json() {
          return {
            evaluator: "managed-sdr-v1",
            authority: "canonical",
            revision,
            grade: { steps: gradeSteps },
          };
        },
      };
    }
    const body = JSON.parse(init.body);
    commands.push({ url: String(url), body, headers: init.headers || {} });
    revision += 1;
    if (body.type === "upsert_step_params") {
      const existing = gradeSteps.find((step) => step.id === body.params.step_id);
      if (existing) {
        existing.params = { ...existing.params, ...body.params.params };
      } else {
        gradeSteps = [
          ...gradeSteps,
          {
            id: body.params.step_id,
            type: body.params.type,
            enabled: true,
            mix: 1,
            selection_id: null,
            params: body.params.params,
          },
        ];
      }
    }
    return {
      ok: true,
      async json() {
        return {
          evaluator: "managed-sdr-v1",
          authority: "canonical",
          revision,
          grade: { steps: gradeSteps },
        };
      },
    };
  };
  const changed = [];
  const editor = createManagedColorEditor({
    panel: fixture.panel,
    getSelectedStudioId: () => "9",
    onChanged: (payload) => changed.push(payload.revision),
  });
  await editor.fill();
  assert.equal(fixture.fields.exposure.disabled, false);
  assert.equal(fixture.fields.exposure.value, "0.4");
  assert.equal(fixture.fields.kelvin.value, "5200");
  assert.equal(fixture.convertBtn.hidden, true);
  assert.equal(fixture.wrapBtn.hidden, true);

  fixture.resetBtn.click();
  await tick();
  await new Promise((resolve) => setTimeout(resolve, 220));
  assert.ok(commands.length >= 1);
  assert.match(commands[0].url, /\/grade\/command$/);
  assert.equal(commands[0].body.type, "upsert_step_params");
  assert.equal(commands[0].body.expected_revision, 7);
  assert.equal(commands[0].body.params.type, "primaries-v1");
  assert.equal(commands[0].body.params.params.exposure, 0);
  assert.ok(commands[0].headers["X-Studio-History-Group"]);
  assert.deepEqual(changed, [8]);
});
