const { shell, BrowserWindow } = require('electron');

// Module-level toolbar attacher — set once by main.js via setToolbarAttacher.
// Avoids passing attachToolbar through every applyNavigationPolicy call site
// (10+ views) and avoids a circular require (main.js requires navigation-policy,
// navigation-policy would require main.js for the function).
let _toolbarAttacher = null;
function setToolbarAttacher(fn) {
  _toolbarAttacher = fn;
}

// Generic navigation policy for any embedded enterprise app (Slack, Teams,
// Outlook, ...). NOT app-specific and NOT tenant-specific — do not hardcode
// any customer's IdP domain here.
//
// The core problem this solves: corporate SSO. When an embedded app redirects
// to sign-in, the chain can hop through an arbitrary, tenant-owned identity
// provider (Okta, ADFS, Ping, Azure AD B2C, a custom STS, a MFA provider like
// Duo, etc.) on domains we cannot know in advance. If we block those hops the
// sign-in hangs (e.g. "Taking you to your organization's sign-in page"
// forever). So the policy is:
//
//   - In-view navigation (will-navigate): ALLOW all https:// hops. SSO chains
//     are cross-domain by nature; blocking any hop breaks auth. We only block
//     non-https schemes (e.g. custom protocol handoffs like slack://) which are
//     attempts to bounce out to a native app.
//   - New windows / popups (setWindowOpenHandler): auth popups are common in
//     SSO (Okta Verify, consent prompts). ALLOW popups that look like auth or
//     that stay within the app's own home domains, load same-domain popups
//     back into the main view, and only send genuinely-external links to the
//     system browser.
//
// Home hosts are used only to decide "is this an external link the user clicked
// (open in system browser)" vs "is this app/auth navigation (keep in-view)".

function _hostMatches(hostname, homeHosts) {
  const h = (hostname || '').toLowerCase();
  return homeHosts.some((base) => h === base || h.endsWith('.' + base));
}

// Heuristic for "this URL is part of an auth/SSO/MFA flow". Deliberately broad
// and provider-agnostic — matches Microsoft login, common IdP vendors, and the
// generic OAuth/SAML/SSO path patterns any custom enterprise IdP will use.
const AUTH_RE =
  /login\.microsoftonline|login\.microsoft|login\.live|login\.windows|\bokta\b|okta\.com|\badfs\b|\/adfs|ping(id|one|federate)|auth0|duosecurity|\bsaml\b|\/sso\b|\/oauth2?\b|openid|\/signin|\/login|federation|\bsts\b|accounts\.google|\bidp\b|entra|b2clogin/i;

