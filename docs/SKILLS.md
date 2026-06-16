# AI Gator Skills & Techniques

> **Two types of skills live in this project — keep them separate:**
>
> | | Location | Purpose | Managed by |
> |---|---|---|---|
> | **Installed Skills** | `.cursor/skills/<name>/SKILL.md` | Raw skill definitions installed via `slai-marketplace` — do not edit | `slai-marketplace` |
> | **This document** | `SKILLS.md` (here) | Living record of all techniques, patterns, and tools built or integrated | Us |
>
> All new skills and integrations we discover go here. Installed marketplace skills are referenced by name only.

---

## PowerPoint Automation

### 1. Create a PowerPoint from scratch — `python-pptx`

**Library:** `python-pptx`
**Install:** `pip install python-pptx`
**Use case:** Generate a fully styled `.pptx` file programmatically (no PowerPoint needed to be open).

**Key patterns:**
- `Presentation()` — create a new deck
- `prs.slide_layouts[6]` — blank slide layout (no placeholders)
- `slide.shapes.add_textbox(...)` — add text anywhere
- `slide.shapes.add_shape(1, ...)` — add rectangles (for cards, dividers, backgrounds)
- `slide.background.fill.solid()` — set background color
- `RGBColor(r, g, b)` — set colors on fills, fonts, lines
- `prs.save(path)` — write file to disk

**Limitation:** Requires the file to be **closed** in PowerPoint before saving — Windows locks open `.pptx` files.

**Reference script:** `create_news_ppt.py`

---

### 2. Update an open PowerPoint in real time — `win32com` COM Automation

**Library:** `pywin32`
**Install:** `pip install pywin32`
**Use case:** Modify slide content in a **live, already-open** PowerPoint session without closing the file.

**Key patterns:**
```python
import win32com.client

# Hook into the running PowerPoint instance
ppt = win32com.client.GetActiveObject("PowerPoint.Application")

# Find the open presentation by filename
for pres in ppt.Presentations:
    if os.path.basename(pres.FullName).lower() == "myfile.pptx".lower():
        target = pres

# Access slide and shapes (1-based index in COM)
slide = pres.Slides(1)
shape = slide.Shapes(3)
shape.TextFrame.TextRange.Text = "New content"
```

**Shape indexing:** Shapes are 1-based in COM. Map your layout carefully:
- Shape 1 = background rectangle
- Shape 2 = divider line
- Shapes 3+ = card backgrounds, labels, body text (3 shapes per card)

**Windows only** — COM automation is a Windows-specific capability.

**Reference script:** `update_news_live.py`

---

## Data Fetching

### 3. Real-time news via Web Search

**Tool:** Built-in `WebSearch`
**Use case:** Pull today's headlines without any API key or external dependency.

**Pattern:**
- Search for `"top news headlines today <date>"` or a topic-specific query
- Parse the structured summary returned
- Feed content into the PPT update script

**Crypto-specific query used:** `"crypto cryptocurrency news today April 17 2026"`

---

## Architecture Patterns

### 4. Fetch → Format → Push pattern

The core loop used across all POC work:

```
[Data Source]         [Processor]          [Output]
WebSearch        →   Python script    →   PowerPoint slide
Confluence MCP   →   Python script    →   PowerPoint slide
```

- **Data source** is swappable (news, Confluence, APIs, databases)
- **Processor** formats and structures content
- **Output** is currently PowerPoint via COM or python-pptx

---

## Atlassian (Jira & Confluence)

### 5. Atlassian CLI — `atlassian`

**Installed skill:** `.cursor/skills/atlassian/SKILL.md` — full CLI reference lives there
**Install via:** `slai-marketplace install atlassian`
**Binary:** `atlassian` (add install directory to PATH)
**Auth:** `atlassian auth login` — OAuth device flow via proxy (one-time, token auto-refreshes)

**Confluence — key commands:**
```bash
atlassian confluence page get PAGE_ID                          # Read a page
atlassian confluence page get PAGE_ID --body-format storage    # With full XHTML body
atlassian confluence search --cql "space = ENG AND title ~ 'design'"
atlassian confluence page update PAGE_ID --body "<p>New content</p>"
```

**Jira — key commands:**
```bash
atlassian jira issue list --jql "project = PROJ AND status = Open"
atlassian jira issue get PROJ-123
atlassian jira issue create --project PROJ --summary "Title" --type Task
atlassian jira issue transition PROJ-123 --transition-id 31
```

**Useful flags:**
- `--json` — machine-readable output, pipe to `jq`
- `--max-results N` — limit list/search results
- `--site NAME` — target a specific Atlassian site without switching active site

**Use case:** Fetch Confluence page content → format → push live into open PowerPoint via COM.

---

## Microsoft 365 Email

### 6. Outlook Email — `m365-email`

**Installed skill:** `.cursor/skills/m365-email/SKILL.md` — full reference lives there
**Install:** Via skill marketplace
**Auth:** Uses shared m365 token — no separate OAuth setup needed

**Capabilities:**

| Script | What it does |
|---|---|
| `list_mail.py` | List recent inbox messages with filters |
| `search_mail.py` | Search by keyword, sender, or date range |
| `read_mail.py` | Read full content of a specific message |
| `send_mail.py` | Send new email to one or more recipients |
| `reply_mail.py` | Reply to an existing email |

**Safety note:** Send and reply are visible to others — always confirm with user before executing.

**Use case:** Read emails → extract content → push summary into PowerPoint slide via COM.

---

## Microsoft 365 — Full Suite

