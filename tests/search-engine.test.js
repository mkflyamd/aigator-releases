const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { createStore, listEngines, ENGINES, DEFAULT_ENGINE } = require('../shell/search-engine');

const tmpFile = () =>
  path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'gator-engine-')), 'engine.json');

test('defaults to Bing when nothing is saved', () => {
  const store = createStore(tmpFile());
  assert.strictEqual(DEFAULT_ENGINE, 'bing');
  assert.strictEqual(store.get(), 'bing');
  assert.strictEqual(store.searchUrl(), 'https://www.bing.com/search?q=');
  assert.strictEqual(store.homeUrl(), 'https://www.bing.com/');
});

test('a chosen engine is used and survives a restart', () => {
  const file = tmpFile();
  const store = createStore(file);
  assert.strictEqual(store.set('duckduckgo'), true);
  assert.strictEqual(store.searchUrl(), ENGINES.duckduckgo.search);
  assert.strictEqual(createStore(file).get(), 'duckduckgo');
});

test('unknown engines are rejected and leave the choice alone', () => {
  const store = createStore(tmpFile());
  store.set('google');
  assert.strictEqual(store.set('nope'), false);
  assert.strictEqual(store.set('__proto__'), false);
  assert.strictEqual(store.set(undefined), false);
  assert.strictEqual(store.get(), 'google');
});

test('a failed save reports failure and keeps the previous engine', () => {
  const file = path.join(tmpFile(), 'missing-dir', 'engine.json');
  const store = createStore(file);
  assert.strictEqual(store.set('google'), false);
  assert.strictEqual(store.get(), 'bing');
  assert.strictEqual(store.homeUrl(), ENGINES.bing.home);
});

test('a corrupt or hostile file falls back to the default', () => {
  const file = tmpFile();
  fs.writeFileSync(file, '{not json');
  assert.strictEqual(createStore(file).get(), 'bing');
  fs.writeFileSync(file, JSON.stringify({ engine: 'toString' }));
  assert.strictEqual(createStore(file).get(), 'bing');
});

test('every engine lists a name and an https search URL that ends ready for a query', () => {
  const list = listEngines();
  assert.deepStrictEqual(
    list.map((e) => e.id),
    ['bing', 'google', 'duckduckgo'],
  );
  for (const e of Object.values(ENGINES)) {
    assert.match(e.search, /^https:\/\/.+[?&]q=$/);
    assert.match(e.home, /^https:\/\//);
  }
});
