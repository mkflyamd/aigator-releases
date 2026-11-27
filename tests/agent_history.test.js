const assert = require('assert');
const h = require('../web/static/agent-history.js');

const NOW = new Date(2026, 10, 15, 12, 0, 0).getTime();
const at = (m, d, hh, mm) => new Date(2026, m, d, hh, mm).getTime() / 1000;

// day groups use local calendar days
{
  assert.strictEqual(h.dayGroup(at(10, 15, 0, 30), NOW), 'today');
  assert.strictEqual(h.dayGroup(at(10, 14, 23, 0), NOW), 'yesterday');
  assert.strictEqual(h.dayGroup(at(10, 14, 0, 0), NOW), 'yesterday');
  assert.strictEqual(h.dayGroup(at(10, 13, 23, 59), NOW), 'earlier');
  assert.strictEqual(
    h.dayGroup(at(10, 15, 13, 0), NOW),
    'today',
    'a clock-skewed future time is today',
  );
}

// relative time
{
  const ago = (sec) => NOW / 1000 - sec;
  assert.strictEqual(h.relTime(ago(5), NOW), 'just now');
  assert.strictEqual(h.relTime(ago(50), NOW), '1 min ago');
  assert.strictEqual(h.relTime(ago(5 * 60), NOW), '5 min ago');
  assert.strictEqual(h.relTime(ago(3 * 3600), NOW), '3 h ago');
  assert.strictEqual(h.relTime(ago(2 * 86400), NOW), '2 d ago');
  const old = h.relTime(ago(30 * 86400), NOW);
  assert(old.length > 0 && !old.includes('ago'), 'older than a week is a date');
  assert.strictEqual(h.relTime(ago(-60), NOW), 'just now');
}

// live state from output alone: a work episode (not a lone repaint) is needed for Needs you
{
  assert.strictEqual(h.WORKING_MS, 12000);
  assert.strictEqual(h.liveState({}, NOW), 'done', 'no output yet');
  assert.strictEqual(h.liveState({ _lastOutputAt: NOW - 1000, _viewedAt: 0 }, NOW), 'working');
  assert.strictEqual(h.liveState({ _lastOutputAt: NOW - 1000, _viewedAt: NOW }, NOW), 'working');
  assert.strictEqual(
    h.liveState({ _lastOutputAt: NOW - 8000, _viewedAt: 0 }, NOW),
    'working',
    'a pause shorter than the hold stays Working',
  );
  const worked = (out, viewed) => ({ _lastOutputAt: out, _workedAt: out, _viewedAt: viewed });
  assert.strictEqual(h.liveState(worked(NOW - 20000, NOW - 30000), NOW), 'needs_you');
  assert.strictEqual(h.liveState(worked(NOW - 20000), NOW), 'needs_you', 'never viewed');
  assert.strictEqual(h.liveState(worked(NOW - 20000, NOW - 15000), NOW), 'done');
  assert.strictEqual(h.liveState(worked(NOW - 20000, NOW - 20000), NOW), 'done');
  assert.strictEqual(
    h.liveState({ _lastOutputAt: NOW - 20000, _viewedAt: 0 }, NOW),
    'done',
    'a repaint burst that never became a work episode never asks for attention',
  );
}

// agent-reported (hook) state wins over output timing
{
  const hook = (state, secAgo, extra) =>
    Object.assign({ _hookState: { state, at: NOW / 1000 - secAgo } }, extra || {});
  assert.strictEqual(
    h.liveState(hook('working', 2, { _lastOutputAt: NOW - 60000 }), NOW),
    'working',
  );
  assert.strictEqual(
    h.liveState(hook('idle', 30, { _lastOutputAt: NOW - 500, _workedAt: NOW - 500 }), NOW),
    'needs_you',
    'finished and not yet seen, regardless of spinner output',
  );
  assert.strictEqual(
    h.liveState(hook('idle', 30, { _viewedAt: NOW - 1000 }), NOW),
    'done',
    'finished and seen',
  );
  assert.strictEqual(
    h.liveState(hook('idle', 30, { _viewedAt: NOW - 40000, _lastOutputAt: NOW - 100 }), NOW),
    'needs_you',
    'output after the viewer left does not clear a finished turn',
  );
  assert.strictEqual(
    h.liveState(hook('asking', 600, { _viewedAt: NOW, _lastOutputAt: NOW - 600000 }), NOW),
    'needs_you',
    'a question stays until the agent moves on, even while viewed',
  );
  assert.strictEqual(
    h.liveState(
      hook('asking', 5, { _viewedAt: NOW, _hookState: { state: 'working', at: NOW / 1000 } }),
      NOW,
    ),
    'working',
    'the next hook event replaces the question',
  );
  assert.strictEqual(
    h.liveState(hook('working', 300, { _lastRawOutputAt: NOW - 200000 }), NOW),
    'done',
    'working with no output for two minutes is stale (Esc and crashes fire no hook)',
  );
  assert.strictEqual(
    h.liveState(hook('working', 300, { _lastRawOutputAt: NOW - 1000 }), NOW),
    'working',
    'a long quiet hook turn with live output stays working',
  );
  assert.strictEqual(
    h.liveState(
      hook('working', 300, {
        _lastRawOutputAt: NOW - 200000,
        _lastOutputAt: NOW - 200000,
        _workedAt: NOW - 200000,
      }),
      NOW,
    ),
    'needs_you',
    'a stale working hook falls back to the output heuristic',
  );
}

