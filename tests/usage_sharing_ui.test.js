// Usage sharing UI: the notice answers only on a button, Esc decides later, toggle-on asks first.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'usage-sharing.js'),
  'utf8',
);

class El {
  constructor(tag) {
    this.tag = tag;
    this.attrs = {};
    this.children = [];
    this.listeners = {};
    this.parent = null;
    this.className = '';
    this.textContent = '';
    this.hidden = false;
    this.checked = false;
  }
  get tagName() {
    return this.tag.toUpperCase();
  }
  appendChild(child) {
    child.parent = this;
    this.children.push(child);
    return child;
  }
  setAttribute(name, value) {
    this.attrs[name] = value;
  }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  fire(type, event = {}) {
    (this.listeners[type] || []).forEach((fn) => fn({ preventDefault() {}, ...event }));
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this);
    this.parent = null;
  }
  focus() {
    this.ownerDocument.activeElement = this;
  }
  walk(visit) {
    visit(this);
    this.children.forEach((c) => c.walk(visit));
  }
  querySelectorAll(selector) {
    assert.strictEqual(selector, 'button');
    const found = [];
    this.walk((n) => n !== this && n.tag === 'button' && found.push(n));
    return found;
  }
}

function setup(status) {
  const document = { activeElement: null, readyState: 'complete' };
  const make = (tag) => {
    const el = new El(tag);
    el.ownerDocument = document;
    return el;
  };
  document.body = make('body');
  document.createElement = make;
  const byId = {};
  for (const id of [
    'usage-sharing-section',
    'usage-sharing-toggle',
    'usage-sharing-status',
    'usage-sharing-review',
  ]) {
    byId[id] = make('div');
    document.body.appendChild(byId[id]);
  }
  document.getElementById = (id) => byId[id] || null;
  document.querySelector = (selector) => {
    const cls = selector.slice(1);
    let hit = null;
    document.body.walk((n) => {
      if (!hit && n.className.split(' ').includes(cls)) hit = n;
    });
    return hit;
  };
  document.contains = () => true;
  document.addEventListener = () => {};

  const posts = [];
  const timers = [];
  let state = { ...status };
  const window = { __CSRF_TOKEN__: 'aigator-fake-api-key' };
  const ctx = {
    window,
    document,
    Array,
    Object,
    JSON,
    Date,
    isNaN,
    Error,
    clearTimeout() {},
    setTimeout(fn, ms) {
      timers.push({ fn, ms });
      return timers.length;
    },
    fetch: async (url, opts = {}) => {
      if (opts.method === 'POST') {
        const body = JSON.parse(opts.body);
        posts.push({ url, body, headers: opts.headers });
        state = {
          ...state,
          consent: body.enabled ? 'on' : 'off',
          status: body.enabled ? 'waiting' : 'off',
        };
      }
      return { ok: true, status: 200, json: async () => state };
    },
  };
  vm.runInNewContext(source, ctx);
  return { ctx, document, byId, posts, timers };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));
const UNSET = { available: true, consent: 'unset', status: 'not_started', last_sent_at: null };

function overlay(document) {
  return document.querySelector('.usage-notice-overlay');
}
function buttonByText(host, text) {
  return host.querySelectorAll('button').find((b) => b.textContent === text);
}

(async () => {
  // Hidden when an admin has not made reporting available.
  let t = setup({ available: false, consent: 'unset', status: 'off', last_sent_at: null });
  await flush();
  assert.strictEqual(t.byId['usage-sharing-section'].hidden, true);
  assert.strictEqual(t.timers.length > 0, true);
  t.timers[0].fn();
  assert.strictEqual(overlay(t.document), null, 'no notice when reporting is unavailable');

  // First run: the notice opens, Esc decides later, nothing is saved.
  t = setup(UNSET);
  await flush();
  assert.strictEqual(t.byId['usage-sharing-section'].hidden, false);
  assert.strictEqual(t.byId['usage-sharing-toggle'].checked, false);
  t.timers[0].fn();
  let host = overlay(t.document);
  assert(host, 'notice opens on first run');
  const box = host.children[0];
  assert.strictEqual(box.attrs.role, 'dialog');
  assert.strictEqual(box.attrs['aria-modal'], 'true');
  host.fire('keydown', { key: 'Escape' });
  assert.strictEqual(overlay(t.document), null, 'Esc closes the notice');
  assert.strictEqual(t.posts.length, 0, 'Esc saves nothing');
  assert.strictEqual(host.listeners.click, undefined, 'a backdrop click never answers');

  // Toggling on before answering opens the notice first; Keep sharing saves and turns it on.
  const toggle = t.byId['usage-sharing-toggle'];
  toggle.checked = true;
  toggle.fire('change');
  await flush();
  assert.strictEqual(toggle.checked, false, 'toggle waits for the answer');
  assert.strictEqual(t.posts.length, 0);
  host = overlay(t.document);
  assert(host, 'notice opens from the toggle');
  buttonByText(host, 'Keep sharing').fire('click');
  await flush();
  assert.strictEqual(t.posts.length, 1);
  assert.deepStrictEqual(t.posts[0].body, { enabled: true });
  assert.strictEqual(t.posts[0].headers['X-CSRF-Token'], 'aigator-fake-api-key');
  assert.strictEqual(toggle.checked, true);
  assert.strictEqual(overlay(t.document), null);

  // Once answered, the toggle saves directly.
  toggle.checked = false;
  toggle.fire('change');
  await flush();
  assert.deepStrictEqual(t.posts[1].body, { enabled: false });
  assert.strictEqual(overlay(t.document), null);

  // Turn off in the notice saves the off answer.
  t = setup(UNSET);
  await flush();
  t.timers[0].fn();
  buttonByText(overlay(t.document), 'Turn off').fire('click');
  await flush();
  assert.deepStrictEqual(t.posts[0].body, { enabled: false });
  assert(t.document.getElementById('usage-sharing-status').textContent.startsWith('Off'));

  // The read-only version has one Close button and no choice.
  t = setup({
    available: true,
    consent: 'on',
    status: 'sent',
    last_sent_at: '2026-11-10T09:42:00+00:00',
  });
  await flush();
  assert(t.byId['usage-sharing-status'].textContent.startsWith('Sent.'));
  t.byId['usage-sharing-review'].fire('click');
  host = overlay(t.document);
  assert.deepStrictEqual(
    host.querySelectorAll('button').map((b) => b.textContent),
    ['Close'],
  );
  host.fire('keydown', { key: 'Escape' });
  assert.strictEqual(overlay(t.document), null);
  assert.strictEqual(t.posts.length, 0);

  console.log('usage_sharing_ui ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
