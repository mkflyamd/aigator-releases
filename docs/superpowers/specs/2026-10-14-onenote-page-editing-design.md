# OneNote page editing (replace, insert, title) for personal and SharePoint team notebooks

**Status:** Approved. Plan: docs/superpowers/plans/2026-10-17-onenote-page-editing.md.

## Goal

Let the assistant change content that is already on a OneNote page, not only append to it, in both personal notebooks and SharePoint team notebooks. Reuse the Graph page-update call the app already makes, and keep the change to the existing OneNote tools. No new routes, no new tool names.

## Use case

The "Who to use for what" page has a 17-row table and a separate MAIDAS paragraph that should be a row of that table. An Excel sheet holds 51 more rows. The user asks: "Add the 51 rows from the Excel file to the table and move the MAIDAS line into it."

Today the assistant can only append, so it cannot touch the existing rows or the paragraph. It creates a second page, and the user has to delete the old one and rename the new one.

After this change:

1. `read_onenote_page(page_id, site_id, include_ids=true)` returns an outline of the page: the table (id, 17 rows, 3 columns) and the MAIDAS paragraph (id).
2. `read_onenote_page(page_id, site_id, element_id=<table id>)` returns the table's full HTML.
3. The assistant builds one table with the 17 existing rows, the MAIDAS row and the 51 new rows.
4. `update_onenote_page(..., action="replace", target=<table id>, content=<table html>, html=true)` swaps the table. The result carries `previous_html` (the old table) and a fresh outline with the new element ids.
5. `update_onenote_page(..., action="replace", target=<MAIDAS paragraph id from the fresh outline>, content="")` clears the paragraph (the tool sends `<p></p>`; Graph rejects empty content).

The same flow works on a page in a SharePoint team notebook by passing that notebook's `site_id` (from `find_onenote_notebook`). Other edits this covers: fix a typo in one paragraph, tick a to-do item, insert a paragraph under a heading, rename the page title.

## What exists today

- `update_onenote_page` (`web/skills/onenote/tools.py:521`) sends one fixed operation, `{"target": "body", "action": "append"}`, to `/me/onenote/pages/{id}/content`. It has no `site_id`, so it cannot reach a team notebook. It uses `urllib` directly, so it has no Graph retry handling.
- `read_onenote_page` (`tools.py:482`) returns plain text capped at 5000 characters and takes `site_id`. It does not request element ids, so the model cannot name an element.
- Pins (`pin_onenote_page`, `state.py`, `routes/chat.py:1325` and `:1501`) store no `site_id`, so a pinned team page cannot be updated without re-navigating.
- Graph's page-update call accepts `append`, `prepend`, `insert` and `replace` against a `target`: `body`, `title`, or an element's id. For `replace`, the target must be the generated id returned by `GET .../content?includeIDs=true` (except the title, and images and objects inside a div). Generated ids can change after any update. `tr` and `td` cannot be targeted, so a table is changed by replacing the whole table.

## Design

### 1. `read_onenote_page`: two new optional inputs

Without them the result is unchanged (title, modified, plain text up to 5000 characters).

- **`include_ids` (boolean).** Fetches `.../content?includeIDs=true` and returns, besides the title, an `elements` list: `{id, tag, text, rows, cols}` (`rows` and `cols` only for tables). `text` is cut to 80 characters. Only elements Graph can update are listed: `p`, `li`, `h1` to `h6`, `ol`, `ul`, `table`, `img`, `object`, and `div` inside a div. Anything inside a table is left out, because `tr` and `td` cannot be targeted. The list is paged with `offset` and `limit` (default 100, at most 200); the result includes `total` and `next_offset`. The page HTML is parsed with BeautifulSoup and lxml, which are already dependencies.
- **`element_id` (string).** Returns `{id, html}` for that one element, with the generated `id` attributes removed (Graph discards ids in submitted HTML) and everything else (styles, tags, links) kept, so the model can rebuild the element. HTML over 100,000 characters returns the error `element_too_large`. An id that is not on the page returns `target_not_found`.

Both read paths use `_onenote_root(site_id)`, so they work for personal and team notebooks.

### 2. `update_onenote_page`: target, action and site

New optional inputs; the current inputs (`page_id`, `content`, `html`) keep their meaning.

| Input      | Values                                                          | Default  |
| ---------- | --------------------------------------------------------------- | -------- |
| `site_id`  | SharePoint site id, or empty for personal                       | empty    |
| `action`   | `append`, `prepend`, `insert`, `replace`                        | `append` |
| `target`   | `body`, `title`, or a generated element id from the outline     | `body`   |
| `position` | `before`, `after` (for `insert`, and for `append` onto a child) | `after`  |

Rules:

