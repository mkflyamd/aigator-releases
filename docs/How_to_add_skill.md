# How to Add a New Skill

This guide covers everything needed to add a new skill to AiGator. After the modular refactor, adding a skill requires **zero changes to `web/app.py`** -- just create a folder and the loader picks it up automatically.

## Quick Start

1. Create a folder: `web/skills/<skill_name>/`
2. Add `__init__.py` (empty)
3. Add `tools.py` with the standard contract (see below)
4. Restart the server
5. Verify at `GET /health` -- your tools should appear in `tool_count` and `skill_tools_map`

## Directory Structure

```
web/skills/<skill_name>/
  __init__.py          # Empty file (required for Python package)
  tools.py             # REQUIRED: tool definitions, handlers, status messages
  api.py               # OPTIONAL: API client wrapper (if the skill calls an external API)
  helpers.py           # OPTIONAL: shared utility functions
  state.py             # OPTIONAL: shared mutable state (e.g. pinned pages dict)
```

## The `tools.py` Contract

Every skill must export these three items from `tools.py`:

```python
"""My skill -- N tools."""

# 1. TOOL_DEFS: list of Claude API tool schemas
TOOL_DEFS = [
    {
        "name": "my_tool_name",
        "description": "What this tool does. When to use it. What it returns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "What this param is for"},
                "param2": {"type": "integer", "description": "Optional param.", "default": 10},
            },
            "required": ["param1"],
        },
    },
]

# 2. TOOL_STATUS: spinner messages shown in the UI while the tool runs
TOOL_STATUS = {
    "my_tool_name": "Running my tool...",
}

# 3. Handler functions + TOOL_HANDLERS dispatch map
def _tool_my_tool_name(param1: str, param2: int = 10) -> dict:
    """Handler function. Must accept **kwargs matching input_schema. Must return a dict."""
    # ... your logic here ...
    return {"result": "success", "data": [...]}

TOOL_HANDLERS = {
    "my_tool_name": _tool_my_tool_name,
}
```

### Optional Exports

```python
SKILL_ID = "my_skill"            # Override the directory name as the skill identifier
                                  # Default: directory name (e.g. "jira", "slack")

SKILL_ALIASES = ["alt_name"]     # Additional keys in SKILL_TOOLS_MAP
                                  # Use when the skill has a legacy name or chip_alias
                                  # Example: excel uses SKILL_ALIASES = ["excel_skill"]

ALWAYS_ON = True                  # Tools are available regardless of which skill is active
                                  # Default: False
                                  # Use sparingly -- only for universally useful tools
                                  # Currently used by: people (search_people), _always_on (describe_images, read_skill)
```

## How the Loader Works

At startup, `_load_skill_modules()` in `app.py`:

1. Scans `web/skills/*/tools.py` (sorted alphabetically)
2. Skips directories starting with `__` (e.g. `__pycache__`)
3. Skips directories starting with `_` EXCEPT `_always_on`
4. Imports each `tools.py` via `importlib.import_module(f"skills.{entry.name}.tools")`
5. Extracts `TOOL_DEFS`, `TOOL_HANDLERS`, `TOOL_STATUS`, `SKILL_ID`, `SKILL_ALIASES`, `ALWAYS_ON`
6. Builds the global `TOOLS`, `TOOL_DISPATCH`, `TOOL_STATUS`, `SKILL_TOOLS_MAP`

**Private/helper packages** (like `_m365`) are skipped by the loader -- they provide shared infrastructure, not tools.

## Examples by Complexity

### Simple skill (no external API)

See: `web/skills/ppt/tools.py` -- 1 tool, calls local COM automation.

### Standard skill with API client

See: `web/skills/slack/tools.py` + `api.py` -- 4 tools, wraps Slack Web API.

Pattern:
```python
# api.py
def get_slack_client():
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Slack token not configured")
    return SlackClient(token)

# tools.py
from .api import get_slack_client

def _tool_slack_list_channels(limit: int = 20) -> dict:
    sc = get_slack_client()
    data = sc.get("conversations.list", {"limit": limit})
    return {"channels": [...]}
```

### Microsoft 365 skill (uses shared GraphClient)

See: `web/skills/contacts/tools.py`, `web/skills/people/tools.py`

Pattern:
```python
# tools.py
def _tool_search_people(query: str) -> dict:
    from .._m365.helpers import get_graph_client
    gc = get_graph_client()
    data = gc.get("/me/people", params={"$search": f'"{query}"'})
    return {"people": [...]}
```

Available M365 helpers from `web/skills/_m365/helpers.py`:
- `get_graph_client()` -- generic Graph API client
- `get_skill_client(scripts_dir)` -- load a skill-specific GraphClient
- `get_cal_client()` -- calendar-specific client
- `make_teams_gc()` -- Teams client with browser token support
- `get_teams_token()` -- raw Teams access token
- `get_current_user_display_name(gc)` -- cached /me displayName
- `html_to_text(html, max_len)` -- HTML to plain text

