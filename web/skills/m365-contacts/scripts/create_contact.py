#!/usr/bin/env python3
"""Create a new personal contact.

Usage:
    python3 create_contact.py --name "Alice Smith" --email "alice@example.com"
    python3 create_contact.py --name "Bob" --email "bob@example.com" --phone "+1-555-0123"
    python3 create_contact.py --name "Carol" --email "carol@example.com" --company "Acme" --title "Engineer" --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a personal contact")
    parser.add_argument("--name", required=True, help="Display name")
    parser.add_argument("--email", help="Email address")
    parser.add_argument("--phone", help="Business phone")
    parser.add_argument("--mobile", help="Mobile phone")
    parser.add_argument("--company", help="Company name")
    parser.add_argument("--title", help="Job title")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Split name into first/last
    parts = args.name.rsplit(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""

    contact = {
        "displayName": args.name,
        "givenName": first_name,
        "surname": last_name,
    }

    if args.email:
        contact["emailAddresses"] = [{"address": args.email, "name": args.name}]
    if args.phone:
        contact["businessPhones"] = [args.phone]
    if args.mobile:
        contact["mobilePhone"] = args.mobile
    if args.company:
        contact["companyName"] = args.company
    if args.title:
        contact["jobTitle"] = args.title

    client = GraphClient()
    result = client.post("/me/contacts", contact)

    output = {
        "message": "Contact created",
        "name": result.get("displayName", args.name),
        "id": result.get("id", ""),
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"Contact created: {output['name']}")


if __name__ == "__main__":
    main()
