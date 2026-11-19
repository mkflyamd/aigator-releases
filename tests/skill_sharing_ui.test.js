'use strict';

// Share modal tests. jsdom is not available in this repo, so this uses the
// same approach as marketplace_p0_dom_render.test.js: a small DOM shim and the
// real source loaded through `vm`.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const sourcePath = path.join(__dirname, '..', 'web', 'static', 'skill-sharing.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const pure = require(sourcePath);

// ── DOM shim ──────────────────────────────────────────────────────────────

function makeDom() {
  const state = { activeElement: null, keydown: null };

  class FakeText {
    constructor(data) {
      this.tag = '#text';
      this.data = String(data);
      this.children = [];
      this.parent = null;
    }
    get textContent() {
      return this.data;
    }
    set textContent(v) {
      this.data = String(v == null ? '' : v);
    }
  }

  class FakeEl {
    constructor(tag) {
      this.tag = tag;
      this.className = '';
      this.children = [];
      this.parent = null;
      this._attrs = {};
      this._listeners = {};
      this.disabled = false;
      this.hidden = false;
      this.value = '';
      this.id = '';
      this.removed = false;
    }
    appendChild(child) {
      child.parent = this;
      this.children.push(child);
      return child;
    }
    get firstChild() {
      return this.children[0] || null;
    }
    setAttribute(k, v) {
      this._attrs[k] = String(v);
      if (k === 'class') this.className = String(v);
    }
    getAttribute(k) {
      return k in this._attrs ? this._attrs[k] : null;
    }
    addEventListener(type, fn) {
      (this._listeners[type] = this._listeners[type] || []).push(fn);
    }
    removeEventListener(type, fn) {
      this._listeners[type] = (this._listeners[type] || []).filter((f) => f !== fn);
    }
    focus() {
      state.activeElement = this;
    }
    remove() {
      this.removed = true;
      if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this);
    }
    set textContent(v) {
      const s = String(v == null ? '' : v);
      this.children = [];
      if (s) this.appendChild(new FakeText(s));
    }
    get textContent() {
      return this.children.map((c) => c.textContent).join('');
    }
    querySelector(tag) {
      return find(this, (el) => el !== this && el.tag === tag);
    }
    click() {
      return fire(this, 'click');
    }
  }

  // Runs every listener of `type` on `el`, like the browser does, and hands
  // back the event so a test can look at preventDefault.
  function fire(el, type, props) {
    const e = Object.assign(
      {
        type,
        target: el,
        prevented: false,
        preventDefault() {
          this.prevented = true;
        },
        stopPropagation() {},
      },
      props,
    );
    (el._listeners[type] || []).slice().forEach((fn) => fn(e));
    return e;
  }

  const body = new FakeEl('body');
  const document = {
    body,
    createElement: (tag) => new FakeEl(tag),
    createElementNS: (ns, tag) => new FakeEl(tag),
    createTextNode: (text) => new FakeText(text),
    get activeElement() {
      return state.activeElement;
    },
    addEventListener(type, fn, capture) {
      if (type === 'keydown' && capture) state.keydown = fn;
    },
    removeEventListener(type, fn, capture) {
      if (type === 'keydown' && capture && state.keydown === fn) state.keydown = null;
    },
  };

  function key(k, shiftKey) {
    const e = {
      key: k,
      shiftKey: !!shiftKey,
      prevented: false,
      preventDefault() {
        this.prevented = true;
      },
      stopPropagation() {},
    };
    if (state.keydown) state.keydown(e);
    return e;
  }

  function walk(el, fn) {
    if (!el) return;
    fn(el);
    el.children.forEach((c) => walk(c, fn));
  }
  function find(root, pred) {
    let hit = null;
    walk(root, (el) => {
      if (!hit && el.tag !== '#text' && pred(el)) hit = el;
    });
    return hit;
  }
  function findAll(root, pred) {
    const hits = [];
    walk(root, (el) => {
      if (el.tag !== '#text' && pred(el)) hits.push(el);
    });
    return hits;
  }
  const hasClass = (el, cls) => el.className.split(' ').includes(cls);
  const byText = (root, text) => find(root, (el) => el.textContent === text);
  const byTag = (root, tag) => find(root, (el) => el.tag === tag);
  const byClass = (root, cls) => find(root, (el) => hasClass(el, cls));
  const allByClass = (root, cls) => findAll(root, (el) => hasClass(el, cls));

  return {
    document,
    state,
    key,
    fire,
    find,
    findAll,
    byText,
    byTag,
    byClass,
    allByClass,
    hasClass,
  };
}

function load(dom, extra) {
  const window = {};
  const ctx = vm.createContext(
    Object.assign({ window, document: dom.document, console, setTimeout, Promise }, extra || {}),
  );
  vm.runInContext(source, ctx);
  return window.SkillSharing;
}

const flush = () => new Promise((r) => setImmediate(r));

