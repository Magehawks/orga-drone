(function () {
  // Loading state on scan / long-running form submits
  document.querySelectorAll("form").forEach((form) => {
    const action = (form.getAttribute("action") || "").toLowerCase();
    const isScan =
      action.includes("/scan") ||
      action.includes("scan-all") ||
      action.includes("/duplicates/scan");
    if (!isScan) return;
    form.addEventListener("submit", () => {
      const btn = form.querySelector('button[type="submit"], button:not([type])');
      if (btn && !btn.disabled) {
        btn.classList.add("is-loading");
        btn.setAttribute("aria-busy", "true");
      }
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