- With the defaults the request is exactly today's: append `<div>content</div>` to the body.
- For any other action, text content (`html=false`) is escaped and wrapped in `<p>`; with `html=true` the content is sent as given. For `title`, the content is always plain text, escaped.
- `replace` on `body` is refused by the tool (a live test showed Graph accepts it and wipes the whole page). `replace` with `content=""` is sent as `<p></p>`, which clears the element (Graph rejects empty content).
- For `insert`, `prepend`, `replace` on an element id, the tool first fetches the page with ids. If the id is not found it returns `target_not_found` and sends nothing, with the hint "Read the page again; element ids change after an update." For `replace` the result carries `previous_html` (the old element, up to 20,000 characters), so the change can be undone.
- Any action other than a plain body append returns a fresh `elements` outline (first 100) in the result, so the next edit uses current ids without another read.
- The call goes through `gc._request("PATCH", ...)` to `{root}/pages/{id}/content` (same as `create_onenote_page`), which adds Graph retry and `Retry-After` handling. Graph errors come back as a readable error; a 404 on a page that was given no `site_id` adds the hint "If this page is in a SharePoint team notebook, pass its site_id from find_onenote_notebook."

### 3. Personal and SharePoint team notebooks

Both go through `_onenote_root(site_id)` (`tools.py:213`): `/me/onenote` for personal, `/sites/{site_id}/onenote` for team. Ids are percent-encoded with `_eid`. The token already carries `Notes.ReadWrite.All` and `Sites.ReadWrite.All` (comment at `tools.py:210`), so there is no scope change. The model gets `site_id` from `list_onenote_notebooks` or `find_onenote_notebook`.

`pin_onenote_page` gains an optional `site_id`, saved with the pin. The pin text in `routes/chat.py` (`:1325` and `:1501`) shows `site_id` when it is set and says to pass it to `read_onenote_page` and `update_onenote_page`.

### 4. Skill text

`web/skills/onenote/SKILL.md` and the tool descriptions get the edit workflow: read with `include_ids`; use `element_id` for a table; to change a table row, replace the whole table with every row included; use the ids from the last result, never reuse older ids; never replace `body`; pass `site_id` for team notebooks.

### 5. Guards that already apply

- OneNote is already a data source in `web/data_sources.py` and its results are already marked untrusted. No new tool names are added, so that table does not change.
- Tool inputs are checked against the registered schema (enums for `action` and `position`), per the prompt-injection controls.
- No route is added, so the CSRF inventory is unaffected. The pane's own PATCH route (`routes/onenote.py:449`) is not changed.
- Writes stay direct, as append is today, with no approval card. `previous_html` on replace gives the undo path.

## Out of scope

- Deleting pages, renaming or moving pages, and section changes.
- Editing a single table cell or row (Graph cannot target `tr` or `td`).
- Images, files and ink (these need a multipart request).
- Microsoft 365 group notebooks (`/groups/{id}/onenote`).
- The in-app OneNote pane (read and append there stay personal-only).
- An approval card for replace.

## Testing

- **Outline:** a fixture page with a paragraph, a list, a table (with `tr` and `td` ids), a `p` inside a `td`, and an absolute-positioned div. Check the element set, the table's `rows` and `cols`, `offset` and `limit` paging, text cut, and that the `td` content is not listed.
- **`element_id`:** returns the HTML without `id` attributes; unknown id returns `target_not_found`; oversize returns `element_too_large`.
- **Update request body:** one test per action (append, prepend, insert before and after, replace element, replace title, replace with empty content) checks the JSON sent. The default call matches today's body.
- **Routing:** personal uses `/me/onenote/pages/...`, a `site_id` uses `/sites/{id}/onenote/pages/...`, and an id with `/`, `+` or `=` is percent-encoded. `test_update_page_encodes_page_id` (`tests/test_graph_id_encoding.py:382`) is updated because the update now uses `gc._request` instead of `urllib`.
- **Guards:** an unknown target returns `target_not_found` and makes no PATCH; `replace` on `body` is refused; replace returns `previous_html` and a fresh outline; a 404 without `site_id` adds the team-notebook hint.
- **Pins:** `site_id` is stored and appears in both pin prompt lines.
- **Manual run on real notebooks:** run against a personal notebook on 2026-10-17: replace by generated id, insert before, title rename, whole-table replace, list item replace and append, to-do tick, ids stable after an append, and two replaces in one call using ids from before the call all work. `replace` by `#data-id` fails on a created page. Empty-content replace fails and `<p></p>` works. `replace` on `body` wipes the page. The same operations (replace paragraph, insert, title, whole-table replace, clear with `<p></p>`, list append, body append) also pass on a SharePoint team notebook (site SiloEngineering, section "Start Here"). On that site `GET .../onenote/notebooks` returns 403 (code 10008, a document library has over 5,000 items) while `GET .../onenote/sections` works, so the assistant must reach a team page through its section, not through a notebook listing.
