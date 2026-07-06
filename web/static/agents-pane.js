/* ── Agents Pane ─────────────────────────────────────── */

let _apRefreshTimer = null;
let _apSelectedJobId = null;
let _apSchedEditorOpen = false; // true while inline schedule editor is expanded
let _apNewFormOpen = false; // true while the inline "New Scheduled Task" form is open

// User-friendly labels for scheduler trigger types. The API contract uses the
// raw keys (cron/interval/date); the UI shows these everywhere (new form + edit)
// so the two views stay consistent. "Recurring" reads better than "cron".
const _AP_TRIGGER_LABELS = { cron: 'Recurring', interval: 'Every N min', date: 'One-time' };

let _apOutsideClickHandler = null;

function _apMaybeCloseOnOutsideClick(e) {
  const pane = document.getElementById('agents-pane');
  if (!pane || !pane.classList.contains('is-open')) return;
  if (pane.contains(e.target)) return;
  // Ignore clicks inside floating popovers/modals that get portaled outside
  // the pane DOM (confirm dialogs, prompt modals, etc.).
  if (e.target.closest && e.target.closest('.modal, .smodal, .confirm-modal, .popover, .dropdown-menu, .toast')) return;
  closeAgentsPane();
}

function openAgentsPane() {
  const pane = document.getElementById('agents-pane');
  if (!pane) return;
  pane.classList.remove('hidden');
  requestAnimationFrame(() => pane.classList.add('is-open'));

  // Clear badge — user has opened the pane, results are visible
  _updateAgentsBadge(0);
  // Show skeleton while first load is in flight
  _apShowSkeleton();
  // Initial load + 60s safety-net poll (SSE task_done drives real-time updates)
  _apRefresh();
  if (_apRefreshTimer) clearInterval(_apRefreshTimer);
  _apRefreshTimer = setInterval(() => {
    if (document.visibilityState !== 'hidden') _apRefresh();
  }, 60000);

  // Close-on-outside-click. Defer to next tick so the click that opened the
  // pane doesn't immediately close it.
  if (_apOutsideClickHandler) document.removeEventListener('mousedown', _apOutsideClickHandler);
  _apOutsideClickHandler = _apMaybeCloseOnOutsideClick;
  setTimeout(() => document.addEventListener('mousedown', _apOutsideClickHandler), 0);
}

function closeAgentsPane() {
  const pane = document.getElementById('agents-pane');
  if (!pane) return;
  pane.classList.remove('is-open');
  setTimeout(() => pane.classList.add('hidden'), 310);
  if (_apRefreshTimer) { clearInterval(_apRefreshTimer); _apRefreshTimer = null; }
  _apSelectedJobId = null;
  _apSchedEditorOpen = false;
  _apNewFormOpen = false;
  document.getElementById('ap-flowchart')?.classList.add('hidden');
  // Reset toolbar to default state
  const closeBtn = document.getElementById('ap-close-btn');
  const backBtn = document.getElementById('ap-back-btn');
  if (closeBtn) closeBtn.style.display = '';
  if (backBtn) backBtn.style.display = 'none';
  if (_apOutsideClickHandler) {
    document.removeEventListener('mousedown', _apOutsideClickHandler);
    _apOutsideClickHandler = null;
  }
}

/* ── Data fetching ───────────────────────────────────── */

function _mkApSk(...cls) { const d = document.createElement('div'); d.className = cls.join(' '); return d; }
function _apSkeletonCard() {
  const card = _mkApSk('ap-skeleton-card');
  const titleRow = _mkApSk('ap-sk-title-row');
  titleRow.appendChild(_mkApSk('ap-sk-line', 'ap-sk-title'));
  titleRow.appendChild(_mkApSk('ap-sk-line', 'ap-sk-status'));
  card.appendChild(titleRow);
  card.appendChild(_mkApSk('ap-sk-line', 'ap-sk-meta'));
  return card;
}

function _rebuildSections() {
  const body = document.getElementById('ap-body');
  if (!body) return;
  // Always remove skeleton cards (may have been injected while fetch was in flight)
  body.querySelectorAll('.ap-skeleton-card').forEach(el => el.remove());
  // Only rebuild if sections are missing (cleared by detail view)
  if (document.getElementById('ap-scheduled-list')) return;
  body.textContent = '';
  const sched = document.createElement('div');
  sched.className = 'ap-section';
  sched.id = 'ap-scheduled';
  const schedHdr = document.createElement('div');
  schedHdr.className = 'ap-section-header';
  schedHdr.textContent = 'SCHEDULED ';
  const schedCount = document.createElement('span');
  schedCount.className = 'ap-count';
  schedCount.id = 'ap-scheduled-count';
  schedCount.textContent = '0';
  schedHdr.appendChild(schedCount);
  const schedList = document.createElement('div');
  schedList.className = 'ap-section-list';
  schedList.id = 'ap-scheduled-list';
  sched.appendChild(schedHdr);
  sched.appendChild(schedList);
  body.appendChild(sched);
  const status = document.createElement('div');
  status.className = 'ap-section';
  status.id = 'ap-status';
  const statusHdr = document.createElement('div');
  statusHdr.className = 'ap-section-header';
  statusHdr.textContent = 'STATUS ';
  const statusCount = document.createElement('span');
  statusCount.className = 'ap-count';
  statusCount.id = 'ap-status-count';
  statusCount.textContent = '0';
  statusHdr.appendChild(statusCount);
  const statusList = document.createElement('div');
  statusList.className = 'ap-section-list';
  statusList.id = 'ap-status-list';
  status.appendChild(statusHdr);
  status.appendChild(statusList);
  body.appendChild(status);
}

function _apShowSkeleton() {
  const body = document.getElementById('ap-body');
  if (!body || body.querySelector('.ap-skeleton-card, .ap-card')) return;
  for (let i = 0; i < 3; i++) body.appendChild(_apSkeletonCard());
}

async function _apRefresh() {
  // Don't clobber the inline "New Scheduled Task" form with a background poll.
  if (_apNewFormOpen) return;
  try {
    const [jobs, tasks] = await Promise.all([
      fetch('/api/scheduler/jobs').then(r => r.ok ? r.json() : []),
      fetch('/api/tasks?limit=30').then(r => r.ok ? r.json() : []),
    ]);
    // Sort: running first, then pending, then done/failed by recency
    const statusTasks = tasks.filter(t => ['running', 'pending', 'done', 'failed'].includes(t.status)).slice(0, 15);
    statusTasks.sort((a, b) => {
      const order = { running: 0, pending: 1, done: 2, failed: 2 };
      return (order[a.status] ?? 3) - (order[b.status] ?? 3);
    });

    // If a job detail is open, refresh it — but not while the schedule editor is expanded
    if (_apSelectedJobId) {
      const selectedJob = jobs.find(j => j.job_id === _apSelectedJobId);
      if (selectedJob) { if (!_apSchedEditorOpen) _openJobDetail(selectedJob); }
      else { _apSelectedJobId = null; _rebuildSections(); _renderScheduled(jobs); _renderStatus(statusTasks); }
    } else {
      _rebuildSections();
      _renderScheduled(jobs);
      _renderStatus(statusTasks);
    }
    // Badge only when pane is closed — pane list IS the notification when open
    const _paneOpen = document.getElementById('agents-pane')?.classList.contains('is-open');
    _updateAgentsBadge(_paneOpen ? 0 : tasks.filter(t => t.status === 'done' || t.status === 'failed').length);
  } catch (e) {
    console.warn('[agents-pane] refresh failed:', e);
  }
}

/* ── Section renderers ───────────────────────────────── */

