/* Shipped model/controller contracts without browser HTML or external packages. */
const test = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const c = vm.createContext({ URL, structuredClone, performance,
  document: { documentElement: { lang: 'en' } }, addEventListener() {} });
vm.runInContext(readFileSync('commentail/static/commentail/editor.js', 'utf8'), c);
const M = c.CommentailEditorModel, P = c.CommentailEditorPolicy, S = c.CommentailEditorShortcuts;
const policy = P.forAudience(P.configure({ guest: 'visual' }), 'guest');
const range = offset => ({ start: { row: 0, offset }, end: { row: 0, offset } });
const apply = (text, typed = text.at(-1), rules = policy) => S.apply([M.row(text)], range(text.length), typed, rules);

test('supported inline markers, Unicode and typed links convert losslessly', () => {
  for (const source of ['**жирный**', '__bold__', '*italic*', '_italic_', '~~strike~~', '***both***',
    '~~**both**~~', '`**literal**`', '[label](https://example.com/a)', '**👨‍👩‍👧‍👦**']) {
    const result = apply(source);
    assert.ok(result, source);
    assert.equal(M.signature(result.rows), M.signature(M.fromMarkdown(source)), source);
    assert.equal(result.point.offset, result.rows[0].text.length);
    assert.equal(M.signature(M.fromMarkdown(M.toCommentMarkdown(result.rows))), M.signature(result.rows));
  }
});

test('block prefixes and fence Enter produce the requested structure', () => {
  for (const [source, trigger, kind, number] of [['- ', ' ', 'ul', 1], ['* ', ' ', 'ul', 1],
    ['+ ', ' ', 'ul', 1], ['1. ', ' ', 'ol', 1], ['42) ', ' ', 'ol', 42],
    ['0. ', ' ', 'ol', 0], ['> ', ' ', 'quote', 1], ['```', '\n', 'pre', 1], ['~~~', '\n', 'pre', 1]]) {
    const result = apply(source, trigger);
    assert.ok(result, source); assert.equal(result.rows[0].kind, kind);
    assert.equal(result.rows[0].start, number); assert.equal(result.rows[0].text, '');
  }
});

test('literal examples, escaping, incomplete syntax and intraword underscores stay text', () => {
  for (const source of ['plain', '**unfinished*', '\\**bold**', 'word_italic_', '\\*italic*',
    '~~ ~~', '[]()', '[x](javascript:alert(1))', '--- ', '1000000000. ', '## ', '``', '`a\nb`']) {
    assert.equal(apply(source), null, source);
  }
});

test('disabled features stay literal, including nested combinations and plain mode', () => {
  for (const [source, feature] of [['**bold**', 'bold'], ['*italic*', 'italic'], ['~~s~~', 'strike'],
    ['~~**s**~~', 'bold'], ['[x](https://example.com)', 'link'], ['`x`', 'inlineCode'],
    ['- ', 'unorderedList'], ['4. ', 'orderedList'], ['> ', 'quote'], ['```', 'codeBlock']]) {
    const rules = P.forAudience(P.configure({ guest: 'visual', features: P.FEATURES.filter(name => name !== feature) }), 'guest');
    assert.equal(apply(source, source === '```' ? '\n' : source.at(-1), rules), null, source);
  }
  assert.equal(apply('**x**', '*', { ...policy, mode: 'plain' }), null);
});

test('code, links, styled markers, noncollapsed ranges and search bounds exclude conversion', () => {
  const text = '**bold**';
  for (const rows of [[M.row(text, 'pre')], [M.row(text, 'p', 0, 1, Array(text.length).fill(M.CODE))],
    [M.row(text, 'p', 0, 1, Array(text.length).fill(M.BOLD))],
    M.applyLink([M.row(text)], { start: { row: 0, offset: 0 }, end: { row: 0, offset: text.length } }, 'https://example.com').rows]) {
    assert.equal(S.apply(rows, range(text.length), '*', policy), null);
  }
  assert.equal(S.apply([M.row(text)], { start: {row:0,offset:0}, end:{row:0,offset:text.length} }, '*', policy), null);
  assert.equal(apply('**' + 'x'.repeat(513) + '**'), null);
});

test('inline conversion preserves preceding text, subsequent text, links and their offsets', () => {
  const rows = M.fromMarkdown('[before](https://example.com) plain');
  const inserted = M.replace(rows, range(rows[0].text.length), ' ~~new~~ suffix');
  const offset = inserted.rows[0].text.indexOf(' suffix');
  const before = JSON.stringify(inserted.rows);
  const result = S.apply(inserted.rows, range(offset), '~', policy);
  assert.ok(result); assert.equal(result.rows[0].text, 'before plain new suffix');
  assert.equal(result.rows[0].links[0].href, 'https://example.com/');
  assert.equal(JSON.stringify(inserted.rows), before);
});

test('strikethrough combinations roundtrip or reject explicitly without model mutation', () => {
  const bits = [0, 1, 2, 3, 8, 9, 10, 11];
  let accepted = 0;
  for (const a of bits) for (const b of bits) for (const d of bits) {
    const rows = [M.row('a b', 'p', 0, 1, [a, b, d])];
    const before = JSON.stringify(rows);
    try {
      const source = M.toMarkdown(rows);
      assert.equal(M.signature(M.fromMarkdown(source)), M.signature(rows)); accepted++;
    } catch (error) { assert.ok(error instanceof M.EditorError, error); }
    assert.equal(JSON.stringify(rows), before);
  }
  assert.ok(accepted > 400);
  const rows = M.fromMarkdown('> ~~old **bold**~~\n\n1. ~~item~~\n\n`~~literal~~`');
  assert.equal(M.signature(M.fromMarkdown(M.toMarkdown(rows))), M.signature(rows));
});

