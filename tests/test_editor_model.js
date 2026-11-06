/* Exercise the shipped bundle, including its Russian UI locale. */
const test = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({ URL, structuredClone,
  document: { documentElement: { lang: 'ru' } }, addEventListener() {} });
vm.runInContext(readFileSync(path.join(__dirname, '../commentail/static/commentail/editor-ru.js'), 'utf8'), context);
vm.runInContext(readFileSync(path.join(__dirname, '../commentail/static/commentail/editor.js'), 'utf8'), context);
const c = context;
const M = context.CommentailEditorModel;
const plain = value => JSON.parse(JSON.stringify(value));
const point = (row, offset) => ({ row, offset });
const range = (r, a, b = a) => ({ start: point(r, a), end: point(r, b) });
function roundtrip(rows) {
  const source = M.toMarkdown(rows);
  assert.equal(M.signature(M.fromMarkdown(source)), M.signature(rows), source);
  return source;
}

test('empty document, exact literal punctuation, HTML and Markdown examples', () => {
  for (const text of ['', '**пример** <script>x</script> &amp; ![x](https://x.test)', 'a\\b `c` [d] # e', 'Привет 👨‍👩‍👧‍👦 café 你好', 'line\nnext']) {
    roundtrip([M.row(text)]);
  }
});

for (const source of ['**bold**', '*italic*', '***both***', '~~strike~~', '~~**bold** and *italic*~~', '**~~both~~**', '~~[link](https://example.com)~~', '`**literal**`', '1. one\n   1. nested\n   2. next\n2. two',
  '0. zero\n1. next', '3. parent\n\n   4. child', '- one\n  1. nested\n- two', '~~~\na\n\n b\n~~~', '~~~\n~~~']) {
  test('semantic roundtrip: ' + JSON.stringify(source), () => roundtrip(M.fromMarkdown(source)));
}

test('unsupported source raises an explicit error rather than deleting structure', () => {
  for (const source of ['[multi\\\nline](https://example.com)', '> > nested quote', '> - list', '> ~~~\n> code\n> ~~~', '```js\ncode\n```', '- first\n\n  second paragraph', '**`code`**', '1. first\n\n1) separate']) {
    assert.throws(() => M.fromMarkdown(source), M.EditorError);
  }
});

test('links import/export safe addresses and mixed inline formats in paragraphs, quotes and lists', () => {
  for (const source of ['[text](https://example.com/a?x=1&y=2#part)', '[почта](mailto:alex@example.com)',
    '[**bold** and *italic* and `code`](https://example.com)', '**before [link](https://example.com) after**',
    '> [quote](https://example.com)', '1. [one](https://example.com)\n   - [child](http://example.com)',
    '[x](https://пример.рф/путь)', '[one](https://example.com/a\\(b\\)) [two](https://example.com/z)']) {
    const rows = M.fromMarkdown(source); assert.ok(rows.some(item => item.links?.length)); roundtrip(rows);
  }
});

test('link creation, address editing, removal and label replacement preserve surrounding content and marks', () => {
  const rows = M.fromMarkdown('before **label** after');
  const selected = range(0, 7, 12);
  const linked = M.applyLink(rows, selected, 'https://example.com', 'label');
  assert.equal(linked.rows[0].text, rows[0].text);
  assert.deepEqual(plain(linked.rows[0].marks), plain(rows[0].marks));
  assert.equal(linked.rows[0].links[0].href, 'https://example.com/'); roundtrip(linked.rows);
  const edited = M.applyLink(linked.rows, selected, 'https://example.org', 'new label');
  assert.equal(edited.rows[0].text, 'before new label after'); roundtrip(edited.rows);
  const removed = M.applyLink(edited.rows, range(0, 7, 16), null);
  assert.equal(removed.rows[0].text, edited.rows[0].text); assert.equal(removed.rows[0].links, undefined);
  assert.equal(rows[0].links, undefined);
});

