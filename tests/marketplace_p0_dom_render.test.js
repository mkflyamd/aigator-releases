'use strict';

// P0 UI rendering tests — verifies that Browse cards, Installed sections,
// and the consent modal render the correct structure, class names, text,
// ARIA attributes, and focus behavior.
//
// jsdom is not available in this repo (see marketplace_verified_consent.test.js
// limitation comment).  Instead we use a lightweight DOM shim that records
// element creation, class names, textContent, setAttribute calls, and focus
// tracking — enough to verify the structural and a11y output of rendering
// functions without needing a real browser.
//
// The shim is provided as the `vm` sandbox context.  Each test extracts one
// rendering function from marketplace-pane.js source via a targeted regex and
// runs it inside the shim context.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'marketplace-pane.js'),
  'utf8',
);

// ── Minimal DOM shim ──────────────────────────────────────────────────────
// A minimal tracking DOM that records what rendering functions produce.
// Tracks: tag, className, textContent, dataset, children, _attrs, disabled,
//         title, _focused (focus() calls), _listeners.

function makeDom() {
  let _focusTarget = null; // last element focus() was called on

  class FakeEl {
    constructor(tag) {
      this.tag = tag;
      this.className = '';
      this._textContent = '';
      this.dataset = {};
      this.children = [];
      this._attrs = {};
      this.disabled = false;
      this.title = '';
      this.id = '';
      this.style = { cssText: '' };
      this._listeners = {};
    }
    appendChild(child) {
      this.children.push(child);
      return child;
    }
    setAttribute(k, v) {
      this._attrs[k] = v;
    }
    getAttribute(k) {
      return this._attrs[k] || null;
    }
    addEventListener(type, fn) {
      this._listeners[type] = fn;
    }
    removeEventListener() {}
    focus() {
      _focusTarget = this;
    }
    set textContent(v) {
      this._textContent = String(v == null ? '' : v);
      this.children = []; // real DOM clears children on textContent set
    }
    get textContent() {
      return this._textContent || '';
    }
    remove() {
      this._removed = true;
    }
    querySelector() {
      return null;
    }
    querySelectorAll() {
      return [];
    }
    get isConnected() {
      return true;
    }
    createElementNS(ns, tag) {
      return new FakeEl(tag);
    }
  }

  // Document-level Escape listener tracking
  let _docKeydownCapture = null;
  let _docKeydownBubble = null;

  function createElement(tag) {
    return new FakeEl(tag);
  }
  function createTextNode(text) {
    const el = new FakeEl('#text');
    el.textContent = text;
    return el;
  }

  const bodyEl = new FakeEl('body');
  const appended = [];
  bodyEl.appendChild = (el) => {
    appended.push(el);
    return el;
  };

  const document = {
    createElement,
    createTextNode,
    createElementNS(ns, tag) {
      return new FakeEl(tag);
    },
    body: bodyEl,
    activeElement: null, // will be set per-test as needed
    addEventListener(type, fn, capture) {
      if (type === 'keydown') {
        if (capture) _docKeydownCapture = fn;
        else _docKeydownBubble = fn;
      }
    },
    removeEventListener(type, fn, capture) {
      if (type === 'keydown') {
        if (capture && _docKeydownCapture === fn) _docKeydownCapture = null;
        else if (!capture && _docKeydownBubble === fn) _docKeydownBubble = null;
      }
    },
  };

  // Dispatch a synthetic keydown event.
  function dispatchEscape() {
    const e = { key: 'Escape', _stopped: false, _prevented: false };
    e.stopPropagation = () => {
      e._stopped = true;
    };
    e.preventDefault = () => {
      e._prevented = true;
    };
    if (_docKeydownCapture) _docKeydownCapture(e);
    return e;
  }

  function allText(el) {
    if (!el) return [];
    const texts = [];
    if (el.tag === '#text' || !el.children || el.children.length === 0) {
      if (el.textContent) texts.push(el.textContent);
    }
    for (const c of el.children || []) texts.push(...allText(c));
    return texts;
  }

  function allClasses(el) {
    if (!el) return [];
    const classes = [];
    if (el.className) classes.push(...el.className.split(' ').filter(Boolean));
    for (const c of el.children || []) classes.push(...allClasses(c));
    return classes;
  }

  function allAttrs(el) {
    if (!el) return [];
    const attrs = [el._attrs];
    for (const c of el.children || []) attrs.push(...allAttrs(c));
    return attrs;
  }

  function findByClass(el, cls) {
    if (!el) return null;
    if ((el.className || '').split(' ').includes(cls)) return el;
    for (const c of el.children || []) {
      const found = findByClass(c, cls);
      if (found) return found;
    }
    return null;
  }

  function findByAttr(el, attr, val) {
    if (!el) return null;
    if (el._attrs[attr] === val) return el;
    for (const c of el.children || []) {
      const found = findByAttr(c, attr, val);
      if (found) return found;
    }
    return null;
  }

  return {
    document,
    allText,
    allClasses,
    allAttrs,
    findByClass,
    findByAttr,
    appended,
    getLastFocused() {
      return _focusTarget;
    },
    dispatchEscape,
    FakeEl,
  };
}

