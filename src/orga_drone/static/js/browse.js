/**
 * Persist browse scroll position when opening a media detail link, and restore
 * it when returning to the same browse URL (filters included).
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
})();
