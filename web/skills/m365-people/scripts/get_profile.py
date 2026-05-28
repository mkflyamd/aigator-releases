#!/usr/bin/env python3
"""Get a user's full profile from Microsoft Graph.

Usage:
    python3 get_profile.py                             # Your own profile
    python3 get_profile.py --email tanmay.shah@example.com  # By email
    python3 get_profile.py --id <user-id>               # By user ID
    python3 get_profile.py --email user@example.com --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Get user profile")
    parser.add_argument("--email", help="User email (UPN)")
    parser.add_argument("--id", help="User ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()

    if args.email:
        path = f"/users/{args.email}"
    elif args.id:
        path = f"/users/{args.id}"
    else:
        path = "/me"

    user = client.get(path)
    profile = {
        "name": user.get("displayName", ""),
        "email": user.get("mail", "") or user.get("userPrincipalName", ""),
        "job_title": user.get("jobTitle", ""),
        "department": user.get("department", ""),
        "office": user.get("officeLocation", ""),
        "phone": user.get("businessPhones", [""])[0] if user.get("businessPhones") else "",
        "mobile": user.get("mobilePhone", ""),
        "city": user.get("city", ""),
        "country": user.get("country", ""),
        "id": user.get("id", ""),
    }

    if args.json:
        print(json.dumps(profile, indent=2))
    else:
        for k, v in profile.items():
            if v:
                print(f"{k.replace('_',' ').title():12s} {v}")


if __name__ == "__main__":
    main()
