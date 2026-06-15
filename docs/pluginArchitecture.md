# AI Gator — Plugin Architecture

## Overview

AI Gator skills are evolving into a full plugin system. This document captures the architecture, compatibility decisions, directory structure, and delivery priorities.

**Naming convention:**
- "Skill" — user-facing term (what users see in the UI)
- "Plugin" — internal term used in code and file structures
- These refer to the same thing

---

## Compatibility Matrix

| Dimension | AI Gator Today | Anthropic Spec | LLM-Agnostic? | Bridge Action | Priority | Risk |
|---|---|---|---|---|---|---|
| **Unit name** | Skill | Plugin | ✅ | Keep "Skill" in UI, "plugin" in code | — | None |
| **Core content file** | `SKILL.md` | `SKILL.md` | ✅ | No change | — | None |
| **Manifest file** | YAML frontmatter inside `SKILL.md` | `.claude-plugin/plugin.json` | ✅ | Add `plugin.json` alongside `SKILL.md`. Keep frontmatter as fallback. Add `gator:` block for Gator policy | P0 | Low |
| **Tool definitions** | Anthropic format (`input_schema`) in `tools.py` | Anthropic format | ⚠️ | Already solved — Gator translates per LLM at runtime. Add one line to docs for skill authors | — | Medium |
| **CLI executables** | Not supported | `bin/` folder added to PATH | ✅ | Add `bin/` to PATH when skill loads. Agent runs commands directly instead of telling user to run them | P0 | Low |
| **MCP per-skill** | One global MCP config for everything | `.mcp.json` inside plugin folder | ⚠️ | Each plugin ships its own `.mcp.json`. Starts when skill enables, stops when disabled. Global MCP stays working | P0 | Medium |
| **Agents** | Not supported | `agents/` directory (Claude-specific) | ❌ | Build Gator-native agents — LLM-agnostic format, works across Claude, GPT-4, Ollama. Same `agents/` folder | P0 | Medium |
| **Hooks** | Not supported | `hooks/` directory (Claude Code-specific) | ❌ | Build Gator-native hooks — LLM-agnostic triggers. Same `hooks/` folder, our own format | P0 | Medium |
| **Slash commands** | `/` menu, auto-detection only | `/plugin:skill` syntax | ✅ | Extend `/` menu with plugin submenus. Power users type `/rocm-toolkit:gpu-doctor` directly. Auto-detection unchanged | P0 | Low |
| **Config folder** | `~/.config/teamspoc/` | N/A | ✅ | Rename to `~/.gator/`. Backup first, copy, verify, keep old folder 30 days. Fallback if migration fails | P0 | Medium |
| **Marketplace** | Custom GitHub API + HTTP URLs | `claude-plugins-official` + `claude-plugins-community` | ✅ | Use Anthropic's marketplace directly. No building our own. Native skills stay bundled in app | v1 | Low |
| **Catalog format** | Our own `catalog_cache.json` | `marketplace.json` | ✅ | Adopt `marketplace.json` field names. Keep filename `catalog_cache.json`. Migrate field names carefully | v1 | Medium |
| **Install flow** | UI click → API → disk | `/plugin install name@marketplace` | ✅ | Keep UI as primary. Add `/skill install` in terminal. If Claude Code detected, also install there | v1 | Low |
| **Hot-reload** | ✅ Works without restart | Enable/disable | ✅ | No change — ours is better | — | None |
| **Source compatibility** | None | N/A | ⚠️ | Same plugin folder works in Gator and Claude Code. Agents/hooks won't carry over — our own format | v1 | Medium |
| **Tier enforcement** | UI badges only | Admin-controlled restrictions | ✅ | Community skills get runtime timeout + read-only restriction. Warn before enforcing | P1 | Medium |
| **Plugin creation UI** | Basic name + instructions only | Cursor-style scaffold + validate | ✅ | Scope picker, template picker, auto-generate `plugin.json`, validate before saving | P1 | Low |

---

## `~/.gator/` Directory Structure