function _renderStatus(tasks) {
  const list  = document.getElementById('ap-status-list');
  const count = document.getElementById('ap-status-count');
  if (!list) return;

  list.textContent = '';
  if (count) count.textContent = String(tasks.length);

  // Clear all button (only when there are completed/failed items)
  const doneCount = tasks.filter(t => t.status === 'done' || t.status === 'failed').length;
  if (doneCount > 0) {
    const clearBtn = document.createElement('button');
    clearBtn.className = 'ap-card-btn';
    clearBtn.textContent = 'Clear completed';
    clearBtn.style.cssText = 'margin: 4px 12px 8px; font-size: 0.68rem;';
    clearBtn.addEventListener('click', () => {
      _showConfirmModal('Clear completed', 'Remove all completed and failed tasks?', 'Clear', async () => {
        try {
          await fetch('/api/tasks/completed', { method: 'DELETE' });
          _apRefresh();
        } catch (e) { console.warn('Clear failed:', e); }
      });
    });
    list.appendChild(clearBtn);
  }

  if (tasks.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'ap-empty';
    empty.textContent = 'No tasks yet';
    list.appendChild(empty);
    return;
  }

  tasks.forEach(task => {
    const card = document.createElement('div');
    card.className = 'ap-card';

    // Status badge + prompt
    const title = document.createElement('div');
    title.className = 'ap-card-title';
    const statusIcons = { running: '\u23F3 ', pending: '\u23F3 ', done: '\u2705 ', failed: '\u26A0\uFE0F ' };
    const statusLabels = { running: 'Running', pending: 'Queued', done: 'Completed', failed: 'Failed' };
    title.textContent = (statusIcons[task.status] || '') + _truncate(task.prompt || task.task_id, 50);
    card.appendChild(title);

    // Status label + meta
    const meta = document.createElement('div');
    meta.className = 'ap-card-meta';
    const statusSpan = document.createElement('span');
    statusSpan.textContent = statusLabels[task.status] || task.status;
    statusSpan.style.fontWeight = '600';
    if (task.status === 'running') statusSpan.style.color = 'var(--accent)';
    if (task.status === 'failed') statusSpan.style.color = 'var(--error, #f87171)';
    meta.appendChild(statusSpan);

    if (task.status === 'done' || task.status === 'failed') {
      const tokensSpan = document.createElement('span');
      tokensSpan.textContent = _fmtTokens(task) + ' tokens';
      meta.appendChild(tokensSpan);
    }
    const timeSpan = document.createElement('span');
    timeSpan.textContent = _timeAgo(task.completed_at || task.created_at);
    meta.appendChild(timeSpan);
    card.appendChild(meta);

    // Actions based on status
    const actions = document.createElement('div');
    actions.className = 'ap-card-actions';

    if (task.status === 'running' || task.status === 'pending') {
      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'ap-card-btn danger';
      cancelBtn.textContent = 'Cancel';
      cancelBtn.addEventListener('click', (e) => { e.stopPropagation(); _apCancel(task.task_id); });
      actions.appendChild(cancelBtn);
    }

    if (task.status === 'done' || task.status === 'failed') {
      let _viewInNewTab = false;

      // Split button: [View in this chat | ⇅]
      const splitBtn = document.createElement('div');
      splitBtn.className = 'ap-split-btn';

      const mainBtn = document.createElement('button');
      mainBtn.className = 'ap-split-btn-main';
      mainBtn.textContent = 'View in this chat';

      const destBtn = document.createElement('button');
      destBtn.className = 'ap-split-btn-dest';
      destBtn.textContent = '⇅';
      destBtn.title = 'Switch destination';

      destBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        _viewInNewTab = !_viewInNewTab;
        mainBtn.textContent = _viewInNewTab ? 'View in new tab' : 'View in this chat';
        destBtn.classList.toggle('is-new-tab', _viewInNewTab);
      });

      mainBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        try {
          const t = await fetch('/api/tasks/' + task.task_id).then(r => r.json());
          const result = t.result || '(no result)';

          // Re-trigger compose pane if the task produced one
          if (t.pane_data) {
            try {
              const pd = typeof t.pane_data === 'string' ? JSON.parse(t.pane_data) : t.pane_data;
              console.log('[agents-pane] Replaying pane signal:', pd.pane);
              if (typeof _handlePaneSignal === 'function') _handlePaneSignal(pd.pane, pd.paneData || {});
            } catch (pe) { console.warn('[agents-pane] pane replay failed:', pe); }
          }

          const _tabTitle = _truncate(task.prompt || 'Task Result', 40);
          if (_viewInNewTab) {
            // New tab: route by the task's context_id when present so the
            // job's stable conversation history loads in the new tab; else
            // open a fresh blank tab.
            if (t.context_id && typeof createTabWithId === 'function') {
              createTabWithId(t.context_id, _tabTitle);
            } else if (typeof createTab === 'function') {
              createTab();
              if (typeof _tabs !== 'undefined' && typeof _activeTabId !== 'undefined') {
                const tab = _tabs.find(tb => tb.id === _activeTabId);
                if (tab) {
                  tab.title = _tabTitle;
                  if (typeof _saveTabs === 'function') _saveTabs();
                  if (typeof _renderTabBar === 'function') _renderTabBar();
                }
              }
            }
          }
          // "View in this chat" path: render result inline in the current tab
          // without switching context. The result is preview-only — it lives
          // in the DOM, not in the saved conversation history for this tab.

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
          closeAgentsPane();
        } catch (err) { console.warn('View failed:', err); }
      });

      splitBtn.appendChild(mainBtn);
      splitBtn.appendChild(destBtn);

      const delBtn = document.createElement('button');
      delBtn.className = 'ap-card-btn danger';
      delBtn.textContent = 'Delete';
      delBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        try {
          await fetch('/api/tasks/' + task.task_id, { method: 'DELETE' });
          card.remove();
          const remaining = list.querySelectorAll('.ap-card').length;
          if (count) count.textContent = String(remaining);
        } catch (err) { console.warn('Delete failed:', err); }
      });

      const btnRow = document.createElement('div');
      btnRow.className = 'ap-card-btns';
      btnRow.appendChild(splitBtn);
      btnRow.appendChild(delBtn);
      actions.appendChild(btnRow);
    }

    card.appendChild(actions);
    list.appendChild(card);
  });
}

