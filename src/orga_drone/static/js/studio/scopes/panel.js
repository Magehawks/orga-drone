/**
 * Color scopes inspector panel. Display-only: never writes grade/export.
 * Live engine taps arrive through injectFrame(); fixtures are explicit demos.
 */

import { accumulateAllScopes } from "./accumulate.js";
import { createScopeFixture, listScopeFixtures } from "./fixtures.js";
import { paintScope } from "./render.js";
import {
  SCOPE_SOURCE_KINDS,
  describeScopeSource,
  isScopeFrameCurrent,
  scopeFrameIdentity,
  scopeViewKey,
} from "./scope-frame.js";

export const SCOPE_KINDS = Object.freeze(["histogram", "waveform", "parade", "vectorscope"]);

/**
 * @param {{
 *   root: HTMLElement,
 *   getView?: () => ({projectId:string,clipId:string,gradeRevision:string,contextDigest:string,tapId?:string}),
 *   now?: () => number,
 *   messages?: Record<string,string>,
 * }} options
 */
export function createColorScopesPanel({
  root,
  getView = () => ({
    projectId: "",
    clipId: "",
    gradeRevision: "",
    contextDigest: "",
  }),
  now = () => performance.now(),
  messages = {},
} = {}) {
  if (!root) {
    return {
      destroy() {},
      injectFrame() {
        return { accepted: false, reason: "missing-root" };
      },
      syncView() {
        return { changed: false, cleared: false };
      },
      invalidate() {
        return { changed: false, cleared: false };
      },
      getState() {
        return null;
      },
      getMetrics() {
        return null;
      },
    };
  }

  const canvas = root.querySelector("[data-scope-canvas]");
  const statusEl = root.querySelector("[data-scope-status]");
  const disclosureEl = root.querySelector("[data-scope-disclosure]");
  const kindGroup = root.querySelector("[data-scope-kinds]");
  const fixtureSelect = root.querySelector("[data-scope-fixture]");
  const enableFixture = root.querySelector("[data-scope-fixture-enable]");
  const droppedEl = root.querySelector("[data-scope-dropped]");

  let activeKind = "histogram";
  let fixtureMode = false;
  let fixtureId = "color-bars";
  let latestIdentity = "";
  let currentFrame = null;
  let measurements = null;
  let lastProcessMs = 0;
  let droppedFrames = 0;
  let acceptedFrames = 0;
  let pending = false;
  let boundViewKey = "";

  const label = (key, fallback) => messages[key] || fallback;

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text || "";
  }

  function setDisclosure() {
    if (!disclosureEl) return;
    if (fixtureMode) {
      disclosureEl.textContent = label(
        "fixtureDisclosure",
        "Test patterns only. Not a measurement of your media."
      );
      disclosureEl.dataset.scopeSource = "fixture";
      return;
    }
    if (currentFrame && currentFrame.sourceKind === SCOPE_SOURCE_KINDS.ENGINE_TAP) {
      disclosureEl.textContent = label(
        "liveDisclosure",
        "Engine tap measurement for the selected clip."
      );
      disclosureEl.dataset.scopeSource = "engine-tap";
      return;
    }
    disclosureEl.textContent = label(
      "unavailableDisclosure",
      "Live scopes wait for the graded render-adapter tap. Display pixels are not used as measurements. Saved grades and export stay unchanged."
    );
    disclosureEl.dataset.scopeSource = "unavailable";
  }

  function updateDropped() {
    if (!droppedEl) return;
    droppedEl.textContent = label("droppedFrames", "Dropped frames: {count}").replace(
      "{count}",
      String(droppedFrames)
    );
  }

  function paint() {
    if (!canvas || !measurements) return;
    paintScope(canvas, activeKind, measurements);
  }

  function clearCanvas() {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#141414";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  function processFrame(frame) {
    const started = now();
    measurements = accumulateAllScopes(frame, {
      waveform: { columns: 160, rows: 160 },
      parade: { columns: 120, rows: 160 },
      vectorscope: { size: 160 },
    });
    lastProcessMs = now() - started;
    currentFrame = frame;
    latestIdentity = scopeFrameIdentity(frame);
    acceptedFrames += 1;
    setStatus(
      `${describeScopeSource(frame, {
        fixture: label("sourceFixture", "Test pattern — not a media measurement"),
        live: label("sourceLive", "Engine tap measurement"),
        composite: label("sourceComposite", "Project composite tap"),
        downsampled: label("sourceDownsampled", "Downsampled measurement"),
      })} · ${activeKind} · ${lastProcessMs.toFixed(2)} ms`
    );
    setDisclosure();
    updateDropped();
    paint();
  }

  function clearLive() {
    currentFrame = null;
    measurements = null;
    latestIdentity = "";
    clearCanvas();
    setStatus(label("waiting", "No live scope tap yet"));
    setDisclosure();
  }

  /**
   * Bind the panel to the current project/clip/grade context.
   * Live measurements from a previous view are cleared immediately so they
   * cannot appear as the current clip's analysis.
   */
  function syncView(nextView) {
    const view = nextView || getView() || {};
    const key = scopeViewKey(view);
    if (key === boundViewKey) {
      return { changed: false, cleared: false, viewKey: key };
    }
    boundViewKey = key;
    if (fixtureMode) {
      // Disclosed fixtures are not live media measurements; keep the pattern.
      setDisclosure();
      return { changed: true, cleared: false, viewKey: key };
    }
    const hadLive = Boolean(currentFrame || measurements);
    if (hadLive) clearLive();
    else {
      clearCanvas();
      setStatus(label("waiting", "No live scope tap yet"));
      setDisclosure();
    }
    return { changed: true, cleared: hadLive, viewKey: key };
  }

  function applyFixture() {
    if (!fixtureMode) {
      clearLive();
      return;
    }
    const frame = createScopeFixture(fixtureId);
    processFrame(frame);
  }

  function isOlderThanCurrent(frame) {
    if (!currentFrame) return false;
    if (frame.frameIndex < currentFrame.frameIndex) return true;
    if (frame.frameIndex > currentFrame.frameIndex) return false;
    const nextPts = frame.ptsNum / frame.ptsDen;
    const curPts = currentFrame.ptsNum / currentFrame.ptsDen;
    return nextPts < curPts;
  }

  /**
   * Accept a ScopeFrameV1 from a future engine tap (#366).
   * Stale identities are dropped and counted; fixtures stay labeled separately.
   */
  function injectFrame(frame) {
    syncView();
    if (fixtureMode) {
      return { accepted: false, reason: "fixture-mode" };
    }
    if (!frame) return { accepted: false, reason: "empty" };
    if (frame.sourceKind === SCOPE_SOURCE_KINDS.FIXTURE) {
      return { accepted: false, reason: "fixture-requires-demo-toggle" };
    }
    const view = getView() || {};
    if (!isScopeFrameCurrent(frame, view)) {
      droppedFrames += 1;
      updateDropped();
      return { accepted: false, reason: "stale-view" };
    }
    if (isOlderThanCurrent(frame)) {
      droppedFrames += 1;
      updateDropped();
      return { accepted: false, reason: "stale-frame" };
    }
    if (pending) {
      droppedFrames += 1;
      updateDropped();
      return { accepted: false, reason: "busy" };
    }
    pending = true;
    try {
      processFrame(frame);
      return { accepted: true, identity: latestIdentity, processMs: lastProcessMs };
    } finally {
      pending = false;
    }
  }

  function onKindClick(event) {
    const button = event.target.closest("[data-scope-kind]");
    if (!button) return;
    activeKind = button.dataset.scopeKind;
    kindGroup?.querySelectorAll("[data-scope-kind]").forEach((el) => {
      const on = el.dataset.scopeKind === activeKind;
      el.classList.toggle("is-active", on);
      el.setAttribute("aria-pressed", on ? "true" : "false");
    });
    if (measurements) paint();
    else if (fixtureMode) applyFixture();
  }

  function onFixtureChange() {
    fixtureId = fixtureSelect?.value || "color-bars";
    if (fixtureMode) applyFixture();
  }

  function onFixtureToggle() {
    fixtureMode = Boolean(enableFixture?.checked);
    root.dataset.scopeFixtureMode = fixtureMode ? "1" : "0";
    if (fixtureMode) applyFixture();
    else {
      // Leaving fixture mode must not keep a test pattern as a live reading.
      clearLive();
      syncView();
    }
  }

  kindGroup?.addEventListener("click", onKindClick);
  fixtureSelect?.addEventListener("change", onFixtureChange);
  enableFixture?.addEventListener("change", onFixtureToggle);

  if (fixtureSelect && !fixtureSelect.options.length) {
    for (const id of listScopeFixtures()) {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = id;
      fixtureSelect.appendChild(option);
    }
    fixtureSelect.value = fixtureId;
  }

  boundViewKey = scopeViewKey(getView() || {});
  clearLive();

  return {
    injectFrame,
    syncView,
    invalidate: syncView,
    showFixture(id) {
      fixtureMode = true;
      if (enableFixture) enableFixture.checked = true;
      if (id) fixtureId = id;
      if (fixtureSelect) fixtureSelect.value = fixtureId;
      root.dataset.scopeFixtureMode = "1";
      applyFixture();
    },
    setKind(kind) {
      if (!SCOPE_KINDS.includes(kind)) return;
      activeKind = kind;
      kindGroup?.querySelectorAll("[data-scope-kind]").forEach((el) => {
        const on = el.dataset.scopeKind === kind;
        el.classList.toggle("is-active", on);
        el.setAttribute("aria-pressed", on ? "true" : "false");
      });
      if (measurements) paint();
    },
    getState() {
      return {
        activeKind,
        fixtureMode,
        fixtureId,
        latestIdentity,
        boundViewKey,
        hasMeasurements: Boolean(measurements),
        sourceKind: currentFrame ? currentFrame.sourceKind : null,
      };
    },
    getMetrics() {
      return {
        lastProcessMs,
        droppedFrames,
        acceptedFrames,
      };
    },
    getMeasurements() {
      return measurements;
    },
    destroy() {
      kindGroup?.removeEventListener("click", onKindClick);
      fixtureSelect?.removeEventListener("change", onFixtureChange);
      enableFixture?.removeEventListener("change", onFixtureToggle);
    },
  };
}
