---
name: people
description: "Look up coworkers, org charts, and manager chains using Microsoft Graph API. Use when user asks about people, who is someone, who reports to whom, org structure, manager chain, find someone by name/email, look up a coworker. Keywords: people, org chart, manager, direct reports, coworker, lookup, who is, find person, org chain."
license: Proprietary
metadata:
  author: Mayuresh Kulkarni
  version: "1.1"
  format: agentskills-1.0
---

# People & Org Lookup Skill

Look up coworkers, org charts, and manager chains using the Microsoft Graph API. No external dependencies -- Python stdlib only.

Shares authentication with [m365-teams](../m365-teams/) skill. Authenticate once, use everywhere.

## Prerequisites

- Python 3.10+
- Microsoft Graph auth token at `~/.config/microsoft-graph/token.json`
- If not authenticated yet, run `m365-teams/scripts/auth.py` first (one-time setup)

## Quick Start

```bash
# Search for someone
python3 scripts/search_people.py "Tanmay Shah"

# Get full profile
python3 scripts/get_profile.py --email tanmay.shah@amd.com

# See org chain (manager hierarchy)
python3 scripts/org_chain.py
python3 scripts/org_chain.py --user tanmay.shah@amd.com
```

## When to Use

Trigger this skill when the user asks:
- "Who is [name]?" or "Find [name]"
- "Who is [name]'s manager?"
- "Show me the org chart for [name]"
- "What is [name]'s email / title / department?"
- "Who reports to [name]?"
- Look up a coworker by name or email

## Available Scripts

| Script | Description |
|--------|-------------|
| `search_people.py` | Search coworkers by name or email |
| `get_profile.py` | Get detailed user profile (title, dept, office, etc.) |
| `org_chain.py` | Show manager chain / org hierarchy |

All scripts support `--json` flag for machine-readable output.

## Usage Examples

```bash
# Search by name (fuzzy)
python3 scripts/search_people.py "Kumar"
python3 scripts/search_people.py "Tanmay" --count 5

# Search by email
python3 scripts/search_people.py "tanmay.shah@amd.com"

# Get full profile by email
python3 scripts/get_profile.py --email tanmay.shah@amd.com

# Get profile by user ID
python3 scripts/get_profile.py --id 5a63e4ef-a360-4492-9806-f17c5f4f0c8f

# Your own profile
python3 scripts/get_profile.py

# Your org chain
python3 scripts/org_chain.py

# Someone's org chain
python3 scripts/org_chain.py --user tanmay.shah@amd.com

# Org chain with depth
python3 scripts/org_chain.py --depth 5
```

## For AI Agents

```bash
# Find someone's info
python3 scripts/search_people.py "name or email"

# Get detailed profile
python3 scripts/get_profile.py --email user@amd.com --json

# Get manager hierarchy
python3 scripts/org_chain.py --user user@amd.com --json
```

## Security

- Uses shared token at `~/.config/microsoft-graph/token.json`
- No credentials stored in scripts
- **NEVER expose token values**

## Limitations

- `search_people.py` uses the People API which ranks results by relevance to you (people you interact with rank higher)
- `get_profile.py --email` may return 404 for external/guest users -- use `search_people.py` as fallback
- Presence/availability check is blocked by tenant policy (missing `Presence.Read` scope)
