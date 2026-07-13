/* ── Third Pane — Teams & Outlook native view ─────────────── */

const TP_SKILLS = new Set(['teams', 'email', 'onenote', 'calendar', 'onedrive', 'slack', 'confluence']);

/* ── Compose bar drag-to-resize ──────────────────────── */
function _initComposeResize(handle, target, minH) {
  let startY, startH;
  handle.addEventListener('mousedown', e => {
    e.preventDefault();
    startY = e.clientY;
    startH = target.offsetHeight;
    const onMove = ev => {
      const h = Math.min(window.innerHeight * 0.5, Math.max(minH, startH - (ev.clientY - startY)));
      target.style.flex = 'none';
      target.style.height = h + 'px';
    };
    const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

/* Shared toolbar SVG icons — + (create) and X (close) */
const _TP_PLUS_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>';
const _TP_CLOSE_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
const _TP_SYSTEM_PEOPLE_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>';

/* ── Gator empty-state hint map ──────────────────────────────
   Maps each pane type to contextual hints shown alongside the
   peek head. Falls back to generic hints for unknown types.
─────────────────────────────────────────────────────────────── */
/* Shared SVG icons for hints — currentColor so they match text-sub */
const _HI_GATOR = `<svg viewBox="0 0 26 26" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="1" y="1" width="22" height="18" rx="5" fill="currentColor" opacity=".9"/>
  <polygon points="4,19 2,24 9,19" fill="currentColor" opacity=".9"/>
  <circle cx="8.5" cy="7.5" r="2.2" fill="var(--surface1,#1e293b)"/>
  <circle cx="8.5" cy="7.5" r="1" fill="currentColor" opacity=".5"/>
  <circle cx="17.5" cy="7.5" r="2.2" fill="var(--surface1,#1e293b)"/>
  <circle cx="17.5" cy="7.5" r="1" fill="currentColor" opacity=".5"/>
  <rect x="5" y="12" width="16" height="5" rx="2.5" fill="currentColor" opacity=".6"/>
  <rect x="8"  y="11" width="2" height="2.5" rx=".6" fill="var(--surface1,#1e293b)"/>
  <rect x="12" y="11" width="2" height="2.5" rx=".6" fill="var(--surface1,#1e293b)"/>
  <rect x="16" y="11" width="2" height="2.5" rx=".6" fill="var(--surface1,#1e293b)"/>
</svg>`;

const _HI_COMPOSE = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
</svg>`;

const _HI_UPLOAD = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="16 16 12 12 8 16"/>
  <line x1="12" y1="12" x2="12" y2="21"/>
  <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/>
</svg>`;

const _GATOR_HINTS = {
  email:    [
    { icon: '✉',          text: 'Select an email to read it' },
    { icon: _HI_COMPOSE,  text: 'Compose a new message' },
    { icon: _HI_GATOR,    text: 'Ask Gator to summarize your inbox' },
  ],
  teams:    [
    { icon: '💬',         text: 'Select a chat or channel' },
    { icon: '➕',         text: 'Start a new conversation' },
    { icon: _HI_GATOR,   text: 'Ask Gator to catch you up on unread messages' },
  ],
  onenote:  [
    { icon: '📄',         text: 'Select a page to read it' },
    { icon: _HI_COMPOSE,  text: 'Create a new page' },
    { icon: _HI_GATOR,    text: 'Ask Gator to search your notes' },
  ],
  onedrive: [
    { icon: '📁',         text: 'Browse and select a file' },
    { icon: _HI_UPLOAD,   text: 'Upload a file to OneDrive' },
    { icon: _HI_GATOR,    text: 'Ask Gator to find a file for you' },
  ],
  slack: 'custom', // handled by _slackEmptyState()
  calendar: [
    { icon: '📅',         text: 'Select an event for details' },
    { icon: '➕',         text: 'Schedule a new meeting' },
    { icon: _HI_GATOR,    text: 'Ask Gator about your day' },
  ],
  confluence: [
    { icon: '📄',         text: 'Select a page to read it' },
    { icon: _HI_COMPOSE,  text: 'Create a new wiki page' },
    { icon: _HI_GATOR,    text: 'Ask Gator to find documentation' },
  ],
  jira: [
    { icon: '🎫',         text: 'Select an issue to view details' },
    { icon: _HI_COMPOSE,  text: 'Ask Gator to create a ticket' },
    { icon: _HI_GATOR,    text: 'Ask Gator to search or update issues' },
  ],
};
const _GATOR_HINTS_DEFAULT = [
  { icon: '👈',       text: 'Select an item from the list' },
  { icon: _HI_GATOR,  text: 'Or ask Gator to help you find something' },
];

function _gatorDetailHint(type) {
  if (type === 'slack') return _slackEmptyState();
  const hints = _GATOR_HINTS[type] || _GATOR_HINTS_DEFAULT;
  return gatorEmptyState(hints);
}

/**
 * Reset the persistent right-pane header (#tp-detail-header) back to
 * just the close button.  Called when switching panes or clearing detail col.
 * #tp-detail-header is a sibling of #tp-detail-col so it is never wiped by
 * col.innerHTML = '' assignments in pane renderers.
 */
function _resetDetailHeader() {
  const hdr = document.getElementById('tp-detail-header');
  if (!hdr) return;
  // Empty/default state: just the collapse button pinned far-right (spacer
  // pushes it over). Closing is this button + Esc.
  hdr.className = 'tp-detail-header tp-detail-toolbar';
  hdr.innerHTML = '<div class="tp-toolbar-spacer" style="flex:1 1 auto;min-width:0"></div>'
    + '<div class="tp-toolbar-divider tp-toolbar-collapse-div"></div>'
    + '<button class="tp-qt-btn tp-call-btn tp-toolbar-collapse" id="tp-detail-close" title="Collapse panel (Esc)" aria-label="Collapse panel">'
    + '<svg xmlns="http://www.w3.org/2000/svg" height="18px" viewBox="0 -960 960 960" width="18px" fill="currentColor"><path d="M660-320v-320L500-480l160 160ZM200-120q-33 0-56.5-23.5T120-200v-560q0-33 23.5-56.5T200-840h560q33 0 56.5 23.5T840-760v560q0 33-23.5 56.5T760-120H200Zm120-80v-560H200v560h120Zm80 0h360v-560H400v560Zm-80 0H200h120Z"/></svg></button>';
  hdr.querySelector('#tp-detail-close').addEventListener('click', closeThirdPane);
}

// Shared "open externally" icon — used by every "Open in <app>" toolbar action.
const _TP_EXT_LINK_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';

/**
 * Shared detail-pane toolbar builder (#120/#142-era standardization).
 *
 * Every third-pane app (Teams, Email, Calendar, OneDrive, Confluence, Jira,
 * Slack, OneNote, GitHub) renders its detail toolbar through this one function
 * instead of hand-rolling a divergent bar inside the wiped content column. It
 * targets the PERSISTENT #tp-detail-header (sibling of #tp-detail-col), so the
 * toolbar survives `col.innerHTML = ''` content wipes.
 *
 * Close is deliberately NOT part of the spec — the pane is closed via the edge
 * collapse handle (#tp-collapse-handle) and Esc, keeping the toolbar reserved
 * for true app tools.
 *
 * spec = {
 *   app:   'email',                     // identifier (data-app on the header)
 *   title: {                            // left-aligned title block
 *     text:        'Subject line',
 *     icon:        '<svg…>'    | null,  // raw HTML icon (optional)
 *     avatar:      'AB'        | null,  // initials avatar (optional)
 *     avatarClass: 'tp-avatar-teams',  // optional avatar modifier
 *     title:       'tooltip'   | null,  // hover tooltip on the title
 *     onClick:     fn          | null,  // e.g. click-to-rename
 *   },
 *   actions: [                          // ordered; rendered left→right after title
 *     { kind:'ai'|'primary'|'icon',
 *       label:   'Reply',              // text for ai/primary kinds
 *       iconHtml:'<svg…>'|'✦',         // markup for icon kind (or leading glyph)
 *       title:   'tooltip + aria-label',
 *       onClick: fn,
 *       id:      'optional-dom-id',
 *       group:   0,                     // actions with a higher group get a
 *                                       // divider before them (Teams: pin | call)
 *       el:      existingButtonEl,      // pass a prebuilt button (e.g. _createPinBtn)
 *     },
 *   ],
 * }
 *
 * Returns the populated header element (or null if it doesn't exist).
 */
function tpBuildDetailToolbar(spec) {
  const hdr = document.getElementById('tp-detail-header');
  if (!hdr) return null;
  spec = spec || {};
  hdr.innerHTML = '';
  hdr.className = 'tp-detail-header tp-detail-toolbar';
  if (spec.app) hdr.dataset.app = spec.app;

  // ── Leading back button (master-detail nav) ────────────────────────
  // Renders top-left before the title so drill-downs (Slack threads, OneDrive
  // folders, etc.) don't need a separate in-content back sub-bar.
  if (spec.back && typeof spec.back.onClick === 'function') {
    const backBtn = document.createElement('button');
    backBtn.className = 'tp-qt-btn tp-call-btn tp-toolbar-back';
    backBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>';
    const blbl = spec.back.title || 'Back';
    backBtn.title = blbl;
    backBtn.setAttribute('aria-label', blbl);
    backBtn.addEventListener('click', spec.back.onClick);
    hdr.appendChild(backBtn);
  }

  // ── Title block (left) ─────────────────────────────────────────────
  const t = spec.title || {};
  if (t.avatar) {
    const av = document.createElement('div');
    av.className = 'tp-avatar ' + (t.avatarClass || '');
    av.style.cssText = 'width:26px;height:26px;font-size:.65rem;flex-shrink:0';
    av.textContent = t.avatar;
    hdr.appendChild(av);
  } else if (t.icon) {
    const ic = document.createElement('span');
    ic.className = 'tp-toolbar-title-icon';
    ic.innerHTML = t.icon;
    hdr.appendChild(ic);
  }
  if (t.text != null) {
    const name = document.createElement('div');
    name.className = 'tp-thread-name tp-toolbar-title';
    name.textContent = t.text;
    if (t.title) name.title = t.title;
    if (t.onClick) { name.style.cursor = 'pointer'; name.addEventListener('click', t.onClick); }
    hdr.appendChild(name);
  }

  // Spacer pushes actions to the right edge.
  const spacer = document.createElement('div');
  spacer.className = 'tp-toolbar-spacer';
  spacer.style.cssText = 'flex:1 1 auto;min-width:0';
  hdr.appendChild(spacer);

  // ── Actions (right) ────────────────────────────────────────────────
  let lastGroup = null;
  (spec.actions || []).forEach((a) => {
    if (!a) return;
    // Group divider: insert before the first action of a new (higher) group.
    if (a.group != null && lastGroup != null && a.group !== lastGroup) {
      const div = document.createElement('div');
      div.className = 'tp-toolbar-divider';
      hdr.appendChild(div);
    }
    if (a.group != null) lastGroup = a.group;

    let btn;
    if (a.el) {
      // Caller supplied a prebuilt button (e.g. _createPinBtn) — adopt it.
      btn = a.el;
      btn.classList.add('tp-qt-btn');
      if (a.kind === 'icon' || !a.kind) btn.classList.add('tp-call-btn');
    } else {
      btn = document.createElement('button');
      btn.className = 'tp-qt-btn'
        + (a.kind === 'icon' ? ' tp-call-btn' : '')
        + (a.kind === 'ai' ? ' tp-toolbar-ai' : '')
        + (a.kind === 'primary' ? ' tp-toolbar-primary' : '');
      if (a.kind === 'icon') {
        btn.innerHTML = a.iconHtml || '';
      } else {
        // ai / primary: optional leading glyph + text label
        btn.textContent = (a.iconHtml ? a.iconHtml + ' ' : '') + (a.label || '');
      }
      if (a.onClick) btn.addEventListener('click', a.onClick);
    }
    if (a.id) btn.id = a.id;
    // a11y + tooltip on every action (icon-only buttons must not be unlabeled).
    const lbl = a.title || a.label || '';
    if (lbl) { btn.title = lbl; btn.setAttribute('aria-label', lbl); }
    // Remember the spec entry so overflow can rebuild a menu item from it.
    btn._tpAction = a;
    hdr.appendChild(btn);
  });

  // Divider then the collapse/close button pinned far-right. Chevron points
  // left to signal the pane collapsing right→left. Excluded from overflow.
  const _collapseDiv = document.createElement('div');
  _collapseDiv.className = 'tp-toolbar-divider tp-toolbar-collapse-div';
  hdr.appendChild(_collapseDiv);
  const closeBtn = document.createElement('button');
  closeBtn.className = 'tp-qt-btn tp-call-btn tp-toolbar-collapse';
  closeBtn.id = 'tp-detail-close';
  closeBtn.title = 'Collapse panel (Esc)';
  closeBtn.setAttribute('aria-label', 'Collapse panel');
  closeBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" height="18px" viewBox="0 -960 960 960" width="18px" fill="currentColor"><path d="M660-320v-320L500-480l160 160ZM200-120q-33 0-56.5-23.5T120-200v-560q0-33 23.5-56.5T200-840h560q33 0 56.5 23.5T840-760v560q0 33-23.5 56.5T760-120H200Zm120-80v-560H200v560h120Zm80 0h360v-560H400v560Zm-80 0H200h120Z"/></svg>';
  closeBtn.addEventListener('click', closeThirdPane);
  hdr.appendChild(closeBtn);

  // Progressive disclosure: if the toolbar is wider than its container, move
  // trailing actions into a "⋯ More" menu so dense toolbars never overflow/wrap.
  _tpApplyToolbarOverflow(hdr);

  return hdr;
}

// Collapse trailing toolbar buttons into a "⋯ More" popover when the header
// overflows its width. Runs after layout (rAF). Idempotent per render.
function _tpApplyToolbarOverflow(hdr) {
  if (!hdr) return;
  requestAnimationFrame(() => {
    if (!hdr.isConnected) return;
    // Only action buttons are candidates (skip title/spacer/avatar/icon).
    const candidates = Array.from(hdr.querySelectorAll('.tp-qt-btn'));
    // Need at least 3 actions before collapsing — a 2-button toolbar (e.g.
    // Calendar's Ask + Refresh) should never overflow into a "⋯ More" menu.
    if (candidates.length < 3) return;
    // Skip if the header hasn't been laid out yet (clientWidth 0 during the
    // calendar's full-width transition gave a false overflow → refresh became ⋯).
    if (hdr.clientWidth < 80) return;
    // Nothing to do if it already fits (small tolerance for sub-pixel rounding).
    if (hdr.scrollWidth <= hdr.clientWidth + 4) return;

    const moreBtn = document.createElement('button');
    moreBtn.className = 'tp-qt-btn tp-call-btn tp-toolbar-more';
    moreBtn.innerHTML = '⋯';
    moreBtn.title = 'More actions';
    moreBtn.setAttribute('aria-label', 'More actions');
    moreBtn.setAttribute('aria-haspopup', 'true');
    // Insert before the collapse divider so the divider + collapse button stay rightmost.
    const _closeEl = hdr.querySelector('.tp-toolbar-collapse-div') || hdr.querySelector('.tp-toolbar-collapse');
    if (_closeEl) hdr.insertBefore(moreBtn, _closeEl); else hdr.appendChild(moreBtn);

    const overflowed = [];
    // Move trailing buttons (lowest priority) into the menu until it fits.
    // Walk from the end, but never remove the AI (first) action.
    for (let i = candidates.length - 1; i >= 1 && hdr.scrollWidth > hdr.clientWidth + 1; i--) {
      const b = candidates[i];
      if (b.classList.contains('tp-toolbar-ai') || b.classList.contains('tp-toolbar-back') || b.classList.contains('tp-toolbar-collapse')) continue;
      overflowed.unshift(b);
      b.style.display = 'none';
    }
    if (!overflowed.length) { moreBtn.remove(); return; }

    moreBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const existing = document.querySelector('.tp-toolbar-overflow-menu');
      if (existing) { existing.remove(); return; }
      const menu = document.createElement('div');
      menu.className = 'tp-toolbar-overflow-menu';
      overflowed.forEach((b) => {
        const a = b._tpAction || {};
        const item = document.createElement('button');
        item.className = 'tp-toolbar-overflow-item';
        item.textContent = (a.label || a.title || '');
        item.setAttribute('aria-label', a.title || a.label || '');
        item.addEventListener('click', () => {
          menu.remove();
          b.click(); // delegate to the original button's handler
        });
        menu.appendChild(item);
      });
      document.body.appendChild(menu);
      const r = moreBtn.getBoundingClientRect();
      menu.style.top = r.bottom + 4 + 'px';
      menu.style.left = Math.max(8, r.right - menu.offsetWidth) + 'px';
      const close = (ev) => { if (!menu.contains(ev.target) && ev.target !== moreBtn) { menu.remove(); document.removeEventListener('mousedown', close); } };
      setTimeout(() => document.addEventListener('mousedown', close), 0);
    });
  });
}

/**
 * Wire the pane edge collapse handle (#tp-collapse-handle) to closeThirdPane.
 * The handle lives on the pane's resize edge but has its own hit-area; we
 * stopPropagation on pointer-down so a click collapses the pane without the
 * resize bar interpreting it as the start of a drag. Idempotent.
 */
function _initCollapseHandle() {
  const handle = document.getElementById('tp-collapse-handle');
  if (!handle || handle.dataset.wired === '1') return;
  handle.dataset.wired = '1';
  // Stop the resize drag from starting when the user clicks the handle.
  handle.addEventListener('mousedown', (e) => { e.stopPropagation(); });
  handle.addEventListener('click', (e) => { e.stopPropagation(); closeThirdPane(); });
}

/**
 * Replace the persistent detail header with a compose-mode title and a single X
 * close button — hides the prior chat's name, avatar, and call/video/pin icons
 * (which are irrelevant while the user is drafting a new message).
 */
function _setComposeDetailHeader(title, onClose, actions) {
  const hdr = document.getElementById('tp-detail-header');
  if (!hdr) return;
  hdr.className = 'tp-detail-header tp-detail-toolbar';
  hdr.innerHTML = `
    <div class="tp-thread-name tp-toolbar-title" style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">${escapeHtml(title)}</div>
    <div class="tp-toolbar-spacer" style="flex:1 1 auto;min-width:0"></div>`;
  // Optional toolbar actions (e.g. Draft with AI) rendered before the close.
  (actions || []).forEach((a) => {
    const btn = document.createElement('button');
    btn.className = 'tp-qt-btn' + (a.kind === 'ai' ? ' tp-toolbar-ai' : '');
    btn.innerHTML = (a.iconHtml ? a.iconHtml + ' ' : '') + (a.label || '');
    if (a.title) { btn.title = a.title; btn.setAttribute('aria-label', a.title); }
    if (a.onClick) btn.addEventListener('click', a.onClick);
    hdr.appendChild(btn);
  });
  const _div = document.createElement('div');
  _div.className = 'tp-toolbar-divider tp-toolbar-collapse-div';
  hdr.appendChild(_div);
  const closeBtn = document.createElement('button');
  closeBtn.className = 'tp-qt-btn tp-call-btn tp-toolbar-collapse';
  closeBtn.id = 'tp-compose-header-close';
  closeBtn.title = 'Discard draft';
  closeBtn.setAttribute('aria-label', 'Discard draft');
  closeBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
  closeBtn.addEventListener('click', onClose);
  hdr.appendChild(closeBtn);
}

/**
 * If the +/X toolbar toggle is currently in compose ("X") state, flip it back
 * to + so the label matches the active pane again.  Called from tpLoadDetail
 * when the user navigates to another chat while a compose form is open.
 */
function _resetComposeToggleBtn() {
  const btn = document.getElementById('tp-add-btn');
  if (!btn || btn.dataset.composing !== '1') return;
  btn.dataset.composing = '';
  btn.innerHTML = _TP_PLUS_SVG;
  // Re-bind onclick to the open-compose action for the current pane — without
  // this the button would still call _closeNewTeamsCompose/_discardCompose from
  // its prior X-state binding, defeating the purpose of resetting it.
  if (tpState.type === 'email') {
    btn.title = 'Compose email';
    btn.onclick = () => _showNewEmailCompose();
  } else if (tpState.type === 'teams') {
    btn.title = 'New conversation';
    btn.onclick = () => _showNewTeamsCompose();
  }
  // The persistent header is still showing the compose title + X.  Reset it now;
  // pane renderers that populate the header (renderTeamsThread) will overwrite
  // this with chat-specific content, while ones that don't (renderEmailDetail)
  // will correctly land on the panel-close-only state.
  _resetDetailHeader();
}

const tpState = {
  type: null,
  selectedId: null,
  list: [],
  loading: false,
  searchQuery: '',
  focusedIndex: -1,
  // Stable id of the keyboard/click-focused row. Tracked by id (not position) so the
  // "focused" highlight can't drift to the wrong chat when the list re-sorts on poll (#…).
  focusedId: null,
  filter: 'all',
};

// Supplemental chat-info map populated by search results and sent-message responses.
// Lets _loadTeamsThread resolve the correct topic even when the chat isn't in tpState.list yet
// (e.g. immediately after sending to a chat found via search).
const _chatInfoCache = new Map(); // chatId -> {topic, chat_type, ...}

// Teams reply-to state (module-level so _buildTeamsMessage reply button and compose send can share it)
let _teamsReplyTo = null; // {id, sender_name, sender_aad, body_preview}
// Set by renderTeamsThread so _buildTeamsMessage (top-level) can call it
let _activeSeekToMessage = null;

function _setTeamsReplyTo(info) {
  _teamsReplyTo = info;
  const bar = document.getElementById('tp-reply-bar');
  if (!bar) return;
  if (info) {
    bar.querySelector('.tp-reply-sender').textContent = info.sender_name || 'Unknown';
    bar.querySelector('.tp-reply-preview').textContent = info.body_preview || '';
    bar.classList.remove('hidden');
  } else {
    bar.classList.add('hidden');
  }
}

const tpThreadCache = new Map(); // id → { data, ts }

// Cached logged-in user email (from /api/auth/status), used to exclude self when
// pre-filling Reply-All CC (#86). Empty string until the first successful fetch.
let tpCurrentUserEmail = '';
async function _ensureCurrentUserEmail() {
  if (tpCurrentUserEmail) return tpCurrentUserEmail;
  try {
    const d = await fetch('/api/auth/status').then(r => r.json());
    if (d && d.email) tpCurrentUserEmail = String(d.email);
  } catch (_) { /* best-effort; self just won't be excluded */ }
  return tpCurrentUserEmail;
}

// Reply-All CC recipients: original To + Cc, excluding the sender AND the current
// user (self). Case-insensitive dedup so token UPN casing differences still match.
function _replyAllCcRecipients(email, selfEmail) {
  const seen = new Set();
  if (email.from_email) seen.add(String(email.from_email).toLowerCase());
  if (selfEmail) seen.add(String(selfEmail).toLowerCase());
  const out = [];
  [...(email.to || []), ...(email.cc || [])].forEach(r => {
    if (!r || !r.email) return;
    const key = String(r.email).toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ email: r.email, name: r.name || r.email });
  });
  return out;
}

/* ── Gator Loading Animation ────────────────────────── */
const _GATOR_TIPS = [
  'Wading through the swamp',
  'Chomping through data',
  'Swimming upstream',
  'Snapping up messages',
  'Surfacing shortly',
  'Tail-whipping the API',
  'Lurking in the data lake',
  'Crunching bytes',
];
let _gatorLoadingTimer = null;

function _gatorLoading() {
  // Clear any previous cycling timer
  if (_gatorLoadingTimer) { clearInterval(_gatorLoadingTimer); _gatorLoadingTimer = null; }

  const id = 'gator-tip-' + Date.now();
  const html = `<div class="gator-loading">
    <div class="gator-loading-icon">
      <span class="gator-chomp">\uD83D\uDC0A</span>
      <span class="gator-dots"><span>.</span><span>.</span><span>.</span></span>
    </div>
    <div class="gator-loading-tip" id="${id}"></div>
  </div>`;

  // Start cycling tips after DOM insertion
  let tipIdx = 0;
  setTimeout(() => {
    const el = document.getElementById(id);
    if (!el) return;
    // Show first tip immediately
    el.textContent = _GATOR_TIPS[0] + '\u2026';
    tipIdx = 1;
    _gatorLoadingTimer = setInterval(() => {
      const tipEl = document.getElementById(id);
      if (!tipEl) { clearInterval(_gatorLoadingTimer); _gatorLoadingTimer = null; return; }
      tipEl.style.opacity = '0';
      setTimeout(() => {
        if (!document.getElementById(id)) return;
        tipEl.textContent = _GATOR_TIPS[tipIdx % _GATOR_TIPS.length] + '\u2026';
        tipEl.style.opacity = '1';
        tipIdx++;
      }, 200);
    }, 2500);
  }, 50);

  return html;
}

/* ── Gator Send Status (sending → success / failure) ── */
const _GATOR_SEND_TIPS = [
  'Delivering your message',
  'Swimming it across',
  'Gator express delivery',
  'Wading to the recipient',
];
function _gatorSendStatus(containerEl) {
  let tipIdx = 0;
  let timer = null;
  const el = document.createElement('div');
  el.className = 'gator-send-status gator-send-sending';
  el.innerHTML = `<span class="gator-send-icon">\uD83D\uDC0A</span><span class="gator-send-dots"><span>.</span><span>.</span><span>.</span></span><span class="gator-send-tip">${_GATOR_SEND_TIPS[0]}\u2026</span>`;
  containerEl.innerHTML = '';
  containerEl.appendChild(el);
  // Cycle tips
  timer = setInterval(() => {
    tipIdx = (tipIdx + 1) % _GATOR_SEND_TIPS.length;
    const tipEl = el.querySelector('.gator-send-tip');
    if (tipEl) { tipEl.style.opacity = '0'; setTimeout(() => { tipEl.textContent = _GATOR_SEND_TIPS[tipIdx] + '\u2026'; tipEl.style.opacity = '1'; }, 150); }
  }, 2000);
  return {
    success(msg) {
      clearInterval(timer);
      el.className = 'gator-send-status gator-send-success';
      el.innerHTML = `<span class="gator-send-icon">\uD83D\uDC0A</span> <span class="gator-send-result">\u2713 ${msg || 'Message delivered!'}</span>`;
    },
    fail(msg) {
      clearInterval(timer);
      el.className = 'gator-send-status gator-send-fail';
      el.innerHTML = `<span class="gator-send-icon">\uD83D\uDC0A</span> <span class="gator-send-result">\u2717 ${msg || 'Delivery failed'}</span>`;
    },
    unknown(msg) {
      clearInterval(timer);
      el.className = 'gator-send-status gator-send-unknown';
      el.innerHTML = `<span class="gator-send-icon">\uD83D\uDC0A</span> <span class="gator-send-result">? ${msg || 'Send status unknown'}</span>`;
    },
    clear() { clearInterval(timer); el.remove(); },
  };
}

/* ── Pin System: single source of truth + optimistic updates ── */
let _pinnedItemsCache = new Set(); // "source::id" keys
let _pinCacheReady = false;

// Load pins from server — call once on init, then keep in sync optimistically
async function _loadPinCache() {
  const cid = typeof _activeTabId !== 'undefined' ? _activeTabId : 'default';
  try {
    const pins = await fetch(`/api/context/pins?context_id=${cid}`).then(r => r.ok ? r.json() : []);
    _pinnedItemsCache = new Set(pins.map(p => `${p.source}::${p.id}`));
  } catch {
    _pinnedItemsCache = new Set();
  }
  _pinCacheReady = true;
}

function _isPinned(source, id) {
  return _pinnedItemsCache.has(`${source}::${id}`);
}

// Pin an item: optimistic cache update → API call → rollback on failure
async function _pinItem(source, id, label, meta = {}) {
  const key = `${source}::${id}`;
  _pinnedItemsCache.add(key);
  _syncAllPinUI();
  const cid = typeof _activeTabId !== 'undefined' ? _activeTabId : 'default';
  try {
    const res = await fetch('/api/context/pin', { method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ source, id: String(id), label, meta, context_id: cid }) });
    if (!res.ok) throw new Error();
  } catch {
    _pinnedItemsCache.delete(key); // rollback
    _syncAllPinUI();
  }
  if (typeof _refreshPinOrb === 'function') _refreshPinOrb();
}

// Unpin an item: optimistic cache update → API call → rollback on failure
async function _unpinItem(source, id) {
  const key = `${source}::${id}`;
  _pinnedItemsCache.delete(key);
  _syncAllPinUI();
  const cid = typeof _activeTabId !== 'undefined' ? _activeTabId : 'default';
  try {
    const res = await fetch(`/api/context/pin/${source}/${encodeURIComponent(id)}?context_id=${cid}`, { method: 'DELETE' });
    if (!res.ok) throw new Error();
  } catch {
    _pinnedItemsCache.add(key); // rollback
    _syncAllPinUI();
  }
  if (typeof _refreshPinOrb === 'function') _refreshPinOrb();
}

// Toggle pin state
async function _togglePin(source, id, label, meta = {}) {
  if (_isPinned(source, id)) await _unpinItem(source, id);
  else await _pinItem(source, id, label, meta);
}

// Sync ALL pin-related UI in one shot
function _syncAllPinUI() {
  const source = tpState.type || 'teams';

  // 1. Left pane: update pin badges on list items (teams/email use .tp-list-item)
  document.querySelectorAll('.tp-list-item').forEach(item => {
    const itemId = item.dataset.id;
    if (!itemId) return;
    const pinned = _isPinned(source, itemId);
    item.classList.toggle('tp-item-pinned', pinned);
    let pinEl = item.querySelector('.tp-pin-inline');
    if (pinned && !pinEl) {
      const nameEl = item.querySelector('.tp-item-name');
      if (nameEl) {
        pinEl = document.createElement('span');
        pinEl.className = 'tp-pin-inline';
        pinEl.textContent = '\uD83D\uDCCC';
        nameEl.prepend(pinEl);
      }
    } else if (!pinned && pinEl) {
      pinEl.remove();
    }
  });

  // 1b. OneDrive rows have a separate layout, but should mirror the same pinned state.
  document.querySelectorAll('.od-flat-row, .od-item-row').forEach(row => {
    const pinBtn = row.querySelector('.pin-ctx-btn');
    if (!pinBtn) return;
    const id = pinBtn._pinId;
    if (!id) return;
    const pinned = _isPinned('onedrive', String(id));
    row.classList.toggle('tp-item-pinned', pinned);
    pinBtn.classList.toggle('pinned', pinned);
    pinBtn.title = pinned ? 'Unpin from Chat' : 'Pin to Chat';
  });

  // 1c. Slack messages: sync pin buttons and pinned glow on .slack-msg rows
  document.querySelectorAll('.slack-msg').forEach(msg => {
    const pinBtn = msg.querySelector('.slack-msg-actions .pin-ctx-btn');
    if (!pinBtn) return;
    const pinned = _isPinned('slack', String(pinBtn._pinId));
    msg.classList.toggle('tp-item-pinned', pinned);
    pinBtn.classList.toggle('pinned', pinned);
    pinBtn.title = pinned ? 'Unpin from Chat' : 'Pin to Chat';
  });

  // 2. Right pane: sync detail pin button
  // Teams puts its pin button in #tp-detail-header (sibling of #tp-detail-col), so search both.
  // For Slack, tpState.selectedId is null — read the pin id/source from the button itself.
  const detailBtn = document.querySelector('#tp-detail-col .pin-ctx-btn, #tp-detail-header .pin-ctx-btn');
  if (detailBtn) {
    const btnSource = detailBtn._pinSource || source;
    const btnId = detailBtn._pinId || tpState.selectedId;
    if (btnId) {
      const pinned = _isPinned(btnSource, String(btnId));
      detailBtn.classList.toggle('pinned', pinned);
      detailBtn.title = pinned ? 'Unpin from Chat' : 'Pin to Chat';
    }
  }
}

// Compat wrapper for old code that calls _refreshPinnedItemsCache
async function _refreshPinnedItemsCache(prefetchedPins) {
  if (Array.isArray(prefetchedPins)) {
    _pinnedItemsCache = new Set(prefetchedPins.map(p => `${p.source}::${p.id}`));
    _pinCacheReady = true;
  } else {
    await _loadPinCache();
  }
  _syncAllPinUI();
}

// Call on every tab switch or tab creation — reloads pins for the active context
async function _switchPinContext() {
  await _loadPinCache();
  _syncAllPinUI();
}

const _origRefreshPinOrb = typeof _refreshPinOrb === 'function' ? _refreshPinOrb : null;

/* ── Universal Pin Button Helper ─────────────────────── */
function _createPinBtn(source, id, label, meta = {}) {
  const btn = document.createElement('button');
  btn.className = 'pin-ctx-btn';
  btn.textContent = '\uD83D\uDCCC';
  btn._pinId = String(id);
  btn._pinSource = source;
  if (_isPinned(source, String(id))) {
    btn.classList.add('pinned');
    btn.title = 'Unpin from Chat';
  } else {
    btn.title = 'Pin to Chat';
  }
  btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    e.preventDefault();
    await _togglePin(source, String(id), label, meta);
  });
  return btn;
}

// ── Teams meeting transcript card ──
// Recordings live in the organizer's OneDrive; identified by (driveId, itemId).
// The resolver endpoints scan the meeting chat for the RichText/Media_CallRecording
// attachment and return the drive-item coordinates. Card is silently hidden
// when no recording or no transcript exists.
// Transcripts panel: replaces the chat-pane body with a list of recordings
// (one row per recording, each with its transcripts). Triggered by the
// 📝 toolbar button on meeting chats. Back arrow restores the chat thread.
async function _openTranscriptsPanel(chat) {
  const col = document.getElementById('tp-detail-col');
  if (!col) return;
  const _pin = document.getElementById('tp-teams-chat-pin');
  if (_pin) _pin.style.display = 'none';
  col.innerHTML = '';

  const wrap = document.createElement('div');
  wrap.className = 'tp-tx-panel';

  const bar = document.createElement('div');
  bar.className = 'tp-tx-panel-bar';
  const back = document.createElement('button');
  back.className = 'tp-tx-back';
  back.title = 'Back to chat';
  back.textContent = '← Back to chat';
  back.addEventListener('click', () => _loadTeamsThread(chat.id));
  bar.appendChild(back);
  const title = document.createElement('div');
  title.className = 'tp-tx-panel-title';
  title.textContent = `Transcripts — ${chat.topic || 'Meeting'}`;
  bar.appendChild(title);
  wrap.appendChild(bar);

  const body = document.createElement('div');
  body.className = 'tp-tx-panel-body';
  body.textContent = 'Loading recordings…';
  wrap.appendChild(body);

  col.appendChild(wrap);

  await _renderTranscriptsList(body, chat);
}

async function _renderTranscriptsList(bodyEl, chat) {
  let resp = null;
  try {
    const r = await fetch(`/api/teams/chats/${encodeURIComponent(chat.id)}/recordings`);
    if (r.ok) resp = await r.json();
  } catch (_) { /* ignore */ }

  bodyEl.innerHTML = '';

  const recs = (resp && resp.recordings) || [];
  if (recs.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'tp-tx-empty';
    empty.textContent = 'No recordings found for this meeting chat.';
    bodyEl.appendChild(empty);
    return;
  }

  for (const rec of recs) {
    bodyEl.appendChild(await _buildRecordingRow(rec, chat));
  }
}

async function _buildRecordingRow(rec, chat) {
  const row = document.createElement('div');
  row.className = 'tp-tx-row';

  const head = document.createElement('div');
  head.className = 'tp-tx-row-head';
  const when = rec.created_at ? new Date(rec.created_at) : null;
  const whenStr = when
    ? when.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })
    : (rec.title || rec.original_name || 'Recording');
  const dateLabel = document.createElement('div');
  dateLabel.className = 'tp-tx-row-date';
  dateLabel.textContent = whenStr;
  head.appendChild(dateLabel);

  if (!rec.has_transcript) {
    const tag = document.createElement('span');
    tag.className = 'tp-tx-row-tag';
    tag.textContent = 'no transcript';
    head.appendChild(tag);
  }
  row.appendChild(head);

  if (!rec.has_transcript) return row;

  // Transcript children for this recording
  const txList = document.createElement('div');
  txList.className = 'tp-tx-row-list';
  txList.textContent = 'Loading transcripts…';
  row.appendChild(txList);

  // When Graph is unavailable the recording is still surfaced (detection comes from
  // the URIObject) but drive/item ids are empty, so the VTT can't be fetched. Show a
  // clear sign-in hint instead of the misleading "no transcript available yet".
  if (!rec.drive_id || !rec.item_id) {
    txList.textContent = 'Transcript available — sign in (Settings) to load it.';
    return row;
  }

  let tResp = null;
  try {
    const r = await fetch(`/api/recordings/${encodeURIComponent(rec.drive_id)}/${encodeURIComponent(rec.item_id)}/transcripts`);
    if (r.ok) tResp = await r.json();
  } catch (_) { /* ignore */ }

  txList.innerHTML = '';
  const items = (tResp && tResp.transcripts) || [];
  if (items.length === 0) {
    txList.textContent = '(no transcript available yet)';
    return row;
  }

  for (const tx of items) {
    txList.appendChild(await _buildTranscriptRow(tx, rec, chat, whenStr));
  }
  return row;
}

async function _buildTranscriptRow(tx, rec, chat, whenStr) {
  const item = document.createElement('div');
  item.className = 'tp-tx-item';

  const left = document.createElement('div');
  left.className = 'tp-tx-item-meta';

  const lang = (tx.language || '').toUpperCase();
  const langSpan = document.createElement('span');
  langSpan.className = 'tp-tx-item-lang';
  langSpan.textContent = lang || 'TRANSCRIPT';
  left.appendChild(langSpan);

  const sub = document.createElement('span');
  sub.className = 'tp-tx-item-sub';
  sub.textContent = 'loading…';
  left.appendChild(sub);

  item.appendChild(left);

  const actions = document.createElement('div');
  actions.className = 'tp-tx-item-actions';

  const view = document.createElement('button');
  view.className = 'tp-tx-item-view';
  view.textContent = 'View';
  view.addEventListener('click', () => _openTranscriptDetail(chat, rec, tx, whenStr));
  actions.appendChild(view);

  // Pin button — populated with header metadata once we have it
  const pinHolder = document.createElement('span');
  pinHolder.className = 'tp-tx-item-pin';
  actions.appendChild(pinHolder);

  item.appendChild(actions);

  // Best-effort header fetch for duration/speakers/tokens + pin meta
  try {
    const hr = await fetch(`/api/recordings/${encodeURIComponent(rec.drive_id)}/${encodeURIComponent(rec.item_id)}/transcripts/${encodeURIComponent(tx.id)}/header`);
    if (hr.ok) {
      const header = await hr.json();
      const mins = Math.round((header.duration_sec || 0) / 60);
      const spkCount = Object.keys(header.speakers || {}).length;
      sub.textContent = `${mins} min · ${spkCount} speaker${spkCount === 1 ? '' : 's'}`;
      const labelStr = `${chat.topic || rec.title || 'Meeting'} · ${whenStr}`;
      const pinMeta = {
        duration_min: mins,
        occurred_at: rec.created_at || tx.created,
        speaker_count: spkCount,
        size_tokens_estimate: header.size_tokens_estimate || 0,
      };
      pinHolder.appendChild(_createPinBtn('teams_transcript', `${rec.drive_id}:${rec.item_id}:${tx.id}`, labelStr, pinMeta));
    } else {
      sub.textContent = '—';
      pinHolder.appendChild(_createPinBtn('teams_transcript', `${rec.drive_id}:${rec.item_id}:${tx.id}`, `${chat.topic || 'Meeting'} · ${whenStr}`, { occurred_at: rec.created_at || tx.created }));
    }
  } catch (_) {
    sub.textContent = '—';
    pinHolder.appendChild(_createPinBtn('teams_transcript', `${rec.drive_id}:${rec.item_id}:${tx.id}`, `${chat.topic || 'Meeting'} · ${whenStr}`, { occurred_at: rec.created_at || tx.created }));
  }

  return item;
}

async function _openTranscriptDetail(chat, rec, tx, whenStr) {
  const col = document.getElementById('tp-detail-col');
  if (!col) return;
  col.innerHTML = '';

  const wrap = document.createElement('div');
  wrap.className = 'tp-tx-panel';

  const bar = document.createElement('div');
  bar.className = 'tp-tx-panel-bar';
  const back = document.createElement('button');
  back.className = 'tp-tx-back';
  back.title = 'Back to transcripts';
  back.textContent = '← Back to transcripts';
  back.addEventListener('click', () => _openTranscriptsPanel(chat));
  bar.appendChild(back);
  const title = document.createElement('div');
  title.className = 'tp-tx-panel-title';
  title.textContent = `${chat.topic || rec.title || 'Meeting'} — ${whenStr}`;
  bar.appendChild(title);
  wrap.appendChild(bar);

  const body = document.createElement('pre');
  body.className = 'tp-tx-detail-body';
  body.textContent = 'Loading transcript…';
  wrap.appendChild(body);

  col.appendChild(wrap);

  try {
    const r = await fetch(`/api/recordings/${encodeURIComponent(rec.drive_id)}/${encodeURIComponent(rec.item_id)}/transcripts/${encodeURIComponent(tx.id)}/full`);
    if (!r.ok) { body.textContent = 'Failed to load transcript.'; return; }
    const data = await r.json();
    body.textContent = data.text || '(empty)';
  } catch (e) {
    body.textContent = `Error: ${e.message}`;
  }
}

// Calendar pane keeps a lightweight inline card (no toolbar switching applies there).
function _chatIdFromJoinUrl(joinUrl) {
  if (!joinUrl) return null;
  // Match both encoded (%3a / %40) and decoded (: / @) URL forms.
  const m = joinUrl.match(/(19(?::|%3[Aa])meeting_[^/?@]+?(?:@|%40)thread\.v2)/);
  if (!m) return null;
  try { return decodeURIComponent(m[1]); } catch { return m[1]; }
}

// Calendar event popover: insert a "Transcripts" button that routes to the
// Teams pane and opens the transcripts panel for the meeting chat. Only
// shows when the meeting chat has at least one recording with a transcript.
async function _renderCalendarTranscriptCard(mountEl, eventId, meetingTopic, joinUrl) {
  const chatId = _chatIdFromJoinUrl(joinUrl);
  if (!chatId) return;
  let hasAny = false;
  try {
    const r = await fetch(`/api/teams/chats/${encodeURIComponent(chatId)}/recordings`);
    if (!r.ok) return;
    const data = await r.json();
    hasAny = (data.recordings || []).some(rec => rec.has_transcript);
  } catch (_) { return; }
  if (!hasAny) return;

  const btn = document.createElement('button');
  btn.className = 'tp-qt-btn tp-call-btn tp-cal-tx-btn';
  btn.title = 'View meeting transcripts';
  btn.setAttribute('aria-label', 'View meeting transcripts');
  btn.innerHTML = '<span class="material-symbols-outlined tp-mi">speaker_notes</span>';
  btn.addEventListener('click', () => {
    const closeBtn = document.querySelector('.tp-cal-pop-close');
    if (closeBtn) closeBtn.click();
    openThirdPane('teams');
    setTimeout(() => _openTranscriptsPanel({ id: chatId, topic: meetingTopic, chat_type: 'meeting' }), 80);
  });
  mountEl.appendChild(btn);
}

let _fcInstance = null;           // FullCalendar instance
const _fcEventCache = new Map();  // "start|end" → { events, ts }
const TP_CACHE_TTL = 86400000; // 24h — show cached instantly, refresh brings fresh data

/* ── Configurable list cache per skill ───────────────────── */
const _listCacheTTL = {
  teams:    30000,   // 30s (delta sync)
  email:    30000,   // 30s (delta sync)
  onenote:  300000,  // 5min
  onedrive: 0,       // 0 = no cache (folder nav state is complex)
  slack:    300000,  // 5min
  jira:     300000,  // 5min
  github:   300000,  // 5min
  confluence: 300000, // 5min
};
// Skills that use stale-while-revalidate (show cached data instantly, refresh in background)
// Includes composite keys like 'email_unread'
const _swrSkills = new Set(['teams', 'email', 'email_unread']);
const _listCache = {}; // { skillId: { data, extra, ts } }

function _getListCache(skillId) {
  const ttl = _listCacheTTL[skillId] || 0;
  if (!ttl) return null;
  const c = _listCache[skillId];
  if (c && Date.now() - c.ts < ttl) return c;
  return null;
}

/** Return cached data even if expired (for stale-while-revalidate). */
const _STALE_MAX_AGE = 24 * 60 * 60 * 1000; // 24h — reject localStorage data older than this

function _getStaleCache(skillId) {
  const c = _listCache[skillId];
  if (c) return c;
  // Fall back to localStorage for cross-session persistence
  try {
    const stored = localStorage.getItem('_lc_' + skillId);
    if (stored) {
      const parsed = JSON.parse(stored);
      // Reject stale data older than 24h
      if (parsed.ts && Date.now() - parsed.ts > _STALE_MAX_AGE) {
        localStorage.removeItem('_lc_' + skillId);
        return null;
      }
      _listCache[skillId] = parsed; // hydrate in-memory cache
      return parsed;
    }
  } catch {}
  return null;
}

function _setListCache(skillId, data, extra = {}) {
  if (!_listCacheTTL[skillId]) return;
  const entry = { data, extra, ts: Date.now() };
  _listCache[skillId] = entry;
  // Persist delta-synced skills to localStorage for instant load on revisit
  if (_swrSkills.has(skillId)) {
    try { localStorage.setItem('_lc_' + skillId, JSON.stringify(entry)); } catch {}
  }
}

function _clearListCache(skillId) {
  delete _listCache[skillId];
  try { localStorage.removeItem('_lc_' + skillId); } catch {}
}

/* ── Teams read tracking (client-side) ────────────────────── */
const TP_READ_KEY = 'tp-teams-read';

function _loadReadTimes() {
  try { return JSON.parse(localStorage.getItem(TP_READ_KEY) || '{}'); } catch { return {}; }
}

function _markChatRead(chatId) {
  const times = _loadReadTimes();
  times[chatId] = new Date().toISOString();
  localStorage.setItem(TP_READ_KEY, JSON.stringify(times));
}

function _isTeamsChatUnread(chat) {
  if (!chat.last_message_time) return false;
  const times = _loadReadTimes();
  const lastRead = times[chat.id];
  if (!lastRead) return true; // never opened → unread
  return new Date(chat.last_message_time) > new Date(lastRead);
}

/* ── State persistence ───────────────────────────────────── */

function saveTpState() {
  try {
    localStorage.setItem('tp-state', JSON.stringify({
      type: tpState.type,
      selectedId: tpState.selectedId,
      filter: tpState.filter,
    }));
  } catch {}
}

function loadTpState() {
  try {
    const s = JSON.parse(localStorage.getItem('tp-state') || '{}');
    tpState.type = s.type || null;
    tpState.selectedId = s.selectedId || null;
    tpState.filter = s.filter || 'all';
  } catch {}
}

/* ── Open / close ────────────────────────────────────────── */

function openThirdPane(type) {
  // Clear selectedId if switching between services (prevents loading Teams ID as email or vice versa)
  if (tpState.type && tpState.type !== type) {
    tpState.selectedId = null;
    tpState.focusedId = null;
  }
  tpState.type = type;
  tpState.focusedIndex = -1;
  saveTpState();

  // Dismiss any auth overlay from previous pane
  _dismissAuthOverlay();

  // Load pin cache for this tab (non-blocking — ready before list renders)
  _loadPinCache();

  const pane = document.getElementById('third-pane');
  const title = document.getElementById('tp-title');

  const _tpIcon = (id, ext='svg') => `<img src="/static/icons/${id}.${ext}" class="skill-icon-img" alt="${id}" style="width:16px;height:16px;">`;
  if (type === 'teams') title.innerHTML = _tpIcon('teams') + 'Teams';
  else if (type === 'email') { title.innerHTML = _tpIcon('outlook') + 'Outlook'; _ensureCurrentUserEmail(); }
  else if (type === 'onenote') { title.innerHTML = _tpIcon('onenote','png') + 'OneNote'; tpState._onenoteLevel = 'notebooks'; tpState._onenoteBreadcrumb = []; }
  else if (type === 'calendar') title.innerHTML = _tpIcon('calendar') + 'Calendar';
  else if (type === 'onedrive') { title.innerHTML = _tpIcon('onedrive') + 'OneDrive'; _odState.selectedFolderId = 'root'; _odState.selectedFolderName = 'My Drive'; _odState.folderCache.clear(); _odState.navStack = []; }
  else if (type === 'jira') { title.innerHTML = _tpIcon('jira') + 'Jira'; }
  else if (type === 'github') { title.innerHTML = _tpIcon('github') + 'GitHub'; }
  else if (type === 'slack') { title.innerHTML = _tpIcon('slack') + 'Slack'; }
  else if (type === 'confluence') { title.innerHTML = _tpIcon('confluence') + 'Confluence'; }

  // Wire toolbar buttons
  document.getElementById('tp-refresh-btn').onclick = tpRefresh;
  { const _b = document.getElementById('tp-close-btn'); if (_b) _b.onclick = closeThirdPane; }
  // Wire persistent right-pane close button
  { const _dc = document.getElementById('tp-detail-close'); if (_dc) _dc.onclick = closeThirdPane; }
  // Wire the pane edge collapse handle (close affordance outside the toolbar)
  _initCollapseHandle();
  _resetDetailHeader();
  // Expandable search toggle
  const _tpSearchBtn = document.getElementById('tp-search-btn');
  const _tpSearchPanel = document.getElementById('tp-toolbar-search');
  const _tpSearchClose = document.getElementById('tp-search-close');
  const _tpTitle = document.getElementById('tp-title');
  const _tpActions = document.getElementById('tp-toolbar-actions');
  if (_tpSearchBtn) _tpSearchBtn.onclick = () => {
    _tpSearchPanel.classList.remove('hidden');
    _tpTitle.style.display = 'none';
    _tpSearchBtn.style.display = 'none';
    document.getElementById('tp-search-input').focus();
  };
  if (_tpSearchClose) _tpSearchClose.onclick = () => {
    _tpSearchPanel.classList.add('hidden');
    _tpTitle.style.display = '';
    _tpSearchBtn.style.display = '';
    document.getElementById('tp-search-input').value = '';
    document.getElementById('tp-search-input').dispatchEvent(new Event('input'));
  };

  pane.classList.remove('hidden');
  requestAnimationFrame(() => pane.classList.add('is-open'));

  // Hide third-pane-resize — main-resize on the chat side controls the same edge without bleeding into chat text
  const tpResize = document.getElementById('third-pane-resize');
  if (tpResize) tpResize.style.display = 'none';

  // Reset OneNote/Calendar full-pane mode if switching away
  if (type !== 'calendar') {
    const _lc = document.getElementById('tp-left-col') || document.getElementById('tp-list-col');
    if (_lc) { _lc.classList.remove('tp-onenote-hidden', 'tp-cal-hidden'); _lc.style.display = ''; }
    const _lr = document.getElementById('tp-list-resize');
    if (_lr) { _lr.classList.remove('tp-onenote-hidden', 'tp-cal-hidden'); _lr.style.display = ''; }
    document.getElementById('tp-detail-col')?.classList.remove('tp-onenote-full', 'tp-cal-full');
    document.getElementById('tp-right-col')?.classList.remove('tp-cal-full');
  } else {
    // Calendar: hide left pane immediately (no flash of loading spinner)
    const _lc = document.getElementById('tp-left-col') || document.getElementById('tp-list-col');
    if (_lc) { _lc.classList.add('tp-cal-hidden'); _lc.style.display = 'none'; }
    const _lr = document.getElementById('tp-list-resize');
    if (_lr) { _lr.classList.add('tp-cal-hidden'); _lr.style.display = 'none'; }
    document.getElementById('tp-right-col')?.classList.add('tp-cal-full');
  }
  // Destroy FullCalendar instance if switching away from calendar
  if (_fcInstance) { _fcInstance.destroy(); _fcInstance = null; }
  document.querySelectorAll('.tp-cal-popover').forEach(e => e.remove());
  // Restore search bar (calendar and jira hide it)
  // Configure toolbar buttons per skill type
  const _noSearch = new Set(['github']);
  const _searchBtn = document.getElementById('tp-search-btn');
  if (_searchBtn) _searchBtn.style.display = _noSearch.has(type) ? 'none' : '';
  // Remove confluence scope selector injected into toolbar when switching away
  _cfState._scopeCleanup?.();
  document.getElementById('cf-scope-wrap')?.remove();
  // Reset search state
  const _srchPanel = document.getElementById('tp-toolbar-search');
  if (_srchPanel) _srchPanel.classList.add('hidden');
  const _ttl = document.getElementById('tp-title');
  if (_ttl) _ttl.style.display = '';
  if (_searchBtn) _searchBtn.style.display = _noSearch.has(type) ? 'none' : '';
  // Show "+" button for panes that support compose
  const _addPanes = { teams: 'New conversation', email: 'Compose email', onenote: 'New page', slack: 'Send DM', jira: 'Create issue' };
  const addBtn = document.getElementById('tp-add-btn');
  if (addBtn) {
    addBtn.style.display = _addPanes[type] ? '' : 'none';
    addBtn.title = _addPanes[type] || '';
    addBtn.onclick = null;
    addBtn.dataset.composing = '';
    addBtn.innerHTML = _TP_PLUS_SVG;
  }

  // Stop real-time polling when switching skills
  _stopThreadPolling();
  _stopChatListPolling();
  // Reset BOTH columns, search, and selected item when switching skills
  document.getElementById('tp-list-col').innerHTML = _gatorLoading();
  document.getElementById('tp-detail-col').innerHTML = _gatorDetailHint(type);
  _resetDetailHeader();
  document.getElementById('tp-search-input').value = '';
  tpState.searchQuery = '';
  tpState.selectedId = null;  // Clear stale ID from previous pane (prevents cross-pane ID leaks)

  { const _b = document.getElementById('tp-close-btn'); if (_b) _b.onclick = closeThirdPane; }

  // Search spinner helpers (shared across all app search handlers)
  const _tpSearchWrap = document.getElementById('tp-search-wrap');
  const _tpSpinner    = document.getElementById('tp-search-spinner');
  function _showSearchSpinner() {
    if (_tpSpinner)  _tpSpinner.classList.remove('hidden');
    if (_tpSearchWrap) _tpSearchWrap.classList.add('is-searching');
  }
  function _hideSearchSpinner() {
    if (_tpSpinner)  _tpSpinner.classList.add('hidden');
    if (_tpSearchWrap) _tpSearchWrap.classList.remove('is-searching');
  }

  // Set generic search handlers BEFORE tpLoadList so skill-specific init can override
  const _tpSearchInput = document.getElementById('tp-search-input');

  // Per-app placeholder text
  const _searchPlaceholders = {
    email:      'Search Outlook mail…',
    teams:      'Search Teams chats…',
    onenote:    'Search OneNote…',
    onedrive:   'Search OneDrive…',
    confluence: 'Search Confluence…',
    jira:       'Search issues…',
    slack:      'Search Slack threads…',
    github:     'Search GitHub…',
  };
  _tpSearchInput.placeholder = _searchPlaceholders[type] || 'Search…';

  // Email: debounced API search (falls back to local list for empty query)
  if (type === 'email') {
    let _emailSearchTimer = null;
    _tpSearchInput.oninput = (e) => {
      const q = e.target.value.trim();
      tpState.searchQuery = q;
      clearTimeout(_emailSearchTimer);
      if (!q) { _hideSearchSpinner(); renderEmailList(tpState.list, tpState._totalUnread || 0, { noAutoFocus: true }); return; }
      _showSearchSpinner();
      _emailSearchTimer = setTimeout(async () => {
        try {
          const res = await fetch(`/api/email/search?q=${encodeURIComponent(q)}`);
          if (!res.ok || tpState.type !== 'email') return;
          const data = await res.json();
          renderEmailList(data.messages || [], tpState._totalUnread || 0, { noAutoFocus: true, isSearchResults: true });
        } catch { /* silent */ } finally { _hideSearchSpinner(); }
      }, 400);
    };
    _tpSearchInput.onkeydown = null;
  // Teams: debounced API search (falls back to local list for empty query)
  } else if (type === 'teams') {
    // Two-tier search: show cached list instantly, then fetch full results from API.
    let _teamsSearchTimer = null;
    _tpSearchInput.oninput = (e) => {
      const q = e.target.value.trim();
      tpState.searchQuery = q;
      clearTimeout(_teamsSearchTimer);
      if (!q) { _hideSearchSpinner(); renderTeamsList(tpState.list); return; }
      // Tier 1: filter already-loaded chats instantly
      renderTeamsList(tpState.list);
      // Tier 2: fetch full results from API in background
      _showSearchSpinner();
      _teamsSearchTimer = setTimeout(async () => {
        try {
          const res = await fetch(`/api/teams/search?q=${encodeURIComponent(q)}`);
          if (!res.ok || tpState.type !== 'teams') return;
          const apiData = await res.json();
          if (tpState.searchQuery !== q) return; // query changed while fetching
          // Cache chat info so _loadTeamsThread can resolve the topic even when
          // the chat isn't in tpState.list yet (e.g. first click from search results).
          (apiData.chats || []).forEach(c => { if (c.id) _chatInfoCache.set(c.id, c); });
          // Render API results as search results — pre-filtered, sections expanded,
          // no per-section cap (renderTeamsList handles this via isSearchResults).
          renderTeamsList(apiData.chats || [], true);
        } catch { /* silent */ } finally { _hideSearchSpinner(); }
      }, 400);
    };
    _tpSearchInput.onkeydown = null;
  } else {
    _tpSearchInput.oninput = (e) => {
      tpState.searchQuery = e.target.value;
      _renderCurrentList();
    };
    _tpSearchInput.onkeydown = null;
  }

  tpLoadList();

  if (tpState.selectedId) {
    tpLoadDetail(tpState.selectedId);
  }
}

function closeThirdPane() {
  // Stop real-time polling
  _stopThreadPolling();
  _stopChatListPolling();
  // Destroy calendar if active
  if (_fcInstance) { _fcInstance.destroy(); _fcInstance = null; }
  document.querySelectorAll('.tp-cal-popover').forEach(e => e.remove());
  const _clc = document.getElementById('tp-left-col') || document.getElementById('tp-list-col');
  if (_clc) { _clc.classList.remove('tp-cal-hidden'); _clc.style.display = ''; }
  const _clr = document.getElementById('tp-list-resize');
  if (_clr) { _clr.classList.remove('tp-cal-hidden'); _clr.style.display = ''; }
  document.getElementById('tp-detail-col')?.classList.remove('tp-cal-full');
  document.getElementById('tp-right-col')?.classList.remove('tp-cal-full');

  const pane = document.getElementById('third-pane');
  pane.classList.remove('is-open');
  pane.classList.add('is-closing');
  setTimeout(() => { pane.classList.remove('is-closing'); pane.classList.add('hidden'); }, 540);
  tpState.type = null;
  tpState.selectedId = null;
  tpState.list = [];
  tpState.focusedIndex = -1;
  tpState.focusedId = null;
  saveTpState();
  // Restore third-pane-resize (main-resize is always visible; third-pane-resize hidden while pane is open)
  const tpResize = document.getElementById('third-pane-resize');
  if (tpResize) tpResize.style.display = '';

  // Sync rail active state back in app.js
  if (typeof onThirdPaneClosed === 'function') onThirdPaneClosed();
}

/* ── Manual refresh ──────────────────────────────────────── */

function tpRefresh() {
  const btn = document.getElementById('tp-refresh-btn');
  if (btn) {
    btn.style.animation = 'tp-spin 0.7s linear infinite';
    btn.disabled = true;
  }

  const done = () => {
    if (btn) {
      btn.style.animation = '';
      btn.disabled = false;
    }
  };

  // Invalidate list cache for current skill
  if (tpState.type) _clearListCache(tpState.type);
  // Reset delta sync state for email/teams so next fetch does a full re-sync
  if (tpState.type === 'email') fetch('/api/delta/reset?type=email', { method: 'POST' });
  if (tpState.type === 'teams') fetch('/api/delta/reset?type=teams_chats', { method: 'POST' });
  // Invalidate cache for currently open item so detail re-fetches fresh data
  if (tpState.selectedId) {
    tpThreadCache.delete(tpState.selectedId);
  }

  // Slack: bust all caches and re-init
  if (tpState.type === 'slack') {
    _slackState.channelCache = null;
    _slackState.dmCache = null;
    if (_slackState.messageCache) _slackState.messageCache.clear();
    _slackState.threadDetailCache.clear();
    _initSlackPane();
    setTimeout(done, 800);
    return;
  }

  // Confluence: bust cache and reload
  if (tpState.type === 'confluence') {
    _clearListCache('confluence');
    _cfState.allSpaces = [];
    _cfLoad();
    setTimeout(done, 800);
    return;
  }

  const listPromise = tpState.type === 'teams'
    ? _fetchTeamsList()
    : tpState.type === 'calendar'
    ? _refreshCalendar()
    : tpState.type === 'onedrive'
    ? (_odState.folderCache.clear(), _odState.sitesCache = null, _odState.drivesCache.clear(), _odState.recentCache = null, _odState.sharedCache = null, window._odSpecialFolderCache = {}, _fetchOneDriveList())
    : _fetchEmailList();

  const detailPromise = tpState.selectedId
    ? tpLoadDetail(tpState.selectedId)
    : Promise.resolve();

  Promise.all([listPromise, detailPromise]).finally(done);
}

/* ── List loading ────────────────────────────────────────── */

function tpLoadList() {
  if (tpState.type === 'teams') _fetchTeamsList();
  else if (tpState.type === 'email') _fetchEmailList();
  else if (tpState.type === 'onenote') _fetchOneNoteNotebooks();
  else if (tpState.type === 'calendar') _initCalendar();
  else if (tpState.type === 'onedrive') _fetchOneDriveList();
  else if (tpState.type === 'jira') _initJiraPane();
  else if (tpState.type === 'github') _initGithubPane();
  else if (tpState.type === 'slack') _initSlackPane();
  else if (tpState.type === 'confluence') _initConfluencePane();
}

function _renderCurrentList() {
  if (tpState.type === 'teams') renderTeamsList(tpState.list);
  else if (tpState.type === 'email') renderEmailList(tpState.list, tpState._totalUnread || 0);
  else if (tpState.type === 'onenote') renderOneNoteList(tpState.list, tpState._onenoteLevel || 'notebooks');
  else if (tpState.type === 'calendar') { /* FullCalendar manages its own rendering */ }
  else if (tpState.type === 'onedrive') _fetchOneDriveList();
}

function _showSkeletons(count = 6) {
  const col = document.getElementById('tp-list-col');
  col.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const s = document.createElement('div');
    s.className = 'tp-skeleton';
    s.innerHTML = `<div class="tp-skeleton-avatar"></div>
      <div class="tp-skeleton-lines">
        <div class="tp-skeleton-line"></div>
        <div class="tp-skeleton-line short"></div>
      </div>`;
    col.appendChild(s);
  }
}

// Open a URL in a new tab — uses anchor click instead of window.open because
// window.open is blocked in Electron/app context with noopener flag.
function _openUrl(url) {
  const a = document.createElement('a');
  a.href = url; a.target = '_blank'; a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ── Teams presence (#22) ─────────────────────────────────────
const _PRESENCE_LABELS = {
  Available: 'Available', Busy: 'Busy', DoNotDisturb: 'Do Not Disturb',
  BeRightBack: 'Be Right Back', Away: 'Appear Away', Offline: 'Appear Offline',
};

// SVG icons matching native Teams presence indicators.
// Busy = full-width minus bar; DND = shorter centered dot/bar to distinguish.
function _presenceIcon(key) {
  const icons = {
    Available:    `<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="6" fill="#22c55e"/><path d="M3.5 6l1.8 1.8 3.2-3.2" stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>`,
    Busy:         `<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="6" fill="#ef4444"/></svg>`,
    DoNotDisturb: `<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="6" fill="#ef4444"/><rect x="3.5" y="5.2" width="5" height="1.6" rx=".8" fill="white"/></svg>`,
    BeRightBack:  `<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="6" fill="#f59e0b"/><path d="M6 3.5v2.8l1.8 1.2" stroke="white" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>`,
    Away:         `<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="5" fill="none" stroke="#f59e0b" stroke-width="1.5"/><path d="M6 3.8v2.5l1.6 1.1" stroke="#f59e0b" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>`,
    Offline:      `<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="5" fill="none" stroke="#6b7280" stroke-width="1.5"/><circle cx="6" cy="6" r="2.5" fill="#6b7280"/></svg>`,
    Unknown:      `<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="5" fill="none" stroke="#6b7280" stroke-width="1.5"/></svg>`,
  };
  return icons[key] || icons.Unknown;
}

// ── Presence for OTHER users (DM list avatars + thread sender avatars) ──────────
// Cache: mri(lower) → { availability, ts }. Batch-fetched, refreshed on a 60s poll.
const _peerPresence = new Map();
const _PRESENCE_TTL = 55000; // slightly under the 60s poll so a poll always refreshes

// Derive a presence-queryable MRI (8:orgid:{guid}) from a message's sender fields.
// Returns '' when no AAD GUID is available (e.g. federated/consumer senders).
function _senderMriFromMsg(msg) {
  const raw = msg.sender_id || msg.sender_aad || '';
  const guid = raw.split(':').pop();
  return (guid && guid.includes('-')) ? `8:orgid:${guid}` : '';
}

// Map a Teams availability to its status color.
const _PRESENCE_COLORS = {
  Available: '#22c55e', Busy: '#ef4444', DoNotDisturb: '#ef4444',
  Away: '#f59e0b', BeRightBack: '#f59e0b', Offline: '#6b7280', Unknown: '#6b7280',
};

// Build the "bud" overlay SVG: a rounded lobe swelling out of the bottom-right rim.
// viewBox 0 0 100 100 maps to the avatar box; the bud center sits on the rim (r=50)
// at ~47° so it grows outward. A surface-colored halo separates it from the avatar.
// Louder states (Busy/DND) get a slightly bigger bud; DND/Away carry a tiny glyph.
function _presenceBudSVG(availability) {
  const c = _PRESENCE_COLORS[availability] || _PRESENCE_COLORS.Unknown;
  const loud = (availability === 'Busy' || availability === 'DoNotDisturb');
  const opacity = availability === 'Offline' ? 0.6 : 1;
  const ang = 47 * Math.PI / 180;
  const bx = 50 + 50 * Math.cos(ang), by = 50 + 50 * Math.sin(ang);
  const r = loud ? 17 : 14;
  let glyph = '';
  if (availability === 'DoNotDisturb') {
    glyph = `<rect x="${(bx - 6).toFixed(1)}" y="${(by - 1.6).toFixed(1)}" width="12" height="3.2" rx="1.6" fill="#fff"/>`;
  } else if (availability === 'Away' || availability === 'BeRightBack') {
    glyph = `<path d="M${bx.toFixed(1)} ${(by - 5).toFixed(1)} v5 l3.2 2" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`;
  }
  return `<svg viewBox="0 0 100 100">`
    + `<circle cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="${r + 2.5}" fill="var(--surface,#0f172a)"/>`
    + `<circle cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="${r}" fill="${c}" opacity="${opacity}"/>`
    + glyph
    + `</svg>`;
}

// Overlay the presence bud on an avatar element for the given MRI.
// No-op if presence isn't known yet (bud appears on next batch resolve).
function _applyPresenceDot(avatarEl, mri) {
  if (!avatarEl || !mri) return;
  avatarEl.dataset.presenceMri = mri;
  const rec = _peerPresence.get(mri.toLowerCase());
  let dot = avatarEl.querySelector('.tp-presence-dot');
  if (!rec) { if (dot) dot.remove(); return; }
  if (!dot) {
    dot = document.createElement('span');
    dot.className = 'tp-presence-dot';
    avatarEl.appendChild(dot);
    if (getComputedStyle(avatarEl).position === 'static') avatarEl.style.position = 'relative';
  }
  dot.innerHTML = _presenceBudSVG(rec.availability);
  dot.title = rec.availability;
}

// Batch-fetch presence for the given MRIs (skips fresh cache entries), then invoke
// the optional onUpdate callback so callers can re-apply dots to their avatars.
async function _fetchPeerPresence(mris, onUpdate) {
  const now = Date.now();
  const need = [...new Set(mris.filter(Boolean))].filter(m => {
    const rec = _peerPresence.get(m.toLowerCase());
    return !rec || (now - rec.ts) > _PRESENCE_TTL;
  });
  if (!need.length) { if (onUpdate) onUpdate(); return; }
  try {
    const r = await fetch('/api/teams/presence/batch', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mris: need }),
    });
    if (!r.ok) return;
    const data = await r.json();
    const presence = data.presence || {};
    for (const [mri, p] of Object.entries(presence)) {
      _peerPresence.set(mri.toLowerCase(), { availability: p.availability || 'Unknown', ts: Date.now() });
    }
    if (onUpdate) onUpdate();
  } catch {}
}

async function _initTeamsPresence() {
  if (document.getElementById('tp-presence-btn')) return;
  // Place presence dot right after the Teams title, before the toolbar actions
  const title = document.getElementById('tp-title');
  if (!title) return;

  const btn = document.createElement('button');
  btn.id = 'tp-presence-btn';
  btn.title = 'Set presence';
  btn.style.cssText = 'background:none;border:none;cursor:pointer;padding:0 3px;display:inline-flex;align-items:center;border-radius:4px;margin-left:3px;flex-shrink:0;line-height:0;vertical-align:middle;';
  btn.innerHTML = `<span id="tp-presence-dot">${_presenceIcon('Unknown')}</span>`;
  title.appendChild(btn);

  // Load current presence
  try {
    const r = await fetch('/api/teams/presence');
    if (r.ok) _updatePresenceDot((await r.json()).availability);
  } catch {}

  // Dropdown
  btn.addEventListener('click', e => {
    e.stopPropagation();
    document.getElementById('tp-presence-dropdown')?.remove();
    const dd = document.createElement('div');
    dd.id = 'tp-presence-dropdown';
    dd.style.cssText = 'position:fixed;z-index:9999;background:var(--surface,#1e1e2e);border:1px solid var(--border2,#334155);border-radius:8px;padding:.35rem 0;box-shadow:0 8px 24px rgba(0,0,0,.45);min-width:170px;';
    Object.entries(_PRESENCE_LABELS).forEach(([key, label]) => {
      const item = document.createElement('div');
      item.style.cssText = 'display:flex;align-items:center;gap:.55rem;padding:.38rem .85rem;cursor:pointer;font-size:.82rem;color:var(--text);transition:background .1s;';
      item.innerHTML = `${_presenceIcon(key)}<span>${label}</span>`;
      item.addEventListener('mouseenter', () => item.style.background = 'var(--surface2)');
      item.addEventListener('mouseleave', () => item.style.background = '');
      item.addEventListener('click', async () => {
        dd.remove();
        _updatePresenceDot(key);
        try { await fetch('/api/teams/presence', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({availability:key}) }); } catch {}
      });
      dd.appendChild(item);
    });
    document.body.appendChild(dd);
    const rect = btn.getBoundingClientRect();
    dd.style.top = (rect.bottom + 4) + 'px';
    dd.style.left = rect.left + 'px';
    const dismiss = ev => { if (!dd.contains(ev.target) && ev.target !== btn) { dd.remove(); document.removeEventListener('click', dismiss, true); } };
    setTimeout(() => document.addEventListener('click', dismiss, true), 0);
  });
}

function _updatePresenceDot(availability) {
  const dot = document.getElementById('tp-presence-dot');
  const btn = document.getElementById('tp-presence-btn');
  if (dot) dot.innerHTML = _presenceIcon(availability);
  if (btn) btn.title = `Presence: ${_PRESENCE_LABELS[availability] || availability}`;
}

async function _fetchTeamsList() {
  // Fresh cache hit — render and skip fetch
  const _cached = _getListCache('teams');
  if (_cached) {
    tpState.list = _cached.data;
    tpState._hasViewpoint = _cached.extra.hasViewpoint || false;
    tpState._channels = _cached.extra.channels || [];
    tpState._hasMore = _cached.extra.hasMore || false;
    tpState._skypeCursor = _cached.extra.skypeCursor || '';
    renderTeamsList(tpState.list);
    _prewarmTeamsThreads(tpState.list);
    _startChatListPolling();
    _initTeamsPresence();
    return;
  }
  // Stale-while-revalidate: show old data instantly, fetch delta in background
  const _stale = _getStaleCache('teams');
  if (_stale) {
    tpState.list = _stale.data;
    tpState._hasViewpoint = _stale.extra.hasViewpoint || false;
    tpState._channels = _stale.extra.channels || [];
    tpState._hasMore = _stale.extra.hasMore || false;
    tpState._skypeCursor = _stale.extra.skypeCursor || '';
    renderTeamsList(tpState.list);
  } else {
    _showSkeletons();
  }
  try {
    const [chatRes, chRes] = await Promise.all([
      fetch('/api/teams/chats?delta=true'),
      fetch('/api/channels/search').catch(() => null),
    ]);
    if (tpState.type !== 'teams') return;
    if (chatRes.status === 401 || chatRes.status === 403) {
      tpThreadCache.clear();
      _showListError('Teams session expired — re-authenticate in Settings', _fetchTeamsList);
      _showAuthOverlay('Teams');
      return;
    }
    if (chatRes.status === 503) {
      // Skype token still being minted after sign-in (errorCode 911 lag). Show a
      // transient "connecting" state and auto-retry — no manual click needed.
      _showSkeletons();
      if (tpState.type === 'teams') setTimeout(() => { if (tpState.type === 'teams') _fetchTeamsList(); }, 3000);
      return;
    }
    if (!chatRes.ok) {
      const err = await chatRes.json().catch(() => ({}));
      _showListError('Teams error: ' + (err.detail || chatRes.status), _fetchTeamsList);
      return;
    }
    const data = await chatRes.json();
    tpState.list = data.chats || [];
    tpState._hasViewpoint = data.has_viewpoint || false;
    tpState._hasMore = !!data.has_more;
    tpState._skypeCursor = data.skype_cursor || '';
    // Persist Teams chats globally so channel dropdown can use them even after pane closes
    window._teamsChatsCache = tpState.list;
    // Team channels (fetched in parallel)
    tpState._channels = [];
    if (chRes?.ok) {
      const chData = await chRes.json();
      tpState._channels = (chData.channels || []).filter(c => c.type === 'channel');
    }
    tpState._channelsFetched = true;
    _setListCache('teams', tpState.list, { hasViewpoint: tpState._hasViewpoint, channels: tpState._channels, hasMore: tpState._hasMore, skypeCursor: tpState._skypeCursor });
    _dismissAuthOverlay();
    renderTeamsList(tpState.list);
    _startChatListPolling();
    _prewarmTeamsThreads(tpState.list);
    _initTeamsPresence();  // presence dot in toolbar (#22)
  } catch (e) {
    _showListError('Could not load Teams chats: ' + e.message, _fetchTeamsList);
  }
}

function _prefetchTeamsThread(chat, { force = false } = {}) {
  if (!chat?.id || chat.id.startsWith('ch::')) return;
  const cached = tpThreadCache.get(chat.id);
  if (!force && cached && Date.now() - cached.ts < TP_CACHE_TTL) return;
  fetch(`/api/teams/chats/${encodeURIComponent(chat.id)}/messages`)
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data) return;
      tpThreadCache.set(chat.id, {
        data: {
          messages: data.messages || [],
          chat,
          myId: data.my_id || '',
          peer_last_read: data.peer_last_read || '',
        },
        ts: Date.now(),
      });
    })
    .catch(() => {}); // silent — this is best-effort
}

// Pre-warm likely-to-open chats (unread first, then recent)
function _prewarmTeamsThreads(chats) {
  const candidates = [...(chats || [])]
    .filter(c => c.id && !c.id.startsWith('ch::'))
    .sort((a, b) => ((b.unread_count || 0) - (a.unread_count || 0)) ||
      (new Date(b.last_message_time || 0) - new Date(a.last_message_time || 0)))
    .slice(0, 3);
  candidates.forEach(chat => _prefetchTeamsThread(chat));
}

async function _fetchEmailList() {
  // Guard: unknown persisted filter values (pre-Sent/Draft sessions) default to 'all'
  if (!['all', 'unread', 'sent', 'drafts'].includes(tpState.filter)) tpState.filter = 'all';

  const _folderSuffix = { all: '', unread: '_unread', sent: '_sent', drafts: '_drafts' };
  const _cacheKey = 'email' + (_folderSuffix[tpState.filter] || '');
  const _folderParam = { all: 'inbox', unread: 'inbox', sent: 'sentitems', drafts: 'drafts' }[tpState.filter] || 'inbox';

  // Fresh cache hit — render and skip fetch
  const _cached = _getListCache(_cacheKey);
  if (_cached) {
    tpState.list = _cached.data;
    tpState._totalUnread = _cached.extra.totalUnread || 0;
    renderEmailList(tpState.list, tpState._totalUnread);
    return;
  }
  // Stale-while-revalidate: show old data instantly, fetch in background
  const _stale = _getStaleCache(_cacheKey);
  const _hasStale = !!_stale;
  if (_stale) {
    tpState.list = _stale.data;
    tpState._totalUnread = _stale.extra.totalUnread || 0;
    renderEmailList(tpState.list, tpState._totalUnread);
  } else {
    _showSkeletons();
  }
  try {
    const filterParam = tpState.filter === 'unread' ? '&filter=unread' : '';
    // Delta sync only for inbox; Sent/Drafts always do a full fetch
    const deltaParam = _folderParam === 'inbox' ? '&delta=true' : '';
    const res = await fetch(`/api/email/inbox?top=50&folder=${_folderParam}${filterParam}${deltaParam}`);
    if (tpState.type !== 'email') return;
    if (res.status === 401) { _showAuthOverlay('Email'); return; }
    if (!res.ok) {
      const folderLabel = { sentitems: 'Sent', drafts: 'Drafts' }[_folderParam] || 'Inbox';
      _showListError(`Could not load ${folderLabel} — please try again.`, _fetchEmailList);
      return;
    }
    const data = await res.json();
    tpState.list = (data.messages || []).sort((a, b) => {
      const aU = !a.is_read ? 1 : 0, bU = !b.is_read ? 1 : 0;
      if (aU !== bU) return bU - aU;
      return new Date(b.received_at || 0) - new Date(a.received_at || 0);
    });
    tpState._totalUnread = data.total_unread || 0;
    _setListCache(_cacheKey, tpState.list, { totalUnread: tpState._totalUnread });
    _dismissAuthOverlay();
    // Background refresh — don't steal focus or scroll (user may be reading an email)
    renderEmailList(tpState.list, tpState._totalUnread, { noAutoFocus: _hasStale });
  } catch {
    _showListError('Could not load email — please try again.', _fetchEmailList);
  }
}

/* ── Context menu helper ─────────────────────────────────── */
function _showCtxMenu(e, items) {
  e.preventDefault();
  document.querySelector('.tp-ctx-menu')?.remove();

  const menu = document.createElement('div');
  menu.className = 'tp-ctx-menu';
  // Inline styles guarantee full-bleed hover — no CSS caching issues
  Object.assign(menu.style, {
    position: 'fixed',
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--surface)',
    border: '1px solid var(--border2)',
    borderRadius: 'var(--radius-sm)',
    boxShadow: '0 4px 16px rgba(0,0,0,.45)',
    padding: '0',
    zIndex: '999',
    minWidth: '180px',
    overflow: 'hidden',
  });

  items.forEach(({ icon, label, action }) => {
    const row = document.createElement('div');
    row.className = 'tp-ctx-item';
    Object.assign(row.style, {
      display: 'flex',
      alignItems: 'center',
      gap: '.5rem',
      padding: '.45rem .8rem',
      fontSize: '.8rem',
      color: 'var(--text)',
      cursor: 'pointer',
      whiteSpace: 'nowrap',
      background: 'transparent',
      border: 'none',
      margin: '0',
      boxSizing: 'border-box',
    });
    row.innerHTML = `<span style="font-size:.85rem;width:1rem;text-align:center">${icon}</span><span>${label}</span>`;
    row.addEventListener('mouseenter', () => { row.style.background = 'var(--surface2)'; });
    row.addEventListener('mouseleave', () => { row.style.background = 'transparent'; });
    row.addEventListener('click', () => { menu.remove(); action(); });
    menu.appendChild(row);
  });

  document.body.appendChild(menu);
  const { innerWidth: vw, innerHeight: vh } = window;
  const { offsetWidth: mw, offsetHeight: mh } = menu;
  menu.style.left = Math.min(e.clientX, vw - mw - 8) + 'px';
  menu.style.top  = Math.min(e.clientY, vh - mh - 8) + 'px';

  const dismiss = (ev) => { if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener('mousedown', dismiss); } };
  setTimeout(() => document.addEventListener('mousedown', dismiss), 0);
}

/* ── Teams list render ───────────────────────────────────── */

function renderTeamsList(chats, isSearchResults = false) {
  const col = document.getElementById('tp-list-col');
  col.innerHTML = '';

  // Keep the poll-render signature in sync with what's on screen so the next
  // poll only re-renders on a real change (prevents periodic flicker).
  if (!isSearchResults) {
    tpState._listSig = (chats || []).map(c =>
      `${c.id}:${c.last_message_time || ''}:${c.unread_count || 0}:${(c.last_message || '').slice(0, 40)}`
    ).join('|');
  }

  // Unread driven by server: viewpoint.lastMessageReadDateTime vs last_message_time
  chats.forEach(c => { c._unread = (c.unread_count || 0) > 0; });
  const totalUnread = chats.filter(c => c._unread).length;
  const unreadLabel = totalUnread > 0 ? `Unread (${totalUnread})` : 'Unread';

  // Header row: filter chips + load older
  const header = document.createElement('div');
  header.className = 'tp-list-header';
  header.style.cssText = 'display:flex;align-items:center;gap:.3rem;padding:.4rem .6rem;border-bottom:1px solid var(--border,#1e293b)';

  const filterNames = ['all', 'unread'];
  const filterLabels = ['All', unreadLabel];
  filterNames.forEach((name, i) => {
    const chip = document.createElement('button');
    chip.className = 'tp-filter-chip' + (tpState.filter === name ? ' active' : '');
    chip.textContent = filterLabels[i];
    chip.style.cssText = 'padding:.2rem .5rem;font-size:.72rem;border-radius:10px;border:1px solid var(--border,#334155);background:' + (tpState.filter === name ? 'var(--accent,#6c63ff)' : 'none') + ';color:' + (tpState.filter === name ? '#fff' : 'var(--text-sub,#94a3b8)') + ';cursor:pointer;font-weight:600;white-space:nowrap;transition:all .15s';
    chip.addEventListener('click', () => { tpState.filter = name; _renderCurrentList(); });
    header.appendChild(chip);
  });

  const spacer = document.createElement('div');
  spacer.style.flex = '1';
  header.appendChild(spacer);


  col.appendChild(header);

  const scroll = document.createElement('div');
  scroll.className = 'tp-list-scroll';
  col.appendChild(scroll);

  // isSearchResults: chats are already filtered by the API — don't re-filter them
  // locally, and treat the view as "search mode" for section expand / no-cap below.
  // (Previously the caller cleared tpState.searchQuery to skip the local filter,
  //  which also defeated the search-mode expand/uncap logic and hid matches — #118.)
  const q = isSearchResults ? '' : tpState.searchQuery.toLowerCase();
  const searchMode = isSearchResults || !!q;
  let filtered = chats;
  if (tpState.filter === 'unread') filtered = chats.filter(c => c._unread);
  if (q) filtered = filtered.filter(c =>
    (c.topic || '').toLowerCase().includes(q) ||
    (c.last_message || '').toLowerCase().includes(q)
  );

  // Split into DMs and groups
  const dms = filtered.filter(c => c.chat_type === 'oneOnOne');
  const groups = filtered.filter(c => c.chat_type === 'group');
  const meetings = filtered.filter(c => c.chat_type === 'meeting');

  // Team channels (from parallel fetch, no unread filter). The API search response
  // doesn't include channels, so always filter them by the active query string —
  // use the real query even in isSearchResults mode (where local q is blanked).
  let channels = tpState._channels || [];
  const channelQ = q || (searchMode ? tpState.searchQuery.toLowerCase() : '');
  if (channelQ) channels = channels.filter(c =>
    (c.channel_name || '').toLowerCase().includes(channelQ) ||
    (c.team_name || '').toLowerCase().includes(channelQ)
  );
  else if (searchMode) channels = [];  // search mode but no query → no channel noise

  const byRecent = (a, b) => new Date(b.last_message_time || 0) - new Date(a.last_message_time || 0);
  dms.sort(byRecent);
  groups.sort(byRecent);
  meetings.sort(byRecent);

  // Build sections
  const sections = [];
  if (dms.length) sections.push({ label: 'Direct Messages', items: dms, type: 'chat' });
  if (groups.length) sections.push({ label: 'Groups', items: groups, type: 'chat' });
  if (meetings.length) sections.push({ label: 'Meetings', items: meetings, type: 'chat' });
  if (channels.length && tpState.filter !== 'unread') {
    const _teamOrder = [];
    const _byTeam = {};
    channels.forEach(ch => {
      const key = ch.team_id || ch.team_name || 'Unknown';
      if (!_byTeam[key]) {
        _byTeam[key] = { teamId: key, teamName: ch.team_name || 'Unknown', items: [] };
        _teamOrder.push(key);
      }
      _byTeam[key].items.push(ch);
    });
    const _teams = _teamOrder.map(key => _byTeam[key]);
    sections.push({ label: 'Channels', items: channels, teams: _teams, type: 'channels-group' });
  }
  if (!sections.length) {
    scroll.innerHTML = `<div class="tp-empty-state" style="height:120px"><span>No conversations</span></div>`;
    return;
  }

  // Collapse state — DMs open by default, others collapsed
  if (!tpState._sectionCollapsed) tpState._sectionCollapsed = {};
  const _defaultCollapsed = { 'Direct Messages': false, 'Groups': true, 'Meetings': true, 'Channels': true };

  let globalIdx = 0;
  sections.forEach(section => {
    // ── Channels group: CHANNELS parent header + per-team sub-sections ──
    if (section.type === 'channels-group') {
      // Parent "CHANNELS" section label — same style as DMs/Groups/Meetings
      const parentKey = 'Channels';
      const collapsedPref = tpState._sectionCollapsed?.[parentKey] ?? true;
      const parentCollapsed = searchMode ? false : collapsedPref;

      const parentLabel = document.createElement('div');
      parentLabel.className = 'tp-section-label tp-section-collapsible tp-team-channel-header';
      parentLabel.setAttribute('aria-expanded', String(!parentCollapsed));
      parentLabel.setAttribute('aria-label', 'Channels, ' + (parentCollapsed ? 'collapsed' : 'expanded'));
      parentLabel.innerHTML = '<span class="tp-section-chevron">' + (parentCollapsed ? '▶' : '▼') + '</span> Channels <span class="tp-section-count">' + section.items.length + '</span>';
      parentLabel.addEventListener('click', () => {
        if (!tpState._sectionCollapsed) tpState._sectionCollapsed = {};
        tpState._sectionCollapsed[parentKey] = !parentCollapsed;
        renderTeamsList(tpState.list);
      });
      scroll.appendChild(parentLabel);

      if (parentCollapsed) { globalIdx += section.items.length; return; }

      // Per-team sub-sections inside the channels group
      const groupBody = document.createElement('div');
      groupBody.className = 'tp-section-body';
      scroll.appendChild(groupBody);

      (section.teams || []).forEach((team, teamIdx) => {
        const lsKey = 'tpChannelExpand:' + team.teamId;
        const stored = localStorage.getItem(lsKey);
        const defaultExpanded = teamIdx === 0;
        const isExpanded = stored !== null ? stored === 'true' : defaultExpanded;
        const showExpanded = !!channelQ || isExpanded;

        // Team sub-header — smaller, indented, not uppercase, no sticky
        const teamHeader = document.createElement('button');
        teamHeader.className = 'tp-team-channel-header';
        teamHeader.setAttribute('aria-expanded', String(showExpanded));
        teamHeader.setAttribute('aria-label', team.teamName + ' channels, ' + (showExpanded ? 'expanded' : 'collapsed'));
        teamHeader.style.cssText = 'display:flex;align-items:center;width:100%;padding:.2rem .6rem .2rem .8rem;background:none;border:none;border-bottom:1px solid var(--border,#1e293b);cursor:pointer;color:var(--text-sub,#94a3b8);font-size:.6rem;font-weight:600;letter-spacing:.04em;text-transform:none;gap:.25rem;text-align:left';
        teamHeader.innerHTML = '<span class="tp-section-chevron" style="font-size:.45rem">' + (showExpanded ? '▼' : '▶') + '</span>' +
          '<span>' + escapeHtml(team.teamName) + '</span>' +
          '<span style="margin-left:auto;opacity:.5">' + team.items.length + '</span>';

        teamHeader.addEventListener('click', () => {
          const nowExpanded = teamHeader.getAttribute('aria-expanded') !== 'true';
          teamHeader.setAttribute('aria-expanded', String(nowExpanded));
          teamHeader.setAttribute('aria-label', team.teamName + ' channels, ' + (nowExpanded ? 'expanded' : 'collapsed'));
          teamHeader.querySelector('.tp-section-chevron').textContent = nowExpanded ? '▼' : '▶';
          localStorage.setItem(lsKey, String(nowExpanded));
          const tbody = teamHeader.nextElementSibling;
          if (tbody) tbody.style.display = nowExpanded ? '' : 'none';
        });
        groupBody.appendChild(teamHeader);

        const teamBody = document.createElement('div');
        teamBody.style.display = showExpanded ? '' : 'none';

        const maxShowTeam = 20;
        let chIdx = 0;
        team.items.forEach(ch => {
          if (chIdx >= maxShowTeam) { chIdx++; return; }
          chIdx++;
          const idx = globalIdx++;
          const compId = 'ch::' + ch.team_id + '::' + ch.channel_id;
          const item = document.createElement('div');
          item.className = 'tp-list-item' +
            (compId === tpState.selectedId ? ' active' : '') +
            (compId === tpState.focusedId ? ' focused' : '');
          item.dataset.idx = idx;
          item.dataset.id = compId;
          item.style.paddingLeft = '1.8rem';
          item.innerHTML = '<div class="tp-avatar tp-avatar-teams" style="font-size:.65rem;width:18px;height:18px;background:transparent;border:1px solid var(--text-sub);color:var(--text-sub);flex-shrink:0">#</div>' +
            '<div class="tp-item-body"><div class="tp-item-name" style="font-size:.75rem">' + escapeHtml(ch.channel_name) + '</div></div>';
          item.addEventListener('click', () => {
            tpState.focusedIndex = idx;
            tpState.focusedId = compId;
            tpState.selectedId = compId;
            _loadChannelThread(ch.team_id, ch.channel_id, ch.channel_name);
            scroll.querySelectorAll('.tp-list-item').forEach(el => el.classList.toggle('active', el.dataset.id === compId));
          });
          teamBody.appendChild(item);
        });

        if (chIdx > maxShowTeam) {
          const remaining = team.items.length - maxShowTeam;
          const more = document.createElement('button');
          more.className = 'tp-load-more-btn tp-section-load-more';
          more.style.paddingLeft = '1.8rem';
          more.textContent = 'Show ' + remaining + ' more';
          more.addEventListener('click', () => {
            team.items.slice(maxShowTeam).forEach(ch => {
              const idx = globalIdx++;
              const compId = 'ch::' + ch.team_id + '::' + ch.channel_id;
              const item = document.createElement('div');
              item.className = 'tp-list-item' + (compId === tpState.selectedId ? ' active' : '');
              item.dataset.idx = idx;
              item.dataset.id = compId;
              item.style.paddingLeft = '1.8rem';
              item.innerHTML = '<div class="tp-avatar tp-avatar-teams" style="font-size:.65rem;width:18px;height:18px;background:transparent;border:1px solid var(--text-sub);color:var(--text-sub);flex-shrink:0">#</div>' +
                '<div class="tp-item-body"><div class="tp-item-name" style="font-size:.75rem">' + escapeHtml(ch.channel_name) + '</div></div>';
              item.addEventListener('click', () => {
                tpState.focusedId = compId;
                tpState.selectedId = compId;
                _loadChannelThread(ch.team_id, ch.channel_id, ch.channel_name);
                scroll.querySelectorAll('.tp-list-item').forEach(el => el.classList.toggle('active', el.dataset.id === compId));
              });
              teamBody.insertBefore(item, more);
            });
            more.remove();
          });
          teamBody.appendChild(more);
        }

        groupBody.appendChild(teamBody);
      });

      return; // skip generic section renderer
    }

    const sKey = section.label;
    const unreadCount = section.items.filter(c => c._unread).length;
    const collapsedPref = tpState._sectionCollapsed[sKey] ?? (_defaultCollapsed[sKey] ?? true);
    // While searching, force ALL sections open — collapsing a section would hide
    // matches (e.g. a "Fire" group match behind a collapsed Groups header) and make
    // search look like it's missing results (#118). UX: any category with unread also
    // auto-opens so users don't have to hunt.
    const isCollapsed = (searchMode || unreadCount > 0) ? false : collapsedPref;
    if (unreadCount > 0) tpState._sectionCollapsed[sKey] = false;

    // Section header — clickable to collapse/expand
    const sectionLabel = document.createElement('div');
    sectionLabel.className = 'tp-section-label tp-section-collapsible';
    sectionLabel.innerHTML = `<span class="tp-section-chevron">${isCollapsed ? '\u25B6' : '\u25BC'}</span> ${escapeHtml(section.label)} <span class="tp-section-count">${section.items.length}${unreadCount ? ` \u00B7 <span class="tp-section-unread">${unreadCount} new</span>` : ''}</span>`;
    sectionLabel.addEventListener('click', () => {
      tpState._sectionCollapsed[sKey] = !isCollapsed;
      renderTeamsList(tpState.list);
    });
    scroll.appendChild(sectionLabel);

    if (isCollapsed) {
      globalIdx += section.items.length;
      return; // skip rendering items
    }

    // Section content container
    const sectionBody = document.createElement('div');
    sectionBody.className = 'tp-section-body';
    scroll.appendChild(sectionBody);

    const SECTION_PAGE_SIZE = 25;
    const _shownKey = '_shown_' + sKey;
    if (!tpState[_shownKey]) tpState[_shownKey] = SECTION_PAGE_SIZE;
    // While searching OR filtering to unread, show ALL matches in each section (no
    // per-section cap / "Show more" button) — paging through a filtered/search view is
    // bad UX (#118). The cap only applies to normal unfiltered browsing.
    const _showAll = searchMode || tpState.filter === 'unread';
    const maxShow = _showAll ? Number.MAX_SAFE_INTEGER : tpState[_shownKey];

    if (section.type === 'channel') {
      const byTeam = {};
      section.items.forEach(ch => {
        const team = ch.team_name || 'Team';
        (byTeam[team] = byTeam[team] || []).push(ch);
      });
      let channelIdx = 0;
      Object.entries(byTeam).forEach(([teamName, chs]) => {
        chs.forEach(ch => {
          if (channelIdx >= maxShow) { channelIdx++; return; }
          channelIdx++;
          const idx = globalIdx++;
          const compId = `ch::${ch.team_id}::${ch.channel_id}`;
          const item = document.createElement('div');
          item.className = 'tp-list-item' +
            (compId === tpState.selectedId ? ' active' : '') +
            (compId === tpState.focusedId ? ' focused' : '');
          item.dataset.idx = idx;
          item.dataset.id = compId;
          item.innerHTML = `
            <div class="tp-avatar tp-avatar-teams" style="font-size:.7rem;background:transparent;border:1.5px solid var(--text-sub);color:var(--text-sub)">#</div>
            <div class="tp-item-body">
              <div class="tp-item-name">${escapeHtml(ch.channel_name)}</div>
              <div class="tp-item-preview">${escapeHtml(teamName)}</div>
            </div>`;
          item.addEventListener('click', () => {
            tpState.focusedIndex = idx;
            tpState.focusedId = compId;
            tpState.selectedId = compId;
            _loadChannelThread(ch.team_id, ch.channel_id, ch.channel_name);
            scroll.querySelectorAll('.tp-list-item').forEach(el => el.classList.toggle('active', el.dataset.id === compId));
          });
          sectionBody.appendChild(item);
        });
      });
      // Per-section "Load more" for channels
      if (channelIdx > maxShow) {
        const more = document.createElement('button');
        more.className = 'tp-load-more-btn tp-section-load-more';
        more.textContent = `Show more channels (${section.items.length - maxShow} remaining)`;
        more.addEventListener('click', () => {
          const scr = document.querySelector('.tp-list-scroll');
          const savedTop = scr ? scr.scrollTop : 0;
          tpState[_shownKey] += SECTION_PAGE_SIZE;
          renderTeamsList(tpState.list);
          // Restore scroll on the NEW .tp-list-scroll created by renderTeamsList
          const newScr = document.querySelector('.tp-list-scroll');
          if (newScr) newScr.scrollTop = savedTop;
        });
        sectionBody.appendChild(more);
      }
    } else {
      const visibleItems = section.items.slice(0, maxShow);
      visibleItems.forEach(chat => {
        const hasUnread = chat._unread;
        const idx = globalIdx++;
        const item = document.createElement('div');
        item.className = 'tp-list-item' +
          (chat.id === tpState.selectedId ? ' active' : '') +
          (chat.id === tpState.focusedId ? ' focused' : '') +
          (hasUnread ? ' unread' : '');
        item.dataset.idx = idx;
        item.dataset.id = chat.id;

        const initials = getInitials(chat.topic);
        const timeStr = relativeTime(chat.last_message_time);
        const senderPrefix = chat.last_sender ? `${chat.last_sender}: ` : '';
        const pinIcon = _isPinned('teams', chat.id) ? '<span class="tp-pin-inline">\uD83D\uDCCC</span>' : '';

        const _peerMri = (chat.chat_type === 'oneOnOne') ? (chat.peer_mri || '') : '';
        item.innerHTML = `
          <div class="tp-avatar tp-avatar-teams"${_peerMri ? ` data-presence-mri="${escapeHtml(_peerMri)}"` : ''}>${escapeHtml(initials)}</div>
          <div class="tp-item-body">
            <div class="tp-item-name${hasUnread ? ' unread' : ''}">${pinIcon}${escapeHtml(chat.topic || 'Chat')}</div>
            <div class="tp-item-preview">${escapeHtml(senderPrefix + (chat.last_message || ''))}</div>
          </div>
          <div class="tp-item-meta">
            <div class="tp-item-time">${timeStr}</div>
            ${hasUnread ? '<div class="tp-unread-badge">\u2022</div>' : ''}
          </div>`;
        if (_peerMri) _applyPresenceDot(item.querySelector('.tp-avatar'), _peerMri);

        item.addEventListener('click', () => {
          tpState.focusedIndex = idx;
          tpState.focusedId = chat.id;
          tpLoadDetail(chat.id);
        });

        item.addEventListener('contextmenu', e => {
          const menuItems = chat._unread
            ? [{
                icon: '\u2714\uFE0F', label: 'Mark as read',
                action: () => {
                  // Preserve scroll around re-render — renderTeamsList recreates the
                  // scroll container, so we must re-query after render (#123)
                  const _savedTop = (document.querySelector('.tp-list-scroll') || {}).scrollTop || 0;
                  chat.unread_count = 0; chat._unread = false; renderTeamsList(tpState.list);
                  const _newScr = document.querySelector('.tp-list-scroll');
                  if (_newScr) _newScr.scrollTop = _savedTop;
                  fetch(`/api/teams/chats/${encodeURIComponent(chat.id)}/mark-read`, { method: 'POST' }).catch(() => {});
                },
              }]
            : [{
                icon: '\u2709\uFE0F', label: 'Mark as unread',
                action: () => {
                  const _savedTop2 = (document.querySelector('.tp-list-scroll') || {}).scrollTop || 0;
                  chat.unread_count = 1; chat._unread = true; renderTeamsList(tpState.list);
                  const _newScr2 = document.querySelector('.tp-list-scroll');
                  if (_newScr2) _newScr2.scrollTop = _savedTop2;
                  fetch(`/api/teams/chats/${encodeURIComponent(chat.id)}/mark-unread`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ last_message_time: chat.last_message_time || '' }),
                  }).then(() => {
                    // After the bookmark is set on the server, force a fresh chat list
                    // fetch (bypassing the delta cache) so unread_count reflects the
                    // new bookmark. Without this, the delta returns the stale read state
                    // and AI Gator reverts the unread indicator seconds later.
                    _clearListCache('teams');
                    setTimeout(() => { if (tpState.type === 'teams') _fetchTeamsList(); }, 1000);
                  }).catch(() => {});
                },
              }];
          const _chatPinned = _isPinned('teams', chat.id);
          menuItems.push({
            icon: _chatPinned ? '\u274C' : '\uD83D\uDCCC',
            label: _chatPinned ? 'Unpin from Chat' : 'Pin to Chat',
            action: () => _togglePin('teams', chat.id, chat.topic || 'Chat', { type: chat.chat_type || 'chat' }),
          });
          _showCtxMenu(e, menuItems);
        });

        // Pin indicator — inline icon + left border
        if (_isPinned('teams', chat.id)) {
          item.classList.add('tp-item-pinned');
        }
        sectionBody.appendChild(item);
      });

      // Per-section button: show more locally OR fetch more from API.
      // Never show these while searching — search shows all matches at once (#118).
      const hasLocalMore = !searchMode && section.items.length > maxShow;
      const hasRemoteMore = !searchMode && !hasLocalMore && tpState._hasMore && tpState._skypeCursor;
      if (hasLocalMore || hasRemoteMore) {
        const more = document.createElement('button');
        more.className = 'tp-load-more-btn tp-section-load-more';
        if (hasLocalMore) {
          more.textContent = `Show more (${section.items.length - maxShow} remaining)`;
          more.addEventListener('click', () => {
            const scr = document.querySelector('.tp-list-scroll');
            const savedTop = scr ? scr.scrollTop : 0;
            tpState[_shownKey] += SECTION_PAGE_SIZE;
            renderTeamsList(tpState.list);
            const newScr = document.querySelector('.tp-list-scroll');
            if (newScr) newScr.scrollTop = savedTop;
          });
        } else {
          more.textContent = 'Load more';
          more.addEventListener('click', async () => {
            more.disabled = true;
            more.textContent = 'Loading…';
            const savedTop = (document.querySelector('.tp-list-scroll') || {}).scrollTop || 0;
            try {
              const res = await fetch(`/api/teams/chats?skype_cursor=${encodeURIComponent(tpState._skypeCursor)}`);
              if (!res.ok) throw new Error(`HTTP ${res.status}`);
              const data = await res.json();
              const newChats = data.chats || [];
              tpState._hasMore = !!data.has_more;
              tpState._skypeCursor = data.skype_cursor || '';
              const existing = new Set(tpState.list.map(c => c.id));
              const unique = newChats.filter(c => !existing.has(c.id));
              if (!unique.length) { more.textContent = 'No more'; return; }
              tpState.list.push(...unique);
              const typeFilter = { 'Direct Messages': 'oneOnOne', 'Groups': 'group', 'Meetings': 'meeting' };
              const newInSection = unique.filter(c => c.chat_type === typeFilter[sKey]).length;
              tpState[_shownKey] += newInSection || SECTION_PAGE_SIZE;
              _clearListCache('teams');
              _setListCache('teams', tpState.list, { hasViewpoint: tpState._hasViewpoint, channels: tpState._channels, hasMore: tpState._hasMore, skypeCursor: tpState._skypeCursor });
              renderTeamsList(tpState.list);
              const newScr = document.querySelector('.tp-list-scroll');
              if (newScr) newScr.scrollTop = savedTop;
            } catch {
              more.textContent = 'Retry';
              more.disabled = false;
            }
          });
        }
        sectionBody.appendChild(more);
      }
    }
    globalIdx = globalIdx; // ensure correct index for next section
  });

  // Empty-state notice when channels fetch completed but user is in no teams
  const hasTeamChannels = sections.some(s => s.type === 'channels-group');
  if (!hasTeamChannels && tpState._channelsFetched && tpState.filter !== 'unread') {
    const empty = document.createElement('div');
    empty.style.cssText = 'padding:.8rem .6rem;color:var(--text-sub,#94a3b8);font-size:.75rem;text-align:center;border-top:1px solid var(--border,#1e293b)';
    empty.textContent = 'No channels found';
    scroll.appendChild(empty);
  }

  // Soft-cap notice when > 200 channels total
  const totalChannels = (tpState._channels || []).length;
  if (hasTeamChannels && totalChannels > 200 && tpState.filter !== 'unread') {
    const notice = document.createElement('div');
    notice.style.cssText = 'padding:.4rem .6rem;font-size:.68rem;color:var(--text-sub,#94a3b8);border-top:1px solid var(--border,#1e293b)';
    notice.textContent = 'Showing ' + totalChannels + ' channels — search to filter';
    scroll.appendChild(notice);
  }

  // (Load older button is now in the header bar)

  // Wire "+" button (in search bar) to open new compose
  const addBtn = document.getElementById('tp-add-btn');
  if (addBtn) {
    addBtn.onclick = () => _showNewTeamsCompose();
    addBtn.style.display = '';
  }

  // Update rail badge
  if (typeof updateRailBadge === 'function') updateRailBadge('teams', totalUnread);

  // ── Keyboard navigation (shared helper) ──────────────────
  _wireListKeyboard(scroll, el => {
    // Update focused + active state in-place on open
    scroll.querySelectorAll('.tp-list-item').forEach(r => r.classList.remove('focused'));
    el.classList.add('focused');
    const id = el.dataset.id;
    if (id) {
      tpState.focusedId = id;
      tpState.selectedId = id;
      tpLoadDetail(id);
    }
    requestAnimationFrame(() => scroll.focus({ preventScroll: true }));
  });
  // Also wire click to update focused class
  scroll.querySelectorAll('.tp-list-item').forEach((el, i) => {
    el.dataset.idx = i;
    el.addEventListener('click', () => {
      scroll.querySelectorAll('.tp-list-item').forEach(r => r.classList.remove('focused'));
      el.classList.add('focused');
      if (el.dataset.id) tpState.focusedId = el.dataset.id;
      if (scroll._openTimer) clearTimeout(scroll._openTimer);
      requestAnimationFrame(() => scroll.focus({ preventScroll: true }));
    }, { once: false });
  });
  requestAnimationFrame(() => _safeScrollFocus(scroll));

  // Presence dots on DM avatars — batch-fetch for visible DM peers, then start the poll
  _refreshListPresence();
  _startListPresencePoll();
}

// Scan currently-rendered DM avatars, batch-fetch their presence, re-apply dots.
function _refreshListPresence() {
  const avatars = [...document.querySelectorAll('.tp-list-item .tp-avatar[data-presence-mri]')];
  if (!avatars.length) return;
  const mris = avatars.map(a => a.dataset.presenceMri).filter(Boolean);
  _fetchPeerPresence(mris, () => {
    document.querySelectorAll('.tp-list-item .tp-avatar[data-presence-mri]').forEach(a => {
      _applyPresenceDot(a, a.dataset.presenceMri);
    });
  });
}

// Scan sender avatars in an open thread, batch-fetch presence, re-apply dots.
function _refreshThreadPresence(scroll) {
  const root = scroll || document;
  const avatars = [...root.querySelectorAll('.tp-msg-avatar[data-presence-mri]')];
  if (!avatars.length) return;
  const mris = avatars.map(a => a.dataset.presenceMri).filter(Boolean);
  _fetchPeerPresence(mris, () => {
    root.querySelectorAll('.tp-msg-avatar[data-presence-mri]').forEach(a => {
      _applyPresenceDot(a, a.dataset.presenceMri);
    });
  });
}

let _listPresenceTimer = null;
function _startListPresencePoll() {
  if (_listPresenceTimer) return;
  _listPresenceTimer = setInterval(() => {
    // Stop polling if the Teams list is no longer mounted
    if (!document.querySelector('.tp-list-item .tp-avatar[data-presence-mri]')) {
      clearInterval(_listPresenceTimer); _listPresenceTimer = null; return;
    }
    _refreshListPresence();
  }, 60000);
}

/* ── Shared list keyboard navigation helper ─────────────────
 * Wires ArrowUp/Down/j/k/Enter + 250ms debounced auto-open onto any scroll
 * container whose children are .tp-list-item elements.
 * onOpen(el) — called when an item should be opened (click or Enter or debounce).
 * Returns AbortController so caller can clean up on re-render.
 * ────────────────────────────────────────────────────────── */
// Only focus if nothing the user is actively typing in has focus
function _safeScrollFocus(scroll) {
  const a = document.activeElement;
  if (a && (a.matches('input, textarea, [contenteditable]') || a === scroll)) return;
  scroll.focus({ preventScroll: true });
}

function _wireListKeyboard(scroll, onOpen) {
  if (scroll._kbAbort) scroll._kbAbort.abort();
  if (scroll._openTimer) { clearTimeout(scroll._openTimer); scroll._openTimer = null; }
  scroll._kbAbort = new AbortController();

  scroll.tabIndex = 0;
  scroll.style.outline = 'none';

  function _visibleItems() {
    return Array.from(scroll.querySelectorAll('.tp-list-item')).filter(
      el => el.offsetParent !== null  // exclude items hidden by collapsed sections
    );
  }

  function _scrollIntoViewIfNeeded(el) {
    const sr = scroll.getBoundingClientRect();
    const er = el.getBoundingClientRect();
    if (er.top < sr.top) scroll.scrollTop -= (sr.top - er.top);
    else if (er.bottom > sr.bottom) scroll.scrollTop += (er.bottom - sr.bottom);
  }

  function _move(delta) {
    const items = _visibleItems();
    if (!items.length) return;
    const cur = items.findIndex(el => el.classList.contains('focused'));
    const next = Math.max(0, Math.min(items.length - 1, (cur < 0 ? 0 : cur) + delta));
    if (next === cur) return;
    items.forEach((el, i) => el.classList.toggle('focused', i === next));
    _scrollIntoViewIfNeeded(items[next]);
    // Debounced auto-open — 250ms pause triggers open (like native Teams)
    clearTimeout(scroll._openTimer);
    scroll._openTimer = setTimeout(() => onOpen(items[next]), 250);
  }

  scroll.addEventListener('keydown', e => {
    switch (e.key) {
      case 'ArrowDown': case 'j': e.preventDefault(); e.stopPropagation(); _move(1); break;
      case 'ArrowUp':   case 'k': e.preventDefault(); e.stopPropagation(); _move(-1); break;
      case 'Enter': {
        e.preventDefault(); e.stopPropagation();
        clearTimeout(scroll._openTimer);
        const focused = scroll.querySelector('.tp-list-item.focused');
        if (focused) onOpen(focused);
        break;
      }
      case 'Home': e.preventDefault(); e.stopPropagation(); _move(-9999); break;
      case 'End':  e.preventDefault(); e.stopPropagation(); _move(9999); break;
    }
  }, { signal: scroll._kbAbort.signal });

  return scroll._kbAbort;
}

/* ── Email list render ───────────────────────────────────── */

function renderEmailList(messages, totalUnread, { noAutoFocus = false, isSearchResults = false } = {}) {
  const col = document.getElementById('tp-list-col');
  // Preserve scroll position across re-renders (background refresh, mark-read, etc.)
  const _prevScroll = col.querySelector('.tp-list-scroll');
  const _savedScrollTop = _prevScroll ? _prevScroll.scrollTop : 0;
  col.innerHTML = '';

  const unreadLabel = totalUnread > 0 ? `Unread (${totalUnread})` : 'Unread';

  const header = document.createElement('div');
  header.className = 'tp-list-header';
  const _emailTabOrder = ['all', 'unread', 'sent', 'drafts'];
  const _emailTabLabels = ['All', unreadLabel, 'Sent', 'Drafts'];
  const _activeTabIdx = Math.max(0, _emailTabOrder.indexOf(tpState.filter));
  const tabs = _makeFilterTabs(_emailTabLabels, _activeTabIdx, (idx) => {
    tpState.filter = _emailTabOrder[idx] ?? 'all';
    tpState.list = [];
    _clearListCache('email');
    _clearListCache('email_unread');
    _clearListCache('email_sent');
    _clearListCache('email_drafts');
    _fetchEmailList();
  });
  header.appendChild(tabs);
  col.appendChild(header);

  // Wire shared "+" button to compose
  const _addBtn = document.getElementById('tp-add-btn');
  if (_addBtn) _addBtn.onclick = () => {
    const isOpen = _addBtn.dataset.composing === '1';
    if (isOpen) {
      _addBtn.dataset.composing = '';
      _addBtn.innerHTML = _TP_PLUS_SVG;
      _addBtn.title = 'Compose email';
      const detailCol = document.getElementById('tp-detail-col');
      if (tpState.selectedId) tpLoadDetail(tpState.selectedId);
      else {
        if (detailCol) detailCol.innerHTML = _gatorDetailHint('email');
        _resetDetailHeader();
      }
    } else {
      _showNewEmailCompose();
    }
  };

  const scroll = document.createElement('div');
  scroll.className = 'tp-list-scroll';
  col.appendChild(scroll);

  // isSearchResults: API already searched server-side — skip client re-filter
  // (same pattern as renderTeamsList). Without this, body-only matches get dropped.
  const q = isSearchResults ? '' : tpState.searchQuery.toLowerCase();
  let filtered = q
    ? messages.filter(m =>
        (m.subject || '').toLowerCase().includes(q) ||
        (m.from_name || '').toLowerCase().includes(q) ||
        (m.preview || '').toLowerCase().includes(q))
    : [...messages];

  // Preserve the server-returned order — do not re-sort mid-session.
  // Sorting by unread-first would shift items when the user marks read/unread,
  // which is disorienting. Initial sort is applied once at fetch time.

  if (filtered.length === 0) {
    const _emptyMsg = isSearchResults
      ? 'No emails found'
      : ({
          all: 'No emails in inbox',
          unread: 'No unread emails',
          sent: 'No sent emails',
          drafts: 'No drafts saved',
        }[tpState.filter] || 'No emails');
    scroll.innerHTML = `<div class="tp-empty-state" style="height:120px"><span>${_emptyMsg}</span></div>`;
    return;
  }

  filtered.forEach((email, idx) => {
    const isUnread = !email.is_read;
    const item = document.createElement('div');
    item.className = 'tp-list-item' +
      (email.id === tpState.selectedId ? ' active' : '') +
      (idx === tpState.focusedIndex ? ' focused' : '') +
      (isUnread ? ' unread' : '');
    item.dataset.idx = idx;
    item.dataset.id = email.id;

    const initials = getInitials(email.from_name);
    const timeStr = relativeTime(email.received_at);
    const pinIcon = _isPinned('email', email.id) ? '<span class="tp-pin-inline">\uD83D\uDCCC</span>' : '';

    item.innerHTML = `
      <div class="tp-avatar tp-avatar-email">${escapeHtml(initials)}</div>
      <div class="tp-item-body">
        <div class="tp-item-name${isUnread ? ' unread' : ''}">${pinIcon}${escapeHtml(email.from_name || '')}</div>
        <div class="tp-item-preview">${escapeHtml(email.subject || '(no subject)')}</div>
        <div class="tp-item-preview">${escapeHtml((email.preview || '').slice(0, 55))}</div>
      </div>
      <div class="tp-item-meta">
        <div class="tp-item-time">${timeStr}</div>
        ${isUnread ? '<div class="tp-unread-badge">\u2022</div>' : ''}
      </div>`;

    item.addEventListener('click', () => {
      // Update focused class in-place on click
      scroll.querySelectorAll('.tp-list-item').forEach(el => el.classList.remove('focused'));
      item.classList.add('focused');
      tpState.focusedIndex = idx;
      if (scroll._openTimer) clearTimeout(scroll._openTimer);  // cancel any pending debounce
      tpLoadDetail(email.id);
      // Restore focus to scroll container so keyboard navigation keeps working
      requestAnimationFrame(() => scroll.focus({ preventScroll: true }));
    });

    item.addEventListener('contextmenu', e => {
      // Update read state in-place — no re-sort, no position change
      function _toggleReadInPlace(markRead) {
        fetch(`/api/email/messages/${encodeURIComponent(email.id)}/markread`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_read: markRead }),
        }).then(r => r.json()).then(d => {
          if (!d.ok) return;
          email.is_read = markRead;
          if (markRead) {
            tpState._totalUnread = Math.max(0, (tpState._totalUnread || 0) - 1);
          } else {
            tpState._totalUnread = Math.min(tpState.list.length, (tpState._totalUnread || 0) + 1);
          }
          // Update this row's visual state without moving it
          item.classList.toggle('unread', !markRead);
          const nameEl = item.querySelector('.tp-item-name');
          if (nameEl) nameEl.classList.toggle('unread', !markRead);
          const badge = item.querySelector('.tp-unread-badge');
          if (markRead && badge) badge.remove();
          if (!markRead && !badge) {
            const meta = item.querySelector('.tp-item-meta');
            if (meta) { const b = document.createElement('div'); b.className = 'tp-unread-badge'; b.textContent = '•'; meta.appendChild(b); }
          }
          // Update the Unread tab label count only
          const unreadLabel = tpState._totalUnread > 0 ? `Unread (${tpState._totalUnread})` : 'Unread';
          const unreadTab = document.querySelectorAll('.tp-filter-tab')[1];
          if (unreadTab) unreadTab.textContent = unreadLabel;
          if (typeof updateRailBadge === 'function' && (tpState.filter === 'all' || tpState.filter === 'unread')) {
            updateRailBadge('email', tpState._totalUnread);
          }
        }).catch(() => {});
      }
      const menuItems = email.is_read
        ? [{ icon: '✉️', label: 'Mark as unread', action: () => _toggleReadInPlace(false) }]
        : [{ icon: '✔️', label: 'Mark as read',   action: () => _toggleReadInPlace(true)  }];
      const _emailPinned = _isPinned('email', email.id);
      menuItems.push({
        icon: _emailPinned ? '\u274C' : '\uD83D\uDCCC',
        label: _emailPinned ? 'Unpin from Chat' : 'Pin to Chat',
        action: () => _togglePin('email', email.id, email.subject || '(no subject)', { from: email.from_name || '' }),
      });
      _showCtxMenu(e, menuItems);
    });

    // Pin indicator
    if (_isPinned('email', email.id)) {
      item.classList.add('tp-item-pinned');
    }
    scroll.appendChild(item);
  });

  // Restore scroll position after all items are in the DOM
  if (_savedScrollTop) scroll.scrollTop = _savedScrollTop;

  // ── Keyboard navigation (shared helper) ──────────────────
  _wireListKeyboard(scroll, el => {
    const emailId = el.dataset.id;
    if (!emailId) return;
    scroll.querySelectorAll('.tp-list-item').forEach(r => r.classList.remove('focused'));
    el.classList.add('focused');
    tpState.focusedIndex = parseInt(el.dataset.idx, 10) || 0;
    tpLoadDetail(emailId);
    requestAnimationFrame(() => scroll.focus({ preventScroll: true }));
  });
  if (!noAutoFocus) requestAnimationFrame(() => _safeScrollFocus(scroll));

  // "Load more" button
  const loadMore = document.createElement('button');
  loadMore.className = 'tp-load-more-btn';
  loadMore.textContent = 'Load more emails';
  loadMore.addEventListener('click', async () => {
    loadMore.disabled = true;
    loadMore.textContent = 'Loading\u2026';
    try {
      const skip = tpState.list.length;
      const filterParam = tpState.filter === 'unread' ? '&filter=unread' : '';
      const res = await fetch(`/api/email/inbox?top=50&skip=${skip}${filterParam}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const more = data.messages || [];
      if (!more.length) {
        loadMore.textContent = 'No more emails';
        return;
      }
      const existing = new Set(tpState.list.map(m => m.id));
      const unique = more.filter(m => !existing.has(m.id));
      tpState.list.push(...unique);
      _clearListCache('email');
      _clearListCache('email_unread');
      renderEmailList(tpState.list, data.total_unread ?? tpState._totalUnread);
    } catch {
      loadMore.textContent = 'Failed — tap to retry';
      loadMore.disabled = false;
    }
  });
  scroll.appendChild(loadMore);

  // Update rail badge — only when viewing inbox-based folders (not Sent/Drafts)
  if (typeof updateRailBadge === 'function' && (tpState.filter === 'all' || tpState.filter === 'unread')) {
    updateRailBadge('email', totalUnread);
  }
}

/* ── Detail loading ──────────────────────────────────────── */

async function tpLoadDetail(id) {
  tpState.selectedId = id;
  // Keep keyboard/click focus aligned with the opened row so a stale positional
  // "focused" highlight can't linger on a different chat after the list re-sorts.
  tpState.focusedId = id;
  saveTpState();

  // If we were in compose mode, flip the toolbar +/X toggle back to + so its
  // label/icon matches the now-active chat rather than the prior draft.
  _resetComposeToggleBtn();

  // Update active + focused state in list — match by data-id across all list item types
  document.querySelectorAll('.tp-list-item, .jira-issue-row, .cf-page-row').forEach(el => {
    const match = el.dataset.id === id;
    el.classList.toggle('active', match);
    if (el.classList.contains('tp-list-item')) el.classList.toggle('focused', match);
  });

  if (tpState.type === 'teams') {
    if (id.startsWith('ch::')) {
      const parts = id.split('::');
      const ch = (tpState._channels || []).find(c => c.team_id === parts[1] && c.channel_id === parts[2]);
      await _loadChannelThread(parts[1], parts[2], ch?.channel_name || 'Channel');
    } else {
      await _loadTeamsThread(id);
    }
  } else if (tpState.type === 'email') await _loadEmailDetail(id);
  else if (tpState.type === 'onenote') await _loadOneNotePageDetail(id);
  else if (tpState.type === 'calendar') { /* handled by popover on eventClick */ }
  else if (tpState.type === 'onedrive') { /* folder clicks handled inline by renderOneDriveList */ }
}

async function _loadTeamsThread(chatId) {
  // Switching conversations cancels any reply that was drafted (unsent) in another
  // chat — a pending reply must never carry over to a different conversation.
  if (_teamsReplyTo && _teamsReplyTo.chat_id !== chatId) _setTeamsReplyTo(null);
  // Mark read visually immediately; also call Graph to sync native Teams
  const chat = tpState.list.find(c => c.id === chatId);
  const hadUnreadAtOpen = Boolean((chat?.unread_count || 0) > 0 || chat?._unread);
  if (chat) { chat.unread_count = 0; chat._unread = false; }
  _markListItemRead(chatId);
  fetch(`/api/teams/chats/${encodeURIComponent(chatId)}/mark-read`, { method: 'POST' }).catch(() => {});

  const cached = tpThreadCache.get(chatId);
  if (cached && Date.now() - cached.ts < TP_CACHE_TTL) {
    try {
      // Seed cursor from cache so _hasOlder() works for blockquote seek navigation
      if (!tpState._threadCursor) tpState._threadCursor = {};
      if (!tpState._threadCursor[chatId]) {
        tpState._threadCursor[chatId] = {
          has_more: !!cached.data.has_more,
          skype_cursor: cached.data.skype_cursor || '',
          next_link: cached.data.next_link || '',
        };
      }
      renderTeamsThread(cached.data.messages, cached.data.chat, cached.data.myId || '', cached.data);
      _startThreadPolling(chatId);
      // If we opened from an unread badge, sync immediately so the newly arrived
      // message appears right away instead of waiting for the 15s poll tick.
      if (hadUnreadAtOpen) _syncActiveTeamsThread(chatId);
      return;
    } catch {
      tpThreadCache.delete(chatId); // bad cache entry — fall through to fetch
    }
  }

  const col = document.getElementById('tp-detail-col');
  col.innerHTML = _gatorLoading();

  try {
    const chatInfo = tpState.list.find(c => c.id === chatId) || _chatInfoCache.get(chatId) || { topic: 'Chat', id: chatId };
    const threadRes = await fetch(`/api/teams/chats/${encodeURIComponent(chatId)}/messages`);
    if (threadRes.status === 401 || threadRes.status === 403) {
      _showAuthOverlay('Teams');
      return;
    }
    if (!threadRes.ok) {
      const err = await threadRes.json().catch(() => ({}));
      col.innerHTML = `<div class="tp-empty-state"><span>Error: ${escapeHtml(err.detail || String(threadRes.status))}</span>
        <button class="tp-ai-btn" onclick="_loadTeamsThread('${escapeHtml(chatId)}')">Retry</button></div>`;
      return;
    }
    const data = await threadRes.json();
    const payload = { messages: data.messages || [], chat: chatInfo, myId: data.my_id || '',
                     peer_last_read: data.peer_last_read || '',
                     next_link: data.next_link || '', skype_cursor: data.skype_cursor || '',
                     has_more: !!data.has_more };
    tpThreadCache.set(chatId, { data: payload, ts: Date.now() });
    // Seed the dedicated cursor store — pollers never touch this, so the cursor
    // survives concurrent sync writes throughout the history-loading session (#118).
    if (!tpState._threadCursor) tpState._threadCursor = {};
    tpState._threadCursor[chatId] = { has_more: !!data.has_more, skype_cursor: data.skype_cursor || '', next_link: data.next_link || '' };
    renderTeamsThread(payload.messages, payload.chat, payload.myId, payload);
    _startThreadPolling(chatId);
  } catch (e) {
    col.innerHTML = `<div class="tp-empty-state"><span>Could not load conversation: ${escapeHtml(e.message)}</span>
      <button class="tp-ai-btn" onclick="_loadTeamsThread('${escapeHtml(chatId)}')">Retry</button></div>`;
  }
}

/* ── Real-time: active thread polling (15s) ──────────────────── */
let _activeThreadPoller = null;
let _activeThreadChatId = null;

const HOT_CHAT_MIN_INTERVAL = 5000;
const HOT_CHAT_MAX_INTERVAL = 15000;
const HOT_CHAT_DECAY_MS = 5 * 60 * 1000;
const HOT_CHAT_IDLE_POLLS = 3;
const HOT_CHAT_MAX_TRACKED = 5;
const _hotChatState = new Map(); // chatId -> {timer, interval, idlePolls, lastActivity, lastMessageId, lastHash}

function _startThreadPolling(chatId) {
  _stopThreadPolling();
  _activeThreadChatId = chatId;
  _promoteHotChat(chatId, 'opened');
  _activeThreadPoller = setInterval(() => {
    if (tpState.type !== 'teams' || tpState.selectedId !== chatId) { _stopThreadPolling(); return; }
    _syncActiveTeamsThread(chatId);
  }, 15000);
}

function _syncActiveTeamsThread(chatId) {
  fetch(`/api/teams/chats/${encodeURIComponent(chatId)}/messages`)
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data || tpState.selectedId !== chatId) return;
      // Skip the cache write if older history is currently being loaded — the history
      // loader owns the cursor and message list; a concurrent sync write would wipe it.
      if (tpState._historyLoading === chatId) return;
      const newMsgs = data.messages || [];
      const cached = tpThreadCache.get(chatId);
      const chatInfo = tpState.list.find(c => c.id === chatId) || _chatInfoCache.get(chatId) || { topic: 'Chat', id: chatId };
      // Preserve accumulated history + pagination cursor — the sync only fetches the
      // latest page (no cursor), so replacing messages and dropping the cursor would
      // prevent scroll-triggered history pages from loading after page 2 (#118).
      const prevData = cached?.data || {};
      const prevMsgs = prevData.messages || [];
      const existingIds2 = new Set(prevMsgs.map(m => m.id));
      const brandNew = newMsgs.filter(m => !existingIds2.has(m.id));
      // Append-only: keep all accumulated history (older pages loaded by scroll-up).
      // NEVER touch has_more/skype_cursor/next_link — those are owned exclusively by
      // _loadTeamsThread (initial) and _loadOlderMessages (history pages). The sync
      // only knows about the latest page and must not corrupt the pagination state (#118).
      const mergedForCache = brandNew.length > 0 ? [...prevMsgs, ...brandNew] : prevMsgs;
      tpThreadCache.set(chatId, {
        data: {
          messages: mergedForCache, chat: chatInfo, myId: data.my_id || '',
          peer_last_read: data.peer_last_read || '',
          has_more: prevData.has_more || false,
          next_link: prevData.next_link || '',
          skype_cursor: prevData.skype_cursor || '',
        },
        ts: Date.now(),
      });
      const scroll = document.querySelector('.tp-thread-scroll');
      if (scroll) {
        const wasAtBottom = (scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 60);
        const existingMap = new Map([...scroll.querySelectorAll('[data-msg-id]')].map(el => [el.dataset.msgId, el]));
        const sorted = [...newMsgs].sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
        let appended = false;
        let mutated = false;
        sorted.forEach(msg => {
          if (!msg.id || msg.id.startsWith('_optimistic_')) return;
          const existingEl = existingMap.get(msg.id);
          if (!existingEl) {
            // Before appending, evict any optimistic bubble for the same message.
            // Race: send response may not have updated dataset.msgId yet when poll fires.
            if (msg.is_mine) {
              const optimisticEl = scroll.querySelector('[data-msg-id^="_optimistic_"]');
              if (optimisticEl) {
                optimisticEl.dataset.msgId = msg.id; // claim the ID so no duplicate on retry
                existingMap.set(msg.id, optimisticEl); // treat it as the existing element
                return; // skip appending — optimistic bubble already represents this message
              }
            }
            const node = _buildTeamsMessage(msg, chatId);
            if (node) {
              scroll.appendChild(node);
              existingMap.set(msg.id, node);
              appended = true;
              mutated = true;
            }
          } else {
            const prevHash = existingEl.dataset.reactionHash || '';
            const newHash = _teamsReactionHash(msg.reactions || []);
            // Normalise ISO timestamps to seconds precision before comparing — Graph sometimes
            // returns different sub-second formats (e.g. ".1230000Z" vs ".123Z") that would
            // otherwise trigger a spurious rebuild, clobbering body_html with plain text.
            const _normTs = ts => ts ? ts.replace(/(\.\d{3})\d*(Z)/, '$1$2') : '';
            const prevModified = _normTs(existingEl.dataset.lastModified || '');
            const newModified  = _normTs(msg.last_modified_at || '');
            if (prevHash !== newHash || prevModified !== newModified) {
              // Only rebuild if body content actually changed too, or reactions changed.
              // This prevents a timestamp-only flicker from wiping formatted body_html.
              const prevBodyHtml = existingEl.querySelector('.tp-msg-text')?.innerHTML || '';
              const newBodyHtml  = msg.body_html || '';
              const bodyChanged  = newBodyHtml && prevBodyHtml !== newBodyHtml;
              const reactChanged = prevHash !== newHash;
              if (reactChanged || bodyChanged || !prevModified) {
                const replacement = _buildTeamsMessage(msg, chatId);
                if (replacement) {
                  existingEl.replaceWith(replacement);
                  existingMap.set(msg.id, replacement);
                  mutated = true;
                }
              } else {
                // Timestamp drifted but content identical — just update the stored ts silently
                existingEl.dataset.lastModified = msg.last_modified_at || '';
              }
            }
          }
        });
        // Lazy-load new images
        scroll.querySelectorAll('img[data-teams-src]').forEach(img => {
          if (img.dataset.teamsSrc) {
            img.src = `/api/teams/proxy-image?url=${encodeURIComponent(img.dataset.teamsSrc)}`;
            delete img.dataset.teamsSrc;
          }
        });
        if (appended && wasAtBottom) scroll.scrollTop = scroll.scrollHeight;
          const meta = _hotChatState.get(chatId);
          if (meta) {
            meta.lastHash = _teamsMessageSetHash(newMsgs);
          }
          if (mutated) {
            if (meta) {
              meta.lastActivity = Date.now();
              meta.idlePolls = 0;
              const latest = newMsgs[newMsgs.length - 1];
              if (latest?.id) meta.lastMessageId = latest.id;
            }
            _promoteHotChat(chatId, appended ? 'active-new' : 'active-update');
          }
      }
    }).catch(() => {});
}

function _stopThreadPolling() {
  if (_activeThreadPoller) { clearInterval(_activeThreadPoller); _activeThreadPoller = null; }
  _activeThreadChatId = null;
}

function _demoteHotChat(chatId, reason = 'idle') {
  const meta = _hotChatState.get(chatId);
  if (!meta) return;
  if (meta.timer) clearTimeout(meta.timer);
  _hotChatState.delete(chatId);
}

function _scheduleHotChatPoll(chatId) {
  const meta = _hotChatState.get(chatId);
  if (!meta) return;
  if (meta.timer) clearTimeout(meta.timer);
  meta.timer = setTimeout(() => _runHotChatPoll(chatId), meta.interval);
}

function _promoteHotChat(chatId, reason = 'activity') {
  if (!chatId) return;
  const now = Date.now();
  let meta = _hotChatState.get(chatId);
  if (!meta) {
    if (_hotChatState.size >= HOT_CHAT_MAX_TRACKED) {
        let oldestId = null;
        let oldestTime = Infinity;
        _hotChatState.forEach((value, key) => {
          if (value.lastActivity < oldestTime) {
          oldestTime = value.lastActivity;
          oldestId = key;
        }
      });
      if (oldestId) _demoteHotChat(oldestId, 'capacity');
    }
    const cached = tpThreadCache.get(chatId);
    const lastMsg = cached?.data?.messages?.slice(-1)?.[0]?.id || null;
    const lastHash = _teamsMessageSetHash(cached?.data?.messages || []);
    meta = {
      timer: null,
      interval: HOT_CHAT_MIN_INTERVAL,
      idlePolls: 0,
      lastActivity: now,
      lastMessageId: lastMsg,
      lastHash,
    };
    _hotChatState.set(chatId, meta);
    _scheduleHotChatPoll(chatId);
    return;
  }
  meta.lastActivity = now;
  meta.idlePolls = 0;
  if (!meta.lastHash) {
    const cached = tpThreadCache.get(chatId);
    meta.lastHash = _teamsMessageSetHash(cached?.data?.messages || []);
  }
  if (meta.interval !== HOT_CHAT_MIN_INTERVAL) {
    meta.interval = HOT_CHAT_MIN_INTERVAL;
  }
  _scheduleHotChatPoll(chatId);
}

async function _runHotChatPoll(chatId) {
  const meta = _hotChatState.get(chatId);
  if (!meta) return;
  // Guard: if another poll is already in-flight for this chat, skip.
  // This prevents timer proliferation when _promoteHotChat reschedules while a fetch is pending.
  if (meta.polling) return;
  const now = Date.now();
  if (now - meta.lastActivity > HOT_CHAT_DECAY_MS) {
    _demoteHotChat(chatId, 'decay');
    return;
  }
  if (tpState.type === 'teams' && tpState.selectedId === chatId) {
    _scheduleHotChatPoll(chatId);
    return;
  }
  meta.polling = true;
  // Clear the timer ref — timer has fired. _scheduleHotChatPoll called during the
  // fetch will set meta.timer to a new ID; we check that at the end to avoid doubling up.
  meta.timer = null;
  try {
    const res = await fetch(`/api/teams/chats/${encodeURIComponent(chatId)}/messages`);
    if (!res.ok) throw new Error(`poll ${res.status}`);
    const data = await res.json();
      // Skip cache writes while history is being loaded (same guard as _syncActiveTeamsThread).
      if (tpState._historyLoading === chatId) { meta.polling = false; if (!meta.timer) _scheduleHotChatPoll(chatId); return; }
      const newMsgs = data.messages || [];
      const latest = newMsgs.length ? (newMsgs[newMsgs.length - 1]?.id || null) : null;
      const messageHash = _teamsMessageSetHash(newMsgs);
      const prevHash = meta.lastHash || '';
      const hasNewMessage = !!(latest && latest !== meta.lastMessageId);
      const hasContentChange = messageHash !== prevHash;

      if (hasNewMessage || hasContentChange) {
        meta.lastMessageId = latest || null;
        meta.lastHash = messageHash;
        meta.interval = HOT_CHAT_MIN_INTERVAL;
        meta.idlePolls = 0;
        meta.lastActivity = now;
        const cached = tpThreadCache.get(chatId);
        const chatInfo = cached?.data?.chat || tpState.list?.find(c => c.id === chatId) || { id: chatId, topic: 'Chat' };
        // Preserve pagination cursor AND accumulated history from the existing cache.
        // The poller only fetches the latest page — it must not wipe the older messages
        // the user has already loaded by scrolling, and must not clear the backward cursor
        // (_loadOlderMessages stored skype_cursor so page-3+ can still load).
        const prevData = tpThreadCache.get(chatId)?.data || {};
        const prevMsgs = prevData.messages || [];
        const existingIds = new Set(prevMsgs.map(m => m.id));
        const brandNewMsgs = newMsgs.filter(m => !existingIds.has(m.id));
        const mergedMsgs = brandNewMsgs.length > 0 ? [...prevMsgs, ...brandNewMsgs] : prevMsgs;
        // Same rule: never touch has_more/cursor — owned by history-loading path only (#118).
        tpThreadCache.set(chatId, {
          data: {
            messages: mergedMsgs, chat: chatInfo, myId: data.my_id || '',
            peer_last_read: data.peer_last_read || '',
            has_more: prevData.has_more || false,
            next_link: prevData.next_link || '',
            skype_cursor: prevData.skype_cursor || '',
          },
          ts: now,
        });
      } else {
        meta.idlePolls += 1;
        if (meta.idlePolls >= HOT_CHAT_IDLE_POLLS && meta.interval < HOT_CHAT_MAX_INTERVAL) {
          meta.interval = Math.min(HOT_CHAT_MAX_INTERVAL, meta.interval + 5000);
        }
      }
  } catch (err) {
    meta.interval = Math.min(HOT_CHAT_MAX_INTERVAL, meta.interval * 2);
  }
  meta.polling = false;
  if (meta.interval > HOT_CHAT_MAX_INTERVAL) meta.interval = HOT_CHAT_MAX_INTERVAL;
  // Only schedule the next poll if _promoteHotChat didn't already schedule one
  // while this fetch was in-flight (meta.timer would be non-null in that case).
  if (!meta.timer) _scheduleHotChatPoll(chatId);
}

/* ── Real-time: chat list background refresh (60s) ──────────── */
let _chatListPoller = null;

function _startChatListPolling() {
  _stopChatListPolling();
  _chatListPoller = setInterval(() => {
    if (tpState.type !== 'teams') { _stopChatListPolling(); return; }
    fetch('/api/teams/chats?delta=true')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data || tpState.type !== 'teams') return;
        const newChats = data.chats || [];
        if (!newChats.length) return;
        // Detect changed chats — invalidate their thread cache
        const oldMap = new Map(tpState.list.map(c => [c.id, {
          last_message_time: c.last_message_time,
          unread_count: c.unread_count || 0,
        }]));
        newChats.forEach(c => {
          const prev = oldMap.get(c.id);
          if (prev && c.last_message_time !== prev.last_message_time) {
            tpThreadCache.delete(c.id); // Invalidate stale thread
          }
        });
        // Compute a cheap signature of what the rendered list depends on (order,
        // last-message time, unread, preview). Only re-render when it changes —
        // re-rendering every poll caused a visible flicker / lost scroll (unwanted refresh).
        const _sig = (arr) => arr.map(c =>
          `${c.id}:${c.last_message_time || ''}:${c.unread_count || 0}:${(c.last_message || '').slice(0, 40)}`
        ).join('|');
        const newSig = _sig(newChats);
        const changed = newSig !== tpState._listSig;
        tpState._listSig = newSig;
        // Update list + badges
        tpState.list = newChats;
        tpState._hasViewpoint = data.has_viewpoint || false;
        _setListCache('teams', tpState.list, { hasViewpoint: tpState._hasViewpoint, channels: tpState._channels, hasMore: tpState._hasMore, skypeCursor: tpState._skypeCursor });
        const unread = newChats.filter(c => (c.unread_count || 0) > 0).length;
        if (typeof updateRailBadge === 'function') updateRailBadge('teams', unread);
        // Don't clobber active search results with the browse list — the poller
        // updates tpState.list + badges silently while a search is showing (#118).
        // Only re-render when the list actually changed (avoids flicker on every poll).
        if (!tpState.searchQuery && changed) renderTeamsList(tpState.list);

        // UX: when a chat becomes newly unread, prefetch that thread now
        // so clicking it feels instant. Only trigger on transition (read→unread),
        // not on every poll for already-unread chats — that causes continuous hot polling.
        const justBecameUnread = newChats
          .filter(c => {
            if (!(c.unread_count > 0) || !c.id || c.id.startsWith('ch::')) return false;
            const prev = oldMap.get(c.id);
            if (!prev) return true; // newly seen chat with unread
            return (prev.unread_count || 0) === 0 && (c.unread_count || 0) > 0;
          })
          .sort((a, b) => new Date(b.last_message_time || 0) - new Date(a.last_message_time || 0))
          .slice(0, 3);
        justBecameUnread.forEach(chat => {
          _promoteHotChat(chat.id, 'delta-unread');
          _prefetchTeamsThread(chat, { force: true });
        });
      }).catch(() => {});
  }, 60000);
}

function _stopChatListPolling() {
  if (_chatListPoller) { clearInterval(_chatListPoller); _chatListPoller = null; }
}

// Parse a Teams message deeplink and open it inside Gator (channel thread or chat)
// instead of native Teams. Returns true if handled, false to fall back to window.open.
// Channel deeplink: /l/message/19:{chan}@thread.tacv2/{msgId}?groupId={teamId}&channelName=...&parentMessageId=...
// Chat deeplink:    /l/message/19:{guids}@unq.gbl.spaces/{msgId}?context={"contextType":"chat"}
function _tryOpenTeamsDeeplinkInApp(href) {
  try {
    if (!/teams\.microsoft\.com\/l\/message\//i.test(href)) return false;
    const u = new URL(href);
    // Path: /l/message/{conversationId}/{messageId}
    const m = u.pathname.match(/\/l\/message\/([^/]+)\/([^/?]+)/);
    if (!m) return false;
    const conversationId = decodeURIComponent(m[1]); // e.g. 19:...@thread.tacv2
    const messageId = decodeURIComponent(m[2]);
    const groupId = u.searchParams.get('groupId') || '';
    const channelName = u.searchParams.get('channelName') || 'Channel';

    if (conversationId.includes('@thread.tacv2') && groupId) {
      // Channel message — open the channel thread in Gator, then seek to the message.
      if (typeof openThirdPane === 'function') openThirdPane('teams');
      _loadChannelThread(groupId, conversationId, channelName).then(() => {
        setTimeout(() => { if (_activeSeekToMessage) _activeSeekToMessage(messageId); }, 600);
      });
      return true;
    }
    if (conversationId.includes('@unq.gbl.spaces') || conversationId.includes('@thread.v2') || conversationId.includes('@thread.skype')) {
      // 1:1 / group chat message — open the chat thread in Gator, then seek.
      if (typeof openThirdPane === 'function') openThirdPane('teams');
      tpState.selectedId = conversationId;
      _loadTeamsThread(conversationId).then(() => {
        setTimeout(() => { if (_activeSeekToMessage) _activeSeekToMessage(messageId); }, 600);
      });
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

async function _loadChannelThread(teamId, channelId, channelName) {
  // Composite chat ID so the thread cache + detail header use a stable key (#127)
  const chatId = `ch::${teamId}::${channelId}`;
  // Keep selection + focus highlight in sync even when reached directly (e.g. deeplink),
  // so the correct channel row stays highlighted rather than a stale one.
  tpState.selectedId = chatId;
  tpState.focusedId = chatId;
  saveTpState();
  document.querySelectorAll('.tp-list-item').forEach(el => {
    const match = el.dataset.id === chatId;
    el.classList.toggle('active', match);
    el.classList.toggle('focused', match);
  });
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = _gatorLoading();

  // Cache check
  const cached = tpThreadCache.get(chatId);
  if (cached && Date.now() - cached.ts < TP_CACHE_TTL) {
    const d = cached.data;
    renderTeamsThread(d.messages || [], d.chat || { id: chatId, topic: channelName, chat_type: 'channel' }, d.myId || '', d);
    return;
  }

  try {
    const res = await fetch(`/api/teams/channels/${encodeURIComponent(teamId)}/${encodeURIComponent(channelId)}/messages`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const chat = { id: chatId, topic: channelName, chat_type: 'channel' };
    // Group replies under their parent so channel threads render correctly (#127).
    // The backend returns parents (is_thread_parent=true) interleaved with their
    // replies (is_reply=true, reply_to_id=parentId). Re-order so each parent is
    // immediately followed by its replies in chronological order.
    const rawMsgs = data.messages || [];
    const parents = rawMsgs.filter(m => !m.is_reply);
    const repliesByParent = {};
    rawMsgs.filter(m => m.is_reply).forEach(m => {
      (repliesByParent[m.reply_to_id] = repliesByParent[m.reply_to_id] || []).push(m);
    });
    const threaded = [];
    parents.forEach(p => {
      threaded.push(p);
      (repliesByParent[p.id] || []).forEach(r => threaded.push(r));
    });
    const payload = { messages: threaded, chat, myId: data.my_id || '', has_more: false };
    tpThreadCache.set(chatId, { data: payload, ts: Date.now() });
    renderTeamsThread(payload.messages, chat, payload.myId, payload);
  } catch (e) {
    col.innerHTML = `<div class="tp-empty-state"><span>Could not load channel: ${escapeHtml(e.message)}</span>
      <button class="tp-ai-btn" onclick="_loadChannelThread('${escapeHtml(teamId)}','${escapeHtml(channelId)}','${escapeHtml(channelName)}')">Retry</button></div>`;
  }
}

// Open a Teams channel thread detail view (Slack-style: parent + replies, back button)
function _openTeamsChannelThread(chat, parentMsg, allMessages) {
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = '';

  // Gather parent + its replies from the already-loaded messages
  const replies = allMessages.filter(m => m.is_reply && m.reply_to_id === parentMsg.id);
  const threadMessages = [parentMsg, ...replies];

  // Header with back button
  const header = document.createElement('div');
  header.className = 'tp-thread-header';

  const back = document.createElement('button');
  back.className = 'slack-back-btn';
  back.textContent = '←';
  back.title = 'Back to ' + (chat.topic || 'channel');
  back.addEventListener('click', () => {
    const [, teamId, channelId] = (chat.id || '').split('::');
    if (teamId && channelId) _loadChannelThread(teamId, channelId, chat.topic || 'Channel');
  });
  header.appendChild(back);

  const title = document.createElement('div');
  title.className = 'tp-thread-name';
  title.textContent = 'Thread in #' + escapeHtml(chat.topic || 'channel');
  header.appendChild(title);

  const spacer = document.createElement('div');
  spacer.style.flex = '1';
  header.appendChild(spacer);
  col.appendChild(header);

  // Scroll area with parent + replies
  const scroll = document.createElement('div');
  scroll.className = 'tp-thread-scroll';
  col.appendChild(scroll);

  const replyCount = threadMessages.length - 1;

  const parentDateKey = (threadMessages[0]?.created_at || '').slice(0, 10);
  let lastDate = null;
  let addedRepliesSep = false;
  threadMessages.forEach((msg, i) => {
    const dateKey = (msg.created_at || '').slice(0, 10);
    const msgEl = _buildTeamsMessage(msg, chat.id, scroll);
    if (!msgEl) return;  // unsurfaced system event

    if (i === 0) {
      // Parent — show its date, then the card
      if (dateKey && dateKey !== lastDate) {
        const dateSep = document.createElement('div');
        dateSep.className = 'tp-date-sep';
        dateSep.textContent = formatDateLabel(dateKey);
        scroll.appendChild(dateSep);
        lastDate = dateKey;
      }
      msgEl.classList.add('tp-thread-parent-msg');
    } else {
      // First reply: insert "N replies" separator.
      // Only add a date sep afterward if the reply is on a different day than the parent.
      if (!addedRepliesSep) {
        addedRepliesSep = true;
        const rSep = document.createElement('div');
        rSep.className = 'slack-replies-sep';
        rSep.textContent = replyCount + (replyCount === 1 ? ' reply' : ' replies');
        scroll.appendChild(rSep);
        lastDate = parentDateKey; // treat replies-sep as having "consumed" the parent date
      }
      // Date sep only if this reply is on a genuinely different day
      if (dateKey && dateKey !== lastDate) {
        const dateSep = document.createElement('div');
        dateSep.className = 'tp-date-sep';
        dateSep.textContent = formatDateLabel(dateKey);
        scroll.appendChild(dateSep);
        lastDate = dateKey;
      }
      msgEl.classList.add('tp-thread-reply-msg');
    }
    scroll.appendChild(msgEl);
  });

  scroll.scrollTop = scroll.scrollHeight;
}

async function _loadEmailDetail(messageId) {
  // Mark read immediately — before cache check, same as Teams
  const listItem = tpState.list.find(m => m.id === messageId);
  if (listItem && !listItem.is_read) {
    _markListItemRead(messageId);  // reads !is_read before mutation
    listItem.is_read = true;
    fetch(`/api/email/messages/${encodeURIComponent(messageId)}/markread`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_read: true }),
    }).catch(() => {});
  }

  // Guard: confirm before discarding an unsaved reply/forward compose
  const _detailCol = document.getElementById('tp-detail-col');
  const _composeDraft = _detailCol && _detailCol.querySelector('.ql-editor');
  if (_composeDraft && (_composeDraft.textContent || '').trim()) {
    if (!confirm('Discard unsaved reply?')) return;
  }

  // Cache check — email content is immutable, cache for 24h
  const cached = tpThreadCache.get('email::' + messageId);
  if (cached && Date.now() - cached.ts < 86400000) {
    renderEmailDetail(cached.data);
    return;
  }

  const col = _detailCol;
  col.innerHTML = _gatorLoading();

  try {
    const res = await fetch(`/api/email/messages/${encodeURIComponent(messageId)}`);
    if (!res.ok) throw new Error(res.status);
    const email = await res.json();

    // Cache the response
    tpThreadCache.set('email::' + messageId, { data: email, ts: Date.now() });

    renderEmailDetail(email);
  } catch {
    col.innerHTML = `<div class="tp-empty-state"><span>Could not load email.</span>
      <button class="tp-ai-btn" onclick="_loadEmailDetail('${escapeHtml(messageId)}')">Retry</button></div>`;
  }
}

/* ── Mark list item as read (visual sync) ──────────────────── */

function _markListItemRead(id) {
  // Update data model
  if (tpState.type === 'teams') {
    const chat = tpState.list.find(c => c.id === id);
    if (chat) {
      chat._unread = false;
      const totalUnread = tpState.list.filter(c => c._unread).length;
      if (typeof updateRailBadge === 'function') updateRailBadge('teams', totalUnread);
    }
  } else if (tpState.type === 'email') {
    const email = tpState.list.find(m => m.id === id);
    if (email && !email.is_read) {
      email.is_read = true;
      if (tpState._totalUnread > 0) tpState._totalUnread--;
      if (typeof updateRailBadge === 'function' && (tpState.filter === 'all' || tpState.filter === 'unread')) {
        updateRailBadge('email', tpState._totalUnread);
      }
    }
  }

  // Update DOM: remove unread styling from the list item
  const listItem = document.querySelector(`.tp-list-item[data-id="${id}"]`);
  if (listItem) {
    listItem.classList.remove('unread');
    const nameEl = listItem.querySelector('.tp-item-name');
    if (nameEl) nameEl.classList.remove('unread');
    const badge = listItem.querySelector('.tp-unread-badge');
    if (badge) badge.remove();
  }

  // Update the "Unread (N)" filter label. Teams renders it as .tp-filter-chip,
  // email as .tp-filter-tab — update whichever is present.
  const tabBtns = document.querySelectorAll('.tp-filter-tab, .tp-filter-chip');
  if (tabBtns.length >= 2) {
    const count = tpState.type === 'teams'
      ? tpState.list.filter(c => c._unread).length
      : (tpState._totalUnread || 0);
    tabBtns[1].textContent = count > 0 ? `Unread (${count})` : 'Unread';
  }
}

/* ── Teams thread render ─────────────────────────────────── */

// Reaction types supported by Teams Graph API
const TEAMS_REACTIONS = [
  { type: 'like',      emoji: '👍' },
  { type: 'heart',     emoji: '❤️' },
  { type: 'laugh',     emoji: '😆' },
  { type: 'surprised', emoji: '😮' },
  { type: 'sad',       emoji: '😢' },
  { type: 'angry',     emoji: '😡' },
];

// Extended Teams reaction name → emoji.
// Microsoft uses jargon names like "handsinair" for its fluent-emoji reaction set
// that don't match any public CLDR/shortcode database, so this is a hand-curated
// catalogue. Source: https://office365itpros.com/2025/11/07/teams-reactions-emojis/
// + https://github.com/12Knocksinna/Office365itpros/blob/master/Report-TeamsEmojis.PS1
// Unknown keys fall through to raw text — extend as new ones surface.
// Extended Teams reaction name → emoji.
// Curated from the top-used Teams reactions analysis published by Office365ITPros
// (https://office365itpros.com/2025/11/07/teams-reactions-emojis/) plus the
// Office 365 for IT Pros Report-TeamsEmojis.PS1 hashtable. Microsoft doesn't
// publish a canonical list, and these names don't match any public emoji
// library (CLDR/joypixels/etc.), so we maintain our own map.
//
// Note: keys with a hex codepoint prefix like "2795_heavyplussign" are decoded
// automatically by _skypeKeyToEmoji; we list the BARE-NAME aliases below in
// case Teams ever sends them without the prefix.
//
// Unknown keys still fall through to raw text — extend as new ones surface.
const _TEAMS_NAMED_REACTIONS = {
  // Legacy core 6 (also handled by TEAMS_REACTIONS picker)
  like: '👍', heart: '❤️', laugh: '😂', surprised: '😮', sad: '😢', angry: '😠',
  // Hand & gesture reactions
  'thumbs up': '👍', 'thumbs down': '👎', yes: '👍', no: '👎',
  handsinair: '🙌', 'hands in air': '🙌', clap: '👏', clapping: '👏',
  fistbump: '👊', wave: '👋', shake: '🤝', praying: '🙏', pray: '🙏',
  ok: '👌', okhand: '👌', point: '👉', muscle: '💪', metal: '🤘',
  victory: '✌️', vulcansalute: '🖖', callme: '🤙', call: '📞',
  womanraisinghand: '🙋‍♀️', manraisinghand: '🙋‍♂️',
  bowing: '🙇', 'head shaking vertically': '🙆', 'head shaking horizontally': '🙅',
  // Symbols & marks
  plus: '➕', heavyplussign: '➕', minus: '➖', heavyminussign: '➖',
  checkmark: '✔️', heavycheckmark: '✔️', check: '✔️',
  cross: '❌', crossmark: '❌', x: '❌',
  question: '❓', questionmark: '❓', exclamation: '❗',
  doubleexclamationmark: '‼️', warning: '⚠️',
  hundred: '💯', hundredpointssymbol: '💯',
  // Faces — positive
  smile: '😄', smiling: '😄', happyface: '😊', joy: '😂', rofl: '🤣',
  grinningfacewithsmilingeyes: '😁', grinningfacewithbigeyes: '😃',
  sweatgrinning: '😅', cool: '😎', hearteyes: '😍', smilingfacewithtear: '🥲',
  squintingfacewithtongue: '😜', zanyface: '🤪', huggingface: '🤗',
  facewithcowboyhat: '🤠', moneymouthface: '🤑', relieved: '😌',
  whew: '😮‍💨', wink: '😉',
  // Faces — neutral / thinking
  think: '🤔', thinking: '🤔', blankface: '😐', neutral: '😐',
  pleadingface: '🥺', anguishedface: '😧',
  // Faces — negative
  cry: '😢', loudlycrying: '😭', screamingfear: '😱',
  facewithheadbandage: '🤕', mindblown: '🤯',
  // Hearts & feelings
  heartblue: '💙', heartgreen: '💚', heartpurple: '💜', heartorange: '🧡',
  heartyellow: '💛', brokenheart: '💔', sparklingheart: '💖', fire: '🔥',
  // Celebration
  partypopper: '🎉', tada: '🎉', sparkles: '✨', confetti: '🎊',
  rocket: '🚀', trophy: '🏆', medal: '🏅',
  // Objects & ideas
  electriclightbulb: '💡', lightbulb: '💡',
  paperclip: '📎', soon: '🔜', zzz: '💤', eyes: '👀',
  ship: '🚢', artistpalette: '🎨', kimono: '👘', tooth: '🦷',
  support: '🆘', followup: '🔔', follow: '👣',
  // Animals & misc
  saddog: '🐶', dog: '🐶', cat: '🐱', coolkoala: '🐨', mickeymouse: '🐭',
  peekingeye: '🙈', peekingeyes: '🙈', monkey: '🙊',
  rainbowsmile: '🌈', rainbowsmileyface: '🌈', rainbow: '🌈',
  // Food
  oreoyum: '🍪', cookie: '🍪', cake: '🎂', coffee: '☕', beer: '🍺',
  // People at work
  womandeveloper: '👩‍💻', mandeveloper: '👨‍💻',
  // Indicators / meta
  eyeinspeechbubble: '👁️‍🗨️', ttm: '🈶',
};

// ── Emoji data — loaded once from CDN ────────────────────────────────────────
// emoji.json schema: Array of { char, name, category, group, subgroup, keywords[] }
// https://cdn.jsdelivr.net/npm/emoji.json@15/emoji.json

// emojibase-data — richer than emoji.json: every emoji carries `tags` (synonyms like
// ok/okay/sure/awesome for 👌) so search finds relevant results the way Teams does.
// emoji.json@15 shipped EMPTY keywords, so search could only match formal Unicode names.
const _EMOJI_CDN = 'https://cdn.jsdelivr.net/npm/emojibase-data@latest/en/data.json';

// emojibase `group` is a numeric code; map it to our display category + icon (in order).
const _EMOJI_CAT_CONFIG = [
  { key: 0, title: 'Smileys & Emotion',  icon: '😀' },
  { key: 1, title: 'People & Body',      icon: '👋' },
  { key: 3, title: 'Animals & Nature',   icon: '🐶' },
  { key: 4, title: 'Food & Drink',       icon: '🍕' },
  { key: 5, title: 'Travel & Places',    icon: '✈️' },
  { key: 6, title: 'Activities',         icon: '⚽' },
  { key: 7, title: 'Objects',            icon: '💡' },
  { key: 8, title: 'Symbols',            icon: '❤️' },
  { key: 9, title: 'Flags',              icon: '🏳️' },
];

// Single promise — resolved once and reused on every picker open.
let _emojiDataPromise = null;

// After resolution, these are populated:
let _emojiCats = null;   // Array<{ key, title, icon, emojis: string[] }>
let _emojiKW   = null;   // Map<emoji_char, { name, kw:[] }>

// Lazily-built index for resolving Teams named reaction keys (speaknoevil, meltingface)
// to an emoji char via the emojibase dataset. Built from _emojiKW on first use.
let _reactionNameIndex = null;   // Map<normalizedName, emoji> (exact)
let _reactionNameList = null;    // Array<[normalizedName, emoji, rawNameLen]> (prefix fallback)

function _buildReactionNameIndex() {
  _reactionNameIndex = new Map();
  _reactionNameList = [];
  if (!_emojiKW) return;
  for (const [em, meta] of _emojiKW) {
    const nameTight = (meta.name || '').replace(/[^a-z0-9]/gi, '').toLowerCase();
    if (nameTight) {
      if (!_reactionNameIndex.has(nameTight)) _reactionNameIndex.set(nameTight, em);
      _reactionNameList.push([nameTight, em, (meta.name || '').length]);
    }
    // tags let synonyms resolve too (e.g. a key matching a tag)
    for (const t of (meta.kw || [])) {
      const tt = t.replace(/[^a-z0-9]/gi, '').toLowerCase();
      if (tt && !_reactionNameIndex.has(tt)) _reactionNameIndex.set(tt, em);
    }
  }
}

// Resolve a Teams reaction key (already stripped of tone suffix upstream) to an emoji
// char using the emojibase label index: exact normalized match, then shortest-name
// prefix match ("speaknoevil" → "speak-no-evil monkey" → 🙊). Returns '' if unknown.
function _reactionKeyFromEmojiData(key) {
  if (!_emojiKW) return '';
  if (!_reactionNameIndex) _buildReactionNameIndex();
  const k = (key || '').replace(/-tone[1-5]$/i, '').replace(/[^a-z0-9]/gi, '').toLowerCase();
  if (!k) return '';
  if (_reactionNameIndex.has(k)) return _reactionNameIndex.get(k);
  let best = '', bestLen = Infinity;
  for (const [nt, em, rawLen] of _reactionNameList) {
    if (nt.startsWith(k) && rawLen < bestLen) { best = em; bestLen = rawLen; }
  }
  return best;
}

function _loadEmojiData() {
  if (_emojiDataPromise) return _emojiDataPromise;
  _emojiDataPromise = fetch(_EMOJI_CDN)
    .then(r => r.json())
    .then(data => {
      const catMap = new Map(); // group code → emojis[]
      const kw = new Map();
      for (const e of data) {
        const char = e.emoji;
        if (!char) continue;
        const groupKey = e.group;
        if (groupKey == null) continue; // skip ungrouped (e.g. some components)
        if (!catMap.has(groupKey)) catMap.set(groupKey, []);
        catMap.get(groupKey).push(char);
        // emojibase: label = name, tags = rich synonyms. Store separately so search
        // can RANK (name match beats a stray tag hit) instead of a flat substring scan.
        kw.set(char, {
          name: (e.label || '').toLowerCase(),
          kw: (e.tags || []).map(k => k.toLowerCase()),
        });
        // Base (no-tone) emoji only in the grid; skin-tone variants stay searchable
        // via the base entry to avoid flooding the grid with 5 copies of each.
      }
      // Build ordered category list from config, skip any group not in data.
      // key stored as string to match tab dataset.cat (which is always a string).
      _emojiCats = _EMOJI_CAT_CONFIG
        .filter(c => catMap.has(c.key))
        .map(c => ({ key: String(c.key), title: c.title, icon: c.icon, emojis: catMap.get(c.key) }));
      _emojiKW = kw;
      // Invalidate derived indexes so they rebuild with new data on next use.
      _emojiShortcodeIndex = null;
      _reactionNameIndex = null;
      _reactionNameList = null;
    })
    .catch(err => {
      console.warn('[emoji] Failed to load emoji data:', err);
      // Leave _emojiCats / _emojiKW null — picker degrades gracefully (Recent-only).
    });
  return _emojiDataPromise;
}

// ── Shared singleton full emoji picker ───────────────────────────────────────
let _fullPicker = null;
let _fullPickerCb = null;

function _getRecentEmojis() {
  try { return JSON.parse(localStorage.getItem('tp_emoji_recent') || '[]'); } catch { return []; }
}

function _addRecentEmoji(em) {
  let r = _getRecentEmojis().filter(x => x !== em);
  r.unshift(em);
  localStorage.setItem('tp_emoji_recent', JSON.stringify(r.slice(0, 30)));
}

function _buildFullEmojiPicker() {
  const wrap = document.createElement('div');
  wrap.className = 'tp-emoji-picker-popup hidden';

  // Search row
  const searchRow = document.createElement('div');
  searchRow.className = 'tp-ep-search-row';
  const searchInput = document.createElement('input');
  searchInput.className = 'tp-ep-search';
  searchInput.type = 'text';
  searchInput.placeholder = 'Find something fun…';
  searchRow.appendChild(searchInput);
  wrap.appendChild(searchRow);

  // Category tabs — icons available immediately from config, no data needed
  const tabs = document.createElement('div');
  tabs.className = 'tp-ep-tabs';
  const _isWindows = navigator.platform?.startsWith('Win') || navigator.userAgent.includes('Windows');

  const recentTab = document.createElement('button');
  recentTab.className = 'tp-ep-tab active';
  recentTab.dataset.cat = 'recent';
  recentTab.title = 'Recent';
  recentTab.textContent = '🕐';
  tabs.appendChild(recentTab);

  _EMOJI_CAT_CONFIG
    .filter(c => !(_isWindows && c.key === 9)) // group 9 = Flags (poor glyph support on Windows)
    .forEach(c => {
      const t = document.createElement('button');
      t.className = 'tp-ep-tab';
      t.dataset.cat = String(c.key);
      t.title = c.title;
      t.textContent = c.icon;
      tabs.appendChild(t);
    });

  wrap.appendChild(tabs);

  // Body
  const body = document.createElement('div');
  body.className = 'tp-ep-body';
  wrap.appendChild(body);

  let _activeCat = 'recent';

  function _emojiBtn(em) {
    const b = document.createElement('button');
    b.className = 'tp-emoji-item';
    b.textContent = em;
    // Show the emoji's name on hover so users learn names over time.
    const meta = _emojiKW && _emojiKW.get(em);
    if (meta && meta.name) b.title = meta.name;
    b.addEventListener('mousedown', e => {
      e.preventDefault();
      _addRecentEmoji(em);
      wrap.classList.add('hidden');
      if (_fullPickerCb) _fullPickerCb(em);
    });
    return b;
  }

  function _renderCat(cat) {
    body.innerHTML = '';
    wrap.querySelectorAll('.tp-ep-tab').forEach(t => t.classList.toggle('active', t.dataset.cat === cat));
    _activeCat = cat;

    if (cat === 'recent') {
      const emojis = _getRecentEmojis();
      const sec = document.createElement('div');
      sec.className = 'tp-ep-section-title';
      sec.textContent = emojis.length ? 'Recent' : 'No recent emojis yet';
      body.appendChild(sec);
      if (emojis.length) {
        const grid = document.createElement('div');
        grid.className = 'tp-ep-grid';
        emojis.forEach(em => grid.appendChild(_emojiBtn(em)));
        body.appendChild(grid);
      }
      return;
    }

    // Category tab — needs data
    if (!_emojiCats) {
      const msg = document.createElement('div');
      msg.className = 'tp-ep-section-title';
      msg.textContent = 'Loading…';
      body.appendChild(msg);
      _loadEmojiData().then(() => {
        if (_activeCat === cat) _renderCat(cat);
      });
      return;
    }

    const catData = _emojiCats.find(c => c.key === cat);
    const sec = document.createElement('div');
    sec.className = 'tp-ep-section-title';
    sec.textContent = catData ? catData.title : cat;
    body.appendChild(sec);
    if (catData?.emojis.length) {
      const grid = document.createElement('div');
      grid.className = 'tp-ep-grid';
      catData.emojis.forEach(em => grid.appendChild(_emojiBtn(em)));
      body.appendChild(grid);
    }
  }

  tabs.addEventListener('mousedown', e => {
    const t = e.target.closest('.tp-ep-tab');
    if (!t) return;
    e.preventDefault();
    searchInput.value = '';
    _renderCat(t.dataset.cat);
  });

  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim().toLowerCase();
    if (!q) { _renderCat(_activeCat); return; }

    body.innerHTML = '';
    wrap.querySelectorAll('.tp-ep-tab').forEach(t => t.classList.remove('active'));

    if (!_emojiKW) {
      const msg = document.createElement('div');
      msg.className = 'tp-ep-section-title';
      msg.textContent = 'Loading…';
      body.appendChild(msg);
      _loadEmojiData().then(() => {
        if (searchInput.value.trim().toLowerCase() === q) searchInput.dispatchEvent(new Event('input'));
      });
      return;
    }

    // Normalize the query: fold separators so "thumbs up", "thumbs-up", "thumbsup",
    // and ":thumbsup:" all search as "thumbs up". Multi-word queries must match ALL words.
    const _norm = s => s.replace(/[_:+-]/g, ' ').replace(/\s+/g, ' ').trim();
    const nq = _norm(q);
    const words = nq.split(' ').filter(Boolean);

    // Score each emoji so the BEST match ranks first, instead of a flat substring dump.
    //   exact name / direct char match .... 100
    //   name starts with query ............. 60
    //   every query word is a whole word in name/keywords ... 40
    //   name contains query (substring) .... 25
    //   keyword contains query ............. 10
    const nqTight = nq.replace(/\s/g, ''); // "thumbs up" query typed as "thumbsup"
    // A hand-curated shortcode hit (e.g. "smile"→😊, "100"→💯) is the canonical answer
    // and must outrank any fuzzy name/keyword match.
    const shortcodeEmoji = EMOJI_SHORTCODES[nqTight] || EMOJI_SHORTCODES[nq];
    const scored = [];
    for (const [em, meta] of _emojiKW) {
      const name = meta.name || '';
      const kws = meta.kw || [];
      const hay = (name + ' ' + kws.join(' '));
      const hayTight = hay.replace(/\s/g, ''); // separator-insensitive haystack
      let score = 0;
      if (em === shortcodeEmoji) score = 120;
      else if (em === q || name === nq) score = 100;
      else if (name.startsWith(nq)) score = 60;
      else if (words.every(w => new RegExp('\\b' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b').test(hay))) score = 40;
      else if (name.includes(nq)) score = 25;
      else if (kws.some(k => k.includes(nq))) score = 10;
      else if (nqTight && hayTight.includes(nqTight)) score = 8; // "thumbsup" ~ "thumbs up"
      if (score) scored.push({ em, score, name });
    }
    // Sort by score desc, then shorter name first (more specific), then alpha for stability.
    scored.sort((a, b) => b.score - a.score || a.name.length - b.name.length || a.name.localeCompare(b.name));
    const seen = new Set();
    const results = [];
    for (const s of scored) {
      if (seen.has(s.em)) continue;
      seen.add(s.em);
      results.push(s.em);
    }

    const sec = document.createElement('div');
    sec.className = 'tp-ep-section-title';
    sec.textContent = results.length ? `Results for "${q}"` : `No results for "${q}"`;
    body.appendChild(sec);
    if (results.length) {
      const grid = document.createElement('div');
      grid.className = 'tp-ep-grid';
      results.forEach(em => grid.appendChild(_emojiBtn(em)));
      body.appendChild(grid);
    }
  });

  _renderCat('recent');
  wrap._renderCat = _renderCat;
  wrap._activeCat = () => _activeCat;
  return wrap;
}

function _openFullEmojiPicker(anchorEl, onSelect) {
  if (!_fullPicker) {
    _fullPicker = _buildFullEmojiPicker();
    _loadEmojiData(); // start fetch in background; picker shows Recent immediately
    document.body.appendChild(_fullPicker);
    document.addEventListener('mousedown', e => {
      if (_fullPicker && !_fullPicker.classList.contains('hidden') && !_fullPicker.contains(e.target)) {
        _fullPicker.classList.add('hidden');
        if (_fullPicker._emojiCleanup) { _fullPicker._emojiCleanup(); _fullPicker._emojiCleanup = null; }
        _fullPicker._emojiRO?.unobserve(_fullPicker);
      }
    });
  }
  _fullPickerCb = onSelect;
  // Toggle off if already open (same anchor re-clicked)
  if (!_fullPicker.classList.contains('hidden')) {
    _fullPicker.classList.add('hidden');
    if (_fullPicker._emojiCleanup) { _fullPicker._emojiCleanup(); _fullPicker._emojiCleanup = null; }
    _fullPicker._emojiRO?.unobserve(_fullPicker);
    return;
  }
  // Clear search and reset to recent tab on every open
  const _searchEl = _fullPicker.querySelector('.tp-ep-search');
  if (_searchEl && _searchEl.value) {
    _searchEl.value = '';
    _searchEl.dispatchEvent(new Event('input', { bubbles: true }));
  }
  if (_fullPicker._activeCat() !== 'recent') _fullPicker._renderCat('recent');
  // Position using original viewport-math (not Floating UI) — avoids the anchor-disappearing
  // problem where CSS :hover hides the anchor before computePosition can measure it.
  _fullPicker.classList.remove('hidden');
  if (_fullPicker._emojiCleanup) _fullPicker._emojiCleanup();
  _fullPicker._emojiCleanup = null;
  _fullPicker._savedAnchorRect = null; // clear stale rect from previous caller
  const _posEmoji = () => {
    const r = anchorEl.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    const pw = _fullPicker.offsetWidth || 320;
    const ph = _fullPicker.offsetHeight || 320; // fixed height from CSS
    const gap = 6, margin = 4;
    // Use saved rect if anchor has been hidden (rect collapses to 0)
    const anchorRect = (r.width > 0 || r.height > 0) ? r : _fullPicker._savedAnchorRect || r;
    if (r.width > 0 || r.height > 0) _fullPicker._savedAnchorRect = r;
    const spaceAbove = anchorRect.top - gap - margin;
    const spaceBelow = vh - anchorRect.bottom - gap - margin;
    let top = spaceAbove >= spaceBelow
      ? Math.max(margin, anchorRect.top - ph - gap)
      : Math.min(anchorRect.bottom + gap, vh - ph - margin);
    if (top < margin) top = margin;
    let left = anchorRect.left;
    if (left + pw > vw - margin) left = vw - pw - margin;
    if (left < margin) left = margin;
    _fullPicker.style.position = 'fixed';
    _fullPicker.style.top = top + 'px';
    _fullPicker.style.left = left + 'px';
    _fullPicker.style.zIndex = '99999';
    _fullPicker.style.visibility = 'visible';
  };
  _posEmoji();
  // Reposition when picker height changes — disconnect old observer so its
  // stale _posEmoji closure (from a previous caller) can't fire. Create fresh
  // each time so the callback always references the current anchor.
  if (_fullPicker._emojiRO) { _fullPicker._emojiRO.disconnect(); }
  if (typeof ResizeObserver !== 'undefined') {
    _fullPicker._emojiRO = new ResizeObserver(_posEmoji);
    _fullPicker._emojiRO.observe(_fullPicker);
  }
}

/* ── Rename group chat (inline edit) ─────────────────────── */
function _teamsStartRename(chat) {
  const topicEl = document.getElementById('tp-thread-topic');
  if (!topicEl) return;
  const oldTopic = chat.topic || '';
  const input = document.createElement('input');
  input.type = 'text';
  input.value = oldTopic;
  input.className = 'tp-rename-input';
  input.style.cssText = 'flex:1;padding:.2rem .4rem;font-size:.82rem;font-weight:600;border:1px solid var(--accent,#6c63ff);border-radius:4px;background:var(--bg-1,#0f172a);color:var(--text);outline:none';
  topicEl.replaceWith(input);
  input.focus();
  input.select();

  async function _save() {
    const newTopic = input.value.trim();
    if (!newTopic || newTopic === oldTopic) { _cancel(); return; }
    input.disabled = true;
    try {
      const res = await fetch(`/api/teams/chats/${encodeURIComponent(chat.id)}/rename`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: newTopic }),
      });
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || res.status); }
      chat.topic = newTopic;
      // Update in list
      const listChat = tpState.list.find(c => c.id === chat.id);
      if (listChat) listChat.topic = newTopic;
      _clearListCache('teams');
      renderTeamsList(tpState.list);
      _cancel();
    } catch (e) {
      input.style.borderColor = 'var(--danger,#f87171)';
      input.disabled = false;
    }
  }
  function _cancel() {
    const span = document.createElement('div');
    span.className = 'tp-thread-name';
    span.id = 'tp-thread-topic';
    span.style.cssText = 'flex:1;cursor:pointer';
    span.title = 'Click to rename';
    span.textContent = chat.topic || 'Chat';
    span.addEventListener('click', () => _teamsStartRename(chat));
    input.replaceWith(span);
  }
  input.addEventListener('keydown', e => { if (e.key === 'Enter') _save(); if (e.key === 'Escape') _cancel(); });
  input.addEventListener('blur', () => setTimeout(_cancel, 200));
}

/* ── Add members to group chat ──────────────────────────── */
function _teamsShowAddMembers(chat) {
  // Create overlay
  const overlay = document.createElement('div');
  overlay.id = 'tp-add-members-overlay';
  Object.assign(overlay.style, {
    position: 'absolute', inset: '0', zIndex: '60',
    display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: '3rem',
    background: 'rgba(0,0,0,.6)', backdropFilter: 'blur(4px)', borderRadius: 'inherit',
  });

  const panel = document.createElement('div');
  Object.assign(panel.style, {
    background: 'var(--surface,#1e293b)', borderRadius: '10px', padding: '1rem 1.2rem',
    width: '300px', maxHeight: '400px', display: 'flex', flexDirection: 'column', gap: '.6rem',
    boxShadow: '0 8px 32px rgba(0,0,0,.5)',
  });
  panel.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between">
      <div style="font-weight:700;font-size:.85rem;color:var(--text)">Add Members</div>
      <button id="tp-add-close" style="background:none;border:none;color:var(--text-sub);cursor:pointer;font-size:1rem" title="Close">&times;</button>
    </div>
    <div id="tp-current-members" class="tp-current-members"></div>
    <input id="tp-add-search" type="text" placeholder="Search people by name..." style="padding:.35rem .5rem;border:1px solid var(--border);border-radius:6px;background:var(--surface2,var(--surface,#f1f5f9));color:var(--text);font-size:.8rem;outline:none" autocomplete="off" />
    <div id="tp-add-results" class="tp-add-results" style="max-height:180px;overflow-y:auto"></div>
    <div id="tp-add-chips" style="display:flex;flex-wrap:wrap;gap:.3rem"></div>
    <div style="display:flex;gap:.4rem;justify-content:flex-end">
      <button id="tp-add-cancel" style="padding:.3rem .6rem;border:1px solid var(--border);border-radius:6px;background:none;color:var(--text-sub);cursor:pointer;font-size:.78rem">Cancel</button>
      <button id="tp-add-confirm" style="padding:.3rem .7rem;border:none;border-radius:6px;background:var(--accent,#6c63ff);color:#fff;cursor:pointer;font-size:.78rem;font-weight:600" disabled>Add</button>
    </div>
    <div id="tp-add-msg" style="font-size:.72rem;display:none"></div>
  `;
  overlay.appendChild(panel);

  const pane = document.getElementById('third-pane');
  pane.style.position = 'relative';
  pane.appendChild(overlay);

  // Populate current members
  const currentMembersDiv = panel.querySelector('#tp-current-members');

  function _renderMembers(memberList) {
    if (!memberList || !memberList.length) {
      currentMembersDiv.innerHTML = '';
      return;
    }
    currentMembersDiv.innerHTML = `<div class="tp-cm-label">Current members (${memberList.length})</div>` +
      memberList.map(m =>
        `<div class="tp-cm-row" data-mri="${escapeHtml(m.mri || '')}" data-email="${escapeHtml(m.email || '')}">
          <span class="tp-cm-avatar">${escapeHtml((m.name || '?')[0].toUpperCase())}</span>
          <span class="tp-cm-name">${escapeHtml(m.name || '')}</span>
          <span class="tp-cm-email">${escapeHtml(m.email || '')}</span>
          ${(m.mri && !m.is_me) ? `<button class="tp-cm-remove" title="Remove from group">&times;</button>` : ''}
        </div>`
      ).join('');
    currentMembersDiv.querySelectorAll('.tp-cm-remove').forEach(btn => {
      btn.addEventListener('click', async () => {
        const row = btn.closest('.tp-cm-row');
        const mri = row.dataset.mri;
        const name = row.querySelector('.tp-cm-name')?.textContent || '';
        if (!mri) return;
        if (!confirm(`Remove ${name} from this group?`)) return;
        try {
          const res = await fetch(`/api/teams/chats/${chat.id}/members/${encodeURIComponent(mri)}`, { method: 'DELETE' });
          if (!res.ok) throw new Error('Failed');
          row.remove();
          const remaining = currentMembersDiv.querySelectorAll('.tp-cm-row').length;
          const label = currentMembersDiv.querySelector('.tp-cm-label');
          if (label) label.textContent = `Current members (${remaining})`;
        } catch (e) {
          _showAlert('Failed to remove member: ' + e.message, 'error');
        }
      });
    });
  }

  const seeded = chat.members?.length
    ? chat.members
    : (chat.member_emails || []).map(e => ({ name: e.split('@')[0], email: e, mri: '' }));
  if (seeded.length > 0) {
    _renderMembers(seeded);
  } else {
    // Named groups arrive with no members on the chat object — fetch the roster
    // on demand so the list shows for ALL groups, not just unnamed ones (#128).
    currentMembersDiv.innerHTML = '<div class="tp-cm-label">Loading members…</div>';
    fetch(`/api/teams/chats/${encodeURIComponent(chat.id)}/members`)
      .then(r => r.ok ? r.json() : { members: [] })
      .then(d => _renderMembers(d.members || []))
      .catch(() => { currentMembersDiv.innerHTML = ''; });
  }

  const searchInput = panel.querySelector('#tp-add-search');
  const resultsDiv = panel.querySelector('#tp-add-results');
  const chipsDiv = panel.querySelector('#tp-add-chips');
  const confirmBtn = panel.querySelector('#tp-add-confirm');
  const msgDiv = panel.querySelector('#tp-add-msg');
  const pending = new Map(); // email -> {name, email, id}
  let _searchTimer = null;

  function _close() { overlay.remove(); }
  panel.querySelector('#tp-add-close').addEventListener('click', _close);
  panel.querySelector('#tp-add-cancel').addEventListener('click', _close);
  overlay.addEventListener('click', e => { if (e.target === overlay) _close(); });

  function _updateChips() {
    chipsDiv.innerHTML = '';
    for (const [email, p] of pending) {
      const chip = document.createElement('span');
      chip.style.cssText = 'display:inline-flex;align-items:center;gap:.2rem;padding:.15rem .4rem;border-radius:10px;background:var(--accent,#6c63ff);color:#fff;font-size:.72rem;font-weight:600';
      chip.innerHTML = `${escapeHtml(p.name || email)} <button style="background:none;border:none;color:#fff;cursor:pointer;font-size:.8rem;padding:0;line-height:1" data-email="${escapeHtml(email)}">&times;</button>`;
      chip.querySelector('button').addEventListener('click', () => { pending.delete(email); _updateChips(); });
      chipsDiv.appendChild(chip);
    }
    confirmBtn.disabled = pending.size === 0;
    confirmBtn.textContent = pending.size ? `Add ${pending.size}` : 'Add';
  }

  searchInput.addEventListener('input', () => {
    clearTimeout(_searchTimer);
    const q = searchInput.value.trim();
    if (q.length < 2) { resultsDiv.innerHTML = '<div style="font-size:.72rem;color:var(--text-sub);padding:.3rem">Type 2+ chars to search</div>'; return; }
    resultsDiv.innerHTML = '<div style="font-size:.72rem;color:var(--text-sub);padding:.3rem">Searching...</div>';
    _searchTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/people/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        resultsDiv.innerHTML = '';
        if (!data.people?.length) { resultsDiv.innerHTML = '<div style="font-size:.72rem;color:var(--text-sub);padding:.3rem">No results</div>'; return; }
        data.people.forEach(p => {
          const alreadyMember = (chat.member_emails || []).includes((p.email || '').toLowerCase());
          const alreadyPending = pending.has(p.email);
          const item = document.createElement('div');
          item.style.cssText = `display:flex;align-items:center;gap:.4rem;padding:.35rem .4rem;cursor:${alreadyMember ? 'default' : 'pointer'};border-radius:4px;transition:background .1s;opacity:${alreadyMember ? '.5' : '1'}`;
          if (!alreadyMember) item.addEventListener('mouseenter', () => { item.style.background = 'var(--surface2)'; });
          if (!alreadyMember) item.addEventListener('mouseleave', () => { item.style.background = 'none'; });
          const initial = (p.name || p.email || '?')[0].toUpperCase();
          item.innerHTML = `
            <span style="width:24px;height:24px;border-radius:50%;background:var(--accent,#6c63ff);color:#fff;display:flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:700;flex-shrink:0">${initial}</span>
            <span style="display:flex;flex-direction:column;overflow:hidden">
              <span style="font-size:.78rem;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(p.name || p.email)}</span>
              <span style="font-size:.68rem;color:var(--text-sub)">${escapeHtml(p.job_title || p.email || '')}</span>
            </span>
            ${alreadyMember ? '<span style="font-size:.65rem;color:var(--text-dim);margin-left:auto">member</span>' : ''}
            ${alreadyPending ? '<span style="font-size:.65rem;color:var(--accent);margin-left:auto">selected</span>' : ''}`;
          if (!alreadyMember && !alreadyPending) {
            item.addEventListener('click', () => {
              pending.set(p.email, p);
              _updateChips();
              searchInput.value = '';
              resultsDiv.innerHTML = '';
              searchInput.focus();
            });
          }
          resultsDiv.appendChild(item);
        });
      } catch { resultsDiv.innerHTML = '<div style="font-size:.72rem;color:var(--danger);padding:.3rem">Search failed</div>'; }
    }, 300);
  });

  confirmBtn.addEventListener('click', async () => {
    if (pending.size === 0) return;
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Adding...';
    msgDiv.style.display = 'none';
    try {
      const res = await fetch(`/api/teams/chats/${encodeURIComponent(chat.id)}/members/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emails: [...pending.keys()] }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.status);
      msgDiv.style.display = 'block';
      if (data.added?.length) {
        msgDiv.style.color = 'var(--success,#16a34a)';
        msgDiv.textContent = `Added: ${data.added.join(', ')}`;
      }
      if (data.failed?.length) {
        msgDiv.style.color = 'var(--danger,#f87171)';
        msgDiv.textContent += (data.added?.length ? ' | ' : '') + `Failed: ${data.failed.join(', ')}`;
      }
      pending.clear();
      _updateChips();
      // Refresh chat list + thread cache to pick up new members
      _clearListCache('teams');
      tpThreadCache.delete(chat.id);
      // Append newly added members to the current members list in the panel
      if (data.added?.length) {
        const label = currentMembersDiv.querySelector('.tp-cm-label');
        const currentCount = currentMembersDiv.querySelectorAll('.tp-cm-row').length;
        if (label) label.textContent = `Current members (${currentCount + data.added.length})`;
        for (const name of data.added) {
          const row = document.createElement('div');
          row.className = 'tp-cm-row';
          row.innerHTML = `<span class="tp-cm-name" style="color:var(--accent,#4ade80)">${escapeHtml(name)} ✓</span>`;
          currentMembersDiv.appendChild(row);
        }
      }
      setTimeout(_close, 2000);
    } catch (e) {
      msgDiv.style.display = 'block';
      msgDiv.style.color = 'var(--danger,#f87171)';
      msgDiv.textContent = e.message;
      confirmBtn.disabled = false;
      confirmBtn.textContent = `Add ${pending.size}`;
    }
  });

  searchInput.focus();
}

function renderTeamsThread(messages, chat, myId, data, { skipScrollToBottom = false } = {}) {
  data = data || {};
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = '';

  // Populate persistent header with chat-specific content
  const isGroup = chat.chat_type === 'group' || chat.chatType === 'group';
  const header = document.getElementById('tp-detail-header');
  const _hdrChatType = (chat.chat_type || chat.chatType || '').toLowerCase();
  const _hdrIsMeeting = _hdrChatType === 'meeting';
  const _hdrIsDm = _hdrChatType === 'oneonone';

  if (header) {
    // Build the Teams toolbar through the shared component (#tp-detail-toolbar).
    // Close is the pane edge handle now — no close button in the toolbar.
    const _AUDIO_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.93 12a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.84 1.27h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9a16 16 0 0 0 6.29 6.29l1.88-1.88a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7a2 2 0 0 1 1.72 2.02z"/></svg>';
    const _VIDEO_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>';
    const _ADD_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>';

    const _pinBtn = _createPinBtn('teams', chat.id, chat.topic || 'Chat', { type: chat.chatType || chat.chat_type || 'chat' });
    _pinBtn.id = 'tp-teams-chat-pin';

    const actions = [];
    if (isGroup) {
      actions.push({ kind: 'icon', iconHtml: '✏️', title: 'Rename group', onClick: () => _teamsStartRename(chat), group: 0 });
    }
    // Ask AI: click handler is attached later by id (see end of renderTeamsThread) — no onClick here.
    actions.push({ kind: 'ai', iconHtml: '✦', label: '', id: 'tp-teams-ask-ai', title: 'Ask AI about this chat', group: 0 });
    if (_hdrIsMeeting) {
      actions.push({ kind: 'icon', iconHtml: '<span class="material-symbols-outlined tp-mi">speaker_notes</span>', id: 'tp-teams-transcripts', title: 'Meeting transcripts', onClick: () => _openTranscriptsPanel(chat), group: 0 });
    }
    actions.push({ el: _pinBtn, kind: 'icon', title: 'Pin chat', group: 0 });
    // group 1 = call/add tools (divider before)
    if (_hdrIsDm && chat.other_email) {
      actions.push({ kind: 'icon', iconHtml: _AUDIO_SVG, title: 'Audio call (opens Teams)', onClick: () => window.open(`https://teams.microsoft.com/l/call/0/0?users=${encodeURIComponent(chat.other_email)}`, '_blank'), group: 1 });
      actions.push({ kind: 'icon', iconHtml: _VIDEO_SVG, title: 'Video call (opens Teams)', onClick: () => window.open(`https://teams.microsoft.com/l/call/0/0?users=${encodeURIComponent(chat.other_email)}&withVideo=true`, '_blank'), group: 1 });
    }
    if (isGroup || _hdrIsDm || _hdrIsMeeting) {
      actions.push({ kind: 'icon', iconHtml: _ADD_SVG, title: _hdrIsDm ? 'Add member (converts to group chat)' : 'Add members', onClick: () => _teamsShowAddMembers(chat), group: 1 });
    }

    // Split topic names, show first 3, append +N for the rest
    const _allNames = (chat.topic || '').split(',').map(s => s.trim()).filter(Boolean);
    const MAX_NAMES = 3;
    const _shownNames = _allNames.slice(0, MAX_NAMES);
    const _hiddenCount = _allNames.length - _shownNames.length;
    const _titleText = _shownNames.join(', ') + (_hiddenCount > 0 ? ` +${_hiddenCount}` : '') || 'Chat';

    tpBuildDetailToolbar({
      app: 'teams',
      title: {
        text: _titleText,
        avatar: getInitials(chat.topic),
        avatarClass: 'tp-avatar-teams',
        title: isGroup ? 'Click to rename' : null,
        onClick: isGroup ? () => _teamsStartRename(chat) : null,
      },
      actions,
    });
    // Give the title the legacy id so rename-in-place can find it.
    const _topic = header.querySelector('.tp-toolbar-title');
    if (_topic) _topic.id = 'tp-thread-topic';
  }

  // Message scroll
  const scroll = document.createElement('div');
  scroll.className = 'tp-thread-scroll';
  col.appendChild(scroll);

  // Auto-load older messages on scroll-up (native-Teams style — no button). When the
  // user nears the top of the thread, fetch the next older page and prepend it while
  // holding their reading position steady (preserve scrollHeight delta so the viewport
  // doesn't jump). Keeps paging until the cursor empties, so history reaches all the
  // way back (e.g. months) without repeated clicks (#118).
  const chatId = chat.id;
  let _loadingOlder = false;
  // Store the pagination cursor in a dedicated map (never touched by the pollers).
  // Using the thread cache for cursor state caused races where poller writes would
  // clobber the cursor between pages. This separate store is only written by
  // _loadTeamsThread (initial) and _loadOlderMessages (pages 2+) (#118).
  if (!tpState._threadCursor) tpState._threadCursor = {};
  // Seed from initial data
  if (data.has_more && (data.skype_cursor || data.next_link)) {
    tpState._threadCursor[chatId] = { has_more: data.has_more, skype_cursor: data.skype_cursor || '', next_link: data.next_link || '' };
  }
  const _hasOlder = () => {
    const cur = tpState._threadCursor?.[chatId];
    return !!(cur?.has_more && (cur?.skype_cursor || cur?.next_link));
  };
  async function _loadOlderMessages() {
    if (_loadingOlder || !_hasOlder()) return;
    _loadingOlder = true;
    tpState._historyLoading = chatId; // block sync cache writes during history load
    const indicator = document.getElementById('tp-teams-older-loading');
    if (indicator) indicator.style.visibility = 'visible';
    try {
      // Read cursor from the dedicated store (not thread cache — pollers corrupt it)
      const cur = tpState._threadCursor?.[chatId] || {};
      const url = cur.next_link
        ? `/api/teams/chats/${encodeURIComponent(chatId)}/messages?next_link=${encodeURIComponent(cur.next_link)}`
        : `/api/teams/chats/${encodeURIComponent(chatId)}/messages?skype_cursor=${encodeURIComponent(cur.skype_cursor)}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      const older = await res.json();
      const cachedPayload = tpThreadCache.get(chatId)?.data || data;
      const existingIds = new Set((cachedPayload.messages || []).map(m => m.id));
      const newMsgs = (older.messages || []).filter(m => !existingIds.has(m.id));
      // Always advance the cursor — even if all fetched messages are already in the
      // cache (duplicates), we must move to the next page cursor or we'll loop forever
      // fetching the same page.
      if (tpState._threadCursor) {
        tpState._threadCursor[chatId] = { has_more: !!older.has_more, skype_cursor: older.skype_cursor || '', next_link: older.next_link || '' };
      }
      if (!newMsgs.length) {
        // All dupes — cursor advanced silently. Re-trigger immediately so the user
        // doesn't have to scroll again: they scrolled to top expecting content, so
        // keep fetching until we find a page with real new messages or reach the end.
        _loadingOlder = false;
        setTimeout(() => { tpState._historyLoading = null; }, 0);
        const ind2 = document.getElementById('tp-teams-older-loading');
        if (ind2) ind2.style.visibility = 'hidden';
        if (_hasOlder()) setTimeout(_loadOlderMessages, 100);
        return;
      }
      const merged = [...newMsgs, ...(cachedPayload.messages || [])];
      cachedPayload.messages = merged;
      tpThreadCache.set(chatId, { data: cachedPayload, ts: Date.now() });
      // Preserve scroll position: capture height before re-render, restore the delta
      // after so the content the user was looking at stays put (no jump).
      const prevHeight = scroll.scrollHeight;
      const prevTop = scroll.scrollTop;
      renderTeamsThread(merged, chat, myId, cachedPayload, { skipScrollToBottom: true });
      requestAnimationFrame(() => {
        const newScroll = col.querySelector('.tp-thread-scroll');
        if (newScroll) newScroll.scrollTop = prevTop + (newScroll.scrollHeight - prevHeight);
      });
    } catch (e) {
      /* leave cursor intact so a later scroll retries */
    } finally {
      _loadingOlder = false;
      const ind = document.getElementById('tp-teams-older-loading');
      if (ind) ind.style.visibility = 'hidden';
      setTimeout(() => { tpState._historyLoading = null; }, 0);
    }
  }
  // Expose seek function so _buildTeamsMessage (top-level scope) can call it.
  // IMPORTANT: _loadOlderMessages calls renderTeamsThread which rebuilds the scroll
  // container and re-assigns _activeSeekToMessage with fresh closures. After each
  // page load we re-delegate to the fresh _activeSeekToMessage so the stale closure
  // doesn't keep running — this is what keeps scroll-up working after a seek.
  _activeSeekToMessage = (msgId) => _seekToMessage(msgId);

  async function _seekToMessage(msgId) {
    const _scrollToTarget = () => {
      const el = document.querySelector(`.tp-msg[data-msg-id="${CSS.escape(msgId)}"]`);
      if (!el) return false;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.style.transition = 'background 0.3s';
      el.style.background = 'var(--surface2, #2a2a3e)';
      setTimeout(() => { el.style.background = ''; }, 1800);
      return true;
    };
    if (_scrollToTarget()) return;
    if (!_hasOlder()) {
      // No more history in this conversation — fall back to native Teams
      const teamsUrl = `https://teams.microsoft.com/l/message/${encodeURIComponent(chatId)}/${encodeURIComponent(msgId)}?context=${encodeURIComponent(JSON.stringify({ contextType: 'chat' }))}`;
      _openUrl(teamsUrl);
      return;
    }
    // Load one older page, then re-delegate to the fresh closure that renderTeamsThread
    // creates — this avoids accumulating stale references to scroll/cursor/loadingOlder.
    await _loadOlderMessages();
    await new Promise(r => setTimeout(r, 120));
    // After renderTeamsThread ran, _activeSeekToMessage is a fresh closure. Use it.
    if (_activeSeekToMessage) _activeSeekToMessage(msgId);
  }

  if (data.has_more || data.next_link) {
    // Subtle top loading indicator (hidden until a fetch is in flight)
    const indicator = document.createElement('div');
    indicator.id = 'tp-teams-older-loading';
    indicator.className = 'tp-thread-older-loading';
    indicator.style.cssText = 'text-align:center;padding:.4rem;font-size:.72rem;color:var(--text-sub,#94a3b8);visibility:hidden';
    indicator.textContent = 'Loading older messages…';
    scroll.appendChild(indicator);
    // Fire when scrolled near the top. Threshold gives a head start so content is
    // ready before the user hits the very top.
    scroll.addEventListener('scroll', () => {
      if (scroll.scrollTop < 200) _loadOlderMessages();
    }, { passive: true });
  }

  if (messages.length === 0) {
    scroll.innerHTML = '<div class="tp-empty-state" style="height:80px"><span>No messages</span></div>';
  }

  messages.sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));

  const _isChannel = (chat.chat_type || chat.chatType || '') === 'channel';

  // Channel view: Slack-style collapsed threads.
  // Show only top-level (non-reply) messages. Each parent gets a clickable
  // "N replies · last Xh" chip that opens the thread detail view.
  // Replies are NOT rendered inline — click the chip to see them.
  const _msgsToRender = _isChannel ? messages.filter(m => !m.is_reply) : messages;
  const _repliesByParent = {};
  if (_isChannel) {
    messages.forEach(m => {
      if (m.is_reply && m.reply_to_id) {
        (_repliesByParent[m.reply_to_id] = _repliesByParent[m.reply_to_id] || []).push(m);
      }
    });
  }

  let lastDate = null;
  _msgsToRender.forEach(msg => {
    const msgEl = _buildTeamsMessage(msg, chat.id, scroll);
    if (!msgEl) return;  // unsurfaced system event — no date sep, no node
    const dateKey = (msg.created_at || '').slice(0, 10);
    if (dateKey && dateKey !== lastDate) {
      const sep = document.createElement('div');
      sep.className = 'tp-date-sep';
      sep.textContent = formatDateLabel(dateKey);
      scroll.appendChild(sep);
      lastDate = dateKey;
    }
    scroll.appendChild(msgEl);

    // Slack-style thread chip on parents with replies
    if (_isChannel) {
      const replyCount = (msg.reply_count || 0) || (_repliesByParent[msg.id] || []).length;
      if (replyCount > 0) {
        const replies = _repliesByParent[msg.id] || [];
        const lastReply = replies[replies.length - 1];
        const lastTime = lastReply ? relativeTime(lastReply.created_at) : '';
        const chip = document.createElement('div');
        chip.className = 'tp-thread-chip';
        chip.setAttribute('role', 'button');
        chip.setAttribute('tabindex', '0');
        chip.innerHTML = '<span class="tp-thread-chip-icon">💬</span>' +
          '<span class="tp-thread-chip-count">' + replyCount + (replyCount === 1 ? ' reply' : ' replies') + '</span>' +
          (lastTime ? '<span class="tp-thread-chip-time"> · last ' + escapeHtml(lastTime) + '</span>' : '') +
          '<span class="tp-thread-chip-cta"> View thread →</span>';
        const _openThread = () => {
          const [, teamId, channelId] = (chat.id || '').split('::');
          if (teamId && channelId) _openTeamsChannelThread(chat, msg, messages);
        };
        chip.addEventListener('click', _openThread);
        chip.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _openThread(); } });
        // Append inside the content column so it sits under the message text, not beside it
        const msgCol = msgEl.querySelector('.tp-msg-col') || msgEl;
        msgCol.appendChild(chip);
      }
    }
  });

  // Presence dots on thread sender avatars — batch-fetch for unique senders, re-apply
  _refreshThreadPresence(scroll);

  // Seen indicator on last sent message
  if (data.peer_last_read) {
    const allMsgEls = scroll.querySelectorAll('.tp-msg.tp-msg-mine');
    const lastSent = allMsgEls[allMsgEls.length - 1];
    if (lastSent) {
      const msgTime = lastSent.dataset.createdAt || '';
      const seen = msgTime && data.peer_last_read >= msgTime;
      const meta = lastSent.querySelector('.tp-msg-meta');
      if (meta) {
        const tick = document.createElement('span');
        tick.className = seen ? 'tp-seen-tick seen' : 'tp-seen-tick';
        tick.title = seen ? 'Seen' : 'Sent';
        tick.textContent = seen ? ' \u2713\u2713' : ' \u2713';
        meta.appendChild(tick);
      }
    }
  }

  // Lazy-load Teams-hosted images via the proxy endpoint
  scroll.querySelectorAll('img[data-teams-src]').forEach(img => {
    const src = img.dataset.teamsSrc;
    if (!src) return;
    img.src = `/api/teams/proxy-image?url=${encodeURIComponent(src)}`;
    delete img.dataset.teamsSrc;
  });

  // Compose bar with rich text editor — tag with chat_id for safety
  const compose = document.createElement('div');
  compose.className = 'tp-compose';
  compose.dataset.chatId = chat.id;
  compose.dataset.chatTopic = chat.topic || 'Chat';

  // ── SAFETY: Show who this message will go to ──
  const sendingTo = document.createElement('div');
  const isGroupChat = chat.chat_type === 'group' || chat.chatType === 'group';
  const isMeeting = chat.chat_type === 'meeting' || chat.chatType === 'meeting';
  sendingTo.style.cssText = 'font-size:.68rem;padding:.25rem .6rem;color:var(--text-sub,#94a3b8);display:flex;align-items:center;gap:.3rem';
  sendingTo.innerHTML = `<span style="color:${isGroupChat ? 'var(--warn,#f59e0b)' : 'var(--text-dim)'}">Sending to${isGroupChat ? ' group' : isMeeting ? ' meeting' : ''}:</span> <strong style="color:var(--text);font-weight:600">${escapeHtml(chat.topic || 'Chat')}</strong>`;
  compose.appendChild(sendingTo);

  // Reply-to preview bar (hidden by default)
  const replyBar = document.createElement('div');
  replyBar.id = 'tp-reply-bar';
  replyBar.className = 'tp-reply-bar hidden';
  replyBar.innerHTML = '<span class="tp-reply-label">\u21A9 Replying to <strong class="tp-reply-sender"></strong></span><span class="tp-reply-preview"></span><button class="tp-reply-dismiss" title="Cancel reply">\u2715</button>';
  replyBar.querySelector('.tp-reply-dismiss').addEventListener('click', () => _setTeamsReplyTo(null));
  compose.appendChild(replyBar);

  const editor = _buildQuillEditor({ placeholder: `Reply to ${chat.topic || 'chat'}\u2026`, showSendBtn: true, draftKey: `teams-draft-${chat.id}` });
  compose.appendChild(editor.wrapEl);

  // Attachment chips container
  const chipsCont = document.createElement('div');
  chipsCont.className = 'tp-compose-chips';
  compose.appendChild(chipsCont);
  col.appendChild(compose);

  // Wire send + attach from the toolbar (no separate row needed)
  const sendBtn = editor.wrapEl.querySelector('.tp-compose-send');
  const attachBtn = editor.wrapEl.querySelector('.tp-qt-attach-btn');
  // Create hidden file input for the toolbar attach button
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = 'image/*,*/*';
  fileInput.multiple = true;
  fileInput.style.display = 'none';
  compose.appendChild(fileInput);
  if (attachBtn) attachBtn.addEventListener('click', () => fileInput.click());
  const chipsEl = chipsCont;
  let _attachedFiles = [];

  // Enter to send, Shift+Enter for newline, @mention and #channel support for Quill editor
  function _wireQuillFeatures() {
    const q = editor.quill;
    if (!q) { setTimeout(_wireQuillFeatures, 200); return; }
    q.root.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
        // Inside a list, Enter makes a new list item (or exits an empty one) —
        // let Quill handle it. Only send when NOT in a list.
        if (q.getFormat().list) return;
        e.preventDefault();
        sendBtn.click();
      }
    });
    _installComposeIndentBindings(q);
    // Use quill root as anchor so dropdown appears directly above the editor
    _wireMentionDropdownQuill(q, q.root);
  }
  setTimeout(_wireQuillFeatures, 150);

  function _addFiles(files) {
    for (const f of files) _attachedFiles.push(f);
    _renderAttachChips();
  }

  fileInput.addEventListener('change', () => { _addFiles(fileInput.files); fileInput.value = ''; });

  // Paste: let Quill embed images inline as data: URIs — the send handler
  // extracts them into hostedImages before posting to the API.

  // Drag-and-drop onto the compose area
  compose.addEventListener('dragover', e => { e.preventDefault(); compose.classList.add('drag-over'); });
  compose.addEventListener('dragleave', e => { if (!compose.contains(e.relatedTarget)) compose.classList.remove('drag-over'); });
  compose.addEventListener('drop', e => {
    e.preventDefault();
    compose.classList.remove('drag-over');
    const files = [...(e.dataTransfer.files || [])].filter(f => f.type.startsWith('image/'));
    if (files.length) _addFiles(files);
  });

  function _renderAttachChips() {
    chipsEl.innerHTML = '';
    _attachedFiles.forEach((f, i) => {
      const chip = document.createElement('span');
      chip.className = 'tp-compose-chip';

      if (f.type.startsWith('image/')) {
        const thumb = document.createElement('img');
        thumb.className = 'tp-compose-chip-thumb';
        thumb.src = URL.createObjectURL(f);
        thumb.alt = f.name;
        thumb.title = 'Click to preview';
        thumb.addEventListener('click', e => {
          e.stopPropagation();
          if (window._tpLightboxOpen) window._tpLightboxOpen(thumb.src);
        });
        chip.appendChild(thumb);
      }

      const label = document.createElement('span');
      label.textContent = f.name;
      chip.appendChild(label);

      const rm = document.createElement('button');
      rm.textContent = '×';
      rm.addEventListener('click', e => { e.stopPropagation(); _attachedFiles.splice(i, 1); _renderAttachChips(); });
      chip.appendChild(rm);
      chipsEl.appendChild(chip);
    });
  }

  sendBtn.addEventListener('click', async () => {
    // ── SAFETY: Verify chat hasn't changed since compose was created ──
    const composeChatId = compose.dataset.chatId;
    if (composeChatId !== chat.id) {
      console.error(`[SAFETY] Compose chat_id mismatch: compose=${composeChatId} closure=${chat.id}`);
      _showAlert('Send blocked: compose context changed. Your message was not sent. Please try again.', 'error');
      sendBtn.disabled = false;
      return;
    }
    if (tpState.selectedId && tpState.selectedId !== chat.id) {
      console.warn(`[SAFETY] Selected chat changed: selected=${tpState.selectedId} compose=${chat.id}`);
      if (!confirm(`You switched chats. Send to "${chat.topic || 'this chat'}" anyway?`)) return;
    }

    const text = editor.quill ? editor.quill.getText().trim() : '';
    const html = editor.getHtml ? editor.getHtml() : '';
    if (!text && !html && _attachedFiles.length === 0) return;
    sendBtn.disabled = true;

    // Quill outputs <p> tags; Teams renders <div> better for line breaks.
    // Quill code-blocks: <pre class="ql-code-block-container"><div class="ql-code-block">…</div></pre>
    // Normalise to a plain <pre> that Teams renders correctly.
    let cleanHtml = html
      ? _quillIndentToNestedList(html)
          .replace(/<p>/g, '<div>').replace(/<\/p>/g, '</div>')
          .replace(/<pre[^>]*class="ql-code-block-container"[^>]*>([\s\S]*?)<\/pre>/g, (_, inner) => {
            const lines = inner.replace(/<div[^>]*class="ql-code-block"[^>]*>(.*?)<\/div>/g, '$1\n').replace(/<br\s*\/?>/g, '\n');
            const text = lines.replace(/<[^>]+>/g, '').replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>').trimEnd();
            return `<pre>${text}</pre>`;
          })
      : '';
    // Quill always parks the cursor on a trailing empty line; strip any empty
    // block elements (<li>, <div>, <p>) at the end so we don't ship phantom bullets.
    cleanHtml = _stripTrailingEmptyBlocks(cleanHtml);
    let message = cleanHtml || text;   // API payload — prefer HTML for formatting
    let displayMessage = cleanHtml || text;   // optimistic bubble — use converted HTML so indent (blockquotes) matches the round-tripped render
    let hostedImages = [];

    const _quillInst = editor.quill;
    let mentions = [];
    if (_quillInst) {
      const hasMentions = _quillInst.getContents().ops.some(op => op.insert && op.insert.mention);
      if (hasMentions) {
        const payload = _buildMentionPayload(_quillInst);
        if (payload.html) {
          cleanHtml = payload.html;
          message = payload.html;
          displayMessage = payload.html;
        }
        if (payload.mentions?.length) {
          mentions = payload.mentions;
        }
      }
    }

    // Safety net: if Quill embedded any images as data URIs (e.g. paste race),
    // extract them into hostedImages so Teams renders them inline instead of as links.
    if (cleanHtml && cleanHtml.includes('src="data:image/')) {
      let imgIdx = hostedImages.length;
      cleanHtml = cleanHtml.replace(/src="data:image\/([^;]+);base64,([^"]+)"/g, (_, mime, b64) => {
        hostedImages.push({ contentType: `image/${mime}`, contentBytes: b64 });
        const ref = `src="../hostedContents/${imgIdx + 1}/$value"`;
        imgIdx++;
        return ref;
      });
      message = cleanHtml;
      displayMessage = html || text;  // keep data URIs for local display only
    }

    if (_attachedFiles.length > 0) {
      const readBase64 = f => new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = e => res(e.target.result.split(',')[1]);
        r.onerror = rej;
        r.readAsDataURL(f);
      });

      let imgIdx = 0;
      const apiParts = [];
      const displayParts = [];
      const INLINE_IMAGE_MAX = 200 * 1024; // 200KB per image — above this, upload to OneDrive instead
      for (const f of _attachedFiles) {
        if (f.type.startsWith('image/') && f.size <= INLINE_IMAGE_MAX) {
          // Small image — inline as hostedContent
          const b64 = await readBase64(f);
          hostedImages.push({ contentType: f.type, contentBytes: b64 });
          apiParts.push(`<img src="../hostedContents/${imgIdx + 1}/$value" style="max-width:400px;border-radius:4px" alt="${escapeHtml(f.name)}">`);
          displayParts.push(`<img src="data:${f.type};base64,${b64}" style="max-width:400px;border-radius:4px" alt="${escapeHtml(f.name)}">`);
          imgIdx++;
        } else {
          // Large image or non-image file — upload to OneDrive and share as link
          try {
            const fd = new FormData();
            fd.append('file', f);
            const up = await fetch('/api/upload/onedrive', { method: 'POST', body: fd });
            const upData = await up.json();
            if (!up.ok) throw new Error(upData.detail || 'Upload failed');
            const isImg = f.type.startsWith('image/');
            const link = isImg
              ? `<a href="${escapeHtml(upData.url)}">${escapeHtml(f.name)}</a>`
              : `\uD83D\uDCCE <a href="${escapeHtml(upData.url)}">${escapeHtml(f.name)}</a>`;
            apiParts.push(link);
            displayParts.push(link);
          } catch (e) {
            const err = `\u26A0 Upload failed: ${escapeHtml(f.name)}`;
            apiParts.push(err);
            displayParts.push(err);
          }
        }
      }
      const textPrefix = cleanHtml || (text ? `<p>${escapeHtml(text)}</p>` : '');
      message = textPrefix + apiParts.join('<br>');
      displayMessage = textPrefix + displayParts.join('<br>');
    }

    if (editor.quill) { editor.quill.setContents([]); editor.quill.setText(''); }
    // Prepend Skype quoted reply if replying to a message — but ONLY if the pending
    // reply belongs to THIS chat. A reply drafted in another conversation and left
    // unsent must never leak into a different chat's message.
    if (_teamsReplyTo && _teamsReplyTo.chat_id && _teamsReplyTo.chat_id !== chat.id) {
      _setTeamsReplyTo(null);
    }
    if (_teamsReplyTo) {
      const q = _teamsReplyTo;
      const quoteMri = q.sender_aad ? `8:orgid:${q.sender_aad}` : '';
      const quoteHtml = `<blockquote itemscope itemtype="http://schema.skype.com/Reply" itemid="${q.id}">`
        + `<strong itemprop="mri" itemid="${quoteMri}">${escapeHtml(q.sender_name)}</strong>`
        + `<span itemprop="time" itemid="${q.id}"></span>`
        + `<p itemprop="preview">${escapeHtml(q.body_preview)}</p>`
        + `</blockquote>`;
      // Append a deeplink back to the quoted message so recipients (incl. native Teams)
      // can navigate to the original — same approach as forwards. The quoted message
      // lives in this same conversation, so use chat.id as the thread.
      let _replyThreadId = chat.id;
      if (chat.id && chat.id.startsWith('ch::')) {
        const _p = chat.id.split('::');
        _replyThreadId = _p[2] || chat.id;
      }
      const _replyDeeplink = (q.id && _replyThreadId)
        ? `https://teams.microsoft.com/l/message/${encodeURIComponent(_replyThreadId)}/${encodeURIComponent(q.id)}?context=${encodeURIComponent(JSON.stringify({ contextType: 'chat' }))}`
        : '';
      // Deeplink back to the original — never embed a formatted timestamp into the
      // outgoing message body. Timestamps belong to AI Gator's UI (.tp-msg-time), not
      // the message content the recipient sees.
      const _replyLinkLine = _replyDeeplink
        ? `<p style="font-size:.75rem;text-align:right"><a href="${_replyDeeplink}">↗ View original message</a></p>`
        : '';
      message = quoteHtml + message + _replyLinkLine;
      displayMessage = quoteHtml + displayMessage + _replyLinkLine;
      _setTeamsReplyTo(null);
    }

    if (editor.clearDraft) editor.clearDraft();
    _attachedFiles = [];
    _renderAttachChips();
    // Seed cache so the thread header shows the correct name after send (not "Chat").
    if (chat.id) _chatInfoCache.set(chat.id, chat);
    await tpSendTeamsMessage(chat.id, message, scroll, true, hostedImages, displayMessage, mentions);
    sendBtn.disabled = false;
    if (_quillInst) { _quillInst.root.focus(); }
  });

  // Scroll to latest message — defer to allow images to affect layout
  if (!skipScrollToBottom) {
    scroll.scrollTop = scroll.scrollHeight;
    setTimeout(() => { scroll.scrollTop = scroll.scrollHeight; }, 300);
    scroll.querySelectorAll('img').forEach(img => {
      if (!img.complete) img.addEventListener('load', () => { scroll.scrollTop = scroll.scrollHeight; }, { once: true });
    });
  }

  // Ask AI (now in header, not aiBar)
  document.getElementById('tp-teams-ask-ai')?.addEventListener('click', () => {
    const context = messages.slice(-5).map(m => `${m.sender_name}: ${m.body || ''}`).join('\n');
    tpInjectAIPrompt(`Summarize my Teams conversation with ${chat.topic}. Recent messages:\n\n${context}`);
  });
}

/* ── Deterministic avatar color from name ─────────────────── */
function _nameColor(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff;
  // use a pleasing palette of hues, skip yellow-greens that look sick on dark bg
  const hue = [8, 28, 195, 215, 265, 290, 330, 350][(h >> 5) & 7] + (h & 31);
  return `hsl(${hue}, 60%, 48%)`;
}

/* ── Single Teams message element ────────────────────────── */
function _buildTeamsMessage(msg, chatId) {
  // System events (member add/remove, topic change) render as a centered grey line,
  // matching native Teams (e.g. "Vainio, Juho added Holanda Noronha, Daniel to the chat").
  if (msg.message_type === 'systemEvent') {
    if (!msg.system_text) return null;  // unsurfaced (e.g. deleteMember) — render nothing
    const ev = document.createElement('div');
    ev.className = 'tp-msg tp-msg-system';
    ev.dataset.msgId = msg.id || '';
    ev.dataset.createdAt = msg.created_at || '';
    ev.innerHTML = `<span class="tp-system-icon">${_TP_SYSTEM_PEOPLE_SVG}</span><span class="tp-system-text">${escapeHtml(msg.system_text)}</span>`;
    return ev;
  }
  const isMine = msg.is_mine;
  const wasEdited = msg.last_modified_at && msg.last_modified_at !== msg.created_at;
  const senderName = msg.sender_name || '';

  const msgEl = document.createElement('div');
  msgEl.className = `tp-msg ${isMine ? 'tp-msg-mine' : 'tp-msg-theirs'}${msg.is_reply ? ' tp-msg-reply' : ''}`;
  msgEl.dataset.msgId = msg.id;
  msgEl.dataset.createdAt = msg.created_at || '';
  msgEl.dataset.lastModified = msg.last_modified_at || '';
  msgEl.dataset.reactionHash = _teamsReactionHash(msg.reactions || []);

  // Avatar
  const avatar = document.createElement('div');
  if (isMine) {
    avatar.className = 'tp-msg-avatar tp-msg-avatar-mine';
    avatar.textContent = 'Me';
    avatar.title = 'You';
  } else {
    avatar.className = 'tp-msg-avatar';
    avatar.textContent = getInitials(senderName);
    avatar.title = senderName;
    avatar.style.background = _nameColor(senderName);
    // Presence dot — key off the sender's MRI/GUID so we can show their availability
    const _sndrMri = _senderMriFromMsg(msg);
    if (_sndrMri) {
      avatar.style.position = 'relative';
      _applyPresenceDot(avatar, _sndrMri);
    }
  }
  msgEl.appendChild(avatar);

  // Content column
  const col = document.createElement('div');
  col.className = 'tp-msg-col';

  // Inline body: for others, bold name flows before message text (no header row for mine)
  const body = document.createElement('div');
  body.className = 'tp-msg-body';
  if (!isMine && senderName) {
    const nameEl = document.createElement('strong');
    nameEl.className = 'tp-msg-sender';
    nameEl.textContent = senderName + '  ';
    nameEl.style.color = _nameColor(senderName);
    // Extract AAD GUID from sender_id (MRI format: "8:orgid:{guid}" or plain GUID)
    const _senderAad = (msg.sender_id || '').split(':').pop();
    if (_senderAad && _senderAad.includes('-')) {
      nameEl.style.cursor = 'pointer';
      nameEl.addEventListener('click', e => { e.stopPropagation(); _showPersonCard(_senderAad, nameEl); });
    }
    body.appendChild(nameEl);
  }
  const textEl = document.createElement('div');
  textEl.className = 'tp-msg-text';
  textEl.innerHTML = sanitizeHtml(_linkifyHtml(msg.body_html || escapeHtml(msg.body || '')));
  // Make images clickable to open lightbox
  textEl.querySelectorAll('img').forEach(img => {
    img.style.cursor = 'zoom-in';
    img.addEventListener('click', e => {
      e.stopPropagation();
      if (window._tpLightboxOpen) window._tpLightboxOpen(img.src);
    });
  });
  // @mention chips — click to show person card
  textEl.querySelectorAll('at[data-aad]').forEach(el => {
    const aadId = el.dataset.aad;
    if (!aadId) return;
    el.style.cursor = 'pointer';
    el.addEventListener('click', e => { e.stopPropagation(); _showPersonCard(aadId, el); });
  });
  // External links (recordings, recaps, etc.) — open in OS browser, not AI chat (#105).
  // Without this, Electron's global navigation handler intercepts the click and opens
  // an AI prompt instead of the browser.
  textEl.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (/^https?:\/\//i.test(href)) {
      a.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        // Teams message deeplinks → open the channel/chat inside Gator instead of
        // bouncing to native Teams. Falls back to native Teams if we can't resolve it.
        if (_tryOpenTeamsDeeplinkInApp(href)) return;
        window.open(href, '_blank', 'noopener');
      });
    }
  });
  // Quoted/forwarded message blockquotes — click to scroll to the original message
  // in the current thread (#131). Skype reply blockquotes carry
  // itemtype="http://schema.skype.com/Reply" and itemid="{msgId}".
  // Forwarded message blockquotes (schema.skype.com/Forward).
  // Navigate to the original message: in Gator if possible, native Teams as fallback.
  // Forward blockquotes carry navigation context in the message PROPERTIES
  // (originalMessageContext), surfaced by the backend as forward_deeplink +
  // original_thread_id + original_message_id. This only exists for native-Teams
  // forwards — Gator-sent forwards can't write that property (Skype rejects it).
  {
    const _origThreadId = msg.original_thread_id || '';
    const _origMsgId = msg.original_message_id || '';
    const _deeplink = msg.forward_deeplink || '';
    textEl.querySelectorAll('blockquote[itemtype="http://schema.skype.com/Forward"]').forEach(bq => {
      // Only make it clickable when we actually have navigation context. Without a
      // deeplink there is nothing reliable to navigate to, so leave it inert rather
      // than silently seeking the wrong conversation.
      if (!_deeplink) return;
      bq.style.cursor = 'pointer';
      bq.title = 'Go to original message';
      bq.addEventListener('click', async e => {
        e.stopPropagation();
        // If the original message lives in the conversation we're already viewing,
        // jump to it in-app. Otherwise open the deeplink in native Teams (it knows
        // how to resolve any conversation/channel; falls back gracefully).
        if (_origThreadId && _origThreadId === chatId && _origMsgId && _activeSeekToMessage) {
          _activeSeekToMessage(_origMsgId);
          return;
        }
        if (_origThreadId && _origThreadId !== chatId) {
          const targetChat = (tpState.list || []).find(c => c.id === _origThreadId);
          if (targetChat) {
            tpState.selectedId = _origThreadId;
            await _loadTeamsThread(_origThreadId);
            await new Promise(r => setTimeout(r, 400));
            if (_activeSeekToMessage) _activeSeekToMessage(_origMsgId);
            return;
          }
        }
        // Source conversation not loaded in Gator — open in native Teams.
        _openUrl(_deeplink);
      });
    });
  }

  // Quoted/forwarded message blockquotes — click to jump to original (#131).
  // If the original message is in the current thread DOM: scroll to it in Gator.
  // If not found (different conversation, channel, or older history not yet loaded):
  // fall back to opening the native Teams deep-link — Teams knows how to navigate
  // across any conversation or channel.
  textEl.querySelectorAll('blockquote[itemtype="http://schema.skype.com/Reply"]').forEach(bq => {
    const msgId = bq.getAttribute('itemid');
    if (!msgId) return;
    // Skip Reply blockquotes that are nested inside a Forward blockquote — the original
    // message is from a different conversation and seeking in this thread would exhaust
    // history pages pointlessly before falling back to native Teams.
    if (bq.closest('blockquote[itemtype="http://schema.skype.com/Forward"]')) return;
    bq.style.cursor = 'pointer';
    bq.title = 'Click to jump to original message';
    bq.addEventListener('click', e => {
      e.stopPropagation();
      if (_activeSeekToMessage) {
        _activeSeekToMessage(msgId);
      }
    });
  });
  body.appendChild(textEl);
  col.appendChild(body);

  // File attachments — render as clickable links
  if (msg.attachments && msg.attachments.length) {
    const attachWrap = document.createElement('div');
    attachWrap.className = 'tp-msg-attachments';
    msg.attachments.forEach(a => {
      if (!a.content_url) return;
      const link = document.createElement('a');
      link.className = 'tp-msg-attachment-link';
      link.href = a.content_url;
      link.target = '_blank';
      link.rel = 'noopener';
      const ext = (a.name || '').split('.').pop()?.toLowerCase() || '';
      const icon = {pptx:'\uD83D\uDCCA',xlsx:'\uD83D\uDCCA',docx:'\uD83D\uDCC4',pdf:'\uD83D\uDCC4',png:'\uD83D\uDDBC',jpg:'\uD83D\uDDBC',jpeg:'\uD83D\uDDBC'}[ext] || '\uD83D\uDCCE';
      link.textContent = `${icon} ${a.name}`;
      attachWrap.appendChild(link);
    });
    col.appendChild(attachWrap);
  }

  // Reactions below body
  const reactBar = document.createElement('div');
  reactBar.className = 'tp-react-bar';
  _renderReactionBar(reactBar, msg.reactions || [], chatId, msg.id);
  col.appendChild(reactBar);

  msgEl.appendChild(col);

  // Hover actions — inline flex sibling, CSS :hover shows them, no gap possible
  const actions = document.createElement('div');
  actions.className = 'tp-msg-actions';

  if (!isMine) {
    async function _doReact(emoji) {
      actions.classList.remove('expanded');
      const existing = msg.reactions || [];
      // Match both emoji char ("✚") and Skype codepoint-name key ("2795_heavyplussign")
      const _skypeKeyToEmoji = key => { const m = key.match(/^([0-9a-fA-F]+)_/); if (m) { try { return String.fromCodePoint(parseInt(m[1], 16)); } catch {} } return key; };
      const alreadyReacted = existing.find(x => (x.type === emoji || _skypeKeyToEmoji(x.type) === emoji) && x.user === 'You');
      const action = alreadyReacted ? 'remove' : 'add';
      // Optimistic update — safe because server now tags the current user's reactions as 'You'
      if (action === 'add') {
        existing.push({ type: emoji, user: 'You' });
      } else {
        const idx = existing.findIndex(x => x.type === emoji && x.user === 'You');
        if (idx !== -1) existing.splice(idx, 1);
      }
      _renderReactionBar(reactBar, existing, chatId, msg.id);
      try {
        const res = await fetch(`/api/teams/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(msg.id)}/react`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reaction: emoji, action }),
        });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          console.warn('Reaction failed:', d.detail || res.status);
          // Roll back optimistic update on failure
          if (action === 'add') {
            const idx = existing.findIndex(x => x.type === emoji && x.user === 'You');
            if (idx !== -1) existing.splice(idx, 1);
          } else {
            existing.push({ type: emoji, user: 'You' });
          }
          _renderReactionBar(reactBar, existing, chatId, msg.id);
        } else {
          setTimeout(() => _syncActiveTeamsThread(chatId), 1500);
        }
      } catch (err) { console.warn('Reaction error:', err); }
    }

    // 6 quick-react choices — always visible on message hover
    TEAMS_REACTIONS.forEach(r => {
      const btn = document.createElement('button');
      btn.className = 'tp-msg-react-choice';
      btn.title = r.type;
      btn.textContent = r.emoji;
      btn.addEventListener('click', e => { e.stopPropagation(); _doReact(r.emoji); });
      actions.appendChild(btn);
    });

    // ⊕ circle-plus — opens full emoji picker
    const moreBtn = document.createElement('button');
    moreBtn.className = 'tp-msg-action-btn tp-msg-react-more';
    moreBtn.title = 'More reactions';
    moreBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
      <circle cx="7.5" cy="7.5" r="6.5"/>
      <line x1="7.5" y1="4.5" x2="7.5" y2="10.5"/>
      <line x1="4.5" y1="7.5" x2="10.5" y2="7.5"/>
    </svg>`;
    moreBtn.addEventListener('click', e => {
      e.stopPropagation();
      _openFullEmojiPicker(moreBtn, emoji => _doReact(emoji));
    });
    actions.appendChild(moreBtn);
  }

  // Reply button — available on all messages
  const replyBtn = document.createElement('button');
  replyBtn.className = 'tp-msg-action-btn tp-msg-reply-btn';
  replyBtn.title = 'Reply';
  replyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3L2 7l4 4"/><path d="M2 7h8a4 4 0 0 1 4 4v1"/></svg>';
  replyBtn.addEventListener('click', e => {
    e.stopPropagation();
    const preview = (msg.body || '').substring(0, 120);
    const senderAad = (msg.body_html || '').match(/data-aad="([^"]+)"/)?.[1] || '';
    _setTeamsReplyTo({
      id: msg.id,
      chat_id: chatId,
      sender_name: msg.sender_name || '',
      sender_aad: msg.sender_aad || senderAad,
      body_preview: preview,
      created_at: msg.created_at || '',
    });
    // Focus the compose editor
    document.querySelector('.tp-quill-editor .ql-editor')?.focus();
  });
  actions.appendChild(replyBtn);

  // Forward button — available on all messages (#114)
  const forwardBtn = document.createElement('button');
  forwardBtn.className = 'tp-msg-action-btn tp-msg-forward-btn';
  forwardBtn.title = 'Forward';
  forwardBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3l4 4-4 4"/><path d="M14 7H6a4 4 0 0 0-4 4v1"/></svg>';
  forwardBtn.addEventListener('click', e => {
    e.stopPropagation();
    const senderName = msg.sender_name || 'Someone';
    const origBody = msg.body_html || `<p>${escapeHtml(msg.body || '')}</p>`;
    // Build a deeplink back to the original message. Skype rejects originalMessageContext
    // in send properties (errorCode 201), so instead we append a real <a href> deeplink
    // to the forward body — it survives the round-trip and opens the source in native Teams.
    // chatId for channels is ch::teamId::channelId — extract the real 19:...@thread id.
    let _srcThreadId = chatId;
    if (chatId.startsWith('ch::')) {
      const _p = chatId.split('::');
      _srcThreadId = _p[2] || chatId;
    }
    const _srcDeeplink = (msg.id && _srcThreadId)
      ? `https://teams.microsoft.com/l/message/${encodeURIComponent(_srcThreadId)}/${encodeURIComponent(msg.id)}?context=${encodeURIComponent(JSON.stringify({ contextType: 'chat' }))}`
      : '';
    // Attribution header — show the original sender only. Never embed a formatted
    // timestamp into the outgoing body; timestamps belong to AI Gator's UI, not the
    // message content the recipient sees.
    const _linkLine = _srcDeeplink
      ? `<p style="font-size:.75rem;text-align:right"><a href="${_srcDeeplink}">↗ View original message</a></p>`
      : '';
    const _attribution = `<p style="margin:0 0 .2rem"><strong>${escapeHtml(senderName)}</strong></p>`;
    // displayHtml: shown in the non-editable preview panel (no schema URL, clean)
    const displayHtml = `<p style="font-size:.8rem;color:var(--text-sub);margin:0 0 .3rem">Forwarded message:</p>${_attribution}${origBody}`;
    // sendHtml: native Forward schema + attribution header + the deeplink so recipients
    // see who/when and can navigate back.
    const sendHtml = `<blockquote itemscope itemtype="http://schema.skype.com/Forward">${_attribution}${origBody}</blockquote>${_linkLine}`;
    _showNewTeamsCompose({ prefillHtml: sendHtml, prefillDisplay: displayHtml });
  });
  actions.appendChild(forwardBtn);

  if (isMine) {
    const editBtn = document.createElement('button');
    editBtn.className = 'tp-msg-action-btn';
    editBtn.title = 'Edit';
    editBtn.textContent = '✏️';
    editBtn.addEventListener('click', () => {
      const liveId = msgEl.dataset.msgId || msg.id;
      if (!liveId || liveId.startsWith('_optimistic_')) {
        _showAlert('Message is still sending — try again in a moment.', 'info');
        return;
      }
      _startInlineEdit(textEl, { ...msg, id: liveId }, chatId);
    });
    actions.appendChild(editBtn);

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'tp-msg-action-btn';
    deleteBtn.title = 'Delete';
    deleteBtn.textContent = '🗑️';
    deleteBtn.addEventListener('click', () => {
      const liveId = msgEl.dataset.msgId || msg.id;
      if (!liveId || liveId.startsWith('_optimistic_')) {
        _showAlert('Message is still sending — try again in a moment.', 'info');
        return;
      }
      _showConfirmModal('Delete message', 'This message will be permanently deleted.', 'Delete', async () => {
        try {
          const res = await fetch(`/api/teams/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(liveId)}`, { method: 'DELETE' });
          if (res.ok) {
            msgEl.style.opacity = '0.4';
            const textNode = msgEl.querySelector('.tp-msg-text');
            if (textNode) textNode.textContent = 'This message was deleted.';
            msgEl.querySelector('.tp-msg-actions')?.remove();
          } else {
            const d = await res.json().catch(() => ({}));
            _showConfirmModal('Delete failed', d.detail || `Status ${res.status}`, 'OK', () => {});
          }
        } catch (err) {
          _showConfirmModal('Delete error', err.message, 'OK', () => {});
        }
      });
    });
    actions.appendChild(deleteBtn);
  }

  msgEl.appendChild(actions);

  // Meta: timestamp + delivery tick — right side, opacity-controlled by CSS
  const meta = document.createElement('div');
  meta.className = 'tp-msg-meta';
  const timeSpan = document.createElement('span');
  timeSpan.className = 'tp-msg-time';
  timeSpan.innerHTML = relativeTime(msg.created_at) + (wasEdited ? ' <span class="tp-msg-edited">(edited)</span>' : '');
  meta.appendChild(timeSpan);
  msgEl.appendChild(meta);

  return msgEl;
}

function _teamsReactionHash(reactions) {
  if (!reactions || !reactions.length) return '';
  return reactions
    .map(r => `${r.type || ''}:${r.user || ''}`)
    .sort()
    .join('|');
}

function _teamsMessageSetHash(messages) {
  if (!messages || !messages.length) return '';
  return messages
    .map(m => {
      const id = m.id || '';
      const modified = m.last_modified_at || '';
      const reactionHash = _teamsReactionHash(m.reactions || []);
      return `${id}:${modified}:${reactionHash}`;
    })
    .join(';');
}

/* ── Reaction bar render ─────────────────────────────────── */
function _renderReactionBar(barEl, reactions, chatId, msgId) {
  barEl.innerHTML = '';
  const container = barEl.closest('[data-msg-id]');
  if (container) {
    container.dataset.reactionHash = _teamsReactionHash(reactions || []);
  }
  if (!reactions.length) return;

  // Group by type — normalize emoji chars to string names for consistent grouping
  const _emojiToName = {'👍':'like','❤️':'heart','😆':'laugh','😮':'surprised','😢':'sad','😡':'angry','😠':'angry'};
  const groups = {};
  reactions.forEach(r => {
    const key = _emojiToName[r.type] || r.type;
    if (!groups[key]) groups[key] = [];
    groups[key].push(r.user);
  });

  // Convert Skype reaction keys → emoji char.
  // Teams uses three naming schemes (see https://office365itpros.com/2025/11/07/teams-reactions-emojis/):
  //   1. Codepoint prefix: "2795_heavyplussign" → 0x2795 → ➕
  //   2. Short named tokens: "handsinair", "fire", "clap"… (no codepoint encoded)
  //   3. Skin-tone variants: "yes-tone1" → 👍🏻
  // Microsoft doesn't publish the full list, so the named-token map is a best-effort
  // catalogue. Unknown keys fall through to the raw string as before.
  function _skypeKeyToEmoji(key) {
    if (_TEAMS_NAMED_REACTIONS[key]) return _TEAMS_NAMED_REACTIONS[key];
    // Strip skin-tone suffix and retry (yes-tone1 → yes → 👍)
    const toneMatch = key.match(/^(.+)-tone[1-5]$/i);
    if (toneMatch && _TEAMS_NAMED_REACTIONS[toneMatch[1]]) return _TEAMS_NAMED_REACTIONS[toneMatch[1]];
    const m = key.match(/^([0-9a-fA-F]+)_/);
    if (m) {
      try { return String.fromCodePoint(parseInt(m[1], 16)); } catch {}
    }
    // Fallback: resolve against the emojibase name index (built from the loaded dataset).
    // Catches newer named reactions the curated map misses — speaknoevil → 🙊,
    // meltingface → 🫠 — by matching the key to an emoji label, exact then prefix.
    const fromData = _reactionKeyFromEmojiData(key);
    if (fromData) return fromData;
    return key;
  }

    let _hadUnresolved = false;
  Object.entries(groups).forEach(([type, users]) => {
    // type may be a Skype named key ("like"), a codepoint key ("2795_heavyplussign"), or an emoji char
    const knownReaction = TEAMS_REACTIONS.find(x => x.type === type || x.emoji === type);
    const displayEmoji = knownReaction ? knownReaction.emoji : _skypeKeyToEmoji(type);
    // A named key that resolved to itself (still shows as a word like "speaknoevil")
    // means the emoji dataset wasn't loaded yet — flag it to retry after data loads.
    if (!knownReaction && displayEmoji === type && /[a-z]/i.test(type)) _hadUnresolved = true;
    // The emoji to send to the API is always the emoji char
    const apiEmoji = knownReaction ? knownReaction.emoji : displayEmoji;
    const pill = document.createElement('button');
    pill.className = 'tp-react-pill';
    pill.title = users.join(', ');
    pill.innerHTML = `${displayEmoji} <span>${users.length}</span>`;
    pill.addEventListener('click', async () => {
      const iMine = users.includes('You');
      const action = iMine ? 'remove' : 'add';
      // Optimistic update
      if (iMine) users.splice(users.indexOf('You'), 1);
      else users.push('You');
      _renderReactionBar(barEl, Object.entries(groups).flatMap(([t, u]) => u.map(x => ({ type: t, user: x }))), chatId, msgId);
      try {
        const res = await fetch(`/api/teams/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(msgId)}/react`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reaction: apiEmoji, action }),
        });
        if (!res.ok) {
          console.warn('Reaction pill failed:', res.status);
          // Roll back
          if (iMine) users.push('You');
          else users.splice(users.indexOf('You'), 1);
          _renderReactionBar(barEl, Object.entries(groups).flatMap(([t, u]) => u.map(x => ({ type: t, user: x }))), chatId, msgId);
        } else {
          setTimeout(() => _syncActiveTeamsThread(chatId), 1500);
        }
      } catch {}
    });
    barEl.appendChild(pill);
  });

  // Some named reaction keys couldn't be resolved because the emoji dataset hadn't
  // loaded yet. Load it, then re-render this bar once so the pills show the real emoji.
  if (_hadUnresolved && !_emojiKW) {
    _loadEmojiData().then(() => {
      if (barEl.isConnected) {
        _renderReactionBar(barEl, Object.entries(groups).flatMap(([t, u]) => u.map(x => ({ type: t, user: x }))), chatId, msgId);
      }
    });
  }
}

/* ── Inline message edit ─────────────────────────────────── */
function _startInlineEdit(textEl, msg, chatId) {
  if (textEl.dataset.editing) return; // already editing
  _runInlineEdit(textEl, msg, chatId);
}

/**
 * Pre-process an HTML body string before passing to dangerouslyPasteHTML:
 * replaces <at data-aad="guid">Name</at> elements with <span class="ql-mention">
 * so Quill's clipboard reads them as native MentionBlots via MentionBlot.value().
 * This avoids Quill.find() index-arithmetic on unregistered tags (#92 / #119).
 */
function _tpConvertAtNodesToMentionBlots(html) {
  return html.replace(
    /<at\b[^>]*\bdata-aad="([^"]*)"[^>]*>([\s\S]*?)<\/at>/gi,
    (_, aadId, inner) => {
      const name = inner.replace(/<[^>]+>/g, '').trim();
      const esc = s => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      return `<span class="ql-mention" contenteditable="false" data-id="${esc(aadId)}" data-name="${esc(name)}" data-email="">@${esc(name)}</span>`;
    },
  );
}

function _runInlineEdit(textEl, msg, chatId) {
  if (textEl.dataset.editing) return;
  // Prefer textEl.dataset.bodyHtml (updated after each save) over the spread-copy
  // msg object which may carry the pre-edit body_html (#117).
  const _origBody = textEl.dataset.bodyHtml || msg.body_html || msg.body || '';
  textEl.dataset.editing = '1';
  const original = textEl.innerHTML;
  // Capture each original <img> tag keyed by its ASM object id. Native Teams needs
  // the full AMSImage metadata (itemtype/itemscope/itemid/id) to render a hosted
  // image — Quill strips all of these, leaving a bare <img src> that only renders
  // in our token-proxy view, not in native Teams (#112). On save we restore the
  // original markup by matching the object id in the surviving src URL.
  const _origImgByObjId = {};
  {
    const _imgRe = /<img\b[^>]*>/gi;
    let _im;
    while ((_im = _imgRe.exec(_origBody)) !== null) {
      let tag = _im[0];
      // Backend stores images as src="" data-teams-src="<realUrl>" for lazy-load.
      // Normalise to a populated src="<realUrl>" (and drop data-teams-src) so the
      // restored tag is what native Teams expects.
      const dts = tag.match(/\bdata-teams-src="([^"]+)"/);
      if (dts) {
        tag = tag.replace(/\bsrc=""/, `src="${dts[1]}"`).replace(/\s*data-teams-src="[^"]+"/, '');
      }
      const oid = (tag.match(/objects\/([^/"?]+)/) || [])[1]
        || (tag.match(/\bitemid="([^"]+)"/) || [])[1];
      if (oid) _origImgByObjId[oid] = tag;
    }
  }
  // Use the message's actual HTML/text — not the rendered DOM which contains UI chrome.
  // Backend rewrites <img src> to src="" + data-teams-src="<real_url>" for lazy-loading.
  // For the editor, rewrite those back to a working proxy URL so images render.
  let originalContent = _origBody;
  // Backend rewrites asm.skype.com URLs to src="" + data-teams-src="<real>".
  // Quill drops custom data-* attrs, so swap them to a proxy URL for display —
  // the original URL is preserved inside the proxy URL's `?url=` param and gets
  // decoded back on save. Microsoft's documented workaround for the hostedContents
  // PATCH bug: https://learn.microsoft.com/en-us/answers/questions/1443196/
  originalContent = originalContent.replace(
    /src="" data-teams-src="([^"]+)"/g,
    (_m, url) => `src="/api/teams/proxy-image?url=${encodeURIComponent(url)}"`,
  );
  // The optimistic bubble (just after send) stores a direct asm.skype.com src.
  // The browser can't load that without the Skype token, so route it through the
  // proxy for the editor too — otherwise a just-sent image shows broken on edit.
  originalContent = originalContent.replace(
    /\bsrc="(https:\/\/[^"]*asm\.skype\.com[^"]+)"/g,
    (_m, url) => `src="/api/teams/proxy-image?url=${encodeURIComponent(url)}"`,
  );

  // Normalise <a> tags so Quill 1.3.7's clipboard reliably keeps the link.
  // Skype-rendered links sometimes carry title/rel/target/data-* attrs that
  // confuse Quill's Link attributor, and any href that's not in the protocol
  // whitelist (http/https/mailto/tel) gets dropped — so we strip everything
  // except href and only keep links that Quill will actually preserve.
  originalContent = originalContent.replace(
    /<a\b[^>]*\bhref\s*=\s*(['"])([^'"]+)\1[^>]*>/gi,
    (m, _q, href) => {
      const safe = /^(https?:|mailto:|tel:)/i.test(href);
      return safe ? `<a href="${href}">` : m;
    },
  );

  // Clear current content and insert Quill editor
  textEl.innerHTML = '';
  const editor = _buildQuillEditor({ placeholder: 'Edit message…', showSendBtn: false, showResize: false });
  textEl.appendChild(editor.wrapEl);

  // Pre-populate with existing message content via Quill's clipboard API (not innerHTML)
  setTimeout(() => {
    if (editor.quill) {
      try {
        // Pre-convert <at data-aad> → ql-mention spans before paste so Quill reads
        // them as native MentionBlots — avoids DOM index-arithmetic on unknown tags (#92/#119)
        editor.quill.clipboard.dangerouslyPasteHTML(0, _tpConvertAtNodesToMentionBlots(originalContent));
      } catch (_e) {
        // Fallback to plain text if HTML paste fails
        editor.quill.setText(msg.body || originalContent);
      }
      editor.quill.focus();
      const len = editor.quill.getLength();
      if (len > 0) editor.quill.setSelection(len - 1, 0);
    }
  }, 60);

  // Save / Cancel buttons — injected into the Quill toolbar (right side)
  const saveBtn = document.createElement('button');
  saveBtn.className = 'tp-ai-btn';
  saveBtn.style.cssText = 'font-size:.72rem;padding:.15rem .5rem;height:22px;';
  saveBtn.textContent = 'Save';

  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'tp-ai-btn secondary';
  cancelBtn.style.cssText = 'font-size:.72rem;padding:.15rem .5rem;height:22px;';
  cancelBtn.textContent = 'Cancel';

  // Append into toolbar after a spacer
  setTimeout(() => {
    const toolbar = editor.wrapEl.querySelector('.tp-quill-toolbar');
    if (toolbar) {
      const spacer = document.createElement('span');
      spacer.style.flex = '1';
      toolbar.appendChild(spacer);
      toolbar.appendChild(cancelBtn);
      toolbar.appendChild(saveBtn);
    } else {
      // Fallback: below the wrap
      const btnRow = document.createElement('div');
      btnRow.className = 'tp-inline-edit-btns';
      btnRow.appendChild(cancelBtn);
      btnRow.appendChild(saveBtn);
      textEl.appendChild(btnRow);
    }
  }, 0);

  function cancelEdit() {
    delete textEl.dataset.editing;
    textEl.innerHTML = original;
  }

  cancelBtn.addEventListener('click', cancelEdit);

  // Keyboard shortcuts + @mention dropdown (available once quill initialises)
  setTimeout(() => {
    if (!editor.quill) return;
    editor.quill.root.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.stopPropagation(); cancelEdit(); }
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); saveBtn.click(); }
    });
    // Wire @mention people-search — was missing from edit pane (#134)
    _wireMentionDropdownQuill(editor.quill, editor.quill.root);
  }, 80);

  saveBtn.addEventListener('click', async () => {
    const quill = editor.quill;
    if (!quill) return;

    // Convert Quill HTML: p → div (Teams prefers div blocks)
    let body = quill.root.innerHTML
      .replace(/<p>/g, '<div>').replace(/<\/p>/g, '</div>')
      .trim();
    body = _stripTrailingEmptyBlocks(body);

    // Extract @mentions from Quill FIRST — _buildMentionPayload re-serializes the
    // editor HTML, so it must run before the image restore below or it would clobber
    // the restored AMSImage markup with Quill's stripped version (#92, #119, #112).
    let mentions = [];
    const mentionPayload = _buildMentionPayload(quill);
    if (mentionPayload.html) {
      body = mentionPayload.html;
    }
    if (mentionPayload.mentions?.length) {
      mentions = mentionPayload.mentions;
    }

    // Rebuild each <img> with the full AMSImage metadata native Teams requires to
    // resolve a hosted image (itemtype/itemscope/itemid/id). A bare <img src> renders
    // on initial send and in our token-proxy view, but native Teams drops it after an
    // edit PUT (#112). Quill strips the metadata, and our own send path never adds it,
    // so we SYNTHESIZE canonical markup from the ASM object id rather than only
    // preserving what was there. Falls back to a decoded plain <img src> if no object
    // id can be recovered.
    body = body.replace(/<img\b[^>]*>/gi, (tag) => {
      // Pull the ASM object id from whichever URL form Quill left behind.
      const oid =
        (tag.match(/proxy-image\?url=([^"]+)/) &&
          decodeURIComponent(tag.match(/proxy-image\?url=([^"]+)/)[1]).match(/objects\/([^/"?]+)/)?.[1]) ||
        (tag.match(/objects\/([^/"?]+)/) || [])[1] ||
        (tag.match(/\bitemid="([^"]+)"/) || [])[1];
      if (!oid) {
        // No object id — best effort: decode proxy URL back to the real ASM URL.
        const proxyM = tag.match(/src="\/api\/teams\/proxy-image\?url=([^"]+)"/);
        if (proxyM) return tag.replace(proxyM[0], `src="${decodeURIComponent(proxyM[1])}"`);
        return tag;
      }
      // Prefer the original tag if it already carried full AMSImage metadata.
      const orig = _origImgByObjId[oid];
      if (orig && /itemtype="http:\/\/schema\.skype\.com\/AMSImage"/i.test(orig)) return orig;
      // Otherwise synthesize canonical AMSImage markup. Carry over alt/width/height
      // from the original or current tag when present (all optional for Teams).
      const src = `https://us-api.asm.skype.com/v1/objects/${oid}/views/imgo`;
      const pick = (re, from) => (from && (from.match(re) || [])[1]) || '';
      const alt = pick(/\balt="([^"]*)"/, orig) || pick(/\balt="([^"]*)"/, tag) || 'image';
      const w = pick(/\bwidth="([^"]*)"/, orig) || pick(/\bwidth="([^"]*)"/, tag);
      const h = pick(/\bheight="([^"]*)"/, orig) || pick(/\bheight="([^"]*)"/, tag);
      const dims = (w ? ` width="${w}"` : '') + (h ? ` height="${h}"` : '');
      return `<img src="${src}" itemtype="http://schema.skype.com/AMSImage" itemscope="png"${dims} alt="${alt}" id="x_${oid}" itemid="${oid}">`;
    });
    const isHtml = /<[a-z][\s\S]*>/i.test(body);

    if (!body || body === '<div><br></div>') { cancelEdit(); return; }

    // Extract any NEWLY-pasted images (data: URIs) into hosted_images so the backend
    // uploads them to ASM — otherwise an image added during an edit PATCHes a raw
    // base64 blob native Teams can't store as a hosted image (#112). Existing images
    // are already real ASM URLs and untouched.
    let hostedImages = [];
    if (body.includes('data:')) {
      try {
        const doc = new DOMParser().parseFromString(body, 'text/html');
        let changed = false;
        doc.querySelectorAll('img[src^="data:"]').forEach(img => {
          const src = img.getAttribute('src') || '';
          const comma = src.indexOf(',');
          if (comma === -1) return;
          const parts = src.slice(5, comma).split(';');
          if (!parts.includes('base64')) return;
          hostedImages.push({ contentType: parts[0] || 'application/octet-stream', contentBytes: src.slice(comma + 1) });
          img.setAttribute('src', `../hostedContents/${hostedImages.length}/$value`);
          changed = true;
        });
        if (changed) body = doc.body.innerHTML;
      } catch {}
    }

    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    try {
      const res = await fetch(`/api/teams/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(msg.id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body, is_html: isHtml, mentions, hosted_images: hostedImages }),
      });
      const editResp = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(editResp.detail || res.status);
      }
      // If new images were uploaded, the backend resolved ../hostedContents/N
      // placeholders to real ASM URLs — use that so the bubble + next edit have the
      // real reference, not a stale placeholder (#112).
      if (editResp.body_html) body = editResp.body_html;
      delete textEl.dataset.editing;
      // Sync msg cache with edited content so second-edit reads current body (#117).
      // msg is a spread copy ({...msg}) — also write to textEl.dataset so the edit
      // button closure reads the live value on next click.
      msg.body_html = body;
      msg.body = body;
      // Normalize Skype mention spans → at[data-aad] chips for immediate display (#92)
      const displayBody = mentions.length
        ? body.replace(
            /<span[^>]*itemtype="http:\/\/schema\.skype\.com\/Mention"[^>]*itemid="(\d+)"[^>]*>(.*?)<\/span>/g,
            (_, itemid, inner) => {
              const m = mentions.find(x => String(x.id) === itemid);
              const aad = m?.mentioned?.user?.id || '';
              return aad ? `<at data-aad="${aad}">${inner}</at>` : `<at>${inner}</at>`;
            })
        : body;
      // Store the <at data-aad> normalized form so the next edit pre-populates
      // correctly — Quill's own serialization (ql-mention spans) is NOT what
      // _tpConvertAtNodesToMentionBlots expects on the second edit.
      textEl.dataset.bodyHtml = displayBody;
      // For immediate local re-render, rewrite ASM image URLs to our token-proxy —
      // the browser can't load asm.skype.com directly (needs the Skype token). This
      // mirrors what the backend does on fetch; without it the image breaks until
      // refresh. dataset.bodyHtml keeps the real ASM src for the next edit/PATCH.
      const localDisplay = displayBody.replace(
        /<img\b([^>]*)\bsrc="(https:\/\/[^"]*asm\.skype\.com[^"]+)"([^>]*)>/gi,
        (_m, pre, url, post) =>
          `<img${pre}src="/api/teams/proxy-image?url=${encodeURIComponent(url)}"${post}>`,
      );
      textEl.innerHTML = sanitizeHtml(localDisplay);
      // Re-wire at[data-aad] click handlers after innerHTML update
      textEl.querySelectorAll('at[data-aad]').forEach(el => {
        const aadId = el.dataset.aad;
        if (!aadId) return;
        el.style.cursor = 'pointer';
        el.addEventListener('click', e => { e.stopPropagation(); _showPersonCard(aadId, el); });
      });
      const timeEl = textEl.closest('.tp-msg')?.querySelector('.tp-msg-time');
      if (timeEl && !timeEl.querySelector('.tp-msg-edited')) {
        timeEl.insertAdjacentHTML('beforeend', ' <span class="tp-msg-edited">(edited)</span>');
      }
    } catch (err) {
      cancelEdit();
      _showAlert('Edit failed: ' + err.message, 'error');
    }
  });

  // Scroll editor into view
  setTimeout(() => editor.wrapEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 80);
}

/* ── Shared compose helpers ──────────────────────────────── */

/**
 * Build a multi-recipient field (To / CC / BCC) with chip UI.
 * Returns { rowEl, getEmails, focusInput }
 */
function _buildRecipientField({ label, chipClass, avatarClass, placeholder = 'Search people…', onchange, normalizeSearch = false, orgOnly = false }) {
  const row = document.createElement('div');
  row.className = 'tp-new-compose-to';
  row.innerHTML = `
    <label>${label}</label>
    <div class="tp-compose-chips-wrap">
      <div class="tp-compose-chips"></div>
      <input type="text" class="tp-new-compose-to-input" placeholder="${placeholder}" autocomplete="off">
    </div>
    <div class="tp-new-compose-people hidden"></div>`;

  const chipsEl = row.querySelector('.tp-compose-chips');
  const input = row.querySelector('.tp-new-compose-to-input');
  const dd = row.querySelector('.tp-new-compose-people');
  const people = [];
  let timer = null;

  function addPerson(p, { preserveExistingChat = false, notify = true } = {}) {
    if (people.find(x => x.email === p.email)) return;
    people.push(p);
    const chip = document.createElement('span');
    chip.className = `chat-chip ${chipClass}`;
    chip.dataset.email = p.email || '';
    chip.innerHTML = `${escapeHtml(p.name || p.email)}<button class="chip-remove" title="Remove">✕</button>`;
    chip.querySelector('.chip-remove').addEventListener('click', () => {
      people.splice(people.indexOf(p), 1);
      chip.remove();
      if (!chipsEl.children.length) input.placeholder = placeholder;
      onchange && onchange({ recipientsChanged: true, people });
    });
    chipsEl.appendChild(chip);
    input.placeholder = '';
    input.value = '';
    dd.classList.add('hidden');
    if (notify) onchange && onchange({ recipientsChanged: !preserveExistingChat, people });
  }

  let ddPeople = []; // track current results for keyboard nav
  let ddFocusIdx = -1;

  function ddSetFocus(idx) {
    const items = dd.querySelectorAll('.tp-new-compose-person');
    items.forEach((el, i) => el.classList.toggle('tp-person-focused', i === idx));
    ddFocusIdx = idx;
  }

  input.addEventListener('keydown', e => {
    const items = dd.querySelectorAll('.tp-new-compose-person');
    if (dd.classList.contains('hidden') || !items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      ddSetFocus(Math.min(ddFocusIdx + 1, items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      ddSetFocus(Math.max(ddFocusIdx - 1, 0));
    } else if (e.key === 'Enter' && ddFocusIdx >= 0) {
      e.preventDefault();
      const p = ddPeople[ddFocusIdx];
      if (p) { addPerson(p); ddFocusIdx = -1; }
    } else if (e.key === 'Escape') {
      dd.classList.add('hidden');
      ddFocusIdx = -1;
    }
  });

  input.addEventListener('input', () => {
    const q = normalizeSearch ? _teamsComposePeopleSearchQuery(input.value) : input.value.trim();
    ddFocusIdx = -1;
    if (q.length < 2) { dd.classList.add('hidden'); return; }
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/people/search?q=${encodeURIComponent(q)}${orgOnly ? '&org_only=true' : ''}`);
        const data = await res.json();
        // Ignore a stale response if the user kept typing while it was in flight
        if (normalizeSearch ? _teamsComposePeopleSearchQuery(input.value) !== q : input.value.trim() !== q) return;
        ddPeople = data.people || [];
        dd.innerHTML = '';
        if (!ddPeople.length) {
          dd.innerHTML = '<div class="tp-new-compose-no-results">No results</div>';
          dd.classList.remove('hidden');
          return;
        }
        ddPeople.forEach((p, i) => {
          const item = document.createElement('div');
          item.className = 'tp-new-compose-person';
          const initial = (p.name || p.email || '?')[0].toUpperCase();
          const displayName = p.name || p.email || '';
          const displayEmail = p.email || '';
          item.innerHTML = `<span class="tp-avatar ${avatarClass}" style="width:24px;height:24px;font-size:.6rem">${initial}</span>
            <span class="tp-new-compose-person-info">
              <span class="tp-new-compose-person-name" title="${escapeHtml(displayName)}">${escapeHtml(displayName)}</span>
              <span class="tp-new-compose-person-sub" title="${escapeHtml(displayEmail)}">${escapeHtml(displayEmail)}</span>
            </span>`;
          item.addEventListener('mousedown', e => { e.preventDefault(); addPerson(p); input.focus(); });
          item.addEventListener('mouseover', () => ddSetFocus(i));
          dd.appendChild(item);
        });
        dd.classList.remove('hidden');
      } catch { dd.classList.add('hidden'); }
    }, 150);
  });

  // Hide dropdown on blur
  input.addEventListener('blur', () => setTimeout(() => { dd.classList.add('hidden'); ddFocusIdx = -1; }, 150));

  function removePerson(emailAddr) {
    const key = String(emailAddr || '').toLowerCase();
    const idx = people.findIndex(p => String(p.email || '').toLowerCase() === key);
    if (idx === -1) return false;
    people.splice(idx, 1);
    const chip = [...chipsEl.children].find(c => String(c.dataset.email || '').toLowerCase() === key);
    if (chip) chip.remove();
    if (!chipsEl.children.length) input.placeholder = placeholder;
    onchange && onchange({ recipientsChanged: true, people });
    return true;
  }

  return {
    rowEl: row,
    getEmails: () => people.map(p => p.email).join(','),
    getPeople: () => people.slice(),
    focusInput: () => input.focus(),
    addPerson,
    removePerson,
  };
}

/* ── Quill image resize (global singleton) ───────────────── */
let _qiOverlay = null, _qiActiveImg = null, _qiCorner = null, _qiStartX = 0, _qiStartW = 0;

function _ensureQiOverlay() {
  if (_qiOverlay) return;
  _qiOverlay = document.createElement('div');
  _qiOverlay.className = 'qi-overlay';
  ['nw','ne','sw','se'].forEach(c => {
    const h = document.createElement('div');
    h.className = `qi-handle qi-${c}`;
    h.dataset.c = c;
    h.addEventListener('mousedown', e => {
      e.preventDefault(); e.stopPropagation();
      _qiCorner = c; _qiStartX = e.clientX;
      _qiStartW = _qiActiveImg ? _qiActiveImg.getBoundingClientRect().width : 0;
    });
    _qiOverlay.appendChild(h);
  });
  document.body.appendChild(_qiOverlay);

  document.addEventListener('mousemove', e => {
    if (!_qiCorner || !_qiActiveImg) return;
    const sign = (_qiCorner === 'nw' || _qiCorner === 'sw') ? -1 : 1;
    const newW = Math.max(40, _qiStartW + sign * (e.clientX - _qiStartX));
    _qiActiveImg.style.width = newW + 'px';
    _qiActiveImg.style.height = 'auto';
    _qiPositionOverlay();
  });

  document.addEventListener('mouseup', () => { _qiCorner = null; });

  document.addEventListener('click', e => {
    if (_qiActiveImg && !_qiOverlay.contains(e.target) && e.target !== _qiActiveImg) {
      _qiHide();
    }
  }, true);

  // Delete or Backspace while image is selected removes it
  document.addEventListener('keydown', e => {
    if (!_qiActiveImg) return;
    if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault();
      _qiActiveImg.remove();
      _qiHide();
    }
  }, true);

  document.addEventListener('scroll', _qiPositionOverlay, true);
  window.addEventListener('resize', _qiPositionOverlay);
}

function _qiPositionOverlay() {
  if (!_qiActiveImg || !_qiOverlay) return;
  const r = _qiActiveImg.getBoundingClientRect();
  // Clip to the nearest scrollable ancestor (the editor wrapper) so the
  // overlay never draws outside the visible text area.
  const clipEl = _qiActiveImg.closest('.tp-quill-editor, .tp-quill-wrap');
  if (clipEl) {
    const c = clipEl.getBoundingClientRect();
    const left   = Math.max(r.left,   c.left);
    const top    = Math.max(r.top,    c.top);
    const right  = Math.min(r.right,  c.right);
    const bottom = Math.min(r.bottom, c.bottom);
    if (right <= left || bottom <= top) { _qiOverlay.style.display = 'none'; return; }
    _qiOverlay.style.left   = left + 'px';
    _qiOverlay.style.top    = top  + 'px';
    _qiOverlay.style.width  = (right - left)  + 'px';
    _qiOverlay.style.height = (bottom - top)  + 'px';
  } else {
    _qiOverlay.style.left   = r.left   + 'px';
    _qiOverlay.style.top    = r.top    + 'px';
    _qiOverlay.style.width  = r.width  + 'px';
    _qiOverlay.style.height = r.height + 'px';
  }
  _qiOverlay.style.display = 'block';
}

function _qiHide() {
  if (_qiOverlay) _qiOverlay.style.display = 'none';
  _qiActiveImg = null; _qiCorner = null;
}

function _initQuillImageResize(editorEl) {
  _ensureQiOverlay();
  editorEl.addEventListener('click', e => {
    if (e.target.tagName === 'IMG') {
      _qiActiveImg = e.target;
      _qiPositionOverlay();
    } else if (!_qiOverlay.contains(e.target)) {
      _qiHide();
    }
  });
}

/* ── Quill MentionBlot — atomic @mention chip ────────── */
(function _registerMentionBlot() {
  if (typeof Quill === 'undefined') return;
  const Embed = Quill.import('blots/embed');
  class MentionBlot extends Embed {
    static create(data) {
      const node = super.create();
      node.setAttribute('contenteditable', 'false');
      node.dataset.id    = data.id    || '';
      node.dataset.name  = data.name  || '';
      node.dataset.email = data.email || '';
      node.textContent = '@' + data.name;
      return node;
    }
    static value(node) {
      return { id: node.dataset.id, name: node.dataset.name, email: node.dataset.email };
    }
  }
  MentionBlot.blotName  = 'mention';
  MentionBlot.tagName   = 'span';
  MentionBlot.className = 'ql-mention';
  Quill.register(MentionBlot);
})();

/**
 * Build a plain contenteditable HTML editor — used when body_html is provided.
 * Supports tables, inline styles, and any HTML that Quill cannot handle.
 * Returns the same interface as _buildQuillEditor: { wrapEl, quill, getHtml, isEmpty }
 */
function _buildHtmlEditor({ placeholder, html }) {
  const wrap = document.createElement('div');
  wrap.className = 'tp-quill-wrap';

  const editorDiv = document.createElement('div');
  editorDiv.className = 'tp-quill-editor tp-html-editor';
  const editableDiv = document.createElement('div');
  editableDiv.className = 'ql-editor';
  editableDiv.setAttribute('contenteditable', 'true');
  editableDiv.setAttribute('data-placeholder', placeholder || '');
  editableDiv.innerHTML = html || '';
  editorDiv.appendChild(editableDiv);
  wrap.appendChild(editorDiv);

  // Minimal toolbar (send button only — formatting is already in the HTML)
  const toolbar = document.createElement('div');
  toolbar.className = 'tp-quill-toolbar';
  toolbar.innerHTML = `
    <button class="tp-qt-btn tp-qt-attach-btn" title="Attach file">\uD83D\uDCCE</button>
    <span style="flex:1"></span>
    <button class="tp-qt-send-btn tp-compose-send" title="Send (Enter)">
      <span class="material-symbols-outlined" aria-hidden="true" style="font-size:16px;font-variation-settings:'FILL' 1,'wght' 400,'GRAD' 0,'opsz' 20;line-height:1;">send</span>
    </button>`;
  wrap.appendChild(toolbar);

  // Keep the original HTML (may include <style> blocks, full document wrapper, etc.)
  // so we can send it intact. The browser strips these when set via innerHTML.
  let _originalHtml = html || '';
  let _userEdited = false;
  editableDiv.addEventListener('input', () => { _userEdited = true; }, { once: true });

  // contenteditable blocks link clicks — intercept and open in new tab so the user
  // can verify hyperlinks in the draft without leaving the compose pane.
  editableDiv.addEventListener('click', e => {
    const a = e.target.closest('a[href]');
    if (a) { e.preventDefault(); window.open(a.href, '_blank', 'noopener'); }
  });

  wrap.getHtml = () => _userEdited ? editableDiv.innerHTML : _originalHtml;
  wrap.isEmpty = () => !editableDiv.textContent.trim();
  wrap.clearDraft = () => {};
  wrap.quill = null; // no Quill instance
  wrap.wrapEl = wrap;
  return wrap;
}

/**
 * Build a Quill rich-text editor with bottom toolbar.
 * Returns { wrapEl, quill, getHtml, isEmpty }
 */
function _buildQuillEditor({ placeholder, draftKey, showSendBtn = true, showResize = true }) {
  const wrap = document.createElement('div');
  wrap.className = 'tp-quill-wrap';

  if (showResize) {
    const resizeHandle = document.createElement('div');
    resizeHandle.className = 'compose-resize-handle';
    wrap.appendChild(resizeHandle);
    _initComposeResize(resizeHandle, wrap, 52);
  }

  const editorDiv = document.createElement('div');
  editorDiv.className = 'tp-quill-editor';
  wrap.appendChild(editorDiv);

  // Bottom toolbar — formatting + attach + morph slot (mic↔send) at far right.
  // Slot lives in the toolbar so it's at the expected position (where old send
  // button was), survives Quill's DOM init, and Discard insertions stay in toolbar.
  const toolbar = document.createElement('div');
  toolbar.className = 'tp-quill-toolbar';
  toolbar.innerHTML = `
    <button class="tp-qt-btn" data-cmd="bold" title="Bold (Ctrl+B)"><b>B</b></button>
    <button class="tp-qt-btn" data-cmd="italic" title="Italic (Ctrl+I)"><i>I</i></button>
    <button class="tp-qt-btn" data-cmd="underline" title="Underline (Ctrl+U)"><u>U</u></button>
    <span class="tp-qt-sep"></span>
    <button class="tp-qt-btn" data-cmd="bullet" title="Bullet list">≡</button>
    <button class="tp-qt-btn" data-cmd="ordered" title="Numbered list">1.</button>
    <button class="tp-qt-btn" data-cmd="indent" title="Indent"><span class="material-symbols-outlined tp-mi">format_indent_increase</span></button>
    <button class="tp-qt-btn" data-cmd="outdent" title="Outdent"><span class="material-symbols-outlined tp-mi">format_indent_decrease</span></button>
    <button class="tp-qt-btn" data-cmd="code-block" title="Code block"><span class="material-symbols-outlined tp-mi">code_blocks</span></button>
    <span class="tp-qt-sep"></span>
    <button class="tp-qt-btn" data-cmd="link" title="Insert link"><span class="material-symbols-outlined tp-mi">link</span></button>
    <button class="tp-qt-btn tp-qt-emoji-btn" title="Emoji"><span class="material-symbols-outlined tp-mi">mood</span></button>
    <div class="tp-emoji-picker-popup hidden"></div>
    <span class="tp-qt-sep"></span>
    <button class="tp-qt-btn tp-qt-attach-btn" title="Attach file">📎</button>`;

  // Morph slot appended last in toolbar; margin-left:auto pushes it to far right.
  // Left border acts as the visual separator before mic/send.
  let sendSlotEl = null;
  if (showSendBtn) {
    sendSlotEl = document.createElement('div');
    sendSlotEl.className = 'tp-quill-send-slot';
    sendSlotEl.innerHTML = `
      <button type="button" class="tp-qt-mic-btn" title="Dictate (Ctrl+Shift+Space)" aria-label="Dictate with speech to text">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" y1="19" x2="12" y2="23"/>
          <line x1="8" y1="23" x2="16" y2="23"/>
        </svg>
      </button>
      <button type="button" class="tp-qt-send-btn tp-compose-send" title="Send (Enter)">
        <span class="material-symbols-outlined tp-send-mi" aria-hidden="true">send</span>
      </button>`;
    toolbar.appendChild(sendSlotEl);
  }
  wrap.appendChild(toolbar);

  // Init Quill after DOM insertion (caller must append wrapEl first)
  let quill;
  setTimeout(() => {
    quill = new Quill(editorDiv, {
      theme: false,
      placeholder,
      modules: { keyboard: { bindings: {} } },
    });

    // Restore draft
    if (draftKey) {
      try {
        const saved = localStorage.getItem(draftKey);
        if (saved) { quill.root.innerHTML = saved; }
      } catch {}
    }

    // Toolbar button handlers
    toolbar.querySelectorAll('.tp-qt-btn[data-cmd]').forEach(btn => {
      btn.addEventListener('mousedown', e => {
        e.preventDefault();
        const cmd = btn.dataset.cmd;
        if (cmd === 'bold') quill.format('bold', !quill.getFormat().bold);
        else if (cmd === 'italic') quill.format('italic', !quill.getFormat().italic);
        else if (cmd === 'underline') quill.format('underline', !quill.getFormat().underline);
        else if (cmd === 'bullet') {
          const cur = quill.getFormat().list;
          quill.format('list', cur === 'bullet' ? false : 'bullet');
        } else if (cmd === 'ordered') {
          const cur = quill.getFormat().list;
          quill.format('list', cur === 'ordered' ? false : 'ordered');
        } else if (cmd === 'indent') {
          quill.format('indent', '+1');
        } else if (cmd === 'outdent') {
          quill.format('indent', '-1');
        } else if (cmd === 'code-block') {
          const cur = quill.getFormat()['code-block'];
          quill.format('code-block', !cur);
        } else if (cmd === 'link') {
          // Capture selection before the modal steals focus — Quill loses it on blur.
          const sel = quill.getSelection(true);
          _showPromptModal('Insert link', 'URL', '', 'https://example.com', url => {
            const trimmed = (url || '').trim();
            if (!trimmed) return;
            if (sel) quill.setSelection(sel.index, sel.length);
            quill.format('link', trimmed);
          });
        }
      });
    });

    // Emoji picker
    _initEmojiPicker(toolbar, quill);

    // Shortcode trigger
    _initEmojiShortcode(quill);

    // Morph slot: toggle has-text so mic↔send crossfade matches main chat
    if (sendSlotEl) {
      const _updateSlot = () => {
        sendSlotEl.classList.toggle('has-text', quill.getText().trim().length > 0);
      };
      quill.on('text-change', _updateSlot);
      _updateSlot();
    }

    // Speech-to-text dictation — wire the slot mic button
    if (window.GatorSpeech && sendSlotEl) {
      const micBtn = sendSlotEl.querySelector('.tp-qt-mic-btn');
      if (micBtn) {
        window.GatorSpeech.wire(micBtn, window.GatorSpeech.makeQuillInserter(() => wrap._quill), { title: 'Dictate (Ctrl+Shift+Space)', target: quill.root });
      }
    }

    // Draft auto-save
    if (draftKey) {
      quill.on('text-change', _debounce(() => {
        try { localStorage.setItem(draftKey, quill.root.innerHTML); } catch {}
      }, 800));
    }

    wrap._quill = quill;
    _initQuillImageResize(quill.root);
  }, 0);

  return {
    wrapEl: wrap,
    get quill() { return wrap._quill; },
    getHtml: () => wrap._quill ? wrap._quill.root.innerHTML : '',
    isEmpty: () => !wrap._quill || wrap._quill.getText().trim().length === 0,
    clearDraft: () => { try { if (draftKey) localStorage.removeItem(draftKey); } catch {} },
  };
}

/* ── Emoji picker (full floating picker) ─────────────────── */
function _initEmojiPicker(toolbar, quill) {
  const btn = toolbar.querySelector('.tp-qt-emoji-btn');
  // Remove the old inline popup — the shared full picker replaces it
  const oldPopup = toolbar.querySelector('.tp-emoji-picker-popup');
  if (oldPopup) oldPopup.remove();

  btn.addEventListener('mousedown', e => {
    e.preventDefault();
    e.stopPropagation();
    _openFullEmojiPicker(btn, em => {
      const range = quill.getSelection(true);
      quill.insertText(range.index, em);
      quill.setSelection(range.index + em.length);
    });
  });
}

/* ── Emoji shortcode trigger (:fire: → 🔥) ──────────────── */
// Canonical, hand-picked shortcodes that should win over auto-derived names.
const EMOJI_SHORTCODES = {
  smile: '😊', joy: '😂', fire: '🔥', thumbsup: '👍', '+1': '👍',
  thumbsdown: '👎', '-1': '👎', heart: '❤️', tada: '🎉', thinking: '🤔',
  sunglasses: '😎', cool: '😎', rocket: '🚀', check: '✅',
  white_check_mark: '✅', clap: '👏', pray: '🙏', star: '⭐', bulb: '💡',
  wave: '👋', muscle: '💪', handshake: '🤝', party: '🥳', '100': '💯',
  eyes: '👀', cry: '😭', laughing: '😂', wink: '😉', ok_hand: '👌',
  raised_hands: '🙌', fingers_crossed: '🤞', facepalm: '🤦', shrug: '🤷',
  smiley: '😃', grin: '😁', sweat_smile: '😅', rofl: '🤣', heart_eyes: '😍',
  blush: '😊', kissing_heart: '😘', thinking_face: '🤔', neutral_face: '😐',
  smirk: '😏', unamused: '😒', rolling_eyes: '🙄', flushed: '😳',
  pleading: '🥺', sob: '😭', angry: '😡', rage: '😡', skull: '💀',
  poop: '💩', clown: '🤡', ghost: '👻', alien: '👽', robot: '🤖',
  fire_emoji: '🔥', sparkles: '✨', boom: '💥', tada_party: '🎉',
  gift: '🎁', cake: '🎂', trophy: '🏆', first_place: '🥇', x: '❌',
  warning: '⚠️', bulb_idea: '💡', pencil: '📝', pushpin: '📌',
  rocket_launch: '🚀', coffee: '☕', pizza: '🍕', beer: '🍺',
};

// Lazily-built, comprehensive search index derived from the full emoji dataset.
let _emojiShortcodeIndex = null;

function _buildEmojiShortcodeIndex() {
  const byEmoji = new Map(); // emoji -> { code, terms:Set }

  const add = (emoji, code, terms) => {
    let entry = byEmoji.get(emoji);
    if (!entry) { entry = { emoji, code, terms: new Set() }; byEmoji.set(emoji, entry); }
    if (code && (!entry.code || entry.codeAuto)) entry.code = code;
    (terms || []).forEach(t => t && entry.terms.add(t));
    if (code) entry.terms.add(code);
  };

  for (const [code, emoji] of Object.entries(EMOJI_SHORTCODES)) add(emoji, code, [code]);

  for (const [emoji, meta] of (_emojiKW || new Map())) {
    // meta = { name, kw:[] } — flatten to a term list (name words + keyword words)
    const terms = [
      ...(meta.name || '').split(/\s+/),
      ...(meta.kw || []).flatMap(k => k.split(/\s+/)),
    ].filter(Boolean);
    if (!terms.length) continue;
    let entry = byEmoji.get(emoji);
    if (!entry) { entry = { emoji, code: terms[0], codeAuto: true, terms: new Set() }; byEmoji.set(emoji, entry); }
    terms.forEach(t => entry.terms.add(t));
    if (entry.codeAuto && !entry.code) entry.code = terms[0];
  }

  return [...byEmoji.values()].map(e => ({ emoji: e.emoji, code: e.code, terms: [...e.terms] }));
}

function _searchEmojiShortcodes(query, limit = 8) {
  query = (query || '').toLowerCase();
  if (!query) return [];
  if (!_emojiShortcodeIndex) _emojiShortcodeIndex = _buildEmojiShortcodeIndex();
  const out = [];
  for (const e of _emojiShortcodeIndex) {
    let score = -1;
    if (e.code === query) score = 0;
    else if (e.code && e.code.startsWith(query)) score = 1;
    else if (e.terms.some(t => t.startsWith(query))) score = 2;
    else if (e.terms.some(t => t.includes(query))) score = 3;
    if (score < 0) continue;
    out.push({ emoji: e.emoji, code: e.code, score });
  }
  out.sort((a, b) => a.score - b.score || a.code.length - b.code.length || a.code.localeCompare(b.code));
  return out.slice(0, limit);
}

// Matches a shortcode being typed at the cursor: ":fire", ":+1", ":sweat_smile".
const _EMOJI_SHORTCODE_RE = /(?:^|\s):([a-z+][a-z0-9_+]{1,})$/;

function _initEmojiShortcode(quill) {
  let suggEl = null;
  let hits = [];
  let activeIdx = 0;
  let anchorCleanup = null;

  function _open() { return !!(suggEl && !suggEl.classList.contains('hidden') && hits.length); }

  function _hide() {
    hits = [];
    if (anchorCleanup) { try { anchorCleanup(); } catch {} anchorCleanup = null; }
    if (suggEl) suggEl.classList.add('hidden');
  }

  function _accept(emoji) {
    const curSel = quill.getSelection();
    if (!curSel) { _hide(); return; }
    const curBefore = quill.getText().slice(0, curSel.index);
    const m = curBefore.match(_EMOJI_SHORTCODE_RE);
    if (!m) { _hide(); return; }
    const token = ':' + m[1];
    const start = curSel.index - token.length;
    quill.deleteText(start, token.length);
    quill.insertText(start, emoji);
    quill.setSelection(start + emoji.length);
    try { _addRecentEmoji(emoji); } catch {}
    _hide();
  }

  function _render() {
    if (!suggEl) {
      suggEl = document.createElement('div');
      suggEl.className = 'tp-emoji-shortcode-popup hidden';
    }
    suggEl.innerHTML = '';
    hits.forEach((hit, i) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'tp-emoji-shortcode-item' + (i === activeIdx ? ' active' : '');
      item.innerHTML = `<span class="tp-sc-emoji">${hit.emoji}</span> <span class="tp-sc-code">:${hit.code}:</span>`;
      item.addEventListener('mousedown', e => { e.preventDefault(); _accept(hit.emoji); });
      item.addEventListener('mouseenter', () => { activeIdx = i; _updateActive(); });
      suggEl.appendChild(item);
    });
    suggEl.classList.remove('hidden');
    if (!anchorCleanup) {
      anchorCleanup = _tpAnchorDropdown(suggEl, quill.root, { width: 260, offsetGap: 6 });
    }
  }

  function _updateActive() {
    if (!suggEl) return;
    [...suggEl.children].forEach((el, i) => el.classList.toggle('active', i === activeIdx));
    const el = suggEl.children[activeIdx];
    if (el) _tpEnsureDropdownFocusVisible(suggEl, el);
  }

  quill.on('text-change', () => {
    const sel = quill.getSelection();
    if (!sel) { _hide(); return; }
    const before = quill.getText().slice(0, sel.index);
    const match = before.match(_EMOJI_SHORTCODE_RE);
    if (!match) { _hide(); return; }
    hits = _searchEmojiShortcodes(match[1]);
    if (!hits.length) { _hide(); return; }
    activeIdx = 0;
    _render();
  });

  quill.on('selection-change', range => { if (!range) _hide(); });

  document.addEventListener('keydown', e => {
    if (!_open() || !quill.hasFocus()) return;
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault(); e.stopPropagation();
        activeIdx = (activeIdx + 1) % hits.length; _updateActive();
        break;
      case 'ArrowUp':
        e.preventDefault(); e.stopPropagation();
        activeIdx = (activeIdx - 1 + hits.length) % hits.length; _updateActive();
        break;
      case 'Enter':
      case 'Tab':
        e.preventDefault(); e.stopPropagation();
        _accept(hits[activeIdx].emoji);
        break;
      case 'Escape':
        e.preventDefault(); e.stopPropagation();
        _hide();
        break;
    }
  }, true);
}

/* ── Shared debounce ─────────────────────────────────────── */
function _debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/* ── @mention / #channel dropdown for compose inputs ─────── */

// _tpAnchorDropdown — thin wrapper around _fpopup (from app.js global scope).
// Maintains the same public API so all callers in third-pane.js work unchanged.
function _tpAnchorDropdown(dd, containerEl, { width = 300, offsetLeft = 0, offsetGap = 8 } = {}) {
  dd.style.width = Math.min(width, containerEl.getBoundingClientRect().width || width) + 'px';
  document.body.appendChild(dd);
  return _fpopup(dd, containerEl, {
    placement: 'bottom-start',
    offsetY:   offsetGap,
    padding:   8,
  });
}

function _tpEnsureDropdownFocusVisible(dd, item) {
  if (!dd || !item) return;
  const itemTop = item.offsetTop;
  const itemBottom = itemTop + item.offsetHeight;
  const viewTop = dd.scrollTop;
  const viewBottom = viewTop + dd.clientHeight;
  if (itemTop < viewTop) {
    dd.scrollTop = itemTop;
  } else if (itemBottom > viewBottom) {
    dd.scrollTop = itemBottom - dd.clientHeight;
  }
}

function _tpBuildDropdown(containerEl, opts) {
  const dd = document.createElement('div');
  dd.className = 'skill-mention-dropdown';
  const cleanup = _tpAnchorDropdown(dd, containerEl, opts || {});
  dd._cleanup = cleanup;
  return dd;
}

function _tpAddSectionLabel(dd, text) {
  const lbl = document.createElement('div');
  lbl.className = 'skill-mention-section';
  lbl.textContent = text;
  dd.appendChild(lbl);
}

function _tpAddPersonItem(dd, person, onCommit) {
  if (!person.name && !person.email) return;
  const item = document.createElement('div');
  item.className = 'skill-mention-item skill-mention-person';
  item.dataset.type = 'person';
  item.dataset.email = person.email || '';
  item.dataset.name = person.name || '';
  const displayName = person.name || person.email || '?';
  const initial = displayName.replace(/^\*+/, '').trim()[0]?.toUpperCase() || '?';
  const subtitle = person.job_title || person.department || person.email || '';
  item.innerHTML = `<span class="skill-mention-avatar">${initial}</span>
    <span class="skill-mention-person-info">
      <span class="skill-mention-name">${escapeHtml(displayName)}</span>
      <span class="skill-mention-sub">${escapeHtml(subtitle)}</span>
    </span>`;
  item.addEventListener('mousedown', e => { e.preventDefault(); onCommit(person); });
  dd.appendChild(item);
}

function _tpRenderChannels(dd, channels, onCommit) {
  const byTeam = {};
  channels.forEach(ch => {
    const grp = ch.team_name || 'Group Chat';
    (byTeam[grp] = byTeam[grp] || []).push(ch);
  });
  Object.entries(byTeam).forEach(([teamName, chs]) => {
    _tpAddSectionLabel(dd, teamName.toUpperCase());
    chs.forEach(ch => {
      const item = document.createElement('div');
      item.className = 'skill-mention-item';
      const isGC = ch.type === 'groupchat';
      item.innerHTML = `<span class="skill-mention-icon" style="font-size:.9rem">${isGC ? '💬' : '#'}</span>
        <span class="skill-mention-name">${escapeHtml(ch.channel_name)}</span>
        <span class="skill-mention-badge">${escapeHtml(isGC ? 'Group Chat' : ch.team_name)}</span>`;
      item.addEventListener('mousedown', e => { e.preventDefault(); onCommit(ch); });
      dd.appendChild(item);
    });
  });
}

/**
 * Wire @mention (people search) and #channel dropdown to a plain <textarea>.
 * containerEl must have position:relative for dropdown positioning.
 */
function _wireMentionDropdown(textarea, containerEl) {
  let _dropdown = null;
  let _focusIdx = -1;
  let _searchCtrl = null;
  let _debounceTimer = null;

  function _close() {
    if (_searchCtrl) { _searchCtrl.abort(); _searchCtrl = null; }
    clearTimeout(_debounceTimer);
    if (_dropdown) {
      if (typeof _dropdown._cleanup === 'function') { _dropdown._cleanup(); }
      _dropdown.remove();
      _dropdown = null;
      _focusIdx = -1;
    }
  }

  function _commitPerson(person) {
    const val = textarea.value;
    const cursor = textarea.selectionStart;
    const before = val.slice(0, cursor);
    const atIdx = before.lastIndexOf('@');
    if (atIdx === -1) { _close(); return; }
    const displayName = (person.name || person.email || '').replace(/\s+/g, '');
    const after = val.slice(cursor);
    textarea.value = val.slice(0, atIdx) + '@' + displayName + ' ' + after;
    const newPos = atIdx + 1 + displayName.length + 1;
    textarea.selectionStart = textarea.selectionEnd = newPos;
    // Store mention metadata so send handler can build the Graph mentions array
    if (!textarea._mentionMap) textarea._mentionMap = new Map();
    textarea._mentionMap.set(displayName, { id: person.id || '', name: person.name || displayName, email: person.email || '' });
    textarea.dispatchEvent(new Event('input'));
    _close();
    textarea.focus();
  }

  function _commitChannel(ch) {
    const val = textarea.value;
    const cursor = textarea.selectionStart;
    const before = val.slice(0, cursor);
    const hashIdx = before.lastIndexOf('#');
    if (hashIdx === -1) { _close(); return; }
    const after = val.slice(cursor);
    textarea.value = val.slice(0, hashIdx) + '#' + ch.channel_name + ' ' + after;
    const newPos = hashIdx + 1 + ch.channel_name.length + 1;
    textarea.selectionStart = textarea.selectionEnd = newPos;
    textarea.dispatchEvent(new Event('input'));
    _close();
    textarea.focus();
  }

  function _openPeopleDropdown(query) {
    _close();
    _dropdown = _tpBuildDropdown(containerEl, { width: 300, offsetLeft: 0, offsetGap: 8 });
    if (query.length < 2) {
      _dropdown.innerHTML = '<div class="skill-mention-loading">Type 2+ chars to search\u2026</div>';
      return;
    }
    _dropdown.innerHTML = '<div class="skill-mention-loading">Searching people\u2026</div>';
    _searchCtrl = new AbortController();
    _debounceTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/people/search?q=${encodeURIComponent(query)}`, { signal: _searchCtrl.signal });
        const data = await res.json().catch(() => ({}));
        if (!_dropdown) return;
        _dropdown.innerHTML = '';
        if (res.status === 401) {
          _dropdown.innerHTML = '<div class="skill-mention-loading">Sign in via Settings to search people</div>';
          return;
        }
        if (data.people?.length) {
          _tpAddSectionLabel(_dropdown, 'PEOPLE');
          data.people.forEach(p => _tpAddPersonItem(_dropdown, p, _commitPerson));
        } else {
          _dropdown.innerHTML = '<div class="skill-mention-loading">No results</div>';
        }
        _focusIdx = -1;
      } catch (err) {
        if (err.name !== 'AbortError' && _dropdown) {
          _dropdown.innerHTML = '<div class="skill-mention-loading">Search failed</div>';
        }
      }
    }, 300);
  }

  function _openChannelDropdown(query) {
    _close();
    _dropdown = _tpBuildDropdown(containerEl, { width: 320, offsetLeft: 0, offsetGap: 8 });

    // Try cached chats first
    const cached = window._teamsChatsCache?.length ? window._teamsChatsCache
      : (typeof tpState !== 'undefined' && tpState.type === 'teams' && tpState.list?.length ? tpState.list : null);
    if (cached) {
      const mapped = cached.map(c => ({
        type: 'groupchat',
        chat_id: c.id,
        channel_name: c.topic || c.display_name || (c.chat_type === 'meeting' ? 'Meeting' : c.id),
        team_name: c.chat_type === 'oneOnOne' ? 'Direct Message' : c.chat_type === 'meeting' ? 'Meetings' : 'Group Chat',
      }));
      const ql = query.toLowerCase();
      const filtered = ql ? mapped.filter(ch => ch.channel_name.toLowerCase().includes(ql)) : mapped;
      if (filtered.length) {
        _tpRenderChannels(_dropdown, filtered, _commitChannel);
      } else {
        _dropdown.innerHTML = `<div class="skill-mention-loading">No chats found${query ? ' for "' + escapeHtml(query) + '"' : ''}</div>`;
      }
      return;
    }

    // Fallback: fetch from API
    _dropdown.innerHTML = '<div class="skill-mention-loading">Loading channels\u2026</div>';
    _searchCtrl = new AbortController();
    (async () => {
      try {
        const res = await fetch(`/api/channels/search?q=${encodeURIComponent(query)}`, { signal: _searchCtrl.signal });
        const data = await res.json();
        if (!_dropdown) return;
        _dropdown.innerHTML = '';
        const channels = (data.channels || []).filter(c => c.type !== '_error');
        if (channels.length) {
          _tpRenderChannels(_dropdown, channels, _commitChannel);
        } else {
          _dropdown.innerHTML = `<div class="skill-mention-loading">No channels found</div>`;
        }
      } catch (err) {
        if (err.name !== 'AbortError' && _dropdown) {
          _dropdown.innerHTML = '<div class="skill-mention-loading">Could not load channels</div>';
        }
      }
    })();
  }

  // Input handler — detect @ and # triggers
  textarea.addEventListener('input', () => {
    const val = textarea.value;
    const cursor = textarea.selectionStart;
    const before = val.slice(0, cursor);

    // # trigger
    const hashIdx = before.lastIndexOf('#');
    const atIdx = before.lastIndexOf('@');
    if (hashIdx !== -1 && hashIdx > atIdx && (hashIdx === 0 || before[hashIdx - 1] === ' ' || before[hashIdx - 1] === '\n')) {
      const query = before.slice(hashIdx + 1).match(/^[\w-]*/)?.[0] || '';
      _openChannelDropdown(query);
      return;
    }

    // @ trigger
    if (atIdx !== -1 && (atIdx === 0 || before[atIdx - 1] === ' ' || before[atIdx - 1] === '\n')) {
      const query = before.slice(atIdx + 1);
      if (/^[\w\s]*$/.test(query)) {
        _openPeopleDropdown(query);
        return;
      }
    }

    _close();
  });

  // Keydown handler (capture phase) — intercept Enter/Tab when dropdown is open
  textarea.addEventListener('keydown', e => {
    if (!_dropdown) return;
    const items = _dropdown.querySelectorAll('.skill-mention-item');
    if (!items.length) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault(); e.stopImmediatePropagation();
      _focusIdx = Math.min(_focusIdx + 1, items.length - 1);
      items.forEach((el, i) => {
        if (i === _focusIdx) el.classList.add('focused');
        else el.classList.remove('focused');
      });
      const focused = items[_focusIdx];
      if (focused) _tpEnsureDropdownFocusVisible(_dropdown, focused);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault(); e.stopImmediatePropagation();
      _focusIdx = Math.max(_focusIdx - 1, 0);
      items.forEach((el, i) => {
        if (i === _focusIdx) el.classList.add('focused');
        else el.classList.remove('focused');
      });
      const focused = items[_focusIdx];
      if (focused) _tpEnsureDropdownFocusVisible(_dropdown, focused);
    } else if ((e.key === 'Enter' || e.key === 'Tab') && _focusIdx >= 0) {
      e.preventDefault(); e.stopImmediatePropagation();
      items[_focusIdx]?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    } else if (e.key === 'Escape') {
      e.preventDefault(); e.stopImmediatePropagation();
      _close();
    }
  }, true); // capture phase — runs before the Enter-to-send handler

  // Close on blur (delayed to allow mousedown on items)
  textarea.addEventListener('blur', () => setTimeout(_close, 150));
}

/**
 * Wire Slack-specific @mention dropdown to a Quill editor.
 * Searches /api/slack/users/{query} instead of M365 people search.
 * Inserts <@USERID|display_name> format on selection.
 */
/**
 * Wire Slack-specific @mention dropdown to a Quill editor.
 * Uses the same _tpBuildDropdown / _caretAnchorAt / _findTrigger infrastructure as Teams,
 * with Slack user search (/api/slack/users) as the data source.
 * Inserts plain text <@USERID> on selection (Slack mrkdwn mention format).
 */
function _wireMentionDropdownSlack(quill, containerEl) {
  // Abort any previous instance's listeners before creating a new one
  if (_slackCurrentMentionAbortCtrl) _slackCurrentMentionAbortCtrl.abort();
  const _mentionAbortCtrl = new AbortController();
  _slackCurrentMentionAbortCtrl = _mentionAbortCtrl;

  let _dropdown = null;
  let _focusIdx = -1;
  let _searchCtrl = null;
  let _debounceTimer = null;
  let _lastTriggerInfo = null;  // saved {docPos, query} so _commitUser works when quill loses focus

  // Local trigger finder — mirrors _wireMentionDropdownQuill's _findTrigger but only for @
  // (that function is a closure inside _wireMentionDropdownQuill, not a global)
  function _findAtTrigger(cursorIdx) {
    const delta = quill.getContents(0, cursorIdx);
    let docPos = 0, triggerPos = -1, prevIsSpace = true, qChars = [];
    for (const op of delta.ops) {
      if (typeof op.insert === 'string') {
        for (let i = 0; i < op.insert.length; i++) {
          const ch = op.insert[i];
          if (ch === '@' && prevIsSpace) { triggerPos = docPos; qChars = []; }
          else if (triggerPos !== -1) { qChars.push(ch); }
          prevIsSpace = (ch === ' ' || ch === '\n');
          docPos++;
        }
      } else {
        prevIsSpace = true;
        if (triggerPos !== -1) { triggerPos = -1; qChars = []; }
        docPos++;
      }
    }
    if (triggerPos === -1) return null;
    return { docPos: triggerPos, query: qChars.join('') };
  }

  function _close() {
    if (_searchCtrl) { _searchCtrl.abort(); _searchCtrl = null; }
    clearTimeout(_debounceTimer);
    if (_dropdown) {
      if (typeof _dropdown._cleanup === 'function') _dropdown._cleanup();
      _dropdown.remove();
      _dropdown = null;
      _focusIdx = -1;
    }
  }

  function _caretAnchor(docPos) {
    return {
      getBoundingClientRect() {
        const rootRect = quill.root.getBoundingClientRect();
        let b = null;
        try { b = quill.getBounds(docPos); } catch (e) { /* ignore */ }
        if (!b) return rootRect;
        const left = rootRect.left + b.left;
        const top = rootRect.top + b.top;
        return { x: left, y: top, left, top, width: b.width || 0, height: b.height,
          right: left + (b.width || 0), bottom: top + b.height };
      },
    };
  }

  function _commitUser(user) {
    // Use saved trigger info — getSelection() returns null when quill loses focus
    // (which happens on mousedown on the dropdown item)
    const sel = quill.getSelection() || (quill.hasFocus() ? null : { index: (_lastTriggerInfo ? _lastTriggerInfo.docPos + _lastTriggerInfo.query.length + 1 : 0) });
    const info = sel ? _findAtTrigger(sel.index) : _lastTriggerInfo;
    if (!info) { _close(); return; }
    const atIdx = info.docPos;
    // Calculate deleteLen: from @ to end of typed query
    const curIdx = sel ? sel.index : atIdx + 1 + info.query.length;
    const deleteLen = curIdx - atIdx;
    const uid = user.user_id || user.id;
    const displayName = user.name || user.display_name || user.real_name || uid;
    quill.focus();
    quill.deleteText(atIdx, deleteLen);
    // Insert as mention embed (chip style, atomic, Ctrl+C friendly)
    quill.insertEmbed(atIdx, 'mention', { id: uid, name: displayName, email: user.email || '' });
    quill.insertText(atIdx + 1, ' ');
    quill.setSelection(atIdx + 2, 0);
    _lastTriggerInfo = null;
    _close();
  }

  function _openSlackPeopleDropdown(query, docPos) {
    _lastTriggerInfo = { docPos, query };
    _close();
    const anchor = _caretAnchor(docPos);
    _dropdown = _tpBuildDropdown(anchor, { width: 280, offsetLeft: 0, offsetGap: 6 });
    _dropdown.innerHTML = '<div class="skill-mention-loading">Searching Slack…</div>';
    _searchCtrl = new AbortController();
    _debounceTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/slack/users/${encodeURIComponent(query)}`,
          { signal: _searchCtrl.signal });
        if (!res.ok) throw new Error();
        const data = await res.json();
        if (!_dropdown) return;
        _dropdown.innerHTML = '';
        const users = data.user ? [data.user] : (data.users || []);
        if (users.length) {
          _tpAddSectionLabel(_dropdown, 'SLACK PEOPLE');
          users.forEach(u => {
            const person = {
              id: u.user_id || u.id,
              user_id: u.user_id || u.id,
              name: u.real_name || u.display_name || u.username || u.user_id,
              email: u.email || '',
              job_title: u.title || '',
            };
            _tpAddPersonItem(_dropdown, person, _commitUser);
          });
        } else {
          _dropdown.innerHTML = '<div class="skill-mention-loading">No results</div>';
        }
        _focusIdx = -1;
      } catch (err) {
        if (err.name !== 'AbortError' && _dropdown) {
          _dropdown.innerHTML = '<div class="skill-mention-loading">Search failed</div>';
        }
      }
    }, 300);
  }

  // Keyboard navigation — same pattern as _wireMentionDropdownQuill
  quill.root.addEventListener('keydown', e => {
    if (!_dropdown) return;
    const items = _dropdown.querySelectorAll('.skill-mention-item');
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _focusIdx = Math.min(_focusIdx + 1, items.length - 1);
      items.forEach((it, i) => it.classList.toggle('focused', i === _focusIdx));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _focusIdx = Math.max(_focusIdx - 1, 0);
      items.forEach((it, i) => it.classList.toggle('focused', i === _focusIdx));
    } else if ((e.key === 'Enter' || e.key === 'Tab') && _focusIdx >= 0) {
      e.preventDefault();
      items[_focusIdx]?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    } else if (e.key === 'Escape') {
      _close();
    }
  });

  // Detect @ trigger on text change — uses delta-aware _findTrigger (same as Teams)
  quill.on('text-change', () => {
    const sel = quill.getSelection();
    if (!sel) { _close(); return; }
    const info = _findAtTrigger(sel.index);
    if (!info) { _close(); return; }
    const { query, docPos } = info;
    if (query.length === 0) {
      // Show loading state immediately on @ so user knows to keep typing
      if (!_dropdown) {
        _close();
        const anchor = _caretAnchor(docPos);
        _dropdown = _tpBuildDropdown(anchor, { width: 280, offsetLeft: 0, offsetGap: 6 });
        _dropdown.innerHTML = '<div class="skill-mention-loading">Type a name…</div>';
      }
      return;
    }
    if (query.length >= 2) {
      _openSlackPeopleDropdown(query, docPos);
    }
  });

  // Close when Quill root is removed (via AbortController cleanup)
  new MutationObserver((_, obs) => {
    if (!document.contains(quill.root)) {
      _mentionAbortCtrl.abort();
      _close();
      obs.disconnect();
    }
  }).observe(document.body, { childList: true, subtree: true });
}

/**
 * Wire @mention and #channel dropdown to a Quill rich-text editor.
 * Same UX as _wireMentionDropdown but using Quill API.
 */
function _wireMentionDropdownQuill(quill, containerEl) {
  let _dropdown = null;
  let _focusIdx = -1;
  let _searchCtrl = null;
  let _debounceTimer = null;
  let _committing = false;

  /**
   * Find the last occurrence of triggerChar in Quill document coordinates.
   * getText() skips embeds so its indices don't match Quill positions.
   * We iterate getContents() delta to get accurate doc positions.
   * Returns { docPos, query } or null.
   */
  function _findTrigger(triggerChar, cursorIdx) {
    const delta = quill.getContents(0, cursorIdx);
    let docPos = 0, triggerPos = -1, prevIsSpace = true, qChars = [];
    for (const op of delta.ops) {
      if (typeof op.insert === 'string') {
        for (let i = 0; i < op.insert.length; i++) {
          const ch = op.insert[i];
          if (ch === triggerChar && prevIsSpace) {
            triggerPos = docPos;
            qChars = [];
          } else if (triggerPos !== -1) {
            qChars.push(ch);
          }
          prevIsSpace = (ch === ' ' || ch === '\n');
          docPos++;
        }
      } else {
        // Embed blot — treat as word boundary
        prevIsSpace = true;
        if (triggerPos !== -1) {
          // Embed inside query invalidates it
          triggerPos = -1;
          qChars = [];
        }
        docPos++;
      }
    }
    if (triggerPos === -1) return null;
    return { docPos: triggerPos, query: qChars.join('') };
  }

  function _close() {
    if (_searchCtrl) { _searchCtrl.abort(); _searchCtrl = null; }
    clearTimeout(_debounceTimer);
    if (_dropdown) {
      if (typeof _dropdown._cleanup === 'function') { _dropdown._cleanup(); }
      _dropdown.remove();
      _dropdown = null;
      _focusIdx = -1;
    }
  }

  // Virtual anchor pinned to the trigger glyph's caret coordinates so the
  // dropdown opens inline at the cursor rather than at the editor's bottom edge.
  // Quill.getBounds() is editor-relative; offset by quill.root's viewport rect.
  // Falls back to the editor div if bounds are unavailable. (#120)
  function _caretAnchorAt(docPos) {
    return {
      getBoundingClientRect() {
        const rootRect = quill.root.getBoundingClientRect();
        let b = null;
        try { b = quill.getBounds(docPos); } catch (e) { /* ignore */ }
        if (!b) return rootRect;
        const left = rootRect.left + b.left;
        const top = rootRect.top + b.top;
        const width = b.width || 0;
        return {
          x: left, y: top, left, top, width, height: b.height,
          right: left + width, bottom: top + b.height,
        };
      },
    };
  }

  // Anchor at the trigger char (@/#) for the current selection, or null.
  function _triggerAnchor(triggerChar) {
    const sel = quill.getSelection();
    if (!sel) return null;
    const info = _findTrigger(triggerChar, sel.index);
    return info ? _caretAnchorAt(info.docPos) : null;
  }

  function _commitPerson(person) {
    const sel = quill.getSelection();
    if (!sel) { _close(); return; }
    const info = _findTrigger('@', sel.index);
    if (!info) { _close(); return; }
    const atIdx = info.docPos;
    const deleteLen = sel.index - atIdx;
    const displayName = (person.name || person.email || '');
    _committing = true;
    quill.deleteText(atIdx, deleteLen);
    quill.insertEmbed(atIdx, 'mention', {
      id: person.id || '',
      name: displayName,
      email: person.email || '',
    });
    quill.insertText(atIdx + 1, ' ', { bold: false, color: false, background: false });
    quill.setSelection(atIdx + 2);
    _committing = false;
    _close();
  }

  function _commitChannel(ch) {
    const sel = quill.getSelection();
    if (!sel) { _close(); return; }
    const info = _findTrigger('#', sel.index);
    if (!info) { _close(); return; }
    const hashIdx = info.docPos;
    const deleteLen = sel.index - hashIdx;
    _committing = true;
    quill.deleteText(hashIdx, deleteLen);
    quill.insertText(hashIdx, '#' + ch.channel_name + ' ');
    quill.setSelection(hashIdx + 1 + ch.channel_name.length + 1);
    _committing = false;
    _close();
  }

  function _openPeopleDropdown(query) {
    _close();
    const anchor = _triggerAnchor('@') || containerEl;
    _dropdown = _tpBuildDropdown(anchor, { width: 300, offsetLeft: 0, offsetGap: 8 });
    if (query.length < 2) {
      _dropdown.innerHTML = '<div class="skill-mention-loading">Type 2+ chars to search\u2026</div>';
      return;
    }
    _dropdown.innerHTML = '<div class="skill-mention-loading">Searching people\u2026</div>';
    _searchCtrl = new AbortController();
    _debounceTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/people/search?q=${encodeURIComponent(query)}`, { signal: _searchCtrl.signal });
        const data = await res.json().catch(() => ({}));
        if (!_dropdown) return;
        _dropdown.innerHTML = '';
        if (res.status === 401) {
          _dropdown.innerHTML = '<div class="skill-mention-loading">Sign in via Settings to search people</div>';
          return;
        }
        if (data.people?.length) {
          _tpAddSectionLabel(_dropdown, 'PEOPLE');
          data.people.forEach(p => _tpAddPersonItem(_dropdown, p, _commitPerson));
        } else {
          _dropdown.innerHTML = '<div class="skill-mention-loading">No results</div>';
        }
        _focusIdx = -1;
      } catch (err) {
        if (err.name !== 'AbortError' && _dropdown) {
          _dropdown.innerHTML = '<div class="skill-mention-loading">Search failed</div>';
        }
      }
    }, 300);
  }

  function _openChannelDropdown(query) {
    _close();
    const anchor = _triggerAnchor('#') || containerEl;
    _dropdown = _tpBuildDropdown(anchor, { width: 320, offsetLeft: 0, offsetGap: 8 });
    const cached = window._teamsChatsCache?.length ? window._teamsChatsCache
      : (typeof tpState !== 'undefined' && tpState.type === 'teams' && tpState.list?.length ? tpState.list : null);
    if (cached) {
      const mapped = cached.map(c => ({
        type: 'groupchat', chat_id: c.id,
        channel_name: c.topic || c.display_name || (c.chat_type === 'meeting' ? 'Meeting' : c.id),
        team_name: c.chat_type === 'oneOnOne' ? 'Direct Message' : c.chat_type === 'meeting' ? 'Meetings' : 'Group Chat',
      }));
      const ql = query.toLowerCase();
      const filtered = ql ? mapped.filter(ch => ch.channel_name.toLowerCase().includes(ql)) : mapped;
      if (filtered.length) { _tpRenderChannels(_dropdown, filtered, _commitChannel); }
      else { _dropdown.innerHTML = `<div class="skill-mention-loading">No chats found</div>`; }
      return;
    }
    _dropdown.innerHTML = '<div class="skill-mention-loading">Loading channels\u2026</div>';
    _searchCtrl = new AbortController();
    (async () => {
      try {
        const res = await fetch(`/api/channels/search?q=${encodeURIComponent(query)}`, { signal: _searchCtrl.signal });
        const data = await res.json();
        if (!_dropdown) return;
        _dropdown.innerHTML = '';
        const channels = (data.channels || []).filter(c => c.type !== '_error');
        if (channels.length) { _tpRenderChannels(_dropdown, channels, _commitChannel); }
        else { _dropdown.innerHTML = '<div class="skill-mention-loading">No channels found</div>'; }
      } catch (err) {
        if (err.name !== 'AbortError' && _dropdown) {
          _dropdown.innerHTML = '<div class="skill-mention-loading">Could not load channels</div>';
        }
      }
    })();
  }

  // Detect @/# triggers on text change (uses delta-aware _findTrigger)
  quill.on('text-change', () => {
    if (_committing) return;
    const sel = quill.getSelection();
    if (!sel) return;

    const hashInfo = _findTrigger('#', sel.index);
    const atInfo = _findTrigger('@', sel.index);

    // Whichever trigger appears later in the document wins
    if (hashInfo && (!atInfo || hashInfo.docPos > atInfo.docPos)) {
      if (/^[\w-]*$/.test(hashInfo.query)) { _openChannelDropdown(hashInfo.query); return; }
    }
    if (atInfo) {
      if (/^[\w\s]*$/.test(atInfo.query)) { _openPeopleDropdown(atInfo.query); return; }
    }
    _close();
  });

  // Keyboard navigation
  quill.root.addEventListener('keydown', e => {
    if (!_dropdown) return;
    const items = _dropdown.querySelectorAll('.skill-mention-item');
    if (!items.length) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault(); e.stopImmediatePropagation();
      _focusIdx = Math.min(_focusIdx + 1, items.length - 1);
      items.forEach((el, i) => {
        if (i === _focusIdx) el.classList.add('focused');
        else el.classList.remove('focused');
      });
      const focused = items[_focusIdx];
      if (focused) _tpEnsureDropdownFocusVisible(_dropdown, focused);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault(); e.stopImmediatePropagation();
      _focusIdx = Math.max(_focusIdx - 1, 0);
      items.forEach((el, i) => {
        if (i === _focusIdx) el.classList.add('focused');
        else el.classList.remove('focused');
      });
      const focused = items[_focusIdx];
      if (focused) _tpEnsureDropdownFocusVisible(_dropdown, focused);
    } else if ((e.key === 'Enter' || e.key === 'Tab') && _focusIdx >= 0) {
      e.preventDefault(); e.stopImmediatePropagation();
      items[_focusIdx]?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    } else if (e.key === 'Escape') {
      e.preventDefault(); e.stopImmediatePropagation();
      _close();
    }
  }, true);

  quill.root.addEventListener('blur', () => setTimeout(_close, 150));
}

/* ── Attachment zone ─────────────────────────────────────── */
const ATTACH_ICONS = {
  'application/pdf': '📄', 'application/msword': '📝',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '📝',
  'application/vnd.ms-excel': '📊',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '📊',
  'application/vnd.ms-powerpoint': '📊',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': '📊',
  'image/png': '🖼️', 'image/jpeg': '🖼️', 'image/gif': '🖼️', 'image/webp': '🖼️',
  'text/plain': '📄', 'text/csv': '📊', 'application/zip': '🗜️',
};
function _attachIcon(type) { return ATTACH_ICONS[type] || '📎'; }
function _formatBytes(n) {
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}
// Graph /me/sendMail hard limit is 4 MB total request body.
// Base64 inflates raw bytes by ~33%, so max safe combined raw size is 3 MB.
const MAX_ATTACH_BYTES_PER_FILE = 3 * 1024 * 1024;   // 3 MB per file
const MAX_ATTACH_BYTES_TOTAL    = 3 * 1024 * 1024;   // 3 MB combined (→ ~4 MB after base64)

/**
 * Build the attachment chip list + hidden file input.
 * Returns { zoneEl, fileInputEl, files, addFiles, clear }
 * `files` is a live array of File objects.
 */
function _buildAttachmentZone() {
  const zone = document.createElement('div');
  zone.className = 'tp-attach-zone hidden';

  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.multiple = true;
  fileInput.className = 'hidden';
  zone.appendChild(fileInput);

  const list = document.createElement('div');
  list.className = 'tp-attach-list';
  zone.appendChild(list);

  const files = [];

  function addFiles(newFiles) {
    Array.from(newFiles).forEach(f => {
      if (f.size > MAX_ATTACH_BYTES_PER_FILE) {
        _showAlert('"' + f.name + '" is ' + _formatBytes(f.size) + ' — over the 3 MB per-file limit. Share via OneDrive instead.', 'error');
        return;
      }
      const currentTotal = files.reduce((sum, x) => sum + x.size, 0);
      if (currentTotal + f.size > MAX_ATTACH_BYTES_TOTAL) {
        _showAlert('Adding "' + f.name + '" would exceed the 3 MB combined limit. Remove an attachment first or share via OneDrive.', 'error');
        return;
      }
      if (files.find(x => x.name === f.name && x.size === f.size)) return; // dedupe
      files.push(f);

      const chip = document.createElement('div');
      chip.className = 'tp-attach-chip';
      chip.innerHTML = `<span class="tp-attach-icon">${_attachIcon(f.type)}</span>
        <span class="tp-attach-name" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</span>
        <span class="tp-attach-size">${_formatBytes(f.size)}</span>
        <button class="chip-remove" title="Remove">✕</button>`;
      chip.querySelector('.chip-remove').addEventListener('click', () => {
        files.splice(files.indexOf(f), 1);
        chip.remove();
        if (!files.length) zone.classList.add('hidden');
      });
      list.appendChild(chip);
      zone.classList.remove('hidden');
    });
  }

  fileInput.addEventListener('change', () => { addFiles(fileInput.files); fileInput.value = ''; });

  return { zoneEl: zone, fileInputEl: fileInput, files, addFiles };
}

/**
 * Wire drag-and-drop onto a container element.
 * Dropped files are passed to the provided addFiles callback.
 */
// Wire image-paste (Ctrl+V / screenshot) on a Quill editor root.
// Must run in capture phase so it fires before Quill's own paste handler,
// which would otherwise embed the image as a data URI in the editor content.
// Wire image-paste on an ANCESTOR of the Quill root (not the root itself).
// Quill registers its own capture-phase paste handler on ql-editor during init.
// Capture fires outer→inner in DOM order, so a listener on an ancestor always
// wins regardless of registration order — intercepting here lets us prevent
// Quill from embedding the image as a data URI in the editor content.
function _wirePasteImages(containerEl, addFiles) {
  containerEl.addEventListener('paste', e => {
    const files = [...(e.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'));
    if (!files.length) return;
    e.preventDefault();
    e.stopPropagation();
    addFiles(files);
  }, true); // capture phase — fires before any listener on descendant nodes
}

function _wireDragDrop(containerEl, addFiles) {
  containerEl.addEventListener('dragover', e => {
    e.preventDefault();
    containerEl.classList.add('tp-drag-over');
  });
  containerEl.addEventListener('dragleave', e => {
    if (!containerEl.contains(e.relatedTarget)) containerEl.classList.remove('tp-drag-over');
  });
  containerEl.addEventListener('drop', e => {
    e.preventDefault();
    containerEl.classList.remove('tp-drag-over');
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  });
}

/**
 * Read a File as a base64 string (no data URI prefix).
 */
function _fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

/* ── New Channel compose ─────────────────────────────────── */

async function _showNewChannelCompose() {
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = '<div class="tp-empty-state"><span>Loading teams…</span></div>';

  // Fetch joined teams for the dropdown
  let teams = [];
  try {
    const res = await fetch('/api/teams/joined-teams');
    if (res.ok) teams = (await res.json()).teams || [];
  } catch {}

  col.innerHTML = '';
  const wrapper = document.createElement('div');
  wrapper.className = 'tp-new-compose';

  const header = document.createElement('div');
  header.className = 'tp-new-compose-header';
  header.textContent = 'Create a channel';
  wrapper.appendChild(header);

  // Scrollable fields area
  const scroll = document.createElement('div');
  scroll.className = 'tp-channel-scroll';

  // Team selector
  const teamRow = document.createElement('div');
  teamRow.className = 'tp-channel-field-row';
  const teamLabel = document.createElement('label');
  teamLabel.className = 'tp-channel-label';
  teamLabel.innerHTML = 'Add the channel to a team<span class="tp-required">*</span>';
  const teamSelect = document.createElement('select');
  teamSelect.className = 'tp-channel-select';
  const placeholder = document.createElement('option');
  placeholder.value = ''; placeholder.textContent = 'Select a team'; placeholder.disabled = true; placeholder.selected = true;
  teamSelect.appendChild(placeholder);
  teams.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t.id; opt.textContent = t.name;
    teamSelect.appendChild(opt);
  });
  teamRow.appendChild(teamLabel);
  teamRow.appendChild(teamSelect);
  scroll.appendChild(teamRow);

  scroll.appendChild(Object.assign(document.createElement('hr'), { className: 'tp-channel-section-divider' }));

  // Channel name
  const nameRow = document.createElement('div');
  nameRow.className = 'tp-channel-field-row';
  const nameLabel = document.createElement('label');
  nameLabel.className = 'tp-channel-label';
  nameLabel.innerHTML = 'Channel name<span class="tp-required">*</span>';
  const nameInput = document.createElement('input');
  nameInput.type = 'text'; nameInput.className = 'tp-channel-input';
  nameInput.placeholder = 'e.g. announcements, general, off-topic';
  const nameHint = document.createElement('div');
  nameHint.className = 'tp-channel-hint';
  nameHint.textContent = 'Letters, numbers, and spaces are allowed';
  nameRow.appendChild(nameLabel);
  nameRow.appendChild(nameInput);
  nameRow.appendChild(nameHint);
  scroll.appendChild(nameRow);

  // Description
  const descRow = document.createElement('div');
  descRow.className = 'tp-channel-field-row';
  const descLabel = document.createElement('label');
  descLabel.className = 'tp-channel-label';
  descLabel.textContent = 'Description';
  const descInput = document.createElement('textarea');
  descInput.className = 'tp-channel-input tp-channel-textarea';
  descInput.placeholder = 'Help others find the right channel by providing a description';
  descInput.rows = 3;
  descRow.appendChild(descLabel);
  descRow.appendChild(descInput);
  scroll.appendChild(descRow);

  scroll.appendChild(Object.assign(document.createElement('hr'), { className: 'tp-channel-section-divider' }));

  // Channel type
  const typeRow = document.createElement('div');
  typeRow.className = 'tp-channel-field-row';
  const typeLabel = document.createElement('label');
  typeLabel.className = 'tp-channel-label';
  typeLabel.innerHTML = 'Channel type<span class="tp-required">*</span>';
  typeRow.appendChild(typeLabel);

  const typeOptions = [
    { value: 'standard', icon: '💬', title: 'Standard', desc: 'Anyone on the team can access this channel.' },
    { value: 'private', icon: '🔒', title: 'Private', desc: 'Only specific people have access.' },
  ];
  let selectedType = 'standard';
  const typeCards = document.createElement('div');
  typeCards.className = 'tp-channel-type-cards';
  typeOptions.forEach(opt => {
    const card = document.createElement('div');
    card.className = 'tp-channel-type-card' + (opt.value === selectedType ? ' selected' : '');
    card.dataset.value = opt.value;
    card.innerHTML = `<span class="tp-channel-type-icon">${opt.icon}</span>
      <div><div class="tp-channel-type-title">${opt.title}</div>
      <div class="tp-channel-type-desc">${opt.desc}</div></div>`;
    card.addEventListener('click', () => {
      selectedType = opt.value;
      typeCards.querySelectorAll('.tp-channel-type-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
    });
    typeCards.appendChild(card);
  });
  typeRow.appendChild(typeCards);
  scroll.appendChild(typeRow);

  scroll.appendChild(Object.assign(document.createElement('hr'), { className: 'tp-channel-section-divider' }));

  // Layout
  const layoutRow = document.createElement('div');
  layoutRow.className = 'tp-channel-field-row';
  const layoutLabelWrap = document.createElement('div');
  layoutLabelWrap.innerHTML = `<div class="tp-channel-label">Layout</div>
    <div class="tp-channel-hint">Channel owners can change this at any time</div>`;
  layoutRow.appendChild(layoutLabelWrap);

  const layoutOptions = [
    { value: 'threads', icon: '🧵', title: 'Threads', desc: 'Looks like chat with replies on the side in threads. Good for back-and-forth discussions.' },
    { value: 'posts',   icon: '📋', title: 'Posts',   desc: 'Posts reorder by most recent reply. Good for forums and announcements.' },
  ];
  let selectedLayout = 'threads';
  const layoutCards = document.createElement('div');
  layoutCards.className = 'tp-channel-type-cards';
  layoutOptions.forEach(opt => {
    const card = document.createElement('div');
    card.className = 'tp-channel-type-card' + (opt.value === selectedLayout ? ' selected' : '');
    card.dataset.value = opt.value;
    card.innerHTML = `<span class="tp-channel-type-icon">${opt.icon}</span>
      <div><div class="tp-channel-type-title">${opt.title}</div>
      <div class="tp-channel-type-desc">${opt.desc}</div></div>`;
    card.addEventListener('click', () => {
      selectedLayout = opt.value;
      layoutCards.querySelectorAll('.tp-channel-type-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
    });
    layoutCards.appendChild(card);
  });
  layoutRow.appendChild(layoutCards);
  scroll.appendChild(layoutRow);
  wrapper.appendChild(scroll);

  // Action bar
  const actionBar = document.createElement('div');
  actionBar.className = 'tp-new-compose-action-bar';
  const statusEl = document.createElement('div');
  statusEl.className = 'tp-send-status';

  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'tp-cancel-btn'; cancelBtn.textContent = 'Cancel';
  cancelBtn.addEventListener('click', () => { col.innerHTML = _gatorDetailHint('teams'); });

  const createBtn = document.createElement('button');
  createBtn.className = 'tp-send-btn'; createBtn.textContent = 'Create';
  createBtn.addEventListener('click', async () => {
    const teamId = teamSelect.value;
    const name = nameInput.value.trim();
    if (!teamId) { statusEl.textContent = 'Please select a team.'; return; }
    if (!name) { statusEl.textContent = 'Channel name is required.'; return; }
    createBtn.disabled = true; createBtn.textContent = 'Creating…';
    statusEl.textContent = '';
    try {
      const res = await fetch('/api/teams/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team_id: teamId, display_name: name, description: descInput.value.trim(), membership_type: selectedType }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        col.innerHTML = `<div class="tp-empty-state"><span>Channel "<strong>${escapeHtml(name)}</strong>" created successfully.</span></div>`;
      } else {
        statusEl.textContent = data.detail || 'Failed to create channel.';
        createBtn.disabled = false; createBtn.textContent = 'Create';
      }
    } catch (e) {
      statusEl.textContent = 'Error: ' + e.message;
      createBtn.disabled = false; createBtn.textContent = 'Create';
    }
  });

  actionBar.appendChild(statusEl);
  actionBar.appendChild(cancelBtn);
  actionBar.appendChild(createBtn);
  wrapper.appendChild(actionBar);
  col.appendChild(wrapper);
  nameInput.focus();
}

/* ── New Teams conversation compose ─────────────────────── */

function _closeNewTeamsCompose() {
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = _gatorDetailHint('teams');
  const addBtn = document.getElementById('tp-add-btn');
  if (addBtn) {
    addBtn.dataset.composing = '';
    addBtn.innerHTML = _TP_PLUS_SVG;
    addBtn.title = 'New conversation';
    addBtn.onclick = () => _showNewTeamsCompose();
  }
  // If a chat was selected, restore its header; else clear back to close-only.
  if (tpState.selectedId) tpLoadDetail(tpState.selectedId);
  else _resetDetailHeader();
}

function _showNewTeamsCompose({ prefillHtml = '', prefillDisplay = '' } = {}) {
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = '';
  // Clear any stale draft so the form always opens fresh
  try { localStorage.removeItem('draft_teams_new'); } catch {}

  // Replace the persistent chat header (avatar/name/call icons) with just
  // "New Conversation" + an X — they don't apply while drafting.
  _setComposeDetailHeader(prefillHtml ? 'Forward Message' : 'New Conversation', _closeNewTeamsCompose);

  // Toggle + icon → X icon
  const addBtn = document.getElementById('tp-add-btn');
  if (addBtn) {
    addBtn.dataset.composing = '1';
    addBtn.innerHTML = _TP_CLOSE_SVG;
    addBtn.title = 'Close compose';
    addBtn.onclick = () => _closeNewTeamsCompose();
  }

  const wrapper = document.createElement('div');
  wrapper.className = 'tp-new-compose';

  // To field
  const toField = _buildRecipientField({
    label: 'To:', chipClass: 'chip-teams', avatarClass: 'tp-avatar-teams',
    normalizeSearch: true, orgOnly: true,
    onchange: updateSendState,
  });
  wrapper.appendChild(toField.rowEl);

  // Rich text editor — no draftKey so nothing persists between sessions
  const editor = _buildQuillEditor({ placeholder: prefillHtml ? 'Add a note… (optional)' : 'Type your message…', showResize: false });
  wrapper.appendChild(editor.wrapEl);

  // Forwarded message preview — non-editable, styled with left accent border.
  // Uses prefillDisplay (clean HTML, no schema URLs) for rendering.
  // prefillHtml (native Skype format) is appended to the message at send time.
  if (prefillHtml) {
    const _forwardPreviewEl = document.createElement('div');
    _forwardPreviewEl.className = 'tp-forward-preview';
    _forwardPreviewEl.innerHTML = sanitizeHtml(prefillDisplay || prefillHtml);
    wrapper.insertBefore(_forwardPreviewEl, editor.wrapEl);
  }

  // Attachment zone
  const attach = _buildAttachmentZone();
  wrapper.appendChild(attach.zoneEl);

  // Wire paperclip button (added after Quill init)
  setTimeout(() => {
    const clipBtn = editor.wrapEl.querySelector('.tp-qt-attach-btn');
    if (clipBtn) clipBtn.addEventListener('click', () => attach.fileInputEl.click());
  }, 50);

  const statusEl = document.createElement('div');
  statusEl.className = 'tp-new-compose-status hidden';
  wrapper.appendChild(statusEl);
  col.appendChild(wrapper);

  // Use toolbar send button (consistent with reply compose)
  const sendBtn = editor.wrapEl.querySelector('.tp-compose-send');

  const hasEditorContent = () => {
    if (prefillHtml) return true; // forward preview counts as content
    if (!editor.isEmpty()) return true;
    const html = editor.getHtml();
    return /<img\b/i.test(html);
  };

  function updateSendState() {
    if (!sendBtn) return;
    const hasContent = hasEditorContent() || attach.files.length > 0;
    sendBtn.disabled = !toField.getEmails() || !hasContent;
  }

  const _originalAddFiles = attach.addFiles;
  attach.addFiles = (files) => {
    _originalAddFiles(files);
    updateSendState();
  };
  attach.zoneEl.addEventListener('click', () => setTimeout(updateSendState, 0));
  const _attachListEl = attach.zoneEl.querySelector('.tp-attach-list');
  if (_attachListEl) {
    const _attachObserver = new MutationObserver(() => updateSendState());
    _attachObserver.observe(_attachListEl, { childList: true });
  }

  // Drag-and-drop onto entire compose wrapper.
  // Paste: let Quill embed images inline as data: URIs — the send handler
  // extracts them into hostedImages before posting to the API.
  _wireDragDrop(wrapper, attach.addFiles);

  function _wireNewComposeQuill() {
    const q = editor.quill;
    if (!q) { setTimeout(_wireNewComposeQuill, 200); return; }
    q.on('text-change', updateSendState);
    // Re-wire slot morph here so it's guaranteed on this Quill instance.
    // The slot's _updateSlot from _buildQuillEditor may have registered on
    // wrap._quill before it was fully initialised in new-email context.
    const _slot = editor.wrapEl.querySelector('.tp-quill-send-slot');
    if (_slot) {
      // When forwarding, the forward preview counts as content — keep send button visible
      // even when the note field is empty.
      const _syncSlot = () => _slot.classList.toggle('has-text', !!prefillHtml || q.getText().trim().length > 0);
      q.on('text-change', _syncSlot);
      _syncSlot(); // set initial state
    }
    _installComposeIndentBindings(q);
    // Use quill root as anchor so dropdown appears above the editor, not the whole wrapper
    _wireMentionDropdownQuill(q, q.root);
  }
  setTimeout(_wireNewComposeQuill, 150);

  let _newComposeInFlight = false;
  sendBtn.addEventListener('click', async () => {
    if (_newComposeInFlight) return; // guard against double-submit (click + Enter, dup listener, etc.)
    const to = toField.getEmails();
    if (!to) return;

    const quillInst = editor.quill;
    const rawHtml = editor.getHtml ? editor.getHtml() : '';
    const plainText = quillInst ? quillInst.getText().trim() : '';
    const hasHtmlImage = /<img\b/i.test(rawHtml);
    if (!hasHtmlImage && !plainText && !prefillHtml && attach.files.length === 0) return;

    _newComposeInFlight = true;
    sendBtn.disabled = true;

    // Convert Quill flat indent paragraphs into Teams' native nested-list structure
    let cleanHtml = rawHtml ? _quillIndentToNestedList(rawHtml) : '';
    cleanHtml = cleanHtml ? cleanHtml.replace(/<p>/g, '<div>').replace(/<\/p>/g, '</div>') : '';
    cleanHtml = _stripTrailingEmptyBlocks(cleanHtml);
    // Append the non-editable forward block to the user's note
    let message = cleanHtml || plainText;
    if (prefillHtml) {
      const sep = message ? '' : '';
      message = (message || '') + sep + prefillHtml;
    }
    let hostedImages = [];
    let mentions = [];

    if (quillInst) {
      const hasMentions = quillInst.getContents().ops.some(op => op.insert && op.insert.mention);
      if (hasMentions) {
        const payload = _buildMentionPayload(quillInst);
        if (payload.html) {
          const mentionHtml = payload.html.replace(/<p>/g, '<div>').replace(/<\/p>/g, '</div>');
          cleanHtml = mentionHtml;
          // Re-append forward block after mention html (was dropped before)
          message = mentionHtml + (prefillHtml || '');
        }
        if (payload.mentions?.length) {
          mentions = payload.mentions;
        }
      }
    }

    if (typeof message === 'string' && message.includes('data:')) {
      try {
        const parser = new DOMParser();
        const doc = parser.parseFromString(message, 'text/html');
        let changed = false;
        doc.querySelectorAll('img[src^="data:"]').forEach(img => {
          const src = img.getAttribute('src') || '';
          const comma = src.indexOf(',');
          if (comma === -1) return;
          const meta = src.slice(5, comma);
          const parts = meta.split(';');
          if (!parts.includes('base64')) return;
          const contentType = parts[0] || 'application/octet-stream';
          const contentBytes = src.slice(comma + 1);
          hostedImages.push({ contentType, contentBytes });
          const idx = hostedImages.length;
          img.setAttribute('src', `../hostedContents/${idx}/$value`);
          changed = true;
        });
        if (changed) {
          message = doc.body.innerHTML;
        }
      } catch {}
    }

    const filesSnapshot = [...attach.files];
    if (filesSnapshot.length) {
      statusEl.textContent = 'Uploading files…';
      statusEl.classList.remove('hidden');
      const apiParts = [];
      const INLINE_IMAGE_MAX = 200 * 1024;
      for (const f of filesSnapshot) {
        try {
          if (f.type.startsWith('image/') && f.size <= INLINE_IMAGE_MAX) {
            const b64 = await _fileToBase64(f);
            hostedImages.push({ contentType: f.type, contentBytes: b64 });
            const idx = hostedImages.length;
            apiParts.push(`<img src="../hostedContents/${idx}/$value" style="max-width:400px;border-radius:4px" alt="${escapeHtml(f.name)}">`);
          } else {
            const fd = new FormData();
            fd.append('file', f);
            const up = await fetch('/api/upload/onedrive', { method: 'POST', body: fd });
            const upData = await up.json();
            if (!up.ok) throw new Error(upData.detail || 'Upload failed');
            const isImg = f.type.startsWith('image/');
            const link = isImg
              ? `<a href="${escapeHtml(upData.url)}">${escapeHtml(upData.name)}</a>`
              : `\uD83D\uDCCE <a href="${escapeHtml(upData.url)}">${escapeHtml(upData.name)}</a>`;
            apiParts.push(link);
          }
        } catch (err) {
          statusEl.textContent = 'Upload error: ' + err.message;
          sendBtn.disabled = false;
          _newComposeInFlight = false;
          return;
        }
      }
      if (apiParts.length) {
        message = (message || '') + (message ? '<br>' : '') + apiParts.join('<br>');
      }
    }

    statusEl.classList.remove('hidden');
    statusEl.textContent = '';
    const gatorStatus = _gatorSendStatus(statusEl);
    try {
      const res = await fetch('/api/teams/chats/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to, message, hosted_images: hostedImages, mentions }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed');
      editor.clearDraft();
      if (quillInst) quillInst.setContents([]);
      const list = attach.zoneEl.querySelector('.tp-attach-list');
      if (list) list.innerHTML = '';
      attach.files.length = 0;
      attach.zoneEl.classList.add('hidden');
      gatorStatus.success('Message delivered!');
      if (data.chat_id) tpThreadCache.delete(data.chat_id);
      if (data.chat_id) {
        const _recipientTopic = (toField.getPeople ? toField.getPeople() : []).map(r => r.name || r.email).filter(Boolean).join(', ');
        const _newChatEntry = { id: data.chat_id, topic: _recipientTopic, chat_type: 'oneOnOne',
          last_message: '', last_message_time: new Date().toISOString(), unread_count: 0, member_emails: toField.getEmails()?.split(',').map(e => e.trim()).filter(Boolean) || [] };
        if (_recipientTopic) _chatInfoCache.set(data.chat_id, { id: data.chat_id, topic: _recipientTopic, chat_type: 'oneOnOne' });
        // Optimistically insert at top of list so the chat appears without a full re-render
        if (tpState.list && !tpState.list.find(c => c.id === data.chat_id)) {
          tpState.list.unshift(_newChatEntry);
          renderTeamsList(tpState.list);
        }
        tpLoadDetail(data.chat_id);
        // Background refresh to reconcile — won't re-render if signature matches
        _fetchTeamsList().catch(() => {});
      } else {
        _clearListCache('teams');
        _fetchTeamsList().catch(() => {});
      }
      sendBtn.disabled = false;
      updateSendState();
    } catch (e) {
      gatorStatus.fail(e.message);
      sendBtn.disabled = false;
    } finally {
      _newComposeInFlight = false;
    }
  });

  updateSendState();

  toField.focusInput();
}

/* ── Mention helpers ─────────────────────────────────────── */

/**
 * Given plain text and a mentionMap (token → {id,name,email}),
 * returns { html, mentions } ready for the Graph API.
 * Replaces "@Token" occurrences with <at id="N">Name</at> and
 * builds the mentions[] array Teams needs to fire notifications.
 */
function _buildMentionPayload(quillInst) {
  const delta = quillInst.getContents();
  const mentions = [];
  let idx = 0;
  delta.ops.forEach(op => {
    if (op.insert && op.insert.mention) {
      const m = op.insert.mention;
      const mention = {
        id: idx++,
        mentionText: m.name,
      };
      mention.mentioned = {
        user: {
          id: m.id || '',
          displayName: m.name,
          userIdentityType: 'aadUser',
        },
      };
      mentions.push(mention);
    }
  });
  if (mentions.length === 0) return { html: null, mentions: [] };
  // Clone DOM and replace .ql-mention spans with <at> tags for Skype API
  const clone = quillInst.root.cloneNode(true);
  clone.querySelectorAll('.ql-mention').forEach((el, i) => {
    const m = mentions[i];
    if (!m) return;
    // Skype chatsvc stores mentions as <span itemtype="http://schema.skype.com/Mention">
    const span = document.createElement('span');
    span.setAttribute('itemscope', '');
    span.setAttribute('itemtype', 'http://schema.skype.com/Mention');
    span.setAttribute('itemid', String(i));
    span.textContent = m.mentionText;
    el.replaceWith(span);
  });
  let finalHtml = clone.innerHTML;
  // Apply same indent conversion as the main send path so mentions + indent work together
  finalHtml = _quillIndentToNestedList(finalHtml);
  finalHtml = finalHtml.replace(/<p>/g, '<div>').replace(/<\/p>/g, '</div>');
  finalHtml = _stripTrailingEmptyBlocks(finalHtml);
  return { html: finalHtml, mentions };
}

/* ── Teams send ──────────────────────────────────────────── */

async function tpSendTeamsMessage(chatId, text, scrollEl, isHtml = false, hostedImages = [], displayText = null, mentions = []) {
  // ── SAFETY: Final check — compose chat_id must match what we're sending to ──
  const activeCompose = document.querySelector('.tp-compose[data-chat-id]');
  if (activeCompose && activeCompose.dataset.chatId !== chatId) {
    console.error(`[SAFETY] tpSendTeamsMessage BLOCKED: compose=${activeCompose.dataset.chatId} target=${chatId}`);
    _showAlert('Send blocked: target chat changed. Your compose was for "' + (activeCompose.dataset.chatTopic || 'unknown') + '".', 'error');
    return;
  }
  _promoteHotChat(chatId, 'outbound');

  // Optimistic bubble — mine style
  // displayText may differ from text when hostedContents refs are used (data URIs for local display)
  const bubbleHtml = displayText !== null ? displayText : (isHtml ? text : '');
  // Normalize Skype mention spans → <at data-aad="..."> for optimistic render (#93).
  // _buildMentionPayload emits itemtype spans; the backend normalizes these on fetch.
  // Running the same conversion here makes mention chips appear immediately.
  let displayHtml = bubbleHtml;
  if (mentions.length && displayHtml) {
    displayHtml = displayHtml.replace(
      /<span[^>]*itemtype="http:\/\/schema\.skype\.com\/Mention"[^>]*itemid="(\d+)"[^>]*>(.*?)<\/span>/g,
      (_, itemid, inner) => {
        const m = mentions.find(x => String(x.id) === itemid);
        const aad = m?.mentioned?.user?.id || '';
        return aad ? `<at data-aad="${aad}">${inner}</at>` : `<at>${inner}</at>`;
      },
    );
  }
  const optimistic = _buildTeamsMessage({
    id: '_optimistic_' + Date.now(),
    is_mine: true,
    sender_name: 'You',
    body: isHtml ? '' : text,
    body_html: displayHtml,
    created_at: new Date().toISOString(),
    last_modified_at: '',
    reactions: [],
  }, chatId);

  if (scrollEl) { scrollEl.appendChild(optimistic); scrollEl.scrollTop = scrollEl.scrollHeight; }

  // Invalidate thread cache so next load fetches fresh data with the new message
  tpThreadCache.delete(chatId);

  try {
    // Route to channel endpoint if composite ID (ch::teamId::channelId)
    let sendUrl, sendBody;
    if (chatId.startsWith('ch::')) {
      const parts = chatId.split('::');
      sendUrl = `/api/teams/channels/${encodeURIComponent(parts[1])}/${encodeURIComponent(parts[2])}/send`;
      sendBody = JSON.stringify({ message: text });
    } else {
      sendUrl = `/api/teams/chats/${encodeURIComponent(chatId)}/send`;
      sendBody = JSON.stringify({ message: text, hosted_images: hostedImages, mentions });
    }
    const res = await fetch(sendUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: sendBody,
    });
    if (res.status === 401 || res.status === 403) {
      // Retry once — token may have just been refreshed
      const retry = await fetch(sendUrl, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: sendBody,
      }).catch(() => null);
      if (retry && retry.ok) {
        const retryData = await retry.json().catch(() => ({}));
        if (retryData.message_id) optimistic.dataset.msgId = retryData.message_id;
        tpThreadCache.delete(chatId);
        return; // Retry succeeded
      }
      optimistic.remove();
      _showAuthOverlay('Teams');
      return;
    }
    if (!res.ok) {
      // Mark optimistic message as failed
      const timeEl = optimistic.querySelector('.tp-msg-time');
      if (timeEl) timeEl.insertAdjacentHTML('beforeend', ' <span style="color:var(--warn,#f87171)">⚠ failed</span>');
    } else {
      // Update optimistic bubble with real message ID so edit works immediately
      const data = await res.json().catch(() => ({}));
      if (data.message_id) optimistic.dataset.msgId = data.message_id;
      const textEl = optimistic.querySelector('.tp-msg-text');
      // Prefer the backend's returned body_html — it has the REAL ASM image URLs
      // (the editor's displayHtml still holds the pasted data: URIs, which native
      // Teams can't store on a later edit) (#112). Mentions are already <at data-aad>
      // normalized in displayHtml; the backend body has Skype mention spans, so when
      // there are mentions keep displayHtml, otherwise prefer the ASM-URL body.
      let storeHtml = displayHtml;
      if (data.body_html && !mentions.length) storeHtml = data.body_html;
      if (textEl && storeHtml) {
        textEl.dataset.bodyHtml = storeHtml;
        // If we stored ASM URLs, re-render locally via the proxy so the image shows
        // (browser can't load asm.skype.com directly — needs the Skype token).
        if (/<img\b[^>]*src="https:\/\/[^"]*asm\.skype\.com/i.test(storeHtml)) {
          const local = storeHtml.replace(
            /<img\b([^>]*)\bsrc="(https:\/\/[^"]*asm\.skype\.com[^"]+)"([^>]*)>/gi,
            (_m, pre, url, post) =>
              `<img${pre}src="/api/teams/proxy-image?url=${encodeURIComponent(url)}"${post}>`,
          );
          textEl.innerHTML = sanitizeHtml(local);
          // Re-wire @mention click handlers — innerHTML reassignment dropped the
          // listeners attached in _buildTeamsMessage (#144).
          textEl.querySelectorAll('at[data-aad]').forEach(el => {
            const aadId = el.dataset.aad;
            if (!aadId) return;
            el.style.cursor = 'pointer';
            el.addEventListener('click', e => { e.stopPropagation(); _showPersonCard(aadId, el); });
          });
          // Re-wire reply blockquote navigation — same innerHTML reassignment also
          // dropped these handlers, leaving the "Replying to" quote unclickable (#144).
          textEl.querySelectorAll('blockquote[itemtype="http://schema.skype.com/Reply"]').forEach(bq => {
            const mid = bq.getAttribute('itemid');
            if (!mid || bq.closest('blockquote[itemtype="http://schema.skype.com/Forward"]')) return;
            bq.style.cursor = 'pointer';
            bq.title = 'Click to jump to original message';
            bq.addEventListener('click', e => { e.stopPropagation(); if (_activeSeekToMessage) _activeSeekToMessage(mid); });
          });
        }
      }
    }
    tpThreadCache.delete(chatId);
  } catch {
    const timeEl = optimistic.querySelector('.tp-msg-time');
    if (timeEl) timeEl.insertAdjacentHTML('beforeend', ' <span style="color:var(--warn,#f87171)">⚠ failed</span>');
  }
}

/* ── OneDrive: nav sidebar (left) + file browser (right) ── */

// TTLs for list caches (ms). Sites/drives are session-scoped (no TTL check).
const _OD_RECENT_TTL  = 2 * 60 * 1000;  // Recent: 2 min  — changes as you work
const _OD_SHARED_TTL  = 5 * 60 * 1000;  // Shared: 5 min  — changes when someone shares

const _odState = {
  section: 'my-drive',        // active left-col nav section
  folderCache: new Map(),     // folderId → items[]  (cleared on Refresh)
  navStack: [],               // [{id,name}] for right-col drill-down
  selectedFolderId: 'root',
  selectedFolderName: 'My Drive',
  currentDriveId: null,       // non-null when browsing a SharePoint drive
  currentSiteName: null,      // site name to show in drive-root back button
  quotaCache: null,
  searchTimer: null,
  // List caches — all cleared by the Refresh button
  sitesCache: null,           // session-scoped: {sites:[]}
  drivesCache: new Map(),     // siteId → {drives:[]}  (session-scoped)
  recentCache: null,          // {items:[], ts}  TTL: _OD_RECENT_TTL
  sharedCache: null,          // {items:[], ts}  TTL: _OD_SHARED_TTL
};

// SharePoint icon — static file served from /static/icons/sharepoint.svg
const _SP_ICON_SVG = `<img src="/static/icons/sharepoint.svg" width="16" height="16" alt="SharePoint" style="flex-shrink:0;vertical-align:middle;display:block;">`;

const _OD_NAV = [
  { id: 'my-drive',  icon: '📂', label: 'My Drive' },
  { id: 'sites',     icon: _SP_ICON_SVG, label: 'SharePoint Sites', svg: true },
  { id: 'recent',    icon: '🕐', label: 'Recent' },
  { id: 'shared',    icon: '👥', label: 'Shared with me' },
  null, // divider
  { id: 'documents', icon: '📄', label: 'Documents', special: 'documents' },
  { id: 'pictures',  icon: '🖼️', label: 'Pictures',  special: 'photos' },
  { id: 'desktop',   icon: '🖥️', label: 'Desktop',   special: 'desktop' },
];

async function _fetchOneDriveFolder(folderId) {
  const cacheKey = _odState.currentDriveId ? `${_odState.currentDriveId}::${folderId}` : folderId;
  if (_odState.folderCache.has(cacheKey)) return _odState.folderCache.get(cacheKey);
  let url;
  if (_odState.currentDriveId) {
    url = `/api/onedrive/drives/${encodeURIComponent(_odState.currentDriveId)}/folders?parent=${encodeURIComponent(folderId)}`;
  } else {
    url = `/api/onedrive/folders?parent=${encodeURIComponent(folderId)}`;
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
  const data = await res.json();
  _odState.folderCache.set(cacheKey, data.items || []);
  return data.items || [];
}

// Entry point — renders nav sidebar in left col, folder browser in right col
async function _fetchOneDriveList() {
  _renderOdNavSidebar();
  _odOpenSection(_odState.section);
}

/* ── Left col: Navigation sidebar ─────────────────────────── */

function _renderOdNavSidebar() {
  const col = document.getElementById('tp-list-col');
  col.innerHTML = '';
  col.style.display = 'flex';
  col.style.flexDirection = 'column';

  // Quota bar moved to the upload zone (more relevant when uploading) — see
  // _buildCollapsibleUploadZone.

  // ── Nav items ─────────────────────────────────────────────
  const nav = document.createElement('div');
  nav.className = 'od-nav-list';
  col.appendChild(nav);

  _OD_NAV.forEach(item => {
    if (item === null) {
      const divider = document.createElement('div');
      divider.className = 'od-nav-divider';
      nav.appendChild(divider);
      return;
    }
    const row = document.createElement('div');
    row.className = 'od-nav-item' + (_odState.section === item.id ? ' active' : '');
    row.dataset.section = item.id;
    const iconSpan = document.createElement('span');
    iconSpan.className = 'od-nav-icon';
    if (item.svg) { iconSpan.innerHTML = item.icon; } else { iconSpan.textContent = item.icon; }
    const labelSpan = document.createElement('span');
    labelSpan.className = 'od-nav-label';
    labelSpan.textContent = item.label;
    row.appendChild(iconSpan);
    row.appendChild(labelSpan);
    row.addEventListener('click', () => {
      if (_odState.section === item.id) return;
      _odState.section = item.id;
      _odState.currentDriveId = null;
      _odState.currentSiteName = null;
      // Reset folder state when changing sections
      if (!item.special && item.id !== 'my-drive') {
        // flat section — no folder state needed
      } else if (item.id === 'my-drive') {
        _odState.navStack = [];
        _odState.selectedFolderId = 'root';
        _odState.selectedFolderName = 'My Drive';
      }
      // Update active state
      nav.querySelectorAll('.od-nav-item').forEach(r => r.classList.remove('active'));
      row.classList.add('active');
      _odOpenSection(item.id);
    });
    nav.appendChild(row);
  });

  // ── Wire toolbar search for OneDrive ──────────────────────
  const _tpSearchInput = document.getElementById('tp-search-input');
  if (_tpSearchInput) {
    _tpSearchInput.placeholder = 'Search OneDrive…';
    _tpSearchInput.value = _odState.section === 'search' ? (_odState.searchQuery || '') : '';
    _tpSearchInput.oninput = () => {
      const q = _tpSearchInput.value.trim();
      clearTimeout(_odState.searchTimer);
      if (!q) {
        { const _sp=document.getElementById('tp-search-spinner'); const _sw=document.getElementById('tp-search-wrap'); if(_sp)_sp.classList.add('hidden'); if(_sw)_sw.classList.remove('is-searching'); }
        if (_odState.section === 'search') {
          _odState.section = 'my-drive';
          _odState.navStack = [];
          _odState.selectedFolderId = 'root';
          _odState.selectedFolderName = 'My Drive';
          nav.querySelectorAll('.od-nav-item').forEach(r =>
            r.classList.toggle('active', r.dataset.section === 'my-drive'));
          _odOpenSection('my-drive');
        }
        return;
      }
      const _sp = document.getElementById('tp-search-spinner');
      const _sw = document.getElementById('tp-search-wrap');
      if (_sp) _sp.classList.remove('hidden');
      if (_sw) _sw.classList.add('is-searching');
      _odState.searchTimer = setTimeout(() => {
        _odState.searchQuery = q;
        _odState.section = 'search';
        nav.querySelectorAll('.od-nav-item').forEach(r => r.classList.remove('active'));
        _odOpenSection('search').finally(() => {
          const _sp2 = document.getElementById('tp-search-spinner');
          const _sw2 = document.getElementById('tp-search-wrap');
          if (_sp2) _sp2.classList.add('hidden');
          if (_sw2) _sw2.classList.remove('is-searching');
        });
      }, 400);
    };
  }
}

async function _renderOdQuota(wrap) {
  if (_odState.quotaCache) {
    _buildQuotaBar(wrap, _odState.quotaCache);
    return;
  }
  wrap.innerHTML = '<div class="od-quota-loading">Loading storage…</div>';
  try {
    const res = await fetch('/api/onedrive/quota');
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
    const data = await res.json();
    _odState.quotaCache = data;
    _buildQuotaBar(wrap, data);
  } catch {
    wrap.innerHTML = '<div class="od-quota-loading" style="color:var(--text-sub)">Storage unavailable</div>';
  }
}

function _buildQuotaBar(wrap, quota) {
  const pct = quota.total_bytes > 0 ? Math.min(100, (quota.used_bytes / quota.total_bytes) * 100) : 0;
  const warn = pct > 85;
  wrap.innerHTML = `
    <div class="od-quota-bar-wrap${warn ? ' od-quota-warn' : ''}">
      <div class="od-quota-bar-track">
        <div class="od-quota-bar-fill" style="width:${pct.toFixed(1)}%"></div>
      </div>
      <div class="od-quota-label">${quota.used_label} of ${quota.total_label} used</div>
    </div>
  `;
}

/* ── Right col: section router ────────────────────────────── */

async function _odOpenSection(sectionId) {
  const detail = document.getElementById('tp-detail-col');
  detail.innerHTML = '<div class="tp-empty-state"><span class="tp-skeleton-line" style="width:60%"></span></div>';

  try {
    if (sectionId === 'my-drive') {
      await _odLoadFolderBrowser(_odState.selectedFolderId, _odState.selectedFolderName);

    } else if (sectionId === 'recent') {
      const now = Date.now();
      if (_odState.recentCache && (now - _odState.recentCache.ts) < _OD_RECENT_TTL) {
        _odRenderFlatList(detail, _odState.recentCache.items, 'No recent files', '🕐 Recent');
      } else {
        const res = await fetch('/api/onedrive/recent');
        if (tpState.type !== 'onedrive') return;
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
        const data = await res.json();
        _odState.recentCache = { items: data.items || [], ts: Date.now() };
        _odRenderFlatList(detail, _odState.recentCache.items, 'No recent files', '🕐 Recent');
      }

    } else if (sectionId === 'shared') {
      const now = Date.now();
      if (_odState.sharedCache && (now - _odState.sharedCache.ts) < _OD_SHARED_TTL) {
        _odRenderFlatList(detail, _odState.sharedCache.items, 'Nothing shared with you', '👥 Shared with me');
      } else {
        const res = await fetch('/api/onedrive/shared');
        if (tpState.type !== 'onedrive') return;
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
        const data = await res.json();
        _odState.sharedCache = { items: data.items || [], ts: Date.now() };
        _odRenderFlatList(detail, _odState.sharedCache.items, 'Nothing shared with you', '👥 Shared with me');
      }

    } else if (sectionId === 'sites') {
      if (_odState.sitesCache) {
        _odRenderSitesList(detail, _odState.sitesCache.sites);
      } else {
        const res = await fetch('/api/onedrive/sites');
        if (tpState.type !== 'onedrive') return;
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
        const data = await res.json();
        _odState.sitesCache = { sites: data.sites || [] };
        _odRenderSitesList(detail, _odState.sitesCache.sites);
      }

    } else if (sectionId === 'search') {
      const q = _odState.searchQuery || '';
      if (!q) { detail.innerHTML = '<div class="tp-empty-state"><span>Type to search…</span></div>'; return; }
      const res = await fetch(`/api/onedrive/search?q=${encodeURIComponent(q)}`);
      if (tpState.type !== 'onedrive') return;
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
      const data = await res.json();
      _odRenderFlatList(detail, data.items || [], `No results for "${q}"`, `🔍 "${q}"`);

    } else {
      // Special folder: documents / pictures / desktop (cached for session)
      const nav = _OD_NAV.find(n => n && n.id === sectionId);
      if (!nav?.special) return;
      if (!window._odSpecialFolderCache) window._odSpecialFolderCache = {};
      let data = window._odSpecialFolderCache[nav.special];
      if (!data) {
        const res = await fetch(`/api/onedrive/special/${nav.special}`);
        if (tpState.type !== 'onedrive') return;
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
        data = await res.json();
        window._odSpecialFolderCache[nav.special] = data;
      }
      _odState.navStack = [];
      _odState.selectedFolderId = data.id;
      _odState.selectedFolderName = data.name;
      await _odLoadFolderBrowser(data.id, data.name);
    }
  } catch (e) {
    if (tpState.type !== 'onedrive') return;
    detail.innerHTML = `<div class="tp-empty-state"><span style="color:var(--warn)">⚠ ${escapeHtml(e.message)}</span></div>`;
  }
}

async function _odLoadFolderBrowser(folderId, folderName) {
  const detail = document.getElementById('tp-detail-col');
  detail.innerHTML = '';
  // Standardized toolbar in the persistent header: back (master-detail nav) +
  // New folder. Uploads live in the bottom upload zone, so the old "+ New ▾"
  // dropdown is gone — only "New folder" is a distinct create action.
  // Back has three cases: subfolder → parent; site drive-root → site list; My Drive root → none.
  let _odBack = null;
  if (_odState.navStack.length > 0) {
    const parent = _odState.navStack[_odState.navStack.length - 1];
    _odBack = { title: `Back to ${parent.name}`, onClick: async () => {
      const prev = _odState.navStack.pop();
      _odState.selectedFolderId = prev.id;
      _odState.selectedFolderName = prev.name;
      tpState.selectedId = null;
      await _odLoadFolderBrowser(prev.id, prev.name);
    } };
  } else if (_odState.currentDriveId && _odState.currentSiteName) {
    _odBack = { title: `Back to ${_odState.currentSiteName}`, onClick: () => {
      _odState.currentDriveId = null;
      _odState.currentSiteName = null;
      _odState.navStack = [];
      _odOpenSection('sites');
    } };
  }
  tpBuildDetailToolbar({
    app: 'onedrive',
    back: _odBack || undefined,
    title: { text: folderName || _odState.selectedFolderName || 'Files', title: folderName || '' },
    actions: [
      { kind: 'icon', iconHtml: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>',
        title: 'New folder', group: 0, onClick: () => _odStartCreateFolder(document.querySelector('.od-list-scroll'), _odState.selectedFolderId) },
    ],
  });
  // Build upload zone at bottom first, then prepend file list
  _buildCollapsibleUploadZone(detail, folderId, null);
  const items = await _fetchOneDriveFolder(folderId);
  if (tpState.type !== 'onedrive') return; // skill changed while loading
  renderOneDriveList(items);
}

function _odCacheKey(folderId) {
  return _odState.currentDriveId ? `${_odState.currentDriveId}::${folderId}` : folderId;
}

function _odShowError(container, message) {
  container.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'tp-empty-state';
  const span = document.createElement('span');
  span.style.color = 'var(--warn)';
  span.textContent = '⚠ ' + message;
  wrap.appendChild(span);
  container.appendChild(wrap);
}

const _SP_FAV_KEY = 'gator-sp-favorites';
function _spGetFavs() { try { return JSON.parse(localStorage.getItem(_SP_FAV_KEY) || '[]'); } catch { return []; } }
function _spToggleFav(id, name) {
  const favs = _spGetFavs();
  const idx = favs.findIndex(f => f.id === id);
  if (idx >= 0) { favs.splice(idx, 1); } else { favs.push({ id, name }); }
  localStorage.setItem(_SP_FAV_KEY, JSON.stringify(favs));
}
function _spIsFav(id) { return _spGetFavs().some(f => f.id === id); }

function _odRenderSitesList(container, sites) {
  container.innerHTML = '';

  // Header
  const header = document.createElement('div');
  header.className = 'tp-thread-header';
  const iconWrap = document.createElement('span');
  iconWrap.className = 'tp-thread-title-icon';
  iconWrap.innerHTML = _SP_ICON_SVG;
  const titleSpan = document.createElement('span');
  titleSpan.className = 'tp-thread-title';
  titleSpan.textContent = 'SharePoint Sites';
  header.appendChild(iconWrap);
  header.appendChild(titleSpan);
  container.appendChild(header);

  if (!sites.length) {
    const empty = document.createElement('div');
    empty.className = 'tp-empty-state';
    empty.appendChild(Object.assign(document.createElement('span'), { textContent: 'No SharePoint sites found' }));
    container.appendChild(empty);
    return;
  }

  const favIds = new Set(_spGetFavs().map(f => f.id));
  // Sort: favorites first, then alphabetical
  const sorted = [...sites].sort((a, b) => {
    const fa = favIds.has(a.id), fb = favIds.has(b.id);
    if (fa !== fb) return fa ? -1 : 1;
    return (a.name || '').localeCompare(b.name || '');
  });

  const list = document.createElement('div');
  list.className = 'od-flat-list';

  const renderRows = () => {
    list.innerHTML = '';
    const curFavs = new Set(_spGetFavs().map(f => f.id));
    const reSorted = [...sites].sort((a, b) => {
      const fa = curFavs.has(a.id), fb = curFavs.has(b.id);
      if (fa !== fb) return fa ? -1 : 1;
      return (a.name || '').localeCompare(b.name || '');
    });
    reSorted.forEach(site => {
      const isFav = curFavs.has(site.id);
      const row = document.createElement('div');
      row.className = 'od-flat-item od-flat-folder od-site-row';

      const icon = document.createElement('span');
      icon.className = 'od-item-icon od-site-icon';
      icon.innerHTML = _SP_ICON_SVG;

      const name = document.createElement('span');
      name.className = 'od-item-name';
      name.textContent = site.name;

      const fav = document.createElement('button');
      fav.className = 'od-fav-btn' + (isFav ? ' od-fav-active' : '');
      fav.title = isFav ? 'Remove from favorites' : 'Add to favorites';
      fav.textContent = isFav ? '★' : '☆';
      fav.addEventListener('click', e => {
        e.stopPropagation();
        _spToggleFav(site.id, site.name);
        renderRows(); // re-sort and re-render in place
      });

      row.appendChild(icon);
      row.appendChild(name);
      row.appendChild(fav);
      row.addEventListener('click', async () => {
        container.innerHTML = '';
        const skel = document.createElement('div');
        skel.className = 'tp-empty-state';
        const line = Object.assign(document.createElement('span'), { className: 'tp-skeleton-line' });
        line.style.width = '60%';
        skel.appendChild(line);
        container.appendChild(skel);
        try {
          if (_odState.drivesCache.has(site.id)) {
            _odRenderDrivesList(container, site.id, site.name, _odState.drivesCache.get(site.id));
          } else {
            const res = await fetch('/api/onedrive/sites/' + encodeURIComponent(site.id) + '/drives');
            if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
            const data = await res.json();
            _odState.drivesCache.set(site.id, data.drives || []);
            _odRenderDrivesList(container, site.id, site.name, data.drives || []);
          }
        } catch (e) {
          _odShowError(container, e.message);
        }
      });
      list.appendChild(row);
    });
  };
  renderRows();
  container.appendChild(list);
}

function _odRenderDrivesList(container, siteId, siteName, drives) {
  container.innerHTML = '';
  // Back + site title now live in the standardized header toolbar (no sub-bar).
  tpBuildDetailToolbar({
    app: 'onedrive',
    back: { title: 'Back to SharePoint Sites', onClick: () => {
      _odState.currentDriveId = null;
      _odState.navStack = [];
      if (_odState.sitesCache) {
        _odRenderSitesList(container, _odState.sitesCache.sites);
      } else {
        fetch('/api/onedrive/sites')
          .then(r => r.json())
          .then(d => { _odState.sitesCache = { sites: d.sites || [] }; _odRenderSitesList(container, _odState.sitesCache.sites); })
          .catch(e => _odShowError(container, e.message));
      }
    } },
    title: { text: siteName, title: siteName },
    actions: [],
  });
  if (!drives.length) {
    const empty = document.createElement('div');
    empty.className = 'tp-empty-state';
    const span = document.createElement('span');
    span.textContent = 'No document libraries found';
    empty.appendChild(span);
    container.appendChild(empty);
    return;
  }
  const list = document.createElement('div');
  list.className = 'od-flat-list';
  drives.forEach(drive => {
    const row = document.createElement('div');
    row.className = 'od-flat-item od-flat-folder';
    const icon = document.createElement('span');
    icon.className = 'od-item-icon';
    icon.textContent = '📁';
    const name = document.createElement('span');
    name.className = 'od-item-name';
    name.textContent = drive.name;
    row.appendChild(icon);
    row.appendChild(name);
    row.addEventListener('click', () => {
      _odState.currentDriveId = drive.id;
      _odState.currentSiteName = siteName; // remember site for drive-root back button
      _odState.navStack = [];
      _odState.selectedFolderId = 'root';
      _odState.selectedFolderName = drive.name;
      _odLoadFolderBrowser('root', drive.name);
    });
    list.appendChild(row);
  });
  container.appendChild(list);
}

function _odRenderFlatList(container, items, emptyMsg, title) {
  container.innerHTML = '';

  const header = document.createElement('div');
  header.className = 'tp-thread-header';
  header.innerHTML = `<span class="tp-thread-title">${escapeHtml(title)}</span>`;
  container.appendChild(header);

  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'tp-empty-state';
    empty.innerHTML = `<span>${escapeHtml(emptyMsg)}</span>`;
    container.appendChild(empty);
    return;
  }

  const list = document.createElement('div');
  list.className = 'od-flat-list';
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'od-flat-row';
    if (_isPinned('onedrive', String(item.id))) row.classList.add('tp-item-pinned');
    const modDate = item.modified ? new Date(item.modified).toLocaleDateString() : '';
    row.innerHTML = `
      <span class="od-item-icon">${_odMimeIcon(item.mime_type, item.is_folder)}</span>
      <div class="od-flat-info">
        <span class="od-flat-name">${escapeHtml(item.name)}</span>
        <span class="od-flat-meta">${modDate}${item.size ? ' · ' + _formatBytes(item.size) : ''}</span>
      </div>
    `;
    const flatActions = document.createElement('div');
    flatActions.className = 'od-row-actions';
    flatActions.appendChild(_createPinBtn('onedrive', item.id, item.name, { file_path: item.path || item.name, web_url: item.web_url || '', drive_id: item.drive_id || '' }));
    row.appendChild(flatActions);
    const flatMoreBtn = document.createElement('button');
    flatMoreBtn.className = 'od-row-more-btn';
    flatMoreBtn.title = 'More options';
    flatMoreBtn.textContent = '⋮';
    flatMoreBtn.addEventListener('click', e => {
      e.stopPropagation();
      const r = flatMoreBtn.getBoundingClientRect();
      _odShowContextMenu(r.right, r.bottom, item);
    });
    row.appendChild(flatMoreBtn);
    row.addEventListener('click', e => {
      if (e.target.closest('.od-flat-open')) return;
      container.querySelectorAll('.od-flat-row').forEach(r => r.classList.remove('active'));
      row.classList.add('active');
      renderOneDriveFileDetail(item);
    });
    row.addEventListener('contextmenu', e => {
      e.preventDefault();
      _odShowContextMenu(e.clientX, e.clientY, item);
    });
    list.appendChild(row);
  });
  container.appendChild(list);
}

function _odMimeIcon(mimeType, isFolder) {
  if (isFolder) return '📁';
  if (!mimeType) return '📄';
  if (mimeType.startsWith('image/')) return '🖼️';
  if (mimeType.startsWith('video/')) return '🎬';
  if (mimeType.startsWith('audio/')) return '🎵';
  if (mimeType.includes('pdf')) return '📕';
  if (mimeType.includes('word') || mimeType.includes('document')) return '📝';
  if (mimeType.includes('sheet') || mimeType.includes('excel')) return '📊';
  if (mimeType.includes('presentation') || mimeType.includes('powerpoint')) return '📊';
  if (mimeType.includes('zip') || mimeType.includes('compressed')) return '🗜️';
  return '📄';
}

function renderOneDriveList(items) {
  // Right col (tp-detail-col) — insert file list + toolbar before the upload footer
  const col = document.getElementById('tp-detail-col');

  // Remove any existing file list + toolbar (leave upload footer in place)
  col.querySelectorAll('.od-toolbar, .od-list-scroll').forEach(el => el.remove());

  const uploadFooter = col.querySelector('.od-upload-footer');

  const folders = items.filter(i => i.is_folder);
  const files = items.filter(i => !i.is_folder);
  const allSorted = [...folders, ...files];

  // Scrollable item area
  const scroll = document.createElement('div');
  scroll.className = 'od-list-scroll';
  if (uploadFooter) col.insertBefore(scroll, uploadFooter);
  else col.appendChild(scroll);

  if (!allSorted.length) {
    scroll.innerHTML = '<div class="tp-empty-state" style="font-size:.8rem">Empty folder</div>';
  }

  allSorted.forEach(item => {
    const row = document.createElement('div');
    row.className = 'tp-list-item od-item-row' +
      (item.id === tpState.selectedId ? ' active' : '') +
      (_isPinned('onedrive', String(item.id)) ? ' tp-item-pinned' : '');
    row.dataset.itemId = item.id;

    const icon = document.createElement('span');
    icon.className = 'od-item-icon';
    icon.textContent = _odMimeIcon(item.mime_type, item.is_folder);

    const name = document.createElement('span');
    name.className = 'tp-li-name';
    name.textContent = item.name;

    const meta = document.createElement('span');
    meta.className = 'tp-li-preview';
    meta.textContent = item.is_folder
      ? (item.has_children ? 'Folder' : 'Empty folder')
      : _formatBytes(item.size);

    row.appendChild(icon);
    const info = document.createElement('div');
    info.className = 'tp-li-body';
    info.appendChild(name);
    info.appendChild(meta);
    row.appendChild(info);

    // Inline action buttons (always visible)
    const actions = document.createElement('div');
    actions.className = 'od-row-actions';
    actions.appendChild(_createPinBtn('onedrive', item.id, item.name, { file_path: item.path || item.name, size: item.size || 0, is_folder: !!item.is_folder, drive_id: item.drive_id || '' }));
    if (item.web_url) {
      const openBtn = document.createElement('button');
      openBtn.className = 'od-row-action-btn';
      openBtn.title = 'Open in OneDrive';
      openBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';
      openBtn.addEventListener('click', e => { e.stopPropagation(); window.open(item.web_url, '_blank'); });
      actions.appendChild(openBtn);
    }
    row.appendChild(actions);

    const moreBtn = document.createElement('button');
    moreBtn.className = 'od-row-more-btn';
    moreBtn.title = 'More options';
    moreBtn.textContent = '⋮';
    moreBtn.addEventListener('click', e => {
      e.stopPropagation();
      const r = moreBtn.getBoundingClientRect();
      _odShowContextMenu(r.right, r.bottom, item);
    });
    row.appendChild(moreBtn);

    row.addEventListener('click', () => {
      tpState.selectedId = item.id;
      saveTpState();
      if (item.is_folder) {
        _odNavigateIntoFolder(item.id, item.name);
      } else {
        scroll.querySelectorAll('.tp-list-item').forEach(r => r.classList.remove('active'));
        row.classList.add('active');
        renderOneDriveFileDetail(item);
      }
    });
    row.addEventListener('contextmenu', e => {
      e.preventDefault();
      _odShowContextMenu(e.clientX, e.clientY, item);
    });

    scroll.appendChild(row);
  });
  // "New folder" + back now live in the standardized header toolbar (built in
  // _odLoadFolderBrowser); uploads live in the bottom upload zone. The old
  // in-content od-toolbar "+ New ▾" dropdown is removed.
}

async function _odNavigateIntoFolder(folderId, folderName) {
  // Push current location onto stack before navigating in
  _odState.navStack.push({ id: _odState.selectedFolderId, name: _odState.selectedFolderName });
  _odState.selectedFolderId = folderId;
  _odState.selectedFolderName = folderName;
  // Use _odLoadFolderBrowser so the back breadcrumb is always rendered
  try {
    await _odLoadFolderBrowser(folderId, folderName);
  } catch (e) {
    _odState.navStack.pop(); // undo push on error
    _showListError('Could not load folder: ' + e.message, () => _odNavigateIntoFolder(folderId, folderName));
  }
}

function _odStartCreateFolder(listCol, parentFolderId) {
  const scroll = listCol.classList.contains('od-list-scroll') ? listCol : (listCol.querySelector('.od-list-scroll') || listCol);
  if (scroll.querySelector('.od-new-folder-row')) return; // already open

  const row = document.createElement('div');
  row.className = 'od-new-folder-row';
  row.innerHTML = `<span class="od-item-icon">📁</span>`;

  const inp = document.createElement('input');
  inp.type = 'text';
  inp.className = 'od-new-folder-input';
  inp.placeholder = 'Folder name…';
  inp.maxLength = 200;
  row.appendChild(inp);

  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'od-new-folder-cancel';
  cancelBtn.textContent = '×';
  cancelBtn.addEventListener('click', () => row.remove());
  row.appendChild(cancelBtn);

  // Insert at top of scrollable list
  scroll.insertBefore(row, scroll.firstChild);
  inp.focus();

  inp.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.stopPropagation(); row.remove(); }
    if (e.key === 'Enter') {
      const name = inp.value.trim();
      if (name) _odCreateFolder(name, parentFolderId, row, listCol);
    }
  });
}

async function _odCreateFolder(name, parentFolderId, inputRow, listCol) {
  const inp = inputRow.querySelector('.od-new-folder-input');
  if (inp) { inp.disabled = true; }

  try {
    const createUrl = _odState.currentDriveId
      ? `/api/onedrive/drives/${encodeURIComponent(_odState.currentDriveId)}/folders/${encodeURIComponent(parentFolderId)}`
      : `/api/onedrive/folders/${encodeURIComponent(parentFolderId)}`;
    const res = await fetch(createUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.status);

    // Invalidate cache and re-render list
    _odState.folderCache.delete(_odCacheKey(parentFolderId));
    const items = await _fetchOneDriveFolder(parentFolderId);
    inputRow.remove();
    renderOneDriveList(items);

    // Flash the newly created folder row
    const detailCol = document.getElementById('tp-detail-col');
    const newRow = detailCol.querySelector(`[data-item-id="${CSS.escape(data.id)}"]`);
    if (newRow) { newRow.classList.add('od-folder-flash'); newRow.addEventListener('animationend', () => newRow.classList.remove('od-folder-flash'), { once: true }); }
  } catch (e) {
    if (inp) { inp.disabled = false; inp.focus(); }
    const errEl = inputRow.querySelector('.od-new-folder-err') || document.createElement('span');
    errEl.className = 'od-new-folder-err';
    errEl.textContent = e.message;
    inputRow.appendChild(errEl);
  }
}

async function _loadOneDriveFolderDetail(folderId) {
  const detail = document.getElementById('tp-detail-col');
  // Show loading inside the file list area of the detail pane
  const listEl = detail.querySelector('.od-file-list');
  if (listEl) { listEl.innerHTML = '<div class="tp-empty-state" style="font-size:.8rem">Loading…</div>'; }
  try {
    const items = await _fetchOneDriveFolder(folderId);
    if (listEl) _renderFolderFileList(listEl, items);
  } catch (e) {
    if (listEl) listEl.innerHTML = `<div class="tp-empty-state" style="font-size:.8rem;color:var(--warn)">Error: ${escapeHtml(e.message)}</div>`;
  }
}

function _renderFolderFileList(container, items) {
  container.innerHTML = '';
  if (!items.length) {
    container.innerHTML = '<div class="tp-empty-state" style="font-size:.8rem">Empty folder</div>';
    return;
  }
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'od-detail-file-row';
    row.innerHTML = `
      <span class="od-item-icon">${_odMimeIcon(item.mime_type, item.is_folder)}</span>
      <span class="od-detail-file-name">${escapeHtml(item.name)}</span>
      <span class="od-detail-file-size">${item.is_folder ? '' : _formatBytes(item.size)}</span>
      ${item.web_url ? `<a href="${escapeHtml(item.web_url)}" target="_blank" class="od-open-link" title="Open in OneDrive"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></a>` : ''}
    `;
    container.appendChild(row);
  });
}

function renderOneDriveDetail(folderItem) {
  renderOneDriveUploadDetail(folderItem.id, folderItem.name);
}

function renderOneDriveUploadDetail(folderId, folderName) {
  const detail = document.getElementById('tp-detail-col');
  detail.innerHTML = '';

  // Header
  const header = document.createElement('div');
  header.className = 'tp-thread-header';
  header.innerHTML = `<span class="tp-thread-title">📁 ${escapeHtml(folderName)}</span>`;
  detail.appendChild(header);

  // Upload zone — full right col, no duplicate file list
  const uploadLabel = document.createElement('div');
  uploadLabel.className = 'od-section-label';
  uploadLabel.textContent = `Upload to ${folderName}`;
  detail.appendChild(uploadLabel);

  _buildCollapsibleUploadZone(detail, folderId, null);
}

function renderOneDriveFileDetail(item) {
  const detail = document.getElementById('tp-detail-col');
  detail.innerHTML = '';

  // ── Smart label based on mime type ──
  const mime = item.mime_type || '';
  let appLabel = 'Open';
  let appIcon = '↗';
  if (mime.includes('word') || mime.includes('document') || item.name.endsWith('.docx') || item.name.endsWith('.doc')) { appLabel = 'Open in Word'; appIcon = '📝'; }
  else if (mime.includes('sheet') || mime.includes('excel') || item.name.endsWith('.xlsx') || item.name.endsWith('.csv')) { appLabel = 'Open in Excel'; appIcon = '📊'; }
  else if (mime.includes('presentation') || mime.includes('powerpoint') || item.name.endsWith('.pptx')) { appLabel = 'Open in PowerPoint'; appIcon = '📊'; }
  else if (mime.includes('pdf')) { appLabel = 'Open PDF'; appIcon = '📕'; }
  else if (mime.startsWith('image/')) { appLabel = 'View Image'; appIcon = '🖼️'; }

  const ext = item.name.includes('.') ? item.name.split('.').pop().toUpperCase() : '';
  const modStr = item.modified ? new Date(item.modified).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—';

  // ── Standardized toolbar in the persistent header (#tp-detail-header) ──
  // Title + app-level actions (Ask, Open, Copy, More, Pin). The breadcrumb,
  // file-info and AI sections below stay in the content column.
  const _odPin = _createPinBtn('onedrive', item.id, item.name, { file_path: item.path || item.name, web_url: item.web_url || '', drive_id: item.drive_id || '' });
  const _odActions = [
    { kind: 'icon', iconHtml: '✦', title: 'Summarize this file', group: 0,
      onClick: () => tpInjectAIPrompt(`Summarize the file "${item.name}" from my OneDrive`) },
  ];
  if (item.web_url) {
    _odActions.push({ kind: 'icon', iconHtml: _TP_EXT_LINK_SVG, title: appLabel, group: 1,
      onClick: () => window.open(item.web_url, '_blank') });
    _odActions.push({ kind: 'icon', iconHtml: '🔗', title: 'Copy link', group: 1,
      onClick: () => { navigator.clipboard.writeText(item.web_url).catch(() => {}); } });
  }
  _odActions.push({ el: _odPin, kind: 'icon', title: 'Pin file', group: 1 });
  _odActions.push({ kind: 'icon', iconHtml: '⋮', title: 'More options', group: 1,
    onClick: (e) => { const r = e.currentTarget.getBoundingClientRect(); _odShowContextMenu(r.right, r.bottom, item); } });
  tpBuildDetailToolbar({
    app: 'onedrive',
    back: { title: `Back to ${_odState.selectedFolderName || 'files'}`, onClick: () => _odOpenSection(_odState.section) },
    title: { text: item.name, icon: _odMimeIcon(item.mime_type, false), title: item.name },
    actions: _odActions,
  });

  // ── File info section ──
  const info = document.createElement('div');
  info.style.cssText = 'padding:.8rem;display:flex;flex-direction:column;gap:.1rem;font-size:.78rem;color:var(--text-sub,#94a3b8)';
  info.innerHTML = `
    <div style="display:flex;gap:.5rem"><span style="width:70px;color:var(--text-dim,#64748b)">Type</span><span>${escapeHtml(ext || 'File')} ${mime ? '(' + escapeHtml(mime.split('/').pop()) + ')' : ''}</span></div>
    <div style="display:flex;gap:.5rem"><span style="width:70px;color:var(--text-dim,#64748b)">Size</span><span>${_formatBytes(item.size)}</span></div>
    <div style="display:flex;gap:.5rem"><span style="width:70px;color:var(--text-dim,#64748b)">Modified</span><span>${modStr}</span></div>
    ${item.path ? `<div style="display:flex;gap:.5rem"><span style="width:70px;color:var(--text-dim,#64748b)">Path</span><span style="word-break:break-all">${escapeHtml(item.path)}</span></div>` : ''}
  `;
  detail.appendChild(info);

  // ── Divider ──
  const divider = document.createElement('div');
  divider.style.cssText = 'height:1px;background:var(--border,#1e293b);margin:0 .8rem';
  detail.appendChild(divider);

  // ── AI actions ──
  const aiSection = document.createElement('div');
  aiSection.style.cssText = 'padding:.8rem;display:flex;flex-direction:column;gap:.5rem';
  const aiLabel = document.createElement('div');
  aiLabel.style.cssText = 'font-size:.72rem;color:var(--text-dim,#64748b);text-transform:uppercase;letter-spacing:.05em;font-weight:600';
  aiLabel.textContent = 'Ask Gator';
  aiSection.appendChild(aiLabel);
  const aiButtons = document.createElement('div');
  aiButtons.style.cssText = 'display:flex;gap:.4rem;flex-wrap:wrap';

  function _odAiAction(label, prompt) {
    const btn = document.createElement('button');
    btn.className = 'tp-ai-btn';
    btn.textContent = '✦ ' + label;
    btn.style.cssText = 'font-size:.78rem;padding:.3rem .6rem';
    btn.addEventListener('click', () => tpInjectAIPrompt(prompt));
    return btn;
  }

  const fileName = item.name;
  aiButtons.appendChild(_odAiAction('Summarize', `Summarize the file "${fileName}" from my OneDrive`));
  aiButtons.appendChild(_odAiAction('Key Points', `Extract the key points from "${fileName}" on OneDrive`));
  if (mime.includes('sheet') || mime.includes('excel') || item.name.endsWith('.xlsx') || item.name.endsWith('.csv')) {
    aiButtons.appendChild(_odAiAction('Analyze Data', `Analyze the data in "${fileName}" from OneDrive`));
  }
  if (mime.includes('presentation') || mime.includes('powerpoint') || item.name.endsWith('.pptx')) {
    aiButtons.appendChild(_odAiAction('Slide Notes', `Give me the slide-by-slide notes from "${fileName}" on OneDrive`));
  }
  aiSection.appendChild(aiButtons);
  detail.appendChild(aiSection);

  // Right-click on detail → context menu
  detail.addEventListener('contextmenu', e => {
    if (e.target.closest('.tp-ai-btn, .pin-ctx-btn')) return;
    e.preventDefault();
    _odShowContextMenu(e.clientX, e.clientY, item);
  });
}

/* ── Right-click context menu ─────────────────────────────── */

function _odShowContextMenu(x, y, item) {
  document.getElementById('od-ctx-menu')?.remove();

  const menu = document.createElement('div');
  menu.id = 'od-ctx-menu';
  menu.className = 'od-ctx-menu';
  Object.assign(menu.style, {
    position: 'fixed',
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    boxShadow: '0 4px 16px rgba(0,0,0,.2)',
    padding: '0',
    zIndex: '9999',
    minWidth: '160px',
    overflow: 'hidden',
  });

  const _odCtxStyle = {
    display: 'flex', alignItems: 'center', gap: '.4rem',
    padding: '.45rem .75rem', boxSizing: 'border-box', margin: '0',
    background: 'none', border: 'none', cursor: 'pointer',
    fontSize: '.82rem', color: 'var(--text)', textAlign: 'left',
    fontFamily: 'inherit', whiteSpace: 'nowrap', width: '100%',
  };
  function _odCtxHover(btn, hoverBg) {
    btn.addEventListener('mouseenter', () => { btn.style.background = hoverBg || 'var(--surface2)'; });
    btn.addEventListener('mouseleave', () => { btn.style.background = 'none'; });
  }

  const pinned = _isPinned('onedrive', String(item.id));
  const pinBtn = document.createElement('button');
  pinBtn.className = 'od-ctx-item';
  Object.assign(pinBtn.style, _odCtxStyle);
  pinBtn.textContent = pinned ? '\u2715 Unpin from Chat' : '\uD83D\uDCCC Pin to Chat';
  _odCtxHover(pinBtn);
  pinBtn.addEventListener('click', () => {
    menu.remove();
    _togglePin('onedrive', String(item.id), item.name, { file_path: item.path || item.name, web_url: item.web_url || '', drive_id: item.drive_id || '' });
  });
  menu.appendChild(pinBtn);

  if (item.web_url) {
    const copyBtn = document.createElement('button');
    copyBtn.className = 'od-ctx-item';
    Object.assign(copyBtn.style, _odCtxStyle);
    copyBtn.textContent = '\uD83D\uDCCB Copy link';
    _odCtxHover(copyBtn);
    copyBtn.addEventListener('click', async () => {
      menu.remove();
      await navigator.clipboard.writeText(item.web_url).catch(() => {});
    });
    menu.appendChild(copyBtn);
  }

  const renameBtn = document.createElement('button');
  renameBtn.className = 'od-ctx-item';
  Object.assign(renameBtn.style, _odCtxStyle);
  renameBtn.textContent = '\u270F\uFE0F Rename';
  _odCtxHover(renameBtn);
  renameBtn.addEventListener('click', () => { menu.remove(); _odPromptRename(item); });
  menu.appendChild(renameBtn);

  const sep = document.createElement('div');
  Object.assign(sep.style, { height: '1px', background: 'var(--border)', margin: '0' });
  menu.appendChild(sep);

  const deleteBtn = document.createElement('button');
  deleteBtn.className = 'od-ctx-item od-ctx-delete';
  Object.assign(deleteBtn.style, { ..._odCtxStyle, color: 'var(--warn, #f87171)' });
  deleteBtn.textContent = '\uD83D\uDDD1 Delete';
  _odCtxHover(deleteBtn, 'rgba(248,113,113,.08)');
  deleteBtn.addEventListener('click', () => { menu.remove(); _odDeleteItem(item); });
  menu.appendChild(deleteBtn);

  document.body.appendChild(menu);
  const rect = menu.getBoundingClientRect();
  menu.style.left = Math.min(x, window.innerWidth - rect.width - 8) + 'px';
  menu.style.top = Math.min(y, window.innerHeight - rect.height - 8) + 'px';

  const dismiss = e => {
    if (e.type === 'keydown' && e.key !== 'Escape') return;
    menu.remove();
    document.removeEventListener('click', dismiss);
    document.removeEventListener('keydown', dismiss);
  };
  setTimeout(() => {
    document.addEventListener('click', dismiss);
    document.addEventListener('keydown', dismiss);
  }, 0);
}

function _odPromptRename(item) {
  // Remove any existing rename modal
  document.getElementById('od-rename-modal')?.remove();

  const pane = document.getElementById('third-pane');
  const overlay = document.createElement('div');
  overlay.id = 'od-rename-modal';
  overlay.className = 'od-rename-overlay';

  const box = document.createElement('div');
  box.className = 'od-rename-box';
  box.innerHTML = `
    <div class="od-rename-title">Rename</div>
    <div class="od-rename-current">${escapeHtml(item.name)}</div>
  `;

  const inp = document.createElement('input');
  inp.type = 'text';
  inp.className = 'od-rename-field';
  inp.value = item.name;
  inp.maxLength = 255;
  box.appendChild(inp);

  const err = document.createElement('div');
  err.className = 'od-rename-err';
  box.appendChild(err);

  const actions = document.createElement('div');
  actions.className = 'od-rename-actions';

  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'tp-ai-btn secondary';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.addEventListener('click', () => overlay.remove());

  const saveBtn = document.createElement('button');
  saveBtn.className = 'tp-ai-btn';
  saveBtn.textContent = 'Rename';

  actions.appendChild(cancelBtn);
  actions.appendChild(saveBtn);
  box.appendChild(actions);
  overlay.appendChild(box);
  pane.appendChild(overlay);

  // Select filename without extension for convenience
  const dotIdx = item.name.lastIndexOf('.');
  if (dotIdx > 0) inp.setSelectionRange(0, dotIdx);
  else inp.select();
  inp.focus();

  async function doRename() {
    const newName = inp.value.trim();
    err.textContent = '';
    if (!newName) { err.textContent = 'Name cannot be empty.'; return; }
    if (newName === item.name) { overlay.remove(); return; }
    saveBtn.disabled = true;
    cancelBtn.disabled = true;
    saveBtn.textContent = 'Renaming…';
    try {
      const driveId = _odState.currentDriveId || item.drive_id;
      const renameUrl = driveId
        ? `/api/onedrive/items/${encodeURIComponent(item.id)}?drive_id=${encodeURIComponent(driveId)}`
        : `/api/onedrive/items/${encodeURIComponent(item.id)}`;
      const res = await fetch(renameUrl, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
      _odState.folderCache.delete(_odCacheKey(_odState.selectedFolderId));
      overlay.remove();
      _odOpenSection(_odState.section);
    } catch (e) {
      err.textContent = e.message;
      saveBtn.disabled = false;
      cancelBtn.disabled = false;
      saveBtn.textContent = 'Rename';
      inp.focus();
    }
  }

  saveBtn.addEventListener('click', doRename);
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); doRename(); }
    if (e.key === 'Escape') { e.stopPropagation(); overlay.remove(); }
  });
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}

async function _odDeleteItem(item) {
  const label = item.is_folder ? 'folder' : 'file';
  if (!confirm(`Delete ${label} "${item.name}"? This cannot be undone.`)) return;
  const driveId = _odState.currentDriveId || item.drive_id;
  const deleteUrl = driveId
    ? `/api/onedrive/items/${encodeURIComponent(item.id)}?drive_id=${encodeURIComponent(driveId)}`
    : `/api/onedrive/items/${encodeURIComponent(item.id)}`;
  try {
    const res = await fetch(deleteUrl, { method: 'DELETE' });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
    _odState.folderCache.delete(_odCacheKey(_odState.selectedFolderId));
    tpState.selectedId = null;
    await _odOpenSection(_odState.section);
  } catch (err) {
    _showAlert('Delete failed: ' + err.message, 'error');
  }
}

function _buildCollapsibleUploadZone(container, folderId, fileListEl) {
  const footer = document.createElement('div');
  footer.className = 'od-upload-footer';

  // Toggle handle (36px strip — always visible)
  const handle = document.createElement('div');
  handle.className = 'od-upload-handle';
  handle.setAttribute('role', 'button');
  handle.setAttribute('aria-expanded', 'true');
  handle.innerHTML = `<span style="font-size:.9rem">☁</span><span>Upload files</span><span class="od-upload-chevron">▲</span>`;
  footer.appendChild(handle);
  footer.classList.add('expanded');

  // Collapsible body (expanded by default)
  const body = document.createElement('div');
  body.className = 'od-upload-body';

  const dropZone = document.createElement('div');
  dropZone.className = 'od-drop-zone';
  dropZone.innerHTML = `
    <div class="od-drop-icon">☁️</div>
    <div class="od-drop-text">Drop files here or <label class="od-browse-link">browse<input type="file" multiple style="display:none"></label></div>
    <div class="od-drop-hint">Any file type · No size limit</div>
  `;
  body.appendChild(dropZone);

  const queue = document.createElement('div');
  queue.className = 'od-upload-queue';
  body.appendChild(queue);

  // Storage quota — shown here (in the upload zone) since it's most relevant
  // while uploading. Moved out of the nav sidebar.
  const quotaWrap = document.createElement('div');
  quotaWrap.className = 'od-quota-wrap od-quota-in-upload';
  body.appendChild(quotaWrap);
  _renderOdQuota(quotaWrap);

  footer.appendChild(body);
  container.appendChild(footer);

  // Hidden file inputs exposed for the "+ New" menu
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.multiple = true;
  fileInput.style.display = 'none';
  footer.appendChild(fileInput);

  const dirInput = document.createElement('input');
  dirInput.type = 'file';
  dirInput.multiple = true;
  dirInput.webkitdirectory = true;
  dirInput.style.display = 'none';
  footer.appendChild(dirInput);

  // Expose inputs so _odTriggerUpload() can find them
  footer._fileInput = fileInput;
  footer._dirInput = dirInput;

  function addFiles(files) {
    expand();
    [...files].forEach(f => _odUploadFile(f, folderId, queue, fileListEl));
  }

  function expand() {
    footer.classList.add('expanded');
    handle.setAttribute('aria-expanded', 'true');
  }
  function collapse() {
    if (queue.children.length === 0) {
      footer.classList.remove('expanded');
      handle.setAttribute('aria-expanded', 'false');
    }
  }

  handle.addEventListener('click', () => {
    if (footer.classList.contains('expanded')) collapse();
    else expand();
  });

  // Browse via label input
  dropZone.querySelector('label input[type=file]').addEventListener('change', e => {
    addFiles(e.target.files);
    e.target.value = '';
  });

  // Hidden file input (triggered by "+ New" menu)
  fileInput.addEventListener('change', e => { addFiles(e.target.files); e.target.value = ''; });
  dirInput.addEventListener('change', e => { addFiles(e.target.files); e.target.value = ''; });

  // Drop zone drag & drop
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    addFiles(e.dataTransfer.files);
  });

  // Auto-expand on drag anywhere over the right pane
  const detailCol = container;
  let dragCounter = 0;
  detailCol.addEventListener('dragenter', e => {
    if (!e.dataTransfer.types.includes('Files')) return;
    dragCounter++;
    handle.classList.add('drag-active');
    expand();
  });
  detailCol.addEventListener('dragleave', () => {
    dragCounter = Math.max(0, dragCounter - 1);
    if (dragCounter === 0) {
      handle.classList.remove('drag-active');
      collapse();
    }
  });
  detailCol.addEventListener('drop', () => {
    dragCounter = 0;
    handle.classList.remove('drag-active');
  });
}

// Called by the "+ New" menu items — finds the footer in tp-detail-col and triggers the right input
function _odTriggerUpload(isFolder) {
  const detail = document.getElementById('tp-detail-col');
  const footer = detail.querySelector('.od-upload-footer');
  if (!footer) return;
  footer.classList.add('expanded');
  footer.querySelector('.od-upload-handle').setAttribute('aria-expanded', 'true');
  if (isFolder) footer._dirInput?.click();
  else footer._fileInput?.click();
}

async function _odUploadFile(file, folderId, queueEl, fileListEl) {
  const item = document.createElement('div');
  item.className = 'od-queue-item';
  item.innerHTML = `
    <span class="od-item-icon">${_odMimeIcon(file.type, false)}</span>
    <div class="od-queue-info">
      <span class="od-queue-name">${escapeHtml(file.name)}</span>
      <span class="od-queue-size">${_formatBytes(file.size)}</span>
      <div class="od-progress-bar"><div class="od-progress-fill" style="width:0%"></div></div>
    </div>
  `;
  queueEl.appendChild(item);

  const fill = item.querySelector('.od-progress-fill');

  try {
    // Animate indeterminate progress while uploading
    fill.style.width = '30%';
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`/api/onedrive/upload/${encodeURIComponent(folderId)}`, { method: 'POST', body: fd });
    fill.style.width = '100%';
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.status);

    // Success state
    item.querySelector('.od-progress-bar').remove();
    const successRow = document.createElement('div');
    successRow.className = 'od-success-row';
    successRow.innerHTML = `
      <span class="od-success-check">✓ Uploaded</span>
      <button class="tp-ai-btn od-copy-btn" data-url="${escapeHtml(data.url)}" style="font-size:.7rem;padding:.2rem .5rem">📋 Copy link</button>
      <a href="${escapeHtml(data.url)}" target="_blank" class="tp-ai-btn secondary" style="font-size:.7rem;padding:.2rem .5rem;text-decoration:none">↗ Open</a>
    `;
    item.querySelector('.od-queue-info').appendChild(successRow);

    successRow.querySelector('.od-copy-btn').addEventListener('click', async e => {
      await navigator.clipboard.writeText(e.target.dataset.url).catch(() => {});
      const orig = e.target.textContent;
      e.target.textContent = '✓ Copied!';
      setTimeout(() => { e.target.textContent = orig; }, 1800);
    });

    // Refresh left col so uploaded file appears in folder list
    _odState.folderCache.delete(_odCacheKey(folderId));
    const updated = await _fetchOneDriveFolder(folderId);
    if (tpState.type === 'onedrive' && _odState.selectedFolderId === folderId) {
      renderOneDriveList(updated);
    }
  } catch (e) {
    fill.style.width = '0%';
    fill.style.background = 'var(--warn, #f87171)';
    const errSpan = document.createElement('span');
    errSpan.style.cssText = 'font-size:.7rem;color:var(--warn,#f87171)';
    errSpan.textContent = '⚠ Failed: ' + e.message;
    item.querySelector('.od-queue-info').appendChild(errSpan);
  }
}

/* ── OneNote: fetch & render ────────────────────────────── */

function _onenoteErrMsg(e) {
  const msg = e.message || String(e);
  if (msg.includes('429')) return 'OneNote rate limit hit — please wait a moment and retry.';
  return msg;
}

async function _fetchOneNoteNotebooks() {
  const _cached = _getListCache('onenote');
  if (_cached) {
    tpState.list = _cached.data;
    tpState._onenoteLevel = 'notebooks';
    renderOneNoteList(tpState.list, 'notebooks');
    return;
  }
  _showSkeletons();
  try {
    const res = await fetch('/api/onenote/notebooks');
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
    const data = await res.json();
    if (tpState.type !== 'onenote') return;
    tpState.list = data.notebooks || [];
    tpState._onenoteLevel = 'notebooks';
    _setListCache('onenote', tpState.list);
    renderOneNoteList(tpState.list, 'notebooks');
  } catch (e) {
    if (tpState.type !== 'onenote') return;
    _showListError('Could not load notebooks: ' + _onenoteErrMsg(e), _fetchOneNoteNotebooks);
  }
}

async function _fetchOneNoteSections(notebookId, notebookName) {
  _showSkeletons();
  try {
    const res = await fetch(`/api/onenote/notebooks/${encodeURIComponent(notebookId)}/sections`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
    const data = await res.json();
    tpState.list = data.sections || [];
    tpState._onenoteLevel = 'sections';
    tpState._onenoteBreadcrumb = [{ level: 'notebooks', label: 'Notebooks' }];
    tpState._onenoteParent = { id: notebookId, name: notebookName };
    renderOneNoteList(tpState.list, 'sections');
  } catch (e) {
    _showListError('Could not load sections: ' + _onenoteErrMsg(e), () => _fetchOneNoteSections(notebookId, notebookName));
  }
}

async function _fetchOneNotePages(sectionId, sectionName) {
  _showSkeletons();
  try {
    const res = await fetch(`/api/onenote/sections/${encodeURIComponent(sectionId)}/pages`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
    const data = await res.json();
    tpState.list = data.pages || [];
    tpState._onenoteLevel = 'pages';
    tpState._onenoteBreadcrumb.push({
      level: 'sections',
      label: tpState._onenoteParent?.name || 'Sections',
      parentId: tpState._onenoteParent?.id,
      parentName: tpState._onenoteParent?.name,
    });
    tpState._onenoteParent = { id: sectionId, name: sectionName };
    renderOneNoteList(tpState.list, 'pages');
  } catch (e) {
    _showListError('Could not load pages: ' + _onenoteErrMsg(e), () => _fetchOneNotePages(sectionId, sectionName));
  }
}

function renderOneNoteList(items, level) {
  // Restore list/detail split if we were in full-page mode
  _onenoteBackToList && document.getElementById('tp-list-col')?.classList.remove('tp-onenote-hidden');
  document.getElementById('tp-list-resize')?.classList.remove('tp-onenote-hidden');
  document.getElementById('tp-detail-col')?.classList.remove('tp-onenote-full');

  const col = document.getElementById('tp-list-col');
  col.innerHTML = '';

  // Back button (except at notebooks level)
  if (level !== 'notebooks' && tpState._onenoteBreadcrumb?.length) {
    const backBtn = document.createElement('button');
    backBtn.className = 'tp-breadcrumb';
    const prev = tpState._onenoteBreadcrumb[tpState._onenoteBreadcrumb.length - 1];
    backBtn.innerHTML = `<span class="tp-breadcrumb-arrow">\u2190</span> ${escapeHtml(prev.label)}`;
    backBtn.addEventListener('click', () => {
      tpState._onenoteBreadcrumb.pop();
      if (prev.level === 'notebooks') {
        _fetchOneNoteNotebooks();
      } else if (prev.level === 'sections') {
        _fetchOneNoteSections(prev.parentId, prev.parentName);
      }
    });
    col.appendChild(backBtn);
  }

  // Header
  const header = document.createElement('div');
  header.className = 'tp-list-header';
  const levelLabel = level === 'notebooks' ? 'Notebooks' : level === 'sections' ? 'Sections' : 'Pages';
  const parentName = tpState._onenoteParent?.name;
  header.innerHTML = `<div class="tp-filter-tabs"><span class="tp-onenote-header-label">${escapeHtml(parentName ? parentName + ' \u203A ' + levelLabel : levelLabel)} <span class="tp-onenote-count">(${items.length})</span></span></div>`;

  col.appendChild(header);

  // Wire shared "+" button at pages level
  const _addBtn = document.getElementById('tp-add-btn');
  if (_addBtn) {
    if (level === 'pages' && tpState._onenoteParent?.id) {
      _addBtn.style.display = '';
      _addBtn.onclick = () => _showNewOneNotePage(tpState._onenoteParent.id);
    } else {
      _addBtn.style.display = 'none';
    }
  }

  const scroll = document.createElement('div');
  scroll.className = 'tp-list-scroll';
  col.appendChild(scroll);

  if (!items.length) {
    scroll.innerHTML = `<div class="tp-empty-state" style="height:120px"><span>No ${levelLabel.toLowerCase()}</span></div>`;
    return;
  }

  const q = tpState.searchQuery.toLowerCase();
  const filtered = q
    ? items.filter(item => ((item.name || item.title || '').toLowerCase().includes(q)))
    : items;

  filtered.forEach((item, idx) => {
    const el = document.createElement('div');
    el.className = 'tp-list-item' + (item.id === tpState.selectedId ? ' active' : '');
    el.dataset.idx = idx;
    el.dataset.id = item.id;

    const name = item.name || item.title || '(untitled)';
    const time = relativeTime(item.modified || item.created || '');
    const icon = level === 'notebooks' ? '📓' : level === 'sections' ? '📑' : '📄';

    el.innerHTML = `
      <div class="tp-avatar tp-avatar-onenote">${icon}</div>
      <div class="tp-item-body">
        <div class="tp-item-name">${escapeHtml(name)}</div>
        ${time ? `<div class="tp-item-preview">${time}</div>` : ''}
      </div>
      ${level !== 'pages' ? '<div class="tp-item-meta"><span class="tp-onenote-chevron">\u203A</span></div>' : ''}`;

    if (level === 'pages') {
      el.appendChild(_createPinBtn('onenote', item.id, name, {
        notebook: tpState._onenoteBreadcrumb?.[0]?.parentName || '',
        section: tpState._onenoteParent?.name || ''
      }));
    }
    el.addEventListener('click', () => {
      if (level === 'notebooks') _fetchOneNoteSections(item.id, name);
      else if (level === 'sections') _fetchOneNotePages(item.id, name);
      else if (level === 'pages') tpLoadDetail(item.id);
    });
    // Right-click to pin notebooks and sections
    if (level !== 'pages') {
      el.addEventListener('contextmenu', e => {
        const pinId = String(item.id);
        const isPinned = _isPinned('onenote', pinId);
        const _pinMeta = level === 'notebooks'
          ? { type: 'notebook' }
          : { type: 'section', notebook: tpState._onenoteParent?.name || '' };
        _showCtxMenu(e, [{
          icon: '📌', label: isPinned ? 'Unpin from Chat' : 'Pin to Chat',
          action: async () => {
            await _togglePin('onenote', pinId, name, _pinMeta);
            if (typeof _refreshPinOrb === 'function') _refreshPinOrb();
          },
        }]);
      });
    }
    scroll.appendChild(el);
  });
}

async function _loadOneNotePageDetail(pageId) {
  // Expand detail to full pane (hide left column incl. toolbar)
  const listCol = document.getElementById('tp-left-col') || document.getElementById('tp-list-col');
  const listResize = document.getElementById('tp-list-resize');
  if (listCol) listCol.classList.add('tp-onenote-hidden');
  if (listResize) listResize.classList.add('tp-onenote-hidden');

  const col = document.getElementById('tp-detail-col');
  col.classList.add('tp-onenote-full');
  col.innerHTML = '<div class="tp-empty-state"><span>Loading\u2026</span></div>';

  try {
    const res = await fetch(`/api/onenote/pages/${encodeURIComponent(pageId)}`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
    const page = await res.json();
    _renderOneNotePageDetail(page);
  } catch (e) {
    col.innerHTML = `<div class="tp-empty-state"><span>Could not load page: ${escapeHtml(e.message)}</span>
      <button class="tp-ai-btn" onclick="_loadOneNotePageDetail('${escapeHtml(pageId)}')">Retry</button></div>`;
  }
}

function _onenoteBackToList() {
  // Restore list/detail split
  const listCol = document.getElementById('tp-left-col') || document.getElementById('tp-list-col');
  const listResize = document.getElementById('tp-list-resize');
  const detailCol = document.getElementById('tp-detail-col');
  if (listCol) listCol.classList.remove('tp-onenote-hidden');
  if (listResize) listResize.classList.remove('tp-onenote-hidden');
  if (detailCol) detailCol.classList.remove('tp-onenote-full');
  tpState.selectedId = null;
  detailCol.innerHTML = _gatorDetailHint('onenote');
}

function _renderOneNotePageDetail(page) {
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = '';

  // Header (title + modified) \u2014 back now lives in the main toolbar (spec.back).
  const header = document.createElement('div');
  header.className = 'tp-email-header';
  header.innerHTML = `
    <div class="tp-email-subject">${escapeHtml(page.title || '(untitled)')}</div>
    <div class="tp-email-meta-row">
      <span class="tp-email-meta-label">Modified</span>
      <span class="tp-email-meta-value">${page.modified ? new Date(page.modified).toLocaleString() : ''}</span>
    </div>`;
  col.appendChild(header);

  // Standardized toolbar in the persistent header (#tp-detail-header). Back +
  // app actions; the page header, body iframe and append area stay in content.
  {
    const _bodyText = page.body_html ? page.body_html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 800) : '';
    const _bc = tpState._onenoteBreadcrumb || [];
    const _nbName = (_bc.length >= 2 ? _bc[1].parentName : null) || (_bc.length >= 1 ? _bc[0].parentName : null) || tpState._onenoteParent?.name || '';
    const _secName = tpState._onenoteParent?.name || '';
    const _onPin = _createPinBtn('onenote', page.id, page.title, { notebook: _nbName, section: _secName });
    tpBuildDetailToolbar({
      app: 'onenote',
      back: { title: 'Back to pages', onClick: _onenoteBackToList },
      title: { text: page.title || '(untitled)', title: page.title || '' },
      actions: [
        { kind: 'icon', iconHtml: '\u2726', title: 'Ask Gator about this page', group: 0,
          onClick: () => tpInjectAIPrompt(`Here is my OneNote page titled "${page.title}":\n\n${_bodyText}\n\nWhat would you like to know or do with this page?`) },
        { kind: 'icon', iconHtml: _TP_EXT_LINK_SVG, title: 'Open in OneNote', group: 1,
          onClick: () => { if (page.url) window.open(page.url, '_blank'); else _showAlert('No web URL available \u2014 use Append below to add content.', 'info'); } },
        { el: _onPin, kind: 'icon', title: 'Pin page', group: 1 },
      ],
    });
  }

  // Body (iframe)
  const bodyWrap = document.createElement('div');
  bodyWrap.className = 'tp-email-body-wrap';
  col.appendChild(bodyWrap);

  if (page.body_html) {
    const frame = document.createElement('iframe');
    frame.className = 'tp-email-body-frame';
    frame.setAttribute('sandbox', 'allow-same-origin');
    frame.title = 'OneNote page content';
    bodyWrap.appendChild(frame);

    requestAnimationFrame(() => {
      const doc = frame.contentDocument || frame.contentWindow?.document;
      if (!doc) return;
      doc.open();
      doc.write(`<!DOCTYPE html><html><head><meta charset="utf-8">
        <style>body{font-family:-apple-system,'Segoe UI',sans-serif;font-size:13px;color:#1a1a1a;background:#fff;padding:1rem 1.2rem;line-height:1.6;margin:0}
        a{color:#0066cc}img{max-width:100%;height:auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:4px 8px}
        pre{white-space:pre-wrap;font-size:12px}div{position:static !important}</style>
      </head><body>${page.body_html}</body></html>`);
      doc.close();
      // Intercept link clicks from parent
      doc.addEventListener('click', e => {
        const a = e.target.closest('a[href]');
        if (a) { e.preventDefault(); window.open(a.href, '_blank', 'noopener'); }
      });
      try {
        const resize = () => { const h = doc.body.scrollHeight; if (h) frame.style.height = h + 24 + 'px'; };
        resize();
        setTimeout(resize, 500);
      } catch {}
    });
  } else {
    bodyWrap.innerHTML = '<div style="padding:1rem;color:var(--text-sub);font-size:.82rem">(No content)</div>';
  }

  // Append compose area
  const appendArea = document.createElement('div');
  appendArea.className = 'tp-onenote-append';
  appendArea.innerHTML = `
    <textarea class="tp-onenote-append-input" placeholder="Add to this page\u2026" rows="2"></textarea>
    <div class="tp-onenote-append-actions">
      <button class="tp-ai-btn" id="tp-onenote-append-send" disabled>Append</button>
      <span class="tp-onenote-append-status hidden" id="tp-onenote-append-status"></span>
    </div>`;
  col.appendChild(appendArea);

  const appendInput = appendArea.querySelector('.tp-onenote-append-input');
  const appendBtn = appendArea.querySelector('#tp-onenote-append-send');
  const appendStatus = appendArea.querySelector('#tp-onenote-append-status');

  appendInput.addEventListener('input', () => { appendBtn.disabled = !appendInput.value.trim(); });
  appendInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !appendBtn.disabled) { e.preventDefault(); appendBtn.click(); }
  });

  appendBtn.addEventListener('click', async () => {
    appendBtn.disabled = true;
    appendStatus.textContent = 'Saving\u2026';
    appendStatus.classList.remove('hidden');
    try {
      const res = await fetch(`/api/onenote/pages/${encodeURIComponent(page.id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body: appendInput.value.trim() }),
      });
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || res.status); }
      appendStatus.textContent = 'Saved!';
      appendInput.value = '';
      // Reload to show updated content
      setTimeout(() => _loadOneNotePageDetail(page.id), 800);
    } catch (e) {
      appendStatus.textContent = 'Error: ' + e.message;
      appendBtn.disabled = false;
    }
  });

  // (Ask/Edit/Pin handlers are wired in the tpBuildDetailToolbar spec above.)
}

function _showNewOneNotePage(sectionId) {
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = '';
  const wrapper = document.createElement('div');
  wrapper.className = 'tp-new-compose';
  wrapper.innerHTML = `
    <div class="tp-new-compose-header">New Page</div>
    <div class="tp-new-compose-to">
      <label>Title:</label>
      <input type="text" class="tp-new-compose-to-input" id="tp-on-title" placeholder="Page title" autocomplete="off">
    </div>
    <textarea class="tp-new-compose-msg" id="tp-on-body" placeholder="Page content\u2026" rows="8"></textarea>
    <div class="tp-new-compose-actions">
      <button class="tp-ai-btn tp-new-compose-send" id="tp-on-send" disabled>Create</button>
    </div>
    <div class="tp-new-compose-status hidden" id="tp-on-status"></div>`;
  col.appendChild(wrapper);

  const titleIn = wrapper.querySelector('#tp-on-title');
  const bodyIn = wrapper.querySelector('#tp-on-body');
  const sendBtn = wrapper.querySelector('#tp-on-send');
  const statusEl = wrapper.querySelector('#tp-on-status');

  const update = () => { sendBtn.disabled = !titleIn.value.trim(); };
  titleIn.addEventListener('input', update);

  sendBtn.addEventListener('click', async () => {
    sendBtn.disabled = true;
    statusEl.textContent = 'Creating\u2026';
    statusEl.classList.remove('hidden');
    try {
      const res = await fetch(`/api/onenote/sections/${encodeURIComponent(sectionId)}/pages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: titleIn.value.trim(), body: bodyIn.value || '' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed');
      statusEl.textContent = 'Created!';
      setTimeout(() => _fetchOneNotePages(sectionId, tpState._onenoteParent?.name || 'Section'), 500);
    } catch (e) {
      statusEl.textContent = 'Error: ' + e.message;
      sendBtn.disabled = false;
    }
  });

  titleIn.focus();
}

/* ── New Email compose ──────────────────────────────────── */

function _showNewEmailCompose(prefill) {
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = '';
  try { localStorage.removeItem('draft_email_new'); localStorage.removeItem('draft_email_new_meta'); } catch {}

  const wrapper = document.createElement('div');
  wrapper.className = 'tp-new-compose';

  // Context note (why Claude drafted this)
  if (prefill?.context) {
    const ctx = document.createElement('div');
    ctx.className = 'tc-compose-context';
    ctx.textContent = prefill.context;
    wrapper.appendChild(ctx);
  }

  // Toggle toolbar + to X
  const _emailAddBtn = document.getElementById('tp-add-btn');
  if (_emailAddBtn) {
    _emailAddBtn.dataset.composing = '1';
    _emailAddBtn.innerHTML = _TP_CLOSE_SVG;
    _emailAddBtn.title = 'Close compose';
  }

  function _discardCompose() {
    const detailCol = document.getElementById('tp-detail-col');
    detailCol.innerHTML = '';
    if (tpState.selectedId) {
      tpLoadDetail(tpState.selectedId);
    } else {
      detailCol.innerHTML = _gatorDetailHint('email');
      _resetDetailHeader();
    }
    // Reset toolbar + button
    const _btn = document.getElementById('tp-add-btn');
    if (_btn) { _btn.dataset.composing = ''; _btn.innerHTML = _TP_PLUS_SVG; _btn.title = 'Compose email'; }
  }

  // Replace the persistent header (avatar/name/folder icons) with the compose
  // title + X — irrelevant action icons get hidden while drafting.
  _setComposeDetailHeader(prefill ? 'Draft Email' : 'New Email', _discardCompose);

  // To field (required)
  const toField = _buildRecipientField({
    label: 'To:', chipClass: 'chip-email', avatarClass: 'tp-avatar-email',
    onchange: updateSendState,
  });
  wrapper.appendChild(toField.rowEl);

  // CC / BCC toggle row
  const ccToggleRow = document.createElement('div');
  ccToggleRow.className = 'tp-cc-toggle-row';
  ccToggleRow.innerHTML = `<button class="tp-cc-toggle-btn" id="tp-cc-toggle">CC</button>
    <button class="tp-cc-toggle-btn" id="tp-bcc-toggle">BCC</button>`;
  wrapper.appendChild(ccToggleRow);

  // CC field (hidden by default)
  const ccField = _buildRecipientField({
    label: 'CC:', chipClass: 'chip-email', avatarClass: 'tp-avatar-email',
    onchange: updateSendState,
  });
  ccField.rowEl.classList.add('hidden');
  wrapper.appendChild(ccField.rowEl);

  // BCC field (hidden by default)
  const bccField = _buildRecipientField({
    label: 'BCC:', chipClass: 'chip-email', avatarClass: 'tp-avatar-email',
    onchange: updateSendState,
  });
  bccField.rowEl.classList.add('hidden');
  wrapper.appendChild(bccField.rowEl);

  // CC/BCC toggles
  ccToggleRow.querySelector('#tp-cc-toggle').addEventListener('click', () => {
    const hidden = ccField.rowEl.classList.toggle('hidden');
    if (!hidden) { ccField.focusInput(); }
  });
  ccToggleRow.querySelector('#tp-bcc-toggle').addEventListener('click', () => {
    const hidden = bccField.rowEl.classList.toggle('hidden');
    if (!hidden) { bccField.focusInput(); }
  });

  // Subject field
  const subjectRow = document.createElement('div');
  subjectRow.className = 'tp-new-compose-to';
  subjectRow.innerHTML = `<label>Subject:</label>
    <div class="tp-compose-chips-wrap">
      <input type="text" class="tp-new-compose-to-input" id="tp-email-compose-subject" placeholder="Subject" autocomplete="off">
    </div>`;
  wrapper.appendChild(subjectRow);
  const subjectInput = subjectRow.querySelector('#tp-email-compose-subject');

  // Rich text body — use Quill for plain text, contenteditable for HTML (tables etc.)
  const useHtmlEditor = !!(prefill && prefill.body_html);
  const editor = useHtmlEditor
    ? _buildHtmlEditor({ placeholder: 'Write your message…', html: prefill.body_html })
    : _buildQuillEditor({ placeholder: 'Write your message…', showResize: false });
  wrapper.appendChild(editor.wrapEl);

  // Attachment zone
  const attach = _buildAttachmentZone();
  wrapper.appendChild(attach.zoneEl);

  // Wire paperclip button (added after Quill init)
  setTimeout(() => {
    const clipBtn = editor.wrapEl.querySelector('.tp-qt-attach-btn');
    if (clipBtn) clipBtn.addEventListener('click', () => attach.fileInputEl.click());
  }, 50);

  // Drag-and-drop onto entire compose wrapper
  _wireDragDrop(wrapper, attach.addFiles);

  const statusEl = document.createElement('div');
  statusEl.className = 'tp-new-compose-status hidden';
  wrapper.appendChild(statusEl);
  col.appendChild(wrapper);

  // Add Discard button into the Quill editor toolbar, next to Send
  const sendBtn = editor.wrapEl.querySelector('.tp-compose-send');
  if (sendBtn) {
    const discardBtn = document.createElement('button');
    discardBtn.className = 'tp-qt-btn';
    discardBtn.textContent = 'Discard';
    discardBtn.title = 'Discard draft';
    discardBtn.style.cssText = 'color:var(--text-sub);';
    discardBtn.addEventListener('click', _discardCompose);
    const _toolbar = sendBtn.closest('.tp-quill-toolbar');
    if (_toolbar) {
      const _sep = document.createElement('span');
      _sep.className = 'tp-qt-sep';
      _toolbar.insertBefore(_sep, _toolbar.firstChild);
      _toolbar.insertBefore(discardBtn, _toolbar.firstChild);
    }
  }

  // Draft restore for subject
  try {
    const d = JSON.parse(localStorage.getItem('draft_email_new_meta') || '{}');
    if (d.subject) subjectInput.value = d.subject;
  } catch {}

  // Draft save for subject on input
  subjectInput.addEventListener('input', _debounce(() => {
    try {
      const d = JSON.parse(localStorage.getItem('draft_email_new_meta') || '{}');
      d.subject = subjectInput.value;
      localStorage.setItem('draft_email_new_meta', JSON.stringify(d));
    } catch {}
  }, 800));

  function updateSendState() {
    if (sendBtn) sendBtn.disabled = !toField.getEmails() || editor.isEmpty();
  }

  function _wireEmailQuill() {
    if (useHtmlEditor) {
      // HTML editor: wire keydown + input on the contenteditable div
      const editableDiv = editor.wrapEl.querySelector('[contenteditable]');
      if (editableDiv) {
        editableDiv.addEventListener('input', updateSendState);
        editableDiv.addEventListener('keydown', e => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (sendBtn) sendBtn.click(); }
        });
      }
      return;
    }
    const q = editor.quill;
    if (!q) { setTimeout(_wireEmailQuill, 200); return; }
    q.on('text-change', updateSendState);
    q.root.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (sendBtn) sendBtn.click(); }
    });
    // Tab indent: email supports both bullet sub-indent and plain margin indent
    if (q.keyboard) {
      q.keyboard.bindings[9] = [];
      q.keyboard.bindings[9].push({ key: 9, shiftKey: false, handler() { this.quill.format('indent', '+1'); return false; } });
      q.keyboard.bindings[9].push({ key: 9, shiftKey: true,  handler() { this.quill.format('indent', '-1'); return false; } });
    }
    _wireMentionDropdownQuill(q, q.root);
  }
  setTimeout(_wireEmailQuill, 150);

  if (sendBtn) sendBtn.addEventListener('click', async () => {
    const to = toField.getEmails();
    if (!to || editor.isEmpty()) return;
    sendBtn.disabled = true;
    statusEl.classList.remove('hidden');
    const gatorStatus = _gatorSendStatus(statusEl);
    try {
      // Read attachments as base64
      const attachments = await Promise.all(attach.files.map(async f => ({
        name: f.name,
        contentType: f.type || 'application/octet-stream',
        contentBytes: await _fileToBase64(f),
      })));

      const res = await fetch('/api/email/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          to,
          cc: ccField.getEmails(),
          bcc: bccField.getEmails(),
          subject: subjectInput.value.trim() || '(no subject)',
          body: _emailIndentForOutlook(editor.getHtml()),
          attachments,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed');
      editor.clearDraft();
      try { localStorage.removeItem('draft_email_new_meta'); } catch {}
      gatorStatus.success('Email delivered!');
      setTimeout(() => {
        _fetchEmailList();
        const detailCol = document.getElementById('tp-detail-col');
        detailCol.innerHTML = '';
        const empty = document.createElement('div');
        empty.className = 'tp-empty-state';
        empty.innerHTML = `<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".3"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg><span>Email sent</span>`;
        detailCol.appendChild(empty);
      }, 1500);
    } catch (e) {
      gatorStatus.fail(e.message);
      sendBtn.disabled = false;
    }
  });

  // Pre-fill from Claude draft
  if (prefill) {
    const preEmails = (prefill.to || '').split(',').map(s => s.trim()).filter(Boolean);
    const preNames = (prefill.to_names || '').split(',').map(s => s.trim());
    preEmails.forEach((email, i) => {
      toField.addPerson({ email, name: preNames[i] || email.split('@')[0] });
    });
    if (prefill.cc) {
      ccField.rowEl.classList.remove('hidden');
      prefill.cc.split(',').map(s => s.trim()).filter(Boolean).forEach(email => {
        ccField.addPerson({ email, name: email.split('@')[0] });
      });
    }
    if (prefill.bcc) {
      bccField.rowEl.classList.remove('hidden');
      prefill.bcc.split(',').map(s => s.trim()).filter(Boolean).forEach(email => {
        bccField.addPerson({ email, name: email.split('@')[0] });
      });
    }
    if (prefill.subject) subjectInput.value = prefill.subject;
    // Pre-fill body after init — must run AFTER _wireEmailQuill (150ms)
    setTimeout(() => {
      if (!useHtmlEditor && editor.quill && prefill.body) {
        editor.quill.setText(prefill.body);
      }
      updateSendState();
    }, 200);
  } else {
    toField.focusInput();
  }
}

/* ── Email: full-view reply / forward (#1 + #21) ───────── */
// mode: 'reply' | 'replyall' | 'forward'. Reuses the chip people-picker and a
// full-height layout; keeps the createReply/createReplyAll/createForward backend
// so conversation threading + the quoted original thread are preserved (#1).
function _showReplyForwardCompose(mode, email) {
  const isForward = mode === 'forward';
  const isReplyAll = mode === 'replyall';
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = '';

  const wrapper = document.createElement('div');
  wrapper.className = 'tp-new-compose tp-rf-compose';

  function _discard() {
    const detailCol = document.getElementById('tp-detail-col');
    const _draft = detailCol && detailCol.querySelector('.ql-editor');
    if (_draft && (_draft.textContent || '').trim()) {
      if (!confirm('Discard unsaved reply?')) return;
    }
    detailCol.innerHTML = '';
    if (email && email.id) tpLoadDetail(email.id);
    else { detailCol.innerHTML = _gatorDetailHint('email'); _resetDetailHeader(); }
  }

  const title = isForward ? 'Forward' : (isReplyAll ? 'Reply All' : `Reply to ${email.from_name || email.from_email || ''}`);
  _setComposeDetailHeader(title, _discard, [
    { kind: 'ai', iconHtml: '✦', label: 'Draft with AI', title: 'Draft this reply with AI',
      onClick: () => tpInjectAIPrompt(`Draft a professional ${isForward ? 'forward note' : 'reply'} for this email:\nFrom: ${email.from_name}\nSubject: ${email.subject}\n\nTheir message: ${(email.body_text || '').slice(0, 800)}`) },
  ]);

  // Recipients (editable chip picker w/ people lookup) ──────
  const toField = _buildRecipientField({ label: 'To:', chipClass: 'chip-email', avatarClass: 'tp-avatar-email', onchange: () => updateSendState() });
  wrapper.appendChild(toField.rowEl);

  const ccToggleRow = document.createElement('div');
  ccToggleRow.className = 'tp-cc-toggle-row';
  ccToggleRow.innerHTML = `<button class="tp-cc-toggle-btn" id="tp-rf-cc-toggle">CC</button>
    <button class="tp-cc-toggle-btn" id="tp-rf-bcc-toggle">BCC</button>`;
  wrapper.appendChild(ccToggleRow);

  const ccField = _buildRecipientField({ label: 'CC:', chipClass: 'chip-email', avatarClass: 'tp-avatar-email', onchange: () => updateSendState() });
  ccField.rowEl.classList.add('hidden');
  wrapper.appendChild(ccField.rowEl);
  const bccField = _buildRecipientField({ label: 'BCC:', chipClass: 'chip-email', avatarClass: 'tp-avatar-email', onchange: () => updateSendState() });
  bccField.rowEl.classList.add('hidden');
  wrapper.appendChild(bccField.rowEl);

  ccToggleRow.querySelector('#tp-rf-cc-toggle').addEventListener('click', () => {
    const hidden = ccField.rowEl.classList.toggle('hidden');
    if (!hidden) ccField.focusInput();
  });
  ccToggleRow.querySelector('#tp-rf-bcc-toggle').addEventListener('click', () => {
    const hidden = bccField.rowEl.classList.toggle('hidden');
    if (!hidden) bccField.focusInput();
  });

  // Message editor — quoted original injected inside Quill so toolbar stays
  // pinned at the bottom and layout matches New Email UX
  const editor = _buildQuillEditor({ placeholder: isForward ? 'Add a message…' : 'Write your reply…', showResize: false });
  wrapper.appendChild(editor.wrapEl);

  // Inject quoted original into the Quill editor after it initialises
  function _injectQuoted() {
    const q = editor.quill;
    if (!q) { setTimeout(_injectQuoted, 150); return; }
    // Date: detail objects carry received_at (ISO); fall back to other shapes.
    const _rawWhen = email.received_at || email.received_label || email.received || email.date || '';
    let when = '';
    if (_rawWhen) {
      const d = new Date(_rawWhen);
      when = isNaN(d) ? String(_rawWhen)
        : d.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
    }
    const fromLabel = email.from_name || email.from_email || '';
    // "On <date>, <sender> wrote:" — omit the comma/parts that are missing so we
    // never render a dangling "On  wrote:" or "On <x> wrote:" with a stray gap.
    const _parts = [];
    if (when) _parts.push(when);
    if (fromLabel) _parts.push(fromLabel);
    const header = _parts.length ? `On ${_parts.join(', ')} wrote:` : 'Original message:';
    // Always use body_text — body_html includes full Outlook HTML (tables, inline styles,
    // background colors) that renders broken inside Quill's contenteditable
    const bodyHtml = `<blockquote style="border-left:3px solid var(--border2,#475569);margin:.6rem 0 0;padding:.3rem .7rem;color:var(--text-sub,#94a3b8);white-space:pre-wrap">${escapeHtml(email.body_text || '')}</blockquote>`;
    // Insert at end of editor: blank line, attribution, quoted body
    q.clipboard.dangerouslyPasteHTML(q.getLength() - 1,
      `<p><br></p><p><em>${escapeHtml(header)}</em></p>${bodyHtml}`
    );
    // Move cursor to top so user types above the quoted content
    q.setSelection(0, 0);
  }
  setTimeout(_injectQuoted, 200);

  const statusEl = document.createElement('div');
  statusEl.className = 'tp-new-compose-status hidden';
  wrapper.appendChild(statusEl);
  col.appendChild(wrapper);

  // Draft-with-AI lives in the compose header toolbar (see _setComposeDetailHeader
  // call above); Discard is the header ×. Nothing extra in the bottom toolbar.
  const sendBtn = editor.wrapEl.querySelector('.tp-compose-send');

  function updateSendState() {
    if (!sendBtn) return;
    // Forward requires a recipient; reply needs a body. createReply sets reply
    // recipients server-side, so reply stays sendable even before editing To.
    sendBtn.disabled = isForward ? (!toField.getEmails() || editor.isEmpty()) : editor.isEmpty();
  }

  function _wireQuill() {
    const q = editor.quill;
    if (!q) { setTimeout(_wireQuill, 150); return; }
    q.on('text-change', updateSendState);
    q.root.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (sendBtn) sendBtn.click(); }
    });
    // Email supports true paragraph indent (Outlook renders ql-indent → margin).
    // Tab always indents the current line; Shift+Tab outdents.
    if (q.keyboard) {
      q.keyboard.bindings[9] = [];
      q.keyboard.bindings[9].push({ key: 9, shiftKey: false, handler() { this.quill.format('indent', '+1'); return false; } });
      q.keyboard.bindings[9].push({ key: 9, shiftKey: true,  handler() { this.quill.format('indent', '-1'); return false; } });
    }
    // Ensure slot morph stays in sync on this Quill instance
    const _slot = editor.wrapEl.querySelector('.tp-quill-send-slot');
    if (_slot) {
      const _syncSlot = () => _slot.classList.toggle('has-text', q.getText().trim().length > 0);
      q.on('text-change', _syncSlot);
      _syncSlot();
    }
  }
  setTimeout(_wireQuill, 150);

  if (sendBtn) sendBtn.addEventListener('click', async () => {
    if (sendBtn.disabled) return;
    sendBtn.disabled = true;
    statusEl.classList.remove('hidden');
    const gatorStatus = _gatorSendStatus(statusEl);
    try {
      // Outlook has no Quill CSS: nest bullet lists AND convert plain-paragraph
      // ql-indent classes to inline margin-left so indentation renders.
      const bodyHtml = _emailIndentForOutlook(editor.getHtml());
      const endpoint = isForward ? '/api/email/forward' : '/api/email/reply';
      const payload = isForward
        ? { message_id: email.id, to: toField.getEmails(), cc: ccField.getEmails(), bcc: bccField.getEmails(), comment: bodyHtml }
        : { message_id: email.id, body: bodyHtml, reply_all: isReplyAll, to: toField.getEmails(), cc: ccField.getEmails(), bcc: bccField.getEmails() };
      const res = await fetch(endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || 'Send failed');
      gatorStatus.success(isForward ? 'Forwarded!' : 'Reply sent!');
      setTimeout(() => { _fetchEmailList(); _discard(); }, 1400);
    } catch (e) {
      gatorStatus.fail(e.message);
      sendBtn.disabled = false;
    }
  });

  // Prefill recipients per mode (editable — user can add/remove) ──
  const fromPerson = email.from_email ? { email: email.from_email, name: email.from_name || email.from_email } : null;
  if (!isForward && fromPerson) toField.addPerson(fromPerson, { notify: false });
  if (isReplyAll) {
    const _addCc = (self) => {
      _replyAllCcRecipients(email, self).forEach(p => {
        ccField.rowEl.classList.remove('hidden');
        ccField.addPerson(p, { notify: false });
      });
    };
    // Use cached self email if present; otherwise prefill now and refine once the
    // /me lookup resolves (drop a self chip that slipped in before the email loaded).
    if (tpCurrentUserEmail) {
      _addCc(tpCurrentUserEmail);
    } else {
      _addCc('');
      _ensureCurrentUserEmail().then(self => {
        if (self) ccField.removePerson?.(self);
      });
    }
  }
  updateSendState();
  if (isForward) toField.focusInput(); else editor.wrapEl.querySelector('.ql-editor')?.focus();
}

/* ── Email: agentic compose (from Claude) ──────────────── */

function _emailReceiveComposeData(data) {
  if (!document.getElementById('third-pane')?.classList.contains('is-open') || tpState.type !== 'email') {
    openThirdPane('email');
  }
  // Open compose form with pre-filled data
  _showNewEmailCompose(data);
}

/* ── Email detail render ─────────────────────────────────── */

function renderEmailDetail(email) {
  const col = document.getElementById('tp-detail-col');
  // Guard: confirm before discarding an unsaved reply/forward compose
  const composeEditor = col.querySelector('.ql-editor');
  if (composeEditor && (composeEditor.textContent || '').trim()) {
    if (!confirm('Discard unsaved reply?')) return;
  }
  col.innerHTML = '';

  // Email header
  const header = document.createElement('div');
  header.className = 'tp-email-header';
  function _recipCollapsible(label, recipients) {
    if (!recipients || !recipients.length) return '';
    const MAX_SHOW = 3;
    const names = recipients.map(r => escapeHtml(r.name || r.email));
    if (names.length <= MAX_SHOW) {
      return `<div class="tp-email-meta-row"><span class="tp-email-meta-label">${label}</span><span class="tp-email-meta-value">${names.join(', ')}</span></div>`;
    }
    const shown = names.slice(0, MAX_SHOW).join(', ');
    const rest = names.slice(MAX_SHOW).join(', ');
    const uid = 'recip-' + label.toLowerCase() + '-' + Math.random().toString(36).slice(2, 6);
    return `<div class="tp-email-meta-row"><span class="tp-email-meta-label">${label}</span><span class="tp-email-meta-value">${shown} <button class="tp-recip-toggle" id="${uid}-btn" style="background:none;border:none;color:var(--accent,#6c63ff);cursor:pointer;font-size:.75rem;padding:0">+${names.length - MAX_SHOW} more</button><span id="${uid}-rest" style="display:none">, ${rest}</span></span></div>`;
  }
  header.innerHTML = `
    <div class="tp-email-subject">${escapeHtml(email.subject || '(no subject)')}</div>
    <div class="tp-email-meta-row">
      <span class="tp-email-meta-label">From</span>
      <span class="tp-email-meta-value">${escapeHtml(email.from_name || '')} &lt;${escapeHtml(email.from_email || '')}&gt;</span>
    </div>
    ${_recipCollapsible('To', email.to)}
    ${_recipCollapsible('Cc', email.cc)}
    <div class="tp-email-meta-row">
      <span class="tp-email-meta-label">Date</span>
      <span class="tp-email-meta-value">${email.received_at ? new Date(email.received_at).toLocaleString() : ''}</span>
    </div>`;
  // Wire up expand/collapse toggles
  header.querySelectorAll('.tp-recip-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const restEl = btn.parentElement.querySelector('[id$="-rest"]');
      if (restEl.style.display === 'none') {
        restEl.style.display = 'inline';
        btn.textContent = 'show less';
      } else {
        restEl.style.display = 'none';
        btn.textContent = btn.dataset.origText || btn.textContent;
      }
    });
    btn.dataset.origText = btn.textContent;
  });
  col.appendChild(header);

  // Email action toolbar — built into the persistent header (#tp-detail-header)
  // via the shared component, replacing the old in-content second toolbar (tp-ai-bar).
  // Only ACTION BUTTONS move up; the email body, RSVP bar, meeting card, and reply/
  // forward compose all stay in #tp-detail-col so the compose lifecycle is untouched
  // (a header action never wipes the content column — memory: email-compose-ux-gap).
  {
    const _pinBtn = _createPinBtn('email', email.id, email.subject || '(no subject)', { from: email.from_name || '' });
    // No title in the toolbar — the subject is shown in the content header right
    // below, so repeating it here is redundant (user feedback). Actions only.
    // Standard email-client action glyphs (reply / reply-all / forward). Draft-
    // with-AI is NOT here — it surfaces inside the compose area once the user
    // opens a reply/forward (intent-first), per UX decision.
    const _REPLY_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>';
    const _REPLYALL_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="7 17 2 12 7 7"/><polyline points="12 17 7 12 12 7"/><path d="M22 18v-2a4 4 0 0 0-4-4H7"/></svg>';
    const _FORWARD_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 17 20 12 15 7"/><path d="M4 18v-2a4 4 0 0 1 4-4h12"/></svg>';
    tpBuildDetailToolbar({
      app: 'email',
      title: {},
      actions: [
        { kind: 'icon', iconHtml: '✦', title: 'Summarize this email', group: 0,
          onClick: () => tpInjectAIPrompt(`Summarize this email from ${email.from_name} with subject "${email.subject}". Content: ${(email.body_text || '').slice(0, 600)}`) },
        { kind: 'icon', iconHtml: _REPLY_SVG, title: 'Reply', id: 'tp-email-reply-btn', group: 1, onClick: () => _showReplyForwardCompose('reply', email) },
        { kind: 'icon', iconHtml: _REPLYALL_SVG, title: 'Reply All', group: 1, onClick: () => _showReplyForwardCompose('replyall', email) },
        { kind: 'icon', iconHtml: _FORWARD_SVG, title: 'Forward', group: 1, onClick: () => _showReplyForwardCompose('forward', email) },
        { el: _pinBtn, kind: 'icon', title: 'Pin email', group: 1 },
      ],
    });
  }

  // RSVP bar — for all meeting invites; event_id used when available, falls back to message endpoint
  if (email.meeting_message_type === 'meetingRequest') {
    // Meeting details card
    const md = email.meeting_details || {};
    if (md.start) {
      const card = document.createElement('div');
      card.className = 'tp-meeting-card';

      const fmt = (iso, allDay) => {
        if (!iso) return '';
        const d = new Date(iso);
        return allDay ? d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
                      : d.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
      };
      const startStr = fmt(md.start.dateTime || md.start.date, md.is_all_day);
      const endStr   = fmt(md.end.dateTime   || md.end.date,   md.is_all_day);

      const rows = [];
      if (startStr) rows.push(`<div class="tp-mcard-row"><span class="tp-mcard-label">When</span><span>${escapeHtml(startStr)}${endStr && endStr !== startStr ? ' → ' + escapeHtml(endStr) : ''}</span></div>`);
      if (md.location) rows.push(`<div class="tp-mcard-row"><span class="tp-mcard-label">Where</span><span>${escapeHtml(md.location)}</span></div>`);
      if (md.organizer) rows.push(`<div class="tp-mcard-row"><span class="tp-mcard-label">Organizer</span><span>${escapeHtml(md.organizer)}</span></div>`);
      if (md.is_online && md.join_url) rows.push(`<div class="tp-mcard-row"><span class="tp-mcard-label">Online</span><a href="${escapeHtml(md.join_url)}" target="_blank" rel="noopener" class="tp-mcard-join">Join meeting ↗</a></div>`);
      if (md.attendees && md.attendees.length) {
        const names = md.attendees.slice(0, 5).map(a => escapeHtml(a.name || a.email)).join(', ');
        const more = md.attendees.length > 5 ? ` +${md.attendees.length - 5} more` : '';
        rows.push(`<div class="tp-mcard-row"><span class="tp-mcard-label">Attendees</span><span>${names}${more}</span></div>`);
      }

      card.innerHTML = `<div class="tp-mcard-title">📅 Meeting Invite</div>${rows.join('')}`;
      col.appendChild(card);
    }

    const rsvpBar = document.createElement('div');
    rsvpBar.className = 'tp-ai-bar';
    rsvpBar.style.cssText = 'background:var(--surface2);border-top:1px solid var(--border);gap:.4rem';
    rsvpBar.innerHTML = `
      <button class="tp-ai-btn" id="tp-rsvp-accept" style="background:var(--success);color:#fff;border-color:var(--success)">✓ Accept</button>
      <button class="tp-ai-btn" id="tp-rsvp-tentative" style="background:var(--warn);color:#fff;border-color:var(--warn)">? Maybe</button>
      <button class="tp-ai-btn" id="tp-rsvp-decline" style="background:var(--danger);color:#fff;border-color:var(--danger)">✕ Decline</button>
      <span id="tp-rsvp-msg" style="font-size:.74rem;color:var(--text-sub);margin-left:.2rem"></span>`;
    col.appendChild(rsvpBar);

    const rsvpMsg = rsvpBar.querySelector('#tp-rsvp-msg');
    const sendRsvp = async (response, label) => {
      rsvpMsg.textContent = 'Sending…';
      try {
        const res = await fetch(`/api/email/messages/${encodeURIComponent(email.id)}/respond`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ response, send_response: true, event_id: email.event_id || '' }),
        });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          const detail = d.detail || `HTTP ${res.status}`;
          // Friendly message for common Graph errors
          if (detail.includes("hasn't requested a response")) throw new Error('Organizer disabled responses for this meeting');
          throw new Error(detail);
        }
        rsvpMsg.textContent = `${label} sent`;
        rsvpBar.querySelectorAll('button').forEach(b => b.disabled = true);
      } catch (e) {
        rsvpMsg.textContent = e.message;
      }
    };

    rsvpBar.querySelector('#tp-rsvp-accept').addEventListener('click', () => sendRsvp('accept', 'Accepted'));
    rsvpBar.querySelector('#tp-rsvp-tentative').addEventListener('click', () => sendRsvp('tentativelyAccept', 'Tentative'));
    rsvpBar.querySelector('#tp-rsvp-decline').addEventListener('click', () => sendRsvp('decline', 'Declined'));
  }

  // Email body
  const bodyWrap = document.createElement('div');
  bodyWrap.className = 'tp-email-body-wrap';
  col.appendChild(bodyWrap);

  if (email.body_html) {
    const frame = document.createElement('iframe');
    frame.className = 'tp-email-body-frame';
    frame.setAttribute('sandbox', 'allow-same-origin');
    frame.title = 'Email body';
    bodyWrap.appendChild(frame);

    requestAnimationFrame(() => {
      const doc = frame.contentDocument || frame.contentWindow?.document;
      if (!doc) return;
      doc.open();
      doc.write(`<!DOCTYPE html><html><head><meta charset="utf-8">
        <style>body{font-family:-apple-system,'Segoe UI',sans-serif;font-size:13px;color:#1a1a1a;background:#fff;padding:1rem 1.2rem;line-height:1.6;margin:0}
        a{color:#0066cc}img{max-width:100%;cursor:zoom-in}blockquote{border-left:3px solid #ccc;margin:.5rem 0;padding-left:.75rem;color:#555}
        pre{white-space:pre-wrap;font-size:12px}</style>
      </head><body>${email.body_html}</body></html>`);
      doc.close();
      // Intercept link clicks and image clicks from parent (no allow-scripts needed)
      doc.addEventListener('click', e => {
        const img = e.target.closest('img');
        if (img && img.src) { if (window._tpLightboxOpen) window._tpLightboxOpen(img.src); return; }
        const a = e.target.closest('a[href]');
        if (a) { e.preventDefault(); window.open(a.href, '_blank', 'noopener'); }
      });
      // Auto-size iframe to content
      try {
        const resize = () => {
          const h = doc.body.scrollHeight;
          if (h) frame.style.height = h + 24 + 'px';
        };
        resize();
        setTimeout(resize, 300);
      } catch {}
    });
  } else {
    bodyWrap.innerHTML = `<div style="padding:1rem .9rem;font-size:.82rem;color:var(--text);line-height:1.6;white-space:pre-wrap">${escapeHtml(email.body_text || '')}</div>`;
  }

  // Reply / Reply All / Forward open a full-view compose pane (_showReplyForwardCompose, #1/#21).
  // Action handlers are wired directly in the tpBuildDetailToolbar spec above.
}

/* ── AI bridge to chat pane ──────────────────────────────── */

function tpInjectAIPrompt(prompt) {
  const input = document.getElementById('chat-input');
  if (!input) return;
  input.value = prompt;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  // Inject skill chip for context
  const _tpSkillMap = { teams: 'teams', email: 'email', slack: 'slack', onenote: 'onenote', onedrive: 'onedrive', calendar: 'email' };
  const skillId = _tpSkillMap[tpState.type] || 'email';
  if (typeof injectChip === 'function') injectChip(skillId, prompt);
  input.focus();
}

/* ── Resize ──────────────────────────────────────────────── */

function initThirdPaneResize() {
  const handle = document.getElementById('third-pane-resize');
  let _currentPaneW = 680;

  const savedW = localStorage.getItem('tp-pane-width');
  if (savedW) {
    _currentPaneW = +savedW;
    document.documentElement.style.setProperty('--third-pane-w', _currentPaneW + 'px');
  }

  // Full-viewport overlay prevents iframes from stealing mouse events during drag
  let overlay = null;

  function onMouseMove(e) {
    const maxW = Math.floor(window.innerWidth * 0.7);
    const w = Math.min(Math.max(_currentPaneW + (e.clientX - _startX), 400), maxW);
    _dragW = w;
    document.documentElement.style.setProperty('--third-pane-w', w + 'px');
  }

  function onMouseUp() {
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
    handle.classList.remove('tp-dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    if (overlay) { overlay.remove(); overlay = null; }
    _currentPaneW = _dragW;
    localStorage.setItem('tp-pane-width', _currentPaneW);
  }

  let _startX = 0, _dragW = _currentPaneW;

  handle.addEventListener('mousedown', e => {
    _startX = e.clientX;
    _dragW = _currentPaneW;
    handle.classList.add('tp-dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    // Create overlay to block iframe pointer events
    overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;cursor:col-resize;';
    document.body.appendChild(overlay);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    e.preventDefault();
  });

  // List/detail split resize
  const listCol = document.getElementById('tp-list-col');
  const listHandle = document.getElementById('tp-list-resize');
  let _listW = 260;

  const savedLW = localStorage.getItem('tp-list-width');
  if (savedLW) {
    _listW = +savedLW;
    document.documentElement.style.setProperty('--third-pane-list-w', _listW + 'px');
  }

  let _lStartX = 0, _lDragW = _listW;
  let lOverlay = null;

  function onListMove(e) {
    const w = Math.min(Math.max(_listW + (e.clientX - _lStartX), 200), 380);
    _lDragW = w;
    document.documentElement.style.setProperty('--third-pane-list-w', w + 'px');
  }

  function onListUp() {
    document.removeEventListener('mousemove', onListMove);
    document.removeEventListener('mouseup', onListUp);
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    if (lOverlay) { lOverlay.remove(); lOverlay = null; }
    _listW = _lDragW;
    localStorage.setItem('tp-list-width', _listW);
  }

  listHandle.addEventListener('mousedown', e => {
    _lStartX = e.clientX;
    _lDragW = _listW;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    lOverlay = document.createElement('div');
    lOverlay.style.cssText = 'position:fixed;inset:0;z-index:9999;cursor:col-resize;';
    document.body.appendChild(lOverlay);
    document.addEventListener('mousemove', onListMove);
    document.addEventListener('mouseup', onListUp);
    e.preventDefault();
  });
}

/* ── Keyboard navigation ─────────────────────────────────── */

document.addEventListener('keydown', e => {
  if (!tpState.type) return;
  if (e.target.matches('input, textarea, [contenteditable]')) return;

  const list = tpState.list;
  if (e.key === 'j' || e.key === 'ArrowDown') {
    e.preventDefault();
    tpMoveFocus(1);
  } else if (e.key === 'k' || e.key === 'ArrowUp') {
    e.preventDefault();
    tpMoveFocus(-1);
  } else if (e.key === 'Enter' && tpState.type !== 'email' && tpState.focusedIndex >= 0 && tpState.focusedIndex < list.length) {
    e.preventDefault();
    tpLoadDetail(list[tpState.focusedIndex].id);
  } else if (e.key === 'Escape') {
    if (document.getElementById('tp-lightbox')?.classList.contains('active')) return;
    closeThirdPane();
  } else if (e.key === 'r' && tpState.type === 'email' && tpState.selectedId) {
    document.getElementById('tp-email-reply-btn')?.click();
  }
});

function tpMoveFocus(delta) {
  // Email has its own scroll-container keydown handler — don't double-handle
  if (tpState.type === 'email') return;
  const list = tpState.list;
  if (!list.length) return;
  const next = Math.max(0, Math.min(list.length - 1, tpState.focusedIndex + delta));
  if (next === tpState.focusedIndex) return;
  // Update focused class in-place using data-idx (handles collapsed sections)
  document.querySelectorAll('.tp-list-item').forEach(el => el.classList.remove('focused'));
  tpState.focusedIndex = next;
  const focused = document.querySelector(`.tp-list-item[data-idx="${next}"]`);
  if (focused) {
    focused.classList.add('focused');
    if (focused.dataset.id) tpState.focusedId = focused.dataset.id;
    focused.scrollIntoView({ block: 'nearest' });
  }
}

/* ── Date range pills ──────────────────────────────────── */

const _DATE_RANGES = [
  { label: 'Today',  days: 1 },
  { label: '3 Days', days: 3 },
  { label: '1 Week', days: 7 },
  { label: '2 Weeks', days: 14 },
  { label: '1 Month', days: 30 },
];

function _makeDateRangeBar(activeKey, onChange) {
  const wrap = document.createElement('div');
  wrap.className = 'tp-date-range-bar';
  _DATE_RANGES.forEach(r => {
    const btn = document.createElement('button');
    btn.className = 'tp-date-range-pill' + (r.days === activeKey ? ' active' : '');
    btn.textContent = r.label;
    btn.addEventListener('click', () => {
      wrap.querySelectorAll('.tp-date-range-pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      onChange(r.days);
    });
    wrap.appendChild(btn);
  });
  return wrap;
}

function _daysAgoISO(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

/* ── Filter tabs helper ──────────────────────────────────── */

function _makeFilterTabs(labels, activeIdx, onChange) {
  const wrap = document.createElement('div');
  wrap.className = 'tp-filter-tabs';
  labels.forEach((label, i) => {
    const btn = document.createElement('button');
    btn.className = 'tp-filter-tab' + (i === activeIdx ? ' active' : '');
    btn.textContent = label;
    btn.addEventListener('click', () => {
      wrap.querySelectorAll('.tp-filter-tab').forEach((b, j) => b.classList.toggle('active', j === i));
      onChange(i);
    });
    wrap.appendChild(btn);
  });
  return wrap;
}

/* ── Error / banner helpers ──────────────────────────────── */

/* ── Auth Expired Overlay (Teams only) ────────────────── */
function _showAuthOverlay(skill) {
  _dismissAuthOverlay();
  const pane = document.getElementById('third-pane');
  if (!pane) return;
  const overlay = document.createElement('div');
  overlay.id = 'tp-auth-overlay';
  Object.assign(overlay.style, {
    position: 'absolute', inset: '0', zIndex: '50',
    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '.8rem',
    background: 'rgba(0,0,0,.65)', backdropFilter: 'blur(4px)',
    borderRadius: 'inherit', cursor: 'default',
  });
  // Build overlay content with safe DOM methods (skill already escaped above)
  const icon = document.createElement('div');
  icon.style.fontSize = '2.2rem';
  icon.textContent = '\uD83D\uDD12';
  overlay.appendChild(icon);

  const title = document.createElement('div');
  Object.assign(title.style, { fontWeight: '600', fontSize: '.95rem', color: '#fff' });
  title.textContent = skill + ' session expired';
  overlay.appendChild(title);

  const desc = document.createElement('div');
  Object.assign(desc.style, { fontSize: '.82rem', color: 'rgba(255,255,255,.7)', maxWidth: '240px', textAlign: 'center', lineHeight: '1.5' });
  desc.textContent = 'Your token has expired. Re-capture to restore access.';
  overlay.appendChild(desc);

  const statusEl = document.createElement('div');
  statusEl.id = 'tp-auth-overlay-cap-status';
  Object.assign(statusEl.style, { fontSize: '.78rem', color: 'rgba(255,255,255,.6)', minHeight: '1.2em', textAlign: 'center' });
  overlay.appendChild(statusEl);

  const btnRow = document.createElement('div');
  Object.assign(btnRow.style, { display: 'flex', gap: '.5rem', marginTop: '.2rem' });

  const capBtn = document.createElement('button');
  capBtn.id = 'tp-auth-overlay-capture';
  Object.assign(capBtn.style, {
    padding: '.45rem 1.2rem', border: 'none', borderRadius: '6px',
    background: 'var(--accent,#6c63ff)', color: '#fff', fontSize: '.82rem', fontWeight: '600',
    cursor: 'pointer', transition: 'opacity .15s',
  });
  capBtn.textContent = 'Re-capture \u26A1';
  btnRow.appendChild(capBtn);

  const dismissBtn = document.createElement('button');
  dismissBtn.id = 'tp-auth-overlay-dismiss';
  Object.assign(dismissBtn.style, {
    padding: '.45rem 1rem', border: '1px solid rgba(255,255,255,.3)', borderRadius: '6px',
    background: 'none', color: 'rgba(255,255,255,.8)', fontSize: '.82rem',
    cursor: 'pointer', transition: 'opacity .15s',
  });
  dismissBtn.textContent = 'Dismiss';
  btnRow.appendChild(dismissBtn);

  overlay.appendChild(btnRow);

  overlay.addEventListener('click', e => e.stopPropagation());
  capBtn.addEventListener('click', () => {
    capBtn.disabled = true;
    capBtn.textContent = 'Capturing\u2026';
    const es = new EventSource('/api/auth/teams/capture/stream');
    es.addEventListener('status', e => {
      statusEl.textContent = JSON.parse(e.data);
    });
    es.addEventListener('result', e => {
      es.close();
      capBtn.textContent = '\u2713 Done';
      statusEl.textContent = 'Token captured successfully';
      statusEl.style.color = '#4caf50';
      setTimeout(() => {
        _dismissAuthOverlay();
        if (typeof _fetchTeamsList === 'function') _fetchTeamsList();
      }, 1000);
    });
    es.addEventListener('error', e => {
      es.close();
      capBtn.disabled = false;
      capBtn.textContent = 'Re-capture \u26A1';
      const msg = e.data ? JSON.parse(e.data) : 'Capture failed \u2014 try again';
      statusEl.textContent = msg;
      statusEl.style.color = '#ff5252';
    });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) return;
      es.close();
      capBtn.disabled = false;
      capBtn.textContent = 'Re-capture \u26A1';
      statusEl.textContent = 'Connection lost \u2014 try again';
      statusEl.style.color = '#ff5252';
    };
  });
  dismissBtn.addEventListener('click', () => {
    _dismissAuthOverlay();
  });
  pane.style.position = 'relative';
  pane.appendChild(overlay);
}

function _dismissAuthOverlay() {
  document.getElementById('tp-auth-overlay')?.remove();
}

function _showListError(msg, retryFn) {
  const col = document.getElementById('tp-list-col');
  col.innerHTML = `<div class="tp-empty-state" style="padding:1rem;text-align:center;gap:.6rem">
    <span>${escapeHtml(msg)}</span>
    ${retryFn ? `<button class="tp-ai-btn" id="tp-retry-btn">Retry</button>` : ''}
  </div>`;
  if (retryFn) col.querySelector('#tp-retry-btn')?.addEventListener('click', retryFn);
}


function _showDetailAuthError(col, retryFn) {
  col.textContent = '';
  const wrap = document.createElement('div');
  wrap.className = 'tp-empty-state';
  Object.assign(wrap.style, { padding: '2rem 1.5rem', textAlign: 'center', gap: '.8rem' });

  const icon = document.createElement('div');
  icon.style.fontSize = '2rem';
  icon.textContent = '\uD83D\uDD11';
  wrap.appendChild(icon);

  const heading = document.createElement('div');
  Object.assign(heading.style, { fontWeight: '600', fontSize: '.95rem' });
  heading.textContent = 'Teams session expired';
  wrap.appendChild(heading);

  const desc = document.createElement('div');
  Object.assign(desc.style, { fontSize: '.82rem', color: 'var(--text-sub)', maxWidth: '260px', lineHeight: '1.5' });
  desc.textContent = 'Your Teams token has expired. Re-capture to restore access.';
  wrap.appendChild(desc);

  const statusEl = document.createElement('div');
  Object.assign(statusEl.style, { fontSize: '.78rem', color: 'var(--text-sub)', minHeight: '1.2em' });
  wrap.appendChild(statusEl);

  const capBtn = document.createElement('button');
  capBtn.className = 'tp-ai-btn';
  capBtn.textContent = 'Re-capture \u26A1';
  capBtn.addEventListener('click', () => {
    capBtn.disabled = true;
    capBtn.textContent = 'Capturing\u2026';
    const es = new EventSource('/api/auth/teams/capture/stream');
    es.addEventListener('status', e => { statusEl.textContent = JSON.parse(e.data); });
    es.addEventListener('result', e => {
      es.close();
      capBtn.textContent = '\u2713 Done';
      statusEl.textContent = 'Token captured successfully';
      statusEl.style.color = '#4caf50';
      setTimeout(() => { if (retryFn) retryFn(); }, 1000);
    });
    es.addEventListener('error', e => {
      es.close();
      capBtn.disabled = false;
      capBtn.textContent = 'Re-capture \u26A1';
      statusEl.textContent = e.data ? JSON.parse(e.data) : 'Capture failed';
      statusEl.style.color = 'var(--danger, #ff5252)';
    });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) return;
      es.close();
      capBtn.disabled = false;
      capBtn.textContent = 'Re-capture \u26A1';
      statusEl.textContent = 'Connection lost';
      statusEl.style.color = 'var(--danger, #ff5252)';
    };
  });
  wrap.appendChild(capBtn);

  col.appendChild(wrap);
}

/* ── Utility functions ───────────────────────────────────── */

function getInitials(name) {
  if (!name) return '?';
  const clean = name.replace(/[,\.]/g, '').trim();
  const parts = clean.split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return clean.slice(0, 2).toUpperCase();
}

function relativeTime(isoString) {
  if (!isoString) return '';
  // Ensure UTC parsing — append Z if no timezone indicator present
  let s = isoString;
  if (!/Z|[+-]\d{2}:\d{2}$/.test(s)) s += 'Z';
  const date = new Date(s);
  if (isNaN(date)) return '';
  const now = Date.now();
  const diff = now - date.getTime();
  if (diff < 0) return 'just now'; // future timestamps (clock skew)
  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m`;
  if (hours < 24) return `${hours}h`;
  if (days === 1) return 'Yesterday';
  if (days < 7) return date.toLocaleDateString('en', { weekday: 'short' });
  return date.toLocaleDateString('en', { month: 'short', day: 'numeric' });
}

function formatDateLabel(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr + 'T00:00:00');
  const today = new Date();
  const todayStr = today.toISOString().slice(0, 10);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const yStr = yesterday.toISOString().slice(0, 10);
  if (dateStr === todayStr) return 'Today';
  if (dateStr === yStr) return 'Yesterday';
  return date.toLocaleDateString('en', { weekday: 'long', month: 'long', day: 'numeric' });
}

// Linkify bare URLs in text nodes — turns plain "https://..." into clickable anchors.
// Skips text inside existing <a> tags so already-linked text is never double-wrapped.
function _linkifyHtml(html) {
  if (!html || !/https?:\/\//i.test(html)) return html;
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  const URL_RE = /(https?:\/\/[^\s<>"')\]]+)/g;
  function walk(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (!URL_RE.test(node.textContent)) return;
      URL_RE.lastIndex = 0;
      const frag = document.createDocumentFragment();
      let last = 0, m;
      while ((m = URL_RE.exec(node.textContent)) !== null) {
        if (m.index > last) frag.appendChild(document.createTextNode(node.textContent.slice(last, m.index)));
        const a = document.createElement('a');
        a.href = m[1]; a.textContent = m[1]; a.target = '_blank'; a.rel = 'noopener';
        frag.appendChild(a);
        last = m.index + m[0].length;
      }
      if (last < node.textContent.length) frag.appendChild(document.createTextNode(node.textContent.slice(last)));
      node.parentNode.replaceChild(frag, node);
    } else if (node.nodeType === Node.ELEMENT_NODE && node.tagName !== 'A') {
      Array.from(node.childNodes).forEach(walk);
    }
  }
  Array.from(tmp.childNodes).forEach(walk);
  return tmp.innerHTML;
}

function sanitizeHtml(html) {
  if (!html) return '';
  const div = document.createElement('div');
  div.innerHTML = html;
  div.querySelectorAll('script, style, iframe, object, embed, form, meta, link').forEach(el => el.remove());
  div.querySelectorAll('*').forEach(el => {
    Array.from(el.attributes).forEach(attr => {
      if (attr.name.startsWith('on') || (attr.name === 'href' && attr.value.startsWith('javascript:'))) {
        el.removeAttribute(attr.name);
      }
    });
  });
  return div.innerHTML;
}

/* ── Lightbox ─────────────────────────────────────────────── */
(function _initLightbox() {
  const lb = document.createElement('div');
  lb.id = 'tp-lightbox';
  lb.innerHTML = `
    <div id="tp-lightbox-backdrop"></div>
    <div id="tp-lightbox-close" title="Close (Esc)">✕</div>
    <div id="tp-lightbox-img-wrap">
      <img id="tp-lightbox-img" alt="">
    </div>
    <div id="tp-lightbox-hint">Scroll to zoom · Click outside to close</div>`;
  document.body.appendChild(lb);

  const img = lb.querySelector('#tp-lightbox-img');
  const wrap = lb.querySelector('#tp-lightbox-img-wrap');
  let _scale = 1;

  function _open(src) {
    img.src = src;
    _scale = 1;
    img.style.transform = `scale(1)`;
    lb.classList.add('active');
    document.addEventListener('keydown', _onKey);
  }
  function _close() {
    lb.classList.remove('active');
    img.src = '';
    document.removeEventListener('keydown', _onKey);
  }
  function _onKey(e) { if (e.key === 'Escape') { e.stopPropagation(); _close(); } }

  lb.querySelector('#tp-lightbox-backdrop').addEventListener('click', _close);
  lb.querySelector('#tp-lightbox-close').addEventListener('click', _close);

  wrap.addEventListener('wheel', e => {
    e.preventDefault();
    _scale = Math.min(8, Math.max(0.25, _scale * (e.deltaY < 0 ? 1.15 : 0.87)));
    img.style.transform = `scale(${_scale})`;
  }, { passive: false });

  // Expose so _buildTeamsMessage can call it
  window._tpLightboxOpen = _open;
})();

// Strip trailing empty block-level elements (the cursor-parking line Quill always
// keeps at the end). Runs in a loop so we collapse nested cases like an empty
// trailing <li> inside an otherwise-non-empty <ul>.
function _stripTrailingEmptyBlocks(html) {
  if (!html) return html;
  let prev;
  do {
    prev = html;
    html = html
      .replace(/(<(li|div|p)[^>]*>(?:\s|<br\s*\/?>)*<\/\2>)\s*$/i, '')
      .replace(/(<(ul|ol)[^>]*>\s*<\/\2>)\s*$/i, '')
      .trim();
  } while (html !== prev);
  return html;
}

/**
 * Convert Quill's flat indented paragraphs into Teams' native nested-list structure.
 *
 * Quill emits each paragraph independently, indent encoded as a class:
 *   <p>A</p><p class="ql-indent-1">B</p><p class="ql-indent-2">C</p>
 *
 * Teams (and the Skype chatsvc round-trip) represents indentation as ONE
 * hierarchical bullet list where deeper items nest inside the previous shallower
 * item — exactly what Teams' own indent button produces:
 *   <ul><li>A<ul><li>B<ul><li>C</li></ul></li></ul></li></ul>
 *
 * Walks the editor's block children in order and rebuilds consecutive runs of
 * indented paragraphs as a single nested <ul> tree (using an open-level stack),
 * so indents become a proper outline instead of the disconnected per-paragraph
 * <ul> blocks the old regex produced. Non-<p> blocks (code blocks, etc.) and
 * level-0 paragraphs pass through untouched, preserving order.
 */
/**
 * Install compose key bindings matching native Teams behavior.
 *
 * Tab: only sub-indents WITHIN a bullet/numbered list (native Teams behavior).
 *   We keep Quill's built-in Tab — it indents list items and inserts a tab
 *   character elsewhere — but make it a no-op outside lists so plain paragraphs
 *   don't sprout surprise indentation. This is what the user expects: bullets
 *   come from the bullet button, Tab only nests sub-bullets.
 *
 * Shift+Enter: newline that does NOT inherit the previous line's list/indent,
 *   so a soft line break inside a bullet doesn't accidentally start a new bullet
 *   or carry indentation. Prepended so it beats Quill's shiftKey:null default
 *   Enter handler (which matches Shift+Enter and would inherit formatting).
 */
function _installComposeIndentBindings(q) {
  if (!q || !q.keyboard) return;
  const kb = q.keyboard;

  const prepend = (keyCode, binding) => {
    if (!Array.isArray(kb.bindings[keyCode])) kb.bindings[keyCode] = [];
    kb.bindings[keyCode].unshift(binding);
  };

  // Tab / Shift+Tab → indent only when inside a list; otherwise do nothing
  // (prevents plain paragraphs from getting indented/bulleted by Tab).
  kb.bindings[9] = [];
  kb.bindings[9].push({ key: 9, shiftKey: false, handler() {
    if (this.quill.getFormat().list) { this.quill.format('indent', '+1'); }
    return false; // swallow Tab regardless so focus never leaves the editor
  } });
  kb.bindings[9].push({ key: 9, shiftKey: true, handler() {
    if (this.quill.getFormat().list) { this.quill.format('indent', '-1'); }
    return false;
  } });

  // Shift+Enter → newline, clear list+indent on the new line so it starts clean
  prepend(13, {
    key: 13,
    shiftKey: true,
    handler(range) {
      this.quill.insertText(range.index, '\n', 'user');
      this.quill.setSelection(range.index + 1, 0);
      this.quill.format('list', false);
      this.quill.format('indent', false);
      return false;
    },
  });
}

/**
 * Email-only: convert Quill's ql-indent-N classes to inline margin-left so
 * indentation renders in Outlook (which doesn't load Quill's stylesheet).
 * Email supports true paragraph indent, so no bullet conversion needed.
 * Each indent level ≈ 2em, matching Quill's visual 3em-ish default closely
 * enough for email.
 */
/**
 * Email body indent normaliser for Outlook (which has no Quill stylesheet).
 *  1. Nest bullet/numbered lists: Quill's flat <li class="ql-indent-N"> becomes
 *     truly-nested <ul>/<li> so sub-bullets actually indent in Outlook.
 *  2. Plain-paragraph indents (<p class="ql-indent-N">) → inline margin-left.
 */
function _emailIndentForOutlook(html) {
  if (!html) return html;
  const out = _quillIndentClassesToMargin(_quillIndentToNestedList(html));
  // Outlook's Word-rendering engine does NOT auto-indent semantically-nested
  // <ul>/<ol>; add explicit inline margin so sub-bullets visibly indent there.
  const root = document.createElement('div');
  root.innerHTML = out;
  const nested = root.querySelectorAll('li > ul, li > ol');
  if (!nested.length) return out;
  nested.forEach(n => {
    const existing = n.getAttribute('style') || '';
    if (!/margin-left/i.test(existing)) {
      n.setAttribute('style', `${existing};margin-left:1.5em`.replace(/^;/, ''));
    }
  });
  return root.innerHTML;
}

function _quillIndentClassesToMargin(html) {
  if (!html || !/ql-indent-\d/.test(html)) return html;
  const root = document.createElement('div');
  root.innerHTML = html;
  root.querySelectorAll('[class*="ql-indent-"]').forEach(el => {
    const m = (el.getAttribute('class') || '').match(/ql-indent-(\d+)/);
    if (m) {
      const lvl = parseInt(m[1], 10);
      const existing = el.getAttribute('style') || '';
      el.setAttribute('style', `${existing};margin-left:${lvl * 2}em`.replace(/^;/, ''));
      // Remove the class so no leftover ql-indent dependency
      el.setAttribute('class', (el.getAttribute('class') || '').replace(/ql-indent-\d+/g, '').trim());
      if (!el.getAttribute('class')) el.removeAttribute('class');
    }
  });
  return root.innerHTML;
}

function _quillIndentToNestedList(html) {
  if (!html || !/<li/i.test(html)) return html;

  const root = document.createElement('div');
  root.innerHTML = html;

  const _isEmptyEl = (el) => {
    const txt = (el.textContent || '').replace(/ /g, ' ').trim();
    return txt === '' && !el.querySelector('img');
  };
  const _liIndent = (li) => {
    const m = (li.getAttribute('class') || '').match(/ql-indent-(\d+)/);
    return m ? parseInt(m[1], 10) : 0;
  };
  // Rebuild one flat Quill list (<ul>/<ol> with ql-indent-N on <li>) as a
  // properly-nested tree, dropping empty trailing items.
  // Quill flat:   <li>A</li><li class=ql-indent-1>B</li><li class=ql-indent-2>C</li>
  // Nested out:   <ul><li>A<ul><li>B<ul><li>C</li></ul></li></ul></li></ul>
  const _nestList = (listEl) => {
    const tag = listEl.tagName.toLowerCase();
    const items = Array.from(listEl.children).filter(c => c.tagName === 'LI' && !_isEmptyEl(c));
    if (!items.length) return '';
    let out = '';
    let level = -1; // no list open yet; first item (lvl 0) opens the outer list
    const closeTo = (t) => { while (level > t) { out += '</li></' + tag + '>'; level--; } };
    items.forEach(li => {
      const lvl = _liIndent(li);
      if (lvl > level) {
        // open deeper: each new level emits <ul><li> (the <li> stays open for content)
        while (level < lvl) { out += '<' + tag + '><li>'; level++; }
        out += li.innerHTML;
      } else {
        closeTo(lvl);            // close down to this level (leaves its <li> open... no)
        out += '</li><li>' + li.innerHTML; // sibling at same level
      }
    });
    closeTo(0);                  // close all nested levels back to outer
    out += '</li></' + tag + '>'; // close the outer level's <li> and list
    return out;
  };

  let result = '';
  Array.from(root.childNodes).forEach(node => {
    if (node.nodeType === 1 && (node.tagName === 'UL' || node.tagName === 'OL')) {
      result += _nestList(node);
    } else if (node.nodeType === 1) {
      if (!_isEmptyEl(node)) result += node.outerHTML;
    } else if (node.nodeType === 3 && (node.textContent || '').trim()) {
      result += node.textContent;
    }
  });
  return result;
}

function _quillIndentToNestedList_OLD(html) {
  if (!html || !/ql-indent-\d/.test(html)) return html;

  const root = document.createElement('div');
  root.innerHTML = html;

  // Remove trailing empty block elements (Quill always parks the cursor on a
  // trailing empty <p> that often inherits the previous line's ql-indent class).
  // If left in, it converts to an empty <li><br></li> bullet — the "blank last
  // indent" — that _stripTrailingEmptyBlocks can't reach once nested in a <ul>.
  const isEmptyBlock = (node) => {
    if (node.nodeType === 3) return !(node.textContent || '').trim();
    if (node.nodeType !== 1) return false;
    if (!/^(P|DIV|LI)$/.test(node.tagName)) return false;
    const txt = (node.textContent || '').replace(/ /g, ' ').trim();
    return txt === '';
  };
  while (root.lastChild && isEmptyBlock(root.lastChild)) {
    root.removeChild(root.lastChild);
  }

  const indentLevel = (node) => {
    if (node.nodeType !== 1 || node.tagName !== 'P') return -1; // not an indentable paragraph
    const m = (node.getAttribute('class') || '').match(/ql-indent-(\d+)/);
    return m ? parseInt(m[1], 10) : 0;
  };

  let out = '';
  const children = Array.from(root.childNodes);
  let i = 0;

  while (i < children.length) {
    const node = children[i];
    const lvl = indentLevel(node);

    // Pass through anything that isn't an indented (level ≥ 1) paragraph.
    if (lvl < 1) {
      out += node.nodeType === 1 ? node.outerHTML : (node.textContent || '');
      i++;
      continue;
    }

    // Start of an indented run: consume consecutive paragraphs with level ≥ 1
    // and build a single nested list. The run's items at level L nest under the
    // nearest preceding item at level L-1.
    let openLevels = 0;
    const closeTo = (target) => {
      while (openLevels > target) { out += '</li></ul>'; openLevels--; }
    };

    while (i < children.length && indentLevel(children[i]) >= 1) {
      const lvlN = indentLevel(children[i]);
      const content = children[i].innerHTML;
      if (lvlN > openLevels) {
        while (openLevels < lvlN) { out += '<ul><li>'; openLevels++; }
        out += content;
      } else {
        closeTo(lvlN);
        out += '</li><li>' + content;
      }
      i++;
    }
    closeTo(0);
  }

  return out;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* ── Email iframe → lightbox bridge ──────────────────────── */
window.addEventListener('message', e => {
  if (e.data?.type === 'tp-lightbox' && e.data.src) {
    if (window._tpLightboxOpen) window._tpLightboxOpen(e.data.src);
  }
  if (e.data?.type === 'tp-open-link' && e.data.href) {
    window.open(e.data.href, '_blank', 'noopener');
  }
});

/* ── Init ────────────────────────────────────────────────── */
initThirdPaneResize();
// Load persisted filter/selectedId but always start with pane closed on refresh.
// The old type is intentionally discarded — opening requires an explicit rail click.
loadTpState();
tpState.type = null;
// Don't auto-open third pane on load — let gator be the default landing

// ── Startup pre-fetch with splash screen ──
// Fire calendar prefetch immediately — before splash even starts — so events are
// cached by the time the user opens the calendar pane.
// Uses local-timezone ISO strings to match FullCalendar's info.startStr/endStr format.
(function _calendarPrefetch() {
  const _localIso = d => {
    const p = n => String(n).padStart(2, '0');
    const off = -d.getTimezoneOffset();
    const sign = off >= 0 ? '+' : '-';
    const oh = p(Math.floor(Math.abs(off) / 60));
    const om = p(Math.abs(off) % 60);
    return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}${sign}${oh}:${om}`;
  };
  const _weekRange = offsetWeeks => {
    const s = new Date();
    s.setDate(s.getDate() - s.getDay() + offsetWeeks * 7);
    s.setHours(0, 0, 0, 0);
    const e = new Date(s);
    e.setDate(e.getDate() + 7);
    return [_localIso(s), _localIso(e)];
  };
  [0, 1].forEach(w => {
    const [start, end] = _weekRange(w);
    fetch(`/api/calendar/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`)
      .then(r => r.ok ? r.json() : null)
      .then(events => { if (events) _fcEventCache.set(`${start}|${end}`, { events, ts: Date.now() }); })
      .catch(() => {});
  });
})();

(async function _startupPrefetch() {
  // Dev mode: skip splash + prefetch with ?dev=1 or localStorage.dev
  const _devMode = new URLSearchParams(location.search).has('dev') || localStorage.getItem('gator_dev') === '1';
  const _splash = document.getElementById('gator-splash');
  if (_devMode) {
    if (_splash) _splash.remove();
    _loadPinCache();
    return;
  }
  const _splashMsg = document.getElementById('gator-splash-msg');
  const _splashBar = document.getElementById('gator-splash-bar');
  let _splashPct = 5;
  const _sp = (msg, pct) => {
    _splashPct = pct;
    if (_splashMsg) { _splashMsg.style.opacity = '0'; setTimeout(() => { if (_splashMsg) { _splashMsg.textContent = msg; _splashMsg.style.opacity = '1'; } }, 120); }
    if (_splashBar) _splashBar.style.width = pct + '%';
  };

  // Cycling status messages while waiting
  const _tips = [
    'Wading into your inbox\u2026',
    'Checking Teams conversations\u2026',
    'Snapping up unread messages\u2026',
    'Syncing your workspace\u2026',
    'Warming up the data lake\u2026',
    'Crunching the latest updates\u2026',
    'Almost ready to chomp\u2026',
  ];
  let _tipIdx = 0;
  const _tipTimer = setInterval(() => {
    _tipIdx = (_tipIdx + 1) % _tips.length;
    _splashPct = Math.min(85, _splashPct + 8);
    _sp(_tips[_tipIdx], _splashPct);
  }, 1800);

  const _dismissSplash = () => {
    clearInterval(_tipTimer);
    _sp('Ready \u2014 let\u2019s go!', 100);
    setTimeout(() => {
      if (_splash) { _splash.style.transition = 'opacity .4s'; _splash.style.opacity = '0'; setTimeout(() => _splash.remove(), 400); }
    }, 400);
  };

  try {
  // Populate badges from stale cache immediately
  const staleTeams = _getStaleCache('teams');
  if (staleTeams) {
    const unread = (staleTeams.data || []).filter(c => (c.unread_count || 0) > 0).length;
    if (typeof updateRailBadge === 'function') updateRailBadge('teams', unread);
  }
  const staleEmail = _getStaleCache('email');
  if (staleEmail) {
    const unread = staleEmail.extra?.totalUnread || 0;
    if (typeof updateRailBadge === 'function') updateRailBadge('email', unread);
  }

  // Single combined fetch — runs Teams + Email in parallel server-side threads
  // AbortController gives us a client-side timeout so the splash never hangs forever.
  console.time('[prefetch] total');
  console.time('[prefetch] api');
  const _prefetchAbort = new AbortController();
  const _prefetchTimeout = setTimeout(() => _prefetchAbort.abort(), 30000); // 30s hard limit
  const prefetchRes = await fetch('/api/prefetch', { signal: _prefetchAbort.signal }).catch(() => null);
  clearTimeout(_prefetchTimeout);
  const prefetchData = prefetchRes?.ok ? await prefetchRes.json() : {};
  console.timeEnd('[prefetch] api');

  // Process Teams
  try {
    const teamsData = prefetchData.teams;
    if (teamsData && !teamsData.error) {
      const chats = teamsData.chats || [];
      _setListCache('teams', chats, {
        hasViewpoint: teamsData.has_viewpoint || false,
        channels: [],
        hasMore: !!teamsData.has_more,
        skypeCursor: teamsData.skype_cursor || '',
      });
      const unread = chats.filter(c => (c.unread_count || 0) > 0).length;
      if (typeof updateRailBadge === 'function') updateRailBadge('teams', unread);
      window._teamsChatsCache = chats;
      // Cache server-prefetched threads (top 3, fetched in parallel server-side)
      const prefetchedThreads = prefetchData.threads || {};
      for (const [chatId, threadData] of Object.entries(prefetchedThreads)) {
        const chat = chats.find(c => c.id === chatId);
        if (chat && threadData.messages) {
          tpThreadCache.set(chatId, { data: { messages: threadData.messages, chat, myId: threadData.my_id || '' }, ts: Date.now() });
        }
      }
      console.log(`[prefetch] ${Object.keys(prefetchedThreads).length} threads cached from server`);
    }
  } catch {}

  // Process Email
  try {
    const emailData = prefetchData.email;
    if (emailData && !emailData.error) {
      const messages = (emailData.messages || []).sort((a, b) => {
        const aU = !a.is_read ? 1 : 0, bU = !b.is_read ? 1 : 0;
        if (aU !== bU) return bU - aU;
        return new Date(b.received_at || 0) - new Date(a.received_at || 0);
      });
      const totalUnread = emailData.total_unread || 0;
      _setListCache('email', messages, { totalUnread });
      if (typeof updateRailBadge === 'function') updateRailBadge('email', totalUnread);
      // Cache server-prefetched email details (top 3, fetched in parallel server-side)
      const prefetchedEmails = prefetchData.emails || {};
      for (const [emailId, emailDetail] of Object.entries(prefetchedEmails)) {
        if (emailDetail) tpThreadCache.set('email::' + emailId, { data: emailDetail, ts: Date.now() });
      }
      console.log(`[prefetch] ${Object.keys(prefetchedEmails).length} emails cached from server`);
    }
  } catch {}

  _loadPinCache();
  console.timeEnd('[prefetch] total');

  } finally {
    // ALWAYS dismiss — even if fetches fail
    _dismissSplash();
    // Deferred: fetch channels in background (slow — N+2 Graph API calls)
    setTimeout(() => {
      fetch('/api/channels/search').then(r => r.ok ? r.json() : null).then(data => {
        if (!data) return;
        const channels = (data.channels || []).filter(c => c.type === 'channel');
        const cached = _getListCache('teams') || _getStaleCache('teams');
        if (cached) {
          cached.extra.channels = channels;
          _setListCache('teams', cached.data, cached.extra);
        }
      }).catch(() => {});
    }, 2000);
  }
})();


/* ── Calendar (FullCalendar) ─────────────────────────────── */

const FC_CACHE_TTL = 5 * 60 * 1000; // 5 min cache per date range
let _fcFetchTimer = null;            // debounce timer

function _initCalendar() {
  if (typeof FullCalendar === 'undefined') {
    const col = document.getElementById('tp-detail-col');
    col.innerHTML = '<div class="tp-empty-state"><span>Calendar library failed to load.<br>Check network or refresh the page.</span></div>';
    return;
  }

  // Hide left column (toolbar + list) — calendar uses full width
  const _lcEl = document.getElementById('tp-left-col') || document.getElementById('tp-list-col');
  if (_lcEl) { _lcEl.classList.add('tp-cal-hidden'); _lcEl.style.display = 'none'; }
  const _lrEl = document.getElementById('tp-list-resize');
  if (_lrEl) { _lrEl.classList.add('tp-cal-hidden'); _lrEl.style.display = 'none'; }
  document.getElementById('tp-right-col')?.classList.add('tp-cal-full');

  // Standardized toolbar in the persistent header. App-level controls only
  // (Ask Gator + Refresh); close is the pane edge handle. FullCalendar's own
  // prev/next/today date-nav (fc-toolbar) lives in the grid below as content.
  {
    const _REFRESH_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
    tpBuildDetailToolbar({
      app: 'calendar',
      title: { text: 'Calendar', icon: '<img src="/static/icons/calendar.svg" class="skill-icon-img" alt="calendar" style="width:16px;height:16px;">' },
      actions: [
        { kind: 'icon', iconHtml: '✦', title: 'Ask Gator about your calendar', group: 0,
          onClick: () => tpInjectAIPrompt('Summarize my upcoming calendar events and flag any conflicts.') },
        { kind: 'icon', iconHtml: _REFRESH_SVG, id: 'tp-cal-refresh-btn', title: 'Refresh', group: 0, onClick: () => _refreshCalendar() },
      ],
    });
  }

  // Hide search bar — not applicable for calendar view
  const searchBar = document.querySelector('.tp-search-bar');
  if (searchBar) searchBar.style.display = 'none';

  const detailCol = document.getElementById('tp-detail-col');
  detailCol.innerHTML = '<div id="tp-fc-container"></div>';

  _fcInstance = new FullCalendar.Calendar(document.getElementById('tp-fc-container'), {
    initialView: 'timeGridWeek',
    headerToolbar: {
      left: 'prev,next today',
      center: 'title',
      right: 'dayGridMonth,timeGridWeek,timeGridDay,listWeek',
    },
    height: '100%',
    nowIndicator: true,
    // Show the full 24h so early/late events are never hidden; open scrolled to
    // working hours so the common case still looks right.
    slotMinTime: '00:00:00',
    slotMaxTime: '24:00:00',
    scrollTime: '07:00:00',
    allDaySlot: true,
    weekends: true,
    eventDisplay: 'block',
    dayMaxEvents: 3,
    slotDuration: '00:30:00',
    expandRows: true,
    events: _fcFetchEvents,
    loading: (isLoading) => {
      const container = document.getElementById('tp-fc-container');
      if (!container) return;
      let spinner = container.querySelector('.tp-cal-loading');
      if (isLoading && !spinner) {
        spinner = document.createElement('div');
        spinner.className = 'tp-cal-loading';
        spinner.textContent = 'Loading events…';
        container.appendChild(spinner);
      } else if (!isLoading && spinner) {
        spinner.remove();
      }
    },
    eventClick: (info) => {
      info.jsEvent.preventDefault();
      _showCalendarEventPopover(info.event, info.el);
    },
    eventDidMount: (info) => {
      const showAs = info.event.extendedProps.showAs;
      if (showAs === 'tentative') info.el.style.borderLeft = '3px solid #f59e0b';
      else if (showAs === 'oof') info.el.style.borderLeft = '3px solid #a855f7';
      else if (showAs === 'free') { info.el.style.opacity = '0.6'; info.el.style.borderLeft = '3px dashed #666'; }
    },
  });
  _fcInstance.render();
}

function _fcFetchEvents(info, successCb, failureCb) {
  // Debounce rapid prev/next clicks (300ms)
  clearTimeout(_fcFetchTimer);
  _fcFetchTimer = setTimeout(() => _fcFetchEventsInner(info, successCb, failureCb), 300);
}

async function _fcFetchEventsInner(info, successCb, failureCb) {
  const cacheKey = `${info.startStr}|${info.endStr}`;
  const cached = _fcEventCache.get(cacheKey);
  if (cached && Date.now() - cached.ts < FC_CACHE_TTL) {
    successCb(cached.events);
    return;
  }

  try {
    const res = await fetch(`/api/calendar/events?start=${encodeURIComponent(info.startStr)}&end=${encodeURIComponent(info.endStr)}`);
    if (res.status === 401) {
      const col = document.getElementById('tp-detail-col');
      col.innerHTML = '<div class="tp-empty-state"><span>Sign in to Microsoft 365 in Settings.</span></div>';
      failureCb(new Error('Unauthorized'));
      return;
    }
    if (res.status === 429) {
      // Throttled — retry after delay
      setTimeout(() => _fcFetchEventsInner(info, successCb, failureCb), 2000);
      return;
    }
    if (!res.ok) {
      failureCb(new Error(`HTTP ${res.status}`));
      return;
    }
    const events = await res.json();
    _fcEventCache.set(cacheKey, { events, ts: Date.now() });
    successCb(events);
  } catch (e) {
    failureCb(e);
  }
}

function _refreshCalendar() {
  _fcEventCache.clear();
  if (_fcInstance) _fcInstance.refetchEvents();
  return Promise.resolve();
}

function _showCalendarEventPopover(event, el) {
  // Remove any existing popover
  document.querySelectorAll('.tp-cal-popover').forEach(e => e.remove());

  tpState.selectedId = event.id || null;
  _syncAllPinUI();

  const props = event.extendedProps || {};
  const fmtOpts = { dateStyle: 'medium', timeStyle: 'short' };
  const startStr = event.allDay
    ? event.start.toLocaleDateString()
    : event.start.toLocaleString([], fmtOpts);
  const endStr = event.end
    ? (event.allDay ? event.end.toLocaleDateString() : event.end.toLocaleString([], fmtOpts))
    : '';

  const pop = document.createElement('div');
  pop.className = 'tp-cal-popover';

  // Attendees section
  let attendeesHtml = '';
  if (props.attendees && props.attendees.length) {
    const rows = props.attendees.slice(0, 8).map(a => {
      const name = escapeHtml(a.name || a.email);
      const statusCls = (a.status || '').toLowerCase();
      const statusLabel = a.status === 'accepted' ? 'Accepted'
        : a.status === 'declined' ? 'Declined'
        : a.status === 'tentativelyAccepted' ? 'Tentative'
        : a.status === 'none' ? 'No response' : (a.status || '');
      return `<div class="tp-cal-pop-attendee"><span>${name}</span><span class="tp-cal-pop-rsvp ${statusCls}">${statusLabel}</span></div>`;
    }).join('');
    const more = props.attendees.length > 8 ? `<div class="tp-cal-pop-attendee" style="color:#4a6a8a;font-style:italic">+${props.attendees.length - 8} more</div>` : '';
    attendeesHtml = `
      <div class="tp-cal-pop-section">
        <div class="tp-cal-pop-icon">👥</div>
        <div class="tp-cal-pop-section-body">
          <div class="tp-cal-pop-label">Attendees (${props.attendees.length})</div>
          ${rows}${more}
        </div>
      </div>`;
  }

  const hasAttendees = props.attendees && props.attendees.length > 0;

  const _rsvpActive = (s) => props.responseStatus === s ? 'is-active' : '';

  pop.innerHTML = `
    <div class="tp-cal-pop-header">
      <div class="tp-cal-pop-header-top">
        <div class="tp-cal-pop-title">${escapeHtml(event.title)}</div>
        <button class="tp-cal-pop-close" title="Close" aria-label="Close">&times;</button>
      </div>
      <div class="tp-cal-pop-rsvp-row">
        <div class="tp-rsvp-pill" role="group" aria-label="RSVP">
          <button class="tp-rsvp-btn ${_rsvpActive('accepted')}" data-rsvp="accept" title="Accept" aria-label="Accept"><span class="material-symbols-outlined tp-mi">check</span><span class="tp-rsvp-lbl">Accept</span></button>
          <button class="tp-rsvp-btn ${_rsvpActive('tentativelyAccepted')}" data-rsvp="tentativelyAccept" title="Tentative" aria-label="Tentative"><span class="material-symbols-outlined tp-mi">help</span><span class="tp-rsvp-lbl">Tentative</span></button>
          <button class="tp-rsvp-btn ${_rsvpActive('declined')}" data-rsvp="decline" title="Decline" aria-label="Decline"><span class="material-symbols-outlined tp-mi">close</span><span class="tp-rsvp-lbl">Decline</span></button>
        </div>
        <span class="tp-rsvp-status"></span>
      </div>
      <div class="tp-cal-pop-header-actions">
        <button class="tp-qt-btn tp-call-btn tp-cal-prep-btn tp-cal-ai" title="Ask AI — prep me for this meeting" aria-label="Ask AI">✦</button>
        ${props.joinUrl ? `<a class="tp-qt-btn tp-call-btn tp-cal-join-btn" target="_blank" rel="noopener" href="${escapeHtml(props.joinUrl)}" title="Join Teams meeting" aria-label="Join Teams meeting"><span class="material-symbols-outlined tp-mi">videocam</span></a>` : ''}
        ${hasAttendees ? `<button class="tp-qt-btn tp-call-btn tp-cal-replyall-btn" title="Email all attendees" aria-label="Email all attendees"><span class="material-symbols-outlined tp-mi">reply_all</span></button>` : ''}
        <span style="flex:1"></span>
        <span class="tp-cal-pin-slot"></span>
      </div>
    </div>
    <div class="tp-cal-pop-body-wrap">
      <div class="tp-cal-pop-section">
        <div class="tp-cal-pop-icon">🕐</div>
        <div class="tp-cal-pop-section-body">
          <div class="tp-cal-pop-label">When</div>
          <div>${startStr}${endStr ? ' &mdash; ' + endStr : ''}</div>
        </div>
      </div>
      ${props.location ? `
      <div class="tp-cal-pop-section">
        <div class="tp-cal-pop-icon">📍</div>
        <div class="tp-cal-pop-section-body">
          <div class="tp-cal-pop-label">Where</div>
          <div>${escapeHtml(props.location)}</div>
        </div>
      </div>` : ''}
      ${props.organizer ? `
      <div class="tp-cal-pop-section">
        <div class="tp-cal-pop-icon">👤</div>
        <div class="tp-cal-pop-section-body">
          <div class="tp-cal-pop-label">Organizer</div>
          <div>${escapeHtml(props.organizer)}</div>
        </div>
      </div>` : ''}
      ${attendeesHtml}
      ${props.bodyPreview ? `
      <div class="tp-cal-pop-section">
        <div class="tp-cal-pop-icon">📝</div>
        <div class="tp-cal-pop-section-body">
          <div class="tp-cal-pop-label">Details</div>
          <div class="tp-cal-pop-body-text">${escapeHtml(props.bodyPreview)}</div>
        </div>
      </div>` : ''}
    </div>
  `;

  // Pin button — inject into reserved slot in header
  const pinMeta = {
    start: event.start ? event.start.toISOString() : null,
    end: event.end ? event.end.toISOString() : null,
    location: props.location || '',
    joinUrl: props.joinUrl || '',
    organizer: props.organizer || '',
  };
  const pinBtn = _createPinBtn('calendar', event.id || '', event.title || 'Calendar event', pinMeta);
  pinBtn.classList.add('tp-cal-pin-btn');
  pinBtn.style.cssText = 'font-size:.72rem;padding:.2rem .35rem';
  const pinSlot = pop.querySelector('.tp-cal-pin-slot');
  if (pinSlot) pinSlot.replaceWith(pinBtn);

  // ── Transcripts button for past Teams meetings ──
  if (props.joinUrl && event.id) {
    const headerActions = pop.querySelector('.tp-cal-pop-header-actions');
    const pinSlotEl = pop.querySelector('.tp-cal-pin-slot') || pop.querySelector('.tp-cal-pin-btn');
    if (headerActions) {
      const txMount = document.createElement('span');
      if (pinSlotEl && pinSlotEl.parentNode === headerActions) {
        headerActions.insertBefore(txMount, pinSlotEl.previousElementSibling || pinSlotEl);
      } else {
        headerActions.appendChild(txMount);
      }
      _renderCalendarTranscriptCard(txMount, event.id, event.title || 'Calendar event', props.joinUrl).catch(() => {});
    }
  }

  // Reply All — open email compose prefilled with all attendees
  const replyAllBtn = pop.querySelector('.tp-cal-replyall-btn');
  if (replyAllBtn) {
    replyAllBtn.addEventListener('click', () => {
      removePopover();
      const attendeeEmails = (props.attendees || [])
        .map(a => a.email).filter(Boolean).join(',');
      const attendeeNames = (props.attendees || [])
        .map(a => a.name || a.email).filter(Boolean).join(',');
      openThirdPane('email');
      // Wait one tick for the email pane to render before opening compose
      setTimeout(() => {
        _showNewEmailCompose({
          to: attendeeEmails,
          to_names: attendeeNames,
          subject: `Re: ${event.title}`,
          body: '',
        });
      }, 80);
    });
  }

    // RSVP buttons
    const rsvpStatus = pop.querySelector('.tp-rsvp-status');
    pop.querySelectorAll('.tp-rsvp-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const response = btn.dataset.rsvp;
      rsvpStatus.textContent = 'Sending\u2026';
      try {
        const res = await fetch(`/api/calendar/events/${encodeURIComponent(event.id)}/respond`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ response, send_response: true }),
        });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.detail || `HTTP ${res.status}`);
        }
        rsvpStatus.textContent = response === 'accept' ? 'Accepted' : response === 'decline' ? 'Declined' : 'Tentative';
        pop.querySelectorAll('.tp-rsvp-btn').forEach(b => {
          b.classList.toggle('is-active', b.dataset.rsvp === response);
        });
        _refreshCalendar();
      } catch (e) {
        rsvpStatus.textContent = 'Failed: ' + e.message;
      }
    });
  });

    // Position popover near clicked element
    const pane = document.getElementById('third-pane');
    if (!pane) return;
    const margin = 12;
    pop.style.position = 'absolute';
    pop.style.zIndex = '100';
    pop.style.visibility = 'hidden';
    pane.appendChild(pop);

    const reposition = () => {
      if (!pop.isConnected) return;
      const paneRect = pane.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      const availableHeight = Math.max(200, paneRect.height - margin * 2);
      const maxHeight = Math.min(420, availableHeight);
      pop.style.maxHeight = `${Math.round(maxHeight)}px`;
      const popRect = pop.getBoundingClientRect();
      const popWidth = popRect.width;
      const popHeight = popRect.height;

      let left = elRect.right - paneRect.left + margin;
      if (left + popWidth > paneRect.width - margin) {
        left = elRect.left - paneRect.left - popWidth - margin;
      }
      const maxLeft = paneRect.width - margin - popWidth;
      if (left > maxLeft) left = maxLeft;
      if (left < margin) left = margin;

      let top = elRect.top - paneRect.top;
      const maxTop = paneRect.height - margin - popHeight;
      if (top > maxTop) top = maxTop;
      if (top < margin) top = margin;

      pop.style.left = `${Math.round(left)}px`;
      pop.style.top = `${Math.round(top)}px`;
      pop.style.visibility = 'visible';
    };

    const handleReposition = () => reposition();
    window.addEventListener('resize', handleReposition);
    pane.addEventListener('scroll', handleReposition, true);
    reposition();
    requestAnimationFrame(reposition);

    let outsideHandler = null;
    const cleanup = () => {
      window.removeEventListener('resize', handleReposition);
      pane.removeEventListener('scroll', handleReposition, true);
      if (outsideHandler) {
        document.removeEventListener('mousedown', outsideHandler);
        outsideHandler = null;
      }
    };

    function removePopover() {
      if (!pop.isConnected) return;
      cleanup();
      pop.remove();
    }

    // Wire up event listeners (no inline onclick — XSS safe)
    pop.querySelector('.tp-cal-pop-close').addEventListener('click', removePopover);
    pop.querySelector('.tp-cal-prep-btn').addEventListener('click', () => {
      removePopover();
      const attendeeNames = (props.attendees || []).map(a => a.name || a.email).join(', ') || 'no attendees listed';
      const msg = `Prep me for this meeting: "${event.title}" with ${attendeeNames}. ${props.bodyPreview || ''}`;
      const input = document.getElementById('chat-input');
      if (input) {
        input.textContent = msg;
        input.focus();
        input.dispatchEvent(new Event('input', { bubbles: true }));
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(input);
        range.collapse(false);
        sel.removeAllRanges();
        sel.addRange(range);
      }
    });

    requestAnimationFrame(() => {
      outsideHandler = (e) => {
        if (!pop.contains(e.target) && !el.contains(e.target)) {
          removePopover();
        }
      };
      document.addEventListener('mousedown', outsideHandler);
    });
}

/* ── Teams: agentic compose pane ──────────────────────── */

// Called from app.js SSE handler when teams-compose pane event arrives
function _teamsReceiveComposeData(data) {
  // Clear selectedId FIRST — openThirdPane reads it to decide whether to call
  // tpLoadDetail, which would overwrite the compose pane once the async list
  // fetch completes. Clearing before openThirdPane prevents that overwrite.
  tpState.selectedId = null;
  // Ensure the pane is open and showing Teams
  if (!document.getElementById('third-pane')?.classList.contains('is-open') || tpState.type !== 'teams') {
    openThirdPane('teams');
  }
  // Defer compose render by one event-loop tick so openThirdPane's synchronous
  // DOM wipes (line 951: tp-detail-col reset to hint) complete first, and the
  // compose form lands AFTER those wipes rather than being wiped by them.
  setTimeout(() => {
    tpState.selectedId = null; // keep cleared in case something set it during openThirdPane
    const detailCol = document.getElementById('tp-detail-col');
    if (detailCol) _renderTeamsComposeForm(detailCol, data);
  }, 0);
}

function _resolveTeamsChatId(recipientEmails) {
  // Match a chat_id from loaded chats — MUST be exact member match to prevent mis-sends.
  // For 1:1: find a oneOnOne chat where the other member matches the email.
  // For group: find a chat where ALL members match (no more, no less).
  if (!tpState.list?.length || !recipientEmails.length) return '';
  const needEmails = new Set(recipientEmails.map(e => e.toLowerCase()));
  for (const chat of tpState.list) {
    const memberEmails = new Set((chat.member_emails || []).map(e => e.toLowerCase()));
    if (needEmails.size === 1) {
      // 1:1: must be a oneOnOne chat with exactly 1 other member matching
      if (chat.chat_type === 'oneOnOne' && memberEmails.size === 1 &&
          [...needEmails].every(e => memberEmails.has(e))) return chat.id;
    } else {
      // Group: exact member count + all match
      if (memberEmails.size === needEmails.size &&
          [...needEmails].every(e => memberEmails.has(e))) return chat.id;
    }
  }
  return '';
}

function _teamsComposePickChatIdForSend(knownChatId, recipientEmails) {
  if (knownChatId) return knownChatId;
  return _resolveTeamsChatId(recipientEmails);
}

function _teamsComposePeopleSearchQuery(value) {
  return (value || '').trim().replace(/^@+/, '').replace(/[._]+/g, ' ').replace(/\s+/g, ' ').trim();
}

async function _teamsFetchWithTimeout(url, options = {}, timeoutMs = 30000) {
  const ctrl = new AbortController();
  const callerSignal = options.signal;
  const onCallerAbort = () => ctrl.abort();
  if (callerSignal) callerSignal.addEventListener('abort', onCallerAbort, { once: true });

  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: ctrl.signal });
  } catch (err) {
    if (ctrl.signal.aborted) {
      const stoppedByUser = Boolean(callerSignal?.aborted);
      const e = new Error(stoppedByUser
        ? 'Stopped waiting for Teams send confirmation. The message may still have been sent.'
        : 'Timed out waiting for Teams send confirmation. The message may still have been sent.');
      e.code = 'TEAMS_SEND_CONFIRMATION_UNKNOWN';
      throw e;
    }
    throw err;
  } finally {
    clearTimeout(timer);
    if (callerSignal) callerSignal.removeEventListener('abort', onCallerAbort);
  }
}

function _markdownToTeamsHtml(text) {
  // Teams HTML body supports: <b>, <i>, <a href>, <br>, <p>.
  // Strategy: tokenise each line into segments so we escape plain text
  // but leave generated HTML tags untouched.
  const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

  function inlineToHtml(raw) {
    // Split on markdown links [label](url) and bare URLs, process segments.
    const tokens = [];
    const pattern = /(\[([^\]]+)\]\((https?:\/\/[^)]+)\))|(https?:\/\/[^\s<>"]+)/g;
    let last = 0, m;
    while ((m = pattern.exec(raw)) !== null) {
      if (m.index > last) tokens.push({ type: 'text', val: raw.slice(last, m.index) });
      if (m[1]) {
        tokens.push({ type: 'html', val: `<a href="${m[3]}">${esc(m[2])}</a>` });
      } else {
        tokens.push({ type: 'html', val: `<a href="${m[0]}">${esc(m[0])}</a>` });
      }
      last = m.index + m[0].length;
    }
    if (last < raw.length) tokens.push({ type: 'text', val: raw.slice(last) });

    // Now apply bold/italic to text segments, then join
    return tokens.map(t => {
      if (t.type === 'html') return t.val;
      let s = esc(t.val);
      s = s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
      s = s.replace(/__(.+?)__/g, '<b>$1</b>');
      s = s.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<i>$1</i>');
      return s;
    }).join('');
  }

  const lines = text.split('\n');
  const out = [];
  for (const line of lines) {
    const bulletMatch = line.match(/^[-*•]\s+(.+)/);
    if (bulletMatch) {
      out.push('<li>' + inlineToHtml(bulletMatch[1]) + '</li>');
    } else if (line.trim() === '') {
      out.push('<br>');
    } else {
      out.push('<p>' + inlineToHtml(line) + '</p>');
    }
  }
  return out.join('');
}

/**
 * After loading an AI draft into Quill via setText/dangerouslyPasteHTML,
 * scans the plain text for @Name patterns matching known recipients and replaces
 * them with real MentionBlot embeds so they render as chips. (#90)
 * Processes matches in reverse position order to avoid index drift.
 */
function _tpInjectMentionBlotsFromText(quill, recipients) {
  if (!recipients || !recipients.length) return;
  const text = quill.getText();
  const tasks = [];
  recipients.forEach(p => {
    if (!p.name && !p.email) return;
    const baseName = p.name || p.email.split('@')[0];
    // Build name variants to search: full "Last, First", first name, last name
    const variants = [baseName];
    if (baseName.includes(', ')) {
      const parts = baseName.split(', ');
      if (parts[1]) variants.push(parts[1]);    // first name
      if (parts[0]) variants.push(parts[0]);    // last name
    } else if (baseName.includes(' ')) {
      variants.push(baseName.split(' ')[0]);     // first word
    }
    variants.sort((a, b) => b.length - a.length); // longest first
    for (const variant of variants) {
      const pattern = new RegExp('@' + variant.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?![\\w,])', 'gi');
      let m;
      while ((m = pattern.exec(text)) !== null) {
        tasks.push({ idx: m.index, len: m[0].length, p, displayName: baseName });
      }
    }
  });
  if (!tasks.length) return;
  // Deduplicate by idx (same position matched by multiple variants)
  const seen = new Set();
  const unique = tasks.filter(t => { if (seen.has(t.idx)) return false; seen.add(t.idx); return true; });
  // Process in reverse so earlier indices aren't shifted by later insertions
  unique.sort((a, b) => b.idx - a.idx);
  unique.forEach(({ idx, len, p, displayName }) => {
    quill.deleteText(idx, len, 'silent');
    quill.insertEmbed(idx, 'mention', { id: p.id || '', name: displayName, email: p.email || '' }, 'silent');
  });
  const qlen = quill.getLength();
  if (qlen > 0) quill.setSelection(qlen - 1, 0);
}

function _renderTeamsComposeForm(container, data) {
  container.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'tc-compose-wrap';
  // chat_id passed from Claude (via read_teams_chats) or resolved client-side
  let _knownChatId = data.chat_id || '';
  console.log('[teams-compose] Init: chat_id=' + _knownChatId + ' to=' + (data.to || ''));

  // Header
  const header = document.createElement('div');
  header.className = 'tc-compose-header';
  header.textContent = '✉ Draft Teams Message';
  wrap.appendChild(header);

  // Context note (why Claude drafted this)
  if (data.context) {
    const ctx = document.createElement('div');
    ctx.className = 'tc-compose-context';
    ctx.textContent = data.context;
    wrap.appendChild(ctx);
  }

  function _composeRecipientDisplayName(email, name) {
    let raw = (name || '').trim() || (email || '').split('@')[0];
    if (raw.includes(', ')) {
      const parts = raw.split(', ', 2);
      raw = `${parts[1]} ${parts[0]}`;
    }
    return raw.replace(/[._]+/g, ' ').replace(/\s+/g, ' ').trim();
  }

  // Pre-populate recipient list from the agent-provided pane payload.
  // When chat_id is known but `to` is missing or placeholder, resolve members
  // from the already-loaded chat list so the compose form shows real names.
  let preEmails = (data.to || '').split(',').map(s => s.trim()).filter(Boolean);
  let preNames = (data.to_names || '').split(',').map(s => s.trim());
  const _looksLikeEmail = e => e && e.includes('@');
  if (_knownChatId && (!preEmails.length || !preEmails.every(_looksLikeEmail))) {
    const _chat = (tpState.list || []).find(c => c.id === _knownChatId);
    if (_chat && _chat.member_emails?.length) {
      preEmails = _chat.member_emails.slice();
      preNames = (_chat.member_names || []).slice();
      console.log('[teams-compose] resolved recipients from chat list:', preEmails);
    }
  }
  const preRecipients = preEmails.map((email, i) => ({
    email,
    name: _composeRecipientDisplayName(email, preNames[i]),
  }));

  // Resolve Graph IDs for pre-populated recipients in the background so they're
  // ready at send time (same lookup the recipient picker uses).
  // Promises are stored so the send handler can await them (#90).
  const _recipientIdPromises = [];
  for (const p of preRecipients) {
    if (p.id) continue;
    const q = _teamsComposePeopleSearchQuery(p.email);
    if (q.length < 2) continue;
    const prom = fetch(`/api/people/search?q=${encodeURIComponent(q)}`)
      .then(r => r.json())
      .then(data => {
        const match = (data.people || []).find(
          pp => pp.email && pp.email.toLowerCase() === p.email.toLowerCase()
        );
        if (match) {
          if (match.id) p.id = match.id;
          if (match.name) p.name = match.name;
        }
      })
      .catch(() => {});
    _recipientIdPromises.push(prom);
  }

  const _chatTopic = data.chat_topic || (tpState.list || []).find(c => c.id === _knownChatId)?.topic || '';

  // ── Always use editable recipient field — supports DM and group equally ──
  const toField = _buildRecipientField({
    label: 'To:',
    chipClass: 'chip-teams',
    avatarClass: 'tp-avatar-teams',
    normalizeSearch: true, orgOnly: true,
    onchange: info => {
      if (info?.recipientsChanged) _knownChatId = '';
      if (info?.recipientsChanged && groupBadge) groupBadge.style.display = 'none';
      updateSendBtn();
      _updateSendingToBar();
    },
  });
  toField.rowEl.classList.add('tc-compose-to');
  preRecipients.forEach(p => toField.addPerson(p, { preserveExistingChat: true, notify: false }));
  wrap.appendChild(toField.rowEl);

  // ── Group-chat badge: shown below To field when a known chat is pre-targeted ──
  // This is informational only — the actual recipients above control who gets the message.
  let groupBadge = null;
  if (_knownChatId && _chatTopic) {
    groupBadge = document.createElement('div');
    groupBadge.className = 'tc-compose-group-badge';
    groupBadge.innerHTML = `<span class="tc-group-badge-icon">\uD83D\uDCAC</span>` +
      `<span class="tc-group-badge-text">Targeting <strong>${escapeHtml(_chatTopic)}</strong> group chat</span>` +
      `<button class="tc-group-badge-clear" title="Switch to DM instead">\u2715</button>`;
    groupBadge.querySelector('.tc-group-badge-clear').addEventListener('click', () => {
      _knownChatId = '';
      groupBadge.style.display = 'none';
      _updateSendingToBar();
    });
    wrap.appendChild(groupBadge);
  }

  // Message editor — full Quill so users get the same toolbar (bold, italic,
  // link, emoji, discard) as the manual compose pane. Previously this was a
  // plain <textarea> for historical reasons; the toolbar is the only meaningful
  // UX difference between the manual and Gator-drafted flows.
  const msgWrap = document.createElement('div');
  msgWrap.className = 'tc-compose-field';
  const msgLabel = document.createElement('label');
  msgLabel.className = 'tc-compose-label';
  msgLabel.textContent = 'Message:';
  msgWrap.appendChild(msgLabel);
  const editor = _buildQuillEditor({ placeholder: 'Write your message…', showSendBtn: false, showResize: false });
  msgWrap.appendChild(editor.wrapEl);
  wrap.appendChild(msgWrap);

  // Pre-fill the draft Gator delivered. Gator may emit HTML (<p>, <b>, <a>, <ul>)
  // or plain text/markdown — sniff for tags so HTML renders formatted instead of
  // showing literal "<p>…</p>" in the editor.
  // Uses async IIFE so recipient id lookups can settle before mention chip injection (#90).
  (async () => {
    await new Promise(r => setTimeout(r, 0)); // yield to let Quill initialise
    if (!editor.quill) return;
    const raw = data.message || '';
    if (!raw) return;
    // Wait for recipient AAD id lookups so _tpInjectMentionBlotsFromText has p.id
    if (_recipientIdPromises.length) {
      await Promise.race([Promise.allSettled(_recipientIdPromises), new Promise(r => setTimeout(r, 2000))]);
    }
    const looksLikeHtml = /<(p|div|br|b|i|u|a|ul|ol|li|strong|em|h[1-6])\b[^>]*>/i.test(raw);
    if (looksLikeHtml) {
      // Normalise only the <a> tags — leave every other tag (ul/li/p/b/i) exactly
      // as Gator emitted it. Real links keep working; placeholder hrefs
      // (e.g. "REPLACE_WITH_ONEDRIVE_SHARE_LINK") have the <a> wrapper stripped
      // so they render as plain text instead of the styled-but-dead link Quill's
      // sanitizer would otherwise rewrite to about:blank.
      const safe = raw.replace(
        /<a\b[^>]*\bhref\s*=\s*(['"])([^'"]+)\1[^>]*>([\s\S]*?)<\/a>/gi,
        (_m, _q, href, inner) =>
          /^(https?:|mailto:|tel:)/i.test(href) ? `<a href="${href}">${inner}</a>` : inner,
      );
      try {
        editor.quill.clipboard.dangerouslyPasteHTML(0, safe);
      } catch {
        editor.quill.setText(raw);
      }
    } else {
      editor.quill.setText(raw);
    }
    // Inject MentionBlot chips for any @Name patterns matching known recipients (#90)
    _tpInjectMentionBlotsFromText(editor.quill, preRecipients);
    const len = editor.quill.getLength();
    if (len > 0) editor.quill.setSelection(len - 1, 0);
  })();

  // @mention + #channel dropdown — same path manual compose uses.
  // Mentions land as MentionBlot embeds; the helper below renders them back to
  // "@Name " plain text for the existing markdown-based send pipeline.
  // Use quill.root (the editable div) not msgWrap as the anchor — msgWrap has zero
  // or incorrect bounds at first @-trigger so FloatingUI positioned the picker at the
  // bottom of the screen. quill.root has the correct pixel bounds from the first keystroke (#120).
  setTimeout(() => { if (editor.quill) _wireMentionDropdownQuill(editor.quill, editor.quill.root); }, 50);

  // Shim that lets the rest of this function keep its textarea.value semantics.
  // Walks Quill's delta so mention embeds become "@Name" text — preserves the
  // downstream @Name regex + _markdownToTeamsHtml path unchanged.
  const textarea = {
    get value() {
      const q = editor.quill;
      if (!q) return '';
      let out = '';
      for (const op of q.getContents().ops) {
        if (typeof op.insert === 'string') out += op.insert;
        else if (op.insert && op.insert.mention) out += '@' + (op.insert.mention.name || '');
      }
      return out.replace(/\n+$/, '');
    },
    set value(v) {
      if (editor.quill) editor.quill.setText(v || '');
    },
    focus() { editor.quill && editor.quill.focus(); },
  };

  // ── "Sending to:" live resolution bar ──────────────────────────────────────
  // Shows the *actual* destination that will be used when Send is clicked —
  // resolved from the To field recipients + _knownChatId, same logic as send.
  const sendingToBar = document.createElement('div');
  sendingToBar.className = 'tc-compose-sending-to';
  wrap.appendChild(sendingToBar);

  function _updateSendingToBar() {
    const recipients = toField.getPeople();
    if (!recipients.length) {
      sendingToBar.innerHTML = '<span class="tc-st-label">Sending to:</span> <span class="tc-st-value tc-st-none">— add recipients above</span>';
      return;
    }
    const recipientEmails = recipients.map(p => p.email);
    const resolvedChatId = _teamsComposePickChatIdForSend(_knownChatId, recipientEmails);
    const resolvedChat = resolvedChatId ? (tpState.list || []).find(c => c.id === resolvedChatId) : null;

    if (resolvedChat) {
      const isGroup = resolvedChat.chat_type === 'group' || resolvedChat.chat_type === 'meeting';
      const chatLabel = resolvedChat.topic || resolvedChat.display_name || resolvedChatId;
      const typeLabel = isGroup ? ' (group chat)' : ' (DM)';
      sendingToBar.innerHTML =
        `<span class="tc-st-label">Sending to:</span> ` +
        `<span class="tc-st-value ${isGroup ? 'tc-st-group' : 'tc-st-dm'}">${escapeHtml(chatLabel)}</span>` +
        `<span class="tc-st-type">${typeLabel}</span>`;
    } else {
      // No existing chat found — will create new DM/group or use API fallback
      const nameList = recipients.map(p => p.name || p.email.split('@')[0]).join(', ');
      const isDm = recipients.length === 1;
      sendingToBar.innerHTML =
        `<span class="tc-st-label">Sending to:</span> ` +
        `<span class="tc-st-value tc-st-new">${escapeHtml(nameList)}</span>` +
        `<span class="tc-st-type"> (new ${isDm ? 'DM' : 'group'})</span>`;
    }
  }
  _updateSendingToBar();

  // Error area
  const errDiv = document.createElement('div');
  errDiv.className = 'tc-compose-error';
  errDiv.style.display = 'none';
  wrap.appendChild(errDiv);

  // Status area (above buttons, full-width)
  const statusArea = document.createElement('div');
  statusArea.className = 'tc-compose-status-area hidden';
  wrap.appendChild(statusArea);

  // Actions
  const actions = document.createElement('div');
  actions.className = 'tc-compose-actions';

  const refineBtn = document.createElement('button');
  refineBtn.className = 'tc-btn-refine';
  refineBtn.textContent = '✦ Refine with AI';
  refineBtn.title = 'Ask Claude to improve the draft';
  refineBtn.addEventListener('click', () => {
    const currentDraft = textarea.value.trim();
    const recipientStr = toField.getPeople().map(p => p.name || p.email).join(', ');
    tpInjectAIPrompt(`Please refine this Teams message draft to ${recipientStr}:\n\n${currentDraft}`);
  });

  const sendBtn = document.createElement('button');
  sendBtn.className = 'tc-btn-send';
  sendBtn.textContent = 'Send via Teams';
  sendBtn.disabled = toField.getPeople().length === 0;

  let sendAbortCtrl = null;
  let _isSending = false;

  function updateSendBtn() {
    if (!_isSending) sendBtn.disabled = toField.getPeople().length === 0;
  }

  function _enterSendingState() {
    _isSending = true;
    sendBtn.disabled = false;
    sendBtn.textContent = 'Cancel';
    sendBtn.classList.add('tc-btn-send-cancel');
    refineBtn.classList.add('hidden');
    statusArea.classList.remove('hidden');
  }

  function _exitSendingState(label) {
    _isSending = false;
    sendBtn.classList.remove('tc-btn-send-cancel');
    sendBtn.textContent = label || 'Send via Teams';
    refineBtn.classList.remove('hidden');
    refineBtn.disabled = false;
    updateSendBtn();
  }

  sendBtn.addEventListener('click', async () => {
    if (_isSending) {
      if (sendAbortCtrl) sendAbortCtrl.abort();
      return;
    }
    const recipients = toField.getPeople();
    if (!recipients.length) {
      errDiv.textContent = 'Please add at least one recipient.';
      errDiv.style.display = '';
      return;
    }
    const msg = textarea.value.trim();
    const rawHtml = editor.getHtml ? editor.getHtml() : '';
    if (!msg) {
      errDiv.textContent = 'Message cannot be empty.';
      errDiv.style.display = '';
      return;
    }
    errDiv.style.display = 'none';

    // ── Pre-send mismatch guard ───────────────────────────────────────────────
    // If a known chat is targeted, verify the To field recipients exactly match
    // that chat's members. If not, block the send — never silently redirect.
    if (_knownChatId) {
      const resolvedChat = (tpState.list || []).find(c => c.id === _knownChatId);
      if (resolvedChat && resolvedChat.member_emails?.length) {
        const chatMembers = new Set((resolvedChat.member_emails).map(e => e.toLowerCase()));
        const toMembers = new Set(recipients.map(p => p.email.toLowerCase()));
        const match = toMembers.size === chatMembers.size &&
                      [...toMembers].every(e => chatMembers.has(e));
        if (!match) {
          const chatName = resolvedChat.topic || resolvedChat.display_name || 'the targeted chat';
          const toNames = recipients.map(p => p.name || p.email).join(', ');
          const chatMemberList = (resolvedChat.member_emails || []).join(', ');
          errDiv.innerHTML =
            `<strong>Send blocked:</strong> The people in the To field (${escapeHtml(toNames)}) ` +
            `don't match the members of <strong>${escapeHtml(chatName)}</strong> (${escapeHtml(chatMemberList)}). ` +
            `Click <strong>✕</strong> on the group badge to switch to a new DM, or update the To field to match the group.`;
          errDiv.style.display = '';
          return;
        }
      }
    }
    // ─────────────────────────────────────────────────────────────────────────

    // Await any pending recipient AAD id lookups before sending (#90).
    // Without this, @mention regex fallback fires with p.id='' and Teams drops the mention.
    if (_recipientIdPromises.length) {
      await Promise.race([
        Promise.allSettled(_recipientIdPromises),
        new Promise(res => setTimeout(res, 2000)),
      ]);
    }

    _enterSendingState();
    const gatorStatus = _gatorSendStatus(statusArea);
    let chatId = '';
    sendAbortCtrl = new AbortController();
    try {
      const toStr = recipients.map(p => p.email).join(',');
      const recipientEmails = recipients.map(p => p.email);
      const usedKnownChatId = Boolean(_knownChatId);
      console.log('[teams-compose] Send: _knownChatId=' + _knownChatId);
      chatId = _teamsComposePickChatIdForSend(_knownChatId, recipientEmails);
      if (chatId && !usedKnownChatId) {
        const chat = (tpState.list || []).find(c => c.id === chatId);
        if (chat) {
          const chatMembers = new Set((chat.member_emails || []).map(e => e.toLowerCase()));
          const toMembers = new Set(recipients.map(p => p.email.toLowerCase()));
          const match = toMembers.size === chatMembers.size &&
                        [...toMembers].every(e => chatMembers.has(e));
          if (!match) {
            console.warn('[teams-send] chat_id member mismatch — dropping chat_id for safe resolution');
            chatId = '';
          }
        }
      }
      // Build HTML from Quill so manual formatting (bold/italic/links/lists) survives.
      // Same normalisation as the manual compose path: <p>→<div>, code-block flatten,
      // trailing-empty-block strip. Fall back to markdown conversion only when Quill
      // didn't give us HTML (e.g. plain-text only Gator draft never touched).
      let htmlMsg;
      const cleanHtml = rawHtml
        ? _stripTrailingEmptyBlocks(
            rawHtml
              .replace(/<p>/g, '<div>').replace(/<\/p>/g, '</div>')
              .replace(/<pre[^>]*class="ql-code-block-container"[^>]*>([\s\S]*?)<\/pre>/g, (_, inner) => {
                const lines = inner.replace(/<div[^>]*class="ql-code-block"[^>]*>(.*?)<\/div>/g, '$1\n').replace(/<br\s*\/?>/g, '\n');
                const text = lines.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trimEnd();
                return `<pre>${text}</pre>`;
              })
          )
        : '';
      htmlMsg = cleanHtml || _markdownToTeamsHtml(msg);

      // Mentions: prefer Quill MentionBlot embeds (dropdown-typed). Fall back to
      // matching "@Name" in the rendered HTML so users who typed without the
      // dropdown still trigger Teams notifications.
      const mentions = [];
      const _quillInst = editor.quill;
      const _hasEmbedMentions = _quillInst && _quillInst.getContents().ops.some(op => op.insert && op.insert.mention);
      if (_hasEmbedMentions) {
        const payload = _buildMentionPayload(_quillInst);
        if (payload.html) htmlMsg = payload.html;
        if (payload.mentions?.length) mentions.push(...payload.mentions);
      } else {
        for (const p of recipients) {
          const name = p.name || p.email.split('@')[0];
          const patterns = [name];
          // "Last, First" format: also try first name (after comma) and last name
          if (name.includes(', ')) {
            const parts = name.split(', ');
            if (parts[1]) patterns.push(parts[1]);  // first name: "Mayuresh"
            if (parts[0]) patterns.push(parts[0]);  // last name: "Kulkarni"
          } else if (name.includes(' ')) {
            patterns.push(name.split(' ')[0]);
          }
          patterns.sort((a, b) => b.length - a.length);
          for (const pat of patterns) {
            const escaped = pat.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            // Word-boundary guard prevents @Jan matching @Janet. Only match @Name
            // outside of tag attributes — restrict to text between '>' and '<'.
            const re = new RegExp('(>[^<]*?)@' + escaped + '(?![\\w])', 'i');
            if (re.test(htmlMsg)) {
              const i = mentions.length;
              htmlMsg = htmlMsg.replace(re,
                `$1<span itemscope itemtype="http://schema.skype.com/Mention" itemid="${i}">${name}</span>`);
              mentions.push({
                id: i,
                mentionText: name,
                mentioned: { user: { id: p.id || '', displayName: name, userIdentityType: 'aadUser' } },
              });
              break;
            }
          }
        }
      }
      const userIds = recipients.map(p => p.id || '').join(',');
      const body = {
        to: toStr,
        message: htmlMsg,
        html: true,
        recipients: recipients.map(p => ({ email: p.email, name: p.name || '', id: p.id || '' })),
      };
      if (mentions.length) body.mentions = mentions;
      if (chatId) body.chat_id = chatId;
      if (userIds.replace(/,/g, '')) body.user_ids = userIds;
      const resp = await _teamsFetchWithTimeout('/api/teams/send-message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: sendAbortCtrl.signal,
      });
      const result = await resp.json();
      if (resp.status === 401 || resp.status === 403) {
        gatorStatus.fail('Authentication expired');
        _showDetailAuthError(container);
        _exitSendingState();
        return;
      }
      if (!resp.ok) throw new Error(result.detail || 'Send failed');
      gatorStatus.success('Message delivered!');
      _exitSendingState('Send via Teams');
      // Keep compose usable after successful delivery.
      textarea.value = '';
      statusArea.classList.remove('hidden');
      setTimeout(() => {
        try { gatorStatus.clear(); } catch {}
        statusArea.classList.add('hidden');
      }, 2200);
      _postTeamsSuccessCard(recipients.map(p => p.name || p.email).join(', '));
      const sentChatId = result.chat_id || chatId;
      if (sentChatId) _knownChatId = sentChatId;
      if (sentChatId) {
        tpThreadCache.delete(sentChatId);
        _clearListCache('teams');
        // Ensure Teams pane is active before loading the thread detail
        // (user may be in Gator chat or another skill pane when this fires)
        if (tpState.type !== 'teams') openThirdPane('teams');
        tpLoadDetail(sentChatId);
        _fetchTeamsList().catch(() => {});
      } else {
        _fetchTeamsList().catch(() => {});
      }
    } catch (err) {
      if (err.code === 'TEAMS_SEND_CONFIRMATION_UNKNOWN') {
        gatorStatus.unknown('Status unknown \u2014 check the conversation before retrying.');
        _exitSendingState('Retry send');
      } else {
        gatorStatus.fail(err.message);
        _exitSendingState();
      }
    } finally {
      sendAbortCtrl = null;
    }
  });

  actions.appendChild(refineBtn);
  actions.appendChild(sendBtn);
  wrap.appendChild(actions);
  container.appendChild(wrap);
}

function _postTeamsSuccessCard(recipientNames) {
  const output = document.getElementById('messages');
  if (!output) return;
  const card = document.createElement('div');
  card.className = 'tc-success-card';
  card.innerHTML = `<span class="tc-success-check">✓</span><span>Teams message sent to <strong>${escapeHtml(recipientNames)}</strong></span>`;
  output.appendChild(card);
  output.scrollTop = output.scrollHeight;
}

/* ── Jira: agentic ticket creation + issue browser ─────── */

const _jiraState = {
  mode: 'list',          // 'list' | 'create'
  selectedKey: null,
  pendingPaneData: null, // holds data from SSE before pane is ready
};

// Track body-portalled dropdown panels so we can clean them up when form re-renders
const _jiraCselPanels = [];

/**
 * Build a fully-styled custom select dropdown (replaces native <select>).
 * The open panel is appended to document.body so it escapes any overflow:hidden parents.
 * Returns { el, getValue, setValue, setOptions, onChange }
 */
function _buildJiraSelect(opts, selectedVal) {
  let currentValue = selectedVal || (opts[0]?.value ?? '');
  let currentOpts = opts.slice();

  const container = document.createElement('div');
  container.className = 'jira-csel';

  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'jira-csel-trigger';

  const valueSpan = document.createElement('span');
  valueSpan.className = 'jira-csel-value';
  trigger.appendChild(valueSpan);
  trigger.insertAdjacentHTML('beforeend',
    `<svg class="jira-csel-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="6 9 12 15 18 9"/></svg>`);

  // Panel lives on body to escape overflow clipping
  const panel = document.createElement('div');
  panel.className = 'jira-csel-panel';
  document.body.appendChild(panel);
  _jiraCselPanels.push(panel);

  function positionPanel() {
    const r = trigger.getBoundingClientRect();
    panel.style.left  = r.left + 'px';
    panel.style.width = r.width + 'px';
    const spaceBelow = window.innerHeight - r.bottom;
    if (spaceBelow < 220 && r.top > 220) {
      panel.style.top    = 'auto';
      panel.style.bottom = (window.innerHeight - r.top + 4) + 'px';
      panel.style.maxHeight = (r.top - 8) + 'px';
    } else {
      panel.style.top    = (r.bottom + 4) + 'px';
      panel.style.bottom = 'auto';
      panel.style.maxHeight = Math.min(spaceBelow - 8, 280) + 'px';
    }
  }

  function openPanel() {
    document.querySelectorAll('.jira-csel.open').forEach(el => el.classList.remove('open'));
    document.querySelectorAll('.jira-csel-panel.open').forEach(el => el.classList.remove('open'));
    container.classList.add('open');
    positionPanel();
    panel.classList.add('open');
    if (panel._searchInput) { panel._searchInput.value = ''; panel._searchInput.focus(); }
    panel.querySelector('.jira-csel-option.selected')?.scrollIntoView({ block: 'nearest' });
  }

  function closePanel() {
    container.classList.remove('open');
    panel.classList.remove('open');
  }

  function updateDisplay(val, label) {
    currentValue = val;
    valueSpan.textContent = label || val || '';
    panel.querySelectorAll('.jira-csel-option').forEach(el =>
      el.classList.toggle('selected', el.dataset.value === val));
  }

  function buildOptions(newOpts) {
    panel.innerHTML = '';
    // Add search input if more than 5 options
    let searchInput;
    if (newOpts.length > 5) {
      searchInput = document.createElement('input');
      searchInput.className = 'jira-csel-search';
      searchInput.placeholder = 'Type to filter…';
      searchInput.addEventListener('click', e => e.stopPropagation());
      panel.appendChild(searchInput);
    }
    const listWrap = document.createElement('div');
    listWrap.className = 'jira-csel-list';
    panel.appendChild(listWrap);

    function renderItems(filter) {
      listWrap.innerHTML = '';
      const q = (filter || '').toLowerCase();
      const filtered = q ? newOpts.filter(o => o.label.toLowerCase().includes(q)) : newOpts;
      if (!filtered.length) {
        listWrap.innerHTML = '<div class="jira-csel-empty">No matches</div>';
        return;
      }
      filtered.forEach(opt => {
        const item = document.createElement('div');
        item.className = 'jira-csel-option';
        item.dataset.value = opt.value;
        item.textContent = opt.label;
        if (opt.value === currentValue) item.classList.add('selected');
        item.addEventListener('click', () => {
          updateDisplay(opt.value, opt.label);
          closePanel();
          container.dispatchEvent(new Event('change'));
        });
        listWrap.appendChild(item);
      });
    }
    renderItems('');
    if (searchInput) {
      searchInput.addEventListener('input', () => renderItems(searchInput.value));
    }
    panel._searchInput = searchInput;
  }

  trigger.addEventListener('click', () => {
    container.classList.contains('open') ? closePanel() : openPanel();
  });

  const outsideClick = (e) => {
    if (!container.contains(e.target) && !panel.contains(e.target)) closePanel();
  };
  document.addEventListener('click', outsideClick);
  container._jiraCleanup = () => {
    document.removeEventListener('click', outsideClick);
    panel.remove();
  };

  buildOptions(currentOpts);
  const init = currentOpts.find(o => o.value === currentValue) || currentOpts[0];
  if (init) updateDisplay(init.value, init.label);

  container.appendChild(trigger);

  return {
    el: container,
    getValue: () => currentValue,
    setValue: (val) => {
      const o = currentOpts.find(o => o.value === val);
      if (o) updateDisplay(o.value, o.label);
    },
    setOptions: (newOpts, selectVal) => {
      currentOpts = newOpts;
      buildOptions(newOpts);
      const target = newOpts.find(o => o.value === selectVal) || newOpts[0];
      if (target) updateDisplay(target.value, target.label);
      else { currentValue = ''; valueSpan.textContent = ''; }
    },
    onChange: (cb) => container.addEventListener('change', cb),
  };
}

const _JIRA_PRIORITY_COLORS = {
  Highest: '#d04437',
  High: '#f15c3c',
  Medium: '#f79232',
  Low: '#707070',
  Lowest: '#aaaaaa',
};

function _initJiraPane() {
  const listCol = document.getElementById('tp-list-col');
  const detailCol = document.getElementById('tp-detail-col');
  if (!listCol || !detailCol) return;

  // Left col: issue list (search is in the toolbar, consistent with Teams/Email)
  listCol.innerHTML = '';
  listCol.style.display = 'flex';
  listCol.style.flexDirection = 'column';
  listCol.style.overflow = 'hidden';

  const listContainer = document.createElement('div');
  listContainer.className = 'jira-issue-list';
  listContainer.id = 'jira-issue-list';
  listCol.appendChild(listContainer);

  // Wire toolbar search for JIRA — enter delegates to Claude
  const _tpSearchInput = document.getElementById('tp-search-input');
  if (_tpSearchInput) {
    _tpSearchInput.placeholder = 'Search issues (e.g. open bugs in ROCM)…';
    _tpSearchInput.oninput = null; // disable real-time filtering
    _tpSearchInput.onkeydown = (e) => {
      if (e.key !== 'Enter') return;
      const q = _tpSearchInput.value.trim();
      if (!q) return;
      tpInjectAIPrompt(`@jira ${q}`);
    };
  }

  // Wire toolbar "+" button → create issue form
  const addBtn = document.getElementById('tp-add-btn');
  if (addBtn) addBtn.onclick = () => _showJiraCreateForm();

  // Right col: gator empty state with contextual hints
  detailCol.innerHTML = _gatorDetailHint('jira');

  // Fetch sectioned "My Work" view
  _renderJiraMyWork(listContainer);
}

const _JIRA_COMPOSE_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>';
const _JIRA_CLOSE_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

let _jiraFormOpen = false;

function _jiraSetAddBtn(mode) {
  const btn = document.getElementById('tp-add-btn');
  if (!btn) return;
  if (mode === 'close') { btn.innerHTML = _JIRA_CLOSE_SVG; btn.title = 'Close form'; _jiraFormOpen = true; }
  else { btn.innerHTML = _JIRA_COMPOSE_SVG; btn.title = 'Create issue'; _jiraFormOpen = false; }
}

function _showJiraCreateForm() {
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return;
  // Toggle: if form is already open, close it
  if (_jiraFormOpen) {
    detailCol.innerHTML = _gatorDetailHint('jira');
    _jiraSetAddBtn('compose');
    return;
  }
  // Open form, toggle to X
  _jiraSetAddBtn('close');
  _renderJiraCreateForm(detailCol, {});
}

/* ── JIRA section collapse state ─────────────────────── */
const _jiraSectionState = {};
const _jiraDefaultCollapsed = { 'Assigned to Me': false, 'Reported by Me': true, 'Watching': true, 'Recently Updated': false, 'Saved Filters': true };
const _JIRA_SECTION_PAGE = 5;
const _jiraSectionShown = {};
let _jiraMyselfPromise = null;

function _renderJiraMyWork(container) {
  const cached = _getListCache('jira');
  if (cached) {
    _renderJiraSections(container, cached.data);
    return;
  }
  container.innerHTML = _gatorLoading();
  fetch('/api/jira/my-work')
    .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`); return d; })
    .then(data => {
      if (tpState.type !== 'jira') return; // pane switched mid-fetch — don't clobber
      _setListCache('jira', data);
      _renderJiraSections(container, data);
    })
    .catch(() => {
      // Fallback to old my-issues endpoint
      fetch('/api/jira/my-issues')
        .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d; })
        .then(data => {
          if (tpState.type !== 'jira') return; // pane switched mid-fetch
          const fallback = { assigned: data.issues || [], reported: [], watched: [], recent: [], filters: [] };
          _setListCache('jira', fallback);
          _renderJiraSections(container, fallback);
        })
        .catch(() => {
          if (tpState.type !== 'jira') return;
          container.innerHTML = '<div class="jira-empty">Could not load issues.<br>Use the search bar above or ask Claude.</div>';
        });
    });
}

function _renderJiraSections(container, data) {
  container.innerHTML = '';
  const sections = [
    { key: 'assigned', label: 'Assigned to Me', items: data.assigned || [] },
    { key: 'reported', label: 'Reported by Me', items: data.reported || [] },
    { key: 'watched',  label: 'Watching',       items: data.watched  || [] },
    { key: 'recent',   label: 'Recently Updated', items: data.recent || [] },
  ];

  sections.forEach(sec => {
    if (!sec.items.length && (_jiraDefaultCollapsed[sec.label] ?? true)) return; // hide empty collapsed sections
    const isCollapsed = _jiraSectionState[sec.key] ?? (_jiraDefaultCollapsed[sec.label] ?? true);

    // Section header
    const label = document.createElement('div');
    label.className = 'tp-section-label tp-section-collapsible';
    label.innerHTML = `<span class="tp-section-chevron">${isCollapsed ? '\u25B6' : '\u25BC'}</span> ${sec.label} <span class="tp-section-count">${sec.items.length}</span>`;
    label.addEventListener('click', () => {
      _jiraSectionState[sec.key] = !isCollapsed;
      _renderJiraSections(container, data);
    });
    container.appendChild(label);

    if (isCollapsed) return;

    // Items with pagination
    const maxShow = _jiraSectionShown[sec.key] || _JIRA_SECTION_PAGE;
    const visible = sec.items.slice(0, maxShow);
    if (!visible.length) {
      container.insertAdjacentHTML('beforeend', '<div class="jira-empty">None</div>');
      return;
    }
    visible.forEach(issue => container.appendChild(_buildJiraIssueRow(issue)));

    if (sec.items.length > maxShow) {
      const more = document.createElement('div');
      more.className = 'tp-section-load-more';
      more.textContent = `Show more (${sec.items.length - maxShow} remaining)`;
      more.addEventListener('click', () => {
        _jiraSectionShown[sec.key] = maxShow + _JIRA_SECTION_PAGE;
        _renderJiraSections(container, data);
      });
      container.appendChild(more);
    }
  });

  // Saved Filters section
  const filters = data.filters || [];
  if (filters.length) {
    const fCollapsed = _jiraSectionState['filters'] ?? (_jiraDefaultCollapsed['Saved Filters'] ?? true);
    const fLabel = document.createElement('div');
    fLabel.className = 'tp-section-label tp-section-collapsible';
    fLabel.innerHTML = `<span class="tp-section-chevron">${fCollapsed ? '\u25B6' : '\u25BC'}</span> Saved Filters <span class="tp-section-count">${filters.length}</span>`;
    fLabel.addEventListener('click', () => {
      _jiraSectionState['filters'] = !fCollapsed;
      _renderJiraSections(container, data);
    });
    container.appendChild(fLabel);

    if (!fCollapsed) {
      filters.forEach(f => {
        const row = document.createElement('div');
        row.className = 'jira-issue-row jira-filter-row';
        row.innerHTML = `<span class="jira-filter-icon">⊙</span><span class="jira-issue-summary" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</span>`;
        row.addEventListener('click', () => {
          document.querySelectorAll('.jira-issue-row.active').forEach(r => r.classList.remove('active'));
          row.classList.add('active');
          _runJiraFilter(f);
        });
        container.appendChild(row);
      });
    }
  }
}

function _runJiraFilter(filter) {
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return;
  detailCol.innerHTML = _gatorLoading();
  fetch(`/api/jira/filter-issues?jql=${encodeURIComponent(filter.jql)}`)
    .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d; })
    .then(data => {
      detailCol.innerHTML = '';
      const hdr = document.createElement('div');
      hdr.className = 'jira-list-header';
      hdr.style.cssText = 'padding:12px 16px 8px;font-size:13px;font-weight:600;color:var(--text);text-transform:none;letter-spacing:0';
      hdr.textContent = filter.name;
      detailCol.appendChild(hdr);
      const list = data.issues || [];
      if (!list.length) {
        detailCol.insertAdjacentHTML('beforeend', '<div class="jira-empty">No matching issues</div>');
        return;
      }
      const scroll = document.createElement('div');
      scroll.style.cssText = 'flex:1;overflow-y:auto;padding:0 4px';
      list.forEach(issue => scroll.appendChild(_buildJiraIssueRow(issue)));
      detailCol.appendChild(scroll);
    })
    .catch(e => {
      detailCol.innerHTML = `<div class="jira-empty">Filter failed: ${escapeHtml(e.message)}</div>`;
    });
}

function _renderJiraIssueList(container, issues, title) {
  if (issues) {
    // Render provided issue list (from agentic search)
    container.innerHTML = '';
    if (title) {
      const hdr = document.createElement('div');
      hdr.className = 'jira-list-header';
      hdr.textContent = title;
      container.appendChild(hdr);
    }
    if (!issues.length) {
      container.insertAdjacentHTML('beforeend', '<div class="jira-empty">No issues found</div>');
      return;
    }
    issues.forEach(issue => container.appendChild(_buildJiraIssueRow(issue)));
    return;
  }

  // Fetch sectioned "My Work" view
  _renderJiraMyWork(container);
}

function _buildJiraIssueRow(issue) {
  const row = document.createElement('div');
  row.className = 'jira-issue-row';
  row.dataset.id = issue.key;
  const color = _JIRA_PRIORITY_COLORS[issue.priority] || '#aaaaaa';
  row.innerHTML = `
    <span class="jira-priority-dot" style="background:${color}" title="${issue.priority || 'No priority'}"></span>
    <span class="jira-issue-key">${issue.key}</span>
    <span class="jira-issue-summary" title="${issue.summary}">${issue.summary}</span>
  `;
  row.appendChild(_createPinBtn('jira', issue.key, `${issue.key}: ${issue.summary}`, { url: issue.url, priority: issue.priority }));
  row.addEventListener('click', () => {
    document.querySelectorAll('.jira-issue-row.active').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
    tpState.selectedId = issue.key;
    const detailCol = document.getElementById('tp-detail-col');
    if (detailCol) _renderJiraIssueDetail(detailCol, issue.key, issue.url);
  });
  return row;
}

// Called from app.js SSE handler when jira-list pane event arrives
function _jiraUpdateIssueList(paneData) {
  const container = document.getElementById('jira-issue-list');
  if (!container) return;
  _renderJiraIssueList(container, paneData.issues || [], paneData.title || 'Search results');
}

// Called from app.js SSE handler when jira-create pane event arrives
function _jiraReceivePaneData(data) {
  // Ensure pane is open
  if (!document.getElementById('third-pane')?.classList.contains('is-open') || tpState.type !== 'jira') {
    openThirdPane('jira');
  }
  const detailCol = document.getElementById('tp-detail-col');
  if (detailCol) _renderJiraCreateForm(detailCol, data);
}

async function _renderJiraCreateForm(container, data) {
  // Clean up any stale portalled panels from a previous form render
  _jiraCselPanels.forEach(p => { p.remove(); });
  _jiraCselPanels.length = 0;
  container.innerHTML = _gatorLoading();

  // Fetch project list and priorities (cached for session — only cache non-empty results)
  let allProjects = [];
  let allPriorities = [];
  try {
    const fetches = [];
    if (window._jiraProjectsCache?.length) fetches.push(Promise.resolve({ projects: window._jiraProjectsCache }));
    else fetches.push(fetch('/api/jira/projects').then(r => r.ok ? r.json() : { projects: [] }));
    if (window._jiraPrioritiesCache?.length) fetches.push(Promise.resolve({ priorities: window._jiraPrioritiesCache }));
    else fetches.push(fetch('/api/jira/priorities').then(r => r.ok ? r.json() : { priorities: [] }));
    const [prData, pvData] = await Promise.all(fetches);
    allProjects = prData.projects || (Array.isArray(prData) ? prData : []);
    allPriorities = pvData.priorities || (Array.isArray(pvData) ? pvData : []);
    console.log('[JIRA] priorities loaded:', allPriorities.length, allPriorities);
    if (allProjects.length) window._jiraProjectsCache = allProjects;
    if (allPriorities.length) window._jiraPrioritiesCache = allPriorities;
  } catch (e) { console.warn('[JIRA] Failed to load projects/priorities:', e.message); }
  // Fallback priorities if API returned nothing
  if (!allPriorities.length) {
    allPriorities = ['Highest', 'High', 'Medium', 'Low', 'Lowest'].map(n => ({ id: n, name: n }));
    console.warn('[JIRA] Using fallback priorities');
  }

  // Fetch project meta (createmeta) — cached per project key for session
  if (!window._jiraMetaCache) window._jiraMetaCache = {};
  let issueTypes = data.issue_types || [];
  const _metaProject = data.project || (allProjects[0]?.key || '');
  if (_metaProject) {
    try {
      if (window._jiraMetaCache[_metaProject]) {
        const cached = window._jiraMetaCache[_metaProject];
        if (cached.issue_types?.length) issueTypes = cached.issue_types;
      } else {
        const mr = await fetch(`/api/jira/project-meta?project=${encodeURIComponent(_metaProject)}`);
        const md = await mr.json();
        window._jiraMetaCache[_metaProject] = md;
        if (md.issue_types?.length) issueTypes = md.issue_types;
      }
    } catch {}
  }

  container.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'jira-form-wrap';

  const _isEdit = !!data._editKey;
  const titleRow = document.createElement('div');
  titleRow.style.cssText = 'display:flex;align-items:center;justify-content:space-between';
  const title = document.createElement('h2');
  title.className = 'jira-form-title';
  title.textContent = _isEdit ? `Edit ${data._editKey}` : 'Create Jira Ticket';
  titleRow.appendChild(title);
  wrap.appendChild(titleRow);
  // Ensure toolbar + shows as X while form is open
  const _formAddBtn = document.getElementById('tp-add-btn');
  if (_formAddBtn) { _formAddBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'; _formAddBtn.title = 'Close form'; }

  // ── Status transition (edit mode only) ──
  if (_isEdit) {
    const statusWrap = _buildJiraLabeledField('Status', false);
    const statusRow = document.createElement('div');
    statusRow.style.cssText = 'display:flex;align-items:center;gap:8px';
    const statusBtn = document.createElement('button');
    statusBtn.className = 'jira-status-btn';
    statusBtn.textContent = 'Change Status…';
    statusBtn.addEventListener('click', () => {
      _jiraShowTransitions(data._editKey, statusBtn, container, '');
    });
    statusRow.appendChild(statusBtn);
    statusWrap.appendChild(statusRow);
    wrap.appendChild(statusWrap);

    // Load current status and display it
    fetch(`/api/jira/issue/${encodeURIComponent(data._editKey)}`)
      .then(async r => { const d = await r.json(); if (r.ok) return d; return null; })
      .then(issue => { if (issue) statusBtn.textContent = issue.status || 'Change Status…'; })
      .catch(() => {});
  }

  // ── Project select ──
  const projectWrap = _buildJiraLabeledField('Project', true);
  const projectOpts = allProjects.length
    ? allProjects.map(p => ({ value: p.key, label: `${p.key} — ${p.name}` }))
    : [{ value: data.project || '', label: data.project || 'Unknown' }];
  const projectCsel = _buildJiraSelect(projectOpts, data.project || projectOpts[0]?.value);
  if (_isEdit) {
    // Show project as read-only text — JIRA API doesn't support moving issues
    const projDisplay = document.createElement('div');
    projDisplay.className = 'jira-field-input';
    projDisplay.style.cssText = 'opacity:.6;cursor:not-allowed;user-select:none';
    projDisplay.textContent = data.project || '';
    projectWrap.appendChild(projDisplay);
  } else {
    projectWrap.appendChild(projectCsel.el);
  }
  wrap.appendChild(projectWrap);

  // ── Issue type select ──
  const typeWrap = _buildJiraLabeledField('Issue Type', true);
  const typeCsel = _buildJiraSelect([], '');
  typeWrap.appendChild(typeCsel.el);
  wrap.appendChild(typeWrap);

  // ── Summary ──
  const summaryWrap = _buildJiraLabeledField('Summary', true);
  const summaryInput = document.createElement('input');
  summaryInput.type = 'text';
  summaryInput.className = 'jira-field-input';
  summaryInput.value = data.summary || '';
  summaryInput.placeholder = 'Short, descriptive title';
  summaryWrap.appendChild(summaryInput);
  wrap.appendChild(summaryWrap);

  // ── Priority (use id for API, name for display) ──
  const priorityWrap = _buildJiraLabeledField('Priority', false);
  const priorityOpts = [{ value: '', label: 'No priority' }, ...allPriorities.map(p => ({ value: p.id || p.name || p, label: p.name || p }))];
  const defaultPriority = data.priority
    ? (allPriorities.find(p => p.name === data.priority)?.id || data.priority)
    : '';
  console.log('[JIRA] priority opts:', priorityOpts.length, 'default:', defaultPriority);
  const priorityCsel = _buildJiraSelect(priorityOpts, defaultPriority);
  let _activePriorityList = allPriorities; // tracks whichever list is currently shown in the priority dropdown
  priorityWrap.appendChild(priorityCsel.el);
  wrap.appendChild(priorityWrap);

  // ── Description ──
  const descWrap = _buildJiraLabeledField('Description', false);
  const descArea = document.createElement('textarea');
  descArea.className = 'jira-field-textarea';
  descArea.rows = 5;
  descArea.value = data.description || '';
  descArea.placeholder = 'Describe the issue in detail…';
  descWrap.appendChild(descArea);
  wrap.appendChild(descWrap);

  // ── Dynamic required fields container ──
  const reqContainer = document.createElement('div');
  reqContainer.id = 'jira-required-fields';
  wrap.appendChild(reqContainer);

  // ── Error area ──
  const errDiv = document.createElement('div');
  errDiv.className = 'jira-form-error';
  errDiv.style.display = 'none';
  wrap.appendChild(errDiv);

  // ── Actions ──
  const actions = document.createElement('div');
  actions.className = 'jira-form-actions';
  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'jira-btn-cancel';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.type = 'button';
  const createBtn = document.createElement('button');
  createBtn.className = 'jira-btn-create';
  createBtn.textContent = _isEdit ? 'Save Changes' : 'Create Ticket';
  createBtn.title = 'Gator will handle field validation and required fields';
  createBtn.type = 'button';
  actions.appendChild(cancelBtn);
  actions.appendChild(createBtn);
  wrap.appendChild(actions);

  container.appendChild(wrap);


  // Populate type dropdown and required fields
  const dynamicFieldBuilders = [];

  function populateTypes(types, selectedName) {
    const typeOpts = types.map(t => ({ value: t.name, label: t.name }));
    typeCsel.setOptions(typeOpts, selectedName || typeOpts[0]?.value);
    updateRequiredFields(types);
  }

  function updateRequiredFields(types) {
    reqContainer.innerHTML = '';
    dynamicFieldBuilders.length = 0;
    const selTypeName = typeCsel.getValue();
    const selType = types.find(t => t.name === selTypeName);
    if (!selType || !selType.required_fields?.length) return;
    const hdr = document.createElement('div');
    hdr.className = 'jira-req-fields-label';
    hdr.textContent = 'Required Fields';
    reqContainer.appendChild(hdr);
    // Priority: always use static dropdown, update options if project restricts them
    const STATIC_FIELDS = new Set(['summary', 'description', 'issuetype', 'project', 'priority']);
    const dynPriorityField = selType.required_fields.find(f => f.key === 'priority' && f.allowed?.length);
    if (dynPriorityField) {
      // Project restricts priorities — update static dropdown to show only allowed values
      const restricted = [{ value: '', label: 'No priority' }, ...dynPriorityField.allowed.map(a => ({ value: a.id || a.name, label: a.name }))];
      _activePriorityList = dynPriorityField.allowed;
      priorityCsel.setOptions(restricted, restricted[1]?.value || '');
    } else {
      // No restriction — reset to full global priorities
      const full = [{ value: '', label: 'No priority' }, ...allPriorities.map(p => ({ value: p.id || p.name || p, label: p.name || p }))];
      _activePriorityList = allPriorities;
      priorityCsel.setOptions(full, full[1]?.value || '');
    }
    const prefills = data.extra_fields || {};
    selType.required_fields.forEach(field => {
      if (STATIC_FIELDS.has(field.key)) return;
      const preselect = _jiraExtractPrefill(prefills[field.key]);
      if (field.type === 'object' && !field.allowed?.length) {
        // AMD Dynamic Field — fetch allowed options async, render as dropdown once loaded
        const proj = projectCsel.getValue();
        const issueTypeId = selType.id || '';
        const placeholder = document.createElement('div');
        placeholder.className = 'jira-field-wrap';
        placeholder.innerHTML = `<label class="jira-field-label jira-field-required">${field.name}</label><div class="jira-field-input" style="opacity:.5;font-size:12px">Loading options…</div>`;
        reqContainer.appendChild(placeholder);
        fetch(`/api/jira/field-options?field=${encodeURIComponent(field.key)}&fieldName=${encodeURIComponent(field.name)}&project=${encodeURIComponent(proj)}&issueType=${encodeURIComponent(issueTypeId)}`)
          .then(r => r.json())
          .then(data => {
            const opts = data.options || [];
            if (!opts.length) {
              placeholder.querySelector('div').textContent = `No options available — set "${field.name}" in Jira after creation`;
              return;
            }
            const dynField = { ...field, type: 'option', _isDynamic: true, allowed: opts };
            const { el, getValue, setError, clearError } = _buildJiraFieldFor(dynField, preselect);
            el.dataset.fieldKey = field.key;
            placeholder.replaceWith(el);
            dynamicFieldBuilders.push({ field: dynField, getValue, setError, clearError });
          })
          .catch(() => {
            placeholder.querySelector('div').textContent = `Could not load "${field.name}" options — set in Jira after creation`;
          });
        return;
      }
      const { el, getValue, setError, clearError } = _buildJiraFieldFor(field, preselect);
      el.dataset.fieldKey = field.key;
      reqContainer.appendChild(el);
      dynamicFieldBuilders.push({ field, getValue, setError, clearError });
    });
  }

  populateTypes(issueTypes, data.issue_type);

  typeCsel.onChange(() => updateRequiredFields(issueTypes));

  // Project change: re-fetch meta
  projectCsel.onChange(async () => {
    const proj = projectCsel.getValue();
    typeCsel.setOptions([{ value: '', label: 'Loading…' }], '');
    reqContainer.innerHTML = '';
    try {
      const mr = await fetch(`/api/jira/project-meta?project=${encodeURIComponent(proj)}`);
      const md = await mr.json();
      issueTypes = md.issue_types || [];
      populateTypes(issueTypes, '');
    } catch {
      typeCsel.setOptions([{ value: '', label: 'Error loading types' }], '');
      _activePriorityList = allPriorities;
    }
  });

  cancelBtn.addEventListener('click', () => {
    // Reset toolbar + button
    const _cancelAddBtn = document.getElementById('tp-add-btn');
    _jiraSetAddBtn('compose');
    if (_isEdit) {
      _renderJiraIssueDetail(container, data._editKey, '');
    } else {
      container.innerHTML = _gatorDetailHint('jira');
    }
  });

  createBtn.addEventListener('click', async () => {
    errDiv.style.display = 'none';
    summaryInput.classList.remove('jira-field-error-border');
    descArea.classList.remove('jira-field-error-border');
    priorityCsel.el.classList.remove('jira-field-error-border');

    const summary = summaryInput.value.trim();
    if (!summary) {
      summaryInput.classList.add('jira-field-error-border');
      summaryInput.focus();
      return;
    }

    // Collect extra fields
    const extraFields = {};
    // field_schemas tells the backend which keys need ADF wrapping (doc fields).
    // The backend owns ADF construction so it can apply the Cloud/Server guard correctly.
    const fieldSchemas = {};
    let hasError = false;
    dynamicFieldBuilders.forEach(({ field, getValue, setError, clearError }) => {
      clearError();
      const val = getValue();
      if (!val && field.required !== false) {
        setError(`${field.name} is required`);
        hasError = true;
      } else if (val) {
        const fsys = field.system || field.key;
        fieldSchemas[field.key] = field.type || 'string';
        if (field.type === 'user' || fsys === 'reporter' || fsys === 'assignee') {
          extraFields[field.key] = { accountId: val };
        } else if (field._isDynamic) {
          // AMD Dynamic Field — requires selectedOptionsList + asArray format
          const opt = (field.allowed || []).find(o => o.id === val);
          const label = opt?.name || val;
          extraFields[field.key] = { selectedOptionsList: [{ label, viewLabel: label, value: val }], asArray: [val] };
        } else if (field.type === 'option') {
          extraFields[field.key] = { id: val };
        } else if (field.type === 'array') {
          extraFields[field.key] = val.split ? val.split(',').map(s => s.trim()).filter(Boolean).map(s => ({ id: s })) : [{ id: String(val) }];
        } else if (field.type === 'object') {
          extraFields[field.key] = { asArray: [val] };
        } else {
          // doc fields and plain string fields both send the raw string;
          // the backend applies ADF wrapping for doc fields via field_schemas.
          extraFields[field.key] = val;
        }
      }
    });
    if (hasError) return;

    const project = projectCsel.getValue();
    const issueType = typeCsel.getValue();
    const desc = descArea.value.trim();
    const priVal = priorityCsel.getValue();
    const priObj = _activePriorityList.find(p => (p.id || p.name) === priVal);
    const priName = priObj?.name || priVal || '';

    const fieldParts = [];
    dynamicFieldBuilders.forEach(({ field, getValue }) => {
      const val = getValue();
      if (val) fieldParts.push(`${field.name}: ${val}`);
    });

    if (_isEdit) {
      const changes = [];
      const originalProject = data._editKey.split('-')[0];
      if (project !== originalProject) {
        errDiv.textContent = 'Moving issues between projects is not supported via the JIRA API. Please use the Move option in Jira directly.';
        errDiv.style.display = 'block';
        return;
      }
      if (summary !== (data.summary || '')) changes.push(`summary to "${summary}"`);
      if (desc !== (data.description || '')) changes.push(`description to "${desc}"`);
      if (priName && priName !== data.priority) changes.push(`priority to "${priName}"`);
      fieldParts.forEach(fp => changes.push(fp));
      if (!changes.length) {
        errDiv.textContent = 'No changes detected';
        errDiv.style.display = 'block';
        return;
      }
      const prompt = `@jira Update ${data._editKey}: change ${changes.join(', ')}`;
      tpInjectAIPrompt(prompt);
      container.innerHTML = _gatorDetailHint('jira');
      _jiraSetAddBtn('compose');
      return;
    }

    const payload = {
      project,
      summary,
      issue_type: issueType,
      description: desc,
      priority: priVal || '',
      extra_fields: extraFields,
      field_schemas: fieldSchemas,
    };

    const originalLabel = createBtn.textContent;
    createBtn.disabled = true;
    createBtn.textContent = 'Creating…';

    try {
      const resp = await fetch('/api/jira/create-issue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      let body = {};
      try {
        body = await resp.json();
      } catch {
        body = {};
      }

      if (!resp.ok) {
        // Close the form immediately — the AI is taking over, leaving the pre-filled
        // form open alongside the AI prompt would confuse the user.
        container.innerHTML = _gatorDetailHint('jira');
        _jiraSetAddBtn('compose');

        // Hand off to the AI agent silently. It will retry via jira_mutate with
        // correct field serialization and post a success card when done.
        _jiraHandoverToAgent(payload, fieldSchemas, body);
        return;
      }

      const issueKey = body.key || '';
      const issueUrl = body.url || '';
      container.innerHTML = _gatorDetailHint('jira');
      if (issueKey) {
        _renderJiraIssueDetail(container, issueKey, issueUrl);
        const listContainer = document.getElementById('jira-issue-list');
        if (listContainer) _renderJiraMyWork(listContainer);
        if (issueUrl) _postJiraSuccessCard(issueKey, issueUrl);
      } else {
        _jiraSetAddBtn('compose');
      }
    } catch (e) {
      errDiv.textContent = `Ticket creation failed: ${e.message || e}`;
      errDiv.style.display = 'block';
    } finally {
      createBtn.disabled = false;
      createBtn.textContent = originalLabel;
    }
  });
}

function _buildJiraLabeledField(label, required) {
  const wrap = document.createElement('div');
  wrap.className = 'jira-field-wrap';
  const lbl = document.createElement('label');
  lbl.className = 'jira-field-label' + (required ? ' jira-field-required' : '');
  lbl.textContent = label;
  wrap.appendChild(lbl);
  return wrap;
}

// Called when the form submit fails. Closes the form and hands field values to
// the AI agent to retry via jira_mutate with correct field serialization.
// The prompt is auto-submitted so the user doesn't need to do anything.
function _jiraHandoverToAgent(payload, fieldSchemas, errorBody) {
  const fieldLines = [];
  const ef = payload.extra_fields || {};
  Object.entries(ef).forEach(([k, v]) => {
    const schemaType = (fieldSchemas || {})[k] || '';
    const display = (typeof v === 'object') ? JSON.stringify(v) : String(v);
    fieldLines.push(`  ${k} (type: ${schemaType || 'unknown'}): ${display.slice(0, 200)}`);
  });

  const prompt = `@jira Please create this Jira ticket using jira_mutate — the form submission failed due to a field format issue. Use jira_get_project_meta first if needed to check field schemas, then call jira_mutate POST issue with correct ADF for any rich-text fields.

Project: ${payload.project}
Summary: ${payload.summary}
Issue type: ${payload.issue_type}
Description: ${payload.description || '(none)'}
Priority: ${payload.priority || '(none)'}
Extra fields:
${fieldLines.length ? fieldLines.join('\n') : '  (none)'}`;

  tpInjectAIPrompt(prompt);
  // Auto-submit so the user doesn't need to press Enter
  document.getElementById('chat-form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
}

// Recursively extract plain text from an ADF node tree.
// Handles text, mention, hardBreak, and all standard block types.
function _adfNodeToText(node) {
  if (!node || typeof node !== 'object') return '';
  if (node.type === 'text') return node.text || '';
  if (node.type === 'mention') return (node.attrs && (node.attrs.text || node.attrs.id)) || '';
  if (node.type === 'hardBreak') return '\n';
  const children = Array.isArray(node.content) ? node.content : [];
  const childText = children.map(_adfNodeToText).join('');
  const BLOCK = new Set(['paragraph','heading','blockquote','codeBlock','bulletList','orderedList','listItem','rule']);
  return BLOCK.has(node.type) ? childText + '\n' : childText;
}

// Extract a display string from an AI-pre-filled field value.
// Replaces String() which produced "[object Object]" for structured values.
function _jiraExtractPrefill(v) {
  if (v === undefined || v === null) return '';
  if (typeof v === 'string' || typeof v === 'number') return String(v);
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'object') {
    if (v.type === 'doc' && Array.isArray(v.content)) return _adfNodeToText(v).trim();
    if (v.name) return v.name;
    if (v.displayName) return v.displayName;
    if (v.value) return v.value;
    if (v.id) return String(v.id);
    if (v.accountId) return v.accountId;
  }
  return '';
}

function _buildJiraFieldFor(fieldDef, preselect = '') {
  const wrap = document.createElement('div');
  wrap.className = 'jira-field-wrap';
  const lbl = document.createElement('label');
  lbl.className = 'jira-field-label' + (fieldDef.required !== false ? ' jira-field-required' : '');
  lbl.textContent = fieldDef.name;
  wrap.appendChild(lbl);

  const errSpan = document.createElement('span');
  errSpan.className = 'jira-field-error';
  errSpan.style.display = 'none';

  const ftype = fieldDef.type || '';
  const fkey = fieldDef.key || '';
  const fsystem = fieldDef.system || fkey;
  let getVal, controlEl;

  if ((ftype === 'option' || ftype === 'array') && fieldDef.allowed?.length) {
    // Dropdown for option/array fields with allowed values
    const opts = [{ value: '', label: `Select ${fieldDef.name}\u2026` },
      ...fieldDef.allowed.map(v => ({
        value: v.id || v.name || v,
        label: v.name || v,
      }))];
    const csel = _buildJiraSelect(opts, preselect);
    controlEl = csel.el;
    getVal = csel.getValue;

  } else if (ftype === 'date' || fsystem === 'duedate' || fkey === 'duedate') {
    // Date picker
    const input = document.createElement('input');
    input.type = 'date';
    input.className = 'jira-field-input';
    if (preselect) input.value = preselect;
    controlEl = input;
    getVal = () => input.value; // already yyyy-MM-dd format

  } else if (ftype === 'number') {
    // Number input
    const input = document.createElement('input');
    input.type = 'number';
    input.className = 'jira-field-input';
    input.placeholder = `Enter ${fieldDef.name.toLowerCase()}`;
    input.min = '0';
    if (preselect) input.value = preselect;
    controlEl = input;
    getVal = () => input.value.trim() ? Number(input.value) : '';

  } else if (ftype === 'user' || fsystem === 'reporter' || fsystem === 'assignee') {
    // User field — shows display name, stores JIRA accountId/username for API
    const userWrap = document.createElement('div');
    userWrap.className = 'jira-user-field';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'jira-field-input';
    input.placeholder = 'Search people\u2026';
    input.addEventListener('input', () => { errSpan.style.display = 'none'; });
    let _jiraUserId = preselect || '';
    // Auto-fill reporter with current JIRA user
    if (!preselect && fsystem === 'reporter') {
      if (!_jiraMyselfPromise) {
        _jiraMyselfPromise = fetch('/api/jira/myself')
          .then(r => (r.ok ? r.json() : null))
          .catch(() => null);
      }
      _jiraMyselfPromise.then(d => {
        if (d && !input.value) {
          input.value = d.displayName || d.name || '';
          _jiraUserId = d.accountId || d.name || '';
          errSpan.style.display = 'none';
        } else if (!d) {
          errSpan.textContent = 'Unable to load Reporter. Verify Jira auth in Settings.';
          errSpan.style.display = 'block';
        }
      });
    }
    // Search JIRA users on input
    let _searchTimer = null;
    const dd = document.createElement('div');
    dd.className = 'jira-user-dropdown hidden';
    input.addEventListener('input', () => {
      _jiraUserId = ''; // clear stored ID when user types
      const q = input.value.trim();
      if (q.length < 2) { dd.classList.add('hidden'); return; }
      clearTimeout(_searchTimer);
      _searchTimer = setTimeout(async () => {
        try {
          const r = await fetch(`/api/jira/user-search?q=${encodeURIComponent(q)}`);
          const data = await r.json();
          const users = data.users || [];
          if (!users.length) { dd.classList.add('hidden'); return; }
          dd.innerHTML = '';
          users.forEach(u => {
            const opt = document.createElement('div');
            opt.className = 'jira-user-option';
            opt.textContent = `${u.display_name}${u.email ? ' (' + u.email + ')' : ''}`;
            opt.addEventListener('mousedown', e => {
              e.preventDefault();
              input.value = u.display_name;
              _jiraUserId = u.account_id || u.mention_id || u.username || '';
              dd.classList.add('hidden');
            });
            dd.appendChild(opt);
          });
          dd.classList.remove('hidden');
        } catch { dd.classList.add('hidden'); }
      }, 300);
    });
    input.addEventListener('blur', () => setTimeout(() => dd.classList.add('hidden'), 200));
    userWrap.appendChild(input);
    userWrap.appendChild(dd);
    controlEl = userWrap;
    getVal = () => _jiraUserId;

  } else if (ftype === 'doc') {
    // Rich-text field — textarea for multi-line input; backend wraps to ADF on Cloud.
    const textarea = document.createElement('textarea');
    textarea.className = 'jira-field-textarea';
    textarea.rows = 6;
    textarea.placeholder = `Enter ${fieldDef.name.toLowerCase()} (plain text)`;
    if (preselect) textarea.value = preselect;
    controlEl = textarea;
    getVal = () => textarea.value.trim();

  } else {
    // Default text input
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'jira-field-input';
    input.placeholder = ftype === 'array' ? 'Comma-separated values' : `Enter ${fieldDef.name.toLowerCase()}`;
    if (preselect) input.value = preselect;
    controlEl = input;
    getVal = () => input.value.trim();
  }

  wrap.appendChild(controlEl);
  wrap.appendChild(errSpan);

  return {
    el: wrap,
    getValue: getVal,
    setError: (msg) => { errSpan.textContent = msg; errSpan.style.display = 'block'; controlEl.classList.add('jira-field-error-border'); },
    clearError: () => { errSpan.style.display = 'none'; controlEl.classList.remove('jira-field-error-border'); },
  };
}

function _jiraUpdateFormFields(fieldData) {
  // Update existing JIRA form inputs with values from AI
  const form = document.querySelector('.jira-form-wrap');
  if (!form) return;
  Object.entries(fieldData).forEach(([key, val]) => {
    // Try to find input by field key — dynamic fields store key in data attributes
    const inputs = form.querySelectorAll('.jira-field-input, .jira-field-textarea');
    for (const inp of inputs) {
      const wrap = inp.closest('.jira-field-wrap');
      if (!wrap) continue;
      // Match by label text or data attribute
      const label = wrap.querySelector('.jira-field-label');
      if (label && (label.textContent.toLowerCase().includes(key.toLowerCase()) || wrap.dataset.fieldKey === key)) {
        if (inp.type === 'date') {
          inp.value = String(val);
        } else if (inp.type === 'number') {
          inp.value = String(val);
        } else {
          inp.value = String(val);
        }
        inp.dispatchEvent(new Event('input', { bubbles: true }));
        inp.dispatchEvent(new Event('change', { bubbles: true }));
        // Flash green to show it was updated
        inp.style.transition = 'border-color .3s';
        inp.style.borderColor = 'var(--accent, #22c55e)';
        setTimeout(() => { inp.style.borderColor = ''; }, 2000);
        break;
      }
    }
    // Also try standard fields
    if (key === 'summary') {
      const summaryInput = form.querySelector('.jira-field-input[placeholder*="summary" i], .jira-field-input');
      if (summaryInput && !summaryInput.closest('.jira-field-wrap')?.querySelector('.jira-field-label')) {
        summaryInput.value = String(val);
      }
    }
    if (key === 'duedate' || key === 'due_date') {
      const dateInputs = form.querySelectorAll('input[type="date"]');
      dateInputs.forEach(d => {
        if (!d.value) { d.value = String(val); d.style.borderColor = 'var(--accent)'; setTimeout(() => { d.style.borderColor = ''; }, 2000); }
      });
    }
  });
}

function _renderJiraIssueDetail(container, key, fallbackUrl) {
  container.innerHTML = _gatorLoading();
  fetch(`/api/jira/issue/${encodeURIComponent(key)}`)
    .then(async r => {
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      return data;
    })
    .then(issue => {
      container.innerHTML = '';

      // Standardized toolbar in the persistent header (#tp-detail-header).
      // The key link + type badge + summary + meta rows below are CONTENT and
      // stay in the jira-detail-wrap inside the content column.
      const _jUrl = issue.url || fallbackUrl;
      const _jPin = _createPinBtn('jira', issue.key, `${issue.key}: ${issue.summary}`, { url: issue.url, priority: issue.priority });
      tpBuildDetailToolbar({
        app: 'jira',
        title: { text: `${issue.key}: ${issue.summary || ''}`, title: issue.summary || '', onClick: () => window.open(_jUrl, '_blank', 'noopener') },
        actions: [
          { kind: 'ai', iconHtml: '✦', label: 'Summarize', title: 'Summarize this issue', group: 0,
            onClick: () => tpInjectAIPrompt(`@jira Summarize ${issue.key} including description, comments, and current status`) },
          { kind: 'ai', iconHtml: '✦', label: 'Suggest Fix', title: 'Suggest next steps or a fix', group: 0,
            onClick: () => tpInjectAIPrompt(`@jira Suggest next steps or a fix for ${issue.key}`) },
          { kind: 'icon', iconHtml: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>', title: 'Edit issue', group: 1,
            onClick: () => {
              _jiraSetAddBtn('close');
              _renderJiraCreateForm(container, {
                project: issue.key.split('-')[0],
                summary: issue.summary,
                description: issue.description || '',
                priority: issue.priority || '',
                _editKey: issue.key,
              });
            } },
          { kind: 'icon', iconHtml: _TP_EXT_LINK_SVG, title: 'Open in Jira', group: 1,
            onClick: () => window.open(_jUrl, '_blank', 'noopener') },
          { el: _jPin, kind: 'icon', title: 'Pin issue', group: 1 },
        ],
      });
      // Reset toolbar + button when detail view loads (form was closed)
      _jiraSetAddBtn('compose');

      const wrap = document.createElement('div');
      wrap.className = 'jira-detail-wrap';

      // ── Header ──
      const hdr = document.createElement('div');
      hdr.className = 'jira-detail-header';
      const keyLink = document.createElement('a');
      keyLink.href = issue.url || fallbackUrl;
      keyLink.target = '_blank';
      keyLink.className = 'jira-detail-key';
      keyLink.textContent = issue.key;
      const typeSpan = document.createElement('span');
      typeSpan.className = 'jira-detail-type';
      typeSpan.textContent = issue.type || '';
      hdr.appendChild(keyLink);
      hdr.appendChild(typeSpan);
      wrap.appendChild(hdr);

      const summary = document.createElement('div');
      summary.className = 'jira-detail-summary';
      summary.textContent = issue.summary;
      wrap.appendChild(summary);

      // ── Meta grid with inline actions ──
      const meta = document.createElement('div');
      meta.className = 'jira-detail-meta';

      // Status — clickable transition dropdown
      const statusRow = document.createElement('div');
      statusRow.className = 'jira-detail-meta-row';
      statusRow.innerHTML = `<span class="jira-detail-meta-label">Status</span>`;
      const statusBtn = document.createElement('button');
      statusBtn.className = 'jira-status-btn';
      statusBtn.textContent = issue.status || 'Unknown';
      statusBtn.title = 'Click to change status';
      statusBtn.addEventListener('click', () => _jiraShowTransitions(issue.key, statusBtn, container, fallbackUrl));
      statusRow.appendChild(statusBtn);
      meta.appendChild(statusRow);

      // Priority — clickable dropdown
      const priorityRow = document.createElement('div');
      priorityRow.className = 'jira-detail-meta-row';
      priorityRow.innerHTML = `<span class="jira-detail-meta-label">Priority</span>`;
      const priorityBtn = document.createElement('button');
      priorityBtn.className = 'jira-inline-edit';
      const pColor = _JIRA_PRIORITY_COLORS[issue.priority] || '#aaa';
      priorityBtn.innerHTML = `<span class="jira-priority-dot" style="background:${pColor};display:inline-block;vertical-align:middle;margin-right:4px"></span>${escapeHtml(issue.priority || 'None')}`;
      priorityBtn.title = 'Click to change priority';
      priorityBtn.addEventListener('click', () => _jiraShowPriorityPicker(issue.key, priorityBtn, container, fallbackUrl));
      priorityRow.appendChild(priorityBtn);
      meta.appendChild(priorityRow);

      // Assignee — clickable edit
      const assigneeRow = document.createElement('div');
      assigneeRow.className = 'jira-detail-meta-row';
      assigneeRow.innerHTML = `<span class="jira-detail-meta-label">Assignee</span>`;
      const assigneeBtn = document.createElement('button');
      assigneeBtn.className = 'jira-inline-edit';
      assigneeBtn.textContent = issue.assignee || 'Unassigned';
      assigneeBtn.title = 'Click to reassign';
      assigneeBtn.addEventListener('click', () => _jiraShowAssigneePicker(issue.key, assigneeBtn, container, fallbackUrl));
      assigneeRow.appendChild(assigneeBtn);
      meta.appendChild(assigneeRow);

      // Static fields
      const staticFields = [
        ['Reporter', issue.reporter],
        ['Created',  issue.created],
        ['Updated',  issue.updated],
      ];
      if (issue.labels?.length) staticFields.push(['Labels', issue.labels.join(', ')]);
      if (issue.components?.length) staticFields.push(['Components', issue.components.join(', ')]);
      if (issue.fix_versions?.length) staticFields.push(['Fix Versions', issue.fix_versions.join(', ')]);
      staticFields.forEach(([label, value]) => {
        if (!value) return;
        const row = document.createElement('div');
        row.className = 'jira-detail-meta-row';
        row.innerHTML = `<span class="jira-detail-meta-label">${label}</span><span class="jira-detail-meta-value">${escapeHtml(String(value))}</span>`;
        meta.appendChild(row);
      });
      wrap.appendChild(meta);

      // ── Description ──
      if (issue.description) {
        const descHdr = document.createElement('div');
        descHdr.className = 'jira-detail-section-label';
        descHdr.textContent = 'Description';
        wrap.appendChild(descHdr);
        const desc = document.createElement('div');
        desc.className = 'jira-detail-description';
        desc.textContent = issue.description;
        wrap.appendChild(desc);
      }

      // ── Comments ──
      const cHdr = document.createElement('div');
      cHdr.className = 'jira-detail-section-label';
      cHdr.textContent = issue.comments?.length ? `Comments (${issue.comments.length})` : 'Comments';
      wrap.appendChild(cHdr);

      if (issue.comments?.length) {
        issue.comments.forEach(c => {
          const comment = document.createElement('div');
          comment.className = 'jira-detail-comment';
          comment.innerHTML = `<div class="jira-detail-comment-author">${escapeHtml(c.author)} · ${escapeHtml(c.created)}</div><div class="jira-detail-comment-body">${escapeHtml(c.body)}</div>`;
          wrap.appendChild(comment);
        });
      }

      // ── Inline Comment Compose ──
      const compose = document.createElement('div');
      compose.className = 'jira-comment-compose';
      const textarea = document.createElement('textarea');
      textarea.className = 'jira-comment-input';
      textarea.placeholder = 'Add a comment…';
      textarea.rows = 1;
      const sendBtn = document.createElement('button');
      sendBtn.className = 'jira-comment-send';
      sendBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`;
      sendBtn.disabled = true;
      sendBtn.title = 'Send comment';
      compose.appendChild(textarea);
      compose.appendChild(sendBtn);
      // Auto-grow textarea
      textarea.addEventListener('input', () => {
        sendBtn.disabled = !textarea.value.trim();
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
      });
      sendBtn.addEventListener('click', async () => {
        const text = textarea.value.trim();
        if (!text) return;
        sendBtn.disabled = true;
        textarea.disabled = true;
        try {
          const r = await fetch(`/api/jira/issue/${encodeURIComponent(issue.key)}/comment`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comment: text }),
          });
          if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Failed'); }
          _renderJiraIssueDetail(container, issue.key, fallbackUrl);
        } catch (e) {
          textarea.disabled = false;
          sendBtn.disabled = false;
          _showAlert('Failed: ' + e.message, 'error');
        }
      });
      // Enter to send, Shift+Enter for newline
      textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey && textarea.value.trim()) {
          e.preventDefault();
          sendBtn.click();
        }
      });
      wrap.appendChild(compose);

      container.appendChild(wrap);
    })
    .catch(err => {
      container.innerHTML = `<div class="jira-empty" style="color:#f87171;padding:20px">⚠ ${escapeHtml(err.message)}</div>`;
    });
}

/* ── Inline Status Transition ──────────────────────── */
function _jiraShowTransitions(issueKey, btn, container, fallbackUrl) {
  document.querySelectorAll('.jira-status-dropdown').forEach(d => d.remove());
  const dd = document.createElement('div');
  dd.className = 'jira-status-dropdown';
  dd.innerHTML = '<div class="jira-dd-loading">Loading…</div>';
  // Anchor to nearest positioned parent or button parent
  const anchor = btn.closest('.jira-detail-meta') || btn.closest('.jira-field-wrap') || btn.parentElement;
  anchor.style.position = 'relative';
  anchor.appendChild(dd);
  // Position below the button
  const btnRect = btn.getBoundingClientRect();
  const anchorRect = anchor.getBoundingClientRect();
  dd.style.left = Math.max(0, btnRect.left - anchorRect.left) + 'px';
  dd.style.top = (btnRect.bottom - anchorRect.top + 4) + 'px';

  fetch(`/api/jira/issue/${encodeURIComponent(issueKey)}/transitions`)
    .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d; })
    .then(data => {
      dd.innerHTML = '';
      (data.transitions || []).forEach(t => {
        const item = document.createElement('div');
        item.className = 'jira-dd-item';
        item.textContent = t.name;
        item.addEventListener('click', () => {
          dd.remove();
          // Delegate to Claude — it handles required fields conversationally
          tpInjectAIPrompt(`@jira Transition ${issueKey} to "${t.name}"`);
        });
        dd.appendChild(item);
      });
      if (!data.transitions?.length) dd.innerHTML = '<div class="jira-dd-loading">No transitions available</div>';
    })
    .catch((e) => { dd.innerHTML = `<div class="jira-dd-loading">Failed: ${escapeHtml(e.message)}</div>`; });

  setTimeout(() => document.addEventListener('click', function _close(e) {
    if (!dd.contains(e.target) && e.target !== btn) { dd.remove(); document.removeEventListener('click', _close); }
  }), 10);
}

/* ── Inline Priority Picker ────────────────────────── */
function _jiraShowPriorityPicker(issueKey, btn, container, fallbackUrl) {
  document.querySelectorAll('.jira-status-dropdown').forEach(d => d.remove());
  const dd = document.createElement('div');
  dd.className = 'jira-status-dropdown';
  dd.innerHTML = '<div class="jira-dd-loading">Loading…</div>';
  btn.parentElement.appendChild(dd);
  btn.parentElement.style.position = 'relative';

  fetch('/api/jira/priorities')
    .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d; })
    .then(data => {
      dd.innerHTML = '';
      const allP = (data.priorities || data || []);
      // Add search if many priorities
      let searchInput;
      if (allP.length > 5) {
        searchInput = document.createElement('input');
        searchInput.className = 'jira-dd-search';
        searchInput.placeholder = 'Filter…';
        searchInput.addEventListener('click', e => e.stopPropagation());
        dd.appendChild(searchInput);
      }
      const listWrap = document.createElement('div');
      listWrap.className = 'jira-dd-results';
      dd.appendChild(listWrap);

      function renderPriorities(filter) {
        listWrap.innerHTML = '';
        const q = (filter || '').toLowerCase();
        allP.forEach(p => {
          const name = p.name || p;
          if (q && !name.toLowerCase().includes(q)) return;
          const item = document.createElement('div');
          item.className = 'jira-dd-item';
          const color = _JIRA_PRIORITY_COLORS[name] || '#aaa';
          item.innerHTML = `<span class="jira-priority-dot" style="background:${color};display:inline-block;vertical-align:middle;margin-right:6px"></span>${escapeHtml(name)}`;
          item.addEventListener('click', async () => {
            dd.remove();
            btn.textContent = 'Updating…';
            try {
              await fetch(`/api/jira/issue/${encodeURIComponent(issueKey)}/assign`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ priority: name }),
              });
              _renderJiraIssueDetail(container, issueKey, fallbackUrl);
            } catch { btn.textContent = 'Error'; }
          });
          listWrap.appendChild(item);
        });
      }
      renderPriorities('');
      if (searchInput) { searchInput.addEventListener('input', () => renderPriorities(searchInput.value)); searchInput.focus(); }
    })
    .catch(() => { dd.innerHTML = '<div class="jira-dd-loading">Failed to load</div>'; });

  setTimeout(() => document.addEventListener('click', function _close(e) {
    if (!dd.contains(e.target) && e.target !== btn) { dd.remove(); document.removeEventListener('click', _close); }
  }), 10);
}

/* ── Inline Assignee Picker ────────────────────────── */
function _jiraShowAssigneePicker(issueKey, btn, container, fallbackUrl) {
  document.querySelectorAll('.jira-status-dropdown').forEach(d => d.remove());
  const dd = document.createElement('div');
  dd.className = 'jira-status-dropdown';
  dd.innerHTML = `<input class="jira-dd-search" placeholder="Search users…" autofocus /><div class="jira-dd-results"></div>`;
  btn.parentElement.appendChild(dd);
  btn.parentElement.style.position = 'relative';

  const input = dd.querySelector('input');
  const results = dd.querySelector('.jira-dd-results');
  let debounce;
  input.addEventListener('input', () => {
    clearTimeout(debounce);
    const q = input.value.trim();
    if (q.length < 2) { results.innerHTML = '<div class="jira-dd-loading">Type 2+ chars…</div>'; return; }
    debounce = setTimeout(async () => {
      results.innerHTML = '<div class="jira-dd-loading">Searching…</div>';
      try {
        const r = await fetch(`/api/jira/user-search?q=${encodeURIComponent(q)}`);
        const data = await r.json();
        const users = data.users || data || [];
        results.innerHTML = '';
        if (!users.length) { results.innerHTML = '<div class="jira-dd-loading">No users found</div>'; return; }
        users.forEach(u => {
          const item = document.createElement('div');
          item.className = 'jira-dd-item';
          item.textContent = u.displayName || u.name || u.display_name || '';
          item.addEventListener('click', async () => {
            dd.remove();
            btn.textContent = 'Updating…';
            try {
              await fetch(`/api/jira/issue/${encodeURIComponent(issueKey)}/assign`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ assignee: u.name || u.accountId || u.account_id || '' }),
              });
              _renderJiraIssueDetail(container, issueKey, fallbackUrl);
            } catch { btn.textContent = 'Error'; }
          });
          results.appendChild(item);
        });
      } catch { results.innerHTML = '<div class="jira-dd-loading">Search failed</div>'; }
    }, 300);
  });

  setTimeout(() => {
    input.focus();
    document.addEventListener('click', function _close(e) {
      if (!dd.contains(e.target) && e.target !== btn) { dd.remove(); document.removeEventListener('click', _close); }
    });
  }, 10);
}

function _postJiraSuccessCard(key, url) {
  const output = document.getElementById('messages');
  if (!output) return;
  const card = document.createElement('div');
  card.className = 'message assistant';
  card.innerHTML = `
    <div class="bubble card-bubble">
      <div class="gator-compose-card gator-success-card-chat">
        <div class="gcc-header">
          <div class="gcc-gator">
            <span class="gcc-gator-icon">\uD83D\uDC0A</span>
            <span class="gcc-gator-trail">
              <span class="gcc-dot gcc-dot-1"></span>
              <span class="gcc-dot gcc-dot-2"></span>
              <span class="gcc-dot gcc-dot-3"></span>
            </span>
            <span class="gcc-pane-icon">\uD83C\uDFAB</span>
          </div>
          <div class="gcc-title">Ticket hatched!</div>
        </div>
        <div class="gcc-body">
          <div class="gcc-recipient"><a href="${url}" target="_blank" style="color:var(--accent);font-weight:600;text-decoration:none">${key}</a> &mdash; created and ready to track</div>
        </div>
        <div class="gcc-footer">
          <span class="gcc-tagline">The Gator delivers. Every time.</span>
        </div>
      </div>
    </div>`;
  output.appendChild(card);
  output.scrollTop = output.scrollHeight;
}

/* ══════════════════════════════════════════════════════════════
   GITHUB PANE
   ══════════════════════════════════════════════════════════ */

const _ghState = {
  activeTab: 'reviews',
  list: [],
  selectedId: null,
  loading: false,
};

function _initGithubPane() {
  const pane = document.getElementById('third-pane');
  pane.querySelector('#tp-list-col').innerHTML = _ghShell();
  pane.querySelector('#tp-detail-col').innerHTML = _ghDetailEmpty();
  _ghBindTabs();
  _ghLoadTab(_ghState.activeTab);
}

function _ghShell() {
  return `
  <div style="display:flex;flex-direction:column;height:100%;overflow:hidden;">
    <div style="display:flex;border-bottom:1px solid var(--border);flex-shrink:0;">
      ${['reviews','issues','prs','repos'].map(t => `
        <button class="gh-tab${t === _ghState.activeTab ? ' gh-tab-active' : ''}"
          data-tab="${t}" style="background:none;border:none;color:${t===_ghState.activeTab?'var(--text)':'var(--text-dim)'};
          font-size:12px;font-weight:500;padding:8px 10px;cursor:pointer;
          border-bottom:2px solid ${t===_ghState.activeTab?'var(--accent)':'transparent'};
          margin-bottom:-1px;white-space:nowrap;transition:color .15s,border-color .15s;">
          ${t==='reviews'?'Review Requests':t==='issues'?'My Issues':t==='prs'?'My PRs':'Repos'}
        </button>`).join('')}
    </div>
    <div id="gh-list-body" style="flex:1;overflow-y:auto;"></div>
  </div>`;
}

function _ghDetailEmpty() {
  return `<div style="display:flex;align-items:center;justify-content:center;height:100%;
    color:var(--text-sub);font-size:12px;flex-direction:column;gap:8px;">
    <span style="font-size:28px;opacity:.4;">🐙</span>Select an item to view details</div>`;
}

function _ghBindTabs() {
  document.querySelectorAll('.gh-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.gh-tab').forEach(b => {
        b.classList.remove('gh-tab-active');
        b.style.color = 'var(--text-dim)';
        b.style.borderBottomColor = 'transparent';
      });
      btn.classList.add('gh-tab-active');
      btn.style.color = 'var(--text)';
      btn.style.borderBottomColor = 'var(--accent)';
      _ghState.activeTab = btn.dataset.tab;
      _ghState.selectedId = null;
      document.getElementById('tp-detail-col').innerHTML = _ghDetailEmpty();
      _ghLoadTab(_ghState.activeTab);
    });
  });
}

async function _ghLoadTab(tab) {
  const body = document.getElementById('gh-list-body');
  if (!body) return;
  body.innerHTML = _ghSkeleton();
  try {
    let result;
    if (tab === 'reviews') {
      result = await _ghDirectTool('github_list_review_requests', {});
      if (tpState.type !== 'github' || !body.isConnected) return; // pane switched mid-fetch
      _ghRenderPRList(body, result?.items || result?.pull_requests || []);
    } else if (tab === 'issues') {
      result = await _ghDirectTool('github_list_my_issues', {});
      if (tpState.type !== 'github' || !body.isConnected) return;
      _ghRenderIssueList(body, result?.items || result?.issues || []);
    } else if (tab === 'prs') {
      result = await _ghDirectTool('github_list_my_prs', {});
      if (tpState.type !== 'github' || !body.isConnected) return;
      _ghRenderPRList(body, result?.items || result?.pull_requests || []);
    } else if (tab === 'repos') {
      result = await _ghDirectTool('github_list_my_repos', {});
      if (tpState.type !== 'github' || !body.isConnected) return;
      _ghRenderRepoList(body, result?.items || result?.repositories || []);
    }
  } catch (e) {
    if (tpState.type !== 'github' || !body.isConnected) return;
    body.innerHTML = `<div style="padding:16px;color:var(--danger);font-size:12px;">Error: ${e.message}</div>`;
  }
}

async function _ghDirectTool(tool, input) {
  const res = await fetch('/api/github/tool', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool, input }),
  });
  return res.json();
}

function _ghSkeleton() {
  return `<style>@keyframes gh-shimmer{0%,100%{opacity:.4}50%{opacity:.7}}</style>` +
    Array(5).fill(0).map(() => `
    <div style="padding:9px 10px;border-bottom:1px solid var(--border);display:flex;gap:8px;">
      <div style="width:8px;height:8px;border-radius:50%;background:var(--surface3);margin-top:4px;
        flex-shrink:0;animation:gh-shimmer 1.5s infinite;"></div>
      <div style="flex:1;">
        <div style="height:12px;background:var(--surface3);border-radius:4px;margin-bottom:6px;width:80%;
          animation:gh-shimmer 1.5s infinite;"></div>
        <div style="height:10px;background:var(--surface3);border-radius:4px;width:50%;
          animation:gh-shimmer 1.5s infinite;"></div>
      </div>
    </div>`).join('');
}

function _ghStateDot(state, draft) {
  if (draft) return `<div style="width:8px;height:8px;border-radius:50%;border:2px solid #6e7681;
    flex-shrink:0;margin-top:4px;"></div>`;
  const color = { OPEN:'#3fb950', MERGED:'#a371f7', CLOSED:'#f85149' }[state] || '#6e7681';
  return `<div style="width:8px;height:8px;border-radius:50%;background:${color};
    flex-shrink:0;margin-top:4px;box-shadow:0 0 0 2px ${color}33;"></div>`;
}

function _ghLabel(name, color) {
  const bg = color ? `#${color}30` : 'rgba(110,118,129,.18)';
  const fg = color ? `#${color}` : '#8b949e';
  return `<span style="font-size:10px;font-weight:600;padding:1px 6px;border-radius:10px;
    line-height:1.5;background:${bg};color:${fg};">${_ghEsc(name)}</span>`;
}

function _ghAge(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function _ghAvatar(login) {
  const initials = (login || '?').slice(0, 2).toUpperCase();
  return `<div style="width:16px;height:16px;border-radius:50%;background:var(--surface3);
    display:inline-flex;align-items:center;justify-content:center;font-size:9px;
    color:var(--text-dim);border:1px solid var(--border2);flex-shrink:0;">${initials}</div>`;
}

function _ghEsc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _ghRenderPRList(body, items) {
  if (!items.length) {
    body.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:200px;gap:8px;color:var(--text-sub);font-size:12px;">
      <span style="font-size:24px;opacity:.5;">✓</span>No pending reviews — you're clear</div>`;
    return;
  }
  body.innerHTML = items.map(pr => {
    const state = pr.draft ? 'DRAFT' : (pr.state || 'OPEN').toUpperCase();
    const dot = _ghStateDot(state, pr.draft);
    const repo = pr.repository ? `${pr.repository.owner?.login||''}/${pr.repository.name}`
                                : (pr.base?.repo?.full_name || pr.repositoryNameWithOwner || '');
    const labels = (pr.labels || []).map(l => _ghLabel(l.name, l.color)).join('');
    const meta = `<span style="font-size:11px;color:var(--text-sub);font-family:monospace;">#${pr.number}</span>
      <span style="font-size:10px;color:var(--text-sub);">${_ghEsc(repo)}</span>${labels}`;
    const right = `<span style="font-size:10px;color:var(--text-sub);">${_ghAge(pr.created_at||pr.createdAt)}</span>
      ${_ghAvatar(pr.user?.login||pr.author?.login)}`;
    const title = (pr.draft?'[Draft] ':'') + pr.title;
    return `<div class="gh-row" data-id="${pr.number}" data-repo="${_ghEsc(repo)}"
      style="padding:9px 10px;border-bottom:1px solid var(--border);cursor:pointer;
      display:flex;gap:8px;align-items:flex-start;transition:background .12s;"
      onmouseover="if(!this.classList.contains('gh-row-sel'))this.style.background='var(--surface2)'"
      onmouseout="if(!this.classList.contains('gh-row-sel'))this.style.background=''"
      onclick="_ghSelectPR(${pr.number},'${_ghEsc(repo)}',this)">
      ${dot}
      <div style="flex:1;min-width:0;">
        <div style="font-size:12px;font-weight:500;color:var(--text);white-space:nowrap;
          overflow:hidden;text-overflow:ellipsis;">${_ghEsc(title)}</div>
        <div style="display:flex;align-items:center;gap:5px;margin-top:3px;flex-wrap:wrap;">${meta}</div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0;">${right}</div>
    </div>`;
  }).join('');
}

function _ghRenderIssueList(body, items) {
  if (!items.length) {
    body.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:200px;gap:8px;color:var(--text-sub);font-size:12px;">
      <span style="font-size:24px;opacity:.5;">🎉</span>No open issues assigned to you</div>`;
    return;
  }
  body.innerHTML = items.map(issue => {
    const state = (issue.state || 'open').toUpperCase();
    const dot = _ghStateDot(state, false);
    const repoUrl = issue.repository_url || '';
    const repo = repoUrl.replace(/.*\/repos\//, '').replace(/.*\/api\/v3\/repos\//, '') ||
                 issue.repositoryNameWithOwner || '';
    const labels = (issue.labels || []).map(l => _ghLabel(l.name, l.color)).join('');
    const [owner, repoName] = repo.split('/');
    const meta = `<span style="font-size:11px;color:var(--text-sub);font-family:monospace;">#${issue.number}</span>
      <span style="font-size:10px;color:var(--text-sub);">${_ghEsc(repo)}</span>${labels}`;
    const right = `<span style="font-size:10px;color:var(--text-sub);">${_ghAge(issue.created_at||issue.createdAt)}</span>`;
    return `<div class="gh-row" data-id="${issue.number}"
      style="padding:9px 10px;border-bottom:1px solid var(--border);cursor:pointer;
      display:flex;gap:8px;align-items:flex-start;transition:background .12s;"
      onmouseover="if(!this.classList.contains('gh-row-sel'))this.style.background='var(--surface2)'"
      onmouseout="if(!this.classList.contains('gh-row-sel'))this.style.background=''"
      onclick="_ghSelectIssue(${issue.number},'${_ghEsc(owner)}','${_ghEsc(repoName)}',this)">
      ${dot}
      <div style="flex:1;min-width:0;">
        <div style="font-size:12px;font-weight:500;color:var(--text);white-space:nowrap;
          overflow:hidden;text-overflow:ellipsis;">${_ghEsc(issue.title)}</div>
        <div style="display:flex;align-items:center;gap:5px;margin-top:3px;flex-wrap:wrap;">${meta}</div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0;">${right}</div>
    </div>`;
  }).join('');
}

function _ghRenderRepoList(body, items) {
  if (!items.length) {
    body.innerHTML = `<div style="padding:16px;color:var(--text-sub);font-size:12px;">No repositories found</div>`;
    return;
  }
  body.innerHTML = items.map(repo => {
    const fullName = _ghEsc(repo.full_name || repo.nameWithOwner || '');
    return `
    <div class="gh-row" data-repo='${JSON.stringify({full_name: repo.full_name||repo.nameWithOwner, description: repo.description||'', language: repo.language||'', stargazers_count: repo.stargazers_count||0, open_issues_count: repo.open_issues_count||0, visibility: repo.visibility||repo.private?'private':'public', html_url: repo.html_url||'', updated_at: repo.updated_at||repo.pushedAt||''}).replace(/'/g,"&#39;")}'
      style="padding:9px 10px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .12s;"
      onmouseover="if(!this.classList.contains('gh-row-sel'))this.style.background='var(--surface2)'"
      onmouseout="if(!this.classList.contains('gh-row-sel'))this.style.background=''"
      onclick="_ghSelectRepo(this)">
      <div style="font-size:12px;font-weight:600;color:var(--text);font-family:monospace;margin-bottom:2px;">
        ${fullName}</div>
      <div style="font-size:11px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
        ${_ghEsc(repo.description||'')}</div>
      <div style="display:flex;gap:10px;margin-top:4px;">
        ${repo.language?`<span style="font-size:10px;color:var(--text-sub);">● ${_ghEsc(repo.language)}</span>`:''}
        ${repo.stargazers_count!=null?`<span style="font-size:10px;color:var(--text-sub);">★ ${repo.stargazers_count}</span>`:''}
        ${repo.open_issues_count!=null?`<span style="font-size:10px;color:var(--text-sub);">● ${repo.open_issues_count} issues</span>`:''}
        ${repo.visibility==='private'||repo.private?`<span style="font-size:10px;color:var(--text-sub);">🔒 Private</span>`:`<span style="font-size:10px;color:var(--text-sub);">Public</span>`}
      </div>
    </div>`;
  }).join('');
}

function _ghSelectRepo(rowEl) {
  document.querySelectorAll('.gh-row').forEach(r => { r.classList.remove('gh-row-sel'); r.style.background=''; });
  rowEl.classList.add('gh-row-sel'); rowEl.style.background='var(--surface3)';
  let repo;
  try { repo = JSON.parse(rowEl.dataset.repo); } catch { return; }
  const detail = document.getElementById('tp-detail-col');
  const [owner, repoName] = (repo.full_name||'').split('/');
  const updated = repo.updated_at ? _ghAge(repo.updated_at) : '';
  detail.innerHTML = `
    <div style="padding:16px;display:flex;flex-direction:column;gap:14px;">
      <div>
        <div style="font-size:14px;font-weight:600;color:var(--text);font-family:monospace;margin-bottom:4px;">
          ${_ghEsc(repo.full_name||'')}</div>
        ${repo.description?`<div style="font-size:12px;color:var(--text-sub);">${_ghEsc(repo.description)}</div>`:''}
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:8px;">
        ${repo.language?`<span style="font-size:11px;padding:2px 8px;border-radius:12px;background:var(--surface2);color:var(--text-sub);">● ${_ghEsc(repo.language)}</span>`:''}
        <span style="font-size:11px;padding:2px 8px;border-radius:12px;background:var(--surface2);color:var(--text-sub);">${repo.visibility==='private'||repo.private?'🔒 Private':'Public'}</span>
        ${updated?`<span style="font-size:11px;padding:2px 8px;border-radius:12px;background:var(--surface2);color:var(--text-sub);">Updated ${updated}</span>`:''}
      </div>
      <div style="display:flex;gap:16px;">
        <div style="text-align:center;">
          <div style="font-size:18px;font-weight:600;color:var(--text);">★ ${repo.stargazers_count||0}</div>
          <div style="font-size:10px;color:var(--text-sub);">Stars</div>
        </div>
        <div style="text-align:center;">
          <div style="font-size:18px;font-weight:600;color:var(--text);">${repo.open_issues_count||0}</div>
          <div style="font-size:10px;color:var(--text-sub);">Open Issues</div>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;">
        <button onclick="window.open('${_ghEsc(repo.html_url)}','_blank')"
          style="padding:7px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:12px;cursor:pointer;text-align:left;">
          ↗ Open in GitHub
        </button>
        <button onclick="_ghLoadRepoIssues('${_ghEsc(owner)}','${_ghEsc(repoName)}')"
          style="padding:7px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:12px;cursor:pointer;text-align:left;">
          ● View open issues
        </button>
        <button onclick="_ghLoadRepoPRs('${_ghEsc(owner)}','${_ghEsc(repoName)}')"
          style="padding:7px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:12px;cursor:pointer;text-align:left;">
          ⎇ View open PRs
        </button>
      </div>
    </div>`;
  // Standardized toolbar in the persistent header (Ask Gator + Open in GitHub).
  tpBuildDetailToolbar({
    app: 'github',
    title: { text: repo.full_name || 'Repository', title: repo.description || '' },
    actions: [
      { kind: 'icon', iconHtml: '✦', title: 'Ask Gator about this repo', group: 0,
        onClick: () => tpInjectAIPrompt(`@git Tell me about the repository ${repo.full_name || ''}`) },
      { kind: 'icon', iconHtml: _TP_EXT_LINK_SVG, title: 'Open in GitHub', group: 1,
        onClick: () => { if (repo.html_url) window.open(repo.html_url, '_blank', 'noopener'); } },
    ],
  });
}

function _ghLoadRepoIssues(owner, repo) {
  const detail = document.getElementById('tp-detail-col');
  detail.innerHTML = `<div style="padding:16px;display:flex;flex-direction:column;gap:8px;">
    <div style="font-size:12px;color:var(--text-sub);margin-bottom:4px;">${_ghEsc(owner)}/${_ghEsc(repo)} — Issues</div>
    <button onclick="window.open('https://github.com/${_ghEsc(owner)}/${_ghEsc(repo)}/issues','_blank')"
      style="padding:7px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:12px;cursor:pointer;">
      ↗ Open issues on GitHub
    </button>
    <button onclick="_ghAskAboutRepo('${_ghEsc(owner)}','${_ghEsc(repo)}','issues')"
      style="padding:7px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:12px;cursor:pointer;">
      Ask AI Gator about issues in this repo
    </button>
  </div>`;
}

async function _ghLoadRepoPRs(owner, repo) {
  const detail = document.getElementById('tp-detail-col');
  detail.innerHTML = `<div style="padding:16px;display:flex;flex-direction:column;gap:8px;">
    <div style="font-size:12px;color:var(--text-sub);margin-bottom:4px;">${_ghEsc(owner)}/${_ghEsc(repo)} — Pull Requests</div>
    <button onclick="window.open('https://github.com/${_ghEsc(owner)}/${_ghEsc(repo)}/pulls','_blank')"
      style="padding:7px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:12px;cursor:pointer;">
      ↗ Open PRs on GitHub
    </button>
    <button onclick="_ghAskAboutRepo('${_ghEsc(owner)}','${_ghEsc(repo)}','pull requests')"
      style="padding:7px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:12px;cursor:pointer;">
      Ask AI Gator about PRs in this repo
    </button>
  </div>`;
}

function _ghAskAboutRepo(owner, repo, topic) {
  // Pre-fill the chat input with a contextual question and switch focus
  const input = document.getElementById('user-input') || document.querySelector('textarea');
  if (input) {
    input.value = `@git Tell me about open ${topic} in ${owner}/${repo}`;
    input.focus();
    input.dispatchEvent(new Event('input', {bubbles:true}));
  }
}

async function _ghSelectPR(number, repo, rowEl) {
  document.querySelectorAll('.gh-row').forEach(r => { r.classList.remove('gh-row-sel'); r.style.background=''; });
  if (rowEl) { rowEl.classList.add('gh-row-sel'); rowEl.style.background='var(--surface3)'; }
  const detail = document.getElementById('tp-detail-col');
  detail.innerHTML = `<div style="padding:16px;color:var(--text-sub);font-size:12px;">Loading PR #${number}…</div>`;
  try {
    const [owner, repoName] = repo.split('/');
    const pr = await _ghDirectTool('github_get_pr', { owner, repo: repoName, pr_number: number });
    detail.innerHTML = _ghPRDetail(pr, owner, repoName);
    _ghBindMergeDialog(pr, owner, repoName);
    // Standardized toolbar in the persistent header (Ask Gator + Open in GitHub).
    tpBuildDetailToolbar({
      app: 'github',
      title: { text: `${owner}/${repoName} #${number}`, title: pr.title || '' },
      actions: [
        { kind: 'icon', iconHtml: '✦', title: 'Ask Gator about this PR', group: 0,
          onClick: () => tpInjectAIPrompt(`@git Summarize PR #${number} in ${owner}/${repoName}: ${pr.title || ''}`) },
        { kind: 'icon', iconHtml: _TP_EXT_LINK_SVG, title: 'Open in GitHub', group: 1,
          onClick: () => { if (pr.html_url) window.open(pr.html_url, '_blank', 'noopener'); } },
      ],
    });
  } catch (e) {
    detail.innerHTML = `<div style="padding:16px;color:var(--danger);font-size:12px;">Error: ${e.message}</div>`;
  }
}

async function _ghSelectIssue(number, owner, repo, rowEl) {
  document.querySelectorAll('.gh-row').forEach(r => { r.classList.remove('gh-row-sel'); r.style.background=''; });
  if (rowEl) { rowEl.classList.add('gh-row-sel'); rowEl.style.background='var(--surface3)'; }
  const detail = document.getElementById('tp-detail-col');
  detail.innerHTML = `<div style="padding:16px;color:var(--text-sub);font-size:12px;">Loading issue #${number}…</div>`;
  try {
    const issue = await _ghDirectTool('github_get_issue', { owner, repo, issue_number: number });
    detail.innerHTML = _ghIssueDetail(issue, owner, repo);
    // Standardized toolbar in the persistent header (Ask Gator + Open in GitHub).
    tpBuildDetailToolbar({
      app: 'github',
      title: { text: `${owner}/${repo} #${number}`, title: issue.title || '' },
      actions: [
        { kind: 'icon', iconHtml: '✦', title: 'Ask Gator about this issue', group: 0,
          onClick: () => tpInjectAIPrompt(`@git Summarize issue #${number} in ${owner}/${repo}: ${issue.title || ''}`) },
        { kind: 'icon', iconHtml: _TP_EXT_LINK_SVG, title: 'Open in GitHub', group: 1,
          onClick: () => { if (issue.html_url) window.open(issue.html_url, '_blank', 'noopener'); } },
      ],
    });
  } catch (e) {
    detail.innerHTML = `<div style="padding:16px;color:var(--danger);font-size:12px;">Error: ${e.message}</div>`;
  }
}

function _ghStatePill(state, draft) {
  if (draft) return `<span style="display:inline-flex;align-items:center;gap:5px;font-size:11px;
    font-weight:600;padding:3px 8px;border-radius:20px;background:rgba(110,118,129,.12);
    color:#6e7681;border:1px solid rgba(110,118,129,.3);margin-bottom:8px;">◌ Draft</span>`;
  const map = {
    OPEN:   {bg:'rgba(63,185,80,.12)',   color:'#3fb950',border:'rgba(63,185,80,.3)',   icon:'●',label:'Open'},
    MERGED: {bg:'rgba(163,113,247,.12)',color:'#a371f7',border:'rgba(163,113,247,.3)',icon:'⬡',label:'Merged'},
    CLOSED: {bg:'rgba(248,81,73,.12)',   color:'#f85149',border:'rgba(248,81,73,.3)',   icon:'✕',label:'Closed'},
  };
  const s = map[(state||'OPEN').toUpperCase()] || map.OPEN;
  return `<span style="display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;
    padding:3px 8px;border-radius:20px;background:${s.bg};color:${s.color};
    border:1px solid ${s.border};margin-bottom:8px;">${s.icon} ${s.label}</span>`;
}

function _ghPRDetail(pr, owner, repo) {
  const state = pr.draft ? 'DRAFT' : (pr.state || 'open').toUpperCase();
  const ghUrl = pr.html_url || '';
  const checksHtml = (pr.checks || []).map(c => {
    const icon = c.conclusion==='success'?`<span style="color:#3fb950">✓</span>`
               : c.conclusion==='failure'?`<span style="color:#f85149">✗</span>`
               : `<span style="color:#d29922">⟳</span>`;
    return `<div style="display:inline-flex;align-items:center;gap:4px;font-size:11px;
      background:var(--surface2);border:1px solid var(--border);border-radius:6px;
      padding:3px 8px;">${icon} ${_ghEsc(c.name)}</div>`;
  }).join('') || `<span style="font-size:11px;color:var(--text-sub);">No checks</span>`;
  const reviewsHtml = (pr.reviews||[]).map(rv => {
    const icon = rv.state==='APPROVED'?`<span style="color:#3fb950">✓ approved</span>`
               : rv.state==='CHANGES_REQUESTED'?`<span style="color:#f85149">✗ changes</span>`
               : `<span style="color:#6e7681">⏳ pending</span>`;
    return `<div style="display:flex;align-items:center;gap:5px;font-size:11px;color:var(--text-dim);">
      ${_ghAvatar(rv.user?.login)} ${_ghEsc(rv.user?.login)} ${icon}</div>`;
  }).join('') || `<span style="font-size:11px;color:var(--text-sub);">No reviewers</span>`;
  const labelsHtml = (pr.labels||[]).map(l=>_ghLabel(l.name,l.color)).join(' ');
  const changesHtml = pr.additions!=null ? `
    <div style="display:flex;gap:6px;font-size:11px;font-family:monospace;margin-bottom:10px;">
      <span style="color:#3fb950">+${pr.additions}</span><span style="color:var(--text-sub)">/</span>
      <span style="color:#f85149">−${pr.deletions}</span>
      <span style="color:var(--text-sub)">· ${pr.changed_files} files</span></div>` : '';
  const commentsHtml = (pr.comments||[]).map(c=>`
    <div style="display:flex;gap:8px;margin-bottom:10px;">
      ${_ghAvatar(c.user?.login)}
      <div><div style="font-size:10px;color:var(--text-sub);margin-bottom:3px;">
        <strong style="color:var(--text-dim)">${_ghEsc(c.user?.login)}</strong> · ${_ghAge(c.created_at)}</div>
        <div style="font-size:12px;color:var(--text-dim);line-height:1.5;">${_ghEsc((c.body||'').slice(0,200))}</div>
      </div></div>`).join('');
  return `
  <div style="flex:1;overflow-y:auto;padding:14px 16px;">
    ${_ghStatePill(state,pr.draft)}
    <div style="font-size:15px;font-weight:600;color:var(--text);line-height:1.4;margin-bottom:4px;">
      ${_ghEsc(pr.title)}</div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:12px;">
      ${_ghEsc(owner)}/${_ghEsc(repo)} ·
      <strong>${_ghEsc(pr.user?.login||pr.author?.login)}</strong> →
      <code style="background:var(--surface3);padding:1px 5px;border-radius:4px;font-size:11px;">
        ${_ghEsc(pr.base?.ref||'main')}</code> · ${_ghAge(pr.created_at)}</div>
    ${labelsHtml?`<div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px;">${labelsHtml}</div>`:''}
    <hr style="border:none;border-top:1px solid var(--border);margin:10px 0;"/>
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--text-sub);margin-bottom:6px;">CI Checks</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;">${checksHtml}</div>
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--text-sub);margin-bottom:6px;">Reviewers</div>
    <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:12px;">${reviewsHtml}</div>
    ${changesHtml}
    <hr style="border:none;border-top:1px solid var(--border);margin:10px 0;"/>
    <div style="font-size:12px;color:var(--text-dim);line-height:1.6;background:var(--surface2);
      border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:12px;">
      ${_ghEsc((pr.body||'No description.').slice(0,600))}</div>
    ${commentsHtml?`<div style="font-size:11px;font-weight:600;color:var(--text-dim);margin-bottom:8px;">
      💬 ${pr.comments?.length||0} comments</div>${commentsHtml}`:''}
  </div>
  <div style="padding:10px 16px;border-top:1px solid var(--border);display:flex;gap:6px;
    flex-wrap:wrap;flex-shrink:0;background:var(--surface);">
    <button onclick="_showAlert('Phase 2', 'info')"
      style="font-size:12px;font-weight:500;padding:5px 12px;border-radius:6px;
      background:#3fb950;color:#000;border:none;cursor:pointer;">✓ Approve</button>
    <button onclick="_showAlert('Phase 2', 'info')"
      style="font-size:12px;padding:5px 12px;border-radius:6px;
      background:transparent;color:var(--text-dim);border:1px solid var(--border2);cursor:pointer;">Request Changes</button>
    <button onclick="_showAlert('Phase 2', 'info')"
      style="font-size:12px;padding:5px 12px;border-radius:6px;
      background:transparent;color:var(--text-dim);border:1px solid var(--border2);cursor:pointer;">Add Comment</button>
    <button id="gh-merge-btn"
      style="font-size:12px;font-weight:500;padding:5px 12px;border-radius:6px;
      background:#a371f7;color:#fff;border:none;cursor:pointer;">Merge PR ▾</button>
    ${ghUrl?`<a href="${ghUrl}" target="_blank"
      style="font-size:12px;padding:5px 12px;border-radius:6px;background:transparent;
      color:var(--text-sub);border:1px solid var(--border);text-decoration:none;margin-left:auto;">
      Open in GitHub ↗</a>`:''}
  </div>
  <div id="gh-merge-overlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);
    z-index:500;align-items:center;justify-content:center;">
    <div style="background:var(--surface2);border:1px solid var(--border2);border-radius:12px;
      padding:20px 24px;width:360px;box-shadow:0 24px 48px rgba(0,0,0,.6);">
      <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:6px;">
        Merge pull request #${pr.number}?</div>
      <div style="font-size:12px;color:var(--text-dim);margin-bottom:16px;line-height:1.5;">
        <code style="background:var(--surface3);padding:1px 5px;border-radius:4px;font-size:11px;">
          ${_ghEsc(owner)}/${_ghEsc(repo)}</code> &nbsp;
        <code style="background:var(--surface3);padding:1px 5px;border-radius:4px;font-size:11px;">
          ${_ghEsc(pr.head?.ref||'branch')}</code> →
        <code style="background:var(--surface3);padding:1px 5px;border-radius:4px;font-size:11px;">
          ${_ghEsc(pr.base?.ref||'main')}</code>
      </div>
      <div style="margin-bottom:16px;">
        <label style="font-size:11px;color:var(--text-sub);display:block;margin-bottom:4px;
          text-transform:uppercase;letter-spacing:.05em;">Merge strategy</label>
        <select id="gh-merge-strategy" style="width:100%;background:var(--surface3);
          border:1px solid var(--border2);border-radius:6px;padding:6px 10px;
          color:var(--text);font-size:12px;outline:none;">
          <option>Squash and merge</option><option>Merge commit</option><option>Rebase and merge</option>
        </select>
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button id="gh-merge-cancel" style="font-size:12px;padding:5px 14px;border-radius:6px;
          background:transparent;color:var(--text-dim);border:1px solid var(--border2);cursor:pointer;">
          Cancel</button>
        <button id="gh-merge-confirm" style="font-size:12px;font-weight:600;padding:5px 14px;
          border-radius:6px;background:#a371f7;color:#fff;border:none;cursor:pointer;">
          Confirm Merge</button>
      </div>
    </div>
  </div>`;
}

function _ghIssueDetail(issue, owner, repo) {
  const state = (issue.state||'open').toUpperCase();
  const labelsHtml = (issue.labels||[]).map(l=>_ghLabel(l.name,l.color)).join(' ');
  const assignee = (issue.assignees||[])[0]?.login || issue.assignee?.login || '';
  const milestone = issue.milestone?.title || '';
  const ghUrl = issue.html_url || '';
  const commentsHtml = (issue.comments||[]).map(c=>`
    <div style="display:flex;gap:8px;margin-bottom:10px;">
      ${_ghAvatar(c.user?.login)}
      <div><div style="font-size:10px;color:var(--text-sub);margin-bottom:3px;">
        <strong style="color:var(--text-dim)">${_ghEsc(c.user?.login)}</strong> · ${_ghAge(c.created_at)}</div>
        <div style="font-size:12px;color:var(--text-dim);line-height:1.5;">${_ghEsc((c.body||'').slice(0,200))}</div>
      </div></div>`).join('');
  return `
  <div style="flex:1;overflow-y:auto;padding:14px 16px;">
    ${_ghStatePill(state,false)}
    <div style="font-size:15px;font-weight:600;color:var(--text);line-height:1.4;margin-bottom:4px;">
      ${_ghEsc(issue.title)}</div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:12px;">
      ${_ghEsc(owner)}/${_ghEsc(repo)} · opened by
      <strong>${_ghEsc(issue.user?.login)}</strong> · ${_ghAge(issue.created_at)}
      · 💬 ${issue.comments?.length||0}</div>
    ${labelsHtml?`<div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px;">${labelsHtml}</div>`:''}
    ${assignee?`<div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;
      display:flex;align-items:center;gap:5px;">${_ghAvatar(assignee)} ${_ghEsc(assignee)}</div>`:''}
    ${milestone?`<div style="font-size:11px;color:var(--text-dim);margin-bottom:10px;">
      📍 ${_ghEsc(milestone)}</div>`:''}
    <hr style="border:none;border-top:1px solid var(--border);margin:10px 0;"/>
    <div style="font-size:12px;color:var(--text-dim);line-height:1.6;background:var(--surface2);
      border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:12px;">
      ${_ghEsc((issue.body||'No description.').slice(0,600))}</div>
    ${commentsHtml?`<div style="font-size:11px;font-weight:600;color:var(--text-dim);margin-bottom:8px;">
      💬 ${issue.comments?.length||0} comments</div>${commentsHtml}`:''}
  </div>
  <div style="padding:10px 16px;border-top:1px solid var(--border);display:flex;gap:6px;
    flex-shrink:0;background:var(--surface);">
    <button onclick="_showAlert('Phase 2', 'info')"
      style="font-size:12px;padding:5px 12px;border-radius:6px;background:transparent;
      color:var(--text-dim);border:1px solid var(--border2);cursor:pointer;">Add Comment</button>
    <button onclick="_showAlert('Phase 2', 'info')"
      style="font-size:12px;padding:5px 12px;border-radius:6px;background:transparent;
      color:#f85149;border:1px solid rgba(248,81,73,.4);cursor:pointer;">Close Issue</button>
    ${ghUrl?`<a href="${ghUrl}" target="_blank"
      style="font-size:12px;padding:5px 12px;border-radius:6px;background:transparent;
      color:var(--text-sub);border:1px solid var(--border);text-decoration:none;margin-left:auto;">
      Open in GitHub ↗</a>`:''}
  </div>`;
}

function _ghBindMergeDialog(pr, owner, repo) {
  const overlay  = document.getElementById('gh-merge-overlay');
  const mergeBtn = document.getElementById('gh-merge-btn');
  const cancelBtn  = document.getElementById('gh-merge-cancel');
  const confirmBtn = document.getElementById('gh-merge-confirm');
  if (!overlay || !mergeBtn) return;
  mergeBtn.addEventListener('click', () => { overlay.style.display = 'flex'; });
  cancelBtn.addEventListener('click', () => { overlay.style.display = 'none'; });
  confirmBtn.addEventListener('click', () => {
    confirmBtn.textContent = 'Merging…';
    confirmBtn.disabled = true;
    setTimeout(() => {
      overlay.style.display = 'none';
      _showAlert('PR #' + pr.number + ' merge queued — Phase 2 will wire this to MCP', 'success');
      confirmBtn.textContent = 'Confirm Merge';
      confirmBtn.disabled = false;
    }, 800);
  });
}


/* ── Slack Third Pane ─────────────────────────────────────── */

const _slackState = {
  selectedChannel: null,
  channelCache: null,
  threadCache: new Map(),
  threadDetailCache: new Map(),
  activeView: 'threads',
  selectedThreadId: null,
  filter: 'all',
  userCache: new Map(),        // username → { display_name, real_name }
  userPending: new Set(),      // usernames currently being resolved
  _slackCursor: null,          // cursor for loading older message history pages
  _slackLoadingOlder: false,   // guard against concurrent history fetches
};
const SLACK_CACHE_TTL = 120000;

/* ── Async user display name resolution (throttled: 2 concurrent) ── */
const _SLACK_MAX_CONCURRENT_LOOKUPS = 2;
let _slackActiveLookups = 0;
const _slackLookupQueue = [];
let _slackCurrentMentionAbortCtrl = null;

async function _slackResolveUsers(usernames) {
  const toResolve = usernames.filter(u => u && !_slackState.userCache.has(u) && !_slackState.userPending.has(u));
  if (!toResolve.length) return;
  toResolve.forEach(u => { _slackState.userPending.add(u); _slackLookupQueue.push(u); });
  _slackDrainLookupQueue();
}

async function _slackDrainLookupQueue() {
  while (_slackLookupQueue.length && _slackActiveLookups < _SLACK_MAX_CONCURRENT_LOOKUPS) {
    const username = _slackLookupQueue.shift();
    if (_slackState.userCache.has(username)) { _slackState.userPending.delete(username); continue; }
    _slackActiveLookups++;
    _slackFetchUser(username).finally(() => { _slackActiveLookups--; _slackDrainLookupQueue(); });
  }
}

async function _slackFetchUser(username) {
  try {
    const res = await fetch(`/api/slack/users/${encodeURIComponent(username)}`);
    if (!res.ok) return;
    const data = await res.json();
    const u = data.user || data;
    if (u && (u.real_name || u.display_name)) {
      _slackState.userCache.set(username, u.real_name || u.display_name);
      // Update visible DOM elements with this username
      document.querySelectorAll(`[data-slack-user="${CSS.escape(username)}"]`).forEach(el => {
        const resolved = _slackState.userCache.get(username);
        el.textContent = resolved;
        const avatar = el.closest('.slack-thread-item, .slack-msg')?.querySelector('.tp-avatar-slack');
        if (avatar) avatar.textContent = _slackInitials(resolved);
      });
    }
  } catch {} finally { _slackState.userPending.delete(username); }
}

function _slackDisplayName(username) {
  if (!username) return 'Thread';
  return _slackState.userCache.get(username) || username;
}

function _slackRelTime(d) {
  if (!d) return '—';
  const ms = Date.now() - new Date(d).getTime();
  if (ms < 60000) return 'just now';
  if (ms < 3600000) return Math.floor(ms/60000) + 'm ago';
  if (ms < 86400000) return Math.floor(ms/3600000) + 'h ago';
  if (ms < 604800000) return Math.floor(ms/86400000) + 'd ago';
  return new Date(d).toLocaleDateString(undefined, {month:'short', day:'numeric'});
}

function _slackInitials(name) {
  if (!name) return '?';
  return name.split(/[\s._-]+/).map(w => w[0]).join('').toUpperCase().slice(0,2);
}

function _slackEsc(s) { return typeof escapeHtml === 'function' ? escapeHtml(s) : s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

/* ── Slack mrkdwn → HTML ──────────────────────────────────── */
function _slackMrkdwn(text) {
  if (!text) return '';
  let s = _slackEsc(text);
  // User mentions: <@UXXXX|Name> → @Name (styled)
  s = s.replace(/&lt;@(\w+)\|([^&]+)&gt;/g, '<span class="slack-mention">@$2</span>');
  // User mentions without display name: <@UXXXX> → resolve from cache or show @UID
  s = s.replace(/&lt;@(\w+)&gt;/g, (_, uid) => {
    const name = (typeof _USER_CACHE !== 'undefined' && _USER_CACHE[uid]) || uid;
    return `<span class="slack-mention">@${escapeHtml(name)}</span>`;
  });
  // Channel mentions: <#CXXXX|channel-name> → #channel-name
  s = s.replace(/&lt;#(\w+)\|([^&]+)&gt;/g, '<span class="slack-mention">#$2</span>');
  // Slack emoji: :emoji_name: → rendered emoji
  s = s.replace(/:([a-z0-9_+-]+):/g, (_, name) => _slackEmoji(name));
  // code blocks (``` ... ```)
  s = s.replace(/```([\s\S]*?)```/g, '<pre class="slack-code-block">$1</pre>');
  // inline code
  s = s.replace(/`([^`\n]+)`/g, '<code class="slack-inline-code">$1</code>');
  // bold
  s = s.replace(/\*([^\s*](?:[^*]*[^\s*])?)\*/g, '<strong>$1</strong>');
  // italic
  s = s.replace(/\b_([^\s_](?:[^_]*[^\s_])?)_\b/g, '<em>$1</em>');
  // strikethrough
  s = s.replace(/~([^\s~](?:[^~]*[^\s~])?)~/g, '<del>$1</del>');
  // Slack links: <url|label> or <url>
  s = s.replace(/&lt;(https?:\/\/[^|&]+)\|([^&]+)&gt;/g, '<a href="$1" target="_blank" rel="noopener" class="slack-link">$2</a>');
  // Bare URLs
  s = s.replace(/&lt;(https?:\/\/[^&]+)&gt;/g, '<a href="$1" target="_blank" rel="noopener" class="slack-link">$1</a>');
  // Blockquotes: > text
  s = s.replace(/^&gt;\s?(.*)$/gm, '<blockquote class="slack-quote">$1</blockquote>');
  return s;
}

/* ── Slack emoji lookup ───────────────────────────────────── */
const _SLACK_EMOJI = {
  '+1': '\u{1F44D}', thumbsup: '\u{1F44D}', '-1': '\u{1F44E}', thumbsdown: '\u{1F44E}',
  heart: '\u2764\uFE0F', white_check_mark: '\u2705', heavy_check_mark: '\u2714\uFE0F',
  eyes: '\u{1F440}', raised_hands: '\u{1F64C}', clap: '\u{1F44F}', fire: '\u{1F525}',
  tada: '\u{1F389}', rocket: '\u{1F680}', thinking_face: '\u{1F914}', pray: '\u{1F64F}',
  100: '\u{1F4AF}', wave: '\u{1F44B}', ok_hand: '\u{1F44C}', point_up: '\u261D\uFE0F',
  muscle: '\u{1F4AA}', star: '\u2B50', sparkles: '\u2728', boom: '\u{1F4A5}',
  warning: '\u26A0\uFE0F', x: '\u274C', question: '\u2753', exclamation: '\u2757',
  bulb: '\u{1F4A1}', memo: '\u{1F4DD}', link: '\u{1F517}', lock: '\u{1F512}',
  key: '\u{1F511}', bug: '\u{1F41B}', wrench: '\u{1F527}', hammer: '\u{1F528}',
  check: '\u2705', smile: '\u{1F604}', laughing: '\u{1F606}', joy: '\u{1F602}',
  sob: '\u{1F62D}', sweat_smile: '\u{1F605}', sunglasses: '\u{1F60E}', rolling_eyes: '\u{1F644}',
  slightly_smiling_face: '\u{1F642}', wink: '\u{1F609}', stuck_out_tongue: '\u{1F61B}',
  party_popper: '\u{1F389}', dart: '\u{1F3AF}', trophy: '\u{1F3C6}', medal: '\u{1F3C5}',
  green_heart: '\u{1F49A}', blue_heart: '\u{1F499}', purple_heart: '\u{1F49C}',
  // Additional common reactions
  thank_you: '\u{1F64F}', thanks: '\u{1F64F}', ty: '\u{1F64F}',
  heavy_plus_sign: '\u2795', heavy_minus_sign: '\u2796',
  '1': '\u0031\uFE0F\u20E3', '2': '\u0032\uFE0F\u20E3', '3': '\u0033\uFE0F\u20E3',
  '4': '\u0034\uFE0F\u20E3', '5': '\u0035\uFE0F\u20E3',
  point_right: '\u{1F449}', point_left: '\u{1F448}', point_down: '\u{1F447}',
  red_circle: '\u{1F534}', large_blue_circle: '\u{1F535}', white_circle: '\u26AA',
  black_circle: '\u26AB', orange_circle: '\u{1F7E0}', green_circle: '\u{1F7E2}',
  thinking: '\u{1F914}', face_with_monocle: '\u{1F9D0}',
  partying_face: '\u{1F973}', star_struck: '\u{1F929}', heart_eyes: '\u{1F60D}',
  scream: '\u{1F631}', angry: '\u{1F620}', rage: '\u{1F621}',
  cry: '\u{1F622}', disappointed: '\u{1F61E}', confused: '\u{1F615}',
  neutral_face: '\u{1F610}', expressionless: '\u{1F611}', unamused: '\u{1F612}',
  relieved: '\u{1F60C}', pensive: '\u{1F614}', sleeping: '\u{1F634}',
  zipper_mouth_face: '\u{1F910}', money_mouth_face: '\u{1F911}',
  hugging_face: '\u{1F917}', nerd_face: '\u{1F913}', cowboy_hat_face: '\u{1F920}',
  skull: '\u{1F480}', ghost: '\u{1F47B}', robot_face: '\u{1F916}',
  see_no_evil: '\u{1F648}', hear_no_evil: '\u{1F649}', speak_no_evil: '\u{1F64A}',
  handshake: '\u{1F91D}', crossed_fingers: '\u{1F91E}', v: '\u270C\uFE0F',
  love_you_gesture: '\u{1F91F}', metal: '\u{1F918}',
  brain: '\u{1F9E0}', gear: '\u2699\uFE0F', chart_with_upwards_trend: '\u{1F4C8}',
  calendar: '\u{1F4C5}', clipboard: '\u{1F4CB}', pushpin: '\u{1F4CC}',
  bell: '\u{1F514}', megaphone: '\u{1F4E3}', loudspeaker: '\u{1F4E2}',
  email: '\u{1F4E7}', inbox_tray: '\u{1F4E5}', package: '\u{1F4E6}',
  computer: '\u{1F4BB}', keyboard: '\u2328\uFE0F', desktop_computer: '\u{1F5A5}\uFE0F',
  white_large_square: '\u2B1C', black_large_square: '\u2B1B',
  arrow_right: '\u27A1\uFE0F', arrow_left: '\u2B05\uFE0F', arrow_up: '\u2B06\uFE0F', arrow_down: '\u2B07\uFE0F',
  rotating_light: '\u{1F6A8}', construction: '\u{1F6A7}',
  hourglass: '\u231B', stopwatch: '\u23F1\uFE0F', timer_clock: '\u23F2\uFE0F',
  coffee: '\u2615', beer: '\u{1F37A}', beers: '\u{1F37B}', pizza: '\u{1F355}',
  earth_americas: '\u{1F30E}', sunny: '\u2600\uFE0F', rainbow: '\u{1F308}',
  zap: '\u26A1', snowflake: '\u2744\uFE0F', umbrella: '\u2602\uFE0F',
};

// Quick-pick reactions for the reaction picker
const _SLACK_QUICK_REACTIONS = [
  { name: '+1', emoji: '\u{1F44D}' },
  { name: 'heart', emoji: '\u2764\uFE0F' },
  { name: 'eyes', emoji: '\u{1F440}' },
  { name: 'raised_hands', emoji: '\u{1F64C}' },
  { name: 'fire', emoji: '\u{1F525}' },
  { name: 'tada', emoji: '\u{1F389}' },
  { name: 'check', emoji: '\u2705' },
  { name: 'thinking_face', emoji: '\u{1F914}' },
];

function _slackEmoji(name) {
  if (!name) return '';
  const clean = name.replace(/^:|:$/g, '').toLowerCase();
  return _SLACK_EMOJI[clean] || `:${clean}:`;
}

// Reverse-lookup: emoji char → Slack shortcode name (e.g. '👍' → 'thumbsup')
// Builds a reverse map from EMOJI_SHORTCODES on first call (lazy singleton).
let _slackEmojiToName = null;
function _slackEmojiName(emoji) {
  if (!_slackEmojiToName) {
    _slackEmojiToName = new Map();
    if (typeof EMOJI_SHORTCODES !== 'undefined') {
      for (const [code, char] of Object.entries(EMOJI_SHORTCODES)) {
        if (!_slackEmojiToName.has(char)) _slackEmojiToName.set(char, code);
      }
    }
  }
  return (_slackEmojiToName.get(emoji) || emoji).replace(/^:|:$/g, '');
}

// ── Slack Reaction Helpers ────────────────────────────────────────────────

/**
 * Toggle a reaction on a Slack message.
 * Detects whether the authed user has already reacted via data-reacted on the pill.
 * Routes to /api/slack/react (add) or /api/slack/unreact (remove).
 * @param {string} channelId   Slack channel ID
 * @param {string} ts          Message timestamp
 * @param {string} emoji       The emoji character (e.g. '👍')
 * @param {Element} [msgEl]    The .slack-msg element
 */
async function _slackReact(channelId, ts, emoji, msgEl) {
  const name = _slackEmojiName(emoji);
  _addRecentEmoji(emoji);

  // Detect existing reaction: look for pill with data-reacted="1"
  let alreadyReacted = false;
  if (msgEl) {
    const pill = msgEl.querySelector(`.slack-reaction-btn[data-name="${CSS.escape(name)}"][data-reacted="1"]`);
    alreadyReacted = !!pill;
  }

  const endpoint = alreadyReacted ? '/api/slack/unreact' : '/api/slack/react';
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_id: channelId, timestamp: ts, name }),
    });
    const body = await res.json().catch(() => ({}));
    if (!body.ok) { console.warn('[Slack react] error:', body.error); return; }
    if (msgEl) _slackToggleReactionPill(msgEl, name, emoji, alreadyReacted);
  } catch (e) {
    console.warn('[Slack react] fetch failed:', e);
  }
}

/**
 * Optimistically update a reaction pill after add/remove.
 */
function _slackToggleReactionPill(msgEl, name, emoji, wasReacted) {
  const pill = msgEl.querySelector(`.slack-reaction-btn[data-name="${CSS.escape(name)}"]`);
  if (pill) {
    const countEl = pill.querySelector('.slack-reaction-count');
    const cur = parseInt(countEl?.textContent || '0', 10);
    const next = wasReacted ? cur - 1 : cur + 1;
    if (next <= 0) {
      pill.remove();
    } else {
      if (countEl) countEl.textContent = String(next);
      pill.dataset.reacted = wasReacted ? '0' : '1';
    }
  } else if (!wasReacted) {
    // Add new pill
    const reactionsDiv = msgEl.querySelector('.slack-reactions');
    const container = reactionsDiv || (() => {
      const d = document.createElement('div');
      d.className = 'slack-reactions';
      const bodyEl = msgEl.querySelector('.slack-msg-body');
      if (bodyEl) bodyEl.after(d);
      return d;
    })();
    const btn = document.createElement('button');
    btn.className = 'slack-reaction-btn';
    btn.dataset.name = name;
    btn.dataset.reacted = '1';
    btn.title = `:${name}:`;
    btn.innerHTML = `${emoji} <span class="slack-reaction-count">1</span>`;
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const cid = _slackState.selectedChannel;
      const msgTs = msgEl.dataset.ts;
      if (cid && msgTs) _slackReact(cid, msgTs, emoji, msgEl);
    });
    container.appendChild(btn);
  }
}

/**
 * Build a DOM div containing clickable reaction pill buttons.
 * @param {Array} reactions  Array of {name, count} objects from Slack API
 * @param {string} channelId
 * @param {string} ts        Message timestamp
 * @param {Element} msgEl    Parent .slack-msg element
 * @returns {HTMLElement|null}
 */
/**
 * Build a forward-preview block for a received forwarded message.
 * Styled like Teams' tp-forward-preview: left accent border with sender + quoted text.
 * @param {{sender:string, text:string, footer:string, pretext:string}} fwd
 * @returns {HTMLElement}
 */
function _slackBuildForwardPreview(fwd) {
  const block = document.createElement('div');
  block.className = 'slack-received-forward';
  if (fwd.sender) {
    const label = document.createElement('div');
    label.className = 'slack-received-forward-label';
    label.textContent = 'Forwarded from ' + fwd.sender;
    block.appendChild(label);
  }
  const body = document.createElement('div');
  body.className = 'slack-received-forward-body';
  body.innerHTML = _slackMrkdwn(fwd.text || '');
  block.appendChild(body);
  if (fwd.footer) {
    const footer = document.createElement('div');
    footer.className = 'slack-received-forward-footer';
    footer.textContent = fwd.footer;
    block.appendChild(footer);
  }
  return block;
}

function _slackBuildReactionsRow(reactions, channelId, ts, msgEl) {
  if (!reactions || !reactions.length) return null;
  const div = document.createElement('div');
  div.className = 'slack-reactions';
  reactions.forEach(r => {
    const name = typeof r === 'string' ? r : (r.name || r.emoji || '');
    const count = typeof r === 'object' ? (r.count || 1) : 1;
    const emoji = _slackEmoji(name);
    const btn = document.createElement('button');
    btn.className = 'slack-reaction-btn';
    btn.dataset.name = name;
    btn.dataset.reacted = (r.self_reacted === true) ? '1' : '0';
    btn.title = `:${name}:`;
    btn.innerHTML = `${emoji}${count > 0 ? ` <span class="slack-reaction-count">${count}</span>` : ''}`;
    btn.addEventListener('click', e => {
      e.stopPropagation();
      _slackReact(channelId, ts, emoji, msgEl);
    });
    div.appendChild(btn);
  });
  return div;
}


// ── Message History (scroll-up loads older pages) ────────────────────────

function _slackOnScroll(channelId, scroll) {
  if (_slackState._slackLoadingOlder || !_slackState._slackCursor) return;
  if (scroll.scrollTop < 150) _slackLoadOlderMessages(channelId, scroll);
}

async function _slackLoadOlderMessages(channelId, scroll) {
  if (_slackState._slackLoadingOlder || !_slackState._slackCursor) return;
  _slackState._slackLoadingOlder = true;

  const indicator = document.createElement('div');
  indicator.className = 'slack-history-loading';
  indicator.textContent = 'Loading older messages…';
  scroll.prepend(indicator);

  const prevHeight = scroll.scrollHeight;
  try {
    const url = `/api/slack/channels/${encodeURIComponent(channelId)}/messages?limit=50&cursor=${encodeURIComponent(_slackState._slackCursor)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();

    const newMessages = data.messages || [];
    const cached = _slackState.messageCache ? _slackState.messageCache.get(channelId) : null;
    const existingTs = new Set((cached?.messages || []).map(m => m.ts));
    const fresh = newMessages.filter(m => !existingTs.has(m.ts));

    if (fresh.length) {
      fresh.slice().reverse().forEach(msg => {
        const el = _slackBuildChannelMessage(msg, channelId);
        scroll.insertBefore(el, indicator.nextSibling);
      });
      if (cached) {
        cached.messages = [...fresh, ...cached.messages];
        cached.cursor = data.cursor || null;
        _slackState.messageCache.set(channelId, cached);
      }
    }

    _slackState._slackCursor = data.cursor || null;

  } catch (e) {
    console.warn('[Slack history] load older failed:', e);
  }

  indicator.remove();
  scroll.scrollTop += scroll.scrollHeight - prevHeight;
  _slackState._slackLoadingOlder = false;
}


/* ── Phase 1: Left Pane — Channels + DMs ─────────────────── */

function _initSlackPane() {
  _slackState.activeView = 'messages';
  _slackState.messageCache = _slackState.messageCache || new Map();
  _slackState.dmCache = null;
  const listCol = document.getElementById('tp-list-col');
  const detailCol = document.getElementById('tp-detail-col');
  listCol.innerHTML = '<div class="tp-empty-state">Loading channels...</div>';
  detailCol.innerHTML = _slackEmptyState();
  // Wire "+" button for DM compose
  const addBtn = document.getElementById('tp-add-btn');
  if (addBtn) addBtn.onclick = () => _slackShowDMCompose();
  // Wire toolbar search — calls /api/slack/search and renders results
  async function _runSlackSearch(q) {
    const sp = document.getElementById('tp-search-spinner');
    const sw = document.getElementById('tp-search-wrap');
    if (sp) sp.classList.remove('hidden'); if (sw) sw.classList.add('is-searching');
    const detail = document.getElementById('tp-detail-col');
    detail.innerHTML = '<div class="tp-empty-state">Searching…</div>';
    try {
      const res = await fetch(`/api/slack/search?q=${encodeURIComponent(q)}&limit=30`);
      if (!res.ok || tpState.type !== 'slack') return;
      const data = await res.json();
      const messages = (data.messages || data.matches || []);
      if (!messages.length) { detail.innerHTML = '<div class="tp-empty-state">No results</div>'; return; }
      detail.innerHTML = '';
      const wrap = document.createElement('div');
      wrap.style.cssText = 'padding:.5rem .75rem;display:flex;flex-direction:column;gap:.5rem';
      const hdr = document.createElement('div');
      hdr.style.cssText = 'font-size:.72rem;color:var(--text-sub);padding-bottom:.25rem;border-bottom:1px solid var(--border)';
      hdr.textContent = `${messages.length} result${messages.length !== 1 ? 's' : ''} for “${q}”`;
      wrap.appendChild(hdr);
      messages.forEach(m => {
        const row = document.createElement('div');
        row.style.cssText = 'background:var(--surface);border-radius:6px;padding:.5rem .7rem;font-size:.78rem';
        const meta = document.createElement('div');
        meta.style.cssText = 'font-size:.7rem;color:var(--text-sub);margin-bottom:.2rem';
        meta.textContent = [m.channel_name || m.channel, m.username || m.user, (m.ts ? new Date(parseFloat(m.ts)*1000).toLocaleString() : '')].filter(Boolean).join(' � ');
        const body = document.createElement('div');
        body.style.cssText = 'color:var(--text);line-height:1.4;white-space:pre-wrap;word-break:break-word';
        body.textContent = m.text || '';
        row.appendChild(meta); row.appendChild(body);
        wrap.appendChild(row);
      });
      detail.appendChild(wrap);
    } catch (e) {
      detail.innerHTML = `<div class="tp-empty-state">Search failed: ${escapeHtml(e.message)}</div>`;
    } finally {
      if (sp) sp.classList.add('hidden'); if (sw) sw.classList.remove('is-searching');
    }
  }
  const _tpSearchInput = document.getElementById('tp-search-input');
  if (_tpSearchInput) {
    _tpSearchInput.placeholder = 'Search Slack threads…';
    let _slackSearchDebounce;
    _tpSearchInput.oninput = () => {
      clearTimeout(_slackSearchDebounce);
      const q = _tpSearchInput.value.trim();
      if (!q) return;
      const sp = document.getElementById('tp-search-spinner');
      const sw = document.getElementById('tp-search-wrap');
      if (sp) sp.classList.remove('hidden'); if (sw) sw.classList.add('is-searching');
      _slackSearchDebounce = setTimeout(() => _runSlackSearch(q), 400);
    };
    _tpSearchInput.onkeydown = (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const q = _tpSearchInput.value.trim();
      if (!q) return;
      clearTimeout(_slackSearchDebounce);
      _runSlackSearch(q);
    };
  }
  _slackLoadAll();
}

async function _slackLoadAll() {
  const listCol = document.getElementById('tp-list-col');
  listCol.innerHTML = '<div class="tp-empty-state">Loading...</div>';
  // Fetch channels and DMs in parallel
  const [chRes, dmRes] = await Promise.all([
    fetch('/api/slack/channels').catch(() => null),
    fetch('/api/slack/dms').catch(() => null),
  ]);
  const chData = chRes?.ok ? await chRes.json() : {};
  const dmData = dmRes?.ok ? await dmRes.json() : {};
  // Guard against a stale render: if the user switched panes while these
  // fetches were in flight, tpState.type is no longer 'slack' — bail so we
  // don't clobber the new pane's list column (cross-pane content bleed).
  if (tpState.type !== 'slack') return;
  const channels = chData.channels || [];
  const dms = dmData.dms || [];
  const fetchFailed = !chRes?.ok || !dmRes?.ok;
  // Surface connectivity errors — token may exist but MCP unreachable
  if ((fetchFailed || chData.error) && !channels.length && !dms.length) {
    listCol.textContent = '';
    const errDiv = document.createElement('div');
    errDiv.className = 'tp-empty-state';
    errDiv.style.cssText = 'padding:1rem;text-align:center;color:var(--text-sub)';
    const icon = document.createElement('div');
    icon.style.cssText = 'font-size:1.3rem;margin-bottom:.4rem';
    icon.textContent = '⚠️';
    const title = document.createElement('div');
    title.style.cssText = 'font-weight:600;margin-bottom:.3rem';
    title.textContent = 'Slack unavailable';
    const msg = document.createElement('div');
    msg.style.cssText = 'font-size:.8rem';
    msg.textContent = 'Could not reach Slack. Check your connection or re-connect in Settings.';
    errDiv.appendChild(icon);
    errDiv.appendChild(title);
    errDiv.appendChild(msg);
    listCol.appendChild(errDiv);
    return;
  }
  _slackState.channelCache = { channels, ts: Date.now() };
  _slackState.dmCache = dms;
  _slackRenderLeftPane(channels, dms);
}

function _slackEmptyState() {
  return gatorEmptyState([
    { icon: '#', text: 'Select a channel or DM to view messages' },
    { icon: '\uD83D\uDD0D', text: 'Search messages across Slack' },
    { icon: '\u270D\uFE0F', text: 'Click + to compose a DM' },
  ]);
}

function _slackGetFavChannels() {
  try { return JSON.parse(localStorage.getItem('gator-slack-fav-channels') || '[]'); } catch { return []; }
}
function _slackSetFavChannels(favs) {
  localStorage.setItem('gator-slack-fav-channels', JSON.stringify(favs));
}

function _slackRenderLeftPane(channels, dms) {
  const col = document.getElementById('tp-list-col');
  col.innerHTML = '';

  // Search filter
  const searchWrap = document.createElement('div');
  searchWrap.style.cssText = 'padding:.3rem .5rem';
  const searchInput = document.createElement('input');
  searchInput.type = 'text';
  searchInput.className = 'slack-search-filter';
  searchInput.placeholder = 'Filter...';
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.toLowerCase();
    scroll.querySelectorAll('.tp-list-item').forEach(el => {
      el.style.display = (el.dataset.name || '').includes(q) ? '' : 'none';
    });
  });
  searchWrap.appendChild(searchInput);
  col.appendChild(searchWrap);

  const scroll = document.createElement('div');
  scroll.className = 'tp-list-scroll';

  // --- DMs section ---
  if (dms.length) {
    const dmLabel = document.createElement('div');
    dmLabel.className = 'tp-section-label tp-section-collapsible';
    dmLabel.textContent = '\u25BE Direct Messages (' + dms.length + ')';
    const dmBody = document.createElement('div');
    dmBody.className = 'tp-section-body';
    dmLabel.addEventListener('click', () => {
      const hidden = dmBody.style.display === 'none';
      dmBody.style.display = hidden ? '' : 'none';
      dmLabel.textContent = (hidden ? '\u25BE' : '\u25B8') + ' Direct Messages (' + dms.length + ')';
    });
    scroll.appendChild(dmLabel);
    dms.forEach(dm => {
      const el = document.createElement('div');
      el.className = 'tp-list-item' + (dm.channel_id === _slackState.selectedChannel ? ' active' : '');
      el.dataset.name = (dm.display_name || '').toLowerCase();
      el.dataset.id = dm.channel_id;
      const initials = _slackInitials(dm.display_name);
      const preview = document.createElement('div');
      preview.className = 'tp-item-preview';
      preview.textContent = (dm.last_message || '').slice(0, 50);
      const nameEl = document.createElement('div');
      nameEl.className = 'tp-item-name';
      nameEl.textContent = dm.display_name;
      const body = document.createElement('div');
      body.className = 'tp-item-body';
      body.appendChild(nameEl);
      body.appendChild(preview);
      const avatar = document.createElement('div');
      avatar.className = 'tp-avatar tp-avatar-slack';
      avatar.style.fontSize = '.6rem';
      avatar.textContent = initials;
      const meta = document.createElement('div');
      meta.className = 'tp-item-meta';
      const timeEl = document.createElement('div');
      timeEl.className = 'tp-item-time';
      timeEl.textContent = _slackRelTime(dm.timestamp);
      meta.appendChild(timeEl);
      el.appendChild(avatar);
      el.appendChild(body);
      el.appendChild(meta);
      el.addEventListener('click', () => _slackSelectChannel(dm.channel_id, dm.display_name));
      dmBody.appendChild(el);
    });
    scroll.appendChild(dmBody);
  }

  // --- Channels section ---
  const chLabel = document.createElement('div');
  chLabel.className = 'tp-section-label tp-section-collapsible';
  chLabel.textContent = '\u25BE Channels (' + channels.length + ')';
  const chBody = document.createElement('div');
  chBody.className = 'tp-section-body';
  chLabel.addEventListener('click', () => {
    const hidden = chBody.style.display === 'none';
    chBody.style.display = hidden ? '' : 'none';
    chLabel.textContent = (hidden ? '\u25BE' : '\u25B8') + ' Channels (' + channels.length + ')';
  });
  scroll.appendChild(chLabel);

  const favs = new Set(_slackGetFavChannels());
  const sorted = [...channels].sort((a, b) => {
    const af = favs.has(a.channel_name) ? 0 : 1;
    const bf = favs.has(b.channel_name) ? 0 : 1;
    if (af !== bf) return af - bf;
    return (a.channel_name || '').localeCompare(b.channel_name || '');
  });
  sorted.forEach(ch => chBody.appendChild(_slackBuildChannelItem(ch)));
  scroll.appendChild(chBody);

  col.appendChild(scroll);

  // ── Keyboard navigation (shared helper) ──────────────────
  _wireListKeyboard(scroll, el => {
    scroll.querySelectorAll('.tp-list-item').forEach(r => r.classList.remove('focused'));
    el.classList.add('focused');
    const id = el.dataset.id;
    const name = el.dataset.name || id;
    if (id) _slackSelectChannel(id, name);
    requestAnimationFrame(() => scroll.focus({ preventScroll: true }));
  });
  scroll.querySelectorAll('.tp-list-item').forEach((el, i) => {
    el.dataset.idx = i;
    el.addEventListener('click', () => {
      scroll.querySelectorAll('.tp-list-item').forEach(r => r.classList.remove('focused'));
      el.classList.add('focused');
      if (scroll._openTimer) clearTimeout(scroll._openTimer);
      requestAnimationFrame(() => scroll.focus({ preventScroll: true }));
    });
  });
  requestAnimationFrame(() => _safeScrollFocus(scroll));
}

function _slackBuildChannelItem(ch) {
  const el = document.createElement('div');
  const selected = ch.channel_name === _slackState.selectedChannel || ch.channel_id === _slackState.selectedChannel;
  const chKey = ch.channel_id || ch.channel_name;
  el.className = 'slack-channel-item tp-list-item' + (selected ? ' active' : '');
  el.dataset.name = (ch.channel_name || '').toLowerCase();
  el.dataset.id = chKey;

  // Unread indicator \u2014 compare most-recent cached message ts vs last-seen ts from localStorage
  const cached = _slackState.messageCache && _slackState.messageCache.get(chKey);
  const newestTs = cached && cached.messages && cached.messages.length
    ? (cached.messages[cached.messages.length - 1].ts || '0') : '0';
  const lastSeenTs = (() => { try { return localStorage.getItem(`gator-slack-last-ts-${chKey}`) || '0'; } catch { return '0'; } })();
  if (!selected && newestTs > lastSeenTs) el.classList.add('slack-unread');

  const icon = ch.type === 'private_channel' ? '\uD83D\uDD12' : '#';
  const avatar = document.createElement('div');
  avatar.className = 'tp-avatar tp-avatar-slack';
  avatar.textContent = icon;
  const nameEl = document.createElement('div');
  nameEl.className = 'tp-item-name slack-channel-name';
  nameEl.textContent = ch.channel_name;
  const body = document.createElement('div');
  body.className = 'tp-item-body';
  body.appendChild(nameEl);
  if (ch.purpose || ch.topic) {
    const prev = document.createElement('div');
    prev.className = 'tp-item-preview';
    prev.textContent = (ch.purpose || ch.topic || '').slice(0, 50);
    body.appendChild(prev);
  }
  el.appendChild(avatar);
  el.appendChild(body);
  el.addEventListener('click', () => _slackSelectChannel(ch.channel_id || ch.channel_name, ch.channel_name));
  return el;
}


/* ── Phase 2: Channel Messages (native Slack style) ───────── */

async function _slackSelectChannel(channelId, displayName) {
  _slackState.selectedChannel = channelId;
  _slackState._displayName = displayName || channelId;
  _slackState.activeView = 'messages';
  _slackState.selectedThreadId = null;
  document.querySelectorAll('.tp-list-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === channelId);
  });

  const col = document.getElementById('tp-detail-col');
  col.textContent = '';
  const loading = document.createElement('div');
  loading.className = 'tp-empty-state';
  loading.textContent = 'Loading...';
  col.appendChild(loading);

  try {
    const res = await fetch('/api/slack/channels/' + encodeURIComponent(channelId) + '/messages?limit=50');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    _slackState.messageCache = _slackState.messageCache || new Map();
    _slackState.messageCache.set(channelId, { messages: data.messages || [], cursor: data.cursor, ts: Date.now() });
    _slackRenderMessages(channelId, data.messages || [], displayName);
    // Mark channel as read — store most recent message ts in localStorage
    const _msgs = data.messages || [];
    if (_msgs.length) {
      const _lastTs = _msgs[_msgs.length - 1].ts;
      if (_lastTs) try { localStorage.setItem(`gator-slack-last-ts-${channelId}`, _lastTs); } catch {}
    }
  } catch (e) {
    col.textContent = '';
    const err = document.createElement('div');
    err.className = 'tp-empty-state';
    err.textContent = 'Failed to load messages. Try again.';
    col.appendChild(err);
  }
}

function _slackRenderMessages(channelId, messages, displayName) {
  const col = document.getElementById('tp-detail-col');
  col.textContent = '';
  const name = displayName || channelId;
  const isChannel = !name.includes(',') && name.length < 30;

  // Standardized toolbar in the persistent header (#tp-detail-header) —
  // replaces the old in-content tp-thread-header (second toolbar). Message
  // list + compose stay in the content column.
  {
    const _slPin = _createPinBtn('slack', channelId, name, { type: 'channel' });
    tpBuildDetailToolbar({
      app: 'slack',
      title: { text: (isChannel ? '# ' : '') + name, title: name },
      actions: [
        { kind: 'icon', iconHtml: '✦', title: 'Ask AI about this channel', group: 0,
          onClick: () => tpInjectAIPrompt('Summarize recent activity in Slack ' + (isChannel ? 'channel #' : '') + name + '. Give me a concise summary of key discussions and decisions.') },
        { el: _slPin, kind: 'icon', title: 'Pin channel', group: 0 },
      ],
    });
  }

  // Message scroll
  const scroll = document.createElement('div');
  scroll.className = 'tp-thread-scroll';
  Object.assign(scroll.style, { flex: '1', overflowY: 'auto', padding: '.5rem' });

  if (!messages.length) {
    const empty = document.createElement('div');
    empty.className = 'tp-empty-state';
    empty.style.padding = '2rem';
    empty.textContent = 'No messages yet.';
    scroll.appendChild(empty);
  } else {
    let prevDateKey = '';
    let prevUserId = null;
    let prevTsMs = 0;
    const GROUP_GAP_MS = 5 * 60 * 1000;  // 5-minute grouping window (native Slack convention)

    messages.forEach(msg => {
      const ts = msg.timestamp || msg.ts;
      const tsMs = parseFloat(msg.ts || 0) * 1000;

      if (ts) {
        const d = new Date(ts);
        const key = d.toDateString();
        if (key !== prevDateKey) {
          prevDateKey = key;
          // Date separator resets grouping
          prevUserId = null;
          prevTsMs = 0;
          const today = new Date().toDateString();
          const yesterday = new Date(Date.now() - 86400000).toDateString();
          const label = key === today ? 'Today' : key === yesterday ? 'Yesterday' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
          const dateSep = document.createElement('div');
          dateSep.className = 'slack-date-sep';
          const span = document.createElement('span');
          span.textContent = label;
          dateSep.appendChild(span);
          scroll.appendChild(dateSep);
        }
      }

      const sameUser = msg.user_id && msg.user_id === prevUserId;
      const withinGap = tsMs > 0 && prevTsMs > 0 && (tsMs - prevTsMs) < GROUP_GAP_MS;
      const isGrouped = sameUser && withinGap;

      scroll.appendChild(_slackBuildChannelMessage(msg, channelId, { grouped: isGrouped }));
      prevUserId = msg.user_id || null;
      prevTsMs = tsMs;
    });
  }
  col.appendChild(scroll);

  // Compose bar
  const compose = document.createElement('div');
  compose.className = 'slack-compose-bar';
  const editor = _buildQuillEditor({ placeholder: 'Message ' + (isChannel ? '#' : '') + _slackEsc(name) + '\u2026', showSendBtn: true });
  compose.appendChild(editor.wrapEl);
  col.appendChild(compose);

  function _wireQuill() {
    const q = editor.quill;
    if (!q) { setTimeout(_wireQuill, 200); return; }
    const sendBtn = editor.wrapEl.querySelector('.tp-compose-send');
    q.on('text-change', () => { if (sendBtn) sendBtn.disabled = editor.isEmpty(); });
    q.root.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (sendBtn) sendBtn.click(); }
    });
    _wireMentionDropdownSlack(q, q.root);
    if (sendBtn) sendBtn.addEventListener('click', () => _slackPostMessage(channelId, editor, sendBtn, 'user'));
    // Wire paperclip attach button → hidden file input (#98)
    const attachBtn = editor.wrapEl.querySelector('.tp-qt-attach-btn');
    if (attachBtn && !attachBtn._slackWired) {
      const fi = document.createElement('input');
      fi.type = 'file'; fi.multiple = true; fi.style.display = 'none';
      editor.wrapEl.appendChild(fi);
      attachBtn.addEventListener('click', () => fi.click());
      attachBtn._slackWired = true;
    }
  }
  setTimeout(_wireQuill, 150);
  setTimeout(() => { scroll.scrollTop = scroll.scrollHeight; }, 100);

  // Store cursor and wire scroll-up for message history
  const _cachedEntry = _slackState.messageCache ? _slackState.messageCache.get(channelId) : null;
  _slackState._slackCursor = _cachedEntry?.cursor || null;
  _slackState._slackLoadingOlder = false;
  scroll.addEventListener('scroll', () => _slackOnScroll(channelId, scroll));

}

function _slackBuildChannelMessage(msg, channelId, opts) {
  const isGrouped = opts && opts.grouped === true;
  const el = document.createElement('div');
  el.className = isGrouped ? 'slack-msg slack-msg-grouped' : 'slack-msg';
  if (msg.ts) el.dataset.ts = msg.ts;
  // msg.user is the already-resolved display name from the backend; use directly.
  // msg.user_id is the Slack UID — use as cache key for any async re-resolution.
  const displayName = msg.user || 'unknown';
  const userId = msg.user_id || '';
  const hasThread = (msg.reply_count || 0) > 0;

  // Grouped messages suppress the avatar (CSS hides it; still rendered for accessibility)
  const avatar = document.createElement('div');
  avatar.className = 'tp-avatar tp-avatar-slack';
  avatar.style.fontSize = '.55rem';
  avatar.textContent = _slackInitials(displayName);

  const content = document.createElement('div');
  content.className = 'slack-msg-content';

  const hdr = document.createElement('div');
  hdr.className = 'slack-msg-header';
  const sender = document.createElement('span');
  sender.className = 'slack-msg-sender';
  if (userId) sender.dataset.slackUser = userId;
  sender.textContent = displayName;
  hdr.appendChild(sender);
  content.appendChild(hdr);

  // If this is a forwarded message, show pretext (if any) then the forward preview block
  if (msg.forward) {
    if (msg.text) {
      const preBody = document.createElement('div');
      preBody.className = 'slack-msg-body';
      preBody.innerHTML = _slackMrkdwn(msg.text);
      content.appendChild(preBody);
    }
    content.appendChild(_slackBuildForwardPreview(msg.forward));
  } else {
    const body = document.createElement('div');
    body.className = 'slack-msg-body';
    body.innerHTML = _slackMrkdwn(msg.text || '');
    content.appendChild(body);
  }

  if ((msg.reactions || []).length) {
    const reactionsEl = _slackBuildReactionsRow(msg.reactions, channelId, msg.ts, el);
    if (reactionsEl) content.appendChild(reactionsEl);
  }

  if (hasThread) {
    const replyCount = msg.reply_count || 0;
    const lastTime = msg.latest_reply ? _slackRelTime(msg.latest_reply) : '';
    const chip = document.createElement('div');
    chip.className = 'tp-thread-chip';
    chip.setAttribute('role', 'button');
    chip.setAttribute('tabindex', '0');
    chip.innerHTML = '<span class="tp-thread-chip-icon">\uD83D\uDCAC</span>' +
      '<span class="tp-thread-chip-count">' + replyCount + (replyCount === 1 ? ' reply' : ' replies') + '</span>' +
      (lastTime ? '<span class="tp-thread-chip-time"> \u00B7 last ' + escapeHtml(lastTime) + '</span>' : '') +
      '<span class="tp-thread-chip-cta"> View thread \u2192</span>';
    chip.addEventListener('click', (e) => { e.stopPropagation(); _slackOpenThread(channelId, msg.ts); });
    chip.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _slackOpenThread(channelId, msg.ts); } });
    content.appendChild(chip);
  }

  // Hover action bar — Quick-react, Add-reaction, Reply-in-thread, Copy text, Pin
  const actions = document.createElement('div');
  actions.className = 'slack-msg-actions';

  // Add-reaction button — Material Symbols sentiment_satisfied_add
  const addReactBtn = document.createElement('button');
  addReactBtn.className = 'tp-msg-action-btn slack-react-add';
  addReactBtn.title = 'Add reaction';
  addReactBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="currentColor"><path d="M480-480Zm0 400q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q43 0 83 8.5t77 24.5v90q-35-20-75.5-31.5T480-800q-133 0-226.5 93.5T160-480q0 133 93.5 226.5T480-160q133 0 226.5-93.5T800-480q0-32-6.5-62T776-600h86q9 29 13.5 58.5T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm320-600v-80h-80v-80h80v-80h80v80h80v80h-80v80h-80ZM620-520q25 0 42.5-17.5T680-580q0-25-17.5-42.5T620-640q-25 0-42.5 17.5T560-580q0 25 17.5 42.5T620-520Zm-280 0q25 0 42.5-17.5T400-580q0-25-17.5-42.5T340-640q-25 0-42.5 17.5T280-580q0 25 17.5 42.5T340-520Zm263.5 221.5Q659-337 684-400H276q25 63 80.5 101.5T480-260q68 0 123.5-38.5Z"/></svg>`;
  addReactBtn.addEventListener('click', e => {
    e.stopPropagation();
    _openFullEmojiPicker(addReactBtn, emoji => _slackReact(channelId, msg.ts, emoji, el));
  });
  actions.appendChild(addReactBtn);

  // Reply-in-thread button — opens thread view (and reply compose) for any message
  const replyThreadBtn = document.createElement('button');
  replyThreadBtn.className = 'slack-reply-thread-btn';
  replyThreadBtn.title = 'Reply in thread';
  replyThreadBtn.textContent = '💬';  // speech bubble — "reply in thread"
  replyThreadBtn.addEventListener('click', e => { e.stopPropagation(); _slackOpenThread(channelId, msg.ts); });
  actions.appendChild(replyThreadBtn);

  // Copy message text button
  const copyBtn = document.createElement('button');
  copyBtn.className = 'slack-copy-btn';
  copyBtn.title = 'Copy message text';
  copyBtn.textContent = '📋';  // 📋
  copyBtn.addEventListener('click', e => {
    e.stopPropagation();
    navigator.clipboard.writeText(msg.text || '').then(() => {
      copyBtn.textContent = '✓';  // ✓
      setTimeout(() => { copyBtn.textContent = '📋'; }, 1500);
    }).catch(() => {});
  });
  actions.appendChild(copyBtn);

  // Forward button — opens DM compose pre-filled with message text
  const forwardBtn = document.createElement('button');
  forwardBtn.className = 'tp-msg-action-btn slack-forward-btn';
  forwardBtn.title = 'Forward message';
  forwardBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="currentColor"><path d="M760-200v-160q0-50-35-85t-85-35H273l144 144-57 56-240-240 240-240 57 56-144 144h367q83 0 141.5 58.5T840-360v160h-80Z"/></svg>`;
  forwardBtn.addEventListener('click', e => {
    e.stopPropagation();
    _slackShowDMCompose({
      forwardSender: displayName || 'Someone',
      forwardText: (msg.text || '').slice(0, 500),
      forwardTs: msg.timestamp || msg.ts || '',
    });
  });
  actions.appendChild(forwardBtn);

  const channelName = (_slackState.channels || []).find(c => c.id === channelId)?.name || channelId;
  const pinLabel = (msg.text || '').slice(0, 60).replace(/\n/g, ' ') || 'message';
  const pinMeta = { type: 'thread', channel: channelName, message_ts: msg.ts };
  const threadPinId = channelId + ':' + msg.ts;
  const pinBtn = _createPinBtn('slack', threadPinId, pinLabel, pinMeta);
  // No inline opacity — let .pin-ctx-btn CSS handle opacity so .pinned glow shows correctly
  pinBtn.style.cssText = 'font-size:.75rem;padding:2px 5px;';
  pinBtn.title = hasThread ? 'Pin thread to Chat' : 'Pin message to Chat';
  actions.appendChild(pinBtn);

  const meta = document.createElement('div');
  meta.className = 'slack-msg-meta';
  meta.textContent = _slackRelTime(msg.timestamp || msg.ts);
  // actions is inside content so it doesn't overlap the trailing meta timestamp
  content.appendChild(actions);
  el.appendChild(avatar);
  el.appendChild(content);
  el.appendChild(meta);
  return el;
}


/* ── Phase 3: Thread Detail View ─────────────────────────── */

async function _slackOpenThread(channelId, messageTs) {
  _slackState.activeView = 'thread-detail';
  _slackState.selectedThreadId = messageTs;
  const col = document.getElementById('tp-detail-col');
  col.textContent = '';
  const loading = document.createElement('div');
  loading.className = 'tp-empty-state';
  loading.textContent = 'Loading thread...';
  col.appendChild(loading);

  try {
    const res = await fetch('/api/slack/threads/' + encodeURIComponent(channelId) + '/' + encodeURIComponent(messageTs));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    _slackState.threadDetailCache.set(messageTs, { data: data, ts: Date.now() });
    _slackRenderThreadDetail(col, data, channelId);
  } catch (e) {
    col.textContent = '';
    const err = document.createElement('div');
    err.className = 'tp-empty-state';
    err.textContent = 'Failed to load thread.';
    col.appendChild(err);
  }
}

async function _slackSelectThread(threadId) {
  const chId = _slackState.selectedChannel || '';
  return _slackOpenThread(chId, threadId);
}

function _slackRenderThreadDetail(container, data, channelId) {
  container.textContent = '';
  const thread = data.thread || data;
  const messages = thread.messages || [];
  const name = _slackState._displayName || _slackState.selectedChannel || '';
  const isChannel = !name.includes(',') && name.length < 30;

  // Back nav now lives in the main toolbar (spec.back below) — no in-content sub-bar.
  const _threadBack = () => {
    _slackState.activeView = 'messages';
    _slackState.selectedThreadId = null;
    const cached = _slackState.messageCache ? _slackState.messageCache.get(channelId || _slackState.selectedChannel) : null;
    if (cached) _slackRenderMessages(channelId || _slackState.selectedChannel, cached.messages, name);
    else _slackSelectChannel(channelId || _slackState.selectedChannel, name);
  };

  // Scroll area
  const scroll = document.createElement('div');
  scroll.className = 'tp-thread-scroll';
  Object.assign(scroll.style, { flex: '1', overflowY: 'auto', padding: '.5rem' });

  // Parent message
  const parentMsg = messages[0];
  if (parentMsg) {
    const p = document.createElement('div');
    p.className = 'slack-msg slack-parent-msg';
    const dn = parentMsg.user || 'unknown';  // already resolved by backend
    const av = document.createElement('div');
    av.className = 'tp-avatar tp-avatar-slack';
    av.style.fontSize = '.55rem';
    av.textContent = _slackInitials(dn);
    const ct = document.createElement('div');
    ct.className = 'slack-msg-content';
    const hdr = document.createElement('div');
    hdr.className = 'slack-msg-header';
    const sn = document.createElement('span');
    sn.className = 'slack-msg-sender';
    sn.textContent = dn;
    hdr.appendChild(sn);
    ct.appendChild(hdr);
    const bd = document.createElement('div');
    bd.className = 'slack-msg-body';
    bd.innerHTML = _slackMrkdwn(parentMsg.text || '');
    ct.appendChild(bd);
    if ((parentMsg.reactions || []).length) {
      const parentReactionsEl = _slackBuildReactionsRow(
        parentMsg.reactions, channelId || _slackState.selectedChannel, parentMsg.ts || '', p);
      if (parentReactionsEl) ct.appendChild(parentReactionsEl);
    }
    const ptm = document.createElement('div');
    ptm.className = 'slack-msg-meta';
    ptm.textContent = _slackRelTime(parentMsg.timestamp);
    p.appendChild(av);
    p.appendChild(ct);
    p.appendChild(ptm);
    scroll.appendChild(p);
  }

  // Replies
  const replies = messages.slice(1);
  const parentTs = messages[0]?.timestamp || messages[0]?.ts;
  const parentDateKey = parentTs ? new Date(parentTs).toDateString() : '';
  if (replies.length) {
    const sep = document.createElement('div');
    sep.className = 'slack-replies-sep';
    sep.textContent = replies.length + (replies.length === 1 ? ' reply' : ' replies');
    scroll.appendChild(sep);
  }

  // prevDateKey starts as the parent's date so the first reply only gets a
  // date separator if it actually falls on a different day than the parent.
  let prevDateKey = parentDateKey;
  replies.forEach(msg => {
    const ts = msg.timestamp || msg.ts;
    if (ts) {
      const d = new Date(ts);
      const key = d.toDateString();
      if (key !== prevDateKey) {
        prevDateKey = key;
        const today = new Date().toDateString();
        const yesterday = new Date(Date.now() - 86400000).toDateString();
        const label = key === today ? 'Today' : key === yesterday ? 'Yesterday' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
        const dateSep = document.createElement('div');
        dateSep.className = 'slack-date-sep';
        const span = document.createElement('span');
        span.textContent = label;
        dateSep.appendChild(span);
        scroll.appendChild(dateSep);
      }
    }
    const replyEl = _slackBuildMessage(msg);
    replyEl.classList.add('slack-reply-msg');
    scroll.appendChild(replyEl);
  });
  container.appendChild(scroll);

  // Reply compose
  const replyCompose = document.createElement('div');
  replyCompose.className = 'slack-compose-bar';
  const replyEditor = _buildQuillEditor({ placeholder: 'Reply to thread\u2026', showSendBtn: true });
  replyCompose.appendChild(replyEditor.wrapEl);
  container.appendChild(replyCompose);

  function _wireReply() {
    const q = replyEditor.quill;
    if (!q) { setTimeout(_wireReply, 200); return; }
    _wireMentionDropdownSlack(q, q.root);
    const sendBtn = replyEditor.wrapEl.querySelector('.tp-compose-send');
    q.on('text-change', () => { if (sendBtn) sendBtn.disabled = replyEditor.isEmpty(); });
    q.root.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (sendBtn) sendBtn.click(); }
    });
    if (sendBtn) sendBtn.addEventListener('click', () => _slackPostMessage(channelId || _slackState.selectedChannel, replyEditor, sendBtn, 'user', _slackState.selectedThreadId));
    // Wire paperclip attach button (#98)
    const attachBtn = replyEditor.wrapEl.querySelector('.tp-qt-attach-btn');
    if (attachBtn && !attachBtn._slackWired) {
      const fi = document.createElement('input');
      fi.type = 'file'; fi.multiple = true; fi.style.display = 'none';
      replyEditor.wrapEl.appendChild(fi);
      attachBtn.addEventListener('click', () => fi.click());
      attachBtn._slackWired = true;
    }
  }
  setTimeout(_wireReply, 150);

  // Standardized toolbar in the persistent header (Ask AI + pin). Built here at
  // function end so parentMsg/replies are available for the summarize prompt.
  {
    const _thId = thread.thread_id || _slackState.selectedThreadId || '';
    const _thPin = _createPinBtn('slack', String(_thId), (messages[0]?.text || 'Thread').slice(0, 60), { type: 'thread', channel: name });
    tpBuildDetailToolbar({
      app: 'slack',
      back: { onClick: _threadBack, title: 'Back to ' + (isChannel ? '#' : '') + name },
      title: { text: 'Thread in ' + (isChannel ? '#' : '') + name, title: name },
      actions: [
        { kind: 'icon', iconHtml: '✦', title: 'Summarize this thread', group: 0,
          onClick: () => {
            const parentText = parentMsg ? parentMsg.text || '' : '';
            const summary = replies.slice(0, 20).map(m => '- ' + (m.user || '?') + ': ' + (m.text || '').slice(0, 120)).join('\n');
            tpInjectAIPrompt('Summarize this Slack thread:\n\nOriginal: ' + parentText.slice(0, 300) + '\n\nReplies:\n' + summary);
          } },
        { el: _thPin, kind: 'icon', title: 'Pin thread', group: 0 },
      ],
    });
  }
}

function _slackBuildMessage(msg) {
  const el = document.createElement('div');
  el.className = 'slack-msg';
  // msg.user is already resolved by backend; use directly.
  const displayName = msg.user || msg.display_name || msg.username || 'unknown';
  const userId = msg.user_id || '';
  const avatar = document.createElement('div');
  avatar.className = 'tp-avatar tp-avatar-slack';
  avatar.style.fontSize = '.55rem';
  avatar.textContent = _slackInitials(displayName);
  const content = document.createElement('div');
  content.className = 'slack-msg-content';
  const hdr = document.createElement('div');
  hdr.className = 'slack-msg-header';
  const sender = document.createElement('span');
  sender.className = 'slack-msg-sender';
  if (userId) sender.dataset.slackUser = userId;
  sender.textContent = displayName;
  hdr.appendChild(sender);
  content.appendChild(hdr);
  if (msg.forward) {
    if (msg.text) {
      const preBody = document.createElement('div');
      preBody.className = 'slack-msg-body';
      preBody.innerHTML = _slackMrkdwn(msg.text);
      content.appendChild(preBody);
    }
    content.appendChild(_slackBuildForwardPreview(msg.forward));
  } else {
    const body = document.createElement('div');
    body.className = 'slack-msg-body';
    body.innerHTML = _slackMrkdwn(msg.text || msg.body || '');
    content.appendChild(body);
  }
  if ((msg.reactions || []).length) {
    const threadChannelId = _slackState.selectedChannel || '';
    const reactionsEl = _slackBuildReactionsRow(msg.reactions, threadChannelId, msg.ts || '', el);
    if (reactionsEl) content.appendChild(reactionsEl);
  }

  // Add-reaction button for thread replies
  const threadActions = document.createElement('div');
  threadActions.className = 'slack-msg-actions';
  const threadAddReactBtn = document.createElement('button');
  threadAddReactBtn.className = 'tp-msg-action-btn slack-react-add';
  threadAddReactBtn.title = 'Add reaction';
  threadAddReactBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="currentColor"><path d="M480-480Zm0 400q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q43 0 83 8.5t77 24.5v90q-35-20-75.5-31.5T480-800q-133 0-226.5 93.5T160-480q0 133 93.5 226.5T480-160q133 0 226.5-93.5T800-480q0-32-6.5-62T776-600h86q9 29 13.5 58.5T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm320-600v-80h-80v-80h80v-80h80v80h80v80h-80v80h-80ZM620-520q25 0 42.5-17.5T680-580q0-25-17.5-42.5T620-640q-25 0-42.5 17.5T560-580q0 25 17.5 42.5T620-520Zm-280 0q25 0 42.5-17.5T400-580q0-25-17.5-42.5T340-640q-25 0-42.5 17.5T280-580q0 25 17.5 42.5T340-520Zm263.5 221.5Q659-337 684-400H276q25 63 80.5 101.5T480-260q68 0 123.5-38.5Z"/></svg>`;
  threadAddReactBtn.addEventListener('click', e => {
    e.stopPropagation();
    const cid = _slackState.selectedChannel || '';
    const msgTs = msg.ts || '';
    _openFullEmojiPicker(threadAddReactBtn, emoji => _slackReact(cid, msgTs, emoji, el));
  });
  threadActions.appendChild(threadAddReactBtn);
  content.appendChild(threadActions);

  const meta = document.createElement('div');
  meta.className = 'slack-msg-meta';
  meta.textContent = _slackRelTime(msg.timestamp || msg.ts);
  el.appendChild(avatar);
  el.appendChild(content);
  el.appendChild(meta);
  return el;
}

function _slackRenderReactions(reactions) {
  if (!reactions || !reactions.length) return '';
  const pills = reactions.map(r => {
    if (typeof r === 'string') {
      const span = document.createElement('span');
      span.className = 'slack-reaction';
      span.textContent = _slackEmoji(r);
      return span.outerHTML;
    }
    const emoji = _slackEmoji(r.name || r.emoji || '');
    return '<span class="slack-reaction">' + emoji + (r.count ? ' <span class="slack-reaction-count">' + r.count + '</span>' : '') + '</span>';
  });
  return '<div class="slack-reactions">' + pills.join('') + '</div>';
}



/* ── Phase 4: Compose (Post to Channel) ──────────────────── */

/**
 * Extract Slack mrkdwn text from a Quill editor, converting mention embeds to <@UID>.
 * Plain getText() drops the mention embed and leaves a blank character.
 */
function _slackGetTextFromQuill(quill) {
  if (!quill) return '';
  const delta = quill.getContents();
  let text = '';
  for (const op of delta.ops) {
    if (typeof op.insert === 'string') {
      text += op.insert;
    } else if (op.insert && op.insert.mention) {
      const uid = op.insert.mention.id || '';
      text += uid ? `<@${uid}>` : `@${op.insert.mention.name || ''}`;
    }
  }
  // Strip trailing newline Quill always adds
  return text.replace(/\n$/, '').trim();
}

async function _slackPostMessage(channelName, editorOrTextarea, sendBtn, sendAs = 'user', threadId = null) {
  // Support both Quill editor objects ({getHtml, isEmpty, quill}) and plain textareas
  // Use _slackGetTextFromQuill to preserve @mention embed → <@UID> conversion
  const isQuill = typeof editorOrTextarea.getHtml === 'function';
  const msg = isQuill ? _slackGetTextFromQuill(editorOrTextarea.quill) : (editorOrTextarea.value || '').trim();
  const isEmpty = !msg;
  if (isEmpty) return;
  console.log('[Slack send] msg="' + msg + '" channel=' + channelName + ' sendAs=' + sendAs);
  const label = sendBtn.textContent;
  sendBtn.disabled = true;
  sendBtn.textContent = 'Sending\u2026';
  try {
    const payload = { message: msg, send_as: sendAs };
    if (threadId) payload.thread_ts = threadId;
    // /post returns a draft for human approval; /send confirms and actually sends
    const res = await fetch(`/api/slack/channels/${encodeURIComponent(channelName)}/post`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const resBody = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(resBody.detail || `HTTP ${res.status}`);
    }
    // MCP may return validation errors as raw text with 200 status
    if (resBody.raw && /error|validation/i.test(resBody.raw)) {
      throw new Error('Slack MCP error: ' + resBody.raw.split('\n')[0]);
    }
    // Server returns a draft \u2014 show approval prompt before actually sending
    if (resBody.draft) {
      sendBtn.textContent = label;
      sendBtn.disabled = false;
      const confirmed = window.confirm(
        'Send this message to Slack?\n\n"' + msg.slice(0, 200) + (msg.length > 200 ? '\u2026' : '') + '"'
      );
      if (!confirmed) return;
      sendBtn.disabled = true;
      sendBtn.textContent = 'Sending\u2026';
      const sendPayload = { ...payload, confirm_token: resBody.confirm_token };
      const sendRes = await fetch(`/api/slack/channels/${encodeURIComponent(channelName)}/send`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(sendPayload),
      });
      if (!sendRes.ok) {
        const errBody = await sendRes.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${sendRes.status}`);
      }
    }
    if (isQuill) { editorOrTextarea.quill.setText(''); } else { editorOrTextarea.value = ''; editorOrTextarea.style.height = 'auto'; }
    sendBtn.textContent = 'Sent!';
    setTimeout(() => { sendBtn.textContent = label; sendBtn.disabled = true; }, 2000);
  } catch (e) {
    sendBtn.textContent = label;
    sendBtn.disabled = false;
    const bar = sendBtn.closest('.slack-compose-bar') || sendBtn.closest('.slack-dm-compose');
    if (bar) {
      let errEl = bar.querySelector('.slack-compose-error');
      if (!errEl) { errEl = document.createElement('div'); errEl.className = 'slack-compose-error'; bar.appendChild(errEl); }
      errEl.textContent = 'Message couldn\'t be sent \u2014 server unreachable. Try again.';
      setTimeout(() => { if (errEl.parentNode) errEl.remove(); }, 5000);
    }
  }
}


/* ── Phase 5: DM Compose ─────────────────────────────────── */

function _slackShowDMCompose({ prefillText = '', forwardSender = '', forwardText = '', forwardTs = '' } = {}) {
  const isForward = !!(forwardSender || forwardText);
  const col = document.getElementById('tp-detail-col');
  col.innerHTML = '';

  const wrap = document.createElement('div');
  wrap.className = 'slack-dm-compose';

  // Header row: title + back button (back to previous channel view)
  const headerRow = document.createElement('div');
  headerRow.className = 'slack-dm-header-row';
  const backBtn = document.createElement('button');
  backBtn.className = 'slack-dm-back-btn';
  backBtn.title = 'Back';
  backBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="currentColor"><path d="M360-240 120-480l240-240 56 56-144 144h568v80H272l144 144-56 56Z"/></svg>';
  backBtn.addEventListener('click', () => {
    // Return to the previously selected channel/DM view
    const prev = _slackState.selectedChannel;
    const prevName = _slackState._displayName;
    if (prev) _slackSelectChannel(prev, prevName);
    else col.innerHTML = '';
  });
  const headerTitle = document.createElement('span');
  headerTitle.className = 'slack-dm-header-title';
  headerTitle.textContent = isForward ? 'Forward Message' : 'Send a Direct Message';
  headerRow.appendChild(backBtn);
  headerRow.appendChild(headerTitle);
  wrap.appendChild(headerRow);

  // To field
  const toRow = document.createElement('div');
  toRow.className = 'slack-dm-field';
  toRow.innerHTML = `<label class="slack-dm-label">To</label>
    <input type="text" class="slack-dm-recipient" placeholder="Type a name to find..." />
    <div class="slack-dm-resolved hidden"></div>`;
  wrap.appendChild(toRow);

  // Forward preview block (shown above compose, like Teams)
  if (isForward) {
    const preview = document.createElement('div');
    preview.className = 'slack-forward-preview-block';
    const previewLabel = document.createElement('div');
    previewLabel.className = 'slack-forward-preview-label';
    previewLabel.textContent = 'Forwarding message from ' + forwardSender;
    if (forwardTs) {
      const tsSpan = document.createElement('span');
      tsSpan.className = 'slack-forward-preview-ts';
      tsSpan.textContent = ' \u00b7 ' + forwardTs;
      previewLabel.appendChild(tsSpan);
    }
    const previewBody = document.createElement('div');
    previewBody.className = 'slack-forward-preview-body';
    previewBody.textContent = forwardText;
    preview.appendChild(previewLabel);
    preview.appendChild(previewBody);
    wrap.appendChild(preview);
  }

  // Message field
  const msgField = document.createElement('div');
  msgField.className = 'slack-dm-field';
  const msgLabel = document.createElement('label');
  msgLabel.className = 'slack-dm-label';
  msgLabel.textContent = isForward ? 'Add a note (optional)' : 'Message';
  msgField.appendChild(msgLabel);
  const dmEditor = _buildQuillEditor({
    placeholder: isForward ? 'Add a note\u2026' : 'Your message\u2026',
    showSendBtn: true, showResize: false,
  });
  msgField.appendChild(dmEditor.wrapEl);
  wrap.appendChild(msgField);

  const statusEl = document.createElement('div');
  statusEl.className = 'slack-dm-status';
  wrap.appendChild(statusEl);

  col.appendChild(wrap);

  // For forwards, the preview counts as content \u2014 pre-enable send when recipient resolved
  // (no prefill into the compose box; the preview block IS the forward content)

  const recipientInput = wrap.querySelector('.slack-dm-recipient');
  const resolved = wrap.querySelector('.slack-dm-resolved');
  const sendBtn = dmEditor.wrapEl.querySelector('.tp-compose-send');
  const status = wrap.querySelector('.slack-dm-status');
  let resolvedUser = null;
  let debounceTimer = null;

  // For forwards, the preview block is the message — compose box is optional note
  const updateSendState = () => {
    if (sendBtn) sendBtn.disabled = !(resolvedUser && (isForward || !!_slackGetTextFromQuill(dmEditor.quill)));
  };
  function _wireDMQuill() {
    const q = dmEditor.quill;
    if (!q) { setTimeout(_wireDMQuill, 200); return; }
    q.on('text-change', updateSendState);
    q.root.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (sendBtn) sendBtn.click(); }
    });
    _wireMentionDropdownSlack(q, q.root);
    // Wire paperclip attach button (#98)
    const attachBtn = dmEditor.wrapEl.querySelector('.tp-qt-attach-btn');
    if (attachBtn && !attachBtn._slackWired) {
      const fi = document.createElement('input');
      fi.type = 'file'; fi.multiple = true; fi.style.display = 'none';
      dmEditor.wrapEl.appendChild(fi);
      attachBtn.addEventListener('click', () => fi.click());
      attachBtn._slackWired = true;
    }
  }
  setTimeout(_wireDMQuill, 150);

  recipientInput.addEventListener('input', () => {
    resolvedUser = null;
    resolved.classList.add('hidden');
    resolved.innerHTML = '';
    updateSendState();
    clearTimeout(debounceTimer);
    const q = recipientInput.value.trim();
    if (q.length < 3) return;
    debounceTimer = setTimeout(async () => {
      resolved.classList.remove('hidden');
      resolved.innerHTML = '<span style="color:var(--text-dim);font-size:.75rem">Searching...</span>';
      try {
        const res = await fetch(`/api/slack/users/${encodeURIComponent(q)}`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        const u = data.user || data;
        if (u && (u.real_name || u.display_name || u.user_id)) {
          // Store user_id (UID like U0XXXXX) — Slack's chat.postMessage needs a UID or channel ID
          resolvedUser = u.user_id || u.id;
          resolved.innerHTML = `
            <div class="slack-dm-user-card">
              <div class="tp-avatar tp-avatar-slack" style="font-size:.55rem;width:28px;height:28px">${_slackInitials(u.real_name || u.display_name)}</div>
              <div>
                <div style="font-weight:600;font-size:.82rem">${_slackEsc(u.real_name || u.display_name)}</div>
                <div style="font-size:.72rem;color:var(--text-sub)">${_slackEsc(u.title || '')} ${u.email ? '· ' + _slackEsc(u.email) : ''}</div>
              </div>
            </div>`;
          updateSendState();
        } else {
          resolved.innerHTML = `<span style="color:var(--text-dim);font-size:.75rem">No user found for "${_slackEsc(q)}"</span>`;
        }
      } catch {
        resolved.innerHTML = '<span style="color:var(--text-dim);font-size:.75rem">Lookup failed</span>';
      }
    }, 600);
  });

  if (sendBtn) sendBtn.addEventListener('click', async () => {
    if (!resolvedUser || (!isForward && !_slackGetTextFromQuill(dmEditor.quill))) return;
    const label = sendBtn.textContent;
    // Build message: for forwards, prepend attribution + forwarded text, then optional note
    const note = _slackGetTextFromQuill(dmEditor.quill);
    let dmMsg;
    if (isForward) {
      const fwdHeader = `Forwarded from ${forwardSender}:\n${forwardText}`;
      dmMsg = note ? `${fwdHeader}\n\n${note}` : fwdHeader;
    } else {
      dmMsg = note;
    }
    const dmPayload = { user_identifier: resolvedUser, message: dmMsg, send_as: 'user' };
    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending\u2026';
    status.textContent = '';
    try {
      // /api/slack/dm returns a draft; /api/slack/dm/send confirms and actually sends
      const res = await fetch('/api/slack/dm', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(dmPayload),
      });
      const resBody = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(resBody.detail || `HTTP ${res.status}`);
      }
      if (resBody.draft) {
        sendBtn.textContent = label;
        sendBtn.disabled = false;
        const previewMsg = isForward
          ? `Forward message from ${forwardSender} to ${resolvedUser}?`
          : 'Send this DM?\n\n"' + dmMsg.slice(0, 200) + (dmMsg.length > 200 ? '\u2026' : '') + '"';
        const confirmed = window.confirm(previewMsg);
        if (!confirmed) return;
        sendBtn.disabled = true;
        sendBtn.textContent = 'Sending\u2026';
        const sendRes = await fetch('/api/slack/dm/send', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ ...dmPayload, confirm_token: resBody.confirm_token }),
        });
        if (!sendRes.ok) {
          const errBody = await sendRes.json().catch(() => ({}));
          throw new Error(errBody.detail || `HTTP ${sendRes.status}`);
        }
      }
      status.style.color = 'var(--success)';
      status.textContent = 'DM sent!';
      dmEditor.quill.setText('');
      sendBtn.textContent = label;
      sendBtn.disabled = true;
    } catch (e) {
      status.style.color = 'var(--danger, #f87171)';
      status.textContent = 'Couldn\u2019t send \u2014 server unreachable. Try again.';
      sendBtn.textContent = label;
      sendBtn.disabled = false;
    }
  });
}

/* ── Slack Compose Data Receiver (for draft approval "Edit in @slack" link) ── */
function _slackReceiveComposeData(data) {
  if (data.channel) {
    _slackSelectChannel(data.channel).then(() => {
      const ta = document.querySelector('.slack-compose-input');
      if (ta) {
        ta.value = data.message || '';
        ta.dispatchEvent(new Event('input'));
        ta.focus();
      }
    });
  } else if (data.recipient) {
    _slackShowDMCompose();
    setTimeout(() => {
      const recipientInput = document.querySelector('.slack-dm-recipient');
      const messageArea = document.querySelector('.slack-dm-message');
      if (recipientInput) { recipientInput.value = data.recipient; recipientInput.dispatchEvent(new Event('input')); }
      if (messageArea) { messageArea.value = data.message || ''; }
    }, 200);
  }
}


/* ══════════════════════════════════════════════════════════════
   CONFLUENCE WIKI PANE
   ══════════════════════════════════════════════════════════ */

const _cfState = {
  activeTab: 'recent',   // kept for breadcrumb back-nav compatibility
  scope: 'recent',       // 'recent' | 'pages' | 'spaces' | 'all'
  searchQuery: '',
  list: [],
  selectedPageId: null,
  breadcrumb: [],
  loading: false,
  allSpaces: [],  // cached for client-side filtering
  _scopeSelect: null,
  _scopeCleanup: null,
};

/* ── Custom scope selector (compact toolbar variant) ── */
function _buildCfScopeSelect(opts, selectedVal) {
  let currentValue = selectedVal || opts[0]?.value || '';

  const wrap = document.createElement('div');
  wrap.className = 'cf-scope-csel';

  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'cf-scope-csel-trigger';

  const label = document.createElement('span');
  label.className = 'cf-scope-csel-label';
  trigger.appendChild(label);
  trigger.insertAdjacentHTML('beforeend',
    `<svg class="cf-scope-csel-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none"
       stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
       <polyline points="6 9 12 15 18 9"/></svg>`);
  wrap.appendChild(trigger);

  const panel = document.createElement('div');
  panel.className = 'cf-scope-csel-panel';
  document.body.appendChild(panel);

  function position() {
    const r = trigger.getBoundingClientRect();
    panel.style.left = r.left + 'px';
    panel.style.minWidth = Math.max(r.width, 100) + 'px';
    const spaceBelow = window.innerHeight - r.bottom;
    if (spaceBelow < 160 && r.top > 160) {
      panel.style.top = 'auto';
      panel.style.bottom = (window.innerHeight - r.top + 4) + 'px';
    } else {
      panel.style.top = (r.bottom + 4) + 'px';
      panel.style.bottom = 'auto';
    }
  }

  function open() {
    // Close any other open scope panels
    document.querySelectorAll('.cf-scope-csel-panel.open').forEach(p => p.classList.remove('open'));
    document.querySelectorAll('.cf-scope-csel.open').forEach(w => w.classList.remove('open'));
    wrap.classList.add('open');
    position();
    panel.classList.add('open');
  }

  function close() {
    wrap.classList.remove('open');
    panel.classList.remove('open');
  }

  function setDisplay(val) {
    currentValue = val;
    const opt = opts.find(o => o.value === val);
    label.textContent = opt?.label || val;
    panel.querySelectorAll('.cf-scope-csel-option').forEach(el =>
      el.classList.toggle('selected', el.dataset.value === val));
  }

  // Build options
  opts.forEach(opt => {
    const item = document.createElement('div');
    item.className = 'cf-scope-csel-option';
    item.dataset.value = opt.value;
    item.textContent = opt.label;
    if (opt.value === currentValue) item.classList.add('selected');
    item.addEventListener('click', () => {
      setDisplay(opt.value);
      close();
      wrap.dispatchEvent(new Event('change'));
    });
    panel.appendChild(item);
  });

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    wrap.classList.contains('open') ? close() : open();
  });

  const outsideClick = (e) => {
    if (!wrap.contains(e.target) && !panel.contains(e.target)) close();
  };
  document.addEventListener('click', outsideClick);

  setDisplay(currentValue);

  return {
    el: wrap,
    getValue: () => currentValue,
    setValue: (val) => setDisplay(val),
    destroy: () => {
      document.removeEventListener('click', outsideClick);
      panel.remove();
    },
  };
}

function _initConfluencePane() {
  const listCol = document.getElementById('tp-list-col');
  const detailCol = document.getElementById('tp-detail-col');
  if (!listCol || !detailCol) return;

  _cfState.breadcrumb = [];
  _cfState.selectedPageId = null;
  _cfState.activeTab = 'recent';
  _cfState.searchQuery = '';

  listCol.innerHTML = '';
  listCol.style.display = 'flex';
  listCol.style.flexDirection = 'column';
  listCol.style.overflow = 'hidden';

  // ── Tab bar: [Spaces] [Pages] [Recent] ──
  const tabBar = document.createElement('div');
  tabBar.className = 'cf-tab-bar';
  tabBar.innerHTML = `
    <button class="cf-tab" data-tab="spaces">Spaces</button>
    <button class="cf-tab" data-tab="my-pages">My Pages</button>
    <button class="cf-tab cf-tab-active" data-tab="recent">Recent</button>
  `;
  listCol.appendChild(tabBar);

  tabBar.querySelectorAll('.cf-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      tabBar.querySelectorAll('.cf-tab').forEach(b => b.classList.remove('cf-tab-active'));
      btn.classList.add('cf-tab-active');
      _cfState.activeTab = btn.dataset.tab;
      _cfState.breadcrumb = [];
      _cfUpdateBreadcrumb();
      _cfLoadTab(_cfState.activeTab);
    });
  });

  // ── Breadcrumb placeholder ──
  const breadcrumbBar = document.createElement('div');
  breadcrumbBar.className = 'cf-breadcrumb';
  breadcrumbBar.id = 'cf-breadcrumb';
  breadcrumbBar.style.display = 'none';
  listCol.appendChild(breadcrumbBar);

  // ── List container ──
  const listContainer = document.createElement('div');
  listContainer.className = 'cf-page-list';
  listContainer.id = 'cf-page-list';
  listCol.appendChild(listContainer);

  // ── Inject custom scope selector into toolbar search panel ──
  const searchPanel = document.getElementById('tp-toolbar-search');
  const searchInput = document.getElementById('tp-search-input');
  // Clean up any previous scope dropdown
  _cfState._scopeCleanup?.();
  document.getElementById('cf-scope-wrap')?.remove();

  if (searchPanel && searchInput) {
    const scopeOpts = [
      { value: 'all', label: 'All' },
      { value: 'pages', label: 'Pages' },
      { value: 'spaces', label: 'Spaces' },
      { value: 'recent', label: 'Recent' },
    ];
    const scope = _buildCfScopeSelect(scopeOpts, 'all');
    scope.el.id = 'cf-scope-wrap';
    // Guard: only insert if searchInput is actually a child of searchPanel.
    // Rapid pane switches can leave a stale searchInput reference, which made
    // insertBefore throw NotFoundError and abort the Confluence pane init.
    if (searchInput.parentNode === searchPanel) {
      searchPanel.insertBefore(scope.el, searchInput);
    } else {
      searchPanel.appendChild(scope.el);
    }
    _cfState._scopeSelect = scope;
    _cfState._scopeCleanup = () => { scope.destroy(); _cfState._scopeSelect = null; };

    scope.el.addEventListener('change', () => {
      if (_cfState.searchQuery) _cfSearch();
    });
  }

  // Wire toolbar search input
  let _cfDebounce = null;
  searchInput.oninput = () => {
    const q = searchInput.value.trim();
    _cfState.searchQuery = q;
    clearTimeout(_cfDebounce);
    if (!q) { _cfLoadTab(_cfState.activeTab); return; }
    { const _sp=document.getElementById('tp-search-spinner'); const _sw=document.getElementById('tp-search-wrap'); if(_sp)_sp.classList.remove('hidden'); if(_sw)_sw.classList.add('is-searching'); }
    _cfDebounce = setTimeout(() => _cfSearch(), 380);
  };
  searchInput.onkeydown = (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    clearTimeout(_cfDebounce);
    const q = searchInput.value.trim();
    if (!q) return;
    _cfState.searchQuery = q;
    _cfSearch();
  };

  // Wire search close — restore active tab view
  const closeBtn = document.getElementById('tp-search-close');
  if (closeBtn) {
    const _origClose = closeBtn.onclick;
    closeBtn.onclick = () => {
      _cfState.searchQuery = '';
      _cfState._scopeSelect?.setValue('all');
      _cfLoadTab(_cfState.activeTab);
      if (_origClose) _origClose.call(closeBtn);
    };
  }

  detailCol.innerHTML = _gatorDetailHint('confluence');
  _cfLoadTab('recent');
}

async function _cfLoadTab(tab) {
  _cfState.activeTab = tab;
  // Sync tab bar active state (called from breadcrumb back / post-create too)
  document.querySelectorAll('.cf-tab').forEach(b => {
    b.classList.toggle('cf-tab-active', b.dataset.tab === tab);
  });
  _cfState.breadcrumb = [];

  const container = document.getElementById('cf-page-list');
  if (!container) return;
  container.innerHTML = _cfSkeleton();
  try {
    if (tab === 'recent') {
      const cached = _getListCache('confluence');
      if (cached) { _cfRenderPageList(container, cached.data, 'Recently Updated'); return; }
      const res = await fetch('/api/confluence/recent-pages');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (tpState.type !== 'confluence' || !container.isConnected) return; // pane switched mid-fetch
      _setListCache('confluence', data.pages || []);
      _cfRenderPageList(container, data.pages || [], 'Recently Updated');

    } else if (tab === 'my-pages') {
      const res = await fetch('/api/confluence/my-pages');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (tpState.type !== 'confluence' || !container.isConnected) return;
      _cfRenderPageList(container, data.pages || [], 'My Pages');

    } else if (tab === 'spaces') {
      if (_cfState.allSpaces.length) {
        _cfRenderSpaceList(container, _cfState.allSpaces);
      } else {
        const res = await fetch('/api/confluence/spaces');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (tpState.type !== 'confluence' || !container.isConnected) return;
        _cfState.allSpaces = data.spaces || [];
        _cfRenderSpaceList(container, _cfState.allSpaces);
      }
    }
  } catch (e) {
    if (tpState.type !== 'confluence' || !container.isConnected) return;
    container.innerHTML = `<div class="cf-empty">\u26A0 ${e.message || 'Failed to load'}. Check your Confluence credentials in Settings.</div>`;
  }
}

async function _cfSearch() {
  const query = _cfState.searchQuery;
  const scope = _cfState._scopeSelect?.getValue() || 'all';
  const container = document.getElementById('cf-page-list');
  if (!container || !query) return;
  { const _sp=document.getElementById('tp-search-spinner'); const _sw=document.getElementById('tp-search-wrap'); if(_sp)_sp.classList.remove('hidden'); if(_sw)_sw.classList.add('is-searching'); }
  // Sync tab bar to match scope (spaces → Spaces tab, pages/recent → that tab, all → keep current)
  const tabMap = { spaces: 'spaces', pages: 'pages', recent: 'recent' };
  if (tabMap[scope]) {
    _cfState.activeTab = tabMap[scope];
    document.querySelectorAll('.cf-tab').forEach(b => {
      b.classList.toggle('cf-tab-active', b.dataset.tab === tabMap[scope]);
    });
  }
  _cfSearchPages(query, scope, container);
}

// _cfLoad kept as alias for any call sites not yet updated
function _cfLoad() { _cfLoadTab(_cfState.activeTab); }

async function _cfSearchPages(query, scope, container) {
  _cfState.breadcrumb = [];
  _cfUpdateBreadcrumb();
  if (!container) container = document.getElementById('cf-page-list');
  if (!container) return;
  container.innerHTML = _cfSkeleton();
  const label = scope === 'pages' ? 'Pages' : scope === 'spaces' ? 'Spaces' : scope === 'all' ? 'All' : '';
  const scopeLabel = label ? ` in ${label}` : '';
  try {
    const res = await fetch('/api/confluence/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, scope: scope || 'all' }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.spaces && data.spaces.length) {
      // Mixed result: spaces section + pages section
      container.innerHTML = '';
      if (data.spaces.length) {
        const hdr = document.createElement('div');
        hdr.className = 'cf-list-header';
        hdr.textContent = `Spaces matching \u201C${query}\u201D`;
        container.appendChild(hdr);
        data.spaces.forEach(space => {
          const row = document.createElement('div');
          row.className = 'cf-page-row cf-space-row';
          row.innerHTML = `
            <span class="cf-space-icon">\u{1F4DA}</span>
            <div class="cf-page-info">
              <span class="cf-page-title">${_cfEsc(space.name)}</span>
              <span class="cf-page-meta">${_cfEsc(space.key)}</span>
            </div>
            <span class="cf-chevron">\u203A</span>`;
          row.addEventListener('click', () => _cfDrillIntoSpace(space.key, space.name));
          container.appendChild(row);
        });
      }
      if (data.pages && data.pages.length) {
        const hdr2 = document.createElement('div');
        hdr2.className = 'cf-list-header';
        hdr2.textContent = `Pages matching \u201C${query}\u201D`;
        container.appendChild(hdr2);
        data.pages.forEach(page => container.appendChild(_buildConfluencePageRow(page)));
      }
      if (!data.pages?.length && !data.spaces?.length) {
        container.insertAdjacentHTML('beforeend', '<div class="cf-empty">No results found</div>');
      }
    } else {
      _cfRenderPageList(container, data.pages || [], `Results for \u201C${query}\u201D${scopeLabel}`);
    }
  } catch (e) {
    container.innerHTML = `<div class="cf-empty">\u26A0 Search failed. ${e.message}</div>`;
  } finally {
    const _sp=document.getElementById('tp-search-spinner'); const _sw=document.getElementById('tp-search-wrap'); if(_sp)_sp.classList.add('hidden'); if(_sw)_sw.classList.remove('is-searching');
  }
}

function _cfRenderPageList(container, pages, title) {
  container.innerHTML = '';
  if (title) {
    const hdr = document.createElement('div');
    hdr.className = 'cf-list-header';
    hdr.textContent = title;
    container.appendChild(hdr);
  }
  if (!pages?.length) {
    container.insertAdjacentHTML('beforeend', '<div class="cf-empty">No pages found</div>');
    return;
  }
  pages.forEach(page => container.appendChild(_buildConfluencePageRow(page)));
}

function _buildConfluencePageRow(page) {
  // Extract page ID from URL as fallback if id is missing
  if (!page.id && page.url) {
    const m = page.url.match(/\/pages\/(\d+)/);
    if (m) page.id = m[1];
  }

  const row = document.createElement('div');
  row.className = 'cf-page-row';
  row.dataset.id = page.id;

  const spaceTag = page.space ? `<span class="cf-space-tag">${_cfEsc(page.space)}</span>` : '';
  const modified = page.last_modified ? _cfRelTime(page.last_modified) : '';

  row.innerHTML = `
    <span class="cf-page-icon">\u{1F4C4}</span>
    <div class="cf-page-info">
      <span class="cf-page-title" title="${_cfEsc(page.title)}">${_cfEsc(page.title)}</span>
      <span class="cf-page-meta">${spaceTag}${modified ? ' \u00B7 ' + modified : ''}</span>
    </div>
  `;

  row.appendChild(_createPinBtn('confluence', page.id, page.title, {
    url: page.url || '',
    space: page.space || '',
  }));

  row.addEventListener('click', () => {
    document.querySelectorAll('.cf-page-row.active').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
    _cfState.selectedPageId = page.id;
    tpState.selectedId = page.id;
    const detailCol = document.getElementById('tp-detail-col');
    if (detailCol) _renderConfluencePageDetail(detailCol, page.id, page.url);
  });

  return row;
}

function _cfGetFavoriteSpaces() {
  try { return JSON.parse(localStorage.getItem('gator-cf-fav-spaces') || '[]'); } catch { return []; }
}
function _cfSetFavoriteSpaces(favs) {
  localStorage.setItem('gator-cf-fav-spaces', JSON.stringify(favs));
}

function _cfRenderSpaceList(container, spaces) {
  container.innerHTML = '';
  const favKeys = new Set(_cfGetFavoriteSpaces());

  // Sort: favorites first, then alphabetical
  const sorted = [...spaces].sort((a, b) => {
    const aFav = favKeys.has(a.key) ? 0 : 1;
    const bFav = favKeys.has(b.key) ? 0 : 1;
    if (aFav !== bFav) return aFav - bFav;
    return (a.name || '').localeCompare(b.name || '');
  });

  // Favorites section
  const favSpaces = sorted.filter(s => favKeys.has(s.key));
  if (favSpaces.length) {
    const favHdr = document.createElement('div');
    favHdr.className = 'cf-list-header';
    favHdr.textContent = 'Favorites';
    container.appendChild(favHdr);
    favSpaces.forEach(space => container.appendChild(_cfBuildSpaceRow(space, true, container, spaces)));
  }

  // All spaces section
  const hdr = document.createElement('div');
  hdr.className = 'cf-list-header';
  hdr.textContent = favSpaces.length ? 'All Spaces' : 'Spaces';
  container.appendChild(hdr);
  if (!spaces.length) {
    container.insertAdjacentHTML('beforeend', '<div class="cf-empty">No spaces found</div>');
    return;
  }
  const nonFav = sorted.filter(s => !favKeys.has(s.key));
  nonFav.forEach(space => container.appendChild(_cfBuildSpaceRow(space, false, container, spaces)));
}

function _cfBuildSpaceRow(space, isFav, container, allSpaces) {
  const row = document.createElement('div');
  row.className = 'cf-page-row cf-space-row';
  row.innerHTML = `
    <span class="cf-space-icon">\u{1F4DA}</span>
    <div class="cf-page-info">
      <span class="cf-page-title">${_cfEsc(space.name)}</span>
      <span class="cf-page-meta">${_cfEsc(space.key)}</span>
    </div>
  `;
  // Star toggle
  const star = document.createElement('button');
  star.className = 'cf-space-star' + (isFav ? ' cf-star-active' : '');
  star.textContent = isFav ? '\u2605' : '\u2606';
  star.title = isFav ? 'Remove from favorites' : 'Add to favorites';
  star.addEventListener('click', (e) => {
    e.stopPropagation();
    const favs = _cfGetFavoriteSpaces();
    if (isFav) {
      _cfSetFavoriteSpaces(favs.filter(k => k !== space.key));
    } else {
      favs.push(space.key);
      _cfSetFavoriteSpaces(favs);
    }
    _cfRenderSpaceList(container, allSpaces);
  });
  row.appendChild(star);

  const chevron = document.createElement('span');
  chevron.className = 'cf-chevron';
  chevron.textContent = '\u203A';
  row.appendChild(chevron);

  row.addEventListener('click', () => _cfDrillIntoSpace(space.key, space.name));
  return row;
}

/* ── Tree-based hierarchy navigation ── */

async function _cfDrillIntoSpace(spaceKey, spaceName) {
  const container = document.getElementById('cf-page-list');
  if (!container) return;
  _cfState.breadcrumb = [{ type: 'space', key: spaceKey, name: spaceName }];
  _cfUpdateBreadcrumb();
  container.innerHTML = _cfSkeleton();
  try {
    const res = await fetch(`/api/confluence/space/${encodeURIComponent(spaceKey)}/pages`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    container.innerHTML = '';
    const hdr = document.createElement('div');
    hdr.className = 'cf-list-header';
    hdr.textContent = spaceName;
    container.appendChild(hdr);
    const pages = data.pages || [];
    if (!pages.length) {
      container.insertAdjacentHTML('beforeend', '<div class="cf-empty">No pages in this space</div>');
      return;
    }
    pages.forEach(page => container.appendChild(_buildConfluenceTreeRow(page, 0)));
  } catch (e) {
    container.innerHTML = `<div class="cf-empty">\u26A0 ${e.message}</div>`;
  }
}

function _buildConfluenceTreeRow(page, depth) {
  // Extract page ID from URL as fallback
  if (!page.id && page.url) {
    const m = page.url.match(/\/pages\/(\d+)/);
    if (m) page.id = m[1];
  }

  const wrap = document.createElement('div');
  wrap.className = 'cf-tree-node';

  const row = document.createElement('div');
  row.className = 'cf-tree-row';
  row.style.paddingLeft = (10 + depth * 16) + 'px';

  // Expand/collapse chevron (always present — lazy-loads children)
  const chevron = document.createElement('span');
  chevron.className = 'cf-tree-chevron';
  chevron.textContent = '\u25B6';
  chevron.title = 'Expand';
  row.appendChild(chevron);

  // Page icon
  const icon = document.createElement('span');
  icon.className = 'cf-page-icon';
  icon.textContent = '\u{1F4C4}';
  row.appendChild(icon);

  // Title
  const title = document.createElement('span');
  title.className = 'cf-tree-title';
  title.textContent = page.title || 'Untitled';
  title.title = page.title || '';
  row.appendChild(title);

  // Pin button
  row.appendChild(_createPinBtn('confluence', page.id, page.title, {
    url: page.url || '', space: page.space || '',
  }));

  // Children container (hidden initially)
  const childContainer = document.createElement('div');
  childContainer.className = 'cf-tree-children';
  childContainer.style.display = 'none';

  let expanded = false;
  let childrenLoaded = false;

  // Click chevron to expand/collapse
  chevron.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (expanded) {
      // Collapse
      expanded = false;
      chevron.textContent = '\u25B6';
      chevron.classList.remove('cf-tree-chevron-open');
      childContainer.style.display = 'none';
    } else {
      // Expand
      expanded = true;
      chevron.textContent = '\u25BC';
      chevron.classList.add('cf-tree-chevron-open');
      childContainer.style.display = '';
      if (!childrenLoaded) {
        childrenLoaded = true;
        childContainer.innerHTML = '<div class="cf-tree-loading">Loading\u2026</div>';
        try {
          const res = await fetch(`/api/confluence/page/${encodeURIComponent(page.id)}/children`);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = await res.json();
          childContainer.innerHTML = '';
          const children = data.children || [];
          if (!children.length) {
            chevron.style.visibility = 'hidden';
            childContainer.style.display = 'none';
          } else {
            children.forEach(child => childContainer.appendChild(_buildConfluenceTreeRow(child, depth + 1)));
          }
        } catch {
          childContainer.innerHTML = '<div class="cf-tree-loading" style="color:var(--danger)">Failed to load</div>';
        }
      }
    }
  });

  // Click row to show detail
  row.addEventListener('click', () => {
    document.querySelectorAll('.cf-tree-row.active').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
    _cfState.selectedPageId = page.id;
    const detailCol = document.getElementById('tp-detail-col');
    if (detailCol) _renderConfluencePageDetail(detailCol, page.id, page.url);
  });

  wrap.appendChild(row);
  wrap.appendChild(childContainer);
  return wrap;
}

function _cfUpdateBreadcrumb() {
  const bar = document.getElementById('cf-breadcrumb');
  if (!bar) return;
  if (!_cfState.breadcrumb.length) {
    bar.style.display = 'none';
    bar.innerHTML = '';
    return;
  }
  bar.style.display = 'flex';
  bar.innerHTML = '';

  const backBtn = document.createElement('button');
  backBtn.className = 'cf-breadcrumb-btn';
  backBtn.textContent = '\u2190 Back';
  backBtn.addEventListener('click', () => {
    _cfState.breadcrumb = [];
    _cfUpdateBreadcrumb();
    _cfLoadTab(_cfState.activeTab);
  });
  bar.appendChild(backBtn);

  const label = document.createElement('span');
  label.className = 'cf-breadcrumb-label';
  label.textContent = _cfState.breadcrumb.map(b => b.name).join(' / ');
  bar.appendChild(label);
}

/* ── Detail view ── */

async function _renderConfluencePageDetail(container, pageId, fallbackUrl) {
  container.innerHTML = '<div class="cf-loading" style="padding:20px">Loading page\u2026</div>';
  try {
    const res = await fetch(`/api/confluence/page/${encodeURIComponent(pageId)}`);
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    _cfBuildPageDetail(container, data, fallbackUrl);
  } catch (err) {
    container.innerHTML = `<div class="cf-empty" style="color:#f87171;padding:20px">\u26A0 ${_cfEsc(err.message)}</div>`;
  }
}

// Resolve a theme-aware palette for content rendered inside an isolated iframe
// (Confluence page body, etc.). CSS custom properties don't cross the iframe
// boundary, so we read the host's computed token values and map them to concrete
// colors. Falls back to sensible per-theme defaults if a token is unset.
function _tpFramePalette() {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  const cs = getComputedStyle(document.documentElement);
  const tok = (name, fallback) => (cs.getPropertyValue(name).trim() || fallback);
  return {
    bg:        tok('--surface',  isLight ? '#ffffff' : '#0f172a'),
    text:      tok('--text',     isLight ? '#0f172a' : '#e2e8f0'),
    heading:   tok('--text',     isLight ? '#0f172a' : '#f1f5f9'),
    dim:       tok('--text-dim', isLight ? '#475569' : 'rgba(255,255,255,.65)'),
    link:      tok('--accent',   isLight ? '#2563eb' : '#60a5fa'),
    border:    tok('--border',   isLight ? '#cbd5e1' : 'rgba(255,255,255,.12)'),
    subtle:    isLight ? 'rgba(0,0,0,.04)' : 'rgba(255,255,255,.06)',
    scrollThumb:      tok('--border2', isLight ? '#94a3b8' : 'rgba(42,74,107,.8)'),
    scrollThumbHover: tok('--border2', isLight ? '#64748b' : 'rgba(60,100,140,.9)'),
  };
}

// Render Confluence storage HTML into a sandboxed, styled iframe so a human
// reads the page the way it will look — not raw markup. Reused by the page
// detail view and the edit-form preview.
function _cfRenderBodyFrame(bodyHtml) {
  const frame = document.createElement('iframe');
  frame.className = 'cf-detail-body-frame';
  frame.setAttribute('sandbox', 'allow-same-origin');
  frame.title = 'Confluence page content';
  // The iframe is an isolated document — the host app's CSS variables don't
  // cross into it, so we resolve the current theme and inject a matching palette.
  // Without this the page rendered with a hardcoded dark palette (#132/#142
  // family of light-mode bugs): a dark island on a white app.
  const _pal = _tpFramePalette();
  requestAnimationFrame(() => {
    const doc = frame.contentDocument || (frame.contentWindow ? frame.contentWindow.document : null);
    if (!doc) return;
    doc.open();
    doc.write(`<!DOCTYPE html><html><head><meta charset="utf-8">
      <style>
        *{box-sizing:border-box;}
        body{font-family:-apple-system,'Segoe UI',sans-serif;font-size:13px;color:${_pal.text};
          background:${_pal.bg};padding:1rem 1.2rem;line-height:1.6;margin:0;
          overflow-x:hidden;word-wrap:break-word;overflow-wrap:break-word;width:100%;}
        a{color:${_pal.link};}
        img{max-width:100%;height:auto;display:block;}
        .table-wrap{overflow-x:auto;max-width:100%;margin:.5em 0;}
        table{border-collapse:collapse;width:auto;max-width:100%;font-size:12px;}
        td,th{border:1px solid ${_pal.border};padding:6px 10px;white-space:nowrap;}
        th{background:${_pal.subtle};font-weight:600;}
        pre,code{background:${_pal.subtle};border-radius:4px;padding:2px 4px;font-size:12px;}
        pre{padding:12px;white-space:pre-wrap;overflow-x:auto;max-width:100%;}
        h1,h2,h3,h4{color:${_pal.heading};margin-top:1em;margin-bottom:.3em;}
        h1{font-size:1.4em;} h2{font-size:1.2em;} h3{font-size:1.05em;} h4{font-size:.95em;}
        hr{border:none;border-top:1px solid ${_pal.border};margin:1em 0;}
        blockquote{border-left:3px solid ${_pal.border};margin-left:0;padding-left:12px;color:${_pal.dim};}
        ul,ol{padding-left:1.5em;}
        li{margin-bottom:.25em;}
        .confluenceTable,table.wrapped{max-width:100%;}
        /* Scrollbar styling (match host app) */
        ::-webkit-scrollbar{width:4px;height:4px;}
        ::-webkit-scrollbar-track{background:transparent;}
        ::-webkit-scrollbar-thumb{background:${_pal.scrollThumb};border-radius:4px;}
        ::-webkit-scrollbar-thumb:hover{background:${_pal.scrollThumbHover};}
        *{scrollbar-width:thin;scrollbar-color:${_pal.scrollThumb} transparent;}
      </style>
    </head><body>${bodyHtml}</body></html>`);
    doc.close();
    // Wrap bare tables in scrollable containers
    doc.querySelectorAll('table').forEach(tbl => {
      if (tbl.parentElement?.classList.contains('table-wrap')) return;
      const w = doc.createElement('div');
      w.className = 'table-wrap';
      tbl.parentNode.insertBefore(w, tbl);
      w.appendChild(tbl);
    });
    // Intercept links
    doc.addEventListener('click', e => {
      const a = e.target.closest('a[href]');
      if (a) { e.preventDefault(); window.open(a.href, '_blank', 'noopener'); }
    });
    // Auto-resize with ResizeObserver
    const resize = () => {
      try { const h = doc.body.scrollHeight; if (h > 0) frame.style.height = h + 'px'; } catch {}
    };
    resize();
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(resize);
      ro.observe(doc.body);
    } else {
      setTimeout(resize, 300);
      setTimeout(resize, 1000);
    }
    setTimeout(resize, 200);
  });
  return frame;
}

function _cfBuildPageDetail(container, page, fallbackUrl) {
  container.innerHTML = '';
  const pane = document.createElement('div');
  pane.className = 'cf-detail-pane';


  // Collapsible page-info meta row (content \u2014 lives in the pane, toggled from toolbar)
  const metaRow = document.createElement('div');
  metaRow.className = 'cf-detail-meta-inline';
  const metaParts = [
    page.version ? `v${page.version}` : '',
    page.last_modified ? _cfRelTime(page.last_modified) : '',
    page.last_modifier ? `by ${page.last_modifier}` : '',
    page.space || '',
  ].filter(Boolean);
  metaRow.textContent = metaParts.join(' \u00B7 ');

  // Standardized toolbar in the persistent header (#tp-detail-header)
  const _cfUrl = page.url || fallbackUrl || '#';
  const _cfPin = _createPinBtn('confluence', page.id, page.title, { url: page.url || '', space: page.space || '' });
  const _cfActions = [
    { kind: 'icon', iconHtml: '\u2726', title: 'Ask Gator about this page', group: 0,
      onClick: () => tpInjectAIPrompt(`Summarize this Confluence page "${page.title}".`) },
  ];
  if (metaParts.length) {
    _cfActions.push({ kind: 'icon', iconHtml: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>', title: 'Toggle page info', group: 0, onClick: () => metaRow.classList.toggle('open') });
  }
  // No Edit \u2014 pages aren't editable in-app. Open externally only.
  _cfActions.push({ kind: 'icon', iconHtml: _TP_EXT_LINK_SVG, title: 'Open in Confluence', group: 1,
    onClick: () => window.open(_cfUrl, '_blank', 'noopener') });
  _cfActions.push({ el: _cfPin, kind: 'icon', title: 'Pin page', group: 1 });

  tpBuildDetailToolbar({
    app: 'confluence',
    title: { text: page.title || 'Untitled', title: page.title || '', onClick: () => window.open(_cfUrl, '_blank', 'noopener') },
    actions: _cfActions,
  });

  // ── Collapsible meta row ──
  pane.appendChild(metaRow);

  // ── Scrollable content area ──
  const scroll = document.createElement('div');
  scroll.className = 'cf-detail-scroll';

  // Body — sandboxed iframe for rich HTML. Prefer the server-rendered view
  // (macros display faithfully); fall back to storage if view isn't available.
  const _displayHtml = page.body_view || page.body_html;
  if (_displayHtml) {
    scroll.appendChild(_cfRenderBodyFrame(_displayHtml));
  } else {
    scroll.innerHTML = '<div style="padding:1rem;color:var(--text-sub);font-size:.82rem">(Empty page)</div>';
  }

  // Child pages
  if (page.children && page.children.length) {
    const childSection = document.createElement('div');
    childSection.style.padding = '0 14px 14px';
    const childHdr = document.createElement('div');
    childHdr.className = 'cf-detail-section-label';
    childHdr.textContent = `Child Pages (${page.children.length})`;
    childSection.appendChild(childHdr);
    page.children.forEach(child => {
      const childRow = document.createElement('div');
      childRow.className = 'cf-detail-child-row';
      childRow.innerHTML = `<span class="cf-page-icon">\u{1F4C4}</span> ${_cfEsc(child.title)}`;
      childRow.addEventListener('click', () => {
        _renderConfluencePageDetail(container, child.id, child.url);
      });
      childSection.appendChild(childRow);
    });
    scroll.appendChild(childSection);
  }

  pane.appendChild(scroll);
  container.appendChild(pane);
}

/* ── Create form ── */

async function _renderConfluenceCreateForm(container, data) {
  container.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'cf-form-wrap';

  const title = document.createElement('h2');
  title.className = 'cf-form-title';
  title.textContent = 'Create Confluence Page';
  wrap.appendChild(title);

  // Searchable space picker
  const spaceField = _cfField('Space', true);
  const spaceWrap = document.createElement('div');
  spaceWrap.className = 'cf-space-picker';
  const spaceInput = document.createElement('input');
  spaceInput.className = 'cf-field-input';
  spaceInput.placeholder = 'Search spaces\u2026';
  spaceInput.autocomplete = 'off';
  const spaceHidden = document.createElement('input');
  spaceHidden.type = 'hidden';
  spaceHidden.className = 'cf-space-value';
  const spaceList = document.createElement('div');
  spaceList.className = 'cf-space-list';
  spaceWrap.appendChild(spaceInput);
  spaceWrap.appendChild(spaceHidden);
  spaceWrap.appendChild(spaceList);
  spaceField.appendChild(spaceWrap);
  wrap.appendChild(spaceField);

  let _allSpaces = [];
  const _renderSpaceList = (q) => {
    const query = (q || '').toLowerCase();
    const filtered = query ? _allSpaces.filter(s => s.name.toLowerCase().includes(query) || s.key.toLowerCase().includes(query)) : _allSpaces;
    spaceList.innerHTML = '';
    if (!filtered.length) { spaceList.innerHTML = '<div class="cf-space-option cf-space-empty">No matches</div>'; return; }
    filtered.slice(0, 30).forEach(s => {
      const opt = document.createElement('div');
      opt.className = 'cf-space-option' + (s.key === spaceHidden.value ? ' selected' : '');
      const badge = s.type === 'personal' ? ' <span class="cf-space-personal">\uD83D\uDC64</span>' : '';
      opt.innerHTML = `${_cfEsc(s.name)} <span class="cf-space-key">(${_cfEsc(s.key)})</span>${badge}`;
      opt.addEventListener('click', () => {
        spaceHidden.value = s.key;
        spaceInput.value = `${s.name} (${s.key})`;
        spaceList.classList.remove('open');
      });
      spaceList.appendChild(opt);
    });
  };
  spaceInput.addEventListener('focus', () => { spaceList.classList.add('open'); _renderSpaceList(spaceInput.value); });
  spaceInput.addEventListener('input', () => { spaceList.classList.add('open'); _renderSpaceList(spaceInput.value); });
  document.addEventListener('click', e => { if (!spaceWrap.contains(e.target)) spaceList.classList.remove('open'); });

  // Load spaces
  fetch('/api/confluence/spaces')
    .then(r => r.json())
    .then(d => {
      _allSpaces = d.spaces || [];
      // Use personal_space_key from API if available and user asked for personal space
      const personalKey = d.personal_space_key || '';
      if (data.space_key) {
        const sk = data.space_key;
        let match = _allSpaces.find(s => s.key === sk);
        if (!match) {
          // Space not in list — add it (common for personal spaces)
          match = { key: sk, name: sk.startsWith('~') ? 'My Personal Space' : sk, type: sk.startsWith('~') ? 'personal' : 'global' };
          _allSpaces.unshift(match);
        }
        spaceHidden.value = match.key;
        spaceInput.value = `${match.name} (${match.key})`;
      } else if (personalKey && !_allSpaces.find(s => s.key === personalKey)) {
        _allSpaces.unshift({ key: personalKey, name: 'My Personal Space', type: 'personal' });
      }
      _renderSpaceList('');
    })
    .catch(() => { spaceList.innerHTML = '<div class="cf-space-option cf-space-empty">Failed to load spaces</div>'; });

  // Title input
  const titleField = _cfField('Title', true);
  const titleInput = document.createElement('input');
  titleInput.className = 'cf-field-input';
  titleInput.type = 'text';
  titleInput.placeholder = 'Page title';
  titleInput.value = data.title || '';
  titleField.appendChild(titleInput);
  wrap.appendChild(titleField);

  // Parent ID (optional)
  const parentField = _cfField('Parent Page ID');
  const parentInput = document.createElement('input');
  parentInput.className = 'cf-field-input';
  parentInput.type = 'text';
  parentInput.placeholder = 'Optional \u2014 numeric page ID';
  parentInput.value = data.parent_id || '';
  parentField.appendChild(parentInput);
  wrap.appendChild(parentField);

  // Body — rich text editor (Quill)
  const bodyField = _cfField('Body');
  const editorWrap = document.createElement('div');
  editorWrap.className = 'cf-editor-wrap';
  const editorDiv = document.createElement('div');
  editorDiv.className = 'cf-quill-editor';
  editorWrap.appendChild(editorDiv);
  bodyField.appendChild(editorWrap);
  wrap.appendChild(bodyField);

  // Initialize Quill after DOM is attached
  let _quillInstance = null;
  requestAnimationFrame(() => {
    if (typeof Quill !== 'undefined') {
      _quillInstance = new Quill(editorDiv, {
        theme: 'snow',
        placeholder: 'Page content\u2026',
        modules: {
          toolbar: [
            [{ header: [1, 2, 3, false] }],
            ['bold', 'italic', 'underline'],
            [{ list: 'ordered' }, { list: 'bullet' }],
            ['link', 'code-block'],
            ['clean'],
          ],
        },
      });
      // Pre-fill with HTML content from Claude
      if (data.body) {
        _quillInstance.root.innerHTML = data.body;
      }
    }
  });

  // Helper to get HTML from editor
  const _getBodyHtml = () => {
    if (_quillInstance) return _quillInstance.root.innerHTML;
    return '';
  };

  // Error area
  const errDiv = document.createElement('div');
  errDiv.className = 'cf-form-error';
  errDiv.style.display = 'none';
  wrap.appendChild(errDiv);

  // Buttons
  const actions = document.createElement('div');
  actions.className = 'cf-form-actions';
  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'cf-btn-secondary';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.addEventListener('click', () => {
    container.innerHTML = _gatorDetailHint('confluence');
  });
  const createBtn = document.createElement('button');
  createBtn.className = 'cf-btn-primary';
  createBtn.textContent = 'Create Page';
  createBtn.addEventListener('click', async () => {
    const sk = spaceHidden.value.trim();
    const t = titleInput.value.trim();
    if (!sk || !t) {
      errDiv.textContent = 'Space and title are required.';
      errDiv.style.display = '';
      return;
    }
    errDiv.style.display = 'none';
    createBtn.disabled = true;
    createBtn.textContent = 'Creating\u2026';
    try {
      const res = await fetch('/api/confluence/page', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          space_key: sk,
          title: t,
          body: _getBodyHtml(),
          parent_id: parentInput.value.trim(),
        }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      // Success
      _cfPostSuccessCard(d.title || t, d.url || '');
      _clearListCache('confluence');
      const listContainer = document.getElementById('cf-page-list');
      if (listContainer) _cfLoadTab('recent');
      container.innerHTML = _gatorDetailHint('confluence');
    } catch (e) {
      errDiv.textContent = e.message;
      errDiv.style.display = '';
      createBtn.disabled = false;
      createBtn.textContent = 'Create Page';
    }
  });
  actions.appendChild(cancelBtn);
  actions.appendChild(createBtn);
  wrap.appendChild(actions);

  container.appendChild(wrap);
}

/* ── Edit form ── */

function _renderConfluenceEditForm(container, data) {
  container.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'cf-form-wrap';

  const title = document.createElement('h2');
  title.className = 'cf-form-title';
  title.textContent = 'Edit Confluence Page';
  wrap.appendChild(title);

  // Version info
  if (data.version) {
    const versionInfo = document.createElement('div');
    versionInfo.className = 'cf-version-info';
    versionInfo.textContent = `Editing version ${data.version}`;
    wrap.appendChild(versionInfo);
  }

  // Title input
  const titleField = _cfField('Title', true);
  const titleInput = document.createElement('input');
  titleInput.className = 'cf-field-input';
  titleInput.type = 'text';
  titleInput.value = data.title || '';
  titleField.appendChild(titleInput);
  wrap.appendChild(titleField);

  // Body — default to a human-readable preview; toggle to edit raw source.
  const bodyField = _cfField('Body');
  const bodyToggle = document.createElement('div');
  bodyToggle.style.cssText = 'display:flex;gap:6px;margin-bottom:8px;';
  const previewBtn = document.createElement('button');
  previewBtn.type = 'button';
  previewBtn.className = 'cf-btn-secondary';
  previewBtn.textContent = 'Preview';
  const sourceBtn = document.createElement('button');
  sourceBtn.type = 'button';
  sourceBtn.className = 'cf-btn-secondary';
  sourceBtn.textContent = 'Edit source';
  bodyToggle.append(previewBtn, sourceBtn);
  bodyField.appendChild(bodyToggle);

  const previewWrap = document.createElement('div');
  previewWrap.style.minHeight = '200px';
  bodyField.appendChild(previewWrap);

  const bodyArea = document.createElement('textarea');
  bodyArea.className = 'cf-field-textarea';
  bodyArea.value = data.body || '';
  bodyArea.style.minHeight = '200px';
  bodyArea.style.display = 'none';
  bodyField.appendChild(bodyArea);
  wrap.appendChild(bodyField);

  const _setActiveToggle = (active) => {
    [previewBtn, sourceBtn].forEach(b => {
      b.style.fontWeight = b === active ? '600' : '400';
      b.style.opacity = b === active ? '1' : '.6';
    });
  };
  const showPreview = () => {
    bodyArea.style.display = 'none';
    previewWrap.style.display = '';
    previewWrap.innerHTML = '';
    const html = bodyArea.value.trim();
    if (html) {
      previewWrap.appendChild(_cfRenderBodyFrame(html));
    } else {
      previewWrap.innerHTML = '<div style="padding:1rem;color:var(--text-sub);font-size:.82rem">(Empty page)</div>';
    }
    _setActiveToggle(previewBtn);
  };
  const showSource = () => {
    previewWrap.style.display = 'none';
    bodyArea.style.display = '';
    _setActiveToggle(sourceBtn);
  };
  previewBtn.addEventListener('click', showPreview);
  sourceBtn.addEventListener('click', showSource);
  showPreview();  // default: readable rendered view, not raw markup

  // Error area
  const errDiv = document.createElement('div');
  errDiv.className = 'cf-form-error';
  errDiv.style.display = 'none';
  wrap.appendChild(errDiv);

  // Buttons
  const actions = document.createElement('div');
  actions.className = 'cf-form-actions';
  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'cf-btn-secondary';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.addEventListener('click', () => {
    if (data.page_id) {
      _renderConfluencePageDetail(container, data.page_id, '');
    } else {
      container.innerHTML = _gatorDetailHint('confluence');
    }
  });
  const saveBtn = document.createElement('button');
  saveBtn.className = 'cf-btn-primary';
  saveBtn.textContent = 'Save Changes';
  saveBtn.addEventListener('click', async () => {
    const t = titleInput.value.trim();
    if (!t) {
      errDiv.textContent = 'Title is required.';
      errDiv.style.display = '';
      return;
    }
    errDiv.style.display = 'none';
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving\u2026';
    try {
      const res = await fetch(`/api/confluence/page/${encodeURIComponent(data.page_id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: t,
          body: bodyArea.value,
          version: data.version || 0,
        }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      // Success — reload detail
      _clearListCache('confluence');
      _renderConfluencePageDetail(container, data.page_id, d.url || '');
    } catch (e) {
      errDiv.textContent = e.message;
      errDiv.style.display = '';
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Changes';
      showSource();  // surface the raw markup so the human can fix the flagged issue
    }
  });
  actions.appendChild(cancelBtn);
  actions.appendChild(saveBtn);
  wrap.appendChild(actions);

  container.appendChild(wrap);
}

/* ── SSE pane signal receivers ── */

function _confluenceReceivePaneData(action, data) {
  if (!document.getElementById('third-pane')?.classList.contains('is-open') || tpState.type !== 'confluence') {
    openThirdPane('confluence');
  }
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return;
  if (action === 'create') {
    _renderConfluenceCreateForm(detailCol, data);
  } else if (action === 'edit') {
    _renderConfluenceEditForm(detailCol, data);
  }
}

function _confluenceUpdatePageList(paneData) {
  const container = document.getElementById('cf-page-list');
  if (!container) return;
  _cfRenderPageList(container, paneData.pages || [], paneData.title || 'Search results');
}

/* ── Utility functions ── */

function _cfFilterSpaces(query) {
  const container = document.getElementById('cf-page-list');
  if (!container || !_cfState.allSpaces.length) return;
  const q = query.trim().toLowerCase();
  if (!q) {
    _cfRenderSpaceList(container, _cfState.allSpaces);
    return;
  }
  const filtered = _cfState.allSpaces.filter(s =>
    s.name.toLowerCase().includes(q) || s.key.toLowerCase().includes(q)
  );
  _cfRenderSpaceList(container, filtered);
}

function _cfRelTime(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  if (isNaN(diff)) return '';
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

function _cfEsc(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _cfSkeleton() {
  const s = `<style>@keyframes cf-shimmer{0%,100%{opacity:.4}50%{opacity:.7}}</style>`;
  return s + Array(5).fill(0).map(() => `
    <div style="padding:9px 10px;border-bottom:1px solid var(--border);display:flex;gap:8px;align-items:center;">
      <div style="width:16px;height:16px;border-radius:3px;background:var(--surface3);flex-shrink:0;animation:cf-shimmer 1.5s infinite;"></div>
      <div style="flex:1;">
        <div style="height:12px;background:var(--surface3);border-radius:4px;margin-bottom:6px;width:75%;animation:cf-shimmer 1.5s infinite;"></div>
        <div style="height:10px;background:var(--surface3);border-radius:4px;width:45%;animation:cf-shimmer 1.5s infinite;"></div>
      </div>
    </div>`).join('');
}

function _cfField(label, required) {
  const wrap = document.createElement('div');
  wrap.className = 'cf-field-wrap';
  const lbl = document.createElement('label');
  lbl.className = 'cf-field-label' + (required ? ' cf-field-required' : '');
  lbl.textContent = label;
  wrap.appendChild(lbl);
  return wrap;
}

/* ── Person card popover (for @mention clicks) ───────────────────────────── */
(function _initPersonCardStyles() {
  const s = document.createElement('style');
  s.textContent = `
    #tp-person-card {
      position: fixed; z-index: 9999;
      background: var(--surface, #1e1e2e); border: 1px solid var(--border2, #333);
      border-radius: 10px; padding: 1rem 1.1rem; min-width: 240px; max-width: 300px;
      max-height: 70vh; overflow-y: auto;
      box-shadow: 0 8px 32px rgba(0,0,0,.45); color: var(--text, #e0e0e0);
      font-size: .85rem; line-height: 1.5;
      scrollbar-width: thin; scrollbar-color: var(--border2, #475569) transparent;
    }
    #tp-person-card::-webkit-scrollbar { width: 4px; }
    #tp-person-card::-webkit-scrollbar-track { background: transparent; }
    #tp-person-card::-webkit-scrollbar-thumb { background: var(--border2, #475569); border-radius: 4px; }
    #tp-person-card .pc-name { font-weight: 600; font-size: 1rem; margin-bottom: .15rem; }
    #tp-person-card .pc-title { color: var(--text-sub, #999); font-size: .8rem; margin-bottom: .6rem; }
    #tp-person-card .pc-row { display: flex; gap: .4rem; align-items: baseline; margin-bottom: .2rem; }
    #tp-person-card .pc-label { color: var(--text-sub, #999); font-size: .75rem; min-width: 60px; }
    #tp-person-card .pc-val a { color: var(--accent, #60a5fa); text-decoration: none; }
    #tp-person-card .pc-mgr { margin-top: .6rem; padding-top: .6rem; border-top: 1px solid var(--border2, #333); font-size: .8rem; color: var(--text-sub, #999); }
    #tp-person-card .pc-mgr strong { color: var(--text, #e0e0e0); }
    #tp-person-card .pc-close { position: absolute; top: .5rem; right: .6rem; cursor: pointer; opacity: .5; font-size: .85rem; }
    #tp-person-card .pc-close:hover { opacity: 1; }
    #tp-person-card .pc-actions { margin-top: .8rem; padding-top: .7rem; border-top: 1px solid var(--border2, #333); display: flex; gap: .5rem; }
    #tp-person-card .pc-action-btn { flex: 1; padding: .35rem .6rem; border-radius: 6px; border: 1px solid var(--border2, #444); background: var(--surface2, #2a2a3e); color: var(--accent, #60a5fa); font-size: .78rem; cursor: pointer; text-align: center; }
    #tp-person-card .pc-action-btn:hover { background: var(--accent, #60a5fa); color: #fff; border-color: var(--accent, #60a5fa); }
  `;
  document.head.appendChild(s);
})();

const _personCardCache = {};

async function _showPersonCard(aadId, anchorEl) {
  // Remove any existing card
  document.getElementById('tp-person-card')?.remove();

  const card = document.createElement('div');
  card.id = 'tp-person-card';
  card.innerHTML = '<div style="opacity:.5;font-size:.8rem">Loading\u2026</div>';
  document.body.appendChild(card);

  // Position using shared Floating UI wrapper \u2014 handles all viewport edges automatically
  let _cardCleanup = _fpopup(card, anchorEl, { placement: 'bottom-start', offsetY: 6, padding: 8 });

  // Close on outside click — also cleans up Floating UI autoUpdate
  const _dismiss = e => {
    if (!card.contains(e.target)) {
      _cardCleanup?.();
      card.remove();
      document.removeEventListener('click', _dismiss, true);
    }
  };
  setTimeout(() => document.addEventListener('click', _dismiss, true), 0);

  // Fetch (cached)
  let person = _personCardCache[aadId];
  if (!person) {
    try {
      const resp = await fetch(`/api/people/card/${encodeURIComponent(aadId)}`);
      person = await resp.json();
      if (resp.ok) _personCardCache[aadId] = person;
    } catch (e) {
      card.innerHTML = '<div style="color:var(--danger,#f87171)">Failed to load profile</div>';
      return;
    }
  }

  const esc = s => escapeHtml(s || '');
  const emailLink = person.email ? `<a href="mailto:${esc(person.email)}">${esc(person.email)}</a>` : '—';

  const mgrId = person.manager?.id || '';
  let mgrHtml = '';
  if (person.manager?.name) {
    const mgrStyle = mgrId ? ' style="cursor:pointer;color:var(--accent,#60a5fa)"' : '';
    mgrHtml = `<div class="pc-mgr">Reports to: <strong class="pc-mgr-name"${mgrStyle}>${esc(person.manager.name)}</strong>${person.manager.title ? ` · ${esc(person.manager.title)}` : ''}</div>`;
  }

  const actionsHtml = person.email ? `<div class="pc-actions"><button class="pc-action-btn pc-open-chat">💬 Open chat</button></div>` : '';

  card.innerHTML = `
    <span class="pc-close" title="Close">✕</span>
    <div class="pc-name">${esc(person.name)}</div>
    <div class="pc-title">${esc(person.title) || '&nbsp;'}</div>
    ${person.department ? `<div class="pc-row"><span class="pc-label">Dept</span><span class="pc-val">${esc(person.department)}</span></div>` : ''}
    ${person.office ? `<div class="pc-row"><span class="pc-label">Office</span><span class="pc-val">${esc(person.office)}</span></div>` : ''}
    <div class="pc-row"><span class="pc-label">Email</span><span class="pc-val">${emailLink}</span></div>
    ${person.phone ? `<div class="pc-row"><span class="pc-label">Phone</span><span class="pc-val">${esc(person.phone)}</span></div>` : ''}
    ${mgrHtml}
    ${actionsHtml}
  `;
  card.querySelector('.pc-close').addEventListener('click', () => {
    _cardCleanup?.();
    card.remove();
  });

  card.querySelector('.pc-open-chat')?.addEventListener('click', () => {
    _cardCleanup?.();
    card.remove();
    const email = person.email;
    if (!email) return;
    // Try to find an existing DM in our loaded chat list
    const existingChatId = typeof _resolveTeamsChatId === 'function'
      ? _resolveTeamsChatId([email]) : '';
    if (existingChatId) {
      tpState.selectedId = existingChatId;
      if (typeof _loadTeamsThread === 'function') _loadTeamsThread(existingChatId);
    } else if (typeof _showNewTeamsCompose === 'function') {
      // No existing DM — open new compose; recipient will need to be typed
      _showNewTeamsCompose();
    }
  });
  // Manager name click — use card's own DOM node as anchor so _fpopup can measure it correctly.
  // The old onclick="...this..." approach passed a detached node (card was removed before
  // the new card was positioned), causing _fpopup to get a zero rect → top-left placement.
  if (mgrId) {
    card.querySelector('.pc-mgr-name')?.addEventListener('click', e => {
      e.stopPropagation();
      _showPersonCard(mgrId, e.currentTarget);
    });
  }
}

function _cfPostSuccessCard(title, url) {
  const output = document.getElementById('messages');
  if (!output) return;
  const card = document.createElement('div');
  card.className = 'cf-success-card';
  card.innerHTML = `<span class="cf-success-check">\u2713</span><span>Page created: <a href="${_cfEsc(url)}" target="_blank"><strong>${_cfEsc(title)}</strong></a></span>`;
  output.appendChild(card);
  output.scrollTop = output.scrollHeight;
}