// ── Helper: evaluate a named function inside a fresh shim context ──────────

function makeModalCtx(dom) {
  const tierBadgeMatch = source.match(/const TIER_BADGE\s*=\s*(\{[\s\S]*?\});/);
  const tierTooltipsMatch = source.match(/const _TIER_TOOLTIPS\s*=\s*(\{[\s\S]*?\});/);

  const ctx = vm.createContext({
    document: dom.document,
    console,
    Set,
    Map,
    Array,
    Object,
    String,
    Number,
    Boolean,
    JSON,
    Math,
    Date,
  });

  if (tierBadgeMatch) vm.runInContext('const TIER_BADGE=' + tierBadgeMatch[1] + ';', ctx);
  if (tierTooltipsMatch) vm.runInContext('const _TIER_TOOLTIPS=' + tierTooltipsMatch[1] + ';', ctx);

  const helperNames = [
    '_makeBadge',
    '_buildCapBadges',
    '_buildMcpSvg',
    '_isCodingSoft',
    '_cardActionState',
    '_pluginMcpState',
    '_findCollisionEntry',
    '_tryAcquireInstallLock',
    '_deriveBundledSkillLabel',
    '_errorMessage',
  ];
  for (const h of helperNames) {
    const re = new RegExp('function ' + h + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n  \\}');
    const m = source.match(re);
    if (m)
      try {
        vm.runInContext(m[0] + ';', ctx);
      } catch (_) {}
  }
  return ctx;
}

function extractWithDom(fnName) {
  const fnRe = new RegExp('function ' + fnName + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n  \\}');
  const match = source.match(fnRe);
  assert(match, fnName + ' not found in marketplace-pane.js');
  const dom = makeDom();
  const ctx = makeModalCtx(dom);
  vm.runInContext(match[0] + ';', ctx);
  return { fn: ctx[fnName], dom };
}

function extractModalFn() {
  const fnRe = /function _showVerifiedConsentModal\([^)]*\)\s*\{[\s\S]*?\n  \}/;
  const match = source.match(fnRe);
  assert(match, '_showVerifiedConsentModal not found');
  const dom = makeDom();
  const ctx = makeModalCtx(dom);
  vm.runInContext(match[0] + ';', ctx);
  return { fn: ctx._showVerifiedConsentModal, dom };
}

// ── Test 1: Plugin Bundle catalog card — label and button text ───────────
{
  const { fn, dom } = extractWithDom('_renderCatalogCard');

  const skill = {
    id: 'slack',
    name: 'Slack',
    description: 'Send messages',
    tier: 'Verified',
    source: 'claude-plugins-official',
    coding_class: 'none',
    has_tools: false,
    has_mcp: true,
    install_count: 0,
  };
  const container = dom.document.createElement('div');
  fn(skill, new Set(), new Set(), container);

  const classes = dom.allClasses(container);
  assert(
    classes.includes('mp-plugin-bundle-label'),
    'Plugin Bundle card must include mp-plugin-bundle-label',
  );

  const texts = dom.allText(container);
  assert(
    texts.some((t) => t === 'Plugin Bundle'),
    '"Plugin Bundle" label text must appear',
  );
  assert(
    texts.some((t) => t === 'Review & Install Plugin'),
    '"Review & Install Plugin" button text',
  );
  assert(
    texts.some((t) => t === 'Slack'),
    'Plugin name must appear',
  );

  console.log('  [PASS] _renderCatalogCard: Plugin Bundle label and button text');
}

