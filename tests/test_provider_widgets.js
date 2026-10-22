const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const vm = require("node:vm");

const source = readFileSync("commentail/static/commentail/commentail.js", "utf8")
  .replace("  const start = () => {", "  window.testCaptchas = { mountCaptchas, releaseCaptchas };\n  const start = () => {");
const settle = () => new Promise((resolve) => setImmediate(resolve));

function harness() {
  const scripts = [];
  const window = {};
  const document = {
    readyState: "loading", addEventListener() {},
    createElement: () => ({ remove() { this.removed = true; } }),
    head: { append: (script) => scripts.push(script) },
  };
  vm.runInNewContext(source, { window, document, setTimeout, clearTimeout });
  return { window, scripts, ...window.testCaptchas };
}

function node(provider = "google") {
  const answer = { value: "" };
  const status = { textContent: "Complete the check" };
  const retry = { hidden: true };
  return {
    answer, status, retry, isConnected: true,
    dataset: { commentailProvider: provider, sitekey: "public", error: "Unavailable" },
    querySelector: (selector) => selector.includes("answer") ? answer : selector.includes("status") ? status : selector.includes("retry") ? retry : {},
  };
}
const root = (...nodes) => ({ querySelectorAll: () => nodes });

test("provider scripts are opt-in and loaded once for independent forms", async () => {
  const h = harness();
  h.mountCaptchas(root());
  assert.equal(h.scripts.length, 0);
  const first = node(), second = node();
  h.mountCaptchas(root(first, second));
  h.mountCaptchas(root(first));
  assert.equal(h.scripts.length, 1);
  const options = [];
  h.window.grecaptcha = { render: (element, value) => { options.push(value); return options.length; } };
  h.window.commentailGoogleCaptchaReady();
  await settle();
  assert.equal(options.length, 2);
  options[0].callback("first-token");
  assert.equal(first.answer.value, "first-token");
  assert.equal(second.answer.value, "");
  options[0]["expired-callback"]();
  assert.equal(first.answer.value, "");
  assert.equal(first.status.textContent, "Complete the check");
  assert.equal(first.retry.hidden, true);
  options[1].callback("second-token");
  options[1]["error-callback"]();
  assert.equal(second.answer.value, "");
  assert.equal(second.status.textContent, "Unavailable");
  assert.equal(second.retry.hidden, false);
  options[1].callback("recovered-token");
  assert.equal(second.retry.hidden, true);
});

test("Yandex subscribes to expiry/errors and destroys removed widgets", async () => {
  const h = harness(), item = node("yandex");
  const events = {};
  let options, destroyed;
  h.window.smartCaptcha = {
    render: (_, value) => { options = value; return 17; },
    subscribe: (_, event, callback) => { events[event] = callback; },
    destroy: (id) => { destroyed = id; },
  };
  h.mountCaptchas(root(item)); await settle();
  options.callback("token"); events["token-expired"]();
  assert.equal(item.answer.value, "");
  options.callback("token"); events["network-error"]();
  assert.equal(item.answer.value, "");
  assert.equal(item.status.textContent, "Unavailable");
  assert.equal(item.retry.hidden, false);
  events["token-expired"]();
  assert.equal(item.retry.hidden, true);
  h.releaseCaptchas(root(item));
  assert.equal(destroyed, 17);
  options.callback("late-token");
  assert.equal(item.answer.value, "");
});

test("removing a form during script loading prevents late rendering", async () => {
  const h = harness(), item = node();
  let calls = 0;
  h.mountCaptchas(root(item));
  h.releaseCaptchas(root(item));
  h.window.grecaptcha = { render: () => { calls++; } };
  h.window.commentailGoogleCaptchaReady(); await settle();
  assert.equal(calls, 0);
});

test("blocked scripts show an error and a refreshed form can retry loading", async () => {
  const h = harness(), item = node();
  h.mountCaptchas(root(item));
  h.scripts[0].onerror(); await settle();
  assert.equal(item.status.textContent, "Unavailable");
  assert.equal(item.answer.value, "");
  assert.equal(item.retry.hidden, false);
  h.releaseCaptchas(root(item));
  h.mountCaptchas(root(node()));
  assert.equal(h.scripts.length, 2);
  h.scripts[1].onerror(); await settle();
});

test("Google reset failures do not interrupt removal or preserve a live callback", async () => {
  const h = harness(), item = node();
  let options;
  h.window.grecaptcha = {
    render: (_, value) => { options = value; return 0; },
    reset: () => { throw new Error("Provider cleanup failed"); },
  };
  h.mountCaptchas(root(item)); await settle();
  h.releaseCaptchas(root(item));
  options.callback("late-token");
  assert.equal(item.answer.value, "");
});