All M365 skills share one auth token at `~/.config/microsoft-graph/token.json`. Authenticate once and all others work immediately.

### Auth — Device Code (one-time, ~90 day refresh)

```bash
python3 skills/m365-teams/scripts/auth.py        # follow device code flow
python3 skills/m365-teams/scripts/whoami.py      # verify
```

Works for send, calendar, email, OneDrive, people. **Chat.Read and Presence are blocked by tenant policy** — use browser token below to unlock them.

### Auth — Browser Token (full access, expires ~1hr)

Use this when you need to **read Teams chats, list messages, or check presence**.

1. Open **https://outlook.office.com** in your browser (Outlook Web, not Teams — it reliably calls graph.microsoft.com)
2. Press `F12` → **Network** tab → type `graph.microsoft.com` in the filter box
3. The page load itself triggers requests — click any one → **Headers** → copy the `Authorization:` value (`Bearer eyJ0...`)
4. Run:
```bash
python3 skills/m365-teams/scripts/browser_token.py --token "Bearer eyJ0..."
python3 skills/m365-teams/scripts/browser_token.py --info   # verify scopes + expiry
```

Token lasts ~1 hour. Repeat step 1-4 when expired. Do **not** paste tokens in chat — treat like a password.

| Skill | What it does |
|---|---|
| `m365-teams` | Send Teams chat messages by email. Send-only (read blocked by tenant policy) |
| `m365-email` | List, search, read, send, and reply to Outlook email via Graph API |
| `m365-calendar` | View events, check availability, find meeting times, create/cancel meetings |
| `m365-contacts` | Manage personal Outlook address book (add, look up, edit contacts) |
| `m365-onedrive` | Browse, upload, download, search, and share OneDrive files |
| `m365-onenote` | Read and create OneNote notebooks, sections, and pages |
| `m365-people` | Look up coworkers, org charts, and manager chains |
| `m365-planner` | Manage Microsoft Planner boards and To Do task lists |
| `m365-sharepoint` | Browse SharePoint sites, document libraries, and lists |

---

## Developer Tools & Utilities

| Skill | What it does |
|---|---|
| `ado` | Azure DevOps — query work items, search tasks/bugs, get comments via WIQL |
| `confluence_skill` | Confluence CLI scripts for search, create/update pages, attachments |
| `jira_skill` | Jira REST API scripts — search, create, update, link, transition issues |
| `screen-highlight` | Generate highlight reels from screen recordings (idle frame compression) |
| `screen-record` | Record screen to MP4/GIF/PNG via ffmpeg; live MJPEG stream for monitoring |
| `skill-creator` | Create and iteratively improve new skills with eval/benchmarking |
| `summon` | Dispatch tasks to other AI models (GPT, Codex, Gemini, Kimi) from Claude Code |
| `terminal-email` | Check email via IMAP/OAuth2 + SMTP relay (alternative to m365-email) |
| `web-automation` | Browser automation — screenshots, clicks, form fill, page navigation via Playwright |

---

## Document Skills (Anthropic-Layered)

Layered Anthropic's `anthropics/skills` marketplace capabilities into Gator Chat with COM live editing.

### 7. Word/DOCX — `docx`

**Tools:** `get_docx_info`, `read_docx`, `create_docx`, `update_docx`
**Libraries:** `python-docx` (file), `win32com` (COM live editing)
**Anthropic scripts bundled:** `validate.py`, `comment.py`, `accept_changes.py`

**Rich creation features:** Page size/margins, headers/footers with page numbers, footnotes, hyperlinks, images, TOC, multi-column layouts, inline formatting (bold/italic/color/font via `runs`), table formatting with shading.

### 8. Excel/XLSX — `excel`

**Tools:** `get_excel_info`, `list_excel_sheets`, `read_excel`, `update_excel`, `create_excel`, `recalc_excel`
**Libraries:** `openpyxl` (file), `win32com` (COM live editing)
**Anthropic scripts bundled:** `recalc.py` (formula recalculation + error scanning)

**Professional features:** Multi-sheet creation, auto-formatting (Arial, bold headers with blue shading, borders, auto-filter, freeze panes), formula support, financial model color standards.

### 9. PowerPoint/PPTX — `ppt`

**Tools:** `get_pptx_info`, `read_pptx`, `create_pptx`, `update_pptx`
**Libraries:** `python-pptx` (file), `win32com` (COM live editing)
**Anthropic scripts bundled:** `thumbnail.py`, `add_slide.py`, `clean.py`

**Creation features:** 7 layout types, speaker notes, images, bullet content.

### Shared Infrastructure

- **COM automation:** `web/skills/_office_com.py` — shared helpers for all 3 apps
- **Shared utilities:** `web/skills/_skill_utils.py` — `@skill_handler`, `resolve_com_target()`, `batch_wrapper()`, `validate_tool_contract()`
- **Shared scripts:** `web/skills/_scripts/office/` — validate, pack, unpack, soffice (one copy)
- **Auto-skill detection:** Keywords in user messages auto-activate relevant skills ("put this in a word doc" activates docx)
- **Batch mode:** All 3 update tools support batch operations to prevent truncation during live editing
- **File picker:** Native Windows file dialog via `/api/file-picker`, composes chip in prompt bar

---

## Planned / Upcoming

| Skill | Tool/Library | Status |
|---|---|---|
| PDF skill (Anthropic layering) | python + Anthropic scripts | Next |
| Confluence → PowerPoint live update | Atlassian CLI + win32com | Planned |
| Scheduled auto-refresh of slides | Python scheduler / Claude loop | Planned |

---

*Last updated: 2026-05-02*
