import {
  MAX_SPEED,
  MIN_SPEED,
  parseRamp,
  rampPreset,
  rampSource,
  rampSpeed,
  rampTime,
} from "./speed-ramp.js";

const LOG_SPAN = Math.log2(MAX_SPEED / MIN_SPEED);
const curveY = (speed) => 58 - (Math.log2(speed / MIN_SPEED) / LOG_SPAN) * 52;
const speedFromCurveY = (normalizedY) => MIN_SPEED * 2 ** ((normalizedY / 52) * LOG_SPAN);

export function createSpeedRampEditor({
  panel,
  getSelection,
  readRamp,
  bounds,
  save,
  pause,
  position,
  onError,
  onSelect,
  onContextMenu,
  isTimedSelected,
}) {
  if (!panel) return { fill() {}, layout() {} };
  const field = (name) => panel.querySelector(`[data-ramp-${name}]`);
  let selected = 0;
  let draft = null;
  let pending = false;
  let idle = Promise.resolve();
  let curve = null;
  let drag = null;
  let selectedClip = null;
  const copy = (value) => JSON.parse(JSON.stringify(value));
  function current() {
    return draft || readRamp(getSelection());
  }
  function hideCurve() {
    if (!curve) return;
    curve.hidden = true;
    curve.replaceChildren();
    if (curve.parentNode) curve.remove();
  }
  function fill() {
    const clip = getSelection();
    if (selectedClip !== clip) {
      draft = null;
      drag = null;
      selected = 0;
      selectedClip = clip;
    }
    panel.hidden = !clip;
    const ramp = current();
    const controls = field("controls");
    controls.hidden = !ramp;
    if (!ramp) {
      hideCurve();
      return;
    }
    selected = Math.min(selected, ramp.points.length - 1);
    const pick = field("point");
    pick.replaceChildren(
      ...ramp.points.map((_, i) => {
        const option = document.createElement("option");
        option.value = i;
        option.textContent = String(i + 1);
        return option;
      })
    );
    pick.value = String(selected);
    const point = ramp.points[selected];
    const range = bounds(clip);
    field("time").value = (point.source_s - range.start).toFixed(2);
    field("speed").value = point.speed;
    field("time").disabled = selected === 0 || selected === ramp.points.length - 1 || pending;
    field("remove-point").disabled =
      selected === 0 || selected === ramp.points.length - 1 || pending;
    field("add").disabled = ramp.points.length >= 5 || pending;
    draw();
  }
  async function commit(value) {
    const clip = getSelection();
    if (pending || !clip) return;
    if (value && !parseRamp(value)) {
      onError();
      fill();
      return;
    }
    pending = true;
    let release;
    idle = new Promise((resolve) => {
      release = resolve;
    });
    pause();
    panel.querySelectorAll("button,input,select").forEach((el) => {
      el.disabled = true;
    });
    try {
      await save(clip, value);
    } catch (error) {
      draft = null;
      onError(error);
    } finally {
      pending = false;
      draft = null;
      panel.querySelectorAll("button,input,select").forEach((el) => {
        el.disabled = false;
      });
      fill();
      release();
    }
  }
  field("apply").addEventListener("click", () => {
    const clip = getSelection();
    if (!clip) return;
    const range = bounds(clip);
    const next = rampPreset(field("preset").value, range.start, range.end);
    if (!next) {
      onError();
      return;
    }
    selected = 0;
    commit(next);
  });
  field("remove").addEventListener("click", () => commit(null));
  field("point").addEventListener("change", () => {
    selected = Number(field("point").value);
    fill();
  });
  function edit() {
    const value = copy(current());
    if (!value) return;
    const range = bounds(getSelection());
    const point = value.points[selected];
    point.source_s = Number(field("time").value) + range.start;
    point.speed = Number(field("speed").value);
    if (parseRamp(value)) commit(value);
    else {
      onError();
      fill();
    }
  }
  field("time").addEventListener("change", edit);
  field("speed").addEventListener("change", edit);
  field("add").addEventListener("click", () => {
    const value = copy(current());
    if (!value || value.points.length >= 5) return;
    const index = Math.min(selected, value.points.length - 2);
    const source = (value.points[index].source_s + value.points[index + 1].source_s) / 2;
    value.points.splice(index + 1, 0, { source_s: source, speed: rampSpeed(value, source) });
    selected = index + 1;
    commit(value);
  });
  field("remove-point").addEventListener("click", () => {
    const value = copy(current());
    if (!value || selected === 0 || selected === value.points.length - 1) return;
    value.points.splice(selected, 1);
    selected -= 1;
    commit(value);
  });
  function svgNode(name, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }
  function draw() {
    if (!curve || drag) return;
    const ramp = current(),
      clip = getSelection();
    if (!ramp || !clip) {
      curve.hidden = true;
      return;
    }
    curve.hidden = false;
    const range = bounds(clip);
    const start = rampTime(ramp, range.start),
      duration = rampTime(ramp, range.end) - start;
    const x = (source) => (1000 * (rampTime(ramp, source) - start)) / duration;
    const y = curveY;
    const line = [];
    for (let i = 0; i <= 100; i += 1) {
      const source = range.start + ((range.end - range.start) * i) / 100;
      line.push(`${i ? "L" : "M"}${x(source)},${y(rampSpeed(ramp, source))}`);
    }
    curve.replaceChildren(
      svgNode("line", { x1: 0, x2: 1000, y1: y(1), y2: y(1), class: "studio-ramp-reference" }),
      svgNode("path", { d: line.join(" "), class: "studio-ramp-line" })
    );
    ramp.points.forEach((point, index) => {
      if (point.source_s < range.start || point.source_s > range.end) return;
      const handle = svgNode("ellipse", {
        cx: x(point.source_s),
        cy: y(point.speed),
        rx: 7000 / Math.max(1, curve.getBoundingClientRect().width),
        ry: 7,
        tabindex: 0,
        role: "button",
        "aria-label": `${field("point").getAttribute("aria-label")} ${index + 1}: ${point.speed.toFixed(2)}×`,
        class: index === selected ? "studio-ramp-point is-selected" : "studio-ramp-point",
      });
      handle.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selected = index;
          fill();
          field("speed").focus();
        }
      });
      handle.addEventListener("pointerdown", (event) => {
        if (pending) return;
        event.stopPropagation();
        event.preventDefault();
        pause();
        selected = index;
        draft = copy(ramp);
        drag = { ramp: copy(ramp), index, rect: curve.getBoundingClientRect(), range };
        curve.setPointerCapture(event.pointerId);
      });
      curve.append(handle);
    });
  }
  function layout(lane) {
    if (!curve) {
      curve = svgNode("svg", {
        viewBox: "0 0 1000 64",
        preserveAspectRatio: "none",
        class: "studio-ramp-curve",
      });
      curve.addEventListener("click", (event) => {
        if (drag || pending) return;
        event.preventDefault();
        event.stopPropagation();
        const clip = getSelection();
        if (clip) onSelect?.(clip, { focusInspector: false, source: "curve" });
      });
      curve.addEventListener("contextmenu", (event) => {
        if (pending) return;
        event.preventDefault();
        event.stopPropagation();
        const clip = getSelection();
        if (clip) onContextMenu?.(event, clip, { source: "curve" });
      });
      curve.addEventListener("pointermove", (event) => {
        if (!drag) return;
        const { rect, index, ramp, range } = drag;
        const point = draft.points[index];
        point.speed = Math.max(
          MIN_SPEED,
          Math.min(MAX_SPEED, speedFromCurveY(58 - ((event.clientY - rect.top) * 64) / rect.height))
        );
        point.speed = Number((Math.round(point.speed / 0.05) * 0.05).toFixed(2));
        if (index > 0 && index < draft.points.length - 1) {
          const time =
            Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) *
            (rampTime(ramp, range.end) - rampTime(ramp, range.start));
          point.source_s = Math.max(
            draft.points[index - 1].source_s + 0.05,
            Math.min(
              draft.points[index + 1].source_s - 0.05,
              rampSource(ramp, time, range.start, range.end)
            )
          );
        }
        const active = drag;
        drag = null;
        fill();
        drag = active;
      });
      curve.addEventListener("pointerup", () => {
        if (!drag) return;
        drag = null;
        commit(draft);
      });
      curve.addEventListener("pointercancel", () => {
        drag = null;
        draft = null;
        fill();
      });
      const cancelDraft = () => {
        if (!drag) return;
        drag = null;
        draft = null;
        fill();
      };
      curve.addEventListener("lostpointercapture", cancelDraft);
      window.addEventListener("blur", cancelDraft);
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && drag) {
          drag = null;
          draft = null;
          fill();
        }
      });
    }
    if (!readRamp(getSelection())) {
      hideCurve();
      return;
    }
    const pos = position(getSelection());
    curve.hidden = false;
    curve.classList.toggle("is-selected", Boolean(isTimedSelected?.()));
    curve.style.left = `${pos.left}px`;
    curve.style.width = `${pos.width}px`;
    curve.style.top = `${Number.parseFloat(lane.style.minHeight) || 36}px`;
    lane.style.minHeight = `${(Number.parseFloat(lane.style.minHeight) || 36) + 68}px`;
    lane.append(curve);
    draw();
  }
  function cancel() {
    if (!drag && !draft) return;
    drag = null;
    draft = null;
    fill();
  }
  return {
    fill,
    layout,
    cancel,
    whenIdle: () => idle,
    isBusy: () => pending || Boolean(drag),
  };
}
