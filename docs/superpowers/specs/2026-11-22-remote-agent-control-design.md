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
- Pinned sessions are exempt from the viewer-based reaper. A pinned session ends on `stop`, process exit, or after `remote_session_idle_hours` (default 8) with no input or output while it is running. A sleeping lane is not running, so the idle limit never applies to it. The idle-suspend sweep treats them like any other agent terminal (see Lanes).
- A pinned remote terminal is never the project's tracked session, so a local cold open of the project does not reattach to it.
- Opening the Code tab on a pinned session attaches to it and replays `output_buf`, as it does today.
- Restart survival: the PTY host keeps the PTYs running when the backend restarts. At spawn each remote session is labelled on the host with its channel, short name and start time, beside the existing `remote_pinned`, `project_id` and vendor `session_id` labels. After a restart the service rebuilds its sessions from those labels, keeping those of its own channel whose project still exists and whose process has not exited, and the command layer waits for that before running any command. If the host does not answer, nothing is rebuilt and the next poll tries again; this is reported as a host error, never as "no sessions".
- Closing a terminal in the Code tab is refused with an error, and the session left open, when the host cannot be asked whether the terminal is a remote session.

#### Lanes

A project has one lane: its one remote session, never two. A lane is stored in `remote_control_state.json` (project id, vendor session id, short name, last activity, state) and survives a backend restart. Its state is `live`, `sleeping` or `failed`.

- The idle-suspend sweep (`web/agent_suspend.py`) suspends an idle remote terminal like any other: it saves the session id, then closes the process. The lane turns `sleeping`; `list` and `status` say so, and the tick never posts "The agent process exited." for it.
- The next `@gator` message to a sleeping lane answers at once ("Waking up") and wakes the session by its own id through the same resume path as wake-on-ping, in a background task, so polling never waits. A lane wakes at most once at a time and not again within 30 seconds of a failed wake; a message that arrives while it wakes gets a short "still waking" reply and is not queued. The wake reply is "Waking this session. Your message goes in when it is up, so no need to resend." The message is typed once the session takes input. The arm cap and idle expiry apply as for any command: nothing wakes while remote control is off, and a wake that finishes after remote control was turned off sends nothing.
- A wake never starts a fresh session. A failure is reported in the chat and the lane stays asleep to retry. A failure that cannot clear (the stored session or its project is gone) marks the lane `failed`; `stop <name>` clears it, and the next message then starts a new session.
- A session that is live in another terminal (for example resumed in the Code tab), or that someone is typing in or has open in AI Gator, is not woken or typed at; the chat gets a clear reply instead, decided before any "Waking up". The message goes to it through the adopted-peer path when it is one, otherwise the stale lane is dropped and a fresh session starts with a one-line note. Two processes never share one session id.
- After a restart, a newer running terminal for a project never replaces a lane that still has a saved session: the lane is kept, marked `failed`, and one line says so; `stop <name>` clears it. A lane with nothing saved is replaced by the running terminal.
- Claude asks how to resume a large old session (from a summary or in full) before it takes input. Only the dialog's two numbered choices count as that prompt; the same words in prose do not. That prompt is never answered for the user: the terminal is closed again, the lane stays asleep, and the chat says to resume the session once from the Code tab and choose there.
- `stop` and `stop all` close the lane cleanly, sleeping or failed ones included: the saved record is dropped, so nothing is left to resume. Idle expiry closes live lanes only. A sleeping or failed lane stays until `stop`, until remote control is turned off, or until the master switch runs out. Stopping a lane that is waking waits for the wake to end and then closes whatever came up.

`SessionHost` is the interface the service calls for spawn, write, read-output, kill and liveness. `LocalPtyHost` wraps the existing PTY registry. A later server tier adds another host without touching the service or API.

### RemoteApi