test('unsafe and unsupported link operations fail atomically', () => {
  const rows = [M.row('label')]; const before = JSON.stringify(rows);
  for (const href of ['javascript:alert(1)', 'data:text/html,x', '//example.com', '/relative', 'ftp://example.com',
    'https://u:p@example.com', 'https://ex ample.com', 'https://example.com\\x', 'mailto:a@b?body=%0aX',
    'https://example.com/\npath', 'https://example.com/' + 'a'.repeat(2048)]) {
    assert.throws(() => M.applyLink(rows, range(0, 0, 5), href), M.EditorError);
  }
  assert.throws(() => M.applyLink([M.row('code', 'pre')], range(0, 0, 4), 'https://example.com'), M.EditorError);
  assert.throws(() => M.applyLink([M.row('a\nb')], range(0, 0, 3), 'https://example.com'), M.EditorError);
  assert.throws(() => M.applyLink([M.row('a'), M.row('b')], {start:point(0,0),end:point(1,1)}, 'https://example.com'), M.EditorError);
  assert.equal(JSON.stringify(rows), before);
});

test('link target expands a cursor or contained selection to the entire link', () => {
  const rows = M.fromMarkdown('a [label](https://example.com) z');
  for (const selected of [range(0, 2), range(0, 4), range(0, 7), range(0, 3, 5)]) {
    const target = M.linkTarget(rows, selected);
    assert.equal(target.href, 'https://example.com/');
    assert.deepEqual(plain(target.range), range(0, 2, 7));
  }
  assert.equal(M.linkTarget(rows, range(0, 0)).href, null);
});

test('text replacement remaps links; typing inside inherits and typing at boundaries remains outside', () => {
  const rows = M.fromMarkdown('a [link](https://example.com) z');
  for (const [offset, linked] of [[2, false], [3, true], [6, false]]) {
    const result = M.replace(rows, range(0, offset), 'X');
    const values = M.linkValues(result.rows[0]); assert.equal(Boolean(values[offset]), linked); roundtrip(result.rows);
  }
  const edited = M.replace(rows, range(0, 3, 5), 'XYZ'); roundtrip(edited.rows);
  assert.equal(edited.rows[0].links[0].end, 7);
  const split = M.replace(rows, range(0, 4), '\n');
  assert.equal(split.rows.length, 2); assert.ok(split.rows.every(item => item.links?.length)); roundtrip(split.rows);
  const merged = M.replace(split.rows, {start:point(0,4),end:point(1,0)}, ''); roundtrip(merged.rows);
  assert.equal(merged.rows[0].links.length, 1);
});

test('link spans follow boundary normalization and intentional conversion to fenced code', () => {
  const rows = M.applyLink([M.row('  label  ')], range(0, 2, 7), 'https://example.com').rows;
  const normalized = M.normalizeForExport(rows);
  assert.deepEqual(plain(normalized[0].links), [{start:0,end:5,href:'https://example.com/'}]);
  assert.equal(M.signature(M.fromMarkdown(M.toCommentMarkdown(rows))), M.signature(normalized));
  const coded = M.structure(rows, range(0, 0, 9), 'pre'); assert.equal(coded[0].links, undefined); roundtrip(coded);
  const joined = M.replace([M.row('code', 'pre'), ...M.fromMarkdown('[label](https://example.com)')],
    {start:point(0,4),end:point(1,0)}, '');
  assert.equal(joined.rows[0].text,'codelabel'); assert.equal(joined.rows[0].links,undefined); roundtrip(joined.rows);
});

test('invalid link spans are rejected without mutation; adjacent equal addresses canonicalize', () => {
  for (const spans of [[{start:-1,end:1,href:'https://example.com'}], [{start:0,end:9,href:'https://example.com'}],
    [{start:0,end:2,href:'javascript:evil'}], [{start:0,end:2,href:'https://example.com'},{start:1,end:3,href:'https://example.org'}]]) {
    const rows = [{...M.row('abc'), links:spans}]; const before = JSON.stringify(rows);
    assert.throws(() => M.normalize(rows), M.EditorError); assert.equal(JSON.stringify(rows), before);
  }
  const rows = [{...M.row('abcd'), links:[{start:0,end:2,href:'https://example.com'},{start:2,end:4,href:'https://example.com/'}]}];
  const normalized = M.normalize(rows); assert.equal(normalized[0].links.length, 1); roundtrip(normalized);
});

