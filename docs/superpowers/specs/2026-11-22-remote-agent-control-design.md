# Remote Agent Control — Design

## Goal

Let a user control AI Gator's coding agents from Teams and Slack while away from the machine running Gator, and get the agent's reply back in the same chat. Build it as a small API so Tailscale, a remote UI, more chat channels or a server-hosted tier can be added later without changing the core.

## Why this replaces the Teams relay

Today `web/teams_remote_control.py` polls the Teams self-chat (`48:notes`) every 8 seconds and types `/code <text>` into the active OpenCode PTY. The relay works, but nothing is ever posted back, so the user sees silence. It also targets "the PTY last activated in any tab", and a session dies about 90 seconds after its tab closes (`is_pty_viewed`). Neither is usable when the user is away.

The new trigger is `@gator`, not `/code`. Slack treats every message that starts with `/` as a slash command, so a slash trigger cannot work there. The same grammar is used in Teams and Slack.

## Users and jobs

An AMD employee who started coding-agent work at their desk and leaves. From a phone they need to:

1. Unblock: see that the agent is waiting and answer it.
2. Know: see what it did and whether it finished.
3. Kick off: start a task in a known project.
4. Steer or stop: send a follow-up or stop a run.

## Architecture

Three layers. Each upper layer calls only the layer directly below it.

```
Channel adapters   TeamsSelfChat, SlackSelfDM   (future: WhatsApp, Telegram, Discord, phone UI)
        │  InboundMessage / post()
Command layer      parse @gator commands, enforce scopes, format replies
        │  RemoteApi (Python interface, mirrored 1:1 by HTTP routes)
Session service    headless session lifecycle on a SessionHost
        │
SessionHost        LocalPtyHost (v1)   (future: RemoteHost for a server tier)
```

### Session service

Owns headless sessions. A remote session is a PTY registered in `web/routes/terminal.py` with a `pinned` flag.

- `start(project, text) -> session_id`: starts the project's agent and sends the first message.
- `send(session_id, text)`, `stop(session_id)`, `list()`, `get(session_id)`.
- `output(session_id, since) -> chunks`: agent output since a cursor, ANSI stripped, built from the PTY `output_buf`.
- Session ids are opaque (`pty:<uuid>`), and the vendor session id (Claude, Crush, Codex, OpenCode) is stored beside each one, so a session can be resumed with `agent_sessions.find_session` after a backend restart. Several agents can run per project.
- Internal event bus names events by A2A task state: `submitted`/`working` (agent started or busy), `input-required` (agent is asking the user), `completed` (the agent finished that turn), `failed` or `canceled` (process exited or was stopped). The command layer subscribes to post replies.
- `SessionHost` and `LocalPtyHost` live in their own module (`web/remote/session_host.py`), so the cross-agent relay's terminal adapter can wrap them later.
- Pinned sessions are exempt from the viewer-based reaper. A pinned session ends on `stop`, process exit, or after `remote_session_idle_hours` (default 8) with no input or output.
- Opening the Code tab on a pinned session attaches to it and replays `output_buf`, as it does today.
- Restart survival: the PTY host keeps the PTYs running when the backend restarts. At spawn each remote session is labelled on the host with its channel, short name and start time, beside the existing `remote_pinned`, `project_id` and vendor `session_id` labels. After a restart the service rebuilds its sessions from those labels, keeping those of its own channel whose project still exists and whose process has not exited, and the command layer waits for that before running any command. If the host does not answer, nothing is rebuilt and the next poll tries again; this is reported as a host error, never as "no sessions".
- Closing a terminal in the Code tab is refused with an error, and the session left open, when the host cannot be asked whether the terminal is a remote session.

`SessionHost` is the interface the service calls for spawn, write, read-output, kill and liveness. `LocalPtyHost` wraps the existing PTY registry. A later server tier adds another host without touching the service or API.

### RemoteApi

