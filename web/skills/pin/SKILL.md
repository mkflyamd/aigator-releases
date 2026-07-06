---
name: pin
description: "Pin a Jira issue, Confluence page, or OneDrive file to the current tab by describing it."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# Pin

Lets the user pin an item to the current tab by describing it in chat, instead of finding it in the side pane and clicking the pin button. It finds the item via the provider's own search — the same call the UI makes — then pins it with the exact id the UI uses, so an item pinned this way also shows as pinned when the user later navigates to it.

## When to use

- "pin the auth design doc" / "pin my Q3 planning spreadsheet" / "pin PROJ-123 to this tab"
- Any request to pin a Jira issue, Confluence page, or OneDrive file by name/keywords/key

## Tools available

- `pin_item` — search the given `source` (`jira`, `confluence`, `onedrive`) for `query` and pin the match to the current tab.

## Rules

- **Auto-pin only on a confident match** — exactly one result, or one whose key/title matches the query exactly. Otherwise the tool returns `candidates`; ask the user which one, then call again with a more specific query (e.g. the exact title or Jira key).
- Pins are scoped to the **current tab** (`_context_id`, injected automatically). To pin to a different tab, the user switches tabs first.
- This tool does not parse URLs — always go through search so the pinned id matches the UI's.
- For other sources (Teams chats, emails, OneNote), pinning is still done from the UI / their own pin tools.
