// Observable placement/cancellation contracts without adding a DOM dependency.
const {test} = require("node:test");
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const vm = require("node:vm");
const script = readFileSync("commentail/static/commentail/commentail.js", "utf8");

function composerHarness() {
  const listeners = {}, children = [], main = {querySelectorAll: () => []};
  const field = {focus() {this.focused = true;}};
  const trigger = {focus(options) {this.focused = true; this.focusOptions = options;},
    getBoundingClientRect() {return {top: 100, bottom: 120};},
    scrollIntoView() {this.scrolled = true;}};
  const content = {append(form) {children.push(form);}};
  const form = {
    dataset: {replyTo: "7"}, classList: {add() {}},
    before(node) {block.main = node;},
    prepend() {},
    querySelector: (s) => s.includes('name="text"') ? field : null,
    querySelectorAll: () => [],
    closest() {return null;},
    remove() {children.splice(children.indexOf(form), 1);},
  };
  const template = {content: {firstElementChild: {cloneNode: () => main}}};
  const block = {
    dataset: {discussion: "17"},
    querySelector(s) {
      if (s === ".commentail-form[data-reply-to]") return form;
      if (s === ".commentail-main-template") return template;
      if (s.includes(".commentail-content")) return content;
      if (s.includes("data-commentail-reply")) return trigger;
      return null;
    },
    querySelectorAll() {return [];},
    getAttribute() {return null;},
  };
  const cancel = {href: "https://local.invalid/page/", dataset: {commentailCancel: ""},
    closest(s) {return s === ".commentail-reply-form" ? form : block;}};
  const document = {readyState: "complete", querySelectorAll: (s) => s === ".commentail[data-discussion]" ? [block] : [],
    addEventListener(name, handler) {listeners[name] = handler;}};
  const window = {innerHeight: 800, location: {href: "https://local.invalid/page/", origin: "https://local.invalid"},
    fetch() {throw new Error("Cancel must not fetch");}, DOMParser: true, AbortController};
  vm.runInNewContext(script, {document, window, URL, AbortController});
  return {block, main, form, field, trigger, children, cancel, listeners};
}

test("reply composer is mounted under its addressee; main form stays separate", () => {
  const h = composerHarness();
  assert.equal(h.block.main, h.main);
  assert.deepEqual(h.children, [h.form]);
});

test("cancel removes the inline composer from DOM and returns keyboard focus", () => {
  const h = composerHarness();
  h.listeners.click({button: 0, target: {closest: () => h.cancel}, preventDefault() {}});
  assert.equal(h.children.length, 0);
  assert.equal(h.trigger.focused, true);
  assert.equal(h.trigger.focusOptions.preventScroll, true);
  assert.equal(h.trigger.scrolled, undefined);
  assert.equal(h.block.main, h.main);
});
