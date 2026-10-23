---
name: onenote
description: 'Microsoft OneNote — read, create, update pages, navigate notebooks and sections.'
metadata:
  author: Mayuresh Kulkarni
  version: '1.0'
  format: agentskills-1.0
---

# OneNote Workflow

- "Create a notebook or section" → call create_onenote_notebook (a new notebook has no sections) and/or create_onenote_section, then create_onenote_page with the returned section id. For a team site pass site_id. Never ask the user to create the notebook or section by hand.
- "Create a page" → call list_onenote_notebooks to find the right notebook, then list_onenote_sections to get the section_id, then create_onenote_page.
- Report a page as created only when create_onenote_page returns verified=true. If it returns created=false or error=page_not_readable, say so, check list_onenote_pages, and create the page again once. Create pages one at a time.
- "Show my notebooks / sections / pages" → call list_onenote_notebooks → list_onenote_sections → list_onenote_pages as needed.
- "Add to a page" → if the page is pinned, use update_onenote_page directly with the pinned page_id. If not pinned, navigate to find the page_id first, then call update_onenote_page. The default action appends to the end.
- "Change something already on a page" (fix a typo, tick a to-do, add a table row, move a line, rename the page) → do NOT create a new page and do NOT append a duplicate:
  1. read_onenote_page with include_ids=true to get the outline (element ids).
  2. For a table, read_onenote_page with element_id=<table id> to get its full HTML.
  3. update_onenote_page with action=replace and target=<element id>. For a table, send the whole table with every row (cells cannot be edited one by one). To remove an element, replace it with empty content. To add next to an element, use action=insert with position before or after. To rename the page, use target=title with action=replace.
  4. The result returns a fresh outline. Use ids from the latest outline only; ids can change after every update. If you get target_not_found, read the page again.
     4b. Edits are verified. If the result has error=edit_misplaced, the page changed but not as requested (for example a heading moved below the list that followed it). Use expected/actual and the fresh outline to correct it, and do not tell the user it worked until the page is right.
  5. Never replace the body. Replace returns previous_html if the change has to be undone. If previous_html_truncated is true, the copy is incomplete; do not use it to undo.
- Team notebooks: pass the notebook's site_id (from find_onenote_notebook or the pin) to every read and update call. A team page is reached through its section, not by listing a site's notebooks. If find_onenote_notebook finds nothing but you know the site (a SharePoint link or its name), call list_onenote_sections with only site_id set to that URL or name to list every section on the site, then list_onenote_pages with the returned site_id.
- "Pin this page" → after finding a page, call pin_onenote_page (with its site_id for team notebooks) so the user can reference it by name in future messages without re-navigating.
- When a page is pinned, ALWAYS use update_onenote_page directly — NEVER re-navigate through notebooks/sections.
