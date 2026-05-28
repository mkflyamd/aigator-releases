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

  // ── SVG helper (no innerHTML — safe DOM construction) ─────────────────────
  function _svgIcon(...paths) {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', '15'); svg.setAttribute('height', '15');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round');
    paths.forEach(d => {
      const el = document.createElementNS(NS, 'path');
      el.setAttribute('d', d);
      svg.appendChild(el);
    });
    return svg;
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  window.MarketplacePane = { open, close, refresh };

  function open() {
    let pane = document.getElementById('marketplace-pane');
    if (!pane) { pane = _build(); document.body.appendChild(pane); }
    pane.classList.remove('hidden');
    pane.getBoundingClientRect(); // force reflow so transition fires
    pane.classList.add('is-open');
    refresh();
  }

  function close() {
    const pane = document.getElementById('marketplace-pane');
    if (!pane) return;
    pane.classList.remove('is-open');
    setTimeout(() => pane.classList.add('hidden'), 310);
  }

  // ── Build skeleton DOM once ────────────────────────────────────────────────
  function _build() {
    const pane = document.createElement('div');
    pane.id = 'marketplace-pane';
    pane.className = 'marketplace-pane hidden';

    // Resize handle
    const resizeHandle = document.createElement('div');
    resizeHandle.id = 'mp-resize';
    resizeHandle.className = 'ap-resize';
    resizeHandle.title = 'Drag to resize';
    pane.appendChild(resizeHandle);

    // Toolbar
    const hdr = document.createElement('div');
    hdr.className = 'ap-toolbar';
    const titleDiv = document.createElement('div');
    titleDiv.className = 'ap-title';
    const NS = 'http://www.w3.org/2000/svg';
    const titleSvg = document.createElementNS(NS, 'svg');
    titleSvg.setAttribute('width', '16'); titleSvg.setAttribute('height', '16');
    titleSvg.setAttribute('viewBox', '0 -960 960 960'); titleSvg.setAttribute('fill', 'currentColor');
    const titlePath = document.createElementNS(NS, 'path');
    titlePath.setAttribute('d', 'M739-83.5q-7-2.5-13-8.5L522-296q-6-6-8.5-13t-2.5-15q0-8 2.5-15t8.5-13l85-85q6-6 13-8.5t15-2.5q8 0 15 2.5t13 8.5l204 204q6 6 8.5 13t2.5 15q0 8-2.5 15t-8.5 13l-85 85q-6 6-13 8.5T754-81q-8 0-15-2.5Zm15-92.5 29-29-147-147-29 29 147 147ZM189.5-83q-7.5-3-13.5-9l-84-84q-6-6-9-13.5T80-205q0-8 3-15t9-13l212-212h85l34-34-165-165h-57L80-765l113-113 121 121v57l165 165 116-116-43-43 56-56H495l-28-28 142-142 28 28v113l56-56 142 142q17 17 26 38.5t9 45.5q0 24-9 46t-26 39l-85-85-56 56-42-42-207 207v84L233-92q-6 6-13 9t-15 3q-8 0-15.5-3Zm15.5-93 170-170v-29h-29L176-205l29 29Zm0 0-29-29 15 14 14 15Zm549 0 29-29-29 29Z');
    titleSvg.appendChild(titlePath);
    titleDiv.appendChild(titleSvg);
    titleDiv.appendChild(document.createTextNode('Skills'));
    const closeBtn = document.createElement('button');
    closeBtn.className = 'ap-toolbar-btn';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.appendChild(_svgIcon('M18 6 6 18', 'M6 6l12 12'));
    closeBtn.addEventListener('click', close);
    hdr.appendChild(titleDiv);
    hdr.appendChild(closeBtn);

    // Search row
    const searchRow = document.createElement('div');
    searchRow.className = 'marketplace-search-row';
    const searchInput = document.createElement('input');
    searchInput.id = 'mp-search';
    searchInput.type = 'text';
    searchInput.placeholder = 'Search skills\u2026';
    searchInput.className = 'marketplace-search';
    searchInput.addEventListener('input', e => { _searchQuery = e.target.value.toLowerCase(); _render(); });
    const tierFilter = document.createElement('select');
    tierFilter.id = 'mp-tier-filter';
    tierFilter.className = 'marketplace-tier-filter';
    [['all','All tiers'],['Verified','\u2713 Verified'],['Community','Community'],['Mine','Mine']]
      .forEach(([val, lbl]) => {
        const opt = document.createElement('option');
        opt.value = val; opt.textContent = lbl;
        tierFilter.appendChild(opt);
      });
    tierFilter.addEventListener('change', e => { _filterTier = e.target.value; _render(); });
    searchRow.appendChild(searchInput);
    searchRow.appendChild(tierFilter);

    // Tabs
    const tabs = document.createElement('div');
    tabs.className = 'marketplace-tabs';
    [['browse','Browse'],['installed','Installed'],['create','+ Create']].forEach(([id, label]) => {
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

    // Content area
    const content = document.createElement('div');
    content.id = 'mp-content';
    content.className = 'marketplace-content';

    pane.appendChild(hdr);
    pane.appendChild(searchRow);
    pane.appendChild(tabs);
    pane.appendChild(content);

    // Single delegated listener for install/remove buttons
    content.addEventListener('click', _handleContentClick);

    // Drag-to-resize
    (function () {
      let dragging = false, startX = 0, startW = 0;
      resizeHandle.addEventListener('mousedown', e => {
        dragging = true;
        startX = e.clientX;
        startW = pane.offsetWidth;
        resizeHandle.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
      });
      document.addEventListener('mousemove', e => {
        if (!dragging) return;
        const w = Math.max(280, Math.min(800, startW - (e.clientX - startX)));
        pane.style.width = w + 'px';
      });
      document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        resizeHandle.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        localStorage.setItem('marketplace-pane-width', pane.offsetWidth);
      });
      const saved = parseInt(localStorage.getItem('marketplace-pane-width'));
      if (saved) pane.style.width = saved + 'px';
    }());

    return pane;
  }

  // ── Tab switching ──────────────────────────────────────────────────────────
  function _switchTab(tab) {
    _activeTab = tab;
    document.querySelectorAll('.mp-tab').forEach(b => {
      b.classList.toggle('mp-tab-active', b.dataset.tab === tab);
    });
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
    } else if (action === 'submit-create') {
      _submitCreate();
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
    else _renderCreate(content);
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
      close();
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

        const actions = document.createElement('div');
        actions.className = 'ap-card-actions';
        actions.style.justifyContent = 'flex-end';
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
        actions.appendChild(btn);

        card.appendChild(top);
        card.appendChild(desc);
        card.appendChild(actions);
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

    // User-installed skills — one card each with Remove
    userSkills.forEach(skill => {
      const card = document.createElement('div');
      card.className = 'ap-card';

      const top = document.createElement('div');
      top.className = 'mp-card-top';
      top.appendChild(_makeBadge(skill.tier));
      const name = document.createElement('span');
      name.className = 'mp-skill-name';
      name.textContent = skill.display_name || skill.id;
      top.appendChild(name);
      const ver = document.createElement('span');
      ver.className = 'mp-version';
      ver.textContent = 'v' + (skill.version || '?');
      top.appendChild(ver);

      const actions = document.createElement('div');
      actions.className = 'ap-card-actions';
      actions.style.justifyContent = 'flex-end';
      const removeBtn = document.createElement('button');
      removeBtn.className = 'ap-card-btn danger';
      removeBtn.textContent = 'Remove';
      removeBtn.dataset.action = 'remove';
      removeBtn.dataset.skillId = skill.id;
      actions.appendChild(removeBtn);

      card.appendChild(top);
      card.appendChild(actions);
      content.appendChild(card);
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

})();
