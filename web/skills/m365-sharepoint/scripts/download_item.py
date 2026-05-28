#!/usr/bin/env python3
"""Download a file from a SharePoint document library.

Usage:
    python3 download_item.py --site-id <site_id> --drive-id <drive_id> --path "General/report.pdf"
    python3 download_item.py --site-id <site_id> --drive-id <drive_id> --item-id <item_id>
    python3 download_item.py --site-id <site_id> --drive-id <drive_id> --path "file.pdf" --output /tmp/file.pdf
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Download a file from SharePoint")
    parser.add_argument("--site-id", required=True, help="Site ID")
    parser.add_argument("--drive-id", required=True, help="Drive ID")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--path", help="File path in the drive")
    group.add_argument("--item-id", help="Item ID")
    parser.add_argument("--output", "-o", help="Local output path (default: filename in current dir)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()

    if args.path:
        meta = client.get(f"/sites/{args.site_id}/drives/{args.drive_id}/root:/{args.path}")
    else:
        meta = client.get(f"/sites/{args.site_id}/drives/{args.drive_id}/items/{args.item_id}")

    download_url = meta.get("@microsoft.graph.downloadUrl", "")
    if not download_url:
        print("ERROR: Could not get download URL.", file=sys.stderr)
        sys.exit(1)

    filename = meta.get("name", "download")
    output_path = args.output or filename

    req = urllib.request.Request(download_url, method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(output_path, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)

    file_size = os.path.getsize(output_path)

    if args.json:
        print(json.dumps({"message": "Downloaded", "name": filename,
                          "output": str(Path(output_path).resolve()), "size": file_size}, indent=2))
    else:
        print(f"Downloaded: {filename}")
        print(f"  Saved to: {Path(output_path).resolve()}")
        print(f"  Size: {file_size:,} bytes")


if __name__ == "__main__":
    main()
