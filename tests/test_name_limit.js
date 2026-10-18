const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const vm = require("node:vm");
const script = readFileSync("commentail/static/commentail/commentail.js", "utf8");

function fieldHarness(intl = Intl) {
  const handlers = {};
  const field = {
    value: "",
    dataset: { commentailNameLimit: "40", commentailNameError: "Too long" },
    addEventListener(name, handler) { handlers[name] = handler; },
    setCustomValidity(value) { this.error = value; },
  };
  const document = {
    readyState: "complete", addEventListener() {},
    querySelectorAll(selector) { return selector === "input[data-commentail-name-limit]" ? [field] : []; },
  };
  vm.runInNewContext(script, { document, window: {}, Intl: intl });
  return { field, handlers };
}

test("name limit accepts full names and 40 graphemes, rejects 41 and clears error", () => {
  const { field, handlers } = fieldHarness();
  for (const name of ["Александр Константиновский", " é".trim().repeat(40), "👍🏽".repeat(40)]) {
    field.value = ` ${name} `;
    handlers.input();
    assert.equal(field.error, "");
  }
  field.value = "é".repeat(41);
  handlers.input();
  assert.equal(field.error, "Too long");
  field.value = "Анна Иванова";
  handlers.input();
  assert.equal(field.error, "");
});

test("missing Segmenter leaves server fallback usable", () => {
  const { handlers } = fieldHarness({});
  assert.equal(handlers.input, undefined);
});
