const test = require('node:test');
const assert = require('node:assert');
const { resolveAddressInput, loadAddressInput } = require('../shell/address-input');

const resolve = (s) => resolveAddressInput(s);

test('full web addresses navigate over https by default', () => {
  assert.deepStrictEqual(resolve('www.cnn.com'), {
    kind: 'url',
    url: 'https://www.cnn.com/',
    explicit: false,
  });
  assert.strictEqual(resolve('cnn.com/world?x=1').url, 'https://cnn.com/world?x=1');
  assert.strictEqual(resolve('  example.org  ').url, 'https://example.org/');
});

test('explicit http and https are kept', () => {
  assert.deepStrictEqual(resolve('http://example.com'), {
    kind: 'url',
    url: 'http://example.com/',
    explicit: true,
  });
  assert.strictEqual(resolve('HTTPS://Example.com/A').url, 'https://example.com/A');
});

test('a bare word is a search, not a guessed .com', () => {
  const r = resolve('cnn');
  assert.strictEqual(r.kind, 'search');
  assert.strictEqual(r.url, 'https://www.bing.com/search?q=cnn');
});

test('anything with spaces is a search and is encoded', () => {
  assert.strictEqual(
    resolve('weather in paris & rome').url,
    'https://www.bing.com/search?q=weather%20in%20paris%20%26%20rome',
  );
  assert.strictEqual(resolve('cnn.com news').kind, 'search');
});

test('localhost, IPs, .local and host:port use http', () => {
  assert.strictEqual(resolve('localhost:3000').url, 'http://localhost:3000/');
  assert.strictEqual(resolve('localhost').url, 'http://localhost/');
  assert.strictEqual(resolve('192.168.1.10:8080/admin').url, 'http://192.168.1.10:8080/admin');
  assert.strictEqual(resolve('printer.local').url, 'http://printer.local/');
  assert.strictEqual(resolve('[::1]:8000').url, 'http://[::1]:8000/');
  assert.strictEqual(resolve('intranet:8080').url, 'http://intranet:8080/');
});

test('other schemes are refused, not searched or executed', () => {
  assert.strictEqual(resolve('javascript:alert(1)'), null);
  assert.strictEqual(resolve('file:///C:/secret.txt'), null);
  assert.strictEqual(resolve('data:text/html,hi'), null);
  assert.strictEqual(resolve('mailto:a@b.com'), null);
});

test('empty input resolves to nothing', () => {
  assert.strictEqual(resolve(''), null);
  assert.strictEqual(resolve('   '), null);
  assert.strictEqual(resolve(undefined), null);
});

test('email-like and single-label dotted junk are searches', () => {
  assert.strictEqual(resolve('me@example.com').kind, 'search');
  assert.strictEqual(resolve('v1.2').kind, 'search');
});

function fakeWc(failures) {
  const loaded = [];
  return {
    loaded,
    focused: 0,
    focus() {
      this.focused += 1;
    },
    loadURL(url) {
      loaded.push(url);
      const err = failures.shift();
      return err ? Promise.reject(err) : Promise.resolve();
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));

test('a guessed address that does not resolve falls back to a search', async () => {
  const wc = fakeWc([Object.assign(new Error('dns'), { code: 'ERR_NAME_NOT_RESOLVED' })]);
  const errors = [];
  loadAddressInput(wc, 'notarealsite.zzz', (e) => errors.push(e));
  await tick();
  assert.deepStrictEqual(wc.loaded, [
    'https://notarealsite.zzz/',
    'https://www.bing.com/search?q=notarealsite.zzz',
  ]);
  assert.strictEqual(errors.length, 0);
});

test('an explicit address that does not resolve reports the error instead of searching', async () => {
  const wc = fakeWc([Object.assign(new Error('dns'), { code: 'ERR_NAME_NOT_RESOLVED' })]);
  const errors = [];
  loadAddressInput(wc, 'https://nope.invalid', (e, url) => errors.push(url));
  await tick();
  assert.strictEqual(wc.loaded.length, 1);
  assert.deepStrictEqual(errors, ['https://nope.invalid/']);
});

test('ERR_ABORTED is not an error and the page gets focus after loading starts', async () => {
  const wc = fakeWc([Object.assign(new Error('aborted'), { errno: -3 })]);
  const errors = [];
  loadAddressInput(wc, 'example.com', (e) => errors.push(e));
  await tick();
  assert.strictEqual(errors.length, 0);
  assert.strictEqual(wc.focused, 1);
});

test('refused schemes report an error and load nothing', () => {
  const wc = fakeWc([]);
  const errors = [];
  loadAddressInput(wc, 'javascript:alert(1)', (e) => errors.push(e.message));
  assert.strictEqual(wc.loaded.length, 0);
  assert.strictEqual(errors.length, 1);
});

test('a mistyped address with a path or query is never sent to the search engine', async () => {
  for (const typed of [
    'intranet.corp.exmple/reports?token=abc',
    'host.zzz/path',
    'host.zzz:8443',
  ]) {
    const wc = fakeWc([Object.assign(new Error('dns'), { code: 'ERR_NAME_NOT_RESOLVED' })]);
    const errors = [];
    loadAddressInput(wc, typed, (e) => errors.push(e));
    await tick();
    assert.strictEqual(wc.loaded.length, 1, typed);
    assert.strictEqual(errors.length, 1, typed);
  }
});

test('typed text is searched with the supplied engine', () => {
  const google = 'https://www.google.com/search?q=';
  assert.strictEqual(resolveAddressInput('cnn', google).url, 'https://www.google.com/search?q=cnn');
  assert.strictEqual(
    resolveAddressInput('weather in paris', google).url,
    'https://www.google.com/search?q=weather%20in%20paris',
  );
  assert.strictEqual(resolveAddressInput('example.com', google).url, 'https://example.com/');
});

test('the unresolved-name fallback uses the supplied engine', async () => {
  const ddg = 'https://duckduckgo.com/?q=';
  const wc = fakeWc([Object.assign(new Error('dns'), { code: 'ERR_NAME_NOT_RESOLVED' })]);
  loadAddressInput(wc, 'notarealsite.zzz', () => {}, ddg);
  await tick();
  assert.deepStrictEqual(wc.loaded, [
    'https://notarealsite.zzz/',
    'https://duckduckgo.com/?q=notarealsite.zzz',
  ]);
});
