---
name: onenote
description: "Microsoft OneNote — read, create, update pages, navigate notebooks and sections."
metadata:
  author: Mayuresh Kulkarni
  version: "1.0"
  format: agentskills-1.0
---

# OneNote Workflow

- "Create a page" → call list_onenote_notebooks to find the right notebook, then list_onenote_sections to get the section_id, then create_onenote_page.
- "Show my notebooks / sections / pages" → call list_onenote_notebooks → list_onenote_sections → list_onenote_pages as needed.
- "Update a page" → if the page is pinned, use update_onenote_page directly with the pinned page_id. If not pinned, navigate to find the page_id first, then call update_onenote_page.
- "Pin this page" → after finding a page, call pin_onenote_page so the user can reference it by name in future messages without re-navigating.
- When a page is pinned, ALWAYS use update_onenote_page directly — NEVER re-navigate through notebooks/sections.
