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
