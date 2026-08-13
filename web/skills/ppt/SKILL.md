---
name: ppt_skill
description: 'Create, read, and edit PowerPoint presentations via Gator Chat tools.'
metadata:
  author: Mayuresh Kulkarni
  version: '2.0'
  format: agentskills-1.0
---

# PowerPoint Rules

## Restyle / polish / reformat an existing deck — USE `pptx_apply_theme`

If the task is to **polish, reformat, restyle, apply a theme/brand colors, fix
consistency, change the look, OR make a polished/reformatted COPY** of an
EXISTING `.pptx`, use `pptx_apply_theme`. This covers phrasings like "create a
copy of this deck and format it", "make a polished version", "reformat this
deck with a dark theme", "apply our brand colors". The workflow is: **copy the
file, then call `pptx_apply_theme` on the copy** — do NOT rebuild the deck from
scratch with pptxgenjs. `pptx_apply_theme` applies background, font family,
title/body colors, and table header/banding across a slide range in one shot
and handles every python-pptx gotcha (slide iteration, RGBColor, table
banding) correctly internally.

```json
{
  "file_path": "C:\\Users\\me\\deck.pptx",
  "slide_range": [1, 32],
  "bg_hex": "0F1B2D",
  "font_name": "Arial",
  "title_color_hex": "FFFFFF",
  "body_color_hex": "C8CACD",
  "table_header_fill_hex": "00C2DE",
  "table_band_fill_hex": "1A2740",
  "table_header_font_hex": "0F1B2D",
  "table_body_font_hex": "C8CACD"
}
```

Every field is optional — omit one to leave that aspect untouched. The file is
saved in place and the return includes a per-slide summary.

**Do NOT rebuild an existing deck with pptxgenjs.** That path loses the
original's exact text, tables, charts, and layout, and the model tends to
narrate the plan for 30K tokens then stop without ever calling a tool.
`pptx_apply_theme` preserves all content and changes only look-and-feel.

**When NOT to use `pptx_apply_theme`:** creating a deck from scratch (use
`create_pptx`), editing specific text (use `update_pptx`), or editing a specific
table cell (use `pptx_write_table_cell`). For global look-and-feel changes to an
existing deck, `pptx_apply_theme` is the right tool — every time.

## Two modes

**Open presentation** — PowerPoint is already running. Use `file_path="open"` for the active presentation, or `file_path="open:Deck.pptx"` for a specific open presentation by name.

**File on disk** — Use a full file path like `C:\Users\me\Documents\deck.pptx`.

## File Selection — ALWAYS Do This First

Before any read or edit operation, ALWAYS clarify which file:

- Call get_pptx_info first — it shows which presentation is active
- If multiple presentations are open, tell the user which one you're targeting (by name)
- If unclear, ASK: "Which presentation? I can see [Deck.pptx, Q2 Report.pptx] open."
- For create operations, ASK where to save
- NEVER assume — always confirm the target file with the user

## Edit In Place vs. New File — ALWAYS Ask First

When the user says "update / edit my presentation" and points at an existing file, you MUST ask — before the first write — whether to **overwrite the original in place** or **save a new copy** (and where). Do not decide this yourself. `update_pptx` (and the table/shape tools) write back to the `file_path` you pass, so pass the original path only after the user chose "overwrite" in this turn.

- **Skip the question ONLY if** the user's current message already states the destination ("overwrite it", "save as X", "make a copy in Documents"). Then honor that verbatim.
- **Resolve the exact target path first.** Use the file already on disk — never re-download a pinned file into a fresh `~/Downloads` copy (that produces spurious `(1)` files).
- **Never invent a destination.** If a copy is chosen and none was given, ASK.

## Write Verification — NEVER Skip

After every update_pptx call, ALWAYS call read_pptx or get_pptx_info to verify the content was actually written. If the read returns an error, report the failure honestly. NEVER claim success without verification. Always tell the user which file was updated — state the **full absolute path** so the UI can render it as a clickable open-link.

## Workflow

1. **Inspect first**: Call `get_pptx_info` to see slide count, titles, and layouts.
2. **Read**: Call `read_pptx` to see all text content and speaker notes.
3. **Edit**: Call `update_pptx` with batch mode for multiple slide updates.
4. **Create**: Call `create_pptx` for new presentations. Call ONCE with all slides.

## Creating Presentations

Use `create_pptx` with an array of slide definitions:

```json
{
  "file_path": "C:\\Users\\me\\deck.pptx",
  "slides": [
    { "layout": "title_slide", "title": "Q2 2025 Report", "subtitle": "Finance Team" },
    {
      "layout": "title_content",
      "title": "Revenue",
      "content": ["$2.4B total revenue", "15% YoY growth", "APAC led all regions"]
    },
    {
      "layout": "title_content",
      "title": "Key Metrics",
      "content": ["Operating margin: 18.5%", "Customer retention: 94%"]
    },
    { "layout": "section", "title": "Next Steps" },
    {
      "layout": "title_content",
      "title": "Action Items",
      "content": ["Expand APAC operations", "Launch new product line", "Hire 50 engineers"],
      "notes": "Discuss timeline with VP Eng"
    }
  ]
}
```

**Available layouts:** `title_slide`, `title_content`, `section`, `blank`, `two_content`, `comparison`, `title_only`

## Batch Mode for Edits

**ALWAYS use batch mode** when updating more than one slide:

