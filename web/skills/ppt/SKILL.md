---
name: ppt_skill
description: "Create, read, and edit PowerPoint presentations via Gator Chat tools."
metadata:
  author: Mayuresh Kulkarni
  version: "2.0"
  format: agentskills-1.0
---

# PowerPoint Rules

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

## Write Verification — NEVER Skip

After every update_pptx call, ALWAYS call read_pptx or get_pptx_info to verify the content was actually written. If the read returns an error, report the failure honestly. NEVER claim success without verification. Always tell the user which file was updated (name + path).

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
    {"layout": "title_slide", "title": "Q2 2025 Report", "subtitle": "Finance Team"},
    {"layout": "title_content", "title": "Revenue", "content": ["$2.4B total revenue", "15% YoY growth", "APAC led all regions"]},
    {"layout": "title_content", "title": "Key Metrics", "content": ["Operating margin: 18.5%", "Customer retention: 94%"]},
    {"layout": "section", "title": "Next Steps"},
    {"layout": "title_content", "title": "Action Items", "content": ["Expand APAC operations", "Launch new product line", "Hire 50 engineers"], "notes": "Discuss timeline with VP Eng"}
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
    {"slide_number": 1, "update_type": "title", "new_text": "Updated Title"},
    {"slide_number": 2, "update_type": "body", "new_text": "New body content"},
    {"slide_number": 3, "update_type": "title", "new_text": "Revised Section"}
  ]
}
```

**Never call update_pptx multiple times** — always combine into one batch call.

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
