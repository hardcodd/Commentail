// Contract tests for failure/replay behavior without a browser dependency.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const vm = require("node:vm");
const script = readFileSync("commentail/static/commentail/commentail.js", "utf8");

function harness(fetchImpl, next = null) {
  const listeners = {};
  const field = { name: "text", value: "Unsent draft", type: "textarea" };
  const key = { name: "key", value: "original-session-key" };
  const button = { disabled: false };
  const alert = { hidden: true, textContent: "", setAttribute() {}, getBoundingClientRect() { return {top: 20, bottom: 80}; }, focus() { this.focused = true; }, scrollIntoView() {} };
  const attributes = {};
  const block = {
    dataset: { discussion: "17", networkError: "Connection failed" },
    getAttribute: (name) => attributes[name],
    setAttribute: (name, value) => { attributes[name] = value; },
    removeAttribute: (name) => { delete attributes[name]; },
    querySelector: () => alert,
    querySelectorAll: (selector) => selector.includes("[name]") ? [field, key] : selector.startsWith("button") ? [button] : [],
    replaceWith: (value) => { block.replacement = value; },
    before: (value) => { block.announcement = value; },
  };
  const form = { action: "https://local.invalid/comments/submit/", matches: () => true, closest: () => block };
  class Data {
    constructor() { this.values = { text: field.value, key: key.value }; }
    append(name, value) { this.values[name] = value; }
  }
  const document = { readyState: "complete", createElement: () => ({setAttribute() {}, textContent: ""}), querySelectorAll: () => [], addEventListener: (name, handler) => { listeners[name] = handler; } };
  const window = { innerHeight: 800, scrollBy() {}, location: { href: "https://local.invalid/page/", origin: "https://local.invalid" }, fetch: fetchImpl, DOMParser: true, AbortController };
  const context = { document, window, fetch: fetchImpl, URL, FormData: Data, AbortController, setTimeout, clearTimeout,
    DOMParser: class { parseFromString() { return { querySelectorAll: () => next ? [next] : [] }; } } };
  vm.runInNewContext(script, context);
  const send = (submitter) => {
    const event = { target: form, submitter, prevented: false, preventDefault() { this.prevented = true; } };
    listeners.submit?.(event);
    return event;
  };
  return { listeners, field, key, block, button, alert, send };
}
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("network failure keeps draft/key, restores controls and never replays POST", async () => {
  let calls = 0;
  const h = harness(async () => { calls++; throw new Error("Disconnected"); });
  assert.equal(h.send().prevented, true);
  await settle();
  assert.equal(calls, 1);
  assert.equal(h.field.value, "Unsent draft");
  assert.equal(h.key.value, "original-session-key");
  assert.equal(h.button.disabled, false);
  assert.equal(h.alert.hidden, false);
  assert.equal(h.alert.textContent, "Connection failed");
  h.send(); await settle();
  assert.equal(calls, 2); // Only the author's explicit retry.
});

test("parallel submit is suppressed and CAPTCHA refresh sends the clicked button", async () => {
  let release, calls = 0, payload;
  const h = harness((url, options) => { calls++; payload = options.body.values; return new Promise((resolve) => { release = resolve; }); });
  h.send({ name: "refresh", value: "1" }); h.send();
  assert.equal(calls, 1);
  assert.equal(payload.refresh, "1");
  assert.equal(h.button.disabled, true);
  release({ status: 500 }); await settle();
  assert.equal(h.button.disabled, false);
});

test("unavailable fetch leaves ordinary form submission alone", () => {
  const h = harness(undefined);
  assert.equal(h.send().prevented, false);
});

