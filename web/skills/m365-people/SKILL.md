---
name: m365-people
description: "Search for coworkers by name or email and browse org-chart relationships via the Microsoft Graph API."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# M365 People

Look up AMD coworkers, browse org-chart chains, and get profile details (job title, department, office location, email) using the Microsoft Graph People and Users APIs.

## When to use

Use this skill when the user wants to find a coworker's contact info, check who someone reports to, or explore the org chart.

## Tools available

- `search_people` — Search for coworkers by name or email address
- `get_profile` — Get the full profile of a specific user (by email or user ID)
- `org_chain` — Retrieve the reporting chain (manager hierarchy) for a user

## Rules

- Requires Microsoft 365 authentication — prompt the user to sign in via Settings if not authenticated.
- Return only the information from the Graph API — do not infer or embellish organizational relationships.
- Do not expose personal contact details (e.g. mobile phone) unless the user explicitly asks for them.
