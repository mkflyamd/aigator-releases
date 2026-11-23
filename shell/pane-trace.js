'use strict';

function summarize(rec) {
  const first = (event) => rec.marks.find((m) => m.event === event);
  const since = (m) => (m ? m.t - rec.t0 : null);
  const layouts = rec.marks.filter((m) => m.event === 'layout');
  const hides = rec.marks.filter((m) => m.event === 'ipc-hide');
  return {
    app: rec.app,
    clickToShowIpcMs: since(first('ipc-show')),
    clickToLayoutMs: since(layouts[0]),
    clickToFrameMs: since(first('frame')),
    layoutPasses: layouts.length,
    nullActivePasses: layouts.filter((m) => m.detail.active == null).length,
    hideIpcs: hides.length,
    noopHideIpcs: hides.filter((m) => m.detail.noop).length,
  };
}

function createPaneTrace({
  enabled = false,
  now = Date.now,
  log = console.log,
  schedule = setTimeout,
  settleMs = 1500,
} = {}) {
  let current = null;

  function finish() {
    if (!current) return null;
    const summary = summarize(current);
    current = null;
    log('[pane-trace] ' + JSON.stringify(summary));
    return summary;
  }

  function click(app, t = now()) {
    if (!enabled) return;
    finish();
    const rec = { app, t0: t, marks: [] };
    current = rec;
    const handle = schedule(() => {
      if (current === rec) finish();
    }, settleMs);
    if (handle && handle.unref) handle.unref();
  }

  function mark(event, detail = {}) {
    if (!enabled || !current) return;
    current.marks.push({ event, t: now(), detail });
    if (event === 'frame') finish();
  }

  function token() {
    return current;
  }

  function markFrame(tok) {
    if (tok && tok === current) mark('frame');
  }

  return { enabled, click, mark, finish, token, markFrame };
}

module.exports = { createPaneTrace, summarize };
