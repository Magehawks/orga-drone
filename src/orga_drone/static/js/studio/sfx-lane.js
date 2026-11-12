/**
 * Freely placed SFX lane (#184 / ADR 0036).
 * Pure DOM helpers for clip bars; persistence stays in the entry via injectables.
 */

export const SFX_MAX_CLIPS = 16;

export function audibleSfxDurationS(clip) {
  const duration = Number(clip?.duration_s);
  const sourceIn = Number(clip?.source_in_s);
  const sourceOut = Number(clip?.source_out_s);
  if (Number.isFinite(sourceIn) && Number.isFinite(sourceOut) && sourceOut > sourceIn) {
    return sourceOut - sourceIn;
  }
  if (Number.isFinite(duration) && duration > 0) return duration;
  return 0;
}

export function sfxClipStyle(clip, pxPerSecond) {
  const start = Math.max(0, Number(clip?.start_s) || 0);
  const width = Math.max(audibleSfxDurationS(clip), 0.05);
  const left = start * pxPerSecond;
  const w = width * pxPerSecond;
  return {
    left: `${left}px`,
    width: `${Math.max(w, 8)}px`,
  };
}

export function renderSfxClips({
  container,
  clips,
  pxPerSecond,
  selectedId,
  onSelect,
  emptyLabel,
}) {
  if (!container) return;
  const list = Array.isArray(clips) ? clips : [];
  container.replaceChildren();
  if (!list.length) {
    const empty = document.createElement("div");
    empty.className = "studio-sfx-empty";
    empty.textContent = emptyLabel || "";
    container.appendChild(empty);
    return;
  }
  for (const clip of list) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "studio-sfx-clip";
    button.dataset.sfxId = String(clip.id);
    if (String(selectedId) === String(clip.id)) {
      button.classList.add("is-selected");
    }
    const style = sfxClipStyle(clip, pxPerSecond);
    button.style.left = style.left;
    button.style.width = style.width;
    button.title = clip.display_name || "";
    button.setAttribute("aria-label", clip.display_name || "SFX");
    const label = document.createElement("span");
    label.className = "studio-sfx-clip-label";
    label.textContent = clip.display_name || "SFX";
    button.appendChild(label);
    button.addEventListener("click", (event) => {
      event.preventDefault();
      onSelect?.(clip.id);
    });
    container.appendChild(button);
  }
}

export function applySfxPayload(stateBox, payload) {
  const clips = Array.isArray(payload?.clips) ? payload.clips.slice() : [];
  if (stateBox && typeof stateBox === "object") {
    stateBox.clips = clips;
  }
  return clips;
}
