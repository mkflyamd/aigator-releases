/**
 * onboarding.js — Guided onboarding tour for Gator
 *
 * Self-contained module: step data, rendering, navigation, persistence.
 * Follows the same pattern as gator-empty-state.js (factory functions
 * returning HTML strings, no framework).
 *
 * NOTE: All HTML is static/hardcoded content only — no user input is
 * rendered as HTML. This follows the same pattern as gator-empty-state.js
 * and app.js throughout the codebase.
 *
 * Public API (called from app.js):
 *   renderOnboarding(container)   — mount the tour into a DOM element
 *   isOnboardingDismissed()       — true if the user completed/dismissed
 *   resetOnboarding()             — clear all persisted state
 */

/* ══════════════════════════════════════════════════════════
   Section 1 — Constants & Step Definitions
   ══════════════════════════════════════════════════════════ */

const OB_DISMISSED_KEY = 'onboarding-dismissed';
const OB_STEP_KEY      = 'onboarding-step';
const OB_PROJECT_KEY   = 'onboarding-project';

const OB_STEPS = [
  /* 0 — welcome */
  {
    id: 'welcome',
    title: 'Welcome to Gator',
    icon: '\u{1F40A}',
    color: '#4ade80',
    act: 'read',
    description: '<ul class="ob-bullets"><li>Your <strong>Integrated Work Environment</strong> — all your tools in one place</li><li>Email, calendar, Jira, Confluence, Teams and more</li><li>Try each skill for real using the <strong>prompt bar</strong> on the right</li></ul>',
    skillId: null,
    simulated: null,
    tryPrompt: null
  },

  /* 1 — connect */
  {
    id: 'connect',
    title: 'Connect Your Tools',
    icon: '\u{2699}',
    color: '#94a3b8',
    act: 'read',
    description: '<ul class="ob-bullets"><li>Click the <strong>gear icon</strong> in the top-right to open Settings</li><li>Connect <strong>Microsoft 365</strong>, <strong>Jira</strong>, <strong>Confluence</strong>, and more</li><li>The more you connect, the more Gator can do for you</li></ul>',
    skillId: null,
    simulated: null,
    tryPrompt: null
  },

  /* 2 — call a skill */
  {
    id: 'call-skill',
    title: 'Call a Skill',
    icon: '/',
    color: '#a78bfa',
    act: 'read',
    description: '<ul class="ob-bullets"><li>Type <code>/</code> followed by the skill name in the prompt bar</li><li><code>/gator</code> is your general-purpose assistant</li><li>Or click the <strong>+</strong> button to browse available skills</li></ul>',
    skillId: null,
    simulated: null,
    tryPrompt: '/gator What can you help me with?'
  },

  /* 2 — email */
  {
    id: 'email',
    title: 'Read Your Email',
    icon: '\u{1F4E7}',
    color: '#3b82f6',
    act: 'read',
    description: '<ul class="ob-bullets"><li>Use <code>/email</code> to check your <strong>Outlook inbox</strong></li><li>Summarises unread messages for quick triage</li><li>Search for emails by sender or topic</li></ul>',
    skillId: 'email',
    tryPrompt: '/email Check my email',
    simulated: [
      '<div class="ob-demo-label">Sample inbox for <strong class="ob-project-name"></strong></div>',
      '<div class="ob-demo-rows">',
        '<div class="ob-demo-row" style="border-left-color:#3b82f6">',
          '<div class="ob-demo-meta">Sarah Chen &middot; 9:14 AM</div>',
          '<div class="ob-demo-text">Q3 roadmap — updated priorities &amp; timeline</div>',
        '</div>',
        '<div class="ob-demo-row" style="border-left-color:#3b82f6">',
          '<div class="ob-demo-meta">DevOps Team &middot; 8:47 AM</div>',
          '<div class="ob-demo-text">Deploy pipeline failed — build #1287</div>',
        '</div>',
        '<div class="ob-demo-row" style="border-left-color:#3b82f6">',
          '<div class="ob-demo-meta">Alex Rivera &middot; Yesterday</div>',
          '<div class="ob-demo-text">Design review notes — mobile nav</div>',
        '</div>',
      '</div>'
    ].join('')
  },

  /* 2 — calendar */
  {
    id: 'calendar',
    title: 'Check Your Calendar',
    icon: '\u{1F4C5}',
    color: '#f59e0b',
    act: 'read',
    description: '<ul class="ob-bullets"><li>Use <code>/calendar</code> to see <strong>today\'s meetings</strong></li><li>Find free slots and check availability</li><li>Schedule new meetings right here</li></ul>',
    skillId: 'calendar',
    tryPrompt: '/calendar What meetings do I have today?',
    simulated: [
      '<div class="ob-demo-label">Today\'s meetings for <strong class="ob-project-name"></strong></div>',
      '<div class="ob-demo-rows">',
        '<div class="ob-demo-row" style="border-left-color:#f59e0b">',
          '<div class="ob-demo-meta">9:00 &ndash; 9:45 AM</div>',
          '<div class="ob-demo-text">Sprint Planning</div>',
        '</div>',
        '<div class="ob-demo-row" style="border-left-color:#f59e0b">',
          '<div class="ob-demo-meta">11:30 AM &ndash; 12:00 PM</div>',
          '<div class="ob-demo-text">1:1 with Manager</div>',
        '</div>',
        '<div class="ob-demo-row" style="border-left-color:#f59e0b">',
          '<div class="ob-demo-meta">2:00 &ndash; 3:00 PM</div>',
          '<div class="ob-demo-text">Design Review</div>',
        '</div>',
      '</div>'
    ].join('')
  },

  /* 3 — teams */
  {
    id: 'teams',
    title: 'Read Teams Messages',
    icon: '\u{1F4AC}',
    color: '#a78bfa',
    act: 'read',
    description: '<ul class="ob-bullets"><li>Use <code>/teams</code> to read your <strong>messages and channels</strong></li><li>Send new messages to people or channels</li><li>Post to saved messages for quick notes</li></ul>',
    skillId: 'teams',
    tryPrompt: '/teams Any new messages?',
    simulated: [
      '<div class="ob-demo-label">Recent Teams messages</div>',
      '<div class="ob-demo-rows">',
        '<div class="ob-demo-row" style="border-left-color:#a78bfa">',
          '<div class="ob-demo-meta">Dana Park &middot; #frontend</div>',
          '<div class="ob-demo-text">Can someone review the nav PR? I pushed the fix.</div>',
        '</div>',
        '<div class="ob-demo-row" style="border-left-color:#a78bfa">',
          '<div class="ob-demo-meta">Jordan Lee &middot; #backend</div>',
          '<div class="ob-demo-text">API rate-limit config updated — deploy after lunch.</div>',
        '</div>',
      '</div>'
    ].join('')
  },

  /* 4 — jira */
  {
    id: 'jira',
    title: 'Browse Jira Tickets',
    icon: '\u{1F3AB}',
    color: '#ef4444',
    act: 'read',
    description: '<ul class="ob-bullets"><li>Use <code>/jira</code> to list your <strong>open tickets</strong></li><li>Get full details on any issue by key</li><li>Filter by project, status, or assignee</li></ul>',
    skillId: 'jira',
    tryPrompt: '/jira Show my open tickets',
    simulated: [
      '<div class="ob-demo-label">Open tickets for <strong class="ob-project-name"></strong></div>',
      '<div class="ob-demo-rows">',
        '<div class="ob-demo-row" style="border-left-color:#ef4444">',
          '<div class="ob-demo-meta">PROJ-142 &middot; High</div>',
          '<div class="ob-demo-text">Auth token refresh fails on expired sessions</div>',
        '</div>',
        '<div class="ob-demo-row" style="border-left-color:#ef4444">',
          '<div class="ob-demo-meta">PROJ-138 &middot; Medium</div>',
          '<div class="ob-demo-text">Add retry logic to webhook delivery</div>',
        '</div>',
        '<div class="ob-demo-row" style="border-left-color:#ef4444">',
          '<div class="ob-demo-meta">PROJ-135 &middot; Low</div>',
          '<div class="ob-demo-text">Update API docs for v2 endpoints</div>',
        '</div>',
      '</div>'
    ].join('')
  },

  /* 5 — confluence */
  {
    id: 'confluence',
    title: 'Search Confluence',
    icon: '\u{1F4DD}',
    color: '#06b6d4',
    act: 'read',
    description: '<ul class="ob-bullets"><li>Use <code>/confluence</code> to search your <strong>spaces</strong></li><li>Find docs, RFCs, and runbooks in seconds</li><li>Get page summaries without switching apps</li></ul>',
    skillId: 'confluence',
    tryPrompt: '/confluence Search for onboarding guide',
    simulated: [
      '<div class="ob-demo-label">Confluence pages for <strong class="ob-project-name"></strong></div>',
      '<div class="ob-demo-rows">',
        '<div class="ob-demo-row" style="border-left-color:#06b6d4">',
          '<div class="ob-demo-meta">Engineering &middot; Updated 2 days ago</div>',
          '<div class="ob-demo-text">API Architecture &amp; Rate-Limit Policy</div>',
        '</div>',
        '<div class="ob-demo-row" style="border-left-color:#06b6d4">',
          '<div class="ob-demo-meta">Team Wiki &middot; Updated last week</div>',
          '<div class="ob-demo-text">Sprint Retrospective — May 2026</div>',
        '</div>',
      '</div>'
    ].join('')
  },

  /* 6 — pinning */
  {
    id: 'pinning',
    title: 'Pin Items for Context',
    icon: '\u{1F4CC}',
    color: '#f59e0b',
    act: 'pin',
    description: '<div id="ob-pin-guide"><div class="ob-pin-step ob-pin-active" id="ob-pin-s1"><span class="ob-pin-num">1</span><span class="ob-pin-text">Click the <strong>email icon</strong> in the skill rail to open your inbox</span></div><div class="ob-pin-step" id="ob-pin-s2"><span class="ob-pin-num">2</span><span class="ob-pin-text"><strong>Right-click</strong> any email \u2192 choose <em>Pin to tab</em></span></div><div class="ob-pin-step" id="ob-pin-s3"><span class="ob-pin-num">3</span><span class="ob-pin-text">Ask Gator a question about your pinned item</span></div></div><div id="ob-pin-tryit" class="ob-pin-tryit-area"></div>',
    skillId: null,
    tryPrompt: null,
    simulated: null
  },

  /* 7 — jira-write */
  {
    id: 'jira-write',
    title: 'Create a Jira Ticket',
    icon: '\u{1F3AB}',
    color: '#ef4444',
    act: 'write',
    description: '<ul class="ob-bullets"><li>Use <code>/jira</code> to <strong>draft tickets</strong> from a description</li><li>Gator fills in project, type, and priority</li><li>Review before submitting</li></ul>',
    skillId: 'jira',
    tryPrompt: '/jira Create a ticket: Add retry logic to payment service',
    simulated: [
      '<div class="ob-demo-label">Draft ticket for <strong class="ob-project-name"></strong></div>',
      '<div class="ob-demo-draft">',
        '<div class="ob-draft-field"><span class="ob-draft-key">Project</span><span class="ob-draft-val">PROJ</span></div>',
        '<div class="ob-draft-field"><span class="ob-draft-key">Type</span><span class="ob-draft-val">Task</span></div>',
        '<div class="ob-draft-field"><span class="ob-draft-key">Summary</span><span class="ob-draft-val">Add retry logic to payment service</span></div>',
        '<div class="ob-draft-field"><span class="ob-draft-key">Priority</span><span class="ob-draft-val">Medium</span></div>',
        '<div class="ob-draft-field"><span class="ob-draft-key">Assignee</span><span class="ob-draft-val">You</span></div>',
      '</div>'
    ].join('')
  },

  /* 8 — confluence-write */
  {
    id: 'confluence-write',
    title: 'Write to Confluence',
    icon: '\u{1F4DD}',
    color: '#06b6d4',
    act: 'write',
    description: '<ul class="ob-bullets"><li>Use <code>/confluence</code> to <strong>create or update</strong> pages</li><li>Gator drafts the content, you choose the space</li><li>Great for meeting notes, status updates, RFCs</li></ul>',
    skillId: 'confluence',
    tryPrompt: '/confluence Draft a page titled Meeting Notes for today in my personal space',
    simulated: [
      '<div class="ob-demo-label">Draft page for <strong class="ob-project-name"></strong></div>',
      '<div class="ob-demo-draft">',
        '<div class="ob-draft-field"><span class="ob-draft-key">Space</span><span class="ob-draft-val">Engineering</span></div>',
        '<div class="ob-draft-field"><span class="ob-draft-key">Title</span><span class="ob-draft-val">Sprint Retro Notes — May 2026</span></div>',
        '<div class="ob-draft-field"><span class="ob-draft-key">Status</span><span class="ob-draft-val">Draft — ready to publish</span></div>',
      '</div>'
    ].join('')
  },

  /* 9 — document */
  {
    id: 'document',
    title: 'Create a Document',
    icon: '\u{1F4C4}',
    color: '#f97316',
    act: 'write',
    description: '<ul class="ob-bullets"><li>Use <code>/docx</code> for Word, <code>/ppt</code> for PowerPoint, <code>/excel</code> for Excel</li><li>Just describe what you need in plain language</li><li>Gator generates the file ready to download</li></ul>',
    skillId: 'docx',
    tryPrompt: '/docx Create a one-page project status report template with sections for highlights, risks, and next steps',
    simulated: [
      '<div class="ob-demo-label">What you can create</div>',
      '<div class="ob-demo-rows">',
        '<div class="ob-demo-row" style="border-left-color:#f97316">',
          '<div class="ob-demo-meta">Word</div>',
          '<div class="ob-demo-text">Meeting notes, proposals, status reports</div>',
        '</div>',
        '<div class="ob-demo-row" style="border-left-color:#f97316">',
          '<div class="ob-demo-meta">PowerPoint</div>',
          '<div class="ob-demo-text">Slide decks, presentations, pitch materials</div>',
        '</div>',
        '<div class="ob-demo-row" style="border-left-color:#f97316">',
          '<div class="ob-demo-meta">Excel</div>',
          '<div class="ob-demo-text">Spreadsheets, data tables, charts</div>',
        '</div>',
      '</div>',
      '<div class="ob-also-note">Also supports <strong>PowerPoint</strong> (<code>/ppt</code>) and <strong>Excel</strong> (<code>/excel</code>) — just mention them in chat.</div>'
    ].join('')
  },

  /* 11 — done */
  {
    id: 'done',
    title: "You're Ready!",
    icon: '\u{1F389}',
    color: '#4ade80',
    act: 'done',
    description: '<ul class="ob-bullets"><li>Type <code>/skill</code> to activate any skill or pick an action</li><li>Use <code>@</code> to mention a colleague</li><li><strong>Pin</strong> items for context, <code>Shift+{</code> to reference</li><li>Explore the <strong>skill bar</strong> on the left for more</li></ul>',
    skillId: null,
    simulated: null,
    tryPrompt: null
  }
];


