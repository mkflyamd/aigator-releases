---
description: 'Download and visually analyze images from Confluence pages, emails, Teams messages, or OneNote pages.'
---

# fetch_image skill

Use the `fetch_image` tool to download images from documents and messages so you can visually analyze them.

## IMPORTANT — do NOT write code to fetch images

When you see `[image: filename]` or `[image](url)` in content you have read, or when the user asks you to explain/describe/view an image:

1. Call `fetch_image` directly — it handles authentication for Confluence, Graph API, Teams, and OneNote automatically.
2. Do NOT use `run_python`, `requests`, `httpx`, or any other code to download images. Code runners do not have the correct SSL certificates or authentication tokens that `fetch_image` has.
3. After `fetch_image` returns a `file_path`, call `describe_images` with task="extract_data" for charts, tables, screenshots, or benchmark results — this extracts actual numbers, axis labels, and values rather than just describing the visual. Use task="describe" only for photographs or diagrams with no numeric content.

## For Confluence attachments

Call `fetch_image(page_id="<id>", filename="<name>.png")`.
The page_id is the numeric Confluence page ID (e.g. `1750622036`).
The filename is the attachment filename from the `[image: filename]` placeholder.

## For direct image URLs

Call `fetch_image(url="https://...")`.