// A clock the test moves by hand, so the people-search debounce is exact.
function makeClock() {
  let now = 0;
  let nextId = 0;
  const timers = new Map();
  return {
    setTimeout(fn, ms) {
      nextId += 1;
      timers.set(nextId, { fn, at: now + (ms || 0) });
      return nextId;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    tick(ms) {
      const end = now + ms;
      for (;;) {
        let next = null;
        timers.forEach((t, id) => {
          if (t.at <= end && (!next || t.at < next.t.at)) next = { id, t };
        });
        if (!next) break;
        timers.delete(next.id);
        now = next.t.at;
        next.t.fn();
      }
      now = end;
    },
  };
}

function defer() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// ── parseEmails ───────────────────────────────────────────────────────────

test('module loads in the browser context and exposes window.SkillSharing', () => {
  const api = load(makeDom());
  assert.strictEqual(typeof api.openShareModal, 'function');
  assert.strictEqual(typeof api.parseEmails, 'function');
  assert.strictEqual(typeof api.shareErrorText, 'function');
});

test('parseEmails splits on commas, semicolons and whitespace', () => {
  const out = pure.parseEmails('a@x.com, b@x.com;c@x.com\n d@x.com\te@x.com');
  assert.deepStrictEqual(out.emails, ['a@x.com', 'b@x.com', 'c@x.com', 'd@x.com', 'e@x.com']);
  assert.deepStrictEqual(out.bad, []);
});

test('parseEmails lower-cases and drops duplicates and empties', () => {
  const out = pure.parseEmails(' A@X.com ,, a@x.com ;; B@x.com ');
  assert.deepStrictEqual(out.emails, ['a@x.com', 'b@x.com']);
});

test('parseEmails reports entries that are not addresses', () => {
  const out = pure.parseEmails('good@x.com, nobody, also@bad, <z@x.com>');
  assert.deepStrictEqual(out.emails, ['good@x.com']);
  assert.deepStrictEqual(out.bad, ['nobody', 'also@bad', '<z@x.com>']);
});

test('parseEmails of nothing gives empty lists', () => {
  assert.deepStrictEqual(pure.parseEmails('  ,; '), { emails: [], bad: [] });
  assert.deepStrictEqual(pure.parseEmails(undefined), { emails: [], bad: [] });
});

// ── shareErrorText ────────────────────────────────────────────────────────

test('shareErrorText covers the four response shapes', () => {
  assert.strictEqual(
    pure.shareErrorText({ ok: false }, { detail: { message: 'OneDrive is not connected.' } }),
    'OneDrive is not connected.',
  );
  assert.strictEqual(
    pure.shareErrorText({ ok: false }, { detail: 'Skill not found' }),
    'Skill not found',
  );
  assert.strictEqual(
    pure.shareErrorText({ ok: false }, { detail: [{ loc: ['body', 'people'], msg: 'bad' }] }),
    'Check the email addresses and try again.',
  );
  assert.strictEqual(
    pure.shareErrorText({ ok: false }, null),
    'Could not share this skill. Try again.',
  );
  assert.strictEqual(
    pure.shareErrorText({ ok: false }, { detail: { code: 'x' } }),
    'Could not share this skill. Try again.',
  );
});

// ── Share modal harness ───────────────────────────────────────────────────

const SKILL = 'weekly-report';
const clone = (x) => JSON.parse(JSON.stringify(x));
const json = (body, status) => ({
  resp: { ok: !status || status < 400, status: status || 200 },
  body,
});
const fail = (status, error, message) => json({ detail: { error, message } }, status);

const LOC_DEFAULT = {
  drive_id: 'b!me',
  folder_id: '',
  name: 'AI Gator Skills',
  path: ['OneDrive', 'AI Gator Skills'],
  web_url: '',
};
const LOC_RECENT = {
  drive_id: 'b!team',
  folder_id: 'f1',
  name: 'Team Skills',
  path: ['Contoso Team', 'Documents', 'Team Skills'],
  web_url: 'https://contoso.sharepoint.com/sites/team',
};
const LOCATIONS = { default: LOC_DEFAULT, recent: [LOC_RECENT], current: null };
const PRIVATE = { kind: 'private' };
const LIBRARY = { kind: 'library', name: 'Contoso Team', approx_count: 1200 };

function checkBody(audience, over) {
  return Object.assign(
    { ok: true, reason: '', can_write: true, location: null, audience, existing: null },
    over,
  );
}

const PUBLISHED = {
  message:
    'I shared a skill with you. Open it here: https://contoso-my.sharepoint.com/s/weekly-report',
  message_html: '<p>I shared a skill with you.</p>',
  web_url:
    'https://contoso-my.sharepoint.com/personal/me/Documents/AI%20Gator%20Skills/weekly-report',
  saved_path: ['OneDrive', 'AI Gator Skills', 'weekly-report'],
  ungranted: [],
};
const DRAFT = {
  drafts: [{ id: 'd1', to: ['ann.lee@contoso.com'], subject: 'weekly-report' }],
  unmatched: [],
};
const PEOPLE = [
  { name: 'Ann Lee', email: 'Ann.Lee@contoso.com' },
  { name: 'Anna Wu', email: 'anna.wu@contoso.com' },
  { name: '', email: 'ann.x@contoso.com' },
];

function defaultGet(url) {
  if (url.startsWith('/api/skills/share/locations')) return json(clone(LOCATIONS));
  if (url.startsWith('/api/skills/share/check')) return json(checkBody(PRIVATE));
  return fail(404, 'not_found', 'No route ' + url);
}

// opts.get / opts.post answer first; returning undefined falls through to the
// defaults above. Payloads are copied to plain objects because values made
// inside the vm context do not deepStrictEqual outer literals.
function makeEnv(opts) {
  const calls = { get: [], post: [], order: [], alerts: [], drafts: [], downloads: [], refresh: 0 };
  const deps = {
    getJson: async (url) => {
      calls.get.push(url);
      const own = opts.get ? await opts.get(url) : undefined;
      return own != null ? own : defaultGet(url);
    },
    postJson: async (url, payload) => {
      calls.post.push({ url, payload: clone(payload) });
      calls.order.push(url.split('/').pop());
      const own = opts.post ? await opts.post(url, clone(payload)) : undefined;
      if (own != null) return own;
      if (url === '/api/skills/share/publish') return json(clone(PUBLISHED));
      if (url === '/api/skills/share/draft') return json(clone(DRAFT));
      return fail(404, 'not_found', 'No route ' + url);
    },
    downloadSkill: (id) => {
      calls.downloads.push(id);
    },
    showAlert: (message, kind) => {
      calls.alerts.push([message, kind]);
    },
    showDrafts: (drafts) => {
      calls.order.push('drafts');
      calls.drafts.push(clone(drafts));
    },
    refresh: () => {
      calls.refresh += 1;
    },
  };
  if (opts.search) deps.searchPeople = opts.search;
  if (opts.noDrafts) delete deps.showDrafts;
  return { calls, deps };
}

function boot(opts) {
  opts = opts || {};
  const dom = makeDom();
  const clock = makeClock();
  const env = makeEnv(opts);
  const clip = { written: [] };
  let navigator;
  if (!opts.noClipboard) {
    navigator = {
      clipboard: {
        writeText: async (text) => {
          if (opts.clipboardFails) throw new Error('denied');
          env.calls.order.push('copy');
          clip.written.push(text);
        },
      },
    };
  }
  const api = load(dom, {
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    AbortController,
    navigator,
  });
  const t = { dom, clock, env, calls: env.calls, clip, api };

  t.start = () => {
    t.shell = api.openShareModal(opts.skill || SKILL, env.deps);
    return t;
  };
  t.root = () => dom.document.body.children[0] || null;
  t.text = () => (t.root() ? t.root().textContent : '');
  t.cls = (name) => dom.allByClass(t.root(), name);
  t.one = (name) => dom.byClass(t.root(), name);
  t.heading = () => t.one('mp-modal-title').textContent;
  t.btn = (label) => dom.find(t.root(), (el) => el.tag === 'button' && el.textContent === label);
  t.press = async (label) => {
    const b = t.btn(label);
    assert(b, 'no button "' + label + '" in: ' + t.text());
    b.click();
    await flush();
  };
  t.radios = () => dom.findAll(t.root(), (el) => el.tag === 'input' && el.type === 'radio');
  t.checkbox = () => dom.find(t.root(), (el) => el.tag === 'input' && el.type === 'checkbox');
  t.nextDisabled = () => t.btn('Next').disabled;
  t.status = () => t.one('ss-status-host').textContent;
  return t;
}

async function open(opts) {
  const t = boot(opts).start();
  await flush();
  return t;
}

function rowLabels(t) {
  return t.cls('ss-loc-name').map((n) => {
    const tag = t.dom.byClass(n, 'ss-tag');
    return [n.firstChild.textContent, tag ? tag.textContent : ''];
  });
}
const selectedRow = (t) => t.cls('ss-loc').findIndex((r) => t.dom.hasClass(r, 'is-selected'));

async function pickRadio(t, i) {
  const r = t.radios()[i];
  r.checked = true;
  t.dom.fire(r, 'change');
  await flush();
}

// ── Step 1: where to save ─────────────────────────────────────────────────

test('opens on Save with a loading line and asks for the locations of this skill', async () => {
  const t = boot().start();
  assert.strictEqual(t.heading(), 'Share "weekly-report"');
  assert(t.text().includes('Loading your folders...'));
  assert.deepStrictEqual(
    t.cls('ss-step').map((b) => b.textContent),
    ['1Save', '2Share', '3Send'],
  );
  assert.strictEqual(t.dom.byClass(t.root(), 'is-current').getAttribute('aria-current'), 'step');
  await flush();
  assert.strictEqual(t.calls.get[0], '/api/skills/share/locations?skill_id=weekly-report');
  assert(!t.text().includes('Loading your folders...'));
});

test('lists the default folder first and selected, then recent ones, as radios', async () => {
  const t = await open();
  assert.strictEqual(t.cls('ss-label')[0].textContent, 'Save to');
  assert.deepStrictEqual(rowLabels(t), [
    ['OneDrive › AI Gator Skills', 'Default'],
    ['Contoso Team › Documents › Team Skills', 'Recent'],
  ]);
  assert.strictEqual(t.radios().length, 2);
  assert.strictEqual(selectedRow(t), 0);
  assert.strictEqual(t.radios()[0].checked, true);
  assert(t.btn('Choose another folder...'));
});

test('checks the default folder on open without a drive or folder id', async () => {
  const t = await open();
  assert.deepStrictEqual(t.calls.get.slice(1), ['/api/skills/share/check?skill_id=weekly-report']);
});

test('a private folder says so and enables Next without any acknowledgement', async () => {
  const t = await open();
  assert(t.status().includes('Only you can see this folder'));
  assert.strictEqual(t.checkbox(), null);
  assert.strictEqual(t.nextDisabled(), false);
});

test('choosing a recent folder checks it with its drive and folder ids', async () => {
  const t = await open();
  await pickRadio(t, 1);
  assert.strictEqual(selectedRow(t), 1);
  assert.strictEqual(
    t.calls.get[2],
    '/api/skills/share/check?skill_id=weekly-report&drive_id=b!team&folder_id=f1',
  );
});

test('while a folder is being checked Next is off and a checking line shows', async () => {
  const gates = [];
  const t = await open({
    get: (url) => {
      if (url.includes('/share/check')) {
        const d = defer();
        gates.push(d);
        return d.promise;
      }
    },
  });
  assert(t.status().includes('Checking who can see this folder...'));
  assert.strictEqual(t.nextDisabled(), true);
  gates[0].resolve(json(checkBody(PRIVATE)));
  await flush();
  assert.strictEqual(t.nextDisabled(), false);
  assert(!t.status().includes('Checking'));
});

test('a library folder needs the acknowledgement before Next', async () => {
  const t = await open({
    get: (url) => (url.includes('/share/check') ? json(checkBody(LIBRARY)) : undefined),
  });
  assert(t.status().includes('Everyone in Contoso Team (about 1,200 people) can see it'));
  assert(t.status().includes('Anyone in this library can open this skill without being added.'));
  assert(t.status().includes('I understand everyone with access to Contoso Team can see it'));
  assert.strictEqual(t.nextDisabled(), true);
  const box = t.checkbox();
  box.checked = true;
  t.dom.fire(box, 'change');
  assert.strictEqual(t.nextDisabled(), false);
  box.checked = false;
  t.dom.fire(box, 'change');
  assert.strictEqual(t.nextDisabled(), true);
});

test('a library without a head count still names the library', async () => {
  const audience = { kind: 'library', name: 'Contoso Team' };
  const t = await open({
    get: (url) => (url.includes('/share/check') ? json(checkBody(audience)) : undefined),
  });
  assert(t.status().includes('Everyone with access to Contoso Team can see it'));
});

test('an organization-wide folder needs the acknowledgement and is flagged as broad', async () => {
  const t = await open({
    get: (url) => (url.includes('/share/check') ? json(checkBody({ kind: 'org' })) : undefined),
  });
  assert(t.status().includes('Everyone in your organization can see it'));
  assert(t.status().includes('I understand everyone in my organization can see it'));
  assert(t.dom.byClass(t.root(), 'ss-audience').className.includes('is-broad'));
  assert.strictEqual(t.nextDisabled(), true);
  const box = t.checkbox();
  box.checked = true;
  t.dom.fire(box, 'change');
  assert.strictEqual(t.nextDisabled(), false);
});

test('an already shared folder needs the acknowledgement, with or without a count', async () => {
  let audience = { kind: 'folder', approx_count: 12 };
  const t = await open({
    get: (url) => (url.includes('/share/check') ? json(checkBody(audience)) : undefined),
  });
  assert(t.status().includes('Already shared with 12 people'));
  assert(t.status().includes('I understand they can see it'));
  assert.strictEqual(t.nextDisabled(), true);
  audience = { kind: 'folder' };
  const u = await open({
    get: (url) => (url.includes('/share/check') ? json(checkBody(audience)) : undefined),
  });
  assert(u.status().includes('Already shared with other people'));
});

test('changing the folder clears the acknowledgement', async () => {
  const t = await open({
    get: (url) => {
      if (!url.includes('/share/check')) return undefined;
      return json(checkBody(url.includes('drive_id') ? PRIVATE : LIBRARY));
    },
  });
  const box = t.checkbox();
  box.checked = true;
  t.dom.fire(box, 'change');
  assert.strictEqual(t.nextDisabled(), false);
  await pickRadio(t, 1);
  assert.strictEqual(t.nextDisabled(), false, 'private recent folder needs no acknowledgement');
  await pickRadio(t, 0);
  assert.strictEqual(t.checkbox().checked, false);
  assert.strictEqual(t.nextDisabled(), true);
});

test('Next does nothing while the acknowledgement is missing', async () => {
  const t = await open({
    get: (url) => (url.includes('/share/check') ? json(checkBody(LIBRARY)) : undefined),
  });
  await t.press('Next');
  assert.strictEqual(t.cls('ss-label')[0].textContent, 'Save to');
  assert.strictEqual(t.heading(), 'Share "weekly-report"');
});

test('a skill with this name from someone else blocks the folder', async () => {
  const existing = { title: 'Weekly report', version: 3, author: 'Dana Kim', yours: false };
  const t = await open({
    get: (url) =>
      url.includes('/share/check') ? json(checkBody(PRIVATE, { existing })) : undefined,
  });
  assert(t.status().includes('A skill with this name is already there'));
  assert(t.status().includes('"weekly-report" in this folder was created by Dana Kim'));
  assert.strictEqual(t.nextDisabled(), true);
  assert.strictEqual(t.dom.byClass(t.root(), 'ss-audience').getAttribute('role'), 'alert');
});

test('a taken folder without an author says someone else, and my own copy is fine', async () => {
  let existing = { yours: false };
  const t = await open({
    get: (url) =>
      url.includes('/share/check') ? json(checkBody(PRIVATE, { existing })) : undefined,
  });
  assert(t.status().includes('created by someone else'));
  existing = { title: 'Weekly report', version: 3, author: 'Me', yours: true };
  const u = await open({
    get: (url) =>
      url.includes('/share/check') ? json(checkBody(PRIVATE, { existing })) : undefined,
  });
  assert(u.status().includes('Only you can see this folder'));
  assert.strictEqual(u.nextDisabled(), false);
});

test('a folder that is gone blocks Next', async () => {
  const t = await open({
    get: (url) =>
      url.includes('/share/check')
        ? json(checkBody(PRIVATE, { ok: false, reason: 'not_found' }))
        : undefined,
  });
  assert(t.status().includes('This folder is no longer available'));
  assert(t.status().includes('Choose another folder.'));
  assert.strictEqual(t.nextDisabled(), true);
});

test('a failed check shows the server message and Try again re-runs it', async () => {
  let n = 0;
  const t = await open({
    get: (url) => {
      if (!url.includes('/share/check')) return undefined;
      n += 1;
      return n === 1 ? fail(502, 'graph_down', 'OneDrive is not answering.') : undefined;
    },
  });
  assert(t.status().includes('Could not check this folder'));
  assert(t.status().includes('OneDrive is not answering.'));
  assert.strictEqual(t.nextDisabled(), true);
  await t.press('Try again');
  assert.strictEqual(n, 2);
  assert(t.status().includes('Only you can see this folder'));
  assert.strictEqual(t.nextDisabled(), false);
});

test('a check that never reaches the server uses the generic message', async () => {
  const t = await open({
    get: (url) => {
      if (url.includes('/share/check')) throw new Error('offline');
    },
  });
  assert(t.status().includes('Could not check this folder. Try again.'));
  assert.strictEqual(t.nextDisabled(), true);
});

test('a slow check for a folder I already left is ignored', async () => {
  const gates = [];
  const t = await open({
    get: (url) => {
      if (url.includes('/share/check')) {
        const d = defer();
        gates.push(d);
        return d.promise;
      }
    },
  });
  await pickRadio(t, 1);
  assert.strictEqual(gates.length, 2);
  gates[1].resolve(json(checkBody(PRIVATE)));
  await flush();
  gates[0].resolve(json(checkBody(LIBRARY)));
  await flush();
  assert(t.status().includes('Only you can see this folder'));
  assert(!t.status().includes('Everyone'));
  assert.strictEqual(t.nextDisabled(), false);
});

test('the path the check reports replaces the label of the folder that was checked', async () => {
  const location = { path: ['Contoso Team', 'Documents', 'Team Skills (renamed)'] };
  const t = await open({
    get: (url) => (url.includes('drive_id') ? json(checkBody(PRIVATE, { location })) : undefined),
  });
  await pickRadio(t, 1);
  assert.deepStrictEqual(rowLabels(t), [
    ['OneDrive › AI Gator Skills', 'Default'],
    ['Contoso Team › Documents › Team Skills (renamed)', 'Recent'],
  ]);
});

test('Next moves to Share and the finished Save step becomes a way back', async () => {
  const t = await open();
  await t.press('Next');
  assert.deepStrictEqual(
    t.cls('ss-step').map((b) => b.textContent),
    ['Save', '2Share', '3Send'],
  );
  assert.strictEqual(t.cls('ss-step')[0].getAttribute('data-done'), 'true');
  assert.strictEqual(t.cls('ss-step')[2].getAttribute('data-done'), 'false');
  assert(t.btn('Back'));
  await t.dom.byClass(t.root(), 'is-done').click();
  await flush();
  assert.strictEqual(t.cls('ss-label')[0].textContent, 'Save to');
});

// ── Folders could not be loaded ───────────────────────────────────────────

test('when the folders fail to load the server text shows with Try again and a download', async () => {
  const t = await open({
    get: (url) =>
      url.startsWith('/api/skills/share/locations')
        ? fail(503, 'unavailable', 'OneDrive is not connected.')
        : undefined,
  });
  const alert = t.dom.find(t.root(), (el) => el.tag === 'p' && el.getAttribute('role') === 'alert');
  assert.strictEqual(alert.textContent, 'OneDrive is not connected.');
  assert(t.btn('Try again'));
  assert(t.btn('Download file instead'));
  assert.strictEqual(t.radios().length, 0);
});

test('a locations answer without a default folder is a load failure', async () => {
  const t = await open({
    get: (url) => (url.startsWith('/api/skills/share/locations') ? json({}) : undefined),
  });
  assert(t.text().includes('Could not load your folders. Try again.'));
});

test('a locations request that throws uses the generic load message', async () => {
  const t = await open({
    get: (url) => {
      if (url.startsWith('/api/skills/share/locations')) throw new Error('offline');
    },
  });
  assert(t.text().includes('Could not load your folders. Try again.'));
});

test('Try again reloads the folders and then shows them', async () => {
  let n = 0;
  const t = await open({
    get: (url) => {
      if (!url.startsWith('/api/skills/share/locations')) return undefined;
      n += 1;
      return n === 1 ? fail(500, 'boom', 'Could not load your folders. Try again.') : undefined;
    },
  });
  await t.press('Try again');
  assert.strictEqual(n, 2);
  assert.strictEqual(t.radios().length, 2);
  assert(!t.text().includes('Download file instead'));
});

test('Download file instead closes the modal and downloads the skill', async () => {
  const t = await open({
    get: (url) =>
      url.startsWith('/api/skills/share/locations') ? fail(500, 'boom', 'Nope') : undefined,
  });
  await t.press('Download file instead');
  assert.strictEqual(t.root(), null);
  assert.deepStrictEqual(t.calls.downloads, ['weekly-report']);
});

// ── A skill that already has a folder ─────────────────────────────────────

const CURRENT = {
  drive_id: 'b!team',
  folder_id: 'f7',
  name: 'weekly-report',
  path: ['Contoso Team', 'Documents', 'Team Skills'],
  web_url: '',
};
const lockedLocations = (url) =>
  url.startsWith('/api/skills/share/locations')
    ? json({ default: LOC_DEFAULT, recent: [LOC_RECENT], current: CURRENT })
    : undefined;

test('a skill saved before is locked to its folder: no radios, no check, Next on', async () => {
  const t = await open({ get: lockedLocations });
  assert.strictEqual(t.cls('ss-label')[0].textContent, 'Saved in');
  assert.strictEqual(t.radios().length, 0);
  assert.deepStrictEqual(
    t.cls('ss-loc-name').map((n) => n.textContent),
    ['Contoso Team › Documents › Team Skills'],
  );
  assert(t.text().includes('This skill is already saved here. Updates go to the same folder.'));
  assert.strictEqual(t.btn('Choose another folder...'), null);
  assert.deepStrictEqual(t.calls.get, ['/api/skills/share/locations?skill_id=weekly-report']);
  assert.strictEqual(t.nextDisabled(), false);
});

test('a locked skill can move on with nobody added, and Share still opens', async () => {
  const t = await open({ get: lockedLocations });
  await t.press('Next');
  assert.strictEqual(t.btn('Next').disabled, false);
  await t.press('Next');
  assert(t.text().includes('Email to'));
});

// ── Folder chooser ────────────────────────────────────────────────────────

const SITES = {
  sites: [
    { id: 'site,1', name: 'Contoso Team' },
    { id: 'site2', name: 'Design' },
  ],
};
const folder = (id, name, extra) =>
  Object.assign({ id, name, is_folder: true, has_children: false, web_url: '' }, extra);

// Answers the OneDrive listing routes the chooser calls. `extra` replaces or
// adds routes; a route may be a function of the url.
function chooserRoutes(extra) {
  const table = Object.assign(
    {
      '/api/onedrive/sites': json(SITES),
      '/api/onedrive/folders?parent=root': json({
        items: [
          folder('d1', 'Projects', { drive_id: 'b!me', has_children: true }),
          folder('d2', 'Notes', { drive_id: 'b!me' }),
          { id: 'x', name: 'a.txt', is_folder: false },
        ],
      }),
      '/api/onedrive/folders?parent=d1': json({ items: [] }),
      '/api/onedrive/sites/site%2C1/drives': json({
        drives: [{ id: 'b!team', name: 'Documents' }],
      }),
      '/api/onedrive/drives/b!team/folders?parent=root': json({
        items: [
          folder('f1', 'Team Skills', {
            has_children: true,
            web_url: 'https://contoso.sharepoint.com/sites/team',
          }),
          folder('f9', 'Archive'),
        ],
      }),
      '/api/onedrive/drives/b!team/folders?parent=f1': json({ items: [] }),
    },
    extra,
  );
  return (url) => {
    const r = table[url];
    return typeof r === 'function' ? r(url) : r;
  };
}

async function inChooser(routes, opts) {
  const t = await open(Object.assign({ get: chooserRoutes(routes) }, opts));
  await t.press('Choose another folder...');
  return t;
}
async function goTo(t, names) {
  for (const n of names) await t.press(n);
}
const foldRows = (t) => t.cls('ss-fold').map((b) => b.textContent);
const crumbs = (t) => t.cls('ss-crumb').map((b) => b.textContent);
const nameInput = (t) =>
  t.dom.find(
    t.root(),
    (el) => el.tag === 'input' && el.getAttribute('aria-label') === 'New folder name',
  );
function typeName(t, text) {
  const i = nameInput(t);
  i.value = text;
  t.dom.fire(i, 'input');
}
const newFolderError = (t) => t.dom.byClass(t.root(), 'ss-newrow-error').textContent;

test('the chooser starts at My OneDrive and the SharePoint sites', async () => {
  const t = await inChooser();
  assert.strictEqual(t.heading(), 'Choose a folder');
  assert.deepStrictEqual(foldRows(t), ['My OneDrive', 'Contoso Team', 'Design']);
  assert.deepStrictEqual(
    t.cls('ss-group').map((g) => g.textContent),
    ['Your OneDrive', 'SharePoint sites'],
  );
  assert.deepStrictEqual(crumbs(t), ['Folders']);
  assert.deepStrictEqual(
    t.cls('ss-step').map((b) => b.textContent),
    ['1Save', '2Share', '3Send'],
  );
  assert.strictEqual(t.btn('Select this folder').disabled, true);
  assert.strictEqual(t.btn('New folder'), null);
  assert(t.calls.get.includes('/api/onedrive/sites'));
});

test('Back leaves the chooser with the folder choice unchanged', async () => {
  const t = await inChooser();
  await t.press('Back');
  assert.strictEqual(t.heading(), 'Share "weekly-report"');
  assert.strictEqual(t.radios().length, 2);
  assert.strictEqual(selectedRow(t), 0);
});

test('a failed sites call keeps My OneDrive and shows a note', async () => {
  const t = await inChooser({ '/api/onedrive/sites': fail(403, 'forbidden', 'No sites for you') });
  assert.deepStrictEqual(foldRows(t), ['My OneDrive']);
  assert.deepStrictEqual(
    t.cls('ss-empty').map((n) => n.textContent),
    ['Could not load SharePoint sites.'],
  );
});

test('My OneDrive lists only folders and each level adds a crumb', async () => {
  const t = await inChooser();
  await t.press('My OneDrive');
  assert.deepStrictEqual(foldRows(t), ['Projects', 'Notes']);
  assert.deepStrictEqual(crumbs(t), ['Folders', 'My OneDrive']);
  assert.strictEqual(t.btn('Select this folder').disabled, true);
  await t.press('Projects');
  assert(t.calls.get.includes('/api/onedrive/folders?parent=d1'));
  assert.deepStrictEqual(crumbs(t), ['Folders', 'My OneDrive', 'Projects']);
  assert.deepStrictEqual(
    t.cls('ss-empty').map((n) => n.textContent),
    ['No folders here'],
  );
  assert.strictEqual(t.btn('Select this folder').disabled, false);
});

test('a crumb goes back up and drops the levels below it', async () => {
  const t = await inChooser();
  await goTo(t, ['My OneDrive', 'Projects', 'My OneDrive']);
  assert.deepStrictEqual(crumbs(t), ['Folders', 'My OneDrive']);
  assert.deepStrictEqual(foldRows(t), ['Projects', 'Notes']);
  await t.press('Folders');
  assert.deepStrictEqual(crumbs(t), ['Folders']);
  assert.deepStrictEqual(foldRows(t), ['My OneDrive', 'Contoso Team', 'Design']);
});

test('a site opens its libraries and a library opens its folders; Select waits for a folder', async () => {
  const t = await inChooser();
  await t.press('Contoso Team');
  assert(t.calls.get.includes('/api/onedrive/sites/site%2C1/drives'));
  assert.deepStrictEqual(foldRows(t), ['Documents']);
  assert.strictEqual(t.btn('Select this folder').disabled, true);
  await t.press('Documents');
  assert(t.calls.get.includes('/api/onedrive/drives/b!team/folders?parent=root'));
  assert.deepStrictEqual(foldRows(t), ['Team Skills', 'Archive']);
  assert.strictEqual(t.btn('Select this folder').disabled, true);
  await t.press('Archive');
  assert(t.calls.get.includes('/api/onedrive/drives/b!team/folders?parent=f9'));
  assert.strictEqual(t.btn('Select this folder').disabled, false);
});

test('Select adds the folder as Chosen after the default, selects it and checks it', async () => {
  const t = await inChooser();
  await goTo(t, ['Contoso Team', 'Documents', 'Archive', 'Select this folder']);
  assert.strictEqual(t.heading(), 'Share "weekly-report"');
  assert.deepStrictEqual(rowLabels(t), [
    ['OneDrive › AI Gator Skills', 'Default'],
    ['Contoso Team › Documents › Archive', 'Chosen'],
    ['Contoso Team › Documents › Team Skills', 'Recent'],
  ]);
  assert.strictEqual(selectedRow(t), 1);
  assert.strictEqual(
    t.calls.get[t.calls.get.length - 1],
    '/api/skills/share/check?skill_id=weekly-report&drive_id=b!team&folder_id=f9',
  );
  assert(t.status().includes('Only you can see this folder'));
  assert.strictEqual(t.nextDisabled(), false);
});

test('choosing a folder that is already listed selects that row instead of adding one', async () => {
  const t = await inChooser();
  await goTo(t, ['Contoso Team', 'Documents', 'Team Skills', 'Select this folder']);
  assert.strictEqual(t.radios().length, 2);
  assert.strictEqual(selectedRow(t), 1);
  assert.strictEqual(rowLabels(t)[1][1], 'Recent');
});

test('a second chosen folder replaces the first one', async () => {
  const t = await inChooser();
  await goTo(t, ['Contoso Team', 'Documents', 'Archive', 'Select this folder']);
  await t.press('Choose another folder...');
  await goTo(t, ['My OneDrive', 'Projects', 'Select this folder']);
  assert.deepStrictEqual(rowLabels(t), [
    ['OneDrive › AI Gator Skills', 'Default'],
    ['My OneDrive › Projects', 'Chosen'],
    ['Contoso Team › Documents › Team Skills', 'Recent'],
  ]);
  assert.strictEqual(selectedRow(t), 1);
  assert.strictEqual(
    t.calls.get[t.calls.get.length - 1],
    '/api/skills/share/check?skill_id=weekly-report&drive_id=b!me&folder_id=d1',
  );
});

test('a chosen folder that needs the acknowledgement keeps Next off until it is ticked', async () => {
  const t = await inChooser(
    {},
    {
      get: (url) =>
        url.includes('folder_id=f9') ? json(checkBody({ kind: 'org' })) : chooserRoutes()(url),
    },
  );
  await goTo(t, ['Contoso Team', 'Documents', 'Archive', 'Select this folder']);
  assert.strictEqual(t.nextDisabled(), true);
  assert(t.status().includes('Everyone in your organization can see it'));
});

// ── New folder ────────────────────────────────────────────────────────────

function createRoutes() {
  const state = { created: false };
  return {
    state,
    get: {
      '/api/onedrive/drives/b!team/folders?parent=f1': () =>
        json({ items: state.created ? [folder('f2', 'Shared')] : [] }),
      '/api/onedrive/drives/b!team/folders?parent=f2': json({ items: [] }),
    },
    post: (url) => {
      if (url === '/api/onedrive/drives/b!team/folders/f1') {
        state.created = true;
        return json({ id: 'f2', name: 'Shared' }, 201);
      }
    },
  };
}

test('New folder posts the name with conflict fail and steps into the new folder', async () => {
  const c = createRoutes();
  const t = await inChooser(c.get, { post: c.post });
  await goTo(t, ['Contoso Team', 'Documents', 'Team Skills', 'New folder']);
  assert(nameInput(t));
  assert.strictEqual(t.btn('Create').disabled, true);
  typeName(t, '  Shared ');
  assert.strictEqual(t.btn('Create').disabled, false);
  await t.press('Create');
  assert.deepStrictEqual(t.calls.post, [
    {
      url: '/api/onedrive/drives/b!team/folders/f1',
      payload: { name: 'Shared', conflict: 'fail' },
    },
  ]);
  assert.deepStrictEqual(crumbs(t), [
    'Folders',
    'Contoso Team',
    'Documents',
    'Team Skills',
    'Shared',
  ]);
  assert.strictEqual(nameInput(t), null);
  assert.strictEqual(t.btn('Select this folder').disabled, false);
});

test('Enter in the name box creates the folder', async () => {
  const c = createRoutes();
  const t = await inChooser(c.get, { post: c.post });
  await goTo(t, ['Contoso Team', 'Documents', 'Team Skills', 'New folder']);
  typeName(t, 'Shared');
  const e = t.dom.fire(nameInput(t), 'keydown', { key: 'Enter' });
  await flush();
  assert.strictEqual(e.prevented, true);
  assert.strictEqual(t.calls.post.length, 1);
});

test('the create route follows where the new folder goes', async () => {
  const cases = [
    [['My OneDrive'], '/api/onedrive/folders/root'],
    [['My OneDrive', 'Projects'], '/api/onedrive/folders/d1'],
    [['Contoso Team', 'Documents'], '/api/onedrive/drives/b!team/folders/root'],
    [['Contoso Team', 'Documents', 'Archive'], '/api/onedrive/drives/b!team/folders/f9'],
  ];
  for (const [path, url] of cases) {
    const t = await inChooser();
    await goTo(t, path.concat('New folder'));
    typeName(t, 'Fresh');
    await t.press('Create');
    assert.strictEqual(t.calls.post[0].url, url, path.join(' > '));
  }
});

test('a SharePoint site is not a place to create a folder', async () => {
  const t = await inChooser();
  await t.press('Contoso Team');
  assert.strictEqual(t.btn('New folder'), null);
});

test('Create stays off for an empty name and Cancel posts nothing', async () => {
  const t = await inChooser();
  await goTo(t, ['My OneDrive', 'New folder']);
  assert.strictEqual(t.btn('Create').disabled, true);
  typeName(t, '   ');
  assert.strictEqual(t.btn('Create').disabled, true);
  await t.press('Cancel');
  assert.strictEqual(nameInput(t), null);
  assert.strictEqual(t.calls.post.length, 0);
});

test('a name that matches a folder already listed is refused before any request', async () => {
  const t = await inChooser();
  await goTo(t, ['Contoso Team', 'Documents', 'New folder']);
  typeName(t, 'archive');
  assert.strictEqual(newFolderError(t), 'A folder with that name already exists');
  assert.strictEqual(nameInput(t).getAttribute('aria-invalid'), 'true');
  assert.strictEqual(t.btn('Create').disabled, true);
  const e = t.dom.fire(nameInput(t), 'keydown', { key: 'Enter' });
  await flush();
  assert.strictEqual(e.prevented, true);
  assert.strictEqual(t.calls.post.length, 0);
  typeName(t, 'Archive 2');
  assert.strictEqual(newFolderError(t), '');
  assert.strictEqual(t.btn('Create').disabled, false);
});

test('a folder_exists answer shows the same sentence and keeps the box open', async () => {
  const t = await inChooser({}, { post: () => fail(409, 'folder_exists', 'nameAlreadyExists') });
  await goTo(t, ['My OneDrive', 'New folder']);
  typeName(t, 'Race');
  await t.press('Create');
  assert.strictEqual(t.calls.post.length, 1);
  assert.strictEqual(newFolderError(t), 'A folder with that name already exists');
  assert(nameInput(t));
  assert.strictEqual(nameInput(t).value, 'Race');
  typeName(t, 'Race 2');
  assert.strictEqual(newFolderError(t), '');
});

test('other create failures show the server text, or a generic one when nothing came back', async () => {
  const t = await inChooser({}, { post: () => fail(500, 'graph_error', 'OneDrive is busy.') });
  await goTo(t, ['My OneDrive', 'New folder']);
  typeName(t, 'Fresh');
  await t.press('Create');
  assert.strictEqual(newFolderError(t), 'OneDrive is busy.');
  const u = await inChooser(
    {},
    {
      post: () => {
        throw new Error('offline');
      },
    },
  );
  await goTo(u, ['My OneDrive', 'New folder']);
  typeName(u, 'Fresh');
  await u.press('Create');
  assert.strictEqual(newFolderError(u), 'Could not create the folder. Try again.');
});

// ── Listing problems and the Escape key ───────────────────────────────────

test('a failed folder list shows the error with Try again', async () => {
  let n = 0;
  const t = await inChooser({
    '/api/onedrive/drives/b!team/folders?parent=root': () => {
      n += 1;
      return n === 1
        ? fail(500, 'graph_error', 'Could not load your folders. Try again.')
        : json({ items: [folder('f9', 'Archive')] });
    },
  });
  await goTo(t, ['Contoso Team', 'Documents']);
  const bad = t.dom.find(t.root(), (el) => el.getAttribute && el.getAttribute('role') === 'alert');
  assert(bad.textContent.includes('Could not load your folders. Try again.'));
  assert.strictEqual(t.btn('Select this folder').disabled, true);
  await t.press('Try again');
  assert.strictEqual(n, 2);
  assert.deepStrictEqual(foldRows(t), ['Archive']);
});

test('while a list is loading nothing can be selected or created', async () => {
  const gate = defer();
  const t = await inChooser({ '/api/onedrive/folders?parent=d1': () => gate.promise });
  await goTo(t, ['My OneDrive', 'Projects']);
  assert(t.text().includes('Loading...'));
  assert.strictEqual(t.btn('Select this folder').disabled, true);
  assert.strictEqual(t.btn('New folder'), null);
  gate.resolve(json({ items: [folder('d3', 'Deep')] }));
  await flush();
  assert.deepStrictEqual(foldRows(t), ['Deep']);
  assert.strictEqual(t.btn('Select this folder').disabled, false);
});

test('a list that arrives after I moved up is ignored', async () => {
  const gate = defer();
  const t = await inChooser({ '/api/onedrive/folders?parent=root': () => gate.promise });
  await t.press('My OneDrive');
  await t.press('Folders');
  assert.deepStrictEqual(crumbs(t), ['Folders']);
  gate.resolve(json({ items: [folder('d1', 'Late')] }));
  await flush();
  assert.deepStrictEqual(foldRows(t), ['My OneDrive', 'Contoso Team', 'Design']);
  assert.deepStrictEqual(crumbs(t), ['Folders']);
});

test('Escape leaves the New folder box, then the chooser, then the modal', async () => {
  const t = await inChooser();
  await goTo(t, ['My OneDrive', 'New folder']);
  assert(nameInput(t));
  let e = t.dom.key('Escape');
  assert.strictEqual(e.prevented, true);
  assert.strictEqual(nameInput(t), null);
  assert.strictEqual(t.heading(), 'Choose a folder');
  t.dom.key('Escape');
  assert.strictEqual(t.heading(), 'Share "weekly-report"');
  assert(t.root());
  t.dom.key('Escape');
  assert.strictEqual(t.root(), null);
});

// ── Step 2: the people field ──────────────────────────────────────────────

function makeSearch(handler) {
  const calls = [];
  const fn = (q, signal) => {
    calls.push({ q, signal });
    return handler ? handler(q, signal, calls.length) : Promise.resolve(clone(PEOPLE));
  };
  fn.calls = calls;
  return fn;
}

// Every call waits until the test resolves it, in call order.
function gatedSearch() {
  const pending = [];
  const fn = makeSearch(() => {
    const d = defer();
    pending.push(d);
    return d.promise;
  });
  fn.pending = pending;
  return fn;
}

async function toShare(opts) {
  const t = await open(opts);
  await t.press('Next');
  return t;
}
const inputOf = (t) =>
  t.dom.find(
    t.root(),
    (el) => el.tag === 'input' && el.getAttribute('aria-label') === 'People to share with',
  );
function typeInto(t, text) {
  const i = inputOf(t);
  i.value = text;
  t.dom.fire(i, 'input');
  return i;
}
function enter(t, text) {
  const i = inputOf(t);
  i.value = text;
  return t.dom.fire(i, 'keydown', { key: 'Enter' });
}
const key = (t, k) => t.dom.fire(inputOf(t), 'keydown', { key: k });
const chipNames = (t) => t.cls('ss-chip').map((c) => c.firstChild.textContent);
const suggestRows = (t) =>
  t.cls('ss-suggest-item').map((li) => li.children.map((c) => c.textContent));
const listHidden = (t) => t.one('ss-suggest').hidden;
const fieldError = (t) => t.one('ss-error').textContent;
const noticeTitles = (t) => t.cls('ss-notice-title').map((n) => n.textContent);
async function search(t, q) {
  typeInto(t, q);
  t.clock.tick(250);
  await flush();
}
const ANN = [
  ['Ann Lee', 'Ann.Lee@contoso.com'],
  ['Anna Wu', 'anna.wu@contoso.com'],
  ['ann.x@contoso.com'],
];

test('nothing is searched until two characters are typed', async () => {
  const s = makeSearch();
  const t = await toShare({ search: s });
  typeInto(t, 'a');
  t.clock.tick(1000);
  await flush();
  assert.strictEqual(s.calls.length, 0);
  assert.strictEqual(listHidden(t), true);
  typeInto(t, 'an');
  t.clock.tick(249);
  assert.strictEqual(s.calls.length, 0);
  t.clock.tick(1);
  await flush();
  assert.deepStrictEqual(
    s.calls.map((c) => c.q),
    ['an'],
  );
});

test('the search waits for a pause in typing', async () => {
  const s = makeSearch();
  const t = await toShare({ search: s });
  typeInto(t, 'an');
  t.clock.tick(200);
  typeInto(t, 'ann');
  t.clock.tick(200);
  assert.strictEqual(s.calls.length, 0);
  t.clock.tick(50);
  await flush();
  assert.deepStrictEqual(
    s.calls.map((c) => c.q),
    ['ann'],
  );
});

test('clearing the box before the pause cancels the search', async () => {
  const s = makeSearch();
  const t = await toShare({ search: s });
  typeInto(t, 'an');
  typeInto(t, '');
  t.clock.tick(1000);
  await flush();
  assert.strictEqual(s.calls.length, 0);
});

test('results are listed with name and address, nothing selected, and the box announces it', async () => {
  const t = await toShare({ search: makeSearch() });
  const input = inputOf(t);
  assert.strictEqual(input.getAttribute('role'), 'combobox');
  assert.strictEqual(input.getAttribute('aria-expanded'), 'false');
  await search(t, 'an');
  assert.deepStrictEqual(suggestRows(t), ANN);
  assert.strictEqual(listHidden(t), false);
  assert.strictEqual(input.getAttribute('aria-expanded'), 'true');
  assert.deepStrictEqual(
    t.cls('ss-suggest-item').map((li) => li.getAttribute('aria-selected')),
    ['false', 'false', 'false'],
  );
});

test('Searching people shows only while there is nothing else to list', async () => {
  const s = gatedSearch();
  const t = await toShare({ search: s });
  await search(t, 'an');
  assert.strictEqual(t.cls('ss-suggest-busy').length, 1);
  assert(t.text().includes('Searching people...'));
  assert.strictEqual(t.cls('ss-suggest-item').length, 0);
  s.pending[0].resolve(clone(PEOPLE));
  await flush();
  assert.strictEqual(t.cls('ss-suggest-busy').length, 0);
  assert.strictEqual(t.cls('ss-suggest-item').length, 3);
  await search(t, 'ann');
  assert.strictEqual(s.pending.length, 2);
  assert.strictEqual(t.cls('ss-suggest-busy').length, 0, 'the earlier results stay up');
  assert.deepStrictEqual(suggestRows(t), ANN);
});

test('a newer search aborts the older request and drops its late answer', async () => {
  const s = gatedSearch();
  const t = await toShare({ search: s });
  await search(t, 'an');
  assert.strictEqual(s.calls[0].signal.aborted, false);
  await search(t, 'ann');
  assert.strictEqual(s.calls[0].signal.aborted, true);
  assert.strictEqual(s.calls[1].signal.aborted, false);
  s.pending[0].resolve([{ name: 'Stale Person', email: 'stale@contoso.com' }]);
  await flush();
  assert(!t.text().includes('Stale'));
  s.pending[1].resolve(clone(PEOPLE));
  await flush();
  assert.deepStrictEqual(suggestRows(t), ANN);
});

test('clearing the box aborts the request and closes the list', async () => {
  const s = gatedSearch();
  const t = await toShare({ search: s });
  await search(t, 'an');
  typeInto(t, '');
  assert.strictEqual(s.calls[0].signal.aborted, true);
  assert.strictEqual(listHidden(t), true);
  s.pending[0].resolve(clone(PEOPLE));
  await flush();
  assert.strictEqual(listHidden(t), true);
});

test('an answered query is cached, whatever the case, and needs no new request', async () => {
  const s = makeSearch();
  const t = await toShare({ search: s });
  await search(t, 'an');
  typeInto(t, '');
  typeInto(t, 'AN');
  assert.deepStrictEqual(suggestRows(t), ANN);
  t.clock.tick(1000);
  await flush();
  assert.strictEqual(s.calls.length, 1);
});

test('a failed search is not cached, so typing it again asks again', async () => {
  const s = makeSearch((q, signal, n) =>
    n === 1 ? Promise.reject(new Error('offline')) : Promise.resolve(clone(PEOPLE)),
  );
  const t = await toShare({ search: s });
  await search(t, 'an');
  assert.strictEqual(listHidden(t), true);
  assert.strictEqual(t.cls('ss-suggest-item').length, 0);
  await search(t, 'an');
  assert.strictEqual(s.calls.length, 2);
  assert.deepStrictEqual(suggestRows(t), ANN);
});

test('a typed address that is not in the results gets an Add row, even before the search returns', async () => {
  const t = await toShare({ search: makeSearch(() => Promise.resolve([])) });
  typeInto(t, 'new.person@contoso.com');
  assert.deepStrictEqual(suggestRows(t), [['Add new.person@contoso.com']]);
  t.clock.tick(250);
  await flush();
  assert.deepStrictEqual(suggestRows(t), [['Add new.person@contoso.com']]);
  const e = t.dom.fire(t.cls('ss-suggest-item')[0], 'mousedown');
  assert.strictEqual(e.prevented, true);
  assert.deepStrictEqual(chipNames(t), ['new.person@contoso.com']);
  assert.strictEqual(inputOf(t).value, '');
  assert.strictEqual(listHidden(t), true);
});

test('no Add row when the address is already listed or already a chip', async () => {
  const s = makeSearch(() => Promise.resolve([{ name: 'Ann Lee', email: 'Ann.Lee@contoso.com' }]));
  const t = await toShare({ search: s });
  await search(t, 'ann.lee@contoso.com');
  assert.deepStrictEqual(suggestRows(t), [['Ann Lee', 'Ann.Lee@contoso.com']]);
  enter(t, 'ann.lee@contoso.com');
  typeInto(t, 'ann.lee@contoso.com');
  assert.deepStrictEqual(suggestRows(t), []);
});

test('picking a result adds a chip with the name and hides that person from the next list', async () => {
  const t = await toShare({ search: makeSearch() });
  await search(t, 'an');
  const e = t.dom.fire(t.cls('ss-suggest-item')[0], 'mousedown');
  assert.strictEqual(e.prevented, true);
  assert.deepStrictEqual(chipNames(t), ['Ann Lee']);
  assert.strictEqual(t.cls('ss-chip')[0].getAttribute('title'), 'ann.lee@contoso.com');
  assert.strictEqual(inputOf(t).value, '');
  typeInto(t, 'an');
  assert.deepStrictEqual(suggestRows(t), ANN.slice(1));
});

test('arrow keys move through the results, wrap around, and Enter picks the active one', async () => {
  const t = await toShare({ search: makeSearch() });
  await search(t, 'an');
  const active = () => t.cls('ss-suggest-item').map((li) => li.getAttribute('aria-selected'));
  let e = key(t, 'ArrowDown');
  assert.strictEqual(e.prevented, true);
  assert.deepStrictEqual(active(), ['true', 'false', 'false']);
  assert(t.dom.hasClass(t.cls('ss-suggest-item')[0], 'is-active'));
  assert.strictEqual(
    inputOf(t).getAttribute('aria-activedescendant'),
    t.cls('ss-suggest-item')[0].id,
  );
  key(t, 'ArrowUp');
  assert.deepStrictEqual(active(), ['false', 'false', 'true']);
  key(t, 'ArrowDown');
  key(t, 'ArrowDown');
  assert.deepStrictEqual(active(), ['false', 'true', 'false']);
  e = key(t, 'Enter');
  assert.strictEqual(e.prevented, true);
  assert.deepStrictEqual(chipNames(t), ['Anna Wu']);
});

test('Enter turns a typed address into a chip, lower-cased', async () => {
  const t = await toShare({ search: makeSearch() });
  const e = enter(t, 'Bob@Contoso.com');
  assert.strictEqual(e.prevented, true);
  assert.deepStrictEqual(chipNames(t), ['bob@contoso.com']);
  assert.strictEqual(inputOf(t).value, '');
  enter(t, 'bob@contoso.com');
  assert.deepStrictEqual(chipNames(t), ['bob@contoso.com'], 'the same address is not added twice');
  assert.strictEqual(enter(t, '').prevented, false);
});

test('a comma or semicolon commits what was typed before it', async () => {
  const t = await toShare({ search: makeSearch() });
  typeInto(t, 'a@x.com, b@x.com;');
  assert.deepStrictEqual(chipNames(t), ['a@x.com', 'b@x.com']);
  assert.strictEqual(inputOf(t).value, '');
  typeInto(t, 'c@x.com, leftover');
  assert.deepStrictEqual(chipNames(t), ['a@x.com', 'b@x.com', 'c@x.com']);
  assert.strictEqual(inputOf(t).value, 'leftover');
  assert.strictEqual(fieldError(t), '"leftover" is not a valid email address.');
});

test('Backspace in an empty box removes the last chip, and the x on a chip removes that one', async () => {
  const t = await toShare({ search: makeSearch() });
  enter(t, 'a@x.com');
  enter(t, 'b@x.com');
  enter(t, 'c@x.com');
  const e = key(t, 'Backspace');
  assert.strictEqual(e.prevented, true);
  assert.deepStrictEqual(chipNames(t), ['a@x.com', 'b@x.com']);
  inputOf(t).value = 'typ';
  assert.strictEqual(key(t, 'Backspace').prevented, false);
  assert.deepStrictEqual(chipNames(t), ['a@x.com', 'b@x.com']);
  inputOf(t).value = '';
  t.dom
    .find(t.root(), (el) => el.getAttribute && el.getAttribute('aria-label') === 'Remove a@x.com')
    .click();
  assert.deepStrictEqual(chipNames(t), ['b@x.com']);
});

test('a chip is flagged as outside the organization only once the directory has shown the domains', async () => {
  const t = await toShare({ search: makeSearch() });
  enter(t, 'outsider@gmail.com');
  assert.strictEqual(t.cls('ss-chip')[0].className, 'ss-chip');
  assert.deepStrictEqual(noticeTitles(t), []);
  await search(t, 'an');
  assert.strictEqual(t.cls('ss-chip')[0].className, 'ss-chip is-warn');
  assert.strictEqual(
    t.cls('ss-chip')[0].getAttribute('title'),
    'outsider@gmail.com (outside your organization)',
  );
  enter(t, 'ann.lee@contoso.com');
  assert.deepStrictEqual(
    t.cls('ss-chip').map((c) => c.className),
    ['ss-chip is-warn', 'ss-chip'],
  );
  assert.deepStrictEqual(noticeTitles(t), ['May need adding in OneDrive']);
  assert(
    t
      .text()
      .includes(
        'outsider@gmail.com is outside your organization, so access may not be given automatically. They still get the email. You can add them to the folder in OneDrive afterwards.',
      ),
  );
  enter(t, 'other@yahoo.com');
  assert(t.text().includes('outsider@gmail.com, other@yahoo.com are outside your organization'));
  t.dom
    .find(
      t.root(),
      (el) => el.getAttribute && el.getAttribute('aria-label') === 'Remove outsider@gmail.com',
    )
    .click();
  t.dom
    .find(
      t.root(),
      (el) => el.getAttribute && el.getAttribute('aria-label') === 'Remove other@yahoo.com',
    )
    .click();
  assert.deepStrictEqual(noticeTitles(t), []);
});

test('a chip typed as an address takes the name the directory later reports', async () => {
  const t = await toShare({ search: makeSearch() });
  enter(t, 'ann.lee@contoso.com');
  assert.deepStrictEqual(chipNames(t), ['ann.lee@contoso.com']);
  await search(t, 'an');
  assert.deepStrictEqual(chipNames(t), ['Ann Lee']);
});

test('text that is not an address stays in the box with an error, and Next will not move on', async () => {
  const t = await toShare({ search: makeSearch() });
  enter(t, 'nobody');
  assert.strictEqual(fieldError(t), '"nobody" is not a valid email address.');
  assert.strictEqual(inputOf(t).value, 'nobody');
  assert.strictEqual(inputOf(t).getAttribute('aria-invalid'), 'true');
  await t.press('Next');
  assert.strictEqual(t.cls('ss-label')[0].textContent, 'Share with');
  assert.deepStrictEqual(chipNames(t), []);
});

test('adding a chip clears the error', async () => {
  const t = await toShare({ search: makeSearch() });
  enter(t, 'nobody');
  assert.notStrictEqual(fieldError(t), '');
  inputOf(t).value = '';
  enter(t, 'a@x.com');
  assert.strictEqual(fieldError(t), '');
});

test('without a search function the box still takes addresses and never opens a list', async () => {
  const t = await toShare({});
  const input = inputOf(t);
  assert.strictEqual(input.getAttribute('role'), null);
  typeInto(t, 'an');
  t.clock.tick(1000);
  await flush();
  assert.strictEqual(listHidden(t), true);
  enter(t, 'a@x.com');
  assert.deepStrictEqual(chipNames(t), ['a@x.com']);
});

test('Next waits for a person, but typed text counts', async () => {
  const t = await toShare({});
  assert.strictEqual(t.nextDisabled(), true);
  typeInto(t, 'x');
  assert.strictEqual(t.nextDisabled(), false);
  typeInto(t, '');
  assert.strictEqual(t.nextDisabled(), true);
  enter(t, 'a@x.com');
  assert.strictEqual(t.nextDisabled(), false);
  t.dom
    .find(t.root(), (el) => el.getAttribute && el.getAttribute('aria-label') === 'Remove a@x.com')
    .click();
  assert.strictEqual(t.nextDisabled(), true);
});

test('Next turns a typed address into a chip and moves on to Send', async () => {
  const t = await toShare({});
  typeInto(t, 'carol@contoso.com');
  await t.press('Next');
  assert(t.text().includes('Email to'));
  assert.deepStrictEqual(
    t.cls('ss-to-row').map((r) => r.textContent),
    ['carol@contoso.com'],
  );
});

test('a private folder explains the read access people get', async () => {
  const t = await toShare({});
  assert(t.text().includes('These people get read access to this skill.'));
  assert.deepStrictEqual(noticeTitles(t), []);
});

test('an already shared folder says who can use it and lets Next go with nobody added', async () => {
  const wording = [
    [
      LIBRARY,
      'Everyone with access to Contoso Team can already use it. Add people only to include them in the message.',
    ],
    [
      { kind: 'org' },
      'Everyone in your organization can already use it. Add people only to include them in the message.',
    ],
    [
      { kind: 'folder' },
      'The people this folder is shared with can already use it. Add people only to include them in the message.',
    ],
  ];
  for (const [audience, text] of wording) {
    const t = await open({
      get: (url) => (url.includes('/share/check') ? json(checkBody(audience)) : undefined),
    });
    const box = t.checkbox();
    box.checked = true;
    t.dom.fire(box, 'change');
    await t.press('Next');
    assert.deepStrictEqual(noticeTitles(t), ['People can already use it']);
    assert(t.text().includes(text), text);
    assert.strictEqual(t.nextDisabled(), false);
  }
});

test('Escape closes an open suggestion list first and the modal second', async () => {
  const t = await toShare({ search: makeSearch() });
  await search(t, 'an');
  assert.strictEqual(listHidden(t), false);
  const e = t.dom.key('Escape');
  assert.strictEqual(e.prevented, true);
  assert.strictEqual(listHidden(t), true);
  assert(t.root());
  t.dom.key('Escape');
  assert.strictEqual(t.root(), null);
});

test('Back keeps the chips for when I return', async () => {
  const t = await toShare({ search: makeSearch() });
  enter(t, 'a@x.com');
  enter(t, 'b@x.com');
  await t.press('Back');
  assert.strictEqual(t.cls('ss-label')[0].textContent, 'Save to');
  await t.press('Next');
  assert.deepStrictEqual(chipNames(t), ['a@x.com', 'b@x.com']);
});

// ── Step 3: message and send, and the Done view ───────────────────────────

const ANN_EMAIL = 'ann.lee@contoso.com';
const DRAFT_ROUTE = '/api/skills/share/draft';
const PUBLISH_ROUTE = '/api/skills/share/publish';

// who: 'ann' picks Ann Lee from the directory (a named chip); anything else is
// typed as an address. opts.pick chooses a recent folder, opts.ack ticks the box.
async function toSend(opts, who) {
  opts = Object.assign({ search: makeSearch() }, opts);
  const t = await open(opts);
  if (opts.pick) await pickRadio(t, opts.pick);
  if (opts.ack) {
    const box = t.checkbox();
    box.checked = true;
    t.dom.fire(box, 'change');
  }
  await t.press('Next');
  for (const w of who || ['ann']) {
    if (w === 'ann') {
      await search(t, 'an');
      t.dom.fire(t.cls('ss-suggest-item')[0], 'mousedown');
    } else {
      enter(t, w);
    }
  }
  await t.press('Next');
  return t;
}

const publishWith = (over) => (url) =>
  url === PUBLISH_ROUTE ? json(Object.assign(clone(PUBLISHED), over)) : undefined;
const failOn = (route, status, code, message) => (url) =>
  url === route ? fail(status, code, message) : undefined;

// Holds the request for each listed route until the test releases it.
function gated(routes) {
  const pending = {};
  const fn = (url) => {
    if (routes.indexOf(url) === -1) return undefined;
    const d = defer();
    (pending[url] = pending[url] || []).push(d);
    return d.promise;
  };
  fn.pending = pending;
  return fn;
}
const sendStatus = (t) => t.one('ss-status').textContent;
const errorBox = (t) => t.cls('ss-audience').filter((b) => t.dom.hasClass(b, 'is-blocked'));
const alertText = (t) => t.cls('ss-error').map((p) => p.textContent);
const messageBox = (t) => t.dom.byTag(t.root(), 'textarea');
const FOLDER_FAULTS = ['not_yours', 'forbidden', 'not_found', 'invalid', 'audience_unacknowledged'];

test('Send lists who the email goes to and shows a read-only message box waiting for the skill to be saved', async () => {
  const t = await toSend({}, ['ann', 'bob@contoso.com']);
  assert.strictEqual(t.heading(), 'Share "weekly-report"');
  assert.strictEqual(t.one('is-current').textContent, '3Send');
  assert.strictEqual(t.cls('ss-label')[0].textContent, 'Email to');
  assert.deepStrictEqual(
    t.cls('ss-to-row').map((r) => r.textContent),
    ['Ann Lee ' + ANN_EMAIL, 'bob@contoso.com'],
  );
  assert.deepStrictEqual(
    t.cls('ss-to-email').map((r) => r.textContent),
    [ANN_EMAIL],
  );
  const box = messageBox(t);
  assert.strictEqual(box.readOnly, true);
  assert.strictEqual(box.id, 'ss-message');
  assert.strictEqual(box.value, '');
  assert.strictEqual(box.parent.hidden, true);
  assert.strictEqual(
    t.dom.find(t.root(), (el) => el.tag === 'label').getAttribute('for'),
    'ss-message',
  );
  assert.strictEqual(
    t.btn('Send').getAttribute('title'),
    'Opens an email draft for you to approve. Nothing is sent automatically.',
  );
  assert.strictEqual(t.btn('Send').disabled, false);
  assert.strictEqual(t.dom.state.activeElement, t.btn('Send'));
  assert.deepStrictEqual(t.calls.post, []);
});

test('with nobody added Send is off, Copy is on and takes the focus', async () => {
  const t = await open({ get: lockedLocations });
  await t.press('Next');
  await t.press('Next');
  assert.deepStrictEqual(
    t.cls('ss-to-row').map((r) => r.textContent),
    ['No one added. Use Copy message to share the link yourself.'],
  );
  assert.strictEqual(t.btn('Send').disabled, true);
  assert.strictEqual(t.btn('Copy message').disabled, false);
  assert.strictEqual(t.dom.state.activeElement, t.btn('Copy message'));
});

test('Copy saves the skill first and then copies the message it got back', async () => {
  const t = await toSend({});
  await t.press('Copy message');
  assert.deepStrictEqual(t.calls.order.slice(-2), ['publish', 'copy']);
  assert.deepStrictEqual(t.clip.written, [PUBLISHED.message]);
  assert.strictEqual(messageBox(t).value, PUBLISHED.message);
  assert.strictEqual(messageBox(t).parent.hidden, false);
  assert.strictEqual(sendStatus(t), 'Message copied.');
  assert.deepStrictEqual(t.calls.alerts, []);
  assert.strictEqual(t.btn('Copy message').disabled, false);
});

test('the save request carries the skill, the addresses, the default folder as no root, and no acknowledgement', async () => {
  const t = await toSend({}, ['ann', 'bob@contoso.com']);
  await t.press('Copy message');
  assert.deepStrictEqual(t.calls.post, [
    {
      url: PUBLISH_ROUTE,
      payload: {
        skill_id: 'weekly-report',
        people: [ANN_EMAIL, 'bob@contoso.com'],
        root: null,
        audience_ack: false,
      },
    },
  ]);
});

test('a recent folder is sent as its drive and folder ids', async () => {
  const t = await toSend({ pick: 1 });
  await t.press('Copy message');
  assert.deepStrictEqual(t.calls.post[0].payload.root, { drive_id: 'b!team', folder_id: 'f1' });
});

test('a skill locked to its folder is saved with no root', async () => {
  const t = await toSend({ get: lockedLocations });
  await t.press('Copy message');
  assert.strictEqual(t.calls.post[0].payload.root, null);
});

test('a ticked acknowledgement is passed on', async () => {
  const t = await toSend({
    get: (url) => (url.includes('/share/check') ? json(checkBody(LIBRARY)) : undefined),
    ack: true,
  });
  await t.press('Copy message');
  assert.strictEqual(t.calls.post[0].payload.audience_ack, true);
});

test('copying twice saves once', async () => {
  const t = await toSend({});
  await t.press('Copy message');
  await t.press('Copy message');
  assert.deepStrictEqual(t.calls.order.filter((o) => o === 'publish').length, 1);
  assert.strictEqual(t.clip.written.length, 2);
});

test('Send saves, asks for an email draft, opens it, then shows Done', async () => {
  const t = await toSend({}, ['ann', 'bob@contoso.com']);
  await t.press('Send');
  assert.deepStrictEqual(t.calls.order.slice(-3), ['publish', 'draft', 'drafts']);
  assert.deepStrictEqual(t.calls.post[1], {
    url: DRAFT_ROUTE,
    payload: {
      skill_id: 'weekly-report',
      channel: 'email',
      people: [{ name: 'Ann Lee', email: ANN_EMAIL }, { email: 'bob@contoso.com' }],
      message: PUBLISHED.message,
      message_html: PUBLISHED.message_html,
    },
  });
  assert.deepStrictEqual(t.calls.drafts, [DRAFT.drafts]);
  assert.deepStrictEqual(t.calls.alerts, []);
  assert.strictEqual(t.calls.post.length, 2);
});

test('Done says the draft needs approval, where the skill went, and links to OneDrive', async () => {
  const t = await toSend({});
  await t.press('Send');
  assert.strictEqual(t.heading(), 'Shared "weekly-report"');
  assert(t.text().includes('Email draft ready for your approval'));
  assert(t.text().includes('Nothing is sent until you approve it in the chat.'));
  assert(t.text().includes('Saved to OneDrive › AI Gator Skills › weekly-report.'));
  assert.strictEqual(t.btn('Send'), null);
  assert.strictEqual(t.btn('Copy message'), null);
  const link = t.dom.find(t.root(), (el) => el.tag === 'a');
  assert.strictEqual(link.textContent, 'Open in OneDrive');
  assert.strictEqual(link.href, PUBLISHED.web_url);
  assert.strictEqual(link.target, '_blank');
  assert.strictEqual(link.rel, 'noopener');
});

test('Open in OneDrive is only offered for an https link', async () => {
  for (const web_url of ['http://contoso.sharepoint.com/x', 'javascript:alert(1)', '', undefined]) {
    const t = await toSend({ post: publishWith({ web_url }) });
    await t.press('Send');
    assert.strictEqual(
      t.dom.find(t.root(), (el) => el.tag === 'a'),
      null,
      String(web_url),
    );
  }
});

test('Done falls back to the chosen folder when the server gives no path', async () => {
  const t = await toSend({ post: publishWith({ saved_path: undefined }) });
  await t.press('Send');
  assert(t.text().includes('Saved to OneDrive › AI Gator Skills.'));
});

test('Done names the locked folder when the server gives no path', async () => {
  const t = await toSend({ get: lockedLocations, post: publishWith({ saved_path: [] }) });
  await t.press('Send');
  assert(t.text().includes('Saved to Contoso Team › Documents › Team Skills.'));
});

test('Copy then Send saves only once', async () => {
  const t = await toSend({});
  await t.press('Copy message');
  await t.press('Send');
  assert.deepStrictEqual(t.calls.order.slice(-4), ['publish', 'copy', 'draft', 'drafts']);
  assert.strictEqual(t.calls.order.filter((o) => o === 'publish').length, 1);
});

test('people with no matching account raise a warning alert after the draft opens', async () => {
  const t = await toSend({
    post: (url) =>
      url === DRAFT_ROUTE
        ? json({ drafts: DRAFT.drafts, unmatched: ['a@x.com', 'b@x.com'] })
        : undefined,
  });
  await t.press('Send');
  assert.deepStrictEqual(t.calls.alerts, [
    ['No account was found for a@x.com, b@x.com. Use Copy message to reach them.', 'warning'],
  ]);
  assert.deepStrictEqual(t.calls.drafts, [DRAFT.drafts]);
  assert.strictEqual(t.heading(), 'Shared "weekly-report"');
});

test('a policy block says nobody was given access and offers no other folder', async () => {
  const t = await toSend({
    post: failOn(PUBLISH_ROUTE, 403, 'policy_blocked', 'Your organization blocks sharing.'),
  });
  await t.press('Send');
  const boxes = errorBox(t);
  assert.strictEqual(boxes.length, 1);
  assert.strictEqual(boxes[0].getAttribute('role'), 'alert');
  assert.strictEqual(
    t.dom.byClass(boxes[0], 'ss-audience-title').textContent,
    'Nobody has been given access',
  );
  assert.strictEqual(
    t.dom.byClass(boxes[0], 'ss-audience-text').textContent,
    'Your organization blocks sharing.',
  );
  assert.strictEqual(t.btn('Choose another folder'), null);
  assert.deepStrictEqual(t.calls.order.slice(-1), ['publish']);
  assert.strictEqual(t.btn('Send').disabled, false);
  assert.strictEqual(t.btn('Back').disabled, false);
  assert.strictEqual(t.heading(), 'Share "weekly-report"');
});

test('a folder fault says it could not save and offers another folder, which goes back to Save', async () => {
  for (const code of FOLDER_FAULTS) {
    const t = await toSend({ post: failOn(PUBLISH_ROUTE, 400, code, 'Trouble: ' + code) });
    await t.press('Send');
    const boxes = errorBox(t);
    assert.strictEqual(boxes.length, 1, code);
    assert.strictEqual(
      t.dom.byClass(boxes[0], 'ss-audience-title').textContent,
      'Could not save to this folder',
    );
    assert.strictEqual(t.dom.byClass(boxes[0], 'ss-audience-text').textContent, 'Trouble: ' + code);
    await t.press('Choose another folder');
    assert.strictEqual(t.cls('ss-label')[0].textContent, 'Save to', code);
    assert.strictEqual(errorBox(t).length, 0);
  }
});

test('a locked skill has no other folder to choose', async () => {
  for (const code of FOLDER_FAULTS) {
    const t = await toSend({
      get: lockedLocations,
      post: failOn(PUBLISH_ROUTE, 403, code, 'No access'),
    });
    await t.press('Send');
    assert.strictEqual(errorBox(t).length, 1, code);
    assert.strictEqual(t.btn('Choose another folder'), null, code);
  }
});

test('any other failure shows the server message as an alert', async () => {
  const t = await toSend({ post: failOn(PUBLISH_ROUTE, 500, 'boom', 'The server exploded.') });
  await t.press('Send');
  assert.deepStrictEqual(alertText(t), ['The server exploded.']);
  assert.strictEqual(t.dom.byClass(t.root(), 'ss-error').getAttribute('role'), 'alert');
  assert.strictEqual(t.btn('Choose another folder'), null);
  assert.strictEqual(errorBox(t).length, 0);
});

test('failures with no usable message fall back to the default or the address hint', async () => {
  const bare = await toSend({
    post: (url) => (url === PUBLISH_ROUTE ? json({ detail: { error: 'boom' } }, 500) : undefined),
  });
  await bare.press('Send');
  assert.deepStrictEqual(alertText(bare), ['Could not share this skill. Try again.']);
  const net = await toSend({
    post: (url) => {
      if (url === PUBLISH_ROUTE) throw new Error('offline');
    },
  });
  await net.press('Send');
  assert.deepStrictEqual(alertText(net), ['Could not share this skill. Try again.']);
  const bad = await toSend({
    post: (url) => (url === PUBLISH_ROUTE ? json({ detail: [{ loc: ['body'] }] }, 422) : undefined),
  });
  await bad.press('Send');
  assert.deepStrictEqual(alertText(bad), ['Check the email addresses and try again.']);
});

test('after a failed save, Send tries to save again and then carries on', async () => {
  let n = 0;
  const t = await toSend({
    post: (url) => {
      if (url !== PUBLISH_ROUTE) return undefined;
      n += 1;
      return n === 1 ? fail(500, 'boom', 'The server exploded.') : undefined;
    },
  });
  await t.press('Send');
  assert.strictEqual(t.cls('ss-error').length, 1);
  await t.press('Send');
  assert.strictEqual(n, 2);
  assert.deepStrictEqual(t.calls.order.slice(-3), ['publish', 'draft', 'drafts']);
  assert.strictEqual(t.heading(), 'Shared "weekly-report"');
});

test('a failed draft keeps the saved message and does not save again on retry', async () => {
  let n = 0;
  const t = await toSend({
    post: (url) => {
      if (url !== DRAFT_ROUTE) return undefined;
      n += 1;
      return n === 1 ? fail(502, 'mail_down', 'Mail is down.') : undefined;
    },
  });
  await t.press('Send');
  assert.deepStrictEqual(alertText(t), ['Mail is down.']);
  assert.strictEqual(messageBox(t).value, PUBLISHED.message);
  assert.strictEqual(t.heading(), 'Share "weekly-report"');
  assert.strictEqual(t.calls.drafts.length, 0);
  assert.strictEqual(t.btn('Send').disabled, false);
  await t.press('Send');
  assert.deepStrictEqual(t.calls.order.filter((o) => o === 'publish').length, 1);
  assert.deepStrictEqual(t.calls.order.slice(-3), ['draft', 'draft', 'drafts']);
  assert.deepStrictEqual(alertText(t), []);
});

test('a failed draft with no message offers Copy message instead', async () => {
  const t = await toSend({
    post: (url) => (url === DRAFT_ROUTE ? json({ detail: {} }, 502) : undefined),
  });
  await t.press('Send');
  assert.deepStrictEqual(alertText(t), ['Could not prepare the draft. Use Copy message instead.']);
  const n = await toSend({
    post: (url) => {
      if (url === DRAFT_ROUTE) throw new Error('offline');
    },
  });
  await n.press('Send');
  assert.deepStrictEqual(alertText(n), ['Could not prepare the draft. Use Copy message instead.']);
});

test('with no way to open drafts here, it says so and stays on Send', async () => {
  const t = await toSend({ noDrafts: true });
  await t.press('Send');
  assert.deepStrictEqual(alertText(t), [
    'Could not open the draft here. Use Copy message instead.',
  ]);
  assert.strictEqual(t.heading(), 'Share "weekly-report"');
  assert.deepStrictEqual(t.calls.alerts, []);
});

test('while saving, the buttons are off, a second Send is ignored, and a status line shows', async () => {
  const g = gated([PUBLISH_ROUTE, DRAFT_ROUTE]);
  const t = await toSend({ post: g });
  t.btn('Send').click();
  await flush();
  assert.strictEqual(sendStatus(t), 'Saving the skill and giving access...');
  assert.strictEqual(t.btn('Back').disabled, true);
  assert.strictEqual(t.btn('Copy message').disabled, true);
  assert.strictEqual(t.btn('Send').disabled, true);
  t.btn('Send').click();
  t.btn('Copy message').click();
  await flush();
  assert.strictEqual(g.pending[PUBLISH_ROUTE].length, 1);
  g.pending[PUBLISH_ROUTE][0].resolve(json(clone(PUBLISHED)));
  await flush();
  assert.strictEqual(sendStatus(t), 'Preparing draft...');
  assert.strictEqual(messageBox(t).value, PUBLISHED.message);
  assert.strictEqual(t.btn('Send').disabled, true);
  g.pending[DRAFT_ROUTE][0].resolve(json(clone(DRAFT)));
  await flush();
  assert.strictEqual(t.heading(), 'Shared "weekly-report"');
  assert.strictEqual(t.calls.drafts.length, 1);
  assert.strictEqual(g.pending[DRAFT_ROUTE].length, 1);
});

test('the buttons come back after a failure', async () => {
  const t = await toSend({ post: failOn(PUBLISH_ROUTE, 500, 'boom', 'Nope') });
  await t.press('Copy message');
  assert.strictEqual(sendStatus(t), '');
  assert.strictEqual(t.btn('Back').disabled, false);
  assert.strictEqual(t.btn('Copy message').disabled, false);
  assert.strictEqual(t.btn('Send').disabled, false);
  assert.deepStrictEqual(t.clip.written, []);
});

test('closing while the save is running still refreshes once it succeeds, and sends nothing', async () => {
  const g = gated([PUBLISH_ROUTE]);
  const t = await toSend({ post: g });
  t.btn('Send').click();
  await flush();
  t.btn('×').click();
  assert.strictEqual(t.root(), null);
  assert.strictEqual(t.calls.refresh, 0);
  g.pending[PUBLISH_ROUTE][0].resolve(json(clone(PUBLISHED)));
  await flush();
  assert.strictEqual(t.calls.refresh, 1);
  assert.deepStrictEqual(t.calls.order, ['publish']);
  assert.deepStrictEqual(t.calls.drafts, []);
  assert.deepStrictEqual(t.calls.alerts, []);
});

test('closing while the save is running does not refresh when it fails', async () => {
  const g = gated([PUBLISH_ROUTE]);
  const t = await toSend({ post: g });
  t.btn('Copy message').click();
  await flush();
  t.dom.key('Escape');
  g.pending[PUBLISH_ROUTE][0].resolve(fail(500, 'boom', 'Nope'));
  await flush();
  assert.strictEqual(t.calls.refresh, 0);
  assert.deepStrictEqual(t.clip.written, []);
});

test('closing while the draft is being prepared refreshes once and opens nothing', async () => {
  const g = gated([DRAFT_ROUTE]);
  const t = await toSend({ post: g });
  t.btn('Send').click();
  await flush();
  assert.strictEqual(sendStatus(t), 'Preparing draft...');
  t.btn('×').click();
  assert.strictEqual(t.calls.refresh, 1);
  g.pending[DRAFT_ROUTE][0].resolve(json({ drafts: DRAFT.drafts, unmatched: ['a@x.com'] }));
  await flush();
  assert.strictEqual(t.calls.refresh, 1);
  assert.deepStrictEqual(t.calls.drafts, []);
  assert.deepStrictEqual(t.calls.alerts, []);
});

test('the list refreshes on close only when the skill was saved, and only once', async () => {
  const a = await open({});
  a.btn('×').click();
  assert.strictEqual(a.calls.refresh, 0);

  const b = await toSend({});
  b.btn('×').click();
  assert.strictEqual(b.calls.refresh, 0);

  const c = await toSend({});
  await c.press('Copy message');
  assert.strictEqual(c.calls.refresh, 0);
  c.dom.key('Escape');
  c.shell.close();
  assert.strictEqual(c.calls.refresh, 1);

  const d = await toSend({});
  await d.press('Send');
  assert.strictEqual(d.calls.refresh, 0);
  d.btn('×').click();
  assert.strictEqual(d.calls.refresh, 1);
});

test('a skill saved to a new folder because the old one was deleted says so', async () => {
  const d = await toSend({ post: publishWith({ relinked: true }) });
  await d.press('Copy message');
  assert.deepStrictEqual(noticeTitles(d), ['Saved to a new folder']);
  assert(d.text().includes('The earlier link does not work anymore.'));
  const plain = await toSend({ post: publishWith({ relinked: false }) });
  await plain.press('Copy message');
  assert.deepStrictEqual(noticeTitles(plain), []);
});

test('people the folder would not accept are listed in a notice, singular and plural', async () => {
  const one = await toSend({ post: publishWith({ ungranted: ['x@gmail.com'] }) });
  await one.press('Copy message');
  assert.deepStrictEqual(noticeTitles(one), ['Access was not granted for x@gmail.com']);
  assert(
    one
      .text()
      .includes(
        'OneDrive would not let this person open the skill, usually because they are outside your organization. Add them in OneDrive',
      ),
  );
  const many = await toSend({ post: publishWith({ ungranted: ['x@gmail.com', 'y@yahoo.com'] }) });
  await many.press('Copy message');
  assert.deepStrictEqual(noticeTitles(many), [
    'Access was not granted for x@gmail.com, y@yahoo.com',
  ]);
  assert(many.text().includes('OneDrive would not let these people open the skill'));
  assert(
    many
      .text()
      .includes(
        'Add each of them in OneDrive (Open in OneDrive, then Share) so the link works for them.',
      ),
  );
});

test('the notice is still there on Done, and not shown when everyone got access', async () => {
  const t = await toSend({ post: publishWith({ ungranted: ['x@gmail.com'] }) });
  await t.press('Send');
  assert.strictEqual(t.heading(), 'Shared "weekly-report"');
  assert.deepStrictEqual(noticeTitles(t), ['Access was not granted for x@gmail.com']);
  const u = await toSend({});
  await u.press('Send');
  assert.deepStrictEqual(noticeTitles(u), []);
});

test('when the clipboard is missing or refuses, it says to copy by hand and the message is selectable', async () => {
  for (const extra of [{ noClipboard: true }, { clipboardFails: true }]) {
    const t = await toSend(extra);
    await t.press('Copy message');
    assert.deepStrictEqual(alertText(t), ['Could not copy. Select the text and copy it.']);
    assert.strictEqual(messageBox(t).value, PUBLISHED.message);
    assert.notStrictEqual(sendStatus(t), 'Message copied.');
    assert.strictEqual(t.btn('Copy message').disabled, false);
    await t.press('Copy message');
    assert.strictEqual(t.calls.order.filter((o) => o === 'publish').length, 1);
  }
});

test('Escape closes Send and puts the focus back where it came from', async () => {
  const t = boot({ search: makeSearch() });
  const trigger = t.dom.document.createElement('button');
  t.dom.state.activeElement = trigger;
  t.start();
  await flush();
  await t.press('Next');
  enter(t, 'bob@contoso.com');
  await t.press('Next');
  assert.notStrictEqual(t.dom.state.activeElement, trigger);
  const e = t.dom.key('Escape');
  assert.strictEqual(e.prevented, true);
  assert.strictEqual(t.root(), null);
  assert.strictEqual(t.dom.state.activeElement, trigger);
});

test('Tab wraps from the last button to Close and Shift+Tab wraps back', async () => {
  const t = await toSend({});
  assert.strictEqual(t.dom.state.activeElement, t.btn('Send'));
  let e = t.dom.key('Tab');
  assert.strictEqual(e.prevented, true);
  assert.strictEqual(t.dom.state.activeElement, t.btn('×'));
  e = t.dom.key('Tab', true);
  assert.strictEqual(e.prevented, true);
  assert.strictEqual(t.dom.state.activeElement, t.btn('Send'));
  t.btn('Back').focus();
  assert.strictEqual(t.dom.key('Tab').prevented, false);
  assert.strictEqual(t.dom.key('Tab', true).prevented, false);
});

test('with Send off, Copy is the last stop of the Tab loop', async () => {
  const t = await open({ get: lockedLocations });
  await t.press('Next');
  await t.press('Next');
  assert.strictEqual(t.dom.state.activeElement, t.btn('Copy message'));
  assert.strictEqual(t.dom.key('Tab').prevented, true);
  assert.strictEqual(t.dom.state.activeElement, t.btn('×'));
});

test('the Done view traps Tab between Close and Open in OneDrive, and Escape closes it', async () => {
  const t = await toSend({});
  await t.press('Send');
  assert.strictEqual(t.dom.state.activeElement, t.btn('×'));
  const link = t.dom.find(t.root(), (el) => el.tag === 'a');
  assert.strictEqual(t.dom.key('Tab', true).prevented, true);
  assert.strictEqual(t.dom.state.activeElement, link);
  assert.strictEqual(t.dom.key('Tab').prevented, true);
  assert.strictEqual(t.dom.state.activeElement, t.btn('×'));
  t.dom.key('Escape');
  assert.strictEqual(t.root(), null);
  assert.strictEqual(t.calls.refresh, 1);
});

test('going back and changing the people saves again with the new list', async () => {
  const t = await toSend({}, ['bob@contoso.com']);
  await t.press('Copy message');
  assert.strictEqual(messageBox(t).value, PUBLISHED.message);
  await t.press('Back');
  assert.deepStrictEqual(chipNames(t), ['bob@contoso.com']);
  enter(t, 'cy@contoso.com');
  await t.press('Next');
  assert.strictEqual(messageBox(t).value, '');
  await t.press('Copy message');
  assert.deepStrictEqual(
    t.calls.post.map((p) => p.payload.people),
    [['bob@contoso.com'], ['bob@contoso.com', 'cy@contoso.com']],
  );
});

test('opening a second share modal replaces the first', async () => {
  const t = await toSend({});
  await t.press('Copy message');
  const first = t.shell;
  t.start();
  assert.strictEqual(t.dom.document.body.children.length, 1);
  assert.strictEqual(first.closed, true);
  assert.notStrictEqual(t.shell, first);
  assert.strictEqual(t.calls.refresh, 1);
});

test('the modal never writes markup: names, ids and messages stay literal text', async () => {
  assert(!/innerHTML|insertAdjacentHTML|outerHTML|document\.write/.test(source));
  const evil = { name: '<img src=x onerror=1>', email: 'evil@contoso.com' };
  const message = 'Open <b>this</b> <img src=x>';
  const t = await toSend(
    {
      skill: '<b>x</b>',
      search: makeSearch(() => Promise.resolve([evil])),
      post: publishWith({ message, saved_path: ['<i>One</i>'] }),
    },
    ['ann'],
  );
  assert.strictEqual(t.heading(), 'Share "<b>x</b>"');
  assert.deepStrictEqual(
    t.cls('ss-to-row').map((r) => r.textContent),
    ['<img src=x onerror=1> evil@contoso.com'],
  );
  await t.press('Copy message');
  assert.strictEqual(messageBox(t).value, message);
  await t.press('Send');
  assert(t.text().includes('Saved to <i>One</i>.'));
  const markup = t.dom.find(t.root(), (el) => ['b', 'i', 'img'].indexOf(el.tag) !== -1);
  assert.strictEqual(markup, null);
});

// ── extractLink ──────────────────────────────────────────────────────────

const LINK = 'aigator://share?d=eyJkIjoiYWJjIiwiZiI6MX0';

test('extractLink returns a plain link unchanged', () => {
  assert.strictEqual(pure.extractLink(LINK), LINK);
  assert.strictEqual(pure.extractLink('  ' + LINK + '\n'), LINK);
});

test('extractLink finds the link inside a sentence and drops trailing punctuation', () => {
  assert.strictEqual(pure.extractLink('Hi! Open ' + LINK + '. Thanks'), LINK);
  assert.strictEqual(pure.extractLink('(' + LINK + '),'), LINK);
  assert.strictEqual(pure.extractLink('<' + LINK + '>'), LINK);
});

test('extractLink returns the first link and empty when there is none', () => {
  assert.strictEqual(pure.extractLink(LINK + ' and aigator://share?d=other'), LINK);
  assert.strictEqual(pure.extractLink('https://example.com/x'), '');
  assert.strictEqual(pure.extractLink('aigator://share?d='), '');
  assert.strictEqual(pure.extractLink(''), '');
  assert.strictEqual(pure.extractLink(undefined), '');
});

// ── openLinkReview ───────────────────────────────────────────────────────

const REVIEW = {
  skill_id: 'weekly-report',
  title: 'Weekly Report',
  description: 'Drafts the weekly status report.',
  author: 'Ann Lee',
  version: 2,
  latest: 2,
  created_at: '2026-11-01T10:00:00Z',
  digest: 'sha256:deadbeef',
  has_scripts: false,
  requested_tools: {},
  summary: { lines: ['Reads your calendar'], digest: 'sha256:deadbeef' },
  collision: '',
};

function reviewDeps(dom, review, installResult, extra) {
  const calls = { post: [], alerts: [], refresh: 0, installed: [], reviews: [], permission: [] };
  const deps = Object.assign(
    {
      postJson: async (url, payload) => {
        calls.post.push({ url, payload: JSON.parse(JSON.stringify(payload)) });
        if (url === '/api/skills/share/review') return review;
        return (
          installResult || { resp: { ok: true }, body: { ok: true, skill_id: 'weekly-report' } }
        );
      },
      showAlert: (msg, kind) => calls.alerts.push({ msg, kind }),
      errorMessage: (body) => (body && body.detail && body.detail.message) || 'Unknown error',
      appendPermissionList: (container, summary) => {
        calls.permission.push(summary);
        const p = dom.document.createElement('p');
        p.textContent = 'PERM:' + summary.lines.join('|');
        container.appendChild(p);
      },
      onInstalled: (r, rev) => {
        calls.installed.push(r);
        calls.reviews.push(rev);
      },
      refresh: () => {
        calls.refresh += 1;
      },
    },
    extra,
  );
  return { deps, calls };
}

const okReview = (over) => ({ resp: { ok: true }, body: Object.assign({}, REVIEW, over) });

test('module exposes openLinkReview and extractLink', () => {
  const api = load(makeDom());
  assert.strictEqual(typeof api.openLinkReview, 'function');
  assert.strictEqual(typeof api.extractLink, 'function');
});

test('review modal shows title, description, author, scripts no, permissions and the nothing-installed note', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps, calls } = reviewDeps(dom, okReview());
  await api.openLinkReview(LINK, deps);

  assert.deepStrictEqual(calls.post, [
    { url: '/api/skills/share/review', payload: { link: LINK } },
  ]);
  const modal = dom.byClass(dom.document.body.children[0], 'mp-modal');
  assert.strictEqual(modal.getAttribute('role'), 'dialog');
  const title = dom.byClass(modal, 'mp-modal-title');
  assert.strictEqual(title.textContent, 'Review "Weekly Report"');
  assert.strictEqual(modal.getAttribute('aria-labelledby'), title.id);
  assert(dom.byText(modal, 'Drafts the weekly status report.'));
  assert(dom.byText(modal, 'Shared by Ann Lee, version 2'));
  assert.strictEqual(dom.byText(modal, 'Newer version 2 is available'), null);
  const scripts = dom.byText(modal, 'Contains scripts: no');
  assert(scripts);
  assert(!scripts.className.includes('mp-modal-community-warn'));
  assert(dom.byText(modal, 'PERM:Reads your calendar'));
  assert.deepStrictEqual(calls.permission, [REVIEW.summary]);
  assert(dom.byText(modal, 'Nothing is installed until you choose Install.'));
  assert.strictEqual(dom.byText(modal, 'Install').disabled, false);
  assert(dom.byText(modal, 'Cancel'));
});

