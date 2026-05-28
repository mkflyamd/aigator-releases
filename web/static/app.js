/* ── Skill Registry ──────────────────────────────────── */
const ICON = id => `<img src="/static/icons/${id}.svg" class="skill-icon-img" alt="${id}" />`;

const SKILL_REGISTRY = [
  {
    id: 'gator', label: 'Gator', icon: ICON('aigator'), chipAlias: 'gator',
    category: 'AI', chipClass: 'chip-aigator',
    connected: true,
    actions: [
      { icon: '📋', label: "What's on my plate?",     prompt: "Give me a briefing: check my email for unread messages, today's calendar events, any new Teams messages, and my open Jira tickets. Summarize everything concisely.",                                    group: 'daily' },
      { icon: '📥', label: 'Check my email',           prompt: 'Check my Outlook inbox for unread messages and summarize them',                        group: 'daily' },
      { icon: '📅', label: "Today's meetings",         prompt: "What meetings do I have today? Show me my calendar with times, attendees, and any conflicts",  group: 'daily' },
      { icon: '🔍', label: 'Find a doc about…',       prompt: 'Search across Confluence, OneDrive, and OneNote for documents about ',                 inputHint: 'topic or keyword', group: 'search' },
      { icon: '👤', label: 'Who is…?',                prompt: 'Look up this person and show their name, email, title, and department: ',               inputHint: 'name',             group: 'search' },
      { icon: '🎫', label: 'My open tickets',          prompt: 'Show my open Jira tickets with status, priority, and assignee',                        group: 'search' },
      { icon: '🌐', label: 'Search the web',           prompt: 'Search the web for ',                                                                     inputHint: 'what to look up', group: 'search' },
    ]
  },
  {
    id: 'email', label: 'Outlook', icon: ICON('outlook'), chipAlias: 'outlook',
    category: 'Productivity', chipClass: 'chip-email',
    connected: false,
    actions: [
      { icon: '📥', label: 'Check my email',              prompt: 'Check my Outlook inbox for unread messages' },
      { icon: '🔍', label: 'Search email for…',           prompt: 'Search my email for ',           inputHint: 'keyword or topic' },
      { icon: '📖', label: 'Read email from…',            prompt: 'Read the latest email from ',    inputHint: 'name or email' },
      { icon: '📤', label: 'Send email to…',              prompt: 'Send an email to ',              inputHint: 'name or email' },
    ]
  },
  {
    id: 'teams', label: 'Teams', icon: ICON('teams'),
    category: 'Productivity', chipClass: 'chip-teams',
    connected: false,
    actions: [
      { icon: '💬', label: 'Send message to…',            prompt: 'Send a Teams message to ',                       inputHint: 'name or email' },
      { icon: '📌', label: 'Send to saved messages',      prompt: 'Send a Teams message to myself in saved messages: ', inputHint: 'your message' },
      { icon: '👥', label: 'List my Teams',               prompt: 'List the Teams I belong to' },
    ]
  },
  {
    id: 'calendar', label: 'Calendar', icon: ICON('calendar'),
    category: 'Productivity', chipClass: 'chip-calendar',
    connected: false,
    actions: [
      { icon: '📅', label: "What meetings do I have today?",    prompt: "What meetings do I have today?" },
      { icon: '🗓️', label: "Am I free at…",                    prompt: "Am I free at ",              inputHint: 'e.g. 3pm Friday' },
      { icon: '🤝', label: 'Find time to meet with…',           prompt: 'Find a time to meet with ',  inputHint: 'name or email' },
      { icon: '➕', label: 'Schedule a meeting with…',           prompt: 'Schedule a meeting with ',   inputHint: 'name or email' },
    ]
  },
  {
    id: 'onedrive', label: 'OneDrive', icon: ICON('onedrive'),
    category: 'Productivity', chipClass: 'chip-onedrive',
    connected: false,
    actions: [
      { icon: '📂', label: "What files do I have?",        prompt: "List my OneDrive files" },
      { icon: '🔍', label: 'Find a file called…',          prompt: 'Find a file in OneDrive called ', inputHint: 'filename' },
      { icon: '⬆️', label: 'Upload file to OneDrive',      tpAction: 'onedrive' },
    ]
  },
  {
    id: 'jira', label: 'Jira', icon: ICON('jira'),
    category: 'Developer Tools', chipClass: 'chip-jira',
    connected: false,
    actions: [
      { icon: '📋', label: 'My open tickets',                     prompt: 'Show my open Jira tickets' },
      { icon: '🔎', label: 'Get details on an issue',             prompt: 'Get details on Jira issue ',         inputHint: 'issue key, e.g. PROJ-123' },
      { icon: '➕', label: 'Create a new issue',                  prompt: 'Create a new Jira issue: ',          inputHint: 'summary and details' },
      { icon: '💬', label: 'Add comment to issue',               prompt: 'Add a comment to Jira issue ',       inputHint: 'issue key' },
    ]
  },
  {
    id: 'confluence', label: 'Confluence', icon: ICON('confluence'),
    category: 'Developer Tools', chipClass: 'chip-confluence',
    connected: false,
    actions: [
      { icon: '🔍', label: 'Search pages for…',           prompt: 'Search Confluence pages for ',             inputHint: 'keyword or topic' },
      { icon: '➕', label: 'Create a new page',           prompt: 'Create a Confluence page titled ',         inputHint: 'page title' },
      { icon: '🗂️', label: 'List available spaces',       prompt: 'List all accessible Confluence spaces' },
    ]
  },
  {
    id: 'github', label: 'GitHub', icon: ICON('github'), labelBadge: 'Alpha',
    category: 'Developer Tools', chipClass: 'chip-github', chipAlias: 'git',
    connected: false,
    actions: [
      { icon: '👀', label: 'What needs my review?',       prompt: 'Show me pull requests waiting for my review' },
      { icon: '🔴', label: 'My open issues',              prompt: 'List GitHub issues assigned to me' },
      { icon: '✅', label: 'Check my PR status',          prompt: 'Show status of my open pull requests including CI' },
    ]
  },
  {
    id: 'ppt', label: 'PowerPoint', labelBadge: 'Alpha', icon: '<img src="/static/icons/ppt-file.png" class="skill-icon-img" alt="ppt" />', chipAlias: 'ppt',
    category: 'Productivity', chipClass: 'chip-ppt',
    railHidden: true, connected: true,
    actions: [
      { icon: '📋', label: 'Inspect open presentation', prompt: 'Get the slide count, titles, and layouts of my open PowerPoint presentation' },
      { icon: '📖', label: 'Read slide content',        prompt: 'Read all text content and speaker notes from my open PowerPoint presentation' },
      { icon: '📝', label: 'Create new presentation',   prompt: 'Create a new PowerPoint presentation with the following slides: ', inputHint: 'describe slides and content' },
      { icon: '📂', label: 'Browse for a file…',        filePicker: { filetypes: 'PowerPoint (*.pptx)|*.pptx', prompt: 'Read and inspect the PowerPoint file at ' } },
    ]
  },
  {
    id: 'excel', label: 'Excel', labelBadge: 'Alpha', icon: '<img src="/static/icons/excel-file.png" class="skill-icon-img" alt="excel" />', chipAlias: 'excel',
    category: 'Productivity', chipClass: 'chip-excel',
    railHidden: true, connected: true,
    actions: [
      { icon: '📊', label: 'Inspect open workbook',    prompt: 'Get the sheet names, headers, and row count of my open Excel workbook' },
      { icon: '📖', label: 'Read open workbook',       prompt: 'Read all data from my open Excel workbook and show me the contents' },
      { icon: '📝', label: 'Create a workbook',        prompt: 'Create a new Excel workbook with the following data: ',   inputHint: 'describe sheets and data' },
      { icon: '📂', label: 'Browse for a file…',      filePicker: { filetypes: 'Excel (*.xlsx)|*.xlsx|CSV (*.csv)|*.csv', prompt: 'Read and inspect the Excel file at ' } },
    ]
  },
  {
    id: 'docx', label: 'Word', labelBadge: 'Alpha', icon: '<img src="/static/icons/word-file.png" class="skill-icon-img" alt="word" />', chipAlias: 'docx',
    category: 'Productivity', chipClass: 'chip-docx',
    railHidden: true, connected: true,
    actions: [
      { icon: '📄', label: 'Inspect open document',   prompt: 'Get the structure, headings, and metadata of my open Word document' },
      { icon: '📖', label: 'Read open document',      prompt: 'Read the content of my open Word document and show me the text' },
      { icon: '📝', label: 'Create a new document',   prompt: 'Create a new Word document with the following content: ',  inputHint: 'describe content' },
      { icon: '📂', label: 'Browse for a file…',      filePicker: { filetypes: 'Word (*.docx)|*.docx', prompt: 'Read and inspect the Word document at ' } },
    ]
  },
  {
    id: 'onenote', label: 'OneNote', icon: '<img src="/static/icons/onenote.png" class="skill-icon-img" alt="onenote" />', chipAlias: 'onenote',
    category: 'Productivity', chipClass: 'chip-onenote',
    connected: true,
    actions: [
      { icon: '📚', label: 'List my notebooks',    prompt: 'List my OneNote notebooks' },
      { icon: '📑', label: 'List sections in…',    prompt: 'List sections in my OneNote notebook ', inputHint: 'notebook name' },
      { icon: '📖', label: 'Read a page',           prompt: 'Read the OneNote page titled ',        inputHint: 'page title' },
      { icon: '✏️', label: 'Create a page',         prompt: 'Create a OneNote page in section ',    inputHint: 'section name + content' },
    ]
  },
  {
    id: 'slack', label: 'Slack', icon: ICON('slack'),
    category: 'Communication', chipClass: 'chip-slack',
    connected: false,
    actions: [
      { icon: '📋', label: 'List available channels',       prompt: 'List all available Slack channels' },
      { icon: '🔍', label: 'Search a channel…',             prompt: 'Search Slack channel ',              inputHint: 'channel name + topic' },
      { icon: '📊', label: 'Summarize a channel',           prompt: 'Summarize recent threads in Slack channel ', inputHint: 'channel name' },
      { icon: '💬', label: 'Post to a channel',             prompt: 'Post a message to Slack channel ',   inputHint: 'channel name' },
    ]
  },
  {
    id: 'browser', label: 'Browse Web', icon: ICON('browser'),
    chipAlias: 'browse', category: 'Productivity', chipClass: 'chip-browser',
    connected: true,
    actions: [
      { icon: '🔍', label: 'Search the web',     prompt: 'Search the web for ',  inputHint: 'what to search' },
      { icon: '🌐', label: 'Visit a website',    prompt: 'Go to ',               inputHint: 'URL or site name' },
      { icon: '📋', label: 'Extract page data',  prompt: 'Extract data from ',   inputHint: 'URL and what to extract' },
    ]
  },
];

// Append MCP connections that were bootstrapped into the page by the server at load time.
// window.__MCP_SKILLS__ is injected before </head> in health.py so it is always defined here.
(window.__MCP_SKILLS__ || []).forEach(c => {
  SKILL_REGISTRY.push({
    id: c.id,
    label: c.name,
    icon: '<span style="font-size:1.1em">🔌</span>',
    chipAlias: c.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || c.id,
    category: 'MCP',
    chipClass: 'chip-mcp',
    connected: false,
    _mcpInjected: true,
    actions: [],
  });
});

// Append installed marketplace skills (Community, Verified, Mine) bootstrapped by the server.
(window.__USER_SKILLS__ || []).forEach(s => {
  const isMine = s.tier === 'Mine';
  SKILL_REGISTRY.push({
    id: s.id,
    label: s.name,
    icon: isMine ? '<span style="font-size:1.1em">⚡</span>' : '<span style="font-size:1.1em">🧩</span>',
    chipAlias: s.id,
    category: s.tier || 'Community',
    chipClass: 'chip-skill',
    railHidden: true,
    _userCreated: true,
    actions: [],
  });
});

const SKILL_MAP = Object.fromEntries(SKILL_REGISTRY.map(s => [s.id, s]));

