// tp-generic-agent-terminal.js — terminal UI for generic, BYO-config coding
// agents (Claude Code CLI, Codex CLI, Crush, OpenCode bare, and a plain
// Terminal).
//
// Calls the shared, session-agnostic xterm helpers in tp-term-helpers.js
// (_ocSpawnTerm, _ocFit, _ocGuardSize, _ocFetch, _ocRemoveHeaderTabStrip)
// rather than re-implementing xterm setup/paste/keybindings — those only ever
// touch the `sess` object passed to them, never this file's own state.
//
// Multi-session per (tab, project): the tab strip is mounted in the SAME
// persistent #tp-detail-header toolbar row OpenCode uses (via its own
// ga-header-tabstrip element, mirroring _ocEnsureHeaderTabStrip) - not a
// second ribbon in the content area. Every tab is an independent process;
// all tabs use the project's currently selected agent (the per-project
// picker in tp-code-agent.js is unchanged).

// True while a tab label is being renamed (contentEditable). Checked by
// _genAgentActivateSession so the terminal's focus() doesn't steal focus
// back from the label mid-rename — mirrors terminal.js's STATE.editing.
let _genAgentEditing = false;

// tabId -> {
//   termsEl,          // .gtp-terms container; session containers append here
//   agent, projectId, repoPath,
//   sessions: { ptyId: sess }, order: [ptyId...], activeId, seq, _starting
// }
let _genAgentTerminals = {};

function _genAgentPromptId(tabId) {
  return 'ga-startprompt-' + (typeof _caSessionKey === 'function' ? _caSessionKey(tabId) : tabId);
}
function _genAgentLoadingId(tabId) {
  return 'ga-loading-' + (typeof _caSessionKey === 'function' ? _caSessionKey(tabId) : tabId);
}

// Agent ids with a multi-word/special-cased display label (default is just
// capitalize-first-letter, e.g. "claude" -> "Claude"). Keep in sync with
// tp-code-agent.js's _CA_AGENT_LABELS for the same id. opencode-bare is now
// the primary/default OpenCode path (see tp-code-agent.js's _CA_AGENT_LABELS
// comment for #156 context) — plain "OpenCode", not the old "(bare test)"
// A/B-test label.
const _GEN_EXTRA_AGENT_LABELS = {
  openclaude: 'OpenClaude',
  grok: 'Grok',
  copilot: 'GitHub Copilot',
  'mimo-code': 'MiMo Code',
  ante: 'Ante',
  trae: 'Trae',
  muse: 'Muse',
  dsh: 'DeepSeek Harness',
  qoder: 'Qoder CLI',
  'qoder-cn': 'Qoder CLI China',
  zcode: 'ZCode',
  pi: 'Pi',
  omp: 'OMP',
  'prime-agent': 'Prime Agent',
  gemini: 'Gemini',
  antigravity: 'Antigravity',
  aider: 'Aider',
  goose: 'Goose',
  amp: 'Amp',
  kilo: 'Kilocode',
  kiro: 'Kiro',
  aug: 'Auggie',
  autohand: 'Autohand Code',
  cline: 'Cline',
  codebuff: 'Codebuff',
  freebuff: 'Freebuff',
  'command-code': 'Command Code',
  continue: 'Continue',
  cursor: 'Cursor',
  droid: 'Droid',
  kimi: 'Kimi',
  'mistral-vibe': 'Mistral Vibe',
  'qwen-code': 'Qwen Code',
  rovo: 'Rovo Dev',
  hermes: 'Hermes',
  devin: 'Devin',
  openclaw: 'OpenClaw',
  codebuddy: 'CodeBuddy',
  jcode: 'JCode',
};
const _GEN_AGENT_LABEL_OVERRIDES = { 'opencode-bare': 'OpenCode', ..._GEN_EXTRA_AGENT_LABELS };
function _genAgentLabel(agent) {
  return _GEN_AGENT_LABEL_OVERRIDES[agent] || agent.charAt(0).toUpperCase() + agent.slice(1);
}

// Agent marks follow Orca's approach: inline SVG that takes the theme colour
// (Claude keeps its brand orange), a bundled PNG for Crush, no network fetch.
const _GEN_AGENT_ICON_HTML = {
  claude:
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path fill="#D97757" d="M4.709 15.955l4.72-2.647.08-.23-.08-.128H9.2l-.79-.048-2.698-.073-2.339-.097-2.266-.122-.571-.121L0 11.784l.055-.352.48-.321.686.06 1.52.103 2.278.158 1.652.097 2.449.255h.389l.055-.157-.134-.098-.103-.097-2.358-1.596-2.552-1.688-1.336-.972-.724-.491-.364-.462-.158-1.008.656-.722.881.06.225.061.893.686 1.908 1.476 2.491 1.833.365.304.145-.103.019-.073-.164-.274-1.355-2.446-1.446-2.49-.644-1.032-.17-.619a2.97 2.97 0 01-.104-.729L6.283.134 6.696 0l.996.134.42.364.62 1.414 1.002 2.229 1.555 3.03.456.898.243.832.091.255h.158V9.01l.128-1.706.237-2.095.23-2.695.08-.76.376-.91.747-.492.584.28.48.685-.067.444-.286 1.851-.559 2.903-.364 1.942h.212l.243-.242.985-1.306 1.652-2.064.73-.82.85-.904.547-.431h1.033l.76 1.129-.34 1.166-1.064 1.347-.881 1.142-1.264 1.7-.79 1.36.073.11.188-.02 2.856-.606 1.543-.28 1.841-.315.833.388.091.395-.328.807-1.969.486-2.309.462-3.439.813-.042.03.049.061 1.549.146.662.036h1.622l3.02.225.79.522.474.638-.079.485-1.215.62-1.64-.389-3.829-.91-1.312-.329h-.182v.11l1.093 1.068 2.006 1.81 2.509 2.33.127.578-.322.455-.34-.049-2.205-1.657-.851-.747-1.926-1.62h-.128v.17l.444.649 2.345 3.521.122 1.08-.17.353-.608.213-.668-.122-1.374-1.925-1.415-2.167-1.143-1.943-.14.08-.674 7.254-.316.37-.729.28-.607-.461-.322-.747.322-1.476.389-1.924.315-1.53.286-1.9.17-.632-.012-.042-.14.018-1.434 1.967-2.18 2.945-1.726 1.845-.414.164-.717-.37.067-.662.401-.589 2.388-3.036 1.44-1.882.93-1.086-.006-.158h-.055L4.132 18.56l-1.13.146-.487-.456.061-.746.231-.243 1.908-1.312-.006.006z"/></svg>',
  codex:
    '<svg viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd" xmlns="http://www.w3.org/2000/svg"><path d="M9.205 8.658v-2.26c0-.19.072-.333.238-.428l4.543-2.616c.619-.357 1.356-.523 2.117-.523 2.854 0 4.662 2.212 4.662 4.566 0 .167 0 .357-.024.547l-4.71-2.759a.797.797 0 00-.856 0l-5.97 3.473zm10.609 8.8V12.06c0-.333-.143-.57-.429-.737l-5.97-3.473 1.95-1.118a.433.433 0 01.476 0l4.543 2.617c1.309.76 2.189 2.378 2.189 3.948 0 1.808-1.07 3.473-2.76 4.163zM7.802 12.703l-1.95-1.142c-.167-.095-.239-.238-.239-.428V5.899c0-2.545 1.95-4.472 4.591-4.472 1 0 1.927.333 2.712.928L8.23 5.067c-.285.166-.428.404-.428.737v6.898zM12 15.128l-2.795-1.57v-3.33L12 8.658l2.795 1.57v3.33L12 15.128zm1.796 7.23c-1 0-1.927-.332-2.712-.927l4.686-2.712c.285-.166.428-.404.428-.737v-6.898l1.974 1.142c.167.095.238.238.238.428v5.233c0 2.545-1.974 4.472-4.614 4.472zm-5.637-5.303l-4.544-2.617c-1.308-.761-2.188-2.378-2.188-3.948A4.482 4.482 0 014.21 6.327v5.423c0 .333.143.571.428.738l5.947 3.449-1.95 1.118a.432.432 0 01-.476 0zm-.262 3.9c-2.688 0-4.662-2.021-4.662-4.519 0-.19.024-.38.047-.57l4.686 2.71c.286.167.571.167.856 0l5.97-3.448v2.26c0 .19-.07.333-.237.428l-4.543 2.616c-.619.357-1.356.523-2.117.523zm5.899 2.83a5.947 5.947 0 005.827-4.756C22.287 18.339 24 15.84 24 13.296c0-1.665-.713-3.282-1.998-4.448.119-.5.19-.999.19-1.498 0-3.401-2.759-5.947-5.946-5.947-.642 0-1.26.095-1.88.31A5.962 5.962 0 0010.205 0a5.947 5.947 0 00-5.827 4.757C1.713 5.447 0 7.945 0 10.49c0 1.666.713 3.283 1.998 4.448-.119.5-.19 1-.19 1.499 0 3.401 2.759 5.946 5.946 5.946.642 0 1.26-.095 1.88-.309a5.96 5.96 0 004.162 1.713z"/></svg>',
  crush: '<img src="/static/icons/agents/crush.png" alt="" />',
  pi: '<svg viewBox="0 0 800 800" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" fill-rule="evenodd" d="M165.29 165.29 H517.36 V400 H400 V517.36 H282.65 V634.72 H165.29 Z M282.65 282.65 V400 H400 V282.65 Z"/><path fill="currentColor" d="M517.36 400 H634.72 V634.72 H517.36 Z"/></svg>',
  omp: '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><path fill="oklch(0.62 0.21 295)" d="M10 14h44v9H43v33h-9V23h-9v22h-9V23H10z"/></svg>',
  aider:
    '<svg viewBox="0 0 436 436" xmlns="http://www.w3.org/2000/svg"><g transform="translate(0,436) scale(0.1,-0.1)" fill="currentColor" stroke="none"><path d="M0 2180 l0 -2180 2180 0 2180 0 0 2180 0 2180 -2180 0 -2180 0 0 -2180z m2705 1818 c20 -20 28 -121 30 -398 l2 -305 216 -5 c118 -3 218 -8 222 -12 3 -3 10 -46 15 -95 5 -48 16 -126 25 -172 17 -86 17 -81 -17 -233 -14 -67 -13 -365 2 -438 21 -100 22 -159 5 -247 -24 -122 -24 -363 1 -458 23 -88 23 -213 1 -330 -9 -49 -17 -109 -17 -132 l0 -43 203 0 c111 0 208 -4 216 -9 10 -6 18 -51 27 -148 8 -76 16 -152 20 -168 7 -39 -23 -361 -37 -387 -10 -18 -21 -19 -214 -16 -135 2 -208 7 -215 14 -22 22 -33 301 -21 501 6 102 8 189 5 194 -8 13 -417 12 -431 -2 -12 -12 -8 -146 8 -261 8 -55 8 -95 1 -140 -6 -35 -14 -99 -17 -143 -9 -123 -14 -141 -41 -154 -18 -8 -217 -11 -679 -11 l-653 0 -11 33 c-31 97 -43 336 -27 533 5 56 6 113 2 128 l-6 26 -194 0 c-211 0 -252 4 -261 28 -12 33 -17 392 -6 522 15 186 -2 174 260 180 115 3 213 8 217 12 4 4 1 52 -5 105 -7 54 -17 130 -22 168 -7 56 -5 91 11 171 10 55 22 130 26 166 4 36 10 72 15 79 7 12 128 15 665 19 l658 5 8 30 c5 18 4 72 -3 130 -12 115 -7 346 11 454 10 61 10 75 -1 82 -8 5 -300 9 -650 9 l-636 0 -27 25 c-18 16 -26 34 -26 57 0 18 -5 87 -10 153 -10 128 5 449 22 472 5 7 26 13 46 15 78 6 1281 3 1287 -4z"/><path d="M1360 1833 c0 -5 -1 -164 -3 -356 l-2 -347 625 -1 c704 -1 708 -1 722 7 5 4 7 20 4 38 -29 141 -32 491 -6 595 9 38 8 45 -7 57 -15 11 -139 13 -675 14 -362 0 -658 -3 -658 -7z"/></g></svg>',
  'opencode-bare':
    '<svg viewBox="0 0 512 512" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M320 224V352H192V224H320Z" fill="currentColor" fill-opacity="0.28"/><path fill-rule="evenodd" clip-rule="evenodd" d="M384 416H128V96H384V416ZM320 160H192V352H320V160Z" fill="currentColor"/></svg>',
  terminal:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg"><path d="m5 8 5 4-5 4"/><path d="M13 17h6"/></svg>',
};
// Orca's bundled favicons for the other catalog agents (qoder-cn shares qoder's);
// anything without a mark falls back to its first letter.
const _GEN_AGENT_PNG_ICONS = [
  'amp',
  'ante',
  'antigravity',
  'aug',
  'autohand',
  'cline',
  'codebuddy',
  'codebuff',
  'command-code',
  'continue',
  'copilot',
  'cursor',
  'devin',
  'droid',
  'dsh',
  'freebuff',
  'gemini',
  'goose',
  'grok',
  'hermes',
  'jcode',
  'kilo',
  'kimi',
  'kiro',
  'mimo-code',
  'mistral-vibe',
  'muse',
  'openclaude',
  'openclaw',
  'prime-agent',
  'qoder',
  'qwen-code',
  'rovo',
  'trae',
  'zcode',
];
const _GEN_AGENT_ICON_FILE = { 'qoder-cn': 'qoder' };
function _genAgentIconHtml(agent) {
  if (_GEN_AGENT_ICON_HTML[agent]) return _GEN_AGENT_ICON_HTML[agent];
  const file = _GEN_AGENT_ICON_FILE[agent] || agent;
  if (_GEN_AGENT_PNG_ICONS.includes(file))
    return '<img src="/static/icons/agents/' + file + '.png" alt="" />';
  return '';
}
function _genAgentTabIcon(agent) {
  const icon = document.createElement('span');
  icon.className = 'gtp-tab-icon';
  icon.dataset.agent = agent;
  icon.setAttribute('aria-hidden', 'true');
  const html = _genAgentIconHtml(agent);
  if (html) icon.append(...new DOMParser().parseFromString(html, 'text/html').body.childNodes);
  else icon.textContent = _genAgentLabel(agent).charAt(0);
  return icon;
}

