(function () {
  const dialog = document.getElementById("about-dialog");
  if (!dialog) return;

  const notice = document.getElementById("update-notice");
  const noticeText = document.getElementById("update-notice-text");
  const noticeLink = document.getElementById("update-notice-link");
  const statusEl = document.getElementById("about-check-status");
  const checkBox = document.getElementById("about-check-updates");
  const checkBtn = document.getElementById("about-check-now");
  const CHECKED_KEY = "orga-drone-update-checked";
  const DISMISS_KEY = "orga-drone-update-dismissed";

  function message(name, values) {
    const template = dialog.dataset[name] || "";
    return template.replace(/\{(\w+)\}/g, (_, key) =>
      values && values[key] != null ? String(values[key]) : ""
    );
  }

  function sessionGet(key) {
    try {
      return sessionStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function sessionSet(key, value) {
    try {
      sessionStorage.setItem(key, value);
    } catch (_) {
      /* private mode */
    }
  }

  function showNotice(latest) {
    if (!notice || !latest) return;
    if (sessionGet(DISMISS_KEY) === latest) return;
    if (noticeText) noticeText.textContent = message("msgAvailable", { version: latest });
    notice.dataset.latest = latest;
    notice.hidden = false;
  }

  function setStatus(text) {
    if (!statusEl) return;
    statusEl.textContent = text || "";
  }

  async function openDownload(event) {
    event.preventDefault();
    try {
      const res = await fetch("/api/updates/open-download", {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      if (res.ok) return;
    } catch (_) {
      /* fall through */
    }
    const href = event.currentTarget.getAttribute("href");
    if (href) window.open(href, "_blank", "noopener");
  }

  async function runCheck(startup) {
    if (checkBtn && !startup) {
      checkBtn.disabled = true;
      setStatus(message("msgChecking"));
    }
    try {
      const res = await fetch("/api/updates/check", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ startup: startup }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || data.ok === false) {
        if (!startup) setStatus(message("msgUnavailable"));
        return;
      }
      if (data.state === "skipped") return;
      if (data.state === "update" && data.latest) {
        showNotice(String(data.latest));
        if (!startup) setStatus(message("msgAvailable", { version: data.latest }));
        return;
      }
      if (data.state === "current") {
        if (!startup) setStatus(message("msgCurrent"));
        return;
      }
      if (!startup) setStatus(message("msgUnavailable"));
    } catch (_) {
      if (!startup) setStatus(message("msgUnavailable"));
    } finally {
      if (checkBtn && !startup) checkBtn.disabled = false;
    }
  }

  document.querySelectorAll("[data-open-about]").forEach((button) => {
    button.addEventListener("click", () => {
      if (typeof dialog.showModal === "function") dialog.showModal();
    });
  });

  document.getElementById("about-close")?.addEventListener("click", () => {
    dialog.close();
  });

  checkBox?.addEventListener("change", async () => {
    const enabled = checkBox.checked;
    dialog.dataset.updateCheck = enabled ? "1" : "0";
    try {
      const res = await fetch("/api/updates/preference", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ enabled: enabled }),
      });
      if (!res.ok) checkBox.checked = !enabled;
    } catch (_) {
      checkBox.checked = !enabled;
    }
  });

  checkBtn?.addEventListener("click", () => {
    runCheck(false);
  });

  document.getElementById("update-notice-dismiss")?.addEventListener("click", () => {
    if (notice && notice.dataset.latest) sessionSet(DISMISS_KEY, notice.dataset.latest);
    if (notice) notice.hidden = true;
  });

  noticeLink?.addEventListener("click", openDownload);
  document.getElementById("about-download")?.addEventListener("click", openDownload);

  if (dialog.dataset.updateCheck === "1" && !sessionGet(CHECKED_KEY)) {
    sessionSet(CHECKED_KEY, "1");
    runCheck(true);
  }
})();
