// Increment 4a (2026-08-07 milestone — Plugin Marketplace A+B+E): frontend
// consent-flow support for claude-plugins-official catalog entries.
//
// Covers two pre-existing bugs fixed in this increment (see
// docs/pluginArchitecture.md, Increment 2's "Increment 4 must-do" open item):
//   1. `_install`'s error branch did `data.detail || data.error || 'Unknown
//      error'` — when `data.detail` is an OBJECT (the 403 not_installable /
//      coding_hard shape: {error, message, coding_class}), string-concat
//      rendered literally as "[object Object]". `_errorMessage` fixes this.
//   2. The catalog card's action-button decision (Built-in / "Use the Coding
//      Agent" / Installed / Install) — decision #8's coding redirect must
//      block Install entirely for coding_hard (LSP) entries, never just an
//      advisory. `_cardActionState` / `_isCodingSoft` are the pure helpers
//      extracted from _renderBrowse so this logic is testable without a DOM.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'marketplace-pane.js'),
  'utf8',
);

function extractFn(name) {
  const re = new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n  \\}');
  const match = source.match(re);
  assert(match, name + ' not found in marketplace-pane.js');
  return vm.runInNewContext(match[0] + ';' + name + ';', {});
}

const _errorMessage = extractFn('_errorMessage');
const _isCodingSoft = extractFn('_isCodingSoft');
const _cardActionState = extractFn('_cardActionState');
const _findCollisionEntry = extractFn('_findCollisionEntry');
const _tryAcquireInstallLock = extractFn('_tryAcquireInstallLock');

// ── _errorMessage ────────────────────────────────────────────────────────
// The 403 not_installable (coding_hard) shape from routes/marketplace.py's
// _install_claude_plugins_official — detail is an object, not a string.
{
  const data = {
    detail: {
      error: 'not_installable',
      message:
        'rocm-lsp is a coding-oriented (LSP) plugin and can’t run in Gator chat. Use the Coding Agent instead.',
      coding_class: 'coding_hard',
    },
  };
  assert.strictEqual(
    _errorMessage(data),
    'rocm-lsp is a coding-oriented (LSP) plugin and can’t run in Gator chat. Use the Coding Agent instead.',
    'object detail with .message must extract the message, not stringify the whole object',
  );
}

// The 400 orphan_resolution_required shape — object detail with no .message,
// only .error + .orphans.
{
  const data = { detail: { error: 'Orphan files require resolution', orphans: ['old_tools.py'] } };
  assert.strictEqual(
    _errorMessage(data),
    'Orphan files require resolution',
    'object detail without .message falls back to .error',
  );
}

// Plain string detail (the common case — install_skill_md failures, etc.)
{
  assert.strictEqual(_errorMessage({ detail: 'Install failed' }), 'Install failed');
}

// No detail at all, but a top-level error field.
{
  assert.strictEqual(_errorMessage({ error: 'boom' }), 'boom');
}

// Nothing usable at all.
{
  assert.strictEqual(_errorMessage({}), 'Unknown error');
  assert.strictEqual(_errorMessage(null), 'Unknown error');
}

// FIX 3 (Increment 4b, defensive): a hypothetical future nested error shape
// where d.message itself is non-string. Must stringify it rather than
// returning it raw — otherwise the caller's 'Install failed: ' + result
// string concat would coerce it via toString() and reproduce the exact
// "[object Object]" bug this function exists to fix, one level deeper.
{
  const data = { detail: { message: { code: 'weird', nested: true } } };
  assert.strictEqual(
    _errorMessage(data),
    JSON.stringify({ code: 'weird', nested: true }),
    'non-string d.message must be stringified, not returned raw',
  );
}
{
  const data = { detail: { error: ['a', 'b'] } };
  assert.strictEqual(
    _errorMessage(data),
    JSON.stringify(['a', 'b']),
    'non-string d.error must be stringified, not returned raw',
  );
}

// ── _isCodingSoft / _cardActionState (decision #8 coding redirect) ───────
const lspEntry = {
  id: 'clangd-lsp',
  tier: 'Verified',
  source: 'claude-plugins-official',
  coding_class: 'coding_hard',
};
const reviewEntry = {
  id: 'code-review',
  tier: 'Verified',
  source: 'claude-plugins-official',
  coding_class: 'coding_soft',
};
const amdSkillsEntry = {
  id: 'amd-skills',
  tier: 'Verified',
  source: 'claude-plugins-official',
  coding_class: 'none',
};
const communityEntry = {
  id: 'frontend-design',
  tier: 'Community',
  source: 'community',
  coding_class: 'none',
};
const nativeEntry = { id: 'docx', tier: 'Native', source: 'native' };

