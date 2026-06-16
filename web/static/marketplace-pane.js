// web/static/marketplace-pane.js
// Marketplace plane — browse catalog, manage installed, create user skills.
// Security: all catalog data is stored in data-* attributes and read with dataset,
// never interpolated into onclick handlers or innerHTML without escaping.

(function () {
  'use strict';

  let _catalog = [];
  let _installed = [];
  let _activeTab = 'browse';
  let _searchQuery = '';
  let _filterTier = 'all';
  let _addSubTab = 'import';  // 'import' | 'create' — active section inside the Add tab

  const TIER_BADGE = {
    Native:    { label: 'Native',     cls: 'tier-native' },
    Verified:  { label: '\u2713 Verified', cls: 'tier-verified' },
    Community: { label: 'Community',  cls: 'tier-community' },
    Mine:      { label: 'Mine',       cls: 'tier-mine' },
  };

  function _searchFor(term) {
    _activeTab = 'browse';
    _searchQuery = term.toLowerCase();
    _filterTier = 'all';
    document.querySelectorAll('.mp-tab').forEach(b => {
      b.classList.toggle('mp-tab-active', b.dataset.tab === 'browse');
    });
    const input = document.getElementById('mp-search');
    if (input) input.value = term;
    const filter = document.getElementById('mp-tier-filter');
    if (filter) filter.value = 'all';
    _render();
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  window.MarketplacePane = { mount, refresh };

  // ── Build content surfaces into any host element ───────────────────────────
  function _buildContent(host) {
    // Tabs first — search + tier filter are Browse-only and render under them.
    const tabs = document.createElement('div');
    tabs.className = 'marketplace-tabs';
    [['browse','Browse'],['installed','Installed'],['add','+ Add']].forEach(([id, label]) => {
      const btn = document.createElement('button');
      btn.className = 'mp-tab' + (id === 'browse' ? ' mp-tab-active' : '');
      btn.dataset.tab = id;
      btn.textContent = label;
      if (id === 'installed') {
        const badge = document.createElement('span');
        badge.id = 'mp-installed-count';
        badge.className = 'ap-count';
        btn.appendChild(badge);
      }
      btn.addEventListener('click', () => _switchTab(id));
      tabs.appendChild(btn);
    });

    // Search row — Browse-only. Built once and toggled on tab switch so
    // typing into the input doesn't lose focus when _render() rebuilds the
    // catalog grid on each keystroke.
    const searchRow = document.createElement('div');
    searchRow.id = 'mp-search-row';
    searchRow.className = 'marketplace-search-row';
    const searchInput = document.createElement('input');
    searchInput.id = 'mp-search';
    searchInput.type = 'text';
    searchInput.placeholder = 'Search skills…';
    searchInput.className = 'marketplace-search';
    searchInput.addEventListener('input', e => { _searchQuery = e.target.value.toLowerCase(); _render(); });
    const tierFilter = document.createElement('select');
    tierFilter.id = 'mp-tier-filter';
    tierFilter.className = 'marketplace-tier-filter';
    [['all','All tiers'],['Verified','✓ Verified'],['Community','Community'],['Mine','Mine']]
      .forEach(([val, lbl]) => {
        const opt = document.createElement('option');
        opt.value = val; opt.textContent = lbl;
        tierFilter.appendChild(opt);
      });
    tierFilter.addEventListener('change', e => { _filterTier = e.target.value; _render(); });
    searchRow.appendChild(searchInput);
    searchRow.appendChild(tierFilter);

    // Content area
    const content = document.createElement('div');
    content.id = 'mp-content';
    content.className = 'marketplace-content';

    host.appendChild(tabs);
    host.appendChild(searchRow);
    host.appendChild(content);

    // Single delegated listener for install/remove buttons
    content.addEventListener('click', _handleContentClick);
  }

  // Mount the pane contents inside an existing host element (e.g., a drawer
  // panel). Idempotent — calling mount() twice on the same host is a no-op
  // (just refreshes data).
  function mount(host) {
    if (!host) return;
    if (host.dataset.mpMounted === '1') { refresh(); return; }
    while (host.firstChild) host.removeChild(host.firstChild);
    _buildContent(host);
    host.dataset.mpMounted = '1';
    refresh();
  }

  // ── Tab switching ──────────────────────────────────────────────────────────
  function _switchTab(tab) {
    _activeTab = tab;
    document.querySelectorAll('.mp-tab').forEach(b => {
      b.classList.toggle('mp-tab-active', b.dataset.tab === tab);
    });
    const searchRow = document.getElementById('mp-search-row');
    if (searchRow) searchRow.style.display = (tab === 'browse') ? '' : 'none';
    _render();
  }

  // ── Delegated click handler (no inline onclick) ────────────────────────────
  function _handleContentClick(e) {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === 'install') {
      const skillId = btn.dataset.skillId;
      const skill = _catalog.find(s => s.id === skillId);
      if (skill) _install(skill);
    } else if (action === 'remove') {
      _uninstall(btn.dataset.skillId);
    } else if (action === 'edit-mine') {
      _editMineSkill(btn.dataset.skillId);
    } else if (action === 'submit-create') {
      _submitCreate();
    } else if (action === 'mp-import-fetch') {
      _importFetchPreview();
    } else if (action === 'mp-import-cancel') {
      const urlInput = document.querySelector('.mp-import-url');
      if (urlInput) urlInput.value = '';
      const previewArea = document.getElementById('mp-import-preview');
      if (previewArea) {
        previewArea.classList.remove('active');
        while (previewArea.firstChild) previewArea.removeChild(previewArea.firstChild);
      }
    } else if (action === 'mp-import-install') {
      _importInstall(btn);
    }
  }

  // ── Skeleton loader ────────────────────────────────────────────────────────
  function _mkSk(...cls) { const d = document.createElement('div'); d.className = cls.join(' '); return d; }
  function _renderSkeleton(content) {
    while (content.firstChild) content.removeChild(content.firstChild);
    for (let i = 0; i < 5; i++) {
      const card = _mkSk('mp-skeleton-card');
      const hdr = _mkSk('mp-sk-header');
      hdr.appendChild(_mkSk('mp-sk-line', 'mp-sk-title'));
      hdr.appendChild(_mkSk('mp-sk-line', 'mp-sk-badge'));
      card.appendChild(hdr);
      card.appendChild(_mkSk('mp-sk-line', 'mp-sk-desc'));
      card.appendChild(_mkSk('mp-sk-line', 'mp-sk-desc', 'mp-sk-short'));
      const ftr = _mkSk('mp-sk-footer');
      ftr.appendChild(_mkSk('mp-sk-line', 'mp-sk-meta'));
      ftr.appendChild(_mkSk('mp-sk-line', 'mp-sk-btn'));
      card.appendChild(ftr);
      content.appendChild(card);
    }
  }

  // ── Fetch data ─────────────────────────────────────────────────────────────
  async function refresh() {
    const content = document.getElementById('mp-content');
    if (content && !_catalog.length) _renderSkeleton(content);
    try {
      const [catResp, instResp] = await Promise.all([
        fetch('/api/marketplace/catalog'),
        fetch('/api/marketplace/installed'),
      ]);
      _catalog = (await catResp.json()).skills || [];
      _installed = (await instResp.json()).skills || [];
      const badge = document.getElementById('mp-installed-count');
      if (badge) { badge.textContent = _installed.length ? String(_installed.length) : ''; badge.style.display = _installed.length ? '' : 'none'; }
      _render();
    } catch (err) {
      console.error('Marketplace refresh failed:', err);
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function _render() {
    const content = document.getElementById('mp-content');
    if (!content) return;
    // Clear safely
    while (content.firstChild) content.removeChild(content.firstChild);
    if (_activeTab === 'browse') _renderBrowse(content);
    else if (_activeTab === 'installed') _renderInstalled(content);
    else if (_activeTab === 'add') _renderAdd(content);
  }

  const _TIER_TOOLTIPS = {
    Native:    'Built into AI Gator. Fully trusted.',
    Verified:  'Reviewed by your admin. Full execution access.',
    Community: 'Unreviewed. Runs with restricted permissions.',
    Mine:      'Created by you. Full execution access.',
  };

  function _makeBadge(tier) {
    const cfg = TIER_BADGE[tier] || TIER_BADGE.Community;
    const span = document.createElement('span');
    span.className = 'mp-tier-badge ' + cfg.cls;
    span.textContent = cfg.label;
    span.title = _TIER_TOOLTIPS[tier] || tier;
    return span;
  }

  // Capability vocabulary — used by the legend strip and per-card badges.
  // Keep in sync with the spec's "Capability badges" section.
  // Build the MCP capability icon — matches the MCP tab icon in the drawer
  // rail so the two surfaces share a visual. Constructed via DOM APIs (not
  // innerHTML) to avoid XSS warnings even though the markup is static.
  function _buildMcpSvg() {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', '13');
    svg.setAttribute('height', '13');
    svg.setAttribute('viewBox', '0 0 180 180');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '14');
    svg.setAttribute('stroke-linecap', 'round');
    const paths = [
      'M18 84.8528L85.8822 16.9706C95.2548 7.59798 110.451 7.59798 119.823 16.9706C129.196 26.3431 129.196 41.5391 119.823 50.9117L68.5581 102.177',
      'M69.2652 101.47L119.823 50.9117C129.196 41.5391 144.392 41.5391 153.765 50.9117L154.118 51.2652C163.491 60.6378 163.491 75.8338 154.118 85.2063L92.7248 146.6C89.6006 149.724 89.6006 154.789 92.7248 157.913L105.331 170.52',
      'M102.853 33.9411L52.6482 84.1457C43.2756 93.5183 43.2756 108.714 52.6482 118.087C62.0208 127.459 77.2167 127.459 86.5893 118.087L136.794 67.8822',
    ];
    paths.forEach(d => {
      const p = document.createElementNS(NS, 'path');
      p.setAttribute('d', d);
      svg.appendChild(p);
    });
    return svg;
  }

  // Render the per-card capability badge row. Only renders badges for
  // capabilities the skill actually has — no dimmed placeholders. Today
  // that's 'instructions' (every skill has SKILL.md) and 'tools' (driven
  // by skill.has_tools). The plugin loader branch will start populating
  // has_agents/has_hooks/has_mcp on the skill record.
  function _buildCapBadges(skill) {
    const row = document.createElement('div');
    row.className = 'skill-cap-row';
    const caps = [
      { emoji: '📝', tip: 'Markdown instructions Gator follows for this skill.', active: true },
      { emoji: '🔧', tip: 'Python functions Gator can call (tools.py).', active: !!skill.has_tools },
      { emoji: '🤖', tip: 'Specialist sub-agents declared by the skill.', active: !!skill.has_agents },
      { emoji: '🪝', tip: 'Event triggers fired by Gator at lifecycle points.', active: !!skill.has_hooks },
      { svg: true,  tip: 'Model Context Protocol servers bundled with the skill.', active: !!skill.has_mcp },
    ];
    caps.forEach(cap => {
      if (!cap.active) return;
      const b = document.createElement('span');
      b.className = 'skill-cap-badge';
      b.title = cap.tip;
      b.dataset.active = '1';
      if (cap.svg) b.appendChild(_buildMcpSvg());
      else b.textContent = cap.emoji;
      row.appendChild(b);
    });
    return row;
  }

  function _renderMcpCta(content) {
    const card = document.createElement('div');
    card.className = 'ap-card mp-mcp-cta';

    const top = document.createElement('div');
    top.className = 'mp-card-top';

    const plug = document.createElement('span');
    plug.className = 'mp-mcp-cta-icon';
    plug.textContent = '🔌';
    top.appendChild(plug);

    const name = document.createElement('span');
    name.className = 'mp-skill-name';
    name.textContent = 'Connect an MCP Server';
    top.appendChild(name);


    const desc = document.createElement('div');
    desc.className = 'mp-skill-desc';
    desc.textContent = 'Any MCP-compatible tool becomes a /skill — paste a URL and AI Gator discovers the rest.';

    const actions = document.createElement('div');
    actions.className = 'ap-card-actions';
    actions.style.justifyContent = 'flex-end';

    const btn = document.createElement('button');
    btn.className = 'ap-card-btn primary';
    btn.textContent = '+ Connect';
    btn.addEventListener('click', () => {
      if (typeof window.openSettingsPanel === 'function') {
        window.openSettingsPanel('mcp');
        // Give drawer time to open, then scroll MCP into view
        setTimeout(() => {
          const mcpList = document.getElementById('mcp-connections-list');
          if (mcpList) mcpList.scrollIntoView({ behavior: 'smooth', block: 'start' });
          document.getElementById('mcp-add-btn')?.click();
        }, 320);
      }
    });
    actions.appendChild(btn);

    card.appendChild(top);
    card.appendChild(desc);
    card.appendChild(actions);
    content.appendChild(card);
  }

  function _renderBrowse(content) {
    // Only show MCP CTA when not actively searching/filtering
    if (!_searchQuery && _filterTier === 'all') _renderMcpCta(content);

    // Only user-installed skills count as "installed" for the catalog badge —
    // Native skills share IDs with marketplace entries (docx, excel, ppt, …),
    // so including them here would falsely mark those catalog entries as installed.
    const installedIds = new Set(_installed.filter(s => s.tier !== 'Native').map(s => s.id));
    const filtered = _catalog.filter(s => {
      if (_filterTier !== 'all' && s.tier !== _filterTier) return false;
      if (_searchQuery) {
        const hay = (s.name + ' ' + s.description + ' ' + s.category).toLowerCase();
        if (!hay.includes(_searchQuery)) return false;
      }
      return true;
    });

    if (!filtered.length) {
      const empty = document.createElement('div');
      empty.className = 'ap-empty-state';
      const icon = document.createElement('div');
      icon.className = 'ap-empty-icon';
      icon.textContent = '🔍';
      const title = document.createElement('div');
      title.className = 'ap-empty-title';
      title.textContent = 'No skills found';
      const sub = document.createElement('div');
      sub.className = 'ap-empty-sub';
      sub.textContent = 'Try a different search or filter.';
      empty.appendChild(icon);
      empty.appendChild(title);
      empty.appendChild(sub);
      content.appendChild(empty);
      return;
    }

    // Group by tier in display order
    const TIER_ORDER = ['Native', 'Verified', 'Community', 'Mine'];
    const grouped = {};
    TIER_ORDER.forEach(t => { grouped[t] = []; });
    filtered.forEach(skill => {
      const t = skill.tier || 'Community';
      if (!grouped[t]) grouped[t] = [];
      grouped[t].push(skill);
    });

    TIER_ORDER.forEach(tier => {
      const skills = grouped[tier];
      if (!skills || !skills.length) return;

      // Section header
      const hdr = document.createElement('div');
      hdr.className = 'ap-section-header';
      hdr.appendChild(document.createTextNode(tier.toUpperCase() + '\u00A0'));
      const badge = document.createElement('span');
      badge.className = 'ap-count';
      badge.textContent = String(skills.length);
      hdr.appendChild(badge);
      content.appendChild(hdr);

      skills.forEach(skill => {
        const card = document.createElement('div');
        card.className = 'ap-card';

        const top = document.createElement('div');
        top.className = 'mp-card-top';
        top.appendChild(_makeBadge(skill.tier));
        const name = document.createElement('span');
        name.className = 'mp-skill-name';
        name.textContent = skill.name;
        top.appendChild(name);
        if (skill.install_count) {
          const cnt = document.createElement('span');
          cnt.className = 'mp-install-count';
          cnt.textContent = skill.install_count.toLocaleString() + ' installs';
          top.appendChild(cnt);
        }

        const desc = document.createElement('div');
        desc.className = 'mp-skill-desc';
        desc.textContent = skill.description;

        top.appendChild(_buildCapBadges(skill));

        const footer = document.createElement('div');
        footer.className = 'mp-card-footer';
        const btn = document.createElement('button');
        if (skill.tier === 'Native') {
          btn.className = 'ap-card-btn';
          btn.textContent = 'Built-in';
          btn.disabled = true;
        } else if (installedIds.has(skill.id)) {
          btn.className = 'ap-card-btn';
          btn.textContent = 'Installed';
          btn.disabled = true;
        } else {
          btn.className = 'ap-card-btn primary';
          btn.textContent = 'Install';
          btn.dataset.action = 'install';
          btn.dataset.skillId = skill.id;
        }
        footer.appendChild(btn);

        card.appendChild(top);
        card.appendChild(desc);
        card.appendChild(footer);
        content.appendChild(card);
      });
    });
  }

  function _renderInstalled(content) {
    if (!_installed.length) {
      const empty = document.createElement('div');
      empty.className = 'ap-empty-state';

      const icon = document.createElement('div');
      icon.className = 'ap-empty-icon';
      icon.textContent = '🧩';

      const title = document.createElement('div');
      title.className = 'ap-empty-title';
      title.textContent = 'No skills installed yet';

      const sub = document.createElement('div');
      sub.className = 'ap-empty-sub';
      sub.textContent = 'Browse the catalog to add capabilities to AI Gator.';

      const examples = document.createElement('div');
      examples.className = 'ap-empty-examples';

      [
        { icon: '📄', term: 'docx',  text: "Search for 'docx' to edit Word documents" },
        { icon: '📊', term: 'xlsx',  text: "Search for 'xlsx' to work with spreadsheets" },
        { icon: '📑', term: 'pdf',   text: "Search for 'pdf' to handle PDF files" },
      ].forEach(({ icon: chipIcon, term, text }) => {
        const chip = document.createElement('button');
        chip.className = 'ap-example-chip';
        const i = document.createElement('span');
        i.textContent = chipIcon;
        const t = document.createElement('span');
        t.textContent = text;
        chip.appendChild(i);
        chip.appendChild(t);
        chip.addEventListener('click', () => _searchFor(term));
        examples.appendChild(chip);
      });

      empty.appendChild(icon);
      empty.appendChild(title);
      empty.appendChild(sub);
      empty.appendChild(examples);
      content.appendChild(empty);
      return;
    }
    const nativeSkills = _installed.filter(s => s.tier === 'Native');
    const userSkills   = _installed.filter(s => s.tier !== 'Native');

    // User-installed skills — roomy cards: left column has meta-strip (tier +
    // caps + version) on top and skill name below; right column has Edit/Remove
    // vertically centered across both lines.
    userSkills.forEach(skill => {
      const row = document.createElement('div');
      row.className = 'mp-installed-row tier-' + (skill.tier || '').toLowerCase();

      const text = document.createElement('div');
      text.className = 'mp-installed-text';

      const meta = document.createElement('div');
      meta.className = 'mp-installed-meta';
      const tierLabel = document.createElement('span');
      tierLabel.className = 'mp-installed-tier';
      tierLabel.textContent = skill.tier || '';
      meta.appendChild(tierLabel);
      meta.appendChild(_buildCapBadges(skill));
      const ver = document.createElement('span');
      ver.className = 'mp-installed-version';
      ver.textContent = 'v' + (skill.version || '?');
      meta.appendChild(ver);

      const name = document.createElement('div');
      name.className = 'mp-installed-name';
      name.textContent = skill.display_name || skill.id;

      text.appendChild(meta);
      text.appendChild(name);

      const actions = document.createElement('div');
      actions.className = 'mp-installed-actions';
      if (skill.tier === 'Mine') {
        const editBtn = document.createElement('button');
        editBtn.className = 'mp-row-btn';
        editBtn.textContent = 'Edit';
        editBtn.dataset.action = 'edit-mine';
        editBtn.dataset.skillId = skill.id;
        actions.appendChild(editBtn);
      }
      const removeBtn = document.createElement('button');
      removeBtn.className = 'mp-row-btn mp-row-btn-danger';
      removeBtn.textContent = 'Remove';
      removeBtn.dataset.action = 'remove';
      removeBtn.dataset.skillId = skill.id;
      actions.appendChild(removeBtn);

      row.appendChild(text);
      row.appendChild(actions);
      content.appendChild(row);
    });

    // Single grouped card for all native skills at the bottom
    if (nativeSkills.length) {
      const card = document.createElement('div');
      card.className = 'ap-card mp-native-group';

      const top = document.createElement('div');
      top.className = 'mp-card-top';
      top.appendChild(_makeBadge('Native'));
      const title = document.createElement('span');
      title.className = 'mp-skill-name';
      title.textContent = 'Built-in Skills';
      top.appendChild(title);
      const count = document.createElement('span');
      count.className = 'ap-count';
      count.textContent = String(nativeSkills.length);
      top.appendChild(count);

      const list = document.createElement('div');
      list.className = 'mp-native-list';
      const sorted = [...nativeSkills].sort((a, b) =>
        (a.display_name || a.id).localeCompare(b.display_name || b.id)
      );
      sorted.forEach(s => {
        const item = document.createElement('span');
        item.className = 'mp-native-item';
        item.textContent = s.display_name || s.name || s.id;
        list.appendChild(item);
      });

      card.appendChild(top);
      card.appendChild(list);
      content.appendChild(card);
    }
  }

  function _renderAdd(content) {
    // Sub-tabs so the user picks one path at a time (Import OR Create).
    const subTabs = document.createElement('div');
    subTabs.className = 'mp-subtabs';
    [['import', 'Import from URL'], ['create', 'Create your own']].forEach(([id, label]) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'mp-subtab' + (_addSubTab === id ? ' mp-subtab-active' : '');
      b.textContent = label;
      b.addEventListener('click', () => { _addSubTab = id; _render(); });
      subTabs.appendChild(b);
    });
    content.appendChild(subTabs);

    if (_addSubTab === 'import') _renderImport(content);
    else _renderCreate(content);
  }

  function _renderCreate(content) {
    const form = document.createElement('div');
    form.className = 'mp-create-form';

    const hint = document.createElement('p');
    hint.className = 'mp-create-hint';
    hint.textContent = 'Create a custom skill by writing instructions for the AI. No code required.';
    form.appendChild(hint);

    [['mp-create-name', 'Name', 'text', 'My Workflow'],
     ['mp-create-desc', 'Description', 'text', 'One line shown in the catalog']
    ].forEach(([id, label, type, placeholder]) => {
      const lbl = document.createElement('label');
      lbl.textContent = label;
      const inp = document.createElement('input');
      inp.id = id; inp.type = type; inp.placeholder = placeholder;
      inp.className = 'mp-input';
      lbl.appendChild(inp);
      form.appendChild(lbl);
    });

    // ── Instructions: label row + toggle + drop zone + textarea ──────────
    const instrLbl = document.createElement('div');
    instrLbl.className = 'mp-instr-label-row';

    const instrLblText = document.createElement('span');
    instrLblText.textContent = 'Instructions';

    const uploadToggle = document.createElement('button');
    uploadToggle.className = 'mp-upload-toggle';
    uploadToggle.textContent = '\uD83D\uDCC4 Upload .md';
    uploadToggle.type = 'button';

    instrLbl.appendChild(instrLblText);
    instrLbl.appendChild(uploadToggle);
    form.appendChild(instrLbl);

    // Drop zone (collapsed by default)
    const dropZone = document.createElement('div');
    dropZone.className = 'mp-drop-zone';
    dropZone.style.display = 'none';
    dropZone.textContent = 'Drag & drop a .md file here, or click to browse';

    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.md,text/markdown';
    fileInput.style.display = 'none';

    const uploadError = document.createElement('div');
    uploadError.style.cssText = 'font-size:0.78rem;color:var(--error,#f87171);display:none;margin-top:2px;';

    form.appendChild(dropZone);
    form.appendChild(fileInput);
    form.appendChild(uploadError);

    // Textarea — always visible, upload populates it
    const instrArea = document.createElement('textarea');
    instrArea.id = 'mp-create-instr';
    instrArea.rows = 8;
    instrArea.className = 'mp-input mp-textarea';
    instrArea.placeholder = 'Describe what this skill does and how the AI should behave\u2026';
    form.appendChild(instrArea);

    // ── Toggle: open/close drop zone, or clear a loaded file ────────────
    uploadToggle.addEventListener('click', () => {
      if (uploadToggle.dataset.loaded === '1') {
        // File was loaded — clicking toggle clears it and resets
        instrArea.value = '';
        uploadToggle.textContent = '\uD83D\uDCC4 Upload .md';
        uploadToggle.classList.remove('mp-upload-toggle-active');
        delete uploadToggle.dataset.loaded;
        dropZone.style.display = 'none';
        uploadError.style.display = 'none';
      } else {
        // No file loaded — toggle the drop zone visibility
        const open = dropZone.style.display === 'none';
        dropZone.style.display = open ? '' : 'none';
        uploadToggle.classList.toggle('mp-upload-toggle-active', open);
        uploadError.style.display = 'none';
      }
    });

    // ── File reading ─────────────────────────────────────────────────────
    function _loadFile(file) {
      uploadError.style.display = 'none';
      const ext = file.name.split('.').pop().toLowerCase();
      if (ext !== 'md') {
        uploadError.textContent = 'Only .md files are supported.';
        uploadError.style.display = '';
        return;
      }
      const reader = new FileReader();
      reader.onload = e => {
        instrArea.value = e.target.result;
        // Collapse drop zone; update toggle to show filename with × hint
        dropZone.style.display = 'none';
        uploadToggle.classList.remove('mp-upload-toggle-active');
        uploadToggle.textContent = '\uD83D\uDCC4 ' + file.name + '  \u00D7';
        uploadToggle.dataset.loaded = '1';
      };
      reader.readAsText(file);
    }

    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      if (fileInput.files[0]) _loadFile(fileInput.files[0]);
      fileInput.value = '';
    });
    dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
    dropZone.addEventListener('dragleave', e => { if (!dropZone.contains(e.relatedTarget)) dropZone.classList.remove('drag-over'); });
    dropZone.addEventListener('drop', e => {
      e.preventDefault(); dropZone.classList.remove('drag-over');
      if (e.dataTransfer.files[0]) _loadFile(e.dataTransfer.files[0]);
    });

    const saveBtn = document.createElement('button');
    saveBtn.className = 'mp-create-save-btn';
    saveBtn.textContent = 'Save Skill';
    saveBtn.dataset.action = 'submit-create';
    form.appendChild(saveBtn);

    const result = document.createElement('div');
    result.id = 'mp-create-result';
    form.appendChild(result);

    content.appendChild(form);
  }

  // ── Import from URL ────────────────────────────────────────────────────────
  function _renderImport(content) {
    const wrap = document.createElement('div');
    wrap.className = 'mp-import';

    const label = document.createElement('label');
    label.textContent = 'GitHub folder URL (or raw SKILL.md / .zip URL):';
    label.className = 'mp-import-label';

    const inputRow = document.createElement('div');
    inputRow.className = 'mp-import-row';

    const urlInput = document.createElement('input');
    urlInput.type = 'text';
    urlInput.className = 'mp-input mp-import-url';
    urlInput.placeholder = 'https://github.com/owner/repo/tree/main/skills/foo';

    const fetchBtn = document.createElement('button');
    fetchBtn.type = 'button';
    fetchBtn.className = 'ap-card-btn primary';
    fetchBtn.textContent = 'Fetch';
    fetchBtn.dataset.action = 'mp-import-fetch';

    inputRow.appendChild(urlInput);
    inputRow.appendChild(fetchBtn);

    const errorArea = document.createElement('div');
    errorArea.id = 'mp-import-error';
    errorArea.className = 'mp-import-error';

    const previewArea = document.createElement('div');
    previewArea.id = 'mp-import-preview';
    previewArea.className = 'mp-import-preview';

    wrap.appendChild(label);
    wrap.appendChild(inputRow);
    wrap.appendChild(errorArea);
    wrap.appendChild(previewArea);
    content.appendChild(wrap);
  }

  async function _importFetchPreview() {
    const urlInput = document.querySelector('.mp-import-url');
    const errorArea = document.getElementById('mp-import-error');
    const previewArea = document.getElementById('mp-import-preview');
    const url = (urlInput.value || '').trim();
    errorArea.textContent = '';
    previewArea.classList.remove('active');
    while (previewArea.firstChild) previewArea.removeChild(previewArea.firstChild);
    if (!url) { errorArea.textContent = 'Enter a URL.'; return; }

    try {
      const resp = await fetch('/api/marketplace/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const body = await resp.json();
      if (!resp.ok) { errorArea.textContent = body.detail || 'Preview failed.'; return; }
      _renderImportPreview(previewArea, body, url);
      previewArea.classList.add('active');
    } catch (e) {
      errorArea.textContent = 'Network error: ' + e.message;
    }
  }

  function _renderImportPreview(previewArea, body, url) {
    // Skill name + description
    const head = document.createElement('div');
    const h = document.createElement('strong');
    h.textContent = body.name || body.skill_id;
    head.appendChild(h);
    if (body.description) {
      const d = document.createElement('div');
      d.style.fontSize = '12px';
      d.style.color = 'var(--text-sub, #888)';
      d.textContent = body.description;
      head.appendChild(d);
    }
    previewArea.appendChild(head);

    // Warning banner
    const warn = document.createElement('div');
    warn.className = 'mp-import-warning';
    const strong = document.createElement('strong');
    strong.textContent = '⚠️ UNVERIFIED SOURCE — ';
    warn.appendChild(strong);
    warn.appendChild(document.createTextNode(
      'This skill is from an unverified source. It can run code on your machine. Only install from sources you trust.'
    ));
    previewArea.appendChild(warn);

    // Overwrite notice
    if ((body.warnings || []).includes('overwrite')) {
      const ow = document.createElement('div');
      ow.className = 'mp-import-warning';
      ow.textContent = 'A skill with id "' + body.skill_id + '" is already installed. Installing will overwrite it.';
      previewArea.appendChild(ow);
    }

    // File list
    const sizeKB = (n) => (n / 1024).toFixed(1) + ' KB';
    const filesHdr = document.createElement('div');
    filesHdr.style.fontSize = '12px';
    filesHdr.textContent = 'Will install (Community tier) — ' + body.files.length +
      ' file(s), ' + sizeKB(body.total_size) + ' total:';
    previewArea.appendChild(filesHdr);
    const fileList = document.createElement('div');
    fileList.className = 'mp-import-files';
    body.files.forEach(f => {
      const row = document.createElement('div');
      row.textContent = '• ' + f.path + '  (' + sizeKB(f.size) + ')';
      fileList.appendChild(row);
    });
    previewArea.appendChild(fileList);

    // Orphan section: shown only when re-importing a skill that drops files.
    if (body.orphans && body.orphans.length > 0) {
      const orphansBox = document.createElement('div');
      orphansBox.className = 'mp-import-orphans';

      const heading = document.createElement('div');
      heading.className = 'mp-import-orphans-heading';
      heading.textContent = '⚠ You already have this skill installed. The new version removes ' +
        body.orphans.length + ' file(s):';
      orphansBox.appendChild(heading);

      const ul = document.createElement('ul');
      ul.className = 'mp-import-orphans-list';
      for (const name of body.orphans) {
        const li = document.createElement('li');
        li.textContent = name;
        ul.appendChild(li);
      }
      orphansBox.appendChild(ul);

      const radioWrap = document.createElement('div');
      radioWrap.className = 'mp-import-orphans-radio';

      const makeRadio = (value, label) => {
        const wrapLabel = document.createElement('label');
        const input = document.createElement('input');
        input.type = 'radio';
        input.name = 'mp-orphan-resolution';
        input.value = value;
        wrapLabel.appendChild(input);
        wrapLabel.appendChild(document.createTextNode(' ' + label));
        return wrapLabel;
      };
      radioWrap.appendChild(makeRadio('keep', 'Keep removed files on disk'));
      radioWrap.appendChild(makeRadio('delete', 'Delete them'));
      orphansBox.appendChild(radioWrap);

      previewArea.appendChild(orphansBox);
    }

    // Trust checkbox
    const trustRow = document.createElement('label');
    trustRow.className = 'mp-import-trust';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = 'mp-import-trust-cb';
    trustRow.appendChild(cb);
    trustRow.appendChild(document.createTextNode('I trust this source'));
    previewArea.appendChild(trustRow);

    // Actions
    const actions = document.createElement('div');
    actions.className = 'mp-import-actions';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'mp-btn';
    cancel.textContent = 'Cancel';
    cancel.dataset.action = 'mp-import-cancel';
    const install = document.createElement('button');
    install.type = 'button';
    install.className = 'ap-card-btn primary';
    install.textContent = 'Install';
    install.disabled = true;
    install.dataset.action = 'mp-import-install';
    install.dataset.skillId = body.skill_id;
    install.dataset.url = url;
    const updateInstallEnabled = () => {
      const trustOk = cb.checked;
      const orphansRequired = body.orphans && body.orphans.length > 0;
      const radioOk = !orphansRequired || !!previewArea.querySelector(
        'input[name="mp-orphan-resolution"]:checked'
      );
      install.disabled = !(trustOk && radioOk);
    };
    cb.addEventListener('change', updateInstallEnabled);
    previewArea.querySelectorAll('input[name="mp-orphan-resolution"]').forEach(r =>
      r.addEventListener('change', updateInstallEnabled)
    );
    actions.appendChild(cancel);
    actions.appendChild(install);
    previewArea.appendChild(actions);
    // Call once to set initial state (disabled when orphans exist + nothing picked).
    updateInstallEnabled();
  }

  async function _importInstall(btn) {
    const skillId = btn.dataset.skillId;
    const url = btn.dataset.url;
    btn.disabled = true;
    btn.textContent = 'Installing…';
    const orphanRadio = document.querySelector('input[name="mp-orphan-resolution"]:checked');
    const payload = { skill_id: skillId, install_url: url, tier: 'Community' };
    if (orphanRadio) {
      payload.orphan_resolution = orphanRadio.value;
    }
    try {
      const resp = await fetch('/api/marketplace/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await resp.json();
      if (!resp.ok) {
        const err = document.getElementById('mp-import-error');
        if (err) err.textContent = body.detail || 'Install failed.';
        btn.disabled = false;
        btn.textContent = 'Install';
        return;
      }
      // Success → refresh installed list and switch tab
      await refresh();
      _switchTab('installed');
    } catch (e) {
      const err = document.getElementById('mp-import-error');
      if (err) err.textContent = 'Network error: ' + e.message;
      btn.disabled = false;
      btn.textContent = 'Install';
    }
  }

  // ── Actions ────────────────────────────────────────────────────────────────
  function _showInstallModal(skill, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'mp-modal-overlay';
    const modal = document.createElement('div');
    modal.className = 'mp-modal';

    const title = document.createElement('div');
    title.className = 'mp-modal-title';
    title.textContent = 'Install \u201C' + skill.name + '\u201D?';

    const body = document.createElement('div');
    body.className = 'mp-modal-body';
    const baseWarning = document.createElement('p');
    baseWarning.textContent = 'Only install skills from sources you trust or that have been approved by your IT admin. Skills can execute code on your machine.';
    body.appendChild(baseWarning);

    if (skill.tier === 'Community') {
      const communityWarning = document.createElement('p');
      communityWarning.className = 'mp-modal-community-warn';
      communityWarning.textContent = '\u26A0\uFE0F Community skill: this has not been verified by the AI Gator team. It will run with restricted permissions, but review the source before installing.';
      body.appendChild(communityWarning);
      if (skill.install_url) {
        const reviewLink = document.createElement('a');
        reviewLink.href = skill.install_url;
        reviewLink.target = '_blank';
        reviewLink.rel = 'noopener noreferrer';
        reviewLink.className = 'mp-modal-review-link';
        reviewLink.textContent = 'Review source \u2197';
        body.appendChild(reviewLink);
      }
    }

    const actions = document.createElement('div');
    actions.className = 'mp-modal-actions';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'ap-card-btn';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () => overlay.remove());
    const installBtn = document.createElement('button');
    installBtn.className = 'ap-card-btn primary';
    installBtn.textContent = skill.tier === 'Community' ? 'Install anyway' : 'Install';
    installBtn.addEventListener('click', () => { overlay.remove(); onConfirm(); });

    actions.appendChild(cancelBtn);
    actions.appendChild(installBtn);
    modal.appendChild(title);
    modal.appendChild(body);
    modal.appendChild(actions);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
  }

  async function _install(skill) {
    _showInstallModal(skill, async () => {
      try {
        const resp = await fetch('/api/marketplace/install', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            skill_id: skill.id,
            skill_md: '',
            version: skill.version || '1.0',
            tier: skill.tier,
            install_url: skill.install_url || '',
          }),
        });
        const data = await resp.json();
        if (resp.ok && data.ok) {
          _showAlert('\u201C' + skill.name + '\u201D installed. AI Gator will use this skill immediately.', 'success');
          if (typeof window.registerUserSkill === 'function') {
            window.registerUserSkill(skill.id, skill.name, skill.tier);
          }
          refresh();
        } else {
          _showAlert('Install failed: ' + (data.detail || data.error || 'Unknown error'), 'error');
        }
      } catch (err) {
        _showAlert('Install error: ' + err.message, 'error');
      }
    });
  }

  async function _uninstall(skillId) {
    await new Promise(resolve => {
      const overlay = document.createElement('div');
      overlay.className = 'mp-modal-overlay';
      const modal = document.createElement('div');
      modal.className = 'mp-modal';
      const title = document.createElement('div');
      title.className = 'mp-modal-title';
      title.textContent = 'Remove \u201C' + skillId + '\u201D?';
      const body = document.createElement('div');
      body.className = 'mp-modal-body';
      const p = document.createElement('p');
      p.textContent = 'This will delete the skill files. You can reinstall it from the marketplace at any time.';
      body.appendChild(p);
      const actions = document.createElement('div');
      actions.className = 'mp-modal-actions';
      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'mp-btn mp-btn-cancel';
      cancelBtn.textContent = 'Cancel';
      cancelBtn.addEventListener('click', () => { overlay.remove(); resolve(false); });
      const removeBtn = document.createElement('button');
      removeBtn.className = 'mp-btn mp-btn-danger';
      removeBtn.textContent = 'Remove';
      removeBtn.addEventListener('click', () => { overlay.remove(); resolve(true); });
      actions.appendChild(cancelBtn);
      actions.appendChild(removeBtn);
      modal.appendChild(title);
      modal.appendChild(body);
      modal.appendChild(actions);
      overlay.appendChild(modal);
      document.body.appendChild(overlay);
    }).then(async confirmed => {
      if (!confirmed) return;
      try {
        const resp = await fetch('/api/marketplace/uninstall/' + encodeURIComponent(skillId), { method: 'DELETE' });
        const data = await resp.json();
        if (resp.ok && data.ok) {
          refresh();
        } else {
          _showAlert('Remove failed: ' + (data.detail || data.error || 'Unknown error'), 'error');
        }
      } catch (err) {
        _showAlert('Remove error: ' + err.message, 'error');
      }
    });
  }

  async function _editMineSkill(skillId) {
    let initialMd = '';
    try {
      const resp = await fetch('/api/marketplace/skill-md/' + encodeURIComponent(skillId));
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        _showAlert('Load failed: ' + (data.detail || data.error || 'Unknown error'), 'error');
        return;
      }
      initialMd = data.skill_md || '';
    } catch (err) {
      _showAlert('Load error: ' + err.message, 'error');
      return;
    }

    const overlay = document.createElement('div');
    overlay.className = 'mp-modal-overlay';
    const modal = document.createElement('div');
    modal.className = 'mp-modal mp-modal-edit';

    const title = document.createElement('div');
    title.className = 'mp-modal-title';
    title.textContent = 'Edit “' + skillId + '”';

    const body = document.createElement('div');
    body.className = 'mp-modal-body';
    const hint = document.createElement('div');
    hint.style.cssText = 'font-size:.72rem;color:var(--text-sub);margin-bottom:6px;';
    hint.textContent = 'Edit the full SKILL.md (frontmatter + body). Changes apply immediately, no restart.';
    body.appendChild(hint);
    const textarea = document.createElement('textarea');
    textarea.className = 'mp-edit-textarea';
    textarea.value = initialMd;
    textarea.spellcheck = false;
    body.appendChild(textarea);

    const actions = document.createElement('div');
    actions.className = 'mp-modal-actions';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'mp-btn mp-btn-cancel';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () => overlay.remove());
    const saveBtn = document.createElement('button');
    saveBtn.className = 'mp-btn mp-btn-primary';
    saveBtn.textContent = 'Save';
    saveBtn.addEventListener('click', async () => {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving...';
      try {
        const resp = await fetch('/api/marketplace/skill-md/' + encodeURIComponent(skillId), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ skill_md: textarea.value }),
        });
        const data = await resp.json();
        if (resp.ok && data.ok) {
          overlay.remove();
          _showAlert('“' + skillId + '” updated.', 'success');
          refresh();
        } else {
          saveBtn.disabled = false;
          saveBtn.textContent = 'Save';
          _showAlert('Save failed: ' + (data.detail || data.error || 'Unknown error'), 'error');
        }
      } catch (err) {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
        _showAlert('Save error: ' + err.message, 'error');
      }
    });
    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);

    modal.appendChild(title);
    modal.appendChild(body);
    modal.appendChild(actions);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    textarea.focus();

    // Escape closes only the modal — capture phase so the settings drawer's
    // document-level Escape handler doesn't also fire and close the drawer.
    const escHandler = (e) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      e.preventDefault();
      overlay.remove();
      document.removeEventListener('keydown', escHandler, true);
    };
    document.addEventListener('keydown', escHandler, true);
    // Also drop the handler if the modal is closed by Cancel/Save (overlay removed).
    const _origRemove = overlay.remove.bind(overlay);
    overlay.remove = () => {
      document.removeEventListener('keydown', escHandler, true);
      _origRemove();
    };
  }

  async function _submitCreate() {
    const name = (document.getElementById('mp-create-name') || {}).value || '';
    const desc = (document.getElementById('mp-create-desc') || {}).value || '';
    const instr = (document.getElementById('mp-create-instr') || {}).value || '';
    const resultEl = document.getElementById('mp-create-result');

    if (!name.trim() || !instr.trim()) {
      if (resultEl) resultEl.textContent = 'Name and Instructions are required.';
      return;
    }
    try {
      const resp = await fetch('/api/marketplace/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), description: desc.trim(), instructions: instr.trim() }),
      });
      const data = await resp.json();
      if (resp.ok && data.ok) {
        if (resultEl) {
          const ok = document.createElement('span');
          ok.className = 'mp-success';
          ok.textContent = '\u2705 Skill "' + data.skill_id + '" created and active.';
          resultEl.textContent = '';
          resultEl.appendChild(ok);
        }
        document.getElementById('mp-create-name').value = '';
        document.getElementById('mp-create-desc').value = '';
        document.getElementById('mp-create-instr').value = '';
        // Reset upload toggle if a file was loaded
        const toggle = document.querySelector('.mp-upload-toggle');
        if (toggle) { toggle.textContent = '\uD83D\uDCC4 Upload .md'; delete toggle.dataset.loaded; toggle.classList.remove('mp-upload-toggle-active'); }
        const dz = document.querySelector('.mp-drop-zone');
        if (dz) dz.style.display = 'none';
        // Register skill immediately so slash commands and dock work without reload
        if (typeof window.registerUserSkill === 'function') {
          window.registerUserSkill(data.skill_id, data.display_name || data.skill_id);
        }
        setTimeout(() => { _switchTab('installed'); refresh(); }, 1500);
      } else {
        if (resultEl) resultEl.textContent = 'Error: ' + (data.detail || 'Unknown error');
      }
    } catch (err) {
      if (resultEl) resultEl.textContent = 'Error: ' + err.message;
    }
  }

  // Self-mount if the Skills settings panel is already the active one when this
  // script finishes loading — app.js's initial activateTab('skills') fires
  // before this IIFE registers MarketplacePane, so without this the panel
  // stays blank until the user re-clicks the Skills tab.
  function _selfMountIfActive() {
    const host = document.getElementById('skills-pane-mount');
    const panel = document.getElementById('spanel-skills');
    if (host && panel && !panel.classList.contains('hidden')) {
      mount(host);
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _selfMountIfActive);
  } else {
    _selfMountIfActive();
  }

})();
