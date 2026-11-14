import {
  MAX_REGIONS,
  MAX_SPEED,
  MIN_SPEED,
  addRampRegion,
  parseRamp,
  placeRampRegion,
  rampPreset,
  rampRegion,
  rampRegions,
  rampSource,
  rampSpeed,
  rampTime,
  removeRampRegion,
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
  let selectedRegionId = "";
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
  function active(ramp) {
    const regions = rampRegions(ramp);
    if (!regions.length) return null;
    const found = regions.findIndex((region) => region.id === selectedRegionId);
    return regions[found >= 0 ? found : 0];
  }
  function regionIdOf(ramp, region) {
    return ramp && ramp.v === 2 ? region.id : null;
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
      selectedRegionId = "";
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
    const region = active(ramp);
    selectedRegionId = region.id;
    selected = Math.min(selected, region.points.length - 1);
    const range = bounds(clip);
    const regionStart = field("region-start");
    const regionEnd = field("region-end");
    if (regionStart && regionEnd) {
      regionStart.value = (region.start - range.start).toFixed(2);
      regionEnd.value = (region.end - range.start).toFixed(2);
      regionStart.disabled = pending;
      regionEnd.disabled = pending;
    }
    const regions = rampRegions(ramp);
    const regionPick = field("region");
    if (regionPick) {
      regionPick.replaceChildren(
        ...regions.map((item, index) => {
          const option = document.createElement("option");
          option.value = item.id;
          option.textContent = String(index + 1);
          return option;
        })
      );
      regionPick.value = region.id;
      regionPick.disabled = pending || regions.length < 2;
    }
    const addRegion = field("add-region");
    const removeRegion = field("remove-region");
    const bounded = ramp.v === 2 || Boolean(ramp.region);
    if (addRegion) addRegion.disabled = pending || !bounded || regions.length >= MAX_REGIONS;
    if (removeRegion) removeRegion.disabled = pending || !bounded;
    const pick = field("point");
    pick.replaceChildren(
      ...region.points.map((_, i) => {
        const option = document.createElement("option");
        option.value = i;
        option.textContent = String(i + 1);
        return option;
      })
    );
    pick.value = String(selected);
    const point = region.points[selected];
    field("time").value = (point.source_s - range.start).toFixed(2);
    field("speed").value = point.speed;
    field("time").disabled = pending;
    field("remove-point").disabled =
      selected === 0 || selected === region.points.length - 1 || pending;
    field("add").disabled = region.points.length >= 5 || pending;
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
    next.region = { start_s: range.start, end_s: range.end };
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
    const clip = getSelection();
    const range = bounds(clip);
    const region = active(value);
    const point = region.points[selected];
    const nextTime = Number(field("time").value) + range.start;
    const nextSpeed = Number(field("speed").value);
    const isEnd = selected === 0 || selected === region.points.length - 1;
    const timeChanged = Number.isFinite(nextTime) && Math.abs(nextTime - point.source_s) > 1e-6;
    if (isEnd && timeChanged) {
      const newStart = selected === 0 ? nextTime : region.start;
      const newEnd = selected === region.points.length - 1 ? nextTime : region.end;
      const placed = placeRampRegion(value, newStart, newEnd, {
        playStart: range.start,
        playEnd: range.end,
        regionId: regionIdOf(value, region),
      });
      if (!placed) {
        onError();
        fill();
        return;
      }
      commit(placed);
      return;
    }
    point.source_s = nextTime;
    point.speed = nextSpeed;
    if (parseRamp(value)) commit(value);
    else {
      onError();
      fill();
    }
  }
  field("time").addEventListener("change", edit);
  field("speed").addEventListener("change", edit);
  function editRegion() {
    const value = copy(current());
    const clip = getSelection();
    const startField = field("region-start");
    const endField = field("region-end");
    if (!value || !clip || !startField || !endField) return;
    const region = active(value);
    if (!region) return;
    const range = bounds(clip);
    const placed = placeRampRegion(
      value,
      Number(startField.value) + range.start,
      Number(endField.value) + range.start,
      {
        playStart: range.start,
        playEnd: range.end,
        regionId: regionIdOf(value, region),
      }
    );
    if (!placed) {
      onError();
      fill();
      return;
    }
    commit(placed);
  }
  const regionStartField = field("region-start");
  const regionEndField = field("region-end");
  if (regionStartField) regionStartField.addEventListener("change", editRegion);
  if (regionEndField) regionEndField.addEventListener("change", editRegion);
  field("add").addEventListener("click", () => {
    const value = copy(current());
    const region = value && active(value);
    if (!value || !region || region.points.length >= 5) return;
    const index = Math.min(selected, region.points.length - 2);
    const source = (region.points[index].source_s + region.points[index + 1].source_s) / 2;
    region.points.splice(index + 1, 0, { source_s: source, speed: rampSpeed(value, source) });
    selected = index + 1;
    commit(value);
  });
  field("remove-point").addEventListener("click", () => {
    const value = copy(current());
    const region = value && active(value);
    if (!value || !region || selected === 0 || selected === region.points.length - 1) return;
    region.points.splice(selected, 1);
    selected -= 1;
    commit(value);
  });
  const regionPick = field("region");
  if (regionPick) {
    regionPick.addEventListener("change", () => {
      selectedRegionId = regionPick.value;
      selected = 0;
      const clip = getSelection();
      if (clip)
        onSelect?.(clip, { focusInspector: false, source: "region", regionId: selectedRegionId });
      fill();
    });
  }
  const addRegion = field("add-region");
  if (addRegion) {
    addRegion.addEventListener("click", () => {
      const value = current();
      const clip = getSelection();
      if (!value || !clip) return;
      const range = bounds(clip);
      const previous = new Set(rampRegions(value).map((region) => region.id));
      const next = addRampRegion(value, {
        playStart: range.start,
        playEnd: range.end,
        preset: field("preset").value,
      });
      if (!next) {
        onError();
        fill();
        return;
      }
      const created = next.regions.find((region) => !previous.has(region.id));
      selectedRegionId = created ? created.id : next.regions[0].id;
      onSelect?.(clip, { focusInspector: false, source: "region", regionId: selectedRegionId });
      commit(next);
    });
  }
  const removeRegion = field("remove-region");
  if (removeRegion) {
    removeRegion.addEventListener("click", () => {
      const value = current();
      if (!value) return;
      const region = active(value);
      const next = removeRampRegion(value, region ? region.id : "");
      if (next === undefined) {
        onError();
        fill();
        return;
      }
      selectedRegionId = next && next.regions ? next.regions[0].id : "";
      selected = 0;
      commit(next);
    });
  }
  function svgNode(name, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }
  function displayRange(ramp) {
    const region = active(ramp);
    return region ? { start: region.start, end: region.end } : rampRegion(ramp);
  }
  function curvePathD(ramp, range) {
    const start = rampTime(ramp, range.start);
    const duration = rampTime(ramp, range.end) - start;
    if (!(duration > 0)) return "";
    const x = (source) => (1000 * (rampTime(ramp, source) - start)) / duration;
    const line = [];
    for (let i = 0; i <= 100; i += 1) {
      const source = range.start + ((range.end - range.start) * i) / 100;
      line.push(`${i ? "L" : "M"}${x(source)},${curveY(rampSpeed(ramp, source))}`);
    }
    return line.join(" ");
  }
  function updateDragVisual() {
    if (!curve || !drag || !draft) return;
    const range = displayRange(draft);
    const start = rampTime(draft, range.start);
    const duration = rampTime(draft, range.end) - start;
    if (!(duration > 0)) return;
    const x = (source) => (1000 * (rampTime(draft, source) - start)) / duration;
    const path = curve.querySelector(".studio-ramp-line");
    if (path) path.setAttribute("d", curvePathD(draft, range));
    const ref = curve.querySelector(".studio-ramp-reference");
    if (ref) {
      const y1 = curveY(1);
      ref.setAttribute("y1", String(y1));
      ref.setAttribute("y2", String(y1));
    }
    curve.querySelectorAll(".studio-ramp-point").forEach((handle) => {
      const index = Number(handle.getAttribute("data-index"));
      const point = active(draft).points[index];
      if (!point) return;
      handle.setAttribute("cx", String(x(point.source_s)));
      handle.setAttribute("cy", String(curveY(point.speed)));
      handle.setAttribute(
        "aria-label",
        `${field("point").getAttribute("aria-label")} ${index + 1}: ${point.speed.toFixed(2)}×`
      );
      handle.setAttribute(
        "class",
        index === selected ? "studio-ramp-point is-selected" : "studio-ramp-point"
      );
    });
    const clip = getSelection();
    const play = clip ? bounds(clip) : range;
    const point = active(draft).points[selected];
    if (point) {
      field("speed").value = point.speed;
      field("time").value = (point.source_s - play.start).toFixed(2);
    }
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
    const range = displayRange(ramp);
    const start = rampTime(ramp, range.start);
    const duration = rampTime(ramp, range.end) - start;
    const x = (source) => (duration > 0 ? (1000 * (rampTime(ramp, source) - start)) / duration : 0);
    const y = curveY;
    curve.replaceChildren(
      svgNode("line", { x1: 0, x2: 1000, y1: y(1), y2: y(1), class: "studio-ramp-reference" }),
      svgNode("path", { d: curvePathD(ramp, range), class: "studio-ramp-line" })
    );
    const focused = active(ramp);
    focused.points.forEach((point, index) => {
      const handle = svgNode("ellipse", {
        cx: x(point.source_s),
        cy: y(point.speed),
        rx: 7000 / Math.max(1, curve.getBoundingClientRect().width),
        ry: 7,
        tabindex: 0,
        role: "button",
        "data-index": index,
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
        drag = {
          ramp: copy(ramp),
          index,
          rect: curve.getBoundingClientRect(),
          range: displayRange(ramp),
        };
        curve.setPointerCapture(event.pointerId);
        fill();
        updateDragVisual();
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
        if (clip)
          onSelect?.(clip, { focusInspector: false, source: "curve", regionId: selectedRegionId });
      });
      curve.addEventListener("contextmenu", (event) => {
        if (pending) return;
        event.preventDefault();
        event.stopPropagation();
        const clip = getSelection();
        if (clip) onContextMenu?.(event, clip, { source: "curve", regionId: selectedRegionId });
      });
      curve.addEventListener("pointermove", (event) => {
        if (!drag || !draft) return;
        const { rect, index } = drag;
        const point = active(draft).points[index];
        const range = displayRange(draft);
        point.speed = Math.max(
          MIN_SPEED,
          Math.min(MAX_SPEED, speedFromCurveY(58 - ((event.clientY - rect.top) * 64) / rect.height))
        );
        point.speed = Number((Math.round(point.speed / 0.05) * 0.05).toFixed(2));
        if (index > 0 && index < active(draft).points.length - 1) {
          const span = rampTime(draft, range.end) - rampTime(draft, range.start);
          const time = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * span;
          point.source_s = Math.max(
            active(draft).points[index - 1].source_s + 0.05,
            Math.min(
              active(draft).points[index + 1].source_s - 0.05,
              rampSource(draft, time, range.start, range.end)
            )
          );
        }
        updateDragVisual();
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
  function selectRegion(id) {
    const next = id || "";
    if (next === selectedRegionId) return;
    selectedRegionId = next;
    selected = 0;
    fill();
  }
  return {
    fill,
    layout,
    cancel,
    selectRegion,
    selectedRegionId: () => selectedRegionId,
    whenIdle: () => idle,
    isBusy: () => pending || Boolean(drag),
  };
}
