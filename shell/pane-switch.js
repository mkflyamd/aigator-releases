'use strict';

const PANE_BG = { dark: '#0a0f1a', light: '#f0f4f8' };

function paneBackground(theme) {
  return theme === 'light' ? PANE_BG.light : PANE_BG.dark;
}

const PANE_BG_SETTLED = '#ffffff';

// The themed colour only covers a pane's first (unpainted) moment. Once the view's first load
// finishes it goes back to white, so pages that set no background of their own (plain text,
// images, example.com) are not drawn on navy. `states` is a WeakMap owned by the caller:
// absent = never seen, 'pending' = themed and waiting for the first load, 'settled' = done.
function applyPaneBackground(view, theme, states) {
  if (!view || typeof view.setBackgroundColor !== 'function') return;
  const state = states.get(view);
  if (state === 'settled') return;
  try {
    const wc = view.webContents;
    if (state === undefined) {
      // Loaded before its first show (startup-created): nothing left to cover.
      if (wc && !wc.isDestroyed() && !wc.isLoading() && wc.getURL()) {
        states.set(view, 'settled');
        view.setBackgroundColor(PANE_BG_SETTLED);
        return;
      }
      states.set(view, 'pending');
      if (wc && typeof wc.once === 'function') {
        wc.once('did-stop-loading', () => {
          states.set(view, 'settled');
          try {
            if (!wc.isDestroyed()) view.setBackgroundColor(PANE_BG_SETTLED);
          } catch {}
        });
      }
    }
    view.setBackgroundColor(paneBackground(theme));
  } catch {}
}

function createSwitchGate() {
  let lastSeq = 0;
  let version = 0;
  return {
    begin(seq) {
      if (typeof seq !== 'number' || !Number.isFinite(seq) || seq <= lastSeq) return null;
      lastSeq = seq;
      version += 1;
      return version;
    },
    isCurrent(ticket) {
      return ticket === version;
    },
    invalidate() {
      version += 1;
    },
    // The renderer's seq restarts at 0 after a reload; forget lastSeq and stale any in-flight ticket.
    reset() {
      lastSeq = 0;
      version += 1;
    },
  };
}

module.exports = {
  createSwitchGate,
  paneBackground,
  applyPaneBackground,
  PANE_BG,
  PANE_BG_SETTLED,
};