/* ══════════════════════════════════════════════════════════
   Section 2 — Progress Bar & Navigation Rendering
   ══════════════════════════════════════════════════════════ */

function _obActLabel(act) {
  switch (act) {
    case 'read':  return { text: 'Read',  color: 'var(--text-sub)' };
    case 'pin':   return { text: 'Pin',   color: '#f59e0b' };
    case 'write': return { text: 'Write', color: '#22c55e' };
    default:      return { text: '',      color: 'var(--text-sub)' };
  }
}

function _obRenderProgress(currentStep) {
  const total = OB_STEPS.length;
  const pct   = Math.round(((currentStep + 1) / total) * 100);

  let dots = '';
  for (let i = 0; i < total; i++) {
    const cls = i < currentStep ? 'ob-dot ob-dot-done'
              : i === currentStep ? 'ob-dot ob-dot-active'
              : 'ob-dot';
    dots += '<span class="' + cls + '"></span>';
  }

  return [
    '<div class="ob-progress">',
      '<div class="ob-progress-header">',
        '<span class="ob-progress-label">Getting to know Gator</span>',
        '<span class="ob-progress-count">Step ' + (currentStep + 1) + ' of ' + total + '</span>',
      '</div>',
      '<div class="ob-progress-track">',
        '<div class="ob-progress-fill" style="width:' + pct + '%"></div>',
      '</div>',
      '<div class="ob-dots">' + dots + '</div>',
    '</div>'
  ].join('');
}