test("navigation preserves the latest draft and cannot target a foreign origin", async () => {
  const newField = { name: "text", value: "" };
  const next = { dataset: { discussion: "17" }, querySelectorAll: (selector) => selector.includes("[name]") ? [newField] : [], querySelector: () => null };
  let calls = 0;
  const h = harness(async () => { calls++; return { status: 200, text: async () => "trusted HTML" }; }, next);
  const click = (href) => h.listeners.click({ button: 0, target: { closest: () => ({ href, dataset: {}, closest: () => h.block }) }, preventDefault() {} });
  click("https://foreign.invalid/"); assert.equal(calls, 0);
  click("https://local.invalid/?thread=2");
  h.field.value = "Typed while loading";
  await settle();
  assert.equal(newField.value, "Typed while loading");
  assert.equal(h.block.replacement, next);
});

test("reading navigation preserves independent main and reply drafts", async () => {
  const main = {name: "text", value: "Main draft"};
  const reply = {name: "text", value: "Reply draft"};
  const newMain = {name: "text", value: ""};
  const newReply = {name: "text", value: ""};
  const next = {dataset: {discussion: "17"}, querySelector: () => null,
    querySelectorAll: (s) => s.includes("[name]") ? (s.includes(":not(") ? [newMain] : [newReply]) : []};
  const h = harness(async () => ({status: 200, text: async () => "HTML"}), next);
  h.block.querySelectorAll = (s) => s.includes("[name]") ? (s.includes(":not(") ? [main] : [reply]) : [];
  h.listeners.click({button: 0, target: {closest: () => ({href: "https://local.invalid/?thread=2", dataset: {}, closest: () => h.block})}, preventDefault() {}});
  await settle();
  assert.equal(newMain.value, "Main draft");
  assert.equal(newReply.value, "Reply draft");
});

test("reply submission keeps the unsent main draft after acceptance", async () => {
  const newMain = {name: "text", value: ""};
  const next = {dataset: {discussion: "17"}, querySelector: () => null,
    querySelectorAll: (s) => s.includes("[name]") ? [newMain] : []};
  const h = harness(async () => ({status: 200, text: async () => "HTML"}), next);
  h.listeners.submit({target: {dataset: {replyTo: "7"}, action: "https://local.invalid/comments/submit/", matches: () => true, closest: () => h.block}, preventDefault() {}});
  await settle();
  assert.equal(newMain.value, "Unsent draft");
});

test("pagination cannot reopen a cancelled reply from a stale rendered URL", async () => {
  let destination;
  const h = harness(async (url) => {destination = url; return {status: 500};});
  h.block.querySelector = (s) => s === ".commentail-network-error" ? h.alert : null;
  h.listeners.click({button: 0, target: {closest: () => ({href: "https://local.invalid/?thread=2&reply_to=7", dataset: {}, closest: () => h.block})}, preventDefault() {}});
  await settle();
  assert.equal(destination.searchParams.has("reply_to"), false);
  assert.equal(destination.searchParams.get("thread"), "2");
});

test("pagination after validation keeps the active reply and its target", async () => {
  let destination;
  const h = harness(async (url) => {destination = url; return {status: 500};});
  h.block.querySelector = (s) => s === ".commentail-network-error" ? h.alert : {dataset: {replyTo: "7"}};
  h.listeners.click({button: 0, target: {closest: () => ({href: "https://local.invalid/?thread=2", dataset: {}, closest: () => h.block})}, preventDefault() {}});
  await settle();
  assert.equal(destination.searchParams.get("reply_to"), "7");
  assert.equal(destination.searchParams.get("target"), "7");
  assert.equal(destination.searchParams.get("thread"), "2");
});

