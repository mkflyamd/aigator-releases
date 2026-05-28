---
name: context
description: "Universal context pinning — pin and unpin items (emails, pages, files, chats) so the agent has persistent, cross-session focus."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# Context

Provides shared, persistent context pinning across all skills. Items pinned from any skill (emails, OneNote pages, SharePoint files, Teams chats, etc.) are stored per tab and survive server restarts.

## When to use

Use this skill when the user wants to pin an item so the agent remembers and focuses on it across turns and sessions, or to unpin items that are no longer relevant.

## Tools available

- `set_pin` — Pin an item (by source, id, and label) to the current context
- `get_pins` — List all currently pinned items for the current context
- `remove_pin` — Unpin a specific item by source and id
- `clear_pins` — Remove all pinned items for the current context

## Rules

- Pins are scoped per tab (context_id) and are persisted to disk; they survive server restarts.
- Always confirm with the user before clearing all pins — this is a destructive operation.
- A pin stores source, id, label, and optional metadata — never store sensitive credential data in pin metadata.
