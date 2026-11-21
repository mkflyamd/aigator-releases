// Electron-side glue for pinning a page or element from a custom-app pane.
// All pure logic lives in web-pin-core.js; this file only talks to webContents.debugger.
const core = require('./web-pin-core');

const CDP_TIMEOUT_MS = 8000;
const HIGHLIGHT = {
  showInfo: false,
  showStyles: false,
  contentColor: { r: 74, g: 222, b: 128, a: 0.12 },
  borderColor: { r: 74, g: 222, b: 128, a: 1 },
  paddingColor: { r: 0, g: 0, b: 0, a: 0 },
  marginColor: { r: 0, g: 0, b: 0, a: 0 },
};
const KNOWN_CODES = new Set(['timeout', 'empty_target', 'page_mismatch']);

function coded(code) {
  const e = new Error(code);
  e.code = code;
  return e;
}

function codeOf(e) {
  return e && KNOWN_CODES.has(e.code) ? e.code : 'pane_unavailable';
}

function withTimeout(promise, ms) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(coded('timeout')), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function openSession(wc, timeoutMs) {
  const dbg = wc.debugger;
  const listeners = [];
  const onMessage = (_e, method, params) => listeners.forEach((l) => l(method, params));
  let owned = false;
  if (!dbg.isAttached()) {
    dbg.attach('1.3');
    owned = true;
  }
  dbg.on('message', onMessage);
  return {
    send: (method, params) => withTimeout(dbg.sendCommand(method, params || {}), timeoutMs),
    onEvent: (l) => listeners.push(l),
    close() {
      dbg.removeListener('message', onMessage);
      if (owned && dbg.isAttached()) {
        try { dbg.detach(); } catch (_) { /* already gone */ }
      }
    },
  };
}

async function readPage(cdp) {
  const r = await cdp.send('Runtime.evaluate', {
    expression: '(' + core.pageTextInPage.toString() + ')()',
    returnByValue: true,
  });
  return JSON.parse(r.result.value);
}

function insideViewport(clip, v) {
  const slack = 1;
  return clip.x >= v.pageX - slack && clip.y >= v.pageY - slack
    && clip.x + clip.width <= v.pageX + v.clientWidth + slack
    && clip.y + clip.height <= v.pageY + v.clientHeight + slack;
}

async function shoot(cdp, clip, v) {
  // Page.captureScreenshot rejects a zero-size clip; fail clearly instead.
  if (!(clip.width >= 1 && clip.height >= 1)) throw coded('empty_target');
  const scale = core.captureScale(clip.width, clip.height);
  const r = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    clip: { ...clip, scale },
    // Chrome implements captureBeyondViewport by resizing the page to the full document,
    // which can reflow responsive dashboards; only ask for it when the clip needs it.
    captureBeyondViewport: !insideViewport(clip, v),
  });
  return r.data;
}

async function captureView(cdp, wc) {
  const { cssVisualViewport: v } = await cdp.send('Page.getLayoutMetrics');
  const page = await readPage(cdp);
  const image_b64 = await shoot(cdp, { x: v.pageX, y: v.pageY, width: v.clientWidth, height: v.clientHeight }, v);
  // The url comes from the main process, never from the page: go-to and the
  // recapture page check trust it, and in-page JS could report anything.
  return { image_b64, text: core.capText(page.text), locator: null, url: wc.getURL(), title: page.title, aria_label: '' };
}

async function captureElement(cdp, wc, backendNodeId) {
  await cdp.send('DOM.scrollIntoViewIfNeeded', { backendNodeId }).catch(() => {});
  const { object } = await cdp.send('DOM.resolveNode', { backendNodeId });
  const called = await cdp.send('Runtime.callFunctionOn', {
    objectId: object.objectId,
    functionDeclaration: core.describeInPage.toString(),
    returnByValue: true,
  });
  const info = JSON.parse(called.result.value);
  const { model } = await cdp.send('DOM.getBoxModel', { backendNodeId });
  const { cssVisualViewport: v } = await cdp.send('Page.getLayoutMetrics');
  // Box-model quads are viewport-relative; screenshot clips are document-relative.
  const clip = core.clipFromQuad(model.border, { x: v.pageX, y: v.pageY });
  if (!(clip.width >= 1 && clip.height >= 1)) throw coded('empty_target');
  const page = await readPage(cdp);
  const image_b64 = await shoot(cdp, clip, v);
  return {
    image_b64,
    text: core.capText(info.text),
    locator: info.locator,
    url: wc.getURL(),
    title: page.title,
    aria_label: info.ariaLabel || info.name || '',
  };
}

