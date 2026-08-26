const { app, BrowserWindow, WebContentsView, session, Menu, shell, ipcMain } = require('electron');
const { applyMediaPermissions } = require('./media-permissions');
const { applyNavigationPolicy, setToolbarAttacher } = require('./navigation-policy');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');

// AI Gator — Electron shell with tiled WebContentsViews.
//
// Why tiled (not overlapping): WebContentsView is a composited surface. When
// two overlap, the one behind gets visibilityState:hidden and doesn't paint.
// Tiling (side by side, no overlap) is the only layout that works.
//
// Why WebContentsView (not <webview>): <webview> is an OOPIF under the hood,
// so Slack's JS detects it's framed (window.top !== window.self) and refuses
// to boot. WebContentsView is a genuine top-level document — Slack loads fully.
// Teams works the same way.
//
// Layout: Gator fills the window. When an external app pane (Slack or Teams)
// is active, Gator shrinks to leave room. Only ONE external app is visible at
// a time — activeExternalApp tracks which ('slack'|'teams'|null).
//
// Pin injection (hardened — per 3-agent review consensus):
//   - Injected ONCE on app dom-ready (sentinel guard prevents double-inject)
//   - Self-managing module: debounced MutationObserver + 2s safety-net interval
//   - Idempotent scan: only creates/moves header button if missing or misplaced
//   - Context updates via __gatorSetCtx (lightweight, no re-injection)
//   - Pin clicks set window.__gatorPinCtx (polled by shell, forwarded to Gator)
//   - dispatchCtx() → Gator's page is SEPARATE from in-app context updates
//
// Teams-specific note (confirmed via spike/native-teams-pane/):
//   - Entry URL must be /v2, not bare domain (bare -> /error/eoa wall)
//   - Teams' /v2 hard-blocks any UA containing "Electron" — strip those tokens
//     via buildNonElectronUA() (opposite of Slack's append pattern)
//   - Teams never updates location.href on chat/channel navigation — all
//     context comes from DOM via MutationObserver, not a URL watcher

// ── Local Network Access (Okta FastPass, Duo, any loopback-based MFA) ──────
// Chromium 130+ (Electron 43) gates "Local Network Access" — pages talking to
// localhost/private-IP services — behind a new permission that defaults to
// block inside embedded contexts. Enterprise MFA that uses a local helper
// (Okta Verify FastPass, some Duo/Ping flows) needs this to reach its on-device
// agent, otherwise sign-in fails with "The browser is blocking communication
// with Okta Verify". This is generic across enterprises/IdPs, not AMD-specific.
// Disable the blocking checks so the loopback handshake succeeds, matching how
// a normal desktop browser (with the permission granted) behaves.
app.commandLine.appendSwitch(
  'disable-features',
  'LocalNetworkAccessChecks,LocalNetworkAccessPermissionPrompt,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights,PrivateNetworkAccessRespectPreflightResults',
);

const IS_MAC = process.platform === 'darwin';
const IS_WINDOWS = process.platform === 'win32';

// Brand the app identity as "AI Gator" (not the default "Electron"). This is
// what Windows shows in Settings → Installed apps and Task Manager, what macOS
// shows in the menu bar, and what app.getPath('userData') resolves under. MUST
// run before the first app.getPath/setPath call below so userData lands under
// "AI Gator" rather than "Electron". Without this the raw Electron runtime
// registers itself as "Electron".
app.setName('AI Gator');

// SPAWN_BACKEND: only spawn a backend if the packaged sidecar or .venv python
// exists AND no GATOR_URL env is set. In dev, a separately supplied URL skips spawn.
const _devPythonPath = IS_WINDOWS
  ? path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe')
  : path.join(__dirname, '..', '.venv', 'bin', 'python');
const _packagedBackendPath = app.isPackaged
  ? path.join(
      process.resourcesPath,
      'backend',
      IS_WINDOWS ? 'aigator-backend.exe' : 'aigator-backend',
    )
  : '';
const _backendAvailable = (() => {
  const candidate = app.isPackaged ? _packagedBackendPath : _devPythonPath;
  try {
    fs.accessSync(candidate);
    return true;
  } catch {
    return false;
  }
})();
const SPAWN_BACKEND = !process.env.GATOR_URL && _backendAvailable;
const GATOR_PORT = app.isPackaged ? 8000 : 8002;
const GATOR_URL = process.env.GATOR_URL || `http://127.0.0.1:${GATOR_PORT}`;
const EXPECTED_API_CONTRACT = '2026-08-17-pins-chat-v1';

// Dev marker: the dev launchers (dev-shell.ps1 / launch-dev.ps1) set GATOR_DEV
// so a dev window is instantly distinguishable from the stable app (both look
// identical otherwise). Prod never sets it. We show it in the window title only;
// no icon/behavior change. Include the backend port so multiple dev instances
// are also distinguishable from each other.
const IS_DEV = !!process.env.GATOR_DEV;
const WINDOW_TITLE = IS_DEV ? `AI Gator [DEV] :${new URL(GATOR_URL).port || '?'}` : 'AI Gator';

// Isolate the userData profile per backend port BEFORE anything (including
// requestSingleInstanceLock below) touches it. Without this, a stable
// instance (port 8000) and a dev instance (port 8002) launched at the same
// time both default to the same %APPDATA%/gator-shell profile — two live
// Chromium processes fighting over one cache/quota database, which is what
// produced the "Unable to create cache" / "Failed to reset the quota
// database" errors. Scoping by port gives each its own profile AND makes the
// single-instance lock below apply per-port instead of treating stable+dev
// as the same app.
const GATOR_PORT_FOR_PROFILE = new URL(GATOR_URL).port || '8000';
app.setPath(
  'userData',
  path.join(app.getPath('userData'), '..', `gator-shell-${GATOR_PORT_FOR_PROFILE}`),
);

// Single-instance lock, scoped (via the userData path above) per backend
// port — double-launching the SAME port is deduped, while stable (8000) and
// dev (8002) keep running side by side as intended.
const _gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!_gotSingleInstanceLock) {
  app.quit();
}
app.on('second-instance', () => {
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});

const SLACK_URL = 'https://app.slack.com';
const SLACK_PARTITION = 'persist:slack';
// Teams: entry URL is /v2 (bare domain -> /error/eoa). Confirmed via spike.
const TEAMS_URL = 'https://teams.microsoft.com/v2';
const TEAMS_PARTITION = 'persist:teams';
// Outlook (OWA): loads at outlook.office.com/mail/ then redirects to
// outlook.cloud.microsoft/mail/. Confirmed via spike/native-outlook-pane/.
// Unlike Teams, OWA uses REAL URL routing (/mail/<folder>/id/<convid>).
const OUTLOOK_URL = 'https://outlook.office.com/mail/';
const OUTLOOK_PARTITION = 'persist:outlook';
// OneDrive (M365): entry via the office.com launcher, which redirects to the
// signed-in user's OneDrive for Business ({tenant}-my.sharepoint.com) after
// SSO. Same MS platform quirks as Teams/Outlook (M2 UA, M4 Trusted Types, M5
// SSO). OneDrive for Business DOES use real URL routing, so deep-link Open
// works via loadURL (like Outlook, unlike Teams). Confirm the entry redirect
// and selectors via a live spike before adding the pin module (Phase 2).
const ONEDRIVE_URL = 'https://www.office.com/launch/onedrive';
const ONEDRIVE_PARTITION = 'persist:onedrive';
// OneNote (M365): entry via onenote.com, which redirects to the signed-in
// user's OneNote on Office.com / {tenant}-my.sharepoint.com after SSO. Same MS
// platform quirks as Teams/Outlook/OneDrive (M2 UA, M4 Trusted Types, M5 SSO).
// OneNote for the web DOES use real URL routing (per-page URLs), so deep-link
// Open works via loadURL (like Outlook/OneDrive, unlike Teams).
const ONENOTE_URL = 'https://www.onenote.com/notebooks';
const ONENOTE_PARTITION = 'persist:onenote';
// Confluence + Jira (Atlassian Cloud): entry URLs are tenant-specific
// (e.g. https://amd.atlassian.net/wiki, https://amd-hub.atlassian.net/jira).
// Read from /api/config at startup — not hardcoded. Atlassian Cloud uses
// cookie-based SSO (not M365), so persist:confluence/persist:jira sessions
// hold the login. No buildNonElectronUA needed (Atlassian doesn't block
// Electron). No onCrossAppNav needed (no M365 app launcher).
let CONFLUENCE_URL = '';
let CONFLUENCE_PARTITION = 'persist:confluence';
let JIRA_URL = '';
let JIRA_PARTITION = 'persist:jira';
// GitHub: entry URL from config (github.com or github.enterprise.com).
// Cookie-based SSO via persist:github. No buildNonElectronUA (GitHub doesn't
// block Electron). No onCrossAppNav (no M365 app launcher).
let GITHUB_URL = '';
let GITHUB_PARTITION = 'persist:github';
function normalizeWebUrl(value) {
  const trimmed = String(value || '')
    .trim()
    .replace(/\/$/, '');
  if (!trimmed) return '';
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}
// Fetched once at startup from the backend config.
let _appConfig = null;
function _fetchAppConfig() {
  try {
    const url = GATOR_URL.replace(/\/$/, '') + '/api/config';
    const data = JSON.parse(
      require('child_process').execSync(`curl -s "${url}"`, { encoding: 'utf-8', timeout: 5000 }),
    );
    _appConfig = data;
    if (data.confluence_base_url) CONFLUENCE_URL = data.confluence_base_url;
    if (data.jira_base_url) {
      JIRA_URL = data.jira_base_url.replace(/\/$/, '');
      if (!JIRA_URL.endsWith('/jira')) JIRA_URL += '/jira';
    }
    if (data.github_base_url) {
      GITHUB_URL = normalizeWebUrl(data.github_base_url);
    }
    if (data.theme) {
      _effectiveTheme = _resolveTheme(data.theme);
    }
  } catch (e) {
    // Config not available yet — views will be created but won't load until
    // config is set. The user can still sign in via Settings.
  }
}

// ── Theme tracking ───────────────────────────────────────────────────────
// The Gator renderer's ThemeManager owns the user's theme choice ('system',
// 'light', 'dark'). It PATCHes /api/config and sets data-theme on its own
// <html>. The toolbar (separate WebContentsView, different origin) can't see
// either, so main.js tracks the effective theme and forwards it via IPC.
let _effectiveTheme = 'dark';

function _resolveTheme(choice) {
  if (choice === 'light') return 'light';
  if (choice === 'dark') return 'dark';
  // 'system' — resolve via the OS prefers-color-scheme. Electron's
  // nativeTheme is the authoritative source (not matchMedia, which runs in
  // the renderer and may differ from the toolbar's process).
  const { nativeTheme } = require('electron');
  return nativeTheme.shouldUseDarkColors ? 'dark' : 'light';
}

function _pushThemeToToolbar() {
  if (!toolbarView || !toolbarView.webContents || toolbarView.webContents.isDestroyed()) return;
  try {
    toolbarView.webContents.send('toolbar:theme', _effectiveTheme);
  } catch {}
}

// ── Child-window toolbar attachment ──────────────────────────────────────
// Attaches a toolbar WebContentsView (back/forward/reload + URL bar + window
// controls) to a child BrowserWindow (file-open popouts, SSO popups, etc.).
// The toolbar overlays the top of the child window; the page content is
// padded down via insertCSS so it's not covered.
//
// IPC disambiguation: toolbar.html always sends on global 'toolbar:*' channels.
// Handlers check event.sender.id against the child toolbar's webContents ID so
// they only act when the IPC came from THIS child's toolbar (not the main
// window's toolbar or another child). Window controls use per-child channels
// ('child-win:*:<id>') injected via executeJavaScript after dom-ready.
//
// Returns a cleanup function (call on window close) that removes listeners.
function attachToolbarToWindow(childWin) {
  if (!childWin || childWin.isDestroyed()) return () => {};

  const childToolbar = new WebContentsView({
    webPreferences: {
      preload: path.join(__dirname, 'toolbar-preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  childToolbar.webContents.loadFile(path.join(__dirname, 'toolbar.html'));
  childWin.contentView.addChildView(childToolbar);

  const childWc = childWin.webContents;
  const tbWc = childToolbar.webContents;
  const tbWcId = tbWc.id;
  const TB_H = TOOLBAR_H;
  const suffix = String(tbWcId);

  // Layout: toolbar fills the top strip. The child window's own webContents
  // fills the whole window — we can't setBounds on it. Instead, pad the page
  // body via CSS so content starts below the toolbar.
  function layoutChild() {
    if (childWin.isDestroyed()) return;
    const [w] = childWin.getContentSize();
    try {
      childToolbar.setBounds({ x: 0, y: 0, width: w, height: TB_H });
    } catch {}
  }

  function _injectPadding() {
    if (childWin.isDestroyed() || childWc.isDestroyed()) return;
    try {
      childWc.insertCSS('body { margin-top: ' + TB_H + 'px !important; }');
    } catch {}
  }
  childWc.on('dom-ready', _injectPadding);

  // Push state { url, nav, loading } to the child's toolbar.
  function pushState() {
    if (tbWc.isDestroyed()) return;
    let nav = { canGoBack: false, canGoForward: false };
    let url = '';
    try {
      nav = {
        canGoBack: !!childWc.navigationHistory.canGoBack(),
        canGoForward: !!childWc.navigationHistory.canGoForward(),
      };
      url = childWc.getURL() || '';
    } catch {}
    try {
      tbWc.send('toolbar:state', { url, app: null, nav, loading: false, visible: true });
    } catch {}
  }

  // Toolbar button IPC — check sender ID to only respond to THIS child's toolbar.
  const backHandler = (e) => {
    if (e.sender.id !== tbWcId) return;
    try {
      childWc.navigationHistory.goBack();
    } catch {}
  };
  const fwdHandler = (e) => {
    if (e.sender.id !== tbWcId) return;
    try {
      childWc.navigationHistory.goForward();
    } catch {}
  };
  const reloadHandler = (e) => {
    if (e.sender.id !== tbWcId) return;
    try {
      childWc.reload();
    } catch {}
  };
  const hardReloadHandler = (e) => {
    if (e.sender.id !== tbWcId) return;
    try {
      childWc.reloadIgnoringCache();
    } catch {}
  };
  const openBrowserHandler = (e, url) => {
    if (e.sender.id !== tbWcId) return;
    if (typeof url === 'string' && /^https:\/\//.test(url)) {
      try {
        shell.openExternal(url);
      } catch {}
    }
  };
  const readyHandler = (e) => {
    if (e.sender.id !== tbWcId) return;
    pushState();
    try {
      tbWc.send('toolbar:theme', _effectiveTheme);
    } catch {}
  };

  ipcMain.on('toolbar:back', backHandler);
  ipcMain.on('toolbar:forward', fwdHandler);
  ipcMain.on('toolbar:reload', reloadHandler);
  ipcMain.on('toolbar:hard-reload', hardReloadHandler);
  ipcMain.on('toolbar:open-in-browser', openBrowserHandler);
  ipcMain.on('toolbar:ready', readyHandler);

  // Window controls — override the toolbar preload's methods via per-child
  // channels so minimize/maximize/close target THIS child window, not the main.
  childToolbar.webContents.once('dom-ready', () => {
    try {
      childToolbar.webContents.executeJavaScript(
        '(function(){var t=window.gatorToolbar;if(!t)return;var s=' +
          JSON.stringify(suffix) +
          ';t.minimize=function(){return t.invoke("child-win:minimize:"+s)};' +
          't.maximizeToggle=function(){return t.invoke("child-win:maximize-toggle:"+s)};' +
          't.close=function(){return t.invoke("child-win:close:"+s)};' +
          't.isMaximized=function(){return t.invoke("child-win:is-maximized:"+s)};})();',
      );
    } catch {}
  });
  ipcMain.handle('child-win:minimize:' + suffix, () => {
    try {
      childWin.minimize();
    } catch {}
  });
  ipcMain.handle('child-win:maximize-toggle:' + suffix, () => {
    try {
      if (childWin.isMaximized()) {
        childWin.unmaximize();
        return false;
      }
      childWin.maximize();
      return true;
    } catch {
      return false;
    }
  });
  ipcMain.handle('child-win:close:' + suffix, () => {
    try {
      childWin.close();
    } catch {}
  });
  ipcMain.handle(
    'child-win:is-maximized:' + suffix,
    () => !!(childWin && !childWin.isDestroyed() && childWin.isMaximized()),
  );

  // Nav event listeners on the child's webContents.
  const onDidNavigate = () => pushState();
  const onDidNavigateInPage = () => pushState();
  const onDidStartLoading = () => {
    if (!tbWc.isDestroyed()) {
      try {
        tbWc.send('toolbar:state', { loading: true });
      } catch {}
    }
  };
  const onDidStopLoading = () => {
    if (!tbWc.isDestroyed()) {
      try {
        tbWc.send('toolbar:state', { loading: false });
      } catch {}
    }
    pushState();
  };
  childWc.on('did-navigate', onDidNavigate);
  childWc.on('did-navigate-in-page', onDidNavigateInPage);
  childWc.on('did-start-loading', onDidStartLoading);
  childWc.on('did-stop-loading', onDidStopLoading);

  childWin.on('resize', layoutChild);

  // Poll nav state at 500ms for live back/forward enable/disable.
  const navPoll = setInterval(() => {
    if (childWin.isDestroyed() || tbWc.isDestroyed()) return;
    pushState();
  }, 500);

  layoutChild();

  let cleaned = false;
  function cleanup() {
    if (cleaned) return;
    cleaned = true;
    clearInterval(navPoll);
    try {
      ipcMain.removeListener('toolbar:back', backHandler);
    } catch {}
    try {
      ipcMain.removeListener('toolbar:forward', fwdHandler);
    } catch {}
    try {
      ipcMain.removeListener('toolbar:reload', reloadHandler);
    } catch {}
    try {
      ipcMain.removeListener('toolbar:hard-reload', hardReloadHandler);
    } catch {}
    try {
      ipcMain.removeListener('toolbar:open-in-browser', openBrowserHandler);
    } catch {}
    try {
      ipcMain.removeListener('toolbar:ready', readyHandler);
    } catch {}
    try {
      ipcMain.removeHandler('child-win:minimize:' + suffix);
    } catch {}
    try {
      ipcMain.removeHandler('child-win:maximize-toggle:' + suffix);
    } catch {}
    try {
      ipcMain.removeHandler('child-win:close:' + suffix);
    } catch {}
    try {
      ipcMain.removeHandler('child-win:is-maximized:' + suffix);
    } catch {}
    try {
      childWc.removeListener('did-navigate', onDidNavigate);
    } catch {}
    try {
      childWc.removeListener('did-navigate-in-page', onDidNavigateInPage);
    } catch {}
    try {
      childWc.removeListener('did-start-loading', onDidStartLoading);
    } catch {}
    try {
      childWc.removeListener('did-stop-loading', onDidStopLoading);
    } catch {}
  }
  childWin.on('closed', cleanup);

  return cleanup;
}

// Register the toolbar attacher so navigation-policy.js calls it on every
// child window (file-open popouts, SSO popups, same-host popouts) without
// needing to pass it per-view at each applyNavigationPolicy call site.
setToolbarAttacher(attachToolbarToWindow);

// Gator's enforced minimum width in split mode (also the floor the drag handle
// stops at — see the extTileWidth clamps below, all of which resolve to
// `windowWidth - GATOR_MIN_WIDTH` as the ceiling for how wide the external
// app tile can grow). Used as the FIRST-LAUNCH default too: before the user
// has ever dragged (i.e. no persisted 'tp-pane-width' yet, see app.js's
// DOMContentLoaded restore), the external app should default to maximized —
// Gator only as wide as its minimum — rather than the old fixed 560px, which
// produced a near-50/50 (or worse) split on a fresh install.
const GATOR_MIN_WIDTH = 400;
const EXT_TILE_WIDTH_DEFAULT = 560;
let extTileWidth = EXT_TILE_WIDTH_DEFAULT;

// Teams' /v2 client hard-blocks any UA containing "Electron" (confirmed via
// spike A/B testing — opposite of Slack which needs an append). Strip
// Electron's app-name and Electron/<ver> tokens at runtime so it
// self-adjusts across Electron/Chromium version bumps.
function buildNonElectronUA(ses) {
  return ses
    .getUserAgent()
    .replace(/\s*[^\s/]+\/[\d.]+\s+(?=Chrome\/)/, ' ')
    .replace(/\s*Electron\/[\d.]+/i, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

// ── Shell layout config ─────────────────────────────────────────────────
// STICKY_RIGHT_RAIL: when true, the Smart Dock (right rail) stays visible
// and clickable even in "app-full" mode (Slack shown full-screen, Gator
// hidden) by reserving DOCK_W pixels for Gator instead of squeezing it down
// to nothing. Flip to false to restore the old fully-hidden behavior.
// DOCK_W must stay in sync with --dock-w in web/static/style.css.
const STICKY_RIGHT_RAIL = true;
const DOCK_W = 56;

// ── Native-pane toolbar ──────────────────────────────────────────────────
// A slim browser-style bar (back / forward / reload + read-only URL + app
// badge + overflow menu) shown ABOVE the native external app pane when one is
// active. Hidden entirely when Gator is solo (no external app) so it never
// clutters the chat-only experience.
//
// Why a separate WebContentsView (not HTML inside the Gator renderer): the
// Gator renderer doesn't know the native app's URL — getURL() lives on the
// main-process webContents. A separate view lets us own the bar's lifecycle,
// keep it visually flush with the native pane's left edge, and hide it
// cleanly without fighting Gator's topbar z-index/layout.
const TOOLBAR_H = 40;

// Persist the last Slack workspace URL so we skip the chooser on restart.
const SLACK_LAST_URL_FILE = path.join(app.getPath('userData'), 'slack-last-url.txt');
function getLastSlackUrl() {
  try {
    const url = fs.readFileSync(SLACK_LAST_URL_FILE, 'utf8').trim();
    if (url && url.includes('/client/')) return url;
  } catch {}
  return SLACK_URL;
}
function saveLastSlackUrl(url) {
  if (url && url.includes('/client/')) {
    try {
      fs.writeFileSync(SLACK_LAST_URL_FILE, url);
    } catch {}
  }
}

// Helper: return the WebContentsView for the given app name, or null.
function viewForApp(appName) {
  if (appName === 'slack') return slackView;
  if (appName === 'teams') return teamsView;
  if (appName === 'outlook') return outlookView;
  if (appName === 'onedrive') return onedriveView;
  if (appName === 'onenote') return onenoteView;
  if (appName === 'confluence') return confluenceView;
  if (appName === 'jira') return jiraView;
  if (appName === 'github') return githubView;
  return null;
}

// ── Native-pane toolbar state push ────────────────────────────────────────
// Sends the current { url, app, nav, loading, visible } snapshot to the
// toolbar view. Called on active-app changes, navigation events, and the
// toolbar's own :ready handshake. Cheap to call often — the toolbar's IPC
// handler is idempotent and diffs internally.
function _toolbarPushState() {
  if (!toolbarView || !toolbarView.webContents || toolbarView.webContents.isDestroyed()) return;
  const app = activeExternalApp;
  const view = viewForApp(app);
  const wc = view && !view.webContents.isDestroyed() ? view.webContents : null;
  let nav = { canGoBack: false, canGoForward: false };
  let url = '';
  if (wc) {
    try {
      nav = {
        canGoBack: !!wc.navigationHistory.canGoBack(),
        canGoForward: !!wc.navigationHistory.canGoForward(),
      };
      url = wc.getURL() || '';
    } catch {}
  }
  const state = {
    url,
    app,
    nav,
    loading: false,
    visible: !!app,
  };
  try {
    toolbarView.webContents.send('toolbar:state', state);
  } catch {}
}

// Attach navigation/load listeners to an external view so the toolbar
// reflects URL changes and loading state live. Called once per view at
// creation. We also push state from the 500ms nav-state poller (below) so
// back/forward button enable/disable stays fresh even if events are missed.
function _attachToolbarListeners(view, appName) {
  if (!view || !view.webContents) return;
  const wc = view.webContents;
  wc.on('did-start-loading', () => {
    if (activeExternalApp === appName && toolbarView && !toolbarView.webContents.isDestroyed()) {
      toolbarView.webContents.send('toolbar:state', { loading: true });
    }
  });
  wc.on('did-stop-loading', () => {
    if (activeExternalApp === appName && toolbarView && !toolbarView.webContents.isDestroyed()) {
      toolbarView.webContents.send('toolbar:state', { loading: false });
    }
    _toolbarPushState();
  });
  wc.on('did-navigate', () => {
    if (activeExternalApp === appName) _toolbarPushState();
  });
  wc.on('did-navigate-in-page', () => {
    if (activeExternalApp === appName) _toolbarPushState();
  });
}

// M365 app launcher (waffle) cross-app navigation guard.
// Outlook/OneDrive/OneNote all share the M365 app launcher — clicking it
// navigates to a DIFFERENT app's URL WITHIN the current WebContentsView. That
// breaks pinning (wrong source/forwarder), deep-link Open (wrong pane), and
// HITL. This classifies the post-navigate URL; if it belongs to a DIFFERENT app
// than the view's home, the URL is redirected to the CORRECT app's view, the
// active app is switched, and the original view is restored to its home URL.
// Teams is NOT affected (it never changes location.href — M3).
function classifyM365App(url) {
  try {
    const u = new URL(url);
    const h = u.hostname.toLowerCase();
    const p = u.pathname.toLowerCase();
    // officeapps.live.com = Office file editor (Word/Excel/PPT/OneNote inline) —
    // NOT an app switch; stays in whichever view opened it.
    if (h.endsWith('officeapps.live.com')) return null;
    // Outlook
    if (
      (h.endsWith('outlook.office.com') ||
        h.endsWith('outlook.cloud.microsoft') ||
        h.endsWith('outlook.office365.com')) &&
      p.startsWith('/mail')
    )
      return 'outlook';
    // Teams
    if (h.endsWith('teams.microsoft.com')) return 'teams';
    // OneNote
    if (h.endsWith('onenote.com') || h.endsWith('onenote.cloud.microsoft')) return 'onenote';
    // OneDrive
    if (h.endsWith('onedrive.live.com') || h.endsWith('onedrive.cloud.microsoft'))
      return 'onedrive';
    // sharepoint.com — shared between OneDrive and OneNote. Classify ONLY by
    // explicit path markers, NOT by ?source=waffle (both apps land on a
    // sharepoint waffle page, so that would cause false cross-app redirects).
    if (h.endsWith('sharepoint.com')) {
      if (p.includes('onedrive.aspx') || p === '/my' || p.startsWith('/my/')) return 'onedrive';
      if (p.includes('onenote')) return 'onenote';
      // Doc.aspx / SitePages = OneNote page or SharePoint content — ambiguous,
      // don't redirect (let it stay in the current view).
      return null;
    }
    // office.com/launch/<app>
    if (h.endsWith('office.com') && p.startsWith('/launch/')) {
      const app = p.split('/')[2];
      if (app === 'onedrive') return 'onedrive';
      if (app === 'onenote') return 'onenote';
      if (app === 'outlook') return 'outlook';
      if (app === 'teams') return 'teams';
    }
    return null; // unknown / SSO / iframe
  } catch {
    return null;
  }
}

// The home URL for each M365 app (used to restore a view after a redirect).
const M365_HOME_URL = {
  outlook: OUTLOOK_URL,
  onedrive: ONEDRIVE_URL,
  onenote: ONENOTE_URL,
};

// The tpState.type the renderer uses for each M365 app. Outlook's pane type is
// 'email' (not 'outlook') — the skill id, not the app name. Must match what
// openThirdPane() expects, or the renderer falls through to the classic pane.
const M365_PANE_TYPE = {
  outlook: 'email',
  onedrive: 'onedrive',
  onenote: 'onenote',
};

// Build an onCrossAppNav callback for a M365 view. Returns a function(url) =>
// boolean: true if the URL belongs to a DIFFERENT app (and was redirected to
// the correct view), false if it's same-app/unknown (allow the nav).
//
// This is called from applyNavigationPolicy's will-navigate AND
// setWindowOpenHandler — BEFORE any navigation/loadURL/child-window happens, so
// there's no race. The current view stays put (the nav was blocked); the correct
// view loads the URL, becomes active, and the renderer's tpState.type is synced.
function _makeCrossAppNavGuard(homeApp) {
  return function (url) {
    const target = classifyM365App(url);
    if (!target || target === homeApp) return false; // same app or unknown
    const correctView = viewForApp(target);
    if (!correctView || !correctView.webContents || correctView.webContents.isDestroyed())
      return false;
    try {
      correctView.webContents.loadURL(url);
      activeExternalApp = target;
      layout();
      // Sync the renderer's tpState.type so dock/hide-show/settings reflect the
      // correct app. Uses M365_PANE_TYPE because Outlook's type is 'email'.
      const paneType = M365_PANE_TYPE[target] || target;
      if (gatorView && gatorView.webContents && !gatorView.webContents.isDestroyed()) {
        gatorView.webContents
          .executeJavaScript(
            "if(typeof openThirdPane==='function') openThirdPane(" +
              JSON.stringify(paneType) +
              ');',
          )
          .catch(() => {});
      }
      return true; // blocked — do not let the current view navigate
    } catch {
      return false;
    }
  };
}

let win = null;
let splashWin = null;
let gatorView = null;
let slackView = null;
let teamsView = null;
let outlookView = null;
let onedriveView = null;
let onenoteView = null;
let confluenceView = null;
let jiraView = null;
let githubView = null;
let githubViewPromise = null;
let toolbarView = null;
let pyProc = null;

function fetchCurrentAppConfig() {
  return new Promise((resolve, reject) => {
    const url = GATOR_URL.replace(/\/$/, '') + '/api/config';
    const request = http.get(url, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => {
        body += chunk;
      });
      response.on('end', () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`Config request failed (${response.statusCode})`));
          return;
        }
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });
    request.setTimeout(5000, () => request.destroy(new Error('Config request timed out')));
    request.on('error', reject);
  });
}

async function createGitHubView() {
  try {
    const data = await fetchCurrentAppConfig();
    GITHUB_URL = normalizeWebUrl(data.github_base_url);
  } catch (error) {
    console.error(`[github] could not refresh config: ${error.message}`);
    return null;
  }
  if (!GITHUB_URL || !win) return null;

  try {
    const githubSession = session.fromPartition(GITHUB_PARTITION);
    applyMediaPermissions(githubSession);
    githubView = new WebContentsView({
      webPreferences: { session: githubSession, contextIsolation: true, nodeIntegration: false },
    });
    githubView.webContents.setBackgroundThrottling(false);
    let configuredHost = '';
    try {
      configuredHost = new URL(GITHUB_URL).hostname;
    } catch {}
    const githubHomeHosts = ['github.com', 'githubusercontent.com', configuredHost].filter(Boolean);
    applyNavigationPolicy(githubView, {
      name: 'github',
      homeHosts: githubHomeHosts,
      sameHostPopupPattern: /\/compare\?|\/pulls\?|\/issues\?|\/search\?/i,
    });
    githubView.webContents.on(
      'did-fail-load',
      (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
        if (isMainFrame === false || errorCode === -3) return;
        console.error(`[github] load failed: ${errorDescription} (${errorCode}) ${validatedURL}`);
        githubView.webContents.loadURL(
          'data:text/html;charset=utf-8,' +
            encodeURIComponent(
              '<!doctype html><html><body style="font:16px system-ui;padding:32px;background:#111827;color:#f8fafc">' +
                '<h1>GitHub could not load</h1><p>Check the GitHub URL in Settings and your network connection.</p><p>' +
                String(errorDescription) +
                ' (' +
                String(errorCode) +
                ')</p></body></html>',
            ),
        );
      },
    );
    win.contentView.addChildView(githubView);
    githubView.setVisible(false);
    githubView.webContents.loadURL(GITHUB_URL).catch((error) => {
      console.error(`[github] could not navigate to ${GITHUB_URL}: ${error.message}`);
    });
    return githubView;
  } catch (error) {
    console.error(`[github] could not create native view: ${error.message}`);
    githubView = null;
    return null;
  }
}

async function ensureGitHubView() {
  if (githubView && githubView.webContents && !githubView.webContents.isDestroyed())
    return githubView;
  if (!githubViewPromise) {
    githubViewPromise = createGitHubView().finally(() => {
      githubViewPromise = null;
    });
  }
  return githubViewPromise;
}
// activeExternalApp: which external pane is currently shown ('slack'|'teams'|null).
// Only one is visible at a time — activating one hides the other.
let activeExternalApp = null;
// Dedup guard for the injected hide/show button poller (see below).
// Hoisted to module scope so the gator-pane:show/hide IPC handlers (which can
// also change Gator's visibility, e.g. from a dock click) can keep it in sync
// — otherwise a later click of the SAME button could be ignored because it'd
// report the same value as last time.
let lastHideShow = null;

function startBackend() {
  if (!SPAWN_BACKEND) return;
  const executable = app.isPackaged ? _packagedBackendPath : _devPythonPath;
  const args = app.isPackaged
    ? ['--port', String(GATOR_PORT)]
    : ['-m', 'uvicorn', 'web.app:app', '--port', String(GATOR_PORT)];
  const backendEnv = { ...process.env, PYTHONIOENCODING: 'utf-8' };
  if (app.isPackaged && !IS_WINDOWS) {
    const runtimeDir = path.join(app.getPath('userData'), 'backend-runtime');
    fs.mkdirSync(runtimeDir, { recursive: true });
    backendEnv.TMPDIR = runtimeDir;
  }
  pyProc = spawn(executable, args, {
    cwd: app.isPackaged ? process.resourcesPath : path.join(__dirname, '..'),
    env: backendEnv,
    stdio: 'inherit',
    windowsHide: true,
  });
}

function waitForBackend(cb, tries = 60) {
  const healthUrl = GATOR_URL.replace(/\/$/, '') + '/health';
  http
    .get(healthUrl, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => {
        body += chunk;
      });
      response.on('end', () => {
        try {
          const health = JSON.parse(body);
          if (response.statusCode !== 200)
            throw new Error(`health returned ${response.statusCode}`);
          if (health.api_contract !== EXPECTED_API_CONTRACT) {
            throw new Error(
              `backend API ${health.api_contract || 'unknown'} does not match ${EXPECTED_API_CONTRACT}`,
            );
          }
          if (app.isPackaged && health.version !== app.getVersion()) {
            throw new Error(
              `backend version ${health.version || 'unknown'} does not match ${app.getVersion()}`,
            );
          }
          cb();
        } catch (error) {
          cb(error);
        }
      });
    })
    .on('error', () => {
      if (tries <= 0) return cb(new Error('backend never came up'));
      setTimeout(() => waitForBackend(cb, tries - 1), 500);
    });
}

