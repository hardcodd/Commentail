/* Focus and selection are enhancements; authorization remains server-side. */
(() => {
  const error = document.querySelector("[data-commentail-error-focus]");
  const result = document.querySelector(".commentail-action-result");
  if (error) error.focus();
  else if (result) {
    result.setAttribute("tabindex", "-1");
    result.focus();
  }
  const panels = new Map();
  document.querySelectorAll("[data-disclosure]").forEach((root) => {
    const toggle = root.querySelector("[data-panel-toggle]");
    const panel = root.querySelector("[data-panel]");
    const inline = root.hasAttribute("data-panel-inline");
    let open = root.dataset.initialOpen === "true";
    const setOpen = (value, returnFocus = false) => {
      open = value;
      toggle.setAttribute("aria-expanded", String(open));
      panel.dataset.open = String(open);
      panel.inert = !open;
      if (returnFocus) toggle.focus();
    };
    panels.set(root, () => setOpen(false));
    root.classList.add("commentail-disclosure-ready");
    toggle.hidden = false;
    setOpen(open);
    toggle.addEventListener("click", () => setOpen(!open));
    root.querySelectorAll("[data-panel-close]").forEach((close) => {
      close.hidden = false;
      close.addEventListener("click", () => setOpen(false, true));
    });
    root.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && open) {
        event.preventDefault();
        setOpen(false, true);
      }
    });
    document.addEventListener("pointerdown", (event) => {
      if (!inline && open && !root.contains(event.target)) setOpen(false);
    });
  });
  const master = document.querySelector("[data-select-all]");
  if (!master) return;
  const form = master.form;
  const rows = [...form.querySelectorAll('input[name="ids"]')];
  const summary = form.querySelector("[data-selection-summary]");
  const counter = form.querySelector("[data-selection-count]");
  const clear = form.querySelector("[data-select-clear]");
  const availability = form.querySelector("[data-action-help]");
  const update = () => {
    const selected = rows.filter((row) => row.checked);
    const count = selected.length;
    if (counter) counter.textContent = String(count);
    if (clear) clear.disabled = count === 0;
    master.checked = rows.length > 0 && count === rows.length;
    master.indeterminate = count > 0 && count < rows.length;
    let unavailable = false;
    form.querySelectorAll('button[name="action"]').forEach((button) => {
      button.disabled = count === 0 || selected.some(
        (row) => !row.dataset.actions.split(" ").includes(button.value),
      );
      const reason = form.querySelector(`[data-bulk-reason="${button.value}"]`);
      if (reason) reason.hidden = count === 0 || !button.disabled;
      unavailable ||= count > 0 && button.disabled;
    });
    if (availability) {
      availability.hidden = !unavailable;
      if (!unavailable) panels.get(availability)?.();
    }
  };
  master.addEventListener("change", () => {
    rows.forEach((row) => { row.checked = master.checked; });
    update();
  });
  if (clear) clear.addEventListener("click", () => {
    rows.forEach((row) => { row.checked = false; });
    update();
    master.focus();
  });
  rows.forEach((row) => row.addEventListener("change", update));
  update();
  if (summary) summary.hidden = false;
})();
