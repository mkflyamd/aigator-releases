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
- "Read a file" → call read_onedrive_file. For .docx files the result includes a `hyperlinks` list of `{text, url}` pairs extracted from the document's hyperlink relationships — use these when the user needs the actual link targets (e.g. to wire links into a .pptx).
- "Download a file to disk" / "save it locally" / "I need the file bytes" → call download_onedrive_file. This saves raw bytes to ~/Downloads (or a specified path) so local tools (python-pptx, python-docx, zip inspection) can work on it.
- Always present file names and download URLs to the user.
