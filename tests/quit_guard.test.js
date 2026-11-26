const assert = require('assert');
const test = require('node:test');

const { confirmQuit, quitCopy } = require('../shell/quit-guard');

function backend(running) {
  const calls = [];
  const request = async (method, path) => {
    calls.push(`${method} ${path}`);
    if (path === '/api/host-shell/status') return { state: 'on', running };
    if (path === '/api/csrf') return { csrf_token: 'aigator-fake-api-key' };
    return { ok: true };
  };
  return { request, calls };
}

test('the confirm names the count and puts Cancel first in line', () => {
  const one = quitCopy(1);
  assert.strictEqual(one.message, 'Quit and stop 1 running command?');
  assert.strictEqual(quitCopy(3).message, 'Quit and stop 3 running commands?');
  assert.deepStrictEqual(one.buttons, ['Quit and stop', 'Cancel']);
  assert.strictEqual(one.defaultId, 1);
  assert.strictEqual(one.cancelId, 1);
});

test('quits at once, without asking, when nothing is running', async () => {
  const { request, calls } = backend([]);
  let asked = 0;
  const ok = await confirmQuit({
    backendRequest: request,
    showConfirm: async () => (asked++, { response: 0 }),
  });
  assert.strictEqual(ok, true);
  assert.strictEqual(asked, 0);
  assert.deepStrictEqual(calls, ['GET /api/host-shell/status']);
});

test('asks once and stops every command before quitting when the user agrees', async () => {
  const { request, calls } = backend([{ request_id: 'a' }, { request_id: 'b' }]);
  const shown = [];
  const ok = await confirmQuit({
    backendRequest: request,
    showConfirm: async (options) => (shown.push(options), { response: 0 }),
  });
  assert.strictEqual(ok, true);
  assert.strictEqual(shown.length, 1);
  assert.strictEqual(shown[0].message, 'Quit and stop 2 running commands?');
  assert.deepStrictEqual(calls, [
    'GET /api/host-shell/status',
    'GET /api/csrf',
    'POST /api/host-shell/stop-all',
  ]);
});

test('Cancel keeps the app open and stops nothing', async () => {
  const { request, calls } = backend([{ request_id: 'a' }]);
  const ok = await confirmQuit({
    backendRequest: request,
    showConfirm: async () => ({ response: 1 }),
  });
  assert.strictEqual(ok, false);
  assert.deepStrictEqual(calls, ['GET /api/host-shell/status']);
});

test('an unreachable backend does not block quitting', async () => {
  const ok = await confirmQuit({
    backendRequest: async () => {
      throw new Error('ECONNREFUSED');
    },
    showConfirm: async () => ({ response: 1 }),
  });
  assert.strictEqual(ok, true);
});
