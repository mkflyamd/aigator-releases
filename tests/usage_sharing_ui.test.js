// Usage sharing UI: informational notice with one OK, locked toggle, no network writes.

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
    this.disabled = false;
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

function setup(status, acked = false) {
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
  const state = { ...status };
  const store = { ...(acked ? { 'aigator.usageNoticeAck': '1' } : {}) };
  const window = {
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => {
        store[k] = String(v);
      },
    },
  };
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
      if (opts.method && opts.method !== 'GET') posts.push({ url, method: opts.method });
      return { ok: true, status: 200, json: async () => state };
    },
  };
  vm.runInNewContext(source, ctx);
  return { ctx, document, byId, posts, timers, store };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));
const WAITING = { available: true, status: 'waiting', last_sent_at: null };

function overlay(document) {
  return document.querySelector('.usage-notice-overlay');
}
function buttonByText(host, text) {
  return host.querySelectorAll('button').find((b) => b.textContent === text);
}

function textOf(node) {
  let out = node.textContent || '';
  node.children.forEach((c) => {
    out += ' ' + textOf(c);
  });
  return out;
}

(async () => {
  // Hidden when an admin has not made reporting available.
  let t = setup({ available: false, status: 'off', last_sent_at: null });
  await flush();
  assert.strictEqual(t.byId['usage-sharing-section'].hidden, true);
  t.timers[0].fn();
  assert.strictEqual(overlay(t.document), null, 'no notice when reporting is unavailable');

  // First run: informational notice with one OK button and two fact rows.
  t = setup(WAITING);
  await flush();
  assert.strictEqual(t.byId['usage-sharing-section'].hidden, false);
  t.timers[0].fn();
  let host = overlay(t.document);
  assert(host, 'notice opens on first run');
  const box = host.children[0];
  assert.strictEqual(box.attrs.role, 'dialog');
  assert.strictEqual(box.attrs['aria-modal'], 'true');
  assert.deepStrictEqual(
    host.querySelectorAll('button').map((b) => b.textContent),
    ['OK'],
  );
  const labels = [];
  host.walk((n) => n.tag === 'dt' && labels.push(n.textContent));
  assert.deepStrictEqual(labels, ['What is sent', 'Never sent']);
  const noticeText = textOf(host);
  assert(noticeText.includes('Account info'));
  assert(!noticeText.includes('email'), 'the notice does not say email');
  assert(!/sharepoint/i.test(noticeText), 'the notice does not name SharePoint');
  assert(!/turn (it )?off|keep sharing/i.test(noticeText), 'no opt-out wording');

  // Esc closes without acknowledging, so the notice returns next launch.
  host.fire('keydown', { key: 'Escape' });
  assert.strictEqual(overlay(t.document), null);
  assert.strictEqual(t.store['aigator.usageNoticeAck'], undefined);

  // OK acknowledges and closes.
  t.byId['usage-sharing-review'].fire('click');
  buttonByText(overlay(t.document), 'Close').fire('click');
  assert.strictEqual(overlay(t.document), null);
  t = setup(WAITING);
  await flush();
  t.timers[0].fn();
  buttonByText(overlay(t.document), 'OK').fire('click');
  assert.strictEqual(overlay(t.document), null);
  assert.strictEqual(t.store['aigator.usageNoticeAck'], '1');

  // Once acknowledged the notice does not return.
  t = setup(WAITING, true);
  await flush();
  t.timers[0].fn();
  assert.strictEqual(overlay(t.document), null);

  // The Settings toggle is rendered locked on and never makes a request.
  const toggle = t.byId['usage-sharing-toggle'];
  assert.strictEqual(toggle.listeners.change, undefined, 'toggle has no handler');
  toggle.checked = false;
  toggle.fire('change');
  await flush();
  assert.strictEqual(t.posts.length, 0);

  // Status text never names the storage backend.
  const statuses = ['waiting', 'delayed', 'signin', 'sent'];
  for (const status of statuses) {
    t = setup({ available: true, status, last_sent_at: '2026-11-10T09:42:00+00:00' }, true);
    await flush();
    const line = t.byId['usage-sharing-status'].textContent;
    assert(line.length > 0, status + ' has text');
    assert(!/sharepoint/i.test(line), status + ' text does not name SharePoint');
  }

  // The read-only version has one Close button and no choice.
  t = setup({ available: true, status: 'sent', last_sent_at: '2026-11-10T09:42:00+00:00' }, true);
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

  // Settings markup: the toggle ships checked and disabled, and the section never names SharePoint.
  const html = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'index.html'), 'utf8');
  const section = html.slice(html.indexOf('id="usage-sharing-section"'));
  const sectionEnd = section.slice(0, section.indexOf('<!-- Browser Engine -->'));
  const input = sectionEnd.match(/<input[^>]*id="usage-sharing-toggle"[^>]*>/)[0];
  assert(/\schecked\s/.test(input) && /\sdisabled\s/.test(input));
  assert(!/sharepoint/i.test(sectionEnd));

  console.log('usage_sharing_ui ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