// output noted as a work episode: continuous output for a few seconds, not a lone burst
{
  const feed = (t, times) => times.forEach((ms) => h.noteOutput(t, NOW + ms));
  const burst = {};
  feed(burst, [0, 100, 200]);
  assert.strictEqual(burst._lastOutputAt, NOW + 200);
  assert.strictEqual(burst._workedAt, undefined, 'a quick repaint burst is not work');
  assert.strictEqual(h.liveState(burst, NOW + 30000), 'done');

  const steady = {};
  feed(steady, [0, 1000, 2000, 3000, 4000]);
  assert.strictEqual(steady._workedAt, NOW + 4000, 'continuous output for 3 s is work');
  assert.strictEqual(h.liveState(steady, NOW + 30000), 'needs_you');

  const apart = {};
  feed(apart, [0, 1000, 2000, 9000, 10000, 11000]);
  assert.strictEqual(
    apart._workedAt,
    undefined,
    'bursts separated by a long gap are separate episodes',
  );

  const resumed = {};
  feed(resumed, [0, 1000, 2000, 3000, 20000]);
  assert.strictEqual(
    resumed._workedAt,
    NOW + 3000,
    'a later lone burst does not extend the old episode',
  );
}

// needsYou looks only at live terminals
{
  const quiet = { _lastOutputAt: NOW - 20000, _workedAt: NOW - 20000, _viewedAt: 0 };
  const busy = { _lastOutputAt: NOW - 500, _workedAt: NOW - 500, _viewedAt: 0 };
  assert.strictEqual(h.needsYou([busy, quiet], NOW), true);
  assert.strictEqual(h.needsYou([busy], NOW), false);
  assert.strictEqual(h.needsYou([], NOW), false);
  assert.strictEqual(h.needsYou(undefined, NOW), false);
}

const rec = (id, agent, title, last, extra) =>
  Object.assign(
    {
      id,
      agent,
      title,
      branch: 'main',
      started_at: last - 60,
      last_active_at: last,
      state: 'done',
      source: 'windows',
    },
    extra || {},
  );
const term = (pty, agent, out, viewed) => ({
  ptySessionId: pty,
  agent,
  _lastOutputAt: out,
  _workedAt: out,
  _viewedAt: viewed,
});

// rows: stored, joined live, and unclaimed live terminals
{
  const sessions = [
    rec('s1', 'claude', 'Fix the login bug', at(10, 15, 9, 0)),
    rec('s2', 'codex', 'Add dark mode', at(10, 14, 16, 0)),
    rec('s3', 'claude', 'Refactor parser', at(10, 1, 9, 0), { pty_session_id: 'p3' }),
    rec('s4', 'claude', 'Joined but its terminal closed', at(10, 15, 8, 0), {
      pty_session_id: 'gone',
    }),
  ];
  const terminals = [
    term('p3', 'claude', NOW - 15000, NOW - 30000),
    term('p9', 'codex', NOW - 1000, 0),
    term('p10', 'terminal', NOW - 1000, 0),
  ];
  const rows = h.buildRows(sessions, terminals, NOW, (a) => a.toUpperCase());
  const by = Object.fromEntries(rows.map((r) => [r.key, r]));

  assert.strictEqual(by['claude:s1'].group, 'today');
  assert.strictEqual(by['claude:s1'].ptySessionId, null);
  assert.strictEqual(by['codex:s2'].group, 'yesterday');
  assert.strictEqual(by['claude:s3'].state, 'needs_you');
  assert.strictEqual(by['claude:s3'].group, 'needs_you');
  assert.strictEqual(by['claude:s3'].ptySessionId, 'p3');
  assert.strictEqual(by['claude:s4'].state, 'done', 'a stale join falls back to a stored row');
  assert.strictEqual(by['claude:s4'].ptySessionId, null);

  const synth = by['live:p9'];
  assert.strictEqual(synth.title, 'New CODEX session');
  assert.strictEqual(synth.id, null);
  assert.strictEqual(synth.state, 'working');
  assert.strictEqual(synth.group, 'working');
  assert.strictEqual(synth.ptySessionId, 'p9');
  assert(!by['live:p10'], 'a bare terminal is not an agent session');
  assert.strictEqual(rows.length, 5);
}

