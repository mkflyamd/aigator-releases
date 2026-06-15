/* ⚠️  POST-MVP — DO NOT MODIFY FOR MVP WORK ⚠️
 *
 * This file is part of the agentic setup wizard (Phase 4) which is DEFERRED
 * until after MVP. The supported "Add MCP" path for MVP is the legacy modal
 * at web/static/mcp_add_modal.js. The wizard workflow has known gaps and is
 * intentionally not wired into the default Add flow.
 *
 * If you are an agent fixing an MCP add/edit bug, modify mcp_add_modal.js
 * (and its backend at web/routes/mcp_routes.py) — NOT this file or anything
 * under web/extensions/ or web/routes/extension_setup.py. Only touch the
 * wizard files if the user has explicitly asked for post-MVP wizard work.
 *
 * ─────────────────────────────────────────────────────────────────────
 * Agentic setup wizard — form-first with collapsible AI Assist.
 *
 * Left pane  = full editable form (primary). Has Test + Save buttons.
 * Right pane = AI Assist chat, collapsed to a 36px strip by default.
 *              Auto-expands when wizard opens via raw_input (e.g. "add Linear").
 *              User can click the strip to expand/collapse at any time.
 *
 * AI never speaks proactively — only responds when the user types.
 * OAuth "Sign in" button lives in the form when auth_type=oauth2.
 *
 * Security: all DOM construction uses createElement + textContent.
 *           innerHTML is NEVER used anywhere in this file.
 */
