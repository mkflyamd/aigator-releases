/* ── Client-side perf instrumentation (ephemeral, in-memory) ──────────────────
 * Records user-perceived timings (pane open -> first paint, thread open, poll
 * round-trips) into a bounded ring buffer on window.__gatorPerf. Nothing is
 * persisted and no message content is stored — only names + durations. Inspect
 * from the browser console with gatorPerf().
 */
(function _initGatorPerf() {
  const MAX = 500;
  const buf = [];
  function mark(name, ms, meta) {
    buf.push({ t: Date.now(), name, ms: Math.round(ms * 10) / 10, ...(meta || {}) });
    if (buf.length > MAX) buf.shift();
  }
  // Time a synchronous or async function and record its duration under `name`.
  async function measure(name, fn, meta) {
    const start = performance.now();
    try {
      return await fn();
    } finally {
      mark(name, performance.now() - start, meta);
    }
  }
  // Return a one-shot stopper: const done = gPerfStart('x'); ...; done({hit:true})
  function start(name) {
    const t0 = performance.now();
    return (meta) => {
      mark(name, performance.now() - t0, meta);
    };
  }
  function summary() {
    const byName = {};
    for (const s of buf) {
      (byName[s.name] = byName[s.name] || []).push(s.ms);
    }
    const rows = Object.entries(byName)
      .map(([name, arr]) => {
        const sorted = [...arr].sort((a, b) => a - b);
        const pct = (p) => sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * p))];
        return {
          name,
          count: arr.length,
          p50: pct(0.5),
          p95: pct(0.95),
          max: sorted[sorted.length - 1],
        };
      })
      .sort((a, b) => b.p95 - a.p95);
    if (console.table) console.table(rows);
    return rows;
  }
  window.__gatorPerf = { buf, mark, measure, start, summary };
  // Console convenience: gatorPerf() prints a p50/p95 table; gatorPerf(true) dumps raw samples.
  window.gatorPerf = (raw) => (raw ? buf.slice() : summary());
})();

/* ── Skill Registry ──────────────────────────────────── */
const ICON = (id) => `<img src="/static/icons/${id}.svg" class="skill-icon-img" alt="${id}" />`;

const SKILL_REGISTRY = [
  {
    id: 'gator',
    label: 'Gator',
    icon: ICON('aigator'),
    chipAlias: 'gator',
    category: 'AI',
    chipClass: 'chip-aigator',
    connected: true,
    actions: [
      {
        icon: '📋',
        label: "What's on my plate?",
        prompt:
          "Give me a briefing: check my email for unread messages, today's calendar events, any new Teams messages, and my open Jira tickets. Summarize everything concisely.",
        group: 'daily',
      },
      {
        icon: '📥',
        label: 'Check my email',
        prompt: 'Check my Outlook inbox for unread messages and summarize them',
        group: 'daily',
      },
      {
        icon: '📅',
        label: "Today's meetings",
        prompt:
          'What meetings do I have today? Show me my calendar with times, attendees, and any conflicts',
        group: 'daily',
      },
      {
        icon: '🔍',
        label: 'Find a doc about…',
        prompt: 'Search across Confluence, OneDrive, and OneNote for documents about ',
        inputHint: 'topic or keyword',
        group: 'search',
      },
      {
        icon: '👤',
        label: 'Who is…?',
        prompt: 'Look up this person and show their name, email, title, and department: ',
        inputHint: 'name',
        group: 'search',
      },
      {
        icon: '🎫',
        label: 'My open tickets',
        prompt: 'Show my open Jira tickets with status, priority, and assignee',
        group: 'search',
      },
      {
        icon: '🌐',
        label: 'Search the web',
        prompt: 'Search the web for ',
        inputHint: 'what to look up',
        group: 'search',
      },
    ],
  },
  {
    id: 'email',
    label: 'Outlook',
    icon: ICON('outlook'),
    chipAlias: 'outlook',
    category: 'Productivity',
    chipClass: 'chip-email',
    connected: false,
    actions: [
      { icon: '📥', label: 'Check my email', prompt: 'Check my Outlook inbox for unread messages' },
      {
        icon: '🔍',
        label: 'Search email for…',
        prompt: 'Search my email for ',
        inputHint: 'keyword or topic',
      },
      {
        icon: '📖',
        label: 'Read email from…',
        prompt: 'Read the latest email from ',
        inputHint: 'name or email',
      },
      {
        icon: '📤',
        label: 'Send email to…',
        prompt: 'Send an email to ',
        inputHint: 'name or email',
      },
    ],
  },
  {
    id: 'teams',
    label: 'Teams',
    icon: ICON('teams'),
    category: 'Productivity',
    chipClass: 'chip-teams',
    connected: false,
    actions: [
      {
        icon: '💬',
        label: 'Send message to…',
        prompt: 'Send a Teams message to ',
        inputHint: 'name or email',
      },
      {
        icon: '📌',
        label: 'Send to saved messages',
        prompt: 'Send a Teams message to myself in saved messages: ',
        inputHint: 'your message',
      },
      { icon: '👥', label: 'List my Teams', prompt: 'List the Teams I belong to' },
    ],
  },
  {
    id: 'calendar',
    label: 'Calendar',
    icon: ICON('calendar'),
    category: 'Productivity',
    chipClass: 'chip-calendar',
    connected: false,
    actions: [
      {
        icon: '📅',
        label: 'What meetings do I have today?',
        prompt: 'What meetings do I have today?',
      },
      { icon: '🗓️', label: 'Am I free at…', prompt: 'Am I free at ', inputHint: 'e.g. 3pm Friday' },
      {
        icon: '🤝',
        label: 'Find time to meet with…',
        prompt: 'Find a time to meet with ',
        inputHint: 'name or email',
      },
      {
        icon: '➕',
        label: 'Schedule a meeting with…',
        prompt: 'Schedule a meeting with ',
        inputHint: 'name or email',
      },
    ],
  },
  {
    id: 'onedrive',
    label: 'OneDrive',
    icon: ICON('onedrive'),
    category: 'Productivity',
    chipClass: 'chip-onedrive',
    connected: false,
    actions: [
      { icon: '📂', label: 'What files do I have?', prompt: 'List my OneDrive files' },
      {
        icon: '🔍',
        label: 'Find a file called…',
        prompt: 'Find a file in OneDrive called ',
        inputHint: 'filename',
      },
      { icon: '⬆️', label: 'Upload file to OneDrive', tpAction: 'onedrive' },
    ],
  },
  {
    id: 'jira',
    label: 'Jira',
    icon: ICON('jira'),
    category: 'Developer Tools',
    chipClass: 'chip-jira',
    connected: false,
    actions: [
      { icon: '📋', label: 'My open tickets', prompt: 'Show my open Jira tickets' },
      {
        icon: '🔎',
        label: 'Get details on an issue',
        prompt: 'Get details on Jira issue ',
        inputHint: 'issue key, e.g. PROJ-123',
      },
      {
        icon: '➕',
        label: 'Create a new issue',
        prompt: 'Create a new Jira issue: ',
        inputHint: 'summary and details',
      },
      {
        icon: '💬',
        label: 'Add comment to issue',
        prompt: 'Add a comment to Jira issue ',
        inputHint: 'issue key',
      },
    ],
  },
  {
    id: 'confluence',
    label: 'Confluence',
    icon: ICON('confluence'),
    category: 'Developer Tools',
    chipClass: 'chip-confluence',
    connected: false,
    actions: [
      {
        icon: '🔍',
        label: 'Search pages for…',
        prompt: 'Search Confluence pages for ',
        inputHint: 'keyword or topic',
      },
      {
        icon: '➕',
        label: 'Create a new page',
        prompt: 'Create a Confluence page titled ',
        inputHint: 'page title',
      },
      {
        icon: '🗂️',
        label: 'List available spaces',
        prompt: 'List all accessible Confluence spaces',
      },
    ],
  },
  {
    id: 'github',
    label: 'GitHub',
    icon: ICON('github'),
    labelBadge: 'Alpha',
    category: 'Developer Tools',
    chipClass: 'chip-github',
    chipAlias: 'git',
    connected: false,
    actions: [
      {
        icon: '👀',
        label: 'What needs my review?',
        prompt: 'Show me pull requests waiting for my review',
      },
      { icon: '🔴', label: 'My open issues', prompt: 'List GitHub issues assigned to me' },
      {
        icon: '✅',
        label: 'Check my PR status',
        prompt: 'Show status of my open pull requests including CI',
      },
    ],
  },
  {
    id: 'code_agent',
    label: 'Code',
    icon: '<span style="font-family:monospace;font-size:0.9em">&lt;/&gt;</span>',
    category: 'Developer Tools',
    chipClass: 'chip-code-agent',
    chipAlias: 'code',
    connected: true,
    actions: [
      {
        icon: '✏️',
        label: 'Make a change to my app',
        prompt: 'Make a change to my app: ',
        inputHint: 'describe the change',
      },
      {
        icon: '🐛',
        label: 'Fix a bug',
        prompt: 'Fix this bug in my app: ',
        inputHint: 'describe the bug',
      },
      {
        icon: '📖',
        label: 'Explain my codebase',
        prompt: 'Explain how my app works in plain English',
      },
    ],
  },
  {
    id: 'ppt',
    label: 'PowerPoint',
    labelBadge: 'Alpha',
    icon: '<img src="/static/icons/ppt-file.png" class="skill-icon-img" alt="ppt" />',
    chipAlias: 'ppt',
    category: 'Productivity',
    chipClass: 'chip-ppt',
    railHidden: true,
    connected: true,
    actions: [
      {
        icon: '📋',
        label: 'Inspect open presentation',
        prompt: 'Get the slide count, titles, and layouts of my open PowerPoint presentation',
      },
      {
        icon: '📖',
        label: 'Read slide content',
        prompt: 'Read all text content and speaker notes from my open PowerPoint presentation',
      },
      {
        icon: '📝',
        label: 'Create new presentation',
        prompt: 'Create a new PowerPoint presentation with the following slides: ',
        inputHint: 'describe slides and content',
      },
      {
        icon: '📂',
        label: 'Browse for a file…',
        filePicker: {
          filetypes: 'PowerPoint (*.pptx)|*.pptx',
          prompt: 'Read and inspect the PowerPoint file at ',
        },
      },
    ],
  },
  {
    id: 'excel',
    label: 'Excel',
    labelBadge: 'Alpha',
    icon: '<img src="/static/icons/excel-file.png" class="skill-icon-img" alt="excel" />',
    chipAlias: 'excel',
    category: 'Productivity',
    chipClass: 'chip-excel',
    railHidden: true,
    connected: true,
    actions: [
      {
        icon: '📊',
        label: 'Inspect open workbook',
        prompt: 'Get the sheet names, headers, and row count of my open Excel workbook',
      },
      {
        icon: '📖',
        label: 'Read open workbook',
        prompt: 'Read all data from my open Excel workbook and show me the contents',
      },
      {
        icon: '📝',
        label: 'Create a workbook',
        prompt: 'Create a new Excel workbook with the following data: ',
        inputHint: 'describe sheets and data',
      },
      {
        icon: '📂',
        label: 'Browse for a file…',
        filePicker: {
          filetypes: 'Excel (*.xlsx)|*.xlsx|CSV (*.csv)|*.csv',
          prompt: 'Read and inspect the Excel file at ',
        },
      },
    ],
  },
  {
    id: 'docx',
    label: 'Word',
    labelBadge: 'Alpha',
    icon: '<img src="/static/icons/word-file.png" class="skill-icon-img" alt="word" />',
    chipAlias: 'docx',
    category: 'Productivity',
    chipClass: 'chip-docx',
    railHidden: true,
    connected: true,
    actions: [
      {
        icon: '📄',
        label: 'Inspect open document',
        prompt: 'Get the structure, headings, and metadata of my open Word document',
      },
      {
        icon: '📖',
        label: 'Read open document',
        prompt: 'Read the content of my open Word document and show me the text',
      },
      {
        icon: '📝',
        label: 'Create a new document',
        prompt: 'Create a new Word document with the following content: ',
        inputHint: 'describe content',
      },
      {
        icon: '📂',
        label: 'Browse for a file…',
        filePicker: {
          filetypes: 'Word (*.docx)|*.docx',
          prompt: 'Read and inspect the Word document at ',
        },
      },
    ],
  },
  {
    id: 'onenote',
    label: 'OneNote',
    icon: '<img src="/static/icons/onenote.png" class="skill-icon-img" alt="onenote" />',
    chipAlias: 'onenote',
    category: 'Productivity',
    chipClass: 'chip-onenote',
    connected: true,
    actions: [
      { icon: '📚', label: 'List my notebooks', prompt: 'List my OneNote notebooks' },
      {
        icon: '📑',
        label: 'List sections in…',
        prompt: 'List sections in my OneNote notebook ',
        inputHint: 'notebook name',
      },
      {
        icon: '📖',
        label: 'Read a page',
        prompt: 'Read the OneNote page titled ',
        inputHint: 'page title',
      },
      {
        icon: '✏️',
        label: 'Create a page',
        prompt: 'Create a OneNote page in section ',
        inputHint: 'section name + content',
      },
    ],
  },
  {
    id: 'slack',
    label: 'Slack',
    icon: ICON('slack'),
    category: 'Communication',
    chipClass: 'chip-slack',
    connected: false,
    actions: [
      { icon: '📋', label: 'List available channels', prompt: 'List all available Slack channels' },
      {
        icon: '🔍',
        label: 'Search a channel…',
        prompt: 'Search Slack channel ',
        inputHint: 'channel name + topic',
      },
      {
        icon: '📊',
        label: 'Summarize a channel',
        prompt: 'Summarize recent threads in Slack channel ',
        inputHint: 'channel name',
      },
      {
        icon: '💬',
        label: 'Post to a channel',
        prompt: 'Post a message to Slack channel ',
        inputHint: 'channel name',
      },
    ],
  },
  {
    id: 'browser',
    label: 'Browse Web',
    icon: ICON('browser'),
    chipAlias: 'browse',
    category: 'Productivity',
    chipClass: 'chip-browser',
    connected: true,
    actions: [
      {
        icon: '🔍',
        label: 'Search the web',
        prompt: 'Search the web for ',
        inputHint: 'what to search',
      },
      { icon: '🌐', label: 'Visit a website', prompt: 'Go to ', inputHint: 'URL or site name' },
      {
        icon: '📋',
        label: 'Extract page data',
        prompt: 'Extract data from ',
        inputHint: 'URL and what to extract',
      },
    ],
  },
];

// ── Google Workspace service skills ────────────────────────────────────
// Each service is a separate skill ID (g-gmail, g-drive, etc.) so the user
// gets a per-service context chip. All route to the same mcp-google-workspace
// MCP connection — the chat routing layer (chat.py) activates the MCP
// connection when any g-* skill is active. Tiles only appear in the launcher
// when Google Workspace is connected.
const _GOOGLE_SERVICES = [
  {
    id: 'g-gmail',
    label: 'Gmail',
    desc: 'Email',
    url: 'https://mail.google.com',
    toolPrefix: 'gmail',
  },
  {
    id: 'g-drive',
    label: 'Google Drive',
    desc: 'Cloud storage',
    url: 'https://drive.google.com',
    toolPrefix: 'drive',
  },
  {
    id: 'g-calendar',
    label: 'Google Calendar',
    desc: 'Calendar',
    url: 'https://calendar.google.com',
    toolPrefix: 'calendar',
  },
  {
    id: 'g-docs',
    label: 'Google Docs',
    desc: 'Documents',
    url: 'https://docs.google.com',
    toolPrefix: 'docs',
  },
  {
    id: 'g-sheets',
    label: 'Google Sheets',
    desc: 'Spreadsheets',
    url: 'https://sheets.google.com',
    toolPrefix: 'sheets',
  },
  {
    id: 'g-slides',
    label: 'Google Slides',
    desc: 'Presentations',
    url: 'https://slides.google.com',
    toolPrefix: 'slides',
  },
  {
    id: 'g-forms',
    label: 'Google Forms',
    desc: 'Forms & surveys',
    url: 'https://forms.google.com',
    toolPrefix: 'forms',
  },
  { id: 'g-tasks', label: 'Google Tasks', desc: 'Task lists', toolPrefix: 'tasks' },
  { id: 'g-contacts', label: 'Google Contacts', desc: 'Address book', toolPrefix: 'contacts' },
  { id: 'g-chat', label: 'Google Chat', desc: 'Chat & Spaces', toolPrefix: 'chat' },
  { id: 'g-search', label: 'Custom Search', desc: 'Web search', toolPrefix: 'search' },
  { id: 'g-script', label: 'Apps Script', desc: 'Automation scripts', toolPrefix: 'script' },
];
const _googleWsConnected = () => {
  return SKILL_REGISTRY.some(
    (s) =>
      (s.id === 'mcp-google-workspace' || (s._mcpInjected && /workspace/i.test(s.label))) &&
      s.connected !== false,
  );
};
_GOOGLE_SERVICES.forEach((svc) => {
  SKILL_REGISTRY.push({
    id: svc.id,
    label: svc.label,
    icon:
      '<img src="/static/icons/' +
      svc.id +
      '.svg" class="skill-icon-img" alt="' +
      svc.label +
      '" />',
    chipAlias: svc.id,
    category: 'Google Workspace',
    chipClass: 'chip-mcp',
    connected: false,
    _googleService: true,
    _googleServiceDesc: svc.desc,
    _googleServiceUrl: svc.url,
    _googleServiceToolPrefix: svc.toolPrefix,
    actions: [],
  });
});

// Append MCP connections that were bootstrapped into the page by the server at load time.
// window.__MCP_SKILLS__ is injected before </head> in health.py so it is always defined here.
(window.__MCP_SKILLS__ || []).forEach((c) => {
  SKILL_REGISTRY.push({
    id: c.id,
    label: c.name,
    icon: '<span style="font-size:1.1em">🔌</span>',
    chipAlias:
      c.name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '') || c.id,
    category: 'MCP',
    chipClass: 'chip-mcp',
    connected: true,
    _mcpInjected: true,
    actions: [],
  });
});

// Append installed marketplace skills (Community, Verified, Mine) bootstrapped by the server.
(window.__USER_SKILLS__ || []).forEach((s) => {
  const isMine = s.tier === 'Mine';
  SKILL_REGISTRY.push({
    id: s.id,
    label: s.name,
    icon: isMine
      ? '<span style="font-size:1.1em">⚡</span>'
      : '<span style="font-size:1.1em">🧩</span>',
    chipAlias: s.id,
    category: s.tier || 'Community',
    chipClass: 'chip-skill',
    railHidden: true,
    _userCreated: true,
    actions: [],
  });
});

const SKILL_MAP = Object.fromEntries(SKILL_REGISTRY.map((s) => [s.id, s]));

// If Google Workspace MCP was bootstrapped at page load, mark its g-* skills
// connected only for services that actually have tools registered.
const _wsMcp = SKILL_REGISTRY.find(
  (s) => s.id === 'mcp-google-workspace' || (s._mcpInjected && /workspace/i.test(s.label)),
);
if (_wsMcp && window.__MCP_SKILLS__) {
  const wsConn = window.__MCP_SKILLS__.find(
    (c) => c.id === 'mcp-google-workspace' || (c.name && /workspace/i.test(c.name)),
  );
  if (wsConn) {
    const toolNames = new Set((wsConn.cached_tool_names || []).map((n) => n.toLowerCase()));
    _GOOGLE_SERVICES.forEach((svc) => {
      if (!SKILL_MAP[svc.id]) return;
      const hasTools = [...toolNames].some(
        (name) => name.startsWith(svc.toolPrefix + '_') || name.startsWith(svc.toolPrefix + '-'),
      );
      SKILL_MAP[svc.id].connected = hasTools;
    });
  }
}

// Installed plugin commands (decision #12, 2026-08-07 milestone) bootstrapped
// by the server — its OWN registry, not part of SKILL_REGISTRY (mirrors
// marketplace/commands.py's COMMAND_REGISTRY being deliberately separate from
// shared.SKILL_PROMPTS: a command is a parameterized prompt-template, not a
// skill activation). Powers the "/" dropdown's COMMANDS section below.
let PLUGIN_COMMANDS = (window.__PLUGIN_COMMANDS__ || []).slice();

// Live-update hook — same naming/shape convention as registerUserSkill /
// registerMcpSkill above. Called after a claude-plugins-official plugin
// install (see marketplace-pane.js's _handleInstallOutcome) so a freshly
// installed plugin's commands show up in the "/" dropdown immediately,
// without a page reload. No matching unregisterPluginCommand — same
// accepted gap as registerUserSkill/registerMcpSkill (an uninstalled skill
// or command stays registered client-side until the next reload).
window.registerPluginCommand = function (name, description, pluginId) {
  // Fix #6 (2026-08-07 milestone adversarial review): overwrite an existing
  // same-named entry in place rather than no-op — matches the server's
  // COMMAND_REGISTRY[name] = {...} "last-installed wins" semantics (decision
  // #11a). Without this, a second plugin registering the same command name
  // updates the server-side expansion but the dropdown keeps showing the
  // first plugin's stale description/attribution.
  const existing = PLUGIN_COMMANDS.find((c) => c.name === name);
  if (existing) {
    existing.description = description || '';
    existing.plugin_id = pluginId || '';
    return;
  }
  PLUGIN_COMMANDS.push({ name, description: description || '', plugin_id: pluginId || '' });
};

// Called by marketplace-pane.js after a user creates a skill so it appears in
// slash commands and the dock immediately without a page reload.
window.registerUserSkill = function (id, name, tier) {
  if (SKILL_MAP[id]) return; // already registered
  const isMine = (tier || 'Mine') === 'Mine';
  const entry = {
    id,
    label: name,
    icon: isMine
      ? '<span style="font-size:1.1em">⚡</span>'
      : '<span style="font-size:1.1em">🧩</span>',
    chipAlias: id,
    category: tier || 'Mine',
    chipClass: 'chip-skill',
    railHidden: true,
    _userCreated: true,
    actions: [],
  };
  SKILL_REGISTRY.push(entry);
  SKILL_MAP[id] = entry;
};

// Called after a new MCP connection is installed so the skill appears in slash
// commands and the skill popup immediately without a page reload.
window.registerMcpSkill = function (id, name) {
  if (SKILL_MAP[id]) {
    SKILL_MAP[id].connected = true;
    renderDock();
    renderLauncher();
    return;
  }
  const entry = {
    id,
    label: name,
    icon: '<span style="font-size:1.1em">🔌</span>',
    chipAlias:
      name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '') || id,
    category: 'MCP',
    chipClass: 'chip-mcp',
    connected: true,
    _mcpInjected: true,
    actions: [],
  };
  SKILL_REGISTRY.push(entry);
  SKILL_MAP[id] = entry;
  if (id === 'mcp-google-workspace' || /google.?workspace/i.test(name)) {
    _refreshGoogleServiceConnected();
  }
  renderDock();
};

async function _refreshGoogleServiceConnected() {
  try {
    const listRes = await fetch('/api/config/mcp');
    const list = await listRes.json();
    const wsConn = (list.connections || []).find(
      (c) => c.id === 'mcp-google-workspace' || (c.name && /workspace/i.test(c.name)),
    );
    if (!wsConn || !wsConn.enabled) return;
    const toolNames = new Set((wsConn.tools || []).map((n) => n.toLowerCase()));
    _GOOGLE_SERVICES.forEach((svc) => {
      if (!SKILL_MAP[svc.id]) return;
      const hasTools = [...toolNames].some(
        (name) => name.startsWith(svc.toolPrefix + '_') || name.startsWith(svc.toolPrefix + '-'),
      );
      SKILL_MAP[svc.id].connected = hasTools;
    });
    const favs = loadDockFavs();
    if (!favs.includes('g-gmail') && SKILL_MAP['g-gmail']?.connected) {
      favs.push('g-gmail');
      saveDockFavs(favs);
    }
    renderDock();
    renderLauncher();
  } catch (e) {}
}

function _getUnapprovedDeps(skillId) {
  const userSkills = window.__USER_SKILLS__ || [];
  const skill = userSkills.find((s) => s.id === skillId);
  if (!skill || !Array.isArray(skill.requires)) return [];
  return skill.requires
    .filter((r) => _GATED_DEP_IDS.has(r.id) && !_approvedSkillDeps.has(r.id))
    .map((r) => r.id);
}

const LAUNCHER_CATEGORIES = [
  { key: 'communication', label: 'Communication', filter: (s) => s.category === 'Communication' },
  { key: 'project', label: 'Project', filter: (s) => s.category === 'Productivity' },
  {
    key: 'development',
    label: 'Development',
    filter: (s) => ['Developer Tools'].includes(s.category),
  },
  {
    key: 'google',
    label: 'Google Workspace',
    filter: (s) => s.category === 'Google Workspace' && _googleWsConnected(),
  },
  { key: 'web', label: 'Web', filter: (s) => s.id === 'browser' },
];

let _activeSkillId = null;
let _activeChips = [];

// Per-conversation permission grants for gated dep skills (shell_runner, code_runner).
// Resets on page load — intentionally per-conversation scope.
const _approvedSkillDeps = new Set();
const _GATED_DEP_IDS = new Set(['shell_runner', 'code_runner']);

const RAIL_CONFIRM_SKIP_KEY = 'aigator-live-confirm-skip';
const AIGATOR_TIP_KEY = 'aigator-tip-dismissed';

const DOCK_FAVS_KEY = 'dock-favorites';
// code_agent (the Code workspace) is a default rail item so it's discoverable
// out of the box - the coding tutor/guardrail flow tells users to "open Code",
// which only works if it's actually reachable. NOTE: this default only applies
// to NEW users; anyone with an existing saved dock (localStorage) keeps their
// own set, so the guardrail nudge also points at the always-available app
// launcher as a fallback (see aigator SKILL.md).
const DEFAULT_DOCK_FAVS = [
  'email',
  'calendar',
  'teams',
  'onedrive',
  'confluence',
  'jira',
  'slack',
  'code_agent',
];
const DOCK_ICON_MAP = { email: 'outlook' };
const _dockIconFile = (id) => DOCK_ICON_MAP[id] || id;
const DOCK_MAX_VISIBLE = 10;

function loadDockFavs() {
  try {
    const raw = localStorage.getItem(DOCK_FAVS_KEY);
    if (raw) return JSON.parse(raw);
  } catch {}
  return [...DEFAULT_DOCK_FAVS];
}
function saveDockFavs(ids) {
  localStorage.setItem(DOCK_FAVS_KEY, JSON.stringify(ids));
}
function toggleDockFav(skillId) {
  const favs = loadDockFavs();
  const idx = favs.indexOf(skillId);
  if (idx >= 0) {
    favs.splice(idx, 1);
  } else {
    favs.push(skillId);
  }
  saveDockFavs(favs);
  renderDock();
  if (typeof renderLauncher === 'function') renderLauncher();
}

/* ── Dock ────────────────────────────────────────────── */
function renderDock() {
  const container = document.getElementById('dock-favorites');
  if (!container) return;
  container
    .querySelectorAll('.dock-item[data-skill-id], .dock-overflow-btn')
    .forEach((el) => el.remove());
  const favIds = loadDockFavs();
  const skills = favIds.map((id) => SKILL_MAP[id]).filter(Boolean);
  const launcherBtn = document.getElementById('dock-launcher-btn');

  const visible = skills.slice(0, DOCK_MAX_VISIBLE);
  const hidden = skills.slice(DOCK_MAX_VISIBLE);

  for (const skill of visible) {
    const btn = document.createElement('button');
    btn.className = 'dock-item';
    btn.title = skill.label;
    btn.dataset.skillId = skill.id;
    btn.draggable = true;

    const iconFile = _dockIconFile(skill.id);
    const img = document.createElement('img');
    img.className = 'dock-icon';
    img.alt = skill.label;
    if (skill._customApp) {
      try {
        const host = new URL(skill._customAppUrl).hostname;
        img.src = 'https://www.google.com/s2/favicons?domain=' + host + '&sz=64';
        img.onerror = function () {
          this.onerror = null;
          this.src = '/static/icons/globe.svg';
        };
        img.onload = function () {
          if (this.naturalWidth <= 16) {
            this.src = '/static/icons/globe.svg';
          }
        };
      } catch {
        img.src = '/static/icons/globe.svg';
      }
    } else {
      const ext = skill.id === 'onenote' ? 'png' : 'svg';
      img.src = '/static/icons/' + iconFile + '.' + ext;
    }
    btn.appendChild(img);

    const badge = document.createElement('span');
    badge.className = 'dock-badge hidden';
    badge.id = 'dock-badge-' + skill.id;
    btn.appendChild(badge);

    if (skill.connected) {
      const dot = document.createElement('span');
      dot.className = 'dock-connected';
      btn.appendChild(dot);
    }

    const grip = document.createElement('span');
    grip.className = 'grip-handle';
    grip.textContent = '\u22EE\u22EE';
    btn.appendChild(grip);

    btn.addEventListener('click', () => selectSkill(skill.id));
    btn.addEventListener('dragstart', (e) => {
      btn.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', skill.id);
      container._dockDragSrcId = skill.id;
    });
    btn.addEventListener('dragend', () => {
      container._dockDragSrcId = null;
      container
        .querySelectorAll('.dock-item')
        .forEach((d) => d.classList.remove('dragging', 'drag-over-top', 'drag-over-bottom'));
    });
    btn.addEventListener('dragover', (e) => {
      if (!container._dockDragSrcId || container._dockDragSrcId === skill.id) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const rect = btn.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      btn.classList.toggle('drag-over-top', e.clientY < midY);
      btn.classList.toggle('drag-over-bottom', e.clientY >= midY);
    });
    btn.addEventListener('dragleave', () => {
      btn.classList.remove('drag-over-top', 'drag-over-bottom');
    });
    btn.addEventListener('drop', (e) => {
      e.preventDefault();
      const srcId = container._dockDragSrcId;
      if (!srcId || srcId === skill.id) return;
      const favs = loadDockFavs();
      const srcIdx = favs.indexOf(srcId);
      const dstIdx = favs.indexOf(skill.id);
      if (srcIdx < 0 || dstIdx < 0) return;
      const rect = btn.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      const insertBefore = e.clientY < midY;
      favs.splice(srcIdx, 1);
      const newIdx = favs.indexOf(skill.id);
      favs.splice(insertBefore ? newIdx : newIdx + 1, 0, srcId);
      saveDockFavs(favs);
      renderDock();
    });
    if (launcherBtn) {
      container.insertBefore(btn, launcherBtn);
    } else {
      container.appendChild(btn);
    }
  }

  if (hidden.length) {
    const overflowBtn = document.createElement('button');
    overflowBtn.className = 'dock-item dock-overflow-btn';
    overflowBtn.title = hidden.length + ' more app' + (hidden.length > 1 ? 's' : '');
    overflowBtn.innerHTML =
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="6" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="18" cy="12" r="1.5"/></svg>' +
      '<span class="dock-overflow-count">' +
      hidden.length +
      '</span>';
    overflowBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      _toggleDockOverflow(hidden, overflowBtn);
    });
    if (launcherBtn) {
      container.insertBefore(overflowBtn, launcherBtn);
    } else {
      container.appendChild(overflowBtn);
    }
  }
}

function _toggleDockOverflow(hiddenSkills, anchorBtn) {
  const existing = document.getElementById('dock-overflow-popover');
  if (existing) {
    existing.remove();
    return;
  }

  const popover = document.createElement('div');
  popover.id = 'dock-overflow-popover';
  popover.className = 'dock-overflow-popover';
  for (const skill of hiddenSkills) {
    const item = document.createElement('button');
    item.className = 'dock-overflow-item';
    item.title = skill.label;
    const img = document.createElement('img');
    img.className = 'dock-overflow-icon';
    img.alt = skill.label;
    if (skill._customApp) {
      try {
        const host = new URL(skill._customAppUrl).hostname;
        img.src = 'https://www.google.com/s2/favicons?domain=' + host + '&sz=64';
        img.onerror = function () {
          this.onerror = null;
          this.src = '/static/icons/globe.svg';
        };
        img.onload = function () {
          if (this.naturalWidth <= 16) {
            this.src = '/static/icons/globe.svg';
          }
        };
      } catch {
        img.src = '/static/icons/globe.svg';
      }
    } else {
      const iconFile = _dockIconFile(skill.id);
      const ext = skill.id === 'onenote' ? 'png' : 'svg';
      img.src = '/static/icons/' + iconFile + '.' + ext;
    }
    item.appendChild(img);
    const label = document.createElement('span');
    label.className = 'dock-overflow-label';
    label.textContent = skill.label;
    item.appendChild(label);
    item.addEventListener('click', () => {
      popover.remove();
      selectSkill(skill.id);
    });
    popover.appendChild(item);
  }

  document.body.appendChild(popover);
  const anchorRect = anchorBtn.getBoundingClientRect();
  popover.style.right = window.innerWidth - anchorRect.right + 4 + 'px';
  popover.style.bottom = window.innerHeight - anchorRect.top + 4 + 'px';

  const closeHandler = (e) => {
    if (!popover.contains(e.target) && e.target !== anchorBtn) {
      popover.remove();
      document.removeEventListener('click', closeHandler);
    }
  };
  setTimeout(() => document.addEventListener('click', closeHandler), 0);
}

function renderLauncher() {
  const body = document.getElementById('launcher-body');
  if (!body) return;
  body.textContent = '';
  const allSkills = SKILL_REGISTRY.filter(
    (s) => !s.railHidden && s.id !== 'gator' && !s._customApp,
  );

  for (const cat of LAUNCHER_CATEGORIES) {
    const skills = allSkills.filter((s) => cat.filter(s));
    if (!skills.length) continue;

    const heading = document.createElement('div');
    heading.className = 'launcher-category';
    heading.dataset.cat = cat.key;
    heading.textContent = cat.label;
    body.appendChild(heading);

    const grid = document.createElement('div');
    grid.className = 'launcher-grid';
    grid.dataset.cat = cat.key;

    for (const skill of skills) {
      const app = document.createElement('button');
      app.className = 'launcher-app';
      app.dataset.name = skill.id;
      app.dataset.label = skill.label.toLowerCase();

      const iconWrap = document.createElement('div');
      iconWrap.className = 'launcher-app-icon';
      const iconImg = document.createElement('img');
      if (skill._googleService) {
        iconImg.src = '/static/icons/' + skill.id + '.svg';
      } else {
        const iconFile = _dockIconFile(skill.id);
        const ext = skill.id === 'onenote' ? 'png' : 'svg';
        iconImg.src = '/static/icons/' + iconFile + '.' + ext;
      }
      iconImg.alt = skill.label;
      iconWrap.appendChild(iconImg);
      app.appendChild(iconWrap);

      const info = document.createElement('div');
      info.className = 'launcher-app-info';
      const nameEl = document.createElement('span');
      nameEl.className = 'launcher-app-name';
      nameEl.textContent = skill.label;
      info.appendChild(nameEl);
      const descEl = document.createElement('span');
      descEl.className = 'launcher-app-desc';
      descEl.textContent = skill._googleServiceDesc || skill.category || '';
      info.appendChild(descEl);
      app.appendChild(info);

      const badge = document.createElement('span');
      badge.className = 'launcher-app-badge hidden';
      badge.id = 'launcher-badge-' + skill.id;
      app.appendChild(badge);

      app.addEventListener('click', () => selectSkill(skill.id));

      const pinBtn = document.createElement('button');
      pinBtn.className = 'launcher-app-pin';
      const updatePin = () => {
        const pinned = loadDockFavs().includes(skill.id);
        pinBtn.textContent = pinned ? '★' : '☆';
        pinBtn.classList.toggle('pinned', pinned);
        pinBtn.title = pinned ? 'Remove from rail' : 'Pin to left rail';
      };
      updatePin();
      pinBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleDockFav(skill.id);
        updatePin();
      });
      app.appendChild(pinBtn);

      grid.appendChild(app);
    }
    body.appendChild(grid);
  }

  // Marketplace link at bottom
  const mktBtn = document.createElement('button');
  mktBtn.className = 'launcher-app';
  mktBtn.style.cssText =
    'justify-content:center;color:var(--text-sub);font-size:.8rem;margin-top:8px;';
  mktBtn.textContent = '+ Browse marketplace';
  mktBtn.addEventListener('click', () => {
    document.getElementById('launcher-backdrop')?.classList.remove('open');
    window.openSettingsPanel?.('skills');
  });
  body.appendChild(mktBtn);
}

/* ── File card helpers ──────────────────────────────── */
function _fileIcon(mimeType) {
  if (!mimeType) return '\uD83D\uDCE6';
  if (mimeType.startsWith('image/')) return '\uD83D\uDDBC\uFE0F';
  if (mimeType === 'application/pdf') return '\uD83D\uDCCE';
  if (mimeType === 'application/json') return '{}';
  if (mimeType === 'text/csv' || mimeType.includes('spreadsheet')) return '\uD83D\uDCCA';
  if (mimeType.startsWith('text/')) return '\uD83D\uDCC4';
  return '\uD83D\uDCE6';
}

function _fileExt(name) {
  if (!name) return '';
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
}

function _fileIconImg(mimeType, name) {
  const ext = _fileExt(name);
  const map = {
    xlsx: 'excel-file.png',
    xls: 'excel-file.png',
    csv: 'excel-file.png',
    docx: 'word-file.png',
    doc: 'word-file.png',
    pptx: 'ppt-file.png',
    ppt: 'ppt-file.png',
    pdf: 'pdf-file.png',
  };
  if (map[ext]) return '/static/icons/' + map[ext];
  const m = (mimeType || '').toLowerCase();
  if (m.includes('presentation')) return '/static/icons/ppt-file.png';
  if (m.includes('spreadsheet') || m === 'text/csv') return '/static/icons/excel-file.png';
  if (m.includes('wordprocessing') || m === 'application/msword')
    return '/static/icons/word-file.png';
  if (m === 'application/pdf') return '/static/icons/pdf-file.png';
  return '';
}

function _friendlyMimeLabel(mimeType, name) {
  const ext = _fileExt(name);
  const byExt = {
    pptx: 'PowerPoint',
    ppt: 'PowerPoint',
    docx: 'Word document',
    doc: 'Word document',
    xlsx: 'Excel spreadsheet',
    xls: 'Excel spreadsheet',
    csv: 'CSV',
    pdf: 'PDF',
    png: 'PNG image',
    jpg: 'JPEG image',
    jpeg: 'JPEG image',
    gif: 'GIF image',
    webp: 'WebP image',
    svg: 'SVG image',
    txt: 'Text',
    md: 'Markdown',
    json: 'JSON',
    xml: 'XML',
    html: 'HTML',
    zip: 'Archive',
  };
  if (byExt[ext]) return byExt[ext];
  const m = (mimeType || '').toLowerCase();
  if (m.includes('presentation')) return 'PowerPoint';
  if (m.includes('spreadsheet')) return 'Excel spreadsheet';
  if (m.includes('wordprocessing') || m === 'application/msword') return 'Word document';
  if (m === 'application/pdf') return 'PDF';
  if (m.startsWith('image/')) return 'Image';
  if (m === 'application/json') return 'JSON';
  if (m.startsWith('text/')) return 'Text';
  if (ext) return ext.toUpperCase();
  return 'File';
}

function _formatBytes(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/* ── File chip remove wiring ─────────────────────────── */
// The chip lives inside #chat-input, a contenteditable host. A bare `click`
// listener on a child button is swallowed there because the preceding
// `mousedown` moves the caret/selection first — so we also preventDefault on
// mousedown to keep the button clickable.
function _wireChipRemove(removeBtn, chip, input) {
  removeBtn.addEventListener('mousedown', (e) => {
    e.preventDefault();
    e.stopPropagation();
  });
  removeBtn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    chip.remove();
    if (input && input.focus) input.focus();
  });
}

/* ── Ctrl+O: Open file picker ───────────────────────── */
function _openFilePicker() {
  fetch('/api/file-picker', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: 'Open a file',
      filetypes:
        'All supported|*.docx;*.xlsx;*.pptx;*.pdf;*.csv;*.doc;*.xls;*.ppt|Word (*.docx)|*.docx|Excel (*.xlsx)|*.xlsx|PowerPoint (*.pptx)|*.pptx|PDF (*.pdf)|*.pdf|All files (*.*)|*.*',
    }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.ok && data.file_path) {
        const input = document.getElementById('chat-input');
        const fileName = data.file_path.split(/[/\\]/).pop();
        const ext = fileName.split('.').pop().toLowerCase();
        const fileIconSrc = {
          xlsx: '/static/icons/excel-file.png',
          xls: '/static/icons/excel-file.png',
          csv: '/static/icons/excel-file.png',
          docx: '/static/icons/word-file.png',
          doc: '/static/icons/word-file.png',
          pptx: '/static/icons/ppt-file.png',
          ppt: '/static/icons/ppt-file.png',
          pdf: '/static/icons/pdf-file.png',
        }[ext];
        const chip = document.createElement('span');
        chip.className = 'pin-ref-chip file-ref-chip';
        chip.contentEditable = 'false';
        chip.dataset.filePath = data.file_path;
        chip.dataset.fileName = fileName;
        chip.title = fileName;
        if (fileIconSrc) {
          const icon = document.createElement('img');
          icon.src = fileIconSrc;
          icon.className = 'file-chip-icon';
          icon.alt = ext;
          chip.appendChild(icon);
          chip.appendChild(document.createTextNode(' ' + fileName));
        } else {
          chip.appendChild(document.createTextNode('\uD83D\uDCC1 ' + fileName));
        }
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'file-chip-remove';
        removeBtn.setAttribute('aria-label', 'Remove ' + fileName);
        removeBtn.title = 'Remove';
        removeBtn.textContent = '\u2715';
        _wireChipRemove(removeBtn, chip, input);
        chip.appendChild(removeBtn);
        input.appendChild(chip);
        input.appendChild(document.createTextNode('\u00A0'));
        input.focus();
        if (typeof _moveCaretToEnd === 'function') _moveCaretToEnd(input);
        const skillMap = {
          docx: 'docx',
          doc: 'docx',
          xlsx: 'excel',
          xls: 'excel',
          csv: 'excel',
          pptx: 'ppt',
          ppt: 'ppt',
        };
        if (skillMap[ext]) selectSkill(skillMap[ext]);
      }
    })
    .catch(() => {});
}

// Ctrl+O shortcut
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'o') {
    e.preventDefault();
    _openFilePicker();
  }
});

const _TP_SKILL_IDS = new Set([
  'teams',
  'email',
  'onenote',
  'calendar',
  'onedrive',
  'jira',
  'github',
  'slack',
  'confluence',
  'code_agent',
]); // defined before third-pane.js loads
// Google Workspace service skills — open as native shell panes.
_GOOGLE_SERVICES.forEach((svc) => {
  _TP_SKILL_IDS.add(svc.id);
});

/* ── Coming Soon ─────────────────────────────────────── */
const _COMING_SOON_SKILLS = {
  ado: {
    emoji: '🔷',
    title: 'Azure DevOps — coming soon!',
    sub: "We're still working hard to bring more integrations and make AI Gator even smarter. The Gator keeps growing — stay tuned.",
  },
};

function showComingSoon(id) {
  const cfg = _COMING_SOON_SKILLS[id];
  if (!cfg) return;
  // Close any open third pane
  if (typeof closeThirdPane === 'function' && tpState?.type) closeThirdPane();
  document.getElementById('cs-emoji').textContent = cfg.emoji;
  document.getElementById('cs-title').textContent = cfg.title;
  document.getElementById('cs-sub').textContent = cfg.sub;
  document.getElementById('messages').classList.add('hidden');
  document.getElementById('coming-soon-inline').classList.remove('hidden');
  _setRailActive(id);
  _activeSkillId = id;
  _setPromptDisabled(true);
}

function hideComingSoon() {
  document.getElementById('coming-soon-inline').classList.add('hidden');
  document.getElementById('messages').classList.remove('hidden');
  _setPromptDisabled(false);
}

function _setPromptDisabled(disabled) {
  const form = document.getElementById('chat-form');
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('send-btn');
  if (!form) return;
  form.classList.toggle('prompt-disabled', disabled);
  input.contentEditable = disabled ? 'false' : 'true';
  btn.disabled = disabled;
  if (disabled) {
    input.dataset.placeholder = 'This integration is coming soon\u2026';
  } else {
    _updatePlaceholder();
  }
}

function selectSkill(id) {
  const skill = SKILL_MAP[id];
  if (!skill) return;

  // Coming-soon skills show inline panel instead of acting
  if (_COMING_SOON_SKILLS[id]) {
    showComingSoon(id);
    return;
  }

  // Custom web apps are treated as third-pane skills — they go through
  // openThirdPane() like Teams/Outlook/Slack, which wires up the topbar
  // split, drag spacer, and expand/collapse button. No special-casing.

  // Switching from a coming-soon view — restore messages
  hideComingSoon();

  // Switching away from a TP skill to a non-TP skill — close the pane
  if (typeof closeThirdPane === 'function' && tpState?.type && !_TP_SKILL_IDS.has(id)) {
    closeThirdPane();
  }

  // Already active and already open — just re-focus, no toggle
  if (_activeSkillId === id && _TP_SKILL_IDS.has(id) && tpState?.type === id) return;

  // Rail click = switch context (clear previous skill chips, but always keep @gator)
  _activeChips.forEach((c) => {
    if (c.skillId === 'gator') return; // never remove gator
    const chip = document.querySelector(`.chat-chip[data-skill-id="${c.skillId}"]`);
    if (chip) chip.remove();
  });
  _activeChips = _activeChips.filter((c) => c.skillId === 'gator');

  _activeSkillId = id;
  _setRailActive(id);

  // Ensure @gator chip is always present, then add the selected skill
  if (!_activeChips.some((c) => c.skillId === 'gator')) _addSkillChip('gator');
  if (id !== 'gator') _addSkillChip(id);

  _updatePlaceholder();

  // TP skills open the third pane
  if (typeof openThirdPane === 'function' && _TP_SKILL_IDS.has(id)) {
    openThirdPane(id);
  }

  // Close launcher if open
  document.getElementById('launcher-backdrop')?.classList.remove('open');

  input?.focus();
}

// Called by closeThirdPane (third-pane.js) to sync rail state
function onThirdPaneClosed() {
  // Remove the TP skill chip but keep @gator
  const tpSkill = _activeSkillId;
  if (tpSkill && tpSkill !== 'gator') {
    const chip = document.querySelector(`.chat-chip[data-skill-id="${tpSkill}"]`);
    if (chip) chip.remove();
    _activeChips = _activeChips.filter((c) => c.skillId !== tpSkill);
  }
  // Fall back to gator as active
  _activeSkillId = _activeChips.some((c) => c.skillId === 'gator') ? 'gator' : null;
  _setRailActive(_activeSkillId);
  _updatePlaceholder();
}

/* ── Shared chip helper ───────────────────────────────── */
function _addSkillChip(skillId) {
  const skill = SKILL_MAP[skillId];
  if (!skill) return;
  const alias = skill.chipAlias || skillId;
  // Dedup by both skillId and chipAlias — prevents MCP "Jira" + native "jira" duplicates
  if (_activeChips.some((c) => c.skillId === skillId)) return;
  if (_activeChips.some((c) => (SKILL_MAP[c.skillId]?.chipAlias || c.skillId) === alias)) return;
  _activeChips.push({ skillId, promptText: '' });
  const chipRow = document.getElementById('chat-chip-row');
  chipRow.classList.remove('hidden');
  const chip = document.createElement('span');
  chip.className = `chat-chip ${skill.chipClass}`;
  chip.dataset.skillId = skillId;
  const alphaBadge = skill.labelBadge
    ? `<span class="skill-alpha-badge">${skill.labelBadge}</span>`
    : '';
  const iconHtml = skill.icon ? `<span class="chip-skill-icon">${skill.icon}</span>` : '';
  chip.innerHTML = `${iconHtml}${alias}${alphaBadge ? ' ' + alphaBadge : ''} <button class="chip-remove" aria-label="Remove ${skill.label} context">\u2715</button>`;
  chip.querySelector('.chip-remove').addEventListener('click', (e) => {
    e.stopPropagation();
    removeChip(skillId);
  });
  chip.addEventListener('click', () => _selectChip(chip));
  chip.setAttribute('tabindex', '0');
  chip.addEventListener('keydown', (e) => {
    if (e.key === 'Backspace' || e.key === 'Delete') {
      e.preventDefault();
      removeChip(skillId, true);
      if (!_activeChips.length) input.focus();
    }
  });
  chipRow.appendChild(chip);
  _ensureAddSkillBtn();
  _saveTabChips(_activeTabId);
}

/* ── + Add Skill button in chip row ───────────────────── */
function _ensureAddSkillBtn() {
  const chipRow = document.getElementById('chat-chip-row');
  let addBtn = chipRow.querySelector('.chip-add-btn');
  if (!addBtn) {
    addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'chip-add-btn';
    addBtn.title = 'Skill Marketplace';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '13');
    svg.setAttribute('height', '13');
    svg.setAttribute('viewBox', '0 -960 960 960');
    svg.setAttribute('fill', 'currentColor');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute(
      'd',
      'M739-83.5q-7-2.5-13-8.5L522-296q-6-6-8.5-13t-2.5-15q0-8 2.5-15t8.5-13l85-85q6-6 13-8.5t15-2.5q8 0 15 2.5t13 8.5l204 204q6 6 8.5 13t2.5 15q0 8-2.5 15t-8.5 13l-85 85q-6 6-13 8.5T754-81q-8 0-15-2.5Zm15-92.5 29-29-147-147-29 29 147 147ZM189.5-83q-7.5-3-13.5-9l-84-84q-6-6-9-13.5T80-205q0-8 3-15t9-13l212-212h85l34-34-165-165h-57L80-765l113-113 121 121v57l165 165 116-116-43-43 56-56H495l-28-28 142-142 28 28v113l56-56 142 142q17 17 26 38.5t9 45.5q0 24-9 46t-26 39l-85-85-56 56-42-42-207 207v84L233-92q-6 6-13 9t-15 3q-8 0-15.5-3Zm15.5-93 170-170v-29h-29L176-205l29 29Zm0 0-29-29 15 14 14 15Zm549 0 29-29-29 29Z',
    );
    svg.appendChild(path);
    addBtn.appendChild(svg);
    addBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      window.openSettingsPanel?.('skills');
    });
    chipRow.prepend(addBtn);
  }
}

/* ── Dynamic placeholder ──────────────────────────────── */
const _DOC_SKILL_IDS = new Set(['docx', 'excel', 'ppt']);

function _updatePlaceholder() {
  const inp = document.getElementById('chat-input');
  if (!inp || inp.contentEditable === 'false') return;
  // Guide div handles all education — placeholder is empty
  inp.dataset.placeholder = '';
}

function _setRailActive(id) {
  document.querySelectorAll('.dock-item[data-skill-id]').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.skillId === id);
    btn.setAttribute('aria-pressed', btn.dataset.skillId === id ? 'true' : 'false');
  });
  const home = document.getElementById('dock-home');
  if (home) home.classList.toggle('active', id === 'gator');
}

/* ── Dock / Launcher unread badge ─────────────────────── */
function updateRailBadge(skillId, count) {
  const dockBadge = document.getElementById('dock-badge-' + skillId);
  if (dockBadge) {
    if (count > 0) {
      dockBadge.textContent = count > 99 ? '99+' : String(count);
      dockBadge.classList.remove('hidden');
    } else {
      dockBadge.textContent = '';
      dockBadge.classList.add('hidden');
    }
  }
  const launcherBadge = document.getElementById('launcher-badge-' + skillId);
  if (launcherBadge) {
    if (count > 0) {
      launcherBadge.textContent = count > 99 ? '99+' : String(count);
      launcherBadge.classList.remove('hidden');
    } else {
      launcherBadge.textContent = '';
      launcherBadge.classList.add('hidden');
    }
  }
}

/* ── / Skill Picker (reuses mention dropdown infrastructure) ── */
let _slashDropdown = null; // kept as alias so legacy _closeSlashDropdown calls still work
let _slashFocusIdx = -1;
let _slashCurrentQuery = null; // track last rendered query to avoid re-rendering on same query

// Cleanup #8 (2026-08-07 milestone adversarial review): the SKILLS and
// COMMANDS sections of _openSkillPickerDropdown each wired an identical
// mouseenter handler on their `.skill-mention-item` rows (recompute
// _mentionFocusIdx from DOM order, toggle .focused on all rows) — extracted
// here so the two sections can't drift apart. The rest of each row's build
// (chevron/inline actions for SKILLS, description/plugin_id badge for
// COMMANDS) differs enough that unifying further would be more awkward than
// it's worth, so only the focus-wiring is shared.
function _wireMentionRowFocus(item) {
  item.addEventListener('mouseenter', () => {
    _mentionFocusIdx = Array.from(_mentionDropdown.querySelectorAll('.skill-mention-item')).indexOf(
      item,
    );
    _mentionDropdown
      .querySelectorAll('.skill-mention-item')
      .forEach((el, i) => el.classList.toggle('focused', i === _mentionFocusIdx));
  });
}

function _openSkillPickerDropdown(query) {
  // If dropdown is already open with the same query, don't rebuild (preserves expanded state)
  if (_mentionDropdown && _slashCurrentQuery === query) return;
  _slashCurrentQuery = query;

  closeMentionDropdown();
  closeChannelDropdown();
  _mentionDropdown = _buildDropdown();
  _mentionFocusIdx = -1;

  const q = query.toLowerCase();
  const skillMatches = _fuzzyFilterSkills(
    SKILL_REGISTRY.filter((s) => !s._customApp),
    q,
  );
  const commandMatches = _fuzzyFilterCommands(PLUGIN_COMMANDS, q);

  if (!skillMatches.length && !commandMatches.length) {
    closeMentionDropdown();
    return;
  }

  if (skillMatches.length) _addSectionLabel(_mentionDropdown, 'SKILLS');

  const hasImages = _aigatorImages.length > 0;

  skillMatches.forEach((s) => {
    const alias = s.chipAlias || s.id;
    const badgeHtml = s.labelBadge ? ` <span class="skill-alpha-badge">${s.labelBadge}</span>` : '';
    const actions = (s.actions || []).filter(
      (a) => !(s.id === 'gator' && a.group === 'export' && !hasImages),
    );
    const hasActions = actions.length > 0;

    // Wrapper holds both the skill row and (optionally) the inline actions
    const wrapper = document.createElement('div');
    wrapper.className = 'skill-mention-wrapper';

    // Main skill row — clicking commits the chip
    const item = document.createElement('div');
    item.className = 'skill-mention-item';
    item.dataset.type = 'slash-skill';
    item.dataset.skillId = s.id;

    const mainZone = document.createElement('span');
    mainZone.className = 'skill-mention-main';
    mainZone.innerHTML = `<span class="skill-mention-icon">${s.icon}</span><span class="skill-mention-name">/${alias}</span><span class="skill-mention-badge">${s.label}${badgeHtml}</span>`;
    mainZone.addEventListener('mousedown', (e) => {
      e.preventDefault();
      _commitSkillChipOnly(s, '/');
    });
    item.appendChild(mainZone);

    if (hasActions) {
      const chevronBtn = document.createElement('span');
      chevronBtn.className = 'skill-mention-chevron-btn';
      chevronBtn.textContent = '›';
      chevronBtn.title = 'Show actions';

      // Inline actions container (hidden by default)
      const actionsGroup = document.createElement('div');
      actionsGroup.className = 'skill-mention-actions-group hidden';

      chevronBtn.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const isOpen = !actionsGroup.classList.contains('hidden');
        // Collapse any other open action groups
        _mentionDropdown
          .querySelectorAll('.skill-mention-actions-group')
          .forEach((g) => g.classList.add('hidden'));
        _mentionDropdown
          .querySelectorAll('.skill-mention-chevron-btn')
          .forEach((b) => b.classList.remove('open'));
        if (!isOpen) {
          actionsGroup.classList.remove('hidden');
          chevronBtn.classList.add('open');
        }
      });

      actions.forEach((action) => {
        const boundAction = Object.assign({}, action, { skill: s });
        const aItem = document.createElement('div');
        aItem.className = 'skill-mention-action-row';
        aItem.dataset.type = 'action';
        const liveHtml = action.live ? '<span class="slash-live-dot"></span>' : '';
        aItem.innerHTML = `<span class="skill-mention-icon">${action.icon}</span><span class="skill-mention-name">${action.label}</span>${liveHtml}`;
        aItem.addEventListener('mousedown', (e) => {
          e.preventDefault();
          closeMentionDropdown();
          _selectSlashAction(boundAction);
        });
        actionsGroup.appendChild(aItem);
      });

      item.appendChild(chevronBtn);
      wrapper.appendChild(item);
      wrapper.appendChild(actionsGroup);
    } else {
      wrapper.appendChild(item);
    }

    _wireMentionRowFocus(item);

    _mentionDropdown.appendChild(wrapper);
  });

  // Decision #12 (2026-08-07 milestone) — COMMANDS section, populated from
  // installed plugin commands (marketplace/commands.py's COMMAND_REGISTRY,
  // bootstrapped as window.__PLUGIN_COMMANDS__ / live-updated via
  // window.registerPluginCommand). Selecting one inserts "/name " as plain
  // text, not a chip — see _commitCommandOnly for why.
  if (commandMatches.length) {
    _addSectionLabel(_mentionDropdown, 'COMMANDS');
    commandMatches.forEach((cmd) => {
      const item = document.createElement('div');
      item.className = 'skill-mention-item';
      item.dataset.type = 'slash-command';
      item.dataset.commandName = cmd.name;

      const mainZone = document.createElement('span');
      mainZone.className = 'skill-mention-main';
      const subtitle = cmd.description || (cmd.plugin_id ? `from ${cmd.plugin_id}` : '');
      mainZone.innerHTML = `<span class="skill-mention-icon">/</span><span class="skill-mention-name">/${escapeHtml(cmd.name)}</span><span class="skill-mention-badge">${escapeHtml(subtitle)}</span>`;
      mainZone.addEventListener('mousedown', (e) => {
        e.preventDefault();
        _commitCommandOnly(cmd);
      });
      item.appendChild(mainZone);

      _wireMentionRowFocus(item);

      _mentionDropdown.appendChild(item);
    });
  }

  const firstItem = _mentionDropdown.querySelector('.skill-mention-item');
  if (firstItem) {
    firstItem.classList.add('focused');
    _mentionFocusIdx = 0;
  }

  // Marketplace footer — always visible at bottom of slash menu
  const mktFooter = document.createElement('div');
  mktFooter.className = 'slash-marketplace-footer';
  const mktIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  mktIcon.setAttribute('width', '12');
  mktIcon.setAttribute('height', '12');
  mktIcon.setAttribute('viewBox', '0 -960 960 960');
  mktIcon.setAttribute('fill', 'currentColor');
  const mktPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  mktPath.setAttribute(
    'd',
    'M739-83.5q-7-2.5-13-8.5L522-296q-6-6-8.5-13t-2.5-15q0-8 2.5-15t8.5-13l85-85q6-6 13-8.5t15-2.5q8 0 15 2.5t13 8.5l204 204q6 6 8.5 13t2.5 15q0 8-2.5 15t-8.5 13l-85 85q-6 6-13 8.5T754-81q-8 0-15-2.5Zm15-92.5 29-29-147-147-29 29 147 147ZM189.5-83q-7.5-3-13.5-9l-84-84q-6-6-9-13.5T80-205q0-8 3-15t9-13l212-212h85l34-34-165-165h-57L80-765l113-113 121 121v57l165 165 116-116-43-43 56-56H495l-28-28 142-142 28 28v113l56-56 142 142q17 17 26 38.5t9 45.5q0 24-9 46t-26 39l-85-85-56 56-42-42-207 207v84L233-92q-6 6-13 9t-15 3q-8 0-15.5-3Zm15.5-93 170-170v-29h-29L176-205l29 29Zm0 0-29-29 15 14 14 15Zm549 0 29-29-29 29Z',
  );
  mktIcon.appendChild(mktPath);
  const mktLabel = document.createElement('span');
  mktLabel.textContent = 'Browse Skill Marketplace';
  mktFooter.appendChild(mktIcon);
  mktFooter.appendChild(mktLabel);
  mktFooter.addEventListener('mousedown', (e) => {
    e.preventDefault();
    closeMentionDropdown();
    window.openSettingsPanel?.('skills');
  });
  _mentionDropdown.appendChild(mktFooter);
}

// Commit chip only — no action popup
function _commitSkillChipOnly(skill, trigger) {
  const alias = skill.chipAlias || skill.id;
  const t = trigger || '/';
  _replaceAtHashInInput(t, () =>
    _createInlineChip('chip-skill', t + alias, { skillId: skill.id, triggerPrefix: t }),
  );
  const isTPOpen =
    typeof tpState !== 'undefined' && tpState?.type && _TP_SKILL_IDS.has(tpState.type);
  const inGator = _activeSkillId === 'gator';
  if (!inGator) {
    _activeSkillId = skill.id;
    if (!isTPOpen && !skill?.railHidden) _setRailActive(skill.id);
  }
  _addSkillChip(skill.id);
  _updatePlaceholder();
  closeMentionDropdown();
}

// Commit a plugin command from the "/" dropdown (decision #12). Unlike a
// skill, a command is NOT rendered as an inline chip — it's a parameterized
// prompt-template the user types args after (marketplace/commands.py's
// $ARGUMENTS/$1/$2 substitution expects literal text, not a chip node), so
// this inserts plain "/name " text at the trigger and leaves the cursor
// positioned right after it for the user to type args. Reuses
// _replaceAtHashInInput exactly as skill selection does — chipFactory only
// needs to return SOME node to insert, and a text node works just as well
// as a chip element.
function _commitCommandOnly(command) {
  _replaceAtHashInInput('/', () => document.createTextNode('/' + command.name));
  closeMentionDropdown();
}

// Alias so legacy call sites still compile
function _openSlashDropdown(query) {
  _openSkillPickerDropdown(query);
}
function _closeSlashDropdown() {
  // Only close if showing a / skill picker (not a @ people search)
  if (
    _mentionDropdown &&
    _mentionDropdown.querySelector('[data-type="slash-skill"], [data-type="action"]')
  ) {
    closeMentionDropdown();
  }
}

function _selectSlashSkill(skill) {
  _closeSlashDropdown();
  const alias = skill.chipAlias || skill.id;
  _replaceAtHashInInput('/', () =>
    _createInlineChip('chip-skill', '/' + alias, { skillId: skill.id }),
  );
  const isTPOpen =
    typeof tpState !== 'undefined' && tpState?.type && _TP_SKILL_IDS.has(tpState.type);
  const inGator = _activeSkillId === 'gator';
  if (!inGator) {
    _activeSkillId = skill.id;
    if (!isTPOpen && !skill.railHidden) _setRailActive(skill.id);
  }
  _addSkillChip(skill.id);
  _updatePlaceholder();
}

function _selectSlashAction(action) {
  console.log(
    '[selectSlash] action:',
    action?.label,
    'prompt:',
    action?.prompt?.slice(0, 50),
    'skill:',
    action?.skill?.id,
  );
  _closeSlashDropdown();
  const skill = action.skill;

  if (action.filePicker) {
    const { filetypes } = action.filePicker;
    fetch('/api/file-picker', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Select a file', filetypes }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.ok && data.file_path) {
          // Insert file chip into compose area — DON'T auto-send
          const fileName = data.file_path.split(/[/\\]/).pop();
          const ext = fileName.split('.').pop().toLowerCase();
          const fileIconSrc = {
            xlsx: '/static/icons/excel-file.png',
            xls: '/static/icons/excel-file.png',
            csv: '/static/icons/excel-file.png',
            docx: '/static/icons/word-file.png',
            doc: '/static/icons/word-file.png',
            pptx: '/static/icons/ppt-file.png',
            ppt: '/static/icons/ppt-file.png',
            pdf: '/static/icons/pdf-file.png',
          }[ext];
          const chip = document.createElement('span');
          chip.className = 'pin-ref-chip file-ref-chip';
          chip.contentEditable = 'false';
          chip.dataset.filePath = data.file_path;
          chip.dataset.fileName = fileName;
          chip.title = fileName;
          if (fileIconSrc) {
            const icon = document.createElement('img');
            icon.src = fileIconSrc;
            icon.className = 'file-chip-icon';
            icon.alt = ext;
            chip.appendChild(icon);
            chip.appendChild(document.createTextNode(' ' + fileName));
          } else {
            chip.textContent = '\uD83D\uDCC1 ' + fileName;
          }
          const input = document.getElementById('chat-input');
          input.appendChild(chip);
          input.appendChild(document.createTextNode('\u00A0'));
          input.focus();
          if (typeof _moveCaretToEnd === 'function') _moveCaretToEnd(input);
          // Activate the skill chip too
          if (skill?.id) selectSkill(skill.id);
        }
      })
      .catch(() => {});
    return;
  }
  if (action.tpAction) {
    input.textContent = '';
    input.dispatchEvent(new Event('input'));
    const alreadyOpen = tpState?.type === action.tpAction;
    selectSkill(action.tpAction);
    if (alreadyOpen) {
      const title = document.getElementById('tp-title');
      if (title) {
        title.classList.remove('tp-title-pulse');
        void title.offsetWidth;
        title.classList.add('tp-title-pulse');
      }
    }
    return;
  }
  if (action.live && !localStorage.getItem(RAIL_CONFIRM_SKIP_KEY)) {
    _showLiveConfirmInline(action, skill);
  } else {
    injectChip(skill.id, action.prompt, action.inputHint);
  }
}

function _showLiveConfirmInline(action, skill) {
  const popover = document.getElementById('qa-confirm-popover');
  if (!popover) {
    injectChip(skill.id, action.prompt, action.inputHint);
    return;
  }
  document.getElementById('qa-confirm-msg').textContent =
    `This will modify your open ${action.label.includes('presentation') ? 'presentation' : 'workbook'}. Changes may not be undoable. Proceed?`;
  popover.classList.remove('hidden');

  // Position above the input
  const inputRow = document.getElementById('chat-input-row');
  const r = inputRow.getBoundingClientRect();
  popover.style.top = r.top - 10 + 'px';
  popover.style.left = r.left + r.width / 2 + 'px';
  popover.style.transform = 'translate(-50%, -100%)';
  popover.style.position = 'fixed';

  const cleanup = () => popover.classList.add('hidden');
  document.getElementById('qa-confirm-ok').onclick = () => {
    if (document.getElementById('qa-confirm-skip-cb')?.checked)
      localStorage.setItem(RAIL_CONFIRM_SKIP_KEY, '1');
    cleanup();
    injectChip(skill.id, action.prompt, action.inputHint);
  };
  document.getElementById('qa-confirm-cancel').onclick = cleanup;
}

/* Legacy stubs — called from other parts of the code */
function _showQuickActions() {
  /* replaced by / dropdown */
}
function _hideQuickActions() {
  /* replaced by / dropdown */
}

/* ── Chat pane resize ────────────────────────────────── */
function initChatResize() {
  const handle = document.getElementById('main-resize');
  const main = document.querySelector('.main');
  if (!handle || !main) return;

  const MIN_W = 320,
    MAX_W = 900;
  const saved = parseInt(localStorage.getItem('chat-pane-width'));
  if (saved) main.style.flexBasis = saved + 'px';

  let dragging = false,
    startX = 0,
    startW = 0;

  handle.addEventListener('mousedown', (e) => {
    dragging = true;
    startX = e.clientX;
    const tp = document.getElementById('third-pane');
    startW = tp && tp.classList.contains('is-open') ? tp.offsetWidth : main.offsetWidth;
    handle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    // Overlay prevents iframes stealing pointer events
    const overlay = document.createElement('div');
    overlay.id = 'main-resize-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;cursor:col-resize;';
    document.body.appendChild(overlay);
    e.preventDefault();
  });
  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const tp = document.getElementById('third-pane');
    if (tp && tp.classList.contains('is-open')) {
      // Handle on left edge of chat (right edge of third-pane, which now
      // docks to the LEFT of chat): dragging right = wider third-pane.
      const TP_MIN = 400,
        TP_MAX = Math.floor(window.innerWidth * 0.7);
      const w = Math.min(TP_MAX, Math.max(TP_MIN, startW + (e.clientX - startX)));
      document.documentElement.style.setProperty('--third-pane-w', w + 'px');
    } else {
      // Normal mode: handle on left edge of chat, dragging left = wider chat
      const w = Math.min(MAX_W, Math.max(MIN_W, startW - (e.clientX - startX)));
      main.style.flexBasis = w + 'px';
    }
  });
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    const overlay = document.getElementById('main-resize-overlay');
    if (overlay) overlay.remove();
    const tp = document.getElementById('third-pane');
    if (tp && tp.classList.contains('is-open')) {
      localStorage.setItem(
        'tp-pane-width',
        parseInt(getComputedStyle(document.documentElement).getPropertyValue('--third-pane-w')),
      );
    } else {
      localStorage.setItem('chat-pane-width', main.offsetWidth);
    }
  });
}

/* ── Chip injection ──────────────────────────────────── */
function injectChip(skillId, promptText, inputHint) {
  const skill = SKILL_MAP[skillId];
  if (!skill) return;

  // Add chip via shared helper (prevents duplicates)
  _addSkillChip(skillId);
  // Store the prompt text for this action
  const existing = _activeChips.find((c) => c.skillId === skillId);
  if (existing) existing.promptText = promptText;

  // Strip leading @skillId prefix if present
  const atPrefix = `@${skillId} `;
  const body = promptText.startsWith(atPrefix) ? promptText.slice(atPrefix.length) : promptText;

  // Clear everything (inline chips, text, file chips) then set fresh text
  console.log(
    '[injectChip] skillId:',
    skillId,
    'body:',
    body?.slice(0, 50),
    'inputHint:',
    inputHint,
  );
  input.innerHTML = '';
  input.textContent = body;
  console.log('[injectChip] input.textContent after set:', input.textContent?.slice(0, 50));
  console.log('[injectChip] _getInputText():', _getInputText()?.slice(0, 50));
  input.dispatchEvent(new Event('input'));
  input.focus();
  // Move cursor to end
  const range = document.createRange();
  range.selectNodeContents(input);
  range.collapse(false);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);

  if (!inputHint) {
    // Complete prompt — submit immediately
    form.requestSubmit();
  }
  // If inputHint: user sees the prompt prefilled, cursor at end, types the rest and hits send
}

function _selectChip(chip) {
  document
    .querySelectorAll('.chat-chip.chip-selected')
    .forEach((c) => c.classList.remove('chip-selected'));
  chip.classList.add('chip-selected');
  chip.focus();
}

function removeChip(skillId, autoSelectNext = false) {
  // @gator is always-on by default — only removable via explicit X click, not backspace
  if (skillId === 'gator' && autoSelectNext) return;
  const idx = _activeChips.findIndex((c) => c.skillId === skillId);
  _activeChips = _activeChips.filter((c) => c.skillId !== skillId);
  const chip = document.querySelector(`.chat-chip[data-skill-id="${skillId}"]`);
  if (chip) chip.remove();
  // If removing the active skill, fall back to gator or null
  if (_activeSkillId === skillId) {
    _activeSkillId = _activeChips.some((c) => c.skillId === 'gator')
      ? 'gator'
      : _activeChips.length
        ? _activeChips[_activeChips.length - 1].skillId
        : null;
    _setRailActive(_activeSkillId);
  }
  _updatePlaceholder();
  _ensureAddSkillBtn();
  _saveTabChips(_activeTabId);
  // Auto-select the nearest remaining chip so user can keep pressing backspace
  if (autoSelectNext && _activeChips.length) {
    const nextIdx = Math.min(idx, _activeChips.length - 1);
    const nextChip = document.querySelector(
      `.chat-chip[data-skill-id="${_activeChips[nextIdx].skillId}"]`,
    );
    if (nextChip) _selectChip(nextChip);
  }
}

function buildFinalMessage(typedText) {
  let text = typedText;
  // Append resolved people context so Claude has the email addresses
  const people = window._resolvedPeople || [];
  if (people.length) {
    const ctx = people
      .map((p) => `[${p.name} = ${p.email}${p.job_title ? ', ' + p.job_title : ''}]`)
      .join(', ');
    text = `${text}\n(Resolved contacts: ${ctx})`;
  }
  if (_activeChips.length === 0) return text;
  // Chips are UI-only — send just the prompt text, not the @alias prefix
  const body =
    text ||
    _activeChips
      .map((c) => c.promptText)
      .filter(Boolean)
      .join('\n');
  return body;
}

/* ── Connection status dots ──────────────────────────── */
async function checkSkillConnectionStatus() {
  let m365Ok = false;
  let teamsOk = false;
  let apiOk = false;
  let jiraOk = false;
  let confluenceOk = false;
  let slackOk = false;

  try {
    const d = await fetch('/api/auth/status').then((r) => r.json());
    m365Ok = d.authenticated === true;
    teamsOk = d.teams_token_ok === true;
  } catch {}
  try {
    const d = await fetch('/api/config/apikey/status').then((r) => r.json());
    apiOk = d.configured === true;
  } catch {}
  try {
    const d = await fetch('/api/config/jira/status').then((r) => r.json());
    jiraOk = d.configured === true && !d.error;
    window.GATOR_JIRA_URL = d.base_url || '';
  } catch {
    window.GATOR_JIRA_URL = '';
  }
  // Collect every distinct Jira host across legacy config + MCP connections.
  // The bare-key auto-linker only runs when exactly one is known; with two+
  // we can't tell which cloud a key like ROCM-123 belongs to, and a wrong
  // link is worse than no link.
  try {
    const bases = new Set();
    if (window.GATOR_JIRA_URL) bases.add(window.GATOR_JIRA_URL.replace(/\/+$/, ''));
    const mcp = await fetch('/api/config/mcp').then((r) => r.json());
    for (const c of mcp.connections || []) {
      if (c.transport !== 'http' || !c.url) continue;
      if (!/atlassian|jira/i.test(c.url) && !/jira/i.test(c.name || '')) continue;
      try {
        const u = new URL(c.url);
        bases.add(`${u.protocol}//${u.host}`);
      } catch {}
    }
    window.GATOR_JIRA_INSTANCES = Array.from(bases);
  } catch {
    window.GATOR_JIRA_INSTANCES = window.GATOR_JIRA_URL ? [window.GATOR_JIRA_URL] : [];
  }
  try {
    const d = await fetch('/api/config/confluence/status').then((r) => r.json());
    confluenceOk = d.configured === true && !d.error;
  } catch {}
  try {
    const d = await fetch('/api/auth/slack/status').then((r) => r.json());
    slackOk = d.configured === true && !!d.user;
  } catch {}

  SKILL_REGISTRY.forEach((s) => {
    if (['email', 'calendar', 'onedrive', 'contacts', 'people'].includes(s.id))
      s.connected = m365Ok;
    else if (s.id === 'teams') s.connected = teamsOk;
    else if (s.id === 'jira') s.connected = jiraOk;
    else if (s.id === 'confluence') s.connected = confluenceOk;
    else if (s.id === 'slack') s.connected = slackOk;
    else if (s.id === 'gator') s.connected = apiOk;
    else if (s.id === 'github') s.connected = githubOk;
    else if (s.id === 'ado') s.connected = false;
    else s.connected = apiOk;
  });

  document.querySelectorAll('.skill-icon-btn').forEach((btn) => {
    const skill = SKILL_MAP[btn.dataset.skillId];
    if (!skill) return;
    const dot = btn.querySelector('.skill-status-dot');
    if (dot)
      dot.className = `skill-status-dot ${skill.connected ? 'dot-connected' : 'dot-disconnected'}`;
  });
}

/* ── Context window meter ────────────────────────────── */
let _contextUsed = 0;
let _contextLimit = 200000;

const _CTX_CIRCUMFERENCE = 100.53; // 2π × r=16

function _updateContextMeter() {
  const pct = _contextLimit > 0 ? Math.min(_contextUsed / _contextLimit, 1) : 0;
  const track = document.getElementById('ctx-arc-track');
  const btn = document.getElementById('send-btn');
  if (!track || !btn) return;

  // Animate arc: offset=circumference means 0%, offset=0 means 100%
  track.style.strokeDashoffset = pct === 0 ? _CTX_CIRCUMFERENCE : _CTX_CIRCUMFERENCE * (1 - pct);

  // Progressive color stages
  if (pct >= 0.95) btn.dataset.ctx = 'crit';
  else if (pct >= 0.9) btn.dataset.ctx = 'high';
  else if (pct >= 0.75) btn.dataset.ctx = 'warn';
  else delete btn.dataset.ctx;
}

/* ── # channel state ─────────────────────────────────── */
let _activeChannels = []; // [{team_id, channel_id, channel_name, team_name}]

function _addChannelChip(ch) {
  const uid = ch.chat_id || ch.channel_id;
  if (document.querySelector(`.channel-chip[data-channel-id="${uid}"]`)) return;
  const chipRow = document.getElementById('chat-chip-row');
  chipRow.classList.remove('hidden');
  const chip = document.createElement('span');
  const isGC = ch.type === 'groupchat';
  const isSlack = ch.type === 'slack_channel';
  chip.className = 'chat-chip ' + (isSlack ? 'chip-slack' : 'chip-teams') + ' channel-chip';
  chip.dataset.channelId = uid;
  const icon = isGC ? '💬' : '#';
  const sub = isGC ? 'Group Chat' : ch.team_name;
  chip.innerHTML = `${icon}${escapeHtml(ch.channel_name)} <span class="chip-sub">${escapeHtml(sub)}</span> <button class="chip-remove" aria-label="Remove">&#10005;</button>`;
  chip.querySelector('.chip-remove').addEventListener('click', () => {
    _activeChannels = _activeChannels.filter((c) => (c.chat_id || c.channel_id) !== uid);
    chip.remove();
    _updatePlaceholder();
  });
  chipRow.appendChild(chip);
}

/* ── { pin reference dropdown ───────────────────────── */
let _pinDropdown = null;
let _pinFocusIdx = -1;
let _pinSearchController = null;

function closePinDropdown() {
  if (_pinSearchController) {
    _pinSearchController.abort();
    _pinSearchController = null;
  }
  if (_pinDropdown) {
    _pinDropdown.remove();
    _pinDropdown = null;
    _pinFocusIdx = -1;
  }
}

/* ── Office document icons (used by { pins + @ chip docActions) ── */
const _OFFICE_ICONS = { word: '\uD83D\uDCC4', excel: '\uD83D\uDCCA', ppt: '\uD83D\uDCD1' };

// Sources that have a real SVG logo in /static/icons/
const _SVG_ICON_SOURCES = new Set([
  'email',
  'teams',
  'onedrive',
  'confluence',
  'jira',
  'slack',
  'calendar',
  'github',
  'sharepoint',
]);

function _pinSourceIcon(source, size) {
  const px = size || 16;
  const file = source === 'email' ? 'outlook' : source;
  if (_SVG_ICON_SOURCES.has(source)) {
    return `<img src="/static/icons/${file}.svg" width="${px}" height="${px}" style="vertical-align:middle;flex-shrink:0" alt="${source}">`;
  }
  return _OFFICE_ICONS[source] || '\uD83D\uDCCC';
}

function _addPinItem(dd, pin, i) {
  const item = document.createElement('div');
  item.className = 'skill-mention-item';
  item.dataset.pinIdx = i;
  item.innerHTML = `<span class="skill-mention-icon">${_pinSourceIcon(pin.source)}</span><span class="skill-mention-name">${escapeHtml(pin.label)}</span><span class="skill-mention-badge">${pin.source}</span>`;
  item.addEventListener('mousedown', (e) => {
    e.preventDefault();
    commitPinMention(pin);
  });
  dd.appendChild(item);
}

async function openPinDropdown(query) {
  closePinDropdown();
  const cid = typeof _activeTabId !== 'undefined' ? _activeTabId : 'default';
  _pinDropdown = _buildDropdown();
  const loading = document.createElement('div');
  loading.className = 'skill-mention-loading';
  loading.textContent = 'Loading pinned items…';
  _pinDropdown.appendChild(loading);
  _pinSearchController = new AbortController();

  let pins;
  try {
    pins = await fetch(`/api/context/pins?context_id=${cid}`, {
      signal: _pinSearchController.signal,
    }).then((r) => (r.ok ? r.json() : []));
  } catch (err) {
    if (err.name === 'AbortError') return;
    pins = [];
  }
  if (!_pinDropdown) return;
  _pinSearchController = null;
  _pinDropdown.innerHTML = '';
  if (!pins.length) {
    closePinDropdown();
    return;
  }
  const q = query.toLowerCase();
  const filtered = q
    ? pins.filter(
        (p) =>
          (p.label || '').toLowerCase().includes(q) || (p.source || '').toLowerCase().includes(q),
      )
    : pins;
  if (!filtered.length) {
    closePinDropdown();
    return;
  }
  filtered.forEach((p, i) => _addPinItem(_pinDropdown, p, i));
  _pinDropdown._pins = filtered;
  _pinFocusIdx = -1;
}

// Build a canonical pin-ref chip element (icon + label, no X button).
// Single source of truth for chip markup so every insertion path — the Shift+{
// dropdown AND the Electron shell's Slack/Teams pin forwarder — produces an
// identical-looking chip. pin: { source, id, label }.
function buildPinChipEl(pin) {
  const chip = document.createElement('span');
  chip.className = 'pin-ref-chip';
  chip.contentEditable = 'false';
  chip.dataset.pinSource = pin.source;
  chip.dataset.pinId = pin.id;
  chip.title = `${pin.source}: ${pin.label}`;
  const iconHtml = _pinSourceIcon(pin.source, 14);
  if (iconHtml.startsWith('<img')) {
    chip.innerHTML = `${iconHtml} ${escapeHtml(pin.label)}`;
  } else {
    chip.textContent = `${iconHtml} ${pin.label}`;
  }
  return chip;
}

// Insert a pin chip at the current caret in the chat composer, exactly as the
// Shift+{ dropdown does (no trailing line/space, no X button). Called by the
// Electron shell's pin forwarder via executeJavaScript so shell-pinned chips
// match dropdown-pinned chips. Returns 'ok' | 'no input'.
window.insertPinChipAtCaret = function (pin) {
  const input = document.getElementById('chat-input');
  if (!input) return 'no input';
  const chip = buildPinChipEl(pin);
  input.focus();
  const sel = window.getSelection();
  let range;
  // Insert at the caret if it's inside the input; otherwise append at the end.
  if (sel && sel.rangeCount && input.contains(sel.anchorNode)) {
    range = sel.getRangeAt(0);
    range.deleteContents();
  } else {
    range = document.createRange();
    range.selectNodeContents(input);
    range.collapse(false);
  }
  range.insertNode(chip);
  // Place caret immediately after the chip (no extra text node / newline).
  range.setStartAfter(chip);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  return 'ok';
};

function commitPinMention(pin) {
  closePinDropdown();
  _replaceAtHashInInput('{', () => buildPinChipEl(pin));
}

/* ── @ mention dropdown ──────────────────────────────── */
let _mentionDropdown = null;
let _mentionFocusIdx = -1;
let _mentionSearchController = null; // AbortController for in-flight people searches
let _mentionDropdownCleanup = null;

function _getChatInputAnchor() {
  return document.getElementById('chat-input-row') || document.getElementById('chat-form');
}

/**
 * _fpopup — shared Floating UI wrapper for all app popups.
 *
 * Positions `el` relative to `anchor` using FloatingUIDOM (flip + shift + size)
 * and wires up autoUpdate so scroll, resize, and DOM changes keep it correct.
 *
 * Returns a cleanup function (call it when the popup is removed).
 *
 * opts:
 *   placement   — Floating UI placement string, default 'bottom-start'
 *   offsetY     — gap between anchor and popup, default 8
 *   minWidth    — force a minimum width on el, default 0 (no constraint)
 *   matchWidth  — if true, el width = anchor width
 *   zIndex      — default 99999
 *   padding     — viewport padding (px), default 8
 *   onUpdate    — called after each reposition (optional)
 */
function _fpopup(
  el,
  anchor,
  {
    placement = 'bottom-start',
    offsetY = 8,
    minWidth = 0,
    matchWidth = false,
    zIndex = 99999,
    padding = 8,
    onUpdate = null,
    once = false, // true = position once only, no autoUpdate (use for transient hover-anchored popups)
  } = {},
) {
  if (!anchor || !el) return () => {};

  const { computePosition, autoUpdate, flip, shift, size, offset } = FloatingUIDOM;

  el.style.position = 'fixed';
  el.style.zIndex = String(zIndex);
  el.style.visibility = 'hidden'; // hide until first position is computed

  const update = () => {
    if (!el.isConnected) return;
    if (matchWidth) el.style.width = anchor.getBoundingClientRect().width + 'px';
    else if (minWidth) el.style.minWidth = minWidth + 'px';

    computePosition(anchor, el, {
      strategy: 'fixed',
      placement,
      middleware: [
        offset(offsetY),
        flip({ padding }),
        shift({ padding }),
        size({
          padding,
          apply({ availableHeight, availableWidth }) {
            el.style.maxHeight = Math.max(120, availableHeight) + 'px';
            el.style.overflowY = 'auto';
            el.style.overflowX = 'hidden';
          },
        }),
      ],
    }).then(({ x, y }) => {
      el.style.left = Math.round(x) + 'px';
      el.style.top = Math.round(y) + 'px';
      el.style.bottom = 'auto';
      el.style.right = 'auto';
      el.style.visibility = 'visible';
      if (onUpdate) onUpdate();
    });
  };

  update();
  if (once)
    return () => {
      el.style.maxHeight = '';
    };
  const cleanup = autoUpdate(anchor, el, update);
  return () => {
    cleanup();
    el.style.maxHeight = '';
  };
}

// _positionDropdownFixed — kept as thin wrapper around _fpopup so all callers
// continue to work unchanged. The offsetLeft param shifts the popup right of
// the anchor's left edge; we model that with a custom offset middleware.
function _positionDropdownFixed(dd, anchor, { width = 300, offsetLeft = 14, offsetGap = 8 } = {}) {
  if (!anchor) return () => {};
  const { computePosition, autoUpdate, flip, shift, size, offset } = FloatingUIDOM;
  dd.style.position = 'fixed';
  dd.style.zIndex = '99999';
  dd.style.width = Math.min(width, anchor.getBoundingClientRect().width || width) + 'px';
  dd.style.visibility = 'hidden';

  const update = () => {
    if (!dd.isConnected) return;
    dd.style.width = Math.min(width, anchor.getBoundingClientRect().width || width) + 'px';
    computePosition(anchor, dd, {
      strategy: 'fixed',
      placement: 'bottom-start',
      middleware: [
        offset({ mainAxis: offsetGap, crossAxis: offsetLeft }),
        flip({ padding: 8 }),
        shift({ padding: 8 }),
        size({
          padding: 8,
          apply({ availableHeight }) {
            dd.style.maxHeight = Math.max(120, availableHeight) + 'px';
            dd.style.overflowY = 'auto';
            dd.style.overflowX = 'hidden';
          },
        }),
      ],
    }).then(({ x, y }) => {
      dd.style.left = Math.round(x) + 'px';
      dd.style.top = Math.round(y) + 'px';
      dd.style.bottom = 'auto';
      dd.style.right = 'auto';
      dd.style.visibility = 'visible';
    });
  };

  update();
  const cleanup = autoUpdate(anchor, dd, update);
  return () => {
    cleanup();
    dd.style.maxHeight = '';
  };
}

function closeMentionDropdown() {
  clearTimeout(_mentionDebounceTimer);
  _mentionDebounceTimer = null;
  if (_mentionSearchController) {
    _mentionSearchController.abort();
    _mentionSearchController = null;
  }
  if (_mentionDropdownCleanup) {
    _mentionDropdownCleanup();
    _mentionDropdownCleanup = null;
  }
  if (_mentionDropdown) {
    _mentionDropdown.remove();
    _mentionDropdown = null;
    _mentionFocusIdx = -1;
  }
  _slashCurrentQuery = null;
}

function _buildDropdown() {
  const dd = document.createElement('div');
  dd.className = 'skill-mention-dropdown';
  // Prevent any click inside the dropdown from stealing focus from the input
  dd.addEventListener('mousedown', (e) => e.preventDefault());
  document.body.appendChild(dd);
  const anchor = _getChatInputAnchor();
  _mentionDropdownCleanup = anchor ? _positionDropdownFixed(dd, anchor, { width: 300 }) : null;
  return dd;
}

function _addPersonItem(dd, person) {
  if (!person.name && !person.email) return; // skip empty results
  const item = document.createElement('div');
  item.className = 'skill-mention-item skill-mention-person';
  item.dataset.type = 'person';
  item.dataset.email = person.email;
  item.dataset.name = person.name;
  const displayName = person.name || person.email || '?';
  const initial = displayName.replace(/^\*+/, '').trim()[0]?.toUpperCase() || '?';
  const subtitle = person.job_title || person.department || person.email || '';
  item.innerHTML = `<span class="skill-mention-avatar">${initial}</span>
    <span class="skill-mention-person-info">
      <span class="skill-mention-name">${escapeHtml(displayName)}</span>
      <span class="skill-mention-sub">${escapeHtml(subtitle)}</span>
    </span>`;
  item.addEventListener('mousedown', (e) => {
    e.preventDefault();
    commitPersonMention(person);
  });
  dd.appendChild(item);
}

function _addSectionLabel(dd, text) {
  const lbl = document.createElement('div');
  lbl.className = 'skill-mention-section';
  lbl.textContent = text;
  dd.appendChild(lbl);
}

let _mentionDebounceTimer = null;

function openMentionDropdown(query) {
  if (!_mentionDropdown) {
    closeChannelDropdown();
    _mentionDropdown = _buildDropdown();
  }
  _mentionDropdown.innerHTML = '';
  _mentionFocusIdx = -1;

  if (_mentionSearchController) {
    _mentionSearchController.abort();
    _mentionSearchController = null;
  }
  clearTimeout(_mentionDebounceTimer);

  const stateDiv = document.createElement('div');
  stateDiv.className = 'skill-mention-loading';
  stateDiv.textContent =
    query.length < 2 ? 'Type a name to search people\u2026' : 'Searching people\u2026';
  _mentionDropdown.appendChild(stateDiv);

  if (query.length < 2) return;

  _mentionDebounceTimer = setTimeout(async () => {
    if (!_mentionDropdown) return;
    _mentionSearchController = new AbortController();
    try {
      const res = await fetch(`/api/people/search?q=${encodeURIComponent(query)}`, {
        signal: _mentionSearchController.signal,
      });
      const data = await res.json();
      if (!_mentionDropdown) return;
      _mentionDropdown.innerHTML = '';
      if (data.people?.length) {
        data.people.forEach((p) => _addPersonItem(_mentionDropdown, p));
        _mentionFocusIdx = 0;
        const firstItem = _mentionDropdown.querySelector('.skill-mention-item');
        if (firstItem) firstItem.classList.add('focused');
      } else {
        const none = document.createElement('div');
        none.className = 'skill-mention-loading';
        none.textContent = 'No results';
        _mentionDropdown.appendChild(none);
      }
    } catch (err) {
      if (err.name === 'AbortError') return;
      if (_mentionDropdown) {
        _mentionDropdown.innerHTML = '';
      }
    }
  }, 250);
}

function commitPersonMention(person) {
  closeMentionDropdown();

  // Replace @query with inline person chip
  _replaceAtHashInInput('@', () =>
    _createInlineChip('chip-person', '@' + person.name, {
      personName: person.name,
      personEmail: person.email || '',
    }),
  );
}

/* ── # channel dropdown ──────────────────────────────── */
let _channelDropdown = null;
let _channelFocusIdx = -1;
let _channelSearchController = null;
let _channels_busted = false;
let _channelDropdownCleanup = null;

function closeChannelDropdown() {
  if (_channelSearchController) {
    _channelSearchController.abort();
    _channelSearchController = null;
  }
  if (_channelDropdownCleanup) {
    _channelDropdownCleanup();
    _channelDropdownCleanup = null;
  }
  if (_channelDropdown) {
    _channelDropdown.remove();
    _channelDropdown = null;
    _channelFocusIdx = -1;
  }
}

async function openChannelDropdown(query) {
  closeChannelDropdown();
  closeMentionDropdown();
  _channelDropdown = document.createElement('div');
  _channelDropdown.className = 'skill-mention-dropdown channel-dropdown';
  document.body.appendChild(_channelDropdown);
  const anchor = _getChatInputAnchor();
  _channelDropdownCleanup = anchor
    ? _positionDropdownFixed(_channelDropdown, anchor, { width: 320 })
    : null;

  // Use cached Teams chats if available — populated whenever Teams pane loads, persists across pane switches
  const _cachedChats = window._teamsChatsCache?.length
    ? window._teamsChatsCache
    : typeof tpState !== 'undefined' && tpState.type === 'teams' && tpState.list?.length
      ? tpState.list
      : null;
  const tpChats = _cachedChats
    ? _cachedChats.map((c) => ({
        type: 'groupchat',
        chat_id: c.id,
        channel_name: c.topic || c.display_name || (c.chat_type === 'meeting' ? 'Meeting' : c.id),
        team_name:
          c.chat_type === 'oneOnOne'
            ? 'Direct Message'
            : c.chat_type === 'meeting'
              ? 'Meetings'
              : 'Group Chat',
      }))
    : null;

  if (tpChats) {
    _channelDropdown.innerHTML = '';
    const ql = query.toLowerCase();
    const channels = tpChats.filter((ch) => {
      if (ql && !ch.channel_name.toLowerCase().includes(ql)) return false;
      return !_activeChannels.some((a) => (a.chat_id || a.channel_id) === ch.chat_id);
    });
    if (!channels.length) {
      _channelDropdown.innerHTML = `<div class="skill-mention-loading">No chats found${query ? ` for "${escapeHtml(query)}"` : ''}</div>`;
      return;
    }
    _renderChannelItems(channels);
    return;
  }

  // Fallback: fetch from API — route to Slack, Teams, or both based on active skills
  const hasSlack = _activeChips.some((c) => c.skillId === 'slack') || _activeSkillId === 'slack';
  const hasTeams = _activeChips.some((c) => c.skillId === 'teams') || _activeSkillId === 'teams';
  // Default to Teams if neither is explicitly active
  const fetchSlack = hasSlack;
  const fetchTeams = hasTeams || !hasSlack;
  const loading = document.createElement('div');
  loading.className = 'skill-mention-loading';
  loading.textContent = 'Loading channels…';
  _channelDropdown.appendChild(loading);

  _channelSearchController = new AbortController();
  try {
    let allChannels = [];
    const ql = query.toLowerCase();

    if (fetchSlack) {
      try {
        const res = await fetch('/api/slack/channels', { signal: _channelSearchController.signal });
        const raw = await res.json();
        const parsed = typeof raw.result === 'string' ? JSON.parse(raw.result) : raw;
        (parsed.channels || []).forEach((ch) => {
          const name = ch.channel_name || ch.name || '';
          if (!ql || name.toLowerCase().includes(ql)) {
            allChannels.push({
              type: 'slack_channel',
              channel_id: name,
              channel_name: name,
              team_name: 'Slack',
            });
          }
        });
      } catch (e) {
        if (e.name === 'AbortError') throw e;
      }
    }

    if (fetchTeams) {
      const bustParam = _channels_busted ? '&bust=true' : '';
      _channels_busted = false;
      const res = await fetch(`/api/channels/search?q=${encodeURIComponent(query)}${bustParam}`, {
        signal: _channelSearchController.signal,
      });
      const teamsData = await res.json();
      if (teamsData.channels) allChannels.push(...teamsData.channels);
    }

    const data = { channels: allChannels };
    if (!_channelDropdown) return;
    _channelDropdown.innerHTML = '';

    const errors = (data.channels || []).filter((ch) => ch.type === '_error');
    const channels = (data.channels || []).filter((ch) => {
      if (ch.type === '_error') return false;
      const uid = ch.type === 'groupchat' ? ch.chat_id : ch.channel_id || ch.channel_name;
      return !_activeChannels.some((a) => (a.chat_id || a.channel_id) === uid);
    });
    if (data.error) {
      _channelDropdown.innerHTML = `<div class="skill-mention-loading" style="color:var(--danger)">⚠ ${escapeHtml(data.error)}</div>`;
      return;
    }
    errors.forEach((e) => {
      const warn = document.createElement('div');
      warn.className = 'skill-mention-loading';
      warn.style.color = 'var(--warn)';
      warn.style.display = 'flex';
      warn.style.alignItems = 'center';
      warn.style.gap = '0.5rem';
      const txt = document.createElement('span');
      txt.textContent = e.channel_name;
      warn.appendChild(txt);
      if (/token expired|re-capture/i.test(e.channel_name)) {
        const btn = document.createElement('button');
        btn.textContent = 'Re-capture ⚡';
        btn.className = 'btn-primary';
        btn.style.cssText = 'padding:2px 8px;font-size:0.75rem;flex-shrink:0;';
        btn.addEventListener('click', (ev) => {
          ev.stopPropagation();
          btn.disabled = true;
          btn.textContent = 'Capturing…';
          const es = new EventSource('/api/auth/teams/capture/stream');
          es.addEventListener('status', (se) => {
            btn.textContent = JSON.parse(se.data);
          });
          es.addEventListener('result', (se) => {
            es.close();
            btn.textContent = '✓ Done';
            _channels_busted = true;
            _showConnectivityToast('Teams token captured', 'success');
            setTimeout(() => openChannelDropdown(''), 800);
          });
          es.addEventListener('error', (se) => {
            es.close();
            btn.disabled = false;
            btn.textContent = 'Re-capture ⚡';
            const msg = se.data ? JSON.parse(se.data) : 'Capture failed';
            _showConnectivityToast(msg, 'error');
          });
          es.onerror = () => {
            if (es.readyState === EventSource.CLOSED) return;
            es.close();
            btn.disabled = false;
            btn.textContent = 'Re-capture ⚡';
          };
        });
        warn.appendChild(btn);
      }
      _channelDropdown.appendChild(warn);
    });
    if (!channels.length) {
      _channelDropdown.innerHTML = `<div class="skill-mention-loading">No channels found${query ? ` for "${escapeHtml(query)}"` : ''}. <span class="channel-refresh-link" style="cursor:pointer;color:var(--accent);text-decoration:underline">Refresh</span></div>`;
      _channelDropdown.querySelector('.channel-refresh-link')?.addEventListener('click', () => {
        _channels_busted = true;
        openChannelDropdown(query);
      });
      return;
    }

    _renderChannelItems(channels);
  } catch (err) {
    if (err.name !== 'AbortError' && _channelDropdown) {
      _channelDropdown.innerHTML =
        '<div class="skill-mention-loading">Could not load channels</div>';
    }
  }
}

function _renderChannelItems(channels) {
  const byTeam = {};
  channels.forEach((ch) => {
    const grp = ch.team_name || 'Group Chat';
    (byTeam[grp] = byTeam[grp] || []).push(ch);
  });
  Object.entries(byTeam).forEach(([teamName, chs]) => {
    const lbl = document.createElement('div');
    lbl.className = 'skill-mention-section';
    lbl.textContent = teamName.toUpperCase();
    _channelDropdown.appendChild(lbl);
    chs.forEach((ch) => {
      const item = document.createElement('div');
      item.className = 'skill-mention-item';
      const isGC = ch.type === 'groupchat';
      item.dataset.type = isGC ? 'groupchat' : 'channel';
      if (isGC) {
        item.dataset.chatId = ch.chat_id;
      } else {
        item.dataset.channelId = ch.channel_id;
        item.dataset.teamId = ch.team_id;
      }
      item.innerHTML = `<span class="skill-mention-icon" style="font-size:.9rem">${isGC ? '💬' : '#'}</span>
        <span class="skill-mention-name">${escapeHtml(ch.channel_name)}</span>
        <span class="skill-mention-badge">${escapeHtml(isGC ? 'Group Chat' : ch.team_name)}</span>`;
      item.addEventListener('mousedown', (e) => {
        e.preventDefault();
        commitChannelMention(ch);
      });
      _channelDropdown.appendChild(item);
    });
  });
}

function commitChannelMention(ch) {
  closeChannelDropdown();

  // Track in _activeChannels
  const uid = ch.chat_id || ch.channel_id;
  if (!_activeChannels.some((c) => (c.chat_id || c.channel_id) === uid)) {
    _activeChannels.push(ch);
  }

  // Replace #query with inline channel chip
  const isSlack = ch.type === 'slack_channel';
  const chipLabel = '#' + ch.channel_name + (isSlack ? '' : '');
  const chipSub = isSlack ? ' Slack' : ' ' + (ch.team_name || 'Teams');
  const chipColorClass = isSlack ? 'chip-slack' : 'chip-teams';
  _replaceAtHashInInput('#', () =>
    _createInlineChip('chip-channel ' + chipColorClass, chipLabel + chipSub, {
      channelName: ch.channel_name,
      channelId: ch.channel_id || '',
      chatId: ch.chat_id || '',
      teamName: ch.team_name || '',
      channelType: ch.type || '',
    }),
  );

  // Ensure appropriate skill is active
  const skillNeeded = isSlack ? 'slack' : 'teams';
  if (!_activeChips.some((c) => c.skillId === skillNeeded)) {
    _addSkillChip(skillNeeded);
  }
  _updatePlaceholder();
}

function _showPersonBadge(person) {
  const chipRow = document.getElementById('chat-chip-row');
  chipRow.classList.remove('hidden');
  // Avoid duplicate badge
  const existing = chipRow.querySelector(`[data-person-email="${person.email}"]`);
  if (existing) return;
  const badge = document.createElement('span');
  badge.className = 'chat-chip chip-person';
  badge.dataset.personEmail = person.email;
  badge.innerHTML = `👤 ${person.name} <span class="chip-sub">${person.email}</span>
    <button class="chip-remove" aria-label="Remove">✕</button>`;
  badge.querySelector('.chip-remove').addEventListener('click', () => {
    badge.remove();
    window._resolvedPeople = (window._resolvedPeople || []).filter((p) => p.email !== person.email);
  });
  chipRow.appendChild(badge);
  _ensureAddSkillBtn(); // keep + at the end
}

/* ── History persistence ─────────────────────────────── */
const HISTORY_KEY = 'chat-history';
const HISTORY_MAX = 50;

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
  } catch {
    return [];
  }
}
function saveHistory(hist) {
  const trimmed = hist.slice(-HISTORY_MAX);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(trimmed));
}
// Strip Slack auth misinformation from history — only model-directed auth actions, not page content
const _SLACK_POISON =
  /go to (Settings|the Settings).*slack|refresh your (slack )?token|sign.?in to slack|reconnect slack|your slack session (has )?expired|re-authenticate (with )?slack/i;
function _sanitizeHistory(hist) {
  return hist.map((m) => {
    if (m.role !== 'assistant' || typeof m.content !== 'string') return m;
    if (!_SLACK_POISON.test(m.content)) return m;
    // Replace the poisoned Slack text with corrected info
    const cleaned = m.content.replace(
      /go to (Settings|the Settings).*slack[^.]*\.|refresh your (slack )?token[^.]*\.|sign.?in to slack[^.]*\.|reconnect slack[^.]*\.|your slack session (has )?expired[^.]*\.|re-authenticate (with )?slack[^.]*/gi,
      'Slack is connected via MCP server — no token needed.',
    );
    return { ...m, content: cleaned };
  });
}

function clearHistory() {
  hideComingSoon();
  history = [];
  _saveActiveTabHistory();
  localStorage.removeItem('tab-disp-' + _activeTabId);
  localStorage.removeItem('tab-compact-' + _activeTabId);
  document.getElementById('messages').innerHTML = `
    <div class="message assistant">
      <div class="bubble">
        🐊 Hey! I'm <strong>@Gator</strong> — Welcome to your Integrated Work Environment (IWE).<br><br>
        I can dig into Confluence, Jira, email, calendar, Teams, and OneDrive — just ask, or pick a skill on the left.
      </div>
    </div>`;
}

/* ── Tab System ──────────────────────────────────────── */
const TABS_KEY = 'gator-tabs';
const ACTIVE_TAB_KEY = 'gator-active-tab';
const _WELCOME_HTML = `<div class="message assistant"><div class="bubble">🐊 New chat — what can I help you with? Pick a skill on the left or just ask.</div></div>`;

function _genTabId() {
  let id;
  do {
    id = Math.random().toString(36).slice(2, 10);
  } while (_tabs.some((t) => t.id === id));
  return id;
}

function _loadTabs() {
  try {
    return JSON.parse(localStorage.getItem(TABS_KEY) || '[]');
  } catch {
    return [];
  }
}
function _syncTabsToServer() {
  // Push tab list to server registry so server-side code can resolve
  // tab names ↔ context_ids (needed for get_tab_pins, scheduled bindings).
  try {
    fetch('/api/tabs/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tabs: _tabs.map((t) => ({ id: t.id, name: t.title })) }),
    }).catch(() => {});
  } catch {}
}
function _saveTabs() {
  localStorage.setItem(
    TABS_KEY,
    JSON.stringify(_tabs.map((t) => ({ id: t.id, title: t.title, createdAt: t.createdAt }))),
  );
  localStorage.setItem(ACTIVE_TAB_KEY, _activeTabId);
  _syncTabsToServer();
}
function _saveTabHistory(tabId, hist) {
  if (!tabId) return;
  const targetHistory = Array.isArray(hist) ? hist : [];
  try {
    localStorage.setItem('tab-hist-' + tabId, JSON.stringify(targetHistory.slice(-HISTORY_MAX)));
  } catch (e) {
    if (e.name === 'QuotaExceededError' || e.code === 22) {
      console.warn('localStorage full — tab history not saved for tab', tabId);
    }
  }
}
function _saveActiveTabHistory() {
  if (!_activeTabId) return;
  _saveTabHistory(_activeTabId, history);
  _saveTabChips(_activeTabId);
  const msgs = document.getElementById('messages');
  if (msgs) {
    localStorage.setItem('tab-scroll-' + _activeTabId, String(msgs.scrollTop));
  }
}
function _loadTabHistory(tabId) {
  try {
    return JSON.parse(localStorage.getItem('tab-hist-' + tabId) || '[]');
  } catch {
    return [];
  }
}

// Compaction seam markers — kept out of `history` (the LLM-facing transcript
// sent back to the server) so a synthetic marker role never reaches the API.
// Each entry is {afterIndex, turnCount, summaryText}: afterIndex is the index
// in `history` after which the marker should render.
function _saveTabCompactions(tabId, markers) {
  if (!tabId) return;
  try {
    localStorage.setItem('tab-compact-' + tabId, JSON.stringify((markers || []).slice(-50)));
  } catch (e) {
    if (e.name === 'QuotaExceededError' || e.code === 22) {
      console.warn('localStorage full — compaction markers not saved for tab', tabId);
    }
  }
}
function _loadTabCompactions(tabId) {
  try {
    return JSON.parse(localStorage.getItem('tab-compact-' + tabId) || '[]');
  } catch {
    return [];
  }
}

function _saveTabDisplayHtml(tabId, html, trimToCount) {
  if (!tabId) return;
  const key = 'tab-disp-' + tabId;
  let store;
  try {
    store = JSON.parse(localStorage.getItem(key) || '[]');
  } catch {
    store = [];
  }
  const safeHtml = html.replace(
    /<img[^>]*src="data:[^"]*"[^>]*>/gi,
    '<span class="img-restored-placeholder">[image]</span>',
  );
  store.push(safeHtml);
  if (typeof trimToCount === 'number' && store.length > trimToCount)
    store = store.slice(-trimToCount);
  try {
    localStorage.setItem(key, JSON.stringify(store));
  } catch (e) {
    if (e.name === 'QuotaExceededError' || e.code === 22) {
      console.warn('localStorage full — tab history not saved for tab', tabId);
    }
  }
}

function _loadTabDisplayHtml(tabId) {
  try {
    return JSON.parse(localStorage.getItem('tab-disp-' + tabId) || '[]');
  } catch {
    return [];
  }
}

function _saveTabChips(tabId) {
  if (!tabId) return;
  try {
    localStorage.setItem('tab-chips-' + tabId, JSON.stringify(_activeChips.map((c) => c.skillId)));
  } catch (e) {
    if (e.name === 'QuotaExceededError' || e.code === 22) {
      console.warn('localStorage full — tab chips not saved for tab', tabId);
    } else {
      throw e;
    }
  }
}
function _loadTabChips(tabId) {
  try {
    const v = JSON.parse(localStorage.getItem('tab-chips-' + tabId) || 'null');
    return Array.isArray(v) ? v : null;
  } catch {
    return null;
  }
}
function _restoreChipsForTab(tabId) {
  // Wipe current chip-row DOM + state
  const chipRow = document.getElementById('chat-chip-row');
  if (chipRow) {
    chipRow.querySelectorAll('.chat-chip').forEach((el) => el.remove());
  }
  _activeChips = [];
  // Restore from storage (default: just gator)
  const saved = _loadTabChips(tabId) || ['gator'];
  saved.forEach((sid) => {
    if (SKILL_MAP[sid]) _addSkillChip(sid);
  });
  if (!_activeChips.some((c) => c.skillId === 'gator')) _addSkillChip('gator');
  _activeSkillId = _activeChips.some((c) => c.skillId === 'gator')
    ? 'gator'
    : _activeChips[_activeChips.length - 1]?.skillId || null;
  _setRailActive?.(_activeSkillId);
  _updatePlaceholder?.();
}

let _tabs = [];
let _activeTabId = '';
const _inflightRequests = new Map();
const _chatTaskIds = new Map(); // tabId -> task_id for the active chat request
const _tabsWithUpdates = new Set(); // tabIds with completed responses the user hasn't seen
const _tabsWorking = new Set(); // tabIds with an in-flight request (animated working line)
let _revealActiveTabOnRender = false; // true = unconditionally scroll active tab into view on next render
let _preserveScrollOnRender = false; // true = closing a tab; keep scroll position, only nudge if needed
let _forcedScrollLeft = null; // when set, _renderTabBar restores exactly this scrollLeft (used on close)

// Toggle the faint animated "in progress" line on a tab. Tracked in a Set so the
// class survives tab-bar re-renders (see _renderTabBar).
function _setTabWorking(tabId, on) {
  if (!tabId) return;
  if (on) _tabsWorking.add(tabId);
  else _tabsWorking.delete(tabId);
  const el = document.querySelector(`.tab-item[data-tab-id="${tabId}"]`);
  if (el) el.classList.toggle('tab-working', on);
}

// User-scroll-override: true when the user has scrolled up during streaming.
// Auto-scroll is suppressed until the stream ends or a new send starts.
let _userScrolledUp = false;

function _initScrollOverride() {
  const msgs = document.getElementById('messages');
  if (!msgs) return;
  msgs.addEventListener(
    'scroll',
    () => {
      const distFromBottom = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight;
      const isStreaming = _chatTaskIds.has(_activeTabId);
      if (!isStreaming) return;
      // If user scrolled more than 80px from the bottom, treat as intentional override
      _userScrolledUp = distFromBottom > 80;
    },
    { passive: true },
  );

  // When the chat form grows (chip-row added, attachments, multi-line input),
  // it eats into the messages container's visible height. Re-pin to bottom
  // if the user was already at the bottom — prevents the last message from
  // being hidden behind the form.
  const form = document.getElementById('chat-form');
  if (form && 'ResizeObserver' in window) {
    let _lastFormHeight = form.offsetHeight;
    const ro = new ResizeObserver(() => {
      const h = form.offsetHeight;
      const grew = h > _lastFormHeight;
      _lastFormHeight = h;
      if (!grew) return;
      const distFromBottom = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight;
      if (distFromBottom <= 80) {
        msgs.scrollTop = msgs.scrollHeight;
      }
    });
    ro.observe(form);
  }
}

function _initTabSystem() {
  _tabs = _loadTabs();
  _activeTabId = localStorage.getItem(ACTIVE_TAB_KEY) || '';
  // Migrate: if no tabs but old history exists, create a tab for it
  if (!_tabs.length) {
    const oldHistory = loadHistory();
    const tab = { id: _genTabId(), title: 'New Chat', createdAt: Date.now() };
    _tabs.push(tab);
    _activeTabId = tab.id;
    if (oldHistory.length) {
      localStorage.setItem('tab-hist-' + tab.id, JSON.stringify(oldHistory));
      tab.title = _deriveTitle(oldHistory);
    }
  }
  if (!_activeTabId || !_tabs.find((t) => t.id === _activeTabId)) {
    _activeTabId = _tabs[0].id;
  }
  // Push current tab list to server on init (no-op if registry already current)
  _syncTabsToServer();
  // Load active tab's history
  history = _loadTabHistory(_activeTabId);
  _saveTabs();
  _renderTabBar();
  // Render conversation messages from restored history
  const msgs = document.getElementById('messages');
  if (history.length && msgs) {
    msgs.innerHTML = '';
    const _displayStore = _loadTabDisplayHtml(_activeTabId);
    const _compactMarkers = _loadTabCompactions(_activeTabId);
    let _userTurnIdx = 0;
    history.forEach((m, idx) => {
      const div = document.createElement('div');
      div.className = 'message ' + m.role;
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      if (m.role === 'assistant') {
        const prose = document.createElement('div');
        prose.className = 'prose';
        prose.innerHTML = renderMarkdown(m.content || '');
        bubble.appendChild(prose);
      } else if (m.role === 'user') {
        bubble.innerHTML =
          _displayStore[_userTurnIdx] ||
          escapeHtml(typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
        _userTurnIdx++;
      } else {
        bubble.innerHTML = escapeHtml(
          typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
        );
      }
      div.appendChild(bubble);
      msgs.appendChild(div);
      if (m.role === 'assistant' && m.content) {
        _addMsgActionBar(div, m.content);
      }
      _compactMarkers
        .filter((cm) => cm.afterIndex === idx)
        .forEach((cm) => {
          msgs.appendChild(_buildCompactionMarker(cm.turnCount, cm.summaryText));
        });
    });
    _refreshRetryVisibility();
    // Re-pin after layout settles — on refresh, images/fonts/markdown grow
    // scrollHeight after this first scroll, leaving the view slightly short.
    _pinScrollToBottom(msgs);
  }
  // Show onboarding if not dismissed and no history
  if (history.length === 0) _showChatOrOnboarding();
}

function _deriveTitle(hist) {
  const first = hist.find((m) => m.role === 'user');
  if (!first) return 'New Chat';
  const text = typeof first.content === 'string' ? first.content : '';
  return text.replace(/@\w+/g, '').trim().slice(0, 25) || 'New Chat';
}

function _showChatOrOnboarding() {
  const obContainer = document.getElementById('onboarding-container');
  const messages = document.getElementById('messages');
  // Messages always visible — no mutual exclusion
  if (history.length === 0) {
    messages.innerHTML = _WELCOME_HTML;
  }
  // Show onboarding panel alongside chat if not dismissed
  if (!isOnboardingDismissed() && history.length === 0) {
    renderOnboarding(obContainer);
    openOnboardingPanel();
  } else {
    closeOnboardingPanel();
  }
}

function createTab() {
  // Save current tab's state
  _saveActiveTabHistory();
  const tab = { id: _genTabId(), title: 'New Chat', createdAt: Date.now() };
  _tabs.push(tab);
  _activeTabId = tab.id;
  history = [];
  _saveTabs();
  _renderTabBar();
  // Scroll new tab fully into view (it lands at the right edge, past the + button)
  requestAnimationFrame(() => {
    const scroll = document.querySelector('.tab-scroll');
    const activeEl = scroll?.querySelector('.tab-item.active');
    if (scroll && activeEl) scroll.scrollLeft = scroll.scrollWidth;
  });
  _showChatOrOnboarding();
  _refreshPinOrb();
  if (typeof _switchPinContext === 'function') _switchPinContext();
  _remountCodeAgentTerminalForTab(_activeTabId);
}

// Creates or switches to a tab with a specific stable ID (used by scheduled-job "view this chat").
// If a tab with that id already exists, switches to it. Otherwise creates a fresh one with that id.
function createTabWithId(id, title) {
  _saveActiveTabHistory();
  let tab = _tabs.find((t) => t.id === id);
  if (!tab) {
    tab = { id, title: title || 'Agent Result', createdAt: Date.now() };
    _tabs.push(tab);
  }
  _activeTabId = id;
  history = _loadTabHistory(id) || [];
  _saveTabs();
  _renderTabBar();
  _showChatOrOnboarding();
  _refreshPinOrb();
  if (typeof _switchPinContext === 'function') _switchPinContext();
  _remountCodeAgentTerminalForTab(_activeTabId);
}

// Pin a scroll container to the bottom, re-applying as late layout grows the
// content (images, web-fonts, code blocks render after the first scroll, which
// otherwise leaves the view slightly above the true bottom on refresh).
function _pinScrollToBottom(el) {
  if (!el) return;
  // Capture the tab that requested this scroll — delayed callbacks must not
  // fire if the user has switched to a different tab by then.
  const ownerTab = _activeTabId;
  const toBottom = () => {
    if (_activeTabId !== ownerTab) return; // tab switched — don't touch other tab's scroll
    el.scrollTop = el.scrollHeight;
  };
  toBottom();
  requestAnimationFrame(toBottom);
  requestAnimationFrame(() => requestAnimationFrame(toBottom));
  // A couple of delayed passes catch images/fonts that finish slightly later.
  setTimeout(toBottom, 100);
  setTimeout(toBottom, 350);
  // Re-pin when any <img> inside finishes loading (covers cached-miss images).
  el.querySelectorAll('img').forEach((img) => {
    if (!img.complete) img.addEventListener('load', toBottom, { once: true });
  });
}

function switchTab(tabId) {
  if (tabId === _activeTabId) return;
  const _leavingTabId = _activeTabId;
  // Save draft from current tab before leaving
  const _draftInput = document.getElementById('chat-input');
  if (_draftInput) {
    const leaving = _activeTabId;
    const draftText = _draftInput.textContent || '';
    if (draftText.trim()) {
      localStorage.setItem('tab-draft-' + leaving, draftText);
    } else {
      localStorage.removeItem('tab-draft-' + leaving);
    }
  }
  // Save current (history + chips snapshot)
  _saveActiveTabHistory();
  // Swap
  _activeTabId = tabId;
  history = _loadTabHistory(tabId);
  _restoreChipsForTab(tabId);
  _saveTabs();
  // Preserve tab bar scroll position — switching tabs must NOT auto-scroll
  // the tab bar. Without this, _renderTabBar's rAF sees the active tab as
  // "out of view" (because innerHTML was wiped and rebuilt) and jumps.
  _preserveScrollOnRender = true;
  _renderTabBar();
  // Restore messages from history
  const msgs = document.getElementById('messages');
  const savedScroll = parseInt(localStorage.getItem('tab-scroll-' + tabId) || '-1');
  if (!history.length) {
    _showChatOrOnboarding();
  } else {
    // Close onboarding panel when switching to a tab with history
    closeOnboardingPanel();
    msgs.innerHTML = '';
    const _displayStore = _loadTabDisplayHtml(tabId);
    const _compactMarkers = _loadTabCompactions(tabId);
    let _userTurnIdx = 0;
    history.forEach((m, idx) => {
      const div = document.createElement('div');
      div.className = 'message ' + m.role;
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      if (m.role === 'assistant') {
        const prose = document.createElement('div');
        prose.className = 'prose';
        prose.innerHTML = renderMarkdown(m.content || '');
        bubble.appendChild(prose);
      } else if (m.role === 'user') {
        bubble.innerHTML =
          _displayStore[_userTurnIdx] ||
          escapeHtml(typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
        _userTurnIdx++;
      } else {
        bubble.innerHTML = escapeHtml(
          typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
        );
      }
      div.appendChild(bubble);
      msgs.appendChild(div);
      if (m.role === 'assistant' && m.content) {
        _addMsgActionBar(div, m.content);
      }
      _compactMarkers
        .filter((cm) => cm.afterIndex === idx)
        .forEach((cm) => {
          msgs.appendChild(_buildCompactionMarker(cm.turnCount, cm.summaryText));
        });
    });
    _refreshRetryVisibility();
    if (savedScroll >= 0) {
      const maxScroll = msgs.scrollHeight - msgs.clientHeight;
      msgs.scrollTop = Math.min(savedScroll, Math.max(0, maxScroll));
    } else {
      // No saved position → pin to bottom. Re-apply after layout settles:
      // images, fonts and markdown blocks grow scrollHeight AFTER the first
      // synchronous scroll, leaving the user slightly above the bottom.
      _pinScrollToBottom(msgs);
    }
  }
  const inflight = _inflightRequests.get(tabId);
  if (inflight?.msgDiv && msgs && !msgs.contains(inflight.msgDiv)) {
    inflight.msgDiv.classList.add('typing');
    msgs.appendChild(inflight.msgDiv);
    // Don't unconditionally scroll to bottom — respect the saved scroll position.
    // Use the same savedScroll read at the top of this block.
    const maxScrollInflight = msgs.scrollHeight - msgs.clientHeight;
    msgs.scrollTop =
      savedScroll >= 0 ? Math.min(savedScroll, Math.max(0, maxScrollInflight)) : msgs.scrollHeight;
  }

  // Sync send button state with the destination tab
  if (_chatTaskIds.has(tabId)) {
    // Destination tab has an active request — show stop mode
    sendBtn.disabled = false;
    sendBtn.classList.add('is-streaming');
    sendBtn.setAttribute('aria-label', 'Stop generating');
    sendBtn.type = 'button';
    setStatus('busy');
  } else {
    // Destination tab is idle — show send mode
    sendBtn.classList.remove('is-streaming');
    sendBtn.setAttribute('aria-label', 'Send message');
    sendBtn.type = 'submit';
    sendBtn.disabled = false;
    setStatus('idle');
  }

  // Clear any tab update indicator when switching to that tab
  _tabsWithUpdates.delete(tabId);
  const tabEl = document.querySelector(`.tab-item[data-tab-id="${tabId}"]`);
  if (tabEl) tabEl.classList.remove('tab-has-update');

  // Restore draft for the destination tab
  const _draftRestore = document.getElementById('chat-input');
  if (_draftRestore) {
    const saved = localStorage.getItem('tab-draft-' + tabId) || '';
    _draftRestore.textContent = saved;
    // Place cursor at end
    if (saved) {
      const range = document.createRange();
      const sel = window.getSelection();
      range.selectNodeContents(_draftRestore);
      range.collapse(false);
      sel.removeAllRanges();
      sel.addRange(range);
    }
  }

  // Clear any HITL poll from the previous tab; the new tab will set up its own if needed
  if (_hitlPollId) {
    clearInterval(_hitlPollId);
    _hitlPollId = null;
  }
  _refreshPinOrb();
  if (typeof _switchPinContext === 'function') _switchPinContext();
  // Sync OpenCode session toggle pill — it's a single global element (in
  // the chat input's guide row, not per-tab DOM), so it needs an explicit
  // check on every tab switch or it incorrectly keeps showing whichever
  // tab last set it.
  if (typeof _ocSyncSessionToggleOnTabSwitch === 'function') {
    _ocSyncSessionToggleOnTabSwitch(tabId);
  }
  // Same story for the session tab strip mounted in #tp-detail-header - also
  // a single global element, also needs an explicit resync per tab. Exactly
  // one of OpenCode's/the generic agent's strip can be relevant for the
  // active project; sync whichever one applies (both are no-ops if their
  // project's agent doesn't match, so calling both is safe even before the
  // active project is known).
  if (typeof _ocSyncHeaderTabStripOnTabSwitch === 'function') {
    _ocSyncHeaderTabStripOnTabSwitch(tabId);
  }
  if (typeof _genAgentSyncHeaderTabStripOnTabSwitch === 'function') {
    _genAgentSyncHeaderTabStripOnTabSwitch(tabId);
  }
  // And the terminal container itself lives in the single shared #tp-detail-col
  // - swap in whichever chat tab's terminal belongs here now.
  _remountCodeAgentTerminalForTab(tabId);
}

// Re-point the shared coding-agent terminal column (#tp-detail-col) at a given
// chat tab. Must run on EVERY way the active chat tab changes while the Code
// pane is open - not just switchTab, but also createTab / createTabWithId,
// which set _activeTabId directly and previously skipped this entirely (real
// bug found via user report: opening/creating a new chat tab with the coding
// agent pane open left the PREVIOUS tab's terminal mounted, or a blank column
// for a tab that never had a session, instead of that tab's own terminal /
// Start prompt).
//
// No-op unless the Code tab is the active third-pane skill (the mount helpers
// guard on tpState.type === 'code_agent'). Routes through the same agent-aware
// dispatcher third-pane.js's pane-reopen path uses: _caMountAgentTab knows
// about OpenCode AND the generic BYO-config agents (Claude/Codex/Crush/
// Terminal), so a project set to any of those mounts that tab's OWN terminal
// rather than leaving another tab's session visible under the new tab.
function _remountCodeAgentTerminalForTab(tabId) {
  const _stProj =
    typeof _caActiveProject !== 'undefined' &&
    _caActiveProject &&
    typeof _caProjects !== 'undefined'
      ? _caProjects.find((p) => p.name === _caActiveProject)
      : null;
  if (_stProj && typeof _caMountAgentTab === 'function') {
    _caMountAgentTab(tabId, _stProj);
    // Mounting only re-attaches an ALREADY-LIVE terminal for this tab (if one
    // exists in memory). A tab that has never had the Code pane opened before
    // has no live state to re-attach, so mounting alone left #tp-detail-col
    // completely empty - not even the Start/Resume prompt - making the pane
    // look "open but blank". Route through the same guided-start dispatcher
    // _initCodeAgentPane's own render path uses; it's a no-op (returns
    // immediately) whenever a terminal is already mounted, so this is safe to
    // call on every switch.
    if (_stProj.repo_path && typeof _caShowAgentStartOrTerminal === 'function') {
      _caShowAgentStartOrTerminal(tabId, _stProj, _stProj.repo_path);
    }
  } else if (typeof _ocMountActiveTab === 'function') {
    _ocMountActiveTab(tabId); // no project resolved yet - OpenCode's own no-op guard covers it
  }
}

function closeTab(tabId) {
  const tab = _tabs.find((t) => t.id === tabId);
  if (!tab) return;
  const tabHist = _loadTabHistory(tabId);
  const doClose = () => {
    const inflight = _inflightRequests.get(tabId);
    if (inflight?.abortCtrl) {
      try {
        inflight.abortCtrl.abort();
      } catch {}
    }
    const chatTaskId = _chatTaskIds.get(tabId);
    if (chatTaskId) {
      fetch(`/api/chat/${chatTaskId}/cancel`, { method: 'POST' }).catch((err) =>
        console.warn('Tab cleanup fetch failed:', err),
      );
      _chatTaskIds.delete(tabId);
    }
    _inflightRequests.delete(tabId);
    // Clear pin context and stored state
    fetch(`/api/context/pins?context_id=${tabId}`, { method: 'DELETE' }).catch((err) =>
      console.warn('Tab cleanup fetch failed:', err),
    );
    fetch(`/api/conversation/${tabId}`, { method: 'DELETE' }).catch((err) =>
      console.warn('Tab cleanup fetch failed:', err),
    );
    localStorage.removeItem('tab-hist-' + tabId);
    localStorage.removeItem('tab-disp-' + tabId);
    localStorage.removeItem('tab-compact-' + tabId);
    localStorage.removeItem('tab-scroll-' + tabId);
    localStorage.removeItem('tab-draft-' + tabId);
    localStorage.removeItem('tab-chips-' + tabId);

    // Capture scroll position before ANY DOM rebuild so we can restore it
    // exactly. _forcedScrollLeft is consumed inside _renderTabBar's rAF callback
    // so it survives multiple intermediate renders triggered by switchTab.
    const _scrollEl = document.querySelector('.tab-scroll');
    _forcedScrollLeft = _scrollEl ? _scrollEl.scrollLeft : 0;

    const closedIdx = _tabs.findIndex((t) => t.id === tabId);
    _tabs = _tabs.filter((t) => t.id !== tabId);
    if (!_tabs.length) {
      _forcedScrollLeft = null;
      createTab();
      return;
    }
    if (_activeTabId === tabId) {
      // Prefer left neighbour; fall back to right when closing the first tab
      const nextIdx = Math.min(closedIdx, _tabs.length - 1);
      const nextId = _tabs[nextIdx].id;
      // Clear _activeTabId so switchTab won't early-return.
      // _forcedScrollLeft is already set; every _renderTabBar called by
      // switchTab will honour it and the final explicit call below wins.
      _activeTabId = '';
      switchTab(nextId);
    }
    _saveTabs();
    _renderTabBar();
    _refreshPinOrb();
  };
  if (tabHist.length > 0) {
    _showConfirmModal(
      'Close tab',
      `Close "${tab.title}"? Chat history will be lost.`,
      'Close',
      doClose,
    );
  } else {
    doClose();
  }
}

function resetTab(tabId) {
  const tab = _tabs.find((t) => t.id === tabId);
  if (!tab) return;
  const doClone = async () => {
    _saveActiveTabHistory();

    // Create a new tab next to the original and clone pins into it
    const newTab = { id: _genTabId(), title: tab.title, createdAt: Date.now() };
    await fetch('/api/context/pins/clone', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from_context_id: tabId, to_context_id: newTab.id }),
    }).catch(() => {});

    // Insert new tab right after the original
    const idx = _tabs.findIndex((t) => t.id === tabId);
    _tabs.splice(idx + 1, 0, newTab);
    _activeTabId = newTab.id;
    history = [];
    _saveTabs();
    _renderTabBar();
    _showChatOrOnboarding();
    _refreshPinOrb();
  };
  doClone();
}

// Compute the scrollLeft needed to bring a tab fully into view, working purely
// in the scroll container's own coordinate space. elRect/scrollRect are
// getBoundingClientRect()-style {left, width} objects, so this is correct
// regardless of which ancestor is the offsetParent (#81: .topbar is fixed, so
// offsetLeft was topbar-relative and mixed coordinate systems).
function _tabScrollTargetLeft(scrollRect, scrollLeft, clientWidth, elRect, pad) {
  const elLeft = elRect.left - scrollRect.left + scrollLeft;
  const elRight = elLeft + elRect.width;
  if (elRight > scrollLeft + clientWidth) {
    return elRight - clientWidth + pad;
  }
  if (elLeft < scrollLeft) {
    return Math.max(0, elLeft - pad);
  }
  return scrollLeft;
}

function _renderTabBar() {
  const bar = document.getElementById('topbar-tabs') || document.getElementById('tab-bar');
  if (!bar) return;
  // Preserve tab bar horizontal scroll position across re-renders
  const prevScroll = bar.querySelector('.tab-scroll');
  const savedScrollLeft = prevScroll ? prevScroll.scrollLeft : 0;
  bar.innerHTML = '';

  // Left scroll arrow — lives INSIDE .tab-scroll (sticky-pinned to the left
  // edge) so it doesn't sit between the drag spacer and the scroll area as a
  // no-drag strip. When it was a flex sibling before .tab-scroll, appearing on
  // scroll-right broke the continuous drag zone (drag worked scroll-left when
  // it was hidden, failed scroll-right when visible). Inside the scroll
  // container with position:sticky, the spacer connects directly to .tab-scroll
  // (both drag) and the arrow is a clickable no-drag island pinned to the edge.
  const arrowL = document.createElement('button');
  arrowL.className = 'tab-scroll-arrow tab-scroll-arrow-left';
  arrowL.textContent = '‹';
  arrowL.title = 'Scroll left';

  // Right scroll arrow — same treatment, pinned to the right edge of .tab-scroll.
  const arrowR = document.createElement('button');
  arrowR.className = 'tab-scroll-arrow tab-scroll-arrow-right';
  arrowR.textContent = '›';
  arrowR.title = 'Scroll right';

  // Scrollable tab container
  const scroll = document.createElement('div');
  scroll.className = 'tab-scroll';
  scroll.appendChild(arrowL);

  let _tabDragSrcId = null;
  _tabs.forEach((tab) => {
    const el = document.createElement('div');
    el.className =
      'tab-item' +
      (tab.id === _activeTabId ? ' active' : '') +
      (_tabsWorking.has(tab.id) ? ' tab-working' : '') +
      (_tabsWithUpdates.has(tab.id) ? ' tab-has-update' : '');
    el.draggable = true;
    el.dataset.tabId = tab.id;
    // Build tab inner content safely (title is already escaped by escapeHtml)
    const titleSpan = document.createElement('span');
    titleSpan.className = 'tab-item-title';
    titleSpan.textContent = tab.title;
    const closeBtn = document.createElement('button');
    closeBtn.className = 'tab-item-close';
    closeBtn.title = 'Close tab';
    closeBtn.textContent = '\u00D7';
    el.appendChild(titleSpan);
    el.appendChild(closeBtn);
    el.addEventListener('click', (e) => {
      if (e.target.closest('.tab-item-close')) return;
      switchTab(tab.id);
    });
    el.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      _showTabCtxMenu(e.clientX, e.clientY, tab.id);
    });
    el.querySelector('.tab-item-close').addEventListener('click', (e) => {
      e.stopPropagation();
      closeTab(tab.id);
    });
    // Double-click to rename (also available via the right-click menu)
    el.querySelector('.tab-item-title').addEventListener('dblclick', () => _beginTabRename(tab.id));
    // ── Tab drag-reorder ──
    el.addEventListener('dragstart', (e) => {
      _tabDragSrcId = tab.id;
      el.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', tab.id);
    });
    el.addEventListener('dragend', () => {
      _tabDragSrcId = null;
      scroll
        .querySelectorAll('.tab-item')
        .forEach((t) => t.classList.remove('dragging', 'drag-over-left', 'drag-over-right'));
    });
    el.addEventListener('dragover', (e) => {
      if (!_tabDragSrcId || _tabDragSrcId === tab.id) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const rect = el.getBoundingClientRect();
      const midX = rect.left + rect.width / 2;
      el.classList.toggle('drag-over-left', e.clientX < midX);
      el.classList.toggle('drag-over-right', e.clientX >= midX);
    });
    el.addEventListener('dragleave', () => {
      el.classList.remove('drag-over-left', 'drag-over-right');
    });
    el.addEventListener('drop', (e) => {
      e.preventDefault();
      if (!_tabDragSrcId || _tabDragSrcId === tab.id) return;
      const srcIdx = _tabs.findIndex((t) => t.id === _tabDragSrcId);
      const dstIdx = _tabs.findIndex((t) => t.id === tab.id);
      if (srcIdx < 0 || dstIdx < 0) return;
      const rect = el.getBoundingClientRect();
      const midX = rect.left + rect.width / 2;
      const insertBefore = e.clientX < midX;
      const [moved] = _tabs.splice(srcIdx, 1);
      const newIdx = _tabs.findIndex((t) => t.id === tab.id);
      _tabs.splice(insertBefore ? newIdx : newIdx + 1, 0, moved);
      _saveTabs();
      _renderTabBar();
    });
    scroll.appendChild(el);
  });

  scroll.appendChild(arrowR);
  bar.appendChild(scroll);

  // "+" button — outside scroll so it's always visible when tabs overflow
  const addBtn = document.createElement('button');
  addBtn.className = 'tab-add';
  addBtn.textContent = '+';
  addBtn.title = 'New tab';
  addBtn.addEventListener('click', createTab);
  bar.appendChild(addBtn);

  // ── All-tabs dropdown button (replaces right arrow) ──────────────────────
  const overflowBtn = document.createElement('button');
  overflowBtn.className = 'tab-overflow-btn';
  overflowBtn.title = 'All tabs';
  // chevron-down SVG
  const chevSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  chevSvg.setAttribute('width', '12');
  chevSvg.setAttribute('height', '12');
  chevSvg.setAttribute('viewBox', '0 0 24 24');
  chevSvg.setAttribute('fill', 'none');
  chevSvg.setAttribute('stroke', 'currentColor');
  chevSvg.setAttribute('stroke-width', '2.5');
  const chevPath = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  chevPath.setAttribute('points', '6 9 12 15 18 9');
  chevSvg.appendChild(chevPath);
  overflowBtn.appendChild(chevSvg);
  overflowBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelector('.tab-overflow-menu')?.remove();
    const menu = document.createElement('div');
    menu.className = 'tab-overflow-menu';
    _tabs.forEach((t) => {
      const item = document.createElement('div');
      item.className = 'tab-overflow-item' + (t.id === _activeTabId ? ' active' : '');
      if (t.id === _activeTabId) {
        const dot = document.createElement('span');
        dot.className = 'tab-overflow-dot';
        item.appendChild(dot);
      }
      const title = document.createElement('span');
      title.className = 'tab-overflow-title';
      title.textContent = t.title;
      item.appendChild(title);
      const closeBtn = document.createElement('button');
      closeBtn.className = 'tab-overflow-close';
      closeBtn.textContent = '×';
      closeBtn.title = 'Close tab';
      closeBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        menu.remove();
        closeTab(t.id);
      });
      item.appendChild(closeBtn);
      item.addEventListener('click', () => {
        menu.remove();
        switchTab(t.id);
      });
      menu.appendChild(item);
    });
    document.body.appendChild(menu);
    const rect = overflowBtn.getBoundingClientRect();
    menu.style.top = rect.bottom + 6 + 'px';
    menu.style.right = window.innerWidth - rect.right + 'px';
    const dismiss = (ev) => {
      if (!menu.contains(ev.target)) {
        menu.remove();
        document.removeEventListener('mousedown', dismiss);
      }
    };
    document.addEventListener('mousedown', dismiss);
  });
  bar.appendChild(overflowBtn);

  // ── Expand / fullscreen button (moved to topbar-right) ────────────────
  const expandBtn = document.createElement('button');
  expandBtn.className = 'tab-expand-btn';
  expandBtn.title = document.body.classList.contains('tab-fullscreen')
    ? 'Exit fullscreen'
    : 'Fullscreen';
  const _expandIcon = (full) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '13');
    svg.setAttribute('height', '13');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute(
      'd',
      full
        ? 'M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 0 2-2h3M3 16h3a2 2 0 0 0 2 2v3'
        : 'M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3',
    );
    svg.appendChild(path);
    return svg;
  };
  expandBtn.appendChild(_expandIcon(document.body.classList.contains('tab-fullscreen')));
  expandBtn.addEventListener('click', () => {
    const full = document.body.classList.toggle('tab-fullscreen');
    expandBtn.title = full ? 'Exit fullscreen' : 'Fullscreen';
    expandBtn.innerHTML = '';
    expandBtn.appendChild(_expandIcon(full));
    if (full && document.documentElement.requestFullscreen) {
      document.documentElement.requestFullscreen().catch(() => {});
    } else if (!full && document.exitFullscreen && document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    }
  });
  document.addEventListener(
    'fullscreenchange',
    () => {
      const full = !!document.fullscreenElement;
      document.body.classList.toggle('tab-fullscreen', full);
      expandBtn.title = full ? 'Exit fullscreen' : 'Fullscreen';
      expandBtn.innerHTML = '';
      expandBtn.appendChild(_expandIcon(full));
    },
    { once: false },
  );
  const _topbarRight = document.querySelector('.topbar-right');
  if (_topbarRight) {
    _topbarRight.querySelector('.tab-expand-btn')?.remove();
    _topbarRight.insertBefore(expandBtn, _topbarRight.firstChild);
  }

  // ── Scroll / overflow visibility ─────────────────────────────────────────
  const updateArrows = () => {
    const canLeft = scroll.scrollLeft > 1;
    const canRight = scroll.scrollLeft < scroll.scrollWidth - scroll.clientWidth - 1;
    const canOverflow = scroll.scrollWidth > scroll.clientWidth + 1;
    arrowL.classList.toggle('visible', canLeft);
    arrowR.classList.toggle('visible', canRight);
    overflowBtn.classList.toggle('visible', canOverflow);
  };
  arrowL.addEventListener('click', () => {
    scroll.scrollLeft -= 120;
  });
  arrowR.addEventListener('click', () => {
    scroll.scrollLeft += 120;
  });
  scroll.addEventListener('scroll', updateArrows);
  // Restore previous scroll position.
  // Only scroll to reveal the active tab when it is genuinely out of view —
  // avoids jarring jumps when the user deletes a tab or re-renders for other reasons.
  // Restore previous scroll position synchronously so the rAF visibility
  // check works against the correct baseline (not 0).
  scroll.scrollLeft = savedScrollLeft;
  requestAnimationFrame(() => {
    const activeEl = scroll.querySelector('.tab-item.active');
    if (activeEl) {
      const scrollRect = scroll.getBoundingClientRect();
      const elRect = activeEl.getBoundingClientRect();
      // Visibility uses the tab-scroll's ACTUAL viewport (no padding) — a tab
      // already fully on-screen must never trigger an auto-scroll. The 48px
      // pad below is cosmetic breathing room for landing when a scroll is
      // genuinely needed, not a threshold for deciding whether one is needed.
      const activeTabOutOfView =
        elRect.left < scrollRect.left - 1 || elRect.right > scrollRect.right + 1;
      const rightPad = 48;
      const target = _tabScrollTargetLeft(
        scrollRect,
        scroll.scrollLeft,
        scroll.clientWidth - rightPad,
        elRect,
        8,
      );
      if (_forcedScrollLeft !== null) {
        // Closing a tab: restore the exact pre-close scroll position.
        // This flag survives intermediate renders (e.g. switchTab's internal
        // _renderTabBar) so the final visible render always lands here first.
        scroll.scrollLeft = _forcedScrollLeft;
        _forcedScrollLeft = null;
        _preserveScrollOnRender = false; // clear legacy flag too
      } else if (_preserveScrollOnRender) {
        // Legacy preserve path (fallback for any other callers).
        scroll.scrollLeft = savedScrollLeft;
        _preserveScrollOnRender = false;
      } else if (activeTabOutOfView || _revealActiveTabOnRender) {
        scroll.scrollLeft = target;
      }
      _revealActiveTabOnRender = false;
    }
    updateArrows();
  });
  if (!bar._resizeObserver) {
    bar._resizeObserver = new ResizeObserver(updateArrows);
    bar._resizeObserver.observe(scroll);
  }
}

/* ── Tab rename (inline edit) ─────────────────────────── */
// Swap a tab's title span for an inline text input. Shared by the double-click
// gesture and the right-click "Rename" menu item so both behave identically.
function _beginTabRename(tabId) {
  const tab = _tabs.find((t) => t.id === tabId);
  const el = document.querySelector(`.tab-item[data-tab-id="${tabId}"]`);
  if (!tab || !el) return;
  const titleEl = el.querySelector('.tab-item-title');
  if (!titleEl) return;
  const inp = document.createElement('input');
  inp.className = 'tab-rename-input';
  inp.value = tab.title;
  inp.style.cssText =
    'width:100px;font-size:.78rem;background:var(--surface2);border:1px solid var(--accent);border-radius:3px;color:var(--text);padding:0 .2rem;outline:none;';
  titleEl.replaceWith(inp);
  inp.focus();
  inp.select();
  const finish = () => {
    tab.title = inp.value.trim() || 'New Chat';
    _saveTabs();
    _renderTabBar();
  };
  inp.addEventListener('blur', finish);
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') finish();
    if (e.key === 'Escape') {
      _renderTabBar();
    }
  });
}

/* ── Tab context menu ────────────────────────────────── */
function _showTabCtxMenu(x, y, tabId) {
  // Remove any existing
  document.querySelector('.tab-ctx-menu')?.remove();
  const menu = document.createElement('div');
  menu.className = 'tab-ctx-menu';
  menu.setAttribute('role', 'menu');

  const items = [
    { label: 'Rename', action: () => _beginTabRename(tabId) },
    { label: 'Clone tab', action: () => resetTab(tabId) },
    { label: 'Close tab', action: () => closeTab(tabId) },
    { label: 'Close other tabs', action: () => _closeOtherTabs(tabId) },
    { label: 'Close all tabs', action: () => _closeAllTabs(), cls: 'danger' },
  ];

  items.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'tab-ctx-item' + (item.cls ? ' ' + item.cls : '');
    row.setAttribute('role', 'menuitem');
    row.textContent = item.label;
    row.addEventListener('click', () => {
      menu.remove();
      item.action();
    });
    menu.appendChild(row);
  });

  // Position near cursor, keep on screen
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  document.body.appendChild(menu);
  const rect = menu.getBoundingClientRect();
  if (rect.right > window.innerWidth) menu.style.left = window.innerWidth - rect.width - 8 + 'px';
  if (rect.bottom > window.innerHeight)
    menu.style.top = window.innerHeight - rect.height - 8 + 'px';

  // Close on click outside or Escape
  const dismiss = (e) => {
    if (!menu.contains(e.target)) {
      menu.remove();
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', escDismiss);
    }
  };
  const escDismiss = (e) => {
    if (e.key === 'Escape') {
      menu.remove();
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', escDismiss);
    }
  };
  setTimeout(() => {
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', escDismiss);
  }, 0);
}

function _closeOtherTabs(keepTabId) {
  const toClose = _tabs.filter((t) => t.id !== keepTabId);
  toClose.forEach((t) => {
    fetch(`/api/context/pins?context_id=${t.id}`, { method: 'DELETE' }).catch(() => {});
    localStorage.removeItem('tab-hist-' + t.id);
    localStorage.removeItem('tab-disp-' + t.id);
    localStorage.removeItem('tab-compact-' + t.id);
  });
  _tabs = _tabs.filter((t) => t.id === keepTabId);
  if (_activeTabId !== keepTabId) {
    _activeTabId = keepTabId;
    switchTab(keepTabId);
  }
  _saveTabs();
  _renderTabBar();
  _refreshPinOrb();
}

function _closeAllTabs() {
  _tabs.forEach((t) => {
    fetch(`/api/context/pins?context_id=${t.id}`, { method: 'DELETE' }).catch(() => {});
    localStorage.removeItem('tab-hist-' + t.id);
    localStorage.removeItem('tab-disp-' + t.id);
    localStorage.removeItem('tab-compact-' + t.id);
  });
  _tabs = [];
  createTab();
}

function _autoTitleTab(tabId, hist = []) {
  if (!tabId) return;
  const tab = _tabs.find((t) => t.id === tabId);
  if (tab && tab.title === 'New Chat' && hist.length) {
    tab.title = _deriveTitle(hist);
    _saveTabs();
    _renderTabBar();
  }
}
function _autoTitleActiveTab() {
  _autoTitleTab(_activeTabId, history);
}

/* ── Pin Orb ─────────────────────────────────────────── */
let _cachedPins = []; // cached for instant popover display
let _cachedPinsContextId = null;
let _pinOrbRefreshSeq = 0;
let _pinOrbInflight = null;
let _pinOrbInflightCtx = null;
let _pinOrbQueued = false;

async function _refreshPinOrb(force = false) {
  const contextId = _activeTabId || 'default';
  if (_pinOrbInflight && _pinOrbInflightCtx === contextId && !force) {
    _pinOrbQueued = true;
    return _pinOrbInflight;
  }
  const refreshSeq = ++_pinOrbRefreshSeq;
  const orb = document.getElementById('pin-orb');
  const badge = document.getElementById('pin-orb-badge');

  if (
    _cachedPinsContextId === contextId &&
    Array.isArray(_cachedPins) &&
    typeof _refreshPinnedItemsCache === 'function'
  ) {
    _refreshPinnedItemsCache(_cachedPins);
  }

  const run = async () => {
    let pins = [];
    try {
      pins = await fetch(`/api/context/pins?context_id=${contextId}`).then((r) =>
        r.ok ? r.json() : [],
      );
    } catch {
      pins = [];
    }

    if (refreshSeq !== _pinOrbRefreshSeq) return pins;

    if (typeof _refreshPinnedItemsCache === 'function') await _refreshPinnedItemsCache(pins);

    _cachedPins = Array.isArray(pins) ? pins : [];
    _cachedPinsContextId = contextId;

    if (!orb || !badge) return pins;

    const count = Array.isArray(_cachedPins) ? pins.length : 0;
    badge.textContent = count;
    badge.classList.toggle('hidden', count === 0);
    orb.classList.toggle('has-pins', count > 0);
    if (count === 0) {
      orb.classList.remove('has-pins');
    }
    return pins;
  };

  // Optimistically reset UI while fetch is in flight
  if (orb && badge && (force || _cachedPinsContextId !== contextId)) {
    badge.textContent = '0';
    badge.classList.add('hidden');
    orb.classList.remove('has-pins');
  }

  const myCtx = contextId;
  _pinOrbInflightCtx = contextId;
  _pinOrbInflight = run().finally(() => {
    // Only clear inflight refs if they still belong to this fetch (not overwritten by a newer context)
    if (_pinOrbInflightCtx === myCtx) {
      _pinOrbInflight = null;
      _pinOrbInflightCtx = null;
    }
    if (_pinOrbQueued) {
      _pinOrbQueued = false;
      _refreshPinOrb(true);
    }
  });
  return _pinOrbInflight;
}

function _togglePinPopover() {
  const existing = document.querySelector('.pin-popover-backdrop');
  if (existing) {
    // Use the cleanup function if available (removes onEsc listener), else fall back to DOM remove
    const popover = document.querySelector('.pin-popover');
    if (popover?._pinCleanup) {
      popover._pinCleanup();
    } else {
      existing.remove();
      popover?.remove();
    }
    return;
  }
  _showPinPopover();
}

async function _showPinPopover() {
  const main = document.querySelector('.main');
  if (!main) return;
  const backdrop = document.createElement('div');
  backdrop.className = 'pin-popover-backdrop';
  const popover = document.createElement('div');
  popover.className = 'pin-popover';
  popover.innerHTML = `<div class="pin-popover-header"><span class="pin-popover-title">\uD83D\uDC0A Gator's Context</span><span class="pin-popover-count"></span><button class="pin-popover-close">&times;</button></div><div class="pin-popover-hint"><span class="guide-key">Shift+{</span> in the prompt to reference a pinned item</div><div class="pin-popover-list"></div>`;
  document.body.appendChild(backdrop);
  main.appendChild(popover);
  const onEsc = (e) => {
    if (e.key === 'Escape') cleanup();
  };
  const cleanup = () => {
    document.removeEventListener('keydown', onEsc);
    if (backdrop.isConnected) backdrop.remove();
    if (popover.isConnected) popover.remove();
  };
  popover._pinCleanup = cleanup;
  backdrop.addEventListener('click', cleanup);
  popover.querySelector('.pin-popover-close').addEventListener('click', cleanup);
  document.addEventListener('keydown', onEsc);

  const contextId = _activeTabId || 'default';
  let pins;
  if (_cachedPinsContextId === contextId && Array.isArray(_cachedPins)) {
    pins = _cachedPins;
  } else {
    // Use the deduped orb refresh to populate cache, then read from it
    await _refreshPinOrb();
    pins = _cachedPinsContextId === contextId && Array.isArray(_cachedPins) ? _cachedPins : [];
  }
  const list = popover.querySelector('.pin-popover-list');
  const countEl = popover.querySelector('.pin-popover-count');
  if (countEl)
    countEl.textContent = pins.length ? `${pins.length} item${pins.length !== 1 ? 's' : ''}` : '';

  if (!pins.length) {
    list.innerHTML =
      '<div class="pin-popover-empty"><div style="font-size:1.4rem;margin-bottom:.4rem">\uD83D\uDC0A</div>No items pinned yet<br><span style="opacity:.6;font-size:.72rem">Right-click any email, chat, or file to pin it.<br>Pinned items give Gator context for this tab.</span></div>';
    return;
  }

  try {
    const _pinIcon = (id) =>
      `<img src="/static/icons/${id}.svg" class="skill-icon-img" alt="${id}" style="width:20px;height:20px;">`;
    const _sourceConfig = {
      email: { icon: _pinIcon('outlook'), label: 'Email' },
      teams: { icon: _pinIcon('teams'), label: 'Teams' },
      onedrive: { icon: _pinIcon('onedrive'), label: 'OneDrive' },
      onenote: {
        icon: '<img src="/static/icons/onenote.png" class="skill-icon-img" alt="onenote" style="width:20px;height:20px;">',
        label: 'OneNote',
      },
      confluence: { icon: _pinIcon('confluence'), label: 'Confluence' },
      jira: { icon: _pinIcon('jira'), label: 'Jira' },
      slack: { icon: _pinIcon('slack'), label: 'Slack' },
      calendar: { icon: _pinIcon('calendar'), label: 'Calendar' },
      github: { icon: _pinIcon('github'), label: 'GitHub' },
    };

    pins.forEach((p) => {
      const cfg = _sourceConfig[p.source] || { icon: '\uD83D\uDCCC', label: p.source };
      const meta =
        p.source === 'onedrive'
          ? p.meta?.file_path || ''
          : p.source === 'onenote'
            ? `${p.meta?.notebook || ''} \u203A ${p.meta?.section || ''}`
            : p.source === 'email'
              ? p.meta?.from || ''
              : p.source === 'teams'
                ? p.meta?.type || 'chat'
                : p.source === 'calendar'
                  ? _calendarPinMeta(p.meta)
                  : '';
      const card = document.createElement('div');
      card.className = 'pin-card';
      card.innerHTML = `
      <div class="pin-card-icon">${cfg.icon}</div>
      <div class="pin-card-body">
        <div class="pin-card-label" title="${escapeHtml(p.label)}">${escapeHtml(p.label)}</div>
        <div class="pin-card-meta" title="${escapeHtml(cfg.label)}${meta ? ' \u00B7 ' + escapeHtml(meta) : ''}">${escapeHtml(cfg.label)}${meta ? ' \u00B7 ' + escapeHtml(meta) : ''}</div>
      </div>
      <div class="pin-card-actions">
        <button class="pin-card-btn pin-card-open" title="Open">&#8599;</button>
        <button class="pin-card-btn pin-card-ask" title="Insert into chat">\u2726</button>
        <button class="pin-card-btn pin-card-remove" title="Unpin">&times;</button>
      </div>`;
      // ↗ Open item in its native pane (or browser for external sources)
      card.querySelector('.pin-card-open').addEventListener('click', () => {
        cleanup();
        const webUrl = p.meta?.web_url || p.meta?.url;
        const _inShell = typeof window.gatorShell !== 'undefined' && window.gatorShell.isShell;
        if (p.source === 'email') {
          // Shell + native Outlook: switch to the OWA pane and deep-link to the
          // pinned conversation (OWA uses real URL routing). Classic: load the
          // email detail in the third pane.
          if (
            _inShell &&
            window.gatorShell.navigateOutlookPin &&
            typeof _outlookNativeEnabled === 'function' &&
            _outlookNativeEnabled()
          ) {
            if (typeof openThirdPane === 'function') openThirdPane('email');
            window.gatorShell.navigateOutlookPin(p.id);
          } else {
            if (typeof openThirdPane === 'function') openThirdPane('email');
            if (typeof tpLoadDetail === 'function') tpLoadDetail(p.id);
          }
        } else if (p.source === 'slack') {
          // Shell mode: switch to the native Slack pane and deep-link to the
          // pinned channel/thread. The shell derives the workspace id from the
          // Slack view's own URL (pins don't store it), so we just pass the id.
          if (_inShell) {
            if (typeof openThirdPane === 'function') openThirdPane('slack');
            if (window.gatorShell.navigateSlackPin) window.gatorShell.navigateSlackPin(p.id);
          } else if (webUrl) {
            window.open(webUrl, '_blank', 'noopener');
          } else if (typeof openThirdPane === 'function') {
            openThirdPane('slack');
          }
        } else if (p.source === 'teams') {
          // Shell mode: switch to the native Teams pane and deep-link to the
          // pinned conversation via /l/message/<threadId>. Classic mode: load
          // the conversation detail in the third pane as before.
          if (_inShell) {
            if (typeof openThirdPane === 'function') openThirdPane('teams');
            if (window.gatorShell.navigateTeamsPin) window.gatorShell.navigateTeamsPin(p.id);
          } else {
            if (typeof openThirdPane === 'function') openThirdPane('teams');
            if (typeof tpLoadDetail === 'function') tpLoadDetail(p.id);
          }
        } else if (p.source === 'onenote') {
          // Shell + native OneNote: switch to the OneNote pane and deep-link to
          // the pinned page via its oneNoteWebUrl (OneNote for the web uses real
          // URL routing). The pin doesn't store the web URL, so resolve it from
          // Graph via /api/onenote/pages/<id> first. Classic / browser: open the
          // classic OneNote pane and load the page detail there.
          if (
            _inShell &&
            window.gatorShell.navigateOneNotePin &&
            typeof _onenoteNativeEnabled === 'function' &&
            _onenoteNativeEnabled()
          ) {
            if (typeof openThirdPane === 'function') openThirdPane('onenote');
            const navUrl = p.meta?.web_url || p.meta?.url;
            if (navUrl) {
              window.gatorShell.navigateOneNotePin(navUrl);
            } else {
              fetch(`/api/onenote/pages/${encodeURIComponent(p.id)}`)
                .then((r) => (r.ok ? r.json() : null))
                .then((data) => {
                  if (data && data.url) window.gatorShell.navigateOneNotePin(data.url);
                  else window.gatorShell.navigateOneNotePin('');
                })
                .catch(() => window.gatorShell.navigateOneNotePin(''));
            }
          } else {
            if (typeof openThirdPane === 'function') openThirdPane('onenote');
            // Delay until list renders (async fetch), then highlight
            setTimeout(() => {
              if (typeof tpLoadDetail === 'function') tpLoadDetail(p.id);
            }, 600);
          }
        } else if (p.source === 'jira') {
          // Shell + native Jira: switch to the Jira pane and deep-link to the issue.
          if (
            _inShell &&
            window.gatorShell.navigateJiraPin &&
            typeof _jiraNativeEnabled === 'function' &&
            _jiraNativeEnabled()
          ) {
            if (typeof openThirdPane === 'function') openThirdPane('jira');
            window.gatorShell.navigateJiraPin(webUrl || p.meta?.web_url || '');
          } else {
            if (typeof openThirdPane === 'function') openThirdPane('jira');
            setTimeout(() => {
              if (typeof tpLoadDetail === 'function') tpLoadDetail(p.id);
              const detailCol = document.getElementById('tp-detail-col');
              if (detailCol && typeof _renderJiraIssueDetail === 'function')
                _renderJiraIssueDetail(detailCol, p.id, webUrl || '');
            }, 300);
          }
        } else if (p.source === 'confluence') {
          // Shell + native Confluence: switch to the Confluence pane and deep-link to the page.
          if (
            _inShell &&
            window.gatorShell.navigateConfluencePin &&
            typeof _confluenceNativeEnabled === 'function' &&
            _confluenceNativeEnabled()
          ) {
            if (typeof openThirdPane === 'function') openThirdPane('confluence');
            window.gatorShell.navigateConfluencePin(webUrl || p.meta?.web_url || '');
          } else {
            if (typeof openThirdPane === 'function') openThirdPane('confluence');
            setTimeout(() => {
              if (typeof tpLoadDetail === 'function') tpLoadDetail(p.id);
              const detailCol = document.getElementById('tp-detail-col');
              if (detailCol && typeof _renderConfluencePageDetail === 'function')
                _renderConfluencePageDetail(detailCol, p.id, webUrl || '');
            }, 300);
          }
        } else if (p.source === 'onedrive') {
          // Shell + native OneDrive: switch to the OneDrive pane and deep-link
          // to the pinned file via its web URL (OneDrive for Business uses real
          // URL routing, like Outlook). Classic / browser: open the web URL in
          // a tab, or resolve it from Graph by id.
          if (
            _inShell &&
            window.gatorShell.navigateOneDrivePin &&
            typeof _onedriveNativeEnabled === 'function' &&
            _onedriveNativeEnabled()
          ) {
            if (typeof openThirdPane === 'function') openThirdPane('onedrive');
            window.gatorShell.navigateOneDrivePin(webUrl || p.meta?.web_url || '');
          } else if (webUrl) {
            window.open(webUrl, '_blank', 'noopener');
          } else {
            // Pin stored without a web_url (e.g. folder-browse path): resolve the
            // file's real URL from Graph by id, then open it. Fall back to the
            // OneDrive pane only if resolution fails (#60).
            // Open the tab synchronously inside the click gesture so the popup
            // blocker doesn't kill it, then redirect once the URL resolves.
            // NOTE: must NOT pass 'noopener' here — that makes window.open return
            // null, severing the handle we need to redirect. Clear opener after.
            const win = window.open('about:blank', '_blank');
            if (win) {
              try {
                win.opener = null;
              } catch (e) {}
            }
            const driveId = p.meta?.drive_id || '';
            const q = driveId ? `?drive_id=${encodeURIComponent(driveId)}` : '';
            const fallback = () => {
              if (win && !win.closed) win.close();
              if (typeof openThirdPane === 'function') openThirdPane('onedrive');
            };
            fetch(`/api/onedrive/items/${encodeURIComponent(p.id)}${q}`)
              .then((r) => (r.ok ? r.json() : null))
              .then((data) => {
                if (data && data.web_url && win && !win.closed) {
                  win.location.href = data.web_url;
                } else {
                  fallback();
                }
              })
              .catch(fallback);
          }
        } else if (p.source === 'calendar') {
          if (typeof openThirdPane === 'function') openThirdPane('calendar');
        } else if (p.source === 'github') {
          // Shell + native GitHub: switch to the GitHub pane and deep-link to the PR/issue.
          if (
            _inShell &&
            window.gatorShell.navigateGitHubPin &&
            typeof _githubNativeEnabled === 'function' &&
            _githubNativeEnabled()
          ) {
            if (typeof openThirdPane === 'function') openThirdPane('github');
            window.gatorShell.navigateGitHubPin(webUrl || p.meta?.web_url || '');
          } else if (webUrl) {
            window.open(webUrl, '_blank', 'noopener');
          } else {
            if (typeof openThirdPane === 'function') openThirdPane('github');
          }
        } else if (webUrl) {
          window.open(webUrl, '_blank', 'noopener');
        }
      });
      // ✦ Insert pin reference into chat input — uses the canonical helper so
      // the chip is identical to Shift+{ and shell-pinned chips (icon+label,
      // no X, no trailing line/space).
      card.querySelector('.pin-card-ask').addEventListener('click', () => {
        if (typeof window.insertPinChipAtCaret === 'function') {
          window.insertPinChipAtCaret({ source: p.source, id: p.id, label: p.label });
        }
        cleanup();
      });
      // × Unpin
      card.querySelector('.pin-card-remove').addEventListener('click', async () => {
        const removeBtn = card.querySelector('.pin-card-remove');
        removeBtn.disabled = true;
        const res = await fetch(
          `/api/context/pin/${p.source}/${encodeURIComponent(p.id)}?context_id=${contextId}`,
          { method: 'DELETE' },
        );
        const result = res.ok ? await res.json().catch(() => ({})) : {};
        if (!res.ok || !result.unpinned) {
          removeBtn.disabled = false;
          return;
        }
        _cachedPins = _cachedPins.filter(
          (pin) => !(pin.source === p.source && String(pin.id) === String(p.id)),
        );
        _cachedPinsContextId = contextId;
        if (typeof _refreshPinnedItemsCache === 'function') _refreshPinnedItemsCache(_cachedPins);
        card.style.transition = 'opacity .2s, transform .2s';
        card.style.opacity = '0';
        card.style.transform = 'scale(.95) translateX(-10px)';
        setTimeout(() => {
          card.remove();
          // Update badge locally from the already-correct _cachedPins — no network fetch needed
          const orb = document.getElementById('pin-orb');
          const badge = document.getElementById('pin-orb-badge');
          const count = Array.isArray(_cachedPins) ? _cachedPins.length : 0;
          if (badge) {
            badge.textContent = count;
            badge.classList.toggle('hidden', count === 0);
          }
          if (orb) {
            orb.classList.toggle('has-pins', count > 0);
          }
          if (countEl)
            countEl.textContent = list.children.length
              ? `${list.children.length} item${list.children.length !== 1 ? 's' : ''}`
              : '';
          if (!list.children.length) {
            const empty = document.createElement('div');
            empty.className = 'pin-popover-empty';
            const icon = document.createElement('div');
            icon.style.cssText = 'font-size:1.4rem;margin-bottom:.4rem';
            icon.textContent = '\uD83D\uDC0A';
            empty.appendChild(icon);
            empty.appendChild(document.createTextNode('All clear! No items pinned.'));
            list.replaceChildren(empty);
          }
        }, 200);
      });
      list.appendChild(card);
    });
  } catch {
    list.innerHTML = '<div class="pin-popover-empty">Could not load pins</div>';
  }
}

/* ── Settings Drawer ─────────────────────────────────── */
const settingsTrigger = document.getElementById('settings-trigger');
const settingsDrawer = document.getElementById('settings-drawer');
const settingsBackdrop = document.getElementById('settings-backdrop');
const drawerClose = document.getElementById('drawer-close');

function openDrawer() {
  // Shell mode: if a native WebContentsView is tiled beside Gator, hide it so
  // Settings gets the full window. Restore on close. Use tpState.type
  // SYNCHRONOUSLY (not getActiveApp().then()) — the async version raced with
  // fast open/close, causing the saved app to be set after closeDrawer ran.
  if (typeof window.gatorShell !== 'undefined' && window.gatorShell.isShell) {
    const t = typeof tpState !== 'undefined' ? tpState.type : null;
    if (t) {
      // Custom apps (Google Workspace services, user-added web apps) and the
      // code_agent pane both go through hideCustomApp — covers all current and
      // future custom-pane types in one branch.
      const skill = typeof SKILL_MAP !== 'undefined' ? SKILL_MAP[t] : null;
      const isCustomPane =
        (skill && (skill._customApp || skill._googleService)) || t === 'code_agent';
      if (isCustomPane && window.gatorShell.hideCustomApp) {
        window._settingsSavedApp = t;
        window.gatorShell.hideCustomApp(t);
      } else if (t === 'slack' && window.gatorShell.hideSlack) {
        window._settingsSavedApp = 'slack';
        window.gatorShell.hideSlack();
      } else if (t === 'teams' && window.gatorShell.hideTeams) {
        window._settingsSavedApp = 'teams';
        window.gatorShell.hideTeams();
      } else if (
        t === 'email' &&
        _outlookNativeEnabled &&
        _outlookNativeEnabled() &&
        window.gatorShell.hideOutlook
      ) {
        window._settingsSavedApp = 'outlook';
        window.gatorShell.hideOutlook();
      } else if (
        t === 'onedrive' &&
        _onedriveNativeEnabled &&
        _onedriveNativeEnabled() &&
        window.gatorShell.hideOneDrive
      ) {
        window._settingsSavedApp = 'onedrive';
        window.gatorShell.hideOneDrive();
      } else if (
        t === 'onenote' &&
        _onenoteNativeEnabled &&
        _onenoteNativeEnabled() &&
        window.gatorShell.hideOneNote
      ) {
        window._settingsSavedApp = 'onenote';
        window.gatorShell.hideOneNote();
      } else if (
        t === 'confluence' &&
        _confluenceNativeEnabled &&
        _confluenceNativeEnabled() &&
        window.gatorShell.hideConfluence
      ) {
        window._settingsSavedApp = 'confluence';
        window.gatorShell.hideConfluence();
      } else if (
        t === 'jira' &&
        _jiraNativeEnabled &&
        _jiraNativeEnabled() &&
        window.gatorShell.hideJira
      ) {
        window._settingsSavedApp = 'jira';
        window.gatorShell.hideJira();
      } else if (
        t === 'github' &&
        _githubNativeEnabled &&
        _githubNativeEnabled() &&
        window.gatorShell.hideGitHub
      ) {
        window._settingsSavedApp = 'github';
        window.gatorShell.hideGitHub();
      }
    }
  }
  settingsBackdrop.classList.remove('hidden');
  settingsDrawer.classList.remove('hidden');
  // Next frame: add is-open so CSS transition fires from the initial transform/opacity
  requestAnimationFrame(() => settingsDrawer.classList.add('is-open'));
  if (typeof _refreshUsageBar === 'function') _refreshUsageBar();
}
window._showConnectivityToast = _showConnectivityToast;
function _showConnectivityToast(message, type = 'success') {
  // Error toasts muted — too noisy for users switching tabs (re-enable when UX is refined)
  if (type === 'error') return;
  const toast = document.createElement('div');
  toast.className = 'connectivity-toast connectivity-toast-' + type;
  const palette = {
    success: { icon: '\u2713 ', bg: '#16a34a' },
    warn: { icon: '\u26A0\uFE0F ', bg: '#f59e0b' },
    warning: { icon: '\u26A0\uFE0F ', bg: '#f59e0b' },
    info: { icon: '\u2139\uFE0F ', bg: '#2563eb' },
    error: { icon: '\u2717 ', bg: '#ef4444' },
  };
  const tone = palette[type] || palette.error;
  toast.textContent = tone.icon + message;
  Object.assign(toast.style, {
    position: 'fixed',
    bottom: '1.2rem',
    left: '50%',
    transform: 'translateX(-50%)',
    padding: '.5rem 1.2rem',
    borderRadius: '8px',
    fontSize: '.82rem',
    fontWeight: '600',
    color: '#fff',
    zIndex: '9999',
    opacity: '0',
    transition: 'opacity .3s',
    background: tone.bg,
    boxShadow: '0 4px 12px rgba(0,0,0,.3)',
  });
  document.body.appendChild(toast);
  requestAnimationFrame(() => {
    toast.style.opacity = '1';
  });
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function _cleanSubtitleText(s) {
  if (!s) return '';
  // Strip markdown noise that shows up raw in the card subtitle.
  let t = s
    .replace(/\*\*/g, '')
    .replace(/^[-*_\s|]+/, '')
    .replace(/[-*_\s|]+$/, '');
  // Take last ~140 chars so we surface the conclusion, not the plan; trim to
  // a word boundary so we don't slice mid-word.
  if (t.length > 140) {
    t = t.slice(-140);
    const sp = t.indexOf(' ');
    if (sp > 0 && sp < 30) t = '\u2026' + t.slice(sp + 1);
    else t = '\u2026' + t;
  }
  return t.trim();
}

async function _openTaskResult(taskId, inNewTab) {
  if (!taskId) return;
  try {
    const t = await fetch('/api/tasks/' + taskId).then((r) => r.json());
    const result = t.result || '(no result)';
    if (t.pane_data) {
      try {
        const pd = typeof t.pane_data === 'string' ? JSON.parse(t.pane_data) : t.pane_data;
        if (typeof _handlePaneSignal === 'function') _handlePaneSignal(pd.pane, pd.paneData || {});
      } catch {}
    }
    if (inNewTab) {
      const _title = 'Task Result';
      if (t.context_id && typeof createTabWithId === 'function') {
        createTabWithId(t.context_id, _title);
      } else if (typeof createTab === 'function') {
        createTab();
      }
    }
    const messages = document.getElementById('messages');
    if (messages) {
      const msgDiv = document.createElement('div');
      msgDiv.className = 'msg assistant';
      const prose = document.createElement('div');
      prose.className = 'prose';
      prose.appendChild(document.createRange().createContextualFragment(renderMarkdown(result)));
      msgDiv.appendChild(prose);
      messages.appendChild(msgDiv);
      messages.scrollTop = messages.scrollHeight;
    }
  } catch (err) {
    console.warn('Open task failed:', err);
  }
}

function _showSystemCard(opts) {
  const card = document.createElement('div');
  card.className = 'system-card' + (opts.status === 'failed' ? ' system-card-failed' : '');
  if (opts.taskId) card.dataset.taskId = opts.taskId;

  const iconEl = document.createElement('span');
  iconEl.className = 'system-card-icon';
  iconEl.textContent = opts.icon || '\u26A1';

  const body = document.createElement('div');
  body.className = 'system-card-body';
  const titleEl = document.createElement('div');
  titleEl.className = 'system-card-title';
  titleEl.textContent = opts.title || '';
  body.appendChild(titleEl);
  if (opts.subtitle) {
    const sub = document.createElement('div');
    sub.className = 'system-card-sub';
    sub.textContent = _cleanSubtitleText(opts.subtitle);
    body.appendChild(sub);
  }

  const actions = document.createElement('div');
  actions.className = 'system-card-actions';

  // If we have a taskId, offer open-in-this-tab / open-in-new-tab actions.
  // Otherwise fall back to a single Dismiss button (e.g., failed-task case
  // where there's no useful result to render).
  if (opts.taskId && opts.status !== 'failed') {
    const openHere = document.createElement('button');
    openHere.className = 'system-card-btn';
    openHere.textContent = 'Open in this tab';
    openHere.addEventListener('click', () => {
      _openTaskResult(opts.taskId, false);
      card.remove();
    });
    const openNew = document.createElement('button');
    openNew.className = 'system-card-btn';
    openNew.textContent = 'Open in new tab';
    openNew.addEventListener('click', () => {
      _openTaskResult(opts.taskId, true);
      card.remove();
    });
    actions.append(openHere, openNew);
  } else {
    const btn = document.createElement('button');
    btn.className = 'system-card-btn';
    btn.textContent = 'Dismiss';
    btn.addEventListener('click', () => card.remove());
    actions.appendChild(btn);
  }

  card.append(iconEl, body, actions);
  const messages = document.getElementById('messages');
  if (messages) {
    messages.appendChild(card);
    messages.scrollTop = messages.scrollHeight;
  }
  if (opts.status !== 'failed')
    setTimeout(() => {
      if (document.contains(card)) card.remove();
    }, 30000);
}

function _showMcpAuthErrorCard(connectionId, connectionName) {
  const chatLog = document.querySelector('#chat-messages, .chat-log, .cc-messages');
  if (!chatLog) return;

  const card = document.createElement('div');
  card.className = 'system-card system-card-failed';

  const iconEl = document.createElement('span');
  iconEl.className = 'system-card-icon';
  iconEl.textContent = '🔑';

  const body = document.createElement('div');
  body.className = 'system-card-body';
  const titleEl = document.createElement('div');
  titleEl.className = 'system-card-title';
  titleEl.textContent = connectionName + ' needs auth credentials';
  const sub = document.createElement('div');
  sub.className = 'system-card-sub';
  sub.textContent = 'Add the required API key or header in the connection settings.';
  body.append(titleEl, sub);

  const actions = document.createElement('div');
  actions.className = 'system-card-actions';

  const editBtn = document.createElement('button');
  editBtn.className = 'system-card-btn';
  editBtn.textContent = 'Edit ' + connectionName + ' settings';
  editBtn.addEventListener('click', () => {
    card.remove();
    fetch('/api/config/mcp')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        const conn = (data || []).find((c) => c.id === connectionId);
        if (conn && typeof window.openMcpEditModal === 'function') {
          window.openMcpEditModal(conn, { onSuccess: () => _loadMcpConnections() });
        }
      })
      .catch(() => {});
  });

  const dismissBtn = document.createElement('button');
  dismissBtn.className = 'system-card-btn';
  dismissBtn.textContent = 'Dismiss';
  dismissBtn.addEventListener('click', () => card.remove());

  actions.append(editBtn, dismissBtn);
  card.append(iconEl, body, actions);
  chatLog.appendChild(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function closeDrawer() {
  settingsDrawer.classList.remove('is-open');
  // Wait for transition to finish before hiding
  setTimeout(() => {
    settingsDrawer.classList.add('hidden');
    settingsBackdrop.classList.add('hidden');
  }, 200);
  // Shell mode: restore the external app that was hidden when Settings opened —
  // BUT only if the user didn't switch to a different pane while Settings was
  // open. If they navigated to OneDrive/Jira/etc. (a classic pane), restoring
  // the native app would layer it on top of the classic pane.
  const app = window._settingsSavedApp;
  if (app && typeof window.gatorShell !== 'undefined' && window.gatorShell.isShell) {
    const currentType = typeof tpState !== 'undefined' ? tpState.type : null;
    const nativeTypes = [
      'slack',
      'teams',
      'email',
      'onedrive',
      'onenote',
      'confluence',
      'jira',
      'github',
    ];
    // Only restore if the current pane is still a native app type (or null =
    // no pane opened while settings was up).
    if (currentType === null || nativeTypes.indexOf(currentType) !== -1) {
      // Custom apps (Google Workspace, custom web apps) and code_agent restore
      // through showCustomApp — covers all current and future custom-pane types.
      const skill = typeof SKILL_MAP !== 'undefined' ? SKILL_MAP[app] : null;
      const isCustomPane =
        (skill && (skill._customApp || skill._googleService)) || app === 'code_agent';
      if (isCustomPane && window.gatorShell.showCustomApp) {
        window.gatorShell.showCustomApp(app);
      } else if (app === 'slack' && window.gatorShell.showSlack) window.gatorShell.showSlack();
      else if (app === 'teams' && window.gatorShell.showTeams) window.gatorShell.showTeams();
      else if (app === 'outlook' && window.gatorShell.showOutlook) window.gatorShell.showOutlook();
      else if (app === 'onedrive' && window.gatorShell.showOneDrive)
        window.gatorShell.showOneDrive();
      else if (app === 'onenote' && window.gatorShell.showOneNote) window.gatorShell.showOneNote();
      else if (app === 'confluence' && window.gatorShell.showConfluence)
        window.gatorShell.showConfluence();
      else if (app === 'jira' && window.gatorShell.showJira) window.gatorShell.showJira();
      else if (app === 'github' && window.gatorShell.showGitHub) window.gatorShell.showGitHub();
    }
    window._settingsSavedApp = null;
  }
}
settingsTrigger.addEventListener('click', openDrawer);
drawerClose.addEventListener('click', closeDrawer);
settingsBackdrop.addEventListener('click', closeDrawer);

/* ── Settings tab switching ─────────────────────────── */
function initSettingsTabs() {
  const tabs = document.querySelectorAll('.smodal-tab');
  const panels = document.querySelectorAll('.smodal-panel');
  const STORAGE_KEY = 'settings-active-tab';

  function activateTab(tabName) {
    tabs.forEach((t) => t.classList.toggle('active', t.dataset.tab === tabName));
    panels.forEach((p) => p.classList.toggle('hidden', p.id !== 'spanel-' + tabName));
    localStorage.setItem(STORAGE_KEY, tabName);
    // When the Skills tab is activated, lazily mount the marketplace pane into
    // its panel. Subsequent activations are no-ops (mount() is idempotent).
    if (tabName === 'skills') {
      const host = document.getElementById('skills-pane-mount');
      if (host && window.MarketplacePane && typeof window.MarketplacePane.mount === 'function') {
        window.MarketplacePane.mount(host);
      }
      // Wire the disclosure toggle the first time we mount Skills.
      const trigger = document.getElementById('skill-disclosure-trigger');
      const panel = document.getElementById('skill-disclosure-panel');
      if (trigger && panel && !trigger.dataset.wired) {
        trigger.dataset.wired = '1';
        trigger.addEventListener('click', (e) => {
          e.preventDefault();
          panel.classList.toggle('hidden');
        });
      }
    }
    // Refresh storage usage each time General is opened (sizes change with use).
    if (tabName === 'general') {
      _loadStorageUsage();
    }
  }

  tabs.forEach((tab) => {
    if (!tab.dataset.tab) return;
    tab.addEventListener('click', () => activateTab(tab.dataset.tab));
  });

  // Restore last-used tab, default to LLM
  const saved = localStorage.getItem(STORAGE_KEY);
  activateTab(saved && document.getElementById('spanel-' + saved) ? saved : 'llm');

  // Public: open settings drawer on a specific panel (used by Marketplace CTA)
  window.openSettingsPanel = (tabName) => {
    openDrawer();
    activateTab(tabName);
  };
}

initSettingsTabs();

/* ── Settings → Storage (Gator working files) ───────────── */
function _fmtBytes(n) {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0,
    v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return (v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)) + ' ' + u[i];
}

async function _loadStorageUsage() {
  const host = document.getElementById('storage-rows');
  if (!host) return;
  try {
    const data = await fetch('/api/storage/usage').then((r) => r.json());
    if (!data.ok) {
      host.innerHTML =
        '<div class="srow"><div class="srow-info"><div class="srow-sub">Couldn\'t read storage.</div></div></div>';
      return;
    }
    host.innerHTML = '';
    data.items.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'srow';
      // Leading status-dot column (empty here) — matches every other srow so the
      // labels align in one vertical line down the panel.
      const status = document.createElement('div');
      status.className = 'section-status';
      const info = document.createElement('div');
      info.className = 'srow-info';
      const label = document.createElement('div');
      label.className = 'srow-label';
      label.textContent = item.label;
      const sub = document.createElement('div');
      sub.className = 'srow-sub';
      sub.textContent = _fmtBytes(item.size_bytes) + ' · ' + item.path;
      info.appendChild(label);
      info.appendChild(sub);
      const actions = document.createElement('div');
      actions.className = 'srow-actions';
      const openBtn = document.createElement('button');
      openBtn.className = 'btn-ghost';
      openBtn.textContent = 'Open';
      openBtn.addEventListener('click', () => {
        fetch('/api/open-file', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: item.path }),
        })
          .then((r) => r.json())
          .then((d) => {
            if (!d.ok) _showConnectivityToast(d.message || "Couldn't open the folder.", 'info');
          });
      });
      actions.appendChild(openBtn);
      if (item.clearable) {
        const clearBtn = document.createElement('button');
        clearBtn.className = 'btn-ghost';
        clearBtn.textContent = 'Clear';
        clearBtn.disabled = !item.size_bytes;
        clearBtn.addEventListener('click', () => _clearStorage(item.key, item.label));
        actions.appendChild(clearBtn);
      }
      row.appendChild(status);
      row.appendChild(info);
      row.appendChild(actions);
      host.appendChild(row);
    });
  } catch {
    host.innerHTML =
      '<div class="srow"><div class="srow-info"><div class="srow-sub">Couldn\'t read storage.</div></div></div>';
  }
}

function _clearStorage(key, label) {
  _showConfirmModal(
    'Clear ' + label + '?',
    'This deletes temporary build files Gator created. Your documents and generated outputs are not affected.',
    'Clear',
    async () => {
      try {
        const d = await fetch('/api/storage/clear', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key }),
        }).then((r) => r.json());
        if (d.ok) _showConnectivityToast('Cleared — ' + label + ' is now empty.', 'success');
        else _showConnectivityToast(d.message || "Couldn't clear that folder.", 'info');
      } catch {
        _showConnectivityToast("Couldn't clear that folder.", 'info');
      }
      _loadStorageUsage();
    },
  );
}

const settingsHomeBtn = document.getElementById('settings-home-btn');
if (settingsHomeBtn) settingsHomeBtn.addEventListener('click', closeDrawer);

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && settingsDrawer && !settingsDrawer.classList.contains('hidden')) {
    closeDrawer();
  }
});

/* ── About Modal ───────────────────────────────────── */
const aboutModal = document.getElementById('about-modal');
const aboutBackdrop = document.getElementById('about-backdrop');
const aboutClose = document.getElementById('about-close');

function openAbout() {
  aboutBackdrop.classList.remove('hidden');
  aboutModal.classList.remove('hidden');
  requestAnimationFrame(() => aboutModal.classList.add('is-open'));
  const versionEl = document.getElementById('about-version');
  if (versionEl && !versionEl.textContent) {
    fetch('/health')
      .then((r) => r.json())
      .then((d) => {
        versionEl.textContent = 'v' + (d.version || '');
      })
      .catch(() => {});
  }
}
function closeAbout() {
  aboutModal.classList.remove('is-open');
  setTimeout(() => {
    aboutModal.classList.add('hidden');
    aboutBackdrop.classList.add('hidden');
  }, 200);
}
const helpTrigger = document.getElementById('help-trigger');
if (helpTrigger)
  helpTrigger.addEventListener('click', () => {
    closeDrawer();
    openAbout();
  });
if (aboutClose) aboutClose.addEventListener('click', closeAbout);
if (aboutBackdrop) aboutBackdrop.addEventListener('click', closeAbout);
document.getElementById('about-restart-tour')?.addEventListener('click', () => {
  resetOnboarding();
  closeAbout();
  if (history.length === 0) {
    _showChatOrOnboarding();
  } else {
    // Current tab has history — create a new empty tab to show the tour
    createTab();
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !aboutModal.classList.contains('hidden')) closeAbout();
});

/* ── Token hint tooltip (inside hidden Teams Chat section) ── */
const tokenHintBtn = document.getElementById('token-hint-btn');
const tokenHintBox = document.getElementById('token-hint-box');
if (tokenHintBtn && tokenHintBox) {
  tokenHintBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const visible = tokenHintBox.classList.toggle('visible');
    tokenHintBtn.classList.toggle('active', visible);
  });
  document.addEventListener('click', () => {
    tokenHintBox.classList.remove('visible');
    tokenHintBtn.classList.remove('active');
  });
}

/* ── LLM Profile Manager ─────────────────────────────── */
// Legacy stubs — referenced by updateSettingsBadges and gate code; kept to avoid crashes
const apikeyDot = document.getElementById('apikey-dot');
const apikeySub = document.getElementById('apikey-sub');
const apikeyInput = document.getElementById('apikey-input');
const useridInput = document.getElementById('userid-input');
const apikeySaveBtn = document.getElementById('apikey-save-btn');
const apikeyChangeBtn = document.getElementById('apikey-change-btn');
const apikeyMsg = document.getElementById('apikey-msg');
const apikeyFormInline = document.getElementById('apikey-form-inline');

// Setup gate elements
const setupGate = document.getElementById('setup-gate');
const gateSaveBtn = document.getElementById('gate-save-btn');
const gateMsg = document.getElementById('gate-msg');
// Once the user dismisses the welcome gate, never force it back this session —
// loadLlmProfiles() runs on every drawer open, so without this it would re-gate.
let _setupGateDismissed = false;
function _dismissSetupGate() {
  _setupGateDismissed = true;
  if (setupGate) setupGate.classList.add('hidden');
}

// ── Internal state ──────────────────────────────────────
const EYE_PATH =
  '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
const EYE_OFF_PATH =
  '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/>';

const _LLM_BASE_URLS = {
  anthropic: 'https://api.anthropic.com',
  openai: 'https://api.openai.com',
  gemini: 'https://generativelanguage.googleapis.com/v1beta/openai',
  local: 'http://localhost:1234/v1',
  gateway: '',
  'openai-compatible': '',
};

let _llmProfiles = [];
let _llmActiveId = null;
let _llmEditingId = null;
let _llmFormMode = 'hidden'; // 'hidden' | 'create' | 'edit'
let _llmBusy = false; // guards activate/delete against double-clicks

// Provider display labels + icon colors
const _LLM_PROVIDER_LABELS = {
  gateway: 'Enterprise Gateway',
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  gemini: 'Google Gemini',
  local: 'Local',
  'openai-compatible': 'OpenAI-Compatible',
};
const _LLM_PROVIDER_ICONS = {
  gateway: '\u2302',
  anthropic: 'A',
  openai: 'AI',
  gemini: 'G',
  local: '\u2981',
  'openai-compatible': '\u2295',
};

// Delegated eye toggle — covers LLM + all connector fields
(function _initEyeToggles() {
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.si-eye');
    if (!btn) return;
    const input = document.getElementById(btn.dataset.target);
    if (!input) return;
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    const svg = btn.querySelector('svg');
    if (svg) svg.innerHTML = show ? EYE_OFF_PATH : EYE_PATH;
  });
})();

// Model selection is handled exclusively in the prompt bar.
window._llmCddPopulate = function () {}; // no-op, kept for compat

function _llmUpdateVisibility() {
  const type = document.getElementById('llm-type')?.value || 'gateway';
  const showBase =
    type === 'gateway' || type === 'openai-compatible' || type === 'gemini' || type === 'local';
  const showHeader = type === 'gateway' || type === 'openai-compatible';
  const showUser = type === 'gateway';
  const showAnthropicUrl = type === 'gateway' || type === 'openai-compatible';
  const toggleRow = (id, show) => {
    const el = document.getElementById(id);
    if (el) el.style.display = show ? '' : 'none';
  };
  toggleRow('llm-si-baseurl', showBase);
  toggleRow('llm-si-keyheader', showHeader);
  toggleRow('llm-si-userid', showUser);
  toggleRow('llm-si-anthropicurl', showAnthropicUrl);
  const hint = document.getElementById('llm-base-hint');
  if (hint) hint.style.display = type === 'local' ? '' : 'none';
}

function _llmShowError(msg) {
  const el = document.getElementById('llm-form-error');
  if (el) {
    el.textContent = msg;
    el.style.display = msg ? '' : 'none';
  }
}

// Show errors in a visible area outside the (possibly hidden) edit form —
// used by card actions (activate/delete) and reload.
function _llmShowCardError(msg) {
  let el = document.getElementById('llm-card-error');
  if (!el) {
    el = document.createElement('div');
    el.id = 'llm-card-error';
    el.style.cssText = 'font-size:.75rem;color:var(--danger,#ef4444);padding:4px 0;display:none';
    const cards = document.getElementById('llm-profile-cards');
    if (cards && cards.parentNode) cards.parentNode.insertBefore(el, cards.nextSibling);
  }
  el.textContent = msg;
  el.style.display = msg ? '' : 'none';
  if (msg)
    setTimeout(() => {
      if (el) el.style.display = 'none';
    }, 5000);
}

function _llmFillForm(profile) {
  if (!profile) return;
  const typeEl = document.getElementById('llm-type');
  if (typeEl) typeEl.value = profile.type || 'gateway';
  const el = (id) => document.getElementById(id);
  if (el('llm-base-url')) el('llm-base-url').value = profile.base_url || '';
  if (el('llm-anthropic-url')) el('llm-anthropic-url').value = profile.anthropic_url || '';
  if (el('llm-api-key')) {
    el('llm-api-key').value = profile.api_key || '';
  }
  if (el('llm-key-header'))
    el('llm-key-header').value =
      profile.api_key_header || (profile.type === 'gateway' ? 'Ocp-Apim-Subscription-Key' : '');
  if (el('llm-user-id')) el('llm-user-id').value = profile.user_id || '';
  // Populate fallback dropdown with other profiles (exclude self)
  _llmPopulateFallback(profile.id, profile.fallback_profile_id || '');
  // Populate custom model dropdown
  _llmCddPopulate(profile.models || [], profile.active_model || '');
  _llmUpdateVisibility();
}

function _llmPopulateFallback(excludeId, selectedId) {
  const sel = document.getElementById('llm-fallback-profile');
  if (!sel) return;
  sel.innerHTML = '<option value="">None (no fallback)</option>';
  _llmProfiles.forEach((p) => {
    if (p.id === excludeId) return;
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name + ' (' + (p.active_model || p.models?.[0] || 'no model') + ')';
    if (p.id === selectedId) opt.selected = true;
    sel.appendChild(opt);
  });
}

async function loadLlmProfiles() {
  try {
    const res = await fetch('/api/config/llm/profiles');
    if (!res.ok) return;
    const d = await res.json();
    _llmProfiles = d.profiles || [];
    _llmActiveId = d.active || d.active_id || null;
    // Render the card list
    renderLlmProfileList(_llmProfiles, _llmActiveId);
    // setup gate
    const hasActive = !!_llmActiveId;
    if (setupGate) setupGate.classList.toggle('hidden', hasActive || _setupGateDismissed);
    if (apikeyDot) apikeyDot.className = 'section-status ' + (hasActive ? 'st-ok' : 'st-err');
    updateSettingsBadges();
    // Refresh prompt bar model list to reflect newly active profile
    if (typeof window._refreshPromptBarModels === 'function') window._refreshPromptBarModels();
  } catch {
    /* non-fatal */
  }
}

// Render profile cards
function renderLlmProfileList(profiles, activeId) {
  const container = document.getElementById('llm-profile-cards');
  if (!container) return;
  container.innerHTML = '';

  if (!profiles || profiles.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'llm-card-empty';
    empty.textContent = 'No providers configured. Click ';
    const strong = document.createElement('strong');
    strong.textContent = '+ Add Provider';
    empty.appendChild(strong);
    empty.appendChild(document.createTextNode(' to get started.'));
    container.appendChild(empty);
    return;
  }

  profiles.forEach((p) => {
    const isActive = p.id === activeId;
    const label = _LLM_PROVIDER_LABELS[p.type] || p.type || 'Unknown';
    const icon = _LLM_PROVIDER_ICONS[p.type] || '?';
    const modelCount = (p.models || []).length;
    const activeModel = p.active_model || (modelCount > 0 ? p.models[0] : '—');

    // Show fallback provider if configured
    let fallbackLabel = '';
    if (p.fallback_profile_id) {
      const fb = _llmProfiles.find((x) => x.id === p.fallback_profile_id);
      if (fb) fallbackLabel = fb.name || fb.id;
    }

    // Build card with DOM APIs (textContent) — no innerHTML, no XSS.
    const card = document.createElement('div');
    card.className = 'llm-profile-card' + (isActive ? ' active' : '');
    card.dataset.profileId = p.id;

    const iconEl = document.createElement('div');
    iconEl.className = 'llm-card-icon';
    iconEl.textContent = icon;
    card.appendChild(iconEl);

    const body = document.createElement('div');
    body.className = 'llm-card-body';

    const header = document.createElement('div');
    header.className = 'llm-card-header';
    const nameEl = document.createElement('span');
    nameEl.className = 'llm-card-name';
    nameEl.textContent = p.name || 'Unnamed';
    header.appendChild(nameEl);
    if (isActive) {
      const badge = document.createElement('span');
      badge.className = 'llm-card-badge';
      badge.textContent = 'Active';
      header.appendChild(badge);
    }
    body.appendChild(header);

    const meta = document.createElement('div');
    meta.className = 'llm-card-meta';
    const providerEl = document.createElement('span');
    providerEl.className = 'llm-card-provider';
    providerEl.textContent = label;
    meta.appendChild(providerEl);
    const sep1 = document.createElement('span');
    sep1.className = 'llm-card-sep';
    sep1.textContent = '\u00B7';
    meta.appendChild(sep1);
    const modelsEl = document.createElement('span');
    modelsEl.className = 'llm-card-models';
    modelsEl.textContent = modelCount + ' model' + (modelCount !== 1 ? 's' : '');
    meta.appendChild(modelsEl);
    const sep2 = document.createElement('span');
    sep2.className = 'llm-card-sep';
    sep2.textContent = '\u00B7';
    meta.appendChild(sep2);
    const activeModelEl = document.createElement('span');
    activeModelEl.className = 'llm-card-active-model';
    activeModelEl.textContent = activeModel;
    activeModelEl.title = activeModel;
    meta.appendChild(activeModelEl);
    if (fallbackLabel) {
      const sep3 = document.createElement('span');
      sep3.className = 'llm-card-sep';
      sep3.textContent = '\u00B7';
      meta.appendChild(sep3);
      const fbEl = document.createElement('span');
      fbEl.className = 'llm-card-fallback';
      fbEl.textContent = 'fallback: ' + fallbackLabel;
      fbEl.title = 'Falls back to ' + fallbackLabel + ' if this model stalls';
      meta.appendChild(fbEl);
    }
    body.appendChild(meta);

    card.appendChild(body);

    const actions = document.createElement('div');
    actions.className = 'llm-card-actions';
    if (!isActive) {
      const actBtn = document.createElement('button');
      actBtn.className = 'llm-card-btn llm-card-activate';
      actBtn.dataset.action = 'activate';
      actBtn.title = 'Set as active provider';
      actBtn.textContent = 'Activate';
      actions.appendChild(actBtn);
    }
    const editBtn = document.createElement('button');
    editBtn.className = 'llm-card-btn llm-card-edit';
    editBtn.dataset.action = 'edit';
    editBtn.title = 'Edit provider settings';
    editBtn.textContent = 'Edit';
    actions.appendChild(editBtn);
    if (!isActive) {
      const delBtn = document.createElement('button');
      delBtn.className = 'llm-card-btn llm-card-delete';
      delBtn.dataset.action = 'delete';
      delBtn.title = 'Delete provider';
      delBtn.textContent = 'Delete';
      actions.appendChild(delBtn);
    }
    card.appendChild(actions);

    container.appendChild(card);
  });
}

async function _saveLlmProfile() {
  const saveBtn = document.getElementById('llm-save-btn');
  _llmShowError('');

  const typedKey = document.getElementById('llm-api-key')?.value.trim() || '';
  const storedKey = _llmEditingId
    ? (_llmProfiles.find((p) => p.id === _llmEditingId) || {}).api_key || ''
    : '';
  const resolvedKey = typedKey || storedKey;

  const nameVal = document.getElementById('llm-name-input')?.value.trim() || '';

  const payload = {
    type: document.getElementById('llm-type')?.value || 'gateway',
    base_url: document.getElementById('llm-base-url')?.value.trim() || '',
    anthropic_url: document.getElementById('llm-anthropic-url')?.value.trim() || '',
    api_key: resolvedKey,
    api_key_header: document.getElementById('llm-key-header')?.value.trim() || '',
    user_id: document.getElementById('llm-user-id')?.value.trim() || '',
    name:
      nameVal ||
      (_llmEditingId
        ? (_llmProfiles.find((p) => p.id === _llmEditingId) || {}).name || 'My Profile'
        : 'My Profile'),
    fallback_profile_id: document.getElementById('llm-fallback-profile')?.value || '',
  };
  if (_llmEditingId) payload.id = _llmEditingId;
  // API key is optional for self-hosted / OpenAI-compatible endpoints (local
  // LM Studio/Ollama, vLLM, etc.) — they often run without auth. Cloud
  // providers (gateway, anthropic, openai, gemini) still require one.
  const _KEY_OPTIONAL = payload.type === 'local' || payload.type === 'openai-compatible';
  if (!payload.api_key && !_KEY_OPTIONAL) {
    _llmShowError('API key is required.');
    return;
  }
  if (!payload.name || !payload.name.trim()) {
    _llmShowError('Name is required.');
    return;
  }

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving\u2026';
  }
  try {
    const res = await fetch('/api/config/llm/profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await res.json();
    if (!res.ok) {
      _llmShowError(
        Array.isArray(d.detail) ? d.detail.map((e) => e.msg).join(', ') : d.detail || 'Save failed',
      );
      return;
    }
    const savedId = d.id || _llmEditingId;
    _llmEditingId = savedId;
    const actRes = await fetch('/api/config/llm/profiles/' + savedId + '/activate', {
      method: 'POST',
    });
    if (!actRes.ok) {
      const ad = await actRes.json().catch(() => ({}));
      _llmShowError(ad.detail || 'Saved but activation failed');
      await loadLlmProfiles();
      return;
    }
    await loadLlmProfiles();
    _llmShowError('');
    // Hide the form — we're back to the card list
    _hideLlmForm();
    if (saveBtn) {
      saveBtn.textContent = '\u2713 Activated';
      setTimeout(() => {
        if (saveBtn) saveBtn.textContent = 'Save \u0026 Activate';
      }, 2000);
    }
  } catch (err) {
    _llmShowError(err.message);
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      if (saveBtn.textContent === 'Saving\u2026') saveBtn.textContent = 'Save \u0026 Activate';
    }
  }
}

// The edit form HTML template — inserted inline below the card being edited,
// or at the end of the list for "Add Provider". Built once as a string and
// re-inserted so the form lives visually next to the card it edits.
const _LLM_FORM_HTML =
  '<div id="llm-edit-form" class="llm-edit-form">' +
  '<div class="llm-edit-form-header">' +
  '<span id="llm-form-mode-label" style="font-size:.85rem;font-weight:600;color:var(--text)">Add Provider</span>' +
  '<button class="btn-ghost" id="llm-cancel-edit-btn" style="font-size:.75rem;padding:.2rem .5rem">Cancel</button>' +
  '</div>' +
  '<div class="si-row" id="llm-si-name">' +
  '<span class="si-label">Name</span>' +
  '<div class="si-field"><input type="text" id="llm-name-input" class="key-field" autocomplete="off" placeholder="e.g. Work Gateway, My OpenAI" required /></div>' +
  '</div>' +
  '<div class="si-row" id="llm-si-provider">' +
  '<span class="si-label">Provider</span>' +
  '<div class="si-field">' +
  '<select id="llm-type" class="key-field llm-select">' +
  '<option value="gateway">Enterprise Gateway</option>' +
  '<option value="anthropic">Anthropic</option>' +
  '<option value="openai">OpenAI</option>' +
  '<option value="gemini">Google Gemini</option>' +
  '<option value="local">Local (LM Studio / Ollama)</option>' +
  '<option value="openai-compatible">OpenAI-Compatible</option>' +
  '</select>' +
  '</div>' +
  '</div>' +
  '<div class="si-row" id="llm-si-baseurl">' +
  '<span class="si-label">Base URL</span>' +
  '<div class="si-field">' +
  '<input type="text" id="llm-base-url" class="key-field" autocomplete="off" />' +
  '<div id="llm-base-hint" class="key-hint" style="display:none;margin-top:2px;font-size:.7rem;color:var(--text-dim)">LM Studio: \u2026:1234 \u00B7 Ollama: \u2026:11434</div>' +
  '</div>' +
  '</div>' +
  '<div class="si-row" id="llm-si-anthropicurl" style="display:none">' +
  '<span class="si-label">Anthropic URL</span>' +
  '<div class="si-field">' +
  '<input type="text" id="llm-anthropic-url" class="key-field" autocomplete="off" placeholder="e.g. https://llm-api.amd.com/Anthropic" />' +
  '<div class="key-hint" style="margin-top:2px;font-size:.7rem;color:var(--text-dim)">Optional \u2014 routes Claude models through native Anthropic API for prompt caching (90% token savings on turns 2+)</div>' +
  '</div>' +
  '</div>' +
  '<div class="si-row">' +
  '<span class="si-label">API Key</span>' +
  '<div class="si-field">' +
  '<div class="si-secret">' +
  '<input type="password" id="llm-api-key" class="key-field" autocomplete="off" />' +
  '<button type="button" class="si-eye" data-target="llm-api-key" title="Show/hide" tabindex="-1">' +
  '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>' +
  '</button>' +
  '</div>' +
  '</div>' +
  '</div>' +
  '<div class="si-row" id="llm-si-keyheader">' +
  '<span class="si-label">Key Header</span>' +
  '<div class="si-field"><input type="text" id="llm-key-header" class="key-field" autocomplete="off" /></div>' +
  '</div>' +
  '<div class="si-row" id="llm-si-userid">' +
  '<span class="si-label">User ID</span>' +
  '<div class="si-field"><input type="text" id="llm-user-id" class="key-field" autocomplete="off" /></div>' +
  '</div>' +
  '<div class="si-row" id="llm-si-fallback">' +
  '<span class="si-label">Fallback</span>' +
  '<div class="si-field">' +
  '<select id="llm-fallback-profile" class="key-field llm-select">' +
  '<option value="">None (no fallback)</option>' +
  '</select>' +
  '<div class="key-hint" style="margin-top:2px;font-size:.7rem;color:var(--text-dim)">If the primary model stalls, the user can switch to this provider to continue.</div>' +
  '</div>' +
  '</div>' +
  '<div class="si-row" style="padding-top:8px">' +
  '<span class="si-label"></span>' +
  '<div class="si-field" style="display:flex;align-items:center;gap:10px">' +
  '<button class="btn-primary" id="llm-save-btn" style="font-size:.8rem">Save &amp; Activate</button>' +
  '<span id="llm-form-error" style="font-size:.75rem;color:var(--danger,#ef4444)"></span>' +
  '</div>' +
  '</div>' +
  '</div>';

// Show the inline form below a specific card (edit) or at the end (create).
// The form is inserted into the card list container so it appears in context.
function _showLlmForm(mode, profile) {
  _llmFormMode = mode;
  const container = document.getElementById('llm-profile-cards');
  if (!container) return;

  // Remove any existing form
  const existing = document.getElementById('llm-edit-form');
  if (existing) existing.remove();

  // Insert form HTML
  const wrapper = document.createElement('div');
  wrapper.innerHTML = _LLM_FORM_HTML;
  const form = wrapper.firstElementChild;

  if (mode === 'edit' && profile) {
    // Insert below the card being edited
    const card = container.querySelector('.llm-profile-card[data-profile-id="' + profile.id + '"]');
    if (card && card.nextSibling) {
      container.insertBefore(form, card.nextSibling);
    } else if (card) {
      container.appendChild(form);
    } else {
      container.appendChild(form);
    }
    _llmEditingId = profile.id;
    _llmFillForm(profile);
    const nameEl = document.getElementById('llm-name-input');
    if (nameEl) nameEl.value = profile.name || '';
    const label = document.getElementById('llm-form-mode-label');
    if (label) label.textContent = 'Edit: ' + (profile.name || 'Provider');
  } else {
    // Create mode — at the end of the list
    container.appendChild(form);
    _llmEditingId = null;
    const el = (id) => document.getElementById(id);
    if (el('llm-name-input')) el('llm-name-input').value = '';
    if (el('llm-type')) el('llm-type').value = 'gateway';
    if (el('llm-base-url')) el('llm-base-url').value = _LLM_BASE_URLS['gateway'] || '';
    if (el('llm-anthropic-url')) el('llm-anthropic-url').value = '';
    if (el('llm-api-key')) el('llm-api-key').value = '';
    if (el('llm-key-header')) el('llm-key-header').value = 'Ocp-Apim-Subscription-Key';
    if (el('llm-user-id')) el('llm-user-id').value = '';
    _llmPopulateFallback(null, '');
    _llmUpdateVisibility();
    const label = document.getElementById('llm-form-mode-label');
    if (label) label.textContent = 'Add Provider';
  }

  // Wire the save + cancel buttons (they're freshly created each time)
  const saveBtn = document.getElementById('llm-save-btn');
  const cancelBtn = document.getElementById('llm-cancel-edit-btn');
  if (saveBtn) saveBtn.addEventListener('click', _saveLlmProfile);
  if (cancelBtn) cancelBtn.addEventListener('click', _hideLlmForm);

  // Wire provider change
  const typeEl = document.getElementById('llm-type');
  const baseUrlEl = document.getElementById('llm-base-url');
  if (typeEl) {
    typeEl.addEventListener('change', () => {
      const preset = _LLM_BASE_URLS[typeEl.value];
      if (preset !== undefined && baseUrlEl) baseUrlEl.value = preset;
      const kh = document.getElementById('llm-key-header');
      if (kh && !kh.value && typeEl.value === 'gateway') kh.value = 'Ocp-Apim-Subscription-Key';
      _llmUpdateVisibility();
    });
  }

  // Focus the name field
  const nameInput = document.getElementById('llm-name-input');
  if (nameInput) nameInput.focus();
}

function _hideLlmForm() {
  _llmFormMode = 'hidden';
  _llmEditingId = null;
  const form = document.getElementById('llm-edit-form');
  if (form) form.remove();
}

function showLlmProfileForm() {
  _showLlmForm('create');
}
function hideLlmProfileForm() {
  _hideLlmForm();
}
function editLlmProfile(id) {
  const p = _llmProfiles.find((x) => x.id === id);
  if (p) _showLlmForm('edit', p);
}
async function activateLlmProfile(id) {
  if (!id || _llmBusy) return;
  _llmBusy = true;
  // Disable all card buttons to prevent double-clicks
  document.querySelectorAll('.llm-card-btn').forEach((b) => (b.disabled = true));
  try {
    const res = await fetch('/api/config/llm/profiles/' + id + '/activate', { method: 'POST' });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      _llmShowCardError(d.detail || 'Activation failed');
    }
    await loadLlmProfiles();
  } catch (err) {
    _llmShowCardError('Activation failed: ' + err.message);
  } finally {
    _llmBusy = false;
    document.querySelectorAll('.llm-card-btn').forEach((b) => (b.disabled = false));
  }
}
async function deleteLlmProfile(id) {
  if (!id || _llmBusy) return;
  const p = _llmProfiles.find((x) => x.id === id);
  const name = p ? p.name || 'this provider' : 'this provider';
  if (!confirm('Delete "' + name + '"? This cannot be undone.')) return;
  _llmBusy = true;
  document.querySelectorAll('.llm-card-btn').forEach((b) => (b.disabled = true));
  try {
    const res = await fetch('/api/config/llm/profiles/' + id, { method: 'DELETE' });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      _llmShowCardError(d.detail || 'Delete failed');
      return;
    }
    await loadLlmProfiles();
  } catch (err) {
    _llmShowCardError(err.message);
  } finally {
    _llmBusy = false;
    document.querySelectorAll('.llm-card-btn').forEach((b) => (b.disabled = false));
  }
}

async function _reloadLlmConfigFromDisk() {
  const btn = document.getElementById('llm-reload-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Reloading…';
  }
  try {
    const res = await fetch('/api/config/reload-llm', { method: 'POST' });
    const d = await res.json();
    if (!res.ok) {
      _llmShowCardError(d.detail || 'Reload failed');
      return;
    }
    await loadLlmProfiles();
    _llmShowCardError('');
    if (btn) {
      btn.textContent = '✓ Reloaded';
      setTimeout(() => {
        if (btn) btn.textContent = 'Reload from disk';
      }, 2000);
    }
  } catch (err) {
    _llmShowCardError(err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

(function _initLlmInlineForm() {
  const reloadBtn = document.getElementById('llm-reload-btn');
  const addBtn = document.getElementById('llm-add-profile-btn');
  if (reloadBtn) reloadBtn.addEventListener('click', _reloadLlmConfigFromDisk);
  if (addBtn) addBtn.addEventListener('click', () => _showLlmForm('create'));
  // Delegated card actions (activate / edit / delete)
  document.getElementById('llm-profile-cards')?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const card = btn.closest('.llm-profile-card');
    if (!card) return;
    const id = card.dataset.profileId;
    const action = btn.dataset.action;
    if (action === 'activate') activateLlmProfile(id);
    else if (action === 'edit') editLlmProfile(id);
    else if (action === 'delete') deleteLlmProfile(id);
  });
})();

// ── Replace native <select> with custom portal dropdown ──────────────────────
// Keeps the hidden <select> as the value store so all existing .value reads work.
function _replaceSelectWithDropdown(selectEl) {
  if (!selectEl || !window.buildDropdown) return;
  var opts = Array.from(selectEl.options).map(function (o) {
    return { value: o.value, label: o.text };
  });
  var drop = window.buildDropdown(opts, selectEl.value, function (val) {
    selectEl.value = val;
    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
  });
  selectEl.style.display = 'none';
  selectEl.parentNode.insertBefore(drop.el, selectEl);
  // Keep dropdown in sync when value is set programmatically (e.g. _llmFillForm)
  Object.defineProperty(selectEl, 'value', {
    get: function () {
      return this._val !== undefined ? this._val : this.options[this.selectedIndex]?.value || '';
    },
    set: function (v) {
      this._val = v;
      drop.setValue(v);
      var idx = Array.from(this.options).findIndex(function (o) {
        return o.value === v;
      });
      if (idx >= 0) this.selectedIndex = idx;
    },
    configurable: true,
  });
}

// mcp_add_modal.js loads before app.js so window.buildDropdown is already defined here
_replaceSelectWithDropdown(document.getElementById('llm-type'));
_replaceSelectWithDropdown(document.getElementById('persona-select'));

// ── Backward-compat shim: checkApiKey now just loads profiles ──
async function checkApiKey() {
  await loadLlmProfiles();
}

// ── Model status (context limit only) ───────────────────────
async function checkModelStatus() {
  try {
    const res = await fetch('/api/config/model/status');
    const d = await res.json();
    if (d.context_window) _contextLimit = d.context_window;
  } catch {
    /* non-fatal */
  }
}

/* ── Persona Management ────────────────────────────────── */
const personaSelect = document.getElementById('persona-select');
const personaSub = document.getElementById('persona-sub');
const personaEditBtn = document.getElementById('persona-edit-btn');
const personaNewBtn = document.getElementById('persona-new-btn');
const personaDeleteBtn = document.getElementById('persona-delete-btn');
const personaEditor = document.getElementById('persona-editor');
const personaNameInput = document.getElementById('persona-name-input');
const personaPromptInput = document.getElementById('persona-prompt-input');
const personaSaveBtn = document.getElementById('persona-save-btn');
const personaCancelBtn = document.getElementById('persona-cancel-btn');
const personaMsg = document.getElementById('persona-msg');

let _personaCache = {};
let _personaEditing = null; // null = closed, 'new' = creating, or persona id

async function loadPersonas() {
  try {
    const res = await fetch('/api/config/personas');
    const d = await res.json();
    _personaCache = d.personas || {};
    const active = d.active || '';

    // Rebuild select options using DOM methods (no innerHTML for safety)
    while (personaSelect.options.length > 0) personaSelect.remove(0);
    const noneOpt = document.createElement('option');
    noneOpt.value = '';
    noneOpt.textContent = 'None (default)';
    personaSelect.appendChild(noneOpt);

    Object.entries(_personaCache).forEach(([id, p]) => {
      const opt = document.createElement('option');
      opt.value = id;
      opt.textContent = p.name;
      if (id === active) opt.selected = true;
      personaSelect.appendChild(opt);
    });

    personaSub.textContent =
      active && _personaCache[active] ? _personaCache[active].name : 'Not set';

    personaEditBtn.disabled = !active;
    personaDeleteBtn.disabled = !active;
  } catch {
    personaSub.textContent = 'Error loading';
  }
}

personaSelect.addEventListener('change', async () => {
  const id = personaSelect.value;
  try {
    await fetch('/api/config/active-persona', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    });
    personaSub.textContent = id && _personaCache[id] ? _personaCache[id].name : 'Not set';
    personaEditBtn.disabled = !id;
    personaDeleteBtn.disabled = !id;
    _closePersonaEditor();
    _showConnectivityToast(
      id ? 'Persona: ' + _personaCache[id].name : 'Persona cleared',
      'success',
    );
  } catch {}
});

function _openPersonaEditor(mode, id) {
  _personaEditing = mode === 'new' ? 'new' : id;
  personaEditor.classList.remove('hidden');
  if (mode === 'new') {
    personaNameInput.value = '';
    personaPromptInput.value = '';
    personaNameInput.focus();
  } else {
    const p = _personaCache[id];
    personaNameInput.value = p?.name || '';
    personaPromptInput.value = p?.prompt || '';
    personaPromptInput.focus();
  }
  personaMsg.textContent = '';
}

function _closePersonaEditor() {
  _personaEditing = null;
  personaEditor.classList.add('hidden');
  personaMsg.textContent = '';
}

personaEditBtn.addEventListener('click', () => {
  const id = personaSelect.value;
  if (id) _openPersonaEditor('edit', id);
});

personaNewBtn.addEventListener('click', () => _openPersonaEditor('new', null));
personaCancelBtn.addEventListener('click', _closePersonaEditor);

personaSaveBtn.addEventListener('click', async () => {
  const name = personaNameInput.value.trim();
  const prompt = personaPromptInput.value.trim();
  if (!name) {
    personaMsg.textContent = 'Name is required';
    personaMsg.style.color = 'var(--danger)';
    return;
  }
  // Generate id from name for new personas
  const id =
    _personaEditing === 'new'
      ? name
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-|-$/g, '')
      : _personaEditing;

  personaSaveBtn.disabled = true;
  personaMsg.textContent = 'Saving...';
  personaMsg.style.color = 'var(--text-dim)';
  try {
    const res = await fetch('/api/config/persona', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, name, prompt }),
    });
    if (!res.ok) {
      const d = await res.json();
      personaMsg.textContent = d.detail || 'Failed';
      personaMsg.style.color = 'var(--danger)';
    } else {
      // Also set as active
      await fetch('/api/config/active-persona', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      });
      await loadPersonas();
      personaSelect.value = id;
      _closePersonaEditor();
      _showConnectivityToast('Persona saved: ' + name, 'success');
    }
  } catch (err) {
    personaMsg.textContent = err.message;
    personaMsg.style.color = 'var(--danger)';
  }
  personaSaveBtn.disabled = false;
});

personaDeleteBtn.addEventListener('click', () => {
  const id = personaSelect.value;
  if (!id) return;
  const name = _personaCache[id]?.name || id;
  _showConfirmModal(
    'Delete Persona',
    `Delete persona "${name}"? This cannot be undone.`,
    'Delete',
    async () => {
      try {
        await fetch('/api/config/persona/' + encodeURIComponent(id), { method: 'DELETE' });
        await loadPersonas();
        _closePersonaEditor();
        _showConnectivityToast('Persona deleted', 'info');
      } catch {}
    },
  );
});

// Load on startup
loadPersonas();

// Setup gate — opens Settings drawer on the AI Model tab
gateSaveBtn.addEventListener('click', () => {
  if (typeof window.openSettingsPanel === 'function') {
    window.openSettingsPanel('llm');
  } else {
    document.getElementById('settings-trigger')?.click();
  }
});

// Setup gate is a welcome, not a wall — let the user dismiss it and use the app.
document.getElementById('gate-close-btn')?.addEventListener('click', _dismissSetupGate);
document.getElementById('gate-dismiss-btn')?.addEventListener('click', _dismissSetupGate);
// Allow Escape to dismiss the gate too
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && setupGate && !setupGate.classList.contains('hidden')) {
    _dismissSetupGate();
  }
});

/* ── Budget & Usage Settings ─────────────────────────── */
async function _loadBudgetSettings() {
  const cfg = await fetch('/api/config')
    .then((r) => r.json())
    .catch(() => ({}));
  const q = (id) => document.getElementById(id);
  if (q('cfg-budget-task')) q('cfg-budget-task').value = cfg.token_budget_per_task || '';
  if (q('cfg-budget-daily')) q('cfg-budget-daily').value = cfg.token_budget_daily || '';
  if (q('cfg-cost-in')) q('cfg-cost-in').value = cfg.cost_input_rate || '';
  if (q('cfg-cost-out')) q('cfg-cost-out').value = cfg.cost_output_rate || '';
}

function _initBudgetSettings() {
  const saveBtn = document.getElementById('cfg-budget-save');
  const clearBtn = document.getElementById('cfg-cost-clear');
  if (!saveBtn) return;
  saveBtn.addEventListener('click', async () => {
    const q = (id) => document.getElementById(id);
    await fetch('/api/config', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token_budget_per_task: parseInt(q('cfg-budget-task')?.value || '0') || 0,
        token_budget_daily: parseInt(q('cfg-budget-daily')?.value || '0') || 0,
        cost_input_rate: parseFloat(q('cfg-cost-in')?.value) || null,
        cost_output_rate: parseFloat(q('cfg-cost-out')?.value) || null,
      }),
    });
    const msg = document.getElementById('cfg-budget-msg');
    if (msg) {
      msg.textContent = 'Saved';
      setTimeout(() => {
        msg.textContent = '';
      }, 2000);
    }
  });
  clearBtn?.addEventListener('click', async () => {
    await fetch('/api/config', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cost_input_rate: null, cost_output_rate: null }),
    });
    ['cfg-cost-in', 'cfg-cost-out'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
  });
  _loadBudgetSettings();
}

_initBudgetSettings();

/* ── M365 Auth ───────────────────────────────────────── */
const authDot = document.getElementById('auth-dot');
const authDetail = document.getElementById('auth-detail');
const teamsDot = document.getElementById('teams-dot');
const teamsDetail = document.getElementById('teams-detail');
const tokenInput = document.getElementById('token-input');
const tokenSaveBtn = document.getElementById('token-save-btn');
const tokenCaptureBtn = document.getElementById('token-capture-btn');
const tokenMsg = document.getElementById('token-msg');

// "Paste manually" toggles the textarea
tokenSaveBtn.addEventListener('click', () => {
  const showing = !tokenInput.classList.contains('hidden');
  if (showing) {
    // Submit what's in the textarea
    saveTeamsToken(tokenInput.value.trim());
  } else {
    tokenInput.classList.remove('hidden');
    tokenSaveBtn.textContent = 'Save Token';
    tokenInput.focus();
  }
});

async function saveTeamsToken(token) {
  if (!token) return;
  tokenSaveBtn.disabled = true;
  tokenMsg.textContent = 'Validating…';
  tokenMsg.style.color = 'var(--text-dim)';
  try {
    const res = await fetch('/api/auth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    const d = await res.json();
    if (!res.ok) {
      tokenMsg.textContent = '✗ ' + (d.detail || 'Failed');
      tokenMsg.style.color = 'var(--danger)';
    } else {
      tokenMsg.textContent = `✓ Saved · ${d.expires_in_minutes}m`;
      tokenMsg.style.color = 'var(--success)';
      tokenInput.value = '';
      tokenInput.classList.add('hidden');
      tokenSaveBtn.textContent = 'Paste manually';
      checkAuthStatus();
      checkSkillConnectionStatus();
      setTimeout(() => {
        tokenMsg.textContent = '';
      }, 4000);
    }
  } catch (err) {
    tokenMsg.textContent = '✗ ' + err.message;
    tokenMsg.style.color = 'var(--danger)';
  }
  tokenSaveBtn.disabled = false;
}

let _prevAuthOk = null;
let _prevTeamsOk = null;

async function checkAuthStatus() {
  try {
    const res = await fetch('/api/auth/status');
    const d = await res.json();

    // Microsoft 365 section (OAuth)
    if (!d.authenticated) {
      authDot.className = 'section-status st-err';
      authDetail.textContent = d.expired ? 'Expired — sign in again' : d.reason || 'Not signed in';
    } else {
      const expWarn = !d.has_refresh_token && d.expires_in_minutes < 10;
      authDot.className = expWarn ? 'section-status st-warn' : 'section-status st-ok';
      const user = d.user?.split(',')[0] || '';
      authDetail.textContent = d.has_refresh_token
        ? `Signed in${user ? ' · ' + user : ''}`
        : `Signed in · expires ${d.expires_in_minutes}m`;
    }

    // Teams Chat section (separate token)
    if (d.teams_token_ok) {
      teamsDot.className = 'section-status st-ok';
      teamsDetail.textContent = `Token active · ${d.teams_expires_in_minutes}m remaining`;
    } else {
      teamsDot.className = 'section-status st-err';
      teamsDetail.textContent = 'Token required';
    }

    // Auto-dismiss auth overlay and re-fetch when token comes back online
    const authNowOk = !!d.authenticated;
    const teamsNowOk = !!d.teams_token_ok;
    if (_prevAuthOk === false && authNowOk) {
      if (typeof _dismissAuthOverlay === 'function') _dismissAuthOverlay();
      if (typeof tpState !== 'undefined' && tpState.type === 'email') {
        _clearListCache('email');
        _clearListCache('email_unread');
        if (typeof _fetchEmailList === 'function') _fetchEmailList();
      }
    }
    if (_prevTeamsOk === false && teamsNowOk) {
      if (typeof _dismissAuthOverlay === 'function') _dismissAuthOverlay();
      if (typeof tpState !== 'undefined' && tpState.type === 'teams') {
        _clearListCache('teams');
        if (typeof _fetchTeamsList === 'function') _fetchTeamsList();
      }
      // Resume notification polling after token recovery
      window._teamsNotifBackoff = false;
    }
    _prevAuthOk = authNowOk;
    _prevTeamsOk = teamsNowOk;

    // Render the per-app Web + API dashboard from the structured payload.
    // d.apps (Web/API status dashboard) removed — native panes use SSO sessions.
  } catch {
    authDot.className = 'section-status st-dim';
    authDetail.textContent = 'Unknown';
    teamsDot.className = 'section-status st-dim';
    teamsDetail.textContent = 'Unknown';
  }
  updateSettingsBadges();
}

const _inShell = () => typeof window.gatorShell !== 'undefined' && !!window.gatorShell.isShell;

/* ── OAuth device flow ───────────────────────────────── */
const deviceStartBtn = document.getElementById('device-start-btn');
const deviceMsg = document.getElementById('device-msg');
const deviceCodeBox = document.getElementById('device-code-box');
const deviceUrlEl = document.getElementById('device-url');
const deviceCodeVal = document.getElementById('device-code-value');
let _devicePollTimer = null;

deviceStartBtn.addEventListener('click', async () => {
  deviceStartBtn.disabled = true;
  deviceMsg.textContent = 'Starting…';
  deviceMsg.style.color = 'var(--text-dim)';
  deviceCodeBox.classList.add('hidden');
  try {
    const res = await fetch('/api/auth/device/start', { method: 'POST' });
    const d = await res.json();
    if (!res.ok || !d.ok) throw new Error(d.detail || 'Failed to start sign-in');
    deviceUrlEl.href = d.url;
    deviceUrlEl.textContent = d.url;
    deviceCodeVal.textContent = d.user_code;
    deviceCodeBox.classList.remove('hidden');
    deviceMsg.textContent = '';
    _pollDeviceCode(d.device_code, d.url);
  } catch (err) {
    deviceMsg.textContent = '✗ ' + err.message;
    deviceMsg.style.color = 'var(--danger)';
    deviceStartBtn.disabled = false;
  }
});

function _pollDeviceCode(deviceCode, url) {
  clearInterval(_devicePollTimer);
  _devicePollTimer = setInterval(async () => {
    try {
      const res = await fetch('/api/auth/device/poll', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_code: deviceCode, tenant_id: 'organizations' }),
      });
      const d = await res.json();
      if (d.ok) {
        clearInterval(_devicePollTimer);
        deviceCodeBox.classList.add('hidden');
        deviceMsg.textContent = '✓ Signed in successfully';
        deviceMsg.style.color = 'var(--success)';
        deviceStartBtn.disabled = false;
        deviceStartBtn.textContent = 'Sign in again →';
        checkAuthStatus();
        checkSkillConnectionStatus();
        setTimeout(() => {
          deviceMsg.textContent = '';
        }, 4000);
        if (!settingsDrawer.classList.contains('is-open')) {
          _showConnectivityToast('Microsoft 365 sign-in successful', 'success');
        }
      } else if (!d.pending) {
        clearInterval(_devicePollTimer);
        deviceCodeBox.classList.add('hidden');
        deviceMsg.textContent = '✗ ' + (d.error || 'Sign-in failed');
        deviceMsg.style.color = 'var(--danger)';
        deviceStartBtn.disabled = false;
        if (!settingsDrawer.classList.contains('is-open')) {
          _showConnectivityToast('Microsoft 365 sign-in failed', 'error');
        }
      }
    } catch {
      /* network hiccup, keep polling */
    }
  }, 5000);
}

/* ── Slack OAuth Sign-in ─────────────────────────────── */
const slackDot = document.getElementById('slack-dot');
const slackDetail = document.getElementById('slack-detail');
const slackSigninBtn = document.getElementById('slack-signin-btn');
const slackAuthMsg = document.getElementById('slack-auth-msg');

if (slackSigninBtn)
  slackSigninBtn.addEventListener('click', async () => {
    slackSigninBtn.disabled = true;
    slackAuthMsg.textContent = '';
    try {
      const _inShell = typeof window.gatorShell !== 'undefined' && !!window.gatorShell.isShell;
      const res = await fetch('/api/auth/slack/start');
      const d = await res.json();
      if (!d.url) throw new Error('no auth url');

      if (_inShell && window.gatorShell.slackOAuthOpen) {
        // Shell mode: open a SEPARATE popup window that shares persist:slack, so
        // it reuses the Slack pane's workspace cookie and goes straight to consent
        // (skips the Enterprise-Grid workspace picker). Not the pane — a standalone
        // window — so no pane hijacking or stray tabs. The backend callback server
        // saves the token; we just wait for the popup to finish.
        slackAuthMsg.textContent = 'Approve in the Slack window…';
        slackAuthMsg.style.color = 'var(--text-dim)';
        const result = await window.gatorShell.slackOAuthOpen(d.url);
        slackSigninBtn.disabled = false;
        if (result && result.ok) {
          slackAuthMsg.textContent = 'Connected!';
          slackAuthMsg.style.color = 'var(--success)';
          slackSigninBtn.textContent = 'Reconnect';
          setTimeout(() => {
            slackAuthMsg.textContent = '';
          }, 4000);
        } else {
          slackAuthMsg.textContent = '';
        }
        // Re-check status regardless (covers manual-close after consent).
        setTimeout(() => {
          checkSlackStatus();
          checkSkillConnectionStatus();
        }, 800);
        return;
      }

      // Browser mode (no shell): window.open on Gator's default session; the
      // callback page postMessages 'slack-auth-ok' back to the opener.
      const popup = window.open(d.url, 'slack-auth', 'width=600,height=700');
      const handler = (ev) => {
        if (ev.data && ev.data.type === 'slack-auth-ok') {
          window.removeEventListener('message', handler);
          slackAuthMsg.textContent = 'Connected!';
          slackAuthMsg.style.color = 'var(--success)';
          checkSlackStatus();
          checkSkillConnectionStatus();
          slackSigninBtn.disabled = false;
          slackSigninBtn.textContent = 'Reconnect';
          setTimeout(() => {
            slackAuthMsg.textContent = '';
          }, 4000);
        }
      };
      window.addEventListener('message', handler);
      const poll = setInterval(() => {
        if (popup && popup.closed) {
          clearInterval(poll);
          slackSigninBtn.disabled = false;
          setTimeout(() => {
            checkSlackStatus();
            checkSkillConnectionStatus();
          }, 1000);
        }
      }, 1000);
    } catch (err) {
      slackAuthMsg.textContent = 'Failed to start auth';
      slackAuthMsg.style.color = 'var(--danger)';
      slackSigninBtn.disabled = false;
    }
  });

async function checkSlackStatus() {
  try {
    const res = await fetch('/api/auth/slack/status');
    const d = await res.json();
    if (d.configured) {
      slackDot.className = 'section-status st-ok';
      slackDetail.textContent = `Connected · ${d.team || 'Slack'}`;
      if (slackSigninBtn) slackSigninBtn.textContent = 'Reconnect';
      const skill = SKILL_MAP['slack'];
      if (skill) skill.connected = true;
    } else if (d.error) {
      // Token exists but live check failed — show degraded state, not "not signed in"
      slackDot.className = 'section-status st-warn';
      slackDetail.textContent = 'Signed in · Slack unreachable';
      if (slackSigninBtn) slackSigninBtn.textContent = 'Reconnect';
    } else {
      slackDot.className = 'section-status st-dim';
      slackDetail.textContent = 'Not signed in';
      if (slackSigninBtn) slackSigninBtn.textContent = 'Sign in with Slack \u2192';
    }
  } catch {
    slackDot.className = 'section-status st-dim';
    slackDetail.textContent = 'Not signed in';
  }
}

/* ── Atlassian (Jira + Confluence merged) ── */
const atlassianDot = document.getElementById('atlassian-dot');
const atlassianDetail = document.getElementById('atlassian-detail');
const atlassianEmailInput = document.getElementById('atlassian-email-input');
const atlassianTokenInput = document.getElementById('atlassian-token-input');
const atlassianJiraUrlInput = document.getElementById('atlassian-jira-url-input');
const atlassianConfluenceUrlInput = document.getElementById('atlassian-confluence-url-input');
const atlassianSaveBtn = document.getElementById('atlassian-save-btn');
const atlassianMsg = document.getElementById('atlassian-msg');

// Aliases so SKILL_MAP and updateSettingsBadges keep working
const jiraDot = atlassianDot;
const confluenceDot = atlassianDot;

async function loadAtlassianStatus() {
  try {
    const [jr, cr, cfg] = await Promise.all([
      fetch('/api/config/jira/status').then((r) => r.json()),
      fetch('/api/config/confluence/status').then((r) => r.json()),
      fetch('/api/config').then((r) => r.json()),
    ]);
    const ok = jr.configured && cr.configured;
    atlassianDot.className = 'section-status ' + (ok ? 'st-ok' : 'st-warn');
    atlassianDetail.textContent = ok ? jr.email || cr.email || 'Configured' : 'Not configured';
    // Pre-fill email
    const email = jr.email || cr.email || cfg.jira_email || cfg.confluence_email || '';
    if (email) atlassianEmailInput.value = email;
    // Pre-fill token from stored config (cloud token or PAT)
    const token = cfg.jira_api_token || cfg.jira_pat || cfg.confluence_pat || '';
    if (token) atlassianTokenInput.value = token;
    // Pre-fill URLs
    if (jr.base_url) atlassianJiraUrlInput.value = jr.base_url;
    if (cr.base_url) atlassianConfluenceUrlInput.value = cr.base_url;
  } catch {
    /* non-fatal */
  }
}
loadAtlassianStatus();

atlassianSaveBtn.addEventListener('click', async () => {
  const email = atlassianEmailInput.value.trim();
  const token = atlassianTokenInput.value.trim();
  const jiraUrl = atlassianJiraUrlInput.value.trim();
  const confUrl = atlassianConfluenceUrlInput.value.trim();
  if (!email || !token) {
    atlassianMsg.textContent = 'Email and token are required.';
    return;
  }
  atlassianMsg.textContent = 'Saving…';
  try {
    const [jr, cr] = await Promise.all([
      fetch('/api/config/jira', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pat: token, base_url: jiraUrl, email }),
      }).then((r) => r.json()),
      fetch('/api/config/confluence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, base_url: confUrl, email }),
      }).then((r) => r.json()),
    ]);
    if (jr.ok && cr.ok) {
      atlassianMsg.textContent = 'Saved.';
      atlassianDot.className = 'section-status st-ok';
      atlassianDetail.textContent = email;
      setTimeout(() => {
        atlassianMsg.textContent = '';
      }, 3000);
    } else {
      atlassianMsg.textContent = jr.error || cr.error || 'Save failed.';
    }
  } catch (err) {
    atlassianMsg.textContent = 'Error: ' + err.message;
  }
});

/* ── GitHub ────────────────────────────────────────────── */
const githubDot = document.getElementById('github-dot');
const githubDetail = document.getElementById('github-detail');
const githubUrlInput = document.getElementById('github-url-input');
const githubTokenInput = document.getElementById('github-token-input');
const githubSaveBtn = document.getElementById('github-save-btn');
const githubMsg = document.getElementById('github-msg');

if (githubSaveBtn) githubSaveBtn.addEventListener('click', () => saveGithub());

async function saveGithub() {
  let url = githubUrlInput.value.trim().replace(/\/$/, '');
  if (url && !/^[a-z][a-z0-9+.-]*:\/\//i.test(url)) url = `https://${url}`;
  const token = githubTokenInput.value.trim();
  if (!url) {
    githubMsg.textContent = 'GitHub URL is required';
    githubMsg.style.color = 'var(--danger)';
    return;
  }
  if (!token) {
    githubMsg.textContent = 'Access token is required';
    githubMsg.style.color = 'var(--danger)';
    return;
  }
  githubSaveBtn.disabled = true;
  githubMsg.textContent = 'Verifying…';
  githubMsg.style.color = 'var(--text-sub)';
  try {
    const res = await fetch('/api/config/github', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, token }),
    });
    const d = await res.json();
    if (!res.ok) {
      githubMsg.textContent = '✗ ' + (d.detail || 'Failed');
      githubMsg.style.color = 'var(--danger)';
    } else {
      githubMsg.textContent = `✓ Connected as ${d.user}`;
      githubMsg.style.color = 'var(--success)';
      if (window.gatorShell && window.gatorShell.refreshGitHub) {
        window.gatorShell.refreshGitHub(d.base_url);
      }
      checkGithubStatus();
      checkSkillConnectionStatus();
      setTimeout(() => {
        githubMsg.textContent = '';
      }, 5000);
    }
  } catch (err) {
    githubMsg.textContent = '✗ ' + err.message;
    githubMsg.style.color = 'var(--danger)';
  }
  githubSaveBtn.disabled = false;
}

let githubOk = false;

async function checkGithubStatus() {
  try {
    const [res, cfgRes] = await Promise.all([
      fetch('/api/config/github/status'),
      fetch('/api/config'),
    ]);
    const d = await res.json();
    const cfg = await cfgRes.json();
    if (d.configured && !d.error) {
      githubDot.className = 'section-status st-ok';
      githubDetail.textContent = `Connected as ${d.user}`;
      githubOk = true;
      const s = SKILL_MAP['github'];
      if (s) s.connected = true;
    } else {
      githubDot.className = 'section-status st-err';
      githubDetail.textContent = 'Not configured';
      githubOk = false;
    }
    const token = cfg.github_token || '';
    if (token && githubTokenInput) githubTokenInput.value = token;
    const url = cfg.github_base_url || '';
    if (url && githubUrlInput) githubUrlInput.value = url;
  } catch {
    githubDot.className = 'section-status st-dim';
    githubDetail.textContent = 'Unknown';
    githubOk = false;
  }
}

checkGithubStatus();

/* ── Slack MCP Username ────── */
const usernameInput = document.getElementById('username-input');
const usernameSaveBtn = document.getElementById('username-save-btn');
const usernameMsg = document.getElementById('username-msg');
const usernameDot = document.getElementById('username-dot');
const usernameSub = document.getElementById('username-sub');

if (usernameSaveBtn) usernameSaveBtn.addEventListener('click', () => saveUsername());
if (usernameInput)
  usernameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') usernameSaveBtn.click();
  });

async function saveUsername() {
  const name = usernameInput.value.trim();
  if (!name) {
    usernameMsg.textContent = 'Username is required';
    usernameMsg.style.color = 'var(--danger)';
    return;
  }
  usernameSaveBtn.disabled = true;
  usernameMsg.textContent = 'Saving…';
  usernameMsg.style.color = 'var(--text-sub)';
  try {
    const res = await fetch('/api/config/username', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: name }),
    });
    const d = await res.json();
    if (!res.ok) {
      usernameMsg.textContent = '✗ ' + (d.detail || 'Failed');
      usernameMsg.style.color = 'var(--danger)';
    } else {
      usernameMsg.textContent = '✓ Saved';
      usernameMsg.style.color = 'var(--success)';
      checkUsernameStatus();
      setTimeout(() => {
        usernameMsg.textContent = '';
      }, 5000);
    }
  } catch (err) {
    usernameMsg.textContent = '✗ ' + err.message;
    usernameMsg.style.color = 'var(--danger)';
  }
  usernameSaveBtn.disabled = false;
}

async function checkUsernameStatus() {
  try {
    const res = await fetch('/api/config/username/status');
    const d = await res.json();
    if (d.configured) {
      if (usernameDot) usernameDot.className = 'section-status st-ok';
      if (usernameSub) usernameSub.textContent = d.username;
      if (usernameInput) usernameInput.value = d.username;
    } else {
      if (usernameDot) usernameDot.className = 'section-status st-err';
      if (usernameSub) usernameSub.textContent = 'Not configured';
    }
  } catch {
    if (usernameDot) usernameDot.className = 'section-status st-dim';
    if (usernameSub) usernameSub.textContent = 'Unknown';
  }
}

checkUsernameStatus();

/* ── Teams token auto-capture (CDP via Edge) ─────────── */
const capInline = document.getElementById('cap-inline');
const capInlineSteps = document.getElementById('cap-inline-steps');
const tokenControls = document.getElementById('token-controls');

function _capStart() {
  capInlineSteps.innerHTML = '';
  capInline.querySelectorAll('.cap-inline-result').forEach((el) => el.remove());
  const spinner = capInline.querySelector('.cap-inline-spinner');
  if (spinner) spinner.classList.remove('done');
  tokenControls.classList.add('hidden');
  capInline.classList.remove('hidden');
}

function _capEnd(ok, msg) {
  // Stop spinner
  const spinner = capInline.querySelector('.cap-inline-spinner');
  if (spinner) spinner.classList.add('done');
  // Mark all steps done
  capInlineSteps.querySelectorAll('.cap-inline-step').forEach((el) => el.classList.add('done'));
  // Show result line
  const result = document.createElement('div');
  result.className = 'cap-inline-result ' + (ok ? 'success' : 'error');
  result.textContent = msg;
  capInline.appendChild(result);
  // On success: restore controls after a moment
  if (ok) {
    setTimeout(() => {
      capInline.classList.add('hidden');
      tokenControls.classList.remove('hidden');
    }, 2500);
  } else {
    // On error: restore controls immediately so user can retry
    tokenControls.classList.remove('hidden');
  }
}

function _capAddStep(text) {
  const row = document.createElement('div');
  row.className = 'cap-inline-step';
  row.textContent = text;
  capInlineSteps.appendChild(row);
  // Mark all but the last step done
  const all = capInlineSteps.querySelectorAll('.cap-inline-step');
  all.forEach((el, i) => {
    if (i < all.length - 1) el.classList.add('done');
  });
}

let _captureES = null; // hoisted so capture survives drawer close

tokenCaptureBtn.addEventListener('click', () => {
  tokenCaptureBtn.disabled = true;
  tokenSaveBtn.disabled = true;
  tokenMsg.textContent = '';
  _capStart();
  _capAddStep('Opening Outlook in Edge…');

  if (_captureES) {
    _captureES.close();
    _captureES = null;
  }
  const es = new EventSource('/api/auth/teams/capture/stream');
  _captureES = es;

  es.addEventListener('status', (e) => {
    _capAddStep(JSON.parse(e.data));
  });

  es.addEventListener('result', (e) => {
    es.close();
    _captureES = null;
    const d = JSON.parse(e.data);
    _capEnd(true, `✓ Captured · ${d.expires_in_minutes}m remaining`);
    checkAuthStatus();
    checkSkillConnectionStatus();
    tokenCaptureBtn.disabled = false;
    tokenSaveBtn.disabled = false;
    // If drawer is closed, show a toast so user knows it completed
    if (!settingsDrawer.classList.contains('is-open')) {
      _showConnectivityToast('Teams token captured successfully', 'success');
    }
  });

  es.addEventListener('error', (e) => {
    es.close();
    _captureES = null;
    const msg = e.data ? JSON.parse(e.data) : 'Capture failed — try again.';
    _capEnd(false, '✗ ' + msg);
    tokenCaptureBtn.disabled = false;
    tokenSaveBtn.disabled = false;
    if (!settingsDrawer.classList.contains('is-open')) {
      _showConnectivityToast('Teams token capture failed', 'error');
    }
  });

  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) return;
    es.close();
    _captureES = null;
    _capEnd(false, '✗ Connection lost — try again.');
    tokenCaptureBtn.disabled = false;
    tokenSaveBtn.disabled = false;
  };
});

/* ── Settings badges (status dots on trigger) ────────── */
function updateSettingsBadges() {
  const badges = document.getElementById('settings-badges');
  const apikeyOk = apikeyDot.classList.contains('st-ok');
  const authOk = authDot.classList.contains('st-ok');
  const authWarn = authDot.classList.contains('st-warn');
  const hasErr = !apikeyOk || (!authOk && !authWarn);
  const hasWarn = !hasErr && authWarn;
  if (hasErr) badges.innerHTML = '<div class="badge-dot badge-err"></div>';
  else if (hasWarn) badges.innerHTML = '<div class="badge-dot badge-warn"></div>';
  else badges.innerHTML = '';
}

/* ── Server Control ──────────────────────────────────── */
const serverDot = document.getElementById('server-dot');
const serverLabel = document.getElementById('server-label');
const restartBtn = document.getElementById('restart-btn');
const stopBtn = document.getElementById('stop-btn');
const startBtn = document.getElementById('start-btn');
const reconnectOverlay = document.getElementById('reconnect-overlay');
const reconnectMsg = document.getElementById('reconnect-msg');
const reconnectSub = document.getElementById('reconnect-sub');

const WATCHDOG = 'http://localhost:8001';

function setServerRunning(running) {
  serverDot.className = 'section-status ' + (running ? 'st-ok' : 'st-err');
  serverLabel.textContent = running ? 'Running' : 'Stopped';
  restartBtn.disabled = !running;
  stopBtn.disabled = !running;
  startBtn.classList.toggle('hidden', running);
}

async function watchdogCmd(cmd) {
  try {
    const res = await fetch(`${WATCHDOG}/${cmd}`, { method: 'POST' });
    return await res.json();
  } catch {
    return { ok: false };
  }
}

async function waitForServer() {
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    reconnectSub.textContent = `Reconnecting${'.'.repeat((i % 3) + 1)}`;
    try {
      const res = await fetch('/health', { signal: AbortSignal.timeout(2000) });
      if (res.ok) {
        window.location.reload();
        return;
      }
    } catch {}
  }
  reconnectOverlay.classList.add('hidden');
  setServerRunning(false);
}

async function checkWatchdog() {
  // Try watchdog first (installed mode)
  try {
    const res = await fetch(`${WATCHDOG}/status`, { signal: AbortSignal.timeout(2000) });
    const d = await res.json();
    if (d.running) {
      setServerRunning(true);
      return;
    }
  } catch {}

  // No watchdog or watchdog says stopped — but if we can load this page, the server IS running
  serverDot.className = 'section-status st-ok';
  serverLabel.textContent = 'Running';
  restartBtn.disabled = true;
  stopBtn.disabled = true;
}

restartBtn.addEventListener('click', () => {
  _showConfirmModal(
    'Restart Server',
    'The page will reload automatically once the server is back up.',
    'Restart',
    async () => {
      reconnectMsg.textContent = 'Restarting server…';
      reconnectSub.textContent = 'Please wait';
      reconnectOverlay.classList.remove('hidden');
      closeDrawer();
      await watchdogCmd('restart');
      await new Promise((r) => setTimeout(r, 2000));
      await waitForServer();
    },
  );
});

stopBtn.addEventListener('click', () => {
  _showConfirmModal(
    'Stop Server',
    'The server will stop running. You can restart it from this panel.',
    'Stop',
    async () => {
      await watchdogCmd('stop');
      reconnectMsg.textContent = 'Server stopped';
      reconnectSub.textContent = 'Click Start to bring it back up';
      reconnectOverlay.classList.remove('hidden');
      closeDrawer();
      setServerRunning(false);
    },
  );
});

startBtn.addEventListener('click', async () => {
  startBtn.disabled = true;
  reconnectMsg.textContent = 'Starting server…';
  reconnectSub.textContent = 'Connecting';
  startBtn.classList.add('hidden');
  await watchdogCmd('start');
  await new Promise((r) => setTimeout(r, 2000));
  await waitForServer();
});

/* ── Status (pip + wordmark) ─────────────────────────── */
const _appNameEl = document.querySelector('.app-name');
const _logoPip = document.getElementById('logo-pip');

function setStatus(state) {
  const busy = state === 'busy';
  if (_appNameEl) {
    _appNameEl.textContent = busy ? 'Working…' : 'AI Gator';
    _appNameEl.classList.toggle('is-busy', busy);
  }
  if (_logoPip) _logoPip.classList.toggle('is-busy', busy);
}

/* ── Chat ────────────────────────────────────────────── */
const messages = document.getElementById('messages');
const form = document.getElementById('chat-form');
const input = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');

let history = [];

const _COMPACTION_ICON_SVG =
  '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8"/><line x1="10" y1="12" x2="14" y2="12"/></svg>';

// Builds the "earlier messages summarized" seam marker — collapsed by
// default; click reveals the actual summary text so a history rewrite is
// inspectable instead of silent.
function _buildCompactionMarker(turnCount, summaryText) {
  const wrap = document.createElement('div');
  wrap.className = 'compaction-marker';
  const n = turnCount || 0;
  wrap.innerHTML =
    `<button type="button" class="compaction-marker-row">` +
    `<span class="compaction-marker-icon">${_COMPACTION_ICON_SVG}</span>` +
    `<span class="compaction-marker-text">Earlier messages summarized · ${n} turn${n === 1 ? '' : 's'}</span>` +
    `<span class="compaction-marker-chevron">▾</span></button>` +
    `<div class="compaction-marker-detail" hidden></div>`;
  wrap.querySelector('.compaction-marker-detail').textContent = summaryText || '';
  wrap.querySelector('.compaction-marker-row').addEventListener('click', () => {
    const expanded = wrap.classList.toggle('expanded');
    wrap.querySelector('.compaction-marker-detail').hidden = !expanded;
  });
  return wrap;
}

_initTabSystem();

// Delegated handler: open local file paths in default OS app
messages.addEventListener('click', (e) => {
  const btn = e.target.closest('.file-path-btn');
  if (!btn) return;
  const path = btn.dataset.path;
  if (!path) return;
  fetch('/api/open-file', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
    .then((r) => r.json())
    .then((d) => {
      if (d.ok) return;
      // Never leave a click feeling dead — surface a calm, specific nudge.
      console.warn('[open-file] failed:', d.message);
      const note =
        d.reason === 'not_found'
          ? "That file isn't there anymore. Here's where it was: " + path
          : d.reason === 'blocked'
            ? "This file type can't be opened from here. You'll find it at: " + path
            : "Couldn't open that automatically. You'll find it at: " + path;
      _showConnectivityToast(note, 'info');
    })
    .catch(() => {
      _showConnectivityToast(
        "Couldn't open that automatically. You'll find it at: " + path,
        'info',
      );
    });
});

/* ── Contenteditable helpers ─────────────────────────── */
function _isTriggerBoundary(ch) {
  return ch === undefined || ch === ' ' || ch === '\u00A0' || ch === '\n';
}

function _getNodeInputText(node) {
  let text = '';
  node.childNodes.forEach((child) => {
    if (child.nodeName === 'BR') {
      text += '\n';
      return;
    }

    const isBlock = child.nodeName === 'DIV' || child.nodeName === 'P';
    if (isBlock && text && !text.endsWith('\n')) text += '\n';

    if (child.nodeType === Node.TEXT_NODE) {
      text += child.textContent;
    } else if (child.classList?.contains('inline-chip')) {
      // Inline chips — use stored trigger prefix so /skill chips don't re-trigger @
      if (child.classList.contains('chip-channel')) {
        // Channel chips use #channelName so the AI sees the channel reference in text
        const channelLabel = child.dataset.channelName || '';
        text += channelLabel ? `#${channelLabel}` : ' ';
      } else {
        const label = child.dataset.personName || child.dataset.skillId || '';
        const prefix = child.dataset.triggerPrefix || '@';
        text += label ? `${prefix}${label}` : ' ';
      }
    } else if (child.dataset?.filePath) {
      // File picker chips — include full path
      text += `[File: ${child.dataset.filePath}]`;
    } else if (child.classList?.contains('pin-ref-chip')) {
      // Pin reference chips — include source and ID so the agent can resolve them.
      // Format: [Pin: source:id] (e.g. [Pin: slack:C06R5U37KBK:1783978133.468829])
      const source = child.dataset.pinSource || '';
      const id = child.dataset.pinId || '';
      const label = child.textContent?.replace(/\s*✕\s*$/, '').trim() || '';
      if (source && id) {
        text += `[Pin: ${source}:${id}]`;
      } else {
        text += label ? `[${label}]` : ' ';
      }
    } else {
      text += _getNodeInputText(child);
    }

    if (isBlock && text && !text.endsWith('\n')) text += '\n';
  });
  return text;
}

function _getInputText() {
  // Extract plain text from contenteditable, preserving chips and line boundaries.
  return _getNodeInputText(input).replace(/\n$/, '');
}

function _cleanShareableChipText(text) {
  return String(text || '')
    .replace(/\u00D7/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function _sourceLabel(source) {
  return String(source || '')
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function _calendarPinMeta(meta = {}) {
  if (!meta) return '';
  const start = meta.start ? new Date(meta.start) : null;
  const startText =
    start && !Number.isNaN(start.valueOf())
      ? start.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
      : '';
  const location = meta.location || '';
  return [startText, location].filter(Boolean).join(' · ');
}

function _closestElement(node) {
  return node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
}

function _serializeShareableNodeText(node) {
  let text = '';
  node.childNodes.forEach((child) => {
    if (child.nodeName === 'BR') {
      text += '\n';
      return;
    }

    const isBlock = child.nodeName === 'DIV' || child.nodeName === 'P';
    if (isBlock && text && !text.endsWith('\n')) text += '\n';

    if (child.nodeType === Node.TEXT_NODE) {
      text += child.textContent;
    } else if (child.dataset?.filePath) {
      const displayName = child.dataset.fileName || child.dataset.filePath.split(/[/\\]/).pop();
      text += `[File: ${displayName}]`;
    } else if (child.classList?.contains('pin-ref-chip')) {
      const label = _cleanShareableChipText(child.textContent);
      const source = _sourceLabel(child.dataset.pinSource);
      text += source ? `[Pinned: ${source} - ${label}]` : `[Pinned: ${label}]`;
    } else if (child.classList?.contains('inline-chip')) {
      if (child.classList.contains('chip-person')) {
        const label = child.dataset.personName || _cleanShareableChipText(child.textContent);
        text += label ? `@${label.replace(/^@/, '')}` : '';
      } else if (child.classList.contains('chip-channel')) {
        const label = child.dataset.channelName || _cleanShareableChipText(child.textContent);
        text += label ? `#${label.replace(/^#/, '')}` : '';
      } else if (child.dataset.skillId) {
        const skill = SKILL_MAP[child.dataset.skillId];
        text += `@${skill?.chipAlias || child.dataset.skillId}`;
      } else {
        text += _cleanShareableChipText(child.textContent);
      }
    } else if (child.classList?.contains('chat-chip')) {
      text += _cleanShareableChipText(child.textContent);
    } else if (child.nodeType === Node.ELEMENT_NODE) {
      // Partially-selected chip or unknown element -- emit cleaned text, strip button noise
      const cleaned = _cleanShareableChipText(child.textContent);
      text += cleaned ? cleaned : _serializeShareableNodeText(child);
    } else {
      text += _serializeShareableNodeText(child);
    }

    if (isBlock && text && !text.endsWith('\n')) text += '\n';
  });
  return text;
}

function _serializeShareableSelection() {
  const sel = window.getSelection();
  if (!sel.rangeCount) return '';
  const range = sel.getRangeAt(0);
  return _serializeShareableNodeText(range.cloneContents()).replace(/\n$/, '');
}

// Escape a string for use inside an HTML double-quoted attribute value.
function _escAttr(t) {
  return String(t == null ? '' : t)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// Emit a single marked chip span carrying just the data needed to rebuild it.
// The data-gator-chip marker is what gates reconstruction on paste — only
// markup WE wrote is ever turned back into a chip (forged @mentions from
// arbitrary pasted HTML stay inert plain text).
function _shareableChipHtml(child) {
  const label = _cleanShareableChipText(child.textContent);
  if (child.classList?.contains('chip-person')) {
    return `<span data-gator-chip="person" data-person-name="${_escAttr(child.dataset.personName || label.replace(/^@/, ''))}" data-person-email="${_escAttr(child.dataset.personEmail || '')}">${escapeHtml(label)}</span>`;
  }
  if (child.classList?.contains('chip-channel')) {
    return `<span data-gator-chip="channel" data-channel-name="${_escAttr(child.dataset.channelName || label.replace(/^#/, ''))}" data-channel-id="${_escAttr(child.dataset.channelId || '')}" data-chat-id="${_escAttr(child.dataset.chatId || '')}" data-team-name="${_escAttr(child.dataset.teamName || '')}" data-channel-type="${_escAttr(child.dataset.channelType || '')}">${escapeHtml(label)}</span>`;
  }
  if (child.dataset?.skillId) {
    return `<span data-gator-chip="skill" data-skill-id="${_escAttr(child.dataset.skillId)}" data-trigger-prefix="${_escAttr(child.dataset.triggerPrefix || '/')}">${escapeHtml(label)}</span>`;
  }
  return escapeHtml(label);
}

// Build an HTML representation of a node tree that preserves Gator chips as
// marked spans. Non-chip content is escaped plain text + <br> for line breaks.
function _serializeShareableNodeHtml(node) {
  let html = '';
  node.childNodes.forEach((child) => {
    if (child.nodeName === 'BR') {
      html += '<br>';
      return;
    }
    const isBlock = child.nodeName === 'DIV' || child.nodeName === 'P';
    if (isBlock && html && !html.endsWith('<br>')) html += '<br>';

    if (child.nodeType === Node.TEXT_NODE) {
      html += escapeHtml(child.textContent);
    } else if (child.dataset?.filePath) {
      // File chips are tied to an upload lifecycle — keep them as plain-text tokens.
      const displayName = child.dataset.fileName || child.dataset.filePath.split(/[/\\]/).pop();
      html += escapeHtml(`[File: ${displayName}]`);
    } else if (child.classList?.contains('pin-ref-chip')) {
      const label = _cleanShareableChipText(child.textContent);
      const source = _sourceLabel(child.dataset.pinSource);
      html += escapeHtml(source ? `[Pinned: ${source} - ${label}]` : `[Pinned: ${label}]`);
    } else if (child.classList?.contains('inline-chip') || child.classList?.contains('chat-chip')) {
      html += _shareableChipHtml(child);
    } else if (child.nodeType === Node.ELEMENT_NODE) {
      const cleaned = _cleanShareableChipText(child.textContent);
      html += cleaned ? escapeHtml(cleaned) : _serializeShareableNodeHtml(child);
    }

    if (isBlock && html && !html.endsWith('<br>')) html += '<br>';
  });
  return html;
}

function _serializeShareableSelectionHtml() {
  const sel = window.getSelection();
  if (!sel.rangeCount) return '';
  const range = sel.getRangeAt(0);
  return _serializeShareableNodeHtml(range.cloneContents()).replace(/(<br>)+$/, '');
}

function _selectionTouches(el) {
  const sel = window.getSelection();
  if (!sel.rangeCount || !el) return false;
  const range = sel.getRangeAt(0);
  return (
    el.contains(range.commonAncestorContainer) ||
    el.contains(sel.anchorNode) ||
    el.contains(sel.focusNode)
  );
}

function _shareablePromptContextPrefix(selectedText) {
  if (!_selectionTouches(input)) return '';
  const selected = selectedText.trim();
  const fullInput = _serializeShareableNodeText(input).replace(/\n$/, '').trim();
  if (fullInput && selected !== fullInput) return '';
  const chips = _serializeShareableNodeText(document.getElementById('chat-chip-row')).trim();
  return chips;
}

function _writeShareableCopy(e, text, html) {
  const normalized = String(text || '')
    .replace(/\s+\n/g, '\n')
    .replace(/\n\s+/g, '\n')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
  if (!normalized) return false;
  e.preventDefault();
  e.clipboardData?.setData('text/plain', normalized);
  // Also write a chip-preserving HTML representation (only when chips are
  // present) so an in-app paste can reconstruct chips. External apps still
  // get clean text/plain; ones that read text/html see escaped text + chip
  // labels with our marker attribute (inert anywhere but our paste handler).
  if (html && /data-gator-chip=/.test(html)) {
    try {
      e.clipboardData?.setData('text/html', html);
    } catch (_) {}
  }
  return true;
}

function _getInputTextBeforeCursor() {
  const sel = window.getSelection();
  if (!sel.rangeCount || !input.contains(sel.anchorNode)) return _getInputText();

  const range = sel.getRangeAt(0).cloneRange();
  range.selectNodeContents(input);
  range.setEnd(sel.anchorNode, sel.anchorOffset);
  return _getNodeInputText(range.cloneContents()).replace(/\n$/, '');
}

function _findTriggerTextNode(trigger) {
  const sel = window.getSelection();
  const range = sel.rangeCount && input.contains(sel.anchorNode) ? sel.getRangeAt(0) : null;
  const walker = document.createTreeWalker(input, NodeFilter.SHOW_TEXT);
  let match = null;
  while (walker.nextNode()) {
    const node = walker.currentNode;
    let text = node.textContent;

    if (range) {
      if (range.startContainer === node) {
        text = text.slice(0, range.startOffset);
      } else {
        const nodeRange = document.createRange();
        nodeRange.selectNodeContents(node);
        if (nodeRange.compareBoundaryPoints(Range.END_TO_END, range) > 0) continue;
      }
    }

    const idx = text.lastIndexOf(trigger);
    if (idx === -1) continue;
    if (!_isTriggerBoundary(text[idx - 1])) continue;
    match = { node, idx };
  }
  return match;
}

function _insertChipAtCursor(chipEl) {
  const sel = window.getSelection();
  if (sel.rangeCount) {
    const range = sel.getRangeAt(0);
    range.deleteContents();
    range.insertNode(chipEl);
    // Add a space after chip and move cursor there
    const space = document.createTextNode('\u00A0');
    chipEl.after(space);
    range.setStartAfter(space);
    range.setEndAfter(space);
    sel.removeAllRanges();
    sel.addRange(range);
  } else {
    input.appendChild(chipEl);
    input.appendChild(document.createTextNode('\u00A0'));
  }
  input.focus();
}

function _createInlineChip(type, label, data) {
  const chip = document.createElement('span');
  chip.contentEditable = 'false';
  const skill = type === 'chip-skill' && data?.skillId ? SKILL_MAP[data.skillId] : null;
  const skillClass = skill?.chipClass || '';
  chip.className = 'inline-chip ' + type + (skillClass ? ' ' + skillClass : '');
  Object.entries(data || {}).forEach(([k, v]) => (chip.dataset[k] = v));
  // For skill chips, include the skill icon for visual consistency with the chip bar
  const iconHtml = skill?.icon ? `<span class="inline-chip-icon">${skill.icon}</span>` : '';
  chip.innerHTML = `${iconHtml}${escapeHtml(label)} <span class="chip-remove">&times;</span>`;
  chip.querySelector('.chip-remove').addEventListener('click', (e) => {
    e.stopPropagation();
    chip.remove();
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  return chip;
}

function _getInlineChips() {
  return [...input.querySelectorAll('.inline-chip')];
}

function _replaceAtHashInInput(trigger, chipFactory) {
  // Walk all text nodes in contenteditable to replace the last active trigger.
  const match = _findTriggerTextNode(trigger);
  if (!match) return;
  const { node, idx } = match;
  const text = node.textContent;
  const before = text.slice(0, idx);
  const triggerRegex =
    trigger === '@'
      ? /^@\w*/
      : trigger === '#'
        ? /^#[\w-]*/
        : trigger === '/'
          ? /^\/[\w-]*/
          : /^\{[^}\n]*/;
  const afterQuery = text.slice(idx).replace(triggerRegex, '');
  const chip = chipFactory();
  const parent = node.parentNode;
  if (before) parent.insertBefore(document.createTextNode(before), node);
  parent.insertBefore(chip, node);
  const space = document.createTextNode('\u00A0' + afterQuery.trimStart());
  parent.insertBefore(space, node);
  parent.removeChild(node);
  // Move cursor after chip
  const sel = window.getSelection();
  const range = document.createRange();
  range.setStartAfter(space);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
  input.focus();
}

// Rebuild a DocumentFragment from chip-preserving clipboard HTML. SECURITY:
// nothing from the pasted markup is inserted directly — we parse it in a detached
// document, then emit ONLY text nodes (.textContent) and freshly-built chip
// elements for spans carrying our data-gator-chip marker. Scripts, styles, event
// handlers, and forged markup never reach the live DOM. Returns {frag, applied}
// where applied lists side effects (active skills / channels) to re-apply.
function _rebuildChipsFromHtml(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const frag = document.createDocumentFragment();
  const applied = { skills: [], channels: [] };

  const walk = (parent) => {
    parent.childNodes.forEach((node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        if (node.textContent) frag.appendChild(document.createTextNode(node.textContent));
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (node.nodeName === 'BR') {
        frag.appendChild(document.createElement('br'));
        return;
      }

      const kind = node.getAttribute && node.getAttribute('data-gator-chip');
      if (kind === 'person') {
        const label =
          (node.textContent || '').trim() || '@' + (node.getAttribute('data-person-name') || '');
        frag.appendChild(
          _createInlineChip('chip-person', label, {
            personName: node.getAttribute('data-person-name') || label.replace(/^@/, ''),
            personEmail: node.getAttribute('data-person-email') || '',
          }),
        );
        frag.appendChild(document.createTextNode(' '));
      } else if (kind === 'channel') {
        const label =
          (node.textContent || '').trim() || '#' + (node.getAttribute('data-channel-name') || '');
        const ctype = node.getAttribute('data-channel-type') || '';
        const isSlack = ctype === 'slack_channel';
        frag.appendChild(
          _createInlineChip('chip-channel ' + (isSlack ? 'chip-slack' : 'chip-teams'), label, {
            channelName: node.getAttribute('data-channel-name') || label.replace(/^#/, ''),
            channelId: node.getAttribute('data-channel-id') || '',
            chatId: node.getAttribute('data-chat-id') || '',
            teamName: node.getAttribute('data-team-name') || '',
            channelType: ctype,
          }),
        );
        frag.appendChild(document.createTextNode(' '));
        applied.channels.push({
          channel_name: node.getAttribute('data-channel-name') || '',
          channel_id: node.getAttribute('data-channel-id') || '',
          chat_id: node.getAttribute('data-chat-id') || '',
          team_name: node.getAttribute('data-team-name') || '',
          type: ctype,
        });
        applied.skills.push(isSlack ? 'slack' : 'teams');
      } else if (kind === 'skill') {
        const skillId = node.getAttribute('data-skill-id') || '';
        if (!SKILL_MAP[skillId]) {
          // unknown skill → drop to plain text
          if (node.textContent) frag.appendChild(document.createTextNode(node.textContent));
          return;
        }
        const label = (node.textContent || '').trim() || skillId;
        frag.appendChild(
          _createInlineChip('chip-skill', label, {
            skillId,
            triggerPrefix: node.getAttribute('data-trigger-prefix') || '/',
          }),
        );
        frag.appendChild(document.createTextNode(' '));
        applied.skills.push(skillId);
      } else {
        // Non-chip element: recurse so we keep its text + any nested chips,
        // but never the element itself.
        walk(node);
      }
    });
  };
  walk(doc.body);
  return { frag, applied };
}

// Paste: prefer our own chip-preserving HTML (marker-gated); otherwise plain text.
input.addEventListener('paste', (e) => {
  const html = e.clipboardData.getData('text/html');
  if (html && /data-gator-chip=/.test(html)) {
    e.preventDefault();
    const { frag, applied } = _rebuildChipsFromHtml(html);
    const sel = window.getSelection();
    if (sel.rangeCount && input.contains(sel.anchorNode)) {
      const range = sel.getRangeAt(0);
      range.deleteContents();
      const lastNode = frag.lastChild;
      range.insertNode(frag);
      if (lastNode) {
        range.setStartAfter(lastNode);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
      }
    } else {
      input.appendChild(frag);
    }
    // Re-apply routing side effects so pasted channel/skill chips stay live.
    [...new Set(applied.skills)].forEach((id) => _addSkillChip(id));
    applied.channels.forEach((ch) => {
      const uid = ch.chat_id || ch.channel_id;
      if (uid && !_activeChannels.some((c) => (c.chat_id || c.channel_id) === uid))
        _activeChannels.push(ch);
    });
    input.focus();
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return;
  }
  e.preventDefault();
  const text = e.clipboardData.getData('text/plain');
  document.execCommand('insertText', false, text);
});

input.addEventListener('copy', (e) => {
  const selectedText = _serializeShareableSelection();
  const prefix = _shareablePromptContextPrefix(selectedText);
  const selectedHtml = _serializeShareableSelectionHtml();
  _writeShareableCopy(e, [prefix, selectedText].filter(Boolean).join(' '), selectedHtml);
});

form.addEventListener('copy', (e) => {
  if (e.defaultPrevented) return;
  const sel = window.getSelection();
  if (!sel.rangeCount) return;
  const selectedEl = _closestElement(sel.getRangeAt(0).commonAncestorContainer);
  if (!selectedEl?.closest?.('#chat-form')) return;
  _writeShareableCopy(e, _serializeShareableSelection(), _serializeShareableSelectionHtml());
});

// Enter = submit (Shift+Enter = newline)
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    // Don't submit if a dropdown is open (Enter selects from dropdown)
    if (
      document.querySelector('.skill-mention-dropdown') ||
      document.querySelector('.channel-dropdown') ||
      document.querySelector('.slash-dropdown')
    )
      return;
    e.preventDefault();
    document
      .getElementById('chat-form')
      .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  }
  // Backspace on empty input removes the last skill chip
  if (e.key === 'Backspace' && _getInputText().trim() === '' && !_getInlineChips().length) {
    if (_activeChips.length) {
      e.preventDefault();
      removeChip(_activeChips[_activeChips.length - 1].skillId);
    }
  }
});

// Deselect any selected chip when user clicks into or types in the input
input.addEventListener('focus', () => {
  document
    .querySelectorAll('.chat-chip.chip-selected')
    .forEach((c) => c.classList.remove('chip-selected'));
});

function _updateSendSlot() {
  const slot = document.getElementById('chat-send-slot');
  if (!slot) return;
  const hasText = (input.textContent || '').trim().length > 0;
  slot.classList.toggle('has-text', hasText);
}

input.addEventListener('input', () => {
  _updateSendSlot();
  document
    .querySelectorAll('.chat-chip.chip-selected')
    .forEach((c) => c.classList.remove('chip-selected'));
  if (!input.dataset.userResized) {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 90) + 'px';
  } else {
    // User manually resized — only grow if content exceeds the pinned height, never shrink.
    const pinned = parseFloat(input.style.height) || 0;
    input.style.height = 'auto';
    const natural = input.scrollHeight;
    input.style.height = Math.max(pinned, natural) + 'px';
  }

  const val = _getInputTextBeforeCursor();

  // / trigger: opens slash command dropdown (at start or after a space)
  const slashIdx = val.lastIndexOf('/');
  if (slashIdx !== -1) {
    const beforeSlash = val[slashIdx - 1];
    if (_isTriggerBoundary(beforeSlash)) {
      const query = val.slice(slashIdx + 1);
      if (/^[\w\s]*$/.test(query)) {
        closeMentionDropdown();
        _openSlashDropdown(query.trim());
        return;
      }
    }
  }
  _closeSlashDropdown();

  // { trigger: open pin reference dropdown
  const braceIdx = val.lastIndexOf('{');
  if (braceIdx !== -1) {
    const beforeBrace = val[braceIdx - 1];
    if (_isTriggerBoundary(beforeBrace)) {
      const afterBrace = val.slice(braceIdx + 1);
      const query = (afterBrace.match(/^[^}\n]*/) || [''])[0];
      closeMentionDropdown();
      closeChannelDropdown();
      openPinDropdown(query);
      return;
    }
  }
  closePinDropdown();

  // # trigger: fire when # is at start or after a space (check before @ so it
  // isn't blocked by an un-committed @mention earlier in the text)
  const hashIdx = val.lastIndexOf('#');
  const atIdx = val.lastIndexOf('@');
  const hashIsLast = hashIdx > atIdx; // # appears after any @ in the text
  if (hashIdx !== -1 && hashIsLast) {
    const beforeHash = val[hashIdx - 1];
    if (_isTriggerBoundary(beforeHash)) {
      const afterHash = val.slice(hashIdx + 1);
      const query = (afterHash.match(/^[\w-]*/) || [''])[0];
      const alreadyCommitted = _activeChannels.some((c) =>
        afterHash.toLowerCase().startsWith(c.channel_name.toLowerCase()),
      );
      if (!alreadyCommitted) {
        closeMentionDropdown();
        openChannelDropdown(query);
        return;
      }
    }
  }
  closeChannelDropdown();

  // @ trigger: people search only. Fire when @ is at start or after a space.
  if (atIdx !== -1) {
    const before = val[atIdx - 1];
    if (_isTriggerBoundary(before)) {
      const query = val.slice(atIdx + 1);
      if (/^[\w\s]*$/.test(query)) {
        openMentionDropdown(query);
        return;
      }
    }
  }
  closeMentionDropdown();
});

input.addEventListener('keydown', (e) => {
  // Prevent browser default Enter behavior (implicit form submission)
  // We handle Enter explicitly in each dropdown handler and the final fallthrough
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
  }
  // Mention dropdown navigation (handles both @ people and / skills)
  if (_mentionDropdown) {
    const items = Array.from(
      _mentionDropdown.querySelectorAll('.skill-mention-item, .skill-mention-action-row'),
    ).filter((el) => !el.closest('.skill-mention-actions-group.hidden'));
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _mentionFocusIdx = (_mentionFocusIdx + 1) % items.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _mentionFocusIdx = (_mentionFocusIdx - 1 + items.length) % items.length;
    } else if (e.key === 'ArrowRight') {
      const idx = _mentionFocusIdx >= 0 ? _mentionFocusIdx : 0;
      const focused = items[idx];
      if (focused?.dataset.type === 'slash-skill') {
        e.preventDefault();
        const chevron = focused.querySelector('.skill-mention-chevron-btn');
        if (chevron) chevron.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        // Focus moves to first action row — recalculate after DOM update
        requestAnimationFrame(() => {
          _mentionFocusIdx = idx + 1;
        });
      }
      return;
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      _mentionDropdown
        .querySelectorAll('.skill-mention-actions-group')
        .forEach((g) => g.classList.add('hidden'));
      _mentionDropdown
        .querySelectorAll('.skill-mention-chevron-btn')
        .forEach((b) => b.classList.remove('open'));
      // Recalculate — _mentionFocusIdx stays on the skill row it was on
      return;
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      const idx = _mentionFocusIdx >= 0 ? _mentionFocusIdx : 0;
      const focused = items[idx];
      if (!focused) return;
      e.preventDefault();
      if (focused.dataset.type === 'person') {
        commitPersonMention({ name: focused.dataset.name, email: focused.dataset.email });
      } else if (focused.dataset.type === 'action') {
        focused.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      } else if (focused.dataset.type === 'slash-skill') {
        const skill = SKILL_MAP[focused.dataset.skillId];
        if (skill) _commitSkillChipOnly(skill, '/');
      } else if (focused.dataset.type === 'slash-command') {
        const cmd = PLUGIN_COMMANDS.find((c) => c.name === focused.dataset.commandName);
        if (cmd) _commitCommandOnly(cmd);
      } else {
        const skill = SKILL_MAP[focused.dataset.skillId];
        if (skill) _commitSkillChipOnly(skill, '@');
      }
      return;
    } else if (e.key === 'Escape') {
      closeMentionDropdown();
      return;
    }
    items.forEach((item, i) => {
      item.classList.toggle('focused', i === _mentionFocusIdx);
      if (i === _mentionFocusIdx) item.scrollIntoView({ block: 'nearest' });
    });
    return;
  }
  // Channel dropdown navigation
  if (_channelDropdown) {
    const items = _channelDropdown.querySelectorAll('.skill-mention-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _channelFocusIdx = Math.min(_channelFocusIdx + 1, items.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _channelFocusIdx = Math.max(_channelFocusIdx - 1, 0);
    } else if ((e.key === 'Enter' || e.key === 'Tab') && _channelFocusIdx >= 0) {
      e.preventDefault();
      const focused = items[_channelFocusIdx];
      commitChannelMention({
        channel_id: focused.dataset.channelId,
        channel_name: focused.querySelector('.skill-mention-name').textContent,
        team_name: focused.querySelector('.skill-mention-badge').textContent,
        team_id: focused.dataset.teamId || '',
      });
      return;
    } else if (e.key === 'Escape') {
      closeChannelDropdown();
      return;
    }
    items.forEach((item, i) => {
      item.classList.toggle('focused', i === _channelFocusIdx);
      if (i === _channelFocusIdx) item.scrollIntoView({ block: 'nearest' });
    });
    return;
  }
  // Pin dropdown navigation
  if (_pinDropdown) {
    const items = _pinDropdown.querySelectorAll('.skill-mention-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _pinFocusIdx = (_pinFocusIdx + 1) % items.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _pinFocusIdx = (_pinFocusIdx <= 0 ? items.length : _pinFocusIdx) - 1;
    } else if ((e.key === 'Enter' || e.key === 'Tab') && _pinFocusIdx >= 0) {
      e.preventDefault();
      const pins = _pinDropdown._pins || [];
      if (pins[_pinFocusIdx]) commitPinMention(pins[_pinFocusIdx]);
      return;
    } else if (e.key === 'Escape') {
      closePinDropdown();
      return;
    }
    items.forEach((item, i) => {
      item.classList.toggle('focused', i === _pinFocusIdx);
      if (i === _pinFocusIdx) item.scrollIntoView({ block: 'nearest' });
    });
    return;
  }
  // ESC removes last chip
  if (e.key === 'Escape' && _activeChips.length > 0) {
    removeChip(_activeChips[_activeChips.length - 1].skillId);
    return;
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

// Dedup set for pane signals — prevents double-fire when signal arrives on both
// the chat SSE stream and the notification SSE stream in the same request cycle
const _paneSignalSeen = new Set();

// Shared pane signal dispatcher — used by chat stream, notification stream, and agents-pane replay
function _handlePaneSignal(pane, paneData) {
  // Build a fingerprint from pane + stable identifying fields
  const _fp =
    pane +
    '|' +
    (paneData._nonce ||
      paneData.draft_id ||
      paneData.chat_id ||
      paneData.to ||
      paneData.subject ||
      JSON.stringify(paneData).slice(0, 80));
  if (_paneSignalSeen.has(_fp)) {
    console.log('[pane-signal] deduped:', pane);
    return;
  }
  _paneSignalSeen.add(_fp);
  setTimeout(() => _paneSignalSeen.delete(_fp), 3000);

  console.log('[pane-signal] dispatching:', pane);

  // Each branch is wrapped in try/catch so a failure in one pane type doesn't
  // silently kill the handler (the outer EventSource catch {} was swallowing these).
  try {
    if (pane === 'teams-compose') {
      // Shell/native mode: the classic Teams third pane is hidden (Teams fills
      // that space). Show a draft-approval card in Gator chat instead —
      // same editable approve/reject pattern used for Slack drafts.
      if (typeof window.gatorShell !== 'undefined' && window.gatorShell.isShell) {
        _injectDraftApprovalCard('teams-message', paneData);
      } else {
        // Classic mode: existing compose pane behaviour unchanged.
        if (typeof tpState !== 'undefined') tpState.selectedId = null;
        if (typeof openThirdPane === 'function') openThirdPane('teams');
        if (typeof _teamsReceiveComposeData === 'function') _teamsReceiveComposeData(paneData);
        _injectComposeCard('teams', paneData);
      }
    } else if (pane === 'email-compose') {
      // Native Outlook (shell) mode: the classic compose pane is hidden, so
      // render an editable draft-approval card in Gator chat (like Teams).
      if (
        typeof window.gatorShell !== 'undefined' &&
        window.gatorShell.isShell &&
        typeof _outlookNativeEnabled === 'function' &&
        _outlookNativeEnabled()
      ) {
        _injectDraftApprovalCard('email-send', paneData);
      } else {
        if (typeof openThirdPane === 'function') openThirdPane('email');
        if (typeof _emailReceiveComposeData === 'function') _emailReceiveComposeData(paneData);
        _injectComposeCard('email', paneData);
      }
    } else if (pane === 'slack-compose') {
      if (typeof openThirdPane === 'function') openThirdPane('slack');
      if (typeof _slackReceiveComposeData === 'function') _slackReceiveComposeData(paneData);
      _injectComposeCard('slack', paneData);
    } else if (pane === 'jira-create') {
      // Shell + native Jira: openThirdPane('jira') would show the native
      // WebContentsView and hide #third-pane, making the create form invisible
      // (same issue Teams/Outlook had — fixed via M8). In native shell mode,
      // open the classic #third-pane form directly without switching to the
      // native pane. _jiraOpenClassicPane() in third-pane.js handles this;
      // fall back to openThirdPane for classic/browser mode.
      const _jiraInShellNative =
        typeof window.gatorShell !== 'undefined' &&
        window.gatorShell.isShell &&
        typeof _jiraNativeEnabled === 'function' &&
        _jiraNativeEnabled();
      if (_jiraInShellNative && typeof _jiraOpenClassicPane === 'function') {
        _jiraOpenClassicPane();
      } else if (typeof openThirdPane === 'function') {
        openThirdPane('jira');
      }
      if (typeof _jiraReceivePaneData === 'function') _jiraReceivePaneData(paneData);
      _injectComposeCard('jira', paneData);
    } else if (pane === 'jira-update-fields') {
      if (typeof _jiraUpdateFormFields === 'function') _jiraUpdateFormFields(paneData);
    } else if (pane === 'jira-list') {
      if (typeof _jiraUpdateIssueList === 'function') _jiraUpdateIssueList(paneData);
    } else if (pane === 'jira-issue') {
      // Opens the issue detail view — emitted by jira_mutate on successful POST issue
      if (typeof openThirdPane === 'function') openThirdPane('jira');
      const detailCol = document.getElementById('tp-detail-col');
      if (detailCol && typeof _renderJiraIssueDetail === 'function') {
        _renderJiraIssueDetail(detailCol, paneData.key, paneData.url || '');
      }
      const listContainer = document.getElementById('jira-issue-list');
      if (listContainer && typeof _renderJiraMyWork === 'function')
        _renderJiraMyWork(listContainer);
      if (paneData.key && paneData.url && typeof _postJiraSuccessCard === 'function') {
        _postJiraSuccessCard(paneData.key, paneData.url);
      }
    } else if (pane === 'confluence-create' || pane === 'confluence-edit') {
      if (typeof openThirdPane === 'function') openThirdPane('confluence');
      const cfAction = pane === 'confluence-create' ? 'create' : 'edit';
      if (typeof _confluenceReceivePaneData === 'function')
        _confluenceReceivePaneData(cfAction, paneData);
    } else if (pane === 'confluence-list') {
      if (typeof _confluenceUpdatePageList === 'function') _confluenceUpdatePageList(paneData);
    } else {
      console.warn('[pane-signal] unknown pane type:', pane);
    }
  } catch (e) {
    console.error('[pane-signal] error handling', pane, ':', e);
  }
}

function _injectComposeCard(type, data) {
  const isJira = type === 'jira';
  const isEmail = type === 'email';
  const paneLabel = isEmail ? '@outlook' : isJira ? '@jira' : '@teams';
  const paneIcon = isEmail ? '✉️' : isJira ? '🎫' : '💬';
  const actionLabel = isJira ? 'Create' : 'Send';
  const title = isJira ? 'Form loaded in @jira' : `Draft delivered to ${paneLabel}`;
  const step1 = isJira
    ? `Form pre-filled in the ${paneLabel} pane`
    : `Draft loaded in the ${paneLabel} pane`;
  const step2 = isJira
    ? `Review, fill any remaining fields, and hit <strong>${actionLabel}</strong> when ready`
    : `Review, edit, and hit <strong>${actionLabel}</strong> when ready`;

  const recipientHint = !isJira && data.to ? data.to.split(',')[0].split('@')[0] : '';
  const subjectHint = !isJira && data.subject ? ` &mdash; "${escapeHtml(data.subject)}"` : '';
  const projectHint =
    isJira && data.project ? `Project: <strong>${escapeHtml(data.project)}</strong>` : '';
  const summaryHint = isJira && data.summary ? ` &mdash; "${escapeHtml(data.summary)}"` : '';

  const card = document.createElement('div');
  card.className = 'message assistant';
  card.innerHTML = `
    <div class="bubble card-bubble">
      <div class="gator-compose-card">
        <div class="gcc-header">
          <div class="gcc-gator">
            <span class="gcc-gator-icon">🐊</span>
            <span class="gcc-gator-trail">
              <span class="gcc-dot gcc-dot-1"></span>
              <span class="gcc-dot gcc-dot-2"></span>
              <span class="gcc-dot gcc-dot-3"></span>
            </span>
            <span class="gcc-pane-icon">${paneIcon}</span>
          </div>
          <div class="gcc-title">${title}</div>
        </div>
        <div class="gcc-body">
          ${recipientHint ? `<div class="gcc-recipient">To: <strong>${escapeHtml(recipientHint)}</strong>${subjectHint}</div>` : ''}
          ${projectHint ? `<div class="gcc-recipient">${projectHint}${summaryHint}</div>` : ''}
          <div class="gcc-steps">
            <div class="gcc-step"><span class="gcc-check">✓</span><span class="gcc-step-text">${step1}</span></div>
            <div class="gcc-step"><span class="gcc-arrow">→</span><span class="gcc-step-text">${step2}</span></div>
          </div>
        </div>
        <div class="gcc-footer">
          <span class="gcc-refine">Want changes? Just tell me here — we'll go back and forth until it's perfect.</span>
          <span class="gcc-tagline">The Gator drafts. You pull the trigger.</span>
        </div>
      </div>
    </div>`;
  document.getElementById('messages').appendChild(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function _injectDraftApprovalCard(type, data) {
  const draftId = data.draft_id;
  const config = {
    'email-reply': {
      paneLabel: '@outlook',
      paneIcon: '\u2709\uFE0F',
      service: 'email',
      action: 'Reply' + (data.action === 'replyAll' ? ' All' : ''),
    },
    'email-forward': {
      paneLabel: '@outlook',
      paneIcon: '\u2709\uFE0F',
      service: 'email',
      action: 'Forward',
    },
    'email-send': {
      paneLabel: '@outlook',
      paneIcon: '\u2709\uFE0F',
      service: 'email',
      action: 'Send to ' + (data.to || ''),
    },
    'slack-post': {
      paneLabel: '@slack',
      paneIcon: '\uD83D\uDCAC',
      service: 'slack',
      action: 'Post to #' + (data.channel || ''),
    },
    'slack-dm': {
      paneLabel: '@slack',
      paneIcon: '\uD83D\uDC8C',
      service: 'slack',
      action: 'DM to ' + (data.recipient || ''),
    },
    'slack-announce': {
      paneLabel: '@slack',
      paneIcon: '\uD83D\uDCE3',
      service: 'slack',
      action: 'Announce to ' + (data.channels || ''),
    },
    'slack-schedule': {
      paneLabel: '@slack',
      paneIcon: '\u23F0',
      service: 'slack',
      action: 'Schedule to #' + (data.channel || ''),
    },
    'teams-message': {
      paneLabel: '@teams',
      paneIcon: '\uD83D\uDCAC',
      service: 'teams',
      action: 'Send to ' + (data.to_names || data.to || data.chat_topic || 'Teams'),
    },
    'calendar-write': {
      paneLabel: '@gcal',
      paneIcon: '\uD83D\uDCC5',
      service: '',
      action: data.action || 'Calendar change',
      hideEditLink: true,
    },
  }[type] || { paneLabel: '@unknown', paneIcon: '\uD83D\uDCE4', service: '', action: 'Send' };

  const fullBody = data.body_snippet || data.message_snippet || data.body || data.message || '';
  const bodySnippet = escapeHtml(fullBody.slice(0, 200));
  const recipientInfo = data.to || data.channel || data.recipient || data.channels || '';
  const subjectLine = data.subject || '';

  const card = document.createElement('div');
  card.className = 'message assistant';
  card.innerHTML = `
    <div class="bubble card-bubble">
      <div class="gator-compose-card gator-draft-card">
        <div class="gcc-header">
          <div class="gcc-gator">
            <span class="gcc-gator-icon">\uD83D\uDC0A</span>
            <span class="gcc-gator-trail">
              <span class="gcc-dot gcc-dot-1"></span>
              <span class="gcc-dot gcc-dot-2"></span>
              <span class="gcc-dot gcc-dot-3"></span>
            </span>
            <span class="gcc-pane-icon">${config.paneIcon}</span>
          </div>
          <div class="gcc-title">Draft ready for approval</div>
        </div>
        <div class="gcc-body">
          <div class="gcc-recipient"><strong>${escapeHtml(config.action)}</strong>${recipientInfo ? ' &mdash; ' + escapeHtml(recipientInfo) : ''}</div>
          ${subjectLine ? `<div class="gcc-subject">${escapeHtml(subjectLine)}</div>` : ''}
          ${config.hideEditLink ? '' : `<textarea class="gcc-edit-area" rows="${Math.min(10, Math.max(3, fullBody.split('\n').length))}" style="width:100%;box-sizing:border-box;background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px;font:inherit;font-size:.85rem;line-height:1.5;resize:vertical;margin-top:6px">${escapeHtml(fullBody)}</textarea>`}
        </div>
        <div class="gcc-actions">
          <button class="gcc-approve-btn" data-draft-id="${draftId}">${config.hideEditLink ? 'I approve' : 'I approve to send'}</button>
          <a class="gcc-edit-link" href="#" ${config.service === 'slack' || config.hideEditLink ? 'style="display:none"' : ''}>Edit in ${config.paneLabel}</a>
        </div>
        <div class="gcc-footer">
          <span class="gcc-refine">${config.hideEditLink ? 'Tell me here to change anything first.' : 'Edit the text above or just tell me here for changes.'}</span>
          <span class="gcc-tagline">The Gator drafts. You pull the trigger.</span>
        </div>
      </div>
    </div>`;

  const approveBtn = card.querySelector('.gcc-approve-btn');
  const editLink = card.querySelector('.gcc-edit-link');

  approveBtn.addEventListener('click', async () => {
    if (approveBtn.dataset.editMode === 'true') return; // blocked — user is editing in pane
    approveBtn.disabled = true;
    approveBtn.textContent = config.hideEditLink ? 'Applying\u2026' : 'Sending\u2026';
    try {
      // Send the EDITED text from the textarea, not the original draft.
      const editArea = card.querySelector('.gcc-edit-area');
      const editedText = editArea ? editArea.value : null;
      const res = await fetch('/api/drafts/' + draftId + '/approve', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': window.__CSRF_TOKEN__ || '',
        },
        body: editedText !== null ? JSON.stringify({ edited_message: editedText }) : undefined,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'HTTP ' + res.status);
      }
      approveBtn.textContent = config.hideEditLink ? 'Applied \u2713' : 'Sent \u2713';
      approveBtn.classList.add('gcc-approved');
      editLink.style.display = 'none';
      // Close the third-pane compose if it's still open (avoid confusion).
      // But DON'T close in shell mode — the native Slack or Teams tile should stay open.
      if (typeof window.gatorShell !== 'undefined' && window.gatorShell.isShell) {
        // Shell mode: keep the native app pane visible.
      } else if (typeof closeThirdPane === 'function') {
        closeThirdPane();
      }
    } catch (e) {
      approveBtn.textContent = 'Failed \u2014 retry?';
      approveBtn.disabled = false;
      approveBtn.classList.add('gcc-failed');
    }
  });

  editLink.addEventListener('click', (e) => {
    e.preventDefault();
    // Disable the approve button — source of truth moves to compose pane
    approveBtn.disabled = true;
    approveBtn.dataset.editMode = 'true';
    approveBtn.textContent = 'Send from ' + config.paneLabel;
    approveBtn.classList.add('gcc-edit-active');
    editLink.textContent = 'Editing in ' + config.paneLabel + ' \u2026';

    if (config.service === 'email') {
      if (typeof openThirdPane === 'function') openThirdPane('email');
      if (typeof _emailReceiveComposeData === 'function') _emailReceiveComposeData(data);
    } else if (config.service === 'slack') {
      if (typeof openThirdPane === 'function') openThirdPane('slack');
      if (typeof _slackReceiveComposeData === 'function') _slackReceiveComposeData(data);
    }
  });

  document.getElementById('messages').appendChild(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function addMessage(role, html) {
  const div = document.createElement('div');
  div.className = `message ${role}`;
  if (role === 'assistant') {
    div.innerHTML = `<div class="msg-avatar"></div><div class="bubble"><div class="prose">${html}</div></div>`;
  } else {
    div.innerHTML = `<div class="bubble">${html}</div>`;
  }
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  // Make any images in this bubble clickable to open lightbox
  div.querySelectorAll('img').forEach((img) => {
    if (img.classList.contains('skill-icon-img')) return; // skip UI icons
    img.style.cursor = 'zoom-in';
    img.addEventListener('click', () => {
      if (window._tpLightboxOpen) window._tpLightboxOpen(img.src);
    });
  });
  // Return the prose div for assistant (so innerHTML updates go there), bubble for user
  return div.querySelector('.prose') || div.querySelector('.bubble');
}

messages.addEventListener('copy', (e) => {
  const sel = window.getSelection();
  if (!sel.rangeCount) return;
  const range = sel.getRangeAt(0);
  const selectedEl = _closestElement(range.commonAncestorContainer);
  const userMessage = selectedEl?.closest?.('.message.user');
  if (!userMessage) return;
  _writeShareableCopy(e, _serializeShareableSelection(), _serializeShareableSelectionHtml());
});

function escapeHtml(t) {
  return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Re-insert a space dropped at a streamed-chunk boundary (issue #52). Fires
// only when the accumulated text ends with sentence punctuation (. ! ?) and
// the next chunk starts with a capital letter or a markdown/quote opener.
// Scoped this tightly on purpose: a lowercase or digit start would corrupt
// decimals (3.14), thousands grouping isn't punctuation here, and domains /
// filenames (app.js, claude.ai) stay intact. A newline boundary already
// ends `prev` with "\n", so this won't fire across paragraph breaks.
function _joinStreamToken(prev, tok) {
  if (prev && tok && /[.!?]$/.test(prev) && /^[A-Z"'([*`]/.test(tok)) {
    return ' ' + tok;
  }
  return tok;
}

// A message is sendable when it has typed text, a file chip, OR at least one
// staged image (issue #30). Enter previously gated on text only, so an
// image-only prompt was a no-op while the Send button worked.
function _canSubmitMessage(hasText, hasFileChips, hasImages) {
  return Boolean(hasText || hasFileChips || hasImages);
}

// Ensure GATOR_JIRA_URL is always a string even before the async config fetch resolves
window.GATOR_JIRA_URL = '';

// Close any open share dropdowns when clicking outside them
document.addEventListener('click', () => {
  document.querySelectorAll('.ofc-share-menu').forEach((m) => {
    m.style.display = 'none';
  });
});

/* ── Fuzzy scorer (ported from VS Code src/vs/base/common/fuzzyScorer.ts) ── */
// Scores a query against a target string. Returns a numeric score (higher = better match)
// or 0 if the query chars are not all present in order. Mirrors VS Code's algorithm:
// prefix match 8pts, consecutive run 6→3 pts, separator/camelCase boundary 4-5 pts.
function _fuzzyScore(query, target) {
  if (!query) return 1; // empty query matches everything equally
  const q = query.toLowerCase();
  const t = target.toLowerCase();
  const tLen = t.length;
  const qLen = q.length;
  if (qLen > tLen) return 0;

  // Require all query chars appear in order
  let qi = 0;
  for (let ti = 0; ti < tLen && qi < qLen; ti++) {
    if (t[ti] === q[qi]) qi++;
  }
  if (qi < qLen) return 0; // not all chars matched

  // Score the match
  let score = 0;
  let qIdx = 0;
  let lastMatchIdx = -1;
  let consecutiveLen = 0;

  for (let tIdx = 0; tIdx < tLen && qIdx < qLen; tIdx++) {
    if (t[tIdx] !== q[qIdx]) {
      consecutiveLen = 0;
      continue;
    }

    const isFirst = tIdx === 0;
    const isSeparator = tIdx > 0 && /[\s\-_./]/.test(t[tIdx - 1]);
    const isCamel =
      tIdx > 0 && t[tIdx] !== t[tIdx].toLowerCase() && t[tIdx - 1] === t[tIdx - 1].toLowerCase();
    const isConsecutive = lastMatchIdx === tIdx - 1;

    if (isFirst || isSeparator)
      score += 8; // prefix / word boundary
    else if (isCamel)
      score += 5; // camelCase boundary
    else if (isConsecutive) {
      consecutiveLen++;
      score += Math.max(6 - consecutiveLen, 3); // consecutive run, diminishing
    } else {
      score += 1; // scattered match
      consecutiveLen = 0;
    }

    // Exact case bonus
    if (query[qIdx] === target[tIdx]) score += 1;

    lastMatchIdx = tIdx;
    qIdx++;
  }

  // Penalise longer targets slightly (prefer shorter, more specific matches)
  score -= tLen * 0.05;

  return score;
}

// Filter + rank a list of skills by fuzzy score against query
function _fuzzyFilterSkills(skills, query) {
  if (!query) return skills;
  const scored = skills
    .map((s) => {
      const alias = s.chipAlias || s.id;
      const labelScore = _fuzzyScore(query, s.label);
      const aliasScore = _fuzzyScore(query, alias);
      const score = Math.max(labelScore, aliasScore);
      return { skill: s, score };
    })
    .filter((x) => x.score > 0);
  scored.sort((a, b) => b.score - a.score);
  return scored.map((x) => x.skill);
}

// Decision #12 (2026-08-07 milestone) — filter PLUGIN_COMMANDS for the "/"
// dropdown's COMMANDS section. A separate function from _fuzzyFilterSkills
// (rather than shoehorning commands into a skill-shaped object) since a
// command has no chipAlias/label split — it's matched on its bare name only,
// same as how the runtime itself matches `/name` (marketplace/commands.py's
// try_expand_command). Pulled out as a pure function (matching the
// Increment 4a convention — _cardActionState, _findCollisionEntry, etc. —
// so it's unit-testable without a DOM).
function _fuzzyFilterCommands(commands, query) {
  if (!query) return commands;
  const scored = commands
    .map((c) => ({ command: c, score: _fuzzyScore(query, c.name) }))
    .filter((x) => x.score > 0);
  scored.sort((a, b) => b.score - a.score);
  return scored.map((x) => x.command);
}

// Inline markdown (runs on already-escaped text)
function applyInline(html) {
  // Phase 1: stash inline code spans so no other regex touches their content
  const codeStash = [];
  html = html.replace(/`([^`]+)`/g, (_, inner) => {
    codeStash.push(inner);
    return `\x00C${codeStash.length - 1}\x00`;
  });

  // Markdown links first — so the URL inside [text](url) is consumed before
  // the bare-URL pass runs (prevents double-wrapping).
  // Handles: https://, http://, root-relative (/api/...), mailto:, #fragment
  html = html.replace(/\[(.*?)\]\(((?:https?:\/\/|mailto:|\/|#)[^\)"]*)\)/g, (_, text, href) => {
    const isExternal = /^https?:\/\//.test(href);
    return `<a href="${href}"${isExternal ? ' target="_blank" rel="noopener"' : ''}>${text}</a>`;
  });
  // Bare https:// URLs not already inside an HTML attribute
  html = html.replace(
    /(?<![="'>])(https?:\/\/[^\s<>"')\]]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  // Bare root-relative /api/files/<run_id>/<filename> download paths. The model
  // sometimes emits these as plain text instead of a markdown link, which then
  // rendered as a non-clickable string (reported by users: "file links are odd
  // and not clickable"). Scoped to /api/files/ specifically — real downloadable
  // artifacts, not arbitrary /api/ endpoints. Skipped when already inside an
  // attribute/anchor (the markdown-link pass above handles [text](/api/files/…)).
  // Link text is the (decoded) filename rather than the raw path — cleaner, and
  // `download` gives the saved file its real name.
  html = html.replace(/(?<![="'>\]])(\/api\/files\/[^\s<>"')\]]+)/g, (_m, path) => {
    let name = path.split('/').pop() || path;
    try {
      name = decodeURIComponent(name);
    } catch (_) {}
    return `<a href="${path}" download>${name}</a>`;
  });
  // Flag EVERY /api/files download link as temporary — these are ephemeral
  // code_runner scratch outputs, deleted after ~24h (see web/routes/files.py's
  // cleanup_old_outputs), not durable storage. Covers both the bare paths
  // linkified just above AND markdown-wrapped [text](/api/files/…) links from
  // the markdown pass, so a user is never handed a clickable link that silently
  // 404s tomorrow. Adds a hover tooltip + a muted "(temporary)" tag.
  html = html.replace(/(<a href="\/api\/files\/[^"]+"[^>]*)>([\s\S]*?)<\/a>/g, (_m, open, text) => {
    const tip = 'Generated file — this download link expires in ~24h. Save a copy to keep it.';
    return (
      `${open} title="${tip}">${text}</a>` +
      `<span class="file-temp-tag" title="${tip}">(temporary)</span>`
    );
  });
  // Jira keys (e.g. PROJ-123) — only when base URL is known.
  // Guard: skip matches that are already inside an HTML tag (href=, /browse/ path, or
  // inside a <a ...> ... </a> that was emitted by the URL pass above) to prevent
  // double-wrapping which corrupts the anchor and renders as raw text in the browser.
  // Auto-link bare keys only when exactly one Jira instance is registered.
  // With 2+ we can't disambiguate; the LLM is instructed to emit markdown
  // links itself using the tool response's `url` field (see aigator SKILL.md).
  const _jiraInstances =
    window.GATOR_JIRA_INSTANCES || (window.GATOR_JIRA_URL ? [window.GATOR_JIRA_URL] : []);
  if (_jiraInstances.length === 1) {
    const _jiraBase = _jiraInstances[0]
      .replace(/\/+$/, '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;');
    html = html.replace(/\b([A-Z][A-Z0-9]+-\d+)\b/g, (match, key, offset) => {
      // Reject if the key appears inside an HTML attribute (preceded by = or /)
      const before = html.slice(Math.max(0, offset - 20), offset);
      if (/[=\/"]/.test(before.slice(-1))) return match;
      // Reject if we're inside an existing <a …> tag by checking for an unclosed <a
      const preceding = html.slice(0, offset);
      const openCount = (preceding.match(/<a[\s>]/g) || []).length;
      const closeCount = (preceding.match(/<\/a>/g) || []).length;
      if (openCount > closeCount) return match;
      return `<a href="${_jiraBase}/browse/${key}" target="_blank" rel="noopener noreferrer">${key}</a>`;
    });
  }
  // Windows absolute file paths — accept both backslash and forward-slash separators
  // (Python's pathlib on Windows can emit either; the AI may use either in prose)
  const _winPathRx = /([A-Za-z]:[/\\](?![/\\])(?:[^<>\s"'`\x00]+[/\\])*[^<>\s"'`\x00]+)/g;
  html = html.replace(_winPathRx, (_, rawPath) => {
    const trailing = rawPath.match(/[.,;:!?]+$/)?.[0] || '';
    const path = trailing ? rawPath.slice(0, -trailing.length) : rawPath;
    const attrSafe = path.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    return `<button class="file-path-btn" data-path="${attrSafe}">&#128196; ${path}</button>${trailing}`;
  });

  // Apply bold/italic while code spans are still placeholders — prevents processing
  // ** or * inside backtick content (e.g. `**not bold**` must stay literal).
  // Bold: .+? allows any content including nested *, but requires at least one char
  // so ** (two adjacent stars from a partial stream token) doesn't match empty.
  // Italic: negative lookaround prevents matching inside **bold** markers.
  html = html
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, '<em>$1</em>');

  // Phase 2: restore stashed code spans — file paths become buttons, everything else stays <code>
  // Backtick spans: allow spaces; (?![/\\]) blocks URLs (https://)
  const _winPath = /^[A-Za-z]:[/\\](?![/\\])(?:[^<>"'`\x00]+[/\\])*[^<>"'`\x00]+$/;
  html = html.replace(/\x00C(\d+)\x00/g, (_, i) => {
    const inner = codeStash[+i];
    const trailing = inner.match(/[.,;:!?]+$/)?.[0] || '';
    const trimmed = trailing ? inner.slice(0, -trailing.length) : inner;
    if (_winPath.test(trimmed)) {
      const attrSafe = trimmed.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
      return `<button class="file-path-btn" data-path="${attrSafe}">&#128196; ${trimmed}</button>${trailing}`;
    }
    return `<code>${inner}</code>`;
  });

  return html;
}

function renderMarkdown(raw) {
  // Extract fenced code blocks before escaping
  // Fenced-block path regex allows spaces; (?![/\\]) blocks URLs (https://)
  const _winPathRxFenced = /^[A-Za-z]:[/\\](?![/\\])(?:[^<>"'`\x00]+[/\\])*[^<>"'`\x00]+$/;
  const blocks = [];
  let s = raw.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const trimmed = code.trim();
    // Single-line Windows path with no lang tag → render as a clickable file button
    if (!lang && _winPathRxFenced.test(trimmed)) {
      const attrSafe = trimmed.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
      const idx = blocks.length;
      blocks.push(
        `<button class="file-path-btn" data-path="${attrSafe}">&#128196; ${escapeHtml(trimmed)}</button>`,
      );
      return `\x00B${idx}\x00`;
    }
    const idx = blocks.length;
    const escaped = escapeHtml(trimmed);
    const langLabel = lang ? `<span class="code-lang">${escapeHtml(lang)}</span>` : '';
    blocks.push(
      `<div class="code-block-wrap">${langLabel}<button class="code-copy-btn" aria-label="Copy code">Copy</button><pre><code>${escaped}</code></pre></div>`,
    );
    return `\x00B${idx}\x00`;
  });

  // Convert raw <a href="URL">TEXT</a> the LLM sometimes emits into markdown
  // links so the markdown-link pass renders one clean anchor, instead of the
  // tag being escaped to visible text and leaking attribute soup (#49).
  // A ')' in the href (common in SharePoint query strings) would terminate the
  // markdown-link pass early and truncate the URL, so percent-encode it.
  s = s.replace(
    /<a\b[^>]*\bhref=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi,
    (_, href, text) =>
      `[${text.replace(/<[^>]+>/g, '').trim() || href}](${href.replace(/\)/g, '%29')})`,
  );

  // Normalize line endings.
  s = s.replace(/\r\n/g, '\n');

  // Fix: LLMs sometimes emit pipe-table rows joined by || on a single line
  // instead of using real newlines, e.g.:
  //   "| A | B || C | D ||---|---|"
  // Split each || into a newline so each row lands on its own line.
  // Guard: only rewrite lines that look like table rows (start with |, contain ||).
  s = s.replace(/^(\|[^\n]+)$/gm, (line) => {
    if (!line.includes('||')) return line;
    // Split rows on ||, drop any empty fragments from a trailing ||
    return line
      .split('||')
      .map((r) => r.trim())
      .filter((r) => r.length > 1)
      .join('\n');
  });

  // Collapse blank lines between pipe-table rows so they land in one group.
  s = s.replace(/(\|[^\n]+)\n{2,}(?=\|)/g, '$1\n');

  // Split on blank lines → paragraph groups
  const groups = s.split(/\n{2,}/);
  const out = groups.map((group) => {
    if (!group.trim()) return '';
    const lines = group.split('\n');

    // Code block placeholder
    if (lines.length === 1 && /^\x00B\d+\x00$/.test(lines[0].trim())) {
      const idx = parseInt(lines[0].match(/\x00B(\d+)\x00/)[1]);
      return blocks[idx];
    }

    // Headings (single line)
    if (lines.length === 1) {
      const l = lines[0];
      const esc = escapeHtml(l);
      if (l.startsWith('#### ')) return `<h4>${applyInline(escapeHtml(l.slice(5)))}</h4>`;
      if (l.startsWith('### ')) return `<h3>${applyInline(escapeHtml(l.slice(4)))}</h3>`;
      if (l.startsWith('## ')) return `<h2>${applyInline(escapeHtml(l.slice(3)))}</h2>`;
      if (l.startsWith('# ')) return `<h1>${applyInline(escapeHtml(l.slice(2)))}</h1>`;
      if (/^---+$/.test(l.trim()))
        return '<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:.5rem 0">';
    }

    // Unordered list — also handle mixed groups where a lead-in line precedes bullets
    const bulletLines2 = lines.filter((l) => /^\s*[-*] /.test(l));
    if (bulletLines2.length > 0 && !lines.every((l) => /^\s*[-*] /.test(l) || l.trim() === '')) {
      const parts = [];
      let inList = false;
      let listLines = [];
      for (const l of lines) {
        if (/^\s*[-*] /.test(l)) {
          inList = true;
          listLines.push(l);
        } else {
          if (listLines.length) {
            parts.push(
              '<ul>' +
                listLines
                  .map((ll) => `<li>${applyInline(escapeHtml(ll.replace(/^\s*[-*] /, '')))}</li>`)
                  .join('') +
                '</ul>',
            );
            listLines = [];
          }
          if (l.trim()) parts.push(`<p>${applyInline(escapeHtml(l))}</p>`);
        }
      }
      if (listLines.length) {
        parts.push(
          '<ul>' +
            listLines
              .map((ll) => `<li>${applyInline(escapeHtml(ll.replace(/^\s*[-*] /, '')))}</li>`)
              .join('') +
            '</ul>',
        );
      }
      return parts.join('');
    }

    // Unordered list (supports nested indentation)
    if (lines.every((l) => /^\s*[-*] /.test(l) || l.trim() === '')) {
      const bulletLines = lines.filter((l) => /^\s*[-*] /.test(l));
      let html = '';
      const stack = [0]; // indentation stack
      bulletLines.forEach((l) => {
        const indent = l.match(/^(\s*)/)[1].length;
        const text = applyInline(escapeHtml(l.replace(/^\s*[-*] /, '')));
        if (indent > stack[stack.length - 1]) {
          html += '<ul>';
          stack.push(indent);
        } else {
          while (stack.length > 1 && indent < stack[stack.length - 1]) {
            html += '</li></ul>';
            stack.pop();
          }
          if (html) html += '</li>'; // close previous sibling
        }
        html += `<li>${text}`;
      });
      while (stack.length > 1) {
        html += '</li></ul>';
        stack.pop();
      }
      html += '</li>';
      return `<ul>${html}</ul>`;
    }

    // Ordered list (supports nested indentation, preserves custom start number)
    if (lines.every((l) => /^\s*\d+\.\s+/.test(l) || l.trim() === '')) {
      const numLines = lines.filter((l) => /^\s*\d+\.\s+/.test(l));
      const startNum = parseInt(numLines[0]?.match(/^\s*(\d+)\./)?.[1] || '1', 10);
      let html = '';
      const stack = [0];
      numLines.forEach((l) => {
        const indent = l.match(/^(\s*)/)[1].length;
        const text = applyInline(escapeHtml(l.replace(/^\s*\d+\.\s+/, '')));
        if (indent > stack[stack.length - 1]) {
          html += '<ol>';
          stack.push(indent);
        } else {
          while (stack.length > 1 && indent < stack[stack.length - 1]) {
            html += '</li></ol>';
            stack.pop();
          }
          if (html) html += '</li>';
        }
        html += `<li>${text}`;
      });
      while (stack.length > 1) {
        html += '</li></ol>';
        stack.pop();
      }
      html += '</li>';
      const startAttr = startNum !== 1 ? ` start="${startNum}"` : '';
      return `<ol${startAttr}>${html}</ol>`;
    }

    // Mixed list (bullets + numbered at different indent levels)
    if (lines.every((l) => /^\s*[-*] /.test(l) || /^\s*\d+\.\s+/.test(l) || l.trim() === '')) {
      const listLines = lines.filter((l) => /^\s*[-*] /.test(l) || /^\s*\d+\.\s+/.test(l));
      if (listLines.length) {
        let html = '';
        const stack = [0];
        listLines.forEach((l) => {
          const indent = l.match(/^(\s*)/)[1].length;
          const text = applyInline(
            escapeHtml(l.replace(/^\s*[-*] /, '').replace(/^\s*\d+\.\s+/, '')),
          );
          if (indent > stack[stack.length - 1]) {
            html += '<ul>';
            stack.push(indent);
          } else {
            while (stack.length > 1 && indent < stack[stack.length - 1]) {
              html += '</li></ul>';
              stack.pop();
            }
            if (html) html += '</li>';
          }
          html += `<li>${text}`;
        });
        while (stack.length > 1) {
          html += '</li></ul>';
          stack.pop();
        }
        html += '</li>';
        return `<ul>${html}</ul>`;
      }
    }

    // Blockquote
    if (lines.every((l) => l.startsWith('> '))) {
      const inner = lines.map((l) => applyInline(escapeHtml(l.slice(2)))).join('<br>');
      return `<blockquote>${inner}</blockquote>`;
    }

    // Markdown table
    if (lines.length >= 2 && lines[0].includes('|') && /^\|?\s*[-:]+[-| :]*$/.test(lines[1])) {
      const parseRow = (r) =>
        r
          .replace(/^\|/, '')
          .replace(/\|$/, '')
          .split('|')
          .map((c) => c.trim());
      const headers = parseRow(lines[0]);
      const aligns = parseRow(lines[1]).map((c) => {
        if (c.startsWith(':') && c.endsWith(':')) return 'center';
        if (c.endsWith(':')) return 'right';
        return 'left';
      });
      const headHtml = headers
        .map(
          (h, i) =>
            `<th style="text-align:${aligns[i] || 'left'}">${applyInline(escapeHtml(h))}</th>`,
        )
        .join('');
      const bodyRows = lines
        .slice(2)
        .filter((l) => l.includes('|'))
        .map((r) =>
          parseRow(r)
            .map(
              (c, i) =>
                `<td style="text-align:${aligns[i] || 'left'}">${applyInline(escapeHtml(c))}</td>`,
            )
            .join(''),
        );
      return `<div class="table-wrap"><table><thead><tr>${headHtml}</tr></thead><tbody>${bodyRows.map((r) => `<tr>${r}</tr>`).join('')}</tbody></table></div>`;
    }

    // Mixed content with headings inside — process line by line
    if (lines.some((l) => l.startsWith('#'))) {
      return lines
        .map((l) => {
          const esc = escapeHtml(l);
          if (l.startsWith('#### ')) return `<h4>${applyInline(escapeHtml(l.slice(5)))}</h4>`;
          if (l.startsWith('### ')) return `<h3>${applyInline(escapeHtml(l.slice(4)))}</h3>`;
          if (l.startsWith('## ')) return `<h2>${applyInline(escapeHtml(l.slice(3)))}</h2>`;
          if (l.startsWith('# ')) return `<h1>${applyInline(escapeHtml(l.slice(2)))}</h1>`;
          return l.trim() ? `<p>${applyInline(esc)}</p>` : '';
        })
        .join('');
    }

    // Regular paragraph — join lines with a space (CommonMark: single \n = space)
    const content = lines.map((l) => applyInline(escapeHtml(l))).join(' ');
    return `<p>${content}</p>`;
  });

  // Restore code blocks
  let html = out.join('');
  html = html.replace(/\x00B(\d+)\x00/g, (_, i) => blocks[i]);
  return html;
}

/* ── Message Action Bar ──────────────────────────────── */

// Only the last assistant message should show the retry button.
function _refreshRetryVisibility() {
  const msgs = document.getElementById('messages');
  if (!msgs) return;
  const bars = [...msgs.querySelectorAll('.msg-action-bar')];
  bars.forEach((bar, i) => {
    const btn = bar.querySelector('.msg-retry-btn');
    if (!btn) return;
    btn.style.display = i === bars.length - 1 ? '' : 'none';
  });
}

function _addMsgActionBar(msgDiv, rawText, tokens) {
  const bubble = msgDiv.querySelector('.bubble');
  if (!bubble || msgDiv.querySelector('.msg-action-bar')) return;
  msgDiv.dataset.raw = rawText;

  const bar = document.createElement('div');
  bar.className = 'msg-action-bar';

  // Copy button
  const copyBtn = document.createElement('button');
  copyBtn.className = 'msg-action-btn';
  copyBtn.title = 'Copy';
  copyBtn.innerHTML =
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
  copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(msgDiv.dataset.raw || '').then(() => {
      copyBtn.classList.add('copied');
      copyBtn.innerHTML =
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>';
      setTimeout(() => {
        copyBtn.classList.remove('copied');
        copyBtn.innerHTML =
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
      }, 1500);
    });
  });
  bar.appendChild(copyBtn);

  // Retry button
  const retryBtn = document.createElement('button');
  retryBtn.className = 'msg-action-btn msg-retry-btn';
  retryBtn.title = 'Retry';
  retryBtn.innerHTML =
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
  retryBtn.addEventListener('click', () => {
    // Find the user message that preceded this response
    const allMsgs = [...document.querySelectorAll('#messages .message')];
    const idx = allMsgs.indexOf(msgDiv);
    const prevUser = idx > 0 ? allMsgs[idx - 1] : null;
    if (prevUser && prevUser.classList.contains('user')) {
      // Remove this assistant message and the user message from history
      const userText = history.findLast((m) => m.role === 'user')?.content;
      // Pop the assistant + user entries
      while (history.length && history[history.length - 1].role === 'assistant') history.pop();
      if (history.length && history[history.length - 1].role === 'user') history.pop();
      _saveActiveTabHistory();
      // Remove both messages from DOM
      msgDiv.remove();
      prevUser.remove();
      // Re-submit via the input
      const input = document.getElementById('chat-input');
      if (input && userText) {
        input.textContent = typeof userText === 'string' ? userText : JSON.stringify(userText);
        document.getElementById('chat-form')?.dispatchEvent(new Event('submit', { bubbles: true }));
      }
    }
  });
  bar.appendChild(retryBtn);

  // Fork to new tab button
  const forkBtn = document.createElement('button');
  forkBtn.className = 'msg-action-btn';
  forkBtn.title = 'Fork to new tab';
  forkBtn.innerHTML =
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9"/><path d="M12 12v3"/></svg>';
  forkBtn.addEventListener('click', async () => {
    // Find this message's index in DOM to determine how much history to copy
    const allMsgs = [...document.querySelectorAll('#messages .message')];
    const msgIdx = allMsgs.indexOf(msgDiv);
    // Count assistant and user messages up to this point to find history slice
    let histCount = 0;
    for (let i = 0; i <= msgIdx; i++) {
      if (allMsgs[i].classList.contains('user') || allMsgs[i].classList.contains('assistant'))
        histCount++;
    }
    const forkedHistory = history.slice(0, histCount);
    if (!forkedHistory.length) return;
    // Save current tab, create new one with forked history
    _saveActiveTabHistory();
    const sourceTabId = _activeTabId;
    const title =
      'Fork: ' + (_tabs.find((t) => t.id === sourceTabId)?.title || 'Chat').slice(0, 20);
    const tab = { id: _genTabId(), title, createdAt: Date.now() };
    _tabs.push(tab);

    // Clone pins from source tab and seed full conversation history server-side
    // so the LLM sees the same context the user does (not just last 10 turns).
    await Promise.all([
      fetch('/api/context/pins/clone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_context_id: sourceTabId, to_context_id: tab.id }),
      }).catch(() => {}),
      fetch(`/api/conversation/${tab.id}/seed`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: _sanitizeHistory(forkedHistory) }),
      }).catch(() => {}),
    ]);

    _activeTabId = tab.id;
    history = forkedHistory;
    _saveActiveTabHistory();
    _saveTabs();
    _renderTabBar();
    // Render forked messages
    const msgs = document.getElementById('messages');
    msgs.innerHTML = '';
    history.forEach((m) => {
      const div = document.createElement('div');
      div.className = 'message ' + m.role;
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.innerHTML =
        m.role === 'assistant'
          ? renderMarkdown(m.content || '')
          : escapeHtml(typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
      div.appendChild(bubble);
      msgs.appendChild(div);
      if (m.role === 'assistant' && m.content) {
        _addMsgActionBar(div, m.content);
      }
    });
    _refreshRetryVisibility();
    msgs.scrollTop = msgs.scrollHeight;
    _refreshPinOrb();
  });
  bar.appendChild(forkBtn);

  // Token usage label (subtle, right-aligned)
  if (tokens && (tokens.in || tokens.out)) {
    const tok = document.createElement('span');
    tok.className = 'msg-token-label';
    const inK = tokens.in >= 1000 ? (tokens.in / 1000).toFixed(1) + 'k' : tokens.in;
    const outK = tokens.out >= 1000 ? (tokens.out / 1000).toFixed(1) + 'k' : tokens.out;
    tok.textContent = inK + ' in · ' + outK + ' out';
    bar.appendChild(tok);
  }

  bubble.appendChild(bar);
}

/* ── Suggested Action Buttons ─────────────────────────── */
function _addSuggestedActions(msgDiv, rawText, explicitLabels) {
  const bubble = msgDiv.querySelector('.bubble');
  if (!bubble || msgDiv.querySelector('.suggested-actions')) return;

  const actions = [];
  const seen = new Set();

  function _stripMd(s) {
    return s
      .replace(/\*\*([^*]+)\*\*/g, '$1') // bold
      .replace(/\*([^*]+)\*/g, '$1') // italic
      .replace(/`([^`]+)`/g, '$1') // code
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // links
      .trim();
  }

  function _push(label) {
    const l = _stripMd(label)
      .replace(/[.?!]+$/, '')
      .trim();
    if (l.length < 3 || l.length > 100) return;
    const key = l.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      actions.push(l);
    }
  }

  // Split "X or Y" alternatives into separate buttons (e.g. "6/8 or 6/9" → two buttons)
  function _pushSplit(label) {
    const clean = _stripMd(label)
      .replace(/[.?!]+$/, '')
      .trim();
    // Only split on " or " if it appears exactly once and both sides are short options
    const orIdx = clean.toLowerCase().lastIndexOf(' or ');
    if (orIdx > 0) {
      const left = clean.slice(0, orIdx).trim();
      const right = clean.slice(orIdx + 4).trim();
      // Split only when both halves look like short choices (no spaces or very short phrases)
      if (left.length <= 40 && right.length <= 40 && left.length >= 1 && right.length >= 1) {
        _push(left);
        _push(right);
        return;
      }
    }
    _push(clean);
  }

  if (explicitLabels && explicitLabels.length) {
    explicitLabels.forEach(_push);
  } else {
    let m;
    // Pattern 1: say/reply/type/respond "..."
    const p1 =
      /(?:say|reply(?:\s+with)?|type|respond|tell\s+me)\s+["\u201c]([^"\u201d]{3,80})["\u201d]/gi;
    while ((m = p1.exec(rawText)) !== null) _push(m[1]);

    // Pattern 2: "..." to (verb) \u2014 e.g. "push to Confluence" to update the page
    const p2 = /["\u201c]([^"\u201d]{3,80})["\u201d]\s+to\s+\w+/gi;
    while ((m = p2.exec(rawText)) !== null) _push(m[1]);

    // Pattern 3: Would you like to X? / Want me to X? / Shall I X?
    // Use _pushSplit so "switch it to 6/8 or 6/9" becomes two buttons
    const p3 = /(?:would you like(?: me)? to|want me to|shall i|should i)\s+([^?.!]{5,80})[?.!]/gi;
    while ((m = p3.exec(rawText)) !== null) {
      const phrase = m[1].trim().toLowerCase();
      // If the phrase contains " or ", split into two "Yes, <option>" buttons
      const orIdx = phrase.lastIndexOf(' or ');
      if (orIdx > 0) {
        const verb = phrase
          .slice(0, phrase.indexOf(' or '))
          .replace(/\s+\S+$/, '')
          .trim(); // shared verb prefix
        const left = phrase.slice(0, orIdx).trim();
        const right = phrase.slice(orIdx + 4).trim();
        if (left.length <= 60 && right.length <= 40) {
          _push('Yes, ' + left);
          _push('Yes, ' + right);
          continue;
        }
      }
      _pushSplit('Yes, ' + phrase);
    }

    // Pattern 4: short numbered/bulleted options near end of response (up to 3)
    const tail = rawText.slice(-400);
    const optRe = /^(?:\d+[.)]\s*|[-*]\s*)(.{3,60})$/gm;
    let optCount = 0;
    while ((m = optRe.exec(tail)) !== null && optCount < 3) {
      const c = _stripMd(m[1].trim());
      if (/:\s*\S/.test(c) && c.split(':').length > 2) continue;
      _push(c);
      optCount++;
    }
  }

  if (!actions.length) return;

  const bar = document.createElement('div');
  bar.className = 'suggested-actions';

  actions.forEach((label) => {
    const btn = document.createElement('button');
    btn.className = 'suggested-action-btn';
    btn.textContent = label;
    btn.addEventListener('click', () => {
      const chatInput = document.getElementById('chat-input');
      if (!chatInput) return;
      chatInput.textContent = label;
      chatInput.dispatchEvent(new Event('input'));
      chatInput.focus();
      const form = document.getElementById('chat-form');
      if (form) form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    bar.appendChild(btn);
  });

  // Insert before the action bar so chips sit directly below message text
  const actionBar = bubble.querySelector('.msg-action-bar');
  if (actionBar) bubble.insertBefore(bar, actionBar);
  else bubble.appendChild(bar);
}

/* ── AI Gator Image Upload ───────────────────────────── */
let _aigatorImages = []; // [{name, mediaType, base64}]

function initAigatorUpload() {
  const attachBtn = document.getElementById('aigator-attach-btn');
  const fileIn = document.getElementById('aigator-file-input');
  const inputRow = document.getElementById('chat-input-row');
  if (!attachBtn || !fileIn) return;

  const _DOC_EXTENSIONS = new Set(['docx', 'doc', 'xlsx', 'xls', 'csv', 'pptx', 'ppt']);
  const _IMAGE_TYPES = new Set([
    'image/png',
    'image/jpeg',
    'image/webp',
    'image/gif',
    'application/pdf',
  ]);

  const processFiles = (files) => {
    const errEl = document.getElementById('aigator-drop-error');
    for (const file of files) {
      const ext = file.name.split('.').pop().toLowerCase();

      // Document files → upload to server temp, create file chip with real path
      if (_DOC_EXTENSIONS.has(ext)) {
        const formData = new FormData();
        formData.append('file', file);
        fetch('/api/file-upload-temp', { method: 'POST', body: formData })
          .then((r) => r.json())
          .then((data) => {
            if (data.ok && data.file_path) {
              const input = document.getElementById('chat-input');
              const fileIconSrc = {
                xlsx: '/static/icons/excel-file.png',
                xls: '/static/icons/excel-file.png',
                csv: '/static/icons/excel-file.png',
                docx: '/static/icons/word-file.png',
                doc: '/static/icons/word-file.png',
                pptx: '/static/icons/ppt-file.png',
                ppt: '/static/icons/ppt-file.png',
              }[ext];
              const chip = document.createElement('span');
              chip.className = 'pin-ref-chip file-ref-chip';
              chip.contentEditable = 'false';
              chip.dataset.filePath = data.file_path;
              chip.dataset.fileName = file.name;
              chip.title = file.name;
              if (fileIconSrc) {
                const icon = document.createElement('img');
                icon.src = fileIconSrc;
                icon.className = 'file-chip-icon';
                icon.alt = ext;
                chip.appendChild(icon);
              } else {
                chip.appendChild(document.createTextNode('\uD83D\uDCC1 '));
              }
              const nameSpan = document.createElement('span');
              nameSpan.className = 'file-chip-name';
              nameSpan.textContent = file.name;
              chip.appendChild(nameSpan);
              const removeBtn = document.createElement('button');
              removeBtn.type = 'button';
              removeBtn.className = 'file-chip-remove';
              removeBtn.setAttribute('aria-label', 'Remove ' + file.name);
              removeBtn.title = 'Remove';
              removeBtn.textContent = '\u2715';
              _wireChipRemove(removeBtn, chip, input);
              chip.appendChild(removeBtn);
              input.appendChild(chip);
              input.appendChild(document.createTextNode('\u00A0'));
              input.focus();
              if (typeof _moveCaretToEnd === 'function') _moveCaretToEnd(input);
              const skillMap = {
                docx: 'docx',
                doc: 'docx',
                xlsx: 'excel',
                xls: 'excel',
                csv: 'excel',
                pptx: 'ppt',
                ppt: 'ppt',
              };
              if (skillMap[ext]) selectSkill(skillMap[ext]);
            }
          })
          .catch(() => _showUploadError(errEl, 'Failed to upload document'));
        continue;
      }

      // Image/PDF files → upload as base64 for Claude vision
      if (_aigatorImages.length >= 5) {
        _showUploadError(errEl, 'Maximum 5 files');
        break;
      }
      if (!_IMAGE_TYPES.has(file.type)) {
        _showUploadError(errEl, `Unsupported file type: .${ext}`);
        continue;
      }
      if (file.size > 20 * 1024 * 1024) {
        _showUploadError(errEl, 'File exceeds 20MB limit');
        continue;
      }
      const imgEntry = { name: file.name, mediaType: file.type, base64: null, savedPath: null };
      _aigatorImages.push(imgEntry);
      _renderAigatorPreviews();
      const reader = new FileReader();
      reader.onload = (ev) => {
        imgEntry.base64 = ev.target.result.split(',')[1];
        _markPreviewLoaded(_aigatorImages.indexOf(imgEntry));
        if (_activeSkillId === 'gator') _showQuickActions(SKILL_MAP['gator']);
      };
      reader.readAsDataURL(file);
      // Issue #12: also save the image to disk so the AI can locate it (e.g. attach to GitHub)
      (async () => {
        try {
          const fd = new FormData();
          fd.append('file', file, file.name);
          const r = await fetch('/api/image-upload-temp', { method: 'POST', body: fd });
          const j = await r.json();
          if (j && j.ok && j.file_path) imgEntry.savedPath = j.file_path;
        } catch (e) {
          console.warn('image-upload-temp failed', e);
        }
      })();
    }
  };

  // Paperclip button
  attachBtn.addEventListener('click', () => fileIn.click());
  fileIn.addEventListener('change', () => {
    processFiles(fileIn.files);
    fileIn.value = '';
  });

  // Drag-and-drop on the input row
  inputRow?.addEventListener('dragover', (e) => {
    e.preventDefault();
    inputRow.classList.add('drag-over');
  });
  inputRow?.addEventListener('dragleave', (e) => {
    if (!inputRow.contains(e.relatedTarget)) inputRow.classList.remove('drag-over');
  });
  inputRow?.addEventListener('drop', (e) => {
    e.preventDefault();
    inputRow.classList.remove('drag-over');
    processFiles(e.dataTransfer.files);
  });

  // Drag-to-resize on chat input
  const _chatResizeHandle = document.getElementById('chat-resize-handle');
  const _chatInputEl = document.getElementById('chat-input');
  if (_chatResizeHandle && _chatInputEl) {
    let _rStartY, _rStartH;
    _chatResizeHandle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      _rStartY = e.clientY;
      _rStartH = _chatInputEl.offsetHeight;
      const onMove = (ev) => {
        const h = Math.min(
          window.innerHeight * 0.5,
          Math.max(32, _rStartH - (ev.clientY - _rStartY)),
        );
        _chatInputEl.style.height = h + 'px';
        _chatInputEl.style.maxHeight = h + 'px';
      };
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        // Mark that the user has manually set the height — auto-grow must not shrink below this.
        _chatInputEl.dataset.userResized = '1';
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  // Ctrl/Cmd+V paste into textarea
  document.getElementById('chat-input')?.addEventListener('paste', (e) => {
    const files = [...(e.clipboardData?.files || [])].filter(
      (f) => f.type.startsWith('image/') || f.type === 'application/pdf',
    );
    if (!files.length) return;
    // Office apps (PowerPoint/Word/Excel) put BOTH text and a rendered bitmap of
    // the selection on the clipboard. When real text is present, the image is just
    // a picture of that text — skip it so we don't attach a redundant image. Only
    // PDFs (real files) and genuine image-only pastes (screenshots) attach.
    const hasText = !!(e.clipboardData?.getData('text/plain') || '').trim();
    const keep = files.filter((f) => f.type === 'application/pdf' || !hasText);
    if (!keep.length) return; // text-only paste handled by the text paste handler
    e.preventDefault();
    processFiles(keep);
  });
}

function _showUploadError(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 4000);
}

function _renderAigatorPreviews() {
  const previews = document.getElementById('aigator-previews');
  const attachBtn = document.getElementById('aigator-attach-btn');
  if (!previews) return;
  previews.innerHTML = '';
  previews.classList.toggle('hidden', _aigatorImages.length === 0);
  attachBtn?.classList.toggle('has-files', _aigatorImages.length > 0);

  _aigatorImages.forEach((img, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'aigator-preview-item';
    const isPdf = img.mediaType === 'application/pdf';
    const dataUrl = !isPdf && img.base64 ? `data:${img.mediaType};base64,${img.base64}` : '';
    const thumbHtml = isPdf
      ? `<div class="aigator-pdf-thumb${img.base64 ? ' loaded' : ''}" id="agi-img-${i}" aria-label="${escapeHtml(img.name)}">📄</div>`
      : `<img src="${dataUrl}" alt="${escapeHtml(img.name)}" id="agi-img-${i}" class="${img.base64 ? 'loaded' : ''}">`;
    wrap.innerHTML = `
      <div class="aigator-preview-spinner${img.base64 ? ' hidden' : ''}" id="agi-spin-${i}"></div>
      ${thumbHtml}
      <span class="aigator-img-name">${escapeHtml(img.name)}</span>
      <button type="button" class="aigator-remove-btn" data-idx="${i}" aria-label="Remove ${escapeHtml(img.name)}">✕</button>`;
    wrap.querySelector('.aigator-remove-btn').addEventListener('click', () => {
      _aigatorImages.splice(i, 1);
      _renderAigatorPreviews();
      if (_activeSkillId === 'gator') _showQuickActions(SKILL_MAP['gator']);
    });
    previews.appendChild(wrap);
  });
}

function _markPreviewLoaded(idx) {
  document.getElementById(`agi-spin-${idx}`)?.classList.add('hidden');
  const el = document.getElementById(`agi-img-${idx}`);
  if (!el) return;
  const img = _aigatorImages[idx];
  if (!img?.base64) return;
  if (img.mediaType === 'application/pdf') {
    el.classList.add('loaded');
  } else {
    el.src = `data:${img.mediaType};base64,${img.base64}`;
    el.classList.add('loaded');
  }
}

function _aigatorClearImagesUI() {
  // Images cleared on send; attach button state updated via _renderAigatorPreviews
}

/* ── Chat Form Submit ────────────────────────────────── */
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  // Guard against double-submit — per-tab, not global. A stream running in
  // another tab must not block sending from this idle tab. The per-tab map
  // _chatTaskIds is the same source of truth switchTab uses to color the
  // send button, so the gate and the button can never disagree.
  if (_chatTaskIds.has(_activeTabId)) return;
  // No auto-dismiss — onboarding panel stays open alongside chat
  // Don't submit while a dropdown is open — the user is navigating, not sending
  if (_slashDropdown || _mentionDropdown || _pinDropdown || _channelDropdown) {
    console.log('[submit] BLOCKED — dropdown open');
    return;
  }
  closeMentionDropdown();
  _closeSlashDropdown();
  let typedText = _getInputText().trim();
  console.log(
    '[submit] typedText:',
    typedText?.slice(0, 80),
    'inputChildren:',
    input.childNodes.length,
  );
  // Collect resolved people from inline chips
  const inlinePeople = _getInlineChips()
    .filter((c) => c.classList.contains('chip-person'))
    .map((c) => ({ name: c.dataset.personName, email: c.dataset.personEmail }));
  if (inlinePeople.length) {
    window._resolvedPeople = inlinePeople;
  }
  // Collect pin reference chips before input is cleared
  const pinChips = [...input.querySelectorAll('.pin-ref-chip')].map((c) => ({
    label: (c.textContent || '').replace(/\s*✕\s*$/, '').trim(),
    source: c.dataset.pinSource || '',
    id: c.dataset.pinId || '',
  }));
  // File chips are already extracted by _getInputText() as [File: path]
  const hasFileChips = input.querySelector('[data-file-path]') !== null;
  // Collect file chip path→name mappings for display (show original name, not temp path)
  const fileChipNames = {};
  input.querySelectorAll('[data-file-path]').forEach((c) => {
    const p = c.dataset.filePath;
    const n = c.dataset.fileName || p.split(/[/\\]/).pop();
    if (p) fileChipNames[p] = n;
  });
  const finalText = buildFinalMessage(typedText);

  // Snapshot images before clearing UI
  const imagesSnapshot = [..._aigatorImages];
  const hasImages = imagesSnapshot.length > 0 && imagesSnapshot.every((i) => i.base64);

  if (!_canSubmitMessage(finalText, hasFileChips, hasImages)) return;

  // Build display HTML (typed text + image thumbnails)
  // Chips are NOT prepended to the display bubble — they're shown in the chip
  // row above the input, which is enough context. Only inline @skill mentions
  // (typed by the user) are pillified in-place below.
  const chipHtml = '';
  const imgHtml = hasImages
    ? imagesSnapshot
        .map(
          (img) =>
            `<img src="data:${img.mediaType};base64,${img.base64}" style="height:40px;border-radius:4px;margin-right:4px;vertical-align:middle" alt="${escapeHtml(img.name)}">`,
        )
        .join('')
    : '';
  // Replace @skill aliases and #channel names inline with styled chip HTML
  // so they stay in-place instead of being stripped and re-prepended.
  let displayText = typedText;

  // Replace @skill aliases with inline chip spans
  // Replace @skill aliases with inline chip spans
  // Use (?:^|\s) prefix so we don't match @ inside email addresses
  _activeChips.forEach((c) => {
    const s = SKILL_MAP[c.skillId];
    const alias = s?.chipAlias || c.skillId;
    const chipSpan = `<span class="chat-chip ${s.chipClass}" style="font-size:.7rem;pointer-events:none">/${escapeHtml(alias)}</span>`;
    displayText = displayText.replace(new RegExp(`(?:^|\\s)[@/]${alias}\\b`, 'gi'), (full) => {
      const prefix = full.match(/^\s/)?.[0] || '';
      return `${prefix}\x00CHIP${chipSpan}\x00`;
    });
  });
  // Fallback: pillify any /<skill> or @<alias> token that matches a known skill
  // but wasn't covered by _activeChips (e.g. user typed the slash command directly).
  // IMPORTANT: only scan segments that aren't already wrapped chip-HTML, otherwise
  // we'd match /startup-update *inside* an existing chip span and even /span inside </span>.
  displayText = displayText
    .split('\x00')
    .map((segment, i) => {
      // Odd-indexed segments are CHIP payloads (between the markers) — leave untouched.
      if (i % 2 === 1) return segment;
      // Skip URL segments — don't chipify /path parts inside https://... URLs
      if (/https?:\/\//i.test(segment)) return segment;
      return segment.replace(/(?:^|\s)[@/]([a-z0-9][a-z0-9_-]*)/gi, (full, name) => {
        // Don't pillify @ in email addresses — an @ preceded by a word char
        // (no space) is part of an email, not a skill mention.
        const prefix = full.match(/^\s/)?.[0] || '';
        const lower = name.toLowerCase();
        let s = SKILL_MAP[lower];
        if (!s) {
          s = Object.values(SKILL_MAP).find((x) => (x.chipAlias || '').toLowerCase() === lower);
        }
        if (!s) return full;
        const alias = s.chipAlias || s.id || lower;
        const chipSpan = `<span class="chat-chip ${s.chipClass || ''}" style="font-size:.7rem;pointer-events:none">/${escapeHtml(alias)}</span>`;
        return `${prefix}\x00CHIP${chipSpan}\x00`;
      });
    })
    .join('\x00');

  // Replace #channel names with inline chip spans so they stay styled in the
  // sent bubble (not just the prompt bar). Source the names from BOTH the live
  // chip elements in the input AND _activeChannels — relying on _activeChannels
  // alone dropped the chip style whenever that array was empty/cleared at send.
  const _chanNames = new Map(); // name -> chipClass
  try {
    const _inp = document.getElementById('chat-input');
    if (_inp)
      _inp.querySelectorAll('.chip-channel').forEach((c) => {
        const n = c.dataset.channelName;
        if (n) _chanNames.set(n, c.classList.contains('chip-slack') ? 'chip-slack' : 'chip-teams');
      });
  } catch (_) {}
  _activeChannels.forEach((ch) => {
    if (ch.channel_name && !_chanNames.has(ch.channel_name)) {
      _chanNames.set(ch.channel_name, ch.type === 'slack_channel' ? 'chip-slack' : 'chip-teams');
    }
  });
  // Replace longest names first so a channel that's a prefix of another doesn't
  // partially match (e.g. "#aipc" vs "#aipc-task-force").
  [..._chanNames.entries()]
    .sort((a, b) => b[0].length - a[0].length)
    .forEach(([name, cls]) => {
      const chanSpan = `<span class="chat-chip ${cls}" style="font-size:.7rem;pointer-events:none">#${escapeHtml(name)}</span>`;
      displayText = displayText.replace(
        new RegExp(`#${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'gi'),
        `\x00CHIP${chanSpan}\x00`,
      );
    });
  // Replace [Pin: source:id] text with inline pin chip spans (display)
  pinChips.forEach((p) => {
    const pinToken = `[Pin: ${p.source}:${p.id}]`;
    const pinSpan = `<span class="pin-ref-chip" data-pin-source="${escapeHtml(p.source)}" data-pin-id="${escapeHtml(p.id)}" style="pointer-events:none">${escapeHtml(p.label)}</span>`;
    displayText = displayText.split(pinToken).join(`\x00CHIP${pinSpan}\x00`);
  });
  // Replace [File: temppath] with the original filename for display
  Object.entries(fileChipNames).forEach(([path, name]) => {
    displayText = displayText.replace(
      `[File: ${path}]`,
      `\x00CHIP<span class="pin-ref-chip file-ref-chip" style="pointer-events:none">\uD83D\uDCC1 ${escapeHtml(name)}</span>\x00`,
    );
  });

  // Split on chip markers, escape text segments, preserve newlines
  const parts = displayText.split('\x00');
  const bodyHtml = parts
    .map((part) => {
      if (part.startsWith('CHIP')) return part.slice(4); // already HTML
      return escapeHtml(part).replace(/\n/g, '<br>');
    })
    .join('');
  const chipPrefix = chipHtml ? chipHtml + ' ' : '';
  const displayHtml = imgHtml + chipPrefix + bodyHtml;

  // Snapshot active skills + channels before clearing (for the API payload)
  const activeSkillsSnapshot = _activeChips.map((c) => c.skillId);
  const activeChannelsSnapshot = [..._activeChannels];

  // Clear chips and resolved people
  _activeChips = [];
  window._resolvedPeople = [];
  document.getElementById('chat-chip-row').innerHTML = '';

  // Re-add the active skill chip so context persists across messages
  if (_activeSkillId) {
    _addSkillChip(_activeSkillId);
  }
  // In Gator mode, also persist any @mentioned skill chips so the prompt
  // area still shows what context is active and carries it forward.
  if (_activeSkillId === 'gator') {
    activeSkillsSnapshot.filter((s) => s !== 'gator').forEach((s) => _addSkillChip(s));
  }
  // Persist #channel chips across messages; ensure teams skill is active when channels exist
  _activeChannels = activeChannelsSnapshot;
  if (activeChannelsSnapshot.length && !_activeChips.some((c) => c.skillId === 'teams')) {
    _addSkillChip('teams');
  }
  activeChannelsSnapshot.forEach((ch) => _addChannelChip(ch));
  _ensureAddSkillBtn();
  _updatePlaceholder();

  // Clear images after send
  if (hasImages) {
    _aigatorImages = [];
    _renderAigatorPreviews();
    if (_activeSkillId === 'gator') _showQuickActions(SKILL_MAP['gator']);
  }

  addMessage('user', displayHtml);

  // Build message payload: vision blocks + text when images present
  // An image-only prompt (no typed text) must NOT include an empty text block —
  // Vertex AI rejects it with "messages: text content blocks must be non-empty".
  const messagePayload = hasImages
    ? [
        ...imagesSnapshot.map((img) =>
          img.mediaType === 'application/pdf'
            ? {
                type: 'document',
                source: { type: 'base64', media_type: 'application/pdf', data: img.base64 },
              }
            : {
                type: 'image',
                source: { type: 'base64', media_type: img.mediaType, data: img.base64 },
              },
        ),
        ...(finalText.trim() ? [{ type: 'text', text: finalText }] : []),
      ]
    : finalText;

  const requestTabId = _activeTabId || _tabs[0]?.id || 'default';
  const requestContextId = requestTabId || 'default';
  const requestHistory = history;

  requestHistory.push({ role: 'user', content: finalText });
  _saveTabHistory(requestTabId, requestHistory);
  // Trim display store to match surviving user turns in the history window
  const _survivingUserTurns = requestHistory
    .slice(-HISTORY_MAX)
    .filter((m) => m.role === 'user').length;
  _saveTabDisplayHtml(requestTabId, displayHtml, _survivingUserTurns);
  input.textContent = '';
  input.style.height = 'auto';
  delete input.dataset.userResized;
  _updateSendSlot();

  // Switch button to stop mode
  sendBtn.disabled = false;
  sendBtn.classList.add('is-streaming');
  sendBtn.setAttribute('aria-label', 'Stop generating');
  sendBtn.type = 'button'; // prevent form submit while streaming
  setStatus('busy');

  const prose = addMessage('assistant', '');
  const msgDiv = prose.closest('.message');
  msgDiv.classList.add('typing');

  let full = '';
  let thinkingText = '';
  let lastThinkingAgent = null;
  const _agentThinking = { planner: '', executor: '', verifier: '' };
  const _agentDone = { planner: false, executor: false, verifier: false };
  let _lastSeenAgent = null;
  let _threeAgentMode = false;
  let _totalInputTokens = 0;
  let _totalOutputTokens = 0;
  let statusLines = [];
  let toastLines = [];
  let autoSkills = [];
  let toolCallCards = [];
  let fileChipsDiv = null;
  let _streamExhausted = false;
  let _exhaustedMessage = '';
  let _abortCtrl = new AbortController();
  _isStreaming = true;
  let _lastTokenAt = Date.now();
  let _userCollapsedThinking = false;
  const _DOTS_HTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';

  // Stop button handler — close EventSource + cancel server task + cancel browser task
  let _userStopped = false;
  const _onStop = () => {
    _userStopped = true;
    _isStreaming = false; // stops the typing-dots interval (see line ~6089) so the animation halts
    if (_abortCtrl._es) {
      _abortCtrl._es.close();
      _abortCtrl._es = null;
    }
    const _stopTabKey = _activeTabId || 'default';
    const _stopTaskId = _chatTaskIds.get(_stopTabKey);
    if (_stopTaskId) {
      fetch(`/api/chat/${_stopTaskId}/cancel`, { method: 'POST' }).catch(() => {});
      _chatTaskIds.delete(_stopTabKey);
      _inflightRequests.delete(_stopTabKey);
    }
    fetch('/api/browser/cancel', { method: 'POST' }).catch(() => {});
    // EventSource.close() does NOT fire onerror, so the awaiting promise would hang
    // and _resetBtn() would never run — manually resolve so cleanup proceeds and the
    // button returns to send (green) mode.
    if (_abortCtrl._resolve) {
      const r = _abortCtrl._resolve;
      _abortCtrl._resolve = null;
      r();
    }
  };
  sendBtn.addEventListener('click', _onStop, { once: true });

  // Escape also stops generation while streaming
  const _onEscStop = (e) => {
    if (e.key === 'Escape') _onStop();
  };
  document.addEventListener('keydown', _onEscStop);

  const _resetBtn = () => {
    sendBtn.removeEventListener('click', _onStop);
    document.removeEventListener('keydown', _onEscStop);
    sendBtn.classList.remove('is-streaming');
    sendBtn.setAttribute('aria-label', 'Send message');
    sendBtn.type = 'submit';
    sendBtn.disabled = false;
  };

  // Shared send logic — extracted so the retry button can re-invoke it.
  // When called with overridePayload (from permission approve), skips input
  // parsing and posts the saved payload directly so post-stream work runs normally.
  const doSend = async (overridePayload) => {
    _userScrolledUp = false;
    _browserHITLShown = false;
    full = '';
    thinkingText = '';
    lastThinkingAgent = null;
    _agentThinking.planner = '';
    _agentThinking.executor = '';
    _agentThinking.verifier = '';
    _agentDone.planner = false;
    _agentDone.executor = false;
    _agentDone.verifier = false;
    _lastSeenAgent = null;
    _threeAgentMode = false;
    _totalInputTokens = 0;
    _totalOutputTokens = 0;
    _userCollapsedThinking = false;
    statusLines = [];
    toastLines = [];
    autoSkills = [];
    toolCallCards = [];
    _isStreaming = true;
    msgDiv.classList.add('typing');
    setStatus('busy');
    prose.innerHTML = '';

    const renderStatusHtml = () => {
      if (!statusLines.length && !toastLines.length) return '';
      const lines = [...statusLines.map((text) => ({ text, level: 'info' })), ...toastLines];
      return `<div class="status-steps">${lines
        .map((line) => {
          const lvl = line.level || 'info';
          const cls = ['status-line'];
          if (lvl === 'warn') cls.push('status-line-warn');
          else if (lvl === 'error') cls.push('status-line-error');
          else if (lvl === 'success') cls.push('status-line-success');
          return `<div class="${cls.join(' ')}">${escapeHtml(line.text)}</div>`;
        })
        .join('')}</div>`;
    };
    const _renderProse = () => {
      let html = '';

      if (_threeAgentMode) {
        const META = {
          planner: { icon: '\uD83D\uDCCB', label: 'Planning' },
          executor: { icon: '\u2699\uFE0F', label: 'Working' },
          verifier: { icon: '\u2713', label: 'Checking' },
        };
        const anyThinking = Object.values(_agentThinking).some((t) => t);
        if (anyThinking) {
          const allDone = ['planner', 'executor', 'verifier'].every((k) => _agentDone[k]);
          const parentLabel = allDone ? 'Gator worked in 3 steps \u2705' : 'Gator is working...';
          let inner = '';
          for (const key of ['planner', 'executor', 'verifier']) {
            const text = _agentThinking[key];
            if (!text) continue;
            const m = META[key];
            const running = _lastSeenAgent === key && !_agentDone[key];
            const badge = _agentDone[key] ? ' \u2705 done' : running ? ' \u23F3 running...' : '';
            inner +=
              '<details class="agent-sub-block"' +
              (running ? ' open' : '') +
              '>' +
              '<summary>' +
              m.icon +
              ' ' +
              m.label +
              badge +
              '</summary>' +
              '<div class="agent-sub-content">' +
              renderMarkdown(text) +
              '</div>' +
              '</details>';
          }
          // Open the outer thinking-block while streaming (unless user
          // manually collapsed it). _userCollapsedThinking is set by the
          // toggle handler installed after each re-render (see below).
          const _thinkingOpen = _isStreaming && !_userCollapsedThinking ? ' open' : '';
          html +=
            '<details class="thinking-block"' +
            _thinkingOpen +
            '><summary>' +
            parentLabel +
            '</summary>' +
            inner +
            '</details>';
        }
      } else if (thinkingText) {
        const _thinkingOpen = _isStreaming && !_userCollapsedThinking ? ' open' : '';
        html +=
          '<details class="thinking-block"' +
          _thinkingOpen +
          '><summary>Reasoning</summary>' +
          '<div class="thinking-content">' +
          renderMarkdown(thinkingText) +
          '</div></details>';
      }

      if (autoSkills.length) {
        const chips = autoSkills
          .map((s) => `<span class="auto-skill-chip">${escapeHtml(s.label || s.id)}</span>`)
          .join(' ');
        html += `<div class="auto-skills-strip"><span class="auto-skills-label">Auto-selected skills</span>${chips}</div>`;
      }
      const statusHtml = renderStatusHtml();
      if (statusHtml) html += statusHtml;
      if (toolCallCards.length) {
        html += '<div class="tool-call-cards">';
        for (const tc of toolCallCards) {
          const tcIcon =
            { receiving: '⏳', executing: '🔧', success: '✅', error: '❌' }[tc.status] || '⏳';
          let tcDetail = '';
          if (tc.status === 'receiving') {
            tcDetail = `Receiving arguments... (${tc.bytesReceived.toLocaleString()} bytes)`;
          } else if (tc.status === 'executing') {
            tcDetail = `Executing ${tc.toolName}...`;
          } else {
            tcDetail = tc.result || (tc.status === 'success' ? 'Completed' : 'Failed');
          }
          const tcPreview = tc.preview
            ? `<span class="tc-preview">${escapeHtml(tc.preview)}</span>`
            : '';
          html +=
            `<div class="tool-call-card">` +
            `<span class="tc-icon">${tcIcon}</span>` +
            `<span class="tc-name">${escapeHtml(tc.toolName)}</span>` +
            `${tcPreview}` +
            `<span class="tc-detail">${escapeHtml(tcDetail)}</span>` +
            `</div>`;
        }
        html += '</div>';
      }
      if (_isStreaming && _activeToolNames.size > 0) {
        const toolChips = [..._activeToolNames]
          .map((name) => {
            const skill = SKILL_REGISTRY.find((s) => s.id === name);
            const label = skill ? skill.label : name;
            return `<span class="active-tool-chip tool-chip">⚙️ ${escapeHtml(label)}…</span>`;
          })
          .join(' ');
        html += `<div class="active-tools-strip">${toolChips}</div>`;
      }
      if (full) {
        if (statusHtml)
          html +=
            '<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:.4rem 0 .7rem">';
        html += renderMarkdown(full);
      }
      // Dots are managed by _dotsInterval directly on the DOM — not injected here
      return html;
    };

    // Throttle DOM updates: render immediately if >50ms since last render
    // (keeps streaming responsive — reasoning and tool calls appear in
    // real-time), but batch rapid tokens via requestAnimationFrame to reduce
    // flicker. The previous approach (rAF only) broke streaming because rAF
    // doesn't fire during synchronous SSE event processing, so all renders
    // queued up and only fired at [DONE].
    let _pendingRender = false;
    let _lastRenderTime = 0;
    const _scheduleRender = () => {
      const now = performance.now();
      if (now - _lastRenderTime > 50) {
        _lastRenderTime = now;
        prose.innerHTML = _renderProse();
        if (!_dotsPlaceholder.parentElement) prose.appendChild(_dotsPlaceholder);
        return;
      }
      if (_pendingRender) return;
      _pendingRender = true;
      requestAnimationFrame(() => {
        _pendingRender = false;
        _lastRenderTime = performance.now();
        prose.innerHTML = _renderProse();
        if (!_dotsPlaceholder.parentElement) prose.appendChild(_dotsPlaceholder);
      });
    };

    // Show initial status + dots immediately (before first SSE event)
    statusLines.push('Gator is on it...');
    // Always create the typing-dots placeholder in the DOM — toggle visibility
    // instead of add/remove so scrollHeight never changes (fixes flicker).
    const _dotsPlaceholder = document.createElement('div');
    _dotsPlaceholder.className = 'typing-dots';
    _dotsPlaceholder.innerHTML = '<span></span><span></span><span></span>';
    _dotsPlaceholder.style.visibility = 'hidden';
    prose.appendChild(_dotsPlaceholder);
    prose.innerHTML = _renderProse();
    // Re-append after innerHTML wipe and keep reference
    prose.appendChild(_dotsPlaceholder);

    // Event delegation: track when the user collapses the thinking block so
    // it stays collapsed across re-renders (prose.innerHTML rebuilds the
    // <details> each time, losing the open attribute). Without this, every
    // SSE token would re-open the block the user just closed.
    prose.addEventListener(
      'toggle',
      (e) => {
        if (e.target.classList && e.target.classList.contains('thinking-block')) {
          if (!e.target.open) _userCollapsedThinking = true;
          // If the user re-opens it, let it stay open
          else _userCollapsedThinking = false;
        }
      },
      true,
    ); // capture phase — toggle doesn't bubble

    // Poll every 200ms to show/hide dots during silent tool-call gaps.
    // Toggles visibility only — never adds/removes from DOM, so scrollHeight
    // stays constant and there's no scroll flicker.
    const _dotsInterval = setInterval(() => {
      if (!_isStreaming) {
        clearInterval(_dotsInterval);
        _dotsPlaceholder.remove();
        return;
      }
      const wantDots = !full || Date.now() - _lastTokenAt > 400;
      // Re-append if _renderProse() wiped it (happens on every SSE event)
      if (!_dotsPlaceholder.parentElement) prose.appendChild(_dotsPlaceholder);
      _dotsPlaceholder.style.visibility = wantDots ? 'visible' : 'hidden';
      // Do NOT set scrollTop here — the SSE token handler drives auto-scroll
      // on real content changes. Setting it here caused the flicker (dots
      // add/remove changed scrollHeight, then this scrolled to the new bottom,
      // then dots were removed and scrollHeight shrank back).
    }, 200);

    // MVP: browser pane disabled — using external browser only.
    // Pane code kept for future headless/Gator's Browser mode.
    const _browserPoll = setInterval(() => {}, 99999); // no-op placeholder

    // Save payload so the permission_required handler can re-POST without relying on
    // the (already-cleared) input field.  Built here, before the fetch, so all the
    // snapshot variables are still in scope.
    let _permissionResendPayload = {
      message: messagePayload,
      history: _sanitizeHistory(history.slice(-10)),
      has_images: hasImages,
      image_names: imagesSnapshot.map((i) => i.name),
      image_paths: imagesSnapshot.map((i) => i.savedPath).filter(Boolean),
      active_skill: _activeSkillId || '',
      active_skills: activeSkillsSnapshot,
      active_channels: activeChannelsSnapshot,
      context_id: _activeTabId || 'default',
      model: window._currentModel || '',
    };
    try {
      // Step 1: POST to get task_id (fast, returns immediately)
      const _postBody = overridePayload
        ? overridePayload
        : {
            message: messagePayload,
            history: _sanitizeHistory(history.slice(-10)),
            has_images: hasImages,
            image_names: imagesSnapshot.map((i) => i.name),
            image_paths: imagesSnapshot.map((i) => i.savedPath).filter(Boolean),
            active_skill: _activeSkillId || '',
            active_skills: activeSkillsSnapshot,
            active_channels: activeChannelsSnapshot,
            context_id: _activeTabId || 'default',
            model: window._currentModel || '',
            unapproved_deps: _getUnapprovedDeps(_activeSkillId || ''),
          };
      const postRes = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(_postBody),
      });

      if (!postRes.ok) {
        let detail = '';
        try {
          const j = await postRes.json();
          detail = j.detail || j.error || '';
        } catch {
          detail = await postRes.text().catch(() => '');
        }
        const hint = detail
          ? `<div class="err-detail">${escapeHtml(String(detail).slice(0, 200))}</div>`
          : '';
        const errHtml = `<div class="err-bubble"><span class="err-icon">&#x26A0;&#xFE0F;</span><span>Something went wrong (${postRes.status}). You can retry or rephrase your message.</span>${hint}<button class="retry-btn">&#x21BA; Retry</button></div>`;
        prose.textContent = '';
        prose.insertAdjacentHTML('afterbegin', errHtml);
        prose.querySelector('.retry-btn')?.addEventListener('click', doSend);
        _isStreaming = false;
        msgDiv.classList.remove('typing');
        _resetBtn();
        setStatus('ready');
        return;
      }

      const { task_id } = await postRes.json();
      const _tabKey = _activeTabId || 'default';
      _chatTaskIds.set(_tabKey, task_id);
      _setTabWorking(requestTabId, true);

      // Register msgDiv so switchTab() can re-attach it if the user switches away
      _inflightRequests.set(_tabKey, { msgDiv, task_id });

      // Step 2: Stream chunks via EventSource (auto-reconnects with Last-Event-ID)
      // _sawDone tracks whether the stream closed cleanly. If the connection is
      // permanently severed (server reload/crash, network drop, timeout) before
      // [DONE], we must offer a recovery affordance instead of freezing on the
      // last token — the buffered chunks may be gone, so reconnect can't resume.
      let _sawDone = false;
      await new Promise((resolve, reject) => {
        const es = new EventSource(`/api/chat/stream/${task_id}`);
        _abortCtrl._es = es;
        _abortCtrl._resolve = resolve; // let _onStop unblock this await

        es.onmessage = (e) => {
          const payload = e.data;
          if (payload === '[DONE]') {
            _sawDone = true;
            _isStreaming = false;
            es.close();
            _chatTaskIds.delete(_tabKey);
            _inflightRequests.delete(_tabKey);
            _userScrolledUp = false;
            prose.innerHTML = _renderProse();
            resolve();
            return;
          }
          try {
            const msg = JSON.parse(payload);
            if ('token' in msg) {
              // Streaming token -- progressive text rendering. _joinStreamToken
              // re-inserts a space dropped at the chunk boundary (issue #52).
              const tok = msg.token;
              full += _joinStreamToken(full, tok);
              _lastTokenAt = Date.now();
              _scheduleRender();
            } else if ('thinking' in msg) {
              const agent = msg.agent || null;
              if (agent && ['planner', 'executor', 'verifier'].includes(agent)) {
                _threeAgentMode = true;
                if (_lastSeenAgent && _lastSeenAgent !== agent) {
                  _agentDone[_lastSeenAgent] = true;
                }
                _lastSeenAgent = agent;
                _agentThinking[agent] += msg.thinking;
              } else {
                thinkingText += msg.thinking;
                lastThinkingAgent = null;
              }
              _scheduleRender();
            } else if (msg.browser_confirm) {
              _showBrowserConfirmCard(msgDiv, msg.browser_confirm);
            } else if (msg.failover_confirm) {
              _showFailoverConfirmCard(msgDiv, msg.failover_confirm);
            } else if (msg.browser_hitl) {
              if (msg.browser_hitl === 'active') {
                // Remove confirm card if it wasn't dismissed (edge case)
                const confirmCard = document.getElementById('browser-confirm-card');
                if (confirmCard) confirmCard.remove();
                _showBrowserHITL(msgDiv);
              } else if (msg.browser_hitl === 'done') {
                const card = document.getElementById('browser-hitl-card');
                if (card) {
                  card.remove();
                  _browserHITLShown = false; // only reset if we actually had a card
                }
                // if no card, stale 'done' signal — ignore
              }
            } else if (msg.tool_call_start) {
              toolCallCards.push({
                callId: msg.tool_call_start.call_id,
                toolName: msg.tool_call_start.tool_name,
                status: 'receiving',
                bytesReceived: 0,
                preview: null,
                result: null,
              });
              _scheduleRender();
            } else if (msg.tool_call_progress) {
              const _tc = toolCallCards.find((c) => c.callId === msg.tool_call_progress.call_id);
              if (_tc) _tc.bytesReceived = msg.tool_call_progress.bytes_received;
              _scheduleRender();
            } else if (msg.tool_call_complete) {
              const _tc = toolCallCards.find((c) => c.callId === msg.tool_call_complete.call_id);
              if (_tc) {
                _tc.status = 'executing';
                _tc.preview = msg.tool_call_complete.argument_preview;
              }
              _scheduleRender();
            } else if (msg.tool_result) {
              const _tc = toolCallCards.find((c) => c.callId === msg.tool_result.call_id);
              if (_tc) {
                _tc.status = msg.tool_result.status;
                _tc.result = msg.tool_result.summary;
              }
              _scheduleRender();
            } else if (msg.status) {
              statusLines.push(msg.status);
              _scheduleRender();
              // Only update tool strip when user is on the submitting tab
              if (_activeTabId === _tabKey) {
                for (const skill of SKILL_REGISTRY) {
                  if (skill.id !== 'gator' && msg.status.toLowerCase().includes(skill.id)) {
                    _updateActiveTools(skill.id, true);
                    break;
                  }
                }
              }
            } else if (msg.skills_auto) {
              autoSkills = Array.isArray(msg.skills_auto) ? msg.skills_auto : [];
              _scheduleRender();
            } else if (msg.compaction) {
              // Seam marker: history was just rewritten server-side. Persist it
              // separately from `history` (never mixed into the LLM-facing
              // transcript) and render it inline if the user is still on this tab.
              const { turn_count, summary_text } = msg.compaction;
              const markers = _loadTabCompactions(requestTabId);
              markers.push({
                afterIndex: requestHistory.length - 1,
                turnCount: turn_count,
                summaryText: summary_text,
              });
              _saveTabCompactions(requestTabId, markers);
              if (_activeTabId === requestTabId && msgDiv && msgDiv.parentNode) {
                msgDiv.parentNode.insertBefore(
                  _buildCompactionMarker(turn_count, summary_text),
                  msgDiv,
                );
              }
            } else if (msg.toast) {
              const toast = msg.toast || {};
              const levelRaw =
                typeof toast.level === 'string' ? toast.level.toLowerCase() : 'error';
              const mapped =
                levelRaw === 'warning'
                  ? 'warn'
                  : ['success', 'info', 'warn', 'error'].includes(levelRaw)
                    ? levelRaw
                    : 'error';
              const message =
                typeof toast.message === 'string' && toast.message.trim()
                  ? toast.message.trim()
                  : 'Tool reported an issue.';
              _showConnectivityToast(message, mapped);
              toastLines.push({ text: message, level: mapped });
              _scheduleRender();
            } else if (msg.text) {
              // Fallback: non-streaming chunked text (backward compat)
              full += msg.text;
              _scheduleRender(); // same sanitized call used everywhere else in this block
            } else if (msg.usage) {
              _totalInputTokens = msg.usage.input_tokens || 0;
              _totalOutputTokens = msg.usage.output_tokens || 0;
              _contextUsed = _totalInputTokens;
              _updateContextMeter();
            } else if (msg.pane) {
              console.log('[chat-stream] pane signal received:', msg.pane);
              _handlePaneSignal(msg.pane, msg.paneData || {});
            } else if (msg.draft) {
              _injectDraftApprovalCard(msg.draft, msg.draftData || {});
            } else if (msg.files && Array.isArray(msg.files) && msg.files.length) {
              if (!fileChipsDiv) {
                fileChipsDiv = document.createElement('div');
                fileChipsDiv.className = 'output-files-row';
              }
              msg.files.forEach((f) => {
                const wrapper = document.createElement('div');
                wrapper.className = 'ofc-wrapper';

                // ── Card ──
                const card = document.createElement('div');
                card.className = 'output-file-card';

                const iconSrc = _fileIconImg(f.mime_type || '', f.name || '');
                let iconEl;
                if (iconSrc) {
                  iconEl = document.createElement('img');
                  iconEl.className = 'ofc-icon ofc-icon-img';
                  iconEl.src = iconSrc;
                  iconEl.alt = '';
                } else {
                  iconEl = document.createElement('span');
                  iconEl.className = 'ofc-icon';
                  iconEl.textContent = _fileIcon(f.mime_type || '');
                }

                const textCol = document.createElement('span');
                textCol.className = 'ofc-text';

                const nameEl = document.createElement('span');
                nameEl.className = 'ofc-name';
                nameEl.title = f.name;
                nameEl.textContent = f.name;

                const mimeLabel = _friendlyMimeLabel(f.mime_type || '', f.name || '');
                const sizeLabel = _formatBytes(f.size_bytes);
                const metaText = [mimeLabel, sizeLabel].filter(Boolean).join(' \u00B7 ');
                const metaEl = document.createElement('span');
                metaEl.className = 'ofc-meta';
                metaEl.textContent = metaText;

                textCol.appendChild(nameEl);
                if (metaText) textCol.appendChild(metaEl);

                const actionsEl = document.createElement('span');
                actionsEl.className = 'ofc-actions';

                const mime = f.mime_type || '';
                const isImage = mime.startsWith('image/');
                const isPdf = mime === 'application/pdf';
                const isText = mime.startsWith('text/') || mime === 'application/json';

                // [Open] only for types with no inline preview
                if (!isImage && !isPdf && !isText) {
                  const openBtn = document.createElement('a');
                  openBtn.className = 'ofc-btn';
                  openBtn.href = f.download_url;
                  openBtn.target = '_blank';
                  openBtn.rel = 'noopener noreferrer';
                  openBtn.textContent = 'Open';
                  actionsEl.appendChild(openBtn);
                }

                const dlBtn = document.createElement('a');
                dlBtn.className = 'ofc-btn ofc-btn-dl';
                dlBtn.href = f.download_url;
                dlBtn.download = f.name;
                dlBtn.textContent = 'Download';

                // Share dropdown
                const shareWrap = document.createElement('span');
                shareWrap.className = 'ofc-share-wrap';

                const shareBtn = document.createElement('button');
                shareBtn.className = 'ofc-btn ofc-btn-share';
                shareBtn.textContent = 'Share \u25BE';

                const shareMenu = document.createElement('div');
                shareMenu.className = 'ofc-share-menu';
                shareMenu.style.display = 'none';

                const _shareChannels = [
                  { label: 'Teams', prompt: 'Share the file via Teams' },
                  { label: 'Slack', prompt: 'Share the file via Slack' },
                  { label: 'Email', prompt: 'Share the file via Email' },
                ];
                _shareChannels.forEach((ch) => {
                  const opt = document.createElement('button');
                  opt.className = 'ofc-share-opt';
                  opt.textContent = ch.label;
                  opt.onclick = (e) => {
                    e.stopPropagation();
                    shareMenu.style.display = 'none';
                    // Trigger file download
                    const tmpA = document.createElement('a');
                    tmpA.href = f.download_url;
                    tmpA.download = f.name;
                    document.body.appendChild(tmpA);
                    tmpA.click();
                    document.body.removeChild(tmpA);
                    // Submit compose prompt
                    const chatInput = document.getElementById('chat-input');
                    const chatForm = document.getElementById('chat-form');
                    if (chatInput && chatForm) {
                      chatInput.textContent = ch.prompt + ' "' + f.name + '"';
                      chatInput.dispatchEvent(new Event('input'));
                      chatForm.requestSubmit();
                    }
                  };
                  shareMenu.appendChild(opt);
                });

                shareBtn.onclick = (e) => {
                  e.stopPropagation();
                  // Close any other open share menus
                  document.querySelectorAll('.ofc-share-menu').forEach((m) => {
                    if (m !== shareMenu) m.style.display = 'none';
                  });
                  shareMenu.style.display = shareMenu.style.display === 'none' ? 'block' : 'none';
                };

                shareWrap.appendChild(shareBtn);
                shareWrap.appendChild(shareMenu);

                actionsEl.appendChild(dlBtn);
                actionsEl.appendChild(shareWrap);
                card.appendChild(iconEl);
                card.appendChild(textCol);
                card.appendChild(actionsEl);
                wrapper.appendChild(card);

                // ── Inline preview ──
                if (isImage) {
                  const img = document.createElement('img');
                  img.className = 'ofc-preview-img';
                  img.src = f.download_url;
                  img.alt = f.name;
                  wrapper.appendChild(img);
                } else if (isPdf) {
                  const details = document.createElement('details');
                  details.className = 'ofc-preview-details';
                  const summary = document.createElement('summary');
                  summary.textContent = 'Show preview';
                  const iframe = document.createElement('iframe');
                  iframe.className = 'ofc-preview-pdf';
                  iframe.src = f.download_url;
                  details.appendChild(summary);
                  details.appendChild(iframe);
                  wrapper.appendChild(details);
                } else if (isText) {
                  const toggleBtn = document.createElement('button');
                  toggleBtn.className = 'ofc-preview-toggle';
                  toggleBtn.textContent = 'Show preview';
                  const pre = document.createElement('pre');
                  pre.className = 'ofc-preview-pre';
                  pre.style.display = 'none';
                  let loaded = false;
                  toggleBtn.onclick = async () => {
                    if (pre.style.display === 'none') {
                      if (!loaded) {
                        pre.textContent = 'Loading\u2026';
                        try {
                          const resp = await fetch(f.download_url);
                          const text = await resp.text();
                          const lines = text.split('\n');
                          pre.textContent =
                            lines.slice(0, 20).join('\n') +
                            (lines.length > 20
                              ? '\n\u2026 (' + (lines.length - 20) + ' more lines)'
                              : '');
                          loaded = true;
                        } catch (_e) {
                          pre.textContent = 'Failed to load preview.';
                        }
                      }
                      pre.style.display = 'block';
                      toggleBtn.textContent = 'Hide preview';
                    } else {
                      pre.style.display = 'none';
                      toggleBtn.textContent = 'Show preview';
                    }
                  };
                  wrapper.appendChild(toggleBtn);
                  wrapper.appendChild(pre);
                }

                fileChipsDiv.appendChild(wrapper);
              });
            } else if (msg.exhausted) {
              _streamExhausted = true;
              _exhaustedMessage =
                msg.message ||
                'Gator hit its step limit. Click Continue to pick up where it left off.';
            } else if (msg.stalled) {
              // A turn ended right after a tool failed — reuse the exhausted
              // banner so the stop is visible and recoverable, never silent (#4).
              _streamExhausted = true;
              _exhaustedMessage =
                msg.message ||
                'Gator stopped after a step failed. Click Continue to pick up where it left off.';
            } else if (msg.type === 'permission_required') {
              _renderPermissionCard(
                msgDiv,
                msg,
                prose,
                async () => {
                  // Mark all listed deps as approved for this conversation
                  msg.deps.forEach((d) => _approvedSkillDeps.add(d.id));
                  // Re-submit using the saved payload — call doSend fresh so post-stream
                  // work (history, action bar, suggested actions) runs normally
                  if (!_permissionResendPayload) return;
                  const resendPayload = Object.assign({}, _permissionResendPayload, {
                    unapproved_deps: [],
                  });
                  _permissionResendPayload = null;
                  await doSend(resendPayload);
                },
                () => {
                  // Deny: card already replaced with hard-stop message, nothing else to do
                  _permissionResendPayload = null;
                },
              );
            }
            if (_activeTabId === _tabKey && !_userScrolledUp)
              messages.scrollTop = messages.scrollHeight;
          } catch (e) {
            console.error('[chat-stream] event handler error:', e);
          }
        };

        es.onerror = () => {
          // Reset streaming state unconditionally so the UI never freezes
          _isStreaming = false;
          // EventSource reconnects automatically with Last-Event-ID — only act on permanent close
          if (es.readyState === EventSource.CLOSED) {
            _userScrolledUp = false;
            _chatTaskIds.delete(_tabKey);
            _inflightRequests.delete(_tabKey);
            _setTabWorking(requestTabId, false);
            // Reset the send button to green for the originating tab
            if (requestTabId === _activeTabId) {
              const _sb = document.getElementById('send-btn');
              if (_sb) {
                _sb.classList.remove('is-streaming');
                _sb.setAttribute('aria-label', 'Send message');
                _sb.type = 'submit';
                _sb.disabled = false;
              }
              setStatus('idle');
            }
            if (_userStopped) {
              resolve(); // user intentionally stopped — not an error
            } else if (!_sawDone && full) {
              // Connection severed mid-stream after partial output (server
              // reload/crash, network drop, timeout). Keep what streamed and
              // offer a Continue affordance via the existing exhausted-banner
              // path, rather than freezing silently or discarding progress.
              _streamExhausted = true;
              _exhaustedMessage =
                'The connection dropped before Gator finished. Click Continue to pick up where it left off.';
              resolve();
            } else if (!_sawDone) {
              // Dropped with nothing streamed — likely the server isn't up.
              // The original error+Retry bubble is the right guidance here.
              reject(new Error('Stream connection failed'));
            } else {
              resolve();
            }
          }
        };
      });
      // Scrub Slack auth hallucinations — only when the model is directing the
      // user to take an auth action (go to Settings, refresh token, sign in, etc.)
      // NOT when page content merely mentions Slack or auth-related words.
      if (
        /slack/i.test(full) &&
        /go to (Settings|the Settings)|refresh your (Slack )?token|sign.?in to Slack|reconnect Slack|your Slack session (has )?expired|re-authenticate (with )?Slack/i.test(
          full,
        )
      ) {
        full =
          'The Slack MCP server is temporarily unreachable — this is a network issue, not a token problem. No action needed on your part. Try again in a moment.';
        const statusHtml = renderStatusHtml();
        const prefix = statusHtml
          ? `${statusHtml}<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:.4rem 0 .7rem">`
          : '';
        prose.innerHTML = prefix + renderMarkdown(full);
      }
      if (fileChipsDiv && fileChipsDiv.children.length) {
        prose.appendChild(document.createElement('br'));
        prose.appendChild(fileChipsDiv);
      }
      // Save to the submitting tab's history, not whatever tab is active now
      if (full) {
        if (_activeTabId === _tabKey) {
          // User is still on the submitting tab — use live history/state
          history.push({ role: 'assistant', content: full });
          _saveActiveTabHistory();
          _autoTitleActiveTab();
        } else {
          // User switched tabs while waiting — write directly to the right tab's storage
          const _submittedHist = _loadTabHistory(_tabKey);
          _submittedHist.push({ role: 'assistant', content: full });
          _saveTabHistory(_tabKey, _submittedHist);
        }
        _addMsgActionBar(msgDiv, full, { in: _totalInputTokens, out: _totalOutputTokens });
        // Suggested action pills disabled (GH issue filed — pills often don't make sense)
        document.querySelectorAll('#messages .suggested-actions').forEach((el) => el.remove());
        _refreshRetryVisibility();
      }
      if (_streamExhausted) {
        const banner = document.createElement('div');
        banner.className = 'exhausted-banner';
        const icon = document.createElement('span');
        icon.className = 'exhausted-icon';
        icon.textContent = '\u26a0\ufe0f';
        const text = document.createElement('span');
        text.className = 'exhausted-text';
        text.textContent = _exhaustedMessage;
        const btn = document.createElement('button');
        btn.className = 'exhausted-continue-btn';
        btn.textContent = 'Continue';
        btn.addEventListener('click', () => {
          banner.remove();
          const chatInput = document.getElementById('chat-input');
          const chatForm = document.getElementById('chat-form');
          if (chatInput && chatForm) {
            chatInput.textContent = 'Continue where you left off.';
            chatInput.dispatchEvent(new Event('input'));
            chatForm.requestSubmit();
          }
        });
        banner.appendChild(icon);
        banner.appendChild(text);
        banner.appendChild(btn);
        // Append inside the bubble, not the .message flex row — appending to the
        // row makes the banner a sibling flex item that squeezes .bubble
        // (min-width:0) into a narrow left column (#91).
        (prose.parentElement || msgDiv).appendChild(banner);
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        // User cancelled — show what was streamed so far (or a brief notice if nothing)
        if (!full) {
          prose.innerHTML = `<span class="err-detail" style="opacity:.5">Generation stopped.</span>`;
        }
        // Don't push partial response to history
      } else {
        prose.innerHTML = `<div class="err-bubble"><span class="err-icon">⚠️</span><span>Connection error — check that the server is running.</span><div class="err-detail">${escapeHtml(err.message)}</div><button class="retry-btn">↺ Retry</button></div>`;
        prose.querySelector('.retry-btn')?.addEventListener('click', () => {
          _abortCtrl = new AbortController();
          doSend();
        });
      }
    }

    if (_threeAgentMode) {
      _agentDone.planner = _agentDone.executor = _agentDone.verifier = true;
      _scheduleRender();
    }
    if (_threeAgentMode && !localStorage.getItem('gator-three-agent-seen')) {
      localStorage.setItem('gator-three-agent-seen', '1');
      _showConnectivityToast(
        'Gator used 3 agents (Planning, Working, Checking). Multi-agent tasks use more tokens. Set a budget in Settings.',
        'info',
      );
    }
    if (_totalInputTokens || _totalOutputTokens) {
      const total = (_totalInputTokens + _totalOutputTokens).toLocaleString();
      const footer = document.createElement('div');
      footer.className = 'msg-token-footer';
      const badgeHtml = _threeAgentMode
        ? '<span class="token-agent-badge">\uD83D\uDCCB</span>' +
          '<span class="token-agent-badge">\u2699\uFE0F</span>' +
          '<span class="token-agent-badge">\u2713</span> '
        : '';
      footer.innerHTML = badgeHtml + total + ' tokens';
      (prose.parentElement || msgDiv).appendChild(footer);
    }
    // Post-stream appends above (file/image chips, action bar, exhausted banner,
    // token footer) all landed after the SSE onmessage handler's per-token
    // auto-scroll (line ~7608) already stopped firing — the stream is closed by
    // now, so nothing re-pinned scroll as these grew the container further. Use
    // _pinScrollToBottom (not a plain scrollTop= line) since it re-applies across
    // several frames/timeouts and on late <img> loads — exactly what a freshly
    // appended image/file chip needs.
    if (_activeTabId === requestTabId && !_userScrolledUp) _pinScrollToBottom(messages);
    // Refresh usage bar after each response
    _refreshUsageBar();
    clearInterval(_browserPoll);
    _activeToolNames.clear();
    _updateActiveTools(null, false);
    _resetBrowserHITL();
    // If user stopped before any text arrived, the typing dots are still in prose — clear them
    if (_userStopped && !full) {
      const _stoppedSpan = document.createElement('span');
      _stoppedSpan.className = 'err-detail';
      _stoppedSpan.style.opacity = '.5';
      _stoppedSpan.textContent = 'Generation stopped.';
      prose.replaceChildren(_stoppedSpan);
    }
    msgDiv.classList.remove('typing');
    _setTabWorking(requestTabId, false);
    _resetBtn();
    setStatus('ready');
  };

  await doSend();
});

/* ── Quick Actions runner ────────────────────────────── */
async function runAction(action, btn, query = '', label = '') {
  btn.classList.add('loading');
  setStatus('busy');
  try {
    const res = await fetch(`/api/actions/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');

    renderActionResult(action, data, label);

    // Inject fetched data as conversation context so AI can reason about it
    const ctx = buildContextText(action, data);
    if (ctx) {
      history.push({ role: 'user', content: `[Context loaded: ${label || action}]\n\n${ctx}` });
      history.push({
        role: 'assistant',
        content: `Got it — I've loaded **${label || action}** as context. Ask me anything about it.`,
      });
    }
  } catch (err) {
    addMessage(
      'assistant',
      `<span style="color:var(--danger)">⚠ ${escapeHtml(err.message)}</span>`,
    );
  }
  btn.classList.remove('loading');
  setStatus('ready');
}

function buildContextText(action, data) {
  if (action === 'email' && data.recent) {
    return data.recent.map((e) => `• ${e.subject} | from: ${e.from} | ${e.received}`).join('\n');
  }
  if (['jira', 'jira-urgent', 'jira-custom'].includes(action) && data.issues) {
    return data.issues
      .map((i) => `• ${i.key}: ${i.summary} [${i.status} / ${i.priority}]`)
      .join('\n');
  }
  if (action === 'teams' && data.chats) {
    return data.chats
      .map(
        (c) =>
          `[${c.topic}]\n` +
          (c.messages || [])
            .slice(-5)
            .map((m) => `  ${m.sender}: ${m.body}`)
            .join('\n'),
      )
      .join('\n\n');
  }
  if (action === 'teams-mentions' && data.mentions) {
    return data.mentions.map((m) => `• [${m.topic}] ${m.sender} (${m.time}): ${m.body}`).join('\n');
  }
  if (action === 'calendar' && data.events) {
    return data.events
      .map(
        (e) =>
          `• ${e.isAllDay ? 'All day' : `${e.start}–${e.end}`}: ${e.subject}${e.location ? ` @ ${e.location}` : ''}`,
      )
      .join('\n');
  }
  if (action === 'onedrive' && data.files) {
    return data.files.map((f) => `• ${f.name} (${f.modified}, ${f.size})`).join('\n');
  }
  return '';
}

// Helper to build a result card
function card(icon, title, count, bodyHtml) {
  const badge = count != null ? `<span class="card-header-badge">${count}</span>` : '';
  return `<div class="result-card"><div class="card-header"><span class="card-header-icon">${icon}</span><span class="card-header-title">${title}</span>${badge}</div><div class="card-items">${bodyHtml}</div></div>`;
}
function cardEmpty(icon, title, msg) {
  return `<div class="result-card"><div class="card-header"><span class="card-header-icon">${icon}</span><span class="card-header-title">${title}</span></div><div class="card-empty">${msg}</div></div>`;
}
function chip(text, type = 'neutral') {
  return `<span class="chip chip-${type}">${escapeHtml(text)}</span>`;
}
function priorityChip(p) {
  const t = (p || '').toLowerCase();
  const cls = t === 'urgent' ? 'urgent' : t === 'high' ? 'high' : 'neutral';
  return p ? chip(p, cls) : '';
}

function renderActionResult(action, data, label = '') {
  const prose = addMessage('assistant', '');
  const bubble = prose.closest('.bubble');
  bubble.classList.add('card-bubble');
  prose.classList.remove('prose'); // card content doesn't need prose typography

  if (action === 'email') {
    const stat = `<div class="card-stat-row"><span class="card-stat-num">${data.unread}</span><span class="card-stat-label">unread of ${data.total} total</span></div>`;
    const items = (data.recent || [])
      .map(
        (m) =>
          `<div class="card-item email-link" data-id="${escapeHtml(m.id)}" style="cursor:pointer">
        <div class="card-item-title">${escapeHtml(m.subject)}</div>
        <div class="card-item-meta">
          <span>${escapeHtml(m.from)}</span>
          <span class="card-item-time">${m.received}</span>
        </div>
      </div>`,
      )
      .join('');
    bubble.innerHTML = `<div class="result-card"><div class="card-header"><span class="card-header-icon">✉️</span><span class="card-header-title">Outlook Inbox</span></div>${stat}<div class="card-items">${items}</div></div>`;
    bubble.querySelectorAll('.email-link').forEach((row) => {
      row.addEventListener('click', async () => {
        const readProse = addMessage(
          'assistant',
          '<em style="color:var(--text-dim)">Loading email…</em>',
        );
        const readBubble = readProse.closest('.bubble');
        readBubble.classList.add('card-bubble');
        readProse.classList.remove('prose');
        try {
          const res = await fetch('/api/actions/email/read', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: row.dataset.id }),
          });
          const email = await res.json();
          if (!res.ok) throw new Error(email.detail);
          const bodyText = (email.body || '').trim().slice(0, 1500);
          readProse.innerHTML = card(
            '✉️',
            escapeHtml(email.subject),
            null,
            `<div class="card-item"><div class="card-item-meta"><span>From</span><span>${escapeHtml(email.from)} &lt;${escapeHtml(email.from_email)}&gt;</span></div></div>` +
              `<div class="card-item"><div class="card-item-meta"><span>To</span><span>${escapeHtml(email.to.join(', '))}</span></div></div>` +
              `<div class="card-item"><div class="card-item-meta"><span>Date</span><span>${escapeHtml(email.received)}</span></div></div>` +
              `<div class="card-item"><div class="card-item-body email-body">${escapeHtml(bodyText)}${bodyText.length >= 1500 ? '\n\n[truncated…]' : ''}</div></div>`,
          );
          messages.scrollTop = messages.scrollHeight;
        } catch (err) {
          readProse.innerHTML = `<span style="color:var(--danger)">⚠ ${escapeHtml(err.message)}</span>`;
        }
      });
    });
  } else if (action === 'jira' || action === 'jira-urgent' || action === 'jira-custom') {
    const icon = action === 'jira-urgent' ? '🔥' : '🎫';
    const title = label || (action === 'jira-urgent' ? 'Jira — High Priority' : 'My Jira Tickets');
    if (!data.issues?.length) {
      bubble.innerHTML = cardEmpty(icon, title, 'No issues found.');
    } else {
      const items = data.issues
        .map(
          (i) =>
            `<div class="card-item">
          <div class="card-item-title"><a href="${i.url}" target="_blank">${escapeHtml(i.key)}</a> &nbsp;${escapeHtml(i.summary)}</div>
          <div class="card-item-meta">${chip(i.status)}&nbsp;${priorityChip(i.priority)}</div>
        </div>`,
        )
        .join('');
      bubble.innerHTML = card(icon, title, data.issues.length, items);
    }
  } else if (action === 'teams' || action === 'teams-mentions') {
    const isTeams = action === 'teams';
    const icon = isTeams ? '💬' : '🔔';
    const title = label || (isTeams ? 'Teams — Last 24hrs' : 'Teams — Mentions');
    const list = isTeams
      ? data.chats
      : data.mentions?.map((m) => ({ topic: m.topic, message_count: 1, messages: [m] }));
    if (!list?.length) {
      bubble.innerHTML = cardEmpty(
        icon,
        title,
        isTeams ? 'No activity in the last 24hrs.' : 'No mentions in the last 48hrs.',
      );
    } else {
      const items = list
        .map((c) => {
          const msgs = (c.messages || [])
            .slice(-3)
            .map(
              (m) =>
                `<div class="teams-msg-row">
            <span class="teams-msg-sender">${escapeHtml(m.sender.split(',')[0])}</span>
            <span class="teams-msg-time">${m.time.slice(11, 16) || m.time.slice(5, 10)}</span>
            <span class="teams-msg-body">${escapeHtml(m.body)}</span>
          </div>`,
            )
            .join('');
          return `<div class="card-item">
          <div class="card-item-meta"><span style="font-weight:600;color:var(--text)">${escapeHtml(c.topic)}</span><span class="card-item-time">${c.message_count} msg${c.message_count !== 1 ? 's' : ''}</span></div>
          ${msgs}
        </div>`;
        })
        .join('');
      bubble.innerHTML = card(icon, title, list.length, items);
    }
  } else if (action === 'calendar') {
    if (!data.events?.length) {
      bubble.innerHTML = cardEmpty('📅', "Today's Calendar", 'No events today.');
    } else {
      const items = data.events
        .map((e) => {
          const time = e.isAllDay ? 'All day' : `${e.start} – ${e.end}`;
          return `<div class="card-item">
          <div class="card-item-title">${escapeHtml(e.subject)}</div>
          <div class="card-item-meta"><span>${escapeHtml(time)}</span>${e.location ? `<span class="sep">·</span><span>${escapeHtml(e.location)}</span>` : ''}</div>
        </div>`;
        })
        .join('');
      bubble.innerHTML = card('📅', "Today's Calendar", data.events.length, items);
    }
  } else if (action === 'onedrive') {
    if (!data.files?.length) {
      bubble.innerHTML = cardEmpty('📁', 'OneDrive Recent', 'No recent files.');
    } else {
      const items = data.files
        .map(
          (f) =>
            `<div class="card-item">
          <div class="card-item-title"><a href="${f.url}" target="_blank">${escapeHtml(f.name)}</a></div>
          <div class="card-item-meta"><span>${f.modified}</span><span class="sep">·</span><span>${escapeHtml(f.size)}</span></div>
        </div>`,
        )
        .join('');
      bubble.innerHTML = card('📁', 'OneDrive Recent', data.files.length, items);
    }
  } else if (action === 'news') {
    bubble.innerHTML = card(
      '📰',
      'News Slide',
      null,
      `<div class="card-item"><div class="card-item-title">${escapeHtml(data.message || 'Slide updated successfully.')}</div></div>`,
    );
  }

  messages.scrollTop = messages.scrollHeight;
}

/* ── Code block copy button ──────────────────────────── */
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.code-copy-btn');
  if (!btn) return;
  const code = btn.closest('.code-block-wrap')?.querySelector('code');
  if (!code) return;
  navigator.clipboard
    .writeText(code.textContent)
    .then(() => {
      const orig = btn.textContent;
      btn.textContent = 'Copied!';
      btn.classList.add('code-copy-btn--done');
      setTimeout(() => {
        btn.textContent = orig;
        btn.classList.remove('code-copy-btn--done');
      }, 1800);
    })
    .catch(() => {});
});

/* ── Init ────────────────────────────────────────────── */
renderDock();
initChatResize();
initAigatorUpload();
_initScrollOverride();

// Default to Gator Chat on load
selectSkill('gator');

// ── Confirm modal (replaces browser confirm()) ─────────
function _showConfirmModal(title, body, confirmLabel, onConfirm) {
  const existing = document.getElementById('confirm-modal-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'confirm-modal-overlay';
  overlay.className = 'confirm-modal-overlay';
  overlay.innerHTML = `
    <div class="confirm-modal-box">
      <div class="confirm-modal-title">${title}</div>
      <div class="confirm-modal-body">${body}</div>
      <div class="confirm-modal-actions">
        <button class="btn-ghost confirm-modal-cancel">Cancel</button>
        <button class="btn-primary confirm-modal-ok">${confirmLabel}</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector('.confirm-modal-cancel').addEventListener('click', close);
  overlay.querySelector('.confirm-modal-ok').addEventListener('click', () => {
    close();
    onConfirm();
  });
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
  // Focus the confirm button
  overlay.querySelector('.confirm-modal-ok').focus();
}

// Prompt modal — styled replacement for browser prompt().
// onSubmit receives the entered string (empty string if user submits blank).
// Cancel (button, ESC, backdrop) does NOT invoke onSubmit.
function _showPromptModal(title, label, defaultValue, placeholder, onSubmit) {
  const existing = document.getElementById('confirm-modal-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'confirm-modal-overlay';
  overlay.className = 'confirm-modal-overlay';
  const box = document.createElement('div');
  box.className = 'confirm-modal-box';
  const titleEl = document.createElement('div');
  titleEl.className = 'confirm-modal-title';
  titleEl.textContent = title;
  const bodyEl = document.createElement('div');
  bodyEl.className = 'confirm-modal-body';
  const labelEl = document.createElement('label');
  labelEl.style.cssText = 'display:block;font-size:.85rem;margin-bottom:.4rem;';
  labelEl.textContent = label || '';
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'confirm-modal-input';
  input.style.cssText =
    'width:100%;padding:.5rem .65rem;border:1px solid var(--border,#444);border-radius:6px;background:var(--bg-2,#1a1a1a);color:inherit;font-size:.9rem;';
  input.value = defaultValue || '';
  if (placeholder) input.placeholder = placeholder;
  bodyEl.appendChild(labelEl);
  bodyEl.appendChild(input);
  const actions = document.createElement('div');
  actions.className = 'confirm-modal-actions';
  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'btn-ghost confirm-modal-cancel';
  cancelBtn.textContent = 'Cancel';
  const okBtn = document.createElement('button');
  okBtn.className = 'btn-primary confirm-modal-ok';
  okBtn.textContent = 'OK';
  actions.appendChild(cancelBtn);
  actions.appendChild(okBtn);
  box.appendChild(titleEl);
  box.appendChild(bodyEl);
  box.appendChild(actions);
  overlay.appendChild(box);
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  const submit = () => {
    const v = input.value;
    close();
    onSubmit(v);
  };
  cancelBtn.addEventListener('click', close);
  okBtn.addEventListener('click', submit);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  });
  setTimeout(() => {
    input.focus();
    input.select();
  }, 0);
}
window._showPromptModal = _showPromptModal;

// Alert modal — styled replacement for browser alert()
function _showAlert(msg, type) {
  type = type || 'info';
  const icon = type === 'error' ? '\u2717' : type === 'success' ? '\u2713' : '\u2139\uFE0F';
  const color =
    type === 'error' ? 'var(--danger)' : type === 'success' ? 'var(--success)' : 'var(--accent)';
  const existing = document.getElementById('confirm-modal-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'confirm-modal-overlay';
  overlay.className = 'confirm-modal-overlay';

  const box = document.createElement('div');
  box.className = 'confirm-modal-box';

  const body = document.createElement('div');
  body.className = 'confirm-modal-body';
  body.style.cssText = 'display:flex;gap:10px;align-items:flex-start;max-width:100%';
  const iconSpan = document.createElement('span');
  iconSpan.style.cssText = 'font-size:1.1rem;flex-shrink:0;color:' + color;
  iconSpan.textContent = icon;
  const textSpan = document.createElement('span');
  // Long error payloads (JSON without spaces) overflow without these wrapping rules.
  textSpan.style.cssText =
    'min-width:0;flex:1;word-break:break-word;overflow-wrap:anywhere;max-height:50vh;overflow-y:auto;white-space:pre-wrap';
  textSpan.textContent = msg;
  body.appendChild(iconSpan);
  body.appendChild(textSpan);

  const actions = document.createElement('div');
  actions.className = 'confirm-modal-actions';
  const okBtn = document.createElement('button');
  okBtn.className = 'btn-primary confirm-modal-ok';
  okBtn.textContent = 'OK';
  actions.appendChild(okBtn);

  box.appendChild(body);
  box.appendChild(actions);
  overlay.appendChild(box);
  document.body.appendChild(overlay);

  var close = function () {
    overlay.remove();
  };
  okBtn.addEventListener('click', close);
  overlay.addEventListener('click', function (e) {
    if (e.target === overlay) close();
  });
  document.addEventListener('keydown', function esc(e) {
    if (e.key === 'Escape') {
      close();
      document.removeEventListener('keydown', esc);
    }
  });
  okBtn.focus();
}
window._showAlert = _showAlert;

// Pin orb click
document.getElementById('pin-orb')?.addEventListener('click', _togglePinPopover);
_refreshPinOrb();

// Click-outside closes dropdowns
document.addEventListener('click', (e) => {
  if (_mentionDropdown && !_mentionDropdown.contains(e.target) && e.target !== input) {
    closeMentionDropdown();
  }
  if (_slashDropdown && !_slashDropdown.contains(e.target) && e.target !== input) {
    _closeSlashDropdown();
  }
  if (_channelDropdown && !_channelDropdown.contains(e.target) && e.target !== input) {
    closeChannelDropdown();
  }
});

checkApiKey();
checkModelStatus();
checkAuthStatus();
checkSlackStatus();
checkWatchdog();
checkSkillConnectionStatus();
setInterval(checkAuthStatus, 60000);
setInterval(checkSlackStatus, 60000);
setInterval(checkWatchdog, 30000);
setInterval(checkSkillConnectionStatus, 60000);

// Pre-warm Teams chats cache so # dropdown works even if Teams pane was never opened
fetch('/api/teams/chats')
  .then((r) => (r.ok ? r.json() : null))
  .then((data) => {
    if (data?.chats?.length) window._teamsChatsCache = data.chats;
  })
  .catch(() => {});

/* ── Global Notifications (Teams + Email) ──────────────────── */
(function () {
  // ── Notification toggle (persisted to server config, default off) ──
  let _notifEnabled = false;
  let _notifSoundsEnabled = false;
  const _notifToggle = document.getElementById('notif-toggle');
  const _notifDot = document.getElementById('notif-dot');
  const _notifSub = document.getElementById('notif-sub');
  const _soundRow = document.getElementById('notif-sounds-row');
  const _soundToggle = document.getElementById('notif-sound-toggle');
  const _soundDot = document.getElementById('notif-sound-dot');
  const _soundSub = document.getElementById('notif-sound-sub');

  function _syncNotifUI() {
    if (_notifToggle) _notifToggle.checked = _notifEnabled;
    if (_notifDot) _notifDot.className = 'section-status ' + (_notifEnabled ? 'st-ok' : 'st-dim');
    if (_notifSub) _notifSub.textContent = _notifEnabled ? 'On' : 'Off';
    if (_soundRow) _soundRow.style.display = _notifEnabled ? '' : 'none';
    if (_soundToggle) _soundToggle.checked = _notifSoundsEnabled;
    if (_soundDot)
      _soundDot.className = 'section-status ' + (_notifSoundsEnabled ? 'st-ok' : 'st-dim');
    if (_soundSub) _soundSub.textContent = _notifSoundsEnabled ? 'On' : 'Off';
  }

  fetch('/api/config')
    .then((r) => r.json())
    .then((cfg) => {
      _notifEnabled = !!cfg.notifications_enabled;
      _notifSoundsEnabled = !!cfg.notification_sounds_enabled;
      _syncNotifUI();
    })
    .catch(() => {
      _syncNotifUI();
    });

  if (_notifToggle)
    _notifToggle.addEventListener('change', () => {
      _notifEnabled = _notifToggle.checked;
      _syncNotifUI();
      fetch('/api/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notifications_enabled: _notifEnabled }),
      }).catch(() => {});
      // Request browser permission on first enable
      if (_notifEnabled && 'Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
      }
    });

  if (_soundToggle)
    _soundToggle.addEventListener('change', () => {
      _notifSoundsEnabled = _soundToggle.checked;
      _syncNotifUI();
      fetch('/api/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notification_sounds_enabled: _notifSoundsEnabled }),
      }).catch(() => {});
    });

  // ── Teams remote control toggle (persisted to server config) ──
  const _trcToggle = document.getElementById('teams-remote-control-toggle');
  const _trcDot = document.getElementById('teams-remote-control-dot');
  const _trcSub = document.getElementById('teams-remote-control-sub');
  let _trcEnabled = false;

  function _syncTrcUI() {
    if (_trcToggle) _trcToggle.checked = _trcEnabled;
    if (_trcDot) _trcDot.className = 'section-status ' + (_trcEnabled ? 'st-ok' : 'st-dim');
    if (_trcSub) _trcSub.textContent = _trcEnabled ? 'On' : 'Off';
  }

  fetch('/api/config')
    .then((r) => r.json())
    .then((cfg) => {
      _trcEnabled = !!cfg.teams_remote_control_enabled;
      _syncTrcUI();
    })
    .catch(() => {});

  if (_trcToggle)
    _trcToggle.addEventListener('change', async () => {
      _trcEnabled = _trcToggle.checked;
      _syncTrcUI();
      await fetch('/api/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ teams_remote_control_enabled: _trcEnabled }),
      }).catch(() => {});
    });

  // ── Browser Display toggle (persisted to server config) ──
  const _bdSub = document.getElementById('browser-display-sub');
  const _bdBtns = document.querySelectorAll('.browser-display-opt');
  let _browserDisplay = 'pane';

  function _syncBrowserDisplayUI() {
    _bdBtns.forEach((b) => {
      const active = b.dataset.val === _browserDisplay;
      b.style.background = active ? 'var(--accent)' : '';
      b.style.color = active ? '#000' : '';
      b.style.fontWeight = active ? '600' : '';
    });
    if (_bdSub)
      _bdSub.textContent = _browserDisplay === 'pane' ? "Gator's Browser" : 'External window';
  }

  // Load current value from server config
  fetch('/api/config')
    .then((r) => r.json())
    .then((cfg) => {
      _browserDisplay = cfg.browser_display || 'external';
      _syncBrowserDisplayUI();
    })
    .catch(() => {});

  _bdBtns.forEach((btn) => {
    btn.addEventListener('click', async () => {
      _browserDisplay = btn.dataset.val;
      _syncBrowserDisplayUI();
      await fetch('/api/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ browser_display: _browserDisplay }),
      });
    });
  });

  // ── Browser Engine toggle (native Chrome/Edge vs Playwright Chromium) ──
  const _beEngineOpts = document.querySelectorAll('.browser-engine-opt');
  const _bePreferOpts = document.querySelectorAll('.browser-prefer-opt');
  const _bePreferRow = document.getElementById('browser-prefer-row');
  const _beEngineSub = document.getElementById('browser-engine-sub');
  let _browserNative = false;
  let _browserPrefer = 'auto';
  let _browserProfile = '';
  let _playwrightInstalled = null; // null = unknown, true/false once checked

  function _syncBrowserEngineUI() {
    _beEngineOpts.forEach((b) =>
      b.classList.toggle('active', b.dataset.val === String(_browserNative)),
    );
    _bePreferOpts.forEach((b) => b.classList.toggle('active', b.dataset.val === _browserPrefer));
    const _advDetails = document.getElementById('browser-advanced-details');
    if (_advDetails) _advDetails.style.display = _browserNative ? '' : 'none';
    if (_bePreferRow) _bePreferRow.style.display = _browserNative ? 'flex' : 'none';
    const _bpProfileRow = document.getElementById('browser-profile-row');
    if (_bpProfileRow) _bpProfileRow.style.display = _browserNative ? 'flex' : 'none';
    const _bpProfileNameRow = document.getElementById('browser-profile-name-row');
    if (_bpProfileNameRow)
      _bpProfileNameRow.style.display =
        _browserNative && _browserProfile === 'personal' ? 'flex' : 'none';
    document
      .querySelectorAll('.browser-profile-opt')
      .forEach((b) => b.classList.toggle('active', b.dataset.val === _browserProfile));
    if (_beEngineSub) {
      if (!_browserNative) {
        if (_playwrightInstalled === true) {
          _beEngineSub.textContent = 'Playwright Chromium · installed';
        } else if (_playwrightInstalled === false) {
          _beEngineSub.textContent =
            'Playwright Chromium · not installed (run: playwright install chromium)';
        } else {
          _beEngineSub.textContent = 'Playwright Chromium';
        }
      } else {
        const engineName =
          _browserPrefer === 'edge'
            ? 'Edge'
            : _browserPrefer === 'chrome'
              ? 'Chrome'
              : 'Chrome / Edge';
        const profileName =
          _browserProfile === 'personal'
            ? 'your logins'
            : _browserProfile === 'gator'
              ? 'isolated'
              : 'choose profile';
        _beEngineSub.textContent = engineName + ' (' + profileName + ')';
      }
    }
  }

  fetch('/api/config')
    .then((r) => r.json())
    .then((cfg) => {
      _browserNative = cfg.browser_native !== false;
      _browserPrefer = cfg.browser_prefer || 'auto';
      _browserProfile = cfg.browser_profile || 'gator';
      const _profileNameInput = document.getElementById('browser-profile-name-input');
      if (_profileNameInput) _profileNameInput.value = cfg.browser_profile_name || 'Default';
      _syncBrowserEngineUI();
    })
    .catch(() => {});

  fetch('/api/browser/playwright-status')
    .then((r) => r.json())
    .then((s) => {
      _playwrightInstalled = !!s.installed;
      _syncBrowserEngineUI();
    })
    .catch(() => {});

  _beEngineOpts.forEach((btn) => {
    btn.addEventListener('click', async () => {
      _browserNative = btn.dataset.val === 'true';
      _syncBrowserEngineUI();
      await fetch('/api/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ browser_native: _browserNative }),
      });
    });
  });

  _bePreferOpts.forEach((btn) => {
    btn.addEventListener('click', async () => {
      _browserPrefer = btn.dataset.val;
      _syncBrowserEngineUI();
      await fetch('/api/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ browser_prefer: _browserPrefer }),
      });
    });
  });

  document.querySelectorAll('.browser-profile-opt').forEach((btn) => {
    btn.addEventListener('click', async () => {
      _browserProfile = btn.dataset.val;
      _syncBrowserEngineUI();
      await fetch('/api/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ browser_profile: _browserProfile }),
      });
    });
  });

  // Profile name save (personal mode — bypasses Chrome profile picker)
  document.getElementById('browser-profile-name-save')?.addEventListener('click', async () => {
    const input = document.getElementById('browser-profile-name-input');
    const name = (input?.value || 'Default').trim();
    await fetch('/api/config', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ browser_profile_name: name }),
    });
    if (input) input.value = name;
  });

  // Track last-known state to detect NEW notifications
  let _lastTeamsUnread = new Map(); // chatId → {topic, sender, time}
  let _lastEmailUnread = new Set(); // messageId set
  let _notifReady = false;

  function _showNotification(title, body, icon, onClick) {
    if (!_notifEnabled) return; // Notifications disabled by user
    // In-app toast
    _showNotifToast(title, body, onClick);
    // Browser notification (if permitted)
    if ('Notification' in window && Notification.permission === 'granted') {
      try {
        const n = new Notification(title, {
          body,
          icon: icon || '/logo',
          tag: title,
          silent: !_notifSoundsEnabled,
        });
        if (onClick)
          n.addEventListener('click', () => {
            window.focus();
            onClick();
            n.close();
          });
        setTimeout(() => n.close(), 8000);
      } catch {}
    }
  }

  function _showNotifToast(title, body, onClick) {
    const toast = document.createElement('div');
    Object.assign(toast.style, {
      position: 'fixed',
      top: '1rem',
      right: '1rem',
      zIndex: '99998',
      background: 'var(--surface, #1e293b)',
      border: '1px solid var(--border2, #334155)',
      borderRadius: '10px',
      padding: '.7rem .9rem',
      minWidth: '260px',
      maxWidth: '360px',
      boxShadow: '0 8px 32px rgba(0,0,0,.4)',
      cursor: 'pointer',
      display: 'flex',
      flexDirection: 'column',
      gap: '.2rem',
      animation: 'slideInRight .3s ease-out',
      transition: 'opacity .3s, transform .3s',
    });
    toast.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between">
        <span style="font-size:.78rem;font-weight:700;color:var(--text)">${_escHtml(title)}</span>
        <button style="background:none;border:none;color:var(--text-sub);cursor:pointer;font-size:.9rem;padding:0;line-height:1">&times;</button>
      </div>
      <div style="font-size:.74rem;color:var(--text-sub);line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_escHtml(body)}</div>
    `;
    toast.querySelector('button').addEventListener('click', (e) => {
      e.stopPropagation();
      toast.remove();
    });
    if (onClick)
      toast.addEventListener('click', () => {
        onClick();
        toast.remove();
      });
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      setTimeout(() => toast.remove(), 300);
    }, 6000);
  }

  function _escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // ── Teams notification polling (every 60s, global) ──
  window.window._teamsNotifBackoff = false;
  setInterval(async () => {
    if (window._teamsNotifBackoff) return; // Skip while auth is broken
    try {
      const res = await fetch('/api/teams/chats?delta=true');
      if (res.status === 401 || res.status === 403) {
        window._teamsNotifBackoff = true; // Stop polling until token is refreshed
        console.warn('[notif] Teams auth failed — pausing notifications until token refresh');
        // Re-enable after 5 minutes (user may have recaptured token)
        setTimeout(() => {
          window._teamsNotifBackoff = false;
        }, 300000);
        return;
      }
      if (!res.ok) return;
      const data = await res.json();
      const chats = data.chats || [];

      // Update badge
      const unread = chats.filter((c) => (c.unread_count || 0) > 0).length;
      if (typeof updateRailBadge === 'function') updateRailBadge('teams', unread);

      if (!_notifReady) {
        // First poll — seed state, don't notify
        chats.forEach((c) => {
          if (c.unread_count > 0) _lastTeamsUnread.set(c.id, c.last_message_time);
        });
        _notifReady = true;
        return;
      }

      // Detect NEW unread (wasn't unread before, or has newer message)
      chats.forEach((c) => {
        if ((c.unread_count || 0) > 0) {
          const prevTime = _lastTeamsUnread.get(c.id);
          if (!prevTime || c.last_message_time > prevTime) {
            _showNotification(
              `Teams: ${c.topic || 'Chat'}`,
              `${c.last_sender || 'Someone'}: ${(c.last_message || '').slice(0, 80)}`,
              '/static/icons/teams.svg',
              () => {
                if (typeof openThirdPane === 'function') openThirdPane('teams');
                if (typeof tpLoadDetail === 'function') setTimeout(() => tpLoadDetail(c.id), 300);
              },
            );
          }
          _lastTeamsUnread.set(c.id, c.last_message_time);
        } else {
          _lastTeamsUnread.delete(c.id);
        }
      });
    } catch {}
  }, 60000);

  // ── Email notification polling (every 90s, global) ──
  setInterval(async () => {
    try {
      const res = await fetch('/api/email/inbox?top=10&delta=true');
      if (!res.ok) return;
      const data = await res.json();
      const messages = data.messages || [];
      const totalUnread = data.total_unread || 0;

      // Update badge
      if (typeof updateRailBadge === 'function') updateRailBadge('email', totalUnread);

      if (!_notifReady) return; // Wait for Teams poll to seed first

      // Detect NEW unread emails
      messages.forEach((m) => {
        if (!m.is_read && !_lastEmailUnread.has(m.id)) {
          _showNotification(
            `Email: ${m.from_name || m.from_email || 'Unknown'}`,
            m.subject || '(no subject)',
            '/static/icons/outlook.svg',
            () => {
              if (typeof openThirdPane === 'function') openThirdPane('email');
              if (typeof tpLoadDetail === 'function') setTimeout(() => tpLoadDetail(m.id), 300);
            },
          );
        }
      });
      // Update known set
      _lastEmailUnread = new Set(messages.filter((m) => !m.is_read).map((m) => m.id));
    } catch {}
  }, 90000);
})();

/* ── Notification SSE subscription ─────────────────── */
function _initNotificationStream() {
  const es = new EventSource('/api/notifications/stream');
  es.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'job_created') {
        if (typeof _apRefresh === 'function') _apRefresh();
        return;
      }
      if (msg.type === 'skill_registered' && msg.skill_id) {
        if (typeof window.registerUserSkill === 'function') {
          window.registerUserSkill(
            msg.skill_id,
            msg.display_name || msg.skill_id,
            msg.tier || 'Mine',
          );
        }
        return;
      }
      if (msg.type === 'skill_renamed' && msg.skill_id) {
        const entry = SKILL_MAP[msg.skill_id];
        if (entry && msg.display_name) entry.label = msg.display_name;
        return;
      }
      if (msg.type === 'model_changed' && msg.model) {
        // Another tab (or settings) changed the active model — refresh this tab's
        // pill + window._currentModel so the next chat request sends the right model.
        if (typeof window._refreshPromptBarModels === 'function') {
          window._refreshPromptBarModels();
        } else {
          window._currentModel = msg.model;
        }
        return;
      }
      if (msg.type === 'skill_auto_activated' && msg.skill_id) {
        // Server detected Claude requested a skill mid-conversation and auto-activated it.
        // Reflect this in the sidebar so the user sees the new active skill.
        try {
          if (typeof _addSkillChip === 'function') _addSkillChip(msg.skill_id);
          if (typeof _activeSkillId !== 'undefined' && _activeSkillId !== 'gator') {
            _activeSkillId = msg.skill_id;
            if (typeof _setRailActive === 'function') _setRailActive(msg.skill_id);
          }
        } catch (err) {
          console.warn('[notify-stream] skill_auto_activated handler failed:', err);
        }
        return;
      }
      // Forward pane signals — backup delivery channel for compose panes
      if (msg.type === 'pane_signal' && msg.pane) {
        console.log('[notify-stream] pane signal received:', msg.pane);
        _handlePaneSignal(msg.pane, msg.paneData || {});
        return;
      }
      if (msg.type === 'draft_signal' && msg.draft) {
        // Deduplicate: if a card with this draft_id already exists (injected
        // by the chat stream), don't inject a second one.
        const existing = document.querySelector(`[data-draft-id="${msg.draftData?.draft_id}"]`);
        if (existing) {
          console.log('[notify-stream] draft already shown, skipping duplicate:', msg.draft);
        } else {
          console.log('[notify-stream] draft signal received:', msg.draft);
          _injectDraftApprovalCard(msg.draft, msg.draftData || {});
        }
        return;
      }
      if (msg.type === 'max_tokens_reached') {
        const text = msg.message || 'Claude hit the output limit — reply "continue" to resume.';
        try {
          _showConnectivityToast(text, 'warning');
        } catch (_) {}
        return;
      }
      if (msg.type === 'warning') {
        try {
          _showConnectivityToast(msg.message || 'Warning', 'warning');
        } catch (_) {}
        return;
      }
      if (msg.type === 'chat_done') {
        // The request finished (success, error, or cancel) — clear the in-progress
        // line. This is the reliable signal: it fires from the server's finally even
        // when a stalled/cancelled chat never sent a local [DONE].
        if (msg.context_id) {
          _setTabWorking(msg.context_id, false);
          // Clear the per-tab task tracking so the send button returns to green
          // even if [DONE] was never received (stalled stream, server crash, etc.).
          // This is the zombie-task fix: without it, _chatTaskIds retains a stale
          // entry and switchTab shows a red stop button on an idle tab.
          _chatTaskIds.delete(msg.context_id);
          _inflightRequests.delete(msg.context_id);
          // Only reset _isStreaming and the send button if the finished chat is
          // for the active tab AND no other stream is now running on this tab.
          // The notification stream is global — a chat_done for tab A can arrive
          // after the user already started a new stream on tab B. Resetting
          // _isStreaming unconditionally would kill tab B's streaming state.
          if (msg.context_id === _activeTabId && !_chatTaskIds.has(_activeTabId)) {
            _isStreaming = false;
            const _sb = document.getElementById('send-btn');
            if (_sb) {
              _sb.classList.remove('is-streaming');
              _sb.setAttribute('aria-label', 'Send message');
              _sb.type = 'submit';
              _sb.disabled = false;
            }
            setStatus('idle');
          }
        }
        // Notify only for a completion on a tab the user is NOT currently viewing.
        // Keying on the active tab (not _chatTaskIds, which the [DONE] handler clears
        // in a race with this message) is timing-independent: it restores same-window
        // cross-tab alerts AND avoids self-notifying the visible/originating tab (B20).
        if (
          msg.context_id &&
          msg.context_id !== _activeTabId &&
          _tabs.some((t) => t.id === msg.context_id)
        ) {
          // Mark the source tab with a visual indicator
          _tabsWithUpdates.add(msg.context_id);
          const tabEl = document.querySelector(`.tab-item[data-tab-id="${msg.context_id}"]`);
          if (tabEl) tabEl.classList.add('tab-has-update');
          // Toast in the current tab
          _showConnectivityToast(
            'Your request in another tab is done — switch back to see the result.',
            'info',
          );
        }
        return;
      }
      if (msg.type === 'mcp_auth_error' && msg.connection_id) {
        _showMcpAuthErrorCard(msg.connection_id, msg.name || msg.connection_id);
        return;
      }
      if (msg.type === 'task_done') {
        _showSystemCard({
          icon: msg.status === 'done' ? '\u26A1' : '\u26A0\uFE0F',
          title: msg.job_name
            ? msg.status === 'done'
              ? msg.job_name + ' completed'
              : msg.job_name + ' failed'
            : msg.status === 'done'
              ? 'Background task complete'
              : 'Task failed',
          subtitle: msg.summary || '',
          taskId: msg.task_id,
          status: msg.status,
        });
        // Refresh usage stats (includes background task tokens)
        _refreshUsageBar();
        // Refresh agents pane so run history + token counts update after task completes
        if (typeof _apRefresh === 'function') _apRefresh();
        // Update agents badge — but not if pane is open (user sees the list directly)
        if (typeof _updateAgentsBadge === 'function') {
          const paneOpen = document.getElementById('agents-pane')?.classList.contains('is-open');
          if (!paneOpen) {
            fetch('/api/tasks?limit=10')
              .then((r) => (r.ok ? r.json() : []))
              .then((tasks) => {
                const completed = tasks.filter(
                  (t) => t.status === 'done' || t.status === 'failed',
                ).length;
                _updateAgentsBadge(completed);
              })
              .catch(() => {});
          }
        }
      }
    } catch {}
  };
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      es.close();
      setTimeout(() => {
        // Refresh CSRF token after server restart — the in-memory token regenerates
        // on each uvicorn reload, so the old token in window.__CSRF_TOKEN__ is stale.
        fetch('/api/csrf')
          .then((r) => (r.ok ? r.json() : null))
          .then((d) => {
            if (d?.csrf_token) window.__CSRF_TOKEN__ = d.csrf_token;
          })
          .catch(() => {})
          .finally(() => _initNotificationStream());
      }, 5000);
    }
  };
}
document.addEventListener('DOMContentLoaded', _initNotificationStream);

/* ── Dock Init ───────────────────────────────────────── */
function _toggleLauncher() {
  const bd = document.getElementById('launcher-backdrop');
  if (!bd) return;
  const isOpen = bd.classList.contains('open');
  if (isOpen) {
    bd.classList.remove('open');
  } else {
    renderLauncher();
    bd.classList.add('open');
    const input = document.getElementById('launcher-input');
    if (input) {
      input.value = '';
      _filterLauncherApps('');
    }
    setTimeout(() => input?.focus(), 100);
  }
}

function _filterLauncherApps(query) {
  const q = query.toLowerCase();
  document.querySelectorAll('.launcher-app[data-name]').forEach((app) => {
    const text = (app.dataset.label || '') + ' ' + (app.dataset.name || '');
    app.classList.toggle('launcher-hidden', q && !text.includes(q));
  });
  document.querySelectorAll('.launcher-category').forEach((cat) => {
    const grid = cat.nextElementSibling;
    if (!grid || !grid.classList.contains('launcher-grid')) return;
    const visible = grid.querySelectorAll('.launcher-app:not(.launcher-hidden)');
    cat.classList.toggle('launcher-hidden', !visible.length);
    grid.classList.toggle('launcher-hidden', !visible.length);
  });
}

function _initLauncher() {
  let _launcherFocusIdx = -1;

  function _launcherItems() {
    return [...document.querySelectorAll('.launcher-app[data-name]:not(.launcher-hidden)')];
  }

  function _launcherSetFocus(idx) {
    const items = _launcherItems();
    if (!items.length) return;
    _launcherFocusIdx = Math.max(0, Math.min(idx, items.length - 1));
    items.forEach((el, i) => el.classList.toggle('launcher-focused', i === _launcherFocusIdx));
    items[_launcherFocusIdx]?.scrollIntoView({ block: 'nearest' });
  }

  function _launcherClearFocus() {
    _launcherFocusIdx = -1;
    document
      .querySelectorAll('.launcher-app.launcher-focused')
      .forEach((el) => el.classList.remove('launcher-focused'));
  }

  document.getElementById('launcher-backdrop')?.addEventListener('click', (e) => {
    if (e.target.id === 'launcher-backdrop') _toggleLauncher();
  });

  const input = document.getElementById('launcher-input');
  input?.addEventListener('input', (e) => {
    _filterLauncherApps(e.target.value);
    _launcherClearFocus();
  });

  input?.addEventListener('keydown', (e) => {
    const bd = document.getElementById('launcher-backdrop');
    if (!bd?.classList.contains('open')) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _launcherSetFocus(_launcherFocusIdx < 0 ? 0 : _launcherFocusIdx + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _launcherSetFocus(_launcherFocusIdx <= 0 ? 0 : _launcherFocusIdx - 1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const items = _launcherItems();
      if (_launcherFocusIdx >= 0 && items[_launcherFocusIdx]) {
        items[_launcherFocusIdx].click();
      } else if (items.length === 1) {
        items[0].click();
      }
    }
  });

  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      _toggleLauncher();
      _launcherClearFocus();
    }
    if (e.key === 'Escape') {
      const bd = document.getElementById('launcher-backdrop');
      if (bd?.classList.contains('open')) {
        bd.classList.remove('open');
        _launcherClearFocus();
      }
    }
  });
}
document.addEventListener('DOMContentLoaded', _initLauncher);

function _initDock() {
  renderDock();
  // Temporarily un-squeeze Gator's view BEFORE any dock action runs, so the
  // action (opening a pane, agents, etc.) doesn't render inside a squeezed
  // viewport and overflow (looks like the dock/logo jumping). Capture phase so
  // this precedes the button's own handler. We deliberately do NOT reset the
  // persisted show/hide intent here — GatorChat.reapply() (run at the end of
  // openThirdPane) re-asserts the user's chosen visibility through the correct
  // mechanism for the newly-opened pane. This keeps "hidden" sticky across app
  // switches while still avoiding the squeezed-render glitch.
  document.getElementById('dock')?.addEventListener(
    'click',
    (e) => {
      if (e.target.closest('#dock-home')) return;
      if (window.gatorShell?.showGator) window.gatorShell.showGator();
    },
    true,
  );
  _initGatorSpin();
  document.getElementById('dock-launcher-btn')?.addEventListener('click', () => {
    _toggleLauncher();
  });
  document.getElementById('dock-agents')?.addEventListener('click', () => {
    if (typeof openAgentsPane === 'function') openAgentsPane();
  });
  document.getElementById('dock-settings')?.addEventListener('click', () => {
    document.getElementById('settings-trigger')?.click();
  });
  document.getElementById('dock-help')?.addEventListener('click', () => {
    document.getElementById('help-trigger')?.click();
  });
}

/* ── GatorChat: single source of truth for chat-pane visibility ───────
 *
 * ONE controller owns "is the Gator chat pane hidden/maximized-away?" and
 * routes every hide/show request through the correct mechanism for whatever
 * pane is currently open. Replaces four previously-independent controllers
 * (dock logo `_gatorHidden`, `_dividerBtns`, `tp-expand-toggle`, shell squeeze)
 * that mutated overlapping state and desynced on cross-app switches.
 *
 * Two mechanisms exist because native apps and in-Gator panes are rendered in
 * fundamentally different surfaces:
 *   - NATIVE panes (Slack/Teams/Outlook) live in their own shell
 *     WebContentsView. Hiding Gator = squeeze Gator's view to the dock sliver
 *     (shell IPC showGator/hideGator) and let the native app fill the window.
 *   - IN-GATOR panes (Calendar/OneDrive/Jira/…) render inside Gator's own page.
 *     There's no native view to fill the space, so we hide the chat column via
 *     CSS (.tp-expanded on #third-pane + .tp-hidden-for-expand on main.main).
 *
 * `hidden` is the SINGLE persisted user intent. It survives app switches
 * (localStorage 'gator-chat-hidden'): whatever the user chose stays in effect
 * until they change it, re-applied through the mechanism valid for the new
 * pane. GatorChat.reapply() (called at the end of every openThirdPane) first
 * clears BOTH mechanisms, then re-asserts the persisted intent — so no leftover
 * squeeze or .tp-expanded can ever strand across a switch.
 */
const GATOR_NATIVE_PANE_TYPES = [
  'slack',
  'teams',
  'email',
  'onedrive',
  'onenote',
  'confluence',
  'jira',
  'github',
];
const _GATOR_HIDDEN_KEY = 'gator-chat-hidden';

const GatorChat = {
  hidden: false,

  init() {
    try {
      this.hidden = localStorage.getItem(_GATOR_HIDDEN_KEY) === '1';
    } catch (_) {
      this.hidden = false;
    }
    this._syncDockLogo();
  },

  isHidden() {
    return this.hidden;
  },

  _inShell() {
    return typeof window.gatorShell !== 'undefined' && !!window.gatorShell.isShell;
  },

  _paneType() {
    return typeof tpState !== 'undefined' ? tpState.type : null;
  },

  _isNativePane() {
    const t = this._paneType();
    if (!t) return false;
    // Hardcoded native apps
    if (GATOR_NATIVE_PANE_TYPES.indexOf(t) !== -1) return true;
    // Custom web apps and Google Workspace services are also native shell panes
    const skill = typeof SKILL_MAP !== 'undefined' ? SKILL_MAP[t] : null;
    return !!(skill && (skill._customApp || skill._googleService));
  },

  _paneOpen() {
    const t = this._paneType();
    if (!t) return false;
    // Native apps (Slack/Teams/Outlook) render in their OWN shell view, so
    // #third-pane is deliberately `.hidden` for them — "open" is signalled by
    // tpState.type being a native type instead. In-Gator panes (Calendar/etc)
    // render inside #third-pane, so they're open when it's not `.hidden`.
    if (this._isNativePane()) return true;
    return !document.getElementById('third-pane')?.classList.contains('hidden');
  },

  _persist() {
    try {
      localStorage.setItem(_GATOR_HIDDEN_KEY, this.hidden ? '1' : '0');
    } catch (_) {}
  },

  _syncDockLogo() {
    const btn = document.getElementById('dock-home');
    if (!btn) return;
    btn.classList.toggle('state-split', !this.hidden);
    btn.classList.toggle('state-hidden', this.hidden);
    btn.title = this.hidden
      ? 'Gator — Hidden · click to show · double-click for chat'
      : 'Gator — Split · click to hide · double-click for chat';
  },

  _syncCloseBtn() {
    // The top-left "Expand/Restore Gator" button is only meaningful while a
    // pane is open. Keep it in sync with pane state (not visibility).
    const closeBtn = document.getElementById('gator-close-pane-btn');
    if (!closeBtn) return;
    closeBtn.classList.toggle('hidden', !this._paneOpen());
  },

  // CSS-expand mechanism (in-Gator panes): grow the third-pane, hide the chat.
  _applyExpand(expand) {
    const pane = document.getElementById('third-pane');
    const main = document.querySelector('main.main');
    if (!pane || !main) return;
    const already = pane.classList.contains('tp-expanded');
    if (expand === already) return;
    pane.classList.toggle('tp-expanded', expand);
    main.classList.toggle('tp-hidden-for-expand', expand);
    if (typeof _tpSyncExpandButton === 'function') _tpSyncExpandButton();
    // FullCalendar caches its pixel geometry; nudge it after the width change.
    if (typeof _fcInstance !== 'undefined' && _fcInstance) {
      _fcInstance.updateSize();
      setTimeout(() => {
        if (_fcInstance) _fcInstance.updateSize();
      }, 550);
    }
  },

  // Shell-squeeze mechanism (native panes): squeeze Gator's whole view.
  async _applySqueeze(squeeze) {
    if (!this._inShell()) return true;
    if (squeeze) {
      if (window.gatorShell.hideGator) await window.gatorShell.hideGator();
      // The shell refuses to squeeze when there's no native app to fill the
      // space; confirm it actually squeezed, else report failure so the caller
      // can fall back to the CSS-expand mechanism.
      if (window.gatorShell.getActiveApp) {
        const active = await window.gatorShell.getActiveApp();
        return !!active;
      }
      return true;
    }
    if (window.gatorShell.showGator) window.gatorShell.showGator();
    return true;
  },

  // Clear the CSS-expand mechanism without changing the persisted intent. Used
  // before re-applying on a pane switch so no leftover state strands.
  //
  // NOTE: we deliberately do NOT call showGator() here. Doing so un-squeezed
  // Gator's whole view (56px → full width) and then _applyForCurrentPane()
  // immediately re-squeezed it back — a visible 56→full→56 bounce/flicker on
  // every app switch while Gator was hidden. _applyForCurrentPane() sets the
  // definitive shell state (squeeze OR show) in a single step, so clearing the
  // shell squeeze here is both unnecessary and the cause of the flicker.
  async _clearAll() {
    this._applyExpand(false);
  },

  // Apply `this.hidden` using the mechanism valid for the CURRENT pane.
  async _applyForCurrentPane() {
    if (!this.hidden) {
      this._applyExpand(false);
      if (this._inShell() && window.gatorShell.showGator) window.gatorShell.showGator();
      this._syncDockLogo();
      return;
    }
    // Want hidden.
    if (this._paneOpen() && this._isNativePane()) {
      const squeezed = await this._applySqueeze(true);
      if (!squeezed) {
        // No native app took the space — fall back to CSS expand.
        this._applyExpand(true);
      }
    } else if (this._paneOpen()) {
      // In-Gator pane: CSS expand.
      this._applyExpand(true);
    } else {
      // No pane open: nothing to maximize; squeezing would blank Gator, so
      // treat "hidden with no pane" as shown.
      this.hidden = false;
      this._persist();
    }
    this._syncDockLogo();
  },

  async hide() {
    this.hidden = true;
    this._persist();
    await this._applyForCurrentPane();
  },

  async show() {
    this.hidden = false;
    this._persist();
    this._applyExpand(false);
    if (this._inShell() && window.gatorShell.showGator) window.gatorShell.showGator();
    this._syncDockLogo();
  },

  async toggle() {
    if (this.hidden) return this.show();
    return this.hide();
  },

  // Called at the end of openThirdPane (app switch) and after a pane opens:
  // guarantee a clean slate, then re-assert the persisted visibility intent
  // via the mechanism valid for the NEW pane.
  async reapply() {
    await this._clearAll();
    await this._applyForCurrentPane();
    this._syncCloseBtn();
  },

  // Called by closeThirdPane: no pane left, so force shown + clear expand.
  onPaneClosed() {
    this._applyExpand(false);
    this.hidden = false;
    this._persist();
    if (this._inShell() && window.gatorShell.showGator) window.gatorShell.showGator();
    this._syncDockLogo();
    this._syncCloseBtn();
  },
};
window.GatorChat = GatorChat;

let _gatorClickTimer = null;

function _initGatorSpin() {
  GatorChat.init();
  const btn = document.getElementById('dock-home');
  if (!btn) return;
  if (typeof window.gatorShell === 'undefined' || !window.gatorShell.isShell) return;

  btn.addEventListener('click', (e) => {
    // Double-click = go home (Gator chat tab).
    if (_gatorClickTimer) {
      clearTimeout(_gatorClickTimer);
      _gatorClickTimer = null;
      selectSkill('gator');
      return;
    }
    _gatorClickTimer = setTimeout(() => {
      _gatorClickTimer = null;
      GatorChat.toggle();
    }, 250);
  });

  // Close-pane button — close all panes, restore Gator to full.
  const closeBtn = document.getElementById('gator-close-pane-btn');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      if (window.gatorShell?.hideSlack) window.gatorShell.hideSlack();
      if (window.gatorShell?.hideTeams) window.gatorShell.hideTeams();
      if (window.gatorShell?.hideOutlook) window.gatorShell.hideOutlook();
      if (typeof closeThirdPane === 'function') closeThirdPane();
      // closeThirdPane → GatorChat.onPaneClosed() handles show + logo sync.
    });
  }
}

// ── Backward-compatible shims over GatorChat ──────────────────────────
// Existing call sites keep working; they now funnel through the one controller.
function _toggleGatorHideShow() {
  return GatorChat.toggle();
}
function _setGatorHidden(hidden) {
  return hidden ? GatorChat.hide() : GatorChat.show();
}
Object.defineProperty(window, '_gatorHidden', {
  get() {
    return GatorChat.hidden;
  },
  configurable: true,
});

window._gatorSpinOnPaneOpen = function () {
  // A pane just opened — surface the close button and re-assert visibility.
  document.getElementById('gator-close-pane-btn')?.classList.remove('hidden');
};
window._gatorSpinOnPaneClose = function () {
  GatorChat.onPaneClosed();
};
// Backward-compat stubs.
window._syncGatorSpin = function () {};
window._gatorSpinSetVisible = function (v) {
  if (v) GatorChat.show();
};
document.addEventListener('DOMContentLoaded', () => {
  _initDock();
  // Restore the single canonical pane width (see 'tp-pane-width' — shared by
  // BOTH native panes (Slack/Teams/Outlook, via the shell's extTileWidth) and
  // classic in-Gator panes (Calendar/OneDrive/etc, via --third-pane-w)) so it
  // persists across app restarts and stays identical for every pane type.
  //
  // This ONE-TIME restore, run before any pane has opened, is what used to
  // race and cause width jumps: a stale localStorage read landing AFTER a
  // fresher shell-driven width update from a mid-session drag/pane-switch.
  // That's no longer possible here because it's the very first thing that
  // touches width — nothing has raced yet. Ongoing sync (both directions,
  // native drag ↔ classic drag) is handled at each drag-end (see _shellDrag
  // and initThirdPaneResize) so this restore only ever runs once at boot.
  try {
    const savedW = localStorage.getItem('tp-pane-width');
    if (savedW) {
      const w = +savedW;
      document.documentElement.style.setProperty('--third-pane-w', w + 'px');
      if (
        typeof window.gatorShell !== 'undefined' &&
        window.gatorShell.isShell &&
        window.gatorShell.restoreExtTileWidth
      ) {
        window.gatorShell.restoreExtTileWidth(w);
      }
    }
  } catch (_) {}
  // Remove any stale active-tool chips from chip row (left over from old code path)
  document.querySelectorAll('#chat-chip-row .active-tool-chip').forEach((el) => el.remove());

  // Window controls in the Gator topbar (Windows/Linux only). macOS uses
  // native traffic-light buttons. Shown only when no external app is active
  // (body class gator-split / gator-squeezed hides them via CSS); the toolbar
  // view has its own controls when an external app is tiled.
  if (
    typeof window.gatorShell !== 'undefined' &&
    window.gatorShell.isShell &&
    window.gatorShell.platform === 'win32'
  ) {
    const wc = document.getElementById('topbar-wincontrols');
    if (wc) {
      wc.style.display = 'flex';
      wc.innerHTML =
        '<button class="topbar-win-btn win-close" id="tb-win-close" title="Close">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>' +
        '</button>' +
        '<button class="topbar-win-btn" id="tb-win-max" title="Maximize">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="1"/></svg>' +
        '</button>' +
        '<button class="topbar-win-btn" id="tb-win-min" title="Minimize">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>' +
        '</button>';
      document
        .getElementById('tb-win-min')
        .addEventListener('click', () => window.gatorShell.winMinimize());
      document.getElementById('tb-win-max').addEventListener('click', async () => {
        const m = await window.gatorShell.winMaximizeToggle();
        const btn = document.getElementById('tb-win-max');
        if (btn) {
          btn.innerHTML = m
            ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="13" height="13" rx="1"/><path d="M8 8V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-3"/></svg>'
            : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="1"/></svg>';
          btn.title = m ? 'Restore' : 'Maximize';
        }
      });
      document
        .getElementById('tb-win-close')
        .addEventListener('click', () => window.gatorShell.winClose());
      // Sync initial maximize state.
      window.gatorShell.winIsMaximized().then((m) => {
        if (m) {
          const btn = document.getElementById('tb-win-max');
          if (btn) {
            btn.innerHTML =
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="13" height="13" rx="1"/><path d="M8 8V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-3"/></svg>';
            btn.title = 'Restore';
          }
        }

        // Double-click on the drag spacer (or any drag region in the topbar) toggles
        // maximize — standard OS title-bar convention. Works on all platforms.
        if (
          typeof window.gatorShell !== 'undefined' &&
          window.gatorShell.isShell &&
          window.gatorShell.winMaximizeToggle
        ) {
          const dragSpacer = document.getElementById('topbar-drag-spacer');
          if (dragSpacer) {
            dragSpacer.addEventListener('dblclick', () => {
              window.gatorShell.winMaximizeToggle().then((maximized) => {
                // Update the maximize button icon if visible
                const btn = document.getElementById('tb-win-max');
                if (btn) {
                  btn.innerHTML = maximized
                    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="13" height="13" rx="1"/><path d="M8 8V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-3"/></svg>'
                    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="1"/></svg>';
                  btn.title = maximized ? 'Restore' : 'Maximize';
                }
              });
            });
          }
        }
      });
    }
  }
});

/* ── Active Tools Strip ───────────────────────────────── */
const _activeToolNames = new Set();

function _updateActiveTools(toolName, add) {
  if (add && toolName) {
    _activeToolNames.add(toolName);
  } else if (!add && toolName) {
    _activeToolNames.delete(toolName);
  }
  // Active-tool indicators are rendered inline in the message bubble via _renderProse,
  // not in the skill chip row, to avoid confusing them with pinned skill chips.
}

/* ── Gator Scrollbar ──────────────────────────────────── */

/* ── Browser Pane (live screenshots via SSE) ───────── */
let _browserStreamES = null;

function _openBrowserPane() {
  const pane = document.getElementById('browser-pane');
  if (pane) pane.classList.remove('hidden');

  // Connect to browser screenshot stream if not already
  if (!_browserStreamES) {
    _browserStreamES = new EventSource('/api/browser/stream');
    _browserStreamES.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'step' && msg.screenshot) {
          const img = document.getElementById('bp-screenshot');
          const placeholder = document.getElementById('bp-placeholder');
          if (img) {
            img.src = 'data:image/png;base64,' + msg.screenshot;
            img.classList.remove('hidden');
          }
          if (placeholder) placeholder.classList.add('hidden');
          const stepEl = document.getElementById('bp-step');
          if (stepEl && msg.status) stepEl.textContent = msg.status;
        } else if (msg.type === 'status') {
          const btn = document.getElementById('bp-takeover-btn');
          if (btn && msg.paused && btn.dataset.paused !== 'true') {
            btn.textContent = 'Resume';
            btn.dataset.paused = 'true';
          }
          if (!msg.active) {
            const stepEl = document.getElementById('bp-step');
            if (stepEl) stepEl.textContent = 'Done';
          }
        } else if (msg.type === 'done') {
          _stopBrowserStream();
          const stepEl = document.getElementById('bp-step');
          if (stepEl) stepEl.textContent = 'Done — close to return to chat';
        }
      } catch {}
    };
    _browserStreamES.onerror = () => {
      _stopBrowserStream();
      setTimeout(() => {
        // Reconnect if browser is still active
        fetch('/api/browser/status')
          .then((r) => r.json())
          .then((s) => {
            if (s.active) _openBrowserPane();
          })
          .catch(() => {});
      }, 3000);
    };
  }
}

function _stopBrowserStream() {
  if (_browserStreamES) {
    _browserStreamES.close();
    _browserStreamES = null;
  }
}

function _closeBrowserPane() {
  // Cancel the running browser task on the server
  fetch('/api/browser/cancel', { method: 'POST' }).catch(() => {});
  _stopBrowserStream();
  const pane = document.getElementById('browser-pane');
  if (pane) pane.classList.add('hidden');
  const img = document.getElementById('bp-screenshot');
  const placeholder = document.getElementById('bp-placeholder');
  if (img) {
    img.classList.add('hidden');
    img.src = '';
  }
  if (placeholder) placeholder.classList.remove('hidden');
  // Reset pause button state
  const btn = document.getElementById('bp-takeover-btn');
  if (btn) {
    btn.textContent = 'Pause';
    btn.dataset.paused = 'false';
    btn.style.background = '';
    btn.style.color = '';
  }
}

// Wire browser pane buttons
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('bp-close-btn')?.addEventListener('click', _closeBrowserPane);

  const takeoverBtn = document.getElementById('bp-takeover-btn');
  if (takeoverBtn) {
    takeoverBtn.addEventListener('click', async () => {
      const isPaused = takeoverBtn.dataset.paused === 'true';
      const stepEl = document.getElementById('bp-step');
      if (isPaused) {
        try {
          await fetch('/api/browser/resume', { method: 'POST' });
        } catch {}
        takeoverBtn.textContent = 'Pause';
        takeoverBtn.dataset.paused = 'false';
        takeoverBtn.style.background = '';
        takeoverBtn.style.color = '';
        if (stepEl) stepEl.textContent = 'Resumed — agent working...';
      } else {
        try {
          await fetch('/api/browser/pause', { method: 'POST' });
        } catch {}
        takeoverBtn.textContent = 'Resume';
        takeoverBtn.dataset.paused = 'true';
        takeoverBtn.style.background = 'var(--surface3)';
        takeoverBtn.style.color = 'var(--text)';
        if (stepEl)
          stepEl.textContent =
            _browserDisplay === 'pane'
              ? 'Paused — switch to External Window in Settings to interact'
              : 'Paused — interact with browser, then click Resume';
      }
    });
  }

  // MVP: browser pane disabled — external browser only
  // Future: auto-open pane on page load if browser is active
});

/* ── Skill Permission Gate ───────────────────────────── */

function _renderPermissionCard(msgDiv, msg, prose, onApprove, onDeny) {
  const skillLabel = (SKILL_MAP[msg.skill] && SKILL_MAP[msg.skill].label) || msg.skill;

  const card = document.createElement('div');
  card.className = 'permission-card';

  const header = document.createElement('div');
  header.className = 'permission-card-header';
  const headerStrong = document.createElement('strong');
  headerStrong.textContent = skillLabel;
  header.append('⚠️ ', headerStrong, ' needs permission');
  card.appendChild(header);

  const body = document.createElement('div');
  body.className = 'permission-card-body';

  const intro = document.createElement('p');
  intro.textContent = 'This skill requires access to execute commands on your machine:';
  body.appendChild(intro);

  const ul = document.createElement('ul');
  msg.deps.forEach((d) => {
    const li = document.createElement('li');
    const strong = document.createElement('strong');
    strong.textContent = (d.label || d.id) + ':';
    li.appendChild(strong);
    li.append(' ' + (d.reason || ''));
    ul.appendChild(li);
  });
  body.appendChild(ul);

  const warning = document.createElement('p');
  warning.className = 'permission-card-warning';
  warning.textContent =
    'These tools can run any shell command or code — only approve skills you trust.';
  body.appendChild(warning);
  card.appendChild(body);

  const actions = document.createElement('div');
  actions.className = 'permission-card-actions';

  const allowBtn = document.createElement('button');
  allowBtn.className = 'permission-allow-btn';
  allowBtn.textContent = 'Allow for this conversation';
  allowBtn.addEventListener('click', () => {
    allowBtn.disabled = true;
    const depNames = msg.deps.map((d) => d.label || d.id).join(', ');
    while (card.firstChild) card.removeChild(card.firstChild);
    const approved = document.createElement('div');
    approved.className = 'permission-card-approved';
    approved.textContent = '✓ ' + depNames + ' approved for this conversation';
    card.appendChild(approved);
    onApprove();
  });

  const denyBtn = document.createElement('button');
  denyBtn.className = 'permission-deny-btn';
  denyBtn.textContent = 'Deny';
  denyBtn.addEventListener('click', () => {
    const depNames = msg.deps.map((d) => d.label || d.id).join(', ');
    while (card.firstChild) card.removeChild(card.firstChild);
    const denied = document.createElement('div');
    denied.className = 'permission-card-denied';
    const strong = document.createElement('strong');
    strong.textContent = skillLabel;
    denied.append(
      '❌ Permission denied — ',
      strong,
      ' requires ' + depNames + ' to function. Try a different skill.',
    );
    card.appendChild(denied);
    onDeny();
  });

  actions.appendChild(allowBtn);
  actions.appendChild(denyBtn);
  card.appendChild(actions);

  prose.textContent = '';
  prose.appendChild(card);
}

/* ── Browser Confirm Gate ────────────────────────────── */

function _showBrowserConfirmCard(msgDiv, { confirm_id, action }) {
  // Remove any stale confirm card
  const existing = document.getElementById('browser-confirm-card');
  if (existing) existing.remove();

  const card = document.createElement('div');
  card.className = 'system-card';
  card.id = 'browser-confirm-card';

  const body = document.createElement('div');
  body.style.cssText = 'display: flex; align-items: flex-start; gap: 10px; width: 100%;';

  const icon = document.createElement('span');
  icon.textContent = '\uD83C\uDF10';
  icon.style.cssText = 'font-size: 1.1rem; flex-shrink: 0; margin-top: 2px;';

  const textWrap = document.createElement('div');
  textWrap.style.cssText = 'flex: 1; min-width: 0;';

  const title = document.createElement('div');
  title.style.cssText =
    'font-size: 0.85rem; font-weight: 600; color: var(--text); margin-bottom: 2px;';
  title.textContent = 'Open browser?';

  const detail = document.createElement('div');
  detail.style.cssText = 'font-size: 0.78rem; color: var(--text-muted); word-break: break-word;';
  detail.textContent = action;

  textWrap.append(title, detail);

  const btnWrap = document.createElement('div');
  btnWrap.style.cssText = 'display: flex; gap: 6px; flex-shrink: 0; align-items: center;';

  const cancelBtn = document.createElement('button');
  cancelBtn.textContent = 'Cancel';
  cancelBtn.style.cssText =
    'font-size: 0.75rem; padding: 4px 12px; border-radius: 6px; background: var(--surface3); color: var(--text); border: none; cursor: pointer; font-weight: 600;';

  const allowBtn = document.createElement('button');
  allowBtn.textContent = 'Allow';
  allowBtn.style.cssText =
    'font-size: 0.75rem; padding: 4px 12px; border-radius: 6px; background: var(--accent); color: #000; border: none; cursor: pointer; font-weight: 600;';

  const _dismiss = () => {
    card.remove();
  };

  cancelBtn.addEventListener('click', async () => {
    _dismiss();
    await fetch(`/api/browser/confirm/${confirm_id}/cancel`, { method: 'POST' });
  });

  allowBtn.addEventListener('click', async () => {
    _dismiss();
    await fetch(`/api/browser/confirm/${confirm_id}`, { method: 'POST' });
  });

  btnWrap.append(cancelBtn, allowBtn);
  body.append(icon, textWrap, btnWrap);
  card.appendChild(body);
  // Append after msgDiv (not inside it) so card stretches full width
  const container = document.getElementById('messages');
  if (container) {
    container.appendChild(card);
  } else {
    msgDiv.appendChild(card);
  }
}

/* ── Failover Consent Gate ───────────────────────────── */

function _showFailoverConfirmCard(msgDiv, { consent_id, fallback_model }) {
  const existing = document.getElementById('failover-confirm-card');
  if (existing) existing.remove();

  const card = document.createElement('div');
  card.className = 'system-card';
  card.id = 'failover-confirm-card';

  const body = document.createElement('div');
  body.style.cssText = 'display: flex; align-items: flex-start; gap: 10px; width: 100%;';

  const icon = document.createElement('span');
  icon.textContent = '⚠️';
  icon.style.cssText = 'font-size: 1.1rem; flex-shrink: 0; margin-top: 2px;';

  const textWrap = document.createElement('div');
  textWrap.style.cssText = 'flex: 1; min-width: 0;';

  const title = document.createElement('div');
  title.style.cssText =
    'font-size: 0.85rem; font-weight: 600; color: var(--text); margin-bottom: 4px;';
  title.textContent = 'Primary model stalled';

  const detail = document.createElement('div');
  detail.style.cssText = 'font-size: 0.78rem; color: var(--text-muted);';
  detail.textContent = `The model stopped responding. Switch to ${fallback_model} to continue?`;

  textWrap.append(title, detail);

  const btnWrap = document.createElement('div');
  btnWrap.style.cssText = 'display: flex; gap: 6px; flex-shrink: 0; align-items: center;';

  const cancelBtn = document.createElement('button');
  cancelBtn.textContent = 'Cancel';
  cancelBtn.style.cssText =
    'font-size: 0.75rem; padding: 4px 12px; border-radius: 6px; background: var(--surface3); color: var(--text); border: none; cursor: pointer; font-weight: 600;';

  const allowBtn = document.createElement('button');
  allowBtn.textContent = 'Switch';
  allowBtn.style.cssText =
    'font-size: 0.75rem; padding: 4px 12px; border-radius: 6px; background: var(--accent); color: #000; border: none; cursor: pointer; font-weight: 600;';

  const _dismiss = () => {
    card.remove();
  };

  cancelBtn.addEventListener('click', async () => {
    _dismiss();
    await fetch(`/api/failover/confirm/${consent_id}/cancel`, { method: 'POST' });
  });

  allowBtn.addEventListener('click', async () => {
    _dismiss();
    await fetch(`/api/failover/confirm/${consent_id}`, { method: 'POST' });
  });

  btnWrap.append(cancelBtn, allowBtn);
  body.append(icon, textWrap, btnWrap);
  card.appendChild(body);
  const container = document.getElementById('messages');
  if (container) {
    container.appendChild(card);
  } else {
    msgDiv.appendChild(card);
  }
}

/* ── Streaming state (module-level so guard works across submissions) ── */
let _isStreaming = false;

/* ── Browser HITL (in-chat controls) ────────────────── */
let _browserHITLShown = false;
let _hitlPollId = null;
let _hitlTurnId = 0;

function _showBrowserHITL(msgDiv) {
  if (_browserHITLShown) return; // Only show once per response
  _browserHITLShown = true;
  const myTurnId = ++_hitlTurnId;

  const card = document.createElement('div');
  card.className = 'system-card';
  card.id = 'browser-hitl-card';
  card.style.cssText = 'margin: 8px 0;';

  const body = document.createElement('div');
  body.style.cssText = 'display: flex; align-items: center; gap: 10px; width: 100%;';

  const icon = document.createElement('span');
  icon.textContent = '\uD83C\uDF10';
  icon.style.fontSize = '1.1rem';

  const text = document.createElement('span');
  text.id = 'browser-hitl-text';
  text.textContent = 'Browser is working...';
  text.style.cssText = 'flex: 1; font-size: 0.82rem; color: var(--text);';

  const btn = document.createElement('button');
  btn.id = 'browser-hitl-btn';
  btn.textContent = 'Take over';
  btn.style.cssText =
    'font-size: 0.75rem; padding: 4px 12px; border-radius: 6px; background: var(--accent); color: #000; border: none; cursor: pointer; font-weight: 600;';

  btn.addEventListener('click', async () => {
    const isPaused = btn.dataset.paused === 'true';
    if (isPaused) {
      // Hand back
      await fetch('/api/browser/resume', { method: 'POST' });
      btn.textContent = 'Take over';
      btn.dataset.paused = 'false';
      text.textContent = 'Browser is working...';
      btn.style.background = 'var(--accent)';
      btn.style.color = '#000';
    } else {
      // Take over
      await fetch('/api/browser/pause', { method: 'POST' });
      btn.textContent = 'Hand back';
      btn.dataset.paused = 'true';
      text.textContent = "You're in control — interact with the browser directly";
      btn.style.background = 'var(--surface3)';
      btn.style.color = 'var(--text)';
    }
  });

  body.append(icon, text, btn);
  card.appendChild(body);

  // Insert after the status line in the message
  const prose = msgDiv.querySelector('.prose');
  if (prose) {
    prose.parentNode.insertBefore(card, prose.nextSibling);
  } else {
    msgDiv.appendChild(card);
  }

  // Poll browser status to detect bot-block pause
  _hitlPollId = setInterval(async () => {
    try {
      const r = await fetch('/api/browser/status');
      const s = await r.json();
      if (s.bot_block && btn.dataset.botblock !== 'true') {
        btn.dataset.botblock = 'true';
        btn.dataset.paused = 'true';
        icon.textContent = '\uD83D\uDEE1\uFE0F';
        text.textContent = 'Bot wall detected \u2014 solve the CAPTCHA, then click Resume';
        text.style.color = '#f97316';
        btn.textContent = 'Resume';
        btn.style.background = '#f97316';
        btn.style.color = '#000';
        card.style.borderColor = '#f97316';
      } else if (!s.bot_block && s.paused && btn.dataset.paused !== 'true') {
        btn.dataset.paused = 'true';
        btn.textContent = 'Hand back';
        text.textContent = "You're in control \u2014 interact with the browser directly";
        btn.style.background = 'var(--surface3)';
        btn.style.color = 'var(--text)';
      } else if (!s.paused && btn.dataset.paused === 'true') {
        btn.dataset.paused = 'false';
        btn.dataset.botblock = 'false';
        icon.textContent = '\uD83C\uDF10';
        text.textContent = 'Browser is working...';
        text.style.color = 'var(--text)';
        btn.textContent = 'Take over';
        btn.style.background = 'var(--accent)';
        btn.style.color = '#000';
        card.style.borderColor = '';
      }
      if (!s.active || _hitlTurnId !== myTurnId) clearInterval(_hitlPollId);
    } catch (e) {
      /* ignore */
    }
  }, 2000);
}

// Reset HITL state when a new message starts
function _resetBrowserHITL() {
  _hitlTurnId++; // invalidate any in-flight interval closure from a prior turn
  if (_hitlPollId) {
    clearInterval(_hitlPollId);
    _hitlPollId = null;
  }
  _browserHITLShown = false;
  const card = document.getElementById('browser-hitl-card');
  if (card) card.remove();
}

function _initGatorScroll() {
  const messages = document.getElementById('messages');
  if (!messages) return;
  let scrollTimer = null;
  messages.addEventListener(
    'scroll',
    () => {
      messages.classList.add('is-scrolling');
      clearTimeout(scrollTimer);
      scrollTimer = setTimeout(() => {
        messages.classList.remove('is-scrolling');
      }, 1200);
    },
    { passive: true },
  );
}
document.addEventListener('DOMContentLoaded', _initGatorScroll);

/* ── Usage Bar ──────────────────────────────────────── */
async function _refreshUsageBar() {
  try {
    const data = await fetch('/api/usage').then((r) => (r.ok ? r.json() : null));
    if (!data) return;
    const k = (n) =>
      n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(n);
    const fill = (tokId, reqId, d) => {
      const tokEl = document.getElementById(tokId);
      const reqEl = document.getElementById(reqId);
      if (tokEl) tokEl.textContent = k(d.input_tokens) + ' in · ' + k(d.output_tokens) + ' out';
      if (reqEl) reqEl.textContent = d.requests.toLocaleString() + ' requests';
    };
    fill('cfg-usage-today', 'cfg-usage-requests', data.today);
    if (data.last_7_days) fill('cfg-usage-week', 'cfg-usage-week-requests', data.last_7_days);
    if (data.all_time) fill('cfg-usage-all', 'cfg-usage-all-requests', data.all_time);
  } catch {}
}
document.addEventListener('DOMContentLoaded', _refreshUsageBar);

// ── Auto-open Code pane when ?open_project= is in the URL ────────────────────
// A new browser tab opened via the project switcher lands here with the param.
// We wait for the app to initialise, then select the Code skill so the pane
// opens and _caLoadProjects picks up the param and pre-selects the project.
(function () {
  const _openProject = new URLSearchParams(window.location.search).get('open_project');
  if (!_openProject) return;
  // Wait for app + projects to be fully ready before opening Code pane.
  // _caLoadProjects must complete first so the project is already selected
  // when _initCodeAgentPane runs — otherwise the pane renders before the
  // project name is known and shows the empty state / SELECT PROJECT.
  const _tryOpen = () => {
    if (typeof selectSkill !== 'function' || typeof _caLoadProjects !== 'function') {
      setTimeout(_tryOpen, 100);
      return;
    }
    // Pre-load projects so _caActiveProject is set before the pane renders
    _caLoadProjects().then(() => {
      selectSkill('code_agent');
    });
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(_tryOpen, 300));
  } else {
    setTimeout(_tryOpen, 300);
  }
})();

// ── OTA Update Toast ──────────────────────────────────────────────────────────
(function () {
  'use strict';

  let _dismissed = sessionStorage.getItem('ota-dismissed') === '1';
  let _downloadInitiated = sessionStorage.getItem('ota-download-initiated') === '1';
  // State the user X'd while a download was in progress — suppress only that state,
  // so the toast re-appears when the state transitions (e.g. downloading → ready).
  let _softDismissedState = null;
  let _installing = false;

  function _btn(label, bgColor, onClick) {
    const b = document.createElement('button');
    b.textContent = label;
    b.style.cssText =
      'border:none;border-radius:4px;padding:4px 10px;cursor:pointer;font-size:12px;';
    b.style.background = bgColor;
    b.style.color = '#1e1e2e';
    b.addEventListener('click', onClick);
    return b;
  }

  function _xBtn(onClick) {
    const b = document.createElement('button');
    b.textContent = '\u2715';
    b.style.cssText =
      'position:absolute;top:-8px;right:-8px;width:20px;height:20px;border-radius:50%;background:#313244;border:1px solid #555;color:#cdd6f4;cursor:pointer;font-size:11px;line-height:20px;text-align:center;padding:0;display:flex;align-items:center;justify-content:center;';
    b.addEventListener('click', onClick);
    return b;
  }

  function _span(text) {
    const s = document.createElement('span');
    s.textContent = text;
    return s;
  }

  function _renderToast(data) {
    // Hard dismiss only applies before the user has committed to downloading.
    if (_dismissed && !_downloadInitiated) return;
    // Don't clobber the "Updating…" toast painted by _otaInstall.
    if (_installing) return;
    // Soft dismiss: user X'd the toast for the current state — suppress until state changes.
    if (_softDismissedState && data.state === _softDismissedState) return;
    _softDismissedState = null;

    let toast = document.getElementById('ota-update-toast');

    if (!data.available) {
      if (toast) toast.remove();
      return;
    }

    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'ota-update-toast';
      toast.style.cssText = [
        'position:fixed',
        'bottom:20px',
        'left:20px',
        'background:var(--surface)',
        'border:1px solid var(--border)',
        'border-radius:8px',
        'padding:12px 16px',
        'z-index:10001',
        'display:flex',
        'align-items:center',
        'font-size:13px',
        'color:var(--text)',
        'box-shadow:0 4px 12px rgba(0,0,0,0.4)',
        'font-family:inherit',
        'gap:8px',
        'overflow:visible',
      ].join(';');
      document.body.appendChild(toast);
    }

    // Clear and rebuild contents safely
    while (toast.firstChild) toast.removeChild(toast.firstChild);

    if (data.state === 'available') {
      toast.appendChild(_span('Update available \u2014 v' + (data.version || '')));
      toast.appendChild(_btn('Download', '#89b4fa', _otaDownload));
      toast.appendChild(_xBtn(_otaDismiss));
    } else if (data.state === 'downloading') {
      toast.appendChild(_span('Downloading update\u2026 ' + (data.progress || 0) + '%'));
      toast.appendChild(_xBtn(_otaDismiss));
    } else if (data.state === 'ready') {
      toast.appendChild(_span('Update ready'));
      toast.appendChild(_btn('Install & Restart', '#a6e3a1', _otaInstall));
      toast.appendChild(_xBtn(_otaDismiss));
    } else if (data.state === 'error') {
      toast.appendChild(_span('Update download failed'));
      toast.appendChild(_btn('Retry', '#f38ba8', _otaDownload));
      toast.appendChild(_xBtn(_otaDismiss));
    }
  }

  function _otaDismiss() {
    const el = document.getElementById('ota-update-toast');
    if (_downloadInitiated) {
      // Soft dismiss \u2014 hide the current state only; re-show on next transition.
      _softDismissedState = _lastState;
      if (el) el.remove();
      return;
    }
    _dismissed = true;
    sessionStorage.setItem('ota-dismissed', '1');
    if (el) el.remove();
  }

  async function _otaDownload() {
    _downloadInitiated = true;
    sessionStorage.setItem('ota-download-initiated', '1');
    try {
      await fetch('/api/update/download', { method: 'POST' });
    } catch (_) {}
  }

  function _sleep(ms) {
    return new Promise(function (r) {
      setTimeout(r, ms);
    });
  }

  async function _waitForServerDown(timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      await _sleep(1500);
      try {
        const r = await fetch('/api/update/status', { cache: 'no-store' });
        if (!r.ok) return true;
      } catch (_) {
        return true;
      }
    }
    return false;
  }

  async function _waitForServerUp(timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      await _sleep(2000);
      try {
        const r = await fetch('/api/update/status', { cache: 'no-store' });
        if (r.ok) return true;
      } catch (_) {}
    }
    return false;
  }

  function _setToastMessage(text) {
    const toast = document.getElementById('ota-update-toast');
    if (!toast) return;
    while (toast.firstChild) toast.removeChild(toast.firstChild);
    toast.appendChild(_span(text));
  }

  async function _otaInstall() {
    _installing = true;
    _setToastMessage('Updating\u2026 this can take up to a minute.');
    try {
      fetch('/api/update/install', { method: 'POST' });
    } catch (_) {}

    const wentDown = await _waitForServerDown(30000);
    if (!wentDown) {
      _setToastMessage('Update did not start. Launch AI Gator from the Start Menu.');
      _installing = false;
      return;
    }
    _setToastMessage('Installing\u2026 reconnecting when ready.');
    const cameBack = await _waitForServerUp(120000);
    if (cameBack) {
      // Clear OTA session flags so the post-restart page starts clean.
      sessionStorage.removeItem('ota-dismissed');
      sessionStorage.removeItem('ota-download-initiated');
      window.location.reload();
      return;
    }
    _setToastMessage('Update finished \u2014 launch AI Gator from the Start Menu.');
    _installing = false;
  }

  let _lastState = null;

  async function _checkUpdate() {
    if (_dismissed && !_downloadInitiated) return;
    if (_installing) return;
    try {
      const r = await fetch('/api/update/status');
      if (!r.ok) return;
      const data = await r.json();
      _lastState = data.state;
      _renderToast(data);
    } catch (_) {}
  }

  // Fast poll (5 s) while downloading; slow poll (60 s) otherwise
  setInterval(function () {
    if (_lastState === 'downloading') _checkUpdate();
  }, 5000);

  setInterval(_checkUpdate, 60000);

  // Initial check 4 seconds after page load
  setTimeout(_checkUpdate, 4000);
})();

/* ── MCP Connections ─────────────────────────────────────── */

const mcpAddBtn = document.getElementById('mcp-add-btn');
const mcpList = document.getElementById('mcp-connections-list');

if (mcpAddBtn) {
  mcpAddBtn.addEventListener('click', () => {
    if (typeof window.openMcpAddModal !== 'function') {
      console.error('openMcpAddModal not loaded');
      return;
    }
    window.openMcpAddModal({
      onSuccess: (data) => {
        if (data && data.id && !SKILL_MAP[data.id]) {
          window.registerMcpSkill(data.id, data.name);
        } else if (data && data.id) {
          SKILL_MAP[data.id].connected = true;
        }
        _loadMcpConnections();
      },
    });
  });
}

// Delete a connection — uses DOM methods, not innerHTML
function _deleteMcpConnection(id, name) {
  _showConfirmModal(
    'Remove Connection',
    `Remove "${name}"? The /${name.toLowerCase()} skill chip will disappear.`,
    'Remove',
    async () => {
      try {
        const res = await fetch(`/api/config/mcp/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (!res.ok) {
          _showAlert('Failed to remove connection \u2014 please try again.', 'error');
          return;
        }
        // Remove from skill registry so the chip disappears immediately
        const idx = SKILL_REGISTRY.findIndex((s) => s.id === id);
        if (idx !== -1) SKILL_REGISTRY.splice(idx, 1);
        delete SKILL_MAP[id];
        await _loadMcpConnections();
      } catch (e) {
        console.error('MCP delete failed', e);
      }
    },
  );
}

// Render the connections list using DOM methods (no innerHTML with user data)
function _renderMcpConnections(connections) {
  while (mcpList.firstChild) mcpList.removeChild(mcpList.firstChild);

  for (const c of connections) {
    // Row container
    const row = document.createElement('div');
    row.className = 'srow';
    row.dataset.mcpId = c.id;

    // Status dot — grey until async health check resolves
    const dot = document.createElement('div');
    dot.className = 'section-status st-dim';

    // Info block
    const info = document.createElement('div');
    info.className = 'srow-info';

    const label = document.createElement('div');
    label.className = 'srow-label';
    label.textContent = c.name;

    const sub = document.createElement('div');
    sub.className = 'srow-sub';
    const connLabel = c.transport === 'stdio' ? c.command_hint || c.id : c.url_hint || c.id;
    sub.textContent = `${connLabel} \u00b7 ${c.tool_count} tool${c.tool_count !== 1 ? 's' : ''}`;

    info.appendChild(label);
    info.appendChild(sub);

    // Plugin ownership badge (Increment 3/4b, 2026-08-07 milestone) —
    // "from the X plugin" per Increment 3's own TODO ("Postgres MCP —
    // from postgres-mcp plugin"). list_with_status() only sets plugin_id
    // when present, so this is a no-op for manually-added connections.
    if (c.plugin_id) {
      const pluginBadge = document.createElement('div');
      pluginBadge.className = 'srow-sub';
      pluginBadge.style.cssText = 'opacity:.75';
      pluginBadge.textContent = `From the "${c.plugin_id}" plugin`;
      info.appendChild(pluginBadge);
    }

    // Actions block
    const actions = document.createElement('div');
    actions.className = 'srow-actions';

    // Pending-secret completion (Increment 4b) — a plugin-registered
    // connection left disabled with unresolved secrets otherwise has no UI
    // path to ever become usable (Increment 3's open TODO). Shown before
    // Edit/Remove since it's the primary action for a pending row.
    if (c.enabled === false && (c.missing_secrets || []).length) {
      const completeBtn = document.createElement('button');
      completeBtn.className = 'btn-ghost';
      completeBtn.style.cssText = 'font-size:.78rem';
      completeBtn.textContent = 'Complete setup';
      completeBtn.addEventListener('click', () => {
        if (typeof window.openMcpCompleteSecretsModal !== 'function') return; // pragma: allowlist secret
        window.openMcpCompleteSecretsModal(c, { onSuccess: () => _loadMcpConnections() });
      });
      actions.appendChild(completeBtn);
    }

    const editBtn = document.createElement('button');
    editBtn.className = 'btn-ghost';
    editBtn.style.cssText = 'font-size:.78rem';
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', () => {
      if (typeof window.openMcpEditModal !== 'function') return;
      window.openMcpEditModal(c, { onSuccess: () => _loadMcpConnections() });
    });

    const delBtn = document.createElement('button');
    delBtn.className = 'btn-ghost';
    delBtn.style.cssText = 'font-size:.78rem';
    delBtn.textContent = 'Remove';
    delBtn.addEventListener('click', () => _deleteMcpConnection(c.id, c.name));

    actions.appendChild(editBtn);
    actions.appendChild(delBtn);
    row.appendChild(dot);
    row.appendChild(info);
    row.appendChild(actions);
    mcpList.appendChild(row);

    // Async health check — update dot after render. Skipped ONLY for a
    // disabled connection that still has unresolved missing_secrets
    // (Increment 4b): health_check() would otherwise try to spawn/connect it
    // with its still-unresolved {PLACEHOLDER} values — for a stdio server
    // that means launching a real process with a literal "{VAR}" string as
    // an argument/env value for no useful signal (the dot would show an
    // error either way). A connection disabled for a different reason (its
    // connect attempt genuinely failed — no missing_secrets, connect_error
    // set) must keep getting the normal health check (fix #3, 2026-08-07
    // milestone adversarial review of this diff) — otherwise it becomes
    // invisible and unrecoverable (no accurate error dot, and the "Complete
    // setup" button is correctly gated on non-empty missing_secrets so it
    // won't show either). Mirrors the same condition the "Complete setup"
    // button above is gated on.
    if (c.enabled === false && (c.missing_secrets || []).length) {
      dot.title = 'Pending setup';
    } else {
      _checkMcpHealth(c.id, dot);
    }
  }
}

// Async health check — pings server, updates the Settings dot, and propagates to SKILL_MAP entry.
async function _checkMcpHealth(id, dotEl) {
  try {
    const res = await fetch(`/api/config/mcp/${encodeURIComponent(id)}/health`, { method: 'POST' });
    const data = await res.json();
    const ok = data.ok === true;
    dotEl.className = 'section-status ' + (ok ? 'st-ok' : 'st-err');
    // Keep SKILL_MAP connected state in sync so chip/launcher can reflect real status
    const entry = SKILL_MAP[id];
    if (entry) entry.connected = ok;
  } catch {
    dotEl.className = 'section-status st-err';
    const entry = SKILL_MAP[id];
    if (entry) entry.connected = false;
  }
}

// Load and render connections — called on Settings open + after add/delete
async function _loadMcpConnections() {
  try {
    const res = await fetch('/api/config/mcp');
    if (!res.ok) {
      while (mcpList.firstChild) mcpList.removeChild(mcpList.firstChild);
      const errDiv = document.createElement('div');
      errDiv.className = 'srow-sub';
      errDiv.style.cssText = 'padding:6px 0 2px 22px';
      errDiv.textContent = 'Could not load connections \u2014 server error.';
      mcpList.appendChild(errDiv);
      return;
    }
    const data = await res.json();
    const connections = data.connections || [];
    _renderMcpConnections(connections);
  } catch (e) {
    console.error('Failed to load MCP connections', e);
  }
}

// Reload connections each time the Settings drawer opens
const _mcpOrigOpenDrawer = openDrawer;
openDrawer = function () {
  _mcpOrigOpenDrawer();
  _loadMcpConnections();
  loadLlmProfiles();
  if (typeof _refreshGoogleWsStatus === 'function') _refreshGoogleWsStatus();
};

// Initial load on page ready
_loadMcpConnections();

/* ── Model Selector + Swarm Toggle (guide-row pill → rich dropdown) ─── */
(function () {
  'use strict';

  // Derive a friendly short name from any model ID
  function _shortName(mid) {
    // Claude-Sonnet-4.6 → Sonnet 4.6, Claude-Opus-4 → Opus 4
    if (/^Claude-/i.test(mid)) return mid.replace(/^Claude-/i, '').replace(/-/g, ' ');
    // gpt-4.1-mini → GPT-4.1 Mini, gpt-4-turbo → GPT-4 Turbo
    if (/^gpt-/i.test(mid)) {
      return mid
        .replace(/^gpt/i, 'GPT')
        .split('-')
        .map((p, i) => {
          if (i === 0) return p; // GPT
          if (/^\d/.test(p)) return p; // 4.1
          return p.charAt(0).toUpperCase() + p.slice(1); // mini → Mini
        })
        .join(' ');
    }
    return mid;
  }

  const _MODEL_DESC = {
    'Sonnet 4.6': 'Balanced — fast responses, strong reasoning. Best for most tasks.',
    'Opus 4.6': 'Most capable — deeper reasoning for complex analysis and writing.',
    'Haiku 4.5': 'Fastest — great for quick lookups, short replies, and simple tasks.',
    'Sonnet 4.5': 'Balanced — fast responses, strong reasoning.',
    'Sonnet 4': 'Balanced — good reasoning, fast responses.',
    'Opus 4': 'Deep reasoning for complex analysis.',
    'Opus 4.1': 'Deep reasoning for complex analysis.',
    'Opus 4.5': 'Deep reasoning for complex analysis and writing.',
    'Opus 4.7': 'Deep reasoning for complex analysis and writing.',
  };

  const modelBtn = document.getElementById('model-selector');
  const modelLabel = document.getElementById('model-selector-label');
  const modelIcon = document.getElementById('model-selector-icon');
  const modelDrop = document.getElementById('model-dropdown');
  const swarmRow = document.getElementById('swarm-dropdown-row');
  const swarmToggle = document.getElementById('swarm-dropdown-toggle');
  const guideBar = document.querySelector('.input-guide-bottom');
  const chatInput = document.getElementById('chat-input');

  if (!modelBtn || !modelDrop) return;

  let _currentModel = '';
  window._currentModel = '';
  let _swarmOn = false;
  let _available = [];

  // ── Content fade: dim guide hints once the user has typed, NOT on focus.
  // The hints (/, @, Shift+{, open file) are discovery affordances — most useful
  // when the box is focused-but-empty (about to type). Keep them readable then;
  // recede only after there's content so they don't compete with what's typed.
  if (chatInput && guideBar) {
    const _syncGuideFade = () => {
      const hasContent = (chatInput.textContent || '').trim().length > 0;
      guideBar.classList.toggle('input-has-content', hasContent);
    };
    chatInput.addEventListener('input', _syncGuideFade);
    _syncGuideFade();
  }

  // ── Update pill appearance ──
  function _updatePill() {
    const short = _shortName(_currentModel);
    if (_swarmOn) {
      modelLabel.textContent = short + ' · Swarm';
      modelIcon.textContent = '🐝';
      modelBtn.classList.add('swarm-on');
    } else {
      modelLabel.textContent = short;
      modelIcon.textContent = '✦';
      modelBtn.classList.remove('swarm-on');
    }
  }

  // ── Render model options into scroll container ──
  function _renderModelOpts(available, active) {
    const scrollBox = document.getElementById('model-opts-list') || modelDrop;
    scrollBox.querySelectorAll('.guide-model-opt').forEach((el) => el.remove());
    available.forEach((mid) => {
      const opt = document.createElement('div');
      opt.className = 'guide-model-opt';
      const check = document.createElement('div');
      check.className = 'gmd-opt-check';
      check.textContent = mid === active ? '✓' : '';
      const body = document.createElement('div');
      body.className = 'gmd-opt-body';
      const short = _shortName(mid);
      const name = document.createElement('div');
      name.className = 'gmd-opt-name';
      name.textContent = short;
      body.appendChild(name);
      const descText = _MODEL_DESC[short] || '';
      if (descText) {
        const desc = document.createElement('div');
        desc.className = 'gmd-opt-desc';
        desc.textContent = descText;
        body.appendChild(desc);
      }
      opt.appendChild(check);
      opt.appendChild(body);
      opt.addEventListener('click', async (e) => {
        e.stopPropagation();
        try {
          const res = await fetch('/api/config/model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: mid }),
          });
          if (res.ok) {
            _currentModel = mid;
            window._currentModel = mid;
            _updatePill();
            _renderModelOpts(_available, mid);
          }
        } catch {}
      });
      scrollBox.appendChild(opt);
    });
  }

  // ── Toggle dropdown ──
  // The panel is portaled to <body> and positioned with fixed coords on open.
  // The discovery-hints row (.input-guide-bottom, below the textarea) sets
  // container-type: inline-size for its own responsive hint-hiding, which
  // creates a stacking context - it used to be the model button's own
  // ancestor (.input-guide) doing this, trapping the dropdown's z-index
  // behind the chat messages with no in-place escape, so it's portaled out
  // of that subtree regardless of which row ends up owning the property.
  function _positionDrop() {
    const r = modelBtn.getBoundingClientRect();
    modelDrop.style.left = Math.max(8, r.right - modelDrop.offsetWidth) + 'px';
    modelDrop.style.top = Math.max(8, r.top - modelDrop.offsetHeight - 8) + 'px';
  }
  function _openDrop() {
    if (modelDrop.parentElement !== document.body) document.body.appendChild(modelDrop);
    modelDrop.style.position = 'fixed';
    modelDrop.style.right = 'auto';
    modelDrop.style.bottom = 'auto';
    modelDrop.style.display = 'flex';
    _positionDrop();
  }
  function _closeDrop() {
    modelDrop.style.display = 'none';
  }

  modelBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    e.preventDefault();
    if (modelDrop.style.display === 'flex') _closeDrop();
    else _openDrop();
  });

  window.addEventListener('resize', () => {
    if (modelDrop.style.display === 'flex') _positionDrop();
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('#model-selector') && !e.target.closest('#model-dropdown')) {
      modelDrop.style.display = 'none';
    }
  });

  // ── Swarm toggle (inside dropdown) ──
  if (swarmRow) {
    swarmRow.addEventListener('click', async (e) => {
      e.stopPropagation();
      _swarmOn = !_swarmOn;
      swarmToggle && swarmToggle.classList.toggle('on', _swarmOn);
      _updatePill();
      try {
        await fetch('/api/config', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ three_agent_mode: _swarmOn }),
        });
      } catch {}
    });
  }

  // ── Init: load current model + swarm state ──
  async function _initGuideControls() {
    try {
      const [modelRes, cfgRes] = await Promise.all([
        fetch('/api/config/model/status'),
        fetch('/api/config'),
      ]);
      if (modelRes.ok) {
        const data = await modelRes.json();
        _currentModel = data.model;
        window._currentModel = data.model;
        _available = data.available || [];
        _renderModelOpts(_available, _currentModel);
      }
      if (cfgRes.ok) {
        const cfg = await cfgRes.json();
        _swarmOn = !!cfg.three_agent_mode;
        swarmToggle && swarmToggle.classList.toggle('on', _swarmOn);
      }
      _updatePill();
    } catch {}
  }

  window._refreshPromptBarModels = _initGuideControls;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _initGuideControls);
  } else {
    _initGuideControls();
  }
})();

/* ── Custom Web Apps ─────────────────────────────────────────────────── */

async function _loadCustomApps() {
  const list = document.getElementById('custom-apps-list');
  if (!list) return;
  try {
    const res = await fetch('/api/config/custom-apps');
    const data = await res.json();
    list.innerHTML = '';
    (data.apps || []).forEach((app) => {
      const row = document.createElement('div');
      row.className = 'custom-app-row';
      let iconHtml;
      try {
        const host = new URL(app.url).hostname;
        iconHtml =
          '<img src="https://www.google.com/s2/favicons?domain=' +
          host +
          '&sz=32" class="custom-app-row-favicon" alt="" onerror="this.onerror=null;this.style.display=\'none\';this.nextElementSibling.style.display=\'\'"><span class="custom-app-row-globe" style="display:none">' +
          '<img src="/static/icons/globe.svg" alt="">' +
          '</span>';
      } catch {
        iconHtml = '<img src="/static/icons/globe.svg" alt="" class="custom-app-row-globe">';
      }
      row.innerHTML = `<span class="custom-app-row-icon">${iconHtml}</span>
        <span class="custom-app-row-name">${escapeHtml(app.name)}</span>
        <span class="custom-app-row-url">${escapeHtml(app.url)}</span>
        <button class="btn-secondary custom-app-row-btn" data-app-id="${app.id}">Remove</button>`;
      row
        .querySelector('button')
        .addEventListener('click', () => _removeCustomApp(app.id, app.name));
      list.appendChild(row);
    });
  } catch (e) {
    console.error('custom-apps load failed', e);
  }
}

async function _addCustomApp() {
  const nameEl = document.getElementById('custom-app-name');
  const urlEl = document.getElementById('custom-app-url');
  const name = nameEl.value.trim();
  let url = urlEl.value.trim();
  if (!name || !url) return;
  if (!url.startsWith('http://') && !url.startsWith('https://')) url = 'https://' + url;
  try {
    const res = await fetch('/api/config/custom-apps', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, url }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || 'Failed to add app');
      return;
    }
    nameEl.value = '';
    urlEl.value = '';
    _loadCustomApps();
    // Create the pane in the shell immediately
    if (window.gatorShell && window.gatorShell.createCustomApp) {
      window.gatorShell.createCustomApp(data.app);
    }
    // Register as a skill so it appears in the dock
    _registerCustomAppSkill(data.app);
  } catch (e) {
    alert('Network error: ' + e.message);
  }
}

async function _removeCustomApp(appId, appName) {
  if (!confirm(`Remove "${appName}"?`)) return;
  try {
    await fetch(`/api/config/custom-apps/${encodeURIComponent(appId)}`, { method: 'DELETE' });
    _loadCustomApps();
    // Remove from skill registry
    const idx = SKILL_REGISTRY.findIndex((s) => s.id === appId);
    if (idx >= 0) {
      SKILL_REGISTRY.splice(idx, 1);
      delete SKILL_MAP[appId];
      renderDock();
    }
  } catch (e) {
    alert('Failed to remove: ' + e.message);
  }
}

function _registerCustomAppSkill(app) {
  if (SKILL_MAP[app.id]) return;
  const entry = {
    id: app.id,
    label: app.name,
    icon: '<span style="font-size:1.1em">\uD83C\uDF10</span>',
    chipAlias: app.name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, ''),
    category: 'Web',
    chipClass: 'chip-mcp',
    connected: true,
    _customApp: true,
    _customAppUrl: app.url,
    railHidden: false,
    actions: [],
  };
  SKILL_REGISTRY.push(entry);
  SKILL_MAP[entry.id] = entry;
  // Register as a third-pane skill so openThirdPane() handles it —
  // same code path as Teams/Outlook/Slack (topbar split, drag spacer,
  // expand/collapse button, layout consistency).
  if (typeof _TP_SKILL_IDS !== 'undefined') {
    _TP_SKILL_IDS.add(entry.id);
  }
  // Add to dock favorites if not already there
  const favs = loadDockFavs();
  if (!favs.includes(entry.id)) {
    favs.push(entry.id);
    saveDockFavs(favs);
  }
  renderDock();
}

// Custom apps are handled by openThirdPane (registered as _TP_SKILL_IDS).
// No separate _selectCustomApp needed — the third-pane system handles
// topbar split, drag spacer, expand/collapse button, and layout.

// Init: load custom apps on startup and when settings drawer opens
function _initOnReady() {
  _loadCustomApps()
    .then(() => {
      return fetch('/api/config/custom-apps')
        .then((r) => r.json())
        .then((data) => {
          (data.apps || []).forEach((app) => _registerCustomAppSkill(app));
        });
    })
    .catch(() => {});
  const addBtn = document.getElementById('custom-app-add-btn');
  if (addBtn) addBtn.addEventListener('click', _addCustomApp);
  _initGoogleWorkspaceSettings();
}

// Called from the shell toolbar when user clicks "Save as app" CTA pill.
// Opens settings → Integrations panel with the URL pre-filled and the name
// derived from the hostname.
window._shellSuggestCustomApp = function (url) {
  try {
    const parsed = new URL(url);
    const nameEl = document.getElementById('custom-app-name');
    const urlEl = document.getElementById('custom-app-url');
    if (nameEl) nameEl.value = parsed.hostname.replace(/^www\./, '');
    if (urlEl) urlEl.value = url;
    if (typeof window.openSettingsPanel === 'function') {
      window.openSettingsPanel('integrations');
      setTimeout(() => {
        if (nameEl) nameEl.focus();
      }, 300);
    }
  } catch (e) {
    /* ignore invalid URLs */
  }
};
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initOnReady);
} else {
  _initOnReady();
}

/* ── Google Workspace Settings section ───────────────────────────────── */

async function _refreshGoogleWsStatus() {
  try {
    const res = await fetch('/api/config/mcp/presets/google/status');
    const data = await res.json();
    const dot = document.getElementById('google-ws-dot');
    const detail = document.getElementById('google-ws-detail');
    const connectBtn = document.getElementById('google-ws-connect-btn');
    const disconnectBtn = document.getElementById('google-ws-disconnect-btn');
    if (!dot) return;
    if (data.connected) {
      dot.className = 'section-status st-ok';
      detail.textContent = 'Connected · ' + (data.name || 'Google Workspace');
      connectBtn?.classList.add('hidden');
      disconnectBtn?.classList.remove('hidden');
    } else {
      dot.className = 'section-status st-dim';
      detail.textContent = 'Not connected';
      connectBtn?.classList.remove('hidden');
      disconnectBtn?.classList.add('hidden');
    }
  } catch {}
}

async function _pollGoogleWsStatus() {
  const dot = document.getElementById('google-ws-dot');
  const detail = document.getElementById('google-ws-detail');
  const connectBtn = document.getElementById('google-ws-connect-btn');
  const disconnectBtn = document.getElementById('google-ws-disconnect-btn');
  const deadline = Date.now() + 180000; // 3-minute safety net
  const interval = 2000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, interval));
    try {
      const res = await fetch('/api/config/mcp/presets/google/status');
      const data = await res.json();
      if (data.connect_status === 'connecting' || data.connect_status === 'loading') {
        if (detail) detail.textContent = 'Starting server, discovering tools…';
        if (dot) dot.className = 'section-status st-dim';
        continue;
      }
      if (data.connect_status === 'failed' || data.connect_error) {
        if (detail)
          detail.textContent = 'Failed: ' + (data.connect_error || 'connection attempt timed out');
        if (dot) dot.className = 'section-status st-err';
        if (connectBtn) {
          connectBtn.disabled = false;
          connectBtn.textContent = 'Connect';
        }
        return;
      }
      if (data.connected) {
        if (typeof window.registerMcpSkill === 'function') {
          try {
            window.registerMcpSkill(data.connection_id, data.name);
          } catch (e) {}
        }
        if (dot) dot.className = 'section-status st-ok';
        if (detail) detail.textContent = 'Connected · ' + (data.name || 'Google Workspace');
        connectBtn?.classList.add('hidden');
        disconnectBtn?.classList.remove('hidden');
        return;
      }
    } catch {}
  }
  if (detail) detail.textContent = 'Failed: connection timed out after 3 minutes';
  if (dot) dot.className = 'section-status st-err';
  if (connectBtn) {
    connectBtn.disabled = false;
    connectBtn.textContent = 'Connect';
  }
}

function _initGoogleWorkspaceSettings() {
  const connectBtn = document.getElementById('google-ws-connect-btn');
  const disconnectBtn = document.getElementById('google-ws-disconnect-btn');
  if (connectBtn) {
    connectBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const detail = document.getElementById('google-ws-detail');
      const dot = document.getElementById('google-ws-dot');
      const disconnectBtn = document.getElementById('google-ws-disconnect-btn');
      connectBtn.disabled = true;
      connectBtn.textContent = 'Connecting…';
      detail.textContent = 'Loading preset…';

      try {
        const resp = await fetch('/api/config/mcp/presets/google');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const preset = await resp.json();

        const server = preset.servers[0];
        detail.textContent = 'Resolving credentials…';

        const resolveResp = await fetch('/api/config/mcp/presets/resolve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: server.name,
            transport: server.transport,
            command: server.command,
            args: server.args,
            url: server.url || '',
            env_mapping: server.env_mapping || {},
            env_defaults: server.env_defaults || {},
          }),
        });
        const resolved = await resolveResp.json();
        if (!resolveResp.ok) throw new Error(resolved.detail || 'Credential resolution failed');

        // For HTTP presets with a command, spawn the server first
        if (resolved.transport === 'http' && resolved.command) {
          detail.textContent = 'Starting server (this may take a moment)…';
          const spawnResp = await fetch('/api/config/mcp/presets/spawn', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: server.name,
              transport: server.transport,
              command: server.command,
              args: server.args,
              url: server.url || '',
              env_mapping: server.env_mapping || {},
              env_defaults: server.env_defaults || {},
            }),
          });
          const spawnData = await spawnResp.json();
          if (!spawnData.ok) throw new Error(spawnData.error || 'Failed to start server');
          // The spawn endpoint now waits for the port to be ready before
          // returning (up to 30s for uvx package fetch on first run), so no
          // fixed client-side sleep is needed. A short settle lets the HTTP
          // server accept requests after binding.
          if (spawnData.ready === false) {
            throw new Error('Server did not become ready in time — try again');
          }
          await new Promise((r) => setTimeout(r, 500));
        }

        detail.textContent = 'Connecting…';
        const saveResp = await fetch('/api/config/mcp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            transport: resolved.transport,
            url: resolved.url || '',
            name: resolved.name,
            auth_type: 'none',
            command: server.command || '',
            args: server.args || [],
          }),
        });
        const saveData = await saveResp.json();
        if (!saveResp.ok || !saveData.name)
          throw new Error(saveData.detail || saveData.error || 'Connection failed');

        if (typeof window.registerMcpSkill === 'function') {
          try {
            window.registerMcpSkill(saveData.id, saveData.name);
          } catch (e) {}
        }
        dot.className = 'section-status st-ok';
        detail.textContent = 'Connected · ' + saveData.name;
        connectBtn.classList.add('hidden');
        disconnectBtn.classList.remove('hidden');
      } catch (err) {
        detail.textContent = 'Failed: ' + err.message;
        dot.className = 'section-status st-err';
      }
      connectBtn.disabled = false;
      connectBtn.textContent = 'Connect';
    });
  }
  if (disconnectBtn) {
    disconnectBtn.addEventListener('click', async () => {
      if (!confirm('Disconnect Google Workspace? Your Google OAuth tokens will be revoked.'))
        return;
      try {
        const statusRes = await fetch('/api/config/mcp/presets/google/status');
        const statusData = await statusRes.json();
        if (statusData.connection_id) {
          // Kill the spawned HTTP server if it was started via the preset
          try {
            await fetch('/api/config/mcp/presets/spawn/stop', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                command: 'uvx',
                args: [
                  'workspace-mcp',
                  '--transport',
                  'streamable-http',
                  '--tool-tier',
                  'complete',
                ],
              }),
            });
          } catch (e) {}
          await fetch('/api/config/mcp/' + encodeURIComponent(statusData.connection_id), {
            method: 'DELETE',
          });
        }
        const idx = SKILL_REGISTRY.findIndex((s) => s.id === 'mcp-google-workspace');
        if (idx >= 0) {
          SKILL_REGISTRY.splice(idx, 1);
          delete SKILL_MAP['mcp-google-workspace'];
        }
        _GOOGLE_SERVICES.forEach((svc) => {
          if (SKILL_MAP[svc.id]) SKILL_MAP[svc.id].connected = false;
        });
        const favs = loadDockFavs().filter((id) => id !== 'g-gmail');
        saveDockFavs(favs);
        renderDock();
        renderLauncher();
        _refreshGoogleWsStatus();
      } catch (e) {
        alert('Failed to disconnect: ' + e.message);
      }
    });
  }
  _refreshGoogleWsStatus();
}
