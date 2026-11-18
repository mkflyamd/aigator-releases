// web/static/skill-sharing.js
//
// Browser side of skill sharing. Owns the Share modal on Mine skill rows:
// publish through OneDrive, show the message the author copies and sends, or
// fall back to downloading the .skill file.
//
// Every dependency on the marketplace pane (CSRF-aware POST, the download
// function, alerts, refresh) is passed in, so this file has no globals of its
// own besides window.SkillSharing. Server text is only ever put in with
// textContent.
(function () {
  'use strict';

  var EMAIL_RE = /^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$/;
  var DEFAULT_ERROR = 'Could not share this skill. Try again.';

  // ── Pure helpers ─────────────────────────────────────────────────────────

  // Split on commas, semicolons and whitespace. Same address rule as the
  // backend (web/routes/skill_sharing.py).
  function parseEmails(text) {
    var emails = [];
    var bad = [];
    var seen = {};
    String(text == null ? '' : text)
      .split(/[,;\s]+/)
      .forEach(function (raw) {
        var item = raw.trim().toLowerCase();
        if (!item || seen[item]) return;
        seen[item] = true;
        (EMAIL_RE.test(item) ? emails : bad).push(item);
      });
    return { emails: emails, bad: bad };
  }

  function shareErrorText(resp, body) {
    var detail = body && body.detail;
    if (Array.isArray(detail)) return 'Check the email addresses and try again.';
    if (detail && typeof detail === 'object') {
      return typeof detail.message === 'string' && detail.message ? detail.message : DEFAULT_ERROR;
    }
    if (typeof detail === 'string' && detail) return detail;
    return DEFAULT_ERROR;
  }

  // ── Modal shell (shared by every modal in this file) ─────────────────────

  var _current = null; // the open modal, so a second one replaces it

  function _el(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function _button(label, primary) {
    var btn = _el('button', primary ? 'ap-card-btn primary' : 'ap-card-btn', label);
    btn.type = 'button';
    return btn;
  }

  // Builds the overlay, dialog, title, body and actions row; wires Escape and
  // the Tab loop. `setFocusables(list)` tells the Tab loop which elements the
  // current view offers. `close()` is idempotent and restores focus.
  function _openShell(titleText, onClose) {
    if (_current) _current.close();

    var prevFocus = document.activeElement;
    var titleId = 'ss-title-' + Date.now();
    var overlay = _el('div', 'mp-modal-overlay');
    var modal = _el('div', 'mp-modal ss-modal');
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', titleId);
    var heading = _el('div', 'mp-modal-title', titleText);
    heading.id = titleId;
    var body = _el('div', 'mp-modal-body');
    var actions = _el('div', 'mp-modal-actions');
    modal.appendChild(heading);
    modal.appendChild(body);
    modal.appendChild(actions);
    overlay.appendChild(modal);

    var shell = { overlay: overlay, heading: heading, body: body, actions: actions, closed: false };
    var focusables = [];

    shell.setFocusables = function (list) {
      focusables = list;
    };
    shell.close = function () {
      if (shell.closed) return;
      shell.closed = true;
      overlay.remove();
      document.removeEventListener('keydown', onKey, true);
      if (_current === shell) _current = null;
      if (prevFocus && typeof prevFocus.focus === 'function') prevFocus.focus();
      if (onClose) onClose();
    };

    function onKey(e) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        e.preventDefault();
        shell.close();
        return;
      }
      if (e.key === 'Tab' && focusables.length) {
        var first = focusables[0];
        var last = focusables[focusables.length - 1];
        var active = document.activeElement;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    document.body.appendChild(overlay);
    document.addEventListener('keydown', onKey, true);
    _current = shell;
    return shell;
  }

  function _clear(el) {
    el.textContent = '';
  }

  // ── Share modal ──────────────────────────────────────────────────────────

  function openShareModal(skillId, deps) {
    var shell = _openShell('Share "' + skillId + '"');
    showForm('');

    function showForm(initialText) {
      var pending = false;
      _clear(shell.body);
      _clear(shell.actions);
      shell.heading.textContent = 'Share "' + skillId + '"';

      var inputId = 'ss-people-' + Date.now();
      var label = _el('label', 'ss-label', 'Share with (work email addresses)');
      label.setAttribute('for', inputId);
      var input = _el('input', 'ss-input');
      input.id = inputId;
      input.type = 'text';
      input.value = initialText;
      input.setAttribute('autocomplete', 'off');
      input.setAttribute('placeholder', 'name@company.com, name2@company.com');
      var hint = _el(
        'p',
        'ss-hint',
        'They can use the skill but not change it. Nobody is emailed; you copy the message and send it yourself.',
      );
      var errorEl = _el('p', 'ss-error');
      errorEl.setAttribute('role', 'alert');
      var statusEl = _el('p', 'ss-status');
      statusEl.setAttribute('aria-live', 'polite');
      shell.body.appendChild(label);
      shell.body.appendChild(input);
      shell.body.appendChild(hint);
      shell.body.appendChild(errorEl);
      shell.body.appendChild(statusEl);

      var cancelBtn = _button('Cancel');
      var downloadBtn = _button('Download file instead');
      var shareBtn = _button('Share', true);
      shell.actions.appendChild(cancelBtn);
      shell.actions.appendChild(downloadBtn);
      shell.actions.appendChild(shareBtn);
      shell.setFocusables([input, cancelBtn, downloadBtn, shareBtn]);

      function setBusy(busy) {
        pending = busy;
        downloadBtn.disabled = busy;
        shareBtn.disabled = busy;
        statusEl.textContent = busy ? 'Sharing...' : '';
      }

      async function submit() {
        if (pending) return;
        errorEl.textContent = '';
        var parsed = parseEmails(input.value);
        if (!parsed.emails.length && !parsed.bad.length) {
          errorEl.textContent = 'Enter at least one work email address.';
          return;
        }
        if (parsed.bad.length) {
          errorEl.textContent = '"' + parsed.bad[0] + '" is not a valid email address.';
          return;
        }
        setBusy(true);
        var result;
        try {
          result = await deps.postJson('/api/skills/share/publish', {
            skill_id: skillId,
            people: parsed.emails,
          });
        } catch (err) {
          result = { resp: { ok: false }, body: null };
        }
        if (shell.closed) {
          // The user closed the modal while the request ran. If it went
          // through, the row should still show it as shared.
          if (result.resp && result.resp.ok && deps.refresh) deps.refresh();
          return;
        }
        setBusy(false);
        if (!result.resp || !result.resp.ok) {
          errorEl.textContent = shareErrorText(result.resp, result.body);
          return;
        }
        showResult(result.body || {}, parsed.emails);
      }

      cancelBtn.addEventListener('click', function () {
        shell.close();
      });
      downloadBtn.addEventListener('click', function () {
        shell.close();
        deps.downloadSkill(skillId);
      });
      shareBtn.addEventListener('click', submit);
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          submit();
        }
      });
      input.focus();
    }

    function showResult(data, emails) {
      _clear(shell.body);
      _clear(shell.actions);
      var version = data.version;
      shell.heading.textContent = data.reused
        ? 'Already shared, no changes since version ' + version
        : 'Shared as version ' + version;

      shell.body.appendChild(_el('p', 'ss-access', 'Access granted to ' + emails.join(', ')));
      var area = _el('textarea', 'ss-message');
      area.readOnly = true;
      area.value = data.message || '';
      area.setAttribute('rows', '8');
      area.setAttribute('aria-label', 'Message to send');
      shell.body.appendChild(area);
      var note = _el('p', 'ss-hint', 'Nothing has been sent. Paste this message into an email or chat yourself.');
      shell.body.appendChild(note);
      var copyStatus = _el('p', 'ss-status');
      copyStatus.setAttribute('aria-live', 'polite');
      shell.body.appendChild(copyStatus);

      function copy(btn, text, doneLabel) {
        var original = btn.textContent;
        var clip = typeof navigator !== 'undefined' && navigator.clipboard;
        if (!clip || typeof clip.writeText !== 'function') {
          copyStatus.textContent = 'Could not copy. Select the text and copy it.';
          return;
        }
        Promise.resolve()
          .then(function () {
            return clip.writeText(text);
          })
          .then(
            function () {
              copyStatus.textContent = '';
              btn.textContent = doneLabel;
              setTimeout(function () {
                btn.textContent = original;
              }, 2000);
            },
            function () {
              copyStatus.textContent = 'Could not copy. Select the text and copy it.';
            },
          );
      }

      var copyMsgBtn = _button('Copy message', true);
      var copyLinkBtn = _button('Copy link');
      var doneBtn = _button('Done');
      copyMsgBtn.addEventListener('click', function () {
        copy(copyMsgBtn, data.message || '', 'Copied');
      });
      copyLinkBtn.addEventListener('click', function () {
        copy(copyLinkBtn, data.link || '', 'Copied');
      });
      doneBtn.addEventListener('click', function () {
        shell.close();
        if (deps.refresh) deps.refresh();
      });

      var focusables = [area, copyMsgBtn, copyLinkBtn];
      shell.actions.appendChild(copyMsgBtn);
      shell.actions.appendChild(copyLinkBtn);
      if (typeof data.web_url === 'string' && data.web_url.indexOf('https://') === 0) {
        var open = _el('a', 'ap-card-btn', 'Open in OneDrive');
        open.href = data.web_url;
        open.target = '_blank';
        open.rel = 'noopener';
        shell.actions.appendChild(open);
        focusables.push(open);
      }
      shell.actions.appendChild(doneBtn);
      focusables.push(doneBtn);
      shell.setFocusables(focusables);
      copyMsgBtn.focus();
    }

    return shell;
  }

  var api = {
    openShareModal: openShareModal,
    parseEmails: parseEmails,
    shareErrorText: shareErrorText,
  };

  if (typeof window !== 'undefined') window.SkillSharing = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