test('scripts yes is emphasised and a newer version is announced', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = reviewDeps(dom, okReview({ has_scripts: true, version: 1, latest: 3 }));
  await api.openLinkReview(LINK, deps);
  const modal = dom.document.body.children[0];

  const scripts = dom.byText(modal, 'Contains scripts: yes');
  assert(scripts.className.split(' ').includes('mp-modal-community-warn'));
  assert(dom.byText(modal, 'Newer version 3 is available. Ask Ann Lee for the latest link.'));
});

test('Details toggle reveals the fingerprint', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = reviewDeps(dom, okReview());
  await api.openLinkReview(LINK, deps);
  const modal = dom.document.body.children[0];

  const fp = dom.byText(modal, 'Fingerprint: sha256:deadbeef');
  assert.strictEqual(fp.hidden, true);
  const toggle = dom.byText(modal, 'Details');
  assert.strictEqual(toggle.getAttribute('aria-expanded'), 'false');
  toggle.click();
  assert.strictEqual(fp.hidden, false);
  assert.strictEqual(toggle.getAttribute('aria-expanded'), 'true');
  toggle.click();
  assert.strictEqual(fp.hidden, true);
});

test('each collision shows its sentence and disables Install', async () => {
  const texts = {
    mine: 'You already have a skill of your own with this name. Rename or remove it to install this one.',
    installed: 'A skill with this name is already installed. Remove it to install this one.',
    native: 'This name is used by a built-in skill.',
  };
  for (const key of Object.keys(texts)) {
    const dom = makeDom();
    const api = load(dom);
    const { deps, calls } = reviewDeps(dom, okReview({ collision: key }));
    await api.openLinkReview(LINK, deps);
    const modal = dom.document.body.children[0];
    assert(dom.byText(modal, texts[key]), key);
    const install = dom.byText(modal, 'Install');
    assert.strictEqual(install.disabled, true, key);
    install.click();
    await flush();
    assert.strictEqual(calls.post.length, 1, 'a disabled Install posts nothing: ' + key);
  }
});

