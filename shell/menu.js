const { app, Menu, MenuItem, BrowserWindow } = require('electron');

// Per-OS menu. macOS requires a proper application menu for standard shortcuts
// (Cmd+C/V/Q, Hide). Windows/Linux keep it minimal.
// IMPORTANT: built-in roles (role:'reload', role:'copy', etc.) target the
// BrowserWindow's OWN webContents, not our WebContentsView children. So we use
// custom menu items with explicit click handlers that target the focused view.
//
// Returns { menu, backItem, forwardItem } so main.js can update enabled state
// dynamically via MenuItem.enabled without rebuilding the whole menu.
module.exports = function buildMenu(isMac, getActiveExternalView) {
  function getFocusedContents() {
    const win = BrowserWindow.getFocusedWindow();
    if (!win) return null;
    const children = win.contentView.children;
    if (win.webContents.isDevToolsFocused()) return win.webContents;
    return children.length > 0 ? children[0].webContents : win.webContents;
  }

  function getNavContents() {
    if (!getActiveExternalView) return null;
    const v = getActiveExternalView();
    return (v && !v.webContents.isDestroyed()) ? v.webContents : null;
  }

  // Build Back/Forward as standalone MenuItems so we can mutate .enabled live.
  const backItem = new MenuItem({
    label: '← Back',
    accelerator: 'Alt+Left',
    enabled: false,
    click: () => { const c = getNavContents(); if (c && c.navigationHistory.canGoBack()) c.navigationHistory.goBack(); },
  });
  const forwardItem = new MenuItem({
    label: 'Forward →',
    accelerator: 'Alt+Right',
    enabled: false,
    click: () => { const c = getNavContents(); if (c && c.navigationHistory.canGoForward()) c.navigationHistory.goForward(); },
  });

  const template = [
    ...(isMac ? [{
      label: app.name,
      submenu: [
        { role: 'about' }, { type: 'separator' },
        { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
        { type: 'separator' }, { role: 'quit' },
      ],
    }] : []),
    { label: 'File', submenu: [ isMac ? { role: 'close' } : { role: 'quit' } ] },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
        { role: 'cut' }, { role: 'copy' }, { role: 'paste' },
        ...(isMac ? [{ role: 'selectAll' }] : [{ role: 'delete' }, { role: 'selectAll' }]),
      ],
    },
    // Navigate menu — Back/Forward for native panes (OneDrive, OneNote, etc.)
    // that navigate in-pane (M15 sameHostPopupPattern). Items are disabled when
    // no navigation history exists; main.js polls canGoBack/canGoForward and
    // updates .enabled directly on the MenuItem objects (no menu rebuild needed).
    {
      label: 'Navigate',
      submenu: [backItem, forwardItem],
    },
    {
      label: 'View',
      submenu: [
        {
          label: 'Reload',
          accelerator: 'CmdOrCtrl+R',
          click: () => { const c = getFocusedContents(); if (c) c.reload(); },
        },
        {
          label: 'Hard Reload',
          accelerator: 'CmdOrCtrl+Shift+R',
          click: () => { const c = getFocusedContents(); if (c) c.reloadIgnoringCache(); },
        },
        { type: 'separator' },
        {
          label: 'Toggle DevTools',
          accelerator: 'CmdOrCtrl+Shift+I',
          click: () => { const c = getFocusedContents(); if (c) c.toggleDevTools(); },
        },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        ...(isMac ? [{ role: 'zoom' }, { type: 'separator' }, { role: 'front' }] : [{ role: 'close' }]),
      ],
    },
  ];

  const menu = Menu.buildFromTemplate(template);
  return { menu, backItem, forwardItem };
};