function _renderScheduled(jobs) {
  const list  = document.getElementById('ap-scheduled-list');
  const count = document.getElementById('ap-scheduled-count');
  if (!list) return;

  list.textContent = '';
  if (count) count.textContent = String(jobs.length);

  if (jobs.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'ap-empty-state';

    const icon = document.createElement('div');
    icon.className = 'ap-empty-icon';
    icon.textContent = '🤖';

    const title = document.createElement('div');
    title.className = 'ap-empty-title';
    title.textContent = 'Schedule tasks via chat';

    const sub = document.createElement('div');
    sub.className = 'ap-empty-sub';
    sub.textContent = 'Ask Gator to run something on a schedule — daily briefings, email checks, monitoring, and more.';

    const examples = document.createElement('div');
    examples.className = 'ap-empty-examples';

    const prompts = [
      { icon: '📧', text: 'Email me a summary of my inbox every morning at 8am' },
      { icon: '📅', text: 'Brief me on today\'s meetings every day at 9am' },
      { icon: '🔍', text: 'Check Teams every hour for messages mentioning me' },
      { icon: '🌐', text: 'Every Monday, check our competitor\'s pricing page and tell me if anything changed' },
      { icon: '🌐', text: 'Every morning, search for industry news and give me a 3-bullet summary' },
    ];

    prompts.forEach(p => {
      const chip = document.createElement('button');
      chip.className = 'ap-example-chip';
      const chipIcon = document.createElement('span');
      chipIcon.textContent = p.icon;
      const chipText = document.createElement('span');
      chipText.textContent = p.text;
      chip.appendChild(chipIcon);
      chip.appendChild(chipText);
      chip.addEventListener('click', () => _apStartSchedulePrompt(p.text));
      examples.appendChild(chip);
    });

    empty.appendChild(icon);
    empty.appendChild(title);
    empty.appendChild(sub);
    empty.appendChild(examples);
    list.appendChild(empty);
    return;
  }

  jobs.forEach(job => {
    const card = document.createElement('div');
    card.className = 'ap-card' + (job.paused ? ' ap-card-paused' : '');
    card.style.cursor = 'pointer';

    // Title
    const title = document.createElement('div');
    title.className = 'ap-card-title';
    const isCardRunning = job.last_run && (job.last_run.status === 'running' || job.last_run.status === 'pending');
    const cardPrefix = job.paused ? '\u23F8 ' : (isCardRunning ? '\uD83C\uDFC3 ' : '');
    title.textContent = cardPrefix + (job.name || job.job_id);
    card.appendChild(title);

    // Meta: schedule + next run (compact, no action buttons)
    const meta = document.createElement('div');
    meta.className = 'ap-card-meta';
    const schedSpan = document.createElement('span');
    schedSpan.textContent = _humanSchedule(job);
    meta.appendChild(schedSpan);
    if (job.next_run_time) {
      const nextSpan = document.createElement('span');
      nextSpan.textContent = 'Next: ' + _fmtDate(job.next_run_time);
      meta.appendChild(nextSpan);
    }
    card.appendChild(meta);

    // Click card to open detail view
    card.addEventListener('click', () => _openJobDetail(job));

    list.appendChild(card);
  });
}

/* ── Job Detail View (replaces list when a scheduled job is clicked) ── */

