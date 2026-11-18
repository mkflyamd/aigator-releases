// web/static/skill-sharing.js
//
// Browser side of skill sharing. Owns the Share modal on Mine skill rows:
// look up people, publish through OneDrive, then copy the message or open a
// draft of it (email, Teams or Slack) for approval; or fall back to downloading
// the .skill file.
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
  // current view offers. `onEscape()` may return true to claim the key (an
  // open suggestion list closes before the modal does). `closeBtn` is the X in
  // the top corner, hidden until a view asks for it. `close()` is idempotent
  // and restores focus.
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
    var closeBtn = _el('button', 'ss-close', '×');
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.hidden = true;
    var body = _el('div', 'mp-modal-body');
    var actions = _el('div', 'mp-modal-actions');
    modal.appendChild(closeBtn);
    modal.appendChild(heading);
    modal.appendChild(body);
    modal.appendChild(actions);
    overlay.appendChild(modal);

    var shell = {
      overlay: overlay,
      heading: heading,
      body: body,
      actions: actions,
      closeBtn: closeBtn,
      closed: false,
      onEscape: null,
    };
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
    closeBtn.addEventListener('click', function () {
      shell.close();
    });

    function onKey(e) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        e.preventDefault();
        if (shell.onEscape && shell.onEscape()) return;
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

  // ── People lookup ────────────────────────────────────────────────────────

  var SUGGEST_MIN = 2;
  var SUGGEST_MAX = 6;
  var SUGGEST_DELAY = 200;

  function _lastToken(text) {
    return /[^,;\s]*$/.exec(text)[0];
  }

  // Suggests people for the address being typed (the text after the last
  // separator). `deps.searchPeople(query)` resolves to [{name, email}], the
  // same /api/people/search lookup the prompt bar's @ mentions use. Without
  // that dependency the field is a plain text input.
  function _attachPeopleLookup(input, list, deps) {
    var rows = [];
    var active = -1;
    var seq = 0;
    var timer = null;
    var cache = {};
    var enabled = typeof deps.searchPeople === 'function';

    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', 'Matching people');
    list.hidden = true;
    if (enabled) {
      input.setAttribute('role', 'combobox');
      input.setAttribute('aria-autocomplete', 'list');
      input.setAttribute('aria-expanded', 'false');
      input.setAttribute('aria-controls', list.id);
    }

    function isOpen() {
      return !list.hidden;
    }

    function close() {
      list.hidden = true;
      _clear(list);
      rows = [];
      active = -1;
      if (enabled) {
        input.setAttribute('aria-expanded', 'false');
        input.setAttribute('aria-activedescendant', '');
      }
    }

    function setActive(i) {
      active = i;
      rows.forEach(function (row, idx) {
        var on = idx === i;
        row.el.className = on ? 'ss-suggest-item is-active' : 'ss-suggest-item';
        row.el.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      input.setAttribute('aria-activedescendant', i >= 0 ? rows[i].el.id : '');
    }

    function choose(person) {
      seq += 1;
      clearTimeout(timer);
      input.value = input.value.replace(/[^,;\s]*$/, '') + person.email.toLowerCase() + ', ';
      close();
      input.focus();
    }

    function show(people, token) {
      var taken = parseEmails(input.value.slice(0, input.value.length - token.length)).emails;
      var shown = people
        .filter(function (p) {
          return p && typeof p.email === 'string' && p.email && taken.indexOf(p.email.toLowerCase()) === -1;
        })
        .slice(0, SUGGEST_MAX);
      if (!shown.length) {
        close();
        return;
      }
      _clear(list);
      rows = shown.map(function (p, i) {
        var li = _el('li', 'ss-suggest-item');
        li.id = list.id + '-' + i;
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', 'false');
        var name = p.name && p.name !== p.email ? p.name : '';
        if (name) li.appendChild(_el('span', 'ss-suggest-name', name));
        li.appendChild(_el('span', 'ss-suggest-email', p.email));
        // mousedown, not click: the input keeps focus, so it does not blur
        // (and close the list) before the choice lands.
        li.addEventListener('mousedown', function (e) {
          e.preventDefault();
          choose(p);
        });
        list.appendChild(li);
        return { el: li, person: p };
      });
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      setActive(-1);
    }

    async function run(token, mine) {
      var people = cache[token];
      if (!people) {
        try {
          people = await deps.searchPeople(token);
        } catch (err) {
          people = [];
        }
        if (!Array.isArray(people)) people = [];
        cache[token] = people;
      }
      if (mine !== seq) return;
      show(people, token);
    }

    function onInput() {
      clearTimeout(timer);
      seq += 1;
      var mine = seq;
      var token = _lastToken(input.value);
      if (token.length < SUGGEST_MIN) {
        close();
        return;
      }
      timer = setTimeout(function () {
        run(token, mine);
      }, SUGGEST_DELAY);
    }

    // True when the key was used by the list and the field must not act on it.
    function handleKey(e) {
      if (!isOpen() || !rows.length) return false;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        var next = active + (e.key === 'ArrowDown' ? 1 : -1);
        if (next < 0) next = rows.length - 1;
        if (next >= rows.length) next = 0;
        setActive(next);
        return true;
      }
      if (e.key === 'Enter' && active >= 0) {
        e.preventDefault();
        choose(rows[active].person);
        return true;
      }
      return false;
    }

    if (enabled) {
      input.addEventListener('input', onInput);
      input.addEventListener('blur', close);
    }
    return { handleKey: handleKey, close: close, isOpen: isOpen };
  }

  // ── Share modal ──────────────────────────────────────────────────────────

  var CHANNELS = [
    { id: 'email', label: 'Email', draft: 'an email draft' },
    { id: 'teams', label: 'Teams', draft: 'a Teams message draft' },
    { id: 'slack', label: 'Slack', draft: 'a Slack message draft' },
  ];

  function _channel(id) {
    return CHANNELS.filter(function (c) {
      return c.id === id;
    })[0];
  }

  function _ungrantedNotice(ungranted) {
    var one = ungranted.length === 1;
    var notice = _el('div', 'ss-notice');
    notice.setAttribute('role', 'status');
    notice.appendChild(_el('p', 'ss-notice-title', 'Access was not granted for ' + ungranted.join(', ')));
    notice.appendChild(
      _el(
        'p',
        'ss-notice-text',
        (one ? 'OneDrive would not let this person open the skill' : 'OneDrive would not let these people open the skill') +
          ', usually because they are outside your organization. Send the message anyway, then add ' +
          (one ? 'them' : 'each of them') +
          ' in OneDrive (Open in OneDrive, then Share) so the link works for them.',
      ),
    );
    return notice;
  }

  function openShareModal(skillId, deps) {
    var published = false;
    var channel = 'email';
    var shell = _openShell('Share "' + skillId + '"', function () {
      if (published && deps.refresh) deps.refresh();
    });
    showForm('');

    function showForm(initialText) {
      var pending = false;
      _clear(shell.body);
      _clear(shell.actions);
      shell.heading.textContent = 'Share "' + skillId + '"';

      var stamp = Date.now();
      var inputId = 'ss-people-' + stamp;
      var label = _el('label', 'ss-label', 'Share with');
      label.setAttribute('for', inputId);
      var field = _el('div', 'ss-field');
      var input = _el('input', 'ss-input');
      input.id = inputId;
      input.type = 'text';
      input.value = initialText;
      input.setAttribute('autocomplete', 'off');
      input.setAttribute('placeholder', 'Search by name or enter work email addresses');
      var suggest = _el('ul', 'ss-suggest');
      suggest.id = 'ss-suggest-' + stamp;
      field.appendChild(input);
      field.appendChild(suggest);
      var lookup = _attachPeopleLookup(input, suggest, deps);
      shell.onEscape = function () {
        if (!lookup.isOpen()) return false;
        lookup.close();
        return true;
      };

      var viaId = 'ss-via-' + stamp;
      var viaLabel = _el('span', 'ss-label', 'Tell them by');
      viaLabel.id = viaId;
      var seg = _el('div', 'ss-seg');
      seg.setAttribute('role', 'radiogroup');
      seg.setAttribute('aria-labelledby', viaId);
      var hint = _el('p', 'ss-hint');
      var segBtns = CHANNELS.map(function (c) {
        var b = _el('button', 'ss-seg-btn', c.label);
        b.type = 'button';
        b.setAttribute('role', 'radio');
        seg.appendChild(b);
        return { id: c.id, el: b };
      });
      var focusOrder = function () {};
      function pick(id, focus) {
        channel = id;
        segBtns.forEach(function (s) {
          var on = s.id === id;
          s.el.className = on ? 'ss-seg-btn is-selected' : 'ss-seg-btn';
          s.el.setAttribute('aria-checked', on ? 'true' : 'false');
          s.el.setAttribute('tabindex', on ? '0' : '-1');
          if (on && focus) s.el.focus();
        });
        focusOrder();
        hint.textContent =
          'They can use the skill but not change it. Nothing is sent until you approve ' + _channel(id).draft + '.';
      }
      segBtns.forEach(function (s, i) {
        s.el.addEventListener('click', function () {
          pick(s.id, false);
        });
        s.el.addEventListener('keydown', function (e) {
          var step = 0;
          if (e.key === 'ArrowRight' || e.key === 'ArrowDown') step = 1;
          if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') step = -1;
          if (!step) return;
          e.preventDefault();
          pick(segBtns[(i + step + segBtns.length) % segBtns.length].id, true);
        });
      });

      var errorEl = _el('p', 'ss-error');
      errorEl.setAttribute('role', 'alert');
      var statusEl = _el('p', 'ss-status');
      statusEl.setAttribute('aria-live', 'polite');
      shell.body.appendChild(viaLabel);
      shell.body.appendChild(seg);
      shell.body.appendChild(label);
      shell.body.appendChild(field);
      shell.body.appendChild(hint);
      shell.body.appendChild(errorEl);
      shell.body.appendChild(statusEl);
      pick(channel, false);

      var cancelBtn = _button('Cancel');
      var downloadBtn = _button('Download file instead');
      downloadBtn.className = 'mp-btn ss-link-btn';
      var shareBtn = _button('Share', true);
      shell.actions.appendChild(downloadBtn);
      shell.actions.appendChild(cancelBtn);
      shell.actions.appendChild(shareBtn);
      focusOrder = function () {
        var selected = segBtns.filter(function (s) {
          return s.id === channel;
        })[0];
        shell.setFocusables([selected.el, input, downloadBtn, cancelBtn, shareBtn]);
      };
      focusOrder();

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
        lookup.close();
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
        published = true;
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
        if (lookup.handleKey(e)) return;
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
      shell.onEscape = null;
      shell.closeBtn.hidden = false;
      var version = data.version;
      shell.heading.textContent = data.reused
        ? 'Already shared, no changes since version ' + version
        : 'Shared as version ' + version;

      var ungranted = Array.isArray(data.ungranted) ? data.ungranted : [];
      var granted = emails.filter(function (e) {
        return ungranted.indexOf(e) === -1;
      });
      if (granted.length) shell.body.appendChild(_el('p', 'ss-access', 'Access granted to ' + granted.join(', ')));
      if (ungranted.length) shell.body.appendChild(_ungrantedNotice(ungranted));
      var area = _el('textarea', 'ss-message');
      area.readOnly = true;
      area.value = data.message || '';
      area.setAttribute('rows', '4');
      area.setAttribute('aria-label', 'Message to send');
      shell.body.appendChild(area);
      shell.body.appendChild(
        _el('p', 'ss-hint', 'Nothing has been sent. Send opens ' + _channel(channel).draft + ' for you to approve.'),
      );
      var errorEl = _el('p', 'ss-error');
      errorEl.setAttribute('role', 'alert');
      shell.body.appendChild(errorEl);
      var statusEl = _el('p', 'ss-status');
      statusEl.setAttribute('aria-live', 'polite');
      shell.body.appendChild(statusEl);

      var copyMsgBtn = _button('Copy message');
      copyMsgBtn.className += ' ss-copy';
      // The label is captured once, so a second click while "Copied" is
      // showing cannot mistake "Copied" for the original label.
      var copyLabel = copyMsgBtn.textContent;
      copyMsgBtn.addEventListener('click', function () {
        var clip = typeof navigator !== 'undefined' && navigator.clipboard;
        if (!clip || typeof clip.writeText !== 'function') {
          errorEl.textContent = 'Could not copy. Select the text and copy it.';
          return;
        }
        Promise.resolve()
          .then(function () {
            return clip.writeText(data.message || '');
          })
          .then(
            function () {
              errorEl.textContent = '';
              copyMsgBtn.textContent = 'Copied';
              setTimeout(function () {
                copyMsgBtn.textContent = copyLabel;
              }, 2000);
            },
            function () {
              errorEl.textContent = 'Could not copy. Select the text and copy it.';
            },
          );
      });

      var sendBtn = _button('Send', true);
      var sending = false;
      sendBtn.addEventListener('click', async function () {
        if (sending) return;
        sending = true;
        sendBtn.disabled = true;
        errorEl.textContent = '';
        statusEl.textContent = 'Preparing draft...';
        var out;
        try {
          out = await deps.postJson('/api/skills/share/draft', {
            channel: channel,
            skill_id: skillId,
            people: emails,
            message: data.message || '',
          });
        } catch (err) {
          out = { resp: { ok: false }, body: null };
        }
        sending = false;
        statusEl.textContent = '';
        if (!out.resp || !out.resp.ok) {
          if (shell.closed) return;
          sendBtn.disabled = false;
          errorEl.textContent = shareErrorText(out.resp, out.body, 'Could not prepare the draft. Use Copy message instead.');
          return;
        }
        if (!deps.showDrafts) {
          if (shell.closed) return;
          sendBtn.disabled = false;
          errorEl.textContent = 'Could not open the draft here. Use Copy message instead.';
          return;
        }
        var drafts = (out.body && out.body.drafts) || [];
        var unmatched = (out.body && out.body.unmatched) || [];
        shell.close();
        deps.showDrafts(drafts);
        if (unmatched.length && deps.showAlert) {
          deps.showAlert(
            'No Slack account was found for ' + unmatched.join(', ') + '. Use Copy message to reach them.',
            'warning',
          );
        }
      });

      // The quiet link sits on the left; the two actions sit on the right with
      // the main one last, like every other modal.
      var focusables = [shell.closeBtn, area];
      if (typeof data.web_url === 'string' && data.web_url.indexOf('https://') === 0) {
        var open = _el('a', 'mp-btn mp-btn-cancel', 'Open in OneDrive');
        open.href = data.web_url;
        open.target = '_blank';
        open.rel = 'noopener';
        shell.actions.appendChild(open);
        focusables.push(open);
      }
      shell.actions.appendChild(_el('div', 'ss-spacer'));
      shell.actions.appendChild(copyMsgBtn);
      shell.actions.appendChild(sendBtn);
      focusables.push(copyMsgBtn, sendBtn);
      shell.setFocusables(focusables);
      sendBtn.focus();
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
      if (deps.onInstalled) deps.onInstalled(out.body, review);
      else deps.showAlert('Installed "' + title + '".', 'success');
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
