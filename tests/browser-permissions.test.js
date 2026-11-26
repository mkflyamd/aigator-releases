const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const { EventEmitter } = require('events');
const { applyBrowserPermissions, createPermissionPrompt } = require('../shell/browser-permissions');

function fakeSession() {
  const s = {};
  s.setPermissionRequestHandler = (fn) => (s.request = fn);
  s.setPermissionCheckHandler = (fn) => (s.check = fn);
  s.setDisplayMediaRequestHandler = (fn, opts) => {
    s.display = fn;
    s.displayOpts = opts;
  };
  return s;
}

const PERMISSIONS = [
  'media',
  'display-capture',
  'clipboard-read',
  'clipboard-sanitized-write',
  'notifications',
  'local-network-access',
  'idle-detection',
  'geolocation',
];

test('the Browser pane denies every permission request and check', () => {
  const ses = fakeSession();
  applyBrowserPermissions(ses);
  for (const p of PERMISSIONS) {
    let granted;
    ses.request(null, p, (ok) => (granted = ok), { requestingUrl: 'https://app.slack.com/' });
    assert.strictEqual(granted, false, `request ${p}`);
    assert.strictEqual(ses.check(null, p, 'https://teams.microsoft.com'), false, `check ${p}`);
  }
});

test('the Browser pane refuses screen capture without a system picker', () => {
  const ses = fakeSession();
  applyBrowserPermissions(ses);
  let result;
  ses.display({}, (r) => (result = r));
  assert.deepStrictEqual(result, {});
  assert.strictEqual(ses.displayOpts, undefined);
});

test('main.js gives only the Browser pane the deny-all policy', () => {
  const src = fs.readFileSync(path.join(__dirname, '../shell/main.js'), 'utf8');
  assert.match(
    src,
    /if \(id === BROWSER_PANE_ID\) applyBrowserPermissions\(ses, _browserPrompt\);\s*else applyMediaPermissions\(ses\);/,
  );
});

function setup() {
  const events = [];
  const prompt = createPermissionPrompt({ onChange: (ev) => events.push(ev) });
  const ses = fakeSession();
  applyBrowserPermissions(ses, prompt);
  const ask = (url, wc = null, permission = 'local-network-access') => {
    const out = { value: undefined };
    ses.request(wc, permission, (ok) => (out.value = ok), { requestingUrl: url });
    return out;
  };
  const settle = () => new Promise((r) => setImmediate(r));
  return { events, prompt, ses, ask, settle };
}

test('a local-network request shows the bar and waits for an answer', async () => {
  const { events, prompt, ask, settle } = setup();
  const r = ask('https://sso.example.com/login');
  await settle();
  assert.deepStrictEqual(events, [{ type: 'show', host: 'sso.example.com' }]);
  assert.strictEqual(r.value, undefined);
  prompt.answer(true);
  await settle();
  assert.strictEqual(r.value, true);
  assert.deepStrictEqual(events[1], { type: 'closed', host: 'sso.example.com', allowed: true });
});

test('Not now denies, and Allow this time is not remembered', async () => {
  const { events, prompt, ask, settle } = setup();
  const first = ask('https://sso.example.com/');
  prompt.answer(false);
  await settle();
  assert.strictEqual(first.value, false);
  const second = ask('https://sso.example.com/');
  await settle();
  assert.strictEqual(second.value, undefined, 'asks again');
  prompt.answer(true);
  await settle();
  assert.strictEqual(second.value, true);
  const third = ask('https://sso.example.com/');
  await settle();
  assert.strictEqual(third.value, undefined, 'still asks after an allow');
  assert.strictEqual(events.filter((e) => e.type === 'show').length, 3);
});

test('no other permission ever prompts', async () => {
  const { events, ask, settle } = setup();
  for (const p of PERMISSIONS.filter((x) => x !== 'local-network-access')) {
    const r = ask('https://sso.example.com/', null, p);
    await settle();
    assert.strictEqual(r.value, false, p);
  }
  assert.deepStrictEqual(events, []);
});

test('non-web origins and a missing URL are denied without prompting', async () => {
  const { events, ask, settle } = setup();
  for (const url of ['file:///C:/x.html', 'chrome://settings', 'not a url', undefined]) {
    const r = ask(url);
    await settle();
    assert.strictEqual(r.value, false, String(url));
  }
  assert.deepStrictEqual(events, []);
});

test('the permission check stays denied even after an allow', async () => {
  const { ses, prompt, ask, settle } = setup();
  ask('https://sso.example.com/');
  prompt.answer(true);
  await settle();
  assert.strictEqual(ses.check(null, 'local-network-access', 'https://sso.example.com'), false);
});

test('a second site queues behind the first and shows after it closes', async () => {
  const { events, prompt, ask, settle } = setup();
  const a = ask('https://a.example.com/');
  const b = ask('https://b.example.com/');
  await settle();
  assert.deepStrictEqual(events, [{ type: 'show', host: 'a.example.com' }]);
  prompt.answer(true);
  await settle();
  assert.strictEqual(a.value, true);
  assert.strictEqual(b.value, undefined);
  assert.deepStrictEqual(
    events.slice(1).map((e) => `${e.type}:${e.host}`),
    ['closed:a.example.com', 'show:b.example.com'],
  );
  prompt.answer(false);
  await settle();
  assert.strictEqual(b.value, false);
});

test('repeat requests from one origin share a single prompt and answer', async () => {
  const { events, prompt, ask, settle } = setup();
  const a = ask('https://sso.example.com/a');
  const b = ask('https://sso.example.com/b');
  await settle();
  assert.strictEqual(events.filter((e) => e.type === 'show').length, 1);
  prompt.answer(true);
  await settle();
  assert.strictEqual(a.value, true);
  assert.strictEqual(b.value, true);
});

