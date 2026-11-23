'use strict';

const PANE_BG = { dark: '#0a0f1a', light: '#f0f4f8' };

function paneBackground(theme) {
  return theme === 'light' ? PANE_BG.light : PANE_BG.dark;
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
  };
}

module.exports = { createSwitchGate, paneBackground, PANE_BG };