function createWebPin({ getPane, isPaneVisible, onState, onCaptured, onError, timeoutMs = CDP_TIMEOUT_MS }) {
  let active = null;
  let closing = Promise.resolve();
  const busy = new Set();
  let starting = null;
  let startingApp = null;

  function fail(appId, code) {
    onError({ appId, code });
    return { ok: false, status: code };
  }

  // skipCdp is true when the pane or debugger is already gone: reset state only.
  function teardown(skipCdp) {
    const a = active;
    if (!a) return closing;
    active = null;
    a.wc.removeListener('before-input-event', a.onInput);
    a.wc.removeListener('destroyed', a.onGone);
    a.dbg.removeListener('detach', a.onGone);
    onState({ appId: a.appId, picking: false, label: '' });
    closing = (async () => {
      if (!skipCdp) {
        try {
          await a.cdp.send('Overlay.setInspectMode', { mode: 'none', highlightConfig: {} });
          await a.cdp.send('Overlay.hideHighlight');
        } catch (_) { /* page may be gone */ }
      }
      a.cdp.close();
    })();
    return closing;
  }

  const stop = () => teardown(false);

  async function pick(backendNodeId) {
    const a = active;
    if (!a || a.picking) return;
    a.picking = true;
    try {
      await a.cdp.send('Overlay.setInspectMode', { mode: 'none', highlightConfig: {} });
      await a.cdp.send('Overlay.hideHighlight');
      const captured = await captureElement(a.cdp, a.wc, backendNodeId);
      // The user may have cancelled (Esc / stop) while the capture was running.
      if (active !== a) return;
      onCaptured({ appId: a.appId, ...captured });
    } catch (e) {
      if (active === a) onError({ appId: a.appId, code: codeOf(e) });
    } finally {
      if (active === a) await teardown(false);
    }
  }

  async function hover(nodeId) {
    const a = active;
    if (!a || a.picking || a.hovering) return;
    a.hovering = true;
    try {
      const { object } = await a.cdp.send('DOM.resolveNode', { nodeId });
      const r = await a.cdp.send('Runtime.callFunctionOn', {
        objectId: object.objectId,
        functionDeclaration: core.labelInPage.toString(),
        returnByValue: true,
      });
      if (active === a && !a.picking) {
        onState({ appId: a.appId, picking: true, label: core.hoverLabel(JSON.parse(r.result.value)) });
      }
    } catch (_) { /* label is best-effort */ } finally {
      a.hovering = false;
    }
  }

  function start(appId) {
    // A double click must not open two sessions: share the in-flight start.
    if (starting) return startingApp === appId ? starting : Promise.resolve(fail(appId, 'pane_unavailable'));
    startingApp = appId;
    starting = doStart(appId).finally(() => { starting = null; startingApp = null; });
    return starting;
  }

  async function doStart(appId) {
    await stop();
    const wc = getPane(appId);
    if (!wc || wc.isDestroyed()) return fail(appId, 'pane_unavailable');
    if (!isPaneVisible(appId)) return fail(appId, 'pane_not_visible');
    if (busy.has(appId)) return fail(appId, 'pane_unavailable');
    let cdp;
    try {
      cdp = openSession(wc, timeoutMs);
      await cdp.send('DOM.enable');
      await cdp.send('Overlay.enable');
      await cdp.send('DOM.getDocument', { depth: 0 });
      await cdp.send('Overlay.setInspectMode', { mode: 'searchForNode', highlightConfig: HIGHLIGHT });
    } catch (e) {
      if (cdp) cdp.close();
      return fail(appId, codeOf(e));
    }
    const onInput = (event, input) => {
      if (input.type === 'keyDown' && input.key === 'Escape') {
        event.preventDefault();
        stop();
      }
    };
    const dbg = wc.debugger;
    const onGone = () => teardown(true);
    wc.on('before-input-event', onInput);
    wc.on('destroyed', onGone);
    dbg.on('detach', onGone);
    active = { appId, wc, dbg, cdp, onInput, onGone, picking: false, hovering: false };
    cdp.onEvent((method, params) => {
      if (!active || active.cdp !== cdp) return;
      if (method === 'Overlay.inspectNodeRequested') pick(params.backendNodeId);
      else if (method === 'Overlay.nodeHighlightRequested') hover(params.nodeId);
    });
    onState({ appId, picking: true, label: '' });
    return { ok: true };
  }

  async function run(appId, fn) {
    const wc = getPane(appId);
    if (!wc || wc.isDestroyed()) return { status: 'pane_unavailable' };
    if (!isPaneVisible(appId)) return { status: 'pane_not_visible' };
    if (busy.has(appId) || (starting && startingApp === appId)) return { status: 'pane_unavailable' };
    busy.add(appId);
    let cdp;
    try {
      cdp = openSession(wc, timeoutMs);
      return { status: 'ok', payload: await fn(cdp, wc) };
    } catch (e) {
      return { status: codeOf(e) };
    } finally {
      if (cdp) cdp.close();
      busy.delete(appId);
    }
  }

  async function pinView(appId) {
    await stop();
    const r = await run(appId, (cdp, wc) => captureView(cdp, wc));
    if (r.status === 'ok') onCaptured({ appId, ...r.payload });
    else onError({ appId, code: r.status });
  }

  async function recapture(appId, locator, url) {
    if (active && active.appId === appId) await stop();
    const r = await run(appId, async (cdp, wc) => {
      // The pin must be of the page it was made on: require the url, and re-check
      // after the capture in case the pane navigated while we were working.
      const samePage = () => !!url && core.urlMatches(wc.getURL(), url);
      if (!samePage()) throw coded('page_mismatch');
      let result = null;
      if (locator) {
        const hit = await core.resolveTarget(cdp, locator);
        if (hit) result = { ...(await captureElement(cdp, wc, hit.backendNodeId)), match: hit.match };
      }
      if (!result) result = { ...(await captureView(cdp, wc)), match: locator ? 'view-fallback' : 'view' };
      if (!samePage()) throw coded('page_mismatch');
      return result;
    });
    return r.status === 'ok' ? { status: 'ok', ...r.payload } : { status: r.status };
  }

  return { start, stop, pinView, recapture };
}

module.exports = { createWebPin, CDP_TIMEOUT_MS };