// ── Test 2: Installed Plugin Bundle shows 'Plugin Installed' ─────────────
{
  const { fn, dom } = extractWithDom('_renderCatalogCard');

  const skill = {
    id: 'datadog',
    name: 'Datadog',
    tier: 'Verified',
    source: 'claude-plugins-official',
    coding_class: 'none',
    has_tools: false,
  };
  const container = dom.document.createElement('div');
  fn(skill, new Set(['datadog']), new Set(), container);

  const texts = dom.allText(container);
  assert(
    texts.some((t) => t === 'Plugin Installed'),
    '"Plugin Installed" button text',
  );
  const btn = dom.findByClass(container, 'ap-card-btn');
  assert(btn && btn.disabled === true, 'Installed plugin button must be disabled');

  console.log('  [PASS] _renderCatalogCard: installed Plugin Bundle shows "Plugin Installed"');
}

// ── Test 3: LSP card shows 'Use the Coding Agent' ────────────────────────
{
  const { fn, dom } = extractWithDom('_renderCatalogCard');

  const lspSkill = {
    id: 'clangd-lsp',
    name: 'Clangd LSP',
    tier: 'Verified',
    source: 'claude-plugins-official',
    coding_class: 'coding_hard',
    has_tools: false,
  };
  const container = dom.document.createElement('div');
  fn(lspSkill, new Set(), new Set(), container);

  const texts = dom.allText(container);
  assert(
    texts.some((t) => t === 'Use the Coding Agent'),
    '"Use the Coding Agent" button text',
  );
  const btn = dom.findByClass(container, 'ap-card-btn');
  assert(btn && btn.disabled === true, 'LSP button must be disabled');

  console.log('  [PASS] _renderCatalogCard: LSP card shows "Use the Coding Agent"');
}

// ── Test 4: coding_soft card shows advisory + install button ──────────────
{
  const { fn, dom } = extractWithDom('_renderCatalogCard');

  const softSkill = {
    id: 'code-review',
    name: 'Code Review',
    tier: 'Verified',
    source: 'claude-plugins-official',
    coding_class: 'coding_soft',
    has_tools: false,
  };
  const container = dom.document.createElement('div');
  fn(softSkill, new Set(), new Set(), container);

  const texts = dom.allText(container);
  assert(
    texts.some((t) => t && t.includes('Coding Agent')),
    'coding_soft shows Coding Agent advisory',
  );
  assert(
    texts.some((t) => t === 'Review & Install Plugin'),
    'coding_soft still shows install button',
  );

  console.log('  [PASS] _renderCatalogCard: coding_soft shows advisory + install button');
}

// ── Test 5: _pluginMcpState — all states via DOM context ─────────────────
{
  const { fn: mcpStateFn } = extractWithDom('_pluginMcpState');

  assert.strictEqual(mcpStateFn(null), 'none', 'null → none');
  assert.strictEqual(
    mcpStateFn({
      total: 1,
      enabled: 1,
      pending: 0,
      failed: 0,
      disabled: 0,
      missing: 0,
      quarantined: 0,
    }),
    'healthy',
    '1/1 enabled → healthy',
  );
  assert.strictEqual(
    mcpStateFn({
      total: 1,
      enabled: 0,
      pending: 1,
      failed: 0,
      disabled: 0,
      missing: 0,
      quarantined: 0,
    }),
    'setup',
    'all pending → setup',
  );
  assert.strictEqual(
    mcpStateFn({
      total: 1,
      enabled: 0,
      pending: 0,
      failed: 1,
      disabled: 0,
      missing: 0,
      quarantined: 0,
    }),
    'failed',
    'all failed → failed',
  );
  assert.strictEqual(
    mcpStateFn({
      total: 1,
      enabled: 0,
      pending: 0,
      failed: 0,
      disabled: 1,
      missing: 0,
      quarantined: 0,
    }),
    'disabled',
    'all disabled → disabled',
  );
  assert.strictEqual(
    mcpStateFn({
      total: 1,
      enabled: 0,
      pending: 0,
      failed: 0,
      disabled: 0,
      missing: 1,
      quarantined: 0,
    }),
    'missing',
    'all missing → missing',
  );
  assert.strictEqual(
    mcpStateFn({
      total: 1,
      enabled: 1,
      pending: 0,
      failed: 0,
      disabled: 0,
      missing: 0,
      quarantined: 1,
    }),
    'quarantined',
    'all enabled + quarantined tools → quarantined',
  );
  assert.strictEqual(
    mcpStateFn({
      total: 2,
      enabled: 1,
      pending: 1,
      failed: 0,
      disabled: 0,
      missing: 0,
      quarantined: 0,
    }),
    'mixed',
    '1-healthy+1-pending → mixed',
  );

  console.log('  [PASS] _pluginMcpState: all states including disabled and missing');
}

