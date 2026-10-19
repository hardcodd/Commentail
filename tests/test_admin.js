const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const vm = require("node:vm");
const script = readFileSync("commentail/static/commentail/admin.js", "utf8");

test("invalid import focuses its error summary without a bulk selection form", () => {
  let focused = false;
  const summary = { focus() { focused = true; } };
  const document = {
    querySelector: (selector) => selector === "[data-commentail-error-focus]" ? summary : null,
  };
  vm.runInNewContext(script, { document });
  assert.equal(focused, true);
});

test("initial import does not move focus", () => {
  const document = { querySelector: () => null };
  vm.runInNewContext(script, { document });
});

test("a moderation result receives focus after redirect", () => {
  const attributes = {};
  let focused = false;
  const result = {
    setAttribute(name, value) { attributes[name] = value; },
    focus() { focused = true; },
  };
  const document = {
    querySelector: (selector) => selector === ".commentail-action-result" ? result : null,
  };
  vm.runInNewContext(script, { document });
  assert.equal(focused, true);
  assert.equal(attributes.tabindex, "-1");
});

function selectionForm(actions) {
  const rows = actions.map((allowed) => ({
    checked: false, dataset: { actions: allowed },
    addEventListener(event, handler) { this[event] = handler; },
  }));
  const buttons = ["approve", "reject", "hide", "restore", "delete"].map(
    (value) => ({ value, disabled: false }),
  );
  const form = {
    querySelectorAll(selector) { return selector.startsWith("input") ? rows : buttons; },
  };
  const master = {
    form, checked: false, indeterminate: false,
    addEventListener(event, handler) { this[event] = handler; },
  };
  const document = {
    querySelector(selector) { return selector === "[data-select-all]" ? master : null; },
  };
  vm.runInNewContext(script, { document });
  return { rows, buttons, master, enabled: () => buttons.filter((b) => !b.disabled).map((b) => b.value) };
}

test("bulk buttons allow only actions shared by all selected rows", () => {
  const ui = selectionForm(["approve reject delete", "hide delete", "restore delete"]);
  assert.deepEqual(ui.enabled(), []);
  ui.rows[0].checked = true;
  ui.rows[0].change();
  assert.deepEqual(ui.enabled(), ["approve", "reject", "delete"]);
  assert.equal(ui.master.indeterminate, true);
  ui.rows[1].checked = true;
  ui.rows[1].change();
  assert.deepEqual(ui.enabled(), ["delete"]);
  ui.master.checked = true;
  ui.master.change();
  assert.equal(ui.rows.every((row) => row.checked), true);
  assert.equal(ui.master.indeterminate, false);
  assert.deepEqual(ui.enabled(), ["delete"]);
  ui.master.checked = false;
  ui.master.change();
  assert.deepEqual(ui.enabled(), []);
});

test("mixed independent grants do not enable an unauthorized bulk action", () => {
  const ui = selectionForm(["hide", "delete"]);
  ui.master.checked = true;
  ui.master.change();
  assert.deepEqual(ui.enabled(), []);
  ui.rows[0].checked = false;
  ui.rows[0].change();
  assert.deepEqual(ui.enabled(), ["delete"]);
});

test("an empty bulk table keeps all action buttons disabled", () => {
  const ui = selectionForm([]);
  assert.deepEqual(ui.enabled(), []);
  assert.equal(ui.master.checked, false);
});