test('navigating the asking page away denies and closes the bar', async () => {
  const { events, ask, settle } = setup();
  const wc = new EventEmitter();
  const r = ask('https://sso.example.com/', wc);
  await settle();
  wc.emit('did-start-navigation', {}, 'https://elsewhere.example.com/', false, true);
  await settle();
  assert.strictEqual(r.value, false);
  assert.deepStrictEqual(events[1], { type: 'closed', host: 'sso.example.com', allowed: false });
});

test('same-document navigation and subframe loads keep the prompt open', async () => {
  const { events, prompt, ask, settle } = setup();
  const wc = new EventEmitter();
  const r = ask('https://sso.example.com/', wc);
  await settle();
  wc.emit('did-start-navigation', {}, 'https://sso.example.com/#x', true, true);
  wc.emit('did-start-navigation', {}, 'https://ads.example.com/', false, false);
  await settle();
  assert.strictEqual(r.value, undefined);
  assert.strictEqual(events.length, 1);
  prompt.answer(true);
  await settle();
  assert.strictEqual(r.value, true);
});

test('navigation events in the single-argument shape also deny', async () => {
  const { ask, settle } = setup();
  const wc = new EventEmitter();
  const r = ask('https://sso.example.com/', wc);
  await settle();
  wc.emit('did-start-navigation', {
    url: 'https://x.example.com/',
    isMainFrame: true,
    isSameDocument: false,
  });
  await settle();
  assert.strictEqual(r.value, false);
});

test('closing the asking window denies, and a queued entry whose page left is dropped', async () => {
  const { events, prompt, ask, settle } = setup();
  const wcA = new EventEmitter();
  const wcB = new EventEmitter();
  const a = ask('https://a.example.com/', wcA);
  const b = ask('https://b.example.com/', wcB);
  await settle();
  wcB.emit('destroyed');
  await settle();
  assert.strictEqual(b.value, false);
  assert.deepStrictEqual(events, [{ type: 'show', host: 'a.example.com' }]);
  wcA.emit('destroyed');
  await settle();
  assert.strictEqual(a.value, false);
  assert.deepStrictEqual(events[1], { type: 'closed', host: 'a.example.com', allowed: false });
  assert.strictEqual(prompt.host(), '');
});

test('answering releases the page listeners', async () => {
  const { prompt, ask, settle } = setup();
  const wc = new EventEmitter();
  ask('https://sso.example.com/', wc);
  await settle();
  assert.strictEqual(wc.listenerCount('did-start-navigation'), 1);
  prompt.answer(true);
  await settle();
  assert.strictEqual(wc.listenerCount('did-start-navigation'), 0);
  assert.strictEqual(wc.listenerCount('destroyed'), 0);
});

test('only an explicit true allows', async () => {
  const { prompt, ask, settle } = setup();
  const r = ask('https://sso.example.com/');
  prompt.answer('yes');
  await settle();
  assert.strictEqual(r.value, false);
});

test('main.js wires the bar: answer channels are main-toolbar only, Esc closes it before pick mode', () => {
  const main = fs.readFileSync(path.join(__dirname, '../shell/main.js'), 'utf8');
  for (const ch of ['toolbar:permission-answer', 'toolbar:permission-height']) {
    const i = main.indexOf(`ipcMain.on('${ch}'`);
    assert.ok(i >= 0, ch);
    assert.match(main.slice(i, i + 150), /_isMainToolbar\(e\)/, ch);
  }
  assert.match(main, /_browserPrompt\.answer\(false\)/);
  assert.match(main, /_permBarH/);
  const top = main.match(/const top = TOOLBAR_H \+ _permBarOffset\(\);/g) || [];
  assert.strictEqual(top.length, 2, 'both layout branches push the pane down');
  assert.match(main, /permHost: _permBarShown\(\) \? _permBarHost : ''/);
  const webPin = fs.readFileSync(path.join(__dirname, '../shell/web-pin.js'), 'utf8');
  assert.match(
    webPin,
    /if \(event\.defaultPrevented\) return;\s*event\.preventDefault\(\);\s*stop\(CANCELLED\)/,
  );
});

test('toolbar renders the bar with the agreed copy, button order and Esc handling', () => {
  const tb = fs.readFileSync(path.join(__dirname, '../shell/toolbar.html'), 'utf8');
  assert.match(tb, /wants to connect to devices on your local network\./);
  assert.match(tb, /Some company sign-in checks need this\./);
  assert.match(tb, /id="tb-pbar-no">Not now<[\s\S]*id="tb-pbar-yes">Allow this time</);
  assert.match(tb, /role="group"/);
  assert.match(tb, /@container \(max-width: 520px\)/);
  assert.match(tb, /@container \(max-width: 300px\)/);
  assert.match(tb, /if \(e\.key === 'Escape' && permOpen\(\)\) \{[\s\S]{0,80}answerPerm\(false\)/);
  assert.match(tb, /renderPerm\(state\)/);
  assert.match(tb, /'toolbar:permission-answer'/);
  assert.match(tb, /'toolbar:permission-height'/);
});

test('popup windows opened from a pane are sandboxed with isolation and no node', () => {
  const src = fs.readFileSync(path.join(__dirname, '../shell/navigation-policy.js'), 'utf8');
  const blocks = src.match(/session: parentSession,[^}]*\}/g) || [];
  assert.ok(blocks.length >= 3);
  for (const b of blocks) {
    assert.match(b, /contextIsolation: true/);
    assert.match(b, /nodeIntegration: false/);
    assert.match(b, /sandbox: true/);
  }
});