One Python interface, mirrored 1:1 by loopback HTTP routes under `/api/remote/`. Every POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]`.

- `GET /api/remote/sessions`, `GET /api/remote/sessions/{id}`, `GET /api/remote/sessions/{id}/output?since=`
- `POST /api/remote/sessions` (start), `POST /api/remote/sessions/{id}/send`, `POST /api/remote/sessions/{id}/stop`
- `GET /api/remote/status`: remote control armed, channels connected, last poll, keep-awake held.

Every call carries a `Principal(channel, identity, scopes)`. Scopes are `read`, `send`, `start`, `stop`. v1 adapters run in-process with the full scope set for the signed-in user. The Principal is the seam for later clients: a non-loopback client (Tailscale, phone UI) gets its own revocable token mapped to a scope set, and the API does not change.

### Command layer

Channel-independent. The grammar is `@gator <command or text>`. A message is a command only if it starts with `@gator` (case-insensitive) followed by whitespace, or if it arrives while the chat window is open (see Chat window). Everything else in the self-chat is an ordinary note and is ignored.

| Message                  | Action                                                                |
| ------------------------ | --------------------------------------------------------------------- |
| `@gator <name> <text>`   | `send` to the session or chat tab with short name `<name>`            |
| `@gator <text>`          | `send`, routed as described below                                     |
| `@gator list`            | sessions and chat tabs with short name, agent, state, age             |
| `@gator status [<name>]` | state and the last agent message                                      |
| `@gator stop [<name>]`   | `stop`                                                                |
| `@gator stop all`        | stop every remote session and disarm remote control                   |
| `@gator hi`              | open the chat window and post the tips (also `hello`, `hey`, `start`) |
| `@gator bye`             | close the chat window                                                 |
| `@gator help`            | the tips                                                              |

`list`, `status`, `stop`, `help`, `bye` and the greeting words (`hi`, `hello`, `hey`, `start`) are reserved words and are never session names. A reserved word on its own, with only trailing punctuation, is a command; inside a longer request it is ordinary text, so `@gator hi there, what changed?` goes to the agent. This is a deliberate change: `@gator hello` used to start a Claude run and now opens the chat window instead. If the first word after `@gator` is not a reserved word and not a known short name, the text is routed as below. A leading `@name` that is not `@gator` routes to a known session; an unknown one is not a command, gets no reply and is not sent to the agent. Only `@gator` is a command tag.

Routing of a message that names no session, tagged or untagged: it goes to the one session that is waiting for an answer, if exactly one is. Otherwise it goes to the only running session. With no session running, a new one starts in the default project. With several running and none or several waiting, Gator replies `Which session?` with the names as options. `<name> <text>` and `<name>: <text>` always pick that session. Before this change an unnamed message always went to the default project's session, so a tagged message now reaches a session in another project when it is the only one running or the only one waiting.

Short names are the addressing scheme. A session is named after its project (`budget`), with `-2`, `-3` added when a project has more than one live session (`budget-2`). A Gator chat tab is addressed by its tab name, in the same namespace. If a tab name collides with a session short name, the command is refused with the list. The default project is a Settings value (`remote_default_project`), falling back to the active project.

Input is trimmed, capped at 4096 bytes and sent as one line plus Enter.

#### Chat window

`@gator hi` opens a window, per channel, in which untagged messages in the own chat are treated as if they started with `@gator`. Gator answers with the greeting and tips: how to type a request, `list`, `status`, `stop all`, `bye`, and that the chat closes after 30 minutes of quiet. `help` posts the same under a new prefix without the crocodile and without "Gator on watch." (when the chat is closed it explains `@gator hi` and `@gator <request>` instead). `@gator hi` while the chat is open replies `This chat is already open.` and extends the window. An untagged `hi` does the same.

- Only the greeting opens the window. A tagged request never opens it, so personal notes in the self-chat do not turn into commands by accident.
- The window slides. Every command, tagged or untagged, moves its end to 30 minutes after that command. `status` and `list` count.
- The window is held while any session is running a turn or shows a prompt (for at most two hours each) and closes 30 minutes after the last result. `allow`, `deny` and a number still work as a quote-reply to the prompt message once it is closed.
- It closes on `bye`, on `stop all`, when remote control is switched off or disarmed, when the absolute cap fires, and after 30 minutes of quiet. `stop [name]` stops one session and leaves the chat open.
- Expiry is checked when a message arrives and on each tick. The first check that finds it expired posts one `Chat closed after 30 minutes of quiet.` notice, with the crocodile. Closing by `bye`, `stop all`, switching off or the cap is silent apart from that command's own reply.
- The window is stored in `~/.gator/remote_control_state.json` under the channel as `window: {opened_at, until}`. After a restart an open window continues and an expired one stays closed without a notice. Nothing is run again on restart: the last processed id still applies.
- An untagged message only counts if its own timestamp is at or after the greeting's, so messages that were already in the chat, or arrive late, never run. A message with no timestamp (the adapter reports 0.0) is never run untagged; a tagged one still runs.
- The self-chat is often a notepad, so the greeting says everything typed in the window goes to the agent, and an untagged message over 1,500 characters (`UNTAGGED_MAX_CHARS`) or with an attachment is not sent. A too-long message gets `Not sent: over 1500 characters.` every time, with `Add @gator to send up to 4096.`; the attachment line is posted once per window. A tagged `@gator` message is exempt from the cap, and a held-back message does not slide the window.
- Slack messages count only when the user typed them: the sender must be the signed-in user and the message must carry no `bot_id` or `app_id`, so other integrations posting with the user's token are not read as the user. If Gator cannot tell who the user is it reads nothing. Messages whose id Gator recorded as its own post are skipped on both channels.
- Untagged text that starts with `[🐊` is never read, the same as everywhere else, and untagged text that matches the older `/code` relay pattern (the compiled pattern in `teams_remote_control.py`, imported and not copied) is left to that relay: it is not run and not answered.
- Every post the window makes (tips, closed notice, bye, replies to untagged messages) goes through the auto-send gate. With the gate off the window and commands still work and nothing is posted.

#### Copy

The wording of every message is the copy deck (`REMOTE-CONTROL-CHAT-COPY.md` in the design repo); `commands.py` implements it and tests compare the two. The rules the code enforces:

- App notices start with `[🐊 Gator]` and agent replies with `[🐊 Gator - <project>]` (`[🐊 Gator - <session> - <project>]` while more than one session is live). The project slot is always present: it is the only visual tell between the two voices. The prefix is built in the command layer from one getter, `remote.settings.agent_name()`; the loop guard, both adapters and every notice use it, and a test fails if any other module spells it out or any notice lacks it.
- One crocodile, inside the opening bracket of every message. No exclamation marks, no bold, no other emoji. The only wordplay is `Gator on watch.` and `Gator out.`.
- The name in the prefix is the `remote_agent_name` setting, default `Gator`. It has no Settings field. A value that is not 1 to 20 characters, or that holds `[`, `]` or a line break, is refused on save and falls back to `Gator` when read.
- A notice ends with a `Next:` block of one to three `•` options, typed options in backticks. An agent reply carries one only when it has useful options. A quick answer is the prefix and the words only; a turn over about 15 seconds gets one `Working on it.` with a `Branch:` line, `Still working, N min.` at most every 2 minutes, and `Done in N min` past a minute. The greeting and `help` carry five options and a closing line about the 30 minutes, as the deck has them.
- Line breaks are real: Teams gets `<br>` from the adapter, Slack gets newlines. A test sends a multi-line crocodile message through both adapters.
- Limits and waits are written in words (`24 hours`, `10 minutes`). A session name typed by the user is echoed back as one line capped at 40 characters. The timeout notice names the Settings section `Remote control`, and a test compares that with the section label in the page.
- After `stop all` the guard is disarmed, so the stop-all reply says Remote control is off and tells the user to open AI Gator and turn it on again. There is no chat option to restart.
- `status [name]` replies `<state> since <time>` and `Last activity <time>`. Options use the session short name, which the prefix's project slot shows, because the agent name is not an address.

The command layer posts a reply when a session emits `completed` (agent finished its turn) or `input-required` (agent is asking the user something), containing the agent's last message with its line breaks. Tool-by-tool progress is not posted:

- Done: `Done.` then the reply. Waiting: `Waiting for your answer.` then the question. When the question ends in two short, safe numbered or lettered choices, those become the first two options; a choice that would parse as a command is never offered.
- No text read back: `Done. No text came back. Open the <agent> tab in AI Gator.` A bare `Done.` is never sent.
- Process exited: `The agent process exited.` Stopped: `Stopped.`
- A reply is never cut. Over 3,500 characters it goes out in order as several messages, each with the normal prefix and `(1/3)` ending its first line. Each part is cut at a paragraph boundary in the last half of the 3,500 characters (else at a line, else at whitespace, never inside a word), and a code fence left open by a cut is closed and opened again in the next part. A question's choices go on the last part only. Only a reply past 60,000 characters stops, and its last part says so and points to the agent's tab. Slack recommends at most 4,000 characters in `text` and Teams allows about 100 KB, so each part stays within both.

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

- The gate is `relay.settings.self_chat_autosend_allowed()`: the administrator's `self_chat_autosend` policy must be `allow` and the user's own switch must be on. The switch is off for everyone until they turn it on, including users who already switched Teams or Slack remote control on. Every adapter calls the gate right before it sends, so every Gator post is covered: replies, `[🐊 Gator] Online`, notices and agent output. With the gate off nothing is posted, nothing is queued for later, and commands still run. The runner logs this once per arming period.
- Before every post the adapter verifies the recipient is the user's own self-chat: Teams chat id `48:notes`, or the Slack DM channel whose other member is the signed-in user. If the check fails or cannot be made, nothing is posted.
- Every post starts with `[🐊` and never starts with `@gator`, so an agent's output cannot form a command when it is echoed.
- Loop guard: replies land in the same chat the poller reads, so the poller must never treat Gator's own posts as commands. It keys on the marker, not the name: it ignores any message that starts with `[🐊` or `[:crocodile:` (Slack may return the emoji as a shortcode), whatever the configured name, plus the older `[Gator` and `[` up to 80 characters `] 🐊` shapes so earlier posts stay ignored. It also ignores any message whose id is one Gator recorded when posting (the ids are kept in `~/.gator/remote_control_state.json`). Either check alone is enough to drop the message.
- The text after `@gator` is the user's own instruction. A message relayed from another agent is a suggestion and is never executed by this layer.

### Delivery guarantees

- Restart and connection. A prompt message is recorded by (session, prompt id) and a restart never posts it again. When the sessions are restored Gator posts one line, `Gator restarted: X running, Y asleep.`, and a turn that finished while it was down still posts its result. A failed poll stores its reason: `GET /api/remote/status` then reports `connection_failed` with `Cannot reach Teams: <reason>`, and once the chat answers again one `Back online.` line names how long it was out and why.
- At-most-once. The adapter persists the last processed message id and records intent before writing to a PTY, in `~/.gator/remote_control_state.json`. A restart neither replays nor silently skips.
- Staleness. A message older than `remote_stale_minutes` (default 15) at pickup is not run. Gator posts `[🐊 Gator] Not sent: N messages you sent while AI Gator was off, because they were more than 15 minutes old. Send them again if you still need them.` Messages inside the limit run once.
- Liveness. Once per backend start, and only while the chat window is closed, Gator posts `[🐊 Gator] Online`. Failures it can report (no live session, expired token, agent exited, unknown name) get an immediate reply naming the reason. Replies with `[🐊 Gator]` are the only signal the user needs: no reply within a minute of a command means Gator is offline.
- Poll cadence: 3 seconds while a session is active or a command arrived in the last 180 seconds, otherwise 10 seconds.
- Inbound rate limit: at most 20 commands per 10 minutes per channel. Excess commands get `[🐊 Gator] Not sent: too many messages at once.` with the real wait in words, and are dropped. Stopping and answering a prompt are exempt. Every dropped command says `Not sent`.
- Absolute cap: remote control runs in one 12 hour window shared by Teams and Slack, fixed in code and not a setting. The window opens when remote control is switched on (`POST /api/remote/arm`, or turning a channel switch on) and its deadline is stored as a wall-clock time, so a restart neither extends nor reopens it and a clock moved backwards counts as expired. Switching on while a window is running does not extend it. About 15 minutes before the deadline each channel posts one "Remote control turns off in 15 minutes." notice (`commands.turns_off_soon`). At the deadline every remote session is stopped the same way `stop all` stops them, a session that will not stop is retried every tick, and only then does the channel post "Remote control turned itself off after 12 hours." once (`commands.timed_out`). After the deadline no command runs, and the first command that arrives gets one "Remote control timed out after 12 hours." reply (`commands.timed_out_reply`); a switch that is on with no window ever opened gets "Remote control is not turned on." (`commands.not_armed`) once instead; the idle limit still stops idle sessions. `GET /api/remote/status` reports the state, `POST /api/remote/arm`, `/restart` and `/disarm` change it; `/restart` closes and reopens the window in one call and is refused, leaving the current window open, whenever arm would be refused.
- Expiry, rate limit and stop-all live in one guard-rails module that the cross-agent relay shares. Components depend on its small interface (expiry timer, sliding-window rate limit, stop-all registry), not on where the module lives.

### Headless and power behavior

- No UI is needed. Nothing navigates on the physical screen. A locked screen does not affect the backend, the PTY or the chat polls.
- While remote control is armed and a pinned session is live, Gator holds `ES_SYSTEM_REQUIRED` from a dedicated thread (the call is per-thread). Armed with no live session releases it.
- Settings shows a hint to set lid-close to "do nothing" while armed. Sleep and hibernate suspend Gator, and the `[🐊 Gator] Online` and stale-message behavior covers that.
- The browser agent in `external` mode and any input simulation are not reachable from remote commands in v1.

### Settings

The "Remote control" section holds per-channel switches (Teams, Slack), the reply switch, a default project, and three limits. Values are saved through `PATCH /api/config` and checked before they are stored.

- `teams_remote_control_enabled`, `slack_remote_control_enabled`: booleans. The existing Teams value is the Teams switch.
- "Reply in my own chat" sits directly under the channel switches and shows "Replies to your own Teams and Slack chat are off until you turn this on." while it is off. It is the user's own auto-send switch, saved through `POST /api/relay/self-chat-autosend` and read from `GET /api/relay`; it is the same setting as "Allow posting to my own Teams and Slack chat" under Agent messaging, and the two stay in step. If the administrator's policy is not `allow`, it is shown off and disabled with "Your administrator has turned this off."
- `remote_default_project`: chosen from a dropdown of existing projects, or left on "Active project". A name that is not a project is rejected on save. If the chosen project is later deleted, a command that needs it is refused with `[🐊 Gator] The default project "X" no longer exists. Choose another in Settings, then resend.` and does not fall back to the active project.
- `remote_session_idle_hours` (default 8, 1 to 72), `remote_stale_minutes` (default 15, 1 to 120), `remote_peer_messages_per_hour` (default 30, whole number 0 to 1000; 0 means no limit; see Messaging other agents). Each is read when it is used, so a change applies to running sessions without a restart. A stored value that is not valid falls back to its default.

## Compatibility with the current `/code` path

Until slice 1 ships, the existing `/code <text>` to the active OpenCode terminal keeps working unchanged through the refactor of `teams_remote_control.py`, covered by a regression test. `/code` stays Teams-only and is not extended.

## Agent adapters

Claude Code sessions come first. Completion comes from the agent-state hooks (PR #121): the `idle` state means the turn finished only when it is written after the message was typed (the startup `idle` the agent writes while its prompt is still being typed does not count), and a permission or question state maps to `input-required`. A suspended session is resumed by the wake-on-ping path (PRs #187 and #188) before a message is typed, and the same rules apply: never type at a permission prompt, one pending message per target. OpenCode keeps working as today, using the OpenCode server events attached to the PTY's `opencode attach` target when available, falling back to the PTY tail with ANSI stripped and a quiet period of 4 seconds to detect `idle`. Other generic agents (`web/generic_agent.py`) follow with the PTY fallback, then structured events where they exist.

Agent-initiated messages stay same-project only and go through `web/agent_mcp.py`, the single path that stamps the sender from the per-session `GATOR_AGENT_TOKEN`. Messages the user types in Teams or Slack are the user's own and do not use that path.

## Acceptance criteria

1. With Gator running, the auto-send switch on, the Code tab closed and the screen locked, `@gator what is open?` in the Teams self-chat produces a `[🐊 Gator - {project}]` reply with the agent's answer in the same chat.
2. The same works from the Slack self-DM.
3. `@gator list`, `@gator status`, `@gator stop` and `@gator <name> <text>` work from both channels.
4. Closing the Code tab does not end a remotely started session. It ends on `@gator stop`, process exit, or the idle limit while it is running.
5. A message sent while Gator was off is run once if newer than 15 minutes and skipped with a notice otherwise. A Gator restart never runs the same message twice.
6. Gator posts only into the user's own self-chat, verified before each post and only while the auto-send gate is on, and its own posts never trigger a command, by prefix and by recorded message id.
   6a. A remote session survives a backend restart. `@gator list` shows it under the same short name and `@gator <name> <text>` reaches it. Sessions that have exited are dropped.
   6b. More than 20 commands in 10 minutes are rate limited, `@gator stop all` disarms remote control, and remote control disarms at the absolute cap.
   6c. An idle remote session is suspended to free memory and the next `@gator` message wakes it by session id, with an immediate acknowledgement, without starting a second session and without blocking the polling loop. `list` and `status` show it as sleeping.
7. Every new mutating route uses `verify_csrf`, and `tests/test_csrf_route_inventory.py` passes with no baseline changes.
8. Opening the Code tab later attaches to the live session and shows its recent output.
9. The existing `/code` OpenCode path still works until slice 1 lands.

## Out of scope

Tailscale or any non-loopback listener, a remote or phone UI, server-hosted agents, bot-style channels, push notifications of our own, widget and dashboard sharing, agent memory or cached results over remote channels, approving prompts that need the app (see Needs-you prompts).

## Messaging other agents

`@gator <name> <text>` reaches another agent session in the default project, such as a session working in a branch or a review session, live or suspended. `@gator list` shows them under the sessions Remote started, at most 8 with "N more". The tag is required: a message to a peer without `@gator` is never routed, and the window does not stick to a peer.

- Reachable means: same project as the default project, not started by Remote, and not opted out in Relay. No per-session opt-in. Other projects are not reachable. When the administrator or user messaging switch is off, a message to an agent is refused with that reason.
- The name is matched exactly (case-insensitive) against the session title, or the full or 8-character session id. `gator`, `all` and the command words are reserved and never match a peer. Two peers with the same name get a reply listing the 8-character ids to use instead.
- The text is typed into the peer as the user's own words, prefixed `[via remote chat from the user]`, through the wake-on-ping path: a suspended session is woken first, nothing is typed at a permission prompt, while the user is typing, or when the session is in a permission mode that skips approvals (bypass or auto-accept). A permission mode that cannot be read is treated as one that skips approvals.
- Sends are counted per peer per hour against `remote_peer_messages_per_hour`, separately from Relay's agent-to-agent limit, which a person typing in chat does not use. Each delivery is written to the same audit log as agent messages.

### Replies from another agent

After a message is delivered, Remote watches that session for one answer and posts it back to the chat as `[🐊 <name> - <project>] <reply>`, under the agent's own name rather than Gator's. A peer whose name is the agent's own name is shown as `<name> (other agent)`. Only the turn that follows the message is posted: the agent's earlier turns and its own idle events are not. A question the agent asks is posted with its name and how to answer it (`@gator <name> <answer>`). If the session closes before answering, the chat is told once.

- The reply is read through the same redaction as Remote's own replies and trimmed at the same length. The name is shown on one line with brackets replaced, so it cannot end the prefix early.
- The prefix starts with the crocodile marker, so the loop guard ignores it and a reply can never start a command.
- Watching is not owning. The session is held apart from the ones Remote started: it does not appear in `list` as a Remote session, `stop` and `stop all` never reach it, the idle limit only stops watching, and the terminal host refuses to close any session that was not started by this channel. A backend restart forgets what was being watched.

## Needs-you prompts

While Remote is armed, an agent waiting on a permission or a question reaches the user's own self-chat, and the reply is typed into the agent from there. This covers three kinds of session: the lane and sessions Remote started, other agents Remote has messaged and watches, and AI Gator terminals Remote did not start (only terminals of the user's own projects).

- One message per prompt, posted at once for a session started from chat and after about 2 minutes for the others, at most 3 at a time with a summary line for the rest. The text is the same for every kind of session: redacted, capped, numbered options for a question, `allow` and `deny` for a permission. The label is the project for a terminal Remote did not start and the agent's name for a watched peer.
- A permission is answered by Enter only for Bash, Edit and Write. Multi-select, several questions, ExitPlanMode and MCP tools stay app-only and say `Open AI Gator`, and also offer `esc`.
- `esc` (or `escape`, optionally with a session name, or as a quote-reply) cancels the prompt a session is showing and ends its turn without closing the session. It passes the same checks as an answer, so it types nothing when the prompt is gone or the user typed in the terminal. With several sessions waiting and no name, Remote asks which one.
- A reply to a question that is not one of its numbered options is typed as the question's own answer (up to 500 characters). Only single-question prompts take this, and a watched session's question does not take ordinary chat as its answer.
- A reply to a permission that is not `allow`, `deny` or a number is not sent, and the options are shown again.
- A reply is typed only when all of these hold: it was written after the prompt was first seen (a reply sent before is told "that was for an earlier question"); the prompt file is still the same prompt and the agent is still asking; the terminal still shows that dialog; and the user has not typed in the terminal since the prompt appeared. Otherwise nothing is typed and the chat says it was already answered.
- A quoted reply is answered only when the quoted message is the prompt currently showing; a quote of an earlier prompt is told it was already answered and skips nothing. An unquoted `allow`, `deny` or number answers the one session that is waiting; when several wait, Remote asks which one and types nothing, and the user quotes the message of the one meant.
- A terminal answered from chat is not posted again until it writes a new state.
- Every refusal ends with one step that can work. A refusal that cannot change by waiting (the session is open elsewhere, set to run without asking, switched off) never says to send it again; a transient one (busy, not ready) does.

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
