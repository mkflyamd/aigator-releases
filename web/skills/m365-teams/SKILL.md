---
name: m365-teams
description: "Read Teams chats and channels, list teams and members, and send chat messages via the Teams/Graph API."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# M365 Teams

Access Microsoft Teams chats, channels, and messages using the Teams internal messaging API (FOCI/Skype token) and the Microsoft Graph API. Supports listing teams, channels, reading chat messages, and sending 1:1 chat messages.

## When to use

Use this skill when the user wants to read Teams messages, check a conversation, list their teams or channels, or send a message to a coworker via Teams chat.

## Tools available

- `list_teams` — List all Teams the current user belongs to
- `list_channels` — List channels in a specific team
- `read_chats` — List recent chat conversations or read messages from a specific chat
- `send_chat` — Send a 1:1 chat message to a user by email or to an existing chat by ID
- `get_meeting_transcript_full` — Fetch full transcript text (drive_id, item_id, transcript_id; small transcripts only)
- `get_meeting_transcript_header` — Duration, speakers with talk-time %, preview (use first for large transcripts)
- `get_meeting_transcript_range` — Time-bounded slice of a transcript
- `search_meeting_transcript` — Substring search over cues with context
- `get_meeting_transcript_speaker` — All utterances by a single speaker

## Rules

- Requires Microsoft 365 authentication — prompt the user to sign in via Settings if not authenticated.
- Never send messages automatically — always show a draft and require explicit user approval before sending.
- Use the Skype token (FOCI swap) for reading chat history; use Graph API for sending messages to channel threads.
- Do not include raw Skype MRIs or internal token values in responses shown to the user.
- For transcripts above the configured token threshold, always call `get_meeting_transcript_header` first and use chunked tools — never request the full body in one call.
- Transcript tools take `drive_id`, `item_id`, and `transcript_id` as a triple — get all three from the pinned context block; do not invent or guess them.
