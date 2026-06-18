/* GatorSpeech — lightweight speech-to-text (dictation) for AI Gator.
 *
 * Uses the browser's built-in Web Speech API (SpeechRecognition). No
 * dependencies, no API keys, no server calls — recognition is handled by the
 * browser. Works in Chrome/Edge and the packaged tray app (which opens the UI
 * in the default system browser).
 *
 * Degrades gracefully: if the API is unavailable, any wired mic button hides
 * itself so the UI is unchanged on unsupported browsers (e.g. Firefox).
 */
(function () {
  'use strict';

  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  function isSupported() { return !!SR; }

  // Only one recognition session may run at a time across the whole app.
  var _active = null; // { rec, button }

  // Registry of wired mics so the global hotkey can target the focused field.
  var _registry = []; // { control, target, button }

  function _stopActive() {
    if (_active) {
      // Trigger the explicit-stop path in whichever wire() instance owns this mic
      var btn = _active.button;
      if (btn && btn._gatorSpeechControl) {
        try { btn._gatorSpeechControl.stop(); } catch (e) { /* ignore */ }
      } else if (_active.rec) {
        try { _active.rec.abort(); } catch (e) { /* ignore */ }
      }
      _active = null;
    }
  }

  // Add a leading space before a dictated chunk unless we're at the start or
  // right after whitespace / an opening bracket.
  function _needsLeadingSpace(prevChar) {
    if (!prevChar) return false;
    return !/\s/.test(prevChar) && '([{""\'-'.indexOf(prevChar) === -1;
  }

  /* ── Inserters for the supported field kinds ───────────────────────── */

  // <textarea> / <input>
  function makeFieldInserter(el) {
    return function (text) {
      var start = el.selectionStart != null ? el.selectionStart : el.value.length;
      var end = el.selectionEnd != null ? el.selectionEnd : el.value.length;
      var prev = el.value.slice(0, start).slice(-1);
      var ins = (_needsLeadingSpace(prev) ? ' ' : '') + text;
      el.value = el.value.slice(0, start) + ins + el.value.slice(end);
      var caret = start + ins.length;
      try { el.selectionStart = el.selectionEnd = caret; } catch (e) { /* ignore */ }
      el.dispatchEvent(new Event('input', { bubbles: true }));
    };
  }

  // contenteditable host (e.g. the Gator chat input)
  function makeContentEditableInserter(el) {
    return function (text) {
      el.focus();
      var sel = window.getSelection();
      if (!sel.rangeCount || !el.contains(sel.anchorNode)) {
        var r = document.createRange();
        r.selectNodeContents(el);
        r.collapse(false);
        sel.removeAllRanges();
        sel.addRange(r);
      }
      var prevChar = '';
      try {
        var probe = sel.getRangeAt(0).cloneRange();
        probe.collapse(true);
        probe.setStart(el, 0);
        prevChar = probe.toString().slice(-1);
      } catch (e) { /* ignore */ }
      var ins = (_needsLeadingSpace(prevChar) ? ' ' : '') + text;
      // execCommand keeps the app's own input listeners (placeholder, guides,
      // chip parsing) firing, so the chat box behaves as if typed.
      document.execCommand('insertText', false, ins);
    };
  }

  // Quill editor instance (or a getter returning one)
  function makeQuillInserter(getQuill) {
    return function (text) {
      var q = typeof getQuill === 'function' ? getQuill() : getQuill;
      if (!q) return;
      var range = q.getSelection(true) || { index: q.getLength(), length: 0 };
      var prevChar = range.index > 0 ? q.getText(range.index - 1, 1) : '';
      var ins = (_needsLeadingSpace(prevChar) ? ' ' : '') + text;
      if (range.length) q.deleteText(range.index, range.length);
      q.insertText(range.index, ins);
      q.setSelection(range.index + ins.length, 0);
    };
  }

  /* ── Wire a mic button to dictate into a target ────────────────────── */
  function wire(button, insertFn, opts) {
    opts = opts || {};
    if (!button) return null;
    if (!isSupported()) { button.style.display = 'none'; return null; }
    if (button._gatorSpeechWired) return button._gatorSpeechControl;

    var rec = null;
    var listening = false;
    var _userStopped = false;  // true only when user explicitly stops

    function _setUI(on) {
      button.classList.toggle('listening', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    }

    function _startRec() {
      rec = new SR();
      rec.lang = opts.lang || navigator.language || 'en-US';
      rec.continuous = true;
      rec.interimResults = false;
      rec.maxAlternatives = 1;

      rec.onresult = function (e) {
        for (var i = e.resultIndex; i < e.results.length; i++) {
          var res = e.results[i];
          if (res && res.isFinal) {
            var t = ((res[0] && res[0].transcript) || '').trim();
            if (t) {
              try { insertFn(t); }
              catch (err) { console.error('[GatorSpeech] insert failed', err); }
            }
          }
        }
      };
      rec.onerror = function (e) {
        if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
          _userStopped = true;
          listening = false;
          _setUI(false);
          if (_active && _active.rec === rec) _active = null;
          _toast('Microphone access is blocked. Allow mic permission in your browser to use dictation.');
        } else if (e.error === 'aborted') {
          // intentional abort — onend will handle cleanup
        } else if (e.error === 'no-speech') {
          // browser fires no-speech then onend — let onend restart if still active
        } else {
          console.warn('[GatorSpeech] recognition error:', e.error);
        }
      };
      rec.onend = function () {
        // Auto-restart on natural pause/timeout unless user explicitly stopped.
        if (!_userStopped && listening) {
          try {
            rec = null;
            _startRec();
            return;
          } catch (err) {
            console.warn('[GatorSpeech] restart failed', err);
          }
        }
        listening = false;
        _setUI(false);
        if (_active && _active.rec === rec) _active = null;
        rec = null;
      };

      try {
        rec.start();
      } catch (err) {
        console.error('[GatorSpeech] start failed', err);
        listening = false;
        _setUI(false);
      }
    }

    function start() {
      _stopActive();
      _userStopped = false;
      listening = true;
      _setUI(true);
      _active = { rec: null, button: button };
      _startRec();
      // Keep _active.rec in sync after _startRec assigns rec
      _active.rec = rec;
    }

    function stop() {
      _userStopped = true;
      listening = false;
      _setUI(false);
      if (rec) { try { rec.abort(); } catch (e) { /* ignore */ } rec = null; }
      if (_active && _active.button === button) _active = null;
    }

    button.addEventListener('mousedown', function (e) { e.preventDefault(); });
    button.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (listening) stop(); else start();
    });

    function toggle() { if (listening) stop(); else start(); }

    _setUI(false);
    button._gatorSpeechWired = true;
    button._gatorSpeechControl = { start: start, stop: stop, toggle: toggle, isSupported: true };
    _registry.push({ control: button._gatorSpeechControl, target: opts.target || null, button: button });
    return button._gatorSpeechControl;
  }

  /* ── Global hotkey: Ctrl+Shift+Space toggles dictation ─────────────── */
  function _findEntryForFocus() {
    var ae = document.activeElement;
    if (ae) {
      for (var i = 0; i < _registry.length; i++) {
        var t = _registry[i].target;
        if (t && (t === ae || (t.contains && t.contains(ae)))) return _registry[i];
      }
    }
    for (var j = 0; j < _registry.length; j++) {
      if (_registry[j].button && _registry[j].button.id === 'gator-mic-btn') return _registry[j];
    }
    return _registry[0] || null;
  }

  function _handleHotkey(e) {
    var isSpace = e.code === 'Space' || e.key === ' ' || e.key === 'Spacebar';
    if (!isSpace || !e.ctrlKey || !e.shiftKey || e.altKey || e.metaKey) return;
    if (!isSupported()) return;
    var entry = _findEntryForFocus();
    if (!entry) return;
    e.preventDefault();
    e.stopPropagation();
    entry.control.toggle();
  }

  if (!window.__gatorSpeechHotkey) {
    window.__gatorSpeechHotkey = true;
    document.addEventListener('keydown', _handleHotkey, true);
  }

  /* ── Stop dictation whenever a message is sent ─────────────────────── */
  function stopAll() {
    for (var i = 0; i < _registry.length; i++) {
      try { _registry[i].control.stop(); } catch (e) { /* ignore */ }
    }
    _stopActive();
  }

  var SEND_SELECTOR = '#send-btn, .tp-compose-send, .tp-qt-send-btn, .cc-send';

  if (!window.__gatorSpeechSendHook) {
    window.__gatorSpeechSendHook = true;
    document.addEventListener('submit', function () { stopAll(); }, true);
    document.addEventListener('click', function (e) {
      var t = e.target;
      if (t && t.closest && t.closest(SEND_SELECTOR)) stopAll();
    }, true);
  }

  function _toast(msg) {
    if (typeof window._showAlert === 'function') {
      try { window._showAlert(msg, 'error'); return; } catch (e) { /* ignore */ }
    }
    console.warn('[GatorSpeech] ' + msg);
  }

  /* ── Standard mic button element ───────────────────────────────────── */
  var MIC_SVG =
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>' +
    '<path d="M19 10v2a7 7 0 0 1-14 0v-2"/>' +
    '<line x1="12" y1="19" x2="12" y2="23"/>' +
    '<line x1="8" y1="23" x2="16" y2="23"/></svg>';

  function createMicButton(className) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'gator-mic-btn' + (className ? ' ' + className : '');
    b.innerHTML = MIC_SVG;
    b.title = 'Dictate (speech to text)';
    b.setAttribute('aria-label', 'Dictate with speech to text');
    return b;
  }

  /* ── Self-init for the main Gator chat input ───────────────────────── */
  function _initGatorChat() {
    var input = document.getElementById('chat-input');
    var btn = document.getElementById('gator-mic-btn');
    if (input && btn) {
      wire(btn, makeContentEditableInserter(input), { title: 'Dictate (Ctrl+Shift+Space)', target: input });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _initGatorChat);
  } else {
    _initGatorChat();
  }

  window.GatorSpeech = {
    isSupported: isSupported,
    wire: wire,
    stopAll: stopAll,
    createMicButton: createMicButton,
    MIC_SVG: MIC_SVG,
    makeFieldInserter: makeFieldInserter,
    makeContentEditableInserter: makeContentEditableInserter,
    makeQuillInserter: makeQuillInserter,
  };
})();
