# Agent Session History

Status: design approved 2026-11-15. Builds on the agent handoff work (PR #117, stacked on #102).

## Problem

A user's agent work is scattered across tools. Sessions live in each agent's own files, a closed terminal tab loses its conversation, and there is no single place to ask "what was I doing here, and what needs me?". Orca offers a session history, but it is busy, shows host and workspace controls that mean nothing to most users, and ties "linked work" to Jira and GitHub. AI Gator should show this project's agent work in one calm list that connects to the rest of the product: resume a session, hand it to another agent, and later plan it on a Workboard.

## Goals

- One list of every agent session in this window's project, past and live, across agents.
- Find a session in seconds: scan titles, search, and preview before opening anything.
- Know at a glance which agent is working and which needs the user.
- Resume a session or continue it in another agent from the same place.
- Look right in both light and dark themes.
- Leave room for a Kanban Workboard without redesigning anything.

## Non-goals (v1)

- Host, workspace or all-projects scopes. A different project opens a new Gator window, so the view is always this window's project.
- Jira, Azure DevOps, GitHub or any "Linked work". That belongs with the Workboard.
- Storing session content. Gator keeps no copy of any conversation.
- Hooks or agent configuration changes to learn live state.
- Syncing history into agents through MCP (issue #76).

## User experience

### Left panel tabs

The left panel's two text tabs ("Source Control", "Explorer") become three icon tabs, each with a tooltip and an accessible name:

| Tab     | Icon                    | Meaning               |
| ------- | ----------------------- | --------------------- |
| Files   | folder                  | the file explorer     |
| Changes | git branch              | source control        |
| History | clock with a back arrow | agent session history |

The History tab shows an amber dot while any session in this project needs the user. Icons use `currentColor` so they follow the theme.

### Session list

A search box sits at the top ("Search this project's sessions"). Below it, sessions are grouped:

1. **Needs you** (amber)
2. **Working** (green)
3. **Today**
4. **Yesterday**
5. **Earlier**

Empty groups are not shown. Each row has two lines:

- Line 1: the title.
- Line 2: `agent · branch · time`. Live rows read "waiting 4m" or "2m".

A live row starts with a status dot (amber needs you, green working). A past row starts with the agent's icon. The only controls are search and the day groups; nothing resets or needs configuring.

**Titles.** Use the agent's own summary when its file has one. Otherwise use the first real user message with boilerplate stripped (system reminders, command wrappers, pasted context markers). No extra AI call is made.

**Hidden.** Subagent sessions and sessions with no real user message. Agents that are not installed are not scanned.

**Empty state.** One plain line: "No agent sessions in this project yet."

### Preview and actions

Clicking a row expands a preview in place: the last few exchanges, passed through the handoff's redaction. Two actions:

- **Resume** (primary): opens a new terminal tab running the agent's own resume command (`claude --resume <id>`, `codex resume <id>`).
- **Continue in another agent…**: opens the existing handoff dialog with this stored session as the source.

If the file was deleted between listing and clicking, resume fails with an inline message and the row drops on the next scan.

### Live states

Gator already owns the terminals it launches, so live state needs no hooks:

- **Working**: the terminal is still printing output. This reuses the handoff's readiness test (`isInputReady`) inverted: not quiet yet.
- **Needs you**: the agent has gone quiet since the user last viewed that tab. Opening the tab clears it.
- Sessions started outside Gator have no terminal in Gator, so they show only as past.

Live sessions join the stored list through the Claude session id Gator pins at launch (`generic_agent.pinned_session_id`). Codex and other agents without a pinned id join by start time: the rollout whose start falls from 5 seconds before to 120 seconds after the terminal's `created_at`, only when exactly one unclaimed Windows rollout matches. Codex writes its first line when the first prompt is sent, so a rollout can start well after the terminal opens.

## Data sources

Nothing new is stored. The list is built from the agents' own files for this project's folder.

| Agent       | Location                               | Project match                                                                           |
| ----------- | -------------------------------------- | --------------------------------------------------------------------------------------- |
| Claude Code | `~/.claude/projects/<slug>/<id>.jsonl` | slug from the folder (`re.sub(r"[^A-Za-z0-9]", "-", cwd)`), compared case-insensitively |
| Codex       | `~/.codex/sessions/**/rollout-*.jsonl` | `cwd` in the first line's `session_meta` payload                                        |

Only the head and tail of each file are read: the head for cwd, branch, version and first user message; the tail for the last exchange and last-activity time. A file's modified time is the session's time.

**Retention.** Gator does not keep a copy. Claude deletes transcripts after 30 days, so older sessions drop off. There is no setting for this.

### WSL

WSL sessions are in v1. They are read through the Windows share `\\wsl.localhost\<distro>\home\<user>\...`, in the background, with the same stale-while-revalidate pattern as the WSL agent probe (`warm_agent_caches`). The list shows Windows results immediately and adds WSL sessions when the read completes.

Known gaps, handled quietly:

- A symlinked `~/.claude` cannot be followed over the share. Skip it with no error.
- Resume must pass the agent its own WSL path, never a UNC path (Orca #24408: an agent started an empty session). The project's Windows folder is also mapped to its `/mnt/c/...` form to match the `cwd` recorded by WSL sessions.
- Codex compresses rollouts idle for 7+ days to `.jsonl.zst` (Orca #40312). Skip them quietly unless a decompressor is already available.
- The distro is stopped or slow: show Windows sessions only; no spinner, no error.

## Implementation notes

- Hidden Claude sessions: `isSidechain`, and any whose first `entrypoint` starts with `sdk` (headless runs that are not user conversations).
- The head read is 256 KB, because a session can open with a very large hook line before the first user message. The tail read is 256 KB.
- A live row is "working" while its terminal printed within the last 3 seconds. After that it is "needs you" until the user views the tab, then "done".
- List titles are redacted as well as previews, because a pasted secret can be the first user message.
- Codex Desktop often opens with a generic prompt, so its titles can read the same ("Review this change…"). The branch and time on the second line tell them apart.

## Session record (Workboard compatibility)

Every list row is built from one stable record:

```
id, agent, title, branch, started_at, last_active_at,
state: needs_you | working | done,
source: windows | wsl:<distro>
```

The three states are the future Kanban columns (Needs you, Working, Done). A Workboard card will be either a session or a work item with sessions attached, so nothing in the list needs rework later. No schema is added now beyond this record.

## Architecture

### Backend

New `web/agent_sessions.py`:

- Scans Claude and Codex files for the project (Windows, plus WSL in the background) and returns session records.
- Reads head and tail only; caches by `(path, mtime, size)`; caps at the 200 newest; runs off the event loop; stale-while-revalidate.
- Unreadable or half-written files are skipped silently.
- Reuses `agent_handoff` for redaction and transcript parsing, not copies of it.

Routes, in `web/routes/generic_agent_routes.py` or a sibling module:

- `GET /api/agent-sessions?project_id=&repo_path=`: the list, with live state merged in from `generic_agent`.
- `GET /api/agent-sessions/{agent}/{id}/preview`: the last exchanges, redacted.
- Resume uses the existing `POST /api/generic-agent/terminal` with a new `resume_id` field. That route already requires `verify_csrf`, so no new mutating route is added. The id is validated against the scanned list for this project (never passed to a shell unchecked) and the launch is always a new process.
- `agent_handoff.prepare_handoff` also accepts a stored session id, so "Continue in another agent…" works for past sessions. Today it needs a live terminal id.

### Frontend

- New `web/static/agent-history.js`: grouping, title and time formatting, live-state merge, row and preview rendering. Pure functions are exported for node tests, as in `agent-handoff.js`.
- `web/static/tp-code-agent.js`: replace the two text tabs with three icon tabs and add the History panel, keeping `_caSetLeftView` as the single switch.
- `web/static/style.css`: styles use only the app's CSS variables (`--surface`, `--bg`, `--border`, `--border2`, `--accent`, `--warn`, `--text`), never hard-coded colours. Scrollbars use the app's thin-scrollbar pattern.

### Rejected

A Gator-owned database index of sessions. It would make search faster but duplicates sensitive conversation data and creates a second place to keep secure and in sync.

## Error handling and limits

- Missing or empty agent directories give an empty list, not an error.
- A scan failure for one agent does not hide the other's sessions.
- The 200-newest cap bounds work and payload size.
- A resume or preview request for a session not in this project's scan returns 404.
- Redaction applies to every preview and every handoff, the same as the live handoff.

## Testing

- Python: parser tests on fixture files (title choice, boilerplate stripping, subagent and empty filtering, half-written file, WSL path mapping, `.zst` skip); route tests (list, preview, 404 on unknown id, resume with `resume_id` including CSRF); `prepare_handoff` from a stored id; the cap and cache.
- Node: grouping and day boundaries, live-state merge, title and time formatting.
- Browser: light and dark themes for the tab strip, list, live dots, preview and empty state, using the fake credential `aigator-fake-api-key` wherever a key is needed.
- `tests/test_csrf_route_inventory.py` stays green without touching its baseline.

## Delivery

Implemented as a stacked PR on top of `feat/agent-handoff` (#117), in this same worktree on its own branch, so history and handoff stay reviewable separately. Nothing is pushed or merged without the user's say-so.

## Later: Workboard

A Kanban view over the session record above, plus work items that sessions attach to. External trackers (Jira, GitHub, Azure DevOps) and "Linked work" are decided there, not here.