// Called by marketplace-pane.js after a user creates a skill so it appears in
// slash commands and the dock immediately without a page reload.
window.registerUserSkill = function(id, name, tier) {
  if (SKILL_MAP[id]) return; // already registered
  const isMine = (tier || 'Mine') === 'Mine';
  const entry = {
    id,
    label: name,
    icon: isMine ? '<span style="font-size:1.1em">⚡</span>' : '<span style="font-size:1.1em">🧩</span>',
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

function _getUnapprovedDeps(skillId) {
  const userSkills = window.__USER_SKILLS__ || [];
  const skill = userSkills.find(s => s.id === skillId);
  if (!skill || !Array.isArray(skill.requires)) return [];
  return skill.requires
    .filter(r => _GATED_DEP_IDS.has(r.id) && !_approvedSkillDeps.has(r.id))
    .map(r => r.id);
}

const LAUNCHER_CATEGORIES = [
  { key: 'communication', label: 'Communication', filter: s => s.category === 'Communication' },
  { key: 'project', label: 'Project', filter: s => s.category === 'Productivity' },
  { key: 'development', label: 'Development', filter: s => ['Developer Tools'].includes(s.category) },
  { key: 'web', label: 'Web', filter: s => s.id === 'browser' },
];

let _activeSkillId = null;
let _activeChips   = [];

// Per-conversation permission grants for gated dep skills (shell_runner, code_runner).
// Resets on page load — intentionally per-conversation scope.
const _approvedSkillDeps = new Set();
const _GATED_DEP_IDS = new Set(['shell_runner', 'code_runner']);

const RAIL_CONFIRM_SKIP_KEY = 'aigator-live-confirm-skip';
const AIGATOR_TIP_KEY = 'aigator-tip-dismissed';

const DOCK_FAVS_KEY = 'dock-favorites';
const DEFAULT_DOCK_FAVS = ['email', 'teams', 'slack', 'onedrive', 'browser'];
const DOCK_ICON_MAP = { email: 'outlook' };
const _dockIconFile = id => (DOCK_ICON_MAP[id] || id);

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
  if (idx >= 0) { favs.splice(idx, 1); } else { favs.push(skillId); }
  saveDockFavs(favs);
  renderDock();
  if (typeof renderLauncher === 'function') renderLauncher();
}

/* ── Dock ────────────────────────────────────────────── */
function renderDock() {
  const container = document.getElementById('dock-favorites');
  if (!container) return;
  // Remove only skill buttons, preserve the launcher "+" button
  container.querySelectorAll('.dock-item[data-skill-id]').forEach(el => el.remove());
  const favIds = loadDockFavs();
  const skills = favIds.map(id => SKILL_MAP[id]).filter(Boolean);
  const launcherBtn = document.getElementById('dock-launcher-btn');

  for (const skill of skills) {
    const btn = document.createElement('button');
    btn.className = 'dock-item';
    btn.title = skill.label;
    btn.dataset.skillId = skill.id;
    btn.draggable = true;

    const iconFile = _dockIconFile(skill.id);
    const ext = skill.id === 'onenote' ? 'png' : 'svg';
    const img = document.createElement('img');
    img.src = '/static/icons/' + iconFile + '.' + ext;
    img.className = 'dock-icon';
    img.alt = skill.label;
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
    // ── Dock drag-reorder ──
    btn.addEventListener('dragstart', (e) => {
      btn.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', skill.id);
      container._dockDragSrcId = skill.id;
    });
    btn.addEventListener('dragend', () => {
      container._dockDragSrcId = null;
      container.querySelectorAll('.dock-item').forEach(d => d.classList.remove('dragging', 'drag-over-top', 'drag-over-bottom'));
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
}

function renderLauncher() {
  const body = document.getElementById('launcher-body');
  if (!body) return;
  body.textContent = '';
  const allSkills = SKILL_REGISTRY.filter(s => !s.railHidden && s.id !== 'gator');

  for (const cat of LAUNCHER_CATEGORIES) {
    const skills = allSkills.filter(s => cat.filter(s));
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

      const iconFile = _dockIconFile(skill.id);
      const ext = skill.id === 'onenote' ? 'png' : 'svg';

      const iconWrap = document.createElement('div');
      iconWrap.className = 'launcher-app-icon';
      const iconImg = document.createElement('img');
      iconImg.src = '/static/icons/' + iconFile + '.' + ext;
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
      descEl.textContent = skill.category || '';
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
      pinBtn.addEventListener('click', e => {
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
  mktBtn.style.cssText = 'justify-content:center;color:var(--text-sub);font-size:.8rem;margin-top:8px;';
  mktBtn.textContent = '+ Browse marketplace';
  mktBtn.addEventListener('click', () => {
    document.getElementById('launcher-backdrop')?.classList.remove('open');
    window.MarketplacePane?.open();
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

function _formatBytes(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/* ── Ctrl+O: Open file picker ───────────────────────── */
function _openFilePicker() {
  fetch('/api/file-picker', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'Open a file', filetypes: 'All supported|*.docx;*.xlsx;*.pptx;*.pdf;*.csv;*.doc;*.xls;*.ppt|Word (*.docx)|*.docx|Excel (*.xlsx)|*.xlsx|PowerPoint (*.pptx)|*.pptx|PDF (*.pdf)|*.pdf|All files (*.*)|*.*' }),
  })
    .then(r => r.json())
    .then(data => {
      if (data.ok && data.file_path) {
        const input = document.getElementById('chat-input');
        const fileName = data.file_path.split(/[/\\]/).pop();
        const ext = fileName.split('.').pop().toLowerCase();
        const fileIconSrc = {
          xlsx: '/static/icons/excel-file.png', xls: '/static/icons/excel-file.png', csv: '/static/icons/excel-file.png',
          docx: '/static/icons/word-file.png', doc: '/static/icons/word-file.png',
          pptx: '/static/icons/ppt-file.png', ppt: '/static/icons/ppt-file.png',
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
          icon.src = fileIconSrc; icon.className = 'file-chip-icon'; icon.alt = ext;
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
        removeBtn.addEventListener('click', e => {
          e.preventDefault(); e.stopPropagation();
          chip.remove();
          input.focus();
        });
        chip.appendChild(removeBtn);
        input.appendChild(chip);
        input.appendChild(document.createTextNode('\u00A0'));
        input.focus();
        if (typeof _moveCaretToEnd === 'function') _moveCaretToEnd(input);
        const skillMap = { docx: 'docx', doc: 'docx', xlsx: 'excel', xls: 'excel', csv: 'excel', pptx: 'ppt', ppt: 'ppt' };
        if (skillMap[ext]) selectSkill(skillMap[ext]);
      }
    })
    .catch(() => {});
}

// Ctrl+O shortcut
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'o') {
    e.preventDefault();
    _openFilePicker();
  }
});

const _TP_SKILL_IDS = new Set(['teams', 'email', 'onenote', 'calendar', 'onedrive', 'jira', 'github', 'slack', 'confluence']); // defined before third-pane.js loads

/* ── Coming Soon ─────────────────────────────────────── */
const _COMING_SOON_SKILLS = {
  ado:    { emoji: '🔷', title: 'Azure DevOps — coming soon!', sub: 'We\'re still working hard to bring more integrations and make AI Gator even smarter. The Gator keeps growing — stay tuned.' },
};

function showComingSoon(id) {
  const cfg = _COMING_SOON_SKILLS[id];
  if (!cfg) return;
  // Close any open third pane
  if (typeof closeThirdPane === 'function' && tpState?.type) closeThirdPane();
  document.getElementById('cs-emoji').textContent = cfg.emoji;
  document.getElementById('cs-title').textContent  = cfg.title;
  document.getElementById('cs-sub').textContent    = cfg.sub;
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
  const form  = document.getElementById('chat-form');
  const input = document.getElementById('chat-input');
  const btn   = document.getElementById('send-btn');
  if (!form) return;
  form.classList.toggle('prompt-disabled', disabled);
  input.contentEditable = disabled ? 'false' : 'true';
  btn.disabled   = disabled;
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
  if (_COMING_SOON_SKILLS[id]) { showComingSoon(id); return; }

  // Switching from a coming-soon view — restore messages
  hideComingSoon();

  // Switching away from a TP skill to a non-TP skill — close the pane
  if (typeof closeThirdPane === 'function' && tpState?.type && !_TP_SKILL_IDS.has(id)) {
    closeThirdPane();
  }

  // Already active and already open — just re-focus, no toggle
  if (_activeSkillId === id && _TP_SKILL_IDS.has(id) && tpState?.type === id) return;

  // Rail click = switch context (clear previous skill chips, but always keep @gator)
  _activeChips.forEach(c => {
    if (c.skillId === 'gator') return; // never remove gator
    const chip = document.querySelector(`.chat-chip[data-skill-id="${c.skillId}"]`);
    if (chip) chip.remove();
  });
  _activeChips = _activeChips.filter(c => c.skillId === 'gator');

  _activeSkillId = id;
  _setRailActive(id);

  // Ensure @gator chip is always present, then add the selected skill
  if (!_activeChips.some(c => c.skillId === 'gator')) _addSkillChip('gator');
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
    _activeChips = _activeChips.filter(c => c.skillId !== tpSkill);
  }
  // Fall back to gator as active
  _activeSkillId = _activeChips.some(c => c.skillId === 'gator') ? 'gator' : null;
  _setRailActive(_activeSkillId);
  _updatePlaceholder();
}

/* ── Shared chip helper ───────────────────────────────── */
function _addSkillChip(skillId) {
  const skill = SKILL_MAP[skillId];
  if (!skill) return;
  if (_activeChips.some(c => c.skillId === skillId)) return; // no duplicates
  _activeChips.push({ skillId, promptText: '' });
  const chipRow = document.getElementById('chat-chip-row');
  chipRow.classList.remove('hidden');
  const alias = skill.chipAlias || skillId;
  const chip = document.createElement('span');
  chip.className = `chat-chip ${skill.chipClass}`;
  chip.dataset.skillId = skillId;
  const alphaBadge = skill.labelBadge ? `<span class="skill-alpha-badge">${skill.labelBadge}</span>` : '';
  const iconHtml = skill.icon ? `<span class="chip-skill-icon">${skill.icon}</span>` : '';
  chip.innerHTML = `${iconHtml}${alias}${alphaBadge ? ' ' + alphaBadge : ''} <button class="chip-remove" aria-label="Remove ${skill.label} context">\u2715</button>`;
  chip.querySelector('.chip-remove').addEventListener('click', (e) => { e.stopPropagation(); removeChip(skillId); });
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
    svg.setAttribute('width', '13'); svg.setAttribute('height', '13');
    svg.setAttribute('viewBox', '0 -960 960 960'); svg.setAttribute('fill', 'currentColor');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M739-83.5q-7-2.5-13-8.5L522-296q-6-6-8.5-13t-2.5-15q0-8 2.5-15t8.5-13l85-85q6-6 13-8.5t15-2.5q8 0 15 2.5t13 8.5l204 204q6 6 8.5 13t2.5 15q0 8-2.5 15t-8.5 13l-85 85q-6 6-13 8.5T754-81q-8 0-15-2.5Zm15-92.5 29-29-147-147-29 29 147 147ZM189.5-83q-7.5-3-13.5-9l-84-84q-6-6-9-13.5T80-205q0-8 3-15t9-13l212-212h85l34-34-165-165h-57L80-765l113-113 121 121v57l165 165 116-116-43-43 56-56H495l-28-28 142-142 28 28v113l56-56 142 142q17 17 26 38.5t9 45.5q0 24-9 46t-26 39l-85-85-56 56-42-42-207 207v84L233-92q-6 6-13 9t-15 3q-8 0-15.5-3Zm15.5-93 170-170v-29h-29L176-205l29 29Zm0 0-29-29 15 14 14 15Zm549 0 29-29-29 29Z');
    svg.appendChild(path);
    addBtn.appendChild(svg);
    addBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      window.MarketplacePane?.open();
    });
    chipRow.appendChild(addBtn);
  }
  // Always move to end
  chipRow.appendChild(addBtn);
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
  document.querySelectorAll('.dock-item[data-skill-id]').forEach(btn => {
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
      dockBadge.classList.add('hidden');
    }
  }
  const launcherBadge = document.getElementById('launcher-badge-' + skillId);
  if (launcherBadge) {
    if (count > 0) {
      launcherBadge.textContent = count > 99 ? '99+' : String(count);
      launcherBadge.classList.remove('hidden');
    } else {
      launcherBadge.classList.add('hidden');
    }
  }
}

/* ── / Skill Picker (reuses mention dropdown infrastructure) ── */
let _slashDropdown = null;  // kept as alias so legacy _closeSlashDropdown calls still work
let _slashFocusIdx = -1;
let _slashCurrentQuery = null; // track last rendered query to avoid re-rendering on same query

function _openSkillPickerDropdown(query) {
  // If dropdown is already open with the same query, don't rebuild (preserves expanded state)
  if (_mentionDropdown && _slashCurrentQuery === query) return;
  _slashCurrentQuery = query;

  closeMentionDropdown();
  closeChannelDropdown();
  _mentionDropdown = _buildDropdown();
  _mentionFocusIdx = -1;

  const q = query.toLowerCase();
  const skillMatches = SKILL_REGISTRY.filter(s => {
    if (!q) return true;
    const alias = (s.chipAlias || s.id).toLowerCase();
    return alias.startsWith(q) || s.label.toLowerCase().startsWith(q);
  });

  if (!skillMatches.length) { closeMentionDropdown(); return; }

  _addSectionLabel(_mentionDropdown, 'SKILLS');

  const hasImages = _aigatorImages.length > 0;

  skillMatches.forEach(s => {
    const alias = s.chipAlias || s.id;
    const badgeHtml = s.labelBadge ? ` <span class="skill-alpha-badge">${s.labelBadge}</span>` : '';
    const actions = (s.actions || []).filter(a => !(s.id === 'gator' && a.group === 'export' && !hasImages));
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
    mainZone.addEventListener('mousedown', e => { e.preventDefault(); _commitSkillChipOnly(s, '/'); });
    item.appendChild(mainZone);

    if (hasActions) {
      const chevronBtn = document.createElement('span');
      chevronBtn.className = 'skill-mention-chevron-btn';
      chevronBtn.textContent = '›';
      chevronBtn.title = 'Show actions';

      // Inline actions container (hidden by default)
      const actionsGroup = document.createElement('div');
      actionsGroup.className = 'skill-mention-actions-group hidden';

      chevronBtn.addEventListener('mousedown', e => {
        e.preventDefault();
        e.stopPropagation();
        const isOpen = !actionsGroup.classList.contains('hidden');
        // Collapse any other open action groups
        _mentionDropdown.querySelectorAll('.skill-mention-actions-group').forEach(g => g.classList.add('hidden'));
        _mentionDropdown.querySelectorAll('.skill-mention-chevron-btn').forEach(b => b.classList.remove('open'));
        if (!isOpen) {
          actionsGroup.classList.remove('hidden');
          chevronBtn.classList.add('open');
        }
      });

      actions.forEach(action => {
        const boundAction = Object.assign({}, action, { skill: s });
        const aItem = document.createElement('div');
        aItem.className = 'skill-mention-action-row';
        aItem.dataset.type = 'action';
        const liveHtml = action.live ? '<span class="slash-live-dot"></span>' : '';
        aItem.innerHTML = `<span class="skill-mention-icon">${action.icon}</span><span class="skill-mention-name">${action.label}</span>${liveHtml}`;
        aItem.addEventListener('mousedown', e => { e.preventDefault(); closeMentionDropdown(); _selectSlashAction(boundAction); });
        actionsGroup.appendChild(aItem);
      });

      item.appendChild(chevronBtn);
      wrapper.appendChild(item);
      wrapper.appendChild(actionsGroup);
    } else {
      wrapper.appendChild(item);
    }

    item.addEventListener('mouseenter', () => {
      _mentionFocusIdx = Array.from(_mentionDropdown.querySelectorAll('.skill-mention-item')).indexOf(item);
      _mentionDropdown.querySelectorAll('.skill-mention-item').forEach((el, i) => el.classList.toggle('focused', i === _mentionFocusIdx));
    });

    _mentionDropdown.appendChild(wrapper);
  });

  const firstItem = _mentionDropdown.querySelector('.skill-mention-item');
  if (firstItem) { firstItem.classList.add('focused'); _mentionFocusIdx = 0; }

  // Marketplace footer — always visible at bottom of slash menu
  const mktFooter = document.createElement('div');
  mktFooter.className = 'slash-marketplace-footer';
  const mktIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  mktIcon.setAttribute('width', '12'); mktIcon.setAttribute('height', '12');
  mktIcon.setAttribute('viewBox', '0 -960 960 960'); mktIcon.setAttribute('fill', 'currentColor');
  const mktPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  mktPath.setAttribute('d', 'M739-83.5q-7-2.5-13-8.5L522-296q-6-6-8.5-13t-2.5-15q0-8 2.5-15t8.5-13l85-85q6-6 13-8.5t15-2.5q8 0 15 2.5t13 8.5l204 204q6 6 8.5 13t2.5 15q0 8-2.5 15t-8.5 13l-85 85q-6 6-13 8.5T754-81q-8 0-15-2.5Zm15-92.5 29-29-147-147-29 29 147 147ZM189.5-83q-7.5-3-13.5-9l-84-84q-6-6-9-13.5T80-205q0-8 3-15t9-13l212-212h85l34-34-165-165h-57L80-765l113-113 121 121v57l165 165 116-116-43-43 56-56H495l-28-28 142-142 28 28v113l56-56 142 142q17 17 26 38.5t9 45.5q0 24-9 46t-26 39l-85-85-56 56-42-42-207 207v84L233-92q-6 6-13 9t-15 3q-8 0-15.5-3Zm15.5-93 170-170v-29h-29L176-205l29 29Zm0 0-29-29 15 14 14 15Zm549 0 29-29-29 29Z');
  mktIcon.appendChild(mktPath);
  const mktLabel = document.createElement('span');
  mktLabel.textContent = 'Browse Skill Marketplace';
  mktFooter.appendChild(mktIcon);
  mktFooter.appendChild(mktLabel);
  mktFooter.addEventListener('mousedown', e => {
    e.preventDefault();
    closeMentionDropdown();
    window.MarketplacePane?.open();
  });
  _mentionDropdown.appendChild(mktFooter);
}

// Commit chip only — no action popup
function _commitSkillChipOnly(skill, trigger) {
  const alias = skill.chipAlias || skill.id;
  const t = trigger || '/';
  _replaceAtHashInInput(t, () => _createInlineChip('chip-skill', t + alias, { skillId: skill.id, triggerPrefix: t }));
  const isTPOpen = typeof tpState !== 'undefined' && tpState?.type && _TP_SKILL_IDS.has(tpState.type);
  const inGator = _activeSkillId === 'gator';
  if (!inGator) {
    _activeSkillId = skill.id;
    if (!isTPOpen && !skill?.railHidden) _setRailActive(skill.id);
  }
  _addSkillChip(skill.id);
  _updatePlaceholder();
  closeMentionDropdown();
}

// Alias so legacy call sites still compile
function _openSlashDropdown(query) { _openSkillPickerDropdown(query); }
function _closeSlashDropdown() {
  // Only close if showing a / skill picker (not a @ people search)
  if (_mentionDropdown && _mentionDropdown.querySelector('[data-type="slash-skill"], [data-type="action"]')) {
    closeMentionDropdown();
  }
}

function _selectSlashSkill(skill) {
  _closeSlashDropdown();
  const alias = skill.chipAlias || skill.id;
  _replaceAtHashInInput('/', () => _createInlineChip('chip-skill', '/' + alias, { skillId: skill.id }));
  const isTPOpen = typeof tpState !== 'undefined' && tpState?.type && _TP_SKILL_IDS.has(tpState.type);
  const inGator = _activeSkillId === 'gator';
  if (!inGator) {
    _activeSkillId = skill.id;
    if (!isTPOpen && !skill.railHidden) _setRailActive(skill.id);
  }
  _addSkillChip(skill.id);
  _updatePlaceholder();
}

function _selectSlashAction(action) {
  console.log('[selectSlash] action:', action?.label, 'prompt:', action?.prompt?.slice(0, 50), 'skill:', action?.skill?.id);
  _closeSlashDropdown();
  const skill = action.skill;

  if (action.filePicker) {
    const { filetypes } = action.filePicker;
    fetch('/api/file-picker', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Select a file', filetypes }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok && data.file_path) {
          // Insert file chip into compose area — DON'T auto-send
          const fileName = data.file_path.split(/[/\\]/).pop();
          const ext = fileName.split('.').pop().toLowerCase();
          const fileIconSrc = {
            xlsx: '/static/icons/excel-file.png', xls: '/static/icons/excel-file.png', csv: '/static/icons/excel-file.png',
            docx: '/static/icons/word-file.png', doc: '/static/icons/word-file.png',
            pptx: '/static/icons/ppt-file.png', ppt: '/static/icons/ppt-file.png',
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
            icon.src = fileIconSrc; icon.className = 'file-chip-icon'; icon.alt = ext;
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
      if (title) { title.classList.remove('tp-title-pulse'); void title.offsetWidth; title.classList.add('tp-title-pulse'); }
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
  if (!popover) { injectChip(skill.id, action.prompt, action.inputHint); return; }
  document.getElementById('qa-confirm-msg').textContent =
    `This will modify your open ${action.label.includes('presentation') ? 'presentation' : 'workbook'}. Changes may not be undoable. Proceed?`;
  popover.classList.remove('hidden');

  // Position above the input
  const inputRow = document.getElementById('chat-input-row');
  const r = inputRow.getBoundingClientRect();
  popover.style.top  = (r.top - 10) + 'px';
  popover.style.left = (r.left + r.width / 2) + 'px';
  popover.style.transform = 'translate(-50%, -100%)';
  popover.style.position  = 'fixed';

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
function _showQuickActions() { /* replaced by / dropdown */ }
function _hideQuickActions() { /* replaced by / dropdown */ }

/* ── Chat pane resize ────────────────────────────────── */
function initChatResize() {
  const handle = document.getElementById('main-resize');
  const main   = document.querySelector('.main');
  if (!handle || !main) return;

  const MIN_W = 320, MAX_W = 900;
  const saved = parseInt(localStorage.getItem('chat-pane-width'));
  if (saved) main.style.flexBasis = saved + 'px';

  let dragging = false, startX = 0, startW = 0;

  handle.addEventListener('mousedown', e => {
    dragging = true;
    startX = e.clientX;
    startW = main.offsetWidth;
    handle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    // Handle is on left edge: dragging left = wider chat, dragging right = narrower
    const w = Math.min(MAX_W, Math.max(MIN_W, startW - (e.clientX - startX)));
    main.style.flexBasis = w + 'px';
  });
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    localStorage.setItem('chat-pane-width', main.offsetWidth);
  });
}

/* ── Chip injection ──────────────────────────────────── */
function injectChip(skillId, promptText, inputHint) {
  const skill = SKILL_MAP[skillId];
  if (!skill) return;

  // Add chip via shared helper (prevents duplicates)
  _addSkillChip(skillId);
  // Store the prompt text for this action
  const existing = _activeChips.find(c => c.skillId === skillId);
  if (existing) existing.promptText = promptText;

  // Strip leading @skillId prefix if present
  const atPrefix = `@${skillId} `;
  const body = promptText.startsWith(atPrefix) ? promptText.slice(atPrefix.length) : promptText;

  // Clear everything (inline chips, text, file chips) then set fresh text
  console.log('[injectChip] skillId:', skillId, 'body:', body?.slice(0, 50), 'inputHint:', inputHint);
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
  document.querySelectorAll('.chat-chip.chip-selected').forEach(c => c.classList.remove('chip-selected'));
  chip.classList.add('chip-selected');
  chip.focus();
}

function removeChip(skillId, autoSelectNext = false) {
  // @gator is always-on by default — only removable via explicit X click, not backspace
  if (skillId === 'gator' && autoSelectNext) return;
  const idx = _activeChips.findIndex(c => c.skillId === skillId);
  _activeChips = _activeChips.filter(c => c.skillId !== skillId);
  const chip = document.querySelector(`.chat-chip[data-skill-id="${skillId}"]`);
  if (chip) chip.remove();
  // If removing the active skill, fall back to gator or null
  if (_activeSkillId === skillId) {
    _activeSkillId = _activeChips.some(c => c.skillId === 'gator') ? 'gator'
      : _activeChips.length ? _activeChips[_activeChips.length - 1].skillId : null;
    _setRailActive(_activeSkillId);
  }
  _updatePlaceholder();
  _ensureAddSkillBtn();
  // Auto-select the nearest remaining chip so user can keep pressing backspace
  if (autoSelectNext && _activeChips.length) {
    const nextIdx = Math.min(idx, _activeChips.length - 1);
    const nextChip = document.querySelector(`.chat-chip[data-skill-id="${_activeChips[nextIdx].skillId}"]`);
    if (nextChip) _selectChip(nextChip);
  }
}

function buildFinalMessage(typedText) {
  let text = typedText;
  // Append resolved people context so Claude has the email addresses
  const people = window._resolvedPeople || [];
  if (people.length) {
    const ctx = people.map(p => `[${p.name} = ${p.email}${p.job_title ? ', ' + p.job_title : ''}]`).join(', ');
    text = `${text}\n(Resolved contacts: ${ctx})`;
  }
  if (_activeChips.length === 0) return text;
  // Chips are UI-only — send just the prompt text, not the @alias prefix
  const body = text || _activeChips.map(c => c.promptText).filter(Boolean).join('\n');
  return body;
}


/* ── Connection status dots ──────────────────────────── */
async function checkSkillConnectionStatus() {
  let m365Ok       = false;
  let teamsOk      = false;
  let apiOk        = false;
  let jiraOk       = false;
  let confluenceOk = false;
  let slackOk      = false;

  try {
    const d = await fetch('/api/auth/status').then(r => r.json());
    m365Ok = d.authenticated === true;
    teamsOk = d.teams_token_ok === true;
  } catch {}
  try {
    const d = await fetch('/api/config/apikey/status').then(r => r.json());
    apiOk = d.configured === true;
  } catch {}
  try {
    const d = await fetch('/api/config/jira/status').then(r => r.json());
    jiraOk = d.configured === true && !d.error;
    window.GATOR_JIRA_URL = d.base_url || '';
  } catch { window.GATOR_JIRA_URL = ''; }
  try {
    const d = await fetch('/api/config/confluence/status').then(r => r.json());
    confluenceOk = d.configured === true && !d.error;
  } catch {}
  try {
    const d = await fetch('/api/auth/slack/status').then(r => r.json());
    slackOk = d.configured === true && !!d.user;
  } catch {}

  SKILL_REGISTRY.forEach(s => {
    if (['email', 'calendar', 'onedrive', 'contacts', 'people'].includes(s.id))
      s.connected = m365Ok;
    else if (s.id === 'teams')
      s.connected = teamsOk;
    else if (s.id === 'jira')
      s.connected = jiraOk;
    else if (s.id === 'confluence')
      s.connected = confluenceOk;
    else if (s.id === 'slack')
      s.connected = slackOk;
    else if (s.id === 'gator')
      s.connected = apiOk;
    else if (s.id === 'github')
      s.connected = githubOk;
    else if (s.id === 'ado')
      s.connected = false;
    else
      s.connected = apiOk;
  });

  document.querySelectorAll('.skill-icon-btn').forEach(btn => {
    const skill = SKILL_MAP[btn.dataset.skillId];
    if (!skill) return;
    const dot = btn.querySelector('.skill-status-dot');
    if (dot) dot.className = `skill-status-dot ${skill.connected ? 'dot-connected' : 'dot-disconnected'}`;
  });
}

/* ── Context window meter ────────────────────────────── */
let _contextUsed  = 0;
let _contextLimit = 200000;

function _updateContextMeter() {
  const pct  = Math.min(_contextUsed / _contextLimit, 1);
  const btn  = document.getElementById('send-btn');
  const fill = document.getElementById('ctx-fill');
  if (!btn || !fill) return;

  fill.style.height = _contextUsed === 0 ? '0' : Math.max(pct * 100, 4) + '%';

  if (pct >= 0.95)      btn.dataset.ctx = 'crit';
  else if (pct >= 0.75) btn.dataset.ctx = 'warn';
  else                  delete btn.dataset.ctx;
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
    _activeChannels = _activeChannels.filter(c => (c.chat_id || c.channel_id) !== uid);
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
  if (_pinSearchController) { _pinSearchController.abort(); _pinSearchController = null; }
  if (_pinDropdown) { _pinDropdown.remove(); _pinDropdown = null; _pinFocusIdx = -1; }
}

/* ── Office document icons (used by { pins + @ chip docActions) ── */
const _OFFICE_ICONS = { word: '\uD83D\uDCC4', excel: '\uD83D\uDCCA', ppt: '\uD83D\uDCD1' };

function _addPinItem(dd, pin, i) {
  const icon = _OFFICE_ICONS[pin.source] || {email:'\u2709\uFE0F',teams:'\uD83D\uDCAC',confluence:'\uD83D\uDCDA',slack:'\uD83D\uDCAC',jira:'\uD83C\uDFAB',onedrive:'\uD83D\uDCC2',onenote:'\uD83D\uDCDD',calendar:'\uD83D\uDCC5'}[pin.source] || '\uD83D\uDCCC';
  const item = document.createElement('div');
  item.className = 'skill-mention-item';
  item.dataset.pinIdx = i;
  item.innerHTML = `<span class="skill-mention-icon">${icon}</span><span class="skill-mention-name">${escapeHtml(pin.label)}</span><span class="skill-mention-badge">${pin.source}</span>`;
  item.addEventListener('mousedown', e => { e.preventDefault(); commitPinMention(pin); });
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
    pins = await fetch(`/api/context/pins?context_id=${cid}`, { signal: _pinSearchController.signal }).then(r => r.ok ? r.json() : []);
  } catch (err) {
    if (err.name === 'AbortError') return;
    pins = [];
  }
  if (!_pinDropdown) return;
  _pinSearchController = null;
  _pinDropdown.innerHTML = '';
  if (!pins.length) { closePinDropdown(); return; }
  const q = query.toLowerCase();
  const filtered = q ? pins.filter(p => (p.label || '').toLowerCase().includes(q) || (p.source || '').toLowerCase().includes(q)) : pins;
  if (!filtered.length) { closePinDropdown(); return; }
  filtered.forEach((p, i) => _addPinItem(_pinDropdown, p, i));
  _pinDropdown._pins = filtered;
  _pinFocusIdx = -1;
}


function commitPinMention(pin) {
  closePinDropdown();
  const icon = _OFFICE_ICONS[pin.source]
    || {email:'\u2709\uFE0F',teams:'\uD83D\uDCAC',confluence:'\uD83D\uDCDA',slack:'\uD83D\uDCAC',jira:'\uD83C\uDFAB',onedrive:'\uD83D\uDCC2',onenote:'\uD83D\uDCDD',calendar:'\uD83D\uDCC5'}[pin.source]
    || '\uD83D\uDCCC';
  const chip = document.createElement('span');
  chip.className = 'pin-ref-chip';
  chip.contentEditable = 'false';
  chip.dataset.pinSource = pin.source;
  chip.dataset.pinId = pin.id;
  chip.textContent = `${icon} ${pin.label}`;
  chip.title = `${pin.source}: ${pin.label}`;
  _replaceAtHashInInput('{', () => chip);
}

/* ── @ mention dropdown ──────────────────────────────── */
let _mentionDropdown = null;
let _mentionFocusIdx = -1;
let _mentionSearchController = null; // AbortController for in-flight people searches
let _mentionDropdownCleanup = null;

function _getChatInputAnchor() {
  return document.getElementById('chat-input-row') || document.getElementById('chat-form');
}

function _positionDropdownFixed(dd, anchor, { width = 300, offsetLeft = 14, offsetGap = 8 } = {}) {
  if (!anchor) return () => {};
  const reposition = () => {
    if (!dd.isConnected) return;
    const rect = anchor.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
    const computedWidth = Math.min(width, rect.width);
    dd.style.position = 'fixed';
    dd.style.width = `${computedWidth}px`;
    dd.style.zIndex = '99999';
    dd.style.overflowY = 'auto';
    dd.style.overflowX = 'hidden';
    let left = rect.left + offsetLeft;
    const minLeft = 8;
    if (left + computedWidth > viewportWidth - minLeft) {
      left = viewportWidth - computedWidth - minLeft;
    }
    if (left < minLeft) left = minLeft;
    dd.style.left = `${Math.round(left)}px`;
    const measuredHeight = dd.offsetHeight || 0;
    const estimateHeight = measuredHeight || 240;
    const spaceAbove = rect.top - offsetGap - minLeft;
    const spaceBelow = viewportHeight - rect.bottom - offsetGap - minLeft;
    const shouldOpenAbove = estimateHeight <= spaceAbove || (spaceAbove > spaceBelow && spaceAbove > 0);
    let top;
    let maxHeight;
    if (shouldOpenAbove) {
      maxHeight = Math.max(120, spaceAbove);
      top = Math.max(minLeft, rect.top - offsetGap - Math.min(estimateHeight, maxHeight));
    } else {
      maxHeight = Math.max(120, spaceBelow);
      top = Math.min(viewportHeight - minLeft - estimateHeight, rect.bottom + offsetGap);
      if (top < minLeft) top = minLeft;
    }
    const actualHeight = dd.offsetHeight || estimateHeight;
    const maxTopAllowed = viewportHeight - actualHeight - minLeft;
    if (!Number.isNaN(maxTopAllowed)) {
      top = Math.min(top, maxTopAllowed);
    }
    if (top < minLeft) top = minLeft;
    dd.style.top = `${Math.round(top)}px`;
    dd.style.bottom = 'auto';
    if (maxHeight && maxHeight !== Infinity) {
      const allowable = shouldOpenAbove ? spaceAbove : spaceBelow;
      dd.style.maxHeight = `${Math.floor(Math.max(120, allowable))}px`;
    } else {
      dd.style.maxHeight = '';
    }
  };
  reposition();
  requestAnimationFrame(reposition);
  requestAnimationFrame(reposition);
  const onFrame = () => reposition();
  window.addEventListener('resize', onFrame);
  window.addEventListener('scroll', onFrame, true);
  let ro = null;
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => reposition());
    ro.observe(anchor);
  }
  let mo = null;
  if (typeof MutationObserver !== 'undefined') {
    mo = new MutationObserver(() => reposition());
    mo.observe(dd, { childList: true, subtree: true, attributes: true });
  }
  return () => {
    window.removeEventListener('resize', onFrame);
    window.removeEventListener('scroll', onFrame, true);
    if (ro) ro.disconnect();
    if (mo) mo.disconnect();
  };
}

function closeMentionDropdown() {
  clearTimeout(_mentionDebounceTimer); _mentionDebounceTimer = null;
  if (_mentionSearchController) { _mentionSearchController.abort(); _mentionSearchController = null; }
  if (_mentionDropdownCleanup) { _mentionDropdownCleanup(); _mentionDropdownCleanup = null; }
  if (_mentionDropdown) { _mentionDropdown.remove(); _mentionDropdown = null; _mentionFocusIdx = -1; }
  _slashCurrentQuery = null;
}

function _buildDropdown() {
  const dd = document.createElement('div');
  dd.className = 'skill-mention-dropdown';
  // Prevent any click inside the dropdown from stealing focus from the input
  dd.addEventListener('mousedown', e => e.preventDefault());
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
  item.addEventListener('mousedown', e => { e.preventDefault(); commitPersonMention(person); });
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

  if (_mentionSearchController) { _mentionSearchController.abort(); _mentionSearchController = null; }
  clearTimeout(_mentionDebounceTimer);

  const stateDiv = document.createElement('div');
  stateDiv.className = 'skill-mention-loading';
  stateDiv.textContent = query.length < 2 ? 'Type a name to search people\u2026' : 'Searching people\u2026';
  _mentionDropdown.appendChild(stateDiv);

  if (query.length < 2) return;

  _mentionDebounceTimer = setTimeout(async () => {
    if (!_mentionDropdown) return;
    _mentionSearchController = new AbortController();
    try {
      const res = await fetch(`/api/people/search?q=${encodeURIComponent(query)}`, { signal: _mentionSearchController.signal });
      const data = await res.json();
      if (!_mentionDropdown) return;
      _mentionDropdown.innerHTML = '';
      if (data.people?.length) {
        data.people.forEach(p => _addPersonItem(_mentionDropdown, p));
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
      if (_mentionDropdown) { _mentionDropdown.innerHTML = ''; }
    }
  }, 250);
}


function commitPersonMention(person) {
  closeMentionDropdown();

  // Replace @query with inline person chip
  _replaceAtHashInInput('@', () => _createInlineChip('chip-person', '@' + person.name, {
    personName: person.name, personEmail: person.email || ''
  }));
}

/* ── # channel dropdown ──────────────────────────────── */
let _channelDropdown = null;
let _channelFocusIdx = -1;
let _channelSearchController = null;
let _channels_busted = false;
let _channelDropdownCleanup = null;

function closeChannelDropdown() {
  if (_channelSearchController) { _channelSearchController.abort(); _channelSearchController = null; }
  if (_channelDropdownCleanup) { _channelDropdownCleanup(); _channelDropdownCleanup = null; }
  if (_channelDropdown) { _channelDropdown.remove(); _channelDropdown = null; _channelFocusIdx = -1; }
}

async function openChannelDropdown(query) {
  closeChannelDropdown();
  closeMentionDropdown();
  _channelDropdown = document.createElement('div');
  _channelDropdown.className = 'skill-mention-dropdown channel-dropdown';
  document.body.appendChild(_channelDropdown);
  const anchor = _getChatInputAnchor();
  _channelDropdownCleanup = anchor ? _positionDropdownFixed(_channelDropdown, anchor, { width: 320 }) : null;

  // Use cached Teams chats if available — populated whenever Teams pane loads, persists across pane switches
  const _cachedChats = window._teamsChatsCache?.length ? window._teamsChatsCache
    : (typeof tpState !== 'undefined' && tpState.type === 'teams' && tpState.list?.length ? tpState.list : null);
  const tpChats = _cachedChats
    ? _cachedChats.map(c => ({
        type: 'groupchat',
        chat_id: c.id,
        channel_name: c.topic || c.display_name || (c.chat_type === 'meeting' ? 'Meeting' : c.id),
        team_name: c.chat_type === 'oneOnOne' ? 'Direct Message' : c.chat_type === 'meeting' ? 'Meetings' : 'Group Chat',
      }))
    : null;

  if (tpChats) {
    _channelDropdown.innerHTML = '';
    const ql = query.toLowerCase();
    const channels = tpChats.filter(ch => {
      if (ql && !ch.channel_name.toLowerCase().includes(ql)) return false;
      return !_activeChannels.some(a => (a.chat_id || a.channel_id) === ch.chat_id);
    });
    if (!channels.length) {
      _channelDropdown.innerHTML = `<div class="skill-mention-loading">No chats found${query ? ` for "${escapeHtml(query)}"` : ''}</div>`;
      return;
    }
    _renderChannelItems(channels);
    return;
  }

  // Fallback: fetch from API — route to Slack, Teams, or both based on active skills
  const hasSlack = _activeChips.some(c => c.skillId === 'slack') || _activeSkillId === 'slack';
  const hasTeams = _activeChips.some(c => c.skillId === 'teams') || _activeSkillId === 'teams';
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
        (parsed.channels || []).forEach(ch => {
          const name = ch.channel_name || ch.name || '';
          if (!ql || name.toLowerCase().includes(ql)) {
            allChannels.push({ type: 'slack_channel', channel_id: name, channel_name: name, team_name: 'Slack' });
          }
        });
      } catch (e) { if (e.name === 'AbortError') throw e; }
    }

    if (fetchTeams) {
      const bustParam = _channels_busted ? '&bust=true' : '';
      _channels_busted = false;
      const res = await fetch(`/api/channels/search?q=${encodeURIComponent(query)}${bustParam}`, { signal: _channelSearchController.signal });
      const teamsData = await res.json();
      if (teamsData.channels) allChannels.push(...teamsData.channels);
    }

    const data = { channels: allChannels };
    if (!_channelDropdown) return;
    _channelDropdown.innerHTML = '';

    const errors = (data.channels || []).filter(ch => ch.type === '_error');
    const channels = (data.channels || []).filter(ch => {
      if (ch.type === '_error') return false;
      const uid = ch.type === 'groupchat' ? ch.chat_id : (ch.channel_id || ch.channel_name);
      return !_activeChannels.some(a => (a.chat_id || a.channel_id) === uid);
    });
    if (data.error) {
      _channelDropdown.innerHTML = `<div class="skill-mention-loading" style="color:var(--danger)">⚠ ${escapeHtml(data.error)}</div>`;
      return;
    }
    errors.forEach(e => {
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
          es.addEventListener('status', se => {
            btn.textContent = JSON.parse(se.data);
          });
          es.addEventListener('result', se => {
            es.close();
            btn.textContent = '✓ Done';
            _channels_busted = true;
            _showConnectivityToast('Teams token captured', 'success');
            setTimeout(() => openChannelDropdown(''), 800);
          });
          es.addEventListener('error', se => {
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
      _channelDropdown.querySelector('.channel-refresh-link')?.addEventListener('click', () => { _channels_busted = true; openChannelDropdown(query); });
      return;
    }

    _renderChannelItems(channels);
  } catch (err) {
    if (err.name !== 'AbortError' && _channelDropdown) {
      _channelDropdown.innerHTML = '<div class="skill-mention-loading">Could not load channels</div>';
    }
  }
}

function _renderChannelItems(channels) {
  const byTeam = {};
  channels.forEach(ch => {
    const grp = ch.team_name || 'Group Chat';
    (byTeam[grp] = byTeam[grp] || []).push(ch);
  });
  Object.entries(byTeam).forEach(([teamName, chs]) => {
    const lbl = document.createElement('div');
    lbl.className = 'skill-mention-section';
    lbl.textContent = teamName.toUpperCase();
    _channelDropdown.appendChild(lbl);
    chs.forEach(ch => {
      const item = document.createElement('div');
      item.className = 'skill-mention-item';
      const isGC = ch.type === 'groupchat';
      item.dataset.type = isGC ? 'groupchat' : 'channel';
      if (isGC) { item.dataset.chatId = ch.chat_id; }
      else { item.dataset.channelId = ch.channel_id; item.dataset.teamId = ch.team_id; }
      item.innerHTML = `<span class="skill-mention-icon" style="font-size:.9rem">${isGC ? '💬' : '#'}</span>
        <span class="skill-mention-name">${escapeHtml(ch.channel_name)}</span>
        <span class="skill-mention-badge">${escapeHtml(isGC ? 'Group Chat' : ch.team_name)}</span>`;
      item.addEventListener('mousedown', e => { e.preventDefault(); commitChannelMention(ch); });
      _channelDropdown.appendChild(item);
    });
  });
}

function commitChannelMention(ch) {
  closeChannelDropdown();

  // Track in _activeChannels
  const uid = ch.chat_id || ch.channel_id;
  if (!_activeChannels.some(c => (c.chat_id || c.channel_id) === uid)) {
    _activeChannels.push(ch);
  }

  // Replace #query with inline channel chip
  const isSlack = ch.type === 'slack_channel';
  const chipLabel = '#' + ch.channel_name + (isSlack ? '' : '');
  const chipSub = isSlack ? ' Slack' : ' ' + (ch.team_name || 'Teams');
  const chipColorClass = isSlack ? 'chip-slack' : 'chip-teams';
  _replaceAtHashInInput('#', () => _createInlineChip('chip-channel ' + chipColorClass, chipLabel + chipSub, {
    channelName: ch.channel_name, channelId: ch.channel_id || '', chatId: ch.chat_id || '',
    teamName: ch.team_name || '', channelType: ch.type || ''
  }));

  // Ensure appropriate skill is active
  const skillNeeded = isSlack ? 'slack' : 'teams';
  if (!_activeChips.some(c => c.skillId === skillNeeded)) {
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
    window._resolvedPeople = (window._resolvedPeople || []).filter(p => p.email !== person.email);
  });
  chipRow.appendChild(badge);
  _ensureAddSkillBtn(); // keep + at the end
}

/* ── History persistence ─────────────────────────────── */
const HISTORY_KEY = 'chat-history';
const HISTORY_MAX = 50;

function loadHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); }
  catch { return []; }
}
function saveHistory(hist) {
  const trimmed = hist.slice(-HISTORY_MAX);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(trimmed));
}
// Strip Slack auth misinformation from history — only model-directed auth actions, not page content
const _SLACK_POISON = /go to (Settings|the Settings).*slack|refresh your (slack )?token|sign.?in to slack|reconnect slack|your slack session (has )?expired|re-authenticate (with )?slack/i;
function _sanitizeHistory(hist) {
  return hist.map(m => {
    if (m.role !== 'assistant' || typeof m.content !== 'string') return m;
    if (!_SLACK_POISON.test(m.content)) return m;
    // Replace the poisoned Slack text with corrected info
    const cleaned = m.content.replace(/go to (Settings|the Settings).*slack[^.]*\.|refresh your (slack )?token[^.]*\.|sign.?in to slack[^.]*\.|reconnect slack[^.]*\.|your slack session (has )?expired[^.]*\.|re-authenticate (with )?slack[^.]*/gi,
      'Slack is connected via MCP server — no token needed.');
    return { ...m, content: cleaned };
  });
}

