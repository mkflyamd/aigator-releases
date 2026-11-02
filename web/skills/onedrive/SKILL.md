---
name: onedrive
description: 'Microsoft OneDrive — browse, search, read, upload, save and copy files and folders'
metadata:
  author: Mayuresh Kulkarni
  version: '1.0'
  format: agentskills-1.0
---

# OneDrive Workflow

- "Find a file" → call search_onedrive_files with a keyword.
- "Browse / list files" → call list_onedrive_files (optionally with a folder path).
- "Read a file" → call read_onedrive_file. For .docx files the result includes a `hyperlinks` list of `{text, url}` pairs extracted from the document's hyperlink relationships — use these when the user needs the actual link targets (e.g. to wire links into a .pptx).
- "Download a file to disk" / "save it locally" / "I need the file bytes" → call download_onedrive_file. This saves raw bytes to ~/Downloads (or a specified path) so local tools (python-pptx, python-docx, zip inspection) can work on it.
- "Move a file to a folder" / "put this in my X folder" → find the source with search_onedrive_files, list_onedrive_files or get_onedrive_item (use resolve_teams_attachment first for a Teams chat attachment), find the destination folder's drive_id and item id with list_onedrive_files, then call file_transfer with mode "move". Do not ask the user to move the file by hand and do not improvise with move_onedrive_file, download and upload: file_transfer already retries a locked file and falls back to a copy.
- "Copy a file" → file_transfer with mode "copy".
- Read the file_transfer result before answering. status "moved": the file is now only at the destination. status "copied" with original_remains true: the original is still in place. Say so in one sentence, give the reason (reason "locked": the file is open somewhere; reason "not_owner": it is in someone else's OneDrive; otherwise a plain copy), and tell the user they can remove the original themselves. Gator never deletes files, so never offer to delete it. status "pending": the copy is still running in OneDrive; say so and do not retry. status "failed": report the error in plain words.
- A Teams chat attachment lives in the sender's OneDrive or a SharePoint site, so file_transfer will usually copy it rather than move it. That is expected.
- "Upload a local file" / "save this file to my OneDrive folder" → file_upload with local_path, dest_drive_id and dest_folder_id. It never overwrites; a name clash gets a numeric suffix.
- When the result has a dest, give the user its web_url.
- Always present file names and download URLs to the user.
