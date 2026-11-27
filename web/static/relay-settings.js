// Settings > General > Agent messaging: the switch, per-agent opt-out, and links between agents.
(function () {
  const root = document.getElementById('relay-settings');
  if (!root) return;

  const LINK_HOURS = [1, 4, 8, 24];
  let state = null;

  function el(tag, props, ...kids) {
    const node = document.createElement(tag);
    Object.assign(node, props || {});
    kids.forEach((k) => node.append(k));
    return node;
  }

  // Reads need the token too (agents can reach this backend but cannot get one); the global
  // fetch wrapper only attaches it to writes, so reads send it and retry once on a stale token.
  async function call(method, url, body) {
    const send = () =>
      fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': window.__CSRF_TOKEN__ || '',
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    let res = await send();
    if (res.status === 403) {
      const fresh = await fetch('/api/csrf')
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      if (fresh?.csrf_token) window.__CSRF_TOKEN__ = fresh.csrf_token;
      res = await send();
    }
    if (!res.ok) {
      const found = await res.json().catch(() => null);
      const error = new Error(`HTTP ${res.status}`);
      error.reason = typeof found?.detail === 'string' ? found.detail : '';
      throw error;
    }
    return res.json();
  }

  async function act(method, url, body) {
    try {
      await call(method, url, body);
    } catch (e) {
      if (typeof _showConnectivityToast === 'function') {
        _showConnectivityToast(e.reason || 'Could not change agent messaging.', 'warn');
      }
    }
    refresh();
  }

  function agentLabel(a) {
    const name = a.name || a.id;
    const same = state.agents.filter(
      (o) => (o.name || o.id) === name && o.project_id === a.project_id,
    );
    const tail = same.length > 1 ? ` #${a.id.slice(4, 8)}` : '';
    return `${name}${tail}${a.project_id ? ` (${a.project_id})` : ''}`;
  }

  function toggle(id, checked, disabled, onChange) {
    const input = el('input', { type: 'checkbox', id, checked, disabled });
    input.addEventListener('change', () => onChange(input.checked));
    return el(
      'div',
      { className: 'srow-actions' },
      el(
        'label',
        { className: 'toggle-switch', style: 'margin: 0' },
        input,
        el('span', { className: 'toggle-track' }),
      ),
    );
  }

  function offReason() {
    if (!state.admin_allows) return 'Your administrator has turned agent messaging off.';
    if (!state.enabled) return 'Agent messaging is off.';
    return '';
  }

  function switchRow() {
    const locked = !state.admin_allows;
    const sub = locked
      ? 'Your administrator has turned agent messaging off.'
      : 'Agents in the same project can message each other. You can link agents across projects below.';
    return el(
      'div',
      { className: 'srow' },
      el(
        'div',
        { className: 'srow-info' },
        el('div', { className: 'srow-label', textContent: 'Let agents message each other' }),
        el('div', { className: 'srow-sub', textContent: sub }),
      ),
      toggle('relay-enabled', state.enabled && !locked, locked, (on) =>
        act('POST', '/api/relay/settings', { enabled: on }),
      ),
    );
  }

  function agentRows() {
    const off = offReason();
    let sub = 'Turn an agent off to stop other agents messaging it.';
    if (off) sub = `${off} Agents cannot be changed until it is on.`;
    else if (!state.agents.length) sub = 'No Claude agents yet.';
    const head = el(
      'div',
      { className: 'srow' },
      el(
        'div',
        { className: 'srow-info' },
        el('div', { className: 'srow-label', textContent: 'Agents' }),
        el('div', { className: 'srow-sub', textContent: sub }),
      ),
    );
    const rows = state.agents.map((a) =>
      el(
        'div',
        { className: 'srow' },
        el(
          'div',
          { className: 'srow-info' },
          el('div', { className: 'srow-label', textContent: agentLabel(a) }),
          el('div', {
            className: 'srow-sub',
            textContent: `${a.state} - Accepts messages from other agents`,
          }),
        ),
        toggle(`relay-accepts-${a.id}`, !a.opted_out, Boolean(off), (on) =>
          act('POST', '/api/relay/opt-out', { endpoint_id: a.id, opted_out: !on }),
        ),
      ),
    );
    return [head, ...rows];
  }

  function pausedNote(l) {
    if (l.paused === 'limit_reached') return ' - Paused: hourly limit reached';
    if (l.paused) return ' - Paused: same message sent several times';
    return '';
  }

  function linkRows() {
    const off = offReason();
    const head = el(
      'div',
      { className: 'srow' },
      el(
        'div',
        { className: 'srow-info' },
        el('div', { className: 'srow-label', textContent: 'Links' }),
        el('div', {
          className: 'srow-sub',
          textContent: off
            ? `${off} New links cannot be made until it is on.`
            : 'A link lets two agents message each other, even across projects, until it expires.',
        }),
      ),
    );
    const rows = state.links.map((l) => {
      const until = new Date(l.expires_at).toLocaleTimeString([], {
        hour: 'numeric',
        minute: '2-digit',
      });
      const end = el('button', { className: 'btn-secondary', textContent: 'End link' });
      end.addEventListener('click', () =>
        act('DELETE', `/api/relay/links/${encodeURIComponent(l.id)}`),
      );
      const buttons = [end];
      if (l.paused) {
        const resume = el('button', { className: 'btn-secondary', textContent: 'Resume' });
        resume.addEventListener('click', () =>
          act('POST', `/api/relay/links/${encodeURIComponent(l.id)}/resume`),
        );
        buttons.unshift(resume);
      }
      return el(
        'div',
        { className: 'srow' },
        el(
          'div',
          { className: 'srow-info' },
          el('div', {
            className: 'srow-label',
            textContent: `${agentLabel(l.a)} and ${agentLabel(l.b)}`,
          }),
          el('div', { className: 'srow-sub', textContent: `Until ${until}${pausedNote(l)}` }),
        ),
        el('div', { className: 'srow-actions' }, ...buttons),
      );
    });
    if (state.agents.length >= 2 && !off) {
      const pick = (id, label) => {
        const select = el('select', { id });
        select.setAttribute('aria-label', label);
        state.agents.forEach((a) =>
          select.append(el('option', { value: a.id, textContent: agentLabel(a) })),
        );
        return select;
      };
      const a = pick('relay-link-a', 'Agent');
      const b = pick('relay-link-b', 'Other agent');
      b.selectedIndex = 1;
      const hours = el('select', { id: 'relay-link-hours' });
      hours.setAttribute('aria-label', 'For');
      LINK_HOURS.forEach((h) =>
        hours.append(el('option', { value: String(h), textContent: `${h} h`, selected: h === 8 })),
      );
      const make = el('button', { className: 'btn-secondary', textContent: 'Link them' });
      make.addEventListener('click', () =>
        act('POST', '/api/relay/links', { a: a.value, b: b.value, hours: Number(hours.value) }),
      );
      rows.push(
        el(
          'div',
          { className: 'srow' },
          el(
            'div',
            {
              className: 'srow-info',
              style: 'display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center',
            },
            a,
            el('span', { textContent: 'and' }),
            b,
            hours,
            make,
          ),
        ),
      );
    }
    if (state.links.length) {
      const endAll = el('button', { className: 'btn-secondary', textContent: 'End all links' });
      endAll.addEventListener('click', () => act('POST', '/api/relay/stop-all'));
      rows.push(el('div', { className: 'srow' }, el('div', { className: 'srow-actions' }, endAll)));
    }
    return [head, ...rows];
  }

  function render() {
    if (!state) {
      const retry = el('button', { className: 'btn-secondary', textContent: 'Retry' });
      retry.addEventListener('click', refresh);
      root.replaceChildren(
        el(
          'div',
          { className: 'srow' },
          el(
            'div',
            { className: 'srow-info' },
            el('div', { className: 'srow-sub', textContent: "Couldn't load agent messaging." }),
          ),
          el('div', { className: 'srow-actions' }, retry),
        ),
      );
      return;
    }
    root.replaceChildren(switchRow(), ...agentRows(), ...linkRows());
  }

  async function refresh() {
    try {
      state = await call('GET', '/api/relay');
    } catch (e) {
      state = null;
    }
    render();
  }

  const panel = document.getElementById('spanel-general');
  if (panel) {
    new MutationObserver(() => {
      if (!panel.classList.contains('hidden')) refresh();
    }).observe(panel, { attributes: true, attributeFilter: ['class'] });
  }
  refresh();
})();
