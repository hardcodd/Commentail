const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = 'frontend/editor/';
const reference = JSON.parse(fs.readFileSync(root + 'locales/ru.json', 'utf8'));

test('every runtime message and toolbar/dialog label has a locale entry', () => {
  const messages = new Set();
  for (const file of fs.readdirSync(root).filter(name => name.endsWith('.js'))) {
    const source = fs.readFileSync(root + file, 'utf8');
    for (const match of source.matchAll(/translate\(("(?:[^"\\]|\\.)*")\)/g)) messages.add(JSON.parse(match[1]));
  }
  const html = fs.readFileSync('commentail/templates/commentail/editor-tools.html', 'utf8');
  for (const match of html.matchAll(/(?:aria-label|placeholder)="([^"]+)"/g)) {
    if (match[1] !== 'https://example.com') messages.add(match[1]);
  }
  for (const match of html.matchAll(/>([^<>]+)</g)) {
    const text = match[1].trim(); if (/[a-z]/i.test(text) && !/Ctrl|Tab/.test(text)) messages.add(text);
  }
  for (const message of messages) assert.ok(Object.hasOwn(reference, message), message);
});

for (const language of ['ru', 'de', 'fr', 'es', 'pt-br']) {
  test(language + ' complete catalog and shipped locale are identical', () => {
    const catalog = JSON.parse(fs.readFileSync(root + 'locales/' + language + '.json', 'utf8'));
    assert.deepEqual(Object.keys(catalog).sort(), Object.keys(reference).sort());
    assert.ok(Object.values(catalog).every(value => typeof value === 'string' && value.trim()));
    const context = vm.createContext({ URL, structuredClone, document: {documentElement:{lang:language}}, addEventListener(){} });
    vm.runInContext(fs.readFileSync('commentail/static/commentail/editor-' + language + '.js', 'utf8'), context);
    assert.deepEqual(JSON.parse(JSON.stringify(context.CommentailEditorLocale)), catalog);
    vm.runInContext(fs.readFileSync('commentail/static/commentail/editor.js', 'utf8'), context);
    assert.equal(context.CommentailEditorPolicy.labels.strike, catalog.Strikethrough);
    assert.throws(() => context.CommentailEditorModel.toCommentMarkdown([]), error => error.message === catalog['Enter your comment.']);
  });
}

test('missing/unknown locale falls back to English without other language payloads', () => {
  const context = vm.createContext({ URL, structuredClone, document:{documentElement:{lang:'xx'}}, addEventListener(){} });
  vm.runInContext(fs.readFileSync('commentail/static/commentail/editor.js','utf8'), context);
  assert.equal(context.CommentailEditorPolicy.labels.strike, 'Strikethrough');
  assert.throws(() => context.CommentailEditorModel.toCommentMarkdown([]), /Enter your comment/);
});
