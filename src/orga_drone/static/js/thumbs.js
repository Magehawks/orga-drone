/**
 * Limit concurrent thumbnail fetches so grid/list loads do not open dozens of
 * media files at once (Windows Defender scans each open → CPU/IO spikes).
 *
 * Markup: <img data-thumb-src="..." loading="lazy"> or plain lazy <img src>.
 * When data-thumb-src is set, src is assigned only when in view and under the cap.
 * Off-screen images revert to a tiny placeholder so WebView2 can drop decoded
 * bitmaps (best-effort; page navigation still frees the full DOM).
 */
(function () {
  const MAX_CONCURRENT = 4;
  const PLACEHOLDER =
    "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";
  const imgs = Array.from(
    document.querySelectorAll("img.list-thumb, .thumb img, .flight-clip-thumb img")
  );
  if (!imgs.length) return;

  let active = 0;
  const queue = [];

  function isQueued(img) {
    return queue.indexOf(img) !== -1;
  }

  function dequeue(img) {
    const idx = queue.indexOf(img);
    if (idx !== -1) queue.splice(idx, 1);
  }

  function pump() {
    while (active < MAX_CONCURRENT && queue.length) {
      const img = queue.shift();
      const url = img.dataset.thumbSrc;
      if (!url || img.getAttribute("src") === url) continue;
      active += 1;
      const done = () => {
        active = Math.max(0, active - 1);
        pump();
      };
      img.addEventListener("load", done, { once: true });
      img.addEventListener("error", done, { once: true });
      img.src = url;
    }
  }

  function enqueue(img) {
    if (!img.dataset.thumbSrc) return;
    if (img.getAttribute("src") === img.dataset.thumbSrc) return;
    if (isQueued(img)) return;
    queue.push(img);
    pump();
  }

  function unload(img) {
    if (!img.dataset.thumbSrc) return;
    dequeue(img);
    if (img.getAttribute("src") === PLACEHOLDER) return;
    img.src = PLACEHOLDER;
    const thumb = img.closest(".thumb");
    if (thumb) thumb.classList.remove("is-loaded");
  }

  imgs.forEach((img) => {
    const current = img.getAttribute("src");
    if (!current || !current.includes("/thumb")) return;
    img.dataset.thumbSrc = current;
    img.removeAttribute("src");
    img.setAttribute("src", PLACEHOLDER);
  });

  if (!("IntersectionObserver" in window)) {
    imgs.forEach(enqueue);
    return;
  }

  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) enqueue(entry.target);
        else unload(entry.target);
      });
    },
    { rootMargin: "200px 0px", threshold: 0.01 }
  );

  imgs.forEach((img) => io.observe(img));
})();
