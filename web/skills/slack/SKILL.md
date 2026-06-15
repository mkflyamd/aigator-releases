---
name: slack
description: "Slack — search messages, read channels/threads, send messages, manage canvases via official Slack MCP."
metadata:
  author: Mayuresh Kulkarni
  version: "2.0"
  format: agentskills-1.0
---

# Slack Skill — Official Slack MCP

Connected to the official Slack MCP server (mcp.slack.com). User authenticates via OAuth in Settings.

## Error Handling

- If a tool returns an error and Slack was NOT the user's focus, silently ignore it.
- If the user explicitly asked about Slack, briefly note it is temporarily unreachable.
- NEVER say "Slack token expired", "reconnect Slack", or "go to Settings for Slack".

## How to Find Messages

**To find messages from a specific person in a channel:**
1. Use `slack_search_public_and_private` with query `from:@PersonName in:#channel-name`
2. If no results, try `slack_read_channel` with the channel_id to browse recent messages

**To find a specific channel:**
1. Use `slack_search_channels` with the channel name as query
2. Include `channel_types: "public_channel,private_channel"` to find private channels too
3. The result gives you the channel ID needed for other tools

**To read channel messages:**
1. First find the channel ID via `slack_search_channels`
2. Then use `slack_read_channel` with that channel_id
3. Use `oldest` and `latest` params (Unix timestamps) to filter by time range

**Time range queries — IMPORTANT:**
When the user says "last N hours", "past 2 days", "since Monday", etc., you MUST compute a Unix timestamp and pass it as the `oldest` parameter. The current Unix timestamp is in the system prompt — use it for arithmetic:
- "last 40 hours" → `oldest = current_unix_ts - (40 * 3600)`
- "past 3 days" → `oldest = current_unix_ts - (3 * 86400)`
- "since Monday" → compute Monday's midnight as Unix timestamp

NEVER call `slack_read_channel` without `oldest` when the user specifies a time range — without it you'll get the most recent N messages which may be months old in quiet channels.

**To read a thread:**
1. You need `channel_id` AND `message_ts` (the parent message timestamp)
2. Use `slack_read_thread` with both

**Slack search syntax (for query param):**
- `from:@username` — messages from a specific user
- `in:#channel` — messages in a specific channel
- `has:link` — messages with links
- `before:2026-05-01` / `after:2026-04-01` — date filters
- Combine: `from:@piotr in:#ext-amd-liquid-ai after:2026-04-01`

## Sending Messages

- `slack_send_message` creates a DRAFT for user approval (human-in-the-loop).
- To DM a user, pass their user_id as channel_id.
- Use `slack_search_users` to find a user's ID first.

## Display Names

- Slack mentions like `<@UXXXX|Name>` contain the display name after the pipe — use "Name" not the ID.
- Use `slack_search_users` to look up users by name, email, or profile.
- Use `slack_read_user_profile` with a user_id for detailed profile info.

## Canvases

- `slack_create_canvas` — create formatted documents (Canvas-flavored Markdown)
- `slack_read_canvas` — read existing canvases
- `slack_update_canvas` — append, prepend, or replace content (CAUTION: replace without section_id replaces ENTIRE canvas)

## Tool Chaining Patterns

**"Catch me up on #channel" / "What happened in #channel in the last N hours?"**
This is the most common request. You MUST use BOTH approaches because thread replies are invisible to `read_channel`:

1. Find the channel ID via `slack_search_channels`
2. Compute `oldest` = current_unix_ts − (N × 3600) for hours, or (N × 86400) for days
3. Use `response_format: "concise"` on `slack_read_thread` calls to save tokens. Use `"detailed"` (default) on `read_channel` and `search` calls so you get thread metadata (`reply_count`, `thread_ts`, `latest_reply`).

**Step A — Search for ALL activity (catches thread replies):**
4. Call `slack_search_public_and_private` with `in:#channel-name`, `after: oldest_timestamp`, `sort: "timestamp"`, `sort_dir: "desc"`, `limit: 20`. This returns BOTH top-level messages AND thread replies posted in the time window — even if the parent message is months old.

**Step B — Two-pass read of top-level messages:**
5. Call `slack_read_channel` with `channel_id`, `oldest`, `limit: 100` — gets new top-level messages.
6. Call `slack_read_channel` with `channel_id`, `limit: 30` (NO oldest filter) — gets recent root messages that may have threads with new replies even if the root message is older than the time window.

**Step C — Expand ALL active threads (do not skip any):**
7. From ALL results (search + both reads), collect EVERY message with `reply_count > 0` or `thread_ts`. Call `slack_read_thread` with `channel_id`, parent `message_ts`, `response_format: "concise"` for EACH one. Do NOT stop after one or two threads — expand them ALL. This is where most activity lives in busy channels.
8. For large threads, use the `cursor` parameter to paginate and get all recent replies.

**Step D — Combine and summarize:**
9. Merge top-level messages + thread replies into a unified chronological summary. Clearly indicate which activity was in a thread vs top-level.
10. If ALL calls return 0 results, say "No new messages in the last N hours" — do NOT fall back to showing older messages.

**"What did X say in #channel?"**
→ `slack_search_public_and_private` with `from:@X in:#channel`

**"Summarize #channel"**
→ Same as "Catch me up" pattern above — always include thread replies

**"Send a message to @person"**
→ `slack_search_users` to get user_id → `slack_send_message` with user_id as channel_id

**"List my channels"**
→ `slack_search_channels` with empty query and `channel_types: "public_channel,private_channel"`
