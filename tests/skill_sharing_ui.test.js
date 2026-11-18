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
  assert.strictEqual(label.textContent, 'Share with');
  assert.strictEqual(label.getAttribute('for'), input.id);
  assert(
    dom.byText(
      modal,
      'They can use the skill but not change it. Nothing is sent until you approve an email draft.',
    ),
  );
  const radios = [];
  dom.find(modal, (el) => {
    if (el.getAttribute('role') === 'radio') radios.push(el);
    return false;
  });
  assert.deepStrictEqual(radios.map((r) => r.textContent), ['Email', 'Teams', 'Slack']);
  assert.deepStrictEqual(radios.map((r) => r.getAttribute('aria-checked')), ['true', 'false', 'false']);
  assert.strictEqual(dom.byClass(modal, 'ss-close').hidden, true, 'no X on the form view');
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
  assert(dom.byText(modal, 'Send').className.includes('primary'));
  assert.strictEqual(dom.byText(modal, 'Copy link'), null);
  assert.strictEqual(dom.byText(modal, 'Done'), null);
  assert.strictEqual(dom.byClass(modal, 'ss-close').hidden, false, 'X is shown on the result view');
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

test('the X closes the result view and refreshes the list', async () => {
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
  dom.byClass(modal, 'ss-close').click();
  assert.strictEqual(dom.document.body.children.length, 0);
  assert.strictEqual(calls.refresh, 1);
});

test('Escape on the result view closes it and refreshes the list', async () => {
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
  dom.key('Escape');
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

test('Tab skips a disabled last button so focus stays in the modal', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = reviewDeps(dom, okReview({ collision: 'mine' }));
  await api.openLinkReview(LINK, deps);
  const modal = dom.document.body.children[0];
  const cancel = dom.byText(modal, 'Cancel');

  cancel.focus();
  const e = dom.key('Tab');
  assert.strictEqual(e.prevented, true);
  assert.notStrictEqual(dom.state.activeElement, cancel);
  assert.strictEqual(dom.byText(modal, 'Install').disabled, true);
});

test('an invalid address marks the input invalid and refocuses it', () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = makeDeps();
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];
  const input = dom.byTag(modal, 'input');

  input.value = 'not-an-email';
  dom.byText(modal, 'Share').click();
  assert.strictEqual(input.getAttribute('aria-invalid'), 'true');
  assert.strictEqual(dom.state.activeElement, input);
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

// ── Task 2 follow-ups: copy helper ───────────────────────────────────────

function loadWithTimers(dom, written) {
  const timers = [];
  const api = load(dom, {
    navigator: { clipboard: { writeText: async (t) => written.push(t) } },
    setTimeout: (fn) => timers.push(fn),
  });
  return { api, timers };
}

async function openResult(dom, api, body) {
  const { deps } = makeDeps({ postJson: async () => ({ resp: { ok: true }, body }) });
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];
  dom.byTag(modal, 'input').value = 'ann@contoso.com';
  dom.byText(modal, 'Share').click();
  await flush();
  return modal;
}

test('clicking Copy message twice within the reset delay still restores the label', async () => {
  const dom = makeDom();
  const { api, timers } = loadWithTimers(dom, []);
  const modal = await openResult(dom, api, PUBLISHED);
  const btn = dom.byText(modal, 'Copy message');

  btn.click();
  await flush();
  assert.strictEqual(btn.textContent, 'Copied');
  btn.click();
  await flush();
  timers.forEach((fn) => fn());
  assert.strictEqual(btn.textContent, 'Copy message');
});

test('the result view offers exactly Copy message and Send as actions, plus the OneDrive link', async () => {
  const dom = makeDom();
  const { api } = loadWithTimers(dom, []);
  const modal = await openResult(dom, api, PUBLISHED);
  const actions = dom.byClass(modal, 'mp-modal-actions');
  const labels = actions.children.filter((c) => c.textContent).map((c) => c.textContent);
  assert.deepStrictEqual(labels, ['Open in OneDrive', 'Copy message', 'Send']);
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
        return installResult || { resp: { ok: true }, body: { ok: true, skill_id: 'weekly-report' } };
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

  assert.deepStrictEqual(calls.post, [{ url: '/api/skills/share/review', payload: { link: LINK } }]);
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
  assert.deepStrictEqual(calls.post[1].payload, { link: LINK, version: 2, digest: 'sha256:deadbeef' });
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
  const { deps } = reviewDeps(dom, okReview({ title: '<img src=x onerror=alert(1)>', author: '<b>x</b>' }));
  await api.openLinkReview(LINK, deps);
  const modal = dom.document.body.children[0];
  assert.strictEqual(dom.byClass(modal, 'mp-modal-title').textContent, 'Review "<img src=x onerror=alert(1)>"');
  assert(dom.byText(modal, 'Shared by <b>x</b>, version 2'));
});