function _genAgentEnsureTermsContainer(tabId) {
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return null;
  let state = _genAgentTerminals[_caSessionKey(tabId)];
  if (state && state.termsEl) {
    // Async completion for a tab the user has left must update its detached
    // DOM in memory, not mount that DOM over the tab currently on screen.
    // _genAgentMountActiveTab is the authoritative re-attach point on a tab
    // switch. Comparing raw tab ids matters even when terminal state uses the
    // shared session key.
    const isActiveTab =
      typeof _activeTabId === 'undefined' || String(tabId) === String(_activeTabId);
    if (isActiveTab && state.termsEl.parentElement !== detailCol) {
      detailCol.appendChild(state.termsEl);
      state.termsEl.style.display = '';
    }
    return state;
  }
  const termsEl = document.createElement('div');
  termsEl.className = 'gtp-terms';
  detailCol.appendChild(termsEl);
  state = _genAgentTerminals[_caSessionKey(tabId)] = state || {
    agent: null,
    projectId: null,
    repoPath: null,
    sessions: {},
    order: [],
    activeId: null,
    seq: 0,
  };
  state.termsEl = termsEl;
  return state;
}

function _genAgentActiveSess(state) {
  return state && state.activeId ? state.sessions[state.activeId] : null;
}

// Hide/show the terminal container for this tab when a file diff/content view
// is opened/closed over it (tp-code-agent.js). The diff and terminal share
// #tp-detail-col (a flex column), so both visible at once would split space
// instead of one covering the other. Hide = display:none on the termsEl; the
// live xterm/WebSocket objects stay in JS memory, intact.
function _genAgentHideTerminal(tabId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (state && state.termsEl) state.termsEl.style.display = 'none';
}

function _genAgentShowTerminal(tabId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (
    state &&
    state.termsEl &&
    state.termsEl.parentElement === document.getElementById('tp-detail-col')
  ) {
    state.termsEl.style.display = '';
    const sess = _genAgentActiveSess(state);
    if (sess) setTimeout(() => _ocFit(sess), 20);
  }
}

// True only when THIS tab's active session is actually attached to the
// visible column right now (mirrors _ocIsTerminalMounted). agent is optional -
// omit it to ask "is anything mounted" (used by the picker's live-session
// check); pass it to ask "is THIS agent's session mounted", which
// _genAgentShowStartOrTerminal below needs - see its comment for why.
function _genAgentIsTerminalMounted(tabId, agent) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  const detailCol = document.getElementById('tp-detail-col');
  const sess = _genAgentActiveSess(state);
  return !!(
    state &&
    state.termsEl &&
    detailCol &&
    state.termsEl.parentElement === detailCol &&
    sess &&
    sess.term &&
    (agent === undefined || state.agent === agent)
  );
}

function _genAgentShowStartOrTerminal(tabId, agent, projectId, repoPath) {
  // Must check that the MOUNTED session's agent matches the one being asked
  // for, not just "is anything mounted". Real bug found via user report:
  // switching a project from OpenCode to Claude showed a leftover PowerShell
  // terminal instead of Claude's own prompt - a "terminal" agent session had
  // been left mounted on this tabId from earlier (switching OpenCode <-> a
  // generic agent only detaches the OUTGOING agent's own state; it never
  // touches the OTHER agent's state, since a project switch away from that
  // one never went through it). Without the agent check here, this function
  // saw "something is mounted" and returned early, silently leaving the
  // stale terminal on screen instead of showing the Claude start prompt.
  if (_genAgentIsTerminalMounted(tabId, agent)) return;
  _genAgentShowStartPrompt(tabId, agent, projectId, repoPath);
}

// Re-attach still-alive sessions into the DOM on return to the Code tab (a
// skill switch tears down and rebuilds #tp-detail-col) - mirrors
// _ocMountActiveTab. Sessions survive in JS memory; their containers ride
// along inside the detached termsEl, so this just re-mounts, re-renders the
// header strip, and refits.
function _genAgentMountActiveTab(tabId) {
  if (typeof tpState === 'undefined' || tpState.type !== 'code_agent') return;
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return;
  Object.keys(_genAgentTerminals).forEach((tid) => {
    if (tid !== _caSessionKey(tabId)) {
      const other = _genAgentTerminals[tid];
      if (other && other.termsEl && other.termsEl.parentElement === detailCol)
        other.termsEl.remove();
    }
  });
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (state && state.termsEl && state.termsEl.parentElement !== detailCol) {
    detailCol.appendChild(state.termsEl);
    state.termsEl.style.display = '';
  }
  _genAgentRenderTabs(tabId);
  const sess = _genAgentActiveSess(state);
  if (sess) setTimeout(() => _ocFit(sess), 20);
}

// ── Header tab strip (mounted in #tp-detail-header, same row/pattern as
// tp-term-helpers.js _ocRemoveHeaderTabStrip - reuses the oc-header-tabs styling) ──
function _genAgentHeaderTabStripId() {
  return 'ga-header-tabstrip';
}

function _genAgentEnsureHeaderTabStrip() {
  if (typeof tpState === 'undefined' || tpState.type !== 'code_agent') return null;
  const hdr = document.getElementById('tp-detail-header');
  if (!hdr) return null;
  // Exactly one header strip at a time - drop OpenCode's if it's up (this
  // project uses a generic agent, not OpenCode).
  if (typeof _ocRemoveHeaderTabStrip === 'function') _ocRemoveHeaderTabStrip();
  let strip = document.getElementById(_genAgentHeaderTabStripId());
  if (!strip) {
    strip = document.createElement('div');
    strip.id = _genAgentHeaderTabStripId();
    strip.className = 'gtp-tabs oc-header-tabs';
    const scroll = document.createElement('div');
    scroll.className = 'gtp-tabs-scroll';
    const newBtn = document.createElement('button');
    newBtn.type = 'button';
    newBtn.className = 'gtp-tab-new';
    newBtn.title = 'New terminal';
    newBtn.innerHTML =
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>';
    scroll.appendChild(newBtn);
    strip.appendChild(scroll);
    strip._scroll = scroll;
    strip._newBtn = newBtn;
    hdr.insertBefore(strip, hdr.firstChild);
  }
  return strip;
}