```
~/.gator/
│
├── config.json                          ← Your settings: LLM model, API keys,
│                                           gateway URL, your NTID, preferences
│
├── catalog_cache.json                   ← The marketplace browse list. Refreshed
│                                           every 6 hours. Powers the Browse tab.
│
├── skills/                              ← Simple installed skills (prompt-only)
│   ├── installed-skills.json            ← Index: what's installed, version, tier, when
│   ├── rocm-basics/
│   │   └── SKILL.md                     ← Prompt instructions for this skill
│   └── mine/                            ← Skills YOU created via the Create tab
│       └── my-custom-skill/
│           └── SKILL.md                 ← Your custom instructions
│
├── outputs/                             ← Files the agent produced for you
│   ├── report_2026-05-24.docx           ← Agent wrote this Word doc
│   ├── celebration.gif                  ← Agent generated this GIF
│   └── analysis.pdf                     ← Agent exported this PDF
│
└── plugins/                             ← Full plugins (code, CLI tools, MCP, agents)
    ├── known_marketplaces.json          ← Marketplaces you've added
    │                                       e.g. gator-native, anthropic-community
    └── cache/
        └── gator-native/                ← Which marketplace it came from
            └── rocm-toolkit/            ← Plugin name
                └── 1.2.0/              ← Exact version installed
                    ├── .claude-plugin/
                    │   └── plugin.json  ← Manifest: name, version, contents,
                    │                       gator policy (tier, gateway_required)
                    ├── SKILL.md         ← Prompt instructions for the agent
                    ├── tools.py         ← Python tools the agent can call
                    │                       e.g. get_gpu_memory(), list_rocm_devices()
                    ├── bin/
                    │   └── rocm-smi    ← CLI binary added to PATH when skill
                    │                      is active. Agent runs it directly.
                    ├── agents/
                    │   └── gpu-doctor.md ← Autonomous agent: diagnoses GPU issues
                    │                        end-to-end without user hand-holding
                    ├── hooks/
                    │   └── hooks.json   ← Triggers: e.g. "after every model train
                    │                       run, check GPU memory automatically"
                    └── .mcp.json        ← MCP server for this plugin only.
                                            Starts when skill enables, stops when not.
```

---

## `plugin.json` Manifest Format

Standard Anthropic fields plus a `gator:` block for Gator-specific policy. Claude Code ignores the `gator:` block; Gator reads it.

```json
{
  "name": "rocm-toolkit",
  "version": "1.2.0",
  "description": "GPU diagnostics and memory management",
  "author": { "name": "AI Gator Team" },
  "license": "MIT",

  "gator": {
    "tier": "native",
    "gateway_required": true,
    "requires_approval": false
  }
}
```

**Tier values:** `native` · `verified` · `community` · `mine`

---

## Slash Command Invocation

Once a plugin is installed, users call it three ways:

**1. Browse and pick**
Type `/` in the compose bar → dropdown shows all plugins → hover a plugin → submenu shows its capabilities → click to invoke.

**2. Type directly (power user)**
```
/rocm-toolkit:gpu-doctor
/rocm-toolkit:get-memory
```

**3. Natural language (unchanged)**
```
why is my GPU at 40% memory utilization?
```
Gator auto-detects the right skill and invokes it. No slash command needed.

---

## Config Folder Migration (`teamspoc` → `~/.gator/`)

Migration runs automatically on first launch after update:

1. Detect `~/.config/teamspoc/` exists
2. Create backup at `~/.config/teamspoc_backup_YYYYMMDD/`
3. **Copy** (not move) all contents to `~/.gator/`
4. Verify Gator starts cleanly from new location
5. Keep old folder for 30 days, then remove
6. If anything fails — fall back to old path, log to `logs/server.log`, retry next launch

---

## Tool Authoring Note

All skill `tools.py` files use Anthropic's tool definition format (`input_schema`). Gator automatically translates this to the correct format for other LLMs (OpenAI, Groq, Ollama) at runtime via `provider.normalize_tool_schema()`. Skill authors do not need to handle this.

```python
TOOL_DEFS = [
    {
        "name": "get_gpu_memory",
        "description": "Get current GPU memory usage for all devices",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "integer", "description": "GPU device index"}
            },
            "required": []
        }
    }
]
```

---

## Marketplace Strategy

**MVP / v1:** Use Anthropic's marketplace directly.
- `claude-plugins-official` — curated, high quality
- `claude-plugins-community` — validated third-party

No hosted marketplace for now. Native skills remain bundled in the app. Community skills come from Anthropic's catalog, federated into the Gator Browse tab.

**Future (P1+):** Evaluate hosting a `gator-skill-marketplace` for Native and Verified tier skills as the catalog grows.

---

## Priority Breakdown

### P0 — Build first

| Item | Why |
|---|---|
| `plugin.json` manifest | Foundation everything else builds on |
| `bin/` CLI executables | Agent acts instead of advises |
| MCP per-skill | Agent's connection to external systems |
| Agents (Gator-native, LLM-agnostic) | Core agentic value prop |
| Hooks (Gator-native, LLM-agnostic) | Core agentic value prop |
| Slash command invocation | How users call plugins explicitly |
| `~/.gator/` rename | Clean up legacy name, safe migration |

### v1 — Ships in first release

| Item | Why |
|---|---|
| Anthropic marketplace integration | No hosting our own catalog for now |
| `marketplace.json` catalog schema | Align with Anthropic's field names |
| Install flow + Claude Code handoff | Install once, works in both tools |
| Source compatibility | Same plugin folder works in Gator and Claude Code |

### P1 — Next phase

| Item | Why |
|---|---|
| Plugin creation UI | Cursor-style: scope picker, scaffolding, validation |
| Tier runtime enforcement | Community skills sandboxed at runtime |