### Always-on skill

See: `web/skills/people/tools.py`

```python
ALWAYS_ON = True  # these tools are available with ANY active skill
```

### Skill with aliases (legacy compatibility)

See: `web/skills/excel/tools.py`

```python
SKILL_ID = "excel"
SKILL_ALIASES = ["excel_skill"]  # old manifest used "excel_skill" as the ID
```

## Adding a Manifest-Based Skill (Composite)

If your skill bundles tools from other skills (like `aigator` bundles excel + ppt), use a `manifest.json` in the top-level `skills/` directory:

```
skills/<skill_name>/
  manifest.json
```

```json
{
  "id": "my_composite_skill",
  "name": "Display Name",
  "version": "1.0",
  "description": "What this skill does.",
  "chip_alias": "my_alias",
  "tools": ["tool_from_skill_a", "tool_from_skill_b", "tool_from_skill_c"]
}
```

The loader reads these via `_load_manifest_skill_maps()` and adds the tool names to `SKILL_TOOLS_MAP` under both the `id` and `chip_alias` keys.

## Adding Action Endpoints

If your skill needs a quick-action card on the dashboard (the cards that show summaries like "5 unread emails"), add an endpoint in `app.py`:

```python
@app.post("/api/actions/my_skill")
async def action_my_skill(req: ActionRequest):
    from skills.my_skill.api import my_api_call  # lazy import
    data = my_api_call(...)
    return {"summary": "...", "items": [...]}
```

The `ActionRequest` model has one optional field: `query: str = ""`.

## Adding Third-Pane Endpoints

If your skill needs a browseable panel in the UI (like the Teams chat panel or email inbox), add endpoints in `app.py`:

```python
@app.get("/api/my_skill/items")
async def tp_my_skill_items():
    from skills.my_skill.api import my_api_call
    return my_api_call(...)
```

## Environment Variables

If your skill needs credentials or config, follow this pattern:

1. Read from environment variables in your `api.py` or `tools.py`
2. Document the required variables in a `SKILL.md` in the top-level `skills/<skill_name>/` directory
3. Support loading from the saved config file (`~/.config/teamspoc/config.json`) -- add config keys in `app.py`'s `_load_config()` if needed

## Naming Conventions

- **Skill directory**: lowercase, no hyphens (e.g. `slack`, `jira`, `onedrive`)
- **Tool names**: `<skill>_<action>` or `<action>_<noun>` (e.g. `slack_send_message`, `read_email`, `jira_search`)
- **Handler functions**: `_tool_<tool_name>` (e.g. `_tool_slack_send_message`)
- **API client functions**: descriptive verb (e.g. `jira_api()`, `get_slack_client()`, `confluence_api()`)

## Checklist

- [ ] Created `web/skills/<name>/__init__.py`
- [ ] Created `web/skills/<name>/tools.py` with `TOOL_DEFS`, `TOOL_HANDLERS`, `TOOL_STATUS`
- [ ] Each tool in `TOOL_DEFS` has a matching entry in `TOOL_HANDLERS` and `TOOL_STATUS`
- [ ] Handler function signatures match `input_schema` properties (with defaults for optional params)
- [ ] All handlers return a `dict`
- [ ] Created `api.py` if the skill calls an external API
- [ ] Verified with `/health` endpoint -- check `tool_count` and `skill_tools_map`
- [ ] Added a `SKILL.md` in `skills/<name>/` documenting environment setup (if applicable)
- [ ] If using M365 Graph API, importing from `skills._m365.helpers` (not reimplementing)

## Pointing Claude to a New Skill

To have Claude add a skill from an existing repo or file:

1. Share the repo link or file content (API docs, SKILL.md, script files)
2. Specify what operations the skill should support (e.g. "search, create, update")
3. Claude will create the `web/skills/<name>/` package following this contract
4. No changes to `app.py` needed -- the loader auto-discovers it

## Shared Utilities (use these in new skills)

### `web/skills/_skill_utils.py`

| Utility | What It Does |
|---------|-------------|
| `@skill_handler` | Decorator that wraps handlers with try/except. No more boilerplate. |
| `resolve_com_target(file_path, app_type)` | Returns `(app, target, err)` for COM. Handles `open` and `open:filename`. |
| `batch_wrapper(operations, execute_one)` | Runs multiple operations in one tool call. |
| `validate_tool_contract(module, name)` | Validates TOOL_DEFS/TOOL_HANDLERS/TOOL_STATUS match at startup. |

### `web/skills/_office_com.py`

COM helpers for Excel, Word, PowerPoint:
- `get_excel_app()`, `get_word_app()`, `get_ppt_app()` — get running app
- `get_excel_workbook()`, `get_word_document()`, `get_ppt_presentation()` — get target by name or active
- `list_excel_workbooks()`, `list_word_documents()`, `list_ppt_presentations()` — list all open
- `save_com_document(target, app_type)` — save with unsaved-file detection
- `get_file_info(target, app_type)` — return file name, path, saved status

