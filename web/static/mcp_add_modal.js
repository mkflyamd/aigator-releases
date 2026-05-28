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

  function buildPlaceholderFields(placeholders, hint) {
    // Returns {container, getValues}. getValues() → {varName: filledValue}.
    var inputs = {};
    if (placeholders.length === 0) {
      return { container: null, getValues: function () { return {}; } };
    }
    var container = $el('div', { className: 'mcp-placeholder-section' });
    container.appendChild($el('p', { className: 'mcp-placeholder-hint', textContent: hint }));
    placeholders.forEach(function (p) {
      var row = $el('div', { className: 'mcp-edit-row' });
      var label = p.key.replace(/^X-/i, '').replace(/-/g, ' ');
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

  // ── Error parsing ─────────────────────────────────────────────────────────────

  function parseErrorMsg(raw) {
    if (!raw) return raw;
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
      body.appendChild(errBanner);
    }

    if (!errorMsg && (result.confidence === 'low' || result.confidence === 'medium')) {
      const warn = $el('div', { className: 'mcp-confidence-warning' });
      warn.appendChild($el('span', { textContent: '⚠ We\'re not certain about this — please review before connecting.' }));
      body.appendChild(warn);
    }

    const detectedLabel = isStdio ? '✓ Found a local MCP server' : '✓ Found a remote MCP server';
    body.appendChild($el('p', { textContent: detectedLabel, className: 'mcp-detected-label' }));

    // ── Read-only card (no error) ─────────────────────────────────────────────
    let getConnectPayload;

    if (!errorMsg) {
      const card = $el('div', { className: 'mcp-review-card' });
      card.appendChild($el('div', { textContent: result.name || 'MCP Server', className: 'mcp-review-name' }));
      card.appendChild($el('div', {
        textContent: isStdio ? 'Local · stdio' : 'Remote · HTTPS',
        className: 'mcp-review-type',
      }));
      if (!isStdio) {
        card.appendChild($el('div', { textContent: result.url, className: 'mcp-review-detail' }));
      } else {
        const cmdRow = $el('div', { className: 'mcp-review-detail' });
        cmdRow.appendChild($el('span', { textContent: 'command  ', className: 'mcp-review-key' }));
        cmdRow.appendChild($el('span', { textContent: result.command }));
        card.appendChild(cmdRow);
        if (result.args && result.args.length) {
          const argsRow = $el('div', { className: 'mcp-review-detail' });
          argsRow.appendChild($el('span', { textContent: 'args     ', className: 'mcp-review-key' }));
          argsRow.appendChild($el('span', { textContent: result.args.join(' ') }));
          card.appendChild(argsRow);
        }
      }
      body.appendChild(card);
      if (result.prerequisite_warning) {
        body.appendChild($el('p', { textContent: '⚠ ' + result.prerequisite_warning, className: 'mcp-prereq-warning' }));
      }

      // Detect {placeholder} values in headers (HTTP) and env (stdio)
      var headerPH   = findPlaceholders(result.headers || {});
      var envPH      = findPlaceholders(result.env || {});
      var headerFields = buildPlaceholderFields(headerPH, 'This server requires connection details:');
      var envFields    = buildPlaceholderFields(envPH,    'This server requires environment variables:');
      if (headerFields.container) body.appendChild(headerFields.container);
      if (envFields.container)    body.appendChild(envFields.container);

      getConnectPayload = function () {
        var resolvedHeaders = resolvePlaceholders(result.headers || {}, headerFields.getValues());
        var resolvedEnv     = resolvePlaceholders(result.env || {}, envFields.getValues());
        return Object.assign({}, result, { headers: resolvedHeaders, env: resolvedEnv });
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

      // HTTP-specific fields
      let urlInput, authDrop, authValueInput, authValueRow;
      if (!isStdio) {
        urlInput = $el('input', { type: 'text', className: 'mcp-edit-input', placeholder: 'https://example.com/mcp' });
        urlInput.value = result.url || '';
        form.appendChild(field('URL', urlInput));

        const defaultAuth = (result.auth_type && result.auth_type !== 'none')
          ? result.auth_type
          : (/\b401\b|unauthorized|auth_error/i.test(errorMsg || '') ? 'bearer' : 'none');
        authDrop = buildDropdown(
          [{ value: 'none', label: 'No auth' }, { value: 'bearer', label: 'Bearer token' }, { value: 'api_key', label: 'API key' }],
          defaultAuth,
          function (val) { authValueRow.style.display = val === 'none' ? 'none' : ''; }
        );
        form.appendChild(field('Auth', authDrop.el));

        authValueInput = $el('input', {
          type: 'password',
          className: 'mcp-edit-input',
          placeholder: 'Token or key',
          autocomplete: 'off',
        });
        authValueInput.value = result.auth_value || '';
        authValueRow = field('Token / Key', authValueInput);
        authValueRow.style.display = defaultAuth === 'none' ? 'none' : '';
        form.appendChild(authValueRow);

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
          return Object.assign({}, result, {
            name: nameInput.value.trim(),
            url: urlInput.value.trim(),
            auth_type: authType,
            auth_value: authType !== 'none' ? authValueInput.value.trim() : '',
          });
        };
      }

      body.appendChild(form);
      // Focus first useful editable field
      setTimeout(function () {
        const isAuthErr = /\b401\b|unauthorized|auth_error/i.test(errorMsg);
        if (!isStdio && isAuthErr && authValueInput) {
          authValueInput.focus();
        } else if (!isStdio && urlInput) {
          urlInput.focus();
        } else {
          nameInput.focus();
        }
      }, 0);
    }

    const footer = $el('div', { className: 'mcp-modal-footer' });
    const cancelBtn = $el('button', { textContent: 'Cancel', className: 'btn-secondary' });
    cancelBtn.onclick = close;
    const connectBtn = $el('button', {
      textContent: isEditMode ? 'Save' : errorMsg ? 'Retry' : 'Connect',
      className: 'btn-primary',
    });
    connectBtn.onclick = function () { doConnect(getConnectPayload(), rawInput); };
    footer.appendChild(cancelBtn);
    footer.appendChild(connectBtn);

    modal.appendChild(hdr);
    modal.appendChild(body);
    modal.appendChild(footer);
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

    function refreshFields() {
      const isStdio = transportSel.value === 'stdio';
      urlRow.style.display = isStdio ? 'none' : '';
      cmdRow.style.display = isStdio ? '' : 'none';
      argsRow.style.display = isStdio ? '' : 'none';
    }
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
        auth_type: 'none', auth_value: '',
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
      command: result.command || '',
      args: result.args || [],
      env: result.env || {},
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
    clear(modal);
    modal.appendChild($el('div', { class: 'mcp-modal-header' }, [
      $el('span', { text: 'Connecting...' }),
    ]));
    const lines = $el('div', { class: 'mcp-status-panel' });
    const target = payload.transport === 'stdio'
      ? (payload.command + ' ' + (payload.args || []).join(' ')).trim()
      : payload.url;
    lines.appendChild($el('div', { class: 'mcp-status-line', text: 'Starting ' + target + '...' }));
    modal.appendChild($el('div', { class: 'mcp-modal-body' }, [lines]));
  }

  function renderSuccess(data) {
    clear(modal);
    const count = data.tool_count || 0;
    const serverName = data.name || 'server';
    modal.appendChild($el('div', { class: 'mcp-modal-body' }, [
      $el('div', { class: 'mcp-status-panel' }, [
        $el('div', { class: 'mcp-status-line mcp-status-ok', text: 'Connected to ' + serverName }),
        $el('div', { class: 'mcp-status-line mcp-status-ok', text: 'Found ' + count + ' tool' + (count !== 1 ? 's' : '') }),
      ]),
    ]));
    if (state && state.opts && typeof state.opts.onSuccess === 'function') {
      try {
        state.opts.onSuccess(data);
      } catch (e) {
        console.error('[mcp-modal] onSuccess threw:', e);
      }
    }
    setTimeout(function () {
      close();
      showSuccessToast('MCP server "' + serverName + '" added with ' + count + ' tool' + (count !== 1 ? 's' : ''));
    }, 700);
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
        text: '←',
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

    // Build a NormalizeResult-shaped object from the saved connection record
    var prefill = {
      ok: true,
      transport: conn.transport || 'http',
      name: conn.name || '',
      url: conn.url || '',
      auth_type: conn.auth_type || 'none',
      auth_value: '',          // never pre-fill secrets
      headers: conn.extra_headers || {},
      command: conn.command || '',
      args: conn.args || [],
      env: conn.env || {},
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
