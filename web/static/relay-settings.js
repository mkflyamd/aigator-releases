// Settings > General > Agent messaging: the switch, per-agent opt-out, and links between agents.
(function () {
  const root = document.getElementById('relay-settings');
  if (!root) return;

  const LINK_HOURS = [1, 4, 8, 24];
  const FILTERS = [
    ['all', 'All'],
    ['Running', 'Running'],
    ['Sleeping', 'Sleeping'],
    ['Blocked', 'Blocked'],
  ];
  let state = null;
  const ui = { open: false, query: '', filter: 'all' };

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

  function agentSummary() {
    const n = state.agents.length;
    if (!n) return 'No agents are open. Open one and it will show up here.';
    const running = state.agents.filter((a) => agentState(a) === 'Running').length;
    const blocked = state.agents.filter((a) => a.opted_out).length;
    const open = n === 1 ? '1 agent is' : `${n} agents are`;
    const tail = blocked ? `${blocked} blocked.` : 'All accept messages.';
    return `${open} open: ${running} running, ${n - running} sleeping. ${tail}`;
  }

  // Running first, then Sleeping, then by name.
  function sortedAgents() {
    return [...state.agents].sort((a, b) => {
      if (agentState(a) !== agentState(b)) return agentState(a) === 'Running' ? -1 : 1;
      return agentName(a).localeCompare(agentName(b));
    });
  }

  function agentShown(a) {
    const q = ui.query.trim().toLowerCase();
    if (q && !agentName(a).toLowerCase().includes(q)) return false;
    if (ui.filter === 'Running' || ui.filter === 'Sleeping') return agentState(a) === ui.filter;
    if (ui.filter === 'Blocked') return a.opted_out;
    return true;
  }

  function agentCounts() {
    const count = (test) => state.agents.filter(test).length;
    return {
      all: state.agents.length,
      Running: count((a) => agentState(a) === 'Running'),
      Sleeping: count((a) => agentState(a) === 'Sleeping'),
      Blocked: count((a) => a.opted_out),
    };
  }

  // The project is only worth saying when agents from more than one project are open.
  function projectLabel(a) {
    const mixed = state.agents.some((o) => o.project_id !== state.agents[0].project_id);
    return mixed ? a.project_id || '' : '';
  }

  function pickerText(a) {
    const project = projectLabel(a);
    return project ? `${agentName(a)} · ${project}` : agentName(a);
  }

  // A pair's ends are stored when the pair is made; show the live name while the agent is open.
  function endName(end) {
    const open = state.agents.find((a) => a.id === end.id);
    if (open) return agentName(open);
    return end.name ? `${end.name} (closed)` : 'Closed agent';
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

  function dot(kind) {
    const node = el('span', { className: `relay-dot relay-dot-${kind}` });
    node.setAttribute('aria-hidden', 'true');
    return node;
  }

  function agentRow(a, off) {
    return el(
      'div',
      { className: 'relay-agent-row' },
      el(
        'span',
        { className: 'relay-agent-name', title: pickerText(a) },
        agentName(a),
        ...(projectLabel(a)
          ? [el('span', { className: 'relay-agent-project', textContent: projectLabel(a) })]
          : []),
      ),
      el(
        'span',
        { className: 'relay-agent-state' },
        dot(agentState(a).toLowerCase()),
        agentState(a),
      ),
      toggle(
        `relay-accepts-${a.id}`,
        `Accepts messages for ${agentName(a)}`,
        !a.opted_out,
        Boolean(off),
        (on) => act('POST', '/api/relay/opt-out', { endpoint_id: a.id, opted_out: !on }),
      ),
    );
  }

  function agentsPanel(off) {
    const search = el('input', {
      type: 'search',
      id: 'relay-agent-search',
      className: 'llm-select relay-agent-search',
      placeholder: 'Find an agent',
      value: ui.query,
    });
    search.setAttribute('aria-label', 'Find an agent');
    const chips = el('div', { className: 'seg-group seg-sm' });
    const chipFor = {};
    FILTERS.forEach(([value, label]) => {
      const chip = el('button', { className: 'seg-btn', type: 'button' });
      chip.addEventListener('click', () => {
        ui.filter = value;
        fillList();
      });
      chipFor[value] = chip;
      chips.append(chip);
    });
    const count = el('span', { className: 'relay-agent-count' });
    count.setAttribute('aria-live', 'polite');
    const list = el('div', { className: 'relay-agent-list', id: 'relay-agents-list', tabIndex: 0 });
    list.setAttribute('role', 'region');
    list.setAttribute('aria-label', 'Agents');
    const fillList = () => {
      const counts = agentCounts();
      FILTERS.forEach(([value, label]) => {
        const chip = chipFor[value];
        const number = counts[value === 'all' ? 'all' : value];
        chip.textContent = `${label} ${number}`;
        chip.classList.toggle('active', ui.filter === value);
        chip.setAttribute('aria-pressed', String(ui.filter === value));
      });
      const shown = sortedAgents().filter(agentShown);
      count.textContent = `${shown.length} of ${state.agents.length} agents`;
      list.replaceChildren(
        ...(shown.length
          ? shown.map((a) => agentRow(a, off))
          : [
              el('div', {
                className: 'srow-sub relay-agent-empty',
                textContent: 'No agent matches. Clear the search or choose All.',
              }),
            ]),
      );
    };
    search.addEventListener('input', () => {
      ui.query = search.value;
      fillList();
    });
    fillList();
    return el(
      'div',
      { className: 'relay-agents-panel', id: 'relay-agents-panel' },
      search,
      chips,
      el(
        'div',
        { className: 'relay-agent-countline' },
        count,
        el('span', { textContent: 'Accepts messages' }),
      ),
      list,
    );
  }

  function agentsBlock() {
    const off = offReason();
    const open = ui.open && !off && state.agents.length > 0;
    const manage = el('button', {
      className: 'btn-secondary',
      id: 'relay-manage-agents',
      textContent: open ? 'Done' : 'Manage agents',
      disabled: Boolean(off) || !state.agents.length,
    });
    manage.setAttribute('aria-expanded', String(open));
    manage.setAttribute('aria-controls', 'relay-agents-panel');
    manage.addEventListener('click', () => {
      ui.open = !ui.open;
      render();
    });
    const head = el(
      'div',
      { className: 'srow' },
      el(
        'div',
        { className: 'srow-info' },
        el('div', { className: 'srow-label', textContent: 'Agents' }),
        el('div', {
          className: 'srow-sub',
          textContent: off ? `${off} Agents cannot be changed until it is on.` : agentSummary(),
        }),
      ),
      el('div', { className: 'srow-actions' }, manage),
    );
    if (open) return [head, agentsPanel(off)];
    const blocked = sortedAgents().filter((a) => a.opted_out);
    return [
      head,
      ...blocked.map((a) => {
        const again = el('button', {
          className: 'btn-secondary',
          textContent: 'Allow again',
          disabled: Boolean(off),
        });
        again.dataset.key = `allow-${a.id}`;
        again.setAttribute('aria-label', `Allow messages to ${agentName(a)} again`);
        again.addEventListener('click', () =>
          act('POST', '/api/relay/opt-out', { endpoint_id: a.id, opted_out: false }),
        );
        return el(
          'div',
          { className: 'srow' },
          el(
            'div',
            { className: 'srow-info' },
            el('div', { className: 'srow-label', textContent: pickerText(a) }),
            el('div', { className: 'srow-sub' }, dot('blocked'), 'Blocked'),
          ),
          el('div', { className: 'srow-actions' }, again),
        );
      }),
    ];
  }

  function pausedReason(l) {
    if (l.paused === 'limit_reached') return 'Hourly limit reached';
    return 'Same message sent several times';
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
          el(
            'div',
            { className: 'srow-sub' },
            dot(l.paused ? 'paused' : 'allowed'),
            l.paused
              ? `Paused · ${pausedReason(l)} · Ends at ${untilText(l.expires_at)}`
              : `Allowed · Can message each other until ${untilText(l.expires_at)}`,
          ),
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
      const endAll = el('button', { className: 'btn-secondary', textContent: 'Remove all pairs' });
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
    const scrolled = root.querySelector('#relay-agents-list')?.scrollTop || 0;
    const endKeys = () => [...root.querySelectorAll('[data-key^="end-"]')];
    const endIndex = key && key.startsWith('end-') ? endKeys().indexOf(active) : -1;
    root.replaceChildren(switchRow(), ...agentsBlock(), ...linkRows());
    const box = root.querySelector('#relay-agents-list');
    if (box) box.scrollTop = scrolled;
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