test('Install posts exactly link, version and digest from the review response', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps, calls } = reviewDeps(dom, okReview({ version: 2, latest: 4 }));
  await api.openLinkReview(LINK, deps);
  const modal = dom.document.body.children[0];

  dom.byText(modal, 'Install').click();
  await flush();

  assert.strictEqual(calls.post.length, 2);
  assert.strictEqual(calls.post[1].url, '/api/skills/share/install');
  assert.deepStrictEqual(calls.post[1].payload, {
    link: LINK,
    version: 2,
    digest: 'sha256:deadbeef',
  });
  assert.deepStrictEqual(calls.alerts, [], 'onInstalled owns the outcome message');
  assert.deepStrictEqual(calls.installed, [{ ok: true, skill_id: 'weekly-report' }]);
  assert.strictEqual(calls.reviews[0].title, 'Weekly Report', 'onInstalled also gets the review');
  assert.strictEqual(calls.refresh, 1);
  assert.strictEqual(dom.document.body.children.length, 0);
});

test('a failed review opens no modal and reports the error', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps, calls } = reviewDeps(dom, {
    resp: { ok: false, status: 400 },
    body: { detail: { error: 'invalid_link', message: 'That is not a valid share link.' } },
  });
  const out = await api.openLinkReview(LINK, deps);

  assert.strictEqual(out, null);
  assert.strictEqual(dom.document.body.children.length, 0);
  assert.deepStrictEqual(calls.alerts, [{ msg: 'That is not a valid share link.', kind: 'error' }]);
});

