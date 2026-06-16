#!/usr/bin/env python3
"""List sections in a OneNote notebook.

Usage:
    python3 list_sections.py --notebook-id <notebook_id>
    python3 list_sections.py --notebook-id <notebook_id> --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="List OneNote sections")
    parser.add_argument("--notebook-id", required=True, help="Notebook ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    data = client.get(f"/me/onenote/notebooks/{args.notebook_id}/sections", params={
        "$select": "id,displayName,createdDateTime",
    })

    sections = [{
        "name": s.get("displayName", ""),
        "id": s.get("id", ""),
        "created": s.get("createdDateTime", "")[:16],
    } for s in data.get("value", [])]

    if args.json:
        print(json.dumps({"total": len(sections), "sections": sections}, indent=2))
    else:
        if not sections:
            print("No sections found.")
            return
        print(f"Sections ({len(sections)}):\n")
        for s in sections:
            print(f"  {s['name']}")
            print(f"    ID: {s['id']}")
            print()


if __name__ == "__main__":
    main()