function clearHistory() {
  hideComingSoon();
  history = [];
  _saveActiveTabHistory();
  localStorage.removeItem('tab-disp-' + _activeTabId);
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

function _genTabId() { return 'tab-' + Math.random().toString(36).slice(2, 10); }

function _loadTabs() {
  try { return JSON.parse(localStorage.getItem(TABS_KEY) || '[]'); } catch { return []; }
}
function _saveTabs() {
  localStorage.setItem(TABS_KEY, JSON.stringify(_tabs.map(t => ({ id: t.id, title: t.title, createdAt: t.createdAt }))));
  localStorage.setItem(ACTIVE_TAB_KEY, _activeTabId);
}
function _saveTabHistory(tabId, hist) {
  if (!tabId) return;
  const targetHistory = Array.isArray(hist) ? hist : [];
  localStorage.setItem('tab-hist-' + tabId, JSON.stringify(targetHistory.slice(-HISTORY_MAX)));
}
function _saveActiveTabHistory() {
  if (!_activeTabId) return;
  _saveTabHistory(_activeTabId, history);
  const msgs = document.getElementById('messages');
  if (msgs) {
    localStorage.setItem('tab-scroll-' + _activeTabId, String(msgs.scrollTop));
  }
}
function _loadTabHistory(tabId) {
  try { return JSON.parse(localStorage.getItem('tab-hist-' + tabId) || '[]'); } catch { return []; }
}

function _saveTabDisplayHtml(tabId, html, trimToCount) {
  if (!tabId) return;
  const key = 'tab-disp-' + tabId;
  let store;
  try { store = JSON.parse(localStorage.getItem(key) || '[]'); } catch { store = []; }
  const safeHtml = html.replace(/<img[^>]*src="data:[^"]*"[^>]*>/gi, '<span class="img-restored-placeholder">[image]</span>');
  store.push(safeHtml);
  if (typeof trimToCount === 'number' && store.length > trimToCount) store = store.slice(-trimToCount);
  localStorage.setItem(key, JSON.stringify(store));
}

function _loadTabDisplayHtml(tabId) {
  try { return JSON.parse(localStorage.getItem('tab-disp-' + tabId) || '[]'); } catch { return []; }
}

let _tabs = [];
let _activeTabId = '';
const _inflightRequests = new Map();
const _chatTaskIds = new Map();      // tabId -> task_id for the active chat request
const _tabsWithUpdates = new Set();  // tabIds with completed responses the user hasn't seen

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
  if (!_activeTabId || !_tabs.find(t => t.id === _activeTabId)) {
    _activeTabId = _tabs[0].id;
  }
  // Load active tab's history
  history = _loadTabHistory(_activeTabId);
  _saveTabs();
  _renderTabBar();
  // Render conversation messages from restored history
  const msgs = document.getElementById('messages');
  if (history.length && msgs) {
    msgs.innerHTML = '';
    const _displayStore = _loadTabDisplayHtml(_activeTabId);
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
        bubble.innerHTML = _displayStore[_userTurnIdx] || escapeHtml(typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
        _userTurnIdx++;
      } else {
        bubble.innerHTML = escapeHtml(typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
      }
      div.appendChild(bubble);
      msgs.appendChild(div);
      if (m.role === 'assistant' && m.content) { _addMsgActionBar(div, m.content); _addSuggestedActions(div, m.content); }
    });
    _refreshRetryVisibility();
    msgs.scrollTop = msgs.scrollHeight;
  }
  // Show onboarding if not dismissed and no history
  if (history.length === 0) _showChatOrOnboarding();
}

function _deriveTitle(hist) {
  const first = hist.find(m => m.role === 'user');
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
  _showChatOrOnboarding();
  _refreshPinOrb();
  if (typeof _switchPinContext === 'function') _switchPinContext();
}

// Creates or switches to a tab with a specific stable ID (used by scheduled-job "view this chat").
// If a tab with that id already exists, switches to it. Otherwise creates a fresh one with that id.
function createTabWithId(id, title) {
  _saveActiveTabHistory();
  let tab = _tabs.find(t => t.id === id);
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
}

function switchTab(tabId) {
  if (tabId === _activeTabId) return;
  // Save current
  _saveActiveTabHistory();
  // Swap
  _activeTabId = tabId;
  history = _loadTabHistory(tabId);
  _saveTabs();
  _renderTabBar();
  // Restore messages from history
  const msgs = document.getElementById('messages');
  if (!history.length) {
    _showChatOrOnboarding();
  } else {
    // Close onboarding panel when switching to a tab with history
    closeOnboardingPanel();
    msgs.innerHTML = '';
    const _displayStore = _loadTabDisplayHtml(tabId);
    let _userTurnIdx = 0;
    history.forEach(m => {
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
        bubble.innerHTML = _displayStore[_userTurnIdx] || escapeHtml(typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
        _userTurnIdx++;
      } else {
        bubble.innerHTML = escapeHtml(typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
      }
      div.appendChild(bubble);
      msgs.appendChild(div);
      if (m.role === 'assistant' && m.content) { _addMsgActionBar(div, m.content); _addSuggestedActions(div, m.content); }
    });
    _refreshRetryVisibility();
    const savedScroll = parseInt(localStorage.getItem('tab-scroll-' + tabId) || '-1');
    msgs.scrollTop = savedScroll >= 0 ? savedScroll : msgs.scrollHeight;
  }
  const inflight = _inflightRequests.get(tabId);
  if (inflight?.msgDiv && msgs && !msgs.contains(inflight.msgDiv)) {
    inflight.msgDiv.classList.add('typing');
    msgs.appendChild(inflight.msgDiv);
    msgs.scrollTop = msgs.scrollHeight;
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

  _refreshPinOrb();
  if (typeof _switchPinContext === 'function') _switchPinContext();
}

function closeTab(tabId) {
  const tab = _tabs.find(t => t.id === tabId);
  if (!tab) return;
  const tabHist = _loadTabHistory(tabId);
  const doClose = () => {
    const inflight = _inflightRequests.get(tabId);
    if (inflight?.abortCtrl) {
      try { inflight.abortCtrl.abort(); } catch {}
    }
    const chatTaskId = _chatTaskIds.get(tabId);
    if (chatTaskId) {
      fetch(`/api/chat/${chatTaskId}/cancel`, { method: 'POST' }).catch(() => {});
      _chatTaskIds.delete(tabId);
    }
    _inflightRequests.delete(tabId);
    // Clear pin context and stored state
    fetch(`/api/context/pins?context_id=${tabId}`, { method: 'DELETE' }).catch(() => {});
    fetch(`/api/conversation/${tabId}`, { method: 'DELETE' }).catch(() => {});
    localStorage.removeItem('tab-hist-' + tabId);
    localStorage.removeItem('tab-disp-' + tabId);
    localStorage.removeItem('tab-scroll-' + tabId);

    const closedIdx = _tabs.findIndex(t => t.id === tabId);
    _tabs = _tabs.filter(t => t.id !== tabId);
    if (!_tabs.length) {
      createTab();
      return;
    }
    if (_activeTabId === tabId) {
      // Prefer left neighbour; fall back to right when closing the first tab
      const nextIdx = Math.min(closedIdx, _tabs.length - 1);
      const nextId = _tabs[nextIdx].id;
      // Clear _activeTabId so switchTab won't early-return
      _activeTabId = '';
      switchTab(nextId);
    }
    _saveTabs();
    _renderTabBar();
    _refreshPinOrb();
  };
  if (tabHist.length > 0) {
    _showConfirmModal('Close tab', `Close "${tab.title}"? Chat history will be lost.`, 'Close', doClose);
  } else {
    doClose();
  }
}

function resetTab(tabId) {
  const tab = _tabs.find(t => t.id === tabId);
  if (!tab) return;
  const doClone = async () => {
    _saveActiveTabHistory();

    // Create a new tab next to the original and clone pins into it
    const newTab = { id: _genTabId(), title: tab.title, createdAt: Date.now() };
    await fetch('/api/context/pins/clone', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from_context_id: tabId, to_context_id: newTab.id })
    }).catch(() => {});

    // Insert new tab right after the original
    const idx = _tabs.findIndex(t => t.id === tabId);
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

function _renderTabBar() {
  const bar = document.getElementById('topbar-tabs') || document.getElementById('tab-bar');
  if (!bar) return;
  bar.innerHTML = '';

  // Left scroll arrow
  const arrowL = document.createElement('button');
  arrowL.className = 'tab-scroll-arrow tab-scroll-arrow-left';
  arrowL.innerHTML = '&#x2039;';
  arrowL.title = 'Scroll left';
  bar.appendChild(arrowL);

  // Scrollable tab container
  const scroll = document.createElement('div');
  scroll.className = 'tab-scroll';

  let _tabDragSrcId = null;
  _tabs.forEach(tab => {
    const el = document.createElement('div');
    el.className = 'tab-item' + (tab.id === _activeTabId ? ' active' : '');
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
    // Double-click to rename
    el.querySelector('.tab-item-title').addEventListener('dblclick', () => {
      const titleEl = el.querySelector('.tab-item-title');
      const inp = document.createElement('input');
      inp.className = 'tab-rename-input';
      inp.value = tab.title;
      inp.style.cssText = 'width:100px;font-size:.78rem;background:var(--surface2);border:1px solid var(--accent);border-radius:3px;color:var(--text);padding:0 .2rem;outline:none;';
      titleEl.replaceWith(inp);
      inp.focus();
      inp.select();
      const finish = () => {
        tab.title = inp.value.trim() || 'New Chat';
        _saveTabs();
        _renderTabBar();
      };
      inp.addEventListener('blur', finish);
      inp.addEventListener('keydown', e => { if (e.key === 'Enter') finish(); if (e.key === 'Escape') { _renderTabBar(); } });
    });
    // ── Tab drag-reorder ──
    el.addEventListener('dragstart', (e) => {
      _tabDragSrcId = tab.id;
      el.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', tab.id);
    });
    el.addEventListener('dragend', () => {
      _tabDragSrcId = null;
      scroll.querySelectorAll('.tab-item').forEach(t => t.classList.remove('dragging', 'drag-over-left', 'drag-over-right'));
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
      const srcIdx = _tabs.findIndex(t => t.id === _tabDragSrcId);
      const dstIdx = _tabs.findIndex(t => t.id === tab.id);
      if (srcIdx < 0 || dstIdx < 0) return;
      const rect = el.getBoundingClientRect();
      const midX = rect.left + rect.width / 2;
      const insertBefore = e.clientX < midX;
      const [moved] = _tabs.splice(srcIdx, 1);
      const newIdx = _tabs.findIndex(t => t.id === tab.id);
      _tabs.splice(insertBefore ? newIdx : newIdx + 1, 0, moved);
      _saveTabs();
      _renderTabBar();
    });
    scroll.appendChild(el);
  });

  // "+" button (inside scroll area so it stays after last tab)
  const addBtn = document.createElement('button');
  addBtn.className = 'tab-add';
  addBtn.textContent = '+';
  addBtn.title = 'New tab';
  addBtn.addEventListener('click', createTab);
  scroll.appendChild(addBtn);

  bar.appendChild(scroll);

  // Right scroll arrow
  const arrowR = document.createElement('button');
  arrowR.className = 'tab-scroll-arrow tab-scroll-arrow-right';
  arrowR.innerHTML = '&#x203A;';
  arrowR.title = 'Scroll right';
  bar.appendChild(arrowR);

  // Scroll arrow visibility + click handlers
  const updateArrows = () => {
    const canLeft = scroll.scrollLeft > 1;
    const canRight = scroll.scrollLeft < scroll.scrollWidth - scroll.clientWidth - 1;
    arrowL.classList.toggle('visible', canLeft);
    arrowR.classList.toggle('visible', canRight);
  };
  arrowL.addEventListener('click', () => { scroll.scrollLeft -= 120; });
  arrowR.addEventListener('click', () => { scroll.scrollLeft += 120; });
  scroll.addEventListener('scroll', updateArrows);
  requestAnimationFrame(updateArrows);
  // Re-check on window resize
  if (!bar._resizeObserver) {
    bar._resizeObserver = new ResizeObserver(updateArrows);
    bar._resizeObserver.observe(scroll);
  }
}

/* ── Tab context menu ────────────────────────────────── */
function _showTabCtxMenu(x, y, tabId) {
  // Remove any existing
  document.querySelector('.tab-ctx-menu')?.remove();
  const menu = document.createElement('div');
  menu.className = 'tab-ctx-menu';
  menu.setAttribute('role', 'menu');

  const items = [
    { label: 'Clone tab', action: () => resetTab(tabId) },
    { label: 'Close tab', action: () => closeTab(tabId) },
    { label: 'Close other tabs', action: () => _closeOtherTabs(tabId) },
    { label: 'Close all tabs', action: () => _closeAllTabs(), cls: 'danger' },
  ];

  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'tab-ctx-item' + (item.cls ? ' ' + item.cls : '');
    row.setAttribute('role', 'menuitem');
    row.textContent = item.label;
    row.addEventListener('click', () => { menu.remove(); item.action(); });
    menu.appendChild(row);
  });

  // Position near cursor, keep on screen
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  document.body.appendChild(menu);
  const rect = menu.getBoundingClientRect();
  if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
  if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';

  // Close on click outside or Escape
  const dismiss = (e) => {
    if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('mousedown', dismiss); document.removeEventListener('keydown', escDismiss); }
  };
  const escDismiss = (e) => {
    if (e.key === 'Escape') { menu.remove(); document.removeEventListener('mousedown', dismiss); document.removeEventListener('keydown', escDismiss); }
  };
  setTimeout(() => { document.addEventListener('mousedown', dismiss); document.addEventListener('keydown', escDismiss); }, 0);
}

function _closeOtherTabs(keepTabId) {
  const toClose = _tabs.filter(t => t.id !== keepTabId);
  toClose.forEach(t => {
    fetch(`/api/context/pins?context_id=${t.id}`, { method: 'DELETE' }).catch(() => {});
    localStorage.removeItem('tab-hist-' + t.id);
    localStorage.removeItem('tab-disp-' + t.id);
  });
  _tabs = _tabs.filter(t => t.id === keepTabId);
  if (_activeTabId !== keepTabId) {
    _activeTabId = keepTabId;
    switchTab(keepTabId);
  }
  _saveTabs();
  _renderTabBar();
  _refreshPinOrb();
}

function _closeAllTabs() {
  _tabs.forEach(t => {
    fetch(`/api/context/pins?context_id=${t.id}`, { method: 'DELETE' }).catch(() => {});
    localStorage.removeItem('tab-hist-' + t.id);
    localStorage.removeItem('tab-disp-' + t.id);
  });
  _tabs = [];
  createTab();
}

