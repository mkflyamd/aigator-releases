// tp-code-agent.js — Code tab for AI Gator Coding Agent
// All Code tab logic is isolated here — nothing added to third-pane.js internals.

// ── State ──────────────────────────────────────────────────────────────────────
let _caProjects = []; // [{name, repo_path, source}]
let _caActiveProject = null; // active project name string (global to this browser tab)
let _caLeftView = 'scm'; // 'scm' | 'explorer' — which view the left pane shows
let _caOpenDiffFile = null; // repo-relative path of the file currently open in the right pane (if a Changes diff), else null

// ── Session scoping ───────────────────────────────────────────────────────────
// When true (default), the coding-agent terminal session is SHARED across all
// Gator chat tabs — one terminal for the whole app, like Teams/Outlook. Users
// treat the coding agent as an app, not a per-conversation resource; the
// terminal's own tab strip provides multi-session parallelism. Set false to
// restore the prior per-Gator-tab model (one terminal per chat tab).
//
// Implementation: _caSessionKey() maps a Gator tabId to the key used in the
// terminal state maps (_ocTerminals / _genAgentTerminals). Shared mode returns
// a constant '_shared' key so every tab looks up the SAME state; per-tab mode
// returns the tabId itself (the original behavior). All tabId-keyed session
// access in tp-opencode-terminal.js / tp-generic-agent-terminal.js routes
// through this function — flipping the flag is the only change needed.
const SHARED_CODE_SESSION = true;
function _caSessionKey(tabId) {
  return SHARED_CODE_SESSION ? '_shared' : String(tabId);
}

// ── Agent dispatch (OpenCode vs generic BYO-config agents) ──────────────────
// Small routing layer so call sites don't need to know which terminal
// implementation backs a given project - defaults to "opencode-bare" (see
// _CA_AGENT_LABELS above for why) for any project without an explicit agent
// set. Every project that predates this default change now silently starts
// using the bare path too, not just newly-created ones - a deliberate choice
// once bare's reliability was confirmed, not an oversight.
function _caProjectAgent(project) {
  return (project && project.agent) || 'opencode-bare';
}

function _caMountAgentTab(tabId, project) {
  // Both agents mount their session tab strip in the shared #tp-detail-header;
  // only one may be present at a time. Clear the other's strip before mounting
  // this one, so switching a project between OpenCode and a generic agent
  // never leaves a stale strip from the previous agent in the header.
  if (_caProjectAgent(project) === 'opencode') {
    if (typeof _genAgentRemoveHeaderTabStrip === 'function') _genAgentRemoveHeaderTabStrip();
    if (typeof _ocMountActiveTab === 'function') _ocMountActiveTab(tabId);
  } else {
    if (typeof _ocRemoveHeaderTabStrip === 'function') _ocRemoveHeaderTabStrip();
    if (typeof _genAgentMountActiveTab === 'function') _genAgentMountActiveTab(tabId);
  }
}

