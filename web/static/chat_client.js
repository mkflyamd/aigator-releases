/* ⚠️  POST-MVP — DO NOT MODIFY FOR MVP WORK ⚠️
 *
 * Currently used ONLY by the deferred agentic setup wizard
 * (web/static/extension_setup_modal.js). The wizard is not wired into the
 * default Add MCP flow for MVP — the legacy form modal mcp_add_modal.js is.
 * Do not modify this file unless the user has explicitly asked for post-MVP
 * wizard work.
 *
 * ─────────────────────────────────────────────────────────────────────
 * chat_client.js — Reusable self-contained chat component for AI Gator.
 *
 * Exposes window.ChatClient.
 *
 * Usage:
 *   const c = new ChatClient({
 *     container,                          // HTMLElement to render into
 *     endpoint: '/api/chat',              // POST endpoint (returns {task_id})
 *     contextId: 'ext_setup_abc123',      // context_id sent in POST body
 *     scopedSkill: '_extension_setup',    // active_skill / scoped_skill
 *     systemPromptSuffix: '...',          // appended to system prompt server-side
 *     onToolEvent: (e) => {},             // called for each poll event
 *   });
 *   c.send('Hello');
 *   c.pollEvents(sessionId);             // start polling /api/extensions/setup/events/…
 *   c.stop();                            // stop polling + cancel any active stream
 *
 * Security: all DOM construction uses createElement + textContent.
 *           innerHTML is NEVER used anywhere in this file.
 */
