/* MCP Add Modal — Universal Connect flow (Task 6).
   Two-step: (1) paste textarea → Analyze → (2) review card → Connect.
   Built with plain DOM. No framework. No innerHTML with user data. */
(function () {
  'use strict';

  let root, overlay, modal, state, prevFocus, keyHandler;

  // Connections currently mid-flow through a "Complete setup" POST
  // .../complete-secrets request, keyed by connection id — mirrors
  // marketplace-pane.js's _pendingVerifiedInstalls / _tryAcquireInstallLock
  // pattern (fix #5, 2026-08-07 milestone adversarial review). The previous
  // `busy` guard was a per-invocation closure: closing and reopening
  // "Complete setup" for the SAME still-in-flight connection created a fresh
  // closure with busy=false, letting a second concurrent request race the
  // first for that id. Keying by connection id (rather than by modal
  // instance) closes that gap.
  const _pendingSecretCompletions = new Set();

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

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  // ── Name uniqueness (soft warning) ────────────────────────────────────────────
  // Two connections with names that slug to the same value will produce the
  // same OAuth provider id and collide. Match backend _slug() in dcr.py.
  function _slugifyName(s) {
    return String(s || '')
      .toLowerCase()
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
    const warn = $el('div', {
      className: 'mcp-name-warning',
      style: 'color:#b85c00;font-size:12px;margin-top:4px;display:none',
    });
    let conns = [];
    _loadExistingConnections().then(function (c) {
      conns = c;
      check();
    });
    function check() {
      const val = nameInput.value.trim();
      const editingId = (typeof getEditingId === 'function' ? getEditingId() : '') || '';
      if (!val) {
        warn.style.display = 'none';
        return;
      }
      const slug = _slugifyName(val);
      const clash = conns.find(function (c) {
        if (c.id === editingId) return false;
        return _slugifyName(c.name || '') === slug;
      });
      if (clash) {
        warn.textContent =
          '⚠ Another connection is named “' +
          (clash.name || '') +
          '” — pick a distinct name so credentials don’t collide.';
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
          var isSecret =
            /passw|secret|token|key|pwd|credential/i.test(lk) ||
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
      return {
        container: null,
        getValues: function () {
          return {};
        },
      };
    }
    var container = $el('div', { className: 'mcp-placeholder-section' });
    container.appendChild($el('p', { className: 'mcp-placeholder-hint', textContent: hint }));
    if (_hasBasicAuthTemplate(sourceObj)) {
      container.appendChild(
        $el('p', {
          className: 'mcp-placeholder-subhint',
          textContent:
            'Tip: enter email and API token separately — we’ll join and base64-encode them for you.',
        }),
      );
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
        Object.keys(inputs).forEach(function (k) {
          out[k] = inputs[k].value.trim();
        });
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
    var menu = $el('div', {
      className: 'mcp-dropdown-menu mcp-dropdown-menu-portal',
      role: 'listbox',
    });
    menu.style.display = 'none';
    document.body.appendChild(menu);

    function setLabel(val) {
      var opt = options.find(function (o) {
        return o.value === val;
      });
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
      menu.style.top = rect.bottom + 4 + 'px';
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
    document.addEventListener(
      'click',
      function (e) {
        if (open && !menu.contains(e.target) && e.target !== trigger) closeMenu();
      },
      true,
    );

    setLabel(current);
    wrap.appendChild(trigger);

    return {
      el: wrap,
      getValue: function () {
        return current;
      },
      setValue: function (val) {
        current = val;
        setLabel(val);
      },
      destroy: function () {
        if (menu.parentNode) menu.parentNode.removeChild(menu);
      },
    };
  }

  function focusableIn(node) {
    return Array.prototype.slice.call(
      node.querySelectorAll(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    );
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
    _clearConnectTimers();
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
      try {
        prevFocus.focus();
      } catch (e) {
        /* ignore */
      }
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
      onclick: null,
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
      if (e.key === 'Escape') {
        e.stopPropagation();
        close();
        return;
      }
      trapTab(e);
    };
    document.addEventListener('keydown', keyHandler, true);

    if (!opts || !opts.skipStep1) renderStep1('');
  }

  // ── Step 1: Paste screen ──────────────────────────────────────────────────────

  function renderStep1(prefill) {
    clear(modal);
    prefill = prefill || '';

    const hdr = $el('div', { className: 'mcp-modal-header' });
    hdr.appendChild(
      $el('span', { textContent: 'Connect an MCP server', className: 'mcp-modal-title' }),
    );
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×', title: 'Close' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body' });
    body.appendChild(
      $el('p', {
        className: 'mcp-modal-hint',
        textContent:
          "Tell us about the MCP you want to connect. Paste a URL, JSON config, or any text from a README — we'll figure out the rest.",
      }),
    );

    const ta = $el('textarea', {
      className: 'mcp-json-textarea',
      placeholder:
        'Paste a GitHub URL, server URL, JSON config, or command\ne.g. npx @playwright/mcp@latest',
    });
    ta.value = prefill;
    body.appendChild(ta);

    const footer = $el('div', { className: 'mcp-modal-footer' });
    const cancelBtn = $el('button', { textContent: 'Cancel', className: 'btn-secondary' });
    cancelBtn.onclick = close;
    const analyzeBtn = $el('button', { textContent: 'Analyze →', className: 'btn-primary' });
    analyzeBtn.onclick = function () {
      doAnalyze(ta.value);
    };
    footer.appendChild(cancelBtn);
    footer.appendChild(analyzeBtn);

    modal.appendChild(hdr);
    modal.appendChild(body);
    modal.appendChild(footer);
    ta.focus();
  }

  // ── Google Workspace wizard ──────────────────────────────────────────────────
  // Collects one OAuth client_id/secret from the user, then drives the existing
  // BYOC OAuth flow (/api/config/mcp/oauth/start → popup → poll → /api/config/mcp)
  // for each server in the preset (Gmail + Google Calendar). The same client_id
  // and secret are reused for both — Google allows multiple redirect URIs per
  // client, and both MCP servers share the Google auth domain.

  async function renderGoogleWizard() {
    clear(modal);
    const hdr = $el('div', { className: 'mcp-modal-header' });
    hdr.appendChild(
      $el('span', { textContent: 'Connect Google Workspace', className: 'mcp-modal-title' }),
    );
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×', title: 'Close' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body' });
    body.appendChild($el('div', { className: 'mcp-spinner', style: 'margin:24px auto' }));
    body.appendChild(
      $el('p', {
        textContent: 'Loading preset…',
        className: 'mcp-modal-hint',
        style: 'text-align:center',
      }),
    );
    modal.appendChild(hdr);
    modal.appendChild(body);

    let preset;
    try {
      const resp = await fetch('/api/config/mcp/presets/google');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      preset = await resp.json();
    } catch (e) {
      clear(modal);
      modal.appendChild(hdr);
      const errBody = $el('div', { className: 'mcp-modal-body' });
      errBody.appendChild(
        $el('p', {
          textContent:
            'Could not load the Google preset: ' +
            e.message +
            '. You can still connect manually — paste the Gmail or Calendar MCP URL below.',
          className: 'mcp-modal-hint',
        }),
      );
      const back = $el('button', {
        textContent: '← Back',
        className: 'btn-secondary',
        onclick: function () {
          renderStep1('');
        },
      });
      errBody.appendChild(back);
      modal.appendChild(errBody);
      return;
    }

    clear(modal);
    modal.appendChild(hdr);
    const wbody = $el('div', { className: 'mcp-modal-body' });

    // Preview notice
    if (preset.preview) {
      const note = $el('p', {
        textContent: '⚠ ' + preset.preview_note,
        style:
          'font-size:.75rem;color:var(--text-secondary,#64748b);padding:8px 10px;background:var(--bg-tertiary,#f1f5f9);border-radius:6px;margin:0 0 14px',
      });
      wbody.appendChild(note);
    }

    // ── Shared client_id path: zero console steps ──────────────────────────
    // When a shared Google OAuth client_id is configured server-side, the user
    // never touches the Google Cloud Console. They just click Connect and sign
    // in with Google. This is the seamless experience — the BYOC steps below
    // are skipped entirely.
    const sharedClientId = preset.shared_client_id || '';
    const sharedClientSecret = preset.shared_client_secret || '';
    if (sharedClientId) {
      wbody.appendChild(
        $el('p', {
          textContent:
            'Connect your Google Workspace (Gmail, Calendar, and more). Click Connect — no setup required.',
          style: 'font-size:.85rem;margin:0 0 14px',
        }),
      );

      // What you'll get
      const list = $el('ul', {
        style: 'margin:0 0 14px;padding-left:20px;font-size:.82rem;line-height:1.6',
      });
      preset.servers.forEach(function (s) {
        const li = $el('li');
        li.appendChild(document.createTextNode(s.name));
        if (s.scopes_note) {
          li.appendChild(
            $el('div', {
              textContent: s.scopes_note,
              style: 'font-size:.72rem;color:var(--text-secondary,#64748b);margin-top:2px',
            }),
          );
        }
        list.appendChild(li);
      });
      wbody.appendChild(list);

      // Status area (filled in as the server connects)
      const status = $el('div', { style: 'margin-top:10px' });
      wbody.appendChild(status);

      modal.appendChild(wbody);

      const footer = $el('div', { className: 'mcp-modal-footer' });
      const backBtn = $el('button', {
        textContent: '← Back',
        className: 'btn-secondary',
        onclick: function () {
          renderStep1('');
        },
      });
      const connectBtn = $el('button', { textContent: 'Connect →', className: 'btn-primary' });
      footer.appendChild(backBtn);
      footer.appendChild(connectBtn);
      modal.appendChild(footer);

      connectBtn.onclick = function () {
        connectBtn.disabled = true;
        backBtn.disabled = true;
        _runPresetFlow(preset, status, connectBtn, backBtn);
      };
      return;
    }

    // ── BYOC path: user supplies their own client_id/secret ────────────────

    // What you'll get
    wbody.appendChild(
      $el('p', {
        textContent: 'This connects two Google remote MCP servers with one OAuth client:',
        style: 'font-size:.85rem;margin:0 0 8px',
      }),
    );
    const list = $el('ul', {
      style: 'margin:0 0 14px;padding-left:20px;font-size:.82rem;line-height:1.6',
    });
    preset.servers.forEach(function (s) {
      const li = $el('li');
      li.appendChild(document.createTextNode(s.name + ' — '));
      const scopes = $el('code', {
        textContent: s.scopes.join(' '),
        style: 'font-size:.72rem;word-break:break-all',
      });
      li.appendChild(scopes);
      if (s.scopes_note) {
        li.appendChild(
          $el('div', {
            textContent: s.scopes_note,
            style: 'font-size:.72rem;color:var(--text-secondary,#64748b);margin-top:2px',
          }),
        );
      }
      list.appendChild(li);
    });
    wbody.appendChild(list);

    // Step 1: enable APIs + create OAuth client in Google Cloud Console
    wbody.appendChild(
      $el('p', {
        textContent: 'Step 1. Enable the required Google APIs',
        style: 'font-size:.85rem;font-weight:600;margin:14px 0 6px',
      }),
    );
    wbody.appendChild(
      $el('p', {
        textContent:
          'Each MCP server needs TWO APIs enabled — the REST API and a separate "*mcp*" API. Skipping the MCP API is the #1 cause of 403 errors. Click each link and pick your project:',
        style: 'font-size:.8rem;margin:0 0 8px;color:var(--text-secondary,#64748b)',
      }),
    );
    if (preset.apis) {
      const apisList = $el('div', { style: 'margin:0 0 10px' });
      Object.keys(preset.apis).forEach(function (serviceName) {
        apisList.appendChild(
          $el('div', {
            textContent: serviceName + ':',
            style: 'font-size:.78rem;font-weight:600;margin-top:6px',
          }),
        );
        preset.apis[serviceName].forEach(function (api) {
          const row = $el('div', { style: 'margin:2px 0 2px 12px;font-size:.78rem' });
          row.appendChild(document.createTextNode('• '));
          const link = $el('a', {
            href: api.url,
            target: '_blank',
            textContent: api.name,
            style: 'color:var(--accent,#16a34a)',
          });
          row.appendChild(link);
          apisList.appendChild(row);
        });
      });
      wbody.appendChild(apisList);
    }

    wbody.appendChild(
      $el('p', {
        textContent: 'Step 2. Add scopes to the OAuth consent screen',
        style: 'font-size:.85rem;font-weight:600;margin:14px 0 6px',
      }),
    );
    wbody.appendChild(
      $el('p', {
        textContent:
          'CRITICAL: Go to Google Auth Platform → Data Access. The scopes for each enabled API appear automatically as checkboxes — tick the ones below. If you get a "legacy API" error when typing a scope manually, it means the parent REST API isn\'t enabled (go back to Step 1). Do NOT use the "Manually add scopes" text field if the picker is available.',
        style: 'font-size:.8rem;margin:0 0 8px;color:var(--danger,#dc2626)',
      }),
    );
    if (preset.consent_scopes) {
      const scopesBox = $el('div', {
        style:
          'font-size:.72rem;padding:8px 10px;background:var(--bg-tertiary,#f1f5f9);border-radius:6px;margin:0 0 8px',
      });
      Object.keys(preset.consent_scopes).forEach(function (serviceName) {
        scopesBox.appendChild(
          $el('div', {
            textContent: serviceName + ' — tick these in the picker:',
            style: 'font-weight:600;margin-top:4px',
          }),
        );
        preset.consent_scopes[serviceName].forEach(function (sc) {
          scopesBox.appendChild(
            $el('div', {
              textContent: '☐ ' + sc,
              style: 'font-family:monospace;word-break:break-all;margin:1px 0 1px 8px',
            }),
          );
        });
      });
      wbody.appendChild(scopesBox);
    }
    if (preset.scopes_url) {
      const scopesLink = $el('a', {
        href: preset.scopes_url,
        target: '_blank',
        textContent: 'Open Google Auth Platform → Data Access →',
        style: 'font-size:.78rem;color:var(--accent,#16a34a)',
      });
      wbody.appendChild(scopesLink);
    }

    wbody.appendChild(
      $el('p', {
        textContent: 'Step 3. Create a Web-application OAuth client',
        style: 'font-size:.85rem;font-weight:600;margin:14px 0 6px',
      }),
    );
    wbody.appendChild(
      $el('p', {
        textContent:
          'In Google Auth Platform → Clients, create a Web-application client with this redirect URI:',
        style: 'font-size:.8rem;margin:0 0 6px;color:var(--text-secondary,#64748b)',
      }),
    );
    const redirectBox = $el('p', {
      style:
        'font-size:.72rem;padding:6px 8px;background:var(--bg-tertiary,#f1f5f9);border-radius:4px;margin:0 0 6px;user-select:all',
    });
    redirectBox.appendChild(document.createTextNode('📋 '));
    redirectBox.appendChild(
      $el('code', { textContent: preset.redirect_uri, style: 'font-size:.72rem' }),
    );
    wbody.appendChild(redirectBox);
    const consoleLink = $el('a', {
      href: preset.console_url,
      target: '_blank',
      textContent: 'Open Google Cloud Console → Clients →',
      style: 'font-size:.78rem;color:var(--accent,#16a34a)',
    });
    wbody.appendChild(consoleLink);

    // Step 4: paste client_id / client_secret
    wbody.appendChild(
      $el('p', {
        textContent: 'Step 4. Paste your OAuth client credentials',
        style: 'font-size:.85rem;font-weight:600;margin:18px 0 6px',
      }),
    );
    const cidLabel = $el('label', {
      textContent: 'Client ID',
      style: 'font-size:.78rem;font-weight:600;display:block;margin-bottom:3px',
    });
    wbody.appendChild(cidLabel);
    const cidInput = $el('input', {
      type: 'text',
      placeholder: 'e.g. 1234567890-abc.apps.googleusercontent.com',
      style:
        'width:100%;box-sizing:border-box;padding:6px 8px;border:1px solid var(--border,#e2e8f0);border-radius:4px;font-size:.8rem;margin-bottom:10px',
    });
    wbody.appendChild(cidInput);
    const csecLabel = $el('label', {
      textContent: 'Client Secret',
      style: 'font-size:.78rem;font-weight:600;display:block;margin-bottom:3px',
    });
    wbody.appendChild(csecLabel);
    const csecInput = $el('input', {
      type: 'password',
      placeholder: 'GOCSPX-…',
      style:
        'width:100%;box-sizing:border-box;padding:6px 8px;border:1px solid var(--border,#e2e8f0);border-radius:4px;font-size:.8rem;margin-bottom:14px',
    });
    wbody.appendChild(csecInput);

    // Status area (filled in as each server connects)
    const status = $el('div', { style: 'margin-top:10px' });
    wbody.appendChild(status);

    modal.appendChild(wbody);

    const footer = $el('div', { className: 'mcp-modal-footer' });
    const backBtn = $el('button', {
      textContent: '← Back',
      className: 'btn-secondary',
      onclick: function () {
        renderStep1('');
      },
    });
    const connectBtn = $el('button', { textContent: 'Connect →', className: 'btn-primary' });
    footer.appendChild(backBtn);
    footer.appendChild(connectBtn);
    modal.appendChild(footer);

    connectBtn.onclick = function () {
      const cid = cidInput.value.trim();
      const csec = csecInput.value.trim();
      if (!cid || !csec) {
        status.textContent = '';
        const warn = $el('p', {
          textContent: '✕ Client ID and Client Secret are both required.',
          style: 'font-size:.78rem;color:var(--danger,#dc2626);margin:6px 0 0',
        });
        status.appendChild(warn);
        return;
      }
      connectBtn.disabled = true;
      backBtn.disabled = true;
      _runGooglePresetFlow(preset, cid, csec, status, connectBtn, backBtn);
    };
  }

  // ── Preset flow (shared-credential path) ─────────────────────────────────────
  // Generic flow for presets with shared credentials configured server-side.
  // 1. Call /api/config/mcp/presets/resolve to inject env vars from shared config
  // 2. POST /api/config/mcp with the resolved payload (normal save flow)
  // 3. The server starts, list_tools succeeds, connection is saved
  // 4. OAuth happens on first tool call (the server opens a browser itself)
  //
  // This works for any preset that declares env_mapping — not just Google.
  async function _runPresetFlow(preset, statusEl, connectBtn, backBtn) {
    const onSuccessCb =
      state && state.opts && typeof state.opts.onSuccess === 'function'
        ? state.opts.onSuccess
        : null;

    const server = preset.servers[0];
    const statusLine = $el('div', {
      style:
        'margin:8px 0;padding:8px 10px;background:var(--bg-secondary,#f8f9fa);border-radius:6px;font-size:.82rem',
    });
    statusLine.appendChild(document.createTextNode(server.name + ' — '));
    const stateEl = $el('span', {
      textContent: 'resolving credentials…',
      style: 'color:var(--text-secondary,#64748b)',
    });
    statusLine.appendChild(stateEl);
    statusEl.appendChild(statusLine);

    try {
      // 1. Resolve env vars from shared config
      const resolveResp = await fetch('/api/config/mcp/presets/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transport: server.transport,
          command: server.command || '',
          args: server.args || [],
          url: server.url || '',
          name: server.name,
          env_mapping: server.env_mapping || {},
          env_defaults: server.env_defaults || {},
        }),
      });
      const resolved = await resolveResp.json();
      if (!resolveResp.ok) {
        throw new Error(resolved.detail || 'Credential resolution failed');
      }

      // 2. Save the connection (the backend starts the server, lists tools, saves)
      stateEl.textContent = 'connecting…';
      const saveResp = await fetch('/api/config/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(resolved),
      });
      const saveData = await saveResp.json();
      if (!saveResp.ok || !saveData.name) {
        throw new Error(saveData.detail || saveData.error || 'Connection failed');
      }

      stateEl.textContent = '✓ connected';
      stateEl.style.color = 'var(--success,#16a34a)';
      if (typeof window.registerMcpSkill === 'function') {
        try {
          window.registerMcpSkill(saveData.id, saveData.name);
        } catch (e) {}
      }

      connectBtn.textContent = 'Done';
      connectBtn.disabled = false;
      backBtn.disabled = false;
      connectBtn.onclick = function () {
        if (onSuccessCb) {
          try {
            onSuccessCb();
          } catch (e) {
            console.error('[preset] onSuccess threw:', e);
          }
        }
        close();
      };
    } catch (e) {
      stateEl.textContent = '✕ ' + e.message;
      stateEl.style.color = 'var(--danger,#dc2626)';
      connectBtn.textContent = 'Retry';
      connectBtn.disabled = false;
      backBtn.disabled = false;
      connectBtn.onclick = function () {
        connectBtn.disabled = true;
        backBtn.disabled = true;
        connectBtn.textContent = 'Connect →';
        // Clear status
        while (statusEl.firstChild) statusEl.removeChild(statusEl.firstChild);
        _runPresetFlow(preset, statusEl, connectBtn, backBtn);
      };
    }
  }

  // Drives the BYOC OAuth flow for each server in the preset.
  // For each server: (1) POST /oauth/start with BYOC creds → (2) popup →
  // (3) poll until done → (4) POST /api/config/mcp to create the connection.
  // Reuses the existing endpoints — no backend changes beyond the preset
  // definition. The same client_id/secret is used for every server.
  //
  // Popup-blocker note: in browser mode, window.open() must fire from a direct
  // user-gesture call stack. The first server's popup fires from the Connect
  // button click (the gesture). Subsequent servers require an explicit
  // "Continue →" click so each popup has its own gesture. In the Electron
  // shell, window.open() is routed to the system browser (Google blocks OAuth
  // in embedded webviews) and returns null — the poll detects completion via
  // the backend callback, not a popup object.
  async function _runGooglePresetFlow(
    preset,
    clientId,
    clientSecret,
    statusEl,
    connectBtn,
    backBtn,
    isShared,
  ) {
    const onSuccessCb =
      state && state.opts && typeof state.opts.onSuccess === 'function'
        ? state.opts.onSuccess
        : null;

    // Connect a stdio server (e.g. community Gmail MCP). Runs auth via the
    // backend's stdio-auth endpoint, waits for credentials, then saves.
    async function _connectStdio(server, statusLine) {
      const stateEl = statusLine.querySelector('span') || statusLine;
      try {
        stateEl.textContent = 'starting auth…';
        const startResp = await fetch('/api/config/mcp/stdio-auth/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ package: server.auth_package }),
        });
        const startData = await startResp.json();
        if (!startResp.ok) {
          throw new Error(startData.detail || 'Auth start failed');
        }
        if (!startData.url) {
          throw new Error('No auth URL returned');
        }

        stateEl.textContent = 'waiting for sign-in…';
        // window.open returns null in Electron shell mode (setWindowOpenHandler
        // opens the URL in the system browser and denies the popup). Don't use
        // popup.closed as a cancellation signal — just poll the backend.
        let popup = null;
        try {
          popup = window.open(
            startData.url,
            'gmail_auth',
            'width=560,height=720,menubar=no,toolbar=no',
          );
        } catch (e) {}

        const ok = await new Promise(function (resolve) {
          const poll = setInterval(function () {
            fetch('/api/config/mcp/stdio-auth/status')
              .then(function (r) {
                return r.json();
              })
              .then(function (s) {
                if (s.done) {
                  clearInterval(poll);
                  resolve(true);
                  return;
                }
                if (s.error) {
                  clearInterval(poll);
                  resolve(false);
                  return;
                }
                // Only use popup.closed as a signal in browser mode (popup is
                // a real window). In shell mode popup is null — the system
                // browser handles sign-in and we just keep polling.
                if (popup && popup.closed) {
                  clearInterval(poll);
                  setTimeout(function () {
                    fetch('/api/config/mcp/stdio-auth/status')
                      .then(function (r) {
                        return r.json();
                      })
                      .then(function (s2) {
                        resolve(s2.done);
                      })
                      .catch(function () {
                        resolve(false);
                      });
                  }, 2000);
                }
              })
              .catch(function () {});
          }, 1000);
          setTimeout(function () {
            clearInterval(poll);
            resolve(false);
          }, 120000);
        });
        if (!ok) {
          throw new Error('Sign-in did not complete.');
        }

        stateEl.textContent = 'saving connection…';
        const saveResp = await fetch('/api/config/mcp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            transport: 'stdio',
            name: server.name,
            command: server.command,
            args: server.args,
            auth_type: 'none',
          }),
        });
        const saveData = await saveResp.json();
        if (!saveResp.ok || !saveData.name) {
          throw new Error(saveData.detail || saveData.error || 'Save failed');
        }

        stateEl.textContent = '✓ connected';
        stateEl.style.color = 'var(--success,#16a34a)';
        if (typeof window.registerMcpSkill === 'function') {
          try {
            window.registerMcpSkill(saveData.id, saveData.name);
          } catch (e) {}
        }
        return true;
      } catch (e) {
        stateEl.textContent = '✕ ' + e.message;
        stateEl.style.color = 'var(--danger,#dc2626)';
        return false;
      }
    }

    // Connect an http MCP server via the existing BYOC OAuth flow.
    async function _connectHttp(server, statusLine) {
      const stateEl = statusLine.querySelector('span') || statusLine;
      try {
        let popup = null;
        try {
          popup = window.open(
            'about:blank',
            'mcp_oauth_' + encodeURIComponent(server.name),
            'width=560,height=720,menubar=no,toolbar=no',
          );
        } catch (e) {}

        stateEl.textContent = 'requesting authorization…';
        const startResp = await fetch('/api/config/mcp/oauth/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url: server.url,
            label: server.name,
            client_id: clientId,
            client_secret: clientSecret,
            scopes: server.scopes,
          }),
        });
        const startData = await startResp.json();
        if (!startResp.ok) {
          try {
            popup && popup.close();
          } catch (e) {}
          throw new Error(startData.detail || 'OAuth start failed');
        }

        stateEl.textContent = 'waiting for sign-in…';
        if (popup && !popup.closed) {
          try {
            popup.location.href = startData.authorize_url;
          } catch (e) {
            try {
              popup.close();
            } catch (_) {}
            popup = window.open(
              startData.authorize_url,
              'mcp_oauth_' + encodeURIComponent(server.name),
            );
          }
        } else {
          popup = window.open(
            startData.authorize_url,
            'mcp_oauth_' + encodeURIComponent(server.name),
            'width=560,height=720,menubar=no,toolbar=no',
          );
        }

        const ok = await new Promise(function (resolve) {
          const poll = setInterval(function () {
            fetch('/api/config/mcp/oauth/poll?state=' + encodeURIComponent(startData.state))
              .then(function (r) {
                return r.json();
              })
              .then(function (s) {
                if (s.status === 'done') {
                  clearInterval(poll);
                  resolve(s.ok === true);
                  return;
                }
                if (popup && popup.closed) {
                  clearInterval(poll);
                  resolve(false);
                }
              })
              .catch(function () {});
          }, 800);
          setTimeout(
            function () {
              clearInterval(poll);
              resolve(false);
            },
            5 * 60 * 1000,
          );
        });
        if (!ok) {
          throw new Error('Sign-in did not complete.');
        }

        stateEl.textContent = 'saving connection…';
        const saveResp = await fetch('/api/config/mcp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            transport: 'http',
            name: server.name,
            url: server.url,
            auth_type: 'oauth2',
            oauth_provider_id: startData.provider_id,
          }),
        });
        const saveData = await saveResp.json();
        if (!saveResp.ok || !saveData.name) {
          throw new Error(saveData.detail || saveData.error || 'Save failed');
        }

        stateEl.textContent = '✓ connected';
        stateEl.style.color = 'var(--success,#16a34a)';
        if (typeof window.registerMcpSkill === 'function') {
          try {
            window.registerMcpSkill(saveData.id, saveData.name);
          } catch (e) {}
        }
        return true;
      } catch (e) {
        stateEl.textContent = '✕ ' + e.message;
        stateEl.style.color = 'var(--danger,#dc2626)';
        return false;
      }
    }

    async function _connectOne(server, statusLine) {
      if (server.transport === 'stdio') {
        return _connectStdio(server, statusLine);
      }
      return _connectHttp(server, statusLine);
    }

    const first = preset.servers[0];
    const firstLine = $el('div', {
      style:
        'margin:8px 0;padding:8px 10px;background:var(--bg-secondary,#f8f9fa);border-radius:6px;font-size:.82rem',
    });
    firstLine.appendChild(document.createTextNode('1. ' + first.name + ' — '));
    const firstState = $el('span', {
      textContent: 'starting…',
      style: 'color:var(--text-secondary,#64748b)',
    });
    firstLine.appendChild(firstState);
    statusEl.appendChild(firstLine);

    let firstOk = await _connectOne(first, firstLine);

    let restAllOk = true;
    for (let i = 1; i < preset.servers.length; i++) {
      const server = preset.servers[i];
      const serverLine = $el('div', {
        style:
          'margin:8px 0;padding:8px 10px;background:var(--bg-secondary,#f8f9fa);border-radius:6px;font-size:.82rem',
      });
      serverLine.appendChild(document.createTextNode(i + 1 + '. ' + server.name + ' — '));
      const stateEl = $el('span', {
        textContent: 'waiting to start',
        style: 'color:var(--text-secondary,#64748b)',
      });
      serverLine.appendChild(stateEl);
      statusEl.appendChild(serverLine);

      connectBtn.textContent = 'Continue to ' + server.name + ' →';
      connectBtn.disabled = false;
      backBtn.disabled = false;

      const ok = await new Promise(function (resolve) {
        connectBtn.onclick = async function () {
          connectBtn.disabled = true;
          backBtn.disabled = true;
          const ok = await _connectOne(server, serverLine);
          resolve(ok);
        };
      });
      if (!ok) restAllOk = false;
    }

    const allOk = firstOk && restAllOk;

    connectBtn.textContent = allOk ? 'Done' : 'Close';
    connectBtn.disabled = false;
    backBtn.disabled = false;
    connectBtn.onclick = function () {
      if (allOk && onSuccessCb) {
        try {
          onSuccessCb();
        } catch (e) {
          console.error('[google-wizard] onSuccess threw:', e);
        }
      }
      close();
    };
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
      args: Array.isArray(r.args) ? r.args.join(' ') : r.args || '',
      auth_type: r.auth_type && r.auth_type !== 'oauth2' ? r.auth_type : 'none',
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
    btn.onclick = function () {
      renderManual(prefill);
    };
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
        return (
          'Connected — but tool calls require the “' +
          hint[1] +
          '” header. Paste the value in the Headers field below, then retry.'
        );
      }
      return 'Connected — but tool calls require authentication. Add the required header in the Headers field below, then retry.';
    }
    if (/^auth_error:4\d\d/.test(raw) || /\b401\b/.test(raw) || /unauthorized/i.test(raw)) {
      return 'Authentication failed — update the credentials below and retry.';
    }
    if (/command not found/i.test(raw)) return raw;
    if (/no tools/i.test(raw))
      return 'Server connected but returned no tools — check the URL or auth settings.';
    // Script file not found — extract filename for a friendly message
    var fileMatch =
      raw.match(/can['']t open file[^']*['"]([^'"]+)['"]/i) ||
      raw.match(/No such file or directory[^:]*:\s*['"]?([^\s'"]+\.(?:py|js|ts))['"]?/i);
    if (fileMatch || /no such file or directory/i.test(raw)) {
      var fname = fileMatch ? fileMatch[1].split(/[\\/]/).pop() : 'the script file';
      return (
        'Can’t find “' + fname + '” — update the path below to where it lives on your machine.'
      );
    }
    // Strip embedded JSON blobs: "Could not list tools: {...}" → "Could not list tools"
    return raw.replace(/:\s*[\[{][^}\]]{0,300}[\]}]/, '').trim() || raw;
  }

  // ── Step 2: Review card (read-only when ok, editable when error) ──────────────

  function renderReview(result, rawInput, errorMsg) {
    clear(modal);
    state.pendingResult = result;

    const isEditMode = errorMsg === '\x00edit';
    const friendlyError = errorMsg && !isEditMode ? parseErrorMsg(errorMsg) : null;
    const isStdio = result.transport === 'stdio';

    const hdr = $el('div', { className: 'mcp-modal-header' });
    const backBtn = $el('button', { className: 'mcp-modal-back', textContent: '‹', title: 'Back' });
    backBtn.onclick = function () {
      renderStep1(rawInput);
    };
    hdr.appendChild(backBtn);
    hdr.appendChild(
      $el('span', { textContent: 'Connect an MCP server', className: 'mcp-modal-title' }),
    );
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body' });

    if (friendlyError) {
      const errBanner = $el('div', { className: 'mcp-inline-error' });
      errBanner.appendChild($el('span', { textContent: '✕ ' + friendlyError }));
      errBanner.appendChild(_manualEscapeBtn(result));
      // If a stale OAuth provider exists for this connection, offer a sign-out
      // link so the user can reset credentials without touching the filesystem.
      const staleProviderId = result.oauth_provider_id || '';
      if (staleProviderId) {
        const signOutLink = $el('button', {
          type: 'button',
          className: 'mcp-auth-linkbtn',
          textContent: 'Sign out & retry →',
          title: 'Clear stored OAuth credentials and start sign-in again',
        });
        signOutLink.style.cssText = 'margin-left:8px;font-size:.78rem';
        signOutLink.onclick = function () {
          fetch('/api/config/mcp/oauth/forget?provider_id=' + encodeURIComponent(staleProviderId), {
            method: 'POST',
          }).catch(function () {});
          // Re-render review without the stale provider so OAuth section resets
          renderReview(Object.assign({}, result, { oauth_provider_id: '' }), rawInput, null);
        };
        errBanner.appendChild(signOutLink);
      }
      body.appendChild(errBanner);
    }

    if (!errorMsg && (result.confidence === 'low' || result.confidence === 'medium')) {
      const warn = $el('div', { className: 'mcp-confidence-warning' });
      warn.appendChild(
        $el('span', {
          textContent: "⚠ We're not certain about this — please review before connecting.",
        }),
      );
      body.appendChild(warn);
    }

    const detectedLabel = isStdio ? '✓ Found a local MCP server' : '✓ Found a remote MCP server';
    body.appendChild($el('p', { textContent: detectedLabel, className: 'mcp-detected-label' }));

    // ── Unified OAuth section (used by both read-only and editable modes) ─────
    // Single source of truth for sign-in state. Both branches assign these so the
    // CTA-morphing logic doesn't need to know which mode it's in.
    let oauthStatus = function () {
      return { isOauth: false, signedIn: true };
    };
    let runOAuthIfNeeded = function (cb) {
      cb(true);
    };

    function createOauthSection(
      initialProviderId,
      getUrl,
      getLabel,
      onStateChange,
      getConnectionId,
    ) {
      let providerId = initialProviderId || '';
      const helper = $el('div', { className: 'mcp-auth-helper' });

      function refresh() {
        clear(helper);
        if (providerId) {
          helper.className = 'mcp-auth-helper ok';
          helper.appendChild(document.createTextNode('✓ Signed in  '));
          const btn = $el('button', {
            type: 'button',
            className: 'mcp-auth-linkbtn',
            textContent: 'Sign out',
          });
          btn.onclick = function () {
            const pid = providerId;
            providerId = '';
            refresh();
            if (onStateChange) onStateChange();
            fetch('/api/config/mcp/oauth/forget?provider_id=' + encodeURIComponent(pid), {
              method: 'POST',
            }).catch(function () {});
          };
          helper.appendChild(btn);
        } else {
          helper.className = 'mcp-auth-helper warn';
          helper.textContent = '⚠ Sign-in required to continue';
        }
      }

      // ── Bring-your-own OAuth client fields (Advanced) ────────────────────────
      const advancedToggle = $el('button', {
        type: 'button',
        className: 'mcp-auth-linkbtn',
        textContent: '▸ Advanced (OAuth client credentials)',
      });
      advancedToggle.style.cssText = 'font-size:.75rem;margin-top:6px;display:block';
      const advancedSection = $el('div');
      advancedSection.style.display = 'none';
      advancedSection.style.cssText =
        'display:none;margin-top:8px;padding:10px 12px;background:var(--bg-secondary,#f8f9fa);border-radius:6px;border:1px solid var(--border,#e2e8f0)';
      advancedSection.innerHTML = `
        <p style="margin:0 0 8px;font-size:.75rem;color:var(--text-secondary,#64748b)">
          Some OAuth providers (e.g. Google) require you to create your own OAuth app.
          Paste your <strong>Client ID</strong> and <strong>Client Secret</strong> from
          <a href="https://console.cloud.google.com/auth/clients" target="_blank" style="color:var(--accent,#16a34a)">Google Cloud Console</a>.
          Leave blank to use auto-registration (works for most MCP servers).
        </p>
        <label style="font-size:.78rem;font-weight:600;display:block;margin-bottom:3px">Client ID</label>
        <input type="text" id="mcp-byoc-client-id" placeholder="e.g. 1234567890-abc.apps.googleusercontent.com"
          style="width:100%;box-sizing:border-box;padding:6px 8px;border:1px solid var(--border,#e2e8f0);border-radius:4px;font-size:.8rem;margin-bottom:8px">
        <label style="font-size:.78rem;font-weight:600;display:block;margin-bottom:3px">Client Secret</label>
        <input type="password" id="mcp-byoc-client-secret" placeholder="GOCSPX-…"
          style="width:100%;box-sizing:border-box;padding:6px 8px;border:1px solid var(--border,#e2e8f0);border-radius:4px;font-size:.8rem;margin-bottom:8px">
        <label style="font-size:.78rem;font-weight:600;display:block;margin-bottom:3px">Scopes <span style="font-weight:400;color:var(--text-secondary,#64748b)">(space-separated, leave blank to auto-detect)</span></label>
        <input type="text" id="mcp-byoc-scopes" placeholder="e.g. https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose"
          style="width:100%;box-sizing:border-box;padding:6px 8px;border:1px solid var(--border,#e2e8f0);border-radius:4px;font-size:.8rem">
        <p style="margin:6px 0 0;font-size:.72rem;color:var(--text-secondary,#64748b)">
          Gmail MCP scopes (both required): <code style="font-size:.72rem">https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose</code>
        </p>
        <p style="margin:8px 0 0;font-size:.72rem;color:var(--text-secondary,#64748b);padding:6px 8px;background:var(--bg-tertiary,#f1f5f9);border-radius:4px">
          📋 Register this redirect URI in your OAuth app:<br>
          <code style="font-size:.72rem;user-select:all">http://127.0.0.1:8000/oauth/callback</code>
        </p>
      `;
      advancedToggle.onclick = function () {
        const open = advancedSection.style.display !== 'none';
        advancedSection.style.display = open ? 'none' : 'block';
        advancedToggle.textContent = (open ? '▸' : '▾') + ' Advanced (OAuth client credentials)';
      };

      function _getByocFields() {
        const cidEl = advancedSection.querySelector('#mcp-byoc-client-id');
        const csecEl = advancedSection.querySelector('#mcp-byoc-client-secret');
        const scopesEl = advancedSection.querySelector('#mcp-byoc-scopes');
        const scopesRaw = (scopesEl && scopesEl.value.trim()) || '';
        return {
          client_id: (cidEl && cidEl.value.trim()) || '',
          client_secret: (csecEl && csecEl.value.trim()) || '',
          scopes: scopesRaw ? scopesRaw.split(/\s+/).filter(Boolean) : [],
        };
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
        const byoc = _getByocFields();
        fetch('/api/config/mcp/oauth/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url: u,
            label: getLabel() || u,
            connection_id: typeof getConnectionId === 'function' ? getConnectionId() || '' : '',
            client_id: byoc.client_id,
            client_secret: byoc.client_secret,
            scopes: byoc.scopes,
          }),
        })
          .then(function (r) {
            return r.json().then(function (d) {
              return { ok: r.ok, body: d };
            });
          })
          .then(function (resp) {
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
            const popup = window.open(
              resp.body.authorize_url,
              'mcp_oauth',
              'width=560,height=720,menubar=no,toolbar=no',
            );
            // In the Electron shell, window.open is routed to the system browser
            // and returns null — that's expected, not an error. Poll detects
            // completion via the backend callback. Only treat null as a block in
            // browser mode (where a null return means a popup blocker fired).
            if (
              !popup &&
              !(typeof window.gatorShell !== 'undefined' && window.gatorShell.isShell)
            ) {
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
              if (ok) {
                providerId = provId;
                refresh();
              } else {
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
                .then(function (r) {
                  return r.json();
                })
                .then(function (s) {
                  if (s.status === 'done') {
                    clearInterval(poll);
                    finish(s.ok, s.error);
                    return;
                  }
                  if (popup && popup.closed) {
                    if (!closedSince) closedSince = Date.now();
                    if (Date.now() - closedSince >= 4000) {
                      clearInterval(poll);
                      finish(false, 'Popup closed before completing.');
                    }
                  }
                })
                .catch(function () {});
            }, 800);
            setTimeout(
              function () {
                clearInterval(poll);
              },
              5 * 60 * 1000,
            );
          })
          .catch(function (e) {
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
        advancedToggle: advancedToggle,
        advancedSection: advancedSection,
        refresh: refresh,
        runFlow: runFlow,
        getProviderId: function () {
          return providerId;
        },
      };
    }

    // ── Read-only card (no error) ─────────────────────────────────────────────
    let getConnectPayload;

    if (!errorMsg) {
      // Flat layout — no nested card. Just rows on the modal body.
      const nameRow = $el('div', { className: 'mcp-review-name-row' });
      nameRow.appendChild(
        $el('label', { textContent: 'Name', className: 'mcp-review-name-label' }),
      );
      const nameInput = $el('input', {
        type: 'text',
        className: 'mcp-review-name-input',
        placeholder: 'Give this connection a name',
      });
      nameInput.value = result.name || '';
      nameRow.appendChild(nameInput);
      body.appendChild(nameRow);
      body.appendChild(
        attachNameValidator(nameInput, function () {
          return result.connection_id || '';
        }),
      );

      body.appendChild(
        $el('div', {
          textContent: isStdio ? 'Local · stdio' : 'Remote · HTTPS',
          className: 'mcp-review-type',
        }),
      );
      if (!isStdio) {
        body.appendChild($el('div', { textContent: result.url, className: 'mcp-review-detail' }));
      } else {
        const cmdRow = $el('div', { className: 'mcp-review-detail' });
        cmdRow.appendChild($el('span', { textContent: 'command  ', className: 'mcp-review-key' }));
        cmdRow.appendChild($el('span', { textContent: result.command }));
        body.appendChild(cmdRow);
        if (result.args && result.args.length) {
          const argsRow = $el('div', { className: 'mcp-review-detail' });
          argsRow.appendChild(
            $el('span', { textContent: 'args     ', className: 'mcp-review-key' }),
          );
          argsRow.appendChild($el('span', { textContent: result.args.join(' ') }));
          body.appendChild(argsRow);
        }
      }
      if (result.prerequisite_warning) {
        body.appendChild(
          $el('p', {
            textContent: '⚠ ' + result.prerequisite_warning,
            className: 'mcp-prereq-warning',
          }),
        );
      }

      // Detect {placeholder} values in headers (HTTP) and env (stdio)
      var headerPH = findPlaceholders(result.headers || {});
      var envPH = findPlaceholders(result.env || {});
      var headerFields = buildPlaceholderFields(
        headerPH,
        'This server requires connection details:',
        result.headers || {},
      );
      var envFields = buildPlaceholderFields(
        envPH,
        'This server requires environment variables:',
        result.env || {},
      );
      if (headerFields.container) body.appendChild(headerFields.container);
      if (envFields.container) body.appendChild(envFields.container);

      // Auto-detected OAuth — show sign-in status inline so the user can authorize
      // before clicking Connect, instead of getting bounced by a server-side error.
      let roOauthSection = null;
      if (!isStdio && result.auth_type === 'oauth2') {
        roOauthSection = createOauthSection(
          result.oauth_provider_id || '',
          function () {
            return result.url;
          },
          function () {
            return nameInput.value.trim() || result.name || result.url;
          },
          function () {
            updateConnectBtn();
          },
          function () {
            return result.connection_id || '';
          },
        );
        body.appendChild(roOauthSection.helper);
        body.appendChild(roOauthSection.advancedToggle);
        body.appendChild(roOauthSection.advancedSection);
        roOauthSection.refresh();
        oauthStatus = function () {
          return { isOauth: true, signedIn: !!roOauthSection.getProviderId() };
        };
        runOAuthIfNeeded = function (cb) {
          if (roOauthSection.getProviderId()) {
            cb(true);
            return;
          }
          roOauthSection.runFlow(cb);
        };
      }

      getConnectPayload = function () {
        var resolvedHeaders = resolvePlaceholders(result.headers || {}, headerFields.getValues());
        var resolvedEnv = resolvePlaceholders(result.env || {}, envFields.getValues());
        return Object.assign({}, result, {
          name: nameInput.value.trim() || result.name || 'MCP Server',
          headers: resolvedHeaders,
          env: resolvedEnv,
          oauth_provider_id: roOauthSection
            ? roOauthSection.getProviderId()
            : result.oauth_provider_id || '',
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

      const nameInput = $el('input', {
        type: 'text',
        className: 'mcp-edit-input',
        placeholder: 'Server name',
      });
      nameInput.value = result.name || '';
      form.appendChild(field('Name', nameInput));
      form.appendChild(
        attachNameValidator(nameInput, function () {
          return result.connection_id || '';
        }),
      );

      // HTTP-specific fields
      let urlInput, authDrop, authValueInput, authValueRow, basicEmailInput, basicEmailRow;
      let editOauthSection = null;
      if (!isStdio) {
        urlInput = $el('input', {
          type: 'text',
          className: 'mcp-edit-input',
          placeholder: 'https://example.com/mcp',
        });
        urlInput.value = result.url || '';
        form.appendChild(field('URL', urlInput));

        // probe_failed means the credential goes in a custom Header (e.g. x-nabu-key),
        // not in a Bearer token — keep Auth=None so the Token field doesn't gate Save.
        const isProbeFailErr = /^auth_error:probe_failed/.test(errorMsg || '');
        const defaultAuth =
          result.auth_type && result.auth_type !== 'none'
            ? result.auth_type
            : !isProbeFailErr && /\b401\b|unauthorized|auth_error/i.test(errorMsg || '')
              ? 'bearer'
              : 'none';
        const authPlaceholders = {
          bearer: 'Token',
          api_key: 'API key', // pragma: allowlist secret
          basic: 'API token',
        };
        // Split existing value if it's basic-format (email:token)
        const initialColon = (result.auth_value || '').indexOf(':');
        const initialEmail =
          defaultAuth === 'basic' && initialColon > 0
            ? result.auth_value.slice(0, initialColon)
            : '';
        const initialSecret =
          defaultAuth === 'basic' && initialColon > 0
            ? result.auth_value.slice(initialColon + 1)
            : result.auth_value || '';

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
            authValueRow.style.display = val === 'none' || isOauth ? 'none' : '';
            basicEmailRow.style.display = val === 'basic' ? '' : 'none';
            if (authValueInput && authPlaceholders[val]) {
              authValueInput.placeholder = authPlaceholders[val];
            }
            if (editOauthSection) {
              editOauthSection.helper.style.display = isOauth ? '' : 'none';
              editOauthSection.advancedToggle.style.display = isOauth ? '' : 'none';
              if (!isOauth) editOauthSection.advancedSection.style.display = 'none';
              if (isOauth) editOauthSection.refresh();
            }
            updateConnectBtn();
          },
        );
        const authRow = field('Auth', authDrop.el);
        form.appendChild(authRow);
        // OAuth section — helper text + sign-in/out controls, hidden unless oauth2 selected.
        editOauthSection = createOauthSection(
          result.oauth_provider_id || '',
          function () {
            return urlInput.value.trim();
          },
          function () {
            return nameInput.value.trim() || urlInput.value.trim();
          },
          function () {
            updateConnectBtn();
          },
          function () {
            return result.connection_id || '';
          },
        );
        editOauthSection.helper.style.display = defaultAuth === 'oauth2' ? '' : 'none';
        editOauthSection.advancedToggle.style.display = defaultAuth === 'oauth2' ? '' : 'none';
        editOauthSection.advancedSection.style.display = 'none';
        authRow.appendChild(editOauthSection.helper);
        authRow.appendChild(editOauthSection.advancedToggle);
        authRow.appendChild(editOauthSection.advancedSection);
        if (defaultAuth === 'oauth2') editOauthSection.refresh();
        oauthStatus = function () {
          return {
            isOauth: authDrop.getValue() === 'oauth2',
            signedIn: !!editOauthSection.getProviderId(),
          };
        };
        runOAuthIfNeeded = function (cb) {
          if (authDrop.getValue() !== 'oauth2' || editOauthSection.getProviderId()) {
            cb(true);
            return;
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
          maskedTokenHint =
            defaultAuth === 'basic' && result.auth_value_hint.indexOf(':') > 0
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
        authValueRow.style.display =
          defaultAuth === 'none' || defaultAuth === 'oauth2' ? 'none' : '';
        form.appendChild(authValueRow);

        // Headers section — needed for servers that gate access on a custom
        // header (e.g. x-api-key). The session_terminated error specifically
        // tells the user to add one here, so it must exist on this form.
        var editHdrsContainer = $el('div', { className: 'mcp-kv-rows' });
        function editAddHdrRow(k, v) {
          var row = $el('div', { className: 'mcp-kv-row' });
          var kIn = $el('input', {
            type: 'text',
            className: 'mcp-kv-key',
            placeholder: 'Header name (e.g. x-api-key)',
          });
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
            placeholder: isMaskedHint || isTemplated ? v : 'Value',
          });
          // Stash the original templated value on the row so substitution can
          // re-apply it on submit when the user hasn't overwritten it.
          if (isTemplated) row.dataset.template = v;
          vIn.value = isMaskedHint || isTemplated ? '' : v || '';
          var rm = $el('button', {
            type: 'button',
            className: 'mcp-kv-rm',
            textContent: '×',
            title: 'Remove',
          });
          rm.onclick = function () {
            editHdrsContainer.removeChild(row);
          };
          row.appendChild(kIn);
          row.appendChild(vIn);
          row.appendChild(rm);
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
          editHeaderPH,
          'This server requires connection details:',
          existingHeaders,
        );
        if (editHeaderFields.container) form.appendChild(editHeaderFields.container);
        Object.keys(existingHeaders).forEach(function (k) {
          editAddHdrRow(k, existingHeaders[k]);
        });

        var editHdrsLabelRow = $el('div', { className: 'mcp-edit-row' });
        editHdrsLabelRow.appendChild(
          $el('label', { textContent: 'Headers', className: 'mcp-edit-label' }),
        );
        var editHdrsRight = $el('div', { style: 'flex:1' });
        editHdrsRight.appendChild(editHdrsContainer);
        var editAddHdrBtn = $el('button', {
          type: 'button',
          className: 'mcp-kv-add',
          textContent: '+ Add header',
        });
        editAddHdrBtn.onclick = function () {
          var kIn = editAddHdrRow('', '');
          setTimeout(function () {
            kIn.focus();
          }, 0);
        };
        editHdrsRight.appendChild(editAddHdrBtn);
        editHdrsLabelRow.appendChild(editHdrsRight);
        form.appendChild(editHdrsLabelRow);

        // For session_terminated or auth_probe_failed: auto-add one empty row
        // + scroll/focus so the user sees exactly where to type without hunting.
        // If the probe_detail mentions a header name (e.g. `'x-nabu-key'`), pre-fill it.
        var isSessionTerm = /^auth_error:session_terminated/.test(errorMsg || '');
        var isProbeFail = /^auth_error:probe_failed/.test(errorMsg || '');
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
            try {
              editHdrsLabelRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } catch (e) {}
            // If we pre-filled the header name, focus the value field instead.
            if (hintedHeader) {
              var row = firstKey.parentElement;
              var valIn = row && row.querySelector('.mcp-kv-val');
              if (valIn) {
                valIn.focus();
                return;
              }
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
        const cmdInput = $el('input', {
          type: 'text',
          className: 'mcp-edit-input',
          placeholder: 'npx',
        });
        cmdInput.value = result.command || '';
        form.appendChild(field('Command', cmdInput));

        const argsInput = $el('input', {
          type: 'text',
          className: 'mcp-edit-input',
          placeholder: '@playwright/mcp@latest',
        });
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
            headers:
              typeof result.__getEditHeaders === 'function'
                ? result.__getEditHeaders()
                : result.headers || {},
            oauth_provider_id:
              authType === 'oauth2' && editOauthSection ? editOauthSection.getProviderId() : '',
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
        : isEditMode
          ? 'Save'
          : errorMsg
            ? 'Try again'
            : 'Connect';
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
    backBtn.onclick = function () {
      renderStep1(rawInput);
    };
    hdr.appendChild(backBtn);
    hdr.appendChild($el('span', { textContent: 'Choose a server', className: 'mcp-modal-title' }));
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body' });
    body.appendChild(
      $el('p', {
        textContent: 'Found ' + results.length + ' servers — pick one to connect:',
        className: 'mcp-modal-hint',
      }),
    );

    const list = $el('div', { className: 'mcp-chooser' });
    results.forEach(function (result) {
      const item = $el('button', { className: 'mcp-chooser-item' });
      item.appendChild(
        $el('span', { textContent: result.name || 'MCP Server', className: 'mcp-chooser-name' }),
      );
      item.appendChild(
        $el('span', {
          textContent: result.transport === 'stdio' ? 'Local · stdio' : 'Remote · HTTPS',
          className: 'mcp-chooser-type',
        }),
      );
      item.onclick = function () {
        renderReview(result, rawInput);
      };
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
    backBtn.onclick = function () {
      renderStep1(rawInput);
    };
    hdr.appendChild(backBtn);
    hdr.appendChild(
      $el('span', { textContent: 'Connect an MCP server', className: 'mcp-modal-title' }),
    );
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body' });
    const errBox = $el('div', { className: 'mcp-parse-status mcp-parse-error' });
    errBox.appendChild($el('span', { textContent: "⚠ We couldn't recognize this format." }));
    body.appendChild(errBox);

    const manualLink = $el('button', {
      textContent: 'Enter details manually →',
      className: 'mcp-manual-link',
    });
    manualLink.onclick = function () {
      renderManual({});
    };
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
    backBtn.onclick = function () {
      renderStep1(state.rawInput || '');
    };
    hdr.appendChild(backBtn);
    hdr.appendChild(
      $el('span', { textContent: 'Enter server details', className: 'mcp-modal-title' }),
    );
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
    const nameInput = $el('input', {
      type: 'text',
      className: 'mcp-form-input',
      placeholder: 'My MCP Server',
    });
    nameInput.value = prefill.name || '';
    nameRow.appendChild(nameInput);
    body.appendChild(nameRow);
    body.appendChild(
      attachNameValidator(nameInput, function () {
        return prefill.connection_id || '';
      }),
    );

    const urlRow = $el('div', { className: 'mcp-form-row' });
    urlRow.appendChild($el('label', { textContent: 'Server URL', className: 'mcp-form-label' }));
    const urlInput = $el('input', {
      type: 'text',
      className: 'mcp-form-input',
      placeholder: 'https://example.com/mcp',
    });
    urlInput.value = prefill.url || '';
    urlRow.appendChild(urlInput);
    body.appendChild(urlRow);

    const cmdRow = $el('div', { className: 'mcp-form-row', style: 'display:none' });
    cmdRow.appendChild($el('label', { textContent: 'Command', className: 'mcp-form-label' }));
    const cmdInput = $el('input', {
      type: 'text',
      className: 'mcp-form-input',
      placeholder: 'npx',
    });
    cmdInput.value = prefill.command || '';
    cmdRow.appendChild(cmdInput);
    body.appendChild(cmdRow);

    const argsRow = $el('div', { className: 'mcp-form-row', style: 'display:none' });
    argsRow.appendChild($el('label', { textContent: 'Args', className: 'mcp-form-label' }));
    const argsInput = $el('input', {
      type: 'text',
      className: 'mcp-form-input',
      placeholder: '@playwright/mcp@latest',
    });
    argsInput.value = (prefill.args || []).join(' ');
    argsRow.appendChild(argsInput);
    body.appendChild(argsRow);

    // ── Auth ────────────────────────────────────────────────────────────────────
    const authRow = $el('div', { className: 'mcp-form-row' });
    authRow.appendChild($el('label', { textContent: 'Auth', className: 'mcp-form-label' }));
    const authSel = $el('select', { className: 'mcp-form-input' });
    [
      { value: 'none', label: 'None' },
      { value: 'bearer', label: 'Bearer token' },
      { value: 'basic', label: 'Basic (email:token)' },
      { value: 'api_key', label: 'API key' },
    ].forEach(function (opt) {
      authSel.appendChild($el('option', { value: opt.value, textContent: opt.label }));
    });
    authSel.value = prefill.auth_type || 'none';
    authRow.appendChild(authSel);
    body.appendChild(authRow);

    const authValRow = $el('div', { className: 'mcp-form-row' });
    authValRow.appendChild(
      $el('label', { textContent: 'Credential', className: 'mcp-form-label' }),
    );
    const authValInput = $el('input', {
      type: 'password',
      className: 'mcp-form-input',
      placeholder: 'token / email:api_token',
    });
    authValInput.value = prefill.auth_value || '';
    authValRow.appendChild(authValInput);
    body.appendChild(authValRow);

    // ── Headers (extra_headers key-value) ────────────────────────────────────
    const hdrsLabel = $el('div', { className: 'mcp-form-row' });
    hdrsLabel.appendChild($el('label', { textContent: 'Headers', className: 'mcp-form-label' }));
    const hdrsHint = $el('span', {
      textContent: 'Extra HTTP headers (e.g. x-api-key)',
      className: 'mcp-form-sublabel',
    });
    hdrsLabel.appendChild(hdrsHint);
    body.appendChild(hdrsLabel);

    const hdrsContainer = $el('div', { className: 'mcp-kv-rows' });

    function addHdrRow(k, v) {
      const row = $el('div', { className: 'mcp-kv-row' });
      const kIn = $el('input', {
        type: 'text',
        className: 'mcp-kv-key',
        placeholder: 'Header name',
      });
      kIn.value = k || '';
      const vIn = $el('input', { type: 'password', className: 'mcp-kv-val', placeholder: 'Value' });
      vIn.value = v || '';
      const rm = $el('button', {
        type: 'button',
        className: 'mcp-kv-rm',
        textContent: '×',
        title: 'Remove',
      });
      rm.onclick = function () {
        hdrsContainer.removeChild(row);
      };
      row.appendChild(kIn);
      row.appendChild(vIn);
      row.appendChild(rm);
      hdrsContainer.appendChild(row);
    }

    // Pre-populate from prefill
    const prefillHeaders = prefill.headers || {};
    Object.keys(prefillHeaders).forEach(function (k) {
      addHdrRow(k, prefillHeaders[k]);
    });

    const hdrsWidget = $el('div', { className: 'mcp-form-row mcp-kv-widget' });
    hdrsWidget.appendChild($el('div', { className: 'mcp-form-label' })); // spacer
    const hdrsRight = $el('div', { style: 'flex:1' });
    hdrsRight.appendChild(hdrsContainer);
    const addHdrBtn = $el('button', {
      type: 'button',
      className: 'mcp-kv-add',
      textContent: '+ Add header',
    });
    addHdrBtn.onclick = function () {
      addHdrRow('', '');
    };
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
      authValRow.style.display = isStdio || authSel.value === 'none' ? 'none' : '';
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
        const withProvider = Object.assign({}, result, {
          oauth_provider_id: payload.oauth_provider_id || result.oauth_provider_id || '',
        });
        renderReview(withProvider, rawInput || state.rawInput || '', msg);
      }
    } catch (e) {
      // Pass the oauth_provider_id through so the error banner can offer "Sign out & retry"
      const withProvider = Object.assign({}, result, {
        oauth_provider_id: payload.oauth_provider_id || result.oauth_provider_id || '',
      });
      renderReview(
        withProvider,
        rawInput || state.rawInput || '',
        'Network error — please try again.',
      );
    }
  }

  // ── Connecting / Success / Error ──────────────────────────────────────────────

  var _connectTimers = [];

  function _clearConnectTimers() {
    _connectTimers.forEach(function (t) {
      clearTimeout(t);
    });
    _connectTimers = [];
  }

  function renderConnecting(payload) {
    _clearConnectTimers();

    var target =
      payload.transport === 'stdio'
        ? payload.command || 'server'
        : payload.name || payload.url || 'server';

    // Replace modal body — no ghosted form behind a dark fog.
    clear(modal);

    // Header
    modal.appendChild(
      $el('div', { class: 'mcp-modal-header' }, [
        $el('span', {}), // spacer for grid
        $el('span', { class: 'mcp-modal-title', text: 'Connecting…' }),
        $el('button', {
          type: 'button',
          class: 'mcp-modal-close',
          onclick: close,
          'aria-label': 'Close',
          text: '×',
        }),
      ]),
    );

    // Shimmer progress bar — sits flush below the header, full modal width
    var bar = $el('div', { class: 'mcp-progress-bar' });
    var fill = $el('div', { class: 'mcp-progress-fill' });
    bar.appendChild(fill);
    modal.appendChild(bar);

    // Body
    var body = $el('div', { class: 'mcp-modal-body mcp-connect-body' });

    var serverLabel = $el('div', { class: 'mcp-connect-server', text: target });
    body.appendChild(serverLabel);

    // Stage rows
    var stages = [
      { key: 'reach', label: 'Reaching server' },
      { key: 'tools', label: 'Discovering tools' },
      { key: 'auth', label: 'Verifying access' },
    ];
    var stageEls = {};
    stages.forEach(function (s) {
      var row = $el('div', { class: 'mcp-stage-row mcp-stage-pending' });
      var dot = $el('span', { class: 'mcp-stage-dot' });
      var lbl = $el('span', { class: 'mcp-stage-label', text: s.label });
      row.appendChild(dot);
      row.appendChild(lbl);
      body.appendChild(row);
      stageEls[s.key] = row;
    });

    modal.appendChild(body);

    // Footer with visible Cancel
    modal.appendChild(
      $el('div', { class: 'mcp-modal-footer' }, [
        $el('button', { type: 'button', class: 'btn-ghost', onclick: close, text: 'Cancel' }),
      ]),
    );

    // Animate stages: tick active → done on a rough timeline that covers the
    // typical backend sequence (URL probe ~1s, tools/list ~2s, auth probe ~2s).
    function activateStage(key) {
      Object.keys(stageEls).forEach(function (k) {
        stageEls[k].className = 'mcp-stage-row mcp-stage-pending';
      });
      stageEls[key].className = 'mcp-stage-row mcp-stage-active';
    }
    function completeStage(key) {
      stageEls[key].className = 'mcp-stage-row mcp-stage-done';
    }

    activateStage('reach');
    _connectTimers.push(
      setTimeout(function () {
        completeStage('reach');
        activateStage('tools');
      }, 1200),
    );
    _connectTimers.push(
      setTimeout(function () {
        completeStage('tools');
        activateStage('auth');
      }, 3200),
    );
    // 'auth' stays active until the real response lands.
  }

  function renderSuccess(data) {
    _clearConnectTimers();
    const count = data.tool_count || 0;
    const serverName = data.name || 'server';
    if (state && state.opts && typeof state.opts.onSuccess === 'function') {
      try {
        state.opts.onSuccess(data);
      } catch (e) {
        console.error('[mcp-modal] onSuccess threw:', e);
      }
    }

    // Brief in-modal confirmation before auto-close — user sees the result
    // in context rather than the modal vanishing and a toast appearing elsewhere.
    clear(modal);
    modal.appendChild(
      $el('div', { class: 'mcp-modal-header' }, [
        $el('span', {}),
        $el('span', { class: 'mcp-modal-title', text: 'Connected' }),
        $el('span', {}),
      ]),
    );
    // Solid green bar — complete
    var bar = $el('div', { class: 'mcp-progress-bar' });
    var fill = $el('div', { class: 'mcp-progress-fill mcp-progress-done' });
    bar.appendChild(fill);
    modal.appendChild(bar);

    var body = $el('div', { class: 'mcp-modal-body mcp-connect-body mcp-success-body' });
    body.appendChild($el('div', { class: 'mcp-success-icon', text: '✓' }));
    body.appendChild($el('div', { class: 'mcp-success-name', text: serverName }));
    body.appendChild(
      $el('div', {
        class: 'mcp-success-count',
        text: count + ' tool' + (count !== 1 ? 's' : '') + ' available',
      }),
    );
    modal.appendChild(body);

    setTimeout(function () {
      close();
      showSuccessToast(
        '"' + serverName + '" connected · ' + count + ' tool' + (count !== 1 ? 's' : ''),
      );
    }, 900);
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
    setTimeout(function () {
      t.classList.add('mcp-toast-out');
    }, 2600);
    setTimeout(function () {
      if (t.parentNode) t.parentNode.removeChild(t);
    }, 3000);
  }

  function renderError(detail, pendingResult) {
    clear(modal);
    const goBack = pendingResult
      ? function () {
          renderReview(pendingResult, state.rawInput || '');
        }
      : function () {
          renderStep1(state.rawInput || '');
        };

    modal.appendChild(
      $el('div', { class: 'mcp-modal-header' }, [
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
      ]),
    );
    modal.appendChild(
      $el('div', { class: 'mcp-modal-body' }, [
        $el('div', { class: 'mcp-error', text: detail || 'Unknown error' }),
      ]),
    );
    modal.appendChild(
      $el('div', { class: 'mcp-modal-footer' }, [
        $el('button', { type: 'button', class: 'btn-ghost', onclick: close, text: 'Cancel' }),
        $el('button', {
          type: 'button',
          class: 'btn-primary',
          text: 'Back to review',
          onclick: goBack,
        }),
      ]),
    );
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
      onclick: null,
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
      if (e.key === 'Escape') {
        e.stopPropagation();
        close();
        return;
      }
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
      url: conn.url_hint || '', // PR #10 fix: field renamed to url_hint (masked)
      auth_type: conn.auth_type || 'none',
      auth_value: prefillAuthValue, // basic-email only, never the secret
      auth_value_hint: hint, // masked preview for placeholder
      headers: headersHint, // {key: "••••wxyz"} — value shown as masked placeholder; blank on save = keep
      oauth_provider_id: conn.oauth_provider_id || '', // so OAuth section shows "Signed in"
      command: conn.command_hint || '', // PR #10 fix: field renamed to command_hint (masked)
      args: conn.args_hint || [], // PR #10 fix: field renamed to args_hint (masked)
      env: envHint, // same masking pattern
    };
    // Open straight into the editable form (reuse error-mode UI which shows all fields)
    // Pass a sentinel errorMsg so the form renders but don't show an error banner
    renderReview(prefill, '', '\x00edit');
  };
  // ── Complete pending secrets (Increment 4b, 2026-08-07 milestone) ────────
  // A plugin-registered MCP connection that declared an unresolved
  // {PLACEHOLDER} (or blank "fill this in") secret is persisted disabled
  // with a `missing_secrets` list (mcp.manager.register_plugin_mcp_server)
  // and, until now, had no code path to complete it. Reuses
  // buildPlaceholderFields — the SAME placeholder-field UI the paste-analyze
  // flow renders for a manually-added server's {placeholder} env/header
  // values (decision #5: reuse the existing add-modal mechanism, don't
  // invent a new form) — so a plugin's declared secret and a hand-typed one
  // look and behave identically. `conn` is a row from /api/config/mcp
  // (id, name, plugin_id, missing_secrets, connect_error).
  window.openMcpCompleteSecretsModal = function (conn, opts) {
    if (overlay) close();
    state = { opts: opts || {} };
    root = document.getElementById('mcp-modal-root');
    if (!root) return;
    prevFocus = document.activeElement;

    overlay = $el('div', { class: 'mcp-modal-overlay', role: 'presentation' });
    modal = $el('div', {
      class: 'mcp-modal',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-label': 'Complete MCP server setup',
    });
    overlay.appendChild(modal);
    root.appendChild(overlay);
    // Fix #4 (2026-08-07 milestone adversarial review): capture identity of
    // THIS modal instance's overlay. If the user closes this modal before its
    // fetch resolves and opens a different one, the stale fetch's callback
    // must no-op instead of tearing down whatever's now showing (the shared
    // close()/errorDiv would otherwise act on a superseded modal).
    const thisOverlay = overlay;

    keyHandler = function (e) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        close();
        return;
      }
      trapTab(e);
    };
    document.addEventListener('keydown', keyHandler, true);

    const hdr = $el('div', { className: 'mcp-modal-header' });
    hdr.appendChild(
      $el('span', {
        textContent: 'Complete setup — ' + (conn.name || conn.id),
        className: 'mcp-modal-title',
      }),
    );
    const xBtn = $el('button', { className: 'mcp-modal-close', textContent: '×', title: 'Close' });
    xBtn.onclick = close;
    hdr.appendChild(xBtn);

    const body = $el('div', { className: 'mcp-modal-body' });
    if (conn.plugin_id) {
      body.appendChild(
        $el('p', {
          className: 'mcp-modal-hint',
          textContent:
            'From the “' +
            conn.plugin_id +
            '” plugin. Enter the values below to finish connecting it.',
        }),
      );
    }
    if (conn.connect_error) {
      body.appendChild(
        $el('p', {
          className: 'mcp-modal-hint',
          style: 'color:#b3261e',
          textContent: conn.connect_error,
        }),
      );
    }

    // missing_secrets is already a flat list of variable names, resolved
    // server-side by marketplace.installer._missing_secrets_for_server —
    // build placeholder-field entries directly from it rather than
    // re-detecting {VAR} substrings client-side (the "declared as an empty
    // string" convention has no {VAR} substring to find in the first place).
    const placeholders = (conn.missing_secrets || []).map(function (name) {
      return {
        key: name,
        varName: name,
        isSecret: /passw|secret|token|key|pwd|credential/i.test(name),
      };
    });
    const fields = buildPlaceholderFields(
      placeholders,
      'This server needs the following before it can connect:',
      {},
    );
    if (fields.container) body.appendChild(fields.container);

    const errorDiv = $el('div', {
      className: 'mcp-modal-hint',
      style: 'color:#b3261e;display:none',
    });
    body.appendChild(errorDiv);

    const footer = $el('div', { className: 'mcp-modal-footer' });
    const cancelBtn = $el('button', { textContent: 'Cancel', className: 'btn-secondary' });
    cancelBtn.onclick = close;
    const submitBtn = $el('button', { textContent: 'Connect', className: 'btn-primary' });

    submitBtn.onclick = function () {
      errorDiv.style.display = 'none';

      // Fix #2 frontend guard (2026-08-07 milestone adversarial review):
      // block submit if any required placeholder field is still blank —
      // mirrors the inline-error pattern already used for a server-side
      // failure below, rather than inventing a new validation UX. Without
      // this, a blank submission reaches the backend and (pre-fix #2 there)
      // could silently re-persist the original unresolved placeholder as if
      // it had been resolved.
      const vals = fields.getValues();
      const blankNames = placeholders
        .filter(function (p) {
          return !(vals[p.varName] || '').trim();
        })
        .map(function (p) {
          return p.varName;
        });
      if (blankNames.length) {
        errorDiv.textContent = 'Please fill in: ' + blankNames.join(', ');
        errorDiv.style.display = '';
        return;
      }

      // Fix #5 (2026-08-07 milestone adversarial review): lock keyed by
      // connection id, not by this invocation's closure — a per-invocation
      // `busy` flag can't stop a second concurrent request for the SAME
      // connection once the modal has been closed and reopened (a fresh
      // closure starts with busy=false again). No-op if already in flight.
      if (_pendingSecretCompletions.has(conn.id)) return;
      _pendingSecretCompletions.add(conn.id);
      submitBtn.disabled = true;
      submitBtn.textContent = 'Connecting…';

      fetch('/api/config/mcp/' + encodeURIComponent(conn.id) + '/complete-secrets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values: vals }),
      })
        .then(function (resp) {
          return resp.json();
        })
        .then(function (data) {
          _pendingSecretCompletions.delete(conn.id);
          if (overlay !== thisOverlay) return; // a different modal is now showing — don't touch it
          if (data && data.ok) {
            close();
            if (opts && typeof opts.onSuccess === 'function') opts.onSuccess(data);
          } else {
            errorDiv.textContent =
              (data && data.error) || 'Could not connect — check the values and try again.';
            errorDiv.style.display = '';
            submitBtn.disabled = false;
            submitBtn.textContent = 'Connect';
          }
        })
        .catch(function () {
          _pendingSecretCompletions.delete(conn.id);
          if (overlay !== thisOverlay) return;
          errorDiv.textContent = 'Network error — please try again.';
          errorDiv.style.display = '';
          submitBtn.disabled = false;
          submitBtn.textContent = 'Connect';
        });
    };
    footer.appendChild(cancelBtn);
    footer.appendChild(submitBtn);

    modal.appendChild(hdr);
    modal.appendChild(body);
    modal.appendChild(footer);
  };

  window._mcpModal = {
    openModal: openModal,
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
    renderGoogleWizard: renderGoogleWizard,
    $el: $el,
    clear: clear,
    close: close,
    get modal() {
      return modal;
    },
    get state() {
      return state;
    },
  };
})();