test('500 seeded text and link edits match an independent per-character address oracle', () => {
  let rows = [M.row('abcdef')], text = 'abcdef', hrefs = Array(6).fill(null), seed = 73181;
  const random = max => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed % max; };
  for (let i = 0; i < 500; i++) {
    const a = random(text.length + 1), b = a + random(text.length - a + 1);
    if (i % 3 === 0 && a !== b) {
      const href = i % 2 ? null : 'https://example.com/' + i;
      rows = M.applyLink(rows, range(0,a,b), href).rows; hrefs.fill(href,a,b);
    } else {
      const value = i % 4 ? String.fromCharCode(97 + random(26)) : '';
      const inherited = a === b ? (a > 0 && a < text.length && hrefs[a-1] === hrefs[a] ? hrefs[a] : null) :
        (hrefs[a] && hrefs.slice(a,b).every(href => href === hrefs[a]) ? hrefs[a] : null);
      rows = M.replace(rows, range(0,a,b), value).rows;
      text = text.slice(0,a) + value + text.slice(b);
      hrefs.splice(a,b-a,...Array(value.length).fill(inherited));
    }
    assert.equal(rows[0].text, text); assert.deepEqual(plain(M.linkValues(rows[0])), hrefs); roundtrip(rows);
  }
});

test('quotes import and export empty, multiple paragraphs, hard breaks and inline formats', () => {
  for (const source of ['> quote', '>', '> **bold** and *italic* and `code`', '> first\n>\n> second',
    'before\n\n> quoted\\\n> next\n\nafter', '> first\n\n> second', '> \\> literal']) {
    const rows = M.fromMarkdown(source);
    assert.ok(rows.some(item => item.kind === 'quote'));
    roundtrip(rows);
  }
  roundtrip([M.row('', 'quote'), M.row('', 'quote'), M.row('text', 'quote')]);
});

test('quote conversion preserves marks, includes list descendants and toggles back to paragraphs', () => {
  const rows = M.fromMarkdown('**parent**\n\n1. child\n   - nested\n\nafter');
  const selected = { start: point(0, 0), end: point(1, 5) };
  const quoted = M.structure(rows, selected, 'quote');
  assert.deepEqual(plain(quoted.map(item => item.kind)), ['quote', 'quote', 'quote', 'p']);
  assert.ok(quoted[0].marks.every(mark => mark === M.BOLD));
  assert.ok(quoted.every(item => item.depth === 0));
  roundtrip(quoted);
  const unquoted = M.structure(quoted, { start: point(0, 0), end: point(2, 6) }, 'quote');
  assert.ok(unquoted.every(item => item.kind === 'p'));
  assert.equal(rows[1].kind, 'ol');
  const exclusiveEnd = M.structure(M.fromMarkdown('one\n\ntwo'), { start: point(0, 0), end: point(1, 0) }, 'quote');
  assert.deepEqual(plain(exclusiveEnd.map(item => item.kind)), ['quote', 'p']);
  const beforeList = M.structure(M.fromMarkdown('intro\n\n1. one\n   - nested'), range(0, 0), 'quote');
  assert.deepEqual(plain(beforeList.map(item => item.kind)), ['quote', 'ol', 'ul']);
  roundtrip(beforeList);
});

test('quote comment export normalizes boundaries but keeps literal content and inline-code spaces', () => {
  for (const text of [' first\nnext \n\t', '> literal **markers**', '<img onerror=x>', 'line\n\nnext']) {
    const rows = [M.row(text, 'quote')];
    const before = JSON.stringify(rows);
    const source = M.toCommentMarkdown(rows);
    assert.equal(M.signature(M.fromMarkdown(source)), M.signature(M.normalizeForExport(rows)));
    assert.equal(JSON.stringify(rows), before);
  }
  const coded = M.row('  code  ', 'quote', 0, 1, Array(8).fill(M.CODE));
  assert.equal(M.fromMarkdown(M.toCommentMarkdown([coded]))[0].text, coded.text);
  assert.throws(() => M.toCommentMarkdown([M.row('', 'quote')]), /Введите текст/);
});

test('unrepresentable whitespace is rejected explicitly with the original model intact', () => {
  for (const text of [' x ', '   ']) {
    const rows = [M.row(text)];
    assert.throws(() => M.toMarkdown(rows), /сочетание оформления/);
    assert.equal(rows[0].text, text);
  }
});

