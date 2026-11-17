// tp-code-agent.js — Code tab for AI Gator Coding Agent
// All Code tab logic is isolated here — nothing added to third-pane.js internals.

// ── State ──────────────────────────────────────────────────────────────────────
let _caProjects = []; // [{name, repo_path, source}]
let _caActiveProject = null; // active project name string (global to this browser tab)
let _caLeftView = 'history'; // 'history' | 'scm' | 'explorer' — which view the left pane shows
let _caOpenDiffFile = null; // repo-relative path of the file currently open in the right pane (if a Changes diff), else null

// ── Session scoping ───────────────────────────────────────────────────────────
// When true (default), the coding-agent terminal session is SHARED across all
// Gator chat tabs — one terminal for the whole app, like Teams/Outlook. Users
// treat the coding agent as an app, not a per-conversation resource; the
// terminal's own tab strip provides multi-session parallelism. Set false to
// restore the prior per-Gator-tab model (one terminal per chat tab).
//
// Implementation: _caSessionKey() maps a Gator tabId to the key used in the
// terminal state maps (_genAgentTerminals). Shared mode returns
// a constant '_shared' key so every tab looks up the SAME state; per-tab mode
// returns the tabId itself (the original behavior). All tabId-keyed session
// access in tp-opencode-terminal.js / tp-generic-agent-terminal.js routes
// through this function — flipping the flag is the only change needed.
const SHARED_CODE_SESSION = true;
function _caSessionKey(tabId) {
  return SHARED_CODE_SESSION ? '_shared' : String(tabId);
}

// ── Agent dispatch (generic BYO-config agents) ──────────────────────────────
// Small routing layer so call sites don't need to know which terminal
// implementation backs a given project - defaults to "opencode-bare" for any
// project without an explicit agent set.
function _caProjectAgent(project) {
  return (project && project.agent) || 'opencode-bare';
}

function _caMountAgentTab(tabId, project) {
  // The generic-agent terminal mounts its session tab strip in the shared
  // #tp-detail-header. Clear any stale strip first so switching agents never
  // leaves a stranded strip from the previous agent.
  if (typeof _ocRemoveHeaderTabStrip === 'function') _ocRemoveHeaderTabStrip();
  if (typeof _genAgentMountActiveTab === 'function') _genAgentMountActiveTab(tabId);
}

function _caShowAgentStartOrTerminal(tabId, project, repoPath) {
  const agent = _caProjectAgent(project);
  if (typeof _genAgentShowStartOrTerminal === 'function') {
    _genAgentShowStartOrTerminal(tabId, agent, project.name, repoPath);
  }
}

// ── CSRF helper ────────────────────────────────────────────────────────────────
function _caHeaders() {
  return { 'Content-Type': 'application/json', 'X-CSRF-Token': window.__CSRF_TOKEN__ || '' };
}

async function _caHeadersAsync() {
  // If the token is missing (e.g. pane opened before page fully bootstrapped),
  // fetch a fresh one from /api/csrf before building the request headers.
  if (!window.__CSRF_TOKEN__) {
    try {
      const d = await fetch('/api/csrf').then((r) => (r.ok ? r.json() : null));
      if (d?.csrf_token) window.__CSRF_TOKEN__ = d.csrf_token;
    } catch (_) {}
  }
  return { 'Content-Type': 'application/json', 'X-CSRF-Token': window.__CSRF_TOKEN__ || '' };
}

// Wraps a CSRF-protected fetch: the in-memory token regenerates every server
// restart (security.py), so a token fetched earlier in this page's lifetime
// can go stale mid-session (e.g. a watchdog/dev-server restart) and every
// subsequent POST would 403 with "CSRF token missing or invalid" until the
// user manually hard-refreshes. On a 403, re-fetch /api/csrf and retry the
// same request once with the fresh token before giving up.
async function _caFetchWithCsrfRetry(url, opts) {
  let resp = await fetch(url, opts);
  if (resp.status === 403) {
    try {
      const d = await fetch('/api/csrf').then((r) => (r.ok ? r.json() : null));
      if (d?.csrf_token) {
        window.__CSRF_TOKEN__ = d.csrf_token;
        resp = await fetch(url, {
          ...opts,
          headers: { ...opts.headers, 'X-CSRF-Token': d.csrf_token },
        });
      }
    } catch (_) {}
  }
  return resp;
}

// ── Entry point ────────────────────────────────────────────────────────────────
function _initCodeAgentPane() {
  // Use the left column for git source control. Real gap found via user
  // report: this used to pin a fixed inline width and hide #tp-list-resize
  // entirely, so unlike every other third-pane skill (Teams, Email, etc.)
  // the source-control panel couldn't be resized at all. #tp-left-col's own
  // base CSS rule already sizes off `var(--third-pane-list-w)` - the exact
  // variable #tp-list-resize's existing drag logic (initThirdPaneResize)
  // already manipulates - so leaving both alone and just not fighting them
  // with inline overrides is enough to make this resizable for free.
  const leftCol = document.getElementById('tp-left-col') || document.getElementById('tp-list-col');
  if (leftCol) {
    leftCol.style.display = '';
    // Render source control panel into the left column
    leftCol.innerHTML = _caSourceControlPanel();
    if (_caLeftView !== 'history') _caSetLeftView(_caLeftView);
  }
  const rightCol = document.getElementById('tp-right-col');
  if (rightCol) {
    rightCol.classList.remove('tp-cal-full');
  }

  // Populate the topbar with Code-tab controls (project chip, refresh, theme,
  // Hide Gator). The terminal theme follows the app theme (ThemeManager).
  _caPopulateTopbar();
  _caInstallBodyObserver();
  _caApplyTerminalTheme();

  // If projects already loaded (e.g. by URL param handler), skip the fetch
  const _doRender = () => {
    _caRenderPane();
    _caRenderProjectSwitcher(_caActiveProject, _caProjects);
    _caRefreshSourceControl();
    _caStartSourceControlPolling();
    if (_caActiveProject) _caSetLeftView(_caStoredLeftView(_caActiveProject));
    // Re-attach any already-live terminal into the freshly-rebuilt DOM BEFORE
    // deciding whether to show Start/Resume. This path runs on a full return
    // from another skill (Teams/Email), which tears down and rebuilds
    // #tp-detail-col - without re-mounting first, _genAgentIsTerminalMounted always
    // sees a stale/detached element and always falls through to the Resume
    // prompt, even for a session that's still perfectly alive in memory. Real
    // bug found via user report: Resume showed on every single return trip.
    if (typeof _activeTabId !== 'undefined' && _caActiveProject) {
      const _mountProj = _caProjects.find((p) => p.name === _caActiveProject);
      if (_mountProj) _caMountAgentTab(_activeTabId, _mountProj);
    }
    // Guided start: show the Start/Resume prompt for the active project (never
    // auto-spawn — that raced the cold start → blank terminal). EXCEPTION: a
    // task handoff (landed via ?open_project=) is already an explicit user
    // action elsewhere, so auto-start it so the seeded/running session surfaces.
    // Handoff auto-start is OpenCode-only for now - non-OpenCode agents have
    // no equivalent "seed a task into the session" concept to land on, so
    // they always land on the guided prompt like any other visit.
    if (_caActiveProject && typeof _activeTabId !== 'undefined') {
      const _proj = _caProjects.find((p) => p.name === _caActiveProject);
      if (_proj && _proj.repo_path) {
        _caShowAgentStartOrTerminal(_activeTabId, _proj, _proj.repo_path);
      }
    }
  };

  if (_caProjects.length > 0) {
    _doRender();
  } else {
    _caLoadProjects().then(_doRender);
  }
}

// ── Source Control Panel (left column) ────────────────────────────────────────
const _CA_TAB_ICON_FILES =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
const _CA_TAB_ICON_CHANGES =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="8" r="2.5"/><path d="M6 8.5v7"/><path d="M18 10.5c0 4-5 4-9 5"/></svg>';
const _CA_TAB_ICON_HISTORY =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>';

function _caSourceControlPanel() {
  return `
    <div class="ca-sc-panel">
      <div class="ca-sc-viewtabs">
        <button class="ca-sc-viewtab active" id="ca-viewtab-history" aria-pressed="true" title="History" aria-label="History"${gatorActionAttrs('_caSetLeftView', ['history'])}>${_CA_TAB_ICON_HISTORY}</button>
        <button class="ca-sc-viewtab" id="ca-viewtab-scm" aria-pressed="false" title="Changes" aria-label="Changes"${gatorActionAttrs('_caSetLeftView', ['scm'])}>${_CA_TAB_ICON_CHANGES}</button>
        <button class="ca-sc-viewtab" id="ca-viewtab-explorer" aria-pressed="false" title="Files" aria-label="Files"${gatorActionAttrs('_caSetLeftView', ['explorer'])}>${_CA_TAB_ICON_FILES}</button>
      </div>
      <div id="ca-scm-view" class="ca-scm-view" style="display:none">
        <div class="ca-sc-section-wrapper">
          <div class="ca-sc-section-label" id="ca-sc-files-label" style="display:none">CHANGES</div>
          <div id="ca-sc-files" class="ca-sc-scroll-region ca-sc-files-scroll">
            <div class="ca-sc-loading"></div>
          </div>
        </div>
        <div class="ca-sc-section-wrapper">
          <div class="ca-sc-section-label" id="ca-sc-commits-label" style="display:none"></div>
          <div id="ca-sc-commits" class="ca-sc-scroll-region ca-sc-commits-scroll" style="display:none"></div>
        </div>
      </div>
      <div id="ca-fe-view" class="ca-sc-section-wrapper" style="display:none">
        <div id="ca-fe-root" class="ca-sc-scroll-region ca-fe-scroll">
          <div class="ca-sc-loading"></div>
        </div>
      </div>
      <div id="ca-hist-view" class="ca-hist-view">
        <div class="ah-search">
          <input
            id="ca-hist-search"
            type="search"
            placeholder="Search this project's sessions"
            aria-label="Search this project's sessions"
            autocomplete="off"
          />
        </div>
        <div id="ca-hist-list" class="ah-list"></div>
      </div>
    </div>`;
}

