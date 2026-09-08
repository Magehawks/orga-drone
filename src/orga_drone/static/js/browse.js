/**
 * Persist browse scroll position when opening a media detail link, and restore
 * it when returning to the same browse URL (filters included).
 * Also enables the current-page Studio bulk-add control.
 */
(function () {
  const KEY = "orga-drone:browse-scroll";
  const pathKey = () => window.location.pathname + window.location.search;

  function isDetailLink(href) {
    if (!href) return false;
    try {
      const url = new URL(href, window.location.origin);
      return /^\/media\/\d+$/.test(url.pathname);
    } catch (_) {
      return false;
    }
  }

  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) {
      const data = JSON.parse(raw);
      if (data && data.path === pathKey() && typeof data.y === "number" && data.y > 0) {
        sessionStorage.removeItem(KEY);
        const y = data.y;
        const restore = () => window.scrollTo(0, y);
        restore();
        window.requestAnimationFrame(restore);
        window.setTimeout(restore, 50);
      }
    }
  } catch (_) {
    /* ignore quota / private mode */
  }

  document.addEventListener("click", (event) => {
    const anchor = event.target && event.target.closest
      ? event.target.closest("a[href]")
      : null;
    if (!anchor || !isDetailLink(anchor.getAttribute("href"))) return;
    try {
      sessionStorage.setItem(
        KEY,
        JSON.stringify({
          path: pathKey(),
          y: window.scrollY || window.pageYOffset || 0,
        })
      );
    } catch (_) {
      /* ignore */
    }
  });

  const bulkForm = document.getElementById("browse-bulk-studio");
  const bulkSubmit = document.getElementById("browse-bulk-submit");
  const bulkCount = document.getElementById("browse-bulk-count");
  if (bulkForm && bulkSubmit) {
    const syncBulk = () => {
      const selected = document.querySelectorAll(
        'input.browse-select-input[name="media_ids"][form="browse-bulk-studio"]:checked:not(:disabled)'
      );
      const n = selected.length;
      bulkSubmit.disabled = n === 0;
      if (bulkCount) {
        if (n > 0) {
          bulkCount.hidden = false;
          bulkCount.textContent = String(n);
        } else {
          bulkCount.hidden = true;
          bulkCount.textContent = "";
        }
      }
    };
    document.addEventListener("change", (event) => {
      const t = event.target;
      if (
        t &&
        t.classList &&
        t.classList.contains("browse-select-input") &&
        t.getAttribute("form") === "browse-bulk-studio"
      ) {
        syncBulk();
      }
    });
    bulkForm.addEventListener("submit", (event) => {
      const n = document.querySelectorAll(
        'input.browse-select-input[name="media_ids"][form="browse-bulk-studio"]:checked:not(:disabled)'
      ).length;
      if (n === 0) {
        event.preventDefault();
        syncBulk();
      }
    });
    syncBulk();
  }
})();