function _genAgentRemoveHeaderTabStrip() {
  document.getElementById(_genAgentHeaderTabStripId())?.remove();
}

function _genAgentSyncHeaderTabStripOnTabSwitch(tabId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (state && state.order.length) _genAgentRenderTabs(tabId);
  else _genAgentRemoveHeaderTabStrip();
}

function _genAgentRenderTabs(tabId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (!state || state.order.filter((id) => state.sessions[id]).length === 0) {
    _genAgentRemoveHeaderTabStrip();
    return;
  }
  const strip = _genAgentEnsureHeaderTabStrip();
  if (!strip) return;
  // The header itself survives some detail-pane remounts. Query its children
  // on every render instead of relying on expando properties set when it was
  // first created, which can be absent on a surviving DOM node and leave a
  // stale tab strip after a session is closed.
  const scroll = strip.querySelector('.gtp-tabs-scroll');
  const newBtn = scroll && scroll.querySelector('.gtp-tab-new');
  if (!scroll || !newBtn) return;
  newBtn.title = 'New terminal…';
  newBtn.setAttribute('aria-haspopup', 'menu');
  newBtn.onclick = () => _genAgentOpenNewMenu(tabId, newBtn);
  [...scroll.querySelectorAll('.gtp-tab')].forEach((el) => el.remove());
  state.order.forEach((id) => {
    const sess = state.sessions[id];
    if (!sess) return;
    const tab = document.createElement('div');
    tab.className = 'gtp-tab' + (id === state.activeId ? ' active' : '');
    tab.dataset.sid = String(id);
    const label = document.createElement('span');
    label.className = 'gtp-tab-label';
    label.textContent = sess.label;
    label.title = sess.label;
    // Per-tab actions (hand off, pop out, restart) live in one kebab menu. Restart
    // is the escape hatch for a session that is alive but silently wedged, which
    // the cold-start watchdog and exit-restart overlay never catch.
    const kebab = document.createElement('button');
    kebab.type = 'button';
    kebab.className = 'gtp-tab-restart gtp-tab-kebab';
    kebab.title = 'Session actions';
    kebab.setAttribute('aria-label', 'Session actions');
    kebab.setAttribute('aria-haspopup', 'menu');
    kebab.textContent = '⋮';
    kebab.addEventListener('click', (e) => {
      e.stopPropagation();
      _genAgentOpenTabMenu(tabId, id, kebab);
    });
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'gtp-tab-close';
    x.title = 'Close';
    x.textContent = '✕';
    tab.appendChild(_genAgentTabIcon(sess.agent || state.agent));
    if (window.agentHistory) window.agentHistory.applyTabState(tab, sess, Date.now());
    tab.appendChild(label);
    _genAgentDecorateWokenTab(tab, sess);
    tab.appendChild(kebab);
    tab.appendChild(x);
    tab.addEventListener('click', (e) => {
      if (e.target === x || e.target === kebab) return;
      if (label.isContentEditable) return; // don't activate while renaming
      if (typeof _caCloseFileDiffIfOpen === 'function') _caCloseFileDiffIfOpen();
      _genAgentActivateSession(tabId, id);
    });
    tab.addEventListener('dblclick', (e) => {
      if (e.target === x || e.target === kebab) return;
      e.preventDefault();
      e.stopPropagation();
      _genAgentBeginRename(sess, label);
    });
    x.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      // Remove the clicked tab immediately. Session cleanup below rebuilds the
      // whole strip, but this avoids leaving a stale tab on screen if a pane
      // remount interrupts that render.
      tab.remove();
      _genAgentCloseSession(tabId, id);
    });
    scroll.insertBefore(tab, newBtn);
  });
}

// Toggle the .active class on existing tab DOM elements — like terminal.js's
// _updateActiveTab. Used by _genAgentActivateSession instead of a full
// _genAgentRenderTabs, so activating a tab does NOT destroy and rebuild the
// tab strip (which would kill the dblclick-to-rename listener before the
// second click of a double-click can fire).
function _genAgentUpdateActiveTab(tabId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (!state) return;
  const scroll = document.querySelector('#' + _genAgentHeaderTabStripId() + ' .gtp-tabs-scroll');
  if (!scroll) return;
  scroll.querySelectorAll('.gtp-tab').forEach((el) => {
    el.classList.toggle('active', el.dataset.sid === state.activeId);
  });
}

function _genAgentBeginRename(sess, labelEl) {
  _genAgentEditing = true;
  labelEl.contentEditable = 'true';
  labelEl.spellcheck = false;
  labelEl.classList.add('editing');
  // Defer focus past the 20ms xterm focus-grab in _genAgentActivateSession
  // (the first click of the dblclick activates the tab, which schedules
  // sess.term.focus() at +20ms). Without this, xterm steals focus back
  // immediately, blur fires, and the rename never takes.
  setTimeout(() => {
    if (!_genAgentEditing) return; // already cancelled
    labelEl.focus();
    const range = document.createRange();
    range.selectNodeContents(labelEl);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }, 50);

  const finish = (commit) => {
    labelEl.removeEventListener('keydown', onKey);
    labelEl.removeEventListener('blur', onBlur);
    labelEl.contentEditable = 'false';
    labelEl.classList.remove('editing');
    _genAgentEditing = false;
    const next = labelEl.textContent.trim();
    if (commit && next) {
      sess.label = next;
      sess.userLabel = next;
    }
    labelEl.textContent = sess.label;
    labelEl.title = sess.label;
    window.getSelection().removeAllRanges();
  };
  const onKey = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      finish(true);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      finish(false);
    }
  };
  const onBlur = () => finish(true);
  labelEl.addEventListener('keydown', onKey);
  labelEl.addEventListener('blur', onBlur);
}

// Ordered by how often people reach for them.
function _genAgentOpenTabMenu(tabId, id, anchor) {
  const wasOpen = document.querySelector('.gtp-new-menu');
  _genAgentCloseNewMenu();
  if (wasOpen && wasOpen.dataset.owner === 'tab:' + id) return;
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  const sess = state && state.sessions[id];
  if (!sess) return;
  const actions = [
    {
      label: 'Hand off to another agent…',
      run: () => {
        if (window.agentHandoff) window.agentHandoff.openDialog({ tabId, sess });
      },
    },
  ];
  if (window.gatorShell && typeof window.gatorShell.popOutTerminal === 'function') {
    actions.push({
      label: 'Open in its own window',
      run: async () => {
        if (await window.gatorShell.popOutTerminal(sess.ptySessionId, sess.label)) {
          _genAgentParkForPopout(sess);
        }
      },
    });
  }
  actions.push({
    label: 'Restart session',
    title: 'Use if the terminal is frozen and Esc does nothing',
    run: () => _genAgentForceRestartTab(tabId, id, null),
  });
  const menu = document.createElement('div');
  menu.className = 'gtp-new-menu';
  menu.dataset.owner = 'tab:' + id;
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', 'Session actions');
  const items = actions.map((action) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'gtp-new-menu-item';
    item.setAttribute('role', 'menuitem');
    item.textContent = action.label;
    if (action.title) item.title = action.title;
    item.addEventListener('click', () => {
      close();
      void action.run();
    });
    menu.appendChild(item);
    return item;
  });
  const onOutside = (e) => {
    if (!menu.contains(e.target) && !anchor.contains(e.target)) close();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      anchor.focus();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const at = items.indexOf(document.activeElement);
      const step = e.key === 'ArrowDown' ? 1 : -1;
      items[(at + step + items.length) % items.length].focus();
    }
  };
  function close() {
    menu.remove();
    document.removeEventListener('mousedown', onOutside, true);
    document.removeEventListener('keydown', onKey, true);
    anchor.setAttribute('aria-expanded', 'false');
  }
  menu._close = close;
  document.addEventListener('mousedown', onOutside, true);
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(menu);
  const rect = anchor.getBoundingClientRect();
  const left = Math.min(rect.left, window.innerWidth - menu.offsetWidth - 4);
  menu.style.left = Math.max(4, left) + 'px';
  menu.style.top = rect.bottom + 2 + 'px';
  anchor.setAttribute('aria-expanded', 'true');
  items[0].focus();
}

// Same kill-and-respawn sequence the exit-restart overlay already uses
// (drop the dead/stuck session, spawn a fresh one in its place) - but
// reachable unconditionally from the tab strip, not gated behind the
// process having actually exited. See the kebab comment above.
function _genAgentForceRestartTab(tabId, ptySessionId, btn) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (!state) return;
  if (btn) {
    btn.disabled = true;
    btn.classList.add('gtp-tab-restart--busy');
  }
  void _genAgentRestartSession(tabId, ptySessionId).then((restarted) => {
    // On success the close/start path rebuilds the tab strip and replaces this
    // button. On a failed backend cleanup, restore the existing control so the
    // user can retry rather than leaving it permanently disabled.
    if (!restarted && btn) {
      btn.disabled = false;
      btn.classList.remove('gtp-tab-restart--busy');
    }
  });
}

// Tell the backend whether this terminal is on screen, so a background tab does
// not count as watched when it decides which idle terminals to suspend.
function _genAgentIsVisible(sess) {
  if (document.visibilityState === 'hidden') return false;
  if (sess._parked) return true;
  return !!(sess.container && sess.container.getClientRects().length);
}

function _genAgentReportVisible(sess, force) {
  if (!sess || !sess.ws || sess.ws.readyState !== WebSocket.OPEN) return;
  const visible = _genAgentIsVisible(sess);
  if (!force && sess._reportedVisible === visible) return;
  sess._reportedVisible = visible;
  sess.ws.send(JSON.stringify({ type: 'visible', value: visible }));
}

function _genAgentReportAllVisible() {
  Object.values(_genAgentTerminals).forEach((st) =>
    Object.values(st.sessions || {}).forEach((s) => _genAgentReportVisible(s)),
  );
}