// ── Left pane view toggle (History / Changes / Files) ───────────────────────
const _CA_LEFT_VIEWS = ['history', 'scm', 'explorer'];
const _CA_LEFT_VIEW_KEY = 'gator.codeagent.leftview.';

function _caStoredLeftView(project) {
  try {
    const v = localStorage.getItem(_CA_LEFT_VIEW_KEY + project);
    if (_CA_LEFT_VIEWS.includes(v)) return v;
  } catch (_) {}
  return 'history';
}

function _caSetLeftView(view) {
  const panes = { history: 'ca-hist-view', scm: 'ca-scm-view', explorer: 'ca-fe-view' };
  if (!panes[view]) view = 'history';
  if (!Object.values(panes).every((id) => document.getElementById(id))) return;
  _caLeftView = view;
  if (_caActiveProject) {
    try {
      localStorage.setItem(_CA_LEFT_VIEW_KEY + _caActiveProject, view);
    } catch (_) {}
  }
  Object.entries(panes).forEach(([name, id]) => {
    document.getElementById(id).style.display = name === view ? '' : 'none';
    const tab = document.getElementById('ca-viewtab-' + name);
    tab?.classList.toggle('active', name === view);
    tab?.setAttribute('aria-pressed', String(name === view));
  });
  if (view === 'explorer') _caLoadFileTree('', document.getElementById('ca-fe-root'), 0);
  if (view === 'history' && window.agentHistory) agentHistory.show();
}

function _caLeftViewRefresh() {
  if (_caLeftView === 'explorer') {
    _caLoadFileTree('', document.getElementById('ca-fe-root'), 0);
  } else if (_caLeftView === 'history') {
    if (window.agentHistory) agentHistory.refresh();
  } else {
    _caRefreshSourceControl(true);
  }
}

// ── Source control cache (session-scoped, keyed by project name) ────────────
// Real redundancy found via user report: every Code-tab-open or
// project-reselect re-fetched git status/log from scratch even when nothing
// had changed since the last fetch. Git state here only ever changes from
// INSIDE the OpenCode terminal (this panel has no commit/stage actions of
// its own) - Gator has no way to know when to invalidate automatically, so
// caching for the browser session and relying on the existing refresh
// button as the manual escape hatch is the simplest correct fix.
const _caGitCache = {}; // project name -> {status, log, sig}

// Cheap signature of everything _caRenderSourceControl actually draws - lets
// the background poller below skip re-rendering (and thus flickering) when a
// fetch comes back identical to what's already on screen.
function _caGitSig(status, log) {
  const staged = (status?.staged || []).map((f) => `S:${f.status}:${f.file}`);
  const unstaged = (status?.unstaged || []).map((f) => `U:${f.status}:${f.file}`);
  const untracked = (status?.untracked || []).map((f) => `?:${f.status}:${f.file}`);
  const filesSig = [...staged, ...unstaged, ...untracked].join('|');
  const commitsSig = (log?.commits || [])
    .map(
      (c) =>
        `${c.hash}:${c.is_head ? 1 : 0}:${(c.local_refs || []).join(',')}:${(c.remote_refs || []).join(',')}:${(c.tags || []).join(',')}`,
    )
    .join('|');
  return `${filesSig}::${log?.branch || ''}:${log?.ahead || 0}:${log?.behind || 0}::${commitsSig}`;
}

function _caRefreshSourceControl(force) {
  if (!_caActiveProject) return;
  const cached = _caGitCache[_caActiveProject];
  if (cached && !force) {
    _caRenderSourceControl(cached.status, cached.log);
    return;
  }

  const filesEl = document.getElementById('ca-sc-files');
  const commitsEl = document.getElementById('ca-sc-commits');
  if (filesEl) filesEl.innerHTML = '<div class="ca-sc-loading"></div>';
  if (commitsEl) {
    commitsEl.innerHTML = '';
    commitsEl.style.display = 'none';
  }
  const _project = _caActiveProject;
  Promise.all([
    fetch(`/api/code_agent/git/status?project_name=${encodeURIComponent(_project)}`).then((r) =>
      r.ok ? r.json() : null,
    ),
    fetch(`/api/code_agent/git/log?project_name=${encodeURIComponent(_project)}`).then((r) =>
      r.ok ? r.json() : null,
    ),
  ])
    .then(([status, log]) => {
      _caGitCache[_project] = { status, log, sig: _caGitSig(status, log) };
      // The user may have switched to a different project while this was in
      // flight - still cache the result for later, but don't render stale
      // data over whatever's now showing.
      if (_project === _caActiveProject) _caRenderSourceControl(status, log);
    })
    .catch(() => {
      if (_project === _caActiveProject && filesEl)
        filesEl.innerHTML = '<div class="ca-sc-empty">Could not load git status</div>';
    });
}

// ── Background auto-refresh (silent - no loading spinner, no re-render
// unless something actually changed) ────────────────────────────────────────
// Real gap found via user report: the left pane only ever refreshed on
// project switch or the manual ↻ button, so file changes OpenCode itself made
// in the terminal (edits, commits) went stale until the user remembered to
// hit refresh. Follows the exact same "poll, diff a signature, only re-render
// on change" pattern as Teams' _startChatListPolling - re-rendering every
// poll tick is what caused a visible flicker there.
//
// Self-rescheduling (setTimeout AFTER each cycle settles), NOT setInterval.
// Real bug this caused: setInterval fires every 15s no matter what, so once
// git/status started taking >15s (during a server-side thread-pool stall) the
// timer kept firing FRESH requests on top of the stuck ones - unbounded
// pile-up that poured fuel on the very stall it was waiting out. Chaining the
// next poll off the previous one's completion makes overlap structurally
// impossible: there is never more than one poll in flight.
const _SC_POLL_INTERVAL_MS = 15000;
let _caScPollTimer = null;
let _caScPollGen = 0; // bumped on stop, so an in-flight cycle won't reschedule

function _caStartSourceControlPolling() {
  _caStopSourceControlPolling();
  const gen = ++_caScPollGen;

  const scheduleNext = () => {
    // Don't reschedule if polling was stopped/restarted while we were away.
    if (gen !== _caScPollGen) return;
    _caScPollTimer = setTimeout(runCycle, _SC_POLL_INTERVAL_MS);
  };

  const runCycle = () => {
    if (gen !== _caScPollGen) return;
    if (typeof tpState === 'undefined' || tpState.type !== 'code_agent' || !_caActiveProject) {
      _caStopSourceControlPolling();
      return;
    }
    const _project = _caActiveProject;
    Promise.all([
      fetch(`/api/code_agent/git/status?project_name=${encodeURIComponent(_project)}`).then((r) =>
        r.ok ? r.json() : null,
      ),
      fetch(`/api/code_agent/git/log?project_name=${encodeURIComponent(_project)}`).then((r) =>
        r.ok ? r.json() : null,
      ),
    ])
      .then(([status, log]) => {
        if (_project !== _caActiveProject) return; // switched away while in flight
        const newSig = _caGitSig(status, log);
        const cached = _caGitCache[_project];
        if (cached && cached.sig === newSig) return; // nothing changed - skip render, no flicker
        _caGitCache[_project] = { status, log, sig: newSig };
        _caRenderSourceControl(status, log);
      })
      .catch(() => {})
      // Only arm the next cycle once THIS one has fully settled - the guard
      // against pile-up. A slow/stuck git/status just delays the next poll;
      // it can never stack a second one on top.
      .finally(scheduleNext);
  };

  scheduleNext();
}

function _caStopSourceControlPolling() {
  _caScPollGen++; // invalidate any in-flight cycle's pending reschedule
  if (_caScPollTimer) {
    clearTimeout(_caScPollTimer);
    _caScPollTimer = null;
  }
}

