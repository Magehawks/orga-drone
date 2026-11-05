/** One sequential command handshake. Editing/preview functions are injected. */
export function hasActiveControlGesture({
  dragCard,
  musicDragCard,
  dragOriginalMediaId,
  edgeDrag,
  maskDragging,
  playheadDragging,
}) {
  return Boolean(
    dragCard || musicDragCard || dragOriginalMediaId || edgeDrag || maskDragging || playheadDragging
  );
}

export function createControlBridge({
  sessionId,
  snapshot,
  whenIdle,
  applyCanonical,
  resumeTicket = null,
  resumeSelection = () => {},
  reloadTimeline = () => {
    throw new Error("Timeline reload unavailable");
  },
  applyProject = () => {
    throw new Error("Project application unavailable");
  },
  lockInput,
  status = () => {},
  request,
}) {
  let enabled = false;
  let running = false;
  let revision = 0;
  let dirty = false;
  let settling = null;
  let stopped = false;
  let uncertainProject = null;
  let resumedCommand = null;

  function noteLocalChange() {
    revision += 1;
    dirty = true;
  }

  function readState() {
    const state = snapshot();
    return { ...state, selection_revision: revision, busy: state.busy || dirty };
  }

  async function settle() {
    if (settling || !dirty) return;
    const before = revision;
    settling = Promise.resolve().then(whenIdle);
    try {
      await settling;
      if (revision === before && !snapshot().busy) dirty = false;
    } finally {
      settling = null;
    }
  }

  async function enable(pairingKey) {
    const result = await request("enable", { session_id: sessionId, pairing_key: pairingKey });
    enabled = result.enabled;
    status(enabled ? "ready" : "off");
    return result;
  }

  async function disable() {
    enabled = false;
    const result = await request("disable", {});
    status("off");
    return result;
  }

  async function tick() {
    if (running || stopped) return;
    running = true;
    try {
      if (resumeTicket || resumedCommand) {
        lockInput(true);
        try {
          if (resumeTicket) {
            if (dirty) throw new Error("Local selection changed before resume");
            const resumed = await request("resume", {
              ticket: resumeTicket,
              project_id: snapshot().project_id,
            });
            resumeTicket = null;
            sessionId = resumed.session_id;
            revision = resumed.selection_revision;
            resumeSelection(resumed.selection_clip_id);
            resumedCommand = resumed.command_id;
            enabled = true;
          }
          await request("poll", { session_id: sessionId, state: readState() });
          await request("ack", {
            session_id: sessionId,
            command_id: resumedCommand,
            preview_status: "refresh_requested",
          });
          resumedCommand = null;
          lockInput(false);
        } catch (error) {
          // Keep a one-use ticket on a network failure so the next tick can
          // retry. A server rejection means the ticket is dead.
          if (!error.code && resumeTicket) {
            status("disconnected");
            return;
          }
          resumeTicket = null;
          if (error.code) resumedCommand = null;
          if (!resumedCommand) lockInput(false);
          status(error.code === "EDITOR_SESSION_CONFLICT" ? "conflict" : "disconnected");
          return;
        }
      }
      if (enabled) void settle().catch(() => status("busy"));
      const polled = uncertainProject
        ? {
            enabled: true,
            commands: [
              await request("recover", {
                session_id: sessionId,
                command_id: uncertainProject,
              }),
            ],
          }
        : await request("poll", { session_id: sessionId, state: readState() });
      enabled = polled.enabled;
      if (!enabled) {
        status("off");
        return;
      }
      const current = readState();
      status(
        current.playing
          ? "playing"
          : current.busy
            ? "busy"
            : current.ready
              ? "ready"
              : "unsupported"
      );
      for (const command of polled.commands || []) {
        // Input exclusion begins before the final synchronous local state read.
        lockInput(true);
        let navigationCommitted = false;
        try {
          let result = command;
          if (result.status === "rejected") {
            uncertainProject = null;
            continue;
          }
          if (!result.persisted) {
            try {
              result = await request("execute", {
                session_id: sessionId,
                command_id: command.command_id,
                state: readState(),
              });
              uncertainProject = null;
            } catch (error) {
              // This request may have committed a project switch. Retain the
              // lock until a recovery poll returns the original outcome.
              if (["project", "timeline"].includes(command.scope))
                uncertainProject = command.command_id;
              throw error;
            }
          }
          if (result.persisted && !result.ui_applied) {
            if (result.scope === "timeline" && result.reload_required) {
              if (!result.resume_ticket) throw new Error("Timeline resume unavailable");
              stopped = true;
              navigationCommitted = true;
              reloadTimeline(result);
              return;
            }
            if (result.scope === "timeline") {
              const fresh = readState();
              if (fresh.busy || fresh.playing) continue;
              await request("ack", {
                session_id: sessionId,
                command_id: result.command_id,
                preview_status: "unavailable",
              });
              status("applied");
              continue;
            }
            const projectAction = result.scope === "project";
            if (projectAction && result.navigation_required) {
              // The committed context is authoritative. A lost acknowledgement
              // must never strand the old editor on another project's context.
              stopped = true;
              navigationCommitted = true;
              applyProject(result);
              return;
            }
            const fresh = readState();
            if (fresh.busy || fresh.playing) continue;
            uncertainProject = null;
            const previewStatus = projectAction ? "unavailable" : applyCanonical(result);
            if (projectAction) applyProject(result);
            await request("ack", {
              session_id: sessionId,
              command_id: result.command_id,
              preview_status: previewStatus,
            });
            status("applied");
          }
        } finally {
          if (!navigationCommitted && !uncertainProject) lockInput(false);
        }
      }
    } catch (error) {
      status(error.code === "EDITOR_SESSION_CONFLICT" ? "conflict" : "disconnected");
    } finally {
      running = false;
    }
  }

  return {
    enable,
    disable,
    tick,
    noteLocalChange,
    readState,
    stop: () => {
      stopped = true;
    },
  };
}

