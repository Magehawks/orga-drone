/**
 * Detail-page action tabs. One panel is visible. The choice lasts for this
 * browser session; the first open is Organize.
 */
(function () {
  const root = document.getElementById("detail-actions");
  if (!root) return;

  const storageKey = "orga-drone.detail.actionsTab";
  const buttons = Array.from(root.querySelectorAll("[data-detail-tab-button]"));
  const panels = Array.from(root.querySelectorAll("[data-detail-tab-panel]"));
  if (!buttons.length) return;

  function select(name, focusButton) {
    const names = buttons.map((button) => button.dataset.detailTabButton);
    const tab = names.includes(name) ? name : names[0];
    buttons.forEach((button) => {
      const on = button.dataset.detailTabButton === tab;
      button.classList.toggle("is-active", on);
      button.setAttribute("aria-selected", on ? "true" : "false");
      button.tabIndex = on ? 0 : -1;
      if (on && focusButton) button.focus();
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.detailTabPanel !== tab;
    });
    try {
      sessionStorage.setItem(storageKey, tab);
    } catch (_) {
      /* private mode */
    }
  }

  buttons.forEach((button, index) => {
    button.addEventListener("click", () => {
      select(button.dataset.detailTabButton, false);
    });
    button.addEventListener("keydown", (event) => {
      let next = null;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        next = (index + 1) % buttons.length;
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        next = (index - 1 + buttons.length) % buttons.length;
      } else if (event.key === "Home") {
        next = 0;
      } else if (event.key === "End") {
        next = buttons.length - 1;
      } else {
        return;
      }
      event.preventDefault();
      select(buttons[next].dataset.detailTabButton, true);
    });
  });

  let stored = null;
  try {
    stored = sessionStorage.getItem(storageKey);
  } catch (_) {
    stored = null;
  }
  select(stored || "organize", false);
})();