function _caRenderSourceControl(status, log) {
  const filesEl = document.getElementById('ca-sc-files');
  const commitsEl = document.getElementById('ca-sc-commits');
  if (!filesEl) return;

  // ── Changes section ──
  const allChanged = [
    ...(status?.staged || []).map((f) => ({ ...f, area: 'staged' })),
    ...(status?.unstaged || []).map((f) => ({ ...f, area: 'unstaged' })),
    ...(status?.untracked || []).map((f) => ({ ...f, area: 'untracked' })),
  ];
  const filesLabel = document.getElementById('ca-sc-files-label');
  if (allChanged.length) {
    if (filesLabel) {
      filesLabel.textContent = `CHANGES (${allChanged.length})`;
      filesLabel.style.display = '';
    }
    const _statusInfo = {
      M: { label: 'M', cls: 'M', title: 'Modified — file has unsaved changes' },
      A: { label: 'A', cls: 'A', title: 'Added — new file staged for commit' },
      D: { label: 'D', cls: 'D', title: 'Deleted — file has been removed' },
      R: { label: 'R', cls: 'R', title: 'Renamed — file has been renamed' },
      '?': { label: 'U', cls: 'U', title: 'Untracked — new file not yet in git' },
    };
    filesEl.innerHTML = allChanged
      .map((f) => {
        const si = _statusInfo[f.status] || { label: f.status, cls: 'U', title: f.status };
        const fname = f.file.split(/[/\\]/).pop();
        const isStaged = f.area === 'staged';
        return `<div class="ca-sc-file"${gatorActionAttrs('_caShowFileDiff', [f.file, !!isStaged])} title="${_caEsc(f.file)}">
        <span class="ca-sc-file-name">${_caEsc(fname)}</span>
        <button class="ca-sc-file-discard"${gatorActionAttrs('_caDiscardFile', [f.file, f.status], { stop: true })} title="${f.status === '?' ? 'Delete file' : 'Discard changes'}">🗑️</button>
        <span class="ca-sc-file-status ca-status-${si.cls}" title="${si.title}">${si.label}</span>
      </div>`;
      })
      .join('');
  } else {
    if (filesLabel) {
      filesLabel.textContent = 'CHANGES';
      filesLabel.style.display = '';
    }
    filesEl.innerHTML = `<div class="ca-sc-empty">No changes</div>`;
  }

  // ── Commits section ──
  const commitsLabel = document.getElementById('ca-sc-commits-label');
  if (log) {
    // Cache branch name so _caRenderRefBadges can highlight the active branch
    window._caCurrentBranch = log.branch || '';
    // Header: branch name + ahead/behind indicator
    const aheadHtml = log.ahead
      ? `<span class="ca-sc-sync-local" title="${log.ahead} unpushed commit${log.ahead !== 1 ? 's' : ''}">↑${log.ahead}</span>`
      : '';
    const behindHtml = log.behind
      ? `<span class="ca-sc-sync-remote" title="${log.behind} unpulled commit${log.behind !== 1 ? 's' : ''}">↓${log.behind}</span>`
      : '';
    const syncBadge =
      log.ahead || log.behind ? ` <span class="ca-sc-sync">${aheadHtml}${behindHtml}</span>` : '';
    if (commitsLabel) {
      commitsLabel.innerHTML = _caEsc(log.branch || 'main') + syncBadge;
      commitsLabel.style.display = '';
    }
    if (commitsEl) {
      commitsEl.style.display = '';
      commitsEl.innerHTML = (log.commits || [])
        .map((c) => {
          // Convert the endpoint's structured format to [{name, type}] for the renderer
          const _refs = [];
          if (c.is_head) _refs.push({ name: 'HEAD', type: 'head' });
          (c.local_refs || []).forEach((n) => _refs.push({ name: n, type: 'local' }));
          (c.remote_refs || []).forEach((n) => _refs.push({ name: n, type: 'remote' }));
          (c.tags || []).forEach((n) => _refs.push({ name: n, type: 'tag' }));
          const badges = _caRenderRefBadges(_refs);
          const metaTitle = `${_caEsc(c.hash)}  ·  ${_caEsc(c.when)}\n${_caEsc(c.message)}`;
          return `
        <div class="ca-sc-commit${c.is_head ? ' ca-sc-commit--head' : ''}" title="${metaTitle}">
          <span class="ca-sc-commit-graph"><span class="ca-sc-graph-dot"></span></span>
          <span class="ca-sc-commit-body">
            <span class="ca-sc-commit-msg">${_caEsc(c.message)}</span>
          </span>
          ${badges ? `<span class="ca-sc-commit-refs">${badges}</span>` : ''}
          <span class="ca-sc-commit-meta">${_caEsc(c.hash)}&ensp;·&ensp;${_caEsc(c.when)}</span>
        </div>`;
        })
        .join('');
    }
  }
}

// ── Ref badge pill renderer ──────────────────────────────────────────────────
// Turns a commit's refs array [{name, type}] into compact icon-only pill badges.
// All text (branch name / ref name) is surfaced only as a tooltip on hover.
//   type="head"   → solid amber pill  ◉  tooltip: "HEAD"
//   type="local"  → solid green/blue pill  ⎇  tooltip: branch name
//   type="remote" → outlined muted pill  ☁  tooltip: full ref name
//   type="tag"    → solid amber/orange pill  🏷  tooltip: tag name
// Real SVG icons (not unicode/emoji glyphs) for the badges that rendered
// inconsistently - a font's own glyph geometry for ◉/⎇/☁ isn't guaranteed
// (◉ drew as an ellipse rather than a true circle, ⎇ sat small and
// off-center in its own glyph box, and ☁ rendered as a full-color emoji at a
// different intrinsic size than the plain-text glyphs next to it). Explicit
// SVG geometry puts size/centering/shape under our control instead of the
// platform font's.
const _CA_REF_ICON_HEAD =
  '<svg width="9" height="9" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="currentColor"/></svg>';
const _CA_REF_ICON_BRANCH =
  '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>';
// Rounder, more recognizable cloud silhouette (filled, not a thin stroke
// outline - reads more clearly as "cloud" at this size than a single 2px path).
const _CA_REF_ICON_CLOUD =
  '<svg width="12" height="9" viewBox="0 0 24 18" fill="currentColor"><path d="M6 16a5 5 0 0 1-.4-9.98 6 6 0 0 1 11.2-2A5.5 5.5 0 0 1 18.5 16H6z"/></svg>';

function _caRenderRefBadges(refs) {
  if (!refs || !refs.length) return '';
  return refs
    .map((r) => {
      switch (r.type) {
        case 'head':
          return `<span class="ca-ref-badge ca-ref-head" title="HEAD">${_CA_REF_ICON_HEAD}</span>`;
        case 'local': {
          // Highlight the active branch (matches server-returned branch name)
          const isActive = r.name === (window._caCurrentBranch || '');
          return `<span class="ca-ref-badge ca-ref-local${isActive ? ' ca-ref-local--active' : ''}" title="${_caEsc(r.name)}">${_CA_REF_ICON_BRANCH}</span>`;
        }
        case 'remote':
          return `<span class="ca-ref-badge ca-ref-remote" title="${_caEsc(r.name)}">${_CA_REF_ICON_CLOUD}</span>`;
        case 'tag':
          return `<span class="ca-ref-badge ca-ref-tag" title="${_caEsc(r.name)}">🏷</span>`;
        default:
          return '';
      }
    })
    .join('');
}

function _caRenderUnifiedDiff(container, diffText) {
  if (!diffText || !diffText.trim()) {
    container.innerHTML = '<div class="ca-sc-empty">No changes</div>';
    return;
  }
  let oldLn = 0,
    newLn = 0;
  const gutter = (o, n) =>
    `<span class="ca-diff-gutter">${o}</span><span class="ca-diff-gutter">${n}</span>`;
  const rows = diffText
    .split('\n')
    .map((line) => {
      let cls = 'ca-diff-ctx';
      let g = gutter('', '');
      if (
        line.startsWith('+++') ||
        line.startsWith('---') ||
        line.startsWith('diff ') ||
        line.startsWith('index ')
      ) {
        cls = 'ca-diff-meta';
      } else if (line.startsWith('@@')) {
        cls = 'ca-diff-hunk';
        const m = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
        if (m) {
          oldLn = parseInt(m[1], 10);
          newLn = parseInt(m[2], 10);
        }
      } else if (line.startsWith('+')) {
        cls = 'ca-diff-add';
        g = gutter('', newLn);
        newLn++;
      } else if (line.startsWith('-')) {
        cls = 'ca-diff-del';
        g = gutter(oldLn, '');
        oldLn++;
      } else {
        g = gutter(oldLn, newLn);
        oldLn++;
        newLn++;
      }
      return `<div class="ca-diff-line ${cls}">${g}<span class="ca-diff-code">${_caEsc(line) || '&nbsp;'}</span></div>`;
    })
    .join('');
  container.innerHTML = `<div class="ca-diff-view">${rows}</div>`;
}

function _caShowFileDiff(file, staged) {
  if (!_caActiveProject) return;
  // Show Monaco diff for this file in the right detail column
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return;

  _caOpenDiffFile = file;

  // Highlight selected file
  document
    .querySelectorAll('.ca-sc-file')
    .forEach((el) => el.classList.remove('ca-sc-file--active'));
  const clicked = [...document.querySelectorAll('.ca-sc-file')].find((el) => el.title === file);
  if (clicked) clicked.classList.add('ca-sc-file--active');

  // Hide (don't destroy) an active terminal for this tab so the diff doesn't
  // render squished alongside it - #tp-detail-col is a flex column, so two
  // visible flex:1 children would share space rather than one covering the
  // other.
  if (typeof _activeTabId !== 'undefined' && typeof _genAgentHideTerminal === 'function') {
    _genAgentHideTerminal(_activeTabId);
  }

  // Show diff container
  const diffId = 'ca-file-diff-view';
  let diffEl = document.getElementById(diffId);
  if (!diffEl) {
    // Insert above the existing pane content
    diffEl = document.createElement('div');
    diffEl.id = diffId;
    diffEl.className = 'ca-file-diff-view';
    detailCol.prepend(diffEl);
  }
  diffEl.innerHTML = `<div id="ca-file-diff-monaco" class="ca-monaco-container"></div>`;
  _caMountFileHeaderChip(file, diffId);

  fetch(
    `/api/code_agent/git/diff?project_name=${encodeURIComponent(_caActiveProject)}&file=${encodeURIComponent(file)}&staged=${staged}`,
  )
    .then((r) => r.json())
    .then((data) => {
      const container = document.getElementById('ca-file-diff-monaco');
      if (container) _caRenderUnifiedDiff(container, data.diff || '');
    })
    .catch(() => {
      const container = document.getElementById('ca-file-diff-monaco');
      if (container) container.innerHTML = '<div class="ca-sc-empty">Could not load diff</div>';
    });
}

function _caCloseFileDiff(diffId) {
  document.getElementById(diffId)?.remove();
  _caRemoveFileHeaderChip();
  _caOpenDiffFile = null;
  document
    .querySelectorAll('.ca-sc-file')
    .forEach((el) => el.classList.remove('ca-sc-file--active'));
  // Restore whichever terminal was hidden for this tab, if any.
  if (typeof _activeTabId !== 'undefined' && typeof _genAgentShowTerminal === 'function') {
    _genAgentShowTerminal(_activeTabId);
  }
}

