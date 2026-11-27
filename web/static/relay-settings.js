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

  // The name on the agent's terminal tab, else its session title, else "<Agent> session".
  function baseName(a) {
    if (typeof _genAgentTerminals !== 'undefined') {
      const ptyId = a.id.slice(4);
      for (const term of Object.values(_genAgentTerminals)) {
        const sess = term.sessions && term.sessions[ptyId];
        if (sess && sess.label) return sess.label;
      }
    }
    if (a.name) return a.name;
    const kind =
      a.agent && typeof _genAgentLabel === 'function' ? _genAgentLabel(a.agent) : 'Agent';
    return `${kind} session`;
  }

  // Two agents with the same name read "Opus" and "Opus (2)".
  function agentName(a) {
    const mine = baseName(a);
    const twins = state.agents.filter((o) => baseName(o) === mine);
    const place = twins.findIndex((o) => o.id === a.id);
    return place > 0 ? `${mine} (${place + 1})` : mine;
  }

  function agentState(a) {
    return a.state === 'suspended' ? 'Sleeping' : 'Running';
  }

  function agentContext(a) {
    return [a.project_id, agentState(a)].filter(Boolean).join(' · ');
  }

  // The project is only worth saying when agents from more than one project are open.
  function pickerText(a) {
    const mixed = state.agents.some((o) => o.project_id !== state.agents[0].project_id);
    return mixed && a.project_id ? `${agentName(a)} · ${a.project_id}` : agentName(a);
  }

  // A pair's ends are stored when the pair is made; show the live name while the agent is open.
  function endName(end) {
    const open = state.agents.find((a) => a.id === end.id);
    return open ? agentName(open) : end.name || 'A closed agent';
  }

  function untilText(iso) {
    const at = new Date(iso);
    const time = at.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    const day = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const days = Math.round((day(at) - day(new Date())) / 86400000);
    if (days <= 0) return time;
    if (days === 1) return `tomorrow ${time}`;
    return `${at.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`;
  }

  function toggle(id, label, checked, disabled, onChange) {
    const input = el('input', { type: 'checkbox', id, checked, disabled });
    input.setAttribute('aria-label', label);
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
      : 'Agents in the same project can message each other. You can allow pairs across projects below.';
    return el(
      'div',
      { className: 'srow' },
      el(
        'div',
        { className: 'srow-info' },
        el('div', { className: 'srow-label', textContent: 'Let agents message each other' }),
        el('div', { className: 'srow-sub', textContent: sub }),
      ),
      toggle(
        'relay-enabled',
        'Let agents message each other',
        state.enabled && !locked,
        locked,
        (on) => act('POST', '/api/relay/settings', { enabled: on }),
      ),
    );
  }

  function agentRows() {
    const off = offReason();
    let sub = 'Turn an agent off to stop other agents messaging it.';
    if (off) sub = `${off} Agents cannot be changed until it is on.`;
    else if (!state.agents.length) sub = 'No agents are open. Open one and it will show up here.';
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
          el('div', { className: 'srow-label', textContent: agentName(a) }),
          el('div', {
            className: 'srow-sub',
            textContent: `${agentContext(a)} · Accepts messages from other agents`,
          }),
        ),
        toggle(
          `relay-accepts-${a.id}`,
          `Accepts messages for ${agentName(a)}`,
          !a.opted_out,
          Boolean(off),
          (on) => act('POST', '/api/relay/opt-out', { endpoint_id: a.id, opted_out: !on }),
        ),
      ),
    );
    return [head, ...rows];
  }

  function pausedReason(l) {
    if (l.paused === 'limit_reached') return 'hourly limit reached';
    return 'same message sent several times';
  }

  function linkRows() {
    const off = offReason();
    const head = el(
      'div',
      { className: 'srow' },
      el(
        'div',
        { className: 'srow-info' },
        el('div', {
          className: 'srow-label',
          textContent: 'Allowed pairs',
          tabIndex: -1,
          id: 'relay-links-heading',
        }),
        el('div', {
          className: 'srow-sub',
          textContent: off
            ? `${off} New pairs cannot be allowed until it is on.`
            : 'Two agents you allow to message each other, even across projects, until the time runs out.',
        }),
      ),
    );
    const rows = state.links.map((l) => {
      const end = el('button', { className: 'btn-secondary', textContent: 'Remove' });
      end.dataset.key = `end-${l.id}`;
      end.addEventListener('click', () =>
        act('DELETE', `/api/relay/links/${encodeURIComponent(l.id)}`),
      );
      const buttons = [end];
      if (l.paused) {
        const resume = el('button', { className: 'btn-secondary', textContent: 'Resume' });
        resume.dataset.key = `resume-${l.id}`;
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
            textContent: `${endName(l.a)} and ${endName(l.b)}`,
          }),
          el('div', {
            className: 'srow-sub',
            textContent: l.paused
              ? `Paused: ${pausedReason(l)} · Allowed until ${untilText(l.expires_at)}`
              : `Allowed until ${untilText(l.expires_at)}`,
          }),
        ),
        el('div', { className: 'srow-actions' }, ...buttons),
      );
    });
    if (state.agents.length >= 2 && !off) {
      const pick = (id, label) => {
        const select = el('select', { id, className: 'llm-select' });
        select.setAttribute('aria-label', label);
        return select;
      };
      const fill = (select, skip) => {
        const keep = select.value;
        select.replaceChildren();
        const left = state.agents.filter((a) => a.id !== skip);
        ['Running', 'Sleeping'].forEach((group) => {
          const members = left.filter((a) => agentState(a) === group);
          if (!members.length) return;
          const box = el('optgroup', { label: group });
          members.forEach((a) =>
            box.append(el('option', { value: a.id, textContent: pickerText(a) })),
          );
          select.append(box);
        });
        if (keep && [...select.options].some((o) => o.value === keep)) select.value = keep;
      };
      const a = pick('relay-link-a', 'First agent');
      const b = pick('relay-link-b', 'Second agent');
      fill(a);
      fill(b, a.value);
      a.addEventListener('change', () => fill(b, a.value));
      const hours = el('select', { id: 'relay-link-hours', className: 'llm-select' });
      hours.setAttribute('aria-label', 'For how long');
      LINK_HOURS.forEach((h) =>
        hours.append(
          el('option', {
            value: String(h),
            textContent: h === 1 ? '1 hour' : `${h} hours`,
            selected: h === 8,
          }),
        ),
      );
      const make = el('button', { className: 'btn-secondary', textContent: 'Allow' });
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
            el('span', { textContent: 'Allow' }),
            a,
            el('span', { textContent: 'and' }),
            b,
            el('span', { textContent: 'to message each other for' }),
            hours,
            make,
          ),
        ),
      );
    }
    if (state.links.length) {
      const endAll = el('button', { className: 'btn-secondary', textContent: 'Remove all' });
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
    const active = root.contains(document.activeElement) ? document.activeElement : null;
    const key = active && (active.id || active.dataset.key);
    const endKeys = () => [...root.querySelectorAll('[data-key^="end-"]')];
    const endIndex = key && key.startsWith('end-') ? endKeys().indexOf(active) : -1;
    root.replaceChildren(switchRow(), ...agentRows(), ...linkRows());
    if (!key) return;
    const find = (k) =>
      [...root.querySelectorAll('[id], [data-key]')].find((n) => n.id === k || n.dataset.key === k);
    let target = find(key);
    if (!target && key.startsWith('resume-')) target = find(`end-${key.slice('resume-'.length)}`);
    if (!target && endIndex >= 0) {
      const ends = endKeys();
      target =
        ends[Math.min(endIndex, ends.length - 1)] || root.querySelector('#relay-links-heading');
    }
    if (target) target.focus();
  }

  async function refresh() {
    try {
      state = await call('GET', '/api/relay');
    } catch (e) {
      if (state) return;
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
