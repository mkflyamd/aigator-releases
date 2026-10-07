// Marketplace skill controls: CSRF + approval helpers, install wiring, Disable/Enable.
// Same harness as marketplace_verified_consent.test.js: functions are pulled out of
// marketplace-pane.js by regex and run in vm. There is no DOM here, so the wiring tests
// check the function source and the pure helpers are run for real.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'marketplace-pane.js'),
  'utf8',
);

function fnSource(name) {
  const re = new RegExp('(?:async\\s+)?function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n  \\}');
  const match = source.match(re);
  assert(match, name + ' not found in marketplace-pane.js');
  return match[0];
}

function extractFn(name, ctx) {
  const context = vm.createContext(ctx || {});
  return vm.runInContext(fnSource(name) + ';' + name + ';', context);
}

// Objects built inside a vm context have another realm's prototypes; compare as JSON.
function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

// ── _permissionLines ─────────────────────────────────────────────────────
{
  const _permissionLines = extractFn('_permissionLines');
  assert.deepStrictEqual(
    plain(_permissionLines({ lines: ['Reads these folders: none declared', '', '  ', 7, null, 'Network access: none declared'] })),
    ['Reads these folders: none declared', 'Network access: none declared'],
  );
  assert.deepStrictEqual(plain(_permissionLines(null)), []);
  assert.deepStrictEqual(plain(_permissionLines({})), []);
  assert.deepStrictEqual(plain(_permissionLines({ lines: 'not a list' })), []);
}

// ── _consentPayload ──────────────────────────────────────────────────────
{
  const _consentPayload = extractFn('_consentPayload');
  assert.deepStrictEqual(
    plain(_consentPayload({ skill_id: 'a', tier: 'Community' }, { summary: { digest: 'abc' }, resolved_ref: 'deadbeef' })),
    { skill_id: 'a', tier: 'Community', consent: true, digest: 'abc', pinned_ref: 'deadbeef' },
  );
  // No resolved_ref from the server: no pinned_ref is sent.
  assert.deepStrictEqual(
    plain(_consentPayload({ skill_id: 'a' }, { summary: { digest: 'abc' }, resolved_ref: '' })),
    { skill_id: 'a', consent: true, digest: 'abc' },
  );
  // No summary at all: an empty digest, which the server refuses with a 400.
  assert.deepStrictEqual(plain(_consentPayload({ skill_id: 'a' }, {})), { skill_id: 'a', consent: true, digest: '' });
  // The original payload is not modified.
  const original = { skill_id: 'a' };
  _consentPayload(original, { summary: { digest: 'x' } });
  assert.deepStrictEqual(plain(original), { skill_id: 'a' });
}

// ── _toggleState ─────────────────────────────────────────────────────────
{
  const _toggleState = extractFn('_toggleState');
  assert.deepStrictEqual(plain(_toggleState({ id: 's' })), { action: 'disable', label: 'Disable' });
  assert.deepStrictEqual(plain(_toggleState({ id: 's', disabled: true })), { action: 'enable', label: 'Enable' });
  assert.deepStrictEqual(plain(_toggleState(null)), { action: 'disable', label: 'Disable' });
}

// ── _postJson: CSRF header and one retry ─────────────────────────────────
function fakeResponse(status, body) {
  return { status, ok: status >= 200 && status < 300, json: async () => body };
}

async function postJsonCase(initialToken, script) {
  const calls = [];
  const win = { __CSRF_TOKEN__: initialToken };
  const fetchFake = async (url, opts) => {
    calls.push({ url, opts });
    return script.shift();
  };
  const _postJson = extractFn('_postJson', { fetch: fetchFake, window: win, JSON });
  const result = await _postJson('/api/marketplace/install', { skill_id: 'a' });
  return { calls, win, result };
}