// ── File header chip ─────────────────────────────────────────────────────────
// Shows which file is open (+ a close ✕) in the persistent #tp-detail-header
// toolbar, right next to the session tab strip - not as a second row inside
// the content column. Previously the diff/content view prepended its own
// `.ca-file-diff-header` bar with its own close button directly under the
// toolbar, so two stacked rows each offered a way to "close something" and
// it wasn't obvious which one did what (user report). One ribbon, one place
// to look.
function _caFileChipId() {
  return 'ca-file-chip';
}

function _caMountFileHeaderChip(file, diffId) {
  const hdr = document.getElementById('tp-detail-header');
  if (!hdr) return;
  _caRemoveFileHeaderChip();
  const chip = document.createElement('div');
  chip.id = _caFileChipId();
  chip.className = 'ca-file-chip';
  chip.title = file;
  const name = document.createElement('span');
  name.className = 'ca-file-chip-name';
  name.textContent = file.split(/[/\\]/).pop();
  chip.appendChild(name);
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'ca-file-chip-close';
  close.title = 'Close file';
  close.setAttribute('aria-label', 'Close file');
  close.textContent = '✕';
  close.addEventListener('click', () => _caCloseFileDiff(diffId));
  chip.appendChild(close);
  // Leftmost slot (the "title" position every other tpBuildDetailToolbar app
  // uses for what's currently in the content pane) - not sandwiched between
  // the tab strip and the spacer, which drifted position depending on tab
  // count/window width and read as a stray, oddly-placed element (user report).
  hdr.insertBefore(chip, hdr.firstChild);
  // The file, not any session, is what's actually on screen right now - mute
  // the tab strip's "active" highlight so it doesn't lie about that.
  _caSetTabStripDimmed(true);
}

function _caRemoveFileHeaderChip() {
  document.getElementById(_caFileChipId())?.remove();
  _caSetTabStripDimmed(false);
}

function _caSetTabStripDimmed(dimmed) {
  const strip =
    document.getElementById('oc-header-tabstrip') || document.getElementById('ga-header-tabstrip');
  if (strip) strip.classList.toggle('ca-tabs-dimmed', dimmed);
}

// Closes any open file diff/content overlay - call before switching which
// terminal session is shown (tab click, "+" new session). Real bug found via
// user report: the file view sits on top of the terminal (`_genAgentHideTerminal`
// hides the whole terminal container, not just the active session), so
// clicking a different session tab switched the session underneath but the
// overlay stayed up - invisible to the user - while the tab strip's own
// "active" class still updated, making it look like the click landed on the
// wrong tab. Closing the overlay first means every session switch is visible.
function _caCloseFileDiffIfOpen() {
  if (_caOpenDiffFile) _caCloseFileDiff('ca-file-diff-view');
}

// ── Discard changes ───────────────────────────────────────────────────────────
function _caDiscardFile(file, status) {
  if (!_caActiveProject) return;
  const fname = file.split(/[/\\]/).pop();
  const isNew = status === '?' || status === 'A';
  _showConfirmModal(
    isNew ? 'Delete file' : 'Discard changes',
    isNew
      ? `Delete <strong>${_caEsc(fname)}</strong>? It hasn't been committed, so this cannot be undone.`
      : `Discard changes to <strong>${_caEsc(fname)}</strong> and restore it to its last committed version? This cannot be undone.`,
    isNew ? 'Delete' : 'Discard',
    () => {
      _caHeadersAsync().then((hdrs) => {
        fetch('/api/code_agent/git/discard', {
          method: 'POST',
          headers: hdrs,
          body: JSON.stringify({ project_name: _caActiveProject, file }),
        })
          .then(async (r) => ({ ok: r.ok, data: await r.json().catch(() => ({})) }))
          .then(({ ok, data }) => {
            if (!ok) {
              _caShowError(data.detail || 'Could not discard changes.');
              return;
            }
            if (_caOpenDiffFile === file) _caCloseFileDiff('ca-file-diff-view');
            _caRefreshSourceControl(true);
          })
          .catch(() => _caShowError('Could not reach the server. Please try again.'));
      });
    },
  );
}

// ── File Explorer (left pane, "Explorer" tab) ────────────────────────────────
// Lazy per-folder loading, mirroring the Confluence page-tree pattern in
// third-pane.js (_buildConfluenceTreeRow) — one API call per expand, not one
// big recursive tree fetch up front.
function _caLoadFileTree(relPath, container) {
  if (!_caActiveProject || !container) return;
  container.innerHTML = '<div class="ca-sc-loading"></div>';
  fetch(
    `/api/code_agent/files/tree?project_name=${encodeURIComponent(_caActiveProject)}&path=${encodeURIComponent(relPath)}`,
  )
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((data) => {
      const entries = data.entries || [];
      container.innerHTML = '';
      if (!entries.length) {
        container.innerHTML = '<div class="ca-sc-empty">Empty folder</div>';
        return;
      }
      const depth = relPath ? relPath.split('/').length : 0;
      entries.forEach((entry) => container.appendChild(_caBuildFileTreeRow(entry, depth)));
    })
    .catch(() => {
      container.innerHTML = '<div class="ca-sc-empty">Could not load files</div>';
    });
}

function _caBuildFileTreeRow(entry, depth) {
  const isDir = entry.type === 'dir';
  const wrap = document.createElement('div');
  wrap.className = 'ca-fe-node';

  const row = document.createElement('div');
  row.className = 'ca-fe-row';
  row.style.paddingLeft = 8 + depth * 14 + 'px';
  row.title = entry.path;

  const chevron = document.createElement('span');
  chevron.className = 'ca-fe-chevron';
  chevron.textContent = isDir ? '▶' : '';
  row.appendChild(chevron);

  const icon = document.createElement('span');
  icon.className = 'ca-fe-icon';
  icon.textContent = isDir ? '📁' : '📄';
  row.appendChild(icon);

  const name = document.createElement('span');
  name.className = 'ca-fe-name';
  name.textContent = entry.name;
  row.appendChild(name);

  wrap.appendChild(row);

  if (isDir) {
    const childContainer = document.createElement('div');
    childContainer.className = 'ca-fe-children';
    childContainer.style.display = 'none';
    wrap.appendChild(childContainer);

    let expanded = false,
      loaded = false;
    row.addEventListener('click', () => {
      expanded = !expanded;
      chevron.textContent = expanded ? '▼' : '▶';
      childContainer.style.display = expanded ? '' : 'none';
      if (expanded && !loaded) {
        loaded = true;
        _caLoadFileTree(entry.path, childContainer);
      }
    });
  } else {
    row.addEventListener('click', () => {
      document
        .querySelectorAll('.ca-fe-row.ca-fe-row--active')
        .forEach((el) => el.classList.remove('ca-fe-row--active'));
      row.classList.add('ca-fe-row--active');
      _caOpenExplorerFile(entry.path);
    });
  }

  return wrap;
}

// Opens a file from the Explorer tab — shows the diff view if the file has
// pending changes (so Explorer and Source Control stay consistent about
// what "the current state of this file" means), otherwise a read-only view.
function _caOpenExplorerFile(file) {
  if (!_caActiveProject) return;
  const status = _caGitCache[_caActiveProject]?.status;
  const staged = (status?.staged || []).find((f) => f.file === file);
  const unstaged = (status?.unstaged || []).find((f) => f.file === file);
  const untracked = (status?.untracked || []).find((f) => f.file === file);
  if (staged || unstaged || untracked) {
    _caShowFileDiff(file, !!staged);
  } else {
    _caShowFileContent(file);
  }
}

function _caShowFileContent(file) {
  if (!_caActiveProject) return;
  const detailCol = document.getElementById('tp-detail-col');
  if (!detailCol) return;

  _caOpenDiffFile = null; // plain read-only view, not a Changes-tracked diff
  document
    .querySelectorAll('.ca-sc-file')
    .forEach((el) => el.classList.remove('ca-sc-file--active'));

  if (typeof _activeTabId !== 'undefined' && typeof _genAgentHideTerminal === 'function') {
    _genAgentHideTerminal(_activeTabId);
  }

  const diffId = 'ca-file-diff-view';
  let diffEl = document.getElementById(diffId);
  if (!diffEl) {
    diffEl = document.createElement('div');
    diffEl.id = diffId;
    diffEl.className = 'ca-file-diff-view';
    detailCol.prepend(diffEl);
  }
  diffEl.innerHTML = `<div id="ca-file-diff-monaco" class="ca-monaco-container"></div>`;
  _caMountFileHeaderChip(file, diffId);

  fetch(
    `/api/code_agent/file/content?project_name=${encodeURIComponent(_caActiveProject)}&file=${encodeURIComponent(file)}`,
  )
    .then((r) => r.json())
    .then((data) => {
      const container = document.getElementById('ca-file-diff-monaco');
      if (!container) return;
      if (data.binary) {
        container.innerHTML = '<div class="ca-sc-empty">Binary file — preview not available</div>';
        return;
      }
      _caRenderPlainFile(container, data.content || '');
    })
    .catch(() => {
      const container = document.getElementById('ca-file-diff-monaco');
      if (container) container.innerHTML = '<div class="ca-sc-empty">Could not load file</div>';
    });
}

function _caRenderPlainFile(container, text) {
  const rows = text
    .split('\n')
    .map((line, i) => {
      const g = `<span class="ca-diff-gutter">${i + 1}</span><span class="ca-diff-gutter"></span>`;
      return `<div class="ca-diff-line ca-diff-ctx">${g}<span class="ca-diff-code">${_caEsc(line) || '&nbsp;'}</span></div>`;
    })
    .join('');
  container.innerHTML = `<div class="ca-diff-view">${rows}</div>`;
}

