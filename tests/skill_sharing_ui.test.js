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

  class FakeEl {
    constructor(tag) {
      this.tag = tag;
      this._text = '';
      this.className = '';
      this.children = [];
      this.parent = null;
      this._attrs = {};
      this._listeners = {};
      this.disabled = false;
      this.value = '';
      this.id = '';
      this.removed = false;
    }
    appendChild(child) {
      child.parent = this;
      this.children.push(child);
      return child;
    }
    setAttribute(k, v) {
      this._attrs[k] = v;
    }
    getAttribute(k) {
      return k in this._attrs ? this._attrs[k] : null;
    }
    addEventListener(type, fn) {
      this._listeners[type] = fn;
    }
    removeEventListener() {}
    focus() {
      state.activeElement = this;
    }
    remove() {
      this.removed = true;
      if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this);
    }
    set textContent(v) {
      this._text = String(v == null ? '' : v);
      this.children = [];
    }
    get textContent() {
      return this._text;
    }
    click() {
      const fn = this._listeners.click;
      return fn ? fn({}) : undefined;
    }
  }

  const body = new FakeEl('body');
  const document = {
    body,
    createElement: (tag) => new FakeEl(tag),
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
      if (!hit && pred(el)) hit = el;
    });
    return hit;
  }
  const byText = (root, text) => find(root, (el) => el.textContent === text);
  const byTag = (root, tag) => find(root, (el) => el.tag === tag);
  const byClass = (root, cls) => find(root, (el) => el.className.split(' ').includes(cls));

  return { document, state, key, find, byText, byTag, byClass };
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

function makeDeps(overrides) {
  const calls = { post: [], download: [], alerts: [], refresh: 0 };
  const deps = Object.assign(
    {
      postJson: async (url, payload) => {
        calls.post.push({ url, payload });
        return { resp: { ok: true }, body: {} };
      },
      downloadSkill: async (id) => {
        calls.download.push(id);
      },
      showAlert: (msg, kind) => calls.alerts.push({ msg, kind }),
      refresh: () => {
        calls.refresh += 1;
      },
    },
    overrides,
  );
  return { deps, calls };
}

const PUBLISHED = {
  skill_id: 'weekly-report',
  version: 3,
  reused: false,
  digest: 'sha256:abc',
  folder: 'AI Gator Skills/weekly-report',
  link: 'https://contoso.sharepoint.com/:f:/s/skills/abc',
  web_url: 'https://contoso.sharepoint.com/sites/skills/weekly-report',
  message: 'Hi, I shared the weekly-report skill: https://contoso.sharepoint.com/:f:/s/skills/abc',
};

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
  assert.strictEqual(pure.shareErrorText({ ok: false }, { detail: 'Skill not found' }), 'Skill not found');
  assert.strictEqual(
    pure.shareErrorText({ ok: false }, { detail: [{ loc: ['body', 'people'], msg: 'bad' }] }),
    'Check the email addresses and try again.',
  );
  assert.strictEqual(pure.shareErrorText({ ok: false }, null), 'Could not share this skill. Try again.');
  assert.strictEqual(pure.shareErrorText({ ok: false }, { detail: { code: 'x' } }), 'Could not share this skill. Try again.');
});

// ── openShareModal: form ──────────────────────────────────────────────────

test('form view has the dialog attributes, labelled input, hint and three buttons', () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = makeDeps();
  api.openShareModal('weekly-report', deps);

  assert.strictEqual(dom.document.body.children.length, 1);
  const overlay = dom.document.body.children[0];
  const modal = dom.byClass(overlay, 'mp-modal');
  assert.strictEqual(modal.getAttribute('role'), 'dialog');
  assert.strictEqual(modal.getAttribute('aria-modal'), 'true');
  const title = dom.byClass(modal, 'mp-modal-title');
  assert.strictEqual(title.textContent, 'Share "weekly-report"');
  assert.strictEqual(modal.getAttribute('aria-labelledby'), title.id);

  const label = dom.byTag(modal, 'label');
  const input = dom.byTag(modal, 'input');
  assert.strictEqual(label.textContent, 'Share with (work email addresses)');
  assert.strictEqual(label.getAttribute('for'), input.id);
  assert(dom.byText(modal, 'They can use the skill but not change it. Nobody is emailed; you copy the message and send it yourself.'));
  assert(dom.byText(modal, 'Cancel'));
  assert(dom.byText(modal, 'Download file instead'));
  assert(dom.byText(modal, 'Share').className.includes('primary'));
  assert.strictEqual(dom.state.activeElement, input);
});