(async () => {
  // The token is sent as a header.
  {
    const { calls, result } = await postJsonCase('tok-1', [fakeResponse(200, { ok: true })]);
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].opts.headers['X-CSRF-Token'], 'tok-1');
    assert.strictEqual(calls[0].opts.method, 'POST');
    assert.strictEqual(calls[0].opts.body, JSON.stringify({ skill_id: 'a' }));
    assert.strictEqual(result.resp.ok, true);
    assert.deepStrictEqual(plain(result.body), { ok: true });
  }

  // No token yet: an empty header, never the string "undefined".
  {
    const { calls } = await postJsonCase(undefined, [fakeResponse(200, { ok: true })]);
    assert.strictEqual(calls[0].opts.headers['X-CSRF-Token'], '');
  }

  // A 403 with a stale token: fetch a fresh token, store it, retry once.
  {
    const { calls, win, result } = await postJsonCase('old', [
      fakeResponse(403, { detail: 'CSRF token missing or invalid' }),
      fakeResponse(200, { csrf_token: 'new' }),
      fakeResponse(200, { ok: true }),
    ]);
    assert.deepStrictEqual(calls.map((c) => c.url), [
      '/api/marketplace/install',
      '/api/csrf',
      '/api/marketplace/install',
    ]);
    assert.strictEqual(calls[2].opts.headers['X-CSRF-Token'], 'new');
    assert.strictEqual(win.__CSRF_TOKEN__, 'new');
    assert.deepStrictEqual(plain(result.body), { ok: true });
  }

  // A 403 that is not about the token (same token comes back): no second attempt.
  {
    const { calls, result } = await postJsonCase('same', [
      fakeResponse(403, { detail: { error: 'not_installable' } }),
      fakeResponse(200, { csrf_token: 'same' }),
    ]);
    assert.strictEqual(calls.filter((c) => c.url === '/api/marketplace/install').length, 1);
    assert.strictEqual(result.resp.status, 403);
  }

  // An answer that is not JSON gives body null instead of throwing.
  {
    const res = { status: 502, ok: false, json: async () => { throw new Error('not json'); } };
    const { result } = await postJsonCase('t', [res]);
    assert.strictEqual(result.body, null);
    assert.strictEqual(result.resp.status, 502);
  }

  // ── _postWithApproval ──────────────────────────────────────────────────
  function approvalHarness(postScript, approve) {
    const posts = [];
    const confirms = [];
    const ctx = {
      _postJson: async (url, payload) => {
        posts.push({ url, payload: plain(payload) });
        return postScript.shift();
      },
      _confirmPermissions: async (title, summary, label) => {
        confirms.push({ title, summary: plain(summary), label });
        return approve;
      },
      _consentPayload: extractFn('_consentPayload'),
    };
    return { posts, confirms, run: extractFn('_postWithApproval', ctx) };
  }

  // Not a consent answer: returned as is, no card.
  {
    const h = approvalHarness([{ resp: { ok: false, status: 400 }, body: { detail: 'bad' } }], true);
    const out = await h.run('/api/marketplace/install', { skill_id: 'a' }, 'T', 'Install');
    assert.strictEqual(out.resp.status, 400);
    assert.strictEqual(h.confirms.length, 0);
    assert.strictEqual(h.posts.length, 1);
  }

  // Approved: the card gets the summary, the second call carries consent and the digest.
  {
    const consent = {
      ok: false,
      consent_required: true,
      resolved_ref: '',
      summary: { lines: ['Network access: none declared'], digest: 'd1' },
    };
    const h = approvalHarness(
      [
        { resp: { ok: true, status: 200 }, body: consent },
        { resp: { ok: true, status: 200 }, body: { ok: true, skill_id: 'a' } },
      ],
      true,
    );
    const out = await h.run('/api/marketplace/install', { skill_id: 'a', tier: 'Community' }, 'Install a?', 'Install');
    assert.deepStrictEqual(h.confirms.map((c) => [c.title, c.label]), [['Install a?', 'Install']]);
    assert.deepStrictEqual(h.confirms[0].summary, consent.summary);
    assert.strictEqual(h.posts.length, 2);
    assert.deepStrictEqual(h.posts[1].payload, { skill_id: 'a', tier: 'Community', consent: true, digest: 'd1' });
    assert.strictEqual(out.body.ok, true);
  }

  // Declined: one call only, nothing is sent with consent.
  {
    const h = approvalHarness(
      [{ resp: { ok: true, status: 200 }, body: { ok: false, consent_required: true, summary: { lines: [], digest: 'd' } } }],
      false,
    );
    const out = await h.run('/api/marketplace/install', { skill_id: 'a' }, 'T', 'Install');
    assert.deepStrictEqual(plain(out), { cancelled: true });
    assert.strictEqual(h.posts.length, 1);
  }

  // The package changed between the card and the install: the 409 is handed back to the caller.
  {
    const h = approvalHarness(
      [
        { resp: { ok: true, status: 200 }, body: { consent_required: true, summary: { lines: [], digest: 'd' } } },
        { resp: { ok: false, status: 409 }, body: { detail: { error: 'content_changed', message: 'changed' } } },
      ],
      true,
    );
    const out = await h.run('/api/marketplace/install-local', { kind: 'zip' }, 'T', 'Install');
    assert.strictEqual(out.resp.status, 409);
    assert.strictEqual(out.body.detail.error, 'content_changed');
  }

  // ── _handleInstallOutcome: a skill installed but its tool list could not be read ──
  {
    const alerts = [];
    const ctx = { _showAlert: (msg, kind) => alerts.push([msg, kind]), refresh: () => {}, window: {} };
    const outcome = extractFn('_handleInstallOutcome', ctx);
    outcome(true, { ok: true, tools_error: 'sandbox unavailable' }, { id: 's', name: 'S', tier: 'Community' });
    assert.deepStrictEqual(plain(alerts), [
      ['Installed, but the skill\u2019s tools could not be loaded: sandbox unavailable', 'warning'],
    ]);
    alerts.length = 0;
    outcome(true, { ok: true }, { id: 's', name: 'S', tier: 'Community' });
    assert.deepStrictEqual(plain(alerts.map((a) => a[1])), ['success']);
  }

  // ── Wiring: no install call bypasses the helpers ───────────────────────
  assert(!/fetch\('\/api\/marketplace\/install(?:-local)?'/.test(source), 'an install call still uses raw fetch');
  for (const name of ['_pickLocalSkill', '_importInstall', '_installUrlPlugin']) {
    assert(fnSource(name).includes('_postWithApproval('), name + ' must go through _postWithApproval');
  }
  const install = fnSource('_install');
  assert(install.includes('_postJson(') && install.includes('_consentPayload(') && install.includes('body.summary'));
  const verified = fnSource('_installVerifiedPlugin');
  assert(verified.includes('_postJson(') && verified.includes('_consentPayload('));
  assert(fnSource('_showVerifiedConsentModal').includes('_appendPermissionList('));
  assert(fnSource('_showInstallModal').includes('_appendPermissionList('));
  assert(fnSource('_importInstall').includes('body.tools_error'), 'URL import must surface tools_error');
  const click = fnSource('_handleContentClick');
  assert(click.includes("'disable'") && click.includes("'enable'") && click.includes('_setSkillDisabled('));
  assert(fnSource('_renderInstalled').split('_decorateInstalledRow(').length - 1 === 2, 'bundle rows and standalone rows both get the toggle');
  const toggle = fnSource('_setSkillDisabled');
  assert(toggle.includes('_postJson(') && toggle.includes('refresh()'));

  console.log('marketplace_controls.test.js: ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