// ── People lookup ─────────────────────────────────────────────────────────

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const PEOPLE = [
  { name: 'Ann Lee', email: 'Ann.Lee@contoso.com' },
  { name: 'Anna Wu', email: 'anna.wu@contoso.com' },
  { name: '', email: 'ann.x@contoso.com' },
];

function openForm(dom, api, overrides) {
  const queries = [];
  const { deps, calls } = makeDeps(
    Object.assign(
      {
        searchPeople: async (q) => {
          queries.push(q);
          return PEOPLE;
        },
      },
      overrides,
    ),
  );
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];
  return { modal, input: dom.byTag(modal, 'input'), list: dom.byClass(modal, 'ss-suggest'), queries, deps, calls };
}

function typeInto(input, text) {
  input.value = text;
  input._listeners.input({});
}

test('typing two characters shows matches after the debounce, not before', async () => {
  const dom = makeDom();
  const api = load(dom, { setTimeout, clearTimeout });
  const { input, list, queries } = openForm(dom, api);

  typeInto(input, 'a');
  await wait(260);
  assert.strictEqual(queries.length, 0, 'one character does not search');

  typeInto(input, 'an');
  assert.strictEqual(queries.length, 0, 'no request before the debounce');
  await wait(260);
  assert.deepStrictEqual(queries, ['an']);
  assert.strictEqual(list.hidden, false);
  assert.strictEqual(list.children.length, 3);
  assert.strictEqual(input.getAttribute('aria-expanded'), 'true');
  assert.strictEqual(list.children[0].children[0].textContent, 'Ann Lee');
  assert.strictEqual(list.children[2].children.length, 1, 'no name row when the person has no name');
});

test('choosing a match replaces the token and adds a separator', async () => {
  const dom = makeDom();
  const api = load(dom, { setTimeout, clearTimeout });
  const { input, list } = openForm(dom, api);

  typeInto(input, 'bob@contoso.com, an');
  await wait(260);
  list.children[0]._listeners.mousedown({ preventDefault() {} });
  assert.strictEqual(input.value, 'bob@contoso.com, ann.lee@contoso.com, ');
  assert.strictEqual(list.hidden, true);
  assert.strictEqual(dom.state.activeElement, input);
});

test('people already added are not suggested again', async () => {
  const dom = makeDom();
  const api = load(dom, { setTimeout, clearTimeout });
  const { input, list } = openForm(dom, api);

  typeInto(input, 'ann.lee@contoso.com, an');
  await wait(260);
  assert.strictEqual(list.children.length, 2);
  assert(!list.children.some((li) => li.children.some((c) => c.textContent === 'Ann.Lee@contoso.com')));
});

test('arrow keys move through matches, Enter picks one and does not submit', async () => {
  const dom = makeDom();
  const api = load(dom, { setTimeout, clearTimeout });
  const { input, list, calls } = openForm(dom, api);

  typeInto(input, 'an');
  await wait(260);
  const key = (k) => {
    const e = {
      key: k,
      prevented: false,
      preventDefault() {
        this.prevented = true;
      },
    };
    input._listeners.keydown(e);
    return e;
  };
  key('ArrowDown');
  key('ArrowDown');
  assert.strictEqual(list.children[1].getAttribute('aria-selected'), 'true');
  assert.strictEqual(input.getAttribute('aria-activedescendant'), list.children[1].id);
  key('ArrowUp');
  assert.strictEqual(list.children[0].getAttribute('aria-selected'), 'true');
  const enter = key('Enter');
  assert.strictEqual(enter.prevented, true);
  assert.strictEqual(input.value, 'ann.lee@contoso.com, ');
  assert.strictEqual(calls.post.length, 0);
});

