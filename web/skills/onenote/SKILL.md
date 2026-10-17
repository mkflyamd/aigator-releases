---
name: onenote
description: 'Microsoft OneNote — read, create, update pages, navigate notebooks and sections.'
metadata:
  author: Mayuresh Kulkarni
  version: '1.0'
  format: agentskills-1.0
---

# OneNote Workflow

- "Create a page" → call list_onenote_notebooks to find the right notebook, then list_onenote_sections to get the section_id, then create_onenote_page.
- "Show my notebooks / sections / pages" → call list_onenote_notebooks → list_onenote_sections → list_onenote_pages as needed.
- "Add to a page" → if the page is pinned, use update_onenote_page directly with the pinned page_id. If not pinned, navigate to find the page_id first, then call update_onenote_page. The default action appends to the end.
- "Change something already on a page" (fix a typo, tick a to-do, add a table row, move a line, rename the page) → do NOT create a new page and do NOT append a duplicate:
  1. read_onenote_page with include_ids=true to get the outline (element ids).
  2. For a table, read_onenote_page with element_id=<table id> to get its full HTML.
  3. update_onenote_page with action=replace and target=<element id>. For a table, send the whole table with every row (cells cannot be edited one by one). To remove an element, replace it with empty content. To add next to an element, use action=insert with position before or after. To rename the page, use target=title with action=replace.
  4. The result returns a fresh outline. Use ids from the latest outline only; ids can change after every update. If you get target_not_found, read the page again.
  5. Never replace the body. Replace returns previous_html if the change has to be undone. If previous_html_truncated is true, the copy is incomplete; do not use it to undo.
- Team notebooks: pass the notebook's site_id (from find_onenote_notebook or the pin) to every read and update call. A team page is reached through its section, not by listing a site's notebooks. If find_onenote_notebook finds nothing but you know the site (from search_sharepoint_sites or a SharePoint link), call list_onenote_sections with only site_id to list every section on the site, then list_onenote_pages.
- "Pin this page" → after finding a page, call pin_onenote_page (with its site_id for team notebooks) so the user can reference it by name in future messages without re-navigating.
- When a page is pinned, ALWAYS use update_onenote_page directly — NEVER re-navigate through notebooks/sections.
