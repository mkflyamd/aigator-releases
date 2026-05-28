---
name: onedrive
description: "Microsoft OneDrive — browse, search, read, upload files."
metadata:
  author: Mayuresh Kulkarni
  version: "1.0"
  format: agentskills-1.0
---

# OneDrive Workflow

- "Find a file" → call search_onedrive_files with a keyword.
- "Browse / list files" → call list_onedrive_files (optionally with a folder path).
- Always present file names and download URLs to the user.
