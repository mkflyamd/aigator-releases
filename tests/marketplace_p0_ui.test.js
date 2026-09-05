// P0 UI regression tests — pure-function helpers added in P0 (archive-root fix,
// discoverability improvements).
//
// Follows the same DOM-free vm-extract pattern as
// tests/marketplace_verified_consent.test.js.  Only pure functions (no document,
// fetch, window, etc.) can be tested here.

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

const _pluginMcpState = extractFn('_pluginMcpState');
const _cardActionState = extractFn('_cardActionState');
const _isCodingSoft = extractFn('_isCodingSoft');
const _deriveBundledSkillLabel = extractFn('_deriveBundledSkillLabel');

// ── _pluginMcpState ───────────────────────────────────────────────────────
// Maps the mcp_status object (from the enriched /api/marketplace/installed
// response) to a semantic state string used to decide the status label in
// the Installed tab.

{
  // No MCP at all — null input
  assert.strictEqual(_pluginMcpState(null), 'none', 'null mcp_status → none');
  assert.strictEqual(_pluginMcpState(undefined), 'none', 'undefined mcp_status → none');
  assert.strictEqual(
    _pluginMcpState({ total: 0, enabled: 0, pending: 0, failed: 0, quarantined: 0 }),
    'none',
    'total=0 → none',
  );
}

{
  // Healthy — all connections enabled, none pending/failed/quarantined
  assert.strictEqual(
    _pluginMcpState({ total: 1, enabled: 1, pending: 0, failed: 0, quarantined: 0 }),
    'healthy',
    '1/1 enabled → healthy',
  );
  assert.strictEqual(
    _pluginMcpState({ total: 3, enabled: 3, pending: 0, failed: 0, quarantined: 0 }),
    'healthy',
    '3/3 enabled → healthy',
  );
}

{
  // Setup required — all pending (needs secrets)
  assert.strictEqual(
    _pluginMcpState({ total: 1, enabled: 0, pending: 1, failed: 0, quarantined: 0 }),
    'setup',
    'all pending → setup',
  );
  assert.strictEqual(
    _pluginMcpState({ total: 2, enabled: 0, pending: 2, failed: 0, quarantined: 0 }),
    'setup',
    '2/2 pending → setup',
  );
  // Slack-like case: installed successfully (consented=true) but SLACK_BOT_TOKEN etc. still needed
  assert.strictEqual(
    _pluginMcpState({ total: 1, enabled: 0, pending: 1, failed: 0, quarantined: 0 }),
    'setup',
    'Slack-like: consented=true but pending → setup (not healthy)',
  );
}

{
  // Failed — all connections failed to connect
  assert.strictEqual(
    _pluginMcpState({ total: 1, enabled: 0, pending: 0, failed: 1, quarantined: 0 }),
    'failed',
    'all failed → failed',
  );
}

{
  // Quarantined — enabled but tools quarantined (incompatibility)
  assert.strictEqual(
    _pluginMcpState({ total: 1, enabled: 1, pending: 0, failed: 0, quarantined: 1 }),
    'quarantined',
    'enabled but quarantined tools → quarantined',
  );
}

{
  // Mixed — some healthy, some pending or failed
  assert.strictEqual(
    _pluginMcpState({ total: 2, enabled: 1, pending: 1, failed: 0, quarantined: 0 }),
    'mixed',
    '1 enabled + 1 pending → mixed',
  );
  assert.strictEqual(
    _pluginMcpState({ total: 2, enabled: 1, pending: 0, failed: 1, quarantined: 0 }),
    'mixed',
    '1 enabled + 1 failed → mixed',
  );
  assert.strictEqual(
    _pluginMcpState({ total: 2, enabled: 2, pending: 0, failed: 0, quarantined: 1 }),
    'quarantined',
    'all enabled but quarantined tools → quarantined (not mixed)',
  );
}

// ── _cardActionState — Plugin Bundle entries ──────────────────────────────
// Verified plugin bundles follow the same state machine as other entries but
// the button text differs (set in _renderCatalogCard, not here).  These
// tests assert the state VALUE — button text is tested by the render function.

{
  // Coding hard (LSP) → coding_redirect regardless of isInstalled
  const lspSkill = {
    tier: 'Verified',
    source: 'claude-plugins-official',
    coding_class: 'coding_hard',
  };
  assert.strictEqual(
    _cardActionState(lspSkill, false),
    'coding_redirect',
    'LSP plugin → coding_redirect',
  );
  assert.strictEqual(
    _cardActionState(lspSkill, true),
    'coding_redirect',
    'LSP plugin installed → still coding_redirect',
  );
}

{
  // Coding soft (repo-acting) → installable (advisory shown separately)
  const softSkill = {
    tier: 'Verified',
    source: 'claude-plugins-official',
    coding_class: 'coding_soft',
  };
  assert.strictEqual(
    _cardActionState(softSkill, false),
    'installable',
    'coding_soft not installed → installable',
  );
  assert.strictEqual(
    _cardActionState(softSkill, true),
    'installed',
    'coding_soft installed → installed',
  );
}

{
  // Normal plugin bundle → installable or installed
  const bundle = { tier: 'Verified', source: 'claude-plugins-official', coding_class: 'none' };
  assert.strictEqual(_cardActionState(bundle, false), 'installable', 'bundle not installed → installable');
  assert.strictEqual(_cardActionState(bundle, true), 'installed', 'bundle installed → installed');
}

// ── _isCodingSoft — Plugin Bundle entries ─────────────────────────────────

{
  assert.strictEqual(
    _isCodingSoft({ source: 'claude-plugins-official', coding_class: 'coding_soft' }),
    true,
    'claude-plugins-official + coding_soft → true',
  );
  assert.strictEqual(
    _isCodingSoft({ source: 'claude-plugins-official', coding_class: 'coding_hard' }),
    false,
    'coding_hard → false (even though source matches)',
  );
  assert.strictEqual(
    _isCodingSoft({ source: 'claude-plugins-official', coding_class: 'none' }),
    false,
    'coding_none → false',
  );
  assert.strictEqual(
    _isCodingSoft({ source: 'anthropic', coding_class: 'coding_soft' }),
    false,
    'non-official source → false even if coding_soft',
  );
}

// ── _deriveBundledSkillLabel ──────────────────────────────────────────────
// Strips the plugin_id namespace prefix and title-cases the remainder.

{
  assert.strictEqual(
    _deriveBundledSkillLabel('amd-skills__local-ai-use', 'amd-skills'),
    'Local Ai Use',
    'strips prefix + title-cases',
  );
  assert.strictEqual(
    _deriveBundledSkillLabel('slack__send-message', 'slack'),
    'Send Message',
    'slack bundle skill',
  );
  // When skill_id equals plugin_id (single top-level SKILL.md — bare id)
  assert.strictEqual(
    _deriveBundledSkillLabel('slack', 'slack'),
    'Slack',
    'bare plugin id → title-cases the id itself',
  );
  // Skill id from a different plugin (no matching prefix) — title-cases the whole id
  assert.strictEqual(
    _deriveBundledSkillLabel('unrelated-skill', 'amd-skills'),
    'Unrelated Skill',
    'no prefix match → title-cases whole id',
  );
}

console.log('marketplace_p0_ui: all assertions passed');