One Python interface, mirrored 1:1 by loopback HTTP routes under `/api/remote/`. Every POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]`.

- `GET /api/remote/sessions`, `GET /api/remote/sessions/{id}`, `GET /api/remote/sessions/{id}/output?since=`
- `POST /api/remote/sessions` (start), `POST /api/remote/sessions/{id}/send`, `POST /api/remote/sessions/{id}/stop`
- `GET /api/remote/status`: remote control armed, channels connected, last poll, keep-awake held.

Every call carries a `Principal(channel, identity, scopes)`. Scopes are `read`, `send`, `start`, `stop`. v1 adapters run in-process with the full scope set for the signed-in user. The Principal is the seam for later clients: a non-loopback client (Tailscale, phone UI) gets its own revocable token mapped to a scope set, and the API does not change.

### Command layer

Channel-independent. The grammar is `@gator <command or text>`. A message is a command only if it starts with `@gator` (case-insensitive) followed by whitespace. Everything else in the self-chat is an ordinary note and is ignored.

| Message                  | Action                                                                |
| ------------------------ | --------------------------------------------------------------------- |
| `@gator <name> <text>`   | `send` to the session or chat tab with short name `<name>`            |
| `@gator <text>`          | `send` to the default project's session, starting one if none is live |
| `@gator list`            | sessions and chat tabs with short name, agent, state, age             |
| `@gator status [<name>]` | state and the last agent message                                      |
| `@gator stop [<name>]`   | `stop`                                                                |
| `@gator stop all`        | stop every remote session and disarm remote control                   |
| `@gator help`            | command list                                                          |

`list`, `status`, `stop` and `help` are reserved words and are never session names. If the first word after `@gator` is not a reserved word and not a known short name, the whole text goes to the default session.

Short names are the addressing scheme. A session is named after its project (`budget`), with `-2`, `-3` added when a project has more than one live session (`budget-2`). A Gator chat tab is addressed by its tab name, in the same namespace. If a tab name collides with a session short name, the command is refused with the list. The default project is a Settings value (`remote_default_project`), falling back to the active project. When the default project has more than one live session and no name is given, the command is refused with the list.

Input is trimmed, capped at 4096 bytes and sent as one line plus Enter. Replies longer than 3500 characters are truncated with "(truncated, N more characters)".

The command layer posts a reply when a session emits `completed` (agent finished its turn) or `input-required` (agent is asking the user something), containing the agent's last message. Tool-by-tool progress is not posted. Each reply starts with `[Gator - <agent> - <project>]`, for example `[Gator - Claude - budget]`.

### Channel adapters

```
class Channel:
    name: str
    max_len: int
    def poll(self) -> list[InboundMessage]
    def post(self, text: str, reply_to: str | None) -> str
    def self_marker(self) -> str
    def is_own_self_chat(self) -> bool
