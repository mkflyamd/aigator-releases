#!/usr/bin/env python3
"""Create a new OneNote page in a section.

Usage:
    python3 create_page.py --section-id <section_id> --title "Meeting Notes" --body "Notes here..."
    python3 create_page.py --section-id <section_id> --title "Title" --body "<b>HTML</b> content" --html
    python3 create_page.py --section-id <section_id> --title "Title" --body "Content" --json
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a OneNote page")
    parser.add_argument("--section-id", required=True, help="Section ID (from list_sections.py)")
    parser.add_argument("--title", required=True, help="Page title")
    parser.add_argument("--body", required=True, help="Page body content")
    parser.add_argument("--html", action="store_true", help="Body is HTML (default: plain text)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()

    if args.html:
        body_html = args.body
    else:
        body_html = args.body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body_html = body_html.replace("\n", "<br/>")

    page_html = f"""<!DOCTYPE html>
<html>
<head><title>{args.title}</title></head>
<body>{body_html}</body>
</html>"""

    url = f"https://graph.microsoft.com/v1.0/me/onenote/sections/{args.section_id}/pages"
    token = client.get_token()
    req = urllib.request.Request(url, data=page_html.encode("utf-8"), headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/xhtml+xml",
    }, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"ERROR: Failed to create page ({e.code}): {e.read().decode()[:500]}", file=sys.stderr)
        sys.exit(1)

    output = {
        "message": "Page created",
        "title": result.get("title", args.title),
        "id": result.get("id", ""),
        "url": result.get("links", {}).get("oneNoteWebUrl", {}).get("href", ""),
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"Page created: {output['title']}")
        if output["url"]:
            print(f"  URL: {output['url']}")


if __name__ == "__main__":
    main()
