/**
 * Settings UI for collage framing modifiers (pan drag / wheel zoom).
 */
import {
  FRAMING_MODIFIERS,
  readFramingPrefs,
  writeFramingPrefs,
} from "./studio/collage-framing-prefs.js";

const root = document.getElementById("settings-collage-framing");
if (root) {
  const panEl = document.getElementById("settings-collage-pan-modifier");
  const zoomEl = document.getElementById("settings-collage-zoom-modifier");
  const statusEl = document.getElementById("settings-collage-framing-status");
  const prefs = readFramingPrefs();
  if (panEl && FRAMING_MODIFIERS.includes(prefs.panModifier)) {
    panEl.value = prefs.panModifier;
  }
  if (zoomEl && FRAMING_MODIFIERS.includes(prefs.zoomModifier)) {
    zoomEl.value = prefs.zoomModifier;
  }

  function persist() {
    const next = writeFramingPrefs({
      panModifier: panEl ? panEl.value : "none",
      zoomModifier: zoomEl ? zoomEl.value : "none",
    });
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent =
        root.dataset.saved || "Framing shortcuts saved on this device.";
    }
    return next;
  }

  panEl?.addEventListener("change", persist);
  zoomEl?.addEventListener("change", persist);
}
