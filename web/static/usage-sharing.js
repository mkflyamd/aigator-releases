// Usage sharing: first-run notice, locked Settings toggle and delivery status.
(function () {
  'use strict';

  var NOTICE_TITLE = 'AI Gator collects usage analytics';
  var NOTICE_INTRO =
    'To understand how AI Gator is used and improve it, it collects usage analytics.';
  var FACTS = [
    [
      'What is sent',
      [
        'Account info',
        'A random ID for this install',
        'Your operating system and AI Gator version',
        'Counts of messages, tokens, errors, and the features, tools and AI model families you use',
      ],
    ],
    ['Never sent', 'Your messages, prompts, files or paths.'],
  ];
  var STATUS_TEXT = {
    waiting: 'Waiting. The first report has not been sent yet.',
    delayed: "Delayed. Couldn't send, trying again.",
    signin: 'Sign-in needed. Sign in with your work account to send reports.',
    sent: 'Sent.',
  };

  var ACK_KEY = 'aigator.usageNoticeAck';
  var current = null;
  var noticeHost = null;
  var noticeOpener = null;

  function el(tag, props, children) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function (key) {
      if (key === 'text') node.textContent = props[key];
      else if (key === 'class') node.className = props[key];
      else node.setAttribute(key, props[key]);
    });
    (children || []).forEach(function (child) {
      node.appendChild(child);
    });
    return node;
  }

  async function fetchStatus() {
    var r = await fetch('/api/usage-sharing');
    if (!r.ok) throw new Error('status ' + r.status);
    return r.json();
  }

  function statusLine(status) {
    var text = STATUS_TEXT[status.status] || '';
    if ((status.status === 'sent' || status.status === 'delayed') && status.last_sent_at) {
      var when = new Date(status.last_sent_at);
      if (!isNaN(when)) text += ' Last report ' + when.toLocaleString() + '.';
    }
    return text;
  }

  function render(status) {
    current = status;
    var section = document.getElementById('usage-sharing-section');
    if (!section) return;
    section.hidden = !status.available;
    var line = document.getElementById('usage-sharing-status');
    if (line) line.textContent = statusLine(status);
  }

  async function refresh() {
    try {
      render(await fetchStatus());
    } catch (_) {}
  }

  function setInert(host, value) {
    Array.prototype.forEach.call(document.body.children, function (child) {
      if (child !== host && child.tagName !== 'SCRIPT') child.inert = value;
    });
  }

  function closeNotice(restoreFocus) {
    if (!noticeHost) return;
    setInert(noticeHost, false);
    noticeHost.remove();
    noticeHost = null;
    if (restoreFocus && noticeOpener && document.contains(noticeOpener)) noticeOpener.focus();
  }

  function acknowledged() {
    try {
      return window.localStorage.getItem(ACK_KEY) === '1';
    } catch (_) {
      return false;
    }
  }

  function acknowledge() {
    try {
      window.localStorage.setItem(ACK_KEY, '1');
    } catch (_) {}
    closeNotice(true);
  }

  function openNotice(firstRun) {
    if (noticeHost) return;
    noticeOpener = document.activeElement;

    var titleEl = el('h3', {
      id: 'usage-notice-title',
      class: 'usage-notice-title',
      tabindex: '-1',
      text: NOTICE_TITLE,
    });
    var facts = el('dl', { class: 'usage-notice-facts' });
    FACTS.forEach(function (fact) {
      facts.appendChild(el('dt', { text: fact[0] }));
      var dd = el('dd');
      if (Array.isArray(fact[1])) {
        dd.appendChild(
          el(
            'ul',
            {},
            fact[1].map(function (item) {
              return el('li', { text: item });
            }),
          ),
        );
      } else {
        dd.textContent = fact[1];
      }
      facts.appendChild(dd);
    });

    var actions = el('div', { class: 'confirm-modal-actions usage-notice-actions' });
    var okBtn = el('button', {
      type: 'button',
      class: 'btn-primary',
      text: firstRun ? 'OK' : 'Close',
    });
    okBtn.addEventListener('click', function () {
      if (firstRun) acknowledge();
      else closeNotice(true);
    });
    actions.appendChild(okBtn);

    var box = el(
      'div',
      {
        class: 'confirm-modal-box usage-notice-box',
        role: 'dialog',
        'aria-modal': 'true',
        'aria-labelledby': 'usage-notice-title',
        'aria-describedby': 'usage-notice-intro',
      },
      [
        titleEl,
        el('p', { id: 'usage-notice-intro', class: 'usage-notice-intro', text: NOTICE_INTRO }),
        facts,
        actions,
      ],
    );
    var host = el('div', { class: 'confirm-modal-overlay usage-notice-overlay' }, [box]);
    noticeHost = host;
    document.body.appendChild(host);
    setInert(host, true);
    titleEl.focus();

    host.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeNotice(true);
        return;
      }
      if (e.key !== 'Tab') return;
      var buttons = Array.prototype.slice.call(host.querySelectorAll('button'));
      var active = document.activeElement;
      if (e.shiftKey && (active === buttons[0] || active === titleEl)) {
        e.preventDefault();
        buttons[buttons.length - 1].focus();
      } else if (!e.shiftKey && active === buttons[buttons.length - 1]) {
        e.preventDefault();
        buttons[0].focus();
      }
    });
  }

  function anotherOverlayOpen() {
    if (document.querySelector('.confirm-modal-overlay')) return true;
    var onboarding = document.getElementById('onboarding-container');
    return !!(onboarding && onboarding.children.length);
  }

  function offerFirstRunNotice(attempt) {
    if (attempt > 180 || !current || !current.available || acknowledged()) return;
    if (anotherOverlayOpen()) {
      setTimeout(function () {
        offerFirstRunNotice(attempt + 1);
      }, 10000);
      return;
    }
    openNotice(true);
  }

  function wireSettings() {
    var review = document.getElementById('usage-sharing-review');
    if (review) {
      review.addEventListener('click', function () {
        openNotice(false);
      });
    }
  }

  async function init() {
    wireSettings();
    try {
      render(await fetchStatus());
    } catch (_) {
      return;
    }
    setTimeout(function () {
      offerFirstRunNotice(0);
    }, 3000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
