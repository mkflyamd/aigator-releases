---
name: sharepoint
description: "Microsoft SharePoint — search sites, browse drives, list files."
metadata:
  author: Mayuresh Kulkarni
  version: "1.0"
  format: agentskills-1.0
---

# SharePoint Workflow

- "Find a SharePoint site" → call search_sharepoint_sites with a keyword.
- "Browse a site's files" → call list_sharepoint_sites to get site_id, list_sharepoint_drives to get drive_id, then list_sharepoint_files.