// a live terminal's newer output lifts the row's last-active time
{
  const rows = h.buildRows(
    [rec('s1', 'claude', 'T', at(10, 15, 9, 0), { pty_session_id: 'p1' })],
    [term('p1', 'claude', NOW - 1000, 0)],
    NOW,
  );
  assert.strictEqual(rows[0].lastActive, (NOW - 1000) / 1000);
}

// meta line
{
  const lab = (a) => a[0].toUpperCase() + a.slice(1);
  const ago = (sec) => NOW / 1000 - sec;
  const row = (o) =>
    Object.assign({ agent: 'claude', branch: 'main', source: 'windows', state: 'done' }, o);
  assert.strictEqual(h.shortAge(ago(10), NOW), '<1m');
  assert.strictEqual(h.shortAge(ago(240), NOW), '4m');
  assert.strictEqual(h.shortAge(ago(3 * 3600), NOW), '3h');
  assert.strictEqual(h.shortAge(ago(2 * 86400), NOW), '2d');
  assert.strictEqual(
    h.metaLine(row({ lastActive: ago(3 * 3600) }), NOW, lab),
    'Claude · main · 3 h ago',
  );
  assert.strictEqual(
    h.metaLine(row({ state: 'needs_you', lastActive: ago(240) }), NOW, lab),
    'Claude · main · waiting 4m',
  );
  assert.strictEqual(
    h.metaLine(row({ state: 'working', lastActive: ago(120) }), NOW, lab),
    'Claude · main · 2m',
  );
  assert.strictEqual(
    h.metaLine(row({ branch: '', lastActive: ago(10) }), NOW, lab),
    'Claude · just now',
  );
  assert.strictEqual(
    h.metaLine(row({ source: 'wsl:Ubuntu', lastActive: ago(10) }), NOW, lab),
    'Claude · main · WSL · just now',
  );
}

// actions
{
  assert.deepStrictEqual(h.rowActions({ ptySessionId: 'p1' }), ['go', 'handoff']);
  assert.deepStrictEqual(h.rowActions({ agent: 'claude', ptySessionId: null }), [
    'resume',
    'handoff',
  ]);
  assert.deepStrictEqual(h.rowActions({ agent: 'codex', ptySessionId: null }), [
    'resume',
    'handoff',
  ]);
  // Crush and OpenCode keep no transcript file to build a handoff from.
  assert.deepStrictEqual(h.rowActions({ agent: 'crush', ptySessionId: null }), ['resume']);
  assert.deepStrictEqual(h.rowActions({ agent: 'opencode-bare', ptySessionId: null }), ['resume']);
}