document.addEventListener('visibilitychange', _genAgentReportAllVisible);
// Switching the Code project tab, opening a diff or file view, or changing Gator's
// main pane hides a terminal without any event this file sees; poll for it. Reports
// are deduped, and the backend's grace is far shorter than its idle threshold.
setInterval(_genAgentReportAllVisible, 15000);

// Show one session, hide the rest (hide, don't destroy - same as OpenCode).
function _genAgentActivateSession(tabId, ptyId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (!state) return;
  _genAgentHideStartPrompt(tabId);
  state.activeId = ptyId;
  state.order.forEach((id) => {
    const s = state.sessions[id];
    if (s && s.container) s.container.style.display = id === ptyId ? '' : 'none';
  });
  _genAgentUpdateActiveTab(tabId);
  _genAgentClearWokenMark(tabId, ptyId);
  state.order.forEach((id) => _genAgentReportVisible(state.sessions[id]));
  const sess = state.sessions[ptyId];
  if (sess) sess._viewedAt = Date.now();
  if (sess && sess.term)
    setTimeout(() => {
      _ocFit(sess);
      // If first output arrived while this session was in the background,
      // force a render now so its pending reveal can complete on activation.
      if (sess._hasOutput && !sess._revealed) {
        if (!sess._revealing) _genAgentRevealSession(sess);
        sess.term.refresh(0, Math.max(0, sess.term.rows - 1));
      }
      if (!_genAgentEditing) sess.term.focus();
    }, 20);
}

// "+" menu choice - always spawns an independent new process of the chosen
// agent. state.agent stays the project's agent so a cold reopen is unchanged.
function _genAgentNewSession(tabId, agent) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (!state || !state.agent) return;
  _genAgentStart(tabId, agent, state.projectId, state.repoPath, {
    forceNew: true,
    keepStateAgent: true,
  });
}

const _GEN_NEW_TAB_AGENTS = ['claude', 'codex', 'crush', 'opencode-bare'];

function _genAgentCloseNewMenu() {
  document.querySelectorAll('.gtp-new-menu').forEach((el) => {
    if (typeof el._close === 'function') el._close();
    else el.remove();
  });
}

// "+" opens this menu; the active tab's agent is pre-focused so Enter repeats it.
function _genAgentOpenNewMenu(tabId, anchor) {
  if (document.querySelector('.gtp-new-menu')) {
    _genAgentCloseNewMenu();
    return;
  }
  const menu = document.createElement('div');
  menu.className = 'gtp-new-menu';
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', 'New terminal with');
  const items = [];
  const addItem = (agent, before = null) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'gtp-new-menu-item';
    item.setAttribute('role', 'menuitem');
    item.appendChild(_genAgentTabIcon(agent));
    const name = document.createElement('span');
    name.className = 'gtp-new-menu-label';
    name.textContent = _genAgentLabel(agent);
    item.appendChild(name);
    item.addEventListener('click', () => {
      close();
      if (typeof _caCloseFileDiffIfOpen === 'function') _caCloseFileDiffIfOpen();
      _genAgentNewSession(tabId, agent);
    });
    item.dataset.agent = agent;
    menu.insertBefore(item, before);
    items.push(item);
    return item;
  };
  _GEN_NEW_TAB_AGENTS.forEach((agent) => addItem(agent));
  // Detected agents are inserted above this divider; the plain shell stays
  // below it for people who want their own machine's setup.
  const divider = document.createElement('div');
  divider.className = 'gtp-new-menu-sep';
  divider.setAttribute('role', 'separator');
  menu.appendChild(divider);
  addItem('terminal');
  const onOutside = (e) => {
    if (!menu.contains(e.target) && !anchor.contains(e.target)) close();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      anchor.focus();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const enabled = items.filter((i) => !i.disabled);
      if (!enabled.length) return;
      const at = enabled.indexOf(document.activeElement);
      const step = e.key === 'ArrowDown' ? 1 : -1;
      enabled[(at + step + enabled.length) % enabled.length].focus();
    }
  };
  function close() {
    menu.remove();
    document.removeEventListener('mousedown', onOutside, true);
    document.removeEventListener('keydown', onKey, true);
    anchor.setAttribute('aria-expanded', 'false');
  }
  menu._close = close;
  document.addEventListener('mousedown', onOutside, true);
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(menu);
  const rect = anchor.getBoundingClientRect();
  const left = Math.min(rect.left, window.innerWidth - menu.offsetWidth - 4);
  menu.style.left = Math.max(4, left) + 'px';
  menu.style.top = rect.bottom + 2 + 'px';
  anchor.setAttribute('aria-expanded', 'true');
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  const active = state && _genAgentActiveSess(state);
  const current = (active && active.agent) || (state && state.agent);
  (items.find((item) => item.dataset.agent === current) || items[0]).focus();
  void _genAgentMarkMissingInMenu(menu, items, (agent) => addItem(agent, divider));
}

// Rows open enabled and are disabled once the check returns, so a slow or
// failed lookup never blocks starting an agent. Other catalog agents are
// listed below the core ones only when they are installed.
async function _genAgentMarkMissingInMenu(menu, items, addItem) {
  let installed;
  let routed;
  try {
    const doFetch = typeof _ocFetch === 'function' ? _ocFetch : fetch;
    const headers = await _caHeadersAsync();
    const resp = await doFetch('/api/generic-agent/installed', { headers });
    if (!resp.ok) return;
    const body = await resp.json();
    installed = body.installed || {};
    routed = body.gateway_routed || {};
  } catch (_) {
    return;
  }
  if (!menu.isConnected) return;
  items.slice().forEach((item) => {
    const agent = item.dataset.agent;
    if (installed[agent] !== false) return;
    item.disabled = true;
    item.querySelector('.gtp-new-menu-label').textContent =
      _genAgentLabel(agent) + ' (not installed)';
  });
  Object.keys(_GEN_EXTRA_AGENT_LABELS)
    .filter((a) => installed[a] === true)
    .forEach(addItem);
  items.forEach((item) => {
    if (item.disabled || routed[item.dataset.agent] !== false) return;
    const badge = document.createElement('span');
    badge.className = 'gtp-new-menu-badge';
    badge.textContent = 'Unmanaged';
    badge.title = 'Runs on its own configuration, outside the AI Gator gateway';
    item.appendChild(badge);
  });
  if (document.activeElement && document.activeElement.disabled) {
    const first = items.find((item) => !item.disabled);
    if (first) first.focus();
  }
}

// "✕" - detach one session; activate a neighbor, or fall back to the start
// prompt if it was the last one.
async function _genAgentCloseBackendSession(state, sess) {
  if (!state || !sess || !sess.ptySessionId) return false;
  try {
    const headers =
      typeof _caHeadersAsync === 'function'
        ? await _caHeadersAsync()
        : { 'Content-Type': 'application/json' };
    const response = await _ocFetch('/api/generic-agent/terminal', {
      method: 'DELETE',
      headers,
      body: JSON.stringify({
        agent: sess.agent || state.agent,
        project_id: state.projectId,
        pty_session_id: sess.ptySessionId,
      }),
    });
    return response.ok;
  } catch (_) {
    // The UI close is local and immediate. A failed cleanup request is safe:
    // the backend will still reap the detached PTY by its normal lifecycle.
    return false;
  }
}

function _genAgentCloseSession(tabId, ptyId, backendAlreadyClosed = false) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (!state) return;
  const idx = state.order.indexOf(ptyId);
  const closing = state.sessions[ptyId];
  // Unlike a project switch, an explicit × means close the process too, so
  // this session cannot be reattached and resurrect its tab later.
  if (!backendAlreadyClosed) void _genAgentCloseBackendSession(state, closing);
  if (closing && closing._parked) void window.gatorShell.closeTerminalPopout(ptyId);
  _genAgentDetachSession(tabId, ptyId);
  state.order = state.order.filter((id) => id !== ptyId);
  if (state.order.length === 0) {
    state.activeId = null;
    _genAgentRenderTabs(tabId);
    _genAgentShowStartPrompt(tabId, state.agent, state.projectId, state.repoPath);
    return;
  }
  const next = state.order[Math.min(idx, state.order.length - 1)];
  _genAgentActivateSession(tabId, next);
  // Rebuild after the active session has changed. This makes the strip's DOM
  // exactly match state.order, so the detached tab cannot remain visible.
  _genAgentRenderTabs(tabId);
}

async function _genAgentRestartSession(tabId, ptyId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  const sess = state && state.sessions[ptyId];
  if (!state || !sess || sess._restarting) return false;
  sess._restarting = true;
  const hadOthers = (state.order || []).filter((id) => id !== ptyId).length > 0;
  const cleanedUp = await _genAgentCloseBackendSession(state, sess);
  if (!cleanedUp) {
    sess._restarting = false;
    return false;
  }
  _genAgentCloseSession(tabId, ptyId, true);
  _genAgentStart(tabId, sess.agent || state.agent, state.projectId, state.repoPath, {
    forceNew: hadOthers,
    keepStateAgent: sess.agent !== state.agent,
    resumeId: sess._resumeId || undefined,
  });
  return true;
}