test('comment export trims paragraph/list edges on a copy and preserves internal breaks', () => {
  for (const kind of ['p', 'ol', 'ul', 'quote']) {
    for (const left of ['', ' ', '\t', ' \t ']) {
      for (const right of ['', ' ', '\t', '\n', ' \n\n\t ']) {
        const rows = [M.row(left + 'first\n\nsecond' + right, kind, kind === 'p' ? 0 : 1, 3)];
        const before = JSON.stringify(rows);
        const normalized = M.normalizeForExport(rows);
        assert.equal(normalized[0].text, 'first\n\nsecond');
        assert.equal(M.signature(M.fromMarkdown(M.toCommentMarkdown(rows))), M.signature(normalized));
        assert.equal(JSON.stringify(rows), before);
        assert.deepEqual(plain(M.normalizeForExport(normalized)), plain(normalized));
      }
    }
  }
});

test('comment export preserves inline and block code whitespace exactly', () => {
  for (const text of ['', ' ', '\t', ' \t ', '\n', '\n\n', ' x \n\t\n', '~~~\n  code\n\n']) {
    const rows = [M.row(' \t'), M.row(text, 'pre'), M.row('\n\t ')];
    const normalized = M.normalizeForExport(rows);
    assert.equal(normalized.length, 1);
    assert.equal(normalized[0].text, text);
    assert.equal(M.fromMarkdown(M.toCommentMarkdown(rows))[0].text, text);
  }
  for (const text of [' ', '  x  ', '\t x\t', '` x `']) {
    const rows = [M.row(' \t' + text + ' \n', 'p', 0, 1, [0, 0, ...Array(text.length).fill(M.CODE), 0, 0])];
    const normalized = M.normalizeForExport(rows);
    assert.equal(normalized[0].text, text);
    assert.ok(normalized[0].marks.every(mark => mark === M.CODE));
    assert.equal(M.signature(M.fromMarkdown(M.toCommentMarkdown(rows))), M.signature(normalized));
  }
});

test('comment export keeps mark offsets, internal spaces, Unicode spaces and nested list starts', () => {
  const rows = [M.row('  a  b\n', 'ol', 1, 3, [0, 0, 1, 0, 0, 2, 0]), M.row('\tchild \n', 'ol', 2, 4)];
  const normalized = M.normalizeForExport(rows);
  assert.deepEqual(plain(normalized[0].marks), [1, 0, 0, 2]);
  assert.equal(normalized[0].start, 3); assert.equal(normalized[1].start, 4);
  assert.equal(M.signature(M.fromMarkdown(M.toCommentMarkdown(rows))), M.signature(normalized));
  const unicode = '\u00a0text\u2003';
  assert.equal(M.normalizeForExport([M.row(unicode)])[0].text, unicode);
  assert.equal(M.fromMarkdown(M.toCommentMarkdown([M.row(unicode)]))[0].text, unicode);
});

test('empty comment export is explicit; internal empty paragraphs and empty list items stay structural', () => {
  for (const rows of [[], [M.row()], [M.row(' \t\n\n')], [M.row(' '), M.row('\t')], [M.row(' \t', 'ul', 1)]]) {
    assert.throws(() => M.toCommentMarkdown(rows), /Введите текст комментария/);
    assert.equal(M.toCommentMarkdown(rows, true).trim(), rows[0]?.kind === 'ul' ? '-' : '');
  }
  const rows = [M.row(' '), M.row('a'), M.row(''), M.row('b\n'), M.row(' \t')];
  assert.deepEqual(plain(M.normalizeForExport(rows)).map(item => item.text), ['a', '', 'b']);
});

test('1000 seeded padded comments preserve their independent clean-text and code oracle', () => {
  let seed = 937;
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed; };
  const padding = ['', ' ', '\t', ' \t '];
  for (let index = 0; index < 1000; index++) {
    const text = 'word' + random() + '\nnext';
    const code = padding[random() % 4] + '~`code' + '\n'.repeat(random() % 4) + padding[random() % 4];
    const inline = padding[random() % 4] + 'code' + padding[random() % 4];
    const rows = [M.row(padding[random() % 4]), M.row(padding[random() % 4] + text + padding[random() % 4] + '\n'.repeat(random() % 4)),
      M.row(code, 'pre'), M.row(' \t' + inline + ' \n', 'p', 0, 1, [0, 0, ...Array(inline.length).fill(M.CODE), 0, 0]), M.row('\t')];
    const before = JSON.stringify(rows);
    const parsed = M.fromMarkdown(M.toCommentMarkdown(rows));
    assert.deepEqual(plain(parsed).map(item => item.text), [text, code, inline]);
    assert.equal(JSON.stringify(rows), before);
    assert.deepEqual(plain(M.normalizeForExport(M.normalizeForExport(rows))), plain(M.normalizeForExport(rows)));
  }
});

