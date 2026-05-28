---
name: m365-onedrive
description: "Browse, upload, download, search, and share files in Microsoft OneDrive via the Graph API."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# M365 OneDrive

Access and manage files in your Microsoft OneDrive using the Microsoft Graph API. Supports browsing folder contents, uploading and downloading files, searching across your drive, and generating share links.

## When to use

Use this skill when the user wants to browse, find, upload, download, or share files stored in their OneDrive.

## Tools available

- `list_files` — List files and folders in the root or a subfolder path
- `search_files` — Search OneDrive for files by name or content keyword
- `download` — Download a file from OneDrive by path or item ID
- `upload` — Upload a local file to a specified OneDrive folder
- `share` — Generate a shareable link for a file or folder

## Rules

- Requires Microsoft 365 authentication — prompt the user to sign in via Settings if not authenticated.
- Always confirm the destination path with the user before uploading files.
- For share links, clarify the access level (view-only vs. edit) with the user before generating the link.