// Layout dimensions model the browser box contract, independently of the helper.
for (const boxSizing of ["border-box", "content-box"]) {
  test(`autoheight fits content with custom borders and padding (${boxSizing})`, () => {
    let contentHeight = 240;
    const padding = 24, borders = 6;
    const events = {};
    const field = {
      style: {},
      get scrollHeight() { return contentHeight + padding; },
      addEventListener(name, listener) { events[name] = listener; },
    };
    const document = {
      readyState: "complete",
      addEventListener() {},
      querySelectorAll: (selector) => selector === "textarea.commentail-input" ? [field] : [],
    };
    const window = {
      getComputedStyle: () => ({boxSizing, borderTopWidth: "2px", borderBottomWidth: "4px", paddingTop: "10px", paddingBottom: "14px"}),
    };
    vm.runInNewContext(script, {document, window});
    const clientHeight = () => parseFloat(field.style.height) + (boxSizing === "border-box" ? -borders : padding);
    assert.equal(clientHeight(), field.scrollHeight, "all content fits without inner scrolling");
    contentHeight = 480;
    events.input();
    assert.equal(clientHeight(), field.scrollHeight, "grows after input");
    contentHeight = 48;
    events.input();
    assert.equal(clientHeight(), field.scrollHeight, "shrinks after removing lines");
  });
}

function focusTarget() {
  return { attributes: {}, querySelector() { return null; }, append() {}, getBoundingClientRect() { return {top: 20, bottom: 80}; }, setAttribute(name, value) { this.attributes[name] = value; },
    focus() { this.focused = true; }, scrollIntoView() {} };
}

test("keyboard expansion moves focus to the first newly loaded message", async () => {
  const existing = {...focusTarget(), id: "commentail-1"};
  const added = {...focusTarget(), id: "commentail-2"};
  const next = { dataset: {discussion: "17"},
    querySelectorAll: (selector) => selector === ".commentail-comment" ? [existing, added] : [],
    querySelector: () => null };
  const h = harness(async () => ({status: 200, text: async () => "HTML"}), next);
  h.block.querySelectorAll = (selector) => selector === ".commentail-comment" ? [existing] : [];
  h.listeners.click({button: 0, target: {closest: () => ({href: "https://local.invalid/?thread=1", dataset: {}, closest: () => h.block})}, preventDefault() {}});
  await settle();
  assert.equal(added.focused, true);
  assert.equal(added.attributes.tabindex, "-1");
});

test("server error receives focus before the requested textarea", async () => {
  const error = focusTarget(), field = focusTarget();
  const next = {dataset: {discussion: "17"}, querySelectorAll: () => [],
    querySelector: (selector) => selector.includes('role="alert"') ? error : field};
  const h = harness(async () => ({status: 400, text: async () => "HTML"}), next);
  h.send(); await settle();
  assert.equal(error.focused, true);
  assert.equal(field.focused, undefined);
});

test("CAPTCHA refresh focuses its answer while keeping the draft", async () => {
  const answer = focusTarget();
  const next = {dataset: {discussion: "17"}, querySelectorAll: () => [],
    querySelector: (selector) => selector.includes('name="answer"') ? answer : null};
  const h = harness(async () => ({status: 200, text: async () => "HTML"}), next);
  h.send({name: "refresh", value: "1"}); await settle();
  assert.equal(answer.focused, true);
});

test("network error receives keyboard focus without losing the draft", async () => {
  const h = harness(async () => {throw new Error("Disconnected");});
  h.send(); await settle();
  assert.equal(h.alert.focused, true);
  assert.equal(h.field.value, "Unsent draft");
});

test("accepted submission focuses its private status instead of an empty form", async () => {
  const accepted = {...focusTarget(), id: "commentail-private-99"};
  const field = focusTarget();
  const next = {dataset: {discussion: "17"},
    querySelectorAll: (selector) => selector === ".commentail-pending" ? [accepted] : [],
    querySelector: (selector) => selector.includes('name="text"') ? field : null};
  const h = harness(async () => ({status: 200, text: async () => "HTML"}), next);
  h.send(); await settle();
  assert.equal(accepted.focused, true);
  assert.equal(field.focused, undefined);
});