function _genAgentShowStartPrompt(tabId, agent, projectId, repoPath, errMsg, resumeId) {
  const state = _genAgentEnsureTermsContainer(tabId);
  if (!state) return;
  state.agent = agent;
  state.projectId = projectId;
  state.repoPath = repoPath;
  const active = _genAgentActiveSess(state);
  if (active && active.container) active.container.style.display = 'none';
  _genAgentHideLoadingState(tabId);
  let el = state.termsEl.querySelector('.oc-start-prompt');
  if (!el) {
    el = document.createElement('div');
    el.id = _genAgentPromptId(tabId);
    el.className = 'gtp-term oc-start-prompt';
    state.termsEl.appendChild(el);
  }
  el.style.display = '';
  const isBareTerminal = agent === 'terminal';
  const agentLabel = _genAgentLabel(agent);
  const busy = state._starting === true;
  const busyLabel = isBareTerminal ? 'Opening…' : 'Starting…';
  const idleLabel = isBareTerminal ? 'Open' : resumeId ? 'Resume' : 'Start';
  const title = isBareTerminal ? 'Open a terminal' : 'Start ' + agentLabel;
  const sub = isBareTerminal
    ? 'Open a plain shell in ' + projectId + "'s directory - run any tool you like."
    : 'Launch ' + agentLabel + ' for ' + projectId + ' using its own installed config.';
  el.innerHTML =
    '<div class="oc-start-card">' +
    '<div class="oc-start-icon">&lt;/&gt;</div>' +
    '<div class="oc-start-title">' +
    escapeHtml(title) +
    '</div>' +
    '<div class="oc-start-sub">' +
    escapeHtml(sub) +
    '</div>' +
    (errMsg ? '<div class="oc-start-err">' + escapeHtml(String(errMsg)) + '</div>' : '') +
    '<button type="button" class="oc-start-btn' +
    (busy ? ' oc-start-btn--busy' : '') +
    '"' +
    (busy ? ' disabled' : '') +
    '>' +
    '<span class="oc-start-btn-spinner"></span>' +
    '<span class="oc-start-btn-label">' +
    escapeHtml(busy ? busyLabel : idleLabel) +
    '</span>' +
    '</button>' +
    '</div>';
  const btn = el.querySelector('.oc-start-btn');
  btn.addEventListener('click', () => {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.classList.add('oc-start-btn--busy');
    btn.querySelector('.oc-start-btn-label').textContent = busyLabel;
    // Same one-tick defer as the OpenCode prompt: _genAgentStart hides this
    // button synchronously before its first await, so calling it in the same
    // tick would never let the busy state paint.
    // A failed resume retries the same stored session, never a fresh one.
    setTimeout(
      () => _genAgentStart(tabId, agent, projectId, repoPath, resumeId ? { resumeId } : undefined),
      0,
    );
  });
}

function _genAgentHideStartPrompt(tabId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  const prompt = state && state.termsEl && state.termsEl.querySelector('.oc-start-prompt');
  prompt?.remove();
}

const _GENAGENT_LOADING_TIPS = [
  'Waking up the compiler',
  'Cloning into the swamp',
  'Untangling imports',
  'Warming up the REPL',
];

function _genAgentShowLoadingState(tabId, ownerEl) {
  const state = _genAgentEnsureTermsContainer(tabId);
  if (!state) return;
  // See tp-term-helpers.js's _ocShowLoadingState for the bug this
  // guards against: a stale Start/Resume prompt re-rendered mid-dispatch
  // (chat-tab switch, pane reopen) is never removed by the success path
  // otherwise, and sits on top of the now-live terminal forever.
  _genAgentHideStartPrompt(tabId);
  const active = _genAgentActiveSess(state);
  if (active && active.container) active.container.style.display = 'none';
  const owner = ownerEl || state.termsEl;
  let el = owner.querySelector('.oc-loading-term');
  if (!el) {
    el = document.createElement('div');
    el.id = _genAgentLoadingId(tabId);
    el.className = 'gtp-term oc-loading-term';
    owner.appendChild(el);
  }
  el.style.display = '';
  el.innerHTML = typeof _gatorLoading === 'function' ? _gatorLoading(_GENAGENT_LOADING_TIPS) : '';
}

function _genAgentHideLoadingState(tabId, ownerEl) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  const owner = ownerEl || (state && state.termsEl);
  if (!owner) return;
  owner.querySelectorAll('.oc-loading-term').forEach((loading) => loading.remove());
}

// opts.forceNew: this is the "+" button - add a tab, never reattach an
// existing PTY (each tab is its own process).
async function _genAgentStart(tabId, agent, projectId, repoPath, opts) {
  opts = opts || {};
  const state = _genAgentEnsureTermsContainer(tabId);
  if (!state) return;
  if (state._starting) return;
  const stateAgent = opts.keepStateAgent ? state.agent : agent;
  state.agent = stateAgent;
  state.projectId = projectId;
  state.repoPath = repoPath;
  _genAgentHideStartPrompt(tabId);
  state._starting = true;
  // These must be function-scoped so the failure path can dispose/remove a
  // terminal created before the spawn request rejects (for example when
  // Codex is not installed). Block-scoped declarations inside try left an
  // orphaned blank xterm covering the restored error prompt.
  let container = null;
  let sess = null;
  try {
    // Create the xterm terminal + container BEFORE the fetch so we can measure
    // its dimensions and spawn the PTY at the correct size. Without this, TUI
    // apps (Crush, Claude Code) paint at the default 220x24 and garble when
    // the late resize arrives after the first frame.
    container = document.createElement('div');
    container.className = 'gtp-term';
    container.style.display = '';
    state.termsEl.appendChild(container);
    state.seq += 1;
    const isBareTerminal = agent === 'terminal';
    const base = isBareTerminal ? 'Terminal' : _genAgentLabel(agent);
    sess = {
      tabId,
      ptySessionId: null,
      container,
      agent,
      label: base + ' ' + state.seq,
      _retryDelay: 0,
    };
    _ocSpawnTerm(sess);
    // Loading belongs to this session container, not the shared .gtp-terms
    // wrapper. Switching to another terminal hides this container and its
    // overlay together, so one session can never cover another.
    _genAgentShowLoadingState(tabId, container);
    // Fit once after layout so cols/rows are real, then send them with the
    // spawn request. rAF ensures the browser has computed the container's
    // width before we measure.
    const dims = await new Promise((resolve) => {
      requestAnimationFrame(() => {
        _ocFit(sess);
        const c = sess.term ? sess.term.cols : 0;
        const r = sess.term ? sess.term.rows : 0;
        resolve({ cols: c, rows: r });
      });
    });

    const headers =
      typeof _caHeadersAsync === 'function'
        ? await _caHeadersAsync()
        : { 'Content-Type': 'application/json' };
    const resp =
      typeof _ocFetch === 'function'
        ? await _ocFetch('/api/generic-agent/terminal', {
            method: 'POST',
            headers,
            body: JSON.stringify({
              agent,
              project_id: projectId,
              repo_path: repoPath,
              force_new: !!opts.forceNew,
              cols: dims.cols,
              rows: dims.rows,
              handoff_id: opts.handoffId,
              resume_id: opts.resumeId,
            }),
          })
        : await fetch('/api/generic-agent/terminal', {
            method: 'POST',
            headers,
            body: JSON.stringify({
              agent,
              project_id: projectId,
              repo_path: repoPath,
              force_new: !!opts.forceNew,
              cols: dims.cols,
              rows: dims.rows,
              handoff_id: opts.handoffId,
              resume_id: opts.resumeId,
            }),
          });
    if (!resp.ok) {
      let detail = 'Could not start ' + agent;
      try {
        const d = await resp.json();
        if (d && d.detail) detail = d.detail;
      } catch (_) {}
      throw new Error(detail);
    }
    const data = await resp.json();
    // Staleness guard: bail without attaching if the user has since switched
    // this tab to a different project OR a different agent while the request
    // was in flight (both replace/repoint this tab's state).
    const current = _genAgentTerminals[_caSessionKey(tabId)];
    if (!current || current.projectId !== projectId || current.agent !== stateAgent) {
      // Clean up the pre-created terminal
      try {
        sess.term && sess.term.dispose();
      } catch (_) {}
      try {
        container.remove();
      } catch (_) {}
      return;
    }
    // Do NOT hide the loading state here. The spawn POST returns almost
    // instantly (~0.3s), but a shell's FIRST paint doesn't arrive until the
    // process is up and has emitted its prompt (~3-4s for PowerShell cold). If
    // we hid loading now, the user would stare at an empty terminal container
    // for those seconds - which reads as "blank/broken", the exact symptom
    // reported. Loading stays up until first output arrives, at which point
    // _genAgentRevealSession (in the WS onmessage handler) hides it and shows
    // the painted terminal.
    //
    // Keep the terminal container VISIBLE (display:'') so xterm's canvas
    // composites and _ocFit measures real dimensions. The loading overlay is
    // layered on top via CSS (oc-loading-term uses position:absolute + z-index)
    // so the user sees the spinner, not the empty canvas behind it.
    // (Previous attempts used display:none or visibility:hidden; both caused
    // _ocFit to bail on zero clientWidth/offsetParent, making TUI apps like
    // opencode render at the wrong size or blank on first visit.)
    // Attach: register the session, connect the WebSocket, wire the resize
    // observer. The terminal + container are already created above.
    sess.ptySessionId = data.pty_session_id;
    state.sessions[data.pty_session_id] = sess;
    state.order.push(data.pty_session_id);
    state.activeId = data.pty_session_id;
    _genAgentConnect(sess);
    if (data.handoff_prompt && window.agentHandoff) {
      sess._handedOffAt = Date.now();
      void window.agentHandoff.deliver(sess, data.handoff_prompt);
    }
    _ocGuardSize(sess);
    _genAgentRenderTabs(tabId);
  } catch (err) {
    // Clean up the pre-created terminal
    try {
      sess && sess.term && sess.term.dispose();
    } catch (_) {}
    try {
      container && container.remove();
    } catch (_) {}
    _genAgentHideLoadingState(tabId, container);
    const current = _genAgentTerminals[_caSessionKey(tabId)];
    if (current && current.projectId === projectId && current.agent === stateAgent) {
      // Clear the in-flight flag BEFORE re-rendering: _genAgentShowStartPrompt
      // reads _starting to decide whether the button renders busy (disabled +
      // spinning), and the finally below runs after this render. Without this,
      // a failed start (notably a not-installed Codex/Crush) would show the
      // error text inside a permanently stuck spinner instead of a clickable
      // retry. Same bug fixed in _ocStartOrResume.
      current._starting = false;
      // Only fall back to the full-pane prompt if there are no other live
      // sessions - if a "+" spawn failed, keep the existing tabs and surface
      // the error rather than blowing away the working terminals.
      if (current.order.length === 0) {
        _genAgentShowStartPrompt(
          tabId,
          stateAgent,
          projectId,
          repoPath,
          (err && err.message) || 'Could not start ' + agent,
          opts.resumeId,
        );
      } else {
        if (typeof addMessage === 'function')
          addMessage('assistant', '⚠️ ' + ((err && err.message) || 'Could not start ' + agent));
        const active = _genAgentActiveSess(current);
        if (active) _genAgentActivateSession(tabId, active.ptySessionId);
      }
    }
  } finally {
    if (state._starting) state._starting = false;
  }
}

