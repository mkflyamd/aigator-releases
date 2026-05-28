#!/usr/bin/env python3
"""Search OneDrive files by name or content.

Usage:
    python3 search_files.py "quarterly report"
    python3 search_files.py "budget" --count 20
    python3 search_files.py "meeting notes" --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(description="Search OneDrive files")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--count", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    data = client.get(f"/me/drive/root/search(q='{args.query}')", params={
        "$top": str(args.count),
        "$select": "name,size,lastModifiedDateTime,parentReference,webUrl,id",
    })

    items = []
    for item in data.get("value", []):
        parent = item.get("parentReference", {})
        parent_path = parent.get("path", "").replace("/drive/root:", "", 1).lstrip("/")
        items.append({
            "name": item.get("name", ""),
            "path": f"{parent_path}/{item.get('name', '')}" if parent_path else item.get("name", ""),
            "size": item.get("size", 0),
            "modified": item.get("lastModifiedDateTime", "")[:16],
            "url": item.get("webUrl", ""),
            "id": item.get("id", ""),
        })

    if args.json:
        print(json.dumps({"query": args.query, "total": len(items), "items": items}, indent=2))
    else:
        if not items:
            print(f"No results for '{args.query}'.")
            return
        print(f"Search results for '{args.query}' ({len(items)}):\n")
        for item in items:
            print(f"  {item['path']}  ({format_size(item['size'])})")
            print(f"    Modified: {item['modified']}")
            print()


if __name__ == "__main__":
    main()
