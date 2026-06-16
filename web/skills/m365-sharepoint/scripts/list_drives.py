#!/usr/bin/env python3
"""List document libraries (drives) in a SharePoint site.

Usage:
    python3 list_drives.py --site-id <site_id>
    python3 list_drives.py --site-id <site_id> --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="List document libraries in a SharePoint site")
    parser.add_argument("--site-id", required=True, help="Site ID (from list_sites.py or search_sites.py)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    data = client.get(f"/sites/{args.site_id}/drives")

    drives = [{
        "name": d.get("name", ""),
        "description": d.get("description", ""),
        "url": d.get("webUrl", ""),
        "id": d.get("id", ""),
        "total_size": d.get("quota", {}).get("total", 0),
        "used_size": d.get("quota", {}).get("used", 0),
    } for d in data.get("value", [])]

    if args.json:
        print(json.dumps({"total": len(drives), "drives": drives}, indent=2))
    else:
        if not drives:
            print("No document libraries found.")
            return
        print(f"Document Libraries ({len(drives)}):\n")
        for d in drives:
            print(f"  {d['name']}")
            if d["description"]:
                print(f"    {d['description'][:80]}")
            print(f"    ID:  {d['id']}")
            print(f"    URL: {d['url']}")
            print()


if __name__ == "__main__":
    main()
