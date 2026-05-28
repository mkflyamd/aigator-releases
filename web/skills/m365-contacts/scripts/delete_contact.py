#!/usr/bin/env python3
"""Delete a personal contact.

Usage:
    python3 delete_contact.py --id <contact_id>
    python3 delete_contact.py --id <contact_id> --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete a contact")
    parser.add_argument("--id", required=True, help="Contact ID (from list_contacts.py)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    client.delete(f"/me/contacts/{args.id}")

    if args.json:
        print(json.dumps({"message": "Contact deleted", "id": args.id}, indent=2))
    else:
        print(f"Contact deleted: {args.id}")


if __name__ == "__main__":
    main()