function _caRenderPane() {
  const col = document.getElementById('tp-detail-col');
  if (!col) return;

  // Show empty state only when there are genuinely no projects configured at all
  if (_caProjects.length === 0 && !_caActiveProject) {
    col.innerHTML = _caEmptyState();
    return;
  }

  // Real gap found via user report: projects exist, but none is selected
  // for THIS tab yet (e.g. a fresh Gator chat tab) - this used to fall
  // straight through to a blank middle pane with no indication of what to
  // do next.
  if (!_caActiveProject) {
    col.innerHTML = _caNoProjectSelectedState();
    return;
  }

  // Right column is intentionally empty when idle — the file diff view is
  // prepended on demand by _caShowFileDiff. The old .ca-pane (ACTIVE SESSION,
  // changes queue, history, glossary) was stale from the pre-native-engine flow.
  col.innerHTML = '';
}

// ── Empty state ────────────────────────────────────────────────────────────────
function _caEmptyState() {
  return `
    <div class="ca-empty-state">
      <div class="ca-empty-icon">&lt;/&gt;</div>
      <div class="ca-empty-title">Open a project folder</div>
      <div class="ca-empty-subtitle">Point Gator at a folder to start working with a coding agent.</div>
      <div class="ca-empty-actions">
        <button class="ca-btn-primary"${gatorActionAttrs('_caAddLocalProject')}>Open folder…</button>
        <button class="ca-btn-link"${gatorActionAttrs('_caAddGitHubProject')}>Paste a GitHub link</button>
      </div>
    </div>`;
}

// Shown when the user already has projects connected, but hasn't picked one
// for THIS Gator chat tab yet (each tab tracks its own active project - see
// _caActiveProject). Reuses the same .ca-empty-state markup/classes as the
// "no projects at all" state above for visual consistency.
function _caNoProjectSelectedState() {
  return `
    <div class="ca-empty-state">
      <div class="ca-empty-icon">&lt;/&gt;</div>
      <div class="ca-empty-title">Select a project to get started</div>
      <div class="ca-empty-subtitle">Pick one of your projects to open its terminals here.</div>
      <div class="ca-empty-actions">
        <button class="ca-btn-secondary"${gatorActionAttrs('_caShowSessionDropdown')}>Select project ▾</button>
      </div>
    </div>`;
}

// ── Project chip ──────────────────────────────────────────────────────────────
// One chip ("● project ▾") opens the Projects menu. Rendered in the left pane
// and cloned into the topbar, next to the Needs-you count.
function _caRenderProjectSwitcher(activeProject, allProjects) {
  const area = document.getElementById('ca-sc-project-area');
  if (area) {
    area.innerHTML = '';
  }
  document
    .getElementById('tp-detail-header')
    ?.querySelectorAll('.ca-project-switcher')
    .forEach((el) => el.remove());

  const proj = activeProject ? (allProjects || []).find((p) => p.name === activeProject) : null;
  const chip = document.createElement('span');
  chip.className = 'ca-project-switcher ca-session-chip';
  chip.tabIndex = 0;
  chip.setAttribute('role', 'button');
  chip.setAttribute('aria-haspopup', 'menu');
  // "● project ▾": the dot signals a project is active. Which agent a terminal
  // runs is chosen in the tab strip's "+" menu, so it is not shown here.
  chip.textContent = proj ? '● ' + proj.name + ' ▾' : 'Select project ▾';
  chip.title = proj
    ? 'Project: ' + proj.name + ' — click to switch'
    : 'Select a project to work on';
  chip.onclick = _caShowSessionDropdown;
  chip.onkeydown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      _caShowSessionDropdown();
    }
  };
  if (area) area.appendChild(chip);

  // Also render into the topbar's code-agent area (if the Code tab is active
  // and the topbar has been populated by _caPopulateTopbar).
  const topbarArea = document.getElementById('ca-topbar-chip-area');
  if (topbarArea) {
    topbarArea.innerHTML = '';
    const topbarChip = chip.cloneNode(true);
    topbarChip.onclick = _caShowSessionDropdown;
    topbarChip.onkeydown = chip.onkeydown;
    topbarArea.appendChild(topbarChip);
    const attn = document.createElement('span');
    attn.id = 'ca-topbar-attn';
    attn.className = 'ca-topbar-attn';
    attn.hidden = true;
    attn.setAttribute('role', 'status');
    topbarArea.appendChild(attn);
    if (window.agentHistory && typeof window.agentHistory.updateDot === 'function') {
      window.agentHistory.updateDot();
    }
  }
}

// ── Topbar population ──────────────────────────────────────────────────────────
// When the Code tab is active, the topbar's drag spacer is repurposed as a
// coding-agent toolbar that mirrors the Electron shell's toolbar layout:
// [back(disabled)] [forward(disabled)] [refresh] [address-bar: lock | project/agent chip | theme-bulb | overflow] [collapse]
// When the Code tab closes, _caClearTopbar restores the empty drag spacer.

const _CA_SVG_BACK =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>';
const _CA_SVG_FORWARD =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';
const _CA_SVG_RELOAD =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
const _CA_SVG_LOCK =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>';
const _CA_SVG_OVERFLOW =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/></svg>';

function _caPopulateTopbar() {
  const spacer = document.getElementById('topbar-drag-spacer');
  if (!spacer) return;
  spacer.innerHTML = '';
  spacer.classList.add('ca-topbar-active');

  // Size the toolbar to match the third-pane width — the shell toolbar covers
  // the external app's tile, so the Code tab toolbar covers the third pane.
  // This makes the collapse button land at the same x as the shell's, so
  // switching between Slack and Code tab doesn't move it.
  // The spacer starts after wincontrols, so its width = thirdPane width -
  // wincontrols end x (which includes both wincontrols width and its x offset).
  const thirdPane = document.getElementById('third-pane');
  const wincontrols = document.getElementById('topbar-wincontrols');
  if (thirdPane && wincontrols) {
    const wcRect = wincontrols.getBoundingClientRect();
    const tpRect = thirdPane.getBoundingClientRect();
    const spacerWidth = tpRect.right - wcRect.right;
    spacer.style.flex = '0 0 ' + spacerWidth + 'px';
    spacer.style.width = spacerWidth + 'px';
  }

  // Leading drag spacer — matches shell's .tb-drag-spacer (48px grab zone
  // between window controls and nav buttons).
  const leadingDrag = document.createElement('div');
  leadingDrag.className = 'ca-tb-drag-spacer';
  spacer.appendChild(leadingDrag);

  // Nav buttons — back (disabled), forward (disabled), reload
  const backBtn = document.createElement('button');
  backBtn.className = 'ca-tb-btn';
  backBtn.title = 'Back';
  backBtn.disabled = true;
  backBtn.innerHTML = _CA_SVG_BACK;
  spacer.appendChild(backBtn);

  const fwdBtn = document.createElement('button');
  fwdBtn.className = 'ca-tb-btn';
  fwdBtn.title = 'Forward';
  fwdBtn.disabled = true;
  fwdBtn.innerHTML = _CA_SVG_FORWARD;
  spacer.appendChild(fwdBtn);

  const reloadBtn = document.createElement('button');
  reloadBtn.className = 'ca-tb-btn';
  reloadBtn.title = 'Refresh source control';
  reloadBtn.innerHTML = _CA_SVG_RELOAD;
  reloadBtn.onclick = () => {
    if (typeof _caLeftViewRefresh === 'function') _caLeftViewRefresh();
  };
  spacer.appendChild(reloadBtn);

  // Address bar — mirrors the shell toolbar's .tb-url
  const urlBar = document.createElement('div');
  urlBar.className = 'ca-tb-url';

  const lock = document.createElement('div');
  lock.className = 'ca-tb-lock';
  lock.title = 'Local repository';
  lock.innerHTML = _CA_SVG_LOCK;
  urlBar.appendChild(lock);

  // Project/agent chip (populated by _caRenderProjectSwitcher)
  const chipArea = document.createElement('div');
  chipArea.id = 'ca-topbar-chip-area';
  chipArea.className = 'ca-tb-chip-area';
  urlBar.appendChild(chipArea);

  // App theme pill — fixed width so toggling doesn't shift the layout.
  // "Dark"/"Light"/"Auto" are all 4-5 chars; min-width + center-align keeps
  // the address bar stable. It holds no state of its own: the label comes from
  // ThemeManager and a click flips the app theme (Settings, terminals and this
  // pill all follow via the gator:theme-change event).
  const themePill = document.createElement('button');
  themePill.className = 'ca-tb-app ca-tb-theme-pill';
  const themeDot = document.createElement('span');
  themeDot.className = 'ca-tb-app-dot';
  const themeLabel = document.createElement('span');
  themeLabel.className = 'ca-tb-theme-label';
  themePill.appendChild(themeDot);
  themePill.appendChild(themeLabel);
  _caSetThemePillLabel(themePill);
  themePill.onclick = () => {
    const order = ['dark', 'light', 'system'];
    const idx = order.indexOf(ThemeManager.getActive());
    ThemeManager.set(order[(idx + 1) % order.length]);
  };
  urlBar.appendChild(themePill);

  // Overflow (placeholder — future menu)
  const overflow = document.createElement('button');
  overflow.className = 'ca-tb-overflow';
  overflow.title = 'More actions';
  overflow.innerHTML = _CA_SVG_OVERFLOW;
  urlBar.appendChild(overflow);

  spacer.appendChild(urlBar);

  // Collapse Gator button — same dimensions/style as shell's .tb-collapse-btn
  const collapseBtn = document.createElement('button');
  collapseBtn.className = 'ca-tb-collapse-btn';
  collapseBtn.title = 'Hide Gator';
  collapseBtn.innerHTML =
    "<span class=\"material-symbols-outlined\" style=\"font-size:18px;line-height:1;font-variation-settings:'FILL' 0,'wght' 300,'GRAD' 0,'opsz' 24;\">left_panel_open</span>";
  collapseBtn.onclick = () => {
    if (typeof GatorChat !== 'undefined' && GatorChat.toggle) GatorChat.toggle();
    else if (typeof _tpToggleExpand === 'function') _tpToggleExpand();
  };
  spacer.appendChild(collapseBtn);

  // Right drag spacer — matches shell's .tb-drag-spacer-right (8px grab zone)
  const rightDrag = document.createElement('div');
  rightDrag.className = 'ca-tb-drag-spacer-right';
  spacer.appendChild(rightDrag);

  // Re-render the project chip into the new address bar
  _caRenderProjectSwitcher(_caActiveProject, _caProjects);

  // Re-size the toolbar when the third-pane resizes (window resize, pane drag)
  // so the collapse button stays aligned with the shell toolbar's position.
  // Skip during external-app transitions (gator-split) — _caSyncTopbarForExternalApp
  // handles sizing then, and following the third-pane's 0.38s width transition
  // would cause Part B to slide.
  if (!window._caTopbarResizeObs) {
    window._caTopbarResizeObs = new ResizeObserver(() => {
      const sp = document.getElementById('topbar-drag-spacer');
      if (
        sp &&
        sp.classList.contains('ca-topbar-active') &&
        !document.body.classList.contains('gator-split') &&
        !document.body.classList.contains('gator-squeezed')
      ) {
        const tp = document.getElementById('third-pane');
        const wc = document.getElementById('topbar-wincontrols');
        if (tp && wc) {
          const tpRect = tp.getBoundingClientRect();
          const wcRect = wc.getBoundingClientRect();
          const w = tpRect.right - wcRect.right;
          sp.style.flex = '0 0 ' + w + 'px';
          sp.style.width = w + 'px';
        }
      }
    });
    const tp = document.getElementById('third-pane');
    if (tp) window._caTopbarResizeObs.observe(tp);
  }
}