function _autoTitleTab(tabId, hist = []) {
  if (!tabId) return;
  const tab = _tabs.find(t => t.id === tabId);
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

  if (_cachedPinsContextId === contextId && Array.isArray(_cachedPins) && typeof _refreshPinnedItemsCache === 'function') {
    _refreshPinnedItemsCache(_cachedPins);
  }

  const run = async () => {
    let pins = [];
    try {
      pins = await fetch(`/api/context/pins?context_id=${contextId}`).then(r => r.ok ? r.json() : []);
    } catch {
      pins = [];
    }

    if (refreshSeq !== _pinOrbRefreshSeq) return pins;

    if (typeof _refreshPinnedItemsCache === 'function') await _refreshPinnedItemsCache(pins);

    _cachedPins = Array.isArray(pins) ? pins : [];
    _cachedPinsContextId = contextId;

    if (!orb || !badge) return pins;

    const count = Array.isArray(_cachedPins) ? _cachedPins.length : 0;
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
    if (popover?._pinCleanup) { popover._pinCleanup(); } else { existing.remove(); popover?.remove(); }
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
  const onEsc = e => { if (e.key === 'Escape') cleanup(); };
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
    pins = (_cachedPinsContextId === contextId && Array.isArray(_cachedPins)) ? _cachedPins : [];
  }
  const list = popover.querySelector('.pin-popover-list');
  const countEl = popover.querySelector('.pin-popover-count');
  if (countEl) countEl.textContent = pins.length ? `${pins.length} item${pins.length !== 1 ? 's' : ''}` : '';

  if (!pins.length) {
    list.innerHTML = '<div class="pin-popover-empty"><div style="font-size:1.4rem;margin-bottom:.4rem">\uD83D\uDC0A</div>No items pinned yet<br><span style="opacity:.6;font-size:.72rem">Right-click any email, chat, or file to pin it.<br>Pinned items give Gator context for this tab.</span></div>';
    return;
  }

  try {
  const _sourceConfig = {
    email:      { icon: '\u2709\uFE0F', label: 'Email',      color: 'rgba(15,108,189,.15)' },
    teams:      { icon: '\uD83D\uDCAC', label: 'Teams',      color: 'rgba(100,181,246,.15)' },
    onedrive:   { icon: '\uD83D\uDCC2', label: 'OneDrive',   color: 'rgba(147,197,253,.15)' },
    onenote:    { icon: '\uD83D\uDCDD', label: 'OneNote',     color: 'rgba(119,25,170,.15)' },
    confluence: { icon: '\uD83D\uDCDA', label: 'Confluence',  color: 'rgba(163,230,53,.15)' },
    jira:       { icon: '\uD83C\uDFAB', label: 'Jira',       color: 'rgba(251,191,36,.15)' },
    slack:      { icon: '\uD83D\uDCAC', label: 'Slack',       color: 'rgba(224,30,90,.15)' },
    calendar:   { icon: '\uD83D\uDCC5', label: 'Calendar',    color: 'rgba(96,165,250,.18)' },
  };

  pins.forEach(p => {
    const cfg = _sourceConfig[p.source] || { icon: '\uD83D\uDCCC', label: p.source, color: 'rgba(255,255,255,.06)' };
    const meta = p.source === 'onedrive' ? (p.meta?.file_path || '')
      : p.source === 'onenote' ? `${p.meta?.notebook || ''} \u203A ${p.meta?.section || ''}`
      : p.source === 'email' ? (p.meta?.from || '')
      : p.source === 'teams' ? (p.meta?.type || 'chat')
      : p.source === 'calendar' ? _calendarPinMeta(p.meta)
      : '';
    const card = document.createElement('div');
    card.className = 'pin-card';
    card.innerHTML = `
      <div class="pin-card-icon" style="background:${cfg.color}">${cfg.icon}</div>
      <div class="pin-card-body">
        <div class="pin-card-label">${escapeHtml(p.label)}</div>
        <div class="pin-card-meta">${escapeHtml(cfg.label)}${meta ? ' \u00B7 ' + escapeHtml(meta) : ''}</div>
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
        if (p.source === 'email') {
          if (typeof openThirdPane === 'function') openThirdPane('email');
          if (typeof tpLoadDetail === 'function') tpLoadDetail(p.id);
        } else if (p.source === 'teams') {
          if (typeof openThirdPane === 'function') openThirdPane('teams');
          if (typeof tpLoadDetail === 'function') tpLoadDetail(p.id);
        } else if (p.source === 'onenote') {
          if (typeof openThirdPane === 'function') openThirdPane('onenote');
          if (typeof tpLoadDetail === 'function') tpLoadDetail(p.id);
        } else if (p.source === 'onedrive') {
          if (webUrl) {
            window.open(webUrl, '_blank', 'noopener');
          } else {
            if (typeof openThirdPane === 'function') openThirdPane('onedrive');
          }
        } else if (p.source === 'confluence' || p.source === 'jira') {
          if (webUrl) window.open(webUrl, '_blank', 'noopener');
        } else if (p.source === 'calendar') {
          if (typeof openThirdPane === 'function') openThirdPane('calendar');
        } else if (webUrl) {
          window.open(webUrl, '_blank', 'noopener');
        }
      });
      // ✦ Insert pin reference into chat input
      card.querySelector('.pin-card-ask').addEventListener('click', () => {
        const inp = document.getElementById('chat-input');
        if (inp) {
        const pinIcon = p.source === 'email' ? '\u2709\uFE0F' : p.source === 'teams' ? '\uD83D\uDCAC' : p.source === 'confluence' ? '\uD83D\uDCDA' : p.source === 'slack' ? '\uD83D\uDCAC' : p.source === 'jira' ? '\uD83C\uDFAB' : p.source === 'calendar' ? '\uD83D\uDCC5' : '\uD83D\uDCCC';
          const pinChip = document.createElement('span');
          pinChip.className = 'pin-ref-chip';
          pinChip.contentEditable = 'false';
          pinChip.dataset.pinSource = p.source;
          pinChip.dataset.pinId = p.id;
          pinChip.textContent = `${pinIcon} ${p.label}`;
          pinChip.title = `${p.source}: ${p.label}`;
          // Append chip + space, then explicitly set cursor after it
          const space = document.createTextNode('\u00A0');
          inp.appendChild(pinChip);
          inp.appendChild(space);
          inp.focus();
          const sel = window.getSelection();
          const r = document.createRange();
          r.setStartAfter(space);
          r.setEndAfter(space);
          sel.removeAllRanges();
          sel.addRange(r);
          // Scroll input to keep cursor visible
          inp.scrollTop = inp.scrollHeight;
        }
        cleanup();
      });
      // × Unpin
      card.querySelector('.pin-card-remove').addEventListener('click', async () => {
        const removeBtn = card.querySelector('.pin-card-remove');
        removeBtn.disabled = true;
        const res = await fetch(`/api/context/pin/${p.source}/${encodeURIComponent(p.id)}?context_id=${contextId}`, { method: 'DELETE' });
        const result = res.ok ? await res.json().catch(() => ({})) : {};
        if (!res.ok || !result.unpinned) {
          removeBtn.disabled = false;
          return;
        }
        _cachedPins = _cachedPins.filter(pin => !(pin.source === p.source && String(pin.id) === String(p.id)));
        _cachedPinsContextId = contextId;
        if (typeof _refreshPinnedItemsCache === 'function') _refreshPinnedItemsCache(_cachedPins);
        card.style.transition = 'opacity .2s, transform .2s';
        card.style.opacity = '0'; card.style.transform = 'scale(.95) translateX(-10px)';
        setTimeout(() => {
          card.remove();
          // Update badge locally from the already-correct _cachedPins — no network fetch needed
          const orb = document.getElementById('pin-orb');
          const badge = document.getElementById('pin-orb-badge');
          const count = Array.isArray(_cachedPins) ? _cachedPins.length : 0;
          if (badge) { badge.textContent = count; badge.classList.toggle('hidden', count === 0); }
          if (orb) { orb.classList.toggle('has-pins', count > 0); }
          if (countEl) countEl.textContent = list.children.length ? `${list.children.length} item${list.children.length !== 1 ? 's' : ''}` : '';
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
const settingsDrawer  = document.getElementById('settings-drawer');
const settingsBackdrop = document.getElementById('settings-backdrop');
const drawerClose     = document.getElementById('drawer-close');

function openDrawer() {
  settingsBackdrop.classList.remove('hidden');
  settingsDrawer.classList.remove('hidden');
  // Next frame: add is-open so CSS transition fires from the initial transform/opacity
  requestAnimationFrame(() => settingsDrawer.classList.add('is-open'));
  if (typeof _refreshUsageBar === 'function') _refreshUsageBar();
}
window._showConnectivityToast = _showConnectivityToast;
function _showConnectivityToast(message, type = 'success') {
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
    position: 'fixed', bottom: '1.2rem', left: '50%', transform: 'translateX(-50%)',
    padding: '.5rem 1.2rem', borderRadius: '8px', fontSize: '.82rem', fontWeight: '600',
    color: '#fff', zIndex: '9999', opacity: '0', transition: 'opacity .3s',
    background: tone.bg,
    boxShadow: '0 4px 12px rgba(0,0,0,.3)',
  });
  document.body.appendChild(toast);
  requestAnimationFrame(() => { toast.style.opacity = '1'; });
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function _showContextWarning(tokenCount) {
  const existing = document.getElementById('ctx-warn-banner');
  if (existing) return; // only show once per chat
  const banner = document.createElement('div');
  banner.id = 'ctx-warn-banner';
  Object.assign(banner.style, {
    background: '#7c3aed', color: '#fff', padding: '.45rem 1rem',
    borderRadius: '8px', fontSize: '.8rem', fontWeight: '600',
    margin: '.5rem 0', display: 'flex', alignItems: 'center', gap: '.5rem',
  });
  const k = Math.round(tokenCount / 1000);
  const msg = document.createElement('span');
  msg.textContent = '\u26a0\ufe0f Context at ' + k + 'K tokens — consider opening a new tab for a fresh conversation.';
  const close = document.createElement('button');
  close.textContent = '\u00d7';
  Object.assign(close.style, {
    marginLeft: 'auto', background: 'none', border: 'none', color: '#fff',
    cursor: 'pointer', fontSize: '1rem', lineHeight: '1',
  });
  close.addEventListener('click', () => banner.remove());
  banner.appendChild(msg);
  banner.appendChild(close);
  const messages = document.getElementById('messages');
  if (messages) messages.appendChild(banner);
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
    sub.textContent = opts.subtitle;
    body.appendChild(sub);
  }

  const actions = document.createElement('div');
  actions.className = 'system-card-actions';
  const btn = document.createElement('button');
  btn.className = 'system-card-btn';
  btn.textContent = 'Dismiss';
  btn.addEventListener('click', () => card.remove());
  actions.appendChild(btn);

  card.append(iconEl, body, actions);
  const messages = document.getElementById('messages');
  if (messages) { messages.appendChild(card); messages.scrollTop = messages.scrollHeight; }
  if (opts.status !== 'failed') setTimeout(() => { if (document.contains(card)) card.remove(); }, 30000);
}

function closeDrawer() {
  settingsDrawer.classList.remove('is-open');
  // Wait for transition to finish before hiding
  setTimeout(() => {
    settingsDrawer.classList.add('hidden');
    settingsBackdrop.classList.add('hidden');
  }, 200);
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
    tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tabName));
    panels.forEach(p => p.classList.toggle('hidden', p.id !== 'spanel-' + tabName));
    localStorage.setItem(STORAGE_KEY, tabName);
  }

  tabs.forEach(tab => {
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

const settingsHomeBtn = document.getElementById('settings-home-btn');
if (settingsHomeBtn) settingsHomeBtn.addEventListener('click', closeDrawer);

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && settingsDrawer && !settingsDrawer.classList.contains('hidden')) {
    closeDrawer();
  }
});

/* ── About Modal ───────────────────────────────────── */
const aboutModal    = document.getElementById('about-modal');
const aboutBackdrop = document.getElementById('about-backdrop');
const aboutClose    = document.getElementById('about-close');
const aboutTrigger  = document.getElementById('app-logo-btn');

function openAbout() {
  aboutBackdrop.classList.remove('hidden');
  aboutModal.classList.remove('hidden');
  requestAnimationFrame(() => aboutModal.classList.add('is-open'));
  const versionEl = document.getElementById('about-version');
  if (versionEl && !versionEl.textContent) {
    fetch('/health').then(r => r.json()).then(d => { versionEl.textContent = 'v' + (d.version || ''); }).catch(() => {});
  }
}
function closeAbout() {
  aboutModal.classList.remove('is-open');
  setTimeout(() => { aboutModal.classList.add('hidden'); aboutBackdrop.classList.add('hidden'); }, 200);
}
if (aboutTrigger) aboutTrigger.addEventListener('click', () => {
  // Navigate to gator chat — close third pane if open, focus chat input
  if (typeof closeThirdPane === 'function' && tpState?.type) closeThirdPane();
  // Deselect any active skill in the rail
  _setRailActive('gator');
  const chatInput = document.getElementById('chat-input');
  if (chatInput) chatInput.focus();
});
const helpTrigger = document.getElementById('help-trigger');
if (helpTrigger) helpTrigger.addEventListener('click', () => { closeDrawer(); openAbout(); });
if (aboutClose)   aboutClose.addEventListener('click', closeAbout);
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
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !aboutModal.classList.contains('hidden')) closeAbout(); });

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
const apikeyDot     = document.getElementById('apikey-dot');
const apikeySub     = document.getElementById('apikey-sub');
const apikeyInput   = document.getElementById('apikey-input');
const useridInput   = document.getElementById('userid-input');
const apikeySaveBtn = document.getElementById('apikey-save-btn');
const apikeyChangeBtn = document.getElementById('apikey-change-btn');
const apikeyMsg     = document.getElementById('apikey-msg');
const apikeyFormInline = document.getElementById('apikey-form-inline');

// Setup gate elements
const setupGate    = document.getElementById('setup-gate');
const gateSaveBtn  = document.getElementById('gate-save-btn');
const gateMsg      = document.getElementById('gate-msg');

// ── Internal state ──────────────────────────────────────
const EYE_PATH = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
const EYE_OFF_PATH = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/>';

const _LLM_BASE_URLS = {
  anthropic: 'https://api.anthropic.com',
  openai:    'https://api.openai.com',
  gateway:   '',
  'openai-compatible': '',
};

let _llmProfiles = [];
let _llmActiveId = null;
let _llmEditingId = null;

// Delegated eye toggle — covers LLM + all connector fields
(function _initEyeToggles() {
  document.addEventListener('click', e => {
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
window._llmCddPopulate = function() {}; // no-op, kept for compat

function _llmUpdateVisibility() {
  const type = document.getElementById('llm-type')?.value || 'gateway';
  const showBase   = type === 'gateway' || type === 'openai-compatible';
  const showHeader = type === 'gateway' || type === 'openai-compatible';
  const showUser   = type === 'gateway';
  const showAnthropicUrl = type === 'gateway' || type === 'openai-compatible';
  const toggleRow = (id, show) => { const el = document.getElementById(id); if (el) el.style.display = show ? '' : 'none'; };
  toggleRow('llm-si-baseurl',   showBase);
  toggleRow('llm-si-keyheader', showHeader);
  toggleRow('llm-si-userid',    showUser);
  toggleRow('llm-si-anthropicurl', showAnthropicUrl);
}

function _llmShowError(msg) {
  const el = document.getElementById('llm-form-error');
  if (el) { el.textContent = msg; el.style.display = msg ? '' : 'none'; }
}

function _llmFillForm(profile) {
  if (!profile) return;
  const typeEl = document.getElementById('llm-type');
  if (typeEl) typeEl.value = profile.type || 'gateway';
  const el = id => document.getElementById(id);
  if (el('llm-base-url'))       el('llm-base-url').value       = profile.base_url || '';
  if (el('llm-anthropic-url')) el('llm-anthropic-url').value  = profile.anthropic_url || '';
  if (el('llm-api-key'))       { el('llm-api-key').value = profile.api_key || ''; }
  if (el('llm-key-header'))    el('llm-key-header').value = profile.api_key_header || (profile.type === 'gateway' ? 'Ocp-Apim-Subscription-Key' : '');
  if (el('llm-user-id'))       el('llm-user-id').value    = profile.user_id || '';
  // Populate custom model dropdown
  _llmCddPopulate(profile.models || [], profile.active_model || '');
  _llmUpdateVisibility();
}

async function loadLlmProfiles() {
  try {
    const res = await fetch('/api/config/llm/profiles');
    if (!res.ok) return;
    const d = await res.json();
    _llmProfiles = d.profiles || [];
    _llmActiveId = d.active || d.active_id || null;
    const active = _llmProfiles.find(p => p.id === _llmActiveId) || _llmProfiles[0] || null;
    if (active) { _llmEditingId = active.id; _llmFillForm(active); }
    // setup gate
    const hasActive = !!_llmActiveId;
    if (setupGate) setupGate.classList.toggle('hidden', hasActive);
    if (apikeyDot) apikeyDot.className = 'section-status ' + (hasActive ? 'st-ok' : 'st-err');
    updateSettingsBadges();
    // stub: keep renderLlmProfileList for compat (hidden element)
    renderLlmProfileList(_llmProfiles, _llmActiveId);
    // Refresh prompt bar model list to reflect newly active profile
    if (typeof window._refreshPromptBarModels === 'function') window._refreshPromptBarModels();
  } catch { /* non-fatal */ }
}

// Stub — the list element is hidden now, but keep function to avoid ref errors
function renderLlmProfileList() {}

async function _saveLlmProfile() {
  const saveBtn = document.getElementById('llm-save-btn');
  _llmShowError('');

  const typedKey  = document.getElementById('llm-api-key')?.value.trim() || '';
  const storedKey = _llmEditingId
    ? ((_llmProfiles.find(p => p.id === _llmEditingId) || {}).api_key || '') : '';
  const resolvedKey = typedKey || storedKey;

  const payload = {
    type:           document.getElementById('llm-type')?.value || 'gateway',
    base_url:       document.getElementById('llm-base-url')?.value.trim() || '',
    anthropic_url:  document.getElementById('llm-anthropic-url')?.value.trim() || '',
    api_key:        resolvedKey,
    api_key_header: document.getElementById('llm-key-header')?.value.trim() || '',
    user_id:        document.getElementById('llm-user-id')?.value.trim() || '',
    name:           (_llmProfiles.find(p => p.id === _llmEditingId) || {}).name || 'My Profile',
  };
  if (_llmEditingId) payload.id = _llmEditingId;
  if (!payload.api_key) { _llmShowError('API key is required.'); return; }

  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving\u2026'; }
  try {
    const res = await fetch('/api/config/llm/profiles', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload),
    });
    const d = await res.json();
    if (!res.ok) { _llmShowError(Array.isArray(d.detail) ? d.detail.map(e=>e.msg).join(', ') : (d.detail||'Save failed')); return; }
    const savedId = d.id || _llmEditingId;
    _llmEditingId = savedId;
    const actRes = await fetch('/api/config/llm/profiles/'+savedId+'/activate', {method:'POST'});
    if (!actRes.ok) { const ad = await actRes.json().catch(()=>({})); _llmShowError(ad.detail||'Saved but activation failed'); return; }
    await loadLlmProfiles();
    _llmShowError('');
    if (saveBtn) { saveBtn.textContent = '\u2713 Activated'; setTimeout(()=>{ if(saveBtn) saveBtn.textContent='Save \u0026 Activate'; },2000); }
  } catch(err) {
    _llmShowError(err.message);
  } finally {
    if (saveBtn) { saveBtn.disabled = false; if (saveBtn.textContent === 'Saving\u2026') saveBtn.textContent = 'Save \u0026 Activate'; }
  }
}

// Stub legacy functions (still called from other parts of the JS)
function showLlmProfileForm() {}
function hideLlmProfileForm() {}
function editLlmProfile() {}
function activateLlmProfile(id) { return fetch('/api/config/llm/profiles/'+id+'/activate',{method:'POST'}).then(()=>loadLlmProfiles()); }
function deleteLlmProfile() {}

(function _initLlmInlineForm() {
  const saveBtn = document.getElementById('llm-save-btn');
  const typeEl  = document.getElementById('llm-type');
  const baseUrlEl = document.getElementById('llm-base-url');
  if (saveBtn) saveBtn.addEventListener('click', _saveLlmProfile);
  if (typeEl) {
    typeEl.addEventListener('change', () => {
      const preset = _LLM_BASE_URLS[typeEl.value];
      if (preset !== undefined && baseUrlEl) baseUrlEl.value = preset;
      const kh = document.getElementById('llm-key-header');
      if (kh && !kh.value && typeEl.value === 'gateway') kh.value = 'Ocp-Apim-Subscription-Key';
      _llmUpdateVisibility();
    });
  }
})();

// ── Replace native <select> with custom portal dropdown ──────────────────────
// Keeps the hidden <select> as the value store so all existing .value reads work.
function _replaceSelectWithDropdown(selectEl) {
  if (!selectEl || !window.buildDropdown) return;
  var opts = Array.from(selectEl.options).map(function(o) {
    return { value: o.value, label: o.text };
  });
  var drop = window.buildDropdown(opts, selectEl.value, function(val) {
    selectEl.value = val;
    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
  });
  selectEl.style.display = 'none';
  selectEl.parentNode.insertBefore(drop.el, selectEl);
  // Keep dropdown in sync when value is set programmatically (e.g. _llmFillForm)
  Object.defineProperty(selectEl, 'value', {
    get: function() { return this._val !== undefined ? this._val : this.options[this.selectedIndex]?.value || ''; },
    set: function(v) {
      this._val = v;
      drop.setValue(v);
      var idx = Array.from(this.options).findIndex(function(o) { return o.value === v; });
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
  } catch { /* non-fatal */ }
}

/* ── Persona Management ────────────────────────────────── */
const personaSelect   = document.getElementById('persona-select');
const personaSub      = document.getElementById('persona-sub');
const personaEditBtn  = document.getElementById('persona-edit-btn');
const personaNewBtn   = document.getElementById('persona-new-btn');
const personaDeleteBtn = document.getElementById('persona-delete-btn');
const personaEditor   = document.getElementById('persona-editor');
const personaNameInput = document.getElementById('persona-name-input');
const personaPromptInput = document.getElementById('persona-prompt-input');
const personaSaveBtn  = document.getElementById('persona-save-btn');
const personaCancelBtn = document.getElementById('persona-cancel-btn');
const personaMsg      = document.getElementById('persona-msg');

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

    personaSub.textContent = active && _personaCache[active]
      ? _personaCache[active].name
      : 'Not set';

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
    _showConnectivityToast(id ? 'Persona: ' + _personaCache[id].name : 'Persona cleared', 'success');
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
  const id = _personaEditing === 'new'
    ? name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
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
  _showConfirmModal('Delete Persona', `Delete persona "${name}"? This cannot be undone.`, 'Delete', async () => {
    try {
      await fetch('/api/config/persona/' + encodeURIComponent(id), { method: 'DELETE' });
      await loadPersonas();
      _closePersonaEditor();
      _showConnectivityToast('Persona deleted', 'info');
    } catch {}
  });
});

// Load on startup
loadPersonas();

// Setup gate — opens Settings to the AI Model section
gateSaveBtn.addEventListener('click', () => {
  // Open the settings drawer and scroll to the LLM profiles section
  const settingsBtn = document.querySelector('[data-drawer="settings"]') || document.getElementById('settings-btn');
  if (settingsBtn) settingsBtn.click();
  setTimeout(() => {
    const llmSection = document.getElementById('llm-profiles-section');
    if (llmSection) llmSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 200);
});

/* ── Budget & Usage Settings ─────────────────────────── */
async function _loadBudgetSettings() {
  const cfg = await fetch('/api/config').then(r => r.json()).catch(() => ({}));
  const q = id => document.getElementById(id);
  if (q('cfg-budget-task'))  q('cfg-budget-task').value  = cfg.token_budget_per_task || '';
  if (q('cfg-budget-daily')) q('cfg-budget-daily').value = cfg.token_budget_daily || '';
  if (q('cfg-cost-in'))      q('cfg-cost-in').value      = cfg.cost_input_rate  || '';
  if (q('cfg-cost-out'))     q('cfg-cost-out').value     = cfg.cost_output_rate || '';
}

function _initBudgetSettings() {
  const saveBtn  = document.getElementById('cfg-budget-save');
  const clearBtn = document.getElementById('cfg-cost-clear');
  if (!saveBtn) return;
  saveBtn.addEventListener('click', async () => {
    const q = id => document.getElementById(id);
    await fetch('/api/config', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        token_budget_per_task: parseInt(q('cfg-budget-task')?.value || '0') || 0,
        token_budget_daily:    parseInt(q('cfg-budget-daily')?.value || '0') || 0,
        cost_input_rate:       parseFloat(q('cfg-cost-in')?.value)  || null,
        cost_output_rate:      parseFloat(q('cfg-cost-out')?.value) || null,
      }),
    });
    const msg = document.getElementById('cfg-budget-msg');
    if (msg) { msg.textContent = 'Saved'; setTimeout(() => { msg.textContent = ''; }, 2000); }
  });
  clearBtn?.addEventListener('click', async () => {
    await fetch('/api/config', {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cost_input_rate: null, cost_output_rate: null}),
    });
    ['cfg-cost-in', 'cfg-cost-out'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  });
  _loadBudgetSettings();
}

_initBudgetSettings();

/* ── M365 Auth ───────────────────────────────────────── */
const authDot       = document.getElementById('auth-dot');
const authDetail    = document.getElementById('auth-detail');
const teamsDot      = document.getElementById('teams-dot');
const teamsDetail   = document.getElementById('teams-detail');
const tokenInput      = document.getElementById('token-input');
const tokenSaveBtn    = document.getElementById('token-save-btn');
const tokenCaptureBtn = document.getElementById('token-capture-btn');
const tokenMsg        = document.getElementById('token-msg');

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
      setTimeout(() => { tokenMsg.textContent = ''; }, 4000);
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
      authDetail.textContent = d.expired ? 'Expired — sign in again' : (d.reason || 'Not signed in');
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
        _clearListCache('email'); _clearListCache('email_unread');
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
  } catch {
    authDot.className = 'section-status st-dim';
    authDetail.textContent = 'Unknown';
    teamsDot.className = 'section-status st-dim';
    teamsDetail.textContent = 'Unknown';
  }
  updateSettingsBadges();
}

/* ── OAuth device flow ───────────────────────────────── */
const deviceStartBtn  = document.getElementById('device-start-btn');
const deviceMsg       = document.getElementById('device-msg');
const deviceCodeBox   = document.getElementById('device-code-box');
const deviceUrlEl     = document.getElementById('device-url');
const deviceCodeVal   = document.getElementById('device-code-value');
let _devicePollTimer  = null;

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
        setTimeout(() => { deviceMsg.textContent = ''; }, 4000);
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
    } catch { /* network hiccup, keep polling */ }
  }, 5000);
}


/* ── Slack OAuth Sign-in ─────────────────────────────── */
const slackDot        = document.getElementById('slack-dot');
const slackDetail     = document.getElementById('slack-detail');
const slackSigninBtn  = document.getElementById('slack-signin-btn');
const slackAuthMsg    = document.getElementById('slack-auth-msg');

if (slackSigninBtn) slackSigninBtn.addEventListener('click', async () => {
  slackSigninBtn.disabled = true;
  slackAuthMsg.textContent = '';
  try {
    const res = await fetch('/api/auth/slack/start');
    const d = await res.json();
    if (d.url) {
      // Open Slack OAuth in popup
      const popup = window.open(d.url, 'slack-auth', 'width=600,height=700');
      // Listen for completion message from callback page
      const handler = (ev) => {
        if (ev.data && ev.data.type === 'slack-auth-ok') {
          window.removeEventListener('message', handler);
          slackAuthMsg.textContent = 'Connected!';
          slackAuthMsg.style.color = 'var(--success)';
          checkSlackStatus();
          checkSkillConnectionStatus();
          slackSigninBtn.disabled = false;
          slackSigninBtn.textContent = 'Reconnect';
          setTimeout(() => { slackAuthMsg.textContent = ''; }, 4000);
        }
      };
      window.addEventListener('message', handler);
      // Fallback: poll for popup close
      const poll = setInterval(() => {
        if (popup && popup.closed) {
          clearInterval(poll);
          slackSigninBtn.disabled = false;
          // Check status in case auth completed
          setTimeout(() => { checkSlackStatus(); checkSkillConnectionStatus(); }, 1000);
        }
      }, 1000);
    }
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
const atlassianDot         = document.getElementById('atlassian-dot');
const atlassianDetail      = document.getElementById('atlassian-detail');
const atlassianEmailInput  = document.getElementById('atlassian-email-input');
const atlassianTokenInput  = document.getElementById('atlassian-token-input');
const atlassianJiraUrlInput       = document.getElementById('atlassian-jira-url-input');
const atlassianConfluenceUrlInput = document.getElementById('atlassian-confluence-url-input');
const atlassianSaveBtn     = document.getElementById('atlassian-save-btn');
const atlassianMsg         = document.getElementById('atlassian-msg');

// Aliases so SKILL_MAP and updateSettingsBadges keep working
const jiraDot       = atlassianDot;
const confluenceDot = atlassianDot;

async function loadAtlassianStatus() {
  try {
    const [jr, cr, cfg] = await Promise.all([
      fetch('/api/config/jira/status').then(r => r.json()),
      fetch('/api/config/confluence/status').then(r => r.json()),
      fetch('/api/config').then(r => r.json()),
    ]);
    const ok = jr.configured && cr.configured;
    atlassianDot.className = 'section-status ' + (ok ? 'st-ok' : 'st-warn');
    atlassianDetail.textContent = ok
      ? (jr.email || cr.email || 'Configured')
      : 'Not configured';
    // Pre-fill email
    const email = jr.email || cr.email || cfg.jira_email || cfg.confluence_email || '';
    if (email) atlassianEmailInput.value = email;
    // Pre-fill token from stored config (cloud token or PAT)
    const token = cfg.jira_api_token || cfg.jira_pat || cfg.confluence_pat || '';
    if (token) atlassianTokenInput.value = token;
    // Pre-fill URLs
    if (jr.base_url) atlassianJiraUrlInput.value = jr.base_url;
    if (cr.base_url) atlassianConfluenceUrlInput.value = cr.base_url;
  } catch { /* non-fatal */ }
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
      }).then(r => r.json()),
      fetch('/api/config/confluence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, base_url: confUrl, email }),
      }).then(r => r.json()),
    ]);
    if (jr.ok && cr.ok) {
      atlassianMsg.textContent = 'Saved.';
      atlassianDot.className = 'section-status st-ok';
      atlassianDetail.textContent = email;
      setTimeout(() => { atlassianMsg.textContent = ''; }, 3000);
    } else {
      atlassianMsg.textContent = (jr.error || cr.error || 'Save failed.');
    }
  } catch (err) {
    atlassianMsg.textContent = 'Error: ' + err.message;
  }
});

/* ── GitHub ────────────────────────────────────────────── */
const githubDot        = document.getElementById('github-dot');
const githubDetail     = document.getElementById('github-detail');
const githubUrlInput   = document.getElementById('github-url-input');
const githubTokenInput = document.getElementById('github-token-input');
const githubSaveBtn    = document.getElementById('github-save-btn');
const githubMsg        = document.getElementById('github-msg');

if (githubSaveBtn) githubSaveBtn.addEventListener('click', () => saveGithub());

async function saveGithub() {
  const url   = githubUrlInput.value.trim().replace(/\/$/, '');
  const token = githubTokenInput.value.trim();
  if (!url)   { githubMsg.textContent = 'GitHub URL is required';  githubMsg.style.color = 'var(--danger)'; return; }
  if (!token) { githubMsg.textContent = 'Access token is required'; githubMsg.style.color = 'var(--danger)'; return; }
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
      checkGithubStatus();
      checkSkillConnectionStatus();
      setTimeout(() => { githubMsg.textContent = ''; }, 5000);
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
const usernameInput   = document.getElementById('username-input');
const usernameSaveBtn = document.getElementById('username-save-btn');
const usernameMsg     = document.getElementById('username-msg');
const usernameDot     = document.getElementById('username-dot');
const usernameSub     = document.getElementById('username-sub');

if (usernameSaveBtn) usernameSaveBtn.addEventListener('click', () => saveUsername());
if (usernameInput) usernameInput.addEventListener('keydown', e => { if (e.key === 'Enter') usernameSaveBtn.click(); });

async function saveUsername() {
  const name = usernameInput.value.trim();
  if (!name) { usernameMsg.textContent = 'Username is required'; usernameMsg.style.color = 'var(--danger)'; return; }
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
      setTimeout(() => { usernameMsg.textContent = ''; }, 5000);
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
const capInline      = document.getElementById('cap-inline');
const capInlineSteps = document.getElementById('cap-inline-steps');
const tokenControls  = document.getElementById('token-controls');

function _capStart() {
  capInlineSteps.innerHTML = '';
  capInline.querySelectorAll('.cap-inline-result').forEach(el => el.remove());
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
  capInlineSteps.querySelectorAll('.cap-inline-step').forEach(el => el.classList.add('done'));
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
  all.forEach((el, i) => { if (i < all.length - 1) el.classList.add('done'); });
}

let _captureES = null; // hoisted so capture survives drawer close

tokenCaptureBtn.addEventListener('click', () => {
  tokenCaptureBtn.disabled = true;
  tokenSaveBtn.disabled = true;
  tokenMsg.textContent = '';
  _capStart();
  _capAddStep('Opening Outlook in Edge…');

  if (_captureES) { _captureES.close(); _captureES = null; }
  const es = new EventSource('/api/auth/teams/capture/stream');
  _captureES = es;

  es.addEventListener('status', e => {
    _capAddStep(JSON.parse(e.data));
  });

  es.addEventListener('result', e => {
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

  es.addEventListener('error', e => {
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
  const authOk   = authDot.classList.contains('st-ok');
  const authWarn = authDot.classList.contains('st-warn');
  const hasErr  = !apikeyOk || (!authOk && !authWarn);
  const hasWarn = !hasErr && authWarn;
  if (hasErr)       badges.innerHTML = '<div class="badge-dot badge-err"></div>';
  else if (hasWarn) badges.innerHTML = '<div class="badge-dot badge-warn"></div>';
  else              badges.innerHTML = '';
}

/* ── Server Control ──────────────────────────────────── */
const serverDot   = document.getElementById('server-dot');
const serverLabel = document.getElementById('server-label');
const restartBtn  = document.getElementById('restart-btn');
const stopBtn     = document.getElementById('stop-btn');
const startBtn    = document.getElementById('start-btn');
const reconnectOverlay = document.getElementById('reconnect-overlay');
const reconnectMsg     = document.getElementById('reconnect-msg');
const reconnectSub     = document.getElementById('reconnect-sub');

const WATCHDOG = 'http://localhost:8001';

function setServerRunning(running) {
  serverDot.className   = 'section-status ' + (running ? 'st-ok' : 'st-err');
  serverLabel.textContent = running ? 'Running' : 'Stopped';
  restartBtn.disabled = !running;
  stopBtn.disabled    = !running;
  startBtn.classList.toggle('hidden', running);
}

async function watchdogCmd(cmd) {
  try {
    const res = await fetch(`${WATCHDOG}/${cmd}`, { method: 'POST' });
    return await res.json();
  } catch { return { ok: false }; }
}

async function waitForServer() {
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 1000));
    reconnectSub.textContent = `Reconnecting${'.'.repeat((i % 3) + 1)}`;
    try {
      const res = await fetch('/health', { signal: AbortSignal.timeout(2000) });
      if (res.ok) { window.location.reload(); return; }
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
    if (d.running) { setServerRunning(true); return; }
  } catch {}

  // No watchdog or watchdog says stopped — but if we can load this page, the server IS running
  serverDot.className = 'section-status st-ok';
  serverLabel.textContent = 'Running';
  restartBtn.disabled = true;
  stopBtn.disabled = true;
}

restartBtn.addEventListener('click', () => {
  _showConfirmModal('Restart Server', 'The page will reload automatically once the server is back up.', 'Restart', async () => {
    reconnectMsg.textContent = 'Restarting server…';
    reconnectSub.textContent = 'Please wait';
    reconnectOverlay.classList.remove('hidden');
    closeDrawer();
    await watchdogCmd('restart');
    await new Promise(r => setTimeout(r, 2000));
    await waitForServer();
  });
});

stopBtn.addEventListener('click', () => {
  _showConfirmModal('Stop Server', 'The server will stop running. You can restart it from this panel.', 'Stop', async () => {
    await watchdogCmd('stop');
    reconnectMsg.textContent = 'Server stopped';
    reconnectSub.textContent = 'Click Start to bring it back up';
    reconnectOverlay.classList.remove('hidden');
    closeDrawer();
    setServerRunning(false);
  });
});

startBtn.addEventListener('click', async () => {
  startBtn.disabled = true;
  reconnectMsg.textContent = 'Starting server…';
  reconnectSub.textContent = 'Connecting';
  startBtn.classList.add('hidden');
  await watchdogCmd('start');
  await new Promise(r => setTimeout(r, 2000));
  await waitForServer();
});

/* ── Status (pip + wordmark) ─────────────────────────── */
const _appNameEl = document.querySelector('.app-name');
const _logoPip   = document.getElementById('logo-pip');

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
const form     = document.getElementById('chat-form');
const input    = document.getElementById('chat-input');
const sendBtn  = document.getElementById('send-btn');

let history = [];
_initTabSystem();

// Delegated handler: open local file paths in default OS app
messages.addEventListener('click', e => {
  const btn = e.target.closest('.file-path-btn');
  if (!btn) return;
  const path = btn.dataset.path;
  if (!path) return;
  fetch('/api/open-file', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path })
  }).then(r => r.json()).then(d => {
    if (!d.ok) console.warn('[open-file] failed:', d.message);
  }).catch(err => console.warn('[open-file] error:', err));
});

/* ── Contenteditable helpers ─────────────────────────── */
function _isTriggerBoundary(ch) {
  return ch === undefined || ch === ' ' || ch === '\u00A0' || ch === '\n';
}

function _getNodeInputText(node) {
  let text = '';
  node.childNodes.forEach(child => {
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
      const label = child.dataset.personName || child.dataset.skillId || '';
      const prefix = child.dataset.triggerPrefix || '@';
      text += label ? `${prefix}${label}` : ' ';
    } else if (child.dataset?.filePath) {
      // File picker chips — include full path
      text += `[File: ${child.dataset.filePath}]`;
    } else if (child.classList?.contains('pin-ref-chip')) {
      // Pin reference chips — include source and label
      const label = child.textContent?.trim() || '';
      text += label ? `[${label}]` : ' ';
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
    .replace(/\b\w/g, c => c.toUpperCase());
}

function _calendarPinMeta(meta = {}) {
  if (!meta) return '';
  const start = meta.start ? new Date(meta.start) : null;
  const startText = start && !Number.isNaN(start.valueOf())
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
  node.childNodes.forEach(child => {
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

function _selectionTouches(el) {
  const sel = window.getSelection();
  if (!sel.rangeCount || !el) return false;
  const range = sel.getRangeAt(0);
  return el.contains(range.commonAncestorContainer)
    || el.contains(sel.anchorNode)
    || el.contains(sel.focusNode);
}

function _shareablePromptContextPrefix(selectedText) {
  if (!_selectionTouches(input)) return '';
  const selected = selectedText.trim();
  const fullInput = _serializeShareableNodeText(input).replace(/\n$/, '').trim();
  if (fullInput && selected !== fullInput) return '';
  const chips = _serializeShareableNodeText(document.getElementById('chat-chip-row')).trim();
  return chips;
}

function _writeShareableCopy(e, text) {
  const normalized = String(text || '').replace(/\s+\n/g, '\n').replace(/\n\s+/g, '\n').replace(/[ \t]{2,}/g, ' ').trim();
  if (!normalized) return false;
  e.preventDefault();
  e.clipboardData?.setData('text/plain', normalized);
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
  const skill = (type === 'chip-skill' && data?.skillId) ? SKILL_MAP[data.skillId] : null;
  const skillClass = skill?.chipClass || '';
  chip.className = 'inline-chip ' + type + (skillClass ? ' ' + skillClass : '');
  Object.entries(data || {}).forEach(([k, v]) => chip.dataset[k] = v);
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
  const triggerRegex = trigger === '@' ? /^@\w*/ : trigger === '#' ? /^#[\w-]*/ : trigger === '/' ? /^\/[\w-]*/ : /^\{[^}\n]*/;
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

// Paste: strip HTML, insert plain text only
input.addEventListener('paste', (e) => {
  e.preventDefault();
  const text = e.clipboardData.getData('text/plain');
  document.execCommand('insertText', false, text);
});

input.addEventListener('copy', (e) => {
  const selectedText = _serializeShareableSelection();
  const prefix = _shareablePromptContextPrefix(selectedText);
  _writeShareableCopy(e, [prefix, selectedText].filter(Boolean).join(' '));
});

form.addEventListener('copy', (e) => {
  if (e.defaultPrevented) return;
  const sel = window.getSelection();
  if (!sel.rangeCount) return;
  const selectedEl = _closestElement(sel.getRangeAt(0).commonAncestorContainer);
  if (!selectedEl?.closest?.('#chat-form')) return;
  _writeShareableCopy(e, _serializeShareableSelection());
});

// Enter = submit (Shift+Enter = newline)
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    // Don't submit if a dropdown is open (Enter selects from dropdown)
    if (document.querySelector('.skill-mention-dropdown') || document.querySelector('.channel-dropdown') || document.querySelector('.slash-dropdown')) return;
    e.preventDefault();
    document.getElementById('chat-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
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
  document.querySelectorAll('.chat-chip.chip-selected').forEach(c => c.classList.remove('chip-selected'));
});

input.addEventListener('input', () => {
  document.querySelectorAll('.chat-chip.chip-selected').forEach(c => c.classList.remove('chip-selected'));
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
  const atIdx   = val.lastIndexOf('@');
  const hashIsLast = hashIdx > atIdx; // # appears after any @ in the text
  if (hashIdx !== -1 && hashIsLast) {
    const beforeHash = val[hashIdx - 1];
    if (_isTriggerBoundary(beforeHash)) {
      const afterHash = val.slice(hashIdx + 1);
      const query = (afterHash.match(/^[\w-]*/) || [''])[0];
      const alreadyCommitted = _activeChannels.some(c =>
        afterHash.toLowerCase().startsWith(c.channel_name.toLowerCase())
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

input.addEventListener('keydown', e => {
  // Prevent browser default Enter behavior (implicit form submission)
  // We handle Enter explicitly in each dropdown handler and the final fallthrough
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
  }
  // Mention dropdown navigation (handles both @ people and / skills)
  if (_mentionDropdown) {
    const items = Array.from(_mentionDropdown.querySelectorAll('.skill-mention-item, .skill-mention-action-row'))
      .filter(el => !el.closest('.skill-mention-actions-group.hidden'));
    if (e.key === 'ArrowDown') { e.preventDefault(); _mentionFocusIdx = (_mentionFocusIdx + 1) % items.length; }
    else if (e.key === 'ArrowUp') { e.preventDefault(); _mentionFocusIdx = (_mentionFocusIdx - 1 + items.length) % items.length; }
    else if (e.key === 'ArrowRight') {
      const idx = _mentionFocusIdx >= 0 ? _mentionFocusIdx : 0;
      const focused = items[idx];
      if (focused?.dataset.type === 'slash-skill') {
        e.preventDefault();
        const chevron = focused.querySelector('.skill-mention-chevron-btn');
        if (chevron) chevron.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        // Focus moves to first action row — recalculate after DOM update
        requestAnimationFrame(() => { _mentionFocusIdx = idx + 1; });
      }
      return;
    }
    else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      _mentionDropdown.querySelectorAll('.skill-mention-actions-group').forEach(g => g.classList.add('hidden'));
      _mentionDropdown.querySelectorAll('.skill-mention-chevron-btn').forEach(b => b.classList.remove('open'));
      // Recalculate — _mentionFocusIdx stays on the skill row it was on
      return;
    }
    else if (e.key === 'Enter' || e.key === 'Tab') {
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
      } else {
        const skill = SKILL_MAP[focused.dataset.skillId];
        if (skill) _commitSkillChipOnly(skill, '@');
      }
      return;
    } else if (e.key === 'Escape') { closeMentionDropdown(); return; }
    items.forEach((item, i) => {
      item.classList.toggle('focused', i === _mentionFocusIdx);
      if (i === _mentionFocusIdx) item.scrollIntoView({ block: 'nearest' });
    });
    return;
  }
  // Channel dropdown navigation
  if (_channelDropdown) {
    const items = _channelDropdown.querySelectorAll('.skill-mention-item');
    if (e.key === 'ArrowDown') { e.preventDefault(); _channelFocusIdx = Math.min(_channelFocusIdx + 1, items.length - 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); _channelFocusIdx = Math.max(_channelFocusIdx - 1, 0); }
    else if ((e.key === 'Enter' || e.key === 'Tab') && _channelFocusIdx >= 0) {
      e.preventDefault();
      const focused = items[_channelFocusIdx];
      commitChannelMention({
        channel_id: focused.dataset.channelId,
        channel_name: focused.querySelector('.skill-mention-name').textContent,
        team_name: focused.querySelector('.skill-mention-badge').textContent,
        team_id: focused.dataset.teamId || '',
      });
      return;
    } else if (e.key === 'Escape') { closeChannelDropdown(); return; }
    items.forEach((item, i) => {
      item.classList.toggle('focused', i === _channelFocusIdx);
      if (i === _channelFocusIdx) item.scrollIntoView({ block: 'nearest' });
    });
    return;
  }
  // Pin dropdown navigation
  if (_pinDropdown) {
    const items = _pinDropdown.querySelectorAll('.skill-mention-item');
    if (e.key === 'ArrowDown') { e.preventDefault(); _pinFocusIdx = Math.min(_pinFocusIdx + 1, items.length - 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); _pinFocusIdx = Math.max(_pinFocusIdx - 1, 0); }
    else if ((e.key === 'Enter' || e.key === 'Tab') && _pinFocusIdx >= 0) {
      e.preventDefault();
      const pins = _pinDropdown._pins || [];
      if (pins[_pinFocusIdx]) commitPinMention(pins[_pinFocusIdx]);
      return;
    } else if (e.key === 'Escape') { closePinDropdown(); return; }
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
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
});

// Dedup set for pane signals — prevents double-fire when signal arrives on both
// the chat SSE stream and the notification SSE stream in the same request cycle
const _paneSignalSeen = new Set();

// Shared pane signal dispatcher — used by chat stream, notification stream, and agents-pane replay
function _handlePaneSignal(pane, paneData) {
  // Build a fingerprint from pane + stable identifying fields
  const _fp = pane + '|' + (paneData.draft_id || paneData.chat_id || paneData.to || paneData.subject || JSON.stringify(paneData).slice(0, 80));
  if (_paneSignalSeen.has(_fp)) { console.log('[pane-signal] deduped:', pane); return; }
  _paneSignalSeen.add(_fp);
  setTimeout(() => _paneSignalSeen.delete(_fp), 3000);

  console.log('[pane-signal] dispatching:', pane);

  // Each branch is wrapped in try/catch so a failure in one pane type doesn't
  // silently kill the handler (the outer EventSource catch {} was swallowing these).
  try {
    if (pane === 'teams-compose') {
      if (typeof openThirdPane === 'function') openThirdPane('teams');
      if (typeof _teamsReceiveComposeData === 'function') _teamsReceiveComposeData(paneData);
      _injectComposeCard('teams', paneData);
    } else if (pane === 'email-compose') {
      if (typeof openThirdPane === 'function') openThirdPane('email');
      if (typeof _emailReceiveComposeData === 'function') _emailReceiveComposeData(paneData);
      _injectComposeCard('email', paneData);
    } else if (pane === 'slack-compose') {
      if (typeof openThirdPane === 'function') openThirdPane('slack');
      if (typeof _slackReceiveComposeData === 'function') _slackReceiveComposeData(paneData);
      _injectComposeCard('slack', paneData);
    } else if (pane === 'jira-create') {
      if (typeof openThirdPane === 'function') openThirdPane('jira');
      if (typeof _jiraReceivePaneData === 'function') _jiraReceivePaneData(paneData);
      _injectComposeCard('jira', paneData);
    } else if (pane === 'jira-update-fields') {
      if (typeof _jiraUpdateFormFields === 'function') _jiraUpdateFormFields(paneData);
    } else if (pane === 'jira-list') {
      if (typeof _jiraUpdateIssueList === 'function') _jiraUpdateIssueList(paneData);
    } else if (pane === 'confluence-create' || pane === 'confluence-edit') {
      if (typeof openThirdPane === 'function') openThirdPane('confluence');
      const cfAction = pane === 'confluence-create' ? 'create' : 'edit';
      if (typeof _confluenceReceivePaneData === 'function') _confluenceReceivePaneData(cfAction, paneData);
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
  const step1 = isJira ? `Form pre-filled in the ${paneLabel} pane` : `Draft loaded in the ${paneLabel} pane`;
  const step2 = isJira
    ? `Review, fill any remaining fields, and hit <strong>${actionLabel}</strong> when ready`
    : `Review, edit, and hit <strong>${actionLabel}</strong> when ready`;

  const recipientHint = (!isJira && data.to) ? data.to.split(',')[0].split('@')[0] : '';
  const subjectHint = (!isJira && data.subject) ? ` &mdash; "${escapeHtml(data.subject)}"` : '';
  const projectHint = (isJira && data.project) ? `Project: <strong>${escapeHtml(data.project)}</strong>` : '';
  const summaryHint = (isJira && data.summary) ? ` &mdash; "${escapeHtml(data.summary)}"` : '';

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
            <div class="gcc-step"><span class="gcc-check">✓</span> ${step1}</div>
            <div class="gcc-step"><span class="gcc-arrow">→</span> ${step2}</div>
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
    'email-reply':    { paneLabel: '@outlook', paneIcon: '\u2709\uFE0F', service: 'email', action: 'Reply' + (data.action === 'replyAll' ? ' All' : '') },
    'email-forward':  { paneLabel: '@outlook', paneIcon: '\u2709\uFE0F', service: 'email', action: 'Forward' },
    'slack-post':     { paneLabel: '@slack',   paneIcon: '\uD83D\uDCAC', service: 'slack', action: 'Post to #' + (data.channel || '') },
    'slack-dm':       { paneLabel: '@slack',   paneIcon: '\uD83D\uDC8C', service: 'slack', action: 'DM to ' + (data.recipient || '') },
    'slack-announce': { paneLabel: '@slack',   paneIcon: '\uD83D\uDCE3', service: 'slack', action: 'Announce to ' + (data.channels || '') },
    'slack-schedule': { paneLabel: '@slack',   paneIcon: '\u23F0',       service: 'slack', action: 'Schedule to #' + (data.channel || '') },
  }[type] || { paneLabel: '@unknown', paneIcon: '\uD83D\uDCE4', service: '', action: 'Send' };

  const bodySnippet = escapeHtml((data.body_snippet || data.message_snippet || data.body || data.message || '').slice(0, 200));
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
          ${bodySnippet ? `<div class="gcc-preview">${bodySnippet}${bodySnippet.length >= 200 ? '&hellip;' : ''}</div>` : ''}
        </div>
        <div class="gcc-actions">
          <button class="gcc-approve-btn" data-draft-id="${draftId}">I approve to send</button>
          <a class="gcc-edit-link" href="#">Edit in ${config.paneLabel}</a>
        </div>
        <div class="gcc-footer">
          <span class="gcc-refine">Want changes? Just tell me here &mdash; we'll go back and forth until it's perfect.</span>
          <span class="gcc-tagline">The Gator drafts. You pull the trigger.</span>
        </div>
      </div>
    </div>`;

  const approveBtn = card.querySelector('.gcc-approve-btn');
  const editLink = card.querySelector('.gcc-edit-link');

  approveBtn.addEventListener('click', async () => {
    if (approveBtn.dataset.editMode === 'true') return; // blocked — user is editing in pane
    approveBtn.disabled = true;
    approveBtn.textContent = 'Sending\u2026';
    try {
      const res = await fetch('/api/drafts/' + draftId + '/approve', { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'HTTP ' + res.status);
      }
      approveBtn.textContent = 'Sent \u2713';
      approveBtn.classList.add('gcc-approved');
      editLink.style.display = 'none';
      // Close the third-pane compose if it's still open (avoid confusion)
      if (typeof closeThirdPane === 'function') closeThirdPane();
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
  div.querySelectorAll('img').forEach(img => {
    if (img.classList.contains('skill-icon-img')) return; // skip UI icons
    img.style.cursor = 'zoom-in';
    img.addEventListener('click', () => { if (window._tpLightboxOpen) window._tpLightboxOpen(img.src); });
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
  _writeShareableCopy(e, _serializeShareableSelection());
});

function escapeHtml(t) {
  return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Ensure GATOR_JIRA_URL is always a string even before the async config fetch resolves
window.GATOR_JIRA_URL = '';

// Close any open share dropdowns when clicking outside them
document.addEventListener('click', () => {
  document.querySelectorAll('.ofc-share-menu').forEach(m => { m.style.display = 'none'; });
});

// Inline markdown (runs on already-escaped text)
function applyInline(html) {
  // Phase 1: stash inline code spans so no other regex touches their content
  const codeStash = [];
  html = html.replace(/`([^`]+)`/g, (_, inner) => {
    codeStash.push(inner);
    return `\x00C${codeStash.length - 1}\x00`;
  });

  // Markdown links first — so the URL inside [text](url) is consumed before
  // the bare-URL pass runs (prevents double-wrapping)
  html = html.replace(
    /\[(.*?)\]\((https?:\/\/[^\)"]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>'
  );
  // Bare https:// URLs not already inside an HTML attribute
  html = html.replace(
    /(?<![="'>])(https?:\/\/[^\s<>"')\]]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  // Jira keys (e.g. PROJ-123) — only when base URL is known
  if (window.GATOR_JIRA_URL) {
    const _jiraBase = window.GATOR_JIRA_URL.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    html = html.replace(
      /\b([A-Z][A-Z0-9]+-\d+)\b/g,
      `<a href="${_jiraBase}/browse/$1" target="_blank" rel="noopener noreferrer">$1</a>`
    );
  }
  // Windows absolute file paths
  html = html.replace(
    /([A-Za-z]:\\(?:[^<>\s"'`\x00]+\\)*[^<>\s"'`\x00]+)/g,
    (_, rawPath) => {
      const path = rawPath.replace(/[.,;:!?]+$/, '');
      const attrSafe = path.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
      return `<button class="file-path-btn" data-path="${attrSafe}">&#128196; ${path}</button>`;
    }
  );

  // Phase 2: restore stashed code spans — file paths become buttons, everything else stays <code>
  const _winPath = /^[A-Za-z]:\\(?:[^<>\s"'`\x00]+\\)*[^<>\s"'`\x00]+$/;
  html = html.replace(/\x00C(\d+)\x00/g, (_, i) => {
    const inner = codeStash[+i];
    const trimmed = inner.replace(/[.,;:!?]+$/, '');
    if (_winPath.test(trimmed)) {
      const attrSafe = trimmed.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
      return `<button class="file-path-btn" data-path="${attrSafe}">&#128196; ${trimmed}</button>`;
    }
    return `<code>${inner}</code>`;
  });

  return html
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>');
}

function renderMarkdown(raw) {
  // Extract fenced code blocks before escaping
  const blocks = [];
  let s = raw.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = blocks.length;
    blocks.push(`<pre><code>${escapeHtml(code.trim())}</code></pre>`);
    return `\x00B${idx}\x00`;
  });

  // Split on blank lines → paragraph groups
  const groups = s.split(/\n{2,}/);
  const out = groups.map(group => {
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
      if (l.startsWith('### ')) return `<h3>${applyInline(escapeHtml(l.slice(4)))}</h3>`;
      if (l.startsWith('## '))  return `<h2>${applyInline(escapeHtml(l.slice(3)))}</h2>`;
      if (l.startsWith('# '))   return `<h1>${applyInline(escapeHtml(l.slice(2)))}</h1>`;
      if (/^---+$/.test(l.trim())) return '<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:.5rem 0">';
    }

    // Unordered list — also handle mixed groups where a lead-in line precedes bullets
    const bulletLines2 = lines.filter(l => /^\s*[-*] /.test(l));
    if (bulletLines2.length > 0 && !lines.every(l => /^\s*[-*] /.test(l) || l.trim() === '')) {
      const parts = [];
      let inList = false;
      let listLines = [];
      for (const l of lines) {
        if (/^\s*[-*] /.test(l)) {
          inList = true;
          listLines.push(l);
        } else {
          if (listLines.length) {
            parts.push('<ul>' + listLines.map(ll => `<li>${applyInline(escapeHtml(ll.replace(/^\s*[-*] /, '')))}</li>`).join('') + '</ul>');
            listLines = [];
          }
          if (l.trim()) parts.push(`<p>${applyInline(escapeHtml(l))}</p>`);
        }
      }
      if (listLines.length) {
        parts.push('<ul>' + listLines.map(ll => `<li>${applyInline(escapeHtml(ll.replace(/^\s*[-*] /, '')))}</li>`).join('') + '</ul>');
      }
      return parts.join('');
    }

    // Unordered list (supports nested indentation)
    if (lines.every(l => /^\s*[-*] /.test(l) || l.trim() === '')) {
      const bulletLines = lines.filter(l => /^\s*[-*] /.test(l));
      let html = '';
      const stack = [0]; // indentation stack
      bulletLines.forEach(l => {
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
      while (stack.length > 1) { html += '</li></ul>'; stack.pop(); }
      html += '</li>';
      return `<ul>${html}</ul>`;
    }

    // Ordered list (supports nested indentation)
    if (lines.every(l => /^\s*\d+\.\s+/.test(l) || l.trim() === '')) {
      const numLines = lines.filter(l => /^\s*\d+\.\s+/.test(l));
      let html = '';
      const stack = [0];
      numLines.forEach(l => {
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
      while (stack.length > 1) { html += '</li></ol>'; stack.pop(); }
      html += '</li>';
      return `<ol>${html}</ol>`;
    }

    // Mixed list (bullets + numbered at different indent levels)
    if (lines.every(l => /^\s*[-*] /.test(l) || /^\s*\d+\.\s+/.test(l) || l.trim() === '')) {
      const listLines = lines.filter(l => /^\s*[-*] /.test(l) || /^\s*\d+\.\s+/.test(l));
      if (listLines.length) {
        let html = '';
        const stack = [0];
        listLines.forEach(l => {
          const indent = l.match(/^(\s*)/)[1].length;
          const text = applyInline(escapeHtml(l.replace(/^\s*[-*] /, '').replace(/^\s*\d+\.\s+/, '')));
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
        while (stack.length > 1) { html += '</li></ul>'; stack.pop(); }
        html += '</li>';
        return `<ul>${html}</ul>`;
      }
    }

    // Blockquote
    if (lines.every(l => l.startsWith('> '))) {
      const inner = lines.map(l => applyInline(escapeHtml(l.slice(2)))).join('<br>');
      return `<blockquote>${inner}</blockquote>`;
    }

    // Markdown table
    if (lines.length >= 2 && lines[0].includes('|') && /^\|?\s*[-:]+[-| :]*$/.test(lines[1])) {
      const parseRow = r => r.replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
      const headers = parseRow(lines[0]);
      const aligns = parseRow(lines[1]).map(c => {
        if (c.startsWith(':') && c.endsWith(':')) return 'center';
        if (c.endsWith(':')) return 'right';
        return 'left';
      });
      const headHtml = headers.map((h, i) => `<th style="text-align:${aligns[i] || 'left'}">${applyInline(escapeHtml(h))}</th>`).join('');
      const bodyRows = lines.slice(2).filter(l => l.includes('|'))
        .map(r => parseRow(r).map((c, i) => `<td style="text-align:${aligns[i] || 'left'}">${applyInline(escapeHtml(c))}</td>`).join(''));
      return `<div class="table-wrap"><table><thead><tr>${headHtml}</tr></thead><tbody>${bodyRows.map(r => `<tr>${r}</tr>`).join('')}</tbody></table></div>`;
    }

    // Mixed content with headings inside — process line by line
    if (lines.some(l => l.startsWith('#'))) {
      return lines.map(l => {
        const esc = escapeHtml(l);
        if (l.startsWith('### ')) return `<h3>${applyInline(escapeHtml(l.slice(4)))}</h3>`;
        if (l.startsWith('## '))  return `<h2>${applyInline(escapeHtml(l.slice(3)))}</h2>`;
        if (l.startsWith('# '))   return `<h1>${applyInline(escapeHtml(l.slice(2)))}</h1>`;
        return l.trim() ? `<p>${applyInline(esc)}</p>` : '';
      }).join('');
    }

    // Regular paragraph — join lines, keeping single newlines as space
    const content = lines.map(l => applyInline(escapeHtml(l))).join('<br>');
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
  copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
  copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(msgDiv.dataset.raw || '').then(() => {
      copyBtn.classList.add('copied');
      copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>';
      setTimeout(() => {
        copyBtn.classList.remove('copied');
        copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
      }, 1500);
    });
  });
  bar.appendChild(copyBtn);

  // Retry button
  const retryBtn = document.createElement('button');
  retryBtn.className = 'msg-action-btn msg-retry-btn';
  retryBtn.title = 'Retry';
  retryBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
  retryBtn.addEventListener('click', () => {
    // Find the user message that preceded this response
    const allMsgs = [...document.querySelectorAll('#messages .message')];
    const idx = allMsgs.indexOf(msgDiv);
    const prevUser = idx > 0 ? allMsgs[idx - 1] : null;
    if (prevUser && prevUser.classList.contains('user')) {
      // Remove this assistant message and the user message from history
      const userText = history.findLast(m => m.role === 'user')?.content;
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
  forkBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9"/><path d="M12 12v3"/></svg>';
  forkBtn.addEventListener('click', () => {
    // Find this message's index in DOM to determine how much history to copy
    const allMsgs = [...document.querySelectorAll('#messages .message')];
    const msgIdx = allMsgs.indexOf(msgDiv);
    // Count assistant and user messages up to this point to find history slice
    let histCount = 0;
    for (let i = 0; i <= msgIdx; i++) {
      if (allMsgs[i].classList.contains('user') || allMsgs[i].classList.contains('assistant')) histCount++;
    }
    const forkedHistory = history.slice(0, histCount);
    if (!forkedHistory.length) return;
    // Save current tab, create new one with forked history
    _saveActiveTabHistory();
    const title = 'Fork: ' + (_tabs.find(t => t.id === _activeTabId)?.title || 'Chat').slice(0, 20);
    const tab = { id: _genTabId(), title, createdAt: Date.now() };
    _tabs.push(tab);
    _activeTabId = tab.id;
    history = forkedHistory;
    _saveActiveTabHistory();
    _saveTabs();
    _renderTabBar();
    // Render forked messages
    const msgs = document.getElementById('messages');
    msgs.innerHTML = '';
    history.forEach(m => {
      const div = document.createElement('div');
      div.className = 'message ' + m.role;
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.innerHTML = m.role === 'assistant' ? renderMarkdown(m.content || '') : escapeHtml(typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
      div.appendChild(bubble);
      msgs.appendChild(div);
      if (m.role === 'assistant' && m.content) { _addMsgActionBar(div, m.content); _addSuggestedActions(div, m.content); }
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
function _addSuggestedActions(msgDiv, rawText) {
  const bubble = msgDiv.querySelector('.bubble');
  if (!bubble || msgDiv.querySelector('.suggested-actions')) return;

  // Extract quoted action phrases from patterns like:
  //   Say "push to Confluence"  |  reply with "yes"  |  type "approve"
  //   Just say "go"  |  respond "publish it"  |  "push to Confluence" to update
  const actions = [];
  const seen = new Set();

  // Pattern 1: say/reply/type/respond "..."
  const p1 = /(?:say|reply(?:\s+with)?|type|respond|tell\s+me)\s+["\u201c]([^"\u201d]+)["\u201d]/gi;
  let match;
  while ((match = p1.exec(rawText)) !== null) {
    const label = match[1].trim();
    if (label.length > 80 || label.length < 2) continue;
    const key = label.toLowerCase();
    if (!seen.has(key)) { seen.add(key); actions.push(label); }
  }

  // Pattern 2: "..." to (verb) -- e.g. "push to Confluence" to update the page
  const p2 = /["\u201c]([^"\u201d]+)["\u201d]\s+to\s+\w+/gi;
  while ((match = p2.exec(rawText)) !== null) {
    const label = match[1].trim();
    if (label.length > 80 || label.length < 2) continue;
    const key = label.toLowerCase();
    if (!seen.has(key)) { seen.add(key); actions.push(label); }
  }

  if (!actions.length) return;

  const bar = document.createElement('div');
  bar.className = 'suggested-actions';

  actions.forEach(label => {
    const btn = document.createElement('button');
    btn.className = 'suggested-action-btn';
    btn.textContent = label;
    btn.addEventListener('click', () => {
      const chatInput = document.getElementById('chat-input');
      if (chatInput) {
        chatInput.textContent = label;
        chatInput.dispatchEvent(new Event('input'));
        chatInput.focus();
        // Auto-submit
        document.getElementById('chat-form').dispatchEvent(
          new Event('submit', { bubbles: true, cancelable: true })
        );
      }
    });
    bar.appendChild(btn);
  });

  bubble.appendChild(bar);
}

/* ── AI Gator Image Upload ───────────────────────────── */
let _aigatorImages = [];  // [{name, mediaType, base64}]

function initAigatorUpload() {
  const attachBtn = document.getElementById('aigator-attach-btn');
  const fileIn    = document.getElementById('aigator-file-input');
  const inputRow  = document.getElementById('chat-input-row');
  if (!attachBtn || !fileIn) return;

  const _DOC_EXTENSIONS = new Set(['docx','doc','xlsx','xls','csv','pptx','ppt']);
  const _IMAGE_TYPES = new Set(['image/png','image/jpeg','image/webp','image/gif','application/pdf']);

  const processFiles = files => {
    const errEl = document.getElementById('aigator-drop-error');
    for (const file of files) {
      const ext = file.name.split('.').pop().toLowerCase();

      // Document files → upload to server temp, create file chip with real path
      if (_DOC_EXTENSIONS.has(ext)) {
        const formData = new FormData();
        formData.append('file', file);
        fetch('/api/file-upload-temp', { method: 'POST', body: formData })
          .then(r => r.json())
          .then(data => {
            if (data.ok && data.file_path) {
              const input = document.getElementById('chat-input');
              const fileIconSrc = {
                xlsx: '/static/icons/excel-file.png', xls: '/static/icons/excel-file.png', csv: '/static/icons/excel-file.png',
                docx: '/static/icons/word-file.png', doc: '/static/icons/word-file.png',
                pptx: '/static/icons/ppt-file.png', ppt: '/static/icons/ppt-file.png',
              }[ext];
              const chip = document.createElement('span');
              chip.className = 'pin-ref-chip file-ref-chip';
              chip.contentEditable = 'false';
              chip.dataset.filePath = data.file_path;
              chip.dataset.fileName = file.name;
              chip.title = file.name;
              if (fileIconSrc) {
                const icon = document.createElement('img');
                icon.src = fileIconSrc; icon.className = 'file-chip-icon'; icon.alt = ext;
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
              removeBtn.addEventListener('click', e => {
                e.preventDefault(); e.stopPropagation();
                chip.remove();
                input.focus();
              });
              chip.appendChild(removeBtn);
              input.appendChild(chip);
              input.appendChild(document.createTextNode('\u00A0'));
              input.focus();
              if (typeof _moveCaretToEnd === 'function') _moveCaretToEnd(input);
              const skillMap = { docx: 'docx', doc: 'docx', xlsx: 'excel', xls: 'excel', csv: 'excel', pptx: 'ppt', ppt: 'ppt' };
              if (skillMap[ext]) selectSkill(skillMap[ext]);
            }
          })
          .catch(() => _showUploadError(errEl, 'Failed to upload document'));
        continue;
      }

      // Image/PDF files → upload as base64 for Claude vision
      if (_aigatorImages.length >= 5) { _showUploadError(errEl, 'Maximum 5 files'); break; }
      if (!_IMAGE_TYPES.has(file.type)) { _showUploadError(errEl, `Unsupported file type: .${ext}`); continue; }
      if (file.size > 20 * 1024 * 1024) { _showUploadError(errEl, 'File exceeds 20MB limit'); continue; }
      const imgEntry = { name: file.name, mediaType: file.type, base64: null, savedPath: null };
      _aigatorImages.push(imgEntry);
      _renderAigatorPreviews();
      const reader = new FileReader();
      reader.onload = ev => {
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
        } catch (e) { console.warn('image-upload-temp failed', e); }
      })();
    }
  };

  // Paperclip button
  attachBtn.addEventListener('click', () => fileIn.click());
  fileIn.addEventListener('change', () => { processFiles(fileIn.files); fileIn.value = ''; });

  // Drag-and-drop on the input row
  inputRow?.addEventListener('dragover', e => { e.preventDefault(); inputRow.classList.add('drag-over'); });
  inputRow?.addEventListener('dragleave', e => { if (!inputRow.contains(e.relatedTarget)) inputRow.classList.remove('drag-over'); });
  inputRow?.addEventListener('drop', e => {
    e.preventDefault(); inputRow.classList.remove('drag-over');
    processFiles(e.dataTransfer.files);
  });

  // Drag-to-resize on chat input
  const _chatResizeHandle = document.getElementById('chat-resize-handle');
  const _chatInputEl = document.getElementById('chat-input');
  if (_chatResizeHandle && _chatInputEl) {
    let _rStartY, _rStartH;
    _chatResizeHandle.addEventListener('mousedown', e => {
      e.preventDefault();
      _rStartY = e.clientY;
      _rStartH = _chatInputEl.offsetHeight;
      const onMove = ev => {
        const h = Math.min(window.innerHeight * 0.5, Math.max(32, _rStartH - (ev.clientY - _rStartY)));
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
  document.getElementById('chat-input')?.addEventListener('paste', e => {
    const files = [...(e.clipboardData?.files || [])].filter(f => f.type.startsWith('image/') || f.type === 'application/pdf');
    if (!files.length) return;
    e.preventDefault();
    processFiles(files);
  });
}

function _showUploadError(el, msg) {
  if (!el) return;
  el.textContent = msg; el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 4000);
}

function _renderAigatorPreviews() {
  const previews  = document.getElementById('aigator-previews');
  const attachBtn = document.getElementById('aigator-attach-btn');
  if (!previews) return;
  previews.innerHTML = '';
  previews.classList.toggle('hidden', _aigatorImages.length === 0);
  attachBtn?.classList.toggle('has-files', _aigatorImages.length > 0);

  _aigatorImages.forEach((img, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'aigator-preview-item';
    const isPdf = img.mediaType === 'application/pdf';
    const dataUrl = (!isPdf && img.base64) ? `data:${img.mediaType};base64,${img.base64}` : '';
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
form.addEventListener('submit', async e => {
  e.preventDefault();
  // No auto-dismiss — onboarding panel stays open alongside chat
  // Don't submit while a dropdown is open — the user is navigating, not sending
  if (_slashDropdown || _mentionDropdown || _pinDropdown || _channelDropdown) {
    console.log('[submit] BLOCKED — dropdown open');
    return;
  }
  closeMentionDropdown();
  _closeSlashDropdown();
  let typedText = _getInputText().trim();
  console.log('[submit] typedText:', typedText?.slice(0, 80), 'inputChildren:', input.childNodes.length);
  // Collect resolved people from inline chips
  const inlinePeople = _getInlineChips()
    .filter(c => c.classList.contains('chip-person'))
    .map(c => ({ name: c.dataset.personName, email: c.dataset.personEmail }));
  if (inlinePeople.length) {
    window._resolvedPeople = inlinePeople;
  }
  // Collect pin reference chips before input is cleared
  const pinChips = [...input.querySelectorAll('.pin-ref-chip')]
    .map(c => ({ label: c.textContent?.trim() || '', source: c.dataset.pinSource || '', id: c.dataset.pinId || '' }));
  // File chips are already extracted by _getInputText() as [File: path]
  const hasFileChips = input.querySelector('[data-file-path]') !== null;
  // Collect file chip path→name mappings for display (show original name, not temp path)
  const fileChipNames = {};
  input.querySelectorAll('[data-file-path]').forEach(c => {
    const p = c.dataset.filePath;
    const n = c.dataset.fileName || p.split(/[/\\]/).pop();
    if (p) fileChipNames[p] = n;
  });
  const finalText = buildFinalMessage(typedText);
  if (!finalText && !hasFileChips) return;

  // Snapshot images before clearing UI
  const imagesSnapshot = [..._aigatorImages];
  const hasImages = imagesSnapshot.length > 0 && imagesSnapshot.every(i => i.base64);

  // Build display HTML (chips + typed text + image thumbnails)
  // Only include chips whose alias wasn't typed inline (those are replaced in-place by the regex below)
  const chipHtml = _activeChips.filter(c => {
    const s = SKILL_MAP[c.skillId];
    const alias = s?.chipAlias || c.skillId;
    return !new RegExp(`[@/]${alias}\\b`, 'i').test(typedText);
  }).map(c => {
    const s = SKILL_MAP[c.skillId];
    const label = s?.label || s?.chipAlias || c.skillId;
    return `<span class="chat-chip ${s?.chipClass || ''}" style="font-size:.7rem;pointer-events:none">${escapeHtml(label)}</span>`;
  }).join(' ');
  const imgHtml = hasImages
    ? imagesSnapshot.map(img => `<img src="data:${img.mediaType};base64,${img.base64}" style="height:40px;border-radius:4px;margin-right:4px;vertical-align:middle" alt="${escapeHtml(img.name)}">`).join('')
    : '';
  // Replace @skill aliases and #channel names inline with styled chip HTML
  // so they stay in-place instead of being stripped and re-prepended.
  let displayText = typedText;

  // Replace @skill aliases with inline chip spans
  _activeChips.forEach(c => {
    const s = SKILL_MAP[c.skillId];
    const alias = s?.chipAlias || c.skillId;
    const chipSpan = `<span class="chat-chip ${s.chipClass}" style="font-size:.7rem;pointer-events:none">/${escapeHtml(alias)}</span>`;
    displayText = displayText.replace(new RegExp(`[@/]${alias}\\b`, 'gi'), `\x00CHIP${chipSpan}\x00`);
  });
  // Replace #channel names with inline chip spans
  _activeChannels.forEach(ch => {
    const chanSpan = `<span class="chat-chip chip-teams" style="font-size:.7rem;pointer-events:none">#${escapeHtml(ch.channel_name)}</span>`;
    displayText = displayText.replace(new RegExp(`#${ch.channel_name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'gi'), `\x00CHIP${chanSpan}\x00`);
  });
  // Replace [PinLabel] text with inline pin chip spans
  pinChips.forEach(p => {
    const pinSpan = `<span class="pin-ref-chip" data-pin-source="${escapeHtml(p.source)}" data-pin-id="${escapeHtml(p.id)}" style="pointer-events:none">${escapeHtml(p.label)}</span>`;
    displayText = displayText.replace(`[${p.label}]`, `\x00CHIP${pinSpan}\x00`);
  });
  // Replace [File: temppath] with the original filename for display
  Object.entries(fileChipNames).forEach(([path, name]) => {
    displayText = displayText.replace(`[File: ${path}]`, `\x00CHIP<span class="pin-ref-chip file-ref-chip" style="pointer-events:none">\uD83D\uDCC1 ${escapeHtml(name)}</span>\x00`);
  });

  // Split on chip markers, escape text segments, preserve newlines
  const parts = displayText.split('\x00');
  const bodyHtml = parts.map(part => {
    if (part.startsWith('CHIP')) return part.slice(4); // already HTML
    return escapeHtml(part).replace(/\n/g, '<br>');
  }).join('');
  const chipPrefix = chipHtml ? chipHtml + ' ' : '';
  const displayHtml = imgHtml + chipPrefix + bodyHtml;

  // Snapshot active skills + channels before clearing (for the API payload)
  const activeSkillsSnapshot = _activeChips.map(c => c.skillId);
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
    activeSkillsSnapshot.filter(s => s !== 'gator').forEach(s => _addSkillChip(s));
  }
  // Persist #channel chips across messages; ensure teams skill is active when channels exist
  _activeChannels = activeChannelsSnapshot;
  if (activeChannelsSnapshot.length && !_activeChips.some(c => c.skillId === 'teams')) {
    _addSkillChip('teams');
  }
  activeChannelsSnapshot.forEach(ch => _addChannelChip(ch));
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
  const messagePayload = hasImages
    ? [
        ...imagesSnapshot.map(img => img.mediaType === 'application/pdf'
          ? { type: 'document', source: { type: 'base64', media_type: 'application/pdf', data: img.base64 } }
          : { type: 'image',    source: { type: 'base64', media_type: img.mediaType,       data: img.base64 } }),
        { type: 'text', text: finalText }
      ]
    : finalText;

  const requestTabId = _activeTabId || (_tabs[0]?.id) || 'default';
  const requestContextId = requestTabId || 'default';
  const requestHistory = history;

  requestHistory.push({ role: 'user', content: finalText });
  _saveTabHistory(requestTabId, requestHistory);
  // Trim display store to match surviving user turns in the history window
  const _survivingUserTurns = requestHistory.slice(-HISTORY_MAX).filter(m => m.role === 'user').length;
  _saveTabDisplayHtml(requestTabId, displayHtml, _survivingUserTurns);
  input.textContent = '';
  input.style.height = 'auto';
  delete input.dataset.userResized;

  // Switch button to stop mode
  sendBtn.disabled = false;
  sendBtn.classList.add('is-streaming');
  sendBtn.setAttribute('aria-label', 'Stop generating');
  sendBtn.type = 'button'; // prevent form submit while streaming
  setStatus('busy');

  const prose = addMessage('assistant', '');
  const msgDiv = prose.closest('.message');
  msgDiv.classList.add('typing');

  // Bouncing dots indicator — wiped when first prose.innerHTML is set
  const _typingDots = document.createElement('div');
  _typingDots.className = 'typing-dots';
  for (let i = 0; i < 3; i++) _typingDots.appendChild(document.createElement('span'));
  prose.appendChild(_typingDots);

  let full = '';
  let thinkingText = '';
  let lastThinkingAgent = null;
  const _agentThinking = { planner: '', executor: '', verifier: '' };
  const _agentDone     = { planner: false, executor: false, verifier: false };
  let _lastSeenAgent   = null;
  let _threeAgentMode  = false;
  let _totalInputTokens = 0;
  let _totalOutputTokens = 0;
  let statusLines = [];
  let toastLines = [];
  let fileChipsDiv = null;
  let _streamExhausted = false;
  let _exhaustedMessage = '';
  let _abortCtrl = new AbortController();

  // Stop button handler — close EventSource + cancel server task + cancel browser task
  let _userStopped = false;
  const _onStop = () => {
    _userStopped = true;
    if (_abortCtrl._es) { _abortCtrl._es.close(); _abortCtrl._es = null; }
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
    if (_abortCtrl._resolve) { const r = _abortCtrl._resolve; _abortCtrl._resolve = null; r(); }
  };
  sendBtn.addEventListener('click', _onStop, { once: true });

  const _resetBtn = () => {
    sendBtn.removeEventListener('click', _onStop);
    sendBtn.classList.remove('is-streaming');
    sendBtn.setAttribute('aria-label', 'Send message');
    sendBtn.type = 'submit';
    sendBtn.disabled = false;
  };

  // Shared send logic — extracted so the retry button can re-invoke it.
  // When called with overridePayload (from permission approve), skips input
  // parsing and posts the saved payload directly so post-stream work runs normally.
  const doSend = async (overridePayload) => {
    full = '';
    thinkingText = '';
    lastThinkingAgent = null;
    _agentThinking.planner = ''; _agentThinking.executor = ''; _agentThinking.verifier = '';
    _agentDone.planner = false; _agentDone.executor = false; _agentDone.verifier = false;
    _lastSeenAgent = null;
    _threeAgentMode = false;
    _totalInputTokens = 0; _totalOutputTokens = 0;
    statusLines = [];
    toastLines = [];
    msgDiv.classList.add('typing');
    setStatus('busy');
    // Re-show bouncing dots on retry
    prose.textContent = '';
    const _retryDots = document.createElement('div');
    _retryDots.className = 'typing-dots';
    for (let i = 0; i < 3; i++) _retryDots.appendChild(document.createElement('span'));
    prose.appendChild(_retryDots);

    const renderStatusHtml = () => {
      if (!statusLines.length && !toastLines.length) return '';
      const lines = [
        ...statusLines.map(text => ({ text, level: 'info' })),
        ...toastLines,
      ];
      return `<div class="status-steps">${lines.map(line => {
        const lvl = line.level || 'info';
        const cls = ['status-line'];
        if (lvl === 'warn') cls.push('status-line-warn');
        else if (lvl === 'error') cls.push('status-line-error');
        else if (lvl === 'success') cls.push('status-line-success');
        return `<div class="${cls.join(' ')}">${escapeHtml(line.text)}</div>`;
      }).join('')}</div>`;
    };
    const _renderProse = () => {
      let html = '';

      if (_threeAgentMode) {
        const META = {
          planner:  { icon: '\uD83D\uDCCB', label: 'Planning'  },
          executor: { icon: '\u2699\uFE0F',  label: 'Working'   },
          verifier: { icon: '\u2713',        label: 'Checking'  },
        };
        const anyThinking = Object.values(_agentThinking).some(t => t);
        if (anyThinking) {
          const allDone = ['planner','executor','verifier'].every(k => _agentDone[k]);
          const parentLabel = allDone ? 'Gator worked in 3 steps \u2705' : 'Gator is working...';
          let inner = '';
          for (const key of ['planner', 'executor', 'verifier']) {
            const text = _agentThinking[key];
            if (!text) continue;
            const m = META[key];
            const running = _lastSeenAgent === key && !_agentDone[key];
            const badge = _agentDone[key] ? ' \u2705 done' : running ? ' \u23F3 running...' : '';
            inner += '<details class="agent-sub-block"' + (running ? ' open' : '') + '>'
                   + '<summary>' + m.icon + ' ' + m.label + badge + '</summary>'
                   + '<div class="agent-sub-content">' + renderMarkdown(text) + '</div>'
                   + '</details>';
          }
          html += '<details class="thinking-block"><summary>' + parentLabel + '</summary>' + inner + '</details>';
        }
      } else if (thinkingText) {
        html += '<details class="thinking-block"><summary>Reasoning</summary>'
             + '<div class="thinking-content">' + renderMarkdown(thinkingText) + '</div></details>';
      }

      const statusHtml = renderStatusHtml();
      if (statusHtml) html += statusHtml;
      if (full) {
        if (statusHtml) html += '<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:.4rem 0 .7rem">';
        html += renderMarkdown(full);
      }
      return html;
    };

    // Bouncing dots show immediately; status text replaces them on first SSE event
    statusLines.push('Gator is on it...');

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
      image_names: imagesSnapshot.map(i => i.name),
      image_paths: imagesSnapshot.map(i => i.savedPath).filter(Boolean),
      active_skill: _activeSkillId || '',
      active_skills: activeSkillsSnapshot,
      active_channels: activeChannelsSnapshot,
      context_id: _activeTabId || 'default',
      model: window._currentModel || '',
    };
    try {
      // Step 1: POST to get task_id (fast, returns immediately)
      const _postBody = overridePayload ? overridePayload : {
        message: messagePayload,
        history: _sanitizeHistory(history.slice(-10)),
        has_images: hasImages,
        image_names: imagesSnapshot.map(i => i.name),
        image_paths: imagesSnapshot.map(i => i.savedPath).filter(Boolean),
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
        try { const j = await postRes.json(); detail = j.detail || j.error || ''; } catch { detail = await postRes.text().catch(() => ''); }
        const hint = detail ? `<div class="err-detail">${escapeHtml(String(detail).slice(0, 200))}</div>` : '';
        const errHtml = `<div class="err-bubble"><span class="err-icon">&#x26A0;&#xFE0F;</span><span>Something went wrong (${postRes.status}). You can retry or rephrase your message.</span>${hint}<button class="retry-btn">&#x21BA; Retry</button></div>`;
        prose.textContent = '';
        prose.insertAdjacentHTML('afterbegin', errHtml);
        prose.querySelector('.retry-btn')?.addEventListener('click', doSend);
        return;
      }

      const { task_id } = await postRes.json();
      const _tabKey = _activeTabId || 'default';
      _chatTaskIds.set(_tabKey, task_id);

      // Register msgDiv so switchTab() can re-attach it if the user switches away
      _inflightRequests.set(_tabKey, { msgDiv, task_id });

      // Step 2: Stream chunks via EventSource (auto-reconnects with Last-Event-ID)
      await new Promise((resolve, reject) => {
        const es = new EventSource(`/api/chat/stream/${task_id}`);
        _abortCtrl._es = es;
        _abortCtrl._resolve = resolve;  // let _onStop unblock this await

        es.onmessage = (e) => {
          const payload = e.data;
          if (payload === '[DONE]') { es.close(); _chatTaskIds.delete(_tabKey); _inflightRequests.delete(_tabKey); resolve(); return; }
          try {
            const msg = JSON.parse(payload);
            if ('token' in msg) {
              // Streaming token -- progressive text rendering
              full += msg.token;
              prose.innerHTML = _renderProse();
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
              prose.innerHTML = _renderProse();
            } else if (msg.browser_confirm) {
              _showBrowserConfirmCard(msgDiv, msg.browser_confirm);
            } else if (msg.browser_hitl) {
              if (msg.browser_hitl === 'active') {
                // Remove confirm card if it wasn't dismissed (edge case)
                const confirmCard = document.getElementById('browser-confirm-card');
                if (confirmCard) confirmCard.remove();
                _showBrowserHITL(msgDiv);
              } else if (msg.browser_hitl === 'done') {
                const card = document.getElementById('browser-hitl-card');
                if (card) card.remove();
                _browserHITLShown = false;
              }
            } else if (msg.status) {
              statusLines.push(msg.status);
              prose.innerHTML = _renderProse();
              // Only update tool strip when user is on the submitting tab
              if (_activeTabId === _tabKey) {
                for (const skill of SKILL_REGISTRY) {
                  if (skill.id !== 'gator' && msg.status.toLowerCase().includes(skill.id)) {
                    _updateActiveTools(skill.id, true);
                    break;
                  }
                }
              }
            } else if (msg.toast) {
              const toast = msg.toast || {};
              const levelRaw = typeof toast.level === 'string' ? toast.level.toLowerCase() : 'error';
              const mapped = levelRaw === 'warning' ? 'warn' : (['success', 'info', 'warn', 'error'].includes(levelRaw) ? levelRaw : 'error');
              const message = typeof toast.message === 'string' && toast.message.trim() ? toast.message.trim() : 'Tool reported an issue.';
              _showConnectivityToast(message, mapped);
              toastLines.push({ text: message, level: mapped });
              prose.innerHTML = _renderProse();
            } else if (msg.text) {
              // Fallback: non-streaming chunked text (backward compat)
              full += msg.text;
              prose.innerHTML = _renderProse(); // same sanitized call used everywhere else in this block
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
              msg.files.forEach(f => {
                const wrapper = document.createElement('div');
                wrapper.className = 'ofc-wrapper';

                // ── Card ──
                const card = document.createElement('div');
                card.className = 'output-file-card';

                const iconEl = document.createElement('span');
                iconEl.className = 'ofc-icon';
                iconEl.textContent = _fileIcon(f.mime_type || '');

                const nameEl = document.createElement('span');
                nameEl.className = 'ofc-name';
                nameEl.title = f.name;
                nameEl.textContent = f.name;

                const mimeLabel = f.mime_type ? f.mime_type.split('/')[1].toUpperCase() : '';
                const sizeLabel = _formatBytes(f.size_bytes);
                const metaText = [mimeLabel, sizeLabel].filter(Boolean).join(' \u00B7 ');
                const metaEl = document.createElement('span');
                metaEl.className = 'ofc-meta';
                metaEl.textContent = metaText;

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
                _shareChannels.forEach(ch => {
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
                  document.querySelectorAll('.ofc-share-menu').forEach(m => {
                    if (m !== shareMenu) m.style.display = 'none';
                  });
                  shareMenu.style.display = shareMenu.style.display === 'none' ? 'block' : 'none';
                };

                shareWrap.appendChild(shareBtn);
                shareWrap.appendChild(shareMenu);

                actionsEl.appendChild(dlBtn);
                actionsEl.appendChild(shareWrap);
                card.appendChild(iconEl);
                card.appendChild(nameEl);
                if (metaText) card.appendChild(metaEl);
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
                          pre.textContent = lines.slice(0, 20).join('\n') +
                            (lines.length > 20 ? '\n\u2026 (' + (lines.length - 20) + ' more lines)' : '');
                          loaded = true;
                        } catch (_e) { pre.textContent = 'Failed to load preview.'; }
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
              _exhaustedMessage = msg.message || 'Gator hit its step limit. Click Continue to pick up where it left off.';
            } else if (msg.context_warning) {
              _showContextWarning(msg.context_tokens || 0);
            } else if (msg.type === 'permission_required') {
              _renderPermissionCard(msgDiv, msg, prose, async () => {
                // Mark all listed deps as approved for this conversation
                msg.deps.forEach(d => _approvedSkillDeps.add(d.id));
                // Re-submit using the saved payload — call doSend fresh so post-stream
                // work (history, action bar, suggested actions) runs normally
                if (!_permissionResendPayload) return;
                const resendPayload = Object.assign({}, _permissionResendPayload, {
                  unapproved_deps: [],
                });
                _permissionResendPayload = null;
                await doSend(resendPayload);
              }, () => {
                // Deny: card already replaced with hard-stop message, nothing else to do
                _permissionResendPayload = null;
              });
            }
            if (_activeTabId === _tabKey) messages.scrollTop = messages.scrollHeight;
          } catch (e) { console.error('[chat-stream] event handler error:', e); }
        };

        es.onerror = () => {
          // EventSource reconnects automatically with Last-Event-ID — only act on permanent close
          if (es.readyState === EventSource.CLOSED) {
            _chatTaskIds.delete(_tabKey);
            _inflightRequests.delete(_tabKey);
            if (_userStopped) {
              resolve(); // user intentionally stopped — not an error
            } else {
              reject(new Error('Stream connection failed'));
            }
          }
        };
      });
      // Scrub Slack auth hallucinations — only when the model is directing the
      // user to take an auth action (go to Settings, refresh token, sign in, etc.)
      // NOT when page content merely mentions Slack or auth-related words.
      if (/slack/i.test(full) && /go to (Settings|the Settings)|refresh your (Slack )?token|sign.?in to Slack|reconnect Slack|your Slack session (has )?expired|re-authenticate (with )?Slack/i.test(full)) {
        full = 'The Slack MCP server is temporarily unreachable — this is a network issue, not a token problem. No action needed on your part. Try again in a moment.';
        const statusHtml = renderStatusHtml();
        const prefix = statusHtml ? `${statusHtml}<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:.4rem 0 .7rem">` : '';
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
        _addSuggestedActions(msgDiv, full);
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
        msgDiv.appendChild(banner);
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
      prose.innerHTML = _renderProse();
    }
    if (_threeAgentMode && !localStorage.getItem('gator-three-agent-seen')) {
      localStorage.setItem('gator-three-agent-seen', '1');
      _showConnectivityToast(
        'Gator used 3 agents (Planning, Working, Checking). Multi-agent tasks use more tokens. Set a budget in Settings.',
        'info'
      );
    }
    if (_totalInputTokens || _totalOutputTokens) {
      const total = (_totalInputTokens + _totalOutputTokens).toLocaleString();
      const footer = document.createElement('div');
      footer.className = 'msg-token-footer';
      const badgeHtml = _threeAgentMode
        ? '<span class="token-agent-badge">\uD83D\uDCCB</span>'
        + '<span class="token-agent-badge">\u2699\uFE0F</span>'
        + '<span class="token-agent-badge">\u2713</span> '
        : '';
      footer.innerHTML = badgeHtml + total + ' tokens';
      msgDiv.appendChild(footer);
    }
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
      history.push({ role: 'assistant', content: `Got it — I've loaded **${label || action}** as context. Ask me anything about it.` });
    }
  } catch (err) {
    addMessage('assistant', `<span style="color:var(--danger)">⚠ ${escapeHtml(err.message)}</span>`);
  }
  btn.classList.remove('loading');
  setStatus('ready');
}

function buildContextText(action, data) {
  if (action === 'email' && data.recent) {
    return data.recent.map(e => `• ${e.subject} | from: ${e.from} | ${e.received}`).join('\n');
  }
  if (['jira','jira-urgent','jira-custom'].includes(action) && data.issues) {
    return data.issues.map(i => `• ${i.key}: ${i.summary} [${i.status} / ${i.priority}]`).join('\n');
  }
  if (action === 'teams' && data.chats) {
    return data.chats.map(c =>
      `[${c.topic}]\n` + (c.messages || []).slice(-5).map(m => `  ${m.sender}: ${m.body}`).join('\n')
    ).join('\n\n');
  }
  if (action === 'teams-mentions' && data.mentions) {
    return data.mentions.map(m => `• [${m.topic}] ${m.sender} (${m.time}): ${m.body}`).join('\n');
  }
  if (action === 'calendar' && data.events) {
    return data.events.map(e => `• ${e.isAllDay ? 'All day' : `${e.start}–${e.end}`}: ${e.subject}${e.location ? ` @ ${e.location}` : ''}`).join('\n');
  }
  if (action === 'onedrive' && data.files) {
    return data.files.map(f => `• ${f.name} (${f.modified}, ${f.size})`).join('\n');
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
    const items = (data.recent || []).map(m =>
      `<div class="card-item email-link" data-id="${escapeHtml(m.id)}" style="cursor:pointer">
        <div class="card-item-title">${escapeHtml(m.subject)}</div>
        <div class="card-item-meta">
          <span>${escapeHtml(m.from)}</span>
          <span class="card-item-time">${m.received}</span>
        </div>
      </div>`
    ).join('');
    bubble.innerHTML = `<div class="result-card"><div class="card-header"><span class="card-header-icon">✉️</span><span class="card-header-title">Outlook Inbox</span></div>${stat}<div class="card-items">${items}</div></div>`;
    bubble.querySelectorAll('.email-link').forEach(row => {
      row.addEventListener('click', async () => {
        const readProse = addMessage('assistant', '<em style="color:var(--text-dim)">Loading email…</em>');
        const readBubble = readProse.closest('.bubble');
        readBubble.classList.add('card-bubble');
        readProse.classList.remove('prose');
        try {
          const res = await fetch('/api/actions/email/read', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: row.dataset.id }),
          });
          const email = await res.json();
          if (!res.ok) throw new Error(email.detail);
          const bodyText = (email.body || '').trim().slice(0, 1500);
          readProse.innerHTML = card('✉️', escapeHtml(email.subject), null,
            `<div class="card-item"><div class="card-item-meta"><span>From</span><span>${escapeHtml(email.from)} &lt;${escapeHtml(email.from_email)}&gt;</span></div></div>` +
            `<div class="card-item"><div class="card-item-meta"><span>To</span><span>${escapeHtml(email.to.join(', '))}</span></div></div>` +
            `<div class="card-item"><div class="card-item-meta"><span>Date</span><span>${escapeHtml(email.received)}</span></div></div>` +
            `<div class="card-item"><div class="card-item-body email-body">${escapeHtml(bodyText)}${bodyText.length >= 1500 ? '\n\n[truncated…]' : ''}</div></div>`
          );
          messages.scrollTop = messages.scrollHeight;
        } catch(err) {
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
      const items = data.issues.map(i =>
        `<div class="card-item">
          <div class="card-item-title"><a href="${i.url}" target="_blank">${escapeHtml(i.key)}</a> &nbsp;${escapeHtml(i.summary)}</div>
          <div class="card-item-meta">${chip(i.status)}&nbsp;${priorityChip(i.priority)}</div>
        </div>`
      ).join('');
      bubble.innerHTML = card(icon, title, data.issues.length, items);
    }

  } else if (action === 'teams' || action === 'teams-mentions') {
    const isTeams = action === 'teams';
    const icon = isTeams ? '💬' : '🔔';
    const title = label || (isTeams ? 'Teams — Last 24hrs' : 'Teams — Mentions');
    const list = isTeams ? data.chats : data.mentions?.map(m => ({ topic: m.topic, message_count: 1, messages: [m] }));
    if (!list?.length) {
      bubble.innerHTML = cardEmpty(icon, title, isTeams ? 'No activity in the last 24hrs.' : 'No mentions in the last 48hrs.');
    } else {
      const items = list.map(c => {
        const msgs = (c.messages || []).slice(-3).map(m =>
          `<div class="teams-msg-row">
            <span class="teams-msg-sender">${escapeHtml(m.sender.split(',')[0])}</span>
            <span class="teams-msg-time">${m.time.slice(11,16) || m.time.slice(5,10)}</span>
            <span class="teams-msg-body">${escapeHtml(m.body)}</span>
          </div>`
        ).join('');
        return `<div class="card-item">
          <div class="card-item-meta"><span style="font-weight:600;color:var(--text)">${escapeHtml(c.topic)}</span><span class="card-item-time">${c.message_count} msg${c.message_count!==1?'s':''}</span></div>
          ${msgs}
        </div>`;
      }).join('');
      bubble.innerHTML = card(icon, title, list.length, items);
    }

  } else if (action === 'calendar') {
    if (!data.events?.length) {
      bubble.innerHTML = cardEmpty('📅', "Today's Calendar", 'No events today.');
    } else {
      const items = data.events.map(e => {
        const time = e.isAllDay ? 'All day' : `${e.start} – ${e.end}`;
        return `<div class="card-item">
          <div class="card-item-title">${escapeHtml(e.subject)}</div>
          <div class="card-item-meta"><span>${escapeHtml(time)}</span>${e.location ? `<span class="sep">·</span><span>${escapeHtml(e.location)}</span>` : ''}</div>
        </div>`;
      }).join('');
      bubble.innerHTML = card('📅', "Today's Calendar", data.events.length, items);
    }

  } else if (action === 'onedrive') {
    if (!data.files?.length) {
      bubble.innerHTML = cardEmpty('📁', 'OneDrive Recent', 'No recent files.');
    } else {
      const items = data.files.map(f =>
        `<div class="card-item">
          <div class="card-item-title"><a href="${f.url}" target="_blank">${escapeHtml(f.name)}</a></div>
          <div class="card-item-meta"><span>${f.modified}</span><span class="sep">·</span><span>${escapeHtml(f.size)}</span></div>
        </div>`
      ).join('');
      bubble.innerHTML = card('📁', 'OneDrive Recent', data.files.length, items);
    }

  } else if (action === 'news') {
    bubble.innerHTML = card('📰', 'News Slide', null,
      `<div class="card-item"><div class="card-item-title">${escapeHtml(data.message || 'Slide updated successfully.')}</div></div>`
    );
  }

  messages.scrollTop = messages.scrollHeight;
}

/* ── Init ────────────────────────────────────────────── */
renderDock();
initChatResize();
initAigatorUpload();

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
  overlay.querySelector('.confirm-modal-ok').addEventListener('click', () => { close(); onConfirm(); });
  overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
  // Focus the confirm button
  overlay.querySelector('.confirm-modal-ok').focus();
}

// Alert modal — styled replacement for browser alert()
function _showAlert(msg, type) {
  type = type || 'info';
  const icon = type === 'error' ? '\u2717' : type === 'success' ? '\u2713' : '\u2139\uFE0F';
  const color = type === 'error' ? 'var(--danger)' : type === 'success' ? 'var(--success)' : 'var(--accent)';
  const existing = document.getElementById('confirm-modal-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'confirm-modal-overlay';
  overlay.className = 'confirm-modal-overlay';

  const box = document.createElement('div');
  box.className = 'confirm-modal-box';

  const body = document.createElement('div');
  body.className = 'confirm-modal-body';
  body.style.cssText = 'display:flex;gap:10px;align-items:flex-start';
  const iconSpan = document.createElement('span');
  iconSpan.style.cssText = 'font-size:1.1rem;flex-shrink:0;color:' + color;
  iconSpan.textContent = icon;
  const textSpan = document.createElement('span');
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

  var close = function() { overlay.remove(); };
  okBtn.addEventListener('click', close);
  overlay.addEventListener('click', function(e) { if (e.target === overlay) close(); });
  document.addEventListener('keydown', function esc(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); } });
  okBtn.focus();
}
window._showAlert = _showAlert;

// Pin orb click
document.getElementById('pin-orb')?.addEventListener('click', _togglePinPopover);
_refreshPinOrb();

// Click-outside closes dropdowns
document.addEventListener('click', e => {
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
fetch('/api/teams/chats').then(r => r.ok ? r.json() : null).then(data => {
  if (data?.chats?.length) window._teamsChatsCache = data.chats;
}).catch(() => {});

/* ── Global Notifications (Teams + Email) ──────────────────── */
(function() {
  // ── Notification toggle (persisted to localStorage) ──
  const _notifKey = 'gator-notif-enabled';
  let _notifEnabled = localStorage.getItem(_notifKey) === '1';
  const _notifToggle = document.getElementById('notif-toggle');
  const _notifDot = document.getElementById('notif-dot');
  const _notifSub = document.getElementById('notif-sub');

  function _syncNotifUI() {
    if (_notifToggle) _notifToggle.checked = _notifEnabled;
    if (_notifDot) _notifDot.className = 'section-status ' + (_notifEnabled ? 'st-ok' : 'st-dim');
    if (_notifSub) _notifSub.textContent = _notifEnabled ? 'On' : 'Off';
  }
  _syncNotifUI();

  if (_notifToggle) _notifToggle.addEventListener('change', () => {
    _notifEnabled = _notifToggle.checked;
    localStorage.setItem(_notifKey, _notifEnabled ? '1' : '0');
    _syncNotifUI();
    // Request browser permission on first enable
    if (_notifEnabled && 'Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  });

  // ── Browser Display toggle (persisted to server config) ──
  const _bdSub = document.getElementById('browser-display-sub');
  const _bdBtns = document.querySelectorAll('.browser-display-opt');
  let _browserDisplay = 'pane';

  function _syncBrowserDisplayUI() {
    _bdBtns.forEach(b => {
      const active = b.dataset.val === _browserDisplay;
      b.style.background = active ? 'var(--accent)' : '';
      b.style.color = active ? '#000' : '';
      b.style.fontWeight = active ? '600' : '';
    });
    if (_bdSub) _bdSub.textContent = _browserDisplay === 'pane' ? "Gator's Browser" : 'External window';
  }

  // Load current value from server config
  fetch('/api/config').then(r => r.json()).then(cfg => {
    _browserDisplay = cfg.browser_display || 'external';
    _syncBrowserDisplayUI();
  }).catch(() => {});

  _bdBtns.forEach(btn => {
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
  const _bePreferRow  = document.getElementById('browser-prefer-row');
  const _beEngineSub  = document.getElementById('browser-engine-sub');
  let _browserNative = false;
  let _browserPrefer = 'auto';
  let _browserProfile = '';

  function _syncBrowserEngineUI() {
    _beEngineOpts.forEach(b => b.classList.toggle('active', b.dataset.val === String(_browserNative)));
    _bePreferOpts.forEach(b => b.classList.toggle('active', b.dataset.val === _browserPrefer));
    const _advDetails = document.getElementById('browser-advanced-details');
    if (_advDetails) _advDetails.style.display = _browserNative ? '' : 'none';
    if (_bePreferRow) _bePreferRow.style.display = _browserNative ? 'flex' : 'none';
    const _bpProfileRow = document.getElementById('browser-profile-row');
    if (_bpProfileRow) _bpProfileRow.style.display = _browserNative ? 'flex' : 'none';
    const _bpProfileNameRow = document.getElementById('browser-profile-name-row');
    if (_bpProfileNameRow) _bpProfileNameRow.style.display = (_browserNative && _browserProfile === 'personal') ? 'flex' : 'none';
    document.querySelectorAll('.browser-profile-opt').forEach(b => b.classList.toggle('active', b.dataset.val === _browserProfile));
    if (_beEngineSub) {
      if (!_browserNative) {
        _beEngineSub.textContent = 'Playwright Chromium';
      } else {
        const engineName = _browserPrefer === 'edge' ? 'Edge' : _browserPrefer === 'chrome' ? 'Chrome' : 'Chrome / Edge';
        const profileName = _browserProfile === 'personal' ? 'your logins' : _browserProfile === 'gator' ? 'isolated' : 'choose profile';
        _beEngineSub.textContent = engineName + ' (' + profileName + ')';
      }
    }
  }

  fetch('/api/config').then(r => r.json()).then(cfg => {
    _browserNative = !!cfg.browser_native;
    _browserPrefer = cfg.browser_prefer || 'auto';
    _browserProfile = cfg.browser_profile || '';
    const _profileNameInput = document.getElementById('browser-profile-name-input');
    if (_profileNameInput) _profileNameInput.value = cfg.browser_profile_name || 'Default';
    _syncBrowserEngineUI();
  }).catch(() => {});

  _beEngineOpts.forEach(btn => {
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

  _bePreferOpts.forEach(btn => {
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

  document.querySelectorAll('.browser-profile-opt').forEach(btn => {
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
  let _lastTeamsUnread = new Map();  // chatId → {topic, sender, time}
  let _lastEmailUnread = new Set();  // messageId set
  let _notifReady = false;

  function _showNotification(title, body, icon, onClick) {
    if (!_notifEnabled) return; // Notifications disabled by user
    // In-app toast
    _showNotifToast(title, body, onClick);
    // Browser notification (if permitted)
    if ('Notification' in window && Notification.permission === 'granted') {
      try {
        const n = new Notification(title, { body, icon: icon || '/logo', tag: title, silent: false });
        if (onClick) n.addEventListener('click', () => { window.focus(); onClick(); n.close(); });
        setTimeout(() => n.close(), 8000);
      } catch {}
    }
  }

  function _showNotifToast(title, body, onClick) {
    const toast = document.createElement('div');
    Object.assign(toast.style, {
      position: 'fixed', top: '1rem', right: '1rem', zIndex: '99998',
      background: 'var(--surface, #1e293b)', border: '1px solid var(--border2, #334155)',
      borderRadius: '10px', padding: '.7rem .9rem', minWidth: '260px', maxWidth: '360px',
      boxShadow: '0 8px 32px rgba(0,0,0,.4)', cursor: 'pointer',
      display: 'flex', flexDirection: 'column', gap: '.2rem',
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
    toast.querySelector('button').addEventListener('click', e => { e.stopPropagation(); toast.remove(); });
    if (onClick) toast.addEventListener('click', () => { onClick(); toast.remove(); });
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; toast.style.transform = 'translateX(100%)'; setTimeout(() => toast.remove(), 300); }, 6000);
  }

  function _escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

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
        setTimeout(() => { window._teamsNotifBackoff = false; }, 300000);
        return;
      }
      if (!res.ok) return;
      const data = await res.json();
      const chats = data.chats || [];

      // Update badge
      const unread = chats.filter(c => (c.unread_count || 0) > 0).length;
      if (typeof updateRailBadge === 'function') updateRailBadge('teams', unread);

      if (!_notifReady) {
        // First poll — seed state, don't notify
        chats.forEach(c => { if (c.unread_count > 0) _lastTeamsUnread.set(c.id, c.last_message_time); });
        _notifReady = true;
        return;
      }

      // Detect NEW unread (wasn't unread before, or has newer message)
      chats.forEach(c => {
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
              }
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
      messages.forEach(m => {
        if (!m.is_read && !_lastEmailUnread.has(m.id)) {
          _showNotification(
            `Email: ${m.from_name || m.from_email || 'Unknown'}`,
            m.subject || '(no subject)',
            '/static/icons/outlook.svg',
            () => {
              if (typeof openThirdPane === 'function') openThirdPane('email');
              if (typeof tpLoadDetail === 'function') setTimeout(() => tpLoadDetail(m.id), 300);
            }
          );
        }
      });
      // Update known set
      _lastEmailUnread = new Set(messages.filter(m => !m.is_read).map(m => m.id));
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
          window.registerUserSkill(msg.skill_id, msg.display_name || msg.skill_id, msg.tier || 'Mine');
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
        } catch (err) { console.warn('[notify-stream] skill_auto_activated handler failed:', err); }
        return;
      }
      // Forward pane signals — backup delivery channel for compose panes
      if (msg.type === 'pane_signal' && msg.pane) {
        console.log('[notify-stream] pane signal received:', msg.pane);
        _handlePaneSignal(msg.pane, msg.paneData || {});
        return;
      }
      if (msg.type === 'draft_signal' && msg.draft) {
        console.log('[notify-stream] draft signal received:', msg.draft);
        _injectDraftApprovalCard(msg.draft, msg.draftData || {});
        return;
      }
      if (msg.type === 'max_tokens_reached') {
        const text = msg.message || 'Claude hit the output limit — reply "continue" to resume.';
        try { _showConnectivityToast(text, 'warning'); } catch (_) {}
        return;
      }
      if (msg.type === 'chat_done') {
        const currentTab = typeof _activeTabId !== 'undefined' ? _activeTabId : 'default';
        if (msg.context_id && msg.context_id !== currentTab) {
          // Mark the source tab with a visual indicator
          _tabsWithUpdates.add(msg.context_id);
          const tabEl = document.querySelector(`.tab-item[data-tab-id="${msg.context_id}"]`);
          if (tabEl) tabEl.classList.add('tab-has-update');
          // Toast in the current tab
          _showConnectivityToast('Your request in another tab is done — switch back to see the result.', 'info');
        }
        return;
      }
      if (msg.type === 'task_done') {
        _showSystemCard({
          icon: msg.status === 'done' ? '\u26A1' : '\u26A0\uFE0F',
          title: msg.job_name
            ? (msg.status === 'done' ? msg.job_name + ' completed' : msg.job_name + ' failed')
            : (msg.status === 'done' ? 'Background task complete' : 'Task failed'),
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
            fetch('/api/tasks?limit=10').then(r => r.ok ? r.json() : []).then(tasks => {
              const completed = tasks.filter(t => t.status === 'done' || t.status === 'failed').length;
              _updateAgentsBadge(completed);
            }).catch(() => {});
          }
        }
      }
    } catch {}
  };
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      es.close();
      setTimeout(_initNotificationStream, 5000);
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
    if (input) { input.value = ''; _filterLauncherApps(''); }
    setTimeout(() => input?.focus(), 100);
  }
}

function _filterLauncherApps(query) {
  const q = query.toLowerCase();
  document.querySelectorAll('.launcher-app[data-name]').forEach(app => {
    const text = (app.dataset.label || '') + ' ' + (app.dataset.name || '');
    app.classList.toggle('launcher-hidden', q && !text.includes(q));
  });
  document.querySelectorAll('.launcher-category').forEach(cat => {
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
    document.querySelectorAll('.launcher-app.launcher-focused').forEach(el => el.classList.remove('launcher-focused'));
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
      if (bd?.classList.contains('open')) { bd.classList.remove('open'); _launcherClearFocus(); }
    }
  });
}
document.addEventListener('DOMContentLoaded', _initLauncher);

function _initDock() {
  renderDock();
  document.getElementById('dock-home')?.addEventListener('click', () => {
    window.MarketplacePane?.close();
    selectSkill('gator');
  });
  document.getElementById('dock-launcher-btn')?.addEventListener('click', () => {
    window.MarketplacePane?.close();
    _toggleLauncher();
  });
  document.getElementById('dock-agents')?.addEventListener('click', () => {
    window.MarketplacePane?.close();
    if (typeof openAgentsPane === 'function') openAgentsPane();
  });
  document.getElementById('dock-settings')?.addEventListener('click', () => {
    window.MarketplacePane?.close();
    document.getElementById('settings-trigger')?.click();
  });
  document.getElementById('dock-help')?.addEventListener('click', () => {
    window.MarketplacePane?.close();
    document.getElementById('help-trigger')?.click();
  });
}
document.addEventListener('DOMContentLoaded', _initDock);

/* ── Active Tools Strip ───────────────────────────────── */
const _activeToolNames = new Set();

function _updateActiveTools(toolName, add) {
  if (add && toolName) { _activeToolNames.add(toolName); }
  else if (!add && toolName) { _activeToolNames.delete(toolName); }
  const chipRow = document.getElementById('chat-chip-row');
  if (!chipRow) return;

  // Remove existing active-tool chips
  chipRow.querySelectorAll('.active-tool-chip').forEach(el => el.remove());

  if (_activeToolNames.size === 0) return;

  const names = [..._activeToolNames];
  const visible = names.slice(0, 4);
  const overflow = names.length - visible.length;
  // Insert before the "+" add-chip button
  const addBtn = chipRow.querySelector('.chip-add') || null;

  for (const name of visible) {
    const skill = SKILL_REGISTRY.find(s => s.id === name);
    const chip = document.createElement('span');
    chip.className = 'active-tool-chip tool-chip';
    const iconFile = typeof _dockIconFile === 'function' ? _dockIconFile(name) : name;
    const img = document.createElement('img');
    const ext = (name === 'onenote' || name === 'ppt' || name === 'excel' || name === 'docx') ? 'png' : 'svg';
    img.src = '/static/icons/' + iconFile + '.' + ext;
    img.alt = name;
    chip.appendChild(img);
    chip.appendChild(document.createTextNode(' ' + (skill ? skill.label : name)));
    if (addBtn) chipRow.insertBefore(chip, addBtn);
    else chipRow.appendChild(chip);
  }
  if (overflow > 0) {
    const more = document.createElement('span');
    more.className = 'active-tool-chip tool-chip-more';
    more.textContent = '+' + overflow + ' more';
    if (addBtn) chipRow.insertBefore(more, addBtn);
    else chipRow.appendChild(more);
  }
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
        fetch('/api/browser/status').then(r => r.json()).then(s => {
          if (s.active) _openBrowserPane();
        }).catch(() => {});
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
  if (img) { img.classList.add('hidden'); img.src = ''; }
  if (placeholder) placeholder.classList.remove('hidden');
  // Reset pause button state
  const btn = document.getElementById('bp-takeover-btn');
  if (btn) { btn.textContent = 'Pause'; btn.dataset.paused = 'false'; btn.style.background = ''; btn.style.color = ''; }
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
        try { await fetch('/api/browser/resume', { method: 'POST' }); } catch {}
        takeoverBtn.textContent = 'Pause';
        takeoverBtn.dataset.paused = 'false';
        takeoverBtn.style.background = '';
        takeoverBtn.style.color = '';
        if (stepEl) stepEl.textContent = 'Resumed — agent working...';
      } else {
        try { await fetch('/api/browser/pause', { method: 'POST' }); } catch {}
        takeoverBtn.textContent = 'Resume';
        takeoverBtn.dataset.paused = 'true';
        takeoverBtn.style.background = 'var(--surface3)';
        takeoverBtn.style.color = 'var(--text)';
        if (stepEl) stepEl.textContent = _browserDisplay === 'pane'
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
  msg.deps.forEach(d => {
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
  warning.textContent = 'These tools can run any shell command or code — only approve skills you trust.';
  body.appendChild(warning);
  card.appendChild(body);

  const actions = document.createElement('div');
  actions.className = 'permission-card-actions';

  const allowBtn = document.createElement('button');
  allowBtn.className = 'permission-allow-btn';
  allowBtn.textContent = 'Allow for this conversation';
  allowBtn.addEventListener('click', () => {
    allowBtn.disabled = true;
    const depNames = msg.deps.map(d => d.label || d.id).join(', ');
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
    const depNames = msg.deps.map(d => d.label || d.id).join(', ');
    while (card.firstChild) card.removeChild(card.firstChild);
    const denied = document.createElement('div');
    denied.className = 'permission-card-denied';
    const strong = document.createElement('strong');
    strong.textContent = skillLabel;
    denied.append('❌ Permission denied — ', strong, ' requires ' + depNames + ' to function. Try a different skill.');
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
  title.style.cssText = 'font-size: 0.85rem; font-weight: 600; color: var(--text); margin-bottom: 2px;';
  title.textContent = 'Open browser?';

  const detail = document.createElement('div');
  detail.style.cssText = 'font-size: 0.78rem; color: var(--text-muted); word-break: break-word;';
  detail.textContent = action;

  textWrap.append(title, detail);

  const btnWrap = document.createElement('div');
  btnWrap.style.cssText = 'display: flex; gap: 6px; flex-shrink: 0; align-items: center;';

  const cancelBtn = document.createElement('button');
  cancelBtn.textContent = 'Cancel';
  cancelBtn.style.cssText = 'font-size: 0.75rem; padding: 4px 12px; border-radius: 6px; background: var(--surface3); color: var(--text); border: none; cursor: pointer; font-weight: 600;';

  const allowBtn = document.createElement('button');
  allowBtn.textContent = 'Allow';
  allowBtn.style.cssText = 'font-size: 0.75rem; padding: 4px 12px; border-radius: 6px; background: var(--accent); color: #000; border: none; cursor: pointer; font-weight: 600;';

  const _dismiss = () => { card.remove(); };

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

/* ── Browser HITL (in-chat controls) ────────────────── */
let _browserHITLShown = false;

function _showBrowserHITL(msgDiv) {
  if (_browserHITLShown) return; // Only show once per response
  _browserHITLShown = true;

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
  btn.style.cssText = 'font-size: 0.75rem; padding: 4px 12px; border-radius: 6px; background: var(--accent); color: #000; border: none; cursor: pointer; font-weight: 600;';

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
  let _hitlPollId = setInterval(async () => {
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
      if (!s.active) clearInterval(_hitlPollId);
    } catch (e) { /* ignore */ }
  }, 2000);
}

// Reset HITL state when a new message starts
function _resetBrowserHITL() {
  _browserHITLShown = false;
  const card = document.getElementById('browser-hitl-card');
  if (card) card.remove();
}

function _initGatorScroll() {
  const messages = document.getElementById('messages');
  if (!messages) return;
  let scrollTimer = null;
  messages.addEventListener('scroll', () => {
    messages.classList.add('is-scrolling');
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
      messages.classList.remove('is-scrolling');
    }, 1200);
  }, { passive: true });
}
document.addEventListener('DOMContentLoaded', _initGatorScroll);

/* ── Usage Bar ──────────────────────────────────────── */
async function _refreshUsageBar() {
  try {
    const data = await fetch('/api/usage').then(r => r.ok ? r.json() : null);
    if (!data) return;
    const k = n => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(n);
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
    b.style.cssText = 'border:none;border-radius:4px;padding:4px 10px;cursor:pointer;font-size:12px;';
    b.style.background = bgColor;
    b.style.color = '#1e1e2e';
    b.addEventListener('click', onClick);
    return b;
  }

  function _xBtn(onClick) {
    const b = document.createElement('button');
    b.textContent = '\u2715';
    b.style.cssText = 'position:absolute;top:-8px;right:-8px;width:20px;height:20px;border-radius:50%;background:#313244;border:1px solid #555;color:#cdd6f4;cursor:pointer;font-size:11px;line-height:20px;text-align:center;padding:0;display:flex;align-items:center;justify-content:center;';
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
        'position:fixed', 'bottom:20px', 'left:20px',
        'background:#1e1e2e', 'border:1px solid #444', 'border-radius:8px',
        'padding:12px 16px', 'z-index:10001', 'display:flex',
        'align-items:center', 'font-size:13px', 'color:#cdd6f4',
        'box-shadow:0 4px 12px rgba(0,0,0,0.4)', 'font-family:inherit',
        'gap:8px', 'overflow:visible',
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
    try { await fetch('/api/update/download', { method: 'POST' }); } catch (_) {}
  }

  function _sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

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
    try { fetch('/api/update/install', { method: 'POST' }); } catch (_) {}

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
const mcpList   = document.getElementById('mcp-connections-list');

if (mcpAddBtn) {
  mcpAddBtn.addEventListener('click', () => {
    if (typeof window.openMcpAddModal !== 'function') {
      console.error('openMcpAddModal not loaded');
      return;
    }
    window.openMcpAddModal({
      onSuccess: (data) => {
        // Register the new skill into SKILL_MAP immediately (bootstrap only runs at page load)
        if (!SKILL_MAP[data.id]) {
          const entry = {
            id: data.id,
            label: data.name,
            icon: '<span style="font-size:1.1em">🔌</span>',
            chipAlias: data.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || data.id,
            category: 'MCP',
            chipClass: 'chip-mcp',
            connected: true,
            _mcpInjected: true,
            actions: [],
          };
          SKILL_REGISTRY.push(entry);
          SKILL_MAP[data.id] = entry;
        } else {
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
        const idx = SKILL_REGISTRY.findIndex(s => s.id === id);
        if (idx !== -1) SKILL_REGISTRY.splice(idx, 1);
        delete SKILL_MAP[id];
        await _loadMcpConnections();
      } catch (e) {
        console.error('MCP delete failed', e);
      }
    }
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
    sub.textContent = `${c.url} \u00b7 ${c.tool_count} tool${c.tool_count !== 1 ? 's' : ''}`;

    info.appendChild(label);
    info.appendChild(sub);

    // Actions block
    const actions = document.createElement('div');
    actions.className = 'srow-actions';

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

    // Async health check — update dot after render
    _checkMcpHealth(c.id, dot);
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
openDrawer = function() {
  _mcpOrigOpenDrawer();
  _loadMcpConnections();
  loadLlmProfiles();
};

// Initial load on page ready
_loadMcpConnections();

/* ── Model Selector + Swarm Toggle (guide-row pill → rich dropdown) ─── */
(function() {
  'use strict';

  // Derive a friendly short name from any model ID
  function _shortName(mid) {
    // Claude-Sonnet-4.6 → Sonnet 4.6, Claude-Opus-4 → Opus 4
    if (/^Claude-/i.test(mid)) return mid.replace(/^Claude-/i, '').replace(/-/g, ' ');
    // gpt-4.1-mini → GPT-4.1 Mini, gpt-4-turbo → GPT-4 Turbo
    if (/^gpt-/i.test(mid)) {
      return mid.replace(/^gpt/i, 'GPT').split('-').map((p, i) => {
        if (i === 0) return p;                          // GPT
        if (/^\d/.test(p)) return p;                    // 4.1
        return p.charAt(0).toUpperCase() + p.slice(1);  // mini → Mini
      }).join(' ');
    }
    return mid;
  }

  const _MODEL_DESC = {
    'Sonnet 4.6': 'Balanced — fast responses, strong reasoning. Best for most tasks.',
    'Opus 4.6':   'Most capable — deeper reasoning for complex analysis and writing.',
    'Haiku 4.5':  'Fastest — great for quick lookups, short replies, and simple tasks.',
    'Sonnet 4.5': 'Balanced — fast responses, strong reasoning.',
    'Sonnet 4':   'Balanced — good reasoning, fast responses.',
    'Opus 4':     'Deep reasoning for complex analysis.',
    'Opus 4.1':   'Deep reasoning for complex analysis.',
    'Opus 4.5':   'Deep reasoning for complex analysis and writing.',
    'Opus 4.7':   'Deep reasoning for complex analysis and writing.',
  };

  const modelBtn      = document.getElementById('model-selector');
  const modelLabel    = document.getElementById('model-selector-label');
  const modelIcon     = document.getElementById('model-selector-icon');
  const modelDrop     = document.getElementById('model-dropdown');
  const swarmRow      = document.getElementById('swarm-dropdown-row');
  const swarmToggle   = document.getElementById('swarm-dropdown-toggle');
  const guideBar      = document.querySelector('.input-guide');
  const chatInput     = document.getElementById('chat-input');

  if (!modelBtn || !modelDrop) return;

  let _currentModel = '';
  window._currentModel = '';
  let _swarmOn = false;
  let _available = [];

  // ── Focus fade: dim guide hints while typing ──
  if (chatInput && guideBar) {
    chatInput.addEventListener('focus', () => guideBar.classList.add('input-focused'));
    chatInput.addEventListener('blur',  () => guideBar.classList.remove('input-focused'));
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
    scrollBox.querySelectorAll('.guide-model-opt').forEach(el => el.remove());
    available.forEach(mid => {
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
  modelBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    e.preventDefault();
    const open = modelDrop.style.display === 'flex';
    modelDrop.style.display = open ? 'none' : 'flex';
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
