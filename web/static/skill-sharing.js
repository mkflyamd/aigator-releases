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
  var REVIEW_ERROR = 'Could not open this share link. Try again.';

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

  function shareErrorText(resp, body, fallback) {
    var none = fallback || DEFAULT_ERROR;
    var detail = body && body.detail;
    if (Array.isArray(detail)) return 'Check the email addresses and try again.';
    if (detail && typeof detail === 'object') {
      return typeof detail.message === 'string' && detail.message ? detail.message : none;
    }
    if (typeof detail === 'string' && detail) return detail;
    return none;
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
    var btn = _el('button', primary ? 'mp-btn mp-btn-primary' : 'mp-btn mp-btn-cancel', label);
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
      var enabled = focusables.filter(function (el) {
        return !el.disabled;
      });
      if (e.key === 'Tab' && enabled.length) {
        var first = enabled[0];
        var last = enabled[enabled.length - 1];
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
      downloadBtn.className = 'mp-btn ss-link-btn';
      var shareBtn = _button('Share', true);
      shell.actions.appendChild(downloadBtn);
      shell.actions.appendChild(cancelBtn);
      shell.actions.appendChild(shareBtn);
      shell.setFocusables([input, downloadBtn, cancelBtn, shareBtn]);

      function setBusy(busy) {
        pending = busy;
        downloadBtn.disabled = busy;
        shareBtn.disabled = busy;
        statusEl.textContent = busy ? 'Sharing...' : '';
      }

      async function submit() {
        if (pending) return;
        errorEl.textContent = '';
        input.setAttribute('aria-invalid', 'false');
        var parsed = parseEmails(input.value);
        var invalid = '';
        if (!parsed.emails.length && !parsed.bad.length) invalid = 'Enter at least one work email address.';
        else if (parsed.bad.length) invalid = '"' + parsed.bad[0] + '" is not a valid email address.';
        if (invalid) {
          errorEl.textContent = invalid;
          input.setAttribute('aria-invalid', 'true');
          input.focus();
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
      area.setAttribute('rows', '4');
      area.setAttribute('aria-label', 'Message to send');
      shell.body.appendChild(area);
      var note = _el('p', 'ss-hint', 'Nothing has been sent. Paste this message into an email or chat yourself.');
      shell.body.appendChild(note);
      var copyStatus = _el('p', 'ss-status');
      copyStatus.setAttribute('aria-live', 'polite');
      shell.body.appendChild(copyStatus);

      // The label is captured once, here, so a second click while "Copied" is
      // showing cannot mistake "Copied" for the original label.
      function wireCopy(btn, text, doneLabel) {
        var original = btn.textContent;
        btn.addEventListener('click', function () {
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
        });
      }

      var copyMsgBtn = _button('Copy message', true);
      copyMsgBtn.className += ' ss-copy';
      var doneBtn = _button('Done');
      wireCopy(copyMsgBtn, data.message || '', 'Copied');
      doneBtn.addEventListener('click', function () {
        shell.close();
        if (deps.refresh) deps.refresh();
      });

      // Secondary actions sit on the left, Done and the main action on the
      // right, so the primary button is last like every other modal.
      var focusables = [area];
      if (typeof data.link === 'string' && data.link) {
        var copyLinkBtn = _button('Copy link');
        copyLinkBtn.className += ' ss-copy';
        wireCopy(copyLinkBtn, data.link, 'Copied');
        shell.actions.appendChild(copyLinkBtn);
        focusables.push(copyLinkBtn);
      }
      if (typeof data.web_url === 'string' && data.web_url.indexOf('https://') === 0) {
        var open = _el('a', 'mp-btn mp-btn-cancel', 'Open in OneDrive');
        open.href = data.web_url;
        open.target = '_blank';
        open.rel = 'noopener';
        shell.actions.appendChild(open);
        focusables.push(open);
      }
      shell.actions.appendChild(_el('div', 'ss-spacer'));
      shell.actions.appendChild(doneBtn);
      shell.actions.appendChild(copyMsgBtn);
      focusables.push(doneBtn, copyMsgBtn);
      shell.setFocusables(focusables);
      copyMsgBtn.focus();
    }

    return shell;
  }

  // ── Review and install from a share link ─────────────────────────────────

  var COLLISION_TEXT = {
    mine: 'You already have a skill of your own with this name. Rename or remove it to install this one.',
    installed: 'A skill with this name is already installed. Remove it to install this one.',
    native: 'This name is used by a built-in skill.',
  };

  // First aigator://share?d=... token in pasted text, or ''. The payload is
  // base64url, so punctuation around the link in a sentence is left out.
  function extractLink(text) {
    var m = /aigator:\/\/share\?d=[A-Za-z0-9_-]+/.exec(String(text == null ? '' : text));
    return m ? m[0] : '';
  }

  // Resolves to the open modal, or null when the review failed (an alert is
  // shown and nothing opens). Nothing is installed until Install is clicked.
  async function openLinkReview(link, deps) {
    var result;
    try {
      result = await deps.postJson('/api/skills/share/review', { link: link });
    } catch (err) {
      result = { resp: { ok: false }, body: null };
    }
    if (!result || !result.resp || !result.resp.ok || !result.body) {
      deps.showAlert(shareErrorText(result && result.resp, result && result.body, REVIEW_ERROR), 'error');
      return null;
    }
    var review = result.body;
    var title = String(review.title || review.skill_id || 'skill');
    var shell = _openShell('Review "' + title + '"');

    var collision = COLLISION_TEXT[review.collision];
    if (review.collision && !collision) collision = 'A skill with this name already exists.';
    if (collision) shell.body.appendChild(_el('p', 'mp-modal-compat-risk ss-collision', collision));
    if (review.description) shell.body.appendChild(_el('p', 'ss-desc', String(review.description)));
    var by = 'Shared by ' + (review.author || 'unknown') + ', version ' + review.version;
    shell.body.appendChild(_el('p', 'ss-meta', by));
    if (typeof review.latest === 'number' && typeof review.version === 'number' && review.latest > review.version) {
      shell.body.appendChild(_el('p', 'ss-meta', 'Newer version ' + review.latest + ' is available. Ask ' + (review.author || 'the sender') + ' for the latest link.'));
    }
    shell.body.appendChild(
      _el(
        'p',
        review.has_scripts ? 'ss-meta mp-modal-community-warn' : 'ss-meta',
        'Contains scripts: ' + (review.has_scripts ? 'yes' : 'no'),
      ),
    );
    if (deps.appendPermissionList) deps.appendPermissionList(shell.body, review.summary);

    var detailsBtn = _el('button', 'ss-details-toggle', 'Details');
    detailsBtn.type = 'button';
    detailsBtn.setAttribute('aria-expanded', 'false');
    var fingerprint = _el('p', 'ss-fingerprint', 'Fingerprint: ' + (review.digest || ''));
    fingerprint.hidden = true;
    detailsBtn.addEventListener('click', function () {
      fingerprint.hidden = !fingerprint.hidden;
      detailsBtn.setAttribute('aria-expanded', fingerprint.hidden ? 'false' : 'true');
    });
    shell.body.appendChild(detailsBtn);
    shell.body.appendChild(fingerprint);

    shell.body.appendChild(_el('p', 'ss-hint', 'Nothing is installed until you choose Install.'));
    var errorEl = _el('p', 'ss-error');
    errorEl.setAttribute('role', 'alert');
    shell.body.appendChild(errorEl);

    var cancelBtn = _button('Cancel');
    var installBtn = _button('Install', true);
    installBtn.disabled = !!collision;
    if (collision) installBtn.title = 'Resolve the name clash above to install';
    shell.actions.appendChild(cancelBtn);
    shell.actions.appendChild(installBtn);
    shell.setFocusables([detailsBtn, cancelBtn, installBtn]);

    var pending = false;
    async function install() {
      if (pending || installBtn.disabled) return;
      pending = true;
      installBtn.disabled = true;
      errorEl.textContent = '';
      var out;
      try {
        out = await deps.postJson('/api/skills/share/install', {
          link: link,
          version: review.version,
          digest: review.digest,
        });
      } catch (err) {
        out = { resp: { ok: false }, body: null };
      }
      pending = false;
      var ok = out && out.resp && out.resp.ok && out.body && out.body.ok !== false;
      if (!ok) {
        if (shell.closed) return;
        installBtn.disabled = false;
        errorEl.textContent = out && out.body
          ? (deps.errorMessage ? deps.errorMessage(out.body) : shareErrorText(out.resp, out.body))
          : 'Could not install this skill. Try again.';
        return;
      }
      deps.showAlert('Installed "' + title + '".', 'success');
      if (deps.onInstalled) deps.onInstalled(out.body, review);
      if (deps.refresh) deps.refresh();
      shell.close();
    }

    cancelBtn.addEventListener('click', function () {
      shell.close();
    });
    installBtn.addEventListener('click', install);
    (collision ? cancelBtn : installBtn).focus();
    return shell;
  }

  var api = {
    openShareModal: openShareModal,
    openLinkReview: openLinkReview,
    extractLink: extractLink,
    parseEmails: parseEmails,
    shareErrorText: shareErrorText,
  };

  if (typeof window !== 'undefined') window.SkillSharing = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
