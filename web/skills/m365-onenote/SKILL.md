---
name: m365-onenote
description: "Browse notebooks, sections, and pages in Microsoft OneNote and create new pages via the Graph API."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# M365 OneNote

Access and create content in Microsoft OneNote using the Microsoft Graph API. Supports listing notebooks, sections, and pages, reading page content, and creating new pages with text or HTML.

## When to use

Use this skill when the user wants to browse their OneNote notebooks, read a page, or create a new note or meeting summary in OneNote.

## Tools available

- `list_notebooks` — List all OneNote notebooks
- `list_sections` — List sections within a notebook
- `list_pages` — List pages within a section
- `get_page` — Read the content of a specific page
- `create_page` — Create a new page in a section with a title and body (text or HTML)

## Rules

- Requires Microsoft 365 authentication — prompt the user to sign in via Settings if not authenticated.
- When creating a page, confirm the target notebook and section with the user before writing.
- Page content can be plain text or HTML; use HTML only when the user explicitly requests formatting.
