---
name: docx
description: "Create, read, and edit Word documents (.docx) via Gator Chat tools."
metadata:
  author: Mayuresh Kulkarni
  version: "1.0"
  format: agentskills-1.0
---

# Word Document Rules

## Two modes

**Open document** — Word is already running. Use `file_path="open"` for the active document, or `file_path="open:Report.docx"` for a specific open document by name.

**File on disk** — Use a full file path like `C:\Users\me\Documents\report.docx`.

## File Selection — ALWAYS Do This First

Before any read or edit operation, ALWAYS clarify which file:
- If multiple documents are open, tell the user which one you're targeting (by name)
- If unclear, ASK: "Which document? I can see [Document1, Report.docx] open in Word."
- For create operations, ASK where to save: "Where should I save the new file?"
- NEVER assume — always confirm the target file with the user

## Write Verification — NEVER Skip

After every update_docx call, ALWAYS call read_docx or get_docx_info to verify the content was actually written. If the read returns an error, report the failure honestly. NEVER claim success without verification. Always tell the user which file was updated (name + path).

## Workflow

1. **Inspect first**: Call `get_docx_info` to understand the document structure before reading or editing.
2. **For tables with unknown structure** (forms, charts, legal docs): Call `update_docx` with `action="introspect_table"` FIRST — it returns the real row/col layout including merged cells, SDT-wrapped checkbox columns, and which cells have checkboxes.
3. **Read**: Call `read_docx` to see the content. Use `content_type="headings"` for a quick outline.
4. **Edit text**: Call `update_docx` with `action="table_update"` — merge-safe, never destroys cell borders or merge state.
5. **Toggle checkboxes**: Call `update_docx` with `action="check_checkbox"` — works on both content-control checkboxes (`<w:sdt>`) and unicode ☐/☑ characters.
6. **Create**: Call `create_docx` for new documents. Call ONCE with ALL content — do not call multiple times.

## Checkbox Forms (e.g. PERM charts, HR forms)

Many Word forms use content-control checkboxes (`<w:sdt>` elements). These are **invisible to `cell.text`** — always use `check_checkbox` to toggle them, never `find_replace`.

```json
{
  "action": "check_checkbox",
  "file_path": "C:\\path\\to\\form.docx",
  "table_index": 0,
  "cells": [
    {"row": 2, "col": 1, "checked": true},
    {"row": 2, "col": 3, "checked": false}
  ]
}
```

Use `introspect_table` first to find the correct row/col indices — col numbers may not match visual columns if the table uses SDT-wrapped cells.

## Creating Professional Documents

When creating documents, ALWAYS use these settings for professional output:

```json
{
  "page_size": "letter",
  "header_text": "Company or Document Name",
  "footer_text": "Page {{page}}"
}
```

### Content blocks

Use the `content` array with these block types:

| Type | Usage |
|------|-------|
| `heading1`, `heading2`, `heading3` | Section headings |
| `paragraph` | Body text |
| `bullet` | Bullet list item |
| `numbered` | Numbered list item |
| `table` | Table with `rows` (2D array, first row = header) |
| `page_break` | Page break |
| `toc` | Table of Contents (user must update in Word) |
| `image` | Image with `path` and `width` (inches) |
| `hyperlink` | Link with `text` and `url` |

### Simple text vs rich formatting

**Simple** — use `text` for plain content:
```json
{"type": "paragraph", "text": "This is plain text."}
```

**Bold/italic shorthand** — use `bold` or `italic` on the block:
```json
{"type": "paragraph", "text": "This entire paragraph is bold.", "bold": true}
```

**Rich inline formatting** — use `runs` instead of `text` when you need mixed formatting within a single paragraph:
```json
{"type": "paragraph", "runs": [
  {"text": "Normal text, "},
  {"text": "bold text", "bold": true},
  {"text": ", and "},
  {"text": "red text", "color": "FF0000"},
  {"text": "."}
]}
```

Run formatting options: `bold`, `italic`, `underline`, `color` (hex), `size` (pt), `font` (name).

### Footnotes

Define footnotes at the document level, then reference by id in runs:
```json
{
  "footnotes": [
    {"id": 1, "text": "Source: Annual Report 2024"},
    {"id": 2, "text": "Adjusted for inflation"}
  ],
  "content": [
    {"type": "paragraph", "runs": [
      {"text": "Revenue grew 15%"},
      {"footnote": 1},
      {"text": " using adjusted metrics"},
      {"footnote": 2}
    ]}
  ]
}
```

### Tables

Tables are auto-formatted with borders, header shading, and cell padding. Just provide the data:
```json
{"type": "table", "rows": [
  ["Metric", "Q1", "Q2", "Q3"],
  ["Revenue", "$580M", "$610M", "$595M"],
  ["Profit", "$104M", "$110M", "$107M"]
]}
```

### Alignment

Set paragraph alignment with: `"alignment": "left"`, `"center"`, `"right"`, or `"justify"`.

### Multi-column layouts

Use `"columns": 2` at the document level for two-column layouts (newsletters, brochures).

## Batch Mode for Edits

**ALWAYS use batch mode** when making more than one change to a document. This prevents truncation and ensures all edits complete in one call.

```json
{
  "file_path": "open",
  "action": "batch",
  "operations": [
    {"action": "find_replace", "find_text": "2024", "replace_text": "2025"},
    {"action": "find_replace", "find_text": "Draft", "replace_text": "Final"},
    {"action": "append", "content_type": "heading1", "text": "New Section"},
    {"action": "append", "content_type": "paragraph", "text": "Content goes here."},
    {"action": "insert_after", "find_text": "Introduction", "content_type": "paragraph", "text": "Added after intro."}
  ]
}
```

**Never call update_docx multiple times** for separate edits — always combine into one batch call.

## Critical Rules

1. **Call create_docx ONCE** with all content. Never call it multiple times for the same document.
2. **Use batch mode for edits** — always combine multiple update_docx operations into one batch call.
3. **Use runs for mixed formatting** — never concatenate styled text into a single text string.
4. **Ask before creating** — confirm the document structure with the user before calling create_docx (similar to Excel layout confirmation).
5. **Inspect before editing** — always call get_docx_info or read_docx before update_docx.
6. **Tables: first row is always the header** — it gets bold text and shaded background automatically.
7. **Use heading levels consistently** — heading1 for major sections, heading2 for subsections, heading3 for sub-subsections. This is required for TOC to work.
8. **Images need full paths** — use absolute file paths for images, e.g. `C:\Users\me\Pictures\chart.png`.
