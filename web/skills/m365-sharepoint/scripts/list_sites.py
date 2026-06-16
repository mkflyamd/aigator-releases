#!/usr/bin/env python3
"""List SharePoint sites the user follows or has access to.

Usage:
    python3 list_sites.py
    python3 list_sites.py --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="List SharePoint sites")
    parser.add_argument("--count", type=int, default=50, help="Max results (default: 50)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    data = client.get("/me/followedSites", params={"$top": str(args.count)})

    sites = [{
        "name": s.get("displayName", ""),
        "url": s.get("webUrl", ""),
        "description": s.get("description", ""),
        "id": s.get("id", ""),
    } for s in data.get("value", [])]

    if args.json:
        print(json.dumps({"total": len(sites), "sites": sites}, indent=2))
    else:
        if not sites:
            print("No followed sites found. Try search_sites.py to find sites.")
            return
        print(f"Followed Sites ({len(sites)}):\n")
        for s in sites:
            print(f"  {s['name']}")
            if s["description"]:
                print(f"    {s['description'][:80]}")
            print(f"    URL: {s['url']}")
            print(f"    ID:  {s['id']}")
            print()


if __name__ == "__main__":
    main()
