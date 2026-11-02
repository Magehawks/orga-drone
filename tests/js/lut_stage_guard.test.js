import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const script = fs.readFileSync("src/orga_drone/static/js/studio.js", "utf8");

function extract(startText, endText) {
  const start = script.indexOf(startText);
  assert.ok(start >= 0, `missing ${startText}`);
  const end = script.indexOf(endText, start);
  assert.ok(end >= 0, `missing ${endText}`);
  return script.slice(start, end);
}

function makeSelect() {
  return {
    children: [],
    value: "",
    set innerHTML(value) {
      if (value === "") this.children = [];
    },
    appendChild(option) {
      this.children.push(option);
    },
  };
}

function lutContext() {
  const context = {
    root: { dataset: { pleaseChoose: "Please choose", noneLabel: "None" } },
    lutCatalog: [
      { asset_name: "creative.cube", display_name: "Creative" },
      { asset_name: "conversion.cube", display_name: "Conversion" },
    ],
    msgColorFileMissingSuffix: "(file missing)",
    msgColorLutStageUsed: "already used in the other stage",
    msgColorLutMissingOption: "Unknown color file (missing)",
    document: {
      createElement: () => ({ value: "", textContent: "", disabled: false }),
    },
    Set,
    String,
  };
  vm.createContext(context);
  vm.runInContext(
    extract("function fillLutSelect", "function syncConversionApplyEnabled"),
    context
  );
  return context;
}

test("LUT stage guard disables a file already used in the other stage", () => {
  const context = lutContext();
  const select = makeSelect();
  context.fillLutSelect(select, "", {
    includeNone: true,
    includePleaseChoose: false,
    blockedAsset: "conversion.cube",
  });
  const blocked = select.children.find((item) => item.value === "conversion.cube");
  assert.equal(blocked.disabled, true);
  assert.match(blocked.textContent, /already used in the other stage/);
  const allowed = select.children.find((item) => item.value === "creative.cube");
  assert.equal(allowed.disabled, false);
});

test("LUT stage guard keeps an existing legacy same-file selection visible", () => {
  const context = lutContext();
  const select = makeSelect();
  context.fillLutSelect(select, "conversion.cube", {
    includeNone: true,
    includePleaseChoose: false,
    blockedAsset: "conversion.cube",
  });
  const selected = select.children.find((item) => item.value === "conversion.cube");
  assert.equal(selected.disabled, false);
  assert.equal(select.value, "conversion.cube");
});