function _genAgentAttachTerminal(tabId, ptySessionId, agent) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (!state) return;
  // Already have this exact session live (reattach on cold reopen) - just show it.
  if (state.sessions[ptySessionId] && state.sessions[ptySessionId].term) {
    _genAgentActivateSession(tabId, ptySessionId);
    return;
  }
  const container = document.createElement('div');
  container.className = 'gtp-term';
  // Visible immediately (not display:none) so xterm initializes with real
  // dimensions and _ocFit on ws.onopen can send the correct size BEFORE the
  // TUI app paints. Hiding the container until first output (the prior
  // approach) meant _ocFit bailed on offsetParent===null, the PTY stayed at
  // its default 220x24, and TUI apps (Crush, Claude Code) rendered their
  // layout at the wrong size — the late resize on first output then garbled
  // the already-painted screen. The loading overlay covers the empty terminal
  // during cold start.
  container.style.display = '';
  state.termsEl.appendChild(container);

  state.seq += 1;
  const isBareTerminal = agent === 'terminal';
  const base = isBareTerminal ? 'Terminal' : _genAgentLabel(agent);
  const sess = {
    tabId,
    ptySessionId,
    container,
    agent,
    label: base + ' ' + state.seq,
    _retryDelay: 0,
  };
  state.sessions[ptySessionId] = sess;
  state.order.push(ptySessionId);
  state.activeId = ptySessionId;
  _ocSpawnTerm(sess); // shared, session-agnostic xterm setup (see file header)
  // Fit synchronously so xterm measures the real container dimensions and
  // sends the correct resize to the PTY BEFORE the WebSocket connects and
  // Crush starts painting. A requestAnimationFrame defer lets the browser
  // compute layout (the container was just appended) without yielding to
  // Crush's output pump. The ws.onopen _ocFit is a belt-and-suspenders
  // re-fit in case the rAF ran before layout completed.
  requestAnimationFrame(() => {
    _ocFit(sess);
    _genAgentConnect(sess);
  });
  _ocGuardSize(sess); // shared ResizeObserver wiring
  _genAgentRenderTabs(tabId);
}

const _GENAGENT_OPENCODE_PAINT_STABLE_MS = 600;

// Read-only view of "a start is in flight for this tab", for agent-handoff.js.
function _genAgentStartInFlight(tabId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  return !!(state && state._starting);
}

function _genAgentPaintedRowCount(sess) {
  const term = sess && sess.term;
  const buffer = term && term.buffer && term.buffer.active;
  if (!term || !buffer) return 0;
  const start = Math.max(0, buffer.viewportY || 0);
  let painted = 0;
  for (let row = 0; row < term.rows; row += 1) {
    const line = buffer.getLine(start + row);
    if (line && line.translateToString(true).trim()) painted += 1;
  }
  return painted;
}

function _genAgentOpenCodeFrameIsReady(sess) {
  const term = sess && sess.term;
  const buffer = term && term.buffer && term.buffer.active;
  if (!term || !buffer) return false;
  // OpenCode is a full-screen TUI. Its startup preamble may briefly paint a
  // word or two before clearing the screen, so one rendered line is not a
  // readiness signal. Require a real multi-row frame in the alternate buffer.
  // The byte fallback covers xterm builds that do not expose buffer.type.
  const hasTuiContent = _genAgentPaintedRowCount(sess) >= Math.min(4, term.rows);
  const isAlternate = buffer.type === 'alternate';
  return hasTuiContent && (isAlternate || (sess._outputChars || 0) >= 1024);
}

function _genAgentRevealSession(sess) {
  if (!sess) return;
  const state = _genAgentTerminals[_caSessionKey(sess.tabId)];
  // Background sessions must still finish their reveal lifecycle so their
  // session-owned loading overlay is removed before the user returns. They
  // must not, however, become visible or steal focus until activated.
  if (!state || state.sessions[sess.ptySessionId] !== sess) return;
  if (sess._revealing || sess._revealed) return;
  sess._revealing = true;

  // term.write() is asynchronous. Wait for xterm's render event instead of
  // treating queued bytes as a completed first paint. OpenCode needs a
  // stronger gate: its startup preamble can render, clear the alternate
  // screen, then leave it blank for several seconds before the real TUI.
  const reveal = () => {
    clearTimeout(sess._paintReadyTimer);
    try {
      sess._revealRenderDisposable && sess._revealRenderDisposable.dispose();
    } catch (_) {}
    sess._revealRenderDisposable = null;
    try {
      sess._revealWriteDisposable && sess._revealWriteDisposable.dispose();
    } catch (_) {}
    sess._revealWriteDisposable = null;
    sess._revealing = false;
    const current = _genAgentTerminals[_caSessionKey(sess.tabId)];
    if (!current || current.sessions[sess.ptySessionId] !== sess || sess._closing) return;
    sess._revealed = true;
    _genAgentHideLoadingState(sess.tabId, sess.container);
    if (current.activeId === sess.ptySessionId) {
      _genAgentHideStartPrompt(sess.tabId);
      if (sess.container) sess.container.style.display = '';
      // The render event confirms xterm consumed the queued output; redraw
      // once after removing the overlay so the exposed canvas is flushed too.
      if (sess.term && sess.term.rows > 0) sess.term.refresh(0, sess.term.rows - 1);
      sess.term && sess.term.focus();
    }
  };

  if (sess.term && typeof sess.term.onRender === 'function') {
    const checkFrame = () => {
      if (sess.agent !== 'opencode-bare') {
        reveal();
        return;
      }
      if (!_genAgentOpenCodeFrameIsReady(sess)) {
        clearTimeout(sess._paintReadyTimer);
        sess._paintReadyTimer = null;
        return;
      }
      // A transitional frame can be immediately cleared. Keep the overlay up
      // until the meaningful frame remains present for a short stability
      // window, rechecking the live buffer before revealing it.
      if (!sess._paintReadyTimer) {
        sess._paintReadyTimer = setTimeout(() => {
          sess._paintReadyTimer = null;
          if (_genAgentOpenCodeFrameIsReady(sess)) reveal();
        }, _GENAGENT_OPENCODE_PAINT_STABLE_MS);
      }
    };
    sess._revealRenderDisposable = sess.term.onRender(checkFrame);
    // A hidden background container may not emit renderer events, but xterm
    // still parses its queued writes. Inspect the buffer after parsing too so
    // OpenCode can complete and remove its hidden overlay off-DOM/off-screen.
    if (sess.agent === 'opencode-bare' && typeof sess.term.onWriteParsed === 'function') {
      sess._revealWriteDisposable = sess.term.onWriteParsed(checkFrame);
    }
    checkFrame();
    sess.term.refresh(0, Math.max(0, sess.term.rows - 1));
  } else {
    reveal();
  }
}

function _genAgentDetachSession(tabId, ptyId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  const sess = state && state.sessions[ptyId];
  if (!sess) return;
  sess._closing = true;
  clearTimeout(sess._resizeDebounce);
  clearTimeout(sess._noOutputTimer);
  clearTimeout(sess._paintReadyTimer);
  try {
    sess._revealRenderDisposable && sess._revealRenderDisposable.dispose();
  } catch (_) {}
  try {
    sess._revealWriteDisposable && sess._revealWriteDisposable.dispose();
  } catch (_) {}
  try {
    sess._sizeObserver && sess._sizeObserver.disconnect();
  } catch (_) {}
  try {
    sess.ws && sess.ws.close();
  } catch (_) {}
  _genAgentWokenDrop(sess);
  try {
    sess.term && sess.term.dispose();
  } catch (_) {}
  try {
    sess.container && sess.container.remove();
  } catch (_) {}
  delete state.sessions[ptyId];
}

// Full teardown for this tab - detaches every session, removes the wrapper
// AND the header strip, mirroring _ocDetachAllForTab. Used when leaving this
// agent entirely (e.g. switching the project to a different agent).
function _genAgentDetachAllForTab(tabId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  if (!state) return;
  (state.order || []).slice().forEach((id) => _genAgentDetachSession(tabId, id));
  try {
    state.termsEl && state.termsEl.remove();
  } catch (_) {}
  _genAgentRemoveHeaderTabStrip();
  delete _genAgentTerminals[_caSessionKey(tabId)];
}

// Same watchdog pattern as the generic terminal -
// a spawned process can succeed at the HTTP layer but wedge without ever
// writing output, and the server's PTY-read pump then blocks forever too, so
// no 'exit' message arrives either. Every agent here (Claude Code CLI, a
// bare shell, etc.) paints something immediately on a working start - none
// of them wait on an LLM call before that - so "no output yet" is a safe
// signal, not something that would misfire on a merely-slow start. Scoped to
// "waiting for the very first output this session has EVER produced" - never
// re-armed once sess._hasOutput is true, so a legitimately idle session is
// never mistaken for a hang.
const _GENAGENT_NO_OUTPUT_TIMEOUT_MS = 30000;

// Does this chunk actually PAINT anything, or is it only terminal mode-setting?
//
// The watchdog above exists to catch "the terminal never painted", but it used
// to disarm on any bytes at all - which a broken PTY defeats. A PTY whose spawn
// half-succeeds emits its mode-setting preamble (e.g. '\x1b[?9001h\x1b[?1004h
// \x1b[2t' - 20 bytes, zero printable characters) and then dies. That counted as
// "output", disarmed the watchdog, and revealed the pane, so the user got a
// blank terminal with no error and no restart affordance. Observed for real when
// pywinpty's helper executables were missing from the packaged build.
//
// Strip escape sequences and require at least one non-whitespace character
// before treating output as a genuine first paint.
function _genAgentIsVisibleOutput(data) {
  if (!data) return false;
  const stripped = String(data)
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '') // OSC ... BEL / ST
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '') // CSI
    .replace(/\x1b[()][0-9A-Za-z]/g, '') // charset selection
    .replace(/\x1b./g, ''); // any remaining 2-byte escape
  return /\S/.test(stripped);
}

