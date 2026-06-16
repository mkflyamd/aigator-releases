#!/usr/bin/env python3
"""Search for SharePoint sites by name.

Usage:
    python3 search_sites.py "firmware"
    python3 search_sites.py "PLM" --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Search SharePoint sites")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--count", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    data = client.get("/sites", params={
        "search": args.query,
        "$top": str(args.count),
    })

    sites = [{
        "name": s.get("displayName", ""),
        "url": s.get("webUrl", ""),
        "description": s.get("description", ""),
        "id": s.get("id", ""),
    } for s in data.get("value", [])]

    if args.json:
        print(json.dumps({"query": args.query, "total": len(sites), "sites": sites}, indent=2))
    else:
        if not sites:
            print(f"No sites found for '{args.query}'.")
            return
        print(f"Sites matching '{args.query}' ({len(sites)}):\n")
        for s in sites:
            print(f"  {s['name']}")
            if s["description"]:
                print(f"    {s['description'][:80]}")
            print(f"    URL: {s['url']}")
            print(f"    ID:  {s['id']}")
            print()


if __name__ == "__main__":
    main()
