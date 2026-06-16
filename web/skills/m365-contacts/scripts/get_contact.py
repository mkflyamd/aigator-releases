#!/usr/bin/env python3
"""Get full details of a personal contact.

Usage:
    python3 get_contact.py --id <contact_id>
    python3 get_contact.py --id <contact_id> --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Get contact details")
    parser.add_argument("--id", required=True, help="Contact ID (from list_contacts.py)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    c = client.get(f"/me/contacts/{args.id}")

    contact = {
        "name": c.get("displayName", ""),
        "first_name": c.get("givenName", ""),
        "last_name": c.get("surname", ""),
        "emails": [e.get("address", "") for e in c.get("emailAddresses", [])],
        "phones": c.get("businessPhones", []),
        "mobile": c.get("mobilePhone", ""),
        "home_phones": c.get("homePhones", []),
        "company": c.get("companyName", ""),
        "title": c.get("jobTitle", ""),
        "department": c.get("department", ""),
        "office": c.get("officeLocation", ""),
        "birthday": c.get("birthday", ""),
        "notes": c.get("personalNotes", ""),
        "id": c.get("id", ""),
    }

    if args.json:
        print(json.dumps(contact, indent=2))
    else:
        for k, v in contact.items():
            if v and v != []:
                label = k.replace("_", " ").title()
                if isinstance(v, list):
                    v = ", ".join(v)
                print(f"{label:14s} {v}")


if __name__ == "__main__":
    main()
