---
name: tabs
description: "Query pinned items across tabs by tab name or current-tab context."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# Tabs

Lets the agent inspect what is pinned to a particular tab (customer/program) — either the current tab or another by name.

## When to use

- The user asks about pinned items, e.g. "what's pinned here?", "show me the Fireworks pins"
- A scheduled run needs to enumerate the pins for its bound tab without relying on auto-injection
- A cross-tab query: "compare the OneDrive files pinned to Fireworks vs Liquid AI"

## Tools available

- `get_tab_pins` — return the pinned items for a tab. Accepts `tab_name` or `tab_context_id`; defaults to the current tab. Optional `type` filter restricts to a single pin source (e.g. `teams_chat`, `confluence_page`).

## Rules

- Pin metadata only — this tool does not fetch the underlying resource content. Follow up with the appropriate read tool (e.g. `read_email`, `get_confluence_page`) when content is needed.
- Pins that point at deleted or no-longer-accessible resources are returned with a `status` field (`ok` / `missing` / `forbidden`) — do not silently drop them.
- The current tab is the default — only specify `tab_name`/`tab_context_id` for cross-tab queries.
