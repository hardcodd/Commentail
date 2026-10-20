const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const vm = require("node:vm");
const script = readFileSync("commentail/static/commentail/admin.js", "utf8");

test("invalid import focuses its error summary without a bulk selection form", () => {
  let focused = false;
  const summary = { focus() { focused = true; } };
  const document = {
    querySelectorAll: () => [],
    querySelector: (selector) => selector === "[data-commentail-error-focus]" ? summary : null,
  };
  vm.runInNewContext(script, { document });
  assert.equal(focused, true);
});

test("initial import does not move focus", () => {
  const document = { querySelector: () => null, querySelectorAll: () => [] };
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
    querySelectorAll: () => [],
    querySelector: (selector) => selector === ".commentail-action-result" ? result : null,
  };
  vm.runInNewContext(script, { document });
  assert.equal(focused, true);
  assert.equal(attributes.tabindex, "-1");
});

function selectionForm(actions, checked = []) {
  const rows = actions.map((allowed) => ({
    checked: checked.includes(allowed), dataset: { actions: allowed },
    addEventListener(event, handler) { this[event] = handler; },
  }));
  const buttons = ["approve", "reject", "hide", "restore", "delete"].map(
    (value) => ({
      value, disabled: false,
      reason: { hidden: true },
    }),
  );
  const availability = { hidden: false };
  const summary = { hidden: true };
  const count = { textContent: "0" };
  const clear = { disabled: false, addEventListener(event, handler) { this[event] = handler; } };
  const form = {
    querySelector(selector) {
      const action = selector.match(/^\[data-bulk-reason="([a-z]+)"\]$/);
      if (action) return buttons.find((button) => button.value === action[1]).reason;
      return {
        "[data-selection-summary]": summary,
        "[data-action-help]": availability,
        "[data-selection-count]": count,
        "[data-select-clear]": clear,
      }[selector] || null;
    },
    querySelectorAll(selector) { return selector.startsWith("input") ? rows : buttons; },
  };
  const master = {
    form, checked: false, indeterminate: false, focused: false,
    focus() { this.focused = true; },
    addEventListener(event, handler) { this[event] = handler; },
  };
  const document = {
    querySelectorAll: () => [],
    querySelector(selector) { return selector === "[data-select-all]" ? master : null; },
  };
  vm.runInNewContext(script, { document });
  return { rows, buttons, master, summary, count, clear, availability, enabled: () => buttons.filter((b) => !b.disabled).map((b) => b.value) };
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

test("selection count and clear reset partial or full selection without submission", () => {
  const ui = selectionForm(["approve reject delete", "hide delete"]);
  assert.equal(ui.summary.hidden, false);
  assert.equal(ui.count.textContent, "0");
  assert.equal(ui.clear.disabled, true);
  assert.equal(ui.master.focused, false);
  ui.rows[0].checked = true;
  ui.rows[0].change();
  assert.equal(ui.count.textContent, "1");
  assert.equal(ui.clear.disabled, false);
  ui.master.checked = true;
  ui.master.change();
  assert.equal(ui.count.textContent, "2");
  ui.clear.click();
  assert.equal(ui.rows.some((row) => row.checked), false);
  assert.equal(ui.count.textContent, "0");
  assert.equal(ui.master.checked, false);
  assert.equal(ui.master.indeterminate, false);
  assert.equal(ui.master.focused, true);
  assert.deepEqual(ui.enabled(), []);
});

test("eligibility explanations follow the selected action intersection", () => {
  const ui = selectionForm(["approve reject delete", "hide delete"]);
  const reasons = () => ui.buttons.filter((b) => !b.reason.hidden).map((b) => b.value);
  assert.deepEqual(reasons(), []);
  ui.rows[0].checked = true;
  ui.rows[0].change();
  assert.deepEqual(reasons(), ["hide", "restore"]);
  ui.rows[1].checked = true;
  ui.rows[1].change();
  assert.deepEqual(reasons(), ["approve", "reject", "hide", "restore"]);
  assert.deepEqual(ui.enabled(), ["delete"]);
  ui.clear.click();
  assert.deepEqual(reasons(), []);
});

test("initialization reflects restored browser selection", () => {
  const ui = selectionForm(["approve reject delete", "hide delete"], ["hide delete"]);
  assert.equal(ui.count.textContent, "1");
  assert.equal(ui.master.indeterminate, true);
  assert.deepEqual(ui.enabled(), ["hide", "delete"]);
  assert.equal(ui.master.focused, false);
});

test("action guidance is available on demand and hides when selection clears", () => {
  const ui = selectionForm(["approve reject delete", "hide delete"]);
  assert.equal(ui.availability.hidden, true);
  ui.rows[0].checked = true;
  ui.rows[0].change();
  assert.equal(ui.availability.hidden, false);
  ui.clear.click();
  assert.equal(ui.availability.hidden, true);
});


function disclosureUi(inline = false, initialOpen = false) {
  const toggle = {
    hidden: true, attributes: {}, focused: false,
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(event, handler) { this[event] = handler; },
    focus() { this.focused = true; },
  };
  const close = { hidden: true, addEventListener(event, handler) { this[event] = handler; } };
  const panel = { dataset: {}, inert: false };
  const root = {
    dataset: { initialOpen: String(initialOpen) },
    classList: { add() {} },
    hasAttribute: () => inline,
    querySelector: (selector) => selector === "[data-panel-toggle]" ? toggle : panel,
    querySelectorAll: () => [close],
    addEventListener(event, handler) { this[event] = handler; },
    contains(target) { return [toggle, panel, close].includes(target); },
  };
  const listeners = {};
  const document = {
    querySelectorAll: () => [root], querySelector: () => null,
    addEventListener(event, handler) { listeners[event] = handler; },
  };
  vm.runInNewContext(script, { document });
  return { toggle, close, panel, root, listeners };
}

test("floating panels toggle, dismiss outside, and return focus on Escape", () => {
  const ui = disclosureUi();
  assert.equal(ui.toggle.hidden, false);
  assert.equal(ui.panel.inert, true);
  ui.toggle.click();
  assert.equal(ui.toggle.attributes["aria-expanded"], "true");
  assert.equal(ui.panel.inert, false);
  ui.listeners.pointerdown({ target: ui.panel });
  assert.equal(ui.panel.inert, false);
  ui.listeners.pointerdown({ target: {} });
  assert.equal(ui.panel.inert, true);
  ui.toggle.click();
  let prevented = false;
  ui.root.keydown({ key: "Escape", preventDefault() { prevented = true; } });
  assert.equal(ui.panel.inert, true);
  assert.equal(ui.toggle.focused, true);
  assert.equal(prevented, true);
});

test("applied filter panel starts open and ignores outside chooser interactions", () => {
  const ui = disclosureUi(true, true);
  assert.equal(ui.panel.inert, false);
  ui.listeners.pointerdown({ target: {} });
  assert.equal(ui.panel.inert, false);
  ui.close.click();
  assert.equal(ui.panel.inert, true);
  assert.equal(ui.toggle.focused, true);
});
