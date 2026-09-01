const { contextBridge, ipcRenderer } = require('electron');

// Exposed into the Gator web UI. The shell tiles Gator + one external app
// (Slack or Teams) side by side. third-pane.js calls show*/hide* to toggle
// the active external pane.
contextBridge.exposeInMainWorld('gatorShell', {
  isShell: true,
  platform: process.platform,

  // ── Slack (backwards-compatible — existing callers unchanged) ──────
  showSlack: () => ipcRenderer.invoke('slack-pane:show'),
  hideSlack: () => ipcRenderer.invoke('slack-pane:hide'),
  adjustSlackWidth: (delta) => ipcRenderer.invoke('slack-pane:adjust-width', delta),
  setSlackWidth: (width) => ipcRenderer.invoke('slack-pane:set-width', width),
  getSlackWidth: () => ipcRenderer.invoke('slack-pane:get-width'),
  navigateSlackPin: (pinId) => ipcRenderer.invoke('slack-pane:navigate-pin', pinId),

  // ── Teams ──────────────────────────────────────────────────────────
  showTeams: () => ipcRenderer.invoke('external-pane:show', 'teams'),
  hideTeams: () => ipcRenderer.invoke('external-pane:hide', 'teams'),
  adjustTeamsWidth: (delta) => ipcRenderer.invoke('external-pane:adjust-width', 'teams', delta),
  setTeamsWidth: (width) => ipcRenderer.invoke('external-pane:set-width', 'teams', width),
  getTeamsWidth: () => ipcRenderer.invoke('external-pane:get-width'),
  navigateTeamsPin: (threadId) => ipcRenderer.invoke('teams-pane:navigate-pin', threadId),

  // ── Outlook (OWA) ───────────────────────────────────────────────────
  showOutlook: () => ipcRenderer.invoke('external-pane:show', 'outlook'),
  hideOutlook: () => ipcRenderer.invoke('external-pane:hide', 'outlook'),
  adjustOutlookWidth: (delta) => ipcRenderer.invoke('external-pane:adjust-width', 'outlook', delta),
  setOutlookWidth: (width) => ipcRenderer.invoke('external-pane:set-width', 'outlook', width),
  getOutlookWidth: () => ipcRenderer.invoke('external-pane:get-width'),
  navigateOutlookPin: (convId) => ipcRenderer.invoke('outlook-pane:navigate-pin', convId),

  // ── OneDrive ────────────────────────────────────────────────────────
  showOneDrive: () => ipcRenderer.invoke('external-pane:show', 'onedrive'),
  hideOneDrive: () => ipcRenderer.invoke('external-pane:hide', 'onedrive'),
  adjustOneDriveWidth: (delta) =>
    ipcRenderer.invoke('external-pane:adjust-width', 'onedrive', delta),
  setOneDriveWidth: (width) => ipcRenderer.invoke('external-pane:set-width', 'onedrive', width),
  getOneDriveWidth: () => ipcRenderer.invoke('external-pane:get-width'),
  navigateOneDrivePin: (webUrl) => ipcRenderer.invoke('onedrive-pane:navigate-pin', webUrl),

  // ── OneNote ─────────────────────────────────────────────────────────
  showOneNote: () => ipcRenderer.invoke('external-pane:show', 'onenote'),
  hideOneNote: () => ipcRenderer.invoke('external-pane:hide', 'onenote'),
  adjustOneNoteWidth: (delta) => ipcRenderer.invoke('external-pane:adjust-width', 'onenote', delta),
  setOneNoteWidth: (width) => ipcRenderer.invoke('external-pane:set-width', 'onenote', width),
  getOneNoteWidth: () => ipcRenderer.invoke('external-pane:get-width'),
  navigateOneNotePin: (webUrl) => ipcRenderer.invoke('onenote-pane:navigate-pin', webUrl),

  // ── Confluence ──────────────────────────────────────────────────────
  showConfluence: () => ipcRenderer.invoke('external-pane:show', 'confluence'),
  hideConfluence: () => ipcRenderer.invoke('external-pane:hide', 'confluence'),
  adjustConfluenceWidth: (delta) =>
    ipcRenderer.invoke('external-pane:adjust-width', 'confluence', delta),
  setConfluenceWidth: (width) => ipcRenderer.invoke('external-pane:set-width', 'confluence', width),
  getConfluenceWidth: () => ipcRenderer.invoke('external-pane:get-width'),
  navigateConfluencePin: (webUrl) => ipcRenderer.invoke('confluence-pane:navigate-pin', webUrl),

  // ── Jira ────────────────────────────────────────────────────────────
  showJira: () => ipcRenderer.invoke('external-pane:show', 'jira'),
  hideJira: () => ipcRenderer.invoke('external-pane:hide', 'jira'),
  adjustJiraWidth: (delta) => ipcRenderer.invoke('external-pane:adjust-width', 'jira', delta),
  setJiraWidth: (width) => ipcRenderer.invoke('external-pane:set-width', 'jira', width),
  getJiraWidth: () => ipcRenderer.invoke('external-pane:get-width'),
  navigateJiraPin: (webUrl) => ipcRenderer.invoke('jira-pane:navigate-pin', webUrl),

  // ── GitHub ──────────────────────────────────────────────────────────
  showGitHub: () => ipcRenderer.invoke('external-pane:show', 'github'),
  hideGitHub: () => ipcRenderer.invoke('external-pane:hide', 'github'),
  adjustGitHubWidth: (delta) => ipcRenderer.invoke('external-pane:adjust-width', 'github', delta),
  setGitHubWidth: (width) => ipcRenderer.invoke('external-pane:set-width', 'github', width),
  getGitHubWidth: () => ipcRenderer.invoke('external-pane:get-width'),
  navigateGitHubPin: (webUrl) => ipcRenderer.invoke('github-pane:navigate-pin', webUrl),

  // ── Gator show/hide (used by dock-click-while-hidden fix) ──────────
  showGator: () => ipcRenderer.invoke('gator-pane:show'),
  hideGator: () => ipcRenderer.invoke('gator-pane:hide'),

  // ── Generic custom app panes ───────────────────────────────────────
  // show/hide/navigate for any custom app by id (e.g. 'custom-gmail').
  showCustomApp: (id) => ipcRenderer.invoke('external-pane:show', id),
  hideCustomApp: (id) => ipcRenderer.invoke('external-pane:hide', id),
  createCustomApp: (appConfig) => ipcRenderer.invoke('custom-app:create', appConfig),

  // Debug/introspection: which external app is currently the active tile.
  getActiveApp: () => ipcRenderer.invoke('shell:get-active-app'),

  // Per-app webview sign-in status (cookie presence in the persist:* partition).
  // Used by the Settings > Apps dashboard. Returns { signedIn: bool|null }.
  nativeAppWebStatus: (appName) => ipcRenderer.invoke('native-app:web-status', appName),

  // Open the Slack OAuth sign-in in a separate popup window that shares the
  // persist:slack session (reuses the pane's workspace cookie → skips the
  // Enterprise-Grid workspace picker, goes straight to consent). Returns
  // { ok: bool, error? }. Browser mode falls back to window.open().
  slackOAuthOpen: (url) => ipcRenderer.invoke('slack-oauth:open', url),

  // Open a second Gator window at the given URL (e.g. for a different project
  // in the coding agent). Browser mode falls back to window.open().
  openGatorWindow: (url) => ipcRenderer.invoke('gator-window:open', url),

  // Restore the persisted tile width on startup (saved on drag-end).
  restoreExtTileWidth: (width) => ipcRenderer.invoke('external-pane:set-width', null, width),

  // Window controls (for custom title bar — native title bar is hidden).
  // Used by the Gator topbar when no external app is active (the toolbar
  // view has its own controls for when an external app is shown).
  winMinimize: () => ipcRenderer.invoke('win:minimize'),
  winMaximizeToggle: () => ipcRenderer.invoke('win:maximize-toggle'),
  winClose: () => ipcRenderer.invoke('win:close'),
  winIsMaximized: () => ipcRenderer.invoke('win:is-maximized'),

  // Theme — notify the shell so it can forward to the toolbar view (which
  // can't read the Gator renderer's ThemeManager or localStorage).
  setTheme: (choice) => ipcRenderer.invoke('shell:set-theme', choice),

  // Widget HUD — open a chat-generated HTML widget as an always-on-top
  // floating window that survives navigation. html is the raw HTML string.
  openWidgetHud: (html) => ipcRenderer.invoke('widget:open-hud', html),
});