test("accepted message exposes its author and outcome as the focused article name", async () => {
  const accepted = {...focusTarget(), id: "commentail-private-99",
    querySelector: (selector) => selector === "strong" ? {textContent: "Alex"}
      : selector === ".commentail-status" ? {textContent: "Awaiting moderation"} : null};
  const next = {dataset: {discussion: "17", publishedLabel: "Published"},
    querySelectorAll: (selector) => selector === ".commentail-pending" ? [accepted] : [],
    querySelector: () => null};
  const h = harness(async () => ({status: 200, text: async () => "HTML"}), next);
  h.send(); await settle();
  assert.equal(accepted.focused, true);
  assert.equal(accepted.attributes["aria-label"], "Alex. Awaiting moderation");
  assert.equal(h.block.announcement.textContent, "Alex. Awaiting moderation");
});

test("published submission announces publication without a visible status badge", async () => {
  const accepted = {...focusTarget(), id: "commentail-99",
    querySelector: (selector) => selector === "strong" ? {textContent: "Alex"} : null};
  const next = {dataset: {discussion: "17", publishedLabel: "Published"},
    querySelectorAll: () => [],
    querySelector: (selector) => selector === "#commentail-99" ? accepted : null};
  const h = harness(async () => ({status: 200, url: "https://local.invalid/?target=99", text: async () => "HTML"}), next);
  h.send(); await settle();
  assert.equal(h.block.announcement.textContent, "Alex. Published");
  assert.equal(accepted.focused, true);
});


test("accepted message keeps focus instead of the section-level email notice", async () => {
  const notice = focusTarget(), accepted = {...focusTarget(), id: "commentail-private-99"};
  const next = {dataset: {discussion: "17"},
    querySelectorAll: (selector) => selector === ".commentail-pending" ? [accepted] : [],
    querySelector: (selector) => selector === ".commentail-mail-notice" ? notice : null};
  const h = harness(async () => ({status: 200, text: async () => "HTML"}), next);
  h.send(); await settle();
  assert.equal(notice.focused, undefined);
  assert.equal(accepted.focused, true);
});


test("submission selects the exact accepted message rather than another newly revealed reply", async () => {
  const unrelated = {...focusTarget(), id: "commentail-2"};
  const accepted = {...focusTarget(), id: "commentail-99"};
  const next = {dataset: {discussion: "17"},
    querySelectorAll: (s) => s === ".commentail-comment" ? [unrelated, accepted] : [],
    querySelector: (s) => s === "#commentail-99" ? accepted : null};
  const h = harness(async () => ({status: 200, url: "https://local.invalid/page/?target=99", text: async () => "HTML"}), next);
  h.send(); await settle();
  assert.equal(accepted.focused, true);
  assert.equal(unrelated.focused, undefined);
});


test("updates retain all expanded thread windows and the loaded root window", async () => {
  let destination;
  const h = harness(async (url) => {destination = url; return {status: 500};});
  h.block.dataset.window = "signed-roots";
  const original = h.block.querySelectorAll;
  h.block.querySelectorAll = (s) => s === ".commentail-replies[data-open]"
    ? [{dataset: {thread: "7", window: "signed-seven"}}, {dataset: {thread: "8", window: "signed-eight"}}] : original(s);
  h.send(); await settle();
  assert.deepEqual(destination.searchParams.getAll("thread"), ["7", "8"]);
  assert.deepEqual(destination.searchParams.getAll("replies"), ["signed-seven", "signed-eight"]);
  assert.equal(destination.searchParams.get("window"), "signed-roots");
});

test("visible accepted messages receive focus without scrolling to the section", async () => {
  const accepted = {...focusTarget(), id: "commentail-99"};
  let scrolls = 0, options;
  accepted.focus = (value) => { options = value; };
  accepted.scrollIntoView = () => {scrolls++;};
  const next = {dataset: {discussion: "17"}, querySelectorAll: () => [],
    querySelector: (s) => s === "#commentail-99" ? accepted : null};
  const h = harness(async () => ({status: 200, url: "https://local.invalid/?target=99", text: async () => "HTML"}), next);
  h.send(); await settle();
  assert.equal(options.preventScroll, true);
  assert.equal(scrolls, 0);
});


