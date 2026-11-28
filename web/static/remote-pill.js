/* Remote control pill: the on/off card at the foot of the History column, plus a small
   gator badge in the Code pane tab strip while Remote control is on. The server owns the
   state and the 12-hour deadline; this file only draws it and sends arm / disarm. */
(function (root) {
  'use strict';

  const AGENT = 'Gator';
  const WINDOW_SECONDS = 12 * 3600;
  const WARN_HOUR = 3600;
  const WARN_QUARTER = 900;
  const TICK_MS = 1000;
  const FETCH_MS = 30000;
  const SHEET_KEY = 'gator.remote-pill.sheet-seen';

  const GATOR_PATH =
    'M3.5 16.5V13.5C3.5 11.4 5 10 7 10C7.2 8 8.6 6.5 10.5 6.5C12.4 6.5 13.8 8 14 10C15.2 10.5 16.5 10.4 17.4 10.1C17.6 9 18.4 8.4 19.3 8.4C20.2 8.4 20.9 9 21 10V12.6C21 13.8 20.4 14.5 19.5 14.5';
  const GATOR = {
    16: {
      body: GATOR_PATH + 'H12.5L11.5 16.5Z M7.6 9.2a2.9 2.9 0 1 0 5.8 0a2.9 2.9 0 1 0 -5.8 0Z',
      pupil: 1.8,
      lid: 2.95,
      water: 'M2 19h20',
      stroke: 2.3,
    },
    24: {
      body:
        GATOR_PATH +
        'L18.6 15.7L17.7 14.5L16.8 15.7L15.9 14.5L15 15.7L14.1 14.5H12.5L11.5 16.5Z M8.0 9.2a2.5 2.5 0 1 0 5.0 0a2.5 2.5 0 1 0 -5.0 0Z',
      pupil: 1.25,
      lid: 2.55,
      water: 'M1.5 19q2.6-2.2 5.2 0t5.2 0 5.2 0 5.2 0',
      stroke: 1.6,
    },
  };

  // Eye states: on | warn | off | blocked | expired. Decorative: the words beside it carry the state.
  function gatorSvg(size, eye) {
    const g = GATOR[size];
    return (
      '<svg class="gator-eye" data-state="' +
      eye +
      '" width="' +
      size +
      '" height="' +
      size +
      '" viewBox="2 4 20 20" aria-hidden="true" focusable="false"><path d="' +
      g.body +
      '" fill="currentColor" fill-rule="evenodd"/><circle class="pupil" cx="10.5" cy="9.2" r="' +
      g.pupil +
      '"/><circle class="lid" cx="10.5" cy="9.2" r="' +
      g.lid +
      '" fill="currentColor"/><path d="' +
      g.water +
      '" fill="none" stroke="currentColor" stroke-width="' +
      g.stroke +
      '" stroke-linecap="round"/><path class="mark" d="M17 4.600l3.200 3.200m0-3.200L17 7.800" fill="none" stroke="currentColor" stroke-width="' +
      g.stroke +
      '" stroke-linecap="round"/></svg>'
    );
  }

  function esc(text) {
    return String(text).replace(
      /[&<>"]/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c],
    );
  }

  // Seconds left, from the server's own clock. The browser clock is never compared with the
  // server's; only the time elapsed since the fetch (a monotonic reading) is added.
  function remainingSeconds(status, fetchedAt, now) {
    if (!status || status.expires_at == null) return 0;
    return status.expires_at - status.now - (now - fetchedAt) / 1000;
  }

  function elapsed(minutes) {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    const parts = [];
    if (h) parts.push(h + ' h');
    if (m || !h) parts.push(m + ' min');
    return parts.join(' ');
  }

  function leftShort(minutes) {
    return elapsed(minutes) + ' left';
  }

  function leftSpoken(minutes) {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    const parts = [];
    if (h) parts.push(h + (h === 1 ? ' hour' : ' hours'));
    if (m || !h) parts.push(m + (m === 1 ? ' minute' : ' minutes'));
    return parts.join(' ');
  }

  const ON_STATES = ['on', 'warn_1h', 'warn_15m'];

  const CHANNEL_LABELS = { teams: 'Teams', slack: 'Slack' };

  // Names only the channels that are switched on, e.g. "Teams", "Slack" or "Teams and Slack".
  function enabledChannels(status) {
    const names = ((status && status.channels) || [])
      .filter((c) => c.enabled)
      .map((c) => CHANNEL_LABELS[c.name] || c.name);
    return names.join(' and ');
  }

  // True while a window is running, including when replies are off after turning it on.
  function windowOpen(status) {
    if (!status) return false;
    if (ON_STATES.includes(status.state)) return true;
    return status.state === 'replies_off' && status.armed_at != null;
  }

  function viewModel(status, remaining) {
    const view = {
      tone: 'off',
      eye: 'off',
      title: 'Remote control',
      sub: '',
      timer: null,
      note: '',
      noteWarn: false,
      acts: [],
      sw: { show: true, on: false, disabled: false },
      bar: null,
    };
    if (!status) {
      view.sub = 'Checking.';
      view.sw.show = false;
      return view;
    }
    const state = status.state;
    const reason = status.reason || '';
    if (ON_STATES.includes(state)) {
      const minutes = Math.max(1, Math.ceil(remaining / 60));
      const quarter = remaining <= WARN_QUARTER;
      const hour = remaining <= WARN_HOUR;
      view.tone = hour ? 'warn' : 'on';
      view.eye = hour ? 'warn' : 'on';
      view.title = 'Remote control on';
      view.sw.on = true;
      view.timer = {
        text: quarter ? 'Turns off in ' + elapsed(minutes) : leftShort(minutes),
        spoken: quarter ? 'Turns off in ' + leftSpoken(minutes) : leftSpoken(minutes) + ' left',
        minutes,
      };
      view.sub = quarter ? '' : enabledChannels(status);
      if (hour && !quarter) {
        view.note = 'Turns off soon. Restart to keep it on.';
        view.noteWarn = true;
        view.acts = [{ act: 'restart', label: 'Restart 12 hours' }];
      } else if (quarter) {
        view.note = 'Sessions stop when the 12 hours end. Restart to keep them going.';
        view.noteWarn = true;
        view.acts = [{ act: 'restart', label: 'Restart 12 hours', primary: true }];
      }
      view.bar = Math.max(2, Math.round((remaining / WINDOW_SECONDS) * 100));
    } else if (state === 'replies_off' && windowOpen(status)) {
      view.tone = 'warn';
      view.eye = 'warn';
      view.title = "Remote control can't reply";
      view.sub = 'Replies in your own chat are off. Gator still runs your requests.';
      view.acts = [{ act: 'replies', label: 'Turn on replies' }];
      view.sw.on = true;
    } else if (state === 'replies_off') {
      view.sub = 'Replies in your own chat are off, so Gator could not answer you.';
      view.acts = [{ act: 'repliesOn', label: 'Turn on replies and Remote control' }];
      view.sw.show = false;
    } else if (state === 'not_set_up') {
      view.sub = 'Connect Teams or Slack first.';
      view.acts = [{ act: 'setup', label: 'Set up' }];
      view.sw.show = false;
    } else if (state === 'replies_blocked_admin') {
      view.eye = 'blocked';
      view.title = 'Remote control is off';
      view.sub = reason;
      view.sw.disabled = true;
    } else if (state === 'expiring') {
      view.eye = 'expired';
      view.title = 'Turning off';
      view.sub = 'Finishing up.';
      view.sw.disabled = true;
    } else if (state === 'expired' || state === 'stopped_from_chat') {
      view.eye = 'expired';
      view.title = 'Remote control is off';
      view.sub = reason;
    } else {
      view.sub =
        'Message ' +
        AGENT +
        ' from ' +
        (enabledChannels(status) || 'Teams or Slack') +
        '. Turns itself off after 12 hours.';
    }
    return view;
  }

  function cardHtml(view) {
    const timer = view.timer
      ? '<span role="timer" class="rcp-nw"><span aria-hidden="true">' +
        esc(view.timer.text) +
        '</span><span class="rcp-sr">' +
        esc(view.timer.spoken) +
        '</span></span>'
      : '';
    const sub = esc(view.sub) + timer;
    const sw = view.sw.show
      ? '<button type="button" class="toggle-track rcp-sw" role="switch" data-rcp="switch" aria-checked="' +
        view.sw.on +
        '" aria-label="Remote control"' +
        (view.sw.disabled ? ' aria-disabled="true"' : '') +
        '></button>'
      : '';
    const note = view.note
      ? '<div class="rcp-note' +
        (view.noteWarn ? ' is-warn' : '') +
        '">' +
        esc(view.note) +
        '</div>'
      : '';
    const acts = view.acts.length
      ? '<div class="rcp-acts">' +
        view.acts
          .map(
            (a) =>
              '<button type="button" class="rcp-btn' +
              (a.primary ? ' is-primary' : '') +
              '" data-rcp="' +
              a.act +
              '">' +
              esc(a.label) +
              '</button>',
          )
          .join('') +
        '</div>'
      : '';
    const bar =
      view.bar != null
        ? '<div class="rcp-bar" aria-hidden="true"><i style="width:' + view.bar + '%"></i></div>'
        : '';
    const watching = view.eye === 'on' || view.eye === 'warn';
    return (
      '<div class="rcp" data-remote-pill data-tone="' +
      view.tone +
      '" role="group" aria-label="Remote control"><div class="rcp-row"><span class="rcp-eye" title="' +
      AGENT +
      (watching ? ' on watch' : ' off duty') +
      '">' +
      gatorSvg(24, view.eye) +
      '</span><div class="rcp-text"><b>' +
      esc(view.title) +
      '</b><span class="rcp-sub">' +
      sub +
      '</span></div>' +
      sw +
      '</div>' +
      note +
      acts +
      '<div class="rcp-err" data-rcp-err role="alert" hidden></div>' +
      bar +
      '</div>'
    );
  }

  function badgeHtml(view) {
    const tip = AGENT + ' on watch' + (view.timer ? ' · ' + view.timer.text : '');
    return (
      '<button type="button" class="rcp-badge" data-rcp="badge" title="' +
      esc(tip) +
      '" aria-label="' +
      esc('Remote control on. ' + (view.timer ? view.timer.spoken + '. ' : '') + 'Open History.') +
      '">' +
      gatorSvg(16, view.eye) +
      '</button>'
    );
  }

  function sheetHtml(status) {
    const repliesOff = status && status.state === 'replies_off';
    const channels = (status && status.channels) || [];
    const rows = channels
      .map(
        (c) =>
          '<li><b>' +
          (c.name === 'teams' ? 'Teams' : c.name === 'slack' ? 'Slack' : esc(c.name)) +
          '</b><span>' +
          (c.name === 'slack' ? 'Your own direct message' : 'Your own chat') +
          '</span><em>' +
          (c.enabled ? 'Connected' : 'Not set up') +
          '</em></li>',
      )
      .join('');
    return (
      '<h3 id="rcp-sheet-title" tabindex="-1">Turn on Remote control</h3><p class="rcp-sheet-lead">Control your Claude sessions from your own chats. ' +
      AGENT +
      ' answers in the same chat.</p><ul class="rcp-chs">' +
      rows +
      '</ul><ul class="rcp-bul"><li>Send <code>@gator</code> and what you want in either chat. ' +
      AGENT +
      ' runs it and answers in the same chat.</li><li>It stays on for 12 hours, then turns itself off. Turn it on again any time.</li><li>' +
      AGENT +
      ' only replies in your own chat. It sends nothing to other people from here.</li>' +
      (repliesOff
        ? '<li>Replies in your own chat are off. Turning on Remote control turns them on too.</li>'
        : '') +
      '</ul><div class="rcp-sheet-foot"><button type="button" class="rcp-btn" data-rcp="sheet-cancel">Cancel</button><button type="button" class="rcp-btn is-primary" data-rcp="sheet-ok">' +
      (repliesOff ? 'Turn on replies and Remote control' : 'Turn on for 12 hours') +
      '</button></div>'
    );
  }

  function create(env) {
    const doc = env.document;
    const perf = env.now || (() => Date.now());
    const store = env.storage;
    let status = null;
    let fetchedAt = 0;
    let lastFetchTry = -Infinity;
    let busy = false;
    let timer = null;
    let sheetOpener = null;
    let lastAnnounce = '';
    let lastLift = -1;
    const out = { fetches: 0 };

    async function call(method, url, body) {
      const r = await env.fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': env.csrf() },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      let data = null;
      try {
        data = await r.json();
      } catch (_) {}
      if (!r.ok) {
        const detail =
          data && typeof data.detail === 'string'
            ? data.detail
            : 'Something went wrong. Try again.';
        throw new Error(detail);
      }
      return data;
    }

    function remaining() {
      return remainingSeconds(status, fetchedAt, perf());
    }

    function take(next) {
      status = next;
      fetchedAt = perf();
      paint();
    }

    async function refresh() {
      lastFetchTry = perf();
      out.fetches += 1;
      try {
        take(await call('GET', '/api/remote/status'));
      } catch (_) {
        /* keep the last good status; the next tick tries again */
      }
    }

    function slot() {
      return doc.getElementById('remote-pill-slot');
    }

    function strip() {
      return doc.querySelector ? doc.querySelector('.ca-sc-viewtabs') : null;
    }

    function paint() {
      const left = remaining();
      const view = viewModel(status, left);
      const card = slot();
      if (card) {
        const html = cardHtml(view);
        if (card._rcpHtml !== html) {
          const focus =
            doc.activeElement && doc.activeElement.getAttribute
              ? doc.activeElement.getAttribute('data-rcp')
              : null;
          card.innerHTML = html;
          card._rcpHtml = html;
          if (focus && card.querySelector) {
            const again = card.querySelector('[data-rcp="' + focus + '"]');
            if (again && again.focus) again.focus();
          }
        }
      }
      const bar = strip();
      if (bar) {
        const existing = bar.querySelector('.rcp-badge');
        if (windowOpen(status)) {
          const html = badgeHtml(view);
          if (!existing || bar._rcpBadge !== html) {
            if (existing) existing.remove();
            bar.insertAdjacentHTML('beforeend', html);
            bar._rcpBadge = html;
          }
        } else if (existing) {
          existing.remove();
          bar._rcpBadge = null;
        }
      }
      const tab = doc.querySelector
        ? doc.querySelector('.smodal-tab[data-tab="remote"] .gator-eye')
        : null;
      if (tab && tab.getAttribute('data-state') !== view.eye)
        tab.setAttribute('data-state', view.eye);
      liftToast(card);
      announce(view);
    }

    // The OTA toast sits bottom-left; lift it above the footer card while the card is on screen.
    function liftToast(card) {
      const style = doc.documentElement && doc.documentElement.style;
      if (!style || !style.setProperty) return;
      const lift = card && card.offsetParent !== null ? card.offsetHeight || 0 : 0;
      if (lastLift === lift) return;
      lastLift = lift;
      style.setProperty('--rcp-toast-lift', lift + 'px');
    }

    function say(text) {
      const live = doc.getElementById('remote-pill-live');
      if (!live || !text) return;
      live.textContent = '';
      env.later(() => {
        live.textContent = text;
      }, 30);
    }

    // Announces only a change of state or a warning threshold, never the ticking countdown.
    function announce(view) {
      if (!status) return;
      let key = status.state;
      if (ON_STATES.includes(status.state)) {
        const left = remaining();
        key = left <= WARN_QUARTER ? 'warn_15m' : left <= WARN_HOUR ? 'warn_1h' : 'on';
      }
      if (lastAnnounce === '') {
        lastAnnounce = key;
        return;
      }
      if (key === lastAnnounce) return;
      lastAnnounce = key;
      if (key === 'warn_1h')
        say('Remote control turns off in 1 hour. Sessions stop when the time is up.');
      else if (key === 'warn_15m')
        say('Remote control turns off in 15 minutes. Sessions stop when the time is up.');
      else if (key === 'expired' || key === 'expiring')
        say('Remote control turned off after 12 hours.');
      else if (key === 'stopped_from_chat') say('Remote control turned off from your chat.');
    }

    function showError(message) {
      const node = slot() && slot().querySelector ? slot().querySelector('[data-rcp-err]') : null;
      if (!node) return;
      node.textContent = message;
      node.hidden = !message;
    }

    async function act(work, done) {
      if (busy) return;
      busy = true;
      showError('');
      try {
        const next = await work();
        if (next && next.state) take(next);
        else await refresh();
        if (done) say(typeof done === 'function' ? done(next) : done);
      } catch (error) {
        showError(error.message);
        await refresh();
        showError(error.message);
      } finally {
        busy = false;
      }
    }

    const arm = () => call('POST', '/api/remote/arm');
    const disarm = () => call('POST', '/api/remote/disarm');

    function turnOn() {
      return act(arm, (next) => {
        const names = enabledChannels(next || status);
        return 'Remote control on for 12 hours.' + (names ? ' ' + names + '.' : '');
      });
    }

    function turnOnReplies() {
      return act(async () => {
        await call('POST', '/api/relay/self-chat-autosend', { enabled: true });
        if (env.notify) env.notify('gator:self-chat-autosend', { source: 'pill' });
        return arm();
      }, 'Replies in your own chat are on. Remote control on for 12 hours.');
    }

    function wantsSheet() {
      return !(store && store.getItem(SHEET_KEY));
    }

    function openSheet() {
      sheetOpener = doc.activeElement || null;
      let host = doc.getElementById('remote-pill-sheet');
      if (!host) {
        host = doc.createElement('div');
        host.id = 'remote-pill-sheet';
        host.className = 'rcp-scrim';
        host.innerHTML =
          '<div class="rcp-sheet" role="dialog" aria-modal="true" aria-labelledby="rcp-sheet-title"></div>';
        doc.body.appendChild(host);
      }
      host.querySelector('.rcp-sheet').innerHTML = sheetHtml(status);
      host.hidden = false;
      const heading = host.querySelector('#rcp-sheet-title');
      if (heading && heading.focus) heading.focus();
    }

    function closeSheet() {
      const host = doc.getElementById('remote-pill-sheet');
      if (host) host.hidden = true;
      if (sheetOpener && sheetOpener.focus) sheetOpener.focus();
      sheetOpener = null;
    }

    function sheetIsOpen() {
      const host = doc.getElementById('remote-pill-sheet');
      return !!host && !host.hidden;
    }

    function startOn() {
      if (status && status.state === 'replies_off') return turnOnReplies();
      return turnOn();
    }

    function onClick(event) {
      const target =
        event.target && event.target.closest ? event.target.closest('[data-rcp]') : null;
      if (!target) return;
      const what = target.getAttribute('data-rcp');
      if (what === 'switch') {
        if (target.getAttribute('aria-disabled') === 'true') {
          say((status && status.reason) || 'Remote control cannot be turned on right now.');
          return;
        }
        if (target.getAttribute('aria-checked') === 'true')
          return act(disarm, 'Remote control off.');
        if (wantsSheet()) return openSheet();
        return startOn();
      }
      if (what === 'restart') {
        return act(
          () => call('POST', '/api/remote/restart'),
          'Remote control restarted. On for 12 hours.',
        );
      }
      if (what === 'replies') {
        return act(async () => {
          await call('POST', '/api/relay/self-chat-autosend', { enabled: true });
          if (env.notify) env.notify('gator:self-chat-autosend', { source: 'pill' });
          return call('GET', '/api/remote/status');
        }, 'Replies in your own chat are on.');
      }
      if (what === 'repliesOn') {
        if (wantsSheet()) return openSheet();
        return turnOnReplies();
      }
      if (what === 'setup') {
        if (env.openSettings) env.openSettings('remote');
        return;
      }
      if (what === 'badge') {
        if (env.showHistory) env.showHistory();
        return;
      }
      if (what === 'sheet-cancel') return closeSheet();
      if (what === 'sheet-ok') {
        if (store) store.setItem(SHEET_KEY, '1');
        const go = startOn();
        closeSheet();
        return go;
      }
    }

    function onKey(event) {
      if (!sheetIsOpen()) return;
      if (event.key === 'Escape') {
        closeSheet();
        return;
      }
      if (event.key !== 'Tab') return;
      const host = doc.getElementById('remote-pill-sheet');
      const items = Array.from(host.querySelectorAll('button'));
      if (!items.length) return;
      const at = items.indexOf(doc.activeElement);
      if (event.shiftKey && at <= 0) {
        event.preventDefault();
        items[items.length - 1].focus();
      } else if (!event.shiftKey && at === items.length - 1) {
        event.preventDefault();
        items[0].focus();
      } else if (at === -1) {
        event.preventDefault();
        items[0].focus();
      }
    }

    function mounted() {
      return (
        !!slot() || !!strip() || !!doc.querySelector('.smodal-tab[data-tab="remote"] .gator-eye')
      );
    }

    function tick() {
      if (!mounted() || doc.hidden === true) return;
      const now = perf();
      const overdue = status && ON_STATES.includes(status.state) && remaining() <= 0;
      if (!status || now - fetchedAt >= FETCH_MS || (overdue && now - lastFetchTry >= 5000)) {
        if (now - lastFetchTry >= 5000) refresh();
        return;
      }
      paint();
    }

    function mount() {
      if (status) paint();
    }

    function start() {
      if (timer) return;
      doc.addEventListener('click', onClick);
      doc.addEventListener('keydown', onKey);
      if (!doc.getElementById('remote-pill-live')) {
        const live = doc.createElement('div');
        live.id = 'remote-pill-live';
        live.className = 'rcp-sr';
        live.setAttribute('role', 'status');
        live.setAttribute('aria-live', 'polite');
        doc.body.appendChild(live);
      }
      timer = env.every(tick, TICK_MS);
      tick();
    }

    return {
      start,
      mount,
      refresh,
      paint,
      tick,
      get status() {
        return status;
      },
      get fetches() {
        return out.fetches;
      },
      stop() {
        if (timer && env.cancel) env.cancel(timer);
        timer = null;
      },
    };
  }

  const api = {
    AGENT,
    WINDOW_SECONDS,
    gatorSvg,
    remainingSeconds,
    leftShort,
    leftSpoken,
    windowOpen,
    viewModel,
    cardHtml,
    badgeHtml,
    sheetHtml,
    create,
  };

  if (typeof document !== 'undefined' && typeof window !== 'undefined') {
    const pill = create({
      document,
      fetch: (...args) => window.fetch(...args),
      csrf: () => window.__CSRF_TOKEN__ || '',
      now: () => performance.now(),
      every: (fn, ms) => setInterval(fn, ms),
      cancel: (id) => clearInterval(id),
      later: (fn, ms) => setTimeout(fn, ms),
      storage: (function () {
        try {
          return window.localStorage;
        } catch (_) {
          return null;
        }
      })(),
      notify: (name, detail) => window.dispatchEvent(new CustomEvent(name, { detail })),
      openSettings: (tab) => window.openSettingsPanel && window.openSettingsPanel(tab),
      showHistory: () => typeof _caSetLeftView === 'function' && _caSetLeftView('history'),
    });
    api.pill = pill;
    root.remotePill = Object.assign({}, api, { mount: pill.mount, refresh: pill.refresh });
    pill.start();
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
