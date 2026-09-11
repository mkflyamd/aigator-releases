'use strict';

// P0 UI rendering tests — verifies that Browse cards, Installed sections,
// and the consent modal render the correct structure, class names, text,
// ARIA attributes, focus behavior, and keyboard trapping.
//
// jsdom is not available in this repo (see marketplace_verified_consent.test.js
// limitation comment).  Instead we use a lightweight DOM shim that records
// element creation, class names, textContent, setAttribute calls, and focus
// tracking — enough to verify the structural and a11y output of rendering
// functions without needing a real browser.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'marketplace-pane.js'),
  'utf8',
);

// ── Minimal DOM shim ──────────────────────────────────────────────────────
// Re-created fresh for every modal test via makeDom().
// document.activeElement tracks the last element focus() was called on,
// which the Tab-trap handler reads to decide which element is "current".

function makeDom() {
  const domState = { activeElement: null };

  // Document-level keydown capture handler (one slot — the modal registers one).
  let _docKeydownCapture = null;

  class FakeEl {
    constructor(tag) {
      this.tag = tag;
      this._textContent = '';
      this.className = '';
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
      return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null;
    }
    addEventListener(type, fn) {
      this._listeners[type] = fn;
    }
    removeEventListener() {}
    focus() {
      domState.activeElement = this;
    }
    remove() {
      this._removed = true;
    }
    set textContent(v) {
      this._textContent = String(v == null ? '' : v);
      this.children = [];
    }
    get textContent() {
      return this._textContent || '';
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
  }

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
    // activeElement is a getter so it always reflects the last focus() call.
    get activeElement() {
      return domState.activeElement;
    },
    set activeElement(el) {
      domState.activeElement = el;
    },
    addEventListener(type, fn, capture) {
      if (type === 'keydown' && capture) _docKeydownCapture = fn;
    },
    removeEventListener(type, fn, capture) {
      if (type === 'keydown' && capture && _docKeydownCapture === fn) _docKeydownCapture = null;
    },
  };

  // Fire a synthetic keydown event through the capture-phase handler.
  function dispatchKey(key, shiftKey) {
    const e = {
      key,
      shiftKey: !!shiftKey,
      _stopped: false,
      _prevented: false,
      stopPropagation() {
        this._stopped = true;
      },
      preventDefault() {
        this._prevented = true;
      },
    };
    if (_docKeydownCapture) _docKeydownCapture(e);
    return e;
  }

  // Tree-walking helpers.
  function allText(el) {
    if (!el) return [];
    const texts = [];
    if (!el.children || el.children.length === 0) {
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

  function findByText(el, text) {
    if (!el) return null;
    if (el.textContent === text) return el;
    for (const c of el.children || []) {
      const found = findByText(c, text);
      if (found) return found;
    }
    return null;
  }

  function hasKeydownCapture() {
    return _docKeydownCapture !== null;
  }

  return {
    document,
    appended,
    allText,
    allClasses,
    findByClass,
    findByAttr,
    findByText,
    dispatchKey,
    hasKeydownCapture,
    domState,
    FakeEl,
  };
}

// ── Context builder ───────────────────────────────────────────────────────

function makeCtx(dom) {
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

function extractFn(fnName) {
  const re = new RegExp('function ' + fnName + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n  \\}');
  const match = source.match(re);
  assert(match, fnName + ' not found in marketplace-pane.js');
  const dom = makeDom();
  const ctx = makeCtx(dom);
  vm.runInContext(match[0] + ';', ctx);
  return { fn: ctx[fnName], dom };
}

function extractModal() {
  const re = /function _showVerifiedConsentModal\([^)]*\)\s*\{[\s\S]*?\n  \}/;
  const match = source.match(re);
  assert(match, '_showVerifiedConsentModal not found');
  const dom = makeDom();
  const ctx = makeCtx(dom);
  vm.runInContext(match[0] + ';', ctx);
  return { fn: ctx._showVerifiedConsentModal, dom };
}

// ── Reusable skill/preview fixtures ──────────────────────────────────────

const SLACK_SKILL = {
  id: 'slack',
  name: 'Slack',
  tier: 'Verified',
  source: 'claude-plugins-official',
  coding_class: 'none',
};

function makePreview(overrides) {
  return {
    capabilities: {
      skill_count: 1,
      command_count: 0,
      has_mcp: false,
      has_local_code: false,
      has_compat_risk: false,
      mcp_servers: [],
      ...overrides,
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// CATALOG CARD TESTS
// ═══════════════════════════════════════════════════════════════════════════

// 1. Plugin Bundle card shows label and "Review & Install Plugin"
{
  const { fn, dom } = extractFn('_renderCatalogCard');
  const container = dom.document.createElement('div');
  fn(
    {
      id: 'slack',
      name: 'Slack',
      description: 'Send messages',
      tier: 'Verified',
      source: 'claude-plugins-official',
      coding_class: 'none',
      has_tools: false,
    },
    new Set(),
    new Set(),
    container,
  );
  const classes = dom.allClasses(container);
  const texts = dom.allText(container);
  assert(classes.includes('mp-plugin-bundle-label'), 'must include mp-plugin-bundle-label');
  assert(
    texts.some((t) => t === 'Plugin Bundle'),
    '"Plugin Bundle" label text',
  );
  assert(
    texts.some((t) => t === 'Review & Install Plugin'),
    '"Review & Install Plugin" button',
  );
  console.log('  [PASS] _renderCatalogCard: Plugin Bundle label and button text');
}

// 2. Installed Plugin Bundle shows "Plugin Installed" disabled
{
  const { fn, dom } = extractFn('_renderCatalogCard');
  const container = dom.document.createElement('div');
  fn(
    {
      id: 'datadog',
      name: 'Datadog',
      tier: 'Verified',
      source: 'claude-plugins-official',
      coding_class: 'none',
    },
    new Set(['datadog']),
    new Set(),
    container,
  );
  const texts = dom.allText(container);
  assert(
    texts.some((t) => t === 'Plugin Installed'),
    '"Plugin Installed" text',
  );
  const btn = dom.findByClass(container, 'ap-card-btn');
  assert(btn && btn.disabled, 'Installed button must be disabled');
  console.log('  [PASS] _renderCatalogCard: installed Plugin Bundle shows "Plugin Installed"');
}

// 3. LSP (coding_hard) card shows "Use the Coding Agent" disabled
{
  const { fn, dom } = extractFn('_renderCatalogCard');
  const container = dom.document.createElement('div');
  fn(
    {
      id: 'clangd-lsp',
      name: 'Clangd LSP',
      tier: 'Verified',
      source: 'claude-plugins-official',
      coding_class: 'coding_hard',
    },
    new Set(),
    new Set(),
    container,
  );
  const texts = dom.allText(container);
  assert(
    texts.some((t) => t === 'Use the Coding Agent'),
    '"Use the Coding Agent" text',
  );
  const btn = dom.findByClass(container, 'ap-card-btn');
  assert(btn && btn.disabled, 'LSP button must be disabled');
  console.log('  [PASS] _renderCatalogCard: LSP card shows "Use the Coding Agent"');
}

// 4. coding_soft card shows advisory and install button
{
  const { fn, dom } = extractFn('_renderCatalogCard');
  const container = dom.document.createElement('div');
  fn(
    {
      id: 'code-review',
      name: 'Code Review',
      tier: 'Verified',
      source: 'claude-plugins-official',
      coding_class: 'coding_soft',
    },
    new Set(),
    new Set(),
    container,
  );
  const texts = dom.allText(container);
  assert(
    texts.some((t) => t && t.includes('Coding Agent')),
    'advisory mentions Coding Agent',
  );
  assert(
    texts.some((t) => t === 'Review & Install Plugin'),
    'install button still present',
  );
  console.log('  [PASS] _renderCatalogCard: coding_soft shows advisory + install button');
}

// 5. _pluginMcpState — all states
{
  const { fn } = extractFn('_pluginMcpState');
  const t = (st, msg) => assert.strictEqual(fn(st), msg.split(' ')[0], msg);
  t(null, 'none null→none');
  t(
    { total: 0, enabled: 0, pending: 0, failed: 0, disabled: 0, missing: 0, quarantined: 0 },
    'none total=0→none',
  );
  t(
    { total: 1, enabled: 1, pending: 0, failed: 0, disabled: 0, missing: 0, quarantined: 0 },
    'healthy all-enabled',
  );
  t(
    { total: 1, enabled: 0, pending: 1, failed: 0, disabled: 0, missing: 0, quarantined: 0 },
    'setup all-pending',
  );
  t(
    { total: 1, enabled: 0, pending: 0, failed: 1, disabled: 0, missing: 0, quarantined: 0 },
    'failed all-failed',
  );
  t(
    { total: 1, enabled: 0, pending: 0, failed: 0, disabled: 1, missing: 0, quarantined: 0 },
    'disabled all-disabled',
  );
  t(
    { total: 1, enabled: 0, pending: 0, failed: 0, disabled: 0, missing: 1, quarantined: 0 },
    'missing all-missing',
  );
  t(
    { total: 1, enabled: 1, pending: 0, failed: 0, disabled: 0, missing: 0, quarantined: 1 },
    'quarantined quarantined-tools',
  );
  t(
    { total: 2, enabled: 1, pending: 1, failed: 0, disabled: 0, missing: 0, quarantined: 0 },
    'mixed 1-enabled+1-pending',
  );
  t(
    { total: 2, enabled: 1, pending: 0, failed: 0, disabled: 1, missing: 0, quarantined: 0 },
    'mixed 1-enabled+1-disabled',
  );
  t(
    { total: 2, enabled: 1, pending: 0, failed: 0, disabled: 0, missing: 1, quarantined: 0 },
    'mixed 1-enabled+1-missing',
  );
  console.log('  [PASS] _pluginMcpState: all 11 states/combinations');
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSENT MODAL TESTS
// ═══════════════════════════════════════════════════════════════════════════

// 6. Full structure + ARIA + generic MCP notice + compat-risk when has_compat_risk=true
{
  const { fn, dom } = extractModal();
  const fakeBtn = dom.document.createElement('button');
  fakeBtn.textContent = 'Old focus';
  let prevRestored = false;
  fakeBtn.focus = () => {
    prevRestored = true;
  };
  dom.document.activeElement = fakeBtn;

  fn(
    SLACK_SKILL,
    makePreview({
      skill_count: 1,
      command_count: 2,
      has_mcp: true,
      has_compat_risk: true,
      mcp_servers: [{ name: 'slack', needs_secrets: ['SLACK_BOT_TOKEN', 'SLACK_TEAM_ID'] }],
    }),
    null,
    () => {},
    () => {},
  );

  assert(dom.appended.length > 0, 'overlay appended to body');
  const overlay = dom.appended[dom.appended.length - 1];
  const classes = dom.allClasses(overlay);
  const texts = dom.allText(overlay);

  // ARIA
  const dialogEl = dom.findByAttr(overlay, 'role', 'dialog');
  assert(dialogEl, 'role="dialog" must be set');
  assert.strictEqual(dialogEl._attrs['aria-modal'], 'true', 'aria-modal="true"');
  const labelledBy = dialogEl._attrs['aria-labelledby'];
  assert(labelledBy, 'aria-labelledby must be set');
  const titleEl = dom.findByClass(overlay, 'mp-modal-title');
  assert(titleEl, 'mp-modal-title must exist');
  assert.strictEqual(titleEl.id, labelledBy, 'title id must match aria-labelledby');
  assert(titleEl.textContent.includes('Review & Install Plugin'), 'title content');

  // Focus moved into dialog
  const focused = dom.document.activeElement;
  assert(
    focused !== null && focused.textContent === 'Cancel',
    'focus must be on Cancel button after open',
  );

  // Generic MCP notice (always shown when has_mcp=true)
  assert(
    classes.includes('mp-modal-mcp-compat-notice'),
    'generic MCP compat notice must be present',
  );
  const noticeEl = dom.findByClass(overlay, 'mp-modal-mcp-compat-notice');
  assert(
    noticeEl && noticeEl.textContent.includes('compatibility-checked'),
    'generic notice must mention compatibility-checked',
  );

  // Stronger compat-risk warning
  assert(
    classes.includes('mp-modal-compat-risk'),
    'mp-modal-compat-risk present when has_compat_risk=true',
  );

  // Skills + commands summary
  assert(
    texts.some((t) => t && t.includes('1 skill') && t.includes('2 commands')),
    'summary includes skill and command count',
  );

  // MCP server + secrets
  assert(
    texts.some((t) => t && t.includes('slack') && t.includes('SLACK_BOT_TOKEN')),
    'MCP server name and secret listed',
  );

  // Install button
  assert(
    texts.some((t) => t === 'Install Plugin'),
    '"Install Plugin" button text',
  );

  // Keyboard handler registered
  assert(dom.hasKeydownCapture(), 'keydown capture handler must be registered');

  console.log('  [PASS] _showVerifiedConsentModal: ARIA, focus, generic MCP notice, compat-risk');
}

// 7. Generic MCP notice when has_mcp=true but mcp_servers=[] (unparsed server)
{
  const { fn, dom } = extractModal();

  fn(
    SLACK_SKILL,
    makePreview({ has_mcp: true, mcp_servers: [], has_compat_risk: false }),
    null,
    () => {},
    () => {},
  );

  const overlay = dom.appended[dom.appended.length - 1];
  const classes = dom.allClasses(overlay);

  // Generic notice MUST be present even though mcp_servers is empty
  assert(
    classes.includes('mp-modal-mcp-compat-notice'),
    'generic MCP compat notice must appear when has_mcp=true even if mcp_servers=[]',
  );

  // Server-specific list must NOT be present (nothing to list)
  assert(
    !classes.includes('mp-mcp-server-list'),
    'mp-mcp-server-list must NOT appear when mcp_servers=[]',
  );

  // Stronger compat-risk warning must NOT appear
  assert(
    !classes.includes('mp-modal-compat-risk'),
    'mp-modal-compat-risk must NOT appear when has_compat_risk=false',
  );

  console.log(
    '  [PASS] _showVerifiedConsentModal: generic notice present when has_mcp=true, mcp_servers=[]',
  );
}

// 8. No MCP notices when has_mcp=false
{
  const { fn, dom } = extractModal();

  fn(
    SLACK_SKILL,
    makePreview({ has_mcp: false, mcp_servers: [], has_compat_risk: false }),
    null,
    () => {},
    () => {},
  );

  const overlay = dom.appended[dom.appended.length - 1];
  const classes = dom.allClasses(overlay);

  assert(!classes.includes('mp-modal-mcp-compat-notice'), 'no generic notice when has_mcp=false');
  assert(!classes.includes('mp-modal-compat-risk'), 'no compat-risk when has_mcp=false');

  console.log('  [PASS] _showVerifiedConsentModal: no MCP notices when has_mcp=false');
}

// 9. Escape closes, calls onCancel, stopPropagation + preventDefault, cleans up handler
{
  const { fn, dom } = extractModal();

  let cancelCalled = false;
  fn(
    SLACK_SKILL,
    makePreview(),
    null,
    () => {},
    () => {
      cancelCalled = true;
    },
  );

  const overlay = dom.appended[dom.appended.length - 1];
  assert(!overlay._removed, 'overlay present before Escape');
  assert(dom.hasKeydownCapture(), 'handler registered before Escape');

  const e = dom.dispatchKey('Escape', false);
  assert(e._stopped, 'Escape must stopPropagation');
  assert(e._prevented, 'Escape must preventDefault');
  assert(overlay._removed, 'overlay removed after Escape');
  assert(cancelCalled, 'onCancel called after Escape');
  assert(!dom.hasKeydownCapture(), 'keydown handler removed after Escape');

  console.log(
    '  [PASS] _showVerifiedConsentModal: Escape closes, cleans up handler, calls onCancel',
  );
}

// 10. Focus restored to previous element after Escape
{
  const { fn, dom } = extractModal();

  let focusRestored = false;
  const prevBtn = dom.document.createElement('button');
  prevBtn.textContent = 'trigger';
  prevBtn.focus = () => {
    focusRestored = true;
  };
  dom.document.activeElement = prevBtn;

  fn(
    SLACK_SKILL,
    makePreview(),
    null,
    () => {},
    () => {},
  );
  dom.dispatchKey('Escape', false);

  assert(focusRestored, 'focus must be restored to prevFocus after Escape');
  console.log('  [PASS] _showVerifiedConsentModal: focus restored to prevFocus after Escape');
}

// 11. Tab from last focusable (installBtn) wraps to first (cancelBtn)
{
  const { fn, dom } = extractModal();

  fn(
    SLACK_SKILL,
    makePreview(),
    null,
    () => {},
    () => {},
  );

  const overlay = dom.appended[dom.appended.length - 1];

  // Find the install button by text and simulate it being focused.
  const installBtnEl = dom.findByText(overlay, 'Install Plugin');
  assert(installBtnEl, 'Install Plugin button must exist');
  dom.document.activeElement = installBtnEl; // simulate focus on last control

  const e = dom.dispatchKey('Tab', false); // forward Tab
  assert(e._prevented, 'Tab must be preventDefault-ed when wrapping');

  // After wrapping, focus should have moved to cancelBtn (first control).
  const nowFocused = dom.document.activeElement;
  assert(
    nowFocused && nowFocused.textContent === 'Cancel',
    'Tab from installBtn must wrap to cancelBtn (got: ' +
      (nowFocused && nowFocused.textContent) +
      ')',
  );

  console.log('  [PASS] _showVerifiedConsentModal: Tab wraps forward from installBtn to cancelBtn');
}

// 12. Shift+Tab from first focusable (cancelBtn) wraps to last (installBtn)
{
  const { fn, dom } = extractModal();

  fn(
    SLACK_SKILL,
    makePreview(),
    null,
    () => {},
    () => {},
  );

  const overlay = dom.appended[dom.appended.length - 1];

  // Find the cancel button. After open, cancelBtn.focus() was called, so
  // document.activeElement is already cancelBtn. But set explicitly for clarity.
  const cancelBtnEl = dom.findByText(overlay, 'Cancel');
  assert(cancelBtnEl, 'Cancel button must exist');
  dom.document.activeElement = cancelBtnEl; // focus on first control

  const e = dom.dispatchKey('Tab', true); // Shift+Tab
  assert(e._prevented, 'Shift+Tab must be preventDefault-ed when wrapping');

  const nowFocused = dom.document.activeElement;
  assert(
    nowFocused && nowFocused.textContent === 'Install Plugin',
    'Shift+Tab from cancelBtn must wrap to installBtn (got: ' +
      (nowFocused && nowFocused.textContent) +
      ')',
  );

  console.log(
    '  [PASS] _showVerifiedConsentModal: Shift+Tab wraps backward from cancelBtn to installBtn',
  );
}

// 13. Tab between non-boundary controls does nothing (no wrapping, no prevention)
{
  const { fn, dom } = extractModal();

  fn(
    SLACK_SKILL,
    makePreview(),
    null,
    () => {},
    () => {},
  );

  // Simulate focus on cancelBtn (first), press forward Tab — handler only
  // acts when activeElement === installBtn. When it's cancelBtn, Tab should
  // fall through normally (no preventDefault called).
  const overlay = dom.appended[dom.appended.length - 1];
  const cancelBtnEl = dom.findByText(overlay, 'Cancel');
  dom.document.activeElement = cancelBtnEl;

  // Tab forward from cancelBtn → NOT at installBtn, so no wrap.
  const e = dom.dispatchKey('Tab', false);
  // preventDefault must NOT have been called (Tab falls through to browser).
  assert(!e._prevented, 'Tab from cancelBtn must NOT preventDefault (not at boundary)');

  console.log(
    '  [PASS] _showVerifiedConsentModal: Tab from non-last control falls through normally',
  );
}

// 14. Install Plugin click calls onConfirm, restores focus, removes handler
{
  const { fn, dom } = extractModal();

  let confirmCalled = false;
  let focusRestored = false;
  const prevBtn = dom.document.createElement('button');
  prevBtn.focus = () => {
    focusRestored = true;
  };
  dom.document.activeElement = prevBtn;

  fn(
    SLACK_SKILL,
    makePreview(),
    null,
    () => {
      confirmCalled = true;
    },
    () => {},
  );

  const overlay = dom.appended[dom.appended.length - 1];
  assert(dom.hasKeydownCapture(), 'handler registered before confirm click');

  const installBtnEl = dom.findByText(overlay, 'Install Plugin');
  assert(installBtnEl, 'Install Plugin button must exist');
  installBtnEl._listeners['click']();

  assert(confirmCalled, 'onConfirm called after Install Plugin click');
  assert(focusRestored, 'focus restored after Install Plugin click');
  assert(overlay._removed, 'overlay removed after Install Plugin click');
  assert(!dom.hasKeydownCapture(), 'keydown handler removed after Install Plugin click');

  console.log(
    '  [PASS] _showVerifiedConsentModal: Install Plugin click → confirm, focus restore, cleanup',
  );
}

// 15. Cancel click calls onCancel, restores focus, removes handler
{
  const { fn, dom } = extractModal();

  let cancelCalled = false;
  let focusRestored = false;
  const prevBtn = dom.document.createElement('button');
  prevBtn.focus = () => {
    focusRestored = true;
  };
  dom.document.activeElement = prevBtn;

  fn(
    SLACK_SKILL,
    makePreview(),
    null,
    () => {},
    () => {
      cancelCalled = true;
    },
  );

  const overlay = dom.appended[dom.appended.length - 1];
  const cancelBtnEl = dom.findByText(overlay, 'Cancel');
  cancelBtnEl._listeners['click']();

  assert(cancelCalled, 'onCancel called after Cancel click');
  assert(focusRestored, 'focus restored after Cancel click');
  assert(!dom.hasKeydownCapture(), 'keydown handler removed after Cancel click');

  console.log('  [PASS] _showVerifiedConsentModal: Cancel click → cancel, focus restore, cleanup');
}

console.log('marketplace_p0_dom_render: all assertions passed');
