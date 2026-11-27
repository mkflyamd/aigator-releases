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
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.__CSRF_TOKEN__ || '' },
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
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function act(method, url, body) {
    try {
      await call(method, url, body);
    } catch (e) {
      if (typeof _showConnectivityToast === 'function') {
        _showConnectivityToast('Could not change agent messaging.', 'warn');
      }
    }
    refresh();
  }

  function agentLabel(a) {
    const name = a.name || a.id;
    const same = state.agents.filter((o) => (o.name || o.id) === name && o.project_id === a.project_id);
    const tail = same.length > 1 ? ` #${a.id.slice(4, 8)}` : '';
    return `${name}${tail}${a.project_id ? ` (${a.project_id})` : ''}`;
  }

  function switchRow() {
    const locked = !state.admin_allows;
    const box = el('input', { type: 'checkbox', id: 'relay-enabled', checked: state.enabled && !locked, disabled: locked });
    box.addEventListener('change', () => act('POST', '/api/relay/settings', { enabled: box.checked }));
    const sub = locked
      ? 'Your administrator has turned agent messaging off.'
      : 'Agents in the same project can message each other. You can link agents across projects below.';
    return el(
      'div',
      { className: 'srow' },
      el(
        'div',
        { className: 'srow-info' },
        el('label', { className: 'srow-label' }, box, ' Let agents message each other'),
        el('div', { className: 'srow-sub', textContent: sub }),
      ),
    );
  }

  function agentsBlock() {
    const block = el('div', { className: 'srow-info' });
    block.append(el('div', { className: 'srow-label', textContent: 'Agents' }));
    block.append(el('div', { className: 'srow-sub', textContent: 'Tick an agent to stop other agents messaging it.' }));
    if (!state.agents.length) {
      block.append(el('div', { className: 'srow-sub', textContent: 'No Claude agents yet.' }));
    }
    state.agents.forEach((a) => {
      const box = el('input', { type: 'checkbox', checked: a.opted_out });
      box.addEventListener('change', () =>
        act('POST', '/api/relay/opt-out', { endpoint_id: a.id, opted_out: box.checked }),
      );
      block.append(
        el(
          'label',
          { className: 'srow-sub saved-permission-item' },
          box,
          el('span', { textContent: `${agentLabel(a)} - ${a.state}` }),
        ),
      );
    });
    return block;
  }

  function linksBlock() {
    const block = el('div', { className: 'srow-info' });
    block.append(el('div', { className: 'srow-label', textContent: 'Links' }));
    block.append(
      el('div', {
        className: 'srow-sub',
        textContent: 'A link lets two agents message each other, even across projects, until it expires.',
      }),
    );
    state.links.forEach((l) => {
      const stop = el('button', { className: 'btn-secondary', textContent: 'Stop' });
      stop.addEventListener('click', () => act('DELETE', `/api/relay/links/${encodeURIComponent(l.id)}`));
      const until = new Date(l.expires_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
      const note = l.paused ? ' - paused' : '';
      block.append(
        el(
          'div',
          { className: 'srow-sub saved-permission-item' },
          el('span', { textContent: `${agentLabel(l.a)} and ${agentLabel(l.b)}, until ${until}${note}` }),
          stop,
        ),
      );
    });
    if (state.agents.length >= 2 && state.admin_allows && state.enabled) {
      const pick = (id) => {
        const select = el('select', { id });
        state.agents.forEach((a) => select.append(el('option', { value: a.id, textContent: agentLabel(a) })));
        return select;
      };
      const a = pick('relay-link-a');
      const b = pick('relay-link-b');
      b.selectedIndex = 1;
      const hours = el('select', { id: 'relay-link-hours' });
      LINK_HOURS.forEach((h) => hours.append(el('option', { value: String(h), textContent: `${h} h`, selected: h === 8 })));
      const make = el('button', { className: 'btn-secondary', textContent: 'Link them' });
      make.addEventListener('click', () =>
        act('POST', '/api/relay/links', { a: a.value, b: b.value, hours: Number(hours.value) }),
      );
      block.append(el('div', { className: 'srow-sub saved-permission-item' }, a, el('span', { textContent: 'and' }), b, hours, make));
    }
    if (state.links.length) {
      const stopAll = el('button', { className: 'btn-secondary', textContent: 'Stop all agent messaging' });
      stopAll.addEventListener('click', () => act('POST', '/api/relay/stop-all'));
      block.append(el('div', { className: 'srow-sub' }, stopAll));
    }
    return block;
  }

  function render() {
    root.replaceChildren(
      switchRow(),
      el('div', { className: 'srow' }, agentsBlock()),
      el('div', { className: 'srow' }, linksBlock()),
    );
  }

  async function refresh() {
    try {
      state = await call('GET', '/api/relay');
    } catch (e) {
      return;
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
