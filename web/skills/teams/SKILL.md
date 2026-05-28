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
| `read_teams_chats` | Read user chats and messages | `Chat.Read`, `ChatMessage.Read` |
| `read_channel_messages` | Read channel messages | `ChannelMessage.Read.All` |
| `send_teams_message` / `teams_open_compose` | Send chat messages | `ChatMessage.Send` |
| `list_teams` | List joined teams | `Team.ReadBasic.All` |
| Create new 1:1/group chats | Create chats (optional — falls back to scanning existing chats) | `Chat.Create` |

**Token source:** Teams tools use a browser-captured token (stored in `~/.config/microsoft-graph/teams_token.json`) rather than the device code OAuth token. This is because Teams chat scopes (`Chat.Read`, `ChatMessage.Send`) require consent that the device code flow may not grant in all tenant configurations.

**How to capture:** Open teams.microsoft.com in a browser, open DevTools (F12) → Network tab, find any Graph API request, copy the `Authorization: Bearer ...` header value, and paste it in Settings → Teams token.
