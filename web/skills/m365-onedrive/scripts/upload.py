#!/usr/bin/env python3
"""Upload a file to OneDrive.

For files <= 4MB, uses simple upload. For larger files, uses upload session
with chunked upload (supports files up to several GB).

Usage:
    python3 upload.py --file ./report.pdf --dest "Documents/report.pdf"
    python3 upload.py --file ./data.csv --dest "Projects/Results/data.csv"
    python3 upload.py --file ./image.png --dest "Pictures/image.png" --json
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient

# Files <= 4MB use simple PUT; larger files use upload session
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB chunks for upload sessions


def simple_upload(client: GraphClient, local_path: str, dest_path: str) -> dict:
    """Upload small file (<= 4MB) with a single PUT."""
    with open(local_path, "rb") as f:
        data = f.read()

    url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{dest_path}:/content"
    headers = client._headers()
    headers["Content-Type"] = "application/octet-stream"
    req = urllib.request.Request(url, data=data, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"ERROR: Upload failed ({e.code}): {e.read().decode()[:500]}", file=sys.stderr)
        sys.exit(1)


def chunked_upload(client: GraphClient, local_path: str, dest_path: str) -> dict:
    """Upload large file using an upload session with chunked PUT."""
    # Create upload session
    session_url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{dest_path}:/createUploadSession"
    session_body = json.dumps({"item": {"@microsoft.graph.conflictBehavior": "replace"}}).encode()
    headers = client._headers()
    req = urllib.request.Request(session_url, data=session_body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            session = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"ERROR: Failed to create upload session ({e.code}): {e.read().decode()[:500]}", file=sys.stderr)
        sys.exit(1)

    upload_url = session["uploadUrl"]
    file_size = os.path.getsize(local_path)

    with open(local_path, "rb") as f:
        offset = 0
        while offset < file_size:
            chunk = f.read(CHUNK_SIZE)
            chunk_end = offset + len(chunk) - 1
            chunk_headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {offset}-{chunk_end}/{file_size}",
            }
            req = urllib.request.Request(upload_url, data=chunk, headers=chunk_headers, method="PUT")
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read())
                    if "id" in result:
                        return result  # Upload complete
            except urllib.error.HTTPError as e:
                print(f"ERROR: Chunk upload failed at offset {offset} ({e.code}): {e.read().decode()[:300]}", file=sys.stderr)
                sys.exit(1)
            offset += len(chunk)

    return {"error": "Upload completed but no final response received"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a file to OneDrive")
    parser.add_argument("--file", "-f", required=True, help="Local file to upload")
    parser.add_argument("--dest", "-d", required=True, help="Destination path in OneDrive (e.g., Documents/file.pdf)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    local_path = args.file
    if not os.path.isfile(local_path):
        print(f"ERROR: File not found: {local_path}", file=sys.stderr)
        sys.exit(1)

    file_size = os.path.getsize(local_path)
    client = GraphClient()

    if file_size <= SIMPLE_UPLOAD_LIMIT:
        result = simple_upload(client, local_path, args.dest)
    else:
        result = chunked_upload(client, local_path, args.dest)

    output = {
        "message": "Uploaded",
        "name": result.get("name", ""),
        "dest": args.dest,
        "size": result.get("size", file_size),
        "url": result.get("webUrl", ""),
        "id": result.get("id", ""),
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"Uploaded: {Path(local_path).name} -> {args.dest}")
        print(f"  Size: {output['size']:,} bytes")
        if output["url"]:
            print(f"  URL: {output['url']}")


if __name__ == "__main__":
    main()
