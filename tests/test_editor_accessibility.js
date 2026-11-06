/* Keyboard and announcement contracts for the shipped controller. Native focus
 * and spoken output are additionally checked in the local browser. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({ URL, structuredClone, performance,
  document: { documentElement: { lang: 'en' } }, addEventListener() {} });
vm.runInContext(fs.readFileSync('commentail/static/commentail/editor.js', 'utf8'), context);
const prototype = context.CommentailVisualEditor.Editor.prototype;
function toolbar() {
  const doc = { activeElement: null };
  const buttons = Array.from({ length: 5 }, (_, index) => ({
    disabled: index === 1, hidden: index === 2, tabIndex: 0,
    closest() { return this.hidden ? {} : null; },
    focus() { doc.activeElement = this; },
  }));
  const editor = Object.create(prototype);
  Object.assign(editor, { root: { ownerDocument: doc },
    toolbar: { querySelectorAll() { return buttons; } } });
  return { editor, buttons, doc };
}
function key(key, extras = {}) {
  return { key, preventDefault() { this.prevented = true; }, ...extras };
}
test('toolbar has one tab stop; arrows wrap and skip disabled/hidden controls', () => {
  const { editor, buttons, doc } = toolbar();
  editor.updateToolbarTabstop();
  assert.deepEqual(buttons.map(button => button.tabIndex), [0, -1, -1, -1, -1]);
  buttons[0].focus();
  editor.toolbarKey(key('ArrowRight'));
  assert.equal(doc.activeElement, buttons[3]);
  editor.toolbarKey(key('End')); assert.equal(doc.activeElement, buttons[4]);
  editor.toolbarKey(key('ArrowRight')); assert.equal(doc.activeElement, buttons[0]);
  editor.toolbarKey(key('ArrowLeft')); assert.equal(doc.activeElement, buttons[4]);
  editor.toolbarKey(key('Home')); assert.equal(doc.activeElement, buttons[0]);
  const tab = key('Tab'); editor.toolbarKey(tab); assert.ok(!tab.prevented);
  const modified = key('ArrowRight', { altKey: true }); editor.toolbarKey(modified);
  assert.equal(doc.activeElement, buttons[0]);
});
test('toolbar remembers last control and recovers when it becomes unavailable', () => {
  const { editor, buttons } = toolbar();
  editor.toolbarButton = buttons[3]; editor.updateToolbarTabstop();
  assert.equal(buttons[3].tabIndex, 0);
  buttons[3].disabled = true; editor.updateToolbarTabstop();
  assert.equal(buttons[0].tabIndex, 0);
  buttons.forEach(button => { button.disabled = true; });
  editor.updateToolbarTabstop();
  assert.ok(buttons.every(button => button.tabIndex === -1));
});
test('Alt+F10 reaches toolbar; Escape restores editor selection; composition is untouched', () => {
  const { editor, buttons, doc } = toolbar();
  Object.assign(editor, { mode: 'visual', composing: false, capture() { this.captured = true; },
    restoreSelection() { this.restored = true; } });
  const shortcut = key('F10', { altKey: true }); editor.key(shortcut);
  assert.ok(shortcut.prevented); assert.ok(editor.captured);
  assert.equal(doc.activeElement, buttons[0]);
  editor.toolbarKey(key('Escape')); assert.ok(editor.restored);
  editor.composing = true; const ime = key('F10', { altKey: true }); editor.key(ime);
  assert.ok(!ime.prevented);
});
test('identical status messages do not mutate the live region repeatedly', () => {
  let writes = 0, value = '';
  const editor = Object.create(prototype);
  editor.status = { get textContent() { return value; }, set textContent(text) { value = text; writes++; } };
  editor.message('changed'); editor.message('changed'); editor.message('error');
  assert.equal(writes, 2);
});
test('Alt+Shift+T reaches the toolbar without function keys or Latin-layout dependence', () => {
  for (const mode of ['visual', 'source']) {
    const { editor, buttons, doc } = toolbar();
    Object.assign(editor, { mode, capture() {}, restoreSelection() {} });
    // Option and non-Latin layouts can change key while preserving code.
    const shortcut = key('ˇ', { code: 'KeyT', altKey: true, shiftKey: true });
    editor.key(shortcut);
    assert.ok(shortcut.prevented);
    assert.equal(doc.activeElement, buttons[0]);
    editor.composing = true;
    const ime = key('T', { code: 'KeyT', altKey: true, shiftKey: true });
    editor.key(ime); assert.ok(!ime.prevented);
  }
});
test('Escape then Tab exits a list without changing indentation', () => {
  const editor = Object.create(prototype);
  Object.assign(editor, { mode: 'visual', rows: [{ depth: 1 }], range: { start: { row: 0 } },
    capture() {}, message() {}, command() { throw new Error('must not indent'); } });
  editor.key(key('Escape'));
  const tab = key('Tab'); editor.key(tab); assert.ok(!tab.prevented);
});
test('validation marks both surfaces, focuses the active one and clears after correction', () => {
  const editor = Object.create(prototype);
  const field = () => ({ attributes: {}, setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; }, focus() { this.focused = true; } });
  Object.assign(editor, { root: field(), source: field(), mode: 'visual', status: { textContent: '' } });
  editor.setInvalid('Enter your comment.'); editor.focus();
  assert.equal(editor.root.attributes['aria-invalid'], 'true');
  assert.equal(editor.source.attributes['aria-invalid'], 'true');
  assert.ok(editor.root.focused); assert.ok(!editor.source.focused);
  editor.mode = 'source'; editor.focus(); assert.ok(editor.source.focused);
  editor.clearInvalid();
  assert.equal(editor.root.attributes['aria-invalid'], undefined);
  assert.equal(editor.source.attributes['aria-invalid'], undefined);
});

test('validation announces each failed submit separately from polite status and clears on correction', () => {
  const editor = Object.create(prototype);
  let writes = 0, text = '';
  const error = { get textContent() { return text; }, set textContent(value) { text = value; writes++; } };
  const field = () => ({ setAttribute() {}, removeAttribute() {} });
  Object.assign(editor, { root: field(), source: field(), error, status: { textContent: 'Ready.' } });
  editor.setInvalid('Enter your comment.');
  assert.equal(error.textContent, 'Enter your comment.');
  assert.equal(editor.status.textContent, '');
  editor.setInvalid('Enter your comment.');
  assert.equal(writes, 2, 'a new submit must update the alert even for the same error');
  editor.clearInvalid();
  editor.message('Changes saved in memory.');
  assert.equal(error.textContent, '');
  assert.equal(editor.status.textContent, 'Changes saved in memory.');
});

// Exercise the actual adapter independently of the controller's model tests.
function mountedForms() {
  const editors = [];
  function element(tagName) {
    return { tagName, attributes: {}, dataset: {}, childNodes: [],
      setAttribute(name, value) { this.attributes[name] = value; },
      getAttribute(name) { return this.attributes[name] ?? null; },
      append(...nodes) { this.childNodes.push(...nodes); }, replaceWith() {}, before(node) { this.previous = node; },
      remove() { this.removed = true; }, addEventListener() {} };
  }
  function container() {
    const source = Object.assign(element(), { value: '', required: true, form: element() });
    source.setAttribute('aria-describedby', 'length');
    const shortcut = element(), tip = Object.assign(element(), { querySelector() { return shortcut; } });
    const button = element(), tool = { querySelector(selector) { return selector === '.tooltip' ? tip : button; }, addEventListener() {} };
    const dialogFields = Object.fromEntries(['h2', '.dialog-hint', '[data-link-error]', '[name="href"]', '[name="label"]', '[data-link-form]'].map(name => [name, element()]));
    const dialog = { querySelector(selector) { return dialogFields[selector]; }, setAttribute() {} };
    const status = element(), root = element(), topbar = element();
    const fields = { 'textarea[name="text"]': source, '.editor-topbar': topbar,
      '[data-editor-dialog]': { content: { firstElementChild: { cloneNode() { return dialog; } } } },
      '[data-editor-root]': root, '[data-editor-toolbar]': element(), '[data-editor-mode]': element(), '[data-editor-status]': status };
    return { isConnected: true, dataset: { editorSettings: '{"guest":"visual"}' },
      querySelector(selector) { return fields[selector]; }, querySelectorAll() { return [tool]; }, addEventListener() {},
      source, root, status, button, shortcut, dialogFields };
  }
  const nodes = [container(), container()];
  const doc = { body: element(), createElement: element, activeElement: null };
  const adapter = vm.createContext({ document: doc, addEventListener() {}, translate: text => text, translateChrome() {},
    CommentailVisualEditor: { Editor: class {
      constructor(options) { Object.assign(this, options, { mode: 'visual', controller: { signal: {} } }); editors.push(this); }
      updateButtons() {} clearInvalid() { this.invalid = false; }
      destroy() { this.destroyed = true; }
      setInvalid(message) { this.invalid = message; } focus() { this.focuses = (this.focuses ?? 0) + 1; }
      getDraft() { return 'draft'; } getContent() { if (this.error) throw new Error(this.error); return { text: 'valid' }; }
    } }, CommentailLinkDialog: { LinkDialog: class {} }, CommentailURLPaste: { URLPaste: class {} } });
  vm.runInContext(fs.readFileSync('frontend/editor/mount.js', 'utf8'), adapter);
  const forms = { querySelectorAll() { return nodes; } };
  adapter.CommentailEditors.mount(forms);
  return { adapter, forms, nodes, editors };
}
test('mount associates unique help/errors, preserves required semantics and avoids duplicate tooltip names', () => {
  const { nodes, editors } = mountedForms();
  for (const [index, node] of nodes.entries()) {
    assert.equal(node.root.attributes['aria-required'], 'true');
    assert.equal(node.source.required, false);
    assert.equal(node.source.attributes['aria-describedby'], node.root.attributes['aria-describedby']);
    const error = editors[index].error;
    assert.ok(error, 'validation needs an existing region independent of polite status');
    assert.equal(error.attributes.role, undefined, 'mounting an empty composer must not create an alert event');
    assert.equal(error.attributes['aria-live'], 'assertive');
    assert.equal(error.attributes['aria-atomic'], 'true');
    assert.equal(node.root.attributes['aria-describedby'].split(' ')[0], error.id);
    const address = node.dialogFields['[name="href"]'];
    assert.equal(address.attributes['aria-describedby'].split(' ')[0], node.dialogFields['[data-link-error]'].id);
    const disclosure = node.status.previous;
    assert.equal(disclosure.tagName, 'details');
    assert.ok(!disclosure.open, 'lengthy help must start collapsed');
    assert.equal(disclosure.childNodes[0].tagName, 'summary');
    const help = disclosure.childNodes[1];
    assert.ok(help.textContent.includes('Escape then Tab'));
    assert.ok(node.root.attributes['aria-describedby'].split(' ').includes(help.id));
    assert.equal(node.button.attributes['aria-describedby'], node.shortcut.id);
  }
  assert.notEqual(nodes[0].status.id, nodes[1].status.id);
  assert.notEqual(editors[0].error.id, editors[1].error.id);
});
test('removing one composer releases only its own validation alert', () => {
  const { adapter, nodes, editors } = mountedForms();
  adapter.CommentailEditors.destroy({ querySelectorAll() { return [nodes[1]]; } });
  assert.ok(editors[1].destroyed);
  assert.ok(editors[1].error.removed);
  assert.ok(!editors[0].destroyed);
  assert.ok(!editors[0].error.removed);
});
test('submission focuses only the first invalid instance; draft synchronization never steals focus', () => {
  const { adapter, forms, editors } = mountedForms();
  editors.forEach(editor => { editor.error = 'invalid'; });
  assert.equal(adapter.CommentailEditors.sync(forms, true), false);
  assert.equal(editors[0].focuses, 1); assert.equal(editors[1].focuses, undefined);
  editors.forEach(editor => { delete editor.error; });
  assert.equal(adapter.CommentailEditors.sync(forms, true), true);
  assert.ok(editors.every(editor => !editor.invalid && editor.source.value === 'valid'));
  assert.equal(adapter.CommentailEditors.sync(forms), true);
  assert.equal(editors[0].focuses, 1);
});

test('successful mode switches are quiet while rejected imports retain an explanation', () => {
  for (const initial of ['', 'A comment']) {
    const editor = Object.create(prototype);
    Object.assign(editor, { policy: context.CommentailEditorPolicy.forAudience({guest:'visual'}, 'guest'),
      mode:'visual', rows:context.CommentailEditorModel.fromMarkdown(initial), sourceText:initial,
      source:{value:initial, focus() {}}, status:{textContent:'Earlier message'},
      range:{start:{row:0,offset:0},end:{row:0,offset:0}},
      capture() {}, snapshot() {return {};}, record() {}, render() {}, clearInvalid() {}, restoreSelection() {}, updateButtons() {} });
    assert.equal(editor.toggleMode(), true);
    assert.equal(editor.status.textContent, '');
    assert.equal(editor.source.value, initial);
    assert.equal(editor.toggleMode(), true);
    assert.equal(editor.status.textContent, '');
    assert.equal(editor.toggleMode(), true);
    editor.source.value = '```python\nprint(1)\n```';
    assert.equal(editor.toggleMode(), false);
    assert.equal(editor.mode, 'source');
    assert.ok(editor.status.textContent.length > 0);
  }
});

test('initial editor mount is quiet in every mode and still explains rejected imports', () => {
  context.AbortController = AbortController;
  class InitialEditor extends context.CommentailVisualEditor.Editor {
    render() {} listen() {}
  }
  for (const mode of ['visual', 'markdown', 'plain']) {
    for (const initial of ['', 'Existing comment']) {
      const status = {textContent:''};
      new InitialEditor({root:{ownerDocument:{}},source:{},status,initial,settings:{guest:mode}});
      assert.equal(status.textContent, '');
    }
  }
  const status = {textContent:''};
  new InitialEditor({root:{ownerDocument:{}},source:{},status,initial:'```python\nprint(1)\n```',settings:{guest:'visual'}});
  assert.ok(status.textContent.length > 0);
});