test('Enter with no highlighted match submits the form as before', async () => {
  const dom = makeDom();
  const api = load(dom, { setTimeout, clearTimeout });
  const { input, calls } = openForm(dom, api);

  typeInto(input, 'an');
  await wait(260);
  input.value = 'ann@contoso.com';
  input._listeners.keydown({ key: 'Enter', preventDefault() {} });
  await flush();
  assert.strictEqual(calls.post.length, 1);
  assert.strictEqual(calls.post[0].url, '/api/skills/share/publish');
});

test('Escape closes the match list first and only then the modal', async () => {
  const dom = makeDom();
  const api = load(dom, { setTimeout, clearTimeout });
  const { input, list } = openForm(dom, api);

  typeInto(input, 'an');
  await wait(260);
  dom.key('Escape');
  assert.strictEqual(list.hidden, true);
  assert.strictEqual(dom.document.body.children.length, 1, 'modal still open');
  dom.key('Escape');
  assert.strictEqual(dom.document.body.children.length, 0);
});

test('a slow earlier search cannot overwrite the matches for newer text', async () => {
  const dom = makeDom();
  const api = load(dom, { setTimeout, clearTimeout });
  const slow = { resolve: null };
  const { input, list } = openForm(dom, api, {
    searchPeople: (q) =>
      q === 'an'
        ? new Promise((r) => {
            slow.resolve = () => r(PEOPLE);
          })
        : Promise.resolve([{ name: 'Zed Zed', email: 'zed@contoso.com' }]),
  });

  typeInto(input, 'an');
  await wait(260);
  typeInto(input, 'ze');
  await wait(260);
  slow.resolve();
  await flush();
  assert.strictEqual(list.children.length, 1);
  assert.strictEqual(list.children[0].children[1].textContent, 'zed@contoso.com');
});

test('a failing lookup shows no list and does not block typing', async () => {
  const dom = makeDom();
  const api = load(dom, { setTimeout, clearTimeout });
  const { input, list } = openForm(dom, api, {
    searchPeople: async () => {
      throw new Error('offline');
    },
  });
  typeInto(input, 'an');
  await wait(260);
  assert.strictEqual(list.hidden, true);
  assert.strictEqual(input.value, 'an');
});

test('without a searchPeople dependency the field is a plain input', () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = makeDeps();
  api.openShareModal('weekly-report', deps);
  const input = dom.byTag(dom.document.body.children[0], 'input');
  assert.strictEqual(input.getAttribute('role'), null);
  assert.strictEqual(input._listeners.input, undefined);
});

// ── Send the message ─────────────────────────────────────────────────────

async function openResultWith(dom, api, extraDeps, body, channelLabel) {
  const { deps, calls } = makeDeps(
    Object.assign(
      {
        postJson: async (url, payload) => {
          calls.post.push({ url, payload });
          if (url.endsWith('/publish')) return { resp: { ok: true }, body: body || PUBLISHED };
          return {
            resp: { ok: true },
            body: { drafts: [{ _draft: 'email-send', data: { draft_id: 'd1' } }], unmatched: [] },
          };
        },
      },
      extraDeps,
    ),
  );
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];
  if (channelLabel) dom.byText(modal, channelLabel).click();
  dom.byTag(modal, 'input').value = 'ann@contoso.com, out@gmail.com';
  dom.byText(modal, 'Share').click();
  await flush();
  return { modal, calls };
}

test('Send posts the chosen channel, people and message, then hands the drafts over and closes', async () => {
  const dom = makeDom();
  const api = load(dom);
  const shown = [];
  const { modal, calls } = await openResultWith(dom, api, { showDrafts: (d) => shown.push(d) }, null, 'Teams');

  assert(dom.byText(modal, 'Nothing has been sent. Send opens a Teams message draft for you to approve.'));
  dom.byText(modal, 'Send').click();
  await flush();

  const draftCall = calls.post[1];
  assert.strictEqual(draftCall.url, '/api/skills/share/draft');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(draftCall.payload)), {
    channel: 'teams',
    skill_id: 'weekly-report',
    people: ['ann@contoso.com', 'out@gmail.com'],
    message: PUBLISHED.message,
  });
  assert.strictEqual(shown.length, 1);
  assert.strictEqual(shown[0][0]._draft, 'email-send');
  assert.strictEqual(dom.document.body.children.length, 0);
  assert.strictEqual(calls.refresh, 1);
});