// filtering and grouping
{
  const sessions = [
    rec('a', 'claude', 'Fix login bug', at(10, 15, 9, 0), { branch: 'fix/login' }),
    rec('b', 'codex', 'Add dark mode', at(10, 15, 10, 0), { branch: 'feat/theme' }),
    rec('c', 'claude', 'Old spike', at(10, 1, 10, 0), { branch: 'spike' }),
    rec('d', 'claude', 'Yesterday task', at(10, 14, 10, 0)),
  ];
  const rows = h.buildRows(sessions, [term('p1', 'claude', NOW - 20000, 0)], NOW);
  const all = h.filterGroups(rows, '');
  assert.deepStrictEqual(
    all.map((g) => g.key),
    ['needs_you', 'today', 'yesterday', 'earlier'],
  );
  assert.deepStrictEqual(
    all.find((g) => g.key === 'today').rows.map((r) => r.id),
    ['b', 'a'],
  );
  assert.deepStrictEqual(
    all.find((g) => g.key === 'needs_you').rows.map((r) => r.id),
    [null],
  );

  const login = h.filterGroups(rows, 'LOGIN');
  assert.deepStrictEqual(
    login.map((g) => g.key),
    ['today'],
  );
  assert.deepStrictEqual(
    h
      .filterGroups(rows, 'fix/login')
      .flatMap((g) => g.rows)
      .map((r) => r.id),
    ['a'],
  );
  assert.deepStrictEqual(
    h
      .filterGroups(rows, 'codex theme')
      .flatMap((g) => g.rows)
      .map((r) => r.id),
    ['b'],
  );
  assert.deepStrictEqual(h.filterGroups(rows, 'login codex'), [], 'every word must match');
  assert.deepStrictEqual(
    h.filterGroups(rows, '   ').length,
    all.length,
    'blank query shows everything',
  );
}

// preview card placement: right of the panel, top-aligned with the row, kept on screen
{
  const panel = { left: 56, right: 316 };
  const card = { width: 360, height: 200 };
  const view = { width: 1400, height: 800 };
  assert.deepStrictEqual(
    h.flyoutPlacement({ top: 120 }, panel, card, view),
    { left: 324, top: 120 },
    'beside the panel, level with the row',
  );
  assert.deepStrictEqual(
    h.flyoutPlacement({ top: 700 }, panel, card, view),
    { left: 324, top: 592 },
    'a row near the bottom pulls the card up so it stays on screen',
  );
  assert.strictEqual(
    h.flyoutPlacement({ top: -30 }, panel, card, view).top,
    8,
    'a row scrolled partly off the top keeps the card below the edge',
  );
  assert.deepStrictEqual(
    h.flyoutPlacement({ top: 120 }, { left: 1000, right: 1260 }, card, view),
    { left: 632, top: 120 },
    'no room on the right puts the card on the left of the panel',
  );
  assert.deepStrictEqual(
    h.flyoutPlacement({ top: 120 }, { left: 40, right: 300 }, card, { width: 600, height: 800 }),
    { left: 232, top: 120 },
    'no room on either side overlaps the panel but stays inside the window',
  );
  assert.strictEqual(
    h.flyoutPlacement({ top: 120 }, panel, { width: 360, height: 900 }, view).top,
    8,
    'a card taller than the window starts at the top edge',
  );
}

// tab names follow the history title; a name the user typed on the tab wins both ways
{
  const sessions = [
    rec('s1', 'claude', 'Fix the login bug', at(10, 15, 9, 0), { pty_session_id: 'p1' }),
  ];
  const t1 = { ...term('p1', 'claude', NOW, 0), label: 'Claude 1' };
  const rows = h.buildRows(sessions, [t1], NOW);
  assert.strictEqual(h.syncTabLabels(rows, [t1]), true);
  assert.strictEqual(t1.label, 'Fix the login bug');
  assert.strictEqual(h.syncTabLabels(rows, [t1]), false, 'nothing to do once in sync');

  const t2 = { ...term('p1', 'claude', NOW, 0), label: 'Mine', userLabel: 'Mine' };
  const renamed = h.buildRows(sessions, [t2], NOW);
  assert.strictEqual(renamed[0].title, 'Mine', 'a tab rename shows in history');
  assert.strictEqual(h.syncTabLabels(renamed, [t2]), false);
  assert.strictEqual(t2.label, 'Mine');

  const fresh = { ...term('p9', 'codex', NOW, 0), label: 'Codex 1' };
  const live = h.buildRows([], [fresh], NOW);
  assert.strictEqual(h.syncTabLabels(live, [fresh]), false, 'no stored session, keep the tab name');
  assert.strictEqual(fresh.label, 'Codex 1');
}