(function (global) {
  var TRANSIENT_RE = /(timeout|network|fetch failed|HTTP 5\d\d|ECONN|ETIMEDOUT|getaddrinfo)/i;

  var AUTH_LABELS = {
    'none':    'No auth',
    'bearer':  'Bearer token',
    'api_key': 'API key',
    'basic':   'Basic (email + token)',
    'oauth2':  'OAuth 2.0',
  };

  var TRANSPORT_LABELS = {
    'http':  'Remote HTTP',
    'stdio': 'Local stdio',
  };

  function el(tag, className) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    return n;
  }

  /* ── Entry point ─────────────────────────────────────────────────────── */
  function openExtensionSetupWizard(opts) {
    opts = opts || {};
    var body = {
      extension_type: opts.extension_type || 'mcp',
      raw_input: opts.raw_input || null,
    };
    var onSuccess = opts.onSuccess || null;
    fetch('/api/extensions/setup/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); })
      .then(function (init) { renderWizard(init, onSuccess); })
      .catch(function (err) { alert('Could not open wizard: ' + err.message); });
  }

  /* ── DOM construction ────────────────────────────────────────────────── */
  function renderWizard(init, onSuccess) {
    var root = el('div', 'ext-wizard');

    // Close button — circle at top-right corner, half outside
    var close = el('button', 'ext-close');
    close.title = 'Close';
    close.textContent = '×';
    root.appendChild(close);

    // ── Left pane: form ──────────────────────────────────────────────────
    var form = el('div', 'ext-pane ext-form');

    var header = el('div', 'ext-header');
    var title = el('div', 'ext-title');
    title.textContent = 'Add Extension';
    header.appendChild(title);
    form.appendChild(header);

    // ── Paste-and-detect section ─────────────────────────────────────────
    var detectSection = el('div', 'ext-detect');
    var detectHint = el('p', 'ext-detect-hint');
    detectHint.textContent = 'Paste a URL, JSON config, or command to auto-fill the form.';
    var detectRow = el('div', 'ext-detect-row');
    var detectInput = el('textarea', 'ext-detect-input');
    detectInput.rows = 2;
    detectInput.placeholder = 'https://mcp.example.com/mcp  or  npx @playwright/mcp@latest  or  {"type":"mcp",…}';
    var detectBtn = el('button', 'ext-detect-btn');
    detectBtn.type = 'button';
    detectBtn.textContent = 'Detect →';
    var detectStatus = el('span', 'ext-detect-status');
    detectRow.appendChild(detectInput);
    detectRow.appendChild(detectBtn);
    detectSection.appendChild(detectHint);
    detectSection.appendChild(detectRow);
    detectSection.appendChild(detectStatus);
    form.appendChild(detectSection);

    var fields = el('div', 'ext-fields');
    form.appendChild(fields);

    // Status pill (read-only indicator)
    var pillRow = el('div', 'ext-pill-row');
    var pill = el('div', 'ext-pill');
    pill.dataset.state = 'idle';
    pill.textContent = 'Ready';
    pillRow.appendChild(pill);
    form.appendChild(pillRow);

    // OAuth sign-in block (shown in form when auth_type=oauth2)
    var oauthBlock = el('div', 'ext-oauth-block');
    oauthBlock.hidden = true;
    var oauthBtn = el('button', 'ext-oauth-open');
    oauthBtn.textContent = 'Sign in with OAuth →';
    var oauthStatus = el('span', 'ext-oauth-status');
    oauthBlock.appendChild(oauthBtn);
    oauthBlock.appendChild(oauthStatus);
    form.appendChild(oauthBlock);

    // Instructions panel (from AI)
    var instructions = el('div', 'ext-instructions');
    instructions.hidden = true;
    form.appendChild(instructions);

    // Form actions: Test + Save
    var actions = el('div', 'ext-form-actions');
    var testBtn = el('button', 'ext-btn-test');
    testBtn.textContent = 'Test Connection';
    var saveBtn = el('button', 'ext-btn-save');
    saveBtn.textContent = 'Save →';
    saveBtn.disabled = true;
    actions.appendChild(testBtn);
    actions.appendChild(saveBtn);
    form.appendChild(actions);

    // ── Right pane: AI Assist (collapsed by default) ─────────────────────
    var chatPane = el('div', 'ext-pane ext-chat ext-chat--collapsed');

    var toggle = el('div', 'ext-assist-toggle');
    toggle.title = 'AI Assist';
    var toggleArrow = el('span', 'ext-assist-arrow');
    toggleArrow.textContent = '▸';
    var toggleLabel = el('span', 'ext-assist-label');
    toggleLabel.textContent = 'AI Assist';
    toggle.appendChild(toggleArrow);
    toggle.appendChild(toggleLabel);
    chatPane.appendChild(toggle);

    var chatInner = el('div', 'ext-chat-inner');
    chatPane.appendChild(chatInner);

    root.appendChild(form);
    root.appendChild(chatPane);

    var overlay = el('div', 'ext-overlay');
    overlay.appendChild(root);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) closeWizard(state);
    });
    document.body.appendChild(overlay);

    /* ── State ────────────────────────────────────────────────────────── */
    var state = {
      sessionId:     init.session_id,
      schema:        init.config_schema,
      draft:         Object.assign({}, init.initial_field_state),
      retried:       {},
      onSuccess:     onSuccess,
      aiOpen:        false,
      $root:         root,
      $fields:       fields,
      $pill:         pill,
      $oauthBlock:   oauthBlock,
      $oauthBtn:     oauthBtn,
      $oauthStatus:  oauthStatus,
      $instructions: instructions,
      $chat:         chatPane,
      $chatInner:    chatInner,
      $testBtn:      testBtn,
      $saveBtn:      saveBtn,
      $toggleArrow:  toggleArrow,
    };

    renderFields(state);
    _refreshActionBtns(state);

    /* ── ChatClient (always created; chat pane may be collapsed) ─────── */
    var chat = new global.ChatClient({
      container: chatInner,
      endpoint: '/api/chat',
      contextId: 'ext_setup_' + state.sessionId,
      scopedSkill: '_extension_setup',
      systemPromptSuffix: init.system_prompt + '\n\nSESSION_ID: ' + state.sessionId,
      onToolEvent: function (e) { handleEvent(state, e); },
    });
    chat.pollEvents(state.sessionId, 700);
    state.chat = chat;

    /* ── Toggle AI Assist pane ─────────────────────────────────────── */
    toggle.addEventListener('click', function () {
      _setAiOpen(state, !state.aiOpen);
    });

    /* ── Open wizard with raw_input → auto-expand AI Assist ──────────── */
    if (init.raw_input) {
      _setAiOpen(state, true);
      chat.send(init.raw_input);
    }
    // No greeting when no raw_input — form-first; user acts first

    /* ── Detect button ───────────────────────────────────────────────── */
    function _runDetect() {
      var raw = detectInput.value.trim();
      if (!raw) return;
      detectBtn.disabled = true;
      detectBtn.textContent = 'Detecting…';
      detectStatus.textContent = '';
      detectStatus.className = 'ext-detect-status';
      fetch('/api/extensions/setup/normalize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ extension_type: 'mcp', raw_input: raw }),
      }).then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok && data.fields) {
            // Merge detected fields into local draft
            Object.keys(data.fields).forEach(function (k) {
              if (!k.startsWith('_')) state.draft[k] = data.fields[k];
            });
            // Sync detected fields to backend session so test/commit use them
            fetch('/api/extensions/setup/draft/' + encodeURIComponent(state.sessionId), {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ fields: data.fields }),
            }).catch(function () {});
            renderFields(state);
            _refreshActionBtns(state);
            detectStatus.textContent = 'Detected — review the fields below.';
            detectStatus.className = 'ext-detect-status ext-detect-ok';
          } else {
            detectStatus.textContent = 'Could not detect — fill in the fields manually.';
            detectStatus.className = 'ext-detect-status ext-detect-err';
          }
        })
        .catch(function () {
          detectStatus.textContent = 'Network error — try again.';
          detectStatus.className = 'ext-detect-status ext-detect-err';
        })
        .finally(function () {
          detectBtn.disabled = false;
          detectBtn.textContent = 'Detect →';
        });
    }

    detectBtn.addEventListener('click', _runDetect);
    detectInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _runDetect(); }
    });

    /* ── Button handlers ─────────────────────────────────────────────── */
    close.addEventListener('click', function () { closeWizard(state); });

    testBtn.addEventListener('click', function () {
      testBtn.disabled = true;
      testBtn.textContent = 'Testing…';
      fetch('/api/extensions/setup/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: state.sessionId }),
      }).then(function (r) { return r.json(); })
        .catch(function () {
          setPill(state, 'amber', 'Test failed');
        })
        .finally(function () {
          testBtn.disabled = false;
          testBtn.textContent = 'Test Connection';
        });
    });

    saveBtn.addEventListener('click', function () { commitWizard(state); });
  }

  /* ── Toggle AI assist open/closed ───────────────────────────────────── */
  function _setAiOpen(state, open) {
    state.aiOpen = open;
    if (open) {
      state.$chat.classList.remove('ext-chat--collapsed');
      state.$chat.classList.add('ext-chat--open');
      state.$toggleArrow.textContent = '◂';
    } else {
      state.$chat.classList.remove('ext-chat--open');
      state.$chat.classList.add('ext-chat--collapsed');
      state.$toggleArrow.textContent = '▸';
    }
  }

  /* ── Refresh Test/Save button states ────────────────────────────────── */
  function _refreshActionBtns(state) {
    var hasEndpoint = !!(
      (state.draft.url     && state.draft.url.trim())     ||
      (state.draft.command && state.draft.command.trim())
    );
    state.$saveBtn.disabled = !hasEndpoint;
    state.$testBtn.disabled = !hasEndpoint;

    // Show OAuth block in form when auth_type=oauth2
    var isOauth = state.draft.auth_type === 'oauth2';
    state.$oauthBlock.hidden = !isOauth;
    if (!isOauth) {
      state.$oauthStatus.textContent = '';
    }
  }

  /* ── Field rendering ─────────────────────────────────────────────────── */
  function renderFields(state) {
    while (state.$fields.firstChild) state.$fields.removeChild(state.$fields.firstChild);
    state.schema.fields.forEach(function (f) {
      if (!isFieldVisible(f, state.draft)) return;

      // auth_type=basic expands into Email + Token inputs
      if (f.path === 'auth_value' && state.draft.auth_type === 'basic') {
        _renderBasicAuthFields(state, f);
        return;
      }

      // auth_type=oauth2: OAuth handled by oauthBlock in the form; skip auth_value
      if (f.path === 'auth_value' && state.draft.auth_type === 'oauth2') {
        return;
      }

      var wrap = el('div', 'ext-field');
      wrap.dataset.path = f.path;
      var label = el('label');
      label.textContent = f.label;
      wrap.appendChild(label);

      if (f.type === 'select') {
        var labelMap = f.path === 'auth_type' ? AUTH_LABELS
                     : f.path === 'transport' ? TRANSPORT_LABELS
                     : null;
        var sel = el('select', 'ext-input');
        (f.options || []).forEach(function (o) {
          var opt = el('option');
          opt.value = o;
          opt.textContent = (labelMap && labelMap[o]) ? labelMap[o] : o;
          if (String(state.draft[f.path]) === String(o)) opt.selected = true;
          sel.appendChild(opt);
        });
        sel.addEventListener('change', function () { onFieldEdit(state, f, sel.value); });
        wrap.appendChild(sel);

      } else if (f.type === 'password') {
        var inp = el('input', 'ext-input');
        inp.type = 'password';
        inp.value = state.draft[f.path] != null ? String(state.draft[f.path]) : '';
        inp.addEventListener('input',  function () { onFieldEdit(state, f, inp.value); });
        inp.addEventListener('change', function () { onFieldEdit(state, f, inp.value); });
        wrap.appendChild(inp);

      } else if (f.type === 'kv') {
        wrap.appendChild(_buildKvWidget(state, f));

      } else if (f.type === 'list') {
        var listInp = el('input', 'ext-input');
        listInp.type = 'text';
        listInp.placeholder = 'space-separated args…';
        var listVal = state.draft[f.path];
        listInp.value = Array.isArray(listVal) ? listVal.join(' ')
                      : listVal != null ? String(listVal) : '';
        listInp.addEventListener('input', function () {
          var arr = listInp.value.trim() ? listInp.value.trim().split(/\s+/) : [];
          onFieldEdit(state, f, arr);
        });
        wrap.appendChild(listInp);

      } else {
        var tinp = el('input', 'ext-input');
        tinp.type = 'text';
        tinp.value = state.draft[f.path] != null ? String(state.draft[f.path]) : '';
        tinp.addEventListener('input',  function () { onFieldEdit(state, f, tinp.value); });
        tinp.addEventListener('change', function () { onFieldEdit(state, f, tinp.value); });
        wrap.appendChild(tinp);
      }

      state.$fields.appendChild(wrap);
    });
  }

  /* ── Basic auth: Email + Token inputs ────────────────────────────────── */
  function _renderBasicAuthFields(state, f) {
    var existing = state.draft[f.path] || '';
    var colonIdx = existing.indexOf(':');
    var emailVal = colonIdx >= 0 ? existing.slice(0, colonIdx) : existing;
    var tokenVal = colonIdx >= 0 ? existing.slice(colonIdx + 1) : '';

    function _rebuild() {
      state.draft[f.path] = emailInp.value + ':' + tokenInp.value;
      _refreshActionBtns(state);
    }

    var emailWrap = el('div', 'ext-field');
    emailWrap.dataset.path = f.path + '__email';
    var emailLabel = el('label');
    emailLabel.textContent = 'Email';
    var emailInp = el('input', 'ext-input');
    emailInp.type = 'text';
    emailInp.placeholder = 'you@company.com';
    emailInp.value = emailVal;
    emailWrap.appendChild(emailLabel);
    emailWrap.appendChild(emailInp);
    state.$fields.appendChild(emailWrap);

    var tokenWrap = el('div', 'ext-field');
    tokenWrap.dataset.path = f.path;
    var tokenLabel = el('label');
    tokenLabel.textContent = 'API Token';
    var tokenInp = el('input', 'ext-input');
    tokenInp.type = 'password';
    tokenInp.placeholder = 'Paste your API token…';
    tokenInp.value = tokenVal;
    tokenWrap.appendChild(tokenLabel);
    tokenWrap.appendChild(tokenInp);
    state.$fields.appendChild(tokenWrap);

    emailInp.addEventListener('input',  _rebuild);
    tokenInp.addEventListener('input',  _rebuild);
    emailInp.addEventListener('change', _rebuild);
    tokenInp.addEventListener('change', _rebuild);
  }

  /* ── Key-value widget for headers ────────────────────────────────────── */
  function _buildKvWidget(state, f) {
    var container = el('div', 'ext-kv');
    var currentVal = state.draft[f.path];
    var pairs = [];
    if (currentVal && typeof currentVal === 'object' && !Array.isArray(currentVal)) {
      Object.keys(currentVal).forEach(function (k) { pairs.push({ k: k, v: String(currentVal[k]) }); });
    }
    if (pairs.length === 0) pairs.push({ k: '', v: '' });

    var rows = [];
    var rowsDiv = el('div', 'ext-kv-rows');

    function _syncDraft() {
      var obj = {};
      rows.forEach(function (r) {
        if (r.keyInp.value.trim()) obj[r.keyInp.value.trim()] = r.valInp.value;
      });
      state.draft[f.path] = Object.keys(obj).length ? obj : null;
      _refreshActionBtns(state);
    }

    function _addRow(k, v) {
      var row = el('div', 'ext-kv-row');
      var keyInp = el('input', 'ext-kv-key');
      keyInp.type = 'text';
      keyInp.placeholder = 'Header name';
      keyInp.value = k || '';
      var valInp = el('input', 'ext-kv-val');
      valInp.type = 'text';
      valInp.placeholder = 'Value';
      valInp.value = v || '';
      var rmBtn = el('button', 'ext-kv-rm');
      rmBtn.type = 'button';
      rmBtn.textContent = '×';
      var rowObj = { keyInp: keyInp, valInp: valInp, el: row };
      rows.push(rowObj);
      keyInp.addEventListener('input', _syncDraft);
      valInp.addEventListener('input', _syncDraft);
      rmBtn.addEventListener('click', function () {
        rows.splice(rows.indexOf(rowObj), 1);
        rowsDiv.removeChild(row);
        if (rows.length === 0) _addRow('', '');
        _syncDraft();
      });
      row.appendChild(keyInp);
      row.appendChild(valInp);
      row.appendChild(rmBtn);
      rowsDiv.appendChild(row);
    }

    pairs.forEach(function (p) { _addRow(p.k, p.v); });

    var addBtn = el('button', 'ext-kv-add');
    addBtn.type = 'button';
    addBtn.textContent = '+ Add header';
    addBtn.addEventListener('click', function () { _addRow('', ''); });

    container.appendChild(rowsDiv);
    container.appendChild(addBtn);
    return container;
  }

  /* ── Visibility rules ────────────────────────────────────────────────── */
  function isFieldVisible(field, draft) {
    if (!field.visible_if) return true;
    var inMatch = field.visible_if.match(/^(\w+)\s+in\s+\(([^)]+)\)$/);
    if (inMatch) {
      var vals = inMatch[2].split(',').map(function (s) { return s.trim(); });
      var cur = draft[inMatch[1]];
      return vals.indexOf(cur == null ? '' : String(cur)) !== -1;
    }
    var eqMatch = field.visible_if.match(/^(\w+)=(.+)$/);
    if (eqMatch) {
      var cur2 = draft[eqMatch[1]];
      return (cur2 == null ? '' : String(cur2)) === eqMatch[2].trim();
    }
    return true;
  }

  /* ── Field edit handler (no debounce, no AI prompt) ─────────────────── */
  function onFieldEdit(state, field, value) {
    state.draft[field.path] = value;
    if (field.path === 'transport' || field.path === 'auth_type') renderFields(state);
    _refreshActionBtns(state);
  }

  /* ── OAuth wiring: in form (AI pane closed) ──────────────────────────── */
  function _wireOAuthInForm(state, authorizeUrl, oauthState) {
    state.$oauthBlock.hidden = false;
    state.$oauthStatus.textContent = '';

    // Replace button to clear any previous listener
    var newBtn = el('button', 'ext-oauth-open');
    newBtn.textContent = 'Sign in with OAuth →';
    state.$oauthBlock.replaceChild(newBtn, state.$oauthBtn);
    state.$oauthBtn = newBtn;

    newBtn.addEventListener('click', function () {
      window.open(authorizeUrl, 'oauth', 'width=500,height=700');
      newBtn.disabled = true;
      state.$oauthStatus.textContent = 'Waiting for sign-in…';
      if (oauthState) _pollOAuth(state, oauthState, newBtn, state.$oauthStatus);
    });
  }

  /* ── OAuth wiring: in chat (AI pane open) ────────────────────────────── */
  function showOAuthButton(state, authorizeUrl, oauthState) {
    var wrap = el('div', 'ext-oauth-prompt');
    var btn = el('button', 'ext-oauth-open');
    btn.textContent = 'Sign in →';
    var status = el('span', 'ext-oauth-status');
    wrap.appendChild(btn);
    wrap.appendChild(status);
    state.chat.appendElement(wrap);

    btn.addEventListener('click', function () {
      window.open(authorizeUrl, 'oauth', 'width=500,height=700');
      btn.disabled = true;
      status.textContent = 'Waiting for sign-in…';
      if (oauthState) _pollOAuth(state, oauthState, btn, status);
    });
  }

  function _pollOAuth(state, oauthState, btn, statusEl) {
    var attempts = 0;
    var timer = setInterval(function () {
      attempts++;
      if (attempts > 120) {
        clearInterval(timer);
        statusEl.textContent = 'Timed out — click Sign in to retry.';
        btn.disabled = false;
        return;
      }
      fetch('/api/config/mcp/oauth/poll?state=' + encodeURIComponent(oauthState))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.status === 'pending') return;
          clearInterval(timer);
          if (data.ok) {
            statusEl.textContent = 'Signed in ✓ — saving…';
            btn.style.display = 'none';
            commitWizard(state);
          } else {
            statusEl.textContent = 'Sign-in failed: ' + (data.error || 'unknown error');
            btn.disabled = false;
            btn.textContent = 'Try again →';
          }
        })
        .catch(function () { /* network blip */ });
    }, 1000);
  }

  /* ── Event handler (from AI tool calls via pollEvents) ───────────────── */
  function handleEvent(state, e) {
    switch (e.type) {
      case 'field_update':
        state.draft[e.field_path] = e.value;
        renderFields(state);
        _refreshActionBtns(state);
        break;
      case 'highlight':
        pulseField(state, e.field_path);
        break;
      case 'instructions':
        showInstructions(state, e.title, e.steps);
        break;
      case 'test_result':
        handleTestResult(state, e);
        break;
      case 'oauth_started':
        if (state.aiOpen) {
          showOAuthButton(state, e.authorize_url, e.state);
        } else {
          _wireOAuthInForm(state, e.authorize_url, e.state);
        }
        break;
      case 'ready_to_commit':
        commitWizard(state);
        break;
    }
  }

  function pulseField(state, path) {
    var cssPath = (window.CSS && CSS.escape) ? CSS.escape(path) : String(path).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
    var el2 = state.$fields.querySelector('[data-path="' + cssPath + '"]');
    if (!el2) return;
    el2.classList.remove('ext-pulse');
    void el2.offsetWidth;
    el2.classList.add('ext-pulse');
  }

  function handleTestResult(state, e) {
    if (e.ok) {
      setPill(state, 'success', 'Connected · ' + e.tool_count + ' tools');
      state.$fields.classList.add('ext-settled');
      return;
    }
    var detail = e.detail || 'Connection failed';
    if (TRANSIENT_RE.test(detail) && !state.retried[detail]) {
      state.retried[detail] = true;
      setPill(state, 'retry', 'Retrying…');
      setTimeout(function () {
        fetch('/api/extensions/setup/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: state.sessionId }),
        }).catch(function () {});
      }, 600);
      return;
    }
    setPill(state, 'amber', 'Needs attention');
    markFieldAmber(state, guessFieldFromError(detail));
    appendDetailsDisclosure(state, e.raw || {});
  }

  function setPill(state, kind, text) {
    state.$pill.dataset.state = kind;
    state.$pill.textContent = text;
  }

  function markFieldAmber(state, path) {
    Array.prototype.forEach.call(
      state.$fields.querySelectorAll('[data-path]'),
      function (el2) { el2.classList.toggle('ext-amber', el2.dataset.path === path); }
    );
  }

  function guessFieldFromError(detail) {
    var d = (detail || '').toLowerCase();
    if (d.indexOf('token') >= 0 || d.indexOf('auth') >= 0 || d.indexOf('401') >= 0) return 'auth_value';
    if (d.indexOf('url') >= 0 || d.indexOf('host') >= 0 || d.indexOf('404') >= 0) return 'url';
    return null;
  }

  function appendDetailsDisclosure(state, raw) {
    var existing = state.$root.querySelector('.ext-details');
    if (existing) existing.parentNode.removeChild(existing);
    var det = el('details', 'ext-details');
    var sum = el('summary');
    sum.textContent = 'Show details';
    var pre = el('pre');
    pre.textContent = JSON.stringify(raw, null, 2);
    det.appendChild(sum);
    det.appendChild(pre);
    state.$pill.parentNode.insertBefore(det, state.$pill.nextSibling);
  }

  function showInstructions(state, title, steps) {
    while (state.$instructions.firstChild) state.$instructions.removeChild(state.$instructions.firstChild);
    state.$instructions.hidden = false;
    var t = el('div', 'ext-instr-title');
    t.textContent = title;
    var ol = el('ol');
    (steps || []).forEach(function (s) {
      var li = el('li');
      li.textContent = s;
      ol.appendChild(li);
    });
    state.$instructions.appendChild(t);
    state.$instructions.appendChild(ol);
  }

  /* ── Commit failure — open AI pane + show inline fix card ────────────── */
  function showFixAndSave(state, message) {
    if (!state.aiOpen) _setAiOpen(state, true);
    var wrap = el('div', 'ext-fix-save');
    var msg = el('p', 'ext-fix-save-msg');
    msg.textContent = message;
    var btn = el('button', 'ext-fix-save-btn');
    btn.textContent = 'Fix & Save →';
    btn.addEventListener('click', function () {
      btn.disabled = true;
      btn.textContent = 'Saving…';
      commitWizard(state);
    });
    wrap.appendChild(msg);
    wrap.appendChild(btn);
    state.chat.appendElement(wrap);
  }

  /* ── Commit / close ──────────────────────────────────────────────────── */
  function commitWizard(state) {
    fetch('/api/extensions/setup/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId }),
    }).then(function (r) {
      if (r.ok) {
        r.json().then(function (data) {
          closeWizard(state);
          if (typeof state.onSuccess === 'function') state.onSuccess(data);
        });
        return;
      }
      r.json().then(function (j) {
        var detail = j && j.detail;
        var msg;
        if (r.status === 422 && detail && detail.auth_required) {
          msg = (detail.message || 'Authentication required.') +
            ' Add the required credentials in the form, then try again.';
        } else {
          msg = 'Save failed: ' + ((detail && (detail.message || (typeof detail === 'string' ? detail : null))) || 'unknown error');
        }
        showFixAndSave(state, msg);
      }).catch(function () {
        showFixAndSave(state, 'Save failed. Check the form and try again.');
      });
    }).catch(function (err) {
      showFixAndSave(state, 'Save failed: ' + err.message);
    });
  }

  function closeWizard(state) {
    if (state.chat) state.chat.stop();
    fetch('/api/extensions/setup/' + encodeURIComponent(state.sessionId), { method: 'DELETE' });
    var overlay = state.$root.parentNode;
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
  }

  global.openExtensionSetupWizard = openExtensionSetupWizard;
})(window);
