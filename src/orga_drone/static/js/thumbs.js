/**
 * Limit concurrent thumbnail fetches so grid/list loads do not open dozens of
 * media files at once (Windows Defender scans each open → CPU/IO spikes).
 *
 * Markup: <img data-thumb-src="..." loading="lazy"> or plain lazy <img src>.
 * When data-thumb-src is set, src is assigned only when in view and under the cap.
 */
(function () {
  const MAX_CONCURRENT = 4;
  const imgs = Array.from(
    document.querySelectorAll("img.list-thumb, .thumb img, .flight-clip-thumb img")
  );
  if (!imgs.length) return;

  // If templates already set src + loading=lazy, still throttle by temporarily
  // parking src on data-thumb-src for off-screen images (browser may ignore
  // lazy under some conditions / many above-the-fold cards).
  let active = 0;
  const queue = [];

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
    queue.push(img);
    pump();
  }

  imgs.forEach((img) => {
    const current = img.getAttribute("src");
    if (!current || !current.includes("/thumb")) return;
    img.dataset.thumbSrc = current;
    // Keep a tiny transparent placeholder so layout stays stable.
    img.removeAttribute("src");
    img.setAttribute("src", "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==");
  });

  if (!("IntersectionObserver" in window)) {
    imgs.forEach(enqueue);
    return;
  }

  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        io.unobserve(entry.target);
        enqueue(entry.target);
      });
    },
    { rootMargin: "200px 0px", threshold: 0.01 }
  );

  imgs.forEach((img) => io.observe(img));
})();
