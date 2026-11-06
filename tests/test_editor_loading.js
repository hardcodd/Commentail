const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('commentail/static/commentail/commentail.js', 'utf8')
  .replace('  const start = () => {', '  window.testEditors = { mountRichEditors };\n  const start = () => {');
const settle = () => new Promise(resolve => setImmediate(resolve));
function harness(locale = '/editor-de.js', mode = 'visual') {
  const nodes = [], window = {};
  let timeout, mounts = 0;
  const document = {readyState:'loading',addEventListener(){},
    createElement: tag => ({tag,remove(){this.removed=true;}}), head:{append:node=>nodes.push(node)}};
  vm.runInNewContext(source,{window,document,setTimeout:fn=>{timeout=fn;return 1;},clearTimeout(){}});
  const rich = {dataset:{editorSettings:JSON.stringify({guest:mode}),editorAsset:'/editor.js',editorCss:'/editor.css',editorLocale:locale}};
  const root = {querySelectorAll:()=>[rich]};
  return {nodes,root,window,mount:()=>window.testEditors.mountRichEditors(root),expire:()=>timeout(),
    loaded:()=>{window.CommentailEditors={mount:()=>mounts++};},mounts:()=>mounts};
}
test('only the selected locale loads, before the bundle, once for concurrent forms', async () => {
  const h = harness();h.mount();h.mount();
  assert.deepEqual(h.nodes.map(node=>node.href??node.src),['/editor.css','/editor-de.js']);
  h.nodes[0].onload?.();
  h.nodes[1].onload();assert.equal(h.nodes[2].src,'/editor.js');
  h.loaded();h.nodes[2].onload();await settle();assert.equal(h.mounts(),2);
  h.mount();assert.equal(h.mounts(),3);assert.equal(h.nodes.length,3);
});
test('English needs no locale payload and nonvisual forms load no editor assets', async () => {
  const h = harness('');h.mount();assert.equal(h.nodes.length,2);assert.equal(h.nodes[1].src,'/editor.js');
  h.nodes[0].onload?.();
  h.loaded();h.nodes[1].onload();await settle();assert.equal(h.mounts(),1);
  for (const mode of ['plain','markdown']) {const h=harness('',mode);h.mount();assert.equal(h.nodes.length,0);}
});
test('locale failure and timeout preserve native input, reject late loads and allow retry', async () => {
  for (const fail of ['error','timeout']) {
    const h=harness();h.mount();const locale=h.nodes[1];
    if(fail==='error')locale.onerror();else h.expire();
    await settle();assert.equal(h.mounts(),0);assert.ok(locale.removed);
    locale.onload();assert.equal(h.nodes.length,2);
    h.mount();assert.equal(h.nodes.length,4);h.nodes[3].onload();
    h.nodes[2].onload?.();
    h.loaded();h.nodes[4].onload();await settle();assert.equal(h.mounts(),1);
  }
});

test('bundle success waits for CSS; CSS failure preserves fallback and can retry', async () => {
  const h = harness(''); h.mount();
  h.loaded(); h.nodes[1].onload(); await settle();
  assert.equal(h.mounts(), 0, 'unstyled visual editor must not replace native input');
  h.nodes[0].onerror?.(); await settle();
  assert.equal(h.mounts(), 0);
  assert.ok(h.nodes[0].removed);
  h.mount(); assert.equal(h.nodes.length, 4, 'loaded JS alone must not bypass failed CSS');
  h.nodes[2].onload(); h.nodes[3].onload(); await settle();
  assert.equal(h.mounts(), 1);
});

test('CSS finishing after the bundle mounts the waiting form', async () => {
  const h = harness(''); h.mount(); h.loaded(); h.nodes[1].onload();
  await settle(); assert.equal(h.mounts(), 0);
  h.nodes[0].onload(); await settle(); assert.equal(h.mounts(), 1);
});