```

- `TeamsSelfChat`: the existing Skype-client polling of `48:notes`, refactored out of `teams_remote_control.py`, plus a new `post`.
- `SlackSelfDM`: polls the user's own DM channel with the existing user-scoped Slack token (history scope) and posts with chat:write. The channel is found with `conversations.open` on the signed-in user's own id, and `conversations.info` confirms it is a one-to-one DM whose other member is that user before any post. Message ids are Slack `ts` strings such as `1700000000.000200`. They are compared as strings by position in the history page, never as numbers, and `float(ts)` is the message time used for the 15-minute stale check. Slack escapes `&`, `<` and `>` in message text, so the adapter unescapes inbound text and escapes outbound text. Edits, joins and other messages with a `subtype` are not commands.
- Teams and Slack run side by side. Each channel has its own switch (`teams_remote_control_enabled`, `slack_remote_control_enabled`), armed state, rate limit, last-processed id, recorded post ids and session list, so `@gator stop all` in one chat stops only that chat's sessions.
- Adding a channel means implementing this class and registering it. Nothing else changes.

Trust: v1 channels are the user's own private self-chat or DM, so the sender is the signed-in user. Bot-style channels (WhatsApp, Telegram, Discord) later need a sender allow-list with a pairing code and an admin policy, off by default. They are out of scope here.

### Outbound messages and HITL

Teams and Slack messages to the user's own self-chat may auto-send (PR #189 records this exception) when the auto-send gate is on. Everything else stays draft-only: email, messages to other people, channels and threads.

- The gate is `relay.settings.self_chat_autosend_allowed()`: the administrator's `self_chat_autosend` policy must be `allow` and the user's own switch must be on. The switch is off for everyone until they turn it on, including users who already switched Teams or Slack remote control on. Every adapter calls the gate right before it sends, so every Gator post is covered: replies, `[Gator] Online`, notices and agent output. With the gate off nothing is posted, nothing is queued for later, and commands still run. The runner logs this once per arming period.
- Before every post the adapter verifies the recipient is the user's own self-chat: Teams chat id `48:notes`, or the Slack DM channel whose other member is the signed-in user. If the check fails or cannot be made, nothing is posted.
- Every post starts with `[Gator` and never starts with `@gator`, so an agent's output cannot form a command when it is echoed.
- Loop guard: replies land in the same chat the poller reads, so the poller must never treat Gator's own posts as commands. It ignores any message that starts with `[Gator`, and it also ignores any message whose id is one Gator recorded when posting (the ids are kept in `~/.gator/remote_control_state.json`). Either check alone is enough to drop the message.
- The text after `@gator` is the user's own instruction. A message relayed from another agent is a suggestion and is never executed by this layer.

### Delivery guarantees

- At-most-once. The adapter persists the last processed message id and records intent before writing to a PTY, in `~/.gator/remote_control_state.json`. A restart neither replays nor silently skips.
- Staleness. A message older than `remote_stale_minutes` (default 15) at pickup is not run. Gator posts `[Gator] Skipped N message(s) received while I was offline. Resend if still needed.` Messages inside the window run once.
- Liveness. On startup and on recovery from a failed poll, Gator posts `[Gator] Online`. Failures it can report (no live session, expired token, agent exited, unknown name) get an immediate reply naming the reason. Replies with `[Gator]` are the only signal the user needs: no reply within a minute of a command means Gator is offline.
- Poll cadence: 3 seconds while a session is active or a command arrived in the last 180 seconds, otherwise 10 seconds.
- Inbound rate limit: at most 20 commands per 10 minutes per channel. Excess commands get one `[Gator] Slow down` reply and are dropped.
- Absolute cap: remote control disarms after `remote_armed_max_hours` (default 24), whether or not sessions are active, and posts `[Gator] Remote control timed out. Re-arm it in Settings.` The idle limit applies to individual sessions within that window.
- Expiry, rate limit and stop-all live in one guard-rails module that the cross-agent relay shares. Components depend on its small interface (expiry timer, sliding-window rate limit, stop-all registry), not on where the module lives.

### Headless and power behavior

- No UI is needed. Nothing navigates on the physical screen. A locked screen does not affect the backend, the PTY or the chat polls.
- While remote control is armed and a pinned session is live, Gator holds `ES_SYSTEM_REQUIRED` from a dedicated thread (the call is per-thread). Armed with no live session releases it.
- Settings shows a hint to set lid-close to "do nothing" while armed. Sleep and hibernate suspend Gator, and the `[Gator] Online` and stale-message behavior covers that.
- The browser agent in `external` mode and any input simulation are not reachable from remote commands in v1.

### Settings

The "Remote control" section holds per-channel switches (Teams, Slack), the reply switch, a default project, and three limits. Values are saved through `PATCH /api/config` and checked before they are stored.

- `teams_remote_control_enabled`, `slack_remote_control_enabled`: booleans. The existing Teams value is the Teams switch.
- "Reply in my own chat" sits directly under the channel switches and shows "Replies to your own Teams and Slack chat are off until you turn this on." while it is off. It is the user's own auto-send switch, saved through `POST /api/relay/self-chat-autosend` and read from `GET /api/relay`; it is the same setting as "Allow posting to my own Teams and Slack chat" under Agent messaging, and the two stay in step. If the administrator's policy is not `allow`, it is shown off and disabled with "Your administrator has turned this off."
- `remote_default_project`: chosen from a dropdown of existing projects, or left on "Active project". A name that is not a project is rejected on save. If the chosen project is later deleted, a command that needs it is refused with `[Gator] The default project "X" no longer exists. Choose another in Settings, then resend.` and does not fall back to the active project.
- `remote_session_idle_hours` (default 8, 1 to 72), `remote_stale_minutes` (default 15, 1 to 120), `remote_armed_max_hours` (default 24, 1 to 168). Each is read when it is used, so a change applies to running sessions without a restart. A stored value that is not valid falls back to its default.

## Compatibility with the current `/code` path

Until slice 1 ships, the existing `/code <text>` to the active OpenCode terminal keeps working unchanged through the refactor of `teams_remote_control.py`, covered by a regression test. `/code` stays Teams-only and is not extended.

## Agent adapters

Claude Code sessions come first. Completion comes from the agent-state hooks (PR #121): the `idle` state means the turn finished only when it is written after the message was typed (the startup `idle` the agent writes while its prompt is still being typed does not count), and a permission or question state maps to `input-required`. A suspended session is resumed by the wake-on-ping path (PRs #187 and #188) before a message is typed, and the same rules apply: never type at a permission prompt, one pending message per target. OpenCode keeps working as today, using the OpenCode server events attached to the PTY's `opencode attach` target when available, falling back to the PTY tail with ANSI stripped and a quiet period of 4 seconds to detect `idle`. Other generic agents (`web/generic_agent.py`) follow with the PTY fallback, then structured events where they exist.

Agent-initiated messages stay same-project only and go through `web/agent_mcp.py`, the single path that stamps the sender from the per-session `GATOR_AGENT_TOKEN`. Messages the user types in Teams or Slack are the user's own and do not use that path.

## Acceptance criteria

1. With Gator running, the auto-send switch on, the Code tab closed and the screen locked, `@gator what is open?` in the Teams self-chat produces a `[Gator]` reply with the agent's answer in the same chat.
2. The same works from the Slack self-DM.
3. `@gator list`, `@gator status`, `@gator stop` and `@gator <name> <text>` work from both channels.
4. Closing the Code tab does not end a remotely started session. It ends on `@gator stop`, process exit, or the idle limit.
5. A message sent while Gator was off is run once if newer than 15 minutes and skipped with a notice otherwise. A Gator restart never runs the same message twice.
6. Gator posts only into the user's own self-chat, verified before each post and only while the auto-send gate is on, and its own posts never trigger a command, by prefix and by recorded message id.
   6a. A remote session survives a backend restart. `@gator list` shows it under the same short name and `@gator <name> <text>` reaches it. Sessions that have exited are dropped.
   6b. More than 20 commands in 10 minutes are rate limited, `@gator stop all` disarms remote control, and remote control disarms at the absolute cap.
7. Every new mutating route uses `verify_csrf`, and `tests/test_csrf_route_inventory.py` passes with no baseline changes.
8. Opening the Code tab later attaches to the live session and shows its recent output.
9. The existing `/code` OpenCode path still works until slice 1 lands.

## Out of scope

Tailscale or any non-loopback listener, a remote or phone UI, server-hosted agents, bot-style channels, push notifications of our own, widget and dashboard sharing, agent memory or cached results over remote channels, remote approvals of agent permission prompts beyond forwarding the question text.

## Chat tabs

A Gator chat tab is addressed as `@gator <tab name> <text>`. A chat tab cannot run without the open browser window (its history is in browser storage), and `POST /api/chat` has no CSRF check, so the command never calls that route. It is delivered to the tab as a frontend event and queues while the window is closed. This ships after Claude sessions work from Teams and Slack.

## Relationship to cross-agent relay

The cross-agent relay is a separate design. Remote control ships first and is later a channel client of the relay: the relay's terminal adapter wraps `SessionHost`, and the relay's `send`, `get_task`, `cancel` and task status events replace direct session-service calls for agent-to-agent traffic. The seam is the opaque session id, the A2A-named events and the shared guard-rails module.

## Delivery phases

Each slice is its own PR, stacked on the previous one, the first on #188.

0. This spec.
1. Session service, headless pinning, Teams reply path with the loop guard and own-self-chat check, Claude Code adapter, Settings, keep-awake, tests. `/code` regression test.
2. Slack adapter with the same loop guard.
3. Chat tabs, then other generic agents.

## Checks before coding

1. Post to the Teams self-chat and the Slack self-DM from Gator and confirm the phone gets a push notification.
2. Confirm the agent-state hooks (#121) report a finished turn and a waiting-for-user state for Claude.
3. Confirm the Skype client used for polling can post to `48:notes`, and what message id a post returns.