(function (global) {
  'use strict';

  /* ── tiny DOM helper ─────────────────────────────────────────────────── */
  function el(tag, className) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    return node;
  }

  /* ── ChatClient constructor ──────────────────────────────────────────── */
  function ChatClient(opts) {
    if (!opts || !opts.container) {
      throw new Error('ChatClient: opts.container is required');
    }
    this.container        = opts.container;
    this.endpoint         = opts.endpoint         || '/api/chat';
    this.contextId        = opts.contextId        || 'default';
    this.scopedSkill      = opts.scopedSkill      || null;
    this.systemPromptSuffix = opts.systemPromptSuffix || null;
    this.onToolEvent      = opts.onToolEvent      || function () {};

    this.history          = [];   // [{role, content}] accumulated for this session
    this._es              = null; // active EventSource
    this._eventTimer      = null; // setInterval handle for pollEvents
    this._busy            = false;
    this._lastStatusEl    = null; // status line from previous turn, cleared on next send

    this._buildDom();
  }

  /* ── DOM construction ────────────────────────────────────────────────── */
  ChatClient.prototype._buildDom = function () {
    /* Clear whatever was in the container */
    while (this.container.firstChild) {
      this.container.removeChild(this.container.firstChild);
    }

    /* Message list */
    this.$messages = el('div', 'cc-messages');

    /* Input row */
    var row = el('div', 'cc-input-row');

    this.$input = el('textarea', 'cc-input');
    this.$input.rows = 2;
    this.$input.placeholder = 'Type or paste here…';

    this.$send = el('button', 'cc-send');
    this.$send.textContent = 'Send';

    row.appendChild(this.$input);
    row.appendChild(this.$send);

    this.container.appendChild(this.$messages);
    this.container.appendChild(row);

    /* Event listeners */
    var self = this;

    this.$send.addEventListener('click', function () {
      self.send(self.$input.value);
    });

    this.$input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        self.send(self.$input.value);
      }
    });
  };

  /* ── Minimal markdown renderer (no innerHTML from user input — text nodes only) */
  function _renderMarkdown(container, text) {
    container.textContent = '';
    var lines = text.split('\n');
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      // Blank line → paragraph break (skip)
      if (!line.trim()) { i++; continue; }
      // Unordered list item
      if (/^[\*\-]\s+/.test(line)) {
        var ul = container.lastChild && container.lastChild.tagName === 'UL'
          ? container.lastChild : null;
        if (!ul) { ul = document.createElement('ul'); container.appendChild(ul); }
        var li = document.createElement('li');
        _applyInline(li, line.replace(/^[\*\-]\s+/, ''));
        ul.appendChild(li);
        i++; continue;
      }
      // Numbered list item
      if (/^\d+\.\s+/.test(line)) {
        var ol = container.lastChild && container.lastChild.tagName === 'OL'
          ? container.lastChild : null;
        if (!ol) { ol = document.createElement('ol'); container.appendChild(ol); }
        var li2 = document.createElement('li');
        _applyInline(li2, line.replace(/^\d+\.\s+/, ''));
        ol.appendChild(li2);
        i++; continue;
      }
      // Heading
      var hm = line.match(/^(#{1,3})\s+(.*)/);
      if (hm) {
        var h = document.createElement('h' + hm[1].length);
        _applyInline(h, hm[2]);
        container.appendChild(h);
        i++; continue;
      }
      // Regular paragraph
      var p = document.createElement('p');
      _applyInline(p, line);
      container.appendChild(p);
      i++;
    }
  }

  function _applyInline(node, text) {
    // Split on **bold** and `code` patterns
    var parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    parts.forEach(function (part) {
      if (/^\*\*(.+)\*\*$/.test(part)) {
        var b = document.createElement('strong');
        b.textContent = part.slice(2, -2);
        node.appendChild(b);
      } else if (/^`(.+)`$/.test(part)) {
        var code = document.createElement('code');
        code.textContent = part.slice(1, -1);
        node.appendChild(code);
      } else {
        node.appendChild(document.createTextNode(part));
      }
    });
  }

  /* ── Append a chat bubble ────────────────────────────────────────────── */
  ChatClient.prototype.appendBubble = function (role, text) {
    var b = el('div', 'cc-bubble cc-' + role);
    if (role === 'assistant' && text && text !== '…') {
      _renderMarkdown(b, text);
    } else {
      b.textContent = text;
    }
    this.$messages.appendChild(b);
    this.$messages.scrollTop = this.$messages.scrollHeight;
    return b;
  };

  /* ── Append an arbitrary element into the message flow ──────────────── */
  ChatClient.prototype.appendElement = function (node) {
    this.$messages.appendChild(node);
    this.$messages.scrollTop = this.$messages.scrollHeight;
  };

  /* ── Append a status line (tool activity) ────────────────────────────── */
  ChatClient.prototype._appendStatus = function (text) {
    var s = el('div', 'cc-status');
    s.textContent = text;
    this.$messages.appendChild(s);
    this.$messages.scrollTop = this.$messages.scrollHeight;
    return s;
  };

  /* ── Set disabled state on input + send button ───────────────────────── */
  ChatClient.prototype._setDisabled = function (disabled) {
    this.$input.disabled = disabled;
    this.$send.disabled  = disabled;
  };

  /* ── Send a message ──────────────────────────────────────────────────── */
  ChatClient.prototype.send = function (text) {
    text = (text || '').trim();
    if (!text || this._busy) return;

    this._busy = true;
    this._setDisabled(true);
    this.$input.value = '';

    /* Remove any leftover status line from the previous turn so it never
     * appears above the new user/assistant bubbles. */
    if (this._lastStatusEl && this._lastStatusEl.parentNode) {
      this._lastStatusEl.parentNode.removeChild(this._lastStatusEl);
    }
    this._lastStatusEl = null;

    /* Append user bubble */
    this.appendBubble('user', text);
    this.history.push({ role: 'user', content: text });

    /* Placeholder for assistant reply */
    var bubble = this.appendBubble('assistant', '…');
    var self   = this;

    /* Build POST body — compatible with the existing /api/chat schema.
     * Fields:
     *   message              — the user text
     *   history              — last 10 turns
     *   context_id           — namespaced per wizard session
     *   active_skill         — singular form (original field)
     *   active_skills        — array form (newer field)
     *   scoped_skill         — wizard scope (Task 5 extension)
     *   system_prompt_suffix — extra rules appended server-side (Task 5)
     *   active_channels      — not used by wizard; send empty array
     *   model                — inherit whatever the app has selected
     */
    var body = {
      message:               text,
      history:               this.history.slice(-10),
      context_id:            this.contextId,
      active_skill:          this.scopedSkill  || '',
      active_skills:         this.scopedSkill  ? [this.scopedSkill] : [],
      scoped_skill:          this.scopedSkill  || null,
      system_prompt_suffix:  this.systemPromptSuffix || null,
      active_channels:       [],
      model:                 (global._currentModel) || '',
    };

    fetch(this.endpoint, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    })
    .then(function (res) {
      if (!res.ok) {
        return res.text().then(function (t) {
          throw new Error('HTTP ' + res.status + ': ' + (t || 'error').slice(0, 200));
        });
      }
      return res.json();
    })
    .then(function (data) {
      var taskId = data.task_id;
      if (!taskId) throw new Error('No task_id in response');

      /* Stream reply via EventSource — same protocol as the main app */
      var accText = '';
      var statusEl = null;
      var es = new EventSource('/api/chat/stream/' + encodeURIComponent(taskId));
      self._es = es;

      es.onmessage = function (e) {
        var payload = e.data;

        if (payload === '[DONE]') {
          es.close();
          self._es = null;
          self.history.push({ role: 'assistant', content: accText });
          self._busy = false;
          self._setDisabled(false);
          self.$input.focus();
          return;
        }

        var msg;
        try { msg = JSON.parse(payload); } catch (_) { return; }

        if (typeof msg.token === 'string') {
          // Fix stream concatenation: if the previous chunk ended mid-word and
          // the new token starts a new word without a leading space, preserve it.
          // The actual space-after-period bug lives server-side; guard here too.
          var tok = msg.token;
          if (accText && tok && !/\s$/.test(accText) && /^[A-Z]/.test(tok)) {
            // heuristic: sentence boundary — ensure space exists
            var lastCh = accText[accText.length - 1];
            if (lastCh === '.' || lastCh === '!' || lastCh === '?') {
              tok = ' ' + tok;
            }
          }
          accText += tok;
          _renderMarkdown(bubble, accText);
          self.$messages.scrollTop = self.$messages.scrollHeight;
        } else if (typeof msg.thinking === 'string') {
          /* Thinking text — show italicised in the bubble */
          if (!accText) {
            bubble.textContent = '(' + msg.thinking.slice(0, 120) + '…)';
          }
        } else if (typeof msg.status === 'string') {
          /* Tool activity — update in place so it never floats above the bubble */
          if (statusEl) {
            statusEl.textContent = msg.status;
          } else {
            statusEl = self._appendStatus(msg.status);
            self._lastStatusEl = statusEl;
          }
        } else if (msg.toast) {
          /* Surface toast text — but suppress internal tool-dispatch errors
           * (Unknown tool, missing session_id) which are noise for the user. */
          var toastText = (typeof msg.toast === 'object' && msg.toast.message)
            ? String(msg.toast.message)
            : String(msg.toast);
          if (!/Unknown tool|session/i.test(toastText)) {
            self._appendStatus('⚠ ' + toastText);
          }
        }
        /* Ignore other event types (browser_confirm, browser_hitl, etc.) */
      };

      es.onerror = function () {
        if (es.readyState === EventSource.CLOSED) {
          /* Stream ended — if no content yet, show error */
          self._es = null;
          if (!accText) {
            bubble.textContent = '⚠ Connection lost. Please try again.';
          }
          self._busy = false;
          self._setDisabled(false);
        }
        /* If CONNECTING/OPEN, EventSource will auto-retry — do nothing */
      };
    })
    .catch(function (err) {
      bubble.textContent = '⚠ ' + err.message;
      self._busy = false;
      self._setDisabled(false);
    });
  };

  /* ── Poll /api/extensions/setup/events/{sessionId} ───────────────────── */
  ChatClient.prototype.pollEvents = function (sessionId, intervalMs) {
    if (!sessionId) return;
    var self = this;
    intervalMs = intervalMs || 700;

    this._eventTimer = setInterval(function () {
      fetch('/api/extensions/setup/events/' + encodeURIComponent(sessionId))
        .then(function (r) {
          if (!r.ok) return null;
          return r.json();
        })
        .then(function (data) {
          if (!data) return;
          var events = data.events || [];
          for (var i = 0; i < events.length; i++) {
            self.onToolEvent(events[i]);
          }
        })
        .catch(function () { /* swallow network errors silently */ });
    }, intervalMs);
  };

  /* ── Stop polling + close any open EventSource ───────────────────────── */
  ChatClient.prototype.stop = function () {
    if (this._eventTimer) {
      clearInterval(this._eventTimer);
      this._eventTimer = null;
    }
    if (this._es) {
      this._es.close();
      this._es = null;
    }
  };

  /* ── Expose on window ────────────────────────────────────────────────── */
  global.ChatClient = ChatClient;

})(window);
