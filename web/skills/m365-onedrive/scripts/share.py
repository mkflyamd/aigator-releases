#!/usr/bin/env python3
"""Create a sharing link for a OneDrive file.

Usage:
    python3 share.py --path "Documents/report.pdf"
    python3 share.py --path "Documents/report.pdf" --edit
    python3 share.py --id <item-id>
    python3 share.py --path "Documents/report.pdf" --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a sharing link for a OneDrive file")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--path", help="File path in OneDrive")
    group.add_argument("--id", help="Item ID")
    parser.add_argument("--edit", action="store_true", help="Create an edit link (default: view-only)")
    parser.add_argument("--org", action="store_true", help="Restrict to organization (default: anyone)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()

    if args.path:
        api_path = f"/me/drive/root:/{args.path}:/createLink"
    else:
        api_path = f"/me/drive/items/{args.id}/createLink"

    link_type = "edit" if args.edit else "view"
    scope = "organization" if args.org else "anonymous"

    result = client.post(api_path, {
        "type": link_type,
        "scope": scope,
    })

    link = result.get("link", {})
    output = {
        "message": "Sharing link created",
        "url": link.get("webUrl", ""),
        "type": link_type,
        "scope": scope,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"Sharing link ({link_type}, {scope}):")
        print(f"  {output['url']}")


if __name__ == "__main__":
    main()
