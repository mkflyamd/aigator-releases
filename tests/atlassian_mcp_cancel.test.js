// The Atlassian MCP connect button's × must cancel while signing in, and must not be offered once the
// site is being saved (the server keeps what it saved, so "cancelled" would be a lie).
// The real helper and click handler are cut out of app.js and run against a stub DOM.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs
  .readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8')
  .replace(/\r\n/g, '\n');

function between(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert(start >= 0, `${startMarker} found`);
  const end = source.indexOf(endMarker, start);
  assert(end > start, `${endMarker} found`);
  return source.slice(start, end);
}

const helperSource = between(
  'function _setAtlassianMcpConnectState',
  'async function loadAtlassianStatus',
);
const handlerSource = between('if (atlassianAddSiteBtn)\n', '/* ── GitHub');

function makeElement(parent = null) {
  const el = {
    parentElement: parent,
    children: [],
    listeners: {},
    dataset: {},
    attrs: {},
    textContent: '',
    disabled: false,
    classList: { toggle() {} },
    setAttribute(k, v) {
      this.attrs[k] = v;
    },
    addEventListener(type, fn) {
      this.listeners[type] = fn;
    },
    append(child) {
      child.parentElement = this;
      this.children.push(child);
    },
    querySelector(sel) {
      return this.children.find((c) => '.' + c.className === sel) || null;
    },
    remove() {
      if (this.parentElement) {
        this.parentElement.children = this.parentElement.children.filter((c) => c !== this);
      }
    },
  };
  return el;
}

function makeEnv(fetchImpl) {
  const wrap = makeElement();
  const button = makeElement(wrap);
  wrap.children.push(button);
  button.textContent = 'Connect Atlassian MCP';
  const ctx = {
    atlassianAddSiteBtn: button,
    atlassianMsg: { textContent: '' },
    document: { createElement: () => makeElement() },
    window: { open: () => ({ closed: false, close() {}, location: {} }), __CSRF_TOKEN__: '' },
    fetch: fetchImpl,
    AbortController,
    setInterval: (fn) => setInterval(fn, 1),
    clearInterval,
    setTimeout,
    clearTimeout,
    encodeURIComponent,
    String,
    Promise,
    Error,
    wrap,
    button,
  };
  vm.createContext(ctx);
  vm.runInContext(helperSource, ctx);
  vm.runInContext(handlerSource, ctx);
  return ctx;
}

const json = (data, ok = true) => Promise.resolve({ ok, json: () => Promise.resolve(data) });
const cancelOf = (env) => env.wrap.querySelector('.atlassian-mcp-cancel');
const tick = (ms = 20) => new Promise((r) => setTimeout(r, ms));

(async () => {
  // While signing in, × exists and clicking it aborts the flow and restores the button.
  {
    const calls = [];
    const env = makeEnv((url, opts = {}) => {
      calls.push({ url, opts });
      if (url.includes('oauth/start'))
        return json({ authorize_url: 'https://auth', state: 's1', provider_id: 'p1' });
      if (url.includes('oauth/poll')) return json({ status: 'pending' });
      throw new Error('unexpected ' + url);
    });
    env.button.listeners.click();
    await tick();
    const cancel = cancelOf(env);
    assert(cancel, '× is offered while signing in');
    assert.strictEqual(cancel.textContent, '×');
    cancel.listeners.click();
    await tick();
    assert.strictEqual(cancelOf(env), null, '× is gone after cancel');
    assert.strictEqual(env.button.disabled, false);
    assert.strictEqual(env.atlassianMsg.textContent, 'Atlassian MCP connection cancelled.');
    assert(!calls.some((c) => c.url === '/api/config/mcp'), 'nothing was saved');
  }

  // Once sign-in finishes and the site is being saved, × is gone and the save is not abortable.
  {
    const calls = [];
    let finishSave;
    const env = makeEnv((url, opts = {}) => {
      calls.push({ url, opts });
      if (url.includes('oauth/start'))
        return json({ authorize_url: 'https://auth', state: 's1', provider_id: 'p1' });
      if (url.includes('oauth/poll')) return json({ status: 'done', ok: true });
      if (url === '/api/config/mcp')
        return new Promise(
          (resolve) =>
            (finishSave = () =>
              resolve({ ok: true, json: () => Promise.resolve({ ok: true, tool_count: 3 }) })),
        );
      return json({});
    });
    env.button.listeners.click();
    await tick(40);
    assert(
      calls.some((c) => c.url === '/api/config/mcp'),
      'save started',
    );
    assert.strictEqual(cancelOf(env), null, '× is not offered while saving');
    assert.strictEqual(env.button.disabled, true);
    const save = calls.find((c) => c.url === '/api/config/mcp');
    assert.strictEqual(save.opts.signal, undefined, 'save request cannot be aborted');
    finishSave();
    await tick(40);
    assert(env.atlassianMsg.textContent.startsWith('Connected.'));
  }

  console.log('atlassian_mcp_cancel: ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
