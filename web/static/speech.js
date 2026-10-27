/* GatorSpeech — lightweight speech-to-text (dictation) for AI Gator.
 *
 * Audio is captured in the page (speech-capture.js), split into utterances at
 * pauses, and each utterance is transcribed locally by the backend
 * (POST /api/dictation/transcribe). No cloud service is involved.
 *
 * Degrades gracefully: if audio capture is unavailable, any wired mic button
 * hides itself so the UI is unchanged.
 */
(function () {
  'use strict';

  function isSupported() {
    return !!(window.GatorSpeechCapture && window.GatorSpeechCapture.isSupported());
  }

  // Dictation toggles on and stays on, so it ends itself after this long without speech.
  var IDLE_MS = 30000;

  // Only one dictation session may run at a time across the whole app.
  var _active = null; // { button }

  // Registry of wired mics so the global hotkey can target the focused field.
  var _registry = []; // { control, target, button }

  function _stopActive() {
    if (_active) {
      var btn = _active.button;
      if (btn && btn._gatorSpeechControl) {
        try {
          btn._gatorSpeechControl.stop();
        } catch (e) {
          /* ignore */
        }
      }
      _active = null;
    }
  }

  function _errorMessage(err) {
    if (err && (err.name === 'NotAllowedError' || err.name === 'SecurityError')) {
      return 'Microphone access is blocked. Allow mic permission to use dictation.';
    }
    if (err && err.name === 'NotFoundError') return 'No microphone found for dictation.';
    return 'Dictation failed: ' + ((err && err.message) || 'unknown error');
  }

  // POST one utterance (Int16Array, 16 kHz mono) and resolve to its text.
  function _transcribe(pcm) {
    function post() {
      return fetch('/api/dictation/transcribe', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/octet-stream',
          'X-CSRF-Token': window.__CSRF_TOKEN__ || '',
        },
        body: new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength),
      });
    }
    return post()
      .then(function (r) {
        if (r.status !== 403) return r;
        return fetch('/api/csrf')
          .then(function (c) {
            return c.json();
          })
          .then(function (j) {
            if (j && j.csrf_token) window.__CSRF_TOKEN__ = j.csrf_token;
            return post();
          });
      })
      .then(function (r) {
        if (r.ok) {
          return r.json().then(function (j) {
            return ((j && j.text) || '').trim();
          });
        }
        return r
          .json()
          .catch(function () {
            return {};
          })
          .then(function (j) {
            throw new Error((j && j.detail) || 'HTTP ' + r.status);
          });
      });
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
      try {
        el.selectionStart = el.selectionEnd = caret;
      } catch (e) {
        /* ignore */
      }
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
      } catch (e) {
        /* ignore */
      }
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
    if (!isSupported()) {
      button.style.display = 'none';
      return null;
    }
    if (button._gatorSpeechWired) return button._gatorSpeechControl;

    var session = null; // { capture, aborted, queue }
    var listening = false;
    var pending = 0; // utterances awaiting transcription
    var idleTimer = null;

    function _clearIdle() {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = null;
    }

    function _armIdle(s) {
      _clearIdle();
      idleTimer = setTimeout(function () {
        idleTimer = null;
        if (session !== s) return;
        _end(true);
        _notice('Dictation stopped after ' + IDLE_MS / 1000 + ' seconds without speech');
      }, IDLE_MS);
    }

    function _setUI(on) {
      button.classList.toggle('listening', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    }

    function _setBusy() {
      button.classList.toggle('transcribing', pending > 0);
    }

    function _enqueue(s, pcm) {
      pending++;
      _setBusy();
      s.queue = s.queue
        .then(function () {
          if (s.aborted) return null;
          return _transcribe(pcm).then(function (text) {
            if (s.aborted || !text) return;
            try {
              insertFn(text);
            } catch (err) {
              console.error('[GatorSpeech] insert failed', err);
            }
          });
        })
        .catch(function (err) {
          if (!s.aborted) _fail(s, err);
        })
        .then(function () {
          pending--;
          _setBusy();
        });
    }

    // Stops capture. deliver=true transcribes any phrase still being spoken;
    // deliver=false drops everything not yet inserted.
    function _end(deliver) {
      _clearIdle();
      listening = false;
      _setUI(false);
      var s = session;
      session = null;
      if (s) {
        if (s.capture) s.capture.stop(deliver);
        if (!deliver || !s.capture) s.aborted = true;
      }
      if (_active && _active.button === button) _active = null;
    }

    function _fail(s, err) {
      if (session === s) _end(false);
      else s.aborted = true;
      console.warn('[GatorSpeech] dictation error:', err);
      _toast(_errorMessage(err));
    }

    function start() {
      _stopActive();
      listening = true;
      _setUI(true);
      var s = { capture: null, aborted: false, queue: Promise.resolve() };
      session = s;
      _active = { button: button };
      _armIdle(s);
      window.GatorSpeechCapture.start(function (pcm) {
        _armIdle(s);
        _enqueue(s, pcm);
      })
        .then(function (cap) {
          if (s.aborted) {
            cap.stop(false);
            return;
          }
          s.capture = cap;
        })
        .catch(function (err) {
          _fail(s, err);
        });
    }

    function stop() {
      _end(true);
    }

    function abort() {
      _end(false);
    }

    button.addEventListener('mousedown', function (e) {
      e.preventDefault();
    });
    button.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (listening) stop();
      else start();
    });

    function toggle() {
      if (listening) stop();
      else start();
    }

    _setUI(false);
    button._gatorSpeechWired = true;
    button._gatorSpeechControl = {
      start: start,
      stop: stop,
      abort: abort,
      toggle: toggle,
      isListening: function () {
        return listening;
      },
      isSupported: true,
    };
    _registry.push({
      control: button._gatorSpeechControl,
      target: opts.target || null,
      button: button,
    });
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
      try {
        _registry[i].control.abort();
      } catch (e) {
        /* ignore */
      }
    }
    _active = null;
  }

  /* ── Stop dictation when the window is hidden or loses focus ──────────── */
  // stop() (not abort) so a phrase already spoken still lands in its field.
  function _stopOnFocusLoss() {
    var stopped = false;
    for (var i = 0; i < _registry.length; i++) {
      var c = _registry[i].control;
      try {
        if (c.isListening()) {
          c.stop();
          stopped = true;
        }
      } catch (e) {
        /* ignore */
      }
    }
    _active = null;
    if (stopped) _notice('Dictation stopped because the window lost focus');
  }

  if (!window.__gatorSpeechFocusHook) {
    window.__gatorSpeechFocusHook = true;
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) _stopOnFocusLoss();
    });
    // Focus moving into an iframe (widgets) also fires window blur, but the
    // document still reports focus then, so only a real loss of focus stops it.
    window.addEventListener('blur', function () {
      setTimeout(function () {
        if (!document.hasFocus()) _stopOnFocusLoss();
      }, 0);
    });
  }

  var SEND_SELECTOR = '#send-btn, .tp-compose-send, .tp-qt-send-btn, .cc-send';

  if (!window.__gatorSpeechSendHook) {
    window.__gatorSpeechSendHook = true;
    document.addEventListener(
      'submit',
      function () {
        stopAll();
      },
      true,
    );
    document.addEventListener(
      'click',
      function (e) {
        var t = e.target;
        if (t && t.closest && t.closest(SEND_SELECTOR)) stopAll();
      },
      true,
    );
  }

  // Non-blocking notice for expected stops (the error toast is a modal).
  function _notice(msg) {
    if (typeof window._showConnectivityToast === 'function') {
      try {
        window._showConnectivityToast(msg, 'info');
        return;
      } catch (e) {
        /* ignore */
      }
    }
    console.info('[GatorSpeech] ' + msg);
  }

  function _toast(msg) {
    if (typeof window._showAlert === 'function') {
      try {
        window._showAlert(msg, 'error');
        return;
      } catch (e) {
        /* ignore */
      }
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
      wire(btn, makeContentEditableInserter(input), {
        title: 'Dictate (Ctrl+Shift+Space)',
        target: input,
      });
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
