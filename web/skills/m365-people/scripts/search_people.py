#!/usr/bin/env python3
"""Search for coworkers by name or email.

Usage:
    python3 search_people.py "Tanmay Shah"
    python3 search_people.py "kumar" --count 10
    python3 search_people.py "tanmay.shah@example.com"
    python3 search_people.py "Tanmay" --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Search for coworkers")
    parser.add_argument("query", help="Name or email to search")
    parser.add_argument("--count", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    data = client.get("/me/people", params={"$search": f'"{ args.query}"', "$top": str(args.count)})
    people = [{
        "name": p.get("displayName", ""),
        "email": p.get("scoredEmailAddresses", [{}])[0].get("address", "") if p.get("scoredEmailAddresses") else "",
        "job_title": p.get("jobTitle", ""),
        "department": p.get("department", ""),
        "office": p.get("officeLocation", ""),
        "id": p.get("id", ""),
    } for p in data.get("value", [])]

    if args.json:
        print(json.dumps({"total": len(people), "people": people}, indent=2))
    else:
        if not people:
            print(f"No results for '{args.query}'.")
            return
        print(f"Results for '{args.query}' ({len(people)}):\n")
        for p in people:
            print(f"  {p['name']}")
            if p['job_title']: print(f"    Title: {p['job_title']}")
            if p['department']: print(f"    Dept:  {p['department']}")
            if p['email']: print(f"    Email: {p['email']}")
            if p['office']: print(f"    Office: {p['office']}")
            print()


if __name__ == "__main__":
    main()
