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
const P = context.CommentailEditorPolicy;
const M = context.CommentailEditorModel;
const fixtures = {
  bold: '**bold**', italic: '*italic*', strike: '~~strike~~', link: '[link](https://example.com)',
  quote: '> quote', orderedList: '1. item', unorderedList: '- item',
  inlineCode: '`code`', codeBlock: '```\ncode\n```'
};

test('safe site defaults and independent audience modes', () => {
  const config = P.configure();
  assert.equal(P.forAudience(config, 'guest').mode, 'plain');
  assert.equal(P.forAudience(config, 'registered').mode, 'plain');
  for (const guest of P.MODES) for (const registered of P.MODES) {
    const site = P.configure({ guest, registered });
    assert.equal(P.forAudience(site, 'guest').mode, guest);
    assert.equal(P.forAudience(site, 'registered').mode, registered);
  }
});

test('configuration rejects unknown keys, modes, audiences and malformed capabilities', () => {
  for (const value of [null, [], 0, 'visual', { guest: 'html' }, { guest: null }, { registered: false }, { admin: 'visual' },
    { features: null }, { features: { bold: true } }, { features: ['bogus'] },
    { features: ['bold', 'bold'] }]) assert.throws(() => P.configure(value));
  for (const audience of ['admin', '__proto__', null]) assert.throws(() => P.forAudience(P.configure(), audience));
});

test('instance policy is immutable and isolated from caller mutation', () => {
  const features = ['bold'];
  const site = P.configure({ features, guest: 'markdown' });
  const policy = P.forAudience(site, 'guest');
  features.push('link');
  assert.deepEqual(Array.from(policy.features), ['bold']);
  assert(Object.isFrozen(site) && Object.isFrozen(policy) && Object.isFrozen(policy.features));
  assert.throws(() => policy.features.push('link'));
});

test('each disabled feature is rejected independently, with no silent suppression', () => {
  for (const [feature, source] of Object.entries(fixtures)) {
    const restricted = P.forAudience(P.configure({ features: P.FEATURES.filter(item => item !== feature), guest: 'markdown' }), 'guest');
    assert.throws(() => P.assertMarkdown(source, restricted), error => error.feature === feature, feature);
    for (const [other, allowedSource] of Object.entries(fixtures)) {
      if (other !== feature) P.assertMarkdown(allowedSource, restricted);
    }
    P.assertMarkdown(source, P.forAudience(P.configure({ guest: 'markdown' }), 'guest'));
  }
});

test('all 512 format subsets accept exactly their own syntax', () => {
  const entries = Object.entries(fixtures);
  for (let bits = 0; bits < 512; bits++) {
    const features = P.FEATURES.filter((_, index) => bits & (1 << index));
    const policy = P.forAudience(P.configure({ features, registered: 'visual' }), 'registered');
    for (const [feature, source] of entries) {
      if (features.includes(feature)) P.assertMarkdown(source, policy);
      else assert.throws(() => P.assertMarkdown(source, policy));
    }
  }
});

test('nested disabled syntax is rejected but literal examples and raw URLs remain text', () => {
  const policy = P.forAudience(P.configure({ features: ['quote', 'orderedList', 'unorderedList', 'codeBlock', 'inlineCode'], guest: 'markdown' }), 'guest');
  for (const source of ['> **bold**', '1. *italic*', '- [x](https://example.com)', '> 1. ~~strike~~']) {
    assert.throws(() => P.assertMarkdown(source, policy));
  }
  for (const source of ['`**bold** [x](https://example.com)`', '```\n~~strike~~\n```', '\\*\\*literal\\*\\*', 'https://example.com', '<strong>literal</strong>']) {
    P.assertMarkdown(source, policy);
  }
});

test('plain mode never interprets syntax, but still enforces source limits/types', () => {
  const plain = P.forAudience(P.configure({ features: [] }), 'guest');
  P.assertMarkdown(Object.values(fixtures).join('\n\n'), plain);
  assert.throws(() => P.assertMarkdown('x'.repeat(100001), plain));
  assert.throws(() => P.assertMarkdown(null, plain));
});

test('row validation and command admission use the same feature names', () => {
  const commands = { bold: 'bold', italic: 'italic', strike: 'strike', code: 'inlineCode', pre: 'codeBlock', link: 'link', quote: 'quote', ol: 'orderedList', ul: 'unorderedList' };
  for (const [command, feature] of Object.entries(commands)) {
    const policy = P.forAudience(P.configure({ features: P.FEATURES.filter(item => item !== feature), registered: 'visual' }), 'registered');
    assert(!P.allowsCommand(command, policy));
    assert.throws(() => P.assertRows(M.fromMarkdown(fixtures[feature]), policy));
    assert(P.allowsCommand('clear', policy));
  }
  const noLists = P.forAudience(P.configure({ features: [], registered: 'visual' }), 'registered');
  assert(!P.allowsCommand('indent', noLists));
  assert(!P.allowsCommand('outdent', noLists));
  assert(!P.allowsCommand('__proto__', noLists));
});
