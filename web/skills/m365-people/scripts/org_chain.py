#!/usr/bin/env python3
"""Show manager chain / org hierarchy.

Usage:
    python3 org_chain.py                              # Your org chain
    python3 org_chain.py --user tanmay.shah@example.com   # Someone's org chain
    python3 org_chain.py --depth 5                    # Up to 5 levels
    python3 org_chain.py --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def get_org_chain(client: GraphClient, user_path: str, depth: int) -> list[dict]:
    """Walk up the manager chain."""
    chain = []
    current_path = user_path
    for _ in range(depth):
        try:
            mgr = client.get(f"{current_path}/manager")
            entry = {
                "name": mgr.get("displayName", ""),
                "email": mgr.get("mail", "") or mgr.get("userPrincipalName", ""),
                "job_title": mgr.get("jobTitle", ""),
                "id": mgr.get("id", ""),
            }
            chain.append(entry)
            mgr_id = mgr.get("id", "")
            if not mgr_id:
                break
            current_path = f"/users/{mgr_id}"
        except SystemExit:
            break
    return chain


def main() -> None:
    parser = argparse.ArgumentParser(description="Show org chain")
    parser.add_argument("--user", help="User email or ID (default: yourself)")
    parser.add_argument("--depth", type=int, default=5, help="Max levels up (default: 5)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()

    if args.user:
        user_path = f"/users/{args.user}"
        user = client.get(user_path)
    else:
        user_path = "/me"
        user = client.get("/me")

    user_info = {
        "name": user.get("displayName", ""),
        "email": user.get("mail", "") or user.get("userPrincipalName", ""),
        "job_title": user.get("jobTitle", ""),
    }

    chain = get_org_chain(client, user_path, args.depth)

    if args.json:
        print(json.dumps({"user": user_info, "managers": chain}, indent=2))
    else:
        print(f"{user_info['name']} ({user_info['job_title']})")
        for i, mgr in enumerate(chain):
            indent = "  " * (i + 1) + "-> "
            print(f"{indent}{mgr['name']} ({mgr['job_title']})")
            if mgr['email']:
                print(f"{' ' * (len(indent))}{mgr['email']}")


if __name__ == "__main__":
    main()