### `web/skills/_constants.py`

Shared tool definition constants:
- `FILE_PATH_DESC` — base file_path description
- `FILE_PATH_DESC_DOCX`, `FILE_PATH_DESC_XLSX`, `FILE_PATH_DESC_PPTX` — per-skill variants

### `web/skills/_scripts/office/`

Shared Anthropic office scripts (validate.py, pack.py, unpack.py, soffice.py, schemas). One copy — not duplicated per skill.

---

## Layering Anthropic Skills into Gator Chat

When Anthropic releases a new skill (e.g., PDF), follow this pattern to layer it in:

### Step 1: Install the Anthropic skill for Claude Code
```bash
/plugin marketplace add anthropics/skills
# The skill is now at ~/.claude/plugins/marketplaces/anthropic-agent-skills/skills/<name>/
```

### Step 2: Read the Anthropic SKILL.md
Understand what it does, what scripts it bundles, and what dependencies it needs. The Anthropic skill is designed for Claude Code (CLI), not for your web app.

### Step 3: Create the Gator Chat skill
```
web/skills/<name>/
  __init__.py
  tools.py       — TOOL_DEFS, TOOL_HANDLERS, TOOL_STATUS
  helpers.py     — XML utilities, formatting helpers (if needed)
  SKILL.md       — Gator-specific prompting guide (NOT the Anthropic one)
```

### Step 4: Implement dual-mode (COM + file-based)
- `file_path="open"` → COM automation (Windows only)
- `file_path="C:\path\to\file"` → library-based (cross-platform)
- Use `resolve_com_target()` from `_skill_utils.py` for COM boilerplate
- Use `save_com_document()` from `_office_com.py` after every COM write
- Use `get_file_info()` to return file name/path in every response

### Step 5: Bundle relevant Anthropic scripts
- Shared scripts (validate, pack, unpack) go in `web/skills/_scripts/office/` (already there)
- Skill-specific scripts go in `web/skills/<name>/scripts/`

### Step 6: Write the SKILL.md for Gator Chat
Include:
- File selection guidance (always ask which file)
- Write verification (always read back after writes)
- Batch mode (if applicable)
- Tool-specific rules and examples

### Step 7: Wire into the app
- Add tools to `skills/aigator/manifest.json`
- Add REST endpoint to `web/app.py` (if needed)
- Add chip + actions to `SKILL_REGISTRY` in `web/static/app.js`
- Add keywords to `_SKILL_KEYWORDS` in `app.py` for auto-detection

### Step 8: Test
- COM mode with app running
- File mode with a real file
- Batch mode
- Multiple files open
- Verify contract at startup (auto via `validate_tool_contract`)

---

## Current Skill Inventory

| Skill | Tools | Always-On | Notes |
|-------|-------|-----------|-------|
| jira | 14 | No | PAT or Basic auth, own api.py |
| confluence | 6 | No | Basic auth, own api.py |
| email | 5 | No | M365 GraphClient |
| calendar | 6 | No | M365, has helpers.py for timezone utils |
| onenote | 7 | No | M365, has state.py for pinned pages |
| excel | 6 | No | COM + openpyxl, create + recalc, aliases: excel_skill |
| slack | 4 | No | Bot token, own api.py |
| sharepoint | 4 | No | M365 GraphClient |
| docx | 4 | No | COM + python-docx, rich creation, aliases: docx_skill |
| ppt | 4 | No | COM + python-pptx, create + read, aliases: ppt_skill |
| teams | 3 | No | M365, special token handling |
| contacts | 3 | No | M365 GraphClient |
| people | 2 | Yes | M365, always available for name resolution |
| onedrive | 2 | No | M365 GraphClient |
| _always_on | 2 | Yes | describe_images, read_skill |

## Importing a skill from a URL

You can install a skill straight from a GitHub folder URL without waiting for
it to land in a curated catalog.

1. Open the Marketplace pane → **+ Import from URL** tab.
2. Paste a URL. Supported formats:
   - GitHub folder: `https://github.com/<owner>/<repo>/tree/<branch>/<path>`
   - GitHub file pointing at `SKILL.md`: `https://github.com/<owner>/<repo>/blob/<branch>/<path>/SKILL.md`
   - Raw `SKILL.md`: `https://raw.githubusercontent.com/...`
   - Direct `.zip` / `.gator` archive URL
3. Click **Fetch preview**. The file list and skill metadata appear.
4. Read the warning banner. URL-imported skills are always installed at
   **Community** tier and run inside the sandbox — but they can still run
   code on your machine. Only install from sources you trust.
5. Tick **I trust this source** and click **Install**.

Limits: 10 MB total, 100 files. Larger skills must be added via a curated
marketplace source.