function _caClearTopbar() {
  const spacer = document.getElementById('topbar-drag-spacer');
  if (!spacer) return;
  spacer.innerHTML = '';
  spacer.classList.remove('ca-topbar-active');
  spacer.style.flex = '';
  spacer.style.width = '';
}

// Watch for external-app activation (body.gator-split / body.gator-squeezed).
// When an external app opens, the shell toolbar takes over — clear the Code
// tab topbar so it doesn't conflict. When the external app closes and we're
// still on the Code tab, re-populate it.
function _caSyncTopbarForExternalApp() {
  const isExternal =
    document.body.classList.contains('gator-split') ||
    document.body.classList.contains('gator-squeezed');
  // Handle both Code tab and Calendar — both use ca-topbar-active
  const isTopbarActive =
    typeof tpState !== 'undefined' &&
    (tpState.type === 'code_agent' || tpState.type === 'calendar');
  const spacer = document.getElementById('topbar-drag-spacer');
  if (!spacer || !spacer.classList.contains('ca-topbar-active')) return;

  // Suppress the third-pane's 0.38s width transition during external-app
  // open/close.
  const pane = document.getElementById('third-pane');
  if (pane) {
    pane.classList.add('no-transition');
    setTimeout(() => pane.classList.remove('no-transition'), 50);
  }

  if (isExternal && isTopbarActive) {
    // External app active — shell toolbar covers the third-pane area.
    // Snap spacer to the Gator chat tile's left edge.
    const main = document.querySelector('main.main') || document.querySelector('main');
    const wc = document.getElementById('topbar-wincontrols');
    if (main && wc) {
      const mainRect = main.getBoundingClientRect();
      const wcRect = wc.getBoundingClientRect();
      const w = Math.max(0, mainRect.left - wcRect.right);
      spacer.style.flex = '0 0 ' + w + 'px';
      spacer.style.width = w + 'px';
    }
  } else if (!isExternal && isTopbarActive) {
    // External app closed — restore spacer to third-pane width.
    const tp = document.getElementById('third-pane');
    const wc = document.getElementById('topbar-wincontrols');
    if (tp && wc) {
      const tpRect = tp.getBoundingClientRect();
      const wcRect = wc.getBoundingClientRect();
      const w = Math.max(0, tpRect.right - wcRect.right);
      spacer.style.flex = '0 0 ' + w + 'px';
      spacer.style.width = w + 'px';
    }
    // Repopulate if empty (Code tab needs its toolbar rebuilt)
    if (tpState.type === 'code_agent' && spacer.children.length === 0) {
      _caPopulateTopbar();
    }
  }
}

// Set up the MutationObserver once
let _caBodyObserverInstalled = false;
function _caInstallBodyObserver() {
  if (_caBodyObserverInstalled) return;
  _caBodyObserverInstalled = true;
  const observer = new MutationObserver(() => {
    _caSyncTopbarForExternalApp();
  });
  observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
}

// ── Terminal theme ─────────────────────────────────────────────────────────────

function _caXtermTheme() {
  // The app theme is the single source of truth (ThemeManager sets data-theme).
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  return light
    ? { background: '#ffffff', foreground: '#0f172a', cursor: '#0f172a' }
    : { background: '#0b0d12', foreground: '#d4d4d4', cursor: '#d4d4d4' };
}

function _caApplyTerminalTheme() {
  const theme = _caXtermTheme();
  // Apply to all live generic-agent terminal sessions
  if (typeof _genAgentTerminals !== 'undefined') {
    Object.values(_genAgentTerminals).forEach((state) => {
      Object.values(state.sessions || {}).forEach((sess) => {
        if (sess.term) sess.term.options.theme = theme;
      });
    });
  }
}

// Pill label mirrors ThemeManager: Auto for system, else Light/Dark.
function _caSetThemePillLabel(pill) {
  const active = ThemeManager.getActive();
  const label = active === 'system' ? 'Auto' : active === 'light' ? 'Light' : 'Dark';
  const labelEl = pill.querySelector('.ca-tb-theme-label');
  if (labelEl) labelEl.textContent = label;
  pill.title = 'Theme: ' + label;
}

function _caRefreshThemePill() {
  const pill = document.querySelector('.ca-tb-theme-pill');
  if (pill) _caSetThemePillLabel(pill);
}

// Registered once: a theme flip from Settings, the pill, or the OS re-tints
// the live terminals and refreshes the pill label.
window.addEventListener('gator:theme-change', () => {
  _caApplyTerminalTheme();
  _caRefreshThemePill();
});

// Remembers the agent picked from a terminal tab's "+" menu as the project's
// default, so the next "+" menu marks it and a cold reopen offers it first.
async function _caRememberProjectAgent(projectName, agent) {
  const proj = _caProjects.find((p) => p.name === projectName);
  if (!proj || _caProjectAgent(proj) === agent) return;
  try {
    const headers = await _caHeadersAsync();
    const resp = await _caFetchWithCsrfRetry('/api/code_agent/projects/agent', {
      method: 'PUT',
      headers,
      body: JSON.stringify({ name: projectName, agent }),
    });
    if (resp.ok) proj.agent = agent;
  } catch (_) {}
}

// The first project opens in this window. Once one is active here, others open
// in a new window so this window's running terminals are never torn down.
// In the Electron shell, openGatorWindow creates a real BrowserWindow (the
// Gator view's setWindowOpenHandler would otherwise deny window.open and send
// it to the system browser); browser mode falls back to window.open.
function _caOpenProject(name) {
  if (!_caActiveProject) {
    _caSetActiveProject(name);
    return;
  }
  const url = new URL(window.location.href);
  url.search = '';
  url.searchParams.set('open_project', name);
  if (window.gatorShell && typeof window.gatorShell.openGatorWindow === 'function') {
    window.gatorShell.openGatorWindow(url.toString());
  } else {
    window.open(url.toString(), '_blank');
  }
}

async function _caRemoveProject(name) {
  const headers = await _caHeadersAsync();
  const resp = await _caFetchWithCsrfRetry('/api/code_agent/projects/' + encodeURIComponent(name), {
    method: 'DELETE',
    headers,
  });
  if (!resp.ok) throw new Error('remove failed');
  await _caLoadProjects();
}

const _CA_RECENT_COUNT = 5;
const _CA_SEARCH_MIN_PROJECTS = 7;

