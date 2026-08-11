---
name: teams
description: "Microsoft Teams — read chats, send messages, browse channels."
metadata:
  author: Mayuresh Kulkarni
  version: "1.0"
  format: agentskills-1.0
---

# Teams Messaging Workflow

## Composing Messages — Confirm Before Acting

Before calling send_teams_message or teams_open_compose, you MUST:
1. **Confirm WHO** — Resolve recipients via search_people if needed. Show the resolved names/emails to the user. If you have a chat_id, mention the chat topic so the user knows the target.
2. **Confirm WHERE** — Teams (not email/Slack). If ambiguous, ask "Should I send this via Teams or email?"
3. **Confirm WHAT** — Show the draft message. Let the user approve or refine before opening compose.

When calling the compose tool:
- Pass real email addresses in `to` (e.g. `john.doe@amd.com`), NEVER use `placeholder` or fake values.
- If you only have a `chat_id` and no emails, pass `chat_id` and leave `to` empty — the UI resolves recipients from the chat.
- Always pass `chat_topic` when you have it — helps the user confirm the target.

## General Rules

- To DM someone → resolve their email via search_people first, then call send_teams_message.
- To browse teams/channels → call list_teams to get team IDs.
- **#channel vs chat**: When the user mentions a `#channel` chip, ALWAYS call `read_channel_messages` (not `read_teams_chats`). `read_teams_chats` is only for 1:1 or group DMs. Never use `read_teams_chats` when a channel chip is active.
- **Mention detection**: When asked "any mentions of me?" or "any action items for me?", the tool results include the current user's display name in the `current_user` field. Scan ALL returned messages for that name (first name, last name, or display name in any order) and flag any message containing it — even if it is not an @mention tag.

## Required Permissions

| Tool | Delegated Permission | Scope |
|---|---|---|
| `read_teams_chats` | Read user chats and messages | `Chat.Read`, `ChatMessage.Read` (via FOCI→Skype swap) |
| `read_channel_messages` | Read channel messages | `ChannelMessage.Read.All` |
| `send_teams_message` / `teams_open_compose` | Send chat messages | `ChatMessage.Send` (via FOCI→Skype swap) |
| `list_teams` | List joined teams | `Team.ReadBasic.All` |
| Create new 1:1/group chats | Create chats (optional — falls back to scanning existing chats) | `Chat.Create` |
| `markChatReadForUser` / `markChatUnreadForUser` | Mark chat read/unread state | `Chat.ReadWrite` (browser-captured token only) |

**Token sources:** Teams chat tools (read, send, edit, members, list) use the
same FOCI token as the rest of M365 (`~/.config/microsoft-graph/token.json`,
client `1fec8e78`) via a FOCI→Skype token swap. Sign in once via Settings →
Apps → Microsoft 365 (device-code flow). The token auto-renews via refresh_token.

Only `markChatReadForUser` / `markChatUnreadForUser` require the separate
`Chat.ReadWrite` scope, which FOCI cannot grant. That scope comes from a
browser-captured token (`~/.config/microsoft-graph/teams_token.json`) that
expires in ~1h with no refresh_token. All other Teams features keep working
when that token expires — only mark-read/unread degrades.

**If a Teams tool returns an auth error:** tell the user "Your Microsoft 365
session has expired — sign in again via Settings → Apps → Microsoft 365."
Do NOT instruct the user to open DevTools, copy Bearer tokens, or paste
anything manually. The in-pane overlay (Electron) auto-prompts recapture for
the narrow `Chat.ReadWrite` token when needed; everything else uses the M365 sign-in.
