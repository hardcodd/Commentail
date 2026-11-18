const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('theme fallback follows host/media changes and releases observers and queued work on abort', () => {
  const callbacks = new Map(), listeners = new Map(), mediaListeners = new Map();
  let observer, disconnected = false, cancelled = false;
  const host = { colorScheme: 'dark' };
  const preference = { matches: false, addEventListener: (key, fn) => mediaListeners.set(key, fn), removeEventListener: key => mediaListeners.delete(key) };
  const view = {
    getComputedStyle: node => node === parent ? host : { getPropertyValue: name => name === '--accent' ? '#abcdef' : '' },
    matchMedia: () => preference,
    MutationObserver: class { constructor(fn) { observer = fn; } observe() {} disconnect() { disconnected = true; } },
    requestAnimationFrame(fn) { callbacks.set(1, fn); return 1; },
    cancelAnimationFrame(id) { callbacks.delete(id); cancelled = true; },
    addEventListener: (key, fn) => listeners.set(key, fn), removeEventListener: key => listeners.delete(key),
  };
  const parent = { parentElement: null };
  const node = { parentElement: parent, dataset: {}, ownerDocument: { defaultView: view, createElement: () => ({ getContext: () => null }) } };
  const copied = {};
  const owner = { dataset: {}, style: { setProperty: (key, value) => { copied[key] = value; } } };
  const controller = new AbortController();
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync('frontend/editor/theme.js', 'utf8') + '\nglobalThis.follow = CommentailEditorTheme.follow;', context);
  context.follow(node, owner, controller.signal);
  assert.equal(node.dataset.editorTheme, 'dark');
  assert.equal(owner.dataset.editorTheme, 'dark');
  assert.equal(copied['--accent'], '#abcdef');
  const mutation = [{ target: parent, attributeName: 'data-theme' }];
  host.colorScheme = 'light'; observer(mutation); observer(mutation);
  assert.equal(callbacks.size, 1, 'theme mutations coalesce');
  callbacks.get(1)(); callbacks.clear();
  assert.equal(node.dataset.editorTheme, 'light');
  observer([{ target: node, attributeName: 'data-editor-theme' }]);
  assert.equal(callbacks.size, 0, 'own output cannot create an observer loop');
  host.colorScheme = 'normal'; preference.matches = true;
  mediaListeners.get('change')(); callbacks.get(1)(); callbacks.clear();
  assert.equal(node.dataset.editorTheme, 'dark');
  listeners.get('resize')(); controller.abort();
  assert.ok(disconnected && cancelled);
  assert.equal(callbacks.size, 0);
  assert.equal(listeners.size, 0);
  assert.equal(mediaListeners.size, 0);
  assert.equal(node.dataset.editorTheme, undefined);
});