// a terminal tab shows the same dot as its history row, from the same state helper
{
  const makeEl = (cls) => {
    const kids = [];
    return {
      className: cls || '',
      children: kids,
      appendChild(c) {
        kids.push(c);
        c.parent = this;
      },
      remove() {
        this.parent.children.splice(this.parent.children.indexOf(this), 1);
      },
      setAttribute() {},
      querySelector(sel) {
        return kids.find((k) => k.className.split(' ').includes(sel.slice(1))) || null;
      },
    };
  };
  global.document = { createElement: () => makeEl() };
  const icon = makeEl('gtp-tab-icon');
  const tab = { querySelector: (sel) => (sel === '.gtp-tab-icon' ? icon : null) };
  const dotClass = () => (icon.children[0] ? icon.children[0].className : '');

  h.applyTabState(tab, term('p1', 'claude', NOW - 1000, 0), NOW);
  assert.strictEqual(dotClass(), 'ah-dot ah-dot-working');
  h.applyTabState(tab, term('p1', 'claude', NOW - 60000, NOW - 120000), NOW);
  assert.strictEqual(dotClass(), 'ah-dot ah-dot-needs_you');
  assert.strictEqual(icon.children.length, 1, 'the dot is reused, not duplicated');
  h.applyTabState(tab, term('p1', 'claude', NOW - 60000, NOW), NOW);
  assert.strictEqual(icon.children.length, 0, 'a done session has no dot');
  h.applyTabState(tab, term('p2', 'terminal', NOW - 1000, 0), NOW);
  assert.strictEqual(icon.children.length, 0, 'a bare terminal never shows a dot');
  delete global.document;
}

// a session open in another window is flagged, unless Gator already owns a terminal for it
{
  const sessions = [
    rec('s1', 'claude', 'Elsewhere', at(10, 15, 9, 0), { live_elsewhere: true }),
    rec('s2', 'claude', 'Owned', at(10, 15, 9, 0), { live_elsewhere: true, pty_session_id: 'p2' }),
    rec('s3', 'claude', 'Closed', at(10, 15, 9, 0)),
  ];
  const rows = h.buildRows(sessions, [term('p2', 'claude', NOW - 1000, 0)], NOW);
  const by = Object.fromEntries(rows.map((r) => [r.id, r]));
  assert.strictEqual(by.s1.liveElsewhere, true);
  assert.strictEqual(by.s2.liveElsewhere, false);
  assert.strictEqual(by.s3.liveElsewhere, false);
  assert.deepStrictEqual(h.rowActions(by.s1), ['resume', 'handoff']);
}

// a session open outside Gator says where, and takes over instead of duplicating
{
  const sessions = [
    rec('s1', 'claude', 'Elsewhere', at(10, 15, 9, 0), {
      live_elsewhere: true,
      live_elsewhere_in: { app: 'Orca', pid: 51892 },
    }),
    rec('s2', 'claude', 'Unknown app', at(10, 15, 9, 0), {
      live_elsewhere: true,
      live_elsewhere_in: { app: null, pid: 71308 },
    }),
  ];
  const by = Object.fromEntries(h.buildRows(sessions, [], NOW).map((r) => [r.id, r]));
  assert.deepStrictEqual(by.s1.elsewhereIn, { app: 'Orca', pid: 51892 });
  assert.strictEqual(h.elsewhereText(by.s1.elsewhereIn), 'Orca (process 51892)');
  assert.strictEqual(h.elsewhereText(by.s2.elsewhereIn), 'another program (process 71308)');
  assert.strictEqual(h.elsewhereText(null), 'another window');
  assert.strictEqual(
    h.takeoverBody({ app: 'Orca', pid: 51892 }),
    'This session is open in Orca (process 51892). Gator will close that process and open the session here. Anything unsaved there is lost.',
  );
  const shown = h.takeoverBody({ app: 'Orca', pid: 51892, created: 1700000000.5 });
  assert(shown.includes('process 51892, started '), 'the dialog shows the process start time');
  assert(!h.takeoverBody({ app: '<b>x</b>', pid: 1 }).includes('<b>'), 'app text is escaped');
}

// only a process the server marked closable, with its identity, can be taken over
{
  const ok = { app: 'Orca', pid: 7, created: 1700000000.5, can_close: true };
  assert.strictEqual(h.canTakeOver(ok), true);
  assert.strictEqual(h.canTakeOver(null), false, 'no identity shown, nothing to confirm');
  assert.strictEqual(h.canTakeOver({ ...ok, can_close: false }), false, 'unknown application');
  assert.strictEqual(h.canTakeOver({ ...ok, can_close: undefined }), false, 'an older server');
  assert.strictEqual(h.canTakeOver({ ...ok, created: null }), false, 'no creation time');
  assert.strictEqual(h.canTakeOver({ ...ok, pid: null }), false);
}

console.log('agent_history: ok');
