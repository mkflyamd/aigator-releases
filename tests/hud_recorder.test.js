// Floating HUD widgets are model-written HTML. They must not be able to start, stop or steer a
// screen recording without the user's consent, and must never hold the backend CSRF token.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { test } = require('node:test');
const {
  HUD_RECORDER_ACTIONS,
  hudRecorderParams,
  createHudRecorder,
} = require('../shell/hud_recorder');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', ...p), 'utf8');

function makeRecorder({ allow = true, idleMs, clock } = {}) {
  const requests = [];
  const asked = [];
  const rec = createHudRecorder({
    confirm: async (id) => {
      asked.push(id);
      return typeof allow === 'function' ? allow() : allow;
    },
    request: async (action, params) => {
      requests.push({ action, params });
      return { ok: true };
    },
    ...(clock ? { now: clock } : {}),
    ...(idleMs ? { idleMs } : {}),
  });
  return { rec, requests, asked };
}

test('a denied consent sends nothing to the backend', async () => {
  const { rec, requests } = makeRecorder({ allow: false });
  const r = await rec.handle(1, 'start', { screen_index: 0, force: true });
  assert.strictEqual(r.ok, false);
  assert(r.error.includes('not allowed'));
  assert.strictEqual(requests.length, 0);
});

test('a consent dialog that throws counts as denied', async () => {
  const { rec, requests } = makeRecorder({
    allow: () => {
      throw new Error('boom');
    },
  });
  assert.strictEqual((await rec.handle(1, 'stop')).ok, false);
  assert.strictEqual(requests.length, 0);
});

test('only an explicit true from the dialog allows the request', async () => {
  for (const answer of ['yes', 1, {}, undefined]) {
    const { rec, requests } = makeRecorder({ allow: () => answer });
    assert.strictEqual((await rec.handle(1, 'stop')).ok, false);
    assert.strictEqual(requests.length, 0);
  }
});

test('an allowed window is asked once, then reuses the grant', async () => {
  const { rec, requests, asked } = makeRecorder();
  await rec.handle(7, 'start', { force: true });
  await rec.handle(7, 'pause');
  await rec.handle(7, 'stop');
  assert.deepStrictEqual(asked, [7]);
  assert.deepStrictEqual(
    requests.map((r) => r.action),
    ['start', 'pause', 'stop'],
  );
});

test('a grant belongs to one window and does not carry to another', async () => {
  const { rec, asked } = makeRecorder();
  await rec.handle(1, 'stop');
  await rec.handle(2, 'stop');
  assert.deepStrictEqual(asked, [1, 2]);
});

test('concurrent calls from one window share a single consent dialog', async () => {
  const { rec, requests, asked } = makeRecorder();
  await Promise.all([rec.handle(3, 'start'), rec.handle(3, 'pause'), rec.handle(3, 'stop')]);
  assert.deepStrictEqual(asked, [3]);
  assert.strictEqual(requests.length, 3);
});

test('the grant lapses after idle time and when the window is forgotten', async () => {
  let t = 1000;
  const { rec, asked } = makeRecorder({ idleMs: 100, clock: () => t });
  await rec.handle(1, 'stop');
  t += 50;
  await rec.handle(1, 'stop');
  assert.strictEqual(asked.length, 1, 'activity keeps the grant alive');
  t += 500;
  await rec.handle(1, 'stop');
  assert.strictEqual(asked.length, 2, 'idle expiry asks again');
  rec.forget(1);
  await rec.handle(1, 'stop');
  assert.strictEqual(asked.length, 3, 'closing the window drops the grant');
});

test('unknown actions are refused before any dialog or request', async () => {
  const { rec, requests, asked } = makeRecorder();
  for (const action of [
    'notify',
    'tts-preview',
    'status',
    '__proto__',
    'constructor',
    42,
    undefined,
  ]) {
    const r = await rec.handle(1, action, {});
    assert.strictEqual(r.ok, false);
    assert.strictEqual(r.error, 'unknown recorder action');
  }
  assert.strictEqual(asked.length, 0);
  assert.strictEqual(requests.length, 0);
});