function controller() {
  const editor = Object.create(c.CommentailVisualEditor.Editor.prototype);
  Object.assign(editor, { rows: [M.row()], range: range(0), pending: null,
    mode: 'visual', policy, dirty: false, sourceText: '', visualSource: '',
    past: [], future: [], lastEdit: null, composing: false, destroyed: false,
    source: { value: '', selectionStart: 0, selectionEnd: 0, selectionDirection: 'none' },
    capture() {}, render() {}, restoreSelection() {}, updateButtons() {}, message() {} });
  return editor;
}

test('real controller typing and undo restore markers, redo restores formatting', () => {
  for (const text of ['**bold**', '~~strike~~', '`literal`', '- ', '> ', '[x](https://example.com)']) {
    const editor = controller();
    for (const data of text) editor.beforeInput({ inputType: 'insertText', data, cancelable: true, preventDefault() {} });
    assert.notEqual(editor.rows[0].text, text);
    const converted = M.signature(editor.rows);
    assert.ok(editor.history()); assert.equal(editor.rows[0].text, text);
    assert.ok(editor.rows[0].marks.every(mark => !mark));
    assert.ok(editor.history(true)); assert.equal(M.signature(editor.rows), converted);
    editor.beforeInput({inputType:'insertText',data:' ',cancelable:true,preventDefault(){}});
    assert.equal(editor.rows[0].marks.at(-1), 0);
  }
});

test('paste, replacement input, selected replacements and composition do not apply shortcuts', () => {
  const pasted = controller(); pasted.insert('**literal**', 'paste');
  assert.equal(pasted.rows[0].text, '**literal**'); assert.ok(pasted.rows[0].marks.every(mark => !mark));
  const replacement = controller(); replacement.rows = [M.row('**literal*')]; replacement.range = range(10);
  replacement.beforeInput({inputType:'insertReplacementText',data:'*',cancelable:true,preventDefault(){}});
  assert.equal(replacement.rows[0].text, '**literal**');
  const composition = controller();
  composition.beforeInput({inputType:'insertText',data:'**x**',isComposing:true,cancelable:true,preventDefault(){}});
  assert.equal(composition.rows[0].text, '');
  const selected = controller(); selected.rows = [M.row('**literal*x')];
  selected.range = { start: {row:0,offset:10}, end:{row:0,offset:11} };
  selected.beforeInput({inputType:'insertText',data:'*',cancelable:true,preventDefault(){}});
  assert.equal(selected.rows[0].text, '**literal**');
});

test('code-fence Enter conversion is undoable and code contents stay literal', () => {
  const editor = controller(); editor.insert('```');
  editor.beforeInput({inputType:'insertParagraph',cancelable:true,preventDefault(){}});
  assert.equal(editor.rows[0].kind, 'pre');
  editor.beforeInput({inputType:'insertText',data:'**literal**',cancelable:true,preventDefault(){}});
  assert.equal(editor.rows[0].text, '**literal**'); assert.ok(editor.rows[0].marks.every(mark => !mark));
  editor.history(); editor.history(); assert.equal(editor.rows[0].text, '```');
  assert.equal(editor.rows[0].kind, 'p');
});

test('strike toolbar/native/keyboard commands respect policy, history and code exclusivity', () => {
  const editor = controller(); editor.rows = M.fromMarkdown('**bold** and plain');
  editor.range = {start:{row:0,offset:0},end:{row:0,offset:4}};
  assert.ok(editor.command('strike')); assert.equal(editor.rows[0].marks[0], M.BOLD | M.STRIKE);
  assert.equal(M.signature(M.fromMarkdown(M.toMarkdown(editor.rows))), M.signature(editor.rows));
  editor.history(); assert.equal(editor.rows[0].marks[0], M.BOLD);
  editor.beforeInput({inputType:'formatStrikeThrough',cancelable:true,preventDefault(){}});
  assert.equal(editor.rows[0].marks[0], M.BOLD | M.STRIKE);
  editor.command('strike'); assert.equal(editor.rows[0].marks[0], M.BOLD);
  editor.policy = {...policy,features:policy.features.filter(name=>name!=='strike')};
  const before = JSON.stringify(editor.rows); assert.equal(editor.command('strike'),false);
  assert.equal(JSON.stringify(editor.rows),before);
  const caret = controller();
  caret.key({key:'x',ctrlKey:true,shiftKey:true,preventDefault(){}});
  caret.beforeInput({inputType:'insertText',data:'x',cancelable:true,preventDefault(){}});
  assert.equal(caret.rows[0].marks[0],M.STRIKE);
  const coded = M.fromMarkdown('`literal`');
  const selected = {start:{row:0,offset:0},end:{row:0,offset:7}};
  assert.ok(M.format(coded,selected,M.STRIKE)[0].marks.every(mark=>mark===M.STRIKE));
  assert.ok(M.format(M.format(coded,selected,M.STRIKE),selected,M.CODE)[0].marks.every(mark=>mark===M.CODE));
});