// The Projects menu: switch, search, remove, or open a folder. One job only;
// which agent a terminal runs is chosen where terminals are created (the tab
// strip's "+" menu).
function _caShowSessionDropdown() {
  document.querySelector('.ca-project-dropdown')?.remove();

  // If projects haven't loaded yet, load them first then re-show.
  if (_caProjects.length === 0) {
    _caLoadProjects().then(() => {
      if (_caProjects.length > 0) _caShowSessionDropdown();
    });
    return;
  }

  const helpers = window.codePickerHelpers;
  const dropdown = document.createElement('div');
  dropdown.className = 'ca-project-dropdown';
  dropdown.setAttribute('role', 'menu');
  dropdown.setAttribute('aria-label', 'Projects');

  let search = null;
  if (_caProjects.length > _CA_SEARCH_MIN_PROJECTS) {
    search = document.createElement('input');
    search.type = 'search';
    search.className = 'ca-project-search';
    search.placeholder = 'Search projects';
    search.setAttribute('aria-label', 'Search projects');
    search.autocomplete = 'off';
    dropdown.appendChild(search);
  }
  const list = document.createElement('div');
  list.className = 'ca-project-list';
  dropdown.appendChild(list);

  const divider = document.createElement('div');
  divider.className = 'ca-project-divider';
  dropdown.appendChild(divider);
  const addItem = document.createElement('div');
  addItem.className = 'ca-project-item ca-project-add';
  addItem.setAttribute('role', 'menuitem');
  addItem.tabIndex = -1;
  addItem.textContent = 'Open folder…';
  addItem.onclick = () => {
    close();
    _caAddLocalProject();
  };
  dropdown.appendChild(addItem);

  const addSection = (text) => {
    const header = document.createElement('div');
    header.className = 'ca-project-section';
    header.textContent = text;
    list.appendChild(header);
  };

  const confirmRow = (p) => {
    const row = document.createElement('div');
    row.className = 'ca-project-item ca-project-confirm';
    const msg = document.createElement('div');
    msg.className = 'ca-project-confirm-msg';
    msg.textContent = 'Remove from Gator? Your files are not touched.';
    const actions = document.createElement('div');
    actions.className = 'ca-project-confirm-actions';
    const yes = document.createElement('button');
    yes.type = 'button';
    yes.className = 'ca-project-confirm-yes';
    yes.textContent = 'Remove';
    const no = document.createElement('button');
    no.type = 'button';
    no.className = 'ca-project-confirm-no';
    no.textContent = 'Cancel';
    yes.onclick = async () => {
      yes.disabled = true;
      try {
        await _caRemoveProject(p.name);
        if (_caProjects.length === 0) {
          close();
          _caRenderPane();
          _caRenderProjectSwitcher(_caActiveProject, _caProjects);
          return;
        }
        render();
      } catch (_) {
        msg.textContent = 'Could not remove ' + p.name + '. Try again.';
        yes.disabled = false;
      }
    };
    no.onclick = () => render();
    actions.append(yes, no);
    row.append(msg, actions);
    return row;
  };

  const projectRow = (p) => {
    const isCurrent = p.name === _caActiveProject;
    const row = document.createElement('div');
    row.className =
      'ca-project-item ca-project-row' + (isCurrent ? ' ca-project-item--active' : '');
    row.setAttribute('role', 'menuitem');
    row.tabIndex = -1;
    const dot = document.createElement('span');
    dot.className = 'ca-project-dot';
    dot.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.className = 'ca-project-text';
    const name = document.createElement('span');
    name.className = 'ca-project-name';
    name.textContent = p.name;
    const path = document.createElement('span');
    path.className = 'ca-project-path';
    path.textContent = p.repo_path || '';
    path.title = p.repo_path || '';
    text.append(name, path);
    row.append(dot, text);
    if (isCurrent) {
      row.title = 'Open in this window';
      row.style.cursor = 'default';
    } else {
      row.title = _caActiveProject ? 'Open ' + p.name + ' in a new window' : 'Select ' + p.name;
      row.onclick = () => {
        close();
        _caOpenProject(p.name);
      };
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'ca-project-remove';
      remove.title = 'Remove from Gator';
      remove.setAttribute('aria-label', 'Remove ' + p.name + ' from Gator');
      remove.textContent = '×';
      remove.onclick = (e) => {
        e.stopPropagation();
        row.replaceWith(confirmRow(p));
      };
      row.appendChild(remove);
    }
    return row;
  };

  function render() {
    list.replaceChildren();
    const query = search ? search.value : '';
    const sorted = helpers.sortProjects(_caProjects);
    if (query.trim()) {
      const hits = helpers.filterProjects(sorted, query);
      if (!hits.length) addSection('No matching projects');
      hits.forEach((p) => list.appendChild(projectRow(p)));
      return;
    }
    const recent = sorted.filter((p) => p.last_opened).slice(0, _CA_RECENT_COUNT);
    const rest = sorted.filter((p) => !recent.includes(p));
    if (recent.length) {
      addSection('Recent');
      recent.forEach((p) => list.appendChild(projectRow(p)));
    }
    if (rest.length) {
      if (recent.length) addSection('All projects');
      rest.forEach((p) => list.appendChild(projectRow(p)));
    }
  }

  function close() {
    dropdown.remove();
    document.removeEventListener('click', onOutside);
    document.removeEventListener('keydown', onKey, true);
  }
  function onOutside(e) {
    if (!dropdown.contains(e.target) && !e.target.classList.contains('ca-project-switcher')) {
      close();
    }
  }
  const focusables = () => [
    ...(search ? [search] : []),
    ...dropdown.querySelectorAll('.ca-project-row, .ca-project-add'),
  ];
  function onKey(e) {
    if (!dropdown.isConnected) {
      close();
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      document.querySelector('.ca-session-chip')?.focus?.();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const items = focusables();
      const at = items.indexOf(document.activeElement);
      const step = e.key === 'ArrowDown' ? 1 : -1;
      items[(at + step + items.length) % items.length]?.focus();
    } else if (e.key === 'Enter' && document.activeElement?.classList.contains('ca-project-item')) {
      e.preventDefault();
      document.activeElement.click();
    }
  }

  render();
  if (search) search.addEventListener('input', render);
  document.body.appendChild(dropdown);

  // Position below the chip.
  const chip = document.querySelector('.ca-session-chip');
  if (chip) {
    const rect = chip.getBoundingClientRect();
    const margin = 8;
    const spaceBelow = window.innerHeight - rect.bottom - margin;
    const spaceAbove = rect.top - margin;
    // Prefer below the chip, but flip above when the project list has more
    // usable room there. The CSS supplies the thin app scrollbar once the
    // rendered menu exceeds this bound.
    const openBelow = spaceBelow >= spaceAbove;
    const availableHeight = Math.max(0, openBelow ? spaceBelow : spaceAbove);
    dropdown.style.maxHeight = availableHeight + 'px';
    dropdown.style.top = openBelow
      ? rect.bottom + 4 + 'px'
      : Math.max(margin, rect.top - Math.min(dropdown.scrollHeight, availableHeight) - 4) + 'px';
    dropdown.style.left = rect.left + 'px';
  }

  (search || focusables()[0])?.focus();
  document.addEventListener('keydown', onKey, true);
  setTimeout(() => document.addEventListener('click', onOutside), 0);
}

function _caSetActiveProject(name) {
  document.querySelector('.ca-project-dropdown')?.remove();

  // If the project is actually changing, tear down the current session completely.
  // A session is bound to a repo at creation time — switching projects means the
  // old session would submit follow-ups to the wrong repo.
  if (name !== _caActiveProject && typeof _activeTabId !== 'undefined') {
    // Detach (don't discard) the terminal - the actual session binding for the
    // OLD project is kept, so switching back to it later can still reattach.
    if (typeof _genAgentDetachAllForTab === 'function') {
      _genAgentDetachAllForTab(_activeTabId);
    }
    // Unlock submit button if it was locked by the old session
    const _btn =
      document.getElementById('send-btn') ||
      document.querySelector('.chat-form button[type="submit"]');
    if (_btn) _btn.disabled = false;
  }

  _caActiveProject = name;
  _caRenderPane();
  _caRenderProjectSwitcher(_caActiveProject, _caProjects);
  _caRefreshSourceControl();
  if (name) _caSetLeftView(_caStoredLeftView(name));

  // Persist active project on the server so new sessions use the right repo
  _caHeadersAsync().then((hdrs) => {
    fetch('/api/code_agent/projects/active', {
      method: 'PUT',
      headers: hdrs,
      body: JSON.stringify({ name }),
    }).catch(() => {});
  });

  // Reattach to an existing OpenCode session for the NEWLY selected project,
  // or auto-start a bare one if none exists yet. Two real bugs found via
  // manual testing, not caught earlier: (1) this check previously only ran
  // once, from _initCodeAgentPane's initial page-load render - picking a
  // different project from the dropdown afterward never re-checked the new
  // project at all; (2) even when it did check, finding no existing session
  // just gave up instead of starting one, leaving the middle pane blank with
  // no way to populate it short of calling the dispatch function by hand.
  if (name && typeof _activeTabId !== 'undefined') {
    const _proj = _caProjects.find((p) => p.name === name);
    if (_proj && _proj.repo_path) {
      // Guided: show the Start/Resume prompt (no auto cold-spawn on select).
      _caShowAgentStartOrTerminal(_activeTabId, _proj, _proj.repo_path);
    }
  }
}

// ── Project management ─────────────────────────────────────────────────────────
function _caLoadProjects() {
  return fetch('/api/code_agent/projects')
    .then((r) => (r.ok ? r.json() : { projects: [], active: null }))
    .then((data) => {
      _caProjects = data.projects || [];
      // If this browser tab was opened with ?open_project=Name, auto-select it.
      const urlProject = new URLSearchParams(window.location.search).get('open_project');
      if (urlProject && _caProjects.find((p) => p.name === urlProject)) {
        _caActiveProject = urlProject;
        // Clean the URL param so refreshing doesn't re-trigger
        try {
          const url = new URL(window.location);
          url.searchParams.delete('open_project');
          history.replaceState({}, '', url);
        } catch (_) {}
      } else {
        // The open project may have been removed in another window. Follow the server's
        // active pointer (it moves to the next most recent) so chat and this view agree;
        // with none left the no-project states show instead of a blank pane.
        if (_caActiveProject && !_caProjects.some((p) => p.name === _caActiveProject))
          _caActiveProject = _caProjects.some((p) => p.name === data.active) ? data.active : null;
        // Auto-select if only one project exists
        if (!_caActiveProject)
          _caActiveProject = _caProjects.length === 1 ? _caProjects[0].name : null;
      }
      // NOTE: no fire-and-forget /api/opencode/warm here anymore. Guided start
      // means OpenCode only spawns on an explicit user click (Start/Resume), so
      // pre-warming a cold ~15-30s server before any click was exactly the auto-
      // spawn (and window/churn) we removed. The explicit Start does the spawn.
    })
    .catch(() => {
      _caProjects = [];
      _caActiveProject = null;
    });
}