function applyNavigationPolicy(view, opts) {
  const homeHosts = (opts && opts.homeHosts) || [];
  // sameHostNavPattern (optional RegExp): a NARROW allowlist of same-host
  // window.open()s that are really in-pane NAVIGATION — load those into the view
  // and deny the child window. Everything else keeps its popup. Kept for apps
  // that only need to catch a couple of known nav URLs.
  const sameHostNavPattern = (opts && opts.sameHostNavPattern) || null;
  // sameHostPopupPattern (optional RegExp): the INVERSE, scalable model. When
  // set, ALL same-host non-auth window.open()s load into the pane by DEFAULT,
  // EXCEPT ones matching this pattern (the app's genuine pop-outs — huddles,
  // calls, file previews). This scales without enumerating per-workspace entry
  // URLs. Slack uses this: entering a workspace happens via unpredictable
  // per-workspace subdomains/paths (app.slack.com/client/<team>,
  // <team>.slack.com/messages, <org>.enterprise.slack.com/, /ssb/, ...) — all
  // should stay in-pane — while only huddles/calls/files should pop out.
  const sameHostPopupPattern = (opts && opts.sameHostPopupPattern) || null;
  // onCrossAppNav (optional function(url) => boolean): M365 app launcher guard
  // (M17). Called for EVERY candidate navigation (will-navigate AND window.open).
  // If it returns true, the navigation is BLOCKED (preventDefault / deny) — the
  // caller is responsible for loading the URL in the correct app's view. This
  // fires BEFORE any loadURL / child-window creation, so there's no race.
  const onCrossAppNav = (opts && opts.onCrossAppNav) || null;
  // fileOpenPattern (optional RegExp): when a will-navigate URL matches, the
  // navigation is intercepted and the URL opens in a new child BrowserWindow
  // (sharing the same session partition) instead of navigating the pane.
  // This keeps the pane on the folder/list view while files open in a closeable
  // child window — same UX as a browser opening a file in a new tab.
  // Scalable: any app can pass a pattern; no per-app code needed beyond this.
  const fileOpenPattern = (opts && opts.fileOpenPattern) || null;
  // onChildWindow (optional function(child, url)): called after a child window
  // is created (both from fileOpenPattern and from setWindowOpenHandler allow).
  // Lets the caller inject modules (pin buttons etc.) into child windows.
  const onChildWindow = (opts && opts.onChildWindow) || null;
  // attachToolbar (optional function(childWin)): if provided, called on every
  // child window to attach the custom browser toolbar (back/forward/reload +
  // URL bar + window controls). Called BEFORE onChildWindow so pin injection
  // etc. runs on the already-toolbar'd child. Falls back to the module-level
  // attacher set via setToolbarAttacher() so callers don't need to pass it
  // per-view.
  const attachToolbar = (opts && opts.attachToolbar) || _toolbarAttacher;
  const wc = view.webContents;

  // Raise the listener cap on this webContents. With sameHostPopupPattern,
  // we redirect same-host window.open()s into the pane via wc.loadURL(), and
  // each loadURL() transiently attaches an internal one-shot 'did-stop-loading'
  // listener. Slack fires bursts of these during SPA navigation, briefly
  // stacking >10 before the loads settle → a benign MaxListenersExceededWarning.
  // The listeners ARE cleaned up; we just lift the default-10 cap to silence the
  // noise. (0 = unlimited would hide a real leak; 50 is generous but bounded.)
  try {
    wc.setMaxListeners(50);
  } catch {}

  const parentSession = wc.session;

  wc.setWindowOpenHandler(({ url }) => {
    // Blank popups: OWA (and other SPAs) open about:blank first, then drive the
    // window via JS. Denying the blank open makes "open in new window" do nothing.
    const isBlank = !url || url === 'about:blank' || url.startsWith('about:');
    let host = '';
    try {
      host = new URL(url).hostname;
    } catch {}

    // M365 app launcher guard (M17): if this is a cross-app nav, block it here
    // — the caller loads the URL in the correct app's view. Must fire BEFORE
    // sameHostPopupPattern loads it in-pane (which would land the wrong app in
    // this view) and before the allow-child-window path.
    if (onCrossAppNav && !isBlank && onCrossAppNav(url)) {
      return { action: 'deny' };
    }

    // File-open interception: if the URL matches fileOpenPattern, open it as a
    // child window (same session) instead of loading in-pane. Must fire BEFORE
    // the sameHostPopupPattern block which would otherwise load it in-pane.
    // Covers window.open() file opens (e.g. tile clicks on OneDrive home page).
    if (fileOpenPattern && !isBlank && !AUTH_RE.test(url) && fileOpenPattern.test(url)) {
      return {
        action: 'allow',
        overrideBrowserWindowOptions: {
          width: 1200,
          height: 800,
          title: 'AI Gator',
          autoHideMenuBar: true,
          webPreferences: {
            session: parentSession,
            contextIsolation: true,
            nodeIntegration: false,
          },
        },
      };
    }

    // Inverse model (scalable): same-host, non-auth, non-blank opens load into
    // the pane by DEFAULT — only genuine pop-outs (sameHostPopupPattern) get a
    // child window. This avoids hardcoding per-workspace entry URLs.
    if (
      sameHostPopupPattern &&
      !isBlank &&
      !AUTH_RE.test(url) &&
      _hostMatches(host, homeHosts) &&
      !sameHostPopupPattern.test(url)
    ) {
      try {
        wc.loadURL(url);
      } catch {}
      return { action: 'deny' };
    }

    // Narrow allowlist model (legacy, still supported): only URLs matching
    // sameHostNavPattern load in-pane; everything else keeps its popup.
    if (
      sameHostNavPattern &&
      !isBlank &&
      !AUTH_RE.test(url) &&
      _hostMatches(host, homeHosts) &&
      sameHostNavPattern.test(url)
    ) {
      try {
        wc.loadURL(url);
      } catch {}
      return { action: 'deny' };
    }

    // Auth popups, same-domain popups, and blank popups: keep them inside the app.
    if (isBlank || AUTH_RE.test(url) || _hostMatches(host, homeHosts)) {
      // Returning allow lets Electron open a child window for the popup, which
      // is what Okta Verify / consent dialogs expect. Pass the parent Session so
      // cookies/PRT carry over (otherwise the popup opens blank or logged out).
      return {
        action: 'allow',
        overrideBrowserWindowOptions: {
          webPreferences: {
            session: parentSession,
            contextIsolation: true,
            nodeIntegration: false,
          },
        },
      };
    }
    // Genuinely external link → system browser, don't hijack the pane.
    if (url.startsWith('http')) shell.openExternal(url).catch(() => {});
    return { action: 'deny' };
  });

  // Make the native close (X) work on popups. Diagnosis (popup-debug.log):
  // clicking X fires the window 'close' event, then OWA's beforeunload handler
  // fires 'will-prevent-unload' and — with no handler — Electron's DEFAULT is to
  // CANCEL the close. So the X becomes a dead button while minimize/maximize
  // still work. In a real browser beforeunload shows a Leave/Stay prompt; Electron
  // instead hands the decision to the app via 'will-prevent-unload'. Calling
  // e.preventDefault() there is the documented way to say "proceed with the
  // unload" — i.e. honor the user's click and close the window. Safe for OWA:
  // its popups are read/RSVP/calendar surfaces, and compose drafts auto-save to
  // the Drafts folder, so nothing is lost.
  wc.on('did-create-window', (childWin) => {
    try {
      childWin.webContents.on('will-prevent-unload', (e) => {
        e.preventDefault();
      });
      if (attachToolbar) attachToolbar(childWin);
      if (onChildWindow) onChildWindow(childWin, childWin.webContents.getURL());
    } catch {}
  });

  wc.on('will-navigate', (e, url) => {
    // M365 app launcher guard (M17): block cross-app nav BEFORE it happens.
    if (onCrossAppNav && onCrossAppNav(url)) {
      e.preventDefault();
      return;
    }
    // File-open interception: if the URL matches fileOpenPattern, open it in a
    // child BrowserWindow (same session) instead of navigating the pane.
    // This keeps the pane on the folder/list view while files open in a
    // closeable child window — exactly how browsers handle file opens in
    // document libraries. Scalable: any future app just passes the pattern.
    if (fileOpenPattern && fileOpenPattern.test(url) && !AUTH_RE.test(url)) {
      e.preventDefault();
      try {
        const child = new BrowserWindow({
          width: 1200,
          height: 800,
          title: 'AI Gator',
          autoHideMenuBar: true,
          webPreferences: {
            session: parentSession,
            contextIsolation: true,
            nodeIntegration: false,
          },
        });
        child.webContents.on('will-prevent-unload', (ev) => {
          ev.preventDefault();
        });
        if (attachToolbar) attachToolbar(child);
        child.loadURL(url);
        if (onChildWindow) onChildWindow(child, url);
      } catch {}
      return;
    }
    // Block non-https — but let msteams:// and other meeting/call protocols
    // pass to the OS via shell.openExternal so meetings open in the Teams
    // desktop app (or system browser) rather than being silently swallowed.
    // This lets users put the call on a separate screen while working in Gator.
    if (!url.startsWith('https://') && !url.startsWith('http://')) {
      e.preventDefault();
      // Meeting/call protocol handoffs: open externally so the OS handles them.
      // msteams:// → Teams desktop app join flow
      // zoommtg:// → Zoom, meet:// → Google Meet, etc.
      if (/^(msteams|zoommtg|zoomus|meet|webex|skype|tel|callto):/.test(url)) {
        try {
          shell.openExternal(url);
        } catch {}
      }
      // All other non-https schemes (slack://, etc.) remain blocked.
    }
  });
}

module.exports = { applyNavigationPolicy, AUTH_RE, setToolbarAttacher };
