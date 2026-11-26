'use strict';

const LOCAL_NETWORK = 'local-network-access';

// Asks for local-network-access one site at a time. An answer covers every
// waiting request for that origin, is never remembered, and leaving the page
// that asked (or closing its popup) counts as no.
function createPermissionPrompt({ onChange }) {
  let current = null;
  const queue = [];

  function originOf(url) {
    try {
      const u = new URL(url);
      return /^https?:$/.test(u.protocol) ? { origin: u.origin, host: u.host } : null;
    } catch {
      return null;
    }
  }

  function find(key) {
    if (current && current.key === key) return current;
    return queue.find((e) => e.key === key) || null;
  }

  function pump() {
    if (current || !queue.length) return;
    current = queue.shift();
    onChange({ type: 'show', host: current.host });
  }

  function release(waiter) {
    for (const off of waiter.offs) off();
    waiter.offs = [];
  }

  function finish(entry, allowed) {
    for (const w of entry.waiters) {
      release(w);
      w.resolve(allowed);
    }
    entry.waiters = [];
    if (current === entry) {
      current = null;
      onChange({ type: 'closed', host: entry.host, allowed });
    } else {
      const i = queue.indexOf(entry);
      if (i >= 0) queue.splice(i, 1);
    }
    pump();
  }

  function watch(entry, waiter, wc) {
    if (!wc || typeof wc.on !== 'function') return;
    const leave = () => {
      const i = entry.waiters.indexOf(waiter);
      if (i < 0) return;
      entry.waiters.splice(i, 1);
      release(waiter);
      waiter.resolve(false);
      if (!entry.waiters.length) finish(entry, false);
    };
    // Electron passes either one details object or (event, url, isInPlace, isMainFrame).
    const onNav = (first, _url, isInPlace, isMainFrame) => {
      const details = first && typeof first === 'object' && 'isMainFrame' in first ? first : null;
      const mainFrame = details ? details.isMainFrame : isMainFrame;
      const sameDocument = details ? details.isSameDocument : isInPlace;
      if (mainFrame && !sameDocument) leave();
    };
    wc.on('did-start-navigation', onNav);
    wc.on('destroyed', leave);
    waiter.offs.push(() => {
      if (typeof wc.removeListener !== 'function') return;
      wc.removeListener('did-start-navigation', onNav);
      wc.removeListener('destroyed', leave);
    });
  }

  function ask(wc, url) {
    const site = originOf(url);
    if (!site) return Promise.resolve(false);
    const key = `${site.origin}|${LOCAL_NETWORK}`;
    return new Promise((resolve) => {
      let entry = find(key);
      if (!entry) {
        entry = { key, host: site.host, waiters: [] };
        queue.push(entry);
      }
      const waiter = { resolve, offs: [] };
      entry.waiters.push(waiter);
      watch(entry, waiter, wc);
      pump();
    });
  }

  return {
    ask,
    answer: (allowed) => {
      if (current) finish(current, allowed === true);
    },
    host: () => (current ? current.host : ''),
  };
}

// The Browser pane loads arbitrary sites, so its session grants nothing unless the
// user says yes to one local-network request at a time. Everything else (camera,
// microphone, screen capture, clipboard, notifications) is denied without asking.
// Child windows (auth popups) share this session, so they inherit the policy.
function applyBrowserPermissions(ses, prompt) {
  ses.setPermissionRequestHandler((webContents, permission, callback, details) => {
    if (prompt && permission === LOCAL_NETWORK) {
      let url = details && details.requestingUrl;
      if (!url && webContents && typeof webContents.getURL === 'function')
        url = webContents.getURL();
      prompt.ask(webContents, url).then(callback);
      return;
    }
    callback(false);
  });
  ses.setPermissionCheckHandler(() => false);
  if (typeof ses.setDisplayMediaRequestHandler === 'function') {
    ses.setDisplayMediaRequestHandler((_request, callback) => callback({}));
  }
}

module.exports = { applyBrowserPermissions, createPermissionPrompt, LOCAL_NETWORK };