function _genAgentArmNoOutputWatchdog(sess) {
  clearTimeout(sess._noOutputTimer);
  sess._noOutputTimer = setTimeout(() => {
    if (sess._hasOutput || sess._closing || sess._dead) return;
    const state = _genAgentTerminals[_caSessionKey(sess.tabId)];
    if (!state) return;
    void _genAgentRestartSession(sess.tabId, sess.ptySessionId);
  }, _GENAGENT_NO_OUTPUT_TIMEOUT_MS);
}

// A PTY has one size, so a terminal shown in two windows garbles whichever
// window did not set it. While a tab is popped out the pop-out owns the PTY:
// this tab disconnects, stops resizing, and shows a placeholder.
function _genAgentParkForPopout(sess) {
  if (sess._parked || !sess.container) return;
  sess._parked = true;
  clearTimeout(sess._noOutputTimer);
  try {
    sess.ws && sess.ws.close();
  } catch (_) {}
  const overlay = document.createElement('div');
  overlay.className = 'oc-restart-overlay';
  const msg = document.createElement('div');
  msg.className = 'oc-restart-msg';
  msg.textContent = 'This terminal is open in a separate window.';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'oc-restart-btn';
  btn.textContent = 'Bring back';
  btn.addEventListener('click', () => {
    btn.disabled = true;
    void window.gatorShell.closeTerminalPopout(sess.ptySessionId).then((closed) => {
      if (!closed) _genAgentUnparkFromPopout(sess);
    });
  });
  overlay.appendChild(msg);
  overlay.appendChild(btn);
  sess.container.appendChild(overlay);
  sess._popoutOverlay = overlay;
}

// The pop-out is gone. Start from a blank screen at this tab's own size and
// from the live end of the output, then force the app to redraw itself.
function _genAgentUnparkFromPopout(sess) {
  if (!sess._parked) return;
  sess._parked = false;
  if (sess._popoutOverlay) sess._popoutOverlay.remove();
  sess._popoutOverlay = null;
  if (!sess.term || sess._closing || sess._dead) return;
  sess.term.reset();
  sess._outputSeq = -1;
  sess._retryAttempt = 0;
  sess._redrawOnOpen = true;
  _genAgentConnect(sess, 0);
}

function _genAgentOnPopoutClosed(ptySessionId) {
  Object.values(_genAgentTerminals).forEach((state) => {
    const sess = state.sessions && state.sessions[ptySessionId];
    if (sess) _genAgentUnparkFromPopout(sess);
  });
}

if (window.gatorShell && typeof window.gatorShell.onTerminalPopoutClosed === 'function') {
  window.gatorShell.onTerminalPopoutClosed(_genAgentOnPopoutClosed);
}

// WebSocket connect/reconnect - same shape as _ocConnect: the exit vs.
// transient-drop distinction, backoff, and restart affordance are generically
// useful, not OpenCode-specific.
function _genAgentConnect(sess, retryDelay) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url =
    proto +
    '//' +
    location.host +
    '/api/terminal/agent?session_id=' +
    encodeURIComponent(sess.ptySessionId) +
    '&seq=' +
    (sess._outputSeq || 0);
  const wasRetrying = !!retryDelay;

  sess.ws = new WebSocket(url);
  sess.ws.onopen = () => {
    _ocNoteEcho(sess);
    _genAgentClearReconnecting(sess);
    _genAgentReportVisible(sess, true);
    if (wasRetrying && sess._retryAttempt) {
      // Don't write [reconnected] text into the terminal - for TUI apps like
      // opencode it injects text into the alternate screen and corrupts the
      // layout. Instead send a resize event to force the TUI to fully redraw.
      if (sess.term && sess.ws.readyState === WebSocket.OPEN) {
        sess.ws.send(
          JSON.stringify({ type: 'resize', cols: sess.term.cols, rows: sess.term.rows }),
        );
      }
    }
    _ocFit(sess);
    if (sess._redrawOnOpen && sess.term) {
      // Back from a pop-out: the PTY may already be this size, and a resize to
      // the same size makes no app redraw. Nudge it so the app repaints.
      sess._redrawOnOpen = false;
      const { cols, rows } = sess.term;
      const resize = (c) => sess.ws.send(JSON.stringify({ type: 'resize', cols: c, rows }));
      resize(Math.max(cols - 1, 2));
      resize(cols);
    }
    // The wake watch re-attaches a suspended tab every few seconds; it must not take focus.
    if (!sess._resumeId) sess.term && sess.term.focus();
    if (!sess._hasOutput) _genAgentArmNoOutputWatchdog(sess);
  };
  sess.ws.onmessage = (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (msg.type === 'output') {
      // Position in the PTY's output stream, so a reconnect resumes after what
      // this terminal already shows instead of replaying the whole buffer.
      if (typeof msg.seq === 'number') sess._outputSeq = msg.seq;
      sess._outputChars = (sess._outputChars || 0) + String(msg.data || '').length;
      sess._lastRawOutputAt = Date.now();
      if (Date.now() >= (sess._quietUntil || 0) && window.agentHistory) {
        agentHistory.noteOutput(sess, Date.now());
        if (agentHistory.isViewing(sess)) sess._viewedAt = sess._lastOutputAt;
      }
      if (window.agentHandoff) {
        // Whether the agent has switched bracketed paste on (ESC[?2004h); the
        // handoff prompt is only drafted into a terminal that has.
        const paste = agentHandoff.trackBracketedPaste(
          { enabled: sess._bracketedPaste, tail: sess._bracketedPasteTail || '' },
          msg.data,
        );
        sess._bracketedPaste = paste.enabled;
        sess._bracketedPasteTail = paste.tail;
      }
      if (window.agentLimitDetect && window.agentHandoff) {
        window.agentLimitDetect.feed(sess, msg.data, (s) => agentHandoff.offerOnLimit(s));
      }
      const hasVisibleOutput = _genAgentIsVisibleOutput(msg.data);
      // A WebSocket opening only proves it reached the backend. Keep retrying
      // through `notready` responses until the PTY produces real visible
      // output; resetting in onopen made every notready reconnect start back
      // at attempt one and hid the restart affordance forever.
      if (hasVisibleOutput) sess._retryAttempt = 0;
      // Always write - mode-setting sequences still have to reach the terminal.
      // Only a chunk that paints something counts as the session having started,
      // so a PTY that emits its preamble and dies can't disarm the watchdog.
      if (!sess._hasOutput && hasVisibleOutput) {
        sess._hasOutput = true;
        clearTimeout(sess._noOutputTimer);
        // write() is queued by xterm. Its callback runs only after these
        // bytes have been parsed, so _genAgentRevealSession can subscribe to
        // the subsequent real canvas render rather than an empty refresh.
        if (sess.term) sess.term.write(msg.data, () => _genAgentRevealSession(sess));
        else _genAgentRevealSession(sess);
      } else {
        sess.term && sess.term.write(msg.data);
      }
    } else if (msg.type === 'truncated') {
      // The replay starts mid-stream (the buffer dropped older output), so what
      // follows can open inside an escape sequence. Clear the screen and nudge
      // the size so the TUI repaints itself in full.
      if (sess.term) {
        sess.term.reset();
        const { cols, rows } = sess.term;
        const resize = (c) => sess.ws.send(JSON.stringify({ type: 'resize', cols: c, rows }));
        resize(Math.max(cols - 1, 2));
        resize(cols);
      }
    } else if (msg.type === 'notready') {
      // Transient: PTY not spawned yet, or reaped while we held its id. Do NOT
      // set _dead — onclose then runs the normal backoff reconnect. After a few
      // attempts the id is genuinely gone (backend restart / idle reap), so ask
      // for a fresh session instead of reattaching to an id that can't return.
      if ((sess._retryAttempt || 0) >= 3 && !sess._respawned) {
        sess._respawned = true;
        sess._dead = true;
        clearTimeout(sess._noOutputTimer);
        _genAgentShowRestartOverlay(sess, 'Session expired — restart to reconnect');
      }
    } else if (msg.type === 'suspended') {
      // Gator stopped this idle agent to free its memory. Restarting the tab
      // resumes the stored session instead of starting a fresh one.
      sess._dead = true;
      sess._resumeId = msg.session_id || null;
      // A wake restarts the stream under the same id, so the next attach replays it all.
      sess._outputSeq = 0;
      sess._awaitingWake = true;
      clearTimeout(sess._noOutputTimer);
      _genAgentShowRestartOverlay(sess, msg.data || 'Suspended - click to resume');
      if (msg.failed) _genAgentShowWakeFailure(sess, msg.failed);
      _genAgentWatchForWake(sess);
    } else if (msg.type === 'woken') {
      // Another agent woke this session: it is running again under the same id.
      sess._dead = false;
      sess._resumeId = null;
      clearTimeout(sess._wakeWatch);
      if (sess._awaitingWake && sess.term) sess.term.reset();
      sess._awaitingWake = false;
      const overlay = sess.container && sess.container.querySelector('.oc-restart-overlay');
      if (overlay) overlay.remove();
      _genAgentShowWokenBanner(sess, msg);
    } else if (msg.type === 'exit') {
      sess._dead = true;
      clearTimeout(sess._noOutputTimer);
      sess.term &&
        sess.term.write('\r\n\x1b[33m[' + (msg.data || 'Session ended') + ']\x1b[0m\r\n');
      _genAgentShowRestartOverlay(sess, msg.data || 'Session ended');
    }
  };
  sess.ws.onerror = () => {
    /* onclose handles retry */
  };
  sess.ws.onclose = () => {
    if (!sess.term || sess._closing || sess._dead || sess._parked) return;
    const attempt = (sess._retryAttempt || 0) + 1;
    sess._retryAttempt = attempt;
    const next = Math.min(500 * attempt, 8000);
    _genAgentShowReconnecting(sess, attempt);
    setTimeout(() => {
      if (!sess.term || sess._closing || sess._dead || sess._parked) return;
      _genAgentConnect(sess, next);
    }, next);
  };
}

