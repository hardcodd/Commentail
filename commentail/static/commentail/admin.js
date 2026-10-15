/* Selection is an enhancement; authorization remains server-side. */
(() => {
  const master = document.querySelector("[data-select-all]");
  if (!master) return;
  const rows = [...document.querySelectorAll('input[name="ids"]')];
  const update = () => {
    const count = rows.filter((row) => row.checked).length;
    master.checked = rows.length > 0 && count === rows.length;
    master.indeterminate = count > 0 && count < rows.length;
    document.querySelectorAll('button[name="action"]').forEach((button) => {
      button.disabled = count === 0;
    });
  };
  master.addEventListener("change", () => {
    rows.forEach((row) => { row.checked = master.checked; });
    update();
  });
  rows.forEach((row) => row.addEventListener("change", update));
  update();
})();
