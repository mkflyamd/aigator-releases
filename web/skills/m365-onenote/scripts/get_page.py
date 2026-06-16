#!/usr/bin/env python3
"""Read a OneNote page's content.

Usage:
    python3 get_page.py --page-id <page_id>
    python3 get_page.py --page-id <page_id> --json
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def html_to_text(html: str) -> str:
    """Basic HTML to plain text conversion."""
    text = re.sub(r'<br\s*/?>', '\n', html)
    text = re.sub(r'</(p|div|h[1-6]|li|tr)>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&nbsp;', ' ')
    return text.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read a OneNote page")
    parser.add_argument("--page-id", required=True, help="Page ID")
    parser.add_argument("--html", action="store_true", help="Output raw HTML instead of text")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()

    # Get page metadata
    meta = client.get(f"/me/onenote/pages/{args.page_id}", params={
        "$select": "id,title,createdDateTime,lastModifiedDateTime",
    })

    # Get page content (HTML)
    token = client.get_token()
    url = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{args.page_id}/content"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "text/html",
    }, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html_content = resp.read().decode("utf-8")
    except Exception as e:
        print(f"ERROR: Failed to get page content: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps({
            "title": meta.get("title", ""),
            "id": meta.get("id", ""),
            "modified": meta.get("lastModifiedDateTime", "")[:16],
            "content": html_content if args.html else html_to_text(html_content),
        }, indent=2))
    elif args.html:
        print(html_content)
    else:
        title = meta.get("title", "(untitled)")
        print(f"# {title}\n")
        print(html_to_text(html_content))


if __name__ == "__main__":
    main()