test('a review that throws opens no modal and reports the error', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps, calls } = reviewDeps(dom, null, null, {
    postJson: async () => {
      throw new Error('offline');
    },
  });
  await api.openLinkReview(LINK, deps);
  assert.strictEqual(dom.document.body.children.length, 0);
  assert.strictEqual(calls.alerts.length, 1);
  assert.strictEqual(calls.alerts[0].kind, 'error');
});

test('a failed install keeps the modal open with the message and re-enables Install', async () => {
  const dom = makeDom();
  const api = load(dom);
  const message = 'The package changed since you reviewed it. Review it again before installing.';
  const { deps, calls } = reviewDeps(dom, okReview(), {
    resp: { ok: false, status: 409 },
    body: { detail: { error: 'content_changed', message } },
  });
  await api.openLinkReview(LINK, deps);
  const modal = dom.document.body.children[0];
  const install = dom.byText(modal, 'Install');
  install.click();
  assert.strictEqual(install.disabled, true, 'disabled while installing');
  await flush();

  assert.strictEqual(dom.document.body.children.length, 1);
  assert.strictEqual(dom.byClass(modal, 'ss-error').textContent, message);
  assert.strictEqual(install.disabled, false);
  assert.strictEqual(calls.installed.length, 0);
  assert.strictEqual(calls.refresh, 0);
  assert.strictEqual(calls.alerts.length, 0);
});

test('Cancel and Escape post nothing beyond the review', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps, calls } = reviewDeps(dom, okReview());
  await api.openLinkReview(LINK, deps);
  dom.byText(dom.document.body.children[0], 'Cancel').click();
  assert.strictEqual(dom.document.body.children.length, 0);

  await api.openLinkReview(LINK, deps);
  dom.key('Escape');
  assert.strictEqual(dom.document.body.children.length, 0);
  assert.deepStrictEqual(
    calls.post.map((c) => c.url),
    ['/api/skills/share/review', '/api/skills/share/review'],
  );
  assert.strictEqual(calls.installed.length + calls.refresh, 0);
});

test('server text in the review modal is set with textContent only', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = reviewDeps(
    dom,
    okReview({ title: '<img src=x onerror=alert(1)>', author: '<b>x</b>' }),
  );
  await api.openLinkReview(LINK, deps);
  const modal = dom.document.body.children[0];
  assert.strictEqual(
    dom.byClass(modal, 'mp-modal-title').textContent,
    'Review "<img src=x onerror=alert(1)>"',
  );
  assert(dom.byText(modal, 'Shared by <b>x</b>, version 2'));
});