function _openJobDetail(job) {
  const body = document.getElementById('ap-body');
  if (!body) return;
  _apSelectedJobId = job.job_id;

  body.textContent = '';

  // Back button
  // Swap toolbar close button → back button while in detail view
  const closeBtn = document.getElementById('ap-close-btn');
  const backBtn = document.getElementById('ap-back-btn');
  if (closeBtn) closeBtn.style.display = 'none';
  if (backBtn) backBtn.style.display = 'flex';

  const _exitDetail = () => {
    if (closeBtn) closeBtn.style.display = '';
    if (backBtn) backBtn.style.display = 'none';
    _apSelectedJobId = null;
    _apSchedEditorOpen = false;
    _apRefresh();
  };
  if (backBtn) {
    backBtn._exitDetail = _exitDetail; // update handler for this job
  }

  // Job header
  const header = document.createElement('div');
  header.style.cssText = 'padding: 4px 16px 12px; border-bottom: 1px solid var(--border);';
  const jobTitle = document.createElement('div');
  jobTitle.style.cssText = 'font-size: 1rem; font-weight: 700; color: var(--text);';
  jobTitle.textContent = job.name || job.job_id;
  header.appendChild(jobTitle);
  const jobSched = document.createElement('div');
  jobSched.style.cssText = 'font-size: 0.78rem; color: var(--text-sub); margin-top: 2px;';
  jobSched.textContent = _humanSchedule(job) + (job.paused ? ' \u00B7 Paused' : '');
  header.appendChild(jobSched);
  if (job.prompt !== undefined) {
    const promptLabel = document.createElement('div');
    promptLabel.style.cssText = 'font-size: 0.68rem; font-weight: 600; color: var(--text-sub); margin-top: 10px; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.06em;';
    promptLabel.textContent = 'Prompt';
    header.appendChild(promptLabel);

    // Prompt wrapper — holds read view and edit view
    const promptWrap = document.createElement('div');
    promptWrap.className = 'ap-prompt-wrap';

    // Read view: text + pencil icon on hover
    const promptReadView = document.createElement('div');
    promptReadView.className = 'ap-prompt-read';
    const promptText = document.createElement('span');
    promptText.className = 'ap-prompt-text';
    promptText.textContent = job.prompt;
    const pencilBtn = document.createElement('button');
    pencilBtn.className = 'ap-prompt-pencil';
    pencilBtn.title = 'Edit prompt';
    pencilBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
    promptReadView.appendChild(promptText);
    promptReadView.appendChild(pencilBtn);
    promptWrap.appendChild(promptReadView);

    // Edit view: textarea + save/cancel (hidden by default)
    const promptEditView = document.createElement('div');
    promptEditView.className = 'ap-prompt-edit hidden';
    const promptArea = document.createElement('textarea');
    promptArea.rows = 4;
    promptArea.style.cssText = 'width: 100%; box-sizing: border-box; font-size: 0.75rem; color: var(--text); background: var(--surface2); border: 1px solid var(--accent); border-radius: 6px; padding: 6px 8px; resize: vertical; line-height: 1.5; font-family: inherit; outline: none;';
    const editActions = document.createElement('div');
    editActions.className = 'ap-prompt-edit-actions';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'ap-prompt-save-btn';
    saveBtn.title = 'Save';
    saveBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'ap-prompt-cancel-btn';
    cancelBtn.title = 'Cancel (Esc)';
    cancelBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    editActions.appendChild(saveBtn);
    editActions.appendChild(cancelBtn);
    promptEditView.appendChild(promptArea);
    promptEditView.appendChild(editActions);
    promptWrap.appendChild(promptEditView);
    header.appendChild(promptWrap);

    // --- Helpers ---
    const _enterEdit = () => {
      promptArea.value = job.prompt;
      promptReadView.classList.add('hidden');
      promptEditView.classList.remove('hidden');
      promptArea.focus();
      promptArea.setSelectionRange(promptArea.value.length, promptArea.value.length);
    };

    const _exitEdit = () => {
      promptEditView.classList.add('hidden');
      promptReadView.classList.remove('hidden');
    };

    const _doSave = async () => {
      const newPrompt = promptArea.value.trim();
      if (!newPrompt || newPrompt === job.prompt) { _exitEdit(); return; }
      saveBtn.disabled = true;
      try {
        const res = await fetch('/api/scheduler/jobs/' + job.job_id, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: newPrompt }),
        });
        if (res.ok) {
          job.prompt = newPrompt;
          promptText.textContent = newPrompt;
          _exitEdit();
        } else {
          saveBtn.disabled = false;
        }
      } catch {
        saveBtn.disabled = false;
      }
    };

    pencilBtn.addEventListener('click', _enterEdit);
    saveBtn.addEventListener('click', _doSave);
    cancelBtn.addEventListener('click', _exitEdit);
    promptArea.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); _exitEdit(); }
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); _doSave(); }
    });
  }
  body.appendChild(header);

  // Workflow steps (vertical)
  const workflow = document.createElement('div');
  workflow.style.cssText = 'padding: 16px;';
  const wfLabel = document.createElement('div');
  wfLabel.style.cssText = 'font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-sub); margin-bottom: 10px;';
  wfLabel.textContent = 'Workflow';
  workflow.appendChild(wfLabel);

  // ── Trigger step (editable) ──────────────────────────────────────────────
  const triggerRow = document.createElement('div');
  triggerRow.style.cssText = 'display: flex; align-items: flex-start; gap: 10px; padding: 6px 0; cursor: pointer;';
  const triggerIcon = document.createElement('span');
  triggerIcon.style.cssText = 'font-size: 1rem; flex-shrink: 0; width: 24px; text-align: center;';
  triggerIcon.textContent = '\uD83D\uDD50';
  const triggerText = document.createElement('div');
  triggerText.style.cssText = 'flex: 1;';
  const triggerLabelRow = document.createElement('div');
  triggerLabelRow.style.cssText = 'display: flex; align-items: center; justify-content: space-between;';
  const triggerLabel = document.createElement('div');
  triggerLabel.style.cssText = 'font-size: 0.82rem; font-weight: 600; color: var(--text);';
  triggerLabel.textContent = 'Trigger';
  const triggerEditBtn = document.createElement('button');
  triggerEditBtn.className = 'ap-card-btn';
  triggerEditBtn.style.cssText = 'font-size: 0.68rem; padding: 2px 8px;';
  triggerEditBtn.textContent = 'Edit';
  triggerLabelRow.append(triggerLabel, triggerEditBtn);
  const triggerSub = document.createElement('div');
  triggerSub.style.cssText = 'font-size: 0.72rem; color: var(--text-dim);';
  triggerSub.textContent = _humanSchedule(job);
  triggerText.append(triggerLabelRow, triggerSub);
  triggerRow.append(triggerIcon, triggerText);
  workflow.appendChild(triggerRow);

  // Bound-tab row (only when this job has a tab binding) — shows which tab's
  // pinned items get auto-injected on each run.
  if (job.tab_context_id) {
    let _tabName = job.tab_context_id;
    if (typeof _tabs !== 'undefined') {
      const _tab = _tabs.find(tb => tb.id === job.tab_context_id);
      if (_tab && _tab.title) _tabName = _tab.title;
    }
    const tabRow = document.createElement('div');
    tabRow.style.cssText = 'display: flex; align-items: center; gap: 8px; margin: 4px 0 4px 0; font-size: 0.72rem; color: var(--text-dim);';
    const tabIcon = document.createElement('span');
    tabIcon.style.cssText = 'font-size: 0.85rem;';
    tabIcon.textContent = '📌';
    const tabTxt = document.createElement('span');
    tabTxt.appendChild(document.createTextNode('Tab: '));
    const tabStrong = document.createElement('strong');
    tabStrong.style.cssText = 'color: var(--text-sub);';
    tabStrong.textContent = _tabName;
    tabTxt.appendChild(tabStrong);
    tabTxt.appendChild(document.createTextNode(' — pins auto-injected on each run'));
    tabRow.append(tabIcon, tabTxt);
    workflow.appendChild(tabRow);
  }

  // Inline schedule editor (hidden by default)
  const schedEditor = document.createElement('div');
  schedEditor.style.cssText = 'display: none; margin: 6px 0 4px 34px; padding: 10px; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;';

  const args = typeof job.trigger_args === 'string' ? JSON.parse(job.trigger_args) : (job.trigger_args || {});

  // Trigger type selector
  const typeRow = document.createElement('div');
  typeRow.style.cssText = 'margin-bottom: 8px;';
  const typeLabel = document.createElement('label');
  typeLabel.style.cssText = 'font-size: 0.7rem; color: var(--text-sub); display: block; margin-bottom: 3px;';
  typeLabel.textContent = 'Type';
  const typeSel = document.createElement('select');
  typeSel.style.cssText = 'width: 100%; font-size: 0.75rem; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;';
  ['cron', 'interval', 'date'].forEach(t => {
    const opt = document.createElement('option');
    opt.value = t; opt.textContent = _AP_TRIGGER_LABELS[t] || t;
    if (t === job.trigger_type) opt.selected = true;
    typeSel.appendChild(opt);
  });
  typeRow.append(typeLabel, typeSel);
  schedEditor.appendChild(typeRow);

  // Dynamic fields container
  const fieldsWrap = document.createElement('div');
  schedEditor.appendChild(fieldsWrap);

  const inputStyle = 'width: 100%; box-sizing: border-box; font-size: 0.75rem; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; appearance: none; -moz-appearance: textfield;';
  const chipBarStyle = 'display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;';
  const chipStyle = 'font-size: 0.68rem; padding: 2px 8px; border: 1px solid var(--border); border-radius: 12px; background: var(--bg); color: var(--text-sub); cursor: pointer;';
  const chipActiveStyle = 'font-size: 0.68rem; padding: 2px 8px; border: 1px solid var(--accent, #6366f1); border-radius: 12px; background: var(--accent, #6366f1); color: #fff; cursor: pointer;';

  function _mkField(labelTxt, inputEl) {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin-bottom: 8px;';
    const lbl = document.createElement('label');
    lbl.style.cssText = 'font-size: 0.7rem; color: var(--text-sub); display: block; margin-bottom: 3px;';
    lbl.textContent = labelTxt;
    inputEl.style.cssText = inputStyle;
    wrap.append(lbl, inputEl);
    return wrap;
  }

  // Preset chip helper — sets a datetime-local input and highlights chosen chip
  function _mkDatePresets(hiddenInput, presets) {
    const bar = document.createElement('div');
    bar.style.cssText = chipBarStyle;
    const chips = [];
    presets.forEach(({ label, getValue }) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.textContent = label;
      chip.style.cssText = chipStyle;
      chip.addEventListener('click', () => {
        const val = getValue();
        hiddenInput.value = val;
        chips.forEach(c => { c.style.cssText = chipStyle; });
        chip.style.cssText = chipActiveStyle;
      });
      chips.push(chip);
      bar.appendChild(chip);
    });
    return bar;
  }

  function _toLocalISO(d) {
    // Returns datetime-local value string (YYYY-MM-DDTHH:MM) in local time
    const pad = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function _startPresets() {
    return [
      { label: 'Now',       getValue: () => '' },
      { label: 'Tomorrow',  getValue: () => { const d = new Date(); d.setDate(d.getDate()+1); d.setHours(9,0,0,0); return _toLocalISO(d); } },
      { label: 'Next Mon',  getValue: () => { const d = new Date(); const day = d.getDay(); d.setDate(d.getDate() + ((8 - day) % 7 || 7)); d.setHours(9,0,0,0); return _toLocalISO(d); } },
      { label: 'Custom',    getValue: () => startIn.value },
    ];
  }

  function _endPresets() {
    return [
      { label: 'Never',    getValue: () => '' },
      { label: 'EOD',      getValue: () => { const d = new Date(); d.setHours(17,0,0,0); return _toLocalISO(d); } },
      { label: '+4 hours', getValue: () => { const d = new Date(Date.now() + 4*3600000); return _toLocalISO(d); } },
      { label: '+1 day',   getValue: () => { const d = new Date(Date.now() + 86400000); return _toLocalISO(d); } },
      { label: '+1 week',  getValue: () => { const d = new Date(Date.now() + 7*86400000); return _toLocalISO(d); } },
      { label: 'Custom',   getValue: () => endIn.value },
    ];
  }

  // Hidden datetime inputs (actual values submitted)
  const startIn = document.createElement('input'); startIn.type = 'datetime-local'; startIn.dataset.key = '_start_date'; startIn.style.cssText = inputStyle + ' margin-top: 6px;';
  const endIn   = document.createElement('input'); endIn.type   = 'datetime-local'; endIn.dataset.key   = '_end_date';   endIn.style.cssText   = inputStyle + ' margin-top: 6px;';

  // Pre-fill from existing args
  if (args.start_date) startIn.value = args.start_date.slice(0, 16);
  if (args.end_date)   endIn.value   = args.end_date.slice(0, 16);

  function _renderSchedFields(type) {
    fieldsWrap.textContent = '';
    if (type === 'cron') {
      const dowIn = document.createElement('input'); dowIn.type = 'text'; dowIn.placeholder = 'e.g. mon-fri or *'; dowIn.value = args.day_of_week || '*'; dowIn.dataset.key = 'day_of_week';
      const hrIn  = document.createElement('input'); hrIn.type  = 'text'; hrIn.placeholder = '0–23'; hrIn.value = args.hour ?? 9; hrIn.dataset.key = 'hour';
      const minIn = document.createElement('input'); minIn.type = 'text'; minIn.placeholder = '0–59'; minIn.value = args.minute ?? 0; minIn.dataset.key = 'minute';

      // Timezone selector — default to browser local timezone; persisted in trigger_args
      const tzSel = document.createElement('select');
      tzSel.dataset.key = 'timezone';
      tzSel.style.cssText = inputStyle;
      const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const savedTz = args.timezone || browserTz;
      // Common IANA zones — browser local is always first if not in list
      const commonZones = [
        'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
        'America/Phoenix', 'America/Anchorage', 'Pacific/Honolulu',
        'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Moscow',
        'Asia/Dubai', 'Asia/Kolkata', 'Asia/Singapore', 'Asia/Tokyo', 'Asia/Shanghai',
        'Australia/Sydney', 'Pacific/Auckland', 'UTC',
      ];
      if (!commonZones.includes(browserTz)) commonZones.unshift(browserTz);
      commonZones.forEach(tz => {
        const opt = document.createElement('option');
        opt.value = tz;
        opt.textContent = tz === browserTz ? `${tz} (local)` : tz;
        if (tz === savedTz) opt.selected = true;
        tzSel.appendChild(opt);
      });

      fieldsWrap.append(_mkField('Day of week', dowIn), _mkField('Hour (0–23)', hrIn), _mkField('Minute (0–59)', minIn), _mkField('Timezone', tzSel));
    } else if (type === 'interval') {
      const minIn = document.createElement('input'); minIn.type = 'text'; minIn.placeholder = 'e.g. 30'; minIn.value = args.minutes ?? 30; minIn.dataset.key = 'minutes';
      fieldsWrap.append(_mkField('Every N minutes', minIn));
    } else if (type === 'date') {
      const dtIn = document.createElement('input'); dtIn.type = 'datetime-local'; dtIn.dataset.key = 'run_date'; dtIn.style.cssText = inputStyle;
      if (args.run_date) dtIn.value = args.run_date.slice(0, 16);
      fieldsWrap.append(_mkField('Run at', dtIn));
    }
    // Start date (cron + interval)
    if (type !== 'date') {
      const startWrap = document.createElement('div');
      startWrap.style.cssText = 'margin-bottom: 8px;';
      const startLbl = document.createElement('label');
      startLbl.style.cssText = 'font-size: 0.7rem; color: var(--text-sub); display: block; margin-bottom: 3px;';
      startLbl.textContent = 'Start';
      startWrap.appendChild(startLbl);
      startWrap.appendChild(_mkDatePresets(startIn, _startPresets()));
      startWrap.appendChild(startIn);
      fieldsWrap.appendChild(startWrap);

      // End date
      const endWrap = document.createElement('div');
      endWrap.style.cssText = 'margin-bottom: 8px;';
      const endLbl = document.createElement('label');
      endLbl.style.cssText = 'font-size: 0.7rem; color: var(--text-sub); display: block; margin-bottom: 3px;';
      endLbl.textContent = 'End';
      endWrap.appendChild(endLbl);
      endWrap.appendChild(_mkDatePresets(endIn, _endPresets()));
      endWrap.appendChild(endIn);
      fieldsWrap.appendChild(endWrap);
    }
  }
  _renderSchedFields(job.trigger_type);
  typeSel.addEventListener('change', () => _renderSchedFields(typeSel.value));

  // Save button
  const schedSaveBtn = document.createElement('button');
  schedSaveBtn.className = 'ap-card-btn primary';
  schedSaveBtn.style.cssText = 'margin-top: 8px; width: 100%;';
  schedSaveBtn.textContent = 'Save schedule';
  schedSaveBtn.addEventListener('click', async () => {
    const newType = typeSel.value;
    const newArgs = {};
    fieldsWrap.querySelectorAll('[data-key]').forEach(el => {
      if (el.dataset.key.startsWith('_')) return; // skip _start_date / _end_date
      const v = el.value.trim();
      if (v === '') return;
      newArgs[el.dataset.key] = (el.type === 'text' && !isNaN(v)) ? parseInt(v) : v;
    });
    // start_date
    if (startIn.value) newArgs['start_date'] = new Date(startIn.value).toISOString();
    const newEndDate = endIn.value ? new Date(endIn.value).toISOString() : null;

    schedSaveBtn.disabled = true; schedSaveBtn.textContent = 'Saving...';
    try {
      const res = await fetch('/api/scheduler/jobs/' + job.job_id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trigger_type: newType, trigger_args: newArgs, end_date: newEndDate }),
      });
      if (res.ok) {
        const updated = await res.json();
        job.trigger_type = newType;
        job.trigger_args = newArgs;
        if (updated.next_run_time) job.next_run_time = updated.next_run_time;
        triggerSub.textContent = _humanSchedule(job);
        schedSaveBtn.textContent = 'Saved ✓';
        setTimeout(() => {
          schedSaveBtn.textContent = 'Save schedule'; schedSaveBtn.disabled = false;
          schedEditor.style.display = 'none'; triggerEditBtn.textContent = 'Edit';
          _apSchedEditorOpen = false;
        }, 1200);
      } else {
        schedSaveBtn.textContent = 'Failed'; schedSaveBtn.disabled = false;
      }
    } catch { schedSaveBtn.textContent = 'Error'; schedSaveBtn.disabled = false; }
  });
  schedEditor.appendChild(schedSaveBtn);
  workflow.appendChild(schedEditor);

  triggerEditBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = schedEditor.style.display !== 'none';
    schedEditor.style.display = isOpen ? 'none' : 'block';
    triggerEditBtn.textContent = isOpen ? 'Edit' : 'Cancel';
    _apSchedEditorOpen = !isOpen;
  });

  // ── Connector ──
  const conn1 = document.createElement('div');
  conn1.style.cssText = 'width: 2px; height: 12px; background: var(--border); margin-left: 11px;';
  workflow.appendChild(conn1);

  // ── Execute step ──
  const steps2 = [
    { icon: '\u2699\uFE0F', label: 'Execute', sub: 'Run tools and gather data' },
    { icon: '\uD83D\uDCE4', label: 'Deliver', sub: 'Notify with results' },
  ];
  steps2.forEach((s, i) => {
    const row = document.createElement('div');
    row.style.cssText = 'display: flex; align-items: flex-start; gap: 10px; padding: 6px 0;';
    const iconEl = document.createElement('span');
    iconEl.style.cssText = 'font-size: 1rem; flex-shrink: 0; width: 24px; text-align: center;';
    iconEl.textContent = s.icon;
    const textWrap = document.createElement('div');
    const labelEl = document.createElement('div');
    labelEl.style.cssText = 'font-size: 0.82rem; font-weight: 600; color: var(--text);';
    labelEl.textContent = s.label;
    const subEl = document.createElement('div');
    subEl.style.cssText = 'font-size: 0.72rem; color: var(--text-dim);';
    subEl.textContent = s.sub;
    textWrap.append(labelEl, subEl);
    row.append(iconEl, textWrap);
    workflow.appendChild(row);
    if (i < steps2.length - 1) {
      const connector = document.createElement('div');
      connector.style.cssText = 'width: 2px; height: 12px; background: var(--border); margin-left: 11px;';
      workflow.appendChild(connector);
    }
  });
  body.appendChild(workflow);

  // Run history
  const histSection = document.createElement('div');
  histSection.style.cssText = 'padding: 0 16px 12px; border-top: 1px solid var(--border);';
  const histLabel = document.createElement('div');
  histLabel.style.cssText = 'font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-sub); margin: 12px 0 6px;';
  histLabel.textContent = 'Run History';
  histSection.appendChild(histLabel);

  // Show running animation if this job has an active task
  const isRunning = job.last_run && (job.last_run.status === 'running' || job.last_run.status === 'pending');
  if (isRunning) {
    const runningRow = document.createElement('div');
    runningRow.style.cssText = 'display: flex; align-items: center; gap: 8px; font-size: 0.78rem; color: var(--accent, #6366f1); line-height: 1.6;';
    const runnerAnim = document.createElement('span');
    runnerAnim.style.cssText = 'font-size: 1.1rem; display: inline-block; animation: ap-runner-bounce 0.6s ease-in-out infinite alternate;';
    runnerAnim.textContent = '\uD83C\uDFC3';
    const runningText = document.createElement('span');
    runningText.textContent = job.last_run.status === 'running' ? 'Running now…' : 'Queued…';
    runningRow.append(runnerAnim, runningText);
    histSection.appendChild(runningRow);
  } else if (job.last_run) {
    const run = job.last_run;
    const runIcon = run.status === 'done' ? '\u2705' : '\u26A0\uFE0F';

    const lr = document.createElement('div');
    lr.style.cssText = 'font-size: 0.78rem; color: var(--text-dim); line-height: 1.6; margin-bottom: 8px;';
    lr.textContent = runIcon + ' ' + _fmtDate(run.completed_at) + ' \u00B7 ' + _fmtTokens(run) + ' tokens';
    histSection.appendChild(lr);

    // View split button — same as in the status list
    if (run.task_id) {
      let _viewInNewTab = false;
      const splitBtn = document.createElement('div');
      splitBtn.className = 'ap-split-btn';

      const mainBtn = document.createElement('button');
      mainBtn.className = 'ap-split-btn-main';
      mainBtn.textContent = 'View in this chat';

      const destBtn = document.createElement('button');
      destBtn.className = 'ap-split-btn-dest';
      destBtn.textContent = '\u21C5';
      destBtn.title = 'Switch destination';

      destBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        _viewInNewTab = !_viewInNewTab;
        mainBtn.textContent = _viewInNewTab ? 'View in new tab' : 'View in this chat';
        destBtn.classList.toggle('is-new-tab', _viewInNewTab);
      });

      mainBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        try {
          const t = await fetch('/api/tasks/' + run.task_id).then(r => r.json());
          const result = t.result || '(no result)';
          if (t.pane_data) {
            try {
              const pd = typeof t.pane_data === 'string' ? JSON.parse(t.pane_data) : t.pane_data;
              if (typeof _handlePaneSignal === 'function') _handlePaneSignal(pd.pane, pd.paneData || {});
            } catch (pe) { console.warn('[agents-pane] pane replay failed:', pe); }
          }
          const _tabTitle = _truncate(job.name || 'Agent Result', 40);
          if (_viewInNewTab) {
            // New tab: route by the task's context_id so the job's stable
            // conversation loads in the new tab; else open a fresh blank tab.
            if (t.context_id && typeof createTabWithId === 'function') {
              createTabWithId(t.context_id, _tabTitle);
            } else if (typeof createTab === 'function') {
              createTab();
              if (typeof _tabs !== 'undefined' && typeof _activeTabId !== 'undefined') {
                const tab = _tabs.find(tb => tb.id === _activeTabId);
                if (tab) {
                  tab.title = _tabTitle;
                  if (typeof _saveTabs === 'function') _saveTabs();
                  if (typeof _renderTabBar === 'function') _renderTabBar();
                }
              }
            }
          }
          // "View in this chat" path: render result inline in the current tab
          // without switching. Preview-only — not persisted to tab history.
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
          closeAgentsPane();
        } catch (err) { console.warn('View failed:', err); }
      });

      splitBtn.appendChild(mainBtn);
      splitBtn.appendChild(destBtn);
      histSection.appendChild(splitBtn);
    }
  } else {
    const noRuns = document.createElement('div');
    noRuns.style.cssText = 'font-size: 0.78rem; color: var(--text-dim); font-style: italic;';
    noRuns.textContent = 'No runs yet';
    histSection.appendChild(noRuns);
  }
  if (job.next_run_time && !isRunning) {
    const nr = document.createElement('div');
    nr.style.cssText = 'font-size: 0.78rem; color: var(--text-sub); margin-top: 4px;';
    nr.textContent = 'Next run: ' + _fmtDate(job.next_run_time);
    histSection.appendChild(nr);
  }
  body.appendChild(histSection);

  // Actions (single set, at bottom)
  const actions = document.createElement('div');
  actions.style.cssText = 'padding: 12px 16px; border-top: 1px solid var(--border); display: flex; gap: 8px;';

  const runBtn = document.createElement('button');
  runBtn.className = 'ap-card-btn primary';
  runBtn.textContent = 'Run now';
  runBtn.addEventListener('click', () => _apRunNow(job.job_id));

  const pauseBtn = document.createElement('button');
  pauseBtn.className = 'ap-card-btn';
  pauseBtn.textContent = job.paused ? 'Resume' : 'Pause';
  pauseBtn.addEventListener('click', () => _apTogglePause(job.job_id, job.paused));

  const delBtn = document.createElement('button');
  delBtn.className = 'ap-card-btn danger';
  delBtn.style.marginLeft = 'auto';
  delBtn.textContent = 'Delete';
  delBtn.addEventListener('click', () => _apDelete(job.job_id));

  actions.append(runBtn, pauseBtn, delBtn);
  body.appendChild(actions);
}