// ── Test 6: Consent modal — ARIA, focus, generic MCP notice, compat risk ──
// Verifies:
//   - role="dialog", aria-modal="true", aria-labelledby on the modal element
//   - title element has a matching id
//   - cancelBtn.focus() is called (focus moved into dialog)
//   - generic MCP compat notice always present when has_mcp=true
//   - mp-modal-compat-risk present when has_compat_risk=true
//   - "Install Plugin" button text
{
  const { fn, dom } = extractModalFn();

  // Give the modal a prevFocus target to restore
  const fakeInstallBtn = dom.document.createElement('button');
  dom.document.activeElement = fakeInstallBtn;

  const skill = {
    id: 'slack',
    name: 'Slack',
    tier: 'Verified',
    source: 'claude-plugins-official',
    coding_class: 'none',
  };
  const previewBody = {
    capabilities: {
      skill_count: 1,
      command_count: 2,
      has_mcp: true,
      has_local_code: false,
      has_compat_risk: true,
      mcp_servers: [{ name: 'slack', needs_secrets: ['SLACK_BOT_TOKEN', 'SLACK_TEAM_ID'] }],
    },
  };

  fn(
    skill,
    previewBody,
    null,
    () => {},
    () => {},
  );

  assert(dom.appended.length > 0, 'Overlay must be appended to document.body');
  const overlay = dom.appended[dom.appended.length - 1];
  const classes = dom.allClasses(overlay);
  const texts = dom.allText(overlay);

  // ARIA: role="dialog"
  const dialogEl = dom.findByAttr(overlay, 'role', 'dialog');
  assert(dialogEl !== null, 'Modal must have role="dialog"');

  // ARIA: aria-modal="true"
  assert(dialogEl._attrs['aria-modal'] === 'true', 'Modal must have aria-modal="true"');

  // ARIA: aria-labelledby
  const labelledBy = dialogEl._attrs['aria-labelledby'];
  assert(labelledBy, 'Modal must have aria-labelledby');

  // Title element has the matching id
  const titleEl = dom.findByClass(overlay, 'mp-modal-title');
  assert(titleEl, 'mp-modal-title must be present');
  assert.strictEqual(titleEl.id, labelledBy, 'mp-modal-title id must match aria-labelledby value');
  assert(
    titleEl.textContent.includes('Review & Install Plugin'),
    'Title must contain "Review & Install Plugin"',
  );

  // Focus moved into dialog (cancelBtn.focus() called)
  const focused = dom.getLastFocused();
  assert(focused !== null, 'focus() must be called on an element inside the modal');
  assert(focused.textContent === 'Cancel', 'Focus must be moved to the Cancel button on open');

  // Generic MCP compatibility notice — ALWAYS present when has_mcp=true
  assert(
    classes.includes('mp-modal-mcp-compat-notice'),
    'Generic MCP compat notice (.mp-modal-mcp-compat-notice) must be present when has_mcp=true',
  );
  const noticeText = (() => {
    const el = dom.findByClass(overlay, 'mp-modal-mcp-compat-notice');
    return el ? el.textContent : '';
  })();
  assert(
    noticeText.includes('compatibility-checked') || noticeText.includes('Incompatible'),
    'Generic notice text must mention compatibility check',
  );

  // Stronger compat risk warning (has_compat_risk=true)
  assert(
    classes.includes('mp-modal-compat-risk'),
    'mp-modal-compat-risk must be present when has_compat_risk=true',
  );

  // Skills + commands summary
  assert(
    texts.some((t) => t && t.includes('1 skill') && t.includes('2 commands')),
    'Modal must show skill and command count',
  );

  // MCP server + secrets listed
  assert(
    texts.some((t) => t && t.includes('slack') && t.includes('SLACK_BOT_TOKEN')),
    'Modal must list MCP server name and required secrets',
  );

  // Install button
  assert(
    texts.some((t) => t === 'Install Plugin'),
    '"Install Plugin" button text',
  );

  console.log('  [PASS] _showVerifiedConsentModal: ARIA, focus, generic MCP notice, compat-risk');
}