test('overlapping bold/italic ranges choose either nesting order without loss', () => {
  for (const marks of [[2, 3, 1, 0, 1, 0, 0], [1, 3, 2, 0, 1, 0, 0]]) {
    roundtrip([M.row('abc xyz', 'p', 0, 1, marks)]);
  }
});

test('independent words and blocks may require different Markdown delimiters', () => {
  const marks = [2, 3, 1, 0, 1, 0, 0];
  roundtrip([M.row('abc xyz', 'p', 0, 1, marks), M.row('abc xyz', 'p', 0, 1, marks.map(mark => mark === 1 ? 2 : mark === 2 ? 1 : mark))]);
  roundtrip([M.row('abc xyz abc xyz', 'p', 0, 1, [...marks, 0, ...marks.map(mark => mark === 1 ? 2 : mark === 2 ? 1 : mark)])]);
});

test('dense adjacent runs may alternate marker spelling within one fragment', () => {
  for (const marks of ['2310300', '1320300', '0233310']) {
    roundtrip([M.row('abc xyz', 'p', 0, 1, [...marks].map(Number))]);
  }
});

test('intrinsic punctuation and whitespace refusals preserve the model', () => {
  const cases = [M.row('a.b', 'p', 0, 1, [0, 1, 0]), M.row(' x '), M.row('   ')];
  for (const item of cases) {
    const before = JSON.stringify(item);
    assert.throws(() => M.toMarkdown([item]), M.EditorError);
    assert.equal(JSON.stringify(item), before);
  }
  roundtrip([M.row('a\n\nb')]);
});

test('hard breaks are structural separators, never styled inline characters', () => {
  for (const text of ['a\nb', 'a\n\nb', '\na']) {
    for (const mask of [1, 2, 3, 4]) {
      const rows = M.normalize([M.row(text, 'p', 0, 1, Array(text.length).fill(mask))]);
      for (let index = 0; index < text.length; index++) if (text[index] === '\n') assert.equal(rows[0].marks[index], 0);
      roundtrip(rows);
    }
  }
  assert.throws(() => M.toMarkdown([M.row('a\n')]), M.EditorError);
});

test('all 16384 bold/italic assignments for a fixed seven-character fixture are lossless or explicit', t => {
  let accepted = 0, rejected = 0;
  for (let value = 0; value < 16384; value++) {
    const rows = [M.row('abc xyz', 'p', 0, 1, Array.from({ length: 7 }, (_, index) => value >> index * 2 & 3))];
    const before = JSON.stringify(rows);
    try { roundtrip(rows); accepted++; }
    catch (error) { assert.ok(error instanceof M.EditorError); rejected++; }
    assert.equal(JSON.stringify(rows), before);
  }
  assert.ok(accepted >= 16046, 'do not regress the recovered encodings');
  t.diagnostic(JSON.stringify({ assignments: 16384, accepted, explicitlyRejected: rejected }));
});

