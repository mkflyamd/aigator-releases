#!/usr/bin/env python3
"""List OneNote notebooks.

Usage:
    python3 list_notebooks.py
    python3 list_notebooks.py --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="List OneNote notebooks")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    data = client.get("/me/onenote/notebooks", params={
        "$orderby": "displayName",
        "$select": "id,displayName,createdDateTime,lastModifiedDateTime,links",
    })

    notebooks = [{
        "name": n.get("displayName", ""),
        "id": n.get("id", ""),
        "modified": n.get("lastModifiedDateTime", "")[:16],
        "url": n.get("links", {}).get("oneNoteWebUrl", {}).get("href", ""),
    } for n in data.get("value", [])]

    if args.json:
        print(json.dumps({"total": len(notebooks), "notebooks": notebooks}, indent=2))
    else:
        if not notebooks:
            print("No notebooks found.")
            return
        print(f"Notebooks ({len(notebooks)}):\n")
        for n in notebooks:
            print(f"  {n['name']}")
            print(f"    Modified: {n['modified']}")
            print(f"    ID: {n['id']}")
            print()


if __name__ == "__main__":
    main()
