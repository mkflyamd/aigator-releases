/* MCP Add Modal — Universal Connect flow (Task 6).
   Two-step: (1) paste textarea → Analyze → (2) review card → Connect.
   Built with plain DOM. No framework. No innerHTML with user data. */
(function () {
  'use strict';

  let root, overlay, modal, state, prevFocus, keyHandler;

  function $el(tag, attrs, children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === 'class' || k === 'className') {
          el.className = attrs[k];
        } else if (k === 'text' || k === 'textContent') {
          el.textContent = attrs[k];
        } else if (k.startsWith('on') && typeof attrs[k] === 'function') {
          el.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        } else if (attrs[k] === true) {
          el.setAttribute(k, '');
        } else if (attrs[k] !== false && attrs[k] != null) {
          el.setAttribute(k, attrs[k]);
        }
      }
    }
    if (children) {
      (Array.isArray(children) ? children : [children]).forEach(function (c) {
        if (c == null) return;
        el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
      });
    }
    return el;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  // ── Name uniqueness (soft warning) ────────────────────────────────────────────
  // Two connections with names that slug to the same value will produce the
  // same OAuth provider id and collide. Match backend _slug() in dcr.py.
  function _slugifyName(s) {
    return String(s || '').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  async function _loadExistingConnections() {
    if (state && state._existingConns) return state._existingConns;
    try {
      const resp = await fetch('/api/config/mcp');
      const data = await resp.json();
      const conns = (data && data.connections) || [];
      if (state) state._existingConns = conns;
      return conns;
    } catch (e) {
      return [];
    }
  }

  function attachNameValidator(nameInput, getEditingId) {
    const warn = $el('div', { className: 'mcp-name-warning', style: 'color:#b85c00;font-size:12px;margin-top:4px;display:none' });
    let conns = [];
    _loadExistingConnections().then(function (c) { conns = c; check(); });
    function check() {
      const val = nameInput.value.trim();
      const editingId = (typeof getEditingId === 'function' ? getEditingId() : '') || '';
      if (!val) { warn.style.display = 'none'; return; }
      const slug = _slugifyName(val);
      const clash = conns.find(function (c) {
        if (c.id === editingId) return false;
        return _slugifyName(c.name || '') === slug;
      });
      if (clash) {
        warn.textContent = '⚠ Another connection is named “' + (clash.name || '') + '” — pick a distinct name so credentials don’t collide.';
        warn.style.display = '';
      } else {
        warn.style.display = 'none';
      }
    }
    nameInput.addEventListener('input', check);
    return warn;
  }

  // ── Placeholder helpers ───────────────────────────────────────────────────────

  function findPlaceholders(obj) {
    // Returns [{key, varName, isSecret}] for each {variable} found in obj values. No duplicates.
    var pattern = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g;
    var seen = {};
    var result = [];
    Object.keys(obj || {}).forEach(function (key) {
      var val = String(obj[key] || '');
      Array.from(val.matchAll(pattern)).forEach(function (m) {
        var varName = m[1];
        if (!seen[varName]) {
          seen[varName] = true;
          var lk = key.toLowerCase();
          var isSecret = /passw|secret|token|key|pwd|credential/i.test(lk) ||
                         /passw|secret|token|key|pwd|credential/i.test(varName);
          result.push({ key: key, varName: varName, isSecret: isSecret });
        }
      });
    });
    return result;
  }

  function _hasBasicAuthTemplate(sourceObj) {
    // True if any header value is a Basic-auth template with ≥2 {placeholders},
    // e.g. "Basic {email}@{api_token}" or "Basic {email}:{api_token}". Used to
    // reassure the user we'll handle the base64 + separator on their behalf.
    if (!sourceObj || typeof sourceObj !== 'object') return false;
    var pat = /\{[A-Za-z_][A-Za-z0-9_]*\}/g;
    return Object.keys(sourceObj).some(function (k) {
      if (k.toLowerCase() !== 'authorization') return false;
      var v = String(sourceObj[k] || '');
      if (!/^basic\s+/i.test(v)) return false;
      var matches = v.match(pat) || [];
      return matches.length >= 2;
    });
  }

  function buildPlaceholderFields(placeholders, hint, sourceObj) {
    // Returns {container, getValues}. getValues() → {varName: filledValue}.
    var inputs = {};
    if (placeholders.length === 0) {
      return { container: null, getValues: function () { return {}; } };
    }
    var container = $el('div', { className: 'mcp-placeholder-section' });
    container.appendChild($el('p', { className: 'mcp-placeholder-hint', textContent: hint }));
    if (_hasBasicAuthTemplate(sourceObj)) {
      container.appendChild($el('p', {
        className: 'mcp-placeholder-subhint',
        textContent: 'Tip: enter email and API token separately — we’ll join and base64-encode them for you.',
      }));
    }
    placeholders.forEach(function (p) {
      var row = $el('div', { className: 'mcp-edit-row' });
      var label = p.varName.replace(/_/g, ' ');
      row.appendChild($el('label', { textContent: label, className: 'mcp-edit-label' }));
      var inp = $el('input', {
        type: p.isSecret ? 'password' : 'text',
        className: 'mcp-edit-input',
        placeholder: '{' + p.varName + '}',
        autocomplete: p.isSecret ? 'off' : 'on',
      });
      inputs[p.varName] = inp;
      row.appendChild(inp);
      container.appendChild(row);
    });
    return {
      container: container,
      getValues: function () {
        var out = {};
        Object.keys(inputs).forEach(function (k) { out[k] = inputs[k].value.trim(); });
        return out;
      },
    };
  }

  function resolvePlaceholders(obj, values) {
    // Replace {varName} patterns in string values with filled-in values.
    var out = {};
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      if (typeof v === 'string') {
        Object.keys(values).forEach(function (varName) {
          v = v.split('{' + varName + '}').join(values[varName]);
        });
      }
      out[k] = v;
    });
    return out;
  }

  // ── Custom dropdown (replaces native <select> for on-brand styling) ──────────

  function buildDropdown(options, currentValue, onChange) {
    // Menu is portalled to document.body with position:fixed so it escapes any overflow:auto ancestor.
    var current = currentValue;
    var open = false;

    var wrap = $el('div', { className: 'mcp-dropdown' });
    var trigger = $el('button', { type: 'button', className: 'mcp-dropdown-trigger' });
    var triggerLabel = $el('span', { className: 'mcp-dropdown-label' });
    var chevron = $el('span', { className: 'mcp-dropdown-chevron', textContent: '›' });
    trigger.appendChild(triggerLabel);
    trigger.appendChild(chevron);

    // Menu lives on document.body, not inside the scrollable modal body
    var menu = $el('div', { className: 'mcp-dropdown-menu mcp-dropdown-menu-portal', role: 'listbox' });
    menu.style.display = 'none';
    document.body.appendChild(menu);

    function setLabel(val) {
      var opt = options.find(function (o) { return o.value === val; });
      triggerLabel.textContent = opt ? opt.label : val;
    }

    function closeMenu() {
      open = false;
      menu.style.display = 'none';
      chevron.style.transform = '';
    }

    function openMenu() {
      var rect = trigger.getBoundingClientRect();
      menu.style.position = 'fixed';
      menu.style.top = (rect.bottom + 4) + 'px';
      menu.style.left = rect.left + 'px';
      menu.style.width = rect.width + 'px';
      menu.style.display = '';
      chevron.style.transform = 'rotate(90deg)';
      open = true;
    }

    options.forEach(function (opt) {
      var item = $el('button', {
        type: 'button',
        className: 'mcp-dropdown-item' + (opt.value === current ? ' mcp-dropdown-item-active' : ''),
        role: 'option',
        textContent: opt.label,
      });
      item.addEventListener('click', function () {
        current = opt.value;
        setLabel(current);
        Array.prototype.forEach.call(menu.querySelectorAll('.mcp-dropdown-item'), function (el) {
          el.classList.toggle('mcp-dropdown-item-active', el.textContent === opt.label);
        });
        closeMenu();
        if (onChange) onChange(current);
      });
      menu.appendChild(item);
    });

    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      open ? closeMenu() : openMenu();
    });

    // Close on outside click or modal scroll
    document.addEventListener('click', function (e) {
      if (open && !menu.contains(e.target) && e.target !== trigger) closeMenu();
    }, true);

    setLabel(current);
    wrap.appendChild(trigger);

    return {
      el: wrap,
      getValue: function () { return current; },
      setValue: function (val) { current = val; setLabel(val); },
      destroy: function () { if (menu.parentNode) menu.parentNode.removeChild(menu); },
    };
  }

  function focusableIn(node) {
    return Array.prototype.slice.call(node.querySelectorAll(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    ));
  }

  function trapTab(e) {
    if (e.key !== 'Tab' || !modal) return;
    const items = focusableIn(modal);
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function close() {
    if (keyHandler) {
      document.removeEventListener('keydown', keyHandler, true);
      keyHandler = null;
    }
    // Clean up any portalled dropdown menus left on document.body
    document.querySelectorAll('.mcp-dropdown-menu-portal').forEach(function (el) {
      if (el.parentNode) el.parentNode.removeChild(el);
    });
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    overlay = modal = state = null;
    if (prevFocus && typeof prevFocus.focus === 'function') {
      try { prevFocus.focus(); } catch (e) { /* ignore */ }
    }
    prevFocus = null;
  }

  function openModal(opts) {
    if (overlay) close();
    state = { opts: opts || {} };
    root = document.getElementById('mcp-modal-root');
    if (!root) return;
    prevFocus = document.activeElement;

    overlay = $el('div', {
      class: 'mcp-modal-overlay',
      role: 'presentation',
      onclick: function (e) { if (e.target === overlay) close(); },
    });
    modal = $el('div', {
      class: 'mcp-modal',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-label': 'Connect an MCP server',
    });
    overlay.appendChild(modal);
    root.appendChild(overlay);

    keyHandler = function (e) {
      if (e.key === 'Escape') { e.stopPropagation(); close(); return; }
      trapTab(e);
    };
    document.addEventListener('keydown', keyHandler, true);

    renderStep1('');
  }

  // ── Step 1: Paste screen ──────────────────────────────────────────────────────

  function renderStep1(prefill) {
    clear(modal);
    prefill = prefill || '';

    const hdr = $el('div', { className: 'mcp-modal-header' });
    hdr.appendChild($el('span', { textContent: 'Connect an MCP server', className: 'mcp-modal-title' }));
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×', title: 'Close' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body' });
    body.appendChild($el('p', {
      className: 'mcp-modal-hint',
      textContent: 'Tell us about the MCP you want to connect. Paste a URL, JSON config, or any text from a README — we\'ll figure out the rest.',
    }));

    const ta = $el('textarea', {
      className: 'mcp-json-textarea',
      placeholder: 'Paste a GitHub URL, server URL, JSON config, or command\ne.g. npx @playwright/mcp@latest',
    });
    ta.value = prefill;
    body.appendChild(ta);

    const footer = $el('div', { className: 'mcp-modal-footer' });
    const cancelBtn = $el('button', { textContent: 'Cancel', className: 'btn-secondary' });
    cancelBtn.onclick = close;
    const analyzeBtn = $el('button', { textContent: 'Analyze →', className: 'btn-primary' });
    analyzeBtn.onclick = function () { doAnalyze(ta.value); };
    footer.appendChild(cancelBtn);
    footer.appendChild(analyzeBtn);

    modal.appendChild(hdr);
    modal.appendChild(body);
    modal.appendChild(footer);
    ta.focus();
  }

  // ── Analyze call ──────────────────────────────────────────────────────────────

  function renderAnalyzing() {
    clear(modal);
    const body = $el('div', { className: 'mcp-modal-body mcp-modal-center' });
    body.appendChild($el('div', { className: 'mcp-spinner' }));
    body.appendChild($el('p', { textContent: 'Analyzing…', className: 'mcp-modal-hint' }));
    modal.appendChild(body);
  }

  async function doAnalyze(rawInput) {
    if (!rawInput.trim()) return;
    state.rawInput = rawInput;
    renderAnalyzing();
    try {
      const resp = await fetch('/api/config/mcp/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_input: rawInput }),
      });
      const result = await resp.json();
      if (!result.ok) {
        renderDetectionFailed(rawInput, result.error || 'unrecognized format');
      } else if (result.all_results && result.all_results.length > 1) {
        renderChooser(result.all_results, rawInput);
      } else {
        renderReview(result, rawInput);
      }
    } catch (e) {
      renderDetectionFailed(rawInput, 'Network error — please try again.');
    }
  }

  // ── Manual-config escape hatch ───────────────────────────────────────────────
  // Used by every failure surface (auto-detect, OAuth discovery, network/SSL).
  // Carries over whatever fields we already have so the user doesn't retype.
  function _manualEscapeBtn(resultOrCfg) {
    const r = resultOrCfg || {};
    const prefill = {
      transport: r.transport || 'http',
      name: r.name || '',
      url: r.url || '',
      command: r.command || '',
      args: Array.isArray(r.args) ? r.args.join(' ') : (r.args || ''),
      auth_type: (r.auth_type && r.auth_type !== 'oauth2') ? r.auth_type : 'none',
      auth_value: r.auth_value || '',
      headers: r.headers || r.extra_headers || {},
      env: r.env || {},
    };
    const btn = $el('button', {
      type: 'button',
      className: 'mcp-manual-link mcp-manual-link--inline',
      textContent: 'Configure manually →',
      title: 'Skip auto-detect and enter the server config yourself',
    });
    btn.onclick = function () { renderManual(prefill); };
    return btn;
  }

  // ── Error parsing ─────────────────────────────────────────────────────────────

  function parseErrorMsg(raw) {
    if (!raw) return raw;
    if (/^auth_error:session_terminated/.test(raw)) {
      return 'Server closed the connection before handshake completed. Check the URL for typos, and add any required Headers below before retrying.';
    }
    if (/^auth_error:probe_failed/.test(raw)) {
      var detail = raw.replace(/^auth_error:probe_failed:?/, '').trim();
      var hint = detail.match(/['"]([a-zA-Z][\w-]*-[\w-]+)['"]/);
      if (hint) {
        return 'Connected — but tool calls require the “' + hint[1] + '” header. Paste the value in the Headers field below, then retry.';
      }
      return 'Connected — but tool calls require authentication. Add the required header in the Headers field below, then retry.';
    }
    if (/^auth_error:4\d\d/.test(raw) || /\b401\b/.test(raw) || /unauthorized/i.test(raw)) {
      return 'Authentication failed — update the credentials below and retry.';
    }
    if (/command not found/i.test(raw)) return raw;
    if (/no tools/i.test(raw)) return 'Server connected but returned no tools — check the URL or auth settings.';
    // Script file not found — extract filename for a friendly message
    var fileMatch = raw.match(/can['']t open file[^']*['"]([^'"]+)['"]/i) ||
                    raw.match(/No such file or directory[^:]*:\s*['"]?([^\s'"]+\.(?:py|js|ts))['"]?/i);
    if (fileMatch || /no such file or directory/i.test(raw)) {
      var fname = fileMatch ? fileMatch[1].split(/[\\/]/).pop() : 'the script file';
      return 'Can’t find “' + fname + '” — update the path below to where it lives on your machine.';
    }
    // Strip embedded JSON blobs: "Could not list tools: {...}" → "Could not list tools"
    return raw.replace(/:\s*[\[{][^}\]]{0,300}[\]}]/, '').trim() || raw;
  }

  // ── Step 2: Review card (read-only when ok, editable when error) ──────────────

  function renderReview(result, rawInput, errorMsg) {
    clear(modal);
    state.pendingResult = result;

    const isEditMode = errorMsg === '\x00edit';
    const friendlyError = (errorMsg && !isEditMode) ? parseErrorMsg(errorMsg) : null;
    const isStdio = result.transport === 'stdio';

    const hdr = $el('div', { className: 'mcp-modal-header' });
    const backBtn = $el('button', { className: 'mcp-modal-back', textContent: '‹', title: 'Back' });
    backBtn.onclick = function () { renderStep1(rawInput); };
    hdr.appendChild(backBtn);
    hdr.appendChild($el('span', { textContent: 'Connect an MCP server', className: 'mcp-modal-title' }));
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body' });

    if (friendlyError) {
      const errBanner = $el('div', { className: 'mcp-inline-error' });
      errBanner.appendChild($el('span', { textContent: '✕ ' + friendlyError }));
      // Always-available escape hatch: auto-detect failed but the user might
      // know exactly what to enter. Drops them into the plain manual form
      // with whatever we already parsed (URL, name, headers) preserved.
      errBanner.appendChild(_manualEscapeBtn(result));
      body.appendChild(errBanner);
    }

    if (!errorMsg && (result.confidence === 'low' || result.confidence === 'medium')) {
      const warn = $el('div', { className: 'mcp-confidence-warning' });
      warn.appendChild($el('span', { textContent: '⚠ We\'re not certain about this — please review before connecting.' }));
      body.appendChild(warn);
    }

    const detectedLabel = isStdio ? '✓ Found a local MCP server' : '✓ Found a remote MCP server';
    body.appendChild($el('p', { textContent: detectedLabel, className: 'mcp-detected-label' }));

    // ── Unified OAuth section (used by both read-only and editable modes) ─────
    // Single source of truth for sign-in state. Both branches assign these so the
    // CTA-morphing logic doesn't need to know which mode it's in.
    let oauthStatus = function () { return { isOauth: false, signedIn: true }; };
    let runOAuthIfNeeded = function (cb) { cb(true); };

    function createOauthSection(initialProviderId, getUrl, getLabel, onStateChange, getConnectionId) {
      let providerId = initialProviderId || '';
      const helper = $el('div', { className: 'mcp-auth-helper' });

      function refresh() {
        clear(helper);
        if (providerId) {
          helper.className = 'mcp-auth-helper ok';
          helper.appendChild(document.createTextNode('✓ Signed in  '));
          const btn = $el('button', { type: 'button', className: 'mcp-auth-linkbtn', textContent: 'Sign out' });
          btn.onclick = function () {
            const pid = providerId;
            providerId = '';
            refresh();
            if (onStateChange) onStateChange();
            fetch('/api/config/mcp/oauth/forget?provider_id=' + encodeURIComponent(pid),
              { method: 'POST' }).catch(function () {});
          };
          helper.appendChild(btn);
        } else {
          helper.className = 'mcp-auth-helper warn';
          helper.textContent = '⚠ Sign-in required to continue';
        }
      }

      function runFlow(onDone) {
        const u = (getUrl() || '').trim();
        if (!u) {
          helper.className = 'mcp-auth-helper err';
          helper.textContent = '✕ Enter the MCP URL first.';
          if (onStateChange) onStateChange();
          if (onDone) onDone(false);
          return;
        }
        helper.className = 'mcp-auth-helper';
        helper.textContent = 'Discovering OAuth metadata…';
        if (onStateChange) onStateChange();
        fetch('/api/config/mcp/oauth/start', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url: u,
            label: getLabel() || u,
            connection_id: (typeof getConnectionId === 'function' ? (getConnectionId() || '') : ''),
          }),
        }).then(function (r) {
          return r.json().then(function (d) { return { ok: r.ok, body: d }; });
        }).then(function (resp) {
          if (!resp.ok) {
            helper.className = 'mcp-auth-helper err';
            helper.textContent = '✕ ' + ((resp.body && resp.body.detail) || 'OAuth start failed');
            helper.appendChild(document.createTextNode(' '));
            helper.appendChild(_manualEscapeBtn({ url: getUrl(), name: getLabel() }));
            if (onStateChange) onStateChange();
            if (onDone) onDone(false);
            return;
          }
          const st = resp.body.state;
          const provId = resp.body.provider_id;
          const popup = window.open(resp.body.authorize_url, 'mcp_oauth',
            'width=560,height=720,menubar=no,toolbar=no');
          if (!popup) {
            helper.className = 'mcp-auth-helper err';
            helper.textContent = '✕ Popup blocked — allow popups and retry.';
            if (onStateChange) onStateChange();
            if (onDone) onDone(false);
            return;
          }
          helper.className = 'mcp-auth-helper';
          helper.textContent = 'Waiting for you to authorize…';
          let closedSince = 0;
          const finish = function (ok, err) {
            if (ok) { providerId = provId; refresh(); }
            else {
              helper.className = 'mcp-auth-helper err';
              helper.textContent = '✕ ' + (err || 'Auth failed');
              helper.appendChild(document.createTextNode(' '));
              helper.appendChild(_manualEscapeBtn({ url: getUrl(), name: getLabel() }));
            }
            if (onStateChange) onStateChange();
            if (onDone) onDone(ok);
          };
          const poll = setInterval(function () {
            fetch('/api/config/mcp/oauth/poll?state=' + encodeURIComponent(st))
              .then(function (r) { return r.json(); })
              .then(function (s) {
                if (s.status === 'done') { clearInterval(poll); finish(s.ok, s.error); return; }
                if (popup.closed) {
                  if (!closedSince) closedSince = Date.now();
                  if (Date.now() - closedSince >= 4000) {
                    clearInterval(poll);
                    finish(false, 'Popup closed before completing.');
                  }
                }
              }).catch(function () {});
          }, 800);
          setTimeout(function () { clearInterval(poll); }, 5 * 60 * 1000);
        }).catch(function (e) {
          helper.className = 'mcp-auth-helper err';
          helper.textContent = '✕ ' + e;
          helper.appendChild(document.createTextNode(' '));
          helper.appendChild(_manualEscapeBtn({ url: getUrl(), name: getLabel() }));
          if (onStateChange) onStateChange();
          if (onDone) onDone(false);
        });
      }

      return {
        helper: helper,
        refresh: refresh,
        runFlow: runFlow,
        getProviderId: function () { return providerId; },
      };
    }

    // ── Read-only card (no error) ─────────────────────────────────────────────
    let getConnectPayload;

    if (!errorMsg) {
      // Flat layout — no nested card. Just rows on the modal body.
      const nameRow = $el('div', { className: 'mcp-review-name-row' });
      nameRow.appendChild($el('label', { textContent: 'Name', className: 'mcp-review-name-label' }));
      const nameInput = $el('input', {
        type: 'text',
        className: 'mcp-review-name-input',
        placeholder: 'Give this connection a name',
      });
      nameInput.value = result.name || '';
      nameRow.appendChild(nameInput);
      body.appendChild(nameRow);
      body.appendChild(attachNameValidator(nameInput, function () { return result.connection_id || ''; }));

      body.appendChild($el('div', {
        textContent: isStdio ? 'Local · stdio' : 'Remote · HTTPS',
        className: 'mcp-review-type',
      }));
      if (!isStdio) {
        body.appendChild($el('div', { textContent: result.url, className: 'mcp-review-detail' }));
      } else {
        const cmdRow = $el('div', { className: 'mcp-review-detail' });
        cmdRow.appendChild($el('span', { textContent: 'command  ', className: 'mcp-review-key' }));
        cmdRow.appendChild($el('span', { textContent: result.command }));
        body.appendChild(cmdRow);
        if (result.args && result.args.length) {
          const argsRow = $el('div', { className: 'mcp-review-detail' });
          argsRow.appendChild($el('span', { textContent: 'args     ', className: 'mcp-review-key' }));
          argsRow.appendChild($el('span', { textContent: result.args.join(' ') }));
          body.appendChild(argsRow);
        }
      }
      if (result.prerequisite_warning) {
        body.appendChild($el('p', { textContent: '⚠ ' + result.prerequisite_warning, className: 'mcp-prereq-warning' }));
      }

      // Detect {placeholder} values in headers (HTTP) and env (stdio)
      var headerPH   = findPlaceholders(result.headers || {});
      var envPH      = findPlaceholders(result.env || {});
      var headerFields = buildPlaceholderFields(headerPH, 'This server requires connection details:', result.headers || {});
      var envFields    = buildPlaceholderFields(envPH,    'This server requires environment variables:', result.env || {});
      if (headerFields.container) body.appendChild(headerFields.container);
      if (envFields.container)    body.appendChild(envFields.container);

      // Auto-detected OAuth — show sign-in status inline so the user can authorize
      // before clicking Connect, instead of getting bounced by a server-side error.
      let roOauthSection = null;
      if (!isStdio && result.auth_type === 'oauth2') {
        roOauthSection = createOauthSection(
          result.oauth_provider_id || '',
          function () { return result.url; },
          function () { return nameInput.value.trim() || result.name || result.url; },
          function () { updateConnectBtn(); },
          function () { return result.connection_id || ''; }
        );
        body.appendChild(roOauthSection.helper);
        roOauthSection.refresh();
        oauthStatus = function () {
          return { isOauth: true, signedIn: !!roOauthSection.getProviderId() };
        };
        runOAuthIfNeeded = function (cb) {
          if (roOauthSection.getProviderId()) { cb(true); return; }
          roOauthSection.runFlow(cb);
        };
      }

      getConnectPayload = function () {
        var resolvedHeaders = resolvePlaceholders(result.headers || {}, headerFields.getValues());
        var resolvedEnv     = resolvePlaceholders(result.env || {}, envFields.getValues());
        return Object.assign({}, result, {
          name: nameInput.value.trim() || result.name || 'MCP Server',
          headers: resolvedHeaders,
          env: resolvedEnv,
          oauth_provider_id: roOauthSection ? roOauthSection.getProviderId() : (result.oauth_provider_id || ''),
        });
      };

    // ── Editable form (any error) ─────────────────────────────────────────────
    } else {
      const form = $el('div', { className: 'mcp-edit-form' });

      function field(labelText, inputEl) {
        const row = $el('div', { className: 'mcp-edit-row' });
        const lbl = $el('label', { textContent: labelText, className: 'mcp-edit-label' });
        row.appendChild(lbl);
        row.appendChild(inputEl);
        return row;
      }

      const nameInput = $el('input', { type: 'text', className: 'mcp-edit-input', placeholder: 'Server name' });
      nameInput.value = result.name || '';
      form.appendChild(field('Name', nameInput));
      form.appendChild(attachNameValidator(nameInput, function () { return result.connection_id || ''; }));

      // HTTP-specific fields
      let urlInput, authDrop, authValueInput, authValueRow, basicEmailInput, basicEmailRow;
      let editOauthSection = null;
      if (!isStdio) {
        urlInput = $el('input', { type: 'text', className: 'mcp-edit-input', placeholder: 'https://example.com/mcp' });
        urlInput.value = result.url || '';
        form.appendChild(field('URL', urlInput));

        // probe_failed means the credential goes in a custom Header (e.g. x-nabu-key),
        // not in a Bearer token — keep Auth=None so the Token field doesn't gate Save.
        const isProbeFailErr = /^auth_error:probe_failed/.test(errorMsg || '');
        const defaultAuth = (result.auth_type && result.auth_type !== 'none')
          ? result.auth_type
          : (!isProbeFailErr && /\b401\b|unauthorized|auth_error/i.test(errorMsg || '') ? 'bearer' : 'none');
        const authPlaceholders = {
          bearer: 'Token',
          api_key: 'API key',
          basic: 'API token',
        };
        // Split existing value if it's basic-format (email:token)
        const initialColon = (result.auth_value || '').indexOf(':');
        const initialEmail = (defaultAuth === 'basic' && initialColon > 0)
          ? result.auth_value.slice(0, initialColon) : '';
        const initialSecret = (defaultAuth === 'basic' && initialColon > 0)
          ? result.auth_value.slice(initialColon + 1) : (result.auth_value || '');

        authDrop = buildDropdown(
          [
            { value: 'none', label: 'No auth' },
            { value: 'bearer', label: 'Bearer token' },
            { value: 'api_key', label: 'API key' },
            { value: 'basic', label: 'Basic (email + token)' },
            { value: 'oauth2', label: 'OAuth 2.0' },
          ],
          defaultAuth,
          function (val) {
            const isOauth = val === 'oauth2';
            authValueRow.style.display = (val === 'none' || isOauth) ? 'none' : '';
            basicEmailRow.style.display = val === 'basic' ? '' : 'none';
            if (authValueInput && authPlaceholders[val]) {
              authValueInput.placeholder = authPlaceholders[val];
            }
            if (editOauthSection) {
              editOauthSection.helper.style.display = isOauth ? '' : 'none';
              if (isOauth) editOauthSection.refresh();
            }
            updateConnectBtn();
          }
        );
        const authRow = field('Auth', authDrop.el);
        form.appendChild(authRow);
        // OAuth section — helper text + sign-in/out controls, hidden unless oauth2 selected.
        editOauthSection = createOauthSection(
          result.oauth_provider_id || '',
          function () { return urlInput.value.trim(); },
          function () { return nameInput.value.trim() || urlInput.value.trim(); },
          function () { updateConnectBtn(); },
          function () { return result.connection_id || ''; }
        );
        editOauthSection.helper.style.display = defaultAuth === 'oauth2' ? '' : 'none';
        authRow.appendChild(editOauthSection.helper);
        if (defaultAuth === 'oauth2') editOauthSection.refresh();
        oauthStatus = function () {
          return {
            isOauth: authDrop.getValue() === 'oauth2',
            signedIn: !!editOauthSection.getProviderId(),
          };
        };
        runOAuthIfNeeded = function (cb) {
          if (authDrop.getValue() !== 'oauth2' || editOauthSection.getProviderId()) {
            cb(true); return;
          }
          editOauthSection.runFlow(cb);
        };

        basicEmailInput = $el('input', {
          type: 'email',
          className: 'mcp-edit-input',
          placeholder: 'you@example.com',
          autocomplete: 'username',
        });
        basicEmailInput.value = initialEmail;
        basicEmailRow = field('Email', basicEmailInput);
        basicEmailRow.style.display = defaultAuth === 'basic' ? '' : 'none';
        form.appendChild(basicEmailRow);

        // On edit, show the masked existing token as the placeholder so the user
        // knows a value is stored (and can leave the field blank to keep it).
        var maskedTokenHint = '';
        if (result.auth_value_hint) {
          maskedTokenHint = (defaultAuth === 'basic' && result.auth_value_hint.indexOf(':') > 0)
            ? result.auth_value_hint.split(':').slice(1).join(':')
            : result.auth_value_hint;
        }
        authValueInput = $el('input', {
          type: 'password',
          className: 'mcp-edit-input',
          placeholder: maskedTokenHint || authPlaceholders[defaultAuth] || 'Token or key',
          autocomplete: 'off',
        });
        authValueInput.value = initialSecret;
        authValueRow = field(defaultAuth === 'basic' ? 'API token' : 'Token / Key', authValueInput);
        authValueRow.style.display = (defaultAuth === 'none' || defaultAuth === 'oauth2') ? 'none' : '';
        form.appendChild(authValueRow);

        // Headers section — needed for servers that gate access on a custom
        // header (e.g. x-api-key). The session_terminated error specifically
        // tells the user to add one here, so it must exist on this form.
        var editHdrsContainer = $el('div', { className: 'mcp-kv-rows' });
        function editAddHdrRow(k, v) {
          var row = $el('div', { className: 'mcp-kv-row' });
          var kIn = $el('input', { type: 'text', className: 'mcp-kv-key', placeholder: 'Header name (e.g. x-api-key)' });
          kIn.value = k || '';
          // Backend hints come through as bullet-masked strings — show as
          // placeholder, not as value, so an unchanged field submits blank
          // (which the backend interprets as "keep stored secret").
          // Cover common mask glyphs: BLACK BULLET (•), WHITE CIRCLE (○),
          // BLACK CIRCLE (●), WHITE BULLET (◦), and any other dot-like char
          // a backend might emit. Anything starting with these is treated as
          // a placeholder, not a real value.
          var isMaskedHint = typeof v === 'string' && /^[•○●◦⚫⚪∙·]+/.test(v);
          // Templated values like "Basic {email}:{api_token}" must NOT land in a
          // password field — Ctrl-A + autofill/clipboard pastes garbage on top
          // (and we'd lose the template). Show the template as placeholder text;
          // user fills the per-variable inputs rendered above.
          var isTemplated = typeof v === 'string' && /\{[A-Za-z_][A-Za-z0-9_]*\}/.test(v);
          var vIn = $el('input', {
            type: 'password',
            className: 'mcp-kv-val',
            placeholder: (isMaskedHint || isTemplated) ? v : 'Value',
          });
          // Stash the original templated value on the row so substitution can
          // re-apply it on submit when the user hasn't overwritten it.
          if (isTemplated) row.dataset.template = v;
          vIn.value = (isMaskedHint || isTemplated) ? '' : (v || '');
          var rm = $el('button', { type: 'button', className: 'mcp-kv-rm', textContent: '×', title: 'Remove' });
          rm.onclick = function () { editHdrsContainer.removeChild(row); };
          row.appendChild(kIn); row.appendChild(vIn); row.appendChild(rm);
          editHdrsContainer.appendChild(row);
          return kIn;
        }
        var existingHeaders = result.headers || {};
        // If any header value carries {placeholder} tokens, render labeled inputs
        // for each unique variable above the KV widget — mirrors the read-only
        // path so users can supply secrets without ever seeing/editing the raw
        // templated header (which would lose the template + invite paste errors).
        var editHeaderPH = findPlaceholders(existingHeaders);
        var editHeaderFields = buildPlaceholderFields(
          editHeaderPH, 'This server requires connection details:', existingHeaders);
        if (editHeaderFields.container) form.appendChild(editHeaderFields.container);
        Object.keys(existingHeaders).forEach(function (k) { editAddHdrRow(k, existingHeaders[k]); });

        var editHdrsLabelRow = $el('div', { className: 'mcp-edit-row' });
        editHdrsLabelRow.appendChild($el('label', { textContent: 'Headers', className: 'mcp-edit-label' }));
        var editHdrsRight = $el('div', { style: 'flex:1' });
        editHdrsRight.appendChild(editHdrsContainer);
        var editAddHdrBtn = $el('button', { type: 'button', className: 'mcp-kv-add', textContent: '+ Add header' });
        editAddHdrBtn.onclick = function () {
          var kIn = editAddHdrRow('', '');
          setTimeout(function () { kIn.focus(); }, 0);
        };
        editHdrsRight.appendChild(editAddHdrBtn);
        editHdrsLabelRow.appendChild(editHdrsRight);
        form.appendChild(editHdrsLabelRow);

        // For session_terminated or auth_probe_failed: auto-add one empty row
        // + scroll/focus so the user sees exactly where to type without hunting.
        // If the probe_detail mentions a header name (e.g. `'x-nabu-key'`), pre-fill it.
        var isSessionTerm = /^auth_error:session_terminated/.test(errorMsg || '');
        var isProbeFail   = /^auth_error:probe_failed/.test(errorMsg || '');
        if ((isSessionTerm || isProbeFail) && Object.keys(existingHeaders).length === 0) {
          var hintedHeader = '';
          if (isProbeFail) {
            // Look for quoted header-like tokens (kebab-case, must contain a dash
            // to avoid matching generic words like 'authentication').
            var m = (errorMsg || '').match(/['"]([a-zA-Z][\w-]*-[\w-]+)['"]/);
            if (m) hintedHeader = m[1];
          }
          var firstKey = editAddHdrRow(hintedHeader, '');
          setTimeout(function () {
            try { editHdrsLabelRow.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) {}
            // If we pre-filled the header name, focus the value field instead.
            if (hintedHeader) {
              var row = firstKey.parentElement;
              var valIn = row && row.querySelector('.mcp-kv-val');
              if (valIn) { valIn.focus(); return; }
            }
            firstKey.focus();
          }, 60);
        }

        function getEditHeaders() {
          var out = {};
          var phValues = editHeaderFields.getValues();
          Array.from(editHdrsContainer.querySelectorAll('.mcp-kv-row')).forEach(function (row) {
            var k = row.querySelector('.mcp-kv-key').value.trim();
            var v = row.querySelector('.mcp-kv-val').value.trim();
            // Field left blank but row carries a template → re-apply the
            // template with placeholder substitutions so the credential is
            // assembled from the per-variable inputs above.
            if (!v && row.dataset.template) {
              v = row.dataset.template;
              Object.keys(phValues).forEach(function (varName) {
                v = v.split('{' + varName + '}').join(phValues[varName]);
              });
            }
            if (k) out[k] = v;
          });
          return out;
        }
        // Expose for getConnectPayload below.
        result.__getEditHeaders = getEditHeaders;

      // stdio-specific fields
      } else {
        const cmdInput = $el('input', { type: 'text', className: 'mcp-edit-input', placeholder: 'npx' });
        cmdInput.value = result.command || '';
        form.appendChild(field('Command', cmdInput));

        const argsInput = $el('input', { type: 'text', className: 'mcp-edit-input', placeholder: '@playwright/mcp@latest' });
        argsInput.value = (result.args || []).join(' ');
        form.appendChild(field('Args', argsInput));

        getConnectPayload = function () {
          return Object.assign({}, result, {
            name: nameInput.value.trim(),
            command: cmdInput.value.trim(),
            args: argsInput.value.trim().split(/\s+/).filter(Boolean),
          });
        };
      }

      if (!isStdio) {
        getConnectPayload = function () {
          const authType = authDrop.getValue();
          let authValue = '';
          if (authType === 'basic') {
            const em = basicEmailInput.value.trim();
            const tk = authValueInput.value.trim();
            authValue = em && tk ? em + ':' + tk : '';
          } else if (authType === 'oauth2') {
            authValue = '';
          } else if (authType !== 'none') {
            authValue = authValueInput.value.trim();
          }
          return Object.assign({}, result, {
            name: nameInput.value.trim(),
            url: urlInput.value.trim(),
            auth_type: authType,
            auth_value: authValue,
            headers: typeof result.__getEditHeaders === 'function'
              ? result.__getEditHeaders() : (result.headers || {}),
            oauth_provider_id: authType === 'oauth2' && editOauthSection
              ? editOauthSection.getProviderId() : '',
          });
        };
      }

      body.appendChild(form);
      // Focus first useful editable field
      setTimeout(function () {
        const isAuthErr = /\b401\b|unauthorized|auth_error/i.test(errorMsg);
        const isBasic = !isStdio && authDrop && authDrop.getValue() === 'basic';
        if (isBasic && isAuthErr && basicEmailInput && !basicEmailInput.value) {
          basicEmailInput.focus();
        } else if (!isStdio && isAuthErr && authValueInput) {
          authValueInput.focus();
        } else if (!isStdio && urlInput) {
          urlInput.focus();
        } else {
          nameInput.focus();
        }
      }, 0);
    }

    const footer = $el('div', { className: 'mcp-modal-footer' });
    const connectBtn = $el('button', {
      textContent: isEditMode ? 'Save' : errorMsg ? 'Try again' : 'Connect',
      className: 'btn-primary',
    });
    // Single morphing CTA: "Sign in & Connect" when oauth2 is required but the
    // user hasn't authorized yet; "Connect" / "Save" / "Try again" otherwise.
    // Works in both read-only and editable modes via the unified oauthStatus closure.
    function updateConnectBtn() {
      if (isStdio) return;
      const s = oauthStatus();
      const needsSignIn = s.isOauth && !s.signedIn;
      connectBtn.textContent = needsSignIn
        ? 'Sign in & Connect'
        : (isEditMode ? 'Save' : errorMsg ? 'Try again' : 'Connect');
    }
    connectBtn.onclick = function () {
      const s = oauthStatus();
      if (s.isOauth && !s.signedIn) {
        connectBtn.disabled = true;
        runOAuthIfNeeded(function (ok) {
          connectBtn.disabled = false;
          if (ok) doConnect(getConnectPayload(), rawInput);
        });
        return;
      }
      doConnect(getConnectPayload(), rawInput);
    };
    footer.appendChild(connectBtn);

    modal.appendChild(hdr);
    modal.appendChild(body);
    modal.appendChild(footer);
    if (!isStdio) updateConnectBtn();
    if (!errorMsg) connectBtn.focus();
  }

  // ── Chooser (multiple results) ────────────────────────────────────────────────

  function renderChooser(results, rawInput) {
    clear(modal);

    const hdr = $el('div', { className: 'mcp-modal-header' });
    const backBtn = $el('button', { className: 'mcp-modal-back', textContent: '‹', title: 'Back' });
    backBtn.onclick = function () { renderStep1(rawInput); };
    hdr.appendChild(backBtn);
    hdr.appendChild($el('span', { textContent: 'Choose a server', className: 'mcp-modal-title' }));
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body' });
    body.appendChild($el('p', {
      textContent: 'Found ' + results.length + ' servers — pick one to connect:',
      className: 'mcp-modal-hint',
    }));

    const list = $el('div', { className: 'mcp-chooser' });
    results.forEach(function (result) {
      const item = $el('button', { className: 'mcp-chooser-item' });
      item.appendChild($el('span', { textContent: result.name || 'MCP Server', className: 'mcp-chooser-name' }));
      item.appendChild($el('span', {
        textContent: result.transport === 'stdio' ? 'Local · stdio' : 'Remote · HTTPS',
        className: 'mcp-chooser-type',
      }));
      item.onclick = function () { renderReview(result, rawInput); };
      list.appendChild(item);
    });
    body.appendChild(list);

    modal.appendChild(hdr);
    modal.appendChild(body);
  }

  // ── Detection failed ──────────────────────────────────────────────────────────

  function renderDetectionFailed(rawInput, errorMsg) {
    clear(modal);

    const hdr = $el('div', { className: 'mcp-modal-header' });
    const backBtn = $el('button', { className: 'mcp-modal-back', textContent: '‹', title: 'Back' });
    backBtn.onclick = function () { renderStep1(rawInput); };
    hdr.appendChild(backBtn);
    hdr.appendChild($el('span', { textContent: 'Connect an MCP server', className: 'mcp-modal-title' }));
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body' });
    const errBox = $el('div', { className: 'mcp-parse-status mcp-parse-error' });
    errBox.appendChild($el('span', { textContent: '⚠ We couldn\'t recognize this format.' }));
    body.appendChild(errBox);

    const manualLink = $el('button', { textContent: 'Enter details manually →', className: 'mcp-manual-link' });
    manualLink.onclick = function () { renderManual({}); };
    body.appendChild(manualLink);

    modal.appendChild(hdr);
    modal.appendChild(body);
  }

  // ── Manual fallback form ──────────────────────────────────────────────────────

  function renderManual(prefill) {
    clear(modal);
    prefill = prefill || {};

    const hdr = $el('div', { className: 'mcp-modal-header' });
    const backBtn = $el('button', { className: 'mcp-modal-back', textContent: '‹', title: 'Back' });
    backBtn.onclick = function () { renderStep1(state.rawInput || ''); };
    hdr.appendChild(backBtn);
    hdr.appendChild($el('span', { textContent: 'Enter server details', className: 'mcp-modal-title' }));
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body mcp-manual-form' });

    const transportRow = $el('div', { className: 'mcp-form-row' });
    transportRow.appendChild($el('label', { textContent: 'Type', className: 'mcp-form-label' }));
    const transportSel = $el('select', { className: 'mcp-form-input' });
    ['Remote (HTTP)', 'Local (stdio)'].forEach(function (opt, i) {
      const o = $el('option', { textContent: opt, value: i === 0 ? 'http' : 'stdio' });
      transportSel.appendChild(o);
    });
    transportSel.value = prefill.transport || 'http';
    transportRow.appendChild(transportSel);
    body.appendChild(transportRow);

    const nameRow = $el('div', { className: 'mcp-form-row' });
    nameRow.appendChild($el('label', { textContent: 'Name', className: 'mcp-form-label' }));
    const nameInput = $el('input', { type: 'text', className: 'mcp-form-input', placeholder: 'My MCP Server' });
    nameInput.value = prefill.name || '';
    nameRow.appendChild(nameInput);
    body.appendChild(nameRow);
    body.appendChild(attachNameValidator(nameInput, function () { return prefill.connection_id || ''; }));

    const urlRow = $el('div', { className: 'mcp-form-row' });
    urlRow.appendChild($el('label', { textContent: 'Server URL', className: 'mcp-form-label' }));
    const urlInput = $el('input', { type: 'text', className: 'mcp-form-input', placeholder: 'https://example.com/mcp' });
    urlInput.value = prefill.url || '';
    urlRow.appendChild(urlInput);
    body.appendChild(urlRow);

    const cmdRow = $el('div', { className: 'mcp-form-row', style: 'display:none' });
    cmdRow.appendChild($el('label', { textContent: 'Command', className: 'mcp-form-label' }));
    const cmdInput = $el('input', { type: 'text', className: 'mcp-form-input', placeholder: 'npx' });
    cmdInput.value = prefill.command || '';
    cmdRow.appendChild(cmdInput);
    body.appendChild(cmdRow);

    const argsRow = $el('div', { className: 'mcp-form-row', style: 'display:none' });
    argsRow.appendChild($el('label', { textContent: 'Args', className: 'mcp-form-label' }));
    const argsInput = $el('input', { type: 'text', className: 'mcp-form-input', placeholder: '@playwright/mcp@latest' });
    argsInput.value = (prefill.args || []).join(' ');
    argsRow.appendChild(argsInput);
    body.appendChild(argsRow);

    // ── Auth ────────────────────────────────────────────────────────────────────
    const authRow = $el('div', { className: 'mcp-form-row' });
    authRow.appendChild($el('label', { textContent: 'Auth', className: 'mcp-form-label' }));
    const authSel = $el('select', { className: 'mcp-form-input' });
    [
      { value: 'none',    label: 'None' },
      { value: 'bearer',  label: 'Bearer token' },
      { value: 'basic',   label: 'Basic (email:token)' },
      { value: 'api_key', label: 'API key' },
    ].forEach(function (opt) {
      authSel.appendChild($el('option', { value: opt.value, textContent: opt.label }));
    });
    authSel.value = prefill.auth_type || 'none';
    authRow.appendChild(authSel);
    body.appendChild(authRow);

    const authValRow = $el('div', { className: 'mcp-form-row' });
    authValRow.appendChild($el('label', { textContent: 'Credential', className: 'mcp-form-label' }));
    const authValInput = $el('input', { type: 'password', className: 'mcp-form-input', placeholder: 'token / email:api_token' });
    authValInput.value = prefill.auth_value || '';
    authValRow.appendChild(authValInput);
    body.appendChild(authValRow);

    // ── Headers (extra_headers key-value) ────────────────────────────────────
    const hdrsLabel = $el('div', { className: 'mcp-form-row' });
    hdrsLabel.appendChild($el('label', { textContent: 'Headers', className: 'mcp-form-label' }));
    const hdrsHint = $el('span', { textContent: 'Extra HTTP headers (e.g. x-api-key)', className: 'mcp-form-sublabel' });
    hdrsLabel.appendChild(hdrsHint);
    body.appendChild(hdrsLabel);

    const hdrsContainer = $el('div', { className: 'mcp-kv-rows' });

    function addHdrRow(k, v) {
      const row = $el('div', { className: 'mcp-kv-row' });
      const kIn = $el('input', { type: 'text', className: 'mcp-kv-key', placeholder: 'Header name' });
      kIn.value = k || '';
      const vIn = $el('input', { type: 'password', className: 'mcp-kv-val', placeholder: 'Value' });
      vIn.value = v || '';
      const rm = $el('button', { type: 'button', className: 'mcp-kv-rm', textContent: '×', title: 'Remove' });
      rm.onclick = function () { hdrsContainer.removeChild(row); };
      row.appendChild(kIn);
      row.appendChild(vIn);
      row.appendChild(rm);
      hdrsContainer.appendChild(row);
    }

    // Pre-populate from prefill
    const prefillHeaders = prefill.headers || {};
    Object.keys(prefillHeaders).forEach(function (k) { addHdrRow(k, prefillHeaders[k]); });

    const hdrsWidget = $el('div', { className: 'mcp-form-row mcp-kv-widget' });
    hdrsWidget.appendChild($el('div', { className: 'mcp-form-label' })); // spacer
    const hdrsRight = $el('div', { style: 'flex:1' });
    hdrsRight.appendChild(hdrsContainer);
    const addHdrBtn = $el('button', { type: 'button', className: 'mcp-kv-add', textContent: '+ Add header' });
    addHdrBtn.onclick = function () { addHdrRow('', ''); };
    hdrsRight.appendChild(addHdrBtn);
    hdrsWidget.appendChild(hdrsRight);
    body.appendChild(hdrsWidget);

    function getHeaders() {
      var out = {};
      Array.from(hdrsContainer.querySelectorAll('.mcp-kv-row')).forEach(function (row) {
        var k = row.querySelector('.mcp-kv-key').value.trim();
        var v = row.querySelector('.mcp-kv-val').value.trim();
        if (k) out[k] = v;
      });
      return out;
    }

    function refreshFields() {
      const isStdio = transportSel.value === 'stdio';
      urlRow.style.display = isStdio ? 'none' : '';
      cmdRow.style.display = isStdio ? '' : 'none';
      argsRow.style.display = isStdio ? '' : 'none';
      authRow.style.display = isStdio ? 'none' : '';
      authValRow.style.display = (isStdio || authSel.value === 'none') ? 'none' : '';
      hdrsLabel.style.display = isStdio ? 'none' : '';
      hdrsWidget.style.display = isStdio ? 'none' : '';
    }

    authSel.onchange = function () {
      authValRow.style.display = authSel.value === 'none' ? 'none' : '';
    };
    transportSel.onchange = refreshFields;
    refreshFields();

    const footer = $el('div', { className: 'mcp-modal-footer' });
    const cancelBtn = $el('button', { textContent: 'Cancel', className: 'btn-secondary' });
    cancelBtn.onclick = close;
    const connectBtn = $el('button', { textContent: 'Connect', className: 'btn-primary' });
    connectBtn.onclick = function () {
      const isStdio = transportSel.value === 'stdio';
      const result = {
        ok: true,
        transport: transportSel.value,
        name: nameInput.value.trim(),
        url: isStdio ? '' : urlInput.value.trim(),
        auth_type: isStdio ? 'none' : authSel.value,
        auth_value: isStdio ? '' : authValInput.value.trim(),
        headers: isStdio ? {} : getHeaders(),
        command: isStdio ? cmdInput.value.trim() : '',
        args: isStdio ? argsInput.value.trim().split(/\s+/).filter(Boolean) : [],
        env: {},
      };
      if (isStdio && !result.command) return;
      if (!isStdio && !result.url) return;
      doConnect(result);
    };
    footer.appendChild(cancelBtn);
    footer.appendChild(connectBtn);

    modal.appendChild(hdr);
    modal.appendChild(body);
    modal.appendChild(footer);
    nameInput.focus();
  }

  // ── Connect (calls existing save endpoint) ────────────────────────────────────

  async function doConnect(result, rawInput) {
    const payload = {
      transport: result.transport,
      name: result.name,
      url: result.url || '',
      auth_type: result.auth_type || 'none',
      auth_value: result.auth_value || '',
      headers: result.headers || {},
      oauth_provider_id: result.oauth_provider_id || '',
      command: result.command || '',
      args: result.args || [],
      env: result.env || {},
      // When set, backend updates this record in place — rename keeps the same id.
      connection_id: result.connection_id || '',
    };
    state.payload = payload;
    renderConnecting(payload);
    try {
      const resp = await fetch('/api/config/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (resp.ok && data.name) {
        renderSuccess(data);
      } else if (data.oauth_required) {
        // Server returned 401 + WWW-Authenticate with OAuth discovery URL.
        // Re-render review form with auth_type=oauth2 so the OAuth sign-in
        // section appears automatically — user clicks "Sign in & Connect".
        var oauthResult = Object.assign({}, result, {
          url: data.mcp_url || result.url || '',
          auth_type: 'oauth2',
          oauth_provider_id: '',
        });
        renderReview(oauthResult, rawInput || state.rawInput || '', null);
      } else if (data.auth_probe_failed) {
        // Tools listed but a probe call required auth. Re-render the form with
        // a marker errorMsg so the Headers field auto-focuses and any header
        // name hinted by the probe response is pre-filled. Force auth_type to
        // 'none' — the credential goes in Headers, not in the Token field.
        var probeMsg = 'auth_error:probe_failed:' + (data.probe_detail || data.error || '');
        var probeResult = Object.assign({}, result, {
          auth_type: 'none',
          auth_value: '',
        });
        renderReview(probeResult, rawInput || state.rawInput || '', probeMsg);
      } else {
        // FastAPI errors come as {detail: "..."}, our own as {error: "..."}
        const msg = data.detail || data.error || 'Connection failed';
        renderReview(result, rawInput || state.rawInput || '', msg);
      }
    } catch (e) {
      renderReview(result, rawInput || state.rawInput || '', 'Network error — please try again.');
    }
  }

  // ── Connecting / Success / Error ──────────────────────────────────────────────

  function renderConnecting(payload) {
    // Overlay on top of whatever screen is currently in the modal — keeps
    // user's context visible (faded) so the transition doesn't feel like
    // the app got stuck. Removed when renderError/renderSuccess swap modal.
    var existing = modal.querySelector('.mcp-connect-overlay');
    if (existing) existing.remove();

    var target = payload.transport === 'stdio'
      ? (payload.command + ' ' + (payload.args || []).join(' ')).trim()
      : (payload.name || payload.url || 'server');

    var overlay = $el('div', { class: 'mcp-connect-overlay' });
    overlay.appendChild($el('div', { class: 'mcp-spinner' }));
    overlay.appendChild($el('div', { class: 'mcp-connect-title', text: 'Connecting to ' + target + '…' }));
    overlay.appendChild($el('div', { class: 'mcp-connect-sub', text: 'This usually takes a few seconds.' }));
    modal.appendChild(overlay);
  }

  function renderSuccess(data) {
    const count = data.tool_count || 0;
    const serverName = data.name || 'server';
    if (state && state.opts && typeof state.opts.onSuccess === 'function') {
      try { state.opts.onSuccess(data); } catch (e) { console.error('[mcp-modal] onSuccess threw:', e); }
    }
    close();
    showSuccessToast('"' + serverName + '" connected · ' + count + ' tool' + (count !== 1 ? 's' : ''));
  }

  function showSuccessToast(message) {
    if (typeof window._showConnectivityToast === 'function') {
      window._showConnectivityToast(message, 'success');
      return;
    }
    const t = $el('div', {
      class: 'mcp-toast',
      role: 'status',
      'aria-live': 'polite',
      text: '✓ ' + message,
    });
    document.body.appendChild(t);
    setTimeout(function () { t.classList.add('mcp-toast-out'); }, 2600);
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 3000);
  }

  function renderError(detail, pendingResult) {
    clear(modal);
    const goBack = pendingResult
      ? function () { renderReview(pendingResult, state.rawInput || ''); }
      : function () { renderStep1(state.rawInput || ''); };

    modal.appendChild($el('div', { class: 'mcp-modal-header' }, [
      $el('button', {
        type: 'button',
        class: 'mcp-modal-back',
        onclick: goBack,
        'aria-label': 'Back',
        text: '‹',
      }),
      $el('span', { text: 'Could not connect' }),
      $el('button', {
        type: 'button',
        class: 'mcp-modal-close',
        onclick: close,
        'aria-label': 'Close',
        text: '×',
      }),
    ]));
    modal.appendChild($el('div', { class: 'mcp-modal-body' }, [
      $el('div', { class: 'mcp-error', text: detail || 'Unknown error' }),
    ]));
    modal.appendChild($el('div', { class: 'mcp-modal-footer' }, [
      $el('button', { type: 'button', class: 'btn-ghost', onclick: close, text: 'Cancel' }),
      $el('button', {
        type: 'button',
        class: 'btn-primary',
        text: 'Back to review',
        onclick: goBack,
      }),
    ]));
  }

  window.openMcpAddModal = openModal;
  window.buildDropdown = buildDropdown;

  window.openMcpEditModal = function (conn, opts) {
    // Open the modal pre-filled with an existing connection's data, skipping the paste step.
    // conn: object from /api/config/mcp (id, name, transport, url, auth_type, command, args, env, extra_headers)
    if (overlay) close();
    state = { opts: opts || {} };
    root = document.getElementById('mcp-modal-root');
    if (!root) return;
    prevFocus = document.activeElement;

    overlay = $el('div', {
      class: 'mcp-modal-overlay',
      role: 'presentation',
      onclick: function (e) { if (e.target === overlay) close(); },
    });
    modal = $el('div', {
      class: 'mcp-modal',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-label': 'Edit MCP server',
    });
    overlay.appendChild(modal);
    root.appendChild(overlay);

    keyHandler = function (e) {
      if (e.key === 'Escape') { e.stopPropagation(); close(); return; }
      trapTab(e);
    };
    document.addEventListener('keydown', keyHandler, true);

    // Build a NormalizeResult-shaped object from the saved connection record.
    // Secrets are NEVER pre-filled. For 'basic' auth the email (left of ':') is not
    // a credential, so we pre-fill that half from the hint; the token half stays
    // blank and the masked hint is shown as a placeholder.
    var hint = conn.auth_value_hint || '';
    var prefillAuthValue = '';
    if (conn.auth_type === 'basic' && hint.indexOf(':') > 0) {
      // hint looks like "you@example.com:••••wxyz" — keep email, drop masked token.
      prefillAuthValue = hint.split(':')[0] + ':';
    }
    // Pre-fill header keys with masked values as placeholders so the user can
    // see which headers exist. Values stay blank — backend treats blank-on-edit
    // as "keep stored secret". Same approach for stdio env vars.
    var headersHint = conn.extra_headers_hint || {};
    var envHint = conn.env_hint || {};
    var prefill = {
      ok: true,
      connection_id: conn.id || '',
      transport: conn.transport || 'http',
      name: conn.name || '',
      url: conn.url || '',
      auth_type: conn.auth_type || 'none',
      auth_value: prefillAuthValue,                    // basic-email only, never the secret
      auth_value_hint: hint,                            // masked preview for placeholder
      headers: headersHint,                             // {key: "••••wxyz"} — value shown as masked placeholder; blank on save = keep
      oauth_provider_id: conn.oauth_provider_id || '', // so OAuth section shows "Signed in"
      command: conn.command || '',
      args: conn.args || [],
      env: envHint,                                     // same masking pattern
    };
    // Open straight into the editable form (reuse error-mode UI which shows all fields)
    // Pass a sentinel errorMsg so the form renders but don't show an error banner
    renderReview(prefill, '', '\x00edit');
  };
  window._mcpModal = {
    renderStep1: renderStep1,
    renderReview: renderReview,
    renderChooser: renderChooser,
    renderDetectionFailed: renderDetectionFailed,
    renderManual: renderManual,
    renderConnecting: renderConnecting,
    renderSuccess: renderSuccess,
    renderError: renderError,
    doConnect: doConnect,
    doAnalyze: doAnalyze,
    $el: $el,
    clear: clear,
    close: close,
    get modal() { return modal; },
    get state() { return state; },
  };
})();
