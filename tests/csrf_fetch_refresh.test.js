// The page-wide fetch wrapper re-reads the CSRF token and retries once when the backend restarted.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const match = source.match(/\(function _initCsrfFetch\(\) \{[\s\S]*?\r?\n\}\)\(\);/);
assert(match, '_initCsrfFetch found in app.js');

function setup({ serverToken, csrfEndpointOk = true }) {
  const calls = [];
  const window = { __CSRF_TOKEN__: 'stale-token' };
  const fakeFetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input.url;
    const headers = new Headers((init && init.headers) || undefined);
    calls.push({ url, method: (init && init.method) || 'GET', token: headers.get('X-CSRF-Token') });
    if (url === '/api/csrf') {
      return csrfEndpointOk
        ? { ok: true, status: 200, json: async () => ({ csrf_token: serverToken }) }
        : { ok: false, status: 401, json: async () => ({}) };
    }
    if (url.startsWith('/api/') && init && init.method && init.method !== 'GET') {
      const ok = headers.get('X-CSRF-Token') === serverToken;
      return { ok, status: ok ? 200 : 403, json: async () => ({ unpinned: ok }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };
  window.fetch = fakeFetch;
  vm.runInNewContext(match[0], { window, Headers });
  return { window, calls };
}

(async () => {
  // A stale token is refreshed once and the original request is retried with the new one.
  {
    const { window, calls } = setup({ serverToken: 'fresh-token' });
    const res = await window.fetch('/api/context/pin/jira/ABC-1?context_id=t1', {
      method: 'DELETE',
    });
    assert.strictEqual(res.status, 200);
    assert.deepStrictEqual(
      calls.map((c) => [c.url, c.token]),
      [
        ['/api/context/pin/jira/ABC-1?context_id=t1', 'stale-token'],
        ['/api/csrf', null],
        ['/api/context/pin/jira/ABC-1?context_id=t1', 'fresh-token'],
      ],
    );
    assert.strictEqual(window.__CSRF_TOKEN__, 'fresh-token', 'later calls use the new token');
  }

  // A valid token goes straight through with no refresh.
  {
    const { window, calls } = setup({ serverToken: 'stale-token' });
    const res = await window.fetch('/api/x', { method: 'POST' });
    assert.strictEqual(res.status, 200);
    assert.strictEqual(calls.length, 1);
  }

  // A 403 that a new token cannot fix is returned as-is, with no retry loop.
  {
    const { window, calls } = setup({ serverToken: 'stale-token' });
    const forbidden = async (input, init) => {
      calls.push({ url: typeof input === 'string' ? input : input.url });
      if (input === '/api/csrf')
        return { ok: true, status: 200, json: async () => ({ csrf_token: 'stale-token' }) };
      return { ok: false, status: 403, json: async () => ({}) };
    };
    const w2 = { __CSRF_TOKEN__: 'stale-token', fetch: forbidden };
    vm.runInNewContext(match[0], { window: w2, Headers });
    const res = await w2.fetch('/api/x', { method: 'POST' });
    assert.strictEqual(res.status, 403);
    assert.strictEqual(calls.filter((c) => c.url === '/api/x').length, 1);
  }

  // If the token cannot be re-read, the original 403 comes back.
  {
    const { window, calls } = setup({ serverToken: 'fresh-token', csrfEndpointOk: false });
    const res = await window.fetch('/api/x', { method: 'DELETE' });
    assert.strictEqual(res.status, 403);
    assert.strictEqual(calls.filter((c) => c.url === '/api/x').length, 1);
  }

  // GET requests are left alone.
  {
    const { window, calls } = setup({ serverToken: 'fresh-token' });
    await window.fetch('/api/context/pins?context_id=t1');
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].token, null);
  }

  // Several stale requests at once share a single token refresh.
  {
    const { window, calls } = setup({ serverToken: 'fresh-token' });
    const results = await Promise.all([
      window.fetch('/api/a', { method: 'POST' }),
      window.fetch('/api/b', { method: 'DELETE' }),
      window.fetch('/api/c', { method: 'PUT' }),
    ]);
    assert(results.every((r) => r.status === 200));
    assert.strictEqual(calls.filter((c) => c.url === '/api/csrf').length, 1);
  }

  console.log('csrf_fetch_refresh ok');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
