---
name: excel
description: "Microsoft Excel — read, write, create, and recalculate spreadsheets."
metadata:
  author: Mayuresh Kulkarni
  version: "2.0"
  format: agentskills-1.0
---

# Excel Rules

## Two modes

**Open workbook** — Excel is already running. Use `file_path="open"` for the active workbook, or `file_path="open:Budget.xlsx"` for a specific open workbook by name.

**File on disk** — Use a full file path. The file is saved after each operation.

## File Selection — ALWAYS Do This First

Before any read or edit operation, ALWAYS clarify which file:
- Call list_excel_sheets first — it shows ALL open workbooks when multiple are open
- If multiple workbooks are open, tell the user which one you're targeting (by name)
- If unclear, ASK: "Which workbook? I can see [Budget.xlsx, Data.xlsx] open in Excel."
- For create operations, ASK where to save
- NEVER assume — always confirm the target file with the user

## Edit In Place vs. New File — Honor the User's Intent

When the user says "update / edit my workbook" and points at an existing file, edit THAT file — `update_excel` writes back to the `file_path` you pass. Do NOT create a new file in Downloads or anywhere else unless the user asked for a copy ("save as", "make a copy"). If you genuinely need a new destination and don't have one, ASK where to save — never invent a path.

## Write Verification — NEVER Skip

After every update_excel call, ALWAYS call read_excel or get_excel_info to verify the content was actually written. If the read returns an error, report the failure honestly. NEVER claim success without verification. Always tell the user which file was updated — state the **full absolute path** so the UI can render it as a clickable open-link.

## Creating Workbooks

Use `create_excel` to create professional workbooks in one call. Call ONCE with all sheets and data.

```json
{
  "file_path": "C:\\Users\\me\\report.xlsx",
  "author": "Finance Team",
  "sheets": [
    {
      "name": "Revenue",
      "headers": ["Quarter", "Revenue ($M)", "Growth (%)"],
      "rows": [
        ["Q1", "580", "12.5"],
        ["Q2", "610", "15.2"],
        ["Q3", "595", "=((B3-B2)/B2)*100"],
        ["Total", "=SUM(B2:B4)", "=AVERAGE(C2:C4)"]
      ]
    }
  ]
}
```

Auto-applied formatting: Arial 11pt, bold headers with blue shading, borders, auto-filter, freeze panes at header row, numeric values right-aligned.

## Editing Workbooks

1. **Confirm layout first**: Call get_excel_info to read headers. ALWAYS ask the user to confirm column layout before writing.
2. **One value per cell**: Never concatenate multiple values into one cell.
3. **Use batch mode**: ALWAYS use the `batch` parameter for multiple rows in one call.

```json
{
  "file_path": "open",
  "batch": [
    {"cell": "A1:D1", "value": "Item\tQty\tPrice\tTotal"},
    {"cell": "A2:D2", "value": "Apple\t5\t3.99\t=B2*C2"},
    {"cell": "A3:D3", "value": "Banana\t3\t1.49\t=B3*C3"}
  ]
}
```

## Formula Standards

**ALWAYS use Excel formulas, not hardcoded calculations.** The spreadsheet must remain dynamic.

- Use `=SUM()`, `=AVERAGE()`, `=IF()`, `=VLOOKUP()` — never compute in your head and hardcode the result
- After writing formulas, call `recalc_excel` to verify no errors
- Document hardcoded values with their source (e.g., "Source: Annual Report 2024")

## Financial Model Color Standards

When building financial models, use these industry-standard colors:

| Cell Type | Color | RGB |
|-----------|-------|-----|
| Hardcoded inputs | Blue text | (0, 0, 255) |
| Formulas/calculations | Black text | (0, 0, 0) |
| Cross-sheet links | Green text | (0, 128, 0) |
| External file links | Red text | (255, 0, 0) |
| Key assumptions | Yellow background | (255, 255, 0) |

## Number Formatting

- Years as text: "2024" not "2,024"
- Currency with units in headers: "Revenue ($mm)" using $#,##0 format
- Zeros displayed as "-"
- Percentages: 0.0% (one decimal)
- Negatives in parentheses: (123) not -123

## Critical Rules

1. **Call create_excel ONCE** with all sheets and data. Never call it multiple times.
2. **Use batch mode** for multiple update_excel operations — never call update_excel multiple times.
3. **Use formulas, not hardcoded values** — keep spreadsheets dynamic and auditable.
4. **Call recalc_excel after writing formulas** — catches #REF!, #DIV/0!, #VALUE!, #N/A before the user sees them.
5. **Confirm column layout** before writing any data to existing workbooks.
6. **Complete every row** — fill all rows without stopping. Confirm row count when done.
7. Never tell the user you cannot fill the file — use the tools to do it.