// ── Test 7: Generic MCP notice present even when has_compat_risk=false ────
{
  const { fn, dom } = extractModalFn();

  const skill = {
    id: 'airtable',
    name: 'Airtable',
    tier: 'Verified',
    source: 'claude-plugins-official',
    coding_class: 'none',
  };
  const previewBody = {
    capabilities: {
      skill_count: 1,
      command_count: 0,
      has_mcp: true,
      has_local_code: false,
      has_compat_risk: false,
      mcp_servers: [{ name: 'airtable', needs_secrets: [] }],
    },
  };

  fn(
    skill,
    previewBody,
    null,
    () => {},
    () => {},
  );

  const overlay = dom.appended[dom.appended.length - 1];
  const classes = dom.allClasses(overlay);

  // Generic notice MUST be present (has_mcp=true, regardless of has_compat_risk)
  assert(
    classes.includes('mp-modal-mcp-compat-notice'),
    'Generic MCP compat notice must appear even when has_compat_risk=false',
  );

  // Stronger compat risk warning must NOT be present
  assert(
    !classes.includes('mp-modal-compat-risk'),
    'mp-modal-compat-risk must NOT appear when has_compat_risk=false',
  );

  console.log(
    '  [PASS] _showVerifiedConsentModal: generic notice present; no compat-risk when false',
  );
}

// ── Test 8: Escape key closes the modal and calls onCancel ───────────────
{
  const { fn, dom } = extractModalFn();

  let cancelCalled = false;
  let confirmCalled = false;

  const skill = {
    id: 'slack',
    name: 'Slack',
    tier: 'Verified',
    source: 'claude-plugins-official',
    coding_class: 'none',
  };
  const previewBody = {
    capabilities: {
      skill_count: 1,
      command_count: 0,
      has_mcp: false,
      has_local_code: false,
      has_compat_risk: false,
      mcp_servers: [],
    },
  };

  fn(
    skill,
    previewBody,
    null,
    () => {
      confirmCalled = true;
    },
    () => {
      cancelCalled = true;
    },
  );

  const overlay = dom.appended[dom.appended.length - 1];
  assert(!overlay._removed, 'Overlay must be present before Escape');

  // Fire the Escape key
  const escEvent = dom.dispatchEscape();
  assert(escEvent._stopped, 'Escape handler must call stopPropagation()');
  assert(escEvent._prevented, 'Escape handler must call preventDefault()');
  assert(overlay._removed, 'Overlay must be removed after Escape');
  assert(cancelCalled, 'onCancel must be called when Escape is pressed');
  assert(!confirmCalled, 'onConfirm must NOT be called on Escape');

  console.log('  [PASS] _showVerifiedConsentModal: Escape closes modal and calls onCancel');
}

// ── Test 9: Focus restored to previous element after close ────────────────
{
  const { fn, dom } = extractModalFn();

  // Set up a fake "previous" element that was focused before the modal opened
  const fakeBtn = dom.document.createElement('button');
  fakeBtn.textContent = 'Install';
  let focusRestored = false;
  fakeBtn.focus = () => {
    focusRestored = true;
  };
  dom.document.activeElement = fakeBtn;

  const skill = {
    id: 'slack',
    name: 'Slack',
    tier: 'Verified',
    source: 'claude-plugins-official',
    coding_class: 'none',
  };
  const previewBody = {
    capabilities: {
      skill_count: 1,
      command_count: 0,
      has_mcp: false,
      has_local_code: false,
      has_compat_risk: false,
      mcp_servers: [],
    },
  };

  let confirmCalled = false;
  fn(
    skill,
    previewBody,
    null,
    () => {
      confirmCalled = true;
    },
    () => {},
  );

  // Simulate user clicking "Install Plugin" to confirm
  const overlay = dom.appended[dom.appended.length - 1];
  // Find the install button via its text
  function findInstallBtn(el) {
    if (!el) return null;
    if (el.textContent === 'Install Plugin') return el;
    for (const c of el.children || []) {
      const found = findInstallBtn(c);
      if (found) return found;
    }
    return null;
  }
  const installBtnEl = findInstallBtn(overlay);
  assert(installBtnEl, 'Install Plugin button must exist in the modal');
  installBtnEl._listeners['click'] && installBtnEl._listeners['click']();

  assert(confirmCalled, 'onConfirm must be called when Install Plugin is clicked');
  assert(
    focusRestored,
    'Focus must be restored to the previous element after Install Plugin is clicked',
  );

  console.log(
    '  [PASS] _showVerifiedConsentModal: focus restored to previous element after confirm',
  );
}

console.log('marketplace_p0_dom_render: all assertions passed');