```json
{
  "file_path": "open",
  "update_type": "batch",
  "operations": [
    { "slide_number": 1, "update_type": "title", "new_text": "Updated Title" },
    { "slide_number": 2, "update_type": "body", "new_text": "New body content" },
    { "slide_number": 3, "update_type": "title", "new_text": "Revised Section" }
  ]
}
```

**Never call update_pptx multiple times** — always combine into one batch call.

## Tables, Pictures & Shapes (closed file only)

`update_pptx` only reaches title/body/shape _text_. For table cells, picture swaps,
and shape geometry use these tools. They operate on a **closed local file via a
full path** (not `open`/COM, which proved unstable). Conventions shared by all:

- **Locate by content, not position.** `slide_locator` accepts a 1-based index OR
  a text string scanned across title/shape/table text. `table_locator` accepts a
  0-based index OR a header-row cell text. `shape_locator`/`picture_locator`
  accept an index OR a shape name/text.
- **Geometry is in inches**, in and out.
- **Colors are 6-digit hex with no `#`** (e.g. `FF0000`).
- **Every write reads back from disk** and returns the post-write value
  (`cell_after`, geometry, `target`, …) so success is proven, not claimed.
- **Nothing is removed.** `pptx_replace_picture` re-points the image; it never
  deletes a shape. To "clear" a cell, write empty text — don't delete the row.
- **Partial updates preserve.** Omit any optional field to leave it untouched
  (e.g. `pptx_write_table_cell` with only `fill_hex` keeps the existing text).

Tools:

- `pptx_list_shapes(file_path, slide_locator)` — every shape's type, name,
  geometry, `has_table`, text preview. Run this first to discover shapes.
- `pptx_read_table(file_path, slide_locator, table_locator)` — rows×cols grid of
  `{text, fill_hex, font_hex, font_bold}`.
- `pptx_write_table_cell(file_path, slide_locator, table_locator, row, col, text?, fill_hex?, font_hex?, bold?)`
- `pptx_add_table_row(file_path, slide_locator, table_locator, copy_last=true)`
- `pptx_replace_picture(file_path, slide_locator, picture_locator, new_image_path)`
- `pptx_add_autoshape(file_path, slide_locator, shape_type, left, top, width, height, fill_hex?)`
- `pptx_set_shape(file_path, slide_locator, shape_locator, left?, top?, width?, height?, fill_hex?)`
- `pptx_add_hyperlink(file_path, slide_locator, shape_locator, run_match, url, color_hex="1A73E8", underline=true)`

Typical flow: `pptx_list_shapes` → `pptx_read_table` → `pptx_write_table_cell`,
then trust the returned read-back instead of re-reading.

## Global Restyle / Polish — use `pptx_apply_theme`, NOT raw python-pptx

For "polish this deck", "make it consistent", "apply brand colors across all
slides", or any restyle that touches more than one slide, call
`pptx_apply_theme` in ONE call. It applies background, font family, title/body
text colors, and table header/banding across a slide range — and handles slide
iteration, `RGBColor`, and table banding correctly internally.

```json
{
  "file_path": "C:\\Users\\me\\deck.pptx",
  "slide_range": [1, 32],
  "bg_hex": "0F1B2D",
  "font_name": "Arial",
  "title_color_hex": "FFFFFF",
  "body_color_hex": "C8CACD",
  "table_header_fill_hex": "00C2DE",
  "table_band_fill_hex": "1A2740",
  "table_header_font_hex": "0F1B2D",
  "table_body_font_hex": "C8CACD"
}
```

Every field is optional — omit one to leave that aspect untouched. The file is
saved in place and the return includes a per-slide summary so success is proven.

**Do NOT reach for `run_python` + python-pptx for global restyle.** The three
recurring crash bugs all come from that path:

1. **Never slice `prs.slides`** (`prs.slides[:32]` or `prs.slides[1:5]`).
   Slicing a `Slides` collection returns a plain `list`, which breaks
   python-pptx's internal `sldId.rId` lookup → `AttributeError: 'list' object
has no attribute 'rId'`. Iterate instead: `for slide in prs.slides:`.
2. **`RGBColor` is a tuple, not an object with attributes.** `color.red` raises
   `AttributeError`. Index it: `color[0]`, `color[1]`, `color[2]`, or build one
   with `RGBColor.from_string("00C2DE")`.
3. **Always open the deck first.** `prs = Presentation(path)` before referencing
   `prs.slides` — a bare `sl = prs.slides[0]` with no `Presentation()` call
   raises `NameError: name 'prs' is not defined`.

`pptx_apply_theme` makes all three moot. Use it.

## Design Guidelines

When creating presentations, follow these principles:

**Color:** Pick a topic-specific palette. One color dominates (60-70%), supported by 1-2 tones and one accent.

**Typography:**

- Titles: 36-44pt bold
- Body text: 14-18pt
- Use consistent font pairing (e.g., Georgia + Calibri)

**Layout:**

- 0.5" minimum margins on all sides
- 0.3-0.5" between content blocks
- Visual elements on every slide — never text-only
- Dark backgrounds for title/conclusion slides, light for content

**Content:**

- Max 5-6 bullet points per slide
- Keep bullet text concise (1 line each)
- Use speaker notes for details, not the slide
- One key message per slide

## Critical Rules

1. **Call create_pptx ONCE** with all slides. Never call it multiple times.
2. **Use batch mode** for multiple update_pptx operations — never call update_pptx multiple times.
3. **Inspect before editing** — always call get_pptx_info or read_pptx before update_pptx.
4. **Use speaker notes** for detailed talking points, not the slide body.
5. **Keep slides visual** — prefer fewer words with clear structure.