/* ── Action handlers ─────────────────────────────────── */

async function _apRunNow(jobId) {
  try {
    await fetch('/api/scheduler/jobs/' + jobId + '/run-now', { method: 'POST' });
    _apRefresh();
  } catch (e) { console.warn('Run now failed:', e); }
}

async function _apTogglePause(jobId, isPaused) {
  const endpoint = isPaused ? 'resume' : 'pause';
  try {
    await fetch('/api/scheduler/jobs/' + jobId + '/' + endpoint, { method: 'POST' });
    _apRefresh();
  } catch (e) { console.warn('Pause/resume failed:', e); }
}

function _apDelete(jobId) {
  _showConfirmModal('Delete scheduled task', 'This will permanently remove the scheduled task and its history.', 'Delete', () => {
    // Optimistic: go back to list immediately
    _apSelectedJobId = null;
    _rebuildSections();
    // Fire-and-forget the API call, refresh after
    fetch('/api/scheduler/jobs/' + jobId, { method: 'DELETE' })
      .then(() => _apRefresh())
      .catch(e => console.warn('Delete failed:', e));
  });
}

async function _apCancel(taskId) {
  try {
    await fetch('/api/tasks/' + taskId + '/cancel', { method: 'POST' });
    _apRefresh();
  } catch (e) { console.warn('Cancel failed:', e); }
}