// coding_hard (LSP) — never installable, regardless of "already installed" state.
assert.strictEqual(
  _cardActionState(lspEntry, false),
  'coding_redirect',
  'LSP plugin must redirect to the Coding Agent',
);
assert.strictEqual(
  _cardActionState(lspEntry, true),
  'coding_redirect',
  'coding_hard takes priority even if somehow marked installed',
);
assert.strictEqual(_isCodingSoft(lspEntry), false, 'coding_hard is not coding_soft');

// coding_soft (repo-acting, e.g. code-review) — advisory shown, but fully installable.
assert.strictEqual(
  _isCodingSoft(reviewEntry),
  true,
  'code-review must trigger the advisory banner',
);
assert.strictEqual(
  _cardActionState(reviewEntry, false),
  'installable',
  'coding_soft must NOT block the Install button (decision #8: advisory only)',
);
assert.strictEqual(
  _cardActionState(reviewEntry, true),
  'installed',
  'coding_soft already-installed still shows Installed',
);

// Verified entry with no coding classification — normal install button, matches
// the milestone's own motivating example (amd-skills is category:"development"
// but must not be redirected).
assert.strictEqual(_isCodingSoft(amdSkillsEntry), false);
assert.strictEqual(_cardActionState(amdSkillsEntry, false), 'installable');

// Non-claude-plugins-official entries are never redirected, regardless of any
// stray coding_class-shaped field.
assert.strictEqual(
  _cardActionState({ ...communityEntry, coding_class: 'coding_hard' }, false),
  'installable',
  'coding_class is only honored for source==claude-plugins-official',
);

// Native always wins.
assert.strictEqual(_cardActionState(nativeEntry, false), 'builtin');

// ── _findCollisionEntry (decision #10 collision detection, FIX 4) ────────
// Extracted from _installVerifiedPlugin so this predicate — previously
// untested — gets coverage via the same DOM-free pattern as the helpers
// above.
{
  const verifiedSkill = { id: 'frontend-design', source: 'claude-plugins-official' };
  const installedList = [
    { id: 'frontend-design', tier: 'Community', source: 'community' },
    { id: 'docx', tier: 'Native', source: 'native' },
  ];
  const hit = _findCollisionEntry(verifiedSkill, installedList);
  assert.ok(hit, 'a colliding Community entry with the same id must be found');
  assert.strictEqual(hit.tier, 'Community');
}
{
  // A Native entry sharing the same bare id (e.g. "github", "slack" are
  // both Native and real claude-plugins-official plugin ids) must NOT be
  // flagged — Native isn't a real install a user could "replace".
  const verifiedSkill = { id: 'github', source: 'claude-plugins-official' };
  const installedList = [{ id: 'github', tier: 'Native', source: 'native' }];
  assert.strictEqual(
    _findCollisionEntry(verifiedSkill, installedList),
    undefined,
    'Native sharing a bare id must not be flagged as a collision',
  );
}
{
  // Re-checking an already-installed Verified plugin against itself (same
  // id, same claude-plugins-official source) must not be a "different
  // source" collision.
  const verifiedSkill = { id: 'amd-skills', source: 'claude-plugins-official' };
  const installedList = [{ id: 'amd-skills', tier: 'Verified', source: 'claude-plugins-official' }];
  assert.strictEqual(
    _findCollisionEntry(verifiedSkill, installedList),
    undefined,
    'same-source (claude-plugins-official) entry must not be flagged as a collision',
  );
}

// ── _tryAcquireInstallLock (FIX 1 pending-install guard) ──────────────────
// _installVerifiedPlugin itself can't be unit-tested here (it calls fetch/
// document, unavailable in this file's DOM-less vm context — see header
// comment), but the guard predicate that prevents a second concurrent flow
// for the same skill id is pulled out as a pure function precisely so it can
// be covered this way.
{
  const pending = new Set();
  assert.strictEqual(
    _tryAcquireInstallLock(pending, 'amd-skills'),
    true,
    'first call acquires the lock',
  );
  assert.strictEqual(
    _tryAcquireInstallLock(pending, 'amd-skills'),
    false,
    'second call while pending is a no-op',
  );
  pending.delete('amd-skills');
  assert.strictEqual(
    _tryAcquireInstallLock(pending, 'amd-skills'),
    true,
    'lock is re-acquirable once released',
  );
  // A different skill id is unaffected by another id's pending lock.
  const pending2 = new Set(['other-skill']);
  assert.strictEqual(
    _tryAcquireInstallLock(pending2, 'amd-skills'),
    true,
    'a different skill id is not blocked',
  );
}

console.log('marketplace_verified_consent: all assertions passed');
