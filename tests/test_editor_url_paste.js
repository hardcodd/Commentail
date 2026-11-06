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
const label=value=>c.CommentailURLPaste.domainLabel(value);

test('domain labels omit scheme, www, port, path, query and fragment',()=>{
 for(const [url,expected] of [['https://www.youtube.com/watch?v=abc#t=5','youtube.com'],['https://vk.ru/video123','vk.ru'],['https://EXAMPLE.COM:8443/long/path?q=yes#part','example.com'],['https://www.example.com./x','example.com']])assert.equal(label(url),expected);
});
test('domain labels keep meaningful subdomains and compound suffixes intact',()=>{
 for(const host of ['m.youtube.com','news.bbc.co.uk','project.github.io','example.com.au'])assert.equal(label('https://'+host+'/x'),host);
});
test('IP and international hosts use canonical URL hostname spelling',()=>{
 assert.equal(label('https://127.0.0.1:8080/a'),'127.0.0.1');assert.equal(label('https://[2001:db8::1]/a'),'[2001:db8::1]');assert.equal(label('https://пример.рф/путь'),'xn--e1afmkfd.xn--p1ai');
});
test('unsafe, incomplete and non-web addresses are rejected',()=>{
 for(const value of ['javascript:alert(1)','mailto:a@example.com','file:///etc/passwd','example.com','https://u:p@example.com','https://example.com/a b','https://example.com/\\x'])assert.throws(()=>label(value),undefined,value);
});
