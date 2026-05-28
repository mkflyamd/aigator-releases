#!/usr/bin/env python3
"""List pages in a OneNote section.

Usage:
    python3 list_pages.py --section-id <section_id>
    python3 list_pages.py --section-id <section_id> --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="List OneNote pages")
    parser.add_argument("--section-id", required=True, help="Section ID")
    parser.add_argument("--count", type=int, default=50, help="Max pages (default: 50)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    data = client.get(f"/me/onenote/sections/{args.section_id}/pages", params={
        "$top": str(args.count),
        "$orderby": "lastModifiedDateTime desc",
        "$select": "id,title,createdDateTime,lastModifiedDateTime,links",
    })

    pages = [{
        "title": p.get("title", "(untitled)"),
        "id": p.get("id", ""),
        "modified": p.get("lastModifiedDateTime", "")[:16],
        "url": p.get("links", {}).get("oneNoteWebUrl", {}).get("href", ""),
    } for p in data.get("value", [])]

    if args.json:
        print(json.dumps({"total": len(pages), "pages": pages}, indent=2))
    else:
        if not pages:
            print("No pages found.")
            return
        print(f"Pages ({len(pages)}):\n")
        for p in pages:
            print(f"  {p['title']}")
            print(f"    Modified: {p['modified']}")
            print(f"    ID: {p['id']}")
            print()


if __name__ == "__main__":
    main()