test('Share with no address shows an error and calls nothing', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps, calls } = makeDeps();
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];

  dom.byText(modal, 'Share').click();
  await flush();
  assert.strictEqual(calls.post.length, 0);
  assert(dom.byClass(modal, 'ss-error').textContent.length > 0);
});

test('Share with a bad entry names it and calls nothing', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps, calls } = makeDeps();
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];

  dom.byTag(modal, 'input').value = 'good@x.com, nobody';
  dom.byText(modal, 'Share').click();
  await flush();
  assert.strictEqual(calls.post.length, 0);
  assert(dom.byClass(modal, 'ss-error').textContent.includes('nobody'));
});

test('Share with two addresses posts once and shows the result view', async () => {
  const dom = makeDom();
  const written = [];
  const api = load(dom, {
    navigator: { clipboard: { writeText: async (t) => written.push(t) } },
  });
  const { deps, calls } = makeDeps({
    postJson: async (url, payload) => {
      calls.post.push({ url, payload });
      return { resp: { ok: true }, body: PUBLISHED };
    },
  });
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];

  dom.byTag(modal, 'input').value = 'Ann@Contoso.com; bob@contoso.com';
  const shareBtn = dom.byText(modal, 'Share');
  shareBtn.click();
  assert.strictEqual(shareBtn.disabled, true, 'buttons disable while the request runs');
  assert.strictEqual(dom.byClass(modal, 'ss-status').textContent, 'Sharing...');
  await flush();

  assert.strictEqual(calls.post.length, 1);
  assert.strictEqual(calls.post[0].url, '/api/skills/share/publish');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(calls.post[0].payload)), {
    skill_id: 'weekly-report',
    people: ['ann@contoso.com', 'bob@contoso.com'],
  });

  assert.strictEqual(dom.byClass(modal, 'mp-modal-title').textContent, 'Shared as version 3');
  assert(dom.byText(modal, 'Access granted to ann@contoso.com, bob@contoso.com'));
  const area = dom.byTag(modal, 'textarea');
  assert.strictEqual(area.value, PUBLISHED.message);
  assert.strictEqual(area.readOnly, true);
  assert(dom.byText(modal, 'Copy message'));
  assert(dom.byText(modal, 'Copy link'));
  assert(dom.byText(modal, 'Done'));
  const open = dom.byText(modal, 'Open in OneDrive');
  assert.strictEqual(open.tag, 'a');
  assert.strictEqual(open.href, PUBLISHED.web_url);
  assert.strictEqual(open.target, '_blank');
  assert.strictEqual(open.rel, 'noopener');

  const copyBtn = dom.byText(modal, 'Copy message');
  copyBtn.click();
  await flush();
  assert.deepStrictEqual(written, [PUBLISHED.message]);
  assert.strictEqual(copyBtn.textContent, 'Copied');

  dom.byText(modal, 'Copy link').click();
  await flush();
  assert.deepStrictEqual(written, [PUBLISHED.message, PUBLISHED.link]);
});

test('result view for an unchanged skill and no Open link without https', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = makeDeps({
    postJson: async () => ({
      resp: { ok: true },
      body: Object.assign({}, PUBLISHED, { reused: true, version: 2, web_url: 'javascript:alert(1)' }),
    }),
  });
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];
  dom.byTag(modal, 'input').value = 'ann@contoso.com';
  dom.byText(modal, 'Share').click();
  await flush();

  assert.strictEqual(
    dom.byClass(modal, 'mp-modal-title').textContent,
    'Already shared, no changes since version 2',
  );
  assert.strictEqual(dom.byText(modal, 'Open in OneDrive'), null);
});