function _obRenderNav(currentStep) {
  var isFirst = currentStep === 0;
  var isLast  = currentStep === OB_STEPS.length - 1;
  var prevTxt = isFirst ? '' : '\u2190 Previous';
  var nextTxt = isLast ? 'Get started' : 'Next \u2192';

  return [
    '<div class="ob-nav">',
      '<button class="ob-nav-prev" id="ob-prev">' + prevTxt + '</button>',
      '<div class="ob-nav-right">',
        '<button class="ob-nav-dismiss" id="ob-dismiss">Dismiss tour</button>',
        '<button class="ob-nav-next" id="ob-next">' + nextTxt + '</button>',
      '</div>',
    '</div>'
  ].join('');
}


/* ══════════════════════════════════════════════════════════
   Section 3 — Step Content Rendering
   ══════════════════════════════════════════════════════════ */



function _obRenderDone() {
  var skillIds = ['email', 'calendar', 'teams', 'jira', 'confluence', 'docx'];
  var hasMap = typeof SKILL_MAP !== 'undefined';

  var grid = skillIds.map(function(id) {
    var skill     = hasMap ? SKILL_MAP[id] : null;
    var label     = skill ? skill.label : id;
    var connected = skill ? skill.connected : false;
    var dotCls    = connected ? 'ob-status-dot ob-dot-green' : 'ob-status-dot ob-dot-gray';
    var statusTxt = connected ? 'Connected' : 'Not connected';
    return [
      '<div class="ob-done-row">',
        '<span class="ob-done-skill">' + label + '</span>',
        '<span class="ob-done-status"><span class="' + dotCls + '"></span>' + statusTxt + '</span>',
      '</div>'
    ].join('');
  }).join('');

  return [
    '<div class="ob-done-summary">',
    '<div class="ob-demo-label">🐊 Here\'s your connection status:</div>',
    '<div class="ob-done-grid">' + grid + '</div>',
    '<div class="ob-done-tips">',
      '<p><strong>Tips to get started:</strong></p>',
      '<ul>',
        '<li>Type <code>/skill</code> to activate any skill or pick an action</li>',
        '<li>Use <code>@</code> to mention a colleague in context</li>',
        '<li>Pin items to give Gator context for follow-up questions</li>',
        '<li>Press <code>Shift+{</code> to open the pin panel</li>',
      '</ul>',
    '</div>',
    '</div>'
  ].join('');
}

