---
name: m365-onenote
description: 'Browse, create and edit notebooks, sections, and pages in Microsoft OneNote via the Graph API.'
metadata:
  author: AI Gator
  version: '1.0'
  format: agentskills-1.0
---

# M365 OneNote

Access and create content in Microsoft OneNote using the Microsoft Graph API. Supports listing notebooks, sections, and pages, reading page content, creating notebooks, sections and pages, and editing pages.

## When to use

Use this skill when the user wants to browse their OneNote notebooks, read a page, or create a new note or meeting summary in OneNote.

## Tools available

- `list_onenote_notebooks`, `find_onenote_notebook` — List or find notebooks (personal and SharePoint team)
- `list_onenote_sections`, `list_onenote_pages` — List sections in a notebook and pages in a section
- `read_onenote_page` — Read a page, or its editable elements
- `create_onenote_notebook`, `create_onenote_section` — Create a notebook, or a section in a notebook. A new notebook has no sections: create a section before creating pages
- `create_onenote_page` — Create a page in a section with a title and body (text or HTML)
- `update_onenote_page` — Append, insert, replace or rename content on an existing page
- `pin_onenote_page` — Pin a page for quick reference

For notebooks on a SharePoint team site, pass the notebook's `site_id` to every call.

## Rules

- Requires Microsoft 365 authentication — prompt the user to sign in via Settings → Apps → Microsoft 365 if not authenticated.
- When creating a page, confirm the target notebook and section with the user before writing. If the user asks for a new notebook or section, create it with the create tools; do not ask the user to make it in the OneNote app.
- Page content can be plain text or HTML; use HTML only when the user explicitly requests formatting.