// A transient banner, not text in the xterm buffer: written text outlived the
// reconnect and read as a permanent disconnect (and corrupts TUI screens).
function _genAgentShowReconnecting(sess, attempt) {
  if (!sess.container) return;
  let banner = sess.container.querySelector('.gtp-reconnect-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.className = 'gtp-reconnect-banner';
    banner.setAttribute('role', 'status');
    sess.container.appendChild(banner);
  }
  banner.textContent = attempt > 1 ? 'Reconnecting… (attempt ' + attempt + ')' : 'Reconnecting…';
}

function _genAgentClearReconnecting(sess) {
  const banner = sess.container && sess.container.querySelector('.gtp-reconnect-banner');
  if (banner) banner.remove();
}

const GEN_AGENT_WAKE_WATCH_MS = 5000;

// A suspended tab can be woken by another agent. Looking again every few seconds is
// cheap (the backend answers a suspended id with one small message) and lets the tab
// reattach to the session without the user clicking.
function _genAgentWatchForWake(sess) {
  clearTimeout(sess._wakeWatch);
  sess._wakeWatch = setTimeout(() => {
    if (!sess.term || sess._closing || sess._parked || sess._restarting || !sess._resumeId) return;
    _genAgentConnect(sess, 0);
  }, GEN_AGENT_WAKE_WATCH_MS);
}

function _genAgentShowWakeFailure(sess, failed) {
  const overlay = sess.container && sess.container.querySelector('.oc-restart-overlay');
  if (!overlay) return;
  const msgEl = overlay.querySelector('.oc-restart-msg');
  if (msgEl) msgEl.textContent = 'could not wake: ' + (failed.reason || 'unknown reason');
  if (failed.message && !overlay.querySelector('.oc-restart-kept')) {
    const kept = document.createElement('div');
    kept.className = 'oc-restart-msg oc-restart-kept';
    kept.textContent = 'Message from ' + (failed.sender || 'another agent') + ': ' + failed.message;
    msgEl.after(kept);
  }
}

const GEN_AGENT_WOKEN_MS = 8000;
const GEN_AGENT_WOKEN_FADE_MS = 150;

// A read-only status line saying why this agent started typing. The message itself is already
// in the terminal under its "from another agent" prefix, so it is never repeated here.
function _genAgentShowWokenBanner(sess, msg) {
  if (!sess.container) return;
  const at = Number(msg.at) || Date.now();
  // A reconnect replays the same wake; only a new wake is news.
  if (sess._wokenLastAt === at || _genAgentWokenSeenAt(sess) === String(at)) return;
  sess._wokenLastAt = at;
  const by = msg.by || String(msg.data || '').replace(/^woken by /i, '') || 'another agent';
  const existing = sess._woken;
  if (existing && existing.by === by) {
    existing.count += 1;
    existing.at = at;
    _genAgentWokenRenderText(existing);
    _genAgentWokenArm(sess);
    return;
  }
  if (existing) _genAgentWokenDrop(sess);

  const el = document.createElement('div');
  el.className = 'gtp-woken-strip';
  el.setAttribute('role', 'status');
  const dot = document.createElement('span');
  dot.className = 'gtp-woken-dot';
  dot.setAttribute('aria-hidden', 'true');
  const text = document.createElement('span');
  text.className = 'gtp-woken-text';
  const dismiss = document.createElement('button');
  dismiss.type = 'button';
  dismiss.className = 'gtp-woken-dismiss';
  dismiss.textContent = 'Dismiss';
  el.append(dot, text, dismiss);

  const w = { el, text, by, at, count: 1, timer: null, visible: false, held: false, io: null };
  sess._woken = w;
  dismiss.addEventListener('click', () => _genAgentWokenDismiss(sess, true));
  const hold = (held) => {
    w.held = held;
    _genAgentWokenArm(sess);
  };
  el.addEventListener('mouseenter', () => hold(true));
  el.addEventListener('mouseleave', () => hold(el.matches(':focus-within')));
  el.addEventListener('focusin', () => hold(true));
  el.addEventListener('focusout', () => hold(el.matches(':hover')));
  _genAgentWokenRenderText(w);

  sess.container.classList.add('gtp-term--woken');
  sess.container.appendChild(el);
  _ocFit(sess);

  // The timer starts only once the strip is actually on screen, so a wake that lands on a
  // background tab is still there when the user switches to it.
  if (typeof IntersectionObserver === 'function') {
    w.io = new IntersectionObserver((entries) => {
      w.visible = entries[entries.length - 1].isIntersecting;
      _genAgentWokenArm(sess);
    });
    w.io.observe(el);
  } else {
    w.visible = true;
    _genAgentWokenArm(sess);
  }
  _genAgentSetWokenMark(sess, by);
}

// The backend replays its wake notice on every connect, so a reload would show the strip again.
// Remember which wake the user has already had on screen long enough to read.
function _genAgentWokenSeenKey(sess) {
  return 'gtp-woken-seen:' + sess.ptySessionId;
}

function _genAgentWokenSeenAt(sess) {
  try {
    return sessionStorage.getItem(_genAgentWokenSeenKey(sess));
  } catch (_) {
    return null;
  }
}

function _genAgentWokenMarkSeen(sess, at) {
  try {
    sessionStorage.setItem(_genAgentWokenSeenKey(sess), String(at));
  } catch (_) {}
}

function _genAgentWokenRenderText(w) {
  const time = new Date(w.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const lead = document.createElement('span');
  lead.className = 'gtp-woken-lead';
  lead.textContent = 'Woken by ';
  const name = document.createElement('span');
  name.className = 'gtp-woken-name';
  name.textContent = w.by;
  name.title = w.by;
  const tail = document.createElement('span');
  tail.className = 'gtp-woken-tail';
  tail.textContent = ' · ' + time + (w.count > 1 ? ' (' + w.count + ' messages)' : '');
  w.text.replaceChildren(lead, name, tail);
}

function _genAgentWokenArm(sess) {
  const w = sess._woken;
  if (!w) return;
  clearTimeout(w.timer);
  w.timer = null;
  if (!w.visible || w.held) return;
  w.timer = setTimeout(() => _genAgentWokenDismiss(sess, false), GEN_AGENT_WOKEN_MS);
}

function _genAgentWokenDrop(sess) {
  const w = sess._woken;
  if (!w) return;
  clearTimeout(w.timer);
  if (w.io) w.io.disconnect();
  w.el.remove();
  sess._woken = null;
  if (sess.container) sess.container.classList.remove('gtp-term--woken', 'gtp-term--woken-leaving');
}

function _genAgentWokenDismiss(sess, immediate) {
  const w = sess._woken;
  if (!w) return;
  clearTimeout(w.timer);
  if (w.io) w.io.disconnect();
  sess._woken = null;
  _genAgentWokenMarkSeen(sess, w.at);
  const finish = () => {
    w.el.remove();
    if (sess.container) sess.container.classList.remove('gtp-term--woken', 'gtp-term--woken-leaving');
    _ocFit(sess);
  };
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (immediate || reduced || !sess.container) {
    finish();
    return;
  }
  sess.container.classList.add('gtp-term--woken-leaving');
  setTimeout(finish, GEN_AGENT_WOKEN_FADE_MS * 2);
}

// The only thing visible when the woken tab is not selected: a dot plus the word "Woken"
// (tooltip and screen-reader text), cleared when the user selects the tab.
function _genAgentDecorateWokenTab(tabEl, sess) {
  tabEl.querySelectorAll('.gtp-tab-woken').forEach((n) => n.remove());
  if (!sess._wokenMark) return;
  const mark = document.createElement('span');
  mark.className = 'gtp-tab-woken';
  const dot = document.createElement('span');
  dot.className = 'gtp-tab-woken-dot';
  dot.setAttribute('aria-hidden', 'true');
  const word = document.createElement('span');
  word.className = 'visually-hidden';
  word.textContent = 'Woken';
  mark.append(dot, word);
  const label = tabEl.querySelector('.gtp-tab-label');
  if (label) label.after(mark);
  tabEl.title = 'Woken by ' + sess._wokenMark;
}

function _genAgentSetWokenMark(sess, by) {
  const state = _genAgentTerminals[_caSessionKey(sess.tabId)];
  if (!state || state.activeId === sess.ptySessionId) return;
  sess._wokenMark = by;
  const tabEl = document.querySelector(
    '#' + _genAgentHeaderTabStripId() + ' .gtp-tab[data-sid="' + sess.ptySessionId + '"]',
  );
  if (tabEl) _genAgentDecorateWokenTab(tabEl, sess);
}

function _genAgentClearWokenMark(tabId, ptyId) {
  const state = _genAgentTerminals[_caSessionKey(tabId)];
  const sess = state && state.sessions[ptyId];
  if (!sess || !sess._wokenMark) return;
  sess._wokenMark = null;
  const tabEl = document.querySelector(
    '#' + _genAgentHeaderTabStripId() + ' .gtp-tab[data-sid="' + ptyId + '"]',
  );
  if (tabEl) {
    tabEl.querySelectorAll('.gtp-tab-woken').forEach((n) => n.remove());
    tabEl.removeAttribute('title');
  }
}

function _genAgentShowRestartOverlay(sess, reason) {
  if (!sess.container) return;
  _genAgentClearReconnecting(sess);
  if (sess.container.querySelector('.oc-restart-overlay')) return;
  // A process can exit before its first visible paint. In that case the
  // cold-start loading layer is still present at z-index 10 and otherwise
  // intercepts every click intended for this recovery control.
  _genAgentHideLoadingState(sess.tabId, sess.container);
  const overlay = document.createElement('div');
  overlay.className = 'oc-restart-overlay';
  const msg = document.createElement('div');
  msg.className = 'oc-restart-msg';
  msg.textContent = reason || 'Session ended';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'oc-restart-btn';
  btn.textContent = sess._resumeId ? 'Resume session' : 'Restart session';
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    const restarted = await _genAgentRestartSession(sess.tabId, sess.ptySessionId);
    if (restarted) {
      overlay.remove();
      return;
    }
    btn.disabled = false;
    msg.textContent = 'Could not close the old session. Check the backend, then try again.';
  });
  overlay.appendChild(msg);
  overlay.appendChild(btn);
  sess.container.appendChild(overlay);
}
