# Getting Started Guide

This tool lets you pull live data from Confluence, Outlook, and the web and push it into PowerPoint — automatically, without closing the file.

---

## 1. Prerequisites

| Requirement | Version | Check |
|---|---|---|
| Python | 3.10+ | `python --version` |
| pip | any | `pip --version` |
| PowerPoint | Microsoft 365 | — |
| VS Code + Claude Code extension | latest | — |

---

## 2. Installation

### Clone the repo

```bash
git clone <repo-url>
cd TeamsPOC
```

### Install Python dependencies

```bash
pip install python-pptx pywin32
```

- **python-pptx** — creates PowerPoint files from scratch
- **pywin32** — updates an already-open PowerPoint in real time (Windows only)

### Install the Atlassian CLI

Run this in PowerShell (not bash):

```powershell
irm https://<YOUR_ARTIFACTORY_HOST>/atlassian-cli/install.ps1 | iex
```

Restart your terminal after installation.

### Install marketplace skills

```bash
slai-marketplace install atlassian
```

---

## 3. Sign-in & Authentication

You need to authenticate once per service. Tokens are saved locally and auto-refresh.

### Confluence & Jira

```bash
atlassian auth login
```

- Opens a browser — sign in with your Atlassian account
- Grants access to both Confluence and Jira in one step
- Verify with: `atlassian auth status`

### Outlook Email (Microsoft Graph)

```bash
cd skills/m365-email
python auth.py
```

- Shows a URL and a short code
- Open **https://login.microsoft.com/device** in your browser
- Enter the code shown in the terminal
- Sign in with your Microsoft account
- Come back to terminal and run:

```bash
python auth.py --complete <device_code_from_terminal>
```

- Token saved to `~/.config/microsoft-graph/token.json`
- Verify with: `python auth.py --status`

### Microsoft Teams *(pending)*

Teams chat access requires an IT app registration with `Chat.Read` permissions. Raise a request with your IT admin to enable this. Once approved, auth will follow the same device-code flow as Outlook above.

---

## 4. How to Use

Once authenticated, everything is driven by natural language through Claude Code in VS Code. You do not need to run scripts manually.

### PowerPoint

| What to say | What happens |
|---|---|
| "Create a news slide for today" | Searches the web, builds a styled PPT |
| "Update the crypto section" | Fetches latest crypto news, updates that card live in open PPT |
| "Change slide 1 to show Confluence content from page 12345" | Pulls page, pushes to open PPT in real time |

> **Tip:** Keep your `.pptx` file open in PowerPoint — updates happen live without closing it.

### Confluence

| What to say | What happens |
|---|---|
| "Find Confluence pages about X" | Searches your org's Confluence |
| "What does page 1234 say?" | Reads and summarises the page |
| "Update page 1234 with this content" | Writes back to Confluence |
| "Create a new page in space ENG" | Creates the page |

### Jira

| What to say | What happens |
|---|---|
| "Show my open Jira tickets" | Lists your assigned issues |
| "Create a task in project PROJ called X" | Creates the ticket |
| "Move PROJ-123 to In Progress" | Transitions the issue |
| "Add a comment to PROJ-456" | Posts the comment |

### Outlook Email

| What to say | What happens |
|---|---|
| "How many unread emails do I have?" | Returns inbox unread count |
| "Search my email for X" | Searches by keyword, sender, or date |
| "Read the email from Alice about the build" | Fetches and displays full content |

---

## 5. File Reference

| File | Purpose |
|---|---|
| `create_news_ppt.py` | Creates `TodaysNews.pptx` from scratch with today's news |
| `update_news_live.py` | Updates an already-open PPT via COM (no file close needed) |
| `skills/atlassian/` | Atlassian CLI skill — full Jira & Confluence reference |
| `skills/m365-email/` | Outlook email skill — read, search, send via Graph API |
| `skills/m365-email/auth.py` | One-time Microsoft Graph authentication script |
| `SKILLS.md` | Living reference of all skills and patterns in this project |

---

## 6. Troubleshooting

**`atlassian: command not found`**
→ Restart your terminal after installing the CLI, or use the full path:
`C:\Users\<you>\AppData\Local\Programs\atlassian-cli\atlassian.exe`

**PowerPoint save fails with `Permission denied`**
→ The `.pptx` file is open in PowerPoint. Use `update_news_live.py` (COM) instead of saving — it updates the open file directly.

**`403 Forbidden` on Graph API**
→ The token is missing a required scope. Re-run `python auth.py` to get a fresh token with the needed permissions.

**Confluence links return 404**
→ Use the format `https://<YOUR_DOMAIN>.atlassian.net/wiki/spaces/{SPACE}/pages/{PAGE_ID}` — note the `/wiki/` segment.