test('Done closes the modal and refreshes', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps, calls } = makeDeps({
    postJson: async () => ({ resp: { ok: true }, body: PUBLISHED }),
  });
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];
  dom.byTag(modal, 'input').value = 'ann@contoso.com';
  dom.byText(modal, 'Share').click();
  await flush();

  assert.strictEqual(calls.refresh, 0);
  dom.byText(modal, 'Done').click();
  assert.strictEqual(dom.document.body.children.length, 0);
  assert.strictEqual(calls.refresh, 1);
});

test('a failed response shows the message and keeps the typed text', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = makeDeps({
    postJson: async () => ({
      resp: { ok: false, status: 502 },
      body: { detail: { message: 'OneDrive is not connected.' } },
    }),
  });
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];
  const input = dom.byTag(modal, 'input');
  input.value = 'ann@contoso.com';
  const shareBtn = dom.byText(modal, 'Share');
  shareBtn.click();
  await flush();

  assert.strictEqual(dom.byClass(modal, 'ss-error').textContent, 'OneDrive is not connected.');
  assert.strictEqual(input.value, 'ann@contoso.com');
  assert.strictEqual(shareBtn.disabled, false);
  assert.strictEqual(dom.byText(modal, 'Download file instead').disabled, false);
  assert.strictEqual(dom.document.body.children.length, 1);
});

test('a network failure shows the default message and re-enables the buttons', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = makeDeps({
    postJson: async () => {
      throw new Error('offline');
    },
  });
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];
  dom.byTag(modal, 'input').value = 'ann@contoso.com';
  dom.byText(modal, 'Share').click();
  await flush();

  assert.strictEqual(dom.byClass(modal, 'ss-error').textContent, 'Could not share this skill. Try again.');
  assert.strictEqual(dom.byText(modal, 'Share').disabled, false);
});

test('Download file instead closes the modal and downloads', () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps, calls } = makeDeps();
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];

  dom.byText(modal, 'Download file instead').click();
  assert.strictEqual(dom.document.body.children.length, 0);
  assert.deepStrictEqual(calls.download, ['weekly-report']);
  assert.strictEqual(calls.post.length, 0);
});

test('Cancel and Escape close the modal without side effects', () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps, calls } = makeDeps();

  api.openShareModal('weekly-report', deps);
  dom.byText(dom.document.body.children[0], 'Cancel').click();
  assert.strictEqual(dom.document.body.children.length, 0);

  api.openShareModal('weekly-report', deps);
  const e = dom.key('Escape');
  assert.strictEqual(e.prevented, true);
  assert.strictEqual(dom.document.body.children.length, 0);
  assert.strictEqual(dom.state.keydown, null, 'keydown listener removed on close');
  assert.strictEqual(calls.post.length + calls.download.length + calls.refresh, 0);
});

test('Tab wraps inside the form view', () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = makeDeps();
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];
  const input = dom.byTag(modal, 'input');
  const shareBtn = dom.byText(modal, 'Share');

  shareBtn.focus();
  dom.key('Tab');
  assert.strictEqual(dom.state.activeElement, input);
  input.focus();
  dom.key('Tab', true);
  assert.strictEqual(dom.state.activeElement, shareBtn);
});

test('opening a second Share modal removes the first', () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = makeDeps();
  api.openShareModal('one', deps);
  const first = dom.document.body.children[0];
  api.openShareModal('two', deps);

  assert.strictEqual(first.removed, true);
  assert.strictEqual(dom.document.body.children.length, 1);
  assert.strictEqual(dom.byClass(dom.document.body.children[0], 'mp-modal-title').textContent, 'Share "two"');
});

test('server text is never written with innerHTML', () => {
  assert(!/innerHTML|insertAdjacentHTML|outerHTML/.test(source));
});