export function createBridgeRequest(fetchImpl) {
  return async (action, body) => {
    const response = await fetchImpl(`/api/studio/control/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const value = await response.json();
    if (!response.ok) {
      const error = new Error("External control request failed");
      error.code = value.error?.code;
      throw error;
    }
    return value;
  };
}

/** Apply canonical settings only to the explicitly identified active clip. */
export function createCanonicalApplier({
  snapshot,
  getClip,
  writeImage,
  writeColor,
  writeHsl,
  writeWheels,
  writeDetail,
  fillInspector,
  syncHistory,
  refreshPreview,
  setSaved,
}) {
  return (result) => {
    const state = snapshot();
    if (result.project_id !== state.project_id || result.clip_id !== state.clip_id) {
      throw new Error("Canonical control target no longer selected");
    }
    const clip = getClip(result.clip_id);
    if (!clip) throw new Error("Control clip no longer present");
    const canonical = result.canonical || {};
    const changed = (raw, value) => {
      if (!clip.dataset) return true;
      try {
        return JSON.stringify(JSON.parse(raw || "null")) !== JSON.stringify(value);
      } catch {
        return true;
      }
    };
    writeImage(clip, canonical.image, true);
    writeColor(clip, canonical.color_look);
    if (canonical.hsl && writeHsl && changed(clip.dataset && clip.dataset.hsl, canonical.hsl))
      writeHsl(clip, canonical.hsl, true);
    if (
      canonical.color_wheels &&
      writeWheels &&
      changed(clip.dataset && clip.dataset.colorWheels, canonical.color_wheels)
    )
      writeWheels(clip, canonical.color_wheels, true);
    if (
      canonical.detail &&
      writeDetail &&
      changed(clip.dataset && clip.dataset.detail, canonical.detail)
    )
      writeDetail(clip, canonical.detail);
    fillInspector(clip);
    syncHistory(result.can_undo, result.can_redo);
    refreshPreview();
    setSaved(true);
    return "refresh_requested";
  };
}

export function mountControlUi({
  panel,
  snapshot,
  whenIdle,
  applyCanonical,
  applyProject,
  resumeSelection,
  fetchImpl,
  hasWriteFailure = () => false,
}) {
  const statusEl = panel.querySelector("[data-control-status]");
  const keyInput = panel.querySelector("input");
  const texts = JSON.parse(panel.dataset.messages);
  let locked = false;
  let pointerActive = false;
  let keyActive = false;
  let lastChange = -1000;
  const events = [
    "pointerdown",
    "pointerup",
    "click",
    "dblclick",
    "keydown",
    "keyup",
    "input",
    "change",
    "dragstart",
    "drop",
    "wheel",
  ];
  events.forEach((name) =>
    window.addEventListener(
      name,
      (event) => {
        if (panel.contains(event.target)) return;
        if (locked) {
          event.preventDefault();
          event.stopImmediatePropagation();
          return;
        }
        if (name === "pointerdown") pointerActive = true;
        if (name === "pointerup") pointerActive = false;
        if (name === "keydown") keyActive = true;
        if (name === "keyup") keyActive = false;
        if (["pointerdown", "keydown", "input", "change", "drop"].includes(name)) {
          lastChange = performance.now();
          bridge.noteLocalChange();
        }
      },
      { capture: true, passive: false }
    )
  );
  document.addEventListener(
    "pointercancel",
    () => {
      pointerActive = false;
    },
    true
  );
  window.addEventListener("blur", () => {
    pointerActive = false;
    keyActive = false;
  });
  let resumeTicket;
  const resumeKey = "orga-drone.timeline-resume";
  try {
    resumeTicket = window.sessionStorage.getItem(resumeKey);
    window.sessionStorage.removeItem(resumeKey);
  } catch {
    resumeTicket = null;
  }
  const fallbackPrefix = resumeKey + ":";
  if (!resumeTicket && window.name.startsWith(fallbackPrefix)) {
    resumeTicket = window.name.slice(fallbackPrefix.length);
    window.name = "";
  }
  const bridge = createControlBridge({
    sessionId: crypto.randomUUID(),
    resumeTicket,
    resumeSelection,
    reloadTimeline: (result) => {
      try {
        window.sessionStorage.setItem(resumeKey, result.resume_ticket);
      } catch {
        window.name = resumeKey + ":" + result.resume_ticket;
      }
      window.location.reload();
    },
    request: createBridgeRequest(fetchImpl),
    snapshot: () => {
      const state = snapshot();
      return {
        ...state,
        busy: state.busy || pointerActive || keyActive || performance.now() - lastChange < 500,
      };
    },
    whenIdle,
    applyCanonical,
    applyProject,
    lockInput: (value) => {
      locked = value;
    },
    status: (code) => {
      if (code === "busy" && hasWriteFailure()) code = "save_failed";
      const next = texts[code] || texts.disconnected;
      if (statusEl.textContent !== next) statusEl.textContent = next;
    },
  });
  async function enable() {
    const key = keyInput.value;
    keyInput.value = "";
    try {
      await bridge.enable(key);
    } catch {
      statusEl.textContent = texts.enable_failed;
    }
  }
  panel.querySelector("[data-control-enable]").addEventListener("click", enable);
  keyInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void enable();
    }
  });
  panel.querySelector("[data-control-disable]").addEventListener("click", () => {
    void bridge.disable().catch(() => {
      statusEl.textContent = texts.disconnected;
    });
  });
  let timer;
  let stopped = false;
  async function poll() {
    await bridge.tick();
    if (!stopped) timer = window.setTimeout(poll, 250);
  }
  void poll();
  window.addEventListener("pagehide", () => {
    stopped = true;
    bridge.stop();
    window.clearTimeout(timer);
  });
  return bridge;
}
