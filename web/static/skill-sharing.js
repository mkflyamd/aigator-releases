// web/static/skill-sharing.js
//
// Browser side of skill sharing. Owns the Share modal on Mine skill rows, a
// three-step flow: Save (pick the OneDrive folder and confirm who can already
// see it), Share (pick people), Send (publish, then open an email draft for
// approval or copy the message). The .skill file download stays as a fallback
// when the folders cannot be loaded.
//
// Every dependency on the marketplace pane (CSRF-aware POST, JSON GET, the
// download function, people search, alerts, refresh) is passed in, so this file
// has no globals of its own besides window.SkillSharing. Server text is only
// ever put in with textContent.
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

  // ── Icons ────────────────────────────────────────────────────────────────

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var ICONS = {
    folder: ['M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'],
    cloud: ['M7 18a4 4 0 0 1-.5-7.97A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9z'],
    site: ['M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0', 'M3 12h18', 'M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18'],
    drive: ['M3 12l2-7h14l2 7', 'M3 12v6a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6z', 'M3 12h18'],
    chev: ['M9 6l6 6-6 6'],
    check: ['M5 12l5 5 9-10'],
  };

  function _icon(name, size) {
    var svg = document.createElementNS(SVG_NS, 'svg');
    var px = String(size || 16);
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', px);
    svg.setAttribute('height', px);
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    ICONS[name].forEach(function (d) {
      var path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('d', d);
      svg.appendChild(path);
    });
    return svg;
  }

  // ── People field ─────────────────────────────────────────────────────────

  var SUGGEST_MIN = 2;
  var SUGGEST_MAX = 6;
  var SUGGEST_DELAY = 250;

  function _domain(email) {
    return email.slice(email.lastIndexOf('@') + 1);
  }

  // A box of address chips with a lookup under it. It searches the same
  // directory as the prompt bar's @ mentions: a short wait before each
  // search, the stale request cancelled, the previous results kept on screen
  // until new ones arrive, and a "Searching people..." row only while there is
  // nothing else to show. `deps.searchPeople(query, signal)` resolves to
  // [{name, email}]. Without it the field only takes typed addresses.
  // `hooks.onChange()` runs when the chips change, `hooks.onInvalid(text)` when
  // typed text is not an address.
  function _peopleField(deps, hooks, initial) {
    var enabled = typeof deps.searchPeople === 'function';
    var stamp = Date.now();
    var people = initial.slice();
    var known = {};
    var orgDomains = {};
    var cache = {};
    var shown = [];
    var rows = [];
    var active = -1;
    var searching = false;
    var seq = 0;
    var timer = null;
    var ctrl = null;

    var field = _el('div', 'ss-field');
    var box = _el('div', 'ss-chipbox');
    var chipsEl = _el('span', 'ss-chips');
    var input = _el('input');
    input.type = 'text';
    input.id = 'ss-people-' + stamp;
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('aria-label', 'People to share with');
    input.setAttribute('placeholder', 'Search by name or enter an email address');
    var list = _el('ul', 'ss-suggest');
    list.id = 'ss-suggest-' + stamp;
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', 'Matching people');
    list.hidden = true;
    box.appendChild(chipsEl);
    box.appendChild(input);
    field.appendChild(box);
    field.appendChild(list);
    if (enabled) {
      input.setAttribute('role', 'combobox');
      input.setAttribute('aria-autocomplete', 'list');
      input.setAttribute('aria-expanded', 'false');
      input.setAttribute('aria-controls', list.id);
    }
    box.addEventListener('click', function (e) {
      if (e.target === box || e.target === chipsEl) input.focus();
    });

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

    function abort() {
      if (ctrl) ctrl.abort();
      ctrl = null;
    }

    function hasOrgInfo() {
      return Object.keys(orgDomains).length > 0;
    }

    function renderChips() {
      _clear(chipsEl);
      people.forEach(function (p) {
        var outside = hasOrgInfo() && !orgDomains[_domain(p.email)];
        var chip = _el('span', outside ? 'ss-chip is-warn' : 'ss-chip');
        var name = p.name || known[p.email] || '';
        chip.appendChild(document.createTextNode(name || p.email));
        chip.setAttribute('title', outside ? p.email + ' (outside your organization)' : p.email);
        var x = _el('button', '', '×');
        x.type = 'button';
        x.setAttribute('aria-label', 'Remove ' + p.email);
        x.addEventListener('click', function () {
          remove(p.email);
          input.focus();
        });
        chip.appendChild(x);
        chipsEl.appendChild(chip);
      });
    }

    function remove(email) {
      people = people.filter(function (p) {
        return p.email !== email;
      });
      renderChips();
      hooks.onChange();
    }

    function add(email, name) {
      email = String(email || '').trim().toLowerCase();
      if (!EMAIL_RE.test(email)) return false;
      var n = name && name !== email ? name : '';
      var have = people.filter(function (p) {
        return p.email === email;
      })[0];
      if (!have) {
        people.push({ email: email, name: n || known[email] || '' });
        renderChips();
        hooks.onChange();
      }
      return true;
    }

    function learn(found) {
      found.forEach(function (p) {
        if (!p || typeof p.email !== 'string' || !p.email) return;
        var email = p.email.toLowerCase();
        if (p.name && p.name !== email) known[email] = p.name;
        orgDomains[_domain(email)] = true;
      });
      people.forEach(function (p) {
        if (!p.name && known[p.email]) p.name = known[p.email];
      });
      renderChips();
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

    function choose(p) {
      seq += 1;
      clearTimeout(timer);
      abort();
      searching = false;
      add(p.email, p.name);
      input.value = '';
      input.setAttribute('aria-invalid', 'false');
      close();
      input.focus();
    }

    function refresh(q) {
      var taken = people.map(function (p) {
        return p.email;
      });
      var items = shown
        .filter(function (p) {
          return p && typeof p.email === 'string' && p.email && taken.indexOf(p.email.toLowerCase()) === -1;
        })
        .slice(0, SUGGEST_MAX)
        .map(function (p) {
          return { name: p.name && p.name !== p.email ? p.name : '', email: p.email, label: '' };
        });
      var typed = q.toLowerCase();
      var listed = items.some(function (p) {
        return p.email.toLowerCase() === typed;
      });
      if (EMAIL_RE.test(typed) && taken.indexOf(typed) === -1 && !listed) {
        items.push({ name: '', email: typed, label: 'Add ' + typed });
      }
      var busy = searching && !items.length;
      if (!items.length && !busy) {
        close();
        return;
      }
      _clear(list);
      rows = [];
      if (busy) {
        var wait = _el('li', 'ss-suggest-busy');
        wait.setAttribute('role', 'status');
        wait.appendChild(_el('span', 'ss-spin'));
        wait.appendChild(_el('span', '', 'Searching people...'));
        list.appendChild(wait);
      }
      items.forEach(function (p, i) {
        var li = _el('li', 'ss-suggest-item');
        li.id = list.id + '-' + i;
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', 'false');
        if (p.label) {
          li.appendChild(_el('span', 'ss-suggest-email', p.label));
        } else {
          if (p.name) li.appendChild(_el('span', 'ss-suggest-name', p.name));
          li.appendChild(_el('span', 'ss-suggest-email', p.email));
        }
        // mousedown, not click: the input keeps focus, so it does not blur
        // (and close the list) before the choice lands.
        li.addEventListener('mousedown', function (e) {
          e.preventDefault();
          choose(p);
        });
        list.appendChild(li);
        rows.push({ el: li, person: p });
      });
      list.hidden = false;
      if (enabled) input.setAttribute('aria-expanded', 'true');
      setActive(-1);
    }

    async function run(q, key, mine) {
      abort();
      ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
      searching = true;
      refresh(q);
      var found = [];
      var ok = true;
      try {
        found = await deps.searchPeople(q, ctrl ? ctrl.signal : undefined);
      } catch (err) {
        ok = false;
      }
      if (mine !== seq) return;
      searching = false;
      if (!Array.isArray(found)) found = [];
      if (ok) {
        cache[key] = found;
        learn(found);
      }
      shown = found;
      refresh(q);
    }

    // Turns whatever is typed into chips. Text that is not an address stays in
    // the box and is reported. Returns true when the box is empty afterwards.
    function flush() {
      var parsed = parseEmails(input.value);
      parsed.emails.forEach(function (email) {
        add(email);
      });
      input.value = parsed.bad.join(' ');
      if (parsed.bad.length) {
        input.setAttribute('aria-invalid', 'true');
        hooks.onInvalid('"' + parsed.bad[0] + '" is not a valid email address.');
        return false;
      }
      input.setAttribute('aria-invalid', 'false');
      return true;
    }

    function onInput() {
      clearTimeout(timer);
      seq += 1;
      var mine = seq;
      if (/[,;\n]/.test(input.value)) {
        flush();
        close();
        return;
      }
      input.setAttribute('aria-invalid', 'false');
      var q = input.value.trim();
      if (q.length < SUGGEST_MIN || !enabled) {
        abort();
        searching = false;
        shown = [];
        close();
        return;
      }
      var key = q.toLowerCase();
      if (cache[key]) {
        abort();
        searching = false;
        shown = cache[key];
        refresh(q);
        return;
      }
      timer = setTimeout(function () {
        run(q, key, mine);
      }, SUGGEST_DELAY);
      refresh(q);
    }

    // True when the key was used by the field and the modal must not act on it.
    function handleKey(e) {
      if (e.key === 'Backspace' && !input.value && people.length) {
        e.preventDefault();
        remove(people[people.length - 1].email);
        return true;
      }
      if (isOpen() && rows.length) {
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
      }
      if (e.key === 'Enter' && input.value.trim()) {
        e.preventDefault();
        flush();
        close();
        return true;
      }
      return false;
    }

    input.addEventListener('input', onInput);
    input.addEventListener('blur', close);
    input.addEventListener('keydown', handleKey);
    renderChips();

    return {
      el: field,
      input: input,
      people: function () {
        return people.slice();
      },
      outside: function () {
        return people.filter(function (p) {
          return hasOrgInfo() && !orgDomains[_domain(p.email)];
        });
      },
      flush: flush,
      close: close,
      isOpen: isOpen,
    };
  }

  // ── Share modal ──────────────────────────────────────────────────────────

  var STEP_NAMES = ['Save', 'Share', 'Send'];
  var LOAD_ERROR = 'Could not load your folders. Try again.';
  var NO_RESPONSE = { resp: { ok: false }, body: null };

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
          ', usually because they are outside your organization. Add ' +
          (one ? 'them' : 'each of them') +
          ' in OneDrive (Open in OneDrive, then Share) so the link works for them.',
      ),
    );
    return notice;
  }

  function _locLabel(loc) {
    var path = loc && Array.isArray(loc.path) && loc.path.length ? loc.path : [(loc && loc.name) || 'Folder'];
    return path.join(' › ');
  }

  function _sameLoc(a, b) {
    return a.drive_id === b.drive_id && a.folder_id === b.folder_id;
  }

  function _count(n) {
    return n >= 1000 ? n.toLocaleString('en-US') : String(n);
  }

  // Title, text and acknowledgement wording for an audience from the check.
  function _audienceCopy(a) {
    var name = a.name || 'this location';
    if (a.kind === 'folder') {
      return {
        title: typeof a.approx_count === 'number' ? 'Already shared with ' + _count(a.approx_count) + ' people' : 'Already shared with other people',
        text: 'Anyone this folder is shared with can open this skill without being added.',
        ack: 'I understand they can see it',
      };
    }
    if (a.kind === 'org') {
      return {
        title: 'Everyone in your organization can see it',
        text: 'This folder is open to the whole organization. Anyone can open this skill without being added.',
        ack: 'I understand everyone in my organization can see it',
        broad: true,
      };
    }
    if (a.kind === 'library') {
      return {
        title:
          typeof a.approx_count === 'number'
            ? 'Everyone in ' + name + ' (about ' + _count(a.approx_count) + ' people) can see it'
            : 'Everyone with access to ' + name + ' can see it',
        text: 'Anyone in this library can open this skill without being added.',
        ack: 'I understand everyone with access to ' + name + ' can see it',
      };
    }
    return {
      title: 'Only you can see this folder',
      text: 'People you add in the next step get read access to this skill only.',
    };
  }

  function _errorInfo(out) {
    var d = out.body && out.body.detail;
    var code = d && typeof d === 'object' && !Array.isArray(d) && typeof d.error === 'string' ? d.error : '';
    return { code: code, text: shareErrorText(out.resp, out.body) };
  }

  function openShareModal(skillId, deps) {
    var published = false;
    var S = {
      step: 1,
      loading: true,
      loadError: '',
      current: null,
      locs: [],
      sel: 0,
      check: { status: 'idle' },
      ack: false,
      chooser: null,
      people: [],
      result: null,
      publishing: false,
      error: null,
    };
    var checkSeq = 0;
    var focus = [];
    var shell = _openShell('Share "' + skillId + '"', function () {
      if (published && deps.refresh) deps.refresh();
    });

    function reg(el) {
      focus.push(el);
      return el;
    }

    function begin(title) {
      _clear(shell.body);
      _clear(shell.actions);
      focus = [shell.closeBtn];
      shell.heading.textContent = title || 'Share "' + skillId + '"';
      shell.closeBtn.hidden = false;
      shell.onEscape = null;
    }

    function finish() {
      shell.setFocusables(focus);
    }

    function get(url) {
      return Promise.resolve()
        .then(function () {
          return deps.getJson(url);
        })
        .catch(function () {
          return NO_RESPONSE;
        });
    }

    function post(url, payload) {
      return Promise.resolve()
        .then(function () {
          return deps.postJson(url, payload);
        })
        .catch(function () {
          return NO_RESPONSE;
        });
    }

    function ok(out) {
      return !!(out && out.resp && out.resp.ok);
    }

    function stepper() {
      var wrap = _el('div', 'ss-steps');
      wrap.setAttribute('role', 'group');
      wrap.setAttribute('aria-label', 'Progress');
      STEP_NAMES.forEach(function (name, i) {
        var k = i + 1;
        var done = k < S.step && S.step <= 3;
        var cls = 'ss-step' + (k === S.step ? ' is-current' : done ? ' is-done' : '');
        var b = _el('button', cls);
        b.type = 'button';
        b.setAttribute('data-done', done ? 'true' : 'false');
        if (!done) b.setAttribute('tabindex', '-1');
        if (k === S.step) b.setAttribute('aria-current', 'step');
        var num = _el('span', 'ss-num');
        if (k < S.step) num.appendChild(_icon('check', 11));
        else num.textContent = String(k);
        b.appendChild(num);
        b.appendChild(document.createTextNode(name));
        if (done) {
          b.addEventListener('click', function () {
            go(k);
          });
          reg(b);
        }
        wrap.appendChild(b);
        if (i < 2) {
          var line = _el('span', 'ss-step-line');
          line.setAttribute('aria-hidden', 'true');
          wrap.appendChild(line);
        }
      });
      return wrap;
    }

    function go(step) {
      if (S.publishing) return;
      if (step < 3) {
        S.result = null;
        S.error = null;
      }
      S.step = step;
      render();
    }

    function render() {
      if (shell.closed) return;
      if (S.chooser) renderChooser();
      else if (S.step === 1) renderSave();
      else if (S.step === 2) renderShare();
      else if (S.step === 3) renderSend();
      else renderDone();
    }

    // ── Step 1: where to save ──────────────────────────────────────────────

    function selectedEntry() {
      return S.locs[S.sel];
    }

    function mapCheck(r) {
      if (!ok(r)) return { status: 'error', text: shareErrorText(r.resp, r.body, 'Could not check this folder. Try again.') };
      var b = r.body || {};
      if (!b.ok) return { status: 'gone' };
      if (b.existing && b.existing.yours === false) return { status: 'taken', author: b.existing.author || '' };
      return { status: 'ok', audience: b.audience || { kind: 'private' }, location: b.location || null };
    }

    function runCheck() {
      var entry = selectedEntry();
      var mine = ++checkSeq;
      S.ack = false;
      S.check = { status: 'checking' };
      fillStatus();
      var q = '?skill_id=' + encodeURIComponent(skillId);
      if (!entry.isDefault) {
        q += '&drive_id=' + encodeURIComponent(entry.loc.drive_id) + '&folder_id=' + encodeURIComponent(entry.loc.folder_id);
      }
      get('/api/skills/share/check' + q).then(function (r) {
        if (mine !== checkSeq || shell.closed) return;
        S.check = mapCheck(r);
        var loc = S.check.location;
        if (loc && Array.isArray(loc.path) && loc.path.length) {
          entry.loc = Object.assign({}, entry.loc, { path: loc.path });
          var row = view.rows && view.rows[S.locs.indexOf(entry)];
          if (row && row.label) row.label.textContent = _locLabel(entry.loc);
        }
        fillStatus();
      });
    }

    function canLeaveSave() {
      if (S.current) return true;
      var c = S.check;
      return c.status === 'ok' && (c.audience.kind === 'private' || S.ack);
    }

    var view = {};

    function blockedBox(title, text) {
      var box = _el('div', 'ss-audience is-blocked');
      box.setAttribute('role', 'alert');
      box.appendChild(_el('div', 'ss-audience-title', title));
      box.appendChild(_el('div', 'ss-audience-text', text));
      return box;
    }

    function fillStatus() {
      if (!view.status) return;
      var c = S.check;
      _clear(view.status);
      if (c.status === 'checking') {
        var line = _el('div', 'ss-check-line');
        line.setAttribute('role', 'status');
        line.appendChild(_el('span', 'ss-spin'));
        line.appendChild(_el('span', '', 'Checking who can see this folder...'));
        view.status.appendChild(line);
      } else if (c.status === 'error') {
        var box = blockedBox('Could not check this folder', c.text);
        var retry = _el('button', 'ss-link-btn', 'Try again');
        retry.type = 'button';
        retry.addEventListener('click', runCheck);
        box.appendChild(retry);
        view.status.appendChild(box);
      } else if (c.status === 'gone') {
        view.status.appendChild(
          blockedBox('This folder is no longer available', 'It may have been moved or deleted. Choose another folder.'),
        );
      } else if (c.status === 'taken') {
        view.status.appendChild(
          blockedBox(
            'A skill with this name is already there',
            '"' + skillId + '" in this folder was created by ' + (c.author || 'someone else') + ', so it cannot be updated from here. Choose another folder.',
          ),
        );
      } else if (c.status === 'ok') {
        var copy = _audienceCopy(c.audience);
        var aud = _el('div', copy.broad ? 'ss-audience is-broad' : 'ss-audience');
        aud.setAttribute('role', 'status');
        aud.appendChild(_el('div', 'ss-audience-title', copy.title));
        aud.appendChild(_el('div', 'ss-audience-text', copy.text));
        if (copy.ack) {
          var ack = _el('label', 'ss-ack');
          var cb = _el('input');
          cb.type = 'checkbox';
          cb.checked = S.ack;
          cb.addEventListener('change', function () {
            S.ack = cb.checked;
            view.next.disabled = !canLeaveSave();
          });
          ack.appendChild(cb);
          ack.appendChild(_el('span', '', copy.ack));
          aud.appendChild(ack);
        }
        view.status.appendChild(aud);
      }
      view.next.disabled = !canLeaveSave();
    }

    function select(i) {
      if (i === S.sel) return;
      S.sel = i;
      view.rows.forEach(function (row, idx) {
        row.el.className = idx === i ? 'ss-loc is-selected' : 'ss-loc';
      });
      runCheck();
    }

    function renderSave() {
      begin();
      shell.body.appendChild(stepper());
      view = {};
      var nextBtn = _button('Next', true);
      if (S.loading) {
        var wait = _el('div', 'ss-check-line');
        wait.setAttribute('role', 'status');
        wait.appendChild(_el('span', 'ss-spin'));
        wait.appendChild(_el('span', '', 'Loading your folders...'));
        shell.body.appendChild(wait);
        finish();
        return;
      }
      if (S.loadError) {
        var err = _el('p', 'ss-error', S.loadError);
        err.setAttribute('role', 'alert');
        shell.body.appendChild(err);
        var dl = reg(_button('Download file instead'));
        dl.className = 'mp-btn ss-link-btn';
        dl.addEventListener('click', function () {
          shell.close();
          deps.downloadSkill(skillId);
        });
        var again = reg(_button('Try again', true));
        again.addEventListener('click', load);
        shell.actions.appendChild(dl);
        shell.actions.appendChild(_el('div', 'ss-spacer'));
        shell.actions.appendChild(again);
        finish();
        again.focus();
        return;
      }

      var labelId = 'ss-save-label-' + Date.now();
      var heading = _el('span', 'ss-label', S.current ? 'Saved in' : 'Save to');
      heading.id = labelId;
      shell.body.appendChild(heading);
      var group = _el('div', 'ss-locs');
      group.setAttribute('role', 'radiogroup');
      group.setAttribute('aria-labelledby', labelId);
      view.rows = [];

      if (S.current) {
        var fixed = _el('div', 'ss-loc is-selected');
        var fname = _el('span', 'ss-loc-name', _locLabel(S.current));
        fixed.appendChild(fname);
        group.appendChild(fixed);
        shell.body.appendChild(group);
        shell.body.appendChild(
          _el('p', 'ss-hint', 'This skill is already saved here. Updates go to the same folder.'),
        );
      } else {
        S.locs.forEach(function (entry, i) {
          var row = _el('label', i === S.sel ? 'ss-loc is-selected' : 'ss-loc');
          var radio = _el('input');
          radio.type = 'radio';
          radio.name = 'ss-loc';
          radio.checked = i === S.sel;
          radio.addEventListener('change', function () {
            select(i);
          });
          var text = _el('span', '');
          var name = _el('span', 'ss-loc-name', _locLabel(entry.loc));
          if (entry.tag) name.appendChild(_el('span', 'ss-tag', entry.tag));
          text.appendChild(name);
          row.appendChild(radio);
          row.appendChild(text);
          group.appendChild(row);
          reg(radio);
          view.rows.push({ el: row, radio: radio, label: name.firstChild });
        });
        shell.body.appendChild(group);
        var choose = _el('p', 'ss-choose');
        var chooseBtn = _el('button', 'ss-link-btn', 'Choose another folder...');
        chooseBtn.type = 'button';
        chooseBtn.addEventListener('click', openChooser);
        choose.appendChild(chooseBtn);
        shell.body.appendChild(choose);
        reg(chooseBtn);
        view.status = _el('div', 'ss-status-host');
        shell.body.appendChild(view.status);
      }

      nextBtn.addEventListener('click', function () {
        if (canLeaveSave()) go(2);
      });
      shell.actions.appendChild(_el('div', 'ss-spacer'));
      shell.actions.appendChild(reg(nextBtn));
      view.next = nextBtn;
      nextBtn.disabled = !canLeaveSave();
      finish();
      if (!S.current) {
        fillStatus();
        view.rows[S.sel].radio.focus();
      } else {
        nextBtn.focus();
      }
    }

    // ── Folder chooser ─────────────────────────────────────────────────────

    function openChooser() {
      S.chooser = { stack: [], items: [], loading: false, error: '', creating: false, newName: '', newError: '', busy: false, seq: 0 };
      loadChooser();
    }

    function chooserTop(ch) {
      return ch.stack[ch.stack.length - 1] || null;
    }

    function folderItems(body, driveId, personal) {
      return ((body && body.items) || [])
        .filter(function (it) {
          return it && it.is_folder;
        })
        .map(function (it) {
          return {
            kind: 'folder',
            id: it.id,
            name: it.name,
            drive_id: it.drive_id || driveId,
            personal: personal,
            web_url: it.web_url || '',
            has_children: !!it.has_children,
          };
        });
    }

    async function listFor(top) {
      var enc = encodeURIComponent;
      var r;
      if (!top) {
        var rows = [{ kind: 'od', name: 'My OneDrive', has_children: true }];
        var sites = await get('/api/onedrive/sites');
        if (!ok(sites)) return { items: rows, note: 'Could not load SharePoint sites.' };
        ((sites.body && sites.body.sites) || []).forEach(function (s) {
          rows.push({ kind: 'site', id: s.id, name: s.name, has_children: true });
        });
        return { items: rows };
      }
      if (top.kind === 'od') {
        r = await get('/api/onedrive/folders?parent=root');
        return ok(r) ? { items: folderItems(r.body, '', true) } : { error: shareErrorText(r.resp, r.body, LOAD_ERROR) };
      }
      if (top.kind === 'site') {
        r = await get('/api/onedrive/sites/' + enc(top.id) + '/drives');
        if (!ok(r)) return { error: shareErrorText(r.resp, r.body, LOAD_ERROR) };
        return {
          items: ((r.body && r.body.drives) || []).map(function (d) {
            return { kind: 'drive', id: d.id, name: d.name, has_children: true };
          }),
        };
      }
      if (top.kind === 'drive') {
        r = await get('/api/onedrive/drives/' + enc(top.id) + '/folders?parent=root');
        return ok(r) ? { items: folderItems(r.body, top.id, false) } : { error: shareErrorText(r.resp, r.body, LOAD_ERROR) };
      }
      if (top.personal) {
        r = await get('/api/onedrive/folders?parent=' + enc(top.id));
        return ok(r) ? { items: folderItems(r.body, top.drive_id, true) } : { error: shareErrorText(r.resp, r.body, LOAD_ERROR) };
      }
      r = await get('/api/onedrive/drives/' + enc(top.drive_id) + '/folders?parent=' + enc(top.id));
      return ok(r) ? { items: folderItems(r.body, top.drive_id, false) } : { error: shareErrorText(r.resp, r.body, LOAD_ERROR) };
    }

    async function loadChooser() {
      var ch = S.chooser;
      var mine = ++ch.seq;
      ch.loading = true;
      ch.error = '';
      ch.note = '';
      ch.items = [];
      renderChooser();
      var out = await listFor(chooserTop(ch));
      if (shell.closed || S.chooser !== ch || mine !== ch.seq) return;
      ch.loading = false;
      ch.items = out.items || [];
      ch.error = out.error || '';
      ch.note = out.note || '';
      renderChooser();
      focusList();
    }

    function focusList() {
      var first = view.folders && view.folders.querySelector('button');
      if (first) first.focus();
      else if (view.back) view.back.focus();
    }

    function chooserTo(depth) {
      var ch = S.chooser;
      ch.stack = ch.stack.slice(0, depth);
      ch.creating = false;
      ch.newName = '';
      ch.newError = '';
      loadChooser();
    }

    function iconFor(kind) {
      return _icon(kind === 'od' ? 'cloud' : kind === 'site' ? 'site' : kind === 'drive' ? 'drive' : 'folder');
    }

    function nameClash(ch) {
      var wanted = ch.newName.trim().toLowerCase();
      return (
        !!wanted &&
        ch.items.some(function (it) {
          return it.kind === 'folder' && it.name.toLowerCase() === wanted;
        })
      );
    }

    function selectChosen() {
      var ch = S.chooser;
      var top = chooserTop(ch);
      if (!top || top.kind !== 'folder') return;
      var loc = {
        drive_id: top.drive_id,
        folder_id: top.id,
        name: top.name,
        path: ch.stack.map(function (e) {
          return e.name;
        }),
        web_url: top.web_url || '',
      };
      var at = -1;
      S.locs.forEach(function (e, i) {
        if (_sameLoc(e.loc, loc)) at = i;
      });
      if (at < 0) {
        S.locs = S.locs.filter(function (e) {
          return e.tag !== 'Chosen';
        });
        S.locs.splice(1, 0, { loc: loc, tag: 'Chosen' });
        at = 1;
      }
      S.sel = at;
      S.chooser = null;
      render();
      runCheck();
    }

    async function createFolder() {
      var ch = S.chooser;
      var top = chooserTop(ch);
      var name = ch.newName.trim();
      if (!name || ch.busy) return;
      if (nameClash(ch)) {
        ch.newError = 'A folder with that name already exists';
        renderChooser();
        return;
      }
      var enc = encodeURIComponent;
      var parent = top.kind === 'folder' ? top.id : 'root';
      var personal = top.kind === 'od' || (top.kind === 'folder' && top.personal);
      var driveId = top.kind === 'drive' ? top.id : top.drive_id;
      var url = personal
        ? '/api/onedrive/folders/' + enc(parent)
        : '/api/onedrive/drives/' + enc(driveId) + '/folders/' + enc(parent);
      ch.busy = true;
      ch.newError = '';
      renderChooser();
      var out = await post(url, { name: name, conflict: 'fail' });
      if (shell.closed || S.chooser !== ch) return;
      ch.busy = false;
      if (!ok(out)) {
        var info = _errorInfo(out);
        ch.newError =
          info.code === 'folder_exists'
            ? 'A folder with that name already exists'
            : shareErrorText(out.resp, out.body, 'Could not create the folder. Try again.');
        renderChooser();
        return;
      }
      var made = out.body || {};
      ch.creating = false;
      ch.newName = '';
      await loadChooser();
      if (shell.closed || S.chooser !== ch) return;
      var found = ch.items.filter(function (it) {
        return it.kind === 'folder' && it.id === made.id;
      })[0];
      if (found && found.drive_id) {
        ch.stack.push(found);
        loadChooser();
      }
    }

    function renderChooser() {
      var ch = S.chooser;
      begin('Choose a folder');
      shell.body.appendChild(stepper());
      shell.onEscape = function () {
        S.chooser = null;
        render();
        return true;
      };
      view = {};

      var crumbs = _el('nav', 'ss-crumbs');
      crumbs.setAttribute('aria-label', 'Folder path');
      var parts = [{ t: 'Folders', d: 0 }].concat(
        ch.stack.map(function (e, i) {
          return { t: e.name, d: i + 1 };
        }),
      );
      parts.forEach(function (p, i) {
        var last = i === parts.length - 1;
        if (i) {
          var sep = _el('span', 'ss-crumb-sep', '›');
          sep.setAttribute('aria-hidden', 'true');
          crumbs.appendChild(sep);
        }
        var b = _el('button', 'ss-crumb', p.t);
        b.type = 'button';
        if (last) b.setAttribute('aria-current', 'true');
        else
          b.addEventListener('click', function () {
            chooserTo(p.d);
          });
        crumbs.appendChild(b);
        reg(b);
      });
      shell.body.appendChild(crumbs);

      var top = chooserTop(ch);
      var box = _el('div', 'ss-folders');
      view.folders = box;
      if (ch.loading) {
        var wait = _el('div', 'ss-empty');
        wait.setAttribute('role', 'status');
        wait.textContent = 'Loading...';
        box.appendChild(wait);
      } else if (ch.error) {
        var bad = _el('div', 'ss-empty');
        bad.setAttribute('role', 'alert');
        bad.appendChild(_el('p', '', ch.error));
        var retry = _el('button', 'ss-link-btn', 'Try again');
        retry.type = 'button';
        retry.addEventListener('click', function () {
          loadChooser();
        });
        bad.appendChild(retry);
        reg(retry);
        box.appendChild(bad);
      } else {
        var lastGroup = '';
        ch.items.forEach(function (it) {
          var group = it.kind === 'od' ? 'Your OneDrive' : it.kind === 'site' ? 'SharePoint sites' : '';
          if (group && group !== lastGroup) {
            box.appendChild(_el('div', 'ss-group', group));
            lastGroup = group;
          }
          var row = _el('button', 'ss-fold');
          row.type = 'button';
          row.appendChild(iconFor(it.kind));
          row.appendChild(document.createTextNode(it.name));
          if (it.has_children) {
            var chev = _icon('chev', 12);
            chev.setAttribute('class', 'ss-chev');
            row.appendChild(chev);
          }
          row.addEventListener('click', function () {
            ch.stack.push(it);
            ch.creating = false;
            ch.newName = '';
            ch.newError = '';
            loadChooser();
          });
          box.appendChild(row);
          reg(row);
        });
        if (ch.note) box.appendChild(_el('div', 'ss-empty', ch.note));
        if (!ch.items.length && !ch.note) box.appendChild(_el('div', 'ss-empty', 'No folders here'));
      }
      shell.body.appendChild(box);

      if (ch.creating) {
        var rowEl = _el('div', 'ss-newrow');
        var fieldEl = _el('div', 'ss-newrow-field');
        var input = _el('input', 'ss-input');
        input.type = 'text';
        input.value = ch.newName;
        input.setAttribute('placeholder', 'Folder name');
        input.setAttribute('aria-label', 'New folder name');
        var clash = nameClash(ch);
        var message = clash ? 'A folder with that name already exists' : ch.newError;
        var errEl = _el('p', 'ss-error ss-newrow-error', message);
        errEl.setAttribute('role', 'alert');
        if (message) input.setAttribute('aria-invalid', 'true');
        var create = _button('Create', true);
        create.disabled = !ch.newName.trim() || clash || ch.busy;
        var cancel = _button('Cancel');
        input.addEventListener('input', function () {
          ch.newName = input.value;
          ch.newError = '';
          var c = nameClash(ch);
          errEl.textContent = c ? 'A folder with that name already exists' : '';
          input.setAttribute('aria-invalid', c ? 'true' : 'false');
          create.disabled = !input.value.trim() || c || ch.busy;
        });
        input.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') {
            e.preventDefault();
            if (!create.disabled) createFolder();
          }
        });
        create.addEventListener('click', createFolder);
        cancel.addEventListener('click', function () {
          ch.creating = false;
          ch.newName = '';
          ch.newError = '';
          renderChooser();
        });
        fieldEl.appendChild(input);
        fieldEl.appendChild(errEl);
        rowEl.appendChild(fieldEl);
        rowEl.appendChild(create);
        rowEl.appendChild(cancel);
        shell.body.appendChild(rowEl);
        reg(input);
        reg(create);
        reg(cancel);
        shell.onEscape = function () {
          ch.creating = false;
          renderChooser();
          return true;
        };
        finish();
        input.focus();
        return;
      }

      var back = reg(_button('Back'));
      view.back = back;
      back.addEventListener('click', function () {
        S.chooser = null;
        render();
      });
      shell.actions.appendChild(back);
      if (top && top.kind !== 'site' && !ch.loading) {
        var fresh = reg(_el('button', 'ss-link-btn', 'New folder'));
        fresh.type = 'button';
        fresh.addEventListener('click', function () {
          ch.creating = true;
          renderChooser();
        });
        shell.actions.appendChild(fresh);
      }
      var pick = reg(_button('Select this folder', true));
      pick.disabled = !(top && top.kind === 'folder' && !ch.loading);
      pick.addEventListener('click', selectChosen);
      shell.actions.appendChild(_el('div', 'ss-spacer'));
      shell.actions.appendChild(pick);
      finish();
    }

    // ── Step 2: who to share with ──────────────────────────────────────────

    function renderShare() {
      begin();
      shell.body.appendChild(stepper());
      var shared = S.check.status === 'ok' && S.check.audience.kind !== 'private';
      var nextBtn = _button('Next', true);
      var errorEl = _el('p', 'ss-error');
      errorEl.setAttribute('role', 'alert');
      var warnHost = _el('div', '');
      var field;

      function updateNext() {
        nextBtn.disabled = !(S.current || shared || S.people.length || field.input.value.trim());
      }

      function fillWarn() {
        _clear(warnHost);
        var out = field.outside();
        if (!out.length) return;
        var names = out.map(function (p) {
          return p.name || p.email;
        });
        var notice = _el('div', 'ss-notice');
        notice.setAttribute('role', 'note');
        notice.appendChild(_el('p', 'ss-notice-title', 'May need adding in OneDrive'));
        notice.appendChild(
          _el(
            'p',
            'ss-notice-text',
            names.join(', ') +
              (out.length === 1 ? ' is' : ' are') +
              ' outside your organization, so access may not be given automatically. They still get the email. You can add them to the folder in OneDrive afterwards.',
          ),
        );
        warnHost.appendChild(notice);
      }

      var label = _el('label', 'ss-label', 'Share with');
      field = _peopleField(
        deps,
        {
          onChange: function () {
            S.people = field.people();
            errorEl.textContent = '';
            fillWarn();
            updateNext();
          },
          onInvalid: function (text) {
            errorEl.textContent = text;
          },
        },
        S.people,
      );
      label.setAttribute('for', field.input.id);
      shell.body.appendChild(label);
      shell.body.appendChild(field.el);

      if (shared) {
        var a = S.check.audience;
        var who =
          a.kind === 'org'
            ? 'Everyone in your organization'
            : a.kind === 'folder'
              ? 'The people this folder is shared with'
              : 'Everyone with access to ' + (a.name || 'this library');
        var note = _el('div', 'ss-notice');
        note.setAttribute('role', 'note');
        note.appendChild(_el('p', 'ss-notice-title', 'People can already use it'));
        note.appendChild(
          _el('p', 'ss-notice-text', who + ' can already use it. Add people only to include them in the message.'),
        );
        shell.body.appendChild(note);
      } else {
        shell.body.appendChild(
          _el(
            'p',
            'ss-hint',
            'These people get read access to this skill. Leave out anyone you do not want to be able to open it.',
          ),
        );
      }
      shell.body.appendChild(warnHost);
      shell.body.appendChild(errorEl);
      fillWarn();

      var back = reg(_button('Back'));
      back.addEventListener('click', function () {
        S.people = field.people();
        go(1);
      });
      nextBtn.addEventListener('click', function () {
        if (!field.flush()) return;
        S.people = field.people();
        if (S.current || shared || S.people.length) go(3);
      });
      field.input.addEventListener('input', updateNext);
      shell.actions.appendChild(back);
      shell.actions.appendChild(_el('div', 'ss-spacer'));
      shell.actions.appendChild(reg(nextBtn));
      focus.splice(focus.length - 2, 0, field.input);
      updateNext();
      shell.onEscape = function () {
        if (!field.isOpen()) return false;
        field.close();
        return true;
      };
      finish();
      field.input.focus();
    }

    // ── Step 3: message and send ───────────────────────────────────────────

    function personRow(p) {
      var row = _el('div', 'ss-to-row');
      if (p.name) {
        row.appendChild(document.createTextNode(p.name + ' '));
        row.appendChild(_el('span', 'ss-to-email', p.email));
      } else {
        row.appendChild(document.createTextNode(p.email));
      }
      return row;
    }

    function setBusy(busy, text) {
      S.publishing = busy;
      view.back.disabled = busy;
      view.copy.disabled = busy;
      view.send.disabled = busy || !S.people.length;
      view.status.textContent = busy ? text || '' : '';
    }

    function showFailure(info) {
      _clear(view.errors);
      if (!info) return;
      var folderFault = ['not_yours', 'forbidden', 'not_found', 'invalid', 'audience_unacknowledged'].indexOf(info.code) !== -1;
      if (info.code === 'policy_blocked') {
        view.errors.appendChild(blockedBox('Nobody has been given access', info.text));
      } else if (folderFault) {
        var box = blockedBox('Could not save to this folder', info.text);
        if (!S.current) {
          var other = _el('button', 'ss-link-btn', 'Choose another folder');
          other.type = 'button';
          other.addEventListener('click', function () {
            go(1);
          });
          box.appendChild(other);
        }
        view.errors.appendChild(box);
      } else {
        var p = _el('p', 'ss-error', info.text);
        p.setAttribute('role', 'alert');
        view.errors.appendChild(p);
      }
    }

    function showPublished(res) {
      view.msg.value = res.message || '';
      view.msgWrap.hidden = false;
      _clear(view.notices);
      if (Array.isArray(res.ungranted) && res.ungranted.length) {
        view.notices.appendChild(_ungrantedNotice(res.ungranted));
      }
    }

    async function ensurePublished() {
      if (S.result) return S.result;
      var entry = selectedEntry();
      var root = S.current || (entry && entry.isDefault) ? null : { drive_id: entry.loc.drive_id, folder_id: entry.loc.folder_id };
      var out = await post('/api/skills/share/publish', {
        skill_id: skillId,
        people: S.people.map(function (p) {
          return p.email;
        }),
        root: root,
        audience_ack: !!S.ack,
      });
      if (ok(out)) published = true;
      if (shell.closed) {
        if (ok(out) && deps.refresh) deps.refresh();
        return null;
      }
      if (!ok(out)) {
        S.error = _errorInfo(out);
        return null;
      }
      S.result = out.body || {};
      S.error = null;
      return S.result;
    }

    async function onCopy() {
      if (S.publishing) return;
      setBusy(true, 'Saving the skill and giving access...');
      showFailure(null);
      var res = await ensurePublished();
      if (shell.closed) return;
      setBusy(false);
      if (!res) {
        showFailure(S.error);
        return;
      }
      showPublished(res);
      var clip = typeof navigator !== 'undefined' && navigator.clipboard;
      try {
        if (!clip || typeof clip.writeText !== 'function') throw new Error('no clipboard');
        await clip.writeText(res.message || '');
        view.status.textContent = 'Message copied.';
      } catch (err) {
        showFailure({ code: '', text: 'Could not copy. Select the text and copy it.' });
      }
    }

    async function onSend() {
      if (S.publishing) return;
      setBusy(true, 'Saving the skill and giving access...');
      showFailure(null);
      var res = await ensurePublished();
      if (shell.closed) return;
      if (!res) {
        setBusy(false);
        showFailure(S.error);
        return;
      }
      showPublished(res);
      view.status.textContent = 'Preparing draft...';
      var out = await post('/api/skills/share/draft', {
        skill_id: skillId,
        channel: 'email',
        people: S.people.map(function (p) {
          return p.name ? { name: p.name, email: p.email } : { email: p.email };
        }),
        message: res.message || '',
        message_html: res.message_html || '',
      });
      if (shell.closed) return;
      setBusy(false);
      if (!ok(out)) {
        showFailure({ code: '', text: shareErrorText(out.resp, out.body, 'Could not prepare the draft. Use Copy message instead.') });
        return;
      }
      if (!deps.showDrafts) {
        showFailure({ code: '', text: 'Could not open the draft here. Use Copy message instead.' });
        return;
      }
      var drafts = (out.body && out.body.drafts) || [];
      var unmatched = (out.body && out.body.unmatched) || [];
      S.step = 4;
      render();
      deps.showDrafts(drafts);
      if (unmatched.length && deps.showAlert) {
        deps.showAlert('No account was found for ' + unmatched.join(', ') + '. Use Copy message to reach them.', 'warning');
      }
    }

    function renderSend() {
      begin();
      shell.body.appendChild(stepper());
      view = {};
      shell.body.appendChild(_el('span', 'ss-label', 'Email to'));
      var to = _el('div', 'ss-tobar');
      if (S.people.length) {
        S.people.forEach(function (p) {
          to.appendChild(personRow(p));
        });
      } else {
        to.appendChild(_el('div', 'ss-to-row', 'No one added. Use Copy message to share the link yourself.'));
      }
      shell.body.appendChild(to);
      var msgLabel = _el('label', 'ss-label', 'Message');
      msgLabel.setAttribute('for', 'ss-message');
      var msg = _el('textarea', 'ss-message');
      msg.id = 'ss-message';
      msg.readOnly = true;
      msg.setAttribute('rows', '5');
      msg.value = S.result ? S.result.message || '' : '';
      var msgWrap = _el('div', '');
      msgWrap.hidden = !S.result;
      msgWrap.appendChild(msgLabel);
      msgWrap.appendChild(msg);
      shell.body.appendChild(msgWrap);
      view.msg = msg;
      view.msgWrap = msgWrap;
      view.status = _el('p', 'ss-status');
      view.status.setAttribute('aria-live', 'polite');
      view.notices = _el('div', '');
      view.errors = _el('div', '');
      shell.body.appendChild(view.status);
      shell.body.appendChild(view.notices);
      shell.body.appendChild(view.errors);

      view.back = reg(_button('Back'));
      view.back.addEventListener('click', function () {
        go(2);
      });
      view.copy = _button('Copy message');
      view.copy.className += ' ss-copy';
      view.copy.addEventListener('click', onCopy);
      view.send = _button('Send', true);
      view.send.disabled = !S.people.length;
      view.send.setAttribute('title', 'Opens an email draft for you to approve. Nothing is sent automatically.');
      view.send.addEventListener('click', onSend);
      reg(msg);
      reg(view.copy);
      reg(view.send);
      shell.actions.appendChild(view.back);
      shell.actions.appendChild(_el('div', 'ss-spacer'));
      shell.actions.appendChild(view.copy);
      shell.actions.appendChild(view.send);
      if (S.result) showPublished(S.result);
      showFailure(S.error);
      finish();
      (view.send.disabled ? view.copy : view.send).focus();
    }

    // ── Done ───────────────────────────────────────────────────────────────

    function renderDone() {
      var res = S.result || {};
      begin('Shared "' + skillId + '"');
      var head = _el('div', 'ss-done-head');
      var check = _el('span', 'ss-done-check');
      check.appendChild(_icon('check', 16));
      var text = _el('div', '');
      text.appendChild(_el('div', 'ss-done-title', 'Email draft ready for your approval'));
      text.appendChild(_el('p', 'ss-done-sub ss-hint', 'Nothing is sent until you approve it in the chat.'));
      head.appendChild(check);
      head.appendChild(text);
      shell.body.appendChild(head);
      var saved = Array.isArray(res.saved_path) && res.saved_path.length ? res.saved_path.join(' › ') : _locLabel(S.current || selectedEntry().loc);
      shell.body.appendChild(_el('p', 'ss-hint', 'Saved to ' + saved + '.'));
      if (Array.isArray(res.ungranted) && res.ungranted.length) shell.body.appendChild(_ungrantedNotice(res.ungranted));
      if (typeof res.web_url === 'string' && res.web_url.indexOf('https://') === 0) {
        var open = reg(_el('a', 'mp-btn mp-btn-cancel', 'Open in OneDrive'));
        open.href = res.web_url;
        open.target = '_blank';
        open.rel = 'noopener';
        shell.actions.appendChild(open);
      }
      finish();
      shell.closeBtn.focus();
    }

    // ── Start ──────────────────────────────────────────────────────────────

    async function load() {
      S.loading = true;
      S.loadError = '';
      render();
      var r = await get('/api/skills/share/locations?skill_id=' + encodeURIComponent(skillId));
      if (shell.closed) return;
      S.loading = false;
      var b = r.body || {};
      if (!ok(r) || !b.default) {
        S.loadError = shareErrorText(r.resp, r.body, LOAD_ERROR);
        render();
        return;
      }
      S.current = b.current || null;
      S.locs = [{ loc: b.default, tag: 'Default', isDefault: true }].concat(
        (Array.isArray(b.recent) ? b.recent : []).map(function (l) {
          return { loc: l, tag: 'Recent' };
        }),
      );
      S.sel = 0;
      render();
      if (!S.current) runCheck();
    }

    load();
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