test('Send only ever posts to the publish and draft routes', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { modal, calls } = await openResultWith(dom, api, { showDrafts() {} });
  dom.byText(modal, 'Send').click();
  await flush();
  assert(calls.post.every((c) => /^\/api\/skills\/share\/(publish|draft)$/.test(c.url)));
});

test('a draft failure explains in plain words, keeps the modal and re-enables Send', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { modal } = await openResultWith(
    dom,
    api,
    {
      showDrafts() {},
      postJson: async (url) =>
        url.endsWith('/publish')
          ? { resp: { ok: true }, body: PUBLISHED }
          : { resp: { ok: false }, body: { detail: { message: 'Slack is not connected.' } } },
    },
    null,
    'Slack',
  );
  const send = dom.byText(modal, 'Send');
  send.click();
  await flush();
  assert.strictEqual(dom.byClass(modal, 'ss-error').textContent, 'Slack is not connected.');
  assert.strictEqual(send.disabled, false);
  assert.strictEqual(dom.document.body.children.length, 1);
});

test('people without a Slack account are reported after the drafts open', async () => {
  const dom = makeDom();
  const api = load(dom);
  const shown = [];
  const reply = { drafts: [{ _draft: 'slack-dm', data: { draft_id: 's1' } }], unmatched: ['out@gmail.com'] };
  const { modal, calls } = await openResultWith(
    dom,
    api,
    {
      showDrafts: (d) => shown.push(d),
      postJson: async (url) =>
        url.endsWith('/publish') ? { resp: { ok: true }, body: PUBLISHED } : { resp: { ok: true }, body: reply },
    },
    null,
    'Slack',
  );
  dom.byText(modal, 'Send').click();
  await flush();
  assert.strictEqual(shown.length, 1);
  assert.strictEqual(calls.alerts.length, 1);
  assert(calls.alerts[0].msg.includes('out@gmail.com'));
  assert.strictEqual(calls.alerts[0].kind, 'warning');
});

test('people who could not be granted access get a plain-words notice and still get the message', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { modal } = await openResultWith(
    dom,
    api,
    { showDrafts() {} },
    Object.assign({}, PUBLISHED, { ungranted: ['out@gmail.com'] }),
  );
  assert(dom.byText(modal, 'Access granted to ann@contoso.com'));
  assert.strictEqual(dom.byClass(modal, 'ss-notice-title').textContent, 'Access was not granted for out@gmail.com');
  const text = dom.byClass(modal, 'ss-notice-text').textContent;
  assert(text.includes('outside your organization'));
  assert(text.includes('Send the message anyway'));
  assert(text.includes('Open in OneDrive'));
  assert(dom.byText(modal, 'Send'));
  assert.strictEqual(dom.byTag(modal, 'textarea').value, PUBLISHED.message);
});

test('no notice when everyone was granted access', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { modal } = await openResultWith(dom, api, {}, Object.assign({}, PUBLISHED, { ungranted: [] }));
  assert.strictEqual(dom.byClass(modal, 'ss-notice'), null);
});

test('when everyone is ungranted there is no Access granted line', async () => {
  const dom = makeDom();
  const api = load(dom);
  const { modal } = await openResultWith(
    dom,
    api,
    {},
    Object.assign({}, PUBLISHED, { ungranted: ['ann@contoso.com', 'out@gmail.com'] }),
  );
  assert.strictEqual(dom.byClass(modal, 'ss-access'), null);
  assert.strictEqual(
    dom.byClass(modal, 'ss-notice-title').textContent,
    'Access was not granted for ann@contoso.com, out@gmail.com',
  );
});

test('the send-by choice moves with the arrow keys', () => {
  const dom = makeDom();
  const api = load(dom);
  const { deps } = makeDeps();
  api.openShareModal('weekly-report', deps);
  const modal = dom.document.body.children[0];
  const email = dom.byText(modal, 'Email');
  const teams = dom.byText(modal, 'Teams');
  const e = {
    key: 'ArrowRight',
    preventDefault() {
      this.prevented = true;
    },
  };
  email._listeners.keydown(e);
  assert.strictEqual(e.prevented, true);
  assert.strictEqual(teams.getAttribute('aria-checked'), 'true');
  assert.strictEqual(email.getAttribute('aria-checked'), 'false');
  assert.strictEqual(dom.state.activeElement, teams);
});