function _caShowAgentStartOrTerminal(tabId, project, repoPath) {
  const agent = _caProjectAgent(project);
  if (agent === 'opencode') {
    if (typeof _ocShowStartOrTerminal === 'function')
      _ocShowStartOrTerminal(tabId, project.name, repoPath);
  } else if (typeof _genAgentShowStartOrTerminal === 'function') {
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
  }
  const rightCol = document.getElementById('tp-right-col');
  if (rightCol) {
    rightCol.classList.remove('tp-cal-full');
  }

  // If projects already loaded (e.g. by URL param handler), skip the fetch
  const _doRender = () => {
    _caRenderPane();
    _caRenderProjectSwitcher(_caActiveProject, _caProjects);
    _caRefreshSourceControl();
    _caStartSourceControlPolling();
    // Re-attach any already-live terminal into the freshly-rebuilt DOM BEFORE
    // deciding whether to show Start/Resume. This path runs on a full return
    // from another skill (Teams/Email), which tears down and rebuilds
    // #tp-detail-col - without re-mounting first, _ocIsTerminalMounted always
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
        if (
          window._ocHandoffAutoStart &&
          _caProjectAgent(_proj) === 'opencode' &&
          typeof _ocStartOrResume === 'function'
        ) {
          window._ocHandoffAutoStart = false;
          _ocStartOrResume(_activeTabId, _caActiveProject, _proj.repo_path);
        } else {
          window._ocHandoffAutoStart = false;
          _caShowAgentStartOrTerminal(_activeTabId, _proj, _proj.repo_path);
        }
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
function _caSourceControlPanel() {
  return `
    <div class="ca-sc-panel">
      <div class="ca-sc-header">
        <div id="ca-sc-project-area" class="ca-sc-project-area"></div>
        <button class="ca-sc-refresh" onclick="_caLeftViewRefresh()" title="Refresh">↻</button>
      </div>
      <div class="ca-sc-viewtabs">
        <button class="ca-sc-viewtab active" id="ca-viewtab-scm" onclick="_caSetLeftView('scm')">Source Control</button>
        <button class="ca-sc-viewtab" id="ca-viewtab-explorer" onclick="_caSetLeftView('explorer')">Explorer</button>
      </div>
      <div id="ca-scm-view" class="ca-scm-view">
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
    </div>`;
}

// ── Left pane view toggle (Source Control ↔ Explorer) ───────────────────────
function _caSetLeftView(view) {
  const scmView = document.getElementById('ca-scm-view');
  const feView = document.getElementById('ca-fe-view');
  if (!scmView || !feView) return;
  const showExplorer = view === 'explorer';
  _caLeftView = showExplorer ? 'explorer' : 'scm';
  scmView.style.display = showExplorer ? 'none' : '';
  feView.style.display = showExplorer ? '' : 'none';
  document.getElementById('ca-viewtab-scm')?.classList.toggle('active', !showExplorer);
  document.getElementById('ca-viewtab-explorer')?.classList.toggle('active', showExplorer);
  if (showExplorer) _caLoadFileTree('', document.getElementById('ca-fe-root'), 0);
}

function _caLeftViewRefresh() {
  if (_caLeftView === 'explorer') {
    _caLoadFileTree('', document.getElementById('ca-fe-root'), 0);
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
        return `<div class="ca-sc-file" onclick="_caShowFileDiff('${_caEsc(f.file)}',${isStaged})" title="${_caEsc(f.file)}">
        <span class="ca-sc-file-name">${_caEsc(fname)}</span>
        <button class="ca-sc-file-discard" onclick="event.stopPropagation();_caDiscardFile('${_caEsc(f.file)}','${f.status}')" title="${f.status === '?' ? 'Delete file' : 'Discard changes'}">🗑️</button>
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

  // Hide (don't destroy) an active OpenCode terminal for this tab so the
  // diff doesn't render squished alongside it - #tp-detail-col is a flex
  // column, so two visible flex:1 children would share space rather than
  // one covering the other.
  if (typeof _activeTabId !== 'undefined' && typeof _ocHideTerminal === 'function') {
    _ocHideTerminal(_activeTabId);
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
  // Restore whichever OpenCode terminal was hidden for this tab, if any.
  if (typeof _activeTabId !== 'undefined' && typeof _ocShowTerminal === 'function') {
    _ocShowTerminal(_activeTabId);
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
// user report: the file view sits on top of the terminal (`_ocHideTerminal`
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

  if (typeof _activeTabId !== 'undefined' && typeof _ocHideTerminal === 'function') {
    _ocHideTerminal(_activeTabId);
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
      <div class="ca-empty-title">Connect your first app</div>
      <div class="ca-empty-subtitle">Point Gator at your codebase to start making changes in plain English.</div>
      <div class="ca-empty-actions">
        <button class="ca-btn-secondary" onclick="_caAddLocalProject()">Browse for folder</button>
        <button class="ca-btn-secondary" onclick="_caAddGitHubProject()">Paste a GitHub link</button>
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
      <div class="ca-empty-subtitle">Pick one of your connected apps and I'll open its OpenCode terminal here.</div>
      <div class="ca-empty-actions">
        <button class="ca-btn-secondary" onclick="_caShowSessionDropdown()">Select project ▾</button>
      </div>
    </div>`;
}

// ── Session selector (project + agent, one chip → one unified dropdown) ──────
// The left-pane header is narrow. Two separate pills (project ▾ + agent ▾)
// crammed in together were unclear and truncated. Now a SINGLE chip shows the
// current state compactly — "● myrepo · OpenCode ▾" — and opens one dropdown
// with two labeled sections (PROJECT / CODING AGENT). One click, one menu,
// half the horizontal footprint. A coding "session" = project + agent, which
// is exactly what this picks.
function _caRenderProjectSwitcher(activeProject, allProjects) {
  const area = document.getElementById('ca-sc-project-area');
  if (!area) return;
  area.innerHTML = '';
  document
    .getElementById('tp-detail-header')
    ?.querySelectorAll('.ca-project-switcher')
    .forEach((el) => el.remove());

  const proj = activeProject ? (allProjects || []).find((p) => p.name === activeProject) : null;
  const agentLabel = proj ? _CA_AGENT_LABELS[_caProjectAgent(proj)] || _caProjectAgent(proj) : '';

  const chip = document.createElement('span');
  chip.className = 'ca-project-switcher ca-session-chip';
  // "● project · Agent ▾" — the dot signals a project is active; without one
  // it reads "Select project ▾". The agent label follows after "· " so both
  // pieces of state are glanceable in the chip itself.
  chip.textContent = proj ? '● ' + proj.name + ' · ' + agentLabel + ' ▾' : 'Select project ▾';
  chip.title = proj
    ? 'Project: ' + proj.name + '  ·  Agent: ' + agentLabel + ' — click to switch'
    : 'Select a project to work on';
  chip.onclick = _caShowSessionDropdown;
  area.appendChild(chip);
}

// Small "using: <agent>" pill next to the project switcher - lets the user
// pick which coding agent this project uses. Persists via PUT /projects/
// agent; defaults to opencode for any project that's never set this, so
// every existing project's behavior is unchanged until a user explicitly
// opts a project into a different agent.
//
// Switching while a session is live detaches it first - same "hide, don't
// destroy" treatment already used for switching PROJECTS (_ocDetachAllForTab
// closes the WebSocket/disposes xterm but never touches the backend
// session/process). That keeps the pane clean without being destructive,
// and means switching back later reattaches to the SAME still-running
// session with its conversation state intact - the same "your work is
// preserved" guarantee Resume already gives for OpenCode.
// #156: the serve+attach split (instance_manager.py) repeatedly hit
// "connection problem" disconnects that a single bare process (generic_agent.
// py's OPENCODE_BARE_AGENT) doesn't reproduce - standalone or through Gator's
// own terminal bridge. opencode-bare is now the primary/default OpenCode path;
// the old serve+attach one is kept (deprecated, not removed) until enough
// runtime confirms the bare path holds up, at which point it gets yanked.
const _CA_AGENT_LABELS = {
  opencode: 'OpenCode (Deprecated)',
  'opencode-bare': 'OpenCode',
  claude: 'Claude Code',
  codex: 'Codex',
  crush: 'Crush',
  terminal: 'Terminal',
};
// "terminal" is a plain shell in the project directory - not a coding agent
// at all, but the maximally-flexible fallback for a tool that isn't in this
// list (or no tool - just wanting a shell scoped to the project).
const _CA_AGENT_OPTIONS = ['opencode-bare', 'opencode', 'claude', 'codex', 'crush', 'terminal'];

function _caAgentHasLiveSession(agent) {
  if (typeof _activeTabId === 'undefined') return false;
  return agent === 'opencode'
    ? typeof _ocIsTerminalMounted === 'function' && _ocIsTerminalMounted(_activeTabId)
    : typeof _genAgentIsTerminalMounted === 'function' &&
        _genAgentIsTerminalMounted(_activeTabId, agent);
}

// Detaches (never destroys) BOTH agent modules' state for this tab, so the
// pane is clean before showing a different agent's prompt. Unconditional on
// purpose, not just "whichever agent is current": a project can hop through
// more than one agent (e.g. terminal -> opencode -> claude), and only ever
// detaching the single most-recent one leaves earlier hops' state stranded -
// real bug found via user report, switching opencode -> claude showed a
// stale leftover Terminal session because an earlier terminal -> opencode
// switch never touched _genAgentTerminals at all. Both detach calls are
// no-ops when there's nothing mounted, so doing both unconditionally is safe
// and removes this whole class of bug rather than chasing each hop.
function _caDetachCurrentAgentTab() {
  if (typeof _activeTabId === 'undefined') return;
  if (typeof _ocDetachAllForTab === 'function') _ocDetachAllForTab(_activeTabId);
  if (typeof _genAgentDetachAllForTab === 'function') _genAgentDetachAllForTab(_activeTabId);
}

// Unified dropdown for the session selector — two labeled sections in one
// menu: PROJECT (switch / add) then CODING AGENT (per-project, persists via
// PUT /projects/agent). Replaces the former separate _caShowProjectDropdown
// and _caShowAgentDropdown so the user picks both halves of a session from a
// single affordance. The project list and agent list logic are unchanged from
// those two functions — only the container is merged.
function _caShowSessionDropdown() {
  document.querySelector('.ca-project-dropdown')?.remove();

  // If projects haven't loaded yet, load them first then re-show.
  if (_caProjects.length === 0) {
    _caLoadProjects().then(() => _caShowSessionDropdown());
    return;
  }

  const dropdown = document.createElement('div');
  dropdown.className = 'ca-project-dropdown';

  // ── Section: PROJECT ───────────────────────────────────────────────
  const projHeader = document.createElement('div');
  projHeader.className = 'ca-project-section';
  projHeader.textContent = 'PROJECT';
  dropdown.appendChild(projHeader);

  _caProjects.forEach((p) => {
    const item = document.createElement('div');
    const isCurrent = p.name === _caActiveProject;
    item.className = 'ca-project-item' + (isCurrent ? ' ca-project-item--active' : '');
    item.textContent = (isCurrent ? '● ' : '') + p.name;
    if (isCurrent) {
      item.title = 'Current project';
      item.style.cursor = 'default';
    } else if (!_caActiveProject) {
      item.title = 'Select ' + p.name;
      item.onclick = () => {
        dropdown.remove();
        _caSetActiveProject(p.name);
      };
    } else {
      // Switching from an existing project — open in a new browser tab.
      item.title = 'Open ' + p.name + ' in a new browser tab';
      item.onclick = () => {
        dropdown.remove();
        const _newUrl = new URL(window.location.href);
        _newUrl.search = '';
        _newUrl.searchParams.set('open_project', p.name);
        window.open(_newUrl.toString(), '_blank');
      };
    }
    dropdown.appendChild(item);
  });

  const addDivider = document.createElement('div');
  addDivider.className = 'ca-project-divider';
  dropdown.appendChild(addDivider);

  const addItem = document.createElement('div');
  addItem.className = 'ca-project-item ca-project-add';
  addItem.textContent = '+ Add app';
  addItem.onclick = () => {
    dropdown.remove();
    _caAddLocalProject();
  };
  dropdown.appendChild(addItem);

  // ── Section: CODING AGENT ──────────────────────────────────────────
  // Only meaningful once a project is selected — the agent is a per-project
  // setting (PUT /projects/agent needs a project name). Hide the whole section
  // when no project is active so the menu doesn't show inert choices.
  const activeProj = _caActiveProject ? _caProjects.find((p) => p.name === _caActiveProject) : null;
  if (activeProj) {
    const agentHeader = document.createElement('div');
    agentHeader.className = 'ca-project-section';
    agentHeader.textContent = 'CODING AGENT';
    dropdown.appendChild(agentHeader);

    const current = _caProjectAgent(activeProj);
    _CA_AGENT_OPTIONS.forEach((agent) => {
      const item = document.createElement('div');
      const isCurrent = agent === current;
      item.className = 'ca-project-item' + (isCurrent ? ' ca-project-item--active' : '');
      item.textContent = (isCurrent ? '● ' : '') + (_CA_AGENT_LABELS[agent] || agent);
      if (isCurrent) {
        item.style.cursor = 'default';
      } else {
        item.onclick = async () => {
          dropdown.remove();
          const headers =
            typeof _caHeadersAsync === 'function'
              ? await _caHeadersAsync()
              : { 'Content-Type': 'application/json' };
          try {
            const resp = await fetch('/api/code_agent/projects/agent', {
              method: 'PUT',
              headers,
              body: JSON.stringify({ name: activeProj.name, agent }),
            });
            if (!resp.ok) {
              alert('Could not change the coding agent for this project.');
              return;
            }
            // Detach (never destroy) BOTH agent modules' state BEFORE switching,
            // same "hide, don't destroy" treatment as switching projects - keeps
            // the pane clean without killing anything, and means switching back
            // later reattaches to a still-running session rather than losing it.
            _caDetachCurrentAgentTab();
            activeProj.agent = agent;
            _caRenderProjectSwitcher(_caActiveProject, _caProjects);
            // Re-show the Start/Resume prompt for the newly-selected agent —
            // otherwise it stays rendered for the PREVIOUS agent (e.g.
            // "Launch OpenCode for X" left showing after switching to Claude).
            if (
              typeof _activeTabId !== 'undefined' &&
              typeof _caShowAgentStartOrTerminal === 'function' &&
              activeProj.repo_path
            ) {
              _caShowAgentStartOrTerminal(_activeTabId, activeProj, activeProj.repo_path);
            }
          } catch (_) {
            alert('Could not change the coding agent for this project.');
          }
        };
      }
      dropdown.appendChild(item);
    });
  }

  document.body.appendChild(dropdown);

  // Position below the chip.
  const chip = document.querySelector('.ca-session-chip');
  if (chip) {
    const rect = chip.getBoundingClientRect();
    dropdown.style.top = rect.bottom + 4 + 'px';
    dropdown.style.left = rect.left + 'px';
  }

  // Close on outside click.
  const _close = (e) => {
    if (!dropdown.contains(e.target) && !e.target.classList.contains('ca-project-switcher')) {
      dropdown.remove();
      document.removeEventListener('click', _close);
    }
  };
  setTimeout(() => document.addEventListener('click', _close), 0);
}

function _caSetActiveProject(name) {
  document.querySelector('.ca-project-dropdown')?.remove();

  // If the project is actually changing, tear down the current session completely.
  // A session is bound to a repo at creation time — switching projects means the
  // old session would submit follow-ups to the wrong repo.
  if (name !== _caActiveProject && typeof _activeTabId !== 'undefined') {
    // Detach (don't discard) the OpenCode terminal - the actual session
    // binding for the OLD project is kept (see _ocOnProjectSwitch), so
    // switching back to it later can still reattach.
    if (typeof _ocOnProjectSwitch === 'function') {
      _ocOnProjectSwitch(_activeTabId);
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
        // A ?open_project= landing is a task handoff (already an explicit user
        // action elsewhere) — flag it so the render path auto-starts/surfaces
        // the seeded session instead of showing the Start prompt.
        window._ocHandoffAutoStart = true;
        // Clean the URL param so refreshing doesn't re-trigger
        try {
          const url = new URL(window.location);
          url.searchParams.delete('open_project');
          history.replaceState({}, '', url);
        } catch (_) {}
      } else if (!_caActiveProject) {
        // Auto-select if only one project exists
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
        <button class="ca-btn-decline" onclick="this.closest('.ca-inline-prompt').remove()">Cancel</button>
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
      <button class="ca-btn-secondary" onclick="this.closest('.ca-error-state').remove()">Dismiss</button>
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