/* ── Badge ───────────────────────────────────────────── */

function _updateAgentsBadge(count) {
  const badge = document.getElementById('dock-agents-badge');
  if (!badge) return;
  if (count > 0) {
    badge.textContent = String(count);
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
}

/* ── Helpers ─────────────────────────────────────────── */

function _truncate(str, maxLen) {
  if (!str) return '';
  return str.length > maxLen ? str.slice(0, maxLen) + '\u2026' : str;
}

function _humanSchedule(job) {
  if (!job.trigger_type || !job.trigger_args) return '';
  const args = typeof job.trigger_args === 'string' ? JSON.parse(job.trigger_args) : job.trigger_args;
  let label = '';
  if (job.trigger_type === 'cron') {
    const days = args.day_of_week || '*';
    const h = args.hour ?? 0;
    const m = args.minute ?? 0;
    const time = (h % 12 || 12) + ':' + String(m).padStart(2, '0') + ' ' + (h >= 12 ? 'PM' : 'AM');
    const dayMap = { mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun', '*': 'Daily' };
    const dayStr = days.split(',').map(d => dayMap[d.trim()] || d).join(', ');
    label = dayStr === 'Daily' ? 'Daily ' + time : dayStr + ' ' + time;
    if (args.timezone && args.timezone !== Intl.DateTimeFormat().resolvedOptions().timeZone) {
      label += ' \u00B7 ' + args.timezone;
    }
  } else if (job.trigger_type === 'interval') {
    const mins = args.minutes;
    if (mins >= 60) label = 'Every ' + Math.round(mins / 60) + ' hr';
    else label = 'Every ' + mins + ' min';
  } else if (job.trigger_type === 'date') {
    label = _fmtDate(args.run_date);
  }
  if (args.end_date) {
    label += ' \u00B7 until ' + _fmtDate(args.end_date);
  }
  return label;
}

function _timeAgo(isoDate) {
  if (!isoDate) return '';
  const diff = Date.now() - new Date(isoDate).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + ' min ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + ' hr ago';
  return Math.floor(hrs / 24) + ' day ago';
}

function _fmtDate(isoDate) {
  if (!isoDate) return 'N/A';
  const d = new Date(isoDate);
  const opts = { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' };
  return d.toLocaleDateString('en-US', opts);
}

function _fmtTokens(run) {
  return ((run.input_tokens || 0) + (run.output_tokens || 0)).toLocaleString();
}

/* ── New Schedule form (inline in #ap-body) ──────────── */

function _apStartSchedulePrompt(prefill = '') {
  _apOpenNewScheduleModal(prefill);
}

function _apOpenNewScheduleModal(prefill = '') {
  // Render the form INLINE inside the Agents pane (replacing the list), the same
  // way _openJobDetail does — instead of a floating white overlay that breaks the
  // pane's dark theme and uses the OS-default scrollbar (#142). The form lives in
  // #ap-body, which already has the app's thin custom scrollbar.
  const apBody = document.getElementById('ap-body');
  if (!apBody) return;

  // Leave any open job-detail view and reset selection state.
  _apSelectedJobId = null;
  _apSchedEditorOpen = false;
  _apNewFormOpen = true;
  apBody.textContent = '';

  // Swap toolbar close button → back button while the form is open (mirrors
  // _openJobDetail), so the form is scoped within the panel and dismissible.
  const apCloseBtn = document.getElementById('ap-close-btn');
  const apBackBtn = document.getElementById('ap-back-btn');
  if (apCloseBtn) apCloseBtn.style.display = 'none';
  if (apBackBtn) apBackBtn.style.display = 'flex';

  const _exitForm = () => {
    if (apCloseBtn) apCloseBtn.style.display = '';
    if (apBackBtn) apBackBtn.style.display = 'none';
    document.removeEventListener('keydown', _keydown);
    _apNewFormOpen = false;
    _apRefresh();
  };
  if (apBackBtn) apBackBtn._exitDetail = _exitForm;

  // Inline section container (matches the dark pane surface).
  const section = document.createElement('div');
  section.className = 'ap-new-sched';

  // Header
  const hdr = document.createElement('div');
  hdr.className = 'ap-new-sched-hdr';
  const title = document.createElement('div');
  title.className = 'ap-new-sched-title';
  title.textContent = 'New Scheduled Task';
  hdr.append(title);
  section.appendChild(hdr);

  const body = document.createElement('div');
  body.className = 'ap-new-sched-body';

  // Shared styles
  const inputStyle = 'width:100%;box-sizing:border-box;font-size:0.8rem;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:6px 10px;font-family:inherit;';
  const labelStyle = 'font-size:0.72rem;color:var(--text-sub);display:block;margin-bottom:4px;font-weight:500;';

  function _field(labelTxt, el) {
    const w = document.createElement('div');
    w.style.cssText = 'margin-bottom:12px;';
    const lbl = document.createElement('label');
    lbl.style.cssText = labelStyle;
    lbl.textContent = labelTxt;
    el.style.cssText = inputStyle;
    w.append(lbl, el);
    return w;
  }

  // Name
  const nameIn = document.createElement('input');
  nameIn.type = 'text';
  nameIn.placeholder = 'e.g. Morning briefing';
  body.appendChild(_field('Name', nameIn));

  // Prompt
  const promptIn = document.createElement('textarea');
  promptIn.rows = 3;
  promptIn.placeholder = prefill || 'What should Gator do?';
  promptIn.style.cssText = inputStyle + 'resize:vertical;';
  const promptWrap = document.createElement('div');
  promptWrap.style.cssText = 'margin-bottom:12px;';
  const promptLbl = document.createElement('label');
  promptLbl.style.cssText = labelStyle;
  promptLbl.textContent = 'Prompt';
  promptWrap.append(promptLbl, promptIn);
  body.appendChild(promptWrap);

  // Trigger type
  const typeRow = document.createElement('div');
  typeRow.style.cssText = 'margin-bottom:12px;display:flex;gap:6px;';
  ['cron', 'interval', 'date'].forEach(t => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = _AP_TRIGGER_LABELS[t] || t;
    btn.dataset.triggerType = t;
    btn.style.cssText = 'flex:1;padding:5px;border-radius:4px;font-size:0.75rem;border:1px solid var(--border);background:var(--bg);color:var(--text-sub);cursor:pointer;';
    btn.addEventListener('click', () => {
      typeRow.querySelectorAll('button').forEach(b => {
        b.style.background = 'var(--bg)';
        b.style.color = 'var(--text-sub)';
        b.style.borderColor = 'var(--border)';
      });
      btn.style.background = 'var(--accent)';
      btn.style.color = '#fff';
      btn.style.borderColor = 'var(--accent)';
      _renderTriggerFields(t);
    });
    typeRow.appendChild(btn);
  });
  body.appendChild(typeRow);

  // Dynamic trigger fields
  const fieldsWrap = document.createElement('div');
  body.appendChild(fieldsWrap);

  const chipBarStyle = 'display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px;';
  const chipStyle = 'font-size:0.68rem;padding:2px 8px;border:1px solid var(--border);border-radius:12px;background:var(--bg);color:var(--text-sub);cursor:pointer;';
  const chipActiveStyle = 'font-size:0.68rem;padding:2px 8px;border:1px solid var(--accent);border-radius:12px;background:var(--accent);color:#fff;cursor:pointer;';

  function _toLocalISO(d) {
    const pad = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function _mkPresets(input, presets) {
    const bar = document.createElement('div');
    bar.style.cssText = chipBarStyle;
    const chips = [];
    presets.forEach(({ label, getValue }) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.textContent = label;
      chip.style.cssText = chipStyle;
      chip.addEventListener('click', () => {
        input.value = getValue();
        chips.forEach(c => { c.style.cssText = chipStyle; });
        chip.style.cssText = chipActiveStyle;
      });
      chips.push(chip);
      bar.appendChild(chip);
    });
    return bar;
  }

  const endIn = document.createElement('input');
  endIn.type = 'datetime-local';
  endIn.style.cssText = inputStyle + 'margin-top:4px;';

  function _renderTriggerFields(type) {
    fieldsWrap.textContent = '';
    if (type === 'cron') {
      const dowIn = document.createElement('input');
      dowIn.type = 'text'; dowIn.placeholder = 'mon-fri or *'; dowIn.value = '*'; dowIn.dataset.key = 'day_of_week';
      const hrIn = document.createElement('input');
      hrIn.type = 'text'; hrIn.placeholder = '0–23'; hrIn.value = '9'; hrIn.dataset.key = 'hour';
      const minIn = document.createElement('input');
      minIn.type = 'text'; minIn.placeholder = '0–59'; minIn.value = '0'; minIn.dataset.key = 'minute';
      const tzSel = document.createElement('select');
      tzSel.dataset.key = 'timezone';
      const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const zones = ['America/New_York','America/Chicago','America/Denver','America/Los_Angeles','Europe/London','Europe/Paris','Asia/Dubai','Asia/Kolkata','Asia/Singapore','Asia/Tokyo','UTC'];
      if (!zones.includes(browserTz)) zones.unshift(browserTz);
      zones.forEach(tz => {
        const opt = document.createElement('option');
        opt.value = tz; opt.textContent = tz === browserTz ? tz + ' (local)' : tz;
        if (tz === browserTz) opt.selected = true;
        tzSel.appendChild(opt);
      });
      fieldsWrap.append(_field('Day of week', dowIn), _field('Hour', hrIn), _field('Minute', minIn), _field('Timezone', tzSel));
    } else if (type === 'interval') {
      const minIn = document.createElement('input');
      minIn.type = 'number'; minIn.min = '1'; minIn.value = '30'; minIn.dataset.key = 'minutes';
      fieldsWrap.appendChild(_field('Every N minutes', minIn));
    } else if (type === 'date') {
      const dtIn = document.createElement('input');
      dtIn.type = 'datetime-local'; dtIn.dataset.key = 'run_date';
      dtIn.value = _toLocalISO(new Date(Date.now() + 3600000));
      fieldsWrap.appendChild(_field('Run at', dtIn));
    }

    if (type !== 'date') {
      const endWrap = document.createElement('div');
      endWrap.style.cssText = 'margin-bottom:12px;';
      const endLbl = document.createElement('label');
      endLbl.style.cssText = labelStyle;
      endLbl.textContent = 'End (optional)';
      endIn.value = '';
      const presets = [
        { label: 'Never',    getValue: () => '' },
        { label: '+1 week',  getValue: () => { const d = new Date(Date.now() + 7*86400000); return _toLocalISO(d); } },
        { label: '+1 month', getValue: () => { const d = new Date(); d.setMonth(d.getMonth()+1); return _toLocalISO(d); } },
      ];
      endWrap.append(endLbl, _mkPresets(endIn, presets), endIn);
      fieldsWrap.appendChild(endWrap);
    }
  }

  // Default to cron
  typeRow.querySelector('[data-trigger-type="cron"]').click();
  body.appendChild(fieldsWrap);

  // Error message
  const errDiv = document.createElement('div');
  errDiv.style.cssText = 'font-size:0.75rem;color:var(--danger,#e55);margin-bottom:8px;display:none;';
  body.appendChild(errDiv);

  // Action row: Cancel + Create
  const actionRow = document.createElement('div');
  actionRow.style.cssText = 'display:flex;gap:8px;margin-top:4px;';

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'ap-card-btn';
  cancelBtn.style.cssText = 'flex:0 0 auto;padding:8px 14px;font-size:0.82rem;';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.addEventListener('click', () => _exitForm());

  const submitBtn = document.createElement('button');
  submitBtn.type = 'button';
  submitBtn.className = 'ap-card-btn primary';
  submitBtn.style.cssText = 'flex:1;padding:8px;font-size:0.82rem;';
  submitBtn.textContent = 'Create Schedule';
  submitBtn.addEventListener('click', async () => {
    const name = nameIn.value.trim();
    const prompt = promptIn.value.trim();
    if (!name || !prompt) {
      errDiv.textContent = 'Name and Prompt are required.';
      errDiv.style.display = 'block';
      return;
    }
    errDiv.style.display = 'none';

    // Determine active trigger type
    const activeTypeBtn = typeRow.querySelector('button[style*="var(--accent)"]') || typeRow.querySelector('button');
    const triggerType = activeTypeBtn.dataset.triggerType;

    const triggerArgs = {};
    fieldsWrap.querySelectorAll('[data-key]').forEach(el => {
      const v = el.value.trim();
      if (!v) return;
      triggerArgs[el.dataset.key] = (el.type === 'number' || (el.type === 'text' && !isNaN(v))) ? parseInt(v) : v;
    });

    const endDate = (triggerType !== 'date' && endIn.value) ? new Date(endIn.value).toISOString() : null;

    submitBtn.disabled = true;
    submitBtn.textContent = 'Creating…';
    try {
      const res = await fetch('/api/scheduler/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, prompt, trigger_type: triggerType, trigger_args: triggerArgs, end_date: endDate }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Server error');
      }
      _exitForm();
    } catch (e) {
      errDiv.textContent = e.message;
      errDiv.style.display = 'block';
      submitBtn.disabled = false;
      submitBtn.textContent = 'Create Schedule';
    }
  });
  actionRow.append(cancelBtn, submitBtn);
  body.appendChild(actionRow);

  section.appendChild(body);
  apBody.appendChild(section);

  // Focus name field
  setTimeout(() => nameIn.focus(), 50);

  // Esc to close the inline form (back to the list)
  const _keydown = e => { if (e.key === 'Escape') { e.preventDefault(); _exitForm(); } };
  document.addEventListener('keydown', _keydown);
}

/* ── Init ────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('ap-close-btn')?.addEventListener('click', closeAgentsPane);
  document.getElementById('ap-new-btn')?.addEventListener('click', () => _apStartSchedulePrompt());
  document.getElementById('ap-back-btn')?.addEventListener('click', () => {
    const btn = document.getElementById('ap-back-btn');
    if (btn?._exitDetail) btn._exitDetail();
  });

  // Drag-to-resize
  const apResize = document.getElementById('ap-resize');
  const apPane = document.getElementById('agents-pane');
  if (apResize && apPane) {
    let dragging = false, startX = 0, startW = 0;
    apResize.addEventListener('mousedown', e => {
      dragging = true;
      startX = e.clientX;
      startW = apPane.offsetWidth;
      apResize.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      e.preventDefault();
    });
    document.addEventListener('mousemove', e => {
      if (!dragging) return;
      const w = Math.max(280, Math.min(800, startW - (e.clientX - startX)));
      apPane.style.width = w + 'px';
    });
    document.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      apResize.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      localStorage.setItem('agents-pane-width', apPane.offsetWidth);
    });
    const saved = parseInt(localStorage.getItem('agents-pane-width'));
    if (saved) apPane.style.width = saved + 'px';
  }

  // Initial badge count — only completed tasks (results to review)
  fetch('/api/tasks?limit=10').then(r => r.ok ? r.json() : []).then(tasks => {
    // Badge only when pane is closed — pane list IS the notification when open
    const _paneOpen = document.getElementById('agents-pane')?.classList.contains('is-open');
    _updateAgentsBadge(_paneOpen ? 0 : tasks.filter(t => t.status === 'done' || t.status === 'failed').length);
  }).catch(() => {});
});
