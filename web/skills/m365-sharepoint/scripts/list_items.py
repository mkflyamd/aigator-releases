#!/usr/bin/env python3
"""Browse files and folders in a SharePoint document library.

Usage:
    python3 list_items.py --site-id <site_id> --drive-id <drive_id>
    python3 list_items.py --site-id <site_id> --drive-id <drive_id> --path "General/Reports"
    python3 list_items.py --site-id <site_id> --drive-id <drive_id> --json
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
    parser = argparse.ArgumentParser(description="Browse SharePoint document library")
    parser.add_argument("--site-id", required=True, help="Site ID")
    parser.add_argument("--drive-id", required=True, help="Drive ID (from list_drives.py)")
    parser.add_argument("--path", default="", help="Folder path (default: root)")
    parser.add_argument("--count", type=int, default=50, help="Max items (default: 50)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()

    if args.path:
        api_path = f"/sites/{args.site_id}/drives/{args.drive_id}/root:/{args.path}:/children"
    else:
        api_path = f"/sites/{args.site_id}/drives/{args.drive_id}/root/children"

    data = client.get(api_path, params={
        "$top": str(args.count),
        "$orderby": "name",
        "$select": "name,size,lastModifiedDateTime,folder,file,webUrl,id",
    })

    items = []
    for item in data.get("value", []):
        is_folder = "folder" in item
        items.append({
            "name": item.get("name", ""),
            "type": "folder" if is_folder else "file",
            "size": item.get("size", 0),
            "modified": item.get("lastModifiedDateTime", "")[:16],
            "url": item.get("webUrl", ""),
            "id": item.get("id", ""),
        })

    if args.json:
        print(json.dumps({"path": args.path or "/", "total": len(items), "items": items}, indent=2))
    else:
        label = args.path or "/"
        if not items:
            print(f"No items in '{label}'.")
            return
        print(f"SharePoint: {label} ({len(items)} items)\n")
        for item in items:
            if item["type"] == "folder":
                print(f"  [DIR]  {item['name']}/")
            else:
                print(f"  [FILE] {item['name']}  ({format_size(item['size'])})")
            print(f"         Modified: {item['modified']}")


if __name__ == "__main__":
    main()