test("expansion ignores an inherited target and reveals the newly loaded reply", async () => {
  const previous = {...focusTarget(), id: "commentail-99"};
  const added = {...focusTarget(), id: "commentail-2"};
  const next = {dataset: {discussion: "17"},
    querySelectorAll: (s) => s === ".commentail-comment" ? [previous, added] : [],
    querySelector: (s) => s === "#commentail-99" ? previous : null};
  const h = harness(async () => ({status: 200, text: async () => "HTML"}), next);
  h.block.querySelectorAll = (s) => s === ".commentail-comment" ? [previous] : [];
  h.listeners.click({button: 0, target: {closest: () => ({href: "https://local.invalid/?thread=2&target=99#commentail", dataset: {}, closest: () => h.block})}, preventDefault() {}});
  await settle();
  assert.equal(added.focused, true);
  assert.equal(previous.focused, undefined);
});

test("opening an inline edit focuses its own textarea and preserves the main draft", async () => {
  const editField = {...focusTarget(), value: "Original comment"};
  const main = {name: "text", value: ""};
  const editor = {dataset: {editComment: "7"}, querySelector: () => editField};
  const next = {dataset: {discussion: "17"},
    querySelectorAll: (s) => s.includes(":not(") && s.includes("[name]") ? [main] : [],
    querySelector: (s) => s === ".commentail-edit-form" ? editor : null};
  const h = harness(async () => ({status: 200, text: async () => "HTML"}), next);
  h.block.querySelector = (s) => s === ".commentail-network-error" ? h.alert : null;
  h.listeners.click({button: 0, target: {closest: () => ({href: "https://local.invalid/?edit_comment=7&target=7#commentail-7", dataset: {commentailEdit: "7", commentailFocus: "text"}, closest: () => h.block})}, preventDefault() {}});
  await settle();
  assert.equal(editField.focused, true);
  assert.equal(editField.value, "Original comment");
  assert.equal(main.value, "Unsent draft");
});

test("edit cancellation removes its editor locally and returns focus to Edit", () => {
  const trigger = focusTarget();
  let removed = false, calls = 0;
  const article = {...focusTarget(), id: "commentail-7"};
  const editor = {remove() {removed = true;}, closest: () => article};
  const link = {href: "https://local.invalid/?target=7#commentail-7", dataset: {commentailEditCancel: ""},
    closest: (s) => s === ".commentail-editor" ? editor : s === ".commentail-comment" ? article : h.block};
  const h = harness(async () => {calls++; return {status: 500};});
  h.block.querySelector = (s) => s.includes("data-commentail-edit=") ? trigger : s === "#commentail-7" ? article : null;
  h.listeners.click({button: 0, target: {closest: () => link}, preventDefault() {}});
  assert.equal(removed, true);
  assert.equal(calls, 0);
  assert.equal(trigger.focused, true);
});

test("saving an edit keeps the independent reply composer in the navigation", async () => {
  let destination;
  const h = harness(async (url) => {destination = url; return {status: 500};});
  h.block.querySelector = (s) => s === ".commentail-network-error" ? h.alert
    : s === ".commentail-form[data-reply-to]" ? {dataset: {replyTo: "8"}} : null;
  h.listeners.submit({target: {dataset: {editComment: "7"}, action: "https://local.invalid/comments/7/edit/", matches: () => true, closest: () => h.block}, preventDefault() {}});
  await settle();
  assert.equal(destination.searchParams.get("reply_to"), "8");
});

test("Escape closes the author disclosure and restores its trigger focus", () => {
  const h = harness(undefined);
  // No progressive fetch: native disclosures still get keyboard dismissal.
  const summary = focusTarget();
  let closed = false;
  const menu = {removeAttribute(name) {if (name === "open") closed = true;}, querySelector: () => summary};
  h.listeners.keydown?.({key: "Escape", target: {closest: () => menu}, preventDefault() {}});
  assert.equal(closed, true);
  assert.equal(summary.focused, true);
});