test('clear inline formatting preserves text, blocks, code and unselected links', () => {
  const rows = M.fromMarkdown('1. [**first** second](https://example.com)\n\n   1. *child*\n\n~~~\n  code\n\n~~~');
  const before = JSON.stringify(rows);
  const cleared = M.clearFormatting(rows, range(0, 1, 7));
  assert.equal(cleared[0].text, rows[0].text);
  assert.deepEqual(plain(cleared[0].marks), [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
  assert.deepEqual(plain(cleared[0].links), [
    { start: 0, end: 1, href: 'https://example.com/' },
    { start: 7, end: 12, href: 'https://example.com/' }
  ]);
  const all = M.clearFormatting(rows, { start: point(0, 0), end: point(2, rows[2].text.length) });
  assert.deepEqual(plain(all.map(item => item.text)), plain(rows.map(item => item.text)));
  assert.deepEqual(plain(all.map(item => [item.kind, item.depth, item.start])), plain(rows.map(item => [item.kind, item.depth, item.start])));
  assert.deepEqual(plain(all[2]), plain(rows[2]));
  assert.ok(all.every(item => item.marks.every(mark => mark === 0) && !item.links));
  assert.equal(JSON.stringify(rows), before); roundtrip(all);
  assert.equal(M.signature(M.clearFormatting(rows, range(0, 2))), M.signature(rows));
});

test('clear formatting recovers a deletion-stranded document without losing text', () => {
  const rows = M.fromMarkdown('a**b*****c** x***y**z');
  const edited = M.replace(rows, range(0, 5, 6), '').rows;
  assert.throws(() => M.toCommentMarkdown(edited), M.EditorError);
  const cleared = M.clearFormatting(edited, range(0, 0, edited[0].text.length));
  assert.equal(M.toCommentMarkdown(cleared), 'abc xz');
  assert.equal(cleared[0].text, edited[0].text);
});

test('replace across blocks preserves first block style and suffix formatting', () => {
  const rows = [M.row('abc', 'ol', 1), M.row('def', 'ol', 1, 2, [1, 1, 1])];
  const result = M.replace(rows, { start: point(0, 1), end: point(1, 2) }, 'XY', 2);
  assert.deepEqual(plain(result.rows[0]), { text: 'aXYf', marks: [0, 2, 2, 1], kind: 'ol', depth: 1, start: 1 });
  assert.equal(rows[0].text, 'abc');
  assert.deepEqual(plain(result.point), point(0, 3));
});

test('replacement newline, CR/NUL, soft break and preformatted newline contracts', () => {
  const result = M.replace([M.row('ab')], range(0, 1), 'x\r\ny\0z');
  assert.deepEqual(plain(result.rows.map(item => item.text)), ['ax', 'y\ufffdzb']);
  assert.deepEqual(plain(result.point), point(1, 3));
  assert.equal(M.replace([M.row('ab')], range(0, 1), '\n', 0, true).rows[0].text, 'a\nb');
  assert.equal(M.replace([M.row('ab', 'pre')], range(0, 1), '\n').rows[0].text, 'a\nb');
});

test('format selected substring, toggle, whitespace, code exclusivity and mutation isolation', () => {
  const original = [M.row('one two')];
  const bold = M.format(original, range(0, 0, 3), M.BOLD);
  assert.equal(roundtrip(bold), '**one** two');
  assert.equal(M.signature(M.format(bold, range(0, 0, 3), M.BOLD)), M.signature(original));
  assert.equal(roundtrip(M.format(original, range(0, 0, 7), M.CODE)), '`one two`');
  const boundary = M.format([M.row(' x ')], range(0, 0, 3), M.BOLD);
  assert.deepEqual(plain(boundary[0].marks), [0, 1, 0]);
  assert.deepEqual(plain(original[0].marks), Array(7).fill(0));
});

test('code spans preserve ticks and spaces; code block preserves fences and trailing LF', () => {
  for (const text of ['`', '``a`', ' a ', ' ', '   ', 'a`b', '\t', 'a~~~b\n']) {
    roundtrip([M.row(text, 'pre')]);
    if (!text.includes('\n')) roundtrip([M.row(text, 'p', 0, 1, Array(text.length).fill(M.CODE))]);
  }
});

test('list subtree indentation/outdent, first-item guard and list toggles', () => {
  const rows = M.fromMarkdown('1. a\n2. b\n   1. c\n3. d');
  const moved = M.structure(rows, range(1, 0, 1), 'indent');
  assert.deepEqual(plain(moved.map(item => item.depth)), [1, 2, 3, 1]);
  assert.equal(moved[1].start, 1);
  roundtrip(moved);
  assert.equal(M.signature(M.structure(moved, range(1, 0, 1), 'outdent')), M.signature(rows));
  assert.equal(M.signature(M.structure(rows, range(0, 0), 'indent')), M.signature(rows));
  assert.equal(M.structure([M.row('a')], range(0, 0), 'ol')[0].kind, 'ol');
  assert.equal(M.structure([M.row('a', 'ol', 1)], range(0, 0), 'ol')[0].kind, 'p');
});

test('outdent changes only list rows in a mixed selection, preserving code and quotes', () => {
  const rows = M.fromMarkdown('1. first\n   1. child\n\n~~~\n  code  \n\n~~~\n\n> **quote**\n\nparagraph');
  const changed = M.structure(rows, { start: point(0, 0), end: point(4, 9) }, 'outdent');
  assert.equal(changed[0].kind, 'p'); assert.equal(changed[1].depth, 1);
  for (let index = 2; index < rows.length; index++) assert.deepEqual(plain(changed[index]), plain(rows[index]));
  roundtrip(changed);
});

test('directional range sorting and endpoint clamping', () => {
  assert.deepEqual(plain(M.selection([M.row('abc'), M.row('de')], point(99, 99), point(-1, -1))), { start: point(0, 0), end: point(1, 2) });
});

test('invalid models and resource limits fail without mutating caller', () => {
  assert.throws(() => M.normalize([M.row('x'.repeat(20001))]), /20 000/);
  assert.throws(() => M.normalize(Array.from({ length: 1001 }, () => M.row())), /1000/);
  for (const row of [{ ...M.row('x'), marks: [] }, { ...M.row(), depth: 9 }, { ...M.row(), start: -1 }, { ...M.row(), kind: 'script' }, { ...M.row('x'), marks: [16] }]) {
    assert.throws(() => M.normalize([row]), /модель/);
  }
  const rows = [M.row('safe')];
  assert.throws(() => M.replace(rows, range(0, 0), 'x'.repeat(20001)));
  assert.equal(rows[0].text, 'safe');
  assert.throws(() => M.replace(rows, range(0, 0), 'x'.repeat(1000000)), /предел/);
  assert.throws(() => M.replace(rows, range(0, 0), '\n'.repeat(1000)), /1000/);
  const deep = [M.row('a', 'ol', 1), M.row('b', 'ol', 1), ...Array.from({ length: 7 }, (_, index) => M.row('child', 'ol', index + 2))];
  const before = JSON.stringify(deep);
  assert.throws(() => M.structure(deep, range(1, 0), 'indent'), /восьми/);
  assert.equal(JSON.stringify(deep), before);
});

function random(seed) {
  return () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
}

test('5000 seeded text replacements match an independent string oracle', () => {
  const rng = random(20261028);
  let rows = [M.row('initial')], expected = 'initial';
  const alphabet = ['a', 'б', '*', '_', '<', ' ', '\n', '😀', '\\', '`'];
  for (let i = 0; i < 5000; i++) {
    const a = Math.floor(rng() * (expected.length + 1));
    const b = a + Math.floor(rng() * (expected.length - a + 1));
    const value = alphabet[Math.floor(rng() * alphabet.length)];
    rows = M.replace(rows, range(0, a, b), value, 0, true).rows;
    expected = expected.slice(0, a) + value + expected.slice(b);
    assert.equal(rows[0].text, expected, 'step ' + i);
    assert.equal(rows[0].marks.length, expected.length);
  }
});

test('1000 seeded literal documents roundtrip without accidental Markdown/HTML interpretation', () => {
  const rng = random(83);
  const alphabet = ['alpha', 'бета', '**', '_', '`', '\\', '<img>', '&amp;', '- ', '1. ', '\n', ' ', '[x](javascript:alert(1))'];
  for (let i = 0; i < 1000; i++) {
    let text = 'a';
    for (let j = 0; j < 12; j++) text += alphabet[Math.floor(rng() * alphabet.length)] + 'z';
    roundtrip([M.row(text)]);
  }
});

test('1000 seeded list/format documents either roundtrip exactly or explicitly reject encoding', t => {
  const rng = random(991);
  let accepted = 0, rejected = 0;
  for (let i = 0; i < 1000; i++) {
    const rows = M.normalize(Array.from({ length: 1 + Math.floor(rng() * 8) }, () => {
      const text = 'abc xyz';
      const kind = ['p', 'ol', 'ul'][Math.floor(rng() * 3)];
      return M.row(text, kind, kind === 'p' ? 0 : 1 + Math.floor(rng() * 3), 1, Array.from(text, () => Math.floor(rng() * 4)));
    }));
    try { roundtrip(rows); accepted++; }
    catch (error) {
      assert.equal(error.constructor.name, 'EditorError');
      assert.match(error.message, /сочетание оформления/);
      rejected++;
    }
  }
  assert.ok(accepted >= 911, 'do not regress the recovered mixed-document encodings');
  t.diagnostic(JSON.stringify({ accepted, explicitlyRejected: rejected }));
});