test('parameters are limited to the documented names and types', async () => {
  const { rec, requests } = makeRecorder();
  await rec.handle(1, 'start', { screen_index: 1, force: true, evil: 'x', crop_w: 640 });
  assert.deepStrictEqual(requests[0].params, { screen_index: 1, force: true, crop_w: 640 });
  for (const bad of [
    { screen_index: '1' },
    { screen_index: Infinity },
    { screen_index: NaN },
    { force: 'true' },
  ]) {
    const r = await rec.handle(1, 'start', bad);
    assert.strictEqual(r.error, 'invalid parameters');
  }
  assert.strictEqual(requests.length, 1);
  assert.deepStrictEqual(hudRecorderParams(HUD_RECORDER_ACTIONS.stop, { anything: 1 }), {});
});

test('a backend failure is returned as an error, not thrown', async () => {
  const rec = createHudRecorder({
    confirm: async () => true,
    request: async () => {
      throw new Error('connect ECONNREFUSED');
    },
  });
  const r = await rec.handle(1, 'stop');
  assert.deepStrictEqual(r, { ok: false, error: 'connect ECONNREFUSED' });
});

test('the allow-list matches the in-chat bridge so both paths accept the same calls', () => {
  const app = read('web', 'static', 'app.js');
  const block = app.slice(
    app.indexOf('const GATOR_RECORDER_ACTIONS'),
    app.indexOf('const GATOR_RECORDER_GRANT_IDLE_MS'),
  );
  for (const [action, spec] of Object.entries(HUD_RECORDER_ACTIONS)) {
    const m = block.match(
      new RegExp("'?" + action + "'?:\\s*\\{\\s*method: 'POST',\\s*params: \\{([^}]*)\\}"),
    );
    assert(m, action + ' is a POST action in app.js');
    const keys = [...m[1].matchAll(/(\w+):\s*'(\w+)'/g)].map((x) => x[1] + ':' + x[2]).sort();
    const mine = Object.entries(spec)
      .map(([k, v]) => k + ':' + v)
      .sort();
    assert.deepStrictEqual(mine, keys, action + ' params match');
  }
});

test('the HUD window cannot reach the backend with the shell key or CSRF token', () => {
  const main = read('shell', 'main.js');
  const hudStart = main.indexOf("ipcMain.handle('widget:open-hud'");
  const hudBlock = main.slice(hudStart, hudStart + 1500);
  assert(/partition:\s*'persist:gator-hud'/.test(hudBlock), 'HUD uses its own session');
  assert(!/session\.defaultSession/.test(hudBlock));
  assert(!/SHELL_KEY|csrf/i.test(hudBlock), 'HUD window setup never touches secrets');
  const html = main.slice(hudStart);
  assert(!/window\._CSRF|__CSRF_TOKEN__/.test(html.slice(0, html.indexOf('app.whenReady'))));
});

test('only registered HUD windows can use the recorder IPC, and it is exposed through the preload', () => {
  const main = read('shell', 'main.js');
  assert(
    /ipcMain\.handle\('hud:recorder'[\s\S]{0,200}_hudContentsIds\.has\(e\.sender\.id\)/.test(main),
  );
  assert(
    /recorder:\s*\(action, params\) => ipcRenderer\.invoke\('hud:recorder'/.test(
      read('shell', 'hud-preload.js'),
    ),
  );
  const pkg = JSON.parse(read('shell', 'package.json'));
  assert(pkg.build.files.includes('hud_recorder.js'));
  assert(pkg.build.files.includes('hud-preload.js'));
});

test('recorder POSTs from the shell carry a CSRF token fetched with the shell key', () => {
  const main = read('shell', 'main.js');
  assert(/X-AIGator-Shell-Key/.test(main.slice(main.indexOf('function _backendRequest'))));
  const post = main.slice(
    main.indexOf('async function _recorderPost'),
    main.indexOf('function _recorderApi'),
  );
  assert(/\/api\/csrf/.test(post) && /X-CSRF-Token/.test(post));
});