function _caAddLocalProject() {
  // Use native directory picker (same as Ctrl+O file picker)
  fetch('/api/directory-picker?title=Select+your+project+folder', { method: 'POST' })
    .then((r) => r.json())
    .then((data) => {
      if (!data.ok || !data.folder_path) return; // user cancelled
      const path = data.folder_path;
      const name = path.split(/[\\/]/).filter(Boolean).pop() || 'my-app';
      // Sanitise name: replace spaces/dots with dashes, lowercase
      const safeName = name
        .replace(/[^a-zA-Z0-9_-]/g, '-')
        .replace(/-+/g, '-')
        .slice(0, 64);
      _caSubmitAddProject(safeName, path, false);
    })
    .catch(() => alert('Could not open the folder picker. Please try again.'));
}

// Posts /api/code_agent/projects. On "not a git repo yet", offers to run
// `git init` in-place and retries once with initGit=true — instead of the
// old dead-end alert that left non-git folders permanently blocked.
function _caSubmitAddProject(safeName, path, initGit) {
  _caHeadersAsync().then((hdrs) => {
    _caFetchWithCsrfRetry('/api/code_agent/projects', {
      method: 'POST',
      headers: hdrs,
      body: JSON.stringify({ name: safeName, repo_path: path, source: 'local', init_git: initGit }),
    })
      .then((r) => r.json())
      .then((result) => {
        if (result.status === 'created') {
          _caLoadProjects().then(() => _caSetActiveProject(result.project.name));
        } else if (!initGit && result.detail && result.detail.code === 'not_git_repo') {
          if (
            confirm(
              "This folder isn't a git repository yet. Initialize one now so the Code tab can track changes?",
            )
          ) {
            _caSubmitAddProject(safeName, path, true);
          }
        } else {
          const detail = result.detail;
          alert(
            (detail && detail.message) || detail || 'Could not add the project. Please try again.',
          );
        }
      })
      .catch(() => alert('Could not add the project. Please try again.'));
  });
}

function _caAddGitHubProject() {
  // Show an inline input overlay instead of window.prompt
  const overlay = document.createElement('div');
  overlay.className = 'ca-inline-prompt';
  overlay.innerHTML = `
    <div class="ca-inline-prompt-box">
      <div class="ca-inline-prompt-label">Paste a GitHub URL</div>
      <input class="ca-inline-prompt-input" type="url" placeholder="https://github.com/org/repo" autocomplete="off" spellcheck="false">
      <div class="ca-inline-prompt-hint">We'll clone it into your Gator folder automatically.</div>
      <div class="ca-inline-prompt-actions">
        <button class="ca-btn-decline"${gatorActionAttrs('removeClosest', [{ $el: true }, '.ca-inline-prompt'])}>Cancel</button>
        <button class="ca-btn-approve" id="ca-github-confirm">Clone</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const input = overlay.querySelector('.ca-inline-prompt-input');
  input.focus();

  const doClone = () => {
    const url = input.value.trim();
    if (!url) return;
    overlay.remove();
    const parts = url.replace(/\/$/, '').split('/');
    const rawName = parts[parts.length - 1]?.replace(/\.git$/, '') || 'my-app';
    const name = rawName
      .replace(/[^a-zA-Z0-9_-]/g, '-')
      .replace(/-+/g, '-')
      .slice(0, 64);

    // Show cloning progress in the Code tab
    _caAppendProgress(`Cloning ${name}…`);
    const sessionEl = document.getElementById('ca-active-session');
    if (sessionEl) sessionEl.style.display = '';

    _caHeadersAsync().then((hdrs) => {
      _caFetchWithCsrfRetry('/api/code_agent/projects', {
        method: 'POST',
        headers: hdrs,
        body: JSON.stringify({ name, repo_path: url, source: 'github' }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.status === 'created') {
            _caLoadProjects().then(() => _caSetActiveProject(data.project.name));
          } else {
            _caShowError(data.detail || 'Could not clone the repository. Please check the URL.');
          }
        })
        .catch(() => _caShowError('Could not reach the server. Please try again.'));
    });
  };

  overlay.querySelector('#ca-github-confirm').onclick = doClone;
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doClone();
    if (e.key === 'Escape') overlay.remove();
  });
}

function _caAppendProgress(msg) {
  const log = document.getElementById('ca-progress-log');
  if (!log) return;
  const line = document.createElement('div');
  line.className = 'ca-progress-line';
  line.innerHTML = `<span class="ca-progress-dot">◌</span> ${_caEsc(msg)}`;
  log.appendChild(line);
  // Mark previous lines as done
  log.querySelectorAll('.ca-progress-dot').forEach((dot, i, all) => {
    if (i < all.length - 1) dot.textContent = '✓';
  });
}

// ── GitHub section ─────────────────────────────────────────────────────────────
function _caRenderGitHub() {
  const list = document.getElementById('ca-github-list');
  if (!list) return;

  // Only show GitHub section if the active project is a GitHub-sourced repo
  const activeProject = _caProjects.find((p) => p.name === _caActiveProject);
  if (!activeProject || activeProject.source !== 'github') {
    list.innerHTML =
      '<div class="ca-empty-section">Connect a GitHub repository to see PR activity here.</div>';
    return;
  }

  if (typeof _ghDirectTool !== 'function') {
    list.innerHTML =
      '<div class="ca-empty-section">Connect GitHub in Settings to see your team\'s activity here.</div>';
    return;
  }

  // Filter PRs to this specific repo
  const repoPath = activeProject.repo_path || '';
  const repoParts = repoPath.replace(/\/$/, '').split('/');
  const repoName = repoParts[repoParts.length - 1]?.replace(/\.git$/, '') || '';
  const orgName = repoParts[repoParts.length - 2] || '';

  _ghDirectTool('github_list_my_prs', { state: 'open', per_page: 5 })
    .then((result) => {
      let prs = result?.items || result?.pull_requests || [];
      // Filter to this repo if we can identify it
      if (repoName && orgName) {
        const filtered = prs.filter((pr) => {
          const url = pr.url || pr.html_url || '';
          return url.includes(`/${orgName}/${repoName}/`);
        });
        if (filtered.length) prs = filtered;
      }
      if (!prs.length) {
        list.innerHTML =
          '<div class="ca-empty-section">No open pull requests for this project.</div>';
        return;
      }
      list.innerHTML = prs
        .map(
          (pr) => `
        <div class="ca-github-item">
          <span class="ca-github-dot" style="color:var(--gh-open)">⬤</span>
          <span class="ca-github-title">${_caEsc(pr.title || 'Pull request')}</span>
          <span class="ca-github-meta">${_caEsc(pr.state || 'open')}</span>
        </div>`,
        )
        .join('');
    })
    .catch(() => {
      list.innerHTML = '<div class="ca-empty-section">Could not load GitHub activity.</div>';
    });
}

// ── Teaching card in chat ──────────────────────────────────────────────────────
function _caShowTeachingCardInChat(content) {
  // Parse __TEACHING_CARD__ ... __END_TEACHING_CARD__ markers
  if (!content || !content.includes('__TEACHING_CARD__')) return;

  const lines = content.split('\n');
  const parsed = {};
  lines.forEach((line) => {
    if (line.startsWith('Before:')) parsed.before = line.slice(7).trim();
    else if (line.startsWith('After:')) parsed.after = line.slice(6).trim();
    else if (line.startsWith('Scope:')) parsed.scope = line.slice(6).trim();
    else if (line.startsWith('Title:')) parsed.title = line.slice(6).trim();
  });

  if (!parsed.before && !parsed.after && !parsed.scope) return;

  // Inject into the chat prose area as a styled card
  // Look for the chat response area (may vary by app version)
  const chatArea =
    document.getElementById('chat-messages') ||
    document.querySelector('.chat-messages') ||
    document.querySelector('.prose');
  if (!chatArea) return;

  const card = document.createElement('div');
  card.className = 'ca-teaching-card';
  card.innerHTML = `
    <div class="ca-teaching-title">🐊 What just changed in your app</div>
    ${parsed.title ? `<div class="ca-teaching-change">${_caEsc(parsed.title)} — applied ✓</div>` : ''}
    ${parsed.before ? `<div class="ca-teaching-section"><span class="ca-teaching-label">Before</span> ${_caEsc(parsed.before)}</div>` : ''}
    ${parsed.after ? `<div class="ca-teaching-section"><span class="ca-teaching-label">After</span> ${_caEsc(parsed.after)}</div>` : ''}
    ${parsed.scope ? `<div class="ca-teaching-section"><span class="ca-teaching-label">Scope</span> ${_caEsc(parsed.scope)}</div>` : ''}`;

  chatArea.appendChild(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

// ── Error display ──────────────────────────────────────────────────────────────
function _caShowError(msg) {
  const sessionEl = document.getElementById('ca-active-session');
  if (!sessionEl) return;
  const errEl = document.createElement('div');
  errEl.className = 'ca-error-state';
  errEl.innerHTML = `
    <div class="ca-error-msg">${_caEsc(msg)}</div>
    <div class="ca-error-actions">
      <button class="ca-btn-secondary"${gatorActionAttrs('removeClosest', [{ $el: true }, '.ca-error-state'])}>Dismiss</button>
    </div>`;
  sessionEl.appendChild(errEl);
}

// ── Utilities ──────────────────────────────────────────────────────────────────
function _caEsc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
