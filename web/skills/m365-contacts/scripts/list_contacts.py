#!/usr/bin/env python3
"""List or search personal Outlook contacts.

Usage:
    python3 list_contacts.py
    python3 list_contacts.py --search "Alice"
    python3 list_contacts.py --count 20 --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="List personal contacts")
    parser.add_argument("--search", help="Filter contacts by name")
    parser.add_argument("--count", type=int, default=50, help="Max results (default: 50)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()

    params = {
        "$top": str(args.count),
        "$orderby": "displayName",
        "$select": "id,displayName,emailAddresses,businessPhones,mobilePhone,companyName,jobTitle",
    }
    if args.search:
        params["$filter"] = f"startswith(displayName,'{args.search}') or startswith(givenName,'{args.search}') or startswith(surname,'{args.search}')"

    data = client.get("/me/contacts", params=params)

    contacts = [{
        "name": c.get("displayName", ""),
        "email": c.get("emailAddresses", [{}])[0].get("address", "") if c.get("emailAddresses") else "",
        "phone": c.get("businessPhones", [""])[0] if c.get("businessPhones") else "",
        "mobile": c.get("mobilePhone", ""),
        "company": c.get("companyName", ""),
        "title": c.get("jobTitle", ""),
        "id": c.get("id", ""),
    } for c in data.get("value", [])]

    if args.json:
        print(json.dumps({"total": len(contacts), "contacts": contacts}, indent=2))
    else:
        if not contacts:
            print("No contacts found." + (" Try without --search." if args.search else ""))
            return
        print(f"Contacts ({len(contacts)}):\n")
        for c in contacts:
            print(f"  {c['name']}")
            if c["email"]:
                print(f"    Email:  {c['email']}")
            if c["phone"]:
                print(f"    Phone:  {c['phone']}")
            if c["mobile"]:
                print(f"    Mobile: {c['mobile']}")
            if c["company"]:
                print(f"    Company: {c['company']}")
            print()


if __name__ == "__main__":
    main()