function _obRenderStepContent(step, currentStep) {
  var actInfo  = _obActLabel(step.act);
  var bgTint   = step.color + '18'; // 18 hex = ~10% opacity

  var actBadge = '';

  var desc = step.description;

  // Special content for done step only
  var demoHtml = '';
  if (step.id === 'done') {
    demoHtml = _obRenderDone();
  }

  // "Try it" button — pre-fills the prompt bar
  var tryHtml = '';
  if (step.tryPrompt) {
    tryHtml = '<div class="ob-try-wrapper"><span class="ob-try-label">Try it</span><hr class="ob-try-divider"/><button class="ob-try-btn" id="ob-try" data-prompt="' + step.tryPrompt.replace(/"/g, '&quot;') + '">' + step.tryPrompt + '</button></div>';
  }

  return [
    '<div class="ob-step-content">',
      '<div class="ob-step-icon" style="background:' + bgTint + ';border-color:' + step.color + '30">',
        '<span>' + step.icon + '</span>',
      '</div>',
      '<div class="ob-step-header">',
        '<h3 class="ob-step-title" style="color:' + step.color + '">' + step.title + '</h3>',
        actBadge,
      '</div>',
      '<p class="ob-step-desc">' + desc + '</p>',
      demoHtml,
      tryHtml,
    '</div>'
  ].join('');
}


/* ══════════════════════════════════════════════════════════
   Section 4 — Main Render Loop & Navigation
   ══════════════════════════════════════════════════════════ */

var _obCurrentStep = 0;

function _obSaveStep() {
  localStorage.setItem(OB_STEP_KEY, String(_obCurrentStep));
}


/** Entry point — called from app.js */
function renderOnboarding(container) {
  var saved = parseInt(localStorage.getItem(OB_STEP_KEY), 10);
  if (!isNaN(saved) && saved >= 0 && saved < OB_STEPS.length) {
    _obCurrentStep = saved;
  } else {
    _obCurrentStep = 0;
  }
  _obRenderCurrentStep(container);
}

function _obRenderCurrentStep(container) {
  var step = OB_STEPS[_obCurrentStep];

  // Build full layout: progress + body + nav
  // All HTML here is static/hardcoded — safe for innerHTML assignment
  container.innerHTML =                                     // eslint-disable-line no-unsanitized/property
    '<div class="ob-container">' +
      _obRenderProgress(_obCurrentStep) +
      '<div class="ob-body">' +
        _obRenderStepContent(step, _obCurrentStep) +
      '</div>' +
      _obRenderNav(_obCurrentStep) +
    '</div>';

  // Bind navigation
  var nextBtn    = document.getElementById('ob-next');
  var prevBtn    = document.getElementById('ob-prev');
  var dismissBtn = document.getElementById('ob-dismiss');

  if (nextBtn)    nextBtn.addEventListener('click',    function() { _obNext(container); });
  if (prevBtn)    prevBtn.addEventListener('click',    function() { _obPrev(container); });
  if (dismissBtn) dismissBtn.addEventListener('click', function() { _obDismiss(container); });

  // "Try it" button: pre-fill the prompt bar, then go into hibernation
  var tryBtn = document.getElementById('ob-try');
  if (tryBtn) {
    tryBtn.addEventListener('click', function() {
      var prompt = tryBtn.getAttribute('data-prompt');
      var chatInput = document.getElementById('chat-input');
      if (chatInput && prompt) {
        chatInput.textContent = prompt;
        chatInput.focus();
        // Place cursor at end
        var range = document.createRange();
        range.selectNodeContents(chatInput);
        range.collapse(false);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
      // Enter hibernation — gator waits while chat responds
      _obHibernate(container);
    });
  }

  // Pinning step: interactive coach marks
  if (step.id === 'pinning') {
    _obStartPinCoaching();
  }

  // Connect step: coach mark on settings gear in the dock
  if (step.id === 'connect') {
    var settingsBtn = document.getElementById('dock-settings') || document.getElementById('settings-trigger');
    if (settingsBtn) {
      setTimeout(function() {
        _obShowCoachBubble(settingsBtn, 'Click here to open <strong>Settings</strong>', 'right');
      }, 200);
    }
  }
}

/* ── Pinning step interactive coaching ────────────────── */

var _obPinCoachCleanup = null;

function _obClearPinCoaching() {
  if (_obPinCoachCleanup) {
    _obPinCoachCleanup();
    _obPinCoachCleanup = null;
  }
  document.querySelectorAll('.ob-coach-bubble').forEach(function(el) { el.remove(); });
}

function _obShowCoachBubble(targetEl, text, position) {
  document.querySelectorAll('.ob-coach-bubble').forEach(function(el) { el.remove(); });

  var rect = targetEl.getBoundingClientRect();
  var bubble = document.createElement('div');
  bubble.className = 'ob-coach-bubble ob-coach-pulse';
  bubble.innerHTML = '<div class="ob-coach-bubble-caret"></div><span>' + text + '</span><button class="ob-coach-close">&times;</button>';
  bubble.querySelector('.ob-coach-close').addEventListener('click', function(e) {
    e.stopPropagation();
    bubble.remove();
  });

  if (position === 'right') {
    var idealTop = rect.top + rect.height / 2 - 18;
    // Keep bubble on screen — at least 75px from bottom edge
    bubble.style.top = Math.min(idealTop, window.innerHeight - 75) + 'px';
    bubble.style.left = (rect.right + 14) + 'px';
    bubble.classList.add('ob-coach-right');
  } else if (position === 'bottom') {
    var bubbleWidth = 220;
    var centerX = rect.left + rect.width / 2;
    bubble.style.top = (rect.bottom + 12) + 'px';
    bubble.style.left = Math.max(8, centerX - bubbleWidth / 2) + 'px';
    bubble.style.width = bubbleWidth + 'px';
    bubble.classList.add('ob-coach-bottom');
  }

  document.body.appendChild(bubble);
  return bubble;
}

function _obPinSetActiveStep(stepNum) {
  for (var i = 1; i <= 3; i++) {
    var el = document.getElementById('ob-pin-s' + i);
    if (el) {
      el.classList.toggle('ob-pin-active', i === stepNum);
      el.classList.toggle('ob-pin-done', i < stepNum);
    }
  }
}

function _obStartPinCoaching() {
  _obClearPinCoaching();

  // Find the email button in the skill rail (retry with delay for async rail render)
  var emailBtn = document.querySelector('[data-skill-id="email"]');
  if (!emailBtn) {
    setTimeout(function() { _obStartPinCoaching(); }, 500);
    return;
  }

  // Step 1: Point to email icon
  _obPinSetActiveStep(1);
  _obShowCoachBubble(emailBtn, 'Click the <strong>email icon</strong> to open your inbox', 'right');

  var observer = null;
  var itemObserver = null;

  // Watch for third pane to open
  observer = new MutationObserver(function() {
    var thirdPane = document.getElementById('third-pane');
    if (thirdPane && thirdPane.classList.contains('is-open')) {
      observer.disconnect();
      // Move to step 2 — wait for email list to populate
      _obPinSetActiveStep(2);
      document.querySelectorAll('.ob-coach-bubble').forEach(function(el) { el.remove(); });

      // Watch for list items to appear
      var listCol = document.getElementById('tp-list-col');
      if (!listCol) return;

      var showStep2Coach = function() {
        var firstItem = listCol.querySelector('.tp-item');
        if (firstItem) {
          if (itemObserver) itemObserver.disconnect();
          _obShowCoachBubble(firstItem, '<strong>Right-click</strong> this email \u2192 <em>Pin to tab</em>', 'bottom');
        }
      };

      // Check if items already exist
      if (listCol.querySelector('.tp-item')) {
        setTimeout(showStep2Coach, 300);
      } else {
        // Observe for items being added
        itemObserver = new MutationObserver(function() {
          if (listCol.querySelector('.tp-item')) {
            setTimeout(showStep2Coach, 300);
          }
        });
        itemObserver.observe(listCol, { childList: true, subtree: true });
      }
    }
  });

  var thirdPane = document.getElementById('third-pane');
  if (thirdPane) {
    // Check if already open
    if (thirdPane.classList.contains('is-open')) {
      // Already open — skip to step 2
      _obPinSetActiveStep(2);
      document.querySelectorAll('.ob-coach-bubble').forEach(function(el) { el.remove(); });
      var listCol = document.getElementById('tp-list-col');
      if (listCol) {
        setTimeout(function() {
          var firstItem = listCol.querySelector('.tp-item');
          if (firstItem) {
            _obShowCoachBubble(firstItem, '<strong>Right-click</strong> this email \u2192 <em>Pin to tab</em>', 'bottom');
          }
        }, 300);
      }
    } else {
      observer.observe(thirdPane, { attributes: true, attributeFilter: ['class'] });
    }
  }

  // Watch pin orb badge for pin events → advance to step 3
  var pinBadge = document.getElementById('pin-orb-badge');
  var pinObserver = null;
  if (pinBadge) {
    pinObserver = new MutationObserver(function() {
      if (!pinBadge.classList.contains('hidden')) {
        pinObserver.disconnect();
        _obPinSetActiveStep(3);
        document.querySelectorAll('.ob-coach-bubble').forEach(function(el) { el.remove(); });

        // Show Try It button for step 3
        var tryArea = document.getElementById('ob-pin-tryit');
        if (tryArea) {
          var prompt = '/gator Summarise the email I just pinned';
          tryArea.innerHTML =
            '<div class="ob-try-wrapper" style="margin-top:12px">' +
              '<span class="ob-try-label">Try it</span>' +
              '<hr class="ob-try-divider"/>' +
              '<button class="ob-try-btn" id="ob-pin-try-btn" data-prompt="' + prompt + '">' + prompt + '</button>' +
            '</div>';

          document.getElementById('ob-pin-try-btn')?.addEventListener('click', function() {
            var chatInput = document.getElementById('chat-input');
            if (chatInput) {
              chatInput.textContent = prompt;
              chatInput.focus();
              var range = document.createRange();
              range.selectNodeContents(chatInput);
              range.collapse(false);
              var sel = window.getSelection();
              sel.removeAllRanges();
              sel.addRange(range);
            }
          });
        }
      }
    });
    pinObserver.observe(pinBadge, { attributes: true, attributeFilter: ['class'] });
    // Also watch text changes in case badge was already visible
    pinObserver.observe(pinBadge, { characterData: true, childList: true, subtree: true });
  }

  _obPinCoachCleanup = function() {
    if (observer) observer.disconnect();
    if (itemObserver) itemObserver.disconnect();
    if (pinObserver) pinObserver.disconnect();
    document.querySelectorAll('.ob-coach-bubble').forEach(function(el) { el.remove(); });
  };
}

/* ── Hibernation state ──────────────────────────────── */

function _obHibernate(container) {
  // Show the gator peeking in hibernation mode while chat responds
  var gatorHtml = typeof gatorEmptyState === 'function'
    ? gatorEmptyState([{ icon: '💤', text: 'Watching Gator work...' }])
    : '<div style="font-size:3rem;text-align:center;padding:2rem">🐊💤</div>';

  container.innerHTML =
    '<div class="ob-container">' +
      _obRenderProgress(_obCurrentStep) +
      '<div class="ob-body ob-hibernate">' +
        gatorHtml +
      '</div>' +
      '<div class="ob-nav">' +
        '<button class="ob-nav-prev" id="ob-prev">\u2190 Previous</button>' +
        '<div class="ob-nav-right">' +
          '<button class="ob-nav-dismiss" id="ob-dismiss">Dismiss tour</button>' +
          '<button class="ob-nav-next" id="ob-next">Next step \u2192</button>' +
        '</div>' +
      '</div>' +
    '</div>';

  // Bind navigation in hibernation
  document.getElementById('ob-next')?.addEventListener('click', function() {
    _obCloseThirdPane();
    _obCurrentStep++;
    _obSaveStep();
    _obRenderCurrentStep(container);
  });
  document.getElementById('ob-prev')?.addEventListener('click', function() { _obPrev(container); });
  document.getElementById('ob-dismiss')?.addEventListener('click', function() { _obDismiss(container); });
}

function _obCloseThirdPane() {
  if (typeof closeThirdPane === 'function') {
    var tp = document.getElementById('third-pane');
    if (tp && tp.classList.contains('is-open')) closeThirdPane();
  }
}

function _obPrev(container) {
  if (_obCurrentStep <= 0) return;
  _obClearPinCoaching();
  _obCloseThirdPane();
  _obCurrentStep--;
  _obSaveStep();
  _obRenderCurrentStep(container);
}

function _obNext(container) {
  _obClearPinCoaching();
  _obCloseThirdPane();
  // Last step -> dismiss
  if (_obCurrentStep >= OB_STEPS.length - 1) {
    _obDismiss(container);
    return;
  }

  _obCurrentStep++;
  _obSaveStep();
  _obRenderCurrentStep(container);
}

function _obDismiss(container) {
  _obClearPinCoaching();
  localStorage.setItem(OB_DISMISSED_KEY, 'true');
  localStorage.removeItem(OB_STEP_KEY);
  sessionStorage.removeItem(OB_PROJECT_KEY);
  container.innerHTML = '';                                 // eslint-disable-line no-unsanitized/property
  // Close the panel
  closeOnboardingPanel();
  // Show coach mark pointing to the ? help button
  _obShowHelpCoachMark();
}

function _obShowHelpCoachMark() {
  // Only show once
  if (localStorage.getItem('ob-help-coach-shown')) return;
  localStorage.setItem('ob-help-coach-shown', '1');

  var helpBtn = document.getElementById('dock-help') || document.getElementById('help-trigger');
  if (!helpBtn) return;

  var bubble = _obShowCoachBubble(helpBtn, 'Click <strong>?</strong> \u2192 <strong>Restart Tour</strong> to revisit anytime', 'right');
  if (!bubble) return;

  // Auto-dismiss after 5 seconds
  var dismiss = function() {
    if (bubble.parentNode) bubble.remove();
    document.removeEventListener('click', dismiss);
  };
  setTimeout(function() {
    document.addEventListener('click', dismiss);
  }, 200);
  setTimeout(dismiss, 5000);
}

/** Open the onboarding side panel */
function openOnboardingPanel() {
  var panel = document.getElementById('onboarding-container');
  var main = panel ? panel.closest('.main') : null;
  if (panel) panel.classList.add('is-open');
  if (main) main.classList.add('ob-panel-open');
}

/** Close the onboarding side panel */
function closeOnboardingPanel() {
  var panel = document.getElementById('onboarding-container');
  var main = panel ? panel.closest('.main') : null;
  if (panel) panel.classList.remove('is-open');
  if (main) main.classList.remove('ob-panel-open');
}


/** Returns true if the user has completed or dismissed the tour */
function isOnboardingDismissed() {
  return localStorage.getItem(OB_DISMISSED_KEY) === 'true';
}

/** Clears all onboarding persisted state (localStorage + sessionStorage) */
function resetOnboarding() {
  localStorage.removeItem(OB_DISMISSED_KEY);
  localStorage.removeItem(OB_STEP_KEY);
  localStorage.removeItem('ob-help-coach-shown');
  sessionStorage.removeItem(OB_PROJECT_KEY);
}
