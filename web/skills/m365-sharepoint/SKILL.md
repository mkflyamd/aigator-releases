---
name: m365-sharepoint
description: "Browse SharePoint sites, document libraries, and files via the Microsoft Graph API."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# M365 SharePoint

Browse and access SharePoint sites and document libraries using the Microsoft Graph API. Supports listing followed sites, searching for sites, listing document library drives, browsing folder contents, and downloading files.

## When to use

Use this skill when the user wants to find a SharePoint site, browse its document library, or access a file stored in SharePoint.

## Tools available

- `list_sites` — List SharePoint sites the user follows
- `search_sites` — Search for SharePoint sites by keyword
- `list_drives` — List document library drives within a site
- `list_items` — Browse files and folders in a document library drive
- `download_item` — Download a file from a SharePoint document library

## Rules

- Requires Microsoft 365 authentication — prompt the user to sign in via Settings if not authenticated.
- Use `list_sites` first to get a site ID before browsing its drives or items.
- Do not upload or delete files in SharePoint without explicit user confirmation.
