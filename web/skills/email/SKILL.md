---
name: email
description: "Microsoft Outlook Email — read inbox, search, compose, reply, forward."
metadata:
  author: Mayuresh Kulkarni
  version: "1.0"
  format: agentskills-1.0
---

# Email Workflow

- "Find an email from X" / "Did I get an email about Y?" → call search_email with keyword or sender.
- For browsing inbox → call read_email. For finding specific threads → prefer search_email.

## Required Permissions

| Tool | Delegated Permission | Scope |
|---|---|---|
| `read_email` | Read user mail | `Mail.Read` |
| `search_email` | Search user mail | `Mail.Read` |
| `send_email` / `email_open_compose` | Send mail on behalf of user | `Mail.Send` |
| `reply_email` | Reply to mail | `Mail.Send` |
| `forward_email` | Forward mail | `Mail.Send` |

**Scope note:** The shared GraphClient requests `Files.ReadWrite.All Sites.ReadWrite.All offline_access` because it serves OneDrive, SharePoint, Calendar, and Teams in addition to Email. The email skill itself only requires `Mail.Read` and `Mail.Send`. The broad token scope is intentional to avoid multiple auth flows, but means a leaked token grants more than mail access. See `graph_client.py:22-26` for the AMD-specific AADSTS65002 constraint that prevents requesting all scopes individually.
