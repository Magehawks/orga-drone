(function () {
  // Loading overlay + button state on scan / long-running form submits
  function isLongRunningForm(form) {
    const action = (form.getAttribute("action") || "").toLowerCase();
    return (
      action.includes("/library/add") ||
      action.includes("/scan") ||
      action.includes("scan-all") ||
      action.includes("/duplicates/scan")
    );
  }

  function showBusyOverlay(message) {
    let overlay = document.getElementById("busy-overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "busy-overlay";
      overlay.className = "busy-overlay";
      overlay.setAttribute("role", "status");
      overlay.setAttribute("aria-live", "polite");
      overlay.setAttribute("aria-busy", "true");
      overlay.innerHTML =
        '<div class="busy-overlay-card">' +
        '<span class="busy-spinner" aria-hidden="true"></span>' +
        '<p class="busy-overlay-text"></p>' +
        "</div>";
      document.body.appendChild(overlay);
    }
    const text = overlay.querySelector(".busy-overlay-text");
    if (text) text.textContent = message || "Loading…";
    document.body.classList.add("is-busy");
  }

  document.querySelectorAll("form").forEach((form) => {
    if (!isLongRunningForm(form)) return;
    form.addEventListener("submit", () => {
      const btn = form.querySelector('button[type="submit"], button:not([type])');
      if (btn && !btn.disabled) {
        btn.classList.add("is-loading");
        btn.setAttribute("aria-busy", "true");
        btn.disabled = true;
      }
      const label =
        (btn && btn.getAttribute("data-loading-label")) ||
        form.getAttribute("data-loading-label") ||
        "Scanning…";
      showBusyOverlay(label);
    });
  });

  // Flash / toast polish: dismiss + auto-hide
  document.querySelectorAll(".flash").forEach((el) => {
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "flash-dismiss";
    dismiss.setAttribute("aria-label", "Dismiss");
    dismiss.textContent = "×";
    dismiss.addEventListener("click", () => hideFlash(el));
    el.appendChild(dismiss);
    window.setTimeout(() => hideFlash(el), 6000);
  });

  function hideFlash(el) {
    if (!el || el.classList.contains("is-hiding")) return;
    el.classList.add("is-hiding");
    window.setTimeout(() => el.remove(), 320);
  }

  // Thumbnail loading skeletons
  document.querySelectorAll(".thumb").forEach((thumb) => {
    const media = thumb.querySelector("img, video");
    if (!media) {
      thumb.classList.add("is-loaded");
      return;
    }
    const mark = () => thumb.classList.add("is-loaded");
    if (media.tagName === "IMG") {
      if (media.complete && media.naturalWidth > 0) mark();
      else {
        media.addEventListener("load", mark, { once: true });
        media.addEventListener("error", mark, { once: true });
      }
    } else {
      media.addEventListener("loadeddata", mark, { once: true });
      media.addEventListener("error", mark, { once: true });
      if (media.readyState >= 2) mark();
    }
  });
})();