function showStartupError(error) {
  if (splashWin && !splashWin.isDestroyed()) splashWin.close();
  splashWin = null;
  const message = String(error && error.message ? error.message : error);
  const errorWin = new BrowserWindow({
    width: 640,
    height: 360,
    title: 'AI Gator startup error',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  errorWin.loadURL(
    'data:text/html;charset=utf-8,' +
      encodeURIComponent(
        '<!doctype html><html><body style="font:16px system-ui;padding:32px;background:#111827;color:#f8fafc">' +
          '<h1>AI Gator could not start</h1><p>The desktop app and local backend do not match.</p><pre style="white-space:pre-wrap">' +
          message.replace(/[&<>"']/g, (character) => `&#${character.charCodeAt(0)};`) +
          '</pre><p>Close all AI Gator processes, reinstall the latest package, and start AI Gator again.</p></body></html>',
      ),
  );
}

function createWindow() {
  const iconPath = IS_MAC
    ? path.join(__dirname, '..', 'tray', 'aigator_icon.png')
    : path.join(__dirname, '..', 'build', 'aigator_icon.ico');
  win = new BrowserWindow({
    width: 1600,
    height: 900,
    title: WINDOW_TITLE,
    icon: iconPath,
    // Linux keeps native window decorations so users always have working
    // minimize/maximize/close controls, including during renderer startup.
    // Windows uses the custom Gator controls; macOS keeps traffic lights.
    titleBarStyle: IS_MAC ? 'hiddenInset' : IS_WINDOWS ? 'hidden' : 'default',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  win.loadURL('data:text/html,<html><body style="margin:0;background:transparent"></body></html>');

  // ── Gator view ──────────────────────────────────────────────────────
  // Gator has no explicit partition, so it (and any window.open() popup it
  // spawns — e.g. MCP OAuth connect flows like Atlassian/Rovo, Slack, Google —
  // see mcp_add_modal.js / extension_setup_modal.js) runs on Electron's
  // session.defaultSession and shares its User-Agent.
  //
  // Same class of problem as Teams (see buildNonElectronUA above): several
  // OAuth/identity providers detect and reject sign-in from a UA containing
  // "Electron/x.x.x" as a non-standard/embedded browser. Confirmed via the
  // Atlassian/Rovo MCP "Connect" flow — OAuth signup fails from the Electron
  // shell ("Signup failed") but works fine from a normal Chrome tab hitting
  // the same Gator URL. Stripping the Electron token fixes it there and
  // preemptively avoids the same failure for any future MCP whose OAuth
  // provider does similar UA sniffing.
  //
  // Safe to do for Gator's own page too: the web app never sniffs
  // navigator.userAgent for Electron detection — it uses window.gatorShell
  // (see preload.js) instead.
  const gatorSession = session.defaultSession;
  const gatorUA = buildNonElectronUA(gatorSession);
  gatorSession.setUserAgent(gatorUA);
  // session.setUserAgent()/webContents.setUserAgent() report the stripped UA
  // back correctly but do NOT reliably change the actual outgoing "User-Agent"
  // header on this Electron build (verified via CDP: navigator.userAgent and
  // the real request header both still showed "Electron/43.2.0" after both
  // calls). webRequest.onBeforeSendHeaders rewrites the wire header directly,
  // which is what an OAuth provider's server-side UA check actually inspects
  // — so it's the mechanism that must work for this fix to matter. Scoped to
  // gatorSession, so it also covers any window.open() popup spawned from
  // Gator's page that shares this session (e.g. MCP OAuth: Atlassian/Rovo,
  // Slack, Google — see mcp_add_modal.js / extension_setup_modal.js).
  gatorSession.webRequest.onBeforeSendHeaders((details, callback) => {
    details.requestHeaders['User-Agent'] = gatorUA;
    callback({ requestHeaders: details.requestHeaders });
  });

  gatorView = new WebContentsView({
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  gatorView.webContents.setWindowOpenHandler(({ url }) => {
    if (/^(https?:\/\/|mailto:)/i.test(url)) shell.openExternal(url).catch(() => {});
    return { action: 'deny' };
  });
  gatorView.webContents.loadURL(GATOR_URL);
  gatorView.webContents.on(
    'did-fail-load',
    (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
      if (isMainFrame === false || errorCode === -3) return;
      gatorView.webContents.loadURL(
        'data:text/html;charset=utf-8,' +
          encodeURIComponent(
            '<!doctype html><html><body style="font:16px system-ui;padding:32px;background:#111827;color:#f8fafc">' +
              '<h1>AI Gator could not start</h1><p>The local backend did not load.</p><p>' +
              String(errorDescription) +
              ' (' +
              String(errorCode) +
              ')</p></body></html>',
          ),
      );
    },
  );
  // Dismiss the splash screen once the Gator page has finished loading.
  // The page's own #gator-splash (renderer-side prefetch) takes over from here.
  gatorView.webContents.once('did-finish-load', () => {
    if (splashWin && !splashWin.isDestroyed()) {
      splashWin.close();
      splashWin = null;
    }
  });
  win.contentView.addChildView(gatorView);

  // ── Toolbar view (native-pane browser bar) ─────────────────────────
  // Created up-front, hidden until an external app is shown. Loads a static
  // self-contained HTML file (no backend dependency) so it paints instantly
  // and never competes with the Gator SPA for network. The toolbar uses its
  // own preload (toolbar-preload.js) exposing a minimal __gatorToolbar IPC
  // surface — kept separate from the Gator renderer's window.gatorShell API
  // so the two can't accidentally invoke each other's handlers.
  toolbarView = new WebContentsView({
    webPreferences: {
      preload: path.join(__dirname, 'toolbar-preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  toolbarView.webContents.loadFile(path.join(__dirname, 'toolbar.html'));
  win.contentView.addChildView(toolbarView);
  // Hide until an external app activates. _layoutNow() will show it.
  if (toolbarView.setVisible) toolbarView.setVisible(false);

  // ── Slack view ──────────────────────────────────────────────────────
  const slackSession = session.fromPartition(SLACK_PARTITION);
  applyMediaPermissions(slackSession);
  // DO NOT append 'Slack/x.x.x' to the UA. History:
  //   - The original code did `slackSession.userAgent = ... + ' Slack/4.51.180'`
  //     which was a silent no-op (Session has no .userAgent setter, only
  //     get/setUserAgent()). So Slack ALWAYS ran with the default Electron UA
  //     (browser mode) — and rendered fine.
  //   - Commit 6d328b5 "fixed" that to actually apply the append. That REGRESSED
  //     Slack to a blank white pane: the 'Slack/<ver>' desktop-app token makes
  //     Slack's web client boot in desktop-app mode, expecting the real Slack
  //     desktop Electron bridge (window.desktop / native IPC) which our shell
  //     doesn't provide, so it never paints.
  //   - Conclusion: the spoof was never needed. Slack works in a plain Electron
  //     WebContentsView with the default UA (browser mode). Leave the UA alone.
  // If the "unsupported browser" banner ever actually appears, prefer a
  // browser-Chrome UA (strip only the Electron/app tokens, like Teams does via
  // buildNonElectronUA) rather than adding a Slack/ desktop token.

  slackView = new WebContentsView({
    webPreferences: { session: slackSession, contextIsolation: true, nodeIntegration: false },
  });
  slackView.webContents.setBackgroundThrottling(false);
  // Generic navigation policy — same helper Teams uses. Slack's home domain is
  // slack.com; SSO hops (Google/Okta/AD/custom IdP) are allowed automatically.
  //
  // sameHostPopupPattern (INVERSE / scalable model): Slack enters a workspace
  // via unpredictable per-workspace URLs — app.slack.com/client/<team>,
  // <team>.slack.com/messages, <org>.enterprise.slack.com/, /ssb/, /get-started,
  // etc. Enumerating them all doesn't scale (every workspace has its own
  // subdomain). Instead: load ALL same-host, non-auth window.open()s into the
  // pane by default, and only let GENUINE pop-outs open their own window —
  // huddles, calls, and file/image previews. That allowlist is stable and small,
  // unlike the open-ended set of workspace entry URLs.
  applyNavigationPolicy(slackView, {
    name: 'slack',
    homeHosts: ['slack.com'],
    sameHostPopupPattern: /\/huddle\/|\/call\/|\/files\/|\/archives\/.*\/files\/|\/print\//,
  });
  slackView.webContents.loadURL(getLastSlackUrl());
  win.contentView.addChildView(slackView);
  slackView.setBounds({ x: 1599, y: 0, width: 1, height: 900 });

  // ── Teams view ──────────────────────────────────────────────────────
  // UA: strip Electron tokens (Teams /v2 hard-blocks "Electron" in UA —
  // confirmed via spike; opposite of Slack's append pattern).
  // Auth: login.microsoftonline.com is already in the SSO regex below
  // (Slack needed it too), no changes required to the allowlist.
  const teamsSession = session.fromPartition(TEAMS_PARTITION);
  applyMediaPermissions(teamsSession);
  teamsSession.setUserAgent(buildNonElectronUA(teamsSession));

  teamsView = new WebContentsView({
    webPreferences: { session: teamsSession, contextIsolation: true, nodeIntegration: false },
  });
  teamsView.webContents.setBackgroundThrottling(false);
  // Generic navigation policy — works for any enterprise / any embedded app.
  // Teams' "home" domains are Microsoft/Office; everything else reached during
  // a session (a tenant's own Okta/ADFS/Ping/custom IdP) is an SSO hop we must
  // allow, because corporate SSO redirect chains are unpredictable and
  // tenant-specific. See applyNavigationPolicy() for the full rationale.
  applyNavigationPolicy(teamsView, {
    name: 'teams',
    homeHosts: [
      'teams.microsoft.com',
      'microsoft.com',
      'office.com',
      'office365.com',
      'skype.com',
      'sfbassets.com',
      'microsoftonline.com',
      'live.com',
    ],
  });
  teamsView.webContents.loadURL(TEAMS_URL);
  win.contentView.addChildView(teamsView);
  teamsView.setBounds({ x: 1599, y: 0, width: 1, height: 900 });

  // Auto-dismiss the Teams launcher interstitial. When a /l/ deep link is
  // clicked (pin "Open"), Teams routes through /dl/launcher/launcher.html which
  // may show a "Stay better connected... / Use the web app instead" page. That
  // page is a SEPARATE document, so the click helper injected into the /v2 page
  // dies on navigation — instead, detect the launcher URL on each load here and
  // click "Use the web app instead" so navigation completes automatically.
  teamsView.webContents.on('did-finish-load', () => {
    try {
      const u = teamsView.webContents.getURL();
      if (u && u.indexOf('/dl/launcher/') !== -1) {
        teamsView.webContents
          .executeJavaScript(
            `
(function(){
  var tries = 0;
  var iv = setInterval(function(){
    tries++;
    var link = [].slice.call(document.querySelectorAll('a,button,[role="button"]')).filter(function(e){
      return /use the web app/i.test(e.textContent || '');
    })[0];
    if (link) { link.click(); clearInterval(iv); }
    else if (tries > 20) clearInterval(iv);
  }, 400);
})();
        `,
          )
          .catch(() => {});
      }
    } catch {}
  });

  // ── Teams context: DOM-only (no URL watcher — Teams /v2 never changes URL) ──
  // Spike confirmed: location.href stays at /v2 throughout all chat/channel
  // navigation. The injected MutationObserver owns all context detection.
  // Shell's only job is to dispatch whatever the injected module reports back.
  function dispatchTeamsCtx(ctx) {
    dispatchCtx(ctx, 'teams');
  }
  function updateTeamsCtx(ctx) {
    updateAppCtx(teamsView, ctx);
  }

  // ── Teams pin module: inject ONCE on dom-ready ──────────────────────
  // Selectors confirmed by spike/native-teams-pane/ passive DOM probe:
  //   header:  button[data-tid=chat-header-more-menu-trigger]
  //   message: button[data-tid=message-actions-menu-hidden-button]
  //   container: div[data-tid=chat-pane-item]
  //   thread-id: [data-track-thread-id]  -> 19:{guid}@unq.gbl.spaces
  //   msg-id:    [data-mid]              -> 13-digit epoch-ms
  //   chat-title: h2[data-tid=chat-title]
  teamsView.webContents.on('dom-ready', () => {
    if (!teamsView || !teamsView.webContents || teamsView.webContents.isDestroyed()) return;
    teamsView.webContents
      .executeJavaScript(
        `
(function() {
if (window.__gatorPinModule) return;
window.__gatorPinModule = true;

// Teams enforces Trusted Types SO strictly it blocks not just
// 'el.innerHTML = "<svg>"' but even DOMParser.parseFromString and named
// trustedTypes policies. The only fully CSP-proof way to inject an icon is to
// build every SVG node with document.createElementNS (no HTML string ever
// touches the DOM). buildSvg() takes a compact spec and returns a real
// <svg> node; setIcon() clears an element and appends it.
var SVG_NS = 'http://www.w3.org/2000/svg';
function buildSvg(spec) {
  var svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('width', spec.w);
  svg.setAttribute('height', spec.h);
  svg.setAttribute('viewBox', spec.vb);
  if (spec.style) svg.setAttribute('style', spec.style);
  (spec.children || []).forEach(function(c) {
    var el = document.createElementNS(SVG_NS, c[0]);
    var attrs = c[1];
    for (var k in attrs) { if (attrs.hasOwnProperty(k)) el.setAttribute(k, attrs[k]); }
    svg.appendChild(el);
  });
  return svg;
}
function setIcon(el, spec) {
  while (el.firstChild) el.removeChild(el.firstChild);
  el.appendChild(buildSvg(spec));
}

// Icon specs (built as real SVG DOM nodes — see buildSvg). Mirror the Slack
// icons exactly so the buttons look identical across apps.
var PIN_ICON = { w: 14, h: 14, vb: '0 0 24 24', children: [
  ['path', { d: 'M12 17v5', fill: 'none', stroke: 'white', 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }],
  ['path', { d: 'M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z', fill: 'white', stroke: 'white', 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }],
] };
var CHECK_ICON = { w: 16, h: 16, vb: '0 0 24 24', children: [
  ['polyline', { points: '20 6 9 17 4 12', fill: 'none', stroke: 'white', 'stroke-width': 3, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }],
] };
var GATOR_ICON = { w: 16, h: 16, vb: '0 0 26 26', style: 'display:block', children: [
  ['rect', { x: 1, y: 1, width: 22, height: 18, rx: 5, fill: '#16a34a' }],
  ['polygon', { points: '4,19 2,24 9,19', fill: '#16a34a' }],
  ['circle', { cx: 8.5, cy: 7.5, r: 2.2, fill: 'white' }],
  ['circle', { cx: 8.5, cy: 7.5, r: 1.1, fill: '#052e16' }],
  ['circle', { cx: 17.5, cy: 7.5, r: 2.2, fill: 'white' }],
  ['circle', { cx: 17.5, cy: 7.5, r: 1.1, fill: '#052e16' }],
  ['rect', { x: 5, y: 12, width: 16, height: 5, rx: 2.5, fill: '#15803d' }],
  ['rect', { x: 8, y: 11, width: 2, height: 2.5, rx: 0.6, fill: 'white' }],
  ['rect', { x: 12, y: 11, width: 2, height: 2.5, rx: 0.6, fill: 'white' }],
  ['rect', { x: 16, y: 11, width: 2, height: 2.5, rx: 0.6, fill: 'white' }],
] };

// Teams header buttons are visually smaller than Slack's — a 24px circle sits
// better next to Teams' compact Fluent-UI header icons than the 28px default.
var TEAMS_BTN_SIZE = 24;
// The per-message hover action bar uses ~32px buttons; a 28px green circle
// reads as one of the actions while staying visually distinct as the Gator pin.
var TEAMS_MSG_BTN_SIZE = 28;

// NOTE: Hide/show Gator is now handled by the 3-position spin logo in the
// dock (web/static/app.js _initGatorSpin). The injected hide/show button,
// gatorHidden, updateHideShowBtn, __gatorSyncHideShow, and the seq-poll
// mechanism have been removed from all three injected blocks.

// Current Teams context — updated by MutationObserver scanning DOM.
// Teams never updates the URL, so this is the ONLY source of truth.
var currentCtx = { id: null, thread_ts: null, label: null, kind: null };
window.__gatorCurrentCtx = currentCtx;
window.__gatorSetCtx = function(ctx) {
  currentCtx = ctx;
  window.__gatorCurrentCtx = ctx;
  var btn = document.getElementById('__gator_pin_header');
  if (btn) btn.title = 'Pin to Gator: ' + (ctx.kind || 'chat') + ' ' + (ctx.label || '');
};

function buildGatorBtn(id, tooltip, onClick, size) {
  var s = size || 28;
  var btn = document.createElement('button');
  if (id) btn.id = id;
  btn.title = tooltip;
  btn.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:' + s + 'px;height:' + s + 'px;border:0;border-radius:50%;background:#1f6f3f;cursor:pointer;flex-shrink:0;transition:background .15s,transform .1s;padding:0;overflow:hidden;vertical-align:middle;box-sizing:border-box;z-index:9999';
  setIcon(btn, PIN_ICON);
  btn.onmouseenter = function() { btn.style.background = '#2a8a4f'; };
  btn.onmouseleave = function() { btn.style.background = '#1f6f3f'; };
  btn.onmousedown = function() { btn.style.transform = 'scale(0.9)'; };
  btn.onmouseup = function() { btn.style.transform = 'scale(1)'; };
  btn.onclick = function(e) { e.preventDefault(); e.stopPropagation(); onClick(btn); };
  return btn;
}

// Classify a Teams thread id by its suffix (matches web/routes/teams.py taxonomy):
//   19:{guid}_{guid}@unq.gbl.spaces  -> 1:1 DM               (kind 'dm')
//   19:{guid}@thread.v2              -> group/multi chat      (kind 'chat')
//   19:{guid}@thread.tacv2 / .skype  -> team channel          (kind 'channel')
// IMPORTANT: @thread.v2 is a CHAT, not a channel. Only @thread.tacv2 and
// @thread.skype are channels. The old code treated any '@thread.' as a
// channel, which mislabeled every v2 DM/group chat as a channel.
function classifyTeamsId(id) {
  if (!id) return 'chat';
  if (id.indexOf('@unq.gbl.spaces') !== -1) return 'dm';
  if (id.indexOf('@thread.tacv2') !== -1 || id.indexOf('@thread.skype') !== -1) return 'channel';
  return 'chat';  // @thread.v2 group chats, and anything else
}

// Read current Teams context from DOM. Prefer a thread id sourced from the
// active conversation's header/main area (not the sidebar/nav, which can carry
// a different conversation's id) so pinning a DM never picks up a channel.
function readTeamsCtx() {
  // Search order: header entity area, then main content, then anywhere.
  var scopes = [
    '[data-tid="entity-header"]',
    '[data-tid="app-layout-area--main"]',
    '[data-tid="message-pane-layout"]',
  ];
  var threadEl = null;
  for (var i = 0; i < scopes.length && !threadEl; i++) {
    var scope = document.querySelector(scopes[i]);
    if (scope) threadEl = scope.querySelector('[data-track-thread-id]');
  }
  // Fallback: any element that is NOT inside the left nav/sidebar.
  if (!threadEl) {
    var all = document.querySelectorAll('[data-track-thread-id]');
    for (var j = 0; j < all.length; j++) {
      if (!all[j].closest('[data-tid="app-layout-area--nav"], [data-tid="app-layout-area--sub-nav"], [role="navigation"]')) {
        threadEl = all[j];
        break;
      }
    }
    // Do NOT fall back to all[0] — it may be a nav/sidebar element for a different conversation.
  }
  var id = threadEl ? threadEl.getAttribute('data-track-thread-id') : null;
  var titleEl = document.querySelector('h2[data-tid="chat-title"]');
  var label = titleEl ? titleEl.textContent.trim() : (id || 'Teams');
  return { id: id, label: label, kind: classifyTeamsId(id), thread_ts: null };
}

// Header click — pins the current chat/channel context.
function headerClick(b) {
  var ctx = readTeamsCtx();
  if (!ctx || !ctx.id) ctx = window.__gatorCurrentCtx || currentCtx;
  window.__gatorPinCtx = {
    channel: ctx.id,
    id: ctx.id,
    thread_ts: null,
    label: ctx.label || ctx.id,
    kind: ctx.kind || 'chat',
    ts: null,
  };
  setIcon(b, CHECK_ICON); b.style.background = '#0a4a2a';
  setTimeout(function() { setIcon(b, PIN_ICON); b.style.background = '#1f6f3f'; }, 1200);
}

// Idempotent header scan — insert pin button into Teams header.
function scanHeader() {
  var actionsEl = document.querySelector('button[data-tid="chat-header-more-menu-trigger"]');
  if (!actionsEl) return;
  var container = actionsEl.parentNode;
  if (!container) return;
  var existing = document.getElementById('__gator_pin_header');
  if (existing && existing.parentNode === container) return;
  document.querySelectorAll('#__gator_pin_header').forEach(function(el) { el.remove(); });
  var ctx = window.__gatorCurrentCtx || readTeamsCtx();
  var hdrBtn = buildGatorBtn('__gator_pin_header', 'Pin to Gator: ' + (ctx.kind || 'chat') + ' ' + (ctx.label || ''), headerClick, TEAMS_BTN_SIZE);
  hdrBtn.style.marginLeft = '4px';
  container.insertBefore(hdrBtn, actionsEl);
  // Update context each time header is scanned (covers SPA navigation).
  var fresh = readTeamsCtx();
  if (fresh.id && fresh.id !== currentCtx.id) {
    currentCtx = fresh;
    window.__gatorCurrentCtx = fresh;
    window.__gatorPinCtx = null;
  }
}

// Message pin scan — insert the pin button INTO the per-message hover action
// bar (the floating reaction/reply/more toolbar), matching Slack's placement.
//
// Teams' hover action bar is a Fluent <div role="toolbar"> containing the
// quick-reaction buttons (message-actions-like/heart/laugh/surprised),
// expanded-reactions-picker-entry, and message-actions-quoted-reply/edit. It
// renders lazily on hover; the MutationObserver catches it appearing. We
// anchor on the toolbar that contains 'message-actions-*' buttons and append
// our pin at the end (after the last native action), so it reads as one more
// action in the same bar.
function _msgActionToolbar(el) {
  // Walk up from any message-action button to its role=toolbar container.
  return el.closest('[role="toolbar"]');
}
function scanMessages() {
  // The hover toolbar's action buttons all share the 'message-actions-' prefix.
  // Find each such toolbar currently in the DOM and inject once per toolbar.
  var anchors = document.querySelectorAll(
    'button[data-tid="expanded-reactions-picker-entry"],' +
    'button[data-tid^="message-actions-"]'
  );
  var seenBars = [];
  anchors.forEach(function(anchor) {
    var bar = _msgActionToolbar(anchor);
    if (!bar) return;
    if (seenBars.indexOf(bar) !== -1) return;
    seenBars.push(bar);
    if (bar.querySelector('.__gator_pin_msg')) return;
    // Resolve the message this toolbar belongs to, to get its data-mid.
    var item = bar.closest('[data-tid="chat-pane-item"]');
    // The toolbar is sometimes a sibling/overlay of the message rather than a
    // descendant — fall back to the message the hidden-actions button marks.
    var midEl = item ? item.querySelector('[data-mid]') : null;
    if (!midEl) {
      // Overlay case: find the message currently hovered (has the visible bar).
      var hoveredItem = document.querySelector('[data-tid="chat-pane-item"]:hover');
      midEl = hoveredItem ? hoveredItem.querySelector('[data-mid]') : null;
      item = hoveredItem || item;
    }
    var mid = midEl ? midEl.getAttribute('data-mid') : null;
    if (!mid) return;
    // Resolve the parent conversation (chat/channel) id for THIS message, so the
    // pin carries a real chat_id — without it the backend can't fetch the message
    // (it produced pins like id=":<ts>" with an empty channel). Prefer the id on
    // the message's own container/subtree; fall back to the live header context.
    function _threadIdForItem(itemEl) {
      // 1. The message item (or an ancestor) may carry the thread id directly.
      var el = itemEl;
      for (var d = 0; d < 6 && el; d++) {
        var tid = el.getAttribute && el.getAttribute('data-track-thread-id');
        if (tid) return tid;
        el = el.parentElement;
      }
      // 2. Any thread-id element inside the message item.
      var inner = itemEl && itemEl.querySelector ? itemEl.querySelector('[data-track-thread-id]') : null;
      if (inner) return inner.getAttribute('data-track-thread-id');
      return null;
    }
    var msgThreadId = _threadIdForItem(item);
    // Message text for the pin label (like Slack): Teams renders each message
    // body in div[id="content-<mid>"]. Fall back to chat title + date if empty
    // (e.g. an attachment-only or system message).
    var textEl = (item ? item.querySelector('#content-' + (window.CSS && CSS.escape ? CSS.escape(mid) : mid)) : null)
              || document.getElementById('content-' + mid);
    var msgText = textEl ? (textEl.innerText || '').replace(/\\s+/g, ' ').trim() : '';
    var lbl = msgText.slice(0, 50);
    if (msgText.length > 50) lbl += '...';
    var b = buildGatorBtn('', 'Pin to Gator: ' + (lbl || ('message ' + mid)), function(btn) {
      // Resolve the chat/channel id at CLICK time (freshest), preferring the id
      // captured from this message's own subtree, then a fresh header read, then
      // the cached context. Never emit a pin without a chat id.
      var freshCtx = readTeamsCtx();
      var chatId = msgThreadId
        || (freshCtx && freshCtx.id)
        || (window.__gatorCurrentCtx && window.__gatorCurrentCtx.id)
        || (currentCtx && currentCtx.id)
        || '';
      var ctxLabel = (freshCtx && freshCtx.label) || (window.__gatorCurrentCtx && window.__gatorCurrentCtx.label) || (currentCtx && currentCtx.label) || 'Teams';
      var finalLbl = lbl || (ctxLabel + ' · message');
      if (!chatId) {
        // No conversation id resolvable — flash the button red and do NOT persist
        // a broken pin (avoids the id=":<ts>" empty-channel pins that can't be read).
        try { console.warn('[gator] Teams message pin: no chat_id resolved for mid ' + mid); } catch (e) {}
        setIcon(btn, PIN_ICON); btn.style.background = '#7f1d1d';
        setTimeout(function() { setIcon(btn, PIN_ICON); btn.style.background = '#1f6f3f'; }, 1500);
        return;
      }
      window.__gatorPinCtx = {
        channel: chatId,
        id: chatId,
        thread_ts: null,
        label: finalLbl,
        kind: 'message',
        ts: mid,
      };
      setIcon(btn, CHECK_ICON); btn.style.background = '#0a4a2a';
      setTimeout(function() { setIcon(btn, PIN_ICON); btn.style.background = '#1f6f3f'; }, 1200);
    }, TEAMS_MSG_BTN_SIZE);
    b.className = '__gator_pin_msg';
    b.setAttribute('data-gator-mid', mid);
    b.style.marginLeft = '2px';
    bar.appendChild(b);
  });
}

function scanAll() { scanHeader(); scanMessages(); }

var scanQueued = false;
var obs = new MutationObserver(function() {
  if (scanQueued) return;
  scanQueued = true;
  requestAnimationFrame(function() { scanQueued = false; scanAll(); });
});
obs.observe(document.body, { childList: true, subtree: true });

setInterval(scanAll, 2000);
setTimeout(scanAll, 500);
})();
    `,
      )
      .catch((e) => {
        try {
          fs.appendFileSync(
            path.join(__dirname, 'pin-debug.log'),
            'TEAMS INJECT ERROR: ' + e.message + '\n',
          );
        } catch {}
      });
  });

  // ── Outlook (OWA) view ───────────────────────────────────────────────
  // Same MS platform quirks as Teams: strip Electron UA, Trusted Types CSP
  // (icons via createElementNS), SSO nav/permissions. BUT unlike Teams, OWA
  // uses REAL URL routing (/mail/<folder>/id/<convid>) — so context comes from
  // a URL watcher (like Slack), and deep-link Open works via loadURL.
  // Confirmed via spike/native-outlook-pane/.
  const outlookSession = session.fromPartition(OUTLOOK_PARTITION);
  applyMediaPermissions(outlookSession);
  outlookSession.setUserAgent(buildNonElectronUA(outlookSession));

  outlookView = new WebContentsView({
    webPreferences: { session: outlookSession, contextIsolation: true, nodeIntegration: false },
  });
  outlookView.webContents.setBackgroundThrottling(false);
  applyNavigationPolicy(outlookView, {
    name: 'outlook',
    // OWA serves from both office.com and the newer cloud.microsoft domain.
    homeHosts: [
      'outlook.office.com',
      'outlook.office365.com',
      'outlook.cloud.microsoft',
      'office.com',
      'office365.com',
      'cloud.microsoft',
      'microsoft.com',
      'microsoftonline.com',
      'live.com',
    ],
    // M365 app launcher guard (M17): block cross-app navs before they happen.
    onCrossAppNav: _makeCrossAppNavGuard('outlook'),
  });
  outlookView.webContents.loadURL(OUTLOOK_URL);
  win.contentView.addChildView(outlookView);
  outlookView.setBounds({ x: 1599, y: 0, width: 1, height: 900 });

  // ── OneDrive view ────────────────────────────────────────────────────
  // Same MS platform quirks as Teams/Outlook: strip Electron UA (M2), expect
  // Trusted Types (M4 — Phase 2 pin module will use createElementNS icons),
  // allow all-https SSO hops (M5). OneDrive for Business uses REAL URL routing
  // (like Outlook, unlike Teams), so deep-link Open works via loadURL.
  const onedriveSession = session.fromPartition(ONEDRIVE_PARTITION);
  applyMediaPermissions(onedriveSession);
  onedriveSession.setUserAgent(buildNonElectronUA(onedriveSession));

  onedriveView = new WebContentsView({
    webPreferences: { session: onedriveSession, contextIsolation: true, nodeIntegration: false },
  });
  onedriveView.webContents.setBackgroundThrottling(false);
  applyNavigationPolicy(onedriveView, {
    name: 'onedrive',
    // OneDrive for Business is served from {tenant}-my.sharepoint.com and the
    // office.com launcher; SSO hops through login.microsoftonline.com etc.
    homeHosts: [
      'office.com',
      'office365.com',
      'cloud.microsoft',
      'microsoft.com',
      'microsoftonline.com',
      'live.com',
      'sharepoint.com',
    ],
    // Inverse popup model (M15): same-host, non-auth window.open()s load INTO
    // the pane by default — so clicking a file/page navigates WITHIN OneDrive
    // (back button returns to the file list), instead of spawning a child
    // Electron window. Only genuine pop-outs get their own window:
    //   - share dialog (_layouts/15/share, ?share=1)
    //   - print (?print=1, /print/)
    //   - explicit download (?download=1)
    sameHostPopupPattern:
      /\/_layouts\/15\/share|[\?&]share=1|[\?&]print=1|\/print\/|[\?&]download=1/,
    // M365 app launcher guard (M17): block cross-app navs before they happen.
    onCrossAppNav: _makeCrossAppNavGuard('onedrive'),
    // File-open interception: Office Online file viewers (Word, Excel, PPT, PDF,
    // OneNote) open in a child window so the OneDrive file list stays intact.
    // Matches Doc.aspx / WopiFrame / onenoteframe and ?action=edit/view params.
    // Folder SPA navigation (/my, /personal/…/Documents) does NOT match → stays in-pane.
    fileOpenPattern:
      /Doc\.aspx|WopiFrame\.aspx|onenoteframe\.aspx|[\?&]action=(edit|view|embedview)/i,
  });
  onedriveView.webContents.loadURL(ONEDRIVE_URL);
  win.contentView.addChildView(onedriveView);
  onedriveView.setBounds({ x: 1599, y: 0, width: 1, height: 900 });

  // ── OneDrive pin module: inject ONCE on dom-ready ───────────────────
  // Selectors confirmed via CDP spike:
  //   file row:    div[class*="filesRow"]  (virtualized — height=0 when off-screen,
  //                but DOM is present; MutationObserver catches rows as they scroll in)
  //   row name:    row.textContent (no dedicated name element — name is in a text node)
  //   row select:  input[aria-label="Select row"] (first interactive element)
  //   command bar: div[class*="commandBar"] (Sort/View/Details — header pin inserts here)
  // No Trusted Types CSP (innerHTML works), but icons use createElementNS for
  // consistency with the Outlook/Teams modules (M4 — forward-safe).
  onedriveView.webContents.on('dom-ready', () => {
    if (!onedriveView || !onedriveView.webContents || onedriveView.webContents.isDestroyed())
      return;
    onedriveView.webContents
      .executeJavaScript(
        `
(function() {
  if (window.__gatorPinModule) return;
  window.__gatorPinModule = true;

  var SVG_NS = 'http://www.w3.org/2000/svg';
  function buildSvg(spec){
    var svg = document.createElementNS(SVG_NS,'svg');
    svg.setAttribute('width',spec.w); svg.setAttribute('height',spec.h);
    svg.setAttribute('viewBox',spec.vb); if(spec.style) svg.setAttribute('style',spec.style);
    (spec.children||[]).forEach(function(c){
      var el=document.createElementNS(SVG_NS,c[0]); var a=c[1];
      for(var k in a){ if(a.hasOwnProperty(k)) el.setAttribute(k,a[k]); }
      svg.appendChild(el);
    });
    return svg;
  }
  function setIcon(el,spec){ while(el.firstChild) el.removeChild(el.firstChild); el.appendChild(buildSvg(spec)); }

  var PIN_ICON = { w:14, h:14, vb:'0 0 24 24', children:[
    ['path',{ d:'M12 17v5', fill:'none', stroke:'white', 'stroke-width':2, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
    ['path',{ d:'M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z', fill:'white', stroke:'white', 'stroke-width':2, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
  ] };

  var ONEDRIVE_BTN_SIZE = 24;

  // Context: the current folder/file being viewed. OneDrive has URL routing
  // (/my, /personal/.../Documents/...) so we read the location for context.
  var currentCtx = { id: null, label: null, kind: 'file' };
  window.__gatorCurrentCtx = currentCtx;
  window.__gatorSetCtx = function(ctx) {
    currentCtx = ctx;
    window.__gatorCurrentCtx = ctx;
  };

  function readOnedriveCtx() {
    // Best-effort: read the current folder from the breadcrumb or URL
    var label = null;
    try {
      var bc = document.querySelector('[class*="breadcrumb"], [aria-label*="breadcrumb" i]');
      if (bc) label = (bc.textContent || '').trim();
    } catch {}
    if (!label) {
      try { label = document.title.replace(/\\s*-\\s*OneDrive.*$/i, '').trim() || null; } catch {}
    }
    return { id: location.href, label: label, kind: 'folder' };
  }

  function buildGatorBtn(id, tooltip, onClick, size) {
    var s = size || ONEDRIVE_BTN_SIZE;
    var btn = document.createElement('button');
    if (id) btn.id = id;
    btn.title = tooltip;
    btn.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:' + s + 'px;height:' + s + 'px;border:0;border-radius:50%;background:#1f6f3f;cursor:pointer;flex-shrink:0;transition:background .15s,transform .1s;padding:0;overflow:hidden;vertical-align:middle;box-sizing:border-box';
    btn.addEventListener('mouseenter', function() { btn.style.background = '#22c55e'; });
    btn.addEventListener('mouseleave', function() { btn.style.background = '#1f6f3f'; });
    btn.addEventListener('mousedown', function() { btn.style.transform = 'scale(0.9)'; });
    btn.addEventListener('mouseup', function() { btn.style.transform = ''; });
    btn.addEventListener('click', function(e) { e.preventDefault(); e.stopPropagation(); onClick(btn); });
    setIcon(btn, PIN_ICON);
    return btn;
  }

  function makePinBtn(nameText, onClickFn) {
    var btn = buildGatorBtn(null, 'Pin to Gator: ' + nameText, onClickFn);
    btn.style.marginRight = '6px';
    btn.style.opacity = '0.6';
    btn.style.flexShrink = '0';
    btn.addEventListener('mouseenter', function() { btn.style.opacity = '1'; });
    btn.addEventListener('mouseleave', function() { btn.style.opacity = '0.6'; });
    return btn;
  }

  // Extract the *resolvable* OneDrive item ID from an element's attributes.
  // The Graph-resolvable ID is the itemKey (e.g. "01ABC...", a base32-ish token),
  // NOT the "SPO@{siteGuid}" prefix. The data-automationid format is
  // "row-SPO@{guid},{itemKey}" — we want the token after the comma.
  // Returns '' if no resolvable itemKey is found (caller must NOT fall back to
  // the bare SPO@guid, which is a site id, not a file id).
  function _itemIdFromAttrs(el) {
    if (!el) return '';
    // 1. data-actions carries a clean itemKey (most reliable when present)
    var actions = el.getAttribute('data-actions') || '';
    var m = actions.match(/"itemKey":"([^"]+)"/);
    if (m && m[1] && _isGraphItemId(m[1])) return m[1];
    // 2. data-automationid="row-SPO@{guid},{itemKey}" — take the part after the comma
    var aid = el.getAttribute('data-automationid') || '';
    m = aid.match(/SPO@[^,]+,\s*([^\s,"]+)/);
    if (m && m[1] && _isGraphItemId(m[1])) return m[1];
    // 3. Some layouts expose the itemKey directly as data-item-key / data-id
    var direct = el.getAttribute('data-item-key') || el.getAttribute('data-id') || '';
    if (_isGraphItemId(direct)) return direct;
    return '';
  }

  // A Graph drive-item id is base32-ish, starts with "01", >= 22 chars.
  // SharePoint base64url tokens (containing '-' or '_') are NOT Graph item ids
  // — they're internal SharePoint tokens that Graph rejects with 400.
  // Reject anything that doesn't match the strict pattern so the pin falls back
  // to a name-search resolution instead of storing a bad id.
  function _isGraphItemId(id) {
    if (!id || id.length < 22) return false;
    return /^01[A-Z0-9]{20,}$/i.test(id);
  }

  function _extractRowItemId(row) {
    return _itemIdFromAttrs(row);
  }

  function _walkUpForItemId(el) {
    for (var depth = 0; depth < 10; depth++) {
      el = el && el.parentElement;
      if (!el) break;
      var id = _itemIdFromAttrs(el);
      if (id) return id;
    }
    return '';
  }

  function pinClickHandler(btn) {
    // label and itemId were stored at injection time to avoid re-scraping the DOM.
    var label = btn.dataset.gatorLabel || btn.title.replace(/^Pin to Gator:\\s*/, '');
    var itemId = btn.dataset.gatorItemId || '';

    // Final fallback: walk the DOM if the button was injected before this code shipped.
    if (!itemId) {
      var row = btn.closest('[class*="filesRow"], [data-automationid*="row-SPO"], [class*="itemTile_"]');
      itemId = _extractRowItemId(row) || _walkUpForItemId(btn);
    }

    // Capture the file's location (SharePoint site/library name) from the row.
    var locationText = '';
    var row2 = btn.closest('[class*="filesRow"], [data-automationid*="row-"], [class*="itemTile_"]');
    if (row2) {
      var locBtn = row2.querySelector('[class*="nameCellBottom"]');
      if (locBtn) locationText = (locBtn.textContent || '').trim();
    }
    if (!locationText) {
      var bc = document.querySelector('[class*="breadcrumb"], [aria-label*="breadcrumb" i]');
      if (bc) locationText = (bc.textContent || '').trim().slice(0, 80);
    }

    // Capture the file's share link. The href of the filename link is the most
    // reliable source — it's a deep link to the file that Graph can resolve via
    // /shares/{token}/driveItem. Fall back to window.location.href (which may be
    // the OneDrive home page for some layouts, but is better than nothing).
    var shareUrl = '';
    if (row2) {
      var fileLink = row2.querySelector('a[href*="sharepoint.com"], a[href*="onedrive"], a[href*="/personal/"]');
      if (fileLink) shareUrl = fileLink.href || '';
    }
    if (!shareUrl) shareUrl = window.location.href;

    window.__gatorPinCtx = {
      id: itemId || ('onedrive:' + encodeURIComponent(label)),
      label: label,
      kind: 'file',
      web_url: shareUrl,
      location: locationText
    };
  }

  // Idempotent: scan all OneDrive layouts and inject pin buttons.
  // Three layouts exist across different views:
  //   1. My Files list view: div[class*="filesRow"] — name in [data-automationid="field-LinkFilename"]
  //   2. Home "Recent" list: [data-automationid="field-name"] — name in div.nameCellDisplay_*
  //   3. Home "For you" tiles: div[class*="itemTile"] — name in span[class*="itemTileTitle"]
  function scanRows() {
    // ── Layout 1: My Files list (filesRow / field-LinkFilename) ──────────
    var rows = document.querySelectorAll('div[class*="filesRow"]');
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (row.dataset.gatorPin === '1') continue;
      if (/header/i.test(row.className || '')) continue;
      var nameCell = row.querySelector('[data-automationid="field-LinkFilename"]');
      if (!nameCell) continue;
      // Extract just the filename from the name cell's link/button text, not the full row.
      var nameText = '';
      try {
        var nameLink = nameCell.querySelector('a, button, [role="link"]');
        nameText = ((nameLink ? nameLink.textContent : nameCell.textContent) || '').trim();
        // Strip any trailing timestamp/author noise that may have leaked in.
        nameText = nameText.split(/\s{2,}|\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s/i)[0].trim();
      } catch {}
      if (!nameText) continue;
      var rowItemId = _extractRowItemId(row) || _walkUpForItemId(nameCell);
      var pinBtn = makePinBtn(nameText, pinClickHandler);
      pinBtn.dataset.gatorLabel = nameText;
      if (rowItemId) pinBtn.dataset.gatorItemId = rowItemId;
      // nameCell is display:block — make it flex so pin + name sit side by side.
      nameCell.style.display = 'flex';
      nameCell.style.alignItems = 'center';
      nameCell.style.overflow = 'hidden';
      var nameContent = nameCell.firstElementChild;
      if (nameContent) {
        nameContent.style.minWidth = '0';
        nameContent.style.flex = '1';
        nameContent.style.overflow = 'hidden';
      }
      nameCell.insertBefore(pinBtn, nameCell.firstChild);
      row.dataset.gatorPin = '1';
    }

    // ── Layout 2: Home "Recent" list (field-name / nameCellTop) ──────────
    // nameCellDisplay is flexDirection:column — don't touch it. Instead inject
    // directly into nameCellTop (the filename button). Use only direct text nodes
    // to avoid including timestamp/author text from child elements.
    var recentCells = document.querySelectorAll('[data-automationid="field-name"]');
    for (var j = 0; j < recentCells.length; j++) {
      var cell = recentCells[j];
      if (cell.dataset.gatorPin === '1') continue;
      var nameBtn = cell.querySelector('[class*="nameCellTop"]');
      if (!nameBtn) continue;
      // Read only direct text nodes — not child element text — to get just the filename.
      var nameText = '';
      nameBtn.childNodes.forEach(function(n) {
        if (n.nodeType === 3 && n.textContent.trim()) nameText += n.textContent;
      });
      nameText = nameText.trim();
      // Fallback: if no direct text nodes, grab the first child element's text.
      if (!nameText) {
        var firstEl = nameBtn.querySelector('span, a, button');
        if (firstEl) nameText = (firstEl.textContent || '').trim();
      }
      if (!nameText) continue;
      // Extract item ID from the containing row before injecting the button.
      var containingRow = cell.closest('[data-automationid*="row-SPO"], [data-automationid*="row-"]') || cell.parentElement;
      var rowItemId = _extractRowItemId(containingRow) || _walkUpForItemId(cell);
      // Wrap existing text nodes in a span so they survive flex layout.
      var textNodes = [];
      nameBtn.childNodes.forEach(function(n) { if (n.nodeType === 3 && n.textContent.trim()) textNodes.push(n); });
      if (textNodes.length) {
        var span = document.createElement('span');
        span.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0';
        textNodes.forEach(function(n) { span.appendChild(n); });
        nameBtn.insertBefore(span, nameBtn.firstChild);
      }
      var pinBtn = makePinBtn(nameText, pinClickHandler);
      pinBtn.dataset.gatorLabel = nameText;
      if (rowItemId) pinBtn.dataset.gatorItemId = rowItemId;
      nameBtn.style.display = 'inline-flex';
      nameBtn.style.alignItems = 'center';
      nameBtn.insertBefore(pinBtn, nameBtn.firstChild);
      cell.dataset.gatorPin = '1';
    }

    // ── Layout 3: Home "For you" tiles (itemTile / itemTileTitle) ────────
    var tiles = document.querySelectorAll('[class*="itemTile_"]');
    for (var k = 0; k < tiles.length; k++) {
      var tile = tiles[k];
      if (tile.dataset.gatorPin === '1') continue;
      var titleEl = tile.querySelector('[class*="itemTileTitle"]');
      if (!titleEl) continue;
      // Use direct text nodes only to avoid child-element noise.
      var nameText = '';
      titleEl.childNodes.forEach(function(n) { if (n.nodeType === 3 && n.textContent.trim()) nameText += n.textContent; });
      nameText = nameText.trim() || (titleEl.textContent || '').trim();
      if (!nameText) continue;
      var tileItemId = _extractRowItemId(tile) || _walkUpForItemId(titleEl);
      var pinBtn = makePinBtn(nameText, pinClickHandler);
      pinBtn.dataset.gatorLabel = nameText;
      if (tileItemId) pinBtn.dataset.gatorItemId = tileItemId;
      titleEl.style.display = 'inline-flex';
      titleEl.style.alignItems = 'center';
      titleEl.insertBefore(pinBtn, titleEl.firstChild);
      tile.dataset.gatorPin = '1';
    }
  }

  function scanAll() {
    try { scanRows(); } catch(e) {
      try { /* silent — don't kill the observer */ } catch {}
    }
  }

  var scanQueued = false;
  var obs = new MutationObserver(function() {
    if (scanQueued) return;
    scanQueued = true;
    requestAnimationFrame(function() { scanQueued = false; scanAll(); });
  });
  obs.observe(document.body, { childList: true, subtree: true });

  setInterval(scanAll, 2000);
  setTimeout(scanAll, 500);
})();
    `,
      )
      .catch((e) => {
        try {
          fs.appendFileSync(
            path.join(__dirname, 'pin-debug.log'),
            'ONEDRIVE INJECT ERROR: ' + e.message + '\n',
          );
        } catch {}
      });
  });

  // ── OneNote view ─────────────────────────────────────────────────────
  // Same MS platform quirks as Teams/Outlook/OneDrive: strip Electron UA (M2),
  // expect Trusted Types (M4 — Phase 2 pin module will use createElementNS icons),
  // allow all-https SSO hops (M5). OneNote for the web uses REAL URL routing
  // (per-page URLs), so deep-link Open works via loadURL.
  const onenoteSession = session.fromPartition(ONENOTE_PARTITION);
  applyMediaPermissions(onenoteSession);
  onenoteSession.setUserAgent(buildNonElectronUA(onenoteSession));

  onenoteView = new WebContentsView({
    webPreferences: { session: onenoteSession, contextIsolation: true, nodeIntegration: false },
  });
  onenoteView.webContents.setBackgroundThrottling(false);
  applyNavigationPolicy(onenoteView, {
    name: 'onenote',
    // OneNote is served from onenote.com / office.com / {tenant}-my.sharepoint.com;
    // SSO hops through login.microsoftonline.com etc.
    homeHosts: [
      'office.com',
      'office365.com',
      'cloud.microsoft',
      'microsoft.com',
      'microsoftonline.com',
      'live.com',
      'sharepoint.com',
      'onenote.com',
    ],
    // Inverse popup model (M15): same-host, non-auth window.open()s load INTO
    // the pane by default — so clicking a page/section navigates WITHIN OneNote
    // (back button returns), instead of spawning a child Electron window. Only
    // genuine pop-outs get their own window:
    //   - share dialog (?share=, /share/)
    //   - print (?print=1, /print/)
    //   - export/download (?download=1, ?export=)
    sameHostPopupPattern:
      /[\?&]share=|\/share\/|[\?&]print=1|\/print\/|[\?&]download=1|[\?&]export=/,
    // M365 app launcher guard (M17): block cross-app navs before they happen.
    onCrossAppNav: _makeCrossAppNavGuard('onenote'),
    // NOTE: OneNote does NOT use fileOpenPattern. Unlike OneDrive (where files
    // open in child windows), clicking a OneNote notebook IS the primary
    // navigation — the pane should navigate from the home page to the editor
    // in-place. The pin injection via webFrameMain works in the in-pane editor.
    // Wire pin injection into the child window's onenoteframe OOPIF so pins
    // work in the editor even when it opens as a child window.
    onChildWindow: (childWin) => {
      _onenoteChildWindows.add(childWin);
      childWin.on('closed', () => _onenoteChildWindows.delete(childWin));
      function _injectIntoChildOopif() {
        if (!childWin || childWin.isDestroyed()) return;
        let frames = [];
        try {
          frames = childWin.webContents.mainFrame.framesInSubtree;
        } catch {
          return;
        }
        for (const fr of frames) {
          try {
            if (fr && fr.url && /onenoteframe\.aspx/i.test(fr.url)) {
              fr.executeJavaScript(ONENOTE_PIN_MODULE).catch(() => {});
              fr.executeJavaScript(M365_NAV_BTN_MODULE).catch(() => {});
            }
          } catch {}
        }
      }
      childWin.webContents.on('dom-ready', _injectIntoChildOopif);
      childWin.webContents.on('did-frame-navigate', _injectIntoChildOopif);
      childWin.webContents.on('frame-created', () => setTimeout(_injectIntoChildOopif, 1500));
      setInterval(_injectIntoChildOopif, 4000);
    },
  });
  onenoteView.webContents.loadURL(ONENOTE_URL);
  win.contentView.addChildView(onenoteView);
  onenoteView.setBounds({ x: 1599, y: 0, width: 1, height: 900 });

  // ── OneNote pin module: inject into the EDITOR SUBFRAME (OOPIF) ───────
  // OneNote's real UI (page list + section tree) renders inside a CROSS-ORIGIN
  // iframe: onenote.officeapps.live.com/o/onenoteframe.aspx, embedded in the
  // SharePoint Doc.aspx wrapper. Top-frame executeJavaScript CANNOT reach it.
  // Electron's webFrameMain (webContents.mainFrame.framesInSubtree) CAN — it
  // exposes every subframe including OOPIFs, each with its own executeJavaScript.
  //
  // Selectors confirmed via CDP OOPIF spike:
  //   page row:    div.pageNode                (188x36, text = page title)
  //   section row: [role="treeitem"].navItem   (184x36, aria "…, Section")
  //   nav pane:    [class*="navPane"]           (the left rail container)
  // Pin CONTEXT flows back via the SUBFRAME's own window.__gatorPinCtx, which
  // the forwarder reads by targeting the same subframe (see _forwardPinFromView).
  // No Trusted Types CSP in the editor frame. Icons via createElementNS.
  const ONENOTE_PIN_MODULE = `
(function() {
  if (window.__gatorPinModule) return;
  window.__gatorPinModule = true;

  var SVG_NS = 'http://www.w3.org/2000/svg';
  function buildSvg(spec){
    var svg = document.createElementNS(SVG_NS,'svg');
    svg.setAttribute('width',spec.w); svg.setAttribute('height',spec.h);
    svg.setAttribute('viewBox',spec.vb); if(spec.style) svg.setAttribute('style',spec.style);
    (spec.children||[]).forEach(function(c){
      var el=document.createElementNS(SVG_NS,c[0]); var a=c[1];
      for(var k in a){ if(a.hasOwnProperty(k)) el.setAttribute(k,a[k]); }
      svg.appendChild(el);
    });
    return svg;
  }
  function setIcon(el,spec){ while(el.firstChild) el.removeChild(el.firstChild); el.appendChild(buildSvg(spec)); }

  var PIN_ICON = { w:13, h:13, vb:'0 0 24 24', children:[
    ['path',{ d:'M12 17v5', fill:'none', stroke:'white', 'stroke-width':2, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
    ['path',{ d:'M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z', fill:'white', stroke:'white', 'stroke-width':2, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
  ] };

  var ONENOTE_BTN_SIZE = 20;

  function buildGatorBtn(tooltip, onClick) {
    var s = ONENOTE_BTN_SIZE;
    var btn = document.createElement('button');
    btn.title = tooltip;
    btn.setAttribute('data-gator-pin-btn', '1');
    // Always visible at 60% (100% on hover) — placed at the START of the row,
    // left of the title text (same pattern as OneDrive file rows).
    btn.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:' + s + 'px;height:' + s + 'px;border:0;border-radius:50%;background:#1f6f3f;cursor:pointer;flex-shrink:0;transition:background .15s,transform .1s,opacity .1s;padding:0;overflow:hidden;vertical-align:middle;box-sizing:border-box;margin-right:6px;opacity:0.6';
    btn.addEventListener('mouseenter', function() { btn.style.background = '#22c55e'; btn.style.opacity = '1'; });
    btn.addEventListener('mouseleave', function() { btn.style.background = '#1f6f3f'; btn.style.opacity = '0.6'; });
    btn.addEventListener('mousedown', function() { btn.style.transform = 'scale(0.9)'; });
    btn.addEventListener('mouseup', function() { btn.style.transform = ''; });
    btn.addEventListener('click', function(e) { e.preventDefault(); e.stopPropagation(); onClick(btn); });
    setIcon(btn, PIN_ICON);
    return btn;
  }

  // Read the current notebook/section title for a richer pin label.
  function ctxPrefix() {
    try {
      var nb = document.querySelector('[class*="documentTitle"]');
      if (nb) {
        // Use the span child text (clean name without icon characters)
        // rather than the full textContent which includes private-use Unicode icons.
        var span = nb.querySelector('span');
        return ((span ? span.textContent : nb.textContent) || '').trim().replace(/[^\x20-\x7e\u00a0-\u024f]/g, '').trim();
      }
    } catch(e) {}
    return '';
  }

  function pinRow(row, name, kind, targetEl) {
    if (row.dataset.gatorPin === '1') return;
    var btn = buildGatorBtn('Pin to Gator: ' + name, function(b) {
      var label = b.title.replace(/^Pin to Gator:\\s*/, '');
      var nb = ctxPrefix();
      window.__gatorPinCtx = {
        id: 'title:' + label,
        label: label,
        kind: kind,
        notebook: nb || ''
      };
    });
    // Inject ABSOLUTELY into the name container (position:relative) so the
    // pin doesn't shift the row's flex spacers. The name text is indented
    // with padding-left to make room (20px pin + 6px gap = 26px).
    var target = targetEl || row;
    btn.style.position = 'absolute';
    btn.style.left = '4px';
    // Use explicit top offset (row is 36px, button is 20px: (36-20)/2 = 8px)
    // rather than top:50%+translateY(-50%) which breaks inside overflow:hidden
    // containers when the selected-state class changes the item height.
    btn.style.top = '8px';
    btn.style.transform = '';
    btn.style.marginRight = '0';
    // Ensure target is position:relative for absolute child to work
    var tcs = window.getComputedStyle(target);
    if (tcs.position === 'static') target.style.position = 'relative';
    // Indent the first real content child (navItem / text) to make room for pin
    var contentEl = target.querySelector('[class*="navItem"], [class*="itemText"], [class*="pageTitle"]') ||
                    (target.firstElementChild && !target.firstElementChild.getAttribute('data-gator-pin-btn') ? target.firstElementChild : null);
    if (contentEl) {
      var ccs = window.getComputedStyle(contentEl);
      var existingPL = parseInt(ccs.paddingLeft, 10) || 0;
      if (existingPL < 26) contentEl.style.paddingLeft = '26px';
    }
    target.appendChild(btn);
    row.dataset.gatorPin = '1';
  }

  // Pages: div.pageNode (188x36) — inject into div.pageListItem (position:relative,
  // overflow:hidden, 101x36) which contains the navItem text. Absolute pin inside
  // pageListItem keeps the row's flex insertionHint spacers untouched.
  function scanPages() {
    var rows = document.querySelectorAll('div.pageNode');
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (row.dataset.gatorPin === '1') continue;
      var name = (row.textContent || '').trim();
      if (!name || name.length < 1 || name.length > 100) continue;
      // Target the pageListItem container (position:relative) inside the row
      var nameContainer = row.querySelector('[class*="pageListItem"]');
      pinRow(row, name, 'page', nameContainer || row);
    }
  }

  // Sections: [role="treeitem"] — inject into the itemWrap child container.
  function scanSections() {
    var rows = document.querySelectorAll('[role="treeitem"]');
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (row.dataset.gatorPin === '1') continue;
      var aria = row.getAttribute('aria-label') || '';
      if (!/section/i.test(aria)) continue;
      var name = (row.textContent || '').trim() || aria.split(',')[0].trim();
      if (!name || name.length < 1) continue;
      // Target the itemWrap child (contains the section label text)
      var nameContainer = row.querySelector('[class*="itemWrap"]') || row.querySelector('[class*="navItem"]');
      pinRow(row, name, 'section', nameContainer || row);
    }
  }

  function scanAll() {
    try { scanPages(); } catch(e) {}
    try { scanSections(); } catch(e) {}
  }

  var scanQueued = false;
  var obs = new MutationObserver(function() {
    if (scanQueued) return;
    scanQueued = true;
    requestAnimationFrame(function() { scanQueued = false; scanAll(); });
  });
  try { obs.observe(document.body, { childList: true, subtree: true }); } catch(e) {}

  setInterval(scanAll, 2000);
  setTimeout(scanAll, 500);
  scanAll();
})();
  `;

  // Inject the module into the OneNote editor subframe (OOPIF). Walk all frames,
  // find the onenoteframe.aspx one, and inject there. Runs on dom-ready,
  // frame-created, and a periodic sweep (the frame loads async + swaps on nav).
  function _injectOnenotePinFrame() {
    if (!onenoteView || !onenoteView.webContents || onenoteView.webContents.isDestroyed()) return;
    let frames = [];
    try {
      frames = onenoteView.webContents.mainFrame.framesInSubtree;
    } catch {
      return;
    }
    for (const fr of frames) {
      try {
        if (fr && fr.url && /onenoteframe\.aspx/i.test(fr.url)) {
          fr.executeJavaScript(ONENOTE_PIN_MODULE).catch((e) => {
            try {
              fs.appendFileSync(
                path.join(__dirname, 'pin-debug.log'),
                'ONENOTE FRAME INJECT ERR: ' + e.message + '\n',
              );
            } catch {}
          });
        }
      } catch {}
    }
  }
  onenoteView.webContents.on('dom-ready', _injectOnenotePinFrame);
  onenoteView.webContents.on('did-frame-navigate', _injectOnenotePinFrame);
  onenoteView.webContents.on('frame-created', () => setTimeout(_injectOnenotePinFrame, 1500));
  setInterval(_injectOnenotePinFrame, 4000);

  // ── Confluence view ──────────────────────────────────────────────────
  // Atlassian Cloud: cookie-based SSO (not M365). persist:confluence session
  // holds the login. No buildNonElectronUA (Atlassian doesn't block Electron).
  // Entry URL from /api/config (tenant-specific, e.g. https://amd.atlassian.net/wiki).
  // HITL: classic create/edit forms are preserved — confluence-create/confluence-edit
  // pane signals still render the custom form overlay (not the real Confluence editor).
  if (CONFLUENCE_URL) {
    const confluenceSession = session.fromPartition(CONFLUENCE_PARTITION);
    applyMediaPermissions(confluenceSession);
    confluenceView = new WebContentsView({
      webPreferences: {
        session: confluenceSession,
        contextIsolation: true,
        nodeIntegration: false,
      },
    });
    confluenceView.webContents.setBackgroundThrottling(false);
    applyNavigationPolicy(confluenceView, {
      name: 'confluence',
      homeHosts: ['atlassian.net', 'atlassian.com'],
      // In-page navigation: clicking a page/link stays in the pane (not a child window).
      // Share/export/print pop out.
      sameHostPopupPattern: /\/share|\/export|\/print|\/download/i,
    });
    confluenceView.webContents.loadURL(CONFLUENCE_URL);
    win.contentView.addChildView(confluenceView);
    confluenceView.setBounds({ x: 1599, y: 0, width: 1, height: 900 });
  }

  // ── Jira view ────────────────────────────────────────────────────────
  // Atlassian Cloud: same SSO pattern as Confluence. persist:jira session.
  // Entry URL from /api/config (e.g. https://amd-hub.atlassian.net/jira).
  // HITL: classic create form is preserved — jira-create pane signal still
  // renders the custom form overlay with dynamic fields + agent retry.
  if (JIRA_URL) {
    const jiraSession = session.fromPartition(JIRA_PARTITION);
    applyMediaPermissions(jiraSession);
    jiraView = new WebContentsView({
      webPreferences: { session: jiraSession, contextIsolation: true, nodeIntegration: false },
    });
    jiraView.webContents.setBackgroundThrottling(false);
    applyNavigationPolicy(jiraView, {
      name: 'jira',
      homeHosts: ['atlassian.net', 'atlassian.com'],
      sameHostPopupPattern: /\/share|\/export|\/print|\/download/i,
    });
    jiraView.webContents.loadURL(JIRA_URL);
    win.contentView.addChildView(jiraView);
    jiraView.setBounds({ x: 1599, y: 0, width: 1, height: 900 });
  }

  // ── Jira pin module: inject ONCE on dom-ready ───────────────────────
  // Two surfaces:
  //   1. Issue detail view (/browse/KEY-123): pin in the action toolbar
  //      (Watch / Share / Actions row) before Watch — uses issue key from URL
  //      and summary from the h1 heading.
  //   2. List / board views: pin on a[href*="/browse/KEY-NNN"] issue card links.
  //
  // Selectors confirmed via live CDP inspection of amd-hub.atlassian.net:
  //   action bar parent:  div containing [data-testid="share-dialog.ui.share-button"]
  //   issue summary:      h1[data-testid="issue.views.issue-base.foundation.summary.heading"]
  //   issue key in URL:   /browse/<KEY>-<NUM>
  if (jiraView) {
    const JIRA_PIN_MODULE = `
(function() {
  if (window.__gatorPinModule) return;
  window.__gatorPinModule = true;

  var SVG_NS = 'http://www.w3.org/2000/svg';
  function buildSvg(spec){
    var svg = document.createElementNS(SVG_NS,'svg');
    svg.setAttribute('width',spec.w); svg.setAttribute('height',spec.h);
    svg.setAttribute('viewBox',spec.vb);
    (spec.children||[]).forEach(function(c){
      var el=document.createElementNS(SVG_NS,c[0]); var a=c[1];
      for(var k in a){ if(a.hasOwnProperty(k)) el.setAttribute(k,a[k]); }
      svg.appendChild(el);
    });
    return svg;
  }

  var PIN_ICON = { w:14, h:14, vb:'0 0 24 24', children:[
    ['path',{ d:'M12 17v5', fill:'none', stroke:'white', 'stroke-width':2, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
    ['path',{ d:'M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z', fill:'white', stroke:'white', 'stroke-width':2, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
  ] };

  var BTN_SIZE = 22;
  function buildGatorBtn(tooltip, onClick) {
    var btn = document.createElement('button');
    btn.title = tooltip;
    btn.setAttribute('data-gator-pin-btn', '1');
    btn.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:' + BTN_SIZE + 'px;height:' + BTN_SIZE + 'px;border:0;border-radius:50%;background:#1f6f3f;cursor:pointer;flex-shrink:0;transition:background .15s,opacity .15s;padding:0;overflow:hidden;box-sizing:border-box;opacity:0.6;margin-right:6px';
    btn.addEventListener('mouseenter', function() { btn.style.background = '#22c55e'; btn.style.opacity = '1'; });
    btn.addEventListener('mouseleave', function() { btn.style.background = '#1f6f3f'; btn.style.opacity = '0.6'; });
    btn.addEventListener('click', function(e) { e.preventDefault(); e.stopPropagation(); onClick(btn); });
    btn.appendChild(buildSvg(PIN_ICON));
    return btn;
  }

  // Extract issue key (e.g. ROCM-27670) from a Jira browse URL.
  function extractIssueKey(href) {
    var m = (href || '').match(/\\/browse\\/([A-Z][A-Z0-9]+-\\d+)/);
    return m ? m[1] : '';
  }

  // ── Issue detail pin: in the Watch/Share/Actions action toolbar ──────
  // Finds the container holding Watch + Share + Actions and inserts the pin
  // before the first action. Idempotent: replaces stale pin on SPA navigation.
  function scanIssueDetail() {
    var issueKey = extractIssueKey(location.pathname);
    if (!issueKey) return;

    var summaryEl = document.querySelector('h1[data-testid="issue.views.issue-base.foundation.summary.heading"]');
    var summary = summaryEl ? (summaryEl.textContent || '').trim().slice(0, 200) : issueKey;
    if (!summary) summary = issueKey;

    // Find the action bar: parent of the Share button.
    var shareBtn = document.querySelector('[data-testid="share-dialog.ui.share-button"]');
    if (!shareBtn) return;
    var actionBar = shareBtn.parentElement;
    // Walk up once if share is nested (DIV > BUTTON).
    if (actionBar && actionBar.children.length < 2) actionBar = actionBar.parentElement;
    if (!actionBar) return;

    // Idempotent: correct pin already present — done.
    var existing = actionBar.querySelector('[data-gator-title-pin]');
    if (existing) {
      if (existing.getAttribute('data-gator-title-pin') === issueKey) return;
      existing.parentNode.removeChild(existing);
    }

    var btn = buildGatorBtn('Pin to Gator: ' + issueKey + ' ' + summary, function(b) {
      window.__gatorPinCtx = {
        id: b.getAttribute('data-pin-issue-id') || '',
        label: b.getAttribute('data-pin-label') || '',
        kind: 'issue',
        web_url: b.getAttribute('data-pin-href') || location.href
      };
    });
    btn.setAttribute('data-pin-issue-id', issueKey);
    btn.setAttribute('data-pin-label', issueKey + ': ' + summary);
    btn.setAttribute('data-pin-href', location.href);
    btn.setAttribute('data-gator-title-pin', issueKey);
    btn.style.marginRight = '8px';
    btn.style.alignSelf = 'center';

    // Insert before the first child of the action bar (before Watch).
    actionBar.insertBefore(btn, actionBar.firstElementChild);
  }

  // ── Issue list pin: on /browse/KEY-NNN links in board / backlog views ─
  // Skips links in the main issue-detail area (those are cross-links, noisy).
  var seenKeys = {};
  function scanIssueLinks() {
    seenKeys = {};
    var links = document.querySelectorAll('a[href*="/browse/"]');
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      if (link.dataset.gatorPin === '1') continue;
      if (link.querySelector('[data-gator-pin-btn]')) { link.dataset.gatorPin = '1'; continue; }

      var href = link.getAttribute('href') || '';
      var key = extractIssueKey(href);
      if (!key) continue;
      if (seenKeys[key]) continue;

      // Skip links inside the issue description / body content area.
      var el = link.parentElement;
      var inBody = false;
      for (var d = 0; d < 8; d++) {
        if (!el) break;
        var tid = el.getAttribute('data-testid') || '';
        if (/description|comment|content|body|editor/i.test(tid)) { inBody = true; break; }
        el = el.parentElement;
      }
      if (inBody) continue;

      // Skip DOM-duplicate: live pin with this key already exists.
      if (document.querySelector('[data-gator-pin-btn][data-pin-issue-id="' + key + '"]')) {
        seenKeys[key] = true; continue;
      }

      seenKeys[key] = true;

      var text = (link.textContent || '').trim().slice(0, 80) || key;
      var fullUrl = href.startsWith('http') ? href : (location.origin + href);
      var finalKey = key, finalLabel = key + ': ' + text, finalUrl = fullUrl;

      var btn = buildGatorBtn('Pin to Gator: ' + finalLabel, function(b) {
        window.__gatorPinCtx = {
          id: b.getAttribute('data-pin-issue-id') || '',
          label: b.getAttribute('data-pin-label') || '',
          kind: 'issue',
          web_url: b.getAttribute('data-pin-href') || ''
        };
      });
      btn.setAttribute('data-pin-issue-id', finalKey);
      btn.setAttribute('data-pin-label', finalLabel);
      btn.setAttribute('data-pin-href', finalUrl);

      link.style.display = 'inline-flex';
      link.style.alignItems = 'center';
      link.style.overflow = 'hidden';
      var wrapper = document.createElement('span');
      wrapper.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;display:block';
      while (link.firstChild) wrapper.appendChild(link.firstChild);
      link.appendChild(wrapper);
      link.insertBefore(btn, wrapper);
      link.dataset.gatorPin = '1';
    }
  }

  function scanAll() { try { scanIssueDetail(); } catch(e) {} try { scanIssueLinks(); } catch(e) {} }

  var scanQueued = false;
  var obs = new MutationObserver(function() {
    if (scanQueued) return;
    scanQueued = true;
    requestAnimationFrame(function() { scanQueued = false; scanAll(); });
  });
  try { obs.observe(document.body, { childList: true, subtree: true }); } catch(e) {}

  setInterval(scanAll, 2000);
  setTimeout(scanAll, 500);
})();
    `;
    jiraView.webContents.on('dom-ready', () => {
      if (!jiraView || !jiraView.webContents || jiraView.webContents.isDestroyed()) return;
      jiraView.webContents.executeJavaScript(JIRA_PIN_MODULE).catch(() => {});
    });
  }

  // ── Confluence pin module: inline pin on page title links ────────────
  // Pin appears inline at the start of each page title link on the home page,
  // recent list, and space views — the same position you confirmed was perfect.
  // Does NOT inject pins inside page body content (those 89+ links are noise).
  //
  // The page ID is extracted from the href (/pages/<id>/) — deterministic.
  // No title search needed — agent calls read_confluence_page(page_id=...) directly.
  if (confluenceView) {
    const CF_PIN_MODULE = `
(function() {
  if (window.__gatorPinModule) return;
  window.__gatorPinModule = true;

  var SVG_NS = 'http://www.w3.org/2000/svg';
  function buildSvg(spec){
    var svg = document.createElementNS(SVG_NS,'svg');
    svg.setAttribute('width',spec.w); svg.setAttribute('height',spec.h);
    svg.setAttribute('viewBox',spec.vb);
    (spec.children||[]).forEach(function(c){
      var el=document.createElementNS(SVG_NS,c[0]); var a=c[1];
      for(var k in a){ if(a.hasOwnProperty(k)) el.setAttribute(k,a[k]); }
      svg.appendChild(el);
    });
    return svg;
  }

  var PIN_ICON = { w:14, h:14, vb:'0 0 24 24', children:[
    ['path',{ d:'M12 17v5', fill:'none', stroke:'white', 'stroke-width':2, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
    ['path',{ d:'M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z', fill:'white', stroke:'white', 'stroke-width':2, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
  ] };

  var BTN_SIZE = 22;

  function buildGatorBtn(tooltip, onClick) {
    var btn = document.createElement('button');
    btn.title = tooltip;
    btn.setAttribute('data-gator-pin-btn', '1');
    btn.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:' + BTN_SIZE + 'px;height:' + BTN_SIZE + 'px;border:0;border-radius:50%;background:#1f6f3f;cursor:pointer;flex-shrink:0;transition:background .15s,opacity .15s;padding:0;overflow:hidden;box-sizing:border-box;opacity:0.6;margin-right:6px';
    btn.addEventListener('mouseenter', function() { btn.style.background = '#22c55e'; btn.style.opacity = '1'; });
    btn.addEventListener('mouseleave', function() { btn.style.background = '#1f6f3f'; btn.style.opacity = '0.6'; });
    btn.addEventListener('click', function(e) { e.preventDefault(); e.stopPropagation(); onClick(btn); });
    btn.appendChild(buildSvg(PIN_ICON));
    return btn;
  }

  // Extract the numeric page ID from a Confluence page URL.
  // Patterns: /pages/<id>/Title, /pages/edit-v2/<id>
  function extractPageId(href) {
    var m = href.match(/\\/pages(?:\\/edit-v2)?\\/(\\d+)/);
    return m ? m[1] : '';
  }

  // Extract a clean page title from the URL slug (e.g. .../1234/WINML+models+status
  // -> "WINML models status"). Confluence sidebar link TEXT is often polluted with
  // action labels ("Create child content for X", "More actions"), so the slug is
  // the most reliable title source when available.
  function titleFromHref(href) {
    var m = href.match(/\\/pages(?:\\/edit-v2)?\\/\\d+\\/([^/?#]+)/);
    if (!m) return '';
    try {
      var slug = decodeURIComponent(m[1].replace(/\\+/g, ' ')).trim();
      return slug;
    } catch (e) { return m[1].replace(/\\+/g, ' ').trim(); }
  }

  // The numeric page ID for the page currently being VIEWED (detail view).
  // Short links (/wiki/x/VF5Ya) don't carry the ID in the URL, so prefer the
  // meta tag Confluence injects, then fall back to the URL.
  function currentPageId() {
    var meta = document.querySelector('meta[name="ajs-page-id"], meta[name="confluence-page-id"]');
    if (meta && meta.content && /^\\d+$/.test(meta.content)) return meta.content;
    var body = document.body;
    if (body && body.getAttribute('data-page-id') && /^\\d+$/.test(body.getAttribute('data-page-id'))) return body.getAttribute('data-page-id');
    return extractPageId(location.pathname + location.search);
  }

  // Check if a link is a nav/card link vs a body-content link.
  // Nav links: short text, appear in lists/cards, NOT inside article/content divs.
  // Body links: inside the page content area (data-testid*="content", article, etc.)
  function isBodyContentLink(link) {
    var el = link.parentElement;
    for (var depth = 0; depth < 10; depth++) {
      if (!el) break;
      var testid = el.getAttribute('data-testid') || '';
      var cls = (el.className || '').toString();
      if (/content-body|confluence-content|wiki-content|editor|ak-renderer/i.test(cls + testid)) return true;
      if (el.tagName === 'ARTICLE') return true;
      el = el.parentElement;
    }
    return false;
  }

  function scanPages() {
    // Per-scan dedup: Confluence renders multiple <a> with the same page ID in
    // the sidebar (e.g. a shortcut card emits two anchors). We collapse them per
    // pass. We do NOT use a persistent cross-scan registry: the sidebar/page-tree
    // re-renders its anchors on navigation, and a persistent registry would then
    // permanently skip the freshly-rendered anchors — that was the root cause of
    // pins showing inconsistently. The per-node data-gator-pin marker already
    // prevents re-pinning the same live node.
    var seenPageIds = {};
    var links = document.querySelectorAll('a[href*="/pages/"]');
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      if (link.dataset.gatorPin === '1') continue;
      if (link.querySelector('[data-gator-pin-btn]')) { link.dataset.gatorPin = '1'; continue; }

      // Extract only the page title — NOT action text embedded in the same link.
      // Confluence page links often contain the title + action buttons ("Create child
      // content for X") as sibling elements inside the same <a>. We want ONLY the title.
      // Strategy: find the first text node or child element whose OWN text (not
      // descendants) is a plausible page title (not an action word).
      var text = '';
      // 1. Direct text nodes (most reliable — only the link label text)
      link.childNodes.forEach(function(n) {
        if (!text && n.nodeType === 3) {
          var t = n.textContent.trim();
          if (t.length > 1) text = t;
        }
      });
      // 2. First child element's OWN direct text (not its full .textContent)
      if (!text) {
        for (var ci = 0; ci < link.children.length; ci++) {
          var child = link.children[ci];
          var childDirectText = '';
          child.childNodes.forEach(function(cn) {
            if (!childDirectText && cn.nodeType === 3) childDirectText = cn.textContent.trim();
          });
          if (childDirectText.length > 1) { text = childDirectText; break; }
          // Try child's textContent but only if it's short (title, not action)
          var ct = (child.textContent || '').trim();
          if (ct.length > 1 && ct.length < 60 && !/create child|child content/i.test(ct)) {
            text = ct; break;
          }
        }
      }
      var href = link.getAttribute('href') || '';
      var pageId = extractPageId(href);
      if (!pageId) continue;

      // Prefer the clean title from the URL slug — sidebar link text is often
      // polluted with action labels ("Create child content for X", "More actions").
      var slugTitle = titleFromHref(href);
      if (slugTitle && slugTitle.length >= 2 && slugTitle.length <= 120) {
        text = slugTitle;
      }

      // Skip pure action words (standalone, not mixed with a real title)
      if (/^(create child content|edit$|delete$|move$|copy$|share$|watch$|more actions$)/i.test(text)) continue;
      if (!text || text.length < 2 || text.length > 120) continue;

      // Skip duplicate page IDs within this scan pass (two <a> for one card).
      if (seenPageIds[pageId]) continue;
      // Skip if a pin for this page ID already exists in the live DOM. Handles
      // duplicate anchors pinned across separate scan passes (the sidebar renders
      // two <a> with the same href for shortcut cards).
      if (document.querySelector('[data-gator-pin-btn][data-pin-page-id="' + pageId + '"]')) {
        seenPageIds[pageId] = true;
        continue;
      }

      // Skip links inside the page body content area
      if (isBodyContentLink(link)) continue;

      seenPageIds[pageId] = true;

      var fullUrl = href.startsWith('http') ? href : (location.origin + href);
      var finalPageId = pageId;
      var finalLabel = text;
      var finalUrl = fullUrl;

      var btn = buildGatorBtn('Pin to Gator: ' + text, function(b) {
        window.__gatorPinCtx = {
          id: b.getAttribute('data-pin-page-id') || '',
          label: b.getAttribute('data-pin-label') || '',
          kind: 'page',
          web_url: b.getAttribute('data-pin-href') || ''
        };
      });
      btn.setAttribute('data-pin-page-id', finalPageId);
      btn.setAttribute('data-pin-label', finalLabel);
      btn.setAttribute('data-pin-href', finalUrl);

      // Inline injection: make link flex, wrap ALL content in a span for ellipsis,
      // then prepend the pin. Using a single wrapper span handles both bare text
      // nodes AND child elements (the latter caused noEllipsis=42).
      link.style.display = 'inline-flex';
      link.style.alignItems = 'center';
      link.style.overflow = 'hidden';

      // Wrap ALL existing children + text nodes into one span for proper ellipsis.
      // This handles the two cases: bare text node (text title link) and child
      // elements (shortcut card links with embedded content).
      var wrapper = document.createElement('span');
      wrapper.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;display:block';
      // Move all current children into the wrapper
      while (link.firstChild) wrapper.appendChild(link.firstChild);
      link.appendChild(wrapper);
      // Prepend the pin button before the wrapper
      link.insertBefore(btn, wrapper);
      link.dataset.gatorPin = '1';
    }
  }

  // Pin the current page. Inserts the pin to the LEFT of the Edit action inside
  // [data-testid="object-header-actions-container"] — the toolbar row that
  // contains (Updated date) / Edit / Share / Copy link / More actions.
  //
  // The Edit control's DOM varies by page: sometimes it's a bare <a> that is a
  // direct child of the bar, sometimes it's an <a> nested inside a wrapper DIV
  // like [data-testid="editIcon-action-container-without-separator"]. To insert
  // reliably (and to sit left of Edit regardless of the changing date text), we
  // find the DIRECT CHILD of the bar that contains the Edit element and insert
  // before that child. Idempotent: replaces the stale pin on SPA navigation.
  function scanTitle() {
    var pageId = currentPageId();
    if (!pageId) return;

    var actionsBar = document.querySelector('[data-testid="object-header-actions-container"]');
    if (!actionsBar) return;

    // Idempotent: already pinned for this page — leave it; stale — replace.
    var existing = actionsBar.querySelector('[data-gator-title-pin]');
    if (existing) {
      if (existing.getAttribute('data-gator-title-pin') === pageId) return;
      existing.parentNode.removeChild(existing);
    }

    var titleEl = document.querySelector('[data-testid="title-text"] h1') || document.querySelector('h1');
    var titleText = titleEl ? (titleEl.textContent || '').trim().slice(0, 200) : (document.title || '');
    if (!titleText || titleText.length < 2) return;

    // Locate the Edit element (link or button), then climb to the direct child
    // of the bar that contains it. Prefer the stable edit action-container.
    var editEl = actionsBar.querySelector('[data-testid^="editIcon-action-container"]')
      || actionsBar.querySelector('a[aria-label="Edit this content"], a[aria-label*="Edit" i], button[aria-label*="Edit" i]');
    var insertBefore = null;
    if (editEl) {
      insertBefore = editEl;
      while (insertBefore && insertBefore.parentNode !== actionsBar) insertBefore = insertBefore.parentNode;
    }
    if (!insertBefore) insertBefore = actionsBar.firstElementChild;  // fallback

    var btn = buildGatorBtn('Pin to Gator: ' + titleText, function(b) {
      window.__gatorPinCtx = {
        id: b.getAttribute('data-pin-page-id') || '',
        label: b.getAttribute('data-pin-label') || '',
        kind: 'page',
        web_url: b.getAttribute('data-pin-href') || location.href
      };
    });
    btn.setAttribute('data-pin-page-id', pageId);
    btn.setAttribute('data-pin-label', titleText);
    btn.setAttribute('data-pin-href', location.href);
    btn.setAttribute('data-gator-title-pin', pageId);
    btn.style.marginRight = '8px';
    btn.style.alignSelf = 'center';

    if (insertBefore) actionsBar.insertBefore(btn, insertBefore);
    else actionsBar.appendChild(btn);
  }

  function scanAll() { try { scanPages(); } catch(e) {} try { scanTitle(); } catch(e) {} }

  var scanQueued = false;
  var obs = new MutationObserver(function() {
    if (scanQueued) return;
    scanQueued = true;
    requestAnimationFrame(function() { scanQueued = false; scanAll(); });
  });
  try { obs.observe(document.body, { childList: true, subtree: true }); } catch(e) {}

  setInterval(scanAll, 2000);
  setTimeout(scanAll, 500);
})();
    `;
    // Inject once on dom-ready (covers initial load + hard reloads — sentinel
    // resets on page context wipe). The in-page MutationObserver + setInterval
    // handle all SPA navigation; no shell-side re-inject timer needed.
    confluenceView.webContents.on('dom-ready', () => {
      if (
        !confluenceView ||
        !confluenceView.webContents ||
        confluenceView.webContents.isDestroyed()
      )
        return;
      confluenceView.webContents.executeJavaScript(CF_PIN_MODULE).catch(() => {});
    });
  }

  ensureGitHubView();

  // ── Outlook pin module: inject ONCE on dom-ready ────────────────────
  // Selectors confirmed by spike/native-outlook-pane/:
  //   list row:      [role="option"][data-convid]  (data-convid = conversation id)
  //   selected row:  [role="option"][aria-selected="true"]
  //   reading pane:  [aria-label="Reading Pane"]
  //   subject:       [role="heading"] inside the reading pane
  //   action row:    the open message's per-message cluster (Reply / Reply all /
  //                  Forward / Apps / "More items"). Our buttons anchor on the
  //                  "More items" (…) button and sit immediately before it.
  // Icons via createElementNS (setIcon) — OWA enforces Trusted Types.
  outlookView.webContents.on('dom-ready', () => {
    if (!outlookView || !outlookView.webContents || outlookView.webContents.isDestroyed()) return;
    outlookView.webContents
      .executeJavaScript(
        `
(function() {
if (window.__gatorPinModule) return;
window.__gatorPinModule = true;

var SVG_NS = 'http://www.w3.org/2000/svg';
function buildSvg(spec){
  var svg = document.createElementNS(SVG_NS,'svg');
  svg.setAttribute('width',spec.w); svg.setAttribute('height',spec.h);
  svg.setAttribute('viewBox',spec.vb); if(spec.style) svg.setAttribute('style',spec.style);
  (spec.children||[]).forEach(function(c){
    var el=document.createElementNS(SVG_NS,c[0]); var a=c[1];
    for(var k in a){ if(a.hasOwnProperty(k)) el.setAttribute(k,a[k]); }
    svg.appendChild(el);
  });
  return svg;
}
function setIcon(el,spec){ while(el.firstChild) el.removeChild(el.firstChild); el.appendChild(buildSvg(spec)); }

var PIN_ICON = { w:14, h:14, vb:'0 0 24 24', children:[
  ['path',{ d:'M12 17v5', fill:'none', stroke:'white', 'stroke-width':2, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
  ['path',{ d:'M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z', fill:'white', stroke:'white', 'stroke-width':2, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
] };
var CHECK_ICON = { w:16, h:16, vb:'0 0 24 24', children:[
  ['polyline',{ points:'20 6 9 17 4 12', fill:'none', stroke:'white', 'stroke-width':3, 'stroke-linecap':'round', 'stroke-linejoin':'round' }],
] };
var GATOR_ICON = { w:16, h:16, vb:'0 0 26 26', style:'display:block', children:[
  ['rect',{ x:1,y:1,width:22,height:18,rx:5,fill:'#16a34a' }],
  ['polygon',{ points:'4,19 2,24 9,19', fill:'#16a34a' }],
  ['circle',{ cx:8.5,cy:7.5,r:2.2,fill:'white' }],['circle',{ cx:8.5,cy:7.5,r:1.1,fill:'#052e16' }],
  ['circle',{ cx:17.5,cy:7.5,r:2.2,fill:'white' }],['circle',{ cx:17.5,cy:7.5,r:1.1,fill:'#052e16' }],
  ['rect',{ x:5,y:12,width:16,height:5,rx:2.5,fill:'#15803d' }],
  ['rect',{ x:8,y:11,width:2,height:2.5,rx:0.6,fill:'white' }],['rect',{ x:12,y:11,width:2,height:2.5,rx:0.6,fill:'white' }],['rect',{ x:16,y:11,width:2,height:2.5,rx:0.6,fill:'white' }],
] };

var OUTLOOK_BTN_SIZE = 26;

// Context: OWA has REAL URL routing. Read the active conversation from the
// selected list row (authoritative) or the URL (/mail/<folder>/id/<convid>).
var currentCtx = { id:null, label:null, kind:'email' };
window.__gatorCurrentCtx = currentCtx;
window.__gatorSetCtx = function(ctx){ currentCtx = ctx; window.__gatorCurrentCtx = ctx; };

function readOutlookCtx(){
  var id = null, label = null;
  var sel = document.querySelector('[role="option"][aria-selected="true"][data-convid]');
  if (sel) { id = sel.getAttribute('data-convid'); label = (sel.getAttribute('aria-label')||'').split(',')[0].trim(); }
  if (!id) {
    var m = /\\/mail\\/[^/]+\\/id\\/([^/?#]+)/.exec(location.href);
    if (m) { try { id = decodeURIComponent(m[1]); } catch(e){ id = m[1]; } }
  }
  // Subject from the reading pane heading (better label than the row aria).
  // The heading DIV can contain sibling UI ("Summarize this email", a shield
  // badge, "AMD General") — take the first meaningful text node/child only and
  // cut at known noise so the pin label is just the subject line.
  var rp = document.querySelector('[aria-label="Reading Pane"]');
  if (rp) {
    var h = rp.querySelector('[role="heading"]');
    if (h) {
      // Prefer the first child's text (the subject span) over the whole heading.
      var raw = (h.firstElementChild && h.firstElementChild.textContent) || h.textContent || '';
      raw = raw.replace(/\\s+/g, ' ').trim();
      // Strip trailing app chrome that sometimes rides along in textContent.
      raw = raw.replace(/\\s*(Summarize this email|AMD General|Confidential).*$/i, '').trim();
      if (raw) label = raw.slice(0, 80);
    }
  }
  return { id:id, label:(label||'Email'), kind:'email' };
}

function buildBtn(id, tooltip, onClick, iconSpec){
  var s = OUTLOOK_BTN_SIZE;
  var btn = document.createElement('button');
  if (id) btn.id = id;
  btn.title = tooltip; btn.type = 'button';
  btn.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:'+s+'px;height:'+s+'px;border:0;border-radius:50%;background:#1f6f3f;cursor:pointer;flex-shrink:0;transition:background .15s,transform .1s;padding:0;overflow:hidden;vertical-align:middle;box-sizing:border-box;margin-left:6px;z-index:9999';
  setIcon(btn, iconSpec);
  btn.onmouseenter=function(){ btn.style.background='#2a8a4f'; };
  btn.onmouseleave=function(){ btn.style.background='#1f6f3f'; };
  btn.onmousedown=function(){ btn.style.transform='scale(0.9)'; };
  btn.onmouseup=function(){ btn.style.transform='scale(1)'; };
  btn.onclick=function(e){ e.preventDefault(); e.stopPropagation(); onClick(btn); };
  return btn;
}

function headerClick(b){
  var ctx = readOutlookCtx();
  currentCtx = ctx; window.__gatorCurrentCtx = ctx;
  if (!ctx.id) return;
  window.__gatorPinCtx = { channel: ctx.id, id: ctx.id, thread_ts:null, label: ctx.label||ctx.id, kind:'email', ts:null };
  setIcon(b, CHECK_ICON); b.style.background='#0a4a2a';
  setTimeout(function(){ setIcon(b, PIN_ICON); b.style.background='#1f6f3f'; }, 1200);
}

// ONE STABLE HOME: a dedicated pin+hide/show ROW inserted into the open
// message's own body block, in the roomy gap BELOW the To/Cc recipient header
// and ABOVE the message body. OWA's per-message action cluster (Reply / … /
// More items) is dense and cramped; this band is the calmest, most stable
// surface — full message width, always present for an open message, and it
// doesn't fight OWA's toolbar re-renders.
//
// Anchor: the message-body element ([aria-label="Message body"] /
// [id^="UniqueMessageBody"] / div[role="document"]). We climb to the body's
// block wrapper (the child that sits directly under the header) and insert our
// row as that wrapper's previous sibling.
function findBodyWrapper(){
  var rp = document.querySelector('[aria-label="Reading Pane"]');
  if (!rp) return null;
  var body = rp.querySelector('[aria-label="Message body"], [id^="UniqueMessageBody"], div[role="document"]');
  if (!body) return null;
  var br = body.getBoundingClientRect();
  if (!(br.width > 0 && br.top >= 0 && br.top < 2000)) return null;
  // Climb while the parent starts at (roughly) the same top as the body — i.e.
  // the parent is still just the body block. Stop once the parent extends above
  // the body (that parent also holds the subject/recipient header): the current
  // node is then the body block, and inserting before it lands in the gap.
  var wrapper = body;
  var bodyTop = br.top;
  for (var i=0; i<5 && wrapper.parentElement && wrapper.parentElement !== rp; i++){
    var p = wrapper.parentElement.getBoundingClientRect();
    if (p.top < bodyTop - 30) break;
    wrapper = wrapper.parentElement;
  }
  return (wrapper && wrapper.parentElement) ? wrapper : null;
}
function scanHeader(){
  var wrapper = findBodyWrapper();
  if (!wrapper) return;
  var parent = wrapper.parentElement;
  var existing = document.getElementById('__gator_pin_row');
  // Already present and sitting right before the body wrapper? Nothing to do.
  // DOCUMENT_POSITION_FOLLOWING => the wrapper comes after our row.
  if (existing && existing.parentNode === parent &&
      (existing.compareDocumentPosition(wrapper) & Node.DOCUMENT_POSITION_FOLLOWING)) {
    return;
  }
  document.querySelectorAll('#__gator_pin_row').forEach(function(el){ el.remove(); });

  var ctx = readOutlookCtx();
  var row = document.createElement('div');
  row.id = '__gator_pin_row';
  // Right-aligned so the buttons line up with the reply / more-actions / date
  // cluster above them (an "actions" column) and keep the message's left edge clean.
  row.style.cssText = 'display:flex;align-items:center;justify-content:flex-end;gap:6px;padding:4px 6px;margin:2px 0';

  var pin = buildBtn('__gator_pin_header', 'Pin to Gator: '+(ctx.label||''), headerClick, PIN_ICON);
  pin.style.marginLeft = '0';               // row uses gap; no per-button margin

  row.appendChild(pin);
  parent.insertBefore(row, wrapper);        // sit ABOVE the message body

  // Keep context fresh.
  if (ctx.id && ctx.id !== currentCtx.id) { currentCtx = ctx; window.__gatorCurrentCtx = ctx; window.__gatorPinCtx = null; }
}

function scanAll(){ scanHeader(); }
var scanQueued = false;
var obs = new MutationObserver(function(){ if(scanQueued) return; scanQueued=true; requestAnimationFrame(function(){ scanQueued=false; scanAll(); }); });
obs.observe(document.body, { childList:true, subtree:true });
setInterval(scanAll, 2000);
setTimeout(scanAll, 500);
})();
    `,
      )
      .catch((e) => {
        try {
          fs.appendFileSync(
            path.join(__dirname, 'pin-debug.log'),
            'OUTLOOK INJECT ERROR: ' + e.message + '\n',
          );
        } catch {}
      });
  });

  // First-launch default: before the renderer has had a chance to restore a
  // persisted width (app.js's DOMContentLoaded reads 'tp-pane-width' from
  // localStorage and calls restoreExtTileWidth — only if the user has EVER
  // dragged before), default to maximizing the external app / minimizing
  // Gator to its floor, rather than the old fixed EXT_TILE_WIDTH_DEFAULT
  // (560px), which produced a near-50/50 (or worse) split. If a width WAS
  // persisted, the renderer's restore call overwrites this moments later.
  {
    const [w0] = win.getContentSize();
    extTileWidth = Math.max(350, w0 - GATOR_MIN_WIDTH);
  }

  // Attach toolbar navigation/load listeners to every external view so the
  // bar's URL display and back/forward state stay live as the user navigates.
  // Done here (after all views exist) in one place rather than at each view's
  // creation site — easier to audit and keep in sync when apps are added.
  _attachToolbarListeners(slackView, 'slack');
  _attachToolbarListeners(teamsView, 'teams');
  _attachToolbarListeners(outlookView, 'outlook');
  _attachToolbarListeners(onedriveView, 'onedrive');
  _attachToolbarListeners(onenoteView, 'onenote');
  _attachToolbarListeners(confluenceView, 'confluence');
  _attachToolbarListeners(jiraView, 'jira');
  _attachToolbarListeners(githubView, 'github');

  _layoutNow();
  win.on('resize', layout);
  _attachMaximizeListener();

  // ── Context capture: watch Slack URL (Teams context is DOM-only) ────
  let lastCtx = null;
  let lastUrl = null;
  let ctxDispatchCount = 0;

  // Cross-page dispatch: fires CustomEvent on GATOR's page.
  // source: 'slack' or 'teams' so the frontend knows which app the context is from.
  function dispatchCtx(ctx, source) {
    if (!ctx || !gatorView || !gatorView.webContents || gatorView.webContents.isDestroyed()) return;
    const event = source === 'teams' ? 'teams:context-changed' : 'slack:context-changed';
    gatorView.webContents
      .executeJavaScript(
        `window.dispatchEvent(new CustomEvent(${JSON.stringify(event)},{detail:${JSON.stringify(ctx)}}));`,
      )
      .catch(() => {});
  }

  // In-app context update: lightweight property set + module function call.
  // Does NOT re-inject. The module uses this for live tooltip + click context.
  function updateAppCtx(view, ctx) {
    if (!view || !view.webContents || view.webContents.isDestroyed()) return;
    const json = JSON.stringify(ctx);
    view.webContents
      .executeJavaScript(
        'window.__gatorCurrentCtx=' +
          json +
          ';if(window.__gatorSetCtx)window.__gatorSetCtx(' +
          json +
          ');',
      )
      .catch(() => {});
  }

  // Watch Slack URL for changes (Slack uses real URL routing).
  // Teams intentionally has no equivalent — Teams /v2 never updates
  // location.href on navigation; Teams context comes from DOM injection only.
  setInterval(() => {
    try {
      if (!slackView || !slackView.webContents || slackView.webContents.isDestroyed()) return;
      const url = slackView.webContents.getURL();
      if (url && url !== lastUrl) {
        lastUrl = url;
        saveLastSlackUrl(url);
        const ctx = parseSlackUrl(url);
        if (ctx) {
          lastCtx = ctx;
          dispatchCtx(ctx, 'slack');
          updateAppCtx(slackView, ctx);
        }
      }
    } catch {}
  }, 750);

  // Early context re-dispatch (startup race fix — Slack only).
  const earlyPoll = setInterval(() => {
    if (lastCtx) {
      dispatchCtx(lastCtx, 'slack');
      ctxDispatchCount++;
    }
    if (ctxDispatchCount > 5) clearInterval(earlyPoll);
  }, 3000);
  gatorView.webContents.on('dom-ready', () => {
    if (lastCtx) dispatchCtx(lastCtx, 'slack');
  });

  // ── Pin module: inject ONCE on Slack dom-ready ──────────────────────
  // Sentinel guard (__gatorPinModule) prevents double-injection.
  // On hard reload, page context is wiped → sentinel is gone → re-injects.
  slackView.webContents.on('dom-ready', () => {
    if (!slackView || !slackView.webContents || slackView.webContents.isDestroyed()) return;
    slackView.webContents
      .executeJavaScript(
        `
(function() {
if (window.__gatorPinModule) return;
window.__gatorPinModule = true;

var GATOR_SVG = '<svg width="16" height="16" viewBox="0 0 26 26" style="display:block"><rect x="1" y="1" width="22" height="18" rx="5" fill="#16a34a"/><polygon points="4,19 2,24 9,19" fill="#16a34a"/><circle cx="8.5" cy="7.5" r="2.2" fill="white"/><circle cx="8.5" cy="7.5" r="1.1" fill="#052e16"/><circle cx="17.5" cy="7.5" r="2.2" fill="white"/><circle cx="17.5" cy="7.5" r="1.1" fill="#052e16"/><rect x="5" y="12" width="16" height="5" rx="2.5" fill="#15803d"/><rect x="8" y="11" width="2" height="2.5" rx=".6" fill="white"/><rect x="12" y="11" width="2" height="2.5" rx=".6" fill="white"/><rect x="16" y="11" width="2" height="2.5" rx=".6" fill="white"/></svg>';
var CHECK_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
// Pin icon (white, for use inside the green circle pin button)
var PIN_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="white" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/></svg>';

var currentCtx = { channel: null, thread_ts: null };
window.__gatorCurrentCtx = currentCtx;
window.__gatorSetCtx = function(ctx) {
  currentCtx = ctx;
  window.__gatorCurrentCtx = ctx;
  var btn = document.getElementById('__gator_pin_header');
  if (btn) {
    var isInThread = !!document.querySelector('.p-flexpane_header__primary');
    var kind = isInThread ? 'thread' : (ctx.channel && ctx.channel.startsWith('D') ? 'conversation' : 'channel');
    btn.title = 'Pin to Gator: ' + kind + ' ' + (ctx.label || ctx.channel);
  }
};

// Build a PIN button (green circle with white pin icon inside).
function buildGatorBtn(id, tooltip, onClick, size) {
  var s = size || 28;
  var btn = document.createElement('button');
  if (id) btn.id = id;
  btn.title = tooltip;
  btn.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:' + s + 'px;height:' + s + 'px;border:0;border-radius:50%;background:#1f6f3f;cursor:pointer;flex-shrink:0;transition:background .15s,transform .1s;padding:0;overflow:hidden;vertical-align:middle;box-sizing:border-box';
  btn.innerHTML = PIN_SVG;
  btn.onmouseenter = function() { btn.style.background = '#2a8a4f'; };
  btn.onmouseleave = function() { btn.style.background = '#1f6f3f'; };
  btn.onmousedown = function() { btn.style.transform = 'scale(0.9)'; };
  btn.onmouseup = function() { btn.style.transform = 'scale(1)'; };
  btn.onclick = function(e) { e.preventDefault(); e.stopPropagation(); onClick(btn); };
  return btn;
}

// Header click — reads LIVE context, with URL fallback.
function headerClick(b) {
  var ctx = window.__gatorCurrentCtx || currentCtx;
  // Fallback: if ctx.channel is null, parse from the URL directly.
  if (!ctx || !ctx.channel) {
    try {
      var u = location.href;
      var parts = u.split('/').filter(function(p) { return p; });
      if (parts.length >= 3 && parts[0] === 'client') {
        ctx = { team: parts[1], channel: parts[2], thread_ts: null };
        var ti = parts.indexOf('thread');
        if (ti !== -1 && parts[ti+1]) ctx.thread_ts = parts[ti+1];
      }
    } catch(e) {}
  }
  var isInThread = !!document.querySelector('.p-flexpane_header__primary');

  // Thread ts: try URL, then DOM (data-thread-ts).
  var threadTs = ctx.thread_ts;
  if (isInThread && !threadTs) {
    var m = new RegExp('/thread/([0-9.]+)').exec(location.href);
    if (m) { threadTs = m[1]; }
  }
  if (isInThread && !threadTs) {
    var threadEl = document.querySelector('[data-thread-ts]');
    if (threadEl) { threadTs = threadEl.getAttribute('data-thread-ts'); }
  }

  // Label: read from the page's header element.
  var label = ctx.label || ctx.channel;
  if (isInThread) {
    var flexText = (document.querySelector('.p-flexpane_header__primary') || {}).textContent || '';
    if (flexText) { label = flexText.replace(/^Thread/i, '').trim() || flexText.trim(); }
  } else {
    var nameEl = document.querySelector('[data-testid="channel_name"],[data-qa="channel_name"],.p-view_header__channel_name,[data-testid="channel_name_text"],[data-testid="conversation_name"]');
    if (nameEl) label = nameEl.textContent.trim();
  }

  // Determine kind.
  var kind = 'channel';
  if (isInThread) kind = 'thread';
  else if (ctx.channel && ctx.channel.startsWith('D')) kind = 'conversation';

  // CRITICAL: set __gatorPinCtx (NOT __gatorSetCtx) — shell polls this.
  window.__gatorPinCtx = {
    channel: ctx.channel,
    thread_ts: threadTs || null,
    label: label,
    kind: kind,
    ts: null,
  };
  b.innerHTML = CHECK_SVG; b.style.background = '#0a4a2a';
  setTimeout(function() { b.innerHTML = PIN_SVG; b.style.background = '#1f6f3f'; }, 1200);
}

// Idempotent header scan — only acts if button missing or misplaced.
function scanHeader() {
  var actionsEl = document.querySelector('.p-view_header__actions, .p-flexpane_header__primary');
  if (!actionsEl) return;
  var existing = document.getElementById('__gator_pin_header');
  // Correctly placed? Done — don't touch (prevents flicker/hover loss).
  if (existing && existing.parentNode === actionsEl) return;
  // Missing or stale — clean duplicates, create one.
  document.querySelectorAll('#__gator_pin_header').forEach(function(el) { el.remove(); });
  var ctx = window.__gatorCurrentCtx || currentCtx;
  var isInThread = !!document.querySelector('.p-flexpane_header__primary');
  var kind = isInThread ? 'thread' : (ctx.channel && ctx.channel.startsWith('D') ? 'conversation' : 'channel');
  var hdrBtn = buildGatorBtn('__gator_pin_header', 'Pin to Gator: ' + kind + ' ' + (ctx.label || ctx.channel), headerClick);
  var moreBtn = [...actionsEl.querySelectorAll('button')].find(function(b) {
    return /^more (channel|conversation|thread) actions/i.test(b.getAttribute('aria-label') || '');
  });
  if (moreBtn) actionsEl.insertBefore(hdrBtn, moreBtn);
  else if (actionsEl.lastElementChild) actionsEl.insertBefore(hdrBtn, actionsEl.lastElementChild);
  else actionsEl.appendChild(hdrBtn);
}

// Message pin scan — idempotent (only injects if missing).
function msgForMoreBtn(moreBtn) {
  return moreBtn.closest('[data-ts],[data-item-key],.c-message_kit__hover,.c-virtual_list__item');
}
function tsFromMsg(msg) {
  if (!msg) return null;
  var el = msg.matches('[data-ts]') ? msg : msg.querySelector('[data-ts]');
  if (el) { var ts = el.getAttribute('data-ts'); if (ts) return ts; }
  el = msg.closest('[data-ts]');
  return el ? el.getAttribute('data-ts') : (msg.getAttribute('data-item-key') || null);
}
function textFromMsg(msg) {
  if (!msg) return '';
  var te = msg.querySelector('[data-testid="message_text"],.c-message__body,.p-rich_text_section,[data-testid="message_body"]');
  return te ? te.textContent.trim() : '';
}
function injectNextToMore(moreBtn) {
  var bar = moreBtn.parentNode;
  if (!bar || bar.querySelector('.__gator_pin_msg')) return;
  var msg = msgForMoreBtn(moreBtn);
  var ts = tsFromMsg(msg);
  if (!ts) return;
  var text = textFromMsg(msg);
  var lbl = (text || '').replace(/\\s+/g, ' ').slice(0, 50);
  if (text && text.length > 50) lbl += '...';
  var ctx = window.__gatorCurrentCtx || currentCtx;
  // Fallback: if ctx.channel is null, parse from URL.
  if (!ctx || !ctx.channel) {
    try {
      var parts = location.href.split('/').filter(function(p) { return p; });
      if (parts.length >= 3 && parts[0] === 'client') {
        ctx = { team: parts[1], channel: parts[2], thread_ts: null };
        var ti = parts.indexOf('thread');
        if (ti !== -1 && parts[ti+1]) ctx.thread_ts = parts[ti+1];
      }
    } catch(e) {}
  }
  // If in a thread view, extract thread_ts from the DOM (data-thread-ts).
  var liveThreadTs = ctx.thread_ts;
  if (!liveThreadTs) {
    var isInThread = !!document.querySelector('.p-flexpane_header__primary');
    if (isInThread) {
      var threadEl = document.querySelector('[data-thread-ts]');
      if (threadEl) liveThreadTs = threadEl.getAttribute('data-thread-ts');
    }
  }
  var b = buildGatorBtn('', 'Pin to Gator: ' + (lbl || ('message ' + ts)), function(btn) {
    // CRITICAL: set __gatorPinCtx — reads live context at click time.
    window.__gatorPinCtx = {
      channel: ctx.channel, thread_ts: liveThreadTs || null,
      label: lbl || ('message ' + ts), kind: 'message', ts: ts,
    };
    btn.innerHTML = CHECK_SVG; btn.style.background = '#0a4a2a';
    setTimeout(function() { btn.innerHTML = PIN_SVG; btn.style.background = '#1f6f3f'; }, 1200);
  }, 28);
  b.className = '__gator_pin_msg';
  b.setAttribute('data-gator-ts', ts);
  bar.insertBefore(b, moreBtn);
}
function scanMessages() {
  var msgPane = document.querySelector('[data-testid="message-pane"], .p-message_pane, [class*=message_pane]');
  if (!msgPane) msgPane = document.body;
  [...msgPane.querySelectorAll('button[aria-label]')].forEach(function(b) {
    var a = b.getAttribute('aria-label') || '';
    if (b.closest('.p-channel_sidebar, .p-workspace__sidebar')) return;
    if (/^more actions/i.test(a) || /more message actions/i.test(a)) injectNextToMore(b);
  });
}

function scanAll() { scanHeader(); scanMessages(); }

// Debounced MutationObserver (prevents scroll jank on large channels).
var scanQueued = false;
var obs = new MutationObserver(function() {
  if (scanQueued) return;
  scanQueued = true;
  requestAnimationFrame(function() { scanQueued = false; scanAll(); });
});
obs.observe(document.body, { childList: true, subtree: true });

// Safety-net interval (catches anything the observer misses).
setInterval(scanAll, 2000);

// Initial scan.
setTimeout(scanAll, 500);
})();
    `,
      )
      .catch((e) => {
        try {
          fs.appendFileSync(
            path.join(__dirname, 'pin-debug.log'),
            'INJECT ERROR: ' + e.message + '\n',
          );
        } catch {}
      });
  });

  // ── Pin forwarding: poll active app view for __gatorPinCtx ──────────
  // Generalized for Slack and Teams. The source ('slack'|'teams') is passed
  // through so the chip and /api/context/pin payload carry the right source.
  // For OneNote, the pin ctx lives in the cross-origin editor SUBFRAME
  // (onenoteframe.aspx), not the top frame — read/clear it there via
  // webFrameMain. Returns the subframe or null.
  function _onenotePinFrame() {
    if (!onenoteView || !onenoteView.webContents || onenoteView.webContents.isDestroyed())
      return null;
    try {
      const frames = onenoteView.webContents.mainFrame.framesInSubtree;
      for (const fr of frames) {
        if (fr && fr.url && /onenoteframe\.aspx/i.test(fr.url)) return fr;
      }
    } catch {}
    return null;
  }

  // Track child BrowserWindows opened for OneNote notebooks so we can poll
  // their OOPIFs for pin clicks. Cleaned up automatically on window close.
  const _onenoteChildWindows = new Set();

  // Find the onenoteframe OOPIF in any tracked child window.
  function _onenoteChildPinFrames() {
    const frames = [];
    for (const child of _onenoteChildWindows) {
      try {
        if (child.isDestroyed()) continue;
        for (const fr of child.webContents.mainFrame.framesInSubtree) {
          if (fr && fr.url && /onenoteframe\.aspx/i.test(fr.url)) frames.push(fr);
        }
      } catch {}
    }
    return frames;
  }

  function _forwardPinFromView(view, source) {
    if (!view || !view.webContents || view.webContents.isDestroyed()) return;
    // OneNote: poll the main view's OOPIF AND any open child window OOPIFs.
    if (source === 'onenote') {
      const allFrames = [];
      const mainFr = _onenotePinFrame();
      if (mainFr) allFrames.push(mainFr);
      allFrames.push(..._onenoteChildPinFrames());
      for (const fr of allFrames) {
        _forwardPinFromFrame(fr, source);
      }
      return;
    }
    // All other apps: read from the top frame.
    _forwardPinFromFrame(view.webContents, source);
  }

  function _forwardPinFromFrame(readTarget, source) {
    if (!readTarget) return;
    readTarget
      .executeJavaScript('window.__gatorPinCtx || null')
      .then((ctx) => {
        if (!ctx) return;
        try {
          readTarget.executeJavaScript('window.__gatorPinCtx = null;');
        } catch {}
        if (!gatorView || !gatorView.webContents || gatorView.webContents.isDestroyed()) return;
        var pinId = ctx.channel || ctx.id || '';
        if (ctx.thread_ts) pinId += ':' + ctx.thread_ts;
        if (ctx.ts && ctx.kind === 'message') pinId += ':' + ctx.ts;
        var pinLabel = ctx.label || ctx.channel || ctx.id || source;
        var pinKind = ctx.kind || 'channel';
        if (pinKind === 'thread') pinLabel += ' (thread)';
        // Insert the chip via Gator's own canonical helper so shell-pinned
        // chips are IDENTICAL to Shift+{ dropdown chips (same icon+label, no X
        // button, no trailing line/space). See window.insertPinChipAtCaret in
        // web/static/app.js. Also keep _nativeSlack._currentCtx in sync for
        // Slack so the send handler has the live context.
        const pinArg = JSON.stringify({ source: source, id: pinId, label: pinLabel });
        gatorView.webContents
          .executeJavaScript(
            `
(function() {
  var pin = ${pinArg};
  var r = (typeof window.insertPinChipAtCaret === 'function')
    ? window.insertPinChipAtCaret(pin) : 'no helper';
  if (${JSON.stringify(source)} === 'slack' && typeof _nativeSlack !== 'undefined') {
    _nativeSlack._currentCtx = { channel: ${JSON.stringify(ctx.channel || null)}, thread_ts: ${JSON.stringify(ctx.thread_ts || null)}, ts: ${JSON.stringify(ctx.ts || null)}, label: ${JSON.stringify(pinLabel)}, kind: ${JSON.stringify(pinKind)} };
  }
  return r;
})();
        `,
          )
          .then((r) => {
            try {
              fs.appendFileSync(
                path.join(__dirname, 'pin-debug.log'),
                'GATOR [' + source + ']: ' + r + '\n',
              );
            } catch {}
            gatorView.webContents
              .executeJavaScript(
                'typeof _activeTabId !== "undefined" && _activeTabId ? _activeTabId : "default"',
              )
              .catch(() => 'default')
              .then((activeTabId) => {
                const pinMeta = {};
                if (ctx.kind) pinMeta.kind = ctx.kind;
                if (ctx.ts) pinMeta.message_ts = ctx.ts;
                if (ctx.channel) pinMeta.channel = ctx.channel;
                if (ctx.notebook) pinMeta.notebook = ctx.notebook; // OneNote: notebook name for title-search
                if (ctx.web_url) pinMeta.web_url = ctx.web_url; // OneDrive/OneNote/Confluence/Jira/GitHub: deep-link URL
                if (ctx.location) pinMeta.location = ctx.location; // OneDrive: SharePoint site/library name
                const pinPayload = JSON.stringify({
                  source: source,
                  id: pinId,
                  label: pinLabel,
                  context_id: activeTabId || 'default',
                  meta: pinMeta,
                });
                const pinReq = http.request(GATOR_URL + '/api/context/pin', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(pinPayload),
                  },
                });
                pinReq.on('error', (e) => {
                  try {
                    fs.appendFileSync(
                      path.join(__dirname, 'pin-debug.log'),
                      'PIN PERSIST ERR: ' + e.message + '\n',
                    );
                  } catch {}
                });
                pinReq.on('response', (res) => {
                  let body = '';
                  res.on('data', (c) => (body += c));
                  res.on('end', () => {
                    try {
                      fs.appendFileSync(
                        path.join(__dirname, 'pin-debug.log'),
                        'PIN PERSIST OK: ' + res.statusCode + ' ' + body + '\n',
                      );
                    } catch {}
                    if (
                      gatorView &&
                      gatorView.webContents &&
                      !gatorView.webContents.isDestroyed()
                    ) {
                      gatorView.webContents
                        .executeJavaScript(
                          'if(typeof _refreshPinOrb==="function"){_refreshPinOrb(true);"refreshed";}else{"no _refreshPinOrb";}',
                        )
                        .then(function (r) {
                          try {
                            fs.appendFileSync(
                              path.join(__dirname, 'pin-debug.log'),
                              'ORB REFRESH: ' + r + '\n',
                            );
                          } catch {}
                        })
                        .catch(function (e) {
                          try {
                            fs.appendFileSync(
                              path.join(__dirname, 'pin-debug.log'),
                              'ORB ERR: ' + e.message + '\n',
                            );
                          } catch {}
                        });
                    }
                  });
                });
                pinReq.write(pinPayload);
                pinReq.end();
                try {
                  fs.appendFileSync(
                    path.join(__dirname, 'pin-debug.log'),
                    'PIN PERSIST SENT to ' + GATOR_URL + ': ' + pinPayload + '\n',
                  );
                } catch {}
              });
          })
          .catch((e) => {
            try {
              fs.appendFileSync(
                path.join(__dirname, 'pin-debug.log'),
                'GATOR ERR: ' + e.message + '\n',
              );
            } catch {}
          });
      })
      .catch(() => {});
  }

  setInterval(() => {
    if (activeExternalApp === 'slack') _forwardPinFromView(slackView, 'slack');
    else if (activeExternalApp === 'teams') _forwardPinFromView(teamsView, 'teams');
    // Outlook pins use source 'email' so they reuse the entire existing email
    // pin infrastructure (icon mapping, chat.py PINNED CONTEXT block, backend).
    else if (activeExternalApp === 'outlook') _forwardPinFromView(outlookView, 'email');
    // OneDrive pins use source 'onedrive'. No-op until Phase 2 injects the pin
    // module; _forwardPinFromView reads __gatorPinCtx (undefined → returns early).
    else if (activeExternalApp === 'onedrive') _forwardPinFromView(onedriveView, 'onedrive');
    // OneNote: poll the main view when active AND always poll any open child
    // windows — child windows stay open even when the user switches to another
    // native pane, so their pin clicks must forward regardless of activeExternalApp.
    if (activeExternalApp === 'onenote') _forwardPinFromView(onenoteView, 'onenote');
    else if (activeExternalApp === 'confluence') _forwardPinFromView(confluenceView, 'confluence');
    else if (activeExternalApp === 'jira') _forwardPinFromView(jiraView, 'jira');
    else if (activeExternalApp === 'github') _forwardPinFromView(githubView, 'github');
    // Always poll OneNote child window OOPIFs (independent of active app).
    for (const fr of _onenoteChildPinFrames()) {
      _forwardPinFromFrame(fr, 'onenote');
    }
  }, 300);

  // ── Slack unread badge poller ────────────────────────────────────────
  // The Slack Web API token is for a different/old workspace, so we can't
  // fetch unread counts via conversations.list. Instead, read the count
  // directly from the Slack WebContentsView's DOM: Slack marks unread
  // channels/DMs with .p-channel_sidebar__channel--unread. Forward the count
  // to the Gator view's updateRailBadge so the dock badge stays in sync.
  // Runs regardless of which app is active (Slack is always loaded).
  let _lastSlackUnread = -1;
  setInterval(() => {
    if (!slackView || !slackView.webContents || slackView.webContents.isDestroyed()) return;
    // The Slack view may be hidden (setVisible(false)) but its DOM is still
    // live — executeJavaScript works on hidden views.
    slackView.webContents
      .executeJavaScript('document.querySelectorAll(".p-channel_sidebar__channel--unread").length')
      .then((count) => {
        if (typeof count !== 'number') return;
        if (count === _lastSlackUnread) return; // no change
        _lastSlackUnread = count;
        if (gatorView && gatorView.webContents && !gatorView.webContents.isDestroyed()) {
          gatorView.webContents
            .executeJavaScript(
              'if(typeof updateRailBadge==="function"){updateRailBadge("slack",' + count + ');}',
            )
            .catch(() => {});
        }
      })
      .catch(() => {});
  }, 15000);

  // Pass a getter for the active external view so Back/Forward in the Navigate
  // menu target OneDrive/OneNote/etc. MenuItem.enabled is mutated live by a
  // poller — no menu rebuild needed on every navigation event.
  const {
    menu: appMenu,
    backItem: _backItem,
    forwardItem: _fwdItem,
  } = require('./menu')(
    IS_MAC,
    () => viewForApp(activeExternalApp),
    (contents, hard) => {
      if (
        !gatorView ||
        gatorView.webContents.isDestroyed() ||
        contents.id !== gatorView.webContents.id
      )
        return false;
      if (hard)
        gatorView.webContents.session
          .clearCache()
          .finally(() => gatorView.webContents.loadURL(GATOR_URL));
      else gatorView.webContents.loadURL(GATOR_URL);
      return true;
    },
  );
  Menu.setApplicationMenu(appMenu);
  // Poll canGoBack/canGoForward every 500ms and update the menu items directly.
  setInterval(() => {
    const v = viewForApp(activeExternalApp);
    const wc = v && !v.webContents.isDestroyed() ? v.webContents : null;
    _backItem.enabled = !!(wc && wc.navigationHistory.canGoBack());
    _fwdItem.enabled = !!(wc && wc.navigationHistory.canGoForward());
  }, 500);
}

// ── Tiling layout ─────────────────────────────────────────────────────
let gatorVisible = true;
// Tracks the toolbar's last-set visibility so we only call setVisible() on
// state changes (not every layout pass) — prevents dock-rail flicker.
let _toolbarVisible = false;

// Coalesce layout() calls. A single app switch fires a burst of IPC calls from
// the renderer (hideSlack + hideTeams + hideOutlook + hideOneDrive + hideOneNote
// + hideJira + showConfluence — 7 calls), and each used to run a full layout
// pass. The hide calls momentarily set activeExternalApp = null, so the rail
// would visibly jump to full-Gator-width for a frame and then snap back to the
// split — the flicker/movement the user sees. By deferring the actual layout to
// the next tick and collapsing the burst into ONE pass, only the final state
// (the newly-shown app, split) is ever painted. No intermediate frames.
let _layoutScheduled = false;
function layout() {
  if (_layoutScheduled) return;
  _layoutScheduled = true;
  setImmediate(() => {
    _layoutScheduled = false;
    try {
      _layoutNow();
    } catch (_) {}
  });
}

function _layoutNow() {
  if (!win) return;
  const [w, h] = win.getContentSize();
  const activeView = viewForApp(activeExternalApp);

  // Toggle visibility via the View.setVisible() API rather than moving the
  // inactive view off-screen or shrinking it to 1px — both of those blank the
  // renderer's compositor (Slack/Teams go white). setVisible(false) cleanly
  // hides a WebContentsView without destroying its rendering surface, so it
  // repaints instantly when shown again.
  if (slackView && slackView.setVisible) slackView.setVisible(activeExternalApp === 'slack');
  if (teamsView && teamsView.setVisible) teamsView.setVisible(activeExternalApp === 'teams');
  if (outlookView && outlookView.setVisible)
    outlookView.setVisible(activeExternalApp === 'outlook');
  if (onedriveView && onedriveView.setVisible)
    onedriveView.setVisible(activeExternalApp === 'onedrive');
  if (onenoteView && onenoteView.setVisible)
    onenoteView.setVisible(activeExternalApp === 'onenote');
  if (confluenceView && confluenceView.setVisible)
    confluenceView.setVisible(activeExternalApp === 'confluence');
  if (jiraView && jiraView.setVisible) jiraView.setVisible(activeExternalApp === 'jira');
  if (githubView && githubView.setVisible) githubView.setVisible(activeExternalApp === 'github');

  // Toolbar: shown only when an external app is active. Sits flush at the top
  // of the external app's tile (x:0, width = external app width, height =
  // TOOLBAR_H), and the external app's bounds start at y = TOOLBAR_H so they
  // don't overlap. Gator's topbar is its own fixed-position element inside the
  // Gator renderer — Gator's bounds are NOT offset by the toolbar (the toolbar
  // only covers the external app's side of the split).
  //
  // Only call setVisible() when the visibility STATE changes — calling it
  // every layout pass (even with the same value) triggers a synchronous
  // recomposite that makes the right dock rail flicker during app switches.
  const showToolbar = !!activeView && !!toolbarView;
  if (toolbarView && toolbarView.setVisible && _toolbarVisible !== showToolbar) {
    _toolbarVisible = showToolbar;
    toolbarView.setVisible(showToolbar);
  }

  if (!gatorVisible && activeView) {
    // App-full: active external app takes most of the window. Gator squeezed to dock width.
    const gatorSliver = STICKY_RIGHT_RAIL ? DOCK_W : 1;
    const extW = w - gatorSliver;
    if (showToolbar) {
      toolbarView.setBounds({ x: 0, y: 0, width: extW, height: TOOLBAR_H });
      activeView.setBounds({ x: 0, y: TOOLBAR_H, width: extW, height: h - TOOLBAR_H });
    } else {
      activeView.setBounds({ x: 0, y: 0, width: extW, height: h });
    }
    gatorView.setBounds({ x: w - gatorSliver, y: 0, width: gatorSliver, height: h });
    _syncGatorSplit(false);
  } else if (activeView) {
    // Split: external app docks on the LEFT, Gator fills the remaining width.
    // Leave a 1px gap between the two WebContentsViews so Gator's border-left
    // renders as a visible seam rather than overlapping the external app's edge.
    const SEAM = 1;
    const gatorW = Math.max(w - extTileWidth, GATOR_MIN_WIDTH);
    const extW = w - gatorW;
    if (showToolbar) {
      toolbarView.setBounds({ x: 0, y: 0, width: extW - SEAM, height: TOOLBAR_H });
      activeView.setBounds({ x: 0, y: TOOLBAR_H, width: extW - SEAM, height: h - TOOLBAR_H });
    } else {
      activeView.setBounds({ x: 0, y: 0, width: extW - SEAM, height: h });
    }
    gatorView.setBounds({ x: extW, y: 0, width: gatorW, height: h });
    _syncGatorSplit(true);
  } else {
    // No external app visible — Gator takes the full window.
    gatorView.setBounds({ x: 0, y: 0, width: w, height: h });
    _syncGatorSplit(false);
  }

  // After any layout change, sync the toolbar's state so the URL/back-forward
  // reflect the now-active app immediately (not just on the next nav event).
  if (showToolbar) _toolbarPushState();
}

function parseSlackUrl(url) {
  try {
    const u = new URL(url);
    if (!u.hostname.endsWith('slack.com')) return null;
    const parts = u.pathname.split('/').filter(Boolean);
    if (parts.length < 3 || parts[0] !== 'client') return null;
    const idx = parts.indexOf('thread');
    return { team: parts[1], channel: parts[2], thread_ts: idx !== -1 ? parts[idx + 1] : null };
  } catch {
    return null;
  }
}

// ── IPC ────────────────────────────────────────────────────────────────

// When Gator is squeezed down to the sticky dock sliver (DOCK_W), any
// third-pane app (Teams/OneNote/etc.) that's still open has a hard
// min-width (530px) it doesn't know to give up — it overflows the tiny
// viewport and pushes/clips the dock (and the logo above it) out of place.
// Force it (and the fixed-position agents-pane, same risk) to collapse
// instantly via a body class instead of fighting the flex layout for space.
// Cleared the moment Gator is shown again, snapping back to normal.
function _syncGatorSqueezed(squeezed) {
  if (!gatorView || !gatorView.webContents || gatorView.webContents.isDestroyed()) return;
  gatorView.webContents
    .executeJavaScript("document.body.classList.toggle('gator-squeezed', " + squeezed + ');')
    .catch(() => {});
}

function _syncGatorSplit(split) {
  if (!gatorView || !gatorView.webContents || gatorView.webContents.isDestroyed()) return;
  gatorView.webContents
    .executeJavaScript("document.body.classList.toggle('gator-split', " + split + ');')
    .catch(() => {});
}

// Generic external-pane IPC — used by both Slack and Teams.
// The Gator view manages its own spin state (no shell→view push).
// If the app is ALREADY active, dock-click reloads its home URL — a "take me
// home" action that rescues users who navigated away (e.g. clicked an org logo
// in Outlook that left the app). Without this, the user is stuck on a foreign
// page with no way back, because show on an already-active app was a no-op.
const APP_HOME_URL = {
  slack: SLACK_URL,
  teams: TEAMS_URL,
  outlook: OUTLOOK_URL,
  onedrive: ONEDRIVE_URL,
  onenote: ONENOTE_URL,
  confluence: CONFLUENCE_URL,
  jira: JIRA_URL,
  github: GITHUB_URL,
};
ipcMain.handle('external-pane:show', async (_e, appName) => {
  let view = viewForApp(appName);
  if (appName === 'github' && !view) view = await ensureGitHubView();
  if (!view) return false;
  if (activeExternalApp === appName && view.webContents && !view.webContents.isDestroyed()) {
    const home = appName === 'github' ? GITHUB_URL : APP_HOME_URL[appName];
    if (home) {
      try {
        view.webContents.loadURL(home);
      } catch {}
    }
  } else {
    activeExternalApp = appName;
  }
  layout();
  return true;
});
ipcMain.handle('github-pane:refresh', async (_e, baseUrl) => {
  const nextUrl = normalizeWebUrl(baseUrl);
  if (!nextUrl) return false;
  GITHUB_URL = nextUrl;
  const view = await ensureGitHubView();
  if (!view) return false;
  try {
    await view.webContents.loadURL(GITHUB_URL);
    return true;
  } catch (error) {
    console.error(`[github] could not refresh ${GITHUB_URL}: ${error.message}`);
    return false;
  }
});
ipcMain.handle('external-pane:hide', (_e, appName) => {
  if (activeExternalApp === appName) {
    activeExternalApp = null;
    layout();
  }
});
ipcMain.handle('external-pane:go-back', (_e, appName) => {
  const v = viewForApp(appName || activeExternalApp);
  if (v && !v.webContents.isDestroyed())
    try {
      v.webContents.navigationHistory.goBack();
    } catch {}
});
ipcMain.handle('external-pane:go-forward', (_e, appName) => {
  const v = viewForApp(appName || activeExternalApp);
  if (v && !v.webContents.isDestroyed())
    try {
      v.webContents.navigationHistory.goForward();
    } catch {}
});
ipcMain.handle('external-pane:can-navigate', (_e, appName) => {
  const v = viewForApp(appName || activeExternalApp);
  if (!v || v.webContents.isDestroyed()) return { canGoBack: false, canGoForward: false };
  try {
    const nav = v.webContents.navigationHistory;
    return { canGoBack: nav.canGoBack(), canGoForward: nav.canGoForward() };
  } catch {
    return { canGoBack: false, canGoForward: false };
  }
});
ipcMain.handle('external-pane:set-width', (_e, _appName, width) => {
  const [w] = win ? win.getContentSize() : [1600];
  extTileWidth = Math.max(350, Math.min(width, w - GATOR_MIN_WIDTH));
  layout();
});
ipcMain.handle('external-pane:adjust-width', (_e, _appName, delta) => {
  const [w] = win ? win.getContentSize() : [1600];
  extTileWidth = Math.max(350, Math.min(extTileWidth + delta, w - GATOR_MIN_WIDTH));
  layout();
});
ipcMain.handle('external-pane:get-width', () => extTileWidth);

// Backwards-compatible Slack aliases — existing preload.js and third-pane.js
// calls continue to work without changes.
ipcMain.handle('slack-pane:show', () => {
  activeExternalApp = 'slack';
  layout();
});
ipcMain.handle('slack-pane:hide', () => {
  if (activeExternalApp === 'slack') {
    activeExternalApp = null;
    layout();
  }
});
ipcMain.handle('slack-pane:set-width', (_e, width) => {
  const [w] = win ? win.getContentSize() : [1600];
  extTileWidth = Math.max(350, Math.min(width, w - GATOR_MIN_WIDTH));
  layout();
});
ipcMain.handle('slack-pane:adjust-width', (_e, delta) => {
  const [w] = win ? win.getContentSize() : [1600];
  extTileWidth = Math.max(350, Math.min(extTileWidth + delta, w - GATOR_MIN_WIDTH));
  layout();
});
ipcMain.handle('slack-pane:get-width', () => extTileWidth);

// Navigate the Slack WebContentsView to a pinned channel/thread. The pin only
// stores channel[:thread_ts[:msg_ts]] — NOT the workspace/team id — so we read
// the team id from the Slack view's current /client/<TEAM>/... URL (it's always
// signed into one workspace) and build the deep link here.
//   channel        -> /client/<team>/<channel>
//   channel + ts    -> /client/<team>/<channel>/thread/<channel>-<thread_ts>
ipcMain.handle('slack-pane:navigate-pin', (_e, pinId) => {
  if (!slackView || slackView.webContents.isDestroyed() || !pinId) return false;
  try {
    const cur = slackView.webContents.getURL();
    const m = /\/client\/([^/]+)/.exec(cur || '');
    const team = m ? m[1] : null;
    if (!team) return false; // not signed in / unknown workspace
    const parts = String(pinId).split(':');
    const channel = parts[0];
    const threadTs = parts[1];
    if (!channel) return false;
    let url = 'https://app.slack.com/client/' + team + '/' + channel;
    if (threadTs) url += '/thread/' + channel + '-' + threadTs;
    slackView.webContents.loadURL(url);
    activeExternalApp = 'slack';
    layout();
    return true;
  } catch {
    return false;
  }
});

// Navigate the Teams WebContentsView to a pinned conversation via the
// /l/message/<threadId>/<msgId> deep link — the SAME format the classic
// forward-message feature uses (web/routes/teams.py _extract_forward_context).
//
// KEY MECHANISM (found 2026-07): the deep link must be consumed as an ANCHOR
// CLICK inside the Teams page, NOT via location.assign / webContents.loadURL.
// A real <a href> click routes through Teams' launcher handoff
// (teams.microsoft.com/dl/launcher/...), which then navigates the /v2 web app
// to the target conversation. location.assign/loadURL bypass that handoff and
// leave the app on the last-open conversation. Confirmed working for group
// chats, channels, AND 1:1 DMs.
//
// The launcher may show a "Stay better connected... / Use the web app instead"
// interstitial (esp. for DMs); the injected helper auto-clicks "Use the web
// app instead" so navigation completes without user intervention.
//
// pinId is "<threadId>" or "<threadId>:<msgTs>" (message pins).
ipcMain.handle('teams-pane:navigate-pin', (_e, pinId) => {
  if (!teamsView || teamsView.webContents.isDestroyed() || !pinId) return false;
  try {
    const raw = String(pinId);
    let threadId = raw,
      msgId = '0';
    const m = raw.match(/^(.*?)(?::(\d{6,}))$/);
    if (m) {
      threadId = m[1];
      msgId = m[2];
    }
    if (!threadId.startsWith('19:')) return false; // not a conversation id
    activeExternalApp = 'teams';
    layout();
    // Inject: build the deep-link anchor, click it, and auto-dismiss the
    // launcher interstitial if it appears. Runs entirely in the Teams page.
    teamsView.webContents
      .executeJavaScript(
        `
(function(){
  try {
    var threadId = ${JSON.stringify(threadId)};
    var msgId = ${JSON.stringify(msgId)};
    // Derive the user's own MRI (oid) from the DM thread id when possible.
    // DM thread: 19:{guidA}_{guidB}@unq.gbl.spaces. We can't tell which guid is
    // "me" from the id alone, so omit oid for groups/channels (not needed) and
    // include a best-effort oid for DMs only if the page exposes one.
    var oid = '';
    try {
      var meEl = document.querySelector('[data-tid="me-control-avatar-trigger"] [id^="8:orgid:"], [data-mri^="8:orgid:"]');
      if (meEl) oid = meEl.getAttribute('data-mri') || (meEl.id || '');
    } catch(e){}
    var ctxObj = { contextType: 'chat' };
    if (oid) ctxObj.oid = oid;
    var ctx = encodeURIComponent(JSON.stringify(ctxObj));
    var href = 'https://teams.microsoft.com/l/message/' + encodeURIComponent(threadId) + '/' + msgId + '?context=' + ctx;
    // Remove any prior test anchor.
    document.querySelectorAll('a[data-gator-nav]').forEach(function(el){ el.remove(); });
    var a = document.createElement('a');
    a.href = href;
    a.setAttribute('data-gator-nav', '1');
    a.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none';
    document.body.appendChild(a);
    ['pointerdown','mousedown','mouseup','click'].forEach(function(t){
      a.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window, button: 0 }));
    });
    setTimeout(function(){ try { a.remove(); } catch(e){} }, 200);
    // Auto-dismiss the launcher interstitial ("Use the web app instead") if it
    // appears — poll briefly since it loads async.
    var tries = 0;
    var iv = setInterval(function(){
      tries++;
      var link = [].slice.call(document.querySelectorAll('a,button')).filter(function(e){
        return /use the web app/i.test(e.textContent || '');
      })[0];
      if (link) { link.click(); clearInterval(iv); }
      else if (tries > 20) clearInterval(iv); // ~10s max
    }, 500);
    return 'nav dispatched';
  } catch(e) { return 'ERR ' + e.message; }
})();
    `,
      )
      .catch(() => {});
    return true;
  } catch {
    return false;
  }
});

// Navigate the Outlook WebContentsView to a pinned conversation. OWA uses REAL
// URL routing, so unlike Teams this is a simple loadURL to
// https://outlook.office.com/mail/inbox/id/<convid> (redirects to
// outlook.cloud.microsoft as needed). The pin id is the data-convid value.
ipcMain.handle('outlook-pane:navigate-pin', (_e, convId) => {
  if (!outlookView || outlookView.webContents.isDestroyed() || !convId) return false;
  try {
    const enc = encodeURIComponent(String(convId));
    const url = 'https://outlook.office.com/mail/inbox/id/' + enc;
    outlookView.webContents.loadURL(url);
    activeExternalApp = 'outlook';
    layout();
    return true;
  } catch {
    return false;
  }
});

// Navigate the OneDrive WebContentsView to a pinned file/folder. OneDrive for
// Business uses REAL URL routing, so (like Outlook) this is a simple loadURL
// to the item's web URL — the same URL the classic pane resolves via Graph and
// opens in a browser tab. The pin's web URL is passed in from the renderer
// (p.meta.web_url); if absent, the pane just opens at OneDrive root.
ipcMain.handle('onedrive-pane:navigate-pin', (_e, webUrl) => {
  if (!onedriveView || onedriveView.webContents.isDestroyed()) return false;
  try {
    activeExternalApp = 'onedrive';
    if (webUrl && /^https:\/\//.test(String(webUrl))) {
      onedriveView.webContents.loadURL(String(webUrl));
    } else {
      onedriveView.webContents.loadURL(ONEDRIVE_URL);
    }
    layout();
    return true;
  } catch {
    return false;
  }
});

// Navigate the OneNote WebContentsView to a pinned page. OneNote for the web
// uses REAL URL routing (per-page URLs), so (like Outlook/OneDrive) this is a
// simple loadURL to the page's oneNoteWebUrl — the same URL the classic pane
// resolves via Graph (meta.links.oneNoteWebUrl.href). The pin's web URL is
// passed in from the renderer; if absent, the pane opens at OneNote root.
ipcMain.handle('onenote-pane:navigate-pin', (_e, webUrl) => {
  if (!onenoteView || onenoteView.webContents.isDestroyed()) return false;
  try {
    activeExternalApp = 'onenote';
    if (webUrl && /^https:\/\//.test(String(webUrl))) {
      onenoteView.webContents.loadURL(String(webUrl));
    } else {
      onenoteView.webContents.loadURL(ONENOTE_URL);
    }
    layout();
    return true;
  } catch {
    return false;
  }
});

// Navigate the Confluence WebContentsView to a pinned page.
ipcMain.handle('confluence-pane:navigate-pin', (_e, webUrl) => {
  if (!confluenceView || confluenceView.webContents.isDestroyed()) return false;
  try {
    activeExternalApp = 'confluence';
    if (webUrl && /^https:\/\//.test(String(webUrl))) {
      confluenceView.webContents.loadURL(String(webUrl));
    } else if (CONFLUENCE_URL) {
      confluenceView.webContents.loadURL(CONFLUENCE_URL);
    }
    layout();
    return true;
  } catch {
    return false;
  }
});

// Navigate the Jira WebContentsView to a pinned issue.
ipcMain.handle('jira-pane:navigate-pin', (_e, webUrl) => {
  if (!jiraView || jiraView.webContents.isDestroyed()) return false;
  try {
    activeExternalApp = 'jira';
    if (webUrl && /^https:\/\//.test(String(webUrl))) {
      jiraView.webContents.loadURL(String(webUrl));
    } else if (JIRA_URL) {
      jiraView.webContents.loadURL(JIRA_URL);
    }
    layout();
    return true;
  } catch {
    return false;
  }
});

// Navigate the GitHub WebContentsView to a pinned PR/issue/repo.
ipcMain.handle('github-pane:navigate-pin', (_e, webUrl) => {
  if (!githubView || githubView.webContents.isDestroyed()) return false;
  try {
    activeExternalApp = 'github';
    if (webUrl && /^https:\/\//.test(String(webUrl))) {
      githubView.webContents.loadURL(String(webUrl));
    } else if (GITHUB_URL) {
      githubView.webContents.loadURL(GITHUB_URL);
    }
    layout();
    return true;
  } catch {
    return false;
  }
});

ipcMain.handle('shell:get-active-app', () => activeExternalApp);

// ── Toolbar IPC ──────────────────────────────────────────────────────────
// The toolbar (shell/toolbar.html) sends these as ipcRenderer.send() (fire-
// and-forget) from its button handlers. Back/Forward/Reload target the
// ACTIVE external view — if none is active (shouldn't happen since the
// toolbar is hidden then, but guard anyway), they no-op.
//
// Reload is context-sensitive: when an external app is active, it reloads
// that app's webContents (the user's clear intent — "refresh what I'm
// looking at"). The Gator-data refresh (old #tp-refresh-btn behavior) is
// NOT routed here — that stays in the Gator renderer's third-pane toolbar,
// which is only visible in classic (non-shell) mode.

// Main-window toolbar handlers. Skip events from child-window toolbars
// (child toolbars have their own handlers with sender-ID checks in
// attachToolbarToWindow). The main toolbar's webContents ID is toolbarView.
const _isMainToolbar = (e) =>
  toolbarView &&
  !toolbarView.webContents.isDestroyed() &&
  e.sender.id === toolbarView.webContents.id;

ipcMain.on('toolbar:ready', (e) => {
  if (!_isMainToolbar(e)) return;
  _toolbarPushState();
  _pushThemeToToolbar();
});

// ── Theme IPC (renderer → main → toolbar) ────────────────────────────────
// The Gator renderer's ThemeManager calls this when the user switches themes
// (or when 'system' mode resolves on init). main.js forwards the effective
// theme to the toolbar view, which sets data-theme on its own <html>.
ipcMain.handle('shell:set-theme', (_e, choice) => {
  _effectiveTheme = _resolveTheme(choice);
  _pushThemeToToolbar();
});

// OS theme changes affect 'system' mode — re-resolve and push if needed.
const { nativeTheme } = require('electron');
nativeTheme.on('updated', () => {
  // Re-fetch the user's choice from config (could be 'system') and re-resolve.
  try {
    const url = GATOR_URL.replace(/\/$/, '') + '/api/config';
    const data = JSON.parse(
      require('child_process').execSync(`curl -s "${url}"`, { encoding: 'utf-8', timeout: 5000 }),
    );
    const newEffective = _resolveTheme(data.theme || 'system');
    if (newEffective !== _effectiveTheme) {
      _effectiveTheme = newEffective;
      _pushThemeToToolbar();
    }
  } catch {}
});

ipcMain.on('toolbar:back', (e) => {
  if (!_isMainToolbar(e)) return;
  const v = viewForApp(activeExternalApp);
  if (v && !v.webContents.isDestroyed()) {
    try {
      v.webContents.navigationHistory.goBack();
    } catch {}
  }
});

ipcMain.on('toolbar:forward', (e) => {
  if (!_isMainToolbar(e)) return;
  const v = viewForApp(activeExternalApp);
  if (v && !v.webContents.isDestroyed()) {
    try {
      v.webContents.navigationHistory.goForward();
    } catch {}
  }
});

ipcMain.on('toolbar:reload', (e) => {
  if (!_isMainToolbar(e)) return;
  const v = viewForApp(activeExternalApp);
  if (v && !v.webContents.isDestroyed()) {
    try {
      v.webContents.reload();
    } catch {}
  }
});

ipcMain.on('toolbar:hard-reload', (e) => {
  if (!_isMainToolbar(e)) return;
  const v = viewForApp(activeExternalApp);
  if (v && !v.webContents.isDestroyed()) {
    try {
      v.webContents.reloadIgnoringCache();
    } catch {}
  }
});

ipcMain.on('toolbar:open-in-browser', (e, url) => {
  if (!_isMainToolbar(e)) return;
  if (typeof url === 'string' && /^https:\/\//.test(url)) {
    try {
      shell.openExternal(url);
    } catch {}
  }
});

// Poll nav state (canGoBack/canGoForward) at 500ms so the toolbar buttons
// enable/disable live — complements the did-navigate event push. Same cadence
// as the existing app-menu back/forward poller above; cheap and reliable.
setInterval(() => {
  if (!activeExternalApp) return;
  if (!toolbarView || toolbarView.webContents.isDestroyed()) return;
  const v = viewForApp(activeExternalApp);
  const wc = v && !v.webContents.isDestroyed() ? v.webContents : null;
  if (!wc) return;
  let nav;
  try {
    nav = {
      canGoBack: !!wc.navigationHistory.canGoBack(),
      canGoForward: !!wc.navigationHistory.canGoForward(),
    };
  } catch {
    return;
  }
  try {
    toolbarView.webContents.send('toolbar:state', { nav, url: wc.getURL() || '' });
  } catch {}
}, 500);

// ── Window-control IPC (custom title bar buttons) ────────────────────────
// With titleBarStyle:'hidden' on Windows/Linux, the native min/max/close
// buttons are gone. The toolbar renders its own. macOS keeps its native
// traffic-light buttons (hiddenInset), so we don't render custom controls
// there — but the IPC is available for completeness.
ipcMain.handle('win:minimize', () => {
  if (win) win.minimize();
});
ipcMain.handle('win:maximize-toggle', () => {
  if (!win) return;
  if (win.isMaximized()) {
    win.unmaximize();
    return false;
  }
  win.maximize();
  return true;
});
ipcMain.handle('win:close', () => {
  if (win) win.close();
});
ipcMain.handle('win:is-maximized', () => !!(win && win.isMaximized()));

// Push maximize state to the toolbar so the button icon toggles correctly.
// Fires on OS-level maximize/unmaximize (e.g. double-clicking the drag
// region, Aero Snap, or Win+Up).
let _maximizeListenerAttached = false;
function _attachMaximizeListener() {
  if (_maximizeListenerAttached || !win) return;
  _maximizeListenerAttached = true;
  win.on('maximize', () => {
    if (toolbarView && !toolbarView.webContents.isDestroyed()) {
      toolbarView.webContents.send('toolbar:state', { maximized: true });
    }
  });
  win.on('unmaximize', () => {
    if (toolbarView && !toolbarView.webContents.isDestroyed()) {
      toolbarView.webContents.send('toolbar:state', { maximized: false });
    }
  });
}

// Webview sign-in status per native app. Checks whether the partition has a
// non-expired session cookie for the app's home URL. Used by Settings > Apps
// dashboard to show "Web: ✓ / ✗" alongside the agent-token status.
//
// Returns { signedIn: bool|null } per app — null when the view doesn't exist
// yet or the cookie check failed (e.g. app not loaded yet).
const NATIVE_APP_HOME = {
  slack: { url: 'https://app.slack.com/', partition: SLACK_PARTITION },
  teams: { url: 'https://teams.microsoft.com/v2', partition: TEAMS_PARTITION },
  outlook: { url: 'https://outlook.office.com/mail/', partition: OUTLOOK_PARTITION },
  onedrive: { url: ONEDRIVE_URL, partition: ONEDRIVE_PARTITION },
  onenote: { url: ONENOTE_URL, partition: ONENOTE_PARTITION },
  confluence: {
    url: CONFLUENCE_URL || 'https://www.atlassian.com',
    partition: CONFLUENCE_PARTITION,
  },
  jira: { url: JIRA_URL || 'https://www.atlassian.com', partition: JIRA_PARTITION },
  github: { url: GITHUB_URL || 'https://github.com', partition: GITHUB_PARTITION },
};
ipcMain.handle('native-app:web-status', async (_e, appName) => {
  const cfg = NATIVE_APP_HOME[appName];
  if (!cfg) return { signedIn: null };
  try {
    const ses = session.fromPartition(cfg.partition);
    const cookies = await ses.cookies.get({ url: cfg.url });
    // Any non-expired cookie for the home URL is a strong signal the user has
    // signed in at least once. We don't try to validate the session — that's
    // the web app's job; if the session lapsed, the webview will re-prompt.
    const now = Date.now();
    const live = cookies.some((c) => !c.expirationDate || c.expirationDate * 1000 > now);
    return { signedIn: live };
  } catch {
    return { signedIn: null };
  }
});

// The Gator view's 3-state logo is self-managed — it derives state from
// _paneOpen + _gatorVisible (both local). The shell does NOT push spin state
// to the view via executeJavaScript. The only sync is the one-time
// getActiveApp() call on init to seed _paneOpen.

ipcMain.handle('gator-pane:show', () => {
  gatorVisible = true;
  layout();
  lastHideShow = 'show';
  _syncGatorSqueezed(false);
});
ipcMain.handle('gator-pane:hide', () => {
  // Squeezing Gator down to the dock sliver only makes sense when an external
  // native app (Slack/Teams/Outlook) is present to fill the vacated space.
  // With no active external app, hiding Gator would collapse it to nothing
  // with a blank window behind it AND strand `gator-squeezed` on the body,
  // which zero-widths the third-pane (Calendar/OneDrive/etc.) and clips its
  // toolbar. In that case, keep Gator visible and ensure it's un-squeezed.
  if (!activeExternalApp) {
    gatorVisible = true;
    layout();
    lastHideShow = 'show';
    _syncGatorSqueezed(false);
    return;
  }
  gatorVisible = false;
  layout();
  lastHideShow = 'hide';
  _syncGatorSqueezed(true);
});

// ── Slack OAuth popup (separate window, shares persist:slack) ──────────
// The Settings "Sign in with Slack" flow. This is a SEPARATE BrowserWindow
// (not the native pane) that shares the persist:slack session, so it reuses
// the workspace cookie the pane already holds and goes straight to the consent
// screen — skipping Slack's Enterprise-Grid workspace picker. Because it's an
// intentional standalone window (not the pane), it never hijacks/loops the
// native pane and there are no stray tabs.
//
// The backend callback server on port 3118 exchanges the code and saves the
// token; the callback page does window.close(). We watch for the callback
// redirect and resolve. Returns { ok: bool, error? }.
//
// In browser mode (no shell) the frontend falls back to window.open() on
// Gator's default session (the pre-existing behavior).
let _slackOAuthWin = null;
ipcMain.handle('slack-oauth:open', async (_e, url) => {
  if (!url) return { ok: false, error: 'missing url' };
  // If a previous popup is still open, close it (a new request supersedes).
  try {
    if (_slackOAuthWin && !_slackOAuthWin.isDestroyed()) _slackOAuthWin.close();
  } catch {}

  const slackSession = session.fromPartition(SLACK_PARTITION);
  const popup = new BrowserWindow({
    width: 600,
    height: 720,
    title: 'Sign in with Slack',
    parent: win || undefined,
    autoHideMenuBar: true,
    webPreferences: { session: slackSession, contextIsolation: true, nodeIntegration: false },
  });
  _slackOAuthWin = popup;

  // Reuse the SAME navigation policy the native panes use. Critical for the
  // "Settings-first" case, where persist:slack has no session yet and the popup
  // must run a full SSO sign-in: the chain hops through amd.enterprise.slack.com
  // → amdsso.okta.com (SAML/FastPass) → Microsoft, etc. applyNavigationPolicy
  // allows those auth popups as session-sharing child windows (AUTH_RE), keeps
  // same-host workspace navigations in-window (sameHostPopupPattern), and only
  // sends genuinely-external links to the system browser. A hand-rolled handler
  // that boots non-slack.com opens to the external browser would break Okta SSO.
  applyNavigationPolicy(popup, {
    name: 'slack-oauth',
    homeHosts: ['slack.com'],
    sameHostPopupPattern: /\/huddle\/|\/call\/|\/files\/|\/archives\/.*\/files\/|\/print\//,
  });

  // Attach the custom toolbar so the OAuth popup has back/forward/reload and
  // window controls (matches the main window's frameless style).
  attachToolbarToWindow(popup);

  popup.loadURL(url);

  return new Promise((resolve) => {
    let _resolved = false;
    let _callbackHit = false;
    let _retried = false;
    const done = (result) => {
      if (_resolved) return;
      _resolved = true;
      try {
        if (!popup.isDestroyed()) popup.close();
      } catch {}
      if (_slackOAuthWin === popup) _slackOAuthWin = null;
      resolve(result);
    };
    const onNav = (_ev, navUrl) => {
      if (!navUrl) return;
      if (navUrl.startsWith('http://localhost:3118/callback')) {
        _callbackHit = true;
        // Give the callback server time to exchange the code + save the token,
        // then close the popup.
        setTimeout(() => done({ ok: true }), 3000);
        return;
      }
      // Auto-retry for the COLD (Settings-first) case. When persist:slack has no
      // session, the OAuth authorize URL detours through the workspace picker +
      // SSO, which drops the OAuth state and lands the user in the signed-in
      // workspace (app.slack.com/client/...) WITHOUT reaching consent/callback.
      // That's the "have to click Sign in twice" problem. Detect it: if we land
      // on a signed-in workspace page and haven't hit the callback, the session
      // is now WARM — re-load the same authorize URL once. Warm → straight to
      // consent → callback. One button click covers sign-in AND consent.
      if (!_retried && !_callbackHit && /app\.slack\.com\/client\//.test(navUrl)) {
        _retried = true;
        setTimeout(() => {
          try {
            if (!popup.isDestroyed()) popup.loadURL(url);
          } catch {}
        }, 800);
      }
    };
    popup.webContents.on('did-navigate', onNav);
    popup.webContents.on('will-navigate', onNav);
    // User closed the popup manually.
    popup.on('closed', () => {
      if (!_resolved) {
        _resolved = true;
        if (_slackOAuthWin === popup) _slackOAuthWin = null;
        resolve({ ok: _callbackHit });
      }
    });
    // Safety timeout — 5 min.
    setTimeout(
      () => done({ ok: _callbackHit, error: _callbackHit ? undefined : 'timeout' }),
      300000,
    );
  });
});

// ── App lifecycle ───────────────────────────────────────────────────────
app.whenReady().then(() => {
  // Show a splash window IMMEDIATELY — before the backend starts — so the
  // user sees the gator chomping instead of a blank screen during the
  // multi-second backend boot. Dismissed when gatorView finishes loading.
  const iconPath = IS_MAC
    ? path.join(__dirname, '..', 'tray', 'aigator_icon.png')
    : path.join(__dirname, '..', 'build', 'aigator_icon.ico');
  splashWin = new BrowserWindow({
    width: 420,
    height: 320,
    frame: false,
    resizable: false,
    movable: false,
    center: true,
    show: true,
    icon: iconPath,
    transparent: false,
    backgroundColor: '#0a0f1a',
    skipTaskbar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  splashWin.loadFile(path.join(__dirname, 'splash.html'));
  splashWin.on('closed', () => {
    splashWin = null;
  });

  startBackend();
  waitForBackend((error) => {
    if (error) {
      showStartupError(error);
      return;
    }
    _fetchAppConfig(); // get Atlassian URLs from config before creating views
    createWindow();
  });
});
app.on('activate', () => {
  if (!win) createWindow();
});
app.on('window-all-closed', () => {
  if (!IS_MAC) quit();
});
app.on('before-quit', () => quit());
function quit() {
  try {
    if (pyProc) pyProc.kill();
  } catch {}
  app.quit();
}
